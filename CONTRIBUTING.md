# Contributing to Avrana Party Games

Read [AGENTS](AGENTS.md) for authority, safety and completion rules, [README](README.md) for
setup, and [provider docs](provider/README.md) for the Avrana integration. The end-to-end loop
(Linear issue → paired branches → PR → CI → merge → deploy → playtest) is Party's
[WORKFLOW](https://github.com/rcnechamkin/avrana-party/blob/main/docs/WORKFLOW.md). Linear owns
live work. Read the relevant
[Party ADRs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/adr) before changing a
contract; the boundary itself is declared in `provider/avrana-contract.json` and checked by CI.
Use an issue-scoped `type/avr-N-description` branch, preserve unrelated work, and submit a PR
ending with the implementation report. Deployment and physical appliance tests need separate
owner authorization.

Use [Graphify](docs/GRAPHIFY.md) for broad code navigation when useful; verify the original
sources. Run freshness checks first. Missing or stale semantic context is an explicit limitation,
never a reason to reinterpret a canonical decision. CI uses local AST extraction and needs no
model API credential.

Install `requirements-dev.txt` and the npm lockfile, then run the privacy gate, the provider
snapshot check, `python ops/check_docs.py`, pytest and the static checks listed in AGENTS. With a
sibling Party checkout (or `AVRANA_PARTY_REPO`), also run the cross-repository tests; CI requires
them. Every Markdown file needs an entry in [docs/manifest.json](docs/manifest.json).
Private read-only Linear snapshots, caches and machine-specific outputs must remain ignored.
Never hand-edit generated semantic graphs/receipts; refresh and review them together.
