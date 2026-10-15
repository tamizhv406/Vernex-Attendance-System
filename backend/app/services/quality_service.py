import cv2

MESSAGES = {
    "no_face": "No face detected. Please keep your face inside the circle.",
    "multiple": "Multiple faces detected. Only one person is allowed.",
    "cut_off": "Keep your whole face inside the frame.",
    "unclear": "Face not clear. Face the camera in good light.",
    "low_light": "Low light on your face. Face a light source or move to a brighter place.",
    "too_bright": "Too much light on your face. Move away from the direct light.",
    "blurry": "Image is blurry. Keep your face still.",
    "too_far": "Face too far. Move closer.",
    "too_close": "Face too close. Move backward.",
    "not_centered": "Keep your face centered inside the circle.",
    "sunglasses": "Please remove sunglasses.",
    "spoof": "Photo or screen detected. Show your real face to the camera.",
    "liveness_uncertain": "Cannot confirm a real face. Face the camera in even light, without glare.",
    "mismatch": "This face does not match the first capture. Only the student being enrolled should be in view.",
    "hold": "Good. Hold still...",
    "moved": "Hold still. Keep your face in the same place until the pose is captured.",
    "inconsistent": "The face changed during the capture. Only the student being enrolled should be in view.",
    "busy": "Still checking the previous frame.",
    "save_failed": "The enrollment could not be saved. Hold this pose to try again.",
    "ambiguous": "Unable to verify identity.",
    "transparent_specs": "Transparent spectacles detected. You can continue, but removing specs improves enrollment accuracy.",
}


# Eye shift inside the face box (share of its width) that counts as a real head turn, roughly 15 degrees.
MIN_HEAD_TURN = 0.06
# Beyond this the face is close to a profile, which the embedding model handles badly.
MAX_HEAD_TURN = 0.20
# Sharpness is measured on the face scaled to this size, so the score does not depend on how big the face is.
SHARPNESS_SIZE = 160
MIN_SHARPNESS = 50
# Focus is the same edge measure divided by the face's contrast, so a dim but sharp face is not called
# blurred. The limits below come from scripts/evaluate_recognition.py --quality: under 0.004 fewer than
# half of enrolled faces were still recognized, and a reference capture should be clearly better than that.
MIN_FOCUS_SCAN = 0.004
MIN_FOCUS_ENROLL = 0.008
# Mean grey level of the face. Recognition held up between 30 and 210 and fell away outside;
# reference captures keep to the range where it was at its best.
BRIGHTNESS_SCAN = (30, 210)
BRIGHTNESS_ENROLL = (55, 190)
# Share of the frame the face must fill in the front step. Close and far are measured against that capture.
FRONT_FACE_RATIO = (0.10, 0.25)
CLOSE_FACTOR = 1.5
FAR_FACTOR = 0.6
# How far the middle of the face may sit from the middle of the frame (share of width, of height).
# The guide oval on screen is 36% of the width and 78% of the height, so this keeps the face inside it.
CENTER_TOLERANCE = (0.15, 0.20)


def check_quality(image, faces, reject_sunglasses=True):
    # faces: [x, y, w, h] boxes from the YOLO detector (face_service.detect_faces).
    # Light and sharpness are measured on the face itself: a bright, sharp background says nothing
    # about a backlit or blurred face, and the face is what gets stored.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    print("detected face count", len(faces))
    if len(faces) == 0:
        return result(False, "no_face", float(gray.mean()), 0.0, faces)
    if len(faces) > 1:
        return result(False, "multiple", float(gray.mean()), 0.0, faces)
    h, w = gray.shape
    x, y, fw, fh = faces[0]
    crop = gray[max(y, 0): y + fh, max(x, 0): x + fw]
    if crop.size == 0:
        return result(False, "no_face", float(gray.mean()), 0.0, faces)
    brightness, blur, focus = face_measures(crop)
    face_ratio = (fw * fh) / float(w * h)
    cx = x + fw / 2
    cy = y + fh / 2
    if x <= 1 or y <= 1 or x + fw >= w - 1 or y + fh >= h - 1:
        return result(False, "cut_off", brightness, blur, faces)
    if brightness < BRIGHTNESS_ENROLL[0]:
        return result(False, "low_light", brightness, blur, faces)
    if brightness > BRIGHTNESS_ENROLL[1]:
        return result(False, "too_bright", brightness, blur, faces)
    if blur < MIN_SHARPNESS or focus < MIN_FOCUS_ENROLL:
        return result(False, "blurry", brightness, blur, faces)
    if face_ratio < 0.06:
        return result(False, "too_far", brightness, blur, faces)
    if face_ratio > 0.70:
        return result(False, "too_close", brightness, blur, faces)
    if abs(cx - w / 2) > w * CENTER_TOLERANCE[0] or abs(cy - h / 2) > h * CENTER_TOLERANCE[1]:
        return result(False, "not_centered", brightness, blur, faces)
    if reject_sunglasses and has_dark_eye_region(gray, faces[0]):
        return result(False, "sunglasses", brightness, blur, faces)
    return {
        "ok": True,
        "quality_status": "good",
        "warning": None,
        # Mostly focus, partly how close the light is to mid-grey. It keeps rising with sharper
        # frames, so "the best of several candidates" really picks the sharpest one.
        "quality_score": round(0.7 * focus / (focus + 0.02) + 0.3 * (1 - abs(brightness - 125) / 125), 4),
        "brightness_score": brightness,
        "blur_score": blur,
        "focus_score": round(focus, 5),
        "face_box": [int(v) for v in faces[0]],
        "face_ratio": face_ratio,
        "center_x_ratio": cx / w,
    }


def face_measures(gray_face):
    # (brightness, sharpness, focus) of a grey face crop. Enrollment and the scanner both use this.
    face = cv2.resize(gray_face, (SHARPNESS_SIZE, SHARPNESS_SIZE), interpolation=cv2.INTER_AREA)
    blur = float(cv2.Laplacian(face, cv2.CV_64F).var())
    return float(gray_face.mean()), blur, blur / max(float(face.var()), 1e-6)


def scan_problem(gray, box):
    # Why a face seen by the scanner should not be matched at all, or None when it is usable.
    # Looser than enrollment: a class is filmed as it is, but a face this dark, burnt out or
    # smeared mostly produces weak scores that would only drag a real match down.
    x, y, w, h = box
    crop = gray[max(y, 0): y + h, max(x, 0): x + w]
    if crop.size == 0:
        return "unclear"
    brightness, _, focus = face_measures(crop)
    if brightness < BRIGHTNESS_SCAN[0]:
        return "low_light"
    if brightness > BRIGHTNESS_SCAN[1]:
        return "too_bright"
    if focus < MIN_FOCUS_SCAN:
        return "blurry"
    return None


def check_pose(image, quality, step, turn=None, front_ratio=None):
    # turn: face_service.head_turn, positive when the head is turned to the person's own left.
    # front_ratio: face size of this enrollment's front capture; close and far must really differ from it.
    ratio = quality["face_ratio"]
    cx = quality["center_x_ratio"]
    if step == "front" and abs(cx - 0.5) > 0.18:
        return False, "Keep your face centered inside the circle."
    if turn is not None and step in ("front", "close", "far") and abs(turn) >= MIN_HEAD_TURN:
        # Which way to correct, not only that something is wrong: most refused front frames of the
        # first real enrollment (15 October 2026) were a head turned the same way, again and again.
        back = "right" if turn > 0 else "left"
        return False, f"Look straight into the camera: turn your head slightly to your {back}."
    if turn is not None and step in ("left", "right"):
        wanted = turn if step == "left" else -turn
        if wanted <= -MIN_HEAD_TURN:
            return False, "Turn your head the other way."
        if wanted < MIN_HEAD_TURN:
            return False, f"Turn your head a little more to your {step}."
        if wanted > MAX_HEAD_TURN:
            return False, "Too far. Turn back a little towards the camera."
    if step == "front" and ratio < FRONT_FACE_RATIO[0]:
        return False, "Face too far. Move closer."
    if step == "front" and ratio > FRONT_FACE_RATIO[1]:
        return False, "Face too close. Move backward."
    if step == "close" and ratio < max(0.22, CLOSE_FACTOR * (front_ratio or 0)):
        return False, "Face too far. Move closer."
    if step == "far" and ratio > (FAR_FACTOR * front_ratio if front_ratio else 0.24):
        return False, "Face too close. Move backward."
    return True, None


def has_dark_eye_region(gray, face):
    x, y, fw, fh = face
    eye_roi = gray[y + int(fh * 0.20): y + int(fh * 0.48), x + int(fw * 0.15): x + int(fw * 0.85)]
    return eye_roi.size > 0 and float(eye_roi.mean()) < 35


def result(ok, code, brightness, blur, faces):
    return {
        "ok": ok,
        "quality_status": code,
        "warning": MESSAGES[code],
        "quality_score": 0.0,
        "brightness_score": brightness,
        "blur_score": blur,
        "face_box": [int(v) for v in faces[0]] if len(faces) else None,
        "face_ratio": 0.0,
        "center_x_ratio": 0.0,
    }
