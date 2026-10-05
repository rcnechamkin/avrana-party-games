"use strict";
/* EXPO's phone client (AVR-275, AVR-267). One viewport during play, in five zones that are
   always on screen: the mission stage, the crew strip, the shared trick, the crew's objectives,
   and the private hand with this player's controls. Crew detail, full tasks and the log open as
   sheets over the board; the helmet radio (Burst Transmission) opens in place, over the trick.
   The server's view is the only source of game meaning: this file draws it and sends requests,
   and never decides a rule, a legal card or an outcome.

   Presentation (AVR-267) is a separate file. director.js is shown each new view after the board
   is drawn and adds transient effects for the server's events. It is given a frozen copy of the
   view and no connection: the senders below are the only code that sends. Everything a player
   needs is drawn here from the view alone, so the board is complete with the director off.

   Two authorities, kept apart (AVR-252):
     Party Host    begins, retries, moves on and ends EXPO. In a Party round the server takes
                   those only with the Party's own word for who the host is (conn.hostAction);
                   AvranaParty.isHost() here only decides which controls are drawn.
     EXPO captain  whatever the rules give the captain: the first lead, Tonoja's cards, the
                   offer in missions 10 and 13. Nothing more. */
const $ = id => document.getElementById(id);
let ST = null, pending = false, pendingTimer = null;
const ui = { sheet: null, opener: null, selected: null, handView: "mine", turnKey: "",
             radio: false, radioCard: null, radioMeaning: null, resultKey: "", resultHidden: false, armed: null,
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
  "After tasks are assigned, use the helmet radio before a trick: a Burst Transmission reveals one color card as your highest, lowest or only card of that color. You normally get one transmission (one sonar token) per attempt. Its meaning stays fixed as your hand changes.",
  "With two players, the captain controls Tonoja’s visible cards and task choices without discussion. Covered cards turn over only after their covering card’s trick ends.",
  "Task difficulty adds up to the mission’s challenge. Some tasks need the full deal; positive tasks may finish earlier. A legal play can still fail the mission. Only the latest trick may be inspected.",
  "In a Party, the Party Host begins each mission, retries, chooses the next one and ends EXPO. The Captain is a role in the game, not the Party Host. The crew decides together only what the rules give the crew, such as distress.",
  "Some missions and tasks are unavailable while conflicting source rules are clarified. Available task descriptions follow the supplied rules and the pinned The Team II reference.",
];
const SHEETS = {crew:"Crew", tasks:"Mission tasks", history:"Log", menu:"Table", help:"One crew. One mission."};
// Words for what the server says, never a judgement of it.
const STATES = {PENDING:["Standby","open"], ACTIVE:["Active","pending"], COMPLETED:["✓ Done","done"], FAILED:["× Failed","failed"], IMPOSSIBLE:["× Lost","failed"]};
const MEANING = {highest:["▲","highest"], lowest:["▼","lowest"], only:["●","only"]};
// The radio as the mission sets it. The fiction names the state; the rule is said in plain words.
const RADIO = {
  normal:   ["clear",    "Radio clear", "Clear signal: one Burst Transmission each this attempt, before a trick."],
  currents: ["degraded", "Radio degraded", "Degraded signal: your card is shown to the crew, but its meaning (highest, lowest, only) stays hidden."],
  rapture:  ["shared",   "Radio shared", "Shared signal: the whole crew draws on one supply of transmissions."],
  none:     ["disabled", "Radio off", "Radio disabled: this mission allows no communication."],
};

if (!Hub.identity.name) Hub.identity.name = "PLAYER";
$("name").value = Hub.identity.name;
Hub.buildAvatarGrid($("avatars"), Hub.identity.avatar, avatar => {
  Hub.identity.avatar = avatar;
  conn.send({t:"profile",avatar});
});
const conn = Hub.connect("/games/expo/ws", {
  onWelcome: () => present(() => director.resync()),      // what arrives next is the state, not news
  onState: render,
  onFx: fx => {
    if (fx.kind === "invalid") { settle(); Hub.toast(fx.msg, "err"); }
    if (fx.kind === "toast") Hub.toast(fx.msg);
  },
});
Hub.wirePfpButton($("photo"), () => conn);

// ---- presentation: the director is optional, read-only and fenced -------------------------------
// It gets the clock, the per-browser preferences and a frozen copy of each view. It gets no
// connection, and nothing it returns is used to draw or to decide. `expo-fx` in this browser's
// storage picks the fidelity (high, medium, low) or turns it off; reduced motion always wins.
const FX_KEY = "expo-fx";
function fxChoice() { try { return localStorage.getItem(FX_KEY); } catch { return null; } }
const director = (() => {
  try {
    if (!window.ExpoDirector || fxChoice() === "off") return null;
    return ExpoDirector.create({
      doc: document, prefs: Hub.prefs, slots: window.ExpoSlots || {}, clock: () => conn.now(), stored: fxChoice,
      store: (() => { try { return window.sessionStorage; } catch { return null; } })(),
      caps: {memory: navigator.deviceMemory, cores: navigator.hardwareConcurrency, saveData: Boolean(navigator.connection && navigator.connection.saveData)},
      vibrate: pattern => Hub.feedback.haptic(pattern),
      audio: (src, volume) => { const a = new Audio(src); a.volume = volume ?? .6; a.play().catch(() => {}); },
      nameOf: seat => name(seat), conditions: g => `${envState(g).text} · ${radioState(g).label}`,
    });
  } catch (error) { console.warn("EXPO: presentation is off", error); return null; }
})();
// Whatever the director does, the game goes on: a throw is caught, counted, and after three the
// director stands down. The board was already drawn from the view.
function present(step) {
  if (!director || director.stats.disabled) return;
  try { step(); } catch (error) { console.warn("EXPO: presentation error", error); director.failed(); }
}
function frozen(value) {
  if (value && typeof value === "object" && !Object.isFrozen(value)) { Object.freeze(value); for (const v of Object.values(value)) frozen(v); }
  return value;
}
for (const type of ["pointerdown", "keydown"]) document.addEventListener(type, () => present(() => director.gesture()), {capture: true, passive: true});
document.addEventListener("visibilitychange", () => present(() => director.visibility()));

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
function why(text) { return el("p", text, "why"); }
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
// Who a sentence is waiting for, at a length that always fits its line: one name, or one name
// and how many more (the crew strip and the crew sheet name every seat).
function whoOf(seats) { return seats.length > 1 ? `${name(seats[0])} and ${seats.length - 1} more` : name(seats[0]); }
function cardLabel(card) { const [s,r] = card.split(":"); return `${r} ${s}`; }
function cardNode(card, action, enabled=false, reason="") {
  const [s,r] = card.split(":");
  const n = el(action ? "button" : "div", undefined, "card " + s);
  n.append(el("span",r,"rank"),el("span",symbols[s],"symbol"),el("span",suitNames[s],"suit"));
  n.setAttribute("aria-label", `${s} ${r}`); n.dataset.key = "card:" + card; n.dataset.card = card;
  if (action) { n.type = "button"; n.disabled = !enabled; n.title = enabled ? "" : reason; n.onclick = action; }      // a reason belongs to a card that cannot be chosen
  return n;
}
// A card this seat has shown the crew keeps a public marker until it leaves the hand.
// In currents the crew sees the card and not its meaning; the author sees both, and is told so.
function hiddenFromCrew(g, seat) { return Boolean(g && g.communication === "currents" && g.me && g.me.seat === seat); }
const HIDDEN = "meaning hidden from the crew";
function mark(node, exposure) {
  const [glyph, word] = MEANING[exposure.assertion] || ["◌", "meaning hidden"];
  const m = el("span", `${glyph} ${{highest:"HIGH", lowest:"LOW", only:"ONLY"}[exposure.assertion] || "SENT"}`, "mark");
  node.append(m); node.classList.add("sent");
  node.setAttribute("aria-label", `${node.getAttribute("aria-label")}, transmitted${exposure.assertion ? " as your " + word : ", meaning hidden"}${exposure.assertion && hiddenFromCrew(ST?.game, exposure.seat) ? ", " + HIDDEN : ""}`);
}
function fx() { const i = el("i", undefined, "fx"); i.setAttribute("aria-hidden", "true"); return i; }
function icon(symbol) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg"), use = document.createElementNS(NS, "use");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false"); svg.classList.add("ic");
  use.setAttribute("href", "#" + symbol); svg.append(use); return svg;
}
function choices(select, entries, value) {
  select.replaceChildren();
  for (const entry of entries) {
    const o = el("option",entry.text); o.value = entry.value; o.disabled = Boolean(entry.disabled); select.append(o);
  }
  if (value !== undefined) select.value = String(value);
}
function ownerSelect(key, seats) {
  const select = el("select"); select.dataset.key = key; select.setAttribute("aria-label","Task owner");
  choices(select, seats.map(s => ({value:s,text:name(s)}))); return select;
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
function blocked(g) { return Boolean(g.proposal) || g.away.length > 0; }
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
$("mission").onchange = () => conn.send({t:"settings",patch:{mission:Number($("mission").value)}});
$("timed").onchange = () => conn.send({t:"settings",patch:{timed:$("timed").checked}});
$("tonoja-position").onchange = () => conn.send({t:"settings",patch:{tonoja_position:Number($("tonoja-position").value)}});
$("menu-toggle").onclick = e => openSheet("menu", e.currentTarget);
$("help-toggle").onclick = e => openSheet("help", e.currentTarget);
for (const tab of document.querySelectorAll(".tab")) tab.onclick = e => openSheet(tab.dataset.sheet, e.currentTarget);
$("sheet-close").onclick = closeSheet;
$("sheet-backdrop").onclick = closeSheet;
document.addEventListener("keydown", e => {
  if (e.key !== "Escape" || !$("result").hidden) return;
  if (ui.sheet) closeSheet(); else if (ui.radio) closeRadio();
});
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
// A new view: draw it, then let the director look at it. The director sees a frozen copy and is
// not waited for; drawing never depends on it.
function render(st) {
  ST = st; settle();
  present(() => director.before());
  draw();
  present(() => director.after(frozen(structuredClone(st))));
}

function draw() {
  const st = ST;
  const focusKey = document.activeElement?.dataset?.key;
  const values = new Map([...document.querySelectorAll("[data-key]")]
    .filter(n => ["INPUT","SELECT"].includes(n.tagName)).map(n => [n.dataset.key, n.value]));
  const lobby = ["lobby","countdown"].includes(st.phase);
  $("lobby").hidden = !lobby; $("game").hidden = lobby || !st.game;
  $("countdown-overlay").hidden = st.phase !== "countdown";
  if (lobby) { drawLobby(st); $("result").hidden = true; drawSheet(null, st); syncModal(); return; }
  const g = st.game;
  if (!g) { say("This table has ended."); $("result").hidden = true; drawSheet(null, st); syncModal(); return; }
  // A crew decision after a result is answered on the result: never leave it put away.
  if (g.result && g.proposal) ui.resultHidden = false;
  ui.grace = graceLeft(g);
  syncTurn(g);
  if (ui.radio && (!g.me || g.proposal || g.result)) endRadio();      // a decision or a result comes first
  $("game").classList.toggle("radio-mode", ui.radio);
  drawStatus(g);
  drawMission(g);
  drawObjectives(g);
  drawCrew(g);
  drawStage(g);
  drawHand(g);
  drawDock(g);
  drawResult(g, st);
  drawSheet(g, st);
  for (const n of document.querySelectorAll("[data-key]")) {
    if (values.has(n.dataset.key) && ["INPUT","SELECT"].includes(n.tagName)
        && (n.tagName !== "SELECT" || [...n.options].some(o => o.value === values.get(n.dataset.key)))) n.value = values.get(n.dataset.key);
    if (n.dataset.key === focusKey && !n.disabled && document.activeElement !== n) n.focus({preventScroll:true});
  }
  syncModal();
  updateTimer();
  fitStatus();
}

function drawLobby(st) {
  const ready = st.players.filter(p => p.ready && p.connected).length;
  // A Party round has no lobby of its own: the Party ran the pregame and its host started it.
  $("lobby-form").hidden = $("lobby-actions").hidden = Boolean(st.party_round);
  say(st.recovery_error
    || (st.party_round ? "The crew is boarding…" : `${ready} crew members ready · ${st.players.length} at the table`));
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

// A new moment at the table: drop a selection made for the last one, and bring up the cards
// that are about to be played (Tonoja's, for the captain on Tonoja's turn).
function syncTurn(g) {
  const key = [g.attempt, g.stage, g.trick_number, g.turn, g.trick.length].join(":");
  if (key === ui.turnKey) return;
  ui.turnKey = key; ui.selected = null; ui.radio = false; ui.radioBack = null; ui.radioCard = null; ui.radioMeaning = null;
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
    next:`Begin mission ${p.mission}?`, end:"End this table?"}[p.kind];
}
function mustAnswer(g) {
  const asked = g.proposal.recipient;
  return Boolean(g.me && !g.proposal.votes.includes(g.me.seat) && !g.away.length && (!asked || asked === g.me.seat));
}
function stillAsked(g) {
  const asked = g.proposal.recipient;
  return asked ? [asked] : g.seats.filter(s => s !== "tonoja" && !g.proposal.votes.includes(s));
}

// A timed mission whose deadline has passed and whose result has not arrived yet (the server
// judges it when the held trick settles). A fact of the view and the clock; no outcome is claimed.
function clockOut(g) { return Boolean(g && g.expiry && !g.result && g.expiry <= conn.now() / 1000); }

// The status line is the one live instruction and is always read whole: it names one person and
// counts the rest, and it asks a decision's question without the sentence of consequence that
// the decision shows under it.
function statusText(g) {
  if (g.away.length) return `Waiting for ${whoOf(g.away)} to reconnect. Your table is preserved.`;
  if (g.proposal) {
    if (mustAnswer(g)) return `Your answer is needed: ${g.proposal.recipient ? `${name(g.captain)} offers you all tasks.` : question(g).replace(/\?.*$/, "?")}`;
    return `Crew decision · waiting for ${whoOf(stillAsked(g))}`;
  }
  if (clockOut(g)) return "The mission clock is at zero";
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

// The one live region. First what is asked of this player now; then, for a screen reader only,
// the latest thing that happened (the mission stage shows the same words to the eye).
function say(text, news="") {
  if (!$("status-now") || !$("status-news")) {
    // Something else wrote into the live region and took its two parts with it: put them back.
    const now = el("span"), then = el("span", undefined, "sr"); now.id = "status-now"; then.id = "status-news";
    $("status").replaceChildren(now, then);
  }
  if ($("status-now").textContent !== text) $("status-now").textContent = text;
  if ($("status-news").textContent !== news) $("status-news").textContent = news;
}
// The status line has a place of its own: a strip above the board, or, on a short screen, the
// space between the two top-bar buttons. A sentence too long for that place is shown whole over
// the mission stage's lesser lines (the objective's line, the chips, the news), under the
// mission's title and clock: the one live instruction outranks them for as long as it is up.
// Measured, not guessed: its own place is tried first, every time.
function fitStatus() {
  const app = $("app"), box = $("status");
  app.classList.remove("status-long");
  if ($("game").hidden || box.scrollHeight <= box.clientHeight + 1) return;
  app.classList.add("status-long");            // the strip leaves its place, so measure after
  const frame = app.getBoundingClientRect(), head = document.querySelector(".mission-head").getBoundingClientRect(), stage = $("mission-stage").getBoundingClientRect();
  app.style.setProperty("--status-top", `${Math.round(head.bottom - frame.top + 2)}px`);
  app.style.setProperty("--status-height", `${Math.round(stage.bottom - head.bottom - 6)}px`);
}
addEventListener("resize", fitStatus);

function drawStatus(g) {
  const news = latest(g);
  // Who is winning the unfinished trick is the server's word (trick_leading). It is said after
  // the news, so a screen reader hears it when it changes and not again with every card.
  const ahead = g.trick_leading ? ` ${name(g.trick_leading)} is winning the trick.` : "";
  say((g.me ? "" : "Watching · ") + statusText(g), (news.length ? ` Latest: ${news.join(". ")}.` : "") + ahead);
  $("status").classList.toggle("urgent", Boolean(g.proposal && mustAnswer(g)));
}

// ---- what the server's events say, in words ----------------------------------------------------
// One sentence per event that carries meaning, built from the event's own fields. The words are
// on the board (and in the live region) whether or not anything moves, flashes or sounds.
const ALLOCATION = {skip_captain:"Task selection skips the captain", free:"The crew agrees who takes each task", one:"One crew member takes every task",
  captain_one:"The captain decides who takes every task", volunteer:"Volunteers take the tasks"};
function sayEvent(e) {
  switch (e.type) {
    case "TRICK_RESOLVED": return `${name(e.winner)} won trick ${e.trick} with ${cardLabel(e.winning_card)}`;
    case "COMMUNICATION_SENT": return `${name(e.seat)} radioed ${cardLabel(e.card)}${e.assertion ? ` as their ${e.assertion}` : ", meaning hidden"}${e.assertion && hiddenFromCrew(ST?.game, e.seat) ? ` (${HIDDEN})` : ""}`;
    case "OBJECTIVE_COMPLETED": return e.scope === "task" ? `${name(e.owner)}’s task is complete` : "The mission objective held";
    case "OBJECTIVE_FAILED": return e.scope === "task" ? `${name(e.owner)}’s task is lost` : "The mission objective is lost";
    case "MISSION_SUCCESS": return "Mission complete";
    case "MISSION_FAILURE": return "Mission failed";
    case "PLAYER_RECONNECTED": return `${name(e.seat)} is back`;
    case "MISSION_MODIFIER_ACTIVATED":
      if (e.modifier === "communication") return `${(RADIO[e.value] || RADIO.normal)[1]}${e.drawn ? " for this attempt" : ""}`;
      if (e.modifier === "allocation") return ALLOCATION[e.value] || null;
      if (e.modifier === "objective") return "A shared objective is in force";
      if (e.modifier === "distress") return e.value === "active" ? "Distress is active" : `Distress: everyone passes one card ${e.value}`;
      if (e.modifier === "timer") return `Clock started: ${e.value} seconds`;
      if (e.modifier === "sonar") return "Radio only before the first trick";
      return null;
    default: return null;      // a card played and a turn begun are the trick and the status line
  }
}
// The newest two, newest first. Only what the view was sent: the latest trick and after.
function latest(g) {
  const out = [];
  for (let i = (g.events || []).length - 1; i >= 0 && out.length < 2; i--) { const said = sayEvent(g.events[i]); if (said) out.push(said); }
  return out;
}

// ---- zone A: the mission stage -------------------------------------------------------------------
// Conditions and radio are the view's own facts. The stage's look follows them (data-env,
// data-radio); the words say them.
function envState(g) {
  if (g.result) return g.result.status === "success" ? {key:"clear", text:"Mission complete"} : g.result.status === "failed" ? {key:"lost", text:"Mission failed"} : {key:"calm", text:"Table ended"};
  if (g.expiry) return {key:"storm", text: clockOut(g) ? "Clock at zero" : "Clock running"};
  if (g.distress) return {key:"distress", text:"Distress active"};
  return {key:"calm", text:`Attempt ${g.attempts || 1}`};
}
function radioState(g) {
  const [key, label, rule] = RADIO[g.communication] || RADIO.normal;
  return {key, rule, label: g.shared_sonar !== null ? `${label} · ${g.shared_sonar} left` : label};
}
function chip(node, symbol, text, cls) {
  node.className = "chip " + cls;
  node.replaceChildren(icon(symbol), el("span", text), fx());
}
function drawMission(g) {
  const env = envState(g), radio = radioState(g), stage = $("mission-stage");
  stage.dataset.env = env.key; stage.dataset.radio = radio.key;
  $("mission-title").textContent = `Mission ${g.mission.id}`;
  $("mission-title").title = `Attempt ${g.attempts||1}`;
  $("trick-count").textContent = `Trick ${g.trick_number} / ${g.planned_tricks}`;
  const done = g.tasks.filter(t => t.state === "COMPLETED").length;
  $("mission-line").textContent = g.mission.objective ? OBJECTIVES[g.mission.objective]
    : g.tasks.length ? `Complete all ${g.tasks.length} crew task${g.tasks.length === 1 ? "" : "s"} together · ${done} done` : "Complete every assigned task together.";
  chip($("env-chip"), "expo-slot-hazard", env.text, env.key);
  chip($("radio-chip"), "expo-slot-radio", radio.label, radio.key);
  $("stage-news").textContent = latest(g).join(" · ");
}

function pill(state) {
  const [text, cls] = STATES[state] || [state, "pending"];
  return el("span", text, "pill " + cls);
}

// ---- zone D: the crew's objectives ----------------------------------------------------------------
// Compact task cards: whose it is, what it asks, and the state the server gives it. What matters
// most comes first (a failure, then this player's own open tasks); the rest is one tap away.
function drawObjectives(g) {
  const box = $("objectives"); box.replaceChildren();
  const rank = t => ["FAILED","IMPOSSIBLE"].includes(t.state) ? 0 : (g.me && t.owner === g.me.seat && t.state !== "COMPLETED") ? 1 : t.state === "ACTIVE" ? 2 : t.state === "PENDING" ? 3 : 4;
  const rows = [];
  if (g.mission.objective) {
    // The shared objective has no task state of its own: it holds with a success, and it is lost
    // only when the server's cause names it.
    const state = g.result?.status === "success" ? "COMPLETED" : g.cause?.kind === "mission_objective" ? g.cause.state : "ACTIVE";
    rows.push({text: OBJECTIVES[g.mission.objective], state, who: null, id: g.mission.objective});
  }
  for (const t of [...g.tasks].sort((a,b) => rank(a) - rank(b))) rows.push({text: t.text, state: t.state, who: t.owner, id: t.id});
  if (!rows.length) rows.push({text: "Complete every assigned task together.", state: "ACTIVE", who: null, id: ""});
  // One target for the whole panel (a row alone is too thin for a thumb): it opens the tasks.
  const open = el("button", undefined, "objectives-open"); open.type = "button"; open.dataset.key = "objectives";
  open.onclick = e => openSheet("tasks", e.currentTarget);
  const list = el("span", undefined, "objective-list");
  const said = [];
  for (const r of rows.slice(0, 2)) {
    const row = el("span", undefined, "objective " + (STATES[r.state] || ["","pending"])[1]); row.dataset.task = r.id;
    const text = el("span", undefined, "objective-text");
    if (r.who) text.append(el("b", name(r.who) + " · "));
    text.append(document.createTextNode(r.text));
    row.append(text, pill(r.state));
    said.push(`${r.who ? name(r.who) + ": " : ""}${r.text}, ${r.state.toLowerCase()}`);
    list.append(row);
  }
  open.append(list);
  const done = g.tasks.filter(t => t.state === "COMPLETED").length;
  if (g.tasks.length) { const count = el("span", undefined, "objective-count"); count.append(el("b", `${done}/${g.tasks.length}`), el("span", "done")); open.append(count); }
  open.setAttribute("aria-label", `Crew objectives${g.tasks.length ? `, ${done} of ${g.tasks.length} done` : ""}. ${said.join(". ")}.${rows.length > 2 ? ` And ${rows.length - 2} more.` : ""} Open tasks.`);
  box.append(open, fx());
}

function exposureOf(g, seat) { return g.exposures.find(e => e.seat === seat); }
function exposureMark(e) {
  const [s,r] = e.card.split(":");
  return `${r}${symbols[s]}${(MEANING[e.assertion] || ["?"])[0]}`;
}
// A seat's radio, from the view: a card it is showing, a transmission used or not, the shared
// supply, or a mission without radio.
function seatRadio(g, seat) {
  if (seat === "tonoja") return null;
  const e = exposureOf(g, seat);
  if (e) return {key:"sent", text:exposureMark(e), said:`radioed ${cardLabel(e.card)}${e.assertion ? " as their " + e.assertion : ", meaning hidden"}${e.assertion && hiddenFromCrew(g, seat) ? ", " + HIDDEN : ""}`};
  if (g.communication === "none") return {key:"off", text:"radio off", short:"off", said:"radio off"};
  if (g.shared_sonar !== null) return {key:g.shared_sonar ? "ready" : "spent", text:`shared ${g.shared_sonar}`, said:`shared radio, ${g.shared_sonar} left`};
  return g.sonar_spent.includes(seat) ? {key:"spent", text:"radio used", short:"used", said:"radio used"} : {key:"ready", text:"radio ready", short:"ready", said:"radio unused"};
}

// ---- zone B: the crew strip ------------------------------------------------------------------------
function drawCrew(g) {
  const strip = $("seats"); strip.replaceChildren();
  strip.style.setProperty("--n", g.seats.length);
  strip.classList.toggle("tight", g.seats.length > 3);
  const host = hostSeat(g), playing = !g.result && ["before_trick","in_trick"].includes(g.stage);
  for (const seat of g.seats) {
    const turn = playing && seat === g.turn, away = g.away.includes(seat);
    const tile = el("button", undefined, "seat" + (turn ? " active" : "") + (g.me && seat === g.me.seat ? " me" : "") + (away ? " away" : ""));
    tile.type = "button"; tile.dataset.key = "seat:" + seat; tile.dataset.seat = seat;
    tile.onclick = e => openSheet("crew", e.currentTarget);
    const top = el("span", undefined, "seat-name");
    if (turn) top.append(el("span", "▶", "turn-pip"));
    if (seat === g.captain) top.append(el("span", "♛", "crown"));
    top.append(el("b", name(seat)));
    // The Party Host's tag never costs a narrow tile its name: with four or five seats it sits
    // on the second line as the letter H (the tile's label, and the crew sheet, say Party Host).
    const tight = g.seats.length > 3;
    const tag = seat === host ? el("span", tight ? "H" : "HOST", "host-tag") : null;
    if (tag) tag.title = "Party Host";
    if (tag && !tight) top.append(tag);
    const roles = [seat === g.captain ? "Captain" : null, seat === host ? "Party Host" : null].filter(Boolean);
    const cards = g.hand_counts[seat], tricks = g.trick_counts[seat], radio = seatRadio(g, seat);
    tile.append(top);
    if (roles.length && g.seats.length <= 3) tile.append(el("span", roles.join(" · "), "seat-role"));
    const second = el("span", undefined, "seat-line");
    second.append(away ? el("span", "Reconnecting…", "seat-count warn")
      : el("span", tight ? `${cards}c · ${tricks}t` : `${cards} cards · ${tricks} trick${tricks===1?"":"s"}`, "seat-count"));
    if (tag && tight) second.append(tag);
    tile.append(second);
    // Four or five tiles share a phone's width: the radio's icon stands for the word "radio".
    const line = el("span", undefined, "seat-radio " + (radio ? radio.key : ""));
    if (radio && g.seats.length > 3 && radio.short) line.append(icon("expo-slot-radio"), el("span", radio.short));
    else line.textContent = radio ? radio.text : `by ${name(g.captain)}`;
    tile.append(line);
    tile.append(fx());
    tile.setAttribute("aria-label", `${name(seat)}${roles.length ? ", " + roles.join(", ") : ""}: ${cards} cards, ${tricks} tricks${radio ? ", " + radio.said : ""}${turn ? ", their turn" : ""}${away ? ", away, reconnecting" : ""}. Open crew.`);
    strip.append(tile);
  }
}

// ---- the stage: the trick during play, the decision or preparation that is waiting otherwise ----
function drawStage(g) {
  const stage = $("stage"); stage.replaceChildren();
  let node;
  if (g.proposal && !g.result) node = decisionNode(g);
  else if (ui.radio && g.me) node = radioNode(g);
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
  } else if (!g.away.length) box.append(why(`Waiting for ${whoOf(stillAsked(g))}.`));
  return box;
}

// ---- zone C: the shared trick -----------------------------------------------------------------------
// Every card stays with the seat that played it, in play order from the lead. The winner shown
// is the one the server resolved, and the seat winning an unfinished trick is the one the server
// names (trick_leading): nothing here looks at the cards to work either out.
function slot(g, seat, card, cls, note, order, tag, ahead) {
  const s = el("div", undefined, "slot " + cls + (g.me && seat === g.me.seat ? " me" : "")); s.dataset.seat = seat;
  const top = el("span", undefined, "slot-top");
  top.append(el("b", String(order), "slot-order"), el("span", name(seat), "slot-name"));
  s.append(top);
  if (card) s.append(cardNode(card));
  else s.append(el("div", note || "", "card-empty"));
  if (tag) s.append(el("span", tag, "slot-tag " + (tag === "WON" ? "won" : "lead")));
  if (ahead) { s.classList.add("ahead"); s.append(el("span", "WINNING", "slot-ahead" + (tag ? " over" : ""))); }
  s.append(fx());
  return s;
}
function suitWord(card) { const s = card.split(":")[0]; return `${s === "submarine" ? "submarines" : s} ${symbols[s]}`; }

function trickNode(g) {
  const box = el("div", undefined, "trick-stage");
  const row = el("div", undefined, "trick"); row.id = "trick";
  row.style.setProperty("--n", g.seats.length);
  const caption = el("div", undefined, "stage-caption");
  const order = from => g.seats.slice(g.seats.indexOf(from)).concat(g.seats.slice(0, g.seats.indexOf(from)));
  if (!g.trick.length && g.last_trick) {
    // The trick that just ended stays on the table until the next card is played: the winner
    // forward, the rest tucked. While the server holds the table (resolving) it says so.
    const t = g.last_trick;
    row.classList.add("resolved"); if (g.resolving) row.classList.add("resolving");
    t.plays.forEach((p, i) => row.append(slot(g, p.seat, p.card, p.seat === t.winner ? "winner" : "tucked", "", i + 1, p.seat === t.winner ? "WON" : i === 0 ? "LEAD" : "")));
    caption.append(el("strong", `Trick ${t.index} · ${name(t.winner)} won · lead ${suitWord(t.plays[0].card)}`));
    if (!g.result) caption.append(el("span", `${name(g.turn)} leads trick ${g.trick_number}`));
  } else if (!g.trick.length) {
    order(g.leader).forEach((seat, i) => row.append(slot(g, seat, null, seat === g.turn && !g.result ? "active" : "idle", seat === g.turn && !g.result ? "To lead" : "", i + 1)));
    caption.append(el("strong", g.result ? "No trick was played" : "Awaiting the opening card"));
  } else {
    const played = new Map(g.trick.map(p => [p.seat, p.card]));
    order(g.leader).forEach((seat, i) => row.append(slot(g, seat, played.get(seat), played.has(seat) ? "played" : seat === g.turn ? "active" : "idle", seat === g.turn ? "To play" : "", i + 1, i === 0 ? "LEAD" : "", seat === g.trick_leading)));
    caption.append(el("strong", `Current trick · lead ${suitWord(g.trick[0].card)}`), el("span", `Waiting for ${g.turn === "tonoja" ? `${name(g.captain)} (Tonoja)` : name(g.turn)}…`));
  }
  box.append(row, caption);
  return box;
}

// ---- the helmet radio: Burst Transmission, in place of the trick while it is open -----------------
// Which cards may be sent, and as what, is the server's list (me.communication_options). The
// page offers exactly that list and adds nothing to it.
function radioOptions(g) { return g.me && !g.proposal ? g.me.communication_options : {}; }
// The radio is about this player's own cards: open, it shows them (the switch to Tonoja's cards
// is put away); closed, the hand goes back to whichever cards were showing.
function openRadio() { ui.radioBack = ui.handView; ui.radio = true; ui.radioCard = null; ui.radioMeaning = null; ui.selected = null; ui.handView = "mine"; draw(); }
function endRadio() {
  if (ui.radio && ui.radioBack) ui.handView = ui.radioBack;
  ui.radio = false; ui.radioBack = null; ui.radioCard = null; ui.radioMeaning = null;
}
function closeRadio() { endRadio(); draw(); focusRef('[data-key="radio"]', $("mission-title")); }
function radioNode(g) {
  const box = el("section", undefined, "prep radio-console"); box.setAttribute("aria-label", "Helmet radio");
  const r = radioState(g), opts = radioOptions(g), keys = Object.keys(opts);
  const head = el("div", undefined, "prep-head");
  head.append(el("h2", "Burst Transmission"), el("span", r.label, "radio-state " + r.key));
  box.append(head, why(r.rule));
  if (ui.radioCard && !keys.includes(ui.radioCard)) { ui.radioCard = null; ui.radioMeaning = null; }
  if (!keys.length) {
    box.append(el("p", g.communication === "none" ? "Nothing can be transmitted in this mission."
      : g.resolving ? g.me.play_reason
      : "Nothing can be transmitted right now. The radio opens before a trick, once the tasks are assigned, if you have a transmission left and a color card that is your highest, lowest or only card of its color."));
    if (g.shared_sonar === null && g.communication !== "none") box.append(why(g.sonar_spent.includes(g.me.seat) ? "Your transmission is used." : "Your transmission is unused."));
  } else if (!ui.radioCard) box.append(el("p", "Choose a lit card in your hand. Only the cards the rules allow are lit."));
  else {
    if (!opts[ui.radioCard].includes(ui.radioMeaning)) ui.radioMeaning = opts[ui.radioCard].length === 1 ? opts[ui.radioCard][0] : null;
    const row = el("div", undefined, "choice-row");
    row.append(el("p", `${cardLabel(ui.radioCard)} is your:`, "radio-ask"));
    for (const a of opts[ui.radioCard]) {
      const b = button(`${(MEANING[a] || [""])[0]} ${a}`, () => { ui.radioMeaning = a; draw(); }, "radio-meaning:" + a, false, "", ui.radioMeaning === a ? "on" : "");
      b.setAttribute("aria-pressed", String(ui.radioMeaning === a)); row.append(b);
    }
    box.append(row);
  }
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
  for (const task of open) {
    const item = el("article", undefined, "pick");
    item.append(el("div", task.text, "pick-text"));
    if (live && ["normal","skip_captain"].includes(mode)) {
      const mineToTake = g.controller === g.me.seat, eligible = task.eligible_owners.includes(g.selector);
      item.append(button(g.selector === "tonoja" && mineToTake ? "Tonoja takes it" : "Take this task", () => send("choose_task",{task:task.id}), "task:"+task.id,
        !mineToTake || !eligible, "Another crew member must select this task."));
      if (mineToTake && !eligible) item.append(why("The captain cannot take a captain comparison task."));
    } else if (live && mode === "free") {
      const sel = ownerSelect("owner:"+task.id, task.eligible_owners);
      const row = el("div", undefined, "choice-row");
      row.append(sel, button("Propose owner", () => propose("assign",{task:task.id,owner:sel.value}), "assign:"+task.id));
      item.append(row);
    }
    list.append(item);
  }
  box.append(list);
  if (!live) return box;
  const actions = el("div", undefined, "choice-row");
  if (["normal","skip_captain"].includes(mode)) {
    if (g.controller === g.me.seat) {
      actions.append(button("Pass selection", () => send("pass_task"), "pass-task", !g.me.may_pass_task, "The remaining tasks must be assigned this round."));
      if (!g.me.may_pass_task) box.append(why("You cannot pass: the remaining tasks must be assigned this round."));
    } else box.append(why(`${name(g.controller)} chooses${g.selector === "tonoja" ? " for Tonoja" : ""} now.`));
  }
  if (["one","captain_one"].includes(mode)) {
    const captainOnly = mode === "captain_one" && g.me.seat !== g.captain;
    const owner = ownerSelect("all-owner", g.seats);
    actions.append(owner, button("Offer all tasks", () => propose("assign",{owner:owner.value,task:"all"}), "all-tasks", captainOnly, "The captain decides who takes the tasks."));
    if (captainOnly) box.append(why(`The captain, ${name(g.captain)}, decides who takes the tasks.`));
  }
  if (mode === "volunteer") {
    if (g.controller === g.me.seat) {
      actions.append(button("Yes · take the tasks", () => send("volunteer",{yes:true}), "volunteer-yes", false, "", "btn-primary"),
        button("No", () => send("volunteer",{yes:false}), "volunteer-no", !g.me.may_decline_volunteer, "The remaining crew must take the tasks."));
      if (!g.me.may_decline_volunteer) box.append(why("You cannot decline: the remaining crew must take the tasks."));
    } else box.append(why(`${name(g.controller)} is asked to volunteer.`));
  }
  if (actions.children.length) box.append(actions);
  return box;
}

function predictionNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Predictions");
  box.append(el("h2", "Predict your tricks"));
  let mine = 0;
  for (const task of g.tasks) {
    if (!(task.prediction_required && !task.prediction_committed && g.me && (task.owner === g.me.seat || (task.owner === "tonoja" && g.captain === g.me.seat)))) continue;
    mine++;
    const item = el("article", undefined, "pick");
    item.append(el("div", (task.owner === "tonoja" ? "Tonoja · " : "") + task.text, "pick-text"));
    const form = el("div", undefined, "choice-row"), input = el("input");
    input.type = "number"; input.min = "0"; input.max = String(g.planned_tricks); input.step = "1"; input.value = "0";
    input.inputMode = "numeric"; input.dataset.key = "predict:"+task.id; input.setAttribute("aria-label","Predicted tricks");
    form.append(input, button("Lock prediction", () => send("predict",{task:task.id,count:Number(input.value)}), "lock:"+task.id, g.away.length > 0, "", "btn-primary"));
    item.append(form); box.append(item);
  }
  if (!mine) box.append(why("Waiting for the crew to lock their predictions."));
  else box.append(why("A prediction cannot be changed once locked."));
  return box;
}

function assistanceNode(g) {
  const box = el("section", undefined, "prep"); box.setAttribute("aria-label", "Before the first trick");
  box.append(el("h2", "Ready to move out"));
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
  box.append(why(!g.me ? "The crew is choosing." : g.me.pass_locked ? "Your pass is sealed. Waiting for the crew." : "Choose a color card from your hand, then pass it. Submarines cannot be passed."));
  return box;
}

// ---- the hand: always on screen ----------------------------------------------------------------
function handState(g) {
  // Which cards are showing, and for each whether it may be chosen now and the server's reason.
  const passing = g.stage === "passing";
  if (ui.radio && g.me) {
    // Radio open: only the cards the server offers for transmission are lit.
    const opts = radioOptions(g);
    return g.me.hand.map(c => ({card:c, enabled: !g.away.length && Object.hasOwn(opts, c), reason:"Only the lit cards can be transmitted now."}));
  }
  if (ui.handView === "tonoja") {
    const mayPlay = Boolean(g.me && g.turn === "tonoja" && g.captain === g.me.seat && !g.proposal && !g.away.length && !g.result);
    return g.tonoja.map(c => c && ({card:c, enabled:mayPlay && g.me.legal_cards.includes(c), reason:g.me?.play_reason || "Only the captain plays for Tonoja."}));
  }
  if (!g.me) return [];
  return g.me.hand.map(c => ({card:c,
    enabled: !g.away.length && !g.proposal && !g.result && (passing ? (!g.me.pass_locked && !c.startsWith("submarine")) : g.turn === g.me.seat && g.me.legal_cards.includes(c)),
    reason: passing ? "Submarines cannot be passed" : g.me.play_reason || (g.turn === g.me.seat ? "You must follow the opening suit." : "Play from Tonoja’s cards.")}));
}

function drawHand(g) {
  const sw = $("hand-switch"); sw.replaceChildren();
  sw.hidden = !(g.tonoja.length && g.me) || ui.radio;
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
  hand.classList.toggle("radio", ui.radio);
  if (ui.selected && !cards.some(c => c && c.card === ui.selected && c.enabled)) ui.selected = null;
  const shown = g.me && ui.handView === "mine" ? exposureOf(g, g.me.seat) : null;
  for (const c of cards) {
    if (!c) { hand.append(el("div", "", "card-empty gone")); continue; }
    // Every card that may be chosen is drawn the same way: nothing here knows, or shows, what a
    // legal card will do.
    const node = ui.radio
      ? cardNode(c.card, () => { ui.radioCard = ui.radioCard === c.card ? null : c.card; ui.radioMeaning = null; draw(); }, c.enabled, c.reason)
      : cardNode(c.card, () => { ui.selected = ui.selected === c.card ? null : c.card; draw(); }, c.enabled, c.reason);
    node.setAttribute("aria-pressed", String((ui.radio ? ui.radioCard : ui.selected) === c.card));
    if (shown && shown.card === c.card) mark(node, shown);
    hand.append(node);
  }
  if (!n) hand.append(el("p", g.me ? "No cards left." : "Spectators see no hands.", "muted"));
  let reason = "";
  if (g.me) {
    const lead = g.trick[0]?.card.split(":")[0];
    const tonoja = ui.handView === "tonoja";
    if (g.result) reason = "The mission is over.";
    else if (ui.radio) reason = !Object.keys(radioOptions(g)).length ? "Nothing to transmit now" : ui.radioCard ? `Transmit ${cardLabel(ui.radioCard)}` : "Choose a lit card to transmit";
    else if (g.stage === "passing") reason = g.me.pass_locked ? "Your pass is sealed" : "Choose one color card";
    else if (tonoja && g.captain !== g.me.seat) reason = "Only the captain plays for Tonoja.";
    else if (g.me.play_reason) reason = g.me.play_reason;
    else if (tonoja !== (g.turn === "tonoja")) reason = tonoja ? "It is not Tonoja’s turn." : "Play from Tonoja’s cards.";
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
    else if (begin && ui.grace > 0) z.append(button(`Begin in ${ui.grace}`, () => {}, "begin", true, "The crew has a moment to ask for distress first.", "btn-primary"));
    else if (begin) z.append(button("Begin mission", () => lifecycle({kind:"begin"}), "begin", blocked(g), g.away.length ? "Waiting for the crew to reconnect." : "The crew is deciding something.", "btn-primary"));
    else z.append(endButton("End EXPO", "end"));
    return z;
  }
  // The crew decides: a standalone table, or a Party that does not say who its host is.
  const z = zone("Crew", g.lifecycle_transitional ? "decides for now" : "decides together"); z.id = "dock-host";
  if (begin) z.append(button("Begin without passing", () => propose("begin"), "begin", blocked(g) || !g.me, "", "btn-primary"));
  else if (!ST.party_round) z.append(button("End table", () => propose("end"), "end", !g.me || blocked(g)));
  else if (amHost()) z.append(endButton("End EXPO", "end"));
  else z.append(el("p", `${hostName() || "The Party Host"} ends EXPO`, "dock-note"));
  return z;
}

function actionZone(g) {
  const tonoja = ui.handView === "tonoja";
  const z = zone(!g.me ? "Watching" : g.me.seat === g.captain ? (tonoja ? "Captain · Tonoja" : "Captain") : "Crew member", g.me ? "game role" : "no seat");
  z.id = "dock-action";
  const row = el("div", undefined, "action-row");
  if (g.me) {
    // The radio is always one thumb away from the hand. Open, it lights the cards that may be
    // sent; when nothing may be sent it says why instead of going grey.
    const can = Object.keys(radioOptions(g)).length > 0;
    const r = button("", () => ui.radio ? closeRadio() : openRadio(), "radio", false, "", "radio-btn" + (ui.radio ? " on" : "") + (can ? " ready" : ""));
    r.append(icon("expo-slot-radio"), el("span", ui.radio ? "Close" : "Radio"));
    r.setAttribute("aria-pressed", String(ui.radio));
    r.setAttribute("aria-label", ui.radio ? "Close the radio" : can ? "Radio: you can transmit now" : "Radio");
    row.append(r);
  }
  if (ui.radio && g.me) {
    const card = ui.radioCard, meaning = ui.radioMeaning, ready = Boolean(card && meaning);
    const text = ready ? `Transmit ${cardLabel(card)} · ${meaning}` : card ? "Choose its meaning" : "Transmit";
    const b = button(text, () => { send("communicate", {card, assertion: meaning}); endRadio(); draw(); focusRef('[data-key="radio"]', $("mission-title")); },
      "transmit", !ready, ready ? "" : "Choose a lit card and its meaning first.", "btn-primary");
    b.setAttribute("aria-label", text);
    row.append(b);
  } else {
    const passing = g.stage === "passing" && !tonoja;
    const card = ui.selected;
    const text = card ? `${passing ? "Pass" : "Play"} ${cardLabel(card)}` : passing ? "Pass card" : "Play card";
    const b = button(text, () => { const c = ui.selected; ui.selected = null; send(passing ? "pass_card" : "play_card", {card:c}); },
      passing ? "pass" : "play", !card, card ? "" : "Choose a card first.", "btn-primary");
    b.setAttribute("aria-label", text);
    row.append(b);
  }
  z.append(row);
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
// Why an attempt failed, from the server's `cause` and nothing else: what failed, the play it is
// attributed to (where the server names one), and whose objective it was. The server names the
// card that decided it, not a fault, and the page says so. No assist is ever invented.
const FAILURE = {
  violated: "Something it forbids happened.", unreachable: "What it needs can no longer happen.",
  unmet_at_end: "The deal ended before it was met.", deadline: "The clock ran out.",
  captain_left_with_comparison_tasks: "The captain was left with only tasks a captain may not take.",
  ineligible_volunteer: "A volunteer may not take one of the tasks.",
};
// Placeholder copy for the fiction, keyed by the kind of failure. The facts beside it are the
// server's; this line is only colour and is the writer's to replace (PRESENTATION.md).
const FICTION = {
  violated: "The line broke where it could not afford to.", unreachable: "The objective slipped out of reach in the dust.",
  unmet_at_end: "The window closed before the crew got through.", deadline: "The storm front arrived first.",
};
function causeFacts(g) {
  const c = g.cause;
  if (!c || typeof c !== "object") return [];
  const task = c.kind === "task" ? g.tasks.find(t => t.id === c.objective) : null;
  const what = task ? task.text : c.kind === "mission_objective" ? (OBJECTIVES[c.objective] || "The mission objective")
    : c.kind === "deadline" ? "The mission clock" : c.kind === "allocation" ? "Task selection" : "The mission’s objectives";
  const facts = [["What failed", `${what}${FAILURE[c.failure] && c.kind !== "deadline" ? " " + FAILURE[c.failure] : ""}`]];
  if (c.trigger_seat) {
    const by = c.trigger_controller && c.trigger_controller !== c.trigger_seat ? `${name(c.trigger_seat)} (played by ${name(c.trigger_controller)})` : name(c.trigger_seat);
    facts.push(["Deciding play", c.trigger_card ? `${by} · ${cardLabel(c.trigger_card)}${c.trick && c.kind !== "deadline" ? ` · trick ${c.trick}` : ""}` : `${by}${c.kind === "allocation" ? " · during task selection" : ""}`]);
  } else facts.push(["Deciding play", "No single play decided it."]);
  facts.push(["Fell on", !c.affected_seat ? "The whole crew" : c.affected_seat === c.trigger_seat ? `${name(c.affected_seat)}’s own ${task ? "task" : "objective"}` : `${name(c.affected_seat)}${task ? "’s task" : ""}`]);
  return facts;
}

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
  const sub = ok ? "Together, you did it." : r.status === "failed" ? (FICTION[g.cause?.failure] || "Regroup and go again.") : "";
  card.append(el("div", ok ? "✓" : "×", "result-mark"), title, el("p", sub, "result-sub"), reason);
  // What the server's state says about how it ended. Nothing is inferred here: the three lines
  // are the server's cause (AVR-246), a failed task is one the server marked failed, and the
  // trick is the last one it resolved, the only one a viewer is sent.
  const facts = el("div", undefined, "result-facts");
  const cause = r.status === "failed" ? causeFacts(g) : [];
  for (const [label, text] of cause) { const fact = el("p", undefined, "fact cause"); fact.append(el("b", label + ": "), document.createTextNode(text)); facts.append(fact); }
  if (cause.length && g.cause.trigger_seat) facts.append(el("p", "Every play was legal. This names the card that decided it, not a fault.", "fact note"));
  if (!cause.length) for (const t of g.tasks.filter(t => t.status === "failed")) {
    const fact = el("p", undefined, "fact");
    fact.append(el("b", `${name(t.owner)}’s task failed`));
    if (t.text !== r.reason) fact.append(document.createTextNode(` · ${t.text}`));
    facts.append(fact);
  }
  if (g.last_trick) {
    const t = g.last_trick, about = g.cause && g.cause.kind !== "deadline" && g.cause.trick === t.index ? g.cause : null;
    facts.append(el("p", `Ended after trick ${t.index} of ${g.planned_tricks}, won by ${name(t.winner)}.`, "fact"));
    const row = el("div", undefined, "result-trick");
    for (const p of t.plays) {
      const decided = Boolean(about && about.trigger_card === p.card), named = Boolean(about && about.cards.includes(p.card));
      const cell = el("div", undefined, "mini" + (p.seat === t.winner ? " winner" : "") + (named ? " about" : ""));
      cell.append(cardNode(p.card), el("span", decided ? `${name(p.seat)} · deciding` : name(p.seat))); row.append(cell);
    }
    facts.append(row);
  }
  if (facts.children.length) card.append(facts);
  const controls = el("div", undefined, "result-actions");
  if (g.proposal) controls.append(decisionNode(g));
  else if (g.away.length) controls.append(why(`Waiting for ${names(g.away)} to reconnect.`));
  else if (mayMoveOn(g)) {
    if (hostOwned(g)) controls.append(el("p", "You are the Party Host: you choose what happens next.", "result-who"));
    if (r.status === "failed") controls.append(button("Retry same tasks", () => lifecycle({kind:"retry",keep:true}), "retry-same"), button("Retry new tasks", () => lifecycle({kind:"retry",keep:false}), "retry-new", false, "", "btn-primary"));
    if (ok) {
      const next = el("select"); next.dataset.key = "next-mission"; next.setAttribute("aria-label", "Next mission");
      const open = (st.missions||[]).filter(m => m.enabled);
      choices(next, open.map(m => ({value:m.id,text:`Mission ${m.id}`})), open.find(m => m.id > g.mission.id)?.id || g.mission.id);
      controls.append(next, button("Next mission", () => lifecycle({kind:"next",mission:Number(next.value)}), "next", false, "", "btn-primary"));
    }
  } else controls.append(el("p", hostOwned(g) ? `Waiting for ${theHost()} (Party Host) to choose what’s next.` : "The crew decides what’s next.", "result-who waiting"));
  // Ending EXPO: the Party Host's in a Party; the crew's own decision at a standalone table.
  if (!g.proposal) {
    if (ST.party_round ? amHost() : false) controls.append(endButton("End EXPO for everyone", "end-expo", "quiet"));
    else if (!ST.party_round && g.me && !g.away.length) controls.append(button("End table", () => propose("end"), "end-table", false, "", "quiet"));
  }
  if (ok && window.Brag && g.me) controls.append(Brag.button(() => ({title:"EXPO",icon:"🌊",winner:{name:"The crew",avatar:"🌊"},headline:`Mission ${g.mission.id} completed together`,beaten:[]})));
  controls.append(button("Look at the table", () => { ui.resultHidden = true; draw(); focusRef('[data-key="show-result"]', $("mission-title")); }, "review", false, "", "quiet"));
  card.append(controls);
  box.append(card, fx());
  if (fresh) focusResult();
}

// ---- sheets: everything that is not this turn ---------------------------------------------------
function drawSheet(g, st) {
  const sheet = $("sheet");
  if (ui.sheet && !g && !["menu","help"].includes(ui.sheet)) ui.sheet = null;
  sheet.hidden = !ui.sheet;
  for (const tab of document.querySelectorAll(".tab")) tab.setAttribute("aria-expanded", String(ui.sheet === tab.dataset.sheet));
  if (!ui.sheet) return;
  $("sheet-title").textContent = SHEETS[ui.sheet];
  const body = $("sheet-body"); body.replaceChildren();
  ({crew:crewSheet, tasks:tasksSheet, history:historySheet, menu:menuSheet, help:helpSheet})[ui.sheet](body, g, st);
}

function crewSheet(body, g) {
  const host = hostSeat(g), hostNamed = hostName();
  body.append(why(`${radioState(g).label}. ${radioState(g).rule}`));
  for (const seat of g.seats) {
    const row = el("article", undefined, "crew-row" + (seat === g.turn ? " active" : ""));
    const roles = [g.me && seat === g.me.seat ? "You" : null, seat === g.captain ? "Captain" : null,
      seat === host ? "Party Host" : null,
      seat === "tonoja" ? `played by ${name(g.captain)}` : null, g.away.includes(seat) ? "Away" : null].filter(Boolean);
    const head = el("div", undefined, "crew-head"); head.append(el("strong", name(seat)), el("span", roles.join(" · "), "muted"));
    const owned = g.tasks.filter(t => t.owner === seat);
    row.append(head, el("p", `${g.hand_counts[seat]} cards · ${g.trick_counts[seat]} tricks · ${owned.length} task${owned.length===1?"":"s"}`));
    const e = exposureOf(g, seat);
    if (e) row.append(el("p", `Radio: ${cardLabel(e.card)} · ${e.assertion || "meaning hidden"}${e.assertion && hiddenFromCrew(g, seat) ? ` (${HIDDEN})` : ""}`, "exposure"));
    else if (seat !== "tonoja") row.append(el("p", g.communication === "none" ? "Radio off" : g.shared_sonar !== null ? "Shares the crew’s transmissions" : g.sonar_spent.includes(seat) ? "Radio used" : "Radio unused", "muted"));
    if (g.away.includes(seat)) row.append(el("p", "Reconnecting: the table waits, and nothing is played for them.", "muted"));
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
    meta.append(el("span", `${name(task.owner)} · ${task.difficulty} difficulty`), pill(task.state));
    n.append(meta, el("div", task.text));
    if (task.prediction_committed) n.append(el("div", `Prediction: ${task.prediction ?? "sealed"}`, "muted"));
    body.append(n);
  }
  if (!g.tasks.length) body.append(el("p", "This mission uses the shared objective instead of task cards.", "muted"));
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
    effectsRow(body);
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
  effectsRow(body);
}

// How much the page moves is this browser's own choice and changes nothing about the game.
function effectsRow(body) {
  const row = el("article", undefined, "crew-row"), now = director && !director.stats.disabled ? director.fidelity : "off";
  row.append(el("strong", "Effects"));
  if (now === "off") { row.append(el("p", "Effects are off in this browser. The game is the same.", "muted")); body.append(row); return; }
  row.append(el("p", Hub.prefs.reducedFx ? "Reduced motion is on for this browser, so the board stays still and this choice is off. The game is the same."
    : "Only how much the board moves. The game is the same at every level.", "muted"));
  const choice = el("div", undefined, "choice-row");
  for (const [value, label] of [["high","Full"],["medium","Light"],["low","Still"]]) {
    // With reduced motion on, the choice would change nothing: it is disabled, and the line
    // above says why.
    const b = button(label, () => { try { localStorage.setItem(FX_KEY, value); } catch { /* private mode */ } draw(); }, "fx:" + value, Boolean(Hub.prefs.reducedFx), "Reduced motion is on for this browser.", now === value ? "on" : "");
    b.setAttribute("aria-pressed", String(now === value)); choice.append(b);
  }
  row.append(choice); body.append(row);
}

function helpSheet(body) { for (const text of HELP) body.append(el("p", text)); }

// ---- clock and connection -----------------------------------------------------------------------
function updateTimer() {
  const expiry = ST?.game?.expiry; $("timer").hidden = !expiry;
  if (expiry) { const remaining = Math.max(0, Math.ceil(expiry - conn.now()/1000)); $("timer").textContent = `${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,"0")}`; }
  // The moment the deadline passes, the chip and the status line stop saying the clock runs.
  const out = clockOut(ST?.game);
  if (out !== ui.clockOut) { ui.clockOut = out; if (ST?.game && !$("game").hidden) { drawMission(ST.game); drawStatus(ST.game); fitStatus(); } }
}
function updateConnection() {
  const up = Boolean(conn.ws && conn.ws.readyState === 1);
  const text = up ? "Connected" : "Reconnecting…";
  if ($("conn").textContent !== text) $("conn").textContent = text;
  $("conn-dot").classList.toggle("down", !up);
  $("conn").classList.toggle("down", !up);        // a lost connection is always said in words
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
