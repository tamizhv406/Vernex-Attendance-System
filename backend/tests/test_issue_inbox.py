"""The Super Admin side of issue reporting (IR-03, SA-03, SA-04): the inbox, one issue's page, status
changes and the resolution note, assigning, the open-issue badge and the dashboard's numbers.

The reporter's side is test_issues_api.py; who may reach which route, test_route_protection.py.
"""
import threading
import time as wall_clock
from datetime import date, datetime, time, timedelta, timezone
from itertools import permutations
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models.audit_log import AuditLog
from app.models.issue import STATUSES, Issue, IssueComment
from app.routes.paging import MAX_PAGE
from app.services import audit_service, auth_service, issue_service
from app.services.auth_service import Actor
from app.services.issue_service import IssueError

NOTE = "Replaced the USB cable of the scanner camera."


class Time:
    # The clock issues are reported and resolved by, moved instead of waited for. It starts long
    # before the real time, so tokens made with the real clock stay good however far it moves.
    def __init__(self, now=datetime(2026, 3, 11, 4, 30)):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **amount):
        self.now += timedelta(**amount)


@pytest.fixture()
def clock(monkeypatch):
    moved = Time()
    monkeypatch.setattr(auth_service, "clock", moved)
    return moved


@pytest.fixture()
def owner(signed_in):
    return signed_in("owner@example.com", role="super_admin", full_name="Olivia Owner")


@pytest.fixture()
def asha(signed_in):
    return signed_in("asha@example.com", full_name="Asha Example")


@pytest.fixture()
def ben(signed_in):
    return signed_in("ben@example.com", full_name="Ben Other")


def report(client, **changes):
    body = {"title": "The scanner froze", "description": "It stopped after the third face.", "category": "bug", "severity": "medium",
            "page_url": "/attendance-scanner", "device_info": {"browser": "Edge 141", "os": "Windows", "screen": "1366x768"}, **changes}
    answer = client.post("/issues", json=body)
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]["id"]


def change(owner, issue_id, **fields):
    return owner.put(f"/super-admin/issues/{issue_id}", json=fields)


def stored(client, issue_id):
    with client.db() as db:
        issue = db.get(Issue, issue_id)
        db.expunge(issue)
        return issue


def audited(client, action="issue.status_changed"):
    with client.db() as db:
        return [(row.actor_id, row.target_type, row.target_id, row.details) for row in db.query(AuditLog).filter_by(action=action).order_by(AuditLog.id)]


def inbox(owner, **params):
    answer = owner.get("/super-admin/issues", params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]


def titles(owner, **params):
    return [row["title"] for row in inbox(owner, **params)["items"]]


def local(day, hour=0, minute=0):
    """A time where the school is (DEFAULT_TIMEZONE), as the UTC the database keeps."""
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(settings.default_timezone)).astimezone(timezone.utc).replace(tzinfo=None)


# ---- the inbox ----------------------------------------------------------------------------------

def test_an_issue_an_admin_reports_is_in_the_inbox_with_who_reported_it(owner, asha):
    issue = report(asha, title="Camera is black")

    data = inbox(owner)
    row = data["items"][0]
    assert (data["total"], row["id"], row["title"], row["status"]) == (1, issue, "Camera is black", "open")
    assert row["reporter"] == {"id": asha.account_id, "full_name": "Asha Example", "role": "admin", "email": "asha@example.com"}
    assert (row["assigned_to"], row["assignee"]) == (None, None)
    # A line of a list: no description and no thread.
    assert "description" not in row and "comments" not in row


@pytest.fixture()
def spread(owner, asha, ben, clock, make_issue):
    """Seven issues, one hour apart, from two reporters, in every status."""
    rows = [
        ("Login page loops", "login_access", "low", "open", asha),
        ("Wrong face matched", "face_recognition", "critical", "in_progress", ben),
        ("Totals are off", "attendance_data", "high", "resolved", asha),
        ("Camera is black", "camera_device", "critical", "open", ben),
        ("Typo on settings", "other", "low", "closed", asha),
        ("Export crashes", "bug", "medium", "open", asha),
        ("Late marked as absent", "attendance_data", "high", "in_progress", ben),
    ]
    with owner.db() as db:
        for number, (title, category, severity, status, who) in enumerate(rows):
            created = clock.now + timedelta(hours=number)
            make_issue(db, who.account_id, title=title, category=category, severity=severity, status=status, created_at=created, updated_at=created,
                       resolution_note=NOTE if status == "resolved" else None, resolved_at=created if status == "resolved" else None)
    return rows


def test_the_inbox_is_newest_first_and_without_a_status_filter_has_every_status(owner, spread):
    assert titles(owner) == [row[0] for row in reversed(spread)]
    assert inbox(owner)["total"] == 7


def test_open_and_in_progress_together_is_the_filter_the_console_starts_with(owner, spread):
    assert titles(owner, status="unresolved") == ["Late marked as absent", "Export crashes", "Camera is black", "Wrong face matched", "Login page loops"]


@pytest.mark.parametrize("status, expected", [
    ("open", ["Export crashes", "Camera is black", "Login page loops"]),
    ("in_progress", ["Late marked as absent", "Wrong face matched"]),
    ("resolved", ["Totals are off"]),
    ("closed", ["Typo on settings"]),
])
def test_the_inbox_filters_by_status(owner, spread, status, expected):
    assert titles(owner, status=status) == expected


def test_the_inbox_filters_by_severity_category_and_reporter(owner, asha, ben, spread):
    assert titles(owner, severity="critical") == ["Camera is black", "Wrong face matched"]
    assert titles(owner, category="attendance_data") == ["Late marked as absent", "Totals are off"]
    assert titles(owner, reporter_id=ben.account_id) == ["Late marked as absent", "Camera is black", "Wrong face matched"]
    # Together, every filter applies.
    assert titles(owner, reporter_id=asha.account_id, severity="high", category="attendance_data") == ["Totals are off"]
    assert titles(owner, reporter_id=asha.account_id, status="unresolved", severity="critical") == []
    assert titles(owner, reporter_id=999999) == []


def test_sorted_by_severity_the_critical_ones_come_first_and_the_newest_first_within_each(owner, spread):
    assert titles(owner, sort="severity") == ["Camera is black", "Wrong face matched", "Late marked as absent", "Totals are off",
                                             "Export crashes", "Typo on settings", "Login page loops"]
    assert titles(owner, sort="severity", status="unresolved")[:2] == ["Camera is black", "Wrong face matched"]


def test_the_inbox_filters_by_the_day_reported_in_the_schools_time_zone(owner, asha, make_issue):
    day = date(2026, 3, 11)
    with owner.db() as db:
        for title, moment in [("Before the day", local(day) - timedelta(minutes=1)), ("First minute", local(day)),
                              ("Last minute", local(day, 23, 59)), ("The next day", local(day + timedelta(days=1)))]:
            make_issue(db, asha.account_id, title=title, created_at=moment)

    assert titles(owner, date_from="2026-03-11", date_to="2026-03-11") == ["Last minute", "First minute"]
    assert titles(owner, date_from="2026-03-12") == ["The next day"]
    assert titles(owner, date_to="2026-03-10") == ["Before the day"]


def test_the_inbox_comes_a_page_at_a_time(owner, asha, make_issue):
    with owner.db() as db:
        for number in range(30):
            make_issue(db, asha.account_id, title=f"Issue number {number:02d}", created_at=datetime(2026, 3, 1) + timedelta(minutes=number))

    first, second = inbox(owner), inbox(owner, page=2)
    small = inbox(owner, page_size=7, page=5)
    assert (len(first["items"]), first["total"], first["page"], first["page_size"]) == (25, 30, 1, 25)
    assert [row["title"] for row in second["items"]] == [f"Issue number {number:02d}" for number in range(4, -1, -1)]
    assert [row["title"] for row in small["items"]] == ["Issue number 01", "Issue number 00"]
    assert inbox(owner, page=9)["items"] == []


@pytest.mark.parametrize("params, message", [
    ({"status": "done"}, "Unknown status."),
    ({"severity": "urgent"}, "Unknown severity."),
    ({"category": "feature"}, "Unknown category."),
    ({"sort": "oldest"}, "Sort by newest or severity."),
    ({"date_from": "2026-03-12", "date_to": "2026-03-11"}, "The start date must not be after the end date."),
])
def test_a_filter_that_makes_no_sense_is_refused(owner, params, message):
    answer = owner.get("/super-admin/issues", params=params)

    assert (answer.status_code, answer.json()) == (400, {"detail": message})


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"reporter_id": "asha"}, {"date_from": "yesterday"},
                                    {"reporter_id": 0}, {"reporter_id": 2 ** 70}])
def test_a_page_or_value_of_the_wrong_kind_is_refused_without_repeating_it(owner, params):
    answer = owner.get("/super-admin/issues", params=params)

    assert answer.status_code == 422
    assert '"input"' not in answer.text and "yesterday" not in answer.text and "asha" not in answer.text and str(2 ** 70) not in answer.text


@pytest.mark.parametrize("issue_id", [0, 2 ** 31, 2 ** 70])
def test_an_issue_number_the_database_cannot_hold_is_refused_before_it_is_asked(owner, issue_id):
    answers = [owner.get(f"/super-admin/issues/{issue_id}"), change(owner, issue_id, status="closed"),
               owner.post(f"/super-admin/issues/{issue_id}/comments", json={"body": "Hello"})]

    assert [answer.status_code for answer in answers] == [422, 422, 422]


@pytest.mark.parametrize("assignee", [0, -5, 2 ** 31, 2 ** 70])
def test_an_assignee_number_the_database_cannot_hold_is_refused_before_it_is_asked(owner, asha, assignee):
    issue = report(asha)

    answer = change(owner, issue, assigned_to=assignee)

    assert answer.status_code == 422 and answer.json()["detail"][0]["loc"][-1] == "assigned_to"
    assert stored(owner, issue).assigned_to is None


# ---- one issue ----------------------------------------------------------------------------------

def test_the_page_of_an_issue_has_everything_about_it(owner, asha):
    issue = report(asha, title="Camera is black", description="Line one.\nLine two.", category="camera_device", severity="critical")
    asha.post(f"/issues/{issue}/comments", json={"body": "It is still black."})

    data = owner.get(f"/super-admin/issues/{issue}").json()["data"]

    assert (data["title"], data["description"], data["category"], data["severity"], data["status"]) == (
        "Camera is black", "Line one.\nLine two.", "camera_device", "critical", "open")
    assert (data["page_url"], data["device_info"]) == ("/attendance-scanner", {"browser": "Edge 141", "os": "Windows", "screen": "1366x768"})
    assert data["reporter"]["email"] == "asha@example.com"
    assert [(comment["body"], comment["author"]["full_name"]) for comment in data["comments"]] == [("It is still black.", "Asha Example")]


def test_an_issue_that_does_not_exist_is_not_found(owner):
    for answer in (owner.get("/super-admin/issues/999999"), change(owner, 999999, status="closed"),
                   owner.post("/super-admin/issues/999999/comments", json={"body": "Hello"})):
        assert (answer.status_code, answer.json()) == (404, {"detail": "Issue not found."})


def test_a_super_admin_reads_and_answers_every_admins_issue(owner, asha, ben):
    for client in (asha, ben):
        issue = report(client)
        assert owner.get(f"/super-admin/issues/{issue}").status_code == 200
        assert owner.post(f"/super-admin/issues/{issue}/comments", json={"body": "On it."}).status_code == 200
        assert change(owner, issue, status="in_progress").status_code == 200


# ---- status, resolution note and resolved_at (D1, D2) -------------------------------------------

def test_an_issue_goes_from_open_to_resolved_to_closed_and_back(owner, asha, clock):
    issue = report(asha)

    clock.advance(hours=1)
    assert change(owner, issue, status="in_progress").json()["data"]["resolved_at"] is None

    clock.advance(hours=1)
    resolving = change(owner, issue, status="resolved", resolution_note=f"  {NOTE}  ")
    resolved_at = clock.now
    assert resolving.status_code == 200
    assert (stored(owner, issue).status, stored(owner, issue).resolved_at, stored(owner, issue).resolution_note) == ("resolved", resolved_at, NOTE)
    assert resolving.json()["data"]["resolved_at"] == resolved_at.isoformat() + "Z"

    # Closing a resolved issue keeps when it was resolved.
    clock.advance(hours=1)
    change(owner, issue, status="closed")
    assert (stored(owner, issue).status, stored(owner, issue).resolved_at) == ("closed", resolved_at)

    # Opened again: no longer resolved, but the note stays, to start from next time.
    clock.advance(hours=1)
    change(owner, issue, status="open")
    assert (stored(owner, issue).status, stored(owner, issue).resolved_at, stored(owner, issue).resolution_note) == ("open", None, NOTE)

    # Resolving again asks for a note again, and gets a new time.
    assert change(owner, issue, status="resolved").status_code == 422
    clock.advance(hours=1)
    change(owner, issue, status="resolved", resolution_note="Swapped the camera itself.")
    assert (stored(owner, issue).resolved_at, stored(owner, issue).resolution_note) == (clock.now, "Swapped the camera itself.")


@pytest.mark.parametrize("before, after", list(permutations(STATUSES, 2)))
def test_any_status_may_follow_any_other(owner, asha, make_issue, before, after):
    with owner.db() as db:
        issue = make_issue(db, asha.account_id, status=before, resolution_note=NOTE if before == "resolved" else None,
                           resolved_at=datetime(2026, 3, 1) if before in ("resolved", "closed") else None).id

    answer = change(owner, issue, status=after, **({"resolution_note": NOTE} if after == "resolved" else {}))

    assert answer.status_code == 200, answer.text
    saved = stored(owner, issue)
    assert saved.status == after
    if after in ("open", "in_progress"):
        assert saved.resolved_at is None
    elif after == "resolved":
        assert saved.resolved_at is not None and saved.resolved_at != datetime(2026, 3, 1)
    else:
        # Closed: what resolved_at was stays as it was (kept after a resolution, empty otherwise).
        assert saved.resolved_at == (datetime(2026, 3, 1) if before in ("resolved", "closed") else None)


def test_closing_an_issue_that_was_never_resolved_leaves_it_without_a_resolution_time(owner, asha):
    issue = report(asha)

    change(owner, issue, status="in_progress")
    change(owner, issue, status="closed")

    assert (stored(owner, issue).status, stored(owner, issue).resolved_at) == ("closed", None)


@pytest.mark.parametrize("note", [None, "", "   ", "\n\t", "a" * 4001])
def test_resolving_without_a_note_of_1_to_4000_characters_is_refused(owner, asha, note):
    issue = report(asha)
    body = {"status": "resolved"} if note is None else {"status": "resolved", "resolution_note": note}

    answer = owner.put(f"/super-admin/issues/{issue}", json=body)

    assert answer.status_code == 422 and answer.json()["detail"][0]["loc"][-1] == "resolution_note"
    assert (stored(owner, issue).status, stored(owner, issue).resolved_at, stored(owner, issue).resolution_note) == ("open", None, None)
    assert audited(owner) == []


def test_a_note_of_4000_characters_resolves(owner, asha):
    issue = report(asha)

    assert change(owner, issue, status="resolved", resolution_note="n" * 4000).status_code == 200


@pytest.mark.parametrize("status", [None, "open", "in_progress", "closed"])
def test_a_resolution_note_goes_with_resolving_only(owner, asha, status):
    issue = report(asha)
    body = {"resolution_note": NOTE} if status is None else {"status": status, "resolution_note": NOTE}

    answer = owner.put(f"/super-admin/issues/{issue}", json=body)

    assert (answer.status_code, answer.json()["detail"][0]["msg"]) == (422, "A resolution note goes with resolving the issue.")
    assert stored(owner, issue).resolution_note is None


def test_the_note_of_a_resolved_issue_can_be_corrected_without_a_new_entry(owner, asha, clock):
    issue = report(asha)
    change(owner, issue, status="resolved", resolution_note=NOTE)
    resolved_at = stored(owner, issue).resolved_at

    clock.advance(hours=2)
    answer = change(owner, issue, resolution_note="Replaced the cable and the hub.")

    assert answer.status_code == 200
    assert (stored(owner, issue).resolution_note, stored(owner, issue).resolved_at) == ("Replaced the cable and the hub.", resolved_at)
    assert len(audited(owner)) == 1


def test_the_same_status_again_changes_nothing_and_writes_nothing(owner, asha, clock):
    issue = report(asha)
    before = stored(owner, issue).updated_at

    clock.advance(hours=1)
    answer = change(owner, issue, status="open")

    assert answer.status_code == 200
    assert stored(owner, issue).updated_at == before and audited(owner) == []


@pytest.mark.parametrize("status", ["done", "Resolved", "", "OPEN"])
def test_a_status_outside_the_list_is_refused_without_repeating_it(owner, asha, status):
    issue = report(asha)

    answer = owner.put(f"/super-admin/issues/{issue}", json={"status": status, "resolution_note": "private words 4421"})

    assert answer.status_code == 422 and "private words" not in answer.text and '"input"' not in answer.text
    assert stored(owner, issue).status == "open"


@pytest.mark.parametrize("field", ["title", "description", "reported_by", "resolved_at", "category"])
def test_a_super_admin_changes_status_note_and_assignee_only(owner, asha, field):
    issue = report(asha)

    answer = owner.put(f"/super-admin/issues/{issue}", json={field: 1})

    assert answer.status_code == 422 and answer.json()["detail"][0]["loc"][-1] == field


def test_the_reporter_sees_every_change_in_my_reports(owner, asha):
    issue = report(asha)

    change(owner, issue, status="in_progress")
    assert asha.get("/issues").json()["data"]["items"][0]["status"] == "in_progress"

    change(owner, issue, status="resolved", resolution_note=NOTE)
    mine = asha.get(f"/issues/{issue}").json()["data"]
    assert (mine["status"], mine["resolution_note"]) == ("resolved", NOTE) and mine["resolved_at"]

    # Opened again, the old note is no longer shown to the reporter.
    change(owner, issue, status="open")
    mine = asha.get(f"/issues/{issue}").json()["data"]
    assert (mine["status"], mine["resolution_note"], mine["resolved_at"]) == ("open", None, None)


# ---- the audit log (SA-04) ----------------------------------------------------------------------

def test_every_change_of_status_and_only_that_is_written_to_the_audit_log(owner, asha, signed_in):
    deputy = signed_in("deputy@example.com", role="super_admin")
    issue = report(asha)

    change(owner, issue, status="in_progress")
    change(owner, issue, assigned_to=deputy.account_id)
    owner.post(f"/super-admin/issues/{issue}/comments", json={"body": "Ordered a new cable."})
    change(owner, issue, status="resolved", resolution_note=NOTE)
    change(owner, issue, status="closed", assigned_to=None)

    assert audited(owner) == [
        (owner.account_id, "issue", issue, {"status": {"from": "open", "to": "in_progress"}}),
        (owner.account_id, "issue", issue, {"status": {"from": "in_progress", "to": "resolved"}}),
        (owner.account_id, "issue", issue, {"status": {"from": "resolved", "to": "closed"}}),
    ]
    with owner.db() as db:
        assert sorted({row.action for row in db.query(AuditLog)}) == ["issue.created", "issue.status_changed"]


def test_the_audit_log_names_the_issue_and_can_be_filtered_to_issues(owner, asha):
    issue = report(asha, title="Camera is black")
    change(owner, issue, status="in_progress")

    entries = owner.get("/super-admin/audit-logs", params={"target_type": "issue"}).json()["data"]["items"]

    assert [(entry["action_label"], entry["target_label"], entry["actor"]["email"]) for entry in entries] == [
        ("Issue status changed", f"#{issue} Camera is black", "owner@example.com"),
        ("Issue reported", f"#{issue} Camera is black", "asha@example.com"),
    ]
    actions = [item["action"] for item in owner.get("/super-admin/audit-logs/actions").json()["data"]]
    assert {"issue.created", "issue.status_changed"} <= set(actions)


def test_a_status_change_whose_entry_cannot_be_written_is_not_made(owner, asha, audit_breaks):
    issue = report(asha)
    audit_breaks("issue.status_changed")

    answer = change(owner, issue, status="resolved", resolution_note=NOTE, assigned_to=owner.account_id)

    assert answer.status_code == 500 and NOTE not in answer.text
    saved = stored(owner, issue)
    # Nothing of the request was kept: not the status, not the note, not the assignee.
    assert (saved.status, saved.resolved_at, saved.resolution_note, saved.assigned_to) == ("open", None, None, None)
    assert owner.get("/super-admin/issues/open-count").json()["data"]["count"] == 1


# ---- assigning ----------------------------------------------------------------------------------

def test_an_issue_is_assigned_to_an_active_super_admin_and_taken_off_them(owner, asha, signed_in):
    deputy = signed_in("deputy@example.com", role="super_admin", full_name="Dana Deputy")
    issue = report(asha)

    assigned = change(owner, issue, assigned_to=deputy.account_id).json()["data"]
    assert (assigned["assigned_to"], assigned["assignee"]) == (deputy.account_id, {"id": deputy.account_id, "full_name": "Dana Deputy", "role": "super_admin"})
    assert inbox(owner)["items"][0]["assignee"]["full_name"] == "Dana Deputy"

    change(owner, issue, assigned_to=owner.account_id)
    assert stored(owner, issue).assigned_to == owner.account_id

    cleared = change(owner, issue, assigned_to=None).json()["data"]
    assert (cleared["assigned_to"], cleared["assignee"]) == (None, None)
    # Its reporter is not told who has it.
    assert "assignee" not in asha.get(f"/issues/{issue}").json()["data"]


@pytest.mark.parametrize("who", ["an admin", "a disabled super admin", "nobody"])
def test_an_issue_cannot_be_assigned_to_anyone_but_an_active_super_admin(owner, asha, signed_in, who):
    target = {
        "an admin": lambda: asha.account_id,
        "a disabled super admin": lambda: signed_in("gone@example.com", role="super_admin", status="disabled").account_id,
        "nobody": lambda: 999999,
    }[who]()
    issue = report(asha)

    answer = change(owner, issue, assigned_to=target)

    assert (answer.status_code, answer.json()["detail"][0]["msg"]) == (422, "An issue can only be assigned to an active super admin.")
    assert stored(owner, issue).assigned_to is None


def test_a_refused_assignee_stops_the_whole_change(owner, asha):
    issue = report(asha)

    answer = change(owner, issue, status="in_progress", assigned_to=asha.account_id)

    assert answer.status_code == 422
    assert (stored(owner, issue).status, stored(owner, issue).assigned_to) == ("open", None) and audited(owner) == []


def test_a_closed_issue_can_still_be_assigned_and_opened_again(owner, asha):
    issue = report(asha)
    change(owner, issue, status="closed")

    assert change(owner, issue, assigned_to=owner.account_id, status="in_progress").status_code == 200
    assert (stored(owner, issue).status, stored(owner, issue).assigned_to) == ("in_progress", owner.account_id)


# ---- comments from the portal -------------------------------------------------------------------

def test_a_super_admin_comments_on_any_issue_except_a_closed_one(owner, asha):
    issue = report(asha)

    first = owner.post(f"/super-admin/issues/{issue}/comments", json={"body": "  Which camera?  "})
    change(owner, issue, status="closed")
    refused = owner.post(f"/super-admin/issues/{issue}/comments", json={"body": "Closing remark"})

    assert first.json()["data"]["body"] == "Which camera?" and first.json()["data"]["author"]["role"] == "super_admin"
    assert (refused.status_code, refused.json()) == (409, {"detail": "This issue is closed, so it takes no more comments."})
    assert [comment["body"] for comment in owner.get(f"/super-admin/issues/{issue}").json()["data"]["comments"]] == ["Which camera?"]


@pytest.mark.parametrize("body", ["", "  ", "c" * 4001])
def test_a_super_admins_comment_follows_the_same_rules(owner, asha, body):
    issue = report(asha)

    answer = owner.post(f"/super-admin/issues/{issue}/comments", json={"body": body})

    assert answer.status_code == 422 and answer.json()["detail"][0]["loc"][-1] == "body"


# ---- the badge ----------------------------------------------------------------------------------

def test_the_badge_counts_issues_that_are_open_or_in_progress(owner, asha, spread):
    assert owner.get("/super-admin/issues/open-count").json()["data"] == {"count": 5}

    issue = report(asha)
    assert owner.get("/super-admin/issues/open-count").json()["data"]["count"] == 6
    change(owner, issue, status="resolved", resolution_note=NOTE)
    assert owner.get("/super-admin/issues/open-count").json()["data"]["count"] == 5


def test_the_badge_is_zero_with_no_issues(owner):
    assert owner.get("/super-admin/issues/open-count").json()["data"] == {"count": 0}


# ---- the dashboard (SA-03) ----------------------------------------------------------------------

def dashboard(owner):
    return owner.get("/super-admin/dashboard").json()["data"]["issues"]


def test_the_dashboard_counts_open_issues_by_severity_and_lists_the_newest(owner, spread):
    issues = dashboard(owner)

    # open + in progress: critical 2, high 1, medium 1, low 1. Resolved and closed are not open.
    assert issues["open"] == {"total": 5, "low": 1, "medium": 1, "high": 1, "critical": 2}
    assert [row["title"] for row in issues["newest_open"]] == ["Late marked as absent", "Export crashes", "Camera is black",
                                                                "Wrong face matched", "Login page loops"]
    assert all(row["id"] and row["status"] in ("open", "in_progress") for row in issues["newest_open"])


def test_the_dashboard_lists_five_open_issues_at_most(owner, asha, make_issue):
    with owner.db() as db:
        for number in range(8):
            make_issue(db, asha.account_id, title=f"Issue number {number}", created_at=datetime(2026, 3, 1) + timedelta(minutes=number))

    assert [row["title"] for row in dashboard(owner)["newest_open"]] == [f"Issue number {number}" for number in (7, 6, 5, 4, 3)]
    assert dashboard(owner)["open"]["total"] == 8


def test_resolved_this_week_counts_monday_to_sunday_where_the_school_is(owner, asha, clock, make_issue):
    wednesday = date(2026, 3, 11)
    monday, next_monday = date(2026, 3, 9), date(2026, 3, 16)
    clock.now = local(wednesday, 10)
    resolved = {
        "the last minute of last week": local(monday) - timedelta(minutes=1),
        "the first minute of this week": local(monday),
        "Wednesday": local(wednesday, 9),
        "the last minute of Sunday": local(next_monday) - timedelta(minutes=1),
        "the first minute of next week": local(next_monday),
    }
    with owner.db() as db:
        for title, moment in resolved.items():
            make_issue(db, asha.account_id, title=title, status="resolved", resolution_note=NOTE, resolved_at=moment)
        # Closed after it was resolved this week: still resolved this week.
        make_issue(db, asha.account_id, title="closed after", status="closed", resolution_note=NOTE, resolved_at=local(wednesday, 8))
        # Closed without being resolved, and opened again: neither was resolved.
        make_issue(db, asha.account_id, title="closed as is", status="closed")
        make_issue(db, asha.account_id, title="opened again", status="open", resolution_note=NOTE)

    issues = dashboard(owner)

    assert issues["resolved_this_week"] == 4
    assert issues["week"] == {"from": "2026-03-09", "to": "2026-03-15"}


@pytest.mark.parametrize("now, week", [
    ((date(2026, 3, 15), 23, 59), {"from": "2026-03-09", "to": "2026-03-15"}),
    ((date(2026, 3, 16), 0, 0), {"from": "2026-03-16", "to": "2026-03-22"}),
    ((date(2026, 3, 9), 0, 0), {"from": "2026-03-09", "to": "2026-03-15"}),
])
def test_the_week_turns_at_midnight_between_sunday_and_monday_where_the_school_is(owner, clock, now, week):
    clock.now = local(*now)

    assert dashboard(owner)["week"] == week


def test_an_issue_resolved_through_the_portal_counts_this_week_and_leaves_the_open_ones(owner, asha, clock):
    clock.now = local(date(2026, 3, 11), 10)
    issue = report(asha, severity="high")
    assert (dashboard(owner)["open"]["high"], dashboard(owner)["resolved_this_week"]) == (1, 0)

    change(owner, issue, status="resolved", resolution_note=NOTE)

    assert (dashboard(owner)["open"]["high"], dashboard(owner)["resolved_this_week"], dashboard(owner)["newest_open"]) == (0, 1, [])


# ---- how far a list is paged --------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/issues", "/super-admin/issues"])
def test_the_last_page_that_may_be_asked_for_is_answered_and_the_next_one_refused(owner, path):
    last = owner.get(path, params={"page": MAX_PAGE})
    beyond = owner.get(path, params={"page": MAX_PAGE + 1})
    far_beyond = owner.get(path, params={"page": 10 ** 19})

    assert MAX_PAGE == 10_000
    assert (last.status_code, last.json()["data"]["items"], last.json()["data"]["page"]) == (200, [], MAX_PAGE)
    # Refused before the database is asked, which an offset this large would make fail.
    for answer in (beyond, far_beyond):
        assert answer.status_code == 422 and answer.json()["detail"][0]["loc"] == ["query", "page"]
        assert '"input"' not in answer.text and str(MAX_PAGE + 1) not in answer.text and str(10 ** 19) not in answer.text


# ---- two requests at the same moment ------------------------------------------------------------
# On a database file with real connections of their own, as two requests at the same moment have.
# SQLite has no row locks: what these show is that the second request waits for the first to commit
# and then decides on what the first one saved (issue_service._held takes SQLite's database-wide write
# lock). PostgreSQL's row lock (SELECT ... FOR UPDATE) is the same promise, kept another way, and is
# not run here: how it waits, and that READ COMMITTED reads the row again after the wait, has to be
# checked on PostgreSQL itself. The test after these only shows that the PostgreSQL query asks for it.

@pytest.fixture()
def race(tmp_path, make_account, make_issue):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with sessions() as db:
        people = [make_account(db, email, role=role) for email, role in
                  [("owner@example.com", "super_admin"), ("deputy@example.com", "super_admin"), ("asha@example.com", "admin")]]
        sessions.actors = {account.email.split("@")[0]: Actor(account.id, account.email, account.full_name, account.role, False, 1) for account in people}
        sessions.issue = make_issue(db, sessions.actors["asha"].id).id
    yield sessions
    engine.dispose()


def acting(sessions, who, work, outcomes, label=None):
    """Runs work(db, actor) as one request of its own; records label (or the refusal's status) when it is done."""
    with sessions() as db:
        actor = sessions.actors[who]
        db.info["actor"] = actor  # as app/security.py does for a request
        try:
            work(db, actor)
            outcomes.append(label or "done")
        except IssueError as error:
            outcomes.append(error.status)


def run_together(*jobs):
    threads = [threading.Thread(target=job) for job in jobs]
    [thread.start() for thread in threads]
    [thread.join(timeout=60) for thread in threads]
    assert not any(thread.is_alive() for thread in threads)


def test_two_status_changes_at_the_same_moment_are_made_one_after_the_other(race, monkeypatch):
    recording = audit_service.record

    def slowly(db, action, **fields):
        # Between reading the status and committing: long enough for the other request to read it too.
        recording(db, action, **fields)
        wall_clock.sleep(0.3)

    monkeypatch.setattr(audit_service, "record", slowly)
    gate, outcomes = threading.Barrier(2), []

    def to(who, status):
        def job():
            gate.wait()
            acting(race, who, lambda db, actor: issue_service.update(db, actor, race.issue, status=status), outcomes)
        return job

    run_together(to("owner", "in_progress"), to("deputy", "closed"))

    with race() as db:
        changes = [row.details["status"] for row in db.query(AuditLog).filter_by(action="issue.status_changed").order_by(AuditLog.id)]
        final = db.get(Issue, race.issue).status
    # Each change starts from the status the other one saved: never two changes "from open".
    assert outcomes == ["done", "done"]
    assert changes[0]["from"] == "open" and changes[1]["from"] == changes[0]["to"] and final == changes[1]["to"]
    assert {changes[0]["to"], changes[1]["to"]} == {"in_progress", "closed"}


def test_a_comment_sent_while_the_issue_is_being_closed_waits_and_is_refused(race, monkeypatch):
    recording, closing = audit_service.record, threading.Event()

    def slowly(db, action, **fields):
        recording(db, action, **fields)
        closing.set()
        wall_clock.sleep(0.5)

    monkeypatch.setattr(audit_service, "record", slowly)
    outcomes = []

    def close():
        acting(race, "owner", lambda db, actor: issue_service.update(db, actor, race.issue, status="closed"), outcomes, "closed")

    def comment():
        closing.wait(10)
        acting(race, "asha", lambda db, actor: issue_service.comment_on_own(db, actor, race.issue, "Still broken"), outcomes, "commented")

    run_together(close, comment)

    # The comment waited for the close to be saved, then saw the issue closed.
    assert sorted(outcomes, key=str) == [409, "closed"]
    with race() as db:
        assert db.query(IssueComment).count() == 0 and db.get(Issue, race.issue).status == "closed"


def test_an_issue_closed_while_a_comment_is_being_saved_is_closed_after_it(race, monkeypatch):
    cleaning, commenting = issue_service.clean_comment, threading.Event()

    def slowly(value):
        # Inside the comment's request, after it found the issue open.
        commenting.set()
        wall_clock.sleep(0.5)
        return cleaning(value)

    monkeypatch.setattr(issue_service, "clean_comment", slowly)
    outcomes = []

    def comment():
        acting(race, "asha", lambda db, actor: issue_service.comment_on_own(db, actor, race.issue, "Still broken"), outcomes, "commented")

    def close():
        commenting.wait(10)
        acting(race, "owner", lambda db, actor: issue_service.update(db, actor, race.issue, status="closed"), outcomes, "closed")

    run_together(comment, close)

    # Never a comment saved on an issue that was already closed: the close waited for the comment to
    # be saved, and only then changed the issue. Had it not waited, it would have been saved during the
    # comment's pause, and the comment, saved after it, would have left its own time on the issue.
    assert sorted(outcomes) == ["closed", "commented"]
    with race() as db:
        saved = db.query(IssueComment).one()
        issue = db.get(Issue, race.issue)
        assert (saved.body, issue.status) == ("Still broken", "closed")
        assert issue.updated_at - saved.created_at >= timedelta(seconds=0.4)


@pytest.mark.parametrize("dialect, locked", [("postgresql", True), ("sqlite", False)])
@pytest.mark.parametrize("reporter_id", [None, 7])
def test_on_postgresql_the_issue_is_read_with_a_row_lock_and_on_sqlite_after_the_write_lock(dialect, locked, reporter_id):
    # A stand-in for a session: it only records what it is asked to run. Nothing connects anywhere.
    asked, found = [], object()
    session = SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name=dialect)),
                              execute=lambda statement: asked.append(statement) or SimpleNamespace(scalar_one_or_none=lambda: found))

    assert issue_service._held(session, 5, reporter_id=reporter_id) is found

    *before, query = asked
    sql = " ".join(str(query.compile(dialect=postgresql.dialect())).split())
    assert sql.endswith("FOR UPDATE") == locked
    assert ("issues.reported_by =" in sql) == (reporter_id is not None)
    # SQLite: the write that changes nothing comes first, so the read happens under the write lock.
    assert [str(statement) for statement in before] == ([] if locked else ["UPDATE issues SET status = status WHERE id < 0"])


def test_an_issue_that_does_not_exist_or_is_someone_elses_is_not_found_when_held(race):
    with race() as db:
        with pytest.raises(IssueError) as missing:
            issue_service._held(db, 999)
        with pytest.raises(IssueError) as others:
            issue_service._held(db, race.issue, reporter_id=race.actors["owner"].id)

    assert (missing.value.status, others.value.status) == (404, 404)
