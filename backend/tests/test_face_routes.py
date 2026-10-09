from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.routes.face_routes import enrollment_users


def test_enrollment_users_includes_non_student_person_types(db_session):
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
    staff = Person(
        person_code="T1",
        full_name="Bob",
        person_type="staff",
        course_id=course.id,
        batch_id=batch.id,
    )
    db_session.add_all([student, staff])
    db_session.commit()

    result = enrollment_users(course.id, batch.id, db_session)
    names = {row["full_name"] for row in result["data"]}

    assert names == {"Alice", "Bob"}
