"""The audit log: one row for each action the task sheet lists.

A row is added to the same database session as the change it records, so the two are committed
together. What goes into details is checked here, whoever calls: no password, token, hash, cookie
or face data, only short values, and nothing that looks like a secret.
"""
import json
import re
from datetime import date, datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.admin_account import AdminAccount
from app.models.attendance import AttendanceRecord
from app.models.audit_log import AuditLog
from app.models.course import Course, CourseBatch
from app.models.face_embedding import FaceEnrollment
from app.models.issue import Issue
from app.models.person import Person
from app.serializers import audit_log_data

# Every action that is written, with the words the Audit Log page shows for it.
ACTIONS = {
    "auth.login": "Logged in",
    "auth.login_failed": "Login failed",
    "auth.logout": "Logged out",
    "auth.password_changed": "Changed own password",
    "admin.created": "Admin created",
    "admin.updated": "Admin updated",
    "admin.disabled": "Admin disabled",
    "admin.enabled": "Admin re-enabled",
    "admin.password_reset": "Admin password reset",
    "person.deleted": "Person deleted",
    "course.deleted": "Course deleted",
    "batch.deleted": "Batch deleted",
    "attendance.marked": "Attendance marked by hand",
    "face_enrollment.started": "Face enrollment started",
    "face_enrollment.completed": "Face enrollment completed",
    "face_enrollment.cancelled": "Face enrollment cancelled",
    "import.uploaded": "Bulk upload",
    "issue.created": "Issue reported",
    "issue.status_changed": "Issue status changed",
}
TARGET_TYPES = ("admin_account", "person", "course", "batch", "attendance_record", "issue")

# Keys that are never kept, at any depth, whatever their value.
_FORBIDDEN_KEY = re.compile(r"(?i)pass(word|wd)?|token|secret|hash|cookie|authori[sz]ation|credential|embedding|vector|image|frame|photo")
# Values that are never kept: a password hash, a signed token, anything long and unbroken enough to be a key.
_SECRET_LOOKING = re.compile(r"\$(argon2|2[aby]\$|pbkdf2|scrypt)|eyJ[A-Za-z0-9_-]{5,}\.|[A-Za-z0-9_-]{32,}")
MAX_TEXT = 200
MAX_ITEMS = 20
MAX_DEPTH = 3
MAX_DETAILS = 2000


def _clean(value, depth: int):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, str):
        return "[hidden]" if _SECRET_LOOKING.search(value) else value[:MAX_TEXT]
    if depth >= MAX_DEPTH:
        return None
    if isinstance(value, dict):
        allowed = [(str(key)[:60], item) for key, item in value.items() if not _FORBIDDEN_KEY.search(str(key))]
        return {key: _clean(item, depth + 1) for key, item in allowed[:MAX_ITEMS]}
    if isinstance(value, (list, tuple, set)):
        return [_clean(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
    # Bytes, objects and anything else are not described at all.
    return None


def clean_details(details):
    """What may be kept of details: a dict of short plain values, without secrets. None if nothing is left."""
    if not details:
        return None
    if not isinstance(details, dict):
        raise TypeError("Audit details must be a dict")
    kept = _clean(details, 0)
    if not kept:
        return None
    if len(json.dumps(kept, default=str)) > MAX_DETAILS:
        return {"note": "details too long to keep"}
    return kept


def _clip(value, limit):
    value = (value or "").strip()
    return value[:limit] or None


def record(db: Session, action: str, *, target_type: str | None = None, target_id: int | None = None, details: dict | None = None,
           actor_id: int | None = None, ip: str | None = None, user_agent: str | None = None) -> AuditLog:
    """Adds one row to db. The caller commits, together with the change the row is about.

    Who acted, and from where, is taken from the request (app/security.py keeps them on the session)
    unless given here. A login that failed and the command-line tool have nobody to name.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    if target_type is not None and target_type not in TARGET_TYPES:
        raise ValueError(f"Unknown audit target: {target_type}")
    actor = db.info.get("actor")
    client = db.info.get("client") or {}
    entry = AuditLog(
        actor_id=actor_id if actor_id is not None else (actor.id if actor else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=clean_details(details),
        ip=_clip(ip if ip is not None else client.get("ip"), 64),
        user_agent=_clip(user_agent if user_agent is not None else client.get("user_agent"), 255),
    )
    db.add(entry)
    return entry


# ---- reading it back ----------------------------------------------------------------------------

def entries(db: Session, *, actor_id: int | None = None, action: str | None = None, target_type: str | None = None,
            since=None, before=None, page: int = 1, page_size: int = 25):
    """One page of rows, newest first, described for the Audit Log page. Returns (rows, how many match)."""
    query = db.query(AuditLog)
    if actor_id is not None:
        query = query.filter(AuditLog.actor_id == actor_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if since is not None:
        query = query.filter(AuditLog.created_at >= since)
    if before is not None:
        query = query.filter(AuditLog.created_at < before)
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return describe(db, rows), total


def _labels(db: Session, model, ids, label):
    return {row.id: label(row) for row in db.query(model).filter(model.id.in_(ids))} if ids else {}


def _label_from_details(entry):
    # The row is gone (it was deleted): its audit entry kept what is needed to say what it was.
    details = entry.details or {}
    name = details.get("full_name") or details.get("course_name") or details.get("batch_name")
    code = details.get("person_code") or details.get("course_code")
    return f"{name} ({code})" if name and code else name or code


def describe(db: Session, rows) -> list:
    """The rows with the names of who acted and of what they acted on, looked up now."""
    wanted = {}
    for entry in rows:
        if entry.target_type and entry.target_id is not None:
            wanted.setdefault(entry.target_type, set()).add(entry.target_id)
    actors = {row.id: row for row in db.query(AdminAccount).filter(AdminAccount.id.in_({entry.actor_id for entry in rows if entry.actor_id}))}
    labels = {
        "admin_account": _labels(db, AdminAccount, wanted.get("admin_account"), lambda row: row.email),
        "person": _labels(db, Person, wanted.get("person"), lambda row: f"{row.full_name} ({row.person_code})"),
        "course": _labels(db, Course, wanted.get("course"), lambda row: f"{row.course_name} ({row.course_code})"),
        "batch": _labels(db, CourseBatch, wanted.get("batch"), lambda row: row.batch_name),
        "attendance_record": _labels(db, AttendanceRecord, wanted.get("attendance_record"), lambda row: f"{row.person_name} ({row.person_code}), {row.attendance_date.isoformat()}"),
        "issue": _labels(db, Issue, wanted.get("issue"), lambda row: f"#{row.id} {row.title}"),
    }
    return [
        audit_log_data(entry, actors.get(entry.actor_id), labels.get(entry.target_type, {}).get(entry.target_id) or _label_from_details(entry), ACTIONS.get(entry.action))
        for entry in rows
    ]


# ---- face enrollment ----------------------------------------------------------------------------
# Written from the changes to face_enrollments rather than in the face routes, which stay as they
# are. An enrollment is started when a record is created in progress or an existing one is put back
# in progress (its started_at is set again), completed when its status becomes "completed", and
# cancelled when an enrollment still in progress is deleted: by Cancel, by timing out, or because
# the faces were refused. Deleting a person removes enrollments without going through this session's
# objects, so it is recorded as the person's deletion only.

def _changed(enrollment, name) -> bool:
    return inspect(enrollment).attrs[name].history.has_changes()


@event.listens_for(Session, "before_flush")
def _face_enrollment_events(db: Session, _context, _instances):
    events = []
    for enrollment in db.new:
        if isinstance(enrollment, FaceEnrollment) and enrollment.enrollment_status == "in_progress":
            events.append(("face_enrollment.started", enrollment, {"steps": enrollment.total_steps}))
    for enrollment in db.dirty:
        if not isinstance(enrollment, FaceEnrollment):
            continue
        if enrollment.enrollment_status == "completed" and _changed(enrollment, "enrollment_status"):
            events.append(("face_enrollment.completed", enrollment, {"steps": enrollment.completed_steps}))
        elif enrollment.enrollment_status == "in_progress" and (_changed(enrollment, "enrollment_status") or _changed(enrollment, "started_at")):
            events.append(("face_enrollment.started", enrollment, {"steps": enrollment.total_steps}))
    for enrollment in db.deleted:
        if isinstance(enrollment, FaceEnrollment) and enrollment.enrollment_status == "in_progress":
            events.append(("face_enrollment.cancelled", enrollment, {"steps_done": enrollment.completed_steps or 0}))
    for action, enrollment, details in events:
        record(db, action, target_type="person", target_id=enrollment.person_id, details=details)
