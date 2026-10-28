// Run with `npm test`. The QR Attendance page's rules. The backend decides who is marked
// (backend/tests/test_code_marking.py); these only decide what is sent and what is shown.
import assert from "node:assert/strict";
import { test } from "node:test";
import { methodLabel } from "./attendance.js";
import { normalizeCode, parseScan } from "./qr.js";
import { DECODE_EVERY_MS, NOT_OURS, REPEAT_MS, RESULT_MS, TYPE_HINT, createScanGate, formatTyped, joinableSession, resultView, typedCodeError } from "./qrScan.js";
import { MOBILE_NAV, NAV_GROUPS, PAGES, PATH_TO_PAGE, ROUTES } from "../routes.js";

const TODAY = "2026-10-28";
const CLASS = { id: 5, session_type: "regular", course_id: 3, batch_id: 7, session_date: TODAY, status: "active" };

test("a session running today for the same scope can be joined, the newest first", () => {
  const sessions = [
    CLASS,
    { ...CLASS, id: 9 },
    { ...CLASS, id: 11, status: "completed" },
    { ...CLASS, id: 12, session_date: "2026-10-27" },
    { ...CLASS, id: 13, batch_id: 8 },
    { id: 20, session_type: "staff", course_id: null, batch_id: null, session_date: TODAY, status: "active" },
    { id: 21, session_type: "member_visit", course_id: null, batch_id: null, session_date: TODAY, status: "active" }
  ];

  assert.equal(joinableSession(sessions, { type: "regular", courseId: "3", batchId: "7" }, TODAY).id, 9);
  assert.equal(joinableSession(sessions, { type: "regular", courseId: "3", batchId: "9" }, TODAY), null);
  assert.equal(joinableSession(sessions, { type: "staff" }, TODAY).id, 20);
  assert.equal(joinableSession(sessions, { type: "member_visit" }, TODAY).id, 21);
  assert.equal(joinableSession([], { type: "staff" }, TODAY), null);
  assert.equal(joinableSession(null, { type: "staff" }, TODAY), null);
});

test("a typed code is shown in capitals with a hyphen after four characters", () => {
  assert.equal(formatTyped("k7m2"), "K7M2");
  assert.equal(formatTyped("k7m29"), "K7M2-9");
  assert.equal(formatTyped("k7m29qxd"), "K7M2-9QXD");
  assert.equal(formatTyped("K7M2-9QXD"), "K7M2-9QXD");
  assert.equal(formatTyped("k7m2 9qxd"), "K7M2-9QXD");
  assert.equal(formatTyped("k7m29qxdzz"), "K7M2-9QXD");
  assert.equal(formatTyped(""), "");
  // A plain code that only starts with V is still a code.
  assert.equal(formatTyped("v7m29qxd"), "V7M2-9QXD");
});

test("a QR reader that types the whole payload is left as it typed it", () => {
  assert.equal(formatTyped("VNXATT:K7M29QXD"), "VNXATT:K7M29QXD");
  assert.equal(formatTyped("vnxatt:k7m2-9qxd"), "VNXATT:K7M2-9QXD");
  assert.equal(formatTyped("VNX"), "VNX");
  assert.equal(normalizeCode(formatTyped("vnxatt:k7m29qxd")), "K7M29QXD");
});

test("only a code is sent from the field; anything else says how a code looks", () => {
  assert.equal(typedCodeError("K7M2-9QXD"), "");
  assert.equal(typedCodeError("k7m29qxd"), "");
  assert.equal(typedCodeError("VNXATT:K7M29QXD"), "");
  for (const text of ["", "K7M2", "K7MU-9QXD", "VNX-S001"]) assert.equal(typedCodeError(text), TYPE_HINT);
});

test("a QR that is not ours is said to be so and sends nothing", () => {
  assert.equal(parseScan("https://example.com").error, NOT_OURS);
  assert.deepEqual(parseScan("VNXATT:K7M29QXD"), { code: "K7M29QXD" });
});

test("one mark at a time, and the same code not again within four seconds of its answer", () => {
  const gate = createScanGate();

  assert.equal(REPEAT_MS, 4000);
  assert.equal(gate.tryStart("K7M29QXD", 0), true);
  // While it waits for its answer, nothing else is sent: not the same card, not another one.
  assert.equal(gate.tryStart("K7M29QXD", 50), false);
  assert.equal(gate.tryStart("AB12CD34", 50), false);
  gate.finish("K7M29QXD", 1000);
  assert.equal(gate.busy, false);
  assert.equal(gate.tryStart("K7M29QXD", 4999), false);
  assert.equal(gate.tryStart("AB12CD34", 1100), true);
  gate.finish("AB12CD34", 1200);
  assert.equal(gate.tryStart("K7M29QXD", 5000), true);
});

test("the camera is looked at about every 150 ms and a result stays three seconds", () => {
  assert.equal(DECODE_EVERY_MS, 150);
  assert.equal(RESULT_MS, 3000);
});

const PERSON = { full_name: "Asha Rao", person_code: "STU-1", course_name: "Comp Sci", batch_name: "Morning A" };

test("green only when the backend says marked, blue when already marked", () => {
  assert.deepEqual(resultView({ data: { result: "marked", attendance_status: "present", person: PERSON } }),
    { tone: "success", title: "Asha Rao: present", name: "Asha Rao", detail: "STU-1 · Comp Sci · Morning A" });
  assert.deepEqual(resultView({ data: { result: "marked", attendance_status: "visited", person: { full_name: "Esha", person_code: "M-1" } } }),
    { tone: "success", title: "Esha: visited", name: "Esha", detail: "M-1" });
  assert.equal(resultView({ data: { result: "already_marked", attendance_status: "late", person: PERSON } }).title, "Already marked: late");
  assert.equal(resultView({ data: { result: "already_marked", attendance_status: "late", person: PERSON } }).tone, "info");
});

test("a refusal shows the backend's sentence in red; no answer, or a server failure, is amber", () => {
  const refused = Object.assign(new Error("Bala Iyer is not in this batch."), { status: 409 });
  assert.deepEqual(resultView({ error: refused }), { tone: "danger", title: "Bala Iyer is not in this batch.", detail: "" });
  assert.equal(resultView({ error: Object.assign(new Error("No one has this code. It may have been replaced by a newer one."), { status: 404 }) }).tone, "danger");
  assert.equal(resultView({ error: Object.assign(new Error("Too many requests. Wait 5 seconds and try again."), { status: 429 }) }).tone, "danger");
  for (const error of [new TypeError("Failed to fetch"), Object.assign(new Error("Bad gateway"), { status: 502 })]) {
    const view = resultView({ error });
    assert.equal(view.tone, "warning");
    assert.equal(view.title, "Not marked. Check the connection and scan again.");
    assert.match(view.detail, /not saved to send later/);
  }
  assert.deepEqual(resultView({ error: { local: true, message: NOT_OURS } }), { tone: "danger", title: NOT_OURS, detail: "" });
  assert.equal(resultView(null), null);
});

test("records say how they were made", () => {
  assert.equal(methodLabel("qr_scan"), "QR scan");
  assert.equal(methodLabel("code_entry"), "Code typed");
  assert.equal(methodLabel("face_ai"), "Face scan");
  assert.equal(methodLabel("manual"), "By hand");
});

test("the QR Attendance page is in the menu under Attendance and on the phone's bar", () => {
  assert.equal(ROUTES.qrScanner, "/qr-attendance");
  assert.equal(PATH_TO_PAGE["/qr-attendance"], "qrScanner");
  assert.deepEqual([PAGES.qrScanner.label, PAGES.qrScanner.title, PAGES.qrScanner.subtitle], ["QR Attendance", "QR Attendance", "Scan a person's QR code, or type their code."]);
  assert.equal(PAGES.qrScanner.roles, undefined);
  assert.deepEqual(NAV_GROUPS.find(group => group.label === "Attendance").items, ["enrollment", "scanner", "qrScanner", "reports"]);
  assert.deepEqual(MOBILE_NAV.right, ["enrollment", "qrScanner"]);
  assert.equal(MOBILE_NAV.left.length + MOBILE_NAV.right.length, 4);
});

test("a card's QR, drawn as pixels, is read back by the fallback decoder as the card's code", async () => {
  const { default: jsQR } = await import("jsqr");
  const { qrMatrix } = await import("./qr.js");
  for (const code of ["K7M29QXD", "00000000", "ZZZZZZZZ"]) {
    const matrix = qrMatrix(code);
    const scale = 4;
    const side = matrix.size * scale;
    const pixels = new Uint8ClampedArray(side * side * 4).fill(255);
    for (const [row, column] of matrix.dark) {
      for (let y = row * scale; y < (row + 1) * scale; y += 1) {
        for (let x = column * scale; x < (column + 1) * scale; x += 1) pixels.fill(0, (y * side + x) * 4, (y * side + x) * 4 + 3);
      }
    }
    const found = jsQR(pixels, side, side, { inversionAttempts: "dontInvert" });

    assert.equal(found?.data, `VNXATT:${code}`);
    assert.deepEqual(parseScan(found.data), { code });
  }
});
