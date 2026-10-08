# Native Checkers sprint follow-up (2026-10-07)

New evidence following Games PR #54 at a3d381f. This does not revise the earlier
[findings](2026-10-07-checkers-native-findings.md), freeze an SDK, or describe deployment.
Games main c768864 was merged preserving the PR history and unrelated work.

## Idle lifecycle

Party ADR 0016 section 4 requires socket-activated games to stop when idle. Checkers now exits
successfully after 60 seconds without an authoritative session, once pending result delivery
finishes. The interval starts at process construction, refused launch, Host End or completion.
This is a game-local field-test choice; no provisioning or SDK convention was added.

An active match never expires because phones disconnected. D6's unlimited turn/reconnect wait
remains. Finished-board reads do not keep a completed process resident forever. Party owns the
accepted result and its bridge's results choices. A subsequent launch uses existing socket
activation. A launch racing with committed idle shutdown receives 503 to retry rather than a
false successful launch. Clean return closes the game's inherited listener; systemd retains
its listener. Pending result-reporting threads prevent exit.

Tests cover real HTTP-server clean exit, active matches, pending delivery and racing launches.
Linux subprocess tests retain the listening socket in the parent, prove initial/completed idle
exit, restart on the same socket, launch a fresh session and reject the prior token. These are
socket-activation simulations; Party's real-systemd proof remains a separate gate.

## Load, origin and build

A real HTTP test holds 32 simultaneous long polls, refuses overflow, accepts a move and checks
all 32 waiters receive the changed board and release their slots. This development-host proof
is not Raspberry Pi capacity measurement.

Bare Party origins accept bracketed IPv6 literals using standard-library address validation,
without DNS. Invalid addresses, credentials, paths, queries, fragments and ports outside
1?65535 are refused. Named-host and IPv4 origins remain supported.
The manually maintained result build identifier advances to `checkers-0.1.1`. Durable package
versioning still belongs to AVR-37/AVR-38.

## Validation boundaries

Commands:

```text
python -m pytest -q -p no:cacheprovider tests/test_checkers_rules.py tests/test_checkers_session.py tests/test_checkers_process.py tests/test_checkers_web.py
python -m pytest -q -p no:cacheprovider tests/test_checkers_process.py -k "idle or default_32 or ipv6 or invalid_ipv6 or pending_result"
node tests/checkers_board_test.mjs
```

The final PR/report carries final-head counts. Windows skips four Unix-process tests. Real
systemd, the paired Party launch/browser path, result display, Linux regression CI and physical
iPhone/Android evidence remain separate gates. AVR-261 owns physical acceptance. No Pi operation,
merge, SDK implementation or `.avrgame` freeze was performed.
