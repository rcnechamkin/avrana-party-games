"""Characterization of SpadesSession's match rules, turn order, clocks and private view (AVR-312):
session level, no sockets.

Hub-coupled on purpose. It drives the fork's own GameSession (join, ready, start, tick, the `g`
dict, _do_bid / _do_play, state_for), so it pins what the donor does today and gives a native
re-home something to be compared with. It is NOT a portable rules test (tests/test_spades_rules.py
is that); expect to adapt it when the session class changes. Seeds are fixed, so every table, deal
and bot delay below is the same on every run; a test that reads a deadline freezes the session's
clocks (the `clock` fixture), so no host is too slow for it.

The last section pins today's gaps on purpose. They are the facts that
docs/findings/2026-10-07-spades-native-readiness.md relies on, not behaviour to keep: when a native
build changes one deliberately, change its pin in the same commit.
"""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import session as base_session
from games.spades import game as spades_game
from games.spades import rules
from games.spades.bots import RookieBot, StandardBot
from games.spades.game import SpadesSession


# ---------------- tables and moves ----------------

class Clock:
    """A frozen stand-in for the `time` module as core.session and games.spades.game read it: the
    wall clock a deadline is armed on and the monotonic clock its wait is measured on. A test moves
    both by hand, so a deadline is read exactly and a slow host cannot shift it."""

    def __init__(self):
        self.wall, self.mono = 1_000_000.0, 5_000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(base_session, "time", c)          # _bump, remaining, state_for, Player.joined_at
    monkeypatch.setattr(spades_game, "time", c)           # _arm_turn, _end_hand
    return c


def dealt(humans=2, seed=11, target=500, difficulty="standard", turn_seconds=30):
    """A dealt table through the fork's own lobby: `humans` ready players join in order, the
    start's countdown is run out, hand 1 is in bidding. Returns (session, human tokens, the fx the
    deal returned)."""
    s = SpadesSession(rng=random.Random(seed))
    toks = []
    for i in range(humans):
        tok = "human-token-%02d" % i
        s.join(tok, "H%d" % i, None)
        s.set_ready(tok, True)
        toks.append(tok)
    s.settings["target"] = target
    s.settings["difficulty"] = difficulty
    s.settings["turn_seconds"] = turn_seconds
    s.start(toks[0])
    fx = s.tick(s.gen)
    assert s.phase == "bidding" and s.g["hand_no"] == 1
    return s, toks, fx


def table(**options):
    """`dealt` without the deal's fx: the table most tests start from. Returns (session, tokens)."""
    s, toks, _ = dealt(**options)
    return s, toks


def party_table(humans, seed=5):
    """The same, seated the way a Party round seats a launch roster (GameSession.party_start)."""
    s = SpadesSession(rng=random.Random(seed))
    roster = [("party-token-%02d" % i, "P%d" % i) for i in range(humans)]
    s.party_start(roster)
    for tok, _ in roster:
        s.join(tok)                                         # the phones arrive
    s.tick(s.gen)                                           # every seat is here: the round starts
    return s, [tok for tok, _ in roster]


def bid_all(s, value=3):
    for _ in range(4):
        fx = s._do_bid(s.g["turn"], value)
        assert not any(f["kind"] == "invalid" for f in fx), fx


def play_card(s):
    """The seat to move plays its first legal card. Returns the fx of that play."""
    seat = s.g["turn"]
    card = rules.legal_plays(s.g["hands"][seat], s.g["trick"], s.g["spades_broken"])[0]
    fx = s._do_play(seat, card)
    assert not any(f["kind"] == "invalid" for f in fx), fx
    return fx


def play_hand(s):
    while s.phase == "playing":
        play_card(s)
    assert s.phase == "hand_end"


def scores(a, b):
    return {0: {"score": a, "bags": 0}, 1: {"score": b, "bags": 0}}


# ---------------- _maybe_finish: when the match ends ----------------

def test_the_match_is_won_at_the_target_not_a_point_before():
    s, _ = table(target=500)
    s.g["hand_no"] = 7
    s.g["scores"] = scores(499, 480)
    assert s._maybe_finish() is None
    assert s.phase == "bidding" and s.g["result"] is None
    s.g["scores"][0]["score"] = 500
    fx = s._maybe_finish()
    assert s.g["result"] == {"winner_team": 0, "scores": {"0": 500, "1": 480}, "hands": 7}
    assert s.phase == "game_end" and [f["kind"] for f in fx] == ["game_over", "game_end"]
    assert fx[0]["winner_team"] == 0


def test_either_team_can_win_and_the_target_setting_is_the_bar():
    for target in (200, 300, 400, 500):
        for team in (0, 1):
            s, _ = table(target=target)
            s.g["scores"] = scores(0, 0)
            s.g["scores"][team]["score"] = target - 1
            assert s._maybe_finish() is None, (target, team)
            s.g["scores"][team]["score"] = target
            assert s._maybe_finish() is not None, (target, team)
            assert s.g["result"]["winner_team"] == team and s.phase == "game_end"


def test_a_tie_at_or_over_the_target_plays_another_hand():
    for target, score in ((300, 300), (300, 320), (500, 640)):
        s, _ = table(target=target)
        s.g["scores"] = scores(score, score)
        assert s._maybe_finish() is None, (target, score)
        assert s.g["result"] is None and s.phase == "bidding"


def test_when_both_teams_are_over_the_target_the_higher_score_wins_not_the_first_over():
    for pair, winner in (((310, 340), 1), ((340, 310), 0), ((301, 300), 0)):
        s, _ = table(target=300)
        s.g["scores"] = scores(*pair)
        s._maybe_finish()
        assert s.g["result"] == {"winner_team": winner, "scores": {"0": pair[0], "1": pair[1]}, "hands": 1}


def test_the_recap_timer_either_ends_the_match_or_deals_the_next_hand():
    s, _ = table(target=300)
    bid_all(s)
    play_hand(s)
    s.g["scores"] = scores(320, 320)                      # tied over the target once the hand is scored
    s.tick(s.gen)
    assert (s.phase, s.g["hand_no"], s.g["result"]) == ("bidding", 2, None)
    bid_all(s)
    play_hand(s)
    s.g["scores"] = scores(320, 330)
    s.tick(s.gen)
    assert s.phase == "game_end" and s.g["hand_no"] == 2
    assert s.g["result"] == {"winner_team": 1, "scores": {"0": 320, "1": 330}, "hands": 2}


# ---------------- hands: dealer, reset, carried points and bags ----------------

def test_each_hand_rotates_the_dealer_by_one_and_resets_the_hand_but_not_the_match():
    s, _ = table()
    g = s.g
    dealer, last_deal = g["dealer"], None
    for hand_no in range(1, 6):                           # five hands: the dealer wraps past seat 3
        assert (s.phase, g["hand_no"], g["dealer"]) == ("bidding", hand_no, dealer)
        assert g["turn"] == (dealer + 1) % 4              # the first bid is left of the dealer
        assert g["bids"] == {0: None, 1: None, 2: None, 3: None}
        assert g["tricks_won"] == {0: 0, 1: 0, 2: 0, 3: 0}
        assert g["trick"] == [] and g["last_trick"] is None and g["played"] == []
        assert g["spades_broken"] is False and g["hand_result"] is None
        assert all(len(h) == 13 for h in g["hands"].values())
        assert sorted(c for h in g["hands"].values() for c in h) == sorted(rules.DECK)
        assert g["hands"] != last_deal                    # a fresh shuffle every hand
        last_deal = {seat: list(h) for seat, h in g["hands"].items()}
        before = {t: dict(g["scores"][t]) for t in (0, 1)}
        bid_all(s)
        assert s.phase == "playing" and g["turn"] == (dealer + 1) % 4   # and so is the first lead
        play_hand(s)
        for t in (0, 1):                                  # the hand's points join the match, its bags replace the count
            delta = g["hand_result"]["teams"][str(t)]["delta"]
            assert g["scores"][t]["score"] == before[t]["score"] + delta
            assert g["scores"][t]["bags"] == g["hand_result"]["teams"][str(t)]["bags"]
        s.tick(s.gen)                                     # the recap is over: nobody is near 500 yet
        dealer = (dealer + 1) % 4


def test_the_hand_result_is_the_scorecard_the_client_reads():
    s, _ = table(seed=51)
    nil_seat = (s.g["dealer"] + 1) % 4
    s._do_bid(nil_seat, "nil")                            # the first bidder goes nil, the other three bid 3
    for _ in range(3):
        s._do_bid(s.g["turn"], 3)
    play_hand(s)
    hr = s.g["hand_result"]
    assert set(hr) == {"teams", "bids", "tricks"} and set(hr["teams"]) == {"0", "1"}
    assert all(set(t) == {"delta", "bags", "made", "bid", "tricks", "nil"} for t in hr["teams"].values())
    assert hr["bids"] == {nil_seat: "nil", **{(nil_seat + i) % 4: 3 for i in (1, 2, 3)}}
    assert set(hr["tricks"]) == {0, 1, 2, 3} and sum(hr["tricks"].values()) == 13
    for team in (0, 1):                                   # a team's tricks are its two seats' tricks
        assert hr["teams"][str(team)]["tricks"] == hr["tricks"][team] + hr["tricks"][team + 2]
    nil_team, other = str(nil_seat % 2), str(1 - nil_seat % 2)
    assert (hr["teams"][nil_team]["bid"], hr["teams"][other]["bid"]) == (3, 6)      # a nil is no tricks of the bid
    ok = hr["tricks"][nil_seat] == 0
    assert hr["teams"][nil_team]["nil"] == [{"seat": nil_seat, "ok": ok, "delta": 100 if ok else -100}]
    assert hr["teams"][other]["nil"] == []


def test_bags_carried_into_a_hand_are_scored_and_the_new_count_is_carried_out():
    def one_hand(carried):
        s, _ = table(seed=31)
        s.g["scores"] = {0: {"score": 0, "bags": carried}, 1: {"score": 0, "bags": carried}}
        bid_all(s, 1)                                     # a bid of 2 a side: the stronger side takes bags
        play_hand(s)
        return s.g

    fresh, loaded = one_hand(0), one_hand(9)
    assert loaded["tricks_won"] == fresh["tricks_won"]                      # same deal, same play
    for team in (0, 1):
        over = fresh["scores"][team]["bags"]                                # bags earned this hand
        assert over >= 1, team
        assert fresh["scores"][team]["score"] - loaded["scores"][team]["score"] == 100, team
        assert loaded["scores"][team]["bags"] == 9 + over - 10, team


def test_bidding_and_card_play_go_clockwise_starting_left_of_the_dealer():
    s, _ = table(seed=14)
    g = s.g
    first = (g["dealer"] + 1) % 4
    bidders = []
    for _ in range(4):
        bidders.append(g["turn"])
        s._do_bid(g["turn"], 3)
    assert bidders == [(first + i) % 4 for i in range(4)] and bidders[-1] == g["dealer"]   # the dealer bids last
    assert s.phase == "playing" and g["turn"] == first    # and the opening lead is left of the dealer too
    tricks = 0
    while s.phase == "playing":
        lead, order = g["turn"], []
        for _ in range(4):
            order.append(g["turn"])
            play_card(s)
        assert order == [(lead + i) % 4 for i in range(4)], (tricks, order)   # a trick goes round the table
        tricks += 1
    assert tricks == 13


def test_the_winner_of_a_trick_leads_the_next_one():
    s, _ = table(seed=14)
    bid_all(s)
    g = s.g
    leaders, winners = [], []
    while s.phase == "playing":
        lead = g["turn"]
        assert not winners or lead == winners[-1], (len(winners), "the last trick's winner leads this one")
        leaders.append(lead)
        fx = []
        for _ in range(4):
            fx = play_card(s)
        winners.append(rules.trick_winner(g["last_trick"]["cards"]))
        assert g["last_trick"]["winner"] == winners[-1]
        assert [f["seat"] for f in fx if f["kind"] == "trick_won"] == [winners[-1]]
    assert len(leaders) == 13 and len(set(leaders)) > 1   # the lead really changed hands in this deal


# ---------------- the private view: hands, every viewer, every phase ----------------

VIEW_KEYS = {"kind", "stage", "seats", "my_seat", "hand", "turn", "trick", "last_trick",
             "spades_broken", "hand_no", "dealer", "turn_seconds", "scores", "target",
             "hand_result", "result"}
SEAT_KEYS = {"seat", "pid", "team", "bid", "tricks", "cards_left", "auto"}


def every_viewer(s):
    """(label, seat or None, state_for(...)) for every kind of viewer the server can serve."""
    g = s.g
    out = [("seat %d" % seat, seat, s.state_for(tok))
           for seat, tok in enumerate(g["seats"]) if not s.players[tok].is_bot]
    out += [("benched human", None, s.state_for(tok))
            for tok, p in s.players.items() if not p.is_bot and tok not in g["seats"]]
    out.append(("unknown token", None, s.state_for("a-token-that-never-joined")))
    out.append(("anonymous watcher", None, s.state_for(None)))
    out.append(("party spectator", None, s.state_for(None, spectator=True)))
    return out


def check_views(s):
    """Own hand and nothing else private, for every viewer, at this moment of the hand."""
    g = s.g
    public_game = public_envelope = None
    for label, seat, st in every_viewer(s):
        game = st["game"]
        assert set(game) == VIEW_KEYS and all(set(x) == SEAT_KEYS for x in game["seats"]), label
        assert game["my_seat"] == seat, label
        assert game["hand"] == (rules.sort_hand(g["hands"][seat]) if seat is not None else None), label
        if seat is not None:
            assert game["seats"][seat]["cards_left"] == len(game["hand"]), label
        # everything else in the game view, and in the envelope around it, is the same for everyone
        rest = {k: v for k, v in game.items() if k not in ("my_seat", "hand")}
        envelope = {k: v for k, v in st.items() if k not in ("now", "you", "game", "spectator")}
        public_game = rest if public_game is None else public_game
        public_envelope = envelope if public_envelope is None else public_envelope
        assert rest == public_game and envelope == public_envelope, label
        blob = json.dumps(st)
        for other, cards in g["hands"].items():
            if other != seat:
                assert not [c for c in cards if '"%s"' % c in blob], (label, "holds seat %d's cards" % other)
        for tok in s.players:
            assert tok not in blob, (label, "carries a player token")


def check_fx(s, fx, label):
    """What a phone is sent beside the state. core.net.push_all sends each fx without its routing
    key `to`, to everyone or only to the one player `to` names. Like a state, it carries no card
    that is still in a hand (a card just played is public) and no player token; an fx for one seat
    may carry that seat's own cards, nobody else's."""
    g = s.g
    for f in fx:
        seat = g["seats"].index(f["to"]) if f.get("to") in g["seats"] else None
        blob = json.dumps({k: v for k, v in f.items() if k != "to"})
        what = (label, f["kind"])
        for other, cards in g["hands"].items():
            if other != seat:
                assert not [c for c in cards if '"%s"' % c in blob], (what, "holds seat %d's cards" % other)
        for tok in s.players:
            assert tok not in blob, (what, "carries a player token")


def walk_one_hand_checking_views(s, deal_fx=()):
    """Bidding (before and after every bid), playing (after every card) and the recap: every viewer's
    state, and the fx the deal, each bid and each card returned, are checked at every step."""
    check_fx(s, deal_fx, "the deal")
    check_views(s)
    assert s.phase == "bidding"
    for _ in range(4):
        check_fx(s, s._do_bid(s.g["turn"], 3), "a bid")
        check_views(s)
    assert s.phase == "playing"
    while s.phase == "playing":
        check_fx(s, play_card(s), "a card")
        check_views(s)
    assert s.phase == "hand_end"
    assert all(h == [] for h in s.g["hands"].values())


def walk_one_hand_by_the_clock(s):
    """The same checks on a hand nobody plays: the turn clock runs out at every seat and the
    autopilot bids and plays, one tick at a time (core.net calls tick(gen) at each deadline). A seat
    with a connected human is also told in a toast that its time ran out."""
    check_views(s)
    while s.phase in ("bidding", "playing"):
        check_fx(s, s.tick(s.gen), "the turn clock")
        check_views(s)
    assert s.phase == "hand_end"


def test_every_seat_sees_only_its_own_hand_in_every_phase_and_nobody_else_sees_any():
    s, toks, deal_fx = dealt(humans=5, seed=21)           # four seats, all human, and a fifth who watches
    assert [s.players[t].is_bot for t in s.g["seats"]] == [False] * 4 and toks[4] not in s.g["seats"]
    assert len(every_viewer(s)) == 4 + 1 + 3
    walk_one_hand_checking_views(s, deal_fx)
    s.g["scores"] = scores(520, 400)
    check_fx(s, s.tick(s.gen), "the end of the match")    # the recap ends the match
    assert s.phase == "game_end"
    check_views(s)


def test_the_private_view_holds_at_a_table_with_bots_too():
    s, toks, deal_fx = dealt(humans=2, seed=22)
    assert sum(1 for t in s.g["seats"] if s.players[t].is_bot) == 2
    assert len(every_viewer(s)) == 2 + 3
    walk_one_hand_checking_views(s, deal_fx)
    check_fx(s, s.tick(s.gen), "the next deal")           # the recap is over: hand 2 is dealt, straight away
    assert (s.phase, s.g["hand_no"]) == ("bidding", 2)
    check_views(s)
    walk_one_hand_by_the_clock(s)                         # and hand 2 is played by the turn clock alone


# ---------------- seats, teams, settings, pacing ----------------

def test_join_order_fills_the_seats_and_teams_alternate_around_the_table():
    s, toks = table(humans=4, seed=41)
    assert s.g["seats"] == toks and not any(p.is_bot for p in s.players.values())
    assert [x["team"] for x in s.state_for(toks[0])["game"]["seats"]] == [0, 1, 0, 1]
    assert s._bot_view(0)["partner"] == 2 and s._bot_view(3)["partner"] == 1
    five = SpadesSession(rng=random.Random(42))
    for i in range(5):
        five.join("human-token-%02d" % i, "H%d" % i, None)
        five.set_ready("human-token-%02d" % i, True)
    five.start("human-token-00")
    fx = five.tick(five.gen)
    assert five.g["seats"] == ["human-token-%02d" % i for i in range(4)]
    assert five.participants == five.g["seats"]           # the fifth is not a participant
    assert [f["msg"] for f in fx if f["kind"] == "toast" and f["to"] == "human-token-04"] == \
        ["Table seats 4 — you're watching this one"]


def test_default_settings_and_what_validate_settings_accepts():
    s = SpadesSession(rng=random.Random(1))
    assert s.settings == {"target": 500, "seating": "partners", "difficulty": "standard",
                          "turn_seconds": 30, "nil_bonus": 100, "nil_penalty": 100}
    every = {"target": 200, "seating": "mixed", "difficulty": "rookie", "turn_seconds": 10,
             "nil_bonus": 5, "nil_penalty": 5, "unknown": 1}
    assert s.validate_settings(every) == {"target": 200, "seating": "mixed", "difficulty": "rookie",
                                          "turn_seconds": 10}           # nil points cannot be set
    assert [s.validate_settings({"target": t}) for t in (199, 250, 600)] == [{}, {}, {}]
    assert s.validate_settings({"turn_seconds": 60}) == {"turn_seconds": 60}
    assert s.validate_settings({"turn_seconds": 9}) == {} and s.validate_settings({"turn_seconds": 61}) == {}
    assert s.validate_settings({"seating": "teams", "difficulty": "hard"}) == {}


@pytest.mark.usefixtures("clock")
def test_bots_and_absent_humans_play_after_a_short_pause_and_the_autopilot_is_always_standard():
    s, toks = table(humans=2, seed=3, difficulty="rookie")
    bots = [s.players[t] for t in s.g["seats"] if s.players[t].is_bot]
    assert len(bots) == 2 and all(isinstance(s.g["bots"][b.token], RookieBot) for b in bots)
    assert isinstance(s.g["autopilot"], StandardBot)      # timeouts and absent humans: never the rookie tier
    assert s.remaining() == 30.0                          # the deal arms the default 30 s clock; each re-arm is pinned below
    bot_seat = s.g["seats"].index(bots[0].token)
    s.g["turn"] = s.g["seats"].index(toks[0])
    assert s.next_bot_action() is None                    # a connected human's turn is theirs
    s.g["turn"] = bot_seat
    bidding = [s.next_bot_action()[0] for _ in range(200)]
    assert all(1.3 <= d < 2.2 for d in bidding) and max(bidding) - min(bidding) > 0.5
    s.phase = "playing"
    playing = [s.next_bot_action()[0] for _ in range(200)]
    assert all(0.9 <= d < 1.8 for d in playing) and max(playing) - min(playing) > 0.5
    assert s.next_bot_action()[1] == bots[0].token
    s.phase = "bidding"
    s.leave(toks[0])                                      # a human who drops is on autopilot at once
    s.g["turn"] = s.g["seats"].index(toks[0])
    assert s.next_bot_action()[1] == toks[0] and s.state_for(toks[1])["game"]["seats"][0]["auto"]
    assert s.run_bot("some-other-token") == []            # a stale bot task acts for nobody else


def test_every_bid_and_every_card_restarts_the_turn_clock_from_the_setting(clock):
    s, _ = table(seed=14, turn_seconds=20)                # not the 30 s default, so a constant would show
    assert s.remaining() == 20.0 and s.deadline == clock.time() + 20      # the deal arms it
    for n in range(4):
        clock.advance(12)                                 # the seat on turn takes its time
        s._do_bid(s.g["turn"], 3)
        assert s.remaining() == 20.0, ("bid", n)          # and its bid starts the clock again for the next seat
    cards = 0
    while s.phase == "playing":
        clock.advance(12)
        play_card(s)
        cards += 1
        if s.phase == "playing":                          # mid-trick cards and the card that completes a trick
            assert s.remaining() == 20.0, ("card", cards)
    assert cards == 52                                    # the last card starts the recap instead (next test)


def test_the_hand_recap_lasts_fourteen_seconds_and_then_the_next_hand_is_dealt(clock):
    s, toks = table(seed=14)
    bid_all(s)
    play_hand(s)
    assert s.remaining() == 14.0 and s.deadline == clock.time() + 14
    shown = s.state_for(toks[0])                          # a browser counts down to the same moment
    assert shown["deadline"] - shown["now"] == 14_000
    clock.advance(14)
    assert s.remaining() == 0.0
    s.tick(s.gen)
    assert (s.phase, s.g["hand_no"], s.remaining()) == ("bidding", 2, 30.0)   # the deal starts the turn clock again


# ---------------- today's gaps, pinned on purpose (see the readiness packet) ----------------

def test_a_party_seated_game_reaches_game_end_with_no_outcome_and_no_result_to_report():
    s, toks = party_table(2)
    s.settings["target"] = 200
    ticks = 0
    while s.phase != "game_end" and ticks < 5000:
        s.tick(s.gen)
        ticks += 1
    assert s.phase == "game_end" and s.g["result"] is not None
    assert s.deadline is None                             # a party round holds the results screen
    assert s.take_outcome() is None                       # so core.net never reports `ended`
    assert s.game_result(lambda token: "participant-x") is None


def test_party_settings_and_lobby_verbs_are_refused_so_the_fork_defaults_stand():
    s, toks = party_table(2)
    s.set_settings(toks[0], {"target": 200, "turn_seconds": 10})
    assert (s.settings["target"], s.settings["turn_seconds"]) == (500, 30)
    assert s.set_ready(toks[0], True)[0]["kind"] == "invalid" and s.start(toks[0])[0]["kind"] == "invalid"
    s.to_lobby()                                          # what `again` does at the end: a lobby that is still a Party round's
    assert s.phase == "lobby" and s.party_round is True
    s.set_settings(toks[0], {"target": 200})
    assert s.settings["target"] == 500                    # refused here by the Party round, not by the phase
    assert s.set_ready(toks[0], True)[0]["kind"] == "invalid" and s.start(toks[0])[0]["kind"] == "invalid"


def test_one_human_cannot_start_a_table():
    lobby = SpadesSession(rng=random.Random(1))
    lobby.join("solo-token-00", "Solo", None)
    lobby.set_ready("solo-token-00", True)
    assert lobby.start("solo-token-00")[0]["kind"] == "invalid"     # MIN_PLAYERS is 2 in the lobby
    party = SpadesSession(rng=random.Random(1))
    party.party_start([("solo-token-00", "Solo")])
    party.join("solo-token-00")
    with pytest.raises(ValueError):                       # a one-seat Party round gets past that check and fails here
        party.tick(party.gen)


def test_a_fifth_party_player_has_no_seat_hand_or_place_in_the_participants():
    s, toks = party_table(5)
    assert s.g["seats"] == toks[:4] and s.participants == toks[:4]
    benched = s.state_for(toks[4])["game"]
    assert benched["my_seat"] is None and benched["hand"] is None


def test_everyone_leaving_returns_to_the_lobby_with_no_outcome_to_report():
    s, toks = party_table(2)
    for tok in toks:
        s.leave(tok)
    assert s.phase == "lobby" and s.participants == [] and s.players == {}
    assert s.party_round is True                          # still a Party round, with nobody in it
    assert s.take_outcome() is None
