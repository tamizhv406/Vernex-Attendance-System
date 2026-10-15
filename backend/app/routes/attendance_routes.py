from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.timing import Timing
from app.schemas.attendance_schema import AttendanceMark, AttendanceSessionCreate
from app.services.attendance_service import audit_marked, mark_attendance
from app.serializers import attendance_record_data, attendance_session_data
from app.utils.time_utils import now_local, today_local

router = APIRouter(prefix="/attendance", tags=["Attendance"])
# What mark_attendance says when it wrote a new record (otherwise "Already marked" or why not).
MARKED = "Attendance marked"


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
    # The school's clock, not the browser's, unless a start time is given.
    data["start_time"] = data["start_time"] or now_local().time().replace(microsecond=0)
    data["category_program"] = data.get("category_program") or course.course_name
    data["batch_name"] = data.get("batch_name") or batch.batch_name
    # The batch's timetable decides when a student counts as late and when as absent, unless the
    # session names its own times. (Until October 2026 a session never took them over, so nobody
    # was ever late.) Late after: late_after_time, else grace_time; absent after:
    # auto_absent_after_time, else end_time.
    timing_id = data.get("timing_id") or batch.timing_id
    timing = db.get(Timing, timing_id) if timing_id else None
    if timing_id and not timing:
        raise HTTPException(404, "Timing not found")
    if timing:
        data["timing_id"] = timing.id
        data["grace_time"] = data["grace_time"] or timing.late_after_time or timing.grace_time
        data["end_time"] = data["end_time"] or timing.auto_absent_after_time or timing.end_time
    if data["grace_time"] and data["end_time"] and data["grace_time"] >= data["end_time"]:
        raise HTTPException(400, "The late-after time must be before the absent-after (end) time.")
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


# These two routes are attendance marked by hand; the scanner marks through /face/recognize. A new
# record is written to the audit log in the same commit as the record (by_hand), and a record that
# is changed here in the same commit as the change.
#
# Marked by hand means: always in a session (the record belongs to that session and its date), never
# in a session that has not happened yet, stored as "manual" (or "auto_absent" for absent) whatever
# the browser sends, and without a recognition score. The teacher may name the status; for a student
# who is already marked, that corrects the one record (the scanner's or an earlier hand mark).

def by_hand(db, payload: AttendanceMark):
    if not payload.session_id:
        raise HTTPException(400, "Choose the session to mark attendance in.")
    session = db.get(AttendanceSession, payload.session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session.session_date and session.session_date > today_local():
        raise HTTPException(400, f"This session is on {session.session_date.isoformat()}. Attendance can be marked from that day on.")
    payload.recognition_method = "auto_absent" if payload.recognition_method == "auto_absent" else "manual"
    payload.confidence_score = None


def correct(db, record, status, notes=None):
    # A record that says something else until now gets the status asked for, recorded in the same commit.
    before = record.status
    record.status = status
    if notes:
        record.notes = notes
    audit_marked(db, record, before)
    db.commit()
    db.refresh(record)
    forget_scanner_status(record)


def forget_scanner_status(record):
    # The scanner keeps who it has seen marked, and how, so as not to ask the database for every
    # frame. After a change by hand it must ask again, or it goes on showing the old status.
    from app.routes import face_routes

    face_routes.marked_today.pop((record.session_id, record.person_id, record.attendance_date), None)


@router.post("/mark")
def mark(payload: AttendanceMark, db: Session = Depends(get_db)):
    by_hand(db, payload)
    record, message = mark_attendance(db, payload, by_hand=True)
    if not record:
        raise HTTPException(404, message)
    forget_scanner_status(record)
    if message != MARKED and payload.status and record.status != payload.status:
        correct(db, record, payload.status, payload.notes)
        message = "Attendance updated"
    return {"success": True, "message": message, "data": attendance_record_data(record)}


@router.post("/mark-absent")
def mark_absent(payload: AttendanceMark, db: Session = Depends(get_db)):
    by_hand(db, payload)
    payload.recognition_method = "auto_absent"
    payload.status = "absent"
    record, message = mark_attendance(db, payload, by_hand=True)
    if record and message != MARKED and record.status != "absent":
        # One that said something else until now. A new record is absent already (and recorded),
        # and marking absent again changes nothing.
        correct(db, record, "absent", payload.notes)
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
def by_date(attendance_date: date, course_id: int | None = None, batch_id: int | None = None, db: Session = Depends(get_db)):
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
