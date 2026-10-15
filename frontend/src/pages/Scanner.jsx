import React, { useEffect, useRef, useState } from "react";
import { MoveHorizontal, Play, ScanFace, ScanLine, ShieldCheck, Square, Sun, Timer, Users, Video } from "lucide-react";
import { CameraPlaceholder, CameraView, faceVerdict, useCamera } from "../camera";
import { completeAttendanceSession, recognizeFace, session as login, startAttendanceSession } from "../lib/api";
import { withRecord } from "../lib/attendance";
import { batchName, courseName, faceEnrolled, formatClock, mapAttendance } from "../lib/format";
import { Button, Card, DataTable, EmptyState, FormInput, FormSelect, Identity, Info, Notice, Page, StatusBadge, tone } from "../ui";
import { SessionRegister } from "./handMarks";

export default function AttendanceScanner({ data }) {
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  // "HH:MM", or empty for the batch's timetable (or nobody late at all when it has none).
  const [lateAfter, setLateAfter] = useState("");
  const [activeSession, setActiveSession] = useState(null);
  const [scan, setScan] = useState({ faces: [], frame: null, status: "" });
  // Names this camera to the backend, which follows faces per camera: two phones scanning the same
  // class never have their sightings of a student added together.
  const scannerId = useRef(`scanner-${Math.random().toString(36).slice(2, 10)}`);
  const [marks, setMarks] = useState({});
  const [events, setEvents] = useState([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const camera = useCamera(Boolean(activeSession));
  const batches = data.batches.filter(batch => Number(batch.course_id) === Number(courseId));
  const students = data.people.filter(person => person.person_type === "student" && Number(person.course_id) === Number(courseId) && Number(person.batch_id) === Number(batchId));
  useEffect(() => { setBatchId(""); setActiveSession(null); }, [courseId]);
  // A scanner left running through a class is not an idle console: it stays logged in meanwhile.
  useEffect(() => {
    if (!activeSession) return;
    login.keepAwake("scanner", true);
    return () => login.keepAwake("scanner", false);
  }, [activeSession]);
  useEffect(() => {
    setScan({ faces: [], frame: null, status: "" });
    if (!activeSession) return;
    setMarks({});
    setEvents([]);
    // Live loop: grab a frame from the camera, let the backend detect and recognize every face in it,
    // then draw the boxes. The backend marks attendance itself, so one request per frame is enough.
    let stopped = false;
    // How long the previous frame took to come back, sent along with the next one so the backend's
    // timing log shows the time spent outside it (network, this device) as well as inside.
    let roundtrip = null;
    const run = async () => {
      while (!stopped) {
        const captureStarted = performance.now();
        const shot = await camera.capture();
        if (shot) {
          try {
            const form = new FormData();
            form.append("image", shot.blob, "frame.jpg");
            form.append("session_id", activeSession.id);
            form.append("device_name", "frontend-scanner");
            form.append("scanner_id", scannerId.current);
            form.append("client_capture_ms", (performance.now() - captureStarted).toFixed(1));
            if (roundtrip !== null) form.append("client_roundtrip_ms", roundtrip.toFixed(1));
            const sent = performance.now();
            const result = await recognizeFace(form);
            roundtrip = performance.now() - sent;
            if (stopped) return;
            if (result.status === "busy") {
              // The frame was not looked at, so there is nothing to draw and nobody was checked.
              setScan(current => ({ ...current, faces: [], status: "The server is busy with earlier frames. This frame was skipped." }));
              await new Promise(resolve => setTimeout(resolve, 400));
              continue;
            }
            const faces = result.faces || [];
            const count = (...names) => faces.filter(face => names.includes(face.result)).length;
            const status = faces.length
              ? `${faces.length} face(s) in view: ${count("verified", "already_marked")} marked, ${count("pending", "challenge")} being verified, ${count("unknown", "ambiguous", "liveness_failed", "challenge_failed", "locked", "not_marked")} not verified, ${count("low_quality", "liveness_uncertain")} unclear`
              : "No face in view";
            setScan({ faces, frame: result.frame, status, ms: result.processing_ms });
            const marked = faces.filter(face => face.person_id && face.attendance_status);
            if (marked.length) setMarks(current => ({ ...current, ...Object.fromEntries(marked.map(face => [face.person_id, face.attendance_status])) }));
            const fresh = faces.filter(face => face.record).map(face => mapAttendance(face.record));
            if (fresh.length) {
              data.setRecords(current => [...fresh, ...current]);
              setEvents(current => [...fresh, ...current].slice(0, 8));
              data.notify(`${fresh.map(record => record.person_name).join(", ")} marked ${fresh[0].status}.`);
            }
            setMessage("");
          } catch (err) {
            if (stopped) return;
            // Boxes from an earlier frame say nothing about what is in front of the camera now.
            setScan(current => ({ ...current, faces: [], status: "" }));
            setMessage(err.message || "Unable to recognize faces.");
          }
        }
        // The next frame goes out as soon as this one is answered, so the boxes keep up with movement.
        await new Promise(resolve => setTimeout(resolve, shot ? 20 : 500));
      }
    };
    run();
    return () => { stopped = true; };
  }, [activeSession]);
  const start = async () => {
    if (!courseId || !batchId) { setMessage("Select course and batch to start attendance session."); return; }
    const course = data.courses.find(item => Number(item.id) === Number(courseId));
    const batch = data.batches.find(item => Number(item.id) === Number(batchId));
    setBusy(true);
    setMessage("");
    try {
      const session = await startAttendanceSession({
        session_name: `${course?.course_name || "Course"} - ${batch?.batch_name || "Batch"}`,
        session_type: "regular",
        course_id: Number(courseId),
        batch_id: Number(batchId),
        timing_id: batch?.timing_id || null,
        // No date or start time: the backend takes both from the school's own clock. (The browser's
        // toISOString() is the UTC date, which in India is still yesterday until 05:30.)
        ...(lateAfter ? { grace_time: `${lateAfter}:00` } : {})
      });
      setActiveSession(session);
      data.notify("Attendance session started.");
    } catch (err) {
      setMessage(err.message || "Unable to start attendance session.");
    } finally {
      setBusy(false);
    }
  };
  const stop = async () => {
    const session = activeSession;
    setStopping(true);
    setActiveSession(null);
    try {
      await completeAttendanceSession(session.id);
      data.notify("Attendance session completed.");
    } catch (err) {
      setMessage(err.message || "Unable to complete attendance session.");
    } finally {
      setStopping(false);
    }
  };
  const sessionRecords = activeSession ? data.records.filter(record => Number(record.session_id) === Number(activeSession.id)) : [];
  const markedCount = students.filter(student => marks[student.id] || sessionRecords.some(record => Number(record.person_id) === Number(student.id))).length;
  // A student marked or corrected by hand: the same lists the scanner's marks go to.
  const handMarked = (record, student) => {
    data.setRecords(current => withRecord(current, record));
    setMarks(current => ({ ...current, [student.id]: record.status }));
    setEvents(current => [record, ...current.filter(item => item.id !== record.id)].slice(0, 8));
    data.notify(`${student.full_name} marked ${record.status} by hand.`);
  };
  const notEnrolled = students.filter(student => !faceEnrolled(student)).length;
  const asking = scan.faces.some(face => face.result === "challenge");

  return <Page title="Live Attendance" subtitle="Pick a course and batch, start a session, then point the camera at the class." actions={activeSession ? <Button variant="danger" icon={Square} loading={stopping} onClick={stop}>Stop session</Button> : null}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,.75fr)]">
      <Card title="Camera" subtitle={activeSession ? activeSession.session_name : "No session running"} action={<StatusBadge tone={activeSession ? "success" : "neutral"}>{activeSession ? "Session active" : "Stopped"}</StatusBadge>}>
        {activeSession ? <div className="grid gap-3">
          <CameraView camera={camera} faces={scan.faces} frame={scan.frame} mirror />
          <p className="flex items-start gap-2 text-sm font-medium text-ink-muted" aria-live="polite">
            <span className="relative mt-1.5 flex h-2 w-2 shrink-0" aria-hidden="true"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" /></span>
            {scan.status || "Starting camera and loading face models. The first scan can take a minute."}
          </p>
          {asking && <Notice tone="info">Blue boxes: that student holds still, facing the camera, then turns their head the way their box says (their own left or right). A photo or a video cannot follow the instruction. A student who cannot be verified is marked by hand below.</Notice>}
          {scan.ms > 1200 && <Notice tone="warning">Each frame takes about {(scan.ms / 1000).toFixed(1)} s to check on this computer. A student is marked after {scan.faces[0]?.confirm_needed || 3} separate checks, so everyone needs to stay in view for a few seconds.</Notice>}
          <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-muted" aria-label="Box colours">
            <Legend swatch="bg-emerald-500">Identity verified, marked</Legend>
            <Legend swatch="bg-sky-600">Follow the head-turn instruction</Legend>
            <Legend swatch="bg-amber-500">Still being verified</Legend>
            <Legend swatch="bg-red-500">Not verified, not marked</Legend>
            <Legend swatch="bg-slate-500">Too small, dark or blurred, or not clearly a real face</Legend>
          </ul>
        </div> : <CameraPlaceholder icon={Video} title="Session stopped" message="Start a session to open the camera. Attendance is written only after the backend has verified a face." />}
      </Card>

      <div className="space-y-5">
        <Card title="Session">
          <div className="grid gap-4">
            <FormSelect label="Course" value={courseId} onChange={e => setCourseId(e.target.value)} disabled={Boolean(activeSession)} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
            <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} disabled={Boolean(activeSession)} options={batches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={courseId ? "Create a batch under this course" : "Select course first"} />
            {!activeSession && <FormInput label="Late after (optional)" type="time" value={lateAfter} onChange={e => setLateAfter(e.target.value)} hint="Students marked after this time are late. Empty: the batch's timetable decides, if it has one." />}
            {!activeSession && courseId && batchId && notEnrolled > 0 && <Notice tone="warning">{notEnrolled} of {students.length} students in this batch have no face enrolled and cannot be recognized.</Notice>}
            {activeSession ? <>
              <div className="grid grid-cols-2 gap-2">
                <Info label="Course" value={courseName(data.courses, activeSession.course_id)} />
                <Info label="Batch" value={batchName(data.batches, activeSession.batch_id)} />
                <Info label="Date" value={activeSession.session_date} />
                <Info label="Started" value={activeSession.start_time || "-"} />
                <Info label="Late after" value={activeSession.grace_time ? activeSession.grace_time.slice(0, 5) : "Never"} />
                <Info label="Absent after" value={activeSession.end_time ? activeSession.end_time.slice(0, 5) : "Never"} />
              </div>
              <div>
                <div className="flex items-center justify-between text-sm"><span className="font-medium text-ink-soft">Marked this session</span><span className="font-bold tabular-nums text-ink">{markedCount} of {students.length}</span></div>
                <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-canvas" role="progressbar" aria-valuemin={0} aria-valuemax={students.length} aria-valuenow={markedCount} aria-label="Students marked this session"><div className="h-full rounded-full bg-emerald-500 transition-[width] duration-500 ease-out" style={{ width: students.length ? `${(markedCount / students.length) * 100}%` : "0%" }} /></div>
              </div>
              <Button variant="outline" icon={Square} loading={stopping} onClick={stop}>Stop session</Button>
            </> : <Button variant="brand" icon={Play} loading={busy} disabled={!courseId || !batchId} onClick={start}>Start session</Button>}
          </div>
        </Card>

        <Card title="Faces in view" subtitle="The backend's verdict for each face in the last frame.">
          {!activeSession ? <EmptyState icon={ScanFace} title="Session not started" message="Faces appear here while a session is running." /> : !scan.faces.length ? <EmptyState icon={ScanLine} title="Waiting for faces" message="Bring people closer to the camera and make sure faces are evenly lit." /> : <ul className="grid gap-3" aria-live="polite">
            {scan.faces.map((face, index) => <FaceRow key={face.track_id ?? index} face={face} />)}
          </ul>}
        </Card>
      </div>
    </div>

    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,.75fr)]">
      <Card title="Students in this batch" subtitle={activeSession ? "Mark a student by hand when the scanner cannot (locked, not recognized, no face enrolled), or correct a mark." : students.length ? `${students.length} student${students.length === 1 ? "" : "s"}` : undefined}>
        {activeSession ? <SessionRegister session={activeSession} students={students} records={sessionRecords} onRecord={handMarked} loading={data.loading} /> : <DataTable loading={data.loading} caption="Students in the selected batch" columns={["Student", "Face", "This session"]} rowKeys={students.map(student => student.id)} rows={students.map(student => [
          <Identity name={student.full_name} detail={student.person_code} />,
          <StatusBadge status={faceEnrolled(student) ? "Enrolled" : "Pending"} />,
          marks[student.id] ? <StatusBadge status={marks[student.id]} /> : <StatusBadge tone="neutral">Not marked</StatusBadge>
        ])} empty={<EmptyState icon={Users} title={courseId && batchId ? "No students found in this batch" : "Select a course and batch"} message={courseId && batchId ? "Add students to this batch first." : "The roster of the batch is listed here."} />} />}
      </Card>

      <div className="space-y-5">
        <Card title="Marked in this session" subtitle="Newest first.">
          {!events.length ? <EmptyState icon={ShieldCheck} title="Nobody marked yet" message="A person is listed here the moment the backend writes their record." /> : <ul className="divide-y divide-line">
            {events.map(record => <li key={record.id ?? `${record.person_id}-${record.marked_time}`} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
              <Identity name={record.person_name} detail={`${record.person_code || ""} · ${formatClock(record.marked_time)}`} />
              <StatusBadge status={record.status} />
            </li>)}
          </ul>}
        </Card>
        <Card title="For reliable scans">
          <ul className="grid gap-3 text-sm text-ink-soft">
            <Tip icon={Sun}>Even light on faces. Avoid a bright window behind the class.</Tip>
            <Tip icon={Timer}>Each person stays in view for a few seconds while several separate looks are checked.</Tip>
            <Tip icon={MoveHorizontal}>When a box turns blue, hold still facing the camera, then turn your head the way it says.</Tip>
            <Tip icon={ShieldCheck}>A face judged to be a photo or a screen is rejected and not marked.</Tip>
          </ul>
        </Card>
      </div>
    </div>
  </Page>;
}

function FaceRow({ face }) {
  const verdict = faceVerdict(face);
  const style = tone(verdict.tone);
  return <li className={`rounded-2xl border p-3 ${verdict.ask ? "border-sky-200 bg-sky-50" : "border-line bg-canvas/50"}`}>
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate font-semibold text-ink">{verdict.name || "Unknown person"}</p>
        {verdict.name === face.person_name && face.person_code && <p className="truncate text-xs text-ink-muted">{face.person_code}</p>}
      </div>
      <StatusBadge tone={verdict.tone}>{verdict.label}</StatusBadge>
    </div>
    <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
      <Check label="Face" value="Detected" />
      <Check label="Identity" value={verdict.identity} />
      <Check label="Liveness" value={verdict.liveness} />
    </dl>
    {verdict.name === face.person_name && typeof face.confidence_score === "number" && <p className="mt-2 text-xs text-ink-muted">Similarity to enrolled face: <span className={`font-semibold tabular-nums ${style.text}`}>{face.confidence_score.toFixed(2)}</span> (0 to 1)</p>}
    {verdict.note && <p className="mt-2 text-xs text-ink-muted">{verdict.note}</p>}
  </li>;
}

function Check({ label, value }) {
  return <div className="rounded-xl bg-white px-2 py-1.5 ring-1 ring-inset ring-line">
    <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">{label}</dt>
    <dd className="mt-0.5 truncate text-xs font-semibold text-ink">{value}</dd>
  </div>;
}

function Legend({ swatch, children }) {
  return <li className="flex items-center gap-1.5"><span className={`h-2.5 w-2.5 shrink-0 rounded-sm ${swatch}`} aria-hidden="true" />{children}</li>;
}

function Tip({ icon: Icon, children }) {
  return <li className="flex items-start gap-3"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-canvas text-ink-muted"><Icon size={16} aria-hidden="true" /></span><span className="pt-1">{children}</span></li>;
}
