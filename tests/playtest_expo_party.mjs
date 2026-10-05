// EXPO in a Party round, in real browsers on phone viewports (AVR-275, AVR-252, AVR-266).
//
//   node tests/playtest_expo_party.mjs [outdir]
//     EXPO_HUMANS=2..5   seated players (default 3; 2 seats Tonoja)
//     EXPO_HOST=spectator   the Party Host watches instead of playing
//     EXPO_PARTY=old     a Party from before the host claim: the transitional crew fallback
//     EXPO_PYTHON=...    the interpreter that runs server.py (default: python3, python on Windows)
//     EXPO_FX=high|medium|low|off, EXPO_MOTION=reduced   the presentation tier (AVR-267)
//
// The script is the Party. It starts its own game server with a party key, launches a signed
// roster the way Party Core does, answers each page's ticket request with a ticket that says
// whether that participant is the host right now, and answers the game server's own question
// ("is this participant the host NOW?") before every host action (avrana-party ADR 0006,
// amendment 2026-10-04).
// The Party's page module (/party/lib/party-follow.js) is replaced by a stub that publishes
// window.AvranaParty from the same truth. Nothing in the game or its client is stubbed.
//
// What it proves: one-viewport play; a pending strategic decision in view for whoever must
// answer; a result that takes over the screen; Party Host and captain as separate authorities
// in the page and at the server; the crew's moment to ask for distress before Begin; host
// succession (a former host is refused at once, whatever tickets it kept); reloads during a
// pending decision, a partly played trick and a result; focus held by what is on top; full
// touch targets; no route to the LAN Games hub. AVR-267: the five zones, the crew strip with
// Captain and Party Host on different seats, the shared trick, card states, a result met on a
// reload shown statically, and a director that sends nothing at whatever tier the run asks for.
// A simulated Party and a desktop Chrome are not a real phone (avrana-party docs/TESTING.md).
import os from "os";
import fs from "fs";
import net from "net";
import path from "path";
import crypto from "crypto";
import http from "http";
import { spawn } from "child_process";
import { fileURLToPath } from "url";
import assert from "node:assert/strict";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";
import { PHONES, oneViewport, onScreen, has, clickKey, playCard, resultOwnsTheScreen, withLongText, touchTargets, modalHolds, focused,
  FX, EXPECT_FX, presentation, directorSentNothing, crewLegible, trickShows, legalCardsLookAlike, criticalTextWhole, longestStatusesFit } from "./_expo_phone.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = process.argv[2] || path.join(os.tmpdir(), "expo-party-playtest");
const HUMANS = Number(process.env.EXPO_HUMANS || 3);
const WATCHING_HOST = process.env.EXPO_HOST === "spectator";
const OLD_PARTY = process.env.EXPO_PARTY === "old";
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
const party = {host: null, members: [], ended: 0, asked: 0};   // members: {pid, name, role, page}
const ticketFor = (m, host = party.host === m.pid) => seal({...base("ticket", 120), pid:m.pid, role:m.role, jti:crypto.randomBytes(8).toString("hex"), ...(OLD_PARTY ? {} : {host})});
// The Party's internal route: a game asks whether one participant is the host at this moment.
function open(token, typ) {
  const [prefix, body, mac] = String(token).split(".");
  const want = b64(crypto.createHmac("sha256", KEY).update(prefix + "." + body).digest());
  if (prefix !== "aps0" || mac !== want) return null;
  const p = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
  return p.typ === typ && p.aud === "party" && p.iss === "expo" && p.sid === SID && p.exp > Date.now() / 1000 ? p : null;
}
const partyServer = http.createServer((req, res) => {
  let raw = ""; req.on("data", d => { raw += d; }); req.on("end", () => {
    const send = (status, body) => { res.writeHead(status, {"Content-Type":"application/json"}); res.end(JSON.stringify(body)); };
    if (req.method !== "POST" || req.url !== "/internal/party-session/v0/host") return send(req.url === "/internal/party-session/v0/ended" ? 200 : 404, {ok:true});
    let q = null; try { q = open(JSON.parse(raw).message, "host"); } catch { /* refused below */ }
    if (!q) return send(403, {error:"bad_message"});
    party.asked++;
    send(200, {ok:true, answer:seal({...base("host_is", 30), pid:q.pid, nonce:q.nonce, host:party.host === q.pid})});
  });
});
await new Promise(resolve => partyServer.listen(0, "127.0.0.1", resolve));
const PARTY_URL = `http://127.0.0.1:${partyServer.address().port}`;

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
  env:{...process.env, LANGAMES_PORT:String(PORT), AVRANA_PARTY_KEYS:keys, AVRANA_PARTY_URL:PARTY_URL, EXPO_SNAPSHOT_PATH:""}});
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
  for (const m of party.members) await m.page.waitForFunction(r => ST?.game && ST.game.revision >= r && !ST.game.away.length && !ST.game.resolving, {}, rev);
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
// A phone reloads (or drops and comes back): the same person, and the table as the server has it.
async function reload(member) {
  await member.page.reload({waitUntil:"networkidle2"});
  await member.page.waitForFunction(() => ST?.game && window.AvranaParty, {timeout:25000});
  await pause(300);                       // the page reads the Party's view again within a tick
  for (const m of party.members) await m.page.waitForFunction(() => ST?.game && !ST.game.away.length, {timeout:25000});
  await pause(120);
  return (await state(member.page)).game;
}
// The labels a player reads never use one authority's name for another's.
async function labels(member, g) {
  const s = await member.page.evaluate(() => ({host: document.getElementById("dock-host")?.querySelector(".dock-label")?.innerText || "",
    action: document.getElementById("dock-action")?.querySelector(".dock-label")?.innerText || "",
    tiles: [...document.querySelectorAll("#seats .seat")].map(n => ({seat: n.dataset.key.slice(5), said: n.getAttribute("aria-label")})), me: ST.you?.pid || null, seat: ST.game.me?.seat || null}));
  if (g.lifecycle === "host") assert.match(s.host, /^Party Host \(table control\)/, `${member.name}: table control is the Party Host's`);
  else assert.match(s.host, /^Crew \(decides (for now|together)\)/);
  if (s.action) assert.match(s.action, !s.seat ? /^Watching \(no seat\)/ : s.seat === g.captain ? /^(Captain|For Tonoja) \(game role\)/ : /^Crew member \(game role\)/, `${member.name}: the in-game role is named as one`);
  const hostSeat = (await state(party.members.find(m => m.pid === party.host).page)).you?.pid ?? null;
  for (const tile of s.tiles) {
    assert.equal(/Captain/.test(tile.said), tile.seat === g.captain, "only the captain's tile says Captain");
    assert.equal(/Party Host/.test(tile.said), seated().some(m => m.pid === party.host) && tile.seat === hostSeat, "only the Party Host's tile says Party Host");
    assert.doesNotMatch(tile.said.replace("Party Host", ""), /Host/, "no bare Host");
  }
}
async function makeHost(member) {
  party.host = member.pid;
  for (const m of party.members) await m.page.evaluate((host, name) => { window.__party.host = host; window.__party.hostName = name; window.__partyMoved && window.__partyMoved(); }, member.pid, member.name);
  await pause(80);
}
async function openPage(member, viewport) {
  const context = await browser.createBrowserContext(), pg = await context.newPage();
  member.page = pg;
  await pg.setViewport({...viewport, deviceScaleFactor:1, isMobile:true, hasTouch:true});
  pg.on("pageerror", e => errors.push(e.message));
  pg.on("framenavigated", f => { if (f === pg.mainFrame() && f.url().startsWith("http")) visited.add(new URL(f.url()).pathname); });
  await presentation(pg);
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
  for (const [i, m] of party.members.entries()) await openPage(m, PHONES[i % PHONES.length]);
  for (const m of party.members) await m.page.waitForFunction(() => ST?.game && window.AvranaParty, {timeout:25000});
  const first = (await settle()).game;
  if (OLD_PARTY) {
    // A Party from before the host claim: the crew decides, for now, and everyone is told so.
    assert.equal(first.lifecycle, "crew"); assert.equal(first.lifecycle_transitional, true);
    assert.equal(first.lifecycle_reasons.begin, "Finish task allocation and predictions first.", "the crew's Begin has the server's reason");
    for (const m of party.members) {
      await labels(m, first);
      assert.match(await m.page.evaluate(() => document.getElementById("dock-host").innerText), /^Crew \(decides for now\)/);
      await m.page.click("#menu-toggle");
      const menu = await m.page.evaluate(() => document.getElementById("sheet-body").innerText);
      assert.match(menu, /does not tell EXPO who its Host is yet/); assert.match(menu, /That is temporary/);
      assert.match(menu, /Party Host · .+\n+Ends EXPO and moves the Party\./, "the Party Host is not credited with what the crew decides");
      await m.page.click("#sheet-close"); await oneViewport(m.page, "an older Party");
    }
    assert.match(serverLog, /do not say who its host is/, "the server says so once in its log");
    assert.equal(await refused(party.members[0].page, SEND_HOST({kind:"begin"})), "Only the Party Host can do that.");
    assert.equal(party.asked, 0, "a ticket without the claim never reaches the Party's host question");
    assert.deepEqual(errors, []); finished = true;
    console.log(`PASS: EXPO under a Party without the host claim, ${HUMANS} seated: transitional crew fallback, shown and logged`, OUT);
  } else {
  assert.equal(first.lifecycle, "host", "the Party named its host: lifecycle is the host's"); assert.equal(first.lifecycle_transitional, false);
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

  // ---- the crew's moment: Begin is closed to the host for a few seconds, and nobody votes ----
  let graceSeen = false;
  if (ready.seats.includes("tonoja")) assert.equal(ready.begin_at, null, "no distress with Tonoja: nothing to wait for");
  else {
    assert.ok(ready.begin_at, "the server says when Begin opens");
    const left = () => host.page.evaluate(() => ST.game.begin_at ? ST.game.begin_at - conn.now() / 1000 : 0);
    if (await left() > 2) {
      const b = await has(host.page, "begin"), reason = (await state(host.page)).game.lifecycle_reasons.begin;
      assert.equal(b.disabled, true); assert.match(b.text, /^Begin in \d$/);
      // Why it is closed is the server's sentence, from the view, in words on the page (AVR-263).
      assert.equal(reason, "The crew has a moment to ask for distress first. Begin in a few seconds.");
      assert.equal(b.title, reason, "the closed Begin gives the view's reason");
      assert.equal((await has(host.page, "begin-why"))?.text, reason, "and says it in words, in the stage");
      assert.match(await host.page.evaluate(() => document.getElementById("status").textContent), /The crew may ask for distress · you can begin in \d/);
      const crew = seated().find(m => m !== host);
      assert.match(await crew.page.evaluate(() => document.getElementById("status").textContent), new RegExp(`Want distress\\? Ask now · ${host.name} can begin in \\d`));
      for (const k of ["distress-left","distress-right"]) assert.equal((await has(crew.page, k)).disabled, false, "any seated crew member may ask");
      assert.equal(await has(crew.page, "agree"), null, "nobody is asked to confirm or say ready");
      assert.equal(await has(crew.page, "begin-why"), null, "the reason is shown to whoever has the control");
      if (await left() > 1) { assert.equal(await refused(host.page, SEND_HOST({kind:"begin"})), "The crew has a moment to ask for distress first. Begin in a few seconds."); graceSeen = true; }
    }
    await host.page.waitForFunction(() => { const b = [...document.querySelectorAll("[data-key]")].find(x => x.dataset.key === "begin"); return b && !b.disabled && b.textContent === "Begin mission"; }, {timeout:9000});
    assert.equal(await host.page.evaluate(() => graceLeft(ST.game)), 0);
    // The server took its reason back by itself: a state pushed when the moment ended, with no
    // message from any phone (the page opens Begin only when the view gives no reason).
    const opened = (await state(host.page)).game;
    assert.equal(opened.lifecycle_reasons.begin, null); assert.equal(opened.begin_at, null);
    assert.equal(await has(host.page, "begin-why"), null);
  }

  // ---- Begin: the host's, once the crew has had its say ----
  for (const m of party.members) { await oneViewport(m.page, "ready to begin"); await touchTargets(m.page, `${m.name}: ready to begin`); await labels(m, ready); }
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
        await oneViewport(m.page, `${m.name}: the distress decision`); await criticalTextWhole(m.page, `${m.name}: the distress decision`);
      }
      assert.match(await m.page.evaluate(() => document.getElementById("status").textContent), /^Your answer is needed: Activate distress/);
      assert.match(await m.page.evaluate(() => document.getElementById("stage").innerText), /Activate distress and pass one color card left/);
    }
    {
      // A phone that must answer reloads: the question is still there, in view, with both answers.
      const answering = seated().find(m => m !== asker), before = (await state(answering.page)).game;
      const after = await reload(answering);
      assert.deepEqual(after.proposal, before.proposal);
      for (const k of ["agree","decline"]) await onScreen(answering.page, k, `${answering.name}: the decision after a reload`);
      assert.match(await answering.page.evaluate(() => document.getElementById("status").textContent), /^Your answer is needed: Activate distress/);
      await oneViewport(answering.page, "a pending decision after a reload"); await criticalTextWhole(answering.page, "a pending decision after a reload"); await touchTargets(answering.page, "a pending decision");
    }
    {
      // Begin waits for the crew's answer, and the reason on it is the view's: the sentence the
      // server refuses the host's Begin with at this moment, on the button and in words (AVR-263).
      const waiting = (await state(host.page)).game.lifecycle_reasons.begin, b = await has(host.page, "begin");
      assert.equal(waiting, "The crew is deciding something. Wait for their answer.");
      assert.equal(b.disabled, true, "Begin waits for the crew's answer"); assert.equal(b.title, waiting);
      assert.equal((await has(host.page, "begin-why"))?.text, waiting, "the reason is words on the page");
      assert.equal(await refused(host.page, SEND_HOST({kind:"begin"})), waiting);
      for (const m of party.members) assert.deepEqual((await state(m.page)).game.lifecycle_reasons, (await state(host.page)).game.lifecycle_reasons, "the same for every viewer");
    }
    await host.page.screenshot({path:path.join(OUT, "decision-pending.png")});
    const decliner = seated().find(m => m !== asker), r2 = (await state(decliner.page)).game.revision;
    await clickKey(decliner.page, "decline"); for (const m of party.members) await waitRevision(m.page, r2);
    const declined = (await settle()).game;
    assert.equal(declined.proposal, null); assert.equal(declined.begin_at, null, "a declined request starts no new wait");
    // the host's own authority stops at the table's routine steps
    assert.equal(await refused(host.page, SEND_HOST({kind:"distress", direction:"left"})), "The crew decides that together.");
    assert.equal(await refused(host.page, SEND_HOST({kind:"end"})), "The crew decides that together.");
    assert.equal(await refused(host.page, `conn.hostAction({t:"play_card",card:"blue:1",attempt:ST.game.attempt,revision:ST.game.revision,request:"x"})`), "Invalid lifecycle action.");
  }
  {
    const rev = (await state(host.page)).game.revision;
    await clickKey(host.page, "begin"); for (const m of party.members) await waitRevision(m.page, rev);
    const began = (await settle()).game;
    assert.equal(began.stage, "before_trick"); assert.equal(began.proposal, null, "nobody voted");
    assert.equal(began.captain, first.captain); assert.equal(began.turn, first.captain, "the captain still opens the first trick");
    // The fullest tile there is: one seat that is the Captain, the Party Host and the seat whose
    // turn it is, at once. The Party says who its host is, so the page is told the captain is
    // (then told the truth again); every phone, 360 px wide ones among them, keeps the name whole.
    await makeHost(captain);
    for (const m of party.members) { await crewLegible(m.page, `${m.name}: the captain as Party Host, ${HUMANS} seats at ${m.page.viewport().width} px`, first.captain); await oneViewport(m.page, `${m.name}: the captain as Party Host`); }
    await party.members[0].page.screenshot({path: path.join(OUT, `crew-captain-host-${HUMANS}.png`)});
    await makeHost(host);
  }

  // ---- ordinary trick play, on one screen ----
  let plays = 0, succession = false, reconnected = false; const statuses = [];
  for (let i = 0; i < 90; i++) {
    const s = await settle(); if (s.game.result) break;
    const actor = await byPid(s.game.turn === "tonoja" ? s.game.captain : s.game.turn), g = (await state(actor.page)).game;
    if (plays < 2 * s.game.seats.length) {
      // The seat the Party Host sits in, if the host is seated: the crew strip tags it for everyone.
      const hostSeat = seated().includes(host) ? (await state(host.page)).you.pid : null;
      for (const m of party.members) {
        await oneViewport(m.page, `${m.name} during trick play`); await crewLegible(m.page, `${m.name} during trick play`, hostSeat); await trickShows(m.page, `${m.name} during trick play`);
        if (plays < 2) { await touchTargets(m.page, `${m.name} during trick play`); await labels(m, s.game); }
      }
      if (s.game.turn !== "tonoja") await legalCardsLookAlike(actor.page, `${actor.name} to play`);
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
    // The longest status sentences, long names, five sizes: for a player, and for whoever watches.
    if (plays === 1) for (const m of [actor, party.members.at(-1)]) statuses.push(...await longestStatusesFit(m.page, `${m.name}: the longest statuses`));
    if (plays === 1) for (const size of PHONES) { await actor.page.setViewport({...actor.page.viewport(), ...size}); await pause(60); await oneViewport(actor.page, "mid-trick"); await withLongText(actor.page, async () => { await oneViewport(actor.page, "mid-trick at its fullest"); await touchTargets(actor.page, "mid-trick at its fullest"); }); await actor.page.screenshot({path:path.join(OUT, `play-${size.width}x${size.height}.png`)}); }
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
      const after = await reload(host);
      assert.deepEqual(after.me.hand, before.me.hand); assert.deepEqual(after.trick, before.trick);
      assert.ok(after.trick.length > 0 && after.trick.length < after.seats.length, "the trick is partly played");
      assert.equal(await host.page.evaluate(() => AvranaParty.isHost()), true);
      await oneViewport(host.page, "a partly played trick after the host reloads");
      // ... and a crew member who is not the host: the same seat, the same cards, the same trick.
      const crew = seated().find(m => m !== host), was = (await state(crew.page)).game;
      const now = await reload(crew);
      assert.deepEqual(now.me.hand, was.me.hand); assert.deepEqual(now.trick, was.trick); assert.equal(now.turn, was.turn);
      assert.equal(await crew.page.evaluate(() => document.querySelectorAll("#trick .slot .card").length), now.trick.length, "the cards already played are on the table");
      await oneViewport(crew.page, "a partly played trick after a reload");
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
    if (m === host) {
      for (const k of NEXT) assert.ok(keys.includes(k), `the host is offered ${k}`); assert.ok(keys.includes("end-expo"));
      // open, because the view gives no reason for the step (AVR-263)
      assert.equal(ended.game.lifecycle_reasons[ended.game.result.status === "failed" ? "retry" : "next"], null);
      for (const k of NEXT) assert.equal(seen.keys.find(x => x.key === k).disabled, false, `${k} is open`);
    }
    else {
      assert.deepEqual(keys.filter(k => [...NEXT, "retry-same", "retry-new", "next", "end-expo", "end-table"].includes(k)), [], `${m.name} is offered no lifecycle control`);
      assert.match(seen.text, new RegExp(`Waiting for ${host.name} \\(Party Host\\) to choose what’s next`));
    }
    await touchTargets(m.page, `${m.name}: the result`); await modalHolds(m.page, "result", `${m.name}: the result`);
  }
  {
    // Reloading on a result: it takes the screen over again, for the host with the controls and
    // for the crew without them.
    const crew = party.members.find(m => m !== host);
    for (const m of [host, crew]) {
      await reload(m);
      const keys = (await resultOwnsTheScreen(m.page, `${m.name}: the result after a reload`)).keys.map(k => k.key);
      // AVR-267: a result met on a reload is the state, not news: no cinematic beat is replayed.
      assert.equal(await m.page.evaluate(() => document.getAnimations().filter(a => String(a.id).startsWith("expo-fx:cine") && a.playState === "running").length), 0, `${m.name}: nothing is replayed after a reload`);
      if (FX !== "off") assert.deepEqual(await m.page.evaluate(() => director.stats.performed.map(p => p.effect).filter(e => e !== "reconnect")), [], `${m.name}: the director showed nothing stale`);
      assert.deepEqual(NEXT.filter(k => keys.includes(k)), m === host ? NEXT : [], `${m.name} after a reload`);
    }
    // "Look at the table": the way back is the whole dock, it says what it leads to, and for the
    // host that includes the lifecycle controls.
    for (const m of [host, crew]) {
      await clickKey(m.page, "review"); await onScreen(m.page, "show-result", `${m.name}: the result put away`);
      assert.equal(await focused(m.page), "show-result");
      const way = (await has(m.page, "show-result")).text;
      assert.match(way, m === host ? /^Mission (complete · show result and next mission|failed · show result and retry)$/ : /^Mission (complete|failed) · show result$/);
      await oneViewport(m.page, `${m.name}: the table after the result`); await touchTargets(m.page, `${m.name}: the table after the result`);
      await clickKey(m.page, "show-result"); await resultOwnsTheScreen(m.page, `${m.name}: the result shown again`);
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
    const old = host, asked = party.asked;
    // The old host keeps tickets fetched while host: each still says `host: true` for 120 s.
    const hoard = [ticketFor(old, true), ticketFor(old, true), ticketFor(old, true)];
    host = others[0]; await makeHost(host); succession = true;
    assert.equal(await refused(old.page, SEND_HOST(decision)), "Only the Party Host can do that.");
    for (const kept of hoard)       // the claim opens the question; the Party's answer, now, is no
      assert.equal(await refused(old.page, `conn.send({t:"host",ticket:${JSON.stringify(kept)},action:{t:"lifecycle",decision:${JSON.stringify(decision)},attempt:ST.game.attempt,revision:ST.game.revision}})`), "Only the Party Host can do that.");
    assert.equal(party.asked, asked + hoard.length, "the game asked the Party for each kept ticket, and for nothing else");
    // Both phones reload after the role moved: the page and the server agree on who the host is.
    await reload(old); await reload(host);
    assert.equal(await old.page.evaluate(() => AvranaParty.isHost()), false); assert.equal(await host.page.evaluate(() => AvranaParty.isHost()), true);
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
    assert.match(menu.text, /Party Host · .+\n+Begins each mission, retries, chooses the next one, ends EXPO and moves the Party\./);
    assert.match(menu.text, /Crew · everyone seated\n+Decides together what the rules give the crew/);
    assert.match(menu.text, /Captain · .+\n+.*A role in the game, not the Party Host\./);
    await touchTargets(m.page, `${m.name}: the table menu`); await modalHolds(m.page, "sheet", `${m.name}: the table menu`);
    if (m !== host) { await m.page.click("#sheet-close"); assert.equal(await m.page.evaluate(() => document.activeElement.id), "menu-toggle", "focus returns to the menu button"); }
  }
  assert.match(await refused(seated().find(m => m !== host).page, SEND_SEAT({kind:"end"})), /the Party Host ends EXPO/);
  // AVR-267: the presentation never sent a frame, and ran at the tier this run asked for.
  for (const m of party.members) await directorSentNothing(m.page, m.name);
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
    `result takeover (${ended.game.result.status}), presentation ${EXPECT_FX || "off"}${process.env.EXPO_MOTION === "reduced" ? " (reduced motion)" : ""} with a silent director, host-only lifecycle${graceSeen ? ", distress moment before Begin" : ""}, captain is not host${succession ? ", succession with kept tickets refused" : ""}${reconnected ? ", reloads mid-trick" : ""}, reloads on a decision and a result, focus and touch targets, Party-owned end, no hub route`, OUT);
  }
} catch (e) {
  for (const m of party.members) if (m.page) await m.page.screenshot({path:path.join(OUT, `failed-${m.name}.png`)}).catch(() => {});
  throw e;
} finally {
  if (browser) await browser.close().catch(() => {});
  server.kill(); partyServer.close();
  fs.rmSync(keys, {recursive:true, force:true});
  if (!finished) console.error(serverLog.split("\n").slice(-15).join("\n"));
}
