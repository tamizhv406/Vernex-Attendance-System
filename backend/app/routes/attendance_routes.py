from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.schemas.attendance_schema import AttendanceMark, AttendanceSessionCreate
from app.services.attendance_service import mark_attendance
from app.serializers import attendance_record_data, attendance_session_data
from app.utils.time_utils import today_local

router = APIRouter(prefix="/attendance", tags=["Attendance"])


@router.post("/session/start")
def start_session(payload: AttendanceSessionCreate, db: Session = Depends(get_db)):
    course = db.get(Course, payload.course_id)
    batch = db.get(CourseBatch, payload.batch_id)
    if not course:
        raise HTTPException(404, "Course not found")
    if not batch:
        raise HTTPException(404, "Batch not found")
    if batch.course_id != course.id:
        raise HTTPException(400, "Selected batch does not belong to selected course")
    data = payload.model_dump()
    data["session_date"] = data["session_date"] or today_local()
    data["category_program"] = data.get("category_program") or course.course_name
    data["batch_name"] = data.get("batch_name") or batch.batch_name
    session = AttendanceSession(**data, status="active")
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"success": True, "message": "Session started", "data": attendance_session_data(session)}


@router.get("/sessions")
def list_sessions(course_id: int | None = None, batch_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(AttendanceSession)
    if course_id:
        query = query.filter(AttendanceSession.course_id == course_id)
    if batch_id:
        query = query.filter(AttendanceSession.batch_id == batch_id)
    rows = query.order_by(AttendanceSession.created_at.desc()).all()
    return {"success": True, "message": "Sessions fetched", "data": [attendance_session_data(row) for row in rows]}


@router.get("/session/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    item = db.get(AttendanceSession, session_id)
    if not item:
        raise HTTPException(404, "Session not found")
    return {"success": True, "message": "Session fetched", "data": attendance_session_data(item)}


@router.post("/session/{session_id}/complete")
def complete_session(session_id: int, db: Session = Depends(get_db)):
    item = db.get(AttendanceSession, session_id)
    if not item:
        raise HTTPException(404, "Session not found")
    item.status = "completed"
    db.commit()
    db.refresh(item)
    return {"success": True, "message": "Session completed", "data": attendance_session_data(item)}


@router.post("/mark")
def mark(payload: AttendanceMark, db: Session = Depends(get_db)):
    record, message = mark_attendance(db, payload)
    if not record:
        raise HTTPException(404, message)
    return {"success": True, "message": message, "data": attendance_record_data(record)}


@router.post("/mark-absent")
def mark_absent(payload: AttendanceMark, db: Session = Depends(get_db)):
    payload.recognition_method = "auto_absent"
    record, message = mark_attendance(db, payload)
    if record:
        record.status = "absent"
        db.commit()
        db.refresh(record)
    return {"success": bool(record), "message": message, "data": attendance_record_data(record) if record else None}


@router.get("/today")
def today(course_id: int | None = None, batch_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(AttendanceRecord).filter(AttendanceRecord.attendance_date == today_local())
    if course_id:
        query = query.filter(AttendanceRecord.course_id == course_id)
    if batch_id:
        query = query.filter(AttendanceRecord.batch_id == batch_id)
    rows = query.all()
    return {"success": True, "message": "Today attendance fetched", "data": [attendance_record_data(row) for row in rows]}


@router.get("/by-date")
def by_date(attendance_date: str, course_id: int | None = None, batch_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(AttendanceRecord).filter(AttendanceRecord.attendance_date == attendance_date)
    if course_id:
        query = query.filter(AttendanceRecord.course_id == course_id)
    if batch_id:
        query = query.filter(AttendanceRecord.batch_id == batch_id)
    rows = query.all()
    return {"success": True, "message": "Attendance fetched", "data": [attendance_record_data(row) for row in rows]}


@router.get("/by-person/{person_id}")
def by_person(person_id: int, db: Session = Depends(get_db)):
    rows = db.query(AttendanceRecord).filter(AttendanceRecord.person_id == person_id).all()
    return {"success": True, "message": "Attendance fetched", "data": [attendance_record_data(row) for row in rows]}


@router.get("/session/{session_id}/records")
def session_records(session_id: int, db: Session = Depends(get_db)):
    rows = db.query(AttendanceRecord).filter(AttendanceRecord.session_id == session_id).all()
    return {"success": True, "message": "Records fetched", "data": [attendance_record_data(row) for row in rows]}
