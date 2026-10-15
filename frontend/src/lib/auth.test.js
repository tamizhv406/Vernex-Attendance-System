// Run with `npm test`. The session rules the app follows: logging in, staying in, being sent back
// to the login page, and which page an account may open. api.js builds its session from exactly
// this code, with fetch as the "send" and one yes/no in localStorage as the "remember".
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { CLIENT_HEADERS, IDLE_ENDED, LOGOUT_UNCONFIRMED, PASSWORD_CHANGED, SESSION_ENDED, UNREACHABLE, createSession, homeFor, landingPage, mayOpen, passwordProblem, screenFor, visibleGroups } from "./auth.js";

const ASHA = { id: 1, email: "asha@example.com", full_name: "Asha Example", role: "admin", must_change_password: false };
const OWNER = { ...ASHA, id: 2, email: "owner@example.com", role: "super_admin" };
const signedIn = (token = "token-1", account = ASHA, expires_in = 900) => ({ status: 200, body: { success: true, data: { access_token: token, token_type: "bearer", expires_in, account } } });
const refused = (status, detail) => ({ status, body: { detail } });
const offline = () => new TypeError("Failed to fetch");

// A backend that answers from a script and keeps every request it was sent.
function fakeBackend() {
  const answers = new Map();
  const requests = [];
  const send = async (path, options = {}) => {
    requests.push({ path, ...options });
    let answer = answers.get(path);
    if (typeof answer === "function") answer = await answer(options);
    if (answer instanceof Error) throw answer;
    answer = answer || refused(404, "Not found");
    return { status: answer.status, json: async () => answer.body };
  };
  return { send, requests, on: (path, answer) => answers.set(path, answer), to: path => requests.filter(request => request.path === path) };
}

function start({ hint = true } = {}) {
  const backend = fakeBackend();
  const store = { value: hint, writes: [], get() { return this.value; }, set(value) { this.value = value; this.writes.push(value); } };
  const timers = [];
  const session = createSession({
    send: backend.send,
    remember: store,
    setTimer: (run, wait) => { const timer = { run, wait }; timers.push(timer); return timer; },
    clearTimer: timer => { const at = timers.indexOf(timer); if (at >= 0) timers.splice(at, 1); }
  });
  return { backend, store, timers, session };
}

async function loggedIn(options) {
  const world = start(options);
  world.backend.on("/auth/login", signedIn());
  await world.session.login("asha@example.com", "correct horse battery staple");
  return world;
}

// ---- on page load --------------------------------------------------------------------------------

test("a browser that was never signed in is shown the login page without asking the backend", async () => {
  const { backend, session } = start({ hint: false });
  assert.equal(session.snapshot().state, "checking");

  const view = await session.restore();

  assert.deepEqual(view, { state: "out", account: null, notice: "" });
  assert.deepEqual(backend.requests, []);
});

test("a browser that was signed in gets its session back from the refresh cookie", async () => {
  const { backend, store, session } = start();
  backend.on("/auth/refresh", signedIn("token-from-cookie"));
  backend.on("/courses", { status: 200, body: { data: [] } });

  const view = await session.restore();
  await session.call("/courses");

  assert.deepEqual(view, { state: "in", account: ASHA, notice: "" });
  assert.equal(backend.to("/auth/refresh")[0].method, "POST");
  // The renewal itself carries no token: the cookie, which this code never sees, is what proves it.
  assert.equal(backend.to("/auth/refresh")[0].token, undefined);
  assert.equal(backend.to("/courses")[0].token, "token-from-cookie");
  assert.equal(store.value, true);
});

test("a cookie that is no longer good leads to the login page, quietly", async () => {
  const { backend, store, session } = start();
  backend.on("/auth/refresh", refused(401, "Your session has ended. Log in again."));

  assert.deepEqual(await session.restore(), { state: "out", account: null, notice: "" });
  assert.equal(store.value, false);
});

test("a backend that cannot be reached on load is said to be unreachable, and asked again next time", async () => {
  for (const trouble of [offline(), refused(500, "Something went wrong"), { status: 200, body: {} }]) {
    const { backend, store, session } = start();
    backend.on("/auth/refresh", trouble);

    assert.deepEqual(await session.restore(), { state: "out", account: null, notice: UNREACHABLE });
    // Not reached is not signed out: the hint stays, so the next load tries the cookie again.
    assert.equal(store.value, true);
  }
});

// ---- logging in ----------------------------------------------------------------------------------

test("logging in sends the email and password once and keeps the token in memory only", async () => {
  const { backend, store, session } = await loggedIn({ hint: false });

  assert.deepEqual(backend.requests, [{ path: "/auth/login", method: "POST", body: { email: "asha@example.com", password: "correct horse battery staple" }, headers: CLIENT_HEADERS }]);
  assert.deepEqual(session.snapshot(), { state: "in", account: ASHA, notice: "" });
  // What is remembered between page loads is a yes or a no. Never the token, never the password.
  assert.deepEqual(store.writes, [true]);
  assert.equal(JSON.stringify(session.snapshot()).includes("token-1"), false);
});

test("a refused login says why in the backend's words and changes nothing", async () => {
  for (const [status, words] of [[401, "Incorrect email or password."], [429, "Too many failed attempts. Try again in 15 minutes."], [403, "This account is disabled. Ask a super admin to enable it."]]) {
    const { backend, store, session } = start({ hint: false });
    await session.restore();
    backend.on("/auth/login", refused(status, words));

    await assert.rejects(session.login("asha@example.com", "wrong"), error => error.message === words && error.status === status);
    assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: "" });
    assert.deepEqual(store.writes, [false]);
  }
});

test("a login that never reaches the backend fails without a status, so the page can say so", async () => {
  const { backend, session } = start({ hint: false });
  backend.on("/auth/login", offline());

  await assert.rejects(session.login("asha@example.com", "anything"), error => error.status === undefined);
});

test("an answer that looks like success but holds no token is not a login", async () => {
  const { backend, session } = start({ hint: false });
  backend.on("/auth/login", { status: 200, body: { success: true, data: {} } });

  await assert.rejects(session.login("asha@example.com", "anything"), /Unable to log in/);
  assert.equal(session.snapshot().state, "checking");
});

// ---- requests ------------------------------------------------------------------------------------

test("every request goes out with the access token", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/users", { status: 200, body: { data: [] } });

  const answer = await session.call("/users", { method: "GET" });

  assert.equal(answer.status, 200);
  assert.deepEqual(backend.to("/users"), [{ path: "/users", method: "GET", token: "token-1" }]);
});

test("when the access token has run out it is renewed once and the request is repeated", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/refresh", signedIn("token-2"));
  backend.on("/courses", options => options.token === "token-2" ? { status: 200, body: { data: ["CS101"] } } : refused(401, "Your session has ended. Log in again."));

  const answer = await session.call("/courses");

  assert.deepEqual([answer.status, await answer.json()], [200, { data: ["CS101"] }]);
  assert.deepEqual(backend.to("/courses").map(request => request.token), ["token-1", "token-2"]);
  assert.equal(backend.to("/auth/refresh").length, 1);
  assert.equal(session.snapshot().state, "in");
});

test("many requests refused at the same moment share one renewal", async () => {
  const { backend, session } = await loggedIn();
  let release;
  backend.on("/auth/refresh", () => new Promise(resolve => { release = () => resolve(signedIn("token-2")); }));
  backend.on("/frame", options => options.token === "token-2" ? { status: 200, body: {} } : refused(401, "ended"));

  const frames = [session.call("/frame"), session.call("/frame"), session.call("/frame"), session.call("/frame")];
  await new Promise(resolve => setTimeout(resolve, 5));
  release();
  const statuses = (await Promise.all(frames)).map(answer => answer.status);

  assert.deepEqual(statuses, [200, 200, 200, 200]);
  assert.equal(backend.to("/auth/refresh").length, 1);
});

test("when the login itself is over the app goes back to the login page and says why", async () => {
  const { backend, store, timers, session } = await loggedIn();
  backend.on("/auth/refresh", refused(401, "Your session has ended. Log in again."));
  backend.on("/courses", refused(401, "Your session has ended. Log in again."));

  const answer = await session.call("/courses");

  assert.equal(answer.status, 401);
  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: SESSION_ENDED });
  assert.equal(store.value, false);
  assert.deepEqual(timers, []);
  // Whatever is tried next goes out without a token.
  await session.call("/courses");
  assert.equal(backend.to("/courses").at(-1).token, null);
});

test("a renewed token that is refused again ends the session instead of trying for ever", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/refresh", signedIn("token-2"));
  backend.on("/courses", refused(401, "ended"));

  assert.equal((await session.call("/courses")).status, 401);

  assert.equal(backend.to("/courses").length, 2);
  assert.equal(backend.to("/auth/refresh").length, 1);
  assert.equal(session.snapshot().notice, SESSION_ENDED);
});

test("a server problem while renewing does not log anyone out", async () => {
  for (const trouble of [refused(500, "Something went wrong on the server."), refused(503, "unavailable")]) {
    const { backend, session } = await loggedIn();
    backend.on("/auth/refresh", trouble);
    backend.on("/courses", refused(401, "ended"));

    assert.equal((await session.call("/courses")).status, 401);
    assert.equal(session.snapshot().state, "in");
  }
});

test("losing the network while renewing fails that request and keeps the session", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/refresh", offline());
  backend.on("/courses", refused(401, "ended"));

  await assert.rejects(session.call("/courses"), /Failed to fetch/);
  assert.equal(session.snapshot().state, "in");
  // The next request tries again, and succeeds once the backend is back.
  backend.on("/auth/refresh", signedIn("token-2"));
  backend.on("/courses", options => options.token === "token-2" ? { status: 200, body: {} } : refused(401, "ended"));
  assert.equal((await session.call("/courses")).status, 200);
});

test("a refusal that is not about the login is passed on as it is", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/courses/create", refused(409, "Course code already exists"));
  backend.on("/super-admin/admins", refused(403, "Only a super admin can do this."));

  assert.equal((await session.call("/courses/create", { method: "POST", body: "{}" })).status, 409);
  assert.equal((await session.call("/super-admin/admins")).status, 403);
  assert.equal(backend.to("/auth/refresh").length, 0);
  assert.equal(session.snapshot().state, "in");
});

test("a request made while logged out is not retried", async () => {
  const { backend, session } = start({ hint: false });
  await session.restore();
  backend.on("/courses", refused(401, "Not logged in."));

  assert.equal((await session.call("/courses")).status, 401);
  assert.equal(backend.to("/auth/refresh").length, 0);
});

// ---- staying in ----------------------------------------------------------------------------------

test("the token is renewed a minute before it runs out, again and again", async () => {
  const { backend, timers, session } = await loggedIn();
  assert.deepEqual(timers.map(timer => timer.wait), [840000]);

  backend.on("/auth/refresh", signedIn("token-2"));
  timers[0].run();
  await new Promise(resolve => setTimeout(resolve, 5));

  assert.equal(backend.to("/auth/refresh").length, 1);
  // One timer, for the new token; the old one is gone.
  assert.deepEqual(timers.map(timer => timer.wait), [840000]);
  backend.on("/courses", { status: 200, body: {} });
  await session.call("/courses");
  assert.equal(backend.to("/courses")[0].token, "token-2");
});

test("a very short token is renewed before it ends, and never in a tight loop", async () => {
  for (const [lifetime, wait] of [[600, 540000], [100, 80000], [30, 24000], [2, 5000]]) {
    const { backend, timers, session } = start({ hint: false });
    backend.on("/auth/login", signedIn("token-1", ASHA, lifetime));
    await session.login("asha@example.com", "x");

    assert.deepEqual(timers.map(timer => timer.wait), [wait]);
  }
});

// ---- logging out ---------------------------------------------------------------------------------

test("logging out tells the backend, forgets the token and stops the renewals", async () => {
  const { backend, store, timers, session } = await loggedIn();
  backend.on("/auth/logout", { status: 200, body: { success: true, message: "Logged out" } });
  backend.on("/courses", refused(401, "Not logged in."));

  await session.logout();

  assert.equal(backend.to("/auth/logout")[0].method, "POST");
  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: "" });
  assert.equal(store.value, false);
  assert.deepEqual(timers, []);
  await session.call("/courses");
  assert.equal(backend.to("/courses")[0].token, null);
});

// A renewal whose answer the test hands over when it chooses.
function slowRenewal(backend) {
  const pending = {};
  backend.on("/auth/refresh", () => new Promise(resolve => { pending.answer = resolve; }));
  return pending;
}
const settle = () => new Promise(resolve => setTimeout(resolve, 5));

test("a renewal still on its way when the person logs out does not log them back in", async () => {
  const { backend, store, timers, session } = await loggedIn();
  const renewal = slowRenewal(backend);
  backend.on("/auth/logout", { status: 200, body: {} });
  backend.on("/courses", refused(401, "Not logged in."));

  timers[0].run();
  await session.logout();
  renewal.answer(signedIn("token-2"));
  await settle();

  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: "" });
  assert.deepEqual(timers, []);
  assert.equal(store.value, false);
  await session.call("/courses");
  assert.equal(backend.to("/courses")[0].token, null);
});

test("a renewal still on its way when the password is changed does not undo the logout", async () => {
  const { backend, timers, session } = await loggedIn();
  const renewal = slowRenewal(backend);
  backend.on("/auth/change-password", { status: 200, body: { success: true } });

  timers[0].run();
  await session.changePassword("correct horse battery staple", "another fine long password");
  renewal.answer(signedIn("token-2"));
  await settle();

  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: PASSWORD_CHANGED });
  assert.deepEqual(timers, []);
});

test("after logging out and in again, a late answer to the old renewal changes nothing", async () => {
  const { backend, session, timers } = await loggedIn();
  const renewal = slowRenewal(backend);
  backend.on("/auth/logout", { status: 200, body: {} });
  timers[0].run();
  await session.logout();
  backend.on("/auth/login", signedIn("token-3"));
  await session.login("asha@example.com", "correct horse battery staple");

  // The new session renews on its own, without waiting for the old renewal's answer.
  backend.on("/auth/refresh", signedIn("token-4"));
  let asked = 0;
  backend.on("/courses", () => (++asked === 1 ? refused(401, "Your session has ended. Log in again.") : { status: 200, body: {} }));
  const answer = await session.call("/courses");
  renewal.answer(signedIn("token-2", OWNER));
  await settle();

  assert.equal(answer.status, 200);
  assert.deepEqual(backend.to("/courses").map(request => request.token), ["token-3", "token-4"]);
  assert.deepEqual(session.snapshot(), { state: "in", account: ASHA, notice: "" });
});

test("renewing and logging out say they come from the console, which another page cannot", async () => {
  const { backend, timers, session } = await loggedIn();
  backend.on("/auth/refresh", signedIn("token-2"));
  backend.on("/auth/logout", { status: 200, body: {} });

  timers[0].run();
  await settle();
  await session.logout();

  assert.deepEqual(CLIENT_HEADERS, { "X-Requested-With": "vernex" });
  assert.deepEqual(backend.to("/auth/refresh").map(request => request.headers), [CLIENT_HEADERS]);
  assert.deepEqual(backend.to("/auth/logout").map(request => request.headers), [CLIENT_HEADERS]);
  // Never the access token: these work on the cookie alone.
  assert.deepEqual(backend.to("/auth/logout").map(request => request.token), [undefined]);
});

test("a logout the server refuses or fails still logs this device out, and says the server did not confirm it", async () => {
  for (const status of [403, 500]) {
    const { backend, store, session } = await loggedIn();
    backend.on("/auth/logout", refused(status, "Refused"));

    await session.logout();

    assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: LOGOUT_UNCONFIRMED });
    assert.equal(store.value, false);
  }
});

test("logging out works on this device even when the backend cannot be reached", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/logout", offline());

  await session.logout();

  assert.equal(session.snapshot().state, "out");
  assert.match(session.snapshot().notice, /could not be reached/);
});

// ---- changing the password -----------------------------------------------------------------------

test("changing the password sends both and ends the session, as it has ended on the server", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/change-password", { status: 200, body: { success: true } });

  await session.changePassword("correct horse battery staple", "another fine long password");

  assert.deepEqual(backend.to("/auth/change-password"), [{ path: "/auth/change-password", method: "POST", body: { current_password: "correct horse battery staple", new_password: "another fine long password" }, token: "token-1" }]);
  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: PASSWORD_CHANGED });
});

test("a refused password change says why and leaves the session as it was", async () => {
  const { backend, session } = await loggedIn();
  backend.on("/auth/change-password", refused(400, "The current password is incorrect."));

  await assert.rejects(session.changePassword("wrong", "another fine long password"), error => error.message === "The current password is incorrect." && error.status === 400);
  assert.equal(session.snapshot().state, "in");
});

// ---- the screens are told --------------------------------------------------------------------------

test("the screens are told of every change, and the view is the same object until one happens", async () => {
  const { backend, session } = start({ hint: false });
  const seen = [];
  const stop = session.subscribe(view => seen.push(view.state));
  backend.on("/auth/login", signedIn());
  backend.on("/auth/logout", { status: 200, body: {} });

  await session.restore();
  await session.login("asha@example.com", "x");
  const first = session.snapshot();
  assert.equal(session.snapshot(), first);
  await session.logout();
  stop();
  await session.login("asha@example.com", "x");

  assert.deepEqual(seen, ["out", "in", "out"]);
  assert.notEqual(session.snapshot(), first);
});

test("no token and no password is ever written where a page could read it back", () => {
  const session_code = readFileSync(new URL("./auth.js", import.meta.url), "utf8");
  const api_code = readFileSync(new URL("./api.js", import.meta.url), "utf8");

  // Using a store means calling something on it; a comment that only names one is not a use.
  const uses_a_store = /\b(localStorage|sessionStorage|indexedDB)\s*[.[]|document\s*\.\s*cookie/;
  assert.equal(uses_a_store.test("localStorage.setItem('t', token)"), true);
  assert.equal(uses_a_store.test(session_code), false);
  // api.js keeps one thing between page loads: the word "yes".
  assert.deepEqual(api_code.match(/\.setItem\([^)]*\)/g), ['.setItem(SIGNED_IN_HINT, "yes")']);
  assert.equal(/\bsessionStorage\s*[.[]|document\s*\.\s*cookie|\bindexedDB\s*[.[]/.test(api_code), false);
});

// ---- which page an account gets ------------------------------------------------------------------

const PAGES = { superAdmin: { roles: ["super_admin"] }, dashboard: {}, scanner: {}, settings: {}, changePassword: {} };

test("nothing of the app is shown until the session is known, and nothing without one", () => {
  for (const page of ["dashboard", "superAdmin", "scanner", "home", "login", "nonsense"]) {
    assert.deepEqual(screenFor({ state: "checking", account: null, page, pages: PAGES }), { screen: "checking" });
    assert.deepEqual(screenFor({ state: "out", account: null, page, pages: PAGES }), { screen: "login" });
    assert.deepEqual(screenFor({ state: "in", account: null, page, pages: PAGES }), { screen: "login" });
  }
});

test("an admin gets the console and is kept out of the super admin page", () => {
  assert.deepEqual(screenFor({ state: "in", account: ASHA, page: "scanner", pages: PAGES }), { screen: "page", page: "scanner" });
  assert.deepEqual(screenFor({ state: "in", account: ASHA, page: "superAdmin", pages: PAGES }), { screen: "not-allowed", page: "superAdmin" });
  assert.deepEqual(screenFor({ state: "in", account: OWNER, page: "superAdmin", pages: PAGES }), { screen: "page", page: "superAdmin" });
  assert.deepEqual(screenFor({ state: "in", account: OWNER, page: "scanner", pages: PAGES }), { screen: "page", page: "scanner" });
});

test("an address that is not a page shows the account's own start page", () => {
  for (const page of ["home", "login", "nonsense"]) {
    assert.deepEqual(screenFor({ state: "in", account: ASHA, page, pages: PAGES }), { screen: "page", page: "dashboard" });
    assert.deepEqual(screenFor({ state: "in", account: OWNER, page, pages: PAGES }), { screen: "page", page: "superAdmin" });
  }
});

test("a temporary password opens the change-password screen and nothing else", () => {
  for (const account of [{ ...ASHA, must_change_password: true }, { ...OWNER, must_change_password: true }]) {
    for (const page of ["dashboard", "superAdmin", "scanner", "settings", "home"]) {
      assert.deepEqual(screenFor({ state: "in", account, page, pages: PAGES }), { screen: "change-password" });
    }
  }
});

test("after logging in a super admin lands on the super admin page and an admin on the dashboard", () => {
  assert.equal(homeFor("super_admin"), "superAdmin");
  assert.equal(homeFor("admin"), "dashboard");
  assert.equal(landingPage({ wanted: null, account: OWNER, pages: PAGES }), "superAdmin");
  assert.equal(landingPage({ wanted: null, account: ASHA, pages: PAGES }), "dashboard");
});

test("someone who opened a page's own address goes there after logging in, if they may", () => {
  // The phone that opened the scanner link gets the scanner.
  assert.equal(landingPage({ wanted: "scanner", account: ASHA, pages: PAGES }), "scanner");
  assert.equal(landingPage({ wanted: "scanner", account: OWNER, pages: PAGES }), "scanner");
  assert.equal(landingPage({ wanted: "superAdmin", account: OWNER, pages: PAGES }), "superAdmin");
  // An admin who typed the super admin address does not, and neither does a made-up address.
  assert.equal(landingPage({ wanted: "superAdmin", account: ASHA, pages: PAGES }), "dashboard");
  assert.equal(landingPage({ wanted: "nonsense", account: ASHA, pages: PAGES }), "dashboard");
});

test("the navigation of an admin has no super admin entry, and no empty group", () => {
  const groups = [{ label: "Super Admin", items: ["superAdmin"] }, { label: "Overview", items: ["dashboard"] }, { label: "System", items: ["settings", "superAdmin"] }];

  assert.deepEqual(visibleGroups(groups, PAGES, "admin"), [{ label: "Overview", items: ["dashboard"] }, { label: "System", items: ["settings"] }]);
  assert.deepEqual(visibleGroups(groups, PAGES, "super_admin"), groups);
  assert.equal(mayOpen(undefined, "admin"), true);
  assert.equal(mayOpen(["super_admin"], "admin"), false);
  assert.equal(mayOpen(["super_admin"], undefined), false);
});

// ---- a new password ------------------------------------------------------------------------------

test("a new password is checked before it is sent, by the rules the backend also applies", () => {
  assert.equal(passwordProblem("nine char", "asha@example.com"), "Use at least 10 characters.");
  assert.equal(passwordProblem("", "asha@example.com"), "Use at least 10 characters.");
  assert.equal(passwordProblem("p".repeat(129), "asha@example.com"), "Use at most 128 characters.");
  assert.equal(passwordProblem("Asha@Example.com", "asha@example.com"), "The password must not be your email address.");
  assert.equal(passwordProblem(" asha@example.com ", "asha@example.com"), "The password must not be your email address.");
  assert.equal(passwordProblem("ten chars!", "asha@example.com"), "");
  assert.equal(passwordProblem("p".repeat(128), "asha@example.com"), "");
  assert.equal(passwordProblem("asha@example.com"), "");
});

// ---- idle consoles (task S-16) -------------------------------------------------------------------

// A console on a clock of its own: advance(ms) moves time, fire() runs the one pending timer.
async function idleWorld(idleLimit = 30 * 60000) {
  let clock = 1_000_000;
  const backend = fakeBackend();
  const timers = [];
  const session = createSession({
    send: backend.send,
    remember: { get: () => true, set() {} },
    setTimer: (run, wait) => { const timer = { run, wait }; timers.push(timer); return timer; },
    clearTimer: timer => { const at = timers.indexOf(timer); if (at >= 0) timers.splice(at, 1); },
    now: () => clock,
    idleLimit
  });
  backend.on("/auth/login", signedIn());
  backend.on("/auth/refresh", signedIn("token-2"));
  backend.on("/auth/logout", { status: 200, body: { success: true } });
  await session.login("asha@example.com", "x");
  const fire = async () => {
    const [timer] = timers;
    clock += timer.wait;
    timer.run();
    await new Promise(resolve => setTimeout(resolve, 5));
    return timer.wait;
  };
  return { backend, timers, session, fire, advance: ms => { clock += ms; } };
}

test("a console nobody touches for 30 minutes logs out, on this device and on the server", async () => {
  const { backend, session, fire } = await idleWorld();

  // Renewed at 14 and 28 minutes, then the timer is set for the 30th minute and goes off there.
  assert.deepEqual([await fire(), await fire(), await fire()], [840000, 840000, 120000]);

  assert.deepEqual(session.snapshot(), { state: "out", account: null, notice: IDLE_ENDED });
  assert.equal(backend.to("/auth/refresh").length, 2);
  assert.equal(backend.to("/auth/logout").length, 1);
  assert.match(IDLE_ENDED, /30 minutes without activity/);
});

test("a click or a key keeps the console logged in", async () => {
  const { backend, session, fire, advance } = await idleWorld();

  for (let round = 0; round < 6; round += 1) {
    advance(600000);
    session.touch();
    await fire();
  }

  assert.equal(session.snapshot().state, "in");
  assert.equal(backend.to("/auth/logout").length, 0);
});

test("activity after the idle timer was set only sets it again", async () => {
  const { session, timers, fire, advance } = await idleWorld(20 * 60000);
  await fire(); // renewal at 14 min; the next timer is for the idle limit, 6 minutes on
  assert.equal(timers[0].wait, 360000);

  advance(-60000); // fire() adds the wait back: the touch happens one minute before the limit
  session.touch();
  await fire();

  assert.equal(session.snapshot().state, "in");
});

test("a running scanner keeps the console awake for as long as it runs", async () => {
  const { session, fire } = await idleWorld();
  session.keepAwake("scanner", true);

  for (let round = 0; round < 10; round += 1) await fire();
  assert.equal(session.snapshot().state, "in");

  // Stopped: idle time counts from then.
  session.keepAwake("scanner", false);
  const waits = [await fire(), await fire(), await fire()];
  assert.deepEqual(waits, [840000, 840000, 120000]);
  assert.equal(session.snapshot().notice, IDLE_ENDED);
});

test("an idle limit of 0 never logs out", async () => {
  const { session, fire } = await idleWorld(0);

  for (let round = 0; round < 10; round += 1) await fire();

  assert.equal(session.snapshot().state, "in");
});
