"""The rules for courses and batches, shared by the JSON API and the spreadsheet import."""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.utils.validation import limited_text, required_text


def clean_course_code(value):
    return required_text(Course, "course_code", value, "Course code").upper()


def clean_course_name(value):
    return required_text(Course, "course_name", value, "Course name")


def clean_batch_name(value):
    return required_text(CourseBatch, "batch_name", value, "Batch name")


def clean_batch_level(value):
    return limited_text(CourseBatch, "batch_level", value, "Batch level") if value else value


def course_with_code(db: Session, code: str, exclude_id: int | None = None):
    query = db.query(Course).filter(func.lower(Course.course_code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Course.id != exclude_id)
    return query.first()


def batch_named(db: Session, course_id: int, name: str, exclude_id: int | None = None):
    query = db.query(CourseBatch).filter(CourseBatch.course_id == course_id, func.lower(CourseBatch.batch_name) == name.lower())
    if exclude_id is not None:
        query = query.filter(CourseBatch.id != exclude_id)
    return query.first()


# A person row carries a copy of its course name and batch name (category_program, batch_name).
# Attendance records and the enrollment list read those copies, so they follow a rename. Attendance
# already recorded keeps the names it was taken under.

def relabel_course_people(db: Session, course: Course):
    db.query(Person).filter(Person.course_id == course.id).update({Person.category_program: course.course_name}, synchronize_session=False)


def relabel_batch_people(db: Session, batch: CourseBatch):
    db.query(Person).filter(Person.batch_id == batch.id).update({Person.batch_name: batch.batch_name}, synchronize_session=False)


def move_batch_people(db: Session, batch: CourseBatch, course: Course):
    """The people of a batch go with it to its new course. Returns how many were moved.

    A person's batch must belong to the person's course: the scanner looks students up by course
    and batch together, and attendance is refused for a student whose course is not the session's.
    Leaving them behind would make every one of them unknown to the scanner.
    """
    return db.query(Person).filter(Person.batch_id == batch.id).update(
        {Person.course_id: course.id, Person.category_program: course.course_name}, synchronize_session=False
    )
