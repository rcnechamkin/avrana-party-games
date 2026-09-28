# Avrana browser-game provider

LAN Games is legacy MVP infrastructure undergoing assimilation. It supplies
individual games and temporary avatar/chat transport; it does not own a second
canonical profile, chat, library, catalog or global navigation.

Metadata authority: games/registry.py REGISTRY and EXTERNAL (WORDCLASH is mounted
in this server). ops/export_avrana_catalog.py reads literal public fields without
importing game runtimes or reading venue.json. Dynamic fields fail explicitly.
Hidden templates are excluded; launch pages must exist. IDs are lan-<slug>, except
existing BLUFF ID bluff. Do not duplicate BLUFF or infer late join/spectator facts.

```
python ops/export_avrana_catalog.py --out provider/catalog.json
python ops/export_avrana_catalog.py --check provider/catalog.json
python ops/export_avrana_catalog.py --check ../avrana-party/contracts/catalogs/lan-games.json
```

The snapshot source.commit pins the reviewed metadata input revision;
registrySha256 hashes normalized source text. A check preserves that provenance
commit and compares all deterministic fields and the digest. On provider changes,
regenerate/review the donor snapshot and copy ONLY that public JSON to the platform,
then run python -m avrana.contracts.catalog there. Venue titles, live counts,
credentials and machine paths are never part of this export. Avrana installation
grants and capability contracts remain Avrana-owned, including BLUFF private hands.

## Integration contract: avrana.lan-launch/v1

/api/games advertises avranaIntegration with value avrana.lan-launch/v1. A known mounted title
opens /games/<slug>/?avrana=1. The marker is context, not authority or credentials.
The shared bootstrap runs before all game clients, including WORDCLASH and TV.
It uses declared data-avrana-* surfaces, suppresses legacy global return/profile
controls and provides one 44px Back to Party control in document flow. It does not
overlay game controls. Game-specific lobbies, ready buttons, rules, private UI,
feedback and control layouts stay game-owned. Profile name is read-only here;
edit it in /party/. Standalone URLs without the marker keep legacy development UX.

Return is fixed same-origin /party/ (production https://party.avrana.net/party/).
No arbitrary return parameter, identity URL or history dependency exists. Marked
TV links and QR destinations retain context and HTTPS. Shared chrome script URLs
are versioned to avoid old cache-first workers replaying pre-integration code.
Integrated clients do not register the root SW. The updated standalone worker
bypasses /party/ and integrated clients and only deletes lan-games-shell-* caches.
It does not widen Avrana's /party/ worker scope. Existing pre-upgrade root worker
registrations may require their normal update/refresh; test that path on devices.

## Party session contract: avrana.party-session/v0 (BLUFF; AVR-22)

Status: TESTED here (unit + fake-socket tests, Windows and CI); not deployed; no real phone yet.
Protocol: core/party_protocol.py, vendored UNCHANGED from avrana-party
avrana/party/protocol.py (ADR 0006 there), with its vectors in tests/vectors/. A test pins
both hashes; re-vendor both files together, never edit them here.

- Keys: $AVRANA_PARTY_KEYS names a directory holding <slug>.key (32-byte hex, 0600, the same
  key the party holds for that game). Only core/party_session.GAMES (BLUFF) look for one. No
  key means no party side and exactly today's standalone behaviour.
- Capability: /api/games adds "avranaSession": "avrana.party-session/v0" to a game ONLY when
  this server loaded that game's key, i.e. when it can really verify tickets.
- Launch: POST /games/<slug>/avrana/session/v0/launch {"message": <signed launch>}. Loopback
  and unproxied only (nginx's X-Forwarded-For/X-Real-IP/Forwarded are refused), 8 KiB, signed,
  30 s, nonce-checked. It replaces the room: a fresh session object, old sockets closed.
- Hello: {"t":"hello","ticket":…} is admitted with GameSide.admit(). The player key is
  game_token(sid, participant): the same participant reconnecting (with a fresh ticket) is
  the same player and seat. The name is the roster's; the game cannot rename a party member.
  The game token is never sent to the browser. Spectator tickets, and player tickets for
  someone not on the roster, watch. A refused ticket gets an `invalid` fx and a close.
- While a party session runs, a browser-minted wc-token (or any unticketed hello) only watches.
- hubnet.js, in an integrated (?avrana=1) page: before every connect, POST
  /party/api/session/ticket (party cookie; the ticket never goes in a URL) and send the ticket
  in the hello. No ticket (no party service, not a member, another game): today's hello.
- Not yet (AVR-24): /end, `ended` reports (completed | abandoned) and returning to no session.
  Until then a party session lasts until the next launch or a server restart. Avatar photos
  and chat still use wc-token.

## Shared local state

wc-token/name/avatar/pfp remain the same compatible identity keys. Hub.identity
and WORDCLASH consume them; no new identity store or account is created. Avatars
still use /api/avatar with x-wc-token and ignored data/avatars. Legacy credential
separation/auth hardening remains future work, not a claim of this adapter.
HTTP/IP/.local profiles cannot be recovered from a different HTTPS origin.

lg-favorites/recent/play-total remain the same backing store. Canonical entries
use avrana:<GameContract ID>. Avrana lazily collapses known raw-slug/bare-ID aliases;
unknown entries survive. Standalone hub converts canonical LAN keys for its
existing tile UI and writes known titles canonically. Games do not record launches
again: history means opened by the shell/hub, not verified play or reloads.

Party Chat remains the singleton /chat/ws rolling history. Integrated games open
no competing global chat UI or socket; returning to Party reconnects to that same
history. Standalone hub retains compatibility chat. Connected chat clients and game
seats are not canonical Party membership. No per-game channels or roster added.

## Review and staggered merge

Donor PR first: backward compatible standalone behavior, advertises support.
Platform PR second: requires that advertisement, otherwise shows Games update
needed and disables launches rather than silently entering the legacy shell.
Deployment is separate and owner-controlled: no deployment in this sprint.
Run the cross-repository Playwright harness in the platform repository with both
checkouts as documented there. Hardware acceptance remains required on Pi/phones.
