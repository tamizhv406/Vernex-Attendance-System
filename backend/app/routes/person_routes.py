from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEnrollment
from app.models.person import Person
from app.schemas.person_schema import PersonCreate, PersonUpdate
from app.serializers import person_data
from app.services import audit_service
from app.services.person_service import DUPLICATE_ID, build_person, clean_person_fields, ensure_course_batch, person_with_code
from app.utils.validation import FieldError

router = APIRouter(prefix="/users", tags=["User Management"])
legacy_router = APIRouter(prefix="/people", tags=["Legacy People"])


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def serialize_people(rows):
    return [person_data(person, course, batch) for person, course, batch in rows]


def commit_or_duplicate(db: Session, code: str, exclude_id: int | None = None):
    # Two requests with the same new ID can both pass the check before them. The database's unique
    # index refuses the second one here, and that is answered as the conflict it is.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if person_with_code(db, code, exclude_id):
            raise HTTPException(409, DUPLICATE_ID)
        raise


@router.post("/create")
@legacy_router.post("/create")
def create_person(payload: PersonCreate, db: Session = Depends(get_db)):
    try:
        person, course, batch = build_person(db, payload)
    except FieldError as error:
        raise HTTPException(error.status, error.message)
    if person_with_code(db, person.person_code):
        raise HTTPException(409, DUPLICATE_ID)
    db.add(person)
    commit_or_duplicate(db, person.person_code)
    db.refresh(person)
    return ok("Created successfully", person_data(person, course, batch))


@router.get("")
@legacy_router.get("")
def list_people(
    person_type: str | None = None,
    course_id: int | None = None,
    batch_id: int | None = None,
    category_program: str | None = None,
    batch_name: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Person, Course, CourseBatch).outerjoin(Course, Person.course_id == Course.id).outerjoin(CourseBatch, Person.batch_id == CourseBatch.id)
    if person_type:
        query = query.filter(Person.person_type == person_type)
    if course_id:
        query = query.filter(Person.course_id == course_id)
    if batch_id:
        query = query.filter(Person.batch_id == batch_id)
    if category_program:
        query = query.filter(Person.category_program == category_program)
    if batch_name:
        query = query.filter(Person.batch_name == batch_name)
    return ok("Users fetched", serialize_people(query.order_by(Person.created_at.desc()).all()))


@router.get("/{person_id}")
@legacy_router.get("/{person_id}")
def get_person(person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "User not found")
    course = db.get(Course, person.course_id) if person.course_id else None
    batch = db.get(CourseBatch, person.batch_id) if person.batch_id else None
    return ok("User fetched", person_data(person, course, batch))


@router.put("/{person_id}")
@legacy_router.put("/{person_id}")
def update_person(person_id: int, payload: PersonUpdate, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "User not found")
    course, batch = ensure_course_batch(db, payload, existing=person)
    try:
        changes = clean_person_fields(payload.model_dump(exclude_unset=True))
    except FieldError as error:
        raise HTTPException(error.status, error.message)
    code = changes.get("person_code", person.person_code)
    # The person's own row is left out, so saving someone with the ID they already have never conflicts.
    if "person_code" in changes and person_with_code(db, code, exclude_id=person_id):
        raise HTTPException(409, DUPLICATE_ID)
    for key, value in changes.items():
        setattr(person, key, value)
    if course:
        person.category_program = course.course_name
    if batch:
        person.batch_name = batch.batch_name
    commit_or_duplicate(db, code, exclude_id=person_id)
    db.refresh(person)
    return ok("Updated successfully", person_data(person, course, batch))


@router.delete("/{person_id}")
@legacy_router.delete("/{person_id}")
def delete_person(person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if not person:
        raise HTTPException(404, "User not found")
    db.query(FaceEnrollment).filter(FaceEnrollment.person_id == person_id).delete()
    db.delete(person)
    # The row is gone after this, so the log keeps what is needed to tell who it was.
    audit_service.record(db, "person.deleted", target_type="person", target_id=person.id,
                         details={"person_code": person.person_code, "full_name": person.full_name, "person_type": person.person_type})
    db.commit()
    return ok("Deleted successfully")
