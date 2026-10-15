"""Every route needs a login, except the few that are named as public.

The first tests walk the routes the application really has, so a route added later is covered
without anyone remembering to add a test for it.
"""
import base64
import json
import logging
import re

import cv2
import numpy as np
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app import database
from app.config import settings
from app.main import PUBLIC_ROUTES, allowed_origins, app, docs_addresses
from app.models.admin_account import AdminAccount
from app.models.attendance import AttendanceRecord, AttendanceSession
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEmbedding
from app.models.person import Person
from app.routes import course_routes, face_routes
from app.schemas.attendance_schema import AttendanceMark
from app.security import require_admin, require_super_admin
from app.services import attendance_service, face_service
from app.utils.errors import safe_error_text
from app.utils.time_utils import today_local

def registered_routes():
    """(method, path) of every route the application answers, however this FastAPI version keeps them."""
    from fastapi import routing

    # Newer versions keep an included router as one entry and list its routes on request; older
    # ones put every route straight into app.routes.
    listed = routing.iter_route_contexts(app.routes) if hasattr(routing, "iter_route_contexts") else app.routes
    return sorted((method, route.path) for route in listed for method in (route.methods or ()) if method not in ("HEAD", "OPTIONS"))


ROUTES = registered_routes()
GUARDED = [route for route in ROUTES if route not in PUBLIC_ROUTES]
# The Super Admin portal, and everything else an account that is logged in uses.
PORTAL = [route for route in GUARDED if route[1].startswith("/super-admin")]
CONSOLE = [route for route in GUARDED if not route[1].startswith(("/auth/", "/super-admin"))]
NOT_LOGGED_IN = {"detail": "Not logged in."}


def address(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def name_of(route):
    return f"{route[0]} {route[1]}"


# ---- the walk -----------------------------------------------------------------------------------

def test_the_walk_really_covers_the_application():
    paths = {path for _method, path in ROUTES}

    # The routes that existed before logins did, by the file they live in, and the new ones.
    assert len(ROUTES) >= 58
    for expected in ("/", "/health", "/health/details", "/courses", "/courses/{course_id}", "/batches/{batch_id}", "/users", "/users/{person_id}",
                     "/people/{person_id}", "/users/upload", "/courses/upload/template", "/timings/{timing_id}", "/attendance/mark",
                     "/attendance/session/start", "/face/recognize", "/face/enrollment/frame", "/face/enrollment/start/{person_id}",
                     "/face/timings", "/sheet/sync-pending", "/sheet/status", "/auth/login", "/auth/me", "/auth/change-password",
                     "/super-admin/dashboard", "/super-admin/admins", "/super-admin/admins/{account_id}/disable", "/super-admin/audit-logs"):
        assert expected in paths, expected
    assert len(PORTAL) == 10 and len(CONSOLE) >= 50


def test_the_walk_and_the_description_of_the_api_list_the_same_routes():
    # Two separate ways of asking the application what it answers. If they ever disagree, one of
    # them is missing a route and the walk below cannot be trusted.
    described = sorted((method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations)

    assert described == ROUTES


def test_the_public_list_is_short_and_names_only_routes_that_exist():
    assert PUBLIC_ROUTES == {("GET", "/health"), ("POST", "/auth/login"), ("POST", "/auth/refresh"), ("POST", "/auth/logout")}
    assert PUBLIC_ROUTES <= set(ROUTES)


@pytest.mark.parametrize("route", GUARDED, ids=name_of)
def test_without_a_login_every_other_route_answers_401(anon_client, route):
    method, path = route

    response = anon_client.request(method, address(path))

    assert (response.status_code, response.json()) == (401, NOT_LOGGED_IN)
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("route", GUARDED, ids=name_of)
def test_a_body_or_a_made_up_token_changes_nothing_about_that(anon_client, route):
    method, path = route

    with_body = anon_client.request(method, address(path), json={"course_code": "CS101", "course_name": "Computer Science", "person_id": 1})
    with_token = anon_client.request(method, address(path), headers={"Authorization": "Bearer not-a-real-token"})

    # 401, never 422 or 404: who is asking is settled before anything about the request is looked at.
    assert (with_body.status_code, with_token.status_code) == (401, 401)


def as_role(backend, make_account, log_in, role, route, **fields):
    method, path = route
    with backend.db() as db:
        # The account the portal's routes act on (id 1) is someone else's, so that they answer
        # about it and not "you cannot do this to yourself".
        if not db.query(AdminAccount).filter_by(email="someone.else@example.com").first():
            make_account(db, "someone.else@example.com", role="super_admin")
        token, _refresh = log_in(db, make_account(db, f"{role}@example.com", role=role, **fields))
    return backend().request(method, address(path), headers={"Authorization": f"Bearer {token}"})


@pytest.mark.parametrize("role", ["admin", "super_admin"])
@pytest.mark.parametrize("route", CONSOLE, ids=name_of)
def test_an_admin_and_a_super_admin_are_let_through_to_every_console_route(backend, make_account, log_in, role, route):
    response = as_role(backend, make_account, log_in, role, route)

    # Whatever the route then makes of an empty request (not found, incomplete...), it was not about access.
    assert response.status_code not in (401, 403)


@pytest.mark.parametrize("route", PORTAL, ids=name_of)
def test_only_a_super_admin_is_let_through_to_the_portal(backend, make_account, log_in, route):
    admin = as_role(backend, make_account, log_in, "admin", route)
    owner = as_role(backend, make_account, log_in, "super_admin", route)

    # Refused before the request is even looked at, also when it is incomplete.
    assert (admin.status_code, admin.json()) == (403, {"detail": "Only a super admin can do this."})
    assert owner.status_code not in (401, 403)


def test_the_audit_log_cannot_be_changed_or_removed_through_the_api():
    audit_routes = [(method, path) for method, path in ROUTES if "audit" in path]

    assert audit_routes == [("GET", "/super-admin/audit-logs"), ("GET", "/super-admin/audit-logs/actions")]


@pytest.mark.parametrize("route", [route for route in GUARDED if not route[1].startswith("/auth/")], ids=name_of)
def test_an_account_with_a_temporary_password_is_let_through_to_none_of_them(backend, make_account, log_in, route):
    response = as_role(backend, make_account, log_in, "super_admin", route, must_change_password=True)

    assert (response.status_code, response.json()) == (403, {"detail": "Change your password before continuing."})


def test_the_public_routes_answer_without_a_login(anon_client):
    assert anon_client.get("/health").status_code == 200
    # Answered on their own terms: a missing password, no cookie to renew, nothing to log out of.
    assert anon_client.post("/auth/login", json={"email": "nobody@example.com", "password": "not the password"}).json() == {"detail": "Incorrect email or password."}
    assert anon_client.post("/auth/logout").status_code == 200
    assert anon_client.post("/auth/refresh").status_code == 401


# ---- the two guards -----------------------------------------------------------------------------

@pytest.fixture()
def guarded_pages(backend):
    # A stand-in application with one route behind each guard. It uses the real guards and, through
    # the backend fixture, the same database as the real application.
    pages = FastAPI()

    @pages.get("/for-admins")
    def for_admins(actor=Depends(require_admin)):
        return {"email": actor.email, "role": actor.role}

    @pages.get("/for-super-admins")
    def for_super_admins(actor=Depends(require_super_admin)):
        return {"email": actor.email, "role": actor.role}

    return TestClient(pages, base_url="https://testserver")


def test_the_super_admin_guard_lets_in_super_admins_only(backend, guarded_pages, make_account, log_in):
    with backend.db() as db:
        admin, _ = log_in(db, make_account(db, "admin@example.com", role="admin"))
        owner, _ = log_in(db, make_account(db, "owner@example.com", role="super_admin"))
        temporary, _ = log_in(db, make_account(db, "new.owner@example.com", role="super_admin", must_change_password=True))

    def ask(path, token=None):
        response = guarded_pages.get(path, headers={"Authorization": f"Bearer {token}"} if token else {})
        return response.status_code, response.json()

    assert ask("/for-super-admins") == (401, NOT_LOGGED_IN)
    assert ask("/for-super-admins", admin) == (403, {"detail": "Only a super admin can do this."})
    assert ask("/for-super-admins", owner) == (200, {"email": "owner@example.com", "role": "super_admin"})
    assert ask("/for-super-admins", temporary) == (403, {"detail": "Change your password before continuing."})
    # A super admin is an admin too.
    assert ask("/for-admins", admin) == (200, {"email": "admin@example.com", "role": "admin"})
    assert ask("/for-admins", owner) == (200, {"email": "owner@example.com", "role": "super_admin"})


# ---- who marked it ------------------------------------------------------------------------------

@pytest.fixture()
def lesson(client):
    with client.db() as db:
        course = Course(course_code="CS101", course_name="Computer Science")
        db.add(course)
        db.commit()
        batch = CourseBatch(course_id=course.id, batch_name="Morning A")
        db.add(batch)
        db.commit()
        student = Person(person_code="STU-1", full_name="Sample Student", person_type="student", course_id=course.id, batch_id=batch.id, face_enrollment_status="completed")
        session = AttendanceSession(session_name="Class", session_type="regular", course_id=course.id, batch_id=batch.id, session_date=today_local(), status="active")
        db.add_all([student, session])
        db.commit()
        return {"session": session.id, "student": student.id}


def saved_records(client):
    with client.db() as db:
        return [(record.person_id, record.marked_by, record.status, record.recognition_method) for record in db.query(AttendanceRecord).order_by(AttendanceRecord.id)]


@pytest.mark.parametrize("claimed", ["principal@example.com", "someone else", "", None])
def test_a_record_marked_by_hand_is_signed_with_the_account_that_is_logged_in(client, lesson, claimed):
    response = client.post("/attendance/mark", json={"session_id": lesson["session"], "person_id": lesson["student"], "recognition_method": "manual", "marked_by": claimed})

    assert response.status_code == 200
    # What the client says about who marked it is not used.
    assert response.json()["data"]["marked_by"] == "admin@example.com"
    assert saved_records(client) == [(lesson["student"], "admin@example.com", "present", "manual")]


def test_marking_absent_is_signed_the_same_way(client, lesson):
    client.post("/attendance/mark-absent", json={"session_id": lesson["session"], "person_id": lesson["student"], "marked_by": "someone else"})

    assert saved_records(client) == [(lesson["student"], "admin@example.com", "absent", "auto_absent")]


def test_code_that_calls_the_service_itself_still_names_who_marked_it(db_session):
    # No request, no logged-in account: a script or a test says who it is, as before.
    student = Person(person_code="STU-1", full_name="Sample Student", person_type="member")
    db_session.add(student)
    db_session.commit()

    record, _message = attendance_service.mark_attendance(db_session, AttendanceMark(person_id=student.id, recognition_method="manual", marked_by="import script"))

    assert record.marked_by == "import script"


# The scanner, over HTTP, with the detector and the liveness model replaced by a known face.
VECTOR = np.random.default_rng(5).normal(size=512)
FRAME = base64.b64encode(cv2.imencode(".png", np.random.default_rng(6).integers(40, 216, size=(480, 640, 3), dtype=np.uint8))[1].tobytes()).decode()


@pytest.fixture()
def scanner(monkeypatch, clock, client, lesson):
    clock.step = 0
    seen = {"frames": 0}

    def detect(image):
        seen["frames"] += 1
        return [{"box": [200, 120, 110, 140], "embedding": list(VECTOR), "detection_confidence": 0.9, "turn": 0.0}]

    monkeypatch.setattr(settings, "face_challenge", "off")
    monkeypatch.setattr(face_routes, "detect_faces", detect)
    monkeypatch.setattr(face_routes, "judge_liveness", lambda image, boxes: [("live", 0.98) for _box in boxes])
    with client.db() as db:
        for pose in face_routes.REQUIRED_STEPS:
            db.add(FaceEmbedding(person_id=lesson["student"], embedding_vector=json.dumps(list(VECTOR)), pose_type=pose, model_name=face_routes.model_label(), is_active=True))
        db.commit()

    def send(through):
        clock.advance(1.0)
        return through.post("/face/recognize", json={"session_id": lesson["session"], "image_base64": FRAME, "scanner_id": "cam-1", "device_name": "phone"})

    send.seen = seen
    return send


def test_a_face_scan_marks_attendance_in_the_name_of_the_account_running_the_scanner(client, lesson, scanner):
    answers = [scanner(client).json() for _ in range(4)]

    assert [answer["faces"][0]["result"] for answer in answers] == ["pending", "pending", "verified", "already_marked"]
    assert saved_records(client) == [(lesson["student"], "admin@example.com", "present", "face_ai")]
    with client.db() as db:
        assert db.query(AttendanceRecord).one().device_name == "phone"


def test_a_frame_sent_without_a_login_never_reaches_the_models(backend, client, lesson, scanner):
    stranger = backend()

    answers = [scanner(stranger) for _ in range(5)]

    assert [(answer.status_code, answer.json()) for answer in answers] == [(401, NOT_LOGGED_IN)] * 5
    assert scanner.seen["frames"] == 0 and saved_records(client) == []


def test_enrollment_cannot_be_started_or_read_without_a_login(backend, client, lesson):
    stranger = backend()

    assert stranger.post(f"/face/enrollment/start/{lesson['student']}").status_code == 401
    assert stranger.get(f"/face/enrollment/status/{lesson['student']}").status_code == 401
    assert stranger.get("/face/enrollment/users", params={"course_id": 1, "batch_id": 1}).status_code == 401
    assert client.get(f"/face/enrollment/status/{lesson['student']}").status_code == 200
    with client.db() as db:
        assert db.get(Person, lesson["student"]).face_enrollment_status == "completed"


# ---- /health ------------------------------------------------------------------------------------

def test_the_public_health_answer_is_one_word(anon_client, monkeypatch):
    monkeypatch.setattr(face_service, "models_ready", False)
    starting = anon_client.get("/health")
    monkeypatch.setattr(face_service, "models_ready", True)
    ready = anon_client.get("/health")

    assert (starting.status_code, starting.json()) == (200, {"success": True, "message": "starting", "data": {"status": "starting"}})
    assert (ready.status_code, ready.json()) == (200, {"success": True, "message": "ok", "data": {"status": "ok"}})


def test_when_the_database_cannot_be_reached_health_says_so_and_nothing_more(anon_client, monkeypatch):
    class Unreachable:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception('connection to server at "db.internal-host.example" (10.1.2.3), port 5432 failed: password authentication failed for user "postgres"'))

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", Unreachable)

    response = anon_client.get("/health")

    assert (response.status_code, response.json()) == (503, {"success": False, "message": "unavailable", "data": {"status": "unavailable"}})
    assert "internal-host" not in response.text and "postgres" not in response.text


def test_the_details_are_for_people_who_are_logged_in(anon_client, client, monkeypatch):
    monkeypatch.setattr(face_service, "models_ready", True)

    assert anon_client.get("/health/details").status_code == 401
    assert client.get("/health/details").json() == {"success": True, "message": "Healthy", "data": {"database": "connected", "face_models": "ready"}}


# ---- the description of the API -----------------------------------------------------------------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"])
def test_the_description_of_every_route_is_not_served_unless_switched_on(anon_client, client, path):
    assert anon_client.get(path).status_code == 404
    assert client.get(path).status_code == 404


def test_the_switch_for_the_description_is_off_by_default_and_works():
    import inspect

    from app import config

    assert 'os.getenv("API_DOCS", "false")' in inspect.getsource(config.Settings)
    assert docs_addresses(False) == {"docs_url": None, "redoc_url": None, "openapi_url": None}
    on, off = FastAPI(**docs_addresses(True)), FastAPI(**docs_addresses(False))
    assert {route.path for route in on.routes} >= {"/docs", "/redoc", "/openapi.json"}
    assert off.routes == []


# ---- errors nobody handled ----------------------------------------------------------------------

SECRETS = ("hunter2-the-password", "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl", "S3cretDbPass")
# No part of a secret may survive either: the salt and the digest inside the hash, the token's signature.
FRAGMENTS = ("c2FsdHNhbHQ", "aGFzaGhhc2hoYXNo", "c2lnbmF0dXJl", "eyJzdWIiOiIxIn0", "hunter2", "S3cret")


def breaking(error):
    def broken(*args, **kwargs):
        raise error
    return broken


def test_an_unhandled_error_is_answered_with_a_reference_and_nothing_about_what_broke(client, monkeypatch, caplog):
    error = RuntimeError(f"could not save password=hunter2-the-password hash {SECRETS[1]} token {SECRETS[2]} via postgresql://postgres:S3cretDbPass@db.example.com/postgres")
    monkeypatch.setattr(course_routes, "course_data", breaking(error))
    with client.db() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.commit()

    with caplog.at_level(logging.DEBUG):
        # The test client would raise an error that reached the web server. It does not: the
        # application answered it itself, so the server never gets to print the original.
        response = client.get("/courses")

    body = response.json()
    reference = body["details"]["reference"]
    assert response.status_code == 500 and body["success"] is False
    assert body["message"] == f"Something went wrong on the server. If it keeps happening, give this reference to whoever looks after the system: {reference}"
    assert re.fullmatch(r"[0-9a-f]{8}", reference)
    for secret in SECRETS + ("could not save", "RuntimeError", "db.example.com"):
        assert secret not in response.text

    logged = [record.getMessage() for record in caplog.records if record.name == "vernex.errors"]
    assert len(logged) == 1
    # What a person looking after the system needs: which request, what kind of error, where.
    assert logged[0].startswith(f"Unhandled error {reference} on GET /courses: RuntimeError | at ")
    assert "course_routes.py" in logged[0] and "list_courses" in logged[0]
    everything_logged = "\n".join(record.getMessage() + str(record.exc_info or "") for record in caplog.records)
    for secret in SECRETS + FRAGMENTS + ("could not save",):
        assert secret not in everything_logged and secret not in response.text


@pytest.mark.parametrize("text_of_error", [
    "Could not import row for asha@example.com, phone 9876543210",
    "'Asha Example'",
    'invalid literal for int() with base 10: "STU-0042"',
])
def test_an_unhandled_error_that_quotes_a_person_is_logged_without_them(client, monkeypatch, caplog, text_of_error):
    monkeypatch.setattr(course_routes, "course_data", breaking(KeyError(text_of_error) if text_of_error.startswith("'") else ValueError(text_of_error)))
    with client.db() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.commit()

    with caplog.at_level(logging.DEBUG):
        client.get("/courses")

    everything_logged = "\n".join(record.getMessage() + str(record.exc_info or "") for record in caplog.records)
    assert "list_courses" in everything_logged
    for personal in ("asha@example.com", "9876543210", "Asha Example", "STU-0042"):
        assert personal not in everything_logged


def test_a_database_error_is_logged_without_the_statement_the_values_or_the_row(client, monkeypatch, caplog):
    driver_says = Exception('null value in column "full_name" violates not-null constraint\nDETAIL:  Failing row contains (7, asha@example.com, null, ' + SECRETS[1] + ').')
    error = IntegrityError("INSERT INTO admin_accounts (email, full_name, password_hash) VALUES (%(email)s, %(full_name)s, %(password_hash)s)", {"email": "asha@example.com", "password_hash": SECRETS[1]}, driver_says)
    monkeypatch.setattr(course_routes, "course_data", breaking(error))
    with client.db() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.commit()

    with caplog.at_level(logging.DEBUG):
        response = client.get("/courses")

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 500
    assert 'IntegrityError: null value in column "full_name" violates not-null constraint' in logged
    for leaked in (SECRETS[1], "asha@example.com", "INSERT INTO", "Failing row", "DETAIL") + FRAGMENTS:
        assert leaked not in logged and leaked not in response.text


def test_the_answer_to_an_unhandled_error_still_carries_the_cors_headers(client, monkeypatch):
    monkeypatch.setattr(course_routes, "course_data", breaking(RuntimeError("anything")))
    with client.db() as db:
        db.add(Course(course_code="CS101", course_name="Computer Science"))
        db.commit()

    response = client.get("/courses", headers={"Origin": "http://localhost:5173"})

    # Without them a browser on another origin would report a network failure instead of this answer.
    assert response.status_code == 500 and response.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---- pages on other origins ---------------------------------------------------------------------

FOREIGN_ORIGINS = [
    "http://localhost:3999", "http://127.0.0.1:5173", "http://192.168.0.50:5173", "http://10.1.2.3:9000",
    "http://172.16.0.9:5173", "https://localhost:5173", "https://evil.example", "null",
]


@pytest.mark.parametrize("origin", FOREIGN_ORIGINS)
def test_a_page_on_another_origin_cannot_read_a_renewed_token(backend, make_account, origin):
    # A browser that is logged in sends the refresh cookie with a request that a page on another port
    # of the same machine starts, too. The token in the answer stays out of that page's reach only
    # because the backend does not name the page's origin as one that may read its answers.
    with backend.db() as db:
        make_account(db, "asha@example.com", password="correct horse battery staple")
    browser = backend()
    assert browser.post("/auth/login", json={"email": "asha@example.com", "password": "correct horse battery staple"}).status_code == 200

    renewed = browser.post("/auth/refresh", headers={"Origin": origin})
    asked = browser.options("/auth/refresh", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
    asked_with_token = browser.options("/users", headers={"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})

    assert renewed.status_code == 200 and "access_token" in renewed.text
    assert "access-control-allow-origin" not in renewed.headers
    assert (asked.status_code, asked_with_token.status_code) == (400, 400)
    assert "access-control-allow-origin" not in asked.headers and "access-control-allow-origin" not in asked_with_token.headers


def test_the_origin_named_in_the_settings_may_read_the_answers(client):
    answer = client.get("/courses", headers={"Origin": "http://localhost:5173"})
    asked = client.options("/courses", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})

    assert answer.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert answer.headers["access-control-allow-credentials"] == "true"
    assert asked.status_code == 200 and asked.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("setting, origins", [
    ("http://localhost:5173", ["http://localhost:5173"]),
    (" https://console.example.com/ , http://localhost:5173,https://console.example.com", ["https://console.example.com", "http://localhost:5173"]),
    ("*", []),
    ("null, ,", []),
    ("*, https://console.example.com", ["https://console.example.com"]),
    ("", []),
])
def test_only_exact_addresses_from_the_settings_are_allowed(setting, origins):
    assert allowed_origins(setting) == origins


def test_no_pattern_of_origins_is_allowed():
    cors = next(item for item in app.user_middleware if item.cls.__name__ == "CORSMiddleware")

    assert cors.kwargs.get("allow_origin_regex") is None
    assert cors.kwargs["allow_origins"] == ["http://localhost:5173"]


def test_refusals_the_routes_make_on_purpose_are_not_touched(client):
    # 404, 409 and the like keep their own words; only what nobody handled gets the generic answer.
    assert client.get("/courses/999").json() == {"detail": "Course not found"}
    assert client.delete("/batches/999").status_code == 404


@pytest.mark.parametrize("text_of_error, kept, removed", [
    (f"stored {SECRETS[1]} for user", "stored [hash] for user", "c2FsdHNhbHQ"),
    (f"stored {SECRETS[1]} for user", "stored [hash] for user", "aGFzaGhhc2hoYXNo"),
    ("row ('asha', '$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHQ$aGFzaGhhc2hoYXNo', 3)", "row ('asha', '[hash]', 3)", "aGFzaGhhc2hoYXNo"),
    ("old hash $2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234 kept", "old hash [hash] kept", "abcdefghijklmnopqrstuu"),
    (f"bad token {SECRETS[2]}", "bad token [token]", "c2lnbmF0dXJl"),
    ("header was Authorization: Bearer abc.def-ghi_jkl", "[hidden]", "abc.def-ghi_jkl"),
    ("cannot connect to postgresql://postgres.ref:S3cretDbPass@host:5432/postgres", "postgresql://postgres.ref:[hidden]@host:5432/postgres", "S3cretDbPass"),
    ("login failed, password=hunter2-the-password", "password=[hidden]", "hunter2-the-password"),
    ("refresh " + "k7" * 24 + " unknown", "refresh [long value] unknown", "k7" * 24),
    ("first line\nsecond line with more", "first line", "second line"),
    ("x" * 1000, "x" * 0, "x" * 301),
    ('invalid input syntax for type integer: "STU-0042"', "invalid input syntax for type integer: [value]", "STU-0042"),
    ("new row for asha@example.com violates check constraint", "new row for [email] violates check constraint", "asha@example.com"),
    ("value 9876543210 out of range for type integer", "value [number] out of range", "9876543210"),
    ('duplicate key value violates unique constraint "ix_admin_accounts_email"', 'violates unique constraint "ix_admin_accounts_email"', "[value]"),
])
def test_what_is_logged_about_a_database_error_has_its_secrets_and_values_taken_out(text_of_error, kept, removed):
    logged = safe_error_text(OperationalError("SELECT 1", {}, Exception(text_of_error)))

    assert logged.startswith("OperationalError: ") and kept in logged and removed not in logged
    assert len(logged) < 400


@pytest.mark.parametrize("error", [
    ValueError("Could not import row for asha@example.com, phone 9876543210"),
    KeyError("Asha Example"),
    RuntimeError(f"could not save password=hunter2-the-password hash {SECRETS[1]}"),
    TypeError(),
])
def test_any_other_error_is_logged_as_its_kind_only(error):
    assert safe_error_text(error) == type(error).__name__


def test_a_database_error_says_what_kind_it_was_and_no_more():
    assert safe_error_text(SQLAlchemyError()) == "SQLAlchemyError: SQLAlchemyError"
    error = OperationalError("SELECT secret_column FROM t WHERE x = ?", ("hunter2-the-password",), Exception("database is locked"))
    assert safe_error_text(error) == "OperationalError: database is locked"


def test_the_database_engine_never_puts_values_into_its_error_messages():
    assert database.engine.hide_parameters is True
    with database.engine.connect() as connection, pytest.raises(SQLAlchemyError) as error:
        connection.execute(text("SELECT * FROM a_table_that_does_not_exist WHERE password_hash = :value"), {"value": "hunter2-the-password"})

    assert "hunter2-the-password" not in str(error.value) and "a_table_that_does_not_exist" in str(error.value)


# ---- what a failed bulk import leaves in the log ------------------------------------------------

def test_a_failed_import_logs_what_kind_of_error_and_where_and_nothing_from_the_rows(client, monkeypatch, caplog, make_csv):
    from app.routes import import_routes

    # What PostgreSQL says when a row clashes: its first line names the constraint, DETAIL quotes the row.
    driver_says = Exception('duplicate key value violates unique constraint "uq_people_person_code"\nDETAIL:  Key (person_code)=(STU-0042) already exists.')
    errors = [
        IntegrityError("INSERT INTO user_management (person_code, full_name, phone) VALUES (%(person_code)s, %(full_name)s, %(phone)s)",
                       {"person_code": "STU-0042", "full_name": "Asha Example", "phone": "9876543210"}, driver_says),
        ValueError("Row 4: Asha Example (asha@example.com, 9876543210) could not be read"),
    ]
    content = make_csv([["person_code", "full_name"], ["STU-0042", "Asha Example"]])

    for error in errors:
        monkeypatch.setattr(import_routes, "run_import", breaking(error))
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            answer = client.post("/users/upload", params={"person_type": "student"}, files={"file": ("students.csv", content)})

        assert (answer.status_code, answer.json()["detail"]) == (500, import_routes.IMPORT_FAILED)
        logged = [record for record in caplog.records if record.name == "app.routes.import_routes"]
        assert len(logged) == 1 and logged[0].exc_info is None, "no traceback: its text is the error's text"
        message = logged[0].getMessage()
        assert message.startswith(f"Bulk import of students failed: {type(error).__name__}") and "import_upload" in message
        for personal in ("STU-0042", "Asha", "asha@example.com", "9876543210", "DETAIL", "INSERT INTO", "full_name"):
            assert personal not in message, personal
    # The database's own first line is kept: it says which rule was broken.
    assert 'uq_people_person_code' in safe_error_text(errors[0])


# ---- what the web server's access log keeps -----------------------------------------------------

@pytest.mark.parametrize("path, kept", [
    ("/super-admin/admins?search=asha%40example.com&role=admin", "/super-admin/admins?search=[hidden]&role=[hidden]"),
    ("/super-admin/audit-logs?actor_id=4&date_from=2026-10-01&page=2", "/super-admin/audit-logs?actor_id=[hidden]&date_from=[hidden]&page=[hidden]"),
    ("/users?asha@example.com", "/users?[hidden]"),
    ("/users?search=&&course_id=3", "/users?search=[hidden]&course_id=[hidden]"),
    ("/x?%3Cscript%3E=1", "/x?[hidden]"),
    ("/courses", "/courses"),
    ("/courses?", "/courses"),
])
def test_the_access_log_keeps_the_names_of_query_parameters_and_never_their_values(path, kept):
    from app.utils.access_log import without_query_values

    assert without_query_values(path) == kept


def test_uvicorns_own_access_line_for_a_search_holds_no_search_term(caplog):
    from uvicorn.logging import AccessFormatter
    from uvicorn.protocols.utils import get_path_with_query_string

    # The line exactly as uvicorn writes it (protocols/http/h11_impl.py and httptools_impl.py), with
    # the path made by uvicorn's own helper, through the logger the backend starts with.
    scope = {"path": "/super-admin/admins", "query_string": b"search=asha%40example.com&status=active"}
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:50000", "GET", get_path_with_query_string(scope), "1.1", 200)

    record = caplog.records[-1]
    assert record.getMessage() == '127.0.0.1:50000 - "GET /super-admin/admins?search=[hidden]&status=[hidden] HTTP/1.1" 200'
    # And as uvicorn's own formatter prints it to the console.
    printed = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "asha" not in printed and "search=[hidden]" in printed


def test_the_backend_puts_the_filter_on_the_access_log_once():
    from app.utils.access_log import QueryValuesHidden, hide_query_values

    hide_query_values()
    assert sum(isinstance(item, QueryValuesHidden) for item in logging.getLogger("uvicorn.access").filters) == 1


def test_searching_still_works_with_the_filter_in_place(backend, make_account, log_in):
    with backend.db() as db:
        token, _refresh = log_in(db, make_account(db, "owner@example.com", role="super_admin"))
        make_account(db, "asha@example.com", full_name="Asha Example")
    owner = backend(headers={"Authorization": f"Bearer {token}"})

    found = owner.get("/super-admin/admins", params={"search": "asha@example"}).json()["data"]

    assert [account["email"] for account in found] == ["asha@example.com"]


# ---- no page on another origin is trusted unless it is named ------------------------------------

def test_by_default_no_page_on_another_origin_may_read_the_answers():
    import inspect
    from pathlib import Path

    from dotenv import dotenv_values

    from app import config

    assert 'os.getenv("FRONTEND_ORIGIN", "")' in inspect.getsource(config.Settings)
    assert allowed_origins("") == []
    template = dotenv_values(Path(__file__).resolve().parents[1] / ".env.example")
    assert template.get("FRONTEND_ORIGIN") == ""
