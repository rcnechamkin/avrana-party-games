"""One Checkers match (AVR-238): two seats, a turn, a version counter and each seat's own view.

A match knows nothing of the Party, tickets, sockets or threads. It is handed the two players, in
roster order, and answers `view(seat)`, `move(...)` and `resign(...)`; the server around it owns the
lock, the tokens and the report to the Party.

  * Seats follow the roster (plan decision D7): the first player listed is white and moves first,
    the second is black. Nobody chooses a colour and nothing is random.
  * `v` counts every change (the position at the start is v 1; each move and a resignation add
    one). A move names the `v` it was made against, so a stale tap changes nothing.
  * There is no timer, no draw offer, no takeback and no bot (D6). Whoever is to move may take as
    long as they like: a player who has gone away leaves the game waiting, and the Party Host may
    end it from the Party.
  * Resigning is allowed at any time, even out of turn: the resigner loses and the game is
    completed (D6).
  * A viewer is shown only what their seat may know. Checkers has no hidden information, so that
    is the legal moves: they are sent to the player to move and to nobody else, so the page never
    works out legality for itself. A watcher (no seat) sees the board and no moves.

The same dict is what the page receives, so its keys are part of the page contract:

    v          int         the version of this view
    seat       "w"|"b"|None  the viewer's side; None for a watcher
    turn       "w"|"b"|None  whose move it is; None once the game is over
    board      [64]        None | "w" | "b" | "W" | "B" (row 0 is the top, white starts at the bottom)
    moves      [[int...]]  complete legal moves, only for the seat to move, else []
    mustCapture bool       every move in `moves` is a capture (capturing is compulsory)
    lastMove   None | {"by": "w"|"b", "path": [int...], "captured": [int...]}
    result     None | {"winner": "w"|"b"|None, "ending": ENDINGS, "plies": int}
    names      {"w": str, "b": str}   the display names from the launch roster
"""

from __future__ import annotations

from checkers import rules

WHITE, BLACK = "w", "b"
SEATS = (WHITE, BLACK)
# How a game ends: the loser has no piece left, the loser has pieces but no move, the loser
# resigned, or 80 half-moves passed with no capture and no man moved (a draw: no loser).
ENDINGS = ("captured", "blocked", "resigned", "drawn")
MAX_PATH = rules.MEN_PER_SIDE + 1       # a start square and up to twelve jumps


class Conflict(Exception):
    """A request the match refuses. `code` is for tests and logs; `message` is the sentence a
    player sees, in the game's own terms."""

    def __init__(self, code, message):
        super().__init__(code)
        self.code, self.message = code, message


class Match:
    def __init__(self, players, state=None):
        """`players`: exactly two {"participant", "name"} dicts in roster order (white first).
        `state` is for tests that need a position other than the opening; it must be running."""
        players = list(players)
        if len(players) != 2:
            raise ValueError("a match has exactly two players")
        ids = [p["participant"] for p in players]
        if ids[0] == ids[1]:
            raise ValueError("the two players must be different people")
        if state is not None and state["result"] is not None:
            raise ValueError("a match cannot start from a finished position")
        self.participants = {WHITE: ids[0], BLACK: ids[1]}
        self.names = {WHITE: str(players[0].get("name") or ""), BLACK: str(players[1].get("name") or "")}
        self.state = state if state is not None else rules.new_game()
        self.v = 1
        self.plies = 0
        self.last = None
        self.winner = None          # "w" | "b" | None (a draw has no winner)
        self.ending = None          # one of ENDINGS once the game is over

    # ---- who is who -------------------------------------------------------------------------

    def seat_of(self, participant):
        """The seat ("w" or "b") this participant plays, or None for anyone else."""
        for seat, pid in self.participants.items():
            if pid == participant:
                return seat
        return None

    @property
    def over(self):
        return self.ending is not None

    # ---- what a seat is shown ---------------------------------------------------------------

    def view(self, seat=None):
        moves = []
        if not self.over and seat in SEATS and seat == self.state["turn"]:
            moves = rules.legal_moves(self.state)
        return {
            "v": self.v,
            "seat": seat if seat in SEATS else None,
            "turn": None if self.over else self.state["turn"],
            "board": list(self.state["board"]),
            "moves": moves,
            "mustCapture": bool(moves) and rules.is_capture(moves[0]),
            "lastMove": None if self.last is None else {
                "by": self.last["by"], "path": list(self.last["path"]),
                "captured": list(self.last["captured"])},
            "result": None if not self.over else {
                "winner": self.winner, "ending": self.ending, "plies": self.plies},
            "names": dict(self.names),
        }

    # ---- what a seat may do -----------------------------------------------------------------

    def move(self, seat, v, path):
        """Play `path` (a complete legal move) for `seat`, against version `v`. Raises Conflict,
        and changes nothing, for anything else."""
        if self.over:
            raise Conflict("over", "The game is over.")
        if seat not in SEATS:
            raise Conflict("watching", "You are watching this game.")
        if seat != self.state["turn"]:
            raise Conflict("not_your_turn", "It is not your turn.")
        if v != self.v:
            raise Conflict("stale", "The board changed. Look again.")
        if not (isinstance(path, (list, tuple)) and 2 <= len(path) <= MAX_PATH
                and all(type(s) is int and 0 <= s < rules.SIZE * rules.SIZE for s in path)):
            raise Conflict("illegal", "That move is not allowed.")
        path = list(path)
        legal = rules.legal_moves(self.state)
        if path not in legal:
            raise Conflict("illegal", _why_not(path, legal))

        mover = self.state["turn"]
        self.state = rules.apply_move(self.state, path)
        self.last = {"by": mover, "path": path, "captured": _jumped(path)}
        self.plies += 1
        self.v += 1
        result = self.state["result"]
        if result == "draw":
            self._finish(None, "drawn")
        elif result is not None:
            loser = rules.opponent(result)
            self._finish(result, "captured" if rules.count_pieces(self.state["board"], loser) == 0
                         else "blocked")

    def resign(self, seat):
        """`seat` gives the game to the other side. Allowed at any time while the game runs."""
        if self.over:
            raise Conflict("over", "The game is over.")
        if seat not in SEATS:
            raise Conflict("watching", "You are watching this game.")
        winner = rules.opponent(seat)
        self.state = dict(self.state, result=winner)
        self.v += 1
        self._finish(winner, "resigned")

    def _finish(self, winner, ending):
        self.winner, self.ending = winner, ending

    # ---- what the Party is told -------------------------------------------------------------

    def standings(self):
        """[(participant, "won" | "lost" | "draw")] in seat order, once the game is over."""
        if not self.over:
            raise RuntimeError("the game is not over")
        if self.winner is None:
            return [(self.participants[seat], "draw") for seat in SEATS]
        return [(self.participants[seat], "won" if seat == self.winner else "lost") for seat in SEATS]


def _jumped(path):
    """The squares a move captured: the one between each pair of landings two rows apart."""
    out = []
    for a, b in zip(path, path[1:]):
        (ra, ca), (rb, cb) = rules.rc(a), rules.rc(b)
        if abs(rb - ra) == 2:
            out.append(rules.sq((ra + rb) // 2, (ca + cb) // 2))
    return out


def _why_not(path, legal):
    """The sentence for a move that is not legal, said in the game's terms."""
    if any(m[:len(path)] == path for m in legal if len(m) > len(path)):
        return "Keep jumping until the capture is complete."
    if legal and rules.is_capture(legal[0]) and not rules.is_capture(path):
        return "A capture is compulsory."
    return "That move is not allowed."
