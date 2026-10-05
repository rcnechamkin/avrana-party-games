// EXPO's presentation director (AVR-267), without a browser:  node tests/expo_director_test.mjs
//
// What it proves about games/expo/web/director.js and slots.js:
//   * the planner consumes events by seq and settles, without replaying anything, on a first
//     view, a reconnect, a gap, a duplicate push, a rewind, a hidden tab, a backlog and a new
//     attempt (where it briefs a mission start once);
//   * event -> intensity tier -> effect, with every duration inside its tier and a trick's
//     resolution inside the server's hold or not played at all;
//   * the three fidelity tiers: only the high tier moves anything, the low tier animates
//     nothing, reduced motion always wins;
//   * it cannot change the game: its source holds no connection and no sender, it is handed a
//     deep-frozen view and never throws on it, and it animates transform and opacity only;
//   * sound and haptics: nothing before a gesture, nothing against a preference, an empty audio
//     slot is silent;
//   * three throws and it stands down;
//   * the asset slots: each is named in the stylesheet or the page, every audio slot is empty
//     (no final asset is shipped), and nothing in EXPO's web directory is fetched from outside.
// The browser playtests prove the same things on a real page (tests/playtest_expo*.mjs).
import fs from "fs";
import path from "path";
import assert from "node:assert/strict";
import { createRequire } from "module";
import { fileURLToPath } from "url";

const require = createRequire(import.meta.url);
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "games", "expo", "web");
const D = require(path.join(WEB, "director.js")), SLOTS = require(path.join(WEB, "slots.js"));
const read = name => fs.readFileSync(path.join(WEB, name), "utf8");
const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---- fixtures ---------------------------------------------------------------------------------
const freeze = v => { if (v && typeof v === "object") { Object.freeze(v); Object.values(v).forEach(freeze); } return v; };
const ev = (seq, type, more = {}) => ({seq, type, attempt: 1, mission: 1, trick: 1, ...more});
const game = (more = {}) => ({attempt: 1, attempts: 1, revision: 10, stage: "in_trick", mission: {id: 1}, seats: ["p1","p2","p3"], captain: "p1", leader: "p1", turn: "p2",
  trick: [{seat: "p1", card: "blue:8"}], last_trick: null, tasks: [], result: null, resolving: null, cause: null, events: [], event_seq: 0,
  me: {seat: "p2", hand: ["blue:1","green:3"], legal_cards: ["blue:1"], play_reason: null, communication_options: {}}, ...more});
const view = g => freeze({phase: "playing", players: [], game: g});
const primed = (seq, attempt = 1) => ({primed: true, attempt, seq});

// A page that records what is animated. Every selector resolves to a node; a node's children
// (its .fx overlay, its .card) are nodes too.
function page({hidden = false} = {}) {
  const animations = [], made = new Map();
  const node = key => {
    if (!made.has(key)) made.set(key, {key, hidden: false, dataset: {card: "blue:1", seat: "p1"}, children: [],
      querySelector: sel => node(key + " " + sel), querySelectorAll: () => [],
      getBoundingClientRect: () => ({left: 10, top: 20, width: 40, height: 50}),
      replaceChildren(...kids) { this.children = kids; },
      animate(frames, options) { const a = {id: "", frames, options, node: key, finished: Promise.resolve(), finish() { a.done = true; }}; animations.push(a); return a; }});
    return made.get(key);
  };
  const doc = {hidden, documentElement: {dataset: {}}, querySelector: sel => node(sel),
    querySelectorAll: sel => /\[data-(card|seat)\]/.test(sel) ? [node(sel + "#1"), node(sel + "#2")] : [],
    createElement: tag => ({tag, textContent: ""})};
  return {doc, animations};
}
function director(over = {}) {
  const pg = page(over.page), vibrated = [], played = [];
  const prefs = {reducedFx: false, haptics: true, sound: true, ...over.prefs};
  const d = D.create({doc: pg.doc, prefs, slots: over.slots || SLOTS, clock: over.clock || (() => 1_000_000), stored: () => over.stored ?? null, canAnimate: over.canAnimate ?? true,
    caps: over.caps || {memory: 8, cores: 8, saveData: false}, vibrate: p => vibrated.push(p), audio: (src, volume) => played.push([src, volume]), nameOf: s => s.toUpperCase(), conditions: () => "Attempt 1 · Radio clear"});
  return {d, ...pg, vibrated, played, prefs};
}
// Prime on a quiet table, then show `events` as the next push.
function show(over, events, more = {}) {
  const x = director(over);
  x.d.after(view(game({event_seq: events[0].seq - 1})));
  x.why = x.d.after(view(game({events, event_seq: events.at(-1).seq, ...more})));
  return x;
}
const props = a => [...new Set(a.frames.flatMap(f => Object.keys(f)))].filter(k => k !== "offset").sort();

// ---- the planner --------------------------------------------------------------------------------
test("a first view settles: the events already in it are the state, not news", () => {
  const g = game({events: [ev(4, "CARD_PLAYED"), ev(5, "TURN_STARTED")], event_seq: 5});
  const plan = D.advance(D.freshCursor(), view(g));
  assert.deepEqual([plan.why, plan.cues, plan.cursor], ["first-view", [], primed(5)]);
});
test("fresh events are presented once, oldest first, each with its intensity tier", () => {
  const g = game({events: [ev(6, "TURN_STARTED"), ev(5, "CARD_PLAYED"), ev(4, "CARD_PLAYED")], event_seq: 6});
  const plan = D.advance(primed(4), view(g));
  assert.equal(plan.why, "live");
  assert.deepEqual(plan.cues.map(c => [c.seq, c.type, c.tier]), [[5, "CARD_PLAYED", "micro"], [6, "TURN_STARTED", "micro"]]);
  assert.deepEqual(D.advance(plan.cursor, view(g)).cues, [], "the same push again presents nothing");
  assert.equal(D.advance(plan.cursor, view(g)).why, "duplicate");
});
test("a gap settles: missing sequence numbers are never guessed and nothing after them is played", () => {
  for (const events of [[ev(7, "CARD_PLAYED")], [ev(5, "CARD_PLAYED"), ev(7, "CARD_PLAYED")], []]) {
    const plan = D.advance(primed(4), view(game({events, event_seq: 7})));
    assert.deepEqual([plan.why, plan.cues, plan.cursor.seq], ["gap", [], 7]);
  }
  // The window a viewer is sent holds only the latest trick: older events are simply not there.
  const late = D.advance(primed(3), view(game({events: [ev(30, "TRICK_RESOLVED"), ev(31, "TURN_STARTED")], event_seq: 31})));
  assert.deepEqual([late.why, late.cues], ["gap", []]);
});
test("a rewind, a hidden tab and a backlog settle", () => {
  assert.equal(D.advance(primed(40), view(game({events: [ev(2, "CARD_PLAYED")], event_seq: 2}))).why, "rewound");
  const fresh = game({events: [ev(5, "CARD_PLAYED")], event_seq: 5});
  assert.deepEqual([D.advance(primed(4), view(fresh), {hidden: true}).why, D.advance(primed(4), view(fresh), {hidden: true}).cues], ["hidden", []]);
  const many = Array.from({length: D.MAX_BATCH + 1}, (_, i) => ev(5 + i, "CARD_PLAYED"));
  assert.deepEqual(D.advance(primed(4), view(game({events: many, event_seq: many.at(-1).seq}))).cues, []);
});
test("a new attempt never replays the old one, and a mission start is briefed once", () => {
  const start = game({attempt: 2, stage: "allocation", trick: [], events: [ev(9, "MISSION_MODIFIER_ACTIVATED", {attempt: 2})], event_seq: 9});
  const plan = D.advance(primed(8, 1), view(start));
  assert.equal(plan.why, "new-attempt");
  assert.deepEqual(plan.cues.map(c => [c.type, c.tier, c.short]), [["BRIEFING", "cinematic", false]]);
  assert.deepEqual(D.advance(primed(8, 1), view(start), {briefed: true}).cues, [], "not twice in one tab");
  assert.equal(D.advance(primed(8, 1), view(game({...start, attempts: 2}))).cues[0].short, true, "a repeated attempt gets the short one");
  // An attempt met in the middle of play, or already decided, is not a mission start.
  assert.deepEqual(D.advance(primed(8, 1), view(game({attempt: 2, event_seq: 9}))).cues, []);
  assert.deepEqual(D.advance(primed(8, 1), view(game({attempt: 2, stage: "allocation", trick: [], result: {status: "failed", reason: "x"}, event_seq: 9}))).cues, []);
  assert.deepEqual(D.advance(D.freshCursor(), view(start), {briefed: true}).cues, [], "nor is a reload during the preparation");
});
test("no table is not an error, and the cursor always ends on the newest sequence number", () => {
  assert.deepEqual(D.advance(primed(5), freeze({phase: "lobby", game: null})), {cursor: {primed: true, attempt: null, seq: 0}, cues: [], why: "no-table"});
  for (const [cursor, g] of [[primed(4), game({events: [ev(9, "CARD_PLAYED")], event_seq: 9})], [D.freshCursor(), game({event_seq: 3})], [primed(1, 7), game({event_seq: 2})]])
    assert.equal(D.advance(cursor, view(g)).cursor.seq, g.event_seq);
});

// ---- tiers and timing ---------------------------------------------------------------------------
test("every event the engine emits has an intensity tier, and every duration is inside its tier", () => {
  const engine = fs.readFileSync(path.resolve(WEB, "..", "engine.py"), "utf8");
  const emitted = [...engine.matchAll(/'([A-Z]+(?:_[A-Z]+)+)'/g)].map(m => m[1]).filter(t => /^(TURN|CARD|TRICK|COMMUNICATION|OBJECTIVE|MISSION|PLAYER)_/.test(t));
  assert.ok(emitted.length >= 11);
  for (const type of new Set(emitted)) assert.ok(D.INTENSITY[type], `${type} has a tier`);
  const within = (ms, tier) => ms >= D.TIER_MS[tier][0] && ms <= D.TIER_MS[tier][1];
  for (const k of ["cardArrive", "handClose", "turn", "reconnect", "progress"]) assert.ok(within(D.TIMING[k], "micro"), k);
  for (const k of ["trick", "radio", "objective", "modifier"]) assert.ok(within(D.TIMING[k], "gameplay"), k);
  for (const k of ["result", "briefing", "briefingShort"]) assert.ok(within(D.TIMING[k], "cinematic"), k);
  assert.deepEqual([D.TIER_MS.micro, D.TIER_MS.gameplay, D.TIER_MS.cinematic], [[100, 400], [500, 1500], [2000, 6000]]);
  assert.ok(D.TIMING.briefing >= 5000 && D.TIMING.briefing <= 7000, "the briefing is 5 to 7 seconds");
  assert.deepEqual([D.INTENSITY.MISSION_FAILURE, D.INTENSITY.MISSION_SUCCESS], ["cinematic", "cinematic"]);
  assert.deepEqual(Object.entries(D.INTENSITY).filter(([, tier]) => tier === "cinematic").map(([type]) => type).sort(), ["MISSION_FAILURE", "MISSION_SUCCESS"], "cinematic beats are rare");
});
test("a trick's resolution fits inside the server's hold, or is not played", () => {
  const hold = Number(/RESOLVE_HOLD = ([\d.]+)/.exec(fs.readFileSync(path.resolve(WEB, "..", "game.py"), "utf8"))[1]) * 1000;
  assert.ok(D.TIMING.trick + D.TIMING.trickMargin <= hold && D.TIMING.trick < 1000, "an ordinary resolution is under the hold and under a second");
  const now = 5_000_000, until = ms => ({resolving: {trick: 1, until: (now + ms) / 1000}});
  assert.equal(D.trickBudget(game(until(hold)), now), D.TIMING.trick);
  const tight = D.trickBudget(game(until(400)), now);
  assert.ok(tight > 0 && now + tight <= now + 400, "a late start is shortened to end before the hold does");
  for (const ms of [200, 0, -900]) assert.equal(D.trickBudget(game(until(ms)), now), 0, "too late: the board already shows the result");
  assert.equal(D.trickBudget(game({resolving: {trick: 1}}), now), 0, "no moment given, nothing played");
  assert.equal(D.trickBudget(game({resolving: null}), now), 0, "a table that is not resolving is not held");
  assert.equal(D.trickBudget(game({result: {status: "failed", reason: "x"}}), now), D.TIMING.trick, "the trick that ends a mission is not held");
});
const TRICK = [ev(5, "CARD_PLAYED", {seat: "p3", controller: "p3", card: "blue:9", position: 3, lead_suit: "blue"}),
  ev(6, "TRICK_RESOLVED", {winner: "p3", winning_card: "blue:9", leader: "p1", lead_suit: "blue", plays: [{seat: "p1", card: "blue:8"}, {seat: "p2", card: "blue:1"}, {seat: "p3", card: "blue:9"}]}),
  ev(7, "OBJECTIVE_COMPLETED", {objective: "t1", scope: "task", owner: "p3"})];
const HELD = {trick: [], last_trick: {index: 1, winner: "p3", plays: TRICK[1].plays}, resolving: {trick: 1, until: (1_000_000 + 800) / 1000}};
test("on the page: a resolved trick's animations all end inside the hold", () => {
  const x = show({}, TRICK, HELD);
  assert.equal(x.why, "live");
  const trick = x.animations.filter(a => a.id === "expo-fx:trick");
  assert.ok(trick.length >= 4, "the lead suit, each card and the winner are presented");
  for (const a of trick) assert.ok((a.options.delay || 0) + a.options.duration <= 800 - D.TIMING.trickMargin + 1, `${a.node} ends inside the hold`);
  assert.equal(x.d.stats.lastTrick.budget, D.TIMING.trick);
  assert.ok(x.d.stats.lastTrick.ends <= HELD.resolving.until * 1000);
  // The objective's own beat starts inside the hold and waits for nothing.
  assert.ok(x.animations.some(a => a.id === "expo-fx:objective" && a.options.delay < 800));
  // A hold that is nearly over: the trick is not played, and the board is already right.
  const late = show({clock: () => 1_000_000 + 700}, TRICK, HELD);
  assert.deepEqual(late.animations.filter(a => a.id === "expo-fx:trick"), []);
  assert.ok(late.d.stats.settled.includes("trick-late"));
});

// ---- fidelity -----------------------------------------------------------------------------------
test("the fidelity tier: reduced motion wins, then the choice, then the device", () => {
  const f = D.fidelity, ok = {animate: true};
  assert.equal(f({...ok}), "high");
  for (const stored of ["high", "medium", "low"]) assert.equal(f({...ok, stored}), stored);
  assert.equal(f({...ok, stored: "high", reduced: true}), "low");
  assert.equal(f({stored: "high", animate: false}), "low");
  for (const weak of [{memory: 2}, {cores: 2}, {saveData: true}]) assert.equal(f({...ok, ...weak}), "medium");
  assert.equal(f({...ok, memory: 2, stored: "high"}), "high", "an explicit choice beats the guess");
  assert.equal(f({...ok, stored: "off"}), "off"); assert.equal(f({...ok, stored: "nonsense"}), "high");
});
test("high moves, medium only fades, low animates nothing, and all three leave the same page", () => {
  const all = [...TRICK, ev(8, "COMMUNICATION_SENT", {seat: "p1", card: "blue:8", mode: "normal", token: "personal", assertion: "highest"}), ev(9, "TURN_STARTED", {seat: "p2", controller: "p2", lead: true})];
  const high = show({}, all, HELD), medium = show({stored: "medium"}, all, HELD), low = show({stored: "low"}, all, HELD), reduced = show({prefs: {reducedFx: true}}, all, HELD);
  assert.equal(high.doc.documentElement.dataset.expoFx, "high");
  assert.ok(high.animations.some(a => props(a).includes("transform")), "the high tier moves things");
  for (const a of high.animations) assert.deepEqual(props(a).filter(p => !["opacity", "transform"].includes(p)), [], `only transform and opacity are animated (${a.node})`);
  assert.equal(medium.doc.documentElement.dataset.expoFx, "medium");
  assert.ok(medium.animations.length > 0);
  for (const a of medium.animations) assert.deepEqual(props(a), ["opacity"], `the medium tier only fades (${a.node})`);
  for (const still of [low, reduced]) { assert.equal(still.doc.documentElement.dataset.expoFx, "low"); assert.deepEqual(still.animations, [], "the low tier animates nothing"); }
  // None of them writes game meaning anywhere: the only thing a tier changes on the page is
  // the tier's own name on the root element.
  for (const x of [high, medium, low]) assert.deepEqual(Object.keys(x.doc.documentElement.dataset), ["expoFx"]);
});
test("cinematic beats are the high tier's only, and end at a tap", () => {
  const start = game({attempt: 2, stage: "allocation", trick: [], event_seq: 3});
  const run = over => { const x = director(over); x.d.after(view(game({event_seq: 0}))); x.d.after(view(start)); return x; };
  const high = run({});
  const cine = high.animations.filter(a => a.id === "expo-fx:cine");
  assert.ok(cine.length > 0 && high.d.stats.performed.some(p => p.effect === "briefing" && p.ms === D.TIMING.briefing));
  for (const a of cine) assert.ok((a.options.delay || 0) + a.options.duration <= D.TIMING.briefing + 1, "nothing outlasts the briefing");
  high.d.gesture();
  assert.ok(cine.every(a => a.done), "a tap or a key finishes it");
  for (const stored of ["medium", "low"]) assert.deepEqual(run({stored}).animations.filter(a => a.id === "expo-fx:cine"), []);
});
test("a briefing ends when the table leaves the preparation, and not before", () => {
  const start = game({attempt: 2, stage: "allocation", trick: [], event_seq: 3});
  const begin = () => { const x = director({}); x.d.after(view(game({event_seq: 0}))); x.d.after(view(start)); return x; };
  const cine = x => x.animations.filter(a => a.id === "expo-fx:cine");
  const still = begin();
  still.d.after(view(game({...start, stage: "assistance", revision: 11})));       // still preparing
  assert.ok(cine(still).length > 0 && cine(still).every(a => !a.done), "the briefing runs on through the preparation");
  for (const next of [game({attempt: 2, stage: "before_trick", trick: [], event_seq: 4, events: [ev(4, "TURN_STARTED", {attempt: 2, seat: "p1"})]}),
    game({attempt: 2, stage: "allocation", trick: [], result: {status: "failed", reason: "x"}, event_seq: 3}), null]) {
    const x = begin(), running = cine(x);
    x.d.after(next ? view(next) : freeze({phase: "lobby", game: null}));
    assert.ok(running.length > 0 && running.every(a => a.done), "the mission stage is given back at once");
  }
});

// ---- it cannot change the game ------------------------------------------------------------------
test("the director's source holds no connection and nothing that sends", () => {
  const src = read("director.js").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  for (const banned of [/\bconn\b/, /WebSocket/, /\bfetch\s*\(/, /XMLHttpRequest/, /sendBeacon/, /\.send\s*\(/, /postMessage/, /hostAction/, /localStorage/, /\bST\b/, /\beval\b|Function\s*\(/, /\.onclick|addEventListener/, /\.click\s*\(/, /dispatchEvent/, /(?<!stats)\.disabled\s*=(?!=)|\.inert\s*=(?!=)/])
    assert.doesNotMatch(src, banned, `director.js must not contain ${banned}`);
  // The client hands it a clock, preferences, slots and a frozen copy of the view; nothing else.
  const client = read("client.js"), made = client.slice(client.indexOf("ExpoDirector.create({"), client.indexOf("});", client.indexOf("ExpoDirector.create({")));
  assert.deepEqual([...made.matchAll(/\bconn\b[.\w]*/g)].map(m => m[0]), ["conn.now"], "of the connection, only its clock is read");
  assert.match(client, /director\.after\(frozen\(structuredClone\(st\)\)\)/, "the view it sees is a frozen copy");
  // Every call into it is fenced: a throw is caught and counted.
  const calls = [...client.matchAll(/director\.(before|after|resync|gesture|visibility|skip)\(/g)];
  assert.ok(calls.length >= 5);
  for (const c of calls) assert.match(client.slice(Math.max(0, c.index - 40), c.index), /present\(\(\) => $/, `director.${c[1]} is called through the guard`);
});
test("it reads a deep-frozen view without a throw, whatever is in it", () => {
  const all = [...TRICK, ev(8, "COMMUNICATION_SENT", {seat: "p2", card: "blue:1", mode: "currents", token: "shared"}), ev(9, "OBJECTIVE_FAILED", {objective: "t2", scope: "task", owner: "p1"}),
    ev(10, "OBJECTIVE_PROGRESS", {objective: "t3", owner: "p3"}), ev(11, "MISSION_MODIFIER_ACTIVATED", {modifier: "timer", value: 150}), ev(12, "PLAYER_RECONNECTED", {seat: "p1"}),
    ev(13, "MISSION_FAILURE", {reason: "x", cause: null}), ev(14, "MISSION_SUCCESS", {reason: "y"}), ev(15, "SOMETHING_NEW", {})];
  for (const stored of ["high", "medium", "low"]) {
    const x = show({stored}, all, {...HELD, result: {status: "failed", reason: "x"}});
    assert.equal(x.why, "live"); assert.equal(x.d.stats.errors, 0);
    assert.ok(!x.d.stats.performed.some(p => p.type === "SOMETHING_NEW"), "an event it does not know is left alone");
  }
  // And a spectator, who has no hand and no seat.
  assert.equal(show({}, all, {...HELD, me: null}).d.stats.errors, 0);
});
test("three throws and it stands down; the client's guard is what counts them", () => {
  const x = director({});
  assert.equal(x.d.fidelity, "high");
  x.d.failed(); x.d.failed();
  assert.equal(x.d.stats.disabled, false);
  x.d.failed();
  assert.equal(x.d.stats.disabled, true); assert.equal(x.d.fidelity, "off");
  x.d.after(view(game({event_seq: 4}))); x.d.after(view(game({events: TRICK, event_seq: 7, ...HELD})));
  assert.deepEqual(x.animations, [], "a director that stood down shows nothing");
});

// ---- sound and haptics --------------------------------------------------------------------------
const TURN = [ev(5, "TURN_STARTED", {seat: "p2", controller: "p2", lead: false})];
test("nothing is felt or heard before a gesture, or against a preference", () => {
  const quiet = show({}, TURN);
  assert.deepEqual([quiet.vibrated, quiet.played], [[], []], "no gesture yet");
  const felt = director({}); felt.d.gesture(); felt.d.after(view(game({event_seq: 4}))); felt.d.after(view(game({events: TURN, event_seq: 5})));
  assert.deepEqual(felt.vibrated, [SLOTS.haptics["turn.mine"]], "my own turn is felt");
  assert.deepEqual(felt.played, [], "an empty audio slot is silent");
  const off = director({prefs: {haptics: false}}); off.d.gesture(); off.d.after(view(game({event_seq: 4}))); off.d.after(view(game({events: TURN, event_seq: 5})));
  assert.deepEqual(off.vibrated, []);
  // A filled audio slot plays after a gesture, with sound on, and never otherwise.
  const filled = {...SLOTS, audio: {...SLOTS.audio, "turn.mine": {src: "audio/turn.ogg", volume: .4}}};
  const run = (prefs, tap) => { const x = director({slots: filled, prefs}); if (tap) x.d.gesture(); x.d.after(view(game({event_seq: 4}))); x.d.after(view(game({events: TURN, event_seq: 5}))); return x.played; };
  assert.deepEqual(run({}, true), [["audio/turn.ogg", .4]]);
  assert.deepEqual(run({}, false), []); assert.deepEqual(run({sound: false}, true), []);
  // Somebody else's turn is neither felt nor heard.
  const theirs = director({slots: filled}); theirs.d.gesture(); theirs.d.after(view(game({event_seq: 4}))); theirs.d.after(view(game({events: [ev(5, "TURN_STARTED", {seat: "p3", controller: "p3"})], event_seq: 5})));
  assert.deepEqual([theirs.vibrated, theirs.played], [[], []]);
});

// ---- asset slots --------------------------------------------------------------------------------
test("every asset slot is a named placeholder, every audio slot is empty, and nothing is fetched from outside", () => {
  const css = read("expo.css"), html = read("index.html");
  for (const [name, slot] of Object.entries(SLOTS.art)) {
    assert.equal(slot.status, "placeholder", `${name} is a placeholder, not final art`);
    if (slot.css) assert.ok(css.includes(slot.css + ":") && css.includes(`var(${slot.css})`), `${name}: ${slot.css} is defined and used in expo.css`);
    if (slot.symbol) assert.ok(html.includes(`<symbol id="${slot.symbol}"`) && (html + read("client.js")).includes(slot.symbol), `${name}: #${slot.symbol} is in index.html`);
  }
  for (const used of new Set([...css.matchAll(/--slot-[a-z-]+/g)].map(m => m[0]))) assert.ok(Object.values(SLOTS.art).some(s => s.css === used), `${used} is in the manifest`);
  for (const [name, slot] of Object.entries(SLOTS.audio)) assert.equal(slot, null, `${name}: no audio is shipped`);
  for (const [name, pattern] of Object.entries(SLOTS.haptics)) assert.ok(pattern === null || (Array.isArray(pattern) && pattern.every(n => Number.isInteger(n) && n > 0 && n <= 100)), name);
  const docs = fs.readFileSync(path.resolve(WEB, "..", "..", "..", "docs", "ASSETS.md"), "utf8");
  for (const name of [...Object.keys(SLOTS.art), ...Object.keys(SLOTS.audio)]) assert.ok(docs.includes("`" + name + "`"), `${name} is documented in docs/ASSETS.md`);
  // An offline appliance: no file here names anything outside it (the SVG namespace is a name).
  for (const file of fs.readdirSync(WEB)) {
    const text = read(file).replaceAll("http://www.w3.org/2000/svg", "");
    assert.doesNotMatch(text, /https?:\/\/|url\(\s*["']?(?!#)|@import|\.(png|jpe?g|webp|gif|mp3|ogg|wav|woff2?)\b/i, `${file} fetches nothing`);
  }
  assert.deepEqual(fs.readdirSync(WEB).sort(), ["client.js", "director.js", "expo.css", "index.html", "slots.js"], "no asset file was added");
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log("ok   " + name); }
  catch (error) { failed++; console.log("FAIL " + name + "\n" + (error.stack || error)); }
}
console.log(failed ? `${failed} of ${tests.length} failed` : `PASS: ${tests.length} director tests`);
process.exit(failed ? 1 : 0);
