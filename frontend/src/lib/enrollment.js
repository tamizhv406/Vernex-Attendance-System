// Who the Face Enrollment page lists, and the words it uses for each kind of person, kept apart from
// the screen so that they can be tested (enrollment.test.js). The backend (GET /face/enrollment/users)
// checks the same again: students come from one batch, staff and members are listed in full.
import { PERSON_CONFIG } from "../routes.js";

// Keyed as the People pages are; PERSON_CONFIG holds the backend's person_type for each.
export const ENROLLMENT_GROUPS = ["students", "staff", "members"];

const TEXT = {
  students: {
    pick: "Student",
    scope: "Only students of the selected batch are listed.",
    list: "Students in this batch",
    loading: "Loading students…",
    none: "No students found in this batch",
    noneHint: "Add students to this batch first.",
    choose: "Select a course, a batch and a student on the left.",
    missing: "Select a course, a batch and a student first."
  },
  staff: {
    pick: "Staff member",
    scope: "Every staff member is listed. No course or batch is needed.",
    list: "Staff",
    loading: "Loading staff…",
    none: "No staff found",
    noneHint: "Add staff on the Staff page first.",
    choose: "Select a staff member on the left.",
    missing: "Select a staff member first."
  },
  members: {
    pick: "Member",
    scope: "Every member is listed. No course or batch is needed.",
    list: "Members",
    loading: "Loading members…",
    none: "No members found",
    noneHint: "Add members on the Members page first.",
    choose: "Select a member on the left.",
    missing: "Select a member first."
  }
};

export function groupOptions() {
  return ENROLLMENT_GROUPS.map(group => ({ value: group, label: PERSON_CONFIG[group].title }));
}

export function enrollmentText(group) {
  return TEXT[group] || TEXT.students;
}

// What to ask the backend for, or null while the list cannot be loaded yet: a student list needs a
// course and a batch. Staff and members load as soon as they are chosen.
export function enrollmentQuery(group, courseId, batchId) {
  const config = PERSON_CONFIG[group];
  if (!config || !ENROLLMENT_GROUPS.includes(group)) return null;
  if (group === "students") return courseId && batchId ? { personType: config.apiType, courseId, batchId } : null;
  return { personType: config.apiType };
}

// The search box on the page: by name or person ID, ignoring case.
export function matchesPerson(person, query) {
  const wanted = String(query || "").trim().toLowerCase();
  if (!wanted) return true;
  return [person.full_name, person.person_code].filter(Boolean).join(" ").toLowerCase().includes(wanted);
}

export function pendingText(pending) {
  return pending ? `${pending} more in this list still pending.` : "Everyone in this list is enrolled.";
}
