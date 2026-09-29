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
.venv/bin/python -m pytest -q tests/test_bluff*.py     # rules, audit/fuzz, security, lifecycle
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
- A Party member taken into BLUFF by the Party Host's start (AVR-127) arrives at the lobby like
  anyone else, so a first-timer sees the briefing before their Ready.
- All words live in `CARDS`. The numbers and block rules come from `FACTS`/`BLOCKS`, which
  `tests/test_bluff_briefing.py` pins to `game.py`: change a rule and the test tells you to
  change the briefing. Bump `VERSION` to make everyone read it again.
- Human check for AVR-27: `games/bluff/PLAYTEST-BRIEFING.md`.

## Known limitations

- **One table per server** (one BLUFF room). The game lives in memory, so a server restart
  loses it.
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
