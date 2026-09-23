"""BLUFF lifecycle: presence, autopilot, pause/abandon, forfeit, end game (fake clock)."""

from __future__ import annotations

import json
import random
import time

import pytest

from games.bluff import game as bluff
from games.bluff.game import (AWAY_GRACE, AUTOPILOT_DELAY, EMPTY_TABLE_ABANDON,
                              RESUME_MIN, BluffSession)

A, B, C, S = "tokenA_alice", "tokenB_bob", "tokenC_cara", "tokenS_stranger"


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def adv(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(time, "time", c)
    return c


def game(n=3, bots=0, seed=3):
    s = BluffSession(rng=random.Random(seed))
    for t, name in zip([A, B, C][:n], ("Alice", "Bob", "Cara")):
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def rig(s, first, **hands):
    toks = {"A": A, "B": B, "C": C}
    for k, cards in hands.items():
        s.g["hand"][toks[k]] = list(cards)
    s.g["turn"] = s.g["seats"].index(first)
    s.g["pending"] = {"stage": "turn", "actor": first}


def act(s, tok, action, target=None):
    msg = {"t": "act", "action": action}
    if target:
        msg["target"] = s.players[target].pid
    return s.game_action(tok, msg)


def run_due(s):
    """What core.net would do: run the scheduled bot/autopilot action if one is due."""
    due = s.next_bot_action()
    if due is None:
        return None
    s.run_bot(due[1])
    return due


def presence(s, tok):
    return next(x["presence"] for x in s.state_for(None)["game"]["seats"]
                if x["pid"] == s.players[tok].pid)


# ---------------------------------------------------------------- temporary disconnect

def test_leave_keeps_seat_game_and_deadline(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"])
    dl = s.deadline
    s.leave(B)
    assert s.phase == "playing" and s.deadline == dl and not s.g["paused"]
    assert presence(s, B) == "reconnecting" and s.players[B].pid
    clock.adv(AWAY_GRACE + 1)
    assert presence(s, B) == "away"


def test_reconnect_same_token_restores_private_state_prompt_and_deadline(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    before = s.state_for(B)["game"]["me"]
    dl = s.deadline
    s.leave(B)
    clock.adv(5)
    s.join(B, "Bob")
    me = s.state_for(B)["game"]["me"]
    assert me["cards"] == before["cards"] and me["prompt"] == {"kind": "challenge"}
    assert s.deadline == dl and presence(s, B) == "here"


def test_within_grace_no_autopilot_then_autopilot(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"])
    s.leave(A)                                  # the ACTIVE player's phone sleeps
    delay, tok = s.next_bot_action()
    assert tok == A and abs(delay - AWAY_GRACE) < 0.01
    clock.adv(AWAY_GRACE)
    delay, tok = s.next_bot_action()
    assert tok == A and delay == 0
    s.run_bot(A)
    assert s.g["coins"][A] == 3                 # autopilot took Income


def test_repeated_pushes_do_not_postpone_a_due_action(clock):
    """Message spam re-runs next_bot_action on every push: the due moment must hold."""
    s = game(n=1, bots=2)
    rig(s, s.g["seats"][1])                     # a bot's turn
    d1, _ = s.next_bot_action()
    clock.adv(0.5)
    d2, _ = s.next_bot_action()
    assert abs((d1 - d2) - 0.5) < 1e-6


@pytest.mark.parametrize("stage", ["challenge", "block", "block_challenge", "lose", "exchange"])
def test_autopilot_is_passive_in_every_stage(clock, stage):
    s = game()
    rig(s, A, A=["Broker", "Smuggler"], B=["Guardian", "Banker"], C=["Agent", "Agent"])
    s.g["coins"][A] = 7
    if stage == "challenge":
        act(s, A, "tax"); away = B
    elif stage == "block":
        act(s, A, "steal", B)
        for t in (B, C):
            s.game_action(t, {"t": "respond", "choice": "pass"})
        away = B
    elif stage == "block_challenge":
        act(s, A, "steal", B)
        for t in (B, C):
            s.game_action(t, {"t": "respond", "choice": "pass"})
        s.game_action(B, {"t": "respond", "choice": "block", "role": "Smuggler"})
        away = C
    elif stage == "lose":
        act(s, A, "coup", B); away = B
    else:
        act(s, A, "exchange")
        for t in (B, C):
            s.game_action(t, {"t": "respond", "choice": "pass"})
        away = A
    assert s.g["pending"]["stage"] == stage and away in s.g["pending"]["waiting"]
    hand_before = list(s.g["hand"][away])
    s.leave(away)
    clock.adv(AWAY_GRACE + 1)
    assert run_due(s)[1] == away
    if stage == "lose":
        assert s.g["revealed"][B] == hand_before[:1]
    elif stage == "exchange":
        assert sorted(s.g["hand"][A]) == sorted(hand_before)
    else:
        assert away not in s.g["pending"].get("waiting", [])
    # autopilot never claims, challenges or blocks
    assert not any("challenges" in l and l.startswith(s.players[away].name) for l in s.g["log"])
    assert not any(l.startswith(s.players[away].name + " blocks") for l in s.g["log"])


def test_autopilot_coups_only_when_forced(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"])
    s.g["coins"][A] = 9
    s.leave(A); clock.adv(AWAY_GRACE + 1)
    run_due(s)
    assert s.g["coins"][A] == 10                # Income, not Coup
    rig(s, A)
    s.g["due"] = None
    run_due(s)
    assert s.g["coins"][A] == 3 and s.g["pending"]["stage"] == "lose"


def test_autopilot_stops_on_return(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"])
    s.leave(A); clock.adv(AWAY_GRACE + 1)
    s.join(A, "Alice")
    assert s.next_bot_action() is None          # A is back in charge of their seat


# ---------------------------------------------------------------- empty table

def test_all_seated_away_pauses_and_freezes(clock):
    s = game(n=2, bots=1)
    rig(s, A, A=["Banker", "Agent"])
    s.leave(A); s.leave(B)
    assert s.g["paused"] and s.deadline == clock.t + EMPTY_TABLE_ABANDON
    assert s.next_bot_action() is None and s.legal_actions(A) == []
    assert s.state_for(None)["game"]["paused"] is True


def test_return_during_pause_restores_remaining_time(clock):
    s = game(n=2)
    rig(s, A, A=["Banker", "Agent"])
    s._bump(clock.t + 50)
    s.leave(A); s.leave(B)
    clock.adv(120)
    s.join(B, "Bob")
    assert not s.g["paused"] and s.deadline == clock.t + 50
    s.leave(B)
    s.g["paused"] = {"remaining": 2}
    s.join(B, "Bob")
    assert s.deadline == clock.t + RESUME_MIN


def test_empty_table_abandons_to_lobby_and_prunes(clock):
    s = game(n=2, bots=2)
    s.leave(A); s.leave(B)
    clock.adv(EMPTY_TABLE_ABANDON)
    s.tick(s.gen)
    assert s.phase == "lobby" and not [p for p in s.players.values()]


def test_present_eliminated_human_prevents_pause(clock):
    s = game()
    s.g["revealed"][C] = list(s.g["hand"][C]); s.g["hand"][C] = []
    s.leave(A); s.leave(B)                      # C (out, but watching) is still here
    assert not s.g["paused"]


def test_brief_total_blackout_resumes_exactly(clock):
    s = game(n=2)
    rig(s, A, A=["Banker", "Agent"])
    before = s.state_for(A)["game"]
    s._bump(clock.t + 60)
    s.leave(A); s.leave(B)
    clock.adv(8)
    s.join(A, "Alice"); s.join(B, "Bob")
    after = s.state_for(A)["game"]
    assert after["pending"]["actor"] == before["pending"]["actor"] and s.deadline == clock.t + 60


# ---------------------------------------------------------------- forfeit / end game

def test_forfeit_goes_autopilot_then_out_at_turn_boundary(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Agent"])
    act(s, A, "tax")
    s.game_action(B, {"t": "leave_game"})
    assert s.g["hand"][B]                        # not mid-claim
    run_due(s)                                   # autopilot passes for B
    s.game_action(C, {"t": "respond", "choice": "pass"})
    assert not s.g["hand"][B] and sorted(s.g["revealed"][B]) == ["Guardian", "Smuggler"]
    assert s.g["pending"]["actor"] == C          # B skipped
    assert s.game_action(B, {"t": "act", "action": "income"})[0]["kind"] == "invalid"


def test_last_forfeit_ends_the_game(clock):
    s = game(n=2)
    rig(s, A, A=["Banker", "Agent"])
    s.game_action(B, {"t": "leave_game"})
    act(s, A, "income")
    assert s.phase == "game_end" and s.g["winner"] == A


def test_end_game_allowed_only_when_nobody_else_is_here(clock):
    s = game()
    assert s.game_action(A, {"t": "end_game"})[0]["kind"] == "invalid"
    s.leave(B); s.leave(C)
    out = s.game_action(A, {"t": "end_game"})
    assert s.phase == "lobby" and any(f["kind"] == "toast" for f in out)


def test_spectator_cannot_end_or_leave(clock):
    s = game()
    s.join(S, "Stranger")
    assert s.state_for(S)["game"]["me"] is None
    for t in ("end_game", "leave_game"):
        assert s.game_action(S, {"t": t})[0]["kind"] == "invalid"
    assert s.phase == "playing"


# ---------------------------------------------------------------- lobby countdown

def test_refresh_during_countdown_keeps_seat_and_ghosts_are_pruned(clock):
    s = BluffSession(rng=random.Random(1))
    for t, n in ((A, "Alice"), (B, "Bob"), (C, "Cara")):
        s.join(t, n); s.set_ready(t, True)
    s.start(A)
    pid_b = s.players[B].pid
    s.leave(B); s.join(B, "Bob")                # refresh: same token, same seat
    s.leave(C)                                  # C never comes back
    s.tick(s.gen)
    assert s.players[B].pid == pid_b and B in s.g["seats"]
    assert C not in s.g["seats"] and C not in s.players


# ---------------------------------------------------------------- protocol hygiene

def test_stale_step_is_rejected(clock):
    s = game()
    rig(s, A, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    old = s.state_for(C)["game"]["pending"]["step"]
    s.game_action(B, {"t": "respond", "choice": "pass"})
    s.game_action(C, {"t": "respond", "choice": "pass", "step": old})   # same step: ok
    assert s.g["pending"]["actor"] == B          # tax resolved, B's turn (new step)
    out = s.game_action(B, {"t": "act", "action": "income", "step": old})
    assert out[0]["kind"] == "invalid" and s.g["coins"][B] == 2


def test_presence_values_and_no_tokens_in_payload(clock):
    s = game(n=2, bots=1)
    s.leave(B)
    g = s.state_for(A)["game"]
    vals = {x["name"]: x["presence"] for x in g["seats"]}
    assert vals == {"Alice": "here", "Bob": "reconnecting", "Test bot 1": "bot"}
    blob = json.dumps([s.state_for(t) for t in (A, B, None)])
    assert A not in blob and B not in blob
