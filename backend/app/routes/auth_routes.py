import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import allowed_origins, settings
from app.database import get_db
from app.models.admin_account import AdminAccount
from app.schemas.auth_schema import ChangePasswordRequest, LoginRequest
from app.security import client_details, current_account, refuse
from app.serializers import admin_account_data
from app.services import audit_service, auth_service
from app.services.auth_service import Actor, AuthError, Login
from app.utils.errors import safe_error_text, where_it_happened

router = APIRouter(prefix="/auth", tags=["Authentication"])
log = logging.getLogger("vernex.audit")
# The refresh token lives in this cookie and nowhere else in the browser. Scripts cannot read it
# (HttpOnly), it only travels over HTTPS (Secure), other sites' pages never send it (SameSite=Strict)
# and it only goes to the auth routes (Path).
REFRESH_COOKIE = "vx_refresh"
# Asked of the two routes that act on the cookie alone (refresh, logout). SameSite=Strict is about
# sites, not origins: a page on another port of the same machine is the same site, and the browser
# sends it the cookie. What no page can do is add a header of its own to a request for another
# origin unless the backend agrees first (a CORS preflight, which only FRONTEND_ORIGIN passes). The
# console sends this header with every auth request; a page elsewhere cannot.
CLIENT_HEADER = "X-Requested-With"
CLIENT_VALUE = "vernex"
NOT_FROM_THE_CONSOLE = "Refused: this request did not come from the Vernex console."


def ok(message, data=None):
    return {"success": True, "message": message, "data": data}


def client_address(request: Request) -> str:
    return client_details(request)["ip"] or "unknown"


def from_the_console(request: Request) -> bool:
    if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
        return False
    # Browsers also say who started a request (pages cannot change it). One started on another site,
    # or another origin of this one, is accepted only from an origin named in FRONTEND_ORIGIN.
    if request.headers.get("sec-fetch-site") in ("cross-site", "same-site"):
        return (request.headers.get("origin") or "").rstrip("/") in allowed_origins(settings.frontend_origin)
    return True


def not_from_the_console() -> JSONResponse:
    # The cookie and the login are left exactly as they were.
    return JSONResponse({"detail": NOT_FROM_THE_CONSOLE}, status_code=403, headers={"Cache-Control": "no-store"})


def failure_reason(error: AuthError) -> str:
    if error.status == 403:
        return "expired_temporary_password" if error.message in auth_service.TEMPORARY_PASSWORD_EXPIRED_MESSAGES else "disabled"
    if error.status == 429:
        return "locked"
    return "wrong_password" if error.account_id else "unknown_email"


def audit_refused_login(db: Session, request: Request, error: AuthError):
    """Writes a refused login to the audit log. The refusal is the answer either way.

    It cannot share a transaction with anything: the refusal is decided, and the attempt counted,
    before. If the entry cannot be written, the person still gets the refusal (never a server
    error in its place) and the server's log says which entry is missing, without the email typed.
    """
    client = client_details(request)
    try:
        # The email that was typed is never kept: for an address without an account it may be a
        # password typed into the wrong field.
        audit_service.record(
            db, "auth.login_failed", target_type="admin_account" if error.account_id else None, target_id=error.account_id,
            details={"reason": failure_reason(error)}, ip=client["ip"], user_agent=client["user_agent"],
        )
        db.commit()
    except SQLAlchemyError as failure:
        db.rollback()
        log.error("A refused login (%s) was not written to the audit log: %s | at %s", failure_reason(error), safe_error_text(failure), where_it_happened(failure))


def keep_cookie(response: Response, refresh_token: str):
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=settings.auth_refresh_days * 24 * 3600, path=settings.auth_cookie_path,
        httponly=True, secure=True, samesite="strict",
    )


def drop_cookie(response: Response):
    response.delete_cookie(REFRESH_COOKIE, path=settings.auth_cookie_path, httponly=True, secure=True, samesite="strict")


def login_data(result: Login):
    return {
        "access_token": result.access_token,
        "token_type": "bearer",
        "expires_in": result.expires_in,
        "account": admin_account_data(result.account),
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        # A login that succeeds is written to the audit log in its own commit (auth_service.login).
        result = auth_service.login(db, payload.email, payload.password, client_address(request), request.headers.get("user-agent"))
    except AuthError as error:
        # Too many attempts from one address is answered before the database is asked, and stays
        # that way: a flood of requests must not become a flood of rows.
        if error.message != auth_service.TOO_MANY_ATTEMPTS:
            audit_refused_login(db, request, error)
        raise refuse(error)
    keep_cookie(response, result.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return ok("Logged in", login_data(result))


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    if not from_the_console(request):
        return not_from_the_console()
    try:
        result = auth_service.refresh(db, request.cookies.get(REFRESH_COOKIE))
    except AuthError as error:
        # The cookie is of no further use. Taking it away stops the browser from offering it again.
        refused = JSONResponse({"detail": error.message}, status_code=error.status, headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        drop_cookie(refused)
        return refused
    response.headers["Cache-Control"] = "no-store"
    return ok("Session renewed", login_data(result))


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Works with the cookie alone, so that someone whose access token has run out can still log out.
    if not from_the_console(request):
        return not_from_the_console()
    client = client_details(request)
    auth_service.logout(db, request.cookies.get(REFRESH_COOKIE), client["ip"], client["user_agent"])
    drop_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return ok("Logged out")


@router.get("/me")
def me(response: Response, actor: Actor = Depends(current_account), db: Session = Depends(get_db)):
    account = db.get(AdminAccount, actor.id)
    if account is None:
        raise refuse(AuthError(401, auth_service.SESSION_ENDED))
    response.headers["Cache-Control"] = "no-store"
    return ok("Account fetched", admin_account_data(account))


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, response: Response, actor: Actor = Depends(current_account), db: Session = Depends(get_db)):
    try:
        # Written to the audit log in the same commit as the new password (auth_service.change_password).
        auth_service.change_password(db, actor, payload.current_password, payload.new_password)
    except AuthError as error:
        raise refuse(error)
    # Every login of the account has ended, this one included: the new password is asked for next.
    drop_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return ok("Password changed. Log in again with the new password.")
