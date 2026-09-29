"""AVR-129: BLUFF in a Party round. The Party ran the pregame (who plays, who watches) and its
Party Host started the round, so the launch roster's players are seated at once and BLUFF's own
ready/start lobby is skipped. Party spectators see every hand; players and anonymous watchers
(a TV, a browser token) never do.

Real core.net binding and BluffSession with fake sockets (tests/test_party_session.py helpers).
"""
import asyncio
import time

import pytest

import core.session as session_mod
from core import party_protocol as proto
from test_party_session import (ALICE, BOB, CAROL, KEY, SID, binding, connect, launch, run,
                                settle, shutdown, ticket)

A, B = proto.game_token(KEY, SID, ALICE), proto.game_token(KEY, SID, BOB)
ROSTER = ((ALICE, "Alice", "player"), (BOB, "Bob", "player"), (CAROL, "Carol", "spectator"))


async def until(pred, limit=6.0):
    t = 0.0
    while not pred():
        assert t < limit, "never happened"
        await asyncio.sleep(0.05)
        t += 0.05


def states(ws):
    return [m for m in ws.sent if m.get("type") == "state"]


def games(ws):
    return [m["game"] for m in states(ws) if m.get("game")]


def test_the_roster_is_the_table_and_the_round_starts_when_the_phones_are_here():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=ROSTER))
        assert b.session.phase == "countdown" and b.session.participants == [A, B]
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        # both phones are here: the arrival wait shortens to the usual 3-2-1
        assert b.session.deadline - time.time() <= session_mod.COUNTDOWN_SECONDS + 0.5
        await until(lambda: b.session.phase == "playing", limit=5)
        g = b.session.g
        assert g["seats"] == [A, B]                                          # no bots, no Carol
        assert not any(p.is_bot for p in b.session.players.values())
        await shutdown(b, a, c)
    run(scenario())


def test_the_games_own_lobby_verbs_are_refused_in_a_party_round():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=ROSTER))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        for msg in ({"t": "ready", "ready": False}, {"t": "start"},
                    {"t": "settings", "patch": {"bots": 3}}):
            await a[0].inbox.put(msg)
        await settle()
        invalid = [m for m in a[0].sent if m.get("type") == "fx" and m.get("kind") == "invalid"]
        assert len(invalid) == 2 and all("Party Host" in m["msg"] for m in invalid)
        assert b.session.phase == "countdown" and b.session.settings == {"bots": 0}
        assert b.session.players[A].ready                                    # still seated
        await shutdown(b, a)
    run(scenario())


def test_a_seat_whose_phone_never_arrives_starts_away(monkeypatch):
    monkeypatch.setattr(session_mod, "PARTY_ARRIVAL_SECONDS", 0.4)

    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=ROSTER))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await until(lambda: b.session.phase == "playing", limit=3)
        assert b.session.g["seats"] == [A, B]
        assert B in b.session.g["away_since"] and A not in b.session.g["away_since"]
        late = await connect(b, {"t": "hello", "ticket": ticket(BOB)})          # Bob arrives
        await settle()
        assert B not in b.session.g["away_since"] and b.session.players[B].connected
        await shutdown(b, a, late)
    run(scenario())


def test_a_phone_that_drops_before_the_start_keeps_its_seat():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=ROSTER))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await a[0].close()
        await a[1]
        await settle()
        assert b.session.phase == "countdown" and A in b.session.players
        assert b.session.participants == [A, B]
    run(scenario())


def test_spectators_see_every_hand_players_and_screens_never_do():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=ROSTER))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        s = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        tv = await connect(b, {"t": "hello", "watch": True})
        eve = await connect(b, {"t": "hello", "token": "tok-browser-eve1", "name": "Eve"})
        await until(lambda: b.session.phase == "playing", limit=5)
        await settle()
        hands = b.session.g["hand"]
        # the spectator: every seat's cards, marked omniscient; no seat of its own
        sg = games(s[0])[-1]
        assert sg["omniscient"] is True and sg["me"] is None
        assert [x["cards"] for x in sg["seats"]] == [hands[A], hands[B]]
        assert s[0].welcome() == {"type": "welcome", "watch": True, "spectator": True}
        # players: their own cards only, in every frame they ever got
        for ws, mine, other in ((a[0], A, B), (c[0], B, A)):
            for g in games(ws):
                assert all("cards" not in x for x in g["seats"])
                assert "omniscient" not in g and "exchange_draw" not in g
                assert g["me"]["cards"] == hands[mine]
            assert all("spectator" not in st for st in states(ws))
        # screens and browser tokens: the public view, no cards at all
        for ws in (tv[0], eve[0]):
            for g in games(ws):
                assert g["me"] is None and all("cards" not in x for x in g["seats"])
                assert "omniscient" not in g
        # a spectator cannot act at the table
        before = b.session.seq
        await s[0].inbox.put({"t": "income", "step": b.session.g["step"]})
        await settle()
        assert b.session.seq == before
        await shutdown(b, a, c, s, tv, eve)
    run(scenario())


def test_the_omniscient_view_is_only_ever_built_for_spectator_sockets(monkeypatch):
    """Belt and braces: count who asks for the spectator view."""
    calls = []

    async def scenario():
        b = binding()
        real = type(b.session).game_state_spectator

        def spy(self):
            calls.append(self)
            return real(self)
        monkeypatch.setattr(type(b.session), "game_state_spectator", spy)
        await b.party_launch(launch(b, entries=ROSTER[:2]))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        tv = await connect(b, {"t": "hello", "watch": True})
        await until(lambda: b.session.phase == "playing", limit=5)
        await settle()
        assert calls == []                                   # no spectator: never built
        await shutdown(b, a, c, tv)
    run(scenario())


def test_standalone_bluff_keeps_its_own_lobby():
    async def scenario():
        b = binding(party=False)
        z = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        await z[0].inbox.put({"t": "ready", "ready": True})
        await settle()
        assert b.session.players["tok-standalone-1"].ready and not b.session.party_round
        assert b.session.phase == "lobby"
        await shutdown(b, z)
    run(scenario())
