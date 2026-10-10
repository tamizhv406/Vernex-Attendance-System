import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { getAttendanceToday, getBatches, getCourses, getPeople, getTimings } from "./lib/api";
import { mapAttendance, mapPerson } from "./lib/format";
import { Shell } from "./layout";
import { PATH_TO_PAGE, ROUTES } from "./routes";
import { BatchesPage, CoursesPage } from "./pages/Courses";
import Dashboard from "./pages/Dashboard";
import FaceEnrollment from "./pages/Enrollment";
import Login from "./pages/Login";
import PeoplePage from "./pages/People";
import Reports from "./pages/Reports";
import AttendanceScanner from "./pages/Scanner";
import SettingsPage from "./pages/Settings";
import "./styles.css";

function App() {
  const [logged, setLogged] = useState(localStorage.getItem("vx_auth") === "yes");
  const [page, setPageState] = useState(() => PATH_TO_PAGE[location.pathname] || "dashboard");
  const data = useBackendData();
  const setPage = pageId => {
    setPageState(pageId);
    history.pushState(null, "", ROUTES[pageId] || "/dashboard");
    scrollTo({ top: 0 });
  };
  useEffect(() => {
    const sync = () => setPageState(PATH_TO_PAGE[location.pathname] || "dashboard");
    addEventListener("popstate", sync);
    return () => removeEventListener("popstate", sync);
  }, []);
  const logout = () => { localStorage.removeItem("vx_auth"); setLogged(false); };
  if (!logged) return <Login onLogin={() => { localStorage.setItem("vx_auth", "yes"); setLogged(true); }} />;
  return <Shell page={page} setPage={setPage} logout={logout} data={data}>
    {page === "dashboard" && <Dashboard data={data} setPage={setPage} />}
    {page === "courses" && <CoursesPage data={data} />}
    {page === "batches" && <BatchesPage data={data} />}
    {["students", "staff", "members"].includes(page) && <PeoplePage page={page} data={data} />}
    {page === "enrollment" && <FaceEnrollment data={data} />}
    {page === "scanner" && <AttendanceScanner data={data} />}
    {page === "reports" && <Reports data={data} />}
    {page === "settings" && <SettingsPage data={data} logout={logout} />}
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
