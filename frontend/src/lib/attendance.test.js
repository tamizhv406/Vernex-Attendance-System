// Run with `npm test`. Marking and correcting attendance by hand: what the screens offer and send.
import assert from "node:assert/strict";
import { test } from "node:test";
import { SESSION_TYPES, WHO_OPTIONS, handMark, isActive, handStatuses, methodLabel, recordIsFor, registerRows, scopePeople, scopeReady, scopeWords, sessionLabel, sessionsOn, statusOf, withRecord } from "./attendance.js";

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

// ---- session scopes: a batch class, staff, members ------------------------------------------------

const PEOPLE = [
  { id: 1, full_name: "Asha", person_type: "student", course_id: 3, batch_id: 7 },
  { id: 2, full_name: "Bala", person_type: "student", course_id: 3, batch_id: 8 },
  { id: 3, full_name: "Chitra", person_type: "admin", course_id: null, batch_id: null },
  { id: 4, full_name: "Dev", person_type: "admin", course_id: 3, batch_id: 7 },
  { id: 5, full_name: "Esha", person_type: "member", course_id: null, batch_id: null }
];
const ids = rows => rows.map(person => person.id);

test("the scanners start a batch class, a staff session or a member session", () => {
  assert.deepEqual(SESSION_TYPES.map(type => type.value), ["regular", "staff", "member_visit"]);
  assert.deepEqual(SESSION_TYPES.map(type => type.label), ["Batch class", "Staff", "Members"]);
});

test("a staff session offers present, late and absent, like a class", () => {
  assert.deepEqual(handStatuses({ ...CLASS, session_type: "staff", course_id: null, batch_id: null }), ["present", "late", "absent"]);
});

test("the roster of a batch class is its students; of a staff or member session, everyone of that kind", () => {
  assert.deepEqual(ids(scopePeople(PEOPLE, { type: "regular", courseId: "3", batchId: "7" })), [1]);
  assert.deepEqual(ids(scopePeople(PEOPLE, { type: "staff" })), [3, 4]);
  assert.deepEqual(ids(scopePeople(PEOPLE, { type: "member_visit" })), [5]);
  // A running session gives its own scope.
  assert.deepEqual(ids(scopePeople(PEOPLE, { session_type: "staff", course_id: null, batch_id: null })), [3, 4]);
  assert.deepEqual(ids(scopePeople(PEOPLE, { session_type: "regular", course_id: 3, batch_id: 8 })), [2]);
});

test("a batch class without its course and batch has nobody on the roster and cannot start", () => {
  assert.deepEqual(scopePeople(PEOPLE, { type: "regular", courseId: "3", batchId: "" }), []);
  assert.deepEqual(scopePeople(PEOPLE, null), []);
  assert.equal(scopeReady({ type: "regular", courseId: "3", batchId: "" }), false);
  assert.equal(scopeReady({ type: "regular", courseId: "3", batchId: "7" }), true);
  assert.equal(scopeReady({ type: "staff", courseId: "", batchId: "" }), true);
  assert.equal(scopeReady({ type: "member_visit" }), true);
  assert.equal(scopeReady({ type: "exam", courseId: "3", batchId: "7" }), false);
});

test("the register names the people of each kind of session", () => {
  assert.equal(scopeWords("regular").person, "Student");
  assert.equal(scopeWords("staff").person, "Staff member");
  assert.equal(scopeWords("member_visit").person, "Member");
  assert.equal(scopeWords(undefined).person, "Student");
  for (const type of ["staff", "member_visit"]) {
    for (const words of Object.values(scopeWords(type))) assert.doesNotMatch(words, /student/i);
  }
});

test("the reports' Who filter picks records by the person's type", () => {
  const records = [{ id: 1, person_type: "student" }, { id: 2, person_type: "admin" }, { id: 3, person_type: "member" }];
  const pick = who => records.filter(record => recordIsFor(record, who)).map(record => record.id);

  assert.deepEqual(WHO_OPTIONS.map(option => option.label), ["All", "Students", "Staff", "Members"]);
  assert.deepEqual(pick("all"), [1, 2, 3]);
  assert.deepEqual(pick("student"), [1]);
  assert.deepEqual(pick("admin"), [2]);
  assert.deepEqual(pick("member"), [3]);
});

// ---- only active people can be marked -----------------------------------------------------------

test("rosters list only active people, plus anyone who already has a record in the session", () => {
  const people = [
    { id: 1, person_type: "admin", status: "active" },
    { id: 2, person_type: "admin", status: "pending" },
    { id: 3, person_type: "admin", status: "inactive" },
    { id: 4, person_type: "admin", status: "Inactive" },
    { id: 5, person_type: "admin" },
    { id: 6, person_type: "student", status: "inactive", course_id: 3, batch_id: 7 },
    { id: 7, person_type: "student", status: "active", course_id: 3, batch_id: 7 }
  ];
  const ids = rows => rows.map(person => person.id);

  assert.deepEqual(ids(scopePeople(people, { type: "staff" })), [1, 5]);
  assert.deepEqual(ids(scopePeople(people, { type: "regular", courseId: 3, batchId: 7 })), [7]);
  // Made inactive after being marked: still on the register, so the mark can be corrected.
  assert.deepEqual(ids(scopePeople(people, { type: "staff" }, [{ person_id: 3, session_id: 9 }])), [1, 3, 5]);
  assert.deepEqual(ids(scopePeople(people, { type: "regular", courseId: 3, batchId: 7 }, [{ person_id: 6 }])), [6, 7]);
});

test("a person without a status counts as active, any other status does not", () => {
  assert.equal(isActive({}), true);
  assert.equal(isActive({ status: "active" }), true);
  assert.equal(isActive({ status: "ACTIVE" }), true);
  assert.equal(isActive({ status: "pending" }), false);
  assert.equal(isActive({ status: "inactive" }), false);
});
