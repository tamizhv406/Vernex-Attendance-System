// Run with `npm test`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { IMPORTS, MAX_IMPORT_BYTES, checkImportFile, describeUploadError, formatBytes, importOutcome, readImportResult, skippedRowsCsv, unusedColumns } from "./imports.js";

// The same list the backend's import specifications are tested with (backend/tests/test_import_templates.py).
const columns = JSON.parse(readFileSync(new URL("../../../backend/tests/data/import_columns.json", import.meta.url), "utf8"));
const file = (name, size) => ({ name, size });

// The answer of POST /courses/upload for a file with two good rows and two bad ones.
const answer = {
  entity: "courses",
  total_rows: 4,
  imported: 2,
  skipped: 2,
  errors: [
    { row: 3, column: "course_code", value: "", message: "course_code is required" },
    { row: 3, column: "course_name", value: "", message: "course_name is required" },
    { row: 6, column: "course_code", value: "CS101", message: "Duplicate of row 2 in this file" }
  ],
  skipped_rows: [
    { row: 3, values: { course_code: "", course_name: "", description: "has, a comma" } },
    { row: 6, values: { course_code: "CS101", course_name: "Say \"hi\"", description: " padded " } }
  ],
  columns: ["course_code", "course_name", "description"],
  ignored_columns: ["Status", "row", "Problem"]
};

test("the dialog lists exactly the columns the backend reads, for all five uploads", () => {
  assert.deepEqual(Object.keys(IMPORTS).sort(), ["batches", "courses", "members", "staff", "students"]);
  for (const [kind, spec] of Object.entries(IMPORTS)) {
    assert.deepEqual(spec.required, columns[kind].required, `${kind}: required`);
    assert.deepEqual(spec.optional, columns[kind].optional, `${kind}: optional`);
    assert.equal(spec.key, kind);
  }
});

test("uploads and templates go to the documented addresses", () => {
  assert.equal(IMPORTS.courses.path, "/courses/upload");
  assert.equal(IMPORTS.courses.templatePath, "/courses/upload/template");
  assert.equal(IMPORTS.batches.path, "/batches/upload");
  assert.equal(IMPORTS.batches.templatePath, "/batches/upload/template");
  for (const [kind, type] of [["students", "student"], ["staff", "admin"], ["members", "member"]]) {
    assert.equal(IMPORTS[kind].path, `/users/upload?person_type=${type}`);
    assert.equal(IMPORTS[kind].templatePath, `/users/upload/template?person_type=${type}`);
  }
});

test("a file is checked for type and size before it is sent", () => {
  assert.equal(checkImportFile(file("students.xlsx", 2048)), "");
  assert.equal(checkImportFile(file("STUDENTS.CSV", 10)), "");
  assert.equal(checkImportFile(null), "Choose a file first.");
  assert.equal(checkImportFile(file("students.xls", 2048)), "Choose an Excel (.xlsx) or CSV (.csv) file.");
  assert.equal(checkImportFile(file("students.pdf", 2048)), "Choose an Excel (.xlsx) or CSV (.csv) file.");
  assert.equal(checkImportFile(file("xlsx", 2048)), "Choose an Excel (.xlsx) or CSV (.csv) file.");
  assert.equal(checkImportFile(file("empty.csv", 0)), "This file is empty.");
  assert.equal(checkImportFile(file("exact.csv", MAX_IMPORT_BYTES)), "");
  assert.equal(checkImportFile(file("big.csv", MAX_IMPORT_BYTES + 1)), "This file is 5.0 MB. The limit is 5.0 MB.");
  assert.equal(checkImportFile(file("huge.xlsx", 12.4 * 1024 * 1024)), "This file is 12.4 MB. The limit is 5.0 MB.");
});

test("sizes are written the way people read them", () => {
  assert.equal(formatBytes(512), "512 B");
  assert.equal(formatBytes(2048), "2.0 KB");
  assert.equal(formatBytes(250 * 1024), "250 KB");
  assert.equal(formatBytes(5 * 1024 * 1024), "5.0 MB");
});

test("the backend's summary is read as it is", () => {
  const result = readImportResult(answer);
  assert.equal(result.total, 4);
  assert.equal(result.imported, 2);
  assert.equal(result.skipped, 2);
  assert.equal(result.errors.length, 3);
  assert.deepEqual(result.errors[2], { row: 6, column: "course_code", value: "CS101", message: "Duplicate of row 2 in this file" });
  assert.deepEqual(result.columns, ["course_code", "course_name", "description"]);
});

test("an answer that is not a summary is not mistaken for one", () => {
  for (const broken of [undefined, null, {}, "ok", [], { total_rows: 4 }, { ...answer, imported: "2" }, { ...answer, errors: null }, { ...answer, skipped: -1 }, { ...answer, total_rows: 1.5 }]) {
    assert.equal(readImportResult(broken), null, JSON.stringify(broken));
  }
});

test("a summary with odd details is still shown, without crashing on them", () => {
  const result = readImportResult({ total_rows: 1, imported: 0, skipped: 1, errors: [null, { row: 2, value: 12, message: null }], skipped_rows: "none" });
  assert.deepEqual(result.errors, [{ row: 2, column: "", value: "12", message: "" }]);
  assert.deepEqual(result.skippedRows, []);
  assert.deepEqual(result.columns, []);
  assert.deepEqual(result.ignoredColumns, []);
});

test("the notification says success, partial success or failure", () => {
  const noun = ["course", "courses"];
  assert.deepEqual(importOutcome({ imported: 3, skipped: 0 }, noun), { tone: "success", message: "3 courses imported." });
  assert.deepEqual(importOutcome({ imported: 1, skipped: 0 }, noun), { tone: "success", message: "1 course imported." });
  assert.deepEqual(importOutcome({ imported: 3, skipped: 2 }, noun), { tone: "warning", message: "3 courses imported, 2 rows skipped." });
  assert.deepEqual(importOutcome({ imported: 1, skipped: 1 }, noun), { tone: "warning", message: "1 course imported, 1 row skipped." });
  assert.deepEqual(importOutcome({ imported: 0, skipped: 2 }, noun), { tone: "danger", message: "Nothing was imported: 2 rows have a problem." });
  assert.deepEqual(importOutcome({ imported: 0, skipped: 1 }, noun), { tone: "danger", message: "Nothing was imported: 1 row has a problem." });
});

test("the skipped-rows CSV has the row number, the values as given and every problem of the row", () => {
  const csv = skippedRowsCsv(readImportResult(answer));
  assert.ok(csv.startsWith("﻿"), "byte-order mark, so Excel reads it as UTF-8");
  assert.deepEqual(csv.slice(1).split("\r\n"), [
    "row,course_code,course_name,description,problem",
    "3,,,\"has, a comma\",course_code: course_code is required; course_name: course_name is required",
    "6,CS101,\"Say \"\"hi\"\"\",\" padded \",course_code: Duplicate of row 2 in this file",
    ""
  ]);
});

test("the skipped-rows CSV keeps values exactly as typed, so the rows can be corrected and uploaded again", () => {
  const result = readImportResult({ ...answer, errors: [{ row: 4, column: "", value: "", message: "The database refused this row" }], skipped_rows: [{ row: 4, values: { course_code: "0042", course_name: "+91 98765 43210", description: "line one\nline two" } }] });
  assert.equal(skippedRowsCsv(result).slice(1), "row,course_code,course_name,description,problem\r\n4,0042,+91 98765 43210,\"line one\nline two\",The database refused this row\r\n");
});

test("columns the file had but the import does not read are named, except the CSV's own two", () => {
  assert.deepEqual(unusedColumns(readImportResult(answer)), ["Status"]);
});

test("a failed request is explained in plain words", () => {
  const refused = Object.assign(new Error("Missing required column: course_name."), { status: 400 });
  assert.equal(describeUploadError(refused), "Missing required column: course_name.");
  assert.equal(describeUploadError(Object.assign(new Error(""), { status: 502 })), "The server refused the request (502).");
  assert.equal(describeUploadError(new TypeError("Failed to fetch")), "Could not reach the server. Check that the backend is running, then try again.");
  assert.equal(describeUploadError(new Error("something else")), "something else");
  assert.equal(describeUploadError(undefined), "Something went wrong. Please try again.");
});
