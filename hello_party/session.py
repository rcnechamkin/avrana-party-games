"""One Hello Party session: pure rules, no sockets, no Party, no threads. EXPERIMENTAL (AVR-38).

Seats follow the launch roster (one to six players, in roster order). Each seat is dealt a SECRET
WORD at launch that only that seat is ever sent. Everyone shares a GREETING BOARD. A seat says
hello once (its input: validated here); when every seat has greeted, the session is over and the
result is cooperative, everyone `won`.

`view(participant)` is the ONLY state a client gets: it is built per viewer, and a secret is added
to the viewer's own view alone (a watcher, `None`, gets none). Nothing hidden is sent and merely
not drawn. A view never carries a participant id, a ticket or a token.

    v         int            bumped on every change anyone could see (the first view is 1)
    seat      int|None       the viewer's seat (index into `names`); None for a watcher
    names     [str]          display names from the launch roster, in seat order
    you       {name, secret}|None   the viewer's own card; None for a watcher
    board     [{seat, by, text}]    the shared greetings, oldest first
    greeted   [bool]         which seats have greeted
    over      bool
    result    {greetings}|None     once over
"""

from __future__ import annotations

import random

from avrana_gamekit.app import Conflict, Declined, Finish

MAX_PLAYERS = 6
MAX_TEXT = 40
WORDS = ("amber", "bramble", "comet", "dune", "ember", "fjord", "glimmer", "harbor", "indigo",
         "juniper", "kestrel", "lantern", "meadow", "nimbus", "orchid", "pebble")
DATA_SCHEMA = "hello.result/v1"


class Session:
    def __init__(self, roster, rng=None):
        players = [r for r in roster if r["role"] == "player"]
        if not 1 <= len(players) <= MAX_PLAYERS:
            raise Declined(f"Hello Party takes one to {MAX_PLAYERS} players.")
        if len({r["participant"] for r in players}) != len(players):
            raise Declined("Hello Party takes one to six different players.")
        words = (rng or random.SystemRandom()).sample(WORDS, len(players))
        self.seats = [{"participant": r["participant"], "name": r["name"], "secret": w}
                      for r, w in zip(players, words)]
        self.board = []
        self.v = 1
        self.over = False

    def seat_of(self, participant):
        for index, seat in enumerate(self.seats):
            if seat["participant"] == participant:
                return index
        return None

    def view(self, participant):
        seat = self.seat_of(participant) if participant is not None else None
        return {
            "v": self.v,
            "seat": seat,
            "names": [s["name"] for s in self.seats],
            "you": None if seat is None else {"name": self.seats[seat]["name"],
                                              "secret": self.seats[seat]["secret"]},
            "board": [dict(entry) for entry in self.board],
            "greeted": [any(e["seat"] == i for e in self.board) for i in range(len(self.seats))],
            "over": self.over,
            "result": {"greetings": len(self.board)} if self.over else None,
        }

    def greet(self, participant, text):
        """A seat says hello. Raises Conflict for anything the rules refuse."""
        seat = self.seat_of(participant)
        if seat is None:
            raise Conflict("watching", "You are watching this game.")
        if self.over:
            raise Conflict("over", "The game is over.")
        text = " ".join(text.split())                     # one line, single spaces
        if not text or len(text) > MAX_TEXT or not text.isprintable():
            raise Conflict("bad_text", f"Say hello in 1 to {MAX_TEXT} characters.")
        if any(e["seat"] == seat for e in self.board):
            raise Conflict("already", "You have already said hello.")
        self.board.append({"seat": seat, "by": self.seats[seat]["name"], "text": text})
        self.over = len(self.board) == len(self.seats)
        self.v += 1

    def finished(self):
        """The report for a finished session: cooperative, every player won."""
        return Finish("cooperative", tuple((s["participant"], "won") for s in self.seats),
                      DATA_SCHEMA, {"greetings": len(self.board)})
