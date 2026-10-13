// Bulk upload: what each kind of file must contain, the checks made before a file is sent, and
// what is made of the answer. No screen code here, so all of it is tested (imports.test.js).

export const MAX_IMPORT_BYTES = 5 * 1024 * 1024;
export const MAX_IMPORT_ROWS = 2000;
export const IMPORT_EXTENSIONS = [".xlsx", ".csv"];
// How many problems the dialog lists. The downloaded CSV always holds every one.
export const MAX_SHOWN_PROBLEMS = 100;

const PHONE_NOTE = "Contact numbers need 10 digits. Spaces, hyphens and +91 in front are accepted.";
const PERSON_OPTIONAL = ["email", "course_code", "batch_name", "level_class", "joining_date", "notes"];

// The column names are the ones the backend reads (backend/app/services/import_service.py).
// backend/tests/data/import_columns.json is checked against both lists.
export const IMPORTS = {
  courses: {
    key: "courses",
    title: "Upload courses",
    noun: ["course", "courses"],
    path: "/courses/upload",
    templatePath: "/courses/upload/template",
    required: ["course_code", "course_name"],
    optional: ["description"],
    notes: ["Imported courses are saved as Pending, whatever status the file gives them.", "A course code that is already in use is skipped."]
  },
  batches: {
    key: "batches",
    title: "Upload batches",
    noun: ["batch", "batches"],
    path: "/batches/upload",
    templatePath: "/batches/upload/template",
    required: ["batch_name", "course_code"],
    optional: ["batch_level"],
    notes: ["course_code must be the code of a course that already exists.", "Imported batches are saved as Pending, whatever status the file gives them."]
  },
  students: {
    key: "students",
    title: "Upload students",
    noun: ["student", "students"],
    path: "/users/upload?person_type=student",
    templatePath: "/users/upload/template?person_type=student",
    required: ["student_id", "full_name", "parent_contact", "course_code", "batch_name"],
    optional: ["parent_name", "level_class", "joining_date", "notes"],
    notes: ["course_code and batch_name must match a course and one of its batches that already exist.", PHONE_NOTE, "Dates are written as 2024-06-15."]
  },
  staff: {
    key: "staff",
    title: "Upload staff",
    noun: ["staff member", "staff members"],
    path: "/users/upload?person_type=admin",
    templatePath: "/users/upload/template?person_type=admin",
    required: ["staff_id", "full_name", "contact_number"],
    optional: PERSON_OPTIONAL,
    notes: ["course_code and batch_name are optional; when given they must already exist.", PHONE_NOTE, "Dates are written as 2024-06-15."]
  },
  members: {
    key: "members",
    title: "Upload members",
    noun: ["member", "members"],
    path: "/users/upload?person_type=member",
    templatePath: "/users/upload/template?person_type=member",
    required: ["member_id", "full_name", "contact_number"],
    optional: PERSON_OPTIONAL,
    notes: ["course_code and batch_name are optional; when given they must already exist.", PHONE_NOTE, "Dates are written as 2024-06-15."]
  }
};

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Why a chosen file cannot be sent, or "" when it can. The backend makes the same checks again.
export function checkImportFile(file) {
  if (!file) return "Choose a file first.";
  const name = String(file.name || "").toLowerCase();
  if (!IMPORT_EXTENSIONS.some(extension => name.endsWith(extension))) return "Choose an Excel (.xlsx) or CSV (.csv) file.";
  if (!file.size) return "This file is empty.";
  if (file.size > MAX_IMPORT_BYTES) return `This file is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_IMPORT_BYTES)}.`;
  return "";
}

const text = value => (value === null || value === undefined ? "" : String(value));

// The backend's summary as the dialog uses it, or null when the answer is not a summary at all
// (a proxy's error page, an older backend...). Nothing is assumed about an answer like that.
export function readImportResult(payload) {
  const isCount = value => Number.isInteger(value) && value >= 0;
  if (!payload || typeof payload !== "object" || !isCount(payload.total_rows) || !isCount(payload.imported) || !isCount(payload.skipped) || !Array.isArray(payload.errors)) return null;
  const list = value => (Array.isArray(value) ? value : []);
  return {
    total: payload.total_rows,
    imported: payload.imported,
    skipped: payload.skipped,
    errors: payload.errors.filter(item => item && typeof item === "object").map(item => ({ row: item.row, column: text(item.column), value: text(item.value), message: text(item.message) })),
    skippedRows: list(payload.skipped_rows).filter(item => item && typeof item === "object").map(item => ({ row: item.row, values: item.values && typeof item.values === "object" ? item.values : {} })),
    columns: list(payload.columns).map(text),
    ignoredColumns: list(payload.ignored_columns).map(text)
  };
}

// What to tell the person, and in which colour: all in, some in, none in.
export function importOutcome(result, [one, many]) {
  const count = (number, single, plural) => `${number} ${number === 1 ? single : plural}`;
  if (!result.skipped) return { tone: "success", message: `${count(result.imported, one, many)} imported.` };
  if (!result.imported) return { tone: "danger", message: `Nothing was imported: ${count(result.skipped, "row has", "rows have")} a problem.` };
  return { tone: "warning", message: `${count(result.imported, one, many)} imported, ${count(result.skipped, "row", "rows")} skipped.` };
}

// Columns of the file that were not read, left out of the count: the two the skipped-rows CSV
// adds itself, so a corrected copy of that CSV can be uploaded as it is without a remark.
export function unusedColumns(result) {
  return result.ignoredColumns.filter(name => !["row", "problem"].includes(name.trim().toLowerCase()));
}

function csvCell(value) {
  const cell = text(value);
  return /[",\r\n]/.test(cell) || cell !== cell.trim() ? `"${cell.replace(/"/g, '""')}"` : cell;
}

// The rows that were not imported, as a CSV: the row number in the uploaded file, every value as it
// was given, and what was wrong. The values are untouched, so the rows can be corrected in place and
// the file uploaded again.
export function skippedRowsCsv(result) {
  const columns = result.columns.length ? result.columns : Object.keys(result.skippedRows[0]?.values || {});
  const problems = new Map();
  for (const error of result.errors) {
    const line = error.column ? `${error.column}: ${error.message}` : error.message;
    problems.set(error.row, [...(problems.get(error.row) || []), line]);
  }
  const lines = [["row", ...columns, "problem"], ...result.skippedRows.map(row => [row.row, ...columns.map(name => row.values[name]), (problems.get(row.row) || []).join("; ")])];
  // The byte-order mark makes Excel read the file as UTF-8.
  return `﻿${lines.map(line => line.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

// What went wrong with a request, in words for the person who pressed the button.
export function describeUploadError(error) {
  if (error?.status) return error.message || `The server refused the request (${error.status}).`;
  // fetch itself failed: no answer came back at all.
  if (error instanceof TypeError) return "Could not reach the server. Check that the backend is running, then try again.";
  return error?.message || "Something went wrong. Please try again.";
}
