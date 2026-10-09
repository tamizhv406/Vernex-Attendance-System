import pytest
from fastapi import HTTPException

from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding, FaceEnrollment
from app.models.person import Person
from app.routes.person_routes import delete_person, ensure_course_batch
from app.schemas.person_schema import PersonUpdate


def _seed_student(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    batch = CourseBatch(course_id=course.id, batch_name="Morning A")
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    student = Person(
        person_code="S1",
        full_name="Alice",
        person_type="student",
        course_id=course.id,
        batch_id=batch.id,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    return student, course, batch


def test_clearing_course_id_alone_is_rejected_for_existing_student(db_session):
    student, _course, _batch = _seed_student(db_session)

    payload = PersonUpdate(course_id=None)
    with pytest.raises(HTTPException) as exc_info:
        ensure_course_batch(db_session, payload, existing=student)

    assert exc_info.value.status_code == 400
    assert "course and batch" in exc_info.value.detail


def test_deleting_an_enrolled_student_removes_their_face_data(db_session):
    student, _course, _batch = _seed_student(db_session)
    db_session.add(FaceEnrollment(person_id=student.id, enrollment_status="completed"))
    db_session.add(FaceEmbedding(person_id=student.id, embedding_vector="[1.0, 0.0]", pose_type="front"))
    db_session.commit()

    result = delete_person(student.id, db_session)

    assert result["success"] is True
    assert db_session.query(Person).count() == 0
    assert db_session.query(FaceEmbedding).count() == 0
    assert db_session.query(FaceEnrollment).count() == 0


def test_batch_id_alone_succeeds_when_student_already_has_a_course(db_session):
    student, course, _batch = _seed_student(db_session)
    other_batch = CourseBatch(course_id=course.id, batch_name="Evening B")
    db_session.add(other_batch)
    db_session.commit()
    db_session.refresh(other_batch)

    payload = PersonUpdate(batch_id=other_batch.id)
    resolved_course, resolved_batch = ensure_course_batch(db_session, payload, existing=student)

    assert resolved_course.id == course.id
    assert resolved_batch.id == other_batch.id
