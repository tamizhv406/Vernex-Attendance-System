// Run with `npm test`. Which camera previews are shown like a mirror (enrollment and the scanner alike).
import assert from "node:assert/strict";
import { test } from "node:test";
import { facesThePerson } from "./camera.js";

test("a camera that says it faces the person is a mirror, one that faces away is not", () => {
  assert.equal(facesThePerson("user", "environment", true), true);
  assert.equal(facesThePerson("environment", "user", false), false);
});

test("a desktop webcam that says nothing faces whoever sits at the computer", () => {
  // The scanner asks for "environment"; a webcam ignores it. The 15 October scan was such a case,
  // and its preview was not mirrored while the enrollment preview was.
  assert.equal(facesThePerson("", "environment", false), true);
  assert.equal(facesThePerson("", "user", false), true);
});

test("on a touch screen that says nothing, the camera asked for decides", () => {
  assert.equal(facesThePerson("", "environment", true), false);
  assert.equal(facesThePerson("", "user", true), true);
});
