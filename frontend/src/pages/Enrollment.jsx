import React, { useEffect, useState } from "react";
import { Check, Glasses, Info as InfoIcon, Loader2, ScanFace, Sun, TriangleAlert, UserRound, Users } from "lucide-react";
import { CameraPlaceholder, CameraView, useCamera } from "../camera";
import { cancelFaceEnrollment, getEnrollmentUsers, sendEnrollmentFrame, startFaceEnrollment } from "../lib/api";
import { MODELS_UNAVAILABLE_TEXT, modelsUnavailable } from "../lib/camera";
import { enrollmentQuery, enrollmentText, groupOptions, matchesPerson, pendingText } from "../lib/enrollment";
import { faceEnrolled, mapPerson, titleCase } from "../lib/format";
import { Button, Card, DataTable, EmptyState, FormSelect, Identity, Notice, Page, SearchInput, Segmented, StatusBadge } from "../ui";

const ENROLLMENT_STEPS = ["front", "left", "right", "close", "far"];
const ENROLLMENT_FIRST_STEP = { step: "front", instruction: "Look straight", progress: 0 };
// The short instruction shown in large type for each reason the backend refuses a frame.
const ENROLL_HEADLINES = {
  no_face: "No face found",
  multiple: "One person at a time",
  cut_off: "Keep your whole face in view",
  not_centered: "Centre your face in the oval",
  too_far: "Move closer",
  too_close: "Move back",
  low_light: "Improve lighting",
  too_bright: "Improve lighting",
  blurry: "Hold still",
  unclear: "Face not clear",
  sunglasses: "Remove sunglasses",
  pose: "Pose not accepted",
  spoof: "Real face needed",
  liveness_uncertain: "Improve lighting",
  mismatch: "Different face detected",
  busy: "Please wait",
  save_failed: "Saving failed, retrying",
  embedding_failed: "Could not read the face"
};
const MODES = [
  { value: "quick", label: "Quick", detail: "Look straight, then left and right. A few seconds." },
  { value: "guided", label: "Full", detail: "Five poses: front, left, right, close and far." }
];

export default function FaceEnrollment({ data }) {
  // "students", "staff" or "members". Students are picked from a batch; the others are listed in full.
  const [group, setGroup] = useState("students");
  const [query, setQuery] = useState("");
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [people, setPeople] = useState([]);
  const [loadingPeople, setLoadingPeople] = useState(false);
  const [personId, setPersonId] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [capture, setCapture] = useState(null);
  const [hint, setHint] = useState("");
  const [headline, setHeadline] = useState("");
  const [holding, setHolding] = useState(false);
  const [finished, setFinished] = useState(null);
  const [tick, setTick] = useState(false);
  // "quick": the few poses the backend is set to (front, left, right). "guided": all five.
  const [mode, setMode] = useState("quick");
  // Face vectors are biometric data: nothing is captured before this is confirmed, for each person.
  const [consent, setConsent] = useState(false);
  useEffect(() => { setConsent(false); }, [personId]);
  const [steps, setSteps] = useState(ENROLLMENT_STEPS);
  // People enroll their own face, so start on the camera that looks at them.
  const camera = useCamera(Boolean(capture), "user");
  const text = enrollmentText(group);
  const batches = data.batches.filter(batch => Number(batch.course_id) === Number(courseId));
  // Switching between students, staff and members starts the choice over.
  const chooseGroup = next => {
    if (next === group) return;
    setGroup(next);
    setCourseId("");
    setBatchId("");
    setQuery("");
    setPeople([]);
    setPersonId("");
    setConsent(false);
    setFinished(null);
  };
  useEffect(() => {
    setBatchId("");
    setPeople([]);
    setPersonId("");
  }, [courseId]);
  useEffect(() => {
    const wanted = enrollmentQuery(group, courseId, batchId);
    if (!wanted) {
      setPeople([]);
      setPersonId("");
      return;
    }
    // A list asked for before the last switch must not replace the one asked for after it.
    let current = true;
    setLoadingPeople(true);
    getEnrollmentUsers(wanted)
      .then(rows => {
        if (!current) return;
        const mapped = (rows || []).map(mapPerson);
        setPeople(mapped);
        setPersonId(mapped[0]?.id || "");
      })
      .catch(err => { if (current) setMessage(err.message || "Unable to load enrollment users."); })
      .finally(() => { if (current) setLoadingPeople(false); });
    return () => { current = false; };
  }, [group, courseId, batchId]);
  useEffect(() => { setCapture(null); setHint(""); setHeadline(""); setFinished(null); }, [personId]);
  const visible = people.filter(person => matchesPerson(person, query));
  const selected = people.find(person => Number(person.id) === Number(personId));
  // The search narrows the select too, so the chosen person is always one the select shows.
  const search = value => {
    setQuery(value);
    const shown = people.filter(person => matchesPerson(person, value));
    if (!shown.some(person => Number(person.id) === Number(personId))) setPersonId(shown[0]?.id || "");
  };
  const start = async () => {
    if (!selected) { setMessage(text.missing); return; }
    setBusy(true);
    setMessage("");
    try {
      // The backend decides which poses this enrollment has; the page only follows.
      const started = await startFaceEnrollment(selected.id, mode, consent);
      const poses = started?.steps?.length ? started.steps : ENROLLMENT_STEPS;
      setSteps(poses);
      setCapture({ ...ENROLLMENT_FIRST_STEP, step: poses[0], instruction: started?.instruction || ENROLLMENT_FIRST_STEP.instruction });
      setHint("");
      setHeadline("");
      setHolding(false);
      setFinished(null);
      data.notify(`Enrollment started for ${selected.full_name}.`);
    } catch (err) {
      setMessage(err.message || "Unable to start enrollment.");
    } finally {
      setBusy(false);
    }
  };
  const step = capture?.step;
  useEffect(() => {
    if (!tick) return;
    const timer = setTimeout(() => setTick(false), 1500);
    return () => clearTimeout(timer);
  }, [tick]);
  useEffect(() => {
    if (!step) return;
    // Auto capture: keep sending frames for the current step. The backend takes a pose once it has
    // seen a few good frames in a row, and answers "hold still" for the ones before that.
    let stopped = false;
    let failures = 0;
    // The previous frame's round trip, reported with the next frame for the backend's timing log.
    let roundtrip = null;
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    const run = async () => {
      // The first pose starts the moment the camera delivers a picture: the person is already
      // looking at it. Later poses leave a moment to read the new instruction and move.
      if (step !== steps[0]) await wait(1200);
      while (!stopped) {
        const captureStarted = performance.now();
        const shot = await camera.capture();
        // No picture yet means the camera is still starting, so look again soon. After a refused
        // frame, a short pause is enough: the backend answers those quickly.
        let pause = shot ? 350 : 150;
        if (shot) {
          try {
            const form = new FormData();
            form.append("image", shot.blob, "frame.jpg");
            form.append("person_id", selected.id);
            form.append("current_step", step);
            form.append("client_capture_ms", (performance.now() - captureStarted).toFixed(1));
            if (roundtrip !== null) form.append("client_roundtrip_ms", roundtrip.toFixed(1));
            const sent = performance.now();
            const result = await sendEnrollmentFrame(form).finally(() => { roundtrip = performance.now() - sent; });
            if (stopped) return;
            failures = 0;
            if (result.accepted) {
              setTick(true);
              setHolding(false);
              setHeadline("");
              if (result.completed) {
                // Leave the tick on screen for a moment before the camera closes.
                await wait(600);
                if (stopped) return;
                setCapture(null);
                setHint("");
                setFinished(selected.full_name);
                setPeople(rows => rows.map(row => row.id === selected.id ? { ...row, face_enrollment_status: "completed" } : row));
                data.notify(`Face enrollment completed for ${selected.full_name}.`);
                await data.refresh();
              } else {
                setCapture({ step: result.next_step, instruction: result.instruction, progress: result.progress_percentage });
                setHint(result.message);
              }
              return;
            }
            // A good frame, but a pose is only taken after several good frames in a row.
            setHolding(true);
            setHint(result.message);
            setHeadline(result.candidates_needed ? `Hold still ${result.candidates}/${result.candidates_needed}` : "Hold still");
            // The next frame of the burst goes out almost at once; the request itself takes long
            // enough for the picture to be a new one.
            pause = 80;
          } catch (err) {
            if (stopped) return;
            setHolding(false);
            if (modelsUnavailable(err)) {
              // The server cannot check any frame: not the person's fault, and trying again will not help.
              cancelFaceEnrollment(selected.id).catch(() => {});
              setCapture(null);
              setHint("");
              setHeadline("");
              setMessage(MODELS_UNAVAILABLE_TEXT.enrollment);
              return;
            }
            if (err.payload?.accepted === false) {
              // The backend refused this frame and says why (no face, blurry, too far...), so show it and try again.
              failures = 0;
              setHint(err.message);
              setHeadline(ENROLL_HEADLINES[err.payload.quality_status] || "Frame not accepted");
            } else {
              // Not a refused frame: the enrollment is no longer valid, or the backend cannot be reached.
              failures += 1;
              if (err.status === 404 || err.status === 409 || failures >= 5) {
                setCapture(null);
                setHint("");
                setHeadline("");
                setMessage(`Enrollment stopped: ${(err.message || "the server is not responding").replace(/\.$/, "")}. Nothing new was saved. Press Start Enrollment to try again.`);
                return;
              }
              setHint("Connection problem. Retrying...");
            }
          }
        }
        await wait(pause);
      }
    };
    run();
    return () => { stopped = true; };
  }, [step]);
  const cancel = () => { cancelFaceEnrollment(selected.id).catch(() => {}); setCapture(null); setHint(""); setHeadline(""); };
  const stepIndex = capture ? Math.max(0, steps.indexOf(capture.step)) : 0;
  const pending = people.filter(person => !faceEnrolled(person)).length;
  // Green while the backend is collecting steady frames, amber when it refused one, plain after a pose was taken.
  const feedback = holding ? { box: "bg-emerald-50 text-emerald-800 ring-emerald-600/15", icon: Loader2, spin: true } : headline ? { box: "bg-amber-50 text-amber-800 ring-amber-600/20", icon: TriangleAlert } : { box: "bg-brand-50 text-brand-700 ring-brand-600/15", icon: InfoIcon };

  const forStudents = group === "students";
  const listReady = Boolean(enrollmentQuery(group, courseId, batchId));
  const searchMiss = Boolean(people.length && !visible.length);
  return <Page title="Face Enrollment" subtitle="Choose a person and an enrollment type, then follow the poses. Capture is automatic.">
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)]">
      <div className="space-y-5">
        <Card title="1. Choose the person" subtitle={text.scope}>
          <div className="grid gap-4">
            <div className="grid gap-1.5">
              <span className="text-[13px] font-semibold text-ink-soft">Who</span>
              <fieldset disabled={Boolean(capture)} className="disabled:opacity-60">
                <legend className="sr-only">Who</legend>
                <Segmented label="Who" value={group} onChange={chooseGroup} options={groupOptions()} />
              </fieldset>
            </div>
            {forStudents ? <>
              <FormSelect label="Course" value={courseId} onChange={e => setCourseId(e.target.value)} disabled={Boolean(capture)} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
              <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} disabled={Boolean(capture)} options={batches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={courseId ? "Create a batch under this course" : "Select course first"} />
            </> : <fieldset disabled={Boolean(capture)} className="disabled:opacity-60">
              <legend className="sr-only">Search</legend>
              <SearchInput value={query} onChange={search} placeholder="Search by name or ID" />
            </fieldset>}
            <FormSelect label={text.pick} value={personId} onChange={e => setPersonId(e.target.value)} disabled={Boolean(capture) || loadingPeople} options={visible.map(person => ({ value: person.id, label: `${person.full_name} - ${person.person_code}` }))} empty={loadingPeople ? text.loading : !listReady ? "Select course and batch first" : searchMiss ? "No one matches the search" : text.none} />
            <div className="grid gap-1.5">
              <span className="text-[13px] font-semibold text-ink-soft">Enrollment type</span>
              <fieldset disabled={Boolean(capture)} className="disabled:opacity-60">
                <legend className="sr-only">Enrollment type</legend>
                <Segmented label="Enrollment type" value={mode} onChange={setMode} options={MODES} />
              </fieldset>
              <span className="text-xs text-ink-muted">{MODES.find(item => item.value === mode).detail}</span>
            </div>
            {selected && <div className="flex items-center justify-between gap-3 rounded-2xl border border-line bg-canvas/60 p-3">
              <Identity name={selected.full_name} detail={[selected.person_code, selected.batch_name].filter(Boolean).join(" · ")} />
              <StatusBadge status={faceEnrolled(selected) ? "Enrolled" : "Pending"} />
            </div>}
            {selected && faceEnrolled(selected) && !capture && <p className="text-xs text-ink-muted">This person already has a face enrolled. It stays in use until a new enrollment is finished.</p>}
            {selected && !capture && <label className="flex items-start gap-3 rounded-2xl border border-line bg-canvas/60 p-3 text-sm text-ink-soft">
              <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0 accent-brand-600" checked={consent} onChange={event => setConsent(event.target.checked)} />
              <span><span className="font-semibold text-ink">{selected.full_name} agreed to face enrollment</span> (or, for a minor, a parent or guardian did). Their face is stored as numbers for attendance only, and deleted with their record.</span>
            </label>}
            <Button variant="brand" icon={ScanFace} loading={busy && !capture} disabled={!selected || Boolean(capture) || !consent} onClick={start}>{faceEnrolled(selected) ? "Enroll again" : "Start enrollment"}</Button>
          </div>
        </Card>
        <Card title="For a good capture">
          <ul className="grid gap-3 text-sm text-ink-soft">
            <Tip icon={UserRound}>Only the person being enrolled in view, face inside the oval.</Tip>
            <Tip icon={Sun}>Face a light source. Avoid a bright window behind.</Tip>
            <Tip icon={Glasses}>Remove sunglasses. Hold still until each pose is taken.</Tip>
          </ul>
        </Card>
      </div>

      <Card title="2. Capture" subtitle={capture ? `Enrolling ${selected?.full_name || ""}` : "The camera opens when enrollment starts."} action={capture && <StatusBadge tone="info">{capture.progress}% done</StatusBadge>}>
        {capture ? <div className="grid gap-4">
          <ol className="flex gap-1.5" aria-label="Enrollment poses">
            {steps.map((name, index) => {
              const done = index < stepIndex;
              const current = index === stepIndex;
              return <li key={name} aria-current={current ? "step" : undefined} className={`flex min-w-0 flex-1 flex-col items-center gap-1.5 rounded-2xl px-1 py-2.5 text-center transition duration-200 ${current ? "bg-ink text-white" : done ? "bg-emerald-50 text-emerald-700" : "bg-canvas text-ink-muted"}`}>
                <span className={`grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold ${current ? "bg-white text-ink" : done ? "bg-emerald-500 text-white" : "bg-white text-ink-muted"}`}>{done ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : index + 1}</span>
                <span className="truncate text-[11px] font-semibold sm:text-xs">{titleCase(name)}<span className="sr-only">{done ? " (captured)" : current ? " (current)" : ""}</span></span>
              </li>;
            })}
          </ol>
          <div className="h-1.5 overflow-hidden rounded-full bg-canvas" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={capture.progress} aria-label="Enrollment progress"><div className="h-full rounded-full bg-brand-600 transition-[width] duration-500 ease-out" style={{ width: `${capture.progress}%` }} /></div>
          <CameraView camera={camera} guide mirror>
            {tick && <div className="pointer-events-none absolute inset-0 grid place-items-center bg-emerald-500/20">
              <div className="grid h-24 w-24 animate-fade-up place-items-center rounded-full bg-emerald-500 text-white shadow-float"><Check size={56} strokeWidth={3} aria-hidden="true" /></div>
            </div>}
          </CameraView>
          <div className="rounded-2xl border border-line bg-canvas/60 p-4" aria-live="polite">
            <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">Step {stepIndex + 1} of {steps.length} · {titleCase(capture.step)}</p>
            <p className="mt-1 text-xl font-bold tracking-tight text-ink">{capture.instruction}</p>
            {(headline || hint) && <div className={`mt-3 flex items-start gap-2.5 rounded-xl px-3 py-2.5 ring-1 ring-inset ${feedback.box}`}>
              <feedback.icon size={17} className={`mt-0.5 shrink-0 ${feedback.spin ? "animate-spin" : ""}`} aria-hidden="true" />
              <div className="min-w-0">
                {headline && <p className="text-base font-bold">{headline}</p>}
                {hint && <p className="text-sm font-medium">{hint}</p>}
              </div>
            </div>}
          </div>
          <p className="text-xs text-ink-muted">Capturing automatically. Each pose is taken from a short burst of steady frames and the sharpest is kept. Nothing is saved until every step is done.</p>
          <Button variant="outline" onClick={cancel}>Cancel enrollment</Button>
        </div> : finished ? <div className="grid place-items-center rounded-3xl bg-emerald-50 px-6 py-12 text-center ring-1 ring-inset ring-emerald-600/15" role="status">
          <div className="grid h-14 w-14 place-items-center rounded-full bg-emerald-500 text-white shadow-float"><Check size={30} strokeWidth={3} aria-hidden="true" /></div>
          <p className="mt-4 text-lg font-bold tracking-tight text-emerald-900">Enrollment complete</p>
          <p className="mt-1 max-w-sm text-sm text-emerald-800">{steps.length === 1 ? "The face was" : `All ${steps.length} poses were`} saved for {finished}. They can now be recognized by the scanner. {pendingText(pending)}</p>
        </div> : <CameraPlaceholder icon={ScanFace} title={selected ? `Ready to enroll ${selected.full_name}` : "Choose a person to begin"} message={selected ? `Press Start enrollment. ${MODES.find(item => item.value === mode).detail}` : text.choose} />}
      </Card>
    </div>

    <Card title={text.list} subtitle={people.length ? `${people.length - pending} of ${people.length} enrolled` : undefined}>
      <DataTable loading={loadingPeople} caption="Enrollment queue" columns={[text.pick, "Course", "Batch", "Face", "Action"]} rowKeys={visible.map(person => person.id)} rows={visible.map(person => [
        <Identity name={person.full_name} detail={person.person_code} />,
        person.course_name || "-",
        person.batch_name || "-",
        <StatusBadge status={faceEnrolled(person) ? "Enrolled" : "Pending"} />,
        <Button variant="outline" size="sm" disabled={Boolean(capture) || Number(person.id) === Number(personId)} onClick={() => { setPersonId(person.id); scrollTo({ top: 0, behavior: "smooth" }); }}>{Number(person.id) === Number(personId) ? "Selected" : "Select"}</Button>
      ])} empty={<EmptyState icon={Users} title={!listReady ? "Select a course and batch" : searchMiss ? "No one matches the search" : text.none} message={!listReady ? "The students of the batch are listed here." : searchMiss ? "Try another name or ID." : text.noneHint} />} />
    </Card>
  </Page>;
}

function Tip({ icon: Icon, children }) {
  return <li className="flex items-start gap-3"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-canvas text-ink-muted"><Icon size={16} aria-hidden="true" /></span><span className="pt-1">{children}</span></li>;
}
