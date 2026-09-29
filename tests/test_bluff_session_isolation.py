"""BLUFF state never crosses Avrana party sessions (AVR-25).

The authoritative BLUFF room belongs to one party session at a time. A new session never inherits
the last one's hands, seats, influence, coins, turn, pending step, log, settings, bots or player
mappings; a connection only ever acts on the room it joined, so a message from an old session's
socket, even one already read when the room was replaced, is dropped, never dispatched; old
credentials (a still-live ticket, a game token sent as a browser token) never reach a newer
session; and a restarted server holds nothing of the session it lost.

Harness: the fake-WebSocket rooms of test_party_session.py and test_party_session_end.py, with the
real BLUFF rules. Reconnect within one session (AVR-23) is test_bluff_party_reconnect.py; here it
is checked again in the second of two back-to-back sessions.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core import party_protocol as proto
from core.net import GameBinding
from games.bluff import game as bluff
from games.bluff.game import BluffSession
from test_party_session import ALICE, BOB, KEY, SID, SID2, connect, launch, run, settle, shutdown, \
    ticket
from test_party_session_end import (binding, fast, fxs, party, party_game, playing,  # noqa: F401
                                    report_of, reports, win_for_alice)

A_ALICE, A_BOB = proto.game_token(KEY, SID, ALICE), proto.game_token(KEY, SID, BOB)
B_ALICE, B_BOB = proto.game_token(KEY, SID2, ALICE), proto.game_token(KEY, SID2, BOB)
# the same two people in the next session, under other party names: anything of session A that
# reached session B would show up as "Alice" or "Bob"
B_ROSTER = ((ALICE, "Ann", "player"), (BOB, "Ben", "player"))


def frames(ws, start=0):
    return ws.sent[start:]


def mentions(ws, text, start=0):
    return any(text in json.dumps(m) for m in frames(ws, start))


def assert_fresh(b, room_before):
    """The room is a new, empty, non-running session object: nothing of the old one remains."""
    s = b.session
    assert s is not room_before
    assert s.phase == "lobby" and s.players == {} and s.participants == []
    assert s.g is None and s.deadline is None
    assert s.settings == BluffSession.DEFAULT_SETTINGS
    assert b.player_sockets == {}


def assert_fresh_table(room, seats):
    """BLUFF just started in `room` with exactly these seats and nothing carried in."""
    g = room.g
    assert g["seats"] == seats
    assert set(g["hand"]) == set(g["revealed"]) == set(g["coins"]) == set(seats)
    assert all(len(g["hand"][t]) == 2 and g["revealed"][t] == [] for t in seats)
    assert all(g["coins"][t] == bluff.START_COINS for t in seats)
    assert g["turn"] == 0 and g["winner"] is None and g["left"] == set()
    assert g["away_since"] == {} and g["paused"] is None and g["exchange_draw"] is None
    assert g["log"][0].startswith("Game on")
    assert not any(p.is_bot for p in room.players.values())


async def second_session(b):
    """Session B: the same two participants, fresh tickets, BLUFF playing."""
    await b.party_launch(launch(b, sid=SID2, entries=B_ROSTER))
    return await playing(b, {"t": "hello", "ticket": ticket(ALICE, sid=SID2)},
                         {"t": "hello", "ticket": ticket(BOB, sid=SID2)})


# ---- back-to-back sessions ------------------------------------------------------------------

def test_session_a_completed_then_session_b_starts_with_nothing_of_a(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        room_a = b.session
        await win_for_alice(a, c)
        # the results screen: a rematch from inside BLUFF is refused (one play-through per session)
        for msg in ({"t": "again"}, {"t": "ready", "ready": True}, {"t": "start"}):
            await a[0].inbox.put(msg)
        await settle()
        assert b.session is room_a and b.session.phase == "game_end"
        await asyncio.sleep(0.9)                         # results screen over -> released
        assert_fresh(b, room_a)
        assert b.party_room_sid is None and b.party_roster == {}
        seen = (len(a[0].sent), len(c[0].sent))

        a2, c2 = await second_session(b)
        room_b = b.session
        assert_fresh_table(room_b, [B_ALICE, B_BOB])
        assert set(room_b.players) == {B_ALICE, B_BOB}
        assert set(b.party_roster) == {B_ALICE, B_BOB} and set(b.player_sockets) == {B_ALICE, B_BOB}
        assert not {A_ALICE, A_BOB} & (set(room_b.players) | set(b.party_roster))
        assert sorted(p.name for p in room_b.humans()) == ["Ann", "Ben"]
        # what the new session's phones get: their own view, nothing of session A
        for ws, me in ((a2[0], B_ALICE), (c2[0], B_BOB)):
            st = ws.last_state()
            assert st["game"]["me"]["cards"] == room_b.g["hand"][me]
            assert [s["name"] for s in st["game"]["seats"]] == ["Ann", "Ben"]
            assert not mentions(ws, "Alice") and not mentions(ws, "Bob")
            assert not any("wins" in line for line in st["game"]["log"])
        # what the old session's phones get: nothing after their room was released
        assert (len(a[0].sent), len(c[0].sent)) == seen
        assert a[0].closed and c[0].closed

        # reconnect within session B still returns the same seat and hand (AVR-23)
        pid, hand = a2[0].welcome()["pid"], list(room_b.g["hand"][B_ALICE])
        await a2[0].close()
        await a2[1]
        await settle()
        again = await connect(b, {"t": "hello", "ticket": ticket(ALICE, sid=SID2)})
        assert again[0].welcome() == {"type": "welcome", "pid": pid}
        assert again[0].last_state()["game"]["me"]["cards"] == hand
        assert b.session is room_b and room_b.g["seats"] == [B_ALICE, B_BOB]

        await win_for_alice(again, c2)
        await reports(b)
        assert [(report_of(m)["sid"], report_of(m)["outcome"]) for _, m, _ in posts] == \
            [(SID, "completed"), (SID2, "completed")]
        await shutdown(b, a, c, again, c2)
    run(scenario())


def test_session_a_abandoned_then_session_b_starts_with_nothing_of_a(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        await a[0].inbox.put({"t": "settings", "patch": {"bots": 2}})   # session A's own setting
        for ws, _ in (a, c):
            await ws.inbox.put({"t": "ready", "ready": True})
        await settle()
        await a[0].inbox.put({"t": "start"})
        for _ in range(50):
            await settle()
            if b.session.phase == "playing":
                break
        room_a = b.session
        assert room_a.phase == "playing" and len(room_a.g["seats"]) == 4     # two test bots
        await c[0].close()                               # Bob's phone is gone
        await c[1]
        await settle()
        await a[0].inbox.put({"t": "end_game"})          # Alice is the last one here: abandoned
        await reports(b)
        assert [report_of(m)["outcome"] for _, m, _ in posts] == ["abandoned"]
        assert_fresh(b, room_a)
        assert b.party_room_sid is None and a[0].closed

        a2, c2 = await second_session(b)
        room_b = b.session
        assert room_b.settings == {"bots": 0}            # A's two bots did not come along
        assert_fresh_table(room_b, [B_ALICE, B_BOB])
        for ws in (a2[0], c2[0]):
            assert not mentions(ws, "Test bot") and not mentions(ws, "Alice")
            assert not mentions(ws, "Game ended by")
        await shutdown(b, a, c, a2, c2)
    run(scenario())


def test_a_launch_mid_game_replaces_the_table_and_no_old_timer_or_bot_fires_into_it(party,
                                                                                  monkeypatch):
    """No end, no report: e.g. the party restarted and launched again while BLUFF was playing.
    Session A's turn timer and bot were due within the wait; neither touches session B's room."""
    monkeypatch.setattr(bluff, "TURN_SECONDS", 0.3)
    monkeypatch.setattr(bluff, "RESPONSE_SECONDS", 0.3)
    monkeypatch.setattr(bluff, "BOT_DELAY", 0.2)

    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b, entries=((ALICE, "Alice", "player"),)))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await a[0].inbox.put({"t": "settings", "patch": {"bots": 1}})
        await a[0].inbox.put({"t": "ready", "ready": True})
        await settle()
        await a[0].inbox.put({"t": "start"})
        for _ in range(50):
            await settle()
            if b.session.phase == "playing":
                break
        room_a = b.session
        assert room_a.phase == "playing" and room_a.deadline is not None
        await b.party_launch(launch(b, sid=SID2, entries=B_ROSTER))
        room_b = b.session
        assert_fresh(b, room_a)
        marks = (room_b.seq, room_b.gen, room_b.phase)
        a_marks = (room_a.seq, room_a.gen, len(room_a.g["log"]))
        await asyncio.sleep(0.8)                         # past A's turn deadline and bot delay
        assert (room_b.seq, room_b.gen, room_b.phase) == marks
        assert (room_a.seq, room_a.gen, len(room_a.g["log"])) == a_marks   # A is inert too
        assert b._timer_task is None and b._bot_task is None
        assert a[0].closed and not mentions(a[0], "Ann")
        await shutdown(b, a)
    run(scenario())


# ---- old-session clients ----------------------------------------------------------------------

@pytest.mark.parametrize("replace", ["launch", "end"])
def test_a_message_in_flight_on_an_old_socket_is_dropped_not_dispatched(party, monkeypatch, replace):
    """Alice's phone sent a message that the server had already read when the party replaced the
    room (a new launch) or released it (End for everyone): it was waiting for the room's lock.
    It must be dropped, never dispatched into the next room, and her socket's close must not
    touch that room either."""
    seen = []
    dispatch, leave = GameBinding.dispatch, BluffSession.leave

    def spy_dispatch(self, token, msg):
        seen.append((self.session, token, msg.get("t")))
        return dispatch(self, token, msg)

    def spy_leave(self, token):
        seen.append((self, token, "leave"))
        return leave(self, token)
    monkeypatch.setattr(GameBinding, "dispatch", spy_dispatch)
    monkeypatch.setattr(BluffSession, "leave", spy_leave)

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        room_a = b.session
        await b.lock.acquire()                           # the room is busy (a push, a bot, ...)
        if replace == "launch":
            task = asyncio.create_task(b.party_launch(launch(b, sid=SID2, entries=B_ROSTER)))
        else:
            task = asyncio.create_task(b.party_end(proto.end_message(KEY, "bluff", SID)))
        await settle()                                   # queued on the lock first
        await a[0].inbox.put({"t": "ready", "ready": True})   # read now, queued on the lock second
        await settle()
        b.lock.release()
        await task
        await settle()
        room_next = b.session
        assert room_next is not room_a
        assert [x for x in seen if x[0] is room_next] == []
        assert a[0].closed and not mentions(a[0], "Ann")
        if replace == "launch":                          # session B is untouched and playable
            a2, c2 = await playing(b, {"t": "hello", "ticket": ticket(ALICE, sid=SID2)},
                                   {"t": "hello", "ticket": ticket(BOB, sid=SID2)})
            assert set(b.session.players) == {B_ALICE, B_BOB}
            await shutdown(b, a2, c2)
        await shutdown(b, a, c)
    run(scenario())


def test_old_credentials_never_reach_a_newer_session(party):
    async def scenario():
        b = binding(party)
        first = launch(b)
        await b.party_launch(first)
        a, c = await playing(b, {"t": "hello", "ticket": ticket(ALICE)},
                             {"t": "hello", "ticket": ticket(BOB)})
        old_ticket = ticket(ALICE)                       # fetched in session A, still unexpired
        await b.party_launch(launch(b, sid=SID2, entries=B_ROSTER))
        room_b = b.session
        # the remembered session-A ticket: refused and told, never seated
        ws, task = await connect(b, {"t": "hello", "ticket": old_ticket})
        await task
        assert ws.closed and ws.welcome() is None and fxs(ws, "invalid")
        # session A's game token sent as a browser token: only watches session B
        w = await connect(b, {"t": "hello", "token": A_ALICE, "name": "Alice"})
        assert w[0].welcome() == {"type": "welcome", "watch": True}
        await w[0].inbox.put({"t": "ready", "ready": True})
        await settle()
        assert room_b.players == {} and b.player_sockets == {}
        # session A's launch replayed, and session A's End: refused, session B untouched
        with pytest.raises(proto.Invalid):
            await b.party_launch(first)
        with pytest.raises(proto.Invalid):
            await b.party_end(proto.end_message(KEY, "bluff", SID))
        assert b.session is room_b and b.party.sid == SID2 and b.party_room_sid == SID2
        # once session B is over too, session A's game token is only a stranger's browser token
        await b.party_end(proto.end_message(KEY, "bluff", SID2))
        z = await connect(b, {"t": "hello", "token": A_ALICE, "name": "Zed"})
        assert list(b.session.players) == [A_ALICE] and b.session.g is None
        assert z[0].last_state()["players"][0]["name"] == "Zed"
        assert not mentions(z[0], "Alice") and not mentions(z[0], "Bob")
        await shutdown(b, a, c, w, z)
    run(scenario())


# ---- process restart --------------------------------------------------------------------------

def test_after_a_restart_the_lost_session_is_refused_and_nothing_of_it_runs(party):
    """The defined outcome of a games-server restart during a party session: the new process
    holds no party session and a fresh room. Tickets for the lost session are refused (the phone
    is told and never seated), no `ended` is reported for it, and the party's End for it is
    refused here (the party closes its session regardless: Party Core end_confirmed(False)).
    Standalone play works, and the party's next launch starts clean."""
    posts, _, _ = party

    async def scenario():
        old = binding(party)
        a, c = await party_game(old)                     # the process that goes away
        await shutdown(old, a, c)

        b = binding(party)                               # restarted: same key file, no memory
        assert b.party.sid is None and b.party_room_sid is None and b._party_last_sid is None
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and ws.welcome() is None
        assert fxs(ws, "invalid") and not fxs(ws, "party_ended")
        assert b.session.players == {} and b.player_sockets == {}
        with pytest.raises(proto.Invalid):
            await b.party_end(proto.end_message(KEY, "bluff", SID))
        z = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        assert z[0].welcome()["token"] == "tok-standalone-1"
        assert list(b.session.players) == ["tok-standalone-1"] and b.session.g is None

        room = b.session
        a2, c2 = await second_session(b)
        assert b.session is not room and z[0].closed
        assert_fresh_table(b.session, [B_ALICE, B_BOB])
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and ws.welcome() is None
        await reports(b)
        assert posts == []                               # nothing was ever reported for A
        await shutdown(b, z, a2, c2)
    run(scenario())
