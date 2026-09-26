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
Checkpoint: metadata exporter/catalog/contract docs committed at febd546. Integration changes and tests committed at ce13795; final navigation checks/doc status pending. No production changes.
Tests: donor Python 1200 passed; provider worker Node 3 passed; metadata drift check passed. Cross-repo Chromium checks passed 10 including all-title geometry and standalone alias coverage. Prior platform baseline CI passed.
Canonical remote established privately: https://github.com/rcnechamkin/avrana-party-games. Existing main 2cf4831 published; no experimental refs. Historical branding/paths retained privately; no credential/private-key scan matches.
Next: push reviewed feature branch, open donor PR and verify Linux CI including rsync release-safety. Platform depends on advertised version. No merge/deploy. Preserve no merge/deploy.
Dependency: donor first, standalone backward compatible; platform activation
requires version advertisement. Party Home and abandoned Diplomacy untouched.

## Closing checkpoint

Implementation complete, review only. Donor PR:
https://github.com/rcnechamkin/avrana-party-games/pull/1
Platform PR (second): https://github.com/rcnechamkin/avrana-party/pull/7
Linux CI run 36261284527 SUCCESS: 1200 Python, privacy, metadata drift, syntax,
worker3 and release-safety. Platform run 36261333271 SUCCESS including real nginx.
Final combined browser suite12 passed. Final standalone unknown/future ID
preservation test2 passed: normalize only known registry titles, never rewrite an
unknown canonical ID when editing other favorites. Final checkpoint reruns CI;
current PR head checks are authoritative before review/merge.
Current uncommitted state: this closing checkpoint; after commit/push tree clean.
Unresolved code failures: none. Real phone/Pi/game-control/TV acceptance pending
owner release; historical origin separation, token auth and session roster remain
known architectural debt. No Party Home, experiment, networking or production edits.
Exact next action: owner review donor first, platform second, check CI, then plan
separate approved deployment/hardware checks. Do not merge/deploy autonomously.
