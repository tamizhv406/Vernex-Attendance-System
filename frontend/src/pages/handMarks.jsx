// Marking attendance by hand: for a student the scanner could not mark (locked after wrong answers,
// not recognized, no face enrolled), and for correcting a record afterwards. Used on the live scanner
// page and on Attendance Records. The backend checks the session, dates the record with it, stores it
// as a hand mark and writes the audit log; a student who is already marked is corrected.
import React, { useState } from "react";
import { Users } from "lucide-react";
import { markAttendance } from "../lib/api";
import { handMark, handStatuses, methodLabel, registerRows, statusOf } from "../lib/attendance";
import { faceEnrolled, mapAttendance, titleCase } from "../lib/format";
import { DataTable, EmptyState, Identity, Notice, StatusBadge } from "../ui";

// mark(student, status) sends one hand mark; busy is the id of the student being marked.
export function useHandMarks(session, onRecord) {
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  const mark = async (student, status) => {
    setBusy(student.id);
    setError("");
    try {
      const record = await markAttendance(handMark(session, student, status));
      onRecord(mapAttendance(record), student, status);
    } catch (err) {
      setError(`${student.full_name}: ${err.message || "Attendance could not be marked."}`);
    } finally {
      setBusy(null);
    }
  };
  return { busy, error, clearError: () => setError(""), mark };
}

export function HandMarkButtons({ session, student, current, busy, disabled, onMark }) {
  return <div role="group" aria-label={`Mark ${student.full_name} by hand`} className="flex flex-wrap gap-1.5">
    {handStatuses(session).map(status => {
      const chosen = current === status;
      return <button key={status} type="button" aria-pressed={chosen} disabled={busy || disabled || chosen} onClick={() => onMark(student, status)}
        className={`h-8 rounded-full px-3 text-xs font-semibold ring-1 ring-inset transition duration-150 disabled:cursor-default ${chosen ? "bg-ink text-white ring-ink" : "bg-white text-ink-soft ring-line hover:bg-canvas disabled:opacity-50"}`}>
        {titleCase(status)}
      </button>;
    })}
  </div>;
}

// The whole register of one session: every student of its batch, what they have, and the buttons.
export function SessionRegister({ session, students, records, onRecord, loading }) {
  const hands = useHandMarks(session, onRecord);
  const rows = registerRows(students, records, session.id);
  return <div className="grid gap-3">
    {hands.error && <Notice tone="danger" onClose={hands.clearError}>{hands.error}</Notice>}
    <DataTable loading={loading} caption={`Register of ${session.session_name}`} columns={["Student", "Face", "Status", "How", "Mark by hand"]} rowKeys={rows.map(row => row.student.id)} rows={rows.map(({ student, record }) => [
      <Identity name={student.full_name} detail={student.person_code} />,
      <StatusBadge status={faceEnrolled(student) ? "Enrolled" : "Pending"} />,
      record ? <StatusBadge status={record.status} /> : <StatusBadge tone="neutral">Not marked</StatusBadge>,
      record ? methodLabel(record.recognition_method) : "-",
      <HandMarkButtons session={session} student={student} current={statusOf(record)} busy={hands.busy === student.id} disabled={hands.busy !== null} onMark={hands.mark} />
    ])} empty={<EmptyState icon={Users} title="No students in this batch" message="Add students to the batch first." />} />
  </div>;
}
