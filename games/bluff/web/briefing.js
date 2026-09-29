/* BLUFF "How to play": the first-play briefing and the rules sheet (AVR-90).
   One dialog, two modes:
     first      before a new player's first Ready. It ends with "I'm ready" (the acknowledgement,
                which also readies them). Escape does not dismiss it; "Not now" closes it, but the
                lobby's Ready button opens it again until it has been acknowledged.
     reference  the ? button, any time. Escape or Close; the game underneath carries on untouched.
   All the words live in CARDS below. The numbers come from FACTS and BLOCKS, which
   tests/test_bluff_briefing.py pins to games/bluff/game.py (the only place rules live).
   The acknowledgement is remembered per browser (localStorage KEY); nothing is sent to the
   server, and the dialog never touches the connection. */
"use strict";

window.BluffBriefing = (() => {
  // ---- facts (pinned to game.py by tests/test_bluff_briefing.py; keep each on one line) ----
  const FACTS = {"handSize": 2, "startCoins": 2, "income": 1, "aid": 2, "coupCost": 7, "mustCoupAt": 10, "tax": 3, "strikeCost": 3, "steal": 2, "responseSeconds": 20};
  const BLOCKS = {"aid": ["Banker"], "strike": ["Guardian"], "steal": ["Smuggler", "Broker"]};
  const ROLE_ORDER = ["Banker", "Agent", "Smuggler", "Broker", "Guardian"];
  const F = FACTS;

  // Bump VERSION when the rules change enough that everyone should read the briefing again.
  const KEY = "bluff-briefed", VERSION = "1";

  // ---- the words: one idea per card. art = BLUFF game art (art.js); role = the role's colour ----
  const CARDS = [
    { id: "goal", art: "crown_a", tone: "gold", title: "Be the last one standing",
      lines: [`You get ${F.handSize} secret role cards and ${F.startCoins} coins.`,
        "Lose your last card and you're out. The last one with a card wins."] },
    { id: "turn", art: "token_add", tone: "gold", title: "On your turn, do one thing",
      items: [
        { art: "token_add", head: "Income:", text: `take ${F.income} coin.` },
        { art: "hand_token", head: "Foreign Aid:", text: `take ${F.aid}. Anyone can block it.` },
        { art: "exploding", head: "Coup:", text: `pay ${F.coupCost}, a player loses a card. Required at ${F.mustCoupAt}+ coins.` },
        { art: "hand_card", head: "Claim:", text: "use a role's power (next card)." },
      ] },
    { id: "claim", art: "hand_card", tone: "claim", title: "Claim any role, even one you don't have",
      lines: ["Nobody sees your cards. That's the bluff."],
      items: [
        { role: "Banker", head: "Banker:", text: `Tax, take ${F.tax} coins.` },
        { role: "Agent", head: "Agent:", text: `Strike, pay ${F.strikeCost} and a player loses a card.` },
        { role: "Smuggler", head: "Smuggler:", text: `Steal ${F.steal} coins from a player.` },
        { role: "Broker", head: "Broker:", text: "Exchange cards with the deck." },
        { role: "Guardian", head: "Guardian:", text: "no move; blocks a Strike." },
      ] },
    { id: "challenge", art: "hand_cross", tone: "stop", title: "Don't believe it? Challenge",
      lines: ["Anyone can challenge a claim, or Pass."],
      items: [
        { art: "skull", head: "Bluffing?", text: "They lose a card and the move fails." },
        { art: "flip_head", head: "Telling the truth?", text: "You lose a card; they get a fresh one." },
      ] },
    { id: "block", art: "shield", tone: "claim", title: "Block with a role",
      lines: ["Stop a move by claiming the right role:"],
      items: [
        { role: BLOCKS.aid[0], head: "Foreign Aid:", text: `anyone, as ${BLOCKS.aid.join(" or ")}.` },
        { role: BLOCKS.strike[0], head: "Strike on you:", text: `as ${BLOCKS.strike.join(" or ")}.` },
        { role: BLOCKS.steal[0], head: "Steal from you:", text: `as ${BLOCKS.steal.join(" or ")}.` },
      ],
      after: "A block is a claim, so it can be challenged too." },
    { id: "controls", art: "hourglass", tone: "gold", title: "When it's your call",
      items: [
        { art: "hand_card", head: "Your moves", text: "are in the bottom bar. To aim one, tap a glowing player." },
        { art: "hand_cross", head: "A gold banner", text: "means answer now: Challenge or Pass, Block or Allow." },
        { art: "hourglass", head: `${F.responseSeconds} seconds`, text: "to answer, or you pass." },
        { icon: "circle-help", head: "The ? button", text: "shows this again any time." },
      ] },
  ];

  const art = window.BluffArt || (() => document.createTextNode(""));
  const icon = window.BluffIcons || (() => document.createTextNode(""));
  const ROLE_ART = { Banker: "dollar", Agent: "sword", Smuggler: "pouch_remove",
    Broker: "card_flipdouble", Guardian: "shield" };

  // ---- the acknowledgement (per browser; private mode or a blocked store falls back to memory) --
  let memoryAck = false;
  function acknowledged() {
    if (memoryAck) return true;
    try { return localStorage.getItem(KEY) === VERSION; } catch (e) { return false; }
  }
  function acknowledge() {
    memoryAck = true;
    try { localStorage.setItem(KEY, VERSION); } catch (e) { /* memory only for this page */ }
  }

  // ---- the dialog ------------------------------------------------------------------------------
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const $ = (id) => document.getElementById(id);
  let mode = null, page = 0, onReady = null, returnTo = null, closingByCode = false, nudgeText = "";

  function renderCard(c, i) {
    const card = el("section", "brief-card tone-" + c.tone);
    card.setAttribute("aria-roledescription", "card");
    card.setAttribute("aria-label", `${i + 1} of ${CARDS.length}: ${c.title}`);
    const hero = el("div", "brief-hero");
    hero.appendChild(art(c.art));
    card.appendChild(hero);
    card.appendChild(el("h3", "brief-title", c.title));
    for (const line of c.lines || []) card.appendChild(el("p", "brief-line", line));
    if (c.items) {
      const ul = el("ul", "brief-items");
      for (const it of c.items) {
        const li = el("li", it.role ? "role-" + it.role.toLowerCase() : "");
        const mark = el("span", "brief-mark");
        if (it.role) mark.appendChild(art(ROLE_ART[it.role]));
        else if (it.icon) mark.appendChild(icon(it.icon));
        else if (it.art) mark.appendChild(art(it.art));
        const words = el("span", "brief-words");
        words.append(el("b", null, it.head), " " + it.text);
        li.append(mark, words);
        ul.appendChild(li);
      }
      card.appendChild(ul);
    }
    if (c.after) card.appendChild(el("p", "brief-line", c.after));
    return card;
  }

  function lastLabel() {
    if (mode === "first") return "I'm ready";
    return acknowledged() ? "Close" : "Got it";
  }

  function show(n) {
    page = Math.max(0, Math.min(CARDS.length - 1, n));
    const d = $("briefing");
    const slot = d.querySelector(".brief-body");
    slot.replaceChildren(renderCard(CARDS[page], page));
    slot.scrollTop = 0;
    d.querySelector(".brief-count").textContent = `${page + 1} of ${CARDS.length}`;
    d.querySelectorAll(".brief-dots button").forEach((b, i) => {
      if (i === page) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    const back = d.querySelector(".brief-back"), next = d.querySelector(".brief-next");
    back.disabled = page === 0;
    const last = page === CARDS.length - 1;
    next.classList.toggle("done", last);
    next.replaceChildren(el("span", null, last ? lastLabel() : "Next"), icon(last ? "check" : "chevron-right"));
    if (back.disabled && document.activeElement === back) next.focus();
  }

  function build() {
    const d = $("briefing");
    if (!d || d.dataset.built) return d;
    d.dataset.built = "1";
    const head = el("div", "brief-head");
    const titles = el("div", "brief-titles");
    const h2 = el("h2", null, "How to play BLUFF");
    h2.id = "briefing-title";
    titles.append(h2, el("span", "brief-count"));
    const later = el("button", "brief-later", "Not now");
    later.type = "button";
    later.onclick = () => close();
    const x = el("button", "round-btn small brief-x");
    x.type = "button";
    x.setAttribute("aria-label", "Close how to play");
    x.appendChild(icon("x"));
    x.onclick = () => close();
    head.append(titles, later, x);

    const body = el("div", "brief-body");
    body.setAttribute("aria-live", "polite");
    // a horizontal swipe turns the card, as the buttons do
    let sx = null, sy = null;
    body.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
    body.addEventListener("touchend", (e) => {
      if (sx == null) return;
      const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
      sx = null;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) show(page + (dx < 0 ? 1 : -1));
    });

    const nudge = el("p", "brief-nudge");
    nudge.setAttribute("role", "status");
    nudge.hidden = true;

    const dots = el("div", "brief-dots");
    CARDS.forEach((c, i) => {
      const b = el("button");
      b.type = "button";
      b.setAttribute("aria-label", `Card ${i + 1}: ${c.title}`);
      b.appendChild(el("span"));
      b.onclick = () => show(i);
      dots.appendChild(b);
    });
    const nav = el("div", "brief-nav");
    const back = el("button", "act brief-back");
    back.type = "button";
    back.append(icon("chevron-left"), el("span", null, "Back"));
    back.onclick = () => show(page - 1);
    const next = el("button", "act primary brief-next");
    next.type = "button";
    next.onclick = () => {
      if (page < CARDS.length - 1) return show(page + 1);
      finish();
    };
    nav.append(back, next);
    d.append(head, nudge, body, dots, nav);

    // Escape: closes the rules sheet; never skips the first-play acknowledgement
    d.addEventListener("cancel", (e) => { if (mode === "first") e.preventDefault(); });
    d.addEventListener("close", () => {
      if (!closingByCode) close(true);     // closed by the browser (e.g. a repeated Escape)
    });
    return d;
  }

  function finish() {
    const wasFirst = mode === "first";
    const firstTime = !acknowledged();
    if (wasFirst || firstTime) acknowledge();
    const then = wasFirst ? onReady : null;
    close();
    if (then) then();
  }

  function close(already) {
    const d = $("briefing");
    if (!d || !mode) return;
    mode = null; onReady = null;
    if (!already && d.open) { closingByCode = true; d.close(); closingByCode = false; }
    const back = returnTo && returnTo.isConnected && !returnTo.disabled ? returnTo : $("rules");
    returnTo = null;
    if (back) back.focus();
  }

  // open("first", onReady) before a new player's Ready; open("reference") from the ? button
  function open(m, ready) {
    const d = build();
    if (!d) return;
    if (d.open) {                          // already showing: switch mode, keep the page
      mode = m === "first" && !acknowledged() ? "first" : (mode || m);
      if (mode === "first" && ready) onReady = ready;
    } else {
      mode = m;
      onReady = ready || null;
      returnTo = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
      if (m !== "first") page = 0;         // the briefing resumes where it was left; rules start at 1
    }
    d.classList.toggle("first", mode === "first");
    d.querySelector(".brief-later").hidden = mode !== "first";
    d.querySelector(".brief-x").hidden = mode === "first";
    show(page);
    status(nudgeText);
    if (!d.open) {
      if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
      d.querySelector(".brief-next").focus();
    }
  }

  // A line inside the open sheet when the table is waiting on this player (their own state only).
  function status(text) {
    nudgeText = text || "";
    const d = $("briefing");
    if (!d || !d.dataset.built) return;
    const n = d.querySelector(".brief-nudge");
    n.hidden = !nudgeText;
    if (n.textContent !== nudgeText) n.textContent = nudgeText;
  }

  const isOpen = () => !!($("briefing") && $("briefing").open);
  const wordCount = () => CARDS.reduce((sum, c) => sum + [c.title, ...(c.lines || []), c.after || "",
    ...(c.items || []).map((it) => it.head + " " + it.text)].join(" ").split(/\s+/).filter(Boolean).length, 0);

  return { acknowledged, open, close: () => close(), status, isOpen, wordCount,
    CARDS, FACTS, BLOCKS, ROLE_ORDER, KEY, VERSION };
})();
