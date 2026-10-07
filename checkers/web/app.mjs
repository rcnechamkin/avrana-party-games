// The Checkers page: what a phone shows and does (AVR-238). Plain ES modules, no framework.
//
// A page on the game's own origin holds no Party identity. It learns where the Party is from its
// own server (GET api/party), embeds the Party's bridge through the vendored shim, asks the bridge
// for a ticket, and trades the ticket for a seat with this game's server (POST api/redeem). That
// is the only way it reaches the Party: no cookie, no Party API call of its own, nothing stored in
// the browser. The game's token lives in memory; a reload asks for a fresh ticket and gets the
// same seat back.
//
// The server says what is legal (board.mjs only chooses among the moves it sent), and its words
// for a refusal are the ones shown. createApp(env) takes everything outside the page as `env`
// (the document, the network, the Party's shim and board.mjs), so tests/checkers_page_test.mjs can
// run it against the real server with a small fake DOM. This module imports nothing: checkers.js
// loads the three modules separately and again after a pause if one of them did not arrive.

export const GAME = 'checkers';
export const IDS = [
  'app', 'status', 'live', 'summary', 'table', 'board', 'resign', 'end', 'rules-open',
  'top-seat', 'top-name', 'top-side', 'top-count', 'top-turn',
  'bottom-seat', 'bottom-name', 'bottom-side', 'bottom-count', 'bottom-turn',
  'result', 'result-headline', 'result-detail', 'result-wait', 'result-actions', 'again', 'home',
  'rules', 'rules-body', 'rules-close',
  'confirm', 'confirm-title', 'confirm-body', 'confirm-yes', 'confirm-no',
];
const RETRY_MS = 3000;                         // between asking for a seat and asking again
const BACKOFF_MS = [1000, 2000, 4000, 8000];   // after a poll fails to reach the game
const NOTICE_MS = 5000;

export function createApp(env = {}) {
  const doc = env.document || globalThis.document;
  const fetchFn = env.fetch || ((...args) => globalThis.fetch(...args));
  const later = env.setTimeout || ((fn, ms) => globalThis.setTimeout(fn, ms));
  const cancel = env.clearTimeout || ((id) => globalThis.clearTimeout(id));
  const Abort = env.AbortController || globalThis.AbortController;
  const here = env.origin !== undefined ? env.origin : (globalThis.location ? globalThis.location.origin : '');
  const connect = env.connectParty;
  const {
    choices, cellLabel, countPieces, describeMove, isDark, lastMarks, order, other, rc, resultLines,
    sources, summary, tap, trailHolds, turnLine, word,
  } = env.board;
  const el = {};
  for (const id of IDS) {
    el[id] = doc.getElementById(id);
    if (!el[id]) throw new Error(`the page has no #${id}`);
  }

  // Everything that changes lives here; render() draws it.
  const S = {
    noParty: false,        // there is no Party to ask for a seat (this page was opened by hand)
    waiting: false,        // asked for a seat and was not given one yet
    linkDown: false,       // the game stopped answering
    party: null,           // the shim's connection
    partyView: null,       // the Party's last word on where it is (the shim's `view`)
    token: null,           // this seat's credential, in memory only
    view: null,            // what the server last showed this seat
    trail: [],             // squares chosen so far for the move being made
    busy: false,           // a move or a resignation is on its way
    notice: null,          // a short sentence that replaces the turn line for a while
    noticeTimer: null,
    flip: null,            // which way the board was built
    cells: new Map(),      // square -> its button
    rules: null,           // onboarding.json once it has been read
    poll: null,            // the AbortController of the poll in flight
    waiters: [],           // callbacks to wake when the Party says something
  };

  // ---- small helpers --------------------------------------------------------------------------

  const delay = (ms) => new Promise((resolve) => later(resolve, ms));

  function h(tag, attrs = {}, ...kids) {
    const node = doc.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined) continue;
      if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value);
    }
    node.append(...kids);
    return node;
  }

  function data(node, key, value) {
    if (value === null || value === undefined || value === '') delete node.dataset[key];
    else node.dataset[key] = value;
  }

  function setText(node, text) {
    if (node.textContent !== text) node.textContent = text;
  }

  async function post(path, body, signal) {
    const res = await fetchFn(path, {
      method: 'POST', cache: 'no-store', credentials: 'omit', signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    let json = null;
    try { json = await res.json(); } catch { /* not JSON */ }
    return { ok: Boolean(res.ok && json && json.ok === true), status: res.status, body: json && typeof json === 'object' ? json : {} };
  }

  /** Resolves on the Party's next word, or after `ms`. */
  function changeOrDelay(ms) {
    return new Promise((resolve) => {
      let timer = null;
      const finish = () => {
        cancel(timer);
        const at = S.waiters.indexOf(finish);
        if (at >= 0) S.waiters.splice(at, 1);
        resolve();
      };
      S.waiters.push(finish);
      timer = later(finish, ms);
    });
  }

  function notice(text) {
    if (S.noticeTimer !== null) cancel(S.noticeTimer);
    S.notice = text;
    S.noticeTimer = later(() => { S.notice = null; S.noticeTimer = null; render(); }, NOTICE_MS);
    render();
  }

  const announce = (text) => { if (text) el.live.textContent = text; };

  // ---- what is on screen ----------------------------------------------------------------------

  const partyAt = () => (S.partyView && S.partyView.location ? S.partyView.location : { at: null, game: null });
  const isHost = () => Boolean(S.partyView && S.partyView.host);
  // Where the Party says it is, for this game. The results are this game's page (ADR 0011): the Party
  // holds them until the Host moves on, and sends every phone back to the page when it is not there.
  const atResults = () => { const at = partyAt(); return at.at === 'results' && at.game === GAME; };
  const inGame = () => { const at = partyAt(); return at.at === 'game' && at.game === GAME; };
  const canAct = () => Boolean(S.view && S.view.seat && S.view.turn === S.view.seat && !S.view.result && !S.busy
    && !atResults());

  function mode() {
    if (S.noParty) return 'noparty';
    if (atResults() || (S.view && S.view.result)) return 'over';   // with a board to show, or without one
    if (!S.view) return S.waiting ? 'waiting' : 'connecting';
    return S.view.seat ? 'play' : 'watch';
  }

  function buildBoard(flip) {
    S.flip = flip;
    S.cells.clear();
    const nodes = [];
    for (const square of order(flip)) {
      const [row, col] = rc(square);
      if (!isDark(row, col)) {
        nodes.push(h('div', { class: 'sq light', 'aria-hidden': 'true' }));
        continue;
      }
      const cell = h('button', { class: 'sq dark', type: 'button', tabindex: '-1' });
      cell.dataset.sq = String(square);
      cell.addEventListener('click', () => onCell(square));
      S.cells.set(square, cell);
      nodes.push(cell);
    }
    el.board.replaceChildren(...nodes);
  }

  function renderBoard() {
    const view = S.view;
    const flip = view.seat === 'b';
    if (S.flip !== flip) buildBoard(flip);
    const acting = canAct();
    const starts = acting ? sources(view.moves) : new Set();
    const held = acting && S.trail.length ? choices(view.moves, S.trail) : null;
    const marks = lastMarks(view.lastMove);
    let tabbable = 0;
    for (const [square, cell] of S.cells) {
      const piece = view.board[square];
      const selected = Boolean(held) && S.trail[0] === square;
      const target = held ? held.targets.get(square) || null : null;
      const movable = starts.has(square) && !target;
      data(cell, 'piece', piece);
      data(cell, 'sel', selected ? '1' : null);
      data(cell, 'target', target);
      data(cell, 'movable', movable ? '1' : null);
      data(cell, 'last', marks.get(square) || null);
      cell.setAttribute('aria-label', cellLabel({ square, piece, movable, selected, target }));
      if (movable) cell.setAttribute('aria-pressed', String(selected));
      else cell.removeAttribute('aria-pressed');
      const live = movable || Boolean(target) || selected;
      cell.setAttribute('tabindex', live ? '0' : '-1');
      if (live) tabbable += 1;
    }
    el.board.setAttribute('tabindex', tabbable ? '-1' : '0');
    setText(el.summary, summary(view));
  }

  function renderSeats() {
    const view = S.view;
    const bottom = view.seat || 'w';
    for (const [place, side] of [['top', other(bottom)], ['bottom', bottom]]) {
      data(el[`${place}-seat`], 'side', side);
      setText(el[`${place}-name`], side === view.seat ? 'You' : (view.names[side] || word(side)));
      setText(el[`${place}-side`], word(side));
      const n = countPieces(view.board, side);
      setText(el[`${place}-count`], n === 1 ? '1 piece' : `${n} pieces`);
      el[`${place}-turn`].hidden = view.turn !== side;
    }
  }

  /** The result, and what happens next. This page has the finished board while the game it played
   * is still held; a page that opens at the results (a reload, or the Party sending the phone back
   * here) has no seat, since the game admits no one after it has reported the end, and no board.
   * The Party's word that it is at the results is enough for the Host's choices and for everyone
   * else's waiting line. */
  function renderResult() {
    const view = S.view;
    const known = Boolean(view && view.result);
    const results = atResults();
    el.result.hidden = !(known || results);
    if (el.result.hidden) return;
    const lines = known ? resultLines(view) : { headline: 'Game over', detail: '' };
    const host = isHost();
    const hostName = S.partyView && S.partyView.hostName;
    const wait = !results ? 'Recording the result…'
      : host ? '' : `Waiting for ${hostName || 'the Host'} to choose what is next.`;
    setText(el['result-headline'], lines.headline);
    setText(el['result-detail'], lines.detail);
    setText(el['result-wait'], wait);
    el['result-detail'].hidden = !lines.detail;                 // an empty line would leave a gap
    el['result-wait'].hidden = !wait;
    el['result-actions'].hidden = !(results && host);
  }

  function statusText() {
    if (S.notice) return S.notice;
    switch (mode()) {
      case 'noparty': return 'Open Checkers from Party Home.';
      case 'connecting': return 'Connecting…';
      case 'waiting': return 'Waiting for the game to start.';
      case 'over': return S.linkDown ? 'Reconnecting…' : 'Game over.';
      default: break;
    }
    if (S.linkDown) return 'Reconnecting…';
    let held = 'none';
    if (S.trail.length) held = choices(S.view.moves, S.trail).mode === 'hop' ? 'hop' : 'piece';
    return turnLine(S.view, { held });
  }

  function render() {
    const m = mode();
    el.app.dataset.mode = m;
    el.table.hidden = !S.view;
    if (S.view) {
      renderBoard();
      renderSeats();
    }
    renderResult();
    setText(el.status, statusText());
    el.resign.hidden = m !== 'play';
    el.resign.disabled = S.busy;                      // a move is on its way: the button stays, so nothing jumps
    el.end.hidden = !(isHost() && inGame());
  }

  // ---- what the server says -------------------------------------------------------------------

  function apply(view) {
    const before = S.view;
    if (before && view.v < before.v) return;                 // an older answer that arrived late
    S.view = view;
    if (!trailHolds(view.moves, S.trail)) S.trail = [];
    if (!before || view.v > before.v) {
      const moved = view.lastMove && view.lastMove.by !== view.seat
        && (!before || JSON.stringify(before.lastMove) !== JSON.stringify(view.lastMove));
      if (moved) announce(describeMove(view.lastMove, view.names));
      if (view.result && !(before && before.result)) {
        const lines = resultLines(view);
        announce(`${lines.headline}. ${lines.detail}`);
      }
    }
    render();
  }

  function onParty(partyView) {
    S.partyView = partyView;
    for (const wake of S.waiters.splice(0)) wake();
    render();
  }

  async function act(path, body) {
    S.busy = true;
    render();
    try {
      const reply = await post(path, body);
      if (reply.body.view) apply(reply.body.view);
      if (!reply.ok) notice(reply.body.message || 'That did not go through. Try again.');
    } catch {
      notice('Could not reach the game. Try again.');
    } finally {
      S.busy = false;
      S.trail = [];
      render();
    }
  }

  function onCell(square) {
    if (!canAct()) return;
    const step = tap(S.view.moves, S.trail, square);
    S.trail = step.trail;
    if (step.move) act('api/move', { token: S.token, v: S.view.v, move: step.move });
    else render();
  }

  // ---- asking, resigning, ending, the rules ---------------------------------------------------

  /** A confirmation: the safe choice has the focus, the other is the destructive one. */
  function ask({ title, body, yes }) {
    if (el.confirm.open) return Promise.resolve(false);
    return new Promise((resolve) => {
      setText(el['confirm-title'], title);
      setText(el['confirm-body'], body);
      setText(el['confirm-yes'], yes);
      const dialog = el.confirm;
      dialog.returnValue = '';
      const closed = () => resolve(dialog.returnValue === 'yes');
      dialog.addEventListener('close', closed, { once: true });
      dialog.showModal();
    });
  }

  async function onResign() {
    if (!S.view || !S.view.seat || S.busy) return;
    const rival = S.view.names[other(S.view.seat)] || word(other(S.view.seat));
    const yes = await ask({ title: 'Resign this game?', body: `${rival} wins. This cannot be undone.`, yes: 'Resign' });
    if (yes && S.view && !S.view.result) await act('api/resign', { token: S.token });
  }

  async function onEnd() {
    const yes = await ask({
      title: 'End the game for everyone?',
      body: 'Everyone goes back to Party Home. No result is recorded.', yes: 'End game' });
    if (!yes) return;
    const done = await S.party.end();
    if (!done.ok) notice('Could not end the game. Try again.');
  }

  async function hostVerb(verb) {
    const done = await S.party[verb]();
    if (!done.ok) notice('That did not work. Try again.');
  }

  async function openRules() {
    if (!S.rules) {
      try {
        const res = await fetchFn('onboarding.json', { cache: 'no-store', credentials: 'omit' });
        const rules = res.ok ? await res.json() : null;
        if (rules && Array.isArray(rules.rules)) S.rules = rules;
      } catch { /* the sheet says so below */ }
    }
    if (S.rules) {
      const facts = S.rules.facts || {};
      const fill = (text) => String(text).replace(/\{(\w+)\}/g, (all, name) => (name in facts ? facts[name] : all));
      el['rules-body'].replaceChildren(
        h('p', { class: 'premise', text: S.rules.premise || '' }),
        ...S.rules.rules.map((section) => h('section', {}, h('h3', { text: fill(section.title) }),
          h('ul', {}, ...section.points.map((point) => h('li', { text: fill(point) }))))));
    } else {
      el['rules-body'].replaceChildren(h('p', { text: 'The rules are not available right now.' }));
    }
    if (!el.rules.open) el.rules.showModal();
  }

  // ---- getting a seat, and keeping it ---------------------------------------------------------

  /** Where the Party is, from this game's own server. Only an answer decides: no answer yet is
   * not "there is no Party", so the page asks again. */
  async function partyOrigin() {
    for (;;) {
      try {
        const res = await fetchFn('api/party', { cache: 'no-store', credentials: 'omit' });
        if (res.ok) {
          const body = await res.json();
          return body && typeof body.partyOrigin === 'string' ? body.partyOrigin : null;
        }
        if (res.status === 404) return null;
      } catch { /* not answered yet */ }
      await delay(RETRY_MS);
    }
  }

  async function seat() {
    const ticket = await S.party.ticket();
    if (!ticket || !ticket.ok) return false;
    let reply;
    try { reply = await post('api/redeem', { ticket: ticket.ticket }); } catch { return false; }
    if (!reply.ok) return false;
    S.token = reply.body.token;
    S.view = null;                                  // a fresh seat starts from what the server says
    S.trail = [];
    S.waiting = false;
    apply(reply.body.view);
    return true;
  }

  async function follow() {
    let failures = 0;
    while (S.token && S.view && !S.view.result) {
      S.poll = new Abort();
      let reply;
      try {
        // A poll waits for news. After a failure the first one asks for the board as it was one
        // version ago, which the game answers at once, so the page learns the link is back
        // without waiting out a quiet game.
        reply = await post('api/poll', { token: S.token, since: failures ? S.view.v - 1 : S.view.v }, S.poll.signal);
      } catch {
        if (S.poll.signal.aborted) continue;        // the phone came back: ask again at once
        failures += 1;
        S.linkDown = true;
        render();
        await delay(BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]);
        continue;
      }
      failures = 0;
      if (S.linkDown) { S.linkDown = false; render(); }
      if (reply.status === 403) {                                // the game no longer knows this seat
        S.token = null; S.view = null; S.trail = [];             // so there is no board to show or play
        render();
        break;
      }
      if (reply.ok && reply.body.view) apply(reply.body.view);
      else await delay(1000);                                    // busy or mid-restart: do not spin
    }
    S.poll = null;
  }

  /** This game is over and the Party decides what comes next: the Host's Play again, or Party Home
   * (which takes the page away: the shim does it). A new game shows as the Party saying a game of
   * this kind is on, and a fresh ticket redeems only for a new session, the old one being closed. So
   * whenever the Party says `game` the page asks for a seat, on each word from the Party and every
   * few seconds; a refusal means it is still the old one. The page does not wait to have watched the
   * Party leave and come back: the Party tells a phone only its latest view, and a phone that was
   * locked or offline through the results sees `game` and then `game` again. Resolves true once
   * seated. */
  async function nextGame() {
    for (;;) {
      if (inGame() && (await seat())) return true;
      await changeOrDelay(RETRY_MS);
    }
  }

  async function run() {
    const origin = await partyOrigin();
    if (!origin || origin === here) {
      S.noParty = true;
      render();
      return;
    }
    S.party = connect({ partyOrigin: origin, game: GAME });
    S.party.onChange(onParty);
    let seated = false;                                // nextGame() has already got the seat
    for (;;) {
      // At the results the Party gives no ticket (the session is over): wait for it to say more.
      if (!seated && (atResults() || !(await seat()))) {
        S.waiting = true;
        render();
        await changeOrDelay(RETRY_MS);
        continue;
      }
      seated = false;
      await follow();
      if (S.view && S.view.result) seated = await nextGame();   // over: the Party decides what comes next
    }
  }

  function wake() {
    if (S.poll) S.poll.abort();
  }

  function start() {
    el['rules-open'].addEventListener('click', openRules);
    el['rules-close'].addEventListener('click', () => el.rules.close());
    el.resign.addEventListener('click', onResign);
    el.end.addEventListener('click', onEnd);
    el.again.addEventListener('click', () => hostVerb('playAgain'));
    el.home.addEventListener('click', () => hostVerb('goHome'));
    el['confirm-yes'].addEventListener('click', () => el.confirm.close('yes'));
    el['confirm-no'].addEventListener('click', () => el.confirm.close('no'));
    doc.addEventListener('visibilitychange', () => { if (doc.visibilityState === 'visible') wake(); });
    if (env.window && env.window.addEventListener) env.window.addEventListener('online', wake);
    render();
    return run();
  }

  return { start, S, render, onCell, onResign, onEnd, openRules };
}
