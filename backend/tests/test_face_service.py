import json
from types import SimpleNamespace

from app.config import settings
from app.services.face_service import best_match, build_gallery, identify


def _stored(person_id, vector):
    return SimpleNamespace(person_id=person_id, embedding_vector=json.dumps(vector))


def test_best_match_returns_the_closest_person():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0]), _stored(2, [0.0, 1.0, 0.0])])

    match = best_match([0.9, 0.1, 0.0], gallery)

    assert match["embedding"].person_id == 1
    assert match["confidence"] > settings.face_match_threshold


def test_best_match_rejects_a_face_below_the_threshold():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0])])

    assert best_match([0.3, 1.0, 0.0], gallery) is None


def test_best_match_rejects_a_face_that_resembles_two_people():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0]), _stored(2, [0.96, 0.28, 0.0])])

    assert best_match([0.99, 0.14, 0.0], gallery) is None


def test_best_match_ignores_other_photos_of_the_same_person_for_the_margin():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0]), _stored(1, [0.96, 0.28, 0.0])])

    assert best_match([0.99, 0.14, 0.0], gallery)["embedding"].person_id == 1


def test_best_match_handles_an_empty_gallery():
    assert best_match([1.0, 0.0, 0.0], build_gallery([])) is None


def test_gallery_matches_a_person_by_the_average_of_their_vectors(monkeypatch):
    monkeypatch.setattr(settings, "face_gallery", "centroid")
    items, matrix = build_gallery([_stored(1, [2.0, 0.0, 0.0]), _stored(1, [0.0, 1.0, 0.0]), _stored(2, [0.0, 0.0, 5.0])])

    assert [item.person_id for item in items] == [1, 2]
    assert [round(value, 4) for value in matrix[0]] == [0.7071, 0.7071, 0.0]
    assert best_match([1.0, 1.0, 0.0], (items, matrix))["confidence"] > 0.99


def test_gallery_can_keep_every_vector_separate(monkeypatch):
    monkeypatch.setattr(settings, "face_gallery", "individual")
    items, matrix = build_gallery([_stored(1, [2.0, 0.0, 0.0]), _stored(1, [0.0, 1.0, 0.0])])

    assert len(items) == 2 and matrix.shape == (2, 3)


def test_identify_says_why_a_face_is_not_named():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0]), _stored(2, [0.96, 0.28, 0.0])])

    matched = identify([1.0, -0.2, 0.0], gallery)
    ambiguous = identify([0.99, 0.14, 0.0], gallery)
    unknown = identify([0.0, 0.0, 1.0], gallery)

    assert matched["status"] == "matched" and matched["embedding"].person_id == 1
    assert ambiguous["status"] == "ambiguous" and ambiguous["runner_up_id"] in (1, 2)
    assert unknown["status"] == "unknown" and unknown["confidence"] < settings.face_match_threshold
    # The closest person is reported for the log even when nobody is named.
    assert matched["runner_up_id"] == 2 and matched["runner_up_score"] < matched["confidence"]


def test_identify_never_names_the_closest_person_of_a_far_away_face():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0])])

    assert identify([0.55, 0.83, 0.0], gallery)["status"] == "unknown"
    assert best_match([0.55, 0.83, 0.0], gallery) is None


def test_identify_treats_a_broken_vector_as_unknown():
    gallery = build_gallery([_stored(1, [1.0, 0.0, 0.0])])

    for broken in ([float("nan"), 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0], [], [float("inf"), 0.0, 0.0], None, ["a", "b", "c"]):
        assert identify(broken, gallery)["status"] == "unknown"


def test_gallery_leaves_out_damaged_vectors():
    rows = [_stored(1, [1.0, 0.0, 0.0]), _stored(2, [float("nan"), 0.0, 0.0]), _stored(3, [1.0, 0.0]), _stored(4, [0.0, 0.0, 0.0]), _stored(5, [0.0, 1.0, 0.0]), SimpleNamespace(person_id=6, embedding_vector="oops")]

    items, matrix = build_gallery(rows)

    assert [item.person_id for item in items] == [1, 5] and matrix.shape == (2, 3)


def test_centroid_matching_is_not_best_of_many(monkeypatch):
    # Person 1 has one stored photo that happens to look like the stranger. Compared photo by photo
    # the stranger is accepted on the strength of that single photo; against the average he is not.
    stored = [_stored(1, [1.0, 0.0, 0.0]), _stored(1, [0.0, 1.0, 0.0]), _stored(1, [0.0, 0.0, 1.0])]
    stranger = [0.0, 0.8, -0.6]

    monkeypatch.setattr(settings, "face_gallery", "individual")
    assert best_match(stranger, build_gallery(stored)) is not None
    monkeypatch.setattr(settings, "face_gallery", "centroid")
    assert best_match(stranger, build_gallery(stored)) is None
