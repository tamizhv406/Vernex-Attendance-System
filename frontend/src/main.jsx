import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BookOpen,
  Camera,
  Check,
  Clock,
  Edit3,
  GraduationCap,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  Plus,
  Save,
  ScanFace,
  Search,
  Settings,
  SwitchCamera,
  Trash2,
  UserCheck,
  Users,
  X
} from "lucide-react";
import {
  API_BASE_URL,
  cancelFaceEnrollment,
  completeAttendanceSession,
  createBatch,
  createCourse,
  createPerson,
  deleteBatch,
  deleteCourse,
  deletePerson,
  getAttendanceByDate,
  getAttendanceToday,
  getBatches,
  getCourses,
  getEnrollmentUsers,
  getPeople,
  getTimings,
  recognizeFace,
  sendEnrollmentFrame,
  startAttendanceSession,
  startFaceEnrollment,
  updateBatch,
  updateCourse
} from "./lib/api";
import "./styles.css";

const ROUTES = {
  dashboard: "/dashboard",
  courses: "/courses",
  batches: "/batches",
  students: "/users/students",
  staff: "/users/staff",
  members: "/users/members",
  enrollment: "/face-enrollment",
  scanner: "/attendance-scanner",
  reports: "/reports",
  settings: "/settings"
};
const PATH_TO_PAGE = Object.fromEntries(Object.entries(ROUTES).map(([page, path]) => [path, page]));

const PERSON_CONFIG = {
  students: { title: "Students", singular: "Student", apiType: "student", icon: GraduationCap },
  staff: { title: "Staff", singular: "Staff", apiType: "admin", icon: UserCheck },
  members: { title: "Members", singular: "Member", apiType: "member", icon: Users }
};

function App() {
  const [logged, setLogged] = useState(localStorage.getItem("vx_auth") === "yes");
  const [page, setPageState] = useState(() => PATH_TO_PAGE[location.pathname] || "dashboard");
  const data = useBackendData();
  const setPage = pageId => {
    setPageState(pageId);
    history.pushState(null, "", ROUTES[pageId] || "/dashboard");
  };
  useEffect(() => {
    const sync = () => setPageState(PATH_TO_PAGE[location.pathname] || "dashboard");
    addEventListener("popstate", sync);
    return () => removeEventListener("popstate", sync);
  }, []);
  if (!logged) return <Login onLogin={() => { localStorage.setItem("vx_auth", "yes"); setLogged(true); }} />;
  return <Shell page={page} setPage={setPage} logout={() => { localStorage.removeItem("vx_auth"); setLogged(false); }}>
    {page === "dashboard" && <Dashboard data={data} setPage={setPage} />}
    {page === "courses" && <CoursesPage data={data} />}
    {page === "batches" && <BatchesPage data={data} />}
    {["students", "staff", "members"].includes(page) && <PeoplePage page={page} data={data} />}
    {page === "enrollment" && <FaceEnrollment data={data} />}
    {page === "scanner" && <AttendanceScanner data={data} />}
    {page === "reports" && <Reports data={data} />}
    {page === "settings" && <SettingsPage data={data} />}
  </Shell>;
}

function useBackendData() {
  const [people, setPeople] = useState([]);
  const [courses, setCourses] = useState([]);
  const [batches, setBatches] = useState([]);
  const [timings, setTimings] = useState([]);
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const refresh = async () => {
    setError("");
    try {
      const [courseRows, batchRows, peopleRows, timingRows, attendanceRows] = await Promise.all([
        getCourses(),
        getBatches(),
        getPeople(),
        getTimings(),
        getAttendanceToday()
      ]);
      setCourses(courseRows || []);
      setBatches(batchRows || []);
      setPeople((peopleRows || []).map(mapPerson));
      setTimings(timingRows || []);
      setRecords((attendanceRows || []).map(mapAttendance));
    } catch (err) {
      setError(err.message || "Unable to load FastAPI data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);
  const notify = message => {
    setToast(message);
    setTimeout(() => setToast(""), 2800);
  };
  return { people, courses, batches, timings, records, setPeople, setCourses, setBatches, setRecords, loading, error, toast, notify, refresh };
}

function Login({ onLogin }) {
  return <main className="grid min-h-screen place-items-center bg-slate-100 p-4">
    <section className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-7 shadow-sm">
      <Brand />
      <div className="mt-8">
        <h1 className="text-3xl font-bold text-[#082248]">Admin Login</h1>
        <p className="mt-2 text-sm text-slate-500">Secure local attendance console for your institute.</p>
      </div>
      <form className="mt-7 grid gap-4" onSubmit={event => { event.preventDefault(); onLogin(); }}>
        <FormInput label="Admin ID" placeholder="Enter admin ID" />
        <FormInput label="Password" placeholder="Enter password" type="password" />
        <button className="h-11 rounded-lg bg-[#082248] font-semibold text-white">Login</button>
      </form>
    </section>
  </main>;
}

function Shell({ children, page, setPage, logout }) {
  const [open, setOpen] = useState(false);
  return <div className="min-h-screen bg-[#f5f7fb] text-slate-950">
    <aside className={`fixed inset-y-0 left-0 z-40 w-72 border-r border-slate-200 bg-white p-5 transition-transform lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="flex h-full flex-col">
        <div className="flex items-start justify-between">
          <Brand />
          <button className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 lg:hidden" onClick={() => setOpen(false)}><X size={18} /></button>
        </div>
        <nav className="mt-8 grid gap-1.5">
          <NavItem id="dashboard" label="Dashboard" icon={LayoutDashboard} page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="courses" label="Courses" icon={BookOpen} page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="batches" label="Batches" icon={Layers3} page={page} setPage={setPage} setOpen={setOpen} />
          <UserMenu page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="enrollment" label="Face Enrollment" icon={ScanFace} page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="scanner" label="Attendance Scanner" icon={Camera} page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="reports" label="Reports" icon={BarChart3} page={page} setPage={setPage} setOpen={setOpen} />
          <NavItem id="settings" label="Settings" icon={Settings} page={page} setPage={setPage} setOpen={setOpen} />
        </nav>
        <button className="mt-auto flex h-11 items-center gap-3 rounded-lg px-3 text-sm font-semibold text-slate-600 hover:bg-slate-100" onClick={logout}><LogOut size={18} />Logout</button>
      </div>
    </aside>
    {open && <button className="fixed inset-0 z-30 bg-slate-950/35 lg:hidden" onClick={() => setOpen(false)} aria-label="Close navigation" />}
    <div className="min-w-0 lg:pl-72">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex min-h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
          <button className="grid h-10 w-10 place-items-center rounded-xl border border-slate-200 text-[#082248] lg:hidden" onClick={() => setOpen(true)}><Menu size={21} /></button>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-slate-500">Local-first attendance over the same Wi-Fi network</p>
            <h1 className="truncate text-lg font-bold text-[#082248] sm:text-xl">VerneX</h1>
          </div>
          <ClockBox />
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl px-4 py-5 sm:px-6 lg:px-8">{children}</main>
    </div>
  </div>;
}

function UserMenu({ page, setPage, setOpen }) {
  const userPages = ["students", "staff", "members"];
  const active = userPages.includes(page);
  return <div className="rounded-xl bg-slate-50/70 p-1">
    <div className={`flex h-11 items-center gap-3 rounded-lg px-3 text-sm font-semibold ${active ? "bg-white text-[#082248] shadow-sm ring-1 ring-slate-200" : "text-slate-600"}`}>
      <Users size={18} /><span>User Management</span>
    </div>
    <div className="mt-1 grid gap-1 pb-1">
      <NavItem child id="students" label="Students" icon={GraduationCap} page={page} setPage={setPage} setOpen={setOpen} />
      <NavItem child id="staff" label="Staff" icon={UserCheck} page={page} setPage={setPage} setOpen={setOpen} />
      <NavItem child id="members" label="Members" icon={Users} page={page} setPage={setPage} setOpen={setOpen} />
    </div>
  </div>;
}

function NavItem({ id, label, icon: Icon, page, setPage, setOpen, child }) {
  const active = page === id;
  return <button className={`${child ? "ml-4 h-9 border-l-2 pl-4" : "h-11 px-3"} flex items-center gap-3 rounded-lg text-left text-sm font-semibold transition ${active ? child ? "border-[#c89736] bg-slate-50 text-[#082248]" : "bg-[#082248] text-white shadow-sm" : child ? "border-slate-200 text-slate-500 hover:border-[#c89736] hover:bg-slate-50" : "text-slate-600 hover:bg-slate-100"}`} onClick={() => { setPage(id); setOpen(false); }}>
    <Icon size={child ? 15 : 18} />{label}
  </button>;
}

function Dashboard({ data, setPage }) {
  const today = data.records;
  const counts = {
    students: data.people.filter(p => p.person_type === "student").length,
    staff: data.people.filter(p => p.person_type === "admin").length,
    members: data.people.filter(p => p.person_type === "member").length,
    present: today.filter(r => r.status === "Present").length,
    late: today.filter(r => r.status === "Late").length
  };
  return <Page title="Dashboard" subtitle="Course-first attendance overview for VerneX.">
    <Alerts data={data} />
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5">
      <Stat icon={BookOpen} label="Courses" value={data.courses.length} />
      <Stat icon={Layers3} label="Batches" value={data.batches.length} />
      <Stat icon={GraduationCap} label="Students" value={counts.students} />
      <Stat icon={Activity} label="Present Today" value={counts.present} />
      <Stat icon={Clock} label="Late Today" value={counts.late} />
    </div>
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <Card title="Course / Batch Summary" action={<button className="text-sm font-semibold text-[#082248]" onClick={() => setPage("courses")}>Manage</button>}>
        <div className="grid gap-3">
          {data.courses.map(course => <CourseSummary key={course.id} course={course} batches={data.batches.filter(batch => batch.course_id === course.id)} people={data.people} />)}
          {!data.courses.length && <Empty title="Create a course first" message="Courses are the first step before batches, students, enrollment, and attendance." />}
        </div>
      </Card>
      <Card title="Recent Attendance">
        <DataTable columns={["Name", "Code", "Course", "Batch", "Status", "Time"]} rows={today.slice(0, 6).map(record => [record.person_name, record.person_code, record.course_name, record.batch_name, <Badge status={record.status} />, formatTime(record.marked_time)])} empty="No scans recorded today." />
      </Card>
    </div>
  </Page>;
}

function CoursesPage({ data }) {
  const blank = { course_code: "", course_name: "", description: "", status: "active" };
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState(null);
  const [message, setMessage] = useState("");
  const save = async event => {
    event.preventDefault();
    try {
      if (editing) await updateCourse(editing, form);
      else await createCourse(form);
      setForm(blank);
      setEditing(null);
      data.notify(editing ? "Course updated." : "Course created.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to save course.");
    }
  };
  const edit = course => {
    setEditing(course.id);
    setForm({ course_code: course.course_code || "", course_name: course.course_name || "", description: course.description || "", status: course.status || "active" });
  };
  const remove = async id => {
    try {
      await deleteCourse(id);
      data.notify("Course deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete course.");
    }
  };
  return <Page title="Courses" subtitle="Create the course before creating batches and assigning students.">
    <Alerts data={data} message={message} />
    <Card title={editing ? "Edit Course" : "Create Course"}>
      <form className="grid gap-4 md:grid-cols-[160px_1fr_1fr_150px_auto]" onSubmit={save}>
        <FormInput label="Course Code" value={form.course_code} onChange={e => setForm({ ...form, course_code: e.target.value })} required />
        <FormInput label="Course Name" value={form.course_name} onChange={e => setForm({ ...form, course_name: e.target.value })} required />
        <FormInput label="Description" value={form.description || ""} onChange={e => setForm({ ...form, description: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <div className="flex items-end gap-2">
          <button className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#082248] px-4 font-semibold text-white"><Save size={16} />Save</button>
          {editing && <button type="button" className="h-11 rounded-xl border border-slate-200 px-3 font-semibold" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</button>}
        </div>
      </form>
    </Card>
    <Card title="Course List">
      <DataTable columns={["Code", "Course", "Description", "Status", "Action"]} rows={data.courses.map(course => [
        course.course_code,
        course.course_name,
        course.description || "-",
        <Badge status={titleCase(course.status)} />,
        <RowActions onEdit={() => edit(course)} onDelete={() => remove(course.id)} />
      ])} empty="Create a course first" />
    </Card>
  </Page>;
}

function BatchesPage({ data }) {
  const firstCourseId = data.courses[0]?.id || "";
  const [selectedCourseId, setSelectedCourseId] = useState(firstCourseId);
  const [editing, setEditing] = useState(null);
  const [message, setMessage] = useState("");
  const blank = { batch_name: "", batch_level: "", timing_id: "", status: "active" };
  const [form, setForm] = useState(blank);
  useEffect(() => { if (!selectedCourseId && firstCourseId) setSelectedCourseId(firstCourseId); }, [firstCourseId, selectedCourseId]);
  const courseBatches = data.batches.filter(batch => Number(batch.course_id) === Number(selectedCourseId));
  const save = async event => {
    event.preventDefault();
    if (!selectedCourseId) { setMessage("Create a course first."); return; }
    const payload = { ...form, course_id: Number(selectedCourseId), timing_id: form.timing_id ? Number(form.timing_id) : null };
    try {
      if (editing) await updateBatch(editing, payload);
      else await createBatch(payload);
      setForm(blank);
      setEditing(null);
      data.notify(editing ? "Batch updated." : "Batch created.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to save batch.");
    }
  };
  const edit = batch => {
    setEditing(batch.id);
    setSelectedCourseId(batch.course_id);
    setForm({ batch_name: batch.batch_name || "", batch_level: batch.batch_level || "", timing_id: batch.timing_id || "", status: batch.status || "active" });
  };
  const remove = async id => {
    try {
      await deleteBatch(id);
      data.notify("Batch deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete batch.");
    }
  };
  return <Page title="Batches" subtitle="Batches are always created under one selected course.">
    <Alerts data={data} message={message} />
    <Card title={editing ? "Edit Batch" : "Create Batch"}>
      <form className="grid gap-4 md:grid-cols-[1fr_1fr_1fr_160px_auto]" onSubmit={save}>
        <FormSelect label="Course" value={selectedCourseId} onChange={e => { setSelectedCourseId(e.target.value); setEditing(null); setForm(blank); }} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
        <FormInput label="Batch Name" value={form.batch_name} onChange={e => setForm({ ...form, batch_name: e.target.value })} required />
        <FormInput label="Batch Level" value={form.batch_level || ""} onChange={e => setForm({ ...form, batch_level: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <div className="flex items-end gap-2">
          <button className="inline-flex h-11 items-center gap-2 rounded-xl bg-[#082248] px-4 font-semibold text-white"><Plus size={16} />Save</button>
          {editing && <button type="button" className="h-11 rounded-xl border border-slate-200 px-3 font-semibold" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</button>}
        </div>
      </form>
    </Card>
    <Card title="Batch List">
      <DataTable columns={["Course", "Batch", "Level", "Status", "Action"]} rows={courseBatches.map(batch => [
        courseName(data.courses, batch.course_id),
        batch.batch_name,
        batch.batch_level || "-",
        <Badge status={titleCase(batch.status)} />,
        <RowActions onEdit={() => edit(batch)} onDelete={() => remove(batch.id)} />
      ])} empty={selectedCourseId ? "Create a batch under this course" : "Create a course first"} />
    </Card>
  </Page>;
}

function PeoplePage({ page, data }) {
  const config = PERSON_CONFIG[page];
  const blank = { person_code: "", full_name: "", guardian_name: "", phone: "", email: "", course_id: "", batch_id: "", level_class: "", joining_date: "", status: "active", face_enrollment_status: "not_started", notes: "" };
  const [form, setForm] = useState(blank);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const availableBatches = useMemo(
    () => data.batches.filter(batch => Number(batch.course_id) === Number(form.course_id)),
    [data.batches, form.course_id],
  );
  const rows = data.people.filter(person => person.person_type === config.apiType).filter(person => JSON.stringify(person).toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    if (form.batch_id && !availableBatches.some(batch => Number(batch.id) === Number(form.batch_id))) setForm(current => ({ ...current, batch_id: "" }));
  }, [form.batch_id, availableBatches]);
  const save = async event => {
    event.preventDefault();
    if (config.apiType === "student" && (!form.course_id || !form.batch_id)) {
      setMessage("Student must select an existing course and batch.");
      return;
    }
    try {
      await createPerson(toPersonPayload(form, config.apiType));
      setForm(blank);
      data.notify(`${config.singular} created.`);
      await data.refresh();
    } catch (err) {
      setMessage(err.message || `Unable to create ${config.singular.toLowerCase()}.`);
    }
  };
  const remove = async id => {
    try {
      await deletePerson(id);
      data.notify(`${config.singular} deleted.`);
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete user.");
    }
  };
  return <Page title={`${config.title} Details`} subtitle="Assign people only to existing courses and batches.">
    <Alerts data={data} message={message} />
    <Card title={`Create ${config.singular}`}>
      <form className="grid gap-4 md:grid-cols-2" onSubmit={save}>
        <FormInput label={`${config.singular} ID`} value={form.person_code} onChange={e => setForm({ ...form, person_code: e.target.value })} required />
        <FormInput label={`${config.singular} Name`} value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} required />
        {config.apiType === "student" && <FormInput label="Parent Name" value={form.guardian_name} onChange={e => setForm({ ...form, guardian_name: e.target.value })} />}
        <FormInput label={config.apiType === "student" ? "Parent Contact" : "Contact Number"} inputMode="numeric" maxLength={10} value={form.phone} onChange={e => setForm({ ...form, phone: onlyNumbers(e.target.value).slice(0, 10) })} required />
        {config.apiType !== "student" && <FormInput label="Email" type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />}
        <FormSelect label="Course" value={form.course_id} onChange={e => setForm({ ...form, course_id: e.target.value, batch_id: "" })} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" required={config.apiType === "student"} />
        <FormSelect label="Batch" value={form.batch_id} onChange={e => setForm({ ...form, batch_id: e.target.value })} options={availableBatches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={form.course_id ? "Create a batch under this course" : "Select course first"} required={config.apiType === "student"} />
        <FormInput label="Level / Class" value={form.level_class} onChange={e => setForm({ ...form, level_class: e.target.value })} />
        <FormInput label="Joining Date" type="date" value={form.joining_date} onChange={e => setForm({ ...form, joining_date: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <FormSelect label="Face Enrollment Status" value={form.face_enrollment_status} onChange={e => setForm({ ...form, face_enrollment_status: e.target.value })} options={[{ value: "not_started", label: "Pending" }, { value: "completed", label: "Completed" }]} />
        <label className="grid gap-1.5 md:col-span-2"><span className="text-sm font-semibold text-slate-700">Notes</span><textarea className="min-h-24 rounded-xl border border-slate-200 px-3 py-3 outline-none focus:border-[#082248] focus:ring-4 focus:ring-slate-200" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Optional notes" /></label>
        <button className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-[#082248] px-4 font-semibold text-white md:col-span-2"><Plus size={17} />Save {config.singular}</button>
      </form>
    </Card>
    <Card title={`${config.singular} List`} action={<SearchBox value={query} onChange={setQuery} />}>
      <DataTable columns={["Name", "Phone", "Code", "Course", "Batch", "Status", "Face", "Action"]} rows={rows.map(person => [
        person.full_name,
        person.guardian_phone || person.phone || "-",
        person.person_code,
        person.course_name || "-",
        person.batch_name || "-",
        <Badge status={titleCase(person.status)} />,
        <Badge status={person.face_enrollment_status === "completed" ? "Completed" : "Pending"} />,
        <button className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-slate-500" onClick={() => remove(person.id)}><Trash2 size={16} /></button>
      ])} empty={`No ${config.title.toLowerCase()} found.`} />
    </Card>
  </Page>;
}

const ENROLLMENT_STEPS = ["front", "left", "right", "close", "far"];
const ENROLLMENT_FIRST_STEP ={ step: "front", instruction: "Look straight", progress: 0 };
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

function FaceEnrollment({ data }) {
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [students, setStudents] = useState([]);
  const [studentId, setStudentId] = useState("");
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
  const [steps, setSteps] = useState(ENROLLMENT_STEPS);
  // Students enroll their own face, so start on the camera that looks at them.
  const camera = useCamera(Boolean(capture), "user");
  const batches = data.batches.filter(batch => Number(batch.course_id) === Number(courseId));
  useEffect(() => {
    setBatchId("");
    setStudents([]);
    setStudentId("");
  }, [courseId]);
  useEffect(() => {
    if (!courseId || !batchId) {
      setStudents([]);
      setStudentId("");
      return;
    }
    getEnrollmentUsers(courseId, batchId)
      .then(rows => {
        const mapped = (rows || []).map(mapPerson);
        setStudents(mapped);
        setStudentId(mapped[0]?.id || "");
      })
      .catch(err => setMessage(err.message || "Unable to load enrollment users."));
  }, [courseId, batchId]);
  useEffect(() => { setCapture(null); setHint(""); setHeadline(""); setFinished(null); }, [studentId]);
  const selected = students.find(student => Number(student.id) === Number(studentId));
  const start = async () => {
    if (!selected) { setMessage("Select course and batch to start enrollment."); return; }
    setBusy(true);
    setMessage("");
    try {
      // The backend decides which poses this enrollment has; the page only follows.
      const started = await startFaceEnrollment(selected.id, mode);
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
    const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
    const run = async () => {
      // The first pose starts the moment the camera delivers a picture: the student is already
      // looking at it. Later poses leave a moment to read the new instruction and move.
      if (step !== steps[0]) await wait(1200);
      while (!stopped) {
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
            const result = await sendEnrollmentFrame(form);
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
                setStudents(rows => rows.map(row => row.id === selected.id ? { ...row, face_enrollment_status: "completed" } : row));
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
  return <Page title="Face Enrollment" subtitle="Select Course, Batch, Student, then start enrollment.">
    <Alerts data={data} message={message} />
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[.9fr_1.1fr]">
      <Card title="Enrollment Selection">
        <div className="grid gap-4">
          <FormSelect label="Course" value={courseId} onChange={e => setCourseId(e.target.value)} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
          <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} options={batches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={courseId ? "Create a batch under this course" : "Select course first"} />
          <FormSelect label="Student" value={studentId} onChange={e => setStudentId(e.target.value)} options={students.map(student => ({ value: student.id, label: `${student.full_name} - ${student.person_code}` }))} empty={courseId && batchId ? "No students found in this batch" : "Select course and batch to start enrollment"} />
          <FormSelect label="Enrollment type" value={mode} onChange={e => setMode(e.target.value)} disabled={Boolean(capture)} options={[{ value: "quick", label: "Quick: look straight, left, right (a few seconds)" }, { value: "guided", label: "Full: five poses (front, left, right, close, far)" }]} />
          <button disabled={busy || !selected || Boolean(capture)} className="h-11 rounded-xl bg-[#082248] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" onClick={start}>{busy && !capture ? "Starting..." : "Start Enrollment"}</button>
        </div>
      </Card>
      {capture ? <Card title="Enrollment Camera" action={<Badge status={`${capture.progress}% done`} />}>
        <div className="grid gap-4">
          <CameraView camera={camera} guide mirror>
            {tick && <div className="pointer-events-none absolute inset-0 grid place-items-center bg-emerald-500/20">
              <div className="grid h-24 w-24 place-items-center rounded-full bg-emerald-500 text-white shadow-lg"><Check size={56} strokeWidth={3} /></div>
            </div>}
          </CameraView>
          <div className="flex flex-wrap gap-2">
            {steps.map((name, index) => {
              const current = steps.indexOf(capture.step);
              const state = index < current ? "border-emerald-200 bg-emerald-50 text-emerald-700" : index === current ? "border-[#082248] bg-[#082248] text-white" : "border-slate-200 bg-white text-slate-400";
              return <span key={name} className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-bold ${state}`}>{index < current && <Check size={12} strokeWidth={3} />}{index + 1}. {titleCase(name)}</span>;
            })}
          </div>
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-semibold text-slate-500">Step {steps.indexOf(capture.step) + 1} of {steps.length}: {titleCase(capture.step)}</p>
            <p className="mt-1 text-xl font-bold text-[#082248]">{capture.instruction}</p>
            {headline && <p className={`mt-3 text-lg font-bold ${holding ? "text-emerald-700" : "text-amber-700"}`}>{headline}</p>}
            {hint && <p className={`mt-1 text-sm font-semibold ${holding ? "text-emerald-700" : "text-amber-700"}`}>{hint}</p>}
          </div>
          <p className="text-sm font-semibold text-slate-500">Capturing automatically. Only the student being enrolled should be in view. Keep your face inside the oval, follow the instruction and hold still: each pose is taken from a short burst of steady frames and the sharpest is kept. Nothing is saved until every step is done.</p>
          <button className="h-11 rounded-xl border border-slate-200 font-semibold text-[#082248]" onClick={() => { cancelFaceEnrollment(selected.id).catch(() => {}); setCapture(null); setHint(""); setHeadline(""); }}>Cancel</button>
        </div>
      </Card> : <Card title="Selected Student" action={<Badge status={selected?.face_enrollment_status === "completed" ? "Completed" : "Pending"} />}>
        {finished && <div className="mb-4 flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
          <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-emerald-500 text-white"><Check size={22} strokeWidth={3} /></div>
          <div><p className="font-bold text-emerald-800">Enrollment complete</p><p className="text-sm font-semibold text-emerald-700">{steps.length === 1 ? "The face was" : `All ${steps.length} poses were`} saved for {finished}. They can now be recognized by the scanner.</p></div>
        </div>}
        {selected ? <div className="grid gap-3">
          <Info label="Name" value={selected.full_name} />
          <Info label="Code" value={selected.person_code} />
          <Info label="Course" value={selected.course_name} />
          <Info label="Batch" value={selected.batch_name} />
        </div> : <Empty title="Select course and batch to start enrollment" message="Only students assigned to the selected batch will appear here." />}
      </Card>}
    </div>
    <Card title="Enrollment Queue">
      <DataTable columns={["Student", "Code", "Course", "Batch", "Status"]} rows={students.map(student => [student.full_name, student.person_code, student.course_name, student.batch_name, <Badge status={student.face_enrollment_status === "completed" ? "Completed" : "Pending"} />])} empty={courseId && batchId ? "No students found in this batch" : "Select course and batch to start enrollment"} />
    </Card>
  </Page>;
}

function AttendanceScanner({ data }) {
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [activeSession, setActiveSession] = useState(null);
  const [scan, setScan] = useState({ faces: [], frame: null, status: "" });
  // Names this camera to the backend, which follows faces per camera: two phones scanning the same
  // class never have their sightings of a student added together.
  const scannerId = useRef(`scanner-${Math.random().toString(36).slice(2, 10)}`);
  const [marks, setMarks] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const camera = useCamera(Boolean(activeSession));
  const batches = data.batches.filter(batch => Number(batch.course_id) === Number(courseId));
  const students = data.people.filter(person => person.person_type === "student" && Number(person.course_id) === Number(courseId) && Number(person.batch_id) === Number(batchId));
  useEffect(() => { setBatchId(""); setActiveSession(null); }, [courseId]);
  useEffect(() => {
    setScan({ faces: [], frame: null, status: "" });
    if (!activeSession) return;
    setMarks({});
    // Live loop: grab a frame from the camera, let the backend detect and recognize every face in it,
    // then draw the boxes. The backend marks attendance itself, so one request per frame is enough.
    let stopped = false;
    const run = async () => {
      while (!stopped) {
        const shot = await camera.capture();
        if (shot) {
          try {
            const form = new FormData();
            form.append("image", shot.blob, "frame.jpg");
            form.append("session_id", activeSession.id);
            form.append("device_name", "frontend-scanner");
            form.append("scanner_id", scannerId.current);
            const result = await recognizeFace(form);
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
        session_date: new Date().toISOString().slice(0, 10),
        start_time: new Date().toTimeString().slice(0, 8)
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
    setActiveSession(null);
    try {
      await completeAttendanceSession(session.id);
      data.notify("Attendance session completed.");
    } catch (err) {
      setMessage(err.message || "Unable to complete attendance session.");
    }
  };
  return <Page title="Attendance Scanner" subtitle="Select Course, Batch, start a session, then point the camera at the class.">
    <Alerts data={data} message={message} />
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.1fr_.9fr]">
      <Card title="Scanner Camera" action={<Badge status={activeSession ? "Active" : "Pending"} />}>
        {activeSession ? <div className="grid gap-3">
          <CameraView camera={camera} faces={scan.faces} frame={scan.frame} />
          <p className="text-sm font-semibold text-slate-500">{scan.status || "Starting camera and loading face models. The first scan can take a minute."}</p>
          {scan.ms > 1200 && <p className="text-sm font-semibold text-amber-700">Each frame takes about {(scan.ms / 1000).toFixed(1)} s to check on this computer. A student is marked after {scan.faces[0]?.confirm_needed || 3} separate checks, so everyone needs to stay in view for a few seconds.</p>}
          {scan.faces.some(face => face.result === "challenge") && <p className="text-sm font-bold text-sky-700">Blue boxes: that student must look straight at the camera, then turn their head the way their box says (their own left or right). A photo or a video cannot follow the instruction.</p>}
          <p className="text-xs font-semibold text-slate-400">Green: identity verified. Blue: must follow the head-turn instruction. Amber: still being verified. Red: not verified, attendance is not marked. Grey: too small, dark or blurred, or not clearly a real face.</p>
        </div> : <div className="grid aspect-video place-items-center rounded-lg border border-slate-200 bg-slate-950 text-center text-white">
          <div><Camera className="mx-auto mb-3 text-cyan-300" size={42} /><p className="font-bold">Session stopped</p></div>
        </div>}
      </Card>
      <Card title="Session Control">
        <div className="grid gap-4">
          <FormSelect label="Course" value={courseId} onChange={e => setCourseId(e.target.value)} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
          <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} options={batches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={courseId ? "Create a batch under this course" : "Select course first"} />
          <button disabled={busy || !courseId || !batchId || Boolean(activeSession)} className="h-11 rounded-xl bg-[#082248] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60" onClick={start}>{busy ? "Starting..." : "Start Session"}</button>
          <button disabled={!activeSession} className="h-11 rounded-xl border border-slate-200 font-semibold text-[#082248] disabled:cursor-not-allowed disabled:opacity-60" onClick={stop}>Stop Session</button>
          {activeSession && <div className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm">
            <Info label="Course" value={courseName(data.courses, activeSession.course_id)} />
            <Info label="Batch" value={batchName(data.batches, activeSession.batch_id)} />
            <Info label="Session Date" value={activeSession.session_date} />
            <Info label="Start Time" value={activeSession.start_time || "-"} />
          </div>}
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <p className="text-sm font-semibold text-slate-500">Faces in view</p>
            {scan.faces.length ? <ul className="mt-2 grid gap-2">
              {scan.faces.map((face, index) => {
                const verdict = faceVerdict(face);
                return <li key={face.track_id ?? index} className="flex items-center gap-2 text-sm font-bold text-[#082248]">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${FACE_TONES[verdict.tone].label}`} />{verdict.text}
                </li>;
              })}
            </ul> : <p className="mt-2 text-lg font-bold text-[#082248]">{activeSession ? "Waiting for faces" : "Session not started"}</p>}
          </div>
        </div>
      </Card>
    </div>
    <Card title="Students in Selected Batch">
      <DataTable columns={["Name", "Code", "Course", "Batch", "Face", "Attendance"]} rows={students.map(student => [student.full_name, student.person_code, student.course_name, student.batch_name, <Badge status={student.face_enrollment_status === "completed" ? "Completed" : "Pending"} />, <Badge status={marks[student.id] || "Pending"} />])} empty={courseId && batchId ? "No students found in this batch" : "Select course and batch to start attendance session"} />
    </Card>
  </Page>;
}

function useCamera(active, initialFacing = "environment") {
  const videoRef = useRef(null);
  const [facing, setFacing] = useState(initialFacing);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(false);
    if (!active) return;
    setError("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(window.isSecureContext ? "This browser does not support camera access." : "The camera only works over HTTPS. Start the frontend with `npm run dev:https` and open the https:// link.");
      return;
    }
    let stream = null;
    let cancelled = false;
    navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      .then(result => {
        if (cancelled) { result.getTracks().forEach(track => track.stop()); return; }
        stream = result;
        if (videoRef.current) videoRef.current.srcObject = result;
      })
      .catch(err => setError(err.name === "NotAllowedError" ? "Camera permission denied. Allow camera access for this site and try again." : err.message || "Unable to open the camera."));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach(track => track.stop());
    };
  }, [active, facing]);
  // Frames are downscaled before upload: faces stay large enough to recognize and requests stay small.
  // Enrollment and the scanner use the same size, so a face reaches the model at the same scale in both.
  const capture = (maxWidth = 960) => new Promise(resolve => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) { resolve(null); return; }
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(blob => resolve(blob ? { blob, width: canvas.width, height: canvas.height } : null), "image/jpeg", 0.8);
  });
  const flip = () => setFacing(current => current === "environment" ? "user" : "environment");
  return { videoRef, error, capture, flip, facing, ready, setReady };
}

// Why the scanner could not judge a face at all.
const SCAN_LABELS = { too_far: "Too far", low_light: "Too dark", too_bright: "Too bright", blurry: "Blurry", unclear: "Unclear" };
const FACE_TONES = {
  good: { box: "border-emerald-400", label: "bg-emerald-500" },
  wait: { box: "border-amber-400", label: "bg-amber-500" },
  ask: { box: "border-sky-400", label: "bg-sky-600" },
  bad: { box: "border-red-400", label: "bg-red-500" },
  idle: { box: "border-slate-300", label: "bg-slate-500" }
};

// What the scanner decided about one face. Every face in the frame gets its own verdict from the backend.
function faceVerdict(face) {
  const name = face.person_name;
  switch (face.result) {
    case "verified": return { tone: "good", text: `${name}: marked ${face.attendance_status}` };
    case "already_marked": return { tone: "good", text: `${name}: already marked` };
    case "recognized": return { tone: "good", text: `${name} ${Math.round(face.confidence_score * 100)}%` };
    case "pending": return { tone: "wait", text: `Verifying ${name} ${face.confirm_hits}/${face.confirm_needed}` };
    // The backend asks each face for its own movement, in a direction it picked at random.
    case "challenge": return face.challenge?.action === "turn"
      ? { tone: "ask", text: `${name}: turn head to YOUR ${face.challenge.direction.toUpperCase()}` }
      : { tone: "ask", text: `${name}: look straight` };
    case "challenge_failed": return { tone: "bad", text: `${name}: wrong movement, wait` };
    case "locked": return { tone: "bad", text: `${name}: locked, mark by hand` };
    case "liveness_uncertain": return { tone: "idle", text: "Cannot confirm a real face" };
    case "not_marked": return { tone: "wait", text: `${name}: not marked` };
    case "ambiguous": return { tone: "bad", text: "Unable to verify identity" };
    case "liveness_failed": return { tone: "bad", text: "Photo or screen detected" };
    case "low_quality": return { tone: "idle", text: SCAN_LABELS[face.status] || "Unclear" };
    default: return { tone: "bad", text: "Unknown" };
  }
}

// guide: draw the oval the face should sit in. mirror: show the front camera like a mirror
// (the preview only; uploaded frames are never flipped).
function CameraView({ camera, faces = [], frame, guide = false, mirror = false, children }) {
  const percent = (value, total) => `${(value / total) * 100}%`;
  return <div className="relative grid place-items-center overflow-hidden rounded-lg border border-slate-200 bg-slate-950">
    <div className="relative inline-block max-w-full">
      <video ref={camera.videoRef} className="block max-h-[70vh] min-h-48 max-w-full" style={mirror && camera.facing === "user" ? { transform: "scaleX(-1)" } : undefined} onLoadedData={() => camera.setReady(true)} autoPlay playsInline muted />
      {guide && camera.ready && <div className="pointer-events-none absolute left-1/2 top-1/2 h-[78%] w-[36%] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border-2 border-dashed border-white/80" />}
      {!camera.ready && !camera.error && <p className="absolute inset-0 grid place-items-center text-sm font-semibold text-slate-300">Starting camera...</p>}
      {frame && faces.map((face, index) => {
        // Keyed by the backend's track, not by position in the list, so a box and its label stay
        // with the same face while people move and the order of the list changes.
        const verdict = faceVerdict(face);
        return <div key={face.track_id ?? index} className={`absolute border-2 transition-all duration-150 ease-linear ${FACE_TONES[verdict.tone].box}`} style={{ left: percent(face.box.x, frame.width), top: percent(face.box.y, frame.height), width: percent(face.box.w, frame.width), height: percent(face.box.h, frame.height) }}>
          <span className={`absolute left-0 top-full whitespace-nowrap px-1.5 py-0.5 text-xs font-bold text-white ${FACE_TONES[verdict.tone].label}`}>{verdict.text}</span>
        </div>;
      })}
    </div>
    {children}
    {camera.error && <p className="p-4 text-center text-sm font-semibold text-red-300">{camera.error}</p>}
    <button className="absolute right-3 top-3 grid h-10 w-10 place-items-center rounded-full bg-white/90 text-[#082248]" onClick={camera.flip} aria-label="Switch camera"><SwitchCamera size={18} /></button>
  </div>;
}
function Reports({ data }) {
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [rows, setRows] = useState(data.records);
  const [message, setMessage] = useState("");
  const batches = data.batches.filter(batch => !courseId || Number(batch.course_id) === Number(courseId));
  useEffect(() => { if (batchId && !batches.some(batch => Number(batch.id) === Number(batchId))) setBatchId(""); }, [batchId, batches]);
  const load = async () => {
    try {
      const result = await getAttendanceByDate(date, { course_id: courseId, batch_id: batchId });
      setRows((result || []).map(mapAttendance));
    } catch (err) {
      setMessage(err.message || "Unable to load report data.");
    }
  };
  useEffect(() => { load(); }, []);
  return <Page title="Reports" subtitle="Filter attendance logs by Course, Batch, and Date.">
    <Alerts data={data} message={message} />
    <Card title="Report Filters">
      <div className="grid gap-4 md:grid-cols-[1fr_1fr_180px_auto]">
        <FormSelect label="Course" value={courseId} onChange={e => { setCourseId(e.target.value); setBatchId(""); }} options={[{ value: "", label: "All Courses" }, ...data.courses.map(course => ({ value: course.id, label: course.course_name }))]} />
        <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} options={[{ value: "", label: "All Batches" }, ...batches.map(batch => ({ value: batch.id, label: batch.batch_name }))]} />
        <FormInput label="Date" type="date" value={date} onChange={e => setDate(e.target.value)} />
        <div className="flex items-end"><button className="h-11 rounded-xl bg-[#082248] px-5 font-semibold text-white" onClick={load}>Apply</button></div>
      </div>
    </Card>
    <Card title="Attendance Records">
      <DataTable columns={["Name", "Code", "Course", "Batch", "Status", "Time"]} rows={rows.map(record => [record.person_name, record.person_code, record.course_name || courseName(data.courses, record.course_id), record.batch_name || batchName(data.batches, record.batch_id), <Badge status={record.status} />, formatTime(record.marked_time)])} empty="No report data available." />
    </Card>
  </Page>;
}

function SettingsPage({ data }) {
  return <Page title="Settings" subtitle="Backend connection and system status.">
    <Alerts data={data} />
    <Card title="System">
      <div className="grid gap-3 md:grid-cols-2">
        <Info label="Backend URL" value={API_BASE_URL} />
        <Info label="Course Source" value="FastAPI only" />
        <Info label="Supabase Client" value="Backend only" />
        <Info label="User Flow" value="Course -> Batch -> Student" />
      </div>
    </Card>
  </Page>;
}

function Page({ title, subtitle, children }) {
  return <div className="space-y-5">
    <div>
      <h2 className="text-2xl font-bold tracking-tight text-[#082248] sm:text-3xl">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm text-slate-500">{subtitle}</p>
    </div>
    {children}
  </div>;
}

function Card({ title, action, children }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <h3 className="text-lg font-bold text-[#082248]">{title}</h3>
      {action}
    </div>
    {children}
  </section>;
}

function FormInput({ label, className = "", ...props }) {
  return <label className={`grid gap-1.5 ${className}`}>
    <span className="text-sm font-semibold text-slate-700">{label}</span>
    <input className="h-11 rounded-xl border border-slate-200 bg-white px-3 text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-[#082248] focus:ring-4 focus:ring-slate-200" {...props} />
  </label>;
}

function FormSelect({ label, options = [], empty = "No options", ...props }) {
  const hasEmptyValueOption = options.some(option => (typeof option === "string" ? option : option.value) === "");
  const needsPlaceholder = options.length > 0 && !hasEmptyValueOption && (props.value ?? "") === "";
  return <label className="grid gap-1.5">
    <span className="text-sm font-semibold text-slate-700">{label}</span>
    <select className="h-11 rounded-xl border border-slate-200 bg-white px-3 text-slate-900 outline-none transition focus:border-[#082248] focus:ring-4 focus:ring-slate-200" {...props}>
      {!options.length && <option value="">{empty}</option>}
      {needsPlaceholder && <option value="" disabled hidden>{`Select ${label}`}</option>}
      {options.map(option => typeof option === "string" ? <option key={option} value={option}>{option}</option> : <option key={`${option.value}-${option.label}`} value={option.value}>{option.label}</option>)}
    </select>
  </label>;
}

function DataTable({ columns, rows, empty }) {
  return <div className="overflow-hidden rounded-xl border border-slate-200">
    <div className="hidden overflow-x-auto md:block">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50"><tr>{columns.map(column => <th key={column} className="px-4 py-3 text-left font-bold text-slate-500">{column}</th>)}</tr></thead>
        <tbody className="divide-y divide-slate-100 bg-white">{rows.map((row, index) => <tr key={index}>{row.map((cell, cellIndex) => <td key={cellIndex} className="px-4 py-3 align-middle text-slate-700">{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
    <div className="grid gap-3 bg-slate-50 p-3 md:hidden">
      {rows.map((row, index) => <div key={index} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        {row.map((cell, cellIndex) => <div key={cellIndex} className="flex items-start justify-between gap-3 border-b border-slate-100 py-2 last:border-0">
          <span className="text-xs font-bold uppercase text-slate-400">{columns[cellIndex]}</span>
          <span className="text-right text-sm font-medium text-slate-700">{cell}</span>
        </div>)}
      </div>)}
    </div>
    {!rows.length && <div className="bg-white px-4 py-8 text-center text-sm text-slate-500">{empty}</div>}
  </div>;
}

function Alerts({ data, message }) {
  return <>
    {data.toast && <Notice tone="success">{data.toast}</Notice>}
    {data.error && <Notice tone="error">{data.error}</Notice>}
    {message && <Notice tone="error">{message}</Notice>}
    {data.loading && <Notice>Loading live backend data...</Notice>}
  </>;
}

function Notice({ tone = "info", children }) {
  const styles = {
    info: "border-cyan-100 bg-cyan-50 text-cyan-800",
    success: "border-emerald-100 bg-emerald-50 text-emerald-800",
    error: "border-red-100 bg-red-50 text-red-800"
  };
  return <div className={`rounded-xl border px-4 py-3 text-sm font-semibold ${styles[tone]}`}>{children}</div>;
}

function Badge({ status }) {
  const key = titleCase(status || "Unknown");
  const classes = {
    Active: "bg-emerald-50 text-emerald-700",
    Completed: "bg-emerald-50 text-emerald-700",
    Present: "bg-emerald-50 text-emerald-700",
    Pending: "bg-amber-50 text-amber-700",
    Late: "bg-amber-50 text-amber-700",
    Absent: "bg-red-50 text-red-700",
    Unknown: "bg-slate-100 text-slate-600",
    Inactive: "bg-slate-100 text-slate-600",
    "Already Marked": "bg-cyan-50 text-cyan-700"
  };
  return <span className={`inline-flex min-h-7 items-center rounded-full px-3 text-xs font-bold ${classes[key] || "bg-slate-100 text-slate-600"}`}>{key}</span>;
}

function RowActions({ onEdit, onDelete }) {
  return <div className="flex gap-2">
    <button className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-[#082248]" onClick={onEdit}><Edit3 size={16} /></button>
    <button className="grid h-9 w-9 place-items-center rounded-lg border border-slate-200 text-red-500" onClick={onDelete}><Trash2 size={16} /></button>
  </div>;
}

function SearchBox({ value, onChange }) {
  return <label className="flex h-10 w-full items-center gap-2 rounded-xl border border-slate-200 px-3 sm:w-64">
    <Search size={16} className="text-slate-400" /><input className="min-w-0 flex-1 bg-transparent text-sm outline-none" placeholder="Search" value={value} onChange={e => onChange(e.target.value)} />
  </label>;
}

function Empty({ title, message }) {
  return <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center">
    <p className="font-semibold text-slate-800">{title}</p>
    <p className="mt-1 text-sm text-slate-500">{message}</p>
  </div>;
}

function Info({ label, value }) {
  return <div className="rounded-lg bg-slate-50 px-3 py-2">
    <p className="text-xs font-bold uppercase text-slate-400">{label}</p>
    <p className="mt-1 font-semibold text-[#082248]">{value || "-"}</p>
  </div>;
}

function Stat({ icon: Icon, label, value }) {
  return <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-sm font-semibold text-slate-500">{label}</p><p className="mt-2 text-3xl font-bold text-[#082248]">{value}</p></div>
      <div className="grid h-11 w-11 place-items-center rounded-lg bg-[#082248] text-white"><Icon size={21} /></div>
    </div>
  </article>;
}

function CourseSummary({ course, batches, people }) {
  const assigned = people.filter(person => Number(person.course_id) === Number(course.id)).length;
  return <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="font-semibold text-slate-900">{course.course_name}</p>
        <p className="text-sm text-slate-500">{assigned} users assigned</p>
      </div>
      <Badge status={titleCase(course.status)} />
    </div>
    <div className="mt-3 flex flex-wrap gap-2">
      {batches.map(batch => <span key={batch.id} className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600">{batch.batch_name}</span>)}
      {!batches.length && <span className="text-sm text-slate-500">Create a batch under this course</span>}
    </div>
  </div>;
}

function Brand() {
  return <div className="flex min-w-0 items-center gap-3">
    <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-[#082248] text-xl font-black text-[#c89736]">V</div>
    <div className="min-w-0">
      <p className="truncate text-xl font-black uppercase tracking-[0.16em] text-[#082248]">VERNEX</p>
      <p className="truncate text-xs font-semibold uppercase tracking-[0.18em] text-[#c89736]">GEN TECHNOLOGIES</p>
    </div>
  </div>;
}

function ClockBox() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-right">
    <p className="text-sm font-bold text-[#082248]">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</p>
    <p className="text-xs font-semibold text-slate-500">{now.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" })}</p>
  </div>;
}

function mapPerson(person) {
  return {
    ...person,
    course_name: person.course_name || person.category_program || "",
    batch_name: person.batch_name || "",
    status: person.status || "active",
    face_enrollment_status: person.face_enrollment_status || "not_started"
  };
}

function mapAttendance(record) {
  return {
    ...record,
    status: toUiStatus(record.status),
    course_name: record.course_name || record.category_program || "",
    batch_name: record.batch_name || "",
    marked_time: record.marked_time || record.created_at || new Date().toISOString()
  };
}

function toPersonPayload(form, apiType) {
  return {
    person_code: form.person_code,
    full_name: form.full_name,
    phone: apiType === "student" ? null : form.phone || null,
    email: form.email || null,
    person_type: apiType,
    guardian_name: form.guardian_name || null,
    guardian_phone: apiType === "student" ? form.phone || null : null,
    course_id: form.course_id ? Number(form.course_id) : null,
    batch_id: form.batch_id ? Number(form.batch_id) : null,
    level_class: form.level_class || null,
    joining_date: form.joining_date || null,
    status: form.status,
    face_enrollment_status: form.face_enrollment_status,
    notes: form.notes || null
  };
}

function courseName(courses, id) {
  return courses.find(course => Number(course.id) === Number(id))?.course_name || "-";
}

function batchName(batches, id) {
  return batches.find(batch => Number(batch.id) === Number(id))?.batch_name || "-";
}

function statusOptions() {
  return [{ value: "active", label: "Active" }, { value: "pending", label: "Pending" }, { value: "inactive", label: "Inactive" }];
}

function toUiStatus(value) {
  const normalized = String(value || "pending").toLowerCase();
  if (normalized === "not_started" || normalized === "in_progress") return "Pending";
  if (normalized === "already marked") return "Already Marked";
  return titleCase(normalized);
}

function titleCase(value) {
  return String(value || "").replace(/_/g, " ").replace(/\w\S*/g, text => text.charAt(0).toUpperCase() + text.slice(1).toLowerCase());
}

function onlyNumbers(value) {
  return value.replace(/\D/g, "");
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

createRoot(document.getElementById("root")).render(<App />);
