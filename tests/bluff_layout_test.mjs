// bluff_layout_test.mjs — BLUFF's table in a real browser, fed REAL server states (AVR-313).
//
//   LANGAMES_PORT=8198 .venv/bin/python server.py &
//   node tests/bluff_layout_test.mjs http://127.0.0.1:8198 [screenshotDir]
//
// Needs puppeteer-core (tests/_resolve.mjs) and Python (the repository venv; GAMEHUB_PYTHON names
// another). The server only has to serve the page: the page's socket is replaced by a stub, so no
// game runs and nothing a leftover room does can change what is on screen. The states come from
// tests/bluff_states.py, which plays the real BluffSession and prints what the server would send
// each viewer; they are delivered through the page's own message path (hubnet -> onState -> render).
//
// Covers the behaviour floors of AVR-313 in BLUFF's own table (games/bluff/web):
//   reveal       the challenge outcome is on the table, verbatim, at 14 px or more, for the player,
//                a bystander, a watcher and a Party spectator, in lose / block_challenge / next turn
//   operability  every target seat, give-up card and exchange card is a button with a name; Enter
//                and Space work; Escape cancels aiming; focus survives a push; a new prompt takes it
//   live region  one polite region (assertive only for a prompt with a deadline); nothing private
//   legibility   text follows the root size with a 12 px floor; 4.5:1 for role names, the primary
//                label and seat names; prefers-contrast: more; one sentence for an unavailable move
//   overlays     one toast in the top band; one sentence-case reconnect line clear of hand and bar;
//                the bar dimmed and aria-disabled offline; the history drawer a real modal
//   reflow       360x640, 390x664, 390x844, 320x568, 844x390, 640x360 and 200 % page zoom
//                (180x320, 195x332 with a 32 px root): no overlap, nothing off-screen, no sideways
//                overflow, the table scrolls when it cannot fit; side safe-area insets
//   motion       reduced motion: zero running animations and no confetti; a long winner name keeps
//                its crown; a spectator's mini cards have names in the accessibility tree
//
// Environment: CHROME_PATH and GAMEHUB_NODE_MODULES (tests/_resolve.mjs); GAMEHUB_PYTHON (the
// helper's Python); BLUFF_STATES_JSON (a saved helper output, to skip playing the sessions);
// BLUFF_LAYOUT_ONLY (a regexp over the section names: matrix reveal operability focus tabwalk live contrast
// legibility overlays drawer party insets motion); BLUFF_LAYOUT_VP (a regexp over viewport names);
// BLUFF_LAYOUT_SHOTS=0 (no screenshots). Writes layout-results.json (every state at every viewport)
// and layout-metrics.json (the numbers a review quotes, the contrast table among them) to the
// screenshot directory. One browser at a time, closed at the end.
import fs from "fs";
import os from "os";
import path from "path";
import { execFileSync } from "child_process";
import { fileURLToPath } from "url";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const BASE = process.argv[2] || "http://127.0.0.1:8198";
const OUT = process.argv[3] || path.join(os.homedir(), "tmp", "ghshot-bluff-layout");
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.join(os.homedir(), "tmp"), { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const ONLY = process.env.BLUFF_LAYOUT_ONLY ? new RegExp(process.env.BLUFF_LAYOUT_ONLY) : null;
const SHOTS = process.env.BLUFF_LAYOUT_SHOTS !== "0";

let bad = 0, total = 0;
const failures = [];
const check = (ok, message) => {
  total += 1;
  console.log(`${ok ? "PASS" : "FAIL"} ${message}`);
  if (!ok) { bad += 1; failures.push(message); }
};
const section = (name) => console.log(`\n== ${name}`);
const wanted = (name) => !ONLY || ONLY.test(name);
const ONLY_VP = process.env.BLUFF_LAYOUT_VP ? new RegExp(process.env.BLUFF_LAYOUT_VP) : null;

// ---------------------------------------------------------------- real states
function realStates() {
  if (process.env.BLUFF_STATES_JSON) return JSON.parse(fs.readFileSync(process.env.BLUFF_STATES_JSON, "utf8"));
  const tried = [];
  const candidates = [process.env.GAMEHUB_PYTHON, process.env.AVRANA_PYTHON,
    path.join(ROOT, ".venv", "bin", "python"), path.join(ROOT, ".venv", "Scripts", "python.exe"),
    "python3", "python"].filter(Boolean);
  for (const py of candidates) {
    try {
      const out = execFileSync(py, [path.join(HERE, "bluff_states.py")], {
        cwd: ROOT, encoding: "utf8", maxBuffer: 256 << 20, timeout: 120000,
        env: { ...process.env, PYTHONIOENCODING: "utf-8" },
      });
      return JSON.parse(out);
    } catch (e) { tried.push(`${py}: ${String(e.message).split("\n")[0]}`); }
  }
  throw new Error("Could not run tests/bluff_states.py (set GAMEHUB_PYTHON to the repository venv's python):\n  " + tried.join("\n  "));
}
const STATES = realStates();
const states = (key) => {
  if (!STATES[key]) throw new Error("no scripted state " + key);
  return STATES[key];
};

// ---------------------------------------------------------------- the phone
const VIEWPORTS = [
  { name: "360x640", w: 360, h: 640 },
  { name: "390x664", w: 390, h: 664 },
  { name: "390x844", w: 390, h: 844 },
  { name: "320x568", w: 320, h: 568 },
  { name: "844x390", w: 844, h: 390 },
  { name: "640x360", w: 640, h: 360 },
  // 200 % page zoom of a 360x640 / 390x664 phone is half the CSS pixels; the root text is doubled too
  { name: "zoom200-180x320", w: 180, h: 320, root: 32 },
  { name: "zoom200-195x332", w: 195, h: 332, root: 32 },
];

const browser = await puppeteer.launch({
  executablePath: CHROME_PATH,
  headless: "new",
  userDataDir: fs.mkdtempSync(path.join(os.homedir(), "tmp", "gh-bluff-layout-")),
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

// Replaces the page's WebSocket: the page "connects" at once, everything it sends is recorded in
// window.__sent, and the test pushes server messages in through deliver().
function stubSocket() {
  window.__sent = [];
  window.__sockets = [];
  window.WebSocket = class StubSocket {
    constructor(url) {
      this.url = url; this.readyState = 0; this.id = window.__sockets.length;
      window.__sockets.push(this);
      setTimeout(() => { if (this.readyState === 0) { this.readyState = 1; if (this.onopen) this.onopen({}); } }, 0);
    }
    send(data) { try { window.__sent.push(JSON.parse(data)); } catch (e) { window.__sent.push(data); } }
    close() { if (this.readyState !== 3) { this.readyState = 3; if (this.onclose) this.onclose({}); } }
  };
  window.__toasts = [];
  new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
    if (n.classList && n.classList.contains("toast")) window.__toasts.push(n.textContent);
  }))).observe(document, { childList: true, subtree: true });
}

async function phone(vp, opts = {}) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  await page.setViewport({ width: vp.w, height: vp.h, deviceScaleFactor: opts.dsf || 1, isMobile: true, hasTouch: true });
  const media = [];
  if (opts.reduced) media.push({ name: "prefers-reduced-motion", value: "reduce" });
  if (opts.contrast) media.push({ name: "prefers-contrast", value: "more" });   // not one of puppeteer's own features
  if (media.length) { const cdp = await page.createCDPSession(); await cdp.send("Emulation.setEmulatedMedia", { features: media }); }
  await page.evaluateOnNewDocument(stubSocket);
  await page.evaluateOnNewDocument(() => {
    try { localStorage.setItem("bluff-briefed", "1"); sessionStorage.setItem("lg-booted", "1"); } catch (e) { /* private */ }
  });
  const url = BASE + "/games/bluff/" + (opts.standalone ? "" : "?avrana=1");
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => typeof render === "function" && typeof Hub !== "undefined" && window.__sockets.length > 0
    && window.__sockets[window.__sockets.length - 1].readyState === 1, { timeout: 15000, polling: 50 });
  if (vp.root) await page.evaluate((px) => { document.documentElement.style.fontSize = px + "px"; }, vp.root);
  if (!opts.standalone) {
    // pose as a Party round: Party chrome rules (the Back to Party bar hidden), host controls mocked
    await page.evaluate((host) => {
      document.documentElement.dataset.avranaParty = "on";
      window.__party = { ended: 0, home: 0, again: 0 };
      window.AvranaParty = { active: true, isHost: () => host, hostName: () => "Alexandria",
        end() { window.__party.ended++; }, goHome() { window.__party.home++; }, playAgain() { window.__party.again++; },
        onChange() {} };
    }, opts.host !== false);
  }
  await deliver(page, { type: "welcome", pid: "p1", token: "t" });
  return { ctx, page, errors };
}

// A server message through the page's own path: hubnet -> handlers.onState -> render()
async function deliver(page, msg) {
  await page.evaluate((m) => {
    const sock = window.__sockets[window.__sockets.length - 1];
    sock.onmessage({ data: JSON.stringify(m) });
  }, msg);
}
// A state of the helper's, stamped with this page's clock; `deadline` starts a prompt timer.
// The server's step only ever counts up, but the scripted scenarios each start from a small number:
// a different state than the last one is numbered afresh, the same state again keeps its number.
const LAST_SHOWN = new WeakMap();
async function show(page, scenarioKey, label, opts = {}) {
  const st = JSON.parse(JSON.stringify(states(scenarioKey).views[label]));
  const tag = scenarioKey + "/" + label;
  const last = LAST_SHOWN.get(page) || { tag: null, n: 0 };
  if (last.tag !== tag) { last.tag = tag; last.n += 1; }
  LAST_SHOWN.set(page, last);
  st.game.pending.step += last.n * 1000;
  st.now = Date.now();
  st.deadline = st.phase === "playing" && opts.deadline !== false ? st.now + 14000 : null;
  if (opts.edit) opts.edit(st);
  await page.evaluate(() => { const cv = document.getElementById("confetti"); if (cv && cv._parts) cv._parts.length = 0; });
  await deliver(page, st);
  return st;
}

// ---------------------------------------------------------------- measuring
// Everything that can be measured in one pass. The table scrolls (AVR-313): its pieces are compared
// in the table's own coordinates (the scroller's content), the header and the dock in the screen's,
// and the table's visible window is checked against the header and the dock. When the whole page
// scrolls instead (data-dock="flow"), all of it is in the page's coordinates.
const MEASURE = () => {
  const W = innerWidth, H = innerHeight;
  const app = document.getElementById("app"), stage = document.getElementById("stage");
  const flow = app.dataset.dock === "flow";
  const scroller = stage ? (flow ? app : stage) : null;               // the page before AVR-313 had none
  if (scroller) scroller.scrollTop = scroller.scrollHeight;          // the end: the moves in their place
  const sR = scroller ? scroller.getBoundingClientRect() : { left: 0, right: W, top: 0, bottom: H };
  const vis = (e) => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && !e.closest("[hidden]")
      && !e.closest("dialog:not([open])");
  };
  const frameOf = (e) => (!scroller ? "screen" : flow ? "page" : (stage.contains(e) ? "table" : "screen"));
  const R = (e) => {
    const r = e.getBoundingClientRect(), f = frameOf(e);
    const dy = f === "screen" ? 0 : scroller.scrollTop - sR.top;
    return { f, l: +r.left.toFixed(1), t: +(r.top + dy).toFixed(1), r: +r.right.toFixed(1), b: +(r.bottom + dy).toFixed(1),
      w: +r.width.toFixed(1), h: +r.height.toFixed(1), vt: r.top, vb: r.bottom };
  };
  const q = (s) => [...document.querySelectorAll(s)].filter(vis);
  const groups = {
    chrome: q("#rules, #party-end, #history, #timer, #home"),
    seats: q("#opponents .seat"),
    center: q("#play .card, #play .winner"),
    caption: q("#caption"),
    reveal: q("#reveal"),
    meSeat: q("#me-seat"), coins: q("#coins"), lost: q("#lost"), piles: q("#piles .pile"),
    hand: q("#hand .card"),
    note: q("#bar-note"), banner: q("#conn-banner"),
    bar: q("#bar"),
  };
  const boxes = {};
  for (const [k, els] of Object.entries(groups)) boxes[k] = els.map((e) => ({ id: e.id || e.className.toString().slice(0, 30), ...R(e) }));
  const ov = (a, b) => Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));
  const KEYS = Object.keys(groups);
  const pairs = [];
  let maxOverlap = 0;
  for (let i = 0; i < KEYS.length; i++) for (let j = i; j < KEYS.length; j++) {
    for (const a of boxes[KEYS[i]]) for (const b of boxes[KEYS[j]]) {
      if (a === b || a.f !== b.f || (KEYS[i] === "hand" && KEYS[j] === "hand")) continue;   // a hand is fanned on purpose
      const area = ov(a, b);
      if (area > 20) pairs.push(`${KEYS[i]}:${a.id} x ${KEYS[j]}:${b.id} = ${Math.round(area)}px2`);
      maxOverlap = Math.max(maxOverlap, area);
    }
  }
  // the table's window against the header and the dock (pinned arrangement): they never share pixels
  if (scroller && !flow) {
    const win = { l: sR.left, r: sR.right, t: sR.top, b: sR.bottom };
    for (const k of KEYS) for (const b of boxes[k]) if (b.f === "screen") {
      const area = ov(win, { l: b.l, r: b.r, t: b.vt, b: b.vb });
      if (area > 20) pairs.push(`table window x ${k}:${b.id} = ${Math.round(area)}px2`);
      maxOverlap = Math.max(maxOverlap, area);
    }
  }
  // nothing off-screen: sideways always; up and down only for what does not scroll
  const off = [];
  for (const [k, list] of Object.entries(boxes)) for (const b of list) {
    const side = b.l < -1 || b.r > W + 1;
    const vertical = b.f === "screen" && (b.vt < -1 || b.vb > H + 1);
    if (side || vertical) off.push(`${k}:${b.id} (${b.l},${b.vt})-(${b.r},${b.vb})`);
  }
  const wide = [];
  for (const e of document.querySelectorAll("#app *")) {
    if (!vis(e)) continue;
    const r = e.getBoundingClientRect();
    if ((r.right > W + 1 || r.left < -1) && !e.closest("#sheet")) wide.push((e.id || e.className.toString().slice(0, 24) || e.tagName) + ` ${Math.round(r.left)}..${Math.round(r.right)}`);
  }
  // text: the smallest size on screen, and every size below the 12 px floor
  const sizes = {}, small = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walker.nextNode())) {
    const t = n.textContent.trim();
    if (!t) continue;
    const p = n.parentElement;
    if (!p || !vis(p) || p.closest("script,style,canvas,.sr-only")) continue;
    const fs = parseFloat(getComputedStyle(p).fontSize);
    sizes[fs] = (sizes[fs] || 0) + 1;
    if (fs < 11.99) small.push(`${fs}px "${t.slice(0, 18)}"`);
  }
  const tt = [];
  for (const e of document.querySelectorAll("#app button, #app [role=button]")) {
    if (!vis(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 43.5 || r.height < 43.5) tt.push(`${e.dataset.k || e.id || e.className.toString().slice(0, 24)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  // a control whose label is cut: its text is wider or taller than its box (and a role name on a card)
  const cut = [];
  for (const e of document.querySelectorAll("#bar .act, #sheet .act, .round-btn, #timer, #hand button, #opponents button, #app .card .nm")) {
    if (!vis(e)) continue;
    if (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1) cut.push(`${e.id || e.dataset.k || (e.textContent || "").trim().slice(0, 16)} ${e.scrollWidth}x${e.scrollHeight}>${e.clientWidth}x${e.clientHeight}`);
  }
  // a word of a move's label or of a role's name is never broken in two (a player's own name may be)
  const broken = [];
  for (const e of document.querySelectorAll("#bar .act, #sheet .act, #sheet h3, #drawer-actions .act, #hand .chip, #app .card .nm")) {
    if (!vis(e)) continue;
    const tw = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
    for (let tn; (tn = tw.nextNode());) {
      for (const m of tn.textContent.matchAll(/\S+/g)) {
        const rg = document.createRange();
        rg.setStart(tn, m.index); rg.setEnd(tn, m.index + m[0].length);
        if ([...rg.getClientRects()].filter((r) => r.width > 0).length > 1) broken.push(`"${m[0]}" in ${e.dataset.k || e.id || e.className.toString().slice(0, 14)}`);
      }
    }
  }
  const text = (id) => ((document.getElementById(id) || {}).textContent || "").trim();
  return {
    W, H, mode: flow ? "flow" : "pinned", rootPx: parseFloat(getComputedStyle(document.documentElement).fontSize),
    docOverflowX: document.documentElement.scrollWidth - W,
    bodyOverflowX: document.body.scrollWidth - W,
    appOverflowX: app.scrollWidth - app.clientWidth,
    stageOverflowX: stage ? stage.scrollWidth - stage.clientWidth : 0,
    scrolls: scroller ? scroller.scrollHeight > scroller.clientHeight + 1 : false,
    scrollH: scroller ? scroller.scrollHeight : H, clientH: scroller ? scroller.clientHeight : H,
    maxOverlap: Math.round(maxOverlap), overlaps: [...new Set(pairs)], offscreen: off, wide: wide.slice(0, 8),
    minFont: Math.min(...Object.keys(sizes).map(Number)), small: small.slice(0, 8),
    smallTargets: tt, cut, broken: broken.slice(0, 6),
    caption: text("caption"), reveal: text("reveal"), bar: text("bar"),
  };
};

async function measure(page) {
  await sleep(40);
  return page.evaluate(MEASURE);
}

// ---------------------------------------------------------------- small helpers
const METRICS = { matrix: {}, reveal: {}, contrast: [], misc: {} };
const activeK = (page) => page.evaluate(() => {
  const a = document.activeElement;
  return !a ? null : (a.dataset && a.dataset.k) || (a.id ? "#" + a.id : a.tagName);
});
const sentMsgs = (page) => page.evaluate(() => window.__sent.filter((m) => m && m.t !== "ping" && m.t !== "hello"));
const clearSent = (page) => page.evaluate(() => { window.__sent.length = 0; });
const focusK = (page, k) => page.evaluate((k) => { const e = document.querySelector('[data-k="' + k + '"]'); if (e) e.focus(); return !!e; }, k);
const press = async (page, k, n = 1) => { for (let i = 0; i < n; i++) { await page.keyboard.press(k); await sleep(40); } };
const texts = (page, sel) => page.evaluate((sel) => [...document.querySelectorAll(sel)].map((e) => e.textContent.trim()), sel);
const attr = (page, sel, a) => page.evaluate((sel, a) => [...document.querySelectorAll(sel)].map((e) => e.getAttribute(a)), sel, a);
const vp = (name) => VIEWPORTS.find((v) => v.name === name);
const CAPPED = (list, n = 3) => list.slice(0, n).join(" | ") + (list.length > n ? ` (+${list.length - n} more)` : "");

// The accessibility tree's view of matching elements (role, name, pressed, disabled)
async function ax(page, selector) {
  const client = await page.createCDPSession();
  try {
    await client.send("DOM.enable");
    await client.send("Accessibility.enable");
    const { root } = await client.send("DOM.getDocument", { depth: 0 });
    const { nodeIds } = await client.send("DOM.querySelectorAll", { nodeId: root.nodeId, selector });
    const out = [];
    for (const nodeId of nodeIds) {
      const { nodes } = await client.send("Accessibility.getPartialAXTree", { nodeId, fetchRelatives: false });
      const n = nodes[0] || {};
      const prop = (name) => { const p = (n.properties || []).find((q) => q.name === name); return p && p.value ? p.value.value : undefined; };
      const tri = (v) => (v === "true" ? true : v === "false" ? false : v);
      out.push({ ignored: !!n.ignored, role: n.role && n.role.value, name: n.name && n.name.value, pressed: tri(prop("pressed")), disabled: tri(prop("disabled")) });
    }
    return out;
  } finally { await client.detach(); }
}

// run one section; an exception is a failed check, not the end of the run
async function run(name, fn) {
  if (!wanted(name)) return;
  section(name);
  try { await fn(); } catch (e) { check(false, `${name}: threw ${String(e && e.stack || e).split("\n").slice(0, 3).join(" / ")}`); }
}

// ---------------------------------------------------------------- 1. the matrix
const SCENARIOS = [
  ["turn_mine_poor", "player"], ["turn_mine_rich", "player"], ["turn_must_coup", "player"],
  ["waiting_other_turn", "player"], ["challenge_prompt", "player"], ["block_prompt_aid", "player"],
  ["block_prompt_steal", "player"], ["block_prompt_after_true", "player"],
  ["block_challenge", "bystander"], ["block_challenge_long", "bystander"],
  ["lose_true", "player"], ["lose_bluff", "player"], ["lose_coup", "player"], ["lose_strike", "player"],
  ["turn_after_bluff", "player"], ["turn_after_true", "bystander"],
  ["exchange_prompt", "player"], ["out_watching", "player"],
  ["results", "player"], ["results", "bystander"], ["results_long_name", "player"],
  ["spectator_full_table", "spectator"], ["challenge_prompt", "spectator"], ["lose_true", "spectator"],
  ["turn_mine_two_players", "player"], ["paused_four", "player"],
];
const results = [];

async function matrix() {
  for (const v of VIEWPORTS) {
    if (ONLY_VP && !ONLY_VP.test(v.name)) continue;
    const { ctx, page, errors } = await phone(v);
    const flagged = [], small = [], cut = [], broke = [];
    let worst = 0, off = 0, side = 0, flows = 0, scrolls = 0, minFont = 99;
    for (const [key, label] of SCENARIOS) {
      await show(page, key, label);
      const m = await measure(page);
      results.push({ vp: v.name, scenario: `${key}/${label}`, ...m });
      if (SHOTS) await page.screenshot({ path: path.join(OUT, `${key}-${label}-${v.name}.png`) });
      worst = Math.max(worst, m.maxOverlap);
      off += m.offscreen.length;
      side = Math.max(side, m.docOverflowX, m.bodyOverflowX, m.appOverflowX, m.stageOverflowX);
      if (m.mode === "flow") flows++;
      if (m.scrolls) scrolls++;
      minFont = Math.min(minFont, m.minFont);
      const problems = [];
      if (m.maxOverlap > 20) problems.push(`overlap ${m.maxOverlap}px2 (${m.overlaps[0]})`);
      if (m.offscreen.length) problems.push(`off-screen ${m.offscreen[0]}`);
      if (m.docOverflowX > 0 || m.bodyOverflowX > 0 || m.appOverflowX > 0 || m.stageOverflowX > 0) problems.push(`sideways overflow ${m.docOverflowX}/${m.appOverflowX}/${m.stageOverflowX}`);
      if (m.wide.length) problems.push(`wider than the screen: ${m.wide[0]}`);
      if (problems.length) flagged.push(`${key}/${label}: ${problems.join("; ")}`);
      if (m.minFont < 11.99) small.push(`${key}/${label}: ${m.small[0]}`);
      if (m.cut.length) cut.push(`${key}/${label}: ${m.cut[0]}`);
      if (m.broken.length) broke.push(`${key}/${label}: ${m.broken[0]}`);
    }
    METRICS.matrix[v.name] = { states: SCENARIOS.length, flagged: flagged.length, worstOverlapPx2: worst, offscreen: off, maxSidewaysPx: side, minFontPx: minFont, flowStates: flows, scrollingStates: scrolls, cutLabels: cut.length, brokenWords: broke.length };
    check(flagged.length === 0, `${v.name}: no overlap above 20px2, nothing off-screen, no sideways overflow in ${SCENARIOS.length} states (worst overlap ${worst}px2; ${scrolls} scroll, ${flows} as one page)${CAPPED(flagged, 4) ? " | " + CAPPED(flagged, 4) : ""}`);
    check(small.length === 0, `${v.name}: no text under 12px (smallest ${minFont}px)${small.length ? " | " + CAPPED(small) : ""}`);
    check(cut.length === 0, `${v.name}: no control label is cut${cut.length ? " | " + CAPPED(cut) : ""}`);
    check(broke.length === 0, `${v.name}: no word of a move label or role name is broken in two${broke.length ? " | " + CAPPED(broke) : ""}`);
    check(errors.length === 0, `${v.name}: no page errors (${errors.slice(0, 2).join(" | ")})`);
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 2. the reveal
// What the server wrote for the last action, shown line for line (tests/bluff_states.py keeps the
// chain as the session wrote it). Each case: [scenario, stage, the role on the claimed card].
const REVEAL_CASES = [
  ["lose_true", "lose", "Banker"], ["lose_bluff", "lose", "Banker"], ["lose_strike", "lose", "Agent"], ["lose_coup", "lose", null],
  ["block_challenge", "block_challenge", "Smuggler"], ["block_challenge_long", "block_challenge", "Smuggler"],
  ["turn_after_bluff", "turn", "Banker"], ["turn_after_true", "turn", "Banker"],
];
async function reveal() {
  for (const name of ["390x844", "390x664", "320x568", "844x390", "zoom200-195x332"]) {
    const v = vp(name);
    const { ctx, page, errors } = await phone(v);
    const bad = [], seen = { lines: 0, minPx: 99, notInView: [] };
    for (const [key, stage, rl] of REVEAL_CASES) {
      const sc = states(key);
      for (const label of Object.keys(sc.views)) {
        await show(page, key, label);
        await sleep(30);
        const got = await page.evaluate(() => {
          const rect = (e) => { if (!e) return null; const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
          const stageEl = document.getElementById("stage"), app = document.getElementById("app");
          const sc = app.dataset.dock === "flow" ? app : stageEl;
          const card = document.querySelector("#play .card");
          const lis = [...document.querySelectorAll("#reveal li")];
          const rv = rect(document.getElementById("reveal")), cd = rect(card);
          const between = rv && cd ? [...document.querySelectorAll("#opponents .seat")].filter((e) => { const r = e.getBoundingClientRect(); const mid = (r.top + r.bottom) / 2; return mid > cd.b && mid < rv.t; }).length : 0;
          return { between, lines: lis.map((li) => li.textContent), px: lis.map((li) => parseFloat(getComputedStyle(li).fontSize)),
            reveal: rv, card: cd, cardRole: card ? (card.querySelector(".nm") || {}).textContent : null,
            cardClass: card ? card.className : "", caption: rect(document.getElementById("caption")), window: rect(sc), W: innerWidth,
            horizontal: lis.every((li) => { const r = li.getBoundingClientRect(); return r.left >= -0.5 && r.right <= innerWidth + 0.5; }) };
        });
        const tag = `${key}/${label}`;
        if (JSON.stringify(got.lines) !== JSON.stringify(sc.chain)) bad.push(`${tag}: lines ${JSON.stringify(got.lines).slice(0, 80)} != chain`);
        seen.lines += got.lines.length;
        seen.minPx = Math.min(seen.minPx, ...got.px);
        if (got.px.some((p) => p < 14)) bad.push(`${tag}: a line under 14px (${Math.min(...got.px)})`);
        if (!got.horizontal) bad.push(`${tag}: a line is off the side of the screen`);
        if ((got.cardRole || null) !== rl) bad.push(`${tag}: claimed card ${got.cardRole} not ${rl}`);
        if (rl && got.card && got.reveal) {
          const gap = got.reveal.t - got.card.b, side = got.reveal.l - got.card.r;
          // beside it, or straight under it; in the stacked one-column table (a very narrow or very
          // large-text screen) only the caption may sit between them and no seat
          const stacked = gap >= -20 && got.between === 0;
          const near = (gap >= -20 && gap <= 220) || (side >= -20 && side <= 120 && got.reveal.t < got.card.b) || stacked;
          if (!near) bad.push(`${tag}: reveal not next to the card (gap ${Math.round(gap)}, side ${Math.round(side)}, ${got.between} seats between)`);
        }
        if (got.reveal && got.window && (got.reveal.t < got.window.t - 1 || got.reveal.b > got.window.b + 1)) seen.notInView.push(`${tag} (lines ${Math.round(got.reveal.t)}..${Math.round(got.reveal.b)}, window ${Math.round(got.window.t)}..${Math.round(got.window.b)})`);
      }
    }
    METRICS.reveal[name] = { linesChecked: seen.lines, minFontPx: seen.minPx, notFullyInView: seen.notInView.length };
    check(bad.length === 0, `${name}: reveal lines == the session's own log lines, >=14px (smallest ${seen.minPx}px), claimed card is the right role and next to them, in 8 stages x every viewer${bad.length ? " | " + CAPPED(bad, 4) : ""}`);
    if (["390x844", "390x664"].includes(name)) check(seen.notInView.length === 0, `${name}: the whole reveal is in view without scrolling${seen.notInView.length ? " | " + CAPPED(seen.notInView) : ""}`);
    check(errors.length === 0, `${name}: reveal: no page errors (${errors.slice(0, 2).join(" | ")})`);
    // until the next prompt: a new action takes the old lines away
    await show(page, "lose_true", "player");
    await show(page, "challenge_prompt", "player");
    const after = await texts(page, "#reveal li");
    check(!after.some((t) => /reveals|challenges/.test(t)), `${name}: the old lines are gone when the next action starts (${after.length} line)`);
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 3. operability
const rotateOpp = (st) => {
  const seats = st.game.seats, me = st.game.me, i = seats.findIndex((x) => x.pid === me.pid);
  return seats.slice(i + 1).concat(seats.slice(0, i));
};
async function operability() {
  const { ctx, page, errors } = await phone(vp("390x844"));
  // aiming: Coup, then a target by keyboard
  const st = await show(page, "turn_mine_rich", "player");
  const opp = rotateOpp(st);
  check(await activeK(page) === "bar:income", `my turn: focus starts on the first move (${await activeK(page)})`);
  await press(page, "Tab", 2);
  check(await activeK(page) === "bar:coup", `Tab reaches Coup in DOM order (${await activeK(page)})`);
  await press(page, "Enter");
  check((await activeK(page) || "").startsWith("seat:"), `Enter on Coup: focus goes to the first target (${await activeK(page)})`);
  const tgt = await ax(page, "#opponents button.seat");
  const want = opp.map((s) => `Target ${s.name}, ${s.coins} ${s.coins === 1 ? "coin" : "coins"}`);
  check(tgt.length === opp.length && tgt.every((n) => n.role === "button"), `every target seat is a native button in the accessibility tree (${tgt.length} of ${opp.length})`);
  check(JSON.stringify(tgt.map((n) => n.name)) === JSON.stringify(want), `target names and DOM order: ${JSON.stringify(tgt.map((n) => n.name).slice(0, 3))}...`);
  check(await page.evaluate(() => [...document.querySelectorAll("#opponents button.seat")].every((b) => b.tagName === "BUTTON")), "targets are <button> elements");
  await clearSent(page);
  await press(page, "Space");
  let sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].t === "act" && sent[0].action === "coup" && sent[0].target === opp[0].pid && sent[0].step === st.game.pending.step, `Space on a target sends the Coup at the first seat (${JSON.stringify(sent[0])})`);
  await show(page, "turn_mine_rich", "player");
  await focusK(page, "bar:coup"); await press(page, "Enter"); await press(page, "Tab", 2);
  await clearSent(page); await press(page, "Enter");
  sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].target === opp[2].pid, `Tab, Tab, Enter picks the third seat (${JSON.stringify(sent[0] && sent[0].target)})`);
  // Escape cancels aiming and puts focus back where it began
  await show(page, "turn_mine_rich", "player");
  await focusK(page, "bar:coup"); await press(page, "Enter");
  await clearSent(page);
  await press(page, "Escape");
  check((await page.evaluate(() => document.querySelectorAll("#opponents button.seat").length)) === 0, "Escape ends aiming: no seat is a button any more");
  check(await activeK(page) === "bar:coup", `...and focus is back on Coup (${await activeK(page)})`);
  check((await sentMsgs(page)).length === 0, "...and nothing was sent");
  // a tap works as before
  await focusK(page, "bar:coup"); await press(page, "Enter");
  await clearSent(page);
  const box = await page.evaluate(() => { const r = document.querySelector("#opponents button.seat").getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; });
  await page.mouse.click(box.x, box.y);
  sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].action === "coup", "a tap on a target still sends the Coup");

  // giving up a card
  const lose = await show(page, "lose_true", "player");
  check(await activeK(page) === "hand:0", `a lose prompt focuses the first card (${await activeK(page)})`);
  const cards = await ax(page, "#hand button.card");
  const mine = lose.game.me.cards;
  check(cards.length === mine.length && cards.every((c, i) => c.role === "button" && c.name === "Give up " + mine[i]), `give-up cards are buttons: ${JSON.stringify(cards.map((c) => c.name))}`);
  await clearSent(page);
  await press(page, "Enter");
  sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].t === "lose" && sent[0].card === 0 && sent[0].step === lose.game.pending.step, `Enter on a card gives it up (${JSON.stringify(sent[0])})`);
  await press(page, "Tab"); await clearSent(page); await press(page, "Space");
  sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].card === 1, `Tab, Space gives up the second (${JSON.stringify(sent[0])})`);

  // exchange: two of four, toggled
  const ex = await show(page, "exchange_prompt", "player");
  check(await activeK(page) === "xc:0", `an exchange prompt focuses the first card (${await activeK(page)})`);
  let xs = await ax(page, "#sheet button.card");
  const pool = ex.game.me.prompt.pool, keep = ex.game.me.prompt.keep;
  check(xs.length === pool.length && xs.every((c, i) => c.role === "button" && c.name === "Keep " + pool[i] && c.pressed === false), `exchange cards are toggle buttons: ${JSON.stringify(xs.map((c) => c.name + "/" + c.pressed))}`);
  await press(page, "Space");
  check(await activeK(page) === "xc:0", "focus stays on the card after it toggles");
  xs = await ax(page, "#sheet button.card");
  check(xs[0].pressed === true && xs.slice(1).every((c) => c.pressed === false), "Space presses it (aria-pressed)");
  const keepLabel = () => page.evaluate(() => { const b = document.querySelector('[data-k="bar:keep"]'); return { t: b.textContent.trim(), off: b.getAttribute("aria-disabled") }; });
  check((await keepLabel()).off === "true", `Keep is off while ${keep - 1} of ${keep} are chosen (${(await keepLabel()).t})`);
  await press(page, "Tab"); await press(page, "Enter");
  const k2 = await keepLabel();
  check(k2.off === null && /2\/2/.test(k2.t), `Keep is on at ${keep} of ${keep} (${k2.t})`);
  await press(page, "Tab"); await press(page, "Space");
  xs = await ax(page, "#sheet button.card");
  check(xs.filter((c) => c.pressed === true).length === keep, "a third card cannot be chosen");
  await focusK(page, "bar:keep"); await clearSent(page); await press(page, "Enter");
  sent = await sentMsgs(page);
  check(sent.length === 1 && sent[0].t === "keep" && JSON.stringify(sent[0].cards) === "[0,1]", `Enter on Keep sends the two (${JSON.stringify(sent[0])})`);
  check(errors.length === 0, `operability: no page errors (${errors.slice(0, 2).join(" | ")})`);
  await ctx.close();
}

// ---------------------------------------------------------------- 4. focus
async function focus() {
  const { ctx, page, errors } = await phone(vp("390x664"));
  await show(page, "turn_mine_poor", "player");
  await focusK(page, "bar:aid");
  const same = [];
  for (let i = 0; i < 3; i++) { await show(page, "turn_mine_poor", "player"); same.push(await activeK(page)); }
  for (let i = 0; i < 3; i++) { await page.evaluate(() => render()); same.push(await activeK(page)); }
  check(same.every((k) => k === "bar:aid"), `render() with the same state keeps focus on the same control (${same.join(", ")})`);
  await page.evaluate(() => { window.dispatchEvent(new Event("resize")); });
  check(await activeK(page) === "bar:aid", "...also after a resize");
  // the same on the other choices: a target while aiming, a card to give up, a card to keep, the drawer's button
  const stays = async (what, key, setup) => {
    await setup();
    check(await focusK(page, key), `${what}: ${key} is there to take focus`);
    const seen = [];
    for (let i = 0; i < 3; i++) { await page.evaluate(() => render()); seen.push(await activeK(page)); }
    check(seen.every((k) => k === key), `${what}: render() keeps focus on ${key} (${seen.join(", ")})`);
  };
  await stays("aiming", "seat:p3", async () => { await show(page, "turn_mine_rich", "player"); await focusK(page, "bar:coup"); await press(page, "Enter"); });
  await stays("giving up a card", "hand:1", async () => { await show(page, "lose_true", "player"); });
  await stays("an exchange", "xc:2", async () => { await show(page, "exchange_prompt", "player"); });
  await stays("the history drawer", "drawer:leave", async () => { await show(page, "turn_mine_poor", "player"); await page.evaluate(() => document.getElementById("history").click()); await sleep(80); });
  await page.evaluate(() => document.getElementById("drawer-close").click());
  await sleep(60);
  // each new prompt: its first control
  const prompts = [["waiting_other_turn", "challenge_prompt", "bar:challenge"], ["challenge_prompt", "lose_true", "hand:0"],
    ["lose_true", "exchange_prompt", "xc:0"], ["exchange_prompt", "turn_mine_poor", "bar:income"], ["turn_mine_poor", "block_prompt_aid", "bar:block:Banker"],
    ["block_prompt_aid", "block_prompt_steal", "bar:block:Smuggler"]];
  for (const [from, to, want] of prompts) {
    await show(page, from, "player");
    await show(page, to, "player");
    const got = await activeK(page);
    check(got === want, `new prompt ${to}: focus on its first control ${want} (${got})`);
  }
  // a move is made and the table moves on: focus does not fall to the page
  await show(page, "challenge_prompt", "player");
  await focusK(page, "bar:pass"); await clearSent(page); await press(page, "Enter");
  check((await sentMsgs(page)).length === 1, "Pass is sent");
  await show(page, "waiting_other_turn", "player");
  const after = await activeK(page);
  check(after && after !== "BODY" && after !== "HTML", `after the move the focus is on the bar, not the page (${after})`);
  // not while a dialog is open
  await page.evaluate(() => document.getElementById("history").click());
  await sleep(60);
  const inside = await page.evaluate(() => !!document.activeElement.closest("#drawer"));
  await show(page, "lose_true", "player");
  check(inside && await page.evaluate(() => !!document.activeElement.closest("#drawer")), "a new prompt does not take focus out of an open dialog");
  check(errors.length === 0, `focus: no page errors (${errors.slice(0, 2).join(" | ")})`);
  await ctx.close();
}

// ---------------------------------------------------------------- 4b. a Tab walk
// From before the first control to past the last: every stop is a visible control with a name, in
// the order of the page (header, then the table, then the moves), and Tab does not get stuck.
async function tabwalk() {
  const { ctx, page, errors } = await phone(vp("390x844"));
  const walk = async (limit = 30) => {
    await page.evaluate(() => { const s = document.createElement("span"); s.tabIndex = -1; document.body.prepend(s); s.focus(); s.remove(); });
    const stops = [];
    for (let i = 0; i < limit; i++) {
      await page.keyboard.press("Tab");
      const st = await page.evaluate(() => {
        const a = document.activeElement;
        if (!a || a === document.body || a === document.documentElement) return { away: true };
        const r = a.getBoundingClientRect(), cs = getComputedStyle(a);
        return { key: a.dataset.k || a.id || a.tagName, name: (a.getAttribute("aria-label") || a.textContent || "").replace(/\s+/g, " ").trim(),
          shown: r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && !a.closest("[hidden]") };
      });
      if (st.away || stops.some((x) => x.key === st.key)) break;
      stops.push(st);
    }
    return stops;
  };
  const HEAD = ["rules", "party-end", "history"];
  const cases = [
    ["a turn", "turn_mine_rich", "player", null, [...HEAD, "bar:income", "bar:aid", "bar:coup", "bar:claim"]],
    ["a turn with Coup not on offer", "turn_mine_poor", "player", null, [...HEAD, "bar:income", "bar:aid", "bar:coup", "bar:claim"]],
    ["aiming a Coup", "turn_mine_rich", "player", async () => { await focusK(page, "bar:coup"); await press(page, "Enter"); }, [...HEAD, "seat:p2", "seat:p3", "seat:p4", "seat:p5", "seat:p6", "bar:cancel"]],
    ["a challenge", "challenge_prompt", "player", null, [...HEAD, "bar:challenge", "bar:pass"]],
    ["a block", "block_prompt_steal", "player", null, [...HEAD, "bar:block:Smuggler", "bar:block:Broker", "bar:allow"]],
    ["giving up a card", "lose_true", "player", null, [...HEAD, "hand:0", "hand:1"]],
    ["an exchange", "exchange_prompt", "player", null, [...HEAD, "xc:0", "xc:1", "xc:2", "xc:3", "bar:keep"]],
    ["waiting for someone", "waiting_other_turn", "player", null, HEAD],
    ["a Party spectator", "spectator_full_table", "spectator", null, HEAD],
  ];
  for (const [what, key, label, prep, want] of cases) {
    await show(page, key, label);
    if (prep) await prep();
    const stops = await walk();
    // a browser makes a table that scrolls and has nothing to press in it a Tab stop (so a keyboard can
    // scroll it): that stop is the named group, and the controls come in the page's order around it
    const keys = stops.map((x) => x.key).filter((k) => k !== "stage");
    const unnamed = stops.filter((x) => !x.name || !x.shown).map((x) => x.key);
    // block prompts offer the roles that can stop this move: the sequence is what the server asks for
    const ok = JSON.stringify(keys) === JSON.stringify(want);
    check(ok && unnamed.length === 0, `Tab walk, ${what}: ${keys.join(" > ")}${ok ? "" : "  (expected " + want.join(" > ") + ")"}${unnamed.length ? "; no name or not shown: " + unnamed.join(",") : ""}`);
  }
  // the one main landmark is top-level, and the scroller around it is a named group, not a landmark
  const land = await page.evaluate(() => {
    const m = document.querySelectorAll("main"), s = document.getElementById("stage");
    const inside = m[0] && m[0].parentElement.closest("[role=region], [role=banner], [role=navigation], [role=complementary], [role=form], [role=search], header, nav, aside, form");
    return { mains: m.length, nested: !!inside, role: s.getAttribute("role"), name: s.getAttribute("aria-label") };
  });
  check(land.mains === 1 && !land.nested && land.role === "group" && !!land.name, `one main landmark, top level; the scroller is the named group "${land.name}" (${JSON.stringify(land)})`);
  check(errors.length === 0, `Tab walk: no page errors (${errors.slice(0, 2).join(" | ")})`);
  await ctx.close();
}

// ---------------------------------------------------------------- 5. the live region
async function live() {
  const { ctx, page, errors } = await phone(vp("390x844"));
  const regions = await page.evaluate(() => ({
    polite: [...document.querySelectorAll('[aria-live="polite"], [role="status"], [role="log"]')].filter((e) => !e.closest("dialog")).map((e) => e.id),
    assertive: [...document.querySelectorAll('[aria-live="assertive"], [role="alert"]')].map((e) => e.id),
  }));
  check(JSON.stringify(regions.polite) === '["live"]', `one polite live region (${JSON.stringify(regions.polite)})`);
  const say = () => page.evaluate(() => ({ polite: document.getElementById("live").textContent, urgent: document.getElementById("live-urgent").textContent }));
  await show(page, "waiting_other_turn", "player");
  let t = await say();
  check(/'s turn\.$/.test(t.polite) && t.urgent === "", `someone else's turn is said politely: "${t.polite}"`);
  await show(page, "turn_mine_poor", "player");
  t = await say();
  check(t.polite === "Your turn." && t.urgent === "", `my turn: "${t.polite}"`);
  await show(page, "challenge_prompt", "spectator");
  t = await say();
  const cp = states("challenge_prompt");
  check(t.polite === cp.chain.join(" ") && t.urgent === "", `a claim is announced as the server's line, politely: ${JSON.stringify(t)}`);
  const claim = cp.chain.join(" "), ask = "Your call: challenge or pass?";
  await show(page, "waiting_other_turn", "player");
  await show(page, "challenge_prompt", "player");
  t = await say();
  check(t.urgent.includes(claim) && t.urgent.endsWith(ask) && t.polite === "", `a prompt on a timer is assertive, with the news that led to it, said once: ${JSON.stringify(t)}`);
  await show(page, "waiting_other_turn", "player");
  await show(page, "challenge_prompt", "player", { deadline: false });
  t = await say();
  check(t.polite.includes(claim) && t.polite.endsWith(ask) && t.urgent === "", `...and polite when there is no timer: ${JSON.stringify(t)}`);
  // an outcome: only what the server wrote since the last state
  await show(page, "challenge_prompt", "bystander");
  await show(page, "lose_bluff", "bystander");
  t = await say();
  const lb = states("lose_bluff").chain;
  check(lb.slice(1).every((l) => t.polite.includes(l)) && !t.polite.includes(lb[0]), `an outcome: the new log lines, once: "${t.polite.slice(0, 90)}"`);
  const polite0 = t.polite;
  await show(page, "lose_bluff", "bystander");
  t = await say();
  check(t.polite === polite0, "the same state again says nothing new");
  await show(page, "results", "player");
  t = await say();
  check(/You win!$/.test(t.polite), `a result: "${t.polite}"`);
  await show(page, "results", "bystander");
  t = await say();
  check(/ wins!$/.test(t.polite), `a result for a bystander: "${t.polite}"`);
  // nothing private: the exchange pool and a spectator's view of hidden hands
  const ex = states("exchange_prompt");
  const hidden = ex.views.player.game.me.prompt.pool.filter((r) => !ex.chain.join(" ").includes(r));
  await show(page, "exchange_prompt", "player");
  t = await say();
  check(hidden.length > 0 && hidden.every((r) => !(t.polite + " " + t.urgent).includes(r)), `an exchange does not announce the cards offered (${hidden.join(", ")} not in "${t.polite} ${t.urgent}")`);
  const sp = states("spectator_full_table").views.spectator.game.seats.flatMap((s) => s.cards || []);
  await show(page, "spectator_full_table", "spectator");
  t = await say();
  const known = states("spectator_full_table").chain.join(" ");
  check(sp.length > 0 && sp.filter((r) => !known.includes(r)).every((r) => !t.polite.includes(r)), `a spectator's hidden hands are not announced ("${t.polite.slice(0, 70)}")`);
  check(errors.length === 0, `live region: no page errors (${errors.slice(0, 2).join(" | ")})`);
  await ctx.close();
}

// ---------------------------------------------------------------- 6. legibility, contrast, sentences
// Contrast the way a person meets it: the colour the text is drawn in against what is really behind
// each of its letters. Two captures of the same screen, one as it is and one with the text made
// transparent: a pixel that is the text's own colour in the first and something else in the second
// is the heart of a letter, and the second capture says what that letter sits on.
async function contrastRows(page, specs) {
  const out = [];
  for (const spec of specs) {
    const meta = await page.evaluate((s) => {
      const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); const p = m[1].split(",").map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
      const e = [...document.querySelectorAll(s.sel)][s.nth || 0];
      if (!e) return { none: "no such element" };
      e.scrollIntoView({ block: "center", inline: "nearest" });
      let o = 1;
      for (let n = e; n && n.nodeType === 1; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity);
      const cs = getComputedStyle(e), r = e.getBoundingClientRect();
      let L = Math.max(0, r.left), T = Math.max(0, r.top), R = Math.min(innerWidth, r.right), B = Math.min(innerHeight, r.bottom);
      for (let n = e.parentElement; n; n = n.parentElement) {
        const c = getComputedStyle(n);
        if (/(hidden|auto|scroll|clip)/.test(c.overflowY + c.overflowX) && n !== document.body && n !== document.documentElement) {
          const b = n.getBoundingClientRect(); L = Math.max(L, b.left); T = Math.max(T, b.top); R = Math.min(R, b.right); B = Math.min(B, b.bottom);
        }
      }
      return { text: e.textContent.trim().slice(0, 24), fg: parse(cs.color), alpha: parse(cs.color).a * o, size: parseFloat(cs.fontSize),
        x: Math.floor(L), y: Math.floor(T), w: Math.ceil(R - L), h: Math.ceil(B - T) };
    }, spec);
    if (meta.none || meta.w < 1 || meta.h < 1) { out.push({ name: spec.name, absent: true, why: meta.none || `no size ${meta.w}x${meta.h}` }); continue; }
    await sleep(60);
    const shown = await page.screenshot({ encoding: "base64", type: "png" });
    await page.addStyleTag({ content: "html[data-probe] #app *, html[data-probe] dialog * { color: transparent !important; text-shadow: none !important; -webkit-text-fill-color: transparent !important; }" });
    await page.evaluate(() => document.documentElement.setAttribute("data-probe", "1"));
    await sleep(60);
    const bare = await page.screenshot({ encoding: "base64", type: "png" });
    await page.evaluate(() => document.documentElement.removeAttribute("data-probe"));
    const row = await page.evaluate(async (a64, b64, q) => {
      const load = async (b64) => { const img = new Image(); await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = "data:image/png;base64," + b64; }); const cv = document.createElement("canvas"); cv.width = img.width; cv.height = img.height; const cx = cv.getContext("2d", { willReadFrequently: true }); cx.drawImage(img, 0, 0); return cx.getImageData(q.x, q.y, q.w, q.h).data; };
      const A = await load(a64), B = await load(b64);
      const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      const lum = (r, g, b) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      let worst = 99, sum = 0, n = 0, soft = 0;
      for (let i = 0; i < A.length; i += 4) {
        const dr = Math.abs(A[i] - B[i]) + Math.abs(A[i + 1] - B[i + 1]) + Math.abs(A[i + 2] - B[i + 2]);
        if (dr < 60) continue;                                              // not part of a letter
        const e = [q.fg.r * q.alpha + B[i] * (1 - q.alpha), q.fg.g * q.alpha + B[i + 1] * (1 - q.alpha), q.fg.b * q.alpha + B[i + 2] * (1 - q.alpha)];
        const core = Math.abs(A[i] - e[0]) + Math.abs(A[i + 1] - e[1]) + Math.abs(A[i + 2] - e[2]) <= 36;
        if (!core) { soft++; continue; }                                    // the soft edge of a letter
        const l1 = lum(e[0], e[1], e[2]), l2 = lum(B[i], B[i + 1], B[i + 2]);
        const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        worst = Math.min(worst, ratio); sum += ratio; n++;
      }
      return n ? { worst: +worst.toFixed(2), mean: +(sum / n).toFixed(2), pixels: n } : { absent: true, why: `no letter pixels (${soft} soft) in ${q.w}x${q.h} at ${q.x},${q.y}; colour ${JSON.stringify(q.fg)} x ${q.alpha}` };
    }, shown, bare, meta);
    out.push({ name: spec.name, text: meta.text, size: meta.size, ...row });
  }
  return out;
}
const CONTRAST_SPECS = [
  { name: "role name Banker", state: ["turn_mine_poor", "player"], sel: "#hand .card.role-banker .nm" },
  { name: "role name Agent", state: ["turn_mine_poor", "player"], sel: "#hand .card.role-agent .nm" },
  { name: "role name Smuggler", state: ["turn_mine_rich", "player"], sel: "#hand .card.role-smuggler .nm" },
  { name: "role name Guardian", state: ["turn_mine_rich", "player"], sel: "#hand .card.role-guardian .nm" },
  { name: "role name Broker", state: ["turn_must_coup", "player"], sel: "#hand .card.role-broker .nm" },
  { name: "primary label (Income)", state: ["turn_mine_poor", "player"], sel: "#bar .act.primary span:last-child" },
  { name: "danger label (Challenge)", state: ["challenge_prompt", "player"], sel: "#bar .act.danger span:last-child" },
  { name: "claim label (Claim)", state: ["turn_mine_poor", "player"], sel: "#bar .act.blue span:last-child" },
  { name: "seat name 1", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 0 },
  { name: "seat name 2", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 1 },
  { name: "seat name 3", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 2 },
  { name: "seat name 4", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 3 },
  { name: "seat name 5", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 4 },
  { name: "seat name 6", state: ["spectator_full_table", "spectator"], sel: ".seat > .nm", nth: 5 },
  { name: "caption", state: ["waiting_other_turn", "player"], sel: "#caption" },
  { name: "caption, your call", state: ["challenge_prompt", "player"], sel: "#caption" },
  { name: "waiting message (muted)", state: ["waiting_other_turn", "player"], sel: "#bar .bar-msg" },
  { name: "story line", state: ["lose_true", "player"], sel: "#reveal li, #play .chip.last", nth: 0 },
];
async function contrast() {
  const normal = await phone(vp("390x844"));
  const rows = [];
  for (const s of CONTRAST_SPECS) {
    await show(normal.page, s.state[0], s.state[1]);
    await page_scrollEnd(normal.page);
    const r = await contrastRows(normal.page, [s]);
    rows.push(...r);
  }
  METRICS.contrast = rows;
  for (const r of rows) {
    if (r.absent) { check(false, `contrast: ${r.name} could not be measured (${r.why})`); continue; }
    check(r.worst >= 4.5, `contrast ${r.name} "${r.text}" ${r.size}px: ${r.worst}:1 worst pixel, ${r.mean}:1 mean (4.5:1)`);
  }
  // prefers-contrast: more raises muted text and every hairline border
  const more = await phone(vp("390x844"), { contrast: true });
  const muted = async (p) => { await show(p, "waiting_other_turn", "player"); return p.evaluate(() => { const m = document.querySelector("#bar .bar-msg"), b = document.getElementById("bar"); const cs = getComputedStyle(m), bs = getComputedStyle(b); return { color: cs.color, border: bs.borderTopColor }; }); };
  const m0 = await muted(normal.page), m1 = await muted(more.page);
  const rgb = (c) => c.match(/[\d.]+/g).map(Number);
  const lumOf = (c) => { const [r, g, b] = rgb(c); const f = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const alphaOf = (c) => (rgb(c)[3] === undefined ? 1 : rgb(c)[3]);
  METRICS.misc.contrastMore = { muted: [m0.color, m1.color], border: [m0.border, m1.border] };
  check(lumOf(m1.color) > lumOf(m0.color), `prefers-contrast: more lightens muted text (${m0.color} -> ${m1.color})`);
  check(alphaOf(m1.border) >= 2.5 * alphaOf(m0.border), `prefers-contrast: more strengthens borders (${m0.border} -> ${m1.border})`);
  const calm = await contrastRows(more.page, [CONTRAST_SPECS.find((s) => s.name.startsWith("waiting"))]);
  const calmN = await contrastRows(normal.page, [CONTRAST_SPECS.find((s) => s.name.startsWith("waiting"))]);
  check(calm[0].worst > calmN[0].worst, `...so muted text is ${calm[0].worst}:1 instead of ${calmN[0].worst}:1`);
  await more.ctx.close();
  await normal.ctx.close();
}

async function legibility() {
  const normal = await phone(vp("390x844"));
  // text follows the root size: 16 -> 32 px doubles it; nothing is under 12px at 16
  const big = await phone({ name: "root32", w: 390, h: 844, root: 32 });
  const sizeOf = (p, sel) => p.evaluate((sel) => { const e = document.querySelector(sel); return e ? parseFloat(getComputedStyle(e).fontSize) : null; }, sel);
  await show(big.page, "lose_true", "player"); await show(normal.page, "lose_true", "player");
  for (const [what, sel] of [["caption", "#caption"], ["story line", "#reveal li"], ["seat name", ".seat > .nm"], ["bar label", "#bar .bar-msg"]]) {
    const a = await sizeOf(normal.page, sel), b = await sizeOf(big.page, sel);
    check(a !== null && b !== null && b >= 1.9 * a, `${what} follows the root size: ${a}px -> ${b}px at 200%`);
  }
  await big.ctx.close();

  // one visible sentence, with numbers, never only a tooltip
  const { page } = normal;
  await show(page, "turn_mine_poor", "player");
  const coup = await page.evaluate(() => { const b = document.querySelector('[data-k="bar:coup"]'), n = document.getElementById("bar-note"); const r = n.getBoundingClientRect(); return { note: n.textContent, hidden: n.hidden, desc: b.getAttribute("aria-describedby"), title: b.getAttribute("title"), h: r.height, lh: parseFloat(getComputedStyle(n).lineHeight), disabled: b.getAttribute("aria-disabled") }; });
  check(coup.note === "Coup needs 7 coins, you have 2." && !coup.hidden && coup.desc === "bar-note" && !coup.title && coup.disabled === "true", `a Coup you cannot afford: "${coup.note}" shown, described by, no tooltip`);
  check(coup.h < 2.2 * coup.lh + 12, `...in one line (${Math.round(coup.h)}px)`);
  await show(page, "turn_mine_rich", "player");
  check((await page.evaluate(() => document.getElementById("bar-note").hidden)), "no sentence when Coup is on offer");
  await show(page, "turn_mine_poor", "player");
  await page.evaluate(() => document.querySelector('[data-k="bar:claim"]').click());
  await sleep(60);
  const sheetNote = await page.evaluate(() => { const n = document.querySelector("#sheet .sheet-note"); if (!n) return null; const r = n.getBoundingClientRect(); return { t: n.textContent, h: r.height, lh: parseFloat(getComputedStyle(n).lineHeight), names: [...document.querySelectorAll("#sheet .act")].map((b) => b.textContent.replace(/\s+/g, " ").trim()) }; });
  check(sheetNote && sheetNote.t === "Strike needs 3 coins, you have 2." && sheetNote.h < 1.6 * sheetNote.lh + 2 && !sheetNote.names.some((n) => /Strike/.test(n)), `Strike absent below 3 coins: one line "${sheetNote && sheetNote.t}"`);
  await show(page, "turn_mine_rich", "player");
  await page.evaluate(() => document.querySelector('[data-k="bar:claim"]').click());
  await sleep(60);
  check(await page.evaluate(() => !document.querySelector("#sheet .sheet-note") && [...document.querySelectorAll("#sheet .act")].some((b) => /Strike/.test(b.textContent))), "...and no line once Strike is on offer");
  // the other moves that are not on offer say so too, with the numbers
  await show(page, "turn_must_coup", "player");
  const forced = await page.evaluate(() => ({ msg: document.querySelector("#bar .bar-msg").textContent, acts: [...document.querySelectorAll("#bar .act")].map((b) => b.textContent.trim()) }));
  check(forced.msg === "You have 11 coins: at 10 or more you must Coup." && forced.acts.length === 1, `a forced Coup says why, with the numbers: "${forced.msg}"`);
  await show(page, "exchange_prompt", "player");
  const pick = () => page.evaluate(() => { const n = document.getElementById("bar-note"), k = document.querySelector('[data-k="bar:keep"]'); return { note: n.hidden ? "" : n.textContent, desc: k.getAttribute("aria-describedby"), off: k.getAttribute("aria-disabled") }; });
  let ex = await pick();
  check(ex.note === "Pick 2 cards to keep: 0 picked so far." && ex.desc === "bar-note" && ex.off === "true", `an exchange that cannot be kept yet says why: ${JSON.stringify(ex)}`);
  await page.evaluate(() => { document.querySelector('[data-k="xc:0"]').click(); document.querySelector('[data-k="xc:2"]').click(); });
  await sleep(60);
  ex = await pick();
  check(ex.note === "" && ex.off === null, `...and says nothing once two are picked: ${JSON.stringify(ex)}`);
  await normal.ctx.close();
}
async function page_scrollEnd(page) {
  await page.evaluate(() => { const app = document.getElementById("app"), sc = app.dataset.dock === "flow" ? app : document.getElementById("stage"); if (sc) sc.scrollTop = sc.scrollHeight; });
}

// ---------------------------------------------------------------- 7. toasts and the reconnect line
async function overlays() {
  for (const name of ["390x844", "360x640", "320x568"]) {
    const { ctx, page, errors } = await phone(vp(name));
    await show(page, "challenge_prompt", "player");
    await page.evaluate(() => { Hub.toast("First notice"); Hub.toast("Second notice", "err"); });
    await sleep(80);
    const t = await page.evaluate(() => {
      const R = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; };
      const toasts = [...document.querySelectorAll(".toast")].filter((e) => getComputedStyle(e).display !== "none");
      // what is on the screen: the table's rows only where its window shows them
      const win = document.getElementById("stage").getBoundingClientRect();
      const seen = (e) => { const r = R(e); if (!e.closest("#stage")) return r; return { l: r.l, r: r.r, t: Math.max(r.t, win.top), b: Math.min(r.b, win.bottom) }; };
      const others = ["#caption", "#bar", "#opponents .seat", "#hand .card", "#play .card", "#reveal"].flatMap((s) => [...document.querySelectorAll(s)].map((e) => [s, seen(e)]));
      const tr = toasts[0] ? R(toasts[0]) : null;
      const hit = tr ? others.filter(([s, r]) => Math.min(r.r, tr.r) - Math.max(r.l, tr.l) > 0 && Math.min(r.b, tr.b) - Math.max(r.t, tr.t) > 0).map(([s]) => s) : [];
      return { n: toasts.length, text: toasts[0] && toasts[0].textContent, tr, head: R(document.getElementById("head")), hit, W: innerWidth, said: document.getElementById("live").textContent };
    });
    check(t.n === 1 && t.text === "Second notice", `${name}: at most one toast is shown, the newest (${t.n}: "${t.text}")`);
    check(t.tr && t.tr.t >= 0 && t.tr.b <= t.head.b + 1 && t.tr.l >= 0 && t.tr.r <= t.W, `${name}: the toast sits in the top band (${Math.round(t.tr.t)}..${Math.round(t.tr.b)} of a ${Math.round(t.head.b)}px header)`);
    check(t.hit.length === 0, `${name}: the toast is never over the caption, the moves, a seat or a card (${t.hit.join(",") || "none"})`);
    check(t.said === "Second notice" || t.said.includes("notice"), `${name}: a toast is said in the live region ("${t.said}")`);
    // the reconnect line
    await page.evaluate(() => { window.__sent.length = 0; window.__sockets[window.__sockets.length - 1].close(); });
    await sleep(120);
    const b = await page.evaluate(() => {
      const R = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, h: r.height }; };
      const ban = document.getElementById("conn-banner"), bar = document.getElementById("bar");
      const br = R(ban), cs = getComputedStyle(ban);
      const over = [...document.querySelectorAll("#hand .card, #bar, #bar .act")].filter((e) => { const r = R(e); return Math.min(r.r, br.r) - Math.max(r.l, br.l) > 1 && Math.min(r.b, br.b) - Math.max(r.t, br.t) > 1; }).map((e) => e.id || e.className.slice(0, 20));
      const act = document.querySelector('#bar .act'); act.click();
      return { hidden: ban.hidden, text: ban.textContent, h: br.h, lh: parseFloat(cs.lineHeight), over, aria: bar.getAttribute("aria-disabled"), op: parseFloat(getComputedStyle(bar).opacity),
        sent: window.__sent.filter((m) => m.t !== "ping").length, inDock: !!ban.closest("#dock"), W: innerWidth, l: br.l, r: br.r };
    });
    check(!b.hidden && /^[A-Z][a-z]/.test(b.text) && b.text !== b.text.toUpperCase(), `${name}: the reconnect line is sentence case ("${b.text}")`);
    check(b.h <= 1.5 * b.lh + 12 && b.l >= 0 && b.r <= b.W, `${name}: ...one line (${Math.round(b.h)}px)`);
    check(b.over.length === 0 && b.inDock, `${name}: ...clear of the hand and the bar (${b.over.join(",") || "none"})`);
    check(b.aria === "true" && b.op < 0.6 && b.sent === 0, `${name}: offline the bar is aria-disabled (${b.aria}), dimmed (opacity ${b.op}) and ignores taps (${b.sent} sent)`);
    await sleep(900);
    const back = await page.evaluate(() => ({ hidden: document.getElementById("conn-banner").hidden, aria: document.getElementById("bar").getAttribute("aria-disabled") }));
    check(back.hidden && back.aria === null, `${name}: back online the line goes and the bar works again (${JSON.stringify(back)})`);
    check(errors.length === 0, `${name}: overlays: no page errors (${errors.slice(0, 2).join(" | ")})`);
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 8. the history drawer
async function drawer() {
  for (const name of ["390x664", "320x568"]) {
    const { ctx, page, errors } = await phone(vp(name));
    await show(page, "challenge_prompt", "player");
    await focusK(page, "bar:pass");
    await page.evaluate(() => document.getElementById("history").focus());
    await press(page, "Enter");
    const open = await page.evaluate(() => { const d = document.getElementById("drawer"); return { open: d.open, modal: d.matches(":modal"), inside: !!document.activeElement.closest("#drawer"), active: document.activeElement.id }; });
    check(open.open && open.modal && open.inside, `${name}: the drawer opens as a modal with focus inside (${JSON.stringify(open)})`);
    // Tab past the last control of a modal dialog leaves the page for the browser's own bar (here:
    // nothing, the body) and comes back in; it never lands on the table behind it
    const trap = [];
    for (let i = 0; i < 10; i++) { await press(page, "Tab"); trap.push(await page.evaluate(() => { const a = document.activeElement; return !a || a === document.body ? "away" : a.closest("#drawer") ? "in" : "BEHIND:" + (a.dataset.k || a.id || a.tagName); })); }
    for (let i = 0; i < 4; i++) { await page.keyboard.down("Shift"); await press(page, "Tab"); await page.keyboard.up("Shift"); trap.push(await page.evaluate(() => { const a = document.activeElement; return !a || a === document.body ? "away" : a.closest("#drawer") ? "in" : "BEHIND:" + (a.dataset.k || a.id || a.tagName); })); }
    check(trap.filter((x) => x === "in").length >= 6 && !trap.some((x) => x.startsWith("BEHIND")), `${name}: focus is trapped: 14 Tab and Shift+Tab presses never land on the table behind (${trap.join(" ")})`);
    const inert = await page.evaluate(() => {
      const b = document.querySelector("#bar .act"), r = b.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const before = document.activeElement; b.focus();
      return { hit: hit && (hit.closest("#bar") ? "bar" : hit.id || hit.tagName), moved: document.activeElement === b };
    });
    check(inert.hit !== "bar" && !inert.moved, `${name}: the table behind is inert (a tap lands on ${inert.hit}; focusing a move ${inert.moved ? "worked" : "did not work"})`);
    const call = await page.evaluate(() => { const c = document.getElementById("drawer-call"); const r = c.getBoundingClientRect(); return { hidden: c.hidden, text: c.textContent, live: c.closest("[aria-live], [role=status], [role=alert], [role=log]") ? "live" : "", desc: document.getElementById("drawer").getAttribute("aria-describedby"), vis: r.width > 0 && r.height > 0 }; });
    check(!call.hidden && call.vis && /^Your call is waiting/.test(call.text) && call.live === "" && call.desc === "drawer-call", `${name}: "Your call is waiting" is shown while the prompt's timer runs, as the dialog's description and not a second live region ("${call.text}")`);
    await press(page, "Escape");
    const closed = await page.evaluate(() => ({ open: document.getElementById("drawer").open, active: document.activeElement.id }));
    check(!closed.open && closed.active === "history", `${name}: Escape closes it and focus returns to the button (${JSON.stringify(closed)})`);
    // no timer, no nudge
    await show(page, "challenge_prompt", "player", { deadline: false });
    await page.evaluate(() => document.getElementById("history").click());
    await sleep(60);
    check(await page.evaluate(() => document.getElementById("drawer-call").hidden && !document.getElementById("drawer").hasAttribute("aria-describedby")), `${name}: with no timer running there is no nudge`);
    // the rules sentence comes from the single source (briefing.js FACTS)
    await page.evaluate(() => { BluffBriefing.FACTS.coupCost = 9; BluffBriefing.FACTS.mustCoupAt = 12; render(); });
    const rule = await page.evaluate(() => [...document.querySelectorAll("#rolehelp div")].pop().textContent);
    check(/Coup: pay 9 \(must at 12\+\)/.test(rule), `${name}: the drawer's rules line is built from the rules source ("${rule}")`);
    await page.evaluate(() => { BluffBriefing.FACTS.coupCost = 7; BluffBriefing.FACTS.mustCoupAt = 10; render(); });
    // Leave game still goes through the table's own confirmation, and the drawer stays usable (provider spec)
    await page.keyboard.press("Escape"); await sleep(40);
    await show(page, "turn_mine_poor", "player");
    await clearSent(page);
    await page.click("#history"); await sleep(60);
    await page.evaluate(() => [...document.querySelectorAll("#drawer .act")].find((b) => /Leave game/.test(b.textContent)).click());
    await sleep(60);
    check(await page.evaluate(() => document.getElementById("confirm").open), `${name}: Leave game asks first`);
    await page.click("#confirm-yes"); await sleep(60);
    check((await sentMsgs(page)).some((m) => m.t === "leave_game") && await page.evaluate(() => document.getElementById("drawer").open), `${name}: confirming sends leave_game and the drawer is still open`);
    await page.click("#drawer-close"); await sleep(60);
    check(!(await page.evaluate(() => document.getElementById("drawer").open)), `${name}: #drawer-close closes it`);
    check(errors.length === 0, `${name}: drawer: no page errors (${errors.slice(0, 2).join(" | ")})`);
    await ctx.close();
  }
  // at every size, 200 % text included: nothing in the drawer is wider than the drawer, it does not
  // scroll sideways, and its close button is on the screen and a full 44 px target
  for (const v of VIEWPORTS) {
    const { ctx, page } = await phone(v);
    await show(page, "challenge_prompt", "player");
    await page.evaluate(() => document.getElementById("history").click());
    await sleep(80);
    const m = await page.evaluate(() => {
      const d = document.getElementById("drawer"), r = d.getBoundingClientRect(), x = document.getElementById("drawer-close").getBoundingClientRect();
      const wide = [...d.querySelectorAll("*")].filter((e) => { const b = e.getBoundingClientRect(); return b.width > 0 && (b.right > r.right + 0.5 || b.left < r.left - 0.5); }).map((e) => e.id || e.className || e.tagName).slice(0, 4);
      return { sw: d.scrollWidth, cw: d.clientWidth, wide, vw: innerWidth, left: Math.round(r.left), right: Math.round(r.right),
        close: x.left >= 0 && x.right <= innerWidth && x.top >= 0 && x.bottom <= innerHeight && x.width >= 44 && x.height >= 44 };
    });
    check(m.sw <= m.cw && m.wide.length === 0 && m.close && m.left >= 0 && m.right <= m.vw,
      `${v.name}: the open drawer fits the screen: ${m.right - m.left}px wide, scrolls sideways ${m.sw > m.cw ? "YES (" + m.sw + ">" + m.cw + ")" : "no"}, wider than it: ${m.wide.join(",") || "none"}, close button on screen: ${m.close}`);
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 9. the Party's view of the page
// The same assertions the Party's provider spec makes on the host's table at 390x844 (its
// assertPhoneLayout), plus the strings it looks for.
async function partySurface() {
  for (const v of [vp("390x844"), vp("360x640"), vp("320x568")]) {
    const { ctx, page, errors } = await phone(v);
    await show(page, "turn_mine_poor", "player");
    await sleep(450);                        // the timer is drawn by a 250 ms interval
    const rep = await page.evaluate((sels) => {
      const w = innerWidth, hgt = innerHeight;
      const boxes = sels.map((s) => {
        const el = document.querySelector(s);
        if (!el || el.hidden || !el.offsetParent) return { s, visible: false };
        const r = el.getBoundingClientRect();
        return { s, visible: true, l: r.left, t: r.top, r: r.right, b: r.bottom, spills: el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1 };
      });
      const overlaps = [], vis = boxes.filter((b) => b.visible);
      for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) {
        const a = vis[i], b = vis[j];
        if (a.l < b.r - 1 && b.l < a.r - 1 && a.t < b.b - 1 && b.t < a.b - 1) overlaps.push(`${a.s} x ${b.s}`);
      }
      return { scroll: document.documentElement.scrollWidth - w, hgt, w, boxes, overlaps };
    }, ["#rules", "#party-end", "#timer", "#history"]);
    const okBoxes = rep.boxes.filter((b) => b.visible).every((b) => b.l >= -1 && b.r <= rep.w + 1 && b.b <= rep.hgt + 1 && !b.spills);
    check(rep.scroll <= 0 && rep.overlaps.length === 0 && okBoxes && rep.boxes.filter((b) => b.visible).length === 4, `${v.name}: the Party's phone-layout assertion on #rules #party-end #timer #history holds (${rep.boxes.filter((b) => b.visible).length} visible, overlaps ${rep.overlaps.length}, sideways ${rep.scroll})`);
    if (v.name === "390x844") {
      const surface = await page.evaluate(() => ({
        rules: document.getElementById("rules").getAttribute("aria-label"), history: !!document.getElementById("history"), close: !!document.getElementById("drawer-close"),
        yes: !!document.getElementById("confirm-yes"), nav: !!document.getElementById("avrana-navigation") && getComputedStyle(document.getElementById("avrana-navigation")).display,
        banned: /playing ·|watching ·|Setting up/.test(document.body.innerText), backToParty: [...document.querySelectorAll("a, button")].some((e) => e.offsetParent && /Back to Party/.test(e.textContent)),
        briefing: document.getElementById("briefing").getAttribute("aria-labelledby"), barButtons: [...document.querySelectorAll("#bar button")].map((b) => b.textContent.trim()),
      }));
      check(surface.rules === "How to play" && surface.history && surface.close && surface.yes && !surface.banned && !surface.backToParty && surface.briefing === "briefing-title", `the Party's selectors and texts are there (${JSON.stringify({ ...surface, barButtons: undefined })})`);
      // results: the host's two buttons carry only their words; a guest waits
      await show(page, "results", "player");
      const bar = await page.evaluate(() => [...document.querySelectorAll("#bar button")].map((b) => b.textContent.trim()));
      check(JSON.stringify(bar) === '["Play again","Party Home"]', `results for the host: ${JSON.stringify(bar)}`);
      await page.evaluate(() => { window.AvranaParty.isHost = () => false; render(); });
      const wait = await page.evaluate(() => ({ text: document.getElementById("bar").textContent, buttons: document.querySelectorAll("#bar button").length }));
      check(/Waiting for Alexandria/.test(wait.text) && wait.buttons === 0, `results for a guest: "${wait.text}"`);
    }
    check(errors.length === 0, `${v.name}: Party surface: no page errors (${errors.slice(0, 2).join(" | ")})`);
    await ctx.close();
  }
  // outside a Party the home button is back in the header row and the row still holds
  for (const v of [vp("390x844"), vp("320x568"), vp("zoom200-195x332")]) {
    const { ctx, page } = await phone(v, { standalone: true });
    await show(page, "turn_mine_poor", "player");
    await sleep(450);
    const m = await measure(page);
    const hdr = await page.evaluate(() => {
      const R = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; };
      const els = ["#home", "#rules", "#timer", "#history"].map((s) => document.querySelector(s)).filter((e) => e && e.offsetParent);
      const rs = els.map(R); let overlap = 0;
      for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) if (rs[i].l < rs[j].r - 1 && rs[j].l < rs[i].r - 1 && rs[i].t < rs[j].b - 1 && rs[j].t < rs[i].b - 1) overlap++;
      return { n: els.length, overlap, inside: rs.every((r) => r.l >= -1 && r.r <= innerWidth + 1) };
    });
    check(hdr.n === 4 && hdr.overlap === 0 && hdr.inside && m.maxOverlap <= 20 && m.docOverflowX <= 0, `${v.name} standalone: home, ?, timer and history sit in the header row (${hdr.n} shown, overlaps ${hdr.overlap}, worst ${m.maxOverlap}px2)`);
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 10. the notch and the home bar
async function insets() {
  const cases = [["390x844", { top: 47, bottom: 34, left: 0, right: 0 }], ["844x390", { top: 0, bottom: 21, left: 47, right: 47 }], ["640x360", { top: 0, bottom: 21, left: 47, right: 47 }]];
  for (const [name, ins] of cases) {
    const { ctx, page, errors } = await phone(vp(name));
    const client = await page.createCDPSession();
    let supported = true;
    try { await client.send("Emulation.setSafeAreaInsetsOverride", { insets: ins }); } catch (e) { supported = false; check(false, `${name}: this Chrome cannot emulate safe-area insets (${String(e.message).slice(0, 80)})`); }
    if (!supported) { await ctx.close(); continue; }
    await sleep(100);
    const bad = [];
    for (const [key, label] of [["turn_mine_poor", "player"], ["lose_true", "player"], ["block_challenge_long", "bystander"], ["spectator_full_table", "spectator"], ["results_long_name", "bystander"]]) {
      await show(page, key, label);
      await sleep(60);
      const got = await page.evaluate((ins) => {
        const W = innerWidth, H = innerHeight, tol = 1.5, out = [];
        const flow = document.getElementById("app").dataset.dock === "flow";
        const win = document.getElementById("stage").getBoundingClientRect();
        const sel = "#app button, #opponents .seat, #caption, #reveal, #bar, #bar-note, #coins, #me-seat, #hand .card, #play .card, .toast";
        for (const e of document.querySelectorAll(sel)) {
          const cs = getComputedStyle(e);
          if (cs.display === "none" || cs.visibility === "hidden" || e.closest("[hidden], dialog:not([open])")) continue;
          const b = e.getBoundingClientRect();
          // the part that can be seen: inside the screen and, for the table, inside its window
          let r = { left: Math.max(0, b.left), right: Math.min(W, b.right), top: Math.max(0, b.top), bottom: Math.min(H, b.bottom) };
          if (!flow && e.closest("#stage")) { r.top = Math.max(r.top, win.top); r.bottom = Math.min(r.bottom, win.bottom); }
          if (r.right - r.left < 1 || r.bottom - r.top < 1) continue;
          const id = e.dataset.k || e.id || e.className.toString().slice(0, 18);
          if (r.left < ins.left - tol) out.push(`${id} left ${Math.round(r.left)} < ${ins.left}`);
          if (r.right > W - ins.right + tol) out.push(`${id} right ${Math.round(r.right)} > ${W - ins.right}`);
          if (r.top < ins.top - tol) out.push(`${id} top ${Math.round(r.top)} < ${ins.top}`);
          if (r.bottom > H - ins.bottom + tol) out.push(`${id} bottom ${Math.round(r.bottom)} > ${H - ins.bottom}`);
        }
        return out;
      }, ins);
      if (got.length) bad.push(`${key}/${label}: ${got[0]}`);
    }
    check(bad.length === 0, `${name}: with insets ${JSON.stringify(ins)} nothing is under the notch or the home bar in 5 states${bad.length ? " | " + CAPPED(bad) : ""}`);
    const m = await measure(page);
    check(m.maxOverlap <= 20 && m.docOverflowX <= 0, `${name}: ...and the layout still holds with them (worst overlap ${m.maxOverlap}px2)`);
    // the insets really reached the page, and the header, the table and the dock keep inside them
    const pads = await page.evaluate(() => {
      // what each keeps clear on its sides (margin and padding), whatever the scroll position
      const box = (id) => { const c = getComputedStyle(document.getElementById(id)); const f = (k) => parseFloat(c[k]) || 0;
        return { l: f("marginLeft") + f("paddingLeft"), r: f("marginRight") + f("paddingRight"), t: f("paddingTop"), b: f("paddingBottom") }; };
      return { head: box("head"), dock: box("dock"), table: box("table") };
    });
    check(pads.head.l >= ins.left - 1 && pads.head.r >= ins.right - 1 && pads.head.t >= ins.top - 1
      && pads.dock.l >= ins.left - 1 && pads.dock.r >= ins.right - 1 && pads.dock.b >= ins.bottom - 1
      && pads.table.l >= ins.left - 1 && pads.table.r >= ins.right - 1,
      `${name}: the header, the table and the dock keep their content inside the insets (${JSON.stringify(pads)})`);
    check(errors.length === 0, `${name}: insets: no page errors (${errors.slice(0, 2).join(" | ")})`);
    await client.detach();
    await ctx.close();
  }
}

// ---------------------------------------------------------------- 11. motion, winners, spectators
async function motion() {
  const calm = await phone(vp("390x844"), { reduced: true });
  const lively = await phone(vp("390x844"));
  const probe = async (p) => {
    await show(p, "turn_mine_rich", "player");
    await focusK(p, "bar:coup"); await p.keyboard.press("Enter"); await sleep(60);
    const aiming = await p.evaluate(() => document.getAnimations().length);
    await show(p, "turn_mine_poor", "player", { edit: (st) => { st.deadline = st.now + 3000; } });
    await sleep(500);
    const urgent = await p.evaluate(() => ({ anims: document.getAnimations().length, cls: document.getElementById("timer").className }));
    await show(p, "results", "player");
    await sleep(120);
    const confetti = await p.evaluate(() => { const cv = document.getElementById("confetti"); return cv && cv._parts ? cv._parts.length : 0; });
    const after = await p.evaluate(() => document.getAnimations().length);
    return { aiming, urgent, confetti, after };
  };
  const a = await probe(calm.page), b = await probe(lively.page);
  METRICS.misc.motion = { reduced: a, normal: b };
  check(b.aiming > 0 && b.urgent.anims > 0 && b.confetti > 0, `(control) without the setting the table animates: ${b.aiming} while aiming, ${b.urgent.anims} urgent timer, ${b.confetti} confetti pieces`);
  check(a.aiming === 0 && a.urgent.anims === 0 && a.after === 0, `reduced motion: 0 running animations while aiming (${a.aiming}), on the urgent timer (${a.urgent.anims}) and at the results (${a.after})`);
  check(/urgent/.test(a.urgent.cls) && a.confetti === 0, `reduced motion: the timer still turns urgent (${a.urgent.cls}) and there is no confetti (${a.confetti} pieces)`);
  await calm.ctx.close(); await lively.ctx.close();

  // a long winner's name keeps the crown
  const bad = [];
  for (const v of VIEWPORTS) {
    if (ONLY_VP && !ONLY_VP.test(v.name)) continue;
    const { ctx, page } = await phone(v);
    await show(page, "results_long_name", "bystander");
    const w = await page.evaluate(() => {
      const crown = document.querySelector(".winner .bart"), name = document.querySelector(".winner .wname");
      if (!crown || !name) return null;
      const c = crown.getBoundingClientRect(), n = name.getBoundingClientRect(), W = innerWidth;
      return { cw: c.width, ch: c.height, inside: c.left >= 0 && c.right <= W && n.left >= 0 && n.right <= W + 0.5, apart: c.right <= n.left + 1 || c.bottom <= n.top + 1, text: name.textContent, clipped: name.scrollWidth > name.clientWidth + 1 };
    });
    if (!w || w.cw < 24 || w.ch < 24 || !w.inside || !w.apart || w.clipped) bad.push(`${v.name}: ${JSON.stringify(w)}`);
    await ctx.close();
  }
  check(bad.length === 0, `a 14-letter winner keeps the crown (at least 24px, whole, clear of the name) at every viewport${bad.length ? " | " + CAPPED(bad) : ""}`);

  // a spectator's mini cards say what they are: as the accessibility tree sees them
  const sp = await phone(vp("390x844"));
  let unnamed = 0, minis = 0, lost = 0, sample = [];
  for (const [k, l] of [["spectator_full_table", "spectator"], ["challenge_prompt", "spectator"], ["lose_true", "spectator"], ["out_watching", "watcher"]]) {
    await show(sp.page, k, l);
    for (const n of await ax(sp.page, ".card.mini")) {
      minis++;
      if (/\(lost\)$/.test(n.name || "")) lost++;
      if (sample.length < 4) sample.push(`${n.role}:${n.name}`);
      if (n.ignored || !/^(img|image)$/.test(n.role || "") || !/^(Banker|Agent|Smuggler|Guardian|Broker)( \(lost\))?$/.test(n.name || "")) unnamed++;
    }
  }
  check(minis > 0 && unnamed === 0, `spectator mini cards all have a role and a name in the accessibility tree (${minis} cards, ${lost} lost, ${unnamed} without; e.g. ${sample.join(", ")})`);
  await sp.ctx.close();
}

// ---------------------------------------------------------------- run
try {
  await run("matrix", matrix);
  await run("reveal", reveal);
  await run("operability", operability);
  await run("focus", focus);
  await run("tabwalk", tabwalk);
  await run("live", live);
  await run("contrast", contrast);
  await run("legibility", legibility);
  await run("overlays", overlays);
  await run("drawer", drawer);
  await run("party", partySurface);
  await run("insets", insets);
  await run("motion", motion);
} finally {
  fs.writeFileSync(path.join(OUT, "layout-results.json"), JSON.stringify(results, null, 1));
  fs.writeFileSync(path.join(OUT, "layout-metrics.json"), JSON.stringify(METRICS, null, 1));
  await browser.close();
}

console.log(`\n${total} checks, ${bad ? bad + " FAILED" : "all passed"} | screenshots, layout-results.json and layout-metrics.json: ${OUT}`);
if (bad) console.log("failed:\n  - " + failures.join("\n  - "));
process.exit(bad ? 1 : 0);
