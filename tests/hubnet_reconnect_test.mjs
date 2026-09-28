// hubnet.js reconnect behaviour, in Node with a fake WebSocket and a manual clock (no browser).
//   node tests/hubnet_reconnect_test.mjs
// 1. Network failures (sockets that never open) must NOT count as "room full": a phone that was
//    offline for a while must reconnect when the network is back.
// 2. Three real refusals (socket opened, no welcome) still stop the retries.
// 3. Coming back online / becoming visible reconnects at once, without a second socket.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

function load() {
  const timers = [];
  let now = 0;
  const listeners = {};
  const docListeners = {};
  const el = () => new Proxy({ style: {}, classList: { add() {}, remove() {}, toggle() {} },
                               appendChild() {}, remove() {}, setAttribute() {}, addEventListener() {} },
                             { get: (t, k) => (k in t ? t[k] : undefined), set: (t, k, v) => { t[k] = v; return true; } });
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(d) { this.sent.push(d); }
    close() { if (this.readyState < 3) { this.readyState = 3; this.onclose && this.onclose(); } }
    // test helpers
    failToConnect() { this.readyState = 3; this.onclose && this.onclose(); }
    accept() { this.readyState = 1; this.onopen && this.onopen(); }
    welcome() { this.onmessage({ data: JSON.stringify({ type: "welcome", token: "t" }) }); }
    refuse() { this.readyState = 3; this.onclose && this.onclose(); }
  }
  const store = {};
  const ctx = {
    console, JSON, Math, Date: { now: () => now },
    location: { pathname: "/games/bluff/", protocol: "http:", host: "10.42.0.1:8196" },
    navigator: {}, window: { isSecureContext: false }, matchMedia: () => ({ matches: false, addEventListener() {} }),
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
    WebSocket: FakeWS,
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
  return { Hub: ctx.Hub, sockets, advance, fire: (ev) => (listeners[ev] || []).forEach((f) => f()),
           fireDoc: (ev) => (docListeners[ev] || []).forEach((f) => f()), doc: ctx.document };
}

// 1. ten network failures in a row, then the network is back: it must still reconnect
{
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  for (let i = 0; i < 10; i++) { t.sockets.at(-1).failToConnect(); t.advance(6000); }
  const last = t.sockets.at(-1);
  assert.equal(t.sockets.length, 11, "kept retrying through network failures");
  last.accept(); last.welcome();
  assert.equal(last.readyState, 1);
  console.log("ok 1 network failures keep retrying (11 attempts), then reconnects");
}
// 2. three real refusals (opened, never welcomed) still stop the retries
{
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  for (let i = 0; i < 3; i++) { t.sockets.at(-1).accept(); t.sockets.at(-1).refuse(); t.advance(6000); }
  const n = t.sockets.length;
  t.advance(60000);
  assert.equal(n, 3, "stopped after three refusals");
  assert.equal(t.sockets.length, 3, "no further attempts");
  t.fire("online");                                      // and a network event doesn't restart it
  t.advance(1000);
  assert.equal(t.sockets.length, 3);
  console.log("ok 2 three refusals still give up ('room full'), even on 'online'");
}
// 3. waking up reconnects immediately instead of waiting out the backoff, with one socket only
{
  const t = load();
  t.Hub.connect("/games/bluff/ws", { onState() {} });
  t.sockets[0].accept(); t.sockets[0].welcome();
  t.sockets[0].refuse();                                 // connection dropped (phone slept)
  for (let i = 0; i < 4; i++) { t.sockets.at(-1).failToConnect(); t.advance(i < 3 ? 6000 : 100); }
  const before = t.sockets.length;
  t.fireDoc("visibilitychange");                         // screen back on
  t.advance(1);
  assert.equal(t.sockets.length, before + 1, "reconnected at once");
  t.fire("online"); t.advance(1);                         // a second event while connecting: no duplicate
  assert.equal(t.sockets.length, before + 1, "no duplicate socket while one is connecting");
  t.advance(10000);
  assert.equal(t.sockets.length, before + 1, "the cancelled backoff timer did not fire later");
  console.log("ok 3 wake/online reconnects at once, no duplicate sockets");
}
console.log("hubnet reconnect: 3/3 passed");
