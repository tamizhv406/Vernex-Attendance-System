import threading

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.person import Person
from app.services.sheet_service import sync_attendance_record
from app.utils.time_utils import now_local, today_local

mark_lock = threading.Lock()


def find_today_record(db: Session, person_id, session_id):
    return db.query(AttendanceRecord).filter(
        AttendanceRecord.person_id == person_id,
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.attendance_date == today_local(),
    ).first()


def mark_attendance(db: Session, payload):
    # One mark at a time: "is there a record already?" and "write one" must not interleave between
    # two scanners that confirm the same student in the same moment.
    with mark_lock:
        record, message = write_attendance(db, payload)
    if record and message == "Attendance marked":
        # Outside the lock: the sheet is a slow network call and must not hold up other students.
        sync_attendance_record(db, record)
        db.refresh(record)
    return record, message


def write_attendance(db: Session, payload):
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
    if person.person_type == "student":
        if expected_course_id and person.course_id != expected_course_id:
            return None, "Person does not belong to this course"
        if expected_batch_id and person.batch_id != expected_batch_id:
            return None, "Person does not belong to this batch"
    existing = find_today_record(db, person.id, payload.session_id)
    if existing:
        existing.duplicate_flag = True
        db.commit()
        return existing, "Already marked"

    now = now_local()
    if session and session.session_type == "member_visit":
        status = "visited"
    elif payload.recognition_method == "auto_absent":
        status = "absent"
    else:
        status = "present"
        if session and session.grace_time and now.time() > session.grace_time:
            status = "late"
        if session and session.end_time and now.time() > session.end_time:
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
        attendance_date=today_local(),
        marked_time=now,
        status=status,
        confidence_score=payload.confidence_score,
        recognition_method=payload.recognition_method,
        device_name=payload.device_name,
        marked_by=payload.marked_by,
        notes=payload.notes,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Another process wrote this person's record first; the database's unique index refused ours.
        db.rollback()
        existing = find_today_record(db, person.id, payload.session_id)
        if not existing:
            raise
        return existing, "Already marked"
    db.refresh(record)
    return record, "Attendance marked"
