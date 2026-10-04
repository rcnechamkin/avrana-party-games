// The Party bridge on a game page (avrana-party ADR 0013, AVR-226).
//   node --test tests/avrana_bridge_test.mjs
// web/avrana-party-bridge.js is avrana-party's web/party/bridge/shim.js, vendored unchanged; it is
// checked here against the vendored contract vectors. web/avrana-integration.js decides, from this
// server's configuration alone, whether a page shares the Party's origin (the Party's own module
// runs in the page, as before) or is on the game origin (the page gets the Party only through the
// shim), and on the game origin publishes the window.AvranaParty that game chrome already uses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { PROTOCOL, parsePush } from "../web/avrana-party-bridge.js";

const vectors = JSON.parse(readFileSync(new URL("./vectors/party-bridge.v1.json", import.meta.url)));
const source = readFileSync(new URL("../web/avrana-integration.js", import.meta.url), "utf8");
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setImmediate(r)); };
const GAMES = "https://games.avrana.net", PARTY = "https://party.avrana.net";

test("the vendored shim speaks the protocol the vendored vectors pin", () => {
  assert.equal(PROTOCOL, vectors.protocol);
  for (const v of vectors.pushes) assert.equal(Boolean(parsePush(v.message)), v.accept, v.name);
});

function element(tag) {
  const el = { tag, children: [], attrs: {}, hidden: false, listeners: {},
    setAttribute(k, v) { el.attrs[k] = v; }, getAttribute: (k) => el.attrs[k],
    toggleAttribute(k, on) { if (on) el.attrs[k] = ""; else delete el.attrs[k]; },
    addEventListener(t, fn) { el.listeners[t] = fn; },
    append(...kids) { el.children.push(...kids); }, appendChild(kid) { el.children.push(kid); return kid; } };
  return el;
}

/** A game page: /games/<slug>/?avrana=1 on `origin`, whose server answers /api/avrana with `config`:
    an object is the 200 body, a number is that status, an Error is a request that reached nothing.
    A list is one answer per request, the last repeated. `tick()` fires the timers set so far. */
function page({ origin = GAMES, slug = "bluff", config = { partyOrigin: PARTY }, shell = true, search = "?avrana=1", shimFails = 0 } = {}) {
  const imports = [], fetched = [], returns = [element("a")], answers = Array.isArray(config) ? [...config] : [config];
  let conn = null, timers = [];
  const connectParty = (opts) => {
    const listeners = new Set();
    let view = null;
    conn = { opts, ended: 0,
      view: () => view, active: () => Boolean(view && view.party && view.member), isHost: () => Boolean(view && view.host),
      hostName: () => (view ? view.hostName : null), location: () => (view ? view.location : { at: "home", game: null }),
      onChange(fn) { listeners.add(fn); }, ticket: async () => ({ ok: true }),
      end: async () => { conn.ended++; return { ok: true, error: null }; },
      goHome: async () => ({ ok: true, error: null }), playAgain: async () => ({ ok: true, error: null }),
      push(v) { view = v; for (const fn of listeners) fn(v); } };
    return conn;
  };
  const body = element("body"), head = element("head"), root = element("html");
  root.dataset = {};
  const window = { isSecureContext: true };
  const ctx = {
    window, console, URL, URLSearchParams,
    location: { origin, pathname: `/games/${slug}/`, search, href: `${origin}/games/${slug}/${search}` },
    AbortController,
    setTimeout: (fn) => timers.push(fn), clearTimeout(id) { if (id) timers[id - 1] = null; },
    fetch: async (url, init) => {
      fetched.push([url, init]);
      const answer = answers.length > 1 ? answers.shift() : answers[0];
      if (answer === "hang") {              // a server that never answers: only giving up ends it
        return new Promise((resolve, reject) => init.signal.addEventListener("abort", () => reject(new Error("aborted"))));
      }
      if (answer instanceof Error) throw answer;
      if (typeof answer === "number") return { ok: answer >= 200 && answer < 300, status: answer, json: async () => { throw new Error("no body"); } };
      return { ok: true, status: 200, json: async () => answer };
    },
    document: { readyState: "complete", documentElement: root, body, head, createElement: element, addEventListener() {},
      querySelectorAll: (sel) => (sel === "[data-avrana-return]" ? returns : []),
      querySelector: (sel) => (sel === "[data-avrana-party-shell]" && shell ? element("div") : null) },
  };
  // The page's two dynamic imports are answered here: Node's vm has no stable hook for them.
  ctx.importModule = async (spec) => {
    imports.push(spec);
    if (spec.startsWith("/shared/avrana-party-bridge.js")) {
      if (shimFails-- > 0) throw new Error("failed to fetch module");
      return { connectParty };
    }
    return { gameOfPath: () => slug, startPartyFollow: async () => null };
  };
  vm.createContext(ctx);
  assert.equal(source.split("import('").length, 3);
  vm.runInContext(source.replaceAll("import('", "importModule('"), ctx);
  const tick = async () => { const due = timers; timers = []; for (const fn of due) if (fn) fn(); await settle(); };
  return { window, root, body, imports, fetched, returns, tick, conn: () => conn, integration: window.AvranaIntegration };
}
const member = (more = {}) => ({ party: true, member: true, host: false, hostName: "Ana",
  location: { at: "game", game: "bluff" }, round: null, ...more });

test("on the game origin the page reaches the Party through the vendored shim, bound to its own game", async () => {
  const p = page();
  await settle();
  assert.deepEqual(p.fetched.map((f) => f[0]), ["/api/avrana"]);
  assert.deepEqual(p.imports, ["/shared/avrana-party-bridge.js"]);       // never the Party's module
  assert.deepEqual({ ...p.conn().opts }, { partyOrigin: PARTY, game: "bluff" });
  assert.equal(await p.integration.party, p.conn());
  assert.equal(p.integration.home, PARTY + "/party/");
  assert.equal(p.returns[0].href, PARTY + "/party/");
});

test("on the game origin a member's page gets the same AvranaParty a same-origin page has", async () => {
  const p = page();
  await settle();
  assert.equal(p.window.AvranaParty, undefined);                          // not before the Party says so
  p.conn().push(member({ member: false }));
  assert.equal(p.window.AvranaParty, undefined);                          // a phone that is not in the party
  assert.equal(p.root.dataset.avranaParty, undefined);
  p.conn().push(member({ host: true }));
  const P = p.window.AvranaParty;
  assert.equal(P.active, true);                                           // a value, as game chrome reads it
  assert.equal(P.isHost(), true);
  assert.equal(P.hostName(), "Ana");
  assert.deepEqual({ ...P.location() }, { at: "game", game: "bluff" });
  assert.equal((await P.end()).ok, true);
  assert.equal(p.root.dataset.avranaParty, "on");
  for (const verb of ["end", "goHome", "playAgain", "onChange", "view"]) assert.equal(typeof P[verb], "function", verb);
  assert.equal(P.ticket, undefined);                                      // game chrome gets no ticket verb
});

test("on the game origin a game with no shell of its own gives the host one End, tapped twice", async () => {
  const p = page({ slug: "expo", shell: false });
  await settle();
  p.conn().push(member({ location: { at: "game", game: "expo" } }));
  const nav = p.body.children[0];
  assert.equal(nav.children.find((c) => c.id === "avrana-party-end"), undefined);      // a guest gets none
  p.conn().push(member({ host: true, location: { at: "game", game: "expo" } }));
  const end = nav.children.find((c) => c.id === "avrana-party-end");
  assert.equal(end.hidden, false);
  assert.equal(nav.attrs["data-avrana-host"], "");
  await end.listeners.click();
  assert.equal(p.conn().ended, 0);                                        // the first tap only arms it
  await end.listeners.click();
  assert.equal(p.conn().ended, 1);
  p.conn().push(member({ host: true, location: { at: "results", game: "expo" } }));
  assert.equal(end.hidden, true);
});

test("on the game origin a game that draws its own host controls gets no fallback End", async () => {
  const p = page({ shell: true });
  await settle();
  p.conn().push(member({ host: true }));
  assert.equal(p.body.children[0].children.some((c) => c.id === "avrana-party-end"), false);
});

for (const [label, config, origin] of [
  ["no Party origin is configured", { partyOrigin: null }, PARTY],
  ["the configured Party origin is this page's own", { partyOrigin: PARTY }, PARTY],
  ["the server predates the route (404)", 404, PARTY],
  ["the Party origin carries a path", { partyOrigin: "https://evil.example/party" }, GAMES],
  ["the Party origin is not http(s)", { partyOrigin: "javascript://x" }, GAMES],
  ["the Party origin is not a string", { partyOrigin: { href: PARTY } }, GAMES],
]) {
  test(`same-origin behaviour is kept when ${label}`, async () => {
    const p = page({ config, origin });
    await settle();
    assert.equal(await p.integration.party, null);
    assert.deepEqual(p.imports, ["/party/lib/party-follow.js"]);
    assert.equal(p.integration.home, "/party/");
    assert.equal(p.conn(), null);
  });
}

// Only an answer decides. A server that says nothing has not said "same origin": on the game origin
// that guess would leave the page without the Party until it was reloaded.
for (const [label, silence] of [["reaches nothing", new Error("offline")], ["gets a 502", 502], ["gets a 200 that is not JSON", 200]]) {
  test(`a request that ${label} decides nothing; the page asks again and then uses the bridge`, async () => {
    const p = page({ config: [silence, silence, { partyOrigin: PARTY }] });
    await settle();
    assert.deepEqual(p.imports, []);                                      // neither path chosen yet
    assert.equal(p.conn(), null);
    await p.tick();
    assert.deepEqual(p.imports, []);
    await p.tick();
    assert.equal(p.fetched.length, 3);
    assert.deepEqual(p.imports, ["/shared/avrana-party-bridge.js"]);
    assert.equal(await p.integration.party, p.conn());
    assert.equal(p.integration.home, PARTY + "/party/");
  });
}

test("a server that never answers is given up on and asked again, and the bar is never stranded", async () => {
  const p = page({ config: "hang" });
  await settle();
  assert.equal(p.fetched.length, 1);
  const nav = p.body.children[0];
  assert.equal(nav.hidden, true);                                         // waiting for the Party's answer
  await p.tick();                                                         // the request's own limit, and the 4 s reveal
  assert.equal(p.fetched[0][1].signal.aborted, true);
  assert.equal(nav.hidden, false);                                        // shown though nothing has answered
  await p.tick();                                                         // the wait before asking again
  assert.equal(p.fetched.length, 2);
  assert.deepEqual(p.imports, []);                                        // still neither path
});

test("on the game origin a shim that failed to load is fetched again, never taken as no Party", async () => {
  const p = page({ shimFails: 2 });
  await settle();
  assert.equal(p.conn(), null);
  await p.tick();
  await p.tick();
  assert.deepEqual(p.imports, ["/shared/avrana-party-bridge.js", "/shared/avrana-party-bridge.js?retry=1",
    "/shared/avrana-party-bridge.js?retry=2"]);                           // and never the Party's own module
  assert.equal(await p.integration.party, p.conn());
  assert.notEqual(p.conn(), null);
});

test("a page that is not an integrated launch asks nothing and has no Party", async () => {
  const p = page({ search: "" });
  await settle();
  assert.equal(p.integration.integrated, false);
  assert.equal(await p.integration.party, null);
  assert.deepEqual(p.fetched, []);
  assert.deepEqual(p.imports, []);
  assert.equal(p.integration.home, "/");
});

test("the Party origin is never taken from the address", async () => {
  const p = page({ config: { partyOrigin: null }, search: "?avrana=1&partyOrigin=https://evil.example&party=https://evil.example" });
  await settle();
  assert.equal(await p.integration.party, null);
  assert.equal(p.integration.home, "/party/");
});
