# Checkers as the first native game process: findings from the Games half (AVR-238)

Observed 2026-10-07 at avrana-party-games `c44ee40` (branch `feat/avr-238-checkers`, draft PR #54,
started from `a448972`) and avrana-party `75b5062` (`main` after AVR-236). Historical evidence, not
a plan and not a decision record: it says what building Checkers as a native game process needed
from the platform, so that AVR-37 and AVR-38 can start from facts. AVR-37 reads "Drafting starts
after Checkers and its findings note exist, not before" (Linear AVR-37, 2026-10-07).

This is the Games half's edition of the dated findings note that AVR-238's last acceptance
criterion asks for. The Party half (game contract, grant, catalog entry, `provision-game`, the
harness's native-process mode, the two-phone browser test, a real systemd run) waits for
avrana-party#87 and has not happened. Section 8 says what that leaves unproven, and the Party half
adds its own dated note beside this one. Nothing here changes an existing findings or archive file.
Nothing here drafts or sketches `.avrgame` v0: sections 4 and 5 say what a package or SDK
primitive would have to express, in terms of what happened in one game, and stop there.

How to read it:

- `path:line` is this repository at `c44ee40` (`git show c44ee40:<path>` reproduces the line
  numbers). `party:path:line` is avrana-party at `75b5062`. `party#87:path:line` is the open pull
  request avrana-party#87 at its head `79e8911`, used only where the stand-in's change there is the
  evidence. `ADR 0016:248-251` is lines 248 to 251 of
  `party:docs/adr/0016-service-identities-and-local-trust-boundary.md`; ADRs 0006, 0011, 0013, 0014
  and 0015 are cited the same way from `party:docs/adr/`. `UX:N` is line N of
  `party:docs/design/GAME-UX-CONTRACT.md` and `NATIVE:N` of `party:docs/design/NATIVE-GAMES.md`.
  A bare `game.py:N` is the stand-in game's `party:avrana/games/standin/game.py:N`. "Linear AVR-N" is
  the issue text as read on 2026-10-07 and can change.
- A sentence under Facts was checked against source or by running it. "Probed" means a scratch
  script (not committed; section 10 gives the recipes) called the code.
- A Proposal is a labelled suggestion for the owner. No proposal here is a decision, none changes an
  Open Decision, and none edits an ADR.
- Nothing was run on the Pi, on a phone, in a browser or under systemd. Party was read, not run,
  except for the stand-in's request function, which was called in process (section 3.2).

## 1. Summary

- **What exists.** `checkers/` is a standard-library Python process (1,144 lines: `rules.py` 262,
  `session.py` 184, `server.py` 356, `party.py` 325, the rest 17) with a phone page (1,117 lines of
  HTML, CSS, JavaScript, JSON and one SVG) and 3,492 lines of tests. Party starts it as
  `python3 -m checkers` on an inherited Unix socket. It seats two players from the launch roster,
  referees the game and reports a signed `ended` carrying an `avrana.game-result/v1`. It has run
  against a fake Party in tests, and as a real process on a real Unix socket in Linux CI. No Party
  Core has run it.
- **The boundary was enough to build on.** The two vendored Party files (`core/party_protocol.py`,
  `core/party_result.py`) are used byte for byte, `GameSide` is unmodified, and the Games half needed
  no change in Party Core. A Checkers result is 354 to 358 bytes against the 2048-byte limit and the
  signed `ended` is 823 to 828 characters against 8192 (probed).
- **Where it was thin**, in the order a player meets it: Party's go-home `end` reaches a session the
  game already reported and `GameSide` refuses it (F3); after `ended` no ticket is admitted, so a
  phone that opens at the results has no board and cannot be told who won (F4); a page cannot tell a
  new session of its own game from the old one (F12); `ended` is not idempotent for the game (F5).
  Around the process: serving on the inherited descriptor (F1), idle stop (F7), build identity (F6).
- **What overlaps.** `checkers/party.py` wrote eleven things the stand-in game in avrana-party
  already has, two of them by importing Party's own modules where Checkers cannot (section 3). The
  fork's older `core/party_session.py` has most of them too: three copies, two of them native.
  Comparing them found two defects in the older ones (an empty proxy header passes the guard; a
  non-ASCII token raises `TypeError` in the stand-in). Neither is in Checkers and neither is touched
  here.
- **Decisions.** D1 to D10 held; none is reopened. D5's promised evidence is section 3, and D4's
  pre-SDK debt is F3 to F5. Five questions the build raises are new and open: D11 to D15 (section 7).
- **Unproven.** Everything that needs a real Party Core, a front door, systemd's address-family
  filter, a browser or a phone (section 8).

## 2. What the Party boundary needed from a native game

Facts, element by element. Where a cell says "refuses" or "never", it is a property of the code
cited, not of a run.

| Element | What Party does or says | What Checkers had to do |
|---|---|---|
| Start | The game is socket-activated on the first connection and is handed fd 3, its own key as a credential, `AVRANA_PARTY_KEYS`, `AVRANA_PARTY_SOCKET` and a state directory; `RestrictAddressFamilies=AF_UNIX`; `Restart=on-failure` (`party:deploy/games/avrana-game@.service:1-9,21-38`; ADR 0016:209-212, 248-251). ADR 0016 calls this "a field-test runtime convention, not an SDK" that "may change before `.avrgame`" (`:248-251`). The Party's browser origin arrives as `AVRANA_PARTY_ORIGIN` only with #87 (`party#87:avrana/games/standin/game.py:13-14,307-308`). | `main` takes fd 3 under systemd's `LISTEN_PID` rule, reads the key and the two paths, accepts the origin only if it is an origin, and exits 2 without what it needs (`checkers/server.py:339-356`; `checkers/party.py:15-22,130-149`). It opens no IP socket, resolves no name, writes nothing to disk and does not use the state directory. |
| `launch` | A signed message, 30 s, replay-guarded, with a roster of exactly `{participant, name, role}` (`core/party_protocol.py:283-294`). For a game without a pregame the roster is the members who are here, in join order: the first `max_players` are players and the rest spectators. `min_players` is not checked at a direct launch (`party:avrana/party/core.py:176,389-393,405-420`). | `GameSide.on_launch` replaces any earlier session (`core/party_protocol.py:433-437`). The first two players are seated white and black in roster order. Any other count is refused with a 409 and a sentence, and the session is reset so no ticket is admitted (`checkers/server.py:170-187`; `checkers/session.py:54-67`). Party records the sentence and Party Home shows it to the Host (`party:avrana/party/sessions.py:114-127`; `party:avrana/party/core.py:496-502,747`; `party:web/party/app.js:559-568`). |
| Tickets and seats | A ticket is minted only while Party's session is active, is single use and valid for 120 s, and reaches the page with a role and no session id (`party:avrana/party/core.py:686-706`; `party:web/party/lib/bridge.js:114-127`; `core/party_protocol.py:83,359-377`). A reload fetches a fresh ticket and the game derives the same `game_token` for the same participant (`core/party_protocol.py:274-279`). | `present` spends the ticket and returns the token (`core/party_protocol.py:446-456`). The seat comes from the roster, not from the ticket's role: a ticket that says player for someone the launch did not name only watches (`checkers/server.py:217-236`; `tests/test_checkers_process.py:366-371`). A token must have been handed out by this session and is compared as UTF-8 bytes in constant time (`checkers/server.py:205-211`). The `host` claim on a ticket (`party:avrana/party/sessions.py:154-163`) is not used: the Host's verbs go through the bridge and Party checks the Host at the action. |
| `ended` and the result | `ended` arrives on Party's internal Unix socket and is checked against its replay guard and the current session. It ends the session as `completed` or `abandoned` and answers `{ok, result: accepted or refused, reason}`. The end and the result are judged separately (`party:avrana/party/sessions.py:167-192`; `party:avrana/party/core.py:581-628`; ADR 0015:86-105). | When a move or a resignation ends the game the server builds the result with `result.build`, which applies Party's own check (`checkers/party.py:154-162`), calls `GameSide.ended`, which clears the session at once (`core/party_protocol.py:484-490`), and reports after releasing the lock, again after 1, 2 and 4 s while nobody answers or the answer is a 5xx (`checkers/server.py:299-336`; `checkers/party.py:183-218`). Standings are won, lost or draw for both players; `data` is `{ending, plies}` under `checkers.result/v1`. A result Party would refuse is left out and the session still ends (`checkers/server.py:303-308`). `abandoned` is never sent. |
| `end` | Party sends `end` when the Host ends the game, when a launch fails or goes stale, when a game reports `abandoned`, and when the Host leaves the results for Party Home, where Party's own text says the game's held results are "released" with an `end` "acknowledged for a finished session" (`party:avrana/party/service.py:132-139,169-187,197-198,201-211`; ADR 0011:36-38). | `end` drops the match, every token and every waiting poll (`checkers/server.py:165-168,189-201`). It also acknowledges the `end` that follows its own `ended` (F3). |
| Origin and bridge | A game page lives on its own origin and reaches Party only through the invisible bridge frame, a closed verb set (`ticket`, `view`, `navigate`, `end`, `home`, `playAgain`) (ADR 0013:109-120; `party:web/party/lib/bridge.js:1-27`). A page is shown `party, member, host, hostName, location {at, game}, round {game, state, outcome, myRole}` and nothing else (`party:web/party/lib/bridge.js:57-74`). | The shim is Party's file, vendored unchanged and pinned by digest (`web/avrana-party-bridge.js`; `provider/avrana-contract.json:21-26`), and served from the game's own path (`checkers/server.py:73-76`). The page learns where Party is from its own server (`GET api/party`: `checkers/server.py:56-57,144-146`), embeds the frame, asks for a ticket and trades it for a seat (`checkers/web/app.mjs:369-397`). Its policy allows one frame, Party's origin (`checkers/server.py:83-89`). |
| The Host's controls and the waiting line | Host controls live in the game's own chrome (ADR 0011:62-67). A completed round's results are held on the game's page until the Host chooses Play again or Party Home (ADR 0011:31-38; `UX:842-846`, Rule 12.1, accepted). The results screen says what happened, gives the Host the two choices and everyone else a named waiting line (`UX:174-177,848-852`, Rules 3.8 and 12.2, proposed). | The page draws Play again and Party Home for the Host and `Waiting for <host> to choose what is next.` for everyone else (`checkers/web/app.mjs:210-227,341-344`), and an End control with a Cancel and End game confirmation while a game is on (`checkers/web/app.mjs:332-339`; `UX:854-864`, Rule 12.3, accepted). |

What needed no change: the vendored protocol and result files are byte-identical to
`party:avrana/party/protocol.py` and `party:avrana/party/result.py` (compared with `cmp`) and are
pinned by digest (`provider/avrana-contract.json:7-8,15-16`); a test fails if either is forked
(`tests/test_checkers_process.py:1470`). Nothing named Checkers was needed in Party Core to write
the Games half.

## 3. What `checkers/party.py` wrote that the stand-in also has

The stand-in is `party:avrana/games/standin/game.py` (298 lines, test only, AVR-236). It imports
Party's own `protocol`, `result`, `service` and `sessions` (`:45`), so some of what it has is
Party's code imported, which a Games-side game cannot do. The fork's `core/party_session.py` and
`core/net.py` are a third, older implementation of the same game side, over loopback TCP. ADR
0016:337 names three of the pieces a native game must gain: serve an inherited socket, treat "arrived
on the Unix socket without proxy headers" as the local check, and post `ended` to a Unix socket.

### 3.1 The overlap

In the Checkers column `party.py`, `server.py` and `session.py` are the files under `checkers/`. In
the fork column `server.py` is the repository's own `server.py` at its root.

| Piece | Checkers | Stand-in at `75b5062` | The fork, and what differs |
|---|---|---|---|
| Strict, bounded JSON body | `checkers/party.py:56,69-114` | `game.py:56,69-93` | `server.py:168-181`, `core/party_session.py:54`: plain `json.loads`, 8 KiB. Checkers adds integer and integer-list fields, a lone-surrogate check and exact keys; the stand-in takes strings only |
| One JSON reply shape | `party.py:117-125` | `game.py:96-97` | |
| Refusing control traffic that came through a proxy | `server.py:126-133`; `party.py:55` | `game.py:55,113-119` | `core/party_session.py:55,136-139`. The stand-in and the fork test the header's value, so an empty header passes (3.2); ADR 0016:165 says "when a proxy header is present". Checkers tests presence |
| `listen_fds` | `party.py:130-138` | imported from Party (`game.py:45,285`; `party:avrana/party/service.py:517-525`) | none (TCP). The rule is the same: `LISTEN_PID` is this process, descriptors start at 3 |
| Key file and environment | `party.py:54,141-143`; `server.py:339-356` | `game.py:282-298` | `core/party_session.py:111-123,142-154`. Same refusals, same promise never to log the key |
| Serve the inherited socket | `party.py:293-325` | `game.py:268-279` | Party's own internal server does it a third time (`party:avrana/party/service.py:528-547`). Both natives close the socket the server class made and put the inherited one in its place. Checkers also gives the class the socket's family first (F1), checks `SO_ACCEPTCONN`, and takes TCP only in tests |
| Request handler: size bound, JSON only, body read before the answer, no URL logged | `party.py:223-290` | `game.py:223-265` | Near-identical logic. Checkers adds a 405 for other methods, one write per response and a handler that survives a phone going away mid-answer |
| Security headers on every reply | `party.py:63-64,243-246` | `game.py:65-66,237-238` | |
| HTTP over a Unix stream socket | `party.py:167-180` | imported from Party (`game.py:45,203`; `party:avrana/party/sessions.py:54-65`) | none (TCP). Checkers says so plainly where the platform has no `AF_UNIX` (F8) |
| The `ended` report and the verdict word | `party.py:183-204`; `server.py:318-330` | `game.py:190-195,198-220` | `core/party_session.py:178-191` reads the status only. Both natives read Party's `result` word |
| Telling the page where Party is | `server.py:56-57,144-146`; `party.py:61,146-149` | `party#87:avrana/games/standin/game.py:60-61,130-131,307-308` | `server.py:133-150`, as `/api/avrana`, with a looser pattern. Three spellings of one route; the same environment name in all three. Checkers' origin pattern is the stand-in's at #87 |
| Entry in the process's own `main` | `server.py:339-356` | `game.py:282-298` | |

Pieces Checkers has and the stand-in lacks:

| Piece | Checkers | Stand-in | The fork |
|---|---|---|---|
| Retry of `ended` inside the message's 30 s, off the lock | `party.py:60,207-218`; `server.py:318-336` | none: "A retry would need the same signed message, which this game does not keep" (`game.py:186-190`) | `core/party_session.py:23-29,62-63,211-234`, the same policy in async form |
| Acknowledging the `end` that follows the game's own `ended` | `server.py:189-201` | refuses it with a 403 (`game.py:139-142`; probed) | `core/net.py:236-261` |
| Comparing tokens | `server.py:205-211`, as UTF-8 bytes | `game.py:173`, as `str` (3.2) | |

### 3.2 Two defects found in the older copies

Facts:

- **An empty proxy header passes.** The stand-in tests `headers.get(h)` (`game.py:116`) and the
  fork tests `headers.get(h)` (`core/party_session.py:139`), so `X-Forwarded-For` with nothing after
  the colon is taken as unproxied. Probed: a launch carrying an empty `x-forwarded-for` is answered
  200 by the stand-in, and `local_unproxied("127.0.0.1", {"x-forwarded-for": ""})` is `True` in the
  fork. nginx always sets a non-empty value (`party:deploy/games/nginx-native-games.location:28-29`),
  so this is not reachable through the deployed front door; it matters for another front door or a
  bug. Checkers refuses on presence and tests it over the App and over HTTP, for every header it
  knows, with and without a value (`checkers/server.py:126-133`;
  `tests/test_checkers_process.py:157-170,960-975`).
- **A non-ASCII token raises.** The stand-in compares the posted token with `hmac.compare_digest`
  on `str` (`game.py:173`), which raises `TypeError` for a non-ASCII string. Probed: with one player
  seated, a `finish` carrying `"é"` raises out of `Standin.handle`. Over HTTP the server's error
  handler would print a traceback (not run). The route needs no ticket to reach, so any phone that can
  load the page could trigger it while a player is seated; the effect is a failed request and no
  change of state. The stand-in is test only, but a Games-side game that copied it would carry the
  defect. Checkers refuses strings that cannot be written as UTF-8 at the JSON
  boundary (`checkers/party.py:75-83`) and compares bytes (`checkers/server.py:205-211`).

Neither is fixed here: the Party repository is read-only for this work and this pull request does not
touch the fork. Proposal: the Party lane corrects the stand-in; the fork's guard is worth a change
only if the fork outlives ADR 0014's retirement plan.

### 3.3 What this says about D5

Facts: NATIVE:81 already lists `core/party_session.py` as an extraction candidate (key loading, the
unproxied guard and the `ended` delivery policy), and NATIVE:112-114 says a pattern is promoted
"only on repeated evidence", when a second independent game needs the same thing. Checkers is the
second native game to need these eleven pieces, and the third copy overall. D5 decided not to
promote them on the evidence of the stand-in and Checkers alone, and this note does not either.

Proposal: the evidence for the rule in NATIVE:112-114 is now in one place. What a library would have
to carry is the left-hand column of 3.1 plus the `end` acknowledgement of F3 and the retry of F5,
and it is standard-library only. When a third independent native game (BLUFF's migration, or the
Spades lane) needs them, the rule is met and the choice of how to share them is Party's.

## 4. Findings: what the boundary does not yet give

F1 to F11 are the findings recorded in the pull request while the Games half was built, in the same
order; the statement of F4 is corrected (the reloaded results screen is defined, not undefined).
F12 to F14 were found later.

**F1. Serving on the inherited descriptor under `RestrictAddressFamilies=AF_UNIX`.**
Facts: `http.server.ThreadingHTTPServer(address, handler, bind_and_activate=False)` still creates
its own `AF_INET` socket while it is constructed (`socketserver.TCPServer.__init__`). The unit
allows `AF_UNIX` only (`party:deploy/games/avrana-game@.service:31`; ADR 0016:170-173), so under
the unit that `socket()` call is refused and a game built that way does not start. The stand-in
avoids it by subclassing `UnixStreamServer` (`game.py:268-279`) and so does Party's internal server
(`party:avrana/party/service.py:528-547`). Checkers keeps the HTTP server class and gives it the
inherited socket's family first, then replaces the socket the class made (`checkers/party.py:293-325`).
`tests/test_checkers_process.py:1132-1163` records every socket created while the server is built.
CI does not run under the address-family filter, so that test, and not a green run, is what catches a
regression. It was not run under systemd.
Proposal: the runtime, not each game, builds the server on the descriptor it hands over.

**F2. The overlap with the stand-in.** Section 3.

**F3. `end` after `ended`.**
Facts: `GameSide.ended` clears `sid` and the roster at once (`core/party_protocol.py:484-490`) and
`GameSide.on_end` refuses any `end` whose `sid` is not the running one (`:439-444`). Party sends that
`end` when the Host leaves the results for Party Home (`party:avrana/party/service.py:132-139`) and
ignores the answer. Three implementations answer it three ways: the stand-in refuses it, probed as
403 with reason `session` (the real-systemd proof's driver goes home from the results at
`party:experiments/native-game/driver.py:233-252` and checks only Party's location, so nothing there
pins the acknowledgement Party's own text describes); the fork remembers the last session and
acknowledges it (`core/net.py:221,236-261`); Checkers does the same with `finished_sid`
(`checkers/server.py:117,189-201`; test `tests/test_checkers_process.py:615-627`). For Checkers the
acknowledgement also releases the finished match that seated phones can still read.
Proposal: an `end` for the session the game last reported is "already done" and is acknowledged by
`GameSide` itself. It changes no wire format but is a paired change to a digest-pinned vendored file
(D13).

**F4. After `ended` no ticket is admitted: results without a board.**
Facts: `GameSide.ended` leaves no session for a ticket to match (`core/party_protocol.py:265-266`),
and Party mints none once its session is no longer active (`party:avrana/party/core.py:697-698`).
Party does send every phone to the game's page at `results` and holds it there until the Host moves
on (ADR 0011:31-38,43-47; `party:avrana/party/core.py:655-669`). So the state is defined, not
undefined: a phone that opens or reloads at the results lands on this game's page with nothing to
redeem. The independent review of PR #54 found the page showing nothing there. It now shows
"Game over", the Host's Play again and Party Home or the named waiting line, and no board
(`checkers/web/app.mjs:131,210-227`; scenario `results`, `tests/checkers_page_test.mjs:441`). What is
missing is what the page may show: the bridge's `round` carries `outcome` and no standings
(`party:web/party/lib/bridge.js:72`; `web/avrana-party-bridge.js:45-47`), and Party keeps the accepted
result without exposing it: "what phones are shown is unchanged" (ADR 0015:125-127), "no public route
exposes it" (`party:experiments/native-game/driver.py:21-22`). A reloaded results screen therefore
cannot say who won, where UX Rule 12.2 (proposed) wants the results screen to say first who won or
what happened (`UX:848-852`). Phones that held a seat when the game ended keep the finished board
until the match is released (`checkers/server.py:28-34`; `tests/test_checkers_process.py:534-548`).
Proposal: D12.

**F5. `ended` is not idempotent for the game.**
Facts: the replay guard remembers nonces and nothing else (`core/party_protocol.py:342-356`). A retry
of a message Party already accepted meets `Invalid('replay')` and is answered 403
(`party:avrana/party/sessions.py:174-179`), and a second `ended` for a session that has ended is
403 (replay) or 409 (stale) with the stored result unchanged (ADR 0015:107-111;
`party:avrana/party/core.py:593-595`). So if Party accepts a report and the reply is lost, the
game's retry gets a 4xx and cannot tell "accepted earlier" from "refused". Checkers treats any answer
under 500 as final and logs that the Party "did not accept" the report with the status
(`checkers/party.py:207-218`; `checkers/server.py:323-330`): a misleading warning and no other
effect, since the phones keep the board and Party holds the result. The fork has the same policy and
says so (`core/party_session.py:23-29`).
Proposal: Party answers a replay of the message it accepted with the same 200 and verdict (the guard
would need to keep the verdict per nonce), or the game's contract says a 403 after a lost reply is
expected (D13).

**F6. `game.build` has no source in a native unit.**
Facts: `game.build` must identify the implementation that produced a result (ADR 0015:59,137-148).
The fork digests the files it has loaded (`core/party_session.py:67-108`), because "a deployed tree
is an rsync copy with no trustworthy .git" (`:99-100`). Probed: `build_files("checkers")` lists 21
files, including the donor's `games/checkers/engine.py` and `games/checkers/game.py`, and none under
`checkers/`, so reusing it would stamp results with the donor's digest. ADR 0015:146-148 allows "its
release version" for a game with its own repository and release process; Checkers is in the Games
repository and has no release process. `BUILD = "checkers-0.1.0"` is kept by hand
(`checkers/party.py:42-46`), and the only test that reads it reads it back from `party.BUILD`
(`tests/test_checkers_process.py:509`), so nothing fails when the rules change and the constant does
not.
Proposal: D15.

**F7. Idle stop has no definition.**
Facts: ADR 0016:209-212 says a game "stops itself when idle" and ADR 0014:132-134 expects stopping
idle games to be cheap; no signal and no duration is given anywhere. The stand-in says it is "NOT
implemented ... deferred to AVR-238, with the resource ceilings" (`game.py:27-29`) and the unit says
the ceilings "come from measuring a real game (AVR-238)" (`party:deploy/games/avrana-game@.service:15`).
Checkers does not stop itself (`checkers/server.py:355`). Its match and `finished_sid` are in memory,
so "idle" cannot mean only "no request for a while" while a session is launched, running or held at
the results: the Party's go-home `end` is the one release (F3). A clean exit is not restarted by
`Restart=on-failure` and the socket unit keeps listening, so the next connection would start the
process again (systemd semantics, not run here). Not measured: Checkers' resident memory and CPU on
the Pi, which is what the ceilings are meant to come from (ADR 0016:244-246).
Proposal: D14.

**F8. A Windows development machine cannot run a native game.**
Facts: CPython on Windows has no `AF_UNIX`; `make_server` and `UnixHTTPConnection` say so
(`checkers/party.py:175-176,313-314`). The two real-process tests are skipped there
(`tests/test_checkers_process.py:1314-1315`) and ran only on Linux CI, where they passed on
`c44ee40` (run 37606044786). Everything else ran over loopback TCP through two seams production never
uses: `make_server(..., families=...)` (`checkers/party.py:302-325`) and `report_to(connect=...)`
(`:183-204`).
Proposal: the SDK, or the Party harness's native-process mode (D10), names an explicit development
transport instead of each game growing test seams.

**F9. The standard library's server logs too much by default.**
Facts: `BaseHTTPRequestHandler.log_message` writes every request line to stderr, so to the journal,
and a request line can carry a credential; `socketserver.BaseServer.handle_error` prints a traceback
and the client address. The stand-in and Checkers both silence the first
(`game.py:227-231`; `checkers/party.py:232-236`). Only Checkers replaces the second with one line
that names the exception class (`checkers/party.py:296-299`; test
`tests/test_checkers_process.py:1179-1213`).
Proposal: a runtime's default is silent, and a game opts in to more.

**F10. Every native page repeats the same plumbing.**
Facts: serve the bridge shim from the game's own origin at a path that does not move
(`checkers/server.py:73-76`), a route that tells the page where Party is
(`checkers/server.py:56-57,144-146`), a policy whose `frame-src` is that origin
(`checkers/server.py:83-89`), a retry when a module import fails on a Wi-Fi blip
(`checkers/web/checkers.js:1-22`) and a retry for the origin route itself
(`checkers/web/app.mjs:369-383`). The stand-in repeats the route at #87 and the fork repeats it as
`/api/avrana` (the root `server.py:146-150`).
Proposal: a package says "this page needs the bridge", and the runtime serves the shim, the route and
the policy.

**F11. Late joiners hold tickets the launch roster does not name.**
Facts: ADR 0006:103-104 says late members are admitted as spectators (v0), and Party gives them
spectator tickets of their own (`party:avrana/party/core.py:721-729`; the default `late_join` is
`spectator_only`, `:148`). `GameSide.present` checks the session and not the roster
(`core/party_protocol.py:446-456`), and the launch roster never grows after launch. Checkers seats
only the two players the launch named and shows every other ticket holder the board, read only, even
when the ticket says player (`checkers/server.py:231-234`; `tests/test_checkers_process.py:354-372`).
Nothing tells a game that a ticket may name someone it never saw.
Proposal: the package says what a game does with a ticket that is not on its roster.

**F12 (new). A page cannot tell a new session of its own game from the old one.**
Facts: the bridge hands a page no ids of any kind (`party:web/party/lib/bridge.js:57-59`), and the
shim refuses a view with any other key (`web/avrana-party-bridge.js:40-47`). Party's client
delivers a phone only the latest view after a gap (`party:web/party/lib/party-client.js:6,34-41`), so
a phone that was locked or offline through the results sees `game` and then `game` again, with no
`results` between. The review of PR #54 found the page staying on the old board when Play again
started the next game. Now, while Party says `game` for this game and the page's game is over, the
page asks for a seat on each word from Party and every 3 s, and a fresh ticket redeems only for the
new session (`checkers/web/app.mjs:430-443,454-466`; scenarios `again` and `missed`,
`tests/checkers_page_test.mjs:393,507`). The cost is one ticket request per attempt in a window that
is normally one attempt long (reasoned, not measured). Related: a page cannot know whether the
other player is here. Presence is in Party's view (`party:avrana/party/core.py:739-741`) and not in the
bridge's, and Checkers keeps no presence signal of its own, so with D6 ("a disconnected player's
turn waits") the waiting player sees the turn line and nothing says the opponent is away.
Proposal: D12.

**F13 (new). Rules in play, and the shape of onboarding.**
Facts: Checkers' `onboarding.json` is `avrana.onboarding/v0`: a premise, an acknowledgement key, two
facts and six sections of one to three points (`checkers/web/onboarding.json:1-29`). Every number in
the text is a placeholder pinned to the rules by a test (`tests/test_checkers_web.py:240-258`), and v0
was enough for this game. Three observations:

1. Party reads the file for the library's How to play button and for the setup scene, where the
   acknowledgement is consulted (`party:web/party/app.js:274-275,776-784`). With `pregame: false`
   there is no setup scene (`party:avrana/party/core.py:405-420`), so at `75b5062` nothing reads
   `ack` for Checkers and no first-play briefing shows. The rules are reachable from the library's
   game sheet before a game and from Checkers' own Rules button during it
   (`checkers/web/app.mjs:346-365`).
2. UX Rule 4.15 (accepted) says rules stay reachable during play, and records that no platform way to
   open them exists (`UX:403-415`). Checkers is the third game, after BLUFF and EXPO, to draw its
   own sheet, and its code fills the `{fact}` placeholders itself (`checkers/web/app.mjs:354-356`),
   as the shell's does (`party:web/party/app.js:763-765`).
3. AVR-37 asks that a package leave room for a short objective, first-play content, player-visible
   actions, rules sections with stable identifiers, example assets and a rule for when to show
   onboarding (Linear AVR-37). Checkers' v0 content has the objective (`premise`) and titled
   sections without identifiers. It has no list of actions, no example asset, and no show policy
   that anything reads for it.

Proposal: try UX's v1 draft (`UX:455-523`, proposed, not built) against this file before
settling the content shape. Part of the question is D11.

**F14 (new). `pregame: false`: who plays, and the player minimum.**
Facts: with no pregame Party picks the players itself: the members who are here, in join order, up to
`max_players` (`party:avrana/party/core.py:163,176,389-393,415-418`), so with six phones the first
two to have joined play and the others watch. `min_players` is enforced only in setup
(`party:avrana/party/core.py:439-440`). Checkers refuses what it cannot host with a sentence
(`checkers/server.py:170-187`), and Party Home shows it to the Host (`party:web/party/app.js:559-568`).
Proposal: D11.

## 5. What a package or SDK primitive must express that today's boundary does not

Requirements read off one game, not a format. No `.avrgame` field is proposed here, and what a
requirement becomes is AVR-37's and AVR-38's to decide after Spades (ADR 0014 decision 12,
`ADR 0014:96-99`).

| A primitive has to say, or own | Because | Today |
|---|---|---|
| How a game is served: an inherited listener, no address, no family, quiet by default | F1, F8, F9 | each game builds it |
| What the platform serves for a page: the bridge shim, where Party is, the page's security policy including who may frame it | F10, D1's note in 7.1 | each game serves them |
| The life of a session as the game sees it: launched, admitting, reported, released; `end` for a reported session is acknowledged | F3 | `GameSide` refuses it |
| What a page can show after `ended`: a read-only admission for a finished session, or a platform-held result | F4 | nothing: "Game over" |
| Reconnect at three levels: the page's link to the game blinks (poll with backoff, `checkers/web/app.mjs:399-428`), the page's seat is gone (a 403, then a fresh ticket: `:419-423`, scenarios `reload`, `replaced`, `stale`, `link`), a new session of the same game starts (F12). And who else is present | F12 | each page does all three itself |
| Delivery of `ended`: at least once, with a guard that turns a retry into a 403 | F5 | the game treats 4xx as final |
| The process's lifetime: idle stop, and what happens to a session held in memory across a restart | F7, ADR 0016:289-290 | undefined; a restart loses the match |
| Build identity of the implementation | F6 | a hand-kept constant |
| Onboarding content: objective, sections with stable identifiers, facts pinned to the rules, a show policy, a rules control in play | F13 | v0 sections and facts; each game draws its own sheet |
| Roster and player bounds: who is seated, what a ticket not on the roster may do | F11, F14 | join order; the game refuses what it cannot host |
| A development transport | F8 | seams in each game |

## 6. Which Party rules are accepted and which are proposed

What each source says about itself at `75b5062`, and what Checkers leans on it for. Checkers
behaves by the accepted ones. It follows the proposed ones only as a direction for wording, such as
the waiting line.

| Source | Status as the source states it | What Checkers relies on it for |
|---|---|---|
| Session protocol v0 (`ADR 0006:3-6`) | "implemented and merged"; deployed, server-side verified 2026-09-29. Single-use tickets are merged source and a game gets them only by taking the new vendored copy (`:22-26`). The host claim is "accepted by the owner on 2026-10-04" and "not merged, not deployed" at that time (`:211-215`), while the header line still calls it proposed (`:8`) | launch, tickets, `ended`, `end`; the host claim is not used |
| Result envelope v1 (`ADR 0015:3`) | accepted 2026-10-03 | the result Checkers builds and reports |
| Native game runtime (`ADR 0016:3`) | accepted 2026-10-03, with its five owner decisions (`:44-57`); its status line still reads "accepted · not implemented · not deployed", although `75b5062` has the template units, the internal socket server and `provision-game` (`party:deploy/games/`, `party:avrana/party/service.py:528-558`, `party:avrana/party/sessions.py:24-27`). Section 5's runtime convention is "not an SDK" and "may change before `.avrgame`" (`:248-251`). Idle stop is stated and not defined (`:209-212`) | fd 3, the key credential, the internal socket, `RestrictAddressFamilies=AF_UNIX` |
| Native games direction (`ADR 0014:3`) | "accepted (direction) · proposed (mechanisms) · not implemented". Decision 11: Checkers is the proof, Spades the pressure test (`:91-95`). Decision 12: `.avrgame`, the SDK and the provider stay unfrozen until both have proven the boundary (`:96-99`). Tier 3 proves a Checkers round on real phones "before any SDK is declared" (`:135-136`). It still calls ADR 0016 "proposed" (`:142-144`); the two statuses disagree and 0016's own line is the later one | the shape of the task |
| Origins and bridge (`ADR 0013:3`) | accepted; mechanisms D1 to D5 accepted 2026-10-03 (`:109-120`); the bridge "is not relied on for field testing until" real-phone validation passes (`:130-133`) | the page's only way to Party |
| Console model (`ADR 0011:3-7`) | accepted and merged; production deployment and real-phone proof pending (AVR-212). Results are held (`:31-38`); an abandoned round has no results screen (`:120-124`) | results on the game's page; the Host's controls in the game's chrome |
| UX Rule 12.1 (`UX:842-846`) | accepted (ADR 0011) | Play again and Party Home are the Host's, with no timer back to a lobby |
| UX Rule 12.3 (`UX:854-864`) | accepted (owner decision, 2026-10-05) | End with a Cancel and End game confirmation |
| UX Rule 4.15 (`UX:403-415`) | accepted, and "Not built" for a platform control | the page's own Rules button |
| UX Rule 12.4 (`UX:866-868`) | accepted for BLUFF, proposed for every game | phones move only when Party moves them: the page has no control that leaves the game except the Host's verbs |
| UX Rules 3.8 and 12.2 (`UX:174-177,848-852`) | proposed (implemented in BLUFF's bar, EXPO's takeover and the shared panel) | the waiting line and the results screen's wording |
| UX Rules 4.16 and 4.17 (`UX:420-428`) | proposed | none |
| `onboarding.json` v0 (`UX:432-453`) | implemented; v1 (`UX:455-523`) is proposed, not built | the file Checkers ships |
| NATIVE-GAMES section 3.1 (`NATIVE:70-76,112-114`) | "identifies candidates; it freezes nothing"; promotion "only on repeated evidence" | D5 |

## 7. Owner decisions

These are for the owner, not for this issue. Linear AVR-238 has no Open decisions, and nothing here
adds one there.

### 7.1 D1 to D10, and what the build showed

The decisions are the owner's of 2026-10-07 on Linear AVR-238, "approved as recommended".

| Decision | What the build showed | Status |
|---|---|---|
| D1. Runs on the isolated game origin and uses the Party bridge only | The page uses no cookie, storage, navigation or Party call but the shim, and only relative routes (`tests/test_checkers_web.py:163-199`); the policy allows one frame, Party's (`checkers/server.py:83-89`). Note for the guardrail that a game being the top-level document must not enter the SDK or contract: the page's policy says `frame-ancestors 'none'` (`checkers/server.py:89`). That is right while the shell sends the phone to the game origin, and wrong for a shell that frames a game viewport (AVR-83, AVR-292). Today it is a property of one game's server, not of any contract | held; watch the policy |
| D2. A small generic Party issue first (AVR-303) | The Games half needed one thing from Party, its origin (`AVRANA_PARTY_ORIGIN`, #87). Nothing named Checkers was needed in Party Core | held |
| D3. Stdlib HTTP with a long poll | Runs on system Python with only the standard library and the two vendored files (`tests/test_checkers_process.py:1435-1470`). The server skeleton is 105 lines (`checkers/party.py:221-325`) and the poll 20 (`checkers/server.py:238-257`). Cost on the Pi and a burst of more than 32 waiting polls are not measured | held |
| D4. The pinned Party protocol and result modules, as pre-SDK debt | Used byte for byte. The debt is F3, F4 and F5 | held; D13 |
| D5. Helpers stay local to Checkers | Section 3 is the evidence | held |
| D6. Forced captures, resign; no draw offers, takebacks, timer, bot or autopilot; a disconnected turn waits; the Host may end | All in `checkers/rules.py` and `checkers/session.py:11-15`. The fork's automatic draw (80 half-moves) stays, as decided on 2026-10-04. A waiting player cannot be told the opponent is away (F12) | held |
| D7. Roster order decides sides and first mover | `checkers/session.py:66`. Party's roster order is join order among those present (F14) | held; D11 |
| D8. `pregame: false`, with real onboarding and rules | `onboarding.json` v0 was enough and is pinned to the rules (F13). What `pregame: false` implies is F14 and part of F13 | held; D11 |
| D9. Generic artwork now | One plain `checkers/web/icon.svg` of 18 lines, no raster, font or sound | held |
| D10. Extend Party's harness with a native-process mode; no Games-side browser harness | The Games half starts no browser. Its page tests run on a fake DOM against the real server in Node (`tests/checkers_page_test.mjs`), which is not a browser harness and proves no browser behaviour | held |

### 7.2 New and open: D11 to D15

**D11. Confirm what D8's `pregame: false` implies (new, open).**
Facts: F14 and F13 point 1. Who plays is the first two present members in join order and nobody
chooses; the rest watch. Party enforces no minimum at a direct launch, so with one person present
Checkers answers 409 and Party Home tells the Host that Checkers did not start and gives the
game's sentence, "Checkers needs two players." The first-play briefing and its acknowledgement do not run.
Options: A. keep D8 as decided and judge it on the two-phone test. B. `pregame: true`, which gives
people the choice and a briefing and costs a setup scene every round: Rule 12.1 sends Play again to
a new setup with no choices carried over (`UX:842-846`), and the contract's own pressure test says a
full briefing per round may feel heavy in a short game and leaves that to evidence (`UX:984-999`).
Proposal: A, and record what the owner sees at a table of six after the field run. The `pregame`
value is one field in the Party half's contract.

**D12. What a page with no seat may be told about the round (new, open).**
Facts: F4 and F12. After `ended` a reload has no board and cannot say who won; a page cannot tell a
new session from the old one except by retrying; the bridge's view is closed (`web/avrana-party-bridge.js:40-47`).
Options: A. nothing more: "Game over", the Host's choices and the waiting line, and the retry in
F12. B. the bridge view carries more, such as an opaque round counter, the accepted result's
headline or who is here: a Party Core and bridge change, and the result part needs AVR-71's privacy
decisions first (ADR 0015:186-188). C. the game admits a read-only ticket for its finished session so
a reload can read the board: a change to `GameSide` and to Party's ticket route
(`party:avrana/party/core.py:697-698`). D. the game serves a ticketless result-only read of names and
outcome: the smallest Games-side change, but an unauthenticated route in a game and a second source
of truth for results (ADR 0014 decision 9).
Proposal: A for the field test; the two-phone test shows how often a phone reloads at the results,
and that decides between B and C.

**D13. Which protocol gaps are fixed in the v0 files before the SDK (new, open).**
Facts: F3 and F5. D4 treats the vendored modules as pre-SDK evidence and debt. Changing one is a
paired change with digests in both contract declarations (`provider/avrana-contract.json:7-8,15-16`;
ADR 0015:179-181; the precedent is AVR-253, ADR 0016:147-154).
Options for F3: (i) `GameSide.on_end` acknowledges the session it last ended, about three lines and
no wire change; (ii) leave it to each game until the SDK. Options for F5: (i) Party answers a replay
of an accepted `ended` with the same verdict; (ii) leave it and document that a 403 after a lost reply
is expected.
Proposal: F3 (i), because Party's own text expects the acknowledgement (`party:avrana/party/service.py:133-134`)
and its reference game does not give it; F5 (ii), documented.

**D14. What "idle" means for a native game (new, open).**
Facts: F7.
Options: (i) none for the field test: a started game stays resident, and its cost is measured on the
Pi first. (ii) idle is "no session launched or held, and no request, for N seconds", with N measured,
and the process exits cleanly; the socket reactivates it.
Proposal: (i) until Checkers' resident cost is measured, because the resource ceilings wait for the
same measurement (ADR 0016:244-246); then write (ii), or its replacement, into ADR 0016.

**D15. Where `game.build` comes from for a native game (new, open).**
Facts: F6.
Options: (i) a constant kept by hand, with a test that fails when the package's files change without
it; (ii) provisioning computes the installed tree's digest or release version and hands it to the
process like the key; (iii) the process digests its own files at start, as the fork does, once the
package's file set is declared.
Proposal: (ii) or (iii) is the package definition's to choose (AVR-37). Until then, (i), which is
cheap. The pinning test is not built here.

## 8. Unproven until the Party half runs

| What | Why it is unproven here | What shows it |
|---|---|---|
| Checkers inside the real unit: `DynamicUser`, `LoadCredential`, `RestrictAddressFamilies=AF_UNIX` (F1) | CI runs the real process on a Unix socket but not under the filter. The stand-in was proven in the unit (`party:.github/workflows/service-trust-proof.yml:7-10`); Checkers has not run in it | the Party half's real-systemd step with Checkers provisioned |
| The game contract, grant `runtime`, catalog entry, `provision-game checkers`, boundary phase 2 | none exists yet; they are Party-side data and tooling | the Party half |
| The front door in front of Checkers | the generic route sets `Connection: upgrade` on every request and has a 3600 s read timeout (`party:deploy/games/nginx-native-games.location:31-33`). The native-game proof's driver talks to the game's socket directly (`party:experiments/native-game/driver.py:209-224`), so nothing sends Checkers' 25 s long polls through nginx | the two-phone test through the real route |
| The bridge in a real frame on another origin, with `playAgain`, `home`, `end` and `navigate` against a real Party Core | the page tests use a fake bridge and a fake DOM; the shim has not passed real-iPhone validation (`ADR 0013:130-133`) | the two-phone browser test (D10) |
| A phone reloading at the results, and Play again from the results, against Party Core's real navigation and timing | scenarios `results`, `again` and `missed` model Party with a flag that gives no ticket once the session is over (`tests/checkers_page_test.mjs:393,441,507`) | the same test |
| What a table of six looks like with `pregame: false` (D11) | no Party launched it | the same test |
| The accepted result reaching Party's record and what Party Home shows of it | a fake Party answers "accepted"; the cross-repository session and contract tests pass against Party's `main`; no public route shows the accepted result (`party:experiments/native-game/driver.py:21-22`) | the Party half's journal check, then AVR-71 |
| Cost on the Pi: memory, threads, CPU, and a burst of more than 32 waiting polls | only the limit lowered to 2 is tested, against the App (`tests/test_checkers_process.py:477-493`) | measurement on the Pi (AVR-261) |
| A restart in mid-match, and Party's session afterwards | the match is memory only; Party's side is "orphaned and ends by the existing rules" (`ADR 0016:289-290`) | a field run |
| Real phones | no phone was used | AVR-261 |

AVR-238's acceptance criteria, as far as the Games half can speak to them. "By test" means a fake
Party or a fake DOM, not a Party Core or a browser.

| Criterion (Linear AVR-238) | The Games half | Waits for |
|---|---|---|
| A Game Contract and a catalog entry, with no Checkers-specific code in Party Core | nothing to do here | the Party half |
| `provision-game checkers` produces a running `avrana-game@checkers` that Party Core launches | runs as a real process on an inherited Unix socket in Linux CI (`tests/test_checkers_process.py:1314-1417`) | the grant, the real unit |
| Two seated players, each sees only their own side's controls, an unseated device is refused | by test (`checkers/server.py:205-236,282-283`; `checkers/session.py:90-107`; `tests/test_checkers_process.py:366-410`) | a browser, two phones |
| The page holds no Party device cookie and calls no Party API except through the bridge | by test (`tests/test_checkers_web.py:163-199`) | the bridge in a real frame |
| A signed `ended` with `avrana.game-result/v1` that Party Core accepts and Party Home shows | built with Party's own check and signed; a fake Party accepts it. There is no public surface that shows an accepted result today (F4) | a real Party Core |
| A player who reloads or reconnects mid-game returns to the same seat and board | by test (`tests/test_checkers_process.py:311-329`; page scenarios `reload`, `replaced`, `stale`, `link`) | a browser |
| The Host ends the game from Party Home and the process holds no session | the match, tokens and polls go (`tests/test_checkers_process.py:268-290,1409-1417`) | Party Core and the shell, in a real browser |
| `python3 -m avrana.ops.boundary --phase 2` reports every rule met | not applicable here | the Party half, a real host |
| A dated findings note | this note | the Party half's note, for what provisioning and the bridge did not provide |

## 9. Known limits of the Games half

The list in [the Checkers README](../../checkers/README.md) is the one to keep current. In short:
the match is in memory; there is no reconnect timer; the process does not stop itself when idle;
`BUILD` is a hand-kept constant; an IPv6-literal Party origin is not accepted by `BARE_ORIGIN`
(`checkers/party.py:61`), so the page would be told there is no Party; at most 32 long polls wait at
once (`checkers/server.py:80`) and the limit is tested only at 2. Nothing ran in a browser and
nothing ran on the Pi. Attribution for the rules adapted from the fork is in
[the NOTICE](../../checkers/NOTICE.md).

## 10. Limits of this note, and how its probes can be repeated

- Party was read at `75b5062`, not run. The one exception is the stand-in, whose request function was
  called in process. The route to tell a page where Party is exists in the stand-in only at #87,
  which was open when this was written (head `79e8911`); it is cited as `party#87:` and not as `main`.
- The vendored files, the stand-in and the Party sources cited are the ones at the commits named at
  the top. Line numbers in a later Games or Party commit will differ.
- The note does not say what an `.avrgame` package should look like. Sections 4 and 5 are
  requirements read off one game, and the Spades lane's readiness packet (`docs/findings/2026-10-07-spades-native-readiness.md`
  on `feat/avr-312-spades-readiness`, Games PR #55) adds the requirements Spades has that Checkers does
  not (its section 11) and maps D1 to D10 onto Spades (its section 13.3). D11 to D15 are new
  relative to that mapping.
- Linear text was read on 2026-10-07 and can change. AVR-238's own comment of the same day lists
  the findings as eleven and calls the reloaded results screen "undefined"; F4 corrects that.

Recipes for the probes (scratch scripts, not committed):

- The stand-in: build `Standin(protocol.GameSide(key, "standin"), lambda message: (200, "accepted"))`
  from `party:avrana/games/standin/game.py` with `PYTHONPATH` set to the Party checkout and
  `PYTHONDONTWRITEBYTECODE=1`. Launch with `protocol.launch_message`, redeem a `mint_ticket` for a
  player, then call `handle("POST", ...)` for: `/api/finish` with `{"token": "é"}` (raises
  `TypeError: comparing strings with non-ASCII characters is not supported`); `/api/finish` with the
  real token, then the session's `protocol.end_message` on the end route (403, reason `session`, and
  the same message again 403, reason `replay`); a launch with the header `x-forwarded-for` set to an
  empty string (200).
- The fork: `core.party_session.local_unproxied("127.0.0.1", {"x-forwarded-for": ""})` returns
  `True`; `core.party_session.build_files("checkers")` lists 21 files, `games/checkers/engine.py` and
  `games/checkers/game.py` among them and none under `checkers/`.
- Sizes: `checkers.party.make_result([(a, "won"), (b, "lost")], "resigned", 1)` serializes to 354
  bytes of canonical JSON (sorted keys, compact separators), 358 with 99999 plies;
  `protocol.ended_message(key, "checkers", sid, "completed", result=made)` is 823 to 828 characters.
- The line counts are `wc -l` at `c44ee40`; the test counts are those of
  `python -m pytest -q tests/test_checkers_rules.py tests/test_checkers_session.py tests/test_checkers_process.py tests/test_checkers_web.py`
  (222 passed and 2 skipped on Windows, where the two real-process tests cannot run) and
  `node --test tests/checkers_board_test.mjs` (15 passed).
