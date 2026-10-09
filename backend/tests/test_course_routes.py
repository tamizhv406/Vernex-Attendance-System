from datetime import date

import pytest
from fastapi import HTTPException

from app.models.attendance import AttendanceRecord
from app.models.course import Course, CourseBatch
from app.routes.course_routes import delete_batch, delete_course


def test_delete_course_is_blocked_by_historical_attendance_records(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    record = AttendanceRecord(
        course_id=course.id,
        attendance_date=date(2026, 1, 1),
        status="present",
    )
    db_session.add(record)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        delete_course(course.id, db_session)

    assert exc_info.value.status_code == 409
    assert db_session.get(Course, course.id) is not None


def test_delete_batch_is_blocked_by_historical_attendance_records(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    batch = CourseBatch(course_id=course.id, batch_name="Morning A")
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    record = AttendanceRecord(
        course_id=course.id,
        batch_id=batch.id,
        attendance_date=date(2026, 1, 1),
        status="present",
    )
    db_session.add(record)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        delete_batch(batch.id, db_session)

    assert exc_info.value.status_code == 409
    assert db_session.get(CourseBatch, batch.id) is not None
