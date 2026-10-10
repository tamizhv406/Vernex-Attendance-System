import React, { useEffect, useMemo, useState } from "react";
import { Plus, UserPlus, Users, X } from "lucide-react";
import { createPerson, deletePerson } from "../lib/api";
import { faceEnrolled, onlyNumbers, statusOptions, toPersonPayload } from "../lib/format";
import { PERSON_CONFIG } from "../routes";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, FormInput, FormSelect, FormTextarea, Identity, Notice, Page, RowActions, SearchInput, Segmented, StatusBadge } from "../ui";

// Only what the list shows is searched. Notes and internal ids are left out of the match.
function matches(person, query) {
  const text = [person.full_name, person.person_code, person.phone, person.guardian_phone, person.guardian_name, person.email, person.course_name, person.batch_name, person.level_class].filter(Boolean).join(" ").toLowerCase();
  return text.includes(query.trim().toLowerCase());
}

export default function PeoplePage({ page, data }) {
  const config = PERSON_CONFIG[page];
  const isStudent = config.apiType === "student";
  const blank = { person_code: "", full_name: "", guardian_name: "", phone: "", email: "", course_id: "", batch_id: "", level_class: "", joining_date: "", status: "active", face_enrollment_status: "not_started", notes: "" };
  const [form, setForm] = useState(blank);
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [courseFilter, setCourseFilter] = useState("");
  const [faceFilter, setFaceFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const availableBatches = useMemo(
    () => data.batches.filter(batch => Number(batch.course_id) === Number(form.course_id)),
    [data.batches, form.course_id],
  );
  const everyone = data.people.filter(person => person.person_type === config.apiType);
  const inCourse = everyone.filter(person => !courseFilter || Number(person.course_id) === Number(courseFilter));
  const rows = inCourse.filter(person => faceFilter === "all" || (faceFilter === "enrolled") === faceEnrolled(person)).filter(person => matches(person, query));
  useEffect(() => {
    if (form.batch_id && !availableBatches.some(batch => Number(batch.id) === Number(form.batch_id))) setForm(current => ({ ...current, batch_id: "" }));
  }, [form.batch_id, availableBatches]);
  // Moving between Students, Staff and Members starts each list clean.
  useEffect(() => { setForm(blank); setAdding(false); setQuery(""); setCourseFilter(""); setFaceFilter("all"); setMessage(""); }, [page]);
  const save = async event => {
    event.preventDefault();
    if (saving) return;
    if (isStudent && (!form.course_id || !form.batch_id)) {
      setMessage("Student must select an existing course and batch.");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      await createPerson(toPersonPayload(form, config.apiType));
      setForm(blank);
      setAdding(false);
      data.notify(`${config.singular} created.`);
      await data.refresh();
    } catch (err) {
      setMessage(err.message || `Unable to create ${config.singular.toLowerCase()}.`);
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setDeleting(true);
    try {
      await deletePerson(removing.id);
      data.notify(`${config.singular} deleted.`);
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete user.");
    } finally {
      setDeleting(false);
      setRemoving(null);
    }
  };
  const filtered = Boolean(query || courseFilter || faceFilter !== "all");
  return <Page title={config.title} subtitle={isStudent ? "Students are assigned to an existing course and batch." : `${config.title} can be assigned to a course and batch.`} actions={<Button variant={adding ? "outline" : "primary"} icon={adding ? X : UserPlus} onClick={() => setAdding(current => !current)} aria-expanded={adding}>{adding ? "Close form" : `Add ${config.singular.toLowerCase()}`}</Button>}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    {adding && <Card title={`New ${config.singular.toLowerCase()}`} subtitle="Fields marked * are required." className="animate-fade-up">
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" onSubmit={save}>
        <FormInput label={`${config.singular} ID`} value={form.person_code} onChange={e => setForm({ ...form, person_code: e.target.value })} required autoFocus />
        <FormInput label="Full name" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} required />
        {isStudent && <FormInput label="Parent name" value={form.guardian_name} onChange={e => setForm({ ...form, guardian_name: e.target.value })} />}
        <FormInput label={isStudent ? "Parent contact" : "Contact number"} inputMode="numeric" maxLength={10} hint="Up to 10 digits." value={form.phone} onChange={e => setForm({ ...form, phone: onlyNumbers(e.target.value).slice(0, 10) })} required />
        {!isStudent && <FormInput label="Email" type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />}
        <FormSelect label="Course" value={form.course_id} onChange={e => setForm({ ...form, course_id: e.target.value, batch_id: "" })} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" required={isStudent} />
        <FormSelect label="Batch" value={form.batch_id} onChange={e => setForm({ ...form, batch_id: e.target.value })} options={availableBatches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={form.course_id ? "Create a batch under this course" : "Select course first"} required={isStudent} />
        <FormInput label="Level / class" value={form.level_class} onChange={e => setForm({ ...form, level_class: e.target.value })} />
        <FormInput label="Joining date" type="date" value={form.joining_date} onChange={e => setForm({ ...form, joining_date: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <FormSelect label="Face enrollment status" value={form.face_enrollment_status} onChange={e => setForm({ ...form, face_enrollment_status: e.target.value })} options={[{ value: "not_started", label: "Pending" }, { value: "completed", label: "Completed" }]} />
        <FormTextarea label="Notes" className="md:col-span-2 xl:col-span-3" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Optional notes" />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end md:col-span-2 xl:col-span-3">
          <Button type="button" variant="outline" onClick={() => { setAdding(false); setForm(blank); }}>Cancel</Button>
          <Button icon={Plus} loading={saving}>Save {config.singular.toLowerCase()}</Button>
        </div>
      </form>
    </Card>}
    <Card title={`All ${config.title.toLowerCase()}`} subtitle={filtered ? `${rows.length} of ${everyone.length} shown` : `${everyone.length} in total`}>
      <div className="mb-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_220px_auto] lg:items-end">
        <SearchInput value={query} onChange={setQuery} placeholder={`Search ${config.title.toLowerCase()} by name, ID, contact or batch`} />
        <FormSelect label="Course" value={courseFilter} onChange={e => setCourseFilter(e.target.value)} options={[{ value: "", label: "All courses" }, ...data.courses.map(course => ({ value: course.id, label: course.course_name }))]} />
        <Segmented label="Face enrollment" value={faceFilter} onChange={setFaceFilter} options={[
          { value: "all", label: "All", count: inCourse.length },
          { value: "enrolled", label: "Enrolled", count: inCourse.filter(faceEnrolled).length },
          { value: "pending", label: "Pending", count: inCourse.filter(person => !faceEnrolled(person)).length }
        ]} />
      </div>
      <DataTable loading={data.loading} caption={config.title} columns={[config.singular, "Contact", "Course", "Batch", "Status", "Face", "Actions"]} rows={rows.map(person => [
        <Identity name={person.full_name} detail={person.person_code} />,
        person.guardian_phone || person.phone || "-",
        person.course_name || "-",
        person.batch_name || "-",
        <StatusBadge status={person.status} />,
        <StatusBadge status={faceEnrolled(person) ? "Enrolled" : "Pending"} />,
        <RowActions name={person.full_name} onDelete={() => setRemoving(person)} />
      ])} empty={filtered ? <EmptyState icon={Users} title={`No ${config.title.toLowerCase()} match`} message="Try another search or clear the filters." action={<Button variant="outline" size="sm" onClick={() => { setQuery(""); setCourseFilter(""); setFaceFilter("all"); }}>Clear filters</Button>} /> : <EmptyState icon={Users} title={`No ${config.title.toLowerCase()} yet`} message={isStudent && !data.courses.length ? "Create a course and a batch first, then add students." : `Add the first ${config.singular.toLowerCase()} to get started.`} action={<Button size="sm" icon={UserPlus} onClick={() => setAdding(true)}>Add {config.singular.toLowerCase()}</Button>} />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title={`Delete ${removing?.full_name || "this person"}?`} message="This removes the person and their enrolled face data. It cannot be undone." onConfirm={remove} onCancel={() => setRemoving(null)} />
  </Page>;
}
