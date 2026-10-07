#!/usr/bin/env python3
"""Real BLUFF per-viewer states for tests/bluff_layout_test.mjs (AVR-313).

The browser layout test needs the table in the situations that are hard to reach by hand: a lose
prompt right after a challenge, a block that is itself challenged, a six-seat Party spectator, a
winner with a long name. Writing those states by hand would let them drift from the server. So this
helper plays the real `BluffSession` (the same class the server runs) through `game_action()` and
prints what `state_for()` would send each viewer, as JSON, at the moment the test names:

    python tests/bluff_states.py            # one JSON document on stdout

The only shortcut is the one tests/test_bluff.py takes: a hand, a coin count and whose turn it is
are set directly (`rig`), so the scenario does not depend on the shuffle. Nothing here changes a
rule, and nothing here is imported by the game or the server.

Each scenario is {"stage": ..., "chain": [log lines], "views": {label: state}}:

  views.player     the seat the moment is about (the one asked, or the one who must act)
  views.bystander  another seated player, not involved
  views.watcher    a phone that is not at the table (state_for(None): the public view)
  views.spectator  a Party spectator (state_for(None, spectator=True): every hand is open)

`chain` is the public log of the action that produced the moment, from its first line to the last,
copied from the session's own log. (A table that has not started, `lobby` and `lobby_party`, has no
game and an empty chain.) The test compares what the page shows with it, so the client's
reading of the log is checked against the server's, not against a second copy of the client's rule.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from games.bluff.game import BluffSession  # noqa: E402

NAMES = ["Alexandria", "Bartholomew", "Chen", "Dee", "Eve-Marie", "Fatima"]
TOKENS = ["tok%s_layout_%02d" % (c, i) for i, c in enumerate("ABCDEF")]
A, B, C, D, E, F = TOKENS


def table(n=6, seed=2, names=None):
    """A started Party round of n seats (A is first to act), the way the Party seats one."""
    s = BluffSession(rng=random.Random(seed))
    for i, (tok, name) in enumerate(zip(TOKENS[:n], (names or NAMES)[:n])):
        s.join(tok, name)
        s.set_ready(tok, True)
        s.players[tok].pfp = "/shared/avatars/gaze-%02d.svg" % (i + 1)
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing", s.phase
    s.party_round = True
    return s


def rig(s, actor, hands=None, coins=None):
    """Whose turn it is, what they hold and how many coins: set directly, as tests/test_bluff.py does."""
    for tok, cards in (hands or {}).items():
        s.g["hand"][tok] = list(cards)
    for tok, count in (coins or {}).items():
        s.g["coins"][tok] = count
    s.g["turn"] = s.g["seats"].index(actor)
    s.g["pending"] = {"stage": "turn", "actor": actor}
    s.g["step"] += 1


def pid(s, tok):
    return s.players[tok].pid


def act(s, tok, action, target=None):
    msg = {"t": "act", "action": action}
    if target:
        msg["target"] = pid(s, target)
    return s.game_action(tok, msg)


def respond(s, tok, choice, role=None):
    msg = {"t": "respond", "choice": choice}
    if role:
        msg["role"] = role
    return s.game_action(tok, msg)


def everyone_else(s, actor, choice):
    for tok in list(s.g["pending"].get("waiting", [])):
        if tok != actor:
            respond(s, tok, choice)


def view(s, tok=None, spectator=False):
    st = s.state_for(None if spectator else tok, spectator=spectator)
    st["deadline"] = None            # the test sets it from the page's own clock
    return st


def views(s, player, bystander, challenger=None):
    out = {
        "player": view(s, player),
        "bystander": view(s, bystander),
        "watcher": view(s, None),
        "spectator": view(s, spectator=True),
    }
    if challenger:
        out["challenger"] = view(s, challenger)
    return out


def scenario(s, stage, player, bystander, since, challenger=None, **extra):
    """since = len(log) before the action that led here: chain is everything the action wrote."""
    return dict({"stage": stage, "chain": list(s.g["log"][since:]),
                 "views": views(s, player, bystander, challenger)}, **extra)


def fresh(n=6, **kw):
    s = table(n, **kw)
    return s, len(s.g["log"])


def build():
    out = {}

    # ---- my turn: what the bar offers at each wealth ------------------------------------------
    s = table()
    rig(s, A, {A: ["Banker", "Agent"]}, {A: 2, B: 3, C: 1, D: 5, E: 0, F: 7})
    out["turn_mine_poor"] = scenario(s, "turn", A, C, 0)

    s = table()
    rig(s, A, {A: ["Smuggler", "Guardian"]}, {A: 8, B: 3})
    out["turn_mine_rich"] = scenario(s, "turn", A, C, 0)

    s = table()
    rig(s, A, {A: ["Broker", "Broker"]}, {A: 11})
    out["turn_must_coup"] = scenario(s, "turn", A, C, 0)

    s = table()
    rig(s, C, {A: ["Banker", "Agent"]}, {A: 2})
    out["waiting_other_turn"] = scenario(s, "turn", A, B, 0)

    s = table(2)
    rig(s, A, {A: ["Banker", "Agent"]}, {A: 2})
    out["turn_mine_two_players"] = scenario(s, "turn", A, B, 0)

    # ---- a claim awaiting a challenge ---------------------------------------------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Guardian", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "tax")
    out["challenge_prompt"] = scenario(s, "challenge", A, D, since)

    # ---- Foreign Aid: a block prompt ----------------------------------------------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "aid")
    out["block_prompt_aid"] = scenario(s, "block", A, D, since)

    # ---- Steal: the claim stands, the target may block ----------------------------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"]}, {A: 4, B: 2})
    since = len(s.g["log"])
    act(s, B, "steal", A)
    everyone_else(s, B, "pass")
    out["block_prompt_steal"] = scenario(s, "block", A, D, since)

    # ---- the same claim was challenged first and held: the block prompt carries the verdict ----
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"], C: ["Banker", "Banker"]},
        {A: 4, B: 2})
    since = len(s.g["log"])
    act(s, B, "steal", A)
    respond(s, C, "challenge")                     # B holds a Smuggler: the claim was TRUE
    s.game_action(C, {"t": "lose", "card": 0})     # C gives up a card
    out["block_prompt_after_true"] = scenario(s, "block", A, D, since)

    # ---- A blocks B's Steal; the block can be challenged --------------------------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"]}, {A: 4, B: 2})
    since = len(s.g["log"])
    act(s, B, "steal", A)
    everyone_else(s, B, "pass")
    respond(s, A, "block", "Smuggler")
    out["block_challenge"] = scenario(s, "block_challenge", D, C, since, challenger=B,
                                      blocker=pid(s, A))

    # ... and with the claim itself proven before the block (the longest chain the table shows)
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"], C: ["Banker", "Banker"]},
        {A: 4, B: 2})
    since = len(s.g["log"])
    act(s, B, "steal", A)
    respond(s, C, "challenge")
    s.game_action(C, {"t": "lose", "card": 0})
    respond(s, A, "block", "Smuggler")
    out["block_challenge_long"] = scenario(s, "block_challenge", D, C, since, challenger=B)

    # ---- a challenge that was right: the claimant must give up a card (BLUFF) -----------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Guardian", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "tax")
    respond(s, A, "challenge")
    out["lose_bluff"] = scenario(s, "lose", B, D, since, challenger=A)

    # ... and what the table shows after the claimant chose: the next turn
    s.game_action(B, {"t": "lose", "card": 0})
    out["turn_after_bluff"] = scenario(s, "turn", A, D, since, challenger=B)

    # ---- a challenge that was wrong: the challenger gives up a card (TRUE) --------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Banker", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "tax")
    respond(s, A, "challenge")
    out["lose_true"] = scenario(s, "lose", A, D, since, challenger=B)

    s.game_action(A, {"t": "lose", "card": 0})
    out["turn_after_true"] = scenario(s, "turn", A, D, since, challenger=B)

    # ---- no challenge at all: a Coup and a Strike also end in "give up a card" ----------------
    s = table()
    rig(s, A, {A: ["Banker", "Agent"], B: ["Banker", "Guardian"]}, {A: 8})
    since = len(s.g["log"])
    act(s, A, "coup", B)
    out["lose_coup"] = scenario(s, "lose", B, D, since)

    s = table()
    rig(s, A, {A: ["Agent", "Guardian"], B: ["Banker", "Guardian"]}, {A: 5})
    since = len(s.g["log"])
    act(s, A, "strike", B)
    everyone_else(s, A, "pass")
    respond(s, B, "allow")
    out["lose_strike"] = scenario(s, "lose", B, D, since)

    # ---- exchange: pick two of four ------------------------------------------------------------
    s = table()
    rig(s, A, {A: ["Broker", "Agent"]}, {A: 2})
    since = len(s.g["log"])
    act(s, A, "exchange")
    everyone_else(s, A, "pass")
    out["exchange_prompt"] = scenario(s, "exchange", A, C, since)

    # ---- I am out, the table goes on -----------------------------------------------------------
    s = table()
    rig(s, C, {A: [], B: ["Agent", "Guardian"]}, {A: 0})
    s.g["revealed"][A] = ["Banker", "Agent"]
    out["out_watching"] = scenario(s, "turn", A, B, 0)

    # ---- the last card: the game ends on a Coup (results) -------------------------------------
    for label, name in (("results", None), ("results_long_name", "Wolfeschlegels")):
        names = list(NAMES)
        if name:
            names[0] = name
        s = table(3, names=names)
        rig(s, A, {A: ["Banker", "Agent"], B: ["Agent"], C: ["Guardian"]}, {A: 9})
        act(s, A, "coup", B)                       # B's last card: out; the table plays on
        rig(s, A, None, {A: 9})
        since = len(s.g["log"])
        act(s, A, "coup", C)                       # C's last card: A is the last one standing
        assert s.phase == "game_end" and s.g["winner"], s.phase
        out[label] = scenario(s, "over", A, B, since, challenger=C)

    # ---- a Party spectator at a full table, mid-challenge -------------------------------------
    s = table()
    rig(s, B, {A: ["Banker", "Agent"], B: ["Guardian", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "tax")
    out["spectator_full_table"] = scenario(s, "challenge", A, D, since)

    # ---- everyone stepped away: paused ---------------------------------------------------------
    s = table(4)
    rig(s, A, {A: ["Banker", "Agent"]}, {A: 2})
    s.g["paused"] = {"remaining": 55, "since": 0}
    out["paused_four"] = scenario(s, "turn", A, B, 0)

    # ---- aiming a Coup with one opponent out: that seat is on the table, and cannot be aimed at -
    s = table(4)
    rig(s, A, {A: ["Banker", "Agent"], B: ["Smuggler", "Guardian"], C: ["Broker", "Guardian"], D: []},
        {A: 8, B: 3, C: 3, D: 0})
    s.g["revealed"][D] = ["Banker", "Agent"]
    out["turn_coup_one_out"] = scenario(s, "turn", A, B, 0)

    # ---- a player whose own name reads like a log verb ("Bo claims Ag"): the story is unchanged ---
    s = table(4, names=["Alexandria", "Bo claims Ag", "Chen", "Dee"])
    rig(s, B, {A: ["Banker", "Agent"], B: ["Guardian", "Guardian"]}, {A: 2, B: 2})
    since = len(s.g["log"])
    act(s, B, "tax")
    respond(s, A, "challenge")
    out["spoofed_name_bluff"] = scenario(s, "lose", B, D, since, challenger=A)
    s.game_action(B, {"t": "lose", "card": 0})
    out["spoofed_name_after"] = scenario(s, "turn", A, D, since, challenger=B)

    # ---- tables that have not started (nobody has a hand): the lobby, and the Party's "starting" ---
    for label, party in (("lobby", False), ("lobby_party", True)):
        s = BluffSession(rng=random.Random(2))
        for i, (tok, name) in enumerate(zip(TOKENS[:4], NAMES)):
            s.join(tok, name)
            s.players[tok].pfp = "/shared/avatars/gaze-%02d.svg" % (i + 1)
        s.set_ready(B, True)
        s.set_ready(C, True)
        s.party_round = party
        assert s.phase == "lobby", s.phase
        out[label] = {"stage": "lobby", "chain": [], "views": views(s, A, B)}

    return out


if __name__ == "__main__":
    json.dump(build(), sys.stdout)
