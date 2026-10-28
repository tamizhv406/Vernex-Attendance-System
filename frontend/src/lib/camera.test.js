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

// ---- the head-turn arrow and the server's model outage ----
import { MODELS_UNAVAILABLE_TEXT, modelsUnavailable, turnArrow } from "./camera.js";

test("on a mirrored preview the arrow points to the person's own side", () => {
  // The person sees themselves as in a mirror: their own left is the screen's left.
  assert.equal(turnArrow("left", true), "left");
  assert.equal(turnArrow("right", true), "right");
});

test("on a preview shown as the camera sees it the arrow points the other way", () => {
  // A rear camera pointed at a class: the person's own left is on the screen's right.
  assert.equal(turnArrow("left", false), "right");
  assert.equal(turnArrow("right", false), "left");
});

test("no arrow without a direction the backend asked for", () => {
  for (const direction of [undefined, null, "", "up", "LEFT"]) assert.equal(turnArrow(direction, true), null);
});

test("a 503 models_unavailable from either face route is told apart from a refused frame", () => {
  assert.equal(modelsUnavailable({ status: 503, payload: { quality_status: "models_unavailable", accepted: false } }), true);
  assert.equal(modelsUnavailable({ status: 503, payload: { status: "models_unavailable" } }), true);
  assert.equal(modelsUnavailable({ status: 200, payload: { quality_status: "embedding_failed", accepted: false } }), false);
  assert.equal(modelsUnavailable({ status: 200, payload: { quality_status: "blurry", accepted: false } }), false);
  assert.equal(modelsUnavailable(new Error("offline")), false);
  assert.equal(modelsUnavailable(undefined), false);
});

test("the outage message never blames the face and says what happens next", () => {
  for (const text of Object.values(MODELS_UNAVAILABLE_TEXT)) assert.match(text, /not a problem with the face/);
  assert.match(MODELS_UNAVAILABLE_TEXT.enrollment, /Nothing was saved/);
  assert.match(MODELS_UNAVAILABLE_TEXT.scanner, /Nobody is being marked/);
});
