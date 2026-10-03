# EXPO (working title)

Playable Avrana Games module at `/games/expo/`, registered as **EXPO** (slug `expo`, Party contract id `expo`). EXPO is an internal working name for a cooperative trick-taking card game; its public identity will be decided later. The six design specifications it was built from are internal development documentation kept outside version control (gitignored under `games/`), not part of this public repository.

## Implemented

- Two to five humans; two humans use captain-controlled Tonoja with 13 cards per human, 14 Tonoja cards and 13 tricks.
- Authoritative dealing, captain, clockwise turns, follow suit, submarines, trick resolution, truthful sonar and task ownership. Losing legal plays remain legal.
- Typed task evaluators, mission modifiers, secret predictions, sealed distress passes, crew agreement, retries, expedition progression and timed mission 16.
- Private player projections, public spectators, latest-trick review, responsive phone controls, stable reconnects and optional server-restart snapshots.

The engine is synchronous and independent of UI, network and filesystem. `rules.py` contains immutable card rules; `content.py` composes mission modifiers; `tasks.py` evaluates structured definitions. `engine.py` accepts authenticated actor IDs, injected RNG and supplied time. It rejects forged, stale and illegal commands transactionally, checks card conservation and deduplicates requests. The browser only renders projections and requests actions. Shared files touched: `games/registry.py` (the entry), `core/party_session.py` (`expo` added to `GAMES`) and `ops/export_avrana_catalog.py` (`FIRST_PARTY` ids). No session, networking or protocol code changed.

## Content boundaries and source decisions

The supplied rulebook has priority over the supplied mission transcription and pinned VTT snapshots. See the specification conflict register; no disputed content was silently adopted. The rulebook's two-player deal was visually checked after text extraction corrupted its numeral: **13/13/14**, not 12/12/14.

`content/tasks.json` records all 96 pinned VTT task IDs, player-count difficulties, source attribution and explicit predicates. 91 are enabled. Five remain quarantined: `moreRedThanGreen`, `moreYellowThanBlue`, `4with8`, `5with7`, `6with6`. This is a reviewed VTT-derived task catalog, not a claim that all official task faces were independently supplied and verified.

Missions 3, 4, 12, 14, 15, 19, 20 and 26 remain disabled with visible conflict reasons. The other 24 numbered missions and 18 continuation challenges (33–50) are enabled for three to five humans. Shared-sonar, terrain and volunteer missions are additionally unavailable with Tonoja until that interpretation is settled. Mission 27 requires yellow 5 as the final played card; leaving it as the surplus card fails. Mission 32 has four fixed tasks.

Explicit digital policies: truthful singleton cards may use highest, lowest or only; predictions lock before the unanimous start; the timed deadline starts on that agreement and keeps running during disconnects; non-timed missions pause actions while a seated human is away; task generation retries bounded private permutations and replenishes the used deck when its remaining difficulties cannot reach the target. Structurally conflicting fixed trick tasks forced onto separate owners are replaced at equal difficulty. Impossible volunteer ownership ends a counted attempt visibly. A deal that puts a listed submarine combination in one hand for a selected submarine task (`black1`, `black2`, `1black`, `2black`, `3black`, `red7WithBlack`, `green9WithBlack`) is redealt before the attempt is counted. These policies are recorded rather than inferred from client behavior.

VTT card/task identities and difficulty data were transformed into structured content. VTT widget coordinates, drag/drop, routines, manual status toggles and its UI state were rewritten. This client uses original CSS card visuals with suit symbols and labels; no VTT artwork is bundled into the public game.

## Implementation against the specification

Reconciled 2026-10-02 against the internal design contracts (rules, state, actions, mission model, reference/conflict register C01–C19, plan). This section is the canonical statement of what the code does where it differs from, or goes beyond, those contracts. Nothing here resolves a source question.

**Vocabulary.** The specified wire verbs were a proposal; the engine accepts `choose_task`, `pass_task`, `volunteer`, `predict`, `pass_card`, `communicate`, `play_card`, and one generic crew decision (`propose` / `confirm`) for `begin`, `distress`, `assign`, `retry`, `next` and `end`. Engine phases are `allocation`, `prediction`, `assistance`, `passing`, `before_trick`, `in_trick`, `mission_result`, `closed`; setup and feasibility run inside mission preparation, and an ended table is `closed` with result `abandoned` unless a mission result already stood. Free allocation is confirmed one task at a time. There is no tutorial mission entry (mission 1 has the same target), no task-evidence view, and no acknowledgement action.

**Enabled under a disclosed digital policy although the register asks for confirmation first.** C10 (a singleton may be communicated as highest, lowest or only). C13 (mission 16 timed: the clock starts at the unanimous begin). C09 (bounded generation with automatic replenishment instead of a replenishment proposal). C18 (the task catalog is VTT-derived: `sumAbove` uses the reference's upper thresholds 23/28/31, and the submarine win-with and `trickWith*` tasks use the reference's orientation; only `4with8`, `5with7`, `6with6` are quarantined). Mission 8 is offered to two humans, with Tonoja counted in the rank-9 balance; the mission model says "when the mode is verified".

**Known gaps (not fixed here; each needs an owner decision, not a guess).**

1. *Forced captain-comparison task.* The captain may never own `lessTricksThanCaptain`, `equalTricksThanCaptain` or `moreTricksThanCaptain`. In clockwise selection the captain can still be the only seat left to take one: unavoidably when a three-seat table draws exactly those three tasks (difficulty 8, mission 11), and avoidably when one is left for the captain's second pick. The engine then rejects both the pick and the pass, and the only way forward is the crew's End table decision. The rules contract requires explicit feasibility handling here but the sources do not say which (replacement at equal difficulty, or a counted failure).
2. *Ending a table while a seat is away.* Every action, including the End table decision, is refused while a seated human is away. A standalone table whose player never returns stays reserved until the server restarts (a Party round is ended by the Party Host). The state contract expects "reconnect or explicit abandonment"; who may abandon an incomplete crew is an open digital policy.
3. *Late satisfaction.* `noneFirst3Tricks`, `noneFirst4Tricks` and `noneFirst5Tricks` stay pending until the final trick although they cannot fail after their window. Outcomes are unchanged; an otherwise early success waits for the last trick.
4. *Currents.* The assertion is hidden from every viewer including the communicator; the contract lets the communicator see their own.
5. *Persistence details.* Only accepted requests are remembered for de-duplication; the content hash covers `content/tasks.json` but not the mission table in `content.py` (an in-flight mission is still compared with its definition on every check); a timed restore trusts the wall clock and does not detect a clock rollback.
6. *Party rounds.* Settings are locked by the shared session layer, so a Party-launched table always opens on mission 1, untimed, with Tonoja after both players; later missions are chosen with the crew's Next decision.
7. *Presentation contracts.* The two draft presentation specifications (state-driven behaviour, mission gameplay UI/UX) are not implemented. The engine emits no presentation or causality events: a result is a status and a reason (a failed task reports its own text, not who triggered it), there is no separate "impossible" objective state, trick resolution is atomic, and a rejection carries a code and message only. The hard-legality boundary those drafts require does hold: legal losing plays are accepted and no pre-commit warning exists.

## Running and restoration

Run the existing games server from the repository root, then open `/games/expo/`. For a local port override in PowerShell:

```powershell
$env:LANGAMES_PORT='8196'
.venv\Scripts\python.exe server.py
```

The default preserves tables across browser reloads and temporary disconnects while the process remains alive. For durable standalone tables, set `EXPO_SNAPSHOT_PATH` to a **private, non-web-served** JSON file before starting the server. It contains hands, RNG and reconnect credentials; do not expose or commit it. The separate `SnapshotStore` performs atomic replacement. The adapter's opt-in IO is an explicit persistence boundary, an exception to the normal IO-free session convention; the domain engine stays IO-free. Failed action saves roll back the action. Saved content versions must match; corrupt or incompatible saves block new tables instead of silently discarding them. Restored humans must reconnect with their original browser identities. Presence itself is ephemeral and all restored players begin away.

The Party catalog and explicit game contract advertise the donor route and private player UI. EXPO is listed in `core/party_session.GAMES`, so with an `expo.key` in `$AVRANA_PARTY_KEYS` it accepts signed Party rosters and tickets exactly like BLUFF (`core/party_session.py`); without a key it runs standalone. Appliance key provisioning and deployment are owner operations. In a Party round the Party's roster is the table: the game's own lobby is skipped, Party spectators get the public view only, results are held until the Party Host moves on, and the opt-in standalone snapshot is neither restored into nor written by a Party room. Default process restart without the optional snapshot remains destructive to an in-memory table.

## Verification

`tests/test_expo.py` covers every enabled task with positive and negative deterministic fixtures, player-count deals, independent trick winner comparisons, communication timing/truth/privacy, legal-turn enforcement, modifier boundaries, hostile commands, task repair/replenishment, Tonoja, predictions, distress, timed expiry, snapshots and reconnects. Task evaluator fixtures isolate predicate behavior; the separate engine tests validate complete, legal histories and conservation.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_expo.py tests/test_avrana_provider.py -q
$env:CHROME_PATH='C:\Program Files\Google\Chrome\Application\chrome.exe'
$env:EXPO_HUMANS='2' # also 3, 4 or 5
node tests/playtest_expo.mjs http://127.0.0.1:8196
```

Browser testing uses independent contexts, task selection, a complete mission result, a forged request, hidden-hand checks, reload and screenshots at widths 360/390/820/1440. Start with an empty lobby. The browser test agrees to end its table afterward; shared lobby reset takes the platform's normal delay.

Release limitations: the quarantined content needs authoritative source clarification; no dedicated TV artwork or automated strategic bot is supplied; durable restoration is opt-in. Adversarial review focused on spectator writes, turn forgery, private projections, partial distress exchange, double spending, stale/replayed commands, forced allocations, all-away lifecycle, surplus-card objectives and storage failures.

### Verification recorded 2026-10-02

Recorded results for this branch live in its pull request (rcnechamkin/avrana-party-games#16), which is updated with each head; GitHub Actions (`.github/workflows/test.yml`) runs the privacy gate, catalog drift check, the full Python suite, static syntax, the shared-client tests and the release-safety script on every push. Locally, `tests/test_party_session_cross_repo.py` and one `tests/test_party_session.py` case compare the vendored Party protocol with a sibling `avrana-party` checkout and fail whenever that checkout is ahead of the vendored copy; they skip in CI.
