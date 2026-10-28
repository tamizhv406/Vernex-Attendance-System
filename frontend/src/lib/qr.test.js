// Run with `npm test`. Attendance codes and QR cards: the same rules as the backend
// (backend/app/services/attendance_code_service.py, backend/tests/test_attendance_codes.py).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import QRCode from "qrcode";
import {
  ALPHABET, CARDS_PER_PAGE, QR_OPTIONS, QR_PREFIX, SLOW_PRINT, cardFileName, cardLines, formatCode, normalizeCode, pagesOf, parseScan, printablePeople, qrMatrix, qrPayload, typeLabel
} from "./qr.js";

const backend = readFileSync(new URL("../../../backend/app/services/attendance_code_service.py", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const ASHA = { id: 1, person_code: "VNX-S001", full_name: "Asha Rao", person_type: "student", course_name: "Comp Sci", batch_name: "Morning A", attendance_code: "K7M29QXD" };
const CHITRA = { id: 3, person_code: "VNX-T001", full_name: "Chitra Nair", person_type: "admin", course_name: "", batch_name: "", attendance_code: "AB12CD34" };

test("the alphabet, length and QR prefix are the backend's", () => {
  assert.equal(backend.match(/^ALPHABET = "([^"]+)"$/m)[1], ALPHABET);
  assert.equal(backend.match(/^CODE_LENGTH = (\d+)$/m)[1], "8");
  assert.equal(backend.match(/^QR_PREFIX = "([^"]+)"$/m)[1], QR_PREFIX);
  assert.equal(ALPHABET, "0123456789ABCDEFGHJKMNPQRSTVWXYZ");
});

test("what people type or scan is read as the stored code, as the backend reads it", () => {
  const cases = [
    ["K7M29QXD", "K7M29QXD"], ["K7M2-9QXD", "K7M29QXD"], ["k7m2-9qxd", "K7M29QXD"], ["  K7M2 9QXD  ", "K7M29QXD"],
    ["K7M2 - 9QXD", "K7M29QXD"], ["VNXATT:K7M29QXD", "K7M29QXD"], ["vnxatt:k7m2-9qxd", "K7M29QXD"], ["  VNXATT:K7M2-9QXD\n", "K7M29QXD"],
    ["KOM2-9QXD", "K0M29QXD"], ["KIM2-9QXL", "K1M29QX1"], ["klm29qxd", "K1M29QXD"]
  ];
  for (const [typed, stored] of cases) assert.equal(normalizeCode(typed), stored, typed);
});

test("anything else is not a code", () => {
  const cases = ["", "   ", null, undefined, 12345678, "K7M29QX", "K7M29QXDA", "K7M2-9QX", "K7MU9QXD", "K7M2_9QXD", "K7M2.9QXD", "K7M29QX!",
    "VNXATT:", "VNXATT:K7M2", "https://example.com/K7M29QXD", "VNX:K7M29QXD", "K7M29QXDVNXATT:", "VNXATT:VNXATT:K7M29QXD", "K7M29QXÉ"];
  for (const typed of cases) assert.equal(normalizeCode(typed), null, String(typed));
});

test("a code is shown with a hyphen, and a QR holds only the prefix and the code", () => {
  assert.equal(formatCode("K7M29QXD"), "K7M2-9QXD");
  assert.equal(formatCode(null), "");
  assert.equal(qrPayload("K7M29QXD"), "VNXATT:K7M29QXD");
  assert.equal(qrPayload("k7m2-9qxd"), "VNXATT:K7M29QXD");
  // No code, no QR: nothing else about the person is ever put into one.
  assert.equal(qrPayload(null), null);
  assert.equal(qrPayload("VNX-S001"), null);
  const payload = qrPayload(ASHA.attendance_code);
  for (const detail of [ASHA.person_code, ASHA.full_name, String(ASHA.id), ASHA.course_name]) assert.ok(!payload.includes(detail), detail);
});

test("a scanned QR is ours only with the prefix and a valid code", () => {
  assert.deepEqual(parseScan("VNXATT:K7M29QXD"), { code: "K7M29QXD" });
  assert.deepEqual(parseScan(" vnxatt:k7m2-9qxd "), { code: "K7M29QXD" });
  for (const text of ["K7M29QXD", "https://example.com", "VNXATT:", "VNXATT:K7M2", "VNX-S001", "", null]) {
    assert.deepEqual(parseScan(text), { error: "Not a Vernex attendance QR" }, String(text));
  }
});

test("a card names the type and leaves out a course and batch the person does not have", () => {
  assert.deepEqual(cardLines(ASHA), ["VNX-S001", "Student", "Comp Sci · Morning A"]);
  assert.deepEqual(cardLines(CHITRA), ["VNX-T001", "Staff"]);
  assert.deepEqual(cardLines({ person_code: "M-1", person_type: "member", course_name: "Gym", batch_name: null }), ["M-1", "Member", "Gym"]);
  assert.equal(typeLabel("member"), "Member");
  assert.equal(typeLabel("something"), "Person");
});

test("a downloaded card is called <person ID>-qr.png", () => {
  assert.equal(cardFileName(ASHA), "VNX-S001-qr.png");
  assert.equal(cardFileName({ person_code: "A/B: 1" }), "A_B_1-qr.png");
  assert.equal(cardFileName({}), "person-qr.png");
});

test("only people with a code are printed, ten cards to a page", () => {
  const people = Array.from({ length: 23 }, (_, index) => ({ ...ASHA, id: index, attendance_code: index === 4 ? null : "K7M29QXD" }));
  const printable = printablePeople(people);

  assert.equal(printable.length, 22);
  assert.equal(CARDS_PER_PAGE, 10);
  assert.deepEqual(pagesOf(printable).map(page => page.length), [10, 10, 2]);
  assert.deepEqual(pagesOf([]), []);
  assert.equal(SLOW_PRINT, 300);
});

test("the QR drawn for a card holds exactly the payload, at error correction M with a 4-module quiet zone", async () => {
  assert.deepEqual(QR_OPTIONS, { errorCorrectionLevel: "M", margin: 4 });
  const qr = QRCode.create(qrPayload(ASHA.attendance_code), QR_OPTIONS);

  assert.equal(qr.errorCorrectionLevel.bit, QRCode.create("x", { errorCorrectionLevel: "M" }).errorCorrectionLevel.bit);
  assert.deepEqual(qr.segments.map(segment => segment.data.toString()), ["VNXATT:K7M29QXD"]);
  const svg = await QRCode.toString(qrPayload(ASHA.attendance_code), { ...QR_OPTIONS, type: "svg" });
  assert.match(svg, /^<svg/);
});

test("the grid a card draws is the library's QR of the payload, with the quiet zone around it", () => {
  const matrix = qrMatrix(ASHA.attendance_code);
  const { modules } = QRCode.create("VNXATT:K7M29QXD", { errorCorrectionLevel: "M" });

  assert.equal(matrix.payload, "VNXATT:K7M29QXD");
  assert.equal(matrix.size, modules.size + 8);
  const dark = new Set(matrix.dark.map(([row, column]) => `${row},${column}`));
  for (let row = 0; row < matrix.size; row += 1) {
    for (let column = 0; column < matrix.size; column += 1) {
      const inside = row >= 4 && column >= 4 && row < modules.size + 4 && column < modules.size + 4;
      assert.equal(dark.has(`${row},${column}`), inside && Boolean(modules.get(row - 4, column - 4)), `${row},${column}`);
    }
  }
  assert.equal(matrix.path.split("z").length - 1, matrix.dark.length);
  assert.equal(qrMatrix(null), null);
  assert.equal(qrMatrix("VNX-S001"), null);
});
