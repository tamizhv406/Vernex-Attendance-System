import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["FACE_SCAN_LOG"] = "false"
os.environ["FACE_TIMING_LOG"] = "false"
# The tests fix their own settings, whatever backend/.env says on this machine. Enrollment tests
# use the full five poses unless a test asks for a quick enrollment.
os.environ.update(FACE_ENROLL_MODE="guided", FACE_ENROLL_QUICK_STEPS="front,left,right", FACE_ENROLL_BURST_FRAMES="3")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class Clock:
    # The time the face routes see. Every look at it moves it on a little, like real frames do;
    # a test can also jump it forward.
    def __init__(self, step=0.3):
        self.now = 1000.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    from app.routes import face_routes
    from app.services import tracking_service

    clock = Clock()
    monkeypatch.setattr(face_routes, "clock", clock)
    face_routes.pending_enrollments.clear()
    face_routes.gallery_cache.clear()
    face_routes.session_cache.clear()
    face_routes.marked_today.clear()
    tracking_service.reset()
    yield clock
    face_routes.pending_enrollments.clear()
    face_routes.gallery_cache.clear()
    face_routes.session_cache.clear()
    face_routes.marked_today.clear()
    tracking_service.reset()
