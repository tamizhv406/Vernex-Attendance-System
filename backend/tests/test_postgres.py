"""The parts that depend on the database engine, on a real PostgreSQL server.

Skipped unless VERNEX_TEST_POSTGRES_URL names a PostgreSQL server ON THIS COMPUTER, as an account
that may create databases. The tests create databases of their own (vx_test_...) and drop them at
the end; they refuse any host but localhost, so a Supabase or other shared server can never be used.

    VERNEX_TEST_POSTGRES_URL=postgresql://user@127.0.0.1:5432/postgres  pytest tests/test_postgres.py

Every database is set to GMT (UTC), the time zone Supabase's databases use.
"""
import asyncio
import json
import os
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.issue import Issue
from app.models.person import Person
from app.schema import ROW_SECURITY_TABLES, SchemaNotReady, init_database_schema, schema_problems
from app.utils.time_utils import now_local, today_local

POSTGRES_URL = os.environ.get("VERNEX_TEST_POSTGRES_URL", "").strip()
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
NUMBERED = sorted(path.name for path in MIGRATIONS.glob("0*.sql"))

pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="VERNEX_TEST_POSTGRES_URL is not set: no local PostgreSQL to test on")


@pytest.fixture(scope="module")
def server():
    url = make_url(POSTGRES_URL)
    if url.get_backend_name() != "postgresql" or url.host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("VERNEX_TEST_POSTGRES_URL must point to a PostgreSQL server on this computer: these tests create and drop databases.")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    made = []

    def database(label):
        name = f"vx_test_{secrets.token_hex(3)}_{label}"
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
            connection.execute(text(f"ALTER DATABASE \"{name}\" SET timezone TO 'GMT'"))
        made.append(name)
        return create_engine(url.set(database=name), hide_parameters=True)

    yield database
    with admin.connect() as connection:
        for name in made:
            connection.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name AND pid <> pg_backend_pid()"), {"name": name})
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


def run_sql(engine, *files):
    # A migration file as psql runs it: all of its statements, DO blocks included, in one go.
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        for name in files:
            # utf-8-sig: 004 starts with a byte order mark, which psql skips and the driver would not.
            cursor.execute((MIGRATIONS / name).read_text(encoding="utf-8-sig"))
        raw.commit()
    finally:
        raw.close()


@pytest.fixture()
def migrated(server):
    engine = server("full")
    run_sql(engine, "full_schema.sql")
    yield engine
    engine.dispose()


def tables(engine):
    return sorted(inspect(engine).get_table_names())


# ---- the schema files -----------------------------------------------------------------------------

def test_full_schema_gives_a_new_database_everything_the_backend_checks_for(migrated):
    assert schema_problems(migrated) == []
    # And it can be run again on it.
    run_sql(migrated, "full_schema.sql")
    assert schema_problems(migrated) == []


def test_the_numbered_migrations_in_order_do_the_same_and_can_be_run_again(server):
    engine = server("steps")
    run_sql(engine, *NUMBERED)
    assert NUMBERED[-1] == "009_app_role.sql" and schema_problems(engine) == []
    run_sql(engine, *NUMBERED)
    assert schema_problems(engine) == []
    engine.dispose()


def test_migration_003_runs_on_postgresql(server):
    # Until October 2026 it stopped with "invalid reference to FROM-clause entry for table r".
    engine = server("m003")
    run_sql(engine, "001_initial_schema.sql", "002_courses_and_user_management.sql", "003_course_batch_attendance_restructure.sql")
    assert {"courses", "batches", "attendance_records"} <= set(tables(engine))
    engine.dispose()


def test_the_schema_the_files_make_matches_the_one_the_backend_makes(server, migrated):
    # Column by column, for every table of the models: name, type and whether it may be empty.
    made = server("orm")
    init_database_schema(made, upgrade=True)

    def columns(engine):
        found = {}
        for table in ROW_SECURITY_TABLES:
            for column in inspect(engine).get_columns(table):
                found[(table, column["name"])] = (str(column["type"]).split("(")[0], column["nullable"])
        return found

    assert columns(migrated) == columns(made)
    made.dispose()


def test_the_files_and_the_backend_agree_on_keys_delete_rules_and_unique_indexes(server, migrated):
    # Beyond the columns: which table each foreign key points at, what happens on delete, and which
    # columns must be unique. A difference here behaves differently on Supabase than in the tests.
    made = server("orm_keys")
    init_database_schema(made, upgrade=True)

    def keys(engine):
        inspector = inspect(engine)
        found = {}
        for table in ROW_SECURITY_TABLES:
            for key in inspector.get_foreign_keys(table):
                found[(table, tuple(key["constrained_columns"]))] = (key["referred_table"], tuple(key["referred_columns"]), (key.get("options") or {}).get("ondelete"))
            for index in inspector.get_indexes(table):
                if index["unique"]:
                    found[(table, "unique", tuple(index["column_names"]))] = True
            for constraint in inspector.get_unique_constraints(table):
                found[(table, "unique", tuple(constraint["column_names"]))] = True
        return found

    files, backend = keys(migrated), keys(made)
    assert {k: v for k, v in files.items() if backend.get(k) != v} == {} and {k: v for k, v in backend.items() if files.get(k) != v} == {}
    made.dispose()


# ---- what the backend does when it starts -----------------------------------------------------------

def statements_while(engine, action):
    seen = []
    listener = lambda conn, cursor, statement, params, context, many: seen.append(" ".join(statement.split()))  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return seen


def test_starting_on_a_ready_database_only_reads(migrated):
    seen = statements_while(migrated, lambda: init_database_schema(migrated))

    assert seen and all(statement.upper().startswith(("SELECT", "WITH", "SHOW")) for statement in seen), [s for s in seen if not s.upper().startswith(("SELECT", "WITH", "SHOW"))]


def test_starting_on_an_empty_database_refuses_and_creates_nothing(server):
    engine = server("empty")

    with pytest.raises(SchemaNotReady) as refused:
        init_database_schema(engine)

    assert "table admin_accounts is missing" in str(refused.value) and "nothing was changed" in str(refused.value)
    assert tables(engine) == []
    engine.dispose()


def test_a_missing_column_index_or_row_level_security_is_named(migrated):
    with migrated.begin() as connection:
        connection.execute(text("ALTER TABLE face_embeddings DROP COLUMN capture_meta"))
        connection.execute(text("DROP INDEX uq_attendance_session_person_date"))
        connection.execute(text("ALTER TABLE user_management DISABLE ROW LEVEL SECURITY"))

    problems = schema_problems(migrated)

    assert problems == [
        "table face_embeddings has no column capture_meta",
        "attendance_records has no uq_attendance_session_person_date index (migration 004)",
        "row level security is off for user_management (migration 008)",
    ]


def test_an_account_that_row_level_security_would_shut_out_is_named(migrated):
    # A role that neither owns the tables nor bypasses row level security would see empty tables.
    role = f"vx_reader_{secrets.token_hex(3)}"
    with migrated.begin() as connection:
        connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}"))
    try:
        with migrated.connect() as connection:
            connection.execute(text(f"SET ROLE {role}"))
            problems = schema_problems(connection)
            connection.rollback()
        assert any(problem.startswith("the database account this backend uses would see no rows of ") for problem in problems)
    finally:
        with migrated.begin() as connection:
            connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
            connection.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {role}"))
            connection.execute(text(f"DROP ROLE {role}"))


def test_the_old_start_up_changes_still_work_when_asked_for(server, migrated):
    # DATABASE_AUTO_UPGRADE=true or scripts/init_db.py: on an empty database, and on a migrated one.
    empty = server("legacy")
    init_database_schema(empty, upgrade=True)
    init_database_schema(migrated, upgrade=True)

    assert schema_problems(empty) == [] and schema_problems(migrated) == []
    empty.dispose()


# ---- Supabase's public roles ------------------------------------------------------------------------

def test_with_supabase_grants_the_public_role_reaches_no_row(migrated):
    # Supabase gives its anon role rights on every table of the public schema. Row level security on
    # every table (008) leaves it nothing to read or change; the owner, as which the backend connects,
    # still sees everything.
    role = f"vx_anon_{secrets.token_hex(3)}"
    with migrated.begin() as connection:
        connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
        connection.execute(text("INSERT INTO user_management (person_code, full_name, person_type, status, face_enrollment_status) VALUES ('SYN-1', 'Synthetic Student', 'student', 'active', 'completed')"))
        connection.execute(text("INSERT INTO face_embeddings (person_id, embedding_vector, pose_type, model_name, is_active) SELECT id, '[0.1]', 'front', 'test', true FROM user_management"))
    try:
        with migrated.connect() as connection:
            connection.execute(text(f"SET ROLE {role}"))
            seen = {table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() for table in ROW_SECURITY_TABLES}
            changed = connection.execute(text("UPDATE user_management SET full_name = 'changed'")).rowcount
            connection.rollback()
        with migrated.connect() as connection:
            owner_sees = connection.execute(text("SELECT count(*) FROM face_embeddings")).scalar()
        assert set(seen.values()) == {0} and changed == 0 and owner_sees == 1
    finally:
        with migrated.begin() as connection:
            connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
            connection.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {role}"))
            connection.execute(text(f"DROP ROLE {role}"))


# ---- attendance on PostgreSQL ------------------------------------------------------------------------

@pytest.fixture()
def school(migrated):
    session_factory = sessionmaker(bind=migrated, autoflush=False)
    with session_factory() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.commit()
        student = Person(person_code="STU-1", full_name="Synthetic Student", person_type="student", course_id=course.id, batch_id=batch.id, face_enrollment_status="completed")
        db.add(student)
        db.commit()
        session = AttendanceSession(session_name="Class", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add(session)
        db.commit()
        ids = {"course": course.id, "batch": batch.id, "student": student.id, "session": session.id}
    return session_factory, ids


def test_many_writers_at_once_leave_exactly_one_record(school):
    # Each thread is a separate connection, as separate backend processes would be, and none of them
    # waits for the others (the in-process lock is not used): the unique index alone decides.
    from app.schemas.attendance_schema import AttendanceMark
    from app.services.attendance_service import write_attendance

    session_factory, ids = school
    start, answers = threading.Barrier(12), []

    def write():
        with session_factory() as db:
            start.wait()
            record, message = write_attendance(db, AttendanceMark(session_id=ids["session"], person_id=ids["student"], recognition_method="face_ai", confidence_score=0.9))
            answers.append(message)

    threads = [threading.Thread(target=write) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with session_factory() as db:
        assert db.query(AttendanceRecord).count() == 1
    assert sorted(set(answers)) == ["Already marked", "Attendance marked"] and answers.count("Attendance marked") == 1


def test_the_time_a_record_was_marked_is_the_schools_local_time(school):
    # The database is on UTC, like Supabase. The record must still say the time on the school's clock,
    # as it does on SQLite; until October 2026 PostgreSQL stored it shifted to UTC.
    from app.schemas.attendance_schema import AttendanceMark
    from app.services.attendance_service import mark_attendance

    session_factory, ids = school
    with session_factory() as db:
        before = now_local().replace(tzinfo=None)
        record, _ = mark_attendance(db, AttendanceMark(session_id=ids["session"], person_id=ids["student"]))
        stored = db.execute(text("SELECT marked_time FROM attendance_records WHERE id = :id"), {"id": record.id}).scalar()
    assert abs(stored - before) < timedelta(minutes=1), (stored, before)


def test_the_scanner_marks_a_student_on_postgresql(school, monkeypatch, clock):
    # The scanner's whole decision with the camera and the models replaced, writing to PostgreSQL.
    from app.config import settings
    from app.routes import face_routes
    from test_recognition_flow import SEATS, VECTORS, FakeRequest, FRAME_BASE64

    session_factory, ids = school
    with session_factory() as db:
        for pose in face_routes.REQUIRED_STEPS:
            db.add(FaceEmbedding(person_id=ids["student"], embedding_vector=json.dumps(list(VECTORS["Arun"])), pose_type=pose, model_name=face_routes.model_label(), is_active=True))
        db.commit()
    clock.step = 0
    face = {"box": list(SEATS[0]), "embedding": list(VECTORS["Arun"]), "detection_confidence": 0.9, "turn": 0.0}
    monkeypatch.setattr(settings, "face_challenge", "off")
    monkeypatch.setattr(face_routes, "detect_faces", lambda image: [face])
    monkeypatch.setattr(face_routes, "judge_liveness", lambda image, boxes: [("live", 0.98)] * len(boxes))
    face_routes.gallery_cache.clear()
    face_routes.session_cache.clear()
    face_routes.marked_today.clear()

    answers = []
    with session_factory() as db:
        for _ in range(4):
            clock.advance(1.0)
            body = {"session_id": ids["session"], "image_base64": FRAME_BASE64, "scanner_id": "pg", "device_name": "test"}
            answers.append(asyncio.run(face_routes.recognize(FakeRequest(body), db))["faces"][0]["result"])
        rows = [(r.person_id, r.session_id, r.attendance_date, r.recognition_method) for r in db.query(AttendanceRecord)]

    assert "verified" in answers and answers[-1] == "already_marked"
    assert rows == [(ids["student"], ids["session"], today_local(), "face_ai")]


def test_an_issue_being_changed_is_locked_against_a_second_change(migrated):
    # issue_service._held takes the row with SELECT ... FOR UPDATE on PostgreSQL. While the first
    # request holds it, a second cannot take it (NOWAIT shows it instead of waiting).
    from app.services import issue_service
    from conftest import add_account

    session_factory = sessionmaker(bind=migrated, autoflush=False)
    with session_factory() as db:
        account = add_account(db, "reporter@example.com")
        issue = Issue(title="Scanner froze", description="It stopped after a while.", category="bug", severity="low", reported_by=account.id)
        db.add(issue)
        db.commit()
        issue_id = issue.id
    first, second = session_factory(), session_factory()
    try:
        issue_service._held(first, issue_id)
        with pytest.raises(OperationalError):
            second.execute(text("SELECT id FROM issues WHERE id = :id FOR UPDATE NOWAIT"), {"id": issue_id})
        second.rollback()
        first.commit()
        assert second.execute(text("SELECT id FROM issues WHERE id = :id FOR UPDATE NOWAIT"), {"id": issue_id}).scalar() == issue_id
    finally:
        first.close()
        second.close()


# ---- the application over HTTP, on PostgreSQL ------------------------------------------------------------

def as_app_role(engine):
    # The same database, reached as the least-privilege account of migration 009 (no password is
    # needed on this local test server).
    with engine.begin() as connection:
        connection.execute(text("ALTER ROLE vernex_app WITH LOGIN"))
    return create_engine(engine.url.set(username="vernex_app"), hide_parameters=True)


@pytest.mark.parametrize("account", ["owner", "vernex_app"])
def test_the_console_works_end_to_end_on_postgresql(migrated, monkeypatch, account):
    from fastapi.testclient import TestClient

    from app import database
    from app.main import app
    from conftest import add_account

    bind = migrated if account == "owner" else as_app_role(migrated)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    with session_factory() as db:
        add_account(db, "owner@example.com", password="A long synthetic passphrase 42", role="super_admin", full_name="Synthetic Owner")
    client = TestClient(app, base_url="https://testserver", headers={"X-Requested-With": "vernex"})

    login = client.post("/auth/login", json={"email": "owner@example.com", "password": "A long synthetic passphrase 42"})
    assert login.status_code == 200, login.text
    client.headers["Authorization"] = f"Bearer {login.json()['data']['access_token']}"

    course = client.post("/courses/create", json={"course_code": "PG101", "course_name": "Postgres Course"}).json()["data"]
    batch = client.post("/batches/create", json={"course_id": course["id"], "batch_name": "Batch P"}).json()["data"]
    student = client.post("/users/create", json={"person_code": "PG-1", "full_name": "Synthetic Student", "person_type": "student", "course_id": course["id"], "batch_id": batch["id"]})
    assert student.status_code == 200, student.text
    student = student.json()["data"]
    session = client.post("/attendance/session/start", json={"session_name": "Class", "session_type": "regular", "course_id": course["id"], "batch_id": batch["id"]}).json()["data"]
    assert session["session_date"] == today_local().isoformat()

    marks = [client.post("/attendance/mark", json={"session_id": session["id"], "person_id": student["id"]}) for _ in range(2)]
    corrected = client.post("/attendance/mark", json={"session_id": session["id"], "person_id": student["id"], "status": "late"})
    assert [answer.json()["message"] for answer in marks + [corrected]] == ["Attendance marked", "Already marked", "Attendance updated"]
    records = client.get(f"/attendance/session/{session['id']}/records").json()["data"]
    assert [(r["person_id"], r["status"], r["recognition_method"]) for r in records] == [(student["id"], "late", "manual")]

    issue = client.post("/issues", json={"title": "Camera is slow", "description": "Frames take long to check.", "category": "camera_device", "severity": "low", "page_url": "/scanner", "device_info": {"browser": "Edge", "os": "Windows", "screen": "1280x720"}})
    assert issue.status_code == 200, issue.text
    issue_id = issue.json()["data"]["id"]
    assert client.put(f"/super-admin/issues/{issue_id}", json={"status": "in_progress"}).status_code == 200
    resolved = client.put(f"/super-admin/issues/{issue_id}", json={"status": "resolved", "resolution_note": "Lowered the frame size."})
    assert resolved.status_code == 200 and resolved.json()["data"]["status"] == "resolved"
    assert client.get("/super-admin/dashboard").status_code == 200

    actions = {row["action"] for row in client.get("/super-admin/audit-logs?page_size=100").json()["data"]["items"]}
    assert {"attendance.marked", "issue.created", "issue.status_changed"} <= actions



# ---- the least-privilege account (migration 009, task S-02) --------------------------------------------

def test_the_app_account_passes_the_start_up_check(migrated):
    app_engine = as_app_role(migrated)

    assert schema_problems(app_engine) == []
    app_engine.dispose()


@pytest.mark.parametrize("statement", [
    "CREATE TABLE stolen (id int)",
    "ALTER TABLE courses ADD COLUMN extra text",
    "DROP TABLE issue_comments",
    "ALTER TABLE user_management DISABLE ROW LEVEL SECURITY",
    "TRUNCATE attendance_records",
])
def test_the_app_account_cannot_change_the_schema(migrated, statement):
    app_engine = as_app_role(migrated)
    with app_engine.connect() as connection:
        with pytest.raises(Exception) as refused:
            connection.execute(text(statement))
        connection.rollback()
    app_engine.dispose()

    assert "permission denied" in str(refused.value) or "must be owner" in str(refused.value)


def test_the_audit_log_is_add_only_for_the_app_account(migrated):
    app_engine = as_app_role(migrated)
    with app_engine.begin() as connection:
        connection.execute(text("INSERT INTO audit_logs (action, details) VALUES ('test.entry', NULL)"))
    for statement in ("UPDATE audit_logs SET action = 'changed'", "DELETE FROM audit_logs"):
        with app_engine.connect() as connection:
            with pytest.raises(Exception) as refused:
                connection.execute(text(statement))
            connection.rollback()
        assert "permission denied" in str(refused.value)
    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT action FROM audit_logs")).scalars().all() == ["test.entry"]
    app_engine.dispose()


def test_an_account_without_rights_is_named_by_the_check(migrated):
    role = f"vx_bare_{secrets.token_hex(3)}"
    with migrated.begin() as connection:
        connection.execute(text(f"CREATE ROLE {role} NOLOGIN BYPASSRLS"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}"))
    try:
        with migrated.connect() as connection:
            connection.execute(text(f"SET ROLE {role}"))
            problems = schema_problems(connection)
            connection.rollback()
        assert any(problem.startswith("the database account this backend uses lacks the rights to read and write ") for problem in problems), problems
    finally:
        with migrated.begin() as connection:
            connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
            connection.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {role}"))
            connection.execute(text(f"DROP ROLE {role}"))


def test_the_public_role_still_gets_nothing_next_to_the_app_policy(migrated):
    # The policy is for vernex_app alone; Supabase's anon role, with its default grants, still gets no rows.
    role = f"vx_anon_{secrets.token_hex(3)}"
    with migrated.begin() as connection:
        connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
        connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
        connection.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
        connection.execute(text("INSERT INTO courses (course_code, course_name) VALUES ('SYN', 'Synthetic')"))
    try:
        with migrated.connect() as connection:
            connection.execute(text(f"SET ROLE {role}"))
            seen = connection.execute(text("SELECT count(*) FROM courses")).scalar()
            connection.rollback()
        assert seen == 0
    finally:
        with migrated.begin() as connection:
            connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
            connection.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {role}"))
            connection.execute(text(f"DROP ROLE {role}"))


# ---- no server error on PostgreSQL for values SQLite would have taken ------------------------------------
# SQLite stores a value longer than its column and compares any text with a date; PostgreSQL refuses
# both with a database error. Until October 2026 five routes answered such a request with a 500.

def test_no_route_answers_a_server_error_to_long_or_odd_values(migrated, monkeypatch):
    from fastapi.testclient import TestClient

    from app import database
    from app.main import app
    from app.utils import rate_limit
    from conftest import add_account

    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=migrated)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(rate_limit.frames, "limit", 10_000)
    # /health/ready answers 503 until the face models are loaded, as it should; they are not loaded here.
    from app.services import face_service

    monkeypatch.setattr(face_service, "models_ready", True)
    with session_factory() as db:
        add_account(db, "fuzz@example.com", password="A long synthetic passphrase 42", role="super_admin")
    client = TestClient(app, base_url="https://testserver", headers={"X-Requested-With": "vernex"})
    token = client.post("/auth/login", json={"email": "fuzz@example.com", "password": "A long synthetic passphrase 42"}).json()["data"]["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    spec = app.openapi()
    components = spec["components"]["schemas"]

    def resolve(schema):
        while "$ref" in schema:
            schema = components[schema["$ref"].split("/")[-1]]
        if "anyOf" in schema:
            options = [item for item in schema["anyOf"] if item.get("type") != "null"]
            return resolve(options[0]) if options else {}
        return schema

    def value(schema, mode):
        schema = resolve(schema)
        if "enum" in schema or "const" in schema:
            return (schema.get("enum") or [schema.get("const")])[0]
        kind, form = schema.get("type"), schema.get("format")
        if kind == "integer":
            return 1 if mode == "long" else 2_147_483_648
        if kind == "number":
            return 1e308
        if kind == "boolean":
            return True
        if kind == "string" and form in ("time", "date", "date-time"):
            return {"time": "09:00:00", "date": "2026-10-15", "date-time": "2026-10-15T09:00:00"}[form]
        if kind == "object":
            return {"browser": "x" * 1000, "os": "x", "screen": "x"}
        return "x" * 1000

    errors, sent = [], 0
    for path, operations in spec["paths"].items():
        target = path.replace("{", "").replace("}", "")
        target = "/".join("1" if part.endswith("_id") else part for part in target.split("/"))
        for method, operation in operations.items():
            if method == "delete":
                continue
            content = operation.get("requestBody", {}).get("content", {}).get("application/json")
            for mode in ("long", "big"):
                body = {key: value(item, mode) for key, item in resolve(content["schema"]).get("properties", {}).items()} if content else None
                for parameter in operation.get("parameters", []):
                    if parameter.get("in") != "query":
                        continue
                    for odd in ("not-a-date", "x" * 2000, 2_147_483_648):
                        answer = client.request(method.upper(), target, params={parameter["name"]: odd}, json=body)
                        sent += 1
                        if answer.status_code >= 500:
                            errors.append((method, path, parameter["name"], str(odd)[:12]))
                answer = client.request(method.upper(), target, json=body)
                sent += 1
                if answer.status_code >= 500:
                    errors.append((method, path, mode))

    assert sent > 300 and errors == []
