"""The scanner, end to end, with the camera and the models replaced by known faces.

These tests prove the decision logic: who gets marked, who does not, and that faces in one frame do
not affect each other. They say nothing about how well the real models tell real people apart; that
is measured by scripts/evaluate_recognition.py and by testing with a camera.
"""
import asyncio
import base64
import json

import cv2
import numpy as np
import pytest

from app.config import settings
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.person import Person
from app.routes import face_routes
from app.utils.time_utils import today_local

rng = np.random.default_rng(11)
FRAME = rng.integers(40, 216, size=(720, 1280, 3), dtype=np.uint8)
# Ten places in the frame, two rows of five: [x, y, w, h].
SEATS = [[60 + 240 * (index % 5), 80 + 320 * (index // 5), 110, 140] for index in range(10)]
NAMES = ["Arun", "Bala", "Chitra", "Deepa", "Elan", "Farid", "Gita", "Hari", "Indu", "Jaya"]
VECTORS = {name: rng.normal(size=512) for name in NAMES + ["Stranger", "Other stranger"]}


def encode(image):
    return base64.b64encode(cv2.imencode(".png", image)[1].tobytes()).decode()


FRAME_BASE64 = encode(FRAME)


class FakeRequest:
    headers = {}

    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def near(vector, cosine, seed=1):
    vector = np.asarray(vector, dtype=float) / np.linalg.norm(vector)
    noise = np.random.default_rng(seed).normal(size=vector.size)
    noise -= (noise @ vector) * vector
    return cosine * vector + np.sqrt(1 - cosine ** 2) * noise / np.linalg.norm(noise)


def face(seat, who):
    vector = VECTORS[who] if isinstance(who, str) else who
    return {"box": list(SEATS[seat]) if isinstance(seat, int) else list(seat), "embedding": list(vector), "detection_confidence": 0.9, "turn": 0.0}


@pytest.fixture()
def camera(monkeypatch, clock):
    # Stands in for the detector and the liveness model. "photos" holds the x positions of the
    # faces that are a photo or a screen.
    # These tests are about identity, tracking and records, so the head-turn challenge is switched
    # off here. It has its own tests in test_challenge_flow.py.
    clock.step = 0
    seen = {"faces": [], "photos": set(), "clock": clock}
    monkeypatch.setattr(settings, "face_challenge", "off")
    monkeypatch.setattr(face_routes, "detect_faces", lambda image: seen["faces"])
    monkeypatch.setattr(face_routes, "judge_liveness", lambda image, boxes: [("spoof", 0.05) if box[0] in seen["photos"] else ("live", 0.98) for box in boxes])
    return seen


def batch_of(db, names, code="CS101"):
    course = Course(course_code=code, course_name=f"Course {code}")
    db.add(course)
    db.commit()
    batch = CourseBatch(course_id=course.id, batch_name=f"Batch {code}")
    db.add(batch)
    db.commit()
    people = {}
    for name in names:
        person = Person(person_code=f"{code}-{name}", full_name=name, person_type="student", course_id=course.id, batch_id=batch.id, face_enrollment_status="completed")
        db.add(person)
        db.commit()
        for pose in face_routes.REQUIRED_STEPS:
            db.add(FaceEmbedding(person_id=person.id, embedding_vector=json.dumps(list(VECTORS[name])), pose_type=pose, model_name=face_routes.model_label(), is_active=True))
        people[name] = person
    session = AttendanceSession(session_name=f"Class {code}", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
    db.add(session)
    db.commit()
    return session, people


def scan(db, camera, session, faces=None, scanner="cam-1", image=FRAME_BASE64, gap=1.0):
    if faces is not None:
        camera["faces"] = faces
    camera["clock"].advance(gap)
    body = {"session_id": session.id if session is not None else None, "image_base64": image, "scanner_id": scanner, "device_name": "test"}
    return asyncio.run(face_routes.recognize(FakeRequest(body), db))


def records(db):
    return db.query(AttendanceRecord).order_by(AttendanceRecord.id).all()


def marked(db):
    return sorted(record.person_name for record in records(db))


def results(answer):
    return [item["result"] for item in answer["faces"]]


@pytest.mark.parametrize("count", [1, 2, 5, 10])
def test_every_student_in_view_is_marked_once(db_session, camera, count):
    session, people = batch_of(db_session, NAMES)
    faces = [face(seat, NAMES[seat]) for seat in range(count)]

    answers = [scan(db_session, camera, session, faces) for _ in range(5)]

    assert results(answers[0]) == ["pending"] * count and marked(db_session) == sorted(NAMES[:count])
    assert results(answers[2]) == ["verified"] * count
    assert results(answers[4]) == ["already_marked"] * count
    assert len(records(db_session)) == count
    for seat in range(count):
        # Each box keeps its own track and its own name through every frame.
        assert len({answer["faces"][seat]["track_id"] for answer in answers}) == 1
        assert {answer["faces"][seat]["person_name"] for answer in answers} == {NAMES[seat]}
        assert answers[2]["faces"][seat]["record"]["person_id"] == people[NAMES[seat]].id
    assert all(record.session_id == session.id and record.course_id == session.course_id and record.batch_id == session.batch_id and record.attendance_date == today_local() for record in records(db_session))


def test_one_frame_is_never_enough(db_session, camera):
    session, _ = batch_of(db_session, NAMES[:2])

    answer = scan(db_session, camera, session, [face(0, "Arun")])

    assert answer["faces"][0]["result"] == "pending" and answer["faces"][0]["confirm_hits"] == 1
    assert records(db_session) == []


def test_an_unknown_person_is_not_marked_and_blocks_nobody(db_session, camera):
    session, _ = batch_of(db_session, NAMES[:3])
    faces = [face(0, "Arun"), face(1, "Stranger"), face(2, "Chitra")]

    answers = [scan(db_session, camera, session, faces) for _ in range(4)]

    assert results(answers[2]) == ["verified", "unknown", "verified"]
    assert "person_id" not in answers[2]["faces"][1]
    assert marked(db_session) == ["Arun", "Chitra"]


def test_a_friend_standing_in_is_not_marked_as_the_enrolled_student(db_session, camera):
    # Arun is enrolled and absent. Bala, who is not in this batch, is live in front of the camera.
    session, _ = batch_of(db_session, ["Arun", "Chitra"])

    answers = [scan(db_session, camera, session, [face(0, "Bala")]) for _ in range(10)]

    assert all(results(answer) == ["unknown"] for answer in answers)
    assert records(db_session) == []


def test_a_classmate_is_marked_as_himself_never_as_the_absent_student(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])

    for _ in range(6):
        scan(db_session, camera, session, [face(0, "Bala")])

    assert marked(db_session) == ["Bala"]


def test_a_weak_resemblance_is_never_enough_to_mark(db_session, camera):
    # Someone who looks somewhat like Arun: over the match threshold in every frame, but never
    # strong enough on average. He stays "pending" for as long as he stands there.
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    lookalike = near(VECTORS["Arun"], 0.65)

    answers = [scan(db_session, camera, session, [face(0, lookalike)]) for _ in range(12)]

    assert all(results(answer) == ["pending"] for answer in answers)
    assert records(db_session) == []


def test_a_face_between_two_students_is_ambiguous_and_not_marked(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    between = VECTORS["Arun"] / np.linalg.norm(VECTORS["Arun"]) + VECTORS["Bala"] / np.linalg.norm(VECTORS["Bala"])

    answers = [scan(db_session, camera, session, [face(0, between)]) for _ in range(6)]

    assert all(results(answer) == ["ambiguous"] for answer in answers)
    assert answers[0]["faces"][0]["message"] == "Unable to verify identity."
    assert "person_id" not in answers[0]["faces"][0] and records(db_session) == []


def test_a_photo_is_refused_while_the_real_student_beside_it_is_marked(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    camera["photos"] = {SEATS[0][0]}
    faces = [face(0, "Arun"), face(1, "Bala")]

    answers = [scan(db_session, camera, session, faces) for _ in range(6)]

    assert all(answer["faces"][0]["result"] == "liveness_failed" and answer["faces"][0]["status"] == "spoof" for answer in answers)
    assert marked(db_session) == ["Bala"]


def test_a_photo_frame_wipes_what_was_collected(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session)
    camera["photos"] = {SEATS[0][0]}
    scan(db_session, camera, session)
    camera["photos"] = set()

    # Inside the pause nothing counts; afterwards three clean observations are needed again.
    answers = [scan(db_session, camera, session, gap=4.0 if index == 0 else 1.0) for index in range(3)]

    assert [answer["faces"][0]["confirm_hits"] for answer in answers[:2]] == [1, 2]
    assert results(answers[2]) == ["verified"] and len(records(db_session)) == 1


def test_a_poor_face_does_not_stop_the_others(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala", "Chitra"])
    x, y, w, h = SEATS[1]
    dark = FRAME.copy()
    dark[y:y + h, x:x + w] = dark[y:y + h, x:x + w] // 6
    faces = [face(0, "Arun"), face(1, "Bala"), face(2, "Chitra"), face([900, 500, 30, 40], "Deepa")]

    answers = [scan(db_session, camera, session, faces, image=encode(dark)) for _ in range(3)]

    assert results(answers[2]) == ["verified", "low_quality", "verified", "low_quality"]
    assert [item["status"] for item in answers[2]["faces"]] == ["matched", "low_light", "matched", "too_far"]
    assert marked(db_session) == ["Arun", "Chitra"]


def test_a_blurred_moment_neither_counts_nor_restarts_the_count(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    x, y, w, h = SEATS[0]
    blurred = FRAME.copy()
    # A face smeared by movement: light and dark areas are still there, the detail is gone.
    blurred[y:y + h, x:x + w] = np.linspace(80, 170, w, dtype=np.uint8)[None, :, None]
    faces = [face(0, "Arun")]

    scan(db_session, camera, session, faces)
    scan(db_session, camera, session, faces)
    moving = scan(db_session, camera, session, faces, image=encode(blurred))
    assert moving["faces"][0]["status"] == "blurry" and records(db_session) == []

    after = scan(db_session, camera, session, faces)
    assert results(after) == ["verified"] and len(records(db_session)) == 1


def test_the_count_does_not_follow_a_name_to_another_face(db_session, camera):
    # Arun is seen twice at one place, then "Arun" shows up at a different place in the frame.
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session, [face(0, "Arun")])

    answer = scan(db_session, camera, session, [face(9, "Arun")])

    assert answer["faces"][0]["result"] == "pending" and answer["faces"][0]["confirm_hits"] == 1
    assert records(db_session) == []


def test_a_new_person_stepping_into_the_same_spot_starts_from_zero(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session, [face(0, "Arun")])

    answers = [scan(db_session, camera, session, [face(0, "Bala")]) for _ in range(3)]

    assert [answer["faces"][0]["confirm_hits"] for answer in answers[:2]] == [1, 2]
    assert marked(db_session) == ["Bala"]


def test_students_who_cross_paths_are_not_mixed_up(db_session, camera):
    session, people = batch_of(db_session, ["Arun", "Bala"])
    scan(db_session, camera, session, [face(0, "Arun"), face(1, "Bala")])
    scan(db_session, camera, session, [face(0, "Arun"), face(1, "Bala")])

    # They change places between two frames. Nobody is marked on the strength of the other's track.
    swapped = scan(db_session, camera, session, [face(0, "Bala"), face(1, "Arun")])
    assert results(swapped) == ["pending", "pending"] and records(db_session) == []

    scan(db_session, camera, session)
    final = scan(db_session, camera, session)
    assert [item["person_id"] for item in final["faces"]] == [people["Bala"].id, people["Arun"].id]
    assert results(final) == ["verified", "verified"] and marked(db_session) == ["Arun", "Bala"]


def test_evidence_goes_stale_when_the_face_leaves(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session, [], gap=3.0)

    answer = scan(db_session, camera, session, [face(0, "Arun")], gap=3.0)

    assert answer["faces"][0]["confirm_hits"] == 1 and records(db_session) == []


def test_two_faces_that_both_look_like_one_student_never_make_two_records(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])

    # Equally strong: neither can be trusted to be Arun.
    tie = [scan(db_session, camera, session, [face(0, "Arun"), face(1, "Arun")]) for _ in range(4)]
    assert all(results(answer) == ["ambiguous", "ambiguous"] for answer in tie) and records(db_session) == []

    # One clearly stronger: that face is Arun, the other is not named, and there is one record.
    clear = [scan(db_session, camera, session, [face(5, "Arun"), face(6, near(VECTORS["Arun"], 0.75))]) for _ in range(4)]
    assert results(clear[2]) == ["verified", "ambiguous"] and marked(db_session) == ["Arun"]


def test_a_marked_student_is_not_marked_again(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [face(0, "Arun")]) for _ in range(8)]

    assert sum(1 for answer in answers if answer["faces"][0].get("newly_marked")) == 1
    assert results(answers[-1]) == ["already_marked"] and answers[-1]["faces"][0]["attendance_status"] == records(db_session)[0].status
    assert len(records(db_session)) == 1


def test_two_scanners_on_one_session_make_one_record(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    faces = [face(0, "Arun")]

    first = [scan(db_session, camera, session, faces, scanner=name, gap=0.6)["faces"][0] for _ in range(3) for name in ("door", "desk")]
    # Even with the scanner's memory of who is marked wiped, the write itself refuses a second record.
    face_routes.marked_today.clear()
    again = [scan(db_session, camera, session, faces, scanner="door")["faces"][0] for _ in range(4)]

    assert [item["result"] for item in first] == ["pending", "pending", "pending", "pending", "verified", "already_marked"]
    assert all(item["result"] == "already_marked" for item in again) and len(records(db_session)) == 1


def test_one_scanner_cannot_finish_what_another_started(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [face(0, "Arun")], scanner="door")
    scan(db_session, camera, session, scanner="door")

    answer = scan(db_session, camera, session, scanner="desk")

    assert answer["faces"][0]["confirm_hits"] == 1 and records(db_session) == []


def test_a_stopped_session_is_not_marked(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [face(0, "Arun")])
    scan(db_session, camera, session)
    session.status = "completed"
    db_session.commit()

    # Within the few seconds the scanner still believes the session is running.
    answer = scan(db_session, camera, session)

    assert answer["faces"][0]["result"] == "not_marked" and "stopped" in answer["faces"][0]["message"]
    assert records(db_session) == []


def test_only_the_sessions_own_batch_is_matched(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"], "CS101")
    other_session, _ = batch_of(db_session, ["Chitra"], "EE201")

    for _ in range(4):
        scan(db_session, camera, session, [face(0, "Arun"), face(1, "Chitra")])
    for _ in range(4):
        scan(db_session, camera, other_session, [face(0, "Arun"), face(1, "Chitra")])

    by_session = {(record.session_id, record.person_name) for record in records(db_session)}
    assert by_session == {(session.id, "Arun"), (other_session.id, "Chitra")}


def test_without_a_session_faces_are_named_but_nothing_is_marked(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])
    camera["faces"] = [face(0, "Arun")]
    body = {"course_id": session.course_id, "batch_id": session.batch_id, "image_base64": FRAME_BASE64}

    answers = [asyncio.run(face_routes.recognize(FakeRequest(body), db_session)) for _ in range(5)]

    assert all(results(answer) == ["recognized"] for answer in answers)
    assert answers[0]["person_id"] == people["Arun"].id and records(db_session) == []


def test_a_damaged_stored_vector_is_skipped_not_matched(db_session, camera):
    session, people = batch_of(db_session, ["Arun", "Bala", "Chitra"])
    rows = db_session.query(FaceEmbedding).filter(FaceEmbedding.person_id == people["Arun"].id).all()
    rows[0].embedding_vector = json.dumps([float("nan")] * 512)
    rows[1].embedding_vector = json.dumps([0.5] * 128)
    rows[2].embedding_vector = "not json"
    rows[3].embedding_vector = json.dumps([0.0] * 512)
    for row in db_session.query(FaceEmbedding).filter(FaceEmbedding.person_id == people["Bala"].id):
        row.embedding_vector = json.dumps([])
    db_session.commit()

    for _ in range(3):
        answer = scan(db_session, camera, session, [face(0, "Arun"), face(1, "Bala"), face(2, "Chitra")])

    assert results(answer) == ["verified", "unknown", "verified"]


def test_a_broken_live_vector_is_unknown(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    faces = [face(0, np.full(512, np.nan)), face(1, VECTORS["Arun"][:128]), face(2, np.zeros(512))]

    answer = scan(db_session, camera, session, faces)

    assert results(answer) == ["unknown", "unknown", "unknown"]


def test_an_overloaded_server_says_so_instead_of_queueing(db_session, camera, monkeypatch):
    session, _ = batch_of(db_session, ["Arun"])
    monkeypatch.setattr(face_routes, "scans_in_flight", face_routes.MAX_SCANS_IN_FLIGHT)

    answer = scan(db_session, camera, session, [face(0, "Arun")])

    assert answer["status"] == "busy" and answer["faces"] == [] and answer["recognized"] is False


def test_the_response_keeps_the_fields_existing_clients_read(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [face(0, "Arun")]) for _ in range(3)]
    empty = scan(db_session, camera, session, [])

    top = answers[2]
    assert {"success", "recognized", "status", "message", "frame", "faces", "person_id", "person_code", "person_name", "person_type", "confidence_score"} <= set(top)
    assert top["status"] == "matched" and top["recognized"] is True and top["frame"] == {"width": 1280, "height": 720}
    item = top["faces"][0]
    assert {"box", "recognized", "status", "message", "person_id", "person_name", "confidence_score", "attendance_status", "newly_marked", "record"} <= set(item)
    assert item["box"] == dict(zip("xywh", SEATS[0])) and item["newly_marked"] is True and item["person_id"] == people["Arun"].id
    assert answers[0]["faces"][0]["confirming"] is True and answers[0]["faces"][0]["attendance_status"] is None
    assert empty["status"] == "no_face" and empty["faces"] == []
