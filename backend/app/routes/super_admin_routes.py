"""The Super Admin portal's API. app/main.py includes this router behind require_super_admin, so an
admin is refused (403) here before anything is looked at; every handler also names the actor itself.

The audit log is read here and nowhere else, and there is no route that changes or removes a row of it.
"""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas.admin_schema import AdminCreate, AdminUpdate
from app.security import refuse, require_super_admin
from app.serializers import managed_account_data
from app.services import admin_service, audit_service, auth_service
from app.services.auth_service import Actor, AuthError

router = APIRouter(prefix="/super-admin", tags=["Super Admin"])
MAX_PAGE_SIZE = 100


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def account_answer(account):
    # The same clock as the lockout and the temporary passwords (tests move it).
    return managed_account_data(account, auth_service.clock())


def with_password(response: Response, message: str, account, password: str):
    # The temporary password is in this one answer and nowhere else: not stored, not logged, and
    # not kept by the browser or anything in between.
    response.headers["Cache-Control"] = "no-store"
    return ok(message, {"account": account_answer(account), "temporary_password": password})


def utc_start_of(day: date) -> datetime:
    # A date on the page is a day where the school is (DEFAULT_TIMEZONE); the log is kept in UTC.
    local = datetime.combine(day, time.min, tzinfo=ZoneInfo(settings.default_timezone))
    return local.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/dashboard")
def dashboard(_actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    return ok("Dashboard fetched", admin_service.dashboard(db))


@router.get("/admins")
def list_admins(search: str | None = None, status: str | None = None, role: str | None = None,
                _actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        accounts = admin_service.list_accounts(db, search, status, role)
    except AuthError as error:
        raise refuse(error)
    return ok("Admins fetched", [account_answer(account) for account in accounts])


@router.post("/admins")
def create_admin(payload: AdminCreate, response: Response, actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        account, password = admin_service.create(db, actor, payload.email, payload.full_name, payload.role)
    except AuthError as error:
        raise refuse(error)
    return with_password(response, "Admin created. Give them the temporary password; it is shown only this once.", account, password)


@router.get("/admins/{account_id}")
def get_admin(account_id: int, _actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        return ok("Admin fetched", account_answer(admin_service.find(db, account_id)))
    except AuthError as error:
        raise refuse(error)


@router.put("/admins/{account_id}")
def update_admin(account_id: int, payload: AdminUpdate, actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        account = admin_service.update(db, actor, account_id, **payload.model_dump(exclude_unset=True))
    except AuthError as error:
        raise refuse(error)
    return ok("Admin updated", account_answer(account))


@router.post("/admins/{account_id}/disable")
def disable_admin(account_id: int, actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        account = admin_service.disable(db, actor, account_id)
    except AuthError as error:
        raise refuse(error)
    return ok("Admin disabled and logged out on every device", account_answer(account))


@router.post("/admins/{account_id}/enable")
def enable_admin(account_id: int, actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        account = admin_service.enable(db, actor, account_id)
    except AuthError as error:
        raise refuse(error)
    return ok("Admin re-enabled", account_answer(account))


@router.post("/admins/{account_id}/reset-password")
def reset_admin_password(account_id: int, response: Response, actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    try:
        account, password = admin_service.reset_password(db, actor, account_id)
    except AuthError as error:
        raise refuse(error)
    return with_password(response, "Password reset. Give them the temporary password; it is shown only this once.", account, password)


@router.get("/audit-logs")
def audit_logs(actor_id: int | None = None, action: str | None = None, target_type: str | None = None,
               date_from: date | None = None, date_to: date | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
               _actor: Actor = Depends(require_super_admin), db: Session = Depends(get_db)):
    if action and action not in audit_service.ACTIONS:
        raise refuse(AuthError(400, "Unknown action."))
    if target_type and target_type not in audit_service.TARGET_TYPES:
        raise refuse(AuthError(400, "Unknown target type."))
    if date_from and date_to and date_from > date_to:
        raise refuse(AuthError(400, "The start date must not be after the end date."))
    rows, total = audit_service.entries(
        db, actor_id=actor_id, action=action, target_type=target_type,
        since=utc_start_of(date_from) if date_from else None,
        before=utc_start_of(date_to + timedelta(days=1)) if date_to else None,
        page=page, page_size=page_size,
    )
    return ok("Audit log fetched", {"items": rows, "total": total, "page": page, "page_size": page_size})


@router.get("/audit-logs/actions")
def audit_actions(_actor: Actor = Depends(require_super_admin)):
    return ok("Actions fetched", [{"action": action, "label": label} for action, label in audit_service.ACTIONS.items()])
