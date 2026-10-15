"""Problems reported from the console (IR-01 to IR-04): what anyone who is logged in reports and
follows in My reports, and what a super admin does with every report in the portal's inbox.

Who is asking is always the Actor of the request's login: nothing here takes a reporter, an author
or (from a reporter) a status from what the browser sent. A report and a change of status are each
committed once, together with their row in the audit log. Assigning an issue and commenting are not
audited: the task sheet's list (SA-04) names neither. What people type is kept as typed, apart from
the trimming below, and the console shows it as plain text only.
"""
import re
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.admin_account import AdminAccount
from app.models.issue import CATEGORIES, SEVERITIES, STATUSES, UNRESOLVED, Issue, IssueComment
from app.serializers import issue_row_data
from app.services import audit_service, auth_service
from app.services.auth_service import Actor

# (shortest, longest) in characters, once the text is trimmed. frontend/src/lib/issues.js has the same.
TITLE_LENGTH = (5, 120)
DESCRIPTION_LENGTH = (10, 4000)
COMMENT_LENGTH = (1, 4000)
NOTE_LENGTH = (1, 4000)
PAGE_LENGTH = 255
DEVICE_FIELDS = ("browser", "os", "screen")
DEVICE_LENGTH = 100
# The inbox's own status filter: open and in progress together, which is what the badge counts.
UNRESOLVED_FILTER = "unresolved"
SORTS = ("newest", "severity")
NEWEST_ON_DASHBOARD = 5

NOT_FOUND = "Issue not found."
CLOSED = "This issue is closed, so it takes no more comments."
NOTE_NEEDED = "Write a resolution note to resolve this issue: what was done, or why nothing needs to be."
NOTE_WITHOUT_RESOLVING = "A resolution note goes with resolving the issue."
NOT_ASSIGNABLE = "An issue can only be assigned to an active super admin."
PAGE_NOT_A_PATH = "The page must be a path inside the console, like /dashboard."
UNKNOWN_DEVICE_FIELD = "Device information has a browser, an OS and a screen only."

# Control characters other than tab and line break. PostgreSQL refuses the NUL character in text
# outright; the others only ever arrive by accident, pasted from a terminal or a document.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# A path inside the console, as the address bar shows it ("/attendance-scanner"): never another site
# ("//host", "https://..."), a backslash, a query string or a fragment.
_PAGE = re.compile(r"/(?!/)[A-Za-z0-9/._~%-]*")
_SEVERITY_FIRST = case({"critical": 0, "high": 1, "medium": 2, "low": 3}, value=Issue.severity, else_=4)
_UNSET = object()


class IssueError(Exception):
    """A request that is refused: the HTTP status, the words for the person and, for a value that
    cannot be accepted, the field it was given for."""

    def __init__(self, status, message, field=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.field = field


def _now() -> datetime:
    # The clock of the logins (tests move it), so that a test can resolve an issue on a Sunday.
    return auth_service.clock()


def _after(previous, now) -> datetime:
    # A change is always later than the one before, even within one tick of the clock (about 15 ms
    # on Windows), so "last change" orders and compares the way it happened.
    return max(now, previous + timedelta(microseconds=1)) if previous else now


# ---- what is typed ------------------------------------------------------------------------------

def _text(value) -> str:
    # Several lines are kept as they were written, with one kind of line break.
    return _CONTROL.sub("", (value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def _line(value) -> str:
    return " ".join(_CONTROL.sub(" ", value or "").split())


def _within(field, text, limits, what) -> str:
    shortest, longest = limits
    if not shortest <= len(text) <= longest:
        raise IssueError(422, f"{what} must be {shortest} to {longest} characters long." if shortest > 1
                         else f"{what} must be at most {longest} characters long, and not empty.", field)
    return text


def clean_title(value) -> str:
    return _within("title", _line(value), TITLE_LENGTH, "The title")


def clean_description(value) -> str:
    return _within("description", _text(value), DESCRIPTION_LENGTH, "The description")


def clean_comment(value) -> str:
    return _within("body", _text(value), COMMENT_LENGTH, "A comment")


def clean_note(value) -> str:
    return _within("resolution_note", _text(value), NOTE_LENGTH, "The resolution note")


def clean_page(value) -> str | None:
    if value is None or value == "":
        return None
    if len(value) > PAGE_LENGTH or not _PAGE.fullmatch(value):
        raise IssueError(422, PAGE_NOT_A_PATH, "page_url")
    return value


def clean_device(info) -> dict | None:
    """The browser, the OS and the screen, each a short line, or None if none of them was given."""
    if not info:
        return None
    if not isinstance(info, dict) or set(info) - set(DEVICE_FIELDS):
        raise IssueError(422, UNKNOWN_DEVICE_FIELD, "device_info")
    kept = {}
    for field in DEVICE_FIELDS:
        text = _line(str(info[field])) if info.get(field) is not None else ""
        if len(text) > DEVICE_LENGTH:
            raise IssueError(422, f"The device's {field} must be at most {DEVICE_LENGTH} characters long.", "device_info")
        if text:
            kept[field] = text
    return kept or None


def _one_of(field, value, allowed):
    if value not in allowed:
        raise IssueError(422, f"The {field} must be one of: {', '.join(allowed)}.", field)
    return value


def _statuses(value) -> tuple:
    # A filter of a list: one status, or open and in progress together.
    if value == UNRESOLVED_FILTER:
        return UNRESOLVED
    if value not in STATUSES:
        raise IssueError(400, "Unknown status.")
    return (value,)


def _page_of(query, page: int, page_size: int):
    return query.offset((page - 1) * page_size).limit(page_size)


def _held(db: Session, issue_id: int, reporter_id: int | None = None) -> Issue:
    """The issue, read so that no other request can change it before this one commits: a change of
    status, or a comment, is decided on the issue as it is now, not as it was a moment ago.

    As admin_service._active_super_admins_held does for the last super admin: PostgreSQL locks the
    row (SELECT ... FOR UPDATE), and a request that waited reads it again and sees the change. SQLite
    has no row locks, so a write that changes nothing takes its database-wide write lock first, held
    until the commit: a second request waits there and then reads what the first one saved.
    reporter_id: only the issue this account reported, as own_issue asks.
    """
    query = select(Issue).where(Issue.id == issue_id)
    if reporter_id is not None:
        query = query.where(Issue.reported_by == reporter_id)
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update()
    else:
        db.execute(text("UPDATE issues SET status = status WHERE id < 0"))
    issue = db.execute(query.execution_options(populate_existing=True)).scalar_one_or_none()
    if issue is None:
        raise IssueError(404, NOT_FOUND)
    return issue


# ---- reporting, and following one's own reports -------------------------------------------------

def report(db: Session, actor: Actor, *, title, description, category, severity, page_url=None, device_info=None) -> Issue:
    """A new open issue, reported by the account that is logged in. Saved with its audit entry, or not at all."""
    now = _now()
    issue = Issue(
        title=clean_title(title),
        description=clean_description(description),
        category=_one_of("category", category, CATEGORIES),
        severity=_one_of("severity", severity, SEVERITIES),
        page_url=clean_page(page_url),
        device_info=clean_device(device_info),
        status="open",
        reported_by=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(issue)
    db.flush()  # its id, for the audit entry
    audit_service.record(db, "issue.created", target_type="issue", target_id=issue.id,
                         details={"title": issue.title, "category": issue.category, "severity": issue.severity})
    db.commit()
    return issue


def own_issue(db: Session, actor: Actor, issue_id: int) -> Issue:
    # The owner is part of the question asked of the database, so an issue someone else reported and
    # one that does not exist get the very same answer.
    issue = db.query(Issue).filter(Issue.id == issue_id, Issue.reported_by == actor.id).one_or_none()
    if issue is None:
        raise IssueError(404, NOT_FOUND)
    return issue


def own_issues(db: Session, actor: Actor, status: str | None = None, page: int = 1, page_size: int = 25):
    """One page of the issues this account reported, newest first. Returns (issues, how many there are)."""
    query = db.query(Issue).filter(Issue.reported_by == actor.id)
    if status:
        query = query.filter(Issue.status.in_(_statuses(status)))
    total = query.count()
    return _page_of(query.order_by(Issue.created_at.desc(), Issue.id.desc()), page, page_size).all(), total


def comments_of(db: Session, issue: Issue) -> list:
    return (db.query(IssueComment).options(selectinload(IssueComment.author))
            .filter(IssueComment.issue_id == issue.id).order_by(IssueComment.created_at, IssueComment.id).all())


def _comment(db: Session, actor: Actor, issue: Issue, body) -> IssueComment:
    # issue is held (_held): an issue closed at this moment is either closed before this looks, and
    # the comment is refused, or closed after this comment is saved.
    if issue.status == "closed":
        raise IssueError(409, CLOSED)
    now = _now()
    comment = IssueComment(issue_id=issue.id, author_id=actor.id, body=clean_comment(body), created_at=now)
    issue.updated_at = _after(issue.updated_at, now)
    db.add(comment)
    db.commit()
    return comment


def comment_on_own(db: Session, actor: Actor, issue_id: int, body) -> IssueComment:
    return _comment(db, actor, _held(db, issue_id, reporter_id=actor.id), body)


# ---- the inbox (super admins) -------------------------------------------------------------------

def find(db: Session, issue_id: int) -> Issue:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise IssueError(404, NOT_FOUND)
    return issue


def inbox(db: Session, *, status=None, severity=None, category=None, reporter_id=None, since=None, before=None,
          sort="newest", page=1, page_size=25):
    """One page of every issue, filtered. since and before are UTC moments, on the time of the report.
    sort: "newest", or "severity" (critical first, the newest first within each). Returns (issues, how many match)."""
    if sort not in SORTS:
        raise IssueError(400, "Sort by newest or severity.")
    query = db.query(Issue)
    if status:
        query = query.filter(Issue.status.in_(_statuses(status)))
    if severity:
        if severity not in SEVERITIES:
            raise IssueError(400, "Unknown severity.")
        query = query.filter(Issue.severity == severity)
    if category:
        if category not in CATEGORIES:
            raise IssueError(400, "Unknown category.")
        query = query.filter(Issue.category == category)
    if reporter_id is not None:
        query = query.filter(Issue.reported_by == reporter_id)
    if since is not None:
        query = query.filter(Issue.created_at >= since)
    if before is not None:
        query = query.filter(Issue.created_at < before)
    total = query.count()
    order = [Issue.created_at.desc(), Issue.id.desc()]
    if sort == "severity":
        order.insert(0, _SEVERITY_FIRST)
    rows = _page_of(query.options(selectinload(Issue.reporter), selectinload(Issue.assignee)).order_by(*order), page, page_size).all()
    return rows, total


def comment(db: Session, actor: Actor, issue_id: int, body) -> IssueComment:
    return _comment(db, actor, _held(db, issue_id), body)


def _assignable(db: Session, account_id: int):
    account = db.get(AdminAccount, account_id)
    if account is None or account.role != "super_admin" or account.status != "active":
        raise IssueError(422, NOT_ASSIGNABLE, "assigned_to")


def update(db: Session, actor: Actor, issue_id: int, *, status=None, resolution_note=None, assigned_to=_UNSET) -> Issue:
    """Changes what is given of the status, the resolution note and who has the issue. Any status may
    follow any other. Resolving needs a note, sent with it; resolved_at is set then, kept when a
    resolved issue is closed and cleared when it is opened again (its note stays, for next time). A
    change of status is saved with its audit entry, or not at all. Nothing changed, nothing written.
    The issue is held (_held) from here to the commit, so the status it changes from, and the one the
    audit entry names, is the one saved last, also when two super admins change it at the same moment."""
    issue = _held(db, issue_id)
    before = issue.status
    after = _one_of("status", status, STATUSES) if status is not None else before
    note = None
    if resolution_note is not None:
        if after != "resolved":
            raise IssueError(422, NOTE_WITHOUT_RESOLVING, "resolution_note")
        note = clean_note(resolution_note)
    if after == "resolved" and before != "resolved" and note is None:
        raise IssueError(422, NOTE_NEEDED, "resolution_note")
    assigning = assigned_to is not _UNSET and assigned_to != issue.assigned_to
    if assigning and assigned_to is not None:
        _assignable(db, assigned_to)

    changed = False
    if assigning:
        issue.assigned_to = assigned_to
        changed = True
    if note is not None and note != issue.resolution_note:
        issue.resolution_note = note
        changed = True
    now = _now()
    if after != before:
        issue.status = after
        if after == "resolved":
            issue.resolved_at = now
        elif after in UNRESOLVED:
            issue.resolved_at = None
        audit_service.record(db, "issue.status_changed", target_type="issue", target_id=issue.id,
                             details={"status": {"from": before, "to": after}})
        changed = True
    if not changed:
        return issue
    issue.updated_at = _after(issue.updated_at, now)
    db.commit()
    return issue


def open_count(db: Session) -> int:
    return db.query(func.count(Issue.id)).filter(Issue.status.in_(UNRESOLVED)).scalar() or 0


# ---- the dashboard ------------------------------------------------------------------------------

def week_of(moment: datetime):
    """The week (Monday to Sunday, where the school is: DEFAULT_TIMEZONE) that a UTC moment falls in.
    Returns (Monday, Sunday, the UTC moment it starts, the UTC moment the next one starts)."""
    zone = ZoneInfo(settings.default_timezone)
    day = moment.replace(tzinfo=timezone.utc).astimezone(zone).date()
    monday = day - timedelta(days=day.weekday())
    start, end = (datetime.combine(first, time.min, tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)
                  for first in (monday, monday + timedelta(days=7)))
    return monday, monday + timedelta(days=6), start, end


def summary(db: Session) -> dict:
    """What the portal's dashboard says about issues. "Open" is open and in progress together."""
    counts = Counter(severity for (severity,) in db.query(Issue.severity).filter(Issue.status.in_(UNRESOLVED)))
    monday, sunday, start, end = week_of(_now())
    resolved = db.query(func.count(Issue.id)).filter(Issue.resolved_at >= start, Issue.resolved_at < end).scalar() or 0
    newest = (db.query(Issue).options(selectinload(Issue.reporter), selectinload(Issue.assignee)).filter(Issue.status.in_(UNRESOLVED))
              .order_by(Issue.created_at.desc(), Issue.id.desc()).limit(NEWEST_ON_DASHBOARD).all())
    return {
        "open": {"total": sum(counts.values()), **{severity: counts.get(severity, 0) for severity in SEVERITIES}},
        "resolved_this_week": resolved,
        "week": {"from": monday.isoformat(), "to": sunday.isoformat()},
        "newest_open": [issue_row_data(issue) for issue in newest],
    }
