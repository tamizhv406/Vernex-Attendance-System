import json
from datetime import datetime, time
from types import SimpleNamespace

import pytest

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.person import Person
from app.routes import face_routes
from app.schemas.attendance_schema import AttendanceMark
from app.services import attendance_service
from app.services.attendance_service import mark_attendance, person_in_session
from app.utils.time_utils import today_local


# ---- who belongs to a session: one rule for face, hand and code marks ---------------------------

def person(person_type, course_id=None, batch_id=None, name="Asha Rao"):
    return SimpleNamespace(full_name=name, person_type=person_type, course_id=course_id, batch_id=batch_id)


def session(session_type, course_id=None, batch_id=None):
    return SimpleNamespace(session_type=session_type, course_id=course_id, batch_id=batch_id)


@pytest.mark.parametrize("who, where, answer", [
    (person("student", 1, 2), session("regular", 1, 2), None),
    (person("student", 1, 3), session("regular", 1, 2), "Asha Rao is not in this batch."),
    (person("student", 9, 2), session("regular", 1, 2), "Asha Rao is not in this batch."),
    (person("student"), session("regular", 1, 2), "Asha Rao is not in this batch."),
    # Decision 5: staff and members count in a batch class only when assigned to that batch.
    (person("admin", 1, 2), session("regular", 1, 2), None),
    (person("admin"), session("regular", 1, 2), "Asha Rao is not in this batch."),
    (person("member", 1, 2), session("regular", 1, 2), None),
    (person("member"), session("regular", 1, 2), "Asha Rao is not in this batch."),
    # An older session type is read as a batch class.
    (person("student", 1, 2), session("class", 1, 2), None),
    (person("admin"), session("staff"), None),
    (person("admin", 1, 2), session("staff"), None),
    (person("student", 1, 2), session("staff"), "Only staff can be marked in a staff session."),
    (person("member"), session("staff"), "Only staff can be marked in a staff session."),
    (person("member"), session("member_visit"), None),
    (person("admin"), session("member_visit"), "Only members can be marked in a member session."),
    (person("student", 1, 2), session("member_visit"), "Only members can be marked in a member session."),
])
def test_who_belongs_to_a_session(who, where, answer):
    assert person_in_session(who, where) == answer


# ---- starting a session --------------------------------------------------------------------------

@pytest.fixture()
def school(client):
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.flush()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        other = CourseBatch(course_id=course.id, batch_name="Evening B")
        db.add_all([batch, other])
        db.flush()
        people = {
            "student": Person(person_code="STU-1", full_name="Asha Rao", person_type="student", course_id=course.id, batch_id=batch.id),
            "other_student": Person(person_code="STU-2", full_name="Bala Iyer", person_type="student", course_id=course.id, batch_id=other.id),
            "staff": Person(person_code="STF-1", full_name="Chitra Nair", person_type="admin"),
            "assigned_staff": Person(person_code="STF-2", full_name="Dev Menon", person_type="admin", course_id=course.id, batch_id=batch.id),
            "member": Person(person_code="MEM-1", full_name="Esha Pillai", person_type="member"),
        }
        db.add_all(people.values())
        db.commit()
        return {"course": course.id, "batch": batch.id, "other_batch": other.id, **{key: row.id for key, row in people.items()}}


def start(client, **body):
    return client.post("/attendance/session/start", json=body)


@pytest.mark.parametrize("session_type, name", [("staff", "Staff attendance"), ("member_visit", "Member visits")])
def test_a_staff_or_member_session_starts_without_a_course_or_batch_and_is_named_for_its_kind(client, session_type, name):
    answer = start(client, session_type=session_type)

    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert (data["session_type"], data["session_name"], data["course_id"], data["batch_id"], data["status"]) == (session_type, name, None, None, "active")
    assert data["session_date"] == today_local().isoformat()


def test_a_staff_session_keeps_a_name_and_a_late_after_time_it_is_given(client):
    data = start(client, session_type="staff", session_name="Monday staff", grace_time="09:15:00").json()["data"]

    assert (data["session_name"], data["grace_time"]) == ("Monday staff", "09:15:00")


@pytest.mark.parametrize("session_type", ["staff", "member_visit"])
@pytest.mark.parametrize("where", [{"course_id": 1}, {"batch_id": 1}, {"course_id": 1, "batch_id": 1}])
def test_a_staff_or_member_session_refuses_a_course_or_batch(client, school, session_type, where):
    answer = start(client, session_type=session_type, **where)

    assert answer.status_code == 400
    assert answer.json()["detail"] == "A staff or member session has no course or batch. Leave them empty."


@pytest.mark.parametrize("where", [{}, {"course_id": 1}, {"batch_id": 1}])
def test_a_batch_class_still_needs_its_course_and_batch(client, school, where):
    answer = start(client, session_name="Class", session_type="regular", **where)

    assert answer.status_code == 400
    assert answer.json()["detail"] == "Select a course and a batch to start a batch class."


def test_a_batch_class_starts_as_before(client, school):
    answer = start(client, session_name="CS - Morning", session_type="regular", course_id=school["course"], batch_id=school["batch"])

    assert answer.status_code == 200
    data = answer.json()["data"]
    assert (data["course_id"], data["batch_id"], data["batch_name"], data["category_program"]) == (school["course"], school["batch"], "Morning A", "Comp Sci")


def test_a_batch_class_with_a_batch_of_another_course_is_still_refused(client, school):
    with client.db() as db:
        other_course = Course(course_code="MA101", course_name="Maths")
        db.add(other_course)
        db.commit()
        other_course_id = other_course.id

    answer = start(client, session_name="Class", session_type="regular", course_id=other_course_id, batch_id=school["batch"])

    assert answer.status_code == 400


@pytest.mark.parametrize("session_type", ["class", "exam", "STAFF", ""])
def test_an_unknown_session_type_cannot_be_started(client, school, session_type):
    answer = start(client, session_name="Class", session_type=session_type, course_id=school["course"], batch_id=school["batch"])

    assert answer.status_code == 400
    assert answer.json()["detail"] == "A session is a batch class, a staff session or a member session."


# ---- marking by hand follows the same rule --------------------------------------------------------

def running(client, session_type, **where):
    return start(client, session_name="Session", session_type=session_type, **where).json()["data"]["id"]


def hand_mark(client, session_id, person_id):
    return client.post("/attendance/mark", json={"session_id": session_id, "person_id": person_id})


def records(client):
    with client.db() as db:
        return [(row.session_id, row.person_id, row.status, row.person_type) for row in db.query(AttendanceRecord).order_by(AttendanceRecord.id)]


def test_staff_are_marked_present_in_a_staff_session_and_a_student_is_refused(client, school):
    session_id = running(client, "staff")

    assert hand_mark(client, session_id, school["staff"]).json()["message"] == "Attendance marked"
    refused = hand_mark(client, session_id, school["student"])

    assert refused.status_code == 409 and refused.json()["detail"] == "Only staff can be marked in a staff session."
    assert records(client) == [(session_id, school["staff"], "present", "admin")]


def test_staff_marked_after_the_late_after_time_are_late(client, school, monkeypatch):
    session_id = start(client, session_type="staff", grace_time="09:00:00").json()["data"]["id"]
    # The school's clock at 10:00 on the session's day, an hour past the late-after time.
    monkeypatch.setattr(attendance_service, "now_local", lambda: datetime.combine(today_local(), time(10, 0)))

    assert hand_mark(client, session_id, school["staff"]).status_code == 200
    assert records(client) == [(session_id, school["staff"], "late", "admin")]


def test_a_member_is_marked_visited_in_a_member_session_and_staff_are_refused(client, school):
    session_id = running(client, "member_visit")

    assert hand_mark(client, session_id, school["member"]).status_code == 200
    refused = hand_mark(client, session_id, school["staff"])

    assert refused.status_code == 409 and refused.json()["detail"] == "Only members can be marked in a member session."
    assert records(client) == [(session_id, school["member"], "visited", "member")]


def test_a_batch_class_marks_its_students_and_the_staff_assigned_to_it_only(client, school):
    session_id = running(client, "regular", course_id=school["course"], batch_id=school["batch"])

    assert hand_mark(client, session_id, school["student"]).status_code == 200
    assert hand_mark(client, session_id, school["assigned_staff"]).status_code == 200
    other = hand_mark(client, session_id, school["other_student"])
    unassigned = hand_mark(client, session_id, school["staff"])

    assert other.json()["detail"] == "Bala Iyer is not in this batch."
    assert unassigned.json()["detail"] == "Chitra Nair is not in this batch."
    assert [row[1] for row in records(client)] == [school["student"], school["assigned_staff"]]


def test_a_record_written_without_a_session_keeps_the_old_student_only_check(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    staff = Person(person_code="STF-1", full_name="Chitra Nair", person_type="admin")
    student = Person(person_code="STU-1", full_name="Asha Rao", person_type="student")
    db_session.add_all([staff, student])
    db_session.commit()

    assert mark_attendance(db_session, AttendanceMark(person_id=staff.id, course_id=course.id))[0] is not None
    assert mark_attendance(db_session, AttendanceMark(person_id=student.id, course_id=course.id)) == (None, "Person does not belong to this course")


# ---- the face gallery of each scope ---------------------------------------------------------------

@pytest.fixture()
def enrolled(db_session):
    face_routes.gallery_cache.clear()
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    batch = CourseBatch(course_id=course.id, batch_name="Morning A")
    db_session.add(batch)
    db_session.commit()
    rows = {
        "student": Person(person_code="STU-1", full_name="Asha", person_type="student", course_id=course.id, batch_id=batch.id),
        "assigned_staff": Person(person_code="STF-2", full_name="Dev", person_type="admin", course_id=course.id, batch_id=batch.id),
        "staff": Person(person_code="STF-1", full_name="Chitra", person_type="admin"),
        "member": Person(person_code="MEM-1", full_name="Esha", person_type="member"),
    }
    db_session.add_all(rows.values())
    db_session.commit()
    for index, row in enumerate(rows.values()):
        vector = [0.0] * 8
        vector[index] = 1.0
        db_session.add(FaceEmbedding(person_id=row.id, embedding_vector=json.dumps(vector), pose_type="front", model_name=face_routes.model_label(), is_active=True))
    db_session.commit()
    yield {"course": course.id, "batch": batch.id, **{key: row.id for key, row in rows.items()}}
    face_routes.gallery_cache.clear()


def gallery_people(gallery):
    return {item.person_id for item in gallery[0]}


def test_a_staff_session_compares_faces_of_staff_only(db_session, enrolled):
    assert gallery_people(face_routes.load_gallery(db_session, None, None, "staff")) == {enrolled["staff"], enrolled["assigned_staff"]}


def test_a_member_session_compares_faces_of_members_only(db_session, enrolled):
    assert gallery_people(face_routes.load_gallery(db_session, None, None, "member_visit")) == {enrolled["member"]}


def test_a_batch_class_compares_the_faces_assigned_to_its_batch(db_session, enrolled):
    assert gallery_people(face_routes.load_gallery(db_session, enrolled["course"], enrolled["batch"], "regular")) == {enrolled["student"], enrolled["assigned_staff"]}
    # Without a session the course and batch the scanner sends still decide, as before.
    assert gallery_people(face_routes.load_gallery(db_session, enrolled["course"], enrolled["batch"])) == {enrolled["student"], enrolled["assigned_staff"]}


@pytest.mark.parametrize("session_type", [None, "regular", "class"])
def test_without_any_scope_no_face_is_compared_rather_than_everyone(db_session, enrolled, session_type):
    gallery = face_routes.load_gallery(db_session, None, None, session_type)

    assert gallery_people(gallery) == set()
    assert gallery[1] is None


def test_each_scope_is_cached_apart(db_session, enrolled):
    staff = face_routes.load_gallery(db_session, None, None, "staff")
    members = face_routes.load_gallery(db_session, None, None, "member_visit")

    assert gallery_people(staff) != gallery_people(members)
    assert face_routes.load_gallery(db_session, None, None, "staff") is staff


def test_the_scanner_session_keeps_its_type(db_session):
    face_routes.session_cache.clear()
    row = AttendanceSession(session_name="Staff attendance", session_type="staff", session_date=today_local(), status="active")
    db_session.add(row)
    db_session.commit()

    assert face_routes.load_session(db_session, row.id).session_type == "staff"
    face_routes.session_cache.clear()
