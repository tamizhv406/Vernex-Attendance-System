import sqlite3

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.course import Course
from app.routes.import_routes import IMPORT_FAILED
from app.services import import_service
from app.services.import_service import SPECS, run_import
from app.utils.spreadsheet import read_sheet

THREE_COURSES = [["course_code", "course_name"], ["CS101", "Computer Science"], ["PHY101", "Physics"], ["BIO", "Biology"]]


def upload(client, content):
    return client.post("/courses/upload", files={"file": ("courses.csv", content)})


def saved(client):
    with client.db() as db:
        return [(course.course_code, course.course_name, course.status) for course in db.query(Course).order_by(Course.course_code)]


def problems(response):
    return [(error["row"], error["column"], error["value"], error["message"]) for error in response.json()["data"]["errors"]]


def saving_physics_first(write):
    # Every row of the file has been checked against the database and found new. Before any of them
    # is written, another request saves a course with one of the same codes.
    def someone_else_first(db, plan, drafts):
        db.execute(insert(Course).values(course_code="PHY101", course_name="Saved by another request", status="active"))
        return write(db, plan, drafts)

    return someone_else_first


@pytest.fixture()
def another_request_saves_physics(monkeypatch):
    monkeypatch.setattr(import_service, "_save", saving_physics_first(import_service._save))


def test_a_row_the_database_refuses_does_not_stop_the_other_rows(client, make_csv, another_request_saves_physics):
    response = upload(client, make_csv(THREE_COURSES))

    assert response.status_code == 200
    assert response.json()["message"] == "2 of 3 rows imported, 1 skipped"
    # Reported as what it is, and not counted as imported: the database never took this row.
    assert problems(response) == [(3, "course_code", "PHY101", "Already exists")]
    assert saved(client) == [("BIO", "Biology", "pending"), ("CS101", "Computer Science", "pending"), ("PHY101", "Saved by another request", "active")]


def test_the_application_goes_on_working_after_an_import_in_which_the_database_refused_rows(client, make_csv, monkeypatch):
    write = import_service._save
    monkeypatch.setattr(import_service, "_save", saving_physics_first(write))
    upload(client, make_csv(THREE_COURSES))
    monkeypatch.setattr(import_service, "_save", write)

    created = client.post("/courses/create", json={"course_code": "ART", "course_name": "Fine Art"})
    second = upload(client, make_csv([["course_code", "course_name"], ["MATH", "Mathematics"]]))

    assert created.status_code == 200
    assert second.json()["message"] == "1 row imported"
    assert [code for code, _name, _status in saved(client)] == ["ART", "BIO", "CS101", "MATH", "PHY101"]


def test_the_session_is_still_usable_after_rows_were_refused(db_session, make_csv, another_request_saves_physics):
    result = run_import(db_session, SPECS["courses"], read_sheet("courses.csv", make_csv(THREE_COURSES)))

    assert (result["imported"], result["skipped"]) == (2, 1)
    # The very same session reads, writes and commits afterwards.
    db_session.add(Course(course_code="AFTER", course_name="Added afterwards"))
    db_session.commit()
    assert [course.course_code for course in db_session.query(Course).order_by(Course.course_code)] == ["AFTER", "BIO", "CS101", "PHY101"]


def test_a_row_refused_for_a_reason_other_than_its_code_is_reported_as_refused(client, make_csv, monkeypatch):
    plan_for_courses = import_service._PLANS["courses"]

    def plan_with_a_row_the_database_cannot_take(db, spec):
        plan = plan_for_courses(db, spec)
        make = plan.make
        # Passes every check, but is built without a name, which the database insists on.
        plan.make = lambda fields: make({**fields, "course_name": None} if fields["course_code"] == "PHY101" else fields)
        return plan

    monkeypatch.setitem(import_service._PLANS, "courses", plan_with_a_row_the_database_cannot_take)

    response = upload(client, make_csv(THREE_COURSES))

    assert response.json()["message"] == "2 of 3 rows imported, 1 skipped"
    assert problems(response) == [(3, "", "", "The database refused this row")]
    assert response.json()["data"]["skipped_rows"] == [{"row": 3, "values": {"course_code": "PHY101", "course_name": "Physics"}}]
    assert [code for code, _name, _status in saved(client)] == ["BIO", "CS101"]


def test_if_the_commit_fails_nothing_is_saved_and_nothing_is_claimed(client, make_csv, monkeypatch):
    commit = Session.commit
    attempts = []

    def commit_that_fails_once(self):
        attempts.append(self)
        if len(attempts) == 1:
            raise OperationalError("COMMIT", {}, sqlite3.OperationalError("disk I/O error"))
        return commit(self)

    monkeypatch.setattr(Session, "commit", commit_that_fails_once)

    failed = upload(client, make_csv(THREE_COURSES))

    assert failed.status_code == 500
    assert failed.json() == {"detail": IMPORT_FAILED}
    # Every row had been written inside the transaction. None of them may outlive its failure.
    assert saved(client) == []

    again = upload(client, make_csv(THREE_COURSES))

    assert again.json()["message"] == "All 3 rows imported"
    assert len(saved(client)) == 3


def test_a_database_failure_is_answered_without_the_database_s_own_words(client, make_csv, monkeypatch):
    def write_that_fails(db, plan, drafts):
        raise OperationalError("INSERT INTO courses (course_code, course_name) VALUES (?, ?)", ("CS101", "Computer Science"), sqlite3.OperationalError("unable to open database file"))

    monkeypatch.setattr(import_service, "_save", write_that_fails)

    response = upload(client, make_csv(THREE_COURSES))

    assert response.status_code == 500
    assert response.json() == {"detail": IMPORT_FAILED}
    for internal in ("INSERT", "sqlite3", "unable to open", "Computer Science", "Traceback", "OperationalError"):
        assert internal not in response.text
    assert saved(client) == []


def test_an_unexpected_failure_is_answered_the_same_way_and_saves_nothing(client, make_csv, monkeypatch):
    def write_that_breaks(db, plan, drafts):
        db.add(plan.make(drafts[0].fields))
        db.flush()
        raise RuntimeError("something nobody planned for, at C:\\secret\\place")

    monkeypatch.setattr(import_service, "_save", write_that_breaks)

    response = upload(client, make_csv(THREE_COURSES))

    assert response.status_code == 500
    assert response.json() == {"detail": IMPORT_FAILED}
    assert "secret" not in response.text and "RuntimeError" not in response.text
    # The one row that had already been written went back with the rest.
    assert saved(client) == []


def test_a_file_that_is_refused_as_a_whole_leaves_the_database_as_it_was(client, make_csv):
    client.post("/courses/create", json={"course_code": "ART", "course_name": "Fine Art"})

    # Three good rows, but no course_name column: nothing of it is imported.
    response = upload(client, make_csv([["course_code", "name"], ["CS101", "Computer Science"], ["PHY101", "Physics"], ["BIO", "Biology"]]))

    assert response.status_code == 400
    assert saved(client) == [("ART", "Fine Art", "active")]


@pytest.mark.parametrize("with_a_refused_row", [False, True], ids=["all rows at once", "row by row after a refusal"])
def test_rows_reach_the_database_together_at_the_commit_not_one_by_one(tmp_path, make_csv, monkeypatch, with_a_refused_row):
    # A file database, so that a second connection can look at what is really saved at each moment.
    path = tmp_path / "import.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()

    def codes_seen_by_another_connection():
        other = sqlite3.connect(path)
        try:
            return [row[0] for row in other.execute("SELECT course_code FROM courses ORDER BY course_code")]
        finally:
            other.close()

    if with_a_refused_row:
        db.add(Course(course_code="PHY101", course_name="Already there"))
        db.commit()
        # The file is checked against a database that does not show the saved course, as if it had
        # been saved a moment later; the write then finds it, and falls back to row by row.
        monkeypatch.setitem(import_service._PLANS, "courses", _plan_that_overlooks("PHY101", import_service._PLANS["courses"]))
    before = codes_seen_by_another_connection()
    seen_after_writing = []
    write = import_service._save

    def write_then_look(session, plan, drafts):
        refused = write(session, plan, drafts)
        seen_after_writing.append(codes_seen_by_another_connection())
        return refused

    monkeypatch.setattr(import_service, "_save", write_then_look)

    try:
        result = run_import(db, SPECS["courses"], read_sheet("courses.csv", make_csv(THREE_COURSES)))
    finally:
        db.close()

    # Written, but not yet committed: nobody else sees a single new row.
    assert seen_after_writing == [before]
    expected = ["BIO", "CS101", "PHY101"]
    assert codes_seen_by_another_connection() == expected
    assert result["imported"] == (2 if with_a_refused_row else 3)
    engine.dispose()


def test_a_database_in_trouble_ends_the_import_instead_of_being_tried_row_by_row(db_session, make_csv, monkeypatch):
    # A refused row is tried again on its own. A database that cannot be written to at all is not
    # a matter of rows: two thousand more attempts would each fail the same way.
    plan_for_courses = import_service._PLANS["courses"]
    built = []

    def plan_on_a_failing_database(db, spec):
        plan = plan_for_courses(db, spec)

        def make(fields):
            built.append(fields["course_code"])
            raise OperationalError("INSERT INTO courses ...", {}, sqlite3.OperationalError("database is locked"))

        plan.make = make
        return plan

    monkeypatch.setitem(import_service._PLANS, "courses", plan_on_a_failing_database)

    with pytest.raises(OperationalError):
        run_import(db_session, SPECS["courses"], read_sheet("courses.csv", make_csv(THREE_COURSES)))

    assert built == ["CS101"]
    db_session.rollback()
    assert db_session.query(Course).count() == 0


def test_an_import_waits_its_turn_and_gives_up_cleanly_when_the_database_stays_locked(tmp_path, make_csv):
    path = tmp_path / "busy.db"
    # timeout: how long this connection waits for the lock before giving up (0.3 s, to keep the test short).
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.3})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    sheet = read_sheet("courses.csv", make_csv(THREE_COURSES))
    # Another connection is in the middle of writing, as a scanner marking attendance would be.
    writer = sqlite3.connect(path, isolation_level=None)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO courses (course_code, course_name, status) VALUES ('ART', 'Fine Art', 'active')")

    try:
        with pytest.raises(OperationalError, match="database is locked"):
            run_import(db, SPECS["courses"], sheet)
        db.rollback()
        writer.execute("COMMIT")

        # Nothing of the file was saved, and the same session imports it once the other writer is done.
        assert [course.course_code for course in db.query(Course).order_by(Course.course_code)] == ["ART"]
        db.rollback()
        result = run_import(db, SPECS["courses"], sheet)
        assert result["imported"] == 3
        assert [course.course_code for course in db.query(Course).order_by(Course.course_code)] == ["ART", "BIO", "CS101", "PHY101"]
    finally:
        writer.close()
        db.close()
        engine.dispose()


def _plan_that_overlooks(code, plan_for_courses):
    def plan_for(db, spec):
        plan = plan_for_courses(db, spec)
        check = plan.check

        def check_without_seeing_it(values, cells):
            checked = check(values, cells)
            if values["course_code"] == code:
                checked.exists = ""
            return checked

        plan.check = check_without_seeing_it
        return plan

    return plan_for
