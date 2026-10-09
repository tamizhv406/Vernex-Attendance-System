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


def test_non_student_can_be_marked_present_despite_no_course_or_batch(db_session):
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

    payload = AttendanceMark(session_id=session.id, person_id=staff.id)
    record, message = mark_attendance(db_session, payload)

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
    assert message == "Person does not belong to this course"


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
