// The Super Admin portal's rules, kept apart from the screens so that they can be tested
// (portal.test.js). The backend checks all of this again; these only keep the screens from offering
// what would be refused, and say why.
import { CATEGORY_OPTIONS, SEVERITY_OPTIONS, STATUS_OPTIONS } from "./issues.js";

export const ROLE_OPTIONS = [
  { value: "admin", label: "Admin" },
  { value: "super_admin", label: "Super admin" }
];
export const MAX_NAME_LENGTH = 160;
export const MAX_EMAIL_LENGTH = 120;
export const AUDIT_PAGE_SIZE = 25;
export const TEMPORARY_PASSWORD_HOURS = 72;
// Whoever resets a password is shown the new one. The password of an account that is or has ever
// been a super admin (has_been_super_admin, also after it was made an admin) is reset on the server
// instead, so that no super admin can take over another's account (the backend refuses it too).
export const SUPER_ADMIN_RESET = "This account is or has been a super admin: its password is reset on the server, with scripts\\create_super_admin.py --force";

// What the dashboard says about temporary passwords that ran out, or null when none did. The way to
// a new one depends on the account, so both are said: a portal reset for an admin, the server for an
// account that is or has been a super admin (which the portal never resets).
export function expiredTemporaryPasswordHelp(count) {
  if (!count) return null;
  const which = count === 1 ? "1 temporary password has" : `${count} temporary passwords have`;
  return {
    detail: `${count} expired: see below`,
    notice: `${which} expired. For an admin, reset the password in Admins: that gives a new temporary password for ${TEMPORARY_PASSWORD_HOURS} hours. `
      + "An account that is or has been a super admin cannot be reset in the portal: whoever runs the backend sets a new password on the server with scripts\\create_super_admin.py --force."
  };
}

// ---- which screen state a list is in ------------------------------------------------------------

// "loading" | "unauthorized" | "error" | "empty" | "ready". A 403 is its own state: the account
// was a super admin when the page opened and is not any more.
export function viewState({ loading, error, items }) {
  if (error) return error.status === 403 ? "unauthorized" : "error";
  if (loading && !items) return "loading";
  return items && items.length ? "ready" : "empty";
}

// ---- the admin list -----------------------------------------------------------------------------

// What the list asks the backend for: only the filters that are set.
export function adminQuery({ search = "", status = "all", role = "all" } = {}) {
  const query = {};
  const words = search.trim();
  if (words) query.search = words;
  if (status !== "all") query.status = status;
  if (role !== "all") query.role = role;
  return query;
}

export function activeSuperAdmins(accounts) {
  return accounts.filter(account => account.role === "super_admin" && account.status === "active").length;
}

// What may be done to one account from this screen, and why not when it may not. "me" is the
// account that is signed in. The last-super-admin rule counts what the list shows, so it is
// complete only for an unfiltered list; the backend applies it to the whole table either way.
export function accountActions(account, me, accounts) {
  const self = account.id === me.id;
  const lastSuperAdmin = account.role === "super_admin" && account.status === "active" && activeSuperAdmins(accounts) <= 1;
  const actions = {
    edit: { allowed: true },
    reset: self ? { allowed: false, reason: "Change your own password in Settings." }
      : account.role === "super_admin" || account.has_been_super_admin ? { allowed: false, reason: SUPER_ADMIN_RESET } : { allowed: true },
    disable: { allowed: false },
    enable: { allowed: false },
    changeRole: { allowed: true }
  };
  if (account.status === "active") {
    actions.disable = self ? { allowed: false, reason: "You cannot disable your own account." }
      : lastSuperAdmin ? { allowed: false, reason: "This is the last active super admin." } : { allowed: true };
  } else {
    actions.enable = { allowed: true };
  }
  if (self) actions.changeRole = { allowed: false, reason: "You cannot change your own role." };
  else if (lastSuperAdmin) actions.changeRole = { allowed: false, reason: "This is the last active super admin." };
  return actions;
}

// ---- the create and edit form -------------------------------------------------------------------

export const BLANK_ADMIN = { email: "", full_name: "", role: "admin" };

export function formFromAccount(account) {
  return { email: account.email, full_name: account.full_name, role: account.role };
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// { field: "what is wrong" } for what can be told before asking the backend.
export function adminFormErrors(form) {
  const errors = {};
  const email = form.email.trim();
  const name = form.full_name.trim().replace(/\s+/g, " ");
  if (!email) errors.email = "Enter the email address.";
  else if (!EMAIL.test(email)) errors.email = "Enter a valid email address.";
  else if (email.length > MAX_EMAIL_LENGTH) errors.email = `Use at most ${MAX_EMAIL_LENGTH} characters.`;
  if (!name) errors.full_name = "Enter the full name.";
  else if (name.length > MAX_NAME_LENGTH) errors.full_name = `Use at most ${MAX_NAME_LENGTH} characters.`;
  if (!ROLE_OPTIONS.some(option => option.value === form.role)) errors.role = "Choose a role.";
  return errors;
}

export function adminPayload(form) {
  return { email: form.email.trim().toLowerCase(), full_name: form.full_name.trim().replace(/\s+/g, " "), role: form.role };
}

// Only what is different from the account as it was opened, so that an edit never sends a field
// nobody touched (the role of one's own account, for one).
export function changedFields(account, form) {
  const wanted = adminPayload(form);
  const before = adminPayload(formFromAccount(account));
  return Object.fromEntries(Object.entries(wanted).filter(([field, value]) => value !== before[field]));
}

// ---- the temporary password ---------------------------------------------------------------------

// The one place a temporary password is held: from the answer that brought it until the dialog
// showing it is closed. Nothing else keeps it, and closing (or leaving the page) forgets it.
// expires: when it stops working (from the backend, UTC with a Z).
export function secretReducer(state, event) {
  switch (event.type) {
    case "shown":
      return { email: event.email, password: event.password, why: event.why, expires: event.expires || null, copied: false };
    case "copied":
      return state ? { ...state, copied: true } : state;
    case "dismissed":
      return null;
    default:
      return state;
  }
}

// ---- the audit log ------------------------------------------------------------------------------

export const BLANK_AUDIT_FILTERS = { actor: "", action: "", from: "", to: "" };

export function auditFilterError({ from, to }) {
  return from && to && from > to ? "The start date must not be after the end date." : "";
}

export function auditQuery(filters, page = 1, pageSize = AUDIT_PAGE_SIZE) {
  const query = { page, page_size: pageSize };
  if (filters.actor) query.actor_id = filters.actor;
  if (filters.action) query.action = filters.action;
  if (filters.from) query.date_from = filters.from;
  if (filters.to) query.date_to = filters.to;
  return query;
}

export function pageCount(total, pageSize = AUDIT_PAGE_SIZE) {
  return Math.max(1, Math.ceil(total / pageSize));
}

// "26-50 of 73", "0 of 0".
export function rangeLabel(page, pageSize, total) {
  if (!total) return "0 of 0";
  const first = (page - 1) * pageSize + 1;
  return `${Math.min(first, total)}-${Math.min(page * pageSize, total)} of ${total}`;
}

const FIELD_WORDS = {
  email: "Email", full_name: "Name", role: "Role", reason: "Reason", status: "Status", previous_status: "Was",
  person_code: "ID", person_type: "Type", course_code: "Code", course_name: "Course", batch_name: "Batch",
  course_id: "Course", person_id: "Person", session_id: "Session", method: "Method", kind: "File of",
  total_rows: "Rows", imported: "Imported", skipped: "Skipped", steps: "Poses", steps_done: "Poses done", via: "Via",
  title: "Title", category: "Category", severity: "Severity"
};
const VALUE_WORDS = {
  super_admin: "Super admin", admin: "Admin", wrong_password: "Wrong password", unknown_email: "Unknown email",
  locked: "Locked out", disabled: "Account disabled", expired_temporary_password: "Temporary password expired", student: "Student", member: "Member",
  // An issue's category, severity and status, as the issue pages name them.
  ...Object.fromEntries([...CATEGORY_OPTIONS, ...SEVERITY_OPTIONS, ...STATUS_OPTIONS].map(option => [option.value, option.label]))
};

function shown(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return VALUE_WORDS[value] || String(value);
}

// details as lines a person reads: "Role: Admin → Super admin", "Reason: Wrong password".
export function detailLines(details) {
  return Object.entries(details || {}).map(([field, value]) => {
    const label = FIELD_WORDS[field] || field.replace(/_/g, " ");
    if (value && typeof value === "object" && "from" in value && "to" in value) return `${label}: ${shown(value.from)} → ${shown(value.to)}`;
    return `${label}: ${shown(value)}`;
  });
}

// What an entry was about: the name the backend found, or the kind of thing and its number.
const TARGET_WORDS = { admin_account: "Account", person: "Person", course: "Course", batch: "Batch", attendance_record: "Attendance record", issue: "Issue" };

export function targetText(entry) {
  if (entry.target_label) return entry.target_label;
  if (!entry.target_type) return "-";
  return `${TARGET_WORDS[entry.target_type] || entry.target_type} #${entry.target_id}`;
}

export function actorText(entry) {
  if (entry.actor) return entry.actor.full_name || entry.actor.email;
  if (entry.actor_id) return `Account #${entry.actor_id}`;
  return entry.details?.via === "command line" ? "Command line" : "Nobody signed in";
}

// A time from the backend (UTC, marked with Z) in the browser's own zone.
export function whenText(value, locale) {
  if (!value) return "-";
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return "-";
  return moment.toLocaleString(locale, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
