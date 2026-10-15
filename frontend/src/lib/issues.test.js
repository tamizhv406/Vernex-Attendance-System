// Run with `npm test`. Issue reporting's rules: what the report form accepts, what it sends, what it
// attaches about the page and the device, the inbox's filters, the status form, and the addresses of
// one issue. The backend checks the same again (backend/tests/test_issues_api.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  BLANK_INBOX_FILTERS, BLANK_REPORT, CATEGORY_OPTIONS, DEVICE_MAX, INBOX_STATUS_OPTIONS, LIMITS, NOTE_NEEDED, OPEN_COUNT_INTERVAL_MS, SEVERITY_OPTIONS,
  STATUS_OPTIONS, UNRESOLVED, badgeText, browserName, canComment, characters, cleanLine, cleanText, commentError, deviceInfo, deviceText, fieldErrors,
  formFromIssue, inboxFilterError, inboxFiltered, inboxQuery, issueChanges, openSummary, pagePath, reportErrors, reportPayload, severityLabel, severityTone,
  showsResolution, statusLabel, statusTone, systemName, weekText
} from "./issues.js";
import { landingPage, screenFor } from "./auth.js";
import { detailLines, targetText } from "./portal.js";
import { ISSUE_PAGES, NAV_GROUPS, PAGES, PATH_TO_PAGE, ROUTES, isPortalPage, locationView, navGroupsFor, pathFor } from "../routes.js";

// The checkout may have either kind of line break; the patterns below expect "\n".
const backend = readFileSync(new URL("../../../backend/app/services/issue_service.py", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const models = readFileSync(new URL("../../../backend/app/models/issue.py", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const GOOD = { title: "The scanner froze", category: "bug", severity: "high", description: "It stopped after the third face." };
const ASHA = { id: 3, email: "asha@example.com", full_name: "Asha Example", role: "admin", status: "active", must_change_password: false };
const OWNER = { ...ASHA, id: 1, email: "owner@example.com", role: "super_admin" };

// ---- the same rules as the backend --------------------------------------------------------------

test("the form's limits are the backend's", () => {
  const limit = name => backend.match(new RegExp(`^${name} = \\((\\d+), (\\d+)\\)$`, "m")).slice(1).map(Number);

  assert.deepEqual(LIMITS, { title: limit("TITLE_LENGTH"), description: limit("DESCRIPTION_LENGTH"), comment: limit("COMMENT_LENGTH"), note: limit("NOTE_LENGTH") });
  assert.deepEqual(LIMITS, { title: [5, 120], description: [10, 4000], comment: [1, 4000], note: [1, 4000] });
  assert.match(backend, new RegExp(`^DEVICE_LENGTH = ${DEVICE_MAX}$`, "m"));
  assert.match(backend, new RegExp(`^NOTE_NEEDED = "${NOTE_NEEDED.replace(/[.:]/g, "\\$&")}"$`, "m"));
});

test("the categories, severities and statuses are the database's", () => {
  const tuple = name => models.match(new RegExp(`^${name} = \\((.*)\\)$`, "m"))[1].split(", ").map(value => value.replace(/"/g, ""));

  assert.deepEqual(CATEGORY_OPTIONS.map(option => option.value), tuple("CATEGORIES"));
  assert.deepEqual(SEVERITY_OPTIONS.map(option => option.value), tuple("SEVERITIES"));
  assert.deepEqual(STATUS_OPTIONS.map(option => option.value), tuple("STATUSES"));
  assert.deepEqual([statusLabel("in_progress"), severityLabel("critical"), statusLabel("unknown")], ["In progress", "Critical", "unknown"]);
  assert.deepEqual(STATUS_OPTIONS.map(option => statusTone(option.value)), ["info", "warning", "success", "neutral"]);
  assert.deepEqual(SEVERITY_OPTIONS.map(option => severityTone(option.value)), ["neutral", "info", "warning", "danger"]);
});

test("the badge and the inbox ask again every 45 seconds, inside the task sheet's 30 to 60", () => {
  assert.equal(OPEN_COUNT_INTERVAL_MS, 45000);
});

// ---- the report form ----------------------------------------------------------------------------

test("a title of 5 to 120 characters and a description of 10 to 4000 are accepted, trimmed", () => {
  for (const [title, description] of [["abcde", "a".repeat(10)], ["a".repeat(120), "a".repeat(4000)], ["   abcde   ", "  0123456789  "]]) {
    assert.deepEqual(reportErrors({ ...GOOD, title, description }), {}, `${title.length}/${description.length}`);
  }
});

test("too short or too long is refused, counted after trimming, with the backend's words", () => {
  const errors = form => reportErrors({ ...GOOD, ...form });

  assert.deepEqual(errors({ title: "abcd" }), { title: "The title must be 5 to 120 characters long." });
  assert.deepEqual(errors({ title: "  ab  cd  " }), {}); // "ab cd" is five characters
  assert.deepEqual(errors({ title: "   abcd   " }), { title: "The title must be 5 to 120 characters long." });
  assert.deepEqual(errors({ title: "a".repeat(121) }), { title: "The title must be 5 to 120 characters long." });
  assert.deepEqual(errors({ description: "a".repeat(9) }), { description: "The description must be 10 to 4000 characters long." });
  assert.deepEqual(errors({ description: ` ${"a".repeat(9)}\n ` }), { description: "The description must be 10 to 4000 characters long." });
  assert.deepEqual(errors({ description: "a".repeat(4001) }), { description: "The description must be 10 to 4000 characters long." });
  assert.deepEqual(Object.keys(reportErrors(BLANK_REPORT)), ["title", "category", "description"]);
});

test("an emoji counts as one character, as the backend counts it", () => {
  const face = "\u{1F600}";

  assert.equal(characters(face.repeat(5)), 5);
  assert.deepEqual(reportErrors({ ...GOOD, title: face.repeat(120) }), {});
  assert.deepEqual(Object.keys(reportErrors({ ...GOOD, title: face.repeat(121) })), ["title"]);
});

test("a category and a severity must come from the lists", () => {
  assert.deepEqual(reportErrors({ ...GOOD, category: "", severity: "urgent" }), { category: "Choose a category.", severity: "Choose a severity." });
  for (const option of CATEGORY_OPTIONS) assert.deepEqual(reportErrors({ ...GOOD, category: option.value }), {});
  for (const option of SEVERITY_OPTIONS) assert.deepEqual(reportErrors({ ...GOOD, severity: option.value }), {});
});

test("the title becomes one line and the description keeps its lines, without control characters", () => {
  assert.equal(cleanLine("  two\nlines\tand   spaces  "), "two lines and spaces");
  assert.equal(cleanLine("Bell\u0007 rang"), "Bell rang");
  assert.equal(cleanText("  line one\r\nline two\rline three  "), "line one\nline two\nline three");
  assert.equal(cleanText("A NUL\u0000 is dropped, a tab\tstays"), "A NUL is dropped, a tab\tstays");
});

test("what is sent names no reporter and carries the page and the device", () => {
  const sent = reportPayload({ ...GOOD, title: "  The   scanner froze ", description: " It stopped.\r\nTwice. " }, { page: "/attendance-scanner", device: { browser: "Edge 141" } });

  assert.deepEqual(sent, { title: "The scanner froze", description: "It stopped.\nTwice.", category: "bug", severity: "high", page_url: "/attendance-scanner", device_info: { browser: "Edge 141" } });
  assert.deepEqual(Object.keys(sent).sort(), ["category", "description", "device_info", "page_url", "severity", "title"]);
  assert.deepEqual([reportPayload(GOOD).page_url, reportPayload(GOOD, { device: {} }).device_info], [null, null]);
});

test("the page attached is the path only, never the query string, the fragment or another site", () => {
  for (const path of ["/", "/dashboard", "/users/students", "/my-reports/12", "/a-b_c.d~e%20f", `/${"a".repeat(254)}`]) {
    assert.equal(pagePath(path), path, path);
  }
  for (const path of ["", "dashboard", "//evil.example/x", "https://evil.example", "/dash board", "/dash\\board", "/dashboard?email=a@b.c", "/dashboard#top", `/${"a".repeat(255)}`, null, undefined]) {
    assert.equal(pagePath(path), null, String(path));
  }
  // The backend accepts exactly these: the same pattern in both places.
  assert.ok(backend.includes('re.compile(r"/(?!/)[A-Za-z0-9/._~%-]*")'));
});

const AGENTS = {
  edge: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0",
  chromeAndroid: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.58 Mobile Safari/537.36",
  safariIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
  chromeIphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0.6723.90 Mobile/15E148 Safari/604.1",
  firefoxMac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1; rv:132.0) Gecko/20100101 Firefox/132.0",
  safariIpad: "Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
  samsung: "Mozilla/5.0 (Linux; Android 13; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
  chromebook: "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
};

test("the browser and the OS are named from the user agent", () => {
  const named = agent => [browserName(agent), systemName(agent)];

  assert.deepEqual(named(AGENTS.edge), ["Edge 141", "Windows"]);
  assert.deepEqual(named(AGENTS.chromeAndroid), ["Chrome 130", "Android 14"]);
  assert.deepEqual(named(AGENTS.safariIphone), ["Safari 17", "iOS 17.1"]);
  assert.deepEqual(named(AGENTS.chromeIphone), ["Chrome 130", "iOS 17.1"]);
  assert.deepEqual(named(AGENTS.firefoxMac), ["Firefox 132", "macOS"]);
  assert.deepEqual(named(AGENTS.safariIpad), ["Safari 16", "iPadOS 16.6"]);
  assert.deepEqual(named(AGENTS.samsung), ["Samsung Internet 23", "Android 13"]);
  assert.deepEqual(named(AGENTS.chromebook), ["Chrome 130", "ChromeOS"]);
  assert.deepEqual(named("curl/8.4.0"), ["", ""]);
  assert.equal(systemName("", "Windows"), "Windows");
});

test("the device attached is three short lines and nothing else about the device", () => {
  assert.deepEqual(deviceInfo({ userAgent: AGENTS.edge }, { width: 1920, height: 1080 }), { browser: "Edge 141", os: "Windows", screen: "1920x1080" });
  // Not the user-agent string itself, nor anything else the browser offers.
  assert.deepEqual(Object.keys(deviceInfo({ userAgent: AGENTS.edge, language: "en", cookieEnabled: true }, { width: 390, height: 844, colorDepth: 24 })), ["browser", "os", "screen"]);
  assert.deepEqual(deviceInfo({}, null), {});
  assert.deepEqual(deviceInfo({ userAgent: "curl/8.4.0" }, { width: 0, height: 0 }), {});
  assert.equal(deviceInfo({ userAgentData: { platform: "x".repeat(300) } }).os.length, DEVICE_MAX);
  assert.equal(deviceText({ browser: "Edge 141", os: "Windows", screen: "1920x1080" }), "Edge 141 · Windows · 1920x1080");
  assert.equal(deviceText({}), "Not recorded");
});

test("a refusal that names a field puts its words next to that field only", () => {
  const refused = { payload: { detail: [{ loc: ["body", "title"], msg: "The title must be 5 to 120 characters long." }, { loc: ["body", "page_url"], msg: "Bad page" }] } };

  assert.deepEqual(fieldErrors(refused, ["title", "description"]), { title: "The title must be 5 to 120 characters long." });
  assert.deepEqual(fieldErrors({ payload: { detail: "Issue not found." } }, ["title"]), {});
  assert.deepEqual(fieldErrors(null, ["title"]), {});
});

// ---- comments -----------------------------------------------------------------------------------

test("a comment is 1 to 4000 characters, and a closed issue takes none", () => {
  assert.equal(commentError("a"), "");
  assert.equal(commentError("a".repeat(4000)), "");
  assert.equal(commentError("   "), "A comment must be at most 4000 characters long, and not empty.");
  assert.equal(commentError("a".repeat(4001)), "A comment must be at most 4000 characters long, and not empty.");
  assert.deepEqual(STATUS_OPTIONS.map(option => canComment({ status: option.value })), [true, true, true, false]);
  assert.equal(canComment(null), false);
});

// ---- the status form ----------------------------------------------------------------------------

const OPEN = { id: 7, status: "open", resolution_note: null, resolved_at: null, assigned_to: null };

test("resolving asks for a note, and sends it with the status", () => {
  assert.deepEqual(issueChanges(OPEN, { status: "resolved", note: "  ", assignee: "" }), { errors: { note: NOTE_NEEDED }, body: { status: "resolved" } });
  assert.deepEqual(issueChanges(OPEN, { status: "resolved", note: "a".repeat(4001), assignee: "" }).errors, { note: "The resolution note must be at most 4000 characters long, and not empty." });
  assert.deepEqual(issueChanges(OPEN, { status: "resolved", note: " Replaced the cable. ", assignee: "" }), { errors: {}, body: { status: "resolved", resolution_note: "Replaced the cable." } });
});

test("an issue opened again must be given a note again when it is resolved, even the same one", () => {
  const reopened = { ...OPEN, resolution_note: "Replaced the cable." };

  assert.deepEqual(formFromIssue(reopened), { status: "open", note: "Replaced the cable.", assignee: "" });
  assert.deepEqual(issueChanges(reopened, { ...formFromIssue(reopened), status: "resolved" }).body, { status: "resolved", resolution_note: "Replaced the cable." });
});

test("only what changed is sent, and no note with any other status", () => {
  const resolved = { ...OPEN, status: "resolved", resolution_note: "Replaced the cable.", resolved_at: "2026-03-11T04:30:00Z", assigned_to: 1 };

  assert.deepEqual(issueChanges(resolved, formFromIssue(resolved)), { errors: {}, body: {} });
  assert.deepEqual(issueChanges(resolved, { ...formFromIssue(resolved), note: "Replaced the cable and the hub." }).body, { resolution_note: "Replaced the cable and the hub." });
  assert.deepEqual(issueChanges(resolved, { ...formFromIssue(resolved), status: "closed" }).body, { status: "closed" });
  assert.deepEqual(issueChanges(resolved, { ...formFromIssue(resolved), status: "in_progress", note: "edited" }).body, { status: "in_progress" });
  assert.deepEqual(issueChanges(OPEN, { status: "open", note: "", assignee: "4" }).body, { assigned_to: 4 });
  assert.deepEqual(issueChanges(resolved, { ...formFromIssue(resolved), assignee: "" }).body, { assigned_to: null });
});

test("the resolution note is shown once an issue is resolved, and not after it is opened again", () => {
  assert.equal(showsResolution({ resolved_at: "2026-03-11T04:30:00Z", resolution_note: "Fixed." }), true);
  assert.equal(showsResolution({ resolved_at: null, resolution_note: "An old note." }), false);
  assert.equal(showsResolution({ resolved_at: "2026-03-11T04:30:00Z", resolution_note: null }), false);
});

// ---- the inbox ----------------------------------------------------------------------------------

test("the inbox starts with open and in progress together, and all statuses are one choice away", () => {
  assert.equal(BLANK_INBOX_FILTERS.status, UNRESOLVED);
  assert.deepEqual(INBOX_STATUS_OPTIONS.slice(0, 2).map(option => option.label), ["Open + in progress", "All statuses"]);
  assert.deepEqual(inboxQuery(BLANK_INBOX_FILTERS), { page: 1, page_size: 25, sort: "newest", status: "unresolved" });
  assert.deepEqual(inboxQuery({ ...BLANK_INBOX_FILTERS, status: "all" }), { page: 1, page_size: 25, sort: "newest" });
});

test("the inbox asks only for the filters that are set", () => {
  const filters = { status: "resolved", severity: "critical", category: "bug", reporter: "3", from: "2026-03-01", to: "2026-03-31", sort: "severity" };

  assert.deepEqual(inboxQuery(filters, 2), { page: 2, page_size: 25, sort: "severity", status: "resolved", severity: "critical", category: "bug", reporter_id: "3", date_from: "2026-03-01", date_to: "2026-03-31" });
  assert.equal(inboxFiltered(BLANK_INBOX_FILTERS), false);
  assert.equal(inboxFiltered({ ...BLANK_INBOX_FILTERS, sort: "severity" }), false);
  assert.equal(inboxFiltered({ ...BLANK_INBOX_FILTERS, status: "all" }), true);
  assert.equal(inboxFilterError({ from: "2026-03-12", to: "2026-03-11" }), "The start date must not be after the end date.");
  assert.equal(inboxFilterError({ from: "2026-03-11", to: "2026-03-11" }), "");
});

test("the badge shows a count, 99+ past 99, and nothing for none", () => {
  assert.deepEqual([badgeText(0), badgeText(null), badgeText(3), badgeText(99), badgeText(100)], ["", "", "3", "99", "99+"]);
});

test("the dashboard names the open issues by severity and the week it counts", () => {
  assert.equal(openSummary({ total: 4, critical: 2, high: 1, medium: 0, low: 1 }), "2 critical · 1 high · 0 medium · 1 low");
  assert.equal(weekText({ from: "2026-03-09", to: "2026-03-15" }, "en-GB"), "Mon 9 Mar – Sun 15 Mar");
  assert.equal(weekText(null), "");
});

test("issue entries of the audit log read as words", () => {
  assert.deepEqual(detailLines({ title: "Camera is black", category: "camera_device", severity: "critical" }), ["Title: Camera is black", "Category: Camera or device", "Severity: Critical"]);
  assert.deepEqual(detailLines({ status: { from: "in_progress", to: "resolved" } }), ["Status: In progress → Resolved"]);
  assert.equal(targetText({ target_type: "issue", target_id: 7 }), "Issue #7");
});

// ---- addresses ----------------------------------------------------------------------------------

test("My reports is a console page for every account, under System", () => {
  assert.equal(ROUTES.myReports, "/my-reports");
  assert.equal(PAGES.myReports.roles, undefined);
  assert.equal(isPortalPage("myReports"), false);
  assert.deepEqual(NAV_GROUPS.find(group => group.label === "System").items, ["myReports", "settings"]);
  for (const account of [ASHA, OWNER]) {
    assert.ok(navGroupsFor(account.role, "dashboard").flatMap(group => group.items).includes("myReports"));
    assert.deepEqual(screenFor({ state: "in", account, page: "myReports", pages: PAGES }), { screen: "page", page: "myReports" });
  }
});

test("one issue has an address of its own, under My reports and under the portal's Issues", () => {
  assert.deepEqual(ISSUE_PAGES, ["myReports", "portalIssues"]);
  assert.deepEqual(locationView("/my-reports/12"), { page: "myReports", issueId: 12 });
  assert.deepEqual(locationView("/super-admin/issues/7"), { page: "portalIssues", issueId: 7 });
  assert.deepEqual(locationView("/my-reports"), { page: "myReports", issueId: null });
  assert.deepEqual(locationView("/dashboard"), { page: "dashboard", issueId: null });
  assert.deepEqual([pathFor("myReports", 12), pathFor("portalIssues", 7), pathFor("myReports"), pathFor("dashboard", 12), pathFor("nowhere")],
    ["/my-reports/12", "/super-admin/issues/7", "/my-reports", "/dashboard", "/dashboard"]);
  // Every plain address still means what it did.
  for (const [path, page] of Object.entries(PATH_TO_PAGE)) assert.deepEqual(locationView(path), { page, issueId: null });
});

test("anything else after the page is no issue, and leads to the start page", () => {
  for (const path of ["/my-reports/abc", "/my-reports/0", "/my-reports/012", "/my-reports/-1", "/my-reports/1.5", "/my-reports/12/x", "/my-reports/", "/my-reports/1234567890", "/courses/12", "/super-admin/admins/3"]) {
    assert.deepEqual(locationView(path), { page: "home", issueId: null }, path);
  }
});

// ---- the screens, read as source ----------------------------------------------------------------

const source = file => readFileSync(new URL(file, import.meta.url), "utf8");
const SCREENS = ["../pages/ReportProblem.jsx", "../pages/MyReports.jsx", "../pages/issueParts.jsx", "../pages/portal/Issues.jsx", "../pages/portal/PortalDashboard.jsx"];

test("what people typed is never handed to the page as HTML, anywhere in the app", () => {
  const everything = ["../main.jsx", "../layout.jsx", "../ui.jsx", ...SCREENS];

  for (const file of everything) {
    const code = source(file);
    assert.equal(/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(code), false, file);
  }
  // Descriptions, comments and resolution notes keep their line breaks as text.
  assert.match(source("../pages/issueParts.jsx"), /<p className=\{`whitespace-pre-wrap break-words/);
});

test("nothing an issue screen holds is kept in the browser or written to the console", () => {
  for (const file of [...SCREENS, "./issues.js"]) {
    const code = source(file);
    assert.equal(/\b(localStorage|sessionStorage|indexedDB)\s*[.[]|document\s*\.\s*cookie/.test(code), false, file);
    assert.equal(/console\.(log|info|warn|error|debug)\(/.test(code), false, file);
  }
});

test("Report a problem is on every page: in the header on large screens, under More on phones", () => {
  const layout = source("../layout.jsx");

  assert.match(layout, /<Button size="sm" variant="outline" icon=\{Flag\} className="hidden lg:inline-flex" onClick=\{onReport\}>Report a problem<\/Button>/);
  assert.match(layout, /onClick=\{\(\) => \{ onClose\(\); onReport\(\); \}\}>\s*<Flag size=\{17\} aria-hidden="true" \/>Report a problem/);
  // The shell carries it, and the console opens the dialog over whatever page is shown.
  assert.match(source("../main.jsx"), /<Shell [^>]*onReport=\{report\}/);
  assert.match(source("../main.jsx"), /\{reporting && <ReportProblem /);
});

test("the report dialog is a labelled modal that keeps the keyboard inside and attaches the page and device", () => {
  const dialog = source("../pages/ReportProblem.jsx");

  assert.match(dialog, /role="dialog" aria-modal="true" aria-labelledby=\{idOf\("heading"\)\} aria-describedby=\{idOf\("about"\)\}/);
  assert.match(dialog, /event\.key === "Escape"/);
  assert.match(dialog, /keepFocusIn\(event, dialogRef\.current\)/);
  assert.match(dialog, /pagePath\(location\.pathname\)/);
  assert.match(dialog, /deviceInfo\(navigator, screen\)/);
  assert.match(dialog, /reportPayload\(form, attached\)/);
});

test("the badge and the inbox poll with the 45-second interval, and only while they can be seen", () => {
  const parts = source("../pages/issueParts.jsx");

  assert.match(parts, /usePolling\(refresh, OPEN_COUNT_INTERVAL_MS, enabled\)/);
  assert.match(parts, /document\.visibilityState/);
  assert.match(source("../pages/portal/Issues.jsx"), /usePolling\(issues\.reload, OPEN_COUNT_INTERVAL_MS\)/);
  // Only while a super admin has a portal page open.
  assert.match(source("../main.jsx"), /useOpenIssueCount\(account\.role === "super_admin" && isPortalPage\(page\)\)/);
});

test("an admin who types an issue address of the portal is told it is not allowed", () => {
  const { page } = locationView("/super-admin/issues/7");

  assert.deepEqual(screenFor({ state: "in", account: ASHA, page, pages: PAGES }), { screen: "not-allowed", page: "portalIssues" });
  assert.deepEqual(screenFor({ state: "in", account: OWNER, page, pages: PAGES }), { screen: "page", page: "portalIssues" });
  assert.equal(landingPage({ wanted: "portalIssues", account: ASHA, pages: PAGES }), "dashboard");
});
