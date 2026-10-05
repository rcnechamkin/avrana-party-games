// EXPO in a Party round, in real browsers on phone viewports (AVR-275, AVR-252, AVR-266).
//
//   node tests/playtest_expo_party.mjs [outdir]
//     EXPO_HUMANS=2..5   seated players (default 3; 2 seats Tonoja)
//     EXPO_HOST=spectator   the Party Host watches instead of playing
//     EXPO_PYTHON=...    the interpreter that runs server.py (default: python3, python on Windows)
//
// The script is the Party. It starts its own game server with a party key, launches a signed
// roster the way Party Core does, and answers each page's ticket request with a ticket that says
// whether that participant is the host right now (avrana-party ADR 0006, amendment 2026-10-04).
// The Party's page module (/party/lib/party-follow.js) is replaced by a stub that publishes
// window.AvranaParty from the same truth. Nothing in the game or its client is stubbed.
//
// What it proves: one-viewport play; a pending strategic decision in view for whoever must
// answer; a result that takes over the screen; Party Host and captain as separate authorities
// in the page and at the server; host succession and reconnect; no route to the LAN Games hub.
// A simulated Party and a desktop Chrome are not a real phone (avrana-party docs/TESTING.md).
import os from "os";
import fs from "fs";
import net from "net";
import path from "path";
import crypto from "crypto";
import { spawn } from "child_process";
import { fileURLToPath } from "url";
import assert from "node:assert/strict";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";
import { PHONES, oneViewport, onScreen, has, clickKey, playCard, resultOwnsTheScreen, withLongText } from "./_expo_phone.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = process.argv[2] || path.join(os.tmpdir(), "expo-party-playtest");
const HUMANS = Number(process.env.EXPO_HUMANS || 3);
const WATCHING_HOST = process.env.EXPO_HOST === "spectator";
const PYTHON = process.env.EXPO_PYTHON || (process.platform === "win32" ? "python" : "python3");
const NAMES = ["Ava","Milo","Noor","Iris","Sage","Dana"];
fs.mkdirSync(OUT, {recursive:true});
const pause = ms => new Promise(r => setTimeout(r, ms));

// ---- the Party's side of avrana.party-session/v0 (core/party_protocol.py is the reference) ----
const KEY = crypto.randomBytes(32), SID = "session-" + crypto.randomBytes(16).toString("hex");
const b64 = buf => Buffer.from(buf).toString("base64url");
const canonical = v => Array.isArray(v) ? "[" + v.map(canonical).join(",") + "]"
  : v && typeof v === "object" ? "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}" : JSON.stringify(v);
function seal(payload) {
  const head = "aps0." + b64(canonical(payload));
  return head + "." + b64(crypto.createHmac("sha256", KEY).update(head).digest());
}
const base = (typ, ttl) => { const now = Math.floor(Date.now() / 1000); return {v:"avrana.party-session/v0", typ, iss:"party", aud:"expo", sid:SID, iat:now, exp:now + ttl}; };
const party = {host: null, members: [], ended: 0};          // members: {pid, name, role, page}
const ticketFor = m => seal({...base("ticket", 120), pid:m.pid, role:m.role, jti:crypto.randomBytes(8).toString("hex"), host:party.host === m.pid});

const followStub = member => `
window.__party=${JSON.stringify({me:member.pid, host:party.host, hostName:(party.members.find(m => m.pid === party.host) || {}).name || null, ended:0, home:0})};
export function gameOfPath(p){const m=/^\\/games\\/([a-z][a-z0-9_-]*)\\//.exec(p||"");return m?m[1]:null;}
export async function startPartyFollow(){
  const listeners=new Set(), s=window.__party;
  const api={active:true,view:()=>({}),isHost:()=>s.host===s.me,hostName:()=>s.hostName,location:()=>({at:"game",game:"expo"}),
    end:async()=>{s.ended++;return {ok:true};},goHome:async()=>{s.home++;return {ok:true};},playAgain:async()=>({ok:true}),
    onChange(fn){listeners.add(fn);return()=>listeners.delete(fn);}};
  document.documentElement.dataset.avranaParty="on";window.AvranaParty=api;
  window.__partyMoved=()=>{for(const fn of listeners)fn({});document.dispatchEvent(new CustomEvent("avrana-party",{detail:{}}));};
  return api;
}`;

// ---- the game server, with a party key ---------------------------------------------------------
const freePort = () => new Promise(resolve => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const keys = fs.mkdtempSync(path.join(os.tmpdir(), "expo-party-keys-"));
fs.writeFileSync(path.join(keys, "expo.key"), KEY.toString("hex"), {mode:0o600});
const PORT = await freePort(), BASE = `http://127.0.0.1:${PORT}`;
const server = spawn(PYTHON, ["server.py"], {cwd:ROOT, stdio:["ignore","pipe","pipe"],
  env:{...process.env, LANGAMES_PORT:String(PORT), AVRANA_PARTY_KEYS:keys, AVRANA_PARTY_URL:"http://127.0.0.1:9", EXPO_SNAPSHOT_PATH:""}});
let serverLog = ""; for (const s of [server.stdout, server.stderr]) s.on("data", d => { serverLog += d; });
async function post(route, message) {
  const res = await fetch(`${BASE}/games/expo/avrana/session/v0/${route}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({message})});
  assert.equal(res.status, 200, `the game accepts the Party's ${route}`);
}

const errors = [], visited = new Set();
let browser;
const state = pg => pg.evaluate(() => ST);
const waitRevision = (pg, old) => pg.waitForFunction(r => ST?.game?.revision > r, {}, old);
async function settle() {
  let rev = -1;
  for (const m of party.members) rev = Math.max(rev, (await state(m.page)).game?.revision ?? -1);
  for (const m of party.members) await m.page.waitForFunction(r => ST?.game && ST.game.revision >= r && !ST.game.away.length, {}, rev);
  return state(party.members[0].page);
}
const seated = () => party.members.filter(m => m.role === "player");
async function byPid(pid) { for (const m of seated()) if ((await state(m.page)).you.pid === pid) return m; throw Error("no browser for " + pid); }
// What the page was told when the server refused something.
async function refused(pg, act) {
  const before = (await state(pg)).game.revision;
  const said = await pg.evaluate(run => new Promise((resolve, reject) => {
    const toast = Hub.toast, timer = setTimeout(() => { Hub.toast = toast; reject(Error("the server did not refuse")); }, 6000);
    Hub.toast = (text, kind) => { clearTimeout(timer); Hub.toast = toast; toast.call(Hub, text, kind); resolve({text, kind}); };
    (0, eval)(run);
  }), act);
  assert.equal(said.kind, "err"); assert.equal((await state(pg)).game.revision, before, "a refused request changes nothing");
  await pause(120); return said.text;
}
const SEND_HOST = decision => `conn.hostAction({t:"lifecycle",decision:${JSON.stringify(decision)},attempt:ST.game.attempt,revision:ST.game.revision})`;
const SEND_SEAT = proposal => `conn.send({t:"propose",proposal:${JSON.stringify(proposal)},attempt:ST.game.attempt,revision:ST.game.revision,request:crypto.randomUUID()})`;
// The Party moves the host role: its next tickets say so and every page's Party view follows.
async function makeHost(member) {
  party.host = member.pid;
  for (const m of party.members) await m.page.evaluate((host, name) => { window.__party.host = host; window.__party.hostName = name; window.__partyMoved && window.__partyMoved(); }, member.pid, member.name);
  await pause(80);
}
async function open(member, viewport) {
  const context = await browser.createBrowserContext(), pg = await context.newPage();
  member.page = pg;
  await pg.setViewport({...viewport, deviceScaleFactor:1, isMobile:true, hasTouch:true});
  pg.on("pageerror", e => errors.push(e.message));
  pg.on("framenavigated", f => { if (f === pg.mainFrame() && f.url().startsWith("http")) visited.add(new URL(f.url()).pathname); });
  await pg.setRequestInterception(true);
  pg.on("request", req => {
    const url = new URL(req.url());
    if (url.pathname === "/party/api/session/ticket") return req.respond({status:200, contentType:"application/json", headers:{"Cache-Control":"no-store"},
      body:JSON.stringify({protocol:"avrana.party-session/v0", game:"expo", session:SID, role:member.role, ticket:ticketFor(member), expires_in:120})});
    if (url.pathname === "/party/lib/party-follow.js") return req.respond({status:200, contentType:"text/javascript", body:followStub(member)});
    if (url.pathname.startsWith("/party/")) return req.respond({status:404, body:""});
    return req.continue();
  });
  await pg.goto(BASE + "/games/expo/?avrana=1", {waitUntil:"networkidle2"});
}

let finished = false;
try {
  for (let i = 0; i < 60; i++) { try { if ((await fetch(BASE + "/games/expo/")).ok) break; } catch { /* starting */ } await pause(250); if (i === 59) throw Error("the game server did not start:\n" + serverLog); }
  browser = await puppeteer.launch({executablePath:CHROME_PATH, headless:"new", userDataDir:path.join(OUT, "browser-profile"), args:["--no-sandbox","--disable-gpu"]});
  for (let i = 0; i < HUMANS; i++) party.members.push({pid:"participant-" + crypto.randomBytes(16).toString("hex"), name:NAMES[i], role:"player"});
  if (WATCHING_HOST) party.members.push({pid:"participant-" + crypto.randomBytes(16).toString("hex"), name:"Dana", role:"spectator"});
  party.host = party.members.at(WATCHING_HOST ? -1 : 0).pid;
  // The launch: exactly {participant, name, role}. The game is never told who hosts.
  await post("launch", seal({...base("launch", 30), nonce:crypto.randomBytes(12).toString("hex"), roster:party.members.map(m => ({participant:m.pid, name:m.name, role:m.role}))}));
  for (const [i, m] of party.members.entries()) await open(m, PHONES[i % PHONES.length]);
  for (const m of party.members) await m.page.waitForFunction(() => ST?.game && window.AvranaParty, {timeout:25000});
  const first = (await settle()).game;
  assert.equal(first.lifecycle, "host", "the Party named its host: lifecycle is the host's");
  for (const m of party.members) assert.equal((await state(m.page)).party_round, true);

  // Host and captain are different people (unless the host only watches, who is nobody's captain).
  const captain = await byPid(first.captain);
  let host = WATCHING_HOST ? party.members.at(-1) : seated().find(m => m !== captain);
  await makeHost(host);
  const others = seated().filter(m => m !== host);
  assert.notEqual(host, captain, "the Party Host is not the EXPO captain");
  for (const m of party.members) {
    const told = await m.page.evaluate(() => ({party: document.documentElement.dataset.avranaParty, bar: getComputedStyle(document.getElementById("avrana-navigation")).display,
      links: [...document.querySelectorAll("a[href]")].map(a => new URL(a.href, location.href).pathname), returns: document.querySelectorAll("[data-avrana-return]").length}));
    assert.equal(told.party, "on"); assert.equal(told.bar, "none", "the game owns the viewport: no Party bar");
    assert.deepEqual(told.links.filter(p => p === "/" || p.startsWith("/shared/hub")), [], "no link to the LAN Games hub");
    assert.equal(told.returns, 0, "no generic return link");
    await oneViewport(m.page, `${m.name} at the opening stage`);
  }

  // ---- task selection: the selector acts from the stage, the rest see who is choosing ----
  for (let i = 0; i < 30; i++) {
    const s = await settle(); if (s.game.stage !== "allocation") break;
    const actor = await byPid(s.game.controller), own = (await state(actor.page)).game;
    if (i === 0) for (const m of party.members) { await oneViewport(m.page, "task selection"); await withLongText(m.page, () => oneViewport(m.page, "task selection, long text")); }
    const task = own.tasks.find(t => !t.owner && t.eligible_owners.includes(own.selector));
    await clickKey(actor.page, task ? "task:" + task.id : "pass-task"); await waitRevision(actor.page, own.revision);
  }
  for (const m of seated()) { const s = await state(m.page); for (const t of s.game.tasks) if (t.prediction_required && !t.prediction_committed && (t.owner === s.you.pid || (t.owner === "tonoja" && s.game.captain === s.you.pid))) { const rev = (await state(m.page)).game.revision; await clickKey(m.page, "lock:" + t.id); await waitRevision(m.page, rev); } }
  const ready = (await settle()).game;
  assert.equal(ready.stage, "assistance");

  // ---- Begin: the host's, once the crew has had its say ----
  for (const m of party.members) await oneViewport(m.page, "ready to begin");
  for (const m of party.members.filter(m => m !== host)) {
    assert.equal(await has(m.page, "begin"), null, `${m.name} is not the host and is offered no Begin`);
    assert.match(await m.page.evaluate(() => document.getElementById("dock-host").innerText), new RegExp(`Waiting for ${host.name} to begin`));
  }
  assert.equal((await has(host.page, "begin")).disabled, false);
  // the captain is not the host: the page offers nothing, and the server refuses both ways in
  assert.equal(await refused(captain.page, SEND_SEAT({kind:"begin"})), "Only the Party Host can begin the mission.");
  assert.equal(await refused(captain.page, SEND_HOST({kind:"begin"})), "Only the Party Host can do that.");
  if (!ready.seats.includes("tonoja")) {
    // A strategic decision (distress) is still the crew's: everyone who must answer sees it, in
    // the viewport, with the hand in view (AVR-266), and the host cannot begin past it.
    const asker = others[0], rev = ready.revision;
    await clickKey(asker.page, "distress-left"); for (const m of party.members) await waitRevision(m.page, rev);
    for (const m of seated().filter(m => m !== asker)) {
      for (const size of m === seated().find(x => x !== asker) ? PHONES : [m.page.viewport()]) {
        await m.page.setViewport({...m.page.viewport(), ...size}); await pause(60);
        for (const k of ["agree","decline"]) await onScreen(m.page, k, `${m.name}: the distress decision`);
        await oneViewport(m.page, `${m.name}: the distress decision`);
      }
      assert.match(await m.page.evaluate(() => document.getElementById("status").textContent), /^Your answer is needed: Activate distress/);
      assert.match(await m.page.evaluate(() => document.getElementById("stage").innerText), /Activate distress and pass one color card left/);
    }
    if (seated().includes(host)) assert.equal((await has(host.page, "begin")).disabled, true, "Begin waits for the crew's answer");
    assert.equal(await refused(host.page, SEND_HOST({kind:"begin"})), "The crew is deciding something. Wait for their answer.");
    await host.page.screenshot({path:path.join(OUT, "decision-pending.png")});
    const decliner = seated().find(m => m !== asker), r2 = (await state(decliner.page)).game.revision;
    await clickKey(decliner.page, "decline"); for (const m of party.members) await waitRevision(m.page, r2);
    assert.equal((await settle()).game.proposal, null);
    // the host's own authority stops at the table's routine steps
    assert.equal(await refused(host.page, SEND_HOST({kind:"distress", direction:"left"})), "The crew decides that together.");
  }
  {
    const rev = (await state(host.page)).game.revision;
    await clickKey(host.page, "begin"); for (const m of party.members) await waitRevision(m.page, rev);
    const began = (await settle()).game;
    assert.equal(began.stage, "before_trick"); assert.equal(began.proposal, null, "nobody voted");
    assert.equal(began.captain, first.captain); assert.equal(began.turn, first.captain, "the captain still opens the first trick");
  }

  // ---- ordinary trick play, on one screen ----
  let plays = 0, succession = false, reconnected = false;
  for (let i = 0; i < 90; i++) {
    const s = await settle(); if (s.game.result) break;
    const actor = await byPid(s.game.turn === "tonoja" ? s.game.captain : s.game.turn), g = (await state(actor.page)).game;
    if (plays < 2 * s.game.seats.length) {
      for (const m of party.members) await oneViewport(m.page, `${m.name} during trick play`);
      assert.match(await actor.page.evaluate(() => document.getElementById("status").textContent), /^Your turn/);
      const waiting = party.members.find(m => m !== actor);
      assert.match(await waiting.page.evaluate(() => document.getElementById("status").textContent), /to (play|lead)/);
      assert.ok(await waiting.page.evaluate(() => document.querySelectorAll("#trick .slot").length === ST.game.seats.length), "every seat has a place in the trick");
      if (s.game.turn === "tonoja") {
        // Tonoja's cards are the captain's to play, and they are what the captain's hand shows now.
        assert.equal(await actor.page.evaluate(() => document.getElementById("hand-title").textContent), "Tonoja · face up");
        const other = seated().find(m => m !== actor);
        await clickKey(other.page, "hand-tonoja");
        assert.equal(await other.page.evaluate(() => [...document.querySelectorAll("#hand button.card")].every(c => c.disabled)), true, "only the captain plays Tonoja");
        await oneViewport(other.page, "looking at Tonoja's cards"); await clickKey(other.page, "hand-mine");
      }
    }
    if (plays === 1) for (const size of PHONES) { await actor.page.setViewport({...actor.page.viewport(), ...size}); await pause(60); await oneViewport(actor.page, "mid-trick"); await withLongText(actor.page, () => oneViewport(actor.page, "mid-trick, long text")); await actor.page.screenshot({path:path.join(OUT, `play-${size.width}x${size.height}.png`)}); }
    // tapping a card chooses it; nothing is played until the dock's button
    await clickKey(actor.page, "card:" + g.me.legal_cards[0]);
    assert.equal((await state(actor.page)).game.revision, g.revision, "choosing a card plays nothing");
    assert.equal((await has(actor.page, "play")).disabled, false);
    await clickKey(actor.page, "play"); await waitRevision(actor.page, g.revision); plays++;
    if (plays === s.game.seats.length) {
      // The trick that just ended stays on the table, with its winner, until the next card.
      const done = (await settle()).game;
      if (!done.result) for (const m of party.members) assert.match(await m.page.evaluate(() => document.getElementById("stage").innerText), new RegExp(`Trick 1 · .+ won`));
    }
    if (plays === 2 && !reconnected && seated().includes(host)) {
      // The host's phone reloads mid-trick: the same seat, the same hand, still the host.
      const before = (await state(host.page)).game;
      await host.page.reload({waitUntil:"networkidle2"}); await host.page.waitForFunction(() => ST?.game?.me && !ST.game.away.length && window.AvranaParty);
      const after = (await state(host.page)).game;
      assert.deepEqual(after.me.hand, before.me.hand); assert.deepEqual(after.trick, before.trick);
      assert.equal(await host.page.evaluate(() => AvranaParty.isHost()), true);
      reconnected = true;
    }
    await pause(110);
  }
  let ended = await settle();
  assert.ok(ended.game.result, "the mission reached a result");

  // ---- the result takes over every screen; only the host is offered what comes next ----
  const NEXT = ended.game.result.status === "failed" ? ["retry-same","retry-new"] : ["next"];
  for (const m of party.members) {
    const seen = await resultOwnsTheScreen(m.page, `${m.name}: the result`);
    const keys = seen.keys.map(k => k.key);
    if (m === host) { for (const k of NEXT) assert.ok(keys.includes(k), `the host is offered ${k}`); assert.ok(keys.includes("end-expo")); }
    else {
      assert.deepEqual(keys.filter(k => [...NEXT, "retry-same", "retry-new", "next", "end-expo", "end-table"].includes(k)), [], `${m.name} is offered no lifecycle control`);
      assert.match(seen.text, new RegExp(`Waiting for ${host.name} to choose what’s next`));
    }
  }
  for (const size of PHONES) { await host.page.setViewport({...host.page.viewport(), ...size}); await pause(60); await resultOwnsTheScreen(host.page, "the host's result"); await host.page.screenshot({path:path.join(OUT, `result-host-${size.width}x${size.height}.png`)}); }
  await others[0].page.screenshot({path:path.join(OUT, "result-crew.png")});
  // The other outcome, drawn from the same state with only the result changed: the page has one
  // way to show a result, and it is as hard to miss for a success as for a failure.
  {
    const real = await state(others[0].page), flip = real.game.result.status === "failed" ? {status:"success", reason:"All mission objectives completed."} : {status:"failed", reason:"The final trick ended before all objectives were completed."};
    await others[0].page.evaluate((st, result) => render({...st, game:{...st.game, attempt:st.game.attempt + 1000, result}}), real, flip);
    await resultOwnsTheScreen(others[0].page, "the other outcome");
    await others[0].page.evaluate(st => render(st), real);
  }
  // A crew member who is not the host cannot move the table on, whatever the page sends.
  const decision = ended.game.result.status === "failed" ? {kind:"retry", keep:true} : {kind:"next", mission:2};
  assert.match(await refused(others[0].page, SEND_SEAT(decision)), /^Only the Party Host can/);
  assert.equal(await refused(others[0].page, SEND_HOST(decision)), "Only the Party Host can do that.");

  // ---- succession: the Party moves the host role, and the game follows with no message ----
  if (!WATCHING_HOST) {
    const old = host; host = others[0]; await makeHost(host); succession = true;
    assert.equal(await refused(old.page, SEND_HOST(decision)), "Only the Party Host can do that.");
    const lost = (await resultOwnsTheScreen(old.page, "the former host")).keys.map(k => k.key);
    assert.deepEqual(lost.filter(k => [...NEXT, "end-expo"].includes(k)), [], "the former host's controls are gone");
    for (const k of NEXT) assert.ok(await has(host.page, k), "the new host has them");
  }
  {
    const rev = ended.game.revision, attempt = ended.game.attempt;
    await clickKey(host.page, NEXT.at(-1)); for (const m of party.members) await waitRevision(m.page, rev);
    const again = (await settle()).game;
    assert.equal(again.result, null); assert.equal(again.proposal, null, "nobody voted"); assert.equal(again.attempt, attempt + 1);
    for (const m of party.members) { assert.equal(await m.page.evaluate(() => document.getElementById("result").hidden), true); await oneViewport(m.page, "the next attempt"); }
  }

  // ---- Home and End are the Party's ----
  for (const m of party.members) {
    await m.page.click("#menu-toggle");
    const menu = await m.page.evaluate(() => ({text: document.getElementById("sheet-body").innerText, links: [...document.querySelectorAll("#sheet a[href]")].map(a => a.getAttribute("href"))}));
    assert.deepEqual(menu.links, [], "the table menu has no link out of the Party's round");
    if (m === host) assert.ok(await has(m.page, "menu-end"));
    else { assert.equal(await has(m.page, "menu-end"), null, `${m.name} cannot end EXPO`); assert.match(menu.text, new RegExp(`Only ${host.name} can end EXPO`)); }
    if (m !== host) await m.page.click("#sheet-close");
  }
  assert.match(await refused(seated().find(m => m !== host).page, SEND_SEAT({kind:"end"})), /the Party Host ends EXPO/);
  await clickKey(host.page, "menu-end");
  assert.equal(await host.page.evaluate(() => window.__party.ended), 0, "one tap does not end the game");
  await clickKey(host.page, "menu-end");
  await host.page.waitForFunction(() => window.__party.ended === 1);
  // The Party ends the session at the game: every phone is told, and none is sent anywhere.
  await post("end", seal({...base("end", 30), nonce:crypto.randomBytes(12).toString("hex")}));
  for (const m of party.members) await m.page.waitForFunction(() => Boolean(document.getElementById("party-ended")), {timeout:8000});
  assert.deepEqual([...visited], ["/games/expo/"], "no page ever left EXPO for another route, the LAN Games hub least of all");
  assert.deepEqual(errors, []);
  finished = true;
  console.log(`PASS: EXPO Party round, ${HUMANS} seated${WATCHING_HOST ? " + a watching host" : ""}${HUMANS === 2 ? " + Tonoja" : ""}: one-viewport play on ${PHONES.length} phone sizes, ` +
    `result takeover (${ended.game.result.status}), host-only lifecycle, captain is not host${succession ? ", succession" : ""}${reconnected ? ", host reconnect" : ""}, Party-owned end, no hub route`, OUT);
} catch (e) {
  for (const m of party.members) if (m.page) await m.page.screenshot({path:path.join(OUT, `failed-${m.name}.png`)}).catch(() => {});
  throw e;
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill();
  fs.rmSync(keys, {recursive:true, force:true});
  if (!finished) console.error(serverLog.split("\n").slice(-15).join("\n"));
}
