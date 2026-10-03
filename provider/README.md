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

## Party session contract: avrana.party-session/v0 (BLUFF; AVR-22, AVR-23, AVR-24)

Status: TESTED here (unit + fake-socket tests, Windows and CI; also against the real
avrana-party service over loopback HTTP/WebSockets, and in avrana-party's browser E2E
tests/provider/party-session.spec.ts); not deployed; no real phone yet.
The party is authoritative throughout: a network failure, reload, sleep/wake or an old
browser token never changes a party player's role, seat or identity by itself.
Protocol: core/party_protocol.py, vendored UNCHANGED from avrana-party
avrana/party/protocol.py (ADR 0006 there), with its vectors in tests/vectors/. A test pins
both hashes; re-vendor both files together, never edit them here.
The whole boundary (protocol digest, routes, launch integration, environment names) is declared in
provider/avrana-contract.json; tests/test_avrana_contract.py checks it against this code, and CI's
cross-repo job compares it with Party's contracts/party-games.v0.json (Party tools/contract_check.py).

- Config (deploy/avrana-party-session.conf, a systemd drop-in for the games service):
  $AVRANA_PARTY_KEYS names a directory holding <slug>.key (32-byte hex, 0600, the same key the
  party holds for that game; only core/party_session.GAMES = BLUFF look for one) and
  $AVRANA_PARTY_URL is the Party Core service on loopback (where `ended` goes). Both or
  neither: with a key but no usable URL, party sessions stay off (logged). Neither: exactly
  today's standalone behaviour. The drop-in's values (/etc/avrana-party/game-keys,
  http://127.0.0.1:8191) are PROPOSED until the Party Core deployment (AVR-51) confirms them.
- Capability: /api/games adds "avranaSession": "avrana.party-session/v0" to a game ONLY when
  this server loaded that game's key and a party URL, i.e. when it can really verify tickets
  and report the end.
- Launch: POST /games/<slug>/avrana/session/v0/launch {"message": <signed launch>}. Loopback
  and unproxied only (nginx's X-Forwarded-For/X-Real-IP/Forwarded are refused), 8 KiB, signed,
  30 s, nonce-checked. It replaces the room: a fresh session object, and every old socket is
  closed, watchers included, so each phone comes back with a fresh ticket and the new roster
  decides its role (a watcher of the last session who is a player now plays, no reload).
- Hello: {"t":"hello","ticket":…} is admitted with GameSide.admit(). The player key is
  game_token(sid, participant): the same participant reconnecting (with a fresh ticket) is
  the same player and seat. The name is the roster's; the game cannot rename a party member.
  The game token is never sent to the browser. Spectator tickets, and player tickets for
  someone not on the roster, watch. A refused ticket gets an `invalid` fx and a close.
- While a party session runs, a browser-minted wc-token (or any unticketed hello) only watches.
- hubnet.js, in an integrated (?avrana=1) player page: before every connect, POST
  /party/api/session/ticket (party cookie; the ticket never goes in a URL; 5 s per attempt) and
  send the ticket in the hello. A request that reaches nothing, times out or gets a 5xx is
  retried with the usual backoff and never becomes a ticketless hello; after 20 failures in a
  row the page waits for online/visibility. A tab that held a ticket remembers its session
  (sessionStorage; a session id, not a secret): when the party then answers "not a member",
  "no game" or "another game" (or no party service answers), that session is over for the
  page: it shows the ended state, never standalone play, and asks the party every 5 s while
  visible, joining the next launch that includes it (a rematch is a new party session). A page
  that never held a ticket keeps today's hello: the server decides (a watcher while the room
  belongs to a party session; standalone otherwise, so the /party/ shell's direct launch works).
- End: POST /games/<slug>/avrana/session/v0/end {"message": <signed end>}, the same guards as
  launch. The room goes back to a non-running state at once (a fresh session object; players'
  sockets get a `party_ended` fx and are closed; watchers stay and see the empty lobby) and the
  session's tickets die. No `ended` is sent back: the party asked. An end for the latest
  session that already finished here is acknowledged (200) too, so the host's End always
  confirms, but it never touches a room that has moved on. 200 {"ok": true}; else 4xx.
- `ended` (game -> party): BLUFF reports when its OWN rules stop a party game.
  completed = one seat left standing (the results screen with a winner, including a loss to
  test bots or a win by forfeits). abandoned = stopped before anyone won: the empty table
  timed out, the last one here used End game, a newcomer took over an empty table, or every
  seat forfeited in the same turn (no winner). No winner, score or result is sent (v0).
  A party game that never starts is not reported; the party's End ends it.
- The report is signed by GameSide.ended() under the room lock (admission for that session
  stops there) and POSTed off the lock and off the event loop to $AVRANA_PARTY_URL +
  /internal/party-session/v0/ended. $AVRANA_PARTY_URL must be a plain http loopback origin
  (e.g. http://127.0.0.1:8191); anything else is ignored with an error in the log (and, at
  startup, turns party sessions off; see Config). Exactly once: one
  report per session; delivery is one attempt plus retries after 1, 2 and 4 s (3 s timeout
  each) on no answer or 5xx, the same signed report each time (the party's replay guard and
  session check count it at most once); 200 or any 4xx is final. Undelivered, the party shows
  the game as on until the host's End. The report is never logged, only outcome and status.
- After a session ends (reported or ended by the party) the room returns to its pre-launch
  state: fresh, empty, not running, no party session. A completed game first finishes its
  results screen; meanwhile tickets are refused and unticketed hellos only watch. Then the
  session's phones get `party_ended`: integrated pages (hubnet.js) leave the room and show
  "This game is over." beside the fixed Back to Party link, then join the next launch that
  includes them. No automatic navigation away (ADR 0006 defers it). One party session is one
  play-through: there is no replay inside it; a rematch is a new launch. Non-integrated pages
  may play standalone again until the next launch.
- A browser cannot produce `ended`: only the server builds it (key-signed), from BLUFF's own
  rules. Watchers and browser-minted tokens cannot act; players cannot end a game others are
  still in; no game route accepts an `ended` message; the party's ended route answers only
  loopback, unproxied, signed, current-session reports.
- A phone asleep when its session ended misses `party_ended`; on waking the party has no
  ticket for it and the page shows the ended state (it remembered its session), never a
  standalone seat. Open: avatar photos and chat still use wc-token.

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
