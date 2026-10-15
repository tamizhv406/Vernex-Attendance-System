import React, { useEffect, useReducer, useState } from "react";
import { BookOpen, Layers3, Plus, Save, Upload } from "lucide-react";
import { createBatch, createCourse, deleteBatch, deleteCourse, updateBatch, updateCourse } from "../lib/api";
import { BLANK_BATCH, BLANK_COURSE, batchErrors, batchPayload, courseErrors, coursePayload, editorReducer, formFromBatch, formFromCourse, startEditor, statusesOf } from "../lib/editForms";
import { courseName, statusOptions, titleCase } from "../lib/format";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, FormInput, FormSelect, Notice, Page, RowActions, Segmented, StatusBadge } from "../ui";
import { UploadDialog } from "../upload";

// Narrows a list to one status. It only appears when the list holds more than one, as it does after
// an upload (imported records are Pending), so an all-active list looks as it always did.
function StatusFilter({ rows, value, onChange }) {
  const statuses = statusesOf(rows);
  if (statuses.length < 2) return null;
  return <Segmented label="Status" value={statuses.includes(value) ? value : "all"} onChange={onChange} options={[
    { value: "all", label: "All", count: rows.length },
    ...statuses.map(status => ({ value: status, label: titleCase(status), count: rows.filter(row => (row.status || "active") === status).length }))
  ]} />;
}

function withStatus(rows, status) {
  return status === "all" || !statusesOf(rows).includes(status) ? rows : rows.filter(row => (row.status || "active") === status);
}

export function CoursesPage({ data }) {
  const [{ editing, form, errors }, dispatch] = useReducer(editorReducer, BLANK_COURSE, startEditor);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const change = field => event => dispatch({ type: "change", field, value: event.target.value });
  const clear = () => { dispatch({ type: "reset", form: BLANK_COURSE }); setMessage(""); };
  const save = async event => {
    event.preventDefault();
    if (saving) return;
    const problems = courseErrors(form);
    if (Object.keys(problems).length) { dispatch({ type: "errors", errors: problems }); return; }
    setSaving(true);
    setMessage("");
    try {
      if (editing) await updateCourse(editing, coursePayload(form));
      else await createCourse(coursePayload(form));
      dispatch({ type: "reset", form: BLANK_COURSE });
      data.notify(editing ? "Course updated." : "Course created.");
      await data.refresh();
    } catch (err) {
      if (err.status === 409) {
        // The code is taken: said under the code field, where it can be put right.
        dispatch({ type: "errors", errors: { course_code: err.message } });
      } else if (editing && err.status === 404) {
        // Deleted somewhere else while it was open here. There is nothing left to save to.
        dispatch({ type: "reset", form: BLANK_COURSE });
        setMessage("That course no longer exists. The list has been reloaded.");
        await data.refresh();
      } else {
        setMessage(err.message || "Unable to save course.");
      }
    } finally {
      setSaving(false);
    }
  };
  const edit = course => {
    dispatch({ type: "edit", id: course.id, form: formFromCourse(course) });
    setMessage("");
    scrollTo({ top: 0, behavior: "smooth" });
  };
  const remove = async () => {
    setDeleting(true);
    try {
      await deleteCourse(removing.id);
      // The form may be holding the very course that is now gone.
      if (editing === removing.id) dispatch({ type: "reset", form: BLANK_COURSE });
      data.notify("Course deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete course.");
    } finally {
      setDeleting(false);
      setRemoving(null);
    }
  };
  const rows = withStatus(data.courses, statusFilter);
  return <Page title="Courses" subtitle="Create a course before its batches and students." actions={<Button variant="outline" icon={Upload} onClick={() => setUploadOpen(true)}>Upload</Button>}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <Card title={editing ? "Edit course" : "New course"} subtitle={editing ? "Change the details and save." : "The code must be unique."}>
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[150px_1fr_1fr_150px_auto]" onSubmit={save} noValidate>
        {/* The key makes the field new for every record opened, so the cursor lands in it. */}
        <FormInput key={editing ?? "new"} autoFocus={Boolean(editing)} label="Course code" value={form.course_code} onChange={change("course_code")} error={errors.course_code} maxLength={40} required />
        <FormInput label="Course name" value={form.course_name} onChange={change("course_name")} error={errors.course_name} maxLength={120} required />
        <FormInput label="Description" value={form.description} onChange={change("description")} />
        <FormSelect label="Status" value={form.status} onChange={change("status")} options={statusOptions()} />
        <div className="flex items-end gap-2 md:col-span-2 xl:col-span-1">
          <Button icon={Save} loading={saving}>{editing ? "Save" : "Create"}</Button>
          {editing && <Button type="button" variant="outline" onClick={clear} disabled={saving}>Cancel</Button>}
        </div>
      </form>
    </Card>
    <Card title="All courses" subtitle={rows.length === data.courses.length ? `${data.courses.length} course${data.courses.length === 1 ? "" : "s"}` : `${rows.length} of ${data.courses.length} shown`}>
      <div className="mb-4 empty:hidden"><StatusFilter rows={data.courses} value={statusFilter} onChange={setStatusFilter} /></div>
      <DataTable loading={data.loading} caption="Courses" columns={["Course", "Code", "Description", "Batches", "Status", "Actions"]} rowKeys={rows.map(course => course.id)} rows={rows.map(course => [
        <span className="font-semibold text-ink">{course.course_name}</span>,
        course.course_code,
        course.description || "-",
        data.batches.filter(batch => Number(batch.course_id) === Number(course.id)).length,
        <StatusBadge status={course.status} />,
        <RowActions name={course.course_name} onEdit={() => edit(course)} onDelete={() => setRemoving(course)} />
      ])} empty={<EmptyState icon={BookOpen} title="No courses yet" message="Create the first course with the form above, or upload a spreadsheet." />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title="Delete this course?" message={`"${removing?.course_name}" will be removed. A course that still has batches, people or attendance cannot be deleted.`} onConfirm={remove} onCancel={() => setRemoving(null)} />
    <UploadDialog kind="courses" open={uploadOpen} onClose={() => setUploadOpen(false)} onImported={data.refresh} notify={data.notify} />
  </Page>;
}

export function BatchesPage({ data }) {
  const firstCourseId = data.courses[0]?.id ?? "";
  const [{ editing, original, form, errors }, dispatch] = useReducer(editorReducer, BLANK_BATCH, startEditor);
  // Which batches the list shows. This is the list's own choice: the form's Course field decides
  // where a batch belongs and nothing else, so changing it can never end an edit.
  const [courseFilter, setCourseFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const change = field => event => dispatch({ type: "change", field, value: event.target.value });
  const blankFor = courseId => ({ ...BLANK_BATCH, course_id: String(courseId ?? "") });
  // A new batch needs a course to go under; until one is picked, the first is offered.
  useEffect(() => {
    if (!editing && !form.course_id && firstCourseId) dispatch({ type: "change", field: "course_id", value: String(firstCourseId) });
  }, [editing, form.course_id, firstCourseId]);
  // A course that was deleted cannot stay selected as the list's filter.
  useEffect(() => {
    if (courseFilter && !data.loading && !data.courses.some(course => Number(course.id) === Number(courseFilter))) setCourseFilter("");
  }, [courseFilter, data.courses, data.loading]);

  const inCourse = data.batches.filter(batch => !courseFilter || Number(batch.course_id) === Number(courseFilter));
  const rows = withStatus(inCourse, statusFilter);
  const moving = Boolean(editing && original && form.course_id !== original.course_id);
  const members = editing ? data.people.filter(person => Number(person.batch_id) === Number(editing)).length : 0;

  const save = async event => {
    event.preventDefault();
    if (saving) return;
    if (!data.courses.length) { setMessage("Create a course first."); return; }
    const problems = batchErrors(form);
    if (Object.keys(problems).length) { dispatch({ type: "errors", errors: problems }); return; }
    const payload = batchPayload(form);
    setSaving(true);
    setMessage("");
    try {
      const saved = editing ? await updateBatch(editing, payload) : await createBatch(payload);
      // The next batch is most likely for the same course, as before.
      dispatch({ type: "reset", form: blankFor(payload.course_id) });
      const moved = Number(saved?.people_moved) || 0;
      data.notify(!editing ? "Batch created." : moved ? `Batch updated. ${moved} ${moved === 1 ? "person" : "people"} moved with it.` : "Batch updated.");
      // If the list is narrowed to another course, follow the batch so that it stays in view.
      if (courseFilter && Number(courseFilter) !== payload.course_id) setCourseFilter(String(payload.course_id));
      await data.refresh();
    } catch (err) {
      if (err.status === 409) {
        dispatch({ type: "errors", errors: { batch_name: err.message } });
      } else if (err.status === 404 && /course/i.test(err.message)) {
        dispatch({ type: "errors", errors: { course_id: "This course no longer exists. Select another." } });
        await data.refresh();
      } else if (editing && err.status === 404) {
        dispatch({ type: "reset", form: blankFor(firstCourseId) });
        setMessage("That batch no longer exists. The list has been reloaded.");
        await data.refresh();
      } else {
        setMessage(err.message || "Unable to save batch.");
      }
    } finally {
      setSaving(false);
    }
  };
  const edit = batch => {
    dispatch({ type: "edit", id: batch.id, form: formFromBatch(batch) });
    setMessage("");
    scrollTo({ top: 0, behavior: "smooth" });
  };
  // Cancel leaves the form empty and ready for a new batch in the course the batch was in.
  const cancel = () => { dispatch({ type: "reset", form: blankFor(original?.course_id || firstCourseId) }); setMessage(""); };
  const remove = async () => {
    setDeleting(true);
    try {
      await deleteBatch(removing.id);
      if (editing === removing.id) dispatch({ type: "reset", form: blankFor(removing.course_id) });
      data.notify("Batch deleted.");
      await data.refresh();
    } catch (err) {
      setMessage(err.message || "Unable to delete batch.");
    } finally {
      setDeleting(false);
      setRemoving(null);
    }
  };
  const filtered = Boolean(courseFilter) || rows.length !== inCourse.length;
  return <Page title="Batches" subtitle="Every batch belongs to one course." actions={<Button variant="outline" icon={Upload} onClick={() => setUploadOpen(true)}>Upload</Button>}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    <Card title={editing ? "Edit batch" : "New batch"} subtitle={editing ? "Change the details, or move the batch to another course, and save." : "Choose the course the batch belongs to."}>
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_150px_auto]" onSubmit={save} noValidate>
        <FormSelect label="Course" value={form.course_id} onChange={change("course_id")} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" error={errors.course_id} hint={moving && members > 0 ? `${members} ${members === 1 ? "person" : "people"} in this batch will move to this course with it.` : undefined} required />
        <FormInput key={editing ?? "new"} autoFocus={Boolean(editing)} label="Batch name" value={form.batch_name} onChange={change("batch_name")} error={errors.batch_name} maxLength={120} required />
        <FormInput label="Batch level" value={form.batch_level} onChange={change("batch_level")} maxLength={120} />
        <FormSelect label="Status" value={form.status} onChange={change("status")} options={statusOptions()} />
        <div className="flex items-end gap-2 md:col-span-2 xl:col-span-1">
          <Button icon={editing ? Save : Plus} loading={saving} disabled={!data.courses.length}>{editing ? "Save" : "Create"}</Button>
          {editing && <Button type="button" variant="outline" onClick={cancel} disabled={saving}>Cancel</Button>}
        </div>
      </form>
    </Card>
    <Card title={courseFilter ? `Batches in ${courseName(data.courses, courseFilter)}` : "All batches"} subtitle={filtered ? `${rows.length} of ${data.batches.length} shown` : `${data.batches.length} batch${data.batches.length === 1 ? "" : "es"}`}>
      {data.courses.length > 0 && <div className="mb-4 grid gap-3 lg:grid-cols-[260px_minmax(0,1fr)] lg:items-end">
        <FormSelect label="Show" value={courseFilter} onChange={e => setCourseFilter(e.target.value)} options={[{ value: "", label: "All courses" }, ...data.courses.map(course => ({ value: course.id, label: course.course_name }))]} />
        <div className="lg:justify-self-end"><StatusFilter rows={inCourse} value={statusFilter} onChange={setStatusFilter} /></div>
      </div>}
      <DataTable loading={data.loading} caption="Batches" columns={["Batch", "Course", "Level", "Status", "Actions"]} rowKeys={rows.map(batch => batch.id)} rows={rows.map(batch => [
        <span className="font-semibold text-ink">{batch.batch_name}</span>,
        courseName(data.courses, batch.course_id),
        batch.batch_level || "-",
        <StatusBadge status={batch.status} />,
        <RowActions name={batch.batch_name} onEdit={() => edit(batch)} onDelete={() => setRemoving(batch)} />
      ])} empty={!data.courses.length ? <EmptyState icon={Layers3} title="Create a course first" message="Batches are always created under a course." /> : courseFilter ? <EmptyState icon={Layers3} title="No batches under this course" message="Add the first batch with the form above." action={<Button variant="outline" size="sm" onClick={() => setCourseFilter("")}>Show all courses</Button>} /> : <EmptyState icon={Layers3} title="No batches yet" message="Add the first batch with the form above, or upload a spreadsheet." />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title="Delete this batch?" message={`"${removing?.batch_name}" will be removed. A batch that still has people or attendance cannot be deleted.`} onConfirm={remove} onCancel={() => setRemoving(null)} />
    <UploadDialog kind="batches" open={uploadOpen} onClose={() => setUploadOpen(false)} onImported={data.refresh} notify={data.notify} />
  </Page>;
}
