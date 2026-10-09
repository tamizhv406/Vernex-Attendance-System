import threading

from sqlalchemy import text
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import attendance, course, face_embedding, person, sync_log, timing
from app.routes import attendance_routes, course_routes, face_routes, person_routes, sheet_routes, timing_routes
from app.schema import init_database_schema
from app.services.face_service import warm_up

app = FastAPI(title="Vernex Smart Attendance AI", version="0.1.0")

origins = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    settings.frontend_origin,
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(origins),
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_database_schema()
    threading.Thread(target=warm_up, daemon=True).start()


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"success": False, "message": str(exc), "details": {}})


@app.get("/")
def root():
    return {"success": True, "message": "Vernex Smart Attendance AI backend is running", "data": {"docs": "/docs"}}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"success": True, "message": "Healthy", "data": {"database": "connected"}}


app.include_router(person_routes.router)
app.include_router(person_routes.legacy_router)
app.include_router(course_routes.router)
app.include_router(timing_routes.router)
app.include_router(attendance_routes.router)
app.include_router(face_routes.router)
app.include_router(sheet_routes.router)
