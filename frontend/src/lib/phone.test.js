// Run with `npm test` (Node's built-in test runner; nothing to install).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { checkPhone } from "./phone.js";

// The same cases the backend's normalize_phone is tested with (backend/tests/test_phone_validation.py).
const cases = JSON.parse(readFileSync(new URL("../../../backend/tests/data/phone_cases.json", import.meta.url), "utf8"));

test("every number the backend accepts is accepted here, and becomes the same ten digits", () => {
  assert.ok(cases.accepted.length > 10);
  for (const { input, value } of cases.accepted) assert.deepEqual(checkPhone(input), { value }, `input ${JSON.stringify(input)}`);
});

test("every number the backend refuses is refused here, with the same words", () => {
  assert.ok(cases.rejected.length > 20);
  for (const { input, error } of cases.rejected) assert.deepEqual(checkPhone(input), { error }, `input ${JSON.stringify(input)}`);
});

test("the cases the requirements name", () => {
  assert.equal(checkPhone("123").error, "Phone number must have exactly 10 digits (found 3)");
  assert.equal(checkPhone("987654321").error, "Phone number must have exactly 10 digits (found 9)");
  assert.equal(checkPhone("9876543210").value, "9876543210");
  assert.equal(checkPhone("98765-43210").value, "9876543210");
  assert.equal(checkPhone("+91 98765 43210").value, "9876543210");
  assert.ok(checkPhone("+1 98765 43210").error);
  assert.ok(checkPhone("phone").error);
});

test("a missing value is refused, not treated as a number", () => {
  for (const nothing of [undefined, null, ""]) assert.deepEqual(checkPhone(nothing), { error: "Enter a phone number" });
});

test("a number given as a number is read like the text it prints as", () => {
  assert.deepEqual(checkPhone(9876543210), { value: "9876543210" });
});
