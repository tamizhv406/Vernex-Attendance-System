// Run with `npm test`. These are the rules the Courses and Batches pages follow when a record is
// opened, changed, cancelled and saved; the pages hold their form in exactly this reducer.
import assert from "node:assert/strict";
import { test } from "node:test";
import { BLANK_BATCH, BLANK_COURSE, batchErrors, batchPayload, courseErrors, coursePayload, editorReducer, formFromBatch, formFromCourse, startEditor, statusesOf } from "./editForms.js";

const course = { id: 7, course_code: "CS101", course_name: "Computer Science", description: null, status: "pending" };
const batch = { id: 3, course_id: 7, batch_name: "Morning A", batch_level: null, timing_id: 4, status: "pending" };
const open = (blank, id, form) => editorReducer(startEditor(blank), { type: "edit", id, form });
const change = (state, field, value) => editorReducer(state, { type: "change", field, value });

test("opening a course fills every field with that course's values", () => {
  const state = open(BLANK_COURSE, course.id, formFromCourse(course));
  assert.equal(state.editing, 7);
  assert.deepEqual(state.form, { course_code: "CS101", course_name: "Computer Science", description: "", status: "pending" });
  assert.deepEqual(state.errors, {});
});

test("opening a batch fills its name, course, level and status", () => {
  const state = open(BLANK_BATCH, batch.id, formFromBatch(batch));
  assert.equal(state.editing, 3);
  assert.deepEqual(state.form, { course_id: "7", batch_name: "Morning A", batch_level: "", status: "pending" });
});

test("changing a batch's course keeps the edit open and touches nothing else", () => {
  let state = open(BLANK_BATCH, batch.id, formFromBatch(batch));
  state = change(state, "batch_name", "Morning A (renamed)");
  state = change(state, "course_id", "9");
  // This is the bug that was fixed: the course select used to end the edit and empty the form.
  assert.equal(state.editing, 3);
  assert.deepEqual(state.form, { course_id: "9", batch_name: "Morning A (renamed)", batch_level: "", status: "pending" });
  // What was opened is still known, so the page can tell that the batch is being moved.
  assert.equal(state.original.course_id, "7");
});

test("what is saved after changing the course is an update of the same batch, to the new course", () => {
  const state = change(open(BLANK_BATCH, batch.id, formFromBatch(batch)), "course_id", "9");
  assert.equal(state.editing, batch.id);
  assert.deepEqual(batchPayload(state.form), { course_id: 9, batch_name: "Morning A", batch_level: null, status: "pending" });
});

test("typing keeps the edit open for every field of both forms", () => {
  for (const [blank, record, form] of [[BLANK_COURSE, course, formFromCourse(course)], [BLANK_BATCH, batch, formFromBatch(batch)]]) {
    for (const field of Object.keys(blank)) {
      const state = change(open(blank, record.id, form), field, "x");
      assert.equal(state.editing, record.id, field);
      assert.equal(state.form[field], "x", field);
      assert.deepEqual({ ...state.form, [field]: form[field] }, form, `only ${field} changed`);
    }
  }
});

test("cancel throws the changes away and leaves an empty form for a new record", () => {
  let state = open(BLANK_COURSE, course.id, formFromCourse(course));
  state = change(state, "course_name", "Should not be saved");
  state = editorReducer(state, { type: "errors", errors: { course_code: "taken" } });
  state = editorReducer(state, { type: "reset", form: BLANK_COURSE });
  assert.deepEqual(state, { editing: null, original: null, form: BLANK_COURSE, errors: {} });
  // Opening the same course again shows its saved values, not what was typed before the cancel.
  assert.equal(open(BLANK_COURSE, course.id, formFromCourse(course)).form.course_name, "Computer Science");
});

test("the record that was opened is never changed by editing the form", () => {
  const form = formFromBatch(batch);
  const before = JSON.stringify(batch);
  change(change(open(BLANK_BATCH, batch.id, form), "course_id", "9"), "status", "active");
  assert.equal(JSON.stringify(batch), before);
  assert.deepEqual(form, formFromBatch(batch));
});

test("opening another record replaces what was typed for the first", () => {
  let state = change(open(BLANK_COURSE, 7, formFromCourse(course)), "course_name", "typed");
  state = editorReducer(state, { type: "edit", id: 8, form: formFromCourse({ ...course, id: 8, course_code: "PHY101", course_name: "Physics" }) });
  assert.equal(state.editing, 8);
  assert.equal(state.form.course_name, "Physics");
});

test("an error under a field goes away when that field is changed, and only that one", () => {
  let state = editorReducer(open(BLANK_BATCH, 3, formFromBatch(batch)), { type: "errors", errors: { batch_name: "exists", course_id: "pick one" } });
  state = change(state, "batch_name", "Other");
  assert.deepEqual(state.errors, { course_id: "pick one" });
});

test("a blank or all-spaces code or name is refused before anything is sent", () => {
  assert.deepEqual(courseErrors({ ...BLANK_COURSE, course_code: "  ", course_name: "" }), { course_code: "Enter a course code.", course_name: "Enter a course name." });
  assert.deepEqual(courseErrors({ ...BLANK_COURSE, course_code: "cs101", course_name: "Computer Science" }), {});
  assert.deepEqual(batchErrors({ ...BLANK_BATCH, batch_name: "   " }), { course_id: "Select a course.", batch_name: "Enter a batch name." });
  assert.deepEqual(batchErrors({ ...BLANK_BATCH, course_id: "7", batch_name: "Morning A" }), {});
});

test("what is sent is trimmed, with the course code in capitals and empty optional fields as null", () => {
  assert.deepEqual(coursePayload({ course_code: " cs101 ", course_name: " Computer Science ", description: "  ", status: "pending" }), { course_code: "CS101", course_name: "Computer Science", description: null, status: "pending" });
  assert.deepEqual(batchPayload({ course_id: "7", batch_name: " Morning A ", batch_level: " Year 1 ", status: "active" }), { course_id: 7, batch_name: "Morning A", batch_level: "Year 1", status: "active" });
});

test("a batch's timing is never sent, so saving the form cannot clear it", () => {
  assert.equal("timing_id" in batchPayload(formFromBatch(batch)), false);
});

test("the status filter lists the statuses a list really holds, in the usual order", () => {
  assert.deepEqual(statusesOf([{ status: "active" }, { status: "active" }]), ["active"]);
  assert.deepEqual(statusesOf([{ status: "inactive" }, { status: "pending" }, { status: "active" }, { status: "archived" }, {}]), ["active", "pending", "inactive", "archived"]);
  assert.deepEqual(statusesOf([]), []);
});
