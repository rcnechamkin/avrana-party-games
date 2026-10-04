/* Explicit Avrana launch context. No credentials, new profile, chat or store.
   Load before every game client (including WORDCLASH and TV pages). */
(() => {
  'use strict';
  const version = 'avrana.lan-launch/v1';
  const slug = (/^\/games\/([a-z][a-z0-9_-]*)\//.exec(location.pathname) || [])[1] || null;
  const integrated = slug !== null && new URLSearchParams(location.search).get('avrana') === '1';
  // Party Home. On the Party's own origin it is this path; on the game origin (avrana-party
  // ADR 0013) it becomes the Party origin this server is configured with, plus this path.
  let home = integrated ? '/party/' : '/';
  /* Where the Party is, for this page (avrana-party ADR 0013, AVR-226):
       same origin   the page shares the Party's origin (today's deployment, and Limited Mode):
                     the Party's own module runs here and tickets are fetched with the cookie.
       game origin   this server names a Party origin that is not this page's: the page holds no
                     Party identity and cannot call the Party API. It embeds the Party's bridge
                     frame through the vendored shim (avrana-party-bridge.js) and everything it
                     may have of the Party (its view, tickets, the host's verbs) comes from there.
     `party` resolves to the shim's connection on the game origin, and to null otherwise. Game
     clients (hubnet.js) wait for it before they ask for a ticket. */
  let settle;
  const party = new Promise((resolve) => { settle = resolve; });
  window.AvranaIntegration = Object.freeze({ version, integrated, get home() { return home; }, party });
  if (!integrated) { settle(null); return; }
  document.documentElement.dataset.avrana = '1';

  // The Party origin comes from this server's configuration only: never from the address bar, a
  // link or a message, so no page can be pointed at another "Party". Only an answer decides: a
  // server that says nothing (a timeout, an error, a 5xx) has not said "same origin", so the page
  // asks again until it is told. A 404 is an answer: a server from before the game origin.
  const CONFIG_WAIT = 3000, CONFIG_RETRY = [500, 1000, 2000, 4000];
  async function askPartyOrigin() {
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = setTimeout(() => { if (ctl) ctl.abort(); }, CONFIG_WAIT);
    try {
      const res = await fetch('/api/avrana', { cache: 'no-store', signal: ctl ? ctl.signal : undefined });
      if (res.status === 404) return null;
      if (!res.ok) return undefined;
      const origin = (await res.json()).partyOrigin;
      return typeof origin === 'string' && /^https?:\/\/[^/]+$/.test(origin) && origin !== location.origin ? origin : null;
    } catch (error) {
      return undefined;
    } finally {
      clearTimeout(timer);
    }
  }
  const partyOrigin = (async () => {
    for (let i = 0; ; i += 1) {
      const origin = await askPartyOrigin();
      if (origin !== undefined) return origin;
      await new Promise((resolve) => setTimeout(resolve, CONFIG_RETRY[Math.min(i, CONFIG_RETRY.length - 1)]));
    }
  })();

  const CONFIRM_MS = 4000;                    // a second tap within this ends the game

  /* The game origin: the Party through the bridge. Publishes the same window.AvranaParty the
     Party's own module publishes on its origin, so a game's chrome is written once. */
  async function followThroughBridge(origin, nav, reveal) {
    const { connectParty } = await import('/shared/avrana-party-bridge.js');
    const conn = connectParty({ partyOrigin: origin, game: slug });
    const api = {
      get active() { return conn.active(); },
      view: conn.view, isHost: conn.isHost, hostName: conn.hostName, location: conn.location,
      end: conn.end, goHome: conn.goHome, playAgain: conn.playAgain, onChange: conn.onChange,
    };
    let endBtn = null, armed = null;
    const endLabel = 'End game for everyone';
    async function onEnd() {
      if (!conn.isHost()) return;
      if (!armed) {
        endBtn.textContent = 'Tap again to end it';
        armed = setTimeout(() => { armed = null; endBtn.textContent = endLabel; }, CONFIRM_MS);
        return;
      }
      clearTimeout(armed);
      armed = null;
      endBtn.disabled = true;
      await conn.end();
      endBtn.disabled = false;
      endBtn.textContent = endLabel;
    }
    // Games that draw the host's controls themselves say so; the rest get one quiet End.
    function fallbackControls(view) {
      if (document.querySelector('[data-avrana-party-shell]')) return;
      const show = view.host && view.location.at === 'game' && view.location.game === slug;
      if (!endBtn && show) {
        endBtn = document.createElement('button');
        endBtn.type = 'button';
        endBtn.id = 'avrana-party-end';
        endBtn.textContent = endLabel;
        endBtn.addEventListener('click', onEnd);
        nav.append(endBtn);
      }
      if (endBtn) endBtn.hidden = !show;
      nav.toggleAttribute('data-avrana-host', show);
    }
    conn.onChange((view) => {
      if (view.party && view.member) {
        // In a Party the game owns the viewport and only the Party Host moves the party.
        document.documentElement.dataset.avranaParty = 'on';
        window.AvranaParty = api;
        fallbackControls(view);
      }
      reveal();
    });
    return conn;
  }

  const install = () => {
    const back = document.createElement('a');
    const point = () => {
      back.href = home;
      document.querySelectorAll('[data-avrana-return]').forEach((link) => { link.href = home; });
    };
    document.querySelectorAll('[data-avrana-return]').forEach((link) => {
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
    back.textContent = 'Back to Party';
    point();
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
    const reveal = () => { nav.hidden = false; };       // Party mode hides it again in CSS
    // A slow or missing Party, or a server slow to say where the Party is, never strands it.
    const late = window.isSecureContext ? setTimeout(reveal, 4000) : null;
    partyOrigin.then((origin) => {
      if (origin) {
        home = origin + '/party/';
        point();
        followThroughBridge(origin, nav, () => { clearTimeout(late); reveal(); })
          .catch(() => null)
          .then((conn) => { settle(conn); if (!conn) { clearTimeout(late); reveal(); } });
        return;
      }
      settle(null);
      // Follow the party (AVR-128): Party Core decides where the party is; when the Party Host
      // switches games or ends this one, this page follows, like Party Home. The module belongs to
      // the Party (/party/lib/, HTTPS Full Mode only); without it, or without Party Core, nothing
      // changes here.
      if (window.isSecureContext) {
        import('/party/lib/party-follow.js')
          .then((m) => m.startPartyFollow({ here: m.gameOfPath(location.pathname), container: nav }))
          .catch(() => null)
          .then(() => { clearTimeout(late); reveal(); });
      }
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install, { once: true });
  else install();
})();
