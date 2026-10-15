"""What a super admin does with the login accounts, and the numbers on the portal's dashboard.

Every change is committed once, together with its row in the audit log. Refusals are AuthErrors
with the HTTP status and the words for the person, as in auth_service.
"""
import secrets
from collections import Counter

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.admin_account import ROLES, STATUSES, AdminAccount
from app.models.attendance import AttendanceRecord
from app.services import audit_service, auth_service, issue_service
from app.services.auth_service import Actor, AuthError
from app.utils.time_utils import today_local

# Temporary passwords: three groups of six from an alphabet without look-alikes (no 0/o, 1/l/i),
# about 89 bits of chance. Read out or typed once, then replaced by the person at their first login.
TEMPORARY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
TEMPORARY_GROUPS = 3
TEMPORARY_GROUP_LENGTH = 6

NOT_FOUND = "Admin account not found."
EMAIL_TAKEN = "An account with this email already exists."
OWN_ROLE = "You cannot change your own role."
OWN_STATUS = "You cannot disable your own account."
OWN_RESET = "Use Change password in Settings to change your own password."
# Whoever resets a password is shown the new one, and could log in with it first. Between super
# admins that would let one take over another's identity, so the password of an account that is or
# has ever been a super admin is reset on the server instead, where it takes the person at the
# keyboard and leaves its own audit entry. "Ever" matters: making someone an admin first and then
# resetting their password would otherwise be the way in (AdminAccount.has_been_super_admin).
SUPER_ADMIN_RESET = "This account is or has been a super admin, so its password cannot be reset here. On the server, run: scripts\\create_super_admin.py --force"
LAST_SUPER_ADMIN = "This is the last active super admin. Make another account a super admin first."
ALREADY_DISABLED = "This account is already disabled."
ALREADY_ACTIVE = "This account is already active."


def temporary_password() -> str:
    return "-".join("".join(secrets.choice(TEMPORARY_ALPHABET) for _ in range(TEMPORARY_GROUP_LENGTH)) for _ in range(TEMPORARY_GROUPS))


def find(db: Session, account_id: int) -> AdminAccount:
    account = db.get(AdminAccount, account_id)
    if account is None:
        raise AuthError(404, NOT_FOUND)
    return account


def _like(text_value: str) -> str:
    escaped = text_value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_accounts(db: Session, search: str | None = None, status: str | None = None, role: str | None = None):
    query = db.query(AdminAccount)
    wanted = " ".join((search or "").split()).lower()[:120]
    if wanted:
        pattern = _like(wanted)
        query = query.filter(or_(func.lower(AdminAccount.email).like(pattern, escape="\\"), func.lower(AdminAccount.full_name).like(pattern, escape="\\")))
    if status:
        if status not in STATUSES:
            raise AuthError(400, "Status must be active or disabled.")
        query = query.filter(AdminAccount.status == status)
    if role:
        if role not in ROLES:
            raise AuthError(400, "Role must be super_admin or admin.")
        query = query.filter(AdminAccount.role == role)
    return query.order_by(func.lower(AdminAccount.full_name), AdminAccount.id).all()


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        # Another request saved the same email between the check and this commit.
        db.rollback()
        raise AuthError(409, EMAIL_TAKEN) from None


def _active_super_admins_held(db: Session) -> list:
    """The ids of the active super admins, read so that no other request can change them before this one commits.

    Two super admins disabling each other at the same moment would otherwise both see the other one
    still active, and both succeed. PostgreSQL locks the rows (in id order, so two requests never
    wait on each other in a circle); a request that waited reads them again and sees the change.
    SQLite has no row locks, so a write that changes nothing takes its database-wide write lock,
    held until the commit: a second request waits there and then reads what the first one saved.
    """
    query = select(AdminAccount.id).where(AdminAccount.role == "super_admin", AdminAccount.status == "active").order_by(AdminAccount.id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        db.execute(text("UPDATE admin_accounts SET role = role WHERE id < 0"))
    return list(db.execute(query).scalars())


def _keep_a_super_admin(db: Session, account: AdminAccount):
    """Refuses (409) to take the super admin role or the active status from the last account that has both."""
    held = _active_super_admins_held(db)
    db.refresh(account)
    if account.role == "super_admin" and account.status == "active" and not [other for other in held if other != account.id]:
        raise AuthError(409, LAST_SUPER_ADMIN)


def create(db: Session, actor: Actor, email: str, full_name: str, role: str = "admin"):
    """A new account with a temporary password, which it must change at its first login and which
    stops working after TEMPORARY_PASSWORD_HOURS. Returns (account, password)."""
    password = temporary_password()
    until = auth_service.temporary_password_until(auth_service.clock())
    try:
        account = auth_service.create_account(db, email, full_name, password, role=role, must_change_password=True,
                                              created_by=actor.id, temporary_password_expires_at=until)
    except IntegrityError:
        # Another request saved an account with this email after this one looked for it. Nothing
        # of this one was kept: no account, no audit entry.
        db.rollback()
        raise AuthError(409, EMAIL_TAKEN) from None
    audit_service.record(db, "admin.created", target_type="admin_account", target_id=account.id,
                         details={"email": account.email, "full_name": account.full_name, "role": account.role})
    _commit(db)
    return account, password


def update(db: Session, actor: Actor, account_id: int, email: str | None = None, full_name: str | None = None, role: str | None = None) -> AdminAccount:
    """Changes what is given of email, name and role. A new role ends the account's logins. Nothing changed, nothing written."""
    account = find(db, account_id)
    changes = {}
    if email is not None:
        email = auth_service.clean_account_email(email)
        if email != account.email:
            if db.query(AdminAccount.id).filter(AdminAccount.email == email, AdminAccount.id != account.id).first():
                raise AuthError(409, EMAIL_TAKEN)
            changes["email"] = email
    if full_name is not None:
        name = auth_service.clean_full_name(full_name)
        if name != account.full_name:
            changes["full_name"] = name
    if role is not None:
        if role not in ROLES:
            raise AuthError(400, "Role must be super_admin or admin.")
        if role != account.role:
            if account.id == actor.id:
                raise AuthError(400, OWN_ROLE)
            if account.role == "super_admin":
                _keep_a_super_admin(db, account)
            if role != account.role:
                changes["role"] = role
    if not changes:
        return account
    details = {field: {"from": getattr(account, field), "to": value} for field, value in changes.items()}
    for field, value in changes.items():
        setattr(account, field, value)
    if "role" in changes:
        # What the account may open has changed: it logs in again and gets the pages of its new role.
        auth_service.end_logins(db, account.id)
    else:
        auth_service.forget_after_commit(db, account.id)
    audit_service.record(db, "admin.updated", target_type="admin_account", target_id=account.id, details=details)
    _commit(db)
    return account


def disable(db: Session, actor: Actor, account_id: int) -> AdminAccount:
    """Disables an account and ends its logins on every device."""
    account = find(db, account_id)
    if account.id == actor.id:
        raise AuthError(400, OWN_STATUS)
    _keep_a_super_admin(db, account)
    if account.status == "disabled":
        raise AuthError(409, ALREADY_DISABLED)
    account.status = "disabled"
    auth_service.end_logins(db, account.id)
    audit_service.record(db, "admin.disabled", target_type="admin_account", target_id=account.id, details={"email": account.email})
    _commit(db)
    return account


def enable(db: Session, actor: Actor, account_id: int) -> AdminAccount:
    account = find(db, account_id)
    if account.status == "active":
        raise AuthError(409, ALREADY_ACTIVE)
    account.status = "active"
    auth_service.forget_after_commit(db, account.id)
    audit_service.record(db, "admin.enabled", target_type="admin_account", target_id=account.id, details={"email": account.email})
    _commit(db)
    return account


def reset_password(db: Session, actor: Actor, account_id: int):
    """A new temporary password: the old one stops working, the account is unlocked and logged out
    everywhere, and must choose its own password at the next login, within TEMPORARY_PASSWORD_HOURS.
    A disabled account stays disabled. Never for an account that is or has been a super admin: see
    SUPER_ADMIN_RESET. Returns (account, password)."""
    account = find(db, account_id)
    if account.id == actor.id:
        raise AuthError(400, OWN_RESET)
    if account.role == "super_admin" or account.has_been_super_admin:
        raise AuthError(400, SUPER_ADMIN_RESET)
    password = temporary_password()
    until = auth_service.temporary_password_until(auth_service.clock())
    auth_service.reset_password(db, account, password, must_change_password=True, enable=False, temporary_password_expires_at=until)
    audit_service.record(db, "admin.password_reset", target_type="admin_account", target_id=account.id, details={"email": account.email})
    _commit(db)
    return account, password


# ---- the dashboard ------------------------------------------------------------------------------

def dashboard(db: Session) -> dict:
    now = auth_service.clock()
    accounts = db.query(AdminAccount).all()
    active = [account for account in accounts if account.status == "active"]
    today = today_local()
    statuses = Counter(status for (status,) in db.query(AttendanceRecord.status).filter(AttendanceRecord.attendance_date == today))
    recent, _total = audit_service.entries(db, page=1, page_size=10)
    return {
        "admins": {
            "total": len(accounts),
            "active": len(active),
            "disabled": len(accounts) - len(active),
            "active_super_admins": sum(1 for account in active if account.role == "super_admin"),
            "active_admins": sum(1 for account in active if account.role == "admin"),
            "must_change_password": sum(1 for account in active if account.must_change_password),
            "temporary_password_expired": sum(1 for account in active if account.must_change_password and auth_service.temporary_password_expired(account, now)),
            "locked": sum(1 for account in accounts if account.locked_until and account.locked_until > now),
        },
        "attendance_today": {
            "date": today.isoformat(),
            "total": sum(statuses.values()),
            "present": statuses.get("present", 0),
            "late": statuses.get("late", 0),
            "absent": statuses.get("absent", 0),
            "visited": statuses.get("visited", 0),
        },
        "recent_activity": recent,
        # Open issues by severity, how many were resolved this week, and the newest open ones.
        "issues": issue_service.summary(db),
    }
