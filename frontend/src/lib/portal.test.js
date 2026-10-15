// Run with `npm test`. The Super Admin portal's rules: who reaches its pages, what its lists ask for,
// what the account screens offer, and how long a temporary password is held.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { landingPage, screenFor } from "./auth.js";
import {
  BLANK_ADMIN, BLANK_AUDIT_FILTERS, SUPER_ADMIN_RESET, TEMPORARY_PASSWORD_HOURS, accountActions, activeSuperAdmins, actorText, adminFormErrors, adminPayload, adminQuery, auditFilterError,
  auditQuery, changedFields, detailLines, expiredTemporaryPasswordHelp, formFromAccount, pageCount, rangeLabel, secretReducer, targetText, viewState, whenText
} from "./portal.js";
import { NAV_GROUPS, PAGES, PATH_TO_PAGE, PORTAL_MOBILE_NAV, PORTAL_NAV_GROUPS, ROUTES, isPortalPage, navEntry, navGroupsFor } from "../routes.js";

const OWNER = { id: 1, email: "owner@example.com", full_name: "Olivia Owner", role: "super_admin", status: "active", must_change_password: false };
const SECOND = { ...OWNER, id: 2, email: "second@example.com", full_name: "Second Owner" };
const ASHA = { id: 3, email: "asha@example.com", full_name: "Asha Example", role: "admin", status: "active", must_change_password: false };
const BEN = { ...ASHA, id: 4, email: "ben@example.com", full_name: "Ben Disabled", status: "disabled" };
const PORTAL = ["superAdmin", "portalAdmins", "portalIssues", "portalAudit"];

// ---- who reaches the portal ---------------------------------------------------------------------

test("the portal has its own four addresses under /super-admin", () => {
  assert.deepEqual(PORTAL.map(page => ROUTES[page]), ["/super-admin", "/super-admin/admins", "/super-admin/issues", "/super-admin/audit-log"]);
  for (const page of PORTAL) {
    assert.equal(PATH_TO_PAGE[ROUTES[page]], page);
    assert.deepEqual(PAGES[page].roles, ["super_admin"]);
    assert.equal(isPortalPage(page), true);
  }
  assert.equal(isPortalPage("dashboard"), false);
});

test("an admin who types a portal address is told it is not allowed, on every portal page", () => {
  for (const page of PORTAL) {
    assert.deepEqual(screenFor({ state: "in", account: ASHA, page, pages: PAGES }), { screen: "not-allowed", page });
    assert.deepEqual(screenFor({ state: "in", account: OWNER, page, pages: PAGES }), { screen: "page", page });
  }
  // Nor is an admin ever sent there after logging in, whatever was asked for.
  assert.equal(landingPage({ wanted: "portalAudit", account: ASHA, pages: PAGES }), "dashboard");
  assert.equal(landingPage({ wanted: "portalAudit", account: OWNER, pages: PAGES }), "portalAudit");
  assert.equal(landingPage({ wanted: null, account: OWNER, pages: PAGES }), "superAdmin");
});

test("a temporary password keeps a super admin out of the portal as well", () => {
  const view = screenFor({ state: "in", account: { ...OWNER, must_change_password: true }, page: "portalAdmins", pages: PAGES });

  assert.deepEqual(view, { screen: "change-password" });
});

test("inside the portal the navigation is the portal's, with the way back to the console last", () => {
  const groups = navGroupsFor("super_admin", "portalAdmins");

  assert.deepEqual(groups.map(group => group.items), [PORTAL, ["dashboard"]]);
  assert.deepEqual([navEntry("superAdmin", true).label, navEntry("dashboard", true).label], ["Dashboard", "Back to console"]);
  assert.deepEqual([navEntry("superAdmin", false).label, navEntry("dashboard", false).label], ["Super Admin", "Dashboard"]);
  assert.deepEqual([...PORTAL_MOBILE_NAV.left, ...PORTAL_MOBILE_NAV.right], PORTAL);
  assert.equal(PORTAL_MOBILE_NAV.center, null);
});

test("in the console a super admin has one way into the portal and an admin none", () => {
  const owner = navGroupsFor("super_admin", "dashboard").flatMap(group => group.items);
  const admin = navGroupsFor("admin", "dashboard").flatMap(group => group.items);

  assert.deepEqual(owner.filter(isPortalPage), ["superAdmin"]);
  assert.deepEqual(admin.filter(isPortalPage), []);
  assert.deepEqual(admin, NAV_GROUPS.flatMap(group => group.items).filter(page => !isPortalPage(page)));
  // Were an admin's screen ever drawn with a portal page, its navigation would still offer nothing of it.
  assert.deepEqual(navGroupsFor("admin", "portalAdmins").flatMap(group => group.items), ["dashboard"]);
  assert.ok(PORTAL_NAV_GROUPS.every(group => group.items.every(page => PAGES[page])));
});

// ---- the states of a list -----------------------------------------------------------------------

test("a list is loading, refused, broken, empty or ready, and says which", () => {
  const refused = Object.assign(new Error("Only a super admin can do this."), { status: 403 });
  const broken = Object.assign(new Error("Could not reach the server."), { status: 500 });

  assert.equal(viewState({ loading: true, error: null, items: null }), "loading");
  assert.equal(viewState({ loading: false, error: refused, items: [OWNER] }), "unauthorized");
  assert.equal(viewState({ loading: false, error: broken, items: null }), "error");
  assert.equal(viewState({ loading: false, error: null, items: [] }), "empty");
  assert.equal(viewState({ loading: false, error: null, items: [OWNER] }), "ready");
  // Reloading keeps what is on screen instead of blanking it.
  assert.equal(viewState({ loading: true, error: null, items: [OWNER] }), "ready");
});

// ---- the admin list -----------------------------------------------------------------------------

test("the list asks the backend only for the filters that are set", () => {
  assert.deepEqual(adminQuery(), {});
  assert.deepEqual(adminQuery({ search: "   ", status: "all", role: "all" }), {});
  assert.deepEqual(adminQuery({ search: "  asha ", status: "disabled", role: "super_admin" }), { search: "asha", status: "disabled", role: "super_admin" });
});

test("nobody is offered disabling, demoting or resetting themself", () => {
  const actions = accountActions(OWNER, OWNER, [OWNER, SECOND]);

  assert.deepEqual(actions.disable, { allowed: false, reason: "You cannot disable your own account." });
  assert.deepEqual(actions.changeRole, { allowed: false, reason: "You cannot change your own role." });
  assert.deepEqual(actions.reset, { allowed: false, reason: "Change your own password in Settings." });
  assert.equal(actions.edit.allowed, true);
});

test("the last active super admin is not offered for disabling or demoting", () => {
  // Signed in as a super admin whose own account was disabled a moment ago, looking at the only one left.
  const actions = accountActions(SECOND, { ...OWNER, id: 99 }, [SECOND]);

  assert.equal(activeSuperAdmins([SECOND, { ...OWNER, status: "disabled" }, ASHA]), 1);
  assert.deepEqual(actions.disable, { allowed: false, reason: "This is the last active super admin." });
  assert.deepEqual(actions.changeRole, { allowed: false, reason: "This is the last active super admin." });
  // Nor is a super admin's password reset here at all (see the next test).
  assert.deepEqual(actions.reset, { allowed: false, reason: SUPER_ADMIN_RESET });
});

test("only an admin's password is reset in the portal; a super admin's is reset on the server", () => {
  assert.deepEqual(accountActions(SECOND, OWNER, [OWNER, SECOND]).reset, { allowed: false, reason: SUPER_ADMIN_RESET });
  assert.deepEqual(accountActions(ASHA, OWNER, [OWNER]).reset, { allowed: true });
  assert.deepEqual(accountActions(BEN, OWNER, [OWNER]).reset, { allowed: true });
  assert.match(SUPER_ADMIN_RESET, /create_super_admin\.py --force/);
});

test("an admin who has ever been a super admin is not reset in the portal either", () => {
  // Made an admin first, then reset: that would be the way into a super admin's account.
  const former = { ...ASHA, id: 7, has_been_super_admin: true };

  assert.deepEqual(accountActions(former, OWNER, [OWNER]).reset, { allowed: false, reason: SUPER_ADMIN_RESET });
  // Everything else about the account is as for any admin.
  assert.deepEqual([accountActions(former, OWNER, [OWNER]).edit.allowed, accountActions(former, OWNER, [OWNER]).disable.allowed], [true, true]);
});

test("other accounts can be edited, reset, disabled, and enabled again", () => {
  const active = accountActions(ASHA, OWNER, [OWNER]);
  const disabled = accountActions(BEN, OWNER, [OWNER]);
  const otherOwner = accountActions(SECOND, OWNER, [OWNER, SECOND]);

  assert.deepEqual([active.edit.allowed, active.reset.allowed, active.disable.allowed, active.enable.allowed, active.changeRole.allowed], [true, true, true, false, true]);
  assert.deepEqual([disabled.disable.allowed, disabled.enable.allowed], [false, true]);
  assert.deepEqual([otherOwner.disable.allowed, otherOwner.changeRole.allowed], [true, true]);
});

// ---- the form -----------------------------------------------------------------------------------

test("the form says what is missing or wrong before anything is sent", () => {
  assert.deepEqual(adminFormErrors(BLANK_ADMIN), { email: "Enter the email address.", full_name: "Enter the full name." });
  assert.deepEqual(adminFormErrors({ email: "not an email", full_name: "Nia", role: "admin" }), { email: "Enter a valid email address." });
  assert.deepEqual(adminFormErrors({ email: `${"a".repeat(115)}@x.com`, full_name: "N".repeat(161), role: "owner" }), {
    email: "Use at most 120 characters.", full_name: "Use at most 160 characters.", role: "Choose a role." });
  assert.deepEqual(adminFormErrors({ email: "nia@example.com", full_name: "  Nia  Admin ", role: "super_admin" }), {});
});

test("what is sent is tidied: the email in small letters, the name's spaces closed up, and never a password", () => {
  const payload = adminPayload({ email: "  Nia@Example.COM ", full_name: "  Nia   Admin ", role: "admin", password: "chosen by me" });

  assert.deepEqual(payload, { email: "nia@example.com", full_name: "Nia Admin", role: "admin" });
});

test("an edit sends only what changed, so one's own role is never sent along with a new name", () => {
  const form = formFromAccount(OWNER);

  assert.deepEqual(changedFields(OWNER, form), {});
  assert.deepEqual(changedFields(OWNER, { ...form, full_name: " Olivia  Renamed " }), { full_name: "Olivia Renamed" });
  assert.deepEqual(changedFields(OWNER, { ...form, email: "OWNER@example.com" }), {});
  assert.deepEqual(changedFields(ASHA, { ...formFromAccount(ASHA), role: "super_admin", email: "asha.new@example.com" }), { email: "asha.new@example.com", role: "super_admin" });
});

// ---- the temporary password ---------------------------------------------------------------------

test("a temporary password is held from the answer until the dialog is closed, and then not at all", () => {
  let state = secretReducer(null, { type: "copied" });
  assert.equal(state, null);

  state = secretReducer(state, { type: "shown", email: "nia@example.com", password: "k7mx2p-q9trwa-h4bn8c", why: "created", expires: "2026-10-17T09:00:00Z" });
  assert.deepEqual(state, { email: "nia@example.com", password: "k7mx2p-q9trwa-h4bn8c", why: "created", expires: "2026-10-17T09:00:00Z", copied: false });
  assert.equal(TEMPORARY_PASSWORD_HOURS, 72);
  state = secretReducer(state, { type: "copied" });
  assert.equal(state.copied, true);
  state = secretReducer(state, { type: "dismissed" });

  assert.equal(state, null);
  assert.equal(JSON.stringify(state).includes("k7mx2p"), false);
});

test("expired temporary passwords: the dashboard names the server for super admins, never the portal", () => {
  assert.equal(expiredTemporaryPasswordHelp(0), null);
  assert.equal(expiredTemporaryPasswordHelp(undefined), null);
  const one = expiredTemporaryPasswordHelp(1);
  const two = expiredTemporaryPasswordHelp(2);

  assert.equal(one.detail, "1 expired: see below");
  assert.match(one.notice, /^1 temporary password has expired\. /);
  assert.match(two.notice, /^2 temporary passwords have expired\. /);
  for (const help of [one, two]) {
    // An admin: a reset in the portal. A current or former super admin: only the server tool.
    assert.match(help.notice, /For an admin, reset the password in Admins: that gives a new temporary password for 72 hours\./);
    assert.match(help.notice, /is or has been a super admin cannot be reset in the portal: .* on the server with scripts\\create_super_admin\.py --force\.$/);
    assert.doesNotMatch(help.notice, /ask (another )?a super admin/i);
  }
});

test("the dashboard card uses that guidance instead of telling everyone to reset in the portal", () => {
  const dashboard = readFileSync(new URL("../pages/portal/PortalDashboard.jsx", import.meta.url), "utf8");

  assert.match(dashboard, /expiredTemporaryPasswordHelp\(admins\?\.temporary_password_expired\)/);
  assert.match(dashboard, /<Notice tone="warning">\{expired\.notice\}<\/Notice>/);
  assert.equal(dashboard.includes("reset to give a new one"), false);
});

test("the password is never written anywhere a page could read it back, nor logged", () => {
  // api.js keeps one yes/no between page loads, and auth.test.js holds it to that.
  const files = ["./portal.js", "../pages/portal/Admins.jsx", "../pages/portal/shared.jsx", "../pages/portal/AuditLog.jsx", "../pages/portal/PortalDashboard.jsx"];

  for (const file of files) {
    const code = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.equal(/\b(localStorage|sessionStorage|indexedDB)\s*[.[]|document\s*\.\s*cookie/.test(code), false, file);
    assert.equal(/console\.(log|info|warn|error|debug)\(/.test(code), false, file);
  }
});

// ---- the audit log ------------------------------------------------------------------------------

test("the audit log asks for the filters that are set, one page at a time", () => {
  assert.deepEqual(auditQuery(BLANK_AUDIT_FILTERS), { page: 1, page_size: 25 });
  assert.deepEqual(auditQuery({ actor: "4", action: "admin.disabled", from: "2026-10-01", to: "2026-10-14" }, 3), {
    page: 3, page_size: 25, actor_id: "4", action: "admin.disabled", date_from: "2026-10-01", date_to: "2026-10-14" });
});

test("a start date after the end date is pointed out instead of asked for", () => {
  assert.equal(auditFilterError({ from: "2026-10-14", to: "2026-10-13" }), "The start date must not be after the end date.");
  assert.equal(auditFilterError({ from: "2026-10-13", to: "2026-10-13" }), "");
  assert.equal(auditFilterError({ from: "2026-10-13", to: "" }), "");
});

test("pages are counted and labelled", () => {
  assert.deepEqual([pageCount(0), pageCount(25), pageCount(26), pageCount(73)], [1, 1, 2, 3]);
  assert.deepEqual([rangeLabel(1, 25, 0), rangeLabel(1, 25, 7), rangeLabel(2, 25, 73), rangeLabel(3, 25, 73)], ["0 of 0", "1-7 of 7", "26-50 of 73", "51-73 of 73"]);
});

test("an entry is described in words: who, about what, and its details", () => {
  const updated = { actor: { id: 1, email: "owner@example.com", full_name: "Olivia Owner" }, actor_id: 1, target_type: "admin_account", target_id: 3, target_label: "asha@example.com",
    details: { role: { from: "admin", to: "super_admin" }, email: { from: "a@x.com", to: "b@x.com" } } };
  const failed = { actor: null, actor_id: null, target_type: null, target_id: null, target_label: null, details: { reason: "unknown_email" } };
  const tool = { actor: null, actor_id: null, target_type: "admin_account", target_id: 7, target_label: null, details: { via: "command line" } };

  assert.deepEqual([actorText(updated), actorText(failed), actorText(tool), actorText({ actor_id: 9 })], ["Olivia Owner", "Nobody signed in", "Command line", "Account #9"]);
  assert.deepEqual([targetText(updated), targetText(failed), targetText(tool)], ["asha@example.com", "-", "Account #7"]);
  assert.deepEqual(detailLines(updated.details), ["Role: Admin → Super admin", "Email: a@x.com → b@x.com"]);
  assert.deepEqual(detailLines(failed.details), ["Reason: Unknown email"]);
  assert.deepEqual(detailLines({ reason: "expired_temporary_password" }), ["Reason: Temporary password expired"]);
  assert.deepEqual(detailLines({ total_rows: 2, imported: 1, skipped: 0, kind: "courses" }), ["Rows: 2", "Imported: 1", "Skipped: 0", "File of: courses"]);
  assert.deepEqual(detailLines(null), []);
});

test("times from the backend are read as UTC and shown in the device's own zone", () => {
  const shown = whenText("2026-10-14T06:00:00Z", "en-GB");
  const expected = new Date(Date.UTC(2026, 9, 14, 6, 0)).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  assert.equal(shown, expected);
  assert.deepEqual([whenText(null), whenText("not a time")], ["-", "-"]);
});
