from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.schemas.course_schema import BatchCreate, BatchUpdate, CourseCreate, CourseUpdate
from app.serializers import batch_data, course_data
from app.services import audit_service, course_service
from app.utils.validation import FieldError

router = APIRouter(tags=["Courses and Batches"])

COURSE_EXISTS = "Course code already exists"
BATCH_EXISTS = "Batch already exists under this course"


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def refuse(error: FieldError):
    return HTTPException(error.status, error.message)


def commit_or_conflict(db: Session, taken, message: str):
    # Another request can save the same code or name between the check and this commit. The
    # database's unique index then refuses this one; that is a conflict to report, not a crash.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if taken():
            raise HTTPException(409, message)
        raise


def ensure_course(db: Session, course_id: int):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "Course not found")
    return course


def ensure_batch(db: Session, batch_id: int):
    batch = db.get(CourseBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    return batch


def validate_batch_course(db: Session, course_id: int, batch_name: str, exclude_id: int | None = None):
    if course_service.batch_named(db, course_id, batch_name, exclude_id):
        raise HTTPException(409, BATCH_EXISTS)


@router.get("/courses")
def list_courses(db: Session = Depends(get_db)):
    rows = db.query(Course).order_by(Course.course_name.asc()).all()
    return ok("Courses fetched", [course_data(row) for row in rows])


@router.post("/courses/create")
def create_course(payload: CourseCreate, db: Session = Depends(get_db)):
    try:
        code = course_service.clean_course_code(payload.course_code)
        name = course_service.clean_course_name(payload.course_name)
    except FieldError as error:
        raise refuse(error)
    if course_service.course_with_code(db, code):
        raise HTTPException(409, COURSE_EXISTS)
    course = Course(course_code=code, course_name=name, description=payload.description, status=payload.status)
    db.add(course)
    commit_or_conflict(db, lambda: course_service.course_with_code(db, code), COURSE_EXISTS)
    db.refresh(course)
    return ok("Course created", course_data(course))


@router.get("/courses/{course_id}")
def get_course(course_id: int, db: Session = Depends(get_db)):
    return ok("Course fetched", course_data(ensure_course(db, course_id)))


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    data = payload.model_dump(exclude_unset=True)
    code, name = course.course_code, course.course_name
    try:
        # A code or name that is sent must hold something. A name of spaces used to be saved as an
        # empty name, with "Course updated" as the answer.
        if data.get("course_code") is not None:
            code = course_service.clean_course_code(data["course_code"])
        if data.get("course_name") is not None:
            name = course_service.clean_course_name(data["course_name"])
    except FieldError as error:
        raise refuse(error)
    # Only a code that really changes is checked, so saving a course with its own code never conflicts.
    if code != course.course_code and course_service.course_with_code(db, code, exclude_id=course_id):
        raise HTTPException(409, COURSE_EXISTS)
    renamed = name != course.course_name
    course.course_code = code
    course.course_name = name
    if "description" in data:
        course.description = data["description"]
    if "status" in data and data["status"]:
        course.status = data["status"]
    if renamed:
        course_service.relabel_course_people(db, course)
    commit_or_conflict(db, lambda: course_service.course_with_code(db, code, exclude_id=course_id), COURSE_EXISTS)
    db.refresh(course)
    return ok("Course updated", course_data(course))


@router.delete("/courses/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db)):
    ensure_course(db, course_id)
    if db.query(Person).filter(Person.course_id == course_id).first():
        raise HTTPException(409, "Unassign users before deleting this course")
    if db.query(AttendanceSession).filter(AttendanceSession.course_id == course_id).first():
        raise HTTPException(409, "Course has attendance sessions and cannot be deleted")
    if db.query(AttendanceRecord).filter(AttendanceRecord.course_id == course_id).first():
        raise HTTPException(409, "Course has attendance records and cannot be deleted")
    if db.query(CourseBatch).filter(CourseBatch.course_id == course_id).first():
        raise HTTPException(409, "Delete batches under this course first")
    course = db.get(Course, course_id)
    db.delete(course)
    audit_service.record(db, "course.deleted", target_type="course", target_id=course.id,
                         details={"course_code": course.course_code, "course_name": course.course_name})
    db.commit()
    return ok("Course deleted")


@router.get("/batches")
def list_batches(course_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(CourseBatch).options(joinedload(CourseBatch.course))
    if course_id:
        query = query.filter(CourseBatch.course_id == course_id)
    rows = query.order_by(CourseBatch.batch_name.asc()).all()
    return ok("Batches fetched", [batch_data(row) for row in rows])


@router.post("/batches/create")
def create_batch(payload: BatchCreate, db: Session = Depends(get_db)):
    ensure_course(db, payload.course_id)
    try:
        name = course_service.clean_batch_name(payload.batch_name)
        level = course_service.clean_batch_level(payload.batch_level)
    except FieldError as error:
        raise refuse(error)
    validate_batch_course(db, payload.course_id, name)
    batch = CourseBatch(
        course_id=payload.course_id,
        batch_name=name,
        batch_level=level,
        timing_id=payload.timing_id,
        status=payload.status,
    )
    db.add(batch)
    commit_or_conflict(db, lambda: course_service.batch_named(db, payload.course_id, name), BATCH_EXISTS)
    db.refresh(batch)
    return ok("Batch created", batch_data(batch))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    return ok("Batch fetched", batch_data(ensure_batch(db, batch_id)))


@router.put("/batches/{batch_id}")
def update_batch(batch_id: int, payload: BatchUpdate, db: Session = Depends(get_db)):
    batch = ensure_batch(db, batch_id)
    data = payload.model_dump(exclude_unset=True)
    if "course_id" in data and data["course_id"] is None:
        raise HTTPException(400, "Select a course for this batch")
    course_id = data.get("course_id", batch.course_id)
    name = batch.batch_name
    try:
        if data.get("batch_name") is not None:
            name = course_service.clean_batch_name(data["batch_name"])
        course_service.clean_batch_level(data.get("batch_level"))
    except FieldError as error:
        raise refuse(error)
    moving = course_id != batch.course_id
    course = ensure_course(db, course_id) if moving else None
    # The name must be free in the course the batch will be in, whichever of the two is changing.
    # A batch saved with its own name in its own course is not compared with itself.
    if moving or name.lower() != batch.batch_name.lower():
        validate_batch_course(db, course_id, name, exclude_id=batch.id)

    # Everything is checked by now; nothing above has changed the batch.
    people_moved = 0
    if moving:
        batch.course_id = course_id
        people_moved = course_service.move_batch_people(db, batch, course)
    if name != batch.batch_name:
        batch.batch_name = name
        course_service.relabel_batch_people(db, batch)
    if "batch_level" in data:
        batch.batch_level = data["batch_level"]
    if "timing_id" in data:
        batch.timing_id = data["timing_id"]
    if "status" in data and data["status"]:
        batch.status = data["status"]
    commit_or_conflict(db, lambda: course_service.batch_named(db, course_id, name, exclude_id=batch_id), BATCH_EXISTS)
    db.refresh(batch)
    return ok("Batch updated", dict(batch_data(batch), people_moved=people_moved))


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int, db: Session = Depends(get_db)):
    ensure_batch(db, batch_id)
    if db.query(Person).filter(Person.batch_id == batch_id).first():
        raise HTTPException(409, "Unassign users before deleting this batch")
    if db.query(AttendanceSession).filter(AttendanceSession.batch_id == batch_id).first():
        raise HTTPException(409, "Batch has attendance sessions and cannot be deleted")
    if db.query(AttendanceRecord).filter(AttendanceRecord.batch_id == batch_id).first():
        raise HTTPException(409, "Batch has attendance records and cannot be deleted")
    batch = db.get(CourseBatch, batch_id)
    db.delete(batch)
    audit_service.record(db, "batch.deleted", target_type="batch", target_id=batch.id,
                         details={"batch_name": batch.batch_name, "course_id": batch.course_id})
    db.commit()
    return ok("Batch deleted")
