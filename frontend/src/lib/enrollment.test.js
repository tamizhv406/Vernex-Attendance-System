// Run with `npm test`. Who the Face Enrollment page lists and what it asks the backend for. The
// backend checks the same again (backend/tests/test_face_routes.py).
import assert from "node:assert/strict";
import { test } from "node:test";
import { ENROLLMENT_GROUPS, enrollmentQuery, enrollmentText, groupOptions, matchesPerson, pendingText } from "./enrollment.js";
import { PAGES } from "../routes.js";

const ASHA = { id: 1, full_name: "Asha Rao", person_code: "VNX-T001", phone: "9876543210", course_name: "Comp Sci" };

test("the page offers students, staff and members, named as on the People pages", () => {
  assert.deepEqual(groupOptions(), [
    { value: "students", label: "Students" },
    { value: "staff", label: "Staff" },
    { value: "members", label: "Members" }
  ]);
  assert.deepEqual(ENROLLMENT_GROUPS, ["students", "staff", "members"]);
});

test("a student list waits for a course and a batch", () => {
  assert.equal(enrollmentQuery("students", "", ""), null);
  assert.equal(enrollmentQuery("students", "3", ""), null);
  assert.equal(enrollmentQuery("students", "", "7"), null);
  assert.deepEqual(enrollmentQuery("students", "3", "7"), { personType: "student", courseId: "3", batchId: "7" });
});

test("staff and members load at once, without a course or batch", () => {
  // Staff are person_type "admin" in the backend; that is not a login account.
  assert.deepEqual(enrollmentQuery("staff", "", ""), { personType: "admin" });
  assert.deepEqual(enrollmentQuery("members", "", ""), { personType: "member" });
  // A course or batch left over from the student list is not sent.
  assert.deepEqual(enrollmentQuery("staff", "3", "7"), { personType: "admin" });
});

test("anything else loads nothing", () => {
  assert.equal(enrollmentQuery("admins", "3", "7"), null);
  assert.equal(enrollmentQuery(undefined, "3", "7"), null);
});

test("the search matches a name or a person ID, ignoring case and spaces around it", () => {
  assert.equal(matchesPerson(ASHA, ""), true);
  assert.equal(matchesPerson(ASHA, "  "), true);
  assert.equal(matchesPerson(ASHA, "asha"), true);
  assert.equal(matchesPerson(ASHA, " RAO "), true);
  assert.equal(matchesPerson(ASHA, "vnx-t001"), true);
  assert.equal(matchesPerson(ASHA, "Ravi"), false);
  // Only the name and the ID are searched, not the phone or the course.
  assert.equal(matchesPerson(ASHA, "98765"), false);
  assert.equal(matchesPerson(ASHA, "comp"), false);
});

test("nothing says student when the list is staff or members", () => {
  for (const group of ["staff", "members"]) {
    for (const words of Object.values(enrollmentText(group))) assert.doesNotMatch(words, /student/i, `${group}: ${words}`);
  }
  assert.equal(enrollmentText("staff").pick, "Staff member");
  assert.equal(enrollmentText("members").pick, "Member");
  assert.equal(enrollmentText("students").list, "Students in this batch");
  assert.equal(enrollmentText("staff").list, "Staff");
  assert.equal(enrollmentText("members").list, "Members");
  assert.doesNotMatch(PAGES.enrollment.subtitle, /student/i);
});

test("the finished message counts the list, not the batch", () => {
  assert.equal(pendingText(2), "2 more in this list still pending.");
  assert.equal(pendingText(0), "Everyone in this list is enrolled.");
});
