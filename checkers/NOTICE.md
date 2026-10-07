# Checkers: notice and attribution

`checkers/` is a native Avrana game process. It is not a module of the LAN Games fork, but its
rules come from the fork's Checkers.

## What is adapted, and from where

`checkers/rules.py` is adapted from [`games/checkers/engine.py`](../games/checkers/engine.py)
in this repository: its lines 1 to 248, which are the module docstring that states the rules of
American checkers (lines 1 to 38) and the engine itself (lines 40 to 248). The engine's bots, which
follow them in that file, are not carried. The engine is part of **LAN Games** by **BEACNpool**
(https://github.com/BEACNpool/LAN-Games; upstream retired in September 2026), MIT licensed,
(c) 2026 BEACNpool, like every file in `games/checkers/`.

What changed in the adaptation, and nothing else:

- the house-rule toggle is gone: a capture is always compulsory;
- `moves_for(board, side)` exposes the move generator on a bare board;
- `is_capture`, `opponent` and `count_pieces` are public;
- the module docstring is reworded where the toggle is gone, and says where the code came from.

`tests/test_checkers_rules.py` ports the fork's rules tests (its bot tests are not carried) and, for
as long as the fork's engine exists, compares the two over seeded playouts.

## Everything else

The session, the server, the Party boundary helpers, the page, the rules content
(`web/onboarding.json`) and the icon (`web/icon.svg`, simple geometry drawn by hand) are new work
by Avrana Party Games, (c) 2026 Avrana Party Games, offered under the same MIT terms: see
[`LICENSE`](../LICENSE) and the repository's [`NOTICE.md`](../NOTICE.md), which this file
extends and does not replace.

No third-party code, font, image or sound is bundled in `checkers/`. The two Party protocol files
it imports (`core/party_protocol.py`, `core/party_result.py`) are vendored unchanged from
avrana-party and are described in [`provider/README.md`](../provider/README.md).
