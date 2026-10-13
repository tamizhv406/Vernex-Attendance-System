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


@pytest.fixture()
def client(monkeypatch):
    # The real application over HTTP, on its own empty in-memory database. Sessions are made the
    # way app/database.py makes them (no autoflush) and handed out by the real get_db, so a route
    # behaves here as it does when the backend runs. client.db() opens a session on the same
    # database, for a test to prepare rows or to look at what a request left behind.
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool

    from app import database
    from app.main import app

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    # Not entered as a context manager: the startup hook (the schema of the real database, loading
    # the face models) must not run for these tests.
    test_client = TestClient(app)
    test_client.db = session_factory
    try:
        yield test_client
    finally:
        engine.dispose()


@pytest.fixture()
def make_xlsx():
    # rows: one list of cell values per spreadsheet row, starting at row 1. None leaves a row empty,
    # as a row someone skipped in Excel is.
    def build(rows, title="Sheet1", more_sheets=()):
        import io

        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = title
        for number, values in enumerate(rows, start=1):
            for column, value in enumerate(values or [], start=1):
                sheet.cell(row=number, column=column, value=value)
        for name, other_rows in more_sheets:
            other = workbook.create_sheet(name)
            for values in other_rows:
                other.append(values)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    return build


@pytest.fixture()
def make_csv():
    # rows: one list of cell values per line. None is an empty line.
    def build(rows, encoding="utf-8", delimiter=","):
        import csv
        import io

        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
        for values in rows:
            writer.writerow(values or [])
        return buffer.getvalue().encode(encoding)

    return build


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
