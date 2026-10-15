import React, { useState } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { Brand } from "../layout";
import { session } from "../lib/api";
import { MIN_PASSWORD_LENGTH, UNREACHABLE, passwordProblem } from "../lib/auth";
import { Button, Card, FormInput, Notice, Page } from "../ui";

// The three fields and what happens when they are sent. Changing the password ends every login of
// the account, this one included, so a successful change leads back to the login page.
function usePasswordForm(account) {
  const [form, setForm] = useState({ current: "", next: "", repeat: "" });
  const [errors, setErrors] = useState({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const change = field => event => {
    const value = event.target.value;
    setForm(now => ({ ...now, [field]: value }));
    setErrors(({ [field]: _fixed, ...rest }) => rest);
  };
  const submit = async event => {
    event.preventDefault();
    if (busy) return;
    const problems = {};
    if (!form.current) problems.current = "Enter your current password.";
    const weak = passwordProblem(form.next, account.email);
    if (weak) problems.next = weak;
    else if (form.next === form.current) problems.next = "The new password must be different from the current one.";
    else if (form.repeat !== form.next) problems.repeat = "The two passwords are not the same.";
    if (Object.keys(problems).length) { setErrors(problems); return; }
    setBusy(true);
    setMessage("");
    try {
      await session.changePassword(form.current, form.next);
    } catch (err) {
      // What the backend refused is said under the field it is about.
      if (!err.status) setMessage(UNREACHABLE);
      else if (err.status === 400 && /current password/i.test(err.message)) setErrors({ current: err.message });
      else if (err.status === 400) setErrors({ next: err.message });
      else setMessage(err.message);
      setBusy(false);
    }
  };
  return { form, errors, message, busy, change, submit };
}

function Fields({ state }) {
  const { form, errors, change } = state;
  return <>
    <FormInput label="Current password" type="password" autoComplete="current-password" value={form.current} onChange={change("current")} error={errors.current} required autoFocus />
    <FormInput label="New password" type="password" autoComplete="new-password" value={form.next} onChange={change("next")} error={errors.next} hint={`At least ${MIN_PASSWORD_LENGTH} characters. Not your email, and not a common password.`} required />
    <FormInput label="New password again" type="password" autoComplete="new-password" value={form.repeat} onChange={change("repeat")} error={errors.repeat} required />
  </>;
}

// Shown instead of the whole app while an account still has a temporary password.
export function ForcedPasswordChange({ account, logout }) {
  const state = usePasswordForm(account);
  return <main className="relative grid min-h-screen place-items-center bg-canvas p-4">
    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(50rem_28rem_at_80%_0%,rgba(59,123,255,.14),transparent),radial-gradient(40rem_24rem_at_10%_100%,rgba(59,123,255,.08),transparent)]" aria-hidden="true" />
    <section className="relative w-full max-w-md animate-fade-up rounded-4xl border border-white/70 bg-white/80 p-7 shadow-float backdrop-blur-xl sm:p-10">
      <Brand />
      <div className="mt-8">
        <h1 className="text-2xl font-extrabold tracking-tight text-ink">Choose a new password</h1>
        <p className="mt-2 text-sm text-ink-muted">{account.full_name}, your account has a temporary password. Replace it to continue. You will log in again with the new one.</p>
      </div>
      <form className="mt-6 grid gap-4" onSubmit={state.submit} noValidate>
        {state.message && <Notice tone="danger">{state.message}</Notice>}
        <Fields state={state} />
        <Button icon={KeyRound} loading={state.busy} className="mt-2 h-12">Save new password</Button>
        <Button type="button" variant="outline" icon={LogOut} onClick={logout} disabled={state.busy}>Log out</Button>
      </form>
    </section>
  </main>;
}

// The same form as a page of the console, opened from Settings.
export default function ChangePasswordPage({ account, onCancel }) {
  const state = usePasswordForm(account);
  return <Page title="Change password" subtitle="Choose a new password for this account.">
    {state.message && <Notice tone="danger">{state.message}</Notice>}
    <Card title={account.email} subtitle="Changing the password logs this account out on every device. You then log in again with the new one." className="max-w-xl">
      <form className="grid gap-4" onSubmit={state.submit} noValidate>
        <Fields state={state} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={onCancel} disabled={state.busy}>Cancel</Button>
          <Button icon={KeyRound} loading={state.busy}>Save new password</Button>
        </div>
      </form>
    </Card>
  </Page>;
}
