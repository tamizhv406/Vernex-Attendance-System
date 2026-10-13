// Bulk upload from a spreadsheet: one dialog, used by Courses, Batches, Students, Staff and Members.
import React, { useEffect, useId, useRef, useState } from "react";
import { Download, FileSpreadsheet, Upload, X } from "lucide-react";
import { downloadFile, uploadImport } from "./lib/api";
import { IMPORTS, MAX_IMPORT_BYTES, MAX_IMPORT_ROWS, MAX_SHOWN_PROBLEMS, checkImportFile, describeUploadError, formatBytes, importOutcome, readImportResult, skippedRowsCsv, unusedColumns } from "./lib/imports";
import { Button, DataTable, Info, Notice, overScreen } from "./ui";

// Hands a file made or fetched in the browser to the person, under the given name.
function saveFile(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ColumnList({ label, names }) {
  return <div className="rounded-2xl bg-canvas/70 px-4 py-3">
    <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</dt>
    <dd className="mt-2 flex flex-wrap gap-1.5">
      {names.map(name => <code key={name} className="rounded-lg bg-white px-2 py-1 font-mono text-xs font-semibold text-ink ring-1 ring-inset ring-line">{name}</code>)}
      {!names.length && <span className="text-xs text-ink-muted">None</span>}
    </dd>
  </div>;
}

// kind: a key of IMPORTS. onImported reloads the page's data; notify is the app's toast.
// Escape and the backdrop close it, except while a file is on its way.
export function UploadDialog({ kind, open, onClose, onImported, notify }) {
  const spec = IMPORTS[kind];
  const titleId = useId();
  const closeRef = useRef(null);
  const inputRef = useRef(null);
  // Set the moment a file is sent, before the screen has redrawn: a second click cannot send it twice.
  const sending = useRef(false);
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [failure, setFailure] = useState("");
  const [fetchingTemplate, setFetchingTemplate] = useState(false);

  // Every opening starts clean: no file, no result from the time before.
  useEffect(() => {
    if (!open) return;
    setFile(null);
    setFileError("");
    setResult(null);
    setFailure("");
  }, [open, kind]);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const onKey = event => { if (event.key === "Escape" && !sending.current) onClose(); };
    addEventListener("keydown", onKey);
    return () => { removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [open]);
  if (!open || !spec) return null;

  const choose = event => {
    const picked = event.target.files?.[0] || null;
    // Cleared so that the same file, corrected and saved again, can be picked a second time.
    event.target.value = "";
    if (!picked) return;
    setFile(picked);
    setFileError(checkImportFile(picked));
    setResult(null);
    setFailure("");
  };

  const send = async () => {
    if (sending.current || !file || fileError) return;
    sending.current = true;
    setUploading(true);
    setFailure("");
    try {
      const summary = readImportResult(await uploadImport(spec.path, file));
      if (!summary) {
        // The request went through but the answer says nothing usable. Rows may have been saved,
        // so the page is reloaded to show what is really there, and nothing is claimed either way.
        await onImported();
        setFailure("The server answered in a way this page does not understand, so it cannot say what was imported. The list behind this window has been reloaded: check it before uploading the file again.");
        notify("The upload could not be confirmed.", "danger");
        return;
      }
      setResult(summary);
      const outcome = importOutcome(summary, spec.noun);
      notify(outcome.message, outcome.tone);
      if (summary.imported > 0) await onImported();
    } catch (error) {
      setFailure(describeUploadError(error));
      notify("The upload did not go through.", "danger");
    } finally {
      sending.current = false;
      setUploading(false);
    }
  };

  const getTemplate = async () => {
    if (fetchingTemplate) return;
    setFetchingTemplate(true);
    setFailure("");
    try {
      saveFile(await downloadFile(spec.templatePath), `${spec.key}_import_template.xlsx`);
    } catch (error) {
      setFailure(`The template could not be downloaded. ${describeUploadError(error)}`);
    } finally {
      setFetchingTemplate(false);
    }
  };

  const getSkippedRows = () => saveFile(new Blob([skippedRowsCsv(result)], { type: "text/csv;charset=utf-8" }), `${spec.key}_skipped_rows.csv`);
  const startOver = () => { setFile(null); setFileError(""); setResult(null); setFailure(""); };
  const close = () => { if (!sending.current) onClose(); };

  const outcome = result && importOutcome(result, spec.noun);
  const unused = result ? unusedColumns(result) : [];
  const shown = result ? result.errors.slice(0, MAX_SHOWN_PROBLEMS) : [];

  return overScreen(<div className="fixed inset-0 z-50 grid place-items-end p-3 sm:place-items-center">
    <button type="button" className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm" onClick={close} aria-label="Close" tabIndex={-1} />
    <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex max-h-[90vh] w-full max-w-2xl animate-sheet-up flex-col overflow-hidden rounded-4xl bg-white shadow-float">
      <div className="flex items-start justify-between gap-3 px-5 pt-5 sm:px-6 sm:pt-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand-50 text-brand-700"><FileSpreadsheet size={20} aria-hidden="true" /></div>
          <div className="min-w-0">
            <h3 id={titleId} className="text-lg font-bold tracking-tight text-ink">{spec.title}</h3>
            <p className="text-sm text-ink-muted">An Excel (.xlsx) or CSV file, up to {MAX_IMPORT_ROWS.toLocaleString()} rows and {formatBytes(MAX_IMPORT_BYTES)}.</p>
          </div>
        </div>
        <button ref={closeRef} type="button" className="icon-btn" onClick={close} disabled={uploading} aria-label="Close"><X size={17} aria-hidden="true" /></button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5 sm:px-6">
        <section aria-label="Columns in the file">
          <dl className="grid gap-3 sm:grid-cols-2">
            <ColumnList label="Required columns" names={spec.required} />
            <ColumnList label="Optional columns" names={spec.optional} />
          </dl>
          <ul className="mt-3 grid gap-1 text-xs text-ink-muted">
            <li>The first row of the file holds these column names. Rows with a problem are skipped and listed here; the other rows are still imported.</li>
            {spec.notes.map(note => <li key={note}>{note}</li>)}
          </ul>
          <Button type="button" variant="outline" size="sm" icon={Download} loading={fetchingTemplate} onClick={getTemplate} className="mt-3">Download template</Button>
        </section>

        <section aria-label="File to upload">
          <input ref={inputRef} type="file" accept=".xlsx,.csv" className="sr-only" onChange={choose} tabIndex={-1} aria-label="Spreadsheet file" />
          <div className={`flex flex-col gap-3 rounded-3xl border border-dashed px-4 py-4 sm:flex-row sm:items-center sm:justify-between ${fileError ? "border-red-300 bg-red-50/60" : "border-slate-300/80 bg-canvas/60"}`}>
            <div className="min-w-0">
              <p className="break-all text-sm font-semibold text-ink">{file ? file.name : "No file chosen"}</p>
              <p className={`text-xs ${fileError ? "font-medium text-red-600" : "text-ink-muted"}`} role={fileError ? "alert" : undefined}>{fileError || (file ? formatBytes(file.size) : "Excel (.xlsx) or CSV (.csv)")}</p>
            </div>
            <Button type="button" variant="outline" size="sm" icon={FileSpreadsheet} onClick={() => inputRef.current?.click()} disabled={uploading}>{file ? "Choose another file" : "Choose file"}</Button>
          </div>
        </section>

        {failure && <Notice tone="danger" onClose={() => setFailure("")}>{failure}</Notice>}

        {result && <section aria-label="Result of the upload" className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Info label="Rows in file" value={String(result.total)} />
            <Info label="Imported" value={String(result.imported)} />
            <Info label="Skipped" value={String(result.skipped)} />
          </div>
          <Notice tone={outcome.tone}>{outcome.message}</Notice>
          {unused.length > 0 && <Notice tone="info">Not read: {unused.join(", ")}. Only the columns listed above are used.</Notice>}
          {result.errors.length > 0 && <>
            <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:items-center sm:justify-between">
              <h4 className="text-sm font-bold text-ink">Skipped rows</h4>
              <Button type="button" variant="outline" size="sm" icon={Download} onClick={getSkippedRows}>Download skipped rows (CSV)</Button>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-2xl">
              <DataTable caption="Rows that were not imported" columns={["Row", "Column", "Value", "Problem"]} rows={shown.map(error => [
                <span className="whitespace-nowrap font-semibold text-ink">Row {error.row}</span>,
                error.column ? <code className="font-mono text-xs">{error.column}</code> : "Whole row",
                error.value ? <span className="break-all">{error.value}</span> : <span className="text-ink-muted">(empty)</span>,
                error.message
              ])} />
            </div>
            {result.errors.length > shown.length && <p className="text-xs text-ink-muted">The first {shown.length} of {result.errors.length} problems are listed. The CSV holds all of them.</p>}
          </>}
        </section>}
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-line px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
        {result ? <>
          <Button type="button" variant="outline" onClick={startOver}>Upload another file</Button>
          <Button type="button" onClick={close}>Done</Button>
        </> : <>
          <Button type="button" variant="outline" onClick={close} disabled={uploading}>Cancel</Button>
          <Button type="button" icon={Upload} loading={uploading} disabled={!file || Boolean(fileError)} onClick={send}>{uploading ? "Uploading" : "Upload"}</Button>
        </>}
      </div>
    </div>
  </div>);
}
