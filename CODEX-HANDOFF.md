# Provider integration sprint continuation

Goal: browser games run beneath the canonical Avrana shell. No merge/deploy.
Repository: avrana-party-games; branch fix/avrana-provider-integration.
Starting main: 2cf4831064de709feeb31865c5022a3f048e49ef.
Companion platform branch: fix/lan-games-providerization, base 459d4cd.
Completed: local isolated clone; concrete audit in platform
 docs/design/LAN-GAMES-PROVIDER.md; deterministic exporter begun.
Decision: avrana.lan-launch/v1 advertised by /api/games; URL avrana=1 is
non-secret, reload-safe context. Same-origin fixed /party/ return. Preserve
wc-* identity and lg-* library backing stores; one chat transport; no roster.
Checkpoint: metadata exporter/catalog/contract docs committed at febd546. Integration changes and tests remain uncommitted. No production changes.
Tests: donor Python 1200 passed; provider worker Node 3 passed; metadata drift check passed. Cross-repo Chromium checks passed 8 before expanding standalone alias/layout coverage. Prior platform baseline CI passed.
Canonical remote established privately: https://github.com/rcnechamkin/avrana-party-games. Existing main 2cf4831 published; no experimental refs. Historical branding/paths retained privately; no credential/private-key scan matches.
Next: finish all-title game-room geometry and standalone library tests, review/commit integration, run static/CI suites, push feature branch and open coordinated PR. Preserve no merge/deploy.
Dependency: donor first, standalone backward compatible; platform activation
requires version advertisement. Party Home and abandoned Diplomacy untouched.
