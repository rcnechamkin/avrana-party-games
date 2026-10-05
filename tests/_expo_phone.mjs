// Shared by the EXPO browser playtests: the one-viewport contract of AVR-275, measured.
import assert from "node:assert/strict";

// Representative narrow phones. The first is the size named by AVR-266 and AVR-275. The short
// ones are what a phone browser leaves when its own bars are showing (a 390 x 844 iPhone in
// Safari draws about 390 x 664).
export const PHONES = [
  {width:360,height:740}, {width:390,height:664}, {width:375,height:667},
  {width:412,height:915}, {width:360,height:600},
];

const BOARD = ["status","mission-title","trick-count","objectives","seats","stage","hand","dock"];

/* Ordinary play needs no vertical scrolling: nothing scrolls as a page, and the mission, the
   trick counter, the status line, the objectives, the crew, the stage (the trick), every card of
   the hand and the dock are all inside the viewport, at a size a finger can use. */
export async function oneViewport(pg, label) {
  // A toast (the shared Hub.toast) is a fixed, passing notice outside the board: wait it out.
  await pg.waitForFunction(() => !document.querySelector(".toast"), {timeout:6000});
  const m = await pg.evaluate(ids => {
    const box = n => { const b = n.getBoundingClientRect(); return {top:b.top,bottom:b.bottom,left:b.left,right:b.right,width:b.width,height:b.height}; };
    const room = document.getElementById("avrana-game-room");
    const scrollers = [document.scrollingElement, document.body, room, document.getElementById("app")].filter(Boolean);
    return {
      vw: innerWidth, vh: innerHeight,
      overflow: scrollers.map(n => ({y: n.scrollHeight - n.clientHeight, x: n.scrollWidth - n.clientWidth, top: n.scrollTop})),
      parts: Object.fromEntries(ids.map(id => { const n = document.getElementById(id); return [id, n && n.offsetParent !== null ? box(n) : null]; })),
      cards: [...document.querySelectorAll("#hand .card")].map(box),
      stageText: document.getElementById("stage")?.innerText || "",
    };
  }, BOARD);
  const at = `${label} at ${m.vw}x${m.vh}`;
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
