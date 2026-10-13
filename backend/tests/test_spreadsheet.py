from datetime import date, datetime

import pytest

from app.utils import spreadsheet
from app.utils.spreadsheet import ImportFileError, build_csv, cell_text, column_key, parse_date, read_sheet


def rows_of(sheet):
    return [(row.number, row.cells) for row in sheet.rows]


def test_excel_numbers_are_read_whole_without_a_trailing_point_zero(make_xlsx):
    # Excel keeps 9876543210 as the number 9876543210.0; an id or a phone number must not gain ".0".
    sheet = read_sheet("people.xlsx", make_xlsx([
        ["staff_id", "contact_number", "level_class", "share"],
        [101.0, 9876543210.0, 7, 12.5],
        ["00042", "+91 98765 43210", "Year 1", None],
    ]))

    first, second = sheet.rows
    assert {key: cell_text(value) for key, value in first.cells.items()} == {"staff_id": "101", "contact_number": "9876543210", "level_class": "7", "share": "12.5"}
    # What was typed as text stays exactly as typed, leading zeros and all.
    assert {key: cell_text(value) for key, value in second.cells.items()} == {"staff_id": "00042", "contact_number": "+91 98765 43210", "level_class": "Year 1", "share": ""}


@pytest.mark.parametrize("value, text", [
    (None, ""), (True, "TRUE"), (False, "FALSE"), (7, "7"), (7.0, "7"), (7.5, "7.5"), (919876543210.0, "919876543210"), (1e16, "10000000000000000"),
    ("  padded  ", "padded"), ("﻿student_id", "student_id"), (date(2024, 6, 15), "2024-06-15"), (datetime(2024, 6, 15), "2024-06-15"),
    (datetime(2024, 6, 15, 8, 30), "2024-06-15 08:30:00"),
])
def test_a_cell_as_text(value, text):
    assert cell_text(value) == text


@pytest.mark.parametrize("header", ["course_code", "Course Code", "  COURSE-CODE ", "course code", "Course_Code*", "course  code"])
def test_headers_are_matched_whatever_their_case_and_spacing(header):
    assert column_key(header) == "course_code"


def test_the_header_row_is_recognised_and_rows_keep_their_spreadsheet_numbers(make_xlsx):
    sheet = read_sheet("courses.XLSX", make_xlsx([
        ["  Course Code ", "COURSE-NAME", None, "notes"],
        ["CS101", "Computer Science"],
        None,
        ["PHY101", "Physics", "under no header", "n"],
        ["   ", None],
        None,
        None,
        ["MATH", "Mathematics"],
    ]))

    assert sheet.headers == ["course_code", "course_name", "notes"]
    assert sheet.titles == {"course_code": "Course Code", "course_name": "COURSE-NAME", "notes": "notes"}
    # Rows 3, 5, 6 and 7 are empty and left out; the others keep the number Excel shows for them.
    assert rows_of(sheet) == [
        (2, {"course_code": "CS101", "course_name": "Computer Science", "notes": None}),
        (4, {"course_code": "PHY101", "course_name": "Physics", "notes": "n"}),
        (8, {"course_code": "MATH", "course_name": "Mathematics", "notes": None}),
    ]


def test_a_header_row_further_down_still_gives_the_right_row_numbers(make_xlsx):
    sheet = read_sheet("courses.xlsx", make_xlsx([None, None, ["course_code", "course_name"], ["CS101", "Computer Science"]]))

    assert rows_of(sheet) == [(4, {"course_code": "CS101", "course_name": "Computer Science"})]


def test_only_the_first_worksheet_is_read(make_xlsx):
    content = make_xlsx([["course_code"], ["CS101"]], title="Courses", more_sheets=[("Instructions", [["course_code"], ["FROM-SECOND-SHEET"]])])

    assert rows_of(read_sheet("courses.xlsx", content)) == [(2, {"course_code": "CS101"})]


def test_a_csv_keeps_its_row_numbers_through_empty_lines_and_quoted_line_breaks(make_csv):
    sheet = read_sheet("courses.csv", make_csv([
        ["course_code", "course_name"],
        None,
        ["CS101", "Computer\nScience"],
        ["", ""],
        ["PHY101", "Physics, applied"],
    ]))

    assert rows_of(sheet) == [
        (3, {"course_code": "CS101", "course_name": "Computer\nScience"}),
        (5, {"course_code": "PHY101", "course_name": "Physics, applied"}),
    ]


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp1252", "utf-16"])
def test_a_csv_is_read_in_the_encodings_excel_writes(make_csv, encoding):
    sheet = read_sheet("courses.csv", make_csv([["course_code", "course_name"], ["CAFE", "Café management"]], encoding=encoding))

    assert sheet.headers == ["course_code", "course_name"]
    assert rows_of(sheet) == [(2, {"course_code": "CAFE", "course_name": "Café management"})]


def test_a_csv_written_with_semicolons_is_read(make_csv):
    sheet = read_sheet("courses.csv", make_csv([["course_code", "course_name"], ["CS101", "Computer Science, applied"]], delimiter=";"))

    assert rows_of(sheet) == [(2, {"course_code": "CS101", "course_name": "Computer Science, applied"})]


def test_a_short_row_has_empty_cells_for_the_columns_it_lacks(make_csv):
    sheet = read_sheet("courses.csv", make_csv([["course_code", "course_name", "description"], ["CS101"]]))

    assert rows_of(sheet) == [(2, {"course_code": "CS101", "course_name": None, "description": None})]


def test_a_column_named_twice_is_refused(make_csv):
    with pytest.raises(ImportFileError, match='"course_code" appears more than once'):
        read_sheet("courses.csv", make_csv([["course_code", "Course Code"], ["A", "B"]]))


@pytest.mark.parametrize("name", ["courses.xls", "courses.txt", "courses.pdf", "courses", "courses.xlsx.exe", ""])
def test_other_file_types_are_refused(name):
    with pytest.raises(ImportFileError, match="Unsupported file type"):
        read_sheet(name, b"course_code\nCS101\n")


@pytest.mark.parametrize("name", ["courses.xlsx", "courses.csv"])
def test_an_empty_file_is_refused(name):
    with pytest.raises(ImportFileError, match="The file is empty"):
        read_sheet(name, b"")


def test_a_file_of_nothing_but_empty_rows_is_refused(make_csv, make_xlsx):
    for name, content in (("courses.csv", make_csv([None, ["", ""], None])), ("courses.xlsx", make_xlsx([None, [None, "  "]]))):
        with pytest.raises(ImportFileError, match="The file is empty"):
            read_sheet(name, content)


@pytest.mark.parametrize("content", [b"this is not a workbook", b"PK\x03\x04 cut short", "course_code,course_name\nCS101,Computer Science\n".encode()])
def test_a_damaged_workbook_is_refused_without_the_library_s_own_words(content):
    with pytest.raises(ImportFileError) as error:
        read_sheet("courses.xlsx", content)

    assert str(error.value) == "The Excel file could not be read. It may be damaged, or not a real .xlsx file."
    assert error.value.__cause__ is None


def test_an_old_or_password_protected_workbook_is_named_as_such():
    with pytest.raises(ImportFileError, match="old .xls file or a password-protected workbook"):
        read_sheet("courses.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64)


def test_a_workbook_that_unpacks_to_far_more_than_it_weighs_is_refused_unopened():
    # Fifty megabytes of the same byte zip down to about fifty kilobytes: small enough to upload,
    # large enough to exhaust the server if it were unpacked.
    import io
    import zipfile

    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", b"0" * (spreadsheet.MAX_UNPACKED_BYTES + 1))
    content = packed.getvalue()
    assert len(content) < spreadsheet.MAX_FILE_BYTES

    with pytest.raises(ImportFileError, match="too large once it is unpacked"):
        read_sheet("courses.xlsx", content)


def test_an_ordinary_workbook_is_nowhere_near_the_unpacked_limit(make_xlsx):
    import io
    import zipfile

    rows = [["student_id", "full_name", "parent_contact", "course_code", "batch_name"]] + [[f"STU-{number:04}", f"Sample Student {number}", "9876543210", "CS101", "Morning A"] for number in range(spreadsheet.MAX_DATA_ROWS)]
    content = make_xlsx(rows)

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        unpacked = sum(item.file_size for item in archive.infolist())
    assert unpacked < spreadsheet.MAX_UNPACKED_BYTES / 50
    assert len(read_sheet("students.xlsx", content).rows) == spreadsheet.MAX_DATA_ROWS


def test_without_the_excel_package_workbooks_are_refused_with_the_reason_and_csv_still_works(make_xlsx, make_csv, monkeypatch):
    def missing():
        raise spreadsheet.SpreadsheetSupportMissing()

    monkeypatch.setattr(spreadsheet, "_openpyxl", missing)
    workbook = make_xlsx([["course_code"], ["CS101"]])

    with pytest.raises(ImportFileError, match="openpyxl") as error:
        read_sheet("courses.xlsx", workbook)

    # The server's set-up is at fault, not the file.
    assert error.value.status == 503
    assert rows_of(read_sheet("courses.csv", make_csv([["course_code"], ["CS101"]]))) == [(2, {"course_code": "CS101"})]


def test_a_workbook_renamed_to_csv_is_refused(make_xlsx):
    with pytest.raises(ImportFileError, match="does not look like a CSV file"):
        read_sheet("courses.csv", make_xlsx([["course_code"], ["CS101"]]))


def test_a_csv_in_an_unknown_encoding_is_refused():
    with pytest.raises(ImportFileError, match="text encoding is not supported"):
        read_sheet("courses.csv", b"course_code\n\x81\x8d\x8f\n")


def test_a_file_over_the_size_limit_is_refused():
    with pytest.raises(ImportFileError, match="larger than 5 MB"):
        read_sheet("courses.csv", b"course_code\n" + b"x" * spreadsheet.MAX_FILE_BYTES)


def test_exactly_the_row_limit_is_read_and_one_row_more_is_refused(make_csv):
    rows = [["course_code"]] + [[f"C{number}"] for number in range(spreadsheet.MAX_DATA_ROWS)]

    assert len(read_sheet("courses.csv", make_csv(rows)).rows) == spreadsheet.MAX_DATA_ROWS
    with pytest.raises(ImportFileError, match="more than 2,000 data rows"):
        read_sheet("courses.csv", make_csv(rows + [["ONE-TOO-MANY"]]))


def test_empty_rows_do_not_count_towards_the_row_limit(make_csv):
    rows = [["course_code"]] + [None] * 500 + [[f"C{number}"] for number in range(spreadsheet.MAX_DATA_ROWS)]

    assert len(read_sheet("courses.csv", make_csv(rows)).rows) == spreadsheet.MAX_DATA_ROWS


def test_a_sheet_that_goes_on_for_tens_of_thousands_of_empty_rows_is_refused(make_xlsx, monkeypatch):
    # A stray cell far below the data makes a sheet as long as its position. Reading stops early.
    monkeypatch.setattr(spreadsheet, "MAX_SCANNED_ROWS", 200)
    rows = [["course_code"], ["CS101"]] + [None] * 300 + [["stray"]]

    with pytest.raises(ImportFileError, match="nearly all of them empty"):
        read_sheet("courses.xlsx", make_xlsx(rows))


@pytest.mark.parametrize("written", [
    "2024-06-15", "2024-6-15", "2024/06/15", "15-06-2024", "15/06/2024", "15.06.2024", "15-Jun-2024", "15 Jun 2024", "15 June 2024",
    "2024-06-15 00:00:00", "2024-06-15T09:30:00", datetime(2024, 6, 15, 9, 30), date(2024, 6, 15),
])
def test_dates_that_are_read(written):
    assert parse_date(written) == date(2024, 6, 15)


@pytest.mark.parametrize("written", ["06/15/2024", "15/06/24", "20240615", "45458", 45458, 45458.0, "31/02/2024", "next week", "", True])
def test_dates_that_are_refused_rather_than_guessed(written):
    with pytest.raises(ValueError, match="2024-06-15"):
        parse_date(written)


@pytest.mark.parametrize("written", ["1899-12-31", "2101-01-01", "0024-06-15", datetime(1800, 1, 1)])
def test_a_date_in_an_impossible_year_is_refused(written):
    with pytest.raises(ValueError, match="between 1900 and 2100"):
        parse_date(written)


def test_a_csv_that_this_app_writes_can_be_read_back():
    content = build_csv(["student_id", "full_name"], [["STU-1", "Name, with a comma"], ["STU-2", "Ünïcode"]])

    assert content.startswith(b"\xef\xbb\xbf")
    assert rows_of(read_sheet("students.csv", content)) == [
        (2, {"student_id": "STU-1", "full_name": "Name, with a comma"}),
        (3, {"student_id": "STU-2", "full_name": "Ünïcode"}),
    ]
