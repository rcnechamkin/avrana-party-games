"""BLUFF "How to play" (AVR-90): the briefing's numbers and role facts must match the rules.

games/bluff/web/briefing.js holds the player-facing words; its FACTS, BLOCKS and ROLE_ORDER
lines are the only numbers/role facts it states. game.py is the only place rules live, so these
tests read both and fail when they drift (change the rule, then the briefing, together).
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from games.bluff import game as bluff
from games.bluff.game import BluffSession

WEB = Path(__file__).resolve().parents[1] / "games" / "bluff" / "web"
SRC = (WEB / "briefing.js").read_text(encoding="utf-8")


def _const(name):
    m = re.search(r"const %s = (.+?);\n" % name, SRC)
    assert m, "briefing.js must keep `const %s = ...;` on one line" % name
    return json.loads(m.group(1))


FACTS = _const("FACTS")
BLOCKS = _const("BLOCKS")
ROLE_ORDER = _const("ROLE_ORDER")

A, B = "tokA_briefing", "tokB_briefing"


def _game():
    s = BluffSession(rng=random.Random(3))
    for t, name in ((A, "Ann"), (B, "Ben")):
        s.join(t, name)
        s.set_ready(t, True)
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def _turn(s, tok, hand=("Guardian", "Guardian")):
    for t in (A, B):
        s.g["hand"][t] = list(hand)
        s.g["coins"][t] = 5
    s.g["turn"] = s.g["seats"].index(tok)
    s.g["pending"] = {"stage": "turn", "actor": tok}


def _everyone_else(s, actor, choice):
    for t in list(s.g["pending"].get("waiting", [])):
        if t != actor:
            s.game_action(t, {"t": "respond", "choice": choice})


def test_constants_match_the_rules():
    assert FACTS["startCoins"] == bluff.START_COINS
    assert FACTS["coupCost"] == bluff.COSTS["coup"]
    assert FACTS["strikeCost"] == bluff.COSTS["strike"]
    assert FACTS["mustCoupAt"] == bluff.MUST_COUP_AT
    assert FACTS["responseSeconds"] == bluff.RESPONSE_SECONDS


def test_roles_and_blocks_match_the_rules():
    assert ROLE_ORDER == list(bluff.ROLES)
    assert BLOCKS == {a: list(v[3]) for a, v in bluff.ACTIONS.items() if v[3]}
    # the action each role's line names is the action that role claims
    claims = {v[0]: a for a, v in bluff.ACTIONS.items() if v[0]}
    words = {"tax": "Tax", "strike": "Strike", "steal": "Steal", "exchange": "Exchange"}
    for role, action in claims.items():
        assert re.search(r'role: "%s", head: "%s:", text: [`"]%s' % (role, role, words[action]), SRC), role
    assert "Guardian" not in claims                     # "no move of its own"
    for role in bluff.ROLES:
        assert role in SRC


def test_dealt_hand_and_coins():
    s = _game()
    for t in (A, B):
        assert len(s.g["hand"][t]) == FACTS["handSize"]
        assert s.g["coins"][t] == FACTS["startCoins"]


def test_income_aid_tax_steal_amounts():
    s = _game()
    _turn(s, A)
    s.game_action(A, {"t": "act", "action": "income"})
    assert s.g["coins"][A] == 5 + FACTS["income"]

    _turn(s, A)
    s.game_action(A, {"t": "act", "action": "aid"})
    _everyone_else(s, A, "allow")
    assert s.g["coins"][A] == 5 + FACTS["aid"]

    _turn(s, A)
    s.game_action(A, {"t": "act", "action": "tax"})
    _everyone_else(s, A, "pass")
    assert s.g["coins"][A] == 5 + FACTS["tax"]

    _turn(s, A)
    s.game_action(A, {"t": "act", "action": "steal", "target": s.players[B].pid})
    _everyone_else(s, A, "pass")                        # the claim stands
    _everyone_else(s, A, "allow")                       # the target does not block
    assert s.g["coins"][A] == 5 + FACTS["steal"]
    assert s.g["coins"][B] == 5 - FACTS["steal"]


def test_page_loads_the_briefing_and_offers_rules():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert html.index('src="briefing.js"') < html.index('src="client.js"')
    assert re.search(r'<button id="rules"[^>]*aria-label="How to play"', html)
    assert '<dialog id="briefing" aria-labelledby="briefing-title">' in html
    # a UI preference of this game only: not an identity key, never sent to the server
    key = re.search(r'const KEY = "([^"]+)"', SRC).group(1)
    assert key == "bluff-briefed" and not key.startswith(("wc-", "lg-"))
    assert "send(" not in SRC and "WebSocket" not in SRC


# ---- the Party's setup scene reads BLUFF's onboarding as data (avrana-party ADR 0011) -----------
ONBOARDING = json.loads((WEB / "onboarding.json").read_text(encoding="utf-8"))


def test_onboarding_facts_are_the_briefings_facts():
    """onboarding.json is the concise rules sheet the Party's setup scene shows. Its numbers come
    only from its `facts` (as {placeholders}); those must be the briefing's, which the tests above
    pin to game.py."""
    assert ONBOARDING["schema"] == "avrana.onboarding/v0" and ONBOARDING["game"] == "bluff"
    assert ONBOARDING["facts"] == FACTS and ONBOARDING["blocks"] == BLOCKS
    ack = ONBOARDING["ack"]
    assert ack["key"] == re.search(r'KEY = "([^"]+)"', SRC).group(1)
    assert ack["version"] == re.search(r'VERSION = "([^"]+)"', SRC).group(1)


def test_onboarding_is_short_and_states_no_bare_numbers():
    rules = ONBOARDING["rules"]
    assert 3 <= len(rules) <= 6                              # one sheet, not a wizard
    for section in rules:
        assert section["title"] and 1 <= len(section["points"]) <= 5
        for point in section["points"]:
            for name in re.findall(r"\{(\w+)\}", point):
                assert name in FACTS, name                  # every placeholder is a fact
            assert not re.search(r"\d", re.sub(r"\{\w+\}", "", point)), point
    words = " ".join(p for s in rules for p in s["points"])
    for role in ROLE_ORDER:
        assert role in words                                 # every role is explained
    assert len(ONBOARDING["premise"]) <= 140
