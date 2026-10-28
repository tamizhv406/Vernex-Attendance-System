// The QR Attendance page's rules, kept apart from the screen so that they can be tested
// (qrScan.test.js): which running session can be joined, what a typed code looks like as it is typed,
// when a scanned code is sent, and what each answer of the backend shows. The backend decides who is
// marked (POST /attendance/code/mark); nothing here marks anyone or counts as marked by itself.
import { QR_PREFIX, normalizeCode } from "./qr.js";

// After an answer for a code, the same code is not sent again for this long: a card held in front of
// the camera is seen many times a second.
export const REPEAT_MS = 4000;
// How often the camera picture is looked at for a QR.
export const DECODE_EVERY_MS = 150;
// How long a result stays on screen.
export const RESULT_MS = 3000;
export const NOT_OURS = "Not a Vernex attendance QR";
export const TYPE_HINT = "Type the 8-character code from the card, for example K7M2-9QXD.";
const NETWORK = "Not marked. Check the connection and scan again.";

// A session that is running today for the same scope, which this device can join instead of
// starting a second one: { type, courseId, batchId }. The newest first.
export function joinableSession(sessions, scope, today) {
  return (sessions || [])
    .filter(session => session.status === "active" && session.session_date === today && session.session_type === scope?.type)
    .filter(session => scope.type !== "regular" || (Number(session.course_id) === Number(scope.courseId) && Number(session.batch_id) === Number(scope.batchId)))
    .sort((a, b) => Number(b.id) - Number(a.id))[0] || null;
}

// What the code field shows as someone types: uppercase, and a hyphen after the fourth character of
// a plain code. A reader that types the whole QR (VNXATT:...) is left as it is, uppercased.
export function formatTyped(text) {
  const value = String(text || "").toUpperCase().replace(/\s+/g, "");
  if (value && (value.startsWith(QR_PREFIX) || QR_PREFIX.startsWith(value))) return value.slice(0, 64);
  const plain = value.replace(/[^0-9A-Z]/g, "").slice(0, 8);
  return plain.length > 4 ? `${plain.slice(0, 4)}-${plain.slice(4)}` : plain;
}

// The error under the code field, or "" for a code that can be sent.
export function typedCodeError(text) {
  return normalizeCode(text) ? "" : TYPE_HINT;
}

// Decides whether a code read by the camera is sent: never while another mark is waiting for its
// answer, and not the same code again within REPEAT_MS of its last answer.
export function createScanGate(repeatMs = REPEAT_MS) {
  let busy = false;
  const answered = new Map();
  return {
    tryStart(code, now) {
      if (busy) return false;
      if (now - (answered.get(code) ?? -Infinity) < repeatMs) return false;
      busy = true;
      return true;
    },
    finish(code, now) {
      busy = false;
      answered.set(code, now);
    },
    get busy() { return busy; }
  };
}

// What the result panel shows for an answer: green marked, blue already marked, red refused (the
// backend's own sentence), amber when the backend could not be reached or failed.
export function resultView(outcome) {
  if (outcome?.data) {
    const { data } = outcome;
    const person = data.person || {};
    const detail = [person.person_code, [person.course_name, person.batch_name].filter(Boolean).join(" · ")].filter(Boolean).join(" · ");
    if (data.result === "already_marked") return { tone: "info", title: `Already marked: ${data.attendance_status}`, name: person.full_name, detail };
    return { tone: "success", title: `${person.full_name}: ${data.attendance_status}`, name: person.full_name, detail };
  }
  const error = outcome?.error;
  if (!error) return null;
  if (error.local) return { tone: "danger", title: error.message, detail: "" };
  if (!error.status || error.status >= 500) return { tone: "warning", title: NETWORK, detail: "Marks are not saved to send later. Scan again once the connection is back." };
  return { tone: "danger", title: error.message || "Not marked.", detail: "" };
}
