import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.audit_log import AuditLog
from app.models.person import Person
from app.schema import init_database_schema, schema_problems
from app.services import attendance_code_service
from app.services.attendance_code_service import (
    ALPHABET, CodeUnavailable, assign_code, fill_missing_codes, format_code, generate_code, normalize_code, qr_payload, regenerate_code,
)

STAFF_HEADER = ["staff_id", "full_name", "contact_number", "email", "course_code", "batch_name", "level_class", "joining_date", "notes"]
CODE = re.compile(r"[0-9A-HJKMNP-TV-Z]{8}")


# ---- the code itself ------------------------------------------------------------------------------

def test_the_alphabet_is_crockford_base32_without_i_l_o_u():
    assert ALPHABET == "0123456789ABCDEFGHJKMNPQRSTVWXYZ" and len(ALPHABET) == 32
    assert not set("ILOU") & set(ALPHABET)


def test_a_code_is_eight_characters_of_the_alphabet_and_codes_do_not_repeat():
    codes = [generate_code() for _ in range(5000)]

    assert all(len(code) == 8 and set(code) <= set(ALPHABET) for code in codes)
    assert len(set(codes)) == len(codes)
    # Every character turns up: the draw is over the whole alphabet, not a part of it.
    assert set("".join(codes)) == set(ALPHABET)


@pytest.mark.parametrize("typed, stored", [
    ("K7M29QXD", "K7M29QXD"),
    ("K7M2-9QXD", "K7M29QXD"),
    ("k7m2-9qxd", "K7M29QXD"),
    ("  K7M2 9QXD  ", "K7M29QXD"),
    ("K7M2 - 9QXD", "K7M29QXD"),
    ("VNXATT:K7M29QXD", "K7M29QXD"),
    ("vnxatt:k7m2-9qxd", "K7M29QXD"),
    ("  VNXATT:K7M2-9QXD\n", "K7M29QXD"),
    # O is read as 0, I and L as 1.
    ("KOM2-9QXD", "K0M29QXD"),
    ("KIM2-9QXL", "K1M29QX1"),
    ("klm29qxd", "K1M29QXD"),
])
def test_what_people_type_or_scan_is_read_as_the_stored_code(typed, stored):
    assert normalize_code(typed) == stored


@pytest.mark.parametrize("typed", [
    "", "   ", None, 12345678, "K7M29QX", "K7M29QXDA", "K7M2-9QX", "K7MU9QXD", "K7M2_9QXD", "K7M2.9QXD", "K7M29QX!",
    "VNXATT:", "VNXATT:K7M2", "https://example.com/K7M29QXD", "VNX:K7M29QXD", "K7M29QXDVNXATT:", "VNXATT:VNXATT:K7M29QXD", "K7M29QXÉ",
])
def test_anything_else_is_not_a_code(typed):
    assert normalize_code(typed) is None


def test_a_code_is_shown_with_a_hyphen_and_put_into_a_qr_with_its_prefix():
    assert format_code("K7M29QXD") == "K7M2-9QXD"
    assert format_code(None) == ""
    assert qr_payload("K7M29QXD") == "VNXATT:K7M29QXD"
    assert normalize_code(qr_payload("K7M29QXD")) == "K7M29QXD" and normalize_code(format_code("K7M29QXD")) == "K7M29QXD"


# ---- giving codes out -----------------------------------------------------------------------------

def add_person(db, code="P-1", attendance_code=None, person_type="student", name="Asha Rao"):
    person = Person(person_code=code, full_name=name, person_type=person_type, attendance_code=attendance_code)
    db.add(person)
    db.commit()
    return person


def test_a_code_already_in_use_is_drawn_again(db_session, monkeypatch):
    add_person(db_session, attendance_code="AAAAAAAA")
    draws = iter(["AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))
    person = Person(person_code="P-2", full_name="Bala", person_type="admin")

    assert assign_code(db_session, person) == "BBBBBBBB"


def test_a_code_given_out_earlier_in_the_same_batch_is_drawn_again(db_session, monkeypatch):
    draws = iter(["AAAAAAAA", "AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))
    taken = set()
    first, second = Person(person_code="P-1", full_name="A", person_type="student"), Person(person_code="P-2", full_name="B", person_type="student")

    assert (assign_code(db_session, first, taken, check_db=False), assign_code(db_session, second, taken, check_db=False)) == ("AAAAAAAA", "BBBBBBBB")
    assert taken == {"AAAAAAAA", "BBBBBBBB"}


def test_running_out_of_draws_is_said_instead_of_looping(db_session, monkeypatch):
    add_person(db_session, attendance_code="AAAAAAAA")
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: "AAAAAAAA")

    with pytest.raises(CodeUnavailable) as refused:
        assign_code(db_session, Person(person_code="P-2", full_name="B", person_type="student"))
    # The error says what happened, never which code.
    assert "AAAAAAAA" not in str(refused.value)


def test_a_person_who_has_a_code_keeps_it(db_session):
    person = add_person(db_session, attendance_code="K7M29QXD")

    assert assign_code(db_session, person) == "K7M29QXD"


def test_the_database_refuses_two_people_with_one_code(db_session):
    add_person(db_session, "P-1", "K7M29QXD")

    with pytest.raises(IntegrityError):
        add_person(db_session, "P-2", "K7M29QXD")
    db_session.rollback()
    # People without a code yet do not conflict with each other.
    add_person(db_session, "P-3")
    add_person(db_session, "P-4")


def test_filling_missing_codes_fills_only_empty_rows_and_a_second_run_changes_nothing(db_session):
    kept = add_person(db_session, "P-1", "K7M29QXD")
    for number in range(2, 6):
        add_person(db_session, f"P-{number}", person_type=("student", "admin", "member")[number % 3])

    assert fill_missing_codes(db_session) == 4
    codes = {person.person_code: person.attendance_code for person in db_session.query(Person)}
    assert codes["P-1"] == "K7M29QXD" and kept.attendance_code == "K7M29QXD"
    assert all(CODE.fullmatch(code) for code in codes.values()) and len(set(codes.values())) == 5
    assert fill_missing_codes(db_session) == 0
    assert {person.person_code: person.attendance_code for person in db_session.query(Person)} == codes


def test_filling_codes_tries_again_when_the_database_refuses_a_round(db_session, monkeypatch):
    add_person(db_session, "P-1", "AAAAAAAA")
    add_person(db_session, "P-2")
    # The first round collides with a code given out after the codes were read (as another backfill
    # or a new person could); the round is taken back and the next one succeeds.
    real = attendance_code_service.assign_code
    rounds = iter(["AAAAAAAA", None])

    def assign(db, person, taken=None, check_db=True):
        code = next(rounds, None)
        if code:
            person.attendance_code = code
            return code
        return real(db, person, taken, check_db)

    monkeypatch.setattr(attendance_code_service, "assign_code", assign)

    assert fill_missing_codes(db_session) == 1
    codes = {person_code: code for person_code, code in db_session.query(Person.person_code, Person.attendance_code)}
    assert codes["P-1"] == "AAAAAAAA" and codes["P-2"] != "AAAAAAAA" and CODE.fullmatch(codes["P-2"])


# ---- new people get a code at once ----------------------------------------------------------------

def test_a_person_created_by_form_gets_a_code(client):
    answer = client.post("/users/create", json={"person_code": "STF-1", "full_name": "Chitra Nair", "person_type": "admin"})

    assert answer.status_code == 200, answer.text
    code = answer.json()["data"]["attendance_code"]
    assert CODE.fullmatch(code)
    with client.db() as db:
        assert db.query(Person).one().attendance_code == code


def test_a_client_cannot_choose_a_code_on_create_or_update(client):
    created = client.post("/users/create", json={"person_code": "STF-1", "full_name": "Chitra Nair", "person_type": "admin", "attendance_code": "AAAAAAAA"}).json()["data"]

    assert created["attendance_code"] != "AAAAAAAA"
    updated = client.put(f"/users/{created['id']}", json={"full_name": "Chitra N", "attendance_code": "BBBBBBBB"})
    assert updated.status_code == 200
    assert updated.json()["data"]["attendance_code"] == created["attendance_code"]
    with client.db() as db:
        assert db.query(Person).one().attendance_code == created["attendance_code"]


def test_a_code_the_database_refuses_at_creation_is_drawn_again(client, monkeypatch):
    with client.db() as db:
        add_person(db, "P-1", "AAAAAAAA")
    # The check before the write sees the code as free (another request took it in between), so the
    # database's unique index refuses it, and the creation draws another one.
    monkeypatch.setattr(attendance_code_service, "code_in_use", lambda db, code: False)
    draws = iter(["AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))

    answer = client.post("/users/create", json={"person_code": "STF-1", "full_name": "Chitra Nair", "person_type": "admin"})

    assert answer.status_code == 200 and answer.json()["data"]["attendance_code"] == "BBBBBBBB"


def test_an_id_taken_meanwhile_is_still_a_conflict_not_a_new_code(client, monkeypatch):
    with client.db() as db:
        add_person(db, "STF-1", "AAAAAAAA")
    # Both requests passed the ID check; the second is refused by the ID's own unique index.
    from app.routes import person_routes

    checks = iter([None])
    real = person_routes.person_with_code
    monkeypatch.setattr(person_routes, "person_with_code", lambda db, code, exclude_id=None: next(checks, "seen") and real(db, code, exclude_id))

    answer = client.post("/users/create", json={"person_code": "STF-1", "full_name": "Someone Else", "person_type": "admin"})

    assert answer.status_code == 409
    with client.db() as db:
        assert db.query(Person).count() == 1


def test_imported_people_get_codes_unique_within_the_upload(client, make_xlsx, monkeypatch):
    # The first draws repeat: the upload must not give one code to two rows.
    draws = iter(["AAAAAAAA", "AAAAAAAA", "BBBBBBBB", "AAAAAAAA", "BBBBBBBB", "CCCCCCCC"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))
    rows = [STAFF_HEADER, ["STF-1", "Chitra Nair", "9876543210"], ["STF-2", "Dev Menon", "9876543211"], ["STF-3", "Esha Pillai", "9876543212"]]

    answer = client.post("/users/upload?person_type=admin", files={"file": ("staff.xlsx", make_xlsx(rows))})

    assert answer.status_code == 200, answer.text
    with client.db() as db:
        assert sorted(code for (code,) in db.query(Person.attendance_code)) == ["AAAAAAAA", "BBBBBBBB", "CCCCCCCC"]


def test_an_imported_person_never_takes_a_code_already_in_use(client, make_xlsx, monkeypatch):
    with client.db() as db:
        add_person(db, "P-1", "AAAAAAAA")
    draws = iter(["AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))

    client.post("/users/upload?person_type=admin", files={"file": ("staff.xlsx", make_xlsx([STAFF_HEADER, ["STF-1", "Chitra Nair", "9876543210"]]))})

    with client.db() as db:
        assert db.query(Person).filter(Person.person_code == "STF-1").one().attendance_code == "BBBBBBBB"


def test_a_code_column_in_an_upload_is_ignored(client, make_xlsx):
    rows = [STAFF_HEADER + ["attendance_code"], ["STF-1", "Chitra Nair", "9876543210", "", "", "", "", "", "", "AAAAAAAA"]]

    answer = client.post("/users/upload?person_type=admin", files={"file": ("staff.xlsx", make_xlsx(rows))})

    assert answer.status_code == 200, answer.text
    assert answer.json()["data"]["ignored_columns"] == ["attendance_code"]
    with client.db() as db:
        code = db.query(Person).one().attendance_code
    assert code != "AAAAAAAA" and CODE.fullmatch(code)


def test_the_import_templates_have_no_code_column(client):
    from app.services.import_service import SPECS

    for spec in SPECS.values():
        assert "attendance_code" not in [column.name for column in spec.columns]


# ---- replacing a code -----------------------------------------------------------------------------

def regenerate(client, person_id):
    return client.post(f"/users/{person_id}/attendance-code/regenerate")


def test_replacing_a_code_gives_a_new_one_and_the_old_one_is_no_ones(client):
    with client.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    answer = regenerate(client, person_id)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    new = body["data"]["attendance_code"]
    assert body["success"] is True and body["data"]["id"] == person_id and body["data"]["person_code"] == "STU-1"
    assert CODE.fullmatch(new) and new != "K7M29QXD"
    with client.db() as db:
        assert db.query(Person).filter(Person.attendance_code == "K7M29QXD").count() == 0
        assert db.get(Person, person_id).attendance_code == new


def test_a_person_without_a_code_gets_their_first_one(client):
    with client.db() as db:
        person_id = add_person(db, "STU-1").id

    assert CODE.fullmatch(regenerate(client, person_id).json()["data"]["attendance_code"])


def test_the_audit_log_says_a_code_was_replaced_without_either_code(client):
    from app.services import audit_service

    with client.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD", name="Asha Rao").id

    new = regenerate(client, person_id).json()["data"]["attendance_code"]

    assert audit_service.ACTIONS["person.attendance_code_regenerated"] == "Attendance code replaced"
    with client.db() as db:
        entry = db.query(AuditLog).filter_by(action="person.attendance_code_regenerated").one()
        assert (entry.target_type, entry.target_id, entry.details) == ("person", person_id, {"person_code": "STU-1", "full_name": "Asha Rao"})
        assert entry.actor_id is not None
    assert "K7M29QXD" not in str(entry.details) and new not in str(entry.details)


def test_replacing_the_code_of_an_unknown_person_is_a_404(client):
    answer = regenerate(client, 999)

    assert answer.status_code == 404
    with client.db() as db:
        assert db.query(AuditLog).filter_by(action="person.attendance_code_regenerated").count() == 0


def test_the_regenerate_route_is_not_swallowed_by_the_person_routes(client):
    with client.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    # GET, PUT and DELETE /users/{id} are other routes; only POST .../regenerate replaces a code.
    assert client.get(f"/users/{person_id}").json()["data"]["attendance_code"] == "K7M29QXD"
    assert client.get(f"/users/{person_id}/attendance-code/regenerate").status_code == 405
    assert regenerate(client, person_id).json()["data"]["attendance_code"] != "K7M29QXD"


def test_replacing_a_code_needs_a_login_and_changes_nothing_without_one(anon_client):
    with anon_client.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    assert regenerate(anon_client, person_id).status_code == 401
    with anon_client.db() as db:
        assert db.get(Person, person_id).attendance_code == "K7M29QXD"


def test_a_replacement_the_database_refuses_is_drawn_again(db_session, monkeypatch):
    add_person(db_session, "P-1", "AAAAAAAA")
    person = add_person(db_session, "P-2", "K7M29QXD")
    monkeypatch.setattr(attendance_code_service, "code_in_use", lambda db, code: False)
    draws = iter(["AAAAAAAA", "BBBBBBBB"])
    monkeypatch.setattr(attendance_code_service, "generate_code", lambda: next(draws))

    assert regenerate_code(db_session, person) == "BBBBBBBB"
    assert db_session.get(Person, person.id).attendance_code == "BBBBBBBB"
    # One audit entry, from the replacement that was saved.
    assert db_session.query(AuditLog).filter_by(action="person.attendance_code_regenerated").count() == 1


def test_every_people_endpoint_shows_the_stored_code(client):
    with client.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    listed, = client.get("/users").json()["data"]
    assert listed["attendance_code"] == "K7M29QXD" and listed["id"] == person_id


# ---- the schema: SQLite upgrade and the startup check ----------------------------------------------

def old_database():
    # A database made before migration 010: user_management without the column or its index.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_user_management_attendance_code"))
        connection.execute(text("ALTER TABLE user_management DROP COLUMN attendance_code"))
        connection.execute(text("INSERT INTO user_management (person_code, full_name, person_type, status, face_enrollment_status) VALUES "
                                "('A-1', 'Asha', 'student', 'active', 'completed'), ('A-2', 'Bala', 'admin', 'active', 'not_started'), ('A-3', 'Chitra', 'member', 'active', 'not_started')"))
    return engine


def test_the_startup_check_names_the_missing_column_and_index_and_migration_010():
    engine = old_database()

    assert schema_problems(engine) == [
        "table user_management has no column attendance_code",
        "user_management has no uq_user_management_attendance_code index (migration 010)",
    ]


def test_the_sqlite_upgrade_adds_the_column_and_index_and_gives_everyone_a_code():
    engine = old_database()

    init_database_schema(engine, upgrade=True)

    indexes = {index["name"]: index for index in inspect(engine).get_indexes("user_management")}
    assert indexes["uq_user_management_attendance_code"]["unique"]
    assert schema_problems(engine) == []
    with engine.connect() as connection:
        rows = dict(connection.execute(text("SELECT person_code, attendance_code FROM user_management")).all())
    assert set(rows) == {"A-1", "A-2", "A-3"} and all(CODE.fullmatch(code) for code in rows.values()) and len(set(rows.values())) == 3
    # Starting again changes nothing: codes already given stay.
    init_database_schema(engine, upgrade=True)
    with engine.connect() as connection:
        assert dict(connection.execute(text("SELECT person_code, attendance_code FROM user_management")).all()) == rows


def test_the_sql_files_add_the_column_and_unique_index_like_the_model():
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    step = (migrations / "010_attendance_codes.sql").read_text(encoding="utf-8")
    full = (migrations / "full_schema.sql").read_text(encoding="utf-8")

    assert "ALTER TABLE user_management ADD COLUMN IF NOT EXISTS attendance_code VARCHAR(16);" in step
    assert re.search(r"CREATE UNIQUE INDEX IF NOT EXISTS uq_user_management_attendance_code\s+ON user_management \(attendance_code\);", step)
    assert "    attendance_code VARCHAR(16),\n" in full
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_management_attendance_code ON user_management (attendance_code);" in full
    # Nothing in the migration changes or removes a row.
    assert not re.search(r"\b(UPDATE|DELETE|DROP|TRUNCATE)\b", re.sub(r"--[^\n]*", "", step), re.IGNORECASE)
    column = Person.__table__.columns["attendance_code"]
    assert column.type.length == 16 and column.nullable


# ---- the backfill script --------------------------------------------------------------------------

def backfill():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_attendance_codes.py"
    spec = importlib.util.spec_from_file_location("backfill_attendance_codes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stored_codes(engine):
    with engine.connect() as connection:
        return dict(connection.execute(text("SELECT person_code, attendance_code FROM user_management")).all())


def test_the_backfill_refuses_before_migration_010_and_changes_nothing():
    engine = old_database()
    said = []

    assert backfill().run(engine, out=said.append) == 1
    assert "010_attendance_codes.sql" in said[0] and "Nothing was changed" in said[0]
    assert "attendance_code" not in {column["name"] for column in inspect(engine).get_columns("user_management")}


def test_the_backfill_refuses_with_the_column_but_without_the_unique_index():
    engine = old_database()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE user_management ADD COLUMN attendance_code VARCHAR(16)"))
    said = []

    assert backfill().run(engine, out=said.append) == 1 and "uq_user_management_attendance_code" in said[0]
    assert set(stored_codes(engine).values()) == {None}


def migrated_with_people():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO user_management (person_code, full_name, person_type, status, face_enrollment_status, attendance_code) VALUES "
                                "('A-1', 'Asha', 'student', 'active', 'completed', 'K7M29QXD'), ('A-2', 'Bala', 'admin', 'active', 'not_started', NULL), "
                                "('A-3', 'Chitra', 'member', 'active', 'not_started', NULL)"))
    return engine


def test_a_dry_run_only_counts():
    engine = migrated_with_people()
    said = []

    assert backfill().run(engine, dry_run=True, out=said.append) == 0
    assert said == ["Dry run: 2 of 3 people have no attendance code and would get one. Nothing was changed."]
    assert stored_codes(engine) == {"A-1": "K7M29QXD", "A-2": None, "A-3": None}


def test_the_backfill_fills_only_the_empty_codes_says_only_counts_and_can_run_again():
    engine = migrated_with_people()
    said = []

    assert backfill().run(engine, out=said.append) == 0
    codes = stored_codes(engine)
    assert codes["A-1"] == "K7M29QXD" and all(CODE.fullmatch(code) for code in codes.values()) and len(set(codes.values())) == 3
    assert said == ["Gave 2 people an attendance code. 1 already had one and were left as they were."]
    assert backfill().run(engine, out=said.append) == 0
    assert said[-1] == "Nothing to do: all 3 people already have an attendance code."
    assert stored_codes(engine) == codes
    # No code, no name is ever printed.
    assert not any(code in line or name in line for line in said for code in codes.values() for name in ("Asha", "Bala", "Chitra"))


def test_a_backfill_that_fails_says_only_the_kind_of_error_and_writes_nothing(monkeypatch):
    module = backfill()
    engine = migrated_with_people()

    def broken(session):
        for number, person in enumerate(session.query(Person).filter(Person.attendance_code.is_(None))):
            person.attendance_code = f"SECRET0{number}"
        session.flush()
        raise CodeUnavailable("SECRET01 could not be used")

    monkeypatch.setattr(module, "fill_missing_codes", broken)
    said = []

    assert module.run(engine, out=said.append) == 2
    assert said == ["The codes could not be written (CodeUnavailable). Nothing was changed."]
    assert stored_codes(engine) == {"A-1": "K7M29QXD", "A-2": None, "A-3": None}


# ---- who may replace a code (the QR card's Replace code and Create code) ---------------------------

@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_any_console_account_may_replace_a_code_and_the_answer_is_the_usual_shape(signed_in, backend, role):
    # Every /users route is open to logged-in console accounts (main.py, require_admin); a QR card
    # is shown and replaced by the same accounts that see and edit the person.
    client = signed_in(f"{role}@example.com", role=role)
    with backend.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    answer = regenerate(client, person_id)

    assert answer.status_code == 200
    assert set(answer.json()) == {"success", "message", "data"} and answer.json()["message"] == "Attendance code replaced"
    assert CODE.fullmatch(answer.json()["data"]["attendance_code"]) and answer.json()["data"]["attendance_code"] != "K7M29QXD"


@pytest.mark.parametrize("fields", [{"status": "disabled"}, {"must_change_password": True}])
def test_an_account_that_may_not_work_yet_cannot_replace_a_code(signed_in, backend, fields):
    client = signed_in("someone@example.com", **fields)
    with backend.db() as db:
        person_id = add_person(db, "STU-1", "K7M29QXD").id

    answer = regenerate(client, person_id)

    assert answer.status_code in (401, 403)
    with backend.db() as db:
        assert db.get(Person, person_id).attendance_code == "K7M29QXD"
        assert db.query(AuditLog).filter_by(action="person.attendance_code_regenerated").count() == 0
