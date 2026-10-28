// Attendance codes and QR cards, kept apart from the screens so that they can be tested (qr.test.js).
// The rules are the backend's (app/services/attendance_code_service.py), word for word: a code is 8
// characters of the Crockford Base32 alphabet, stored as K7M29QXD, shown as K7M2-9QXD, and a QR holds
// VNXATT:K7M29QXD. A QR never holds a person's ID, name or anything else about them.
import QRCode from "qrcode";

export const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const CODE_LENGTH = 8;
export const QR_PREFIX = "VNXATT:";
const LOOKALIKES = { O: "0", I: "1", L: "1" };
const CODE = new RegExp(`^[${ALPHABET}]{${CODE_LENGTH}}$`);
// The type each person_type is called on a card.
const TYPE_LABELS = { student: "Student", admin: "Staff", member: "Member" };
// ID-card size, 10 to an A4 page (2 columns, 5 rows).
export const CARDS_PER_PAGE = 10;
// Past this many cards the browser can take a while to lay out the print.
export const SLOW_PRINT = 300;

// What a person typed or a scanner read, as a stored code, or null when it is not a code at all.
// Trim, uppercase, drop the QR prefix, drop spaces and hyphens, read O as 0 and I or L as 1.
export function normalizeCode(text) {
  if (typeof text !== "string") return null;
  let value = text.trim().toUpperCase();
  if (value.startsWith(QR_PREFIX)) value = value.slice(QR_PREFIX.length);
  value = value.replace(/[\s-]+/g, "").replace(/[OIL]/g, letter => LOOKALIKES[letter]);
  return CODE.test(value) ? value : null;
}

// As people read it: K7M2-9QXD. Empty for no code.
export function formatCode(code) {
  return code ? `${code.slice(0, 4)}-${code.slice(4)}` : "";
}

// What a QR card holds. Only a valid code is ever put into a QR.
export function qrPayload(code) {
  const stored = normalizeCode(code);
  return stored ? `${QR_PREFIX}${stored}` : null;
}

// What a scanned QR says: { code } for one of ours, { error } for any other QR.
export function parseScan(text) {
  const raw = typeof text === "string" ? text.trim() : "";
  if (!raw.toUpperCase().startsWith(QR_PREFIX)) return { error: "Not a Vernex attendance QR" };
  const code = normalizeCode(raw);
  return code ? { code } : { error: "Not a Vernex attendance QR" };
}

export function typeLabel(personType) {
  return TYPE_LABELS[personType] || "Person";
}

// The lines printed on a card under the name: the ID, the type, and the course and batch when there
// are any (staff and members usually have none, and get no empty line for them).
export function cardLines(person) {
  return [
    person.person_code,
    typeLabel(person.person_type),
    [person.course_name, person.batch_name].filter(Boolean).join(" · ")
  ].filter(Boolean);
}

// The name a downloaded card gets: <person ID>-qr.png, with anything a file name cannot hold replaced.
export function cardFileName(person) {
  const id = String(person?.person_code || "person").trim().replace(/[\\/:*?"<>|\s]+/g, "_") || "person";
  return `${id}-qr.png`;
}

// The people who can be printed (they have a code), in pages of CARDS_PER_PAGE.
export function printablePeople(people) {
  return (people || []).filter(person => qrPayload(person.attendance_code));
}

export function pagesOf(items, size = CARDS_PER_PAGE) {
  const pages = [];
  for (let start = 0; start < (items || []).length; start += size) pages.push(items.slice(start, start + size));
  return pages;
}

// How the QR is drawn: error correction M and a quiet zone of 4 modules, as scanners expect.
export const QR_OPTIONS = { errorCorrectionLevel: "M", margin: 4 };

// The QR of a code as a grid of dark modules, drawn at once (no waiting before a print). null for
// no code. size counts the quiet zone too; path is SVG for one unit per module.
export function qrMatrix(code) {
  const payload = qrPayload(code);
  if (!payload) return null;
  const { modules } = QRCode.create(payload, { errorCorrectionLevel: QR_OPTIONS.errorCorrectionLevel });
  const margin = QR_OPTIONS.margin;
  const dark = [];
  for (let row = 0; row < modules.size; row += 1) {
    for (let column = 0; column < modules.size; column += 1) {
      if (modules.get(row, column)) dark.push([row + margin, column + margin]);
    }
  }
  return {
    payload,
    size: modules.size + margin * 2,
    dark,
    path: dark.map(([row, column]) => `M${column} ${row}h1v1h-1z`).join("")
  };
}
