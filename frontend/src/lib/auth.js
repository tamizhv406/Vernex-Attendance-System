// Who is signed in, and keeping them signed in. Kept apart from the screens and from fetch so that
// it can be tested (auth.test.js).
//
// The access token lives in this module's memory and nowhere else: not in localStorage, not in a
// cookie the page can read. A reload starts without one, and the refresh cookie, which scripts
// cannot read at all, gets a new one from the backend.

export const ROLE_LABELS = { super_admin: "Super admin", admin: "Admin" };
export const SESSION_ENDED = "Your session has ended. Log in again.";
export const UNREACHABLE = "Could not reach the server. Check that the backend is running, then try again.";
export const PASSWORD_CHANGED = "Password changed. Log in with your new password.";
export const MIN_PASSWORD_LENGTH = 10;
export const MAX_PASSWORD_LENGTH = 128;
export const LOGOUT_UNREACHABLE = "Logged out on this device. The server could not be reached, so its side of the session ends on its own later.";
export const LOGOUT_UNCONFIRMED = "Logged out on this device. The server did not confirm it, so its side of the session ends on its own later.";
// After this long without a click, a key or a touch the console logs out (task S-16). A running
// scanner keeps it awake: a camera left on a desk during a class is not an abandoned console.
export const IDLE_MINUTES = 30;
export const IDLE_ENDED = `You were logged out after ${IDLE_MINUTES} minutes without activity. Log in again.`;
// Sent with the requests that work on the refresh cookie alone. The backend refuses those without
// it: another page can make the browser send the cookie, but it cannot add a header of its own.
export const CLIENT_HEADERS = { "X-Requested-With": "vernex" };

function refusal(answer, payload, fallback) {
  const error = new Error(typeof payload?.detail === "string" ? payload.detail : payload?.message || fallback);
  error.status = answer.status;
  error.payload = payload;
  return error;
}

// send(path, { method, body, token }) does one HTTP exchange and resolves to { status, json() };
// it rejects only when the server cannot be reached. remember keeps one yes/no between page loads:
// whether this browser was signed in, so that a visitor who never was is not asked about.
export function createSession({ send, remember = { get: () => true, set: () => {} }, setTimer = setTimeout, clearTimer = clearTimeout, now = () => Date.now(), idleLimit = IDLE_MINUTES * 60000 }) {
  let token = null;
  // The last time the person did something here, when the token is due for renewal, and what is
  // keeping the console awake (the scanner while a session runs).
  let lastActive = now();
  let renewDue = 0;
  const awake = new Set();
  let account = null;
  let state = "checking";
  let notice = "";
  let timer = null;
  let renewing = null;
  // Goes up each time the session is dropped. A renewal answered after that (it was on its way when
  // the person logged out or changed the password) belongs to the session that has ended.
  let generation = 0;
  const listeners = new Set();
  // What the screens are given: { state: "checking" | "in" | "out", account, notice }. The same
  // object until something changes, and never the token.
  let view = { state, account, notice };

  const snapshot = () => view;
  const publish = () => {
    view = { state, account, notice };
    listeners.forEach(listener => listener(view));
  };

  function accept(data) {
    token = data.access_token;
    account = data.account;
    state = "in";
    notice = "";
    remember.set(true);
    // Renewed a minute before it runs out, so that a scanner sending frames never meets a refusal.
    // (A token shorter than five minutes: when four fifths of it are gone. Never sooner than 5 seconds.)
    const seconds = Number(data.expires_in) || 900;
    const wait = Math.max(5, seconds - 60, seconds * 0.8) * 1000;
    renewDue = now() + wait;
    arm(wait);
    publish();
  }

  function idleFor() {
    return awake.size ? 0 : now() - lastActive;
  }

  // One timer: it goes off for the renewal, or earlier if the console would by then have been idle
  // for too long. Activity since it was set only means it is set again.
  function arm(wait) {
    clearTimer(timer);
    const idleLeft = idleLimit > 0 && !awake.size ? idleLimit - idleFor() : Infinity;
    const forRenewal = wait <= idleLeft;
    timer = setTimer(() => wake(forRenewal), forRenewal ? wait : Math.max(1000, idleLeft));
  }

  function wake(forRenewal) {
    if (state !== "in") return;
    if (idleLimit > 0 && idleFor() >= idleLimit) {
      endIdle();
      return;
    }
    if (forRenewal) {
      renew().catch(() => {});
      return;
    }
    // Set for the idle limit, but there was activity since: wait for whichever comes next.
    arm(Math.max(0, renewDue - now()));
  }

  async function endIdle() {
    drop(IDLE_ENDED);
    // The server's side of the login is ended too; if it cannot be reached it ends on its own later.
    try { await send("/auth/logout", { method: "POST", headers: CLIENT_HEADERS }); } catch { /* ended on this device anyway */ }
  }

  function drop(why = "", keepHint = false) {
    generation += 1;
    renewing = null;
    token = null;
    account = null;
    state = "out";
    notice = why;
    clearTimer(timer);
    timer = null;
    if (!keepHint) remember.set(false);
    publish();
  }

  // One renewal at a time, however many requests ask for it at the same moment.
  // Resolves to "renewed", "ended" (the login is over) or "unavailable" (the server had a problem).
  function renew() {
    if (!renewing) {
      const started = generation;
      renewing = (async () => {
        try {
          const answer = await send("/auth/refresh", { method: "POST", headers: CLIENT_HEADERS });
          const payload = await answer.json();
          // Logged out while this was on its way: whatever the answer says, it opens nothing.
          if (started !== generation) return "ended";
          if (answer.status === 200 && payload?.data?.access_token) {
            accept(payload.data);
            return "renewed";
          }
          if (answer.status === 401 || answer.status === 403) {
            drop(state === "in" ? SESSION_ENDED : "");
            return "ended";
          }
          return "unavailable";
        } finally {
          // A drop has already let go of it, and a newer renewal may have started since.
          if (started === generation) renewing = null;
        }
      })();
    }
    return renewing;
  }

  return {
    snapshot,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    // On page load: is this browser still signed in?
    async restore() {
      if (!remember.get()) {
        drop("");
        return snapshot();
      }
      try {
        if (await renew() === "unavailable") drop(UNREACHABLE, true);
      } catch {
        // Not reachable is not the same as signed out: the next load asks again.
        drop(UNREACHABLE, true);
      }
      return snapshot();
    },

    // Called on every click, key and touch in the console.
    touch() {
      lastActive = now();
    },

    // keepAwake("scanner", true) while a scanning session runs; false when it stops.
    keepAwake(reason, on) {
      if (on) awake.add(reason);
      else if (awake.delete(reason)) lastActive = now();
    },

    async login(email, password) {
      const answer = await send("/auth/login", { method: "POST", body: { email, password }, headers: CLIENT_HEADERS });
      const payload = await answer.json();
      if (answer.status !== 200 || !payload?.data?.access_token) throw refusal(answer, payload, "Unable to log in.");
      lastActive = now();
      accept(payload.data);
      return snapshot();
    },

    async logout() {
      // This device is logged out whatever happens. Only a 200 means the server ended its side too.
      let notice = "";
      try {
        const answer = await send("/auth/logout", { method: "POST", headers: CLIENT_HEADERS });
        if (answer.status !== 200) notice = LOGOUT_UNCONFIRMED;
      } catch {
        notice = LOGOUT_UNREACHABLE;
      }
      drop(notice);
    },

    async changePassword(currentPassword, newPassword) {
      const answer = await this.call("/auth/change-password", { method: "POST", body: { current_password: currentPassword, new_password: newPassword } });
      const payload = await answer.json();
      if (answer.status !== 200) throw refusal(answer, payload, "Unable to change the password.");
      // Every login of the account has ended on the server, this one included.
      drop(PASSWORD_CHANGED);
    },

    // A request made as whoever is signed in. If the access token has run out it is renewed once
    // and the request repeated; if the login itself is over, the app goes back to the login page.
    async call(path, options = {}) {
      let answer = await send(path, { ...options, token });
      if (answer.status !== 401 || state !== "in") return answer;
      const outcome = await renew();
      if (outcome !== "renewed") return answer;
      answer = await send(path, { ...options, token });
      if (answer.status === 401 && state === "in") drop(SESSION_ENDED);
      return answer;
    }
  };
}

// ---- which screen an account gets --------------------------------------------------------------

export function mayOpen(roles, role) {
  return !roles || roles.includes(role);
}

export function homeFor(role) {
  return role === "super_admin" ? "superAdmin" : "dashboard";
}

// pages: { id: { roles?: [...] } }. Returns what to show for the page somebody asked for.
export function screenFor({ state, account, page, pages }) {
  if (state === "checking") return { screen: "checking" };
  if (state !== "in" || !account) return { screen: "login" };
  // A temporary password opens one page only, whatever address was typed.
  if (account.must_change_password) return { screen: "change-password" };
  if (!pages[page]) return { screen: "page", page: homeFor(account.role) };
  if (!mayOpen(pages[page].roles, account.role)) return { screen: "not-allowed", page };
  return { screen: "page", page };
}

// Where to go after logging in: the page that was asked for if this account may open it, else home.
export function landingPage({ wanted, account, pages }) {
  return wanted && pages[wanted] && mayOpen(pages[wanted].roles, account.role) ? wanted : homeFor(account.role);
}

export function visibleGroups(groups, pages, role) {
  return groups
    .map(group => ({ ...group, items: group.items.filter(id => mayOpen(pages[id]?.roles, role)) }))
    .filter(group => group.items.length > 0);
}

// What is wrong with a new password, or "". The backend applies these rules too, and refuses the
// most commonly used passwords as well.
export function passwordProblem(password, email = "") {
  if (password.length < MIN_PASSWORD_LENGTH) return `Use at least ${MIN_PASSWORD_LENGTH} characters.`;
  if (password.length > MAX_PASSWORD_LENGTH) return `Use at most ${MAX_PASSWORD_LENGTH} characters.`;
  if (email && password.trim().toLowerCase() === email.trim().toLowerCase()) return "The password must not be your email address.";
  return "";
}
