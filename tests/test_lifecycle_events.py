"""Structured lifecycle log lines (core/events.py): a playtest can reconstruct who joined, left,
reconnected and what phase the game was in — and no token ever reaches the log."""
from __future__ import annotations

import asyncio
import json
import logging
import random

from fastapi import WebSocketDisconnect

from core.net import GameBinding
from games.bluff.game import BluffSession

TOKENS = ("tok-alice-0001", "tok-bob-00002")


class FakeWS:
    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def receive_text(self):
        item = await self.inbox.get()
        if item is None:
            raise WebSocketDisconnect()
        return json.dumps(item)

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self):
        pass


def events(caplog):
    out = []
    for r in caplog.records:
        msg = r.getMessage()
        if msg.startswith("EVENT "):
            out.append(json.loads(msg[6:]))
    return out


def test_lifecycle_events_reconstruct_a_session_without_tokens(caplog):
    caplog.set_level(logging.INFO, logger="gamehub.events")

    async def scenario():
        b = GameBinding("bluff", BluffSession(rng=random.Random(1)))
        a1, bws = FakeWS(), FakeWS()
        ta = asyncio.create_task(b.endpoint(a1))
        await a1.inbox.put({"t": "hello", "token": TOKENS[0], "name": "Alice"})
        tb = asyncio.create_task(b.endpoint(bws))
        await bws.inbox.put({"t": "hello", "token": TOKENS[1], "name": "Bob"})
        await asyncio.sleep(0.05)
        await a1.inbox.put({"t": "ready", "ready": True})
        await asyncio.sleep(0.05)
        await bws.inbox.put(None)                      # Bob's phone drops
        await asyncio.sleep(0.05)
        b2 = FakeWS()                                  # ... and comes back with the same token
        tb2 = asyncio.create_task(b.endpoint(b2))
        await b2.inbox.put({"t": "hello", "token": TOKENS[1], "name": "Bob"})
        await asyncio.sleep(0.05)
        for ws in (a1, b2):
            await ws.inbox.put(None)
        await asyncio.gather(ta, tb, tb2)
        for task in (b._timer_task, b._bot_task):
            if task:
                task.cancel()

    asyncio.run(scenario())
    evs = events(caplog)
    kinds = [(e["ev"], e.get("name") or e.get("t")) for e in evs if e["ev"] != "table"]
    assert ("join", "Alice") in kinds and ("join", "Bob") in kinds
    assert ("verb", "ready") in kinds
    assert [e["ev"] for e in evs].count("disconnect") == 3        # Bob, then Alice and Bob at the end
    # LAN Games drops a disconnected player from the LOBBY (only in-game seats are kept), so the
    # same phone coming back to the lobby is a NEW player with a new pid — and the log shows it.
    bobs = [e["pid"] for e in evs if e["ev"] == "join" and e["name"] == "Bob"]
    assert len(bobs) == 2 and bobs[0] != bobs[1]
    dropped = next(e for e in evs if e["ev"] == "disconnect")
    assert (dropped["pid"], dropped["phase"], dropped["sockets"]) == (bobs[0], "lobby", 0)
    assert all(isinstance(e["ts"], float) and e["game"] == "bluff" for e in evs)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert not any(t in text for t in TOKENS)                    # tokens never logged
