"use strict";
/* EXPO's presentation director (AVR-267).

   It turns the server's semantic events (AVR-246) into presentation: event -> intensity tier ->
   effects, scaled by a fidelity tier. It is NOT part of the game:

     * It reads a frozen copy of the view and the page; it is handed no connection and contains
       no code that sends anything. The only code that sends is the client's intent senders.
     * It decides no rule and computes no outcome: every fact it shows is a field of an event or
       of the view.
     * Everything it does is transient decoration (Web Animations on transform and opacity, the
       briefing strip it owns, haptics). The board the client draws from the view is complete and
       correct without it: turned off, or after it throws, nothing about the game is missing.
     * It never delays input: nothing here disables, covers or waits for a control.

   Events are consumed by `seq`. The first view after a load or a reconnect, a gap, a rewind, a
   batch that arrives while the tab is hidden and a new attempt all settle straight to the
   authoritative state: no stale animation is replayed.

   Loaded as a plain script (window.ExpoDirector) and by the Node tests (module.exports). */
(function (root) {
  const VERSION = 1;

  // ---- event -> intensity tier (what kind of beat an event is; durations are bounded per tier) --
  const INTENSITY = Object.freeze({
    TURN_STARTED: "micro", CARD_PLAYED: "micro", PLAYER_RECONNECTED: "micro", OBJECTIVE_PROGRESS: "micro",
    TRICK_RESOLVED: "gameplay", COMMUNICATION_SENT: "gameplay", OBJECTIVE_COMPLETED: "gameplay",
    OBJECTIVE_FAILED: "gameplay", MISSION_MODIFIER_ACTIVATED: "gameplay",
    MISSION_SUCCESS: "cinematic", MISSION_FAILURE: "cinematic",
  });
  const TIER_MS = Object.freeze({micro: [100, 400], gameplay: [500, 1500], cinematic: [2000, 6000]});
  // Milliseconds. A trick's resolution is shortened to fit the server's hold (`resolving.until`),
  // never the other way round; below `trickMin` it is not played at all.
  const TIMING = Object.freeze({
    cardArrive: 300, handClose: 220, turn: 280, reconnect: 320, progress: 300,
    trick: 700, trickMin: 250, trickMargin: 60,
    radio: 900, objective: 600, modifier: 600,
    result: 2600, briefing: 5600, briefingShort: 2200,
  });
  const MAX_BATCH = 24;           // more fresh events than one command can make: a backlog, settle
  const FIDELITIES = Object.freeze(["high", "medium", "low"]);

  /* Which fidelity tier this browser gets. Reduced motion (the system's or the per-browser
     setting) always wins; then an explicit choice; then what the device says about itself.
       high    movement, pulses, ambient stage, cinematic beats
       medium  opacity pulses only: no movement, no ambient, no cinematic beats
       low     static: words and state only
       off     the director does not run at all (diagnostic; same board) */
  function fidelity(env) {
    if (env.stored === "off") return "off";
    if (env.reduced || !env.animate) return "low";
    if (FIDELITIES.includes(env.stored)) return env.stored;
    if (env.saveData || (env.memory && env.memory <= 2) || (env.cores && env.cores <= 2)) return "medium";
    return "high";
  }

  const freshCursor = () => ({primed: false, attempt: null, seq: 0});
  const briefable = g => !g.result && !g.last_trick && !(g.trick || []).length
    && ["allocation", "prediction", "assistance"].includes(g.stage);

  /* The planner, a pure function: (cursor, view, env) -> {cursor, cues, why}.
     `cues` are the fresh events worth presenting, oldest first, each with its intensity tier;
     `why` says how the batch was classified. Whatever it returns, the cursor ends on the newest
     sequence number, so nothing is ever presented twice. */
  function advance(cursor, view, env = {}) {
    const g = view && view.game;
    if (!g) return {cursor: {primed: true, attempt: null, seq: 0}, cues: [], why: "no-table"};
    const top = Number(g.event_seq) || 0;
    const next = {primed: true, attempt: g.attempt, seq: top};
    const brief = () => briefable(g) && !env.briefed
      ? [{type: "BRIEFING", tier: "cinematic", seq: top, short: (g.attempts || 1) > 1}] : [];
    if (!cursor.primed) return {cursor: next, cues: env.hidden ? [] : brief(), why: "first-view"};
    if (cursor.attempt !== g.attempt) return {cursor: next, cues: env.hidden ? [] : brief(), why: "new-attempt"};
    if (top < cursor.seq) return {cursor: next, cues: [], why: "rewound"};
    const fresh = (Array.isArray(g.events) ? g.events : []).filter(e => e && e.seq > cursor.seq).sort((a, b) => a.seq - b.seq);
    if (!fresh.length) return {cursor: next, cues: [], why: top > cursor.seq ? "gap" : "duplicate"};
    const whole = fresh.every((e, i) => e.seq === cursor.seq + 1 + i) && fresh[fresh.length - 1].seq === top;
    if (!whole) return {cursor: next, cues: [], why: "gap"};
    if (env.hidden) return {cursor: next, cues: [], why: "hidden"};
    if (fresh.length > MAX_BATCH) return {cursor: next, cues: [], why: "backlog"};
    const cues = fresh.filter(e => INTENSITY[e.type]).map(e => ({...e, tier: INTENSITY[e.type]}));
    return {cursor: next, cues, why: "live"};
  }

  /* How long a resolved trick may be presented: inside the server's hold, or not at all.
     A trick that ended the mission is not held (the result is its own boundary). */
  function trickBudget(g, nowMs) {
    if (g.result) return TIMING.trick;
    const until = g.resolving && g.resolving.until;
    if (typeof until !== "number") return 0;
    const left = until * 1000 - nowMs - TIMING.trickMargin;
    return left < TIMING.trickMin ? 0 : Math.min(TIMING.trick, Math.floor(left));
  }

  function create(ctx) {
    const doc = ctx.doc, prefs = ctx.prefs || {}, slots = ctx.slots || {};
    const clock = ctx.clock || (() => Date.now());
    const store = ctx.store || null;          // sessionStorage-like, for "this briefing was shown"
    const stats = {errors: 0, disabled: false, fidelity: "low", performed: [], settled: [], lastTrick: null, haptics: [], sounds: []};
    let cursor = freshCursor(), rects = null, gesture = false, cine = [], moving = false, briefingOn = false;
    const settled = why => { stats.settled.push(why); if (stats.settled.length > 30) stats.settled.shift(); };

    const env = () => ({
      stored: ctx.stored ? ctx.stored() : null, reduced: Boolean(prefs.reducedFx),
      animate: Boolean(ctx.canAnimate !== undefined ? ctx.canAnimate : (root.Element && root.Element.prototype.animate)),
      memory: ctx.caps && ctx.caps.memory, cores: ctx.caps && ctx.caps.cores, saveData: ctx.caps && ctx.caps.saveData,
    });
    const level = () => stats.disabled ? "off" : fidelity(env());
    function publish() {
      stats.fidelity = level();
      const el = doc.documentElement;
      if (el && el.dataset) {
        if (el.dataset.expoFx !== stats.fidelity) el.dataset.expoFx = stats.fidelity;
        if (doc.hidden) el.dataset.expoPaused = "1"; else delete el.dataset.expoPaused;
      }
      return stats.fidelity;
    }

    // ---- the page, read-only except for the decoration this file owns --------------------------
    const quote = v => String(v).replace(/["\\]/g, "\\$&");
    const q = sel => doc.querySelector(sel);
    const tile = seat => q(`#seats [data-seat="${quote(seat)}"]`);
    const slot = seat => q(`#trick [data-seat="${quote(seat)}"]`);
    const fxOf = node => node && node.querySelector(":scope > .fx");
    const box = node => node && node.getBoundingClientRect();
    function play(node, frames, options, tag) {
      if (!node || typeof node.animate !== "function") return null;
      const a = node.animate(frames, {easing: "cubic-bezier(.2,.7,.2,1)", ...options});
      a.id = "expo-fx:" + tag;
      return a;
    }
    const pulse = (node, ms, tag, delay = 0, peak = .9) => play(fxOf(node), [{opacity: 0}, {opacity: peak, offset: .35}, {opacity: 0}], {duration: ms, delay}, tag);
    // A ring grows a little as it fades: movement, so the medium tier gets the plain pulse.
    const ring = (node, ms, tag, delay = 0) => !moving ? pulse(node, ms, tag, delay) : play(fxOf(node), [{opacity: 0, transform: "scale(1)"}, {opacity: .9, transform: "scale(1.04)", offset: .3}, {opacity: 0, transform: "scale(1.16)"}], {duration: ms, delay}, tag);
    const note = (cue, effect, ms) => { stats.performed.push({seq: cue.seq, type: cue.type, tier: cue.tier, effect, ms}); if (stats.performed.length > 60) stats.performed.shift(); };

    // ---- sound and haptics: slots, never before a gesture, never against a preference ----------
    function haptic(name) {
      const pattern = slots.haptics && slots.haptics[name];
      if (!pattern || !gesture || prefs.haptics === false) return false;
      try { if (ctx.vibrate) ctx.vibrate(pattern); } catch { /* optional */ }
      stats.haptics.push(name); if (stats.haptics.length > 30) stats.haptics.shift();
      return true;
    }
    function sound(name) {
      const slotted = slots.audio && slots.audio[name];
      if (!slotted || !slotted.src || !gesture || prefs.sound === false || !ctx.audio) return false;   // an empty slot is silent
      try { ctx.audio(slotted.src, slotted.volume); } catch { /* optional */ }
      stats.sounds.push(name); if (stats.sounds.length > 30) stats.sounds.shift();
      return true;
    }
    const feel = name => { haptic(name); sound(name); };

    // ---- effects --------------------------------------------------------------------------------
    const mine = (g, seat) => Boolean(g.me && (seat === g.me.seat || (seat === "tonoja" && g.captain === g.me.seat)));
    function travel(card, seat, target) {
      // Where a played card comes from: the place it had in this hand, or its player's tile.
      const from = (rects && rects.hand.get(card)) || (rects && rects.tiles.get(seat)), to = box(target);
      if (!from || !to || !to.width) return null;
      const dx = from.left + from.width / 2 - (to.left + to.width / 2), dy = from.top + from.height / 2 - (to.top + to.height / 2);
      return `translate(${dx.toFixed(1)}px,${dy.toFixed(1)}px) scale(.7)`;
    }
    function closeHand() {
      if (!rects) return;
      for (const node of doc.querySelectorAll("#hand [data-card]")) {
        const was = rects.hand.get(node.dataset.card), now = box(node);
        if (!was || !now) continue;
        const dx = was.left - now.left, dy = was.top - now.top;
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) play(node, [{transform: `translate(${dx.toFixed(1)}px,${dy.toFixed(1)}px)`}, {transform: "none"}], {duration: TIMING.handClose}, "hand");
      }
    }
    function cardPlayed(cue, g, high, inTrick) {
      if (inTrick) return;                       // the last card of a trick arrives inside the resolution
      const target = slot(cue.seat), card = target && target.querySelector(".card");
      if (high && card) {
        const from = travel(cue.card, cue.seat, card);
        if (from) play(card, [{transform: from, opacity: .5}, {transform: "none", opacity: 1}], {duration: TIMING.cardArrive}, "card");
      }
      pulse(tile(cue.seat), TIMING.cardArrive, "tile");
      feel("card.play");
      note(cue, "card-to-trick", TIMING.cardArrive);
    }
    function trickResolved(cue, g, high, last) {
      const D = trickBudget(g, clock());
      stats.lastTrick = {seq: cue.seq, budget: D, until: g.resolving ? g.resolving.until : null, started: clock(), ends: clock() + D};
      if (!D) { settled("trick-late"); return 0; }
      for (const p of cue.plays || []) {
        const s = slot(p.seat), card = s && s.querySelector(".card");
        if (!s) continue;
        const won = p.seat === cue.winner, arriving = last && last.seat === p.seat;
        if (String(p.card).split(":")[0] === cue.lead_suit) pulse(s, D * .35, "trick", D * .2, .8);     // the lead suit, reinforced
        if (!high || !card) continue;
        const from = arriving ? travel(p.card, p.seat, card) : null;
        const frames = from ? [{transform: from, opacity: .5, offset: 0}, {transform: "none", opacity: 1, offset: .28}] : [{transform: "none", opacity: 1, offset: 0}];
        // The rest moves to where the board already draws it: the winner forward, the others tucked.
        if (won) frames.push({transform: "none", opacity: 1, offset: .45}, {transform: "scale(1.14)", opacity: 1, offset: .68});
        else frames.push({transform: "none", opacity: 1, offset: .55});
        play(card, frames, {duration: D, easing: "ease-out"}, "trick");
      }
      ring(slot(cue.winner), D * .45, "trick", D * .45);
      pulse(tile(cue.winner), D * .25, "trick", D * .75);
      feel("trick.resolve");
      note(cue, "trick-resolution", D);
      return D;
    }
    function radio(cue, g, high) {
      const sender = tile(cue.seat);
      ring(sender, 450, "radio"); ring(sender, 450, "radio", 220);
      pulse(q("#radio-chip"), 600, "radio");
      if (g.me && g.me.seat === cue.seat) {
        const mark = q(`#hand [data-card="${quote(cue.card)}"] .mark`);
        if (high) play(mark, [{transform: "scale(.4)", opacity: 0}, {transform: "scale(1.25)", opacity: 1, offset: .6}, {transform: "none", opacity: 1}], {duration: 420}, "radio");
        feel("radio.send");
      } else {
        pulse(q("#mission-stage"), TIMING.radio, "radio", 0, .55);       // the others: a short radio pulse
        feel("radio.receive");
      }
      note(cue, "radio-burst", TIMING.radio);
    }
    function objective(cue, delay) {
      const ms = cue.type === "OBJECTIVE_PROGRESS" ? TIMING.progress : TIMING.objective;
      pulse(q("#objectives"), ms, "objective", delay);
      const row = cue.objective && q(`#objectives [data-task="${quote(cue.objective)}"]`);
      if (row) play(row, [{opacity: 1}, {opacity: .45, offset: .3}, {opacity: 1}], {duration: ms, delay}, "objective");
      if (cue.type !== "OBJECTIVE_PROGRESS") feel(cue.type === "OBJECTIVE_COMPLETED" ? "objective.complete" : "objective.fail");
      note(cue, "objective-beat", ms);
    }
    function ending(cue, g, high) {
      const failed = cue.type === "MISSION_FAILURE";
      feel(failed ? "mission.failure" : "mission.success");
      const result = q("#result");
      if (!result || result.hidden) return;
      if (!high) { pulse(result, TIMING.objective, "result"); note(cue, "result-pulse", TIMING.objective); return; }
      // A cinematic beat that covers nothing: every control of the result is usable from its
      // first frame. Any tap or key finishes it.
      const T = TIMING.result;
      cine.push(play(fxOf(result), failed
        ? [{opacity: 0}, {opacity: .6, offset: .08}, {opacity: .1, offset: .2}, {opacity: .5, offset: .3}, {opacity: .05, offset: .5}, {opacity: .3, offset: .62}, {opacity: 0}]
        : [{opacity: 0}, {opacity: .55, offset: .25}, {opacity: .2, offset: .6}, {opacity: 0}], {duration: T, easing: "linear"}, "cine"));
      cine.push(play(result.querySelector(".result-card"), [{transform: "translateY(14px)", opacity: .55}, {transform: "none", opacity: 1}], {duration: 520}, "cine"));
      cine.push(play(result.querySelector(".result-mark"), [{transform: "scale(.4)", opacity: 0}, {transform: "scale(1.18)", opacity: 1, offset: .7}, {transform: "none", opacity: 1}], {duration: 700, delay: 120, fill: "backwards"}, "cine"));
      [...result.querySelectorAll(".result-facts > *")].slice(0, 6).forEach((n, i) =>
        cine.push(play(n, [{opacity: .2, transform: "translateY(6px)"}, {opacity: 1, transform: "none"}], {duration: 320, delay: 520 + i * 300, fill: "backwards"}, "cine")));
      note(cue, failed ? "failure-cinematic" : "success-cinematic", T);
    }
    function briefing(cue, g) {
      // Mission start, inside the mission stage only: the board and every control under it stay
      // live, and a tap or a key anywhere ends it early. Its words are all on the board already.
      const stage = q("#mission-stage"), strip = q("#briefing"), body = stage && stage.querySelector(".mstage-body");
      if (!stage || !strip) return;
      const T = cue.short ? TIMING.briefingShort : TIMING.briefing;
      const who = seat => seat === "tonoja" ? "Tonoja" : ((ctx.nameOf && ctx.nameOf(seat)) || seat);
      const tasks = (g.tasks || []).length;
      const lines = cue.short
        ? [`Mission ${g.mission.id} · attempt ${g.attempts || 1}`, `Captain ${who(g.captain)}`]
        : ["Radio check", `Mission ${g.mission.id}`, `Captain ${who(g.captain)}`,
           (ctx.conditions && ctx.conditions(g)) || "", tasks ? `${tasks} objective${tasks === 1 ? "" : "s"}` : "One shared objective"].filter(Boolean);
      strip.replaceChildren(...lines.map(text => { const p = doc.createElement("p"); p.textContent = text; return p; }));
      strip.hidden = false;
      const step = T / lines.length;
      [...strip.children].forEach((p, i) => cine.push(play(p, [{opacity: 0, transform: "translateY(8px)"}, {opacity: 1, transform: "none", offset: .2}, {opacity: 1, transform: "none", offset: .8}, {opacity: 0, transform: "translateY(-6px)"}],
        {duration: step, delay: i * step, fill: "both", easing: "ease-out"}, "cine")));
      const veil = play(body, [{opacity: 1}, {opacity: .1, offset: .06}, {opacity: .1, offset: .94}, {opacity: 1}], {duration: T, easing: "linear"}, "cine");
      cine.push(veil);
      briefingOn = true;
      const done = () => { briefingOn = false; strip.hidden = true; strip.replaceChildren(); };
      if (veil && veil.finished) veil.finished.then(done, done); else done();
      // The crew arrives and the cards are dealt early, so the hand is readable while the rest plays.
      [...doc.querySelectorAll("#seats [data-seat]")].forEach((n, i) => cine.push(play(n, [{opacity: .2, transform: "translateY(-6px)"}, {opacity: 1, transform: "none"}], {duration: 300, delay: Math.min(T * .1, 500) + i * 90, fill: "backwards"}, "cine")));
      [...doc.querySelectorAll("#hand [data-card]")].forEach((n, i) => cine.push(play(n, [{opacity: .25, transform: "translateY(10px)"}, {opacity: 1, transform: "none"}], {duration: 260, delay: Math.min(T * .16, 900) + i * 45, fill: "backwards"}, "cine")));
      cine.push(ring(tile(g.captain), 600, "cine", cue.short ? step : step * 2));
      feel("mission.brief");
      note(cue, "briefing", T);
    }
    function skip() {
      const running = cine.filter(Boolean); cine = [];
      for (const a of running) { try { a.finish(); } catch { /* already over */ } }
    }

    function perform(cues, g) {
      const tier = publish();
      if (tier === "off") return;
      const high = tier === "high", still = tier === "low";
      moving = high;
      const resolved = cues.find(c => c.type === "TRICK_RESOLVED");
      const last = resolved ? cues.filter(c => c.type === "CARD_PLAYED").pop() : null;
      let hold = 0;
      for (const cue of cues) {
        if (still) {                 // static: the words are on the board; only the felt cue is left
          if (cue.type === "TURN_STARTED" && mine(g, cue.seat)) haptic("turn.mine");
          continue;
        }
        switch (cue.type) {
          case "BRIEFING": if (high) briefing(cue, g); break;
          case "CARD_PLAYED": cardPlayed(cue, g, high, Boolean(resolved)); if (high) closeHand(); break;
          case "TRICK_RESOLVED": hold = trickResolved(cue, g, high, last); break;
          case "TURN_STARTED":
            pulse(tile(cue.seat), TIMING.turn, "turn");
            if (mine(g, cue.seat)) { pulse(q("#hand-panel"), TIMING.turn, "turn", 0, .6); feel("turn.mine"); }
            note(cue, "turn", TIMING.turn); break;
          case "PLAYER_RECONNECTED": pulse(tile(cue.seat), TIMING.reconnect, "tile"); note(cue, "reconnect", TIMING.reconnect); break;
          case "COMMUNICATION_SENT": radio(cue, g, high); break;
          case "OBJECTIVE_PROGRESS": case "OBJECTIVE_COMPLETED": case "OBJECTIVE_FAILED": objective(cue, hold * .8); break;
          case "MISSION_MODIFIER_ACTIVATED": pulse(q("#mission-stage"), TIMING.modifier, "modifier", 0, .5); note(cue, "modifier", TIMING.modifier); break;
          case "MISSION_SUCCESS": case "MISSION_FAILURE": ending(cue, g, high); break;
          default: break;
        }
      }
    }

    const signature = g => [g.attempt, g.mission && g.mission.id, g.captain, (g.seats || []).join(",")].join(":");
    function briefed(g) {
      // One briefing per attempt and tab: a reload in the middle of the preparation is not a
      // mission start.
      if (!store || !g) return false;
      try { const key = signature(g), seen = store.getItem("expo-briefed") === key; store.setItem("expo-briefed", key); return seen; }
      catch { return false; }
    }

    const api = {
      stats,
      get fidelity() { return publish(); },
      /* Before the client redraws: remember where the hand's cards and the crew's tiles are, so
         a played card can travel from its place. One read per state, never per frame. */
      before() {
        rects = null;
        if (publish() !== "high" || doc.hidden) return;
        rects = {hand: new Map(), tiles: new Map()};
        for (const n of doc.querySelectorAll("#hand [data-card]")) rects.hand.set(n.dataset.card, box(n));
        for (const n of doc.querySelectorAll("#seats [data-seat]")) rects.tiles.set(n.dataset.seat, box(n));
      },
      /* After the client has drawn the view: present what is new in it. */
      after(view) {
        publish();
        const g = view && view.game;
        const plan = advance(cursor, view, {hidden: Boolean(doc.hidden), briefed: g ? briefed(g) : false});
        cursor = plan.cursor;
        if (plan.why !== "live" && plan.why !== "duplicate") settled(plan.why);
        // A briefing belongs to the preparation: once the table has left it (the first trick
        // has begun, a result stands, the table is gone) the mission stage is given back.
        if (briefingOn && !(g && briefable(g))) { briefingOn = false; skip(); }
        if (plan.cues.length && g) perform(plan.cues, g);
        rects = null;
        return plan.why;
      },
      /* The connection came back: whatever arrives next is the state, not news. */
      resync() { cursor = {...cursor, primed: false}; },
      /* A tap or a key: sound and haptics are allowed from now on, and a running cinematic beat ends. */
      gesture() { gesture = true; skip(); },
      skip,
      /* The client's guard reports a throw; three of them and the director stands down for good. */
      failed() { stats.errors += 1; if (stats.errors >= 3) { stats.disabled = true; skip(); publish(); } },
      visibility() { publish(); if (doc.hidden) skip(); },
    };
    publish();
    return Object.freeze(api);
  }

  const api = Object.freeze({VERSION, INTENSITY, TIER_MS, TIMING, MAX_BATCH, FIDELITIES, fidelity, advance, trickBudget, briefable, freshCursor, create});
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ExpoDirector = api;
})(typeof window !== "undefined" ? window : globalThis);
