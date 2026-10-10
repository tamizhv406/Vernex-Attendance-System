import React from "react";
import { ArrowRight, BookOpen, CalendarCheck, Clock, GraduationCap, Layers3, ScanFace, ScanLine, UserPlus } from "lucide-react";
import { faceEnrolled, formatClock } from "../lib/format";
import { Button, Card, EmptyState, Identity, Page, ProgressRing, Skeleton, StatCard, StatusBadge } from "../ui";

// Every number on this page is counted from what the backend returned: the people list, the course
// and batch lists, and today's attendance records. Nothing is estimated.
export default function Dashboard({ data, setPage }) {
  const today = data.records;
  const students = data.people.filter(person => person.person_type === "student");
  const enrolled = students.filter(faceEnrolled).length;
  const count = status => today.filter(record => record.status === status).length;
  const present = count("Present");
  const late = count("Late");
  const absent = count("Absent");
  const studentIds = new Set(students.map(student => student.id));
  const attended = new Set(today.filter(record => ["Present", "Late"].includes(record.status) && studentIds.has(record.person_id)).map(record => record.person_id)).size;
  const recent = [...today].sort((a, b) => new Date(b.marked_time) - new Date(a.marked_time)).slice(0, 6);
  const loading = data.loading;
  const breakdown = [{ label: "Present", value: present, bar: "bg-emerald-500" }, { label: "Late", value: late, bar: "bg-amber-500" }, { label: "Absent", value: absent, bar: "bg-red-500" }];

  return <Page title="Dashboard" subtitle="Today's attendance at a glance." actions={<>
    <Button variant="outline" icon={ScanFace} onClick={() => setPage("enrollment")}>Enroll a face</Button>
    <Button variant="brand" icon={ScanLine} onClick={() => setPage("scanner")}>Start scanning</Button>
  </>}>
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard icon={GraduationCap} label="Students" value={students.length} detail={`${enrolled} with a face enrolled`} loading={loading} />
      <StatCard icon={CalendarCheck} label="Present today" value={present} detail={`${today.length} record${today.length === 1 ? "" : "s"} today`} loading={loading} accent />
      <StatCard icon={Clock} label="Late today" value={late} detail={absent ? `${absent} marked absent` : "None marked absent"} loading={loading} />
      <StatCard icon={BookOpen} label="Courses" value={data.courses.length} detail={`${data.batches.length} batch${data.batches.length === 1 ? "" : "es"}`} loading={loading} />
    </div>

    <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
      <Card title="Today's attendance" subtitle="Students marked present or late today." className="xl:col-span-1">
        {loading ? <div className="grid place-items-center py-4"><Skeleton className="h-32 w-32 rounded-full" /></div> : !students.length ? <EmptyState icon={GraduationCap} title="No students yet" message="Add students to see how many attend each day." action={<Button size="sm" icon={UserPlus} onClick={() => setPage("students")}>Add a student</Button>} /> : <div className="flex flex-col items-center gap-6 sm:flex-row xl:flex-col">
          <ProgressRing value={attended} total={students.length} label={`${attended} of ${students.length} students attended today`} />
          <dl className="grid w-full flex-1 gap-3">
            {breakdown.map(item => <div key={item.label}>
              <div className="flex items-center justify-between text-sm"><dt className="font-medium text-ink-soft">{item.label}</dt><dd className="font-bold tabular-nums text-ink">{item.value}</dd></div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-canvas" aria-hidden="true"><div className={`h-full rounded-full transition-[width] duration-700 ease-out ${item.bar}`} style={{ width: today.length ? `${(item.value / today.length) * 100}%` : "0%" }} /></div>
            </div>)}
            {!today.length && <p className="text-sm text-ink-muted">No attendance has been recorded today.</p>}
          </dl>
        </div>}
      </Card>

      <Card title="Recent activity" subtitle="The latest attendance records from today." className="xl:col-span-2" action={<Button variant="outline" size="sm" onClick={() => setPage("reports")}>All records<ArrowRight size={15} aria-hidden="true" /></Button>}>
        {loading ? <div className="grid gap-3">{[0, 1, 2, 3].map(index => <Skeleton key={index} className="h-14 w-full" />)}</div> : !recent.length ? <EmptyState icon={ScanLine} title="No scans recorded today" message="Records appear here as soon as the scanner marks someone." action={<Button variant="brand" size="sm" icon={ScanLine} onClick={() => setPage("scanner")}>Open the scanner</Button>} /> : <ul className="divide-y divide-line">
          {recent.map(record => <li key={record.id ?? `${record.person_id}-${record.marked_time}`} className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0">
            <Identity name={record.person_name} detail={[record.person_code, record.course_name, record.batch_name].filter(Boolean).join(" · ")} />
            <div className="flex shrink-0 items-center gap-3">
              <span className="hidden text-xs font-medium tabular-nums text-ink-muted sm:inline">{formatClock(record.marked_time)}</span>
              <StatusBadge status={record.status} />
            </div>
          </li>)}
        </ul>}
      </Card>
    </div>

    <div className="grid grid-cols-1 gap-5 xl:grid-cols-3">
      <Card title="Courses and batches" subtitle="Who is assigned where." className="xl:col-span-2" action={<Button variant="outline" size="sm" onClick={() => setPage("courses")}>Manage<ArrowRight size={15} aria-hidden="true" /></Button>}>
        {loading ? <div className="grid gap-3 md:grid-cols-2">{[0, 1].map(index => <Skeleton key={index} className="h-24 w-full" />)}</div> : !data.courses.length ? <EmptyState icon={BookOpen} title="Create a course first" message="Courses come before batches, students, enrollment and attendance." action={<Button size="sm" icon={BookOpen} onClick={() => setPage("courses")}>Create a course</Button>} /> : <div className="grid gap-3 md:grid-cols-2">
          {data.courses.map(course => <CourseSummary key={course.id} course={course} batches={data.batches.filter(batch => batch.course_id === course.id)} people={data.people} />)}
        </div>}
      </Card>

      <Card title="Face enrollment" subtitle="Students who can be recognized by the scanner.">
        {loading ? <Skeleton className="h-28 w-full" /> : !students.length ? <EmptyState icon={ScanFace} title="Nothing to enroll yet" message="Students appear here once they are added." /> : <div>
          <div className="flex items-end justify-between">
            <p className="text-3xl font-extrabold tabular-nums tracking-tight text-ink">{enrolled}<span className="text-base font-semibold text-ink-muted"> / {students.length}</span></p>
            <StatusBadge tone={enrolled === students.length ? "success" : "warning"}>{enrolled === students.length ? "All enrolled" : `${students.length - enrolled} pending`}</StatusBadge>
          </div>
          <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-canvas" role="progressbar" aria-valuemin={0} aria-valuemax={students.length} aria-valuenow={enrolled} aria-label="Students with a face enrolled"><div className="h-full rounded-full bg-brand-600 transition-[width] duration-700 ease-out" style={{ width: `${(enrolled / students.length) * 100}%` }} /></div>
          <Button variant="outline" className="mt-5 w-full" icon={ScanFace} onClick={() => setPage("enrollment")}>Go to enrollment</Button>
        </div>}
      </Card>
    </div>
  </Page>;
}

function CourseSummary({ course, batches, people }) {
  const assigned = people.filter(person => Number(person.course_id) === Number(course.id)).length;
  return <div className="rounded-2xl border border-line bg-canvas/50 p-4">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate font-semibold text-ink">{course.course_name}</p>
        <p className="text-xs text-ink-muted">{course.course_code} · {assigned} assigned</p>
      </div>
      <StatusBadge status={course.status} />
    </div>
    <div className="mt-3 flex flex-wrap gap-1.5">
      {batches.map(batch => <span key={batch.id} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-1 text-xs font-medium text-ink-soft"><Layers3 size={12} aria-hidden="true" />{batch.batch_name}</span>)}
      {!batches.length && <span className="text-xs text-ink-muted">No batches under this course yet.</span>}
    </div>
  </div>;
}
