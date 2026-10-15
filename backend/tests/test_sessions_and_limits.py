"""Sessions take the batch's timetable, the scanner shows a status corrected by hand, and no value
that is too long for its column reaches the database (where PostgreSQL would refuse it with a 500).
"""
from datetime import time, timedelta

import pytest
from typing import Annotated

from pydantic import TypeAdapter, ValidationError

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.timing import Timing
from app.routes import face_routes
from app.schemas.attendance_schema import AttendanceMark, AttendanceSessionCreate
from app.schemas.timing_schema import TimingCreate, TimingUpdate
from app.utils.time_utils import today_local
from test_recognition_flow import batch_of, face, results, scan  # noqa: F401
from test_recognition_flow import camera  # noqa: F401  (fixture)


@pytest.fixture()
def classroom(client):
    course = client.post("/courses/create", json={"course_code": "TT1", "course_name": "Timetable"}).json()["data"]
    timing = client.post("/timings/create", json={
        "name": "Morning", "timing_type": "class", "start_time": "09:00:00", "grace_time": "09:05:00",
        "late_after_time": "09:10:00", "end_time": "10:00:00", "auto_absent_after_time": "09:45:00",
    }).json()["data"]
    batch = client.post("/batches/create", json={"course_id": course["id"], "batch_name": "With timetable", "timing_id": timing["id"]}).json()["data"]
    plain = client.post("/batches/create", json={"course_id": course["id"], "batch_name": "Without"}).json()["data"]
    student = client.post("/users/create", json={"person_code": "TT-1", "full_name": "Timed Student", "person_type": "student", "course_id": course["id"], "batch_id": plain["id"]}).json()["data"]
    return {"course": course["id"], "batch": batch["id"], "plain": plain["id"], "timing": timing["id"], "student": student["id"]}


def start(client, classroom, batch="batch", **fields):
    return client.post("/attendance/session/start", json={"session_name": "Class", "session_type": "regular", "course_id": classroom["course"], "batch_id": classroom[batch], **fields})


def test_a_session_takes_late_and_absent_times_from_the_batch_timetable(client, classroom):
    answer = start(client, classroom)

    data = answer.json()["data"]
    assert answer.status_code == 200
    assert (data["timing_id"], data["grace_time"], data["end_time"]) == (classroom["timing"], "09:10:00", "09:45:00")


def test_times_given_for_the_session_win_over_the_timetable(client, classroom):
    data = start(client, classroom, grace_time="09:20:00").json()["data"]

    assert (data["grace_time"], data["end_time"]) == ("09:20:00", "09:45:00")


def test_a_batch_without_a_timetable_has_no_late_time(client, classroom):
    data = start(client, classroom, batch="plain").json()["data"]

    assert (data["timing_id"], data["grace_time"], data["end_time"]) == (None, None, None)


def test_the_session_starts_on_the_school_clock_unless_a_start_is_given(client, classroom):
    assert start(client, classroom).json()["data"]["start_time"] is not None
    assert start(client, classroom, start_time="07:30:00").json()["data"]["start_time"] == "07:30:00"


@pytest.mark.parametrize("fields, status, message", [
    ({"grace_time": "10:00:00", "end_time": "09:00:00"}, 400, "The late-after time must be before the absent-after (end) time."),
    ({"timing_id": 9999}, 404, "Timing not found"),
])
def test_impossible_session_times_are_refused(client, classroom, fields, status, message):
    answer = start(client, classroom, batch="plain", **fields)

    assert (answer.status_code, answer.json()) == (status, {"detail": message})


def test_a_student_marked_after_the_late_time_is_late(client, classroom):
    # Late after one second past midnight, absent only at the very end of the day.
    session = start(client, classroom, batch="plain", grace_time="00:00:01", end_time="23:59:59").json()["data"]

    answer = client.post("/attendance/mark", json={"session_id": session["id"], "person_id": classroom["student"]})

    assert answer.json()["data"]["status"] == "late"


def test_the_scanner_shows_a_status_corrected_by_hand(client, db_session, camera, monkeypatch):
    # The scanner and the route share one database here, so a mark by hand is seen by the scanner.
    from app import database

    session, people = batch_of(db_session, ["Arun"])
    answers = [scan(db_session, camera, session, [face(0, "Arun")]) for _ in range(4)]
    assert results(answers[-1]) == ["already_marked"] and answers[-1]["faces"][0]["attendance_status"] == "present"

    monkeypatch.setattr(database, "SessionLocal", lambda: db_session)
    record = db_session.query(AttendanceRecord).one()
    from app.routes.attendance_routes import correct

    correct(db_session, record, "late")

    after = scan(db_session, camera, session, [face(0, "Arun")])
    assert results(after) == ["already_marked"] and after["faces"][0]["attendance_status"] == "late"


@pytest.mark.parametrize("value", ["not-a-date", "2026-02-30", "x" * 300])
def test_a_date_filter_that_is_not_a_date_is_refused(client, value):
    # PostgreSQL refused such a value with a database error (500); SQLite compared it as text.
    assert client.get("/attendance/by-date", params={"attendance_date": value}).status_code == 422


@pytest.mark.parametrize("route, body", [
    ("/attendance/session/start", {"session_name": "x" * 141, "session_type": "regular", "course_id": 1, "batch_id": 1}),
    ("/attendance/mark", {"session_id": 1, "person_id": 1, "device_name": "x" * 121}),
    ("/attendance/mark", {"session_id": 1, "person_id": 1, "notes": "x" * 1001}),
    ("/timings/create", {"name": "x" * 141, "timing_type": "class"}),
])
def test_a_value_longer_than_its_column_is_refused_before_the_database(client, route, body):
    assert client.post(route, json=body).status_code == 422


@pytest.mark.parametrize("schema, model", [
    (AttendanceSessionCreate, AttendanceSession), (AttendanceMark, AttendanceRecord), (TimingCreate, Timing), (TimingUpdate, Timing),
])
def test_every_text_field_is_limited_to_its_column(schema, model):
    # A field written to a column of limited length must not accept more than the column holds.
    for name, field in schema.model_fields.items():
        column = model.__table__.columns.get(name)
        limit = getattr(getattr(column, "type", None), "length", None)
        if not limit:
            continue
        accepts = TypeAdapter(Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation)
        try:
            accepts.validate_python("x")
        except ValidationError:
            continue  # a fixed list of values (status), not free text
        accepts.validate_python("x" * limit)
        with pytest.raises(ValidationError):
            accepts.validate_python("x" * (limit + 1))
