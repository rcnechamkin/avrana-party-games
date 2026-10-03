"""EXPO in an Avrana party session (core/party_session.py, ADR 0006 in rcnechamkin/avrana-party).

The game side is shared with BLUFF (core/net.py admits Party tickets and holds the roster); this
file proves it holds for EXPO's own rules: a signed roster seats the crew under Party names, a
dropped crew member returns by a fresh ticket to the same seat and the same private hand, no one
else can see that hand or take the seat, and the game reports how it ended through take_outcome()
with EXPO's vocabulary (a mission that succeeds or fails has *completed*; an ended table is
*abandoned*). Harness: test_party_session.py.
"""
from __future__ import annotations

import asyncio
import json
import random

import pytest

from core import party_protocol as proto
from core import party_session
from core.net import GameBinding
from games.expo.game import ExpoSession

from test_party_session import ALICE, BOB, KEY, SID, FakeWS, connect, roster, run, settle, shutdown

ALICE_TOKEN = proto.game_token(KEY, SID, ALICE)
BOB_TOKEN = proto.game_token(KEY, SID, BOB)


def binding():
    return GameBinding("expo", ExpoSession(rng=random.Random(1)), party=proto.GameSide(KEY, "expo"))


def launch(entries=((ALICE, "Alice", "player"), (BOB, "Bob", "player"))):
    return proto.launch_message(KEY, "expo", SID, roster(*entries))


def ticket(participant, role="player"):
    return proto.mint_ticket(KEY, "expo", SID, participant, role)


async def seated_table():
    """Alice and Bob admitted by ticket, both ready, the two-human mission dealt."""
    b = binding()
    await b.party_launch(launch())
    a = await connect(b, {"t": "hello", "ticket": ticket(ALICE), "name": "Mallory"})
    c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
    for ws, _ in (a, c):
        await ws.inbox.put({"t": "ready", "ready": True})
    await settle()
    await a[0].inbox.put({"t": "start"})
    await asyncio.sleep(3.3)                        # the 3-2-1 countdown
    assert b.session.phase == "allocation"
    assert set(b.session.participants) == {ALICE_TOKEN, BOB_TOKEN}
    return b, a, c


def test_expo_is_a_party_session_game():
    assert "expo" in party_session.GAMES


def test_the_roster_seats_the_crew_under_party_names():
    async def scenario():
        b, a, c = await seated_table()
        assert b.session.players[ALICE_TOKEN].name == "Alice"      # never the hello's "Mallory"
        assert "token" not in a[0].welcome()
        state = a[0].last_state()
        assert state["you"]["name"] == "Alice"
        assert state["game"]["me"]["seat"] == a[0].welcome()["pid"]
        assert len(state["game"]["me"]["hand"]) == 13
        await shutdown(b, a, c)
    run(scenario())


def test_a_dropped_crew_member_returns_by_fresh_ticket_to_the_same_seat_and_hand():
    async def scenario():
        b, a, c = await seated_table()
        pid = a[0].welcome()["pid"]
        hand = list(b.session.engine.s["hands"][pid])
        assert a[0].last_state()["game"]["me"]["hand"] == hand
        await a[0].close()                          # reload, or the phone went to sleep
        await a[1]
        await settle()
        assert pid in b.session.engine.s["away"]    # the table waits; the seat is held
        assert ALICE_TOKEN in b.session.participants
        assert c[0].last_state()["game"]["away"] == [pid]
        again = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        assert again[0].welcome() == {"type": "welcome", "pid": pid}
        back = again[0].last_state()["game"]
        assert back["me"]["seat"] == pid and back["me"]["hand"] == hand
        assert back["away"] == []
        assert len(b.session.humans()) == 2
        await shutdown(b, again, c)
    run(scenario())


def test_nobody_else_sees_or_takes_an_empty_seat():
    async def scenario():
        b, a, c = await seated_table()
        pid = a[0].welcome()["pid"]
        hand = b.session.engine.s["hands"][pid]
        await a[0].close()
        await a[1]
        await settle()
        # Bob's view never carries Alice's cards, held seat or not.
        bob_view = json.dumps(c[0].last_state()["game"])
        assert all(card not in bob_view for card in hand)
        # A browser-minted hello under her name only watches and sees no hand.
        m = await connect(b, {"t": "hello", "name": "Alice"})
        assert m[0].welcome().get("watch")
        assert m[0].last_state()["game"]["me"] is None
        # Her own game token sent as a hello is not a ticket.
        t = await connect(b, {"t": "hello", "token": ALICE_TOKEN})
        assert t[0].welcome().get("watch")
        assert ALICE_TOKEN in b.session.participants and pid in b.session.engine.s["away"]
        await shutdown(b, m, t, c)
    run(scenario())


def test_a_spectator_ticket_watches_the_table_without_a_hand():
    async def scenario():
        b, a, c = await seated_table()
        s = await connect(b, {"t": "hello", "ticket": ticket("participant-" + "c" * 32, "spectator")})
        assert s[0].welcome().get("watch")
        game = s[0].last_state()["game"]
        assert game["me"] is None and game["hand_counts"]
        await shutdown(b, a, c, s)
    run(scenario())


def test_a_party_round_never_inherits_or_writes_a_standalone_snapshot(tmp_path):
    # core/net.py builds a fresh session object for every launch; with EXPO_SNAPSHOT_PATH set that
    # object restores the standalone table. party_start() must drop it and stop persisting.
    path = tmp_path / "expo.json"
    saved, _ = session()
    saved.store = __import__("games.expo.storage", fromlist=["SnapshotStore"]).SnapshotStore(path)
    saved._save()
    before = path.read_bytes()
    room = ExpoSession(random.Random(2), snapshot_path=path)
    assert room.engine is not None                     # the standalone table came back
    room.party_start([(ALICE_TOKEN, "Alice"), (BOB_TOKEN, "Bob")])
    assert room.engine is None and room.store is None and room.recovery_error is None
    assert list(room.players) == [ALICE_TOKEN, BOB_TOKEN] and room.party_round
    room.tick(room.gen)                                # arrival deadline: the round starts
    assert room.phase == "allocation" and set(room.engine.s["humans"]) == {p.pid for p in room.players.values()}
    assert path.read_bytes() == before                 # the standalone save is untouched


# ---- outcome vocabulary (take_outcome(); reported to the party as `ended`) --------------------

def command(e, actor, t, **kwargs):
    return {"t": t, "attempt": e.s["attempt"], "revision": e.s["revision"],
            "request": str(e.s["revision"]) + "-" + actor, **kwargs}


def session(n=3):  # a standalone table
    s = ExpoSession(random.Random(4))
    tokens = [f"human-{i}" for i in range(n)]
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.start(tokens[0])
    s.tick(s.gen)
    assert s.phase == "allocation" and s.take_outcome() is None
    return s, tokens


def decide(s, tokens, kind, **kwargs):
    s.game_action(tokens[0], command(s.engine, s.players[tokens[0]].pid, "propose",
                                     proposal={"kind": kind, **kwargs}))
    for t in tokens[1:]:
        s.game_action(t, command(s.engine, s.players[t].pid, "confirm", yes=True))


def test_ending_the_table_is_abandoned():
    s, tokens = session()
    decide(s, tokens, "end")
    assert s.phase == "game_end" and s.take_outcome() == "abandoned"
    assert s.take_outcome() is None                 # once


@pytest.mark.parametrize("status", ["success", "failed"])
def test_ending_the_table_after_a_decided_mission_is_completed(status):
    # A mission result is not the end of the party session: the crew may retry or sail on, so
    # nothing is reported yet. Ending the table then is a completed game (the mission was decided,
    # won or lost), not an abandoned one; only a table ended mid-mission is abandoned.
    s, tokens = session()
    s.engine._finish(status, "fixture")
    s._sync()
    assert s.phase == "mission_result" and s.take_outcome() is None
    decide(s, tokens, "end")
    assert s.engine.s["result"]["status"] == status
    assert s.phase == "game_end" and s.take_outcome() == "completed"
