"""BLUFF rules / state-machine audit (subagent: gameplay).

Scenario tests for claims, challenges, blocks, challenge-the-block, elimination,
timeouts, bots, turn order and invariants, plus a randomized fuzz that drives the
session with legal, illegal, stale and timed-out inputs and checks invariants after
every step. Tests that expose a real bug are marked xfail(strict=True).
"""

from __future__ import annotations

import random

import pytest

from games.bluff.game import BluffSession, COPIES, ROLES

A, B, C, D = "tokenA_alice", "tokenB_bob", "tokenC_cara", "tokenD_dave"
TOKS = {"A": A, "B": B, "C": C, "D": D}
TOTAL_CARDS = COPIES * len(ROLES)


# ---------------------------------------------------------------- helpers

def game(n=2, bots=0, seed=1):
    s = BluffSession(rng=random.Random(seed))
    for t, name in list(zip((A, B, C, D), ("Alice", "Bob", "Cara", "Dave")))[:n]:
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def rig(s, coins=None, **hands):
    """Set hands (rest of the 15 cards become the deck, so conservation holds),
    and give the turn to the first named player."""
    pool = [r for r in ROLES for _ in range(COPIES)]
    for k, cards in hands.items():
        tok = TOKS[k]
        s.g["hand"][tok] = list(cards)
        for c in cards:
            pool.remove(c)
        for c in s.g["revealed"][tok]:
            pool.remove(c)
    for tok in s.g["seats"]:
        if tok not in [TOKS[k] for k in hands]:
            for c in s.g["hand"][tok] + s.g["revealed"][tok]:
                pool.remove(c)
    s.g["deck"] = pool
    for k, v in (coins or {}).items():
        s.g["coins"][TOKS[k]] = v
    first = TOKS[next(iter(hands))]
    s.g["turn"] = s.g["seats"].index(first)
    s.g["pending"] = {"stage": "turn", "actor": first}
    check_invariants(s)


def give(s, tok, role):
    """Ensure `tok` holds `role` by swapping its first card with one found in the
    deck or another hand (conserves cards)."""
    if role in s.g["hand"][tok]:
        return
    for src in [s.g["deck"]] + [s.g["hand"][t] for t in s.g["seats"] if t != tok]:
        if role in src:
            i = src.index(role)
            src[i], s.g["hand"][tok][0] = s.g["hand"][tok][0], src[i]
            check_invariants(s)
            return
    raise AssertionError("no %s available" % role)


def kill(s, tok, card):
    """Pre-reveal one card of `tok` (hand must already hold it)."""
    s.g["hand"][tok].remove(card)
    s.g["revealed"][tok].append(card)


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


def lose(s, tok, idx=0):
    return s.game_action(tok, {"t": "lose", "card": idx})


def stage(s):
    return s.g["pending"]["stage"]


def waiting(s):
    return list(s.g["pending"].get("waiting", []))


def invalid(out):
    return bool(out) and out[0]["kind"] == "invalid"


def check_invariants(s):
    g = s.g
    cards = list(g["deck"]) + list(g["exchange_draw"] or [])
    for t in g["seats"]:
        cards += g["hand"][t] + g["revealed"][t]
        assert len(g["hand"][t]) + len(g["revealed"][t]) == 2, t
        assert g["coins"][t] >= 0, (t, g["coins"][t])
        if not g["hand"][t]:
            assert g["coins"][t] == 0
    assert sorted(cards) == sorted(r for r in ROLES for _ in range(COPIES))
    assert len(cards) == TOTAL_CARDS
    if s.phase == "playing":
        p = g["pending"]
        assert p and p.get("stage") in ("turn", "challenge", "block", "block_challenge",
                                         "lose", "exchange")
        assert s.deadline is not None
        assert s._alive(s._actor()), "dead player holds the turn"
        if p["stage"] == "turn":
            assert p["actor"] == s._actor()
        else:
            assert p["waiting"], "non-turn stage with nobody to wait for"
            for t in p["waiting"]:
                assert s._alive(t), "eliminated player in waiting list"
        if p["stage"] != "exchange":
            assert g["exchange_draw"] is None
    else:
        assert s.phase in ("game_end", "lobby")
        alive = s._alive_seats()
        assert len(alive) == 1 and g["winner"] == alive[0]


# ---------------------------------------------------------------- 1. challenge the block (third party)

def test_third_party_challenges_true_steal_block_block_stands():
    s = game(n=3)
    rig(s, A=["Smuggler", "Banker"], B=["Smuggler", "Agent"], C=["Guardian", "Broker"])
    act(s, A, "steal", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    assert stage(s) == "block" and waiting(s) == [B]
    respond(s, B, "block", "Smuggler")
    assert stage(s) == "block_challenge" and set(waiting(s)) == {A, C}
    respond(s, C, "challenge")
    assert stage(s) == "lose" and s.g["pending"]["loser"] == C
    # B proved Smuggler: it went back to the deck and B still holds 2 cards
    assert len(s.g["hand"][B]) == 2 and s.g["revealed"][B] == []
    lose(s, C, 1)
    assert s.g["revealed"][C] == ["Broker"]
    assert s.g["coins"][A] == 2 and s.g["coins"][B] == 2          # steal failed
    assert stage(s) == "turn" and s.g["pending"]["actor"] == B
    check_invariants(s)


def test_third_party_challenges_bluffed_steal_block_steal_resolves():
    s = game(n=3)
    rig(s, A=["Smuggler", "Banker"], B=["Guardian", "Agent"], C=["Broker", "Banker"])
    act(s, A, "steal", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    respond(s, B, "block", "Smuggler")                              # bluff
    respond(s, C, "challenge")
    assert stage(s) == "lose" and s.g["pending"]["loser"] == B
    lose(s, B, 0)
    assert s.g["revealed"][B] == ["Guardian"] and len(s.g["hand"][C]) == 2
    assert s.g["coins"][A] == 4 and s.g["coins"][B] == 0
    assert s.g["pending"]["actor"] == B
    check_invariants(s)


def test_block_challenger_with_one_card_eliminated_block_stands():
    s = game(n=3)
    rig(s, A=["Smuggler", "Banker"], B=["Broker", "Agent"], C=["Guardian", "Banker"])
    kill(s, C, "Banker")
    act(s, A, "steal", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    respond(s, B, "block", "Broker")
    respond(s, C, "challenge")                                     # single card: auto-reveal
    assert not s.g["hand"][C] and s.g["coins"][A] == 2
    assert s.g["pending"]["actor"] == B
    check_invariants(s)


# ---------------------------------------------------------------- 2. tax proven

def test_tax_proven_card_replaced_challenger_loses_tax_resolves():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    act(s, A, "tax")
    respond(s, B, "challenge")
    assert stage(s) == "lose" and s.g["pending"]["loser"] == B
    # A revealed + replaced: still 2 hidden cards, nothing revealed
    assert len(s.g["hand"][A]) == 2 and s.g["revealed"][A] == []
    lose(s, B, 1)
    assert s.g["revealed"][B] == ["Smuggler"] and s.g["coins"][A] == 5
    assert s.g["pending"]["actor"] == B
    check_invariants(s)


def test_tax_proven_challenger_eliminated_tax_still_resolves_3p():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    kill(s, B, "Smuggler")
    act(s, A, "tax")
    respond(s, B, "challenge")
    assert not s.g["hand"][B]
    assert s.g["coins"][A] == 5 and s.g["pending"]["actor"] == C  # B skipped
    check_invariants(s)


# ---------------------------------------------------------------- 3. strike

def test_strike_target_loses_challenge_can_still_block():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    act(s, A, "strike", B)
    respond(s, B, "challenge")
    lose(s, B, 1)                                                   # loses Smuggler
    assert stage(s) == "block" and waiting(s) == [B]
    assert s.state_for(B)["game"]["me"]["prompt"] == {"kind": "block", "roles": ["Guardian"]}
    respond(s, B, "block", "Guardian")
    respond(s, A, "pass"); respond(s, C, "pass")
    assert s.g["hand"][B] == ["Guardian"] and s.g["coins"][A] == 0
    assert s.g["pending"]["actor"] == B
    check_invariants(s)


def test_strike_target_loses_challenge_then_allows_double_loss_eliminated():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    act(s, A, "strike", B)
    respond(s, B, "challenge")
    lose(s, B, 1)
    respond(s, B, "allow")
    assert not s.g["hand"][B] and s.g["revealed"][B] == ["Smuggler", "Guardian"]
    assert s.g["pending"]["actor"] == C
    check_invariants(s)


def test_strike_target_wins_challenge_actor_loses_coins_stay_spent():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Banker", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    act(s, A, "strike", B)                                          # bluff
    respond(s, B, "challenge")
    assert s.g["pending"]["loser"] == A
    lose(s, A, 0)
    assert len(s.g["hand"][B]) == 2 and s.g["coins"][A] == 0
    assert s.g["pending"]["actor"] == B
    check_invariants(s)


def test_strike_target_with_one_card_loses_challenge_no_block_window():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    kill(s, B, "Smuggler")
    act(s, A, "strike", B)
    respond(s, B, "challenge")
    assert not s.g["hand"][B] and s.g["pending"]["actor"] == C
    check_invariants(s)


def test_strike_third_party_challenge_lost_then_target_blocks():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Banker"])
    act(s, A, "strike", B)
    respond(s, C, "challenge")
    lose(s, C, 0)
    assert stage(s) == "block" and waiting(s) == [B]
    respond(s, B, "block", "Guardian")
    respond(s, A, "challenge")                                      # B has Guardian
    lose(s, A, 0)
    assert len(s.g["hand"][B]) == 2 and s.g["pending"]["actor"] == B
    check_invariants(s)


def test_strike_block_bluff_caught_blocker_eliminated_no_second_loss_crash():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Smuggler", "Broker"],
        C=["Broker", "Banker"])
    act(s, A, "strike", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    respond(s, B, "block", "Guardian")
    respond(s, C, "challenge")
    lose(s, B, 0)                                                   # bluff: loses one ...
    # ... then the strike resolves and takes the other: B is out
    assert stage(s) != "lose" or s.g["pending"]["loser"] != B or len(s.g["hand"][B]) == 1
    if stage(s) == "lose":
        lose(s, B, 0)
    assert not s.g["hand"][B] and s.g["pending"]["actor"] == C
    check_invariants(s)


# ---------------------------------------------------------------- 4. coins / forced coup

def test_ten_coins_only_coup_legal_and_other_actions_rejected():
    s = game(n=2)
    rig(s, coins={"A": 10}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    assert [a["action"] for a in s.legal_actions(A)] == ["coup"]
    for a, tgt in (("income", None), ("tax", None), ("aid", None), ("strike", B),
                   ("steal", B), ("exchange", None)):
        assert invalid(act(s, A, a, tgt))
    assert s.g["coins"][A] == 10 and stage(s) == "turn"


def test_timeout_with_ten_coins_forces_coup():
    s = game(n=2)
    rig(s, coins={"A": 12}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.tick(s.gen)
    assert s.g["coins"][A] == 5 and stage(s) == "lose" and s.g["pending"]["loser"] == B
    check_invariants(s)


def test_exactly_seven_coins_coup_and_others_legal():
    s = game(n=2)
    rig(s, coins={"A": 7}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    legal = [a["action"] for a in s.legal_actions(A)]
    assert "coup" in legal and "income" in legal and "strike" in legal
    act(s, A, "coup", B)
    assert s.g["coins"][A] == 0


def test_six_coins_no_coup():
    s = game(n=2)
    rig(s, coins={"A": 6}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    assert "coup" not in [a["action"] for a in s.legal_actions(A)]
    assert invalid(act(s, A, "coup", B))


def test_idle_turn_takes_income_below_forced_coup():
    """Decided 2026-09-23: an idle/absent actor plays passively. With 7-9 coins
    (Coup NOT mandatory) a timeout takes Income; only at 10+ is the Coup forced."""
    s = game(n=2)
    rig(s, coins={"A": 7}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.tick(s.gen)
    assert s.g["coins"][A] == 8 and s.g["pending"]["actor"] == B
    s = game(n=2)
    rig(s, coins={"A": 10}, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.tick(s.gen)
    assert s.g["coins"][A] == 3 and stage(s) == "lose"


def test_strike_needs_three_coins_and_cannot_target_self_or_dead():
    s = game(n=3)
    rig(s, coins={"A": 2}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    assert invalid(act(s, A, "strike", B))
    s.g["coins"][A] = 3
    kill(s, C, "Broker"); kill(s, C, "Broker"); s.g["coins"][C] = 0
    assert invalid(act(s, A, "strike", C))
    assert invalid(act(s, A, "strike", A))
    assert s.g["coins"][A] == 3 and stage(s) == "turn"


def test_steal_from_zero_and_one_coin():
    s = game(n=2)
    rig(s, coins={"B": 0}, A=["Smuggler", "Banker"], B=["Guardian", "Agent"])
    act(s, A, "steal", B); respond(s, B, "pass"); respond(s, B, "allow")
    assert s.g["coins"][A] == 2 and s.g["coins"][B] == 0
    check_invariants(s)


# ---------------------------------------------------------------- 5. elimination mid-flow

def test_steal_target_eliminated_by_own_failed_challenge_steal_takes_nothing():
    s = game(n=3)
    rig(s, coins={"B": 5}, A=["Smuggler", "Banker"], B=["Guardian", "Agent"],
        C=["Broker", "Broker"])
    kill(s, B, "Agent")
    act(s, A, "steal", B)
    respond(s, B, "challenge")                                      # A has Smuggler
    assert not s.g["hand"][B] and s.g["coins"][B] == 0
    assert s.g["coins"][A] == 2 and s.g["pending"]["actor"] == C
    check_invariants(s)


def test_actor_eliminated_challenging_a_true_block_turn_advances():
    s = game(n=3)
    rig(s, A=["Agent", "Guardian"], B=["Banker", "Smuggler"], C=["Broker", "Broker"])
    kill(s, A, "Guardian")
    act(s, A, "aid")
    respond(s, B, "block", "Banker")
    respond(s, A, "challenge")
    assert not s.g["hand"][A] and s.g["coins"][A] == 0
    assert s.g["pending"]["actor"] == B and stage(s) == "turn"
    check_invariants(s)


def test_eliminating_current_actor_on_bluff_turn_passes_to_next_alive():
    s = game(n=4)
    rig(s, A=["Agent", "Guardian"], B=["Banker", "Smuggler"], C=["Broker", "Broker"],
        D=["Banker", "Agent"])
    kill(s, A, "Guardian")
    kill(s, B, "Smuggler"); kill(s, B, "Banker"); s.g["coins"][B] = 0   # B already out
    act(s, A, "tax")                                                # bluff
    respond(s, D, "challenge")
    assert not s.g["hand"][A]
    assert s.g["pending"]["actor"] == C                             # skips dead B
    check_invariants(s)


def test_winner_declared_mid_response_window():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    kill(s, B, "Smuggler")
    act(s, A, "tax")
    respond(s, B, "challenge")
    assert s.phase == "game_end" and s.g["winner"] == A
    assert s.state_for(A)["game"]["pending"]["stage"] == "over"
    assert invalid(respond(s, B, "pass"))
    assert invalid(act(s, A, "income"))
    check_invariants(s)


def test_bluffed_block_blocker_eliminated_strike_on_dead_target_is_noop():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Smuggler", "Banker"],
        C=["Broker", "Broker"])
    kill(s, B, "Banker"); kill(s, C, "Broker")
    act(s, A, "strike", B)
    respond(s, B, "pass"); respond(s, C, "pass")
    respond(s, B, "block", "Guardian")
    respond(s, C, "challenge")                                      # B bluffing: B out
    assert not s.g["hand"][B] and s.phase == "playing"
    assert s.g["pending"]["actor"] == C
    check_invariants(s)


# ---------------------------------------------------------------- 6. exchange

def test_exchange_with_one_card_keeps_exactly_one_of_three():
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler"])
    kill(s, A, "Agent")
    act(s, A, "exchange"); respond(s, B, "pass")
    prompt = s.state_for(A)["game"]["me"]["prompt"]
    assert prompt["kind"] == "exchange" and len(prompt["pool"]) == 3 and prompt["keep"] == 1
    assert invalid(s.game_action(A, {"t": "keep", "cards": [0, 1]}))
    assert invalid(s.game_action(A, {"t": "keep", "cards": []}))
    assert invalid(s.game_action(A, {"t": "keep", "cards": [3]}))
    s.game_action(A, {"t": "keep", "cards": [2]})
    assert s.g["hand"][A] == [prompt["pool"][2]] and s.g["exchange_draw"] is None
    check_invariants(s)


def test_exchange_duplicate_or_bool_indices_rejected():
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "exchange"); respond(s, B, "pass")
    for bad in ([0, 0], [True, 1], [0, -1], [0, 1.0], [0, "1"], None, [0, 1, 2]):
        assert invalid(s.game_action(A, {"t": "keep", "cards": bad}))
    assert stage(s) == "exchange"
    check_invariants(s)


def test_exchange_timeout_keeps_hand_returns_draw():
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "exchange"); respond(s, B, "pass")
    assert len(s.g["deck"]) == TOTAL_CARDS - 4 - 2
    s.tick(s.gen)
    assert s.g["hand"][A] == ["Broker", "Agent"] and s.g["exchange_draw"] is None
    assert len(s.g["deck"]) == TOTAL_CARDS - 4 and s.g["pending"]["actor"] == B
    check_invariants(s)


def test_exchange_six_players_deck_never_short():
    s = game(n=1, bots=5)
    assert len(s.g["deck"]) == 3
    tok = s.g["seats"][0]
    give(s, tok, "Broker")
    act(s, tok, "exchange")
    while stage(s) == "challenge":
        s.run_bot(waiting(s)[0])
    assert stage(s) == "exchange" and len(s.g["exchange_draw"]) == 2
    check_invariants(s)


def test_exchange_proven_under_challenge_then_exchange_happens():
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler", ])
    act(s, A, "exchange")
    respond(s, B, "challenge")
    lose(s, B, 0)
    assert stage(s) == "exchange" and len(s.g["exchange_draw"]) == 2
    check_invariants(s)


# ---------------------------------------------------------------- 7. bots

def test_bot_target_of_steal_allows_and_bot_in_waiting_passes():
    s = game(n=1, bots=2, seed=3)
    b1, b2 = s.g["seats"][1], s.g["seats"][2]
    give(s, A, "Smuggler")
    act(s, A, "steal", b1)
    assert s.next_bot_action()[1] in (b1, b2)
    while stage(s) != "turn":
        s.run_bot(s.next_bot_action()[1])
    assert s.g["coins"][A] == 4 and s.g["coins"][b1] == 0 and s.g["pending"]["actor"] == b1
    check_invariants(s)


def test_bot_with_ten_coins_coups_and_bot_lose_prompt():
    s = game(n=1, bots=1, seed=3)
    bot = s.g["seats"][1]
    s.g["turn"] = 1
    s.g["pending"] = {"stage": "turn", "actor": bot}
    s.g["coins"][bot] = 10
    s.run_bot(bot)
    assert s.g["coins"][bot] == 3 and stage(s) == "lose" and s.g["pending"]["loser"] == A
    lose(s, A, 0)
    # A coups the bot; the bot answers its own lose prompt
    s.g["coins"][A] = 7
    act(s, A, "coup", bot)
    assert stage(s) == "lose" and s.next_bot_action()[1] == bot
    s.run_bot(bot)
    assert len(s.g["revealed"][bot]) == 1
    check_invariants(s)


def test_stale_bot_run_is_ignored():
    s = game(n=1, bots=2, seed=3)
    b1, b2 = s.g["seats"][1], s.g["seats"][2]
    give(s, A, "Banker")
    act(s, A, "tax")
    s.run_bot(b1); s.run_bot(b2)                                   # both pass -> b1's turn
    assert s.g["pending"]["actor"] == b1
    before = (s.g["coins"][b1], s.g["coins"][b2], s.gen)
    assert s.run_bot(b2) == [] and (s.g["coins"][b1], s.g["coins"][b2], s.gen) == before
    assert s.run_bot(A) == []                                       # a human token
    check_invariants(s)


@pytest.mark.parametrize("seed", range(40))
def test_full_bot_game_terminates(seed):
    s = game(n=1, bots=5, seed=seed)
    for _ in range(3000):
        if s.phase != "playing":
            break
        due = s.next_bot_action()
        if due:
            s.run_bot(due[1])
        else:
            s.tick(s.gen)                                           # human idles
        check_invariants(s)
    assert s.phase == "game_end" and s.g["winner"] is not None


# ---------------------------------------------------------------- 8. timeouts

def test_tick_stale_gen_is_ignored_every_stage():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    old = s.gen
    act(s, A, "strike", B)
    assert s.tick(old) == [] and stage(s) == "challenge"
    assert s.tick(s.gen - 1) == [] and stage(s) == "challenge"


def test_timeout_each_stage_semantics():
    # challenge -> claim accepted; block -> allow; lose -> first card
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    act(s, A, "strike", B)
    respond(s, C, "pass")
    s.tick(s.gen)
    assert stage(s) == "block"
    s.tick(s.gen)
    assert stage(s) == "lose" and s.g["pending"]["loser"] == B
    s.tick(s.gen)
    assert s.g["revealed"][B] == ["Guardian"] and s.g["pending"]["actor"] == B
    check_invariants(s)
    # block_challenge -> block stands
    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Smuggler", "Broker"])
    act(s, A, "aid"); respond(s, B, "block", "Banker")
    s.tick(s.gen)
    assert s.g["coins"][A] == 2 and s.g["pending"]["actor"] == B
    check_invariants(s)


def test_timeout_turn_income():
    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Smuggler", "Broker"])
    s.tick(s.gen)
    assert s.g["coins"][A] == 3 and s.g["pending"]["actor"] == B


def test_every_stage_transition_bumps_gen():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Broker"])
    g0 = s.gen
    act(s, A, "strike", B); g1 = s.gen; assert g1 > g0
    respond(s, B, "pass"); assert s.gen == g1                      # still waiting on C
    respond(s, C, "pass"); g2 = s.gen; assert g2 > g1 and stage(s) == "block"
    respond(s, B, "allow"); assert s.gen > g2 and stage(s) == "lose"


# ---------------------------------------------------------------- 9. turn order

def test_turn_order_skips_multiple_dead_and_wraps():
    s = game(n=4)
    rig(s, coins={"C": 7}, C=["Agent", "Banker"], D=["Guardian", "Smuggler"],
        A=["Broker", "Broker"], B=["Banker", "Guardian"])
    kill(s, D, "Guardian"); kill(s, A, "Broker"); kill(s, A, "Broker"); s.g["coins"][A] = 0
    act(s, C, "coup", D)                                            # D auto-reveals, out
    assert s.g["pending"]["actor"] == B                             # D, A dead -> wrap to B
    check_invariants(s)


# ---------------------------------------------------------------- races / ordering

def test_second_challenger_after_first_resolves_is_rejected():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    act(s, A, "tax")
    respond(s, B, "challenge")
    assert invalid(respond(s, C, "challenge"))                      # stage is now lose(B)
    assert invalid(lose(s, C, 0))
    lose(s, B, 0)
    assert s.g["coins"][A] == 5 and len(s.g["hand"][C]) == 2


def test_double_pass_and_wrong_verb_per_stage():
    s = game(n=3)
    rig(s, A=["Smuggler", "Banker"], B=["Broker", "Agent"], C=["Guardian", "Banker"])
    act(s, A, "steal", B)
    respond(s, B, "pass")
    assert invalid(respond(s, B, "pass"))
    assert invalid(respond(s, C, "allow"))
    assert invalid(respond(s, C, "block", "Broker"))
    respond(s, C, "pass")
    assert invalid(respond(s, B, "pass"))                           # block stage wants allow/block
    assert invalid(respond(s, B, "challenge"))
    assert invalid(respond(s, A, "allow"))                          # actor not waiting
    assert stage(s) == "block"


def test_reconnect_during_pending_prompt_keeps_prompt():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "tax")
    gen = s.gen
    s.leave(B)
    assert not s.players[B].connected and stage(s) == "challenge"
    p, fx = s.join(B, "Bob")
    assert p is s.players[B] and p.connected and s.gen == gen
    assert s.state_for(B)["game"]["me"]["prompt"] == {"kind": "challenge"}
    respond(s, B, "pass")
    assert s.g["coins"][A] == 5


def test_spectator_cannot_act_or_respond():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.join("tokenE_eve", "Eve")
    act(s, A, "tax")
    assert invalid(respond(s, "tokenE_eve", "challenge"))
    assert s.state_for("tokenE_eve")["game"]["me"] is None


@pytest.mark.parametrize("msg", [
    {"t": "respond", "choice": ["pass"]}, {"t": "respond", "choice": None},
    {"t": "respond", "choice": "block", "role": ["Banker"]},
    {"t": "respond", "choice": "block", "role": "Guardian"},
    {"t": "lose", "card": True}, {"t": "lose", "card": 99}, {"t": "lose", "card": -1},
    {"t": "keep", "cards": [0, 1]}, {"t": ["respond"]}, {"t": {"a": 1}},
])
def test_malformed_responses_in_block_stage(msg):
    s = game(n=2)
    rig(s, A=["Agent", "Guardian"], B=["Banker", "Smuggler"])
    act(s, A, "aid")
    assert invalid(s.game_action(B, msg))
    assert stage(s) == "block" and s.g["coins"][A] == 2


# ---------------------------------------------------------------- UI-facing state hygiene

def test_public_pending_has_no_stale_loser_after_lose_stage():
    s = game(n=3)
    rig(s, coins={"A": 3}, A=["Agent", "Banker"], B=["Guardian", "Smuggler"],
        C=["Broker", "Banker"])
    act(s, A, "strike", B)
    respond(s, C, "challenge")
    lose(s, C, 0)                                                   # C lost the challenge
    assert stage(s) == "block"
    assert s.state_for(B)["game"]["pending"]["loser"] is None


# ---------------------------------------------------------------- randomized fuzz

def _random_msg(s, rng, tok):
    kind = rng.random()
    others = [t for t in s.g["seats"] if t != tok]
    if kind < 0.35:
        a = rng.choice(["income", "aid", "coup", "tax", "strike", "steal", "exchange", "x"])
        m = {"t": "act", "action": a}
        if rng.random() < 0.9:
            m["target"] = s.players[rng.choice(others + [tok])].pid
        return m
    if kind < 0.75:
        return {"t": "respond", "choice": rng.choice(["pass", "challenge", "allow", "block", "?"]),
                "role": rng.choice(list(ROLES) + [None])}
    if kind < 0.87:
        return {"t": "lose", "card": rng.choice([0, 1, 2, -1, True])}
    n = rng.choice([0, 1, 2, 3])
    return {"t": "keep", "cards": rng.sample(range(4), n)}


@pytest.mark.parametrize("seed", range(150))
def test_fuzz_random_inputs_preserve_invariants(seed):
    rng = random.Random(seed)
    n = 2 + seed % 3
    s = game(n=n, bots=seed % 3, seed=seed)
    for _ in range(1500):
        if s.phase != "playing":
            break
        r = rng.random()
        before = s.gen
        if r < 0.08:
            s.tick(s.gen)
        elif r < 0.12:
            s.tick(s.gen - 1)                                       # stale
            assert s.gen == before
        elif r < 0.25:
            due = s.next_bot_action()
            if due:
                s.run_bot(due[1])
            else:
                s.run_bot(rng.choice(s.g["seats"]))                 # stale/wrong bot
        elif r < 0.27:
            tok = rng.choice([A, B, C, D][:n])
            s.leave(tok); s.join(tok)
        else:
            tok = rng.choice(s.g["seats"])
            if s.players[tok].is_bot:
                continue
            p = s.g["pending"]
            # bias toward the player whose input is awaited
            if rng.random() < 0.7:
                if p["stage"] == "turn":
                    tok = p["actor"]
                elif p.get("waiting"):
                    cand = [t for t in p["waiting"] if not s.players[t].is_bot]
                    if cand:
                        tok = rng.choice(cand)
            s.game_action(tok, _random_msg(s, rng, tok))
        check_invariants(s)
    # drive to completion with timeouts: game must terminate
    for _ in range(3000):
        if s.phase != "playing":
            break
        s.tick(s.gen)
        check_invariants(s)
    assert s.phase == "game_end"
