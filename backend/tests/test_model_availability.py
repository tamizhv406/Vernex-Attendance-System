"""Face models that cannot be loaded are a server problem, never a face problem.

From 11:00 to 15:53 on 28 October 2026 a server without its face models answered all 1,223
enrollment frames "Could not read the face", so the person kept trying to fix a capture that was
never the problem. Now such a frame is answered 503 models_unavailable, by the enrollment and the
scanner alike, and nothing is stored or marked.
"""
import json
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models.face_embedding import FaceEmbedding
from app.routes import face_routes
from app.services import face_service
from app.services.face_service import ModelsUnavailable
from app.services.quality_service import MESSAGES
from test_enrollment_flow import FRONT_BOX, camera, face, send, student  # noqa: F401  (fixtures)
from test_recognition_flow import batch_of, records, scan

MISSING = ModelsUnavailable("DeepFace failed to import: No module named 'tensorflow'")


def body(answer):
    return json.loads(answer.body)


def broken(*_args):
    raise MISSING


# ---- where the outage is noticed --------------------------------------------------------------

def test_deepface_that_cannot_be_imported_is_models_unavailable(monkeypatch):
    monkeypatch.setattr(face_service, "DeepFace", None)
    monkeypatch.setattr(face_service, "DeepFaceImportError", ImportError("No module named 'tensorflow'"))

    with pytest.raises(ModelsUnavailable):
        face_service.get_deepface()
    with pytest.raises(ModelsUnavailable):
        face_service.locate_faces(None)


def test_a_liveness_model_that_cannot_be_imported_is_models_unavailable(monkeypatch):
    def missing():
        raise ImportError("No module named 'tensorflow'")

    monkeypatch.setattr(settings, "face_liveness", True)
    monkeypatch.setattr(face_service, "get_liveness_models", missing)

    with pytest.raises(ModelsUnavailable):
        face_service.liveness_scores(None, [(0, 0, 10, 10)])


def test_a_liveness_model_that_breaks_while_running_is_not_called_an_outage(monkeypatch):
    pytest.importorskip("tensorflow")

    def crash():
        raise ValueError("bad weights")

    monkeypatch.setattr(settings, "face_liveness", True)
    monkeypatch.setattr(face_service, "get_liveness_models", crash)

    with pytest.raises(RuntimeError) as raised:
        face_service.liveness_scores(None, [(0, 0, 10, 10)])
    assert not isinstance(raised.value, ModelsUnavailable)


def test_the_detector_says_whether_it_gave_both_eye_points():
    area = SimpleNamespace(x=100, y=50, w=80, h=100, confidence=0.9, left_eye=(160, 90), right_eye=(120, 90))
    one_eye = SimpleNamespace(**dict(vars(area), left_eye=None))

    assert face_service.located(area)["eyes"] is True and face_service.located(area)["turn"] == pytest.approx(0.0)
    assert face_service.located(one_eye)["eyes"] is False and face_service.located(one_eye)["turn"] is None


# ---- enrollment ----------------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["locate_faces", "judge_liveness", "embed_faces"])
def test_an_enrollment_frame_during_an_outage_is_503_and_stores_nothing(db_session, camera, student, monkeypatch, stage):
    face_routes.start_enrollment(student.id, db_session)
    camera["faces"] = [face(FRONT_BOX)]
    monkeypatch.setattr(face_routes, stage, broken)

    answer = send(db_session, student, "front")

    assert answer.status_code == 503
    assert body(answer)["quality_status"] == "models_unavailable" and body(answer)["accepted"] is False
    assert body(answer)["message"] == MESSAGES["models_unavailable"]
    # Never a capture problem, and what went wrong inside the server is not sent to the browser.
    assert body(answer)["quality_status"] != "embedding_failed" and "tensorflow" not in answer.body.decode()
    assert db_session.query(FaceEmbedding).count() == 0
    assert face_routes.pending_enrollments[student.id]["candidates"] == []


def test_any_other_model_error_is_still_a_frame_that_failed(db_session, camera, student, monkeypatch):
    def fails(image):
        raise RuntimeError("Face detection failed: out of memory")

    face_routes.start_enrollment(student.id, db_session)
    monkeypatch.setattr(face_routes, "locate_faces", fails)

    answer = send(db_session, student, "front")

    assert answer["quality_status"] == "embedding_failed" and answer["accepted"] is False


def test_the_enrollment_route_answers_503_over_http(client, monkeypatch):
    from test_enrollment_flow import IMAGE_BASE64
    from app.models.person import Person

    with client.db() as db:
        person = Person(person_code="STF-9", full_name="Staff Nine", person_type="admin")
        db.add(person)
        db.commit()
        person_id = person.id
    assert client.post(f"/face/enrollment/start/{person_id}?consent=true").status_code == 200
    monkeypatch.setattr(face_routes, "locate_faces", broken)

    answer = client.post("/face/enrollment/frame", json={"person_id": person_id, "current_step": "front", "image_base64": IMAGE_BASE64})

    assert answer.status_code == 503 and answer.json()["quality_status"] == "models_unavailable"


# ---- the scanner ---------------------------------------------------------------------------

@pytest.fixture()
def scanner(monkeypatch, clock):
    clock.step = 0
    monkeypatch.setattr(settings, "face_challenge", "off")
    monkeypatch.setattr(face_routes, "judge_liveness", lambda image, boxes: [("live", 0.98)] * len(boxes))
    return {"faces": [], "clock": clock}


def test_a_scan_during_an_outage_is_503_and_marks_nobody(db_session, scanner, monkeypatch):
    session, _ = batch_of(db_session, ["Arun"])
    monkeypatch.setattr(face_routes, "detect_faces", broken)

    answers = [scan(db_session, scanner, session) for _ in range(4)]

    assert all(answer.status_code == 503 for answer in answers)
    assert all(body(answer)["status"] == "models_unavailable" and body(answer)["faces"] == [] for answer in answers)
    assert "tensorflow" not in answers[0].body.decode() and records(db_session) == []


def test_a_liveness_outage_in_the_middle_of_a_scan_marks_nobody(db_session, scanner, monkeypatch):
    from test_recognition_flow import face as seated

    session, _ = batch_of(db_session, ["Arun"])
    monkeypatch.setattr(face_routes, "detect_faces", lambda image: scanner["faces"])
    monkeypatch.setattr(face_routes, "judge_liveness", broken)

    answers = [scan(db_session, scanner, session, [seated(0, "Arun")]) for _ in range(4)]

    assert all(answer.status_code == 503 and body(answer)["status"] == "models_unavailable" for answer in answers)
    assert records(db_session) == []
