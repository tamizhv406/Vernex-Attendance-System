import { createSession } from "./auth";

// "/api" is proxied to FastAPI by Vite, so a phone on the same Wi-Fi reaches the backend through this origin.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

// One exchange with the backend. A refusal is an answer like any other; only a server that cannot
// be reached makes this reject. The body goes out as JSON unless it is a form (a file, a camera frame).
async function send(path, { token, body, headers, ...options } = {}) {
  const isFormData = body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    body: body === undefined || isFormData || typeof body === "string" ? body : JSON.stringify(body),
    // The refresh cookie has to travel with the auth requests, also when the backend is on another origin.
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers || {})
    }
  });
  return { status: response.status, json: () => response.json().catch(() => ({})), blob: () => response.blob() };
}

// Whether this browser was signed in when it was last used. A yes/no and nothing else: the tokens
// themselves are never written anywhere the page can read them back from.
const SIGNED_IN_HINT = "vx_session";
const hint = {
  get() { try { return localStorage.getItem(SIGNED_IN_HINT) === "yes"; } catch { return true; } },
  set(signedIn) { try { signedIn ? localStorage.setItem(SIGNED_IN_HINT, "yes") : localStorage.removeItem(SIGNED_IN_HINT); } catch { /* private mode: every load simply asks the backend */ } }
};
// What the page used to keep before there were real logins. It opens nothing now; it is just removed.
try { localStorage.removeItem("vx_auth"); } catch { /* nothing to remove */ }

export const session = createSession({ send, remember: hint });

async function request(path, options = {}) {
  const answer = await session.call(path, options);
  const payload = await answer.json();

  if (answer.status < 200 || answer.status > 299 || payload.success === false) throw apiError(payload, answer.status);

  return payload.data ?? payload;
}

// Callers can tell a refused request (payload) from a broken one (status) instead of guessing from the text.
function apiError(payload, status) {
  const error = new Error(payload.message || detailText(payload.detail) || `Request failed with status ${status}`);
  error.status = status;
  error.payload = payload;
  return error;
}

// The backend explains a refusal in "detail": one sentence from a route, or a list from FastAPI's
// own checking of the request ([{ loc: ["body", "course_id"], msg: "Input should be..." }]).
function detailText(detail) {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "";
  return detail.map(item => {
    const field = (Array.isArray(item?.loc) ? item.loc : []).filter(part => !["body", "query", "path"].includes(part)).join(".");
    return [field, item?.msg].filter(Boolean).join(": ");
  }).filter(Boolean).join("; ");
}

function queryString(filters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function getPeople(filters = {}) {
  return request(`/users${queryString(filters)}`);
}

export function createPerson(data) {
  return request("/users/create", { method: "POST", body: JSON.stringify(data) });
}

export function updatePerson(id, data) {
  return request(`/users/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export function deletePerson(id) {
  return request(`/users/${id}`, { method: "DELETE" });
}

export function getCourses() {
  return request("/courses");
}

export function createCourse(data) {
  return request("/courses/create", { method: "POST", body: JSON.stringify(data) });
}

export function updateCourse(id, data) {
  return request(`/courses/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export function deleteCourse(id) {
  return request(`/courses/${id}`, { method: "DELETE" });
}

export function getBatches(courseId) {
  return request(`/batches${queryString({ course_id: courseId })}`);
}

export function createBatch(data) {
  return request("/batches/create", { method: "POST", body: JSON.stringify(data) });
}

export function updateBatch(id, data) {
  return request(`/batches/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export function deleteBatch(id) {
  return request(`/batches/${id}`, { method: "DELETE" });
}

// Bulk upload. The file goes in a form, so no JSON content type is set for it (see request).
export function uploadImport(path, file) {
  const form = new FormData();
  form.append("file", file, file.name);
  return request(path, { method: "POST", body: form });
}

// A file from the backend (an import template) as a Blob. A refusal arrives as JSON and is thrown like any other.
export async function downloadFile(path) {
  const answer = await session.call(path);
  if (answer.status !== 200) throw apiError(await answer.json(), answer.status);
  return answer.blob();
}

export function getTimings() {
  return request("/timings");
}

export function createTiming(data) {
  return request("/timings/create", { method: "POST", body: JSON.stringify(data) });
}

export function startAttendanceSession(data) {
  return request("/attendance/session/start", { method: "POST", body: JSON.stringify(data) });
}

export function completeAttendanceSession(sessionId) {
  return request(`/attendance/session/${sessionId}/complete`, { method: "POST" });
}

export function getAttendanceToday() {
  return request("/attendance/today");
}

export function getAttendanceByDate(attendanceDate, filters = {}) {
  return request(`/attendance/by-date${queryString({ attendance_date: attendanceDate, ...filters })}`);
}

export function markAttendance(data) {
  return request("/attendance/mark", { method: "POST", body: JSON.stringify(data) });
}

// mode: "quick" or "guided" (five poses). Left out, the backend's FACE_ENROLL_MODE decides.
export function startFaceEnrollment(personId, mode) {
  return request(`/face/enrollment/start/${personId}${queryString({ mode })}`, { method: "POST" });
}

export function cancelFaceEnrollment(personId) {
  return request(`/face/enrollment/cancel/${personId}`, { method: "POST" });
}

export function getFaceEnrollmentStatus(personId) {
  return request(`/face/enrollment/status/${personId}`);
}

export function getEnrollmentUsers(courseId, batchId) {
  return request(`/face/enrollment/users${queryString({ course_id: courseId, batch_id: batchId })}`);
}

export function sendEnrollmentFrame(formData) {
  return request("/face/enrollment/frame", { method: "POST", body: formData });
}

export function recognizeFace(formData) {
  return request("/face/recognize", { method: "POST", body: formData });
}

// The database and face-model state, for someone who is logged in. (The public /health says one word.)
export function getHealth() {
  return request("/health/details");
}

// ---- the Super Admin portal (the backend refuses all of these to an admin) ----------------------

export function getPortalDashboard() {
  return request("/super-admin/dashboard");
}

export function getAdmins(filters = {}) {
  return request(`/super-admin/admins${queryString(filters)}`);
}

// Resolves to { account, temporary_password }. The password is in this one answer only.
export function createAdmin(data) {
  return request("/super-admin/admins", { method: "POST", body: JSON.stringify(data) });
}

export function updateAdmin(id, data) {
  return request(`/super-admin/admins/${id}`, { method: "PUT", body: JSON.stringify(data) });
}

export function disableAdmin(id) {
  return request(`/super-admin/admins/${id}/disable`, { method: "POST" });
}

export function enableAdmin(id) {
  return request(`/super-admin/admins/${id}/enable`, { method: "POST" });
}

// Resolves to { account, temporary_password }, like createAdmin.
export function resetAdminPassword(id) {
  return request(`/super-admin/admins/${id}/reset-password`, { method: "POST" });
}

export function getAuditLogs(query = {}) {
  return request(`/super-admin/audit-logs${queryString(query)}`);
}

export function getAuditActions() {
  return request("/super-admin/audit-logs/actions");
}

export { API_BASE_URL };
