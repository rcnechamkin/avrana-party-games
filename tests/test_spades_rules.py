"""Characterization of games.spades.rules (AVR-312): today's behaviour, pinned before any migration.

Pure functions only. This file imports nothing of this repository except the rules module under
test (the first test enforces that), so a native re-home of Spades can run it against its own
rules module by changing the one import line. Every expected value below is a literal worked out
by hand from the rules of the game as `rules.py` implements them, never a call back into `rules`.
Each test names the rule it pins; if a rule is changed on purpose, change its test with it.
"""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games.spades import rules


def bids(a, b, c, d):
    """Bids by seat; seats 0 and 2 are one team, 1 and 3 the other."""
    return {0: a, 1: b, 2: c, 3: d}


def test_this_file_imports_only_the_rules_module():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported |= {"%s.%s" % (node.module, alias.name) for alias in node.names}
    project = {name for name in imported if name.split(".")[0] not in sys.stdlib_module_names}
    assert project == {rules.__name__}


# ---------------- constants, deck, cards ----------------

def test_constants_and_deck_order_are_the_dealing_contract():
    assert rules.RANKS == "23456789TJQKA" and rules.SUITS == "SHDC"
    assert (rules.BAG_LIMIT, rules.BAG_PENALTY) == (10, 100)
    assert len(rules.DECK) == 52 and len(set(rules.DECK)) == 52
    # suit-major, rank ascending inside a suit: a seeded shuffle of this exact order is what makes
    # a dealt hand reproducible
    assert rules.DECK[:13] == ["2S", "3S", "4S", "5S", "6S", "7S", "8S", "9S", "TS", "JS", "QS", "KS", "AS"]
    assert rules.DECK[13:26] == ["2H", "3H", "4H", "5H", "6H", "7H", "8H", "9H", "TH", "JH", "QH", "KH", "AH"]
    assert rules.DECK[26:39] == ["2D", "3D", "4D", "5D", "6D", "7D", "8D", "9D", "TD", "JD", "QD", "KD", "AD"]
    assert rules.DECK[39:] == ["2C", "3C", "4C", "5C", "6C", "7C", "8C", "9C", "TC", "JC", "QC", "KC", "AC"]


def test_rank_and_suit_of_read_the_two_character_card():
    assert [rules.rank_of(r + "H") for r in "23456789TJQKA"] == list(range(13))
    assert rules.rank_of("TD") == 8 and rules.rank_of("AS") == 12 and rules.rank_of("2C") == 0
    assert [rules.suit_of(c) for c in ("AS", "2H", "TD", "KC")] == ["S", "H", "D", "C"]


def test_sort_hand_is_spades_high_to_low_then_hearts_diamonds_clubs():
    hand = ["2C", "AH", "KS", "9D", "AS", "3H", "TC"]
    assert rules.sort_hand(hand) == ["AS", "KS", "AH", "3H", "9D", "TC", "2C"]
    assert hand == ["2C", "AH", "KS", "9D", "AS", "3H", "TC"]      # a new list: the dealt hand keeps its order
    high_to_low = "AKQJT98765432"
    assert rules.sort_hand(list(reversed(rules.DECK))) == (
        [r + "S" for r in high_to_low] + [r + "H" for r in high_to_low]
        + [r + "D" for r in high_to_low] + [r + "C" for r in high_to_low])
    assert rules.sort_hand([]) == []


# ---------------- trick_winner ----------------

def test_trick_winner_highest_card_of_the_led_suit_wins_when_nobody_trumps():
    assert rules.trick_winner([(0, "5H"), (1, "KH"), (2, "AH"), (3, "2D")]) == 2
    assert rules.trick_winner([(0, "2H"), (1, "3H"), (2, "4H"), (3, "5H")]) == 3
    # an off-suit ace is a discard, not a winner: the leader keeps the trick
    assert rules.trick_winner([(0, "5H"), (1, "AD"), (2, "KC"), (3, "2D")]) == 0


def test_trick_winner_any_spade_beats_the_led_suit_and_the_highest_spade_wins():
    assert rules.trick_winner([(0, "AH"), (1, "2S"), (2, "KH"), (3, "QH")]) == 1      # the lowest trump takes the ace
    assert rules.trick_winner([(0, "AH"), (1, "2S"), (2, "9S"), (3, "QH")]) == 2      # the highest of two trumps
    # a spade lead is beaten only by a higher spade, never by an off-suit ace
    assert rules.trick_winner([(0, "2S"), (1, "AH"), (2, "AD"), (3, "AC")]) == 0
    assert rules.trick_winner([(3, "2S"), (0, "AS"), (1, "KH"), (2, "3S")]) == 0
    assert rules.trick_winner([(2, "KS"), (3, "AH"), (0, "QS"), (1, "JS")]) == 2


def test_trick_winner_returns_the_seat_not_the_play_order():
    # played by seats 3, 0, 1, 2: the winning card is the third one played, from seat 1
    assert rules.trick_winner([(3, "9H"), (0, "TH"), (1, "AH"), (2, "2H")]) == 1
    # the lone trump is again the third card played, this time from seat 0
    assert rules.trick_winner([(2, "9H"), (3, "TH"), (0, "2S"), (1, "AH")]) == 0


# ---------------- legal_plays ----------------

def test_legal_plays_must_follow_the_led_suit_when_able():
    hand = ["AS", "2H", "9H", "3C"]
    assert rules.legal_plays(hand, [(0, "KH")], False) == ["2H", "9H"]          # hand order is kept
    assert rules.legal_plays(hand, [(0, "KH")], True) == ["2H", "9H"]           # broken spades are no way out of following
    # the led suit is the FIRST card on the table, not the last
    assert rules.legal_plays(["3H", "4D"], [(0, "KH"), (1, "2D")], False) == ["3H"]
    # a led spade must be followed even while spades are unbroken
    assert rules.legal_plays(["2S", "9H", "KC"], [(0, "AS")], False) == ["2S"]


def test_legal_plays_a_void_hand_may_play_anything_including_a_spade_while_unbroken():
    assert rules.legal_plays(["AS", "3C"], [(0, "KD")], False) == ["AS", "3C"]
    assert rules.legal_plays(["9H", "KC"], [(0, "AS")], False) == ["9H", "KC"]


def test_legal_plays_spades_cannot_be_led_until_broken_unless_the_hand_is_all_spades():
    hand = ["AS", "2S", "9H", "KC"]
    assert rules.legal_plays(hand, [], False) == ["9H", "KC"]
    assert rules.legal_plays(hand, [], True) == ["AS", "2S", "9H", "KC"]
    assert rules.legal_plays(["AS", "2S"], [], False) == ["AS", "2S"]
    assert rules.legal_plays(["9H"], [], False) == ["9H"]


# ---------------- score_hand ----------------

def test_score_hand_exact_bid_makes_the_contract_with_no_bags():
    res = rules.score_hand(bids(3, 3, 3, 3), {0: 3, 2: 3, 1: 3, 3: 4}, {0: 0, 1: 0})
    assert res[0] == {"delta": 60, "bags": 0, "made": True, "bid": 6, "tricks": 6, "nil": []}
    # one overtrick is one point and one bag on top of the contract
    assert res[1] == {"delta": 61, "bags": 1, "made": True, "bid": 6, "tricks": 7, "nil": []}
    assert sorted(res) == [0, 1]


def test_score_hand_bag_penalty_fires_exactly_at_ten_bags():
    tricks = {0: 4, 2: 3, 1: 3, 3: 3}                                  # team 0: bid 6, takes 7, one bag
    nine = rules.score_hand(bids(3, 3, 3, 3), tricks, {0: 8, 1: 0})
    assert (nine[0]["delta"], nine[0]["bags"]) == (61, 9)             # nine bags: no penalty yet
    ten = rules.score_hand(bids(3, 3, 3, 3), tricks, {0: 9, 1: 0})
    assert (ten[0]["delta"], ten[0]["bags"]) == (61 - 100, 0)         # the tenth bag costs 100 and the count restarts


def test_score_hand_charges_one_penalty_per_ten_bags_in_a_single_hand():
    # team 0 bids 2 and takes all 13: 11 bags on top of the 9 it carried is 20, so two penalties
    res = rules.score_hand(bids(1, 1, 1, 1), {0: 7, 2: 6, 1: 0, 3: 0}, {0: 9, 1: 0})
    assert (res[0]["delta"], res[0]["bags"]) == (20 + 11 - 200, 0)
    assert (res[1]["delta"], res[1]["bags"], res[1]["made"]) == (-20, 0, False)


def test_score_hand_a_set_team_loses_ten_per_bid_trick_and_keeps_its_bags():
    res = rules.score_hand(bids(4, 3, 3, 3), {0: 3, 2: 2, 1: 4, 3: 4}, {0: 8, 1: 0})
    assert res[0] == {"delta": -70, "bags": 8, "made": False, "bid": 7, "tricks": 5, "nil": []}


def test_score_hand_failed_nil_still_counts_its_tricks_toward_the_team():
    res = rules.score_hand(bids("nil", 3, 3, 3), {0: 1, 2: 3, 1: 4, 3: 5}, {0: 0, 1: 0})
    assert res[0]["nil"] == [(0, False, -100)]
    # the nil bidder's trick is a trick for the team: 4 taken against a bid of 3 makes it, with a bag
    assert (res[0]["bid"], res[0]["tricks"], res[0]["made"]) == (3, 4, True)
    assert (res[0]["delta"], res[0]["bags"]) == (-100 + 30 + 1, 1)


def test_score_hand_a_team_with_no_numeric_bid_banks_every_trick_as_a_bag():
    res = rules.score_hand(bids("nil", 6, "nil", 6), {0: 0, 2: 1, 1: 6, 3: 6}, {0: 0, 1: 0})
    assert res[0]["nil"] == [(0, True, 100), (2, False, -100)]
    assert (res[0]["delta"], res[0]["bags"], res[0]["made"]) == (0 + 1, 1, True)
    clean = rules.score_hand(bids("nil", 6, "nil", 6), {0: 0, 2: 0, 1: 6, 3: 7}, {0: 0, 1: 0})
    assert (clean[0]["delta"], clean[0]["bags"]) == (200, 0)          # two clean nils, nothing to bag


def test_score_hand_nil_bonus_and_penalty_are_parameters():
    ok = rules.score_hand(bids("nil", 3, 3, 3), {0: 0, 2: 3, 1: 5, 3: 5}, {0: 0, 1: 0},
                          nil_bonus=50, nil_penalty=150)
    assert ok[0]["nil"] == [(0, True, 50)] and ok[0]["delta"] == 50 + 30
    bad = rules.score_hand(bids("nil", 3, 3, 3), {0: 2, 2: 3, 1: 4, 3: 4}, {0: 0, 1: 0},
                           nil_bonus=50, nil_penalty=150)
    assert bad[0]["nil"] == [(0, False, -150)]
