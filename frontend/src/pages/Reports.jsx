import React, { useEffect, useState } from "react";
import { CalendarSearch, Filter } from "lucide-react";
import { getAttendanceByDate } from "../lib/api";
import { batchName, courseName, formatTime, localDate, mapAttendance } from "../lib/format";
import { Button, Card, DataTable, EmptyState, ErrorState, FormInput, FormSelect, Identity, Page, SearchInput, Segmented, StatusBadge } from "../ui";

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
  const count = name => rows.filter(record => record.status === name).length;
  const statuses = ["Present", "Late", "Absent"].filter(name => count(name) > 0);
  const visible = rows
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
      {rows.length > 0 && <div className="mb-4"><Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "all", label: "All", count: rows.length }, ...statuses.map(name => ({ value: name, label: name, count: count(name) }))]} /></div>}
      <DataTable loading={loading} caption="Attendance records" columns={["Person", "Course", "Batch", "Status", "Marked at", "Method"]} rows={visible.map(record => [
        <Identity name={record.person_name} detail={record.person_code} />,
        record.course_name || courseName(data.courses, record.course_id),
        record.batch_name || batchName(data.batches, record.batch_id),
        <StatusBadge status={record.status} />,
        <span className="whitespace-nowrap tabular-nums">{formatTime(record.marked_time)}</span>,
        record.recognition_method === "face_ai" ? "Face scan" : record.recognition_method ? String(record.recognition_method).replace(/_/g, " ") : "-"
      ])} empty={rows.length ? <EmptyState icon={CalendarSearch} title="No records match" message="Try another search or status." action={<Button variant="outline" size="sm" onClick={() => { setQuery(""); setStatus("all"); }}>Clear</Button>} /> : <EmptyState icon={CalendarSearch} title="No attendance on this date" message="Choose another date, course or batch and press Apply." />} />
    </Card>
  </Page>;
}
