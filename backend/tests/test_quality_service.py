import cv2
import numpy as np
import pytest

from app.services.face_service import head_turn
from app.services.quality_service import MESSAGES, check_pose, check_quality

CENTERED = {"face_ratio": 0.15, "center_x_ratio": 0.5}


def test_head_turn_is_zero_when_the_eyes_sit_in_the_middle_of_the_box():
    area = {"x": 100, "y": 50, "w": 200, "h": 240, "left_eye": (250, 120), "right_eye": (150, 120)}

    assert head_turn(area) == 0


def test_head_turn_is_positive_when_the_eyes_shift_towards_the_image_right():
    area = {"x": 100, "y": 50, "w": 200, "h": 240, "left_eye": (270, 120), "right_eye": (170, 120)}

    assert head_turn(area) == 0.1


def test_head_turn_is_unknown_without_eye_points():
    assert head_turn({"x": 0, "y": 0, "w": 100, "h": 100, "left_eye": None, "right_eye": None}) is None


def test_left_step_needs_a_real_turn_to_the_left():
    assert check_pose(None, CENTERED, "left", 0.10) == (True, None)
    assert check_pose(None, CENTERED, "left", 0.02) == (False, "Turn your head a little more to your left.")
    assert check_pose(None, CENTERED, "left", -0.10) == (False, "Turn your head the other way.")


def test_right_step_needs_a_real_turn_to_the_right():
    assert check_pose(None, CENTERED, "right", -0.10) == (True, None)
    assert check_pose(None, CENTERED, "right", 0.10) == (False, "Turn your head the other way.")


def test_turn_steps_pass_when_the_detector_gave_no_eye_points():
    assert check_pose(None, CENTERED, "left", None) == (True, None)


# ---- Poor enrollment captures, one reason each ----------------------------------------------------
# A 640x360 frame with fine texture everywhere stands in for a sharp, evenly lit face. These prove which
# reason each kind of poor capture is refused for; they are not pictures of real faces.

FACE_BOX = [240, 72, 160, 216]


def textured(level=120, spread=60, blur=0):
    picture = np.clip(level + np.random.default_rng(3).normal(0, spread, (360, 640, 3)), 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(picture, (0, 0), blur) if blur else picture


@pytest.mark.parametrize("image, boxes, reason", [
    (textured(), [], "no_face"),
    (textured(), [FACE_BOX, [20, 20, 100, 120]], "multiple"),
    (textured(), [[0, 72, 160, 216]], "cut_off"),
    (textured(30, 15), [FACE_BOX], "low_light"),
    (textured(225, 15), [FACE_BOX], "too_bright"),
    (textured(blur=6), [FACE_BOX], "blurry"),
    (textured(), [[300, 150, 40, 50]], "too_far"),
    (textured(), [[60, 5, 520, 350]], "too_close"),
    (textured(), [[40, 72, 160, 216]], "not_centered"),
], ids=["no-face", "two-faces", "cut-off", "dark", "too-bright", "blurred", "too-small", "too-close", "off-centre"])
def test_a_poor_capture_is_refused_for_its_own_reason(image, boxes, reason):
    quality = check_quality(image, boxes)

    assert quality["ok"] is False and quality["quality_status"] == reason and quality["warning"] == MESSAGES[reason]


def test_a_sharp_well_lit_centred_face_is_accepted():
    quality = check_quality(textured(), [FACE_BOX])

    assert quality["ok"] is True and quality["quality_status"] == "good"
