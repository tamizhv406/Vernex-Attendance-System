import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { ShieldAlert } from "lucide-react";
import { getAttendanceToday, getBatches, getCourses, getPeople, getTimings, session } from "./lib/api";
import { SESSION_ENDED, landingPage, screenFor } from "./lib/auth";
import { mapAttendance, mapPerson } from "./lib/format";
import { Shell } from "./layout";
import { PAGES, PATH_TO_PAGE, ROUTES } from "./routes";
import ChangePasswordPage, { ForcedPasswordChange } from "./pages/ChangePassword";
import { BatchesPage, CoursesPage } from "./pages/Courses";
import Dashboard from "./pages/Dashboard";
import FaceEnrollment from "./pages/Enrollment";
import Login from "./pages/Login";
import PeoplePage from "./pages/People";
import Reports from "./pages/Reports";
import AttendanceScanner from "./pages/Scanner";
import SettingsPage from "./pages/Settings";
import AdminsPage from "./pages/portal/Admins";
import AuditLogPage from "./pages/portal/AuditLog";
import IssuesPage from "./pages/portal/Issues";
import PortalDashboard from "./pages/portal/PortalDashboard";
import { Button, EmptyState, Spinner } from "./ui";
import "./styles.css";

// The page an address stands for. "home" is not a page: it becomes the account's own start page.
function pageAt(path) {
  return PATH_TO_PAGE[path] || "home";
}

function App() {
  // { state: "checking" | "in" | "out", account, notice }, kept by lib/auth.js.
  const auth = useSyncExternalStore(session.subscribe, session.snapshot);
  const [page, setPageState] = useState(() => pageAt(location.pathname));
  const before = useRef("checking");
  // Where someone was headed when the login page took over.
  const wanted = useRef(null);
  const view = screenFor({ state: auth.state, account: auth.account, page, pages: PAGES });
  const show = (pageId, replace) => {
    setPageState(pageId);
    history[replace ? "replaceState" : "pushState"](null, "", ROUTES[pageId] || ROUTES.dashboard);
  };
  const setPage = pageId => { show(pageId); scrollTo({ top: 0 }); };
  // On load: is this browser still signed in? Nothing of the app is shown until that is known.
  useEffect(() => { session.restore(); }, []);
  useEffect(() => {
    const sync = () => setPageState(pageAt(location.pathname));
    addEventListener("popstate", sync);
    return () => removeEventListener("popstate", sync);
  }, []);
  useEffect(() => {
    const was = before.current;
    before.current = auth.state;
    if (auth.state === "out") {
      // Arriving logged out, or a session that ran out, leads back to that page after logging in.
      // After logging out on purpose there is nowhere to go back to.
      if (was === "checking") wanted.current = PAGES[page] ? page : null;
      else if (was === "in") wanted.current = auth.notice === SESSION_ENDED && PAGES[page] ? page : null;
      if (location.pathname !== ROUTES.login) history.replaceState(null, "", ROUTES.login);
    } else if (auth.state === "in" && was === "out") {
      show(landingPage({ wanted: wanted.current, account: auth.account, pages: PAGES }), true);
      wanted.current = null;
    }
  }, [auth.state]);
  useEffect(() => {
    // The address bar says what is on screen, also when it was something else that was typed.
    if (view.screen === "change-password" && location.pathname !== ROUTES.changePassword) history.replaceState(null, "", ROUTES.changePassword);
    if (view.screen === "page" && view.page !== page) show(view.page, true);
  }, [view.screen, view.page, page]);

  const logout = () => session.logout();
  if (view.screen === "checking") return <main className="grid min-h-screen place-items-center bg-canvas"><Spinner label="Checking your session" /></main>;
  if (view.screen === "login") return <Login notice={auth.notice} />;
  if (view.screen === "change-password") return <ForcedPasswordChange account={auth.account} logout={logout} />;
  return <Console page={view.page} allowed={view.screen === "page"} setPage={setPage} logout={logout} account={auth.account} />;
}

// Everything behind the login. It exists only while someone is logged in, so nothing is asked of the
// backend before that, and what was loaded is thrown away the moment they log out.
function Console({ page, allowed, setPage, logout, account }) {
  const data = useBackendData();
  return <Shell page={page} setPage={setPage} logout={logout} data={data} account={account}>
    {!allowed && <EmptyState icon={ShieldAlert} title="Not allowed" message="This page is for super admins only." action={<Button size="sm" onClick={() => setPage("dashboard")}>Go to the dashboard</Button>} />}
    {allowed && page === "superAdmin" && <PortalDashboard setPage={setPage} />}
    {allowed && page === "portalAdmins" && <AdminsPage account={account} notify={data.notify} />}
    {allowed && page === "portalIssues" && <IssuesPage setPage={setPage} />}
    {allowed && page === "portalAudit" && <AuditLogPage />}
    {allowed && page === "changePassword" && <ChangePasswordPage account={account} onCancel={() => setPage("settings")} />}
    {allowed && page === "dashboard" && <Dashboard data={data} setPage={setPage} />}
    {allowed && page === "courses" && <CoursesPage data={data} />}
    {allowed && page === "batches" && <BatchesPage data={data} />}
    {allowed && ["students", "staff", "members"].includes(page) && <PeoplePage page={page} data={data} />}
    {allowed && page === "enrollment" && <FaceEnrollment data={data} />}
    {allowed && page === "scanner" && <AttendanceScanner data={data} />}
    {allowed && page === "reports" && <Reports data={data} />}
    {allowed && page === "settings" && <SettingsPage data={data} logout={logout} account={account} setPage={setPage} />}
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
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);

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
  const dismissToast = () => { clearTimeout(toastTimer.current); setToast(null); };
  const notify = (message, tone = "success") => {
    clearTimeout(toastTimer.current);
    setToast({ message, tone });
    toastTimer.current = setTimeout(() => setToast(null), 3200);
  };
  return { people, courses, batches, timings, records, setPeople, setCourses, setBatches, setRecords, loading, error, toast, notify, dismissToast, refresh };
}

createRoot(document.getElementById("root")).render(<App />);
