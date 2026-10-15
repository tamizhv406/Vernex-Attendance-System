// "Report a problem" (IR-02): a dialog over whatever page someone is on, for admins and super admins
// alike. The page's path and a short description of the device go with the report; both are shown
// before it is sent. Who reported it is not sent at all: the backend takes that from the login.
import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { CheckCircle2, Flag, LifeBuoy, Send } from "lucide-react";
import { reportIssue } from "../lib/api";
import { UNREACHABLE } from "../lib/auth";
import {
  BLANK_REPORT, CATEGORY_OPTIONS, LIMITS, SEVERITY_OPTIONS, characters, cleanLine, cleanText, deviceInfo, deviceText, fieldErrors, pagePath, reportErrors, reportPayload
} from "../lib/issues";
import { Button, FormInput, FormSelect, FormTextarea, Notice, overScreen } from "../ui";

const FIELDS = ["title", "category", "severity", "description"];
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])";

// Tab and Shift+Tab go round inside the dialog instead of out to the page behind it.
function keepFocusIn(event, container) {
  const items = container ? [...container.querySelectorAll(FOCUSABLE)] : [];
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

// onClose(): the dialog is closed. onReported(issue): a report was saved. onOpenReport(id): go and see it.
export default function ReportProblem({ onClose, onReported, onOpenReport }) {
  const [form, setForm] = useState(BLANK_REPORT);
  const [errors, setErrors] = useState({});
  const [failure, setFailure] = useState("");
  const [sending, setSending] = useState(false);
  const [reported, setReported] = useState(null);
  const base = useId();
  const idOf = field => `${base}-${field}`;
  const dialogRef = useRef(null);
  // Focus goes back where it was (the button that opened this) when the dialog closes.
  const opener = useRef(document.activeElement);
  // Worked out once, when the dialog opens: the page it was opened on, and the device.
  const attached = useMemo(() => ({ page: pagePath(location.pathname), device: deviceInfo(navigator, screen) }), []);

  const close = () => {
    onClose();
    if (opener.current?.isConnected) opener.current.focus();
  };
  useEffect(() => {
    const onKey = event => {
      if (event.key === "Escape" && !sending) { event.preventDefault(); close(); }
      if (event.key === "Tab") keepFocusIn(event, dialogRef.current);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [sending]);

  const set = field => event => {
    const value = event.target.value;
    setForm(current => ({ ...current, [field]: value }));
    if (errors[field]) setErrors(current => ({ ...current, [field]: undefined }));
  };
  const focusFirst = found => {
    const field = FIELDS.find(name => found[name]);
    if (field) document.getElementById(idOf(field))?.focus();
  };
  const submit = async event => {
    event.preventDefault();
    const found = reportErrors(form);
    setErrors(found);
    setFailure("");
    if (Object.keys(found).length) { focusFirst(found); return; }
    setSending(true);
    try {
      const issue = await reportIssue(reportPayload(form, attached));
      setReported(issue);
      onReported?.(issue);
    } catch (error) {
      const named = fieldErrors(error, FIELDS);
      if (Object.keys(named).length) { setErrors(named); focusFirst(named); }
      else setFailure(error.status ? error.message : UNREACHABLE);
    } finally {
      setSending(false);
    }
  };

  const titleCount = characters(cleanLine(form.title));
  const descriptionCount = characters(cleanText(form.description));
  return overScreen(<div className="fixed inset-0 z-50 grid place-items-end p-3 sm:place-items-center">
    <button type="button" tabIndex={-1} aria-label="Close" className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm" onClick={() => { if (!sending) close(); }} />
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={idOf("heading")} aria-describedby={idOf("about")}
      className="relative max-h-[calc(100dvh-1.5rem)] w-full max-w-xl animate-sheet-up overflow-y-auto rounded-4xl bg-white p-5 shadow-float sm:p-6">
      {reported ? <div>
        <div className="grid h-11 w-11 place-items-center rounded-2xl bg-emerald-50 text-emerald-700"><CheckCircle2 size={20} aria-hidden="true" /></div>
        <h2 id={idOf("heading")} className="mt-4 text-lg font-bold tracking-tight text-ink">Problem reported</h2>
        <p id={idOf("about")} role="status" className="mt-1 text-sm text-ink-muted">Issue #{reported.id} is open. A super admin will look at it; its status and any answer appear in My reports.</p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={close}>Done</Button>
          <Button type="button" icon={LifeBuoy} autoFocus onClick={() => onOpenReport(reported.id)}>Open My reports</Button>
        </div>
      </div> : <>
        <div className="flex items-start gap-3">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand-50 text-brand-700"><Flag size={20} aria-hidden="true" /></div>
          <div className="min-w-0">
            <h2 id={idOf("heading")} className="text-lg font-bold tracking-tight text-ink">Report a problem</h2>
            <p id={idOf("about")} className="mt-0.5 text-sm text-ink-muted">It goes to the super admins. You can follow it, and answer them, in My reports.</p>
          </div>
        </div>
        <form className="mt-5 grid gap-4" onSubmit={submit} noValidate>
          <FormInput id={idOf("title")} autoFocus required label="Title" value={form.title} onChange={set("title")} error={errors.title} autoComplete="off"
            hint={`${titleCount}/${LIMITS.title[1]} characters, at least ${LIMITS.title[0]}`} />
          <div className="grid gap-4 sm:grid-cols-2">
            <FormSelect id={idOf("category")} required label="Category" value={form.category} onChange={set("category")} options={CATEGORY_OPTIONS} error={errors.category} />
            <FormSelect id={idOf("severity")} required label="Severity" value={form.severity} onChange={set("severity")} options={SEVERITY_OPTIONS} error={errors.severity} />
          </div>
          <FormTextarea id={idOf("description")} required label="What happened" rows={6} value={form.description} onChange={set("description")} error={errors.description}
            hint={`${descriptionCount}/${LIMITS.description[1]} characters, at least ${LIMITS.description[0]}. What you did, and what you expected.`} />
          <div className="rounded-2xl bg-canvas/70 px-4 py-3 text-sm">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">Sent with it</p>
            <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="font-medium text-ink-muted">Page</dt>
              <dd className="min-w-0 break-all font-mono text-[13px] text-ink">{attached.page || "Not recorded"}</dd>
              <dt className="font-medium text-ink-muted">Device</dt>
              <dd className="min-w-0 break-words text-ink">{deviceText(attached.device)}</dd>
            </dl>
          </div>
          {failure && <Notice tone="danger">{failure}</Notice>}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={close} disabled={sending}>Cancel</Button>
            <Button icon={Send} loading={sending}>Send report</Button>
          </div>
        </form>
      </>}
    </div>
  </div>);
}
