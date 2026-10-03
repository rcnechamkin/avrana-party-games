/* BLUFF table client. The phone is the whole game: you see the table, the other
   players' card BACKS (the server never sends their faces), your own cards as a
   real hand, and big contextual controls in the bar at the bottom. */
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
// A coin count reads as words to assistive tech: "3 coins".
function coinsEl(n, cls) {
  const c = el("span", cls);
  c.setAttribute("aria-label", n + (n === 1 ? " coin" : " coins"));
  c.append(art("flip_full"), el("span", null, String(n)));
  c.lastChild.setAttribute("aria-hidden", "true");
  return c;
}
document.querySelectorAll("[data-icon]").forEach((slot) => slot.appendChild(icon(slot.dataset.icon)));

let ST = null;
let takeoverTimer = null;
let picking = null;          // action awaiting a target tap
let sheet = null;            // "claim" when the claim menu is open
let keepSel = [], keepKey = "";
let drawerOpen = false, celebrated = false;
// How to play (briefing.js): shown once before a new player's first Ready; ? reopens it any time.
const brief = window.BluffBriefing || null;
let briefOffered = false, briefHinted = false;

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
    if (step(ST) !== step(st)) { picking = null; sheet = null; }
    ST = st;
    render();
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

// Opponent seats as [x, y] % of the opponents' zone (#opponents: header row down to
// your own avatar row), each seat anchored at its top-centre, listed clockwise
// from your left. MAX_SEATS is 6, so at most 5 opponents. The centre card sits in
// the lower middle of the zone; side seats stay clear of it horizontally.
const LAYOUT = {
  1: [[50, 0]],
  2: [[27, 0], [73, 0]],
  3: [[14, 30], [50, 0], [86, 30]],
  4: [[13, 36], [32, 0], [68, 0], [87, 36]],
  5: [[12, 52], [16, 0], [50, 0], [84, 0], [88, 52]],
  6: [[12, 52], [12, 0], [37, 0], [63, 0], [88, 0], [88, 52]],   // spectator of a full table
};
const seatPos = (n, i) => ((LAYOUT[Math.min(n, 6)] || [])[i] || [50, 0]);

// keep the real visible height in a CSS variable (older iOS lacks dvh; this also
// follows Safari's toolbars showing/hiding and rotation)
function syncHeight() {
  const h = Math.round(window.innerHeight);
  $("app").style.setProperty("--apph", h + "px");
  $("app").style.height = h + "px";
}
syncHeight();
window.addEventListener("resize", () => { syncHeight(); if (ST) render(); });

// 3+ opponents, or a short opponents' zone, get compact seats
function compactSeats(box, n) {
  box.classList.toggle("compact", n >= 3 || box.clientHeight < 400);
}

// ---------------------------------------------------------------- helpers

const playerOf = (pid) => (ST.players || []).find((p) => p.pid === pid) || {};
const g = () => ST.game;
const seatOf = (pid) => g() && g().seats.find((s) => s.pid === pid);
const isMe = (pid) => !!(pid && g() && g().me && g().me.pid === pid);
const nameOf = (pid) => (isMe(pid) ? "You" : (seatOf(pid) || playerOf(pid)).name || "?");
const role = (r) => (g() ? g().roles[r] : null) || { icon: "", text: "" };

function avatarEl(pid, size) {
  const p = playerOf(pid), a = el("div", "avatar");
  a.style.setProperty("--col", p.color || "#2d3a8c");
  if (size) { a.style.width = a.style.height = size + "px"; a.style.fontSize = size * 0.58 + "px"; }
  if (p.pfp) { const img = el("img"); img.src = p.pfp; img.alt = ""; a.appendChild(img); }
  else if (p.bot) a.appendChild(icon("bot"));
  else a.textContent = p.avatar || "🙂";      // a player's own chosen character (identity)
  return a;
}

function cardFace(r, extra) {
  const c = el("div", "card role-" + roleKey(r) + (extra ? " " + extra : ""));
  const idx = el("div", "idx"); idx.appendChild(art(roleArt(r))); c.appendChild(idx);
  const big = el("div", "big"); big.appendChild(art(roleArt(r))); c.appendChild(big);
  c.appendChild(el("div", "nm", r));
  return c;
}

// ic: a Lucide name for table controls (play, x, check, ...) or "art:<name>" for BLUFF's
// own game art (roles, coins, the coup, a claim, a challenge).
const LUCIDE = new Set(["play", "x", "check", "hand", "log-out", "circle-stop", "circle-help", "house"]);
function actBtn(ic, label, onclick, cls, disabled) {
  const b = el("button", "act " + (cls || ""));
  const slot = el("span", "ic");
  if (LUCIDE.has(ic)) slot.appendChild(icon(ic));
  else if (ic.startsWith("art:")) slot.appendChild(art(ic.slice(4)));
  else slot.textContent = ic;
  b.appendChild(slot);
  b.appendChild(el("span", null, label));
  b.onclick = onclick;
  if (disabled) b.disabled = true;
  return b;
}

// ---------------------------------------------------------------- timer

setInterval(() => {
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
  const st = ST;
  if (SETUP) return;
  const P = party();
  $("party-end").hidden = !(P && st.party_round && st.phase === "playing" && P.isHost());
  const inLobby = st.phase === "lobby" || st.phase === "countdown";
  briefing(st, inLobby);
  $("drawer").hidden = !drawerOpen;
  $("piles").classList.toggle("hide", inLobby);
  if (inLobby) { picking = null; sheet = null; celebrated = false; return renderLobby(st); }
  $("play").classList.remove("lobby");
  if (!g()) return;
  renderOpponents();
  renderCenter();
  renderMe();
  renderBar();
  renderDrawer();
  if (g().winner && !celebrated) { celebrated = true; if (g().me && g().winner === g().me.pid) Hub.confettiBurst(140); }
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

function renderOpponents() {
  const box = $("opponents");
  box.textContent = "";
  const opp = orderedOpponents();
  compactSeats(box, opp.length);
  const waiting = new Set(g().pending.waiting || []);
  const targets = targetsFor(picking);
  opp.forEach((s, i) => {
    const [x, y] = seatPos(opp.length, i);
    const seat = el("div", "seat" + (s.turn ? " turn" : "") + (s.alive ? "" : " out")
      + (targets.has(s.pid) ? " targetable" : ""));
    seat.style.left = x + "%"; seat.style.top = y + "%";
    const av = avatarEl(s.pid);
    if (waiting.has(s.pid)) av.appendChild(el("div", "bubble", "…"));
    if (g().winner === s.pid) { const cr = el("div", "crown"); cr.appendChild(art("crown_a", "Winner")); av.appendChild(cr); }
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", s.name));
    const pres = { reconnecting: "reconnecting…", away: "away", left: "left" }[s.presence];
    if (pres && s.alive) seat.appendChild(el("div", "presence " + s.presence, pres));
    const info = el("div", "info"), cards = el("div", "cards");
    // a Party spectator's view shows every hand (AVR-129); players only ever get backs
    if (s.cards) for (const r of s.cards) cards.appendChild(cardFace(r, "mini"));
    else for (let k = 0; k < s.influence; k++) cards.appendChild(el("div", "back mini"));
    for (const r of s.revealed) cards.appendChild(cardFace(r, "mini dead"));
    info.appendChild(cards);
    info.appendChild(coinsEl(s.coins, "chip coins-chip"));
    seat.appendChild(info);
    if (targets.has(s.pid)) seat.onclick = () => {
      const a = picking; picking = null;
      gsend({ t: "act", action: a, target: s.pid });
    };
    box.appendChild(seat);
  });
}

function targetsFor(action) {
  if (!action || !g().me) return new Set();
  const a = (g().me.actions || []).find((x) => x.action === action);
  return new Set(a && a.targets ? a.targets : []);
}

function renderCenter() {
  const p = g().pending, play = $("play"), cap = $("caption");
  play.textContent = "";
  $("deck-n").textContent = g().deck_count;
  let text = "";
  const actor = nameOf(p.actor), tgt = p.target ? " → " + nameOf(p.target) : "";
  if (p.stage === "over") {
    const win = el("div", "winner");
    if (g().winner) win.append(art("crown_a"), `${nameOf(g().winner)} ${isMe(g().winner) ? "win" : "wins"}!`);
    else win.textContent = "Game over";
    play.appendChild(win);
  } else if (picking) {
    text = "Tap a glowing player to target them";
  } else if (p.stage === "turn") {
    text = p.actor === (g().me && g().me.pid) ? "Your turn" : `${actor}'s turn`;
  } else if (p.stage === "challenge") {
    play.appendChild(cardFace(p.claim_role, "claimed"));
    text = `${actor} claim${isMe(p.actor) ? "" : "s"} ${p.claim_role}: ${p.label}${tgt}`;
  } else if (p.stage === "block") {
    if (p.claim_role) play.appendChild(cardFace(p.claim_role, "claimed"));
    text = p.action === "aid" ? `${actor} wants Foreign Aid (+2)` : `${actor}: ${p.label}${tgt}`;
  } else if (p.stage === "block_challenge") {
    play.appendChild(cardFace(p.block_role, "claimed block"));
    text = `${nameOf(p.blocker)} block${isMe(p.blocker) ? "" : "s"} with ${p.block_role}`;
  } else if (p.stage === "lose") {
    text = `${nameOf(p.loser)} must give up a card`;
  } else if (p.stage === "exchange") {
    text = `${actor} ${isMe(p.actor) ? "are" : "is"} exchanging cards`;
  }
  if (g().paused) text = "Game paused: everyone stepped away. It ends unless someone returns.";
  cap.textContent = text;
  $("center").classList.toggle("row", !!play.querySelector(".claimed") && $("opponents").clientHeight < 360);
  // a decision waiting on me: say so in gold, and say what the question is
  const q = callQuestion(p);
  cap.classList.toggle("call", !!q);
  if (q) { if (!text) cap.textContent = ""; cap.appendChild(el("span", "q", q)); }
  // what just happened: only while nothing else is on the table (avoids repeating the caption)
  const last = g().log[g().log.length - 1];
  if (last && p.stage === "turn" && !picking) play.appendChild(el("div", "chip last", last));
}

// The question behind my current prompt, spelled out (claim and block are two
// separate windows: a Steal/Strike target first answers the claim, then may block).
function callQuestion(p) {
  const pr = g().me && g().me.prompt;
  if (!pr) return "";
  const actor = nameOf(p.actor), mine = p.target && p.target === g().me.pid;
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
  seatBox.textContent = ""; hand.textContent = ""; lost.textContent = "";
  if (!me) { coins.hidden = true; return; }
  const s = seatOf(me.pid);
  seatBox.className = s && s.turn ? "turn" : "";
  const av = avatarEl(me.pid, 50);
  if ((g().pending.waiting || []).includes(me.pid)) av.appendChild(el("div", "bubble", "!"));
  if (g().winner === me.pid) { const cr = el("div", "crown"); cr.appendChild(art("crown_a", "Winner")); av.appendChild(cr); }
  seatBox.appendChild(av);
  coins.hidden = false;
  coins.replaceChildren(coinsEl(s ? s.coins : 0, "coins-in"));
  const choosing = me.prompt && me.prompt.kind === "lose";
  hand.className = choosing ? "choosing" : "";
  me.cards.forEach((r, i) => {
    const c = cardFace(r);
    if (choosing) c.onclick = () => gsend({ t: "lose", card: i });
    hand.appendChild(c);
  });
  if (!me.cards.length) hand.appendChild(el("div", "chip", "You're out: watching the rest"));
  for (const r of s ? s.revealed : []) lost.appendChild(cardFace(r, "mini dead"));
}

// ---------------------------------------------------------------- the bar

function renderBar() {
  const bar = $("bar"), me = g().me, p = g().pending;
  bar.textContent = "";
  bar.classList.toggle("call", !!(me && me.prompt));
  $("sheet").hidden = true;
  const msg = (t) => bar.appendChild(el("div", "bar-msg", t));
  if (p.stage === "over") {
    const P = party();
    if (!(ST.party_round && P)) { msg("Back to the lobby in a moment…"); return; }
    // A Party round's results stay until the Party Host moves everyone on (ADR 0011).
    if (P.isHost()) {
      bar.appendChild(actBtn("play", "Play again", () => P.playAgain(), "primary"));
      bar.appendChild(actBtn("house", "Party Home", () => P.goHome()));
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
      else bar.appendChild(actBtn("play", "Start a new game", () => send({ t: "end_game" }), "primary"));
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
      bar.appendChild(actBtn("x", "Cancel", () => { picking = null; render(); }));
      return;
    }
    const by = Object.fromEntries(acts.map((a) => [a.action, a]));
    const choose = (a) => () => {
      sheet = null;
      if (a.targets) { picking = a.action; render(); }
      else gsend({ t: "act", action: a.action });
    };
    if (acts.length === 1 && by.coup) {
      msg("10+ coins: you must Coup");
      bar.appendChild(actBtn("art:exploding", "Coup", choose(by.coup), "danger"));
      return;
    }
    bar.appendChild(actBtn("art:token_add", "Income +1", choose(by.income), "primary", !by.income));
    bar.appendChild(actBtn("art:hand_token", "Foreign Aid +2", choose(by.aid), "", !by.aid));
    bar.appendChild(actBtn("art:exploding", "Coup (7)", by.coup ? choose(by.coup) : null, "danger", !by.coup));
    bar.appendChild(actBtn("art:hand_card", "Claim", () => { sheet = sheet ? null : "claim"; render(); }, "blue"));
    if (sheet === "claim") renderClaimSheet(acts, choose);
    return;
  }
  sheet = null;
  const pr = me.prompt;
  if (pr && pr.kind === "challenge") {
    bar.appendChild(actBtn("art:hand_cross", "CHALLENGE", () => gsend({ t: "respond", choice: "challenge" }), "danger"));
    bar.appendChild(actBtn("art:flip_head", "Pass", () => gsend({ t: "respond", choice: "pass" })));
  } else if (pr && pr.kind === "block") {
    for (const r of pr.roles)
      bar.appendChild(actBtn("art:" + roleArt(r), "Block as " + r, () => gsend({ t: "respond", choice: "block", role: r }), "blue role-" + roleKey(r)));
    bar.appendChild(actBtn("art:flip_head", "Allow", () => gsend({ t: "respond", choice: "allow" })));
  } else if (pr && pr.kind === "lose") {
    msg("Tap one of your cards to give it up");
  } else if (pr && pr.kind === "exchange") {
    renderExchangeSheet(pr);
    const ok = actBtn("check", `Keep ${keepSel.length}/${pr.keep}`, () => gsend({ t: "keep", cards: keepSel }), "primary", keepSel.length !== pr.keep);
    bar.appendChild(ok);
  } else {
    const w = (p.waiting || []).map(nameOf);
    msg(p.stage === "turn" ? `Waiting for ${nameOf(p.actor)}…` : w.length ? `Waiting for ${w.join(", ")}…` : "…");
  }
}

function renderClaimSheet(acts, choose) {
  const sh = $("sheet");
  sh.hidden = false; sh.textContent = "";
  sh.appendChild(el("h3", null, "CLAIM A ROLE (you don't need to hold it)"));
  const grid = el("div", "sheet-grid");
  for (const a of acts.filter((x) => x.claims)) {
    grid.appendChild(actBtn("art:" + roleArt(a.claims), `${a.claims}\n${a.label}`, choose(a), "blue role-" + roleKey(a.claims)));
  }
  if (!grid.childElementCount) grid.appendChild(el("div", "bar-msg", "No role actions available"));
  sh.appendChild(grid);
}

function renderExchangeSheet(pr) {
  const key = pr.pool.join(",");
  if (key !== keepKey) { keepKey = key; keepSel = []; }
  const sh = $("sheet");
  sh.hidden = false; sh.textContent = "";
  sh.appendChild(el("h3", null, `EXCHANGE: KEEP ${pr.keep}`));
  const row = el("div", "sheet-cards");
  pr.pool.forEach((r, i) => {
    const c = cardFace(r, keepSel.includes(i) ? "sel" : "");
    c.onclick = () => {
      keepSel = keepSel.includes(i) ? keepSel.filter((x) => x !== i)
        : keepSel.length < pr.keep ? keepSel.concat(i) : keepSel;
      render();
    };
    row.appendChild(c);
  });
  sh.appendChild(row);
}

// ---------------------------------------------------------------- drawer

// The server's log lines start with a marker glyph (game.py); draw BLUFF art instead and
// keep the words. Unknown lines are shown as sent.
const LOG_MARKS = [["\u{1F3F3}", "flag_square"], ["\u{1F3C6}", "award"], ["\u2620", "skull"], ["\u23F1", "hourglass"]];
function logLine(line) {
  const li = el("li");
  const hit = LOG_MARKS.find(([mark]) => line.startsWith(mark));
  if (!hit) { li.textContent = line; return li; }
  li.className = "marked";
  li.append(art(hit[1]), line.slice(hit[0].length).replace(/^\uFE0F/, "").trim());
  return li;
}

function renderDrawer() {
  if (!drawerOpen) return;
  let box = $("drawer-actions");
  if (!box) { box = el("div"); box.id = "drawer-actions"; $("log").before(box); }
  box.textContent = "";
  const me = g().me;
  if (me && !me.left && me.cards.length && !g().winner) {
    box.appendChild(actBtn("log-out", "Leave game", () => confirmAction({
      title: "Leave this game?",
      body: "Your seat plays on autopilot and you're out at the next turn. You'll watch the rest.",
      yes: "Leave game",
    }, () => send({ t: "leave_game" }))));
  }
  // In a Party round only the Party Host ends the game (their End beside ?; ADR 0011)
  if (me && !g().winner && !ST.party_round) {
    box.appendChild(actBtn("circle-stop", "End game", () => confirmAction({
      title: "End the game?",
      body: "Everyone goes back to the lobby. This only works when nobody else is still playing.",
      yes: "End game",
    }, () => send({ t: "end_game" }))));
  }
  const ol = $("log");
  ol.textContent = "";
  for (const line of g().log.slice().reverse()) ol.appendChild(logLine(line));
  const help = $("rolehelp");
  help.textContent = "";
  for (const [r, v] of Object.entries(g().roles)) {
    const row = el("div", "role-row role-" + roleKey(r));
    const words = el("span"); words.append(el("b", null, r), ": " + v.text);
    row.append(art(roleArt(r)), words);
    help.appendChild(row);
  }
  help.appendChild(el("div", null, "Anyone: Income +1 · Foreign Aid +2 (blockable) · Coup: pay 7 (must at 10+)."));
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

// ---------------------------------------------------------------- lobby

function renderLobby(st) {
  $("hand").textContent = ""; $("lost").textContent = ""; $("sheet").hidden = true;
  $("coins").hidden = true; $("me-seat").textContent = "";
  const opp = st.players.filter((p) => !st.you || p.pid !== st.you.pid);
  const box = $("opponents");
  box.textContent = "";
  compactSeats(box, opp.length);
  opp.forEach((p, i) => {
    const [x, y] = seatPos(opp.length, i);
    const seat = el("div", "seat");
    seat.style.left = x + "%"; seat.style.top = y + "%";
    const av = avatarEl(p.pid);
    if (p.ready) { const t = el("div", "ready-tick"); t.appendChild(icon("check")); t.setAttribute("aria-label", "Ready"); av.appendChild(t); }
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", p.name));
    box.appendChild(seat);
  });
  if (st.you) {
    const av = avatarEl(st.you.pid, 50);
    if (st.you.ready) { const t = el("div", "ready-tick"); t.appendChild(icon("check")); t.setAttribute("aria-label", "Ready"); av.appendChild(t); }
    $("me-seat").appendChild(av);
  }
  const play = $("play");
  play.textContent = "";
  play.classList.add("lobby");
  $("center").classList.remove("row");
  play.appendChild(el("div", "lobby-title", "BLUFF"));
  if (st.party_round) {                   // AVR-129: the Party chose the table; no ready/start here
    const here = st.players.filter((p) => p.connected).length;
    $("caption").textContent = here < st.players.length
      ? `Starting: ${here} of ${st.players.length} players here` : "Starting…";
    $("deck-n").textContent = "";
    $("bar").textContent = "";
    return;
  }
  const bots = (st.settings && st.settings.bots) || 0;
  const step = el("div", "stepper");
  const minus = el("button"), plus = el("button");
  minus.appendChild(icon("minus")); minus.setAttribute("aria-label", "Fewer test bots");
  plus.appendChild(icon("plus")); plus.setAttribute("aria-label", "More test bots");
  minus.onclick = () => send({ t: "settings", patch: { bots: Math.max(0, bots - 1) } });
  plus.onclick = () => send({ t: "settings", patch: { bots: Math.min(5, bots + 1) } });
  step.append("Test bots", minus, el("b", null, String(bots)), plus);
  play.appendChild(step);
  const n = st.players.filter((p) => p.ready && p.connected).length;
  $("caption").textContent = st.phase === "countdown" ? "Starting…" : `${n} of ${st.players.length} ready`;
  $("deck-n").textContent = "";
  const bar = $("bar");
  bar.textContent = "";
  const me = st.you;
  if (me && me.ready && n >= st.min_players) {
    bar.appendChild(actBtn("play", "START GAME", () => send({ t: "start" }), "primary"));
    bar.appendChild(actBtn("x", "Not ready", () => send({ t: "ready", ready: false })));
  } else {
    bar.appendChild(actBtn(me && me.ready ? "check" : "hand", me && me.ready ? "Ready" : "I'M READY", () => {
      // nobody enters play without the briefing's acknowledgement
      if (!(me && me.ready) && brief && !brief.acknowledged()) return brief.open("first", readyAfterBriefing);
      send({ t: "ready", ready: !(me && me.ready) });
    }, "primary"));
  }
}
