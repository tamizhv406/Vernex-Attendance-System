from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.schemas.attendance_schema import AttendanceMark
from app.schema import init_database_schema
from app.services import attendance_service
from app.services.attendance_service import mark_attendance


def _seed_course_batch(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    batch = CourseBatch(course_id=course.id, batch_name="Morning A")
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    return course, batch


# Until Phase 2 of the staff upgrade, staff without a batch could be marked into any batch class. A
# batch class is now for whoever is assigned to it; staff without a batch have a staff session.
def test_staff_without_a_batch_are_refused_in_a_batch_class_and_marked_in_a_staff_session(db_session):
    course, batch = _seed_course_batch(db_session)

    session = AttendanceSession(
        session_name="Morning",
        session_type="class",
        course_id=course.id,
        batch_id=batch.id,
        session_date=date(2026, 1, 1),
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    staff = Person(
        person_code="T1",
        full_name="Bob",
        person_type="staff",
        course_id=None,
        batch_id=None,
    )
    db_session.add(staff)
    db_session.commit()
    db_session.refresh(staff)

    staff.person_type = "admin"
    staff_session = AttendanceSession(session_name="Staff attendance", session_type="staff", session_date=date(2026, 1, 1))
    db_session.add(staff_session)
    db_session.commit()

    assert mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=staff.id)) == (None, "Bob is not in this batch.")
    record, message = mark_attendance(db_session, AttendanceMark(session_id=staff_session.id, person_id=staff.id))

    assert record is not None, f"expected staff to be marked present, got rejection: {message}"
    assert record.status in {"present", "late"}


def test_student_is_still_rejected_for_mismatched_course(db_session):
    course, batch = _seed_course_batch(db_session)
    other_course = Course(course_code="EE101", course_name="Electrical")
    db_session.add(other_course)
    db_session.commit()
    db_session.refresh(other_course)

    session = AttendanceSession(
        session_name="Morning",
        session_type="class",
        course_id=course.id,
        batch_id=batch.id,
        session_date=date(2026, 1, 1),
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    student = Person(
        person_code="S1",
        full_name="Alice",
        person_type="student",
        course_id=other_course.id,
        batch_id=None,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    payload = AttendanceMark(session_id=session.id, person_id=student.id)
    record, message = mark_attendance(db_session, payload)

    assert record is None
    assert message == "Alice is not in this batch."


def _session_and_student(db_session):
    course, batch = _seed_course_batch(db_session)
    session = AttendanceSession(session_name="Morning", session_type="class", course_id=course.id, batch_id=batch.id, session_date=date(2026, 1, 1))
    student = Person(person_code="S1", full_name="Alice", person_type="student", course_id=course.id, batch_id=batch.id)
    db_session.add_all([session, student])
    db_session.commit()
    return session, student


def test_marking_twice_keeps_one_record(db_session):
    session, student = _session_and_student(db_session)

    first, first_message = mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=student.id))
    second, second_message = mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=student.id))

    assert (first_message, second_message) == ("Attendance marked", "Already marked")
    assert second.id == first.id and second.duplicate_flag is True
    assert db_session.query(AttendanceRecord).count() == 1
    assert (first.course_id, first.batch_id, first.session_id) == (session.course_id, session.batch_id, session.id)


def test_the_database_itself_refuses_a_second_record(db_session):
    session, student = _session_and_student(db_session)
    mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=student.id))
    first = db_session.query(AttendanceRecord).one()

    db_session.add(AttendanceRecord(session_id=session.id, person_id=student.id, attendance_date=first.attendance_date, status="present"))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.query(AttendanceRecord).count() == 1


def test_a_record_written_by_someone_else_in_the_same_moment_is_not_doubled(db_session, monkeypatch):
    # The "is there a record already?" look comes back empty, as it does when another process is
    # writing at that very moment. The unique index catches it and the existing record is returned.
    session, student = _session_and_student(db_session)
    first, _ = mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=student.id))
    real = attendance_service.find_today_record
    looks = iter([None])
    monkeypatch.setattr(attendance_service, "find_today_record", lambda *args: next(looks, None) or real(*args))

    record, message = mark_attendance(db_session, AttendanceMark(session_id=session.id, person_id=student.id))

    assert message == "Already marked" and record.id == first.id
    assert db_session.query(AttendanceRecord).count() == 1


def test_many_requests_at_once_write_one_record_per_student(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        course, batch = _seed_course_batch(db)
        session = AttendanceSession(session_name="Morning", session_type="class", course_id=course.id, batch_id=batch.id, session_date=date(2026, 1, 1))
        students = [Person(person_code=f"S{index}", full_name=f"Student {index}", person_type="student", course_id=course.id, batch_id=batch.id) for index in range(10)]
        db.add_all([session, *students])
        db.commit()
        session_id, student_ids = session.id, [student.id for student in students]

    def mark(person_id):
        with factory() as db:
            return mark_attendance(db, AttendanceMark(session_id=session_id, person_id=person_id))[1]

    # Every student is marked by four scanners at the same moment.
    with ThreadPoolExecutor(max_workers=16) as pool:
        messages = list(pool.map(mark, student_ids * 4))

    with factory() as db:
        rows = db.query(AttendanceRecord).all()
        assert sorted(row.person_id for row in rows) == sorted(student_ids)
    assert messages.count("Attendance marked") == 10 and messages.count("Already marked") == 30
    engine.dispose()


def test_an_older_database_gets_the_new_column_and_index_without_losing_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        # Back to how the tables looked before this version.
        connection.execute(text("DROP INDEX uq_attendance_session_person_date"))
        connection.execute(text("ALTER TABLE face_embeddings DROP COLUMN capture_meta"))
        connection.execute(text("INSERT INTO attendance_records (session_id, person_id, attendance_date, status, recognition_method, duplicate_flag, sync_status) VALUES (1, 1, '2026-01-01', 'present', 'face_ai', 0, 'pending')"))

    init_database_schema(engine)
    init_database_schema(engine)

    with engine.begin() as connection:
        assert "capture_meta" in {column["name"] for column in inspect(connection).get_columns("face_embeddings")}
        assert connection.execute(text("SELECT COUNT(*) FROM attendance_records")).scalar() == 1
        with pytest.raises(IntegrityError):
            connection.execute(text("INSERT INTO attendance_records (session_id, person_id, attendance_date, status, recognition_method, duplicate_flag, sync_status) VALUES (1, 1, '2026-01-01', 'present', 'face_ai', 0, 'pending')"))
    engine.dispose()


def test_existing_duplicates_are_reported_not_deleted(tmp_path, capsys):
    engine = create_engine(f"sqlite:///{tmp_path / 'dupes.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX uq_attendance_session_person_date"))
        for _ in range(2):
            connection.execute(text("INSERT INTO attendance_records (session_id, person_id, attendance_date, status, recognition_method, duplicate_flag, sync_status) VALUES (1, 1, '2026-01-01', 'present', 'face_ai', 0, 'pending')"))

    init_database_schema(engine)

    with engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM attendance_records")).scalar() == 2
    assert "NOT created" in capsys.readouterr().out
    engine.dispose()


# ---- marking by hand, through the routes, for each kind of session ------------------------------
# recognition_method "auto_absent" means absent: /attendance/mark-absent sets it, and a record marked
# with it is absent in every kind of session, a member visit included. Every other method follows
# the session (a member visit is "visited", a class is "present", or "late"/"absent" by its times).

RECORD_FIELDS = {
    "id", "session_id", "person_id", "person_code", "person_name", "person_type", "course_id", "batch_id", "category_program",
    "batch_name", "level_class", "attendance_date", "marked_time", "status", "confidence_score", "recognition_method",
    "device_name", "marked_by", "duplicate_flag", "sync_status", "notes", "created_at", "updated_at",
}


@pytest.fixture()
def visit(client):
    def make(session_type):
        from app.utils.time_utils import today_local

        with client.db() as db:
            # A member: no course or batch to match. No grace or end time: nothing makes it late.
            member = Person(person_code="MEM-1", full_name="Sample Member", person_type="member")
            session = AttendanceSession(session_name="Visit", session_type=session_type, session_date=today_local(), status="active")
            db.add_all([member, session])
            db.commit()
            return {"session_id": session.id, "person_id": member.id}
    return make


def stored_records(client):
    with client.db() as db:
        return [(record.status, record.recognition_method) for record in db.query(AttendanceRecord)]


@pytest.mark.parametrize("session_type, route, method, status, saved_method", [
    ("regular", "/attendance/mark", "manual", "present", "manual"),
    # A hand mark is never stored as a face scan, whatever the browser says (it was, until 2026-10).
    ("regular", "/attendance/mark", "face_ai", "present", "manual"),
    ("regular", "/attendance/mark", "auto_absent", "absent", "auto_absent"),
    ("regular", "/attendance/mark-absent", None, "absent", "auto_absent"),
    ("regular", "/attendance/mark-absent", "manual", "absent", "auto_absent"),
    ("member_visit", "/attendance/mark", "manual", "visited", "manual"),
    ("member_visit", "/attendance/mark", "face_ai", "visited", "manual"),
    ("member_visit", "/attendance/mark", "auto_absent", "absent", "auto_absent"),
    ("member_visit", "/attendance/mark-absent", None, "absent", "auto_absent"),
    ("member_visit", "/attendance/mark-absent", "manual", "absent", "auto_absent"),
])
def test_a_new_record_marked_by_hand_gets_the_status_its_session_and_method_say(client, visit, session_type, route, method, status, saved_method):
    body = visit(session_type)
    if method:
        body["recognition_method"] = method

    answer = client.post(route, json=body)

    payload = answer.json()
    assert answer.status_code == 200 and (payload["success"], payload["message"]) == (True, "Attendance marked")
    assert set(payload["data"]) == RECORD_FIELDS
    assert (payload["data"]["status"], payload["data"]["recognition_method"]) == (status, saved_method)
    assert stored_records(client) == [(status, saved_method)]


@pytest.mark.parametrize("session_type, first", [("regular", "present"), ("member_visit", "visited")])
def test_marking_absent_after_a_mark_changes_the_one_record_and_says_it_was_already_marked(client, visit, session_type, first):
    body = visit(session_type)
    client.post("/attendance/mark", json={**body, "recognition_method": "manual"})

    answer = client.post("/attendance/mark-absent", json=body)
    again = client.post("/attendance/mark-absent", json=body)

    assert (answer.status_code, answer.json()["success"], answer.json()["message"]) == (200, True, "Already marked")
    assert set(answer.json()["data"]) == RECORD_FIELDS and answer.json()["data"]["status"] == "absent"
    assert again.json()["data"]["status"] == "absent"
    # Still one record; it keeps the method it was first marked with, and it is flagged as marked twice.
    with client.db() as db:
        record = db.query(AttendanceRecord).one()
        assert (record.status, record.recognition_method, record.duplicate_flag) == ("absent", "manual", True)
        from app.models.audit_log import AuditLog
        changes = [row.details for row in db.query(AuditLog).filter_by(action="attendance.marked").order_by(AuditLog.id)]
    assert [(change["status"], change.get("previous_status")) for change in changes] == [(first, None), ("absent", first)]


def test_marking_someone_who_is_not_found_is_404_by_either_route(client, visit):
    # Until October 2026 mark-absent answered 200 with success false; a refusal is now the same for both.
    body = visit("member_visit")

    for route in ("/attendance/mark-absent", "/attendance/mark"):
        answer = client.post(route, json={**body, "person_id": 999})
        assert (answer.status_code, answer.json()) == (404, {"detail": "Person not found"})
