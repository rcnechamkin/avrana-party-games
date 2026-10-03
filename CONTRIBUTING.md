# Contributing to Avrana Party Games

Read [AGENTS](AGENTS.md) for authority and operational boundaries, [README](README.md) for setup,
and [provider docs](provider/README.md) for integration. Linear owns live work. Read the relevant
[Party ADRs](https://github.com/rcnechamkin/avrana-party/tree/main/docs/adr) before changing contracts.
Use an issue-scoped branch, preserve unrelated work, and submit a PR with scope and test evidence.
Deployment and physical appliance tests need separate owner authorization.

Use [Graphify](docs/GRAPHIFY.md) for broad code navigation when useful; verify the original sources.
Run freshness checks first. Missing or stale semantic context is an explicit limitation, never a
reason to reinterpret a canonical decision. Use interactive host-agent Graphify for documentation
semantics; CI uses local AST extraction and needs no model API credential.

Install existing requirements and npm lockfile dependencies, then run the privacy gate, provider
snapshot check, pytest and static checks listed in AGENTS and the existing CI workflow.
The shared Graphify fixture tests live in Party; Games' CI checks out their immutable pinned commit.
Run `python ops/graphify_context.py check-config` locally after bootstrapping that toolkit.
Private read-only Linear snapshots, caches and machine-specific outputs must remain ignored.
Never hand-edit generated semantic graphs/receipts; refresh and review them together.
