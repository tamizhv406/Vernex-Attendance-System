import asyncio
import base64
import json

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from app.models.face_embedding import FaceEmbedding, FaceEnrollment
from app.models.person import Person
from app.routes import face_routes
from app.services.quality_service import MESSAGES, check_pose, check_quality

# Face boxes in a 640x360 frame: [x, y, w, h].
FRONT_BOX = [240, 72, 160, 216]
CLOSE_BOX = [220, 45, 200, 270]
FAR_BOX = [260, 99, 120, 162]
STEPS = [("front", FRONT_BOX, 0.0), ("left", FRONT_BOX, 0.10), ("right", FRONT_BOX, -0.10), ("close", CLOSE_BOX, 0.0), ("far", FAR_BOX, 0.0)]

rng = np.random.default_rng(7)
IMAGE = rng.integers(40, 216, size=(360, 640, 3), dtype=np.uint8)
IMAGE_BASE64 = base64.b64encode(cv2.imencode(".png", IMAGE)[1].tobytes()).decode()
STUDENT_VECTOR = rng.normal(size=512)
STRANGER_VECTOR = rng.normal(size=512)


class FakeRequest:
    headers = {}

    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def face(box, turn=0.0, vector=STUDENT_VECTOR, confidence=0.9):
    return {"box": box, "embedding": list(vector), "detection_confidence": confidence, "turn": turn}


@pytest.fixture()
def camera(monkeypatch, clock):
    # Stands in for the detector: each test sets the faces the next frame "contains".
    # "live" is what the liveness model says about the face: True, False (a photo) or "uncertain".
    # "embedded" counts the frames that reached the embedding model.
    seen = {"faces": [], "live": True, "clock": clock, "embedded": 0}
    verdicts = {True: ("live", 0.98), False: ("spoof", 0.05), "uncertain": ("uncertain", 0.6)}

    def embed(image, faces):
        seen["embedded"] += 1
        return faces

    monkeypatch.setattr(face_routes, "locate_faces", lambda image: seen["faces"])
    monkeypatch.setattr(face_routes, "embed_faces", embed)
    monkeypatch.setattr(face_routes, "judge_liveness", lambda image, boxes: [verdicts[seen["live"]]] * len(boxes))
    yield seen


@pytest.fixture()
def student(db_session):
    person = Person(person_code="S1", full_name="Alice", person_type="student")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    return person


def send(db, person, step):
    body = {"person_id": person.id, "current_step": step, "image_base64": IMAGE_BASE64}
    return asyncio.run(face_routes.enrollment_frame(FakeRequest(body), db))


def capture(db, camera, person, step, box, turn, vector=STUDENT_VECTOR):
    camera["faces"] = [face(box, turn, vector)]
    answers = [send(db, person, step) for _ in range(face_routes.CANDIDATES_PER_STEP)]
    return answers


def enroll(db, camera, person, steps=STEPS):
    face_routes.start_enrollment(person.id, db)
    return [capture(db, camera, person, *step)[-1] for step in steps]


def active(db, person):
    return db.query(FaceEmbedding).filter(FaceEmbedding.person_id == person.id, FaceEmbedding.is_active == True).all()


def test_a_pose_needs_several_good_frames_in_a_row(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)

    answers = capture(db_session, camera, student, *STEPS[0])

    assert [answer["accepted"] for answer in answers] == [False, False, True]
    assert answers[0]["holding"] and answers[0]["message"] == MESSAGES["hold"]
    assert answers[-1]["next_step"] == "left"


def test_a_bad_frame_restarts_the_run_of_good_frames(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    send(db_session, student, "front")
    send(db_session, student, "front")
    camera["faces"] = []
    assert send(db_session, student, "front")["message"] == MESSAGES["no_face"]

    camera["faces"] = [face(FRONT_BOX)]
    assert send(db_session, student, "front")["accepted"] is False


def test_full_enrollment_saves_five_poses_only_at_the_end(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    for step in STEPS[:4]:
        assert capture(db_session, camera, student, *step)[-1]["accepted"]
    assert db_session.query(FaceEmbedding).count() == 0

    last = capture(db_session, camera, student, *STEPS[4])[-1]

    assert last["completed"] and last["progress_percentage"] == 100
    rows = active(db_session, student)
    assert [row.pose_type for row in rows] == ["front", "left", "right", "close", "far"]
    assert all(len(json.loads(row.embedding_vector)) == 512 for row in rows)
    db_session.refresh(student)
    assert student.face_enrollment_status == "completed"
    assert face_routes.complete_enrollment(student.id, db_session)["success"]


def test_frame_without_a_started_enrollment_is_refused(db_session, camera, student):
    camera["faces"] = [face(FRONT_BOX)]

    with pytest.raises(HTTPException) as error:
        send(db_session, student, "front")

    assert error.value.status_code == 409
    assert db_session.query(FaceEmbedding).count() == 0


@pytest.mark.parametrize("step", ["far", "left", "banana"])
def test_client_cannot_skip_or_invent_steps(db_session, camera, student, step):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FAR_BOX)]

    with pytest.raises(HTTPException) as error:
        send(db_session, student, step)

    assert error.value.status_code == 409
    assert db_session.query(FaceEmbedding).count() == 0


def test_frames_after_completion_are_refused(db_session, camera, student):
    enroll(db_session, camera, student)

    with pytest.raises(HTTPException):
        send(db_session, student, "front")

    assert len(active(db_session, student)) == 5


def test_abandoned_re_enrollment_keeps_the_old_faces(db_session, camera, student):
    enroll(db_session, camera, student)
    old_ids = {row.id for row in active(db_session, student)}

    face_routes.start_enrollment(student.id, db_session)
    capture(db_session, camera, student, *STEPS[0])

    assert {row.id for row in active(db_session, student)} == old_ids
    db_session.refresh(student)
    assert student.face_enrollment_status == "completed"


def test_finished_re_enrollment_replaces_the_old_faces(db_session, camera, student):
    enroll(db_session, camera, student)
    old_ids = {row.id for row in active(db_session, student)}

    enroll(db_session, camera, student)

    new_ids = {row.id for row in active(db_session, student)}
    assert len(new_ids) == 5 and not new_ids & old_ids
    assert db_session.query(FaceEmbedding).filter(FaceEmbedding.is_active == False).count() == 5


def test_another_person_stepping_in_is_refused(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    capture(db_session, camera, student, *STEPS[0])

    answers = capture(db_session, camera, student, "left", FRONT_BOX, 0.10, STRANGER_VECTOR)

    assert all(answer["message"] == MESSAGES["mismatch"] for answer in answers)


def test_vector_of_the_wrong_size_is_never_accepted(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)

    answers = capture(db_session, camera, student, "front", FRONT_BOX, 0.0, STUDENT_VECTOR[:128])

    assert all(answer["quality_status"] == "embedding_failed" for answer in answers)


def test_weak_detection_is_refused(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX, confidence=0.55)]

    assert send(db_session, student, "front")["message"] == MESSAGES["unclear"]


def test_the_front_frame_cannot_be_reused_for_close_or_far(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    for step in STEPS[:3]:
        capture(db_session, camera, student, *step)

    assert capture(db_session, camera, student, "close", FRONT_BOX, 0.0)[-1]["message"] == "Face too far. Move closer."
    capture(db_session, camera, student, *STEPS[3])
    assert capture(db_session, camera, student, "far", FRONT_BOX, 0.0)[-1]["message"] == "Face too close. Move backward."


def test_complete_is_refused_when_nothing_is_stored(db_session, camera, student):
    with pytest.raises(HTTPException) as error:
        face_routes.complete_enrollment(student.id, db_session)

    assert error.value.status_code == 409
    db_session.refresh(student)
    assert student.face_enrollment_status != "completed"
    assert db_session.query(FaceEnrollment).count() == 0


def near(vector, cosine, seed=1):
    # A vector at the given cosine similarity to `vector`: the same face seen a little differently
    # (high cosine) or another person who resembles them (lower).
    vector = np.asarray(vector, dtype=float) / np.linalg.norm(vector)
    noise = np.random.default_rng(seed).normal(size=vector.size)
    noise -= (noise @ vector) * vector
    return cosine * vector + np.sqrt(1 - cosine ** 2) * noise / np.linalg.norm(noise)


def other_student(db, code="S2", name="Bala"):
    person = Person(person_code=code, full_name=name, person_type="student")
    db.add(person)
    db.commit()
    db.refresh(person)
    return person


def test_two_faces_in_view_are_never_captured(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX), face([20, 60, 120, 160], vector=STRANGER_VECTOR)]

    answers = [send(db_session, student, "front") for _ in range(5)]

    assert all(answer["quality_status"] == "multiple" and not answer["accepted"] for answer in answers)
    assert face_routes.pending_enrollments[student.id]["samples"] == []


def test_a_face_outside_the_guide_is_not_captured(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face([400, 72, 160, 216])]

    assert send(db_session, student, "front")["quality_status"] == "not_centered"


def test_a_photo_is_never_captured(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"], camera["live"] = [face(FRONT_BOX)], False

    answers = [send(db_session, student, "front") for _ in range(4)]

    assert all(answer["quality_status"] == "spoof" for answer in answers)


def test_a_face_the_liveness_model_is_unsure_about_is_never_captured(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"], camera["live"] = [face(FRONT_BOX)], "uncertain"

    answers = [send(db_session, student, "front") for _ in range(4)]

    assert all(answer["quality_status"] == "liveness_uncertain" and not answer["accepted"] for answer in answers)
    assert face_routes.pending_enrollments[student.id]["candidates"] == []


def test_one_unsure_frame_restarts_the_run_of_good_frames(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    send(db_session, student, "front")
    send(db_session, student, "front")
    camera["live"] = "uncertain"
    send(db_session, student, "front")
    camera["live"] = True

    assert send(db_session, student, "front")["candidates"] == 1


def test_the_same_picture_sent_twice_is_one_candidate(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    camera["clock"].step = 0.01

    answers = [send(db_session, student, "front") for _ in range(6)]

    assert not any(answer["accepted"] for answer in answers)
    assert answers[-1]["candidates"] == 1


def test_the_best_of_the_candidates_is_kept(db_session, camera, student, monkeypatch):
    scores = iter([0.5, 0.9, 0.6])
    real = face_routes.check_quality
    monkeypatch.setattr(face_routes, "check_quality", lambda *args, **kwargs: dict(real(*args, **kwargs), quality_score=next(scores)))
    face_routes.start_enrollment(student.id, db_session)

    capture(db_session, camera, student, *STEPS[0])

    assert face_routes.pending_enrollments[student.id]["samples"][0]["quality_score"] == 0.9


def test_a_face_that_moves_starts_the_run_again(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    send(db_session, student, "front")
    send(db_session, student, "front")
    camera["faces"] = [face([280, 72, 160, 216])]

    answer = send(db_session, student, "front")

    assert answer["accepted"] is False and answer["candidates"] == 1


def test_front_candidates_must_all_be_the_same_face(db_session, camera, student):
    # The front pose has no earlier capture to be compared with, so its frames are compared with each other.
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    send(db_session, student, "front")
    camera["faces"] = [face(FRONT_BOX, vector=STRANGER_VECTOR)]

    answer = send(db_session, student, "front")

    assert answer["message"] == MESSAGES["inconsistent"]
    assert face_routes.pending_enrollments[student.id]["candidates"] == []


@pytest.mark.parametrize("bad", [np.full(512, np.nan), np.zeros(512), np.append(STUDENT_VECTOR[:511], np.inf), []])
def test_broken_vectors_are_never_accepted(db_session, camera, student, bad):
    face_routes.start_enrollment(student.id, db_session)

    answers = capture(db_session, camera, student, "front", FRONT_BOX, 0.0, bad)

    assert all(answer["quality_status"] == "embedding_failed" for answer in answers)
    assert db_session.query(FaceEmbedding).count() == 0


def test_capture_details_are_stored_with_each_pose(db_session, camera, student):
    enroll(db_session, camera, student)

    rows = active(db_session, student)
    meta = json.loads(rows[1].capture_meta)

    assert all(row.model_name == face_routes.model_label() for row in rows)
    assert meta["pipeline"] == face_routes.model_label() and meta["embedding_size"] == 512
    assert meta["candidates"] == face_routes.CANDIDATES_PER_STEP and meta["frame_size"] == [640, 360]
    assert meta["same_as_front"] == 1.0 and meta["detection_confidence"] == 0.9


def test_a_face_already_enrolled_as_someone_else_is_refused(db_session, camera, student):
    enroll(db_session, camera, student)
    bala = other_student(db_session)
    face_routes.start_enrollment(bala.id, db_session)
    # The same face (Alice's, seen slightly differently) being enrolled under Bala's name.
    for step, box, turn in STEPS[:4]:
        capture(db_session, camera, bala, step, box, turn, near(STUDENT_VECTOR, 0.9))

    with pytest.raises(HTTPException) as error:
        capture(db_session, camera, bala, "far", FAR_BOX, 0.0, near(STUDENT_VECTOR, 0.9))

    assert error.value.status_code == 409 and "already enrolled as Alice" in error.value.detail
    assert active(db_session, bala) == [] and len(active(db_session, student)) == 5
    db_session.refresh(bala)
    assert bala.face_enrollment_status == "not_started"
    assert bala.id not in face_routes.pending_enrollments


def test_a_different_face_is_enrolled_normally_beside_others(db_session, camera, student):
    enroll(db_session, camera, student)
    bala = other_student(db_session)
    face_routes.start_enrollment(bala.id, db_session)

    answers = [capture(db_session, camera, bala, step, box, turn, STRANGER_VECTOR)[-1] for step, box, turn in STEPS]

    assert answers[-1]["completed"] and len(active(db_session, bala)) == 5


def test_a_failed_save_keeps_the_old_faces_and_can_be_retried(db_session, camera, student, monkeypatch):
    enroll(db_session, camera, student)
    old_ids = {row.id for row in active(db_session, student)}
    face_routes.start_enrollment(student.id, db_session)
    for step in STEPS[:4]:
        capture(db_session, camera, student, *step)
    real_commit = db_session.commit

    def broken_commit():
        raise RuntimeError("disk full")

    monkeypatch.setattr(db_session, "commit", broken_commit)
    failed = capture(db_session, camera, student, *STEPS[4])[-1]
    monkeypatch.setattr(db_session, "commit", real_commit)

    assert failed["quality_status"] == "save_failed" and not failed["accepted"]
    assert {row.id for row in active(db_session, student)} == old_ids
    assert len(face_routes.pending_enrollments[student.id]["samples"]) == 4

    retried = capture(db_session, camera, student, *STEPS[4])[-1]

    assert retried["completed"]
    new_ids = {row.id for row in active(db_session, student)}
    assert len(new_ids) == 5 and not new_ids & old_ids


def test_cancel_leaves_a_finished_enrollment_as_it_was(db_session, camera, student):
    enroll(db_session, camera, student)
    old_ids = {row.id for row in active(db_session, student)}
    face_routes.start_enrollment(student.id, db_session)
    capture(db_session, camera, student, *STEPS[0])

    face_routes.cancel_enrollment(student.id, db_session)

    assert {row.id for row in active(db_session, student)} == old_ids
    assert face_routes.enrollment_status(student.id, db_session)["data"]["enrollment_status"] == "completed"
    assert face_routes.complete_enrollment(student.id, db_session)["success"]
    with pytest.raises(HTTPException):
        send(db_session, student, "left")


def test_cancel_of_a_first_enrollment_saves_nothing(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    capture(db_session, camera, student, *STEPS[0])

    face_routes.cancel_enrollment(student.id, db_session)

    db_session.refresh(student)
    assert student.face_enrollment_status == "not_started"
    assert db_session.query(FaceEmbedding).count() == 0 and db_session.query(FaceEnrollment).count() == 0


def test_an_enrollment_left_alone_times_out(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    capture(db_session, camera, student, *STEPS[0])
    camera["clock"].advance(face_routes.ENROLLMENT_IDLE_SECONDS + 1)

    with pytest.raises(HTTPException) as error:
        send(db_session, student, "left")

    assert error.value.status_code == 409 and "timed out" in error.value.detail


def test_a_second_camera_cannot_mix_into_a_capture_being_checked(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    face_routes.pending_enrollments[student.id]["busy"] = True

    answer = send(db_session, student, "front")

    assert answer["quality_status"] == "busy" and face_routes.pending_enrollments[student.id]["candidates"] == []


def test_straight_steps_refuse_a_turned_head():
    quality = {"face_ratio": 0.15, "center_x_ratio": 0.5}

    assert check_pose(None, quality, "front", 0.08) == (False, "Look straight into the camera: turn your head slightly to your right.")
    assert check_pose(None, quality, "close", -0.08) == (False, "Look straight into the camera: turn your head slightly to your left.")
    assert check_pose(None, quality, "front", 0.02) == (True, None)
    assert check_pose(None, quality, "left", 0.30) == (False, "Too far. Turn back a little towards the camera.")


def test_quality_is_measured_on_the_face_not_the_background():
    x, y, w, h = FRONT_BOX
    blurred = IMAGE.copy()
    blurred[y:y + h, x:x + w] = cv2.GaussianBlur(blurred[y:y + h, x:x + w], (31, 31), 0)
    backlit = IMAGE.copy()
    backlit[y:y + h, x:x + w] = backlit[y:y + h, x:x + w] // 4

    assert check_quality(IMAGE, [FRONT_BOX])["ok"]
    assert check_quality(blurred, [FRONT_BOX])["quality_status"] == "blurry"
    assert check_quality(backlit, [FRONT_BOX])["quality_status"] == "low_light"
    assert check_quality(IMAGE, [[0, 72, 160, 216]])["quality_status"] == "cut_off"


# ---- Quick enrollment ----

def quick(db, camera, person, steps):
    face_routes.start_enrollment(person.id, db, "quick")
    return [capture(db, camera, person, *step)[-1] for step in steps]


def test_quick_enrollment_takes_front_left_and_right(db_session, camera, student):
    started = face_routes.start_enrollment(student.id, db_session, "quick")["data"]
    assert (started["mode"], started["steps"], started["total_steps"]) == ("quick", ["front", "left", "right"], 3)

    answers = [capture(db_session, camera, student, *step)[-1] for step in STEPS[:3]]

    assert [answer["progress_percentage"] for answer in answers] == [33, 66, 100]
    assert [answer["next_step"] for answer in answers] == ["left", "right", None] and answers[-1]["completed"]
    rows = active(db_session, student)
    assert [row.pose_type for row in rows] == ["front", "left", "right"]
    meta = json.loads(rows[0].capture_meta)
    assert meta["enrollment_mode"] == "quick" and meta["enrollment_poses"] == ["front", "left", "right"]
    db_session.refresh(student)
    assert student.face_enrollment_status == "completed"
    assert face_routes.complete_enrollment(student.id, db_session)["success"]
    with pytest.raises(HTTPException):
        send(db_session, student, "close")


def test_quick_enrollment_can_be_set_to_one_frontal_capture(db_session, camera, student, monkeypatch):
    monkeypatch.setattr(face_routes.settings, "face_enroll_quick_steps", ["front"])
    face_routes.start_enrollment(student.id, db_session, "quick")
    camera["faces"] = [face(FRONT_BOX)]

    answers = [send(db_session, student, "front") for _ in range(3)]

    assert [answer["accepted"] for answer in answers] == [False, False, True] and answers[-1]["completed"]
    assert [row.pose_type for row in active(db_session, student)] == ["front"]
    assert face_routes.complete_enrollment(student.id, db_session)["success"]


def test_quick_steps_from_the_settings_are_cleaned_up(monkeypatch):
    monkeypatch.setattr(face_routes.settings, "face_enroll_quick_steps", ["right", "banana", "left"])
    assert face_routes.enrollment_steps("quick") == ("quick", ["front", "left", "right"])
    monkeypatch.setattr(face_routes.settings, "face_enroll_quick_steps", [])
    assert face_routes.enrollment_steps("quick") == ("quick", ["front"])
    assert face_routes.enrollment_steps("guided") == ("guided", ["front", "left", "right", "close", "far"])


def test_the_default_kind_of_enrollment_comes_from_the_settings(db_session, camera, student, monkeypatch):
    monkeypatch.setattr(face_routes.settings, "face_enroll_mode", "quick")
    assert face_routes.start_enrollment(student.id, db_session)["data"]["mode"] == "quick"
    monkeypatch.setattr(face_routes.settings, "face_enroll_mode", "guided")
    assert face_routes.start_enrollment(student.id, db_session)["data"]["steps"] == face_routes.REQUIRED_STEPS


def test_an_unknown_kind_of_enrollment_is_refused(db_session, camera, student):
    with pytest.raises(HTTPException) as error:
        face_routes.start_enrollment(student.id, db_session, "instant")

    assert error.value.status_code == 400 and student.id not in face_routes.pending_enrollments


def test_the_number_of_frames_per_pose_is_a_setting(db_session, camera, student, monkeypatch):
    monkeypatch.setattr(face_routes, "CANDIDATES_PER_STEP", 1)
    face_routes.start_enrollment(student.id, db_session, "quick")
    camera["faces"] = [face(FRONT_BOX)]

    answer = send(db_session, student, "front")

    assert answer["accepted"] and answer["next_step"] == "left"


def test_the_embedding_model_only_runs_for_frames_worth_keeping(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session, "quick")
    for faces in ([], [face(FRONT_BOX), face([20, 60, 120, 160])], [face([400, 72, 160, 216])], [face(FRONT_BOX, turn=0.1)], [face(FRONT_BOX, confidence=0.55)], [face([200, 20, 240, 320])]):
        camera["faces"] = faces
        assert not send(db_session, student, "front")["accepted"]
    camera["faces"], camera["live"] = [face(FRONT_BOX)], False
    send(db_session, student, "front")
    camera["live"] = "uncertain"
    send(db_session, student, "front")
    assert camera["embedded"] == 0

    camera["live"] = True
    send(db_session, student, "front")
    assert camera["embedded"] == 1


def test_a_repeated_picture_is_not_sent_to_the_models_again(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session, "quick")
    camera["faces"] = [face(FRONT_BOX)]
    camera["clock"].step = 0.01

    for _ in range(6):
        send(db_session, student, "front")

    assert camera["embedded"] == 1


def test_quick_enrollment_refuses_another_face_in_a_later_pose(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session, "quick")
    capture(db_session, camera, student, *STEPS[0])

    answers = capture(db_session, camera, student, "left", FRONT_BOX, 0.10, STRANGER_VECTOR)

    assert all(answer["message"] == MESSAGES["mismatch"] for answer in answers)
    assert db_session.query(FaceEmbedding).count() == 0


def test_quick_enrollment_refuses_a_face_enrolled_as_someone_else(db_session, camera, student):
    enroll(db_session, camera, student)
    bala = other_student(db_session)
    face_routes.start_enrollment(bala.id, db_session, "quick")
    for step, box, turn in STEPS[:2]:
        capture(db_session, camera, bala, step, box, turn, near(STUDENT_VECTOR, 0.9))

    with pytest.raises(HTTPException) as error:
        capture(db_session, camera, bala, "right", FRONT_BOX, -0.10, near(STUDENT_VECTOR, 0.9))

    assert "already enrolled as Alice" in error.value.detail and active(db_session, bala) == []


def test_a_quick_re_enrollment_replaces_a_five_pose_one_only_when_it_is_finished(db_session, camera, student):
    enroll(db_session, camera, student)
    old_ids = {row.id for row in active(db_session, student)}
    face_routes.start_enrollment(student.id, db_session, "quick")
    capture(db_session, camera, student, *STEPS[0])
    capture(db_session, camera, student, *STEPS[1])
    assert {row.id for row in active(db_session, student)} == old_ids

    capture(db_session, camera, student, *STEPS[2])

    rows = active(db_session, student)
    assert len(rows) == 3 and not {row.id for row in rows} & old_ids
    assert face_routes.enrollment_status(student.id, db_session)["data"]["completed_steps"] == 3


def test_a_cancelled_quick_enrollment_saves_nothing(db_session, camera, student):
    face_routes.start_enrollment(student.id, db_session, "quick")
    capture(db_session, camera, student, *STEPS[0])

    face_routes.cancel_enrollment(student.id, db_session)

    assert db_session.query(FaceEmbedding).count() == 0 and db_session.query(FaceEnrollment).count() == 0


def test_starting_again_within_one_clock_tick_is_still_a_new_start(db_session, student, monkeypatch):
    # Windows' clock can give the same time to two calls a few milliseconds apart; the restart must
    # still change started_at, which is how the audit log sees it.
    from datetime import datetime

    frozen = datetime(2026, 10, 15, 12, 0, 0)

    class Frozen(datetime):
        @classmethod
        def utcnow(cls):
            return frozen

    monkeypatch.setattr(face_routes, "datetime", Frozen)
    face_routes.start_enrollment(student.id, db_session)
    first = face_routes.latest_enrollment(db_session, student.id).started_at
    face_routes.start_enrollment(student.id, db_session)

    assert face_routes.latest_enrollment(db_session, student.id).started_at > first
