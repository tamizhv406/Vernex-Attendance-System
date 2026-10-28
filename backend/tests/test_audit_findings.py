"""Reproductions written during the October 2026 audit. Each test states the behaviour that should hold."""
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.routes import face_routes
from app.services import tracking_service
from app.utils.time_utils import today_local


def make_batch(client):
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.commit()
        session = AttendanceSession(session_name="today", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add(session)
        db.commit()
        return course.id, batch.id, session.id


def create_student(client, code, course_id, batch_id):
    answer = client.post("/users/create", json={"person_code": code, "full_name": f"Student {code}", "person_type": "student", "course_id": course_id, "batch_id": batch_id})
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]["id"]


def test_a_new_person_never_inherits_the_attendance_of_a_deleted_one(client):
    course_id, batch_id, session_id = make_batch(client)
    deleted = create_student(client, "OLD-1", course_id, batch_id)
    assert client.post("/attendance/mark", json={"session_id": session_id, "person_id": deleted}).status_code == 200
    # What the scanner remembers about the deleted person (a mark it saw, a challenge it asked).
    face_routes.marked_today[(session_id, deleted, today_local())] = "present"
    tracking_service.challenge_entry(session_id, deleted, 0.0)
    assert client.delete(f"/users/{deleted}").status_code == 200

    newcomer = create_student(client, "NEW-1", course_id, batch_id)

    assert newcomer == deleted  # SQLite gave the deleted person's id to the next one
    history = client.get(f"/attendance/by-person/{newcomer}").json()["data"]
    assert history == [], f"person {newcomer} was just created but has records {[(r['person_code'], r['status']) for r in history]}"
    assert (session_id, newcomer, today_local()) not in face_routes.marked_today
    assert (session_id, newcomer) not in tracking_service.challenges
    marked = client.post("/attendance/mark", json={"session_id": session_id, "person_id": newcomer}).json()
    assert marked["message"] == "Attendance marked", marked["message"]
    # The deleted person's record is still there, under their own code and name.
    with client.db() as db:
        kept = db.query(AttendanceRecord).filter(AttendanceRecord.person_code == "OLD-1").one()
        assert (kept.person_id, kept.person_name, kept.status) == (None, "Student OLD-1", "present")


def test_deleting_a_timing_a_batch_uses_never_blocks_its_classes(client):
    course_id, batch_id, _session_id = make_batch(client)
    timing = client.post("/timings/create", json={"name": "Morning", "timing_type": "batch", "start_time": "09:00:00", "end_time": "11:00:00"}).json()["data"]
    assert client.put(f"/batches/{batch_id}", json={"timing_id": timing["id"]}).status_code == 200

    deleted = client.delete(f"/timings/{timing['id']}")

    assert deleted.status_code == 409, deleted.text
    assert "Batches use this timing" in deleted.json()["detail"]
    started = client.post("/attendance/session/start", json={"session_type": "regular", "session_name": "Maths", "course_id": course_id, "batch_id": batch_id})
    assert started.status_code == 200, started.text
    # Used by a session only (the batch moved on to no timing): still kept, the session refers to it.
    assert client.put(f"/batches/{batch_id}", json={"timing_id": None}).status_code == 200
    assert client.delete(f"/timings/{timing['id']}").status_code == 409


def test_a_timing_nobody_uses_can_be_deleted(client):
    timing = client.post("/timings/create", json={"name": "Spare", "timing_type": "batch"}).json()["data"]

    assert client.delete(f"/timings/{timing['id']}").status_code == 200
    assert client.get(f"/timings/{timing['id']}").status_code == 404


def test_a_refusal_is_answered_the_same_by_hand_and_by_code(client):
    # V-04: someone who exists but may not be marked here is 409 with the reason, whichever way the
    # mark comes in; 404 is only for a person who does not exist. Nothing is written either way.
    course_id, batch_id, session_id = make_batch(client)
    inactive = client.post("/users/create", json={"person_code": "OFF-1", "full_name": "Away", "person_type": "student", "course_id": course_id, "batch_id": batch_id, "status": "inactive"}).json()["data"]
    expected = (409, {"detail": "Away is inactive. Attendance was not marked."})

    by_hand = client.post("/attendance/mark", json={"session_id": session_id, "person_id": inactive["id"]})
    absent = client.post("/attendance/mark-absent", json={"session_id": session_id, "person_id": inactive["id"]})
    by_code = client.post("/attendance/code/mark", json={"session_id": session_id, "code": inactive["attendance_code"], "method": "code_entry"})

    assert [(answer.status_code, answer.json()) for answer in (by_hand, absent, by_code)] == [expected] * 3
    assert client.post("/attendance/mark", json={"session_id": session_id, "person_id": 999}).status_code == 404
    with client.db() as db:
        assert db.query(AttendanceRecord).count() == 0
