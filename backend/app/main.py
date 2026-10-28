import threading
from contextlib import asynccontextmanager

from sqlalchemy import text
from fastapi import FastAPI, Depends, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import allowed_origins, settings
from app.database import get_db, require_database_file, require_login_accounts
from app.models import admin_account, attendance, audit_log, course, face_embedding, issue, person, sync_log, timing
from app.routes import attendance_routes, auth_routes, course_routes, face_routes, import_routes, issue_routes, person_routes, sheet_routes, super_admin_routes, timing_routes
from app.schema import init_database_schema
from app.security import require_admin, require_super_admin
from app.services import auth_service, face_service
from app.services.face_service import warm_up
from app.utils import access_log
from app.utils.errors import ServerErrors
from app.utils.security_headers import SecurityHeaders
from app.utils.upload_limit import UploadLimit

# The web server's access log keeps the path of every request, query string included. Searches and
# filters (an email typed into the Admins search) are not written there: only their names are.
access_log.hide_query_values()


def docs_addresses(enabled: bool) -> dict:
    # /docs, /redoc and /openapi.json describe every route to anyone who asks. They exist only when
    # API_DOCS=true is set in backend/.env, which is for a developer's own machine.
    return {} if enabled else {"docs_url": None, "redoc_url": None, "openapi_url": None}


def startup():
    # Before anything else: without the signing secret nobody could log in, so the backend says so
    # and stops instead of starting up useless.
    auth_service.signing_key()
    # The same for the database: a missing SQLite file, or one without a login account, is a wrong
    # DATABASE_URL. Said at once, instead of a backend where every password is "incorrect".
    require_database_file()
    init_database_schema()
    require_login_accounts()
    threading.Thread(target=warm_up, daemon=True).start()


@asynccontextmanager
async def lifespan(app):
    startup()
    yield


app = FastAPI(title="Vernex Smart Attendance", version="0.1.0", lifespan=lifespan, **docs_addresses(settings.api_docs))

# Added first so that it sits inside the CORS middleware: its answers get the CORS headers too.
app.add_middleware(ServerErrors)
# Camera frames: refused by their declared length before the body is read (inside CORS, like ServerErrors).
app.add_middleware(UploadLimit, limit=settings.face_max_upload_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(settings.frontend_origin),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Outermost, so that every answer has them, refusals and errors included.
app.add_middleware(SecurityHeaders)


def repeats_nothing(path: str) -> bool:
    return path == "/issues" or path.startswith(("/auth/", "/super-admin/", "/issues/"))


@app.exception_handler(RequestValidationError)
async def malformed_request(request: Request, error: RequestValidationError):
    # FastAPI answers a malformed request by repeating what was sent ("input"). On the auth routes
    # what was sent is a password, on the portal's account routes it can be one typed into a field
    # that does not exist, and a reported issue holds whatever was typed into it. There the answer
    # says what is wrong and repeats nothing.
    if not repeats_nothing(request.url.path):
        return await request_validation_exception_handler(request, error)
    problems = [{"type": item.get("type"), "loc": list(item.get("loc", ())), "msg": item.get("msg")} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": problems})


# Everything that is not on this list needs a login. tests/test_route_protection.py walks every
# route of the application and fails if one is open without being named here.
PUBLIC_ROUTES = {
    ("GET", "/health"),
    # For a process supervisor or an uptime monitor: one word each, nothing about what is behind it.
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
    ("POST", "/auth/login"),
    # These two are answered on the strength of the refresh cookie, which only a logged-in browser has.
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
}
logged_in = [Depends(require_admin)]


@app.get("/", dependencies=logged_in)
def root():
    return {"success": True, "message": "Vernex Smart Attendance backend is running", "data": {"docs": "/docs"} if settings.api_docs else {}}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    # Open to anyone, so it says one word and nothing about what is behind it: "ok" once the backend
    # can be used, "starting" while the face models load, "failed" if they could not be loaded (the log
    # says why), "unavailable" if the database cannot be reached.
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"success": False, "message": "unavailable", "data": {"status": "unavailable"}})
    return {"success": True, "message": models_status(), "data": {"status": models_status()}}


def models_status():
    if face_service.models_ready:
        return "ok"
    return "failed" if face_service.models_failed else "starting"


@app.get("/health/live")
def health_live():
    # The process is up and answering. Says nothing about the database or the models.
    return {"success": True, "message": "ok", "data": {"status": "ok"}}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    # Ready to take attendance: the database answers and the face models are loaded. 503 otherwise,
    # so a monitor or a load balancer can wait for it.
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"success": False, "message": "unavailable", "data": {"status": "unavailable"}})
    if not face_service.models_ready:
        status = models_status()
        return JSONResponse(status_code=503, content={"success": False, "message": status, "data": {"status": status}})
    return {"success": True, "message": "ok", "data": {"status": "ok"}}


@app.get("/health/details", dependencies=logged_in)
def health_details(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    models = {"ok": "ready", "failed": "failed", "starting": "loading"}[models_status()]
    return {"success": True, "message": "Healthy", "data": {"database": "connected", "face_models": models}}


app.include_router(auth_routes.router)
# First of the rest, so that "/users/upload" and "/courses/upload" can never be taken for "/users/{person_id}" or "/courses/{course_id}".
app.include_router(import_routes.router, dependencies=logged_in)
app.include_router(person_routes.router, dependencies=logged_in)
app.include_router(person_routes.legacy_router, dependencies=logged_in)
app.include_router(course_routes.router, dependencies=logged_in)
app.include_router(timing_routes.router, dependencies=logged_in)
app.include_router(attendance_routes.router, dependencies=logged_in)
app.include_router(face_routes.router, dependencies=logged_in)
app.include_router(sheet_routes.router, dependencies=logged_in)
# Reporting a problem: any account that is logged in, about its own issues only.
app.include_router(issue_routes.router, dependencies=logged_in)
# Super admins only, for every route of the portal, whatever each route asks for itself.
app.include_router(super_admin_routes.router, dependencies=[Depends(require_super_admin)])
