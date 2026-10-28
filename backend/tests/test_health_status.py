import pytest

from app.services import face_service


@pytest.fixture()
def models(monkeypatch):
    # (ready, failed): the two flags warm_up leaves behind.
    def set_state(ready, failed):
        monkeypatch.setattr(face_service, "models_ready", ready)
        monkeypatch.setattr(face_service, "models_failed", failed)
    return set_state


def test_models_that_could_not_be_loaded_are_reported_as_failed_not_as_starting(anon_client, client, models):
    # Until October 2026 a failed load said "starting" for ever, so nobody could tell it from a slow one.
    models(False, True)

    health = anon_client.get("/health")
    ready = anon_client.get("/health/ready")

    assert (health.status_code, health.json()) == (200, {"success": True, "message": "failed", "data": {"status": "failed"}})
    assert (ready.status_code, ready.json()["data"]) == (503, {"status": "failed"})
    assert client.get("/health/details").json()["data"] == {"database": "connected", "face_models": "failed"}


def test_models_still_loading_and_loaded_are_answered_as_before(anon_client, client, models):
    models(False, False)
    assert anon_client.get("/health").json()["data"] == {"status": "starting"}
    assert anon_client.get("/health/ready").status_code == 503
    assert client.get("/health/details").json()["data"]["face_models"] == "loading"

    models(True, False)
    assert anon_client.get("/health").json()["data"] == {"status": "ok"}
    assert anon_client.get("/health/ready").status_code == 200
    assert client.get("/health/details").json()["data"]["face_models"] == "ready"


def test_the_public_answer_says_failed_and_nothing_about_why(anon_client, models):
    models(False, True)

    assert anon_client.get("/health").text.count("tensorflow") == 0
    assert set(anon_client.get("/health").json()["data"]) == {"status"}


def test_warm_up_remembers_a_failed_load(monkeypatch):
    monkeypatch.setattr(face_service, "models_ready", False)
    monkeypatch.setattr(face_service, "models_failed", False)

    def missing(_image):
        raise ImportError("DeepFace failed to import: No module named 'tensorflow'")

    monkeypatch.setattr(face_service, "detect_faces", missing)

    face_service.warm_up()

    assert (face_service.models_ready, face_service.models_failed) == (False, True)
