import React, { useEffect, useId, useReducer, useRef, useState } from "react";
import { Copy, Edit3, KeyRound, Plus, Save, UserCheck, UserCog, UserX } from "lucide-react";
import { createAdmin, disableAdmin, enableAdmin, getAdmins, resetAdminPassword, updateAdmin } from "../../lib/api";
import { ROLE_LABELS } from "../../lib/auth";
import { BLANK_ADMIN, ROLE_OPTIONS, TEMPORARY_PASSWORD_HOURS, accountActions, adminFormErrors, adminPayload, adminQuery, changedFields, formFromAccount, secretReducer, viewState, whenText } from "../../lib/portal";
import { Button, Card, ConfirmDialog, DataTable, EmptyState, ErrorState, FormInput, FormSelect, IconButton, Identity, Notice, Page, SearchInput, Segmented, StatusBadge, overScreen } from "../../ui";
import { NotAllowed, useLoaded } from "./shared";

const STATUS_FILTERS = [{ value: "all", label: "All" }, { value: "active", label: "Active" }, { value: "disabled", label: "Disabled" }];
const ROLE_FILTERS = [{ value: "all", label: "All roles" }, { value: "super_admin", label: "Super admins" }, { value: "admin", label: "Admins" }];
const ACTION_BUTTON = "h-9 w-9 disabled:cursor-not-allowed disabled:opacity-40";

// The temporary password, on screen once. Closing this is the end of it: the page keeps no copy.
function TemporaryPassword({ secret, onCopied, onDone }) {
  const doneRef = useRef(null);
  const titleId = useId();
  useEffect(() => { doneRef.current?.focus(); }, []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret.password);
      onCopied();
    } catch {
      // No clipboard (a plain-http address, or permission refused): it can still be read off the screen.
    }
  };
  return overScreen(<div className="fixed inset-0 z-50 grid place-items-end p-3 sm:place-items-center">
    <div className="absolute inset-0 bg-ink/40 backdrop-blur-sm" aria-hidden="true" />
    <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="relative w-full max-w-md animate-sheet-up rounded-4xl bg-white p-6 shadow-float">
      <div className="grid h-11 w-11 place-items-center rounded-2xl bg-brand-50 text-brand-700"><KeyRound size={20} aria-hidden="true" /></div>
      <h3 id={titleId} className="mt-4 text-lg font-bold tracking-tight text-ink">{secret.why === "created" ? "Admin created" : "Password reset"}</h3>
      <p className="mt-1 text-sm text-ink-muted">Give this temporary password to <span className="font-semibold text-ink">{secret.email}</span>. They choose their own password when they first log in with it. It is shown only now: once this is closed it cannot be shown again.</p>
      <p className="mt-2 text-sm font-medium text-ink-soft">It works for {TEMPORARY_PASSWORD_HOURS} hours{secret.expires ? `, until ${whenText(secret.expires)}` : ""}. After that, reset the password again.</p>
      <div className="mt-4 flex items-center gap-2 rounded-2xl bg-canvas px-4 py-3">
        <code className="min-w-0 flex-1 select-all break-all font-mono text-base font-semibold tracking-wide text-ink">{secret.password}</code>
        <IconButton icon={Copy} label={secret.copied ? "Copied" : "Copy the password"} onClick={copy} />
      </div>
      {secret.copied && <p className="mt-2 text-xs font-medium text-emerald-700" role="status">Copied to the clipboard.</p>}
      <div className="mt-6 flex justify-end">
        <button ref={doneRef} type="button" className="btn btn-primary" onClick={onDone}>Done, I have passed it on</button>
      </div>
    </div>
  </div>);
}

function AdminEditor({ editor, me, owners, onChange, onSave, onCancel }) {
  const { mode, account, form, errors, saving } = editor;
  const role = account ? accountActions(account, me, owners).changeRole : { allowed: true };
  return <Card title={mode === "create" ? "Add an admin" : `Edit ${account.full_name}`} subtitle={mode === "create"
    ? "They get a temporary password, shown to you once, and choose their own when they first log in."
    : "A new role logs them out on every device, so that they come back with the pages of that role."}>
    <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_190px_auto]" onSubmit={onSave} noValidate>
      <FormInput autoFocus label="Full name" value={form.full_name} onChange={onChange("full_name")} error={errors.full_name} maxLength={160} autoComplete="off" required />
      <FormInput label="Email" type="email" value={form.email} onChange={onChange("email")} error={errors.email} maxLength={120} autoComplete="off" required />
      <FormSelect label="Role" value={form.role} onChange={onChange("role")} options={ROLE_OPTIONS} error={errors.role} disabled={!role.allowed} hint={role.allowed ? undefined : role.reason} />
      <div className="flex items-end gap-2 md:col-span-2 xl:col-span-1">
        <Button icon={mode === "create" ? Plus : Save} loading={saving}>{mode === "create" ? "Create" : "Save"}</Button>
        <Button type="button" variant="outline" onClick={onCancel} disabled={saving}>Cancel</Button>
      </div>
    </form>
  </Card>;
}

function StatusCell({ account }) {
  return <div className="flex flex-wrap gap-1.5">
    <StatusBadge status={account.status} tone={account.status === "disabled" ? "danger" : undefined} />
    {account.locked && <StatusBadge tone="warning">Locked out</StatusBadge>}
    {account.must_change_password && (account.temporary_password_expired
      ? <StatusBadge tone="danger">Temporary password expired</StatusBadge>
      : <StatusBadge tone="info">Temporary password</StatusBadge>)}
  </div>;
}

export default function AdminsPage({ account: me, notify }) {
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [role, setRole] = useState("all");
  useEffect(() => {
    const wait = setTimeout(() => setSearch(typed), 250);
    return () => clearTimeout(wait);
  }, [typed]);
  const query = adminQuery({ search, status, role });
  const list = useLoaded(() => getAdmins(query), [JSON.stringify(query)]);
  // The last-super-admin rule counts every active super admin, whatever the list is narrowed to.
  const owners = useLoaded(() => getAdmins({ role: "super_admin", status: "active" }), []);
  const [editor, setEditor] = useState(null);
  const [confirming, setConfirming] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [secret, dispatchSecret] = useReducer(secretReducer, null);

  const refresh = () => Promise.all([list.reload(), owners.reload()]);
  const fail = err => {
    if (err.status === 403) setForbidden(true);
    else setMessage(err.message || "That did not work. Try again.");
  };
  const change = field => event => setEditor(current => ({ ...current, form: { ...current.form, [field]: event.target.value }, errors: { ...current.errors, [field]: "" } }));
  const startCreate = () => { setEditor({ mode: "create", form: BLANK_ADMIN, errors: {}, saving: false }); setMessage(""); };
  const startEdit = account => {
    setEditor({ mode: "edit", account, form: formFromAccount(account), errors: {}, saving: false });
    setMessage("");
    scrollTo({ top: 0, behavior: "smooth" });
  };

  const save = async event => {
    event.preventDefault();
    if (!editor || editor.saving) return;
    const errors = adminFormErrors(editor.form);
    if (Object.keys(errors).length) { setEditor({ ...editor, errors }); return; }
    const changes = editor.mode === "edit" ? changedFields(editor.account, editor.form) : null;
    if (changes && !Object.keys(changes).length) { setEditor(null); return; }
    setEditor({ ...editor, saving: true });
    setMessage("");
    try {
      if (editor.mode === "create") {
        const result = await createAdmin(adminPayload(editor.form));
        dispatchSecret({ type: "shown", email: result.account.email, password: result.temporary_password, why: "created", expires: result.account.temporary_password_expires_at });
        notify("Admin created.");
      } else {
        await updateAdmin(editor.account.id, changes);
        notify(changes.role ? "Role changed. They have been logged out and log in again with the new role." : "Admin updated.");
      }
      setEditor(null);
      await refresh();
    } catch (err) {
      if (err.status === 409) setEditor(current => ({ ...current, saving: false, errors: { email: err.message } }));
      else {
        setEditor(current => current && { ...current, saving: false });
        fail(err);
        if (err.status === 404) { setEditor(null); refresh(); }
      }
    }
  };

  const act = async (kind, account) => {
    setBusy(true);
    setMessage("");
    try {
      if (kind === "disable") {
        await disableAdmin(account.id);
        notify(`${account.full_name} is disabled and logged out everywhere.`);
      } else if (kind === "enable") {
        await enableAdmin(account.id);
        notify(`${account.full_name} can log in again.`);
      } else {
        const result = await resetAdminPassword(account.id);
        dispatchSecret({ type: "shown", email: result.account.email, password: result.temporary_password, why: "reset", expires: result.account.temporary_password_expires_at });
      }
      await refresh();
    } catch (err) {
      fail(err);
      refresh();
    } finally {
      setBusy(false);
      setConfirming(null);
    }
  };

  const unauthorized = forbidden || list.error?.status === 403 || owners.error?.status === 403;
  const pageProps = { title: "Admins", subtitle: "Who can log in, and what they may do." };
  if (unauthorized) return <Page {...pageProps}><NotAllowed /></Page>;

  const state = viewState({ loading: list.loading, error: list.error, items: list.value });
  const filtered = Boolean(search || status !== "all" || role !== "all");
  const accounts = list.value || [];
  const rows = accounts.map(account => {
    const allowed = accountActions(account, me, owners.value || []);
    return [
      <Identity name={account.full_name} detail={`${account.email}${account.id === me.id ? " · you" : ""}`} />,
      <StatusBadge tone={account.role === "super_admin" ? "info" : "neutral"}>{ROLE_LABELS[account.role] || account.role}</StatusBadge>,
      <StatusCell account={account} />,
      account.last_login_at ? whenText(account.last_login_at) : "Never",
      <div className="flex gap-2">
        <IconButton icon={Edit3} label={`Edit ${account.full_name}`} onClick={() => startEdit(account)} className={ACTION_BUTTON} />
        <IconButton icon={KeyRound} label={`Reset the password of ${account.full_name}`} title={allowed.reset.reason || `Reset the password of ${account.full_name}`} disabled={!allowed.reset.allowed || busy} onClick={() => setConfirming({ kind: "reset", account })} className={ACTION_BUTTON} />
        {account.status === "active"
          ? <IconButton icon={UserX} label={`Disable ${account.full_name}`} title={allowed.disable.reason || `Disable ${account.full_name}`} disabled={!allowed.disable.allowed || busy} onClick={() => setConfirming({ kind: "disable", account })} className={`${ACTION_BUTTON} hover:border-red-200 hover:bg-red-50 hover:text-red-600`} />
          : <IconButton icon={UserCheck} label={`Enable ${account.full_name}`} disabled={busy} onClick={() => act("enable", account)} className={ACTION_BUTTON} />}
      </div>
    ];
  });

  return <Page {...pageProps} actions={!editor && <Button icon={Plus} onClick={startCreate}>Add admin</Button>}>
    {message && <Notice tone="danger" onClose={() => setMessage("")}>{message}</Notice>}
    {editor && <AdminEditor editor={editor} me={me} owners={owners.value || []} onChange={change} onSave={save} onCancel={() => setEditor(null)} />}
    <Card title="Accounts" subtitle={state === "ready" ? `${accounts.length} shown` : "Admins and super admins who can log in to the console."}>
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center">
        <SearchInput className="xl:w-72" value={typed} onChange={setTyped} placeholder="Search name or email" />
        <Segmented label="Status" value={status} onChange={setStatus} options={STATUS_FILTERS} />
        <Segmented label="Role" value={role} onChange={setRole} options={ROLE_FILTERS} />
      </div>
      {state === "error"
        ? <ErrorState title="Could not load the accounts" message={list.error.message} onRetry={refresh} />
        : <DataTable loading={state === "loading"} caption="Admin accounts" columns={["Admin", "Role", "Status", "Last login", "Actions"]} rows={rows}
          empty={filtered
            ? <EmptyState icon={UserCog} title="No account matches" message="Try another search, or show all statuses and roles." />
            : <EmptyState icon={UserCog} title="No accounts yet" message="Add the first admin with the button above." />} />}
    </Card>
    <ConfirmDialog open={confirming?.kind === "disable"} busy={busy} confirmLabel="Disable"
      title={`Disable ${confirming?.account.full_name}?`}
      message="They are logged out on every device at once, and cannot log in until the account is enabled again."
      onConfirm={() => act("disable", confirming.account)} onCancel={() => setConfirming(null)} />
    <ConfirmDialog open={confirming?.kind === "reset"} busy={busy} confirmLabel="Reset password"
      title={`Reset the password of ${confirming?.account.full_name}?`}
      message="Their current password stops working and they are logged out everywhere. You get a temporary password to give them; they choose their own when they log in with it."
      onConfirm={() => act("reset", confirming.account)} onCancel={() => setConfirming(null)} />
    {secret && <TemporaryPassword secret={secret} onCopied={() => dispatchSecret({ type: "copied" })} onDone={() => dispatchSecret({ type: "dismissed" })} />}
  </Page>;
}
