from datetime import date

import pytest

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person


@pytest.fixture()
def school(client):
    # Two courses. Computer Science has two batches, with two students in "Morning A" and one in
    # "Evening B"; Physics has "Lab Group" and no students.
    ids = {}
    for code, name in (("CS101", "Computer Science"), ("PHY101", "Physics")):
        ids[code] = client.post("/courses/create", json={"course_code": code, "course_name": name, "description": f"About {name}"}).json()["data"]["id"]
    for code, batch in (("CS101", "Morning A"), ("CS101", "Evening B"), ("PHY101", "Lab Group")):
        ids[batch] = client.post("/batches/create", json={"course_id": ids[code], "batch_name": batch, "batch_level": "Year 1"}).json()["data"]["id"]
    for code, batch in (("STU-1", "Morning A"), ("STU-2", "Morning A"), ("STU-3", "Evening B")):
        ids[code] = client.post("/users/create", json={
            "person_code": code, "full_name": f"Sample Student {code[-1]}", "person_type": "student", "guardian_phone": "9876543210", "course_id": ids["CS101"], "batch_id": ids[batch],
        }).json()["data"]["id"]
    return ids


def courses(client):
    with client.db() as db:
        return {course.id: (course.course_code, course.course_name, course.description, course.status) for course in db.query(Course)}


def batches(client):
    with client.db() as db:
        return {batch.id: (batch.course_id, batch.batch_name, batch.batch_level, batch.status) for batch in db.query(CourseBatch)}


def students(client):
    with client.db() as db:
        return {person.person_code: (person.course_id, person.batch_id, person.category_program, person.batch_name) for person in db.query(Person).order_by(Person.person_code)}


# ---- courses ------------------------------------------------------------------------------------

def test_a_course_can_be_edited_and_no_second_course_appears(client, school):
    response = client.put(f"/courses/{school['CS101']}", json={"course_code": "CS101", "course_name": "Computer Science and Engineering", "description": "Four-year programme", "status": "inactive"})

    assert response.status_code == 200
    assert response.json()["message"] == "Course updated"
    assert {key: response.json()["data"][key] for key in ("id", "course_code", "course_name", "description", "status")} == {
        "id": school["CS101"], "course_code": "CS101", "course_name": "Computer Science and Engineering", "description": "Four-year programme", "status": "inactive",
    }
    assert courses(client) == {
        school["CS101"]: ("CS101", "Computer Science and Engineering", "Four-year programme", "inactive"),
        school["PHY101"]: ("PHY101", "Physics", "About Physics", "active"),
    }
    # What the Courses page reloads after a save.
    assert sorted(course["course_name"] for course in client.get("/courses").json()["data"]) == ["Computer Science and Engineering", "Physics"]


def test_a_course_code_can_be_changed_and_is_saved_in_capitals(client, school):
    response = client.put(f"/courses/{school['CS101']}", json={"course_code": "  cse-101 "})

    assert response.status_code == 200
    assert courses(client)[school["CS101"]] == ("CSE-101", "Computer Science", "About Computer Science", "active")


def test_changing_a_course_code_to_one_that_is_taken_is_refused_with_a_useful_message(client, school):
    before = courses(client)

    for taken in ("PHY101", "phy101", " Phy101 "):
        response = client.put(f"/courses/{school['CS101']}", json={"course_code": taken, "course_name": "Should not be saved"})

        assert response.status_code == 409
        assert response.json() == {"detail": "Course code already exists"}
    assert courses(client) == before


def test_saving_a_course_with_its_own_unchanged_code_is_not_a_duplicate(client, school):
    # The form always sends the code back, changed or not.
    same = client.put(f"/courses/{school['CS101']}", json={"course_code": "CS101", "course_name": "Computer Science", "description": "About Computer Science", "status": "active"})
    other_case = client.put(f"/courses/{school['CS101']}", json={"course_code": "cs101", "course_name": "Renamed"})

    assert same.status_code == 200
    assert other_case.status_code == 200
    assert courses(client)[school["CS101"]] == ("CS101", "Renamed", "About Computer Science", "active")


@pytest.mark.parametrize("change, said", [
    ({"course_name": "   "}, "Course name is required"),
    ({"course_name": ""}, "Course name is required"),
    ({"course_code": "  "}, "Course code is required"),
    ({"course_code": "C" * 41}, "Course code must be at most 40 characters"),
    ({"course_name": "N" * 121}, "Course name must be at most 120 characters"),
])
def test_a_course_cannot_be_saved_with_an_empty_or_oversized_code_or_name(client, school, change, said):
    # A name of spaces used to be saved as an empty name, and answered with "Course updated".
    before = courses(client)

    response = client.put(f"/courses/{school['CS101']}", json={"course_code": "CS101", "course_name": "Computer Science", **change})

    assert response.status_code == 400
    assert response.json() == {"detail": said}
    assert courses(client) == before


def test_only_the_fields_that_are_sent_are_changed(client, school):
    client.put(f"/courses/{school['CS101']}", json={"status": "pending"})
    client.put(f"/courses/{school['CS101']}", json={"description": None})

    assert courses(client)[school["CS101"]] == ("CS101", "Computer Science", None, "pending")


def test_a_pending_course_from_an_upload_can_be_edited_and_made_active(client, make_csv):
    client.post("/courses/upload", files={"file": ("courses.csv", make_csv([["course_code", "course_name"], ["ART", "Fine Art"]]))})
    imported, = client.get("/courses").json()["data"]
    assert imported["status"] == "pending"

    response = client.put(f"/courses/{imported['id']}", json={"course_code": "ART", "course_name": "Fine Arts", "description": None, "status": "active"})

    assert response.status_code == 200
    assert courses(client) == {imported["id"]: ("ART", "Fine Arts", None, "active")}


def test_editing_a_course_leaves_its_batches_and_students_in_place(client, school):
    batches_before = batches(client)

    client.put(f"/courses/{school['CS101']}", json={"course_code": "CSE", "course_name": "Computer Science and Engineering", "status": "inactive"})

    assert batches(client) == batches_before
    assert {code: (course_id, batch_id) for code, (course_id, batch_id, _course, _batch) in students(client).items()} == {
        "STU-1": (school["CS101"], school["Morning A"]), "STU-2": (school["CS101"], school["Morning A"]), "STU-3": (school["CS101"], school["Evening B"]),
    }


def test_a_renamed_course_is_shown_under_its_new_name_everywhere_students_are_listed(client, school):
    client.put(f"/courses/{school['CS101']}", json={"course_name": "Computer Science and Engineering"})

    # The copy of the course name each student carries, which new attendance records are written from...
    assert {code: name for code, (_course_id, _batch_id, name, _batch) in students(client).items()} == {
        "STU-1": "Computer Science and Engineering", "STU-2": "Computer Science and Engineering", "STU-3": "Computer Science and Engineering",
    }
    # ...and the list face enrollment shows, which reads that copy.
    enrollable = client.get(f"/face/enrollment/users?course_id={school['CS101']}&batch_id={school['Morning A']}").json()["data"]
    assert {person["course_name"] for person in enrollable} == {"Computer Science and Engineering"}


def test_renaming_a_course_does_not_rewrite_attendance_already_recorded(client, school):
    with client.db() as db:
        session = AttendanceSession(session_name="Monday", session_type="regular", course_id=school["CS101"], batch_id=school["Morning A"], category_program="Computer Science", batch_name="Morning A", session_date=date(2026, 1, 5), status="completed")
        db.add(session)
        db.flush()
        db.add(AttendanceRecord(session_id=session.id, person_id=school["STU-1"], person_code="STU-1", course_id=school["CS101"], batch_id=school["Morning A"], category_program="Computer Science", batch_name="Morning A", attendance_date=date(2026, 1, 5), status="present"))
        db.commit()

    client.put(f"/courses/{school['CS101']}", json={"course_name": "Computer Science and Engineering"})
    client.put(f"/batches/{school['Morning A']}", json={"batch_name": "Morning Alpha"})

    with client.db() as db:
        record = db.query(AttendanceRecord).one()
        session = db.query(AttendanceSession).one()
        # History keeps the names it was taken under.
        assert (record.category_program, record.batch_name, record.course_id, record.batch_id) == ("Computer Science", "Morning A", school["CS101"], school["Morning A"])
        assert (session.category_program, session.batch_name) == ("Computer Science", "Morning A")


def test_editing_a_course_that_does_not_exist_is_a_404(client, school):
    response = client.put("/courses/9999", json={"course_name": "Nothing"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


# ---- batches ------------------------------------------------------------------------------------

def test_a_batch_can_be_edited_and_no_second_batch_appears(client, school):
    response = client.put(f"/batches/{school['Morning A']}", json={"course_id": school["CS101"], "batch_name": "Morning Alpha", "batch_level": "Year 2", "status": "inactive"})

    assert response.status_code == 200
    assert response.json()["message"] == "Batch updated"
    assert {key: response.json()["data"][key] for key in ("id", "course_id", "batch_name", "batch_level", "status", "course_name", "people_moved")} == {
        "id": school["Morning A"], "course_id": school["CS101"], "batch_name": "Morning Alpha", "batch_level": "Year 2", "status": "inactive", "course_name": "Computer Science", "people_moved": 0,
    }
    assert batches(client) == {
        school["Morning A"]: (school["CS101"], "Morning Alpha", "Year 2", "inactive"),
        school["Evening B"]: (school["CS101"], "Evening B", "Year 1", "active"),
        school["Lab Group"]: (school["PHY101"], "Lab Group", "Year 1", "active"),
    }
    # The copy of the batch name its students carry follows the rename.
    assert {code: name for code, (_course_id, _batch_id, _course, name) in students(client).items()} == {"STU-1": "Morning Alpha", "STU-2": "Morning Alpha", "STU-3": "Evening B"}


def test_moving_a_batch_to_another_course_is_saved(client, school):
    response = client.put(f"/batches/{school['Evening B']}", json={"course_id": school["PHY101"], "batch_name": "Evening B", "batch_level": "Year 1", "status": "active"})

    assert response.status_code == 200
    assert (response.json()["data"]["course_id"], response.json()["data"]["course_name"]) == (school["PHY101"], "Physics")
    assert batches(client)[school["Evening B"]] == (school["PHY101"], "Evening B", "Year 1", "active")
    # Listed under its new course, and no longer under the old one: what the Batches page reloads.
    assert [batch["batch_name"] for batch in client.get(f"/batches?course_id={school['PHY101']}").json()["data"]] == ["Evening B", "Lab Group"]
    assert [batch["batch_name"] for batch in client.get(f"/batches?course_id={school['CS101']}").json()["data"]] == ["Morning A"]


def test_the_people_of_a_batch_move_with_it_and_nobody_else_does(client, school):
    response = client.put(f"/batches/{school['Morning A']}", json={"course_id": school["PHY101"]})

    assert response.status_code == 200
    assert response.json()["data"]["people_moved"] == 2
    assert students(client) == {
        "STU-1": (school["PHY101"], school["Morning A"], "Physics", "Morning A"),
        "STU-2": (school["PHY101"], school["Morning A"], "Physics", "Morning A"),
        # The student of the batch that stayed is exactly where he was.
        "STU-3": (school["CS101"], school["Evening B"], "Computer Science", "Evening B"),
    }


def test_students_of_a_moved_batch_can_still_be_edited_and_marked_present(client, school):
    # Before, the batch moved and its students stayed behind in the old course: they could no
    # longer be edited ("batch does not belong to course") and the scanner could not mark them.
    client.put(f"/batches/{school['Morning A']}", json={"course_id": school["PHY101"]})

    edited = client.put(f"/users/{school['STU-1']}", json={"notes": "Moved with the batch"})
    session = client.post("/attendance/session/start", json={"session_name": "After the move", "session_type": "regular", "course_id": school["PHY101"], "batch_id": school["Morning A"]})
    marked = client.post("/attendance/mark", json={"session_id": session.json()["data"]["id"], "person_id": school["STU-1"], "recognition_method": "manual"})

    assert edited.status_code == 200
    assert session.status_code == 200
    assert marked.status_code == 200
    assert (marked.json()["message"], marked.json()["data"]["course_id"], marked.json()["data"]["category_program"]) == ("Attendance marked", school["PHY101"], "Physics")


def test_moving_a_batch_does_not_touch_attendance_already_recorded(client, school):
    with client.db() as db:
        db.add(AttendanceRecord(person_id=school["STU-1"], person_code="STU-1", course_id=school["CS101"], batch_id=school["Morning A"], category_program="Computer Science", batch_name="Morning A", attendance_date=date(2026, 1, 5), status="present"))
        db.commit()

    client.put(f"/batches/{school['Morning A']}", json={"course_id": school["PHY101"]})

    with client.db() as db:
        record = db.query(AttendanceRecord).one()
        assert (record.course_id, record.batch_id, record.category_program) == (school["CS101"], school["Morning A"], "Computer Science")


def test_a_batch_cannot_be_moved_to_a_course_that_already_has_a_batch_of_that_name(client, school):
    client.post("/batches/create", json={"course_id": school["PHY101"], "batch_name": "morning a"})
    before, students_before = batches(client), students(client)

    # With the name in the request, as the form sends it, and with the course alone: this second
    # form used to slip past the check and end as a database error.
    for body in ({"course_id": school["PHY101"], "batch_name": "Morning A"}, {"course_id": school["PHY101"]}):
        response = client.put(f"/batches/{school['Morning A']}", json=body)

        assert response.status_code == 409
        assert response.json() == {"detail": "Batch already exists under this course"}
    assert batches(client) == before
    assert students(client) == students_before


def test_renaming_a_batch_to_a_name_taken_in_its_course_is_refused(client, school):
    before = batches(client)

    response = client.put(f"/batches/{school['Morning A']}", json={"batch_name": "evening b"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Batch already exists under this course"}
    assert batches(client) == before


def test_saving_a_batch_with_its_own_unchanged_name_is_not_a_duplicate(client, school):
    # The form always sends the name and the course back, changed or not.
    same = client.put(f"/batches/{school['Morning A']}", json={"course_id": school["CS101"], "batch_name": "Morning A", "batch_level": "Year 1", "status": "active"})
    other_case = client.put(f"/batches/{school['Morning A']}", json={"batch_name": "MORNING A", "status": "pending"})

    assert same.status_code == 200
    assert same.json()["data"]["people_moved"] == 0
    assert other_case.status_code == 200
    assert batches(client)[school["Morning A"]] == (school["CS101"], "MORNING A", "Year 1", "pending")


def test_the_same_name_may_be_used_once_a_batch_has_moved_away(client, school):
    client.put(f"/batches/{school['Morning A']}", json={"course_id": school["PHY101"]})

    again = client.post("/batches/create", json={"course_id": school["CS101"], "batch_name": "Morning A"})

    assert again.status_code == 200


@pytest.mark.parametrize("body, status, said", [
    ({"course_id": None, "batch_name": "Morning A"}, 400, "Select a course for this batch"),
    ({"course_id": 9999, "batch_name": "Morning A"}, 404, "Course not found"),
    ({"batch_name": "   "}, 400, "Batch name is required"),
    ({"batch_name": ""}, 400, "Batch name is required"),
    ({"batch_name": "B" * 121}, 400, "Batch name must be at most 120 characters"),
    ({"batch_level": "L" * 121}, 400, "Batch level must be at most 120 characters"),
])
def test_a_batch_cannot_be_saved_without_a_real_course_or_a_name(client, school, body, status, said):
    before, students_before = batches(client), students(client)

    response = client.put(f"/batches/{school['Morning A']}", json=body)

    assert response.status_code == status
    assert response.json() == {"detail": said}
    assert batches(client) == before
    assert students(client) == students_before


def test_a_course_id_that_is_not_a_number_is_refused_by_the_request_check(client, school):
    response = client.put(f"/batches/{school['Morning A']}", json={"course_id": "physics"})

    assert response.status_code == 422
    assert batches(client)[school["Morning A"]][0] == school["CS101"]


def test_a_batch_s_status_can_be_changed_in_every_direction(client, school):
    for status in ("pending", "inactive", "active", "pending"):
        response = client.put(f"/batches/{school['Lab Group']}", json={"course_id": school["PHY101"], "batch_name": "Lab Group", "batch_level": "Year 1", "status": status})

        assert response.status_code == 200
        assert batches(client)[school["Lab Group"]] == (school["PHY101"], "Lab Group", "Year 1", status)


def test_a_pending_batch_from_an_upload_can_be_found_edited_moved_and_saved(client, school, make_csv):
    client.post("/batches/upload", files={"file": ("batches.csv", make_csv([["batch_name", "course_code"], ["Weekend", "CS101"]]))})
    imported, = [batch for batch in client.get("/batches").json()["data"] if batch["status"] == "pending"]
    assert (imported["batch_name"], imported["course_id"], imported["course_name"]) == ("Weekend", school["CS101"], "Computer Science")

    response = client.put(f"/batches/{imported['id']}", json={"course_id": school["PHY101"], "batch_name": "Weekend Lab", "batch_level": "Beginner", "status": "active"})

    assert response.status_code == 200
    assert batches(client)[imported["id"]] == (school["PHY101"], "Weekend Lab", "Beginner", "active")


def test_a_batch_s_timing_is_kept_when_the_form_does_not_send_one(client, school):
    with client.db() as db:
        db.get(CourseBatch, school["Morning A"]).timing_id = 7
        db.commit()

    client.put(f"/batches/{school['Morning A']}", json={"course_id": school["CS101"], "batch_name": "Morning A", "batch_level": None, "status": "active"})

    with client.db() as db:
        assert db.get(CourseBatch, school["Morning A"]).timing_id == 7


def test_editing_a_batch_that_does_not_exist_is_a_404(client, school):
    response = client.put("/batches/9999", json={"batch_name": "Nothing"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Batch not found"}


# ---- creating: the same rules ------------------------------------------------------------------

def test_creating_follows_the_same_rules_as_editing(client, school):
    blank_course = client.post("/courses/create", json={"course_code": "  ", "course_name": "No Code"})
    taken_course = client.post("/courses/create", json={"course_code": "phy101", "course_name": "Physics Again"})
    blank_batch = client.post("/batches/create", json={"course_id": school["CS101"], "batch_name": "  "})
    taken_batch = client.post("/batches/create", json={"course_id": school["CS101"], "batch_name": "MORNING A"})
    no_course = client.post("/batches/create", json={"course_id": 9999, "batch_name": "Orphan"})

    assert (blank_course.status_code, blank_course.json()["detail"]) == (400, "Course code is required")
    assert (taken_course.status_code, taken_course.json()["detail"]) == (409, "Course code already exists")
    assert (blank_batch.status_code, blank_batch.json()["detail"]) == (400, "Batch name is required")
    assert (taken_batch.status_code, taken_batch.json()["detail"]) == (409, "Batch already exists under this course")
    assert (no_course.status_code, no_course.json()["detail"]) == (404, "Course not found")
    assert len(courses(client)) == 2 and len(batches(client)) == 3


def test_two_requests_creating_the_same_course_at_once_end_as_one_course_and_one_conflict(client, monkeypatch):
    # Both requests pass the "is this code free?" check before either has saved. The database's
    # unique index refuses the second; that is answered as the conflict it is, not as a crash.
    from app.services import course_service

    find = course_service.course_with_code
    asked = []

    def blind_the_first_time(db, code, exclude_id=None):
        asked.append(code)
        return None if len(asked) == 1 else find(db, code, exclude_id)

    client.post("/courses/create", json={"course_code": "CS101", "course_name": "Saved first"})
    monkeypatch.setattr(course_service, "course_with_code", blind_the_first_time)

    response = client.post("/courses/create", json={"course_code": "CS101", "course_name": "Saved second"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Course code already exists"}
    assert [name for _code, name, _description, _status in courses(client).values()] == ["Saved first"]
