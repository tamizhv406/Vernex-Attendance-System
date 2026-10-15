import React, { useState } from "react";
import { ArrowRight, ScanFace, ShieldCheck, Users } from "lucide-react";
import { Brand } from "../layout";
import { session } from "../lib/api";
import { UNREACHABLE } from "../lib/auth";
import { Button, FormInput, Notice } from "../ui";

// The email and password are checked by the backend. This page keeps neither of them; what it gets
// back is a session, and the app opens when there is one. notice: why the last session is over, if it is.
export default function Login({ notice }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async event => {
    event.preventDefault();
    if (busy) return;
    if (!email.trim() || !password) { setError("Enter your email and your password."); return; }
    setBusy(true);
    setError("");
    try {
      await session.login(email.trim(), password);
    } catch (err) {
      // A refusal comes in the backend's own words (wrong password, locked, too many attempts).
      // An error without a status means the backend was never reached.
      setError(err.status ? err.message : UNREACHABLE);
      setPassword("");
      setBusy(false);
    }
  };
  return <main className="relative grid min-h-screen place-items-center bg-canvas p-4">
    <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(50rem_28rem_at_80%_0%,rgba(59,123,255,.14),transparent),radial-gradient(40rem_24rem_at_10%_100%,rgba(59,123,255,.08),transparent)]" aria-hidden="true" />
    <div className="relative grid w-full max-w-4xl animate-fade-up overflow-hidden rounded-4xl border border-white/70 bg-white/80 shadow-float backdrop-blur-xl md:grid-cols-2">
      <section className="p-7 sm:p-10">
        <Brand />
        <div className="mt-10">
          <h1 className="text-3xl font-extrabold tracking-tight text-ink">Welcome back</h1>
          <p className="mt-2 text-sm text-ink-muted">Sign in to the attendance console for your institute.</p>
        </div>
        <form className="mt-8 grid gap-4" onSubmit={submit} noValidate>
          {error ? <Notice tone="danger">{error}</Notice> : notice ? <Notice tone="info">{notice}</Notice> : null}
          <FormInput label="Email" type="email" inputMode="email" placeholder="name@example.com" autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus value={email} onChange={event => setEmail(event.target.value)} />
          <FormInput label="Password" placeholder="Enter password" type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} />
          <Button loading={busy} className="mt-2 h-12">Log in<ArrowRight size={16} aria-hidden="true" /></Button>
        </form>
      </section>
      <aside className="hidden flex-col justify-between bg-ink p-10 text-white md:flex">
        <p className="text-xs font-semibold uppercase tracking-wider text-white/50">AI-powered smart attendance</p>
        <ul className="grid gap-5">
          <Feature icon={Users} title="Courses, batches, students">Everyone organised the way your institute already works.</Feature>
          <Feature icon={ScanFace} title="Guided face enrollment">A few poses, checked for light and sharpness as they are taken.</Feature>
          <Feature icon={ShieldCheck} title="Verified before it is marked">Attendance is written by the backend, one record per person and session.</Feature>
        </ul>
        <p className="text-xs text-white/40">Runs on your own network.</p>
      </aside>
    </div>
  </main>;
}

function Feature({ icon: Icon, title, children }) {
  return <li className="flex gap-4">
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-white/10 text-brand-200"><Icon size={19} aria-hidden="true" /></span>
    <span><span className="block font-semibold">{title}</span><span className="mt-0.5 block text-sm text-white/60">{children}</span></span>
  </li>;
}
