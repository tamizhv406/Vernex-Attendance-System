"""Logging in and staying logged in: accounts, the lockout, open logins and the tokens that prove them.

Nothing in this file writes a password, a token or a hash to a log or into an error message.
"""
import hashlib
import logging
import math
import secrets
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.admin_account import ROLES, AdminAccount, AdminSession
from app.services import audit_service, password_service
from app.services.password_service import PasswordPolicyError
from app.utils.errors import safe_error_text, where_it_happened
from app.utils.time_utils import utc_now
from app.utils.validation import normalize_email, text_limit

log = logging.getLogger("vernex.audit")

ALGORITHM = "HS256"
MIN_SECRET_BYTES = 32
# Wrong passwords in a row before an email is locked, and for how long.
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
# Login attempts one network address may make in a minute, right or wrong.
LOGIN_ATTEMPTS_PER_MINUTE = 10
# How long an answer to "is this login still good?" is reused before the database is asked again.
# The scanner sends several frames a second and the database may be far away, so not every frame
# can ask. Logging out, changing a password and ending an account's logins take effect at once in
# this process; a change made by another process (the command-line tool) within this many seconds.
ACTOR_CACHE_SECONDS = 10
# A temporary password (a new account's, or one from a reset in the portal) works for this long.
TEMPORARY_PASSWORD_HOURS = 72

INVALID_LOGIN = "Incorrect email or password."
TOO_MANY_ATTEMPTS = "Too many login attempts from this device. Wait a minute and try again."
DISABLED = "This account is disabled. Ask a super admin to enable it."
# How to get a new password depends on the account, as admin_service.reset_password decides: a super
# admin resets an admin's in the portal; an account that is or has been a super admin is never reset
# there, only on the server (AdminAccount.has_been_super_admin).
TEMPORARY_PASSWORD_EXPIRED = "This temporary password has expired. Ask a super admin for a new one."
TEMPORARY_PASSWORD_EXPIRED_ON_SERVER = (
    "This temporary password has expired. This account is or has been a super admin, so its password "
    "cannot be reset in the Super Admin portal: whoever runs the backend sets a new one on the server "
    "with scripts\\create_super_admin.py --force."
)
TEMPORARY_PASSWORD_EXPIRED_MESSAGES = (TEMPORARY_PASSWORD_EXPIRED, TEMPORARY_PASSWORD_EXPIRED_ON_SERVER)
NOT_LOGGED_IN = "Not logged in."
SESSION_ENDED = "Your session has ended. Log in again."
MISSING_SECRET = (
    "JWT_SECRET is missing from backend\\.env or is shorter than 32 characters, and nobody can log in "
    "without it. Create one with:  .venv\\Scripts\\python scripts\\create_jwt_secret.py  "
    "(it is written into backend\\.env and never shown), then start the backend again."
)

_memory = threading.Lock()
_attempts = {}  # network address -> times of its login attempts in the last minute
_strangers = {}  # email that has no account -> (failed attempts, locked until)
_actors = {}  # login (session id) -> (trusted until, Actor)
_changes = {}  # account id -> how often its logins have been ended or its details changed here
# The accounts whose remembered logins a database session forgets once its changes are committed.
FORGET_ON_COMMIT = "vx_forget_on_commit"


class AuthError(Exception):
    """A request that is refused, with the HTTP status and the words for the person."""

    def __init__(self, status, message, retry_after=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after
        # For a refused login: the account the email belongs to, if any. For the audit log only;
        # the answer to the person never depends on it.
        self.account_id = None


@dataclass(frozen=True)
class Actor:
    """Who a request comes from. What routes and services are given; it holds no secret."""
    id: int
    email: str
    full_name: str
    role: str
    must_change_password: bool
    session_id: int


@dataclass(frozen=True)
class Login:
    account: AdminAccount
    access_token: str
    expires_in: int
    # Set when a login starts. A refresh keeps the cookie the browser already has.
    refresh_token: str | None = None


def clock() -> datetime:
    # The one clock of everything in this file. Tests replace it to move time forward.
    return utc_now()


def reset_memory():
    """Forgets the attempt counts and the remembered logins. For tests and tools; the database is not touched."""
    with _memory:
        _attempts.clear()
        _strangers.clear()
        _actors.clear()
        _changes.clear()


# ---- the signing secret and the tokens ----------------------------------------------------------

def signing_key() -> str:
    if len(settings.jwt_secret.encode("utf-8")) < MIN_SECRET_BYTES:
        raise RuntimeError(MISSING_SECRET)
    return settings.jwt_secret


def hash_token(token: str) -> str:
    # The refresh token is 48 random bytes, so a plain SHA-256 is enough: there is nothing to guess.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _epoch(moment: datetime) -> int:
    return int(moment.replace(tzinfo=timezone.utc).timestamp())


def issue_access_token(account: AdminAccount, session: AdminSession, now: datetime):
    """A signed token for one login, good for a few minutes. Returns (token, seconds it lasts)."""
    seconds = settings.auth_access_minutes * 60
    claims = {"sub": str(account.id), "sid": session.id, "role": account.role, "iat": _epoch(now), "exp": _epoch(now) + seconds}
    return jwt.encode(claims, signing_key(), algorithm=ALGORITHM), seconds


def _read_access_token(token: str, now: datetime):
    try:
        # Only HS256 with our own secret is accepted, whatever the token's header claims. The
        # expiry is compared below with this file's clock, not the library's.
        claims = jwt.decode(
            token, signing_key(), algorithms=[ALGORITHM],
            options={"require": ["sub", "sid", "iat", "exp"], "verify_exp": False, "verify_iat": False},
        )
        account_id, session_id, expires = int(claims["sub"]), int(claims["sid"]), int(claims["exp"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise AuthError(401, SESSION_ENDED) from None
    if expires <= _epoch(now):
        raise AuthError(401, SESSION_ENDED)
    return account_id, session_id


# ---- who a request comes from -------------------------------------------------------------------

def temporary_password_expired(account: AdminAccount, now: datetime) -> bool:
    until = account.temporary_password_expires_at
    return until is not None and now >= until


def temporary_password_until(now: datetime) -> datetime:
    return now + timedelta(hours=TEMPORARY_PASSWORD_HOURS)


def expired_temporary_password(account: AdminAccount) -> AuthError:
    # Said only to someone who has typed the temporary password, so it may say which way applies.
    on_server = account.role == "super_admin" or account.has_been_super_admin
    return AuthError(403, TEMPORARY_PASSWORD_EXPIRED_ON_SERVER if on_server else TEMPORARY_PASSWORD_EXPIRED)


def _usable(session: AdminSession, account: AdminAccount, now: datetime) -> bool:
    # A login opened with a temporary password ends when that password runs out, like the password.
    return session.revoked_at is None and session.expires_at > now and account.status == "active" and not temporary_password_expired(account, now)


def actor_for(db: Session, token: str) -> Actor:
    """The account an access token belongs to, if its login is still open and the account active."""
    now = clock()
    account_id, session_id = _read_access_token(token, now)
    with _memory:
        known = _actors.get(session_id)
        changes_seen = _changes.get(account_id, 0)
    if known and known[0] > now and known[1].id == account_id:
        return known[1]
    row = (
        db.query(AdminSession, AdminAccount)
        .join(AdminAccount, AdminAccount.id == AdminSession.account_id)
        .filter(AdminSession.id == session_id, AdminAccount.id == account_id)
        .first()
    )
    if not row or not _usable(row[0], row[1], now):
        forget_session(session_id)
        raise AuthError(401, SESSION_ENDED)
    account = row[1]
    actor = Actor(account.id, account.email, account.full_name, account.role, bool(account.must_change_password), session_id)
    with _memory:
        # Not remembered if the account was changed while the database was being asked: what was
        # read may be from before the change, and would be trusted for seconds after it.
        if _changes.get(account_id, 0) == changes_seen:
            if len(_actors) > 2000:
                _actors.clear()
            _actors[session_id] = (now + timedelta(seconds=ACTOR_CACHE_SECONDS), actor)
    return actor


def forget_session(session_id: int):
    with _memory:
        _actors.pop(session_id, None)


def forget_account(account_id: int):
    with _memory:
        _changes[account_id] = _changes.get(account_id, 0) + 1
        for session_id in [key for key, (_until, actor) in _actors.items() if actor.id == account_id]:
            del _actors[session_id]


def forget_after_commit(db: Session, account_id: int):
    """What this process remembers about the account's logins is forgotten once db's changes are committed.

    Not before: until then the database still says the old thing, and a request answered in between
    would remember that again.
    """
    db.info.setdefault(FORGET_ON_COMMIT, set()).add(account_id)


@event.listens_for(Session, "after_commit")
def _forget_what_was_committed(db: Session):
    for account_id in db.info.pop(FORGET_ON_COMMIT, ()):
        forget_account(account_id)


# ---- attempts and the lockout -------------------------------------------------------------------

def _allow_attempt(address: str, now: datetime):
    with _memory:
        if len(_attempts) > 5000:
            _attempts.clear()
        recent = _attempts.setdefault(address, deque())
        while recent and (now - recent[0]).total_seconds() >= 60:
            recent.popleft()
        if len(recent) >= LOGIN_ATTEMPTS_PER_MINUTE:
            raise AuthError(429, TOO_MANY_ATTEMPTS, retry_after=max(1, math.ceil(60 - (now - recent[0]).total_seconds())))
        recent.append(now)


def _locked(until: datetime, now: datetime) -> AuthError:
    seconds = max(1, math.ceil((until - now).total_seconds()))
    minutes = math.ceil(seconds / 60)
    return AuthError(429, f"Too many failed attempts. Try again in {minutes} minute{'' if minutes == 1 else 's'}.", retry_after=seconds)


def _find(db: Session, email: str):
    return db.query(AdminAccount).filter(AdminAccount.email == email).first()


def _refuse_if_locked(db: Session, email: str, account, now: datetime):
    # An email is locked the same way whether or not an account has it, so that the answer never
    # tells someone who is guessing which addresses exist.
    if account is None:
        with _memory:
            _count, until = _strangers.get(email, (0, None))
            if until and until <= now:
                del _strangers[email]
    else:
        until = account.locked_until
        if until and until <= now:
            account.locked_until = None
            account.failed_login_count = 0
            db.commit()
    if until and until > now:
        raise _locked(until, now)


def _count_attempt(db: Session, email: str) -> bool:
    """Takes one of the account's attempts. False when none is left (or the email has no account)."""
    # Taken before the password is looked at, in one statement, so attempts made at the same moment
    # cannot all slip in under the limit: each must get its own, and there are only five. For an
    # email without an account this changes no row, and costs the database the same as for one that has.
    taken = db.query(AdminAccount).filter(AdminAccount.email == email, AdminAccount.failed_login_count < MAX_FAILED_LOGINS).update(
        {AdminAccount.failed_login_count: AdminAccount.failed_login_count + 1}, synchronize_session=False
    )
    db.commit()
    return bool(taken)


def _failed(db: Session, email: str, account, now: datetime) -> AuthError:
    """Records a wrong password and returns what to answer: wrong, or locked from now on."""
    until = now + timedelta(minutes=LOCK_MINUTES)
    if account is None:
        with _memory:
            if len(_strangers) > 5000:
                _strangers.clear()
            count = _strangers.get(email, (0, None))[0] + 1
            _strangers[email] = (count, until if count >= MAX_FAILED_LOGINS else None)
    else:
        count = account.failed_login_count
        if count >= MAX_FAILED_LOGINS:
            account.locked_until = until
            db.commit()
    return _locked(until, now) if count >= MAX_FAILED_LOGINS else AuthError(401, INVALID_LOGIN)


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    # Checked when an email has no account, so that the answer takes as long as for one that has.
    return password_service.hash_password(secrets.token_urlsafe(24))


def _password_matches(account, password: str) -> bool:
    # A stored password is never longer than the limit, so a longer one is wrong without being hashed.
    usable = account is not None and len(password) <= password_service.MAX_LENGTH
    matched = password_service.verify_password(account.password_hash if usable else _decoy_hash(), password[: password_service.MAX_LENGTH])
    return usable and matched


# ---- logging in, staying in, logging out --------------------------------------------------------

def login(db: Session, email: str, password: str, address: str | None = None, user_agent: str | None = None) -> Login:
    now = clock()
    _allow_attempt(address or "unknown", now)
    email = (email or "").strip().lower()[:320]
    try:
        return _log_in(db, email, password, address, user_agent, now)
    except AuthError as error:
        found = _find(db, email)
        error.account_id = found.id if found else None
        raise


def _log_in(db: Session, email: str, password: str, address: str | None, user_agent: str | None, now: datetime) -> Login:
    _refuse_if_locked(db, email, _find(db, email), now)
    attempt_taken = _count_attempt(db, email)
    account = _find(db, email)
    # With no attempt left the password is not even looked at, right or wrong.
    if (account is not None and not attempt_taken) or not _password_matches(account, password or ""):
        raise _failed(db, email, account, now)
    account.failed_login_count = 0
    account.locked_until = None
    if account.status != "active":
        # Said only to someone who has just proved they know the password.
        db.commit()
        raise AuthError(403, DISABLED)
    if temporary_password_expired(account, now):
        # Also said only to someone who knows the password, with the way to a new one.
        db.commit()
        raise expired_temporary_password(account)
    account.last_login_at = now
    if password_service.needs_rehash(account.password_hash):
        account.password_hash = password_service.hash_password(password)
    # Logins that ran out more than a day ago are of no use to anyone.
    db.query(AdminSession).filter(AdminSession.expires_at < now - timedelta(days=1)).delete(synchronize_session=False)
    token = secrets.token_urlsafe(48)
    session = AdminSession(
        account_id=account.id, token_hash=hash_token(token), expires_at=now + timedelta(days=settings.auth_refresh_days),
        last_used_at=now, ip=(address or "")[:64] or None, user_agent=(user_agent or "")[:255] or None,
    )
    db.add(session)
    db.flush()
    access_token, seconds = issue_access_token(account, session, now)
    # In the same commit as the login: there is no login without its audit entry. If the entry
    # cannot be written, the login is not saved either and the person is told it failed.
    audit_service.record(db, "auth.login", actor_id=account.id, target_type="admin_account", target_id=account.id, ip=address, user_agent=user_agent)
    db.commit()
    return Login(account, access_token, seconds, refresh_token=token)


def refresh(db: Session, refresh_token: str | None) -> Login:
    """A new access token for a login that is still open. The refresh token itself stays as it is."""
    if not refresh_token:
        raise AuthError(401, NOT_LOGGED_IN)
    now = clock()
    row = (
        db.query(AdminSession, AdminAccount)
        .join(AdminAccount, AdminAccount.id == AdminSession.account_id)
        .filter(AdminSession.token_hash == hash_token(refresh_token))
        .first()
    )
    if not row or not _usable(row[0], row[1], now):
        raise AuthError(401, SESSION_ENDED)
    session, account = row
    access_token, seconds = issue_access_token(account, session, now)
    session.last_used_at = now
    db.commit()
    return Login(account, access_token, seconds)


def logout(db: Session, refresh_token: str | None, address: str | None = None, user_agent: str | None = None) -> int | None:
    """Ends the login the refresh token belongs to, and returns its account's id. Without a token, or
    with one that is unknown or already ended, nothing happens and None is returned.

    The end of the login and its audit entry are committed together. Should the entry be what
    cannot be written, the login is ended all the same, without it: logging out must never depend
    on the audit log. That one case is written to the server's log.
    """
    if not refresh_token:
        return None
    session = db.query(AdminSession).filter(AdminSession.token_hash == hash_token(refresh_token)).first()
    if not session:
        return None
    session_id, account_id = session.id, session.account_id
    ended = None
    if session.revoked_at is None:
        session.revoked_at = clock()
        forget_after_commit(db, account_id)
        try:
            audit_service.record(db, "auth.logout", actor_id=account_id, target_type="admin_account", target_id=account_id, ip=address, user_agent=user_agent)
            db.commit()
        except SQLAlchemyError as error:
            db.rollback()
            log.error("Logout of account %s was not written to the audit log: %s | at %s", account_id, safe_error_text(error), where_it_happened(error))
            db.query(AdminSession).filter(AdminSession.id == session_id, AdminSession.revoked_at.is_(None)).update(
                {AdminSession.revoked_at: clock()}, synchronize_session=False
            )
            forget_after_commit(db, account_id)
            db.commit()
        ended = account_id
    forget_session(session_id)
    return ended


def end_logins(db: Session, account_id: int):
    """Ends every login of an account, on every device. The caller commits, and they end at the commit."""
    db.query(AdminSession).filter(AdminSession.account_id == account_id, AdminSession.revoked_at.is_(None)).update(
        {AdminSession.revoked_at: clock()}, synchronize_session=False
    )
    forget_after_commit(db, account_id)


def change_password(db: Session, actor: Actor, current_password: str, new_password: str):
    """Replaces an account's password and ends all its logins: the new password is needed everywhere."""
    now = clock()
    account = db.get(AdminAccount, actor.id)
    if account is None or account.status != "active":
        raise AuthError(401, SESSION_ENDED)
    if temporary_password_expired(account, now):
        # Its logins end with it; this answers one made in the seconds a login is remembered for.
        raise expired_temporary_password(account)
    # The current password is guarded like a login: a stolen session cannot be used to try them all.
    _refuse_if_locked(db, account.email, account, now)
    attempt_taken = _count_attempt(db, account.email)
    db.refresh(account)
    if not attempt_taken or not _password_matches(account, current_password or ""):
        error = _failed(db, account.email, account, now)
        raise error if error.status == 429 else AuthError(400, "The current password is incorrect.")
    account.failed_login_count = 0
    db.commit()
    check_new_password(new_password, account.email)
    if new_password == current_password:
        raise AuthError(400, "The new password must be different from the current one.")
    account.password_hash = password_service.hash_password(new_password)
    account.must_change_password = False
    account.temporary_password_expires_at = None
    end_logins(db, account.id)
    # Committed together: a changed password always has its audit entry, and if the entry cannot be
    # written the password stays as it was and the person is told it failed.
    audit_service.record(db, "auth.password_changed", actor_id=account.id, target_type="admin_account", target_id=account.id)
    db.commit()


# ---- accounts -----------------------------------------------------------------------------------

def clean_account_email(value: str) -> str:
    """The address as it is stored: valid, in small letters, short enough. Raises AuthError."""
    try:
        email = normalize_email(value or "").lower()
    except ValueError as error:
        raise AuthError(400, f"{error}.") from None
    limit = text_limit(AdminAccount, "email")
    if len(email) > limit:
        raise AuthError(400, f"Email must be at most {limit} characters.")
    return email


def clean_full_name(value: str) -> str:
    """The name as it is stored: spaces tidied, not empty, short enough. Raises AuthError."""
    name = " ".join((value or "").split())
    if not name or len(name) > text_limit(AdminAccount, "full_name"):
        raise AuthError(400, "Enter a full name (160 characters at most).")
    return name


def create_account(db: Session, email: str, full_name: str, password: str, role: str = "admin", must_change_password: bool = False,
                   created_by: int | None = None, temporary_password_expires_at: datetime | None = None) -> AdminAccount:
    """Adds a login account. The caller commits. Raises AuthError for anything that cannot be saved.

    The row is written (flushed) before this returns, so a clash with an account another request
    has just saved raises sqlalchemy's IntegrityError here; the caller rolls back.
    """
    email = clean_account_email(email)
    name = clean_full_name(full_name)
    if role not in ROLES:
        raise AuthError(400, "Role must be super_admin or admin.")
    if _find(db, email):
        raise AuthError(409, "An account with this email already exists.")
    check_new_password(password, email)
    account = AdminAccount(
        email=email, full_name=name, password_hash=password_service.hash_password(password), role=role,
        must_change_password=must_change_password, created_by=created_by, temporary_password_expires_at=temporary_password_expires_at,
    )
    db.add(account)
    db.flush()
    return account


def check_new_password(password: str, email: str):
    """Raises AuthError, with the reason, unless the password may be given to the account with this email."""
    try:
        password_service.check_password(password or "", email)
    except PasswordPolicyError as error:
        raise AuthError(400, f"{error}.") from None


def reset_password(db: Session, account: AdminAccount, password: str, must_change_password: bool = False, enable: bool = True,
                   temporary_password_expires_at: datetime | None = None):
    """Gives an account a new password, unlocks it (and enables it, unless enable is False) and ends its logins. The caller commits."""
    check_new_password(password, account.email)
    account.password_hash = password_service.hash_password(password)
    account.must_change_password = must_change_password
    account.temporary_password_expires_at = temporary_password_expires_at
    if enable:
        account.status = "active"
    account.failed_login_count = 0
    account.locked_until = None
    end_logins(db, account.id)
