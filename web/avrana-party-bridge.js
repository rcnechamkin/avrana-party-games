// The game page's side of the Party bridge (`avrana.party-bridge/v1`, ADR 0013).
//
// This file is the reference shim. A game repository vendors it unchanged and serves it from the
// GAME's own origin; it has no imports so that one file is the whole dependency. It embeds the
// Party's invisible frame (<party origin>/party/bridge.html) and turns its messages into the
// object game pages already use:
//
//   const party = connectParty({ partyOrigin: 'https://party.avrana.net', game: 'bluff' });
//   party.onChange((view) => …);      // {party, member, host, hostName, location, round}
//   const t = await party.ticket();   // {ok, ticket, role, expiresIn} | {ok: false, error}
//   await party.end();                // the host's verbs: {ok, error}
//   await party.goHome();
//   await party.playAgain();
//
// A game page holds no Party identity. It never sees a cookie, a member id or a device id, and
// it cannot call the Party API. When the party is somewhere else the page is taken to Party
// Home: the Party origin given here plus "/party/", never a URL that arrived in a message.
//
// The shim trusts only messages whose origin is `partyOrigin` and whose source is the frame it
// created; everything else is ignored.
export const PROTOCOL = 'avrana.party-bridge/v1';
const PUSHED = ['view', 'navigate', 'ticket', 'result'];
const ID = /^[A-Za-z0-9_-]{1,32}$/;
const AT = ['home', 'setup', 'game', 'results'];
const str = (v) => typeof v === 'string';
const nullable = (v) => v === null || str(v);

function keysAre(obj, ...names) {
  return Object.keys(obj).sort().join(',') === names.sort().join(',');
}

/** A message from the bridge, checked: the message itself, or null for anything else. */
export function parsePush(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data) || data.avrana !== PROTOCOL) return null;
  if (!PUSHED.includes(data.type)) return null;
  if (data.type === 'navigate') return keysAre(data, 'avrana', 'type', 'to') && data.to === 'party' ? data : null;
  if (data.type === 'view') {
    const v = data.view;
    if (!keysAre(data, 'avrana', 'type', 'view') || !v || typeof v !== 'object') return null;
    if (!keysAre(v, 'party', 'member', 'host', 'hostName', 'location', 'round')) return null;
    if (typeof v.party !== 'boolean' || typeof v.member !== 'boolean' || typeof v.host !== 'boolean'
        || !nullable(v.hostName)) return null;
    const loc = v.location;
    if (!loc || typeof loc !== 'object' || !keysAre(loc, 'at', 'game') || !AT.includes(loc.at) || !nullable(loc.game)) return null;
    const r = v.round;
    if (r !== null && (typeof r !== 'object' || !keysAre(r, 'game', 'state', 'outcome', 'myRole')
        || !nullable(r.game) || !nullable(r.state) || !nullable(r.outcome) || !nullable(r.myRole))) return null;
    return data;
  }
  if (!str(data.id) || !ID.test(data.id) || typeof data.ok !== 'boolean') return null;
  if (data.type === 'result') return keysAre(data, 'avrana', 'type', 'id', 'ok', 'error') && nullable(data.error) ? data : null;
  if (data.ok) {
    return keysAre(data, 'avrana', 'type', 'id', 'ok', 'ticket', 'role', 'expiresIn') && str(data.ticket)
      && str(data.role) && Number.isFinite(data.expiresIn) ? data : null;
  }
  return keysAre(data, 'avrana', 'type', 'id', 'ok', 'error') && str(data.error) ? data : null;
}

export function connectParty({ partyOrigin, game, window: win = globalThis, document: doc = win.document,
  go = (url) => win.location.replace(url), timeoutMs = 10000,
  schedule = (fn, ms) => win.setTimeout(fn, ms), cancel = (t) => win.clearTimeout(t) } = {}) {
  if (!/^https?:\/\/[^/]+$/.test(partyOrigin || '')) throw new Error('connectParty: partyOrigin must be an origin');
  const listeners = new Set(), waiting = new Map();
  const early = [];
  let view = null, seq = 0, stopped = false, loaded = false;

  const frame = doc.createElement('iframe');
  frame.hidden = true;
  frame.title = 'Avrana Party';
  frame.setAttribute('aria-hidden', 'true');
  frame.setAttribute('tabindex', '-1');
  // The frame needs its own origin (the Party cookie and profile live there) and scripts, and
  // nothing else: it may not navigate this page, open windows or submit forms.
  frame.setAttribute('sandbox', 'allow-scripts allow-same-origin');
  frame.src = partyOrigin + '/party/bridge.html';

  const send = (msg) => frame.contentWindow.postMessage({ avrana: PROTOCOL, ...msg }, partyOrigin);

  function onMessage(ev) {
    if (stopped || ev.origin !== partyOrigin || ev.source !== frame.contentWindow) return;
    const msg = parsePush(ev.data);
    if (!msg) return;
    if (msg.type === 'view') {
      view = msg.view;
      for (const fn of listeners) { try { fn(view); } catch { /* a listener's own problem */ } }
      if (doc.dispatchEvent && typeof win.CustomEvent === 'function') {
        doc.dispatchEvent(new win.CustomEvent('avrana-party', { detail: { location: view.location, host: view.host } }));
      }
    } else if (msg.type === 'navigate') {
      go(partyOrigin + '/party/');            // the only place a game page is ever sent
    } else {
      const pending = waiting.get(msg.id);
      if (!pending || pending.type !== msg.type) return;
      waiting.delete(msg.id);
      cancel(pending.timer);
      const { avrana, type, id, ...answer } = msg;
      pending.resolve(answer);
    }
  }

  function request(type, answerType) {
    if (stopped) return Promise.resolve({ ok: false, error: 'stopped' });
    const id = 'r' + (++seq);
    return new Promise((resolve) => {
      const timer = schedule(() => { waiting.delete(id); resolve({ ok: false, error: 'timeout' }); }, timeoutMs);
      waiting.set(id, { type: answerType, resolve, timer });
      // Before the frame has loaded there is nobody to hear a request: it waits for the hello.
      if (loaded) send({ type, id }); else early.push({ type, id });
    });
  }

  win.addEventListener('message', onMessage);
  frame.addEventListener('load', () => {
    if (stopped) return;
    loaded = true;
    send({ type: 'hello', game });
    for (const msg of early.splice(0)) if (waiting.has(msg.id)) send(msg);
  });
  (doc.body || doc.documentElement).append(frame);

  return {
    game,
    view: () => view,
    active: () => Boolean(view && view.party && view.member),
    isHost: () => Boolean(view && view.host),
    hostName: () => (view ? view.hostName : null),
    location: () => (view ? view.location : { at: 'home', game: null }),
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    /** A fresh ticket for this game's running session. Tickets are single-use: ask before every
     * connect and reconnect. */
    ticket: () => request('ticket', 'ticket'),
    end: () => request('end', 'result'),
    goHome: () => request('home', 'result'),
    playAgain: () => request('playAgain', 'result'),
    stop() {
      stopped = true;
      win.removeEventListener('message', onMessage);
      for (const p of waiting.values()) { cancel(p.timer); p.resolve({ ok: false, error: 'stopped' }); }
      waiting.clear();
      frame.remove();
    },
  };
}
