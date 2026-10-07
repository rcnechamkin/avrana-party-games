"""BLUFF's table tells what just happened from the public log (AVR-313).

games/bluff/web/client.js reads the log the server sends. It finds the line that opens an action and
shows that line and every line after it beside the claimed card; it takes the role of the last claim
or block from two phrases. Those words are written by game.py, so these tests play the real
BluffSession and fail when the two drift apart: change the log wording and the client's reading
together.

A log line begins with the name of the player it is about, and a name is the player's own words (up
to 14 letters, digits, spaces and a few marks: " claims " can be one). So the client reads a line only
after a seat's name, never from anywhere in it, and these tests play a table with such a name.

tests/bluff_layout_test.mjs checks the other half in a browser: what the page shows equals the
session's own lines, including at that table.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bluff_states as helper  # noqa: E402  (plays the real BluffSession)
from games.bluff.game import ROLES  # noqa: E402  (the table's roles: the client reads a claim only for one of them)

WEB = Path(__file__).resolve().parents[1] / "games" / "bluff" / "web"
SRC = (WEB / "client.js").read_text(encoding="utf-8")

_m = re.search(r"const OPENERS = (\[.*?\]);", SRC)
assert _m, "client.js must keep a one-line: const OPENERS = [...];"
OPENERS = json.loads(_m.group(1))                   # what follows a name when a move opens a story
_m = re.search(r'const OPENING_LINE = ("[^"]*");', SRC)
assert _m, 'client.js must keep a one-line: const OPENING_LINE = "...";'
OPENING_LINE = json.loads(_m.group(1))              # the one line that has no name in front of it


def _phrase(const):
    found = re.search(r"const %s = /(.+?)/;" % const, SRC)
    assert found, "client.js must keep a one-line: const %s = /.../;" % const
    return re.compile(found.group(1))               # these two are valid in both languages


CLAIM_AT, BLOCK_AT = _phrase("CLAIM_AT"), _phrase("BLOCK_AT")
assert CLAIM_AT.pattern.startswith("^ claims ") and BLOCK_AT.pattern.startswith("^ blocks, claiming")

A, B, C = helper.A, helper.B, helper.C


def names_of(s):
    return [p.name for p in s.players.values()]


def after_names(line, names):
    """What is left of a line after each seat name it starts with (client.js afterNames)."""
    return [line[len(n):] for n in names if n and line.startswith(n)]


def claimed_role(line, names, phrase):
    """client.js roleIn: the role a claim or a block names after a seat's name, if it is one of the roles."""
    for rest in after_names(line, names):
        m = phrase.match(rest)
        if m and m.group(1) in ROLES:
            return m.group(1)
    return None


def is_opener(line, names):
    """client.js isOpener: the table's first line, or a seat's name followed by a move that opens one."""
    return line.startswith(OPENING_LINE) or any(
        rest.startswith(m) for rest in after_names(line, names) for m in OPENERS
    ) or claimed_role(line, names, CLAIM_AT) is not None


def _started(coins=None, names=None):
    s = helper.table(3, names=names)
    helper.rig(s, A, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"], C: ["Broker", "Guardian"]},
               coins or {A: 8, B: 3, C: 3})
    return s, len(s.g["log"])


def test_the_first_line_of_a_game_opens_the_story():
    s = helper.table(3)
    assert s.g["log"] and is_opener(s.g["log"][0], names_of(s)), s.g["log"][:1]


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
    assert is_opener(first, names_of(s)), "client.js does not know how game.py starts %s: %r" % (action, first)
    claim = claimed_role(first, names_of(s), CLAIM_AT)
    if role:
        assert claim == role, "the claim phrase no longer finds %s in %r" % (role, first)
    else:
        assert claim is None, first


def test_a_block_is_a_claim_the_client_can_read():
    s, since = _started()
    helper.act(s, A, "aid")
    helper.respond(s, B, "block", role="Banker")
    lines = s.g["log"][since:]
    blocks = [ln for ln in lines if claimed_role(ln, names_of(s), BLOCK_AT)]
    assert len(blocks) == 1, lines
    assert claimed_role(blocks[0], names_of(s), BLOCK_AT) == "Banker"
    # the block is a continuation of the action, never a new story
    assert not is_opener(blocks[0], names_of(s)), blocks[0]


def _names_in(scenario):
    return [x["name"] for x in scenario["views"]["watcher"]["game"]["seats"]]


def test_only_the_first_line_of_an_action_is_an_opener():
    """The client shows the log from the LAST opener on: a later line that looks like one would cut the story."""
    chains = [(name, sc["chain"], _names_in(sc)) for name, sc in helper.build().items() if sc["chain"]]
    assert len(chains) >= 15
    for name, chain, names in chains:
        starts = [i for i, ln in enumerate(chain) if is_opener(ln, names)]
        assert starts == [0], "%s: openers at %s in %r" % (name, starts, chain)


# names a player may really choose that read like part of a log line (core.session.clean_name: up to
# 14 letters, digits, spaces and - ' . ! ?)
SPOOFS = ["Bo claims Ag", "Al claims Bo", "x claims y z", "Alexandria", "Ann blocks"]


@pytest.mark.parametrize("spoof", SPOOFS)
def test_a_name_that_reads_like_a_verb_does_not_cut_or_open_a_story(spoof):
    """A challenge, a bluff called, a lost card and a failed claim all name the claimant: with a name
    such as "Bo claims Ag" none of those lines may look like the start of a claim."""
    names = ["Alexandria", spoof, "Chen"]
    s = helper.table(3, names=names)
    helper.rig(s, B, {A: ["Banker", "Agent"], B: ["Guardian", "Guardian"], C: ["Broker", "Guardian"]},
               {A: 2, B: 2, C: 2})
    since = len(s.g["log"])
    helper.act(s, B, "tax")
    helper.respond(s, A, "challenge")
    s.game_action(B, {"t": "lose", "card": 0})
    chain = s.g["log"][since:]
    assert len(chain) >= 5, chain
    seats = names_of(s)
    assert [i for i, ln in enumerate(chain) if is_opener(ln, seats)] == [0], chain
    assert claimed_role(chain[0], seats, CLAIM_AT) == "Banker", chain[0]
    # ... and a line that is only the name's words is not a claim, whoever is asked
    for ln in chain[1:]:
        assert claimed_role(ln, seats, CLAIM_AT) is None and claimed_role(ln, seats, BLOCK_AT) is None, ln


def test_the_words_alone_do_not_open_a_story_without_the_name_in_front():
    """Only a seat's name followed by the move counts: the same words elsewhere in a line, or after a
    name that is not at this table, are not a claim."""
    names = ["Alexandria", "Bo", "Chen"]
    assert is_opener("Bo claims \U0001F3E6 Banker to Tax.", names)
    assert not is_opener("Chen challenges Bo's Banker! Bo claims \U0001F3E6 Banker to Tax.", names)
    assert not is_opener("Zed claims \U0001F3E6 Banker to Tax.", names)
    assert not is_opener("Bo claims a lot to Chen", names)           # " to " without a role in front of it
    assert claimed_role("Bo blocks, claiming \U0001F3E6 Banker.", names, BLOCK_AT) == "Banker"
    assert claimed_role("Alexandria challenges Bo blocks, claiming \U0001F3E6 Banker.", names, BLOCK_AT) is None


def test_a_slow_turn_leads_into_its_forced_move():
    """client.js adds the "took too long" line that comes just before the move it forced."""
    s, since = _started({A: 2, B: 3, C: 3})
    s.game_tick()
    lines = s.g["log"][since:]
    assert lines[0].startswith("⏱"), lines
    assert is_opener(lines[1], names_of(s)), lines
    assert 'startsWith("⏱")' in SRC


def test_the_story_window_is_what_the_table_shows():
    """The client takes the last 15 log lines the server sends (state_for): a story is never longer."""
    s, since = _started()
    helper.act(s, A, "steal", B)
    log = helper.view(s, A)["game"]["log"]
    assert log and log == s.g["log"][-len(log):]
    assert len(log) <= 15
