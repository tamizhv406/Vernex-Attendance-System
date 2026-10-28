import json
import logging
from datetime import datetime, time, timedelta

import pytest

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.audit_log import AuditLog
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.routes import face_routes
from app.services import attendance_service
from app.utils import rate_limit
from app.utils.time_utils import today_local

CODES = {"student": "K7M29QXD", "other_student": "AB12CD34", "staff": "ST4FF001", "member": "MEMBER01", "inactive": "QQQQ0000", "assigned_staff": "ZZ998877"}


@pytest.fixture()
def school(client):
    face_routes.marked_today.clear()
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.flush()
        batch, other = CourseBatch(course_id=course.id, batch_name="Morning A"), CourseBatch(course_id=course.id, batch_name="Evening B")
        db.add_all([batch, other])
        db.flush()
        people = {
            "student": Person(person_code="STU-1", full_name="Asha Rao", person_type="student", course_id=course.id, batch_id=batch.id, status="active"),
            "other_student": Person(person_code="STU-2", full_name="Bala Iyer", person_type="student", course_id=course.id, batch_id=other.id, status="active"),
            "staff": Person(person_code="STF-1", full_name="Chitra Nair", person_type="admin", status="active"),
            "assigned_staff": Person(person_code="STF-2", full_name="Dev Menon", person_type="admin", course_id=course.id, batch_id=batch.id, status="active"),
            "member": Person(person_code="MEM-1", full_name="Esha Pillai", person_type="member", status="active"),
            "inactive": Person(person_code="STU-3", full_name="Farah Khan", person_type="student", course_id=course.id, batch_id=batch.id, status="inactive"),
        }
        for key, person in people.items():
            person.attendance_code = CODES[key]
        db.add_all(people.values())
        today = today_local()
        sessions = {
            "class": AttendanceSession(session_name="CS - Morning", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today, status="active"),
            "staff": AttendanceSession(session_name="Staff attendance", session_type="staff", session_date=today, status="active"),
            "members": AttendanceSession(session_name="Member visits", session_type="member_visit", session_date=today, status="active"),
            "stopped": AttendanceSession(session_name="Old", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today, status="completed"),
            "yesterday": AttendanceSession(session_name="Yesterday", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today - timedelta(days=1), status="active"),
        }
        db.add_all(sessions.values())
        db.commit()
        ids = {f"session_{key}": row.id for key, row in sessions.items()}
        ids.update({key: row.id for key, row in people.items()})
    yield ids
    face_routes.marked_today.clear()


def mark(client, session_id, code, method="qr_scan", **extra):
    return client.post("/attendance/code/mark", json={"session_id": session_id, "code": code, "method": method, **extra})


def records(client):
    with client.db() as db:
        return [(row.session_id, row.person_id, row.status, row.recognition_method, row.confidence_score, row.device_name) for row in db.query(AttendanceRecord).order_by(AttendanceRecord.id)]


# ---- marked ---------------------------------------------------------------------------------------

def test_a_student_of_the_batch_is_marked_present_by_a_scanned_qr(client, school):
    answer = mark(client, school["session_class"], "VNXATT:K7M29QXD", device_name="Front desk phone")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["success"] is True and body["message"] == "Asha Rao marked present"
    data = body["data"]
    assert (data["result"], data["attendance_status"]) == ("marked", "present")
    assert data["person"] == {"id": school["student"], "full_name": "Asha Rao", "person_code": "STU-1", "person_type": "student",
                              "course_name": "Comp Sci", "batch_name": "Morning A", "face_enrollment_status": "not_started"}
    assert data["record"]["person_id"] == school["student"] and data["record"]["session_id"] == school["session_class"]
    assert records(client) == [(school["session_class"], school["student"], "present", "qr_scan", None, "Front desk phone")]


@pytest.mark.parametrize("typed", ["K7M29QXD", "k7m2-9qxd", " K7M2 9QXD ", "vnxatt:k7m29qxd", "K7M2-9QXD"])
def test_a_typed_code_is_read_however_it_was_typed(client, school, typed):
    answer = mark(client, school["session_class"], typed, method="code_entry")

    assert answer.status_code == 200 and answer.json()["data"]["result"] == "marked"


def test_the_answer_never_contains_the_code(client, school):
    for method in ("qr_scan", "code_entry"):
        text = mark(client, school["session_class"], "K7M29QXD", method=method).text

        assert "K7M29QXD" not in text and "K7M2-9QXD" not in text


def test_marked_after_the_late_after_time_is_late(client, school, monkeypatch):
    with client.db() as db:
        db.get(AttendanceSession, school["session_class"]).grace_time = time(9, 0)
        db.commit()
    monkeypatch.setattr(attendance_service, "now_local", lambda: datetime.combine(today_local(), time(10, 0)))

    answer = mark(client, school["session_class"], "K7M29QXD")

    assert answer.json()["data"]["attendance_status"] == "late" and answer.json()["message"] == "Asha Rao marked late"


def test_marking_twice_is_already_marked_with_one_record(client, school):
    first = mark(client, school["session_class"], "K7M29QXD")
    second = mark(client, school["session_class"], "K7M2-9QXD", method="code_entry")

    assert first.json()["data"]["result"] == "marked"
    assert second.status_code == 200
    assert (second.json()["data"]["result"], second.json()["data"]["attendance_status"]) == ("already_marked", "present")
    assert second.json()["message"] == "Asha Rao: already marked present"
    assert len(records(client)) == 1


def test_a_face_scan_and_a_qr_share_one_record(client, school):
    # The face scanner marked first (its record, its method); the QR finds it and writes nothing.
    from app.schemas.attendance_schema import AttendanceMark

    with client.db() as db:
        attendance_service.mark_attendance(db, AttendanceMark(session_id=school["session_class"], person_id=school["student"], recognition_method="face_ai", confidence_score=0.9))

    answer = mark(client, school["session_class"], "K7M29QXD")

    assert answer.json()["data"]["result"] == "already_marked"
    assert [row[3] for row in records(client)] == ["face_ai"]


def test_staff_are_marked_in_a_staff_session(client, school):
    answer = mark(client, school["session_staff"], "ST4F-F001")

    assert answer.status_code == 200 and answer.json()["data"]["attendance_status"] == "present"
    assert answer.json()["data"]["person"]["person_type"] == "admin"


def test_a_member_is_marked_visited_in_a_member_session(client, school):
    answer = mark(client, school["session_members"], "MEMBER01")

    assert answer.status_code == 200 and answer.json()["data"]["attendance_status"] == "visited"
    assert answer.json()["message"] == "Esha Pillai marked visited"


def test_staff_assigned_to_the_batch_are_marked_in_its_class(client, school):
    assert mark(client, school["session_class"], "ZZ998877").status_code == 200


def test_the_method_is_stored_as_sent(client, school):
    mark(client, school["session_class"], "K7M29QXD", method="code_entry")
    mark(client, school["session_staff"], "ST4FF001", method="qr_scan")

    assert [row[3] for row in records(client)] == ["code_entry", "qr_scan"]


# ---- refused --------------------------------------------------------------------------------------

@pytest.mark.parametrize("session, code, sentence", [
    ("session_class", "AB12CD34", "Bala Iyer is not in this batch."),
    ("session_class", "ST4FF001", "Chitra Nair is not in this batch."),
    ("session_staff", "K7M29QXD", "Only staff can be marked in a staff session."),
    ("session_staff", "MEMBER01", "Only staff can be marked in a staff session."),
    ("session_members", "ST4FF001", "Only members can be marked in a member session."),
    ("session_members", "K7M29QXD", "Only members can be marked in a member session."),
])
def test_someone_outside_the_session_is_refused(client, school, session, code, sentence):
    answer = mark(client, school[session], code)

    assert (answer.status_code, answer.json()["detail"]) == (409, sentence)
    assert records(client) == []


def test_an_inactive_person_is_refused(client, school):
    answer = mark(client, school["session_class"], "QQQQ0000")

    assert (answer.status_code, answer.json()["detail"]) == (409, "Farah Khan is inactive. Attendance was not marked.")
    assert records(client) == []


@pytest.mark.parametrize("code", ["ZZZZZZZZ", "VNXATT:ZZZZ-ZZZZ"])
def test_an_unknown_code_is_refused(client, school, code):
    answer = mark(client, school["session_class"], code)

    assert (answer.status_code, answer.json()["detail"]) == (404, "No one has this code. It may have been replaced by a newer one.")
    assert records(client) == []


@pytest.mark.parametrize("code", ["", "   ", "K7M29QX", "K7MU9QXD", "https://example.com/K7M29QXD", "VNX-S001", "STU-1", "X" * 65, "VNXATT:" + "K7M29QXD" * 10])
def test_something_that_is_not_a_code_is_refused_and_not_repeated(client, school, code):
    answer = mark(client, school["session_class"], code)

    assert (answer.status_code, answer.json()) == (400, {"detail": "This is not a Vernex attendance code."})
    assert records(client) == []


def test_a_persons_id_is_not_their_code(client, school):
    # The sequential person ID was never a code: a QR made from it marks nobody.
    assert mark(client, school["session_class"], "VNXATT:STU-1").status_code == 400


def test_a_stopped_session_is_refused(client, school):
    answer = mark(client, school["session_stopped"], "K7M29QXD")

    assert (answer.status_code, answer.json()["detail"]) == (409, "This session has been stopped. Attendance was not marked.")
    assert records(client) == []


def test_a_session_of_another_day_is_refused(client, school):
    answer = mark(client, school["session_yesterday"], "K7M29QXD")

    assert answer.status_code == 409
    assert answer.json()["detail"] == f"This session is for {(today_local() - timedelta(days=1)).isoformat()}. Stop it and start a new session for today. Attendance was not marked."
    assert records(client) == []


def test_an_unknown_session_is_a_404(client, school):
    assert mark(client, 99999, "K7M29QXD").status_code == 404


@pytest.mark.parametrize("body", [
    {"session_id": 1, "code": "K7M29QXD", "method": "face_ai"},
    {"session_id": 1, "code": "K7M29QXD", "method": "manual"},
    {"session_id": 1, "code": "K7M29QXD"},
    {"code": "K7M29QXD", "method": "qr_scan"},
])
def test_only_a_scan_or_a_typed_code_can_be_sent(client, school, body):
    assert client.post("/attendance/code/mark", json=body).status_code == 422
    assert records(client) == []


# ---- audit, scanner, limits, login ----------------------------------------------------------------

def test_a_typed_code_is_audited_and_a_scanned_qr_is_not(client, school):
    mark(client, school["session_class"], "K7M29QXD", method="qr_scan")
    mark(client, school["session_staff"], "ST4FF001", method="code_entry")

    with client.db() as db:
        entries = db.query(AuditLog).filter(AuditLog.action == "attendance.marked").all()
        assert len(entries) == 1
        assert entries[0].details["method"] == "code_entry" and entries[0].actor_id is not None
        details = json.dumps(entries[0].details)
    assert "ST4FF001" not in details and "ST4F-F001" not in details


def test_a_repeated_typed_code_writes_no_second_audit_entry(client, school):
    mark(client, school["session_class"], "K7M29QXD", method="code_entry")
    mark(client, school["session_class"], "K7M29QXD", method="code_entry")

    with client.db() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "attendance.marked").count() == 1


def test_the_face_scanner_learns_who_was_marked(client, school):
    mark(client, school["session_class"], "K7M29QXD")

    assert face_routes.marked_today[(school["session_class"], school["student"], today_local())] == "present"


def test_too_many_codes_from_one_account_are_told_to_wait(client, school, monkeypatch):
    monkeypatch.setattr(rate_limit.codes, "limit", 3)
    answers = [mark(client, school["session_class"], "ZZZZZZZZ").status_code for _ in range(4)]

    assert answers == [404, 404, 404, 429]


def test_marking_by_code_needs_a_login(anon_client):
    answer = anon_client.post("/attendance/code/mark", json={"session_id": 1, "code": "K7M29QXD", "method": "qr_scan"})

    assert answer.status_code == 401


def test_no_code_is_logged(client, school, caplog):
    with caplog.at_level(logging.DEBUG):
        for code in ("K7M29QXD", "ZZZZZZZZ", "not a code", "AB12CD34"):
            mark(client, school["session_class"], code, method="code_entry")

    assert not any(code in record.getMessage() for record in caplog.records for code in ("K7M29QXD", "ZZZZZZZZ", "AB12CD34"))
