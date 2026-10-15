// What the issue pages share: My reports (anyone) and the portal's Issues (super admins). Everything
// people typed is shown as text: React writes it into the page as text, and nothing here hands it to
// the page as HTML.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, SearchX, Send } from "lucide-react";
import { getOpenIssueCount } from "../lib/api";
import { ROLE_LABELS } from "../lib/auth";
import {
  LIMITS, OPEN_COUNT_INTERVAL_MS, canComment, categoryLabel, characters, cleanText, commentError, deviceText, severityLabel, severityTone,
  showsResolution, statusLabel, statusTone
} from "../lib/issues";
import { whenText } from "../lib/portal";
import { Button, Card, EmptyState, FormTextarea, Notice, StatusBadge } from "../ui";

// Calls load() every `every` milliseconds while the page can be seen, and at once when it can be
// seen again. Nothing is asked while the tab is hidden, or while enabled is false.
export function usePolling(load, every, enabled = true) {
  const latest = useRef(load);
  latest.current = load;
  useEffect(() => {
    if (!enabled) return undefined;
    let timer = null;
    const stop = () => { clearInterval(timer); timer = null; };
    const start = () => { stop(); if (document.visibilityState === "visible") timer = setInterval(() => latest.current(), every); };
    const onVisibility = () => {
      if (document.visibilityState !== "visible") { stop(); return; }
      latest.current();
      start();
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [enabled, every]);
}

// The number on the portal's Issues entry: issues open or in progress. Asked for only while a
// super admin has a portal page open (enabled); null otherwise, or when it could not be had.
export function useOpenIssueCount(enabled) {
  const [count, setCount] = useState(null);
  const on = useRef(enabled);
  on.current = enabled;
  const refresh = useCallback(async () => {
    if (!on.current) return;
    try {
      const data = await getOpenIssueCount();
      if (on.current) setCount(data.count);
    } catch {
      // Refused (the role changed a moment ago) or no backend: no number is better than a wrong one.
      setCount(null);
    }
  }, []);
  useEffect(() => { if (enabled) refresh(); }, [enabled]);
  usePolling(refresh, OPEN_COUNT_INTERVAL_MS, enabled);
  return { count: enabled ? count : null, refresh };
}

export function IssueStatus({ status }) {
  return <StatusBadge tone={statusTone(status)}><span className="sr-only">Status: </span>{statusLabel(status)}</StatusBadge>;
}

export function IssueSeverity({ severity }) {
  return <StatusBadge tone={severityTone(severity)}><span className="sr-only">Severity: </span>{severityLabel(severity)}</StatusBadge>;
}

// Text someone typed, with its line breaks, as text.
export function PlainText({ children, className = "" }) {
  return <p className={`whitespace-pre-wrap break-words ${className}`}>{children}</p>;
}

export function When({ value }) {
  return value ? <time dateTime={value} className="whitespace-nowrap tabular-nums">{whenText(value)}</time> : <span className="text-ink-muted">-</span>;
}

// The title of an issue in a list: a real link (it can be opened in a new tab) that the console
// follows itself.
export function IssueLink({ issue, href, onOpen }) {
  const follow = event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    onOpen(issue.id);
  };
  return <a href={href} onClick={follow} className="block min-w-0 rounded-lg text-left outline-none focus-visible:ring-4 focus-visible:ring-brand-100">
    <span className="block break-words font-semibold text-ink underline-offset-2 hover:underline">{issue.title}</span>
    <span className="block text-xs font-medium text-ink-muted">#{issue.id}</span>
  </a>;
}

function Fact({ label, children }) {
  return <div className="min-w-0 rounded-2xl bg-canvas/70 px-4 py-3">
    <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</dt>
    <dd className="mt-1 break-words text-sm font-semibold text-ink">{children}</dd>
  </div>;
}

function personText(person) {
  if (!person) return "Nobody";
  return person.email ? `${person.full_name} (${person.email})` : person.full_name;
}

// One issue: what was reported, how it was resolved (once it was), and where it came from. withPeople:
// the portal's view, which also says who reported it and who has it.
export function IssueSummary({ issue, withPeople = false }) {
  return <Card>
    <div className="flex flex-wrap items-center gap-2">
      <IssueStatus status={issue.status} />
      <IssueSeverity severity={issue.severity} />
      <span className="text-xs font-semibold text-ink-muted">#{issue.id} · {categoryLabel(issue.category)}</span>
    </div>
    <h3 className="mt-3 break-words text-xl font-bold tracking-tight text-ink">{issue.title}</h3>
    <PlainText className="mt-3 text-sm leading-6 text-ink-soft">{issue.description}</PlainText>
    {showsResolution(issue) && <section aria-label="Resolution" className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 ring-1 ring-inset ring-emerald-600/15">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-emerald-800">Resolution note</p>
      <PlainText className="mt-1 text-sm text-emerald-900">{issue.resolution_note}</PlainText>
    </section>}
    <dl className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {withPeople && <Fact label="Reported by">{personText(issue.reporter)}</Fact>}
      {withPeople && <Fact label="Assigned to">{personText(issue.assignee)}</Fact>}
      <Fact label="Reported"><When value={issue.created_at} /></Fact>
      <Fact label="Last change"><When value={issue.updated_at} /></Fact>
      {issue.resolved_at && <Fact label="Resolved"><When value={issue.resolved_at} /></Fact>}
      <Fact label="Page"><span className="break-all font-mono text-[13px]">{issue.page_url || "Not recorded"}</span></Fact>
      <Fact label="Device">{deviceText(issue.device_info)}</Fact>
    </dl>
  </Card>;
}

export function CommentThread({ comments }) {
  if (!comments.length) return <p className="text-sm text-ink-muted">No comments yet.</p>;
  return <ol className="grid gap-3">
    {comments.map(comment => <li key={comment.id} className={`rounded-2xl px-4 py-3 ${comment.author?.role === "super_admin" ? "bg-brand-50/70" : "bg-canvas/70"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="text-sm font-semibold text-ink">{comment.author?.full_name || "Someone"}<span className="font-medium text-ink-muted"> · {ROLE_LABELS[comment.author?.role] || "Account"}</span></p>
        <p className="text-xs text-ink-muted"><When value={comment.created_at} /></p>
      </div>
      <PlainText className="mt-1 text-sm text-ink-soft">{comment.body}</PlainText>
    </li>)}
  </ol>;
}

// send(body) adds the comment; onSent() reloads the thread.
export function CommentForm({ issue, send, onSent }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  if (!canComment(issue)) return <Notice>This issue is closed, so it takes no more comments.</Notice>;
  const submit = async event => {
    event.preventDefault();
    const problem = commentError(text);
    if (problem) { setError(problem); return; }
    setBusy(true);
    setError("");
    try {
      await send(cleanText(text));
      setText("");
      onSent();
    } catch (failure) {
      setError(failure.message || "The comment could not be sent.");
    } finally {
      setBusy(false);
    }
  };
  return <form onSubmit={submit} noValidate className="grid gap-3">
    <FormTextarea label="Add a comment" rows={3} value={text} error={error} hint={`${characters(cleanText(text))}/${LIMITS.comment[1]} characters`}
      onChange={event => { setText(event.target.value); if (error) setError(""); }} />
    <div className="flex justify-end"><Button icon={Send} loading={busy}>Send comment</Button></div>
  </form>;
}

export function Pager({ label, page, pages, busy, onPage }) {
  if (pages <= 1) return null;
  return <nav aria-label={label} className="mt-4 flex items-center justify-between gap-3">
    <Button size="sm" variant="outline" icon={ChevronLeft} disabled={page <= 1 || busy} onClick={() => onPage(page - 1)}>Previous</Button>
    <p className="text-sm font-medium tabular-nums text-ink-muted">Page {page} of {pages}</p>
    <Button size="sm" variant="outline" disabled={page >= pages || busy} onClick={() => onPage(page + 1)}>Next<ChevronRight size={16} aria-hidden="true" /></Button>
  </nav>;
}

// The same words for an issue that does not exist and for one that is somebody else's.
export function IssueMissing({ action }) {
  return <EmptyState icon={SearchX} title="Issue not found" message="It does not exist, or it is not one you can open." action={action} />;
}
