"use strict";
/* EXPO's phone client (AVR-275). One viewport during play: the mission, whose turn it is, the
   current trick and the hand are always on screen; crew detail, full tasks, sonar and history
   open as sheets over the board. The server's view is the only source of game meaning: this
   file draws it and sends requests, and never decides a rule.

   Two authorities, kept apart (AVR-252):
     Party Host    begins, retries, moves on and ends EXPO. In a Party round the server takes
                   those only with the Party's own word for who the host is (conn.hostAction);
                   AvranaParty.isHost() here only decides which controls are drawn.
     EXPO captain  whatever the rules give the captain: the first lead, Tonoja's cards, the
                   offer in missions 10 and 13. Nothing more. */
const $ = id => document.getElementById(id);
let ST = null, pending = false, pendingTimer = null;
const ui = { sheet: null, opener: null, selected: null, handView: "mine", turnKey: "",
             sonarCard: null, sonarMeaning: null, resultKey: "", resultHidden: false, armed: null,
             grace: 0, modal: null, partySig: "" };
const symbols = {blue:"○",green:"△",pink:"□",yellow:"×",submarine:"◆"};
const suitNames = {blue:"blue",green:"green",pink:"pink",yellow:"yellow",submarine:"sub"};
const OBJECTIVES = {
  balance9: "Never capture two more 9s than another crew member.",
  balance1: "Never capture two more color 1s than another crew member.",
  first_winner: "The first trick winner must always have strictly more tricks than everyone else. Sonar opens before trick 2.",
  final_yellow5: "Play yellow 5 as the final card in the final trick.",
};
const HELP = [
  "Take tricks together to complete every assigned task. Keep your hand secret: don’t tell, show or hint which cards you hold.",
  "Follow the opening suit when you can. When you cannot, play any card. Submarines beat every color; the highest submarine wins. The captain opens the first trick, and each winner opens the next.",
  "After tasks are assigned, communicate a color card before a trick. Reveal your highest, lowest or only card of that color. You normally get one sonar token per attempt. Its meaning stays fixed as your hand changes.",
  "With two players, the captain controls Tonoja’s visible cards and task choices without discussion. Covered cards turn over only after their covering card’s trick ends.",
  "Task difficulty adds up to the mission’s challenge. Some tasks need the full deal; positive tasks may finish earlier. A legal play can still fail the mission. Only the latest trick may be inspected.",
  "In a Party, the Party Host begins each mission, retries, chooses the next one and ends EXPO. The Captain is a role in the game, not the Party Host. The crew decides together only what the rules give the crew, such as distress.",
  "Some missions and tasks are unavailable while conflicting source rules are clarified. Available task descriptions follow the supplied rules and the pinned The Team II reference.",
];
const SHEETS = {crew:"Crew", tasks:"Mission tasks", sonar:"Sonar", history:"History", menu:"Table", help:"One crew. One mission."};

if (!Hub.identity.name) Hub.identity.name = "PLAYER";
$("name").value = Hub.identity.name;
Hub.buildAvatarGrid($("avatars"), Hub.identity.avatar, avatar => {
  Hub.identity.avatar = avatar;
  conn.send({t:"profile",avatar});
});
const conn = Hub.connect("/games/expo/ws", {
  onWelcome: () => { ui.setup = null; },   // a new connection may be a new table: nothing chosen carries over
  onState: render,
  onFx: fx => {
    if (fx.kind === "invalid") { settle(); Hub.toast(fx.msg, "err"); }
    if (fx.kind === "toast") Hub.toast(fx.msg);
  },
});
Hub.wirePfpButton($("photo"), () => conn);

// ---- small helpers ----------------------------------------------------------------------------
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, action, key, disabled=false, reason="", cls="") {
  const b = el("button", text, "btn" + (cls ? " " + cls : "")); b.type = "button"; b.disabled = disabled;
  b.dataset.key = key; b.title = reason; b.onclick = action; return b;
}
// A control that cannot be used says why in words on the page: a phone never shows a title.
// Why a card, a task, a pass, an answer, an offer or a prediction is unavailable is the server's
// sentence, from the view (`me.*_reason`, `me.*_reasons`): the very words it refuses that request
// with. So is why Begin, Retry or Next is (`lifecycle_reasons`, the same for every viewer: the
// Party Host may hold no seat). This file words no reason of its own for them, and such a control
// is disabled exactly when the view gives a reason (AVR-263).
function why(text) { return el("p", text, "why"); }
function stepReason(g, kind) { return g.lifecycle_reasons[kind] || ""; }
function busy() {
  pending = true;
  clearTimeout(pendingTimer);
  pendingTimer = setTimeout(settle, 4000);
}
function settle() { pending = false; clearTimeout(pendingTimer); }
function send(t, payload={}) {
  if (!ST?.game || pending) return;
  busy();
  conn.send({t,...payload,attempt:ST.game.attempt,revision:ST.game.revision,request:crypto.randomUUID()});
}
function propose(kind, payload={}) { send("propose", {proposal:{kind,...payload}}); }
function name(seat) {
  if (seat === "tonoja") return "Tonoja";
  return ST.players.find(p => p.pid === seat)?.name || seat || "Unassigned";
}
function names(seats) { return seats.map(name).join(", "); }
function cardLabel(card) { const [s,r] = card.split(":"); return `${r} ${s}`; }
function cardNode(card, action, enabled=false, reason="") {
  const [s,r] = card.split(":");
  const n = el(action ? "button" : "div", undefined, "card " + s);
  n.append(el("span",r,"rank"),el("span",symbols[s],"symbol"),el("span",suitNames[s],"suit"));
  n.setAttribute("aria-label", `${s} ${r}`); n.dataset.key = "card:" + card;
  if (action) { n.type = "button"; n.disabled = !enabled; n.title = reason; n.onclick = action; }
  return n;
}
function choices(select, entries, value) {
  select.replaceChildren();
  for (const entry of entries) {
    const o = el("option",entry.text); o.value = entry.value; o.disabled = Boolean(entry.disabled); select.append(o);
  }
  if (value !== undefined) select.value = String(value);
}
function ownerSelect(key, seats, refused={}) {
  const select = el("select"); select.dataset.key = key; select.setAttribute("aria-label","Task owner");
  choices(select, seats.map(s => ({value:s,text:name(s),disabled:Boolean(refused[s])})), seats.find(s => !refused[s]));
  return select;
}

// ---- the Party and its host -------------------------------------------------------------------
// Display only. The game server asks the Party again, by ticket, for every host action.
function party() { const P = window.AvranaParty; return P && P.active ? P : null; }
function amHost() { const P = party(); return Boolean(P && P.isHost()); }
function hostName() { const P = party(); return (P && P.hostName()) || null; }
function theHost() { return hostName() || "the Party Host"; }
function hostOwned(g) { return g.lifecycle === "host"; }
// May this phone ask for Begin, Retry or Next?
function mayMoveOn(g) { return hostOwned(g) ? amHost() : Boolean(g.me); }
// Ending a standalone table is the crew's decision: not offered while it cannot be proposed.
function blocked(g) { return Boolean(g.proposal) || g.away.length > 0; }
// The server's sentence for a Begin that cannot be used now, in words for whoever has the
// control: in the stage, where there is room for a line (the dock has none).
function beginWhy(g) {
  const refused = g.stage === "assistance" && !g.result && mayMoveOn(g) ? stepReason(g, "begin") : "";
  if (!refused) return null;
  const line = why(refused); line.dataset.key = "begin-why";
  return line;
}
// Seconds until the Party Host's Begin opens: the crew's moment to ask for distress (server's).
function graceLeft(g) { return g && g.begin_at ? Math.max(0, Math.ceil(g.begin_at - conn.now()/1000)) : 0; }
// The seat the Party Host sits in, when the name says so without doubt (the Party gives a name,
// not a seat): two crew members with the host's name get no badge rather than both.
function hostSeat(g) {
  const host = hostName();
  const seats = host ? g.seats.filter(s => s !== "tonoja" && name(s) === host) : [];
  return seats.length === 1 ? seats[0] : null;
}
async function lifecycle(decision) {
  const g = ST?.game;
  if (!g || pending) return;
  if (!hostOwned(g)) { const {kind, ...rest} = decision; propose(kind, rest); return; }
  busy();
  const sent = await conn.hostAction({t:"lifecycle",decision,attempt:g.attempt,revision:g.revision});
  if (!sent) { settle(); Hub.toast("Could not reach the Party. Try again.", "err"); }
}
// End for everyone is the Party's (ADR 0011): two taps, then the Party moves every phone home.
function endButton(text, key, cls="") {
  const label = () => ui.armed === key ? "Tap again to end for everyone" : text;
  const b = button(label(), async () => {
    if (ui.armed !== key) {
      ui.armed = key; draw();
      setTimeout(() => { if (ui.armed === key) { ui.armed = null; draw(); } }, 4000);
      return;
    }
    ui.armed = null; b.disabled = true;
    const P = party();
    const res = P ? await P.end() : null;
    if (!res || res.ok === false) { Hub.toast("The Party did not end the game. Try again.", "err"); draw(); }
  }, key, false, "", cls + (ui.armed === key ? " armed" : ""));
  return b;
}

// ---- lobby wiring -----------------------------------------------------------------------------
$("name").onchange = () => {
  Hub.identity.name = $("name").value;
  conn.send({t:"profile",name:Hub.identity.name});
};
$("ready").onclick = () => conn.send({t:"ready",ready:!ST?.you?.ready});
$("start").onclick = () => conn.send({t:"start"});
$("mission").onchange = () => choose({mission:Number($("mission").value)});
$("timed").onchange = () => choose({timed:$("timed").checked});
$("tonoja-position").onchange = () => choose({tonoja_position:Number($("tonoja-position").value)});
$("menu-toggle").onclick = e => openSheet("menu", e.currentTarget);
$("help-toggle").onclick = e => openSheet("help", e.currentTarget);
for (const tab of document.querySelectorAll(".tab")) tab.onclick = e => openSheet(tab.dataset.sheet, e.currentTarget);
$("sheet-close").onclick = closeSheet;
$("sheet-backdrop").onclick = closeSheet;
document.addEventListener("keydown", e => { if (e.key === "Escape" && ui.sheet && $("result").hidden) closeSheet(); });
document.addEventListener("avrana-party", () => { if (ST) draw(); });

// How to find a control again after a redraw has replaced it.
function refOf(node) {
  if (!node) return null;
  if (node.id) return "#" + node.id;
  if (node.dataset?.key) return `[data-key="${CSS.escape(node.dataset.key)}"]`;
  if (node.dataset?.sheet) return `.tab[data-sheet="${node.dataset.sheet}"]`;
  return null;
}
function focusRef(ref, fallback) {
  const n = (ref && document.querySelector(ref)) || null;
  const target = n && !n.disabled && n.offsetParent !== null ? n : fallback;
  if (target) target.focus({preventScroll:true});
}
function openSheet(kind, opener) {
  ui.sheet = kind; ui.opener = refOf(opener);
  draw();
  $("sheet-close").focus({preventScroll:true});
}
function closeSheet() {
  const opener = ui.opener;
  ui.sheet = null; ui.opener = null;
  draw();
  focusRef(opener, $("mission-title"));
}

// ---- one thing at a time: the sheet and the result are modal -----------------------------------
// What is on top keeps the keyboard and the screen reader: everything under it is inert (not
// focusable, not read, not tappable), Tab stays inside it, and focus goes back where it was.
// The status line stays live under it so a change is still announced.
function modalTop() { return !$("result").hidden ? $("result") : !$("sheet").hidden ? $("sheet") : null; }
function focusables(root) {
  return [...root.querySelectorAll("button, a[href], select, input, [tabindex]")]
    .filter(n => !n.disabled && n.tabIndex >= 0 && n.offsetParent !== null);
}
function syncModal() {
  const top = modalTop();
  for (const n of [document.querySelector(".topbar"), $("lobby"), $("game"), $("sheet")]) n.inert = Boolean(top) && n !== top;
  const was = ui.modal; ui.modal = top ? top.id : null;
  if (top && !top.contains(document.activeElement)) {
    if (top.id === "result") focusResult(); else $("sheet-close").focus({preventScroll:true});
  }
  // The result went away by itself (a retry, the next mission): focus lands on the board.
  if (was === "result" && !top && (!document.activeElement || document.activeElement === document.body))
    focusRef('[data-key="show-result"]', $("mission-title"));
}
document.addEventListener("keydown", e => {
  if (e.key !== "Tab") return;
  const top = modalTop(); if (!top) return;
  const list = focusables(top); if (!list.length) { e.preventDefault(); return; }
  const first = list[0], last = list[list.length - 1], at = document.activeElement;
  if (!top.contains(at)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
});

// ---- render -----------------------------------------------------------------------------------
function render(st) { ST = st; settle(); draw(); }

function draw() {
  const st = ST;
  const focusKey = document.activeElement?.dataset?.key;
  const values = new Map([...document.querySelectorAll("[data-key]")]
    .filter(n => ["INPUT","SELECT"].includes(n.tagName)).map(n => [n.dataset.key, n.value]));
  const setup = setupOf(st);                       // a Party round before its first deal (AVR-245)
  if (!setup) leaveSetup();
  const lobby = ["lobby","countdown"].includes(st.phase) || Boolean(setup);
  $("lobby").hidden = !lobby; $("game").hidden = lobby || !st.game;
  $("countdown-overlay").hidden = st.phase !== "countdown";
  if (lobby) { setup ? drawSetup(st, setup) : drawLobby(st); $("result").hidden = true; drawSheet(null, st); syncModal(); return; }
  const g = st.game;
  if (!g) { $("status").textContent = "This table has ended."; $("result").hidden = true; drawSheet(null, st); syncModal(); return; }
  // A crew decision after a result is answered on the result: never leave it put away.
  if (g.result && g.proposal) ui.resultHidden = false;
  ui.grace = graceLeft(g);
  syncTurn(g);
  drawStatus(g);
  drawHead(g);
  drawObjectives(g);
  drawCrew(g);
  drawStage(g);
  drawTabs(g);
  drawHand(g);
  drawDock(g);
  drawResult(g, st);
  drawSheet(g, st);
  for (const n of document.querySelectorAll("[data-key]")) {
    if (values.has(n.dataset.key) && ["INPUT","SELECT"].includes(n.tagName)
        && (n.tagName !== "SELECT" || [...n.options].some(o => o.value === values.get(n.dataset.key) && !o.disabled))) n.value = values.get(n.dataset.key);
    if (n.dataset.key === focusKey && !n.disabled && document.activeElement !== n) n.focus({preventScroll:true});
  }
  syncModal();
  if (ui.fromSetup) {
    // The table was just dealt and the control that did it is gone: focus lands on the board,
    // where a result that goes away puts it too, unless something still holds it.
    ui.fromSetup = false;
    const at = document.activeElement;
    if (!modalTop() && (!at || at === document.body || $("lobby").contains(at))) { $("mission-title").tabIndex = -1; $("mission-title").focus({preventScroll:true}); }
  }
  updateTimer();
}

function drawLobby(st) {
  const ready = st.players.filter(p => p.ready && p.connected).length;
  // A Party round has no lobby of its own: the Party ran the pregame and its host started it.
  $("lobby-form").hidden = $("lobby-actions").hidden = Boolean(st.party_round);
  $("status").textContent = st.recovery_error
    || (st.party_round ? "The crew is boarding…" : `${ready} crew members ready · ${st.players.length} at the table`);
  choices($("mission"), (st.missions||[]).map(m => ({value:m.id,text:`${m.id>32?"Deep dive":"Mission"} ${m.id}${m.enabled?"":" · unavailable"}`,disabled:!m.enabled})), st.settings.mission);
  $("timed").checked = st.settings.timed; $("tonoja-position").value = String(st.settings.tonoja_position);
  $("roster").replaceChildren();
  for (const p of st.players) {
    const row = el("div",undefined,"person"); const avatar = el("span",p.avatar,"avatar");
    Hub.fillAvatar(avatar,p);
    row.append(avatar, el("strong",p.name,"name"), el("span", st.party_round ? (p.connected?"Aboard":"On the way") : p.ready?"Ready":"Not ready", "muted"));
    $("roster").append(row);
  }
  $("ready").textContent = st.you?.ready ? "Ready ✓ · unready" : "Ready up";
  $("start").disabled = !st.you?.ready || ready<2 || st.phase==="countdown" || Boolean(st.recovery_error);
  $("lobby-reason").textContent = st.party_round ? "The mission starts when the crew is aboard."
    : ready<2 ? "Ready at least two players to begin. With two, Tonoja joins your crew." : "Crew order follows joining order, clockwise.";
}

// ---- setup: a Party round chooses what it opens on, in EXPO, before anything is dealt (AVR-245) ----
// The lobby's mission and clock controls, for whoever moves the table on: the Party Host, or the
// crew under a Party that does not name its host. The choice is this phone's until it is sent as
// one decision, as the next mission is after a success. Tonoja's seat is not in it: with two
// players the two of them agree it (one proposes, the other answers in the usual decision
// panel), and everyone else reads what they agreed. What may be chosen, what is agreed and the
// reason a control cannot be used are the server's (g.setup). ui.setup is this phone's choice
// while it is being made.
const SETUP_PROFILE = ['label[for="name"]', "#name", "[data-avrana-global]", ".lobby .intro"];
function setupOf(st) { const g = st && st.game; return g && g.stage === "setup" ? g : null; }
function setupChoice(g) {
  // What is offered, until this phone chooses otherwise. A choice does not outlive its table
  // (leaveSetup, onWelcome), and one the server no longer offers is dropped.
  const open = id => g.setup.missions.some(m => m.id === id && m.enabled);
  if (ui.setup && !open(ui.setup.mission)) ui.setup = null;
  if (!ui.setup) ui.setup = {mission:g.setup.mission, timed:g.setup.timed, tonoja_position:g.setup.tonoja_seat ?? g.setup.tonoja_position};
  return ui.setup;
}
// A seat for Tonoja in the lobby's own words ("after both players").
function seatWords(position) {
  const seat = $("tonoja-position").querySelector(`option[value="${position}"]`);
  return seat ? seat.textContent.toLowerCase() : `in seat ${position}`;
}
function choose(patch) {
  const g = setupOf(ST);
  if (!g) { conn.send({t:"settings",patch}); return; }
  Object.assign(setupChoice(g), patch); draw();
}
function setupWords(p) {
  // The clock is the table's setting and the lobby's own label says what it is for: mission 16.
  const clock = !p.timed ? "" : p.mission === 16 ? " against the clock" : " (clock on, for mission 16 only)";
  return `mission ${p.mission}${clock}`;
}
function leaveSetup() {
  ui.setup = null;
  for (const id of ["setup-box", "setup-why"]) { const n = $(id); if (n) n.remove(); }
  for (const n of document.querySelectorAll("[data-setup-hid]")) { n.hidden = false; delete n.dataset.setupHid; }
  document.querySelector('label[for="tonoja-position"]').hidden = $("tonoja-position").hidden = false;
}
function drawSetup(st, g) {
  const focusKey = document.activeElement?.dataset?.key;
  const mine = mayMoveOn(g), choice = setupChoice(g), wait = g.setup.waiting;
  for (const n of SETUP_PROFILE.map(q => document.querySelector(q))) if (n && !n.hidden) { n.hidden = true; n.dataset.setupHid = "1"; }
  $("lobby-form").hidden = !mine || Boolean(g.proposal);
  $("lobby-actions").hidden = true;
  // A mission that cannot be chosen says why in the server's own sentence: in its option where
  // that fits, and in words on the page, one line for each reason, under the list.
  const shut = g.setup.missions.filter(m => !m.enabled), label = m => `${m.id>32?"Deep dive":"Mission"} ${m.id}`;
  choices($("mission"), g.setup.missions.map(m => ({value:m.id,text:label(m) + (m.enabled ? "" : ` · ${m.reason && m.reason.length <= 60 ? m.reason : "unavailable"}`),disabled:!m.enabled})), choice.mission);
  let whyNot = $("setup-why");
  if (!whyNot) {
    whyNot = el("details"); whyNot.id = "setup-why";
    const head = el("summary", undefined, "muted"); head.style.cssText = "min-height:44px;display:flex;align-items:center;cursor:pointer";
    whyNot.append(head); $("mission").after(whyNot);
  }
  whyNot.hidden = !shut.length;
  whyNot.firstChild.textContent = `${shut.length} unavailable · why`;
  while (whyNot.children.length > 1) whyNot.lastChild.remove();
  for (const reason of new Set(shut.map(m => m.reason))) whyNot.append(why(`${shut.filter(m => m.reason === reason).map(m => m.id).join(", ")} · ${reason || "unavailable"}`));
  $("timed").checked = choice.timed;
  // The lobby's seat control belongs to a standalone lobby. Here the seat is the two players'
  // (below), never part of what the setup sends.
  document.querySelector('label[for="tonoja-position"]').hidden = $("tonoja-position").hidden = true;
  ui.fromSetup = true;
  const seatOpen = g.setup.tonoja && g.setup.tonoja_seat === null;
  const text = g.away.length ? `Waiting for ${names(g.away)} to reconnect.`
    : g.proposal ? (mustAnswer(g) ? `Your answer is needed: ${question(g)}` : `Crew decision · waiting for ${names(stillAsked(g))}`)
    : seatOpen ? (g.me ? "Agree where Tonoja sits" : "Waiting for the two players to agree where Tonoja sits")
    : !hostOwned(g) ? "Agree on the mission to open on"
    : amHost() ? "Choose the mission to open on" : `Waiting for ${theHost()} (Party Host) to choose the mission`;
  $("status").textContent = (g.me ? "" : "Watching · ") + text;
  $("status").classList.toggle("urgent", Boolean(g.proposal && mustAnswer(g)));
  $("roster").replaceChildren();
  for (const seat of g.seats) {
    const p = st.players.find(q => q.pid === seat) || {}, row = el("div",undefined,"person"), avatar = el("span",p.avatar,"avatar");
    if (p.pid) Hub.fillAvatar(avatar,p);
    row.append(avatar, el("strong",name(seat),"name"), el("span", g.away.includes(seat) ? "Away" : "Aboard", "muted"));
    $("roster").append(row);
  }
  $("lobby-reason").textContent = mine && wait && !g.proposal ? wait : hostOwned(g)
    ? (amHost() ? "You are the Party Host: you choose. Nothing is dealt until you do." : "Nothing is dealt until the Party Host has chosen.")
    : `Nothing is dealt until the whole crew agrees.${g.lifecycle_transitional ? " This Party does not tell EXPO who its Host is yet, so the crew decides for now." : ""}`;
  let box = $("setup-box");
  if (!box) { box = el("div", undefined, "actions"); box.id = "setup-box"; $("roster").before(box); }      // above the crew list: in view on a short phone
  box.replaceChildren();
  if (g.setup.tonoja) {
    // Public, for every phone: the seat the two players agreed, or that none is agreed yet.
    const agreed = g.setup.tonoja_seat;
    const line = el("p", agreed === null ? "Tonoja’s seat is not agreed yet. The two players decide it."
      : `Tonoja sits ${seatWords(agreed)} · agreed by ${names(g.seats)}.`, "muted");
    line.dataset.key = "tonoja-seat"; line.style.cssText = "flex-basis:100%;margin:0"; box.append(line);
  }
  if (g.proposal) box.append(decisionNode(g));
  else {
    if (g.setup.tonoja && g.me) {
      // A seated player proposes a seat; the other player is then asked, in the decision panel.
      const pick = el("select"); pick.dataset.key = "seat-choice"; pick.setAttribute("aria-label", "Tonoja’s seat");
      choices(pick, [...$("tonoja-position").options].map(o => ({value:o.value, text:o.textContent})), choice.tonoja_position);
      pick.onchange = () => { choice.tonoja_position = Number(pick.value); };
      const stop = g.setup.seat_waiting;
      box.append(pick, button(g.setup.tonoja_seat === null ? "Propose Tonoja’s seat" : "Propose another seat",
        () => propose("tonoja_seat", {position:Number(pick.value)}), "seat-propose", Boolean(stop), stop || ""));
      if (stop && !(mine && stop === wait)) { const said = why(stop); said.style.flexBasis = "100%"; box.append(said); }   // else it is the line under the crew list
    }
    if (mine) {
      box.append(button(`Deal mission ${choice.mission}`, () => lifecycle({kind:"setup",mission:choice.mission,timed:choice.timed}),
        "setup-confirm", Boolean(wait), wait || "", "btn-primary"));
    }
  }
  if (!g.proposal && st.party_round && amHost()) box.append(endButton("End EXPO for everyone", "end-expo", "quiet"));
  const back = focusKey && box.querySelector(`[data-key="${CSS.escape(focusKey)}"]`);
  if (back && !back.disabled && document.activeElement !== back) back.focus({preventScroll:true});
}

// A new moment at the table: drop a selection made for the last one, and bring up the cards
// that are about to be played (Tonoja's, for the captain on Tonoja's turn).
function syncTurn(g) {
  const key = [g.attempt, g.stage, g.trick_number, g.turn, g.trick.length].join(":");
  if (key === ui.turnKey) return;
  ui.turnKey = key; ui.selected = null;
  if (!g.me) ui.handView = g.tonoja.length ? "tonoja" : "none";
  else ui.handView = g.tonoja.length && g.turn === "tonoja" && g.captain === g.me.seat
    && ["before_trick","in_trick"].includes(g.stage) ? "tonoja" : "mine";
}

function question(g) {
  const p = g.proposal.payload;
  return {begin:"Begin the mission without passing cards?",
    distress:`Activate distress and pass one color card ${p.direction}? This adds one recorded attempt to the mission.`,
    assign:p.task==="all"?`Give all tasks to ${name(p.owner)}?`:`Give this task to ${name(p.owner)}?`,
    retry:p.keep?"Retry with the same tasks?":"Retry with fresh tasks?",
    next:`Begin mission ${p.mission}?`, end:"End this table?", setup:`Open on ${setupWords(p)}?`,
    tonoja_seat:`Seat Tonoja ${seatWords(p.position)}?`}[p.kind];
}
function mustAnswer(g) {
  const asked = g.proposal.recipient;
  return Boolean(g.me && !g.proposal.votes.includes(g.me.seat) && !g.away.length && (!asked || asked === g.me.seat));
}
function stillAsked(g) {
  const asked = g.proposal.recipient;
  return asked ? [asked] : g.seats.filter(s => s !== "tonoja" && !g.proposal.votes.includes(s));
}

function statusText(g) {
  if (g.away.length) return `Waiting for ${names(g.away)} to reconnect. Your table is preserved.`;
  if (g.proposal) {
    if (mustAnswer(g)) return `Your answer is needed: ${g.proposal.recipient ? `${name(g.captain)} offers you all tasks.` : question(g)}`;
    return `Crew decision · waiting for ${names(stillAsked(g))}`;
  }
  if (g.result) return g.result.status === "success" ? "Mission complete" : g.result.status === "failed" ? "Mission failed" : "Table ended";
  const mine = seat => g.me && (seat === g.me.seat || (seat === "tonoja" && g.captain === g.me.seat));
  if (g.stage === "allocation") {
    if (g.mission.allocation === "free") return "Agree who takes each task";
    if (["one","captain_one"].includes(g.mission.allocation)) return g.mission.allocation === "captain_one" ? `${name(g.captain)} decides who takes the tasks` : "Agree who takes all the tasks";
    return mine(g.selector) ? (g.selector === "tonoja" ? "Your turn · choose for Tonoja" : "Your turn · select a task") : `${name(g.selector)} selects a task`;
  }
  if (g.stage === "prediction") return "Commit the required trick predictions";
  if (g.stage === "assistance") {
    if (!hostOwned(g)) return "Tasks assigned · the crew agrees to begin, or asks for distress";
    if (ui.grace > 0) return amHost() ? `The crew may ask for distress · you can begin in ${ui.grace}` : `Want distress? Ask now · ${theHost()} can begin in ${ui.grace}`;
    return amHost() ? "Crew ready · begin when you are" : `Waiting for ${theHost()} (Party Host) to begin`;
  }
  if (g.stage === "passing") return g.me?.pass_locked ? "Your pass is sealed · waiting for the crew" : "Choose a color card to pass · choices stay sealed";
  const verb = g.trick.length ? "play" : "lead";
  if (g.turn === "tonoja") return mine("tonoja") ? `Your turn · ${verb} for Tonoja` : `${name(g.captain)} to ${verb} for Tonoja`;
  return mine(g.turn) ? `Your turn to ${verb}` : `${name(g.turn)} to ${verb}`;
}

function drawStatus(g) {
  const text = (g.me ? "" : "Watching · ") + statusText(g);
  if ($("status").textContent !== text) $("status").textContent = text;
  $("status").classList.toggle("urgent", Boolean(g.proposal && mustAnswer(g)));
}

function drawHead(g) {
  $("mission-title").textContent = `Mission ${g.mission.id}`;
  $("mission-title").title = `Attempt ${g.attempts||1}`;
  $("trick-count").textContent = `Trick ${g.trick_number} / ${g.planned_tricks}`;
}

function pill(status) {
  const map = {failed:["× Failed","failed"], satisfied:["✓ Done","done"], pending:["○ Pending","pending"], unassigned:["Open","open"]};
  const [text, cls] = map[status] || [status, "pending"];
  return el("span", text, "pill " + cls);
}

// The two lines under the mission: what matters most first (a failure, then this player's own
// tasks). The rest is one tap away in Tasks.
function drawObjectives(g) {
  const box = $("objectives"); box.replaceChildren();
  const rank = t => t.status === "failed" ? 0 : (g.me && t.owner === g.me.seat && t.status !== "satisfied") ? 1 : t.status === "pending" ? 2 : t.status === "unassigned" ? 3 : 4;
  const rows = [];
  if (g.mission.objective) {
    const status = g.result ? (g.result.status === "success" ? "satisfied" : g.tasks.some(t => t.status === "failed") ? "pending" : "failed") : "pending";
    rows.push({text: OBJECTIVES[g.mission.objective], status, who: null});
  }
  for (const t of [...g.tasks].sort((a,b) => rank(a) - rank(b))) rows.push({text: t.text, status: t.status, who: t.owner});
  if (!rows.length) rows.push({text: "Complete every assigned task together.", status: "pending", who: null});
  // One target for the whole panel (a row alone is too thin for a thumb): it opens the tasks.
  const open = el("button", undefined, "objectives-open"); open.type = "button"; open.dataset.key = "objectives";
  open.onclick = e => openSheet("tasks", e.currentTarget);
  const said = [];
  for (const r of rows.slice(0, 2)) {
    const row = el("span", undefined, "objective " + r.status);
    const text = el("span", undefined, "objective-text");
    if (r.who) text.append(el("b", name(r.who) + " · "));
    text.append(document.createTextNode(r.text));
    row.append(text, pill(r.status));
    said.push(`${r.who ? name(r.who) + ": " : ""}${r.text}, ${r.status}`);
    open.append(row);
  }
  open.setAttribute("aria-label", `${said.join(". ")}.${rows.length > 2 ? ` And ${rows.length - 2} more.` : ""} Open tasks.`);
  box.append(open);
}

function exposureOf(g, seat) { return g.exposures.find(e => e.seat === seat); }
function exposureMark(e) {
  const [s,r] = e.card.split(":");
  const meaning = {highest:"▲", lowest:"▼", only:"●"}[e.assertion] || "?";
  return `${r}${symbols[s]}${meaning}`;
}

function drawCrew(g) {
  const strip = $("seats"); strip.replaceChildren();
  strip.style.setProperty("--n", g.seats.length);
  strip.classList.toggle("tight", g.seats.length > 3);
  const host = hostSeat(g);
  for (const seat of g.seats) {
    const tile = el("button", undefined, "seat" + (seat === g.turn && !g.result && ["before_trick","in_trick"].includes(g.stage) ? " active" : "")
      + (g.me && seat === g.me.seat ? " me" : "") + (g.away.includes(seat) ? " away" : ""));
    tile.type = "button"; tile.dataset.key = "seat:" + seat;
    tile.onclick = e => openSheet("crew", e.currentTarget);
    const top = el("span", undefined, "seat-name");
    if (seat === g.captain) top.append(el("span", "♛", "crown"));
    top.append(el("b", name(seat)));
    const roles = [seat === g.captain ? "Captain" : null, seat === host ? "Party Host" : null].filter(Boolean);
    const cards = g.hand_counts[seat], tricks = g.trick_counts[seat];
    const e = exposureOf(g, seat);
    tile.append(top);
    if (roles.length && g.seats.length <= 3) tile.append(el("span", roles.join(" · "), "seat-role"));
    tile.append(el("span", g.seats.length > 3 ? `${cards}c · ${tricks}t` : `${cards} cards · ${tricks} trick${tricks===1?"":"s"}`, "seat-count"));
    if (e) tile.append(el("span", exposureMark(e), "seat-sonar"));
    tile.setAttribute("aria-label", `${name(seat)}${roles.length ? ", " + roles.join(", ") : ""}: ${cards} cards, ${tricks} tricks${g.away.includes(seat) ? ", away" : ""}. Open crew.`);
    strip.append(tile);
  }
}

// ---- the stage: the trick during play, the decision or preparation that is waiting otherwise ----
function drawStage(g) {
  const stage = $("stage"); stage.replaceChildren();
  let node;
  if (g.proposal && !g.result) node = decisionNode(g);
  else if (g.result || ["before_trick","in_trick"].includes(g.stage)) node = trickNode(g);
  else if (g.stage === "allocation") node = allocationNode(g);
  else if (g.stage === "prediction") node = predictionNode(g);
  else if (g.stage === "assistance") node = assistanceNode(g);
  else node = passingNode(g);
  stage.append(node);
}

function decisionNode(g) {
  const box = el("section", undefined, "decision"); box.setAttribute("aria-label", "Crew decision");
  const asked = g.proposal.recipient;
  if (asked) box.append(el("h2","Captain’s offer"), el("p",`${name(g.captain)} offers all tasks to ${name(asked)}.`), el("p",`Only ${name(asked)} can accept or decline.`,"muted"));
  else box.append(el("h2","Crew decision"), el("p",question(g)), el("p",`${g.proposal.votes.length} / ${g.seats.filter(s=>s!=="tonoja").length} confirmed · everyone must agree`,"muted"));
  if (mustAnswer(g)) {
    const row = el("div",undefined,"choice-row");
    row.append(button(asked?"Accept":"Agree",()=>send("confirm",{yes:true}),"agree",false,"","btn-primary"),button("Decline",()=>send("confirm",{yes:false}),"decline"));
    box.append(row);
  } else if (!g.away.length) box.append(why(`Waiting for ${names(stillAsked(g))}.`));
  const begin = beginWhy(g);
  if (begin) box.append(begin);
  return box;
}

function slot(g, seat, card, cls, note) {
  const s = el("div", undefined, "slot " + cls + (g.me && seat === g.me.seat ? " me" : ""));
  s.append(el("span", name(seat), "slot-name"));
  if (card) s.append(cardNode(card));
  else s.append(el("div", note || "", "card-empty"));
  return s;
}

function trickNode(g) {
  const box = el("div", undefined, "trick-stage");
  const row = el("div", undefined, "trick"); row.id = "trick";
  row.style.setProperty("--n", g.seats.length);
  const caption = el("div", undefined, "stage-caption");
  const order = from => g.seats.slice(g.seats.indexOf(from)).concat(g.seats.slice(0, g.seats.indexOf(from)));
  if (!g.trick.length && g.last_trick) {
    // The trick that just ended stays on the table until the next card is played.
    const t = g.last_trick;
    for (const p of t.plays) row.append(slot(g, p.seat, p.card, p.seat === t.winner ? "winner" : "done"));
    caption.append(el("strong", `Trick ${t.index} · ${name(t.winner)} won`));
    if (!g.result) caption.append(el("span", `${name(g.turn)} leads trick ${g.trick_number}`));
  } else if (!g.trick.length) {
    for (const seat of order(g.leader)) row.append(slot(g, seat, null, seat === g.turn && !g.result ? "active" : "idle", seat === g.turn && !g.result ? "To lead" : ""));
    caption.append(el("strong", g.result ? "No trick was played" : "Awaiting the opening card"));
  } else {
    const played = new Map(g.trick.map(p => [p.seat, p.card]));
    for (const seat of order(g.leader)) row.append(slot(g, seat, played.get(seat), played.has(seat) ? "done" : seat === g.turn ? "active" : "idle", seat === g.turn ? "To play" : ""));
    caption.append(el("strong", "Current trick"), el("span", `Waiting for ${g.turn === "tonoja" ? `${name(g.captain)} (Tonoja)` : name(g.turn)}…`));
  }
  box.append(row, caption);
  return box;
}

function allocationNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Task selection");
  const mode = g.mission.allocation, open = g.tasks.filter(t => !t.owner);
  const live = g.me && !g.away.length;
  const head = el("div", undefined, "prep-head");
  head.append(el("h2", g.mission.fixed ? "Assign the fixed tasks" : `Assign the tasks · difficulty ${g.mission.target}`), el("span", `${g.tasks.length - open.length} of ${g.tasks.length} taken`, "muted"));
  box.append(head);
  const list = el("div", undefined, "pick-list");
  const said = new Set();       // why the selecting seat cannot take a task: said once, not per task
  for (const task of open) {
    const item = el("article", undefined, "pick");
    item.append(el("div", task.text, "pick-text"));
    if (live && ["normal","skip_captain"].includes(mode)) {
      const mineToTake = g.controller === g.me.seat, refused = g.me.task_reasons[task.id] || "";
      item.append(button(g.selector === "tonoja" && mineToTake ? "Tonoja takes it" : "Take this task", () => send("choose_task",{task:task.id}), "task:"+task.id,
        Boolean(refused), refused));
      if (mineToTake && refused) said.add(refused);
    } else if (live && mode === "free") {
      const sel = ownerSelect("owner:"+task.id, task.eligible_owners);
      const row = el("div", undefined, "choice-row");
      row.append(sel, button("Propose owner", () => propose("assign",{task:task.id,owner:sel.value}), "assign:"+task.id));
      item.append(row);
    }
    list.append(item);
  }
  box.append(list);
  for (const reason of said) box.append(why(reason));
  if (!live) return box;
  const actions = el("div", undefined, "choice-row");
  if (["normal","skip_captain"].includes(mode)) {
    if (g.controller === g.me.seat) {
      const refused = g.me.pass_task_reason || "";
      actions.append(button("Pass selection", () => send("pass_task"), "pass-task", Boolean(refused), refused));
      if (refused) box.append(why(refused));
    } else box.append(why(`${name(g.controller)} chooses${g.selector === "tonoja" ? " for Tonoja" : ""} now.`));
  }
  if (["one","captain_one"].includes(mode)) {
    // An owner the server would refuse cannot be chosen; with nobody left, or no right to offer,
    // the button is unavailable too.
    const refusedOwners = g.me.offer_owner_reasons;
    const refused = g.me.offer_reason || (g.seats.every(s => refusedOwners[s]) ? refusedOwners[g.seats[0]] : "");
    const owner = ownerSelect("all-owner", g.seats, g.me.offer_reason ? {} : refusedOwners);
    actions.append(owner, button("Offer all tasks", () => propose("assign",{owner:owner.value,task:"all"}), "all-tasks", Boolean(refused), refused));
    if (refused) box.append(why(refused));
    else for (const s of g.seats.filter(s => refusedOwners[s])) box.append(why(`${name(s)}: ${refusedOwners[s]}`));
  }
  if (mode === "volunteer") {
    if (g.controller === g.me.seat) {
      actions.append(button("Yes · take the tasks", () => send("volunteer",{yes:true}), "volunteer-yes", Boolean(g.me.volunteer_reasons.yes), g.me.volunteer_reasons.yes || "", "btn-primary"),
        button("No", () => send("volunteer",{yes:false}), "volunteer-no", Boolean(g.me.volunteer_reasons.no), g.me.volunteer_reasons.no || ""));
      for (const reason of new Set([g.me.volunteer_reasons.yes, g.me.volunteer_reasons.no].filter(Boolean))) box.append(why(reason));
    } else box.append(why(`${name(g.controller)} is asked to volunteer.`));
  }
  if (actions.children.length) box.append(actions);
  return box;
}

function predictionNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Predictions");
  box.append(el("h2", "Predict your tricks"));
  let mine = 0;
  const said = new Set();       // why a prediction cannot be locked now: said once, not per task
  for (const task of g.tasks) {
    if (!(task.prediction_required && !task.prediction_committed && g.me && (task.owner === g.me.seat || (task.owner === "tonoja" && g.captain === g.me.seat)))) continue;
    mine++;
    const item = el("article", undefined, "pick");
    item.append(el("div", (task.owner === "tonoja" ? "Tonoja · " : "") + task.text, "pick-text"));
    const form = el("div", undefined, "choice-row"), input = el("input");
    input.type = "number"; input.min = "0"; input.max = String(g.planned_tricks); input.step = "1"; input.value = "0";
    input.inputMode = "numeric"; input.dataset.key = "predict:"+task.id; input.setAttribute("aria-label","Predicted tricks");
    const refused = g.me.predict_reasons[task.id] || "";
    form.append(input, button("Lock prediction", () => send("predict",{task:task.id,count:Number(input.value)}), "lock:"+task.id, Boolean(refused), refused, "btn-primary"));
    item.append(form); box.append(item);
    if (refused) said.add(refused);
  }
  for (const reason of said) box.append(why(reason));
  if (!mine) box.append(why("Waiting for the crew to lock their predictions."));
  else box.append(why("A prediction cannot be changed once locked."));
  return box;
}

function assistanceNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Before the first trick");
  box.append(el("h2", "Ready to dive"));
  const begin = beginWhy(g);            // first, so a short screen shows it without scrolling
  if (begin) box.append(begin);
  const begins = !hostOwned(g) ? "Beginning needs the whole crew to agree."
    : amHost() ? "You begin the mission as Party Host, below."
    : `${theHost()} begins the mission as Party Host. Nobody has to confirm.`;
  box.append(el("p", `${g.tasks.length ? "Every task has an owner." : "This mission uses the shared objective instead of task cards."} ${begins}`));
  if (g.me && !g.away.length && g.seats.every(s => s !== "tonoja")) {
    const row = el("div", undefined, "choice-row");
    row.append(button("Distress ← left", () => propose("distress",{direction:"left"}), "distress-left"),
      button("Distress → right", () => propose("distress",{direction:"right"}), "distress-right"));
    box.append(el("h3", "Request distress", "prep-sub"), row, why(`Any crew member may ask before the first trick: everyone passes one color card that way, and the mission records one more attempt. Distress is the crew’s decision, so the whole crew must agree to it.${hostOwned(g) ? " The Party Host cannot begin while a request is waiting." : ""}`));
  }
  return box;
}

function passingNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Distress");
  box.append(el("h2", "Distress signal"), el("p", "Everyone passes one color card to the next crew member. Choices stay sealed until the whole crew has chosen."));
  box.append(why(!g.me ? "The crew is choosing." : g.me.pass_locked ? "Your pass is sealed. Waiting for the crew." : "Choose a color card from your hand, then pass it."));
  return box;
}

function drawTabs(g) {
  const done = g.tasks.filter(t => t.status === "satisfied").length;
  $("tab-tasks").textContent = g.tasks.length ? `Tasks ${done}/${g.tasks.length}` : "Tasks";
  const can = g.me && Object.keys(g.me.communication_options).length > 0 && !g.proposal;
  $("tab-sonar").textContent = "Sonar";
  $("tab-sonar").parentElement.classList.toggle("ready", Boolean(can));
  $("tab-sonar").parentElement.setAttribute("aria-label", can ? "Sonar: you can communicate now" : "Sonar");
}

// ---- the hand: always on screen ----------------------------------------------------------------
function handState(g) {
  // Which cards are showing, and for each the server's reason it cannot be chosen now, if any
  // (AVR-263). A watcher has no reasons and can choose nothing.
  const state = c => { const reason = g.me?.card_reasons[c] || ""; return {card:c, enabled:Boolean(g.me) && !reason, reason}; };
  if (ui.handView === "tonoja") return g.tonoja.map(c => c && state(c));
  return g.me ? g.me.hand.map(state) : [];
}

function drawHand(g) {
  const sw = $("hand-switch"); sw.replaceChildren();
  sw.hidden = !(g.tonoja.length && g.me);
  if (!sw.hidden) {
    for (const [view, label, count] of [["mine","Yours",g.me.hand.length],["tonoja","Tonoja",g.tonoja.filter(Boolean).length]]) {
      const b = el("button", `${label} ${count}`, "switch" + (ui.handView === view ? " on" : "")); b.type = "button";
      b.dataset.key = "hand-" + view; b.setAttribute("aria-pressed", String(ui.handView === view));
      b.onclick = () => { ui.handView = view; ui.selected = null; draw(); };
      sw.append(b);
    }
  }
  const cards = handState(g);
  $("hand-title").textContent = ui.handView === "tonoja" ? "Tonoja · face up" : g.me ? "Your hand" : "Watching";
  $("hand-title").classList.toggle("sr", !sw.hidden);       // the switch already names both hands
  const hand = $("hand"); hand.replaceChildren();
  const n = cards.length;
  hand.style.setProperty("--cols", n <= 7 ? Math.max(n, 5) : Math.ceil(n / 2));
  hand.classList.toggle("two-rows", n > 7);
  if (ui.selected && !cards.some(c => c && c.card === ui.selected && c.enabled)) ui.selected = null;
  for (const c of cards) {
    if (!c) { hand.append(el("div", "", "card-empty gone")); continue; }
    const node = cardNode(c.card, () => { ui.selected = ui.selected === c.card ? null : c.card; draw(); }, c.enabled, c.reason);
    node.setAttribute("aria-pressed", String(ui.selected === c.card));
    hand.append(node);
  }
  if (!n) hand.append(el("p", g.me ? "No cards left." : "Spectators see no hands.", "muted"));
  let reason = "";
  if (g.me) {
    // When no card showing can be chosen the line says why, in the server's words; otherwise it
    // says what to do.
    const lead = g.trick[0]?.card.split(":")[0];
    const shown = cards.filter(Boolean);
    const passing = g.stage === "passing" && ui.handView !== "tonoja";
    if (shown.length && shown.every(c => c.reason && c.reason === shown[0].reason)) reason = shown[0].reason;
    else if (!shown.length) reason = (passing ? "" : g.me.play_reason) || "";
    else if (passing) reason = "Choose one color card";
    else reason = lead ? `Follow ${lead === "submarine" ? "submarines" : lead} if you can` : "Lead any card";
  }
  $("hand-reason").textContent = reason;
}

// ---- the dock: table control (Party Host) on the left, this player's own action on the right ----
function zone(title, sub) {
  const z = el("div", undefined, "dock-zone");
  const label = el("div", undefined, "dock-label");
  label.append(el("b", title)); if (sub) label.append(el("span", ` (${sub})`));
  z.append(label);
  return z;
}

function tableZone(g) {
  const begin = g.stage === "assistance";
  if (hostOwned(g)) {
    const z = zone("Party Host", "table control"); z.id = "dock-host";
    if (!amHost()) z.append(el("p", begin ? `Waiting for ${theHost()} to begin` : `${hostName() || "The Party Host"} runs the table`, "dock-note"));
    else if (begin) {
      // Closed exactly while the server gives a reason; `begin_at` only counts the wait down.
      const refused = stepReason(g, "begin");
      z.append(button(ui.grace > 0 ? `Begin in ${ui.grace}` : "Begin mission", () => lifecycle({kind:"begin"}), "begin", Boolean(refused), refused, "btn-primary"));
    } else z.append(endButton("End EXPO", "end"));
    return z;
  }
  // The crew decides: a standalone table, or a Party that does not say who its host is.
  const z = zone("Crew", g.lifecycle_transitional ? "decides for now" : "decides together"); z.id = "dock-host";
  if (begin && g.me) {
    const refused = stepReason(g, "begin");
    z.append(button("Begin without passing", () => propose("begin"), "begin", Boolean(refused), refused, "btn-primary"));
  } else if (begin) z.append(el("p", "The crew agrees to begin", "dock-note"));
  else if (!ST.party_round) z.append(button("End table", () => propose("end"), "end", !g.me || blocked(g)));
  else if (amHost()) z.append(endButton("End EXPO", "end"));
  else z.append(el("p", `${hostName() || "The Party Host"} ends EXPO`, "dock-note"));
  return z;
}

function actionZone(g) {
  const tonoja = ui.handView === "tonoja";
  const z = zone(!g.me ? "Watching" : g.me.seat === g.captain ? (tonoja ? "Captain · Tonoja" : "Captain") : "Crew member", g.me ? "your role in the game" : "no seat");
  z.id = "dock-action";
  const passing = g.stage === "passing" && !tonoja;
  const card = ui.selected;
  const text = card ? `${passing ? "Pass" : "Play"} ${cardLabel(card)}` : passing ? "Pass card" : "Play card";
  const b = button(text, () => { const c = ui.selected; ui.selected = null; send(passing ? "pass_card" : "play_card", {card:c}); },
    passing ? "pass" : "play", !card, card ? "" : "Choose a card first.", "btn-primary");
  b.setAttribute("aria-label", text);
  z.append(b);
  return z;
}

function drawDock(g) {
  const dock = $("dock"); dock.replaceChildren();
  dock.classList.toggle("ended", Boolean(g.result && ui.resultHidden));
  if (g.result && ui.resultHidden) {
    // The result never leaves the screen: put away to look at the table, it holds the dock.
    const label = g.result.status === "success" ? "Mission complete" : g.result.status === "failed" ? "Mission failed" : "Table ended";
    const next = mayMoveOn(g) ? (g.result.status === "success" ? " and next mission" : g.result.status === "failed" ? " and retry" : "") : "";
    dock.append(button(`${label} · show result${next}`, () => { ui.resultHidden = false; draw(); focusResult(); }, "show-result", false, "", "btn-primary wide " + g.result.status));
    return;
  }
  dock.append(tableZone(g), actionZone(g));
}

// ---- mission result: takes over the screen ------------------------------------------------------
function focusResult() {
  const first = $("result").querySelector("button:not(:disabled), select") || $("result-title");
  if (first) first.focus({preventScroll:true});
}

function drawResult(g, st) {
  const box = $("result");
  const key = g.result ? `${g.attempt}:${g.result.status}` : "";
  const fresh = key !== ui.resultKey;
  if (fresh) { ui.resultKey = key; ui.resultHidden = false; if (key) { ui.sheet = null; ui.selected = null; } }
  box.hidden = !g.result || ui.resultHidden;
  box.replaceChildren();
  if (box.hidden) return;
  const r = g.result, ok = r.status === "success";
  box.className = "result " + r.status;
  const card = el("div", undefined, "result-card");
  const title = el("h2", ok ? "MISSION COMPLETE" : r.status === "failed" ? "MISSION FAILED" : "TABLE ENDED"); title.id = "result-title"; title.tabIndex = -1;
  const reason = el("p", r.reason, "result-reason"); reason.id = "result-reason";
  card.append(el("div", ok ? "✓" : "×", "result-mark"), title, el("p", ok ? "Together, you did it." : r.status === "failed" ? "Dive again." : "", "result-sub"), reason);
  // What the server's state says about how it ended. Nothing is inferred here: a failed task is
  // one the server marked failed, and the trick is the last one it resolved (AVR-246 will add
  // the triggering play; `cause` is shown as soon as the result carries it).
  const facts = el("div", undefined, "result-facts");
  for (const t of g.tasks.filter(t => t.status === "failed")) {
    const fact = el("p", undefined, "fact");
    fact.append(el("b", `${name(t.owner)}’s task failed`));
    if (t.text !== r.reason) fact.append(document.createTextNode(` · ${t.text}`));
    facts.append(fact);
  }
  if (typeof r.cause === "string") facts.append(el("p", r.cause, "fact"));
  if (g.last_trick) {
    const t = g.last_trick;
    facts.append(el("p", `Ended after trick ${t.index} of ${g.planned_tricks}, won by ${name(t.winner)}.`, "fact"));
    const row = el("div", undefined, "result-trick");
    for (const p of t.plays) { const cell = el("div", undefined, "mini" + (p.seat === t.winner ? " winner" : "")); cell.append(cardNode(p.card), el("span", name(p.seat))); row.append(cell); }
    facts.append(row);
  }
  if (facts.children.length) card.append(facts);
  const controls = el("div", undefined, "result-actions");
  if (g.proposal) controls.append(decisionNode(g));
  else if (mayMoveOn(g)) {
    // Retry and Next are closed exactly while the server gives a reason, and say it in words.
    if (hostOwned(g)) controls.append(el("p", "You are the Party Host: you choose what happens next.", "result-who"));
    if (r.status === "failed") {
      const refused = stepReason(g, "retry");
      controls.append(button("Retry same tasks", () => lifecycle({kind:"retry",keep:true}), "retry-same", Boolean(refused), refused), button("Retry new tasks", () => lifecycle({kind:"retry",keep:false}), "retry-new", Boolean(refused), refused, "btn-primary"));
      if (refused) controls.append(why(refused));
    }
    if (ok) {
      const refused = stepReason(g, "next");
      const next = el("select"); next.dataset.key = "next-mission"; next.setAttribute("aria-label", "Next mission");
      const open = (st.missions||[]).filter(m => m.enabled);
      choices(next, open.map(m => ({value:m.id,text:`Mission ${m.id}`})), open.find(m => m.id > g.mission.id)?.id || g.mission.id);
      controls.append(next, button("Next mission", () => lifecycle({kind:"next",mission:Number(next.value)}), "next", Boolean(refused), refused, "btn-primary"));
      if (refused) controls.append(why(refused));
    }
  } else if (g.away.length) controls.append(why(`Waiting for ${names(g.away)} to reconnect.`));
  else controls.append(el("p", hostOwned(g) ? `Waiting for ${theHost()} (Party Host) to choose what’s next.` : "The crew decides what’s next.", "result-who waiting"));
  // Ending EXPO: the Party Host's in a Party; the crew's own decision at a standalone table.
  if (!g.proposal) {
    if (ST.party_round ? amHost() : false) controls.append(endButton("End EXPO for everyone", "end-expo", "quiet"));
    else if (!ST.party_round && g.me && !g.away.length) controls.append(button("End table", () => propose("end"), "end-table", false, "", "quiet"));
  }
  if (ok && window.Brag && g.me) controls.append(Brag.button(() => ({title:"EXPO",icon:"🌊",winner:{name:"The crew",avatar:"🌊"},headline:`Mission ${g.mission.id} completed together`,beaten:[]})));
  controls.append(button("Look at the table", () => { ui.resultHidden = true; draw(); focusRef('[data-key="show-result"]', $("mission-title")); }, "review", false, "", "quiet"));
  card.append(controls);
  box.append(card);
  if (fresh) focusResult();
}

// ---- sheets: everything that is not this turn ---------------------------------------------------
function drawSheet(g, st) {
  const sheet = $("sheet");
  if (ui.sheet && !g && !["menu","help"].includes(ui.sheet)) ui.sheet = null;
  sheet.hidden = !ui.sheet;
  for (const tab of document.querySelectorAll(".tab")) tab.setAttribute("aria-expanded", String(ui.sheet === tab.dataset.sheet));
  if (!ui.sheet) return;
  $("sheet-title").textContent = ui.sheet === "sonar" && g ? `Sonar · ${g.communication}` : SHEETS[ui.sheet];
  const body = $("sheet-body"); body.replaceChildren();
  ({crew:crewSheet, tasks:tasksSheet, sonar:sonarSheet, history:historySheet, menu:menuSheet, help:helpSheet})[ui.sheet](body, g, st);
}

function crewSheet(body, g) {
  const host = hostSeat(g), hostNamed = hostName();
  for (const seat of g.seats) {
    const row = el("article", undefined, "crew-row" + (seat === g.turn ? " active" : ""));
    const roles = [g.me && seat === g.me.seat ? "You" : null, seat === g.captain ? "Captain" : null,
      seat === host ? "Party Host" : null,
      seat === "tonoja" ? `played by ${name(g.captain)}` : null, g.away.includes(seat) ? "Away" : null].filter(Boolean);
    const head = el("div", undefined, "crew-head"); head.append(el("strong", name(seat)), el("span", roles.join(" · "), "muted"));
    const owned = g.tasks.filter(t => t.owner === seat);
    row.append(head, el("p", `${g.hand_counts[seat]} cards · ${g.trick_counts[seat]} tricks · ${owned.length} task${owned.length===1?"":"s"}`));
    const e = exposureOf(g, seat);
    if (e) row.append(el("p", `Sonar: ${cardLabel(e.card)} · ${e.assertion || "meaning hidden"}`, "exposure"));
    else if (seat !== "tonoja") row.append(el("p", g.shared_sonar !== null ? "Shares the crew’s sonar tokens" : g.sonar_spent.includes(seat) ? "Sonar spent" : "Sonar unused", "muted"));
    body.append(row);
  }
  if (hostNamed && !host) body.append(why(g.seats.some(s => s !== "tonoja" && name(s) === hostNamed)
    ? `Party Host: ${hostNamed}.` : `Party Host: ${hostNamed} (watching, no seat).`));
}

function tasksSheet(body, g) {
  if (g.mission.objective) body.append(el("p", OBJECTIVES[g.mission.objective], "objective-full"));
  body.append(el("p", g.mission.fixed ? "4 fixed tasks" : `Difficulty ${g.mission.target} · attempt ${g.attempts||1}`, "muted"));
  for (const task of g.tasks) {
    const n = el("article", undefined, "task " + task.status), meta = el("div", undefined, "meta");
    meta.append(el("span", `${name(task.owner)} · ${task.difficulty} difficulty`), pill(task.status));
    n.append(meta, el("div", task.text));
    if (task.prediction_committed) n.append(el("div", `Prediction: ${task.prediction ?? "sealed"}`, "muted"));
    body.append(n);
  }
  if (!g.tasks.length) body.append(el("p", "This mission uses the shared objective instead of task cards.", "muted"));
}

function sonarSheet(body, g) {
  const tokens = g.shared_sonar !== null ? `${g.shared_sonar} shared token${g.shared_sonar===1?"":"s"} left` : !g.me ? "" : g.sonar_spent.includes(g.me.seat) ? "Your token is spent" : "Your token is unused";
  if (tokens) body.append(el("p", tokens, "muted"));
  for (const e of g.exposures) body.append(el("div", `${name(e.seat)} · ${cardLabel(e.card)} · ${e.assertion || "sonar meaning hidden"}`, "exposure"));
  if (!g.me) return;
  const opts = g.me.communication_options, keys = Object.keys(opts);
  if (!keys.length || g.proposal) {
    body.append(why("Sonar is available only before a trick, after task allocation, with an unused token and an eligible color card."));
    return;
  }
  if (!keys.includes(ui.sonarCard)) ui.sonarCard = keys[0];
  if (!opts[ui.sonarCard].includes(ui.sonarMeaning)) ui.sonarMeaning = opts[ui.sonarCard][0];
  body.append(el("h3", "Choose a card to reveal"));
  const cards = el("div", undefined, "hand sonar-cards");
  for (const c of keys) {
    const node = cardNode(c, () => { ui.sonarCard = c; draw(); }, true);
    node.dataset.key = "sonar-card:" + c; node.setAttribute("aria-pressed", String(ui.sonarCard === c));
    cards.append(node);
  }
  body.append(cards, el("h3", "It is your…"));
  const row = el("div", undefined, "choice-row");
  for (const a of opts[ui.sonarCard]) {
    const b = button(a, () => { ui.sonarMeaning = a; draw(); }, "sonar-meaning:" + a, false, "", ui.sonarMeaning === a ? "on" : "");
    b.setAttribute("aria-pressed", String(ui.sonarMeaning === a)); row.append(b);
  }
  body.append(row);
  if (g.communication === "currents") body.append(why("Your card is revealed, but the token’s meaning stays hidden."));
  body.append(button(`Communicate ${cardLabel(ui.sonarCard)} · ${ui.sonarMeaning}`, () => { send("communicate",{card:ui.sonarCard,assertion:ui.sonarMeaning}); closeSheet(); }, "communicate", false, "", "btn-primary wide"));
}

function historySheet(body, g) {
  if (g.last_trick) {
    const t = g.last_trick;
    body.append(el("h3", `Trick ${t.index} · ${name(t.winner)} won`));
    const row = el("div", undefined, "result-trick"); row.id = "last-content";
    for (const p of t.plays) { const cell = el("div", undefined, "mini" + (p.seat === t.winner ? " winner" : "")); cell.append(cardNode(p.card), el("span", name(p.seat))); row.append(cell); }
    body.append(row);
  } else body.append(el("p", "No trick has been completed yet.", "muted"));
  body.append(why("Only the latest trick may be inspected."));
  if (g.log.length) {
    body.append(el("h3", "Logbook"));
    for (const entry of g.log) body.append(el("p", `Mission ${entry.mission} · completed in ${entry.attempts} attempt${entry.attempts===1?"":"s"}${entry.distress ? " · distress used" : ""}`));
  }
}

function menuSheet(body, g) {
  const P = party(), integration = window.AvranaIntegration;
  if (g) body.append(el("p", `Mission ${g.mission.id} · attempt ${g.attempts||1} · captain ${name(g.captain)}`, "muted"));
  if (P && ST.party_round) {
    const host = el("article", undefined, "crew-row");
    const owned = !g || hostOwned(g);
    host.append(el("strong", `Party Host · ${hostName() || "nobody right now"}`), el("p", owned
      ? "Begins each mission, retries, chooses the next one, ends EXPO and moves the Party."
      : "Ends EXPO and moves the Party."));
    body.append(host);
    if (g) {
      const crew = el("article", undefined, "crew-row");
      crew.append(el("strong", "Crew · everyone seated"), el("p", owned
        ? "Decides together what the rules give the crew: distress, and who takes the tasks where the mission says so."
        : "Decides together: distress, the tasks, and for now Begin, Retry and Next."));
      body.append(crew);
      if (g.lifecycle_transitional) { const note = why("This Party does not tell EXPO who its Host is yet, so the crew agrees on Begin, Retry and Next. That is temporary: an updated Avrana Party gives them to the Party Host."); note.dataset.key = "transitional"; body.append(note); }
    }
    if (g) {
      const cap = el("article", undefined, "crew-row");
      cap.append(el("strong", `Captain · ${name(g.captain)}`), el("p", g.seats.includes("tonoja") ? "Opens the first trick and plays Tonoja’s cards. A role in the game, not the Party Host." : "Opens the first trick. A role in the game, not the Party Host."));
      body.append(cap);
    }
    if (amHost()) body.append(endButton("End EXPO for everyone", "menu-end", "wide"), why("Everyone goes back to Party Home."));
    else body.append(why(`Only ${theHost()} can end EXPO or take the Party somewhere else.`));
    return;
  }
  if (integration && integration.integrated) {
    // Not in a Party round: the way out is Party Home, as the Party's integration gives it.
    const back = el("a", "Back to Party", "btn wide"); back.href = integration.home; back.dataset.key = "back-to-party";
    body.append(back);
  }
  if (g && !ST.party_round) {
    body.append(button("End table", () => { closeSheet(); propose("end"); }, "menu-end-table", !g.me || blocked(g), "", "wide"));
    body.append(why("Ending the table needs the whole crew to agree."));
  }
  if (!body.children.length) body.append(why("Nothing to do here yet."));
}

function helpSheet(body) { for (const text of HELP) body.append(el("p", text)); }

// ---- clock and connection -----------------------------------------------------------------------
function updateTimer() {
  const expiry = ST?.game?.expiry; $("timer").hidden = !expiry;
  if (expiry) { const remaining = Math.max(0, Math.ceil(expiry - conn.now()/1000)); $("timer").textContent = `${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,"0")}`; }
}
function updateConnection() {
  const up = Boolean(conn.ws && conn.ws.readyState === 1);
  const text = up ? "Connected" : "Reconnecting…";
  if ($("conn").textContent !== text) $("conn").textContent = text;
  $("conn-dot").classList.toggle("down", !up);
}
setInterval(() => {
  updateTimer(); updateConnection();
  // The Party's view arrives on its own schedule (after a reload it can follow the table's
  // state), and not every way it reaches the page announces itself: who the host is, is read
  // again here, so the right controls are drawn without waiting for the next move.
  const sig = party() ? `${amHost()}|${hostName()}` : "";
  const moved = sig !== ui.partySig; ui.partySig = sig;
  const ticked = Boolean(ST?.game && !$("game").hidden && graceLeft(ST.game) !== ui.grace);
  if (ST && moved) draw();
  else if (ticked && modalTop()) { ui.grace = graceLeft(ST.game); drawStatus(ST.game); drawDock(ST.game); }   // leave what is on top alone
  else if (ticked) draw();
  if (ST?.phase === "countdown") $("cd").textContent = String(Math.max(1, Math.ceil((ST.deadline - conn.now())/1000)));
}, 250);
