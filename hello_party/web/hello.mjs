// Hello Party page. EXPERIMENTAL reference (AVR-38): plain ES module, no framework, no storage, no cookie.
//
// The pattern every native game page follows (Checkers does the same, with more to draw):
//   1. ask THIS game's server where the Party is (GET api/party);
//   2. embed the Party's bridge through the vendored shim and ask it for a ticket;
//   3. trade the ticket for a seat at this game's server (POST api/redeem); keep the token in memory;
//   4. long-poll for newer views (POST api/poll); send intent as POSTs (POST api/greet);
//   5. on a reload or a lost seat, ask the bridge for a FRESH ticket: the same seat comes back.
// The page holds no Party identity and draws only what the server's view for this seat contains.
import { connectParty } from './avrana-party-bridge.js';

const $ = (id) => document.getElementById(id);
const GAME = 'hello';
const RETRY_MS = 3000;
const BACKOFF_MS = [1000, 2000, 4000, 8000];
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const S = { party: null, partyView: null, token: null, view: null, busy: false };

async function post(path, body, signal) {
  const res = await fetch(path, {
    method: 'POST', cache: 'no-store', credentials: 'omit', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let json = null;
  try { json = await res.json(); } catch { /* not JSON */ }
  return { ok: Boolean(res.ok && json && json.ok === true), status: res.status, body: json && typeof json === 'object' ? json : {} };
}

function say(text) { $('status').textContent = text; }

function render() {
  const v = S.view;
  const host = Boolean(S.partyView && S.partyView.host);
  $('card').hidden = !(v && v.you);
  $('secret').textContent = v && v.you ? v.you.secret : '';
  $('board-section').hidden = !v;
  const items = v ? v.board.map((e) => {
    const li = document.createElement('li');
    li.textContent = `${e.by}: ${e.text}`;
    return li;
  }) : [];
  $('board').replaceChildren(...items);
  const canSay = Boolean(v && v.seat !== null && !v.over && !v.greeted[v.seat]);
  $('say').hidden = !canSay;
  $('end').hidden = !(v && host && !v.over);
  $('done').hidden = !(v && v.over);
  $('host-actions').hidden = !(v && v.over && host);
  if (!v) return;
  if (v.over) {
    say('Everyone said hello.');
    $('done-detail').textContent = `${v.result.greetings} greetings. The Party has the result.`;
  } else if (v.seat === null) {
    say('You are watching.');
    $('waiting').textContent = '';
  } else if (v.greeted[v.seat]) {
    const waiting = v.names.filter((_, i) => !v.greeted[i]);
    say('Waiting for the others.');
    $('waiting').textContent = `Still to say hello: ${waiting.join(', ')}`;
  } else {
    say('Say hello when you are ready.');
    $('waiting').textContent = '';
  }
}

function apply(view) {
  if (S.view && view.v < S.view.v) return;          // a late answer never moves the page backwards
  S.view = view;
  render();
}

async function partyOrigin() {
  for (;;) {
    try {
      const res = await fetch('api/party', { cache: 'no-store', credentials: 'omit' });
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
  S.view = null;
  apply(reply.body.view);
  return true;
}

async function follow() {
  let failures = 0;
  while (S.token && S.view && !S.view.over) {
    let reply;
    try {
      reply = await post('api/poll', { token: S.token, since: failures ? S.view.v - 1 : S.view.v });
    } catch {
      failures += 1;
      say('Lost the connection. Trying again…');
      await delay(BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]);
      continue;
    }
    failures = 0;
    if (reply.status === 403) { S.token = null; S.view = null; render(); return; }   // the seat is gone
    if (reply.ok && reply.body.view) apply(reply.body.view); else await delay(1000);
  }
}

async function run() {
  const origin = await partyOrigin();
  if (!origin || origin === location.origin) {
    say('Open Hello Party from the Party on your Wi-Fi to join.');
    return;
  }
  S.party = connectParty({ partyOrigin: origin, game: GAME });
  S.party.onChange((view) => { S.partyView = view; render(); });
  for (;;) {
    if (!(await seat())) { say('Waiting for the Party…'); await delay(RETRY_MS); continue; }
    await follow();
    if (S.view && S.view.over) await delay(RETRY_MS);   // the Party holds the results; stay on them
  }
}

$('say').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (S.busy || !S.token) return;
  S.busy = true;
  $('problem').textContent = '';
  try {
    const reply = await post('api/greet', { token: S.token, text: $('text').value });
    if (reply.body.view) apply(reply.body.view);
    if (!reply.ok) $('problem').textContent = reply.body.message || 'That did not work. Try again.';
    else $('text').value = '';
  } catch {
    $('problem').textContent = 'Could not reach the game. Try again.';
  } finally {
    S.busy = false;
  }
});
$('end').addEventListener('click', async () => {
  if (!window.confirm('End the game for everyone? No result is recorded.')) return;
  const done = await S.party.end();
  if (!done.ok) $('problem').textContent = 'Could not end the game. Try again.';
});
$('again').addEventListener('click', () => S.party.playAgain());
$('home').addEventListener('click', () => S.party.goHome());

run().catch((error) => console.error(error));
