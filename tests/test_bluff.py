"""BLUFF baseline: full interaction model + server-side masking."""

from __future__ import annotations

import json
import random

import pytest

from games.bluff.game import BluffSession

A, B, C = "tokenA_alice", "tokenB_bob", "tokenC_cara"


def game(n=2, bots=0, seed=1):
    s = BluffSession(rng=random.Random(seed))
    toks = [A, B, C][:n]
    for t, name in zip(toks, ("Alice", "Bob", "Cara")):
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def rig(s, **hands):
    """rig(s, A=[...], B=[...]) and give the turn to the first named player."""
    toks = {"A": A, "B": B, "C": C}
    for k, cards in hands.items():
        s.g["hand"][toks[k]] = list(cards)
    first = toks[next(iter(hands))]
    s.g["turn"] = s.g["seats"].index(first)
    s.g["pending"] = {"stage": "turn", "actor": first}


def act(s, tok, action, target=None):
    msg = {"t": "act", "action": action}
    if target:
        msg["target"] = s.players[target].pid
    return s.game_action(tok, msg)


def respond(s, tok, choice, role=None):
    msg = {"t": "respond", "choice": choice}
    if role:
        msg["role"] = role
    return s.game_action(tok, msg)


def stage(s):
    return s.g["pending"]["stage"]


def snap(s, tok):
    st = s.state_for(tok)
    st.pop("now", None)
    return json.dumps(st, sort_keys=True)


# ---------------------------------------------------------------- setup

def test_setup_two_cards_two_coins_bots_fill():
    s = game(n=1, bots=3)
    assert len(s.g["seats"]) == 4
    for t in s.g["seats"]:
        assert len(s.g["hand"][t]) == 2 and s.g["coins"][t] == 2
    assert len(s.g["deck"]) == 15 - 8
    assert s.state_for(A)["game"]["me"]["cards"] == s.g["hand"][A]


def test_solo_gets_at_least_one_bot():
    s = game(n=1, bots=0)
    assert len(s.g["seats"]) == 2


# ---------------------------------------------------------------- masking

def test_hidden_cards_never_in_other_payloads():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Smuggler", "Guardian"], C=["Broker", "Broker"])
    views = {t: snap(s, t) for t in (B, C, None)}
    # change ONLY A's hidden state (hand + an exchange draw): others must not change
    s.g["hand"][A] = ["Guardian", "Smuggler"]
    s.g["exchange_draw"] = ["Agent", "Banker"]
    for t, before in views.items():
        assert snap(s, t) == before, "A's hidden cards leaked to %r" % t
    seat = next(x for x in s.state_for(B)["game"]["seats"] if x["pid"] == s.players[A].pid)
    assert seat["influence"] == 2 and "cards" not in seat
    assert s.state_for(None)["game"]["me"] is None
    assert "deck" not in s.state_for(B)["game"]           # only deck_count


def test_exchange_pool_only_visible_to_exchanger():
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Banker"])
    before_b = snap(s, B)
    act(s, A, "exchange")
    respond(s, B, "pass")
    assert stage(s) == "exchange"
    pool = s.state_for(A)["game"]["me"]["prompt"]["pool"]
    assert len(pool) == 4 and pool[:2] == ["Broker", "Agent"]
    assert s.state_for(B)["game"]["me"]["prompt"] is None
    # B's view changed only publicly (log/pending), never includes the drawn cards
    assert "pool" not in json.dumps(s.state_for(B)["game"]["seats"])
    assert snap(s, B) != before_b
    s.game_action(A, {"t": "keep", "cards": [2, 3]})
    assert sorted(s.g["hand"][A]) == sorted(pool[2:]) and stage(s) == "turn"
    assert len(s.g["deck"]) == 15 - 4


# ---------------------------------------------------------------- general actions

def test_income_and_forced_coup():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "income")
    assert s.g["coins"][A] == 3 and s.g["pending"]["actor"] == B
    s.g["coins"][B] = 10
    assert [a["action"] for a in s.state_for(B)["game"]["me"]["actions"]] == ["coup"]
    assert act(s, B, "income")[0]["kind"] == "invalid"
    act(s, B, "coup", A)
    assert s.g["coins"][B] == 3 and stage(s) == "lose"
    assert s.state_for(A)["game"]["me"]["prompt"] == {"kind": "lose"}
    s.game_action(A, {"t": "lose", "card": 1})
    assert s.g["revealed"][A] == ["Agent"] and s.g["hand"][A] == ["Banker"]


def test_foreign_aid_blocked_block_challenged_true_and_false():
    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Banker", "Smuggler"])
    act(s, A, "aid")
    assert stage(s) == "block"
    respond(s, B, "block", "Banker")
    assert stage(s) == "block_challenge"
    respond(s, A, "challenge")              # B really has Banker -> A loses a card, aid fails
    assert stage(s) == "lose" and s.g["pending"]["loser"] == A
    s.game_action(A, {"t": "lose", "card": 0})
    assert s.g["coins"][A] == 2 and s.g["pending"]["actor"] == B
    assert "Banker" not in s.g["revealed"][B] and len(s.g["hand"][B]) == 2   # proved + redrawn

    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Smuggler", "Broker"])
    act(s, A, "aid")
    respond(s, B, "block", "Banker")        # bluff
    respond(s, A, "challenge")              # B can't show Banker -> B loses, aid resolves
    s.game_action(B, {"t": "lose", "card": 0})
    assert s.g["coins"][A] == 4 and s.g["revealed"][B] == ["Smuggler"]


# ---------------------------------------------------------------- claims and challenges

def test_tax_unchallenged_true_challenge_and_bluff():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    assert stage(s) == "challenge" and s.state_for(B)["game"]["me"]["prompt"] == {"kind": "challenge"}
    respond(s, B, "pass")
    assert s.g["coins"][A] == 5

    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    respond(s, B, "challenge")              # true claim: B loses, A still taxes
    s.game_action(B, {"t": "lose", "card": 0})
    assert s.g["coins"][A] == 5 and len(s.g["hand"][A]) == 2 and s.g["revealed"][B] == ["Guardian"]

    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")                        # bluff
    respond(s, B, "challenge")
    s.game_action(A, {"t": "lose", "card": 1})
    assert s.g["coins"][A] == 2 and s.g["revealed"][A] == ["Guardian"]


def test_strike_cost_block_and_double_loss_on_bluffed_block():
    s = game(n=2)
    rig(s, A=["Agent", "Banker"], B=["Guardian", "Smuggler"])
    s.g["coins"][A] = 3
    act(s, A, "strike", B)
    assert s.g["coins"][A] == 0            # paid up front
    respond(s, B, "pass")                   # no challenge of the Agent
    assert stage(s) == "block"
    respond(s, B, "block", "Guardian")
    respond(s, A, "pass")                   # block stands
    assert len(s.g["hand"][B]) == 2 and s.g["pending"]["actor"] == B

    s = game(n=2)
    rig(s, A=["Agent", "Banker"], B=["Smuggler", "Broker"])
    s.g["coins"][A] = 3
    act(s, A, "strike", B)
    respond(s, B, "pass")
    respond(s, B, "block", "Guardian")      # bluff block
    respond(s, A, "challenge")              # B loses for the bluff, then the strike lands
    s.game_action(B, {"t": "lose", "card": 0})
    assert s.phase == "game_end" and s.g["winner"] == A


def test_steal_blocked_by_broker_and_limited_by_coins():
    s = game(n=2)
    rig(s, A=["Smuggler", "Banker"], B=["Broker", "Agent"])
    act(s, A, "steal", B)
    respond(s, B, "pass")
    respond(s, B, "block", "Broker")
    respond(s, A, "pass")
    assert s.g["coins"][A] == 2 and s.g["coins"][B] == 2

    s = game(n=2)
    rig(s, A=["Smuggler", "Banker"], B=["Broker", "Agent"])
    s.g["coins"][B] = 1
    act(s, A, "steal", B)
    respond(s, B, "pass")
    respond(s, B, "allow")
    assert s.g["coins"][A] == 3 and s.g["coins"][B] == 0


def test_only_the_target_may_block_and_only_valid_roles():
    s = game(n=3)
    rig(s, A=["Smuggler", "Banker"], B=["Broker", "Agent"], C=["Broker", "Guardian"])
    act(s, A, "steal", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    assert respond(s, C, "block", "Broker")[0]["kind"] == "invalid"     # not the target
    assert respond(s, B, "block", "Guardian")[0]["kind"] == "invalid"   # wrong role
    assert stage(s) == "block"


# ---------------------------------------------------------------- elimination, timers, input

def test_elimination_and_winner():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian"], C=["Broker", "Smuggler"])
    s.g["revealed"][B] = ["Smuggler"]
    s.g["coins"][A] = 7
    act(s, A, "coup", B)                    # one card left: revealed automatically
    assert not s.g["hand"][B] and s.g["coins"][B] == 0
    seat = next(x for x in s.state_for(C)["game"]["seats"] if x["pid"] == s.players[B].pid)
    assert seat["alive"] is False and seat["revealed"] == ["Smuggler", "Guardian"]
    assert s.g["pending"]["actor"] == C     # B skipped


def test_timers_never_stall():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    s.tick(s.gen)                           # challenge window expires -> tax resolves
    assert s.g["coins"][A] == 5 and s.g["pending"]["actor"] == B
    s.tick(s.gen)                           # B idle -> auto income
    assert s.g["coins"][B] == 3 and s.g["pending"]["actor"] == A
    s.g["coins"][A] = 7
    act(s, A, "coup", B)
    s.tick(s.gen)                           # lose choice expires -> first card
    assert s.g["revealed"][B] == ["Guardian"]


@pytest.mark.parametrize("msg", [
    {"t": "act", "action": ["tax"]}, {"t": "act", "action": "coup"},
    {"t": "act", "action": "steal", "target": {"x": 1}}, {"t": "act", "action": "nope"},
    {"t": "respond", "choice": "challenge"}, {"t": "lose", "card": "0"},
    {"t": "keep", "cards": "all"}, {"t": 7}, {},
])
def test_malformed_input_never_raises(msg):
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    out = s.game_action(A, msg)
    assert out and out[0]["kind"] == "invalid"
    assert s.g["coins"][A] == 2 and stage(s) == "turn"


def test_bots_and_timers_finish_a_whole_game():
    s = game(n=1, bots=3, seed=7)
    for _ in range(2000):
        if s.phase != "playing":
            break
        due = s.next_bot_action()
        if due:
            s.run_bot(due[1])
        elif stage(s) == "turn" and s.g["pending"]["actor"] == A:
            acts = [a["action"] for a in s.legal_actions(A)]
            a = "coup" if "coup" in acts else "income"
            tgt = next(t for t in s.g["seats"] if t != A and s.g["hand"][t]) if a == "coup" else None
            act(s, A, a, tgt)
        else:
            s.tick(s.gen)                   # A's lose choice etc.
    assert s.phase == "game_end" and s.g["winner"] is not None


def test_everyone_disconnecting_does_not_abandon():
    s = game(n=2)
    s.leave(A); s.leave(B)
    assert s.phase == "playing"
