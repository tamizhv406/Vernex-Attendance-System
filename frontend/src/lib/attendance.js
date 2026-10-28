// Attendance marked or corrected by hand: which statuses a teacher may choose, what each student of a
// session has so far, and how a record says it was made. The backend decides every rule (the session,
// its date, the audit log); this only arranges what the screens show and send.
import { titleCase } from "./format.js";

// A class has present, late and absent; a member visit has visited and absent.
export function handStatuses(session) {
  return session?.session_type === "member_visit" ? ["visited", "absent"] : ["present", "late", "absent"];
}

// How a record was made, in words. "auto_absent" is the backend's name for absent marked by hand.
export function methodLabel(method) {
  if (!method) return "-";
  if (method === "face_ai") return "Face scan";
  if (method === "manual" || method === "auto_absent") return "By hand";
  if (method === "qr_scan") return "QR scan";
  if (method === "code_entry") return "Code typed";
  return titleCase(method);
}

// The kinds of session the scanners start. A batch class takes a course and a batch; a staff or a
// member session takes everyone of its kind (staff are person_type "admin").
export const SESSION_TYPES = [
  { value: "regular", label: "Batch class" },
  { value: "staff", label: "Staff" },
  { value: "member_visit", label: "Members" }
];
const SCOPE_PERSON_TYPES = { staff: "admin", member_visit: "member" };

// Who a session about to start (or running) is for: { type, courseId, batchId }, or a session itself.
// A batch class lists the students of its batch, as the roster always did; the backend also accepts
// staff and members assigned to that batch (attendance_service.person_in_session).
// records: the session's records, when there is a session. Only active people can be marked, so the
// roster is the active people of the scope, plus anyone who already has a record in this session
// (someone made pending or inactive later), whose record can still be corrected by hand.
export function scopePeople(people, scope, records = []) {
  const type = scope?.type ?? scope?.session_type;
  const courseId = scope?.courseId ?? scope?.course_id;
  const batchId = scope?.batchId ?? scope?.batch_id;
  const personType = SCOPE_PERSON_TYPES[type];
  const recorded = new Set((records || []).map(record => Number(record.person_id)));
  const markable = person => isActive(person) || recorded.has(Number(person.id));
  if (personType) return (people || []).filter(person => person.person_type === personType && markable(person));
  if (!courseId || !batchId) return [];
  return (people || []).filter(person => person.person_type === "student" && Number(person.course_id) === Number(courseId) && Number(person.batch_id) === Number(batchId) && markable(person));
}

// A person without a status is treated as active, as mapPerson does.
export function isActive(person) {
  return String(person?.status || "active").toLowerCase() === "active";
}

// How the screens name the people of a session of each kind.
const SCOPE_WORDS = {
  regular: { person: "Student", list: "Students in this batch", none: "No students in this batch", hint: "Add students to the batch first." },
  staff: { person: "Staff member", list: "Staff", none: "No staff found", hint: "Add staff on the Staff page first." },
  member_visit: { person: "Member", list: "Members", none: "No members found", hint: "Add members on the Members page first." }
};

export function scopeWords(type) {
  return SCOPE_WORDS[type] || SCOPE_WORDS.regular;
}

// The Reports page's "Who" filter, on the person_type each record keeps.
export const WHO_OPTIONS = [
  { value: "all", label: "All" },
  { value: "student", label: "Students" },
  { value: "admin", label: "Staff" },
  { value: "member", label: "Members" }
];

export function recordIsFor(record, who) {
  return who === "all" || record?.person_type === who;
}

// A session can start once its scope is complete: a batch class needs its course and batch.
export function scopeReady(scope) {
  if (SCOPE_PERSON_TYPES[scope?.type]) return true;
  return scope?.type === "regular" && Boolean(scope.courseId && scope.batchId);
}

// One row per student, with that student's record in this session, or null when there is none yet.
export function registerRows(students, records, sessionId) {
  const byPerson = new Map();
  for (const record of records || []) {
    if (Number(record.session_id) === Number(sessionId)) byPerson.set(Number(record.person_id), record);
  }
  return (students || []).map(student => ({ student, record: byPerson.get(Number(student.id)) || null }));
}

// The status a record has, as the backend spells it ("present"), whether the record was mapped for the
// screen ("Present") or not.
export function statusOf(record) {
  return record ? String(record.status || "").toLowerCase() : null;
}

// What is sent to mark a student by hand. The status is always named, so a student who is already
// marked (by the scanner or by hand) is corrected instead of being left as they were.
export function handMark(session, student, status, notes) {
  const body = { session_id: Number(session.id), person_id: Number(student.id), status };
  if (notes && notes.trim()) body.notes = notes.trim();
  return body;
}

// The sessions held on one day (YYYY-MM-DD), the latest first.
export function sessionsOn(sessions, date) {
  return (sessions || [])
    .filter(session => session.session_date === date)
    .sort((a, b) => String(b.start_time || "").localeCompare(String(a.start_time || "")) || Number(b.id) - Number(a.id));
}

export function sessionLabel(session) {
  const started = session.start_time ? `, started ${String(session.start_time).slice(0, 5)}` : "";
  return `${session.session_name || `Session ${session.id}`}${started} (${titleCase(session.status || "")})`;
}

// Puts a record that was just written or changed into a list, replacing the one it was before.
export function withRecord(records, record) {
  return [record, ...(records || []).filter(item => Number(item.id) !== Number(record.id))];
}
