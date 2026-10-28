import React, { useEffect, useMemo, useState } from "react";
import { Plus, Printer, QrCode, Upload, UserPlus, Users, X } from "lucide-react";
import { createPerson, deletePerson } from "../lib/api";
import { faceEnrolled, statusOptions, toPersonPayload } from "../lib/format";
import { checkPhone } from "../lib/phone";
import { SLOW_PRINT, formatCode, printablePeople } from "../lib/qr";
import { PERSON_CONFIG } from "../routes";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, FormInput, FormSelect, FormTextarea, Identity, Notice, Page, RowActions, SearchInput, Segmented, StatusBadge } from "../ui";
import { UploadDialog } from "../upload";
import { QrCardDialog, usePrintCards } from "./qrCards";

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
  // What is wrong with a field, shown under it: { person_code, phone }.
  const [errors, setErrors] = useState({});
  const [adding, setAdding] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [courseFilter, setCourseFilter] = useState("");
  const [faceFilter, setFaceFilter] = useState("all");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(null);
  const [deleting, setDeleting] = useState(false);
  // The person whose QR card is open (their id, so the card follows data.refresh()).
  const [qrFor, setQrFor] = useState(null);
  // A print of more than SLOW_PRINT cards, waiting to be confirmed.
  const [bigPrint, setBigPrint] = useState(null);
  const cards = usePrintCards();
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
  useEffect(() => { setForm(blank); setErrors({}); setAdding(false); setUploadOpen(false); setQuery(""); setCourseFilter(""); setFaceFilter("all"); setMessage(""); setQrFor(null); }, [page]);
  const closeForm = () => { setAdding(false); setForm(blank); setErrors({}); };
  // Typing in a field takes back what was said about it; the number is judged again on leaving the field.
  const setField = (field, value) => { setForm(current => ({ ...current, [field]: value })); setErrors(({ [field]: _fixed, ...rest }) => rest); };
  const phoneLabel = isStudent ? "Parent contact" : "Contact number";
  const checkPhoneField = () => {
    const checked = checkPhone(form.phone);
    setErrors(({ phone: _old, ...rest }) => (checked.error ? { ...rest, phone: checked.error } : rest));
    return checked;
  };
  const save = async event => {
    event.preventDefault();
    if (saving) return;
    if (isStudent && (!form.course_id || !form.batch_id)) {
      setMessage("Student must select an existing course and batch.");
      return;
    }
    // The same rules the backend applies. What is sent is the ten digits, however they were typed.
    const phone = checkPhoneField();
    if (phone.error) return;
    setSaving(true);
    setMessage("");
    try {
      await createPerson(toPersonPayload({ ...form, phone: phone.value }, config.apiType));
      closeForm();
      data.notify(`${config.singular} created.`);
      await data.refresh();
    } catch (err) {
      // A refusal about one field is said under that field; anything else at the top of the page.
      const aboutPhone = err.status === 400 && String(err.message).startsWith(`${phoneLabel}: `);
      if (err.status === 409) setErrors(current => ({ ...current, person_code: `This ${config.singular.toLowerCase()} ID is already in use. Every student, staff member and member needs a different ID.` }));
      else if (aboutPhone) setErrors(current => ({ ...current, phone: err.message.slice(phoneLabel.length + 2) }));
      else setMessage(err.message || `Unable to create ${config.singular.toLowerCase()}.`);
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
  // The cards of the list as it is filtered now: search, course and face filters all count.
  const printable = printablePeople(rows);
  const printCards = () => {
    if (printable.length > SLOW_PRINT) setBigPrint(printable);
    else cards.print(printable);
  };
  const qrPerson = qrFor === null ? null : data.people.find(person => Number(person.id) === Number(qrFor)) || null;
  return <Page title={config.title} subtitle={isStudent ? "Students are assigned to an existing course and batch." : `${config.title} can be assigned to a course and batch.`} actions={<>
    <Button variant="outline" icon={Printer} disabled={!printable.length} onClick={printCards} title={printable.length ? undefined : "No one in this list has an attendance code yet"}>Print QR cards ({printable.length})</Button>
    <Button variant="outline" icon={Upload} onClick={() => setUploadOpen(true)}>Upload</Button>
    <Button variant={adding ? "outline" : "primary"} icon={adding ? X : UserPlus} onClick={() => setAdding(current => !current)} aria-expanded={adding}>{adding ? "Close form" : `Add ${config.singular.toLowerCase()}`}</Button>
  </>}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    {adding && <Card title={`New ${config.singular.toLowerCase()}`} subtitle="Fields marked * are required." className="animate-fade-up">
      <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" onSubmit={save}>
        <FormInput label={`${config.singular} ID`} value={form.person_code} onChange={e => setField("person_code", e.target.value)} error={errors.person_code} maxLength={80} required autoFocus />
        <FormInput label="Full name" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })} maxLength={160} required />
        {isStudent && <FormInput label="Parent name" value={form.guardian_name} onChange={e => setForm({ ...form, guardian_name: e.target.value })} />}
        <FormInput label={phoneLabel} type="tel" inputMode="tel" autoComplete="off" maxLength={20} hint="10 digits. Spaces, hyphens and +91 in front are accepted." value={form.phone} onChange={e => setField("phone", e.target.value)} onBlur={() => { if (form.phone.trim()) checkPhoneField(); }} error={errors.phone} required />
        {!isStudent && <FormInput label="Email" type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />}
        <FormSelect label="Course" value={form.course_id} onChange={e => setForm({ ...form, course_id: e.target.value, batch_id: "" })} options={data.courses.map(course => ({ value: course.id, label: course.course_name }))} empty="Create a course first" required={isStudent} />
        <FormSelect label="Batch" value={form.batch_id} onChange={e => setForm({ ...form, batch_id: e.target.value })} options={availableBatches.map(batch => ({ value: batch.id, label: batch.batch_name }))} empty={form.course_id ? "Create a batch under this course" : "Select course first"} required={isStudent} />
        <FormInput label="Level / class" value={form.level_class} onChange={e => setForm({ ...form, level_class: e.target.value })} />
        <FormInput label="Joining date" type="date" value={form.joining_date} onChange={e => setForm({ ...form, joining_date: e.target.value })} />
        <FormSelect label="Status" value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} options={statusOptions()} />
        <FormSelect label="Face enrollment status" value={form.face_enrollment_status} onChange={e => setForm({ ...form, face_enrollment_status: e.target.value })} options={[{ value: "not_started", label: "Pending" }, { value: "completed", label: "Completed" }]} />
        <FormTextarea label="Notes" className="md:col-span-2 xl:col-span-3" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Optional notes" />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end md:col-span-2 xl:col-span-3">
          <Button type="button" variant="outline" onClick={closeForm}>Cancel</Button>
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
      <DataTable loading={data.loading} caption={config.title} columns={[config.singular, "Contact", "Course", "Batch", "Status", "Face", "Actions"]} rowKeys={rows.map(person => person.id)} rows={rows.map(person => [
        <Identity name={person.full_name} detail={person.attendance_code ? `${person.person_code} · ${formatCode(person.attendance_code)}` : person.person_code} />,
        person.guardian_phone || person.phone || "-",
        person.course_name || "-",
        person.batch_name || "-",
        <StatusBadge status={person.status} />,
        <StatusBadge status={faceEnrolled(person) ? "Enrolled" : "Pending"} />,
        <RowActions name={person.full_name} extra={[{ icon: QrCode, label: `QR card of ${person.full_name}`, onClick: () => setQrFor(person.id) }]} onDelete={() => setRemoving(person)} />
      ])} empty={filtered ? <EmptyState icon={Users} title={`No ${config.title.toLowerCase()} match`} message="Try another search or clear the filters." action={<Button variant="outline" size="sm" onClick={() => { setQuery(""); setCourseFilter(""); setFaceFilter("all"); }}>Clear filters</Button>} /> : <EmptyState icon={Users} title={`No ${config.title.toLowerCase()} yet`} message={isStudent && !data.courses.length ? "Create a course and a batch first, then add students." : `Add the first ${config.singular.toLowerCase()} to get started.`} action={<Button size="sm" icon={UserPlus} onClick={() => setAdding(true)}>Add {config.singular.toLowerCase()}</Button>} />} />
    </Card>
    <ConfirmDialog open={Boolean(removing)} busy={deleting} title={`Delete ${removing?.full_name || "this person"}?`} message="This removes the person and their enrolled face data. It cannot be undone." onConfirm={remove} onCancel={() => setRemoving(null)} />
    <QrCardDialog person={qrPerson} onClose={() => setQrFor(null)} onChanged={data.refresh} notify={data.notify} />
    <ConfirmDialog open={Boolean(bigPrint)} title={`Print ${bigPrint?.length || 0} QR cards?`} message={`That is ${Math.ceil((bigPrint?.length || 0) / 10)} A4 pages. Printing this many may be slow; filtering the list by course or batch prints fewer.`} confirmLabel="Print" onConfirm={() => { cards.print(bigPrint); setBigPrint(null); }} onCancel={() => setBigPrint(null)} />
    {cards.sheet}
    <UploadDialog kind={page} open={uploadOpen} onClose={() => setUploadOpen(false)} onImported={data.refresh} notify={data.notify} />
  </Page>;
}
