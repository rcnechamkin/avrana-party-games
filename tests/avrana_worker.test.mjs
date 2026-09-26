import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source = readFileSync('web/sw.js', 'utf8');
function worker(client = null) {
  const handlers = {}, deleted = [], requests = [];
  vm.runInNewContext(source, {
    URL, location: { origin: 'https://party.avrana.net' },
    self: { addEventListener: (name, fn) => { handlers[name] = fn; }, skipWaiting() {},
      clients: { claim: async () => {}, get: async () => client } },
    caches: { keys: async () => ['avrana-party-shell-dev','lan-games-shell-v3','lan-games-shell-v4','other'],
      delete: async (key) => { deleted.push(key); },
      match: async () => { throw new Error('Integrated request reached cache'); } },
    fetch: async (request) => { requests.push(request.url); return { ok: true }; },
  });
  return { handlers, deleted, requests };
}
test('standalone activation deletes only its own obsolete caches', async () => {
  const w = worker(); let done;
  w.handlers.activate({ waitUntil: (p) => { done = p; } }); await done;
  assert.deepEqual(w.deleted, ['lan-games-shell-v3']);
});
test('Party scope and integrated navigations bypass the root worker', () => {
  const w = worker();
  for (const path of ['/party/', '/party/app.js', '/games/chess/?avrana=1']) {
    let intercepted = false;
    w.handlers.fetch({ request: { method: 'GET', url: 'https://party.avrana.net' + path },
      respondWith() { intercepted = true; } });
    assert.equal(intercepted, false);
  }
});
test('integrated client assets use network, never standalone caches', async () => {
  const w = worker({ url: 'https://party.avrana.net/games/chess/?avrana=1' }); let done;
  w.handlers.fetch({ clientId: 'seat', request: { method: 'GET', url: 'https://party.avrana.net/shared/hubnet.js' },
    respondWith(p) { done = p; } }); await done;
  assert.equal(w.requests.length, 1);
});
