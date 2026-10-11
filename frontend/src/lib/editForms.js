// The "new / edit" form of the Courses and Batches pages: what it holds and what each action does
// to it. Kept apart from the screen so that it can be tested (editForms.test.js).
//
// Editing ends in exactly two ways: "reset" (Cancel, a finished save, or the record being deleted)
// and opening another record with "edit". Changing a field, whichever field, never ends it. On the
// Batches page the Course field used to be the list's filter as well, and changing it threw the
// edit away; the next press of the button then created a second batch.

export const BLANK_COURSE = { course_code: "", course_name: "", description: "", status: "active" };
export const BLANK_BATCH = { course_id: "", batch_name: "", batch_level: "", status: "active" };

const text = value => (value === null || value === undefined ? "" : String(value));

export function formFromCourse(course) {
  return { course_code: text(course.course_code), course_name: text(course.course_name), description: text(course.description), status: course.status || "active" };
}

export function formFromBatch(batch) {
  return { course_id: text(batch.course_id), batch_name: text(batch.batch_name), batch_level: text(batch.batch_level), status: batch.status || "active" };
}

export function startEditor(form) {
  return { editing: null, original: null, form, errors: {} };
}

export function editorReducer(state, action) {
  switch (action.type) {
    case "edit":
      // Every field takes the record's own value; nothing is left over from what was typed before.
      return { editing: action.id, original: action.form, form: action.form, errors: {} };
    case "change": {
      const { [action.field]: _fixed, ...errors } = state.errors;
      return { ...state, form: { ...state.form, [action.field]: action.value }, errors };
    }
    case "errors":
      return { ...state, errors: action.errors };
    case "reset":
      return startEditor(action.form);
    default:
      return state;
  }
}

export function courseErrors(form) {
  const errors = {};
  if (!form.course_code.trim()) errors.course_code = "Enter a course code.";
  if (!form.course_name.trim()) errors.course_name = "Enter a course name.";
  return errors;
}

// What is sent to the backend: trimmed, the code in capitals as it will be stored.
export function coursePayload(form) {
  return { course_code: form.course_code.trim().toUpperCase(), course_name: form.course_name.trim(), description: form.description.trim() || null, status: form.status };
}

export function batchErrors(form) {
  const errors = {};
  if (!form.course_id) errors.course_id = "Select a course.";
  if (!form.batch_name.trim()) errors.batch_name = "Enter a batch name.";
  return errors;
}

export function batchPayload(form) {
  return { course_id: Number(form.course_id), batch_name: form.batch_name.trim(), batch_level: form.batch_level.trim() || null, status: form.status };
}

// The statuses a list really holds, in the usual order. One status means there is nothing to filter.
export function statusesOf(rows, known = ["active", "pending", "inactive"]) {
  const found = [...new Set(rows.map(row => row.status || "active"))];
  return [...known.filter(status => found.includes(status)), ...found.filter(status => !known.includes(status)).sort()];
}
