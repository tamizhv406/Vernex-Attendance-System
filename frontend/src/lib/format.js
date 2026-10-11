// Mapping between backend rows and what the screens show. Moved here unchanged from main.jsx.

export function mapPerson(person) {
  return {
    ...person,
    course_name: person.course_name || person.category_program || "",
    batch_name: person.batch_name || "",
    status: person.status || "active",
    face_enrollment_status: person.face_enrollment_status || "not_started"
  };
}

export function mapAttendance(record) {
  return {
    ...record,
    status: toUiStatus(record.status),
    course_name: record.course_name || record.category_program || "",
    batch_name: record.batch_name || "",
    marked_time: record.marked_time || record.created_at || new Date().toISOString()
  };
}

export function toPersonPayload(form, apiType) {
  return {
    person_code: form.person_code,
    full_name: form.full_name,
    phone: apiType === "student" ? null : form.phone || null,
    email: form.email || null,
    person_type: apiType,
    guardian_name: form.guardian_name || null,
    guardian_phone: apiType === "student" ? form.phone || null : null,
    course_id: form.course_id ? Number(form.course_id) : null,
    batch_id: form.batch_id ? Number(form.batch_id) : null,
    level_class: form.level_class || null,
    joining_date: form.joining_date || null,
    status: form.status,
    face_enrollment_status: form.face_enrollment_status,
    notes: form.notes || null
  };
}

export function courseName(courses, id) {
  return courses.find(course => Number(course.id) === Number(id))?.course_name || "-";
}

export function batchName(batches, id) {
  return batches.find(batch => Number(batch.id) === Number(id))?.batch_name || "-";
}

export function statusOptions() {
  return [{ value: "active", label: "Active" }, { value: "pending", label: "Pending" }, { value: "inactive", label: "Inactive" }];
}

export function toUiStatus(value) {
  const normalized = String(value || "pending").toLowerCase();
  if (normalized === "not_started" || normalized === "in_progress") return "Pending";
  if (normalized === "already marked") return "Already Marked";
  return titleCase(normalized);
}

export function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\w\S*/g, text => text.charAt(0).toUpperCase() + text.slice(1).toLowerCase());
}

export function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatClock(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Today's date as the device sees it (YYYY-MM-DD), for date pickers.
export function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

export function initials(name) {
  return String(name || "?").trim().split(/\s+/).slice(0, 2).map(part => part.charAt(0).toUpperCase()).join("") || "?";
}

export function faceEnrolled(person) {
  return person?.face_enrollment_status === "completed";
}
