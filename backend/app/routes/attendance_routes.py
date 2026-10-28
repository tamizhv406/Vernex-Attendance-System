from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.models.timing import Timing
from app.schemas.attendance_schema import AttendanceMark, AttendanceSessionCreate, CodeMark
from app.services.attendance_code_service import normalize_code
from app.services.attendance_service import audit_marked, mark_attendance, not_active_refusal, person_in_session
from app.serializers import attendance_record_data, attendance_session_data
from app.utils import rate_limit
from app.utils.time_utils import now_local, today_local

router = APIRouter(prefix="/attendance", tags=["Attendance"])
# What mark_attendance says when it wrote a new record (otherwise "Already marked" or why not).
MARKED = "Attendance marked"
# The kinds of session that can be started, with the name a staff or member session gets when none is sent.
SESSION_NAMES = {"regular": None, "staff": "Staff attendance", "member_visit": "Member visits"}


@router.post("/session/start")
def start_session(payload: AttendanceSessionCreate, db: Session = Depends(get_db)):
    # Three kinds of session can be started: a batch class, a staff session and a member session.
    # Older rows may carry other types; they are still read, but no new one is started.
    if payload.session_type not in SESSION_NAMES:
        raise HTTPException(400, "A session is a batch class, a staff session or a member session.")
    data = payload.model_dump()
    if payload.session_type == "regular":
        if payload.course_id is None or payload.batch_id is None:
            raise HTTPException(400, "Select a course and a batch to start a batch class.")
        if not (payload.session_name or "").strip():
            raise HTTPException(400, "Give the session a name.")
        course = db.get(Course, payload.course_id)
        batch = db.get(CourseBatch, payload.batch_id)
        if not course:
            raise HTTPException(404, "Course not found")
        if not batch:
            raise HTTPException(404, "Batch not found")
        if batch.course_id != course.id:
            raise HTTPException(400, "Selected batch does not belong to selected course")
        data["category_program"] = data.get("category_program") or course.course_name
        data["batch_name"] = data.get("batch_name") or batch.batch_name
    else:
        # Staff and members are not taught in batches: their sessions take everyone of their kind.
        if payload.course_id is not None or payload.batch_id is not None:
            raise HTTPException(400, "A staff or member session has no course or batch. Leave them empty.")
        batch = None
        data["category_program"] = None
        data["batch_name"] = None
        data["session_name"] = (data.get("session_name") or "").strip() or SESSION_NAMES[payload.session_type]
    data["session_date"] = data["session_date"] or today_local()
    # The school's clock, not the browser's, unless a start time is given.
    data["start_time"] = data["start_time"] or now_local().time().replace(microsecond=0)
    # The batch's timetable decides when a student counts as late and when as absent, unless the
    # session names its own times. (Until October 2026 a session never took them over, so nobody
    # was ever late.) Late after: late_after_time, else grace_time; absent after:
    # auto_absent_after_time, else end_time. A staff or member session uses a timing only when one is sent.
    timing_id = data.get("timing_id") or (batch.timing_id if batch else None)
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


def refused(message):
    # Why a hand mark wrote nothing. A person who does not exist is 404; one who exists but may not be
    # marked here (pending, inactive, another batch or kind of session) is 409, as for a QR code
    # (mark_by_code). Until October 2026 those were 404 here, and 200 with success false for absent.
    return HTTPException(404 if message == "Person not found" else 409, message)


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


NOT_A_CODE = "This is not a Vernex attendance code."
UNKNOWN_CODE = "No one has this code. It may have been replaced by a newer one."
# Longer than any code with its prefix and separators; anything longer is not looked at.
MAX_CODE_TEXT = 64


@router.post("/code/mark", dependencies=[Depends(rate_limit.codes)])
def mark_by_code(payload: CodeMark, db: Session = Depends(get_db)):
    # A person's QR card scanned on the QR Attendance page, or their code typed at the desk. The same
    # rules as a face scan: the session must be running today, the person active and in its scope,
    # and one record per person and session. A typed code is audited like a hand mark; a scanned QR,
    # like a face scan, is not. The code itself is never repeated in an answer, a log or the audit log.
    from app.routes import face_routes

    code = normalize_code(payload.code) if len(payload.code) <= MAX_CODE_TEXT else None
    if not code:
        raise HTTPException(400, NOT_A_CODE)
    session = db.get(AttendanceSession, payload.session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    refusal = face_routes.session_refusal(session)
    if refusal:
        raise HTTPException(409, refusal)
    person = db.query(Person).filter(Person.attendance_code == code).first()
    if not person:
        raise HTTPException(404, UNKNOWN_CODE)
    not_active = not_active_refusal(person)
    if not_active:
        raise HTTPException(409, not_active)
    outside = person_in_session(person, session)
    if outside:
        raise HTTPException(409, outside)
    record, message = mark_attendance(db, AttendanceMark(
        session_id=session.id,
        person_id=person.id,
        recognition_method=payload.method,
        confidence_score=None,
        device_name=payload.device_name,
    ), by_hand=payload.method == "code_entry")
    if not record:
        raise HTTPException(409, message)
    # A face scanner on the same session now knows this person is marked, and does not try again.
    face_routes.marked_today[(session.id, person.id, record.attendance_date)] = record.status
    already = message != MARKED
    course = db.get(Course, person.course_id) if person.course_id else None
    batch = db.get(CourseBatch, person.batch_id) if person.batch_id else None
    return {
        "success": True,
        "message": f"{person.full_name}: already marked {record.status}" if already else f"{person.full_name} marked {record.status}",
        "data": {
            "result": "already_marked" if already else "marked",
            "attendance_status": record.status,
            "person": {
                "id": person.id,
                "full_name": person.full_name,
                "person_code": person.person_code,
                "person_type": person.person_type,
                "course_name": course.course_name if course else person.category_program,
                "batch_name": batch.batch_name if batch else person.batch_name,
                "face_enrollment_status": person.face_enrollment_status,
            },
            "record": attendance_record_data(record),
        },
    }


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
        raise refused(message)
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
    if not record:
        raise refused(message)
    if message != MARKED and record.status != "absent":
        # One that said something else until now. A new record is absent already (and recorded),
        # and marking absent again changes nothing.
        correct(db, record, "absent", payload.notes)
    return {"success": True, "message": message, "data": attendance_record_data(record)}


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
