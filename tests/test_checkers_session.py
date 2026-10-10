"""One Checkers match: seats, turns, versions, each seat's own view and how a game ends (AVR-238)."""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from checkers import rules
from checkers.rules import sq
from checkers.session import ENDINGS, Conflict, Match

ANA = {"participant": "participant-" + "a" * 32, "name": "Ana"}
BEN = {"participant": "participant-" + "b" * 32, "name": "Ben"}


def make(pieces, turn="w", clock=0):
    board = [None] * 64
    for (r, c), p in pieces.items():
        assert rules.is_dark(r, c), "test bug: piece on a light square"
        board[sq(r, c)] = p
    return {"board": board, "turn": turn, "clock": clock, "result": None}


def match(pieces=None, **kw):
    return Match([ANA, BEN], make(pieces, **kw) if pieces is not None else None)


def refused(m, seat, *args, op="move"):
    """Run an operation that must be refused, and prove it changed nothing."""
    before = (m.v, m.plies, list(m.state["board"]), m.state["turn"], m.ending, m.last)
    with pytest.raises(Conflict) as caught:
        getattr(m, op)(seat, *args)
    assert (m.v, m.plies, list(m.state["board"]), m.state["turn"], m.ending, m.last) == before
    return caught.value


# ---------------- seats ----------------

def test_the_first_player_listed_is_white_and_the_second_is_black():
    m = Match([ANA, BEN])
    assert (m.seat_of(ANA["participant"]), m.seat_of(BEN["participant"])) == ("w", "b")
    assert m.participants == {"w": ANA["participant"], "b": BEN["participant"]}
    swapped = Match([BEN, ANA])
    assert (swapped.seat_of(BEN["participant"]), swapped.seat_of(ANA["participant"])) == ("w", "b")


def test_nobody_else_has_a_seat():
    assert Match([ANA, BEN]).seat_of("participant-" + "c" * 32) is None
    assert Match([ANA, BEN]).seat_of(None) is None


def test_a_match_needs_exactly_two_different_players_and_a_running_position():
    for players in ([], [ANA], [ANA, BEN, {"participant": "participant-" + "c" * 32, "name": "Cal"}],
                    [ANA, dict(ANA)]):
        with pytest.raises(ValueError):
            Match(players)
    finished = make({(5, 2): "w"})
    finished["result"] = "w"
    with pytest.raises(ValueError):
        Match([ANA, BEN], finished)


def test_names_come_from_the_roster_and_are_always_text():
    m = Match([{"participant": ANA["participant"], "name": None}, {"participant": BEN["participant"]}])
    assert m.view()["names"] == {"w": "", "b": ""}
    assert Match([ANA, BEN]).view()["names"] == {"w": "Ana", "b": "Ben"}


# ---------------- what each seat is shown ----------------

def test_the_opening_view():
    m = Match([ANA, BEN])
    v = m.view("w")
    assert (v["v"], v["seat"], v["turn"]) == (1, "w", "w")
    assert v["board"] == rules.new_game()["board"]
    assert (v["lastMove"], v["result"], v["mustCapture"]) == (None, None, False)
    assert v["moves"] == rules.legal_moves(rules.new_game()) and len(v["moves"]) == 7


def test_only_the_seat_to_move_is_sent_its_moves():
    m = Match([ANA, BEN])
    assert m.view("w")["moves"]
    assert m.view("b")["moves"] == []              # black's turn has not come
    assert m.view(None)["moves"] == []             # a watcher is never offered a move
    assert m.view()["seat"] is None
    m.move("w", m.v, m.view("w")["moves"][0])
    assert m.view("w")["moves"] == []
    assert m.view("b")["moves"] and m.view("b")["turn"] == "b"
    assert m.view(None)["moves"] == [] and m.view(None)["turn"] == "b"


def test_a_watcher_sees_the_same_board_and_turn_as_the_players():
    m = Match([ANA, BEN])
    m.move("w", 1, m.view("w")["moves"][0])
    for key in ("v", "turn", "board", "lastMove", "result", "names"):
        assert m.view(None)[key] == m.view("w")[key] == m.view("b")[key]


def test_an_unknown_seat_is_a_watcher():
    assert Match([ANA, BEN]).view("x")["seat"] is None
    assert Match([ANA, BEN]).view("x")["moves"] == []


def test_a_view_is_a_copy():
    m = Match([ANA, BEN])
    v = m.view("w")
    v["board"][0] = "Z"
    v["moves"].clear()
    v["names"]["w"] = "Mallory"
    again = m.view("w")
    assert again["board"][0] != "Z" and again["moves"] and again["names"]["w"] == "Ana"


def test_every_view_is_plain_json():
    m = Match([ANA, BEN])
    for seat in ("w", "b", None):
        json.dumps(m.view(seat))
    m.resign("w")
    for seat in ("w", "b", None):
        assert json.loads(json.dumps(m.view(seat))) == m.view(seat)


def test_the_view_says_when_a_capture_is_compulsory():
    m = match({(5, 2): "w", (4, 3): "b", (6, 5): "w", (0, 1): "b"})
    v = m.view("w")
    assert v["mustCapture"] is True
    assert v["moves"] == [[sq(5, 2), sq(3, 4)]]
    assert match({(5, 2): "w", (0, 1): "b"}).view("w")["mustCapture"] is False
    assert m.view("b")["mustCapture"] is False         # not black's turn: nothing is offered


# ---------------- moving ----------------

def test_a_move_changes_the_board_the_turn_and_the_version_once():
    m = Match([ANA, BEN])
    path = m.view("w")["moves"][0]
    m.move("w", 1, path)
    assert (m.v, m.plies, m.state["turn"]) == (2, 1, "b")
    assert m.view("b")["lastMove"] == {"by": "w", "path": path, "captured": []}
    assert m.view("b")["board"][path[0]] is None and m.view("b")["board"][path[1]] == "w"


def test_a_multi_jump_records_every_square_it_took():
    m = match({(7, 0): "w", (6, 1): "b", (4, 3): "b", (2, 5): "b", (0, 1): "b"})
    path = [sq(7, 0), sq(5, 2), sq(3, 4), sq(1, 6)]
    assert m.view("w")["moves"] == [path]
    m.move("w", 1, path)
    assert m.view("b")["lastMove"] == {"by": "w", "path": path,
                                       "captured": [sq(6, 1), sq(4, 3), sq(2, 5)]}
    assert m.view("b")["board"][sq(4, 3)] is None


def test_every_refusal_changes_nothing_and_says_why_in_words():
    m = Match([ANA, BEN])
    legal = m.view("w")["moves"][0]
    cases = [
        (("b", 1, legal), "not_your_turn"),
        (("w", 7, legal), "stale"),
        (("w", 1, [sq(0, 0), sq(1, 1)]), "illegal"),
        (("w", 1, [legal[0]]), "illegal"),
        (("w", 1, []), "illegal"),
        (("w", 1, legal + [legal[1]] * 20), "illegal"),
        (("w", 1, [legal[0], 64]), "illegal"),
        (("w", 1, [legal[0], -1]), "illegal"),
        (("w", 1, [True, 1]), "illegal"),
        (("w", 1, [legal[0], 3.0]), "illegal"),
        (("w", 1, "not a path"), "illegal"),
        (("w", 1, None), "illegal"),
        ((None, 1, legal), "watching"),
        (("x", 1, legal), "watching"),
    ]
    for args, code in cases:
        error = refused(m, args[0], *args[1:])
        assert error.code == code, args
        assert error.message and error.message[0].isupper() and error.message.endswith(".")
        for word in ("token", "socket", "exception", "traceback", "version"):
            assert word not in error.message.lower()


def test_a_stale_tap_is_refused_even_when_the_move_would_still_be_legal():
    m = Match([ANA, BEN])
    first = m.view("w")["moves"][0]
    m.move("w", 1, first)
    m.move("b", 2, m.view("b")["moves"][0])
    again = m.view("w")["moves"][0]
    refused(m, "w", 2, again)               # made against version 2; the board is at version 3
    m.move("w", 3, again)


def test_the_capture_is_compulsory_and_the_refusal_says_so():
    m = match({(5, 2): "w", (4, 3): "b", (6, 5): "w", (0, 1): "b"})
    error = refused(m, "w", 1, [sq(6, 5), sq(5, 6)])
    assert (error.code, error.message) == ("illegal", "A capture is compulsory.")
    m.move("w", 1, [sq(5, 2), sq(3, 4)])


def test_a_capture_cannot_stop_early_and_the_refusal_says_so():
    m = match({(6, 1): "w", (5, 2): "b", (3, 4): "b", (0, 1): "b"})
    error = refused(m, "w", 1, [sq(6, 1), sq(4, 3)])
    assert (error.code, error.message) == ("illegal", "Keep jumping until the capture is complete.")
    m.move("w", 1, [sq(6, 1), sq(4, 3), sq(2, 5)])


def test_a_move_by_a_tuple_is_the_same_as_by_a_list():
    m = Match([ANA, BEN])
    m.move("w", 1, tuple(m.view("w")["moves"][0]))
    assert m.v == 2


def test_the_moves_a_seat_is_offered_are_the_moves_it_may_play():
    m = Match([ANA, BEN])
    for _ in range(6):
        seat = m.state["turn"]
        offered = m.view(seat)["moves"]
        assert offered == rules.legal_moves(m.state)
        every_other = [list(c) for c in _all_two_square_paths() if list(c) not in offered]
        for path in every_other[:40]:
            refused(m, seat, m.v, path)
        m.move(seat, m.v, offered[len(offered) // 2])


def _all_two_square_paths():
    for a in range(64):
        for b in range(64):
            if a != b and abs(rules.rc(a)[0] - rules.rc(b)[0]) in (1, 2):
                yield (a, b)


# ---------------- how a game ends ----------------

def test_taking_the_last_piece_wins():
    m = match({(5, 2): "w", (4, 3): "b"})
    m.move("w", 1, [sq(5, 2), sq(3, 4)])
    assert m.over and (m.winner, m.ending, m.plies, m.v) == ("w", "captured", 1, 2)
    for seat in ("w", "b", None):
        v = m.view(seat)
        assert v["result"] == {"winner": "w", "ending": "captured", "plies": 1}
        assert v["turn"] is None and v["moves"] == [] and v["mustCapture"] is False
    assert m.standings() == [(ANA["participant"], "won"), (BEN["participant"], "lost")]


def test_leaving_the_other_side_without_a_move_wins():
    m = match({(5, 0): "b", (6, 1): "w", (7, 2): "w", (5, 4): "w"})
    m.move("w", 1, [sq(5, 4), sq(4, 5)])
    assert (m.winner, m.ending) == ("w", "blocked")
    assert m.standings() == [(ANA["participant"], "won"), (BEN["participant"], "lost")]


def test_black_can_win_and_is_then_the_one_standing():
    m = match({(2, 1): "b", (3, 2): "w"}, turn="b")
    m.move("b", 1, [sq(2, 1), sq(4, 3)])
    assert (m.winner, m.ending) == ("b", "captured")
    assert m.standings() == [(ANA["participant"], "lost"), (BEN["participant"], "won")]


def test_eighty_quiet_half_moves_are_a_draw_with_no_winner():
    m = match({(4, 3): "W", (0, 1): "B"}, clock=rules.DRAW_CLOCK - 1)
    m.move("w", 1, [sq(4, 3), sq(3, 2)])
    assert (m.winner, m.ending) == (None, "drawn")
    assert m.view("w")["result"] == {"winner": None, "ending": "drawn", "plies": 1}
    assert m.standings() == [(ANA["participant"], "draw"), (BEN["participant"], "draw")]


def test_a_finished_game_takes_no_more_moves_or_resignations():
    m = match({(5, 2): "w", (4, 3): "b"})
    m.move("w", 1, [sq(5, 2), sq(3, 4)])
    for seat in ("w", "b"):
        assert refused(m, seat, m.v, [sq(3, 4), sq(2, 5)]).code == "over"
        assert refused(m, seat, op="resign").code == "over"


def test_resigning_gives_the_game_to_the_other_side_and_completes_it():
    m = Match([ANA, BEN])
    m.resign("b")                            # out of turn is fine: it is black's choice to make
    assert m.over and (m.winner, m.ending, m.plies, m.v) == ("w", "resigned", 0, 2)
    assert m.view("w")["result"] == {"winner": "w", "ending": "resigned", "plies": 0}
    assert m.view("b")["turn"] is None and m.view("b")["moves"] == []
    assert m.standings() == [(ANA["participant"], "won"), (BEN["participant"], "lost")]
    assert refused(m, "w", op="resign").code == "over"


def test_white_may_resign_on_their_own_turn_too():
    m = Match([ANA, BEN])
    m.resign("w")
    assert (m.winner, m.ending) == ("b", "resigned")
    assert m.standings() == [(ANA["participant"], "lost"), (BEN["participant"], "won")]


def test_resigning_keeps_the_last_move_for_the_final_picture():
    m = Match([ANA, BEN])
    m.move("w", 1, m.view("w")["moves"][0])
    last = m.view("b")["lastMove"]
    m.resign("b")
    assert m.view("w")["lastMove"] == last


def test_a_watcher_cannot_resign_and_nothing_changes():
    m = Match([ANA, BEN])
    for seat in (None, "x"):
        assert refused(m, seat, op="resign").code == "watching"


def test_standings_wait_for_the_end():
    with pytest.raises(RuntimeError):
        Match([ANA, BEN]).standings()


def test_every_ending_is_a_known_word():
    assert ENDINGS == ("captured", "blocked", "resigned", "drawn")


# ---------------- what a match does not do ----------------

def test_there_is_no_draw_offer_takeback_timer_or_bot():
    """D6 of the plan: the only things a seat can do are move and resign. Adding one is a product
    decision, and this test is where it has to be made on purpose."""
    public = {n for n in dir(Match) if not n.startswith("_")}
    assert public == {"move", "resign", "view", "seat_of", "over", "standings"}
    mine = {n for n in vars(Match([ANA, BEN])) if not n.startswith("_")}
    assert mine == {"participants", "names", "state", "v", "plies", "last", "winner", "ending"}


# ---------------- whole games ----------------

def test_seeded_games_play_to_the_end_through_the_views_alone():
    """Players only ever play moves a view offered them. Every game ends, agrees with the rules'
    own result, and reports consistent standings."""
    endings = set()
    for seed in range(40):
        rng = random.Random(seed)
        m = Match([ANA, BEN])
        reference = rules.new_game()
        for _ in range(500):
            if m.over:
                break
            seat = m.state["turn"]
            version = m.view(seat)["v"]
            move = rng.choice(m.view(seat)["moves"])
            m.move(seat, version, move)
            reference = rules.apply_move(reference, move)
            assert m.state == reference
        assert m.over and m.ending in ENDINGS
        assert m.plies > 0
        assert m.v == 1 + m.plies
        assert (reference["result"] == "draw") == (m.winner is None)
        if m.winner:
            assert reference["result"] == m.winner
        outcomes = [s for _, s in m.standings()]
        assert sorted(outcomes) in (["draw", "draw"], ["lost", "won"])
        endings.add(m.ending)
    assert endings & {"captured", "blocked"}
