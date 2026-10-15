// The application shell: sidebar on large screens, a rounded bar at the bottom on phones and tablets.
import React, { useEffect, useRef, useState } from "react";
import { Flag, LogOut, MoreHorizontal, ScanLine, X } from "lucide-react";
import { ROLE_LABELS } from "./lib/auth";
import { badgeText } from "./lib/issues";
import { MOBILE_NAV, PAGES, PORTAL_MOBILE_NAV, isPortalPage, navEntry, navGroupsFor } from "./routes";
import { Button, ErrorState, Toast } from "./ui";

export function Brand({ compact }) {
  return <div className="flex min-w-0 items-center gap-3">
    <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-ink text-white shadow-card" aria-hidden="true">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 8V6a2 2 0 0 1 2-2h2" /><path d="M16 4h2a2 2 0 0 1 2 2v2" /><path d="M20 16v2a2 2 0 0 1-2 2h-2" /><path d="M8 20H6a2 2 0 0 1-2-2v-2" />
        <path d="m8.5 9.5 3.5 6 3.5-6" stroke="#6EA0FF" />
      </svg>
    </div>
    {!compact && <div className="min-w-0">
      <p className="truncate text-lg font-extrabold tracking-tight text-ink">Vernex</p>
      <p className="truncate text-[11px] font-medium text-ink-muted">Smart Attendance System</p>
    </div>}
  </div>;
}

// Who is signed in, above the sidebar's Log out button.
function SignedInAs({ account, className = "" }) {
  return <div className={`min-w-0 ${className}`}>
    <p className="truncate text-sm font-semibold text-ink">{account.full_name}</p>
    <p className="truncate text-[11px] font-medium text-ink-muted">{ROLE_LABELS[account.role] || account.role} · {account.email}</p>
  </div>;
}

// The number next to a navigation entry (the portal's open issues). Nothing when there is none.
function CountBadge({ count, active, className = "" }) {
  const text = badgeText(count);
  if (!text) return null;
  return <span className={`inline-flex h-5 min-w-[1.25rem] shrink-0 items-center justify-center rounded-full px-1.5 text-[11px] font-bold tabular-nums ${active ? "bg-white text-ink" : "bg-red-600 text-white"} ${className}`}>
    {text}<span className="sr-only"> open</span>
  </span>;
}

function SidebarItem({ id, page, setPage, badges }) {
  const { label, icon: Icon } = navEntry(id, isPortalPage(page));
  const active = page === id;
  return <button type="button" aria-current={active ? "page" : undefined} onClick={() => setPage(id)} className={`group flex h-11 w-full items-center gap-3 rounded-full px-3.5 text-left text-sm font-semibold transition duration-150 ${active ? "bg-ink text-white shadow-card" : "text-ink-muted hover:bg-canvas hover:text-ink"}`}>
    <Icon size={18} className={active ? "" : "transition-transform duration-150 group-hover:scale-110"} aria-hidden="true" />
    <span className="truncate">{label}</span>
    <CountBadge count={badges?.[id]} active={active} className="ml-auto" />
  </button>;
}

// Says, under the logo, that this is the portal and not the console.
function PortalMark() {
  return <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-brand-700 ring-1 ring-inset ring-brand-600/15">Super Admin portal</p>;
}

function Sidebar({ page, setPage, logout, account, badges }) {
  return <aside className="fixed inset-y-3 left-3 z-30 hidden w-[264px] flex-col rounded-4xl border border-white/70 bg-white/80 p-4 shadow-card backdrop-blur-xl lg:flex">
    <div className="px-2 pt-2"><Brand />{isPortalPage(page) && <PortalMark />}</div>
    <nav aria-label="Main" className="mt-6 flex-1 space-y-5 overflow-y-auto pr-1">
      {navGroupsFor(account.role, page).map(group => <div key={group.label}>
        <p className="mb-1.5 px-3.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group.label}</p>
        <div className="grid gap-1">{group.items.map(id => <SidebarItem key={id} id={id} page={page} setPage={setPage} badges={badges} />)}</div>
      </div>)}
    </nav>
    <SignedInAs account={account} className="mt-3 border-t border-line px-3.5 pt-3" />
    <button type="button" className="mt-2 flex h-11 items-center gap-3 rounded-full px-3.5 text-sm font-semibold text-ink-muted transition duration-150 hover:bg-red-50 hover:text-red-600" onClick={logout}><LogOut size={18} aria-hidden="true" />Log out</button>
  </aside>;
}

function ClockBox() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <div className="hidden shrink-0 text-right sm:block">
    <p className="text-sm font-bold tabular-nums text-ink">{now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</p>
    <p className="text-[11px] font-medium text-ink-muted">{now.toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short", year: "numeric" })}</p>
  </div>;
}

// Says what the app really knows about the backend: still loading, last load failed, or loaded.
function ConnectionPill({ data }) {
  const state = data.loading ? { text: "Connecting", dot: "bg-amber-500 animate-pulse" } : data.error ? { text: "Backend offline", dot: "bg-red-500" } : { text: "Backend online", dot: "bg-emerald-500" };
  return <span className="inline-flex h-9 shrink-0 items-center gap-2 rounded-full border border-line bg-white px-3 text-xs font-semibold text-ink-soft" role="status">
    <span className={`h-2 w-2 rounded-full ${state.dot}`} aria-hidden="true" />{state.text}
  </span>;
}

function Topbar({ page, data, onReport }) {
  const meta = PAGES[page] || PAGES.dashboard;
  return <header className="sticky top-0 z-20 px-3 pt-3 lg:px-6">
    <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 rounded-full border border-white/70 bg-white/75 pl-3 pr-4 shadow-card backdrop-blur-xl lg:pl-6">
      <div className="flex min-w-0 items-center gap-3">
        <div className="lg:hidden"><Brand compact /></div>
        <div className="min-w-0">
          <p className="hidden truncate text-[11px] font-medium text-ink-muted sm:block">Vernex <span aria-hidden="true">/</span> {isPortalPage(page) && page !== "superAdmin" ? <>Super Admin <span aria-hidden="true">/</span> </> : null}{meta.label}</p>
          <h1 className="truncate text-base font-bold tracking-tight text-ink">{meta.title}</h1>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {/* On every page, in the header on large screens; phones and tablets have it under "More". */}
        <Button size="sm" variant="outline" icon={Flag} className="hidden lg:inline-flex" onClick={onReport}>Report a problem</Button>
        <ConnectionPill data={data} />
        <ClockBox />
      </div>
    </div>
  </header>;
}

function MobileItem({ id, page, setPage, badges }) {
  const { label, icon: Icon } = navEntry(id, isPortalPage(page));
  const active = page === id;
  const count = badgeText(badges?.[id]);
  return <button type="button" aria-current={active ? "page" : undefined} aria-label={count ? `${label}, ${count} open` : label} onClick={() => setPage(id)} className={`relative flex h-12 items-center justify-center gap-2 rounded-full text-[13px] font-semibold transition-all duration-200 ${active ? "bg-ink px-4 text-white" : "w-12 text-ink-muted hover:text-ink"}`}>
    <Icon size={20} aria-hidden="true" />
    {active && <span className="max-w-[5.5rem] truncate">{label.split(" ").pop()}</span>}
    <span aria-hidden="true" className={active ? "" : "absolute -right-0.5 -top-0.5"}><CountBadge count={badges?.[id]} active={active} /></span>
  </button>;
}

function MoreSheet({ page, setPage, logout, account, onClose, onReport, badges }) {
  const closeRef = useRef(null);
  useEffect(() => {
    closeRef.current?.focus();
    const onKey = event => { if (event.key === "Escape") onClose(); };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  const go = id => { setPage(id); onClose(); };
  const portal = isPortalPage(page);
  return <div className="fixed inset-0 z-50 lg:hidden">
    <button type="button" className="absolute inset-0 cursor-default bg-ink/40 backdrop-blur-sm" onClick={onClose} aria-label="Close menu" tabIndex={-1} />
    <div role="dialog" aria-modal="true" aria-label="All pages" className="absolute inset-x-3 bottom-3 max-h-[80vh] animate-sheet-up overflow-y-auto rounded-4xl bg-white p-5 shadow-float">
      <div className="flex items-center justify-between">
        <div><Brand />{portal && <PortalMark />}</div>
        <button ref={closeRef} type="button" className="icon-btn" onClick={onClose} aria-label="Close menu"><X size={17} aria-hidden="true" /></button>
      </div>
      <nav aria-label="All pages" className="mt-5 space-y-4">
        {navGroupsFor(account.role, page).map(group => <div key={group.label}>
          <p className="mb-1.5 px-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group.label}</p>
          <div className="grid grid-cols-2 gap-2">
            {group.items.map(id => {
              const { label, icon: Icon } = navEntry(id, portal);
              const active = page === id;
              return <button key={id} type="button" aria-current={active ? "page" : undefined} onClick={() => go(id)} className={`flex h-12 items-center gap-2.5 rounded-2xl px-3.5 text-left text-sm font-semibold transition duration-150 ${active ? "bg-ink text-white" : "bg-canvas text-ink-soft hover:bg-slate-200/70"}`}>
                <Icon size={17} aria-hidden="true" /><span className="truncate">{label}</span><CountBadge count={badges?.[id]} active={active} className="ml-auto" />
              </button>;
            })}
          </div>
        </div>)}
      </nav>
      <button type="button" className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-2xl border border-line bg-white px-4 text-sm font-semibold text-ink transition duration-150 hover:bg-canvas" onClick={() => { onClose(); onReport(); }}>
        <Flag size={17} aria-hidden="true" />Report a problem
      </button>
      {/* Who is signed in goes inside the button: a line of its own would push Log out off a phone's screen. */}
      <button type="button" className="mt-2 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-red-50 px-4 text-sm font-semibold text-red-600" onClick={logout}><LogOut size={17} className="shrink-0" aria-hidden="true" /><span className="shrink-0">Log out</span><span className="truncate font-medium text-red-600/70">· {account.full_name} ({ROLE_LABELS[account.role] || account.role})</span></button>
    </div>
  </div>;
}

function MobileNav({ page, setPage, logout, account, onReport, badges }) {
  const [more, setMore] = useState(false);
  const bar = isPortalPage(page) ? PORTAL_MOBILE_NAV : MOBILE_NAV;
  const inBar = [...bar.left, bar.center, ...bar.right].includes(page);
  const scanning = page === bar.center;
  return <>
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex justify-center px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] lg:hidden">
      <div className="flex h-[68px] w-full max-w-md items-center justify-between gap-1 rounded-full border border-white/70 bg-white/85 px-2.5 shadow-float backdrop-blur-xl">
        {bar.left.map(id => <MobileItem key={id} id={id} page={page} setPage={setPage} badges={badges} />)}
        {bar.center && <button type="button" aria-current={scanning ? "page" : undefined} aria-label={PAGES[bar.center].label} onClick={() => setPage(bar.center)} className={`grid h-14 w-14 shrink-0 place-items-center rounded-full bg-brand-600 text-white shadow-brand transition duration-200 active:scale-95 ${scanning ? "ring-4 ring-brand-200" : ""}`}>
          <ScanLine size={24} aria-hidden="true" />
        </button>}
        {bar.right.map(id => <MobileItem key={id} id={id} page={page} setPage={setPage} badges={badges} />)}
        <button type="button" aria-label="More pages" aria-haspopup="dialog" onClick={() => setMore(true)} className={`flex h-12 items-center justify-center gap-2 rounded-full text-[13px] font-semibold transition-all duration-200 ${!inBar ? "bg-ink px-4 text-white" : "w-12 text-ink-muted hover:text-ink"}`}>
          <MoreHorizontal size={20} aria-hidden="true" />{!inBar && <span className="max-w-[5.5rem] truncate">{PAGES[page]?.label.split(" ").pop()}</span>}
        </button>
      </div>
    </nav>
    {more && <MoreSheet page={page} setPage={setPage} logout={logout} account={account} onClose={() => setMore(false)} onReport={onReport} badges={badges} />}
  </>;
}

// onReport(): opens "Report a problem". badges: { pageId: count } shown next to those entries.
export function Shell({ children, page, setPage, logout, data, account, onReport, badges }) {
  return <div className="min-h-screen bg-canvas text-ink">
    {/* A faint tint behind everything, so the glass surfaces have something to sit on. */}
    <div className="pointer-events-none fixed inset-0 -z-0 bg-[radial-gradient(60rem_30rem_at_85%_-10%,rgba(59,123,255,.10),transparent),radial-gradient(40rem_24rem_at_0%_100%,rgba(59,123,255,.06),transparent)]" aria-hidden="true" />
    <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white">Skip to content</a>
    <Sidebar page={page} setPage={setPage} logout={logout} account={account} badges={badges} />
    <div className="relative min-w-0 lg:pl-[282px]">
      <Topbar page={page} data={data} onReport={onReport} />
      <main id="main" className="mx-auto w-full max-w-6xl px-3 pb-32 pt-5 sm:px-4 lg:px-6 lg:pb-10">
        {data.error && <div className="mb-5"><ErrorState title="Cannot reach the backend" message={`${data.error} Check that the backend is running, then try again.`} onRetry={data.refresh} /></div>}
        {children}
      </main>
    </div>
    <MobileNav page={page} setPage={setPage} logout={logout} account={account} onReport={onReport} badges={badges} />
    <Toast toast={data.toast} onClose={data.dismissToast} />
  </div>;
}
