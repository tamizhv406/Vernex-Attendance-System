"""Bulk import of courses, batches and people from a spreadsheet.

A file is first checked as a whole: readable, within the limits, holding the required columns. A
file that fails there is refused and nothing from it is saved. After that every row stands on its
own: valid rows are saved, the others are reported with their spreadsheet row number, the column,
the value that was given and the reason. A row counts as imported only once the database has it.
"""
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.schemas.person_schema import PersonCreate
from app.services import course_service
from app.services.person_service import build_person, person_with_code
from app.utils.spreadsheet import (
    CSV_MEDIA_TYPE, MAX_DATA_ROWS, MAX_FILE_BYTES, XLSX_MEDIA_TYPE, ImportFileError, Sheet, build_csv, build_template,
    cell_text, parse_date,
)
from app.utils.validation import FieldError, normalize_email, normalize_phone, text_limit

# An imported course or batch waits for someone to look at it, whatever status the file gives it.
IMPORTED_STATUS = "pending"
ALREADY_EXISTS = "Already exists"
NOT_SAVED = "The database refused this row"
PERSON_TYPE_NAMES = {"student": "a student", "admin": "a staff member", "member": "a member"}

_PHONE_HELP = "Ten digits. Spaces, hyphens and +91 in front are accepted: 98765 43210 or +91 98765 43210."
_DATE_HELP = "Written as 2024-06-15 (year-month-day). 15-06-2024 is also read, as day-month-year."
_FILE_NOTES = (
    "Type your rows on the first sheet, under the header row. Do not rename the columns.",
    "Columns with a dark header are required. Columns with a grey header may be left empty or deleted.",
    f"One file holds up to {MAX_DATA_ROWS:,} rows and {MAX_FILE_BYTES // (1024 * 1024)} MB. Empty rows are skipped.",
    "A row with a problem is left out and listed after the upload, with its row number. The other rows are still imported.",
)


@dataclass(frozen=True)
class Column:
    name: str
    required: bool
    help: str


@dataclass(frozen=True)
class ImportSpec:
    key: str
    title: str
    columns: tuple
    notes: tuple
    examples: tuple
    person_type: str | None = None

    @property
    def required(self):
        return [column.name for column in self.columns if column.required]

    @property
    def optional(self):
        return [column.name for column in self.columns if not column.required]


def _person_spec(key, title, singular, person_type, id_column, id_example):
    student = person_type == "student"
    contact = "parent_contact" if student else "contact_number"
    relation = [
        Column("course_code", student, "Code of a course that already exists." + ("" if student else " Leave empty if not assigned to a course.")),
        Column("batch_name", student, "Name of an existing batch of that course." + ("" if student else " Needs course_code.")),
    ]
    columns = [
        Column(id_column, True, f"Unique id, for example {id_example}. No other student, staff member or member may have it."),
        Column("full_name", True, "Name as it should appear in attendance."),
        Column(contact, True, _PHONE_HELP),
    ]
    if student:
        columns += relation + [Column("parent_name", False, "Name of the parent or guardian.")]
    else:
        columns += [Column("email", False, "Email address, for example name@example.com.")] + relation
    columns += [
        Column("level_class", False, "Level or class, for example Year 1."),
        Column("joining_date", False, _DATE_HELP),
        Column("notes", False, "Anything worth remembering."),
    ]
    sample = {
        id_column: id_example, "full_name": f"Sample {singular.title()} One", contact: "98765 43210",
        "course_code": "CS101", "batch_name": "Morning A", "parent_name": "Sample Parent", "email": "sample.one@example.com",
        "level_class": "Year 1", "joining_date": "2024-06-15", "notes": "Made-up example",
    }
    second = dict(sample, **{id_column: id_example[:-1] + "2", "full_name": f"Sample {singular.title()} Two", contact: "+91 98765 43211", "email": "sample.two@example.com", "notes": ""})
    return ImportSpec(
        key=key,
        title=title,
        columns=tuple(columns),
        notes=_FILE_NOTES + (
            f"Every imported {singular} is saved as Active, with face enrollment still to be done.",
            "course_code and batch_name must match a course and a batch that already exist: import courses first, then batches." if student
            else "course_code and batch_name are optional; when given they must match a course and a batch that already exist.",
        ),
        examples=tuple([row[column.name] for column in columns] for row in (sample, second)),
        person_type=person_type,
    )


SPECS = {
    "courses": ImportSpec(
        key="courses",
        title="Courses",
        columns=(
            Column("course_code", True, "Short unique code, for example CS101. Saved in capital letters."),
            Column("course_name", True, "Name of the course."),
            Column("description", False, "Anything that helps to tell the course apart."),
        ),
        notes=_FILE_NOTES + ("Imported courses are saved with the status Pending. Review them on the Courses page.",),
        examples=(["CS101", "Computer Science", "Three-year programme"], ["PHY101", "Physics", ""]),
    ),
    "batches": ImportSpec(
        key="batches",
        title="Batches",
        columns=(
            Column("batch_name", True, "Name of the batch. Two batches of one course cannot share a name."),
            Column("course_code", True, "Code of a course that already exists. Import or create the course first."),
            Column("batch_level", False, "Level or year, for example Beginner."),
        ),
        notes=_FILE_NOTES + ("Imported batches are saved with the status Pending. Review them on the Batches page.",),
        examples=(["Morning A", "CS101", "Year 1"], ["Evening B", "CS101", ""]),
    ),
    "students": _person_spec("students", "Students", "student", "student", "student_id", "STU-001"),
    "staff": _person_spec("staff", "Staff", "staff member", "admin", "staff_id", "STF-001"),
    "members": _person_spec("members", "Members", "member", "member", "member_id", "MEM-001"),
}
# The API names people by person_type, as the rest of /users does.
PERSON_SPECS = {spec.person_type: spec for spec in SPECS.values() if spec.person_type}


@dataclass
class Checked:
    """One row after its values were checked."""
    fields: dict  # what would be saved
    problems: list  # (column, why the value cannot be used)
    key: tuple | None = None  # what must not repeat, in the file or in the database
    exists: str = ""  # set when the database already holds this key: the message to report


@dataclass
class Plan:
    """How one kind of record is checked and saved."""
    key_column: str
    check: callable
    make: callable  # fields -> a new, unsaved record
    taken: callable  # fields -> is this key in the database now?


@dataclass
class Draft:
    number: int
    values: dict  # column -> the text that was given
    fields: dict
    problems: list = field(default_factory=list)


def template_file(spec: ImportSpec, file_format: str = "xlsx"):
    """The template for one kind of record: (bytes, media type, file name)."""
    name = f"{spec.key}_import_template"
    headers = [column.name for column in spec.columns]
    if file_format == "csv":
        # A CSV has no second sheet for the examples, so it is the header row and nothing else.
        return build_csv(headers), CSV_MEDIA_TYPE, f"{name}.csv"
    if file_format != "xlsx":
        raise ImportFileError("The template is available as xlsx or csv.")
    content = build_template(spec.title, [(column.name, column.required, column.help) for column in spec.columns], spec.notes, spec.examples)
    return content, XLSX_MEDIA_TYPE, f"{name}.xlsx"


def run_import(db: Session, spec: ImportSpec, sheet: Sheet):
    """Imports the rows of a sheet that was already read. Returns the summary sent back to the browser.

    Raises ImportFileError when the file as a whole cannot be used, before anything is saved.
    """
    missing = [name for name in spec.required if name not in sheet.headers]
    if missing:
        raise ImportFileError(f"Missing required column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. The header row must contain: {', '.join(spec.required)}.")
    if not sheet.rows:
        raise ImportFileError("The file has a header row but no data rows.")
    known = {column.name for column in spec.columns}
    columns = [name for name in sheet.headers if name in known]
    ignored = [sheet.titles[name] for name in sheet.headers if name not in known]

    _open_transaction(db)
    plan = _PLANS[spec.key](db, spec)
    drafts = []
    first_row_with = {}
    for row in sheet.rows:
        # A number cell is read as the number it shows: 9876543210, never "9876543210.0".
        values = {name: cell_text(row.cells.get(name)) for name in columns}
        checked = plan.check(values, row.cells)
        problems = list(checked.problems)
        if checked.key is not None:
            first = first_row_with.setdefault(checked.key, row.number)
            if first != row.number:
                problems.append((plan.key_column, f"Duplicate of row {first} in this file"))
            elif checked.exists:
                problems.append((plan.key_column, checked.exists))
        drafts.append(Draft(row.number, values, checked.fields, problems))

    refused = _save(db, plan, [draft for draft in drafts if not draft.problems])
    db.commit()

    errors, skipped_rows = [], []
    for draft in drafts:
        problems = draft.problems or ([refused[draft.number]] if draft.number in refused else [])
        if not problems:
            continue
        skipped_rows.append({"row": draft.number, "values": draft.values})
        errors.extend({"row": draft.number, "column": column, "value": draft.values.get(column, ""), "message": message} for column, message in problems)
    return {
        "entity": spec.key,
        "total_rows": len(drafts),
        "imported": len(drafts) - len(skipped_rows),
        "skipped": len(skipped_rows),
        "errors": errors,
        "skipped_rows": skipped_rows,
        "columns": columns,
        "ignored_columns": ignored,
    }


def summary_message(result: dict):
    total, imported, skipped = result["total_rows"], result["imported"], result["skipped"]
    rows = "row" if total == 1 else "rows"
    if not skipped:
        return f"All {total} {rows} imported" if total > 1 else "1 row imported"
    if not imported:
        return f"No rows imported: {skipped} of {total} {rows} skipped"
    return f"{imported} of {total} {rows} imported, {skipped} skipped"


def _open_transaction(db: Session):
    # SQLite through Python's sqlite3 opens a transaction only before INSERT, UPDATE or DELETE. A
    # SAVEPOINT sent first becomes the transaction itself, and releasing it commits: each row would
    # be saved for good the moment it passed, and a later failure could not take the import back.
    # Opening the transaction by hand keeps every row inside the one commit at the end.
    #
    # IMMEDIATE takes the write lock now. Taken later, between reading and writing, it is refused
    # outright if another connection (a scanner marking attendance) writes in that moment.
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    if not getattr(connection.connection.dbapi_connection, "in_transaction", True):
        connection.exec_driver_sql("BEGIN IMMEDIATE")


# What the database can hold against one row: a key that exists, a value it cannot store. Anything
# else (a locked or unreachable database) is the database's own trouble; it is not answered by
# trying two thousand rows one by one, and is left to end the import.
_ROW_ERRORS = (IntegrityError, DataError)


def _save(db: Session, plan: Plan, drafts: list):
    """Writes the rows that passed every check. Returns {row number: (column, message)} for rows the database refused."""
    if not drafts:
        return {}
    try:
        # All at once first: one round trip to the database instead of several per row, which is
        # the difference between a second and minutes on a remote database.
        with db.begin_nested():
            db.add_all([plan.make(draft.fields) for draft in drafts])
            db.flush()
        return {}
    except _ROW_ERRORS:
        pass
    # Something in the batch was refused (another request may have saved the same id meanwhile).
    # The savepoint took the whole batch back, so now each row gets a savepoint of its own and
    # only the rows the database really refuses are left out.
    refused = {}
    for draft in drafts:
        try:
            with db.begin_nested():
                db.add(plan.make(draft.fields))
                db.flush()
        except IntegrityError:
            refused[draft.number] = (plan.key_column, ALREADY_EXISTS) if plan.taken(draft.fields) else ("", NOT_SAVED)
        except DataError:
            refused[draft.number] = ("", NOT_SAVED)
    return refused


def _required(problems, values, column):
    if values.get(column):
        return True
    problems.append((column, f"{column} is required"))
    return False


def _fits(problems, model, model_field, column, value):
    limit = text_limit(model, model_field)
    if value and limit and len(value) > limit:
        problems.append((column, f"Must be at most {limit} characters (this has {len(value)})"))


def _course_plan(db: Session, spec: ImportSpec):
    existing = {code.lower() for (code,) in db.query(Course.course_code)}

    def check(values, _cells):
        problems = []
        code = values["course_code"].upper()
        name = values["course_name"]
        _required(problems, values, "course_code")
        _required(problems, values, "course_name")
        _fits(problems, Course, "course_code", "course_code", code)
        _fits(problems, Course, "course_name", "course_name", name)
        fields = {"course_code": code, "course_name": name, "description": values.get("description") or None, "status": IMPORTED_STATUS}
        return Checked(fields, problems, key=(code.lower(),) if code else None, exists=ALREADY_EXISTS if code.lower() in existing else "")

    return Plan("course_code", check, lambda fields: Course(**fields), lambda fields: course_service.course_with_code(db, fields["course_code"]))


def _batch_plan(db: Session, spec: ImportSpec):
    courses = {course.course_code.lower(): course for course in db.query(Course)}
    existing = {(course_id, name.lower()) for course_id, name in db.query(CourseBatch.course_id, CourseBatch.batch_name)}

    def check(values, _cells):
        problems = []
        name = values["batch_name"]
        code = values["course_code"]
        _required(problems, values, "batch_name")
        _fits(problems, CourseBatch, "batch_name", "batch_name", name)
        level = values.get("batch_level") or None
        _fits(problems, CourseBatch, "batch_level", "batch_level", level)
        course = None
        if _required(problems, values, "course_code"):
            course = courses.get(code.lower())
            if not course:
                problems.append(("course_code", "Course not found. Create or import the course first"))
        fields = {"course_id": course.id if course else None, "batch_name": name, "batch_level": level, "status": IMPORTED_STATUS}
        exists = f"{ALREADY_EXISTS} under this course" if course and (course.id, name.lower()) in existing else ""
        return Checked(fields, problems, key=(code.lower(), name.lower()) if code and name else None, exists=exists)

    return Plan("batch_name", check, lambda fields: CourseBatch(**fields), lambda fields: course_service.batch_named(db, fields["course_id"], fields["batch_name"]))


def _person_plan(db: Session, spec: ImportSpec):
    student = spec.person_type == "student"
    id_column = spec.columns[0].name
    phone_column, phone_field = ("parent_contact", "guardian_phone") if student else ("contact_number", "phone")
    # The column each saved field was read from, to name the right column if the shared rules object.
    column_of = {"person_code": id_column, phone_field: phone_column, "guardian_name": "parent_name"}
    courses = {course.course_code.lower(): course for course in db.query(Course)}
    batches = {}
    courses_with_batch = {}
    course_codes = {course.id: course.course_code for course in courses.values()}
    for batch in db.query(CourseBatch):
        batches[(batch.course_id, batch.batch_name.lower())] = batch
        courses_with_batch.setdefault(batch.batch_name.lower(), []).append(course_codes.get(batch.course_id, "another course"))
    # An id is unique across students, staff and members together.
    existing = {code.lower(): person_type for code, person_type in db.query(Person.person_code, Person.person_type)}

    def make(fields):
        return build_person(db, PersonCreate(**fields))[0]

    def check(values, cells):
        problems = []
        code = values[id_column]
        _required(problems, values, id_column)
        _fits(problems, Person, "person_code", id_column, code)
        _required(problems, values, "full_name")
        _fits(problems, Person, "full_name", "full_name", values["full_name"])

        phone = None
        if _required(problems, values, phone_column):
            try:
                phone = normalize_phone(values[phone_column])
            except ValueError as error:
                problems.append((phone_column, str(error)))
        email = None
        if values.get("email"):
            try:
                email = normalize_email(values["email"])
                _fits(problems, Person, "email", "email", email)
            except ValueError as error:
                problems.append(("email", str(error)))

        course_code = values.get("course_code", "")
        batch_name = values.get("batch_name", "")
        if student:
            _required(problems, values, "course_code")
            _required(problems, values, "batch_name")
        course = batch = None
        if course_code:
            course = courses.get(course_code.lower())
            if not course:
                problems.append(("course_code", "Course not found"))
        if batch_name and course:
            batch = batches.get((course.id, batch_name.lower()))
            if not batch:
                elsewhere = courses_with_batch.get(batch_name.lower())
                problems.append(("batch_name", f"This batch belongs to a different course ({', '.join(sorted(elsewhere))}), not {course.course_code}" if elsewhere else f"Batch not found under course {course.course_code}"))
        elif batch_name and not course_code and not student:
            problems.append(("batch_name", "course_code is required when batch_name is given"))

        joining_date = None
        if values.get("joining_date"):
            try:
                joining_date = parse_date(cells.get("joining_date"))
            except ValueError as error:
                problems.append(("joining_date", str(error)))
        _fits(problems, Person, "guardian_name", "parent_name", values.get("parent_name"))
        _fits(problems, Person, "level_class", "level_class", values.get("level_class"))

        fields = {
            "person_code": code,
            "full_name": values["full_name"],
            "person_type": spec.person_type,
            phone_field: phone,
            "email": email,
            "guardian_name": values.get("parent_name") or None,
            "course_id": course.id if course else None,
            "batch_id": batch.id if batch else None,
            "level_class": values.get("level_class") or None,
            "joining_date": joining_date,
            "notes": values.get("notes") or None,
        }
        if not problems:
            # The same rules as POST /users/create have the last word on every row.
            try:
                make(fields)
            except FieldError as error:
                problems.append((column_of.get(error.field, error.field), error.message))
            except HTTPException as error:
                problems.append(("", str(error.detail)))
            except ValidationError:
                problems.append(("", "This row could not be read"))
        owner = existing.get(code.lower())
        exists = f"{ALREADY_EXISTS}: this ID belongs to {PERSON_TYPE_NAMES.get(owner, 'another person')}" if owner is not None else ""
        return Checked(fields, problems, key=(code.lower(),) if code else None, exists=exists)

    return Plan(id_column, check, make, lambda fields: person_with_code(db, fields["person_code"]))


_PLANS = {"courses": _course_plan, "batches": _batch_plan, "students": _person_plan, "staff": _person_plan, "members": _person_plan}
