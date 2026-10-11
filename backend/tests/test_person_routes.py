import pytest
from fastapi import HTTPException

from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding, FaceEnrollment
from app.models.person import Person
from app.routes.person_routes import delete_person, ensure_course_batch
from app.schemas.person_schema import PersonUpdate


def _seed_student(db_session):
    course = Course(course_code="CS101", course_name="Comp Sci")
    db_session.add(course)
    db_session.commit()
    db_session.refresh(course)

    batch = CourseBatch(course_id=course.id, batch_name="Morning A")
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    student = Person(
        person_code="S1",
        full_name="Alice",
        person_type="student",
        course_id=course.id,
        batch_id=batch.id,
    )
    db_session.add(student)
    db_session.commit()
    db_session.refresh(student)

    return student, course, batch


def test_clearing_course_id_alone_is_rejected_for_existing_student(db_session):
    student, _course, _batch = _seed_student(db_session)

    payload = PersonUpdate(course_id=None)
    with pytest.raises(HTTPException) as exc_info:
        ensure_course_batch(db_session, payload, existing=student)

    assert exc_info.value.status_code == 400
    assert "course and batch" in exc_info.value.detail


def test_deleting_an_enrolled_student_removes_their_face_data(db_session):
    student, _course, _batch = _seed_student(db_session)
    db_session.add(FaceEnrollment(person_id=student.id, enrollment_status="completed"))
    db_session.add(FaceEmbedding(person_id=student.id, embedding_vector="[1.0, 0.0]", pose_type="front"))
    db_session.commit()

    result = delete_person(student.id, db_session)

    assert result["success"] is True
    assert db_session.query(Person).count() == 0
    assert db_session.query(FaceEmbedding).count() == 0
    assert db_session.query(FaceEnrollment).count() == 0


def test_batch_id_alone_succeeds_when_student_already_has_a_course(db_session):
    student, course, _batch = _seed_student(db_session)
    other_batch = CourseBatch(course_id=course.id, batch_name="Evening B")
    db_session.add(other_batch)
    db_session.commit()
    db_session.refresh(other_batch)

    payload = PersonUpdate(batch_id=other_batch.id)
    resolved_course, resolved_batch = ensure_course_batch(db_session, payload, existing=student)

    assert resolved_course.id == course.id
    assert resolved_batch.id == other_batch.id


# ---- an ID that is already in use ---------------------------------------------------------------

def member(code="MEM-1", **fields):
    return {"person_code": code, "full_name": "Sample Member", "person_type": "member", "phone": "9876543210", **fields}


def saved_people(client):
    with client.db() as db:
        return [(person.person_code, person.full_name, person.person_type) for person in db.query(Person).order_by(Person.id)]


@pytest.mark.parametrize("path", ["/users/create", "/people/create"])
def test_creating_a_person_with_an_id_that_is_taken_is_a_conflict_not_a_server_error(client, path):
    client.post("/users/create", json=member())

    response = client.post(path, json=member(full_name="Somebody Else"))

    # This used to be a 500 whose message was the database's own INSERT statement.
    assert response.status_code == 409
    assert response.json() == {"detail": "ID already exists"}
    assert saved_people(client) == [("MEM-1", "Sample Member", "member")]


@pytest.mark.parametrize("written", ["mem-1", "  MEM-1  ", "Mem-1"])
def test_an_id_that_differs_only_in_case_or_spaces_is_the_same_id(client, written):
    client.post("/users/create", json=member())

    response = client.post("/users/create", json=member(written))

    assert response.status_code == 409
    assert response.json() == {"detail": "ID already exists"}


def test_an_id_is_unique_across_students_staff_and_members(client):
    client.post("/users/create", json=member("SHARED-1"))

    response = client.post("/users/create", json={"person_code": "SHARED-1", "full_name": "Sample Staff", "person_type": "admin", "phone": "9876543210"})

    assert response.status_code == 409
    assert saved_people(client) == [("SHARED-1", "Sample Member", "member")]


def test_the_application_goes_on_working_after_a_conflict(client):
    client.post("/users/create", json=member())
    client.post("/users/create", json=member())

    response = client.post("/users/create", json=member("MEM-2"))

    assert response.status_code == 200
    assert [code for code, _name, _type in saved_people(client)] == ["MEM-1", "MEM-2"]


def test_two_requests_creating_the_same_id_at_once_end_as_one_person_and_one_conflict(client, monkeypatch):
    # Both requests ask "is this ID free?" before either has saved. The database's unique index
    # refuses the second one; the answer is still 409, and the session is left clean.
    from app.routes import person_routes

    find = person_routes.person_with_code
    asked = []

    def blind_the_first_time(db, code, exclude_id=None):
        asked.append(code)
        return None if len(asked) == 1 else find(db, code, exclude_id)

    client.post("/users/create", json=member())
    monkeypatch.setattr(person_routes, "person_with_code", blind_the_first_time)

    response = client.post("/users/create", json=member(full_name="Saved Second"))

    assert response.status_code == 409
    assert response.json() == {"detail": "ID already exists"}
    assert saved_people(client) == [("MEM-1", "Sample Member", "member")]


def test_changing_a_person_s_id_to_one_that_is_taken_is_a_conflict(client):
    client.post("/users/create", json=member("MEM-1"))
    second = client.post("/users/create", json=member("MEM-2")).json()["data"]["id"]

    response = client.put(f"/users/{second}", json={"person_code": "mem-1"})

    assert response.status_code == 409
    assert response.json() == {"detail": "ID already exists"}
    assert [code for code, _name, _type in saved_people(client)] == ["MEM-1", "MEM-2"]


def test_saving_a_person_with_the_id_they_already_have_is_not_a_conflict(client):
    person_id = client.post("/users/create", json=member()).json()["data"]["id"]

    same = client.put(f"/users/{person_id}", json={"person_code": "MEM-1", "full_name": "Renamed Member"})
    new = client.put(f"/users/{person_id}", json={"person_code": "MEM-9"})

    assert same.status_code == 200
    assert new.status_code == 200
    assert saved_people(client) == [("MEM-9", "Renamed Member", "member")]


@pytest.mark.parametrize("fields, said", [
    ({"person_code": "   "}, "ID is required"),
    ({"full_name": ""}, "Full name is required"),
    ({"person_code": "X" * 81}, "ID must be at most 80 characters"),
    ({"email": "not-an-email"}, "Email: Enter a valid email address, like name@example.com"),
])
def test_a_person_cannot_be_created_without_an_id_and_a_name_or_with_a_wrong_email(client, fields, said):
    response = client.post("/users/create", json=member(**fields))

    assert response.status_code == 400
    assert response.json() == {"detail": said}
    assert saved_people(client) == []


def test_a_created_person_is_trimmed_and_given_the_names_of_their_course_and_batch(client):
    course = client.post("/courses/create", json={"course_code": "CS101", "course_name": "Computer Science"}).json()["data"]["id"]
    batch = client.post("/batches/create", json={"course_id": course, "batch_name": "Morning A"}).json()["data"]["id"]

    response = client.post("/users/create", json={"person_code": "  STU-1 ", "full_name": " Sample Student ", "person_type": "student", "guardian_phone": "98765 43210", "email": " ", "course_id": course, "batch_id": batch})

    assert response.status_code == 200
    created = response.json()["data"]
    assert (created["person_code"], created["full_name"], created["guardian_phone"], created["email"]) == ("STU-1", "Sample Student", "9876543210", None)
    assert (created["category_program"], created["batch_name"], created["status"], created["face_enrollment_status"]) == ("Computer Science", "Morning A", "active", "not_started")
