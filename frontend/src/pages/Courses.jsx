import React, { useEffect, useState } from "react";
import { BookOpen, Layers3, Plus, Save } from "lucide-react";
import { createBatch, createCourse, deleteBatch, deleteCourse, updateBatch, updateCourse } from "../lib/api";
import { courseName, statusOptions } from "../lib/format";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, FormInput, FormSelect, Notice, Page, RowActions, StatusBadge } from "../ui";

export function CoursesPage({ data }) {
  const blank = { course_code: "", course_name: "", description: "", status: "active" };
  const [form, setForm] = useState(blank);
  const [editing, setEditing] = useState(null);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const save = async event => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setMessage("");
    try {
      if (editing) await updateCourse(editing, form);
      else await createCourse(form);
      setForm(blank);
      setEditing(null);
      data.notify(editing ? "Course updated." : "Course created.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to save course.");
    } finally {
      setSaving(false);
    }
  };
  const edit = course => {
    setEditing(course.id);
    setForm({ course_code: course.course_code || "", course_name: course.course_name || "", description: course.description || "", status: course.status || "active" });
    scrollTo({ top: 0, behavior: "smooth" });
  };
  const remove = async () => {
    setDeleting(true);
    try {
      await deleteCourse(removing.id);
      data.notify("Course deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete course.");
    } finally {
      setDeleting(false);
      setRemoving(null);
    }
  };
  return <Page title="Courses" subtitle="Create a course before its batches and students.">
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <Card title={editing ? "Edit course" : "New course"} subtitle={editing ? "Change the details and save." : "The code must be unique."}>
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[150px_1fr_1fr_150px_auto]" onSubmit={save}>
        <FormInput label="Course code" value={form.course_code} onChange={e => setForm({ ...form, course_code: e.target.value })} required />
        <FormInput label="Course name" value={form.course_name} onChange={e => setForm({ ...form, course_name: e.target.value })} required />
        <FormInput label="Description" value={form.description || ""} onChange={e => setForm({ ...form, description: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <div className="flex items-end gap-2 md:col-span-2 xl:col-span-1">
          <Button icon={Save} loading={saving}>{editing ? "Save" : "Create"}</Button>
          {editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</Button>}
        </div>
      </form>
    </Card>
    <Card title="All courses" subtitle={`${data.courses.length} course${data.courses.length === 1 ? "" : "s"}`}>
      <DataTable loading={data.loading} caption="Courses" columns={["Course", "Code", "Description", "Batches", "Status", "Actions"]} rows={data.courses.map(course => [
        <span className="font-semibold text-ink">{course.course_name}</span>,
        course.course_code,
        course.description || "-",
        data.batches.filter(batch => Number(batch.course_id) === Number(course.id)).length,
        <StatusBadge status={course.status} />,
        <RowActions name={course.course_name} onEdit={() => edit(course)} onDelete={() => setRemoving(course)} />
      ])} empty={<EmptyState icon={BookOpen} title="No courses yet" message="Create the first course with the form above." />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title="Delete this course?" message={`"${removing?.course_name}" will be removed. A course that still has batches, people or attendance cannot be deleted.`} onConfirm={remove} onCancel={() => setRemoving(null)} />
  </Page>;
}

export function BatchesPage({ data }) {
  const firstCourseId = data.courses[0]?.id || "";
  const [selectedCourseId, setSelectedCourseId] = useState(firstCourseId);
  const [editing, setEditing] = useState(null);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const blank = { batch_name: "", batch_level: "", timing_id: "", status: "active" };
  const [form, setForm] = useState(blank);
  useEffect(() => { if (!selectedCourseId && firstCourseId) setSelectedCourseId(firstCourseId); }, [firstCourseId, selectedCourseId]);
  const courseBatches = data.batches.filter(batch => Number(batch.course_id) === Number(selectedCourseId));
  const save = async event => {
    event.preventDefault();
    if (saving) return;
    if (!selectedCourseId) { setMessage("Create a course first."); return; }
    const payload = { ...form, course_id: Number(selectedCourseId), timing_id: form.timing_id ? Number(form.timing_id) : null };
    setSaving(true);
    setMessage("");
    try {
      if (editing) await updateBatch(editing, payload);
      else await createBatch(payload);
      setForm(blank);
      setEditing(null);
      data.notify(editing ? "Batch updated." : "Batch created.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to save batch.");
    } finally {
      setSaving(false);
    }
  };
  const edit = batch => {
    setEditing(batch.id);
    setSelectedCourseId(batch.course_id);
    setForm({ batch_name: batch.batch_name || "", batch_level: batch.batch_level || "", timing_id: batch.timing_id || "", status: batch.status || "active" });
    scrollTo({ top: 0, behavior: "smooth" });
  };
  const remove = async () => {
    setDeleting(true);
    try {
      await deleteBatch(removing.id);
      data.notify("Batch deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete batch.");
    } finally {
      setDeleting(false);
      setRemoving(null);
    }
  };
  return <Page title="Batches" subtitle="Every batch belongs to one course.">
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <Card title={editing ? "Edit batch" : "New batch"} subtitle="The list below shows the batches of the selected course.">
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_150px_auto]" onSubmit={save}>
        <FormSelect label="Course" value={selectedCourseId} onChange={e => { setSelectedCourseId(e.target.value); setEditing(null); setForm(blank); }} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" />
        <FormInput label="Batch name" value={form.batch_name} onChange={e => setForm({ ...form, batch_name: e.target.value })} required />
        <FormInput label="Batch level" value={form.batch_level || ""} onChange={e => setForm({ ...form, batch_level: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <div className="flex items-end gap-2 md:col-span-2 xl:col-span-1">
          <Button icon={editing ? Save : Plus} loading={saving} disabled={!data.courses.length}>{editing ? "Save" : "Create"}</Button>
          {editing && <Button type="button" variant="outline" onClick={() => { setEditing(null); setForm(blank); }}>Cancel</Button>}
        </div>
      </form>
    </Card>
    <Card title={selectedCourseId ? `Batches in ${courseName(data.courses, selectedCourseId)}` : "Batches"} subtitle={`${courseBatches.length} batch${courseBatches.length === 1 ? "" : "es"}`}>
      <DataTable loading={data.loading} caption="Batches" columns={["Batch", "Course", "Level", "Status", "Actions"]} rows={courseBatches.map(batch => [
        <span className="font-semibold text-ink">{batch.batch_name}</span>,
        courseName(data.courses, batch.course_id),
        batch.batch_level || "-",
        <StatusBadge status={batch.status} />,
        <RowActions name={batch.batch_name} onEdit={() => edit(batch)} onDelete={() => setRemoving(batch)} />
      ])} empty={<EmptyState icon={Layers3} title={selectedCourseId ? "No batches under this course" : "Create a course first"} message={selectedCourseId ? "Add the first batch with the form above." : "Batches are always created under a course."} />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title="Delete this batch?" message={`"${removing?.batch_name}" will be removed. A batch that still has people or attendance cannot be deleted.`} onConfirm={remove} onCancel={() => setRemoving(null)} />
  </Page>;
}
