import React, { useEffect, useState } from "react";
import { CalendarSearch, ClipboardCheck, Filter } from "lucide-react";
import { getAttendanceByDate, getAttendanceSessions, getSessionRecords } from "../lib/api";
import { WHO_OPTIONS, methodLabel, recordIsFor, scopePeople, sessionLabel, sessionsOn, withRecord } from "../lib/attendance";
import { batchName, courseName, formatTime, localDate, mapAttendance } from "../lib/format";
import { Button, Card, DataTable, EmptyState, ErrorState, FormInput, FormSelect, Identity, Notice, Page, SearchInput, Segmented, StatusBadge } from "../ui";
import { SessionRegister } from "./handMarks";

export default function Reports({ data }) {
  const [courseId, setCourseId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [date, setDate] = useState(localDate());
  const [rows, setRows] = useState([]);
  const [shown, setShown] = useState(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  // Students, staff or members. Staff and member records have no course or batch, so they are
  // found with "All courses" and narrowed here instead.
  const [who, setWho] = useState("all");
  const batches = data.batches.filter(batch => !courseId || Number(batch.course_id) === Number(courseId));
  useEffect(() => { if (batchId && !batches.some(batch => Number(batch.id) === Number(batchId))) setBatchId(""); }, [batchId, batches]);
  const load = async () => {
    setLoading(true);
    setMessage("");
    try {
      const result = await getAttendanceByDate(date, { course_id: courseId, batch_id: batchId });
      setRows((result || []).map(mapAttendance));
      setShown({ date, courseId, batchId });
    } catch (err) {
      setMessage(err.message || "Unable to load report data.");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);
  const forWho = rows.filter(record => recordIsFor(record, who));
  const count = name => forWho.filter(record => record.status === name).length;
  const statuses = ["Present", "Late", "Absent", "Visited"].filter(name => count(name) > 0);
  const visible = forWho
    .filter(record => status === "all" || record.status === status)
    .filter(record => [record.person_name, record.person_code, record.course_name, record.batch_name].filter(Boolean).join(" ").toLowerCase().includes(query.trim().toLowerCase()))
    .sort((a, b) => new Date(b.marked_time) - new Date(a.marked_time));
  // The table shows what was last loaded; say so when the filters have been changed since.
  const stale = shown && (shown.date !== date || shown.courseId !== courseId || shown.batchId !== batchId);

  return <Page title="Attendance Records" subtitle="Filter attendance by course, batch and date.">
    <Card title="Filters">
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_190px_auto]" onSubmit={event => { event.preventDefault(); load(); }}>
        <FormSelect label="Course" value={courseId} onChange={e => { setCourseId(e.target.value); setBatchId(""); }} options={[{ value: "", label: "All courses" }, ...data.courses.map(course => ({ value: course.id, label: course.course_name }))]} />
        <FormSelect label="Batch" value={batchId} onChange={e => setBatchId(e.target.value)} options={[{ value: "", label: "All batches" }, ...batches.map(batch => ({ value: batch.id, label: batch.batch_name }))]} />
        <FormInput label="Date" type="date" value={date} max={localDate()} onChange={e => setDate(e.target.value)} required />
        <div className="flex items-end"><Button icon={Filter} loading={loading} className="w-full xl:w-auto">Apply</Button></div>
      </form>
      {stale && !loading && <p className="mt-3 text-xs font-medium text-amber-700">Filters changed. Press Apply to update the records below.</p>}
    </Card>

    {message && <ErrorState title="Could not load records" message={message} onRetry={load} />}

    <Card title="Records" subtitle={shown ? `${rows.length} record${rows.length === 1 ? "" : "s"} on ${shown.date}` : undefined} action={rows.length > 0 && <SearchInput value={query} onChange={setQuery} placeholder="Search records" className="w-full sm:w-64" />}>
      {rows.length > 0 && <div className="mb-4 flex flex-wrap gap-2">
        <Segmented label="Who" value={who} onChange={setWho} options={WHO_OPTIONS.map(option => ({ ...option, count: rows.filter(record => recordIsFor(record, option.value)).length }))} />
        <Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "all", label: "All", count: forWho.length }, ...statuses.map(name => ({ value: name, label: name, count: count(name) }))]} />
      </div>}
      <DataTable loading={loading} caption="Attendance records" columns={["Person", "Course", "Batch", "Status", "Marked at", "Method"]} rowKeys={visible.map(record => record.id)} rows={visible.map(record => [
        <Identity name={record.person_name} detail={record.person_code} />,
        record.course_name || courseName(data.courses, record.course_id),
        record.batch_name || batchName(data.batches, record.batch_id),
        <StatusBadge status={record.status} />,
        <span className="whitespace-nowrap tabular-nums">{formatTime(record.marked_time)}</span>,
        methodLabel(record.recognition_method)
      ])} empty={rows.length ? <EmptyState icon={CalendarSearch} title="No records match" message="Try another search, person type or status." action={<Button variant="outline" size="sm" onClick={() => { setQuery(""); setStatus("all"); setWho("all"); }}>Clear</Button>} /> : <EmptyState icon={CalendarSearch} title="No attendance on this date" message="Choose another date, course or batch and press Apply." />} />
    </Card>

    <HandCorrections data={data} shown={shown} onRecord={record => { if (shown && record.attendance_date === shown.date) setRows(current => withRecord(current, record)); }} />
  </Page>;
}

// Marking or correcting attendance by hand, in one session of the batch and day that are shown. Every
// student of the batch is listed, marked or not; the backend keeps the record in that session and on
// its date, and writes each change to the audit log.
function HandCorrections({ data, shown, onRecord }) {
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const ready = Boolean(shown?.courseId && shown?.batchId);
  useEffect(() => {
    setSessions([]);
    setSessionId("");
    setRecords([]);
    setMessage("");
    if (!ready) return;
    let current = true;
    setLoading(true);
    getAttendanceSessions({ course_id: shown.courseId, batch_id: shown.batchId })
      .then(result => {
        if (!current) return;
        const that = sessionsOn(result || [], shown.date);
        setSessions(that);
        setSessionId(that[0] ? String(that[0].id) : "");
        if (!that.length) setLoading(false);
      })
      .catch(err => { if (current) { setMessage(err.message || "Unable to load the sessions."); setLoading(false); } });
    return () => { current = false; };
  }, [shown]);
  useEffect(() => {
    if (!sessionId) return;
    let current = true;
    setLoading(true);
    getSessionRecords(sessionId)
      .then(result => { if (current) setRecords((result || []).map(mapAttendance)); })
      .catch(err => { if (current) setMessage(err.message || "Unable to load the session's records."); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [sessionId]);
  const session = sessions.find(item => String(item.id) === sessionId);
  // The batch's active students, plus anyone with a record in this session, whose mark can be corrected.
  const students = scopePeople(data.people, { type: "regular", courseId: shown?.courseId, batchId: shown?.batchId }, records);
  const marked = (record, student) => {
    setRecords(current => withRecord(current, record));
    onRecord(record);
    data.notify(`${student.full_name} marked ${record.status} by hand.`);
  };
  return <Card title="Mark or correct by hand" subtitle="For a student the scanner could not mark, or a mark that is wrong. Each change is kept in the audit log.">
    {!ready ? <EmptyState icon={ClipboardCheck} title="Choose a course and a batch" message="Then press Apply. The sessions of that batch on the chosen date are listed here." />
      : message ? <ErrorState title="Could not load the session" message={message} />
      : !loading && !sessions.length ? <EmptyState icon={ClipboardCheck} title={`No session of this batch on ${shown.date}`} message="Attendance is always marked in a session. Start one on Live Attendance." />
      : <div className="grid gap-4">
        {sessions.length > 1 && <FormSelect label="Session" value={sessionId} onChange={event => setSessionId(event.target.value)} options={sessions.map(item => ({ value: String(item.id), label: sessionLabel(item) }))} className="max-w-md" />}
        {session && sessions.length === 1 && <p className="text-sm text-ink-muted">{sessionLabel(session)}</p>}
        {session && session.status === "active" && <Notice tone="info">This session is still running. Marks made here and by the scanner go into the same register.</Notice>}
        {session ? <SessionRegister session={session} students={students} records={records} onRecord={marked} loading={loading} /> : <DataTable loading rows={[]} columns={[]} />}
      </div>}
  </Card>;
}
