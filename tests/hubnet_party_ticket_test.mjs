// hubnet.js party tickets (AVR-22), in Node with a fake WebSocket, a fake fetch and a manual clock.
//   node tests/hubnet_party_ticket_test.mjs
// In an integrated (?avrana=1) game page, every connect first asks the party for a session ticket
// (POST /party/api/session/ticket, cookie, never a URL) and sends it only in the WebSocket hello.
// The party is authoritative (AVR-22/23/24): a request that reaches nothing, times out or gets a
// 5xx is retried (bounded) and never becomes a ticketless hello; a tab that held a ticket and is
// then told "no game" shows the ended state (never standalone play) and joins the next launch
// that includes it. A page that never held a ticket keeps today's fallback hello.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const flush = () => new Promise((r) => setImmediate(r));
const S1 = "session-" + "1".repeat(32), S2 = "session-" + "2".repeat(32);
const NO_GAME = { status: 409, body: { error: "no_game", message: "No game is on." } };
const ticketFor = (session, ticket = "aps0.T.S") => ({ status: 200, body: { game: "bluff", ticket, session } });

function load({ integrated = true, answer = () => ticketFor(S1), tab = {} } = {}) {
  const timers = [];
  let now = 0;
  const listeners = {};
  const docListeners = {};
  const added = [];
  const el = () => new Proxy({ style: {}, classList: { add() {}, remove() {}, toggle() {} },
                               appendChild(c) { added.push(c); }, insertBefore(c) { added.push(c); },
                               remove() { this.removed = true; }, setAttribute() {}, addEventListener() {} },
                             { get: (t, k) => (k in t ? t[k] : undefined), set: (t, k, v) => { t[k] = v; return true; } });
  const room = el();
  room.id = "avrana-game-room";
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
    sessionStorage: { getItem: (k) => tab[k] ?? null, setItem: (k, v) => { tab[k] = String(v); }, removeItem: (k) => { delete tab[k]; } },
    document: {
      querySelector: () => ({}), getElementById: (id) => (id === "avrana-game-room" ? room : null), createElement: el,
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
  const helloOf = (ws) => ws.sent.find((m) => m.t === "hello");
  const ended = () => added.some((n) => n.id === "party-ended" && !n.removed);
  const run = async (ms, step = 500) => {
    for (let t = 0; t < ms; t += step) { advance(step); await flush(); await flush(); }
  };
  const roomShown = () => room.style.display !== "none";
  return { Hub: ctx.Hub, sockets, calls, store, advance, added, tab, helloOf, ended, run, roomShown,
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
  assert.equal(init.body, '{"game":"bluff"}');            // names its game (AVR-128)
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

test("integrated, network error: no ticketless hello; the ticket request is retried (AVR-23)", async () => {
  // A waking phone often loses its first request (stale keep-alive, Wi-Fi still rejoining) while a
  // new socket would connect: falling back then would turn a seated player into a watcher.
  const ok = { status: 200, body: { game: "bluff", ticket: "aps0.T.S" } };
  const t = load({ answer: (n) => (n === 1 ? new Error("offline") : ok) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  assert.equal(t.sockets.length, 0, "no socket without a ticket after a network error");
  t.advance(600); await flush();
  assert.equal(t.calls.length, 2);
  assert.equal(t.sockets.length, 1);
  t.sockets[0].accept();
  assert.deepEqual(t.sockets[0].sent[0], { t: "hello", ticket: "aps0.T.S", avatar: "🦊" });
});

test("integrated, network error on a reconnect: waking up retries at once, with a ticket", async () => {
  const ok = { status: 200, body: { game: "bluff", ticket: "aps0.T.S" } };
  const t = load({ answer: (n) => (n === 2 ? new Error("offline") : ok) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
  t.advance(600); await flush();                 // the reconnect's ticket request fails
  assert.equal(t.calls.length, 2);
  assert.equal(t.sockets.length, 1, "no ticketless socket");
  t.fire("online"); t.advance(0); await flush();
  assert.equal(t.calls.length, 3);
  assert.equal(t.sockets.length, 2);
  t.sockets[1].accept();
  assert.equal(t.sockets[1].sent[0].ticket, "aps0.T.S");
  assert.equal(t.sockets[1].sent[0].token, undefined);
});

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

test("a ticket request that never answers does not stall reconnecting", async () => {
  const ok = { status: 200, body: { game: "bluff", ticket: "aps0.T.S" } };
  const t = load({ answer: (n) => (n === 2 ? new Promise(() => {}) : ok) });  // e.g. slept mid-request
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
  t.advance(1000); await flush();              // the reconnect's ticket request hangs
  assert.equal(t.calls.length, 2);
  await t.run(10000);
  t.fire("online"); await t.run(5000);
  assert.ok(t.sockets.length >= 2, "the page must reconnect after a hung ticket request");
  t.sockets[1].accept();
  assert.equal(t.helloOf(t.sockets[1]).ticket, "aps0.T.S", "... with a ticket, never as a watcher");
});

for (const integrated of [true, false]) {
  test(`party_ended (${integrated ? "integrated" : "standalone"}): ${integrated ? "stops reconnecting and says so" : "is ignored"}`, async () => {
    const t = load({ integrated, answer: (n) => (n === 1 ? ticketFor(S1) : NO_GAME) });
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
      assert.ok(t.calls.length > 1, "it keeps asking the party (a later launch may include it)");
      assert.ok(t.added.some((n) => n.id === "party-ended" && /over/.test(n.textContent)));
    } else {
      assert.ok(t.sockets.length > 1, "standalone pages keep today's reconnect");
      assert.ok(!t.added.some((n) => n.id === "party-ended"));
    }
  });
}

// ---- integration (AVR-22/23/24): the party is authoritative; a player never degrades -------------

test("a ticket request that times out is retried, and the retry's ticket is used", async () => {
  const t = load({ answer: (n) => (n === 2 ? new Promise(() => {}) : ticketFor(S1)) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
  t.advance(1000); await flush();                  // reconnect: the ticket request hangs
  assert.equal(t.calls.length, 2);
  await t.run(7000);                               // TICKET_WAIT passes: no ticketless socket
  assert.ok(t.calls.length >= 3, "retried after the timeout");
  assert.equal(t.sockets.length, 2);
  t.sockets[1].accept();
  assert.equal(t.helloOf(t.sockets[1]).ticket, "aps0.T.S");
  assert.equal(t.helloOf(t.sockets[1]).token, undefined);
});

for (const [label, failure] of [["network errors", () => new Error("offline")],
                                 ["party 5xx", () => ({ status: 503, body: {} })],
                                 ["timeouts", () => new Promise(() => {})]]) {
  test(`repeated ${label} never turn a player into a watcher, and retrying is bounded`, async () => {
    const t = load({ answer: (n) => (n === 1 ? ticketFor(S1) : failure()) });
    t.Hub.connect("/games/bluff/ws", { onState() {} });
    await flush();
    t.sockets[0].accept(); t.sockets[0].welcome(); t.sockets[0].drop();
    await t.run(20 * 60 * 1000, 1000);             // twenty minutes of failures
    assert.equal(t.sockets.length, 1, "never a socket without a ticket");
    const tries = t.calls.length;
    assert.ok(tries > 5 && tries <= 30, `bounded retries, got ${tries}`);
    await t.run(10 * 60 * 1000, 1000);
    assert.equal(t.calls.length, tries, "stopped: waits for the network to come back");
    t.fire("online"); await t.run(1000);
    assert.equal(t.calls.length, tries + 1, "coming back online tries again");
    assert.ok(!t.ended(), "a failure is not the end of the session");
  });
}

test("sleeping through the end: the page shows the end, never plays standalone", async () => {
  const t = load({ answer: (n) => (n === 1 ? ticketFor(S1) : NO_GAME) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome();
  t.sockets[0].drop();                             // asleep; meanwhile the party ended the session
  await t.run(3000);
  assert.equal(t.sockets.length, 1, "no socket: not a standalone player, not a watcher");
  assert.ok(t.ended(), "the ended state with Back to Party");
});

for (const [label, answer] of [["no game on", NO_GAME], ["no party service any more", { status: 404, body: {} }],
                               ["another game on", { status: 200, body: { game: "poker", ticket: "aps0.P.S", session: S2 } }]]) {
  test(`a reload after the session ended (${label}) shows the end, not standalone play`, async () => {
    const tab = {};
    const first = load({ tab, answer: () => ticketFor(S1) });
    first.Hub.connect("/games/bluff/ws", { onState() {} });
    await flush();
    const t = load({ tab, answer: () => answer });   // same tab, reloaded
    t.Hub.connect("/games/bluff/ws", { onState() {} });
    await flush(); await flush();
    assert.equal(t.sockets.length, 0);
    assert.ok(t.ended());
  });
}

test("from the ended state, the next launch that includes this phone is joined without a reload", async () => {
  let launched = false;
  const t = load({ answer: (n) => (n === 1 ? ticketFor(S1) : launched ? ticketFor(S2, "aps0.NEW.S") : NO_GAME) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome();
  t.sockets[0].onmessage({ data: JSON.stringify({ type: "fx", kind: "party_ended", outcome: "completed" }) });
  await t.run(12000);
  assert.equal(t.sockets.length, 1);
  assert.ok(t.ended());
  launched = true;                                 // the host starts a rematch: a new session
  await t.run(6000);
  assert.equal(t.sockets.length, 2, "joined the new play-through");
  assert.ok(!t.ended(), "the ended note is gone");
  t.sockets[1].accept();
  assert.equal(t.helloOf(t.sockets[1]).ticket, "aps0.NEW.S");
  assert.equal(t.tab["avrana-party-session:bluff"], S2);
});

test("a watcher whose socket the next launch closes comes back with its new (player) ticket", async () => {
  const t = load({ answer: (n) => (n === 1 ? ticketFor(S1, "aps0.SPECTATOR.S") : ticketFor(S2, "aps0.PLAYER.S")) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].onmessage({ data: JSON.stringify({ type: "welcome", watch: true }) });
  t.sockets[0].drop();                             // the launch closed every socket
  await t.run(2000);
  assert.equal(t.sockets.length, 2);
  t.sockets[1].accept();
  assert.equal(t.helloOf(t.sockets[1]).ticket, "aps0.PLAYER.S");
});

test("a page that never had a party session keeps today's fallback (the server decides its role)", async () => {
  const t = load({ answer: () => NO_GAME });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush(); await flush();
  assert.equal(t.sockets.length, 1);
  t.sockets[0].accept();
  assert.equal(t.helloOf(t.sockets[0]).token, "browser-minted-token");
  assert.ok(!t.ended());
});

test("the ended state hides the stale table, and the next play-through shows the room again", async () => {
  // Found on the Pi over the Party Wi-Fi (AVR-23 remote run): the note said "This game is over."
  // but the last table (the old hand, a turn timer) stayed on screen below it.
  let launched = false;
  const t = load({ answer: (n) => (n === 1 ? ticketFor(S1) : launched ? ticketFor(S2, "aps0.NEW.S") : NO_GAME) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome();
  assert.ok(t.roomShown());
  t.sockets[0].drop();                             // asleep through the end (no party_ended fx)
  await t.run(3000);
  assert.ok(t.ended());
  assert.ok(!t.roomShown(), "no stale table under the ended note");
  launched = true;
  await t.run(6000);
  assert.equal(t.sockets.length, 2);
  assert.ok(t.roomShown(), "the room is back for the new play-through");
});

test("party_ended hides the table too", async () => {
  const t = load({ answer: (n) => (n === 1 ? ticketFor(S1) : NO_GAME) });
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  await flush();
  t.sockets[0].accept(); t.sockets[0].welcome();
  t.sockets[0].onmessage({ data: JSON.stringify({ type: "fx", kind: "party_ended", outcome: "ended" }) });
  assert.ok(!t.roomShown());
});

let passed = 0;
for (const [name, fn] of tests) {
  try { await fn(); passed++; console.log("ok", passed, name); }
  catch (e) { console.log("not ok", name); console.log(e); process.exitCode = 1; }
}
console.log(`hubnet party ticket: ${passed}/${tests.length} passed`);
