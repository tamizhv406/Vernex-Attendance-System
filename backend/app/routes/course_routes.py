from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.schemas.course_schema import BatchCreate, BatchUpdate, CourseCreate, CourseUpdate
from app.serializers import batch_data, course_data

router = APIRouter(tags=["Courses and Batches"])


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


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
    query = db.query(CourseBatch).filter(
        CourseBatch.course_id == course_id,
        func.lower(CourseBatch.batch_name) == batch_name.lower(),
    )
    if exclude_id:
        query = query.filter(CourseBatch.id != exclude_id)
    if query.first():
        raise HTTPException(409, "Batch already exists under this course")


@router.get("/courses")
def list_courses(db: Session = Depends(get_db)):
    rows = db.query(Course).order_by(Course.course_name.asc()).all()
    return ok("Courses fetched", [course_data(row) for row in rows])


@router.post("/courses/create")
def create_course(payload: CourseCreate, db: Session = Depends(get_db)):
    code = payload.course_code.strip().upper()
    name = payload.course_name.strip()
    if not code or not name:
        raise HTTPException(400, "Course code and course name are required")
    exists = db.query(Course).filter(func.lower(Course.course_code) == code.lower()).first()
    if exists:
        raise HTTPException(409, "Course code already exists")
    course = Course(course_code=code, course_name=name, description=payload.description, status=payload.status)
    db.add(course)
    db.commit()
    db.refresh(course)
    return ok("Course created", course_data(course))


@router.get("/courses/{course_id}")
def get_course(course_id: int, db: Session = Depends(get_db)):
    return ok("Course fetched", course_data(ensure_course(db, course_id)))


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseUpdate, db: Session = Depends(get_db)):
    course = ensure_course(db, course_id)
    data = payload.model_dump(exclude_unset=True)
    if "course_code" in data and data["course_code"]:
        code = data["course_code"].strip().upper()
        exists = db.query(Course).filter(func.lower(Course.course_code) == code.lower(), Course.id != course_id).first()
        if exists:
            raise HTTPException(409, "Course code already exists")
        course.course_code = code
    if "course_name" in data and data["course_name"]:
        course.course_name = data["course_name"].strip()
    if "description" in data:
        course.description = data["description"]
    if "status" in data and data["status"]:
        course.status = data["status"]
    db.commit()
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
    name = payload.batch_name.strip()
    if not name:
        raise HTTPException(400, "Batch name is required")
    validate_batch_course(db, payload.course_id, name)
    batch = CourseBatch(
        course_id=payload.course_id,
        batch_name=name,
        batch_level=payload.batch_level,
        timing_id=payload.timing_id,
        status=payload.status,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return ok("Batch created", batch_data(batch))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    return ok("Batch fetched", batch_data(ensure_batch(db, batch_id)))


@router.put("/batches/{batch_id}")
def update_batch(batch_id: int, payload: BatchUpdate, db: Session = Depends(get_db)):
    batch = ensure_batch(db, batch_id)
    data = payload.model_dump(exclude_unset=True)
    next_course_id = data.get("course_id", batch.course_id)
    if "course_id" in data and data["course_id"] is not None:
        ensure_course(db, data["course_id"])
        batch.course_id = data["course_id"]
    if "batch_name" in data and data["batch_name"]:
        name = data["batch_name"].strip()
        validate_batch_course(db, next_course_id, name, exclude_id=batch.id)
        batch.batch_name = name
    if "batch_level" in data:
        batch.batch_level = data["batch_level"]
    if "timing_id" in data:
        batch.timing_id = data["timing_id"]
    if "status" in data and data["status"]:
        batch.status = data["status"]
    db.commit()
    db.refresh(batch)
    return ok("Batch updated", batch_data(batch))


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
    db.commit()
    return ok("Batch deleted")
