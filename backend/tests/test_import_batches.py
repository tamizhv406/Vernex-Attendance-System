import pytest

from app.models.course import Course, CourseBatch

HEADER = ["batch_name", "course_code", "batch_level"]


@pytest.fixture()
def courses(client):
    created = {}
    for code, name in (("CS101", "Computer Science"), ("PHY101", "Physics")):
        created[code] = client.post("/courses/create", json={"course_code": code, "course_name": name}).json()["data"]["id"]
    return created


def upload(client, content, name="batches.xlsx"):
    return client.post("/batches/upload", files={"file": (name, content)})


def saved(client):
    with client.db() as db:
        rows = db.query(CourseBatch, Course).join(Course, CourseBatch.course_id == Course.id).order_by(CourseBatch.id)
        return [(batch.batch_name, course.course_code, batch.batch_level, batch.status) for batch, course in rows]


def problems(response):
    return [(error["row"], error["column"], error["value"], error["message"]) for error in response.json()["data"]["errors"]]


def test_a_valid_batch_is_imported_under_its_course_as_pending(client, make_xlsx, courses):
    response = upload(client, make_xlsx([HEADER, ["Morning A", "CS101", "Year 1"]]))

    assert response.status_code == 200
    assert response.json()["message"] == "1 row imported"
    assert saved(client) == [("Morning A", "CS101", "Year 1", "pending")]
    # The relationship is the real one: the batch is listed under its course like any other.
    listed = client.get(f"/batches?course_id={courses['CS101']}").json()["data"]
    assert [(batch["batch_name"], batch["course_id"], batch["course_name"], batch["status"]) for batch in listed] == [("Morning A", courses["CS101"], "Computer Science", "pending")]
    assert client.get(f"/batches?course_id={courses['PHY101']}").json()["data"] == []


def test_imported_batches_are_pending_whatever_status_the_file_gives(client, make_xlsx, courses):
    response = upload(client, make_xlsx([HEADER + ["status"], ["Morning A", "CS101", None, "active"], ["Evening B", "CS101", None, "inactive"]]))

    assert response.json()["data"]["ignored_columns"] == ["status"]
    assert [status for *_rest, status in saved(client)] == ["pending", "pending"]


def test_a_batch_for_a_course_that_does_not_exist_is_skipped_and_reported(client, make_xlsx, courses):
    response = upload(client, make_xlsx([HEADER, ["Morning A", "CS101", None], ["Lab", "CHEM", None], ["Evening B", "phy101", None]]))

    assert response.json()["message"] == "2 of 3 rows imported, 1 skipped"
    assert problems(response) == [(3, "course_code", "CHEM", "Course not found. Create or import the course first")]
    assert saved(client) == [("Morning A", "CS101", None, "pending"), ("Evening B", "PHY101", None, "pending")]


def test_a_batch_repeated_under_the_same_course_is_reported_with_the_row_it_repeats(client, make_xlsx, courses):
    response = upload(client, make_xlsx([
        HEADER,
        ["Morning A", "CS101", None],
        ["Morning A", "PHY101", None],
        ["morning a", "cs101", "Again, in small letters"],
        ["Evening B", "CS101", None],
    ]))

    assert problems(response) == [(4, "batch_name", "morning a", "Duplicate of row 2 in this file")]
    # The same name under another course is a different batch.
    assert saved(client) == [("Morning A", "CS101", None, "pending"), ("Morning A", "PHY101", None, "pending"), ("Evening B", "CS101", None, "pending")]


def test_a_batch_that_is_already_saved_under_its_course_is_reported_and_left_alone(client, make_xlsx, courses):
    client.post("/batches/create", json={"course_id": courses["CS101"], "batch_name": "Morning A", "batch_level": "As created by hand"})

    response = upload(client, make_xlsx([HEADER, ["MORNING A", "CS101", "From the file"], ["Morning A", "PHY101", None]]))

    assert problems(response) == [(2, "batch_name", "MORNING A", "Already exists under this course")]
    assert saved(client) == [("Morning A", "CS101", "As created by hand", "active"), ("Morning A", "PHY101", None, "pending")]


def test_missing_values_are_reported_per_column(client, make_xlsx, courses):
    response = upload(client, make_xlsx([HEADER, [None, "CS101", "Year 1"], ["Morning A", None, None], ["B" * 121, "CS101", "L" * 121]]))

    assert problems(response) == [
        (2, "batch_name", "", "batch_name is required"),
        (3, "course_code", "", "course_code is required"),
        (4, "batch_name", "B" * 121, "Must be at most 120 characters (this has 121)"),
        (4, "batch_level", "L" * 121, "Must be at most 120 characters (this has 121)"),
    ]
    assert saved(client) == []


def test_batches_can_be_imported_for_a_course_that_was_itself_just_imported(client, make_csv):
    client.post("/courses/upload", files={"file": ("courses.csv", make_csv([["course_code", "course_name"], ["ART", "Fine Art"]]))})

    response = upload(client, make_csv([HEADER, ["Studio 1", "art", ""]]), name="batches.csv")

    assert response.json()["data"]["imported"] == 1
    assert saved(client) == [("Studio 1", "ART", None, "pending")]


def test_a_missing_required_column_refuses_the_whole_file(client, make_xlsx, courses):
    response = upload(client, make_xlsx([["batch_name", "batch_level"], ["Morning A", "Year 1"]]))

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required column: course_code. The header row must contain: batch_name, course_code."}
    assert saved(client) == []
