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
  return titleCase(method);
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
