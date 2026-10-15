import threading

from sqlalchemy import text
from fastapi import FastAPI, Depends, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import allowed_origins, settings
from app.database import get_db
from app.models import admin_account, attendance, audit_log, course, face_embedding, issue, person, sync_log, timing
from app.routes import attendance_routes, auth_routes, course_routes, face_routes, import_routes, issue_routes, person_routes, sheet_routes, super_admin_routes, timing_routes
from app.schema import init_database_schema
from app.security import require_admin, require_super_admin
from app.services import auth_service, face_service
from app.services.face_service import warm_up
from app.utils import access_log
from app.utils.errors import ServerErrors

# The web server's access log keeps the path of every request, query string included. Searches and
# filters (an email typed into the Admins search) are not written there: only their names are.
access_log.hide_query_values()


def docs_addresses(enabled: bool) -> dict:
    # /docs, /redoc and /openapi.json describe every route to anyone who asks. They exist only when
    # API_DOCS=true is set in backend/.env, which is for a developer's own machine.
    return {} if enabled else {"docs_url": None, "redoc_url": None, "openapi_url": None}


app = FastAPI(title="Vernex Smart Attendance AI", version="0.1.0", **docs_addresses(settings.api_docs))

# Added first so that it sits inside the CORS middleware: its answers get the CORS headers too.
app.add_middleware(ServerErrors)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(settings.frontend_origin),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    # Before anything else: without the signing secret nobody could log in, so the backend says so
    # and stops instead of starting up useless.
    auth_service.signing_key()
    init_database_schema()
    threading.Thread(target=warm_up, daemon=True).start()


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
    ("POST", "/auth/login"),
    # These two are answered on the strength of the refresh cookie, which only a logged-in browser has.
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
}
logged_in = [Depends(require_admin)]


@app.get("/", dependencies=logged_in)
def root():
    return {"success": True, "message": "Vernex Smart Attendance AI backend is running", "data": {"docs": "/docs"} if settings.api_docs else {}}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    # Open to anyone, so it says one word and nothing about what is behind it: "ok" once the backend
    # can be used, "starting" while the face models load, "unavailable" if the database cannot be reached.
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"success": False, "message": "unavailable", "data": {"status": "unavailable"}})
    status = "ok" if face_service.models_ready else "starting"
    return {"success": True, "message": status, "data": {"status": status}}


@app.get("/health/details", dependencies=logged_in)
def health_details(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"success": True, "message": "Healthy", "data": {"database": "connected", "face_models": "ready" if face_service.models_ready else "loading"}}


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
