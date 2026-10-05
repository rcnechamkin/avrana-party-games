// Shared by the EXPO browser playtests: the one-viewport contract of AVR-275 and the five-zone
// board of AVR-267, measured.
import assert from "node:assert/strict";

/* How the page presents, chosen by the environment so that every playtest can be run at each
   fidelity tier, with reduced motion, and with the director off:
     EXPO_FX=high|medium|low|off   the per-browser choice (off: the director is never created)
     EXPO_MOTION=reduced           the system's reduced-motion preference
   The tier the page must then report (undefined when the director is off). */
export const FX = process.env.EXPO_FX || "", REDUCED = process.env.EXPO_MOTION === "reduced";
export const EXPECT_FX = FX === "off" ? undefined : REDUCED ? "low" : (FX || "high");
export async function presentation(pg) {
  if (REDUCED) await pg.emulateMediaFeatures([{name:"prefers-reduced-motion", value:"reduce"}]);
  await pg.evaluateOnNewDocument(fx => {
    if (fx) localStorage.setItem("expo-fx", fx);
    // Every frame the page sends, and whether the director was on the stack when it was sent.
    window.__sent = [];
    const send = WebSocket.prototype.send;
    WebSocket.prototype.send = function (data) {
      let t = "?"; try { t = JSON.parse(data).t; } catch { /* not ours */ }
      window.__sent.push({t, director: /director\.js/.test(new Error().stack || "")});
      return send.call(this, data);
    };
  }, FX);
}
/* The director sends nothing: no frame ever left the page with director.js on the stack. The
   page reports the fidelity tier the environment asked for, the director never threw, and below
   the high tier nothing ambient runs; at the low tier (and with the director off) nothing is
   animated at all. */
export async function directorSentNothing(pg, label) {
  const sent = await pg.evaluate(() => window.__sent);
  assert.ok(sent.length > 0, `${label}: the page's frames were recorded`);
  assert.deepEqual(sent.filter(f => f.director), [], `${label}: no frame was sent from the director`);
  assert.equal(await pg.evaluate(() => document.documentElement.dataset.expoFx), EXPECT_FX, `${label}: the fidelity tier the environment asked for`);
  if (EXPECT_FX !== "high") assert.equal(await pg.evaluate(() => getComputedStyle(document.querySelector(".mstage-art .h1")).animationName), "none", `${label}: no ambient motion below the high tier`);
  if (FX !== "off") assert.equal(await pg.evaluate(() => director.stats.errors), 0, `${label}: the director never threw`);
  else assert.equal(await pg.evaluate(() => director), null, `${label}: the director is off`);
  if (EXPECT_FX === "low" || FX === "off") assert.equal(await pg.evaluate(() => document.getAnimations().filter(a => String(a.id).startsWith("expo-fx:")).length), 0, `${label}: nothing is animated`);
}

// Representative narrow phones. The first is the size named by AVR-266 and AVR-275. The short
// ones are what a phone browser leaves when its own bars are showing (a 390 x 844 iPhone in
// Safari draws about 390 x 664).
export const PHONES = [
  {width:360,height:740}, {width:390,height:664}, {width:375,height:667},
  {width:412,height:915}, {width:360,height:600},
];

const BOARD = ["status","mission-stage","mission-title","trick-count","objectives","seats","stage","hand","dock"];
// The five zones, top to bottom: mission stage, crew strip, shared trick (or the decision that
// takes its place), crew objectives, private hand and controls.
const ZONES = ["mission-stage","seats","stage","objectives","hand-panel","dock"];

/* Ordinary play needs no vertical scrolling: nothing scrolls as a page, and the mission, the
   trick counter, the status line, the objectives, the crew, the stage (the trick), every card of
   the hand and the dock are all inside the viewport, at a size a finger can use. */
export async function oneViewport(pg, label) {
  // A toast (the shared Hub.toast) is a fixed, passing notice outside the board: wait it out.
  await pg.waitForFunction(() => !document.querySelector(".toast"), {timeout:6000});
  // The hand is measured at rest. While the director slides its cards into place (transform
  // only) a card is its full size, but a box read through a fractional translate comes back as
  // 43.99999 px and would fail a comparison with 44 for a reason that is arithmetic, not size.
  await pg.waitForFunction(() => !document.getAnimations().some(a => a.playState === "running" && a.effect?.target?.closest?.("#hand")), {timeout:8000});
  const m = await pg.evaluate(ids => {
    const box = n => { const b = n.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,left:b.left,right:b.right,width:b.width,height:b.height}; };
    const room = document.getElementById("avrana-game-room");
    const scrollers = [document.scrollingElement, document.body, room, document.getElementById("app")].filter(Boolean);
    return {
      vw: innerWidth, vh: innerHeight,
      overflow: scrollers.map(n => ({y: n.scrollHeight - n.clientHeight, x: n.scrollWidth - n.clientWidth, top: n.scrollTop})),
      parts: Object.fromEntries(ids.map(id => { const n = document.getElementById(id); return [id, n && n.offsetParent !== null ? box(n) : null]; })),
      stageWords: ["mission-title","mission-line","env-chip","radio-chip"].map(id => { const n = document.getElementById(id); return {id, text: n.textContent.trim(), ...box(n)}; }),
      cards: [...document.querySelectorAll("#hand .card")].map(box),
      stageText: document.getElementById("stage")?.innerText || "",
    };
  }, [...new Set([...BOARD, ...ZONES])]);
  const at = `${label} at ${m.vw}x${m.vh}`;
  // AVR-267: the mission stage is 15 to 25 percent of the screen, the zones stand in order and
  // do not overlap, and the stage says the mission, its objective, the conditions and the radio.
  const share = m.parts["mission-stage"].height / m.vh;
  assert.ok(share >= .15 && share <= .25, `${at}: the mission stage is 15 to 25 percent of the screen (${(share * 100).toFixed(1)}%)`);
  for (let i = 1; i < ZONES.length; i++) {
    const above = m.parts[ZONES[i - 1]], below = m.parts[ZONES[i]];
    assert.ok(above && below, `${at}: the ${ZONES[i]} zone is on screen`);
    assert.ok(below.top >= above.bottom - .5, `${at}: ${ZONES[i]} is below ${ZONES[i - 1]} and they do not overlap`);
  }
  const zoneA = m.parts["mission-stage"];
  for (const w of m.stageWords) {
    assert.ok(w.text.length > 0, `${at}: the mission stage says its ${w.id}`);
    assert.ok(w.top >= zoneA.top - .5 && w.bottom <= zoneA.bottom + .5, `${at}: #${w.id} is inside the mission stage`);
  }
  for (const o of m.overflow) {
    assert.ok(o.y <= 1, `${at}: nothing scrolls vertically (overflow ${o.y}px)`);
    assert.ok(o.x <= 1, `${at}: nothing scrolls sideways (overflow ${o.x}px)`);
    assert.equal(o.top, 0, `${at}: the page is not scrolled`);
  }
  for (const id of BOARD) {
    const b = m.parts[id];
    assert.ok(b, `${at}: #${id} is on screen`);
    assert.ok(b.top >= -0.5 && b.bottom <= m.vh + 0.5 && b.left >= -0.5 && b.right <= m.vw + 0.5,
      `${at}: #${id} is inside the viewport (${Math.round(b.top)}..${Math.round(b.bottom)} of ${m.vh})`);
    assert.ok(b.height > 0 && b.width > 0, `${at}: #${id} has a size`);
  }
  assert.ok(m.parts.stage.height >= 84, `${at}: the stage keeps room for the trick (${Math.round(m.parts.stage.height)}px)`);
  for (const c of m.cards) {
    assert.ok(c.top >= 0 && c.bottom <= m.vh + 0.5 && c.left >= 0 && c.right <= m.vw + 0.5, `${at}: every hand card is inside the viewport`);
    assert.ok(c.width >= 40 && c.height >= 44, `${at}: a hand card is big enough to tap (${Math.round(c.width)}x${Math.round(c.height)})`);
  }
  return m;
}

/* An element (by data-key, or #id) is drawn inside the viewport and not covered by anything. */
export async function onScreen(pg, selector, label) {
  const r = await pg.evaluate(sel => {
    const n = sel.startsWith("#") ? document.querySelector(sel) : [...document.querySelectorAll("[data-key]")].find(x => x.dataset.key === sel);
    if (!n || n.offsetParent === null) return null;
    const b = n.getBoundingClientRect();
    const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return {top:b.top, bottom:b.bottom, left:b.left, right:b.right, vh:innerHeight, vw:innerWidth, reachable: Boolean(top && (top === n || n.contains(top) || top.contains(n)))};
  }, selector);
  assert.ok(r, `${label}: ${selector} is drawn`);
  assert.ok(r.top >= -0.5 && r.bottom <= r.vh + 0.5 && r.left >= -0.5 && r.right <= r.vw + 0.5, `${label}: ${selector} is inside the viewport`);
  assert.ok(r.reachable, `${label}: ${selector} is not covered`);
}

export async function has(pg, key) {
  return pg.evaluate(k => { const n = [...document.querySelectorAll("[data-key]")].find(x => x.dataset.key === k); return n ? {disabled: Boolean(n.disabled), title: n.title || "", text: n.textContent} : null; }, key);
}

export async function clickKey(pg, key) {
  await pg.evaluate(k => {
    const n = [...document.querySelectorAll("[data-key]")].find(x => x.dataset.key === k);
    if (!n || n.disabled) throw Error("Unavailable " + k);
    n.click();
  }, key);
}

/* Play (or pass) a card the way a thumb does: choose it in the hand, then commit in the dock. */
export async function playCard(pg, card, commit="play") {
  await clickKey(pg, "card:" + card);
  await clickKey(pg, commit);
}

/* The mission result owns the screen: the overlay covers the app, and its title, the server's
   reason and whatever this viewer may do next are inside the viewport without scrolling. */
export async function resultOwnsTheScreen(pg, label) {
  const m = await pg.evaluate(() => {
    const box = n => { const b = n.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,left:b.left,right:b.right,width:b.width,height:b.height}; };
    const r = document.getElementById("result"), app = document.getElementById("app");
    if (!r || r.hidden) return null;
    const card = r.querySelector(".result-card");
    const mid = document.elementFromPoint(innerWidth / 2, innerHeight / 2);
    return {vh: innerHeight, vw: innerWidth, overlay: box(r), app: box(app), title: box(document.getElementById("result-title")),
      titleText: document.getElementById("result-title").textContent, reason: box(document.getElementById("result-reason")),
      reasonText: document.getElementById("result-reason").textContent, covers: Boolean(mid && r.contains(mid)),
      cardScroll: card.scrollHeight - card.clientHeight, text: r.innerText,
      keys: [...r.querySelectorAll("[data-key]")].map(n => ({key: n.dataset.key, ...box(n), disabled: Boolean(n.disabled)})),
      handCovered: (() => { const h = document.querySelector("#hand .card"); if (!h) return true; const b = h.getBoundingClientRect(); const t = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return Boolean(t && r.contains(t)); })(),
      status: ST.game.result, live: document.getElementById("status").textContent};
  });
  const at = `${label} at ${m?.vw}x${m?.vh}`;
  assert.ok(m, `${label}: the result is showing`);
  assert.ok(m.covers && m.handCovered, `${at}: the result covers the board`);
  assert.ok(m.overlay.top <= m.app.top + 1 && m.overlay.bottom >= m.app.bottom - 1 && m.overlay.width >= m.app.width - 1, `${at}: the result takes the whole screen`);
  for (const [what, b] of [["title", m.title], ["reason", m.reason]]) assert.ok(b.top >= 0 && b.bottom <= m.vh, `${at}: the result's ${what} is inside the viewport`);
  assert.equal(m.titleText, {success:"MISSION COMPLETE", failed:"MISSION FAILED", abandoned:"TABLE ENDED"}[m.status.status]);
  assert.equal(m.reasonText, m.status.reason, `${at}: the reason is the server's`);
  assert.match(m.live, /Mission (complete|failed)|Table ended|Your answer|Crew decision|Waiting/, `${at}: the status line says it too`);
  for (const k of m.keys.filter(k => ["retry-same","retry-new","next","next-mission"].includes(k.key)))
    assert.ok(k.top >= 0 && k.bottom <= m.vh + 0.5, `${at}: ${k.key} is inside the viewport`);
  return m;
}

/* The same moment at its fullest: the longest names the lobby allows, a long sentence on every
   task and more tasks than any mission deals, and the largest hand a deal gives (14 cards).
   Text and cards never widen or lengthen the board. `check` runs against that drawing. */
export async function withLongText(pg, check) {
  const real = await pg.evaluate(() => ST);
  await pg.evaluate(st => {
    const long = "Win a trick by playing a color 7 and capture a color 5 in that same trick, and never a submarine.";
    const g = st.game;
    const tasks = g.tasks.map(t => ({...t, text: long}));
    while (tasks.length && tasks.length < 8) tasks.push({...tasks[tasks.length % g.tasks.length], id: "stress-" + tasks.length});
    const deck = ["blue","green","pink","yellow"].flatMap(c => [1,2,3,4,5,6,7,8,9].map(n => `${c}:${n}`)).concat([1,2,3,4].map(n => `submarine:${n}`));
    const fill = hand => hand.concat(deck.filter(c => !hand.includes(c))).slice(0, Math.max(hand.length, 14));
    render({...st, players: st.players.map(p => ({...p, name: "WWWWWWWWWWWWWW"})),
      game: {...g, tasks, me: g.me ? {...g.me, hand: fill(g.me.hand)} : g.me,
             tonoja: g.tonoja.length ? fill(g.tonoja.filter(Boolean)) : g.tonoja}});
  }, real);
  try { await check(); } finally { await pg.evaluate(st => render(st), real); }
}

/* Every control a thumb can reach is a real target: at least 44 px tall and 40 px wide (a hand
   of seven shares a 360 px screen), measured on the element itself, not a padded hit area. */
export async function touchTargets(pg, label) {
  const small = await pg.evaluate(() => {
    const top = !document.getElementById("result").hidden ? document.getElementById("result") : !document.getElementById("sheet").hidden ? document.getElementById("sheet") : document.getElementById("app");
    return [...top.querySelectorAll("button, a[href], select, input:not([type=checkbox])")]
      .filter(n => n.offsetParent !== null && !n.closest("[inert]") && n.id !== "sheet-backdrop")
      .map(n => { const b = n.getBoundingClientRect(); return {what: n.dataset.key || n.id || n.className, w: Math.round(b.width * 10) / 10, h: Math.round(b.height * 10) / 10}; })
      .filter(b => b.h < 43.5 || b.w < 39.5);
  });
  const vp = pg.viewport();
  assert.deepEqual(small, [], `${label} at ${vp.width}x${vp.height}: every control is a full touch target`);
}

/* What is on top (a sheet, or the result) holds the keyboard: the board under it is inert, focus
   is inside it, and Tab and Shift+Tab never leave it. */
export async function modalHolds(pg, which, label) {
  const at = () => pg.evaluate(id => {
    const top = document.getElementById(id), a = document.activeElement;
    return {open: !top.hidden, inside: top.contains(a), inert: document.getElementById("game").inert && document.querySelector(".topbar").inert,
            status: Boolean(document.getElementById("status").closest("[inert]")), what: a && (a.dataset.key || a.id || a.tagName)};
  }, which);
  let s = await at();
  assert.ok(s.open, `${label}: ${which} is open`);
  assert.ok(s.inert, `${label}: the board under the ${which} is inert`);
  assert.equal(s.status, false, `${label}: the status line stays live`);
  assert.ok(s.inside, `${label}: focus is inside the ${which} (on ${s.what})`);
  const seen = new Set();
  for (const key of ["Tab","Tab","Tab","Tab","Tab","Tab","Tab","Tab","Tab","Tab","Tab","Tab"]) { await pg.keyboard.press(key); s = await at(); seen.add(s.what); assert.ok(s.inside, `${label}: Tab stays in the ${which} (reached ${s.what})`); }
  for (let i = 0; i < 3; i++) { await pg.keyboard.down("Shift"); await pg.keyboard.press("Tab"); await pg.keyboard.up("Shift"); s = await at(); assert.ok(s.inside, `${label}: Shift+Tab stays in the ${which}`); }
  return seen;
}

/* What has the keyboard focus now: its data-key, id or tag. */
export const focused = pg => pg.evaluate(() => { const a = document.activeElement; return a && (a.dataset.key || a.id || a.tagName); });

/* AVR-267, the crew strip: every seat's identity, Captain, Party Host where the page knows it,
   whose turn it is, the radio state, the hand size and a reconnecting seat are words on the
   tile, at a readable size, and equal to the view. `host` is the Party Host's seat, or null. */
export async function crewLegible(pg, label, host = null) {
  const m = await pg.evaluate(() => {
    const g = ST.game;
    return {g: {seats: g.seats, captain: g.captain, turn: g.turn, stage: g.stage, result: Boolean(g.result), counts: g.hand_counts, away: g.away, names: Object.fromEntries(g.seats.map(s => [s, name(s)]))},
      tiles: [...document.querySelectorAll("#seats .seat")].map(n => {
        const part = c => { const x = n.querySelector(c); if (!x) return null; const cs = getComputedStyle(x); return {text: x.textContent, size: parseFloat(cs.fontSize), clipped: x.scrollWidth > x.clientWidth + 1, shown: cs.display !== "none" && cs.visibility !== "hidden"}; };
        return {seat: n.dataset.seat, name: part(".seat-name b"), crown: part(".crown"), hostTag: part(".host-tag"), pip: part(".turn-pip"), count: part(".seat-count"), radio: part(".seat-radio"), active: n.classList.contains("active"), said: n.getAttribute("aria-label")};
      })};
  });
  assert.deepEqual(m.tiles.map(t => t.seat), m.g.seats, `${label}: one tile per seat, in seat order`);
  const playing = !m.g.result && ["before_trick","in_trick"].includes(m.g.stage);
  for (const t of m.tiles) {
    const who = `${label}: the tile of ${m.g.names[t.seat]}`;
    assert.ok(t.name.shown && t.name.text === m.g.names[t.seat], `${who} shows the name`);
    assert.equal(Boolean(t.crown), t.seat === m.g.captain, `${who}: the Captain mark is on the captain and nobody else`);
    assert.equal(Boolean(t.hostTag), host !== null && t.seat === host, `${who}: the Party Host tag is on the host and nobody else`);
    if (t.hostTag) assert.ok(t.hostTag.shown && t.hostTag.text === "HOST" && t.hostTag.size >= 8, `${who}: the host tag is readable`);
    assert.equal(Boolean(t.pip) && t.active, playing && t.seat === m.g.turn, `${who}: turn emphasis is on the seat whose turn it is`);
    if (m.g.away.includes(t.seat)) assert.equal(t.count.text, "Reconnecting…", `${who} says it is reconnecting`);
    else assert.match(t.count.text, new RegExp(`^${m.g.counts[t.seat]}(c| cards) `), `${who} shows the hand size the view gives`);
    assert.ok(t.count.shown && t.count.size >= 10 && !t.count.clipped, `${who}: the hand size is readable (${t.count.size}px)`);
    assert.ok(t.radio && t.radio.shown && t.radio.text.length > 0 && t.radio.size >= 10 && !t.radio.clipped, `${who}: the radio state is readable`);
    assert.match(t.said, /\d+ cards, \d+ tricks/, `${who}: the tile says it to a screen reader too`);
  }
}

/* AVR-267, the shared trick: each card stays with its player, in play order from the lead; the
   lead and its suit are named; the winner shown is the one the server resolved, and an
   unfinished trick names no winner (the page never works one out). */
export async function trickShows(pg, label) {
  const m = await pg.evaluate(() => {
    const g = ST.game;
    return {trick: g.trick, last: g.last_trick, leader: g.leader, seats: g.seats, names: Object.fromEntries(g.seats.map(s => [s, name(s)])),
      caption: document.querySelector(".stage-caption strong")?.textContent || "", resolving: Boolean(g.resolving),
      slots: [...document.querySelectorAll("#trick .slot")].map(n => ({seat: n.dataset.seat, order: n.querySelector(".slot-order")?.textContent, name: n.querySelector(".slot-name")?.textContent,
        card: n.querySelector(".card")?.dataset.card || null, tag: n.querySelector(".slot-tag")?.textContent || "", winner: n.classList.contains("winner")}))};
  });
  if (!m.slots.length) return null;
  assert.equal(m.slots.length, m.seats.length, `${label}: every seat has a place in the trick`);
  assert.deepEqual(m.slots.map(s => s.order), m.slots.map((_, i) => String(i + 1)), `${label}: the play order is numbered`);
  for (const s of m.slots) assert.equal(s.name, m.names[s.seat], `${label}: each place names its player`);
  if (m.trick.length) {
    assert.equal(m.slots[0].seat, m.trick[0].seat, `${label}: the lead is first`);
    assert.equal(m.slots[0].tag, "LEAD", `${label}: the lead is marked`);
    for (const p of m.trick) assert.equal(m.slots.find(s => s.seat === p.seat).card, p.card, `${label}: each card is in its player's place`);
    assert.match(m.caption, new RegExp(`lead ${m.trick[0].card.split(":")[0].replace("submarine", "submarines")}`), `${label}: the lead suit is named`);
    assert.deepEqual(m.slots.filter(s => s.winner || s.tag === "WON"), [], `${label}: an unfinished trick names no winner`);
  } else if (m.last) {
    const won = m.slots.filter(s => s.winner);
    assert.deepEqual(won.map(s => [s.seat, s.tag]), [[m.last.winner, "WON"]], `${label}: the resolved winner is the server's and is marked`);
    for (const p of m.last.plays) assert.equal(m.slots.find(s => s.seat === p.seat).card, p.card, `${label}: each resolved card is in its player's place`);
    assert.match(m.caption, new RegExp(`^Trick ${m.last.index} · ${m.names[m.last.winner]} won · lead `), `${label}: the caption says who won and what was led`);
  }
  return m;
}

/* AVR-267, the hand: a card that may be played looks like every other card that may be played
   (same classes, same computed look, same structure: nothing marks one as better or worse); a
   card that may not is muted, still readable, cannot be chosen, and the reason is the view's
   own sentence, in words on the page. Legality is the server's list and nothing else. */
export async function legalCardsLookAlike(pg, label) {
  const m = await pg.evaluate(() => {
    const g = ST.game, legal = new Set(g.me.legal_cards);
    const look = n => { const cs = getComputedStyle(n); return {cls: [...n.classList].filter(c => !["blue","green","pink","yellow","submarine","sent"].includes(c)).sort().join(" "),
      opacity: cs.opacity, filter: cs.filter, borderStyle: cs.borderStyle, borderWidth: cs.borderWidth, shadow: cs.boxShadow.replace(/rgba?\([^)]*\)|color\([^)]*\)/g, "C"), transform: cs.transform, outline: cs.outlineStyle,
      kids: [...n.children].filter(c => !c.classList.contains("mark")).map(c => c.className).join(","), attrs: [...n.attributes].map(a => a.name).filter(a => !["class","aria-label","data-key","data-card","title"].includes(a)).sort().join(","), pressed: n.getAttribute("aria-pressed"), title: n.title}; };
    return {view: ui.handView, legal: [...legal], reason: g.me.play_reason, said: document.getElementById("hand-reason").textContent,
      cards: [...document.querySelectorAll("#hand button.card")].map(n => ({card: n.dataset.card, disabled: n.disabled, text: n.textContent, size: parseFloat(getComputedStyle(n.querySelector(".rank")).fontSize), ...look(n)}))};
  });
  const open = m.cards.filter(c => !c.disabled), shut = m.cards.filter(c => c.disabled);
  assert.deepEqual(open.map(c => c.card).sort(), m.cards.map(c => c.card).filter(c => m.legal.includes(c)).sort(), `${label}: the cards that can be chosen are exactly the legal cards the server lists`);
  const same = c => JSON.stringify([c.cls, c.opacity, c.filter, c.borderStyle, c.borderWidth, c.shadow, c.transform, c.outline, c.kids, c.attrs, c.pressed, c.title]);
  assert.ok(new Set(open.map(same)).size <= 1, `${label}: every legal card looks the same before it is committed: ${[...new Set(open.map(same))].join(" | ")}`);
  for (const c of shut) {
    assert.ok(Number(c.opacity) < 1 && Number(c.opacity) >= .4, `${label}: a card that cannot be played is muted but readable`);
    assert.ok(c.text.length > 0 && c.size >= 14, `${label}: a muted card still shows its rank`);
    assert.ok(c.title.length > 0, `${label}: a muted card has a reason`);
  }
  if (shut.length) assert.ok(m.said.length > 0, `${label}: the reason is words on the page, not only a title`);
  if (m.reason) assert.equal(m.said, m.reason, `${label}: the reason on the page is the one the server gives`);
  return m;
}
