from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEnrollment
from app.models.person import Person
from app.schemas.person_schema import PersonCreate, PersonUpdate
from app.serializers import person_data

router = APIRouter(prefix="/users", tags=["User Management"])
legacy_router = APIRouter(prefix="/people", tags=["Legacy People"])


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def serialize_people(rows):
    return [person_data(person, course, batch) for person, course, batch in rows]


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


@router.post("/create")
@legacy_router.post("/create")
def create_person(payload: PersonCreate, db: Session = Depends(get_db)):
    course, batch = ensure_course_batch(db, payload)
    data = payload.model_dump()
    if course:
        data["category_program"] = course.course_name
    if batch:
        data["batch_name"] = batch.batch_name
    person = Person(**data)
    db.add(person)
    db.commit()
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
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(person, key, value)
    if course:
        person.category_program = course.course_name
    if batch:
        person.batch_name = batch.batch_name
    db.commit()
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
    db.commit()
    return ok("Deleted successfully")
