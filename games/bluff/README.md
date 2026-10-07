# BLUFF (working title): developer notes

The first Avrana-native game: a **social bluffing card game**, using Coup-style mechanics as
a **temporary baseline** while the interaction model is proven. The role names (Banker,
Agent, Smuggler, Broker, Guardian) and all text are original placeholders. The mechanics and
identity will be redesigned once this plays cleanly on phones.

*Not* classic Diplomacy: that direction was abandoned (see the Avrana Party repo's
`docs/ROADMAP.md`). No map, powers, units or `diplomacy/diplomacy` engine here.

## Architecture

| Piece | Where | Notes |
|---|---|---|
| Rules + state machine | `game.py` (`BluffSession(GameSession)`) | server-authoritative; the only place rules live |
| Phone client | `web/index.html`, `client.js`, `table.css` | a card table drawn in CSS; renders server state only |
| Framework (upstream LAN Games, unchanged) | `core/session.py`, `core/net.py`, `web/hubnet.js` | identity tokens, lobby, WebSocket, per-viewer pushes, timers, bot scheduler |
| Registry | `games/registry.py` (one entry, slug `bluff`) | the only upstream file BLUFF touches |

**Flow:** turn → claim → challenge window → block window → block-challenge window → resolve.
There are also `lose` (choose a card to lose) and `exchange` (choose cards to keep) prompts.
Every stage has a deadline. A timeout means pass/allow, the first card, keeping your hand, or,
for an idle turn, Income (Coup only when forced at 10+ coins). Every prompt has a public
`step` counter; clients echo it, and a stale answer is rejected ("that moment has passed").

## Private-state guarantees

- `game_state(viewer)` builds each player's payload on the server.
  - **Seats carry only public data:** coins, a *count* of hidden cards, revealed cards, and
    presence.
  - **A player's own hand and exchange draw** appear only in that player's `me` block.
  - Spectators (and `state_for(None)`) get public data only.
  - The deck order, tokens and saved-state blobs are never sent.
- The log records only public events (claims, challenges, reveals, losses). A proven claim's
  replacement card stays private.
- Every action is type-checked and validated against the current state and the sender's
  seat. Malformed input gets an `invalid` fx and never raises.
- Proven by differential tests (another viewer's payload is byte-identical whatever the
  victim's hidden cards are), a hostile-client matrix, a frame-shape whitelist over live
  WebSocket traffic, and the full-game simulator.

## Lifecycle (phones sleep)

| Situation | What happens |
|---|---|
| A player's last socket closes | seat shows **reconnecting…**; the game carries on unchanged |
| Returns with the same token (same phone/browser) | same seat, same cards, same prompt and deadline; others see "X is back" |
| Away > 30 s (prompts) / > 60 s (their own turn) | seat shows **away**; a **passive autopilot** answers for them: Income (Coup only at 10+), pass, allow, first card, keep hand. It never claims, challenges or blocks |
| **Every** seated human disconnected | the table **pauses** (timers and bots frozen); anyone returning resumes it with the remaining time (at least 10 s) |
| Paused > 60 s | a newcomer can **Start a new game** (ends the empty table) |
| The server's clock is stepped (time sync) | nothing changes: grace, autopilot, pause, takeover and the armed deadline are measured on the monotonic clock, forward or backward (AVR-221; `tests/test_clock_jumps.py`) |
| Paused 5 min | the game is abandoned and the room returns to the lobby |
| **Leave game** (drawer, two taps) | autopilot at once; eliminated at the next turn boundary |
| **End game** (drawer) | allowed when no other alive player is present |
| Refresh during the 3-2-1 countdown | keeps the seat |
| Unknown token mid-game | spectator (public view only) |
| Results screen | always runs its 20 s; "again" can't cut it short |

Constants are at the top of `game.py`.

## Testing

Run from the repo root with the repo venv:

```sh
.venv/bin/python -m pytest -q tests/test_bluff*.py     # rules, audit/fuzz, security, lifecycle, log wording
.venv/bin/python -m pytest -q                          # + the whole upstream LAN Games suite

# protocol-level checks against a RUNNING, fresh dev server (one room: restart between runs)
LANGAMES_PORT=8198 .venv/bin/python server.py &
.venv/bin/python tests/ws_check_bluff.py     ws://127.0.0.1:8198   # frame whitelist / privacy
.venv/bin/python tests/ws_attack_bluff.py    ws://127.0.0.1:8198   # hostile client
.venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 main               # reconnects
.venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 countdown_abandon  # abandonment

# full-game simulator with a rules oracle and invariants on every frame
LANGAMES_PORT=8200 .venv/bin/python tests/sim_bluff.py --serve --server-seed 19 &
.venv/bin/python tests/sim_bluff.py --url ws://127.0.0.1:8200 --seed 19 --players 6 --games 2 [--adversarial] [--lazy] [--spectator]
```

Phone-size screenshots were taken with headless Playwright/Chromium (2–6 players; 390×844,
360×740, 390×664). Chromium is **not** iOS Safari; see "real-device checks" below.

The table itself (AVR-313: reveal, buttons and focus, live region, contrast, overlays, drawer,
reflow at eight phone sizes and 200 % text, insets, reduced motion, the felt where nobody has a
hand: a Party spectator, a watcher, the lobby) is checked in a real browser
against real server states: `tests/bluff_states.py` plays the real session and the page's socket
is a stub, so no game runs. Run it against any server that serves the page (screenshots go to the
directory, `GAMEHUB_NODE_MODULES` and `CHROME_PATH` as for the other `.mjs` tests):

```sh
node tests/bluff_layout_test.mjs http://127.0.0.1:8198 /tmp/bluff-layout
node --test tests/bluff_layout_test.mjs     # no arguments: BLUFF_LAYOUT_URL / BLUFF_LAYOUT_OUT, else port 8198
```

`tests/test_bluff_story.py` pins the log wording the reveal reads (`OPENERS`, `OPENING_LINE`,
`CLAIM_AT` and `BLOCK_AT` in `web/client.js`) to `game.py`. A log line starts with a player's own
name, and a name can contain the verbs (`Bo claims Ag`), so the client reads a line only after a
seat's name; the tests play tables with such names.

## How to play: first-play briefing and rules (AVR-90)

`web/briefing.js` is one dialog with two modes:
- **First play:** six short cards, 231 words (about a minute): goal, a turn, claims, challenges,
  blocks, controls. It opens once per page load for a seated lobby player who has never
  acknowledged it. The last button, "I'm ready", is also that player's Ready. Escape can't skip it;
  "Not now" closes it, but the lobby's Ready opens it again until it is acknowledged.
- **Reference:** the `?` button beside Back to games reopens the same cards any time. Escape or
  Close; the game underneath is untouched. While it is open, a line says when the table is
  waiting on you.

Decisions:
- The acknowledgement is per browser (`localStorage` `bluff-briefed` = version). Private mode
  falls back to memory for that page. Nothing is sent to the server, and the dialog never touches
  the connection, so reconnect and seat restore (AVR-23) are unaffected.
- A player arriving while a game is already running (reconnect, watcher, a late Party member)
  is never covered by it; a toast points at `?` instead.
- In a Party (avrana-party ADR 0011, the console model) a round's setup is **Party Home's own
  full-screen scene**, not this page: its premise and concise rules come from
  `web/onboarding.json` (numbers as `{facts}`, pinned to game.py by `tests/test_bluff_briefing.py`),
  and a first-timer's Play opens those rules first ("Got it, I'll play"), acknowledging the same
  `bluff-briefed` key as this briefing.

## Party rounds (AVR-129; avrana-party ADR 0010)

- **The pregame is the Party's.** Every member who is here chooses Play or Watch. Only the Party
  Host can start, and only once everyone has chosen and 2–6 chose Play. BLUFF's own ready/start
  lobby is skipped: the launch roster's players are seated at once (`core/session.py`
  `party_start`), and BLUFF deals after a 3-2-1 once every seat's phone is here. After 15 s a
  missing seat starts away, so the usual grace and autopilot apply. BLUFF's ready, start and
  settings (test bots) are refused in a Party round. Standalone BLUFF keeps its own lobby.
- **Spectators see every hand, on purpose.** A Party spectator (a spectator ticket) gets
  `game_state_spectator()`: the public table plus every seat's cards, and the exchange draw while
  one is open. Players still get only their own cards. A TV or a browser-token watcher gets only
  the public view, because players can see that screen. Tests: `tests/test_bluff_party_pregame.py`.
- **Roles change only between rounds.** During a round a Party member cannot switch between Play
  and Watch; members who arrive late watch until the next setup.
- **The round is the Party Host's** (ADR 0011). BLUFF draws the host's controls in its own chrome
  (`window.AvranaParty`): an End button beside `?` (confirmed in the table's dialog), and on the
  results screen Play again / Party Home, while everyone else sees who they wait for. The results
  are held until the host moves on (no timer). In a Party round nobody else can end the game:
  `end_game` and the empty-table takeover are refused; a player's own forfeit stays. The Party
  bar (Back to Party) is hidden for everyone in a Party; standalone BLUFF keeps its lobby, its
  timers and its Back link.
- All words live in `CARDS`. The numbers and block rules come from `FACTS`/`BLOCKS`, which
  `tests/test_bluff_briefing.py` pins to `game.py`: change a rule and the test tells you to
  change the briefing. Bump `VERSION` to make everyone read it again.
- Human check for AVR-27: `games/bluff/PLAYTEST-BRIEFING.md`.

## Known limitations

- **One table per server** (one BLUFF room). The game lives in memory, so a server restart
  loses it.
- **Party sessions never share state (AVR-25).** Each Avrana party launch replaces the room with
  a fresh one: no hands, seats, coins, turn, pending step, log, bots or player mappings carry
  over. A connection acts only on the room it joined, so a message read just before a new launch
  is dropped, not dispatched. Old tickets and game tokens never reach a newer session.
  **After a server restart mid-session:** the new process holds no party session. Phones
  presenting the lost session's ticket are told it is invalid and never seated. No `ended` is
  reported for it. The Party Host's End for everyone still closes it on the Party side (this server
  refuses that end; Party Core closes the session anyway, or after 15 s with no answer), and the next launch starts clean. Tests: `tests/test_bluff_session_isolation.py`.
- **Framework-level issues (not fixed; they'd need `core/`):** oversized WebSocket frames are
  dropped only after being received; every message pushes full state to every socket
  (amplification); one device can fill all 6 *lobby* seats with invented tokens.
  (Mid-game watchers are allowed beyond the 6 seats, up to 6 more; the lobby itself holds 6.)
- **UX:** portrait only; placeholder emoji art; no confirmation after tapping a target (a
  mis-tap can spend a Coup); the claim sheet hides roles you can't afford instead of
  greying them out; a refresh in the lobby (not the countdown) gives you a new player id.
- **End game** has no majority vote yet: it's only allowed when nobody else is present.
- **Test bots** are passive and never bluff.
- Timings (90/20/30/45 s) are provisional.

## Real-device checks still needed (iPhone Safari)

Toolbar collapse and the `--apph` height sync; notch and home-indicator safe areas; sleep and
background then return (seat, cards, prompt); two phones on one table; a lock-screen during
someone else's claim; emoji rendering; text zoom.

## Next UX work

Target confirmation for Coup/Strike; greyed-out unaffordable claims; clearer two-step (claim,
then block) prompts for targets; timer tuning; event feed readability.

## Later

LAN Games-style **chat / social messaging** (social play is central to bluffing), original
art and identity, the rules redesign, an optional TV/table view (never showing hidden cards).
