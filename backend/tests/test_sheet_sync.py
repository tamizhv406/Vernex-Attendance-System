"""The Google Sheet copy of each new mark, when GOOGLE_SCRIPT_URL is set.

Until October 2026 the mark waited for the sheet's answer (up to 8 seconds) before it was answered, and
a face scan waited on the server's event loop, so every other request waited with it. The sheet is now
written in the background: the mark is answered at once, and what the sheet said is kept as before
(the record's sync_status and a sheet_sync_logs row). No test here reaches the network.
"""
import threading
import time

import pytest
import requests

from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.person import Person
from app.models.sync_log import SheetSyncLog
from app.services import sheet_service
from app.utils.time_utils import today_local

SHEET = "https://sheet.example.invalid/exec"
SLOW_SECONDS = 2


class Answer:
    ok = True
    text = "ok"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # The real application on a SQLite FILE with the engine's usual pool, as the backend runs: the
    # sheet is written from a thread of its own, on a connection of its own. (The shared in-memory
    # database of conftest has one connection for everybody, which two threads cannot use at once.)
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.main import app
    from conftest import add_account, open_login

    engine = create_engine(f"sqlite:///{tmp_path / 'school.db'}", connect_args={"check_same_thread": False})
    database.Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    test_client = TestClient(app, base_url="https://testserver", headers={"X-Requested-With": "vernex"})
    test_client.db = session_factory
    with session_factory() as db:
        access_token, _refresh_token = open_login(db, add_account(db, "admin@example.com"))
    test_client.headers["Authorization"] = f"Bearer {access_token}"
    yield test_client
    assert sheet_service.wait_until_sent(timeout=10)
    engine.dispose()


@pytest.fixture()
def school(client):
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Comp Sci")
        db.add(course)
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.commit()
        people = [Person(person_code=f"S{n}", full_name=f"Student {n}", person_type="student", course_id=course.id, batch_id=batch.id) for n in (1, 2)]
        session = AttendanceSession(session_name="today", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add_all(people + [session])
        db.commit()
        return {"session": session.id, "people": [person.id for person in people]}


@pytest.fixture()
def sheet(monkeypatch):
    # The sheet is configured; what it answers is up to each test. Every send is counted.
    calls = []
    monkeypatch.setattr(sheet_service.settings, "google_script_url", SHEET)

    def answer_with(behaviour):
        def post(url, json=None, timeout=None):
            calls.append(json["record"]["person_code"])
            return behaviour()
        monkeypatch.setattr(sheet_service.requests, "post", post)

    answer_with.calls = calls
    yield answer_with
    sheet_service.wait_until_sent(timeout=10)


def slow():
    time.sleep(SLOW_SECONDS)
    return Answer()


def unreachable():
    raise requests.ConnectionError("sheet.example.invalid could not be reached")


def mark(client, school, n=0):
    started = time.monotonic()
    answer = client.post("/attendance/mark", json={"session_id": school["session"], "person_id": school["people"][n]})
    return answer, time.monotonic() - started


def stored(client):
    with client.db() as db:
        records = [(r.person_code, r.status, r.sync_status) for r in db.query(AttendanceRecord).order_by(AttendanceRecord.id)]
        logs = [(log.sync_status, log.error_message) for log in db.query(SheetSyncLog).order_by(SheetSyncLog.id)]
    return records, logs


def test_a_slow_sheet_never_holds_up_the_mark(client, school, sheet):
    sheet(slow)

    answer, seconds = mark(client, school)

    assert answer.status_code == 200 and answer.json()["message"] == "Attendance marked"
    assert seconds < 1, f"the mark waited {seconds:.1f} s for the sheet"
    assert sheet_service.wait_until_sent(timeout=10)
    assert stored(client) == ([("S1", "present", "synced")], [("synced", None)])
    assert sheet.calls == ["S1"]


def test_an_unreachable_sheet_is_recorded_and_the_mark_stands(client, school, sheet):
    sheet(unreachable)

    answer, seconds = mark(client, school)

    assert answer.status_code == 200 and answer.json()["message"] == "Attendance marked" and seconds < 1
    assert sheet_service.wait_until_sent(timeout=10)
    # As before: the record waits as "pending" for POST /sheet/sync-pending, the log says why.
    records, logs = stored(client)
    assert records == [("S1", "present", "pending")]
    assert logs == [("failed", "sheet.example.invalid could not be reached")]


def test_a_sheet_that_refuses_is_recorded_as_failed(client, school, sheet):
    class Refused(Answer):
        ok = False
        text = "Script error"

    sheet(Refused)

    mark(client, school)

    assert sheet_service.wait_until_sent(timeout=10)
    assert stored(client) == ([("S1", "present", "failed")], [("failed", None)])


def test_records_waiting_are_sent_again_on_request(client, school, sheet):
    sheet(unreachable)
    mark(client, school)
    assert sheet_service.wait_until_sent(timeout=10)

    sheet(Answer)
    retried = client.post("/sheet/sync-pending")

    assert retried.json()["data"]["count"] == 1
    assert stored(client)[0] == [("S1", "present", "synced")]


def test_already_marked_sends_nothing_again(client, school, sheet):
    sheet(Answer)
    mark(client, school)
    assert sheet_service.wait_until_sent(timeout=10)

    again, _ = mark(client, school)

    assert again.json()["message"] == "Already marked"
    assert sheet_service.wait_until_sent(timeout=10)
    assert sheet.calls == ["S1"]


def test_without_a_sheet_nothing_is_sent_and_the_record_says_so(client, school, monkeypatch):
    monkeypatch.setattr(sheet_service.settings, "google_script_url", "")
    monkeypatch.setattr(sheet_service.requests, "post", lambda *args, **kwargs: pytest.fail("nothing may be sent"))

    answer, _ = mark(client, school)

    assert answer.json()["data"]["sync_status"] == "not_required"
    assert stored(client) == ([("S1", "present", "not_required")], [])


# ---- one record, one send: the worker and POST /sheet/sync-pending never send the same record together

def sending_slowly(started):
    def slow_answer():
        started.set()
        time.sleep(1)
        return Answer()
    return slow_answer


def test_sync_pending_skips_the_record_the_worker_is_sending(client, school, sheet):
    started = threading.Event()
    sheet(sending_slowly(started))
    mark(client, school)
    assert started.wait(5)  # the worker is sending S1 right now

    manual = client.post("/sheet/sync-pending").json()["data"]

    assert sheet_service.wait_until_sent(timeout=10)
    assert sheet.calls == ["S1"]
    assert (manual["count"], manual["skipped"]) == (0, 1)
    assert stored(client) == ([("S1", "present", "synced")], [("synced", None)])


def test_two_sync_pending_requests_at_once_send_each_record_once(client, school, sheet):
    sheet(unreachable)
    mark(client, school, 0)
    mark(client, school, 1)
    assert sheet_service.wait_until_sent(timeout=10)
    assert stored(client)[0] == [("S1", "present", "pending"), ("S2", "present", "pending")]
    sheet.calls.clear()
    sheet(sending_slowly(threading.Event()))

    answers = []
    requests_at_once = [threading.Thread(target=lambda: answers.append(client.post("/sheet/sync-pending").json()["data"])) for _ in range(2)]
    for request in requests_at_once:
        request.start()
    for request in requests_at_once:
        request.join(timeout=20)

    assert sorted(sheet.calls) == ["S1", "S2"]
    assert sum(answer["count"] for answer in answers) == 2
    assert stored(client)[0] == [("S1", "present", "synced"), ("S2", "present", "synced")]


def test_a_record_the_worker_could_not_send_is_still_retried_by_hand(client, school, sheet):
    sheet(unreachable)
    mark(client, school)
    assert sheet_service.wait_until_sent(timeout=10)

    sheet(Answer)
    retried = client.post("/sheet/sync-pending").json()["data"]

    assert (retried["count"], retried["skipped"]) == (1, 0)
    assert stored(client) == ([("S1", "present", "synced")], [("failed", "sheet.example.invalid could not be reached"), ("synced", None)])
