# Spades: native-migration readiness packet (AVR-312)

Observed 2026-10-07 at avrana-party-games `a448972` (origin/main) and avrana-party `75b5062`.
Historical evidence, not a plan and not a decision record: it says what Spades needs from a
native platform so that AVR-41 can start from facts. Nothing in `games/spades/`, `core/`,
`provider/`, the registry or any catalog changed, the retired LAN Games runtime is not
revived, and Spades stays unreachable from Party Home. The only code this work adds is two
test files (section 10).

How to read it:

- `path:line` is this repository at `a448972`. `party:path:line` is avrana-party at `75b5062`.
  `ADR 0015:N`, `ADR 0014:N` and `ADR 0010:N` are line N of
  `party:docs/adr/0015-game-result-envelope.md`,
  `party:docs/adr/0014-native-games-isolated-lan-games-retired.md` and
  `party:docs/adr/0010-party-pregame.md`. A bare `:N` continues the file named just before it in
  the same sentence or table row. "Linear AVR-N" is the issue text as read on 2026-10-07.
- A sentence in a **Facts** list was checked against source or by running it. "Measured" means
  a scratch script (not committed) ran the code; the numbers can be reproduced with
  `core/party_result.build` and `SpadesSession.state_for`.
- A **Proposal** is a labelled suggestion for the owner. No proposal here is a decision and
  none changes an Open Decision elsewhere.
- Party-side behaviour was read from source at `75b5062`. Nothing was run on the Pi, nothing was
  deployed, and no browser or phone was used.

## 1. Summary

- `games/spades/` is 749 lines of Python (rules 106, bots 268, session 375) and 898 lines of
  web client (page 140, styles 178, script 580). Rules and bots are pure and import nothing
  outside `games.spades` (`games/spades/rules.py:9`, `games/spades/bots.py:22-24`). The session
  is a subclass of the fork's `GameSession` (`games/spades/game.py:29`) and the page is a client
  of the shared `hubnet.js` (`games/spades/web/index.html:136-138`).
- Spades cannot be launched by a Party today: it has no party side
  (`core/party_session.py:53`), its launch route answers 404 `no_party_session`
  (`server.py:189-192`, `:162-164`), Party Home grants only three games
  (`party:contracts/appliances/avrana-pi4.json:67-94`) and nginx sends `/games/spades/` to a
  socket nobody provisioned (`party:deploy/games/nginx-native-games.location:20-25`).
- If a Party did seat it as it stands, a match would reach `game_end` and report nothing: the
  session never sets an outcome and has no `game_result()` (`core/session.py:193-217`, no
  override in `games/spades/game.py`). That, a one-human crash, a fifth player with no seat and
  an abandon with no outcome are pinned by tests in `tests/test_spades_session_pins.py` as
  today's gaps, not as behaviour to keep.
- The Game Contract has no teams field (`party:avrana/contracts/game.py:60-62`) and the result
  envelope deliberately has no team or score field (`party:docs/adr/0015-game-result-envelope.md:82-84`).
  Teams, four seats with bots, private hands, a per-seat clock and a multi-hand match are what
  Spades asks of the platform that Checkers (AVR-238) does not (section 11).
- Nine owner decisions, plus four more the issue did not list, stand between this packet and a
  build (section 13). The Checkers D1 to D10 decisions carry over, reopen or are new for Spades
  as mapped in section 13.3.
- The rules module is portable as it is. Of the 38 existing Spades tests, 25 survive a move
  unchanged (all 19 in `tests/test_bots.py` and 6 of 19 in `tests/test_spades.py`); the 35 new
  tests split into 17 portable rules tests and 18 session tests, five of which pin gaps on
  purpose (section 10).

### What AVR-41 asks to be captured, and where it is answered

| AVR-41 capture item (Linear AVR-41) | Where |
|---|---|
| source and game architecture detected | sections 2 and 3 |
| platform primitives that replace source-specific identity, session and navigation | sections 4, 11 and 13 |
| first-play onboarding and rules representation | section 12 |
| UI shows only valid actions; game authority validates | section 7 (last bullet) and section 12 |
| game-owned visuals versus shared interaction primitives | section 5 |
| licence and provenance constraints for redistribution | section 5 (last table) and decision S9 |

## 2. Source map

Line counts are `wc -l` at `a448972`.

| File | Lines | Imports (outside the standard library) | Role |
|---|---:|---|---|
| `games/spades/__init__.py` | 0 | none | package marker |
| `games/spades/rules.py` | 106 | none (`from __future__` only, `:9`) | cards, deck, `sort_hand`, `legal_plays`, `trick_winner`, `score_hand` |
| `games/spades/bots.py` | 268 | `games.spades.rules` (`:24`) | `RookieBot`, `StandardBot`, `make_bot` |
| `games/spades/game.py` | 375 | `core.session.GameSession`, `games.spades.rules`, `games.spades.bots.make_bot` (`:21-23`) | `SpadesSession`: seating, bidding, play, scoring, match end, projection |
| `games/spades/web/index.html` | 140 | scripts `/shared/avrana-integration.js` (`:4`), `/shared/hubnet.js` (`:136`), `/shared/brag.js` (`:137`); style `/shared/shared.css` (`:13`) | join, lobby, table, scorecard, game-over |
| `games/spades/web/spades.css` | 178 | 16 design tokens from `shared.css` (section 5) | table layout and cards |
| `games/spades/web/spades.js` | 580 | globals `Hub` (`hubnet.js`) and `Brag` (`brag.js`) | rendering and input; the server is authoritative (`games/spades/web/spades.js:1-2`) |

The directory holds nothing else: no README, no docs, no rules text, no `onboarding.json`, no
art or audio file (a directory listing at `a448972`).

What else in this repository names Spades:

| Where | What |
|---|---|
| `games/registry.py:14`, `:228-242` | the registry entry: slug, `min_p` 2, `max_p` 4, blurb, `session: SpadesSession`, web directory |
| `provider/catalog.json:435-450` | the exported catalog row `lan-spades` (launch path `/games/spades/`) |
| `web/gameart.js:108-110` | the library artwork scene for Spades (first party, an inline spade shape) |
| `web/hub.js:83` | the retired hub's duration label, "25-45 min" |
| `core/session.py:3`, `ADDING_A_GAME.md:23, 100, 273, 339, 521` | Spades is documented as the fork's reference game |
| `games/hearts/game.py:3`, `games/euchre/game.py:3` | Hearts and Euchre are written in Spades' shape and copy its bot contract (`games/hearts/bots.py:15`, `games/euchre/bots.py:1`) |
| `tests/test_spades.py`, `tests/test_bots.py`, `tests/test_spades_rules.py`, `tests/test_spades_session_pins.py` | Python suites (section 10) |
| `tests/playtest_spades.mjs`, `tests/hub_profile_test.mjs:97-98`, `tests/pfp_test.mjs:102` | browser scripts against the retired hub; not run for this packet |

The shared code Spades stands on (line counts at `a448972`): `core/session.py` 492,
`core/net.py` 644, `core/party_session.py` 234, `core/party_result.py` 181 and
`core/party_protocol.py` 490 (the last two are vendored byte-identical from Party,
`core/party_session.py:3-4`); in `web/`: `hubnet.js` 850, `shared.css` 413, `brag.js` 272,
`avrana-integration.js` 185 and `.css` 61, `avrana-party-bridge.js` 143, `brand.js` 100,
`gameart.js` 264 and `.css` 103.

## 3. Hub and session dependencies

What `SpadesSession` and its page take from the fork's runtime, and what a native Spades has to
provide for itself. The classification of each shared module (donor, extraction candidate,
legacy) is Party's: `party:docs/design/NATIVE-GAMES.md:78-93`.

| Dependency | Facts | A native Spades must |
|---|---|---|
| Session base class | `SpadesSession(GameSession)` (`games/spades/game.py:29`); knobs `MIN_PLAYERS = 2`, `MAX_HUMANS = 8`, `DEFAULT_SETTINGS` (`games/spades/game.py:30-39`; the base's defaults, `core/session.py:117-119`). Overrides, all in `games/spades/game.py`: `validate_settings` (`:47`), `game_start` (`:65`), `game_action` (`:155`), `game_tick` (`:265`), `game_state` (`:336`), `game_player_left` and `game_player_back` (`:318`, `:326`), `next_bot_action` and `run_bot` (`:296`, `:307`). Does not override `host_action` (the base refuses, `core/session.py:154-159`), `game_state_spectator` (the base returns the public view, `core/session.py:170-173`), `take_outcome` or `game_result` (`core/session.py:193-217`). | Re-express the behaviour, not the inheritance: `GameSession` is a pattern donor (`party:docs/design/NATIVE-GAMES.md:82`). |
| Lobby and start | Ready, start, the 3-2-1 countdown, the minimum-player gate and the lock-in of participants in join order are base-class code (`core/session.py:284-311`, `:377-411`, `:426-441`; `COUNTDOWN_SECONDS` `:42`). The page draws the lobby (`spades.js:114-162`). | Nothing of it in a Party round: the Party ran the pregame, and the base refuses ready, start and settings (`core/session.py:379-380`, `:393`, `:401-402`; `party:docs/adr/0010-party-pregame.md:45-48`). |
| Party round entry | `party_start(seats)` seats the roster in order and arms a 15 s arrival wait (`core/session.py:349-366`, `PARTY_ARRIVAL_SECONDS` `:45`); `tick` then calls `game_start()` and marks missing seats away (`:417-425`). | Seat by roster order (S2); decide what "away at the deal" means (S4). |
| One timer | One `(deadline, gen)` pair: a wall-clock deadline for browsers, the wait on the monotonic clock (`core/session.py:226-248`); `GameBinding` re-arms it after every push and ignores stale generations (`core/net.py:131-169`). Spades uses it for the turn clock (`games/spades/game.py:132-133`) and the 14 s recap (`:25`, `:246`). | One pending deadline per room is enough: only one clock runs at a time. |
| Bots and absent seats | `next_bot_action()` returns `(delay, token)` (`game.py:296-305`); `GameBinding` schedules it and drops it if `seq` moved (`core/net.py:173-205`; `game.py:156`, `:313`). | A scheduler that any other mutation cancels. |
| Per-viewer push | After every mutation `push_all` sends `state_for(token)` to each player socket, the public state to watchers and the spectator state to Party spectators (`core/net.py:95-127`). | Per-viewer projection (section 7). |
| Sockets | `/games/spades/ws` (`server.py:67-77`); 32 anonymous watchers (`core/net.py:49`, `:492-502`); 4 sockets per token (`:46`, `:517`); 30 messages per 2 s and 4096 characters per message (`:44`, `:547-554`). | Its own limits. |
| Match end | `end_game()` enters `game_end`. In a Party round no timer runs and the results stay until the Host moves on; outside a Party the room returns to the lobby after `GAME_END_SECONDS = 20` (`core/session.py:44`, `:442-443`, `:446-453`). | Hold the results (`party:docs/design/GAME-UX-CONTRACT.md:842-846`, Rule 12.1). |
| Outcome and result | After every mutation the binding reads `take_outcome()` and, for "completed", asks `game_result(ref)` once (`core/net.py:284-301`, `:303-332`). Spades sets and defines neither. | Report completed or abandoned, and a result (section 9). |
| Back to lobby | The base verb `again` returns to the lobby at `game_end` (`core/net.py:642-643`); the page's "BACK TO LOBBY" sends it (`spades.js:532`). | No game-side way back to a lobby in a Party round: results are held until the Host chooses Play again, which goes to a new setup (`party:docs/design/GAME-UX-CONTRACT.md:842-846`, Rule 12.1), and no game returns phones by itself (`:866-868`, Rule 12.4, proposed for every game). |
| Party side | `GAMES = ("bluff", "expo")` (`core/party_session.py:53`); `provider/avrana-contract.json:47` (`party_side_games`) and `:19` (`result.reported_by`) leave Spades out. A launch gets 404 (`server.py:189-192`, `:162-164`); a ticket hello is refused (`core/net.py:467-475`). | A contract file, a grant with a `runtime`, a key and provisioning (`party:docs/runbooks/provision-game.md:10-14`, `:32-45`, `:49-57`). |
| Registry, catalog, static files | One `REGISTRY` entry (`games/registry.py:228-242`) becomes one binding (`server.py:66-70`) and one static mount (`:350-352`). | The native path's contract, grant and registry replace it. |
| Build id | `build_id("spades")` hashes `server.py`, `requirements.txt`, `core/**/*.py`, `games/__init__.py`, `games/registry.py` and `games/spades/` without `web`, `art`, `docs` (`core/party_session.py:70-72`, `:75-108`). | Keep the layout it assumes or change it with Party (Linear AVR-238 plan, gap 5: a new top-level directory is invisible to it). |
| Fresh room | Each launch replaces the session with `type(self.session)()` (`core/net.py:273`). | A no-argument constructor (`SpadesSession(rng=None)`, `game.py:41`, qualifies). |
| Persistence | None: the whole match is `self.g`, in memory (`game.py:43`). EXPO saves a standalone snapshot and says Party tables are not saved (`games/expo/game.py:93-109`, `games/expo/storage.py:1-40`). | A decision (S10). |

Other hub services Spades does not use: chat, venue branding and the hub page. The page never
calls them.

## 4. Identity and navigation dependencies

Facts:

- **Standalone identity.** The join screen asks for a call sign, an avatar and optionally a
  photo (`games/spades/web/index.html:19-33`; `spades.js:507-517`, `:568-572`). `Hub.identity`
  keeps `wc-token`, `wc-name`, `wc-avatar` and `wc-pfp` in localStorage
  (`web/hubnet.js:55-64`); the hello carries them (`:616-620`); the server accepts a well-formed
  client token or mints one (`core/net.py:504-509`); photos go to `/api/avatar` under that
  token (`web/hubnet.js:157-170`; `server.py:238-251`), and the stored photo is attached to the
  player at hello (`core/net.py:530`).
- **Party identity.** A ticket hello carries `{ticket, avatar}` (`web/hubnet.js:613-614`). The
  game learns a participant id and the Party's display name, nothing else
  (`core/net.py:361-379`; `party:docs/design/GAME-UX-CONTRACT.md:552-553`), and a Party
  member cannot be renamed by the game (`core/net.py:636`). The name field and avatar controls
  carry `data-avrana-profile-name` and `data-avrana-global`, which the integration script makes
  read-only and hides (`index.html:26`, `:28-29`, `:41`; `web/avrana-integration.js:135-139`;
  `web/avrana-integration.css:2`). A Party roster is players in join order, then spectators
  (`party:avrana/party/core.py:162-163`, `:466-467`).
- **The page does not know it is in a Party.** `spades.js` never mentions `AvranaIntegration`,
  `party_round`, `party_host` or the spectator flag. On a phone with no stored `wc-name` it shows
  the join screen and waits for "TAKE A SEAT" before it connects, Party or not
  (`spades.js:574-580`).
- **Navigation.** Two `data-avrana-return` links to `/` (`index.html:38`, `:77`) are relabelled
  "Back to Party" (`web/avrana-integration.js:125-128`) and hidden on every integrated page
  (`web/avrana-integration.css:16`); the platform's own "Back to Party" bar stands in for them
  and is hidden in a Party for everyone but the Host's single control
  (`web/avrana-integration.css:47-49`). Without a `[data-avrana-party-shell]` element that
  control is a host-only "End game for everyone" (`web/avrana-integration.js:92-106`;
  `party:docs/design/GAME-UX-CONTRACT.md:167-172`).
  On the game origin the page reaches the Party through the vendored bridge
  (`web/avrana-integration.js:56-117`); on the Party's origin through `/party/lib/party-follow.js`,
  which NATIVE-GAMES lists as legacy and not ported (`web/avrana-integration.js:171-180`;
  `party:docs/design/NATIVE-GAMES.md:87`).
- **End of a match.** The game-over card says "BACK TO LOBBY" and counts "lobby in Ns"
  (`index.html:128-129`; `spades.js:485-487`, `:532`). In a Party round `game_end` has no
  deadline, so the count reads "lobby in 0s" (`spades.js:63-66`; `core/session.py:450-452`), and
  the button sends `again`, which returns a Party-seated room to a lobby whose verbs are all
  refused (`core/net.py:642-643`; pinned by
  `test_party_settings_and_lobby_verbs_are_refused_so_the_fork_defaults_stand`). The shared
  "Round over" panel with the Host's Play again and Party Home appears only after a
  `party_ended` fx (`web/hubnet.js:626-628`, `:668-737`), which needs an outcome Spades never
  records.

Proposal: a native Spades takes identity from the Party only (no join screen, avatar picker or
photo upload: Rules 6.1 and 6.2), shows the Party name beside each human seat, gives non-hosts
no route out (Rule 3.3), leaves Play again and End to the Host (Rules 3.4, 12.1, 12.3), and keeps
"Party Host" distinct from any in-game role (Rule 6.5). All seven rules:
`party:docs/design/GAME-UX-CONTRACT.md:131-140`, `:527-555`, `:840-868`. Rules 3.3, 3.4, 12.1 and
12.3 are accepted there; the parts of 6.1, 6.2 and 6.5 that bind a game (no name field or avatar
picker of its own, the Party name shown, "Party Host" labelled apart from a game role) are
proposed.

## 5. Shared UI dependencies

Facts:

- **Shared client API.** `spades.js` calls `Hub.connect` (`:501`), `Hub.identity` (`:507`,
  `:512-513`, `:572`, `:574`), `Hub.AVATARS` (`:508`), `Hub.buildAvatarGrid` (`:571`),
  `Hub.wirePfpButton` (`:568-569`), `Hub.fillAvatar` (`:122`, `:188`), `Hub.toast` (`:431-432`,
  `:436`), `Hub.confettiBurst` (`:396`, `:399`) and `Brag.button` (`:536`).
- **Shared style.** `spades.css` uses 16 design tokens from `web/shared.css` (`--bg --cyan
  --danger --faint --grad --green --line --mono --muted --pink --raised --sab --sat --surface
  --text --violet`), and the page uses shared classes such as `.btn`, `.icon-btn`, `.modal`,
  `.topbar`, `.avatar-grid`, `.wordmark`, `.bg-fx`, `.pfp-btn` and `.player-card`, all defined in
  `web/shared.css`. `hubnet.js` itself injects the web-app manifest and icon links, `brand.js` and
  `gameart.css` into the page (`web/hubnet.js:12-52`).
- **What Party has already classed** (`party:docs/design/NATIVE-GAMES.md:86-87`, `:90`):
  reconnect with a fresh ticket and the server-clock offset are pattern donors; `wc-*` identity,
  manifest and icon injection and the hub's toasts and chrome are not carried;
  `avrana-integration.js` is legacy compatibility replaced by the ADR 0013 seam; `brag.js` and
  `brand.js` belong to the legacy hub runtime. A native Spades therefore brings its own
  announce/toast, celebration (or none), avatar rendering (the Party's 32 bundled Gaze avatars,
  `docs/ASSETS.md:5-16`) and share card (or drops it).
- **Game-owned and staying in the game.** Card faces and suits drawn as text in CSS
  (`spades.js:79-89`); seat plates with a turn ring (`:166-214`); trick area and last-trick flash
  (`:216-235`); the hand fan fitted to the viewport (`:237-282`); the bid sheet with a two-tap nil
  (`:284-311`); score chips (`:313-324`); the hand scorecard (`:332-382`); the game-over card
  (`:384-401`); eight synthesized sounds, no audio file, muted state in `wc-muted`
  (`:15-47`, `:558-566`).
- **Legal-move display.** The client carries its own copy of the legal-play rule to dim illegal
  cards (`spades.js:68-77`, `:247-266`); the server validates every action again and names the
  reason ("Follow suit", "Spades aren't broken yet", "Not your turn", "Not in your hand",
  "Bid 1-13 or nil") (`games/spades/game.py:167-200`).

Provenance and licence:

| Item | Fact |
|---|---|
| Code | MIT. A fork of LAN Games by BEACNpool; modifications under the same terms (`NOTICE.md:3-14`, `LICENSE:1-3`). `games/spades` imports no third-party package. |
| Fonts | Sora and JetBrains Mono, SIL OFL 1.1, bundled in `web/fonts` (`NOTICE.md:21-27`). |
| Art | None in `games/spades/`. Cards are typographic. The library scene is a first-party inline spade shape (`web/gameart.js:108-110`), and `docs/ASSETS.md` has no Spades row. Party exported that scene as `lan:spades` and removed it with the grant in AVR-259 (Party commit `a5e122f`; `party:contracts/artwork.json:3-8` lists three games today). |
| Names and text | Bot names VEGA, ONYX, JINX, NOVA (`game.py:26`) and all on-screen copy are the fork's own. `NOTICE.md:33-36` says Avrana games use their own names, text and assets, so rules text is written fresh (S8). |

Proposal: draw the table from the game's own code and tokens, take Party's primitives for
identity, avatars and navigation, and let the legal-play list come from the server so the client
copy of the rule can go (the server already computes it, `game.py:195`).

## 6. Bot behaviour

Facts:

- **Two tiers, one factory.** `make_bot(difficulty, rng)` returns `RookieBot` or `StandardBot` and
  raises `ValueError` for any other name (`games/spades/bots.py:74-82`).
  - `RookieBot` plays a uniformly random legal card and bids the number of spades of queen or
    higher plus off-suit aces, between 1 and 4 (`bots.py:108-119`).
  - `StandardBot` estimates near-certain tricks (each ace, king or queen of spades 1, spade
    length beyond three 1 each, an off-suit ace 1, king 0.5, protected queen 0.25;
    `bots.py:141-158`), bids that rounded half up between 1 and 13, and bids nil when the hand
    has no ace, at most one king, at most two spades all below the queen, and an estimate of 1.0
    or less (`bots.py:127-139`).
  - Its play: duck as high as possible on its own nil (`:251-258`); cover a partner's nil that
    has not played, and overtake it cheaply when it is about to win (`:169-175`, `:260-268`);
    otherwise lead aces, then a boss trump when spades are broken and the team needs tricks, then
    kings, then low off-suit cards (`:193-212`); follow low when the partner is winning and
    cannot be topped, otherwise win with the cheapest winning card, preferring one no later
    opponent can top (`:214-235`); when void, trump only
    with the lowest winning spade and only if the team needs tricks and the partner is not
    winning, else discard low off-suit (`:237-249`). Card tracking is shallow by design
    (`_is_boss`, `:45-54`).
- **Own hand only.** A bot is handed its own hand and public facts (`_bot_view`,
  `games/spades/game.py:140-151`); `bots.py` normalizes it, string keys included
  (`games/spades/bots.py:57-71`).
- **Deterministic and legal.** All randomness comes from the injected `random.Random`, there is no
  IO and no clock (`bots.py:13-16`); the session passes its own `rng` (`game.py:87`, `:91`). A
  choice outside `legal_plays` becomes the lowest legal card (`bots.py:94-102`), and the session
  checks again before it plays (`game.py:289-293`).
- **Seating and names.** Empty seats get bots named BOT VEGA, ONYX, JINX, NOVA by seat index
  (`game.py:26`, `:81-87`). Each is a `Player` with `is_bot` and a `bot:`-prefixed token
  (`core/session.py:265-276`) and shows as `bot: true` in `players` (`:100-104`). The bot tier
  setting applies to those seats only. The autopilot that plays timeouts and absent humans is
  always a `StandardBot` (`game.py:91`, `:284`; pinned).
- **Pacing.** A bot or absent seat acts 0.9 to 1.8 s after its turn starts, plus 0.4 s when
  bidding (`game.py:296-305`); the turn clock restarts on every bid and card (`:132-133`,
  `:185`, `:222`); when it runs out, a bot seat's own bot plays for it and the autopilot plays for a
  human seat (`:265-294`).
- **Party.** A bot has no participant id, so it is dropped from standings
  (`core/net.py:317-318`).
- **Tests.** `tests/test_bots.py` has 19 pure tests: fuzzed full games and mid-trick states
  where a bot may only ever choose a legal card (`:114-143`), bid and play heuristics and the
  safety net (`:145-262`), the factory and view normalization (`:263-285`) and seeded
  determinism (`:287-310`).

Proposal: `bots.py` needs no change to move; what is open is policy (S1, S4, S5), not code.

## 7. Private-hand projection

Facts:

- **One projection.** `game_state(viewer_token)` (`games/spades/game.py:336-375`) finds the
  viewer's seat from the token (`:353`, `_seat_of` `:126-130`) and returns that seat's sorted
  hand under `hand` (`:359`), otherwise `None`. Every seat's summary is public and carries
  `seat`, `pid`, `team`, `bid`, `tricks`, `cards_left` and `auto` (`:344-352`): never a card or a
  token. The trick on the table, the last completed trick and both scores are public
  (`:361-370`).
- **Who gets what.** A seated human gets their own hand. A benched human (a fifth player), an
  unknown token, an anonymous watcher and a Party spectator get `hand: None` and `my_seat: None`
  (`core/net.py:109-120`; a Party spectator's view is the default `game_state_spectator`, the
  public view, `core/session.py:170-173`). The envelope adds `players` (public fields only,
  `core/session.py:100-104`), `you`, `settings`, `party_round` and `party_host`
  (`core/session.py:469-492`). `fx` events carry only what is already public: a bid, a played
  card, a trick winner (`games/spades/game.py:177`, `:207`, `:216`).
- **Existing coverage.** `tests/test_spades.py:233-247` checks hand privacy in bidding only. A
  scratch mutation that sends the partner's hand while playing passed all 38 existing tests
  (mutation P01 in section 10).
- **New coverage.** `tests/test_spades_session_pins.py:210-288` walks bidding, every card of a
  hand, the hand recap, the next deal and `game_end` for every seat, a benched human, an unknown
  token, an anonymous watcher and a Party spectator, with humans only and with bots. For each view
  and phase it asserts the exact key sets, that only the viewer's own cards appear, that no other
  seat's card appears anywhere in the serialized state, that no player token appears, and that the
  rest of the view is identical for every viewer.
- **Where the rule is duplicated.** The legal-play rule exists in `rules.py` and again in
  `spades.js:68-77`. See section 5.

What a native build must keep: the per-viewer projection with a public spectator view, the
every-phase leak test, and public-only `fx`. Whether Party spectators should see more than the
public view (BLUFF shows them every hand, `party:docs/adr/0010-party-pregame.md:49-54`) is S11.

## 8. Team and scoring semantics

Facts, from `rules.py` unless another file is named:

- **Seats and teams.** Four seats 0 to 3 clockwise; team is `seat % 2`, so seats 0 and 2 play
  seats 1 and 3; the partner of `s` is `(s + 2) % 4` (`rules.py:5-6`; `game.py:13`, `:145`).
  Seats fill in join order (a Party: roster order): four humans take seats 0 to 3; three humans
  take 0, 1, 2 and a bot sits at 3; two humans sit at 0 and 2 (partners) or 0 and 1 (opponents)
  by the `seating` setting, bots in the rest (`game.py:72-87`; layouts checked by running them).
- **Deal and turn order.** The dealer starts at a random seat (`game.py:93`) and moves one seat at
  the start of every hand, the first included (`:107`); the deck is shuffled with the session's
  `rng` and dealt 13 each (`:108-110`); bidding and the first lead start left of the dealer (`:118`,
  `:181`); a trick winner leads next (`:214`).
- **Bids.** An integer 1 to 13 or `"nil"` (`game.py:171-174`). A team's bid is the sum of its
  numeric bids. There is no blind nil and no minimum team bid.
- **Play.** Follow the led suit if able; spades cannot be led until a spade has been played
  (`game.py:204-205`) unless the hand is all spades (`rules.py:32-47`); the highest spade wins,
  else the highest card of the led suit (`:50-56`).
- **Hand score** (`rules.py:59-106`). Per team: tricks are both partners' tricks. Contract made
  (tricks at least the team bid): +10 per bid, and each trick over the bid is 1 point and 1 bag.
  Set: -10 per bid, no new bags, carried bags kept. Each nil bidder: +`nil_bonus` for zero tricks,
  else -`nil_penalty` (100 and 100 by default). A team with no numeric bid banks every trick it
  took as a bag. Every 10 accumulated bags cost 100 and are removed, repeatedly if needed.
  Bags carry from hand to hand (`game.py:231`, `:236`).
- **Match.** After the 14 s recap the match ends when at least one team is at or above the target
  and the scores differ; if both are over, the higher score wins, not the first across the line;
  an equal score plays another hand (`game.py:249-261`, `:265-268`). Targets are 200, 300, 400 or
  500, default 500 (`:33`, `:50`). There is no losing threshold and no cap on hands.
- **Not in the code:** blind nil, a minimum team bid, a bonus for large bids, a negative-score
  loss, a hand limit.

The rules are pinned by `tests/test_spades_rules.py` (functions) and the match pins in
`tests/test_spades_session_pins.py:85-208`. Behaviours a reimplementation must choose to keep or
change on purpose (S13), each pinned today:

| Behaviour | Where | Pinned by |
|---|---|---|
| A set team keeps its carried bags and gains none | `rules.py:88`, `:94-95` | `test_score_hand_a_set_team_loses_ten_per_bid_trick_and_keeps_its_bags` |
| A failed nil still counts its tricks for the team's contract | `rules.py:78`, `:83-85` | `test_score_hand_failed_nil_still_counts_its_tricks_toward_the_team` |
| A team with no numeric bid banks every trick as a bag, and reports `made` true | `rules.py:87`, `:96-98` | `test_score_hand_a_team_with_no_numeric_bid_banks_every_trick_as_a_bag` |
| Several bag penalties can land in one hand | `rules.py:101-103` | `test_score_hand_charges_one_penalty_per_ten_bags_in_a_single_hand` |
| The nil points are parameters of `score_hand` and session defaults but cannot be set by a player; the page prints "+-100" as fixed text | `game.py:37-38`, `:47-61`; `index.html:109`; `spades.js:310` | `test_score_hand_nil_bonus_and_penalty_are_parameters`, `test_default_settings_and_what_validate_settings_accepts` |
| Both teams over the target: the higher score wins; a tie plays on | `game.py:253` | `test_when_both_teams_are_over_the_target_the_higher_score_wins_not_the_first_over`, `test_a_tie_at_or_over_the_target_plays_another_hand` |

One client string disagrees with the server: the lobby note says "teams by ready order"
(`spades.js:141`), but the server orders players by join time (`core/session.py:432-433`), the
order the lobby lists them in (`:481-482`). Seat numbers shown to players are one-based
(`game.py:323-324`), so the "(1&3)" in the settings comment (`game.py:34`) means seat indexes 0
and 2 (`:77-78`).

## 9. Result shape

What Spades produces today:

- When the match ends it stores `{"winner_team": 0 or 1, "scores": {"0": n, "1": n}, "hands": n}`
  in `g["result"]` and emits `game_over` (`games/spades/game.py:249-258`). Each hand ends with
  `hand_result = {"teams": {"0": {delta, bags, made, bid, tricks, nil: [{seat, ok, delta}]},
  "1": {...}}, "bids": {seat: bid}, "tricks": {seat: n}}` (`:237-244`). Both ride in the
  projection to every viewer (`:372-373`).
- It never sets an outcome and defines no `game_result()`, so `core/net.py` never reports
  `ended` for it (`core/net.py:284-301`; `core/session.py:193-217`). An abandon (every human gone)
  returns the room to the lobby and also reports nothing (`core/session.py:331-337`). All
  pinned: `test_a_party_seated_game_reaches_game_end_with_no_outcome_and_no_result_to_report`,
  `test_everyone_leaving_returns_to_the_lobby_with_no_outcome_to_report`.

What the Party accepts (`party:docs/adr/0015-game-result-envelope.md`, reference code
`core/party_result.py`):

- `schema`, `game{id, build, content?}`, `mode` (`competitive` or `cooperative`), `standings`,
  `data_schema` with `data` (`core/party_result.py:100-167`; `ADR 0015:39-76`).
- `standings` has one entry for every **player** of the session and nobody else: `participant`,
  `standing` (`won`, `lost`, `draw`), optional `rank` for everyone or no one, ties sharing a rank
  (`core/party_result.py:127-151`; `ADR 0015:62`, `ADR 0015:71`). A result that names four of five
  players is refused as `incomplete` (`core/party_result.py:148-149`; measured).
- `data` is game-owned: at most 1024 bytes canonical, 4 containers deep, strings of 200 characters
  or fewer; the whole result at most 2048 bytes (`core/party_result.py:38-42`; `ADR 0015:73-76`).
  "There is deliberately no score, team, round or achievement field" (`ADR 0015:82-84`); teams are
  on the deferred list (`ADR 0015:173-175`).
- An `abandoned` end carries no result (a result sent with it is refused `not_completed`)
  (`ADR 0015:94-100`). A result that would be refused is left out and the session still ends
  (`core/net.py:328-332`; `ADR 0015:86-105`).
- Party records the result in memory only; what phones are shown is unchanged
  (`ADR 0015:125-127`). What is kept and shown is AVR-71's.

Proposal (a mapping, not a decision):

| Part | Value |
|---|---|
| `mode` | `competitive` |
| `standings` | each human: `won` on the winning team, `lost` otherwise; no `draw`, because a tie plays on (`game.py:253`); bots are not roster members and are dropped (`core/net.py:317-318`) |
| `rank` | 1 for the winners, 2 for the losers (all or none; ties share) |
| `data_schema`, `data` | `spades.result/v1`; `{"winner_team", "scores": {"0", "1"}, "hands", "bots": <count>, "teams": {<participant>: 0 or 1}}`, the same facts as `g["result"]` plus the partner map the envelope cannot carry, public facts only |
| `content` | the ruleset id if rules content is versioned (S8) |

Measured with `core/party_result.build`: four humans give a 794-byte result with 269 bytes of
`data`; three humans and a bot 655 and 220; two humans and two bots 517 and 171 (limits 2048 and
1024). BLUFF's precedent for bots in `data` is `bots` and `winner: "bot" | "player"`
(`games/bluff/game.py:543-564`; `ADR 0015:152-155`).

The outcome would be `completed` when a team wins. An `abandoned` outcome from inside the game
conflicts with the proposed rule that no game ends a Party round by itself
(`party:docs/design/GAME-UX-CONTRACT.md:866-868`); the Host's End is reported by the Party as
`ended_by_host` (`ADR 0015:100`).

## 10. Tests: what survives a migration

Four Spades files hold 73 tests at `a448972` plus this change: 38 existing and 35 new.

| Suite | Tests | Imports | Moves with the rules? |
|---|---:|---|---|
| `tests/test_bots.py` | 19 | `games.spades.rules`, `games.spades.bots` (`:11-12`) | Yes, as it is. Its determinism tests assume the same `random.Random` call sequence (`games/spades/bots.py:13-16`). |
| `tests/test_spades.py` | 19 | `rules`, `SpadesSession` (`:7-8`) | 6 yes: `test_deck` to `test_score_hand_nil_and_bagout` (`:13-82`). 13 no: they drive the lobby, `s.g`, `_do_bid` and `_do_play` (`:84-266`). |
| `tests/test_spades_rules.py` (new, 169 lines) | 17 | only `games.spades.rules`; its first test fails if anything else of the project is imported (`:24-35`) | Yes: change the one import line. Every expected value is a literal worked out by hand, never a call back into `rules`. |
| `tests/test_spades_session_pins.py` (new, 397 lines) | 18 | `rules`, `bots`, `SpadesSession` | No. 13 pin behaviour to re-express against a native session: the match (`:85-141`), the hand (`:143-208`), the private view (`:269-288`), seating, settings and pacing (`:291-344`). 5 pin today's gaps on purpose (`:347-397`). |

The 5 gap pins say what is true now and are meant to flip with the decision named beside them;
each is changed in the same commit as the behaviour:

| Pin (`tests/test_spades_session_pins.py`) | True today | Flips with |
|---|---|---|
| `test_a_party_seated_game_reaches_game_end_with_no_outcome_and_no_result_to_report` | no outcome, no result, no deadline at `game_end` | section 9 and S5 |
| `test_party_settings_and_lobby_verbs_are_refused_so_the_fork_defaults_stand` | settings, ready and start are refused in a Party round, including in the dead lobby after `again` | S3, S7 |
| `test_one_human_cannot_start_a_table` | the lobby refuses one human; a one-seat Party round raises `ValueError` | S1 |
| `test_a_fifth_party_player_has_no_seat_hand_or_place_in_the_participants` | the fifth player is benched with no hand | S1, S7 |
| `test_everyone_leaving_returns_to_the_lobby_with_no_outcome_to_report` | the room becomes a lobby, nothing is reported | S4 |

Evidence that the new tests bite. Each rules case was checked against a scratch mutation of the
rule it names, on a throwaway copy of the repository outside the worktree; the worktree itself was
never mutated. In all, 96 single-edit mutations were applied one at a time and the four suites run
for each: 95 to source files (38 in `games/spades/rules.py`, 52 in `games/spades/game.py`, 5 in
`core/session.py`) and one to the rules test's own import rule. All 96 were killed. 67 are killed
by the new tests alone, 29 by both old and new, none by the old alone, and each of the 35 new tests
fails under at least one. For example, sending the partner's hand while playing, accepting the
first team over the target, and not wrapping the dealer rotation are caught by the new tests; only
the last was already caught by an old one. The harness is not committed; the per-mutation table is
in the AVR-312 pull request description. Baseline: 73 passed, Python 3.12.3.

Run them with:

```
python -m pytest -q tests/test_spades.py tests/test_bots.py tests/test_spades_rules.py tests/test_spades_session_pins.py
```

Not covered by any Python test, and not run here: the page itself and the shared client
(`tests/playtest_spades.mjs` drives the retired hub in a browser). A native build needs its own
browser proof (the Checkers D10 analogue, section 13.3).

## 11. What an SDK primitive must express that Checkers does not

Checkers here means the approved decisions D1 to D10 and the plan on Linear AVR-238 (2026-10-06
and 2026-10-07); its implementation is in progress and was not read. These are observations about
what Spades needs. They do not propose shared code: Party's rule is that a pattern is promoted
only on repeated evidence (`party:docs/design/NATIVE-GAMES.md:112-114`; ADR 0014 decision 12,
`party:docs/adr/0014-native-games-isolated-lan-games-retired.md:96-99`).

| # | Needs | Checkers (per the decisions) | Spades (fact) |
|---|---|---|---|
| 1 | Teams | none; roster order decides sides (D7) | partnership by `seat % 2` (`rules.py:5-6`); the contract has no teams field (`party:avrana/contracts/game.py:60-62`), the envelope has no team field and defers teams (`ADR 0015:82-84`, `ADR 0015:173-175`); ADR 0014 decision 7 expects teams in the manifest "over time" (`ADR 0014:72-75`) |
| 2 | Seats beyond two, filled by humans and by players who are not in the roster | two humans, no bot (D6; Linear AVR-238, 2026-10-04, decision 3) | two to four humans and up to two bots, seat layout by head count (`game.py:72-87`); bots have no participant id and are dropped from standings (`core/net.py:317-318`) |
| 3 | Hidden information with several audiences | none; the board is public | own hand, a benched human, an unknown token, an anonymous watcher, a Party spectator (`game.py:336-375`; `core/session.py:170-173`); an every-phase leak test is needed (`tests/test_spades_session_pins.py:269-288`) |
| 4 | A per-seat clock and an absence policy | no timer, no autopilot; a disconnected turn waits; the Host may end (D6) | 30 s clock, 10 to 60 (`game.py:59`), autopilot for stalled or absent seats, at once on disconnect (`:135-139`, `:265-305`, `:318-332`) |
| 5 | A multi-hand match with carried state | one game | dealer rotation, bags and scores carried, a 14 s recap, a tie plays on (`game.py:104-122`, `:227-268`) |
| 6 | Settings with an owner | none declared | four settings in the fork, refused in a Party round (`game.py:32-61`; `core/session.py:391-397`); host settings are a deferred platform question (`party:docs/design/GAME-UX-CONTRACT.md:352-379`) |
| 7 | Seeded randomness | none; roster order decides | dealing and bot choices come from one injected `random.Random`; the tests rely on it (`game.py:41-42`, `:108-110`; `bots.py:13-16`) |
| 8 | A result with team meaning | won, lost or draw per player | won or lost per human by team, scores and the partner map in `data` (section 9) |
| 9 | Reasons for refused actions, with a legal-move list | forced captures; reasons not specified | five server reasons (`game.py:167-200`); the client rebuilds the legal list itself and gives a dimmed card no reason (`spades.js:68-77`, `:269`); a reasons catalogue exists only as a draft (`party:docs/design/GAME-UX-CONTRACT.md:514-517`) |
| 10 | Rule numbers pinned to code | real onboarding content (D8) | nil points and bags appear as fixed text (`index.html:109`; `spades.js:310`); BLUFF pins its briefing facts to the rules (`tests/test_bluff_briefing.py:127-132`) |
| 11 | A long session across a process restart | one game; not decided | a match spans many hands and is held only in memory (`game.py:43`) |
| 12 | A seat that changes hands between a human and an autopilot mid-hand | no autopilot | an `auto` flag per seat in the projection, drop and back toasts (`game.py:135-139`, `:318-332`, `:351`) |

## 12. Onboarding requirements

Facts:

- Spades has no rules text at all: no `onboarding.json`, no README, no "how to play" control.
  The page's only "rules" word is the settings heading "TABLE RULES" (`games/spades/web/index.html:52`);
  the one-line catalog description is the only prose (`provider/catalog.json:439-440`).
- Party shows a game's briefing from `onboarding.json` served beside its entry page. The shell
  requires `schema: "avrana.onboarding/v0"` and a `rules` array; without a file it falls back to
  the catalog summary as both premise and rules
  (`party:docs/design/GAME-UX-CONTRACT.md:434-436`, `:451-453`). The v0 shape is `schema`, `game`,
  `title`, `premise`, `ack {key, version}`, `facts`, `rules [{title, points}]`, with `{name}`
  placeholders filled from `facts` and plain text only (`:436-453`). A v1 draft (sections, an
  example, a reasons catalogue, declared settings) exists on paper and no code reads it
  (`:455-523`).
- Rules must stay reachable during play (Rule 4.15); no platform overlay exists yet and BLUFF and
  EXPO draw their own (`party:docs/design/GAME-UX-CONTRACT.md:403-415`). The Spades page has no
  such control.
- The Game Contract's `accessibility` block takes true, false or "unknown" per key
  (`party:avrana/contracts/game.py:305-311`). The Spades page has no aria attributes in its
  script and one in its markup (`index.html:17`), so nothing could be claimed beyond "unknown"
  without an audit. Not assessed here.

What the content must cover (derived from the facts above; a proposal for the content, not a
decision about its form):

1. Partners sit opposite each other; the team's bid is the sum of both partners' bids.
2. Bidding: 1 to 13 or nil, in seat order, left of the dealer first.
3. Spades are trump; follow suit when able; spades cannot be led until one has been played,
   unless the hand is all spades.
4. Scoring numbers, each a `fact` rather than prose: made contract +10 per bid, set -10 per bid,
   each overtrick 1 point and 1 bag, ten bags cost 100, nil +100 or -100, the target. A nil
   bidder's tricks still count for the team, and a team with no numeric bid banks every trick as
   a bag (S13).
5. The match: how many hands it takes, that a tie plays on, and that both teams over the target
   means the higher score wins.
6. What a bot or the autopilot does for a seat, and when (S4).
7. The reasons for refused actions, as sentences a player sees where the action was refused.

Each number should be pinned to the rules by a test, as BLUFF's briefing facts are
(`tests/test_bluff_briefing.py:127-132`), reading `rules.BAG_LIMIT`, `rules.BAG_PENALTY` and the
session defaults (`rules.py:15-16`; `game.py:32-39`). The text is written fresh
(`NOTICE.md:33-36`, S9).

## 13. Owner decisions before a build

These are for the owner, not for this issue (Linear AVR-312 has no Open Decisions). S1 to S9
are the nine the issue names; S10 to S13 are the four this reading added. Each has the facts
that bear on it, the options, and a proposal that is only a proposal. D3, D5 and D10 depend on
evidence that Checkers (AVR-238) has not produced yet.

### 13.1 The nine decisions the issue names

**S1. `players.min` and `players.max`**

- Facts. The fork's own lobby needs 2 ready humans (`games/spades/game.py:30`;
  `core/session.py:406-408`); up to 8 may join and the first 4 are seated (`game.py:31`,
  `:66-71`). The registry and catalog say 2 to 4 plus bots (`games/registry.py:233`, `:238`;
  `provider/catalog.json:441-442`, `:448`) and the page says "TWO HUMANS MINIMUM"
  (`index.html:23`). One human in a Party-seated round never meets the lobby's minimum and
  raises `ValueError` in `game_start` (`game.py:77-78`; pinned). Party Core enforces the minimum only in
  the pregame (`party:avrana/party/core.py:439-442`); without a pregame it opens the session with
  whoever is here, in join order, the first `max_players` as players and the rest as spectators,
  with no minimum check (`:415-418`). A `ValueError` out of `tick` is caught, logged and re-armed
  2 s later (`core/net.py:158-169`), so a one-seat round would retry and log every 2 s (read from
  the code, not exercised end to end). The contract takes `players.min` and `players.max` as
  integers from 1 to 32 (`party:avrana/contracts/game.py:163-169`) and Party Core derives its
  limits from them (`party:avrana/contracts/party_config.py:6-13`). Hearts and Euchre are
  registered for solo play (`games/registry.py:247`, `:262`); Spades is not.
- Options. (a) 2 to 4, bots fill empty seats, as today. (b) exactly 4 humans, no bots.
  (c) 1 to 4, a solo player against bots (a new seating rule).
- Proposal. (a) with a maximum of 4, so a fifth phone watches (S7). (b) would remove S5 and most
  of S4 if the owner would rather have no bots at all.
- Checkers analogue. "Two human players; no bot" (Linear AVR-238, 2026-10-04, decision 3) fixes
  Checkers at exactly two. Spades is the first game where the minimum, the maximum and bots
  interact.

**S2. Partner order**

- Facts. Seats fill in join order, and in a Party in roster order (players in join order, then
  spectators: `party:avrana/party/core.py:162-163`, `:466-467`); team is `seat % 2`, so partners
  are the 1st and 3rd and the 2nd and 4th (`games/spades/game.py:73-76`). With three humans the
  bot at seat 3 partners the second human; with two, the `seating` setting makes them partners
  (seats 0 and 2) or opponents (0 and 1), default partners (`game.py:34`, `:77-80`; layouts
  checked by running them). Nobody chooses a partner: no lobby control does it
  (`index.html:35-72`). The first dealer is random (`game.py:93`), so the first bidder is not the
  first-listed player. The fork announces the teams in a toast (`game.py:99-100`).
- Options. (a) roster order as it is. (b) the Host or the players choose partners in the briefing
  (a Party-drawn control, or a game-side step like EXPO's). (c) a seeded random draw. (d) for two
  humans, fix partners or opponents (the `seating` setting goes away if settings do, S3).
- Proposal. (a), with the teams stated before the first deal, and partners fixed for two humans.
  It needs nothing new from Party.
- Checkers analogue. D7: roster order decides sides and first mover. Here it decides seats and
  so partners; it does not decide who bids first.

**S3. Settings**

- Facts. Four values are settable in the fork: `target` 200, 300, 400 or 500; `seating`;
  `difficulty`; `turn_seconds` 10 to 60 (`game.py:32-61`). `nil_bonus` and `nil_penalty` are
  defaults that `validate_settings` never accepts (`:37-38`, `:47-61`; pinned). In a Party round
  the settings verb is refused, so the defaults (500, partners, standard, 30 s) always apply
  (`core/session.py:391-397`; `party:docs/adr/0010-party-pregame.md:45-48`). The retired hub
  labels a Spades game "25-45 min" (`web/hub.js:83`). The session protocol carries no settings
  to a game, and host settings in the briefing are a deferred platform question
  (`party:docs/design/GAME-UX-CONTRACT.md:364-379`, `:1187`); EXPO's setup stays inside EXPO "for
  now" (`:352-362`). The page prints "+-100" for nil as fixed text (`index.html:109`;
  `spades.js:310`).
- Options. (a) no settings in the first native build: one rule set, chosen deliberately.
  (b) a game-side setup step before the first deal, confirmed by the Host (EXPO's pattern).
  (c) wait for the platform settings question.
- Proposal. (a). 500 points and a 30 s clock are the fork's defaults, not decisions; a shorter
  target is the main lever on the length of an evening.
- Checkers analogue. D6: fewer knobs (no draw offers, takebacks or timer).

**S4. Autopilot, pause and abandon**

- Facts. When the turn clock (default 30 s) runs out, the autopilot (always a StandardBot) plays for
  a human seat on turn and a bot seat's own bot plays for itself; a connected human gets the toast
  "ran out of time" (`game.py:265-294`). A human whose last socket closes is on autopilot at once
  (`_seat_is_auto`, `:135-139`) and plays after 0.9 to 1.8 s (+0.4 s bidding) (`:296-305`), with a
  toast (`:318-332`). When the last human leaves the base class returns the room to the lobby with
  "Game abandoned" and no outcome (`core/session.py:331-337`; pinned). There is no pause, no grace
  and no forfeit verb: the game handles only `bid` and `play` (`game.py:155-165`). BLUFF's model is
  five presence states (`games/bluff/game.py:818-827`), a table pause when every seated human is
  disconnected and an abandon after `EMPTY_TABLE_ABANDON`, 300 s (`:24-35`, `:89`); Party's design
  table proposes one presence grace at party level, a seat held "until the game ends" by default,
  and what "away" means left to the game (`party:docs/design/GAME-INTEGRATION.md:337`). Party rules:
  only the Host moves the Party (Rule 3.4, accepted); a game's own forfeit or sit-out must not move
  a page (Rule 3.4) and no game ends a Party round by itself (Rule 12.4), both proposed for every
  game; the Host may end a game unilaterally after a confirmation (Rule 12.3, accepted)
  (`party:docs/design/GAME-UX-CONTRACT.md:136-140`, `:854-868`).
- Options. (a) as the fork: a clock and an immediate autopilot. (b) autopilot only after a
  presence grace from the platform, a pause when every human is away, and End by the Host only.
  (c) no clock and no autopilot: the table waits for the absent seat, as Checkers does, and bots
  fill only seats that no human holds. Separately: does the clock exist at all, and is the
  autopilot the StandardBot (today, pinned) or something quieter.
- Proposal. (b), keeping the StandardBot as the autopilot. Nothing inside the game ends the
  round.
- Checkers analogue. D6, reopened: Checkers decided to have no clock, bot or autopilot and to
  let a disconnected turn wait. Spades has all three today.

**S5. Bots in result data**

- Facts. A bot is not a roster member: it has no participant id and is dropped from standings
  (`core/net.py:317-318`). A bot can be a human's partner and can decide the match. BLUFF puts the
  count of bots and whether a bot won in `data` (`games/bluff/game.py:557-564`; `ADR 0015:152-155`).
  The measured sizes are in section 9. Whether a game with bots should count in future history or
  stats is AVR-71's (`ADR 0015:165-171`).
- Options. (a) a bot count only. (b) the count plus the partner map (`teams`), so a recap can say
  who partnered whom. (c) nothing about bots.
- Proposal. (b), public facts only, no bot names.
- Checkers analogue. None: Checkers has no bots.

**S6. Transport**

- Facts. The fork speaks one WebSocket per game with a full per-viewer state after every
  mutation (`server.py:67-77`; `core/net.py:95-127`). One hand is 56 mutations (4 bids and 52
  cards); a viewer's state measured 1,755 to 2,060 bytes (mean 1,866), about 0.1 MB per viewer
  per hand. Server-initiated changes come from three clocks: the turn clock, the bot delays of
  0.9 to 2.2 s and the 14 s recap (`game.py:25`, `:133`, `:246`, `:301-303`), plus transient `fx`
  events beside the state. The game code itself does no IO (`core/session.py:19`). Checkers chose
  stdlib HTTP long-poll because it runs on system Python under a dynamic user with no virtual
  environment, and judged a WebSocket to need the Games venv readable by that user and an
  inherited-socket server path nobody has run (Linear AVR-238 plan, row D3).
- Options. (a) long-poll with versioned per-viewer state and an event cursor for `fx`. (b) a
  WebSocket, with the venv and inherited-socket work that implies. (c) decide after Checkers'
  real-systemd proof.
- Proposal. (c). The rules, bots and session are already transport-free, so either choice stays
  open.
- Checkers analogue. D3, reopened: four private views, a clock and bot pushes are what long-poll
  was not asked to carry.

**S7. Pregame**

- Facts. A game declares `extensions["net.avrana.party"].pregame` (BLUFF and EXPO set it true:
  `party:contracts/games/bluff.json:43-45`, `party:contracts/games/expo.json:39-41`); that is the
  only key the extension accepts today (`party:avrana/contracts/party_config.py:30`, `:49-51`).
  With a pregame the Party shows Play or Watch and the Host starts, and Party Core refuses unless
  the number of players is between min and max (`party:docs/adr/0010-party-pregame.md:19-28`;
  `party:avrana/party/core.py:439-442`). Without one there is no briefing and the Host's start
  goes straight to the game (`party:docs/design/GAME-UX-CONTRACT.md:103-105`), with the
  seating described in S1. The pregame is also where `onboarding.json` content and a first-play
  acknowledgement appear (S8). A game's own lobby is skipped either way
  (`core/session.py:379-402`).
- Options. (a) `pregame: true`. (b) `pregame: false`.
- Proposal. (a): it is the only path on which Party enforces `players.min`, and the way a fifth
  phone chooses to watch.
- Checkers analogue. D8 chose `pregame: false` for Checkers, which has exactly two players and
  nothing to configure.

**S8. Rules content**

- Facts. Section 12. Without a file the Party uses the catalog summary as the rules. BLUFF pins
  its briefing facts to the rules code (`tests/test_bluff_briefing.py:127-132`). The text must be
  the project's own (`NOTICE.md:33-36`).
- Options. (a) an `avrana.onboarding/v0` file, with every number a `fact` pinned by a test.
  (b) a Quick Start and Rules Guide, which needs the unbuilt v1 draft
  (`party:docs/design/GAME-UX-CONTRACT.md:381-399`, `:455-523`).
- Proposal. (a) first. Decide with it who writes and approves the text, and which rules the game
  states (S13).
- Checkers analogue. D8: real structured onboarding and rules content through the normal Avrana
  rules surface. It carries over unchanged.

**S9. Art provenance**

- Facts. Section 5: no art files; cards are typographic; the library scene is a first-party inline
  shape that Party stopped using in AVR-259; `docs/ASSETS.md` has no Spades row; sounds are
  synthesized. The artwork contract says a game without an entry shows a generic icon
  (`party:contracts/artwork.json:3`); its sources are `lan:<slug>` (a GameArt scene, "prototype
  era, not final logos") and `kenney:<icon>` (CC0) (`:3`). Rule 13.1 says no emoji is implicitly
  required as game art; Rule 13.2 (proposed) allows card suits as notation and wants a placeholder
  declared as one (`party:docs/design/GAME-UX-CONTRACT.md:872-880`). The title icon and favicon are the
  spade emoji (`games/registry.py:230`, `:235`; `index.html:12`).
- Options. (a) a generic icon now, cards stay typographic and are declared a placeholder.
  (b) reuse the first-party GameArt scene through the existing source kind. (c) human-made or
  licensed card and table art, with an author, source and licence row in `docs/ASSETS.md`.
- Proposal. (a) now and (c) later, as for Checkers.
- Checkers analogue. D9, unchanged.

### 13.2 Four more the issue did not list

**S10. Persistence across a process restart.** Fact: the match is memory only
(`games/spades/game.py:43`); EXPO's snapshot is standalone only and its Party tables are not saved
(`games/expo/game.py:93-109`); a native game gets a state directory of its own
(`party:docs/runbooks/provision-game.md:70-72`). Options: accept the loss, snapshot after each
hand, or snapshot after every action. Proposal: decide after the first native game has run on the
appliance, since a restart mid-match is a property of how the unit is restarted.

**S11. What Party spectators see.** Fact: the default spectator view is the public view, so no
hands (`core/session.py:170-173`; pinned). BLUFF shows spectators every hand by choice
(`party:docs/adr/0010-party-pregame.md:49-54`) and records that a second device can then see
every hand (`ADR 0010:86-87`). Options: public only; every hand; one team's. Proposal: public only, the
fork's behaviour, with the every-phase test as the guard.

**S12. Teams: a platform field or game-owned data.** Fact: the contract, the envelope and the
`net.avrana.party` extension accept no team data (`party:avrana/contracts/game.py:60-62`;
`ADR 0015:82-84`; `party:avrana/contracts/party_config.py:30`); ADR 0014 decision 7 expects the
manifest to carry teams "over time" (`ADR 0014:72-75`) and ADR 0015 defers them
(`ADR 0015:173-175`). Options: keep teams in `spades.result/v1` and in the game's own text, or add a
contract key and an envelope field. Proposal: game-owned until a second team game needs it; Euchre
is written in Spades' mold (`games/euchre/game.py:3`), so the evidence may come from the Classics.

**S13. Rules parity.** Fact: section 8 lists six behaviours that are pinned today. Options:
keep each and say so in the rules text; change one on purpose, with its pin changed in the same
commit. Proposal: keep all six for the first native build, so the pins in
`tests/test_spades_rules.py` stay the contract, and write each into the rules text (S8).

### 13.3 Checkers D1 to D10, and what each means for Spades

The decisions are the owner's of 2026-10-07 on Linear AVR-238, "approved as recommended".

| Checkers decision | For Spades | Status |
|---|---|---|
| D1. Runs on the isolated game origin and uses the Party bridge only. The guardrail: "a game must forever be the top-level browser document" must not enter the SDK or contract | The same trust tier. The fork's page carries a bridge path (`web/avrana-integration.js:56-117`) beside the legacy same-origin one, which a native page must not use | carries over |
| D2. A small generic Party issue first (AVR-303); no game-specific Party Core behaviour | The same prerequisite; nothing Spades-specific is asked of Party Core | carries over, same blocker |
| D3. Stdlib HTTP long-poll; a game decision, not an SDK mandate | S6 | reopens |
| D4. The existing pinned Party protocol and result modules, recorded as pre-SDK debt | The same two files; the result content is new (section 9, S5, S12) | carries over, content new |
| D5. Game-side helpers stay local; not promoted on the stand-in and Checkers alone | Spades is the second independent consumer: copy, share or write its own is a Party decision on evidence (`party:docs/design/NATIVE-GAMES.md:112-114`) | reopens as evidence |
| D6. Forced captures, resign; no draw offers, takebacks, timer, bot or autopilot; a disconnected turn waits; the Host may end | S4, S1, S5: Spades has a clock, bots and an autopilot and no forfeit verb | reopens |
| D7. Roster order decides sides and first mover | S2: roster order decides seats and so partners | carries over, one step further |
| D8. `pregame: false`, real onboarding and rules content | S7 (pregame) and S8 (content) | content carries over, pregame reopens |
| D9. Generic artwork now; licensed or human artwork later | S9 | carries over |
| D10. Extend Party's provider and browser harness with a native-process mode; no Games-side harness | The same mode, with four phone contexts for the private-hand, spectator and reconnect proof | carries over, larger scenario |

## 14. Classics

Fact: AVR-155 (Backlog) names Classics as a candidate tier, "a quieter Classics collection rather
than hero tiles", lists Spades among the familiar games, and asks that catalog metadata can
represent the tiers and that Classics not compete visually with showcase games (Linear AVR-155).
None of the existing places can carry that tag. The registry's `category` and `hidden` fields
(`games/registry.py:231`, `:241`) belong to the retired hub. An appliance `collections[]` entry
is a hub that is not a game, with its own entry path and required runtimes
(`party:contracts/README.md:136`; `party:avrana/contracts/appliance.py:124-135`). The grant's
`tier` is a trust tier, `builtin`, `trusted` or `community`
(`party:avrana/contracts/appliance.py:21`, `:117-118`). `party_session.GAMES` is a list of servers
that implement the game side, a capability and not a catalog (`core/party_session.py:51-53`).

Proposal: a Classics shelf is a tag on native games, carried by the Game Contract through an
extension (the contract already has reverse-DNS `extensions`, `party:avrana/contracts/game.py:313-319`,
and the Party validator that reads the `net.avrana.party` one would need a new key,
`party:avrana/contracts/party_config.py:30`), plus a grouping in the Library. It is never the LAN
hub, which ADR 0014 retires as a runtime, and not `collections[]` or `party_session.GAMES`.
Whether Spades is Classics or Featured is AVR-155's decision; nothing here pre-empts it.

## 15. Limits of this packet

- Read, not run: everything on the Party side (source at `75b5062`), the routes of AVR-259
  (in source; Party's own text says "not deployed", `party:docs/design/NATIVE-GAMES.md:95`), and
  the browser client. No phone, browser, Playwright suite or Pi was used.
- Checkers' implementation (AVR-238) was not read; the Checkers column in section 11 and the
  mapping in 13.3 come from its approved decisions and plan on Linear.
- Measured with scratch scripts that are not committed: the result sizes (section 9), the
  state-push sizes (S6), the seat layouts (S2) and the mutation table (section 10).
- The five-player and one-human behaviours are pinned for the session; what Party Core then does
  with them end to end was not exercised.
- Linear text was read on 2026-10-07 and can change.
