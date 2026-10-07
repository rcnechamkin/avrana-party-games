// The Checkers page, run against the real game server (AVR-238).
//
//   node tests/checkers_page_test.mjs <scenario>      (run by tests/test_checkers_web.py, which
//                                                     starts the server and reads the key)
//
// No browser. checkers/web/app.mjs runs unchanged on a small fake DOM built from the real
// checkers/web/index.html (every element id the page asks for must exist there), talking over real
// HTTP to the real server with real signed tickets. The Party's bridge is a stand-in that hands out
// the tickets it was given and records what the page asks of it. The scenarios are the page's
// behaviour on a phone: its seat, its board, its turn line, resign, reconnect, the host's buttons.
//
// The environment is JSON from the wrapper:
//   CHECKERS_ORIGIN   http://127.0.0.1:<port>
//   CHECKERS_SETUP    { tickets: {ana, ben, cal: {one, again, next}}, launch2, end }
//                     one: a ticket for this game, again: two more for it (a reload), next: one for
//                     the game that replaces it; launch2 starts that game with the players swapped,
//                     end ends it
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createApp, IDS } from '../checkers/web/app.mjs';
import * as board from '../checkers/web/board.mjs';

const { sq } = board;

const ORIGIN = process.env.CHECKERS_ORIGIN;
const SETUP = JSON.parse(process.env.CHECKERS_SETUP || '{}');
const BASE = new URL('/games/checkers/', ORIGIN);
const PARTY = 'https://party.example';
const HTML = readFileSync(new URL('../checkers/web/index.html', import.meta.url), 'utf8');

// ---- a fake DOM: exactly what app.mjs uses --------------------------------------------------

class Node {
  constructor(tag, hidden = false) {
    Object.assign(this, { tag, hidden, children: [], attrs: new Map(), dataset: {}, listeners: {}, text: '',
      open: false, returnValue: '' });
  }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this.text; }
  set textContent(value) { this.children = []; this.text = String(value); }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  removeAttribute(name) { this.attrs.delete(name); }
  append(...kids) { this.children.push(...kids); }
  replaceChildren(...kids) { this.children = kids; this.text = ''; }
  addEventListener(type, fn, options = {}) { (this.listeners[type] ||= []).push({ fn, once: Boolean(options.once) }); }
  fire(type) {
    const list = this.listeners[type] || [];
    this.listeners[type] = list.filter((l) => !l.once);
    for (const { fn } of list) fn({ type, target: this });
  }
  click() { this.fire('click'); }
  showModal() { this.open = true; }
  close(value) {
    if (value !== undefined) this.returnValue = value;
    this.open = false;
    this.fire('close');
  }
}

function makeDocument() {
  const nodes = new Map();
  for (const [, tag, attrs] of HTML.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>/g)) {
    const id = /\sid="([^"]+)"/.exec(attrs);
    if (id) nodes.set(id[1], new Node(tag, /(?:^|\s)hidden(?=\s|$|=)/.test(attrs)));
  }
  const doc = new Node('document');
  doc.visibilityState = 'visible';
  doc.getElementById = (id) => nodes.get(id) || null;
  doc.createElement = (tag) => new Node(tag);
  doc.nodes = nodes;
  return doc;
}

// ---- a phone: the page, a stand-in for the Party's bridge, and a log of what each asked for --

/** `options.fetch` replaces the network; `options.hold` is an object whose `polls` promise, while
 * set, delays every poll; `options.failPolls()` says whether a poll fails to reach the game. */
function phone(tickets, options = {}) {
  const doc = makeDocument();
  const win = new Node('window');
  const requests = [];
  const party = {
    opts: null, calls: [], tickets: [...tickets], listener: null,
    onChange(fn) { this.listener = fn; },
    async ticket() {
      this.calls.push('ticket');
      const ticket = this.tickets.shift();
      return ticket ? { ok: true, ticket } : { ok: false, error: 'no_ticket' };
    },
    async end() { this.calls.push('end'); return { ok: true }; },
    async playAgain() { this.calls.push('playAgain'); return { ok: true }; },
    async goHome() { this.calls.push('goHome'); return { ok: true }; },
    push(view) { this.listener(view); },
  };
  const fetchFn = async (path, init = {}) => {
    requests.push({ path: String(path), body: init.body ? JSON.parse(init.body) : null, init });
    if (options.fetch) return options.fetch(path, init);
    if (String(path) === 'api/poll') {
      if (options.failPolls && options.failPolls()) throw new TypeError('network down');
      if (options.hold && options.hold.polls) await options.hold.polls;
    }
    return fetch(new URL(String(path), BASE), init);
  };
  const app = createApp({
    document: doc, window: win, board, origin: options.origin || ORIGIN, fetch: fetchFn,
    connectParty: (opts) => { party.opts = opts; return party; },
  });
  const me = {
    app, S: app.S, el: Object.fromEntries(doc.nodes), doc, win, party, requests, run: null,
    start() { me.run = app.start(); me.run.catch((e) => { console.error(e); process.exit(1); }); return me.run; },
    cell: (square) => app.S.cells.get(square),
    darkCells: () => doc.nodes.get('board').children.filter((n) => n.tag === 'button'),
    movable: () => me.darkCells().filter((n) => n.dataset.movable === '1').map((n) => Number(n.dataset.sq)),
    asked: (path) => requests.filter((r) => r.path === path),
    status: () => doc.nodes.get('status').textContent,
    text: (id) => doc.nodes.get(id).textContent,
  };
  return me;
}

async function until(check, what, ms = 8000) {
  const end = Date.now() + ms;
  for (;;) {
    let value;
    try { value = check(); } catch { value = false; }
    if (value) return value;
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

const quiet = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function party(path, message) {
  const res = await fetch(new URL(path, ORIGIN), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message }),
  });
  return res.status;
}
const LAUNCH = '/games/checkers/avrana/session/v0/launch';
const END = '/games/checkers/avrana/session/v0/end';

/** Ana (white) and Ben (black) at the table, both seated and watching. */
async function table() {
  const ana = phone(SETUP.tickets.ana.one), ben = phone(SETUP.tickets.ben.one);
  ana.start();
  ben.start();
  await until(() => ana.S.view && ben.S.view, 'both players to be seated');
  return { ana, ben };
}

/** One full move by tapping: the piece, then where it goes. */
async function play(who, from, to, then) {
  who.cell(from).click();
  assert.deepEqual(who.S.trail, [from]);
  who.cell(to).click();
  await until(() => then(), 'the move to be accepted');
}

// ---- the scenarios --------------------------------------------------------------------------

const scenarios = {
  // The opening, a move, the other side's reply and a compulsory capture, as two phones see it.
  async play() {
    const { ana, ben } = await table();
    assert.deepEqual(ana.party.opts, { partyOrigin: PARTY, game: 'checkers' });
    assert.equal(ana.S.view.seat, 'w');
    assert.equal(ben.S.view.seat, 'b');
    assert.equal(ana.el.app.dataset.mode, 'play');
    assert.equal(ana.status(), 'Your move.');
    assert.equal(ben.status(), 'Waiting for Ana.');
    assert.equal(ana.text('bottom-name'), 'You');
    assert.equal(ana.text('top-name'), 'Ben');
    assert.equal(ana.text('bottom-count'), '12 pieces');
    assert.equal(ben.text('top-name'), 'Ana');

    // The board: thirty-two squares you can press, white's side at the bottom for white, turned for black.
    assert.equal(ana.darkCells().length, 32);
    assert.equal(ana.darkCells()[0].dataset.sq, '1');
    assert.equal(ben.darkCells()[0].dataset.sq, '62');
    assert.deepEqual(ana.movable().sort((a, b) => a - b), [sq(5, 0), sq(5, 2), sq(5, 4), sq(5, 6)]);
    assert.deepEqual(ben.movable(), []);
    assert.equal(ana.cell(sq(5, 2)).getAttribute('aria-label'), 'c3, white man, can move');
    assert.equal(ana.cell(sq(5, 2)).getAttribute('tabindex'), '0');
    assert.equal(ana.cell(sq(0, 1)).getAttribute('tabindex'), '-1');
    assert.equal(ana.cell(sq(0, 1)).dataset.piece, 'b');
    assert.match(ana.text('summary'), /^White: .*c3.*\. Black: .*b8.*\.$/);
    assert.equal(ana.el.resign.hidden, false);
    assert.equal(ben.el.resign.hidden, false);                      // resigning is allowed out of turn
    assert.equal(ana.el.end.hidden, true);                          // the Host's End is the Party's to show
    assert.equal(ana.el.result.hidden, true);

    // A tap on a square that cannot be played asks the server nothing.
    ana.cell(sq(0, 1)).click();
    ana.cell(sq(6, 1)).click();
    assert.deepEqual(ana.S.trail, []);
    assert.equal(ana.asked('api/move').length, 0);

    // Pick a piece up, see where it may go, put it down, pick another, move it.
    ana.cell(sq(5, 2)).click();
    assert.equal(ana.status(), 'Tap where it goes.');
    assert.equal(ana.cell(sq(5, 2)).dataset.sel, '1');
    assert.equal(ana.cell(sq(5, 2)).getAttribute('aria-pressed'), 'true');
    assert.equal(ana.cell(sq(4, 1)).dataset.target, 'move');
    assert.equal(ana.cell(sq(4, 3)).dataset.target, 'move');
    assert.match(ana.cell(sq(4, 3)).getAttribute('aria-label'), /move here/);
    ana.cell(sq(5, 2)).click();
    assert.deepEqual(ana.S.trail, []);
    assert.equal(ana.cell(sq(4, 3)).dataset.target, undefined);
    ana.cell(sq(5, 4)).click();                                     // another piece instead
    assert.deepEqual(ana.S.trail, [sq(5, 4)]);
    ana.cell(sq(5, 2)).click();                                     // and back again
    assert.deepEqual(ana.S.trail, [sq(5, 2)]);
    ana.cell(sq(4, 3)).click();
    await until(() => ana.S.view.v === 2, 'the move to be accepted');

    const sent = ana.asked('api/move');
    assert.equal(sent.length, 1);
    assert.deepEqual(Object.keys(sent[0].body).sort(), ['move', 'token', 'v']);
    assert.deepEqual([sent[0].body.v, sent[0].body.move], [1, [sq(5, 2), sq(4, 3)]]);
    await until(() => ben.S.view.v === 2, 'Ben to hear of the move');
    assert.equal(ben.text('live'), 'Ana moved c3 to d4.');
    assert.equal(ben.status(), 'Your move.');
    assert.equal(ana.status(), 'Waiting for Ben.');
    assert.deepEqual(ana.movable(), []);
    assert.equal(ana.cell(sq(4, 3)).dataset.last, 'to');
    assert.equal(ana.cell(sq(5, 2)).dataset.last, 'from');
    ana.cell(sq(5, 4)).click();                                     // not Ana's turn: nothing happens
    assert.deepEqual(ana.S.trail, []);

    // Ben answers with a move that offers a piece: Ana must take it.
    await play(ben, sq(2, 5), sq(3, 4), () => ben.S.view.v === 3);
    await until(() => ana.S.view.v === 3, 'Ana to hear of the reply');
    assert.equal(ana.status(), 'Your move. A capture is compulsory.');
    assert.deepEqual(ana.movable(), [sq(4, 3)]);
    ana.cell(sq(4, 3)).click();
    assert.equal(ana.cell(sq(2, 5)).dataset.target, 'jump');
    assert.equal(ana.cell(sq(4, 3)).getAttribute('aria-pressed'), 'true');
    ana.cell(sq(2, 5)).click();
    await until(() => ana.S.view.v === 4, 'the capture to be accepted');
    assert.equal(ana.cell(sq(3, 4)).dataset.last, 'taken');
    assert.equal(ana.cell(sq(2, 5)).dataset.piece, 'w');
    assert.equal(ana.text('top-count'), '11 pieces');
    await until(() => ben.S.view.v === 4, 'Ben to hear of the capture');
    assert.equal(ben.text('live'), 'Ana jumped d4 to f6 and took a piece.');
    assert.equal(ben.text('bottom-count'), '11 pieces');

    // Nothing in the page's traffic carries a credential anywhere but a body.
    for (const r of [...ana.requests, ...ben.requests]) {
      assert.match(r.path, /^(api\/(party|redeem|poll|move|resign)|onboarding\.json)$/);
      assert.equal(r.init.credentials, 'omit');
      assert.equal(r.init.cache, 'no-store');
    }
  },

  // A reload: a fresh ticket, the same seat, the board as it is.
  async reload() {
    const ana = phone(SETUP.tickets.ana.one);
    const ben = phone(SETUP.tickets.ben.one);
    ana.start();
    ben.start();
    await until(() => ana.S.view && ben.S.view, 'both players to be seated');
    await play(ana, sq(5, 2), sq(4, 3), () => ana.S.view.v === 2);
    const again = phone(SETUP.tickets.ana.again);                      // the same person on a reloaded page
    again.start();
    await until(() => again.S.view, 'the reloaded page to be seated');
    assert.equal(again.S.token, ana.S.token);
    assert.equal(again.S.view.seat, 'w');
    assert.equal(again.S.view.v, 2);
    assert.deepEqual(again.S.view.lastMove.path, [sq(5, 2), sq(4, 3)]);
    assert.equal(again.status(), 'Waiting for Ben.');
    assert.equal(again.cell(sq(4, 3)).dataset.piece, 'w');
    assert.equal(again.party.calls.length, 1);
    assert.equal(again.asked('api/redeem').length, 1);
  },

  // Somebody watching: the board, the turn, the rules; no way to play.
  async spectator() {
    const { ana, ben } = await table();
    const cal = phone(SETUP.tickets.cal.one);
    cal.start();
    await until(() => cal.S.view, 'the spectator to be seated');
    assert.equal(cal.el.app.dataset.mode, 'watch');
    assert.equal(cal.S.view.seat, null);
    assert.equal(cal.status(), "Ana's move (white).");
    assert.equal(cal.el.resign.hidden, true);
    assert.equal(cal.text('bottom-name'), 'Ana');
    assert.equal(cal.darkCells()[0].dataset.sq, '1');
    assert.deepEqual(cal.movable(), []);
    cal.cell(sq(5, 2)).click();
    cal.cell(sq(4, 3)).click();
    assert.deepEqual(cal.S.trail, []);
    assert.equal(cal.asked('api/move').length, 0);
    await play(ana, sq(5, 2), sq(4, 3), () => ana.S.view.v === 2);
    await until(() => cal.S.view.v === 2, 'the spectator to see the move');
    assert.equal(cal.status(), "Ben's move (black).");
    assert.equal(cal.text('live'), 'Ana moved c3 to d4.');
    assert.equal(cal.S.view.moves.length, 0);
    // To the end: the result is told by name.
    ben.el.resign.click();
    await until(() => ben.el.confirm.open, 'the confirmation');
    ben.el['confirm-yes'].click();
    await until(() => cal.S.view.result, 'the spectator to see the end');
    assert.equal(cal.text('result-headline'), 'Ana won');
    assert.equal(cal.text('result-detail'), 'Ben resigned.');
    assert.equal(cal.el.result.hidden, false);
    assert.equal(cal.asked('api/resign').length, 0);
  },

  // Resigning: asked first, with the safe choice first; then the result for both.
  async resign() {
    const { ana, ben } = await table();
    ben.el.resign.click();
    await until(() => ben.el.confirm.open, 'the confirmation');
    assert.equal(ben.text('confirm-title'), 'Resign this game?');
    assert.equal(ben.text('confirm-body'), 'Ana wins. This cannot be undone.');
    assert.equal(ben.text('confirm-yes'), 'Resign');
    ben.el.resign.click();                                           // asking twice does not stack
    ben.el['confirm-no'].click();
    await until(() => !ben.el.confirm.open, 'the confirmation to close');
    await quiet(50);
    assert.equal(ben.asked('api/resign').length, 0);
    assert.equal(ben.S.view.result, null);

    ben.el.resign.click();
    await until(() => ben.el.confirm.open, 'the confirmation again');
    ben.el['confirm-yes'].click();
    await until(() => ben.S.view.result && ana.S.view.result, 'both phones to show the end');
    assert.deepEqual(ana.S.view.result, { winner: 'w', ending: 'resigned', plies: 0 });
    assert.equal(ana.text('result-headline'), 'You won');
    assert.equal(ana.text('result-detail'), 'Ben resigned.');
    assert.equal(ben.text('result-headline'), 'You lost');
    assert.equal(ben.text('result-detail'), 'You resigned.');
    assert.equal(ben.text('live'), 'You lost. You resigned.');
    for (const side of [ana, ben]) {
      assert.equal(side.el.result.hidden, false);
      assert.equal(side.el.resign.hidden, true);
      assert.equal(side.el.app.dataset.mode, 'over');
      assert.equal(side.status(), 'Game over.');
      assert.deepEqual(side.movable(), []);
    }
    await Promise.all([ana.run, ben.run]);                           // the pages stop asking: the Party takes it from here
    assert.equal(ana.text('result-wait'), 'Recording the result…');
  },

  // The Host's buttons come from the Party and nothing else, and are only shown where they apply.
  async host() {
    const { ana, ben } = await table();
    const at = (where) => ({ location: { at: where, game: 'checkers' }, hostName: 'Ana' });
    ana.party.push({ ...at('game'), host: true });
    ben.party.push({ ...at('game'), host: false });
    assert.equal(ana.el.end.hidden, false);
    assert.equal(ben.el.end.hidden, true);
    ana.el.end.click();
    await until(() => ana.el.confirm.open, 'the confirmation');
    assert.equal(ana.text('confirm-title'), 'End the game for everyone?');
    assert.equal(ana.text('confirm-yes'), 'End game');
    ana.el['confirm-no'].click();
    await until(() => !ana.el.confirm.open, 'the confirmation to close');
    await quiet(50);
    assert.ok(!ana.party.calls.includes('end'));
    ana.el.end.click();
    await until(() => ana.el.confirm.open, 'the confirmation again');
    ana.el['confirm-yes'].click();
    await until(() => ana.party.calls.includes('end'), 'the Party to be asked to end');
    assert.equal(ana.party.calls.filter((c) => c === 'end').length, 1);

    // At the results: the Host chooses, everyone else waits for them.
    ben.el.resign.click();
    await until(() => ben.el.confirm.open, 'the confirmation');
    ben.el['confirm-yes'].click();
    await until(() => ana.S.view.result && ben.S.view.result, 'the end');
    ana.party.push({ ...at('results'), host: true });
    ben.party.push({ ...at('results'), host: false });
    assert.equal(ana.el['result-actions'].hidden, false);
    assert.equal(ana.text('result-wait'), '');
    assert.equal(ben.el['result-actions'].hidden, true);
    assert.equal(ben.text('result-wait'), 'Waiting for Ana to choose what is next.');
    assert.equal(ana.el.end.hidden, true);
    ana.el.again.click();
    ana.el.home.click();
    await until(() => ana.party.calls.includes('playAgain') && ana.party.calls.includes('goHome'), 'the Host verbs');
  },

  // The rules, from the same file the Party reads, filled in with its facts.
  async rules() {
    const { ana } = await table();
    ana.el['rules-open'].click();
    await until(() => ana.el.rules.open, 'the rules to open');
    const body = ana.text('rules-body');
    for (const title of ['Capturing', 'Kings', 'Ending a game']) assert.ok(body.includes(title), title);
    assert.ok(body.includes('Each side starts with 12 pieces'));
    assert.ok(body.includes('80 turns in a row'));
    assert.ok(!/[{}]/.test(body), 'a placeholder was left in the rules');
    assert.equal(ana.asked('onboarding.json').length, 1);
    ana.el['rules-open'].click();                                    // already open: not opened twice
    ana.el['rules-close'].click();
    assert.equal(ana.el.rules.open, false);
    ana.el['rules-open'].click();
    await until(() => ana.el.rules.open, 'the rules to open again');
    assert.equal(ana.asked('onboarding.json').length, 1);            // read once
  },

  // A newer launch replaces the game under the page: both phones ask for a seat again.
  async replaced() {
    const ana = phone([...SETUP.tickets.ana.one, ...SETUP.tickets.ana.next]);
    const ben = phone([...SETUP.tickets.ben.one, ...SETUP.tickets.ben.next]);
    ana.start();
    ben.start();
    await until(() => ana.S.view && ben.S.view, 'both players to be seated');
    const was = ana.S.token;
    await play(ana, sq(5, 2), sq(4, 3), () => ana.S.view.v === 2);
    assert.equal(await party(LAUNCH, SETUP.launch2), 200);           // the same two people, the other way round
    await until(() => ana.S.token && ana.S.token !== was && ana.S.view && ben.S.view && ben.S.view.v === 1,
      'both phones to be seated in the new game');
    assert.equal(ana.S.view.seat, 'b');
    assert.equal(ben.S.view.seat, 'w');
    assert.equal(ana.S.view.v, 1);
    assert.equal(ana.status(), 'Waiting for Ben.');
    assert.equal(ben.status(), 'Your move.');
    assert.equal(ana.darkCells()[0].dataset.sq, '62');               // Ana's board turned round
    assert.equal(ben.darkCells()[0].dataset.sq, '1');
    assert.equal(ana.cell(sq(5, 2)).dataset.piece, 'w');             // the new game starts from the opening
    assert.equal(ana.cell(sq(4, 3)).dataset.piece, undefined);

    // The Party ends it: the phones lose their seats and say so; nothing is left to play.
    assert.equal(await party(END, SETUP.end), 200);
    await until(() => !ana.S.view && !ben.S.view, 'both phones to lose their seats');
    assert.equal(ana.el.table.hidden, true);
    assert.equal(ana.status(), 'Waiting for the game to start.');
    assert.equal(ana.S.token, null);
    assert.equal(ana.el.resign.hidden, true);
  },

  // A phone with a stale board: its tap is turned away in the game's words and the board is brought up to date.
  async stale() {
    const hold = { polls: Promise.resolve() };
    let release;
    hold.polls = new Promise((resolve) => { release = resolve; });
    const ana = phone(SETUP.tickets.ana.one, { hold });
    const ben = phone(SETUP.tickets.ben.one);
    ana.start();
    ben.start();
    await until(() => ana.S.view && ben.S.view, 'both players to be seated');
    const other = phone(SETUP.tickets.ana.again);                      // Ana on a second page
    other.start();
    await until(() => other.S.view, 'the second page to be seated');
    await play(other, sq(5, 4), sq(4, 3), () => other.S.view.v === 2);
    assert.equal(ana.S.view.v, 1);                                   // her first page has heard nothing
    ana.cell(sq(5, 2)).click();
    ana.cell(sq(4, 3)).click();
    await until(() => ana.S.view.v === 2, 'the refusal to bring the board up to date');
    assert.equal(ana.status(), 'It is not your turn.');
    assert.equal(ana.asked('api/move').length, 1);
    assert.deepEqual(ana.S.trail, []);
    assert.equal(ana.cell(sq(4, 3)).dataset.piece, 'w');
    release();                                                       // and the poll that was held now answers
    await quiet(50);
    assert.equal(ana.S.view.v, 2);
  },

  // The game cannot be reached for a while: the page says so, keeps its board and comes back by itself.
  async link() {
    let down = true;
    const ana = phone(SETUP.tickets.ana.one, { failPolls: () => down });
    ana.start();
    await until(() => ana.S.view, 'the seat');
    await until(() => ana.status() === 'Reconnecting…', 'the page to say it lost the game');
    assert.ok(ana.S.view, 'the board stays while the link is down');
    assert.equal(ana.darkCells().length, 32);
    down = false;
    ana.win.fire('online');
    await until(() => ana.status() === 'Your move.', 'the page to come back', 4000);
    assert.equal(ana.S.linkDown, false);
  },

  // Opened by hand, outside the Party: the page says where to go and asks the Party for nothing.
  async noparty() {
    const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
    for (const told of [null, ORIGIN]) {
      const lonely = phone([], { fetch: async () => json({ partyOrigin: told }) });
      lonely.start();
      await until(() => lonely.el.app.dataset.mode === 'noparty', 'the page to notice');
      assert.equal(lonely.status(), 'Open Checkers from Party Home.');
      assert.equal(lonely.party.opts, null);
      assert.equal(lonely.requests.length, 1);
      assert.equal(lonely.el.table.hidden, true);
    }
  },
};

const name = process.argv[2];
if (!scenarios[name]) {
  console.error(`no scenario ${JSON.stringify(name)}; the scenarios are ${Object.keys(scenarios).join(', ')}`);
  process.exit(2);
}
for (const id of IDS) assert.ok(makeDocument().getElementById(id), `index.html has no #${id}`);
try {
  await scenarios[name]();
  console.log(`ok ${name}`);
  process.exit(0);                                                   // pages that are still polling would hold the process
} catch (error) {
  console.error(error);
  process.exit(1);
}
