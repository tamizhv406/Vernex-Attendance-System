from app.services.face_service import head_turn
from app.services.quality_service import check_pose

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
