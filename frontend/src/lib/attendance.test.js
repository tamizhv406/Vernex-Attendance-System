// Run with `npm test`. Marking and correcting attendance by hand: what the screens offer and send.
import assert from "node:assert/strict";
import { test } from "node:test";
import { handMark, handStatuses, methodLabel, registerRows, sessionLabel, sessionsOn, statusOf, withRecord } from "./attendance.js";

const CLASS = { id: 7, session_name: "Morning class", session_type: "regular", session_date: "2026-10-15", start_time: "09:00:00", status: "active" };
const VISIT = { ...CLASS, id: 8, session_type: "member_visit" };
const ASHA = { id: 1, full_name: "Asha" };
const BALA = { id: 2, full_name: "Bala" };

test("a class offers present, late and absent; a member visit offers visited and absent", () => {
  assert.deepEqual(handStatuses(CLASS), ["present", "late", "absent"]);
  assert.deepEqual(handStatuses(VISIT), ["visited", "absent"]);
  assert.deepEqual(handStatuses(null), ["present", "late", "absent"]);
});

test("a record says whether the scanner or a person made it", () => {
  assert.equal(methodLabel("face_ai"), "Face scan");
  assert.equal(methodLabel("manual"), "By hand");
  assert.equal(methodLabel("auto_absent"), "By hand");
  assert.equal(methodLabel(null), "-");
  assert.equal(methodLabel("google_sheet"), "Google Sheet");
});

test("every student of the batch gets a row, with their record in this session only", () => {
  const records = [
    { id: 11, session_id: 7, person_id: 1, status: "present" },
    { id: 12, session_id: 99, person_id: 2, status: "late" }
  ];

  const rows = registerRows([ASHA, BALA], records, 7);

  assert.deepEqual(rows.map(row => [row.student.full_name, row.record?.id ?? null]), [["Asha", 11], ["Bala", null]]);
  assert.deepEqual(registerRows([ASHA], null, 7), [{ student: ASHA, record: null }]);
});

test("a status reads the same from a raw record and from one mapped for the screen", () => {
  assert.equal(statusOf({ status: "present" }), "present");
  assert.equal(statusOf({ status: "Late" }), "late");
  assert.equal(statusOf(null), null);
});

test("a hand mark always names the session, the student and the status", () => {
  assert.deepEqual(handMark(CLASS, ASHA, "late"), { session_id: 7, person_id: 1, status: "late" });
  assert.deepEqual(handMark({ id: "7" }, { id: "1" }, "absent", "  Sick note  "), { session_id: 7, person_id: 1, status: "absent", notes: "Sick note" });
  assert.equal("notes" in handMark(CLASS, ASHA, "present", "   "), false);
});

test("the sessions of a day come latest first, and other days are left out", () => {
  const sessions = [
    { id: 1, session_date: "2026-10-15", start_time: "09:00:00" },
    { id: 2, session_date: "2026-10-14", start_time: "10:00:00" },
    { id: 3, session_date: "2026-10-15", start_time: "13:30:00" },
    { id: 4, session_date: "2026-10-15", start_time: null }
  ];

  assert.deepEqual(sessionsOn(sessions, "2026-10-15").map(session => session.id), [3, 1, 4]);
  assert.deepEqual(sessionsOn(undefined, "2026-10-15"), []);
});

test("a session is named with its start time and whether it is still running", () => {
  assert.equal(sessionLabel(CLASS), "Morning class, started 09:00 (Active)");
  assert.equal(sessionLabel({ id: 5, status: "completed" }), "Session 5 (Completed)");
});

test("a changed record replaces the one it was", () => {
  const before = [{ id: 1, status: "present" }, { id: 2, status: "late" }];

  assert.deepEqual(withRecord(before, { id: 2, status: "absent" }), [{ id: 2, status: "absent" }, { id: 1, status: "present" }]);
  assert.deepEqual(withRecord(undefined, { id: 3 }), [{ id: 3 }]);
});
