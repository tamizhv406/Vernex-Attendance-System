// "/api" is proxied to FastAPI by Vite, so a phone on the same Wi-Fi reaches the backend through this origin.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function request(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {})
    }
  });

  const payload = await response.json().catch(() => ({}));

  if (!response.ok || payload.success === false) {
    // Callers can tell a refused request (payload) from a broken one (status) instead of guessing from the text.
    const error = new Error(payload.message || (typeof payload.detail === "string" ? payload.detail : "") || `Request failed with status ${response.status}`);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload.data ?? payload;
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

export function getHealth() {
  return request("/health");
}

export { API_BASE_URL };
