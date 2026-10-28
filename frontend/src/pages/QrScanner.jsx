import React, { useEffect, useRef, useState } from "react";
import { Camera, CameraOff, Keyboard, LogIn, Play, QrCode, ShieldCheck, Square, Volume2, VolumeX } from "lucide-react";
import { CameraPlaceholder, CameraView, useCamera } from "../camera";
import { completeAttendanceSession, getAttendanceSessions, getSessionRecords, markByCode, session as login, startAttendanceSession } from "../lib/api";
import { SESSION_TYPES, methodLabel, scopePeople, scopeReady, scopeWords, withRecord } from "../lib/attendance";
import { batchName, courseName, formatClock, localDate, mapAttendance } from "../lib/format";
import { normalizeCode, parseScan } from "../lib/qr";
import { DECODE_EVERY_MS, RESULT_MS, createScanGate, formatTyped, joinableSession, resultView, typedCodeError } from "../lib/qrScan";
import { Button, Card, ConfirmDialog, EmptyState, FormInput, FormSelect, Identity, Info, Notice, Page, Segmented, StatusBadge } from "../ui";
import { SessionRegister } from "./handMarks";

const SOUND_KEY = "vernex.qrScanner.sound";
const RESULT_STYLES = {
  success: "bg-emerald-50 text-emerald-900 ring-emerald-600/20",
  info: "bg-sky-50 text-sky-900 ring-sky-600/20",
  danger: "bg-red-50 text-red-900 ring-red-600/20",
  warning: "bg-amber-50 text-amber-900 ring-amber-600/25"
};

function soundSaved() {
  try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; }
}

function saveSound(on) {
  try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch { /* private window: it is only a preference */ }
}

// A short tone: high for marked, low for anything else. Silently nothing where audio is not allowed.
let audio = null;
function beep(ok) {
  try {
    audio = audio || new AudioContext();
    const tone = audio.createOscillator();
    const gain = audio.createGain();
    tone.frequency.value = ok ? 880 : 220;
    gain.gain.value = 0.15;
    tone.connect(gain).connect(audio.destination);
    tone.start();
    tone.stop(audio.currentTime + (ok ? 0.12 : 0.3));
  } catch { /* no audio on this device */ }
}

// The browser's own QR reader where there is one; jsQR on the picture otherwise.
const detector = typeof window !== "undefined" && "BarcodeDetector" in window ? (() => {
  try { return new window.BarcodeDetector({ formats: ["qr_code"] }); } catch { return null; }
})() : null;

let jsqr = null;

async function decode(frame) {
  if (detector) {
    try {
      const found = await detector.detect(frame.canvas);
      if (found.length) return found[0].rawValue;
      return null;
    } catch { /* fall back to jsQR below */ }
  }
  // Loaded the first time it is needed: browsers with their own reader never download it.
  jsqr = jsqr || import("jsqr").then(module => module.default);
  const found = (await jsqr)(frame.imageData.data, frame.imageData.width, frame.imageData.height, { inversionAttempts: "dontInvert" });
  return found?.data || null;
}

export default function QrScanner({ data }) {
  const [sessionType, setSessionType] = useState("regular");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  // "HH:MM", or empty for the batch's timetable (or nobody late at all when it has none).
  const [lateAfter, setLateAfter] = useState("");
  const [activeSession, setActiveSession] = useState(null);
  // A session already running today for this scope (on the face scanner, or another phone).
  const [running, setRunning] = useState(null);
  const [cameraOn, setCameraOn] = useState(true);
  const [result, setResult] = useState(null);
  const [events, setEvents] = useState([]);
  const [typed, setTyped] = useState("");
  const [typedError, setTypedError] = useState("");
  const [sending, setSending] = useState(false);
  const [sound, setSound] = useState(soundSaved);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopping, setStopping] = useState(false);
  const typedRef = useRef(null);
  const gate = useRef(createScanGate());
  const camera = useCamera(Boolean(activeSession) && cameraOn, "environment");
  const scope = { type: sessionType, courseId, batchId };
  const batches = data.batches.filter(batch => Number(batch.course_id) === Number(courseId));
  const sessionRecords = activeSession ? data.records.filter(record => Number(record.session_id) === Number(activeSession.id)) : [];
  const people = scopePeople(data.people, activeSession || scope, sessionRecords);
  const words = scopeWords(activeSession?.session_type || sessionType);
  const markedCount = people.filter(person => sessionRecords.some(record => Number(record.person_id) === Number(person.id))).length;
  const chooseType = next => { setSessionType(next); setCourseId(""); setBatchId(""); };
  useEffect(() => { setBatchId(""); }, [courseId]);

  // A running session of the same scope can be joined instead of starting a second one.
  useEffect(() => {
    setRunning(null);
    if (activeSession || !scopeReady(scope)) return;
    let current = true;
    getAttendanceSessions(sessionType === "regular" ? { course_id: courseId, batch_id: batchId } : {})
      .then(rows => { if (current) setRunning(joinableSession(rows, scope, localDate())); })
      .catch(() => {});
    return () => { current = false; };
  }, [sessionType, courseId, batchId, activeSession]);

  // A session left running is not an idle console: the login stays awake meanwhile.
  useEffect(() => {
    if (!activeSession) return;
    login.keepAwake("qr-scanner", true);
    return () => login.keepAwake("qr-scanner", false);
  }, [activeSession]);

  // The records the session already has (marked on another device, say), so the lists are complete.
  useEffect(() => {
    setEvents([]);
    setResult(null);
    gate.current = createScanGate();
    if (!activeSession) return;
    getSessionRecords(activeSession.id)
      .then(rows => data.setRecords(current => (rows || []).map(mapAttendance).reduce((all, record) => withRecord(all, record), current)))
      .catch(() => {});
  }, [activeSession?.id]);

  useEffect(() => {
    if (!result) return;
    const timer = setTimeout(() => setResult(null), RESULT_MS);
    return () => clearTimeout(timer);
  }, [result]);

  const show = (outcome, ok) => {
    setResult({ ...resultView(outcome), at: Date.now() });
    if (sound) beep(ok);
    try { navigator.vibrate?.(ok ? 80 : [60, 60, 60]); } catch { /* not on this device */ }
  };

  // One mark. Only an answer from the backend says marked; a failure is never shown as one.
  const send = async (code, method) => {
    const session = activeSession;
    try {
      const answer = await markByCode({ session_id: session.id, code, method, device_name: method === "qr_scan" ? "qr-scanner" : "qr-desk" });
      show({ data: answer }, answer.result === "marked");
      if (answer.record) {
        const record = mapAttendance(answer.record);
        data.setRecords(current => withRecord(current, record));
        if (answer.result === "marked") setEvents(current => [record, ...current.filter(item => item.id !== record.id)].slice(0, 12));
      }
    } catch (error) {
      show({ error }, false);
    }
  };

  // The camera: a frame about every 150 ms, decoded on this device; nothing is uploaded but the code.
  useEffect(() => {
    if (!activeSession || !cameraOn) return;
    let stopped = false;
    let looking = false;
    const timer = setInterval(async () => {
      if (stopped || looking || gate.current.busy) return;
      const frame = camera.readFrame(640);
      if (!frame) return;
      looking = true;
      try {
        const text = await decode(frame);
        if (stopped || !text) return;
        const scanned = parseScan(text);
        const key = scanned.code || `other:${text}`;
        if (!gate.current.tryStart(key, performance.now())) return;
        if (scanned.error) {
          show({ error: { local: true, message: scanned.error } }, false);
          gate.current.finish(key, performance.now());
          return;
        }
        await send(scanned.code, "qr_scan");
        gate.current.finish(key, performance.now());
      } finally {
        looking = false;
      }
    }, DECODE_EVERY_MS);
    return () => { stopped = true; clearInterval(timer); };
  }, [activeSession?.id, cameraOn, sound]);

  const submitTyped = async event => {
    event?.preventDefault();
    const problem = typedCodeError(typed);
    if (problem) { setTypedError(problem); return; }
    // Through the same gate as the camera, so a typed code and a scan are never sent at once. A
    // typed code may be sent again at once: the key is new each time.
    const key = `typed:${performance.now()}`;
    if (sending || !gate.current.tryStart(key, performance.now())) return;
    setSending(true);
    setTypedError("");
    await send(normalizeCode(typed), "code_entry");
    gate.current.finish(key, performance.now());
    setSending(false);
    // Ready for the next one at once, which is also what a USB or Bluetooth QR reader needs.
    setTyped("");
    typedRef.current?.focus();
  };

  const start = async () => {
    if (!scopeReady(scope)) { setMessage("Select course and batch to start attendance session."); return; }
    const course = data.courses.find(item => Number(item.id) === Number(courseId));
    const batch = data.batches.find(item => Number(item.id) === Number(batchId));
    setBusy(true);
    setMessage("");
    try {
      const where = sessionType === "regular"
        ? { session_name: `${course?.course_name || "Course"} - ${batch?.batch_name || "Batch"}`, course_id: Number(courseId), batch_id: Number(batchId), timing_id: batch?.timing_id || null }
        : {};
      const started = await startAttendanceSession({ session_type: sessionType, ...where, ...(lateAfter ? { grace_time: `${lateAfter}:00` } : {}) });
      setActiveSession(started);
      data.notify("Attendance session started.");
    } catch (err) {
      setMessage(err.message || "Unable to start attendance session.");
    } finally {
      setBusy(false);
    }
  };
  const join = () => { setActiveSession(running); data.notify(`Joined ${running.session_name}.`); };
  const stop = async () => {
    const session = activeSession;
    setStopping(true);
    try {
      await completeAttendanceSession(session.id);
      setActiveSession(null);
      setConfirmStop(false);
      data.notify("Attendance session stopped on every device.");
    } catch (err) {
      setConfirmStop(false);
      setMessage(err.message || "Unable to stop the session.");
    } finally {
      setStopping(false);
    }
  };
  const handMarked = (record, person) => {
    data.setRecords(current => withRecord(current, record));
    setEvents(current => [record, ...current.filter(item => item.id !== record.id)].slice(0, 12));
    data.notify(`${person.full_name} marked ${record.status} by hand.`);
  };
  const toggleSound = () => setSound(current => { saveSound(!current); return !current; });

  return <Page title="QR Attendance" subtitle="Scan a person's QR code, or type their code." actions={activeSession ? <Button variant="danger" icon={Square} onClick={() => setConfirmStop(true)}>Stop session</Button> : null}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,.75fr)]">
      <div className="space-y-5">
        <Card title="Camera" subtitle={activeSession ? activeSession.session_name : "No session running"} action={activeSession && <div className="flex gap-2">
          <Button size="sm" variant="outline" icon={sound ? Volume2 : VolumeX} onClick={toggleSound} aria-pressed={sound}>{sound ? "Sound on" : "Sound off"}</Button>
          <Button size="sm" variant="outline" icon={cameraOn ? CameraOff : Camera} onClick={() => setCameraOn(current => !current)}>{cameraOn ? "Camera off" : "Camera on"}</Button>
        </div>}>
          {activeSession && cameraOn ? <div className="grid gap-3">
            <CameraView camera={camera} mirror>
              {camera.ready && <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden="true">
                <div className="aspect-square w-[60%] max-w-[22rem] rounded-3xl border-4 border-white/85 shadow-[0_0_0_100vmax_rgba(14,17,22,.4)]" />
              </div>}
            </CameraView>
            {camera.error && <p className="text-sm text-ink-muted">Typing the code below still works without a camera.</p>}
          </div> : <CameraPlaceholder icon={activeSession ? CameraOff : QrCode} title={activeSession ? "Camera off" : "Session stopped"} message={activeSession ? "Type codes below, or turn the camera on to scan QR cards." : "Start or join a session to scan QR cards. The QR is read on this device; no picture is sent."} />}
          <ResultPanel result={result} />
          {activeSession && <p className="mt-3 text-xs text-ink-muted">A mark needs the connection: nothing is kept to send later. If a scan says it was not marked, scan again.</p>}
        </Card>

        {activeSession && <Card title="Type a code" subtitle="For a card that will not scan, or a USB or Bluetooth QR reader.">
          <form className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start" onSubmit={submitTyped}>
            <FormInput ref={typedRef} label="Attendance code" value={typed} placeholder="XXXX-XXXX" autoComplete="off" autoCapitalize="characters" spellCheck={false} inputMode="text" error={typedError}
              onChange={event => { setTyped(formatTyped(event.target.value)); setTypedError(""); }} className="font-mono" />
            <Button variant="brand" icon={Keyboard} loading={sending} className="sm:mt-[26px]">Mark attendance</Button>
          </form>
        </Card>}
      </div>

      <div className="space-y-5">
        <Card title="Session">
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <span className="text-[13px] font-semibold text-ink-soft">Session for</span>
              <fieldset disabled={Boolean(activeSession)} className="disabled:opacity-60">
                <legend className="sr-only">Session for</legend>
                <Segmented label="Session for" value={activeSession?.session_type || sessionType} onChange={chooseType} options={SESSION_TYPES} />
              </fieldset>
            </div>
            {!activeSession && sessionType === "regular" && <>
              <FormSelect label="Course" value={courseId} onChange={e => setCourseId(e.target.value)} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
              <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} options={batches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={courseId ? "Create a batch under this course" : "Select course first"} />
            </>}
            {!activeSession && <FormInput label="Late after (optional)" type="time" value={lateAfter} onChange={e => setLateAfter(e.target.value)} hint={sessionType === "member_visit" ? "Members are marked visited whatever the time." : "People marked after this time are late. Empty: the batch's timetable decides, if it has one."} />}
            {activeSession ? <>
              <div className="grid grid-cols-2 gap-2">
                {activeSession.course_id ? <>
                  <Info label="Course" value={courseName(data.courses, activeSession.course_id)} />
                  <Info label="Batch" value={batchName(data.batches, activeSession.batch_id)} />
                </> : <Info label="For" value={words.list} />}
                <Info label="Date" value={activeSession.session_date} />
                <Info label="Started" value={activeSession.start_time || "-"} />
                <Info label="Late after" value={activeSession.grace_time ? activeSession.grace_time.slice(0, 5) : "Never"} />
              </div>
              <div>
                <div className="flex items-center justify-between text-sm"><span className="font-medium text-ink-soft">Marked this session</span><span className="font-bold tabular-nums text-ink">{markedCount} of {people.length}</span></div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-canvas" role="progressbar" aria-valuemin={0} aria-valuemax={people.length} aria-valuenow={markedCount} aria-label="People marked this session"><div className="h-full rounded-full bg-emerald-500 transition-[width] duration-500 ease-out" style={{ width: people.length ? `${(markedCount / people.length) * 100}%` : "0%" }} /></div>
              </div>
              <Button variant="outline" icon={Square} onClick={() => setConfirmStop(true)}>Stop session</Button>
            </> : <div className="grid gap-2">
              {running && <Notice tone="info">{running.session_name} is already running today{running.start_time ? `, since ${String(running.start_time).slice(0, 5)}` : ""}. Join it to mark into the same register as the other devices.</Notice>}
              {running && <Button variant="brand" icon={LogIn} onClick={join}>Join running session</Button>}
              <Button variant={running ? "outline" : "brand"} icon={Play} loading={busy} disabled={!scopeReady(scope)} onClick={start}>Start new session</Button>
            </div>}
          </div>
        </Card>

        <Card title="Marked in this session" subtitle="Newest first.">
          {!events.length ? <EmptyState icon={ShieldCheck} title="Nobody marked yet" message="A person is listed here the moment the backend writes their record." /> : <ul className="divide-y divide-line">
            {events.map(record => <li key={record.id} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
              <Identity name={record.person_name} detail={`${record.person_code || ""} · ${formatClock(record.marked_time)} · ${methodLabel(record.recognition_method)}`} />
              <StatusBadge status={record.status} />
            </li>)}
          </ul>}
        </Card>
      </div>
    </div>

    {activeSession && <Card title={words.list} subtitle="Mark a person by hand when their card is lost or will not scan, or correct a mark.">
      <SessionRegister session={activeSession} students={people} records={sessionRecords} onRecord={handMarked} loading={data.loading} />
    </Card>}
    <ConfirmDialog open={confirmStop} busy={stopping} title="Stop this session?" message="This stops the session on every device using it." confirmLabel="Stop session" onConfirm={stop} onCancel={() => setConfirmStop(false)} />
  </Page>;
}

// Large and plain, to be read from a metre away. Announced as it changes.
function ResultPanel({ result }) {
  return <div aria-live="assertive" aria-atomic="true" className="mt-3 min-h-[5.5rem]">
    {result && <div key={result.at} className={`animate-fade-up rounded-2xl px-4 py-4 ring-1 ring-inset ${RESULT_STYLES[result.tone]}`}>
      <p className="text-2xl font-extrabold tracking-tight">{result.title}</p>
      {result.tone === "info" && result.name && <p className="mt-0.5 text-lg font-semibold">{result.name}</p>}
      {result.detail && <p className="mt-1 text-sm font-medium opacity-80">{result.detail}</p>}
    </div>}
  </div>;
}
