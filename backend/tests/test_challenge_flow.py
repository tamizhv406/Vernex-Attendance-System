"""Anti-spoofing decisions: passive liveness verdicts and the head-turn challenge, per face.

The camera and the models are replaced by known faces, so these tests prove the rules (what gets a
record and what never does). They do not show how well the liveness model tells a real face from a
print, a screen or a video: that takes a camera and real attacks (scripts/liveness_camera_test.py).
"""
import asyncio

import pytest

from app.config import settings
from app.routes import face_routes
from app.services import face_service, tracking_service
from test_recognition_flow import FRAME_BASE64, SEATS, VECTORS, FakeRequest, batch_of, marked, records, results, scan  # noqa: F401

LEFT, RIGHT = 0.10, -0.10
REAL_PICK_DIRECTION = tracking_service.pick_direction
# Each scan is one second after the last, so two looks in the same pose hold it still long enough
# (CHALLENGE_STEADY_SECONDS) to be the starting pose of the challenge.


def look(seat, who, turn=0.0, squeeze=1.0):
    # One face as the detector reports it. turn: eye shift (positive = the person's own left).
    # squeeze: face box width relative to normal, as a tilted flat picture shows it.
    x, y, w, h = SEATS[seat]
    narrow = int(w * squeeze)
    vector = VECTORS[who] if isinstance(who, str) else who
    return {"box": [x + (w - narrow) // 2, y, narrow, h], "embedding": list(vector), "detection_confidence": 0.9, "turn": turn}


@pytest.fixture()
def camera(monkeypatch, clock):
    # "liveness" maps a seat to what the liveness model says about the face there; live when not listed.
    # Every student is asked to turn LEFT unless a test says otherwise.
    clock.step = 0
    seen = {"faces": [], "liveness": {}, "clock": clock, "directions": iter(())}
    verdicts = {"live": ("live", 0.98), "uncertain": ("uncertain", 0.6), "spoof": ("spoof", 0.05)}

    def seat_of(box):
        return min(range(len(SEATS)), key=lambda index: abs(SEATS[index][0] + SEATS[index][2] / 2 - box[0] - box[2] / 2) + abs(SEATS[index][1] - box[1]))

    def judge(image, boxes):
        return [verdicts[seen["liveness"].get(seat_of(box), "live")] for box in boxes]

    monkeypatch.setattr(settings, "face_challenge", "always")
    monkeypatch.setattr(face_routes, "detect_faces", lambda image: seen["faces"])
    monkeypatch.setattr(face_routes, "judge_liveness", judge)
    monkeypatch.setattr(tracking_service, "pick_direction", lambda: next(seen["directions"], "left"))
    return seen


def one(answer, index=0):
    return answer["faces"][index]


def test_a_face_that_never_turns_is_never_marked(db_session, camera):
    # A printed photo or a still picture on a phone, however real it looks to the liveness model.
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Arun")]) for _ in range(25)]

    assert all(results(answer) == ["challenge"] for answer in answers)
    assert one(answers[3])["challenge"] == {"action": "turn", "direction": "left"} and "LEFT" in one(answers[3])["message"]
    assert records(db_session) == []


def test_identity_then_the_right_turn_marks_the_student(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])

    waiting = [scan(db_session, camera, session, [look(0, "Arun")]) for _ in range(3)]
    answer = scan(db_session, camera, session, [look(0, "Arun", LEFT)])

    assert all(results(item) == ["challenge"] for item in waiting)
    assert results(answer) == ["verified"] and one(answer)["record"]["person_id"] == people["Arun"].id
    assert len(records(db_session)) == 1
    assert results(scan(db_session, camera, session, [look(0, "Arun")])) == ["already_marked"]


def test_the_turn_alone_marks_nobody(db_session, camera):
    # The challenge is answered as soon as the turn is asked for, but identity still needs its
    # separate looks; the turn itself is not one of them.
    session, _ = batch_of(db_session, ["Arun"])
    held = [scan(db_session, camera, session, [look(0, "Arun")]) for _ in range(2)]
    assert [one(answer)["challenge"]["action"] for answer in held] == ["straight", "turn"]

    after_turn = scan(db_session, camera, session, [look(0, "Arun", LEFT)])
    assert results(after_turn) == ["pending"] and one(after_turn)["confirm_hits"] == 2 and records(db_session) == []

    assert results(scan(db_session, camera, session, [look(0, "Arun")])) == ["verified"]


def test_a_stranger_who_answers_the_challenge_is_still_unknown(db_session, camera):
    # Bala is live and does everything asked. He is not Arun, so there is nothing to mark.
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Bala", turn)]) for turn in (0, 0, 0, LEFT, 0, RIGHT, 0, LEFT)]

    assert all(results(answer) == ["unknown"] for answer in answers) and records(db_session) == []


def test_turning_the_wrong_way_fails_and_then_locks(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    outcomes = []
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")], gap=4.0)
        scan(db_session, camera, session, [look(0, "Arun")])
        outcomes.append(one(scan(db_session, camera, session, [look(0, "Arun", RIGHT)]))["result"])
    assert outcomes == ["challenge_failed", "challenge_failed", "locked"] and records(db_session) == []

    # While locked, even the right answer marks nobody, on any camera.
    locked = [scan(db_session, camera, session, [look(0, "Arun", turn)], scanner="desk", gap=4.0) for turn in (0, 0, 0, LEFT)]
    assert all(results(answer) == ["locked"] for answer in locked) and records(db_session) == []

    camera["clock"].advance(tracking_service.CHALLENGE_LOCK_SECONDS)
    for turn in (0, 0, 0):
        scan(db_session, camera, session, [look(0, "Arun", turn)])
    assert results(scan(db_session, camera, session, [look(0, "Arun", LEFT)])) == ["verified"]


def test_a_wrong_answer_wipes_what_was_collected(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])
    scan(db_session, camera, session, [look(0, "Arun", RIGHT)])

    # Straight away the right way: too late, the run is gone and a pause is in force.
    assert results(scan(db_session, camera, session, [look(0, "Arun", LEFT)])) == ["pending"]
    assert records(db_session) == []


def test_a_head_already_turned_is_not_an_answer(db_session, camera):
    # Held still, a turned head is only where the challenge starts from: the answer is a further turn.
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Arun", LEFT)]) for _ in range(6)]

    assert one(answers[0])["challenge"] == {"action": "straight"}
    assert all(one(answer)["challenge"] == {"action": "turn", "direction": "left"} for answer in answers[1:])
    assert records(db_session) == []


def test_a_tilted_flat_picture_is_not_a_head_turn(db_session, camera):
    # Tilting a photo shifts the eyes inside the face box like a turn does, but the box gets narrower.
    # It is never an answer; since a real person who moves while turning does the same, it is a
    # retry, not a wrong answer.
    session, people = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    answer = scan(db_session, camera, session, [look(0, "Arun", LEFT, squeeze=0.75)])

    assert results(answer) == ["challenge_retry"] and records(db_session) == []
    assert entry(session, people["Arun"])["failures"] == 0 and entry(session, people["Arun"])["retries"] == 1


def entry(session, person):
    return tracking_service.challenges[(session.id, person.id)]


def test_the_answer_must_come_from_the_same_tracked_face(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    # "Arun" turning his head at another place in the frame is another track with nothing behind it.
    answer = scan(db_session, camera, session, [look(9, "Arun", LEFT)])

    assert one(answer)["challenge"] == {"action": "straight"} and records(db_session) == []


def test_another_person_cannot_answer_for_the_student(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    # Bala steps into Arun's place and does the turn.
    scan(db_session, camera, session, [look(0, "Bala", LEFT)])
    back = scan(db_session, camera, session, [look(0, "Arun")])

    assert records(db_session) == [] and one(back)["confirm_hits"] == 1


def test_each_face_answers_its_own_challenge(db_session, camera):
    camera["directions"] = iter(["left", "right"])
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    for _ in range(3):
        both = scan(db_session, camera, session, [look(0, "Arun"), look(1, "Bala")])
    assert [item["challenge"]["direction"] for item in both["faces"]] == ["left", "right"]

    # Arun answers. Bala does not move: Arun's answer does nothing for him.
    answer = scan(db_session, camera, session, [look(0, "Arun", LEFT), look(1, "Bala")])
    assert results(answer) == ["verified", "challenge"] and marked(db_session) == ["Arun"]

    # Bala copies Arun's direction, which is not the one he was asked for.
    answer = scan(db_session, camera, session, [look(0, "Arun"), look(1, "Bala", LEFT)])
    assert results(answer) == ["already_marked", "challenge_failed"] and marked(db_session) == ["Arun"]


def test_ten_faces_are_challenged_and_marked_independently(db_session, camera):
    names = ["Arun", "Bala", "Chitra", "Deepa", "Elan", "Farid", "Gita", "Hari", "Indu", "Jaya"]
    camera["directions"] = iter(["left", "right"] * 5)
    session, _ = batch_of(db_session, names)
    for _ in range(3):
        scan(db_session, camera, session, [look(seat, name) for seat, name in enumerate(names)])

    # Everyone turns to their own left. Half of them were asked for right.
    answer = scan(db_session, camera, session, [look(seat, name, LEFT) for seat, name in enumerate(names)])

    assert results(answer) == ["verified", "challenge_failed"] * 5
    assert marked(db_session) == sorted(names[0::2]) and len(records(db_session)) == 5


def test_one_faces_liveness_never_counts_for_another(db_session, camera):
    session, _ = batch_of(db_session, ["Arun", "Bala"])
    camera["liveness"] = {0: "spoof"}

    for turn in (0, 0, 0, LEFT, 0, 0):
        answer = scan(db_session, camera, session, [look(0, "Arun", turn), look(1, "Bala", turn)])

    assert one(answer, 0)["result"] == "liveness_failed" and marked(db_session) == ["Bala"]


def test_an_unsure_liveness_verdict_counts_for_nothing(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    camera["liveness"] = {0: "uncertain"}

    answers = [scan(db_session, camera, session, [look(0, "Arun", turn)]) for turn in (0, 0, 0, LEFT, 0, 0, LEFT, 0)]

    assert all(results(answer) == ["liveness_uncertain"] for answer in answers)
    assert one(answers[-1])["recognized"] is False and one(answers[-1])["confirm_hits"] == 0
    assert records(db_session) == []


def test_an_unsure_frame_cannot_be_the_answer_but_wipes_nothing(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    camera["liveness"] = {0: "uncertain"}
    unsure = scan(db_session, camera, session, [look(0, "Arun", LEFT)])
    assert results(unsure) == ["liveness_uncertain"] and one(unsure)["confirm_hits"] == 3 and records(db_session) == []

    camera["liveness"] = {}
    assert results(scan(db_session, camera, session, [look(0, "Arun", LEFT)])) == ["verified"]


def test_a_photo_verdict_after_the_challenge_wipes_the_challenge_too(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [look(0, "Arun")])
    scan(db_session, camera, session, [look(0, "Arun", LEFT)])
    camera["liveness"] = {0: "spoof"}
    scan(db_session, camera, session, [look(0, "Arun")])
    camera["liveness"] = {}

    answers = [scan(db_session, camera, session, [look(0, "Arun")], gap=4.0 if index == 0 else 1.0) for index in range(4)]

    assert all(results(answer) == ["challenge"] for answer in answers) and records(db_session) == []


def test_an_answer_that_comes_too_late_does_not_count(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [look(0, "Arun")])
    assert one(scan(db_session, camera, session, [look(0, "Arun")]))["challenge"]["action"] == "turn"
    # The face stays in view (the track lives on) but answers only after the time is up.
    for _ in range(tracking_service.CHALLENGE_SECONDS + 1):
        scan(db_session, camera, session, [look(0, "Arun")])

    late = scan(db_session, camera, session, [look(0, "Arun", LEFT)])

    assert one(late)["challenge"] == {"action": "straight"} and records(db_session) == []


def test_a_passed_challenge_does_not_stay_good_forever(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [look(0, "Arun")])
    scan(db_session, camera, session, [look(0, "Arun", LEFT)])
    camera["liveness"] = {0: "uncertain"}
    for _ in range(tracking_service.CHALLENGE_PASS_SECONDS + 1):
        scan(db_session, camera, session, [look(0, "Arun")])
    camera["liveness"] = {}

    answers = [scan(db_session, camera, session, [look(0, "Arun")]) for _ in range(4)]

    assert all(results(answer) == ["challenge"] for answer in answers) and records(db_session) == []


def test_without_eye_points_a_turn_cannot_be_seen_and_nobody_is_marked(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Arun", None)]) for _ in range(8)]

    assert all(results(answer) == ["challenge"] for answer in answers) and records(db_session) == []


def test_the_direction_is_one_per_student_and_session_on_every_camera(db_session, camera, monkeypatch):
    monkeypatch.setattr(tracking_service, "pick_direction", REAL_PICK_DIRECTION)
    session, _ = batch_of(db_session, ["Arun"])

    asked = set()
    for scanner in ("door", "desk", "window"):
        for seat in (0, 9):
            scan(db_session, camera, session, [look(seat, "Arun")], scanner=scanner, gap=3.0)
            asked.add(one(scan(db_session, camera, session, scanner=scanner))["challenge"]["direction"])

    # Moving to another place or another camera never gets a second draw.
    assert len(asked) == 1


def test_directions_are_drawn_at_random():
    assert {tracking_service.pick_direction() for _ in range(200)} == {"left", "right"}


def test_no_session_means_no_challenge_and_no_record(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    camera["faces"] = [look(0, "Arun")]
    body = {"course_id": session.course_id, "batch_id": session.batch_id, "image_base64": FRAME_BASE64}

    answer = asyncio.run(face_routes.recognize(FakeRequest(body), db_session))

    assert results(answer) == ["recognized"] and "challenge" not in one(answer) and records(db_session) == []


@pytest.mark.parametrize("score, verdict", [(0.05, "spoof"), (0.49, "spoof"), (0.50, "uncertain"), (0.69, "uncertain"), (0.70, "live"), (0.99, "live"), (float("nan"), "spoof")])
def test_liveness_scores_become_three_verdicts(monkeypatch, score, verdict):
    monkeypatch.setattr(settings, "face_liveness_threshold", 0.50)
    monkeypatch.setattr(settings, "face_liveness_confident", 0.70)
    monkeypatch.setattr(face_service, "liveness_scores", lambda image, boxes: [score] * len(boxes))

    assert face_service.judge_liveness(None, [(0, 0, 10, 10)])[0][0] == verdict
    assert face_service.check_liveness(None, [(0, 0, 10, 10)]) == [verdict == "live"]


def test_a_liveness_model_that_fails_marks_nobody(db_session, camera, monkeypatch):
    session, _ = batch_of(db_session, ["Arun"])

    def broken(image, boxes):
        raise RuntimeError("Liveness check failed: model missing")

    monkeypatch.setattr(face_routes, "judge_liveness", broken)

    answers = [scan(db_session, camera, session, [look(0, "Arun", turn)]) for turn in (0, 0, 0, LEFT)]

    assert all(answer["success"] is False for answer in answers) and records(db_session) == []


# A student who reads the scanner's screen beside the camera faces the camera at an angle all the
# time. The only real attempt so far (15 October 2026) measured a turn of 0.17 to 0.24 throughout,
# which an absolute "look straight" never accepted, so nobody could be marked.
ANGLED = 0.20


@pytest.mark.parametrize("direction, answer", [("left", ANGLED + 0.10), ("right", ANGLED - 0.12)])
def test_a_student_facing_the_camera_at_an_angle_can_answer(db_session, camera, direction, answer):
    camera["directions"] = iter([direction])
    session, people = batch_of(db_session, ["Arun"])

    held = [scan(db_session, camera, session, [look(0, "Arun", ANGLED)]) for _ in range(3)]
    assert [one(item)["challenge"]["action"] for item in held] == ["straight", "turn", "turn"]
    assert one(held[-1])["confirm_hits"] == 3

    marked_now = scan(db_session, camera, session, [look(0, "Arun", answer)])

    assert results(marked_now) == ["verified"] and one(marked_now)["record"]["person_id"] == people["Arun"].id


def test_turning_back_to_the_camera_is_a_new_start_not_a_wrong_answer(db_session, camera):
    # Asked for LEFT while already turned to the left, the student first faces the camera.
    session, people = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun", ANGLED)])

    back = scan(db_session, camera, session, [look(0, "Arun", 0.0)])
    assert one(back)["result"] == "challenge" and one(back)["challenge"] == {"action": "straight"}

    assert one(scan(db_session, camera, session, [look(0, "Arun", 0.0)]))["challenge"]["action"] == "turn"
    assert results(scan(db_session, camera, session, [look(0, "Arun", LEFT)])) == ["verified"]
    assert tracking_service.challenges[(session.id, people["Arun"].id)]["failures"] == 0


def test_from_an_angle_the_wrong_way_still_fails(db_session, camera):
    # Asked for LEFT from a pose turned to the left; turning past the camera to the right is wrong.
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun", ANGLED)])

    assert results(scan(db_session, camera, session, [look(0, "Arun", RIGHT)])) == ["challenge_failed"]
    assert records(db_session) == []


def test_a_face_turned_far_from_the_camera_is_never_a_start(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Arun", turn)]) for turn in (0.30, 0.31, 0.30, 0.42, 0.30)]

    assert all(one(answer)["challenge"] == {"action": "straight"} for answer in answers) and records(db_session) == []


def test_a_head_still_moving_is_not_a_start(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    answers = [scan(db_session, camera, session, [look(0, "Arun", turn)]) for turn in (-0.12, -0.06, 0.0, 0.06, 0.12)]

    assert all(one(answer)["challenge"] == {"action": "straight"} for answer in answers) and records(db_session) == []


def test_two_looks_closer_together_than_the_hold_are_not_a_start(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    scan(db_session, camera, session, [look(0, "Arun")])

    too_soon = scan(db_session, camera, session, [look(0, "Arun")], gap=tracking_service.CHALLENGE_STEADY_SECONDS / 2)

    assert one(too_soon)["challenge"] == {"action": "straight"}


def test_from_an_angle_a_tilted_flat_picture_still_fails(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun", ANGLED)])

    answer = scan(db_session, camera, session, [look(0, "Arun", ANGLED + 0.10, squeeze=0.75)])

    assert results(answer) == ["challenge_retry"] and records(db_session) == []


# ---- A face box that changes shape while turning (28 October 2026: a genuine person locked so) ----
#
# These prove the rule only: with the detector replaced, a "flat picture" here is a narrower or wider
# box. Whether real prints and screens behave like that in front of a real camera is not shown here.

def attempt(db, camera, session, turn, squeeze, scanner="cam-1"):
    # One whole try: wait out any pause, hold still facing the camera twice, then the movement.
    scan(db, camera, session, [look(0, "Arun")], scanner=scanner, gap=4.0)
    scan(db, camera, session, [look(0, "Arun")], scanner=scanner)
    return one(scan(db, camera, session, [look(0, "Arun", turn, squeeze)], scanner=scanner))["result"]


@pytest.mark.parametrize("squeeze", [0.70, 0.80, 0.88, 1.12, 1.25, 1.40])
@pytest.mark.parametrize("turn", [LEFT, 0.20])
def test_a_box_that_changes_shape_can_never_answer_however_often_it_is_tried(db_session, camera, squeeze, turn):
    session, people = batch_of(db_session, ["Arun"])

    outcomes = [attempt(db_session, camera, session, turn, squeeze) for _ in range(tracking_service.CHALLENGE_MAX_RETRIES)]

    assert outcomes == ["challenge_retry"] * (tracking_service.CHALLENGE_MAX_RETRIES - 1) + ["locked"]
    assert records(db_session) == [] and entry(session, people["Arun"])["failures"] == 0
    # Locked: even the right movement marks nobody now.
    assert attempt(db_session, camera, session, LEFT, 1.0) == "locked" and records(db_session) == []


def test_a_retry_is_not_held_against_a_real_person_who_then_turns_properly(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])

    assert attempt(db_session, camera, session, LEFT, 0.75) == "challenge_retry"
    scan(db_session, camera, session, [look(0, "Arun")], gap=4.0)
    scan(db_session, camera, session, [look(0, "Arun")])
    scan(db_session, camera, session, [look(0, "Arun")])
    answer = scan(db_session, camera, session, [look(0, "Arun", LEFT)])

    assert results(answer) == ["verified"] and one(answer)["record"]["person_id"] == people["Arun"].id
    assert entry(session, people["Arun"])["failures"] == 0


def test_a_retry_wipes_what_was_collected_and_pauses_like_a_wrong_answer(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])
    scan(db_session, camera, session, [look(0, "Arun", LEFT, squeeze=0.75)])

    # Straight away the right way: the run is gone and the pause is in force, as after a wrong answer.
    assert results(scan(db_session, camera, session, [look(0, "Arun", LEFT)])) == ["pending"]
    assert records(db_session) == []


def test_turning_the_wrong_way_is_still_a_strike_whatever_the_box_does(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])

    outcomes = [attempt(db_session, camera, session, RIGHT, squeeze) for squeeze in (0.75, 1.0, 1.25)]

    assert outcomes == ["challenge_failed", "challenge_failed", "locked"] and records(db_session) == []


def test_a_box_that_changes_shape_without_turning_is_not_an_answer_of_any_kind(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    answer = scan(db_session, camera, session, [look(0, "Arun", 0.02, squeeze=0.75)])

    assert one(answer)["challenge"] == {"action": "turn", "direction": "left"} and records(db_session) == []
    assert entry(session, people["Arun"])["failures"] == 0 and entry(session, people["Arun"])["retries"] == 0


@pytest.mark.parametrize("squeeze, passes", [(0.93, True), (1.07, True), (0.88, False), (1.12, False)])
def test_the_box_change_limit_is_where_it_was(db_session, camera, squeeze, passes):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [look(0, "Arun")])

    outcome = one(scan(db_session, camera, session, [look(0, "Arun", LEFT, squeeze)]))["result"]

    assert outcome == ("verified" if passes else "challenge_retry")
    assert len(records(db_session)) == (1 if passes else 0)


def test_a_photo_that_turns_and_changes_shape_is_still_a_photo(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    camera["liveness"] = {0: "spoof"}

    answers = [scan(db_session, camera, session, [look(0, "Arun", turn, squeeze)], gap=gap) for turn, squeeze, gap in ((0, 1, 4), (0, 1, 1), (LEFT, 0.75, 1), (LEFT, 1, 1))]

    assert all(results(answer) == ["liveness_failed"] for answer in answers) and records(db_session) == []


def test_retries_are_counted_across_cameras(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])

    outcomes = [attempt(db_session, camera, session, LEFT, 0.75, scanner=f"cam-{index % 3}") for index in range(tracking_service.CHALLENGE_MAX_RETRIES)]

    assert outcomes[-1] == "locked" and records(db_session) == []


def test_the_challenge_limits_are_unchanged():
    # Change C only stopped counting a changed box as a wrong answer. Everything else stays.
    assert (tracking_service.CHALLENGE_TURN, tracking_service.CHALLENGE_BOX_CHANGE, tracking_service.CHALLENGE_STRAIGHT) == (0.08, 0.10, 0.04)
    assert (tracking_service.CHALLENGE_MAX_FAILURES, tracking_service.CHALLENGE_LOCK_SECONDS, tracking_service.SPOOF_COOLDOWN_SECONDS) == (3, 120, 3)


def test_the_log_says_why_an_answer_did_not_count_in_numbers_only(db_session, camera, monkeypatch):
    lines = []
    monkeypatch.setattr(face_routes, "log_decision", lambda **fields: lines.append(fields))
    session, _ = batch_of(db_session, ["Arun"])

    # A changed box, then (after the pause) a turn the wrong way.
    for turn, squeeze, gap in ((0, 1, 1), (0, 1, 1), (LEFT, 0.75, 1), (0, 1, 4), (0, 1, 1), (RIGHT, 1, 1)):
        scan(db_session, camera, session, [dict(look(0, "Arun", turn, squeeze), eyes=True)], gap=gap)

    notes = [line["challenge_note"] for line in lines if line.get("challenge_note")]
    assert [note["reason"] for note in notes] == ["box_changed", "wrong_direction"]
    assert notes[0]["turned"] == pytest.approx(0.10) and notes[0]["box_change"] == pytest.approx(0.2545, abs=1e-3)
    assert notes[1]["turned"] == pytest.approx(-0.10)
    retry = next(line for line in lines if line["result"] == "challenge_retry")
    assert retry["detection_confidence"] == 0.9 and retry["eyes"] is True
    # Ids, scores, sizes and reasons: no vector, no picture, no name.
    for line in lines:
        assert "embedding" not in line and "image" not in line and "person_name" not in line
        assert all(not isinstance(value, (list, tuple)) or len(value) <= 4 for value in line.values())
