# Agent entry point — Avrana Party Games

Read [AGENTS](AGENTS.md) for shared invariants and derived Graphify guidance, and
[CONTRIBUTING](CONTRIBUTING.md) for the contributor workflow. This handoff adds no authority.

Start from current GitHub `main` and the current issue in
[Linear](https://linear.app/avranakern) for scope, sequencing, blockers, acceptance and ownership.
The former PR #1 providerization handoff is a historical sprint record in Git history; its next
actions and branch/review instructions are no longer authoritative.

The [Party repository](https://github.com/rcnechamkin/avrana-party) owns canonical platform
architecture and contracts. Read its [CLAUDE.md](https://github.com/rcnechamkin/avrana-party/blob/main/CLAUDE.md),
[SYSTEM](https://github.com/rcnechamkin/avrana-party/blob/main/docs/SYSTEM.md), relevant
[ADRs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/adr) (especially 0006–0011) and
[design docs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/design).

Party PR #34 and Games PR #13 are merged source for ADR 0011. Merged source may be ahead of
production: SYSTEM and dated Party findings own deployed revisions, and AVR-212 owns console-model
deployment and Tier 3 phone verification. Older deployment-status notes in Games docs are dated
sprint evidence; consult SYSTEM before treating them as current runtime status.

Use [README](README.md), [provider docs](provider/README.md), [BLUFF docs](games/bluff/README.md)
and the existing `tests/` and CI workflows for Games implementation and test commands. Party's
[TESTING](https://github.com/rcnechamkin/avrana-party/blob/main/docs/TESTING.md) documents the
cross-repository harness and evidence tiers. Automated browsers do not prove physical phones.

Work on an issue-scoped branch and open a PR. Never edit production game checkouts or runtime
data; deployment and service restarts require the owner's approval. Do not use or push
`abandoned/classic-diplomacy`.
