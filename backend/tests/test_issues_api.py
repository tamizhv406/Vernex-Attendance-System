"""Reporting a problem and following it (IR-02, IR-04): what an admin, or a super admin, may do with
the issues they reported, and nothing more.

Who may reach these routes at all is walked route by route in test_route_protection.py. The inbox,
where a super admin reads and manages every issue, is test_issue_inbox.py.
"""
import pytest
from sqlalchemy import text

from app.main import app
from app.models.audit_log import AuditLog
from app.models.issue import Issue, IssueComment
from app.services import issue_service

GOOD = {
    "title": "The scanner froze",
    "description": "It stopped after the third face and showed a spinner.",
    "category": "bug",
    "severity": "high",
    "page_url": "/attendance-scanner",
    "device_info": {"browser": "Edge 141", "os": "Windows", "screen": "1920x1080"},
}
NOT_FOUND = {"detail": "Issue not found."}


@pytest.fixture()
def asha(signed_in):
    return signed_in("asha@example.com", full_name="Asha Example")


@pytest.fixture()
def ben(signed_in):
    return signed_in("ben@example.com", full_name="Ben Other")


@pytest.fixture()
def owner(signed_in):
    return signed_in("owner@example.com", role="super_admin", full_name="Olivia Owner")


def report(client, **changes):
    return client.post("/issues", json={**GOOD, **changes})


def reported(client, **changes):
    answer = report(client, **changes)
    assert answer.status_code == 200, answer.text
    return answer.json()["data"]


def saved(client, issue_id):
    with client.db() as db:
        issue = db.get(Issue, issue_id)
        if issue is not None:
            db.expunge(issue)
        return issue


def issue_count(client):
    with client.db() as db:
        return db.query(Issue).count()


def field_error(answer):
    """The field a 422 names, from the answer's list of problems."""
    assert answer.status_code == 422, answer.text
    return [problem["loc"][-1] for problem in answer.json()["detail"]]


# ---- reporting ----------------------------------------------------------------------------------

def test_an_admin_reports_a_problem_and_sees_it_open_in_my_reports(asha):
    issue = reported(asha)

    assert (issue["title"], issue["description"], issue["category"], issue["severity"], issue["status"]) == (
        GOOD["title"], GOOD["description"], "bug", "high", "open")
    assert issue["page_url"] == "/attendance-scanner" and issue["device_info"] == GOOD["device_info"]
    assert issue["resolved_at"] is None and issue["resolution_note"] is None and issue["comments"] == []
    assert issue["created_at"].endswith("Z")
    mine = asha.get("/issues").json()["data"]
    assert [(row["id"], row["status"]) for row in mine["items"]] == [(issue["id"], "open")] and mine["total"] == 1
    # Its reporter is never told who the issue is assigned to, nor sent their own account back.
    assert {"reporter", "assignee", "assigned_to"}.isdisjoint(issue) and {"reporter", "assignee", "assigned_to"}.isdisjoint(mine["items"][0])
    assert saved(asha, issue["id"]).reported_by == asha.account_id


def test_a_super_admin_can_report_a_problem_too(owner):
    issue = reported(owner, severity="critical")

    assert issue["status"] == "open" and saved(owner, issue["id"]).reported_by == owner.account_id


@pytest.mark.parametrize("claim", [{"reported_by": 999}, {"status": "resolved"}, {"assigned_to": 1}, {"resolution_note": "fixed"},
                                   {"resolved_at": "2026-01-01T00:00:00Z"}, {"id": 7}, {"created_at": "2020-01-01"}])
def test_who_reported_it_and_where_it_stands_are_never_taken_from_the_request(asha, ben, claim):
    answer = report(asha, **claim)

    assert field_error(answer) == [next(iter(claim))]
    assert issue_count(asha) == 0


def test_an_account_on_a_temporary_password_cannot_report(signed_in):
    newcomer = signed_in("new@example.com", must_change_password=True)

    assert report(newcomer).json() == {"detail": "Change your password before continuing."}
    assert issue_count(newcomer) == 0


# ---- what is checked ----------------------------------------------------------------------------

@pytest.mark.parametrize("title, kept", [
    ("abcde", "abcde"),
    ("   abcde   ", "abcde"),
    ("a" * 120, "a" * 120),
    ("two\nlines\tand   spaces", "two lines and spaces"),
    ("Bell\x07 rang", "Bell rang"),
])
def test_a_title_of_5_to_120_characters_is_kept_on_one_line(asha, title, kept):
    assert reported(asha, title=title)["title"] == kept


@pytest.mark.parametrize("title", ["abcd", "  abcd  ", "a" * 121, "", "     ", "\x00\x01\x02\x03\x04"])
def test_a_title_shorter_than_5_or_longer_than_120_characters_is_refused(asha, title):
    answer = report(asha, title=title)

    assert field_error(answer) == ["title"]
    assert answer.json()["detail"][0]["msg"] == "The title must be 5 to 120 characters long."
    assert issue_count(asha) == 0


@pytest.mark.parametrize("description, kept", [
    ("a" * 10, "a" * 10),
    ("a" * 4000, "a" * 4000),
    ("  line one\r\nline two\r\n  ", "line one\nline two"),
    ("tab\tkept and\nbreak kept", "tab\tkept and\nbreak kept"),
    ("A NUL\x00 is dropped here", "A NUL is dropped here"),
])
def test_a_description_of_10_to_4000_characters_keeps_its_lines(asha, description, kept):
    assert reported(asha, description=description)["description"] == kept


@pytest.mark.parametrize("description", ["a" * 9, "  " + "a" * 9 + "  ", "a" * 4001, "", "\x00" * 20])
def test_a_description_shorter_than_10_or_longer_than_4000_characters_is_refused(asha, description):
    answer = report(asha, description=description)

    assert field_error(answer) == ["description"]
    assert issue_count(asha) == 0


@pytest.mark.parametrize("field, value", [("category", "feature_request"), ("category", "Bug"), ("category", ""), ("severity", "urgent"),
                                          ("severity", "HIGH"), ("severity", None), ("category", None)])
def test_a_category_or_severity_outside_the_lists_is_refused(asha, field, value):
    assert field_error(report(asha, **{field: value})) == [field]
    assert issue_count(asha) == 0


@pytest.mark.parametrize("missing", ["title", "description", "category", "severity"])
def test_what_every_report_needs_cannot_be_left_out(asha, missing):
    body = {key: value for key, value in GOOD.items() if key != missing}

    assert field_error(asha.post("/issues", json=body)) == [missing]


@pytest.mark.parametrize("page", ["/", "/dashboard", "/users/students", "/my-reports/12", "/super-admin/issues", "/a-b_c.d~e%20f"])
def test_the_page_is_kept_when_it_is_a_path_inside_the_console(asha, page):
    assert reported(asha, page_url=page)["page_url"] == page


@pytest.mark.parametrize("page", [None, ""])
def test_a_report_without_a_page_has_none(asha, page):
    assert reported(asha, page_url=page)["page_url"] is None


@pytest.mark.parametrize("page", [
    "https://evil.example/login", "http://localhost:5173/dashboard", "//evil.example/x", "javascript:alert(1)", "dashboard",
    "/dash board", "/dash\\board", "/dashboard?email=asha@example.com", "/dashboard#top", "/" + "a" * 255, "/\x00", "/café",
    " /dashboard", "/dashboard\n",
])
def test_a_page_that_is_not_a_path_inside_the_console_is_refused(asha, page):
    answer = report(asha, page_url=page)

    assert field_error(answer) == ["page_url"]
    assert answer.json()["detail"][0]["msg"] == "The page must be a path inside the console, like /dashboard."
    assert issue_count(asha) == 0


def test_the_longest_page_kept_is_255_characters(asha):
    assert reported(asha, page_url="/" + "a" * 254)["page_url"] == "/" + "a" * 254


@pytest.mark.parametrize("device, kept", [
    ({"browser": "Edge 141", "os": "Windows", "screen": "1366x768"}, {"browser": "Edge 141", "os": "Windows", "screen": "1366x768"}),
    ({"browser": "Safari 17"}, {"browser": "Safari 17"}),
    ({"browser": "  Chrome\n 130 ", "os": "", "screen": None}, {"browser": "Chrome 130"}),
    ({"browser": "b" * 100}, {"browser": "b" * 100}),
    ({}, {}),
    (None, {}),
])
def test_device_information_is_three_short_lines_at_most(asha, device, kept):
    issue = reported(asha, device_info=device)

    assert issue["device_info"] == kept
    assert saved(asha, issue["id"]).device_info == (kept or None)


@pytest.mark.parametrize("device", [None, {}, {"browser": "", "os": None}])
def test_a_report_without_device_information_stores_sql_null(asha, device):
    issue = reported(asha, device_info=device)

    with asha.db() as db:
        empty = db.execute(text("SELECT device_info IS NULL FROM issues WHERE id = :id"), {"id": issue["id"]}).scalar()
    assert empty == 1 and issue["device_info"] == {}


@pytest.mark.parametrize("device", [{"browser": "b" * 101}, {"userAgent": "Mozilla/5.0"}, {"browser": "Edge", "cookies": "x"},
                                    {"browser": "x" * 501}, "Edge on Windows", ["Edge"], {"screen": 1920}])
def test_anything_else_as_device_information_is_refused(asha, device):
    assert field_error(report(asha, device_info=device))[0] in ("device_info", "browser", "userAgent", "cookies", "screen")
    assert issue_count(asha) == 0


def test_a_refused_report_does_not_repeat_what_was_typed(asha):
    marker = "private words typed into the form 7731"
    answers = [
        report(asha, description=marker, category="not-a-category"),
        report(asha, title=marker, unexpected=marker),
        asha.post("/issues", content=f'{{"title": "{marker}", "description": 5}}', headers={"Content-Type": "application/json"}),
        asha.post("/issues/1/comments", json={"body": marker, "author_id": 2}),
    ]

    for answer in answers:
        assert answer.status_code == 422
        assert marker not in answer.text and '"input"' not in answer.text and '"ctx"' not in answer.text


def test_script_and_html_are_kept_exactly_as_typed_and_never_turned_into_anything(asha):
    title = "<script>alert('x')</script>"
    description = '<img src=x onerror="alert(1)"> & <b>bold</b> "quoted" \'single\''
    issue = reported(asha, title=title, description=description)
    comment = asha.post(f"/issues/{issue['id']}/comments", json={"body": "<iframe src=//evil></iframe>"}).json()["data"]

    shown = asha.get(f"/issues/{issue['id']}").json()["data"]
    assert (shown["title"], shown["description"], shown["comments"][0]["body"]) == (title, description, "<iframe src=//evil></iframe>")
    assert comment["body"] == "<iframe src=//evil></iframe>"
    # A JSON answer, never a page a browser would draw.
    assert asha.get(f"/issues/{issue['id']}").headers["content-type"].startswith("application/json")


# ---- my reports ---------------------------------------------------------------------------------

def test_my_reports_lists_only_my_own_issues_newest_first(asha, ben, owner):
    first = reported(asha, title="First of mine")["id"]
    reported(ben, title="Ben's problem")
    reported(owner, title="The owner's own problem")
    second = reported(asha, title="Second of mine")["id"]

    mine = asha.get("/issues").json()["data"]
    assert [row["id"] for row in mine["items"]] == [second, first] and mine["total"] == 2
    assert [row["title"] for row in ben.get("/issues").json()["data"]["items"]] == ["Ben's problem"]
    # A super admin's own reports are theirs too; every issue is in the portal's inbox.
    assert [row["title"] for row in owner.get("/issues").json()["data"]["items"]] == ["The owner's own problem"]


def test_my_reports_come_a_page_at_a_time_and_by_status(asha, make_issue):
    with asha.db() as db:
        for number, status in enumerate(["open", "in_progress", "resolved", "closed", "open"]):
            make_issue(db, asha.account_id, title=f"Issue number {number}", status=status,
                       resolution_note="Done." if status == "resolved" else None)

    first = asha.get("/issues", params={"page_size": 2}).json()["data"]
    third = asha.get("/issues", params={"page_size": 2, "page": 3}).json()["data"]
    assert (len(first["items"]), first["total"], len(third["items"])) == (2, 5, 1)
    assert [row["status"] for row in asha.get("/issues", params={"status": "unresolved"}).json()["data"]["items"]] == ["open", "in_progress", "open"]
    assert asha.get("/issues", params={"status": "closed"}).json()["data"]["total"] == 1
    assert asha.get("/issues", params={"status": "done"}).json() == {"detail": "Unknown status."}
    assert asha.get("/issues", params={"page_size": 101}).status_code == 422


def test_the_reporter_sees_the_resolution_note_only_once_the_issue_has_been_resolved(asha, make_issue):
    with asha.db() as db:
        reopened = make_issue(db, asha.account_id, status="open", resolution_note="An earlier fix that did not hold.").id
        resolved = make_issue(db, asha.account_id, status="resolved", resolution_note="Replaced the camera cable.", resolved_at=issue_service._now()).id

    assert asha.get(f"/issues/{reopened}").json()["data"]["resolution_note"] is None
    assert asha.get(f"/issues/{resolved}").json()["data"]["resolution_note"] == "Replaced the camera cable."


# ---- someone else's issue (IR-04: the IDOR test) ------------------------------------------------

def test_an_admin_asking_for_another_admins_issue_is_told_it_does_not_exist(asha, ben):
    theirs = reported(ben)["id"]

    asked = asha.get(f"/issues/{theirs}")
    nonexistent = asha.get("/issues/999999")

    # The same answer as for an issue that does not exist, so the number tells nothing.
    assert (asked.status_code, asked.json()) == (404, NOT_FOUND)
    assert (nonexistent.status_code, nonexistent.json()) == (404, NOT_FOUND)
    assert asked.text == nonexistent.text


def test_an_admin_cannot_comment_on_another_admins_issue(asha, ben):
    theirs = reported(ben)["id"]

    answer = asha.post(f"/issues/{theirs}/comments", json={"body": "Mine now"})

    assert (answer.status_code, answer.json()) == (404, NOT_FOUND)
    with asha.db() as db:
        assert db.query(IssueComment).count() == 0


def test_an_admin_cannot_read_a_super_admins_issue_or_use_the_inbox(asha, owner):
    theirs = reported(owner)["id"]

    assert asha.get(f"/issues/{theirs}").json() == NOT_FOUND
    for method, path in [("GET", "/super-admin/issues"), ("GET", f"/super-admin/issues/{theirs}"), ("PUT", f"/super-admin/issues/{theirs}"),
                         ("POST", f"/super-admin/issues/{theirs}/comments"), ("GET", "/super-admin/issues/open-count")]:
        answer = asha.request(method, path, json={"status": "closed", "body": "x"})
        assert (answer.status_code, answer.json()) == (403, {"detail": "Only a super admin can do this."}), path
    assert saved(owner, theirs).status == "open"


@pytest.mark.parametrize("path, status", [("/issues/0", 422), ("/issues/-1", 422), ("/issues/abc", 422), ("/issues/1.5", 422),
                                          (f"/issues/{2 ** 31}", 422), (f"/issues/{2 ** 70}", 422), (f"/issues/{2 ** 31 - 1}", 404)])
def test_a_number_that_is_no_issues_is_refused_without_repeating_it(asha, path, status):
    # Too large for the database's id column: refused before the database is asked, which would fail.
    answer = asha.get(path)
    comment = asha.post(f"{path}/comments", json={"body": "Hello"})

    assert (answer.status_code, comment.status_code) == (status, status)
    for text in (answer.text, comment.text):
        assert '"input"' not in text and "abc" not in text and "1.5" not in text and str(2 ** 31) not in text


def every_route():
    # The application's own description of its routes. test_route_protection.py checks that it
    # lists exactly the routes the application answers.
    return sorted((method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations)


def test_nobody_can_change_or_remove_an_issue_or_a_comment_through_the_reporters_routes():
    issue_routes = [route for route in every_route() if route[1].startswith("/issues")]

    # Reading and adding only: the reporter never changes a status, and nothing is ever deleted.
    assert issue_routes == [("GET", "/issues"), ("GET", "/issues/{issue_id}"), ("POST", "/issues"), ("POST", "/issues/{issue_id}/comments")]


def test_no_route_deletes_an_issue_or_changes_a_comment():
    issue_routes = [route for route in every_route() if "issues" in route[1]]

    assert len(issue_routes) == 9
    assert not [route for route in issue_routes if route[0] in ("DELETE", "PATCH")]
    assert not [route for route in issue_routes if "comments" in route[1] and route[0] != "POST"]
    # The one route that changes an issue is the portal's, for super admins.
    assert [route for route in issue_routes if route[0] == "PUT"] == [("PUT", "/super-admin/issues/{issue_id}")]


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_a_reporter_trying_to_change_or_remove_their_issue_is_refused(asha, method):
    issue = reported(asha)["id"]

    assert asha.request(method, f"/issues/{issue}", json={"status": "resolved"}).status_code == 405
    assert saved(asha, issue).status == "open"


# ---- comments -----------------------------------------------------------------------------------

def test_the_reporter_comments_and_the_thread_is_kept_in_order(asha):
    issue = reported(asha)["id"]

    first = asha.post(f"/issues/{issue}/comments", json={"body": "  It happened again at 10:15.  "})
    asha.post(f"/issues/{issue}/comments", json={"body": "And once more.\r\nSecond line."})

    assert first.status_code == 200
    assert first.json()["data"]["author"] == {"id": asha.account_id, "full_name": "Asha Example", "role": "admin"}
    thread = asha.get(f"/issues/{issue}").json()["data"]["comments"]
    assert [comment["body"] for comment in thread] == ["It happened again at 10:15.", "And once more.\nSecond line."]


@pytest.mark.parametrize("body", ["a", "a" * 4000, " ok "])
def test_a_comment_of_1_to_4000_characters_is_kept(asha, body):
    issue = reported(asha)["id"]

    assert asha.post(f"/issues/{issue}/comments", json={"body": body}).json()["data"]["body"] == body.strip()


@pytest.mark.parametrize("body", ["", "   ", "\n\n", "a" * 4001, "\x00"])
def test_an_empty_comment_or_one_over_4000_characters_is_refused(asha, body):
    issue = reported(asha)["id"]

    assert field_error(asha.post(f"/issues/{issue}/comments", json={"body": body})) == ["body"]
    with asha.db() as db:
        assert db.query(IssueComment).count() == 0


def test_a_comment_is_always_signed_by_the_account_that_is_logged_in(asha, ben):
    issue = reported(asha)["id"]

    answer = asha.post(f"/issues/{issue}/comments", json={"body": "From Asha", "author_id": ben.account_id})

    assert field_error(answer) == ["author_id"]
    asha.post(f"/issues/{issue}/comments", json={"body": "From Asha"})
    with asha.db() as db:
        assert [(comment.author_id, comment.body) for comment in db.query(IssueComment)] == [(asha.account_id, "From Asha")]


def test_a_closed_issue_takes_no_more_comments_but_a_resolved_one_does(asha, make_issue):
    with asha.db() as db:
        closed = make_issue(db, asha.account_id, status="closed").id
        resolved = make_issue(db, asha.account_id, status="resolved", resolution_note="Fixed.", resolved_at=issue_service._now()).id

    refused = asha.post(f"/issues/{closed}/comments", json={"body": "Still broken"})
    accepted = asha.post(f"/issues/{resolved}/comments", json={"body": "Still broken"})

    assert (refused.status_code, refused.json()) == (409, {"detail": "This issue is closed, so it takes no more comments."})
    assert accepted.status_code == 200
    with asha.db() as db:
        assert [comment.issue_id for comment in db.query(IssueComment)] == [resolved]


def test_a_comment_marks_the_issue_as_updated(asha):
    issue = reported(asha)
    before = saved(asha, issue["id"]).updated_at

    asha.post(f"/issues/{issue['id']}/comments", json={"body": "One more thing."})

    assert saved(asha, issue["id"]).updated_at > before


def test_a_super_admins_reply_reaches_the_reporter(asha, owner):
    issue = reported(asha)["id"]

    owner.post(f"/super-admin/issues/{issue}/comments", json={"body": "Looking into it."})

    thread = asha.get(f"/issues/{issue}").json()["data"]["comments"]
    assert [(comment["body"], comment["author"]["full_name"], comment["author"]["role"]) for comment in thread] == [
        ("Looking into it.", "Olivia Owner", "super_admin")]
    assert "email" not in thread[0]["author"]


# ---- the audit log ------------------------------------------------------------------------------

def test_a_report_is_written_to_the_audit_log_with_who_made_it(asha):
    issue = reported(asha, title="Camera shows nothing", category="camera_device", severity="critical")

    with asha.db() as db:
        rows = [(row.action, row.actor_id, row.target_type, row.target_id, row.details) for row in db.query(AuditLog)]
    assert rows == [("issue.created", asha.account_id, "issue", issue["id"],
                     {"title": "Camera shows nothing", "category": "camera_device", "severity": "critical"})]


def test_comments_are_not_written_to_the_audit_log(asha):
    issue = reported(asha)["id"]

    asha.post(f"/issues/{issue}/comments", json={"body": "More detail."})

    with asha.db() as db:
        assert [row.action for row in db.query(AuditLog)] == ["issue.created"]


def test_a_report_whose_entry_cannot_be_written_is_not_saved(asha, audit_breaks):
    audit_breaks("issue.created")

    answer = report(asha)

    assert answer.status_code == 500 and GOOD["description"] not in answer.text
    assert issue_count(asha) == 0
    assert asha.get("/issues").json()["data"]["total"] == 0
