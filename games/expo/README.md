# EXPO (working title)

Playable Avrana Games module at `/games/expo/`, registered as **EXPO** (slug `expo`, Party contract id `expo`). EXPO is an internal working name for a cooperative trick-taking card game; its public identity will be decided later. The six design specifications it was built from are internal development documentation kept outside version control (gitignored under `games/`), not part of this public repository.

## Implemented

- Two to five humans; two humans use captain-controlled Tonoja with 13 cards per human, 14 Tonoja cards and 13 tricks.
- Authoritative dealing, captain, clockwise turns, follow suit, submarines, trick resolution, truthful sonar and task ownership. Losing legal plays remain legal.
- Typed task evaluators, mission modifiers, secret predictions, sealed distress passes, crew agreement, retries, expedition progression and timed mission 16.
- Private player projections, public spectators, latest-trick review, responsive phone controls, stable reconnects and optional server-restart snapshots.

The engine is synchronous and independent of UI, network and filesystem. `rules.py` contains immutable card rules; `content.py` composes mission modifiers; `tasks.py` evaluates structured definitions. `engine.py` accepts authenticated actor IDs, injected RNG and supplied time. It rejects forged, stale and illegal commands transactionally, checks card conservation and deduplicates requests. The browser only renders projections and requests actions. No shared core files changed.

## Content boundaries and source decisions

The supplied rulebook has priority over the supplied mission transcription and pinned VTT snapshots. See the specification conflict register; no disputed content was silently adopted. The rulebook's two-player deal was visually checked after text extraction corrupted its numeral: **13/13/14**, not 12/12/14.

`content/tasks.json` records all 96 pinned VTT task IDs, player-count difficulties, source attribution and explicit predicates. 91 are enabled. Five remain quarantined: `moreRedThanGreen`, `moreYellowThanBlue`, `4with8`, `5with7`, `6with6`. This is a reviewed VTT-derived task catalog, not a claim that all official task faces were independently supplied and verified.

Missions 3, 4, 12, 14, 15, 19, 20 and 26 remain disabled with visible conflict reasons. The other 24 numbered missions and 18 continuation challenges (33–50) are enabled for three to five humans. Shared-sonar, terrain and volunteer missions are additionally unavailable with Tonoja until that interpretation is settled. Mission 27 requires yellow 5 as the final played card; leaving it as the surplus card fails. Mission 32 has four fixed tasks.

Explicit digital policies: truthful singleton cards may use highest, lowest or only; predictions lock before the unanimous start; the timed deadline starts on that agreement and keeps running during disconnects; non-timed missions pause actions while a seated human is away; task generation retries bounded private permutations and replenishes the used deck when its remaining difficulties cannot reach the target. Structurally conflicting fixed trick tasks forced onto separate owners are replaced at equal difficulty. Impossible volunteer ownership ends a counted attempt visibly. These policies are recorded rather than inferred from client behavior.

VTT card/task identities and difficulty data were transformed into structured content. VTT widget coordinates, drag/drop, routines, manual status toggles and its UI state were rewritten. This client uses original CSS card visuals with suit symbols and labels; no VTT artwork is bundled into the public game.

## Running and restoration

Run the existing games server from the repository root, then open `/games/expo/`. For a local port override in PowerShell:

```powershell
$env:LANGAMES_PORT='8196'
.venv\Scripts\python.exe server.py
```

The default preserves tables across browser reloads and temporary disconnects while the process remains alive. For durable standalone tables, set `EXPO_SNAPSHOT_PATH` to a **private, non-web-served** JSON file before starting the server. It contains hands, RNG and reconnect credentials; do not expose or commit it. The separate `SnapshotStore` performs atomic replacement. The adapter's opt-in IO is an explicit persistence boundary, an exception to the normal IO-free session convention; the domain engine stays IO-free. Failed action saves roll back the action. Saved content versions must match; corrupt or incompatible saves block new tables instead of silently discarding them. Restored humans must reconnect with their original browser identities. Presence itself is ephemeral and all restored players begin away.

The Party catalog and explicit game contract advertise the donor route and private player UI. EXPO is listed in `core/party_session.GAMES`, so with an `expo.key` in `$AVRANA_PARTY_KEYS` it accepts signed Party rosters and tickets exactly like BLUFF (`core/party_session.py`); without a key it runs standalone. Appliance key provisioning and deployment are owner operations. Default process restart without the optional snapshot remains destructive to an in-memory table.

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

- Games repository: **1,480 tests passed**. Final targeted domain/provider run after the task-copy polish: **142 passed**. Provider metadata consistency and JavaScript syntax checks passed.
- Chrome: real missions with **2, 3, 4 and 5 humans**, masked frames, forged requests, reload and four viewport widths passed. The final three-human run additionally communicated a non-default sonar card and restored a partial trick.
- Party integration: **28 contract/assimilation tests** and **78 offline browser-module tests** passed. The full Party unit run encountered unrelated Windows emulator/process, symlink-privilege and shell/deployment failures; its catalog-count failure was fixed and the affected suite rerun successfully. This is not a claim that the complete Party suite passes on this Windows host.
- Visual review: two-player phone and five-player desktop screenshots inspected; no horizontal overflow at 360, 390, 820 or 1440 pixels. Local screenshots are under the ignored repository `test-results/expo-*` directories.
