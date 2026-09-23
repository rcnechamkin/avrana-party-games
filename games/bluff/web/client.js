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

let ST = null;
let leaveArmed = 0;         // two-tap confirm for "Leave game"
let picking = null;          // action awaiting a target tap
let sheet = null;            // "claim" when the claim menu is open
let keepSel = [], keepKey = "";
let drawerOpen = false, celebrated = false;

const conn = Hub.connect("/games/bluff/ws", {
  onFx: (fx) => {
    if (fx.kind === "toast") Hub.toast((fx.icon ? fx.icon + " " : "") + fx.msg);
    if (fx.kind === "invalid") Hub.toast(fx.msg, "err");
  },
  onState: (st) => { ST = st; render(); },
});
const send = (m) => conn.send(m);
// game answers carry the prompt step, so a late tap can never land in a newer prompt
const gsend = (m) => send(Object.assign({ step: g() && g().pending.step }, m));

$("home").onclick = () => { location.href = "/"; };
$("history").onclick = () => { drawerOpen = true; render(); };
$("drawer-close").onclick = () => { drawerOpen = false; render(); };

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
};
const seatPos = (n, i) => ((LAYOUT[Math.min(n, 5)] || [])[i] || [50, 0]);

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
const role = (r) => (g() ? g().roles[r] : null) || { icon: "❔", text: "" };

function avatarEl(pid, size) {
  const p = playerOf(pid), a = el("div", "avatar");
  a.style.setProperty("--col", p.color || "#2d3a8c");
  if (size) { a.style.width = a.style.height = size + "px"; a.style.fontSize = size * 0.58 + "px"; }
  if (p.pfp) { const img = el("img"); img.src = p.pfp; img.alt = ""; a.appendChild(img); }
  else a.textContent = p.bot ? "🤖" : (p.avatar || "🙂");
  return a;
}

function cardFace(r, extra) {
  const c = el("div", "card" + (extra ? " " + extra : ""));
  const R = role(r);
  const idx = el("div", "idx"); idx.textContent = R.icon; c.appendChild(idx);
  c.appendChild(el("div", "big", R.icon));
  c.appendChild(el("div", "nm", r));
  return c;
}

function actBtn(icon, label, onclick, cls, disabled) {
  const b = el("button", "act " + (cls || ""));
  b.appendChild(el("span", "ic", icon));
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
  if (g().paused) {
    t.textContent = "⏸ " + Math.floor(left / 60) + ":" + String(left % 60).padStart(2, "0");
    t.classList.remove("urgent");
    return;
  }
  t.textContent = "⏱ " + left;
  t.classList.toggle("urgent", left <= 5);
}, 250);

// ---------------------------------------------------------------- render

function render() {
  const st = ST;
  const inLobby = st.phase === "lobby" || st.phase === "countdown";
  $("drawer").hidden = !drawerOpen;
  $("piles").classList.toggle("hide", inLobby);
  if (inLobby) { picking = null; sheet = null; celebrated = false; return renderLobby(st); }
  if (!g()) return;
  renderOpponents();
  renderCenter();
  renderMe();
  renderBar();
  renderDrawer();
  if (g().winner && !celebrated) { celebrated = true; if (g().me && g().winner === g().me.pid) Hub.confettiBurst(140); }
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
    if (g().winner === s.pid) av.appendChild(el("div", "crown", "👑"));
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", s.name + (s.bot ? " 🤖" : "")));
    const pres = { reconnecting: "reconnecting…", away: "away · autopilot", left: "left" }[s.presence];
    if (pres && s.alive) seat.appendChild(el("div", "presence " + s.presence, pres));
    const info = el("div", "info"), cards = el("div", "cards");
    for (let k = 0; k < s.influence; k++) cards.appendChild(el("div", "back mini"));
    for (const r of s.revealed) cards.appendChild(cardFace(r, "mini dead"));
    info.appendChild(cards);
    info.appendChild(el("div", "chip", "🪙 " + s.coins));
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
    play.appendChild(el("div", "winner", g().winner ? `👑 ${nameOf(g().winner)} ${isMe(g().winner) ? "win" : "wins"}!` : "Game over"));
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
  if (g().winner === me.pid) av.appendChild(el("div", "crown", "👑"));
  seatBox.appendChild(av);
  coins.hidden = false;
  coins.textContent = "🪙 " + (s ? s.coins : 0);
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
  if (p.stage === "over") { msg("Back to the lobby in a moment…"); return; }
  if (!me) { msg("Watching"); return; }
  if (me.left) { msg("You left this game: watching"); return; }

  const acts = me.actions || [];
  if (acts.length) {
    if (picking) {
      const pa = (acts.find((x) => x.action === picking) || {}).label || "";
      msg(`${pa}: tap a glowing player`);
      bar.appendChild(actBtn("✕", "Cancel", () => { picking = null; render(); }));
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
      bar.appendChild(actBtn("💥", "Coup", choose(by.coup), "danger"));
      return;
    }
    bar.appendChild(actBtn("🪙", "Income +1", choose(by.income), "primary", !by.income));
    bar.appendChild(actBtn("🤲", "Foreign Aid +2", choose(by.aid), "", !by.aid));
    bar.appendChild(actBtn("💥", "Coup (7)", by.coup ? choose(by.coup) : null, "danger", !by.coup));
    bar.appendChild(actBtn("🎭", "Claim ▸", () => { sheet = sheet ? null : "claim"; render(); }, "blue"));
    if (sheet === "claim") renderClaimSheet(acts, choose);
    return;
  }
  sheet = null;
  const pr = me.prompt;
  if (pr && pr.kind === "challenge") {
    bar.appendChild(actBtn("⚔️", "CHALLENGE", () => gsend({ t: "respond", choice: "challenge" }), "danger"));
    bar.appendChild(actBtn("👍", "Pass", () => gsend({ t: "respond", choice: "pass" })));
  } else if (pr && pr.kind === "block") {
    for (const r of pr.roles)
      bar.appendChild(actBtn(role(r).icon, "Block as " + r, () => gsend({ t: "respond", choice: "block", role: r }), "blue"));
    bar.appendChild(actBtn("👍", "Allow", () => gsend({ t: "respond", choice: "allow" })));
  } else if (pr && pr.kind === "lose") {
    msg("Tap one of your cards to give it up");
  } else if (pr && pr.kind === "exchange") {
    renderExchangeSheet(pr);
    const ok = actBtn("✔", `Keep ${keepSel.length}/${pr.keep}`, () => gsend({ t: "keep", cards: keepSel }), "primary", keepSel.length !== pr.keep);
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
    grid.appendChild(actBtn(role(a.claims).icon, `${a.claims}\n${a.label}`, choose(a), "blue"));
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

function renderDrawer() {
  if (!drawerOpen) return;
  let box = $("drawer-actions");
  if (!box) { box = el("div"); box.id = "drawer-actions"; $("log").before(box); }
  box.textContent = "";
  const me = g().me;
  if (me && !me.left && me.cards.length && !g().winner) {
    const armed = Date.now() - leaveArmed < 4000;
    box.appendChild(actBtn("🏳", armed ? "Tap again to leave" : "Leave game", () => {
      if (Date.now() - leaveArmed < 4000) { leaveArmed = 0; send({ t: "leave_game" }); }
      else { leaveArmed = Date.now(); setTimeout(render, 4100); }
      render();
    }, armed ? "danger" : ""));
  }
  if (me && !g().winner)
    box.appendChild(actBtn("⏹", "End game", () => send({ t: "end_game" }), "",
      false));
  const ol = $("log");
  ol.textContent = "";
  for (const line of g().log.slice().reverse()) ol.appendChild(el("li", null, line));
  const help = $("rolehelp");
  help.textContent = "";
  for (const [r, v] of Object.entries(g().roles)) help.appendChild(el("div", null, `${v.icon} ${r}: ${v.text}`));
  help.appendChild(el("div", null, "Anyone: Income +1 · Foreign Aid +2 (blockable) · Coup: pay 7 (must at 10+)."));
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
    if (p.ready) av.appendChild(el("div", "ready-tick", "✅"));
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", p.name));
    box.appendChild(seat);
  });
  if (st.you) {
    const av = avatarEl(st.you.pid, 50);
    if (st.you.ready) av.appendChild(el("div", "ready-tick", "✅"));
    $("me-seat").appendChild(av);
  }
  const play = $("play");
  play.textContent = "";
  $("center").classList.remove("row");
  play.appendChild(el("div", "lobby-title", "BLUFF"));
  const bots = (st.settings && st.settings.bots) || 0;
  const step = el("div", "stepper");
  const minus = el("button", null, "−"), plus = el("button", null, "+");
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
    bar.appendChild(actBtn("▶", "START GAME", () => send({ t: "start" }), "primary"));
    bar.appendChild(actBtn("✕", "Not ready", () => send({ t: "ready", ready: false })));
  } else {
    bar.appendChild(actBtn("✋", me && me.ready ? "Ready ✓" : "I'M READY", () => send({ t: "ready", ready: !(me && me.ready) }), "primary"));
  }
}
