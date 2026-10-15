import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.admin_account import AdminAccount, AdminSession
from app.models.course import Course
from app.models.person import Person
from app.schema import POSTGRES_REPAIR_STATEMENTS, init_database_schema
from app.serializers import admin_account_data
from app.utils.time_utils import utc_now

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
# The columns the task sheet names for the accounts table (A-01).
ACCOUNT_COLUMNS = {
    "id", "email", "full_name", "password_hash", "role", "status", "must_change_password", "failed_login_count",
    "locked_until", "last_login_at", "created_by", "created_at", "updated_at", "temporary_password_expires_at", "has_been_super_admin",
}
SESSION_COLUMNS = {"id", "account_id", "token_hash", "expires_at", "revoked_at", "last_used_at", "ip", "user_agent", "created_at"}


def account(**fields):
    return AdminAccount(**{"email": "asha@example.com", "full_name": "Asha Example", "password_hash": "not-a-real-hash", **fields})


def test_both_login_tables_are_created_with_their_columns(db_session):
    tables = inspect(db_session.get_bind())

    assert {column["name"] for column in tables.get_columns("admin_accounts")} == ACCOUNT_COLUMNS
    assert {column["name"] for column in tables.get_columns("admin_sessions")} == SESSION_COLUMNS


def test_a_new_account_is_an_active_admin_who_has_never_failed_a_login(db_session):
    db_session.add(account())
    db_session.commit()

    saved = db_session.query(AdminAccount).one()
    assert (saved.role, saved.status, saved.must_change_password, saved.failed_login_count) == ("admin", "active", False, 0)
    assert (saved.locked_until, saved.last_login_at, saved.created_by) == (None, None, None)
    assert saved.created_at is not None and saved.updated_at is not None


def test_the_database_itself_fills_in_the_defaults_for_a_row_written_by_hand(db_session):
    db_session.execute(text("INSERT INTO admin_accounts (email, full_name, password_hash) VALUES ('by.hand@example.com', 'By Hand', 'x')"))
    db_session.commit()

    saved = db_session.query(AdminAccount).one()
    assert (saved.role, saved.status, saved.must_change_password, saved.failed_login_count) == ("admin", "active", False, 0)


def test_two_accounts_cannot_share_an_email(db_session):
    db_session.add(account())
    db_session.commit()
    db_session.add(account(full_name="Somebody Else"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_an_email_with_capital_letters_is_refused_by_the_database(db_session):
    # The application stores the address in small letters; this is what makes "one account per
    # address" true however the address is typed.
    db_session.add(account(email="Asha@Example.com"))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("fields", [{"role": "owner"}, {"role": "student"}, {"role": ""}, {"status": "pending"}, {"status": "deleted"}])
def test_a_role_or_status_outside_the_list_is_refused_by_the_database(db_session, fields):
    db_session.add(account(**fields))

    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("role", ["super_admin", "admin"])
@pytest.mark.parametrize("status", ["active", "disabled"])
def test_the_two_roles_and_the_two_statuses_are_accepted(db_session, role, status):
    db_session.add(account(role=role, status=status))
    db_session.commit()

    assert db_session.query(AdminAccount).one().role == role


def test_an_account_can_record_which_account_created_it(db_session):
    first = account(role="super_admin")
    db_session.add(first)
    db_session.commit()
    db_session.add(account(email="second@example.com", created_by=first.id))
    db_session.commit()

    assert db_session.query(AdminAccount).filter_by(email="second@example.com").one().created_by == first.id


def test_two_sessions_cannot_hold_the_same_token_hash(db_session):
    owner = account()
    db_session.add(owner)
    db_session.commit()
    db_session.add(AdminSession(account_id=owner.id, token_hash="a" * 64, expires_at=utc_now()))
    db_session.commit()
    db_session.add(AdminSession(account_id=owner.id, token_hash="a" * 64, expires_at=utc_now()))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_login_accounts_are_not_kept_with_the_people_whose_attendance_is_taken(db_session):
    # person_type "admin" means a staff member. Saving one must never create something that can log in.
    db_session.add(Person(person_code="STF-1", full_name="Sample Staff", person_type="admin", email="staff@example.com"))
    db_session.commit()

    assert AdminAccount.__tablename__ == "admin_accounts" != Person.__tablename__
    assert db_session.query(AdminAccount).count() == 0


def test_what_the_console_is_told_about_an_account_has_no_hash_and_no_lock_details(db_session):
    db_session.add(account(password_hash="$argon2id$secret-looking", failed_login_count=3, locked_until=utc_now()))
    db_session.commit()

    data = admin_account_data(db_session.query(AdminAccount).one())

    assert set(data) == {"id", "email", "full_name", "role", "status", "must_change_password", "last_login_at", "created_at", "updated_at"}
    assert "argon2" not in str(data)


def test_a_database_from_an_earlier_version_gains_the_login_tables_and_keeps_its_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    older = [table for name, table in Base.metadata.tables.items() if not name.startswith("admin_")]
    Base.metadata.create_all(bind=engine, tables=older)
    with sessionmaker(bind=engine)() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.commit()
    assert "admin_accounts" not in inspect(engine).get_table_names()

    init_database_schema(engine)
    init_database_schema(engine)  # every start of the backend runs it again

    assert {"admin_accounts", "admin_sessions"} <= set(inspect(engine).get_table_names())
    with sessionmaker(bind=engine)() as db:
        assert [(course.course_code, course.course_name) for course in db.query(Course)] == [("CS101", "Computer Science")]
        assert db.query(AdminAccount).count() == 0
    engine.dispose()


# ---- PostgreSQL: checked as text, because these tests run on SQLite -----------------------------

def statements(sql):
    return [" ".join(statement.split()) for statement in sql.split(";") if statement.strip()]


def table_columns(sql, table):
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S).group(1)
    lines = [line.strip().rstrip(",") for line in body.splitlines() if line.strip()]
    return {line.split()[0]: line for line in lines if not line.startswith("CONSTRAINT")}


@pytest.mark.parametrize("table", ["admin_accounts", "admin_sessions"])
def test_startup_switches_row_level_security_on_for_the_login_tables_on_postgresql(table):
    assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in [" ".join(statement.split()) for statement in POSTGRES_REPAIR_STATEMENTS]
    # No policy is created anywhere: with security on and no policy, the anon key reads nothing.
    assert not any("CREATE POLICY" in statement.upper() for statement in POSTGRES_REPAIR_STATEMENTS)


@pytest.mark.parametrize("file", ["005_admin_accounts.sql", "full_schema.sql"])
def test_the_sql_files_describe_the_same_tables_as_the_models(file):
    sql = (MIGRATIONS / file).read_text(encoding="utf-8")

    for model in (AdminAccount, AdminSession):
        written = table_columns(sql, model.__tablename__)
        assert list(written) == [column.name for column in model.__table__.columns], model.__tablename__
        for column in model.__table__.columns:
            line = written[column.name]
            length = getattr(column.type, "length", None)
            if length:
                assert f"VARCHAR({length})" in line, line
            # The primary key says so itself; every other column that must be filled says NOT NULL.
            assert ("NOT NULL" in line or "PRIMARY KEY" in line) == (not column.nullable), line
    for constraint in ("ck_admin_accounts_role", "ck_admin_accounts_status", "ck_admin_accounts_email_lower"):
        assert constraint in sql
    listed = statements(sql)
    for expected in (
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_accounts_email ON admin_accounts (email)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_admin_sessions_token_hash ON admin_sessions (token_hash)",
        "CREATE INDEX IF NOT EXISTS ix_admin_sessions_account_id ON admin_sessions (account_id)",
    ):
        assert expected in listed


@pytest.mark.parametrize("file", ["005_admin_accounts.sql", "full_schema.sql"])
def test_the_sql_files_switch_row_level_security_on_and_can_be_run_twice(file):
    sql = (MIGRATIONS / file).read_text(encoding="utf-8")
    listed = [statement.split("-- ")[-1] if statement.startswith("--") else statement for statement in statements(re.sub(r"--[^\n]*", "", sql))]

    assert "ALTER TABLE admin_accounts ENABLE ROW LEVEL SECURITY" in listed
    assert "ALTER TABLE admin_sessions ENABLE ROW LEVEL SECURITY" in listed
    for statement in listed:
        if statement.startswith("CREATE"):
            assert "IF NOT EXISTS" in statement, statement
        if statement.startswith("ALTER TABLE admin_accounts ADD COLUMN"):
            assert "IF NOT EXISTS" in statement, statement
        # Nothing in a migration may remove or rewrite what is already stored. The one UPDATE marks
        # the existing super admins in the column this file adds, and nothing else.
        if statement == SUPER_ADMIN_BACKFILL:
            continue
        assert not re.match(r"(DROP|TRUNCATE|DELETE|UPDATE)\b", statement), statement


SUPER_ADMIN_BACKFILL = "UPDATE admin_accounts SET has_been_super_admin = TRUE WHERE role = 'super_admin' AND NOT has_been_super_admin"


def test_the_migration_marks_every_existing_super_admin_and_only_them():
    listed = statements(re.sub(r"--[^\n]*", "", (MIGRATIONS / "005_admin_accounts.sql").read_text(encoding="utf-8")))

    assert "ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS has_been_super_admin BOOLEAN NOT NULL DEFAULT FALSE" in listed
    # After the column exists, so a second run finds nothing left to mark.
    assert listed.index(SUPER_ADMIN_BACKFILL) > listed.index("ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS has_been_super_admin BOOLEAN NOT NULL DEFAULT FALSE")
    assert [statement for statement in listed if statement.startswith("UPDATE")] == [SUPER_ADMIN_BACKFILL]


def test_the_migration_holds_no_account_and_no_password():
    # The first super admin is made with scripts/create_super_admin.py. Nothing is seeded.
    for file in ("005_admin_accounts.sql", "full_schema.sql"):
        sql = (MIGRATIONS / file).read_text(encoding="utf-8").upper()
        assert "INSERT INTO ADMIN_ACCOUNTS" not in sql and "$ARGON2" not in sql


def test_an_accounts_table_from_before_temporary_passwords_expired_gains_the_column_and_keeps_its_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'phase1.db'}")
    older = [table for name, table in Base.metadata.tables.items() if name not in ("admin_accounts", "admin_sessions", "audit_logs")]
    Base.metadata.create_all(bind=engine, tables=older)
    with engine.begin() as connection:
        # admin_accounts as the first version of the login tables made it, with an account in it.
        connection.execute(text(
            "CREATE TABLE admin_accounts (id INTEGER PRIMARY KEY, email VARCHAR(120) NOT NULL UNIQUE, full_name VARCHAR(160) NOT NULL, "
            "password_hash VARCHAR(255) NOT NULL, role VARCHAR(30) NOT NULL DEFAULT 'admin', status VARCHAR(30) NOT NULL DEFAULT 'active', "
            "must_change_password BOOLEAN NOT NULL DEFAULT 0, failed_login_count INTEGER NOT NULL DEFAULT 0, locked_until DATETIME, "
            "last_login_at DATETIME, created_by INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        ))
        connection.execute(text("INSERT INTO admin_accounts (email, full_name, password_hash, role, must_change_password) VALUES ('owner@example.com', 'Sample Owner', 'x', 'super_admin', 1)"))
        connection.execute(text("INSERT INTO admin_accounts (email, full_name, password_hash, role) VALUES ('asha@example.com', 'Asha Example', 'y', 'admin')"))

    init_database_schema(engine)
    init_database_schema(engine)  # every start of the backend runs it again

    assert {"temporary_password_expires_at", "has_been_super_admin"} <= {column["name"] for column in inspect(engine).get_columns("admin_accounts")}
    with sessionmaker(bind=engine)() as db:
        owner, asha = db.query(AdminAccount).order_by(AdminAccount.id).all()
        assert (owner.email, owner.role, owner.must_change_password, owner.temporary_password_expires_at) == ("owner@example.com", "super_admin", True, None)
        # The super admin that was there is marked as one; the admin is not; nothing else changed.
        assert (owner.has_been_super_admin, asha.has_been_super_admin) == (True, False)
        assert (asha.role, asha.password_hash, owner.password_hash) == ("admin", "y", "x")
    engine.dispose()


def test_a_super_admin_written_into_the_table_by_hand_is_marked_at_the_next_start(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'by_hand.db'}")
    init_database_schema(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO admin_accounts (email, full_name, password_hash, role) VALUES ('owner@example.com', 'By Hand', 'x', 'super_admin')"))

    init_database_schema(engine)

    with sessionmaker(bind=engine)() as db:
        assert db.query(AdminAccount).one().has_been_super_admin is True
    engine.dispose()


def test_the_migration_adds_the_expiry_column_to_a_table_made_by_its_earlier_version():
    listed = statements(re.sub(r"--[^\n]*", "", (MIGRATIONS / "005_admin_accounts.sql").read_text(encoding="utf-8")))

    assert "ALTER TABLE admin_accounts ADD COLUMN IF NOT EXISTS temporary_password_expires_at TIMESTAMP" in listed
