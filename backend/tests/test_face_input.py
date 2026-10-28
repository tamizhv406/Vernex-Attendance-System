"""What the face routes do with a frame they cannot use: a clear refusal, never a server error.

Every request here goes through the real application over HTTP (logged in), and none reaches the
face models: each one is refused before that.
"""
import base64

import cv2
import numpy as np
import pytest

from app.config import settings

ROUTES = ["/face/recognize", "/face/enrollment/frame"]


def jpeg(width=64, height=48):
    return cv2.imencode(".jpg", np.full((height, width, 3), 128, np.uint8))[1].tobytes()


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("field, value", [("person_id", "abc"), ("session_id", "1.5"), ("session_id", "-3"), ("batch_id", "99999999999"), ("course_id", "1e3")])
def test_a_field_that_is_not_a_whole_number_is_refused_by_name(client, route, field, value):
    answer = client.post(route, files={"image": ("frame.jpg", jpeg(), "image/jpeg")}, data={field: value})

    assert answer.status_code == 400 and answer.json() == {"detail": f"{field} must be a whole number."}


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("body, kind", [(b"{not json", "application/json"), (b"[1, 2]", "application/json"), (b"\xff\xfe", "application/json")])
def test_a_body_that_is_not_a_json_object_is_refused(client, route, body, kind):
    answer = client.post(route, content=body, headers={"content-type": kind})

    assert answer.status_code == 400 and answer.json()["detail"].startswith("The frame could not be read.")


@pytest.mark.parametrize("image_base64", ["%%%not base64%%%", "aGVsbG8=", "", "data:image/jpeg;base64,AAAA"])
def test_an_image_that_is_not_an_image_is_answered_as_invalid(client, image_base64):
    answer = client.post("/face/recognize", json={"image_base64": image_base64})

    assert answer.status_code == 200 and answer.json()["success"] is False and answer.json()["message"] == "Invalid image"


def test_an_empty_upload_is_answered_as_invalid(client):
    answer = client.post("/face/recognize", files={"image": ("frame.jpg", b"", "image/jpeg")})

    assert answer.status_code == 200 and answer.json()["message"] == "Invalid image"


@pytest.mark.parametrize("route", ROUTES)
def test_a_frame_over_the_size_limit_is_refused_before_it_is_read(client, route):
    too_big = b"\xff\xd8" + b"\x00" * settings.face_max_upload_bytes

    answer = client.post(route, files={"image": ("frame.jpg", too_big, "image/jpeg")})

    assert answer.status_code == 413 and "too large" in answer.json()["detail"]


def test_a_frame_of_unknown_length_is_refused(client):
    def chunks():
        yield b'{"image_base64": "'
        yield base64.b64encode(jpeg())
        yield b'"}'

    answer = client.post("/face/recognize", content=chunks(), headers={"content-type": "application/json"})

    assert answer.status_code == 411


@pytest.mark.parametrize("encoding", [".png", ".jpg"])
def test_a_small_file_that_unpacks_into_too_many_pixels_is_refused(client, encoding):
    # 5000 x 5000 plain pixels: a few hundred kilobytes as a file, 75 MB once unpacked.
    huge = cv2.imencode(encoding, np.zeros((5000, 5000, 3), np.uint8))[1].tobytes()
    assert len(huge) < settings.face_max_upload_bytes

    answer = client.post("/face/recognize", files={"image": ("frame" + encoding, huge, "image/png")})

    assert answer.status_code == 413 and "5000 x 5000" in answer.json()["detail"]


def test_a_frame_within_the_limits_is_read(client):
    # Unknown session aside, the frame itself is accepted and looked at (no face in a grey square).
    import app.routes.face_routes as face_routes

    face_routes.detect_faces, real = (lambda image: []), face_routes.detect_faces
    try:
        answer = client.post("/face/recognize", files={"image": ("frame.jpg", jpeg(960, 540), "image/jpeg")})
    finally:
        face_routes.detect_faces = real

    assert answer.status_code == 200 and answer.json()["status"] == "no_face" and answer.json()["frame"] == {"width": 960, "height": 540}


def test_other_routes_keep_their_own_limits(client):
    # The bulk uploads read files of up to 5 MB themselves; the frame limit is for /face/ only.
    answer = client.post("/courses/upload", files={"file": ("courses.csv", b"course_code,course_name\r\n" + b"X" * (settings.face_max_upload_bytes + 10), "text/csv")})

    assert answer.status_code != 413


# ---- consent before a face is enrolled (task S-10) -----------------------------------------------------

@pytest.fixture()
def student(client):
    with client.db() as db:
        from app.models.person import Person

        person = Person(person_code="CONSENT-1", full_name="Consent Student", person_type="student")
        db.add(person)
        db.commit()
        return person.id


@pytest.mark.parametrize("query", ["", "?consent=false", "?consent=no"])
def test_an_enrollment_does_not_start_without_consent(client, student, query):
    answer = client.post(f"/face/enrollment/start/{student}{query}")

    assert answer.status_code in (400, 422)
    with client.db() as db:
        from app.models.face_embedding import FaceEnrollment

        assert db.query(FaceEnrollment).count() == 0


def test_the_consent_message_fits_staff_and_members_as_well_as_students(client, student):
    answer = client.post(f"/face/enrollment/start/{student}")

    assert answer.status_code == 400
    assert answer.json()["detail"] == "Confirm that the person (or, for a minor, a parent or guardian) agreed to face enrollment."


def test_with_consent_it_starts_and_the_audit_log_says_so(client, student):
    from app.models.audit_log import AuditLog

    answer = client.post(f"/face/enrollment/start/{student}?consent=true")

    assert answer.status_code == 200
    with client.db() as db:
        entry = db.query(AuditLog).filter_by(action="face_enrollment.started").one()
    assert entry.details == {"steps": 5, "consent": True} and entry.target_id == student
