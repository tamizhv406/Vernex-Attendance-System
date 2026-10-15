"""Who is asking. These are the dependencies that guard every route except the few public ones.

app/main.py attaches require_admin where each router is included, so a route file does not have to
mention it and a route added later is guarded without anyone remembering to.
"""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import auth_service
from app.services.auth_service import Actor, AuthError

PASSWORD_CHANGE_REQUIRED = "Change your password before continuing."
SUPER_ADMIN_ONLY = "Only a super admin can do this."


def refuse(error: AuthError) -> HTTPException:
    headers = {}
    if error.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if error.retry_after:
        headers["Retry-After"] = str(error.retry_after)
    return HTTPException(error.status, error.message, headers=headers or None)


def current_account(request: Request, db: Session = Depends(get_db)) -> Actor:
    """The account the request's access token belongs to. 401 without one, or once its login has ended."""
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise refuse(AuthError(401, auth_service.NOT_LOGGED_IN))
    try:
        actor = auth_service.actor_for(db, token.strip())
    except AuthError as error:
        raise refuse(error)
    # Kept on the request's own database session. The route gets this same session, so code further
    # in (who marked an attendance record, who did what in the audit log) can say who is acting
    # without every function in between having to hand it along, and without taking the client's word for it.
    db.info["actor"] = actor
    db.info["client"] = client_details(request)
    request.state.account = actor
    return actor


def client_details(request: Request) -> dict:
    # Behind the frontend's proxy this is the browser's address: the proxy passes it on and uvicorn
    # accepts that from the local machine only.
    return {"ip": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


def require_admin(actor: Actor = Depends(current_account)) -> Actor:
    """Any account that is logged in: an admin or a super admin."""
    if actor.must_change_password:
        # A temporary password opens nothing but the page that replaces it.
        raise HTTPException(403, PASSWORD_CHANGE_REQUIRED)
    return actor


def require_super_admin(actor: Actor = Depends(require_admin)) -> Actor:
    if actor.role != "super_admin":
        raise HTTPException(403, SUPER_ADMIN_ONLY)
    return actor
