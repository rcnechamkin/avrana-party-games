# Avrana Party Games: shared agent invariants

Read [README](README.md), [contributor guide](CONTRIBUTING.md) and [provider documentation](provider/README.md).
Linear owns work, status, priorities, sequencing, blockers, acceptance and ownership.
Canonical GitHub documentation/ADRs own decisions and intended architecture; code/tests own
actual implementation. The [Party documentation](https://github.com/rcnechamkin/avrana-party/tree/main/docs)
owns cross-repository platform contracts. Read ADR status/amendments, especially 0006–0011.
A merge is not deployment evidence; Party SYSTEM/findings own verified deployments.

## Graphify is derived context only

Use [Graphify setup](docs/GRAPHIFY.md). Before broad repository searching or architecture questions,
run `python ops/graphify_context.py ensure --architecture` and a scoped
`python ops/graphify_context.py query "question" --architecture` where useful, then verify cited
source files/tests and canonical docs. Exact-file reads, focused debugging and targeted tests can
go directly to source. Graphify nodes/edges/reports and generated Linear snapshots never assign
work or override any source of truth. Inferred edges are hypotheses.

Check semantic freshness separately with `check-semantic`; stale/missing semantic output means
read canonical docs directly or refresh through the interactive host-agent Graphify skill.
Use the connected Linear app for live work. With a scoped read-only `LINEAR_API_KEY`, `refresh`
generates private work context; snapshots older than six hours are stale. Never edit generated
files or mark a receipt current by hand. No model API credential is required; CI extracts ASTs only.
Claude has a nonblocking search reminder; Codex uses these instructions, not a PreToolUse hook.

## Boundaries and verification

Work on a descriptive issue-scoped branch from current GitHub main. Preserve unrelated changes.
Games owns game implementation and provider integration; Party owns identity, presence, chat,
navigation and platform contracts. Do not add parallel platform stores/tokens. Preserve upstream
license/notices. Never use or push `abandoned/classic-diplomacy`.

Run existing CI checks: `python tests/test_no_private_data.py`,
`python ops/export_avrana_catalog.py --check provider/catalog.json`, `python -m pytest -q`,
and `npm run check:syntax` after installing the existing lockfile/dependencies.
Use Party TESTING for cross-repository evidence tiers; simulated browsers do not prove real phones.
Do not commit secrets, runtime data, private Linear exports, machine paths, ROMs, or raw telemetry.
No production checkout edits, deployment, service restart or appliance changes are authorized
by development instructions. Submit reviewable commits/PRs; do not merge or deploy without scope.
