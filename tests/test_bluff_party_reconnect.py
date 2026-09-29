"""BLUFF reconnect and private-state restoration in an Avrana party session (AVR-23).

Game side, with the fake-WebSocket harness of test_party_session.py and the real BLUFF rules: a
seated participant who drops (reload, phone asleep) and comes back with a fresh Party ticket gets
the same seat and the same private hand, the table shows them `reconnecting` meanwhile, and
nobody else (another participant, a wc-token hello under their name, their own game token) can
take the seat or see the hand while it is empty. The cross-repository browser run of the same
story is avrana-party tests/provider/party-session.spec.ts.
"""
from __future__ import annotations

import asyncio
import json
import time
import types

from core import party_protocol as proto
from games.bluff import game as bluff_game

from test_party_session import (ALICE, BOB, KEY, SID, binding, connect, launch, run, settle,
                                shutdown, ticket)

ALICE_TOKEN = proto.game_token(KEY, SID, ALICE)
BOB_TOKEN = proto.game_token(KEY, SID, BOB)


async def seated_table():
    """Alice and Bob admitted by ticket, both ready, BLUFF playing."""
    b = binding()
    await b.party_launch(launch(b))
    a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
    c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
    for ws, _ in (a, c):
        await ws.inbox.put({"t": "ready", "ready": True})
    await settle()
    await a[0].inbox.put({"t": "start"})
    await asyncio.sleep(3.3)                        # the 3-2-1 countdown
    assert b.session.phase == "playing"
    assert set(b.session.g["seats"]) == {ALICE_TOKEN, BOB_TOKEN}
    return b, a, c


def seat(state, pid):
    return next(s for s in state["game"]["seats"] if s["pid"] == pid)


def game_states(ws):
    return [m for m in ws.sent if m.get("type") == "state" and m.get("game")]


def test_a_dropped_player_returns_by_fresh_ticket_to_the_same_seat_and_hand():
    async def scenario():
        b, a, c = await seated_table()
        pid = a[0].welcome()["pid"]
        hand = list(b.session.g["hand"][ALICE_TOKEN])
        before = a[0].last_state()["game"]
        assert before["me"]["pid"] == pid and before["me"]["cards"] == hand
        await a[0].close()                          # reload, or the phone went to sleep
        await a[1]
        await settle()
        assert seat(c[0].last_state(), pid)["presence"] == "reconnecting"
        assert ALICE_TOKEN in b.session.g["seats"]  # the seat is held, not freed
        again = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        assert again[0].welcome() == {"type": "welcome", "pid": pid}   # no token to the browser
        back = again[0].last_state()["game"]
        assert back["me"]["pid"] == pid
        assert back["me"]["cards"] == hand
        assert [s["pid"] for s in back["seats"]] == [s["pid"] for s in before["seats"]]
        assert seat(c[0].last_state(), pid)["presence"] == "here"
        assert len(b.session.humans()) == 2
        await shutdown(b, again, c)
    run(scenario())


def test_a_return_inside_the_away_grace_finds_the_hand_untouched_by_autopilot(monkeypatch):
    # BLUFF's supported grace: AWAY_GRACE for prompts, AWAY_TURN_GRACE for one's own turn. A phone
    # that sleeps for most of AWAY_GRACE and wakes is still `reconnecting`, and nothing was played
    # for it. (Beyond the grace, autopilot plays passively; the seat is still held.)
    async def scenario():
        b, a, c = await seated_table()
        pid = a[0].welcome()["pid"]
        hand = list(b.session.g["hand"][ALICE_TOKEN])
        coins = dict(b.session.g["coins"])
        await a[0].close()
        await a[1]
        await settle()
        offset = bluff_game.AWAY_GRACE - 5
        monkeypatch.setattr(bluff_game, "time", types.SimpleNamespace(
            time=lambda: time.time() + offset))
        due = b.session.next_bot_action()            # autopilot is not in charge of Alice yet
        assert due is None or due[0] >= 1
        await c[0].inbox.put({"t": "ping"})
        await settle()
        state = b.session.state_for(BOB_TOKEN)
        assert seat(state, pid)["presence"] == "reconnecting"
        again = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        assert again[0].welcome()["pid"] == pid
        assert again[0].last_state()["game"]["me"]["cards"] == hand
        assert b.session.g["coins"] == coins
        assert seat(c[0].last_state(), pid)["presence"] == "here"
        await shutdown(b, again, c)
    run(scenario())


def test_nobody_else_takes_an_empty_seat_or_sees_its_hand():
    async def scenario():
        b, a, c = await seated_table()
        pa, pb = a[0].welcome()["pid"], c[0].welcome()["pid"]
        hand = list(b.session.g["hand"][ALICE_TOKEN])
        await a[0].close()
        await a[1]
        await settle()
        # Bob's own fresh ticket, on a second socket: Bob, never Alice
        bob2 = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        assert bob2[0].welcome() == {"type": "welcome", "pid": pb}
        # a browser-minted token under Alice's name, and Alice's game token sent as a wc-token:
        # both only watch
        for hello in ({"t": "hello", "token": "alice-wc-token-01", "name": "Alice"},
                      {"t": "hello", "token": ALICE_TOKEN, "name": "Alice"}):
            w = await connect(b, hello)
            assert w[0].welcome() == {"type": "welcome", "watch": True}
            assert w[0].last_state()["game"]["me"] is None
            await w[0].close()
            await w[1]
        # a spectator ticket for Alice's participant id only watches too: as a Party spectator
        # (AVR-129: the intentionally omniscient view), never in Alice's seat
        s = await connect(b, {"t": "hello", "ticket": ticket(ALICE, role="spectator")})
        assert s[0].welcome() == {"type": "welcome", "watch": True, "spectator": True}
        await s[0].close()
        await s[1]
        assert b.session.g["seats"].count(ALICE_TOKEN) == 1
        assert not b.session.players[ALICE_TOKEN].connected
        assert b.session.g["hand"][ALICE_TOKEN] == hand
        # no frame to Bob, or to any watcher, ever carried Alice's private view
        for ws in (c[0], bob2[0]):
            for st in game_states(ws):
                assert st["game"]["me"]["pid"] == pb
                assert all("cards" not in s for s in st["game"]["seats"])
        assert "cards" not in json.dumps(b.session.state_for(None)["game"]["seats"])
        await shutdown(b, bob2, c)
    run(scenario())
