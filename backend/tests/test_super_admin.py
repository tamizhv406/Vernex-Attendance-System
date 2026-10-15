"""The Super Admin portal: managing the admin accounts, the dashboard and the audit log (SA-01 to SA-04).

Who may reach these routes at all (nobody, an admin, a super admin) is walked route by route in
test_route_protection.py. This file is about what they do.
"""
import json
import re
import threading
import time as wall_clock
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.admin_account import AdminAccount, AdminSession
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.audit_log import AuditLog
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEnrollment
from app.models.person import Person
from app.routes import face_routes
from app.schema import POSTGRES_REPAIR_STATEMENTS
from app.services import admin_service, audit_service, auth_service
from app.services.auth_service import Actor, AuthError
from app.utils.time_utils import today_local, utc_now

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a password of my very own"
TEMPORARY = re.compile(r"[a-hjkmnp-z2-9]{6}-[a-hjkmnp-z2-9]{6}-[a-hjkmnp-z2-9]{6}")
# What no answer of the portal and no row of the audit log may ever hold.
NEVER_SHOWN = ("password_hash", "$argon2", "token_hash", "failed_login_count", "refresh_token", PASSWORD)


@pytest.fixture()
def owner(backend, make_account, log_in):
    """A super admin who is logged in. owner.account_id is the account's id."""
    with backend.db() as db:
        account = make_account(db, "owner@example.com", PASSWORD, role="super_admin", full_name="Olivia Owner")
        token, _refresh = log_in(db, account)
        account_id = account.id
    client = backend()
    client.headers["Authorization"] = f"Bearer {token}"
    client.account_id = account_id
    return client


@pytest.fixture()
def asha(backend, make_account):
    with backend.db() as db:
        return make_account(db, "asha@example.com", PASSWORD, full_name="Asha Example").id


class Time:
    # The clock of logins and temporary passwords, moved forward instead of waited for. It starts
    # long before the real time, so the super admin's token (made with the real clock, by asking for
    # owner before time) stays good however far a test moves it.
    def __init__(self):
        self.now = datetime(2026, 1, 5, 9, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, **amount):
        self.now += timedelta(**amount)


@pytest.fixture()
def time(monkeypatch):
    clock = Time()
    monkeypatch.setattr(auth_service, "clock", clock)
    return clock


def sign_in(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def bearer(response):
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def create(owner, email="nia@example.com", full_name="Nia Admin", role="admin"):
    return owner.post("/super-admin/admins", json={"email": email, "full_name": full_name, "role": role})


def stored(backend, account_id):
    with backend.db() as db:
        account = db.get(AdminAccount, account_id)
        db.expunge(account)
        return account


def audit(backend, *actions):
    """(action, actor_id, target_type, target_id, details) of every row, oldest first; only these actions if named."""
    with backend.db() as db:
        rows = db.query(AuditLog).order_by(AuditLog.id)
        if actions:
            rows = rows.filter(AuditLog.action.in_(actions))
        return [(row.action, row.actor_id, row.target_type, row.target_id, row.details) for row in rows]


def assert_nothing_secret(text, *also):
    for secret in NEVER_SHOWN + also:
        assert secret not in text, secret


# ---- creating an admin --------------------------------------------------------------------------

def test_a_super_admin_creates_an_admin_who_gets_a_temporary_password_shown_once(backend, owner):
    answer = create(owner, email="  Nia.Admin@Example.com ", full_name="  Nia   Admin ")

    data = answer.json()["data"]
    password = data["temporary_password"]
    account = data["account"]
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store"
    assert TEMPORARY.fullmatch(password)
    assert (account["email"], account["full_name"], account["role"], account["status"], account["must_change_password"], account["created_by"]) == (
        "nia.admin@example.com", "Nia Admin", "admin", "active", True, owner.account_id)
    # Never again: not in the list, not on the account's own page, not in the database or the log.
    later = owner.get("/super-admin/admins").text + owner.get(f"/super-admin/admins/{account['id']}").text
    assert password not in later and '"temporary_password":' not in later
    with backend.db() as db:
        assert db.get(AdminAccount, account["id"]).password_hash.startswith("$argon2")
        assert password not in json.dumps([row.details for row in db.query(AuditLog)])
    assert_nothing_secret(answer.text)


def test_the_new_admin_logs_in_with_it_must_change_it_and_then_sees_the_console(backend, owner):
    password = create(owner).json()["data"]["temporary_password"]
    newcomer = backend()

    first = sign_in(newcomer, "nia@example.com", password)
    assert first.status_code == 200 and first.json()["data"]["account"]["must_change_password"] is True
    assert newcomer.get("/courses", headers=bearer(first)).json() == {"detail": "Change your password before continuing."}
    changed = newcomer.post("/auth/change-password", headers=bearer(first), json={"current_password": password, "new_password": NEW_PASSWORD})
    assert changed.status_code == 200

    assert sign_in(newcomer, "nia@example.com", password).status_code == 401
    again = sign_in(newcomer, "nia@example.com", NEW_PASSWORD)
    assert again.json()["data"]["account"]["must_change_password"] is False
    assert newcomer.get("/courses", headers=bearer(again)).status_code == 200
    # An admin, not a super admin: the portal stays shut.
    assert newcomer.get("/super-admin/dashboard", headers=bearer(again)).status_code == 403


def test_a_super_admin_can_create_another_super_admin(backend, owner):
    answer = create(owner, email="second@example.com", role="super_admin")

    assert answer.json()["data"]["account"]["role"] == "super_admin"


def test_temporary_passwords_are_random_unambiguous_and_pass_the_password_rules():
    made = {admin_service.temporary_password() for _ in range(300)}

    assert len(made) == 300
    for password in made:
        assert TEMPORARY.fullmatch(password)
        auth_service.check_new_password(password, "nia@example.com")
    # Nothing that can be misread when it is read out or copied from a screen.
    assert not set("0o1li") & set("".join(made))


@pytest.mark.parametrize("body, status, detail", [
    ({"email": "OWNER@example.com", "full_name": "Someone"}, 409, "An account with this email already exists."),
    ({"email": "not an email", "full_name": "Someone"}, 400, None),
    ({"email": "nia@example.com", "full_name": "   "}, 400, "Enter a full name (160 characters at most)."),
    ({"email": "nia@example.com", "full_name": "N" * 161}, 400, "Enter a full name (160 characters at most)."),
    ({"email": "nia@example.com", "full_name": "Nia", "role": "owner"}, 400, "Role must be super_admin or admin."),
    ({"email": "nia@example.com", "full_name": "Nia", "password": "chosen by the super admin"}, 422, None),
    ({"email": "nia@example.com", "full_name": "Nia", "status": "disabled"}, 422, None),
    ({"full_name": "Nia"}, 422, None),
])
def test_an_account_that_cannot_be_created_is_refused_and_nothing_is_saved(backend, owner, body, status, detail):
    answer = owner.post("/super-admin/admins", json=body)

    assert answer.status_code == status
    if detail:
        assert answer.json() == {"detail": detail}
    with backend.db() as db:
        assert db.query(AdminAccount).count() == 1
    assert audit(backend, "admin.created") == []
    assert "chosen by the super admin" not in answer.text


def test_an_email_saved_by_another_request_after_the_check_is_refused_and_nothing_is_kept(db_session, make_account, monkeypatch):
    owner = make_account(db_session, "owner@example.com", role="super_admin")
    make_account(db_session, "same@example.com", full_name="Saved A Moment Ago")
    actor = Actor(owner.id, owner.email, owner.full_name, "super_admin", False, 1)
    # The check for the email ran before the other request saved it.
    monkeypatch.setattr(auth_service, "_find", lambda db, email: None)

    with pytest.raises(AuthError) as refused:
        admin_service.create(db_session, actor, "same@example.com", "Same Person")

    assert (refused.value.status, refused.value.message) == (409, "An account with this email already exists.")
    db_session.expire_all()
    assert [account.full_name for account in db_session.query(AdminAccount).filter_by(email="same@example.com")] == ["Saved A Moment Ago"]
    assert db_session.query(AuditLog).count() == 0
    # The session is usable again: the next request on it works.
    monkeypatch.undo()
    account, _password = admin_service.create(db_session, actor, "other@example.com", "Other Person")
    assert account.id is not None


def test_two_super_admins_creating_the_same_email_at_the_same_moment_get_one_account_and_a_409(tmp_path, make_account, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'create.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        owner = make_account(db, "owner@example.com", role="super_admin")
        actor = Actor(owner.id, owner.email, owner.full_name, "super_admin", False, 1)
    checking = auth_service.check_new_password

    def slowly(password, email):
        # Between looking for the email and saving it: long enough for the other request to look too.
        wall_clock.sleep(0.3)
        checking(password, email)

    monkeypatch.setattr(auth_service, "check_new_password", slowly)
    gate, outcomes = threading.Barrier(2), []

    def create_it():
        gate.wait()
        with sessions() as db:
            try:
                admin_service.create(db, actor, "same@example.com", "Same Person")
                outcomes.append("created")
            except AuthError as error:
                outcomes.append(error.status)

    threads = [threading.Thread(target=create_it) for _ in range(2)]
    [thread.start() for thread in threads]
    [thread.join(timeout=60) for thread in threads]

    assert sorted(outcomes, key=str) == [409, "created"]
    with sessions() as db:
        assert db.query(AdminAccount).filter_by(email="same@example.com").count() == 1
        assert db.query(AuditLog).filter_by(action="admin.created").count() == 1
    engine.dispose()


# ---- the list -----------------------------------------------------------------------------------

@pytest.fixture()
def staff(backend, owner, make_account):
    with backend.db() as db:
        make_account(db, "asha@example.com", full_name="Asha Example")
        make_account(db, "ben@example.com", full_name="Ben Disabled", status="disabled")
        make_account(db, "carla_x@example.com", full_name="Carla Second", role="super_admin")
        make_account(db, "dev@example.com", full_name="Dev Locked", failed_login_count=5, locked_until=utc_now() + timedelta(minutes=10))


def emails(answer):
    assert answer.status_code == 200, answer.text
    return [account["email"] for account in answer.json()["data"]]


@pytest.mark.parametrize("query, expected", [
    ({}, ["asha@example.com", "ben@example.com", "carla_x@example.com", "dev@example.com", "owner@example.com"]),
    ({"search": "ASHA"}, ["asha@example.com"]),
    ({"search": "  second "}, ["carla_x@example.com"]),
    # "_" and "%" are what they say, not wildcards.
    ({"search": "_x"}, ["carla_x@example.com"]),
    ({"search": "%"}, []),
    ({"status": "disabled"}, ["ben@example.com"]),
    ({"role": "super_admin"}, ["carla_x@example.com", "owner@example.com"]),
    ({"role": "admin", "status": "active", "search": "example"}, ["asha@example.com", "dev@example.com"]),
])
def test_admins_can_be_searched_and_filtered(owner, staff, query, expected):
    assert emails(owner.get("/super-admin/admins", params=query)) == expected


@pytest.mark.parametrize("query", [{"status": "deleted"}, {"role": "owner"}])
def test_an_unknown_filter_is_refused(owner, staff, query):
    assert owner.get("/super-admin/admins", params=query).status_code == 400


def test_the_list_says_who_is_locked_out_and_holds_nothing_secret(owner, staff):
    answer = owner.get("/super-admin/admins")
    accounts = {account["email"]: account for account in answer.json()["data"]}

    assert accounts["dev@example.com"]["locked"] is True and accounts["dev@example.com"]["locked_until"].endswith("Z")
    assert accounts["asha@example.com"]["locked"] is False and accounts["asha@example.com"]["locked_until"] is None
    assert set(accounts["asha@example.com"]) == {"id", "email", "full_name", "role", "status", "must_change_password", "last_login_at",
                                                 "created_at", "updated_at", "locked", "locked_until", "created_by",
                                                 "temporary_password_expires_at", "temporary_password_expired", "has_been_super_admin"}
    assert_nothing_secret(answer.text, "no-password-set")


def test_an_account_that_does_not_exist_is_not_found(owner):
    for answer in (owner.get("/super-admin/admins/999"), owner.put("/super-admin/admins/999", json={"full_name": "X"}),
                   owner.post("/super-admin/admins/999/disable"), owner.post("/super-admin/admins/999/enable"),
                   owner.post("/super-admin/admins/999/reset-password")):
        assert (answer.status_code, answer.json()) == (404, {"detail": "Admin account not found."})


# ---- editing ------------------------------------------------------------------------------------

def test_name_and_email_can_be_changed_and_the_login_in_use_follows_at_once(backend, owner, asha):
    login = bearer(sign_in(backend(), "asha@example.com", PASSWORD))
    assert backend().get("/auth/me", headers=login).json()["data"]["email"] == "asha@example.com"

    answer = owner.put(f"/super-admin/admins/{asha}", json={"email": "Asha.New@Example.com", "full_name": "Asha  Renamed"})

    assert (answer.status_code, answer.json()["data"]["email"], answer.json()["data"]["full_name"]) == (200, "asha.new@example.com", "Asha Renamed")
    # Still logged in, under the new address, without waiting for anything to run out.
    assert backend().get("/auth/me", headers=login).json()["data"]["email"] == "asha.new@example.com"
    assert sign_in(backend(), "asha.new@example.com", PASSWORD).status_code == 200
    assert audit(backend, "admin.updated") == [("admin.updated", owner.account_id, "admin_account", asha, {
        "email": {"from": "asha@example.com", "to": "asha.new@example.com"}, "full_name": {"from": "Asha Example", "to": "Asha Renamed"}})]


def test_a_new_role_ends_the_accounts_logins_so_it_comes_back_with_the_right_pages(backend, owner, asha):
    browser = backend()
    login = bearer(sign_in(browser, "asha@example.com", PASSWORD))

    answer = owner.put(f"/super-admin/admins/{asha}", json={"role": "super_admin"})

    assert answer.status_code == 200 and stored(backend, asha).role == "super_admin"
    assert backend().get("/courses", headers=login).status_code == 401
    assert browser.post("/auth/refresh").status_code == 401
    again = sign_in(browser, "asha@example.com", PASSWORD)
    assert browser.get("/super-admin/dashboard", headers=bearer(again)).status_code == 200


def test_an_email_another_account_has_is_refused(backend, owner, asha):
    answer = owner.put(f"/super-admin/admins/{asha}", json={"email": "Owner@Example.com"})

    assert (answer.status_code, answer.json()) == (409, {"detail": "An account with this email already exists."})
    assert stored(backend, asha).email == "asha@example.com"


def test_saving_without_a_change_writes_nothing(backend, owner, asha):
    answer = owner.put(f"/super-admin/admins/{asha}", json={"email": "ASHA@example.com", "full_name": "Asha  Example", "role": "admin"})

    assert answer.status_code == 200 and audit(backend, "admin.updated") == []


@pytest.mark.parametrize("body", [{"status": "disabled"}, {"password": "a new password for asha"}, {"must_change_password": False}])
def test_status_and_password_are_not_changed_through_an_edit(owner, asha, body):
    assert owner.put(f"/super-admin/admins/{asha}", json=body).status_code == 422


def test_a_super_admin_cannot_demote_themself_but_may_rename_themself(backend, owner):
    demoted = owner.put(f"/super-admin/admins/{owner.account_id}", json={"role": "admin"})
    renamed = owner.put(f"/super-admin/admins/{owner.account_id}", json={"full_name": "Olivia Renamed"})

    assert (demoted.status_code, demoted.json()) == (400, {"detail": "You cannot change your own role."})
    assert renamed.status_code == 200 and stored(backend, owner.account_id).role == "super_admin"
    # The rename does not log the super admin out.
    assert owner.get("/super-admin/dashboard").status_code == 200


# ---- disabling and enabling ---------------------------------------------------------------------

def test_disabling_an_admin_logs_them_out_everywhere_at_once_and_keeps_them_out(backend, owner, asha):
    phone, laptop = backend(), backend()
    on_phone, on_laptop = bearer(sign_in(phone, "asha@example.com", PASSWORD)), bearer(sign_in(laptop, "asha@example.com", PASSWORD))
    assert phone.get("/courses", headers=on_phone).status_code == 200

    answer = owner.post(f"/super-admin/admins/{asha}/disable")

    assert answer.status_code == 200 and answer.json()["data"]["status"] == "disabled"
    assert phone.get("/courses", headers=on_phone).status_code == 401
    assert laptop.get("/courses", headers=on_laptop).status_code == 401
    assert phone.post("/auth/refresh").status_code == 401
    assert sign_in(backend(), "asha@example.com", PASSWORD).json() == {"detail": "This account is disabled. Ask a super admin to enable it."}


def test_a_disabled_admin_can_be_enabled_again_and_log_in(backend, owner, asha):
    owner.post(f"/super-admin/admins/{asha}/disable")

    answer = owner.post(f"/super-admin/admins/{asha}/enable")

    assert answer.status_code == 200 and answer.json()["data"]["status"] == "active"
    assert sign_in(backend(), "asha@example.com", PASSWORD).status_code == 200


def test_disabling_twice_or_enabling_an_active_account_is_refused(owner, asha):
    assert owner.post(f"/super-admin/admins/{asha}/enable").json() == {"detail": "This account is already active."}
    owner.post(f"/super-admin/admins/{asha}/disable")
    assert owner.post(f"/super-admin/admins/{asha}/disable").json() == {"detail": "This account is already disabled."}


def test_a_super_admin_cannot_disable_themself(backend, owner):
    answer = owner.post(f"/super-admin/admins/{owner.account_id}/disable")

    assert (answer.status_code, answer.json()) == (400, {"detail": "You cannot disable your own account."})
    assert stored(backend, owner.account_id).status == "active"


def test_one_super_admin_can_disable_another_while_both_are_active(backend, owner, make_account):
    with backend.db() as db:
        second = make_account(db, "second@example.com", role="super_admin").id

    assert owner.post(f"/super-admin/admins/{second}/disable").status_code == 200


@pytest.mark.parametrize("change", ["disable", "demote"])
def test_the_last_active_super_admin_cannot_be_disabled_or_demoted(db_session, make_account, change):
    # Only possible for an actor whose own account stopped being an active super admin a moment
    # ago (another super admin disabled it): the guard does not trust that the actor still counts.
    last = make_account(db_session, "last@example.com", role="super_admin")
    make_account(db_session, "former@example.com", role="super_admin", status="disabled")
    make_account(db_session, "admin@example.com")
    former = Actor(2, "former@example.com", "Former Owner", "super_admin", False, 1)

    with pytest.raises(AuthError) as refused:
        if change == "disable":
            admin_service.disable(db_session, former, last.id)
        else:
            admin_service.update(db_session, former, last.id, role="admin")
    db_session.rollback()

    assert (refused.value.status, refused.value.message) == (409, "This is the last active super admin. Make another account a super admin first.")
    db_session.expire_all()
    assert (db_session.get(AdminAccount, last.id).role, db_session.get(AdminAccount, last.id).status) == ("super_admin", "active")


@pytest.fixture()
def two_super_admins(tmp_path, make_account):
    # A database file with real connections of its own, as two requests at the same moment have.
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        first, second = make_account(db, "first@example.com", role="super_admin"), make_account(db, "second@example.com", role="super_admin")
        sessions.actors = {account.id: Actor(account.id, account.email, account.full_name, "super_admin", False, 1) for account in (first, second)}
    yield sessions
    engine.dispose()


@pytest.mark.parametrize("change", ["disable", "demote"])
def test_two_super_admins_removing_each_other_at_the_same_moment_leave_one(two_super_admins, monkeypatch, change):
    sessions = two_super_admins
    ending = auth_service.end_logins

    def slowly(db, account_id):
        # Between the check and the commit, long enough for the other request to check too.
        wall_clock.sleep(0.3)
        ending(db, account_id)

    monkeypatch.setattr(auth_service, "end_logins", slowly)
    gate = threading.Barrier(2)
    outcomes = []

    def remove(actor_id, target_id):
        gate.wait()
        with sessions() as db:
            try:
                if change == "disable":
                    admin_service.disable(db, sessions.actors[actor_id], target_id)
                else:
                    admin_service.update(db, sessions.actors[actor_id], target_id, role="admin")
                outcomes.append("done")
            except AuthError as error:
                db.rollback()
                outcomes.append(error.status)

    first, second = sessions.actors
    threads = [threading.Thread(target=remove, args=(first, second)), threading.Thread(target=remove, args=(second, first))]
    [thread.start() for thread in threads]
    [thread.join(timeout=60) for thread in threads]

    assert sorted(outcomes, key=str) == [409, "done"]
    with sessions() as db:
        assert db.query(AdminAccount).filter_by(role="super_admin", status="active").count() == 1


# ---- password reset -----------------------------------------------------------------------------

def test_a_reset_gives_a_new_temporary_password_and_the_old_one_stops_working(backend, owner, asha):
    browser = backend()
    login = bearer(sign_in(browser, "asha@example.com", PASSWORD))
    with backend.db() as db:
        locked = db.get(AdminAccount, asha)
        locked.failed_login_count, locked.locked_until = 5, utc_now() + timedelta(minutes=10)
        db.commit()

    answer = owner.post(f"/super-admin/admins/{asha}/reset-password")

    password = answer.json()["data"]["temporary_password"]
    assert answer.status_code == 200 and answer.headers["cache-control"] == "no-store" and TEMPORARY.fullmatch(password)
    assert answer.json()["data"]["account"]["must_change_password"] is True and answer.json()["data"]["account"]["locked"] is False
    assert browser.get("/courses", headers=login).status_code == 401
    assert sign_in(backend(), "asha@example.com", PASSWORD).status_code == 401
    fresh = sign_in(backend(), "asha@example.com", password)
    assert fresh.status_code == 200 and fresh.json()["data"]["account"]["must_change_password"] is True
    assert_nothing_secret(answer.text)


def test_a_reset_leaves_a_disabled_account_disabled(backend, owner, asha):
    owner.post(f"/super-admin/admins/{asha}/disable")

    password = owner.post(f"/super-admin/admins/{asha}/reset-password").json()["data"]["temporary_password"]

    assert stored(backend, asha).status == "disabled"
    assert sign_in(backend(), "asha@example.com", password).status_code == 403


def test_a_super_admin_changes_their_own_password_in_settings_not_here(backend, owner):
    answer = owner.post(f"/super-admin/admins/{owner.account_id}/reset-password")

    assert (answer.status_code, answer.json()) == (400, {"detail": "Use Change password in Settings to change your own password."})
    assert sign_in(backend(), "owner@example.com", PASSWORD).status_code == 200


SUPER_ADMIN_RESET = {"detail": "This account is or has been a super admin, so its password cannot be reset here. On the server, run: scripts\\create_super_admin.py --force"}


def test_a_super_admin_cannot_reset_another_super_admins_password(backend, owner, make_account):
    # Whoever resets a password is shown the new one: this would let one super admin log in as another.
    with backend.db() as db:
        second = make_account(db, "second@example.com", PASSWORD, role="super_admin", full_name="Second Owner").id
    browser = backend()
    login = bearer(sign_in(browser, "second@example.com", PASSWORD))

    answer = owner.post(f"/super-admin/admins/{second}/reset-password")

    assert (answer.status_code, answer.json()) == (400, SUPER_ADMIN_RESET)
    assert "temporary_password" not in answer.text
    # Nothing about the account changed: its password, its logins, the log.
    assert browser.get("/auth/me", headers=login).status_code == 200
    assert sign_in(backend(), "second@example.com", PASSWORD).status_code == 200
    assert stored(backend, second).must_change_password is False
    assert audit(backend, "admin.password_reset") == []


def test_taking_the_role_away_first_does_not_open_a_super_admins_account(backend, owner, make_account):
    # The takeover this closes: (1) make the other super admin an admin, (2) reset that account's
    # password in the portal and read the new one, (3) log in as them and choose a password, (4) make
    # the account a super admin again. Step 2 is refused, whatever the account's role is by then.
    with backend.db() as db:
        second = make_account(db, "second@example.com", PASSWORD, role="super_admin", full_name="Second Owner").id

    demoted = owner.put(f"/super-admin/admins/{second}", json={"role": "admin"})
    reset = owner.post(f"/super-admin/admins/{second}/reset-password")
    promoted = owner.put(f"/super-admin/admins/{second}", json={"role": "super_admin"})
    reset_again = owner.post(f"/super-admin/admins/{second}/reset-password")

    assert demoted.status_code == 200 and demoted.json()["data"]["has_been_super_admin"] is True
    assert (reset.status_code, reset.json()) == (400, SUPER_ADMIN_RESET)
    assert promoted.status_code == 200 and (reset_again.status_code, reset_again.json()) == (400, SUPER_ADMIN_RESET)
    assert "temporary_password" not in reset.text + reset_again.text
    # No temporary password ever existed: the account still opens with its own password only.
    account = stored(backend, second)
    assert (account.must_change_password, account.temporary_password_expires_at, account.has_been_super_admin) == (False, None, True)
    assert sign_in(backend(), "second@example.com", PASSWORD).status_code == 200
    assert audit(backend, "admin.password_reset") == []
    # The role changes themselves are on record, under the acting account.
    assert [(actor, details["role"]["to"]) for _action, actor, _type, _target, details in audit(backend, "admin.updated")] == [
        (owner.account_id, "admin"), (owner.account_id, "super_admin")]


def test_an_admin_who_was_a_super_admin_only_for_a_moment_is_protected_for_good(backend, owner, asha):
    owner.put(f"/super-admin/admins/{asha}", json={"role": "super_admin"})
    owner.put(f"/super-admin/admins/{asha}", json={"role": "admin"})
    # Nothing in the portal takes the mark away again.
    owner.post(f"/super-admin/admins/{asha}/disable")
    owner.post(f"/super-admin/admins/{asha}/enable")
    owner.put(f"/super-admin/admins/{asha}", json={"full_name": "Asha Renamed", "email": "asha.new@example.com"})

    assert stored(backend, asha).has_been_super_admin is True
    assert (owner.post(f"/super-admin/admins/{asha}/reset-password").status_code) == 400


def test_the_mark_is_set_whenever_an_account_becomes_a_super_admin(backend, owner, db_session, make_account):
    created_super_admin = create(owner, email="new.owner@example.com", role="super_admin").json()["data"]["account"]
    created_admin = create(owner, email="new.admin@example.com", role="admin").json()["data"]["account"]
    # Whatever code sets the role, also outside the portal.
    direct = make_account(db_session, "direct@example.com", role="super_admin")
    plain = make_account(db_session, "plain@example.com")
    plain.role = "super_admin"
    db_session.commit()

    assert (created_super_admin["has_been_super_admin"], created_admin["has_been_super_admin"]) == (True, False)
    assert (direct.has_been_super_admin, plain.has_been_super_admin) == (True, True)
    assert stored(backend, created_admin["id"]).has_been_super_admin is False


def test_the_guards_around_super_admins_are_unchanged_by_the_mark(backend, owner, make_account):
    with backend.db() as db:
        second = make_account(db, "second@example.com", PASSWORD, role="super_admin").id
    # Still: not yourself, and a former super admin still counts as protected after being disabled.
    assert owner.post(f"/super-admin/admins/{owner.account_id}/reset-password").json() == {"detail": "Use Change password in Settings to change your own password."}
    assert owner.put(f"/super-admin/admins/{owner.account_id}", json={"role": "admin"}).status_code == 400
    owner.post(f"/super-admin/admins/{second}/disable")
    assert owner.post(f"/super-admin/admins/{second}/reset-password").json() == SUPER_ADMIN_RESET


def test_an_admins_password_is_still_reset_in_the_portal(backend, owner, asha):
    assert owner.post(f"/super-admin/admins/{asha}/reset-password").status_code == 200


# ---- temporary passwords run out ----------------------------------------------------------------

EXPIRED = {"detail": "This temporary password has expired. Ask a super admin for a new one."}
EXPIRED_ON_SERVER = {"detail": "This temporary password has expired. This account is or has been a super admin, so its password "
                               "cannot be reset in the Super Admin portal: whoever runs the backend sets a new one on the server "
                               "with scripts\\create_super_admin.py --force."}


@pytest.mark.parametrize("kind", ["super admin", "former super admin"])
def test_an_expired_super_admins_temporary_password_points_to_the_server_not_the_portal(backend, owner, time, kind):
    # A super admin created in the portal is given a temporary password too, but no super admin can
    # give it a new one there (has_been_super_admin): the answer must not send anyone to the portal.
    created = create(owner, email="new.owner@example.com", role="super_admin").json()["data"]
    if kind == "former super admin":
        assert owner.put(f"/super-admin/admins/{created['account']['id']}", json={"role": "admin"}).status_code == 200
    time.advance(hours=72)

    answer = sign_in(backend(), "new.owner@example.com", created["temporary_password"])

    assert (answer.status_code, answer.json()) == (403, EXPIRED_ON_SERVER)
    assert "Ask a super admin" not in answer.text and created["temporary_password"] not in answer.text
    assert [details["reason"] for *_rest, details in audit(backend, "auth.login_failed")] == ["expired_temporary_password"]
    # What it says is true: the portal refuses the reset.
    assert owner.post(f"/super-admin/admins/{created['account']['id']}/reset-password").json() == SUPER_ADMIN_RESET


@pytest.mark.parametrize("role, demoted, on_server", [("admin", False, False), ("super_admin", False, True), ("super_admin", True, True)],
                         ids=["admin", "super admin", "former super admin"])
def test_the_expired_password_message_names_the_way_the_portal_really_allows(db_session, make_account, time, role, demoted, on_server):
    owner = make_account(db_session, "owner@example.com", role="super_admin")
    account = make_account(db_session, "nia@example.com", "k7mx2p-q9trwa-h4bn8c", role=role, must_change_password=True,
                           temporary_password_expires_at=time.now)
    if demoted:
        account.role = "admin"
        db_session.commit()

    with pytest.raises(AuthError) as at_login:
        auth_service.login(db_session, "nia@example.com", "k7mx2p-q9trwa-h4bn8c", "test")
    with pytest.raises(AuthError) as at_change:
        # The password change says the same, for a login remembered in the seconds after it ran out.
        auth_service.change_password(db_session, Actor(account.id, account.email, account.full_name, account.role, True, 1), "k7mx2p-q9trwa-h4bn8c", NEW_PASSWORD)
    try:
        admin_service.reset_password(db_session, Actor(owner.id, owner.email, owner.full_name, "super_admin", False, 1), account.id)
        portal_resets = True
    except AuthError:
        portal_resets = False

    expected = (EXPIRED_ON_SERVER if on_server else EXPIRED)["detail"]
    assert (at_login.value.status, at_login.value.message) == (at_change.value.status, at_change.value.message) == (403, expected)
    assert portal_resets is not on_server


def test_a_temporary_password_works_for_72_hours_and_not_a_second_longer(backend, owner, time):
    created = create(owner).json()["data"]
    password = created["temporary_password"]
    assert created["account"]["temporary_password_expires_at"] == "2026-01-08T09:00:00Z"

    time.advance(hours=71, minutes=59, seconds=59)
    just_in_time = sign_in(backend(), "nia@example.com", password)
    time.advance(seconds=1)
    too_late = sign_in(backend(), "nia@example.com", password)
    guessed = sign_in(backend(), "nia@example.com", "not the temporary one")

    assert just_in_time.status_code == 200 and just_in_time.json()["data"]["account"]["must_change_password"] is True
    assert (too_late.status_code, too_late.json()) == (403, EXPIRED)
    # Only someone who knows the password is told it ran out; a guess is an ordinary wrong password.
    assert (guessed.status_code, guessed.json()) == (401, {"detail": "Incorrect email or password."})
    assert "set-cookie" not in too_late.headers
    assert [details["reason"] for *_rest, details in audit(backend, "auth.login_failed")] == ["expired_temporary_password", "wrong_password"]


def test_a_login_opened_with_a_temporary_password_ends_when_the_password_does(backend, owner, time):
    password = create(owner).json()["data"]["temporary_password"]
    browser = backend()
    sign_in(browser, "nia@example.com", password)

    time.advance(hours=71, minutes=59)
    renewed = browser.post("/auth/refresh")
    still_in = bearer(renewed)
    time.advance(minutes=1)

    assert renewed.status_code == 200
    # Neither the access token nor the cookie gets anything any more, not even the password change.
    assert browser.post("/auth/change-password", headers=still_in, json={"current_password": password, "new_password": NEW_PASSWORD}).status_code == 401
    assert browser.post("/auth/refresh").status_code == 401
    assert sign_in(backend(), "nia@example.com", NEW_PASSWORD).status_code == 401


def test_the_password_change_itself_refuses_an_expired_temporary_password(db_session, make_account, time):
    # For a request made in the seconds a login is remembered for, after the password ran out.
    account = make_account(db_session, "nia@example.com", "k7mx2p-q9trwa-h4bn8c", must_change_password=True,
                           temporary_password_expires_at=time.now)
    actor = Actor(account.id, account.email, account.full_name, "admin", True, 1)

    with pytest.raises(AuthError) as refused:
        auth_service.change_password(db_session, actor, "k7mx2p-q9trwa-h4bn8c", NEW_PASSWORD)

    assert (refused.value.status, refused.value.message) == (403, EXPIRED["detail"])


def test_a_reset_gives_72_new_hours_and_a_chosen_password_has_no_limit(backend, owner, asha, time):
    first = owner.post(f"/super-admin/admins/{asha}/reset-password").json()["data"]["temporary_password"]
    time.advance(hours=73)
    assert sign_in(backend(), "asha@example.com", first).status_code == 403
    listed = {account["email"]: account for account in owner.get("/super-admin/admins").json()["data"]}
    assert listed["asha@example.com"]["temporary_password_expired"] is True

    second = owner.post(f"/super-admin/admins/{asha}/reset-password").json()["data"]["temporary_password"]
    browser = backend()
    login = bearer(sign_in(browser, "asha@example.com", second))
    browser.post("/auth/change-password", headers=login, json={"current_password": second, "new_password": NEW_PASSWORD})
    time.advance(days=180)

    assert stored(backend, asha).temporary_password_expires_at is None
    assert sign_in(backend(), "asha@example.com", NEW_PASSWORD).status_code == 200
    listed = {account["email"]: account for account in owner.get("/super-admin/admins").json()["data"]}
    assert (listed["asha@example.com"]["temporary_password_expires_at"], listed["asha@example.com"]["temporary_password_expired"]) == (None, False)


def test_a_password_given_out_before_temporary_passwords_expired_keeps_working(backend, make_account, time):
    # Accounts from an earlier version have no expiry time: nothing is taken away from them.
    with backend.db() as db:
        make_account(db, "older@example.com", PASSWORD, must_change_password=True)
    time.advance(days=30)

    assert sign_in(backend(), "older@example.com", PASSWORD).status_code == 200


def test_the_dashboard_counts_expired_temporary_passwords(backend, owner, time):
    create(owner, email="early@example.com")
    time.advance(hours=48)
    create(owner, email="late@example.com")
    time.advance(hours=24)

    admins = owner.get("/super-admin/dashboard").json()["data"]["admins"]

    assert (admins["must_change_password"], admins["temporary_password_expired"]) == (2, 1)


# ---- the dashboard ------------------------------------------------------------------------------

def test_the_dashboard_counts_what_is_in_the_database(backend, owner, staff):
    with backend.db() as db:
        course = Course(course_code="CS101", course_name="Computer Science")
        db.add(course)
        db.commit()
        people = [Person(person_code=f"STU-{number}", full_name=f"Student {number}", person_type="student", course_id=course.id) for number in range(5)]
        db.add_all(people)
        db.commit()
        today, yesterday = today_local(), today_local() - timedelta(days=1)
        for person, status, day in zip(people, ["present", "present", "late", "absent", "present"], [today, today, today, today, yesterday]):
            db.add(AttendanceRecord(person_id=person.id, person_code=person.person_code, person_name=person.full_name, attendance_date=day, status=status))
        db.add(AdminAccount(email="new@example.com", full_name="New One", password_hash="x", must_change_password=True))
        db.commit()
    for number in range(12):
        create(owner, email=f"made{number}@example.com")

    data = owner.get("/super-admin/dashboard").json()["data"]

    # owner, asha, ben (disabled), carla (super admin), dev (locked), new (must change), made0..made11 (must change)
    assert data["admins"] == {"total": 18, "active": 17, "disabled": 1, "active_super_admins": 2, "active_admins": 15, "must_change_password": 13,
                              "temporary_password_expired": 0, "locked": 1}
    assert data["attendance_today"] == {"date": today.isoformat(), "total": 4, "present": 2, "late": 1, "absent": 1, "visited": 0}
    assert [entry["target_label"] for entry in data["recent_activity"]] == [f"made{number}@example.com" for number in range(11, 1, -1)]
    assert data["issues"] is None


def test_an_empty_dashboard_has_zeros_and_no_activity(owner):
    data = owner.get("/super-admin/dashboard").json()["data"]

    assert data["attendance_today"]["total"] == 0 and data["recent_activity"] == []
    assert data["admins"]["active_super_admins"] == 1


# ---- the audit log: one row for each action -----------------------------------------------------

def test_logging_in_and_failing_to_log_in_are_recorded_without_the_email_typed(backend, asha, make_account):
    with backend.db() as db:
        gone = make_account(db, "gone@example.com", PASSWORD, status="disabled").id
    browser = backend()

    sign_in(browser, "asha@example.com", PASSWORD)
    sign_in(browser, "asha@example.com", "not the password at all")
    sign_in(browser, "Typed.By.Mistake@example.com", "my secret password typed in the email box")
    sign_in(browser, "gone@example.com", PASSWORD)

    assert audit(backend) == [
        ("auth.login", asha, "admin_account", asha, None),
        ("auth.login_failed", None, "admin_account", asha, {"reason": "wrong_password"}),
        ("auth.login_failed", None, None, None, {"reason": "unknown_email"}),
        ("auth.login_failed", None, "admin_account", gone, {"reason": "disabled"}),
    ]
    with backend.db() as db:
        everything = json.dumps([[row.details, row.ip, row.user_agent] for row in db.query(AuditLog)])
        assert {(row.ip, row.user_agent) for row in db.query(AuditLog)} == {("testclient", "testclient")}
    assert "typed.by.mistake" not in everything.lower() and "secret password" not in everything


def test_a_locked_account_is_recorded_as_locked_and_a_flood_from_one_address_writes_nothing(backend, asha):
    browser = backend()
    answers = [sign_in(browser, "asha@example.com", f"wrong guess number {number}").status_code for number in range(12)]

    assert answers == [401] * 4 + [429] * 8
    reasons = [details["reason"] for _action, _actor, _type, _id, details in audit(backend, "auth.login_failed")]
    # The address's ten attempts a minute are recorded; the two refused before the database was asked are not.
    assert reasons == ["wrong_password"] * 4 + ["locked"] * 6


def test_logging_out_is_recorded_once(backend, asha):
    browser = backend()
    sign_in(browser, "asha@example.com", PASSWORD)

    browser.post("/auth/logout")
    browser.post("/auth/logout")

    assert audit(backend, "auth.logout") == [("auth.logout", asha, "admin_account", asha, None)]


def test_changing_ones_own_password_is_recorded(backend, asha):
    browser = backend()
    login = bearer(sign_in(browser, "asha@example.com", PASSWORD))

    browser.post("/auth/change-password", headers=login, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    browser.post("/auth/change-password", headers=login, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})

    assert audit(backend, "auth.password_changed") == [("auth.password_changed", asha, "admin_account", asha, None)]


def test_every_change_to_an_account_is_recorded_once_with_who_did_it(backend, owner, asha):
    nia = create(owner).json()["data"]["account"]["id"]
    owner.put(f"/super-admin/admins/{nia}", json={"role": "super_admin"})
    owner.post(f"/super-admin/admins/{asha}/disable")
    owner.post(f"/super-admin/admins/{asha}/disable")  # refused: nothing to record
    owner.post(f"/super-admin/admins/{asha}/enable")
    owner.post(f"/super-admin/admins/{asha}/reset-password")
    owner.post(f"/super-admin/admins/{owner.account_id}/disable")  # refused

    assert [(action, actor, target) for action, actor, _type, target, _details in audit(backend)] == [
        ("admin.created", owner.account_id, nia),
        ("admin.updated", owner.account_id, nia),
        ("admin.disabled", owner.account_id, asha),
        ("admin.enabled", owner.account_id, asha),
        ("admin.password_reset", owner.account_id, asha),
    ]
    assert audit(backend, "admin.created")[0][4] == {"email": "nia@example.com", "full_name": "Nia Admin", "role": "admin"}
    assert audit(backend, "admin.updated")[0][4] == {"role": {"from": "admin", "to": "super_admin"}}


@pytest.fixture()
def school(client):
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Computer Science")
        spare = Course(course_code="ART1", course_name="Art")
        db.add_all([course, spare])
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        empty_batch = CourseBatch(course_id=course.id, batch_name="Evening B")
        db.add_all([batch, empty_batch])
        db.commit()
        student = Person(person_code="STU-1", full_name="Sample Student", person_type="student", course_id=course.id, batch_id=batch.id)
        leaver = Person(person_code="STU-2", full_name="Leaving Student", person_type="student")
        session = AttendanceSession(session_name="Class", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add_all([student, leaver, session])
        db.commit()
        admin_id = db.query(AdminAccount).filter_by(email="admin@example.com").one().id
        return {"course": course.id, "spare": spare.id, "batch": batch.id, "empty_batch": empty_batch.id, "student": student.id,
                "leaver": leaver.id, "session": session.id, "admin": admin_id}


def test_deleting_a_person_a_course_or_a_batch_is_recorded_with_what_it_was(client, school):
    client.delete(f"/users/{school['leaver']}")
    client.delete(f"/courses/{school['spare']}")
    client.delete(f"/batches/{school['empty_batch']}")
    client.delete(f"/courses/{school['course']}")  # refused: it has batches and people

    assert audit(client) == [
        ("person.deleted", school["admin"], "person", school["leaver"], {"person_code": "STU-2", "full_name": "Leaving Student", "person_type": "student"}),
        ("course.deleted", school["admin"], "course", school["spare"], {"course_code": "ART1", "course_name": "Art"}),
        ("batch.deleted", school["admin"], "batch", school["empty_batch"], {"batch_name": "Evening B", "course_id": school["course"]}),
    ]


def test_attendance_marked_by_hand_is_recorded_once_per_change(client, school):
    mark = {"session_id": school["session"], "person_id": school["student"], "recognition_method": "manual"}

    client.post("/attendance/mark", json=mark)
    client.post("/attendance/mark", json=mark)  # already marked: nothing changed
    client.post("/attendance/mark-absent", json=mark)  # present -> absent
    client.post("/attendance/mark-absent", json=mark)  # absent already

    rows = audit(client, "attendance.marked")
    with client.db() as db:
        record = db.query(AttendanceRecord).one().id
    assert [(actor, target, details["status"], details.get("previous_status")) for _action, actor, _type, target, details in rows] == [
        (school["admin"], record, "present", None), (school["admin"], record, "absent", "present")]
    assert rows[0][4] == {"person_id": school["student"], "person_code": "STU-1", "session_id": school["session"], "status": "present", "method": "manual"}


def test_a_bulk_upload_is_recorded_with_its_counts_and_none_of_its_rows(client, school, make_csv):
    content = make_csv([["course_code", "course_name"], ["PHY1", "Physics Secret Name"], ["", "No code"]])

    client.post("/courses/upload", files={"file": ("my students private.csv", content)})

    assert audit(client) == [("import.uploaded", school["admin"], None, None, {"kind": "courses", "total_rows": 2, "imported": 1, "skipped": 1})]


def samples(steps):
    vector = np.random.default_rng(3).normal(size=512)
    return [{"pose_type": step, "embedding": list(vector / np.linalg.norm(vector)), "quality_score": 0.9, "brightness_score": 0.5, "blur_score": 0.5,
             "face_angle": 0.0, "has_specs": False, "box": [10, 10, 100, 100], "face_ratio": 0.3} for step in steps]


def test_face_enrollment_started_completed_and_cancelled_are_recorded(client, school, clock):
    student = school["student"]

    client.post(f"/face/enrollment/start/{student}", params={"mode": "quick"})
    client.post(f"/face/enrollment/cancel/{student}")
    client.post(f"/face/enrollment/cancel/{student}")  # nothing in progress: nothing to record
    client.post(f"/face/enrollment/start/{student}", params={"mode": "quick"})
    client.post(f"/face/enrollment/start/{student}", params={"mode": "quick"})  # started again, from the front
    with client.db() as db:
        # The last pose saved, as the frame route does it, on a session of a request by this admin.
        db.info["actor"] = Actor(school["admin"], "admin@example.com", "Sample Admin", "admin", False, 1)
        enrollment = db.query(FaceEnrollment).one()
        face_routes.save_enrollment(db, db.get(Person, student), enrollment, samples(["front", "left", "right"]), steps=["front", "left", "right"], mode="quick")

    assert [(action, actor, target_type, target, details) for action, actor, target_type, target, details in audit(client)] == [
        ("face_enrollment.started", school["admin"], "person", student, {"steps": 3}),
        ("face_enrollment.cancelled", school["admin"], "person", student, {"steps_done": 0}),
        ("face_enrollment.started", school["admin"], "person", student, {"steps": 3}),
        ("face_enrollment.started", school["admin"], "person", student, {"steps": 3}),
        ("face_enrollment.completed", school["admin"], "person", student, {"steps": 3}),
    ]
    with client.db() as db:
        assert "embedding" not in json.dumps([row.details for row in db.query(AuditLog)])


def test_enrolling_again_after_a_completed_enrollment_and_deleting_the_person(client, school, clock):
    student = school["student"]
    with client.db() as db:
        db.add(FaceEnrollment(person_id=student, enrollment_status="completed", completed_steps=3))
        db.commit()

    client.post(f"/face/enrollment/start/{student}", params={"mode": "quick"})
    client.delete(f"/users/{student}")

    # The new attempt was started; the person's deletion removes it without calling it a cancellation.
    assert [action for action, *_rest in audit(client)] == ["face_enrollment.started", "person.deleted"]


def test_scanner_marks_and_reading_pages_write_nothing(client, school):
    client.get("/courses")
    client.get("/users")
    client.get("/attendance/today")
    client.post("/attendance/session/start", json={"course_id": school["course"], "batch_id": school["batch"]})

    assert audit(client) == []


# ---- an action and its entry are saved together -------------------------------------------------

@pytest.fixture()
def audit_breaks(monkeypatch):
    """audit_breaks("admin.created", ...): writing those entries fails, as it would on a full disk."""
    writing = audit_service.record

    def for_actions(*actions):
        def record(db, action, **fields):
            if action in actions:
                raise OperationalError("INSERT INTO audit_logs (...) VALUES (...)", {}, Exception("disk I/O error"))
            return writing(db, action, **fields)
        monkeypatch.setattr(audit_service, "record", record)

    return for_actions


def test_an_account_change_whose_entry_cannot_be_written_is_not_made(backend, owner, asha, audit_breaks):
    audit_breaks("admin.created", "admin.disabled", "admin.password_reset")

    created = create(owner)
    disabled = owner.post(f"/super-admin/admins/{asha}/disable")
    reset = owner.post(f"/super-admin/admins/{asha}/reset-password")

    assert [created.status_code, disabled.status_code, reset.status_code] == [500, 500, 500]
    assert "temporary_password" not in created.text + reset.text
    with backend.db() as db:
        assert db.query(AdminAccount).filter_by(email="nia@example.com").count() == 0
    assert stored(backend, asha).status == "active" and stored(backend, asha).must_change_password is False
    assert sign_in(backend(), "asha@example.com", PASSWORD).status_code == 200


def test_a_deletion_whose_entry_cannot_be_written_is_not_made(client, school, audit_breaks):
    audit_breaks("person.deleted", "course.deleted")

    assert client.delete(f"/users/{school['leaver']}").status_code == 500
    assert client.delete(f"/courses/{school['spare']}").status_code == 500
    with client.db() as db:
        assert db.get(Person, school["leaver"]) is not None and db.get(Course, school["spare"]) is not None


def test_attendance_marked_by_hand_and_its_entry_are_saved_together(client, school, audit_breaks):
    mark = {"session_id": school["session"], "person_id": school["student"], "recognition_method": "manual"}
    audit_breaks("attendance.marked")

    assert client.post("/attendance/mark", json=mark).status_code == 500
    with client.db() as db:
        assert db.query(AttendanceRecord).count() == 0


def test_a_record_changed_to_absent_by_hand_and_its_entry_are_saved_together(client, school, monkeypatch, audit_breaks):
    mark = {"session_id": school["session"], "person_id": school["student"], "recognition_method": "manual"}
    client.post("/attendance/mark", json=mark)
    audit_breaks("attendance.marked")

    assert client.post("/attendance/mark-absent", json=mark).status_code == 500
    with client.db() as db:
        assert db.query(AttendanceRecord).one().status == "present"
    assert len(audit(client, "attendance.marked")) == 1


def test_a_new_record_marked_absent_is_saved_absent_with_its_entry(client, school):
    client.post("/attendance/mark-absent", json={"session_id": school["session"], "person_id": school["student"]})

    with client.db() as db:
        record = db.query(AttendanceRecord).one()
    assert (record.status, record.recognition_method) == ("absent", "auto_absent")
    assert [(details["status"], details.get("previous_status")) for *_rest, details in audit(client, "attendance.marked")] == [("absent", None)]


def test_a_bulk_upload_and_its_entry_are_saved_together(client, school, make_csv, audit_breaks):
    audit_breaks("import.uploaded")

    answer = client.post("/courses/upload", files={"file": ("courses.csv", make_csv([["course_code", "course_name"], ["PHY1", "Physics"]]))})

    assert answer.status_code == 500
    with client.db() as db:
        assert db.query(Course).filter_by(course_code="PHY1").count() == 0


def test_a_face_enrollment_whose_entry_cannot_be_written_is_not_started(client, school, clock, audit_breaks):
    audit_breaks("face_enrollment.started")

    assert client.post(f"/face/enrollment/start/{school['student']}", params={"mode": "quick"}).status_code == 500
    with client.db() as db:
        assert db.query(FaceEnrollment).count() == 0


# ---- what may be kept in a row ------------------------------------------------------------------

def test_details_keep_short_plain_values_and_nothing_that_could_be_secret():
    kept = audit_service.clean_details({
        "email": "asha@example.com", "count": 3, "ok": True, "when": date(2026, 10, 14), "nothing": None,
        "password": "hunter2-the-password", "new_password": "x", "token": "abc", "password_hash": "y", "Cookie": "z",
        "embedding": [0.1] * 512, "face_vector": [1], "image_base64": "...", "refresh_token": "r",
        "nested": {"secret": "s", "name": "Asha", "deeper": {"api_key_token": "t", "keep": 1}},
        # Under harmless names, values that are a hash, a signed token and a key; and a key-like run of letters.
        "note_1": "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA", "note_2": "eyJhbGciOi.eyJzdWIiOiIx.c2ln",
        "note_3": "k7" * 20, "note_4": "x" * 500, "long_text": "a long sentence " * 40, "many": list(range(50)),
        "thing": object(), "raw": b"bytes",
    })

    assert kept == {
        "email": "asha@example.com", "count": 3, "ok": True, "when": "2026-10-14", "nothing": None,
        "nested": {"name": "Asha", "deeper": {"keep": 1}},
        "note_1": "[hidden]", "note_2": "[hidden]", "note_3": "[hidden]", "note_4": "[hidden]",
        "long_text": ("a long sentence " * 40)[:200], "many": list(range(20)), "thing": None, "raw": None,
    }


def test_details_that_are_too_long_are_not_kept_and_unknown_actions_are_refused(db_session):
    assert audit_service.clean_details({f"field{number}": "some words " * 18 for number in range(15)}) == {"note": "details too long to keep"}
    assert audit_service.clean_details({}) is None and audit_service.clean_details({"password": "x"}) is None
    with pytest.raises(ValueError):
        audit_service.record(db_session, "admin.deleted_everything")
    with pytest.raises(ValueError):
        audit_service.record(db_session, "person.deleted", target_type="spaceship")
    with pytest.raises(TypeError):
        audit_service.clean_details(["not", "a", "dict"])


# ---- reading the log ----------------------------------------------------------------------------

@pytest.fixture()
def history(backend, owner, monkeypatch):
    # Rows at known moments. The school's days are in India (UTC+5:30): 18:29 UTC on the 13th is
    # 23:59 there, still the 13th; 18:31 UTC is already the 14th.
    monkeypatch.setattr(settings, "default_timezone", "Asia/Kolkata")
    with backend.db() as db:
        other = AdminAccount(email="other@example.com", full_name="Other Owner", password_hash="x", role="super_admin")
        person = Person(person_code="STU-9", full_name="Named Student", person_type="student")
        db.add_all([other, person])
        db.commit()
        rows = [
            (owner.account_id, "admin.created", "admin_account", other.id, datetime(2026, 10, 12, 9, 0)),
            (other.id, "person.deleted", "person", 404, datetime(2026, 10, 13, 18, 29)),
            (None, "auth.login_failed", None, None, datetime(2026, 10, 13, 18, 31)),
            (owner.account_id, "face_enrollment.started", "person", person.id, datetime(2026, 10, 14, 6, 0)),
        ]
        for actor, action, target_type, target_id, moment in rows:
            details = {"person_code": "STU-404", "full_name": "Gone Student"} if action == "person.deleted" else None
            db.add(AuditLog(actor_id=actor, action=action, target_type=target_type, target_id=target_id, details=details, created_at=moment))
        db.commit()
        return {"owner": owner.account_id, "other": other.id, "person": person.id}


def page(owner, **query):
    answer = owner.get("/super-admin/audit-logs", params=query)
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]


def test_the_log_is_shown_newest_first_with_names_and_utc_times(owner, history):
    data = page(owner)

    assert (data["total"], data["page"], data["page_size"]) == (4, 1, 25)
    assert [(item["action"], item["action_label"], item["target_label"]) for item in data["items"]] == [
        ("face_enrollment.started", "Face enrollment started", "Named Student (STU-9)"),
        ("auth.login_failed", "Login failed", None),
        ("person.deleted", "Person deleted", "Gone Student (STU-404)"),
        ("admin.created", "Admin created", "other@example.com"),
    ]
    assert data["items"][0]["created_at"] == "2026-10-14T06:00:00Z"
    assert data["items"][0]["actor"] == {"id": history["owner"], "email": "owner@example.com", "full_name": "Olivia Owner"}
    assert data["items"][1]["actor"] is None


@pytest.mark.parametrize("query, expected", [
    ({"action": "person.deleted"}, ["person.deleted"]),
    ({"target_type": "person"}, ["face_enrollment.started", "person.deleted"]),
    ({"date_from": "2026-10-13", "date_to": "2026-10-13"}, ["person.deleted"]),
    ({"date_from": "2026-10-14"}, ["face_enrollment.started", "auth.login_failed"]),
    ({"date_to": "2026-10-12"}, ["admin.created"]),
])
def test_the_log_can_be_filtered_by_action_target_and_days(owner, history, query, expected):
    assert [item["action"] for item in page(owner, **query)["items"]] == expected


def test_the_log_can_be_filtered_by_who_did_it(owner, history):
    assert [item["action"] for item in page(owner, actor_id=history["other"])["items"]] == ["person.deleted"]
    assert [item["action"] for item in page(owner, actor_id=history["owner"])["items"]] == ["face_enrollment.started", "admin.created"]


def test_the_log_comes_in_pages(owner, history):
    first, second, beyond = page(owner, page=1, page_size=3), page(owner, page=2, page_size=3), page(owner, page=3, page_size=3)

    assert [len(first["items"]), len(second["items"]), len(beyond["items"])] == [3, 1, 0]
    assert first["total"] == second["total"] == 4
    assert second["items"][0]["action"] == "admin.created"


@pytest.mark.parametrize("query, status", [
    ({"action": "admin.deleted_everything"}, 400), ({"target_type": "spaceship"}, 400),
    ({"date_from": "2026-10-14", "date_to": "2026-10-13"}, 400), ({"date_from": "yesterday"}, 422),
    ({"page": 0}, 422), ({"page_size": 101}, 422), ({"actor_id": "someone"}, 422),
])
def test_a_filter_that_makes_no_sense_is_refused(owner, history, query, status):
    assert owner.get("/super-admin/audit-logs", params=query).status_code == status


def test_the_viewer_lists_every_action_with_its_words(owner):
    actions = owner.get("/super-admin/audit-logs/actions").json()["data"]

    assert [item["action"] for item in actions] == list(audit_service.ACTIONS)
    assert all(item["label"] for item in actions)


def test_admins_cannot_read_the_log_and_nobody_can_change_it(backend, client, owner, history):
    assert client.get("/super-admin/audit-logs").status_code == 403
    for method in ("PUT", "PATCH", "DELETE"):
        assert owner.request(method, "/super-admin/audit-logs").status_code == 405
        assert owner.request(method, "/super-admin/audit-logs/1").status_code == 404
    assert audit(backend) != [] and len(audit(backend)) == 4


def test_nothing_secret_is_in_any_answer_of_the_portal_or_any_row_of_the_log(backend, owner, asha):
    browser = backend()
    sign_in(browser, "asha@example.com", PASSWORD)
    sign_in(browser, "asha@example.com", "a wrong password for asha")
    browser.post("/auth/logout")
    nia = create(owner).json()["data"]
    reset = owner.post(f"/super-admin/admins/{asha}/reset-password").json()["data"]["temporary_password"]

    said = "".join(owner.get(path).text for path in ("/super-admin/dashboard", "/super-admin/admins", f"/super-admin/admins/{asha}",
                                                      "/super-admin/audit-logs", "/super-admin/audit-logs/actions"))
    with backend.db() as db:
        logged = json.dumps([[row.action, row.details, row.ip, row.user_agent] for row in db.query(AuditLog)])
        hashes = [account.password_hash for account in db.query(AdminAccount)] + [session.token_hash for session in db.query(AdminSession)]
    for text in (said, logged):
        assert_nothing_secret(text, nia["temporary_password"], reset, "a wrong password for asha", *hashes)


# ---- the table and the migration ----------------------------------------------------------------

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
AUDIT_COLUMNS = ["id", "actor_id", "action", "target_type", "target_id", "details", "ip", "user_agent", "created_at"]


def test_the_audit_table_has_the_columns_the_task_sheet_names(db_session):
    assert [column["name"] for column in inspect(db_session.get_bind()).get_columns("audit_logs")] == AUDIT_COLUMNS
    assert [column.name for column in AuditLog.__table__.columns] == AUDIT_COLUMNS


def test_a_row_written_without_a_time_gets_the_utc_time_and_keeps_its_actor_column_if_the_account_goes(db_session, make_account):
    account = make_account(db_session, "gone@example.com", role="super_admin")
    db_session.add(AuditLog(actor_id=account.id, action="auth.login"))
    db_session.commit()

    row = db_session.query(AuditLog).one()
    assert abs((row.created_at - utc_now()).total_seconds()) < 5
    assert AuditLog.__table__.c.actor_id.foreign_keys.pop().ondelete == "SET NULL"


def test_startup_switches_row_level_security_on_for_the_audit_log_on_postgresql():
    assert "ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY" in [" ".join(statement.split()) for statement in POSTGRES_REPAIR_STATEMENTS]
    assert not any("CREATE POLICY" in statement.upper() for statement in POSTGRES_REPAIR_STATEMENTS)


def sql_statements(sql):
    return [" ".join(statement.split()) for statement in re.sub(r"--[^\n]*", "", sql).split(";") if statement.strip()]


@pytest.mark.parametrize("file", ["006_audit_logs.sql", "full_schema.sql"])
def test_the_sql_files_describe_the_audit_table_like_the_model(file):
    sql = (MIGRATIONS / file).read_text(encoding="utf-8")
    body = re.search(r"CREATE TABLE IF NOT EXISTS audit_logs \((.*?)\n\);", sql, re.S).group(1)
    written = {line.strip().split()[0]: line.strip().rstrip(",") for line in body.splitlines() if line.strip()}

    assert list(written) == AUDIT_COLUMNS
    for column in AuditLog.__table__.columns:
        line = written[column.name]
        length = getattr(column.type, "length", None)
        if length:
            assert f"VARCHAR({length})" in line, line
        assert ("NOT NULL" in line or "PRIMARY KEY" in line) == (not column.nullable), line
    assert "REFERENCES admin_accounts (id) ON DELETE SET NULL" in written["actor_id"] and written["details"].endswith("JSON")
    listed = sql_statements(sql)
    for index in AuditLog.__table__.indexes:
        columns = ", ".join(column.name for column in index.columns)
        assert f"CREATE INDEX IF NOT EXISTS {index.name} ON audit_logs ({columns})" in listed
    assert "ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY" in listed


def test_the_audit_migration_can_be_run_twice_and_touches_nothing_stored():
    for statement in sql_statements((MIGRATIONS / "006_audit_logs.sql").read_text(encoding="utf-8")):
        if statement.startswith("CREATE"):
            assert "IF NOT EXISTS" in statement, statement
        assert not re.match(r"(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", statement), statement
