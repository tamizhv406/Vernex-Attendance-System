import threading

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.person import Person
from app.services import audit_service
from app.services.sheet_service import queue_attendance_record
from app.utils.time_utils import now_local, today_local

mark_lock = threading.Lock()


def find_today_record(db: Session, person_id, session_id):
    return find_record(db, person_id, session_id, today_local())


def find_record(db: Session, person_id, session_id, day):
    return db.query(AttendanceRecord).filter(
        AttendanceRecord.person_id == person_id,
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.attendance_date == day,
    ).first()


def session_day(session):
    # The day a record in this session belongs to: the session's own date. A record written into
    # yesterday's session (a correction by hand) is yesterday's attendance, not today's.
    return session.session_date if session is not None and session.session_date else today_local()


def mark_attendance(db: Session, payload, by_hand: bool = False):
    # One mark at a time: "is there a record already?" and "write one" must not interleave between
    # two scanners that confirm the same student in the same moment.
    # by_hand: marked through the attendance routes rather than by the scanner. A new record is then
    # written to the audit log in the same commit as the record itself.
    with mark_lock:
        record, message = write_attendance(db, payload, by_hand)
    if record and message == "Attendance marked":
        # Outside the lock, and in the background: the sheet is a slow network call and must not hold
        # up this answer or other students.
        queue_attendance_record(db, record)
        db.refresh(record)
    return record, message


def audit_marked(db: Session, record: AttendanceRecord, previous_status: str | None = None):
    """Adds the audit row for attendance marked by hand. The caller commits, with the change it records."""
    details = {"person_id": record.person_id, "person_code": record.person_code, "session_id": record.session_id,
               "status": record.status, "method": record.recognition_method}
    if previous_status:
        details["previous_status"] = previous_status
    audit_service.record(db, "attendance.marked", target_type="attendance_record", target_id=record.id, details=details)


def person_in_session(person, session):
    # The one rule for who may be marked in a session, whether by face, by hand or by code. None
    # when the person belongs, otherwise the sentence the screen shows. A staff session is for staff
    # (person_type "admin"), a member session for members. Any other session is a batch class, older
    # rows included: it is for whoever is assigned to that course and batch, staff and members too.
    if session.session_type == "staff":
        return None if person.person_type == "admin" else "Only staff can be marked in a staff session."
    if session.session_type == "member_visit":
        return None if person.person_type == "member" else "Only members can be marked in a member session."
    if person.course_id != session.course_id or person.batch_id != session.batch_id:
        return f"{person.full_name} is not in this batch."
    return None


def not_active_refusal(person):
    # Only active people get new attendance records, whatever marks them: a face, a hand or a code.
    # Pending and inactive people are refused with this sentence. A record they already have stays,
    # and can still be corrected by hand.
    if person.status == "active":
        return None
    state = "pending" if person.status == "pending" else "inactive"
    return f"{person.full_name} is {state}. Attendance was not marked."


def write_attendance(db: Session, payload, by_hand: bool = False):
    person = None
    if payload.person_id:
        person = db.get(Person, payload.person_id)
    elif payload.person_code:
        person = db.query(Person).filter(Person.person_code == payload.person_code).first()
    if not person:
        return None, "Person not found"

    session = db.get(AttendanceSession, payload.session_id) if payload.session_id else None
    expected_course_id = session.course_id if session else payload.course_id
    expected_batch_id = session.batch_id if session else payload.batch_id
    if session:
        refused = person_in_session(person, session)
        if refused:
            return None, refused
    elif person.person_type == "student":
        # A record written without a session (scripts, older callers): only a student's course and
        # batch are checked, as they always were.
        if expected_course_id and person.course_id != expected_course_id:
            return None, "Person does not belong to this course"
        if expected_batch_id and person.batch_id != expected_batch_id:
            return None, "Person does not belong to this batch"
    day = session_day(session)
    existing = find_record(db, person.id, payload.session_id, day)
    if existing:
        existing.duplicate_flag = True
        db.commit()
        return existing, "Already marked"
    refused = not_active_refusal(person)
    if refused:
        return None, refused

    # Who is logged in, which app/security.py puts on the database session of every request. A
    # record written through the API is signed with that account whatever the client sent; only
    # code that calls this service directly (a script, a test) supplies the name itself.
    actor = db.info.get("actor")
    now = now_local()
    # Marked absent by hand is absent whatever the session (the route insists on it), and is saved
    # that way at once, so the record and its audit row say the same thing. A status chosen by the
    # teacher is taken as it is. Otherwise the clock decides late or absent, but only on the
    # session's own day: marked by hand afterwards, the time it is marked says nothing.
    if getattr(payload, "status", None):
        status = payload.status
    elif payload.recognition_method == "auto_absent":
        status = "absent"
    elif session and session.session_type == "member_visit":
        status = "visited"
    else:
        status = "present"
        if day == now.date() and session and session.grace_time and now.time() > session.grace_time:
            status = "late"
        if day == now.date() and session and session.end_time and now.time() > session.end_time:
            status = "absent"

    record = AttendanceRecord(
        session_id=payload.session_id,
        person_id=person.id,
        person_code=person.person_code,
        person_name=person.full_name,
        person_type=person.person_type,
        course_id=person.course_id or expected_course_id,
        batch_id=person.batch_id or expected_batch_id,
        category_program=person.category_program,
        batch_name=person.batch_name,
        level_class=person.level_class,
        attendance_date=day,
        # The school's clock, without a time zone, which is what the column holds. Handed a time WITH
        # a zone, PostgreSQL converts it to its own zone first (UTC on Supabase: 5.5 hours off for
        # Asia/Kolkata) while SQLite keeps the clock time, so the same mark read differently.
        marked_time=now.replace(tzinfo=None),
        status=status,
        confidence_score=payload.confidence_score,
        recognition_method=payload.recognition_method,
        device_name=payload.device_name,
        marked_by=actor.email if actor else payload.marked_by,
        notes=payload.notes,
    )
    db.add(record)
    try:
        if by_hand:
            db.flush()  # the record's id, for the audit row
            audit_marked(db, record)
        db.commit()
    except IntegrityError:
        # Another process wrote this person's record first; the database's unique index refused ours.
        db.rollback()
        existing = find_record(db, person.id, payload.session_id, day)
        if not existing:
            raise
        return existing, "Already marked"
    db.refresh(record)
    return record, "Attendance marked"
