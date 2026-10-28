// QR cards: one person's card in a dialog (view, download, print, replace the code), and the print
// sheet of many, ID-card size, 10 to an A4 page. Printing goes through the browser's own dialog
// ("Save as PDF" works); styles.css shows only the sheet on paper. What a QR holds is lib/qr.js's.
import React, { useEffect, useId, useRef, useState } from "react";
import { Download, Printer, QrCode, RefreshCw, X } from "lucide-react";
import { regenerateAttendanceCode } from "../lib/api";
import { cardFileName, cardLines, formatCode, pagesOf, printablePeople, qrMatrix, typeLabel } from "../lib/qr";
import { Button, ConfirmDialog, Identity, Notice, overScreen } from "../ui";

// The QR as an SVG, one unit per module, drawn at once from the code.
export function QrImage({ code, label, className = "" }) {
  const matrix = qrMatrix(code);
  if (!matrix) return null;
  return <svg viewBox={`0 0 ${matrix.size} ${matrix.size}`} className={className} role="img" aria-label={label} shapeRendering="crispEdges">
    <rect width={matrix.size} height={matrix.size} fill="#fff" />
    <path d={matrix.path} fill="#000" />
  </svg>;
}

// A PNG of the card's QR with the code and name under it, saved as <person ID>-qr.png.
function downloadPng(person) {
  const matrix = qrMatrix(person.attendance_code);
  if (!matrix) return false;
  const scale = 12;
  const side = matrix.size * scale;
  const canvas = document.createElement("canvas");
  canvas.width = side;
  canvas.height = side + 110;
  const context = canvas.getContext("2d");
  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#000";
  for (const [row, column] of matrix.dark) context.fillRect(column * scale, row * scale, scale, scale);
  context.textAlign = "center";
  context.font = "bold 44px ui-monospace, Menlo, Consolas, monospace";
  context.fillText(formatCode(person.attendance_code), side / 2, side + 40);
  context.font = "28px system-ui, sans-serif";
  context.fillText(`${person.full_name} · ${person.person_code}`.slice(0, 48), side / 2, side + 88);
  const link = document.createElement("a");
  link.download = cardFileName(person);
  link.href = canvas.toDataURL("image/png");
  link.click();
  return true;
}

// Prints a set of cards: they are put into the print-only sheet, the browser's print dialog opens,
// and the sheet is emptied again once it closes.
export function usePrintCards() {
  const [cards, setCards] = useState(null);
  useEffect(() => {
    if (!cards) return;
    const done = () => setCards(null);
    addEventListener("afterprint", done);
    // One frame for the sheet to be on the page before the print dialog takes its picture of it.
    const frame = requestAnimationFrame(() => window.print());
    return () => { cancelAnimationFrame(frame); removeEventListener("afterprint", done); };
  }, [cards]);
  return { print: people => setCards(printablePeople(people)), sheet: cards ? overScreen(<QrCardSheet people={cards} />) : null };
}

export function QrCardSheet({ people }) {
  return <div className="qr-print" aria-hidden="true">
    {pagesOf(people).map((page, index) => <div key={index} className="qr-page">
      {page.map(person => <QrCard key={person.id} person={person} />)}
    </div>)}
  </div>;
}

function QrCard({ person }) {
  const place = [person.course_name, person.batch_name].filter(Boolean).join(" · ");
  return <div className="qr-card">
    <div className="qr-card-text">
      <p className="qr-card-brand">Vernex</p>
      <p className="qr-card-name">{person.full_name}</p>
      <p>{person.person_code}</p>
      <p>{typeLabel(person.person_type)}</p>
      {place && <p>{place}</p>}
    </div>
    <div className="qr-card-code">
      <QrImage code={person.attendance_code} label="" className="qr-card-qr" />
      <p>{formatCode(person.attendance_code)}</p>
    </div>
  </div>;
}

// One person's card. person: as data.people has them; onChanged(person) after a new code was saved.
export function QrCardDialog({ person, onClose, onChanged, notify }) {
  const titleId = useId();
  const closeRef = useRef(null);
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The person as the backend last answered, so a new code shows at once, before the list reloads.
  const [current, setCurrent] = useState(person);
  const cards = usePrintCards();
  useEffect(() => { setCurrent(person); setError(""); }, [person?.id]);
  useEffect(() => {
    if (!person) return;
    const previous = document.activeElement;
    closeRef.current?.focus();
    const onKey = event => { if (event.key === "Escape" && !busy && !replacing) onClose(); };
    addEventListener("keydown", onKey);
    return () => { removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [person?.id, busy, replacing]);
  if (!person || !current) return null;
  const code = current.attendance_code;
  const hasCode = Boolean(qrMatrix(code));
  const renew = async () => {
    setBusy(true);
    setError("");
    try {
      const updated = await regenerateAttendanceCode(current.id);
      setCurrent(previous => ({ ...previous, ...updated }));
      setReplacing(false);
      // Said only once the backend has saved the new code.
      notify(code ? `New attendance code for ${current.full_name}. The old card no longer works; print a new one.` : `Attendance code created for ${current.full_name}.`);
      await onChanged?.(updated);
    } catch (err) {
      setReplacing(false);
      setError(`${code ? "The code was not replaced" : "No code was created"}: ${(err.message || "the server did not answer").replace(/\.$/, "")}. The card is as it was.`);
    } finally {
      setBusy(false);
    }
  };
  const download = () => { if (!downloadPng(current)) setError("This person has no code yet, so there is nothing to download."); };

  return <>
    {overScreen(<div className="fixed inset-0 z-50 grid place-items-end p-3 sm:place-items-center">
      <button type="button" className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm" onClick={() => !busy && onClose()} aria-label="Close" tabIndex={-1} />
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative flex max-h-[92vh] w-full max-w-md animate-sheet-up flex-col overflow-hidden rounded-4xl bg-white shadow-float">
        <div className="flex items-start justify-between gap-3 px-5 pt-5 sm:px-6 sm:pt-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand-50 text-brand-700"><QrCode size={20} aria-hidden="true" /></div>
            <h3 id={titleId} className="text-lg font-bold tracking-tight text-ink">Attendance QR</h3>
          </div>
          <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} disabled={busy} aria-label="Close"><X size={17} aria-hidden="true" /></button>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5 sm:px-6">
          {error && <Notice tone="danger" onClose={() => setError("")}>{error}</Notice>}
          <div className="rounded-2xl border border-line bg-canvas/60 p-3">
            <Identity name={current.full_name} detail={cardLines(current).join(" · ")} />
          </div>
          {hasCode ? <div className="grid place-items-center gap-3">
            <QrImage code={code} label={`QR code of ${current.full_name}'s attendance code`} className="h-auto w-full max-w-[18rem] rounded-xl ring-1 ring-line" />
            <p className="font-mono text-3xl font-bold tracking-[0.2em] text-ink" aria-label={`Attendance code ${formatCode(code).split("").join(" ")}`}>{formatCode(code)}</p>
          </div> : <div className="grid place-items-center gap-2 rounded-3xl border border-dashed border-slate-300/80 bg-canvas/60 px-6 py-10 text-center">
            <p className="font-semibold text-ink">No code yet</p>
            <p className="max-w-sm text-sm text-ink-muted">Create a code to print this person's QR card.</p>
          </div>}
        </div>
        <div className="flex flex-col gap-2 border-t border-line px-5 py-4 sm:flex-row sm:flex-wrap sm:justify-end sm:px-6">
          {hasCode ? <>
            <Button variant="outline" icon={RefreshCw} disabled={busy} onClick={() => setReplacing(true)}>Replace code</Button>
            <Button variant="outline" icon={Download} disabled={busy} onClick={download}>Download PNG</Button>
            <Button variant="brand" icon={Printer} disabled={busy} onClick={() => cards.print([current])}>Print card</Button>
          </> : <Button variant="brand" icon={QrCode} loading={busy} onClick={renew}>Create code</Button>}
        </div>
      </div>
    </div>)}
    <ConfirmDialog open={replacing} busy={busy} title={`Replace ${current.full_name}'s code?`} message="The old QR and code stop working at once. Print a new card for this person." confirmLabel="Replace code" onConfirm={renew} onCancel={() => setReplacing(false)} />
    {cards.sheet}
  </>;
}
