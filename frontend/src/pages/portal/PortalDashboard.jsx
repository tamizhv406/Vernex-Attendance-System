import React from "react";
import { CalendarCheck, CheckCircle2, History, KeyRound, Lock, MessageSquareWarning, RefreshCw, UserCog, UserX } from "lucide-react";
import { getPortalDashboard } from "../../lib/api";
import { actorText, expiredTemporaryPasswordHelp, targetText, whenText } from "../../lib/portal";
import { Button, Card, EmptyState, Notice, Page, Skeleton, StatCard } from "../../ui";
import { LoadFailed, NotAllowed, useLoaded } from "./shared";

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;

function RecentActivity({ entries, loading, setPage }) {
  if (loading) return <div className="grid gap-2" aria-busy="true">{[0, 1, 2].map(index => <Skeleton key={index} className="h-12 w-full" />)}</div>;
  if (!entries.length) return <EmptyState icon={History} title="Nothing recorded yet" message="Logins, account changes, deletions and uploads appear here as they happen." />;
  return <ol className="divide-y divide-line overflow-hidden rounded-2xl border border-line bg-white">
    {entries.map(entry => <li key={entry.id} className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-ink">{entry.action_label}<span className="font-normal text-ink-muted"> · {targetText(entry)}</span></p>
        <p className="truncate text-xs text-ink-muted">{actorText(entry)}</p>
      </div>
      <time dateTime={entry.created_at} className="shrink-0 text-xs font-medium tabular-nums text-ink-muted">{whenText(entry.created_at)}</time>
    </li>)}
    <li className="px-4 py-3"><Button size="sm" variant="outline" icon={History} onClick={() => setPage("portalAudit")}>Open the audit log</Button></li>
  </ol>;
}

export default function PortalDashboard({ setPage }) {
  const { loading, error, value, reload } = useLoaded(getPortalDashboard, []);
  const waiting = loading && !value;
  if (error?.status === 403) return <Page title="Super Admin" subtitle="Accounts, activity and today's numbers."><NotAllowed /></Page>;
  const admins = value?.admins;
  const today = value?.attendance_today;
  const expired = expiredTemporaryPasswordHelp(admins?.temporary_password_expired);
  return <Page title="Super Admin" subtitle="Accounts, activity and today's numbers." actions={<Button variant="outline" icon={RefreshCw} loading={loading && Boolean(value)} onClick={reload}>Refresh</Button>}>
    {error && <LoadFailed error={error} onRetry={reload} what="the dashboard" />}
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard icon={UserCog} accent label="Active admins" loading={waiting} value={admins ? admins.active : "-"} detail={admins ? `${plural(admins.active_super_admins, "super admin")}, ${plural(admins.active_admins, "admin")}` : ""} />
      <StatCard icon={CalendarCheck} label="Attendance today" loading={waiting} value={today ? today.total : "-"} detail={today ? `${today.present} present · ${today.late} late · ${today.absent} absent` : ""} />
      <StatCard icon={MessageSquareWarning} label="Open issues" value="–" detail="Comes with issue reporting" />
      <StatCard icon={CheckCircle2} label="Resolved this week" value="–" detail="Comes with issue reporting" />
    </div>
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <StatCard icon={UserX} label="Disabled accounts" loading={waiting} value={admins ? admins.disabled : "-"} />
      <StatCard icon={KeyRound} label="Waiting for a first login" loading={waiting} value={admins ? admins.must_change_password : "-"}
        detail={expired ? expired.detail : "Still on a temporary password"} />
      <StatCard icon={Lock} label="Locked out now" loading={waiting} value={admins ? admins.locked : "-"} detail="Too many wrong passwords" />
    </div>
    {expired && <Notice tone="warning">{expired.notice}</Notice>}
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
      <Card title="Recent activity" subtitle="The newest entries of the audit log.">
        <RecentActivity entries={value?.recent_activity || []} loading={waiting} setPage={setPage} />
      </Card>
      <Card title="Newest open issues" subtitle="Problems admins report from the console.">
        <EmptyState icon={MessageSquareWarning} title="Issue reporting is not built yet" message="When it is, the newest open issues appear here, with links to each one." action={<Button size="sm" variant="outline" onClick={() => setPage("portalIssues")}>About issues</Button>} />
      </Card>
    </div>
  </Page>;
}
