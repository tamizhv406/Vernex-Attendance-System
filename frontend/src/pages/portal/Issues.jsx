// The issues inbox (IR-03): every problem admins and super admins reported, filtered and sorted, and
// one issue's page, where a super admin answers it, changes its status and assigns it. The backend
// refuses all of this to an admin; the list asks again every 45 seconds while it can be seen.
import React, { useEffect, useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ArrowLeft, Inbox, RefreshCw, Save, X } from "lucide-react";
import { commentOnIssue, getAdmins, getInboxIssue, getInboxIssues, updateIssue } from "../../lib/api";
import {
  BLANK_INBOX_FILTERS, CATEGORY_OPTIONS, INBOX_STATUS_OPTIONS, ISSUE_PAGE_SIZE, LIMITS, OPEN_COUNT_INTERVAL_MS, SEVERITY_OPTIONS, SORT_OPTIONS, STATUS_OPTIONS,
  categoryLabel, characters, cleanText, fieldErrors, formFromIssue, inboxFilterError, inboxFiltered, inboxQuery, issueChanges
} from "../../lib/issues";
import { pageCount, rangeLabel, viewState } from "../../lib/portal";
import { pathFor } from "../../routes";
import { Button, Card, DataTable, EmptyState, ErrorState, FormInput, FormSelect, FormTextarea, Notice, Page, Segmented, Skeleton } from "../../ui";
import { CommentForm, CommentThread, IssueLink, IssueMissing, IssueSeverity, IssueStatus, IssueSummary, Pager, When, usePolling } from "../issueParts";
import { LoadFailed, NotAllowed, useLoaded } from "./shared";

const PAGE_TEXT = { title: "Issues", subtitle: "Problems reported by admins and super admins." };

// issueId: one issue, or the inbox when there is none. The inbox's filters and page are kept here,
// so that coming back from an issue finds them as they were. onChanged(): the open count may have
// changed (the badge asks again).
export default function IssuesPage({ issueId, setPage, onChanged, notify }) {
  const [filters, setFilters] = useState(BLANK_INBOX_FILTERS);
  const [listPage, setListPage] = useState(1);
  if (issueId) return <InboxIssue key={issueId} issueId={issueId} setPage={setPage} onChanged={onChanged} notify={notify} />;
  return <InboxList filters={filters} setFilters={setFilters} page={listPage} setListPage={setListPage} setPage={setPage} />;
}

function InboxList({ filters, setFilters, page, setListPage, setPage }) {
  const problem = inboxFilterError(filters);
  // While the two dates contradict each other the last list that made sense stays on screen.
  const lastGood = useRef(inboxQuery(filters, page));
  if (!problem) lastGood.current = inboxQuery(filters, page);
  const query = lastGood.current;
  const issues = useLoaded(() => getInboxIssues(query), [JSON.stringify(query)]);
  const accounts = useLoaded(() => getAdmins(), []);
  // A report made a moment ago shows up within the minute, without anyone pressing Refresh.
  usePolling(issues.reload, OPEN_COUNT_INTERVAL_MS);
  if ([issues, accounts].some(item => item.error?.status === 403)) return <Page {...PAGE_TEXT}><NotAllowed /></Page>;

  const data = issues.value;
  const items = data?.items || [];
  const state = viewState({ loading: issues.loading, error: issues.error, items: data ? items : null });
  const set = field => event => { setFilters(current => ({ ...current, [field]: event.target.value })); setListPage(1); };
  const sortBy = value => { setFilters(current => ({ ...current, sort: value })); setListPage(1); };
  const clear = () => { setFilters(current => ({ ...BLANK_INBOX_FILTERS, sort: current.sort })); setListPage(1); };
  const filtered = inboxFiltered(filters);
  const open = id => setPage("portalIssues", id);
  const reporters = (accounts.value || []).map(account => ({ value: String(account.id), label: `${account.full_name} (${account.email})` }));

  return <Page {...PAGE_TEXT} actions={<Button variant="outline" icon={RefreshCw} loading={issues.loading && Boolean(data)} onClick={issues.reload}>Refresh</Button>}>
    <Card title="Filters">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <FormSelect label="Status" value={filters.status} onChange={set("status")} options={INBOX_STATUS_OPTIONS} />
        <FormSelect label="Severity" value={filters.severity} onChange={set("severity")} options={[{ value: "", label: "Any severity" }, ...SEVERITY_OPTIONS]} />
        <FormSelect label="Category" value={filters.category} onChange={set("category")} options={[{ value: "", label: "Any category" }, ...CATEGORY_OPTIONS]} />
        <FormSelect label="Reported by" value={filters.reporter} onChange={set("reporter")} options={[{ value: "", label: "Anyone" }, ...reporters]} />
        <FormInput label="Reported from" type="date" value={filters.from} onChange={set("from")} max={filters.to || undefined} />
        <FormInput label="Reported until" type="date" value={filters.to} onChange={set("to")} min={filters.from || undefined} error={problem || undefined} />
      </div>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold text-ink-soft" aria-hidden="true">Sort by</span>
          <Segmented label="Sort by" value={filters.sort} onChange={sortBy} options={SORT_OPTIONS} />
        </div>
        <Button type="button" variant="outline" icon={X} onClick={clear} disabled={!filtered}>Clear filters</Button>
      </div>
      <p className="mt-3 text-xs text-ink-muted">Days are counted in the school's time zone; times are shown in this device's. The list updates by itself every 45 seconds.</p>
    </Card>
    <Card title="Reported issues" subtitle={data ? rangeLabel(page, ISSUE_PAGE_SIZE, data.total) : "Newest first."}>
      {state === "error"
        ? <ErrorState title="Could not load the issues" message={issues.error.message} onRetry={issues.reload} />
        : <DataTable loading={state === "loading"} caption="Reported issues" columns={["Issue", "Status", "Severity", "Category", "Reported by", "Assigned to", "Reported"]}
          rowKeys={items.map(issue => issue.id)} rows={items.map(issue => [
            <IssueLink issue={issue} href={pathFor("portalIssues", issue.id)} onOpen={open} />,
            <IssueStatus status={issue.status} />,
            <IssueSeverity severity={issue.severity} />,
            categoryLabel(issue.category),
            <span className="break-words">{issue.reporter?.full_name || "-"}</span>,
            <span className="break-words">{issue.assignee?.full_name || "Nobody"}</span>,
            <When value={issue.created_at} />
          ])}
          empty={filtered
            ? <EmptyState icon={Inbox} title="No issue matches these filters" action={<Button size="sm" variant="outline" onClick={clear}>Clear the filters</Button>} />
            : <EmptyState icon={Inbox} title="No open issues" message="Problems admins report from the console arrive here. To see resolved and closed ones too, choose All statuses." />} />}
      <Pager label="Pages of the issues" page={page} pages={pageCount(data?.total || 0, ISSUE_PAGE_SIZE)} busy={issues.loading} onPage={setListPage} />
    </Card>
  </Page>;
}

function InboxIssue({ issueId, setPage, onChanged, notify }) {
  const issue = useLoaded(() => getInboxIssue(issueId), [issueId]);
  // Who an issue can be given to: the active super admins.
  const owners = useLoaded(() => getAdmins({ role: "super_admin", status: "active" }), []);
  const data = issue.value;
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [failure, setFailure] = useState("");
  const [saving, setSaving] = useState(false);
  const noteId = useId();
  // The form starts from the issue as saved, again after each save. A new comment does not touch it.
  useEffect(() => {
    if (data) { setForm(formFromIssue(data)); setErrors({}); }
  }, [data?.id, data?.status, data?.assigned_to, data?.resolution_note]);

  const back = <Button variant="outline" icon={ArrowLeft} onClick={() => setPage("portalIssues")}>All issues</Button>;
  if ([issue, owners].some(item => item.error?.status === 403)) return <Page {...PAGE_TEXT}><NotAllowed /></Page>;
  if (issue.error?.status === 404) {
    return <Page {...PAGE_TEXT} actions={back}><Card><IssueMissing action={<Button size="sm" variant="outline" onClick={() => setPage("portalIssues")}>Back to the inbox</Button>} /></Card></Page>;
  }

  const set = field => event => {
    const value = event.target.value;
    setForm(current => ({ ...current, [field]: value }));
    if (errors[field]) setErrors(current => ({ ...current, [field]: undefined }));
  };
  const save = async event => {
    event.preventDefault();
    const { errors: found, body } = issueChanges(data, form);
    setErrors(found);
    setFailure("");
    if (found.note) { document.getElementById(noteId)?.focus(); return; }
    if (!Object.keys(body).length) { notify("Nothing to save: nothing was changed.", "info"); return; }
    // The fields stay locked until the saved issue has been read back: a change made meanwhile would
    // be overwritten by the reload without a word.
    setSaving(true);
    let focusNote = false;
    try {
      await updateIssue(issueId, body);
      onChanged?.();
      await issue.reload();
      notify("Issue saved. The reporter sees the change in My reports.");
    } catch (error) {
      const named = fieldErrors(error, ["status", "resolution_note", "assigned_to"]);
      if (named.resolution_note) { setErrors({ note: named.resolution_note }); focusNote = true; }
      else setFailure(named.assigned_to || named.status || error.message);
    } finally {
      flushSync(() => setSaving(false));
      if (focusNote) document.getElementById(noteId)?.focus();
    }
  };

  // Whoever has the issue stays in the list even if they are no longer an active super admin.
  const assignees = [{ value: "", label: "Nobody" }, ...(owners.value || []).map(account => ({ value: String(account.id), label: account.full_name }))];
  if (data?.assignee && !assignees.some(option => option.value === String(data.assigned_to))) {
    assignees.push({ value: String(data.assigned_to), label: `${data.assignee.full_name} (no longer an active super admin)` });
  }
  const noteCount = characters(cleanText(form?.note));

  return <Page {...PAGE_TEXT} actions={<>
    {back}
    <Button variant="outline" icon={RefreshCw} loading={issue.loading && Boolean(data)} onClick={issue.reload}>Refresh</Button>
  </>}>
    {issue.error && <LoadFailed error={issue.error} onRetry={issue.reload} what="this issue" />}
    {!data && !issue.error && <div className="grid gap-3" aria-busy="true"><Skeleton className="h-40 w-full" /><Skeleton className="h-28 w-full" /></div>}
    {data && form && <>
      <IssueSummary issue={data} withPeople />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_360px]">
        <Card title="Status and assignment" subtitle="The reporter sees the status, and the resolution note once it is resolved." className="xl:order-2 xl:self-start">
          <form onSubmit={save} noValidate className="grid gap-4">
            <FormSelect label="Status" value={form.status} onChange={set("status")} options={STATUS_OPTIONS} disabled={saving} />
            {form.status === "resolved" && <FormTextarea id={noteId} required label="Resolution note" rows={4} value={form.note} onChange={set("note")} error={errors.note} disabled={saving}
              hint={`${noteCount}/${LIMITS.note[1]} characters. What was done, or why nothing needs to be.`} />}
            <FormSelect label="Assigned to" value={form.assignee} onChange={set("assignee")} options={assignees} hint="Active super admins only." disabled={saving} />
            {failure && <Notice tone="danger">{failure}</Notice>}
            <div className="flex justify-end"><Button icon={Save} loading={saving}>Save</Button></div>
          </form>
        </Card>
        <Card title="Comments" subtitle="The reporter reads these in My reports. A comment cannot be changed once it is sent." className="xl:order-1">
          <CommentThread comments={data.comments} />
          <div className="mt-5"><CommentForm issue={data} send={body => commentOnIssue(issueId, body)} onSent={issue.reload} /></div>
        </Card>
      </div>
    </>}
  </Page>;
}
