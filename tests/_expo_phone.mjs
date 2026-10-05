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
  try { await criticalTextWhole(pg, "at its fullest"); await check(); } finally { await pg.evaluate(st => render(st), real); }
}

/* The sentences a player must be able to read are read whole: the status line (the one live
   instruction), a pending decision's question and who it waits for, the radio's sentence and
   rule, and the reason the hand cannot be played. None is cut by an ellipsis, a line clamp, its
   own box, a scrolled panel or the edge of the screen. */
export async function criticalTextWhole(pg, label) {
  const cut = await pg.evaluate(() => {
    const out = [], app = document.getElementById("app").getBoundingClientRect();
    const sel = ["#status", "#status-now", "#hand-reason", '[data-key="agree"]', '[data-key="decline"]', ".dock-label", ".decision .choice-row", ".decision > p", ".decision .why", ".radio-ask", ".radio-console .why"];
    for (const s of sel) for (const n of document.querySelectorAll(s)) {
      if (!n.textContent.trim() || n.offsetParent === null || n.closest("[hidden]")) continue;
      const b = n.getBoundingClientRect(), why = [];
      if (n.scrollWidth > n.clientWidth + 1 && getComputedStyle(n).display !== "inline") why.push("wider than its box");
      if (n.scrollHeight > n.clientHeight + 1 && getComputedStyle(n).display !== "inline") why.push("taller than its box");
      if (b.width < 1 || b.height < 1) why.push("no size");
      if (b.left < app.left - .5 || b.right > app.right + .5 || b.top < -.5 || b.bottom > innerHeight + .5) why.push("off the screen");
      for (let p = n.parentElement; p && p.id !== "app"; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (![cs.overflowX, cs.overflowY].some(v => v !== "visible")) continue;
        const pb = p.getBoundingClientRect();
        if (b.top < pb.top - 1 || b.bottom > pb.bottom + 1 || b.left < pb.left - 1 || b.right > pb.right + 1) why.push(`outside ${p.id || p.className}`);
      }
      if (why.length) out.push(`${s} "${n.textContent.trim().slice(0, 60)}": ${why.join(", ")}`);
    }
    return {out, status: document.getElementById("status-now").textContent};
  });
  const vp = pg.viewport();
  assert.ok(cut.status.length > 0, `${label}: the status line says something`);
  assert.deepEqual(cut.out, [], `${label} at ${vp.width}x${vp.height}: every critical sentence is whole (status: "${cut.status}")`);
}

/* The longest status sentences the page can produce, with the longest names the lobby allows, on
   every phone size: each is drawn from a copy of the real state with one thing changed, and each
   is whole, with everything else still on one screen. Returns the sentences that were checked. */
export async function longestStatusesFit(pg, label, shots = null) {
  const real = await pg.evaluate(() => ST), size = pg.viewport(), said = new Set(); let answered = 0;
  const cases = await pg.evaluate(st => {
    const g = st.game, me = g.me && g.me.seat, others = g.seats.filter(s => s !== "tonoja" && s !== me);
    const idle = {proposal: null, away: [], result: null, resolving: null};
    const ask = (payload, more = {}) => ({...idle, proposal: {payload, votes: [], recipient: null, ...more}});
    const stuck = reason => g.me ? {me: {...g.me, legal_cards: [], play_reason: reason}} : {};
    const crew = g.seats.filter(s => s !== "tonoja").length > 2, open = crew ? {kind: "distress", direction: "right"} : {kind: "begin"};
    const preparing = {...idle, stage: "assistance", trick: [], last_trick: null, ...stuck("Finish mission preparation before playing.")};
    const late = {...idle, stage: "before_trick", trick: [], expiry: 1, resolving: g.last_trick ? {trick: g.last_trick.index, until: 2} : null, ...stuck("The trick is being resolved.")};
    const watching = {me: null};
    const list = [
      ["one seat away", {...idle, away: others.slice(0, 1), ...stuck("Waiting for the crew to reconnect.")}],
      ["every other seat away", {...idle, away: others, ...stuck("Waiting for the crew to reconnect.")}],
      // Distress is a crew of three or more; two players are asked to begin.
      [crew ? "distress asked" : "begin asked", ask(open)],
      ["all tasks to one seat asked", ask({kind: "assign", task: "all", owner: others[0]})],
      ["next mission asked", ask({kind: "next", mission: 32})],
      ["waiting for one answer", ask(open, {votes: g.seats.filter(s => s !== "tonoja" && s !== others[0])})],
      ["waiting for every other answer", ask(open, {votes: me ? [me] : []})],
      ["a captain who decides", {...idle, stage: "allocation", trick: [], selector: g.captain, mission: {...g.mission, allocation: "captain_one"}, ...stuck("Finish mission preparation before playing.")}],
      ["tasks assigned", {...idle, stage: "assistance", trick: [], begin_at: null, ...stuck("Finish mission preparation before playing.")}],
      ["another seat to play", {...idle, stage: "in_trick", turn: others[0], ...stuck("It is another crew member’s turn.")}],
      ["a held trick after the deadline", late],
      // Someone with no seat reads the same sentences after "Watching · ".
      ["watching: a held trick after the deadline", {...late, ...watching}],
      ["watching: one seat away", {...idle, away: others.slice(0, 1), ...watching}],
      // A Party round: the host's Begin opens after a moment in which the crew may ask for distress.
      ["the host's Begin is counting down", {...preparing, lifecycle: "host", begin_at: Date.now() / 1000 + 9}],
      ["watching: the host's Begin is counting down", {...preparing, lifecycle: "host", begin_at: Date.now() / 1000 + 9, ...watching}],
    ];
    if (g.seats.includes("tonoja")) list.push(["the captain to play for Tonoja", {...idle, stage: "in_trick", turn: "tonoja", ...stuck("It is another crew member’s turn.")}],
      ["watching: the captain to play for Tonoja", {...idle, stage: "in_trick", turn: "tonoja", ...watching}]);
    if (me && me !== g.captain) list.push(["the captain's offer", ask({kind: "assign", task: "all", owner: me}, {recipient: me})]);
    return list.map(([what, patch]) => [what, {...st, players: st.players.map(p => ({...p, name: "WWWWWWWWWWWWWW"})), game: {...g, ...patch}}]);
  }, real);
  try {
    for (const phone of PHONES) {
      await pg.setViewport({...size, ...phone});
      for (const [what, st] of cases) {
        await pg.evaluate(s => render(s), st);
        const where = `${label}: ${what}`;
        await criticalTextWhole(pg, where);
        await oneViewport(pg, where);
        // A decision this viewer must answer: both answers are whole, on screen and full targets.
        if (await pg.evaluate(() => Boolean(ST.game.proposal && !ST.game.result && mustAnswer(ST.game)))) {
          for (const k of ["agree", "decline"]) await onScreen(pg, k, where);
          await touchTargets(pg, where); answered++;
        }
        said.add(await pg.evaluate(() => document.getElementById("status-now").textContent));
        if (shots) await pg.screenshot({path: `${shots}/status-${phone.width}x${phone.height}-${what.replace(/[^a-z]+/gi, "-")}.png`});
      }
    }
  } finally { await pg.setViewport(size); await pg.evaluate(st => render(st), real); }
  if (real.game.me) assert.ok(answered >= PHONES.length, `${label}: a decision to answer was drawn at every size`);
  return [...said];
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
        // The room the name's row leaves for the name: the row less the marks beside it.
        const row = n.querySelector(".seat-name"), marks = [...row.children].filter(c => c.tagName !== "B");
        const room = row.clientWidth - marks.reduce((sum, c) => sum + c.getBoundingClientRect().width, 0) - (parseFloat(getComputedStyle(row).columnGap) || 0) * marks.length;
        return {seat: n.dataset.seat, room, name: part(".seat-name b"), crown: part(".crown"), hostTag: part(".host-tag"), pip: part(".turn-pip"), count: part(".seat-count"), radio: part(".seat-radio"), active: n.classList.contains("active"), said: n.getAttribute("aria-label")};
      })};
  });
  assert.deepEqual(m.tiles.map(t => t.seat), m.g.seats, `${label}: one tile per seat, in seat order`);
  const playing = !m.g.result && ["before_trick","in_trick"].includes(m.g.stage);
  for (const t of m.tiles) {
    const who = `${label}: the tile of ${m.g.names[t.seat]}`;
    assert.ok(t.name.shown && t.name.text === m.g.names[t.seat], `${who} shows the name`);
    // No mark beside it (turn, Captain, Party Host) costs a tile its name: the name is whole,
    // and the row keeps room for one whatever else the seat is.
    assert.ok(!t.name.clipped, `${who}: the name is not cut short`);
    assert.ok(t.room >= 28, `${who}: the name keeps at least 28 px of its row (${Math.round(t.room)} px)`);
    assert.equal(Boolean(t.crown), t.seat === m.g.captain, `${who}: the Captain mark is on the captain and nobody else`);
    assert.equal(Boolean(t.hostTag), host !== null && t.seat === host, `${who}: the Party Host tag is on the host and nobody else`);
    if (t.hostTag) assert.ok(t.hostTag.shown && t.hostTag.text === (m.g.seats.length > 2 ? "H" : "HOST") && t.hostTag.size >= 8 && !t.hostTag.clipped, `${who}: the host tag is readable`);
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
    return {leading: g.trick_leading, sent: "trick_leading" in g, result: Boolean(g.result), live: document.getElementById("status").textContent,
      handMarks: document.querySelectorAll('#hand .ahead, #hand .slot-ahead, #hand [class*="winning"], #hand [class*="leading"]').length,
      trick: g.trick, last: g.last_trick, leader: g.leader, seats: g.seats, names: Object.fromEntries(g.seats.map(s => [s, name(s)])),
      caption: document.querySelector(".stage-caption strong")?.textContent || "", resolving: Boolean(g.resolving),
      slots: [...document.querySelectorAll("#trick .slot")].map(n => ({seat: n.dataset.seat, order: n.querySelector(".slot-order")?.textContent, name: n.querySelector(".slot-name")?.textContent,
        card: n.querySelector(".card")?.dataset.card || null, tag: n.querySelector(".slot-tag")?.textContent || "", winner: n.classList.contains("winner"),
        ahead: (a => { if (!a) return null; const b = a.getBoundingClientRect(), box = n.getBoundingClientRect(), t = n.querySelector(".slot-tag")?.getBoundingClientRect();
          return {text: a.textContent, size: parseFloat(getComputedStyle(a).fontSize), inside: b.left >= box.left && b.right <= box.right + .5 && b.top >= box.top && b.bottom <= box.bottom + .5 && a.scrollWidth <= a.clientWidth + 1,
            clear: !t || b.bottom <= t.top + .5 || b.top >= t.bottom - .5 || b.right <= t.left + .5 || b.left >= t.right - .5, outlined: n.classList.contains("ahead")}; })(n.querySelector(".slot-ahead"))}))};
  });
  // The seat winning an unfinished trick is the server's field, drawn as a word on that seat's
  // place and on no other, and said once in the live region. Nothing in the hand is marked by it.
  assert.ok(m.sent, `${label}: the view carries trick_leading`);
  assert.equal(m.leading !== null, m.trick.length > 0 && !m.result && !m.resolving, `${label}: a seat is leading exactly while an unfinished trick is on the table`);
  assert.deepEqual(m.slots.filter(s => s.ahead).map(s => s.seat), m.leading && m.slots.length ? [m.leading] : [], `${label}: the WINNING tag is on the seat the view names and on no other`);
  for (const s of m.slots.filter(s => s.ahead)) assert.deepEqual(s.ahead, {text: "WINNING", size: s.ahead.size, inside: true, clear: true, outlined: true}, `${label}: the WINNING tag is a readable word inside its place, clear of the LEAD tag`);
  for (const s of m.slots.filter(s => s.ahead)) assert.ok(s.ahead.size >= 8);
  assert.equal(/ is winning the trick\./.test(m.live), m.leading !== null, `${label}: the live region says who is winning only while someone is`);
  if (m.leading) assert.ok(m.live.includes(`${m.names[m.leading]} is winning the trick.`), `${label}: and names the seat the view names`);
  assert.equal(m.handMarks, 0, `${label}: nothing in the hand is marked by who is winning`);
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
