"""The rules for creating and changing a person, shared by the JSON API and the spreadsheet import."""
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.utils.validation import FieldError, limited_text, normalize_email, normalize_phone, required_text

DUPLICATE_ID = "ID already exists"
# What each field is called on the screens, for messages a person will read.
LABELS = {
    "person_code": "ID",
    "full_name": "Full name",
    "phone": "Contact number",
    "guardian_phone": "Parent contact",
    "guardian_name": "Parent name",
    "email": "Email",
    "level_class": "Level / class",
}


def label_of(field):
    return LABELS.get(field) or field.replace("_", " ").capitalize()


def ensure_course_batch(db: Session, payload, existing: Person | None = None):
    data = payload.model_dump(exclude_unset=True)
    person_type = data["person_type"] if "person_type" in data else (existing.person_type if existing else None)
    course_id = data["course_id"] if "course_id" in data else (existing.course_id if existing else None)
    batch_id = data["batch_id"] if "batch_id" in data else (existing.batch_id if existing else None)
    if person_type == "student" and (not course_id or not batch_id):
        raise HTTPException(400, "Student must be assigned to a course and batch")
    if batch_id and not course_id:
        raise HTTPException(400, "Select a course before selecting a batch")
    course = db.get(Course, course_id) if course_id else None
    batch = db.get(CourseBatch, batch_id) if batch_id else None
    if course_id and not course:
        raise HTTPException(404, "Course not found")
    if batch_id and not batch:
        raise HTTPException(404, "Batch not found")
    if course and batch and batch.course_id != course.id:
        raise HTTPException(400, "Selected batch does not belong to selected course")
    return course, batch


def clean_person_fields(data: dict):
    """Checks and tidies the fields that are present. A create sends all of them, an update only some.

    Raises FieldError. The contact numbers come back as ten digits, whatever way they were written.
    """
    cleaned = dict(data)
    for field in ("person_code", "full_name"):
        if field in cleaned:
            cleaned[field] = required_text(Person, field, cleaned[field], label_of(field))
    for field, normalize in (("phone", normalize_phone), ("guardian_phone", normalize_phone), ("email", normalize_email)):
        if field not in cleaned:
            continue
        value = cleaned[field]
        if value is None or not str(value).strip():
            # No number is not a wrong number. The forms and the uploads are what require one.
            cleaned[field] = None
            continue
        try:
            cleaned[field] = normalize(value)
        except ValueError as error:
            raise FieldError(field, f"{label_of(field)}: {error}") from None
    for field, value in cleaned.items():
        if isinstance(value, str):
            limited_text(Person, field, value, label_of(field))
    return cleaned


def person_with_code(db: Session, code: str, exclude_id: int | None = None):
    query = db.query(Person).filter(func.lower(Person.person_code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Person.id != exclude_id)
    return query.first()


def build_person(db: Session, payload):
    """Everything POST /users/create checks, without the write: an unsaved Person, its course and batch.

    Raises FieldError for a bad value and HTTPException for a course or batch that does not fit.
    The spreadsheet import builds its rows with this too, so both follow the same rules.
    """
    data = clean_person_fields(payload.model_dump())
    course, batch = ensure_course_batch(db, payload)
    if course:
        data["category_program"] = course.course_name
    if batch:
        data["batch_name"] = batch.batch_name
    return Person(**data), course, batch
