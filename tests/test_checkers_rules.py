"""The rules of Checkers as adapted into checkers/rules.py (AVR-238).

The fork's Checkers engine (games/checkers/engine.py) is the donor: its rules behaviour is the
behaviour here, with the capture always compulsory. These are the donor's rules tests, ported
(the bot tests and the house-rule toggle tests are not carried), plus pins for what the adaptation
adds. The `test_donor_*` tests compare the two over seeded playouts for as long as the donor exists;
delete them with the donor when the fork's Checkers is retired.
"""

import copy
import inspect
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from checkers import rules
from checkers.rules import (
    DRAW_CLOCK, MEN_PER_SIDE, apply_move, count_pieces, is_capture, is_dark, legal_moves,
    moves_for, new_game, opponent, rc, sq,
)


def make(pieces, turn="w", clock=0):
    """Build a state from {(row, col): piece}. Dark squares only."""
    board = [None] * 64
    for (r, c), p in pieces.items():
        assert is_dark(r, c), "test bug: piece on a light square"
        board[sq(r, c)] = p
    return {"board": board, "turn": turn, "clock": clock, "result": None}


def moveset(state):
    return {tuple(m) for m in legal_moves(state)}


# ---------------- new_game ----------------

def test_new_game_shape():
    st = new_game()
    assert st["turn"] == "w"
    assert st["clock"] == 0
    assert st["result"] is None
    assert len(st["board"]) == 64
    ws = [i for i, p in enumerate(st["board"]) if p == "w"]
    bs = [i for i, p in enumerate(st["board"]) if p == "b"]
    assert len(ws) == MEN_PER_SIDE == 12 and len(bs) == 12
    assert not any(p in ("W", "B") for p in st["board"])  # no kings at start
    for i in ws + bs:
        r, c = divmod(i, 8)
        assert is_dark(r, c)
    assert all(divmod(i, 8)[0] >= 5 for i in ws)   # white bottom rows 5-7
    assert all(divmod(i, 8)[0] <= 2 for i in bs)   # black top rows 0-2
    # rows 3-4 empty
    assert all(st["board"][sq(r, c)] is None for r in (3, 4) for c in range(8))


def test_new_game_opening_moves():
    # the classic 7 opening moves, all simple, all onto dark squares
    moves = legal_moves(new_game())
    assert len(moves) == 7
    for m in moves:
        assert len(m) == 2
        r, c = divmod(m[1], 8)
        assert is_dark(r, c) and r == 4


def test_white_moves_first_and_black_cannot_start():
    st = new_game()
    assert st["turn"] == "w"
    black_step = [sq(2, 1), sq(3, 0)]
    with pytest.raises(ValueError):
        apply_move(st, black_step)


# ---------------- simple moves ----------------

def test_white_man_moves_up_only():
    st = make({(5, 2): "w", (0, 1): "b"})
    assert moveset(st) == {(sq(5, 2), sq(4, 1)), (sq(5, 2), sq(4, 3))}


def test_black_man_moves_down_only():
    st = make({(2, 3): "b", (7, 0): "w"}, turn="b")
    assert moveset(st) == {(sq(2, 3), sq(3, 2)), (sq(2, 3), sq(3, 4))}


def test_king_moves_all_four_ways():
    st = make({(4, 3): "W", (0, 1): "b"})
    assert moveset(st) == {(sq(4, 3), sq(3, 2)), (sq(4, 3), sq(3, 4)),
                           (sq(4, 3), sq(5, 2)), (sq(4, 3), sq(5, 4))}


def test_edge_of_board():
    st = make({(5, 0): "w", (0, 1): "b"})
    assert moveset(st) == {(sq(5, 0), sq(4, 1))}


def test_cannot_move_onto_occupied_square():
    # own piece blocks; enemy piece with a blocked landing blocks too
    st = make({(5, 2): "w", (4, 3): "w", (0, 1): "b"})
    assert (sq(5, 2), sq(4, 3)) not in moveset(st)
    st = make({(5, 2): "w", (4, 1): "b", (3, 0): "b"})
    assert moveset(st) == {(sq(5, 2), sq(4, 3))}


def test_destinations_always_dark():
    st = make({(4, 3): "W", (0, 1): "B"})
    for m in legal_moves(st):
        assert is_dark(*divmod(m[1], 8))


# ---------------- captures ----------------

def test_jump_removes_the_jumped_piece():
    st = make({(5, 2): "w", (4, 3): "b", (0, 1): "b"})
    assert [sq(5, 2), sq(3, 4)] in legal_moves(st)
    nxt = apply_move(st, [sq(5, 2), sq(3, 4)])
    assert nxt["board"][sq(4, 3)] is None
    assert nxt["board"][sq(3, 4)] == "w"
    assert nxt["board"][sq(5, 2)] is None
    assert nxt["turn"] == "b"


def test_cannot_jump_own_piece():
    st = make({(5, 2): "w", (4, 3): "w", (0, 1): "b"})
    assert moveset(st) == {(sq(5, 2), sq(4, 1)),
                           (sq(4, 3), sq(3, 2)), (sq(4, 3), sq(3, 4))}


def test_landing_square_must_be_empty():
    st = make({(5, 2): "w", (4, 3): "b", (3, 4): "b"})
    assert moveset(st) == {(sq(5, 2), sq(4, 1))}  # jump blocked -> simple only


def test_man_cannot_jump_backward():
    # black man sits BEHIND the white man; American men capture forward only
    st = make({(3, 2): "w", (4, 3): "b", (0, 1): "b"})
    assert moveset(st) == {(sq(3, 2), sq(2, 1)), (sq(3, 2), sq(2, 3))}


def test_king_jumps_backward():
    st = make({(3, 2): "W", (4, 3): "b"})
    assert [sq(3, 2), sq(5, 4)] in legal_moves(st)
    nxt = apply_move(st, [sq(3, 2), sq(5, 4)])
    assert nxt["board"][sq(4, 3)] is None and nxt["board"][sq(5, 4)] == "W"


def test_a_capture_is_compulsory_so_simple_moves_are_hidden():
    st = make({(5, 2): "w", (4, 3): "b", (6, 5): "w", (0, 1): "b"})
    assert moveset(st) == {(sq(5, 2), sq(3, 4))}  # only the capture


def test_the_compulsory_capture_is_not_a_parameter():
    """D6 of the plan: forced captures are always on, with no house-rule toggle to switch off."""
    for fn in (legal_moves, apply_move, moves_for):
        assert "forced" not in inspect.signature(fn).parameters
    with pytest.raises(TypeError):
        legal_moves(new_game(), forced=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        apply_move(new_game(), [sq(5, 0), sq(4, 1)], forced=False)  # type: ignore[call-arg]


# ---------------- multi-jump ----------------

def test_double_jump_cannot_stop_early():
    st = make({(6, 1): "w", (5, 2): "b", (3, 4): "b", (0, 1): "b"})
    ms = legal_moves(st)
    assert ms == [[sq(6, 1), sq(4, 3), sq(2, 5)]]
    assert [sq(6, 1), sq(4, 3)] not in ms  # the partial hop is never offered
    nxt = apply_move(st, [sq(6, 1), sq(4, 3), sq(2, 5)])
    assert nxt["board"][sq(5, 2)] is None and nxt["board"][sq(3, 4)] is None
    assert nxt["board"][sq(2, 5)] == "w"


def test_triple_jump():
    st = make({(7, 0): "w", (6, 1): "b", (4, 3): "b", (2, 5): "b"})
    ms = legal_moves(st)
    assert ms == [[sq(7, 0), sq(5, 2), sq(3, 4), sq(1, 6)]]
    nxt = apply_move(st, ms[0])
    for r, c in ((6, 1), (4, 3), (2, 5)):
        assert nxt["board"][sq(r, c)] is None
    assert nxt["board"][sq(1, 6)] == "w"   # row 1: no crowning
    assert nxt["result"] == "w"            # black has nothing left


def test_branching_multi_jump_offers_both_branches():
    st = make({(6, 3): "w", (5, 2): "b", (3, 2): "b", (5, 4): "b", (3, 4): "b"})
    ms = moveset(st)
    assert ms == {(sq(6, 3), sq(4, 1), sq(2, 3)),
                  (sq(6, 3), sq(4, 5), sq(2, 3))}
    # taking branch A removes only branch A's victims
    nxt = apply_move(st, [sq(6, 3), sq(4, 1), sq(2, 3)])
    assert nxt["board"][sq(5, 2)] is None and nxt["board"][sq(3, 2)] is None
    assert nxt["board"][sq(5, 4)] == "b" and nxt["board"][sq(3, 4)] == "b"


def test_a_king_may_loop_back_through_its_own_start_square():
    # Four men round a diamond: the king takes all four and lands where it began, either way
    # round. Two different complete sequences end on the same square, the source.
    st = make({(5, 2): "W", (4, 3): "b", (4, 5): "b", (6, 5): "b", (6, 3): "b"})
    start = sq(5, 2)
    around = [start, sq(3, 4), sq(5, 6), sq(7, 4), start]
    other_way = [start, sq(7, 4), sq(5, 6), sq(3, 4), start]
    assert sorted(legal_moves(st)) == sorted([around, other_way])
    nxt = apply_move(st, around)
    assert nxt["board"][start] == "W"
    assert count_pieces(nxt["board"], "b") == 0 and nxt["result"] == "w"


# ---------------- crowning ----------------

def test_crowning_on_simple_move():
    st = make({(1, 2): "w", (5, 0): "b"})
    nxt = apply_move(st, [sq(1, 2), sq(0, 1)])
    assert nxt["board"][sq(0, 1)] == "W"


def test_crowning_on_jump():
    st = make({(2, 1): "w", (1, 2): "b", (5, 4): "b"})
    nxt = apply_move(st, [sq(2, 1), sq(0, 3)])
    assert nxt["board"][sq(0, 3)] == "W"
    assert nxt["board"][sq(1, 2)] is None


def test_black_crowns_on_row_seven():
    st = make({(6, 1): "b", (0, 7): "W"}, turn="b")
    nxt = apply_move(st, [sq(6, 1), sq(7, 0)])
    assert nxt["board"][sq(7, 0)] == "B"


def test_crowning_ends_the_jump_sequence():
    # RULE pin: landing on the last row crowns AND ends the move, even
    # though the fresh king could jump (1,4) onward to (2,5).
    st = make({(2, 1): "w", (1, 2): "b", (1, 4): "b"})
    ms = legal_moves(st)
    assert ms == [[sq(2, 1), sq(0, 3)]]
    assert [sq(2, 1), sq(0, 3), sq(2, 5)] not in ms
    nxt = apply_move(st, [sq(2, 1), sq(0, 3)])
    assert nxt["board"][sq(0, 3)] == "W"
    assert nxt["board"][sq(1, 4)] == "b"   # survived: no jump after crowning
    assert nxt["turn"] == "b"


# ---------------- endings ----------------

def test_no_pieces_loses():
    st = make({(5, 2): "w", (4, 3): "b"})
    nxt = apply_move(st, [sq(5, 2), sq(3, 4)])
    assert nxt["result"] == "w"
    assert legal_moves(nxt) == []


def test_black_can_win_too():
    st = make({(2, 1): "b", (3, 2): "w"}, turn="b")
    nxt = apply_move(st, [sq(2, 1), sq(4, 3)])
    assert nxt["result"] == "b"
    assert legal_moves(nxt) == []


def test_blocked_side_loses():
    # black's lone man at (5,0) is walled in: (6,1) occupied, jump landing
    # (7,2) occupied. White plays elsewhere; black is stuck and loses.
    st = make({(5, 0): "b", (6, 1): "w", (7, 2): "w", (5, 4): "w"})
    nxt = apply_move(st, [sq(5, 4), sq(4, 5)])
    assert nxt["result"] == "w"
    assert legal_moves(nxt) == []


def test_a_decisive_position_outranks_the_draw_counter():
    # White's quiet king move is the 80th half-move without progress, and it also leaves black's
    # only man walled in: that is a win for white, not a draw.
    st = make({(5, 0): "b", (6, 1): "w", (7, 2): "w", (3, 4): "W"}, clock=DRAW_CLOCK - 1)
    nxt = apply_move(st, [sq(3, 4), sq(2, 5)])
    assert nxt["clock"] == DRAW_CLOCK
    assert nxt["result"] == "w"


def test_clock_draw_at_80():
    st = make({(4, 3): "W", (0, 1): "B"}, clock=DRAW_CLOCK - 1)
    nxt = apply_move(st, [sq(4, 3), sq(3, 2)])
    assert nxt["clock"] == DRAW_CLOCK
    assert nxt["result"] == "draw"
    assert legal_moves(nxt) == []


def test_the_draw_clock_is_eighty_half_moves():
    assert DRAW_CLOCK == 80


def test_clock_increments_on_king_quiet_move():
    st = make({(4, 3): "W", (0, 1): "B"}, clock=5)
    nxt = apply_move(st, [sq(4, 3), sq(3, 2)])
    assert nxt["clock"] == 6 and nxt["result"] is None


def test_clock_resets_on_man_move():
    st = make({(4, 3): "W", (5, 6): "w", (0, 1): "B"}, clock=50)
    nxt = apply_move(st, [sq(5, 6), sq(4, 7)])
    assert nxt["clock"] == 0


def test_clock_resets_on_king_capture():
    st = make({(4, 3): "W", (3, 2): "b", (0, 7): "B"}, clock=50)
    nxt = apply_move(st, [sq(4, 3), sq(2, 1)])
    assert nxt["clock"] == 0 and nxt["result"] is None


# ---------------- apply_move rejections ----------------

def test_rejects_illegal_move():
    with pytest.raises(ValueError):
        apply_move(new_game(), [sq(0, 0), sq(1, 1)])
    with pytest.raises(ValueError):
        apply_move(new_game(), [sq(4, 1), sq(5, 2)])  # empty source


def test_rejects_wrong_turns_piece():
    with pytest.raises(ValueError):
        apply_move(new_game(), [sq(2, 1), sq(3, 0)])  # black piece, white's turn


def test_rejects_partial_capture_sequence():
    st = make({(6, 1): "w", (5, 2): "b", (3, 4): "b", (0, 1): "b"})
    with pytest.raises(ValueError):
        apply_move(st, [sq(6, 1), sq(4, 3)])  # must finish the double


def test_rejects_simple_move_when_capture_is_compulsory():
    st = make({(5, 2): "w", (4, 3): "b", (6, 5): "w", (0, 1): "b"})
    with pytest.raises(ValueError):
        apply_move(st, [sq(6, 5), sq(5, 6)])


def test_rejects_moves_in_finished_game():
    st = make({(5, 2): "w", (4, 3): "b"})
    done = apply_move(st, [sq(5, 2), sq(3, 4)])
    with pytest.raises(ValueError):
        apply_move(done, [sq(3, 4), sq(2, 5)])


# ---------------- immutability ----------------

def test_apply_move_does_not_mutate_input():
    st = new_game()
    snapshot = copy.deepcopy(st)
    apply_move(st, legal_moves(st)[0])
    assert st == snapshot
    # and through a capture with crowning
    st2 = make({(2, 1): "w", (1, 2): "b", (5, 4): "b"}, clock=3)
    snap2 = copy.deepcopy(st2)
    apply_move(st2, [sq(2, 1), sq(0, 3)])
    assert st2 == snap2


# ---------------- what the adaptation adds ----------------

def test_moves_for_serves_either_side_of_a_bare_board():
    st = make({(5, 2): "w", (2, 3): "b"})
    assert {tuple(m) for m in moves_for(st["board"], "w")} == {(sq(5, 2), sq(4, 1)), (sq(5, 2), sq(4, 3))}
    assert {tuple(m) for m in moves_for(st["board"], "b")} == {(sq(2, 3), sq(3, 2)), (sq(2, 3), sq(3, 4))}
    assert moves_for([None] * 64, "w") == []
    # legal_moves is moves_for for the side to move, and nothing once the game is decided
    assert legal_moves(st) == moves_for(st["board"], "w")
    st["result"] = "w"
    assert legal_moves(st) == []


def test_is_capture_tells_a_jump_from_a_step():
    assert not is_capture([sq(5, 2), sq(4, 3)])
    assert is_capture([sq(5, 2), sq(3, 4)])
    assert is_capture([sq(6, 1), sq(4, 3), sq(2, 5)])


def test_opponent_and_counts():
    assert (opponent("w"), opponent("b")) == ("b", "w")
    st = new_game()
    assert (count_pieces(st["board"], "w"), count_pieces(st["board"], "b")) == (12, 12)
    st = make({(5, 2): "w", (4, 3): "W", (2, 1): "B"})
    assert (count_pieces(st["board"], "w"), count_pieces(st["board"], "b")) == (2, 1)


def _playout(seed_white, seed_black, cap):
    rng = {"w": random.Random(seed_white), "b": random.Random(seed_black)}
    state, transcript = new_game(), []
    for _ in range(cap):
        if state["result"] is not None:
            break
        moves = legal_moves(state)
        move = moves[rng[state["turn"]].randrange(len(moves))]
        transcript.append(move)
        state = apply_move(state, move)
    return state, transcript


def test_random_playouts_end_and_keep_the_board_sane():
    """The donor's fuzz (its first 150 seeds, the same uniform choices), plus the
    invariants every ply: pieces only on dark squares, nothing ever added, sides alternate."""
    for i in range(150):
        rng = {"w": random.Random(i), "b": random.Random(10_000 + i)}
        state = new_game()
        seen = {"w": MEN_PER_SIDE, "b": MEN_PER_SIDE}
        for _ in range(300):
            if state["result"] is not None:
                break
            moves = legal_moves(state)
            assert moves, "a running game always has a move"
            mover = state["turn"]
            state = apply_move(state, moves[rng[mover].randrange(len(moves))])
            assert state["turn"] == opponent(mover)
            for side in "wb":
                n = count_pieces(state["board"], side)
                assert n <= seen[side]
                seen[side] = n
            for square, piece in enumerate(state["board"]):
                assert piece is None or is_dark(*rc(square))
        # the draw clock guarantees termination inside the cap
        assert state["result"] in ("w", "b", "draw")


def test_the_module_is_stdlib_only():
    import ast
    tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__"}, imported


# ---------------- the donor ----------------

@pytest.fixture(scope="module")
def engine():
    """The fork's own engine, move for move (skipped once the fork's Checkers is retired)."""
    return pytest.importorskip("games.checkers.engine")


def test_donor_same_moves_and_same_states_over_seeded_playouts(engine):
    for i in range(60):
        rng = {"w": random.Random(i), "b": random.Random(50_000 + i)}
        mine, theirs = new_game(), engine.new_game()
        assert mine == theirs
        for _ in range(400):
            assert legal_moves(mine) == engine.legal_moves(theirs, True)
            if mine["result"] is not None:
                break
            moves = legal_moves(mine)
            move = moves[rng[mine["turn"]].randrange(len(moves))]
            mine, theirs = apply_move(mine, move), engine.apply_move(theirs, move, True)
            assert mine == theirs
        assert mine["result"] is not None


def test_donor_same_constants(engine):
    assert (rules.SIZE, rules.DRAW_CLOCK, rules.MEN_PER_SIDE) == (
        engine.SIZE, engine.DRAW_CLOCK, engine.MEN_PER_SIDE)


def test_donor_toggle_is_the_only_difference(engine):
    st = make({(5, 2): "w", (4, 3): "b", (6, 5): "w", (0, 1): "b"})
    assert legal_moves(st) == engine.legal_moves(st, True)
    assert legal_moves(st) != engine.legal_moves(st, False)
