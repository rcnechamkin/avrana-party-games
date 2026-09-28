// hubnet.js party tickets (AVR-22), in Node with a fake WebSocket, a fake fetch and a manual clock.
//   node tests/hubnet_party_ticket_test.mjs
// In an integrated (?avrana=1) game page, every connect first asks the party for a session ticket
// (POST /party/api/session/ticket, cookie, never a URL) and sends it only in the WebSocket hello.
// Without a ticket (no party service, not a member, another game) the page falls back to today's
// hello, which the game server treats as a watcher while a party session runs.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const flush = () => new Promise((r) => setImmediate(r));

function load({ integrated = true, answer = () => ({ status: 200, body: { game: "bluff", ticket: "aps0.T.S" } }) } = {}) {
  const timers = [];
  let now = 0;
  const listeners = {};
  const docListeners = {};
  const added = [];
  const el = () => new Proxy({ style: {}, classList: { add() {}, remove() {}, toggle() {} },
                               appendChild(c) { added.push(c); }, insertBefore(c) { added.push(c); },
                               remove() {}, setAttribute() {}, addEventListener() {} },
                             { get: (t, k) => (k in t ? t[k] : undefined), set: (t, k, v) => { t[k] = v; return true; } });
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(d) { this.sent.push(JSON.parse(d)); }
    close() { if (this.readyState < 3) { this.readyState = 3; this.onclose && this.onclose(); } }
    accept() { this.readyState = 1; this.onopen && this.onopen(); }
    welcome(extra = {}) { this.onmessage({ data: JSON.stringify({ type: "welcome", pid: "p1", ...extra }) }); }
    drop() { this.readyState = 3; this.onclose && this.onclose(); }
  }
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const a = await answer(calls.length);
    if (a instanceof Error) throw a;
    return { ok: a.status >= 200 && a.status < 300, status: a.status, json: async () => a.body };
  };
  const store = { "wc-token": "browser-minted-token", "wc-name": "Eve", "wc-avatar": "🦊" };
  const ctx = {
    console, JSON, Math, Promise, Date: { now: () => now }, URLSearchParams,
    location: { pathname: "/games/bluff/", search: integrated ? "?avrana=1" : "", protocol: "https:", host: "party.example" },
    navigator: {}, matchMedia: () => ({ matches: false, addEventListener() {} }),
    window: { isSecureContext: false, AvranaIntegration: { integrated, home: integrated ? "/party/" : "/" } },
    localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); }, removeItem: (k) => { delete store[k]; } },
    document: {
      querySelector: () => ({}), getElementById: () => null, createElement: el,
      head: el(), body: el(), documentElement: el(), visibilityState: "visible",
      addEventListener: (ev, fn) => { (docListeners[ev] ||= []).push(fn); },
    },
    addEventListener: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
    setTimeout: (fn, ms) => { const t = { at: now + ms, fn, live: true }; timers.push(t); return t; },
    clearTimeout: (t) => { if (t) t.live = false; },
    setInterval: () => 0, requestAnimationFrame: () => 0, queueMicrotask: () => {},
    WebSocket: FakeWS, fetch,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(readFileSync(new URL("../web/hubnet.js", import.meta.url), "utf8") + "\n;globalThis.Hub = Hub;", ctx);
  const advance = (ms) => {
    const until = now + ms;
    for (;;) {
      const due = timers.filter((t) => t.live && t.at <= until).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      now = due.at; due.live = false; due.fn();
    }
    now = until;
  };
  return { Hub: ctx.Hub, sockets, calls, store, advance, added,
           fire: (ev) => (listeners[ev] || []).forEach((f) => f()) };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("integrated: the ticket goes only in the hello, never the URL, with no browser token", async () => {
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  assert.equal(t.calls.length, 1);
  const { url, init } = t.calls[0];
  assert.equal(url, "/party/api/session/ticket");
  assert.equal(init.method, "POST");
  assert.equal(init.credentials, "same-origin");
  assert.equal(init.cache, "no-store");
  assert.equal(init.body, "{}");
  assert.equal(t.sockets.length, 1);
  assert.ok(!t.sockets[0].url.includes("aps0"), "ticket must never be in the URL");
  t.sockets[0].accept();
  assert.deepEqual(t.sockets[0].sent[0], { t: "hello", ticket: "aps0.T.S", avatar: "🦊" });
});

test("integrated: every reconnect fetches a fresh ticket", async () => {
  let n = 0;
  const t = load({ answer: () => ({ status: 200, body: { game: "bluff", ticket: "aps0.T" + (++n) + ".S" } }) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
  t.advance(5000); await flush();
  assert.equal(t.calls.length, 2);
  t.sockets[1].accept();
  assert.equal(t.sockets[1].sent[0].ticket, "aps0.T2.S");
});

test("integrated: a party welcome (no token) leaves the browser's own token alone", async () => {
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome();
  assert.equal(t.store["wc-token"], "browser-minted-token");
});

for (const [label, answer] of [
  ["no party service (404)", () => ({ status: 404, body: {} })],
  ["not a member (403)", () => ({ status: 403, body: { error: "not_member" } })],
  ["network error", () => new Error("offline")],
  ["a ticket for another game", () => ({ status: 200, body: { game: "poker", ticket: "aps0.P.S" } })],
  ["no ticket in the answer", () => ({ status: 200, body: { game: "bluff" } })],
]) {
  test(`integrated, ${label}: falls back to today's hello`, async () => {
    const t = load({ answer });
    t.Hub.connect("/games/bluff/ws", { onState() {} });
    await flush();
    assert.equal(t.sockets.length, 1);
    t.sockets[0].accept();
    const hello = t.sockets[0].sent[0];
    assert.equal(hello.ticket, undefined);
    assert.equal(hello.token, "browser-minted-token");
  });
}

test("standalone: no ticket request, and the socket opens at once", () => {
  const t = load({ integrated: false });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  assert.equal(t.calls.length, 0);
  assert.equal(t.sockets.length, 1);
  t.sockets[0].accept();
  assert.equal(t.sockets[0].sent[0].token, "browser-minted-token");
});

test("integrated watch (TV) pages never ask for a ticket", () => {
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} }, { watch: true });
  assert.equal(t.calls.length, 0);
  t.sockets[0].accept();
  assert.deepEqual(t.sockets[0].sent[0], { t: "hello", watch: true });
});

test("waking up while a ticket request is pending opens only one socket", async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  const ok = { status: 200, body: { game: "bluff", ticket: "aps0.T.S" } };
  const t = load({ answer: (n) => (n === 1 ? ok : gate.then(() => ok)) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
  t.advance(1000); await flush();              // the reconnect's ticket request is now in flight
  assert.equal(t.calls.length, 2);
  t.fire("online"); t.advance(0); t.fire("online"); t.advance(1000); await flush();
  release(); await flush(); await flush();
  assert.equal(t.sockets.length, 2, "exactly one new socket after the drop");
  assert.equal(t.calls.length, 2, "no second ticket request while one is pending");
});

for (const integrated of [true, false]) {
  test(`party_ended (${integrated ? "integrated" : "standalone"}): ${integrated ? "stops reconnecting and says so" : "is ignored"}`, async () => {
    const t = load({ integrated });
    const seen = [];
    t.Hub.connect("/games/bluff/ws", { onState() {}, onFx: (fx) => seen.push(fx.kind) });
    await flush();
    t.sockets[0].accept(); t.sockets[0].welcome();
    t.sockets[0].onmessage({ data: JSON.stringify({ type: "fx", kind: "party_ended", outcome: "completed" }) });
    t.sockets[0].drop();                       // the server closes the socket
    t.advance(10000); await flush();
    t.fire("online"); t.advance(1000); await flush();
    assert.deepEqual(seen, ["party_ended"]);
    if (integrated) {
      assert.equal(t.sockets.length, 1, "no reconnect into a room the party session has left");
      assert.equal(t.calls.length, 1, "no new ticket request");
      assert.ok(t.added.some((n) => n.id === "party-ended" && /over/.test(n.textContent)));
    } else {
      assert.ok(t.sockets.length > 1, "standalone pages keep today's reconnect");
      assert.ok(!t.added.some((n) => n.id === "party-ended"));
    }
  });
}

let passed = 0;
for (const [name, fn] of tests) {
  try { await fn(); passed++; console.log("ok", passed, name); }
  catch (e) { console.log("not ok", name); console.log(e); process.exitCode = 1; }
}
console.log(`hubnet party ticket: ${passed}/${tests.length} passed`);
