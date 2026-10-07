"""The Checkers process (AVR-238): what Party Core and the phones can do to it, and what it tells
the Party.

Four layers, each runnable where it can be:

  * App: the game's logic with no sockets (`App.handle`), everywhere;
  * Live: the real HTTP server on a loopback TCP socket, a real client, and a fake Party that
    receives `ended` over loopback TCP, everywhere. The Unix socket is the only thing it swaps;
  * Process: `python -m checkers` handed an inherited Unix socket on fd 3, the way the Party
    starts a native game, with a fake Party on a Unix socket. It needs AF_UNIX, which Python on
    Windows lacks: skipped there and run on Linux CI;
  * Boundary: what the package imports and the sockets it may open (source checks).

The Party's end of everything is played by this file with a key it made, so nothing here needs
the Party repository.
"""

import ast
import copy
import hashlib
import http.client
import http.server
import json
import logging
import os
import random
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import party_protocol as protocol
from core import party_result
from checkers import party, rules, server
from checkers.rules import sq
from checkers.session import ENDINGS, Match

GAME = "checkers"
BASE = party.BASE
SID, SID2 = "session-" + "a" * 32, "session-" + "b" * 32
ANA, BEN, CAL, DEB = ("participant-" + c * 32 for c in "abcd")
ORIGIN = "https://party.example"
ROSTER = [{"participant": ANA, "name": "Ana", "role": "player"},
          {"participant": BEN, "name": "Ben", "role": "player"},
          {"participant": CAL, "name": "Cal", "role": "spectator"}]
UNIX = hasattr(socket, "AF_UNIX")
VIEW_KEYS = {"v", "seat", "turn", "board", "moves", "mustCapture", "lastMove", "result", "names"}


def wait_until(check, timeout=5.0, what="the condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


def start_from(pieces, turn="w"):
    """A `new_match` that starts from this position (squares are (row, col)) instead of the opening."""
    board = [None] * 64
    for (r, c), piece in pieces.items():
        board[sq(r, c)] = piece
    state = {"board": board, "turn": turn, "clock": 0, "result": None}
    return lambda players: Match(players, copy.deepcopy(state))


def opened(key, message, sid=SID):
    """What the Party does with an `ended` message: open it with the game's key, and check its result."""
    payload = protocol.open_message(key, message, "ended", "party", protocol.ReplayGuard())
    assert (payload["iss"], payload["sid"], payload["outcome"]) == (GAME, sid, "completed")
    return payload, party_result.check(payload["result"], GAME, [ANA, BEN])


def standings(checked):
    return {e["participant"]: e["standing"] for e in checked["standings"]}


# ==================================================================================== the App

class Rig:
    """The App, with the Party's end of everything played by the test."""

    def __init__(self, report=None, **options):
        self.key = protocol.new_key()
        self.reports = []                       # every signed `ended` the party was sent
        self.answer = (200, "accepted")         # what the party says to a report
        self.slept = []                         # the waits the reporter would have made
        self.app = server.App(protocol.GameSide(self.key, GAME), report or self._report,
                              party_origin=ORIGIN, sleep=self.slept.append, **options)

    def _report(self, message):
        self.reports.append(message)
        return self.answer

    def raw(self, method, path, body=None, headers=None, data=None):
        data = data if data is not None else (b"" if body is None else json.dumps(body).encode())
        return self.app.handle(method, path, {k.lower(): v for k, v in (headers or {}).items()}, data)

    def call(self, method, path, body=None, headers=None, data=None):
        reply = self.raw(method, path, body, headers, data)
        return reply.status, (json.loads(reply.body) if reply.ctype == "application/json" else reply.body)

    def post(self, route, **body):
        return self.call("POST", f"{BASE}/api/{route}", body)

    def launch(self, sid=SID, roster=ROSTER, headers=None, **kw):
        message = protocol.launch_message(self.key, GAME, sid, roster, **kw)
        return self.call("POST", party.LAUNCH, {"message": message}, headers)

    def end(self, sid=SID, headers=None, **kw):
        message = protocol.end_message(self.key, GAME, sid, **kw)
        return self.call("POST", party.END, {"message": message}, headers)

    def ticket(self, pid, role="player", sid=SID, key=None):
        return protocol.mint_ticket(key or self.key, GAME, sid, pid, role)

    def seat(self, pid, role="player", sid=SID):
        """Redeem a fresh ticket: {"ok", "token", "role", "view"}."""
        status, body = self.post("redeem", ticket=self.ticket(pid, role, sid))
        assert status == 200, body
        return body

    def two(self):
        """Launch the session and seat Ana and Ben: (ana, ben)."""
        assert self.launch()[0] == 200
        return self.seat(ANA), self.seat(BEN)

    def move(self, who, path):
        return self.post("move", token=who["token"], v=who["view"]["v"], move=path)

    def reported(self):
        assert self.app.wait_for_reports()
        return list(self.reports)


@pytest.fixture
def rig():
    return Rig()


# ---- Party Core: launch and end ---------------------------------------------------------------

PROXY_HEADER_NAMES = ("X-Forwarded-For", "X-Real-IP", "Forwarded")


def test_the_proxy_headers_these_tests_try_are_the_ones_the_guard_knows():
    assert {name.lower() for name in PROXY_HEADER_NAMES} == set(party.PROXY_HEADERS)


@pytest.mark.parametrize("header", PROXY_HEADER_NAMES)
@pytest.mark.parametrize("value", ("10.42.0.23", ""), ids=("with a value", "empty"))
def test_control_routes_refuse_every_proxy_header_and_do_nothing(rig, header, value):
    # The header's presence is what refuses, whatever it says: an empty one came through the front door too.
    for path, message in ((party.LAUNCH, protocol.launch_message(rig.key, GAME, SID, ROSTER)),
                          (party.END, protocol.end_message(rig.key, GAME, SID))):
        assert rig.call("POST", path, {"message": message}, {header: value})[0] == 404
    assert rig.app.side.sid is None and rig.app.match is None
    assert rig.launch()[0] == 200                       # the same kind of message, unproxied
    assert rig.app.side.sid == SID


def test_a_control_route_is_post_only_and_other_control_paths_are_not_found(rig):
    assert rig.call("GET", party.LAUNCH)[0] == 404
    assert rig.call("GET", party.END)[0] == 404
    assert rig.call("POST", BASE + "/avrana/session/v0/other", {})[0] == 404
    assert rig.call("POST", BASE + "/avrana/", {})[0] == 404


def test_forged_replayed_expired_and_misdirected_launches_are_refused(rig):
    forged = protocol.launch_message(protocol.new_key(), GAME, SID, ROSTER)
    assert rig.call("POST", party.LAUNCH, {"message": forged})[0] == 403
    elsewhere = protocol.launch_message(rig.key, "bluff", SID, ROSTER)       # right key, another game
    assert rig.call("POST", party.LAUNCH, {"message": elsewhere})[0] == 403
    assert rig.launch(now=time.time() - 3600)[0] == 403                        # expired
    ended = protocol.end_message(rig.key, GAME, SID)                           # the wrong type
    assert rig.call("POST", party.LAUNCH, {"message": ended})[0] == 403
    assert rig.app.side.sid is None and rig.app.match is None
    message = protocol.launch_message(rig.key, GAME, SID, ROSTER)
    assert rig.call("POST", party.LAUNCH, {"message": message})[0] == 200
    assert rig.call("POST", party.LAUNCH, {"message": message})[0] == 403      # a replay


def test_bodies_are_strict_json(rig):
    for raw in (b"", b"not json", b"[]", b'{"message": 1}', b'{"message": "x", "extra": "y"}',
                b'{"message": "a", "message": "b"}', b'{"message": NaN}', b"\xff", b'"message"'):
        for path in (party.LAUNCH, party.END):
            assert rig.call("POST", path, data=raw)[0] == 400, (path, raw)
    redeem, poll = BASE + "/api/redeem", BASE + "/api/poll"
    for raw in (b'{"ticket": 1}', b"{}", b'{"ticket": "x", "token": "y"}'):
        assert rig.call("POST", redeem, data=raw)[0] == 400, raw
    for raw in (rb'{"ticket": "\ud800"}', rb'{"ticket": "a\udfffb"}'):                # a lone surrogate is not text
        assert rig.call("POST", redeem, data=raw)[0] == 400, raw
    assert rig.call("POST", party.LAUNCH, data=rb'{"message": "\ud800"}')[0] == 400
    assert rig.call("POST", poll, data=rb'{"token": "\ud800", "since": 1}')[0] == 400
    for raw in (b'{"token": "x"}', b'{"token": "x", "since": "1"}', b'{"token": "x", "since": 1.5}',
                b'{"token": "x", "since": true}', b'{"token": "x", "since": 1e400}',
                b'{"token": "x", "since": 99999999999999999}', b'{"token": 1, "since": 1}'):
        assert rig.call("POST", poll, data=raw)[0] == 400, raw
    move = BASE + "/api/move"
    for raw in (b'{"token": "x", "v": 1, "move": "1,2"}', b'{"token": "x", "v": 1, "move": [1, "2"]}',
                b'{"token": "x", "v": 1, "move": [1, 2.0]}', b'{"token": "x", "v": 1, "move": [true, 2]}',
                b'{"token": "x", "v": 1, "move": [[1, 2]]}', b'{"token": "x", "v": 1}',
                b'{"token": "x", "v": 1, "move": ' + str(list(range(65))).encode() + b"}"):
        assert rig.call("POST", move, data=raw)[0] == 400, raw
    assert rig.call("POST", BASE + "/api/resign", data=b'{"token": "x", "v": 1}')[0] == 400


def test_a_launch_seats_the_first_two_players_in_roster_order(rig):
    assert rig.launch() == (200, {"ok": True})
    ana, ben = rig.seat(ANA), rig.seat(BEN)
    assert (ana["role"], ana["view"]["seat"], ana["view"]["names"]) == ("player", "w", {"w": "Ana", "b": "Ben"})
    assert (ben["role"], ben["view"]["seat"]) == ("player", "b")
    assert ana["token"] != ben["token"] and ana["token"].startswith("avr-")

    swapped = Rig()
    swapped.launch(roster=[ROSTER[1], ROSTER[0], ROSTER[2]])
    assert swapped.seat(BEN)["view"]["seat"] == "w" and swapped.seat(ANA)["view"]["seat"] == "b"


def test_a_roster_without_exactly_two_players_is_refused_and_the_session_is_reset(rig):
    ana, ben = {**ROSTER[0]}, {**ROSTER[1]}
    cal_playing = {"participant": CAL, "name": "Cal", "role": "player"}
    deb_playing = {"participant": DEB, "name": "Deb", "role": "player"}
    for roster in ([], [ana], [ana, ROSTER[2]], [ana, ben, cal_playing], [ana, ben, cal_playing, deb_playing]):
        status, body = rig.launch(roster=roster)
        assert (status, body) == (409, {"ok": False, "message": "Checkers needs two players."}), roster
        assert rig.app.side.sid is None and rig.app.match is None, roster
        assert rig.post("redeem", ticket=rig.ticket(ANA))[0] == 403, roster       # nothing admits it
    assert rig.launch()[0] == 200                                                   # and the next one works
    assert rig.seat(ANA)["view"]["seat"] == "w"


def test_a_refused_launch_ends_the_match_that_was_running(rig):
    ana, ben = rig.two()
    assert rig.launch(sid=SID2, roster=[ROSTER[0]])[0] == 409
    assert rig.post("poll", token=ana["token"], since=0)[0] == 403
    assert rig.post("move", token=ben["token"], v=1, move=[1, 2])[0] == 403


def test_the_same_person_listed_twice_is_not_two_players(rig):
    twin = [ROSTER[0], {**ROSTER[0], "name": "Ana again"}]
    assert rig.launch(roster=twin)[0] == 409
    assert rig.app.side.sid is None and rig.app.match is None


def test_a_newer_launch_replaces_the_match_and_forgets_every_seat(rig):
    ana, _ = rig.two()
    assert rig.move(ana, ana["view"]["moves"][0])[0] == 200
    assert rig.launch(sid=SID2, roster=[ROSTER[1], ROSTER[0]])[0] == 200
    assert rig.post("poll", token=ana["token"], since=0)[0] == 403           # the old seat is gone
    assert rig.post("redeem", ticket=rig.ticket(ANA, sid=SID))[0] == 403     # and the old session's tickets
    fresh = rig.seat(ANA, sid=SID2)
    assert (fresh["view"]["seat"], fresh["view"]["v"], fresh["view"]["lastMove"]) == ("b", 1, None)
    assert fresh["token"] != ana["token"]                                    # a token is per session


def test_end_drops_the_match_and_later_polls_are_refused(rig):
    ana, ben = rig.two()
    end = protocol.end_message(rig.key, GAME, SID)
    assert rig.call("POST", party.END, {"message": end}) == (200, {"ok": True})
    assert rig.app.match is None and rig.app.side.sid is None and not rig.app.tokens
    for who in (ana, ben):
        assert rig.post("poll", token=who["token"], since=0)[0] == 403
        assert rig.move(who, [1, 2])[0] == 403
        assert rig.post("resign", token=who["token"])[0] == 403
    assert rig.call("POST", party.END, {"message": end})[0] == 403               # a replay
    assert rig.post("redeem", ticket=rig.ticket(ANA))[0] == 403                  # a late ticket
    assert rig.reported() == []                                                   # ended by the Party: no report


def test_an_end_for_another_session_or_a_forged_end_changes_nothing(rig):
    ana, _ = rig.two()
    assert rig.end(sid=SID2)[0] == 403
    forged = protocol.end_message(protocol.new_key(), GAME, SID)
    assert rig.call("POST", party.END, {"message": forged})[0] == 403
    assert rig.call("POST", party.END, {"message": protocol.launch_message(rig.key, GAME, SID, ROSTER)})[0] == 403
    assert rig.end(headers={"X-Forwarded-For": "10.42.0.2"})[0] == 404
    assert rig.post("poll", token=ana["token"], since=0)[0] == 200               # the match runs on


def test_an_end_wakes_the_polls_that_are_waiting():
    rig = Rig(poll_seconds=30)
    ana, _ = rig.two()
    answer = {}

    def wait():
        answer["reply"] = rig.post("poll", token=ana["token"], since=ana["view"]["v"])
    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    wait_until(lambda: rig.app.pollers == 1, what="the poll to wait")
    started = time.monotonic()
    assert rig.end()[0] == 200
    thread.join(5)
    assert not thread.is_alive() and time.monotonic() - started < 3
    assert answer["reply"][0] == 403 and rig.app.pollers == 0


# ---- the phones: seats ------------------------------------------------------------------------

def test_redeem_is_single_use_and_a_reload_gets_the_same_seat(rig):
    rig.launch()
    ticket = rig.ticket(ANA)
    status, first = rig.post("redeem", ticket=ticket)
    assert status == 200
    assert rig.post("redeem", ticket=ticket)[0] == 403                           # the same ticket again
    again = rig.seat(ANA)                                                         # a reload: a fresh ticket
    assert (again["token"], again["role"], again["view"]) == (first["token"], "player", first["view"])
    assert again["view"]["seat"] == "w"


def test_a_reload_after_moves_gets_the_board_as_it_is(rig):
    ana, ben = rig.two()
    path = ana["view"]["moves"][0]
    assert rig.move(ana, path)[0] == 200
    again = rig.seat(ANA)
    assert (again["view"]["v"], again["view"]["lastMove"]["path"], again["view"]["turn"]) == (2, path, "b")
    assert again["view"]["moves"] == []                                          # not Ana's turn
    assert rig.seat(BEN)["view"]["moves"] != []


def test_redeem_refuses_forged_wrong_session_early_and_malformed_tickets(rig):
    assert rig.post("redeem", ticket=rig.ticket(ANA))[0] == 403                  # nothing launched
    rig.launch()
    assert rig.post("redeem", ticket=rig.ticket(ANA, key=protocol.new_key()))[0] == 403
    assert rig.post("redeem", ticket=rig.ticket(ANA, sid=SID2))[0] == 403
    assert rig.post("redeem", ticket=protocol.mint_ticket(rig.key, "bluff", SID, ANA, "player"))[0] == 403
    assert rig.post("redeem", ticket=protocol.launch_message(rig.key, GAME, SID, ROSTER))[0] == 403
    assert rig.post("redeem", ticket="aps0.x.y")[0] == 403
    assert rig.post("redeem", ticket="")[0] == 403
    expired = protocol.mint_ticket(rig.key, GAME, SID, ANA, "player", now=time.time() - 3600)
    assert rig.post("redeem", ticket=expired)[0] == 403
    assert not rig.app.tokens                                                     # none of it seated anyone


def test_a_ticket_for_a_launched_session_with_no_match_is_told_so():
    rig = Rig()
    rig.launch()
    rig.app.match = None                                                          # as if dropped by hand
    status, body = rig.post("redeem", ticket=rig.ticket(ANA))
    assert (status, body["message"]) == (409, "There is no game.")


def test_a_spectator_sees_the_board_and_nothing_else(rig):
    ana, _ = rig.two()
    cal = rig.seat(CAL, "spectator")
    assert (cal["role"], cal["view"]["seat"], cal["view"]["moves"]) == ("spectator", None, [])
    assert cal["view"]["board"] == ana["view"]["board"] and cal["view"]["turn"] == "w"
    status, body = rig.move(cal, [sq(5, 0), sq(4, 1)])
    assert (status, body["error"], body["message"]) == (403, "watching", "You are watching this game.")
    assert rig.post("resign", token=cal["token"])[0] == 403
    assert rig.post("poll", token=cal["token"], since=0)[0] == 200                # watching is allowed
    assert rig.app.match.v == 1 and not rig.app.match.over


def test_somebody_not_on_the_roster_can_only_watch(rig):
    rig.launch()
    deb = rig.seat(DEB, "spectator")
    assert (deb["role"], deb["view"]["seat"]) == ("spectator", None)
    assert rig.seat(DEB, "player")["role"] == "spectator"                        # a ticket's word does not seat anyone
    assert rig.post("resign", token=deb["token"])[0] == 403


def test_a_token_is_only_good_if_this_session_handed_it_out(rig):
    rig.launch()
    ana = rig.seat(ANA)
    derivable = protocol.game_token(rig.key, SID, BEN)       # only the key can make it; Ben never redeemed
    for token in (derivable, "avr-" + "0" * 40, "", "x" * 5000, ana["token"] + "0", ana["token"][:-1],
                  ana["token"].upper(), "avr-é"):
        assert rig.post("poll", token=token, since=0)[0] == 403, token
        assert rig.post("move", token=token, v=1, move=[1, 2])[0] == 403, token
        assert rig.post("resign", token=token)[0] == 403, token


def test_nothing_the_phones_are_sent_names_a_participant(rig):
    ana, ben = rig.two()
    cal = rig.seat(CAL, "spectator")
    replies = [ana, ben, cal, rig.post("poll", token=ana["token"], since=0)[1], rig.move(ana, ana["view"]["moves"][0])[1],
               rig.move(ana, [1, 2])[1], rig.post("resign", token=ben["token"])[1]]
    text = json.dumps(replies)
    for pid in (ANA, BEN, CAL, "participant-"):
        assert pid not in text
    assert rig.call("GET", BASE + "/api/party")[1] == {"partyOrigin": ORIGIN}


# ---- the phones: what each seat is shown ------------------------------------------------------

def test_each_seat_is_shown_its_own_moves_and_nobody_elses(rig):
    ana, ben = rig.two()
    cal = rig.seat(CAL, "spectator")
    assert ana["view"]["moves"] and ben["view"]["moves"] == [] and cal["view"]["moves"] == []
    assert set(ana["view"]) == VIEW_KEYS == set(ben["view"]) == set(cal["view"])
    assert ana["view"]["mustCapture"] is False
    assert rig.move(ana, ana["view"]["moves"][0])[0] == 200
    for token, who in ((ben["token"], "b"), (ana["token"], "w"), (cal["token"], None)):
        view = rig.post("poll", token=token, since=1)[1]["view"]
        assert (view["moves"] != []) == (who == "b"), who
        assert view["turn"] == "b" and view["v"] == 2


def test_a_move_changes_the_board_once_and_the_poll_sees_it(rig):
    ana, ben = rig.two()
    path = ana["view"]["moves"][0]
    status, body = rig.move(ana, path)
    assert (status, body["ok"], body["view"]["v"], body["view"]["turn"]) == (200, True, 2, "b")
    assert body["view"]["lastMove"] == {"by": "w", "path": path, "captured": []}
    assert body["view"]["board"][path[0]] is None and body["view"]["board"][path[-1]] == "w"
    polled = rig.post("poll", token=ben["token"], since=1)[1]["view"]                # Ben was behind: at once
    assert polled["v"] == 2 and polled["lastMove"] == body["view"]["lastMove"] and polled["moves"]


def test_an_illegal_move_is_a_409_that_changes_nothing_and_carries_the_current_view(rig):
    ana, ben = rig.two()
    before = rig.post("poll", token=ana["token"], since=0)[1]["view"]
    for path in ([0, 1], [sq(5, 0), sq(3, 2)], [sq(2, 1), sq(3, 2)], [5], [sq(5, 0), sq(4, 1), sq(3, 2)], [1, 2, 3, 4]):
        status, body = rig.move(ana, path)
        assert (status, body["ok"], body["error"]) == (409, False, "illegal"), path
        assert body["message"] == "That move is not allowed." and body["view"] == before
    assert rig.post("poll", token=ana["token"], since=0)[1]["view"] == before


def test_a_move_out_of_turn_or_on_a_stale_board_is_a_409(rig):
    ana, ben = rig.two()
    assert rig.move(ben, ana["view"]["moves"][0])[1]["error"] == "not_your_turn"
    first, second = ana["view"]["moves"][0], ana["view"]["moves"][1]
    assert rig.move(ana, first)[0] == 200
    status, body = rig.post("move", token=ben["token"], v=1, move=rig.seat(BEN)["view"]["moves"][0])
    assert (status, body["error"], body["message"]) == (409, "stale", "The board changed. Look again.")
    assert body["view"]["v"] == 2
    assert rig.post("move", token=ana["token"], v=2, move=second)[1]["error"] == "not_your_turn"


def test_the_compulsory_capture_is_enforced_in_the_servers_words():
    pieces = {(5, 2): "w", (4, 3): "b", (7, 0): "w", (0, 1): "b"}
    rig = Rig(new_match=start_from(pieces))
    ana, _ = rig.two()
    assert ana["view"]["mustCapture"] is True and ana["view"]["moves"] == [[sq(5, 2), sq(3, 4)]]
    status, body = rig.move(ana, [sq(7, 0), sq(6, 1)])
    assert (status, body["error"], body["message"]) == (409, "illegal", "A capture is compulsory.")
    assert rig.move(ana, [sq(5, 2), sq(3, 4)])[0] == 200


def test_a_poll_waits_for_a_change_and_then_says_nothing_new():
    rig = Rig(poll_seconds=0.2)
    ana, ben = rig.two()
    started = time.monotonic()
    status, body = rig.post("poll", token=ben["token"], since=ben["view"]["v"])
    assert (status, body["view"]["v"]) == (200, 1) and 0.15 <= time.monotonic() - started < 3
    assert rig.app.pollers == 0
    assert rig.post("poll", token=ben["token"], since=0)[1]["view"]["v"] == 1       # behind: answered at once


def test_a_waiting_poll_is_answered_by_the_move_it_was_waiting_for():
    rig = Rig(poll_seconds=30)
    ana, ben = rig.two()
    answer = {}
    thread = threading.Thread(target=lambda: answer.update(reply=rig.post("poll", token=ben["token"], since=1)), daemon=True)
    thread.start()
    wait_until(lambda: rig.app.pollers == 1, what="the poll to wait")
    assert rig.move(ana, ana["view"]["moves"][0])[0] == 200
    thread.join(5)
    assert not thread.is_alive()
    status, body = answer["reply"]
    assert (status, body["view"]["v"], body["view"]["turn"]) == (200, 2, "b") and body["view"]["moves"]


def test_a_party_has_room_for_a_few_waiting_polls_and_no_more(monkeypatch):
    monkeypatch.setattr(server, "MAX_POLLERS", 2)
    rig = Rig(poll_seconds=30)
    ana, ben = rig.two()
    cal = rig.seat(CAL, "spectator")
    answers = []
    threads = [threading.Thread(target=lambda t=who["token"]: answers.append(rig.post("poll", token=t, since=1)), daemon=True)
               for who in (ana, ben)]
    for thread in threads:
        thread.start()
    wait_until(lambda: rig.app.pollers == 2, what="two polls to wait")
    status, body = rig.post("poll", token=cal["token"], since=1)
    assert (status, body["error"]) == (503, "busy")
    assert rig.end()[0] == 200                                                       # and they are all let go
    for thread in threads:
        thread.join(5)
    assert rig.app.pollers == 0 and [a[0] for a in answers] == [403, 403]


# ---- the end of a game ------------------------------------------------------------------------

def test_taking_the_last_piece_ends_the_game_and_reports_the_result_to_the_party():
    rig = Rig(new_match=start_from({(5, 2): "w", (4, 3): "b"}))
    ana, ben = rig.two()
    status, body = rig.move(ana, [sq(5, 2), sq(3, 4)])
    assert status == 200
    for view in (body["view"], rig.post("poll", token=ben["token"], since=1)[1]["view"]):
        assert view["result"] == {"winner": "w", "ending": "captured", "plies": 1}
        assert view["turn"] is None and view["moves"] == []
    [message] = rig.reported()
    payload, checked = opened(rig.key, message)
    assert standings(checked) == {ANA: "won", BEN: "lost"}
    assert (checked["game"], checked["mode"]) == ({"id": GAME, "build": party.BUILD}, "competitive")
    assert (checked["data_schema"], checked["data"]) == ("checkers.result/v1", {"ending": "captured", "plies": 1})
    assert [e["participant"] for e in checked["standings"]] == [ANA, BEN]


def test_black_can_win_and_the_result_says_so():
    rig = Rig(new_match=start_from({(2, 1): "b", (3, 2): "w"}, turn="b"))
    _, ben = rig.two()
    assert rig.move(ben, [sq(2, 1), sq(4, 3)])[0] == 200
    [message] = rig.reported()
    assert standings(opened(rig.key, message)[1]) == {ANA: "lost", BEN: "won"}


def test_a_resignation_gives_the_game_to_the_other_player_whoever_resigns_and_whenever():
    for resigner, winner, loser in (("ben", ANA, BEN), ("ana", BEN, ANA)):
        rig = Rig()
        ana, ben = rig.two()
        status, body = rig.post("resign", token={"ana": ana, "ben": ben}[resigner]["token"])    # Ben is out of turn
        assert (status, body["view"]["result"]) == (200, {"winner": "w" if winner == ANA else "b", "ending": "resigned", "plies": 0})
        [message] = rig.reported()
        payload, checked = opened(rig.key, message)
        assert standings(checked) == {winner: "won", loser: "lost"}
        assert checked["data"] == {"ending": "resigned", "plies": 0}


def test_the_final_board_stays_readable_and_the_finished_game_takes_nothing_more():
    rig = Rig(new_match=start_from({(5, 2): "w", (4, 3): "b"}))
    ana, ben = rig.two()
    cal = rig.seat(CAL, "spectator")
    rig.move(ana, [sq(5, 2), sq(3, 4)])
    rig.reported()
    for who, seat in ((ana, "w"), (ben, "b"), (cal, None)):
        view = rig.post("poll", token=who["token"], since=1)[1]["view"]
        assert (view["seat"], view["result"]["winner"], view["lastMove"]["by"]) == (seat, "w", "w")
    status, body = rig.move(ana, [sq(3, 4), sq(2, 3)])
    assert (status, body["error"], body["message"]) == (409, "over", "The game is over.")
    assert rig.post("resign", token=ben["token"])[1]["error"] == "over"
    assert len(rig.reports) == 1                                                       # and nothing more is reported
    assert rig.post("redeem", ticket=rig.ticket(ANA))[0] == 403                       # the session no longer admits


def test_the_party_reports_are_sent_after_the_lock_is_released():
    """A slow Party must not hold the game: the answer to the winning move comes back, and the
    other phone can read the final board, while the report is still being delivered."""
    gate, started = threading.Event(), threading.Event()
    seen = []

    def slow(message):
        seen.append(message)
        started.set()
        gate.wait(10)
        return 200, "accepted"
    rig = Rig(report=slow, new_match=start_from({(5, 2): "w", (4, 3): "b"}))
    ana, ben = rig.two()
    try:
        assert rig.move(ana, [sq(5, 2), sq(3, 4)])[0] == 200            # returns although the report is not done
        assert started.wait(5)
        assert rig.post("poll", token=ben["token"], since=1)[1]["view"]["result"]["winner"] == "w"
        assert rig.app.cond.acquire(timeout=1)                          # the lock is free while it waits
        rig.app.cond.release()
        assert not rig.app.wait_for_reports(timeout=0.05)
    finally:
        gate.set()
    assert rig.app.wait_for_reports() and len(seen) == 1


def test_a_party_that_does_not_answer_is_asked_again_with_the_same_message():
    rig = Rig(new_match=start_from({(5, 2): "w", (4, 3): "b"}))
    rig.answer = (None, None)
    ana, _ = rig.two()
    rig.move(ana, [sq(5, 2), sq(3, 4)])
    messages = rig.reported()
    assert len(messages) == 1 + len(party.REPORT_RETRY_AFTER) and len(set(messages)) == 1
    assert rig.slept == list(party.REPORT_RETRY_AFTER)
    opened(rig.key, messages[0])


@pytest.mark.parametrize("answers,tries", (
    ([(200, "accepted")], 1), ([(200, "refused")], 1), ([(409, None)], 1), ([(400, None)], 1),
    ([(None, None), (200, "accepted")], 2), ([(503, None), (502, None), (200, "accepted")], 3),
    ([(None, None)] * 9, 4),
))
def test_the_reporter_stops_at_an_answer_and_keeps_asking_only_while_there_is_none(answers, tries):
    calls, sleeps = [], []

    def report(message):
        calls.append(message)
        return answers[min(len(calls), len(answers)) - 1]
    last = party.deliver(report, "m", sleep=sleeps.append)
    assert len(calls) == tries and last == answers[min(tries, len(answers)) - 1]
    assert sleeps == list(party.REPORT_RETRY_AFTER[:tries - 1])


def test_a_result_the_party_would_refuse_is_left_out_but_the_session_still_ends(rig, monkeypatch, caplog):
    def refuse(*args, **kw):
        raise party_result.Refused("size")
    monkeypatch.setattr(party, "make_result", refuse)
    ana, _ = rig.two()
    with caplog.at_level(logging.INFO, logger="checkers"):
        assert rig.post("resign", token=ana["token"])[0] == 200
    [message] = rig.reported()
    payload = protocol.open_message(rig.key, message, "ended", "party", protocol.ReplayGuard())
    assert payload["outcome"] == "completed" and "result" not in payload
    assert "would be refused" in caplog.text


def test_the_party_going_home_from_the_results_is_acknowledged_and_releases_the_match():
    rig = Rig(new_match=start_from({(5, 2): "w", (4, 3): "b"}))
    ana, ben = rig.two()
    rig.move(ana, [sq(5, 2), sq(3, 4)])
    rig.reported()
    assert rig.end(sid=SID2)[0] == 403                                  # another session's end: nothing happens
    assert rig.app.match is not None
    end = protocol.end_message(rig.key, GAME, SID)
    assert rig.call("POST", party.END, {"message": end}) == (200, {"ok": True})
    assert rig.app.match is None and not rig.app.tokens
    assert rig.call("POST", party.END, {"message": end})[0] == 403       # once only
    assert rig.post("poll", token=ben["token"], since=0)[0] == 403
    assert rig.end()[0] == 403                                            # and nothing is left to end


def test_nothing_secret_is_logged(rig, caplog):
    with caplog.at_level(logging.DEBUG):
        rig.launch()
        ticket = rig.ticket(ANA)
        ana = rig.post("redeem", ticket=ticket)[1]
        rig.post("redeem", ticket=ticket)
        rig.post("redeem", ticket=rig.ticket(ANA, key=protocol.new_key()))
        rig.post("poll", token="avr-" + "1" * 40, since=0)
        rig.move(ana, [1, 2])
        rig.post("resign", token=ana["token"])
        message = rig.reported()[0]
    text = caplog.text
    assert "finished (resigned after 0 moves)" in text
    for secret in (ticket, ana["token"], rig.key.hex(), message, ANA, BEN, "Ana", "Ben"):
        assert secret not in text


def test_the_page_is_told_where_the_party_is_and_nothing_else_decides_it():
    for origin in (None, ORIGIN):
        rig = Rig()
        rig.app.party_origin = origin
        assert rig.call("GET", BASE + "/api/party") == (200, {"partyOrigin": origin})
        frame = origin if origin else "'none'"
        assert f"frame-src {frame};" in server.page_policy(origin)
    policy = server.page_policy(ORIGIN)
    for want in ("default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
                 "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
        assert want in policy
    assert "unsafe" not in policy and "*" not in policy


# ---- what is served ---------------------------------------------------------------------------

def test_exactly_the_listed_files_are_served_and_nothing_else(rig):
    for path, (source, ctype) in server.FILES.items():
        reply = rig.raw("GET", path)
        assert (reply.status, reply.ctype, reply.body) == (200, ctype, source.read_bytes()), path
    page = dict(rig.raw("GET", server.PAGE).headers)
    assert page["Content-Security-Policy"] == server.page_policy(ORIGIN)
    assert dict(rig.raw("GET", server.BASE + "/web/checkers.js").headers)["Content-Security-Policy"] == "default-src 'none'"
    for path in ("/", BASE, BASE + "/web/", BASE + "/web/nope.js", BASE + "/web/../server.py", BASE + "/server.py",
                 BASE + "/checkers.key", BASE + "/web/%2e%2e/rules.py", BASE + "//", "/games/bluff/",
                 BASE + "/api/", BASE + "/api/unknown", BASE + "/avrana/"):
        assert rig.call("GET", path)[0] == 404, path
    for path in (server.PAGE, BASE + "/api/party", BASE + "/web/checkers.css"):
        assert rig.call("POST", path, {})[0] == 405, path
    for path in server.POSTS:
        assert rig.call("GET", path)[0] == 405, path


def test_the_bridge_shim_is_served_byte_for_byte_from_the_repository_copy(rig):
    pinned = json.loads((ROOT / "provider/avrana-contract.json").read_text(encoding="utf-8"))["bridge"]
    reply = rig.raw("GET", BASE + "/web/avrana-party-bridge.js")
    assert reply.status == 200 and reply.body == (ROOT / pinned["vendored"]).read_bytes()
    assert hashlib.sha256(reply.body.replace(b"\r\n", b"\n")).hexdigest() == pinned["vendored_sha256"]
    assert server.FILES[BASE + "/web/avrana-party-bridge.js"][0] == ROOT / "web" / "avrana-party-bridge.js"


# ===================================================================== the real HTTP server (TCP)

class NoDelayConnection(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def tcp_connect(address, timeout):
    """`report_to`'s connection factory for a Party listening on loopback TCP."""
    return NoDelayConnection(address[0], address[1], timeout=timeout)


class FakeParty:
    """The Party's internal socket, as a loopback TCP server: it records what is posted to it and
    answers as told."""

    def __init__(self):
        self.received = []                            # (path, content type, body)
        self.reply = (200, b'{"ok": true, "result": "accepted"}')
        self.delay = 0
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))   # all of it, then answer
                outer.received.append((self.path, self.headers.get("Content-Type"), body))
                time.sleep(outer.delay)
                status, raw = outer.reply
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        self.address = self.httpd.server_address

    def messages(self):
        return [json.loads(body)["message"] for _, _, body in self.received]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_party():
    fake = FakeParty()
    yield fake
    fake.close()


def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    return sock


class Client:
    """A phone and Party Core in one: real HTTP to a game on loopback TCP, with the game's key."""

    def __init__(self, port, key):
        self.port, self.key = port, key

    def request(self, method, path, body=None, headers=None, data=None, timeout=15):
        conn = NoDelayConnection("127.0.0.1", self.port, timeout=timeout)
        headers = dict(headers or {})
        if data is None and body is not None:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=data, headers=headers)
            reply = conn.getresponse()
            return reply.status, reply.read(), {k.lower(): v for k, v in reply.getheaders()}
        finally:
            conn.close()

    def call(self, method, path, body=None, headers=None, data=None):
        status, raw, _ = self.request(method, path, body, headers, data)
        return status, json.loads(raw) if raw[:1] in (b"{", b"[") else raw

    def post(self, route, **body):
        return self.call("POST", f"{BASE}/api/{route}", body)

    def launch(self, sid=SID, roster=ROSTER, headers=None):
        message = protocol.launch_message(self.key, GAME, sid, roster)
        return self.call("POST", party.LAUNCH, {"message": message}, headers)

    def end(self, sid=SID, headers=None):
        return self.call("POST", party.END, {"message": protocol.end_message(self.key, GAME, sid)}, headers)

    def seat(self, pid, role="player", sid=SID):
        status, body = self.post("redeem", ticket=protocol.mint_ticket(self.key, GAME, sid, pid, role))
        assert status == 200, body
        return body

    def two(self):
        assert self.launch() == (200, {"ok": True})
        return self.seat(ANA), self.seat(BEN)


class Live(Client):
    """The real server on loopback TCP, with the App behind it."""

    def __init__(self, fake, **options):
        self.fake = fake
        self.app = server.App(protocol.GameSide(protocol.new_key(), GAME),
                              lambda message: party.report_to(fake.address, message, connect=tcp_connect),
                              party_origin=ORIGIN, **options)
        self.sock = listener()
        self.httpd = party.make_server(self.sock, self.app, families=(socket.AF_INET,))
        super().__init__(self.sock.getsockname()[1], self.app.side.key)
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def live(fake_party):
    live = Live(fake_party)
    yield live
    live.close()


def play_out(live, tokens, views, rng, cap=900):
    """Both players play only moves the server offered them, until the game is over."""
    for _ in range(cap):
        if views["w"]["result"]:
            return
        mover = views["w"]["turn"]
        other = "b" if mover == "w" else "w"
        mine = views[mover]
        status, body = live.post("move", token=tokens[mover], v=mine["v"], move=rng.choice(mine["moves"]))
        assert status == 200, body
        views[mover] = body["view"]
        status, body = live.post("poll", token=tokens[other], since=views[other]["v"])
        assert status == 200, body
        views[other] = body["view"]
    raise AssertionError("the game did not finish")


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_a_whole_game_over_http_ends_with_one_consistent_result_at_the_party(live, fake_party, seed):
    ana, ben = live.two()
    tokens, views = {"w": ana["token"], "b": ben["token"]}, {"w": ana["view"], "b": ben["view"]}
    play_out(live, tokens, views, random.Random(seed))
    final = views["w"]["result"]
    assert views["b"]["result"] == final and final["ending"] in ENDINGS
    assert views["w"]["v"] == views["b"]["v"] == 1 + final["plies"]

    wait_until(lambda: len(fake_party.received) >= 1, what="the report to reach the party")
    path, ctype, body = fake_party.received[0]
    assert (path, ctype, list(json.loads(body))) == ("/internal/party-session/v0/ended", "application/json", ["message"])
    payload, checked = opened(live.key, fake_party.messages()[0])
    mine = {"w": ANA, "b": BEN}
    if final["winner"] is None:
        assert standings(checked) == {ANA: "draw", BEN: "draw"}
    else:
        winner = mine[final["winner"]]
        assert standings(checked) == {winner: "won", (BEN if winner == ANA else ANA): "lost"}
    assert checked["data"] == {"ending": final["ending"], "plies": final["plies"]}
    assert live.app.wait_for_reports() and len(fake_party.received) == 1


def test_the_two_phones_see_what_the_rules_say_through_a_game_with_a_capture(live, fake_party):
    ana, ben = live.two()
    # Two quiet moves that bring the men together, then the forced jump.
    first = [sq(5, 2), sq(4, 3)]
    assert first in ana["view"]["moves"]
    status, body = live.post("move", token=ana["token"], v=1, move=first)
    assert status == 200
    status, body = live.post("poll", token=ben["token"], since=1)
    reply = [sq(2, 5), sq(3, 4)]
    assert reply in body["view"]["moves"] and body["view"]["mustCapture"] is False
    live.post("move", token=ben["token"], v=2, move=reply)
    view = live.post("poll", token=ana["token"], since=2)[1]["view"]
    assert view["mustCapture"] is True and view["moves"] == [[sq(4, 3), sq(2, 5)]]
    status, body = live.post("move", token=ana["token"], v=3, move=[sq(5, 0), sq(4, 1)])
    assert (status, body["message"]) == (409, "A capture is compulsory.")
    status, body = live.post("move", token=ana["token"], v=3, move=[sq(4, 3), sq(2, 5)])
    assert status == 200 and body["view"]["lastMove"]["captured"] == [sq(3, 4)]
    assert body["view"]["board"][sq(3, 4)] is None and body["view"]["board"][sq(2, 5)] == "w"


def test_resigning_over_http_reports_once_and_the_phones_keep_the_final_board(live, fake_party):
    ana, ben = live.two()
    cal = live.seat(CAL, "spectator")
    status, body = live.post("resign", token=ben["token"])
    assert (status, body["view"]["result"]) == (200, {"winner": "w", "ending": "resigned", "plies": 0})
    wait_until(lambda: fake_party.received, what="the report")
    assert standings(opened(live.key, fake_party.messages()[0])[1]) == {ANA: "won", BEN: "lost"}
    for who in (ana, ben, cal):
        view = live.post("poll", token=who["token"], since=1)[1]["view"]
        assert view["result"]["ending"] == "resigned" and view["turn"] is None
    assert live.post("resign", token=ana["token"])[1]["error"] == "over"
    assert live.post("redeem", ticket=protocol.mint_ticket(live.key, GAME, SID, ANA, "player"))[0] == 403
    assert live.end() == (200, {"ok": True})                    # Party's "go home": acknowledged
    assert live.post("poll", token=ana["token"], since=0)[0] == 403
    assert live.app.wait_for_reports() and len(fake_party.received) == 1


def test_a_slow_or_absent_party_never_holds_the_players(fake_party):
    fake_party.delay = 1.0
    live = Live(fake_party)
    try:
        ana, ben = live.two()
        started = time.monotonic()
        assert live.post("resign", token=ana["token"])[0] == 200
        assert time.monotonic() - started < 0.8                  # answered before the Party was
        assert live.post("poll", token=ben["token"], since=1)[1]["view"]["result"]["ending"] == "resigned"
        assert live.app.wait_for_reports(5) and len(fake_party.received) == 1
    finally:
        live.close()


def test_a_poll_over_http_waits_for_the_move_and_returns_when_it_comes(live):
    ana, ben = live.two()
    answer = {}
    thread = threading.Thread(target=lambda: answer.update(reply=live.post("poll", token=ben["token"], since=1)), daemon=True)
    thread.start()
    wait_until(lambda: live.app.pollers == 1, what="the poll to wait")
    time.sleep(0.1)
    assert thread.is_alive()                                      # held open, not answered
    assert live.post("move", token=ana["token"], v=1, move=ana["view"]["moves"][0])[0] == 200
    thread.join(5)
    assert not thread.is_alive()
    status, body = answer["reply"]
    assert (status, body["view"]["v"], body["view"]["turn"]) == (200, 2, "b")


def test_a_player_who_goes_away_leaves_the_game_waiting_and_comes_back_to_it(live, fake_party):
    ana, ben = live.two()
    live.post("move", token=ana["token"], v=1, move=ana["view"]["moves"][0])
    time.sleep(0.3)                                               # Ben is to move and nothing ever times him out
    view = live.post("poll", token=ana["token"], since=1)[1]["view"]
    assert (view["v"], view["turn"], view["result"]) == (2, "b", None)
    assert fake_party.received == [] and live.app.match.v == 2
    again = live.seat(BEN)                                        # Ben comes back with a fresh ticket
    assert (again["token"], again["view"]["v"], again["view"]["turn"]) == (ben["token"], 2, "b")
    assert again["view"]["moves"]
    assert live.post("move", token=again["token"], v=2, move=again["view"]["moves"][0])[0] == 200


def test_tickets_cannot_be_replayed_forged_or_used_for_another_session(live):
    live.launch()
    ticket = protocol.mint_ticket(live.key, GAME, SID, ANA, "player")
    assert live.post("redeem", ticket=ticket)[0] == 200
    assert live.post("redeem", ticket=ticket)[0] == 403
    for bad in (protocol.mint_ticket(protocol.new_key(), GAME, SID, ANA, "player"),
                protocol.mint_ticket(live.key, GAME, SID2, ANA, "player"),
                protocol.mint_ticket(live.key, "bluff", SID, ANA, "player")):
        assert live.post("redeem", ticket=bad)[0] == 403
    assert live.launch(sid=SID2)[0] == 200
    assert live.post("redeem", ticket=protocol.mint_ticket(live.key, GAME, SID, BEN, "player"))[0] == 403


@pytest.mark.parametrize("players", (0, 1, 3))
def test_a_roster_that_is_not_two_players_is_refused_over_http(live, players):
    roster = [{"participant": "participant-" + c * 32, "name": c, "role": "player"} for c in "1234"[:players]]
    message = protocol.launch_message(live.key, GAME, SID, roster)
    status, body, _ = live.request("POST", party.LAUNCH, {"message": message})
    assert (status, json.loads(body)) == (409, {"ok": False, "message": "Checkers needs two players."})
    assert live.post("redeem", ticket=protocol.mint_ticket(live.key, GAME, SID, ANA, "player"))[0] == 403


def test_control_messages_through_a_proxy_are_refused_over_http(live):
    assert live.launch(headers={"X-Forwarded-For": "10.42.0.23"})[0] == 404
    assert live.launch(headers={"X-Real-IP": "10.42.0.23"})[0] == 404
    assert live.launch(headers={"Forwarded": "for=10.42.0.23"})[0] == 404
    for name in PROXY_HEADER_NAMES:                     # a header with nothing after the colon is still a header
        assert live.launch(headers={name: ""})[0] == 404, name
    assert live.app.match is None
    assert live.launch() == (200, {"ok": True})
    for name in PROXY_HEADER_NAMES:                     # and an end that came that way does not drop the match
        assert live.end(headers={name: ""})[0] == 404, name
    assert live.app.match is not None and live.app.side.sid == SID
    ana = live.seat(ANA)
    # page traffic arrives through nginx with proxy headers, and is served
    assert live.call("POST", BASE + "/api/poll", {"token": ana["token"], "since": 0}, {"X-Forwarded-For": "10.42.0.23"})[0] == 200


def test_every_answer_is_uncacheable_cookieless_and_sniff_proof(live):
    ana, ben = live.two()
    live.post("resign", token=ben["token"])
    requests = [("GET", server.PAGE, None), ("GET", BASE + "/web/checkers.js", None), ("GET", BASE + "/web/avrana-party-bridge.js", None),
                ("GET", BASE + "/onboarding.json", None), ("GET", BASE + "/api/party", None), ("GET", BASE + "/nope", None),
                ("POST", BASE + "/api/redeem", {"ticket": "x"}), ("POST", BASE + "/api/poll", {"token": ana["token"], "since": 0}),
                ("POST", BASE + "/api/move", {"token": ana["token"], "v": 1, "move": [1, 2]}),
                ("POST", BASE + "/api/resign", {"token": "avr-0"}), ("POST", party.LAUNCH, {"message": "x"}),
                ("POST", BASE + "/api/poll", {"nonsense": 1}), ("DELETE", BASE + "/api/poll", None)]
    for method, path, body in requests:
        status, _, headers = live.request(method, path, body)
        assert headers["cache-control"] == "no-store", (method, path)
        assert headers["x-content-type-options"] == "nosniff", (method, path)
        assert headers["referrer-policy"] == "no-referrer", (method, path)
        assert "set-cookie" not in headers and "access-control-allow-origin" not in headers, (method, path)
        assert "server" in headers and "python" not in headers["server"].lower(), (method, path)


def test_the_real_handler_refuses_what_is_not_small_json(live):
    url, json_type = BASE + "/api/redeem", {"Content-Type": "application/json"}
    assert live.request("POST", url, data=b"ticket=x", headers={"Content-Type": "application/x-www-form-urlencoded"})[0] == 415
    assert live.request("POST", url, data=b"{}")[0] == 415                          # no Content-Type at all
    assert live.request("POST", url, data=b"", headers=json_type)[0] == 400
    # A length that is too large (or not a number) is refused before any body is read.
    for length in ("16385", "99999999999", "-4", "many"):
        status, raw, headers = live.request("POST", url, headers=dict(json_type, **{"Content-Length": length}))
        assert (status, json.loads(raw)["error"]) == (413, "body_size"), length
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS"):
        status, raw, _ = live.request(method, url, data=b"{}", headers=json_type)
        assert (status, json.loads(raw)["error"]) == (405, "method"), method
    assert live.request("HEAD", url)[0] == 405
    status, raw, _ = live.request("GET", BASE + "/api/party?x=" + "a" * 100)
    assert (status, json.loads(raw)) == (200, {"partyOrigin": ORIGIN})              # the query is not read


def test_a_client_that_stalls_before_sending_is_let_go(fake_party, monkeypatch):
    monkeypatch.setattr(party, "REQUEST_TIMEOUT", 0.2)
    live = Live(fake_party)
    try:
        sock = socket.create_connection(("127.0.0.1", live.port), timeout=5)
        sock.sendall(b"POST /games/checkers/api/redeem HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 50\r\n\r\n{")
        sock.settimeout(5)
        started = time.monotonic()
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except OSError:
            pass
        assert time.monotonic() - started < 4 and b'"ok": true' not in data
        sock.close()
        assert live.post("redeem", ticket="x")[0] == 403                           # and the server is still serving
    finally:
        live.close()


# ---- the Party's side, and the process's own wiring -------------------------------------------

@pytest.mark.parametrize("reply,want", (
    ((200, b'{"ok": true, "result": "accepted"}'), (200, "accepted")),
    ((200, b'{"ok": true, "result": "refused", "reason": "x"}'), (200, "refused")),
    ((200, b'{"ok": true}'), (200, None)),
    ((200, b"not json"), (200, None)),
    ((200, b"[1]"), (200, None)),
    ((200, b'{"result": 7}'), (200, None)),
    ((400, b'{"ok": false}'), (400, None)),
    ((500, b'{"result": "accepted"}'), (500, "accepted")),
))
def test_the_report_reads_the_verdict_from_the_partys_reply(fake_party, reply, want):
    fake_party.reply = reply
    assert party.report_to(fake_party.address, "m", connect=tcp_connect) == want
    path, ctype, body = fake_party.received[0]
    assert (path, ctype, json.loads(body)) == ("/internal/party-session/v0/ended", "application/json", {"message": "m"})


def test_a_party_that_is_absent_or_too_slow_gets_a_warning_with_the_kind_of_failure_only(caplog):
    gone = listener()
    address = gone.getsockname()
    gone.close()
    with caplog.at_level(logging.WARNING, logger="checkers"):
        assert party.report_to(address, "signed-message-xyz", connect=tcp_connect) == (None, None)
    assert "could not report to the party (" in caplog.text
    assert "signed-message-xyz" not in caplog.text and str(address[1]) not in caplog.text

    slow = FakeParty()
    slow.delay = 1.0
    try:
        assert party.report_to(slow.address, "m", timeout=0.2, connect=tcp_connect) == (None, None)
    finally:
        slow.close()


def test_the_unix_connection_says_so_where_there_are_no_unix_sockets():
    if UNIX:
        pytest.skip("this platform has them")
    assert party.report_to("/nowhere.sock", "m") == (None, None)


def test_listen_fds_follows_systemds_rule():
    me = os.getpid()
    assert party.listen_fds({"LISTEN_PID": str(me), "LISTEN_FDS": "1"}) == [3]
    assert party.listen_fds({"LISTEN_PID": str(me), "LISTEN_FDS": "2"}) == [3, 4]
    assert party.listen_fds({"LISTEN_PID": str(me + 1), "LISTEN_FDS": "1"}) == []
    assert party.listen_fds({"LISTEN_PID": "7", "LISTEN_FDS": "1"}, pid=7) == [3]
    for environ in ({}, {"LISTEN_PID": str(me)}, {"LISTEN_FDS": "1"}, {"LISTEN_PID": "x", "LISTEN_FDS": "1"},
                    {"LISTEN_PID": str(me), "LISTEN_FDS": "many"}, {"LISTEN_PID": str(me), "LISTEN_FDS": "0"}):
        assert party.listen_fds(environ) == [], environ


def test_origins_are_origins_and_nothing_else():
    for good in ("https://party.example", "http://party.example:8183", "https://a.b-c.example", "http://10.0.0.1:80"):
        assert party.valid_origin(good) == good
    for bad in (None, 5, "", "party.example", "https://party.example/", "https://party.example/p", "https://party.example?x=1",
                "https://user@party.example", "javascript:alert(1)", "ftp://party.example", "*", "https://a https://b",
                "https://party.example\n", "https://-x.example", "http://x:123456"):
        assert party.valid_origin(bad) is None, bad


def test_a_missing_or_unusable_key_is_refused_without_saying_what_it_held(tmp_path):
    with pytest.raises(OSError):
        party.read_key(str(tmp_path))
    (tmp_path / "checkers.key").write_text("secret-not-a-key\n", encoding="ascii")
    with pytest.raises(ValueError) as caught:
        party.read_key(str(tmp_path))
    assert "secret-not-a-key" not in str(caught.value)                           # it names the file, not what is in it
    protocol_key = protocol.new_key()
    (tmp_path / "checkers.key").unlink()
    protocol.write_key(str(tmp_path / "checkers.key"), protocol_key)
    assert party.read_key(str(tmp_path)) == protocol_key


def test_make_server_takes_only_the_socket_it_was_handed(fake_party):
    app = Rig().app
    sock = listener()
    try:
        with pytest.raises(SystemExit):                            # a TCP socket is not what the unit hands over
            party.make_server(sock, app)
    finally:
        sock.close()
    sock = listener()                                              # a file descriptor number is taken as it is
    httpd = party.make_server(sock.detach(), app, families=(socket.AF_INET,))
    try:
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        port = httpd.socket.getsockname()[1]
        conn = NoDelayConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", BASE + "/api/party")
        assert conn.getresponse().status == 200
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_server_makes_no_socket_of_another_family_than_the_one_it_was_handed(monkeypatch):
    """The unit may create AF_UNIX sockets and nothing else: building the server must not so much as
    try another family (the standard server class makes a socket of its own while it is built)."""
    tmp = None
    if UNIX:
        tmp = tempfile.mkdtemp(prefix="avr", dir="/tmp")
        sock, families = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM), None
        sock.bind(os.path.join(tmp, "s.sock"))
    else:
        try:                                                        # a family other than the default one
            sock, families = socket.socket(socket.AF_INET6, socket.SOCK_STREAM), (socket.AF_INET6,)
            sock.bind(("::1", 0))
        except OSError:
            pytest.skip("this machine has neither Unix sockets nor an IPv6 loopback")
    sock.listen(4)
    made, real = [], socket.socket

    class Recorder(real):
        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
            super().__init__(family, type, proto, fileno)
            made.append(self.family)
    monkeypatch.setattr(socket, "socket", Recorder)
    try:
        httpd = party.make_server(sock, Rig().app, families=families)
        assert made and set(made) == {sock.family}
        assert type(httpd).address_family == sock.family and httpd.socket is sock
        httpd.server_close()
    finally:
        monkeypatch.undo()
        sock.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def test_a_socket_that_is_not_a_listening_stream_is_refused():
    app = Rig().app
    idle = socket.socket(socket.AF_INET, socket.SOCK_STREAM)                       # never listened on
    datagrams = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for sock in (idle, datagrams):
            with pytest.raises(SystemExit):
                party.make_server(sock, app, families=(socket.AF_INET,))
    finally:
        idle.close()
        datagrams.close()


def test_a_request_that_ends_badly_leaves_one_line_with_the_kind_of_failure_only(caplog):
    httpd = party.make_server(listener().detach(), Rig().app, families=(socket.AF_INET,))
    try:
        with caplog.at_level(logging.WARNING, logger="checkers"):
            try:
                raise ConnectionResetError("GET /games/checkers/x?token=avr-123 from 10.0.0.9")
            except ConnectionResetError:
                httpd.handle_error(None, ("10.0.0.9", 1234))
        assert [r.getMessage() for r in caplog.records] == ["a request ended badly (ConnectionResetError)"]
        assert "avr-123" not in caplog.text and "10.0.0.9" not in caplog.text and "Traceback" not in caplog.text
    finally:
        httpd.server_close()


def run_main(environ, fake, monkeypatch):
    """`server.main(environ)` the way the unit runs it, except that fd 3 is a loopback TCP socket and
    the Party's socket is `fake`. Returns (the Live-like handles, the thread running main)."""
    made = {}
    real = party.make_server

    def make_server(fd, app, families=None):
        assert fd == 3
        made["app"], made["sock"] = app, listener()
        made["httpd"] = real(made["sock"], app, families=(socket.AF_INET,))
        made["port"] = made["sock"].getsockname()[1]
        return made["httpd"]
    monkeypatch.setattr(party, "make_server", make_server)
    monkeypatch.setattr(party, "listen_fds", lambda environ=os.environ, pid=None: [3])
    monkeypatch.setattr(party, "UnixHTTPConnection", lambda path, timeout: tcp_connect(fake.address, timeout))
    result = {}
    thread = threading.Thread(target=lambda: result.update(code=server.main(environ)), daemon=True)
    thread.start()
    wait_until(lambda: "httpd" in made, what="main to start serving")
    return made, thread, result


def test_main_wires_the_key_the_origin_and_the_report_to_the_party(tmp_path, monkeypatch, fake_party):
    key = protocol.new_key()
    protocol.write_key(str(tmp_path / "checkers.key"), key)
    environ = {"AVRANA_PARTY_KEYS": str(tmp_path), "AVRANA_PARTY_SOCKET": "/run/avrana/party/internal.sock",
               "AVRANA_PARTY_ORIGIN": ORIGIN}
    made, thread, result = run_main(environ, fake_party, monkeypatch)
    try:
        client = Client(made["port"], key)
        assert client.call("GET", BASE + "/api/party") == (200, {"partyOrigin": ORIGIN})
        assert client.launch() == (200, {"ok": True})
        ana, ben = client.seat(ANA), client.seat(BEN)
        assert (ana["view"]["seat"], ben["view"]["seat"]) == ("w", "b")
        assert client.post("resign", token=ben["token"])[0] == 200
        wait_until(lambda: fake_party.received, what="the report to reach the party")
        assert standings(opened(key, fake_party.messages()[0])[1]) == {ANA: "won", BEN: "lost"}
    finally:
        made["httpd"].shutdown()
        thread.join(5)
        made["httpd"].server_close()
    assert result["code"] == 0


@pytest.mark.parametrize("origin,told", ((ORIGIN, ORIGIN), ("javascript:alert(1)", None), (None, None)))
def test_main_tells_the_page_only_a_well_formed_origin(tmp_path, monkeypatch, fake_party, origin, told):
    protocol.write_key(str(tmp_path / "checkers.key"), protocol.new_key())
    environ = {"AVRANA_PARTY_KEYS": str(tmp_path), "AVRANA_PARTY_SOCKET": "x"}
    if origin is not None:
        environ["AVRANA_PARTY_ORIGIN"] = origin
    made, thread, result = run_main(environ, fake_party, monkeypatch)
    try:
        assert made["app"].party_origin == told
    finally:
        made["httpd"].shutdown()
        thread.join(5)
        made["httpd"].server_close()


def test_main_refuses_to_start_without_what_the_unit_provides(tmp_path, monkeypatch, caplog):
    protocol.write_key(str(tmp_path / "checkers.key"), protocol.new_key())
    good = {"AVRANA_PARTY_KEYS": str(tmp_path), "AVRANA_PARTY_SOCKET": "x"}
    served = []
    monkeypatch.setattr(party, "make_server", lambda *a, **k: served.append(a))
    monkeypatch.setattr(party, "listen_fds", lambda environ=os.environ, pid=None: [3])
    assert server.main(dict(good, AVRANA_PARTY_KEYS="")) == 2
    assert server.main({"AVRANA_PARTY_KEYS": str(tmp_path)}) == 2                    # no party socket
    assert server.main({"AVRANA_PARTY_SOCKET": "x"}) == 2                            # no keys directory
    assert server.main(dict(good, AVRANA_PARTY_KEYS=str(tmp_path / "missing"))) == 2   # no key file
    (tmp_path / "checkers.key").write_text("not-a-key-at-all-" + "f" * 40 + "\n", encoding="ascii")
    with caplog.at_level(logging.INFO, logger="checkers"):
        assert server.main(good) == 2                                                # a key that is not one
    assert "not-a-key-at-all" not in caplog.text
    monkeypatch.setattr(party, "listen_fds", lambda environ=os.environ, pid=None: [])
    assert server.main(good) == 2                                                    # no inherited socket
    monkeypatch.setattr(party, "listen_fds", lambda environ=os.environ, pid=None: [3, 4])
    assert server.main(good) == 2                                                    # more than one
    assert served == []


# ======================================================================= the real process (Unix)

def launcher():
    """What socket activation does for a unit: the listening socket is fd 3 and LISTEN_PID names the
    process. Then run the game exactly as `python3 -m checkers` does."""
    return ("import os, runpy, sys\n"
            "os.dup2(int(sys.argv[1]), 3); os.set_inheritable(3, True)\n"
            "os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1')\n"
            "runpy.run_module('checkers', run_name='__main__', alter_sys=True)\n")


class UnixParty:
    """The Party's internal socket for the real process: records every post and answers 'accepted'."""

    def __init__(self, path):
        self.received = []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                length, request = 0, self.rfile.readline().decode("ascii", "replace").split()
                while True:
                    line = self.rfile.readline()
                    if line in (b"\r\n", b""):
                        break
                    if line.lower().startswith(b"content-length:"):
                        length = int(line.split(b":", 1)[1])
                body = self.rfile.read(length)                     # the whole request, then the answer
                outer.received.append((request[1] if len(request) > 1 else "", body))
                reply = b'{"ok": true, "result": "accepted"}'
                self.wfile.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                                 + str(len(reply)).encode() + b"\r\n\r\n" + reply)
        self.httpd = socketserver.ThreadingUnixStreamServer(path, Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.mark.skipif(not UNIX, reason="Unix sockets are not available on this platform (run on Linux CI)")
class TestTheRealProcess:
    @pytest.fixture(autouse=True)
    def process(self):
        self.tmp = tempfile.mkdtemp(prefix="avr", dir="/tmp")                 # short: the socket path limit
        keys = Path(self.tmp) / "keys"
        keys.mkdir()
        self.key = protocol.new_key()
        protocol.write_key(str(keys / "checkers.key"), self.key)
        self.game_socket = str(Path(self.tmp) / "game.sock")
        self.party_socket = str(Path(self.tmp) / "party.sock")
        self.fake = UnixParty(self.party_socket)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.game_socket)
        sock.listen(16)
        env = dict(os.environ, AVRANA_PARTY_KEYS=str(keys), AVRANA_PARTY_SOCKET=self.party_socket,
                   AVRANA_PARTY_ORIGIN=ORIGIN, PYTHONPATH=str(ROOT))
        env.pop("LISTEN_PID", None)
        env.pop("LISTEN_FDS", None)
        self.log = open(Path(self.tmp) / "game.log", "wb")
        self.proc = subprocess.Popen([sys.executable, "-c", launcher(), str(sock.fileno())],
                                     pass_fds=[sock.fileno()], env=env, cwd=str(ROOT), stderr=self.log)
        sock.close()                                                           # the game holds it now
        yield
        died = self.proc.poll() is not None                                    # it should still be serving
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()
        self.fake.close()
        if died:
            print((Path(self.tmp) / "game.log").read_text(encoding="utf-8", errors="replace"))   # why, if this test failed
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method, path, body=None, headers=None):
        conn = party.UnixHTTPConnection(self.game_socket, 10)
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=dict(headers, Host="localhost"))
            reply = conn.getresponse()
            raw = reply.read()
            return reply.status, (json.loads(raw) if raw[:1] == b"{" else raw), {k.lower(): v for k, v in reply.getheaders()}
        finally:
            conn.close()

    def post(self, route, **body):
        status, answer, _ = self.request("POST", f"{BASE}/api/{route}", body)
        return status, answer

    def ticket(self, pid, role="player"):
        return protocol.mint_ticket(self.key, GAME, SID, pid, role)

    def test_launch_play_resign_and_the_party_is_told_over_its_unix_socket(self):
        message = protocol.launch_message(self.key, GAME, SID, ROSTER)
        assert self.request("POST", party.LAUNCH, {"message": message}, {"X-Forwarded-For": "10.42.0.23"})[0] == 404
        assert self.request("POST", party.LAUNCH, {"message": message})[:2] == (200, {"ok": True})
        status, page, headers = self.request("GET", server.PAGE, headers={"X-Forwarded-For": "10.42.0.2"})
        assert status == 200 and b"<title>" in page and f"frame-src {ORIGIN};" in headers["content-security-policy"]
        assert self.request("GET", BASE + "/api/party")[:2] == (200, {"partyOrigin": ORIGIN})
        ticket = self.ticket(ANA)
        status, ana = self.post("redeem", ticket=ticket)
        assert (status, ana["role"], ana["view"]["seat"]) == (200, "player", "w")
        assert self.post("redeem", ticket=ticket)[0] == 403                                # single use
        status, ben = self.post("redeem", ticket=self.ticket(BEN))
        assert (status, ben["view"]["seat"], ben["view"]["moves"]) == (200, "b", [])
        status, body = self.post("move", token=ana["token"], v=1, move=ana["view"]["moves"][0])
        assert (status, body["view"]["v"]) == (200, 2)
        status, body = self.post("move", token=ana["token"], v=2, move=[0, 1])
        assert status == 409
        assert self.post("poll", token=ben["token"], since=1)[1]["view"]["moves"]
        again = self.post("redeem", ticket=self.ticket(ANA))[1]                           # a reload
        assert (again["token"], again["view"]["v"]) == (ana["token"], 2)
        assert self.post("resign", token=ben["token"])[0] == 200
        wait_until(lambda: self.fake.received, timeout=10, what="the report on the party's Unix socket")
        path, raw = self.fake.received[0]
        assert path == "/internal/party-session/v0/ended"
        payload, checked = opened(self.key, json.loads(raw)["message"])
        assert standings(checked) == {ANA: "won", BEN: "lost"}
        assert checked["data"] == {"ending": "resigned", "plies": 1}
        assert self.post("redeem", ticket=self.ticket(ANA))[0] == 403                     # the session is closed
        end = protocol.end_message(self.key, GAME, SID)
        assert self.request("POST", party.END, {"message": end})[:2] == (200, {"ok": True})
        assert self.post("poll", token=ana["token"], since=0)[0] == 403
        self.proc.terminate()
        self.proc.wait(10)
        logged = (Path(self.tmp) / "game.log").read_bytes().decode("utf-8", "replace")
        for secret in (ticket, ana["token"], self.key.hex(), json.loads(raw)["message"], ANA, BEN):
            assert secret not in logged

    def test_the_hosts_end_through_the_party_drops_the_match(self):
        message = protocol.launch_message(self.key, GAME, SID, ROSTER)
        assert self.request("POST", party.LAUNCH, {"message": message})[0] == 200
        ana = self.post("redeem", ticket=self.ticket(ANA))[1]
        end = protocol.end_message(self.key, GAME, SID)
        assert self.request("POST", party.END, {"message": end})[:2] == (200, {"ok": True})
        assert self.post("poll", token=ana["token"], since=0)[0] == 403
        assert self.post("redeem", ticket=self.ticket(BEN))[0] == 403
        assert self.fake.received == []


# ====================================================================================== boundary

CHECKERS = sorted((ROOT / "checkers").glob("*.py"))


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, None
        elif isinstance(node, ast.ImportFrom):
            yield ("." * node.level) + (node.module or ""), [alias.name for alias in node.names]


@pytest.mark.parametrize("path", CHECKERS, ids=lambda p: p.name)
def test_the_package_imports_only_the_standard_library_the_pinned_party_modules_and_itself(path):
    for module, names in imports(path):
        top = module.split(".")[0]
        if top in sys.stdlib_module_names:
            continue
        if module == "core":
            assert set(names) <= {"party_protocol", "party_result"}, (path.name, names)
        elif module in ("checkers", "checkers.party", "checkers.rules", "checkers.session", "checkers.server"):
            continue
        else:
            raise AssertionError(f"{path.name} imports {module}")


@pytest.mark.parametrize("path", CHECKERS, ids=lambda p: p.name)
def test_the_package_opens_no_socket_of_its_own_and_resolves_no_name(path):
    source = path.read_text(encoding="utf-8")
    for word in ("AF_INET", "urllib", "getaddrinfo", "gethostby", "create_connection", ".bind(", ".listen(",
                 "setsockopt", "subprocess", "os.system", "eval(", "exec(", "pickle", "Set-Cookie", "set_cookie"):
        assert word not in source, (path.name, word)


def test_importing_the_server_pulls_in_nothing_but_the_standard_library_and_the_two_vendored_files():
    """The unit runs the system's python3, which has none of this repository's requirements."""
    code = ("import sys; before = set(sys.modules); import checkers.server; "
            "print(sorted(m for m in set(sys.modules) - before "
            "if m.split('.')[0] not in sys.stdlib_module_names and not m.startswith('_')))")
    done = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(ROOT)))
    assert done.returncode == 0, done.stderr
    assert ast.literal_eval(done.stdout.strip()) == [
        "checkers", "checkers.party", "checkers.rules", "checkers.server", "checkers.session",
        "core", "core.party_protocol", "core.party_result"]


def test_the_protocol_modules_are_the_vendored_files_and_nothing_here_forks_them():
    for name in ("party_protocol.py", "party_result.py"):
        assert not (ROOT / "checkers" / name).exists()
    assert party.protocol is protocol and party.result is party_result
