# Avrana Party Games: agent and contributor entry point

This repository holds the browser game servers (LAN Games titles and BLUFF) that run under
[Avrana Party](https://github.com/rcnechamkin/avrana-party). It routes you to the authoritative
material; it does not repeat it. The development loop for both repositories is Party's
[WORKFLOW](https://github.com/rcnechamkin/avrana-party/blob/main/docs/WORKFLOW.md).
`CLAUDE.md` and `CODEX-HANDOFF.md` add environment notes only.

## Authority

Highest first; each source answers its own question.

| Question | Source of truth |
|---|---|
| What is implemented | code and tests on GitHub `main` here (games) and in Party (platform) |
| Platform architecture, contracts, decisions | Party's canonical docs and [ADRs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/adr) (0005–0011 for provider launch, sessions, navigation, Play/Watch, the console model) |
| How to add or change a game | [ADDING_A_GAME](ADDING_A_GAME.md) (upstream guide) and [provider/README](provider/README.md) (Avrana rules, which win where they differ) |
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

## Safety

Never, unless the task explicitly authorizes it in writing:

- merge a PR, force-push, rewrite history, or use/push `abandoned/classic-diplomacy`;
- deploy, restart or edit anything on the Pi (no `sudo`, no production checkout changes);
- change the vendored protocol (`core/party_protocol.py`, `tests/vectors/`) by hand: re-vendor
  from Party and update `provider/avrana-contract.json` together, on paired branches;
- add a parallel identity, roster, chat, library or navigation store: Party owns them; games never
  receive device identity;
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
