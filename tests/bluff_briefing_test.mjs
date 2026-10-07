// bluff_briefing_test.mjs — BLUFF's first-play briefing and rules sheet (AVR-90) in a real
// browser at phone sizes. Needs a RUNNING, FRESH dev server (one BLUFF room: restart between
// runs) and puppeteer-core (tests/_resolve.mjs):
//
//   LANGAMES_PORT=8198 .venv/bin/python server.py &
//   node tests/bluff_briefing_test.mjs http://127.0.0.1:8198 [screenshotDir]
//
// Covers: the briefing opens before a new player's Ready and cannot be skipped into play
// (Escape keeps it; "Not now" closes it but Ready reopens it); its "I'm ready" readies the
// player; the acknowledgement survives a reload; ? reopens the rules mid-game and closing them
// changes nothing; a mid-game reload restores the seat without the briefing; a watcher who
// arrives mid-game is not blocked; dialog semantics, focus, 44 px targets, no sideways scroll.
import fs from "fs";
import os from "os";
import path from "path";
import { puppeteer, CHROME_PATH } from "./_resolve.mjs";

const BASE = process.argv[2] || "http://127.0.0.1:8198";
const OUT = process.argv[3] || path.join(os.homedir(), "tmp", "ghshot-bluff-briefing");
fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.join(os.homedir(), "tmp"), { recursive: true });
const URL_ = BASE + "/games/bluff/";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let bad = 0;
const check = (ok, message) => {
  console.log(`${ok ? "PASS" : "FAIL"} ${message}`);
  if (!ok) bad += 1;
};

const browser = await puppeteer.launch({
  executablePath: CHROME_PATH,
  headless: "new",
  userDataDir: fs.mkdtempSync(path.join(os.homedir(), "tmp", "gh-bluff-brief-")),
  args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
});

async function phone(width, height) {
  const ctx = await browser.createBrowserContext();       // its own storage: a new phone
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.setViewport({ width, height, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  await page.evaluateOnNewDocument(() => {
    sessionStorage.setItem("lg-booted", "1");
    // toasts last 3 s; keep a record of every one shown
    window.__toasts = [];
    new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
      if (n.classList && n.classList.contains("toast")) window.__toasts.push(n.textContent);
    }))).observe(document, { childList: true, subtree: true });
  });
  return { ctx, page, errors };
}

const dialogOpen = (page) => page.evaluate(() => !!document.getElementById("briefing")?.open);
const phase = (page) => page.evaluate(() => (typeof ST !== "undefined" && ST ? ST.phase : null));
const waitFor = async (page, fn, arg, ms = 8000) => {
  await page.waitForFunction(fn, { timeout: ms, polling: 100 }, arg);
};
// A dialog's close event is sent with the next frame, and the briefing takes a close it did not ask
// for as the browser closing it. A step that reopens the dialog inside that frame would then have
// its state cleared by the late event (the last card read "Got it"): let the event land first.
const frames = (page, n = 2) => page.evaluate((count) => new Promise((resolve) => {
  const tick = (left) => (left <= 0 ? resolve() : requestAnimationFrame(() => tick(left - 1)));
  tick(count);
  setTimeout(resolve, 500);
}), n);
const clickBar = (page, text) => page.evaluate((t) => {
  const b = [...document.querySelectorAll("#bar button")].find((x) => x.textContent.includes(t));
  if (b) b.click();
  return !!b;
}, text);

// Geometry and semantics of the open dialog.
async function audit(page, label) {
  const r = await page.evaluate(() => {
    const d = document.getElementById("briefing");
    const rect = d.getBoundingClientRect();
    const small = [...d.querySelectorAll("button")].filter((b) => b.offsetParent)
      .map((b) => b.getBoundingClientRect()).filter((b) => b.width < 44 || b.height < 44);
    const nav = d.querySelector(".brief-nav").getBoundingClientRect();
    const title = document.getElementById(d.getAttribute("aria-labelledby"));
    return {
      inside: rect.top >= 0 && rect.bottom <= innerHeight + 0.5 && rect.left >= 0 && rect.right <= innerWidth + 0.5,
      navVisible: nav.bottom <= innerHeight + 0.5,
      small: small.length,
      overflow: document.documentElement.scrollWidth > innerWidth,
      name: title ? title.textContent : "",
      focusInside: d.contains(document.activeElement),
      unnamed: [...d.querySelectorAll("button")].filter((b) => b.offsetParent
        && !(b.getAttribute("aria-label") || b.textContent.trim())).length,
    };
  });
  check(r.inside && r.navVisible, `${label}: dialog and its buttons fit the screen`);
  check(r.small === 0, `${label}: every dialog control is at least 44x44 (${r.small} smaller)`);
  check(!r.overflow, `${label}: no sideways scroll`);
  check(r.name === "How to play BLUFF", `${label}: dialog is labelled "${r.name}"`);
  check(r.unnamed === 0, `${label}: every control has a name`);
  check(r.focusInside, `${label}: focus is inside the dialog`);
}

try {
  // ---- 1. a small Android-size phone, first time, in the lobby -------------------------------
  {
    const { ctx, page, errors } = await phone(360, 640);
    await page.goto(URL_, { waitUntil: "domcontentloaded" });
    await waitFor(page, () => document.getElementById("briefing")?.open);
    check(true, "360x640: the briefing opens for a new player in the lobby");
    await audit(page, "360x640");
    for (let i = 0; i < 6; i++) {
      await page.screenshot({ path: path.join(OUT, `360x640-card${i + 1}.png`) });
      const fits = await page.evaluate(() => {
        const b = document.querySelector("#briefing .brief-body");
        return b.scrollHeight <= b.clientHeight + 1 || getComputedStyle(b).overflowY === "auto";
      });
      check(fits, `360x640 card ${i + 1}: content fits or scrolls inside the card`);
      if (i < 5) await page.click("#briefing .brief-next");
    }
    await page.click("#briefing .brief-later");                      // leave without readying
    check(!(await dialogOpen(page)), "360x640: Not now closes the briefing");
    check(errors.length === 0, `360x640: no page errors (${errors.join(" | ")})`);
    await ctx.close();
    await sleep(500);
  }

  // ---- 1b. an Avrana Party launch (?avrana=1): a member sent here by the Party Host --------
  // Locally there is no Party service (its ticket request 404s), so the page joins with today's
  // hello; the page, the Back to Party bar and the briefing are exactly those of a Party launch.
  {
    const { ctx, page, errors } = await phone(375, 812);
    await page.goto(URL_ + "?avrana=1", { waitUntil: "domcontentloaded" });
    await waitFor(page, () => document.getElementById("briefing")?.open, null, 12000);
    check(true, "Party launch: the briefing opens for a first-time player");
    await audit(page, "Party launch 375x812");
    const chrome = await page.evaluate(() => {
      const r = document.getElementById("rules").getBoundingClientRect();
      const nav = document.getElementById("avrana-navigation");
      return { nav: !!nav, homeHidden: document.getElementById("home").hidden,
        rulesLeft: Math.round(r.left), rulesBelowNav: nav ? r.top >= nav.getBoundingClientRect().bottom : false };
    });
    check(chrome.nav && chrome.homeHidden, "Party launch: Back to Party bar replaces the home button");
    check(chrome.rulesLeft === 12 && chrome.rulesBelowNav, `Party launch: ? sits where home was (left ${chrome.rulesLeft})`);
    await page.screenshot({ path: path.join(OUT, "375x812-party-launch.png") });
    await page.click("#briefing .brief-later");
    check(!(await dialogOpen(page)), "Party launch: Not now closes it, so Back to Party is reachable");
    check(await page.evaluate(() => {
      const a = document.querySelector("#avrana-navigation a");
      a.focus();
      return document.activeElement === a;
    }), "Party launch: Back to Party can take focus once the briefing is closed");
    check(errors.length === 0, `Party launch: no page errors (${errors.join(" | ")})`);
    await ctx.close();
    await sleep(500);
  }

  // ---- 2. a 375x812 phone: the full first-play flow ------------------------------------------
  const A = await phone(375, 812);
  const pa = A.page;
  await pa.goto(URL_, { waitUntil: "domcontentloaded" });
  await waitFor(pa, () => document.getElementById("briefing")?.open);
  check(true, "375x812: the briefing opens before the player's Ready");
  await audit(pa, "375x812 first play");
  check(await pa.$eval("#briefing .brief-x", (x) => x.hidden), "first play: no close X");
  check(await pa.$eval("#briefing .brief-count", (x) => x.textContent === "1 of 6"), "first play starts at 1 of 6");
  await pa.screenshot({ path: path.join(OUT, "375x812-first-card1.png") });

  await pa.keyboard.press("Escape");
  await sleep(200);
  check(await dialogOpen(pa), "Escape does not skip the first-play briefing");

  let outside = 0;
  for (let i = 0; i < 14; i++) {
    await pa.keyboard.press("Tab");
    outside += await pa.evaluate(() => {
      const a = document.activeElement;
      return a && a !== document.body && !document.getElementById("briefing").contains(a) ? 1 : 0;
    });
  }
  check(outside === 0, "Tab never reaches the table behind the briefing");

  await pa.click("#briefing .brief-later");
  check(!(await dialogOpen(pa)), "Not now closes it");
  check(await pa.evaluate(() => localStorage.getItem("bluff-briefed") === null), "Not now is not an acknowledgement");
  check(await pa.evaluate(() => document.activeElement && document.activeElement.id === "rules"),
    "focus returns to the ? button");
  await frames(pa);

  check(await clickBar(pa, "I'M READY"), "the lobby's I'M READY button is there");
  await waitFor(pa, () => document.getElementById("briefing")?.open);
  await sleep(400);
  check(await pa.evaluate(() => !ST.you.ready), "Ready before acknowledging reopens the briefing and does not ready");

  for (let i = 1; i < 6; i++) {
    await pa.click("#briefing .brief-next");
    await pa.screenshot({ path: path.join(OUT, `375x812-first-card${i + 1}.png`) });
  }
  check(await pa.$eval("#briefing .brief-next", (b) => b.textContent.trim() === "I'm ready"),
    "the last card's button says I'm ready");
  await pa.click("#briefing .brief-next");
  await waitFor(pa, () => ST && ST.you && ST.you.ready);
  check(!(await dialogOpen(pa)), "I'm ready closes the briefing");
  check(await pa.evaluate(() => localStorage.getItem("bluff-briefed") === "1"), "the acknowledgement is stored");
  check(true, "I'm ready readies the player");

  // reload: acknowledged, so no briefing; Ready works directly
  await pa.reload({ waitUntil: "domcontentloaded" });
  await waitFor(pa, () => typeof ST !== "undefined" && ST && ST.you);
  await sleep(1200);
  check(!(await dialogOpen(pa)), "after a reload an acknowledged player is not briefed again");
  if (!(await pa.evaluate(() => ST.you.ready))) {
    await clickBar(pa, "I'M READY");
    await waitFor(pa, () => ST.you.ready);
  }
  check(!(await dialogOpen(pa)), "an acknowledged player's Ready goes straight through");

  // one test bot, start
  await pa.click('[aria-label="More test bots"]');
  await waitFor(pa, () => ST.settings && ST.settings.bots === 1);
  await clickBar(pa, "START GAME");
  await waitFor(pa, () => ST.phase === "playing" && ST.game && ST.game.me, null, 12000);
  check(true, "the game starts");
  await pa.screenshot({ path: path.join(OUT, "375x812-table.png") });

  // ---- 3. rules during play ------------------------------------------------------------------
  // open them when the table is waiting on this player (their turn or a prompt)
  await waitFor(pa, () => ST.game && ST.game.me && (ST.game.me.prompt || (ST.game.me.actions || []).length), null, 15000);
  const before = await pa.evaluate(() => JSON.stringify({ cards: ST.game.me.cards, seats: ST.game.seats.map((s) => s.pid) }));
  await pa.click("#rules");
  await waitFor(pa, () => document.getElementById("briefing")?.open);
  await audit(pa, "rules mid-game");
  check(await pa.$eval("#briefing .brief-later", (x) => x.hidden), "rules sheet: no Not now");
  check(await pa.$eval("#briefing .brief-x", (x) => !x.hidden), "rules sheet: a Close button");
  check(await pa.$eval("#briefing .brief-count", (x) => x.textContent === "1 of 6"), "rules sheet opens at 1 of 6");
  await pa.click("#briefing .brief-dots button:nth-child(3)");
  check(await pa.$eval("#briefing .brief-count", (x) => x.textContent === "3 of 6"), "a dot jumps to its card");
  check(await pa.$eval("#briefing .brief-nudge", (n) => !n.hidden && /close to/.test(n.textContent)),
    "rules sheet says when the table is waiting on this player");
  await pa.screenshot({ path: path.join(OUT, "375x812-rules-midgame.png") });
  await pa.keyboard.press("Escape");
  await sleep(200);
  check(!(await dialogOpen(pa)), "Escape closes the rules sheet");
  check(await pa.evaluate(() => document.activeElement && document.activeElement.id === "rules"),
    "focus returns to the ? button");
  const after = await pa.evaluate(() => JSON.stringify({ cards: ST.game.me.cards, seats: ST.game.seats.map((s) => s.pid) }));
  check(before === after, "opening and closing the rules changed nothing at the table");
  check(await pa.evaluate(() => ST.phase === "playing"), "the game is still running");

  // ---- 4. reconnect mid-game: seat and hand restored, no briefing ---------------------------
  await pa.reload({ waitUntil: "domcontentloaded" });
  await waitFor(pa, () => typeof ST !== "undefined" && ST && ST.game && ST.game.me, null, 10000);
  await sleep(800);
  const restored = await pa.evaluate(() => JSON.stringify({ cards: ST.game.me.cards, seats: ST.game.seats.map((s) => s.pid) }));
  check(restored === after || (await pa.evaluate(() => ST.phase !== "playing")), "a mid-game reload restores the same seat and hand");
  check(!(await dialogOpen(pa)), "no briefing on a mid-game reconnect");
  check(A.errors.length === 0, `375x812: no page errors (${A.errors.join(" | ")})`);

  // ---- 5. a new phone arrives mid-game (a watcher who never saw the briefing) ---------------
  const B = await phone(375, 812);
  await B.page.goto(URL_, { waitUntil: "domcontentloaded" });
  await waitFor(B.page, () => typeof ST !== "undefined" && ST && ST.game, null, 10000);
  await sleep(1200);
  check(!(await dialogOpen(B.page)), "a watcher arriving mid-game is not blocked by the briefing");
  check(await B.page.evaluate(() => window.__toasts.some((t) => /how to play/.test(t))),
    "the watcher is pointed at ? instead");
  check(await B.page.evaluate(() => ST.game.me === null), "the watcher sees public state only");
  await B.page.click("#rules");
  await waitFor(B.page, () => document.getElementById("briefing")?.open);
  check(true, "the watcher can open the rules");
  await B.page.keyboard.press("Escape");
  await sleep(200);
  check(!(await dialogOpen(B.page)), "and close them");
  check(B.errors.length === 0, `watcher: no page errors (${B.errors.join(" | ")})`);
  await B.ctx.close();
} finally {
  await browser.close();
}

console.log(bad ? `${bad} FAILED` : "all passed", "| screenshots:", OUT);
process.exit(bad ? 1 : 0);
