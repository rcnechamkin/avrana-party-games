# Avrana Party Games: agent and contributor entry point

This repository holds the browser game servers (LAN Games titles and BLUFF) that run under
[Avrana Party](https://github.com/rcnechamkin/avrana-party). It is the deployed game runtime
today and is retiring as one: Party
[ADR 0014](https://github.com/rcnechamkin/avrana-party/blob/main/docs/adr/0014-native-games-isolated-lan-games-retired.md)
keeps it as donor and reference code and moves native games to isolated processes (accepted,
not implemented). This file routes you to the authoritative material; it does not repeat it. The development loop for both repositories is Party's
[WORKFLOW](https://github.com/rcnechamkin/avrana-party/blob/main/docs/WORKFLOW.md).
`CLAUDE.md` and `CODEX-HANDOFF.md` add environment notes only.

## Authority

Highest first; each source answers its own question.

| Question | Source of truth |
|---|---|
| What is implemented | code and tests on GitHub `main` here (games) and in Party (platform) |
| Platform architecture, contracts, decisions | Party's canonical docs and [ADRs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/adr) (0005–0011 for provider launch, sessions, navigation, Play/Watch, the console model as implemented; 0012–0014 for accepted direction that is not implemented: Limited Mode, separate Party and game origins, isolated native games) |
| How to maintain or change an existing game here | [ADDING_A_GAME](ADDING_A_GAME.md) (upstream guide) and [provider/README](provider/README.md) (Avrana rules, which win where they differ) |
| How to build a new Avrana-native game | not as a module here: ADR 0014 and Party's [add-a-game runbook](https://github.com/rcnechamkin/avrana-party/blob/main/docs/runbooks/add-a-game.md). The native path is not built yet; take scope from the Linear issue |
| What should change now, acceptance, ownership | the AVR issue in [Linear](https://linear.app/avranakern) |
| What is running on the Pi | Party's `/party/api/status` and deployment manifest; Party's SYSTEM summarizes |
| Party ↔ Games interface | [`provider/avrana-contract.json`](provider/avrana-contract.json) (what this server requires) and Party's [PARTY-GAMES-CONTRACT](https://github.com/rcnechamkin/avrana-party/blob/main/docs/design/PARTY-GAMES-CONTRACT.md) |
| Document classification | [docs/manifest.json](docs/manifest.json) (`ops/check_docs.py`) |

Old handoffs, sprint notes and dated deployment remarks in this repository are history, never
instructions. A merge is not a deployment. Simulated browsers do not prove real phones.

## Starting work

Given `Implement AVR-N`:

1. Read the Linear issue: Outcome, Acceptance Criteria, Out of Scope, Repositories, Tests
   Required, Dependencies, Open Decisions. An unresolved Open Decision means stop and ask.
2. Read the game or module the issue touches and its tests first; then the provider docs and the
   Party ADRs they cite. [Graphify](docs/GRAPHIFY.md) is navigation only; verify what it returns.
3. Decide whether Party must change too (identity, presence, navigation, session protocol, catalog
   snapshot, launch integration are Party-owned). If so, pair branches with the same `avr-N`
   ([CROSS-REPO](https://github.com/rcnechamkin/avrana-party/blob/main/docs/CROSS-REPO.md)).
4. Name the tests that will prove the change before editing.
5. Branch from fetched `origin/main` as `type/avr-N-short-description`.

## Worktrees and claims

Issue work happens in a dedicated worktree claimed through
[AI-workflow](https://github.com/rcnechamkin/AI-workflow), checked out beside this repository:
`python ../AI-workflow/aw.py start AVR-N` checks readiness, finds or creates the worktree from
`origin/main` and claims it for your session; `claim`, `handoff`, `release` and `status` manage it
afterwards. Live Linear data comes from your agent's Linear connector, piped to `start` (its README
shows how). Do not edit or commit in a worktree another session has claimed. Local commit hooks
check this: today they warn, and they will refuse once enforcement is switched on; the message
names the owner and the way out. Workflow state is never committed here.

## Safety

Never, unless the task explicitly authorizes it in writing:

- merge a PR, force-push, rewrite history, or use/push `abandoned/classic-diplomacy`;
- deploy, restart or edit anything on the Pi (no `sudo`, no production checkout changes);
- change the vendored protocol (`core/party_protocol.py`, `tests/vectors/`) by hand: re-vendor
  from Party and update `provider/avrana-contract.json` together, on paired branches;
- add a parallel identity, roster, chat, library, navigation or durable results/history store:
  Party owns them; games never receive device identity, and a game reports results rather than
  keeping the platform's record;
- start a new Avrana-native title as a LAN Games module, or design new work around standalone
  LAN Games play, `wc-token` admission or a browser origin shared with Party, unless the Linear
  issue says so explicitly (ADRs 0013/0014);
- regenerate `provider/catalog.json` without copying the reviewed export to Party's
  `contracts/catalogs/lan-games.json` in the paired PR;
- commit secrets, `venue.json`, runtime data, ROMs, private Linear exports, machine paths or
  personal data (the privacy gate is CI's, not a substitute for looking).

## Derived context (Graphify)

[Graphify](docs/GRAPHIFY.md) is derived navigation, never a source of truth. Before a broad
search, run `python ops/graphify_context.py ensure --architecture` and a scoped
`python ops/graphify_context.py query "question" --architecture`, then verify the cited source,
tests and canonical docs. Linear owns live work; generated snapshots older than six hours are
stale; inferred edges are hypotheses. Never edit generated graphs or receipts.

## Completion

Done means all of:

- the requested behavior is implemented and nothing out of scope changed;
- tests added or updated; locally `python tests/test_no_private_data.py`,
  `python ops/export_avrana_catalog.py --check provider/catalog.json`, `python ops/check_docs.py`,
  `python -m pytest -q` and `npm run check:syntax` pass, and with a Party checkout
  `AVRANA_PARTY_REPO=../avrana-party python -m pytest -q tests/test_party_session_cross_repo.py tests/test_avrana_contract.py`;
- Linux CI including the `cross-repo` job is expected to pass;
- Party compatibility handled: paired PR, or "Party unaffected because ...";
- `provider/README.md` and the manifest updated when behavior changed;
- the implementation report (Party's
  [format](https://github.com/rcnechamkin/avrana-party/blob/main/docs/agents/IMPLEMENTATION-REPORT.md))
  is in the PR and the final message; the issue is In Review, not Done, while review, CI or phones remain.

## Cross-repo behavior

CI checks out the Party branch carrying the same `avr-N` (else `main`), runs Party's
`tools/contract_check.py` on both declarations and the real Party service against this server
(`tests/test_party_session_cross_repo.py`, which fails rather than skips in CI). Party merges
first unless the change is Games-only and backwards-compatible.

## Deployment

Humans deploy, from the Party repository: `ops/deploy.sh --party <sha> --games <sha>`
([runbook](https://github.com/rcnechamkin/avrana-party/blob/main/docs/runbooks/deploy.md)); the
Games commit reaches the Pi as a bundle ([games-fork-deploy](https://github.com/rcnechamkin/avrana-party/blob/main/docs/runbooks/games-fork-deploy.md)).
`ops/deploy.sh` in this repository is the upstream rsync tool, not the appliance path.
