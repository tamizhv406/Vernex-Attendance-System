"""What the face routes keep in memory is forgotten once it can never be used again.

Until October 2026 four of their stores only ever grew while the backend ran: every day's "already
marked" answers, enrollments abandoned by closing the page (with their face vectors), and expired
galleries and sessions. Today's marks, running enrollments and fresh caches are never dropped.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.routes import face_routes
from app.utils.time_utils import today_local

NOW = 100_000.0


@pytest.fixture(autouse=True)
def empty_stores(monkeypatch):
    for store in (face_routes.marked_today, face_routes.pending_enrollments, face_routes.gallery_cache, face_routes.session_cache):
        store.clear()
    monkeypatch.setattr(face_routes, "last_forgotten", float("-inf"))
    yield
    for store in (face_routes.marked_today, face_routes.pending_enrollments, face_routes.gallery_cache, face_routes.session_cache):
        store.clear()


def enrollment(touched, busy=False):
    return {"mode": "guided", "steps": ["front"], "step": "front", "samples": [], "candidates": [], "touched": touched, "busy": busy}


def test_marks_of_earlier_days_are_forgotten_and_todays_kept():
    today = today_local()
    face_routes.marked_today.update({(1, 7, today - timedelta(days=1)): "present", (2, 8, today - timedelta(days=30)): "late", (3, 7, today): "present"})

    face_routes.forget_what_is_stale(NOW)

    assert face_routes.marked_today == {(3, 7, today): "present"}


def test_an_abandoned_enrollment_is_forgotten_and_a_live_or_busy_one_kept():
    face_routes.pending_enrollments.update({
        1: enrollment(touched=NOW - face_routes.ENROLLMENT_FORGET_SECONDS - 1),
        2: enrollment(touched=NOW - 5),
        3: enrollment(touched=NOW - face_routes.ENROLLMENT_FORGET_SECONDS - 1, busy=True),
    })

    face_routes.forget_what_is_stale(NOW)

    assert sorted(face_routes.pending_enrollments) == [2, 3]


def test_expired_galleries_and_sessions_are_forgotten_and_fresh_ones_kept():
    face_routes.gallery_cache.update({"old": (NOW - face_routes.GALLERY_TTL_SECONDS - 1, "vectors"), "fresh": (NOW - 1, "vectors")})
    face_routes.session_cache.update({1: (NOW - face_routes.SESSION_TTL_SECONDS - 1, SimpleNamespace()), 2: (NOW - 1, SimpleNamespace())})

    face_routes.forget_what_is_stale(NOW)

    assert list(face_routes.gallery_cache) == ["fresh"] and list(face_routes.session_cache) == [2]


def test_the_stores_are_looked_through_at_most_once_a_minute():
    face_routes.marked_today[(1, 7, today_local() - timedelta(days=1))] = "present"
    face_routes.forget_what_is_stale(NOW)
    face_routes.marked_today[(2, 7, today_local() - timedelta(days=1))] = "present"

    face_routes.forget_what_is_stale(NOW + face_routes.FORGET_EVERY_SECONDS - 1)
    assert len(face_routes.marked_today) == 1
    face_routes.forget_what_is_stale(NOW + face_routes.FORGET_EVERY_SECONDS)
    assert face_routes.marked_today == {}


def test_a_scan_and_a_new_enrollment_both_look_through_the_stores():
    import inspect

    assert "forget_what_is_stale(" in inspect.getsource(face_routes.scan_frame)
    assert "forget_what_is_stale(" in inspect.getsource(face_routes.start_enrollment)
