import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { ShieldAlert } from "lucide-react";
import { getAttendanceToday, getBatches, getCourses, getPeople, getTimings, session } from "./lib/api";
import { SESSION_ENDED, landingPage, screenFor } from "./lib/auth";
import { mapAttendance, mapPerson } from "./lib/format";
import { Shell } from "./layout";
import { PAGES, ROUTES, isPortalPage, locationView, pathFor } from "./routes";
import ChangePasswordPage, { ForcedPasswordChange } from "./pages/ChangePassword";
import { BatchesPage, CoursesPage } from "./pages/Courses";
import Dashboard from "./pages/Dashboard";
import FaceEnrollment from "./pages/Enrollment";
import { useOpenIssueCount } from "./pages/issueParts";
import Login from "./pages/Login";
import MyReportsPage from "./pages/MyReports";
import PeoplePage from "./pages/People";
import ReportProblem from "./pages/ReportProblem";
import Reports from "./pages/Reports";
import AttendanceScanner from "./pages/Scanner";
import SettingsPage from "./pages/Settings";
import AdminsPage from "./pages/portal/Admins";
import AuditLogPage from "./pages/portal/AuditLog";
import IssuesPage from "./pages/portal/Issues";
import PortalDashboard from "./pages/portal/PortalDashboard";
import { Button, EmptyState, Spinner } from "./ui";
import "./styles.css";

function App() {
  // { state: "checking" | "in" | "out", account, notice }, kept by lib/auth.js.
  const auth = useSyncExternalStore(session.subscribe, session.snapshot);
  // The page an address stands for, and the issue it shows if it shows one (/my-reports/12). A page
  // of "home" is not a page: it becomes the account's own start page.
  const [place, setPlace] = useState(() => locationView(location.pathname));
  const { page, issueId } = place;
  const before = useRef("checking");
  // Where someone was headed when the login page took over: { page, issueId }.
  const wanted = useRef(null);
  const view = screenFor({ state: auth.state, account: auth.account, page, pages: PAGES });
  const show = (pageId, replace, issue = null) => {
    setPlace({ page: pageId, issueId: issue });
    history[replace ? "replaceState" : "pushState"](null, "", pathFor(pageId, issue));
  };
  const setPage = (pageId, issue = null) => { show(pageId, false, issue); scrollTo({ top: 0 }); };
  // On load: is this browser still signed in? Nothing of the app is shown until that is known.
  useEffect(() => { session.restore(); }, []);
  useEffect(() => {
    const sync = () => setPlace(locationView(location.pathname));
    addEventListener("popstate", sync);
    return () => removeEventListener("popstate", sync);
  }, []);
  useEffect(() => {
    const was = before.current;
    before.current = auth.state;
    if (auth.state === "out") {
      // Arriving logged out, or a session that ran out, leads back to that page after logging in.
      // After logging out on purpose there is nowhere to go back to.
      if (was === "checking") wanted.current = PAGES[page] ? place : null;
      else if (was === "in") wanted.current = auth.notice === SESSION_ENDED && PAGES[page] ? place : null;
      if (location.pathname !== ROUTES.login) history.replaceState(null, "", ROUTES.login);
    } else if (auth.state === "in" && was === "out") {
      const landing = landingPage({ wanted: wanted.current?.page, account: auth.account, pages: PAGES });
      show(landing, true, landing === wanted.current?.page ? wanted.current.issueId : null);
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
  return <Console page={view.page} issueId={view.page === page ? issueId : null} allowed={view.screen === "page"} setPage={setPage} logout={logout} account={auth.account} />;
}

// Everything behind the login. It exists only while someone is logged in, so nothing is asked of the
// backend before that, and what was loaded is thrown away the moment they log out.
function Console({ page, issueId, allowed, setPage, logout, account }) {
  const data = useBackendData();
  // "Report a problem" is open over the page; reported counts the reports made since, so that My
  // reports asks again.
  const [reporting, setReporting] = useState(false);
  const [reported, setReported] = useState(0);
  // The portal's badge, asked for only while a super admin has a portal page open.
  const openIssues = useOpenIssueCount(account.role === "super_admin" && isPortalPage(page));
  const report = () => setReporting(true);
  return <Shell page={page} setPage={setPage} logout={logout} data={data} account={account} onReport={report} badges={{ portalIssues: openIssues.count }}>
    {!allowed && <EmptyState icon={ShieldAlert} title="Not allowed" message="This page is for super admins only." action={<Button size="sm" onClick={() => setPage("dashboard")}>Go to the dashboard</Button>} />}
    {allowed && page === "superAdmin" && <PortalDashboard setPage={setPage} />}
    {allowed && page === "portalAdmins" && <AdminsPage account={account} notify={data.notify} />}
    {allowed && page === "portalIssues" && <IssuesPage issueId={issueId} setPage={setPage} onChanged={openIssues.refresh} notify={data.notify} />}
    {allowed && page === "portalAudit" && <AuditLogPage />}
    {allowed && page === "myReports" && <MyReportsPage issueId={issueId} setPage={setPage} onReport={report} reported={reported} />}
    {allowed && page === "changePassword" && <ChangePasswordPage account={account} onCancel={() => setPage("settings")} />}
    {allowed && page === "dashboard" && <Dashboard data={data} setPage={setPage} />}
    {allowed && page === "courses" && <CoursesPage data={data} />}
    {allowed && page === "batches" && <BatchesPage data={data} />}
    {allowed && ["students", "staff", "members"].includes(page) && <PeoplePage page={page} data={data} />}
    {allowed && page === "enrollment" && <FaceEnrollment data={data} />}
    {allowed && page === "scanner" && <AttendanceScanner data={data} />}
    {allowed && page === "reports" && <Reports data={data} />}
    {allowed && page === "settings" && <SettingsPage data={data} logout={logout} account={account} setPage={setPage} />}
    {reporting && <ReportProblem onClose={() => setReporting(false)}
      onReported={() => { setReported(count => count + 1); openIssues.refresh(); }}
      onOpenReport={id => { setReporting(false); setPage("myReports", id); }} />}
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
