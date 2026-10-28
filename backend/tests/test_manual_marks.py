"""Attendance marked or corrected by hand, and the scanner's refusal of a session from another day.

Until October 2026 a hand mark could be stored as a face scan with a score the browser made up
(B1), went into whatever session was named, with today's date, even a finished session of an
earlier day (B2), or into no session at all (B3); and a scanner left running overnight wrote
today's records into yesterday's session (B6). These are the rules that replaced that.
"""
from datetime import timedelta

import pytest

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.audit_log import AuditLog
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.routes import face_routes
from app.utils.time_utils import today_local
from test_recognition_flow import VECTORS, batch_of, face, records, results, scan  # noqa: F401
from test_recognition_flow import camera  # noqa: F401  (fixture)


@pytest.fixture()
def school(client):
    # A course with one batch, two students, and three sessions of it: today's (running), yesterday's
    # (finished) and tomorrow's (not yet).
    today = today_local()
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.commit()
        students = [Person(person_code=f"STU-{n}", full_name=f"Student {n}", person_type="student", course_id=course.id, batch_id=batch.id) for n in (1, 2)]
        outsider = Person(person_code="STU-9", full_name="Other Batch", person_type="student")
        db.add_all(students + [outsider])
        sessions = {
            name: AttendanceSession(session_name=name, session_type="regular", course_id=course.id, batch_id=batch.id, session_date=day, status=status)
            for name, day, status in (("today", today, "active"), ("yesterday", today - timedelta(days=1), "completed"), ("tomorrow", today + timedelta(days=1), "scheduled"))
        }
        db.add_all(sessions.values())
        db.commit()
        return {"student": students[0].id, "second": students[1].id, "outsider": outsider.id, **{name: session.id for name, session in sessions.items()}}


def stored(client):
    with client.db() as db:
        return [(r.session_id, r.person_id, r.attendance_date, r.status, r.recognition_method, r.confidence_score) for r in db.query(AttendanceRecord).order_by(AttendanceRecord.id)]


def audit(client):
    # (status, previous status, email of the account that did it) per audit entry, oldest first.
    from app.models.admin_account import AdminAccount

    with client.db() as db:
        rows = db.query(AuditLog, AdminAccount.email).outerjoin(AdminAccount, AuditLog.actor_id == AdminAccount.id).filter(AuditLog.action == "attendance.marked").order_by(AuditLog.id)
        return [(row.details["status"], row.details.get("previous_status"), email) for row, email in rows]


@pytest.mark.parametrize("route", ["/attendance/mark", "/attendance/mark-absent"])
def test_a_hand_mark_needs_a_session(client, school, route):
    answer = client.post(route, json={"person_id": school["student"]})

    assert (answer.status_code, answer.json()) == (400, {"detail": "Choose the session to mark attendance in."})
    assert stored(client) == []


@pytest.mark.parametrize("route", ["/attendance/mark", "/attendance/mark-absent"])
def test_a_session_that_does_not_exist_is_not_found(client, school, route):
    answer = client.post(route, json={"session_id": 9999, "person_id": school["student"]})

    assert (answer.status_code, answer.json()) == (404, {"detail": "Session not found"}) and stored(client) == []


@pytest.mark.parametrize("route", ["/attendance/mark", "/attendance/mark-absent"])
def test_a_session_on_a_later_day_cannot_be_marked_yet(client, school, route):
    answer = client.post(route, json={"session_id": school["tomorrow"], "person_id": school["student"]})

    assert answer.status_code == 400 and "Attendance can be marked from that day on." in answer.json()["detail"]
    assert stored(client) == []


@pytest.mark.parametrize("method", [None, "face_ai", "manual", "something_else"])
def test_a_hand_mark_is_stored_as_manual_without_the_score_the_browser_sent(client, school, method):
    body = {"session_id": school["today"], "person_id": school["student"], "confidence_score": 0.99}
    if method:
        body["recognition_method"] = method

    answer = client.post("/attendance/mark", json=body)

    assert answer.status_code == 200 and answer.json()["message"] == "Attendance marked"
    assert stored(client) == [(school["today"], school["student"], today_local(), "present", "manual", None)]


def test_a_correction_in_an_earlier_session_is_dated_with_that_session(client, school):
    yesterday = today_local() - timedelta(days=1)

    answer = client.post("/attendance/mark", json={"session_id": school["yesterday"], "person_id": school["student"]})

    assert answer.status_code == 200 and answer.json()["data"]["attendance_date"] == yesterday.isoformat()
    # Marked afterwards, the time of day says nothing: present, not late or absent by the clock.
    assert stored(client) == [(school["yesterday"], school["student"], yesterday, "present", "manual", None)]
    assert audit(client) == [("present", None, client.account_email)]


def test_the_teacher_can_name_the_status(client, school):
    answer = client.post("/attendance/mark", json={"session_id": school["today"], "person_id": school["student"], "status": "late"})

    assert answer.json()["data"]["status"] == "late" and [row[3] for row in stored(client)] == ["late"]


def test_a_status_that_does_not_exist_is_refused(client, school):
    answer = client.post("/attendance/mark", json={"session_id": school["today"], "person_id": school["student"], "status": "excellent"})

    assert answer.status_code == 422 and stored(client) == []


def test_naming_another_status_corrects_the_one_record_and_records_who_did_it(client, school):
    body = {"session_id": school["today"], "person_id": school["student"]}
    client.post("/attendance/mark", json=body)

    late = client.post("/attendance/mark", json={**body, "status": "late", "notes": "Came in at 9:20"})
    same = client.post("/attendance/mark", json={**body, "status": "late"})
    absent = client.post("/attendance/mark-absent", json=body)
    back = client.post("/attendance/mark", json={**body, "status": "present"})

    assert [late.json()["message"], same.json()["message"], absent.json()["message"], back.json()["message"]] == ["Attendance updated", "Already marked", "Already marked", "Attendance updated"]
    assert [row[3] for row in stored(client)] == ["present"]
    assert audit(client) == [("present", None, client.account_email), ("late", "present", client.account_email),
                             ("absent", "late", client.account_email), ("present", "absent", client.account_email)]
    with client.db() as db:
        assert db.query(AttendanceRecord).one().notes == "Came in at 9:20"


def test_a_mark_without_a_status_never_changes_a_record(client, school):
    body = {"session_id": school["today"], "person_id": school["student"]}
    client.post("/attendance/mark-absent", json=body)

    answer = client.post("/attendance/mark", json=body)

    assert answer.json()["message"] == "Already marked" and [row[3] for row in stored(client)] == ["absent"]


def test_a_student_of_another_batch_is_refused(client, school):
    answer = client.post("/attendance/mark", json={"session_id": school["today"], "person_id": school["outsider"]})

    # 409: the student exists and may not be marked here, as for a QR code (404 until October 2026).
    assert answer.status_code == 409 and answer.json() == {"detail": "Other Batch is not in this batch."} and stored(client) == []


def test_a_scanner_record_can_be_corrected_by_hand(client, school):
    from app.schemas.attendance_schema import AttendanceMark
    from app.services.attendance_service import mark_attendance

    with client.db() as db:
        mark_attendance(db, AttendanceMark(session_id=school["today"], person_id=school["student"], recognition_method="face_ai", confidence_score=0.91))

    answer = client.post("/attendance/mark", json={"session_id": school["today"], "person_id": school["student"], "status": "absent", "notes": "Was not in class"})

    assert answer.json()["message"] == "Attendance updated"
    # One record. It keeps the method it was made with; the audit log says who changed it and from what.
    assert stored(client) == [(school["today"], school["student"], today_local(), "absent", "face_ai", 0.91)]
    assert audit(client) == [("absent", "present", client.account_email)]


def test_every_student_of_a_session_can_be_marked_once(client, school):
    for person in (school["student"], school["second"]):
        for _ in range(3):
            client.post("/attendance/mark", json={"session_id": school["today"], "person_id": person})

    assert sorted(row[1] for row in stored(client)) == sorted([school["student"], school["second"]])


# ---- the scanner and a session from another day ---------------------------------------------------

def test_the_scanner_writes_nothing_into_a_session_from_an_earlier_day(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])
    session.session_date = today_local() - timedelta(days=1)
    db_session.commit()
    face_routes.session_cache.clear()

    answers = [scan(db_session, camera, session, [face(0, "Arun")]) for _ in range(4)]

    assert results(answers[-1]) == ["not_marked"] and "start a new session for today" in answers[-1]["faces"][0]["message"]
    assert records(db_session) == []


def test_the_scanner_marks_into_todays_session(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [face(0, "Arun")]) for _ in range(4)]

    assert "verified" in [results(answer)[0] for answer in answers]
    assert [(r.person_id, r.attendance_date, r.recognition_method) for r in records(db_session)] == [(people["Arun"].id, today_local(), "face_ai")]
