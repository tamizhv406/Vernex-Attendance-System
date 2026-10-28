import json

import pytest

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.person import Person
from app.routes import face_routes
from app.schemas.attendance_schema import AttendanceMark
from app.services.attendance_service import mark_attendance
from app.utils.time_utils import today_local

STATUSES = ["active", "pending", "inactive"]
REFUSED = {"pending": "{name} is pending. Attendance was not marked.", "inactive": "{name} is inactive. Attendance was not marked."}


@pytest.fixture()
def school(client):
    # One batch class running today, and a student of that batch in each status.
    face_routes.gallery_cache.clear()
    face_routes.marked_today.clear()
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.flush()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.flush()
        people = {status: Person(person_code=f"STU-{status}", full_name=f"Student {status.title()}", person_type="student",
                                 course_id=course.id, batch_id=batch.id, status=status, attendance_code=code)
                  for status, code in zip(STATUSES, ("AAAAAAAA", "BBBBBBBB", "CCCCCCCC"))}
        db.add_all(people.values())
        session = AttendanceSession(session_name="Class", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add(session)
        db.commit()
        yield {"session": session.id, "course": course.id, "batch": batch.id, **{status: person.id for status, person in people.items()}}
    face_routes.gallery_cache.clear()
    face_routes.marked_today.clear()


def records(client, person_id=None):
    with client.db() as db:
        query = db.query(AttendanceRecord)
        if person_id is not None:
            query = query.filter(AttendanceRecord.person_id == person_id)
        return [(row.person_id, row.status, row.recognition_method) for row in query]


def set_status(client, person_id, status):
    with client.db() as db:
        db.get(Person, person_id).status = status
        db.commit()


# ---- every way of marking refuses a person who is not active -------------------------------------

@pytest.mark.parametrize("status", STATUSES)
def test_a_face_scan_marks_only_active_people(client, school, status):
    with client.db() as db:
        session = db.get(AttendanceSession, school["session"])
        answer = face_routes.mark_for_session(db, session, school[status], 0.91, "test-camera")

    if status == "active":
        assert answer["result"] == "verified" and records(client) == [(school["active"], "present", "face_ai")]
    else:
        assert answer["result"] == "not_marked" and answer["message"] == REFUSED[status].format(name=f"Student {status.title()}")
        assert records(client) == []


@pytest.mark.parametrize("status", STATUSES)
def test_a_hand_mark_marks_only_active_people(client, school, status):
    answer = client.post("/attendance/mark", json={"session_id": school["session"], "person_id": school[status], "status": "present"})

    if status == "active":
        assert answer.status_code == 200 and records(client) == [(school["active"], "present", "manual")]
    else:
        assert answer.status_code == 409 and answer.json()["detail"] == REFUSED[status].format(name=f"Student {status.title()}")
        assert records(client) == []


@pytest.mark.parametrize("status", ["pending", "inactive"])
def test_marking_absent_by_hand_is_refused_too(client, school, status):
    answer = client.post("/attendance/mark-absent", json={"session_id": school["session"], "person_id": school[status]})

    assert (answer.status_code, answer.json()) == (409, {"detail": REFUSED[status].format(name=f"Student {status.title()}")})
    assert records(client) == []


@pytest.mark.parametrize("status, code", [("active", "AAAAAAAA"), ("pending", "BBBBBBBB"), ("inactive", "CCCCCCCC")])
@pytest.mark.parametrize("method", ["qr_scan", "code_entry"])
def test_a_qr_or_typed_code_marks_only_active_people(client, school, status, code, method):
    answer = client.post("/attendance/code/mark", json={"session_id": school["session"], "code": code, "method": method})

    if status == "active":
        assert answer.status_code == 200 and answer.json()["data"]["result"] == "marked"
    else:
        assert answer.status_code == 409 and answer.json()["detail"] == REFUSED[status].format(name=f"Student {status.title()}")
        assert records(client) == []


@pytest.mark.parametrize("status", ["pending", "inactive"])
def test_a_record_written_without_a_session_is_refused_too(client, school, status):
    with client.db() as db:
        record, message = mark_attendance(db, AttendanceMark(person_id=school[status], course_id=school["course"], batch_id=school["batch"]))

    assert record is None and message == REFUSED[status].format(name=f"Student {status.title()}")


# ---- what a person already has stays, and can be corrected -------------------------------------

def test_a_record_kept_after_the_person_becomes_inactive_can_still_be_corrected_by_hand(client, school):
    assert client.post("/attendance/mark", json={"session_id": school["session"], "person_id": school["active"], "status": "present"}).status_code == 200
    set_status(client, school["active"], "inactive")

    corrected = client.post("/attendance/mark", json={"session_id": school["session"], "person_id": school["active"], "status": "late", "notes": "Arrived late"})
    absent = client.post("/attendance/mark-absent", json={"session_id": school["session"], "person_id": school["active"]})

    assert corrected.status_code == 200 and corrected.json()["message"] == "Attendance updated"
    assert absent.json()["success"] is True
    assert records(client) == [(school["active"], "absent", "manual")]


def test_a_scan_of_someone_already_marked_and_now_inactive_changes_nothing(client, school):
    client.post("/attendance/code/mark", json={"session_id": school["session"], "code": "AAAAAAAA", "method": "qr_scan"})
    set_status(client, school["active"], "inactive")

    with client.db() as db:
        session = db.get(AttendanceSession, school["session"])
        face = face_routes.mark_for_session(db, session, school["active"], 0.91, "test-camera")
    code = client.post("/attendance/code/mark", json={"session_id": school["session"], "code": "AAAAAAAA", "method": "qr_scan"})

    # The record stays as it was: the face scanner sees it is there, the code route refuses an inactive person.
    assert face["result"] == "already_marked" and code.status_code == 409
    assert records(client) == [(school["active"], "present", "qr_scan")]


# ---- the face gallery compares active people only ----------------------------------------------

def test_the_face_gallery_holds_only_active_people(client, school):
    with client.db() as db:
        for status in STATUSES:
            db.add(FaceEmbedding(person_id=school[status], embedding_vector=json.dumps([1.0] + [0.0] * 7), pose_type="front", model_name=face_routes.model_label(), is_active=True))
        db.commit()
        gallery = face_routes.load_gallery(db, school["course"], school["batch"], "regular")

    assert {item.person_id for item in gallery[0]} == {school["active"]}


@pytest.mark.parametrize("session_type, person_type", [("staff", "admin"), ("member_visit", "member")])
def test_staff_and_member_galleries_hold_only_active_people_too(client, session_type, person_type):
    face_routes.gallery_cache.clear()
    with client.db() as db:
        people = [Person(person_code=f"P-{status}", full_name=status, person_type=person_type, status=status) for status in STATUSES]
        db.add_all(people)
        db.flush()
        for person in people:
            db.add(FaceEmbedding(person_id=person.id, embedding_vector=json.dumps([1.0] + [0.0] * 7), pose_type="front", model_name=face_routes.model_label(), is_active=True))
        db.commit()
        active_id = people[0].id
        gallery = face_routes.load_gallery(db, None, None, session_type)
    face_routes.gallery_cache.clear()

    assert {item.person_id for item in gallery[0]} == {active_id}
