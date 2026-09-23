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

let ST = null, clockOffset = 0;
let picking = null;          // action awaiting a target tap
let sheet = null;            // "claim" when the claim menu is open
let keepSel = [], keepKey = "";
let drawerOpen = false, celebrated = false;

if (!Hub.identity.name) Hub.identity.name = "PLAYER";

const conn = Hub.connect("/games/bluff/ws", {
  onFx: (fx) => {
    if (fx.kind === "toast") Hub.toast((fx.icon ? fx.icon + " " : "") + fx.msg);
    if (fx.kind === "invalid") Hub.toast(fx.msg, "err");
  },
  onState: (st) => { clockOffset = Date.now() - st.now; ST = st; render(); },
});
const send = (m) => conn.send(m);

$("home").onclick = () => { location.href = "/"; };
$("history").onclick = () => { drawerOpen = true; render(); };
$("drawer-close").onclick = () => { drawerOpen = false; render(); };

// Opponent positions (% of the screen), listed clockwise from your left.
const LAYOUT = {
  1: [[50, 15]],
  2: [[24, 17], [76, 17]],
  3: [[12, 42], [50, 15], [88, 42]],
  4: [[12, 46], [30, 16], [70, 16], [88, 46]],
  5: [[12, 55], [12, 30], [50, 15], [88, 30], [88, 55]],
  6: [[12, 58], [12, 34], [34, 15], [66, 15], [88, 34], [88, 58]],
};

// ---------------------------------------------------------------- helpers

const playerOf = (pid) => (ST.players || []).find((p) => p.pid === pid) || {};
const g = () => ST.game;
const seatOf = (pid) => g() && g().seats.find((s) => s.pid === pid);
const nameOf = (pid) => (pid === (g() && g().me && g().me.pid) ? "You" : (seatOf(pid) || playerOf(pid)).name || "?");
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
  const left = Math.max(0, Math.ceil((ST.deadline - (Date.now() - clockOffset)) / 1000));
  t.hidden = false;
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
  const opp = orderedOpponents(), pos = LAYOUT[Math.min(opp.length, 6)] || [];
  const waiting = new Set(g().pending.waiting || []);
  const targets = targetsFor(picking);
  opp.forEach((s, i) => {
    const [x, y] = pos[i] || [50, 50];
    const seat = el("div", "seat" + (s.turn ? " turn" : "") + (s.alive ? "" : " out")
      + (targets.has(s.pid) ? " targetable" : ""));
    seat.style.left = x + "%"; seat.style.top = y + "%";
    const av = avatarEl(s.pid);
    if (waiting.has(s.pid)) av.appendChild(el("div", "bubble", "…"));
    if (g().winner === s.pid) av.appendChild(el("div", "crown", "👑"));
    seat.appendChild(av);
    seat.appendChild(el("div", "nm", s.name + (s.bot ? " 🤖" : "")));
    const cards = el("div", "cards");
    for (let k = 0; k < s.influence; k++) cards.appendChild(el("div", "back mini"));
    for (const r of s.revealed) cards.appendChild(cardFace(r, "mini dead"));
    seat.appendChild(cards);
    seat.appendChild(el("div", "chip", "🪙 " + s.coins));
    if (targets.has(s.pid)) seat.onclick = () => {
      const a = picking; picking = null;
      send({ t: "act", action: a, target: s.pid });
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
    play.appendChild(el("div", "winner", g().winner ? `👑 ${nameOf(g().winner)} ${nameOf(g().winner) === "You" ? "win" : "wins"}!` : "Game over"));
  } else if (picking) {
    text = "Tap a player to target";
  } else if (p.stage === "turn") {
    text = p.actor === (g().me && g().me.pid) ? "Your turn" : `${actor}'s turn`;
  } else if (p.stage === "challenge") {
    play.appendChild(cardFace(p.claim_role, "claimed"));
    text = `${actor} claim${actor === "You" ? "" : "s"} ${p.claim_role}: ${p.label}${tgt}`;
  } else if (p.stage === "block") {
    if (p.claim_role) play.appendChild(cardFace(p.claim_role, "claimed"));
    text = p.action === "aid" ? `${actor} wants Foreign Aid (+2)` : `${actor}: ${p.label}${tgt}`;
  } else if (p.stage === "block_challenge") {
    play.appendChild(cardFace(p.block_role, "claimed block"));
    text = `${nameOf(p.blocker)} block${nameOf(p.blocker) === "You" ? "" : "s"} with ${p.block_role}`;
  } else if (p.stage === "lose") {
    text = `${nameOf(p.loser)} must give up a card`;
  } else if (p.stage === "exchange") {
    text = `${actor} ${actor === "You" ? "are" : "is"} exchanging cards`;
  }
  cap.textContent = text;
  // what just happened: only while nothing else is on the table (avoids repeating the caption)
  const last = g().log[g().log.length - 1];
  if (last && p.stage === "turn" && !picking) play.appendChild(el("div", "chip last", last));
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
    if (choosing) c.onclick = () => send({ t: "lose", card: i });
    hand.appendChild(c);
  });
  if (!me.cards.length) hand.appendChild(el("div", "chip", "You're out: watching the rest"));
  for (const r of s ? s.revealed : []) lost.appendChild(cardFace(r, "mini dead"));
}

// ---------------------------------------------------------------- the bar

function renderBar() {
  const bar = $("bar"), me = g().me, p = g().pending;
  bar.textContent = "";
  $("sheet").hidden = true;
  const msg = (t) => bar.appendChild(el("div", "bar-msg", t));
  if (p.stage === "over") { msg("Back to the lobby in a moment…"); return; }
  if (!me) { msg("Watching"); return; }

  const acts = me.actions || [];
  if (acts.length) {
    if (picking) {
      msg("Tap a glowing player");
      bar.appendChild(actBtn("✕", "Cancel", () => { picking = null; render(); }));
      return;
    }
    const by = Object.fromEntries(acts.map((a) => [a.action, a]));
    const choose = (a) => () => {
      sheet = null;
      if (a.targets) { picking = a.action; render(); }
      else send({ t: "act", action: a.action });
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
    bar.appendChild(actBtn("⚔️", "CHALLENGE", () => send({ t: "respond", choice: "challenge" }), "danger"));
    bar.appendChild(actBtn("👍", "Pass", () => send({ t: "respond", choice: "pass" })));
  } else if (pr && pr.kind === "block") {
    for (const r of pr.roles)
      bar.appendChild(actBtn(role(r).icon, "Block as " + r, () => send({ t: "respond", choice: "block", role: r }), "blue"));
    bar.appendChild(actBtn("👍", "Allow", () => send({ t: "respond", choice: "allow" })));
  } else if (pr && pr.kind === "lose") {
    msg("Tap one of your cards to give it up");
  } else if (pr && pr.kind === "exchange") {
    renderExchangeSheet(pr);
    const ok = actBtn("✔", `Keep ${keepSel.length}/${pr.keep}`, () => send({ t: "keep", cards: keepSel }), "primary", keepSel.length !== pr.keep);
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
  const pos = LAYOUT[Math.min(Math.max(opp.length, 1), 6)] || [];
  const box = $("opponents");
  box.textContent = "";
  opp.forEach((p, i) => {
    const [x, y] = pos[i] || [50, 50];
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
