// My reports (IR-02): the problems this account reported, their status, and the thread with the super
// admins. The backend answers about one's own issues only; someone else's is "not found".
import React, { useState } from "react";
import { ArrowLeft, Flag, LifeBuoy, RefreshCw } from "lucide-react";
import { commentOnMyIssue, getMyIssue, getMyIssues } from "../lib/api";
import { ISSUE_PAGE_SIZE, categoryLabel } from "../lib/issues";
import { pageCount, rangeLabel, viewState } from "../lib/portal";
import { PAGES, pathFor } from "../routes";
import { Button, Card, DataTable, EmptyState, ErrorState, Page, Skeleton } from "../ui";
import { CommentForm, CommentThread, IssueLink, IssueMissing, IssueSeverity, IssueStatus, IssueSummary, Pager, When } from "./issueParts";
import { LoadFailed, useLoaded } from "./portal/shared";

const { title: TITLE, subtitle: SUBTITLE } = PAGES.myReports;

// issueId: one issue, or the list when there is none. reported: goes up by one with every new report,
// so that the list asks again. The page of the list is kept while one issue is open.
export default function MyReportsPage({ issueId, setPage, onReport, reported }) {
  const [listPage, setListPage] = useState(1);
  if (issueId) return <MyIssue key={issueId} issueId={issueId} setPage={setPage} />;
  return <MyIssueList page={listPage} setListPage={setListPage} setPage={setPage} onReport={onReport} reported={reported} />;
}

function MyIssueList({ page, setListPage, setPage, onReport, reported }) {
  const issues = useLoaded(() => getMyIssues({ page, page_size: ISSUE_PAGE_SIZE }), [page, reported]);
  const data = issues.value;
  const items = data?.items || [];
  const state = viewState({ loading: issues.loading, error: issues.error, items: data ? items : null });
  const open = id => setPage("myReports", id);
  const reportButton = <Button size="sm" icon={Flag} onClick={onReport}>Report a problem</Button>;
  return <Page title={TITLE} subtitle={SUBTITLE} actions={<>
    <Button variant="outline" icon={RefreshCw} loading={issues.loading && Boolean(data)} onClick={issues.reload}>Refresh</Button>
    <Button icon={Flag} onClick={onReport}>Report a problem</Button>
  </>}>
    <Card title="Your reports" subtitle={data ? `${rangeLabel(page, ISSUE_PAGE_SIZE, data.total)}, newest first.` : "Newest first."}>
      {state === "error" || state === "unauthorized"
        ? <ErrorState title="Could not load your reports" message={issues.error.message} onRetry={issues.reload} />
        : <DataTable loading={state === "loading"} caption="Problems you reported" columns={["Issue", "Status", "Severity", "Category", "Reported", "Last change"]}
          rowKeys={items.map(issue => issue.id)} rows={items.map(issue => [
            <IssueLink issue={issue} href={pathFor("myReports", issue.id)} onOpen={open} />,
            <IssueStatus status={issue.status} />,
            <IssueSeverity severity={issue.severity} />,
            categoryLabel(issue.category),
            <When value={issue.created_at} />,
            <When value={issue.updated_at} />
          ])}
          empty={<EmptyState icon={LifeBuoy} title="You have not reported anything"
            message="When something does not work, use Report a problem: it goes to the super admins with the page you were on." action={reportButton} />} />}
      <Pager label="Pages of your reports" page={page} pages={pageCount(data?.total || 0, ISSUE_PAGE_SIZE)} busy={issues.loading} onPage={setListPage} />
    </Card>
  </Page>;
}

function MyIssue({ issueId, setPage }) {
  const issue = useLoaded(() => getMyIssue(issueId), [issueId]);
  const data = issue.value;
  const back = <Button variant="outline" icon={ArrowLeft} onClick={() => setPage("myReports")}>All my reports</Button>;
  if (issue.error?.status === 404) {
    return <Page title={TITLE} subtitle={SUBTITLE} actions={back}><Card><IssueMissing action={<Button size="sm" variant="outline" onClick={() => setPage("myReports")}>Back to my reports</Button>} /></Card></Page>;
  }
  return <Page title={TITLE} subtitle={SUBTITLE} actions={<>
    {back}
    <Button variant="outline" icon={RefreshCw} loading={issue.loading && Boolean(data)} onClick={issue.reload}>Refresh</Button>
  </>}>
    {issue.error && <LoadFailed error={issue.error} onRetry={issue.reload} what="this report" />}
    {!data && !issue.error && <div className="grid gap-3" aria-busy="true"><Skeleton className="h-40 w-full" /><Skeleton className="h-28 w-full" /></div>}
    {data && <>
      <IssueSummary issue={data} />
      <Card title="Comments" subtitle="Between you and the super admins. A comment cannot be changed once it is sent.">
        <CommentThread comments={data.comments} />
        <div className="mt-5"><CommentForm issue={data} send={body => commentOnMyIssue(issueId, body)} onSent={issue.reload} /></div>
      </Card>
    </>}
  </Page>;
}
