from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.time_utils import utc_now


class AuditLog(Base):
    # Who did what, and when. Rows are only ever added: no route changes or removes one. Written by
    # app/services/audit_service.py, which keeps passwords, tokens, hashes and face data out of details.
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_target", "target_type", "target_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # The account that acted. Empty for a failed login, which nobody has proved to be, and for the
    # command-line tool. Kept as empty if the account is ever deleted, so the row itself stays.
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    # UTC without a time zone, like every other time the backend writes (app.utils.time_utils.utc_now).
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=utc_now, server_default=func.now(), index=True)
