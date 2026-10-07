/* BLUFF table client. The phone is the whole game: you see the table, the other
   players' card BACKS (the server never sends their faces), your own cards as a
   real hand, and big contextual controls in the bar at the bottom.

   Presentation only (AVR-313): the table is a grid that the page scrolls where it cannot fit, every
   choice is a native button, a state that has not changed keeps its controls (and your focus), what
   the table says is also said in one live region, and what just happened is shown in the server's
   own words. Nothing here changes a rule, a message to the server or what the server sends. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};

const icon = window.BluffIcons || (() => document.createTextNode(""));
// BLUFF's own game art (art.js, Kenney Board Game Icons): roles, coins, actions, crown, log.
const art = window.BluffArt || (() => document.createTextNode(""));
// Presentation only: the server's role emoji (game.py ROLES) are not drawn; each role has its
// own art and colour, so the five read as one deck.
const ROLE_ART = { Banker: "dollar", Agent: "sword", Smuggler: "pouch_remove",
  Broker: "card_flipdouble", Guardian: "shield" };
const roleArt = (r) => ROLE_ART[r] || "hexagon_question";
const roleKey = (r) => (ROLE_ART[r] ? r.toLowerCase() : "unknown");
document.querySelectorAll("[data-art]").forEach((slot) => slot.appendChild(art(slot.dataset.art)));
const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
// A coin count reads as words to assistive tech: "3 coins".
function coinsEl(n, cls) {
  const c = el("span", cls);
  c.setAttribute("role", "img");
  c.setAttribute("aria-label", plural(n, "coin", "coins"));
  c.append(art("flip_full"), el("span", null, String(n)));
  c.lastChild.setAttribute("aria-hidden", "true");
  return c;
}
document.querySelectorAll("[data-icon]").forEach((slot) => slot.appendChild(icon(slot.dataset.icon)));

let ST = null;
let takeoverTimer = null;
let picking = null;          // action awaiting a target tap
let pickFrom = "";           // the control that started it (focus goes back there)
let sheet = null;            // "claim" when the claim menu is open
let keepSel = [], keepKey = "";
let drawerOpen = false, celebrated = false;
let stepChanged = false;     // this render is the first of a new prompt (onState sets it)
let focusReq = null;         // "targets": aiming has begun, focus the first target
// How to play (briefing.js): shown once before a new player's first Ready; ? reopens it any time.
const brief = window.BluffBriefing || null;
let briefOffered = false, briefHinted = false;
// The rules' numbers: one source (briefing.js FACTS, pinned to game.py by tests/test_bluff_briefing.py).
const FACTS = (brief && brief.FACTS) || { income: 1, aid: 2, coupCost: 7, mustCoupAt: 10, strikeCost: 3 };

// In a Party (avrana-party ADR 0011) the round's setup is the Party's own full-screen scene on
// Party Home; this page only runs the round and its results. If it is ever opened during a setup,
// it shows nothing of the table until the round starts (the Party takes the phone to the setup).
let SETUP = false;
// The Party underneath (party-follow.js): the host's controls live in this table's own chrome.
const party = () => (window.AvranaParty && window.AvranaParty.active ? window.AvranaParty : null);
document.addEventListener("avrana-party", () => { if (ST) render(); });
const conn = Hub.connect("/games/bluff/ws", {
  onSetup: (on) => { SETUP = on; $("app").hidden = on; if (!on && ST) render(); },
  onFx: (fx) => {
    if (fx.kind === "toast") Hub.toast((fx.icon ? fx.icon + " " : "") + fx.msg);
    if (fx.kind === "invalid") Hub.toast(fx.msg, "err");
  },
  onState: (st) => {
    const step = (x) => x && x.game && x.game.pending ? x.game.pending.step : null;
    if (step(ST) !== step(st)) { picking = null; pickFrom = ""; sheet = null; stepChanged = true; }
    ST = st;
    render();
    stepChanged = false;
  },
});
const send = (m) => conn.send(m);
// game answers carry the prompt step, so a late tap can never land in a newer prompt
const gsend = (m) => send(Object.assign({ step: g() && g().pending.step }, m));

$("home").onclick = () => { location.href = window.AvranaIntegration?.home || "/"; };
$("history").onclick = () => { drawerOpen = true; render(); };
$("drawer-close").onclick = () => { drawerOpen = false; render(); };
$("rules").onclick = () => brief && brief.open("reference");
// The Party Host ends a Party round for everyone from the table itself (no Party bar on top).
$("party-end").onclick = () => confirmAction({ title: "End the game for everyone?",
  body: "Everyone goes back to Party Home. This round can't be resumed.", yes: "End game" },
() => party() && party().end());
if (!brief) $("rules").hidden = true;
// The briefing's "I'm ready" is this player's Ready, while there is a lobby to be ready in.
function readyAfterBriefing() {
  if (ST && (ST.phase === "lobby" || ST.phase === "countdown") && ST.you && !ST.you.ready)
    send({ t: "ready", ready: true });
}

// ---------------------------------------------------------------- choices are buttons

// Every control that acts is built with a key (data-k); one listener reads the key and runs the
// handler registered for it in the latest render, so a control that was not rebuilt (its markup
// did not change) still does what the newest state says.
const HANDLERS = Object.create(null);
document.addEventListener("click", (e) => {
  const t = e.target.closest && e.target.closest("[data-k]");
  if (!t || t.disabled || t.getAttribute("aria-disabled") === "true") return;
  const run = HANDLERS[t.dataset.k];
  if (run && !offline()) run(e);
});
// Escape cancels aiming (and closes the claim menu); a dialog keeps its own Escape.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.defaultPrevented || document.querySelector("dialog[open]")) return;
  if (picking) { e.preventDefault(); cancelPicking(); }
  else if (sheet) { e.preventDefault(); sheet = null; render(); focusKeyed("bar:claim"); }
});
function cancelPicking() {
  const back = pickFrom;
  picking = null; pickFrom = "";
  render();
  if (!focusKeyed(back)) focusFirst("#bar .act:not([aria-disabled='true'])");
}

// Replace a region's children only when the markup is different, so a state that changes
// nothing keeps its nodes, its scroll position and the player's focus.
function swap(box, build) {
  const probe = box.cloneNode(false);
  build(probe);
  if (probe.innerHTML === box.innerHTML) return false;
  box.replaceChildren(...probe.childNodes);
  return true;
}

// ---- focus: the same logical control after a render; a new prompt takes it to its first control
const focusKey = () => {
  const a = document.activeElement;
  if (!a || a === document.body || !a.closest || !$("app").contains(a) || a.closest("#confirm, #briefing")) return null;
  return a.dataset && a.dataset.k ? a.dataset.k : (a.id ? "#" + a.id : null);
};
function focusEl(t, scroll) {
  if (!t || t.hidden || !t.getClientRects().length) return false;
  try { t.focus({ preventScroll: !scroll }); } catch (e) { return false; }
  if (scroll && t.scrollIntoView) t.scrollIntoView({ block: "nearest", inline: "nearest" });
  return document.activeElement === t;
}
function focusKeyed(k, scroll) {
  if (!k) return false;
  return focusEl(k[0] === "#" ? $(k.slice(1)) : document.querySelector('[data-k="' + CSS.escape(k) + '"]'), scroll);
}
const focusFirst = (sel, scroll) => focusEl(document.querySelector(sel), scroll);
// where a prompt begins: its first control, in reading order
function focusPrompt() {
  const G = g(), me = G && G.me;
  if (picking) return focusFirst("#opponents button.seat", true);
  if (!me || me.left) return false;
  const kind = me.prompt && me.prompt.kind;
  if (kind === "lose") return focusFirst("#hand button.card", true);
  if (kind === "exchange") return focusFirst("#sheet button.card", true);
  return focusFirst("#bar .act:not([aria-disabled='true'])", true);
}
function settleFocus(keep) {
  if (document.querySelector("dialog[open]")) return;
  if (focusReq === "targets" || (stepChanged && wantsPrompt())) { focusReq = null; if (focusPrompt()) return; }
  focusReq = null;
  const now = focusKey();
  if (now === keep && now) return;
  if (!keep) return;
  if (focusKeyed(keep)) return;
  // the control is gone (a move was made, the prompt moved on): the nearest place it was
  if (/^(bar|claim|xc):/.test(keep) && focusFirst("#bar .act:not([aria-disabled='true'])")) return;
  if (/^hand:/.test(keep) && focusFirst("#bar .act:not([aria-disabled='true'])")) return;
  if (/^seat:/.test(keep) && focusFirst("#bar .act:not([aria-disabled='true'])")) return;
  const bar = $("bar");
  bar.tabIndex = -1;
  if (!focusEl(bar)) focusEl($("history"));
}
// a prompt is waiting on me: an answer, or my own turn
function wantsPrompt() {
  const G = g(), me = G && G.me;
  return !!(me && !me.left && (me.prompt || (me.actions || []).length));
}

// Opponent seats: [grid-column, grid-row, side?] by the number of opponents, listed clockwise
// from your left (MAX_SEATS is 6, so at most 5 opponents; a full table's spectator sees 6).
// Row 1 is the far side of the table; row 2 holds the side seats and the centre.
const SLOTS = {
  1: [["1 / -1", 1]],
  2: [["1 / span 6", 1], ["7 / span 6", 1]],
  3: [["1 / span 3", 2, 1], ["4 / span 6", 1], ["10 / span 3", 2, 1]],
  4: [["1 / span 3", 2, 1], ["3 / span 4", 1], ["7 / span 4", 1], ["10 / span 3", 2, 1]],
  5: [["1 / span 3", 2, 1], ["1 / span 4", 1], ["5 / span 4", 1], ["9 / span 4", 1], ["10 / span 3", 2, 1]],
  6: [["1 / span 3", 2, 1], ["1 / span 3", 1], ["4 / span 3", 1], ["7 / span 3", 1], ["10 / span 3", 1], ["10 / span 3", 2, 1]],
};
const slotOf = (n, i) => (SLOTS[Math.min(Math.max(n, 1), 6)] || SLOTS[1])[i] || SLOTS[1][0];
function placeSeat(seat, n, i) {
  const [col, row, side] = slotOf(n, i);
  seat.style.setProperty("--seat-col", col);
  seat.style.setProperty("--seat-row", String(row));
  if (side) seat.dataset.side = "1";
}
function sizeTable(n) {
  const table = $("table");
  table.dataset.n = String(n);
  table.classList.toggle("compact", n >= 3);
}

// ---------------------------------------------------------------- fit: header, table, dock
// The header and the dock keep their natural size; the table takes what is left and scrolls. If
// that is too little (a zoomed page, a large text size), the whole page scrolls instead (flow).
let fitQueued = false;
function syncHeight() {
  const h = Math.round(window.innerHeight);
  $("app").style.height = h + "px";
}
function fit() {
  const app = $("app");
  if (app.hidden) return;
  const root = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const H = app.clientHeight || Math.round(window.innerHeight);
  const headH = $("head").offsetHeight, dockH = $("dock").offsetHeight;
  const room = H - headH - dockH;
  const flow = app.dataset.dock === "flow";
  const need = 11 * root;
  const mode = (flow ? room < need + 24 : room < need) ? "flow" : "pinned";
  app.dataset.dock = mode;
  app.style.setProperty("--app-h", H + "px");
  app.style.setProperty("--head-h", headH + "px");
  app.style.setProperty("--dock-h", dockH + "px");
  app.style.setProperty("--room", Math.max(room, 240) + "px");
  // the felt's lower edge crosses the top of the hand, as it always has
  const hand = $("hand"), a = app.getBoundingClientRect(), h = hand.getBoundingClientRect();
  app.style.setProperty("--felt-b", Math.max(0, Math.round(a.bottom - (h.top + h.height * .4))) + "px");
}
function fitSoon() {
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fit(); });
}
syncHeight();
window.addEventListener("resize", () => { syncHeight(); fitSoon(); if (ST) render(); });
if (typeof ResizeObserver === "function") {
  const ro = new ResizeObserver(fitSoon);
  ro.observe($("dock")); ro.observe($("head")); ro.observe($("app"));
}

// ---------------------------------------------------------------- helpers

const playerOf = (pid) => (ST.players || []).find((p) => p.pid === pid) || {};
const g = () => ST && ST.game;
const seatOf = (pid) => g() && g().seats.find((s) => s.pid === pid);
const isMe = (pid) => !!(pid && g() && g().me && g().me.pid === pid);
const nameOf = (pid) => (isMe(pid) ? "You" : (seatOf(pid) || playerOf(pid)).name || "?");
const role = (r) => (g() ? g().roles[r] : null) || { icon: "", text: "" };

function avatarEl(pid, size) {
  const p = playerOf(pid), a = el("span", "avatar");
  a.style.setProperty("--col", p.color || "#2d3a8c");
  if (size) { a.style.width = a.style.height = size + "px"; a.style.fontSize = size * 0.58 + "px"; }
  if (p.pfp) { const img = el("img"); img.src = p.pfp; img.alt = ""; a.appendChild(img); }
  else if (p.bot) a.appendChild(icon("bot"));
  else a.textContent = p.avatar || "🙂";      // a player's own chosen character (identity)
  return a;
}

// A card: its role's art and name. `mini` cards (an opponent's hand in a spectator's view, lost
// cards) carry their name as a label; a card you can choose is a button.
function cardFace(r, extra, button) {
  const mini = /(^|\s)mini(\s|$)/.test(extra || "");
  const c = el(button ? "button" : mini ? "span" : "div", "card role-" + roleKey(r) + (extra ? " " + extra : ""));
  if (button) c.type = "button";
  const idx = el("span", "idx"); idx.appendChild(art(roleArt(r))); c.appendChild(idx);
  const big = el("span", "big"); big.appendChild(art(roleArt(r))); c.appendChild(big);
  c.appendChild(el("span", "nm", r));
  if (mini) {
    c.setAttribute("role", "img");
    c.setAttribute("aria-label", /(^|\s)dead(\s|$)/.test(extra) ? r + " (lost)" : r);
  }
  return c;
}
const backCard = () => { const b = el("span", "back mini"); b.setAttribute("role", "img"); b.setAttribute("aria-label", "Face-down card"); return b; };

// ic: a Lucide name for table controls (play, x, check, ...) or "art:<name>" for BLUFF's
// own game art (roles, coins, the coup, a claim, a challenge). `k` keys it for focus and clicks;
// a control that is off stays a button (aria-disabled) so it can still say why.
const LUCIDE = new Set(["play", "x", "check", "hand", "log-out", "circle-stop", "circle-help", "house"]);
function actBtn(ic, label, onclick, cls, disabled, k, describedby) {
  const b = el("button", "act " + (cls || ""));
  b.type = "button";
  const slot = el("span", "ic");
  if (LUCIDE.has(ic)) slot.appendChild(icon(ic));
  else if (ic.startsWith("art:")) slot.appendChild(art(ic.slice(4)));
  else slot.textContent = ic;
  b.appendChild(slot);
  b.appendChild(el("span", null, label));
  if (k) {
    b.dataset.k = k;
    if (onclick && !disabled) HANDLERS[k] = onclick; else delete HANDLERS[k];
  }
  if (disabled) b.setAttribute("aria-disabled", "true");
  if (describedby) b.setAttribute("aria-describedby", describedby);
  return b;
}

// ---------------------------------------------------------------- timer

setInterval(() => {
  drawerCall();
  const t = $("timer");
  if (!ST || !ST.deadline || !g() || ST.phase !== "playing") { t.hidden = true; return; }
  const left = Math.max(0, Math.ceil((ST.deadline - conn.now()) / 1000));
  t.hidden = false;
  const show = (name, text) => {
    if (t.dataset.icon !== name) { t.dataset.icon = name; t.replaceChildren(icon(name), el("span")); }
    t.lastChild.textContent = text;
  };
  if (g().paused) {
    show("pause", Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0"));
    t.classList.remove("urgent");
    return;
  }
  show("timer", String(left));
  t.classList.toggle("urgent", left <= 5);
}, 250);

// ---------------------------------------------------------------- render

function render() {
  if (SETUP || !ST) return;
  const keep = focusKey();
  paint();
  fit();
  // a new step: the end of the table, where the story and the question are, is in view
  if (stepChanged) { const sc = $("app").dataset.dock === "flow" ? $("app") : $("stage"); sc.scrollTop = sc.scrollHeight; }
  settleFocus(keep);
  announce();
}

function paint() {
  const st = ST;
  const P = party();
  $("party-end").hidden = !(P && st.party_round && st.phase === "playing" && P.isHost());
  const inLobby = st.phase === "lobby" || st.phase === "countdown";
  briefing(st, inLobby);
  $("piles").classList.toggle("hide", inLobby);
  if (inLobby) {
    picking = null; sheet = null; celebrated = false;
    renderLobby(st);
    renderDrawer();
    syncDrawer();
    return;
  }
  $("play").classList.remove("lobby");
  if (!g()) { syncDrawer(); return; }
  renderOpponents();
  renderCenter();
  renderMe();
  renderBar();
  renderDrawer();
  syncDrawer();
  if (g().winner && !celebrated) {
    celebrated = true;
    const calm = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!calm && g().me && g().winner === g().me.pid) Hub.confettiBurst(140);
  }
}

// First play: open the briefing once per page load for a seated lobby player who has never
// acknowledged it (a reload before acknowledging shows it again). A game already running is
// never covered by it (a reconnect, a watcher): a toast points at ? instead. While the rules
// are open, a line says when the table is waiting on this player.
function briefing(st, inLobby) {
  if (!brief) return;
  const me = !inLobby && st.game && st.game.me;
  brief.status(me && !me.left && (me.prompt || (me.actions || []).length)
    ? (me.prompt ? "Your call is waiting: close to answer." : "It's your turn: close to play.") : "");
  if (brief.acknowledged()) return;
  if (inLobby && st.you && !st.you.ready && !briefOffered) {
    briefOffered = true;
    brief.open("first", readyAfterBriefing);
  } else if (!inLobby && !briefHinted && !brief.isOpen()) {
    briefHinted = true;
    Hub.toast("New to BLUFF? Tap ? for how to play");
  }
}

function orderedOpponents() {
  const seats = g().seats, me = g().me;
  if (!me) return seats;
  const i = seats.findIndex((s) => s.pid === me.pid);
  return seats.slice(i + 1).concat(seats.slice(0, i));
}

// What a seat is, in words: its name, coins and cards, and what it is doing
function seatLabel(s, waiting) {
  const bits = [s.name, plural(s.coins, "coin", "coins")];
  if (!s.alive) bits.push("out of the game");
  else if (s.cards) bits.push("holds " + s.cards.join(" and "));
  else bits.push(plural(s.influence, "card", "cards"));
  if (s.turn) bits.push("their turn");
  if (waiting) bits.push("deciding");
  if (s.alive && s.presence && s.presence !== "here") bits.push({ reconnecting: "reconnecting", away: "away", left: "left" }[s.presence] || s.presence);
  return bits.join(", ");
}

function renderOpponents() {
  const box = $("opponents");
  const opp = orderedOpponents();
  sizeTable(opp.length);
  const waiting = new Set(g().pending.waiting || []);
  const targets = targetsFor(picking);
  swap(box, (probe) => opp.forEach((s, i) => {
    const aim = targets.has(s.pid);
    const seat = el(aim ? "button" : "div", "seat" + (s.turn ? " turn" : "") + (s.alive ? "" : " out") + (aim ? " targetable" : ""));
    placeSeat(seat, opp.length, i);
    if (aim) {
      seat.type = "button";
      seat.dataset.k = "seat:" + s.pid;
      seat.setAttribute("aria-label", `Target ${s.name}, ${plural(s.coins, "coin", "coins")}`);
      HANDLERS["seat:" + s.pid] = () => {
        const a = picking; picking = null; pickFrom = "";
        gsend({ t: "act", action: a, target: s.pid });
      };
    } else {
      seat.setAttribute("role", "img");
      seat.setAttribute("aria-label", seatLabel(s, waiting.has(s.pid)));
    }
    const av = avatarEl(s.pid);
    if (waiting.has(s.pid)) av.appendChild(el("span", "bubble", "…"));
    if (g().winner === s.pid) { const cr = el("span", "crown"); cr.appendChild(art("crown_a", "Winner")); av.appendChild(cr); }
    seat.appendChild(av);
    seat.appendChild(el("span", "nm", s.name));
    const pres = { reconnecting: "reconnecting…", away: "away", left: "left" }[s.presence];
    if (pres && s.alive) seat.appendChild(el("span", "presence " + s.presence, pres));
    if (!s.alive) seat.appendChild(el("span", "presence out", "out"));
    const info = el("span", "info"), cards = el("span", "cards");
    // a Party spectator's view shows every hand (AVR-129); players only ever get backs
    if (s.cards) for (const r of s.cards) cards.appendChild(cardFace(r, "mini"));
    else for (let k = 0; k < s.influence; k++) cards.appendChild(backCard());
    for (const r of s.revealed) cards.appendChild(cardFace(r, "mini dead"));
    info.appendChild(cards);
    info.appendChild(coinsEl(s.coins, "chip coins-chip"));
    seat.appendChild(info);
    probe.appendChild(seat);
  }));
}

function targetsFor(action) {
  if (!action || !g().me) return new Set();
  const a = (g().me.actions || []).find((x) => x.action === action);
  return new Set(a && a.targets ? a.targets : []);
}

// ---- what just happened, from the public log -------------------------------------------------
// The log is a run of short stories: an action opens one, the lines after it say what became of it.
// These markers open one (tests/test_bluff_story.py pins them to what game.py writes). The table
// shows the latest story, line for line as the server wrote it, until the next action opens another.
const OPENERS = [" takes Income (", " launches a Coup", " asks for Foreign Aid (", " claims ", "Game on: "];
const isOpener = (line) => OPENERS.some((m) => line.includes(m));
function story() {
  const log = (g() && g().log) || [];
  let i = log.length - 1;
  while (i >= 0 && !isOpener(log[i])) i--;
  if (i < 0) return { lines: [], role: null, block: false };
  if (i > 0 && log[i - 1].startsWith("⏱")) i--;          // "took too long" leads into the move it forced
  const lines = log.slice(i), names = Object.keys(g().roles || {});
  let rl = null, block = false;
  for (const line of lines) {                                  // the last claim made (a block is a claim too)
    let m = line.match(/ blocks, claiming \S+ ([A-Za-z]+)\./);
    if (m && names.includes(m[1])) { rl = m[1]; block = true; continue; }
    m = line.match(/ claims \S+ ([A-Za-z]+) to /);
    if (m && names.includes(m[1])) { rl = m[1]; block = false; }
  }
  return { lines, role: rl, block };
}

function renderCenter() {
  const p = g().pending, play = $("play"), cap = $("caption");
  $("deck-n").textContent = g().deck_count;
  const sty = story();
  let text = "", face = null, kind = "claimed";
  const actor = nameOf(p.actor), tgt = p.target ? " → " + nameOf(p.target) : "";
  if (p.stage === "turn") {
    text = p.actor === (g().me && g().me.pid) ? "Your turn" : `${actor}'s turn`;
    if (sty.role) { face = sty.role; kind = "claimed past" + (sty.block ? " block" : ""); }
  } else if (p.stage === "challenge") {
    face = p.claim_role;
    text = `${actor} claim${isMe(p.actor) ? "" : "s"} ${p.claim_role}: ${p.label}${tgt}`;
  } else if (p.stage === "block") {
    face = p.claim_role || null;
    text = p.action === "aid" ? `${actor} wants Foreign Aid (+2)` : `${actor}: ${p.label}${tgt}`;
  } else if (p.stage === "block_challenge") {
    face = p.block_role; kind = "claimed block";
    text = `${nameOf(p.blocker)} block${isMe(p.blocker) ? "" : "s"} with ${p.block_role}`;
  } else if (p.stage === "lose") {
    if (sty.role) { face = sty.role; kind = "claimed" + (sty.block ? " block" : ""); }
    text = `${nameOf(p.loser)} must give up a card`;
  } else if (p.stage === "exchange") {
    text = `${actor} ${isMe(p.actor) ? "are" : "is"} exchanging cards`;
  }
  if (picking) text = "Tap a glowing player to target them";
  if (g().paused) text = "Game paused: everyone stepped away. It ends unless someone returns.";
  // the story is shown in every stage where it adds to the caption: always when something was
  // resolved (a loss, a block under challenge, the next turn, the end); while a claim or a block
  // is waiting only if more than the claim itself has happened (a challenge already held).
  const quiet = p.stage === "challenge" || p.stage === "block" || p.stage === "exchange";
  const lines = quiet && sty.lines.length < 2 ? [] : sty.lines;
  swap(play, (probe) => {
    if (p.stage === "over") {
      const win = el("div", "winner");
      if (g().winner) win.append(art("crown_a"), el("span", "wname", `${nameOf(g().winner)} ${isMe(g().winner) ? "win" : "wins"}!`));
      else win.textContent = "Game over";
      probe.appendChild(win);
    } else if (face) probe.appendChild(cardFace(face, kind));
  });
  swap($("reveal"), (probe) => lines.forEach((l) => probe.appendChild(el("li", null, l))));
  if (lines.length) $("table").dataset.story = "1"; else delete $("table").dataset.story;
  // a decision waiting on me: say so in gold, and say what the question is
  const q = callQuestion(p);
  cap.classList.toggle("call", !!q);
  swap(cap, (probe) => {
    if (text) probe.appendChild(document.createTextNode(text));
    if (q) probe.appendChild(el("span", "q", q));
  });
}

// The question behind my current prompt, spelled out (claim and block are two
// separate windows: a Steal/Strike target first answers the claim, then may block).
function callQuestion(p) {
  const pr = g().me && g().me.prompt;
  if (!pr) return "";
  const mine = p.target && p.target === g().me.pid;
  if (pr.kind === "challenge" && p.stage === "challenge")
    return "Your call: challenge or pass?" + (mine && p.action !== "exchange" ? " (block comes next)" : "");
  if (pr.kind === "challenge") return "Your call: challenge the block?";
  if (pr.kind === "block")
    return (p.action === "aid" ? "" : "Claim stands. ") + `Block (as ${pr.roles.join(" / ")}) or allow?`;
  if (pr.kind === "lose") return "Your call: tap a card to give up";
  if (pr.kind === "exchange") return `Your call: keep ${pr.keep}`;
  return "";
}

function renderMe() {
  const me = g().me, seatBox = $("me-seat"), hand = $("hand"), lost = $("lost"), coins = $("coins");
  if (!me) {
    coins.hidden = true;
    swap(seatBox, () => {}); swap(hand, () => {}); swap(lost, () => {});
    return;
  }
  const s = seatOf(me.pid);
  seatBox.className = s && s.turn ? "turn" : "";
  swap(seatBox, (probe) => {
    const av = avatarEl(me.pid, 50);
    if ((g().pending.waiting || []).includes(me.pid)) av.appendChild(el("span", "bubble", "!"));
    if (g().winner === me.pid) { const cr = el("span", "crown"); cr.appendChild(art("crown_a", "Winner")); av.appendChild(cr); }
    probe.appendChild(av);
  });
  coins.hidden = false;
  swap(coins, (probe) => probe.appendChild(coinsEl(s ? s.coins : 0, "coins-in")));
  const choosing = !!(me.prompt && me.prompt.kind === "lose");
  hand.className = choosing ? "choosing" : "";
  swap(hand, (probe) => {
    me.cards.forEach((r, i) => {
      const c = cardFace(r, "", choosing);
      if (choosing) {
        c.dataset.k = "hand:" + i;
        c.setAttribute("aria-label", "Give up " + r);
        HANDLERS["hand:" + i] = () => gsend({ t: "lose", card: i });
      }
      probe.appendChild(c);
    });
    if (!me.cards.length) probe.appendChild(el("div", "chip", "You're out: watching the rest"));
  });
  swap(lost, (probe) => { for (const r of s ? s.revealed : []) probe.appendChild(cardFace(r, "mini dead")); });
}

// ---------------------------------------------------------------- the bar

function renderBar() {
  const bar = $("bar"), me = g().me;
  bar.classList.toggle("call", !!(me && me.prompt));
  let out = { note: "", sheet: null };
  swap(bar, (box) => { out = fillBar(box) || out; });
  const note = $("bar-note");
  note.textContent = out.note;
  note.hidden = !out.note;
  renderSheet(out.sheet, out.acts, out.choose, out.pr);
}

// What the bar offers now, built into `bar`. Returns the sentence that explains an unavailable
// move, and the sheet (if any) that goes with it.
function fillBar(bar) {
  const me = g().me, p = g().pending;
  const msg = (t) => bar.appendChild(el("div", "bar-msg", t));
  if (p.stage === "over") {
    const P = party();
    if (!(ST.party_round && P)) { msg("Back to the lobby in a moment…"); return; }
    // A Party round's results stay until the Party Host moves everyone on (ADR 0011).
    if (P.isHost()) {
      bar.appendChild(actBtn("play", "Play again", () => P.playAgain(), "primary", false, "bar:play-again"));
      bar.appendChild(actBtn("house", "Party Home", () => P.goHome(), "", false, "bar:party-home"));
    } else msg(`Waiting for ${P.hostName() || "the host"} to choose what's next`);
    return;
  }
  if (!me) {
    if (g().paused) {                      // an empty table: a newcomer may start fresh
      const wait = Math.ceil(((g().takeover_at || 0) - conn.now()) / 1000);
      if (wait > 0) {
        msg(`Table empty: you can start a new game in ${wait} s`);
        clearTimeout(takeoverTimer);
        takeoverTimer = setTimeout(render, 1000);
      }
      else bar.appendChild(actBtn("play", "Start a new game", () => send({ t: "end_game" }), "primary", false, "bar:new-game"));
      return;
    }
    msg(ST.spectator ? "Watching this round: you see every hand" : "Watching");
    return;
  }
  if (me.left) { msg("You left this game: watching"); return; }

  const acts = me.actions || [];
  if (acts.length) {
    if (picking) {
      const pa = (acts.find((x) => x.action === picking) || {}).label || "";
      msg(`${pa}: tap a glowing player`);
      bar.appendChild(actBtn("x", "Cancel", () => cancelPicking(), "", false, "bar:cancel"));
      return;
    }
    const by = Object.fromEntries(acts.map((a) => [a.action, a]));
    const choose = (a, from) => () => {
      sheet = null;
      if (a.targets) { picking = a.action; pickFrom = from; focusReq = "targets"; render(); }
      else gsend({ t: "act", action: a.action });
    };
    if (acts.length === 1 && by.coup) {
      const rich = seatOf(me.pid);
      msg(`You have ${plural(rich ? rich.coins : 0, "coin", "coins")}: at ${FACTS.mustCoupAt} or more you must Coup.`);
      bar.appendChild(actBtn("art:exploding", "Coup", choose(by.coup, "bar:coup"), "danger", false, "bar:coup"));
      return;
    }
    const mine = seatOf(me.pid), coins = mine ? mine.coins : 0;
    bar.appendChild(actBtn("art:token_add", `Income +${FACTS.income}`, choose(by.income, "bar:income"), "primary", !by.income, "bar:income"));
    bar.appendChild(actBtn("art:hand_token", `Foreign Aid +${FACTS.aid}`, choose(by.aid, "bar:aid"), "", !by.aid, "bar:aid"));
    bar.appendChild(actBtn("art:exploding", `Coup (${FACTS.coupCost})`, by.coup ? choose(by.coup, "bar:coup") : null, "danger", !by.coup, "bar:coup",
      by.coup ? "" : "bar-note"));
    bar.appendChild(actBtn("art:hand_card", "Claim", () => { sheet = sheet ? null : "claim"; render(); focusKeyed("bar:claim"); }, "blue", false, "bar:claim"));
    return { note: by.coup ? "" : `Coup needs ${FACTS.coupCost} coins, you have ${coins}.`,
      sheet: sheet === "claim" ? "claim" : null, acts, choose: (a) => choose(a, "bar:claim") };
  }
  sheet = null;
  const pr = me.prompt;
  if (pr && pr.kind === "challenge") {
    // "Challenge" is set in capitals by table.css (not at 200 % text, where the word is wider than the bar)
    bar.appendChild(actBtn("art:hand_cross", "Challenge", () => gsend({ t: "respond", choice: "challenge" }), "danger", false, "bar:challenge"));
    bar.appendChild(actBtn("art:flip_head", "Pass", () => gsend({ t: "respond", choice: "pass" }), "", false, "bar:pass"));
  } else if (pr && pr.kind === "block") {
    for (const r of pr.roles)
      bar.appendChild(actBtn("art:" + roleArt(r), "Block as " + r, () => gsend({ t: "respond", choice: "block", role: r }), "blue role-" + roleKey(r), false, "bar:block:" + r));
    bar.appendChild(actBtn("art:flip_head", "Allow", () => gsend({ t: "respond", choice: "allow" }), "", false, "bar:allow"));
  } else if (pr && pr.kind === "lose") {
    msg("Tap one of your cards to give it up");
  } else if (pr && pr.kind === "exchange") {
    const short = keepSel.length !== pr.keep;
    const ok = actBtn("check", `Keep ${keepSel.length}/${pr.keep}`, () => gsend({ t: "keep", cards: keepSel }), "primary", short, "bar:keep", short ? "bar-note" : "");
    bar.appendChild(ok);
    return { note: short ? `Pick ${pr.keep} cards to keep: ${keepSel.length} picked so far.` : "", sheet: "exchange", pr };
  } else {
    const w = (p.waiting || []).map(nameOf);
    msg(p.stage === "turn" ? `Waiting for ${nameOf(p.actor)}…` : w.length ? `Waiting for ${w.join(", ")}…` : "…");
  }
}

function renderSheet(kind, acts, choose, pr) {
  const sh = $("sheet");
  if (kind === "claim") renderClaimSheet(acts, choose);
  else if (kind === "exchange") renderExchangeSheet(pr);
  else { sh.hidden = true; if (sh.firstChild) sh.replaceChildren(); }
}

function renderClaimSheet(acts, choose) {
  const sh = $("sheet");
  sh.hidden = false;
  const me = g().me, mine = seatOf(me.pid), coins = mine ? mine.coins : 0;
  swap(sh, (probe) => {
    probe.appendChild(el("h3", null, "CLAIM A ROLE (you don't need to hold it)"));
    const grid = el("div", "sheet-grid");
    for (const a of acts.filter((x) => x.claims)) {
      grid.appendChild(actBtn("art:" + roleArt(a.claims), `${a.claims}\n${a.label}`, choose(a), "blue role-" + roleKey(a.claims), false, "claim:" + a.action));
    }
    if (!grid.childElementCount) grid.appendChild(el("div", "bar-msg", "No role actions available"));
    probe.appendChild(grid);
    // a move that is not on offer says so, with the numbers (Strike costs coins to claim)
    if (!acts.some((x) => x.action === "strike") && coins < FACTS.strikeCost)
      probe.appendChild(el("p", "sheet-note", `Strike needs ${FACTS.strikeCost} coins, you have ${coins}.`));
  });
}

function renderExchangeSheet(pr) {
  const key = pr.pool.join(",");
  if (key !== keepKey) { keepKey = key; keepSel = []; }
  const sh = $("sheet");
  sh.hidden = false;
  swap(sh, (probe) => {
    probe.appendChild(el("h3", "caps", `Exchange: keep ${pr.keep}`));
    const row = el("div", "sheet-cards");
    pr.pool.forEach((r, i) => {
      const on = keepSel.includes(i);
      const c = cardFace(r, on ? "sel" : "", true);
      c.dataset.k = "xc:" + i;
      c.setAttribute("aria-pressed", on ? "true" : "false");
      c.setAttribute("aria-label", "Keep " + r);
      HANDLERS["xc:" + i] = () => {
        keepSel = keepSel.includes(i) ? keepSel.filter((x) => x !== i)
          : keepSel.length < pr.keep ? keepSel.concat(i) : keepSel;
        render();
      };
      row.appendChild(c);
    });
    probe.appendChild(row);
  });
}

// ---------------------------------------------------------------- drawer

// The server's log lines start with a marker glyph (game.py); draw BLUFF art instead and
// keep the words. Unknown lines are shown as sent.
const LOG_MARKS = [["\u{1F3F3}", "flag_square"], ["\u{1F3C6}", "award"], ["☠", "skull"], ["⏱", "hourglass"]];
function logLine(line) {
  const li = el("li");
  const hit = LOG_MARKS.find(([mark]) => line.startsWith(mark));
  if (!hit) { li.textContent = line; return li; }
  li.className = "marked";
  li.append(art(hit[1]), line.slice(hit[0].length).replace(/^️/, "").trim());
  return li;
}

// The rules in one line, from the single rules source (briefing.js FACTS): never typed here
const rulesLine = () => `Anyone: Income +${FACTS.income} · Foreign Aid +${FACTS.aid} (blockable) · Coup: pay ${FACTS.coupCost} (must at ${FACTS.mustCoupAt}+).`;

// The history drawer is a modal dialog, like #confirm: focus goes in and stays there, Escape
// closes it, focus comes back to the button that opened it, and the table behind is inert.
const drawer = $("drawer");
function syncDrawer() {
  if (drawerOpen && !drawer.open) {
    if (typeof drawer.showModal === "function") drawer.showModal(); else drawer.setAttribute("open", "");
  } else if (!drawerOpen && drawer.open) {
    if (typeof drawer.close === "function") drawer.close(); else drawer.removeAttribute("open");
  }
}
drawer.addEventListener("close", () => {
  drawerOpen = false;
  drawerCall();
  if (!document.activeElement || document.activeElement === document.body) $("history").focus();
});
// While a prompt's timer runs, the drawer says the call is waiting (and for how long). It is part
// of the dialog's description, not a live region: a countdown that is read out every second would
// drown the page; the one polite region stays the table's own.
function drawerCall() {
  const box = $("drawer-call");
  if (!drawerOpen || !ST || !g()) { box.hidden = true; drawer.removeAttribute("aria-describedby"); return; }
  const me = g().me;
  const waiting = me && !me.left && ST.phase === "playing" && ST.deadline && !g().paused && !g().winner
    && (me.prompt || (me.actions || []).length);
  if (!waiting) { box.hidden = true; drawer.removeAttribute("aria-describedby"); return; }
  const left = Math.max(0, Math.ceil((ST.deadline - conn.now()) / 1000));
  const text = me.prompt ? `Your call is waiting: ${left} s left. Close to answer.` : `It's your turn: ${left} s left. Close to play.`;
  if (box.hidden) { drawer.setAttribute("aria-describedby", "drawer-call"); box.hidden = false; }
  if (box.textContent !== text) box.textContent = text;
}

function renderDrawer() {
  if (!drawerOpen) return;
  let box = $("drawer-actions");
  if (!box) { box = el("div"); box.id = "drawer-actions"; $("log").before(box); }
  const G = g(), me = G && G.me;
  swap(box, (probe) => {
    if (me && !me.left && me.cards.length && !G.winner) {
      probe.appendChild(actBtn("log-out", "Leave game", () => confirmAction({
        title: "Leave this game?",
        body: "Your seat plays on autopilot and you're out at the next turn. You'll watch the rest.",
        yes: "Leave game",
      }, () => send({ t: "leave_game" })), "", false, "drawer:leave"));
    }
    // In a Party round only the Party Host ends the game (their End beside ?; ADR 0011)
    if (me && G && !G.winner && !ST.party_round) {
      probe.appendChild(actBtn("circle-stop", "End game", () => confirmAction({
        title: "End the game?",
        body: "Everyone goes back to the lobby. This only works when nobody else is still playing.",
        yes: "End game",
      }, () => send({ t: "end_game" })), "", false, "drawer:end"));
    }
  });
  swap($("log"), (probe) => {
    if (!G) { probe.appendChild(el("li", null, "Nothing has happened yet.")); return; }
    for (const line of G.log.slice().reverse()) probe.appendChild(logLine(line));
  });
  swap($("rolehelp"), (probe) => {
    if (!G) return;
    for (const [r, v] of Object.entries(G.roles)) {
      const row = el("div", "role-row role-" + roleKey(r));
      const words = el("span"); words.append(el("b", null, r), ": " + v.text);
      row.append(art(roleArt(r)), words);
      probe.appendChild(row);
    }
    probe.appendChild(el("div", null, rulesLine()));
  });
  drawerCall();
}

// A consequential action asks first, in the table's own dialog (the message sent is unchanged).
function confirmAction({ title, body, yes }, run) {
  const d = $("confirm");
  if (typeof d.showModal !== "function") { if (window.confirm(title + " " + body)) run(); return; }
  $("confirm-title").textContent = title;
  $("confirm-body").textContent = body;
  $("confirm-yes").textContent = yes;
  d.returnValue = "";
  d.onclose = () => { if (d.returnValue === "yes") run(); };
  d.showModal();
}

// ---------------------------------------------------------------- the connection, in the dock
// hubnet.js owns the reconnect line and the toasts. Here the line sits in the dock above the
// moves, in sentence case, and the moves are dimmed and ignored while the table is out of reach.
const banner = $("conn-banner");
const offline = () => !!(banner && !banner.hidden);
if (banner) {
  $("dock").insertBefore(banner, $("bar"));
  const SENTENCES = { "RECONNECTING…": "Reconnecting…", "CAN'T REACH THE PARTY — CHECK WI-FI": "Can't reach the Party. Check your Wi-Fi." };
  const tidy = () => {
    const t = banner.textContent, s = SENTENCES[t] || (t === t.toUpperCase() && /[A-Z]/.test(t) ? t.charAt(0) + t.slice(1).toLowerCase() : t);
    if (t !== s) banner.textContent = s;
    const bar = $("bar");
    if (banner.hidden) bar.removeAttribute("aria-disabled"); else bar.setAttribute("aria-disabled", "true");
  };
  new MutationObserver(tidy).observe(banner, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
  tidy();
}

// ---------------------------------------------------------------- live region
// One polite region says what the table says: what just happened (the server's public log lines),
// whose turn it is, what a player is deciding. A prompt that is on a timer goes to the assertive one.
// Only public things go in: never a hand, never a pool of cards to exchange.
let heard = "", heardLog = null;
const sayIn = (id, text) => { const box = $(id); if (box.textContent !== text) box.textContent = text; };
function newLines(prev, cur) {
  for (let k = Math.min(prev.length, cur.length); k > 0; k--) {
    let same = true;
    for (let j = 0; j < k && same; j++) same = prev[prev.length - k + j] === cur[j];
    if (same) return cur.slice(k);
  }
  return cur.slice();
}
function announce() {
  const G = g();
  if (!ST || !G || ST.phase === "lobby" || ST.phase === "countdown") { heardLog = null; return; }
  const p = G.pending, me = G.me;
  const key = [p.step, p.stage, G.log.length, G.winner, G.paused, me && me.prompt && me.prompt.kind].join("|");
  if (key === heard) return;
  heard = key;
  const fresh = heardLog ? newLines(heardLog, G.log) : [];
  heardLog = G.log.slice();
  const parts = fresh.slice();
  let urgent = "";
  const q = callQuestion(p);
  if (p.stage === "over") parts.push(G.winner ? `${nameOf(G.winner)} ${isMe(G.winner) ? "win" : "wins"}!` : "Game over.");
  else if (G.paused) parts.push("Game paused: everyone stepped away.");
  else if (q) { if (ST.deadline) urgent = q; else parts.push(q); }
  else if (p.stage === "turn") parts.push(p.actor === (me && me.pid) ? "Your turn." : `${nameOf(p.actor)}'s turn.`);
  else if (p.stage === "lose") parts.push(`${nameOf(p.loser)} must give up a card.`);
  else if (p.stage === "exchange") parts.push(`${nameOf(p.actor)} ${isMe(p.actor) ? "are" : "is"} exchanging cards.`);
  // a prompt on a timer interrupts, so it says the news that led to it in the same breath
  if (urgent) { urgent = parts.concat(urgent).join(" "); parts.length = 0; }
  sayIn("live", parts.join(" "));
  sayIn("live-urgent", urgent);
}
// toasts (hubnet.js) are public notices: say them too, in the same region
function say(text) { if (text) sayIn("live", text); }
(() => {
  const hear = (n) => { if (n.classList && n.classList.contains("toast")) say(n.textContent); };
  const watch = (holder) => {
    if (holder._said) return;
    holder._said = true;
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach(hear))).observe(holder, { childList: true });
    // hubnet.js makes the holder together with the page's first toast: that one is already in it
    [...holder.children].forEach(hear);
  };
  const existing = document.getElementById("toasts");
  if (existing) watch(existing);
  new MutationObserver(() => { const h = document.getElementById("toasts"); if (h) watch(h); })
    .observe(document.body, { childList: true });
})();

// ---------------------------------------------------------------- lobby

function renderLobby(st) {
  swap($("hand"), () => {}); swap($("lost"), () => {}); $("sheet").hidden = true;
  $("bar-note").hidden = true;
  $("coins").hidden = true;
  delete $("table").dataset.story;
  const opp = st.players.filter((p) => !st.you || p.pid !== st.you.pid);
  sizeTable(opp.length);
  swap($("opponents"), (probe) => opp.forEach((p, i) => {
    const seat = el("div", "seat");
    placeSeat(seat, opp.length, i);
    seat.setAttribute("role", "img");
    seat.setAttribute("aria-label", p.name + (p.ready ? ", ready" : ""));
    const av = avatarEl(p.pid);
    if (p.ready) { const t = el("span", "ready-tick"); t.appendChild(icon("check")); av.appendChild(t); }
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", p.name));
    probe.appendChild(seat);
  }));
  swap($("me-seat"), (probe) => {
    if (!st.you) return;
    const av = avatarEl(st.you.pid, 50);
    if (st.you.ready) { const t = el("span", "ready-tick"); t.appendChild(icon("check")); av.appendChild(t); }
    probe.appendChild(av);
  });
  const play = $("play");
  play.classList.add("lobby");
  swap($("reveal"), () => {});
  const caption = $("caption");
  caption.classList.remove("call");
  const n = st.players.filter((p) => p.ready && p.connected).length;
  const bots = (st.settings && st.settings.bots) || 0;
  if (st.party_round) {                   // AVR-129: the Party chose the table; no ready/start here
    swap(play, (probe) => probe.appendChild(el("div", "lobby-title", "BLUFF")));
    const here = st.players.filter((p) => p.connected).length;
    caption.textContent = here < st.players.length
      ? `Starting: ${here} of ${st.players.length} players here` : "Starting…";
    $("deck-n").textContent = "";
    swap($("bar"), () => {});
    return;
  }
  swap(play, (probe) => {
    probe.appendChild(el("div", "lobby-title", "BLUFF"));
    const step = el("div", "stepper");
    const minus = el("button"), plus = el("button");
    minus.type = plus.type = "button";
    minus.appendChild(icon("minus")); minus.setAttribute("aria-label", "Fewer test bots");
    plus.appendChild(icon("plus")); plus.setAttribute("aria-label", "More test bots");
    minus.dataset.k = "lobby:fewer"; plus.dataset.k = "lobby:more";
    HANDLERS["lobby:fewer"] = () => send({ t: "settings", patch: { bots: Math.max(0, bots - 1) } });
    HANDLERS["lobby:more"] = () => send({ t: "settings", patch: { bots: Math.min(5, bots + 1) } });
    step.append("Test bots", minus, el("b", null, String(bots)), plus);
    probe.appendChild(step);
  });
  caption.textContent = st.phase === "countdown" ? "Starting…" : `${n} of ${st.players.length} ready`;
  $("deck-n").textContent = "";
  const me = st.you;
  swap($("bar"), (bar) => {
    if (me && me.ready && n >= st.min_players) {
      bar.appendChild(actBtn("play", "START GAME", () => send({ t: "start" }), "primary", false, "bar:start"));
      bar.appendChild(actBtn("x", "Not ready", () => send({ t: "ready", ready: false }), "", false, "bar:not-ready"));
    } else {
      bar.appendChild(actBtn(me && me.ready ? "check" : "hand", me && me.ready ? "Ready" : "I'M READY", () => {
        // nobody enters play without the briefing's acknowledgement
        if (!(me && me.ready) && brief && !brief.acknowledged()) return brief.open("first", readyAfterBriefing);
        send({ t: "ready", ready: !(me && me.ready) });
      }, "primary", false, "bar:ready"));
    }
  });
}
