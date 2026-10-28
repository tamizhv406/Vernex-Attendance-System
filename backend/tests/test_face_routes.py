import pytest

from app.models.course import Course, CourseBatch
from app.models.person import Person


@pytest.fixture()
def people(client):
    # Two batches of one course, and a second course. Staff and members are mostly without a batch,
    # as in a real school, but one of each is assigned to the batch the students are in.
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        other_course = Course(course_code="MA101", course_name="Maths")
        db.add_all([course, other_course])
        db.flush()
        morning = CourseBatch(course_id=course.id, batch_name="Morning A")
        evening = CourseBatch(course_id=course.id, batch_name="Evening B")
        db.add_all([morning, evening])
        db.flush()
        db.add_all([
            Person(person_code="S1", full_name="Alice", person_type="student", course_id=course.id, batch_id=morning.id),
            Person(person_code="S2", full_name="Arun", person_type="student", course_id=course.id, batch_id=evening.id),
            Person(person_code="T1", full_name="Bob", person_type="admin", course_id=course.id, batch_id=morning.id),
            Person(person_code="T2", full_name="Zara", person_type="admin"),
            Person(person_code="T3", full_name="Carl", person_type="admin", course_id=other_course.id),
            Person(person_code="M1", full_name="Mona", person_type="member"),
            Person(person_code="M2", full_name="Dev", person_type="member", course_id=course.id, batch_id=morning.id),
        ])
        db.commit()
        return {"course": course.id, "other_course": other_course.id, "morning": morning.id, "evening": evening.id}


def codes(answer):
    assert answer.status_code == 200, answer.text
    return [row["person_code"] for row in answer.json()["data"]]


def test_students_are_listed_per_batch_without_the_staff_and_members_of_that_batch(client, people):
    answer = client.get("/face/enrollment/users", params={"course_id": people["course"], "batch_id": people["morning"]})

    assert codes(answer) == ["S1"]


def test_person_type_student_is_the_same_as_leaving_it_out(client, people):
    answer = client.get("/face/enrollment/users", params={"person_type": "student", "course_id": people["course"], "batch_id": people["evening"]})

    assert codes(answer) == ["S2"]


@pytest.mark.parametrize("params", [{}, {"course_id": 1}, {"batch_id": 1}, {"person_type": "student"}])
def test_students_need_a_course_and_a_batch(client, people, params):
    answer = client.get("/face/enrollment/users", params=params)

    assert answer.status_code == 400
    assert answer.json()["detail"] == "Select a course and a batch."


def test_every_staff_member_is_listed_by_name_without_a_course_or_batch(client, people):
    answer = client.get("/face/enrollment/users", params={"person_type": "admin"})

    assert codes(answer) == ["T1", "T3", "T2"]  # Bob, Carl, Zara


def test_staff_can_be_narrowed_to_a_course_or_a_batch(client, people):
    assert codes(client.get("/face/enrollment/users", params={"person_type": "admin", "course_id": people["other_course"]})) == ["T3"]
    assert codes(client.get("/face/enrollment/users", params={"person_type": "admin", "batch_id": people["morning"]})) == ["T1"]


def test_every_member_is_listed_by_name(client, people):
    answer = client.get("/face/enrollment/users", params={"person_type": "member"})

    assert codes(answer) == ["M2", "M1"]  # Dev, Mona


@pytest.mark.parametrize("person_type", ["staff", "STUDENT", "teacher", ""])
def test_an_unknown_person_type_is_refused(client, people, person_type):
    answer = client.get("/face/enrollment/users", params={"person_type": person_type, "course_id": people["course"], "batch_id": people["morning"]})

    assert answer.status_code == 400
    assert answer.json()["detail"] == "Choose students, staff or members."
