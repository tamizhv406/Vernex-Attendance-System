// Issue reporting's rules, kept apart from the screens so that they can be tested (issues.test.js).
// The backend (app/services/issue_service.py) checks all of this again, with the same limits and the
// same words; these only let a form say what is wrong before anything is sent.

export const CATEGORY_OPTIONS = [
  { value: "bug", label: "Bug" },
  { value: "face_recognition", label: "Face recognition" },
  { value: "attendance_data", label: "Attendance data" },
  { value: "camera_device", label: "Camera or device" },
  { value: "login_access", label: "Login or access" },
  { value: "other", label: "Other" }
];
export const SEVERITY_OPTIONS = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "critical", label: "Critical" }
];
export const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "in_progress", label: "In progress" },
  { value: "resolved", label: "Resolved" },
  { value: "closed", label: "Closed" }
];
// A status is a word and an icon in a colour (StatusBadge), never a colour on its own.
const STATUS_TONES = { open: "info", in_progress: "warning", resolved: "success", closed: "neutral" };
const SEVERITY_TONES = { low: "neutral", medium: "info", high: "warning", critical: "danger" };

// (shortest, longest) in characters, once the text is trimmed.
export const LIMITS = { title: [5, 120], description: [10, 4000], comment: [1, 4000], note: [1, 4000] };
export const PAGE_MAX = 255;
export const DEVICE_MAX = 100;
export const ISSUE_PAGE_SIZE = 25;
// How often the portal's open-issue badge and the open inbox ask again (the task sheet: 30 to 60 s).
export const OPEN_COUNT_INTERVAL_MS = 45000;
// Open and in progress together: what the badge counts, and what the inbox shows first.
export const UNRESOLVED = "unresolved";
export const NOTE_NEEDED = "Write a resolution note to resolve this issue: what was done, or why nothing needs to be.";

function labelIn(options, value) {
  return options.find(option => option.value === value)?.label || value || "-";
}

export const categoryLabel = value => labelIn(CATEGORY_OPTIONS, value);
export const severityLabel = value => labelIn(SEVERITY_OPTIONS, value);
export const statusLabel = value => labelIn(STATUS_OPTIONS, value);
export const statusTone = value => STATUS_TONES[value] || "neutral";
export const severityTone = value => SEVERITY_TONES[value] || "neutral";

// ---- what is typed ------------------------------------------------------------------------------

// Control characters other than tab and line break, which the backend drops as well.
const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f]/g;

// Several lines, as written, with one kind of line break.
export function cleanText(value) {
  return String(value ?? "").replace(/\r\n?/g, "\n").replace(CONTROL, "").trim();
}

// One line: every run of spaces and line breaks becomes one space.
export function cleanLine(value) {
  return String(value ?? "").replace(CONTROL, " ").split(/\s+/).filter(Boolean).join(" ");
}

// Characters as the backend counts them: an emoji is one, not the two halves JavaScript sees.
export function characters(text) {
  return [...String(text ?? "")].length;
}

export function lengthProblem(text, [shortest, longest], what) {
  const count = characters(text);
  if (count >= shortest && count <= longest) return "";
  return shortest > 1 ? `${what} must be ${shortest} to ${longest} characters long.` : `${what} must be at most ${longest} characters long, and not empty.`;
}

// ---- reporting a problem ------------------------------------------------------------------------

export const BLANK_REPORT = { title: "", category: "", severity: "medium", description: "" };

// { field: "what is wrong" } for what can be told before sending.
export function reportErrors(form) {
  const errors = {};
  const title = lengthProblem(cleanLine(form.title), LIMITS.title, "The title");
  const description = lengthProblem(cleanText(form.description), LIMITS.description, "The description");
  if (title) errors.title = title;
  if (!CATEGORY_OPTIONS.some(option => option.value === form.category)) errors.category = "Choose a category.";
  if (!SEVERITY_OPTIONS.some(option => option.value === form.severity)) errors.severity = "Choose a severity.";
  if (description) errors.description = description;
  return errors;
}

// What is sent. Who reports it is not in it: the backend takes that from the login.
export function reportPayload(form, { page = null, device = null } = {}) {
  return {
    title: cleanLine(form.title),
    description: cleanText(form.description),
    category: form.category,
    severity: form.severity,
    page_url: page,
    device_info: device && Object.keys(device).length ? device : null
  };
}

// The page a report comes from, as a path inside the console: never the query string or the
// fragment, which can hold what was typed into a page. null when it is not a plain path.
const PAGE = /^\/(?!\/)[A-Za-z0-9/._~%-]*$/;

export function pagePath(pathname) {
  const path = String(pathname ?? "");
  return path.length <= PAGE_MAX && PAGE.test(path) ? path : null;
}

const BROWSERS = [
  [/Edg(?:e|A|iOS)?\/(\d+)/, "Edge"],
  [/OPR\/(\d+)/, "Opera"],
  [/SamsungBrowser\/(\d+)/, "Samsung Internet"],
  [/FxiOS\/(\d+)/, "Firefox"],
  [/Firefox\/(\d+)/, "Firefox"],
  [/CriOS\/(\d+)/, "Chrome"],
  [/Chrome\/(\d+)/, "Chrome"],
  [/Version\/(\d+)[\d.]* (?:Mobile\/\S+ )?Safari\//, "Safari"]
];

export function browserName(agent = "") {
  for (const [pattern, name] of BROWSERS) {
    const found = pattern.exec(agent);
    if (found) return `${name} ${found[1]}`;
  }
  return "";
}

export function systemName(agent = "", platform = "") {
  const apple = /(iPhone|iPad|iPod)[^)]*? OS (\d+)(?:_(\d+))?/.exec(agent);
  if (apple) return `${apple[1] === "iPad" ? "iPadOS" : "iOS"} ${apple[2]}${apple[3] ? `.${apple[3]}` : ""}`;
  const android = /Android (\d+)/.exec(agent);
  if (android) return `Android ${android[1]}`;
  if (/Windows NT/.test(agent)) return "Windows";
  if (/CrOS/.test(agent)) return "ChromeOS";
  if (/Mac OS X/.test(agent)) return "macOS";
  if (/Linux/.test(agent)) return "Linux";
  return String(platform || "");
}

// The browser, the OS and the screen: three short lines worked out here, and nothing else about the
// device (not the whole user-agent string). Empty ones are left out.
export function deviceInfo(browser = {}, screen = null) {
  const agent = String(browser.userAgent || "");
  const info = {
    browser: browserName(agent),
    os: systemName(agent, browser.userAgentData?.platform),
    screen: screen?.width && screen?.height ? `${Math.round(screen.width)}x${Math.round(screen.height)}` : ""
  };
  return Object.fromEntries(Object.entries(info)
    .map(([field, value]) => [field, [...cleanLine(value)].slice(0, DEVICE_MAX).join("")])
    .filter(([, value]) => value));
}

export function deviceText(info) {
  return [info?.browser, info?.os, info?.screen].filter(Boolean).join(" · ") || "Not recorded";
}

// When a refused report names a field (a 422 list), the words go next to that field.
export function fieldErrors(error, fields) {
  const detail = error?.payload?.detail;
  if (!Array.isArray(detail)) return {};
  return Object.fromEntries(detail
    .map(item => [Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : null, item?.msg])
    .filter(([field, message]) => fields.includes(field) && message));
}

// ---- comments -----------------------------------------------------------------------------------

export function commentError(text) {
  return lengthProblem(cleanText(text), LIMITS.comment, "A comment");
}

export function canComment(issue) {
  return Boolean(issue) && issue.status !== "closed";
}

// ---- an issue's status, resolution note and assignee (super admins) -----------------------------

// The resolution note is shown once the issue has been resolved (also after it was closed); an
// issue that was opened again keeps its old note, but does not show it.
export function showsResolution(issue) {
  return Boolean(issue?.resolved_at && issue?.resolution_note);
}

export function formFromIssue(issue) {
  return { status: issue.status, note: issue.resolution_note || "", assignee: issue.assigned_to ? String(issue.assigned_to) : "" };
}

// { errors, body }: what a save sends, only what changed, or what must be put right first.
// Resolving always sends a note; a resolved issue sends one only when it was edited.
export function issueChanges(issue, form) {
  const errors = {};
  const body = {};
  if (form.status !== issue.status) body.status = form.status;
  if (form.status === "resolved") {
    const note = cleanText(form.note);
    const problem = lengthProblem(note, LIMITS.note, "The resolution note");
    if (problem) errors.note = note ? problem : NOTE_NEEDED;
    else if (form.status !== issue.status || note !== (issue.resolution_note || "")) body.resolution_note = note;
  }
  const assignee = form.assignee ? Number(form.assignee) : null;
  if (assignee !== (issue.assigned_to ?? null)) body.assigned_to = assignee;
  return { errors, body };
}

// ---- lists --------------------------------------------------------------------------------------

export const INBOX_STATUS_OPTIONS = [{ value: UNRESOLVED, label: "Open + in progress" }, { value: "all", label: "All statuses" }, ...STATUS_OPTIONS];
export const SORT_OPTIONS = [{ value: "newest", label: "Newest" }, { value: "severity", label: "Severity" }];
export const BLANK_INBOX_FILTERS = { status: UNRESOLVED, severity: "", category: "", reporter: "", from: "", to: "", sort: "newest" };

export function inboxFilterError({ from, to }) {
  return from && to && from > to ? "The start date must not be after the end date." : "";
}

// What the inbox asks the backend for: only the filters that are set.
export function inboxQuery(filters, page = 1, pageSize = ISSUE_PAGE_SIZE) {
  const query = { page, page_size: pageSize, sort: filters.sort || "newest" };
  if (filters.status && filters.status !== "all") query.status = filters.status;
  if (filters.severity) query.severity = filters.severity;
  if (filters.category) query.category = filters.category;
  if (filters.reporter) query.reporter_id = filters.reporter;
  if (filters.from) query.date_from = filters.from;
  if (filters.to) query.date_to = filters.to;
  return query;
}

export function inboxFiltered(filters) {
  return Object.entries(BLANK_INBOX_FILTERS).some(([field, value]) => field !== "sort" && filters[field] !== value);
}

// ---- the portal's badge and dashboard -----------------------------------------------------------

export function badgeText(count) {
  if (!count || count < 0) return "";
  return count > 99 ? "99+" : String(count);
}

// "2 critical · 1 high · 0 medium · 1 low"
export function openSummary(open) {
  if (!open) return "";
  return ["critical", "high", "medium", "low"].map(severity => `${open[severity] ?? 0} ${severity}`).join(" · ");
}

// "Mon 9 Mar – Sun 15 Mar", from the backend's { from: "2026-03-09", to: "2026-03-15" }.
export function weekText(week, locale) {
  if (!week?.from || !week?.to) return "";
  const day = text => {
    const [year, month, date] = text.split("-").map(Number);
    return new Date(year, month - 1, date).toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
  };
  return `${day(week.from)} – ${day(week.to)}`;
}
