import getpass
import importlib.util
import io
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models.admin_account import AdminAccount, AdminSession
from app.models.audit_log import AuditLog
from app.services import auth_service, password_service

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a brand new long password"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load("create_super_admin")
secret_tool = load("create_jwt_secret")


class Console:
    # Stands for the terminal: answers the questions in order and keeps everything that was shown.
    def __init__(self, typed=(), hidden=()):
        self.typed, self.hidden = list(typed), list(hidden)
        self.questions, self.lines = [], []

    def ask(self, question):
        self.questions.append(question)
        return self.typed.pop(0)

    def ask_hidden(self, question):
        self.questions.append(question)
        return self.hidden.pop(0)

    def say(self, line):
        self.lines.append(line)

    @property
    def shown(self):
        return "\n".join(self.questions + self.lines)


def run(db, console, force=False):
    return tool.run(db, force, console.ask, console.ask_hidden, console.say, "the test database")


def accounts(db):
    db.expire_all()
    return [(account.email, account.role, account.status) for account in db.query(AdminAccount).order_by(AdminAccount.id)]


def first_super_admin(db, email="owner@example.com", password=PASSWORD):
    assert run(db, Console([email, "Sample Owner"], [password, password])) == 0


# ---- creating -----------------------------------------------------------------------------------

def test_it_creates_exactly_one_super_admin_from_what_is_typed(db_session):
    console = Console(["  Owner@Example.com ", "  Sample   Owner "], [PASSWORD, PASSWORD])

    assert run(db_session, console) == 0

    saved = db_session.query(AdminAccount).one()
    assert (saved.email, saved.full_name, saved.role, saved.status) == ("owner@example.com", "Sample Owner", "super_admin", "active")
    # The person typed this password themselves, so there is nothing to force a change of.
    assert (saved.must_change_password, saved.failed_login_count, saved.created_by) == (False, 0, None)
    assert saved.password_hash.startswith("$argon2id$") and password_service.verify_password(saved.password_hash, PASSWORD)
    assert console.lines[-1] == "Super admin created: owner@example.com"
    assert "the test database" in console.lines[0]


def test_the_account_it_creates_can_log_in(backend, anon_client):
    with backend.db() as db:
        first_super_admin(db)

    answer = anon_client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})

    assert answer.status_code == 200
    assert answer.json()["data"]["account"]["role"] == "super_admin"


def test_the_password_is_asked_for_hidden_and_never_shown(db_session):
    console = Console(["owner@example.com", "Sample Owner"], [PASSWORD, PASSWORD])
    run(db_session, console)

    assert PASSWORD not in console.shown and "argon2" not in console.shown
    # Both password questions went through the hidden prompt, none through the visible one.
    assert console.questions == ["Email: ", "Full name: ", "Password (at least 10 characters; what you type is not shown): ", "The same password again: "]
    assert console.hidden == [] and console.typed == []


def test_it_refuses_when_a_super_admin_exists_and_asks_nothing(db_session):
    first_super_admin(db_session)
    console = Console()

    assert run(db_session, console) == 1

    assert console.questions == []
    assert "A super admin already exists (1 in all). Nothing was changed." in console.lines
    assert "--force" in console.shown
    assert accounts(db_session) == [("owner@example.com", "super_admin", "active")]


def test_an_ordinary_admin_does_not_count_as_a_super_admin(db_session, make_account):
    make_account(db_session, "admin@example.com", PASSWORD)

    first_super_admin(db_session)

    assert accounts(db_session) == [("admin@example.com", "admin", "active"), ("owner@example.com", "super_admin", "active")]


def test_force_adds_another_super_admin(db_session):
    first_super_admin(db_session)

    assert run(db_session, Console(["second@example.com", "Second Owner"], [NEW_PASSWORD, NEW_PASSWORD]), force=True) == 0

    assert accounts(db_session) == [("owner@example.com", "super_admin", "active"), ("second@example.com", "super_admin", "active")]


@pytest.mark.parametrize("typed", ["not an email", "", "owner@", "a" * 115 + "@example.com"])
def test_an_email_that_is_not_one_stops_it(db_session, typed):
    console = Console([typed])

    assert run(db_session, console) == 1
    assert console.lines[-1].endswith("Nothing was changed.") and accounts(db_session) == []


def test_a_password_that_breaks_the_rules_is_asked_for_again(db_session):
    console = Console(["owner@example.com", "Sample Owner"], ["too short", "qwertyuiop", PASSWORD, PASSWORD])

    assert run(db_session, console) == 0

    assert "Password must have at least 10 characters." in console.lines
    assert "This password is one of the most commonly used. Choose another one." in console.lines
    assert "too short" not in console.shown and "qwertyuiop" not in console.shown
    assert password_service.verify_password(db_session.query(AdminAccount).one().password_hash, PASSWORD)


def test_two_different_passwords_are_asked_for_again(db_session):
    console = Console(["owner@example.com", "Sample Owner"], [PASSWORD, PASSWORD + "x", PASSWORD, PASSWORD])

    assert run(db_session, console) == 0
    assert "The two passwords are not the same." in console.lines


def test_after_three_refused_passwords_nothing_is_created(db_session):
    console = Console(["owner@example.com", "Sample Owner"], ["short", "owner@example.com", "1234567890"])

    assert run(db_session, console) == 1
    assert console.lines[-1] == "No password was accepted. Nothing was changed." and accounts(db_session) == []


def test_what_the_tool_does_is_written_to_the_audit_log_without_a_password(db_session):
    first_super_admin(db_session)
    console = Console(["owner@example.com", "owner@example.com"], [NEW_PASSWORD, NEW_PASSWORD])
    assert run(db_session, console, force=True) == 0
    assert run(db_session, Console(["not-an-email"]), force=True) == 1  # refused: nothing to record

    owner = db_session.query(AdminAccount).one().id
    rows = [(row.action, row.actor_id, row.target_type, row.target_id, row.details) for row in db_session.query(AuditLog).order_by(AuditLog.id)]
    # Nobody is logged in when the tool runs on the server, so no account is named as the actor.
    assert rows == [
        ("admin.created", None, "admin_account", owner, {"via": "command line", "email": "owner@example.com", "role": "super_admin"}),
        ("admin.password_reset", None, "admin_account", owner, {"via": "command line"}),
    ]
    assert PASSWORD not in str(rows) and NEW_PASSWORD not in str(rows)


def test_a_password_set_with_the_tool_is_chosen_by_its_owner_and_does_not_run_out(db_session):
    # The tool is the way to recover a super admin: the person at the server types the password
    # themselves, so it is neither temporary nor shown to anyone else.
    first_super_admin(db_session)
    run(db_session, Console(["owner@example.com", "owner@example.com"], [NEW_PASSWORD, NEW_PASSWORD]), force=True)

    db_session.expire_all()
    account = db_session.query(AdminAccount).one()
    assert (account.must_change_password, account.temporary_password_expires_at) == (False, None)


# ---- --force on an account that exists ----------------------------------------------------------

def test_force_replaces_the_password_of_an_existing_super_admin_after_the_email_is_typed_again(backend):
    with backend.db() as db:
        first_super_admin(db)
    laptop = backend()
    token = {"Authorization": f"Bearer {laptop.post('/auth/login', json={'email': 'owner@example.com', 'password': PASSWORD}).json()['data']['access_token']}"}
    assert laptop.get("/courses", headers=token).status_code == 200

    with backend.db() as db:
        # Locked out and disabled: the state this command exists to get someone out of.
        owner = db.query(AdminAccount).one()
        owner.status, owner.failed_login_count, owner.locked_until = "disabled", 5, auth_service.clock() + timedelta(minutes=10)
        db.commit()
        console = Console(["Owner@Example.com", "owner@example.com"], [NEW_PASSWORD, NEW_PASSWORD])

        assert run(db, console, force=True) == 0

        assert console.lines[-1] == "The password of super admin owner@example.com was replaced."
        # It says what is about to happen before asking, and does not ask for a name it already has.
        assert "replaces its password, unlocks and enables it, and logs it out on every device" in console.shown
        assert "Full name: " not in console.questions and "Type the email again to confirm: " in console.questions
        assert NEW_PASSWORD not in console.shown
        saved = db.query(AdminAccount).one()
        assert (saved.full_name, saved.role, saved.status, saved.failed_login_count, saved.locked_until) == ("Sample Owner", "super_admin", "active", 0, None)
        assert db.query(AdminSession).count() == 1 and all(session.revoked_at is not None for session in db.query(AdminSession))

    # The login that was open is over, the old password is dead and the new one works.
    assert laptop.get("/courses", headers=token).status_code == 401
    assert backend().post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 401
    assert backend().post("/auth/login", json={"email": "owner@example.com", "password": NEW_PASSWORD}).status_code == 200


@pytest.mark.parametrize("confirmation", ["", "yes", "owner@example.co", "other@example.com"])
def test_force_changes_nothing_unless_the_same_email_is_typed_again(db_session, confirmation):
    first_super_admin(db_session)
    before = db_session.query(AdminAccount).one().password_hash
    console = Console(["owner@example.com", confirmation])

    assert run(db_session, console, force=True) == 1

    assert console.lines[-1] == "That is not the same email. Nothing was changed."
    # The password was never asked for.
    assert not any("assword" in question for question in console.questions)
    db_session.expire_all()
    assert db_session.query(AdminAccount).one().password_hash == before


def test_a_super_admin_made_in_the_portal_whose_temporary_password_ran_out_is_recovered_here(db_session, monkeypatch):
    # The portal never resets such an account (it is a super admin); this is the way back in that
    # the expired-password message names.
    from app.services import admin_service
    from app.services.auth_service import Actor, AuthError

    first_super_admin(db_session)
    owner = db_session.query(AdminAccount).filter_by(email="owner@example.com").one()
    new, temporary = admin_service.create(db_session, Actor(owner.id, owner.email, owner.full_name, "super_admin", False, 1),
                                          "new.owner@example.com", "New Owner", role="super_admin")
    later = auth_service.clock() + timedelta(hours=73)
    monkeypatch.setattr(auth_service, "clock", lambda: later)
    with pytest.raises(AuthError) as expired:
        auth_service.login(db_session, "new.owner@example.com", temporary, "test")
    assert expired.value.status == 403 and "create_super_admin.py --force" in expired.value.message
    console = Console(["new.owner@example.com", "new.owner@example.com"], [NEW_PASSWORD, NEW_PASSWORD])

    assert run(db_session, console, force=True) == 0

    db_session.expire_all()
    account = db_session.get(AdminAccount, new.id)
    assert (account.role, account.must_change_password, account.temporary_password_expires_at) == ("super_admin", False, None)
    assert auth_service.login(db_session, "new.owner@example.com", NEW_PASSWORD, "test").access_token
    assert NEW_PASSWORD not in console.shown and temporary not in console.shown


def test_force_does_not_turn_an_admin_into_a_super_admin_or_touch_its_password(db_session, make_account):
    first_super_admin(db_session)
    admin = make_account(db_session, "admin@example.com", PASSWORD)
    before = admin.password_hash
    console = Console(["admin@example.com"])

    assert run(db_session, console, force=True) == 1

    assert "has never been a super admin" in console.lines[-1] and "reset in the Super Admin portal" in console.lines[-1]
    db_session.expire_all()
    assert (admin.role, admin.password_hash) == ("admin", before)


def former_super_admin(db, make_account, log_in):
    """A super admin who was then made an admin in the portal, logged in on a device."""
    first_super_admin(db)
    former = make_account(db, "former@example.com", PASSWORD, role="super_admin", full_name="Former Owner")
    former.role = "admin"
    db.commit()
    log_in(db, former)
    return former


def test_force_is_how_a_former_super_admin_gets_a_new_password_and_it_stays_an_admin(db_session, make_account, log_in):
    # The portal never resets this account's password (it has been a super admin), so this is the way back in.
    former = former_super_admin(db_session, make_account, log_in)
    console = Console(["former@example.com", "former@example.com"], [NEW_PASSWORD, NEW_PASSWORD])

    assert run(db_session, console, force=True) == 0

    assert "former@example.com was a super admin and is an admin now" in console.shown and "It stays an admin." in console.shown
    assert console.lines[-1] == "The password of former@example.com (a former super admin, an admin now) was replaced."
    db_session.expire_all()
    assert (former.role, former.has_been_super_admin, former.must_change_password, former.temporary_password_expires_at) == ("admin", True, False, None)
    assert password_service.verify_password(former.password_hash, NEW_PASSWORD)
    # Logged out everywhere, and the reset is on record as done on the server.
    assert [session.revoked_at is not None for session in db_session.query(AdminSession).filter_by(account_id=former.id)] == [True]
    assert [(row.action, row.actor_id, row.details) for row in db_session.query(AuditLog).filter_by(target_id=former.id)] == [
        ("admin.password_reset", None, {"via": "command line"})]
    assert NEW_PASSWORD not in console.shown


def test_force_changes_nothing_for_a_former_super_admin_unless_the_email_is_typed_again(db_session, make_account, log_in):
    former = former_super_admin(db_session, make_account, log_in)
    before = former.password_hash

    assert run(db_session, Console(["former@example.com", "someone.else@example.com"]), force=True) == 1

    db_session.expire_all()
    assert former.password_hash == before and db_session.query(AuditLog).filter_by(target_id=former.id).count() == 0


# ---- the command itself -------------------------------------------------------------------------

def test_no_option_takes_a_password_an_email_or_a_name(capsys):
    with pytest.raises(SystemExit):
        tool.main(["--help"])
    usage = capsys.readouterr().out

    assert "--force" in usage
    assert "--password" not in usage and "--email" not in usage and "--name" not in usage
    for attempt in (["--password", PASSWORD], ["--password=" + PASSWORD], [PASSWORD]):
        with pytest.raises(SystemExit) as refused:
            tool.main(attempt)
        assert refused.value.code == 2
    assert PASSWORD not in capsys.readouterr().out


def test_it_does_not_read_a_password_from_a_pipe_or_a_file(monkeypatch, capsys):
    from app import schema

    monkeypatch.setattr(sys, "stdin", io.StringIO(f"owner@example.com\nSample Owner\n{PASSWORD}\n{PASSWORD}\n"))
    monkeypatch.setattr(schema, "init_database_schema", lambda *args: pytest.fail("the database was touched"))

    assert tool.main([]) == 2
    assert "Run this in a terminal window" in capsys.readouterr().out


def test_run_from_a_terminal_it_creates_the_account_in_the_configured_database(tmp_path, monkeypatch, capsys):
    from app import database, schema

    engine = create_engine(f"sqlite:///{tmp_path / 'vernex.db'}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(schema, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    typed = iter(["owner@example.com", "Sample Owner"])
    monkeypatch.setattr("builtins.input", lambda question="": next(typed))
    monkeypatch.setattr(getpass, "getpass", lambda question="": PASSWORD)

    assert tool.main([]) == 0

    shown = capsys.readouterr().out
    assert "Super admin created: owner@example.com" in shown and "vernex.db" in shown and PASSWORD not in shown
    with sessionmaker(bind=engine)() as db:
        assert accounts(db) == [("owner@example.com", "super_admin", "active")]
    # Run again as it is, it changes nothing.
    assert tool.main([]) == 1
    engine.dispose()


def test_it_says_which_database_without_the_user_name_or_the_password():
    remote = tool.database_label(make_url("postgresql://postgres.sampleref:S3cret%40Pass@aws-0-region.pooler.example.com:6543/postgres"))
    local = tool.database_label(make_url("sqlite:///./vernex_attendance.db"))

    assert remote == 'the postgresql database "postgres" on aws-0-region.pooler.example.com'
    assert "S3cret" not in remote and "sampleref" not in remote
    assert local == "the local SQLite file ./vernex_attendance.db"


def test_no_password_and_no_hash_is_written_into_the_backend_sources():
    # "No default credentials": the only way in is an account somebody created at the prompt.
    import re

    backend_folder = Path(__file__).resolve().parents[1]
    sources = [path for folder in ("app", "scripts", "migrations") for path in (backend_folder / folder).rglob("*") if path.suffix in (".py", ".sql")]
    literal_password = re.compile(r"""(?i)\w*(password|passwd|secret)\w*\s*[:=]\s*["'][^"'{}\s]{4,}["']""")
    # A real hash has a salt and a digest after its settings; a comment that shows the format does not.
    stored_hash = re.compile(r"\$argon2(?:id|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{8,}\$[A-Za-z0-9+/]{16,}")
    assert stored_hash.search("$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaGhhc2g")
    assert len(sources) > 30
    for path in sources:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert not stored_hash.search(text), path
        assert not literal_password.search(text), (path, literal_password.search(text).group(0))
        assert "INSERT INTO admin_accounts" not in text, path
    assert "getpass.getpass" in (SCRIPTS / "create_super_admin.py").read_text(encoding="utf-8")


# ---- the signing secret -------------------------------------------------------------------------

EXAMPLE = "# Copy this file to .env\r\nFRONTEND_ORIGIN=http://localhost:5173\r\n\r\n# Login\r\nJWT_SECRET=\r\n# AUTH_ACCESS_MINUTES=15\r\n"


def files(tmp_path, env=None, example=EXAMPLE):
    env_file, example_file = tmp_path / ".env", tmp_path / ".env.example"
    if example is not None:
        example_file.write_bytes(example.encode())
    if env is not None:
        env_file.write_bytes(env.encode())
    return env_file, example_file


def test_without_a_settings_file_one_is_made_from_the_template_with_a_secret_in_it(tmp_path):
    env_file, example_file = files(tmp_path)

    assert secret_tool.ensure_secret(env_file, example_file) == "added"

    written = env_file.read_bytes().decode()
    secret = dotenv_values(env_file)["JWT_SECRET"]
    assert len(secret.encode()) >= 32 and secret.isascii()
    # Everything else is the template, line for line, and the template itself is left empty.
    assert written.replace(f"JWT_SECRET={secret}", "JWT_SECRET=") == EXAMPLE
    assert example_file.read_bytes().decode() == EXAMPLE
    assert dotenv_values(env_file)["FRONTEND_ORIGIN"] == "http://localhost:5173"


@pytest.mark.parametrize("existing", ["DATABASE_URL=sqlite:///./x.db\nFRONTEND_ORIGIN=http://localhost:5173\n", "DATABASE_URL=sqlite:///./x.db", "", "# JWT_SECRET=commented-out-and-not-a-setting-0123456789\n"])
def test_a_settings_file_without_the_secret_gets_one_added_and_keeps_its_lines(tmp_path, existing):
    env_file, example_file = files(tmp_path, env=existing)

    assert secret_tool.ensure_secret(env_file, example_file) == "added"

    written = env_file.read_bytes().decode()
    assert written.startswith(existing) and written.endswith("\n")
    assert len(dotenv_values(env_file)["JWT_SECRET"]) >= 32
    assert len([line for line in written.splitlines() if line.startswith("JWT_SECRET=")]) == 1


def test_a_secret_that_is_already_there_is_left_alone(tmp_path):
    existing = f"JWT_SECRET={'k' * 40}\nFRONTEND_ORIGIN=http://localhost:5173\n"
    env_file, example_file = files(tmp_path, env=existing)

    assert secret_tool.ensure_secret(env_file, example_file) == "kept"
    assert env_file.read_bytes().decode() == existing


def test_running_it_twice_changes_nothing_the_second_time(tmp_path):
    env_file, example_file = files(tmp_path)
    secret_tool.ensure_secret(env_file, example_file)
    first = env_file.read_bytes()

    assert secret_tool.ensure_secret(env_file, example_file) == "kept"
    assert env_file.read_bytes() == first


def test_every_installation_gets_its_own_secret(tmp_path):
    secrets_made = set()
    for name in ("one", "two", "three"):
        (tmp_path / name).mkdir()
        env_file, example_file = files(tmp_path / name)
        secret_tool.ensure_secret(env_file, example_file)
        secrets_made.add(dotenv_values(env_file)["JWT_SECRET"])

    assert len(secrets_made) == 3


def test_a_secret_that_is_too_short_is_left_for_a_person_to_decide(tmp_path):
    env_file, example_file = files(tmp_path, env="JWT_SECRET=zq7-typed-by-hand\n")

    with pytest.raises(ValueError) as problem:
        secret_tool.ensure_secret(env_file, example_file)

    assert "shorter than 32 characters" in str(problem.value) and "zq7" not in str(problem.value)
    assert env_file.read_bytes().decode() == "JWT_SECRET=zq7-typed-by-hand\n"


def test_the_command_never_shows_the_secret(tmp_path, monkeypatch, capsys):
    files(tmp_path)
    monkeypatch.setattr(secret_tool, "ROOT", tmp_path)

    assert secret_tool.main() == 0
    assert secret_tool.main() == 0

    shown = capsys.readouterr().out
    assert dotenv_values(tmp_path / ".env")["JWT_SECRET"] not in shown
    assert "was written to backend\\.env" in shown and "already has a JWT_SECRET" in shown
