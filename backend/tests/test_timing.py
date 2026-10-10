"""The timing instrumentation: what it records, what it must never record, and that it changes no answer.

These tests use the stand-in camera of the recognition tests, so they prove the bookkeeping, not
how fast the real models are. Real speed is measured by scripts/benchmark_latency.py.
"""
import asyncio
import json

import pytest

from app.routes import face_routes
from app.utils import timing
from test_recognition_flow import FRAME_BASE64, NAMES, VECTORS, FakeRequest, batch_of, camera, face, marked, scan  # noqa: F401 (camera is a fixture)


@pytest.fixture(autouse=True)
def fresh_timings():
    timing.recent.clear()
    timing.warmed.clear()
    timing.current.set(None)
    yield
    timing.recent.clear()
    timing.warmed.clear()
    timing.current.set(None)


def test_stages_add_up_inside_one_request():
    timer = timing.start("scan")
    with timing.stage("detect"):
        pass
    with timing.stage("detect"):
        pass
    timing.note(width=960, height=540, faces=2)

    record = timing.finish(timer, "pending")

    assert set(record["stages_ms"]) == {"detect"} and record["stages_ms"]["detect"] >= 0
    assert record["kind"] == "scan" and record["outcome"] == "pending" and record["faces"] == 2
    assert record["total_ms"] >= record["stages_ms"]["detect"]
    assert list(timing.recent) == [record]


def test_a_stage_outside_a_request_is_not_timed_but_the_model_counts_as_loaded():
    # The warm-up at startup runs outside any request. The first real request after it is warm.
    with timing.stage("detect", model=True):
        pass
    timing.note(faces=3)
    timer = timing.start("scan")
    with timing.stage("detect", model=True):
        pass
    record = timing.finish(timer, "no_face")

    assert list(timing.recent) == [record] and record["cold"] == [] and "faces" not in record


def test_a_model_that_failed_to_load_is_still_cold_next_time():
    for _ in range(2):
        timer = timing.start("scan")
        with pytest.raises(RuntimeError):
            with timing.stage("detect", model=True):
                raise RuntimeError("weights missing")
        record = timing.finish(timer, "error")
        assert record["cold"] == ["detect"]


def test_only_the_first_run_of_a_model_is_cold():
    # A model is loaded once per process and reused: the request that loads it is marked, the ones
    # after it are not.
    records = []
    for _ in range(3):
        timer = timing.start("scan")
        with timing.stage("detect", model=True):
            pass
        with timing.stage("embed", model=True):
            pass
        records.append(timing.finish(timer, "unknown"))

    assert [record["cold"] for record in records] == [["detect", "embed"], [], []]


def test_percentiles_are_measured_values_and_leave_cold_requests_out():
    records = [{"kind": "scan", "outcome": "x", "cold": [], "total_ms": float(value), "stages_ms": {"detect": float(value) / 2}} for value in range(1, 101)]
    records.append({"kind": "scan", "outcome": "x", "cold": ["detect"], "total_ms": 40000.0, "stages_ms": {"detect": 39000.0}})

    summary = timing.summarize(records)["scan"]

    assert summary["requests"] == 101 and summary["cold_requests"] == 1 and summary["cold_total_ms"] == [40000.0]
    assert summary["total_ms"] == {"n": 100, "p50": 50.0, "p95": 95.0, "p99": 99.0, "max": 100.0}
    assert summary["stages_ms"]["detect"]["p95"] == 47.5


def test_a_scan_is_timed_stage_by_stage_and_still_marks_as_before(db_session, camera):
    session, _ = batch_of(db_session, NAMES[:2])

    answers = [scan(db_session, camera, session, [face(0, "Arun"), face(1, "Stranger")]) for _ in range(3)]

    assert [item["result"] for item in answers[2]["faces"]] == ["verified", "unknown"] and marked(db_session) == ["Arun"]
    scans = [record for record in timing.recent if record["kind"] == "scan"]
    assert len(scans) == 3
    assert [record["outcome"] for record in scans] == ["pending+unknown", "pending+unknown", "unknown+verified"]
    last = scans[-1]
    assert {"read", "decode", "lock_wait", "session", "gallery", "quality", "match", "write"} <= set(last["stages_ms"])
    assert "write" not in scans[0]["stages_ms"]
    assert (last["width"], last["height"], last["faces"], last["in_flight"]) == (1280, 720, 2, 1)
    assert all(value >= 0 for value in last["stages_ms"].values()) and last["total_ms"] >= max(last["stages_ms"].values())


def test_the_timing_record_holds_no_names_ids_or_vectors(db_session, camera):
    session, people = batch_of(db_session, ["Arun"])
    for _ in range(3):
        scan(db_session, camera, session, [face(0, "Arun")])

    text = json.dumps(list(timing.recent))

    assert "Arun" not in text and "person" not in text and "embedding" not in text and "track" not in text
    allowed = {"time", "kind", "outcome", "cold", "total_ms", "stages_ms", "width", "height", "faces", "in_flight", "upload_bytes", "client_capture_ms", "client_roundtrip_ms", "step"}
    assert all(set(record) <= allowed for record in timing.recent)
    assert str(VECTORS["Arun"][0]) not in text


def test_a_skipped_frame_is_recorded_as_busy_and_runs_no_stage_of_the_models(db_session, camera, monkeypatch):
    session, _ = batch_of(db_session, ["Arun"])
    monkeypatch.setattr(face_routes, "scans_in_flight", face_routes.MAX_SCANS_IN_FLIGHT)

    answer = scan(db_session, camera, session, [face(0, "Arun")])

    assert answer["status"] == "busy"
    assert timing.recent[-1]["outcome"] == "busy" and set(timing.recent[-1]["stages_ms"]) == {"read", "decode"}


def test_a_refused_enrollment_frame_is_recorded_with_its_reason(db_session):
    body = {"person_id": 999, "current_step": "front", "image_base64": FRAME_BASE64}

    with pytest.raises(Exception):
        asyncio.run(face_routes.enrollment_frame(FakeRequest(body), db_session))

    assert timing.recent[-1]["kind"] == "enroll" and timing.recent[-1]["outcome"] == "http_404"
    assert timing.current.get() is None


def test_browser_timings_are_kept_only_when_they_are_sane_numbers():
    assert face_routes.client_ms("12.345") == 12.3
    assert face_routes.client_ms(None) is None and face_routes.client_ms("abc") is None
    assert face_routes.client_ms("-5") is None and face_routes.client_ms("1e12") is None


def test_the_timings_endpoint_reports_numbers_only(db_session, camera):
    session, _ = batch_of(db_session, ["Arun"])
    for _ in range(4):
        scan(db_session, camera, session, [face(0, "Arun")])

    data = face_routes.timings()["data"]

    assert data["scan"]["requests"] == 4 and data["scan"]["total_ms"]["n"] == 4
    assert "Arun" not in json.dumps(data)
