// Shared building blocks. Every screen is made from these, so spacing, radii, colours and states stay the same everywhere.
import React, { useEffect, useId, useRef } from "react";
import { AlertTriangle, Check, CheckCircle2, Clock3, Edit3 as EditIcon, Inbox, Info as InfoIcon, Loader2, Minus, RefreshCw, Search, Trash2 as TrashIcon, X, XCircle } from "lucide-react";
import { initials, titleCase } from "./lib/format";

const TONES = {
  success: { soft: "bg-emerald-50 text-emerald-700 ring-emerald-600/15", solid: "bg-emerald-500", text: "text-emerald-700", icon: Check },
  warning: { soft: "bg-amber-50 text-amber-800 ring-amber-600/20", solid: "bg-amber-500", text: "text-amber-800", icon: Clock3 },
  danger: { soft: "bg-red-50 text-red-700 ring-red-600/15", solid: "bg-red-500", text: "text-red-700", icon: X },
  info: { soft: "bg-brand-50 text-brand-700 ring-brand-600/15", solid: "bg-brand-600", text: "text-brand-700", icon: InfoIcon },
  neutral: { soft: "bg-slate-100 text-slate-600 ring-slate-500/15", solid: "bg-slate-400", text: "text-slate-600", icon: Minus }
};

const STATUS_TONE = {
  Active: "success", Completed: "success", Present: "success", Enrolled: "success", Online: "success", Visited: "success",
  Pending: "warning", Late: "warning", Confirming: "warning", Verifying: "warning", Checking: "warning",
  Absent: "danger", Offline: "danger", Rejected: "danger",
  "Already Marked": "info",
  Unknown: "neutral", Inactive: "neutral", "Not Started": "neutral", Stopped: "neutral"
};

export function toneOf(status) {
  return STATUS_TONE[titleCase(status || "Unknown")] || "neutral";
}

export function tone(name) {
  return TONES[name] || TONES.neutral;
}

// A status is always an icon and a word, never a colour on its own.
export function StatusBadge({ status, tone: forced, children }) {
  const label = children || titleCase(status || "Unknown");
  const style = tone(forced || toneOf(status));
  const Icon = style.icon;
  return <span className={`inline-flex min-h-7 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-xs font-semibold ring-1 ring-inset ${style.soft}`}>
    <Icon size={12} strokeWidth={2.75} aria-hidden="true" />{label}
  </span>;
}

// Written out in full so Tailwind keeps every variant in the stylesheet.
const BUTTON_VARIANTS = { primary: "btn-primary", brand: "btn-brand", outline: "btn-outline", danger: "btn-danger" };

export function Button({ variant = "primary", size, icon: Icon, loading, children, className = "", disabled, ...props }) {
  return <button className={`btn ${BUTTON_VARIANTS[variant]} ${size === "sm" ? "btn-sm" : ""} ${className}`} {...props} disabled={loading || disabled}>
    {loading ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : Icon ? <Icon size={16} aria-hidden="true" /> : null}
    {children}
  </button>;
}

export function IconButton({ icon: Icon, label, className = "", ...props }) {
  return <button type="button" className={`icon-btn ${className}`} aria-label={label} title={label} {...props}><Icon size={17} aria-hidden="true" /></button>;
}

export function Card({ title, subtitle, action, children, className = "", padded = true }) {
  return <section className={`card ${padded ? "p-5 sm:p-6" : ""} ${className}`}>
    {(title || action) && <div className={`flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between ${padded ? "mb-5" : "px-5 pt-5 sm:px-6 sm:pt-6"}`}>
      <div className="min-w-0">
        {title && <h3 className="text-base font-bold tracking-tight text-ink">{title}</h3>}
        {subtitle && <p className="mt-0.5 text-sm text-ink-muted">{subtitle}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
    </div>}
    {children}
  </section>;
}

export function PageHeader({ title, subtitle, actions }) {
  return <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
    <div className="min-w-0">
      <h2 className="text-2xl font-extrabold tracking-tight text-ink sm:text-[28px]">{title}</h2>
      {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-muted">{subtitle}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
  </div>;
}

export function Page({ title, subtitle, actions, children }) {
  return <div className="animate-fade-up space-y-5">
    <PageHeader title={title} subtitle={subtitle} actions={actions} />
    {children}
  </div>;
}

function FieldShell({ label, hint, error, className = "", children }) {
  return <label className={`grid content-start gap-1.5 ${className}`}>
    <span className="text-[13px] font-semibold text-ink-soft">{label}</span>
    {children}
    {error ? <span className="text-xs font-medium text-red-600">{error}</span> : hint ? <span className="text-xs text-ink-muted">{hint}</span> : null}
  </label>;
}

export function FormInput({ label, hint, error, className = "", ...props }) {
  return <FieldShell label={props.required ? `${label} *` : label} hint={hint} error={error} className={className}>
    <input className={`field ${error ? "border-red-400" : ""}`} aria-invalid={Boolean(error) || undefined} {...props} />
  </FieldShell>;
}

export function FormTextarea({ label, hint, className = "", ...props }) {
  return <FieldShell label={label} hint={hint} className={className}>
    <textarea className="field h-auto min-h-24 py-3" {...props} />
  </FieldShell>;
}

export function FormSelect({ label, options = [], empty = "No options", hint, className = "", ...props }) {
  const hasEmptyValueOption = options.some(option => (typeof option === "string" ? option : option.value) === "");
  const needsPlaceholder = options.length > 0 && !hasEmptyValueOption && (props.value ?? "") === "";
  return <FieldShell label={props.required ? `${label} *` : label} hint={hint} className={className}>
    <select className="field field-select" {...props}>
      {!options.length && <option value="">{empty}</option>}
      {needsPlaceholder && <option value="" disabled hidden>{`Select ${label.toLowerCase()}`}</option>}
      {options.map(option => typeof option === "string" ? <option key={option} value={option}>{option}</option> : <option key={`${option.value}-${option.label}`} value={option.value}>{option.label}</option>)}
    </select>
  </FieldShell>;
}

export function SearchInput({ value, onChange, placeholder = "Search", className = "" }) {
  return <label className={`relative block ${className}`}>
    <span className="sr-only">{placeholder}</span>
    <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden="true" />
    <input type="search" className="field rounded-full pl-10" placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)} />
  </label>;
}

// A row of pill choices; the chosen one is the dark pill, as in the navigation.
export function Segmented({ label, value, onChange, options }) {
  return <div role="group" aria-label={label} className="inline-flex max-w-full gap-1 overflow-x-auto rounded-full border border-line bg-canvas p-1">
    {options.map(option => <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => onChange(option.value)} className={`h-9 whitespace-nowrap rounded-full px-3.5 text-[13px] font-semibold transition duration-150 ${value === option.value ? "bg-ink text-white shadow-sm" : "text-ink-muted hover:bg-white hover:text-ink"}`}>
      {option.label}{option.count !== undefined && <span className={`ml-1.5 tabular-nums ${value === option.value ? "text-white/70" : "text-slate-400"}`}>{option.count}</span>}
    </button>)}
  </div>;
}

export function EmptyState({ icon: Icon = Inbox, title, message, action }) {
  return <div className="grid place-items-center rounded-3xl border border-dashed border-slate-300/80 bg-canvas/60 px-6 py-10 text-center">
    <div className="grid h-12 w-12 place-items-center rounded-2xl bg-white text-ink-muted shadow-card"><Icon size={22} aria-hidden="true" /></div>
    <p className="mt-4 font-semibold text-ink">{title}</p>
    {message && <p className="mt-1 max-w-sm text-sm text-ink-muted">{message}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>;
}

export function ErrorState({ title = "Something went wrong", message, onRetry }) {
  return <div role="alert" className="flex flex-col gap-3 rounded-3xl border border-red-200 bg-red-50 p-4 sm:flex-row sm:items-center sm:justify-between">
    <div className="flex min-w-0 items-start gap-3">
      <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-white text-red-600"><AlertTriangle size={17} aria-hidden="true" /></div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-red-900">{title}</p>
        {message && <p className="mt-0.5 break-words text-sm text-red-800">{message}</p>}
      </div>
    </div>
    {onRetry && <Button variant="outline" size="sm" icon={RefreshCw} onClick={onRetry}>Try again</Button>}
  </div>;
}

export function Notice({ tone: name = "info", children, onClose }) {
  const style = tone(name);
  const Icon = name === "danger" ? XCircle : name === "success" ? CheckCircle2 : name === "warning" ? AlertTriangle : InfoIcon;
  return <div role={name === "danger" ? "alert" : "status"} className={`flex items-start gap-3 rounded-2xl px-4 py-3 text-sm font-medium ring-1 ring-inset ${style.soft}`}>
    <Icon size={17} className="mt-0.5 shrink-0" aria-hidden="true" />
    <p className="min-w-0 flex-1 break-words">{children}</p>
    {onClose && <button type="button" className="-m-1 grid h-7 w-7 shrink-0 place-items-center rounded-full hover:bg-black/5" onClick={onClose} aria-label="Dismiss"><X size={15} aria-hidden="true" /></button>}
  </div>;
}

export function Toast({ toast, onClose }) {
  if (!toast) return null;
  const style = tone(toast.tone);
  const Icon = toast.tone === "danger" ? XCircle : CheckCircle2;
  return <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex justify-center px-4" aria-live="polite">
    <div role="status" className="pointer-events-auto flex max-w-md animate-fade-up items-center gap-3 rounded-full border border-white/60 bg-ink/95 py-2.5 pl-3 pr-2 text-sm font-medium text-white shadow-float backdrop-blur">
      <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full ${style.solid}`}><Icon size={14} aria-hidden="true" /></span>
      <span className="min-w-0 break-words">{toast.message}</span>
      <button type="button" className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-white/70 hover:bg-white/10 hover:text-white" onClick={onClose} aria-label="Dismiss notification"><X size={14} aria-hidden="true" /></button>
    </div>
  </div>;
}

export function Skeleton({ className = "" }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function Spinner({ label = "Loading" }) {
  return <span className="inline-flex items-center gap-2 text-sm font-medium text-ink-muted" role="status"><Loader2 size={16} className="animate-spin" aria-hidden="true" />{label}</span>;
}

export function Avatar({ name, size = "md" }) {
  const dims = size === "lg" ? "h-12 w-12 text-base" : size === "sm" ? "h-8 w-8 text-[11px]" : "h-10 w-10 text-xs";
  return <span className={`grid shrink-0 place-items-center rounded-full bg-gradient-to-br from-brand-100 to-brand-50 font-bold text-brand-700 ring-1 ring-inset ring-brand-600/10 ${dims}`} aria-hidden="true">{initials(name)}</span>;
}

// Name with a quieter second line (a code, a batch...). Used as the first cell of most tables.
export function Identity({ name, detail }) {
  return <div className="flex min-w-0 items-center gap-3">
    <Avatar name={name} size="sm" />
    <div className="min-w-0 text-left">
      <p className="truncate font-semibold text-ink">{name || "-"}</p>
      {detail && <p className="truncate text-xs text-ink-muted">{detail}</p>}
    </div>
  </div>;
}

export function Info({ label, value }) {
  return <div className="rounded-2xl bg-canvas/70 px-4 py-3">
    <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</p>
    <p className="mt-1 break-words text-sm font-semibold text-ink">{value || "-"}</p>
  </div>;
}

export function StatCard({ icon: Icon, label, value, detail, loading, accent }) {
  return <article className="card flex items-center gap-4 p-5 transition duration-200 hover:-translate-y-0.5 hover:shadow-float">
    <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl ${accent ? "bg-brand-600 text-white shadow-brand" : "bg-canvas text-ink"}`}><Icon size={21} aria-hidden="true" /></div>
    <div className="min-w-0">
      <p className="truncate text-[13px] font-medium text-ink-muted">{label}</p>
      {loading ? <Skeleton className="mt-1.5 h-7 w-14" /> : <p className="text-2xl font-extrabold tabular-nums tracking-tight text-ink">{value}</p>}
      {detail && !loading && <p className="truncate text-xs text-ink-muted">{detail}</p>}
    </div>
  </article>;
}

// Share of a whole as a ring. Shows nothing invented: with no total it draws an empty track.
export function ProgressRing({ value, total, size = 132, label }) {
  const stroke = 12;
  const radius = (size - stroke) / 2;
  const length = 2 * Math.PI * radius;
  const share = total > 0 ? Math.min(1, value / total) : 0;
  return <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }} role="img" aria-label={label}>
    <svg width={size} height={size} className="-rotate-90">
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#ECEEF1" strokeWidth={stroke} />
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#2563EB" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={length} strokeDashoffset={length * (1 - share)} className="transition-[stroke-dashoffset] duration-700 ease-out" />
    </svg>
    <div className="absolute text-center">
      <p className="text-2xl font-extrabold tabular-nums tracking-tight text-ink">{total > 0 ? `${Math.round(share * 100)}%` : "–"}</p>
      <p className="text-[11px] font-medium text-ink-muted">{total > 0 ? `${value} of ${total}` : "No data"}</p>
    </div>
  </div>;
}

// Desktop: a table. Phones: one card per row, with the first column as the card's heading.
export function DataTable({ columns, rows, empty, emptyIcon, loading, caption }) {
  if (loading) return <div className="grid gap-2" aria-busy="true">{[0, 1, 2, 3].map(index => <Skeleton key={index} className="h-12 w-full" />)}</div>;
  if (!rows.length) return typeof empty === "string" ? <EmptyState icon={emptyIcon} title={empty} /> : empty;
  return <div className="overflow-hidden rounded-2xl border border-line">
    <div className="hidden overflow-x-auto md:block">
      <table className="min-w-full text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead><tr className="bg-canvas/70">{columns.map(column => <th key={column} scope="col" className="whitespace-nowrap px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{column}</th>)}</tr></thead>
        <tbody className="divide-y divide-line bg-white">{rows.map((row, index) => <tr key={index} className="transition-colors duration-150 hover:bg-canvas/50">{row.map((cell, cellIndex) => <td key={cellIndex} className="px-4 py-3 align-middle text-ink-soft">{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>
    <ul className="divide-y divide-line bg-white md:hidden">
      {rows.map((row, index) => <li key={index} className="p-4">
        <div className="font-semibold text-ink">{row[0]}</div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3">
          {row.slice(1).map((cell, cellIndex) => <div key={cellIndex} className="min-w-0">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{columns[cellIndex + 1]}</dt>
            <dd className="mt-1 break-words text-sm text-ink-soft">{cell}</dd>
          </div>)}
        </dl>
      </li>)}
    </ul>
  </div>;
}

// Asks before anything that cannot be undone. Escape and the backdrop cancel; focus starts on Cancel.
export function ConfirmDialog({ open, title, message, confirmLabel = "Delete", busy, onConfirm, onCancel }) {
  const cancelRef = useRef(null);
  const titleId = useId();
  const textId = useId();
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement;
    cancelRef.current?.focus();
    const onKey = event => { if (event.key === "Escape" && !busy) onCancel(); };
    addEventListener("keydown", onKey);
    return () => { removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [open, busy]);
  if (!open) return null;
  return <div className="fixed inset-0 z-50 grid place-items-end p-3 sm:place-items-center">
    <button type="button" className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm" onClick={() => !busy && onCancel()} aria-label="Cancel" tabIndex={-1} />
    <div role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={textId} className="relative w-full max-w-md animate-sheet-up rounded-4xl bg-white p-6 shadow-float">
      <div className="grid h-11 w-11 place-items-center rounded-2xl bg-red-50 text-red-600"><AlertTriangle size={20} aria-hidden="true" /></div>
      <h3 id={titleId} className="mt-4 text-lg font-bold tracking-tight text-ink">{title}</h3>
      <p id={textId} className="mt-1 text-sm text-ink-muted">{message}</p>
      <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <button ref={cancelRef} type="button" className="btn btn-outline" onClick={onCancel} disabled={busy}>Cancel</button>
        <Button variant="danger" loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
      </div>
    </div>
  </div>;
}

export function RowActions({ onEdit, onDelete, name }) {
  return <div className="flex gap-2">
    {onEdit && <IconButton icon={EditIcon} label={`Edit ${name}`} onClick={onEdit} className="h-9 w-9" />}
    {onDelete && <IconButton icon={TrashIcon} label={`Delete ${name}`} onClick={onDelete} className="h-9 w-9 hover:border-red-200 hover:bg-red-50 hover:text-red-600" />}
  </div>;
}
