from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, event, false, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

ROLES = ("super_admin", "admin")
STATUSES = ("active", "disabled")


class AdminAccount(Base):
    # The people who may log in to the console. This is not user_management: there, person_type
    # "admin" means a staff member whose attendance is taken, and none of those rows can log in.
    __tablename__ = "admin_accounts"
    __table_args__ = (
        CheckConstraint("role IN ('super_admin', 'admin')", name="ck_admin_accounts_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_admin_accounts_status"),
        # One account per address, however it is typed: the address is stored in small letters.
        CheckConstraint("email = lower(email)", name="ck_admin_accounts_email_lower"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 120 characters, so that it fits attendance_records.marked_by, where it is written.
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    # An Argon2id hash. The password itself is never stored, logged or sent back.
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default="admin", server_default="admin")
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Times are UTC without a time zone (app.utils.time_utils.utc_now), on SQLite and PostgreSQL alike.
    locked_until: Mapped[DateTime | None] = mapped_column(DateTime)
    last_login_at: Mapped[DateTime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    # Set while the account is on a temporary password that a super admin was shown (a new account,
    # or a reset in the portal): from this moment that password no longer works. Cleared when the
    # account chooses its own. Empty for a password chosen by its owner or on the command line.
    temporary_password_expires_at: Mapped[DateTime | None] = mapped_column(DateTime)
    # True from the moment the account is a super admin, and never false again, also after it is made
    # an admin. Whoever resets a password in the portal is shown the new one, so such an account is
    # given a new password on the server only (scripts/create_super_admin.py --force). Otherwise
    # making someone an admin first would be a way into their account. Set by _remember_super_admin.
    has_been_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


@event.listens_for(AdminAccount.role, "set")
def _remember_super_admin(account, value, _previous, _initiator):
    # Whenever the role becomes super_admin, whatever code sets it: a new account, a promotion, the
    # command-line tool. Nothing ever sets the flag back.
    if value == "super_admin":
        account.has_been_super_admin = True


class AdminSession(Base):
    # One row for each device an account is logged in on. Ending the row (logging out, disabling the
    # account, changing the password) ends that login, whatever the browser still holds.
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="CASCADE"), index=True)
    # SHA-256 of the refresh token. The token itself exists only in the browser's cookie.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[DateTime] = mapped_column(DateTime)
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime)
    last_used_at: Mapped[DateTime | None] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
