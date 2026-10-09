import pytest

from app.config import settings
from app.services import tracking_service
from app.services.tracking_service import assign_tracks, observe, track_score

CAMERA = (7, "phone-1")
LEFT = [100, 100, 80, 100]
RIGHT = [400, 100, 80, 100]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(settings, "face_confirm_frames", 3)
    monkeypatch.setattr(settings, "face_confirm_score", 0.70)
    tracking_service.reset()
    yield
    tracking_service.reset()


def track_at(box, now, camera=CAMERA):
    return assign_tracks(camera, [box], now)[0]


def looks(person_id, times, score=1.0, live=True, box=LEFT):
    return [observe(CAMERA, track_at(box, now), person_id, score, live, now) for now in times]


def test_a_person_needs_several_separate_observations():
    assert looks(1, [0.0, 1.0, 2.0]) == [False, False, True]


def test_frames_of_the_same_instant_count_once():
    assert looks(1, [0.0, 0.1, 0.2, 0.3, 1.0, 2.0]) == [False, False, False, False, False, True]


def test_the_same_instant_keeps_its_weakest_score():
    track = track_at(LEFT, 0.0)
    observe(CAMERA, track, 1, 0.90, True, 0.0)
    observe(CAMERA, track, 1, 0.65, True, 0.1)
    observe(CAMERA, track, 1, 0.95, True, 0.2)

    assert track["hits"] == [(0.0, 0.65)]


def test_the_average_score_must_be_strong():
    # Three borderline frames are not enough; two strong ones lift the average of the latest three.
    verdicts = [observe(CAMERA, track_at(LEFT, now), 1, score, True, now) for now, score in enumerate((0.62, 0.63, 0.61, 0.80, 0.80))]

    assert verdicts == [False, False, False, False, True]
    assert round(track_score(track_at(LEFT, 4.5)), 2) == 0.74


def test_a_spoof_frame_starts_the_count_again_and_pauses_it():
    # Two live frames, a spoof frame, a frame inside the pause, then three clean live frames.
    verdicts = [observe(CAMERA, track_at(LEFT, now), 1, 1.0, live, now) for now, live in zip((0.0, 1.0, 2.0, 3.0, 6.0, 7.0, 8.0), (True, True, False, True, True, True, True))]

    assert verdicts == [False, False, False, False, False, False, True]


def test_moving_a_photo_to_get_a_new_track_does_not_lift_the_pause():
    observe(CAMERA, track_at(LEFT, 0.0), 1, 1.0, False, 0.0)

    elsewhere = track_at(RIGHT, 1.0)
    observe(CAMERA, elsewhere, 1, 1.0, True, 1.0)

    assert elsewhere["hits"] == []


def test_old_observations_are_forgotten(monkeypatch):
    monkeypatch.setattr(settings, "face_confirm_frames", 2)
    monkeypatch.setattr(tracking_service, "TRACK_LOST_SECONDS", 100)

    assert looks(1, [0.0, 60.0, 61.0]) == [False, False, True]


def test_another_name_on_the_same_face_starts_the_count_again():
    track = track_at(LEFT, 0.0)
    observe(CAMERA, track, 1, 1.0, True, 0.0)
    observe(CAMERA, track, 1, 1.0, True, 1.0)

    assert observe(CAMERA, track, 2, 1.0, True, 2.0) is False
    assert track["person_id"] == 2 and len(track["hits"]) == 1
    # Going back to the first name does not bring its earlier observations back.
    assert observe(CAMERA, track, 1, 1.0, True, 3.0) is False and len(track["hits"]) == 1


def test_an_unnamed_look_ends_the_run():
    track = track_at(LEFT, 0.0)
    observe(CAMERA, track, 1, 1.0, True, 0.0)
    observe(CAMERA, track, 1, 1.0, True, 1.0)
    observe(CAMERA, track, None, now=2.0)

    assert observe(CAMERA, track, 1, 1.0, True, 3.0) is False
    assert len(track["hits"]) == 1


def test_two_faces_are_counted_separately():
    # The same person "seen" on two different faces: neither face has enough on its own.
    for now, box in ((0.0, LEFT), (1.0, RIGHT), (2.0, LEFT), (3.0, RIGHT)):
        assert observe(CAMERA, track_at(box, now), 1, 1.0, True, now) is False


def test_faces_keep_their_tracks_as_they_move():
    first = assign_tracks(CAMERA, [LEFT, RIGHT], 0.0)
    ids = [track["id"] for track in first]

    # Both drift a little, and the detector lists them in the other order.
    second = assign_tracks(CAMERA, [[410, 105, 82, 102], [110, 98, 78, 98]], 0.3)

    assert [track["id"] for track in second] == ids[::-1]
    assert len(set(ids)) == 2


def test_ten_faces_get_ten_tracks_that_stay_put():
    boxes = [[60 + 120 * (index % 5), 60 + 200 * (index // 5), 80, 100] for index in range(10)]
    first = [track["id"] for track in assign_tracks(CAMERA, boxes, 0.0)]
    second = [track["id"] for track in assign_tracks(CAMERA, [[x + 6, y - 4, w, h] for x, y, w, h in boxes], 0.4)]

    assert len(set(first)) == 10 and first == second


def test_a_short_dropout_keeps_the_track_and_a_long_one_ends_it():
    first = track_at(LEFT, 0.0)
    observe(CAMERA, first, 1, 1.0, True, 0.0)
    assign_tracks(CAMERA, [], 0.5)

    back = track_at(LEFT, 1.0)
    assert back["id"] == first["id"] and len(back["hits"]) == 1

    assign_tracks(CAMERA, [], 2.0)
    later = track_at(LEFT, 1.0 + tracking_service.TRACK_LOST_SECONDS + 0.5)
    assert later["id"] != first["id"] and later["hits"] == []


def test_a_face_that_jumps_across_the_frame_is_a_new_track():
    first = track_at(LEFT, 0.0)

    assert track_at(RIGHT, 0.3)["id"] != first["id"]


def test_a_face_of_a_very_different_size_is_a_new_track():
    first = track_at(LEFT, 0.0)

    assert track_at([80, 80, 200, 250], 0.3)["id"] != first["id"]


def test_people_who_swap_places_do_not_inherit_each_others_count():
    # Arun (1) on the left and Bala (2) on the right, two observations each.
    for now in (0.0, 1.0):
        left, right = assign_tracks(CAMERA, [LEFT, RIGHT], now)
        observe(CAMERA, left, 1, 1.0, True, now)
        observe(CAMERA, right, 2, 1.0, True, now)
    # Between two frames they change places: each track now carries the other person's face.
    left, right = assign_tracks(CAMERA, [LEFT, RIGHT], 2.0)

    assert observe(CAMERA, left, 2, 1.0, True, 2.0) is False
    assert observe(CAMERA, right, 1, 1.0, True, 2.0) is False
    assert len(left["hits"]) == 1 and len(right["hits"]) == 1


def test_cameras_do_not_share_tracks():
    for now in (0.0, 1.0):
        observe(CAMERA, track_at(LEFT, now), 1, 1.0, True, now)
    other = (7, "phone-2")

    assert observe(other, track_at(LEFT, 2.0, other), 1, 1.0, True, 2.0) is False


def test_idle_cameras_are_forgotten():
    track_at(LEFT, 0.0)
    track_at(LEFT, tracking_service.SCANNER_IDLE_SECONDS + 5, (8, "phone-9"))

    assert list(tracking_service.scanners) == [(8, "phone-9")]
