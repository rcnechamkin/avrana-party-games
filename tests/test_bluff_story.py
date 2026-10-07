"""BLUFF's table tells what just happened from the public log (AVR-313).

games/bluff/web/client.js reads the log the server sends. It finds the line that opens an action (a
marker in OPENERS) and shows that line and every line after it beside the claimed card; it takes
the role of the last claim or block from two phrases. Those phrases are written by game.py, so
these tests play the real BluffSession and fail when the two drift apart: change the log wording
and the client's reading together.

tests/bluff_layout_test.mjs checks the other half in a browser: what the page shows equals the
session's own lines.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bluff_states as helper  # noqa: E402  (plays the real BluffSession)

WEB = Path(__file__).resolve().parents[1] / "games" / "bluff" / "web"
SRC = (WEB / "client.js").read_text(encoding="utf-8")

_m = re.search(r"const OPENERS = (\[.*?\]);", SRC)
assert _m, "client.js must keep `const OPENERS = [...];` on one line"
OPENERS = json.loads(_m.group(1))

# the two phrases story() reads a role from, exactly as client.js writes them
_PHRASES = re.findall(r"line\.match\(/(.+?)/\)", SRC)
assert len(_PHRASES) == 2, "story() reads the claimed role from two phrases"
BLOCK_PHRASE, CLAIM_PHRASE = (re.compile(p) for p in _PHRASES)
assert "blocks, claiming" in BLOCK_PHRASE.pattern and " claims " in CLAIM_PHRASE.pattern

A, B, C = helper.A, helper.B, helper.C


def is_opener(line):
    return any(marker in line for marker in OPENERS)


def _started(coins=None):
    s = helper.table(3)
    helper.rig(s, A, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"], C: ["Broker", "Guardian"]},
               coins or {A: 8, B: 3, C: 3})
    return s, len(s.g["log"])


def test_the_first_line_of_a_game_opens_the_story():
    s = helper.table(3)
    assert s.g["log"] and is_opener(s.g["log"][0]), s.g["log"][:1]


# (action, target) -> the role the claim names, or None for a move that claims nothing
ACTIONS = [
    ("income", None, None),
    ("aid", None, None),
    ("coup", B, None),
    ("tax", None, "Banker"),
    ("steal", B, "Smuggler"),
    ("strike", B, "Agent"),
    ("exchange", None, "Broker"),
]


@pytest.mark.parametrize("action,target,role", ACTIONS)
def test_each_action_opens_with_a_marker_the_client_knows(action, target, role):
    s, since = _started()
    helper.act(s, A, action, target)
    first = s.g["log"][since]
    assert is_opener(first), "client.js OPENERS does not know how game.py starts %s: %r" % (action, first)
    claim = CLAIM_PHRASE.search(first)
    if role:
        assert claim and claim.group(1) == role, "the claim phrase no longer finds %s in %r" % (role, first)
    else:
        assert not claim, first


def test_a_block_is_a_claim_the_client_can_read():
    s, since = _started()
    helper.act(s, A, "aid")
    helper.respond(s, B, "block", role="Banker")
    lines = s.g["log"][since:]
    blocks = [ln for ln in lines if BLOCK_PHRASE.search(ln)]
    assert len(blocks) == 1, lines
    assert BLOCK_PHRASE.search(blocks[0]).group(1) == "Banker"
    # the block is a continuation of the action, never a new story
    assert not is_opener(blocks[0]), blocks[0]


def test_only_the_first_line_of_an_action_is_an_opener():
    """The client shows the log from the LAST opener on: a later line that looks like one would cut the story."""
    chains = [(name, sc["chain"]) for name, sc in helper.build().items() if sc["chain"]]
    assert len(chains) >= 15
    for name, chain in chains:
        starts = [i for i, ln in enumerate(chain) if is_opener(ln)]
        assert starts == [0], "%s: openers at %s in %r" % (name, starts, chain)


def test_a_slow_turn_leads_into_its_forced_move():
    """client.js adds the "took too long" line that comes just before the move it forced."""
    s, since = _started({A: 2, B: 3, C: 3})
    s.game_tick()
    lines = s.g["log"][since:]
    assert lines[0].startswith("⏱"), lines
    assert is_opener(lines[1]), lines
    assert 'startsWith("⏱")' in SRC


def test_the_story_window_is_what_the_table_shows():
    """The client takes the last 15 log lines the server sends (state_for): a story is never longer."""
    s, since = _started()
    helper.act(s, A, "steal", B)
    log = helper.view(s, A)["game"]["log"]
    assert log and log == s.g["log"][-len(log):]
    assert len(log) <= 15
