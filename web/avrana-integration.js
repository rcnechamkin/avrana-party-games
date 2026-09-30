/* Explicit Avrana launch context. No credentials, new profile, chat or store.
   Load before every game client (including WORDCLASH and TV pages). */
(() => {
  'use strict';
  const version = 'avrana.lan-launch/v1';
  const integrated = /^\/games\/[a-z][a-z0-9_-]*\//.test(location.pathname)
    && new URLSearchParams(location.search).get('avrana') === '1';
  const home = integrated ? '/party/' : '/';
  window.AvranaIntegration = Object.freeze({ version, integrated, home });
  if (!integrated) return;
  document.documentElement.dataset.avrana = '1';
  const install = () => {
    document.querySelectorAll('[data-avrana-return]').forEach((link) => {
      link.href = home;
      link.textContent = 'Back to Party';
      link.setAttribute('aria-label', 'Back to Party');
    });
    document.querySelectorAll('[data-avrana-game-link]').forEach((link) => {
      const url = new URL(link.getAttribute('href'), location.href);
      if (url.origin === location.origin && url.pathname.startsWith('/games/')) {
        url.searchParams.set('avrana', '1'); link.href = url.pathname + url.search + url.hash;
      }
    });
    document.querySelectorAll('[data-avrana-profile-name]').forEach((input) => {
      input.readOnly = true;
      input.setAttribute('aria-label', 'Party name; edit your profile in Party');
    });
    document.querySelectorAll('[data-avrana-global]').forEach((el) => { el.hidden = true; });
    // In normal document flow; never place an overlay over game controls.
    const nav = document.createElement('nav');
    nav.setAttribute('aria-label', 'Party navigation');
    nav.id = 'avrana-navigation';
    const back = document.createElement('a');
    back.href = home; back.textContent = 'Back to Party';
    // The console model (avrana-party ADR 0011): while this phone is in a Party, the Party decides
    // where it is and only the Party Host moves it, so there is no Back to Party. The bar waits
    // for the Party's answer and shows only on a standalone page (or, for the host, one control).
    if (window.isSecureContext) nav.hidden = true;
    // Give full-screen clients the remaining space rather than clipping their
    // controls below a new header. Containment also bounds fixed game overlays.
    const room = document.createElement('div'); room.id = 'avrana-game-room';
    while (document.body.firstChild) room.appendChild(document.body.firstChild);
    nav.appendChild(back); document.body.append(nav, room);
    const style = document.createElement('link');
    style.rel = 'stylesheet'; style.href = '/shared/avrana-integration.css';
    document.head.appendChild(style);
    // Follow the party (AVR-128): Party Core decides where the party is; when the Party Host
    // switches games or ends this one, this page follows, like Party Home. The module belongs to
    // the Party (/party/lib/, HTTPS Full Mode only); without it, or without Party Core, nothing
    // changes here.
    if (window.isSecureContext) {
      const reveal = () => { nav.hidden = false; };     // Party mode hides it again in CSS
      const late = setTimeout(reveal, 4000);             // a slow or missing Party never strands it
      import('/party/lib/party-follow.js')
        .then((m) => m.startPartyFollow({ here: m.gameOfPath(location.pathname), container: nav }))
        .catch(() => null)
        .then(() => { clearTimeout(late); reveal(); });
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
