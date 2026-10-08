/* LAN Games app shell. Multiplayer state is always live and never cached;
   only the lightweight interface/assets are kept for fast repeat launches. */
const CACHE = "lan-games-shell-v5";
const SHELL = [
  "/",
  "/offline",
  "/shared/shared.css",
  "/shared/hub-premium.css",
  "/shared/gameart.css",
  "/shared/hubnet.js",
  "/shared/hub.js",
  "/shared/gameart.js",
  "/shared/brand.js",
  "/shared/qr.js",
  "/shared/app-icon.svg",
  "/shared/app-icon-192.png",
  "/shared/app-icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key.startsWith("lan-games-shell-") && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;
  // Avrana owns this shell and integrated launches. Existing root registrations
  // must bypass both, including scripts/requests made by an integrated client.
  if (url.pathname.startsWith('/party/') || url.searchParams.get('avrana') === '1') return;
  if (event.clientId) {
    event.respondWith((async () => {
      const client = await self.clients.get(event.clientId);
      if (client && new URL(client.url).searchParams.get('avrana') === '1') return fetch(request);
      return legacyResponse(request, url);
    })());
    return;
  }
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/avatars/')
      || url.pathname.startsWith('/chatmedia/')) return;
  event.respondWith(legacyResponse(request, url));
});

function legacyResponse(request, url) {
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/avatars/")
      || url.pathname.startsWith("/chatmedia/")) return fetch(request);

  if (request.mode === "navigate") {
    return (
      fetch(request).catch(() =>
        caches.match(request).then((hit) => hit || caches.match("/offline")))
    );
  }

  if (url.pathname.startsWith("/shared/") || url.pathname.startsWith("/games/")) {
    return (
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      }))
    );
  }
  return fetch(request);
}
