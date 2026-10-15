import React, { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, History, RefreshCw, X } from "lucide-react";
import { getAdmins, getAuditActions, getAuditLogs } from "../../lib/api";
import { AUDIT_PAGE_SIZE, BLANK_AUDIT_FILTERS, actorText, auditFilterError, auditQuery, detailLines, pageCount, rangeLabel, targetText, viewState, whenText } from "../../lib/portal";
import { Button, Card, DataTable, EmptyState, ErrorState, FormInput, FormSelect, Page } from "../../ui";
import { NotAllowed, useLoaded } from "./shared";

function Details({ details }) {
  const lines = detailLines(details);
  if (!lines.length) return <span className="text-ink-muted">-</span>;
  return <ul className="grid gap-0.5 text-xs">{lines.map(line => <li key={line} className="break-words">{line}</li>)}</ul>;
}

export default function AuditLogPage() {
  const [filters, setFilters] = useState(BLANK_AUDIT_FILTERS);
  const [page, setPage] = useState(1);
  const problem = auditFilterError(filters);
  // While the two dates contradict each other the last query that made sense stays on screen.
  const lastGood = useRef(auditQuery(filters, page));
  if (!problem) lastGood.current = auditQuery(filters, page);
  const query = lastGood.current;
  const entries = useLoaded(() => getAuditLogs(query), [JSON.stringify(query)]);
  const actions = useLoaded(getAuditActions, []);
  const accounts = useLoaded(() => getAdmins(), []);
  const data = entries.value;

  const pageProps = { title: "Audit Log", subtitle: "Who did what, and when. Entries are only ever added: nothing here can be changed or removed." };
  if ([entries, actions, accounts].some(item => item.error?.status === 403)) return <Page {...pageProps}><NotAllowed /></Page>;

  const set = field => event => { setFilters(current => ({ ...current, [field]: event.target.value })); setPage(1); };
  const clear = () => { setFilters(BLANK_AUDIT_FILTERS); setPage(1); };
  const filtered = Object.values(filters).some(Boolean);
  const items = data?.items || [];
  const state = viewState({ loading: entries.loading, error: entries.error, items: data ? items : null });
  const pages = pageCount(data?.total || 0, AUDIT_PAGE_SIZE);

  return <Page {...pageProps} actions={<Button variant="outline" icon={RefreshCw} loading={entries.loading && Boolean(data)} onClick={entries.reload}>Refresh</Button>}>
    <Card title="Filters">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_170px_170px_auto]">
        <FormSelect label="Who" value={filters.actor} onChange={set("actor")}
          options={[{ value: "", label: "Anyone" }, ...(accounts.value || []).map(account => ({ value: String(account.id), label: `${account.full_name} (${account.email})` }))]} />
        <FormSelect label="Action" value={filters.action} onChange={set("action")}
          options={[{ value: "", label: "Every action" }, ...(actions.value || []).map(item => ({ value: item.action, label: item.label }))]} />
        <FormInput label="From" type="date" value={filters.from} onChange={set("from")} max={filters.to || undefined} />
        <FormInput label="To" type="date" value={filters.to} onChange={set("to")} min={filters.from || undefined} error={problem || undefined} />
        <div className="flex items-end"><Button type="button" variant="outline" icon={X} onClick={clear} disabled={!filtered}>Clear</Button></div>
      </div>
      <p className="mt-3 text-xs text-ink-muted">Days are counted in the school's time zone; times are shown in this device's.</p>
    </Card>
    <Card title="Entries" subtitle={data ? rangeLabel(page, AUDIT_PAGE_SIZE, data.total) : "Newest first."}>
      {state === "error"
        ? <ErrorState title="Could not load the audit log" message={entries.error.message} onRetry={entries.reload} />
        : <DataTable loading={state === "loading"} caption="Audit log entries" columns={["When", "Who", "Action", "About", "Details", "From"]} rowKeys={items.map(entry => entry.id)} rows={items.map(entry => [
          <time dateTime={entry.created_at} className="whitespace-nowrap font-semibold tabular-nums text-ink">{whenText(entry.created_at)}</time>,
          <span className="break-words">{actorText(entry)}</span>,
          <span className="font-semibold text-ink">{entry.action_label}</span>,
          <span className="break-words">{targetText(entry)}</span>,
          <Details details={entry.details} />,
          <span className="whitespace-nowrap text-xs" title={entry.user_agent || undefined}>{entry.ip || "-"}</span>
        ])} empty={filtered
          ? <EmptyState icon={History} title="No entry matches these filters" action={<Button size="sm" variant="outline" onClick={clear}>Clear the filters</Button>} />
          : <EmptyState icon={History} title="Nothing recorded yet" message="Logins, account changes, deletions, manual attendance, face enrollments and uploads are recorded here." />} />}
      {data && data.total > AUDIT_PAGE_SIZE && <nav aria-label="Pages of the audit log" className="mt-4 flex items-center justify-between gap-3">
        <Button size="sm" variant="outline" icon={ChevronLeft} disabled={page <= 1 || entries.loading} onClick={() => setPage(page - 1)}>Newer</Button>
        <p className="text-sm font-medium tabular-nums text-ink-muted">Page {page} of {pages}</p>
        <Button size="sm" variant="outline" disabled={page >= pages || entries.loading} onClick={() => setPage(page + 1)}>Older<ChevronRight size={16} aria-hidden="true" /></Button>
      </nav>}
    </Card>
  </Page>;
}
