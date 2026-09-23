/* BLUFF prototype client. The phone is the whole game: the shared table for
   everyone, your own cards for you only (the server never sends anyone else's),
   and big contextual buttons for whatever the server is waiting on you for. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, text, cls) => {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
};
let ST = null, clockOffset = 0, picking = null, keepSel = [], keepKey = "";

if (!Hub.identity.name) Hub.identity.name = "PLAYER";

const conn = Hub.connect("/games/bluff/ws", {
  onFx: (fx) => {
    if (fx.kind === "toast") Hub.toast((fx.icon ? fx.icon + " " : "") + fx.msg);
    if (fx.kind === "invalid") Hub.toast(fx.msg, "err");
  },
  onState: (st) => { clockOffset = Date.now() - st.now; ST = st; render(); },
});

setInterval(tickTimer, 250);
function tickTimer() {
  if (!ST || !ST.deadline || !ST.game) { $("timer").textContent = ""; return; }
  const left = Math.max(0, Math.ceil((ST.deadline - (Date.now() - clockOffset)) / 1000));
  $("timer").textContent = left + "s";
}

const send = (m) => conn.send(m);
const nameOf = (pid) => {
  const s = ST && ST.game && ST.game.seats.find((x) => x.pid === pid);
  return s ? s.name : "?";
};
const roleTag = (g, r) => (g.roles[r] ? g.roles[r].icon + " " + r : r);

// ---------------------------------------------------------------- lobby

function renderLobby(st) {
  const n = st.players.filter((p) => p.ready && p.connected).length;
  $("lobby-status").textContent = `LOBBY — ${n} ready of ${st.players.length}`;
  const bots = (st.settings && st.settings.bots) || 0;
  $("bots-n").textContent = bots;
  $("bots-minus").onclick = () => send({ t: "settings", patch: { bots: Math.max(0, bots - 1) } });
  $("bots-plus").onclick = () => send({ t: "settings", patch: { bots: Math.min(5, bots + 1) } });
  const me = st.you, btn = $("lobby-btn");
  if (me && me.ready && n >= st.min_players) {
    btn.textContent = "START GAME";
    btn.onclick = () => send({ t: "start" });
  } else {
    btn.textContent = me && me.ready ? "READY ✓" : "READY UP";
    btn.onclick = () => send({ t: "ready", ready: !(me && me.ready) });
  }
}

// ---------------------------------------------------------------- game

function render() {
  const st = ST;
  $("countdown-overlay").hidden = st.phase !== "countdown";
  const inLobby = st.phase === "lobby" || st.phase === "countdown";
  $("lobby").hidden = !inLobby;
  $("play").hidden = inLobby || !st.game;
  if (inLobby) { picking = null; return renderLobby(st); }
  const g = st.game;
  if (!g) return;
  renderBanner(g);
  renderMine(g);
  renderPrompt(g);
  renderSeats(g);
  renderLog(g);
  renderRoles(g);
}

function describePending(g) {
  const p = g.pending, a = nameOf(p.actor);
  const tgt = p.target ? " → " + nameOf(p.target) : "";
  switch (p.stage) {
    case "turn": return `${a}'s turn`;
    case "challenge": return `${a} claims ${roleTag(g, p.claim_role)} (${p.label}${tgt}). Anyone may challenge.`;
    case "block": return p.action === "aid"
      ? `${a} wants Foreign Aid. Anyone may block with ${roleTag(g, "Banker")}.`
      : `${a}: ${p.label}${tgt}. ${nameOf(p.target)} may block.`;
    case "block_challenge": return `${nameOf(p.blocker)} blocks, claiming ${roleTag(g, p.block_role)}. Challenge it?`;
    case "lose": return `${nameOf(p.loser)} must give up a card.`;
    case "exchange": return `${a} is exchanging cards.`;
    case "over": return g.winner ? `🏆 ${nameOf(g.winner)} wins!` : "Game over";
    default: return "";
  }
}

function renderBanner(g) {
  const me = g.me, p = g.pending;
  const mine = me && ((p.stage === "turn" && p.actor === me.pid) || (me.prompt));
  $("banner").className = mine ? "you" : "";
  let t = describePending(g);
  if (me && p.stage === "turn" && p.actor === me.pid) t = "YOUR TURN — choose an action";
  $("banner-text").textContent = t;
}

function renderMine(g) {
  const me = g.me;
  $("mine").hidden = !me;
  if (!me) return;
  const seat = g.seats.find((s) => s.pid === me.pid);
  $("mycoins").textContent = seat ? `· 🪙 ${seat.coins}` : "";
  const box = $("mycards");
  box.textContent = "";
  for (const r of me.cards) box.appendChild(cardEl(g, r));
  for (const r of seat ? seat.revealed : []) box.appendChild(cardEl(g, r, "dead"));
  if (!me.cards.length) box.appendChild(el("p", "You're out — watch the rest.", "muted"));
}

function cardEl(g, r, extra) {
  const c = el("div", null, "card" + (extra ? " " + extra : ""));
  c.appendChild(el("div", g.roles[r].icon, "ic"));
  c.appendChild(el("div", r, "rn"));
  c.appendChild(el("div", g.roles[r].text, "tx"));
  return c;
}

function button(label, onclick, cls) {
  const b = el("button", label, "btn " + (cls || ""));
  b.onclick = onclick;
  return b;
}

function renderPrompt(g) {
  const box = $("prompt"), me = g.me, p = g.pending;
  box.textContent = "";
  if (!me) return;
  const grid = el("div", null, "btns");

  if (me.actions && me.actions.length) {
    if (picking) {
      const a = me.actions.find((x) => x.action === picking);
      if (!a) { picking = null; return renderPrompt(g); }
      box.appendChild(el("div", `${a.label}: choose a target`, "ptext"));
      for (const pid of a.targets) {
        grid.appendChild(button(nameOf(pid), () => { picking = null; send({ t: "act", action: a.action, target: pid }); }, "btn-primary"));
      }
      grid.appendChild(button("Cancel", () => { picking = null; renderPrompt(g); }, "btn-wide"));
    } else {
      if (me.actions.length === 1 && me.actions[0].action === "coup")
        box.appendChild(el("div", "You have 10+ coins: you must Coup.", "ptext"));
      for (const a of me.actions) {
        const label = a.claims ? `${a.label}\n(claim ${g.roles[a.claims].icon} ${a.claims})` : a.label;
        grid.appendChild(button(label, () => {
          if (a.targets) { picking = a.action; renderPrompt(g); }
          else send({ t: "act", action: a.action });
        }, a.claims ? "" : "btn-primary"));
      }
    }
    box.appendChild(grid);
    return;
  }
  picking = null;
  const pr = me.prompt;
  if (!pr) return;

  if (pr.kind === "challenge") {
    box.appendChild(el("div", "Do you believe them?", "ptext"));
    grid.appendChild(button("CHALLENGE", () => send({ t: "respond", choice: "challenge" }), "btn-primary"));
    grid.appendChild(button("Pass", () => send({ t: "respond", choice: "pass" })));
  } else if (pr.kind === "block") {
    box.appendChild(el("div", "Block it by claiming a role, or allow it.", "ptext"));
    for (const r of pr.roles)
      grid.appendChild(button(`BLOCK as ${roleTag(g, r)}`, () => send({ t: "respond", choice: "block", role: r }), "btn-primary"));
    grid.appendChild(button("Allow", () => send({ t: "respond", choice: "allow" }), "btn-wide"));
  } else if (pr.kind === "lose") {
    box.appendChild(el("div", "Choose a card to give up (it is revealed to everyone):", "ptext"));
    me.cards.forEach((r, i) => grid.appendChild(button(`Lose ${roleTag(g, r)}`, () => send({ t: "lose", card: i }), "btn-primary")));
  } else if (pr.kind === "exchange") {
    const key = pr.pool.join(",");
    if (key !== keepKey) { keepKey = key; keepSel = []; }
    box.appendChild(el("div", `Keep ${pr.keep} card(s). Tap to select:`, "ptext"));
    const row = el("div", null, "cards");
    pr.pool.forEach((r, i) => {
      const c = cardEl(g, r, keepSel.includes(i) ? "sel" : "");
      c.onclick = () => {
        keepSel = keepSel.includes(i) ? keepSel.filter((x) => x !== i)
          : keepSel.length < pr.keep ? keepSel.concat(i) : keepSel;
        renderPrompt(g);
      };
      row.appendChild(c);
    });
    box.appendChild(row);
    const ok = button(`KEEP ${keepSel.length}/${pr.keep}`, () => send({ t: "keep", cards: keepSel }), "btn-primary btn-wide");
    ok.disabled = keepSel.length !== pr.keep;
    grid.appendChild(ok);
  }
  box.appendChild(grid);
}

function renderSeats(g) {
  const box = $("seats"), waiting = new Set(g.pending.waiting || []);
  box.textContent = "";
  for (const s of g.seats) {
    const row = el("div", null, "seat" + (s.turn ? " turn" : "") + (s.alive ? "" : " out"));
    row.appendChild(el("span", s.name + (g.me && g.me.pid === s.pid ? " (you)" : "") + (s.bot ? " 🤖" : ""), "nm"));
    if (s.turn) row.appendChild(el("span", "TURN", "badge"));
    if (waiting.has(s.pid)) row.appendChild(el("span", "deciding…", "badge"));
    row.appendChild(el("span", "🪙" + s.coins, "coins"));
    row.appendChild(el("span", "▮".repeat(s.influence) || "OUT", "dots"));
    for (const r of s.revealed) row.appendChild(el("span", r, "rev"));
    box.appendChild(row);
  }
  $("seats").appendChild(el("div", `Deck: ${g.deck_count} cards`, "muted"));
}

function renderLog(g) {
  const ol = $("log");
  ol.textContent = "";
  for (const line of g.log.slice().reverse()) ol.appendChild(el("li", line));
}

function renderRoles(g) {
  const box = $("roles");
  if (box.childElementCount) return;
  for (const [r, v] of Object.entries(g.roles)) box.appendChild(el("div", `${v.icon} ${r}: ${v.text}`));
  box.appendChild(el("div", "Anyone: Income +1 · Foreign Aid +2 (blockable) · Coup: pay 7, target loses a card (must Coup at 10+)."));
}
