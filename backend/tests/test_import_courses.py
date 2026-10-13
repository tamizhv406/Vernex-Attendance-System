import pytest

from app.models.course import Course
from app.services.import_service import SPECS, run_import
from app.utils import spreadsheet
from app.utils.spreadsheet import ImportFileError, read_sheet

HEADER = ["course_code", "course_name", "description"]


def upload(client, content, name="courses.xlsx"):
    return client.post("/courses/upload", files={"file": (name, content)})


def saved(client):
    with client.db() as db:
        return [(course.course_code, course.course_name, course.description, course.status) for course in db.query(Course).order_by(Course.id)]


def problems(response):
    return [(error["row"], error["column"], error["value"], error["message"]) for error in response.json()["data"]["errors"]]


def test_three_valid_rows_are_imported_and_two_invalid_rows_are_reported(client, make_xlsx):
    response = upload(client, make_xlsx([
        HEADER,
        ["CS101", "Computer Science", "Three-year programme"],
        [None, "Has no code", None],
        ["phy101", "Physics", None],
        ["MATH", "   ", None],
        ["BIO", "Biology", None],
    ]))

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "3 of 5 rows imported, 2 skipped"
    assert {key: body["data"][key] for key in ("entity", "total_rows", "imported", "skipped", "columns", "ignored_columns")} == {
        "entity": "courses", "total_rows": 5, "imported": 3, "skipped": 2, "columns": HEADER, "ignored_columns": [],
    }
    assert problems(response) == [
        (3, "course_code", "", "course_code is required"),
        (5, "course_name", "", "course_name is required"),
    ]
    # The rows that were left out come back as they were given, to be corrected and uploaded again.
    assert body["data"]["skipped_rows"] == [
        {"row": 3, "values": {"course_code": "", "course_name": "Has no code", "description": ""}},
        {"row": 5, "values": {"course_code": "MATH", "course_name": "", "description": ""}},
    ]
    assert saved(client) == [
        ("CS101", "Computer Science", "Three-year programme", "pending"),
        ("PHY101", "Physics", None, "pending"),
        ("BIO", "Biology", None, "pending"),
    ]


def test_imported_courses_are_pending_whatever_status_the_file_gives(client, make_xlsx):
    response = upload(client, make_xlsx([
        HEADER + ["Status"],
        ["CS101", "Computer Science", None, "active"],
        ["PHY101", "Physics", None, "inactive"],
        ["BIO", "Biology", None, None],
    ]))

    assert response.json()["data"]["imported"] == 3
    # The column is not read at all, and the answer says so.
    assert response.json()["data"]["ignored_columns"] == ["Status"]
    assert [status for _code, _name, _description, status in saved(client)] == ["pending", "pending", "pending"]
    assert [course["status"] for course in client.get("/courses").json()["data"]] == ["pending", "pending", "pending"]


def test_a_code_repeated_in_the_file_is_reported_with_the_row_it_repeats(client, make_xlsx):
    response = upload(client, make_xlsx([
        HEADER,
        ["CS101", "Computer Science", None],
        ["PHY101", "Physics", None],
        ["cs101", "Same code in small letters", None],
        ["  CS101  ", "Same code with spaces", None],
    ]))

    assert response.json()["data"]["imported"] == 2
    assert problems(response) == [
        (4, "course_code", "cs101", "Duplicate of row 2 in this file"),
        (5, "course_code", "CS101", "Duplicate of row 2 in this file"),
    ]
    assert [code for code, *_rest in saved(client)] == ["CS101", "PHY101"]


def test_a_code_that_is_already_saved_is_reported_and_the_saved_course_is_left_alone(client, make_xlsx):
    client.post("/courses/create", json={"course_code": "CS101", "course_name": "Computer Science", "description": "As created by hand", "status": "active"})

    response = upload(client, make_xlsx([
        HEADER,
        ["cs101", "A different name", "A different description"],
        ["PHY101", "Physics", None],
    ]))

    assert response.json()["message"] == "1 of 2 rows imported, 1 skipped"
    assert problems(response) == [(2, "course_code", "cs101", "Already exists")]
    assert saved(client) == [
        ("CS101", "Computer Science", "As created by hand", "active"),
        ("PHY101", "Physics", None, "pending"),
    ]


def test_uploading_the_same_file_twice_adds_nothing_the_second_time(client, make_xlsx):
    content = make_xlsx([HEADER, ["CS101", "Computer Science", None], ["PHY101", "Physics", None]])

    first, second = upload(client, content), upload(client, content)

    assert first.json()["data"]["imported"] == 2
    assert second.json()["message"] == "No rows imported: 2 of 2 rows skipped"
    assert problems(second) == [(2, "course_code", "CS101", "Already exists"), (3, "course_code", "PHY101", "Already exists")]
    assert len(saved(client)) == 2


def test_row_numbers_in_the_report_are_the_rows_of_the_spreadsheet(client, make_xlsx):
    response = upload(client, make_xlsx([
        HEADER,                              # row 1
        ["CS101", "Computer Science", None],  # row 2
        None,                                # row 3 is empty
        [None, "Row four has no code", None],
        None,
        None,
        ["PHY101", "Physics", None],          # row 7
        None,
        ["BIO", None, None],                 # row 9 has no name
    ]))

    assert response.json()["data"]["total_rows"] == 4
    assert [(row, column) for row, column, _value, _message in problems(response)] == [(4, "course_code"), (9, "course_name")]
    assert [row["row"] for row in response.json()["data"]["skipped_rows"]] == [4, 9]


def test_a_row_with_several_problems_reports_each_of_them(client, make_xlsx):
    response = upload(client, make_xlsx([HEADER, [None, None, "Only a description"], ["X" * 41, "N" * 121, None]]))

    assert response.json()["data"]["skipped"] == 2
    assert problems(response) == [
        (2, "course_code", "", "course_code is required"),
        (2, "course_name", "", "course_name is required"),
        (3, "course_code", "X" * 41, "Must be at most 40 characters (this has 41)"),
        (3, "course_name", "N" * 121, "Must be at most 120 characters (this has 121)"),
    ]
    assert saved(client) == []


def test_a_file_in_which_every_row_is_wrong_is_answered_with_the_report_not_an_error(client, make_xlsx):
    response = upload(client, make_xlsx([HEADER, [None, "No code", None]]))

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "No rows imported: 1 of 1 row skipped"
    assert saved(client) == []


def test_a_csv_file_is_imported_like_a_workbook(client, make_csv):
    response = upload(client, make_csv([["Course Code", "Course Name"], ["cs101", "Computer Science"], None, ["", "No code"]]), name="courses.CSV")

    assert response.json()["message"] == "1 of 2 rows imported, 1 skipped"
    assert problems(response) == [(4, "course_code", "", "course_code is required")]
    assert saved(client) == [("CS101", "Computer Science", None, "pending")]


def test_a_code_typed_as_a_number_in_excel_is_not_given_a_decimal_point(client, make_xlsx):
    upload(client, make_xlsx([HEADER, [101.0, 2024, None]]))

    assert saved(client) == [("101", "2024", None, "pending")]


def test_a_missing_required_column_refuses_the_whole_file(client, make_xlsx):
    response = upload(client, make_xlsx([["course_code", "description"], ["CS101", "A perfectly good row otherwise"]]))

    assert response.status_code == 400
    assert response.json() == {"detail": "Missing required column: course_name. The header row must contain: course_code, course_name."}
    assert saved(client) == []


def test_all_missing_required_columns_are_named_together(client, make_csv):
    response = upload(client, make_csv([["code", "name"], ["CS101", "Computer Science"]]), name="courses.csv")

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Missing required columns: course_code, course_name.")
    assert saved(client) == []


@pytest.mark.parametrize("name, content, said", [
    ("courses.csv", b"", "The file is empty."),
    ("courses.xlsx", b"", "The file is empty."),
    ("courses.xlsx", b"neither a workbook nor anything else", "The Excel file could not be read. It may be damaged, or not a real .xlsx file."),
    ("courses.xls", b"course_code,course_name\nCS101,Computer Science\n", "Unsupported file type. Upload a .xlsx or .csv file."),
    ("courses.pdf", b"%PDF-1.7", "Unsupported file type. Upload a .xlsx or .csv file."),
    ("courses.csv", b"course_code,course_name\n", "The file has a header row but no data rows."),
    ("courses.csv", b"\n\n,,\n", "The file is empty."),
])
def test_a_file_that_cannot_be_used_is_refused_as_a_whole(client, name, content, said):
    response = upload(client, content, name=name)

    assert response.status_code == 400
    assert response.json() == {"detail": said}
    assert saved(client) == []


def test_a_file_over_five_megabytes_is_refused_before_anything_is_read_from_it(client):
    content = b"course_code,course_name\nCS101,Computer Science\n" + b" " * spreadsheet.MAX_FILE_BYTES

    response = upload(client, content, name="courses.csv")

    assert response.status_code == 400
    assert response.json() == {"detail": "The file is larger than 5 MB."}
    assert saved(client) == []


def test_one_row_over_the_limit_refuses_the_whole_file(client, make_csv):
    rows = [["course_code", "course_name"]] + [[f"C{number}", f"Course {number}"] for number in range(spreadsheet.MAX_DATA_ROWS + 1)]

    response = upload(client, make_csv(rows), name="courses.csv")

    assert response.status_code == 400
    assert response.json() == {"detail": "The file has more than 2,000 data rows. Split it into smaller files."}
    assert saved(client) == []


def test_a_file_of_exactly_the_row_limit_is_imported(client, make_csv):
    rows = [["course_code", "course_name"]] + [[f"C{number}", f"Course {number}"] for number in range(spreadsheet.MAX_DATA_ROWS)]

    response = upload(client, make_csv(rows), name="courses.csv")

    assert response.json()["message"] == "All 2000 rows imported"
    assert len(saved(client)) == spreadsheet.MAX_DATA_ROWS


def test_the_file_must_be_sent_in_the_field_named_file(client, make_csv):
    content = make_csv([["course_code", "course_name"], ["CS101", "Computer Science"]])

    nothing = client.post("/courses/upload")
    wrong_field = client.post("/courses/upload", files={"upload": ("courses.csv", content)})

    for response in (nothing, wrong_field):
        assert response.status_code == 400
        assert response.json() == {"detail": "Attach a .xlsx or .csv file in the form field \"file\"."}
    assert saved(client) == []


def test_the_upload_address_is_not_mistaken_for_a_course_id(client):
    # "/courses/upload" sits beside "/courses/{course_id}"; the template is a file, not a course.
    template = client.get("/courses/upload/template")

    assert template.status_code == 200
    assert template.headers["content-disposition"] == 'attachment; filename="courses_import_template.xlsx"'
    assert client.get("/courses/1").status_code == 404


def test_the_upload_addresses_are_described_in_the_api_documentation(client):
    # /docs is built from this; it also proves that every route of the application still registers.
    schema = client.get("/openapi.json")

    assert schema.status_code == 200
    paths = schema.json()["paths"]
    for path in ("/courses/upload", "/batches/upload", "/users/upload"):
        assert "multipart/form-data" in paths[path]["post"]["requestBody"]["content"], path
        assert "get" in paths[f"{path}/template"], path
    # The routes that were there before are all still there.
    for path in ("/courses/create", "/courses/{course_id}", "/batches/{batch_id}", "/users/create", "/users/{person_id}", "/people/create", "/face/recognize", "/attendance/mark"):
        assert path in paths, path


def test_a_server_without_the_excel_package_says_so_and_goes_on_taking_csv(client, make_xlsx, make_csv, monkeypatch):
    # A backend updated without "pip install -r requirements.txt" still starts; only Excel is off.
    def missing():
        raise spreadsheet.SpreadsheetSupportMissing()

    monkeypatch.setattr(spreadsheet, "_openpyxl", missing)

    workbook = upload(client, make_xlsx([HEADER, ["CS101", "Computer Science", None]]))
    template = client.get("/courses/upload/template")
    csv_template = client.get("/courses/upload/template?format=csv")
    csv_file = upload(client, make_csv([HEADER, ["CS101", "Computer Science", ""]]), name="courses.csv")

    for refused in (workbook, template):
        assert refused.status_code == 503
        assert "openpyxl" in refused.json()["detail"] and "csv" in refused.json()["detail"]
    assert csv_template.status_code == 200
    assert csv_file.json()["message"] == "1 row imported"
    assert saved(client) == [("CS101", "Computer Science", None, "pending")]


def test_the_import_gives_the_same_result_on_a_session_that_flushes_by_itself(db_session, make_xlsx):
    # The other tests run with the application's own kind of session (no autoflush); this is the other kind.
    db_session.add(Course(course_code="BIO", course_name="Biology"))
    db_session.commit()
    sheet = read_sheet("courses.xlsx", make_xlsx([HEADER, ["CS101", "Computer Science", None], ["bio", "Biology again", None], [None, "No code", None], ["PHY101", "Physics", None]]))

    result = run_import(db_session, SPECS["courses"], sheet)

    assert (result["total_rows"], result["imported"], result["skipped"]) == (4, 2, 2)
    assert [(error["row"], error["message"]) for error in result["errors"]] == [(3, "Already exists"), (4, "course_code is required")]
    assert [(course.course_code, course.status) for course in db_session.query(Course).order_by(Course.id)] == [("BIO", "active"), ("CS101", "pending"), ("PHY101", "pending")]


def test_a_sheet_without_the_required_columns_is_refused_before_the_database_is_touched(db_session, make_xlsx):
    sheet = read_sheet("courses.xlsx", make_xlsx([["course_name"], ["Computer Science"]]))

    with pytest.raises(ImportFileError, match="Missing required column: course_code"):
        run_import(db_session, SPECS["courses"], sheet)

    assert db_session.query(Course).count() == 0
