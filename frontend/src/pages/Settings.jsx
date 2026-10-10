import React, { useEffect, useState } from "react";
import { Activity, LogOut, RefreshCw } from "lucide-react";
import { API_BASE_URL, getHealth } from "../lib/api";
import { Button, Card, Info, Page, Spinner, StatusBadge } from "../ui";

export default function SettingsPage({ data, logout }) {
  // The health check is a real request to the backend's /health endpoint.
  const [health, setHealth] = useState({ state: "checking" });
  const check = async () => {
    setHealth({ state: "checking" });
    try {
      const result = await getHealth();
      setHealth({ state: "ok", database: result?.database || "connected", at: new Date() });
    } catch (err) {
      setHealth({ state: "failed", error: err.message || "No answer from the backend.", at: new Date() });
    }
  };
  useEffect(() => { check(); }, []);
  const [reloading, setReloading] = useState(false);
  const reload = async () => { setReloading(true); await data.refresh(); setReloading(false); data.notify("Data reloaded."); };

  return <Page title="Settings" subtitle="Connection and system status.">
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <Card title="Backend connection" subtitle="The app talks to the FastAPI backend on this network." action={health.state === "checking" ? <Spinner label="Checking" /> : <StatusBadge status={health.state === "ok" ? "Online" : "Offline"} />}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Info label="API address" value={API_BASE_URL} />
          <Info label="Database" value={health.state === "ok" ? health.database : health.state === "failed" ? "Unknown" : "…"} />
          <Info label="Last checked" value={health.at ? health.at.toLocaleTimeString() : "…"} />
          <Info label="Data source" value="FastAPI backend only" />
        </div>
        {health.state === "failed" && <p className="mt-3 text-sm font-medium text-red-700" role="alert">{health.error} Start the backend, then check again.</p>}
        <Button variant="outline" className="mt-5" icon={Activity} loading={health.state === "checking"} onClick={check}>Check connection</Button>
      </Card>

      <Card title="Loaded data" subtitle="What this screen currently holds from the backend.">
        <div className="grid grid-cols-2 gap-3">
          <Info label="Courses" value={String(data.courses.length)} />
          <Info label="Batches" value={String(data.batches.length)} />
          <Info label="People" value={String(data.people.length)} />
          <Info label="Records today" value={String(data.records.length)} />
        </div>
        <Button variant="outline" className="mt-5" icon={RefreshCw} loading={reloading} onClick={reload}>Reload data</Button>
      </Card>

      <Card title="Set-up order" subtitle="Each step needs the one before it.">
        <ol className="grid gap-2 text-sm text-ink-soft">
          {["Create a course", "Create a batch under it", "Add students to the batch", "Enroll each student's face", "Start a session in the scanner"].map((step, index) => <li key={step} className="flex items-center gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-canvas text-xs font-bold text-ink">{index + 1}</span>{step}</li>)}
        </ol>
      </Card>

      <Card title="This device" subtitle="Signing out only affects this browser.">
        <p className="text-sm text-ink-muted">The camera needs an HTTPS address. On a phone, open the https link shown when the frontend starts and accept the certificate warning.</p>
        <Button variant="outline" className="mt-5 hover:border-red-200 hover:bg-red-50 hover:text-red-600" icon={LogOut} onClick={logout}>Log out</Button>
      </Card>
    </div>
  </Page>;
}
