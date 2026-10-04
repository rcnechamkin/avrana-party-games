# EXPO (working title)

A rules-enforced cooperative trick-taking card game for two to five players, served at
`/games/expo/` (slug and Party contract id `expo`). EXPO is an internal working name; the game's
public identity is undecided. It adapts a published card game; the sources are identified in
[docs/VTT_REFERENCE.md](docs/VTT_REFERENCE.md) and are not part of this repository.

This file is the entry point and the implementation-status summary. The design record is in
[`docs/`](docs/RULES_SPEC.md).

## Read this first

EXPO was implemented and merged before its specification was reviewed (Linear AVR-215). The
specification and a full audit of the code against it were written afterwards. **Do not treat the
code as the definition of the game.** Where the code and the documents disagree, the disagreement
is listed in the reconciliation with a class (match, policy, defect, ambiguity, stale
specification, deferred) and an issue.

| Question | Document |
|---|---|
| What is the game supposed to do, and which source says so? | [RULES_SPEC](docs/RULES_SPEC.md) (base rules), [MISSION_MODEL](docs/MISSION_MODEL.md) (missions, tasks, modifiers) |
| What exactly may a player do, when, and how is it refused? | [ACTIONS](docs/ACTIONS.md) |
| What state exists, who sees what, how do reconnect and restart work? | [GAME_STATE](docs/GAME_STATE.md) |
| Which sources were used, what came from the reference implementation, what is unresolved? | [VTT_REFERENCE](docs/VTT_REFERENCE.md) (pins, reuse and rewrite, conflict register C01 to C20, task catalog) |
| Is the code right? Where is it wrong? What does the owner still have to decide? | [RECONCILIATION](docs/RECONCILIATION.md) |
| Which tests prove each rule, and what should be built next? | [IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md) |

## Status on 2026-10-04

**Playable.** Two to five humans; two humans play with a captain-controlled dummy hand (Tonoja).
24 of the 32 numbered missions and a continuation (33 to 50) are enabled for three to five
players; two players get all of them except the volunteer mission (16), and no distress. 92 of 96
tasks are enabled.

**Verified against the sources.** Deal, captain, turn order, following suit, submarines, trick
resolution, truthful communication and its timing, task drawing, selection and passing, task
evaluation, mission results, distress, the two-player variant, and the modifiers of the enabled
missions.

**Known defects** (each pinned by a strict expected-failure test in
`tests/test_expo_contract.py` or `tests/test_expo_coverage.py` where one can be written):

| | Defect | Issue |
|---|---|---|
| E-D2 | A table cannot be ended while a seated player is away; a standalone table can be stranded until the server restarts | AVR-240 |
| E-D8 | Six unavailable-control reasons differ from the server's rejection; the server refuses each request | AVR-263 |

Fixed: E-D1, the task-selection stall when the captain was the only seat left for a
captain-comparison task (AVR-239, 2026-10-04). E-D3 and E-D4, late completion of the "win none of
the first N tricks" tasks and the communicator not seeing their own declaration in currents
(AVR-241, 2026-10-04). E-D5 and E-D7, the content hash now covers every mission definition and a
timed mission runs on the monotonic clock and never gains time across a restart (AVR-242,
2026-10-04). E-D6, request memory, was settled by amending the contract: accepted requests only.
E-D9, a malformed crew decision that froze the table: every field of a crew decision is now
checked for its type before anything is stored (AVR-264, 2026-10-04). E-D10, a task dealt twice
in a mission played after mission 32: a task card is now in one place at a time (AVR-265,
2026-10-04). E-D11, a request id that could not be written to the snapshot file and stopped the
table: a request id is plain printable text, and a snapshot that cannot be written is a failed
write like any other (AVR-268, 2026-10-04).

**Owner decisions, built.** The owner answered the open policy questions on 2026-10-04 under a
"fidelity first" principle (AVR-243). The four answers that change behaviour are built: a single
card of a color is communicated only as "only" (AVR-248), the task `5with7` is enabled (AVR-249),
two players share one sonar token in the shared-sonar and unfamiliar-terrain missions (AVR-250),
and in missions 10 and 13 the captain decides and only the recipient consents (AVR-251).

**Waiting on the owner.** The rule for routine progression decisions: AVR-252, tied to AVR-240.
Party-round setup: AVR-245. Presentation contract: AVR-246.

**Blocked on source material.** Missions 3, 4, 12, 14, 15, 19, 20, 26 and tasks
`moreRedThanGreen`, `moreYellowThanBlue`, `4with8`, `6with6`: AVR-244. With two
players, distress, volunteer missions and shared-sonar or terrain missions are refused.

**Not done.** No deployment, no appliance key, no real-phone acceptance. No TV view, bots or
presentation events.

## Code map

| File | Responsibility |
|---|---|
| `rules.py` | the 40 cards, legal cards, trick winner, truthful declarations |
| `content.py`, `content/tasks.json` | mission and task definitions, blocked content, content hash |
| `tasks.py` | task status from resolved tricks |
| `engine.py` | authoritative state, command validation, transitions, per-viewer views, snapshots |
| `game.py` | platform adapter: seats, lobby settings, timer tick, presence, optional snapshot file, Party outcome |
| `storage.py` | atomic single-file snapshot store |
| `web/` | client: draws the view it is sent and sends intentions |

Shared files EXPO touches: `games/registry.py` (its entry), `core/party_session.py` (`expo` in
`GAMES`), `ops/export_avrana_catalog.py` (`FIRST_PARTY`), `provider/` (catalog and contract). No
session, networking or protocol code is EXPO-specific.

## Running

From the repository root, on a development port (never the live service):

```powershell
$env:LANGAMES_PORT='8196'
.venv\Scripts\python.exe server.py
```

Open `/games/expo/`. A table lives in memory and survives reloads and disconnects while the
process runs. For restart recovery of a standalone table set `EXPO_SNAPSHOT_PATH` to a **private,
non-served** JSON file before starting; it contains hidden hands, the random state and reconnect
credentials and must never be committed. Details and limits:
[GAME_STATE](docs/GAME_STATE.md#restoration-after-a-server-restart).

With an `expo.key` in `$AVRANA_PARTY_KEYS` the server admits signed Party rosters and tickets for
EXPO (`core/party_session.py`); without one it runs standalone. Key provisioning and deployment
are owner operations.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/test_expo.py tests/test_expo_party.py tests/test_expo_contract.py tests/test_expo_docs.py -q
$env:EXPO_HUMANS='3'   # 2 to 5
node tests/playtest_expo.mjs http://127.0.0.1:8196
```

| File | What it proves |
|---|---|
| `tests/test_expo.py` | rules, every enabled task (one success and one failure fixture), privacy, snapshots, adapter lifecycle |
| `tests/test_expo_party.py` | Party roster seating, ticket reconnect, spectators, outcome vocabulary |
| `tests/test_expo_contract.py` | rules that had no direct test before the reconciliation, and the pinned defects |
| `tests/test_expo_docs.py` | the mission table, task catalog, conflict codes and cited tests in `docs/` equal the code |
| `tests/playtest_expo.mjs` | browser playtest, run by hand |

The rule-to-test matrix, with what is still thin, is in
[IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md#deterministic-test-matrix). The exact runs
recorded for the reconciliation are in
[RECONCILIATION](docs/RECONCILIATION.md#implementation-report).

## Changing EXPO

Start from the Linear issue. A rule change goes into the specification with its source first, then
the code, then the tests, in one pull request. Fixing a pinned defect removes its `xfail` marker
and updates the reconciliation. Enabling blocked content needs source evidence or a recorded owner
ruling. See
[IMPLEMENTATION_PLAN](docs/IMPLEMENTATION_PLAN.md#rules-for-changing-expo-from-here).
