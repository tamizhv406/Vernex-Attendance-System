from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.admin_account import AdminAccount
from app.utils.time_utils import utc_now

CATEGORIES = ("bug", "face_recognition", "attendance_data", "camera_device", "login_access", "other")
SEVERITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "in_progress", "resolved", "closed")
# Still waiting for an answer: what the portal's badge and the dashboard count as open.
UNRESOLVED = ("open", "in_progress")


def one_of(column: str, values) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Issue(Base):
    # A problem reported from the console by an admin or a super admin (IR-01). reported_by is the
    # account that was logged in, never a value the browser sent. The app never deletes an issue,
    # and accounts are disabled rather than deleted, so a reporter cannot go while their issues stay.
    __tablename__ = "issues"
    __table_args__ = (
        CheckConstraint(one_of("category", CATEGORIES), name="ck_issues_category"),
        CheckConstraint(one_of("severity", SEVERITIES), name="ck_issues_severity"),
        CheckConstraint(one_of("status", STATUSES), name="ck_issues_status"),
        # A resolved issue says how it was resolved. A note left from an earlier resolution stays on
        # an issue that is opened again, so this only asks for one while the issue is resolved.
        CheckConstraint("status <> 'resolved' OR (resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0)",
                        name="ck_issues_resolution_note"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", index=True)
    # The page it was reported from, as a path inside the console ("/attendance-scanner"). Never a
    # whole address, a query string or a fragment: those can carry what was typed into a page.
    page_url: Mapped[str | None] = mapped_column(String(255))
    # {"browser", "os", "screen"}: short strings worked out by the browser, nothing else. None is SQL
    # NULL (none_as_null), not the JSON value null, so "IS NULL" finds a report without it.
    device_info: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    reported_by: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="RESTRICT"), index=True)
    # Only ever an active super admin when it is set (app/services/issue_service.py checks).
    assigned_to: Mapped[int | None] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="SET NULL"), index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    # UTC without a time zone, like every other time the backend writes (app.utils.time_utils.utc_now).
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=utc_now, server_default=func.now(), index=True)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, default=utc_now, server_default=func.now())
    # Set when the issue becomes resolved, kept when a resolved issue is closed, and cleared when it
    # is opened again. "Resolved this week" on the dashboard counts by it.
    resolved_at: Mapped[DateTime | None] = mapped_column(DateTime)

    reporter: Mapped[AdminAccount] = relationship(AdminAccount, foreign_keys=[reported_by])
    assignee: Mapped[AdminAccount | None] = relationship(AdminAccount, foreign_keys=[assigned_to])


class IssueComment(Base):
    # The thread under an issue, written by its reporter and by super admins. A comment is never
    # changed or removed: there is no route that does either.
    __tablename__ = "issue_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    issue_id: Mapped[int] = mapped_column(Integer, ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_accounts.id", ondelete="RESTRICT"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[DateTime] = mapped_column(DateTime, default=utc_now, server_default=func.now())

    author: Mapped[AdminAccount] = relationship(AdminAccount)
