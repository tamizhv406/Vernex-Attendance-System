from datetime import date, datetime

import pytest

from app.models.person import Person

STUDENT_HEADER = ["student_id", "full_name", "parent_contact", "course_code", "batch_name", "parent_name", "level_class", "joining_date", "notes"]
STAFF_HEADER = ["staff_id", "full_name", "contact_number", "email", "course_code", "batch_name", "level_class", "joining_date", "notes"]
MEMBER_HEADER = ["member_id"] + STAFF_HEADER[1:]


@pytest.fixture()
def school(client):
    # Two courses; "Morning A" exists under both, "Lab Group" only under Physics.
    ids = {}
    for code, name in (("CS101", "Computer Science"), ("PHY101", "Physics")):
        ids[code] = client.post("/courses/create", json={"course_code": code, "course_name": name}).json()["data"]["id"]
    for code, batch in (("CS101", "Morning A"), ("CS101", "Evening B"), ("PHY101", "Morning A"), ("PHY101", "Lab Group")):
        ids[(code, batch)] = client.post("/batches/create", json={"course_id": ids[code], "batch_name": batch}).json()["data"]["id"]
    return ids


def upload(client, person_type, content, name="people.xlsx"):
    return client.post(f"/users/upload?person_type={person_type}", files={"file": (name, content)})


def people(client):
    with client.db() as db:
        return list(db.query(Person).order_by(Person.id))


def codes(client):
    return [person.person_code for person in people(client)]


def problems(response):
    return [(error["row"], error["column"], error["value"], error["message"]) for error in response.json()["data"]["errors"]]


# ---- students -----------------------------------------------------------------------------------

def test_a_valid_student_is_imported_as_an_active_student_with_no_face_enrolled(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        ["STU-001", "Sample Student One", "+91 98765 43210", "cs101", "morning a", "Sample Parent", "Year 1", "2024-06-15", "Made-up example"],
    ]))

    assert response.status_code == 200
    assert response.json()["message"] == "1 row imported"
    student, = people(client)
    assert (student.person_code, student.full_name, student.person_type) == ("STU-001", "Sample Student One", "student")
    assert (student.status, student.face_enrollment_status) == ("active", "not_started")
    # student_id -> person_code, parent_contact -> guardian_phone (ten digits), parent_name -> guardian_name.
    assert (student.guardian_phone, student.phone, student.guardian_name) == ("9876543210", None, "Sample Parent")
    assert (student.course_id, student.batch_id) == (school["CS101"], school[("CS101", "Morning A")])
    # The copies of the course and batch names that attendance records are written from.
    assert (student.category_program, student.batch_name) == ("Computer Science", "Morning A")
    assert (student.level_class, student.joining_date, student.notes) == ("Year 1", date(2024, 6, 15), "Made-up example")


def test_an_imported_student_shows_up_wherever_students_are_listed(client, make_xlsx, school):
    upload(client, "student", make_xlsx([STUDENT_HEADER, ["STU-001", "Sample Student One", "9876543210", "CS101", "Morning A"]]))

    listed, = client.get("/users?person_type=student").json()["data"]
    assert (listed["person_code"], listed["course_code"], listed["batch_name"], listed["status"], listed["face_enrollment_status"]) == ("STU-001", "CS101", "Morning A", "active", "not_started")
    # ...including the list face enrollment picks its student from.
    enrollable = client.get(f"/face/enrollment/users?course_id={school['CS101']}&batch_id={school[('CS101', 'Morning A')]}").json()["data"]
    assert [person["person_code"] for person in enrollable] == ["STU-001"]


def test_students_with_a_wrong_parent_contact_are_skipped_and_the_others_imported(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        ["STU-001", "Three Digits", "123", "CS101", "Morning A"],
        ["STU-002", "Good Number", "98765-43210", "CS101", "Morning A"],
        ["STU-003", "Nine Digits", 987654321, "CS101", "Morning A"],
        ["STU-004", "Letters", "nine eight seven", "CS101", "Morning A"],
        ["STU-005", "No Number", None, "CS101", "Morning A"],
        ["STU-006", "Typed As A Number", 9876543211.0, "CS101", "Morning A"],
        ["STU-007", "Other Country", "+1 98765 43210", "CS101", "Morning A"],
    ]))

    assert response.json()["message"] == "2 of 7 rows imported, 5 skipped"
    assert problems(response) == [
        (2, "parent_contact", "123", "Phone number must have exactly 10 digits (found 3)"),
        (4, "parent_contact", "987654321", "Phone number must have exactly 10 digits (found 9)"),
        (5, "parent_contact", "nine eight seven", "Phone number can only contain digits, spaces and hyphens, with an optional +91 in front"),
        (6, "parent_contact", "", "parent_contact is required"),
        (8, "parent_contact", "+1 98765 43210", "Only the +91 country code is supported"),
    ]
    assert [(person.person_code, person.guardian_phone) for person in people(client)] == [("STU-002", "9876543210"), ("STU-006", "9876543211")]


def test_a_student_whose_course_or_batch_is_missing_or_unknown_is_reported(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        ["STU-001", "No Course", "9876543210", None, "Morning A"],
        ["STU-002", "No Batch", "9876543210", "CS101", None],
        ["STU-003", "Unknown Course", "9876543210", "CHEM", "Morning A"],
        ["STU-004", "Unknown Batch", "9876543210", "CS101", "Night Owls"],
        ["STU-005", "Neither", "9876543210", None, None],
    ]))

    assert response.json()["message"] == "No rows imported: 5 of 5 rows skipped"
    assert problems(response) == [
        (2, "course_code", "", "course_code is required"),
        (3, "batch_name", "", "batch_name is required"),
        (4, "course_code", "CHEM", "Course not found"),
        (5, "batch_name", "Night Owls", "Batch not found under course CS101"),
        (6, "course_code", "", "course_code is required"),
        (6, "batch_name", "", "batch_name is required"),
    ]
    assert people(client) == []


def test_a_batch_that_belongs_to_a_different_course_is_rejected(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        ["STU-001", "Wrong Course For Batch", "9876543210", "CS101", "Lab Group"],
        ["STU-002", "Right Course", "9876543210", "PHY101", "Lab Group"],
        ["STU-003", "Shared Batch Name", "9876543210", "PHY101", "Morning A"],
    ]))

    assert problems(response) == [(2, "batch_name", "Lab Group", "This batch belongs to a different course (PHY101), not CS101")]
    imported = {person.person_code: (person.course_id, person.batch_id) for person in people(client)}
    # "Morning A" exists under both courses; the student gets the one of the course in the row.
    assert imported == {"STU-002": (school["PHY101"], school[("PHY101", "Lab Group")]), "STU-003": (school["PHY101"], school[("PHY101", "Morning A")])}


def test_a_student_id_repeated_in_the_file_is_reported_with_the_row_it_repeats(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        ["STU-001", "First", "9876543210", "CS101", "Morning A"],
        ["STU-002", "Second", "9876543210", "CS101", "Morning A"],
        ["stu-001", "Same id in small letters", "9876543210", "CS101", "Morning A"],
        ["STU-001", "Same id again", "9876543210", "PHY101", "Lab Group"],
    ]))

    assert problems(response) == [
        (4, "student_id", "stu-001", "Duplicate of row 2 in this file"),
        (5, "student_id", "STU-001", "Duplicate of row 2 in this file"),
    ]
    assert [(person.person_code, person.full_name) for person in people(client)] == [("STU-001", "First"), ("STU-002", "Second")]


def test_a_student_id_that_is_already_saved_is_reported_and_the_saved_student_is_left_alone(client, make_xlsx, school):
    client.post("/users/create", json={"person_code": "STU-001", "full_name": "Saved By Hand", "person_type": "student", "guardian_phone": "9000000001", "course_id": school["CS101"], "batch_id": school[("CS101", "Morning A")]})

    response = upload(client, "student", make_xlsx([STUDENT_HEADER, ["stu-001", "From The File", "9876543210", "PHY101", "Lab Group"], ["STU-002", "New", "9876543210", "CS101", "Evening B"]]))

    assert problems(response) == [(2, "student_id", "stu-001", "Already exists: this ID belongs to a student")]
    assert [(person.person_code, person.full_name, person.guardian_phone, person.course_id) for person in people(client)] == [
        ("STU-001", "Saved By Hand", "9000000001", school["CS101"]),
        ("STU-002", "New", "9876543210", school["CS101"]),
    ]


def test_dates_are_read_from_date_cells_and_from_text_and_wrong_ones_are_reported(client, make_xlsx, school):
    row = lambda code, joining_date: [code, "Sample Student", "9876543210", "CS101", "Morning A", None, None, joining_date]
    response = upload(client, "student", make_xlsx([
        STUDENT_HEADER,
        row("STU-001", datetime(2024, 6, 15)),
        row("STU-002", "15-06-2024"),
        row("STU-003", None),
        row("STU-004", "15/06/24"),
        row("STU-005", 45458),
    ]))

    assert problems(response) == [
        (5, "joining_date", "15/06/24", "Date must be written like 2024-06-15 (year-month-day) or 15-06-2024 (day-month-year)"),
        (6, "joining_date", "45458", "Date must be written like 2024-06-15 (year-month-day) or 15-06-2024 (day-month-year)"),
    ]
    assert [(person.person_code, person.joining_date) for person in people(client)] == [("STU-001", date(2024, 6, 15)), ("STU-002", date(2024, 6, 15)), ("STU-003", None)]


def test_a_student_file_needs_all_five_required_columns(client, make_xlsx, school):
    response = upload(client, "student", make_xlsx([["student_id", "full_name", "parent_contact"], ["STU-001", "Sample Student", "9876543210"]]))

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required columns: course_code, batch_name. The header row must contain: student_id, full_name, parent_contact, course_code, batch_name."}
    assert people(client) == []


# ---- staff and members --------------------------------------------------------------------------

@pytest.mark.parametrize("person_type, header, code", [("admin", STAFF_HEADER, "STF-001"), ("member", MEMBER_HEADER, "MEM-001")])
def test_valid_staff_and_members_are_imported_with_their_own_person_type(client, make_xlsx, school, person_type, header, code):
    response = upload(client, person_type, make_xlsx([
        header,
        [code, "Sample Person One", "98765 43210", "sample.one@example.com", "PHY101", "Lab Group", "Senior", "2024-06-15", "Made-up example"],
        [code[:-1] + "2", "Sample Person Two", "+919876543211", None, None, None, None, None, None],
    ]))

    assert response.json()["message"] == "All 2 rows imported"
    first, second = people(client)
    assert (first.person_code, first.person_type, first.status, first.face_enrollment_status) == (code, person_type, "active", "not_started")
    # contact_number -> phone; the parent fields are a student's and stay empty.
    assert (first.phone, first.guardian_phone, first.email) == ("9876543210", None, "sample.one@example.com")
    assert (first.course_id, first.batch_id, first.category_program, first.batch_name) == (school["PHY101"], school[("PHY101", "Lab Group")], "Physics", "Lab Group")
    assert (first.level_class, first.joining_date, first.notes) == ("Senior", date(2024, 6, 15), "Made-up example")
    # No course and no batch is fine for staff and members.
    assert (second.person_type, second.phone, second.email, second.course_id, second.batch_id) == (person_type, "9876543211", None, None, None)


@pytest.mark.parametrize("person_type, header", [("admin", STAFF_HEADER), ("member", MEMBER_HEADER)])
def test_wrong_numbers_emails_and_repeated_ids_are_reported_for_staff_and_members(client, make_xlsx, school, person_type, header):
    client.post("/users/create", json={"person_code": "TAKEN-1", "full_name": "A Student", "person_type": "student", "guardian_phone": "9876543210", "course_id": school["CS101"], "batch_id": school[("CS101", "Morning A")]})

    response = upload(client, person_type, make_xlsx([
        header,
        ["P-001", "Good", "9876543210", "good@example.com"],
        ["P-002", "Wrong Number", "12345", "p2@example.com"],
        ["P-003", "Wrong Email", "9876543210", "not-an-email"],
        ["P-004", "Also Wrong Email", "9876543210", "two@@example.com"],
        ["p-001", "Repeats Row Two", "9876543210", None],
        ["TAKEN-1", "Id Of A Student", "9876543210", None],
        ["P-007", "Both Wrong", "98765", "a b@example.com"],
    ]))

    assert response.json()["message"] == "1 of 7 rows imported, 6 skipped"
    assert problems(response) == [
        (3, "contact_number", "12345", "Phone number must have exactly 10 digits (found 5)"),
        (4, "email", "not-an-email", "Enter a valid email address, like name@example.com"),
        (5, "email", "two@@example.com", "Enter a valid email address, like name@example.com"),
        (6, header[0], "p-001", "Duplicate of row 2 in this file"),
        # An id is unique across students, staff and members together.
        (7, header[0], "TAKEN-1", "Already exists: this ID belongs to a student"),
        (8, "contact_number", "98765", "Phone number must have exactly 10 digits (found 5)"),
        (8, "email", "a b@example.com", "Enter a valid email address, like name@example.com"),
    ]
    assert codes(client) == ["TAKEN-1", "P-001"]


@pytest.mark.parametrize("person_type, header", [("admin", STAFF_HEADER), ("member", MEMBER_HEADER)])
def test_a_course_and_batch_given_for_staff_or_a_member_must_exist_and_belong_together(client, make_xlsx, school, person_type, header):
    row = lambda code, course, batch: [code, "Sample Person", "9876543210", None, course, batch]
    response = upload(client, person_type, make_xlsx([
        header,
        row("P-001", "CS101", None),
        row("P-002", "CS101", "Evening B"),
        row("P-003", "CHEM", None),
        row("P-004", "CS101", "Lab Group"),
        row("P-005", None, "Morning A"),
        row("P-006", "PHY101", "Night Owls"),
    ]))

    assert problems(response) == [
        (4, "course_code", "CHEM", "Course not found"),
        (5, "batch_name", "Lab Group", "This batch belongs to a different course (PHY101), not CS101"),
        (6, "batch_name", "Morning A", "course_code is required when batch_name is given"),
        (7, "batch_name", "Night Owls", "Batch not found under course PHY101"),
    ]
    assert [(person.person_code, person.course_id, person.batch_id) for person in people(client)] == [
        ("P-001", school["CS101"], None),
        ("P-002", school["CS101"], school[("CS101", "Evening B")]),
    ]


def test_a_staff_file_with_only_the_required_columns_is_enough(client, make_csv):
    response = upload(client, "admin", make_csv([["Staff ID", "Full Name", "Contact Number"], ["STF-001", "Sample Staff", "98765-43210"]]), name="staff.csv")

    assert response.json()["message"] == "1 row imported"
    assert response.json()["data"]["columns"] == ["staff_id", "full_name", "contact_number"]
    staff, = people(client)
    assert (staff.person_type, staff.phone, staff.email, staff.course_id) == ("admin", "9876543210", None, None)


def test_missing_ids_and_names_are_reported(client, make_csv):
    response = upload(client, "member", make_csv([["member_id", "full_name", "contact_number"], ["", "No Id", "9876543210"], ["MEM-002", "", "9876543210"], ["M" * 81, "N" * 161, "9876543210"]]), name="members.csv")

    assert problems(response) == [
        (2, "member_id", "", "member_id is required"),
        (3, "full_name", "", "full_name is required"),
        (4, "member_id", "M" * 81, "Must be at most 80 characters (this has 81)"),
        (4, "full_name", "N" * 161, "Must be at most 160 characters (this has 161)"),
    ]
    assert people(client) == []


# ---- which kind of person -----------------------------------------------------------------------

def test_staff_can_also_be_asked_for_by_the_word_staff(client, make_csv):
    response = upload(client, "staff", make_csv([["staff_id", "full_name", "contact_number"], ["STF-001", "Sample Staff", "9876543210"]]), name="staff.csv")

    assert response.json()["data"]["entity"] == "staff"
    assert [person.person_type for person in people(client)] == ["admin"]


@pytest.mark.parametrize("query", ["", "?person_type=", "?person_type=teacher", "?person_type=students"])
def test_an_upload_without_a_known_person_type_is_refused(client, make_csv, query):
    response = client.post(f"/users/upload{query}", files={"file": ("people.csv", make_csv([["member_id", "full_name", "contact_number"], ["MEM-001", "Sample Member", "9876543210"]]))})

    assert response.status_code == 400
    assert response.json() == {"detail": "person_type must be student, admin or member"}
    assert people(client) == []


def test_a_file_for_one_kind_of_person_is_refused_as_another(client, make_xlsx, school):
    # A students file has student_id and parent_contact; staff are read from staff_id and contact_number.
    response = upload(client, "admin", make_xlsx([STUDENT_HEADER, ["STU-001", "Sample Student", "9876543210", "CS101", "Morning A"]]))

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Missing required columns: staff_id, contact_number.")
    assert people(client) == []
