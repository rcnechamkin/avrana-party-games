"""Protocol-level check of BLUFF against a RUNNING, fresh instance (not a pytest).

    .venv/bin/python tests/ws_check_bluff.py ws://127.0.0.1:8196

Two real WebSocket clients play a whole game: a Tax claim that gets challenged,
then Income/Coup until someone wins. EVERY frame each client receives is checked
against a whitelist of the payload shape: seats may carry only public fields, and
hidden-card lists may appear only in the viewer's own `me` block. (Substring checks
are unsound here: role names also appear in public log lines and revealed cards.)
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys

import websockets

URL = (sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8196") + "/games/bluff/ws"
SEAT_KEYS = {"pid", "name", "bot", "coins", "influence", "revealed", "alive", "turn", "presence"}
GAME_KEYS = {"kind", "roles", "seats", "deck_count", "pending", "paused", "takeover_at", "log", "winner", "me"}
PENDING_KEYS = {"stage", "step", "actor", "action", "label", "target", "claim_role", "blocker",
                "block_role", "loser", "waiting"}
ME_KEYS = {"pid", "cards", "actions", "prompt", "left"}


class Client:
    def __init__(self, name):
        self.name, self.token = name, "t" + secrets.token_hex(12)
        self.frames, self.state, self.pid = [], None, None

    async def open(self):
        self.ws = await websockets.connect(URL, max_size=2**22)
        await self.ws.send(json.dumps({"t": "hello", "token": self.token, "name": self.name}))
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            m = json.loads(raw)
            self.frames.append(m)
            if m.get("type") == "welcome":
                self.pid = m.get("pid")
            if m.get("type") == "state":
                self.state = m

    async def send(self, **msg):
        await self.ws.send(json.dumps(msg))
        await asyncio.sleep(0.12)

    def g(self):
        return (self.state or {}).get("game") or {}


def check_frame(m, viewer_pid):
    if m.get("type") != "state" or not m.get("game"):
        return
    g = m["game"]
    assert set(g) <= GAME_KEYS, set(g) - GAME_KEYS
    assert set(g["pending"]) <= PENDING_KEYS
    for s in g["seats"]:
        assert set(s) == SEAT_KEYS, "seat carries non-public keys: %r" % (set(s) - SEAT_KEYS)
        assert isinstance(s["influence"], int)
    me = g["me"]
    if me is not None:
        assert set(me) == ME_KEYS and me["pid"] == viewer_pid, "me block is not the viewer's"
        pr = me["prompt"]
        if pr and pr.get("kind") == "exchange":
            assert g["pending"]["actor"] == viewer_pid


async def until(pred, what, timeout=15):
    for _ in range(int(timeout / 0.05)):
        if pred():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out: " + what)


async def main():
    a, b = Client("Alice"), Client("Bob")
    await a.open(); await b.open()
    await until(lambda: a.state and b.state and a.pid and b.pid, "welcome")
    assert a.state["phase"] == "lobby", "needs a fresh server in the lobby"
    await a.send(t="ready", ready=True); await b.send(t="ready", ready=True)
    await a.send(t="start")
    await until(lambda: a.g().get("seats") and b.g().get("seats"), "game start")
    assert len(a.g()["me"]["cards"]) == 2 and len(b.g()["me"]["cards"]) == 2
    print("joined: each client holds exactly its own 2 cards")

    clients = {a.pid: a, b.pid: b}
    challenged = False
    for _ in range(400):
        g = a.g()
        if g["pending"]["stage"] == "over" or g.get("winner"):
            break
        p = g["pending"]
        if p["stage"] == "turn":
            c = clients[p["actor"]]
            other = next(x for x in clients if x != c.pid)
            acts = {x["action"] for x in c.g()["me"]["actions"]}
            if not challenged and "tax" in acts:
                await c.send(t="act", action="tax")          # a claim, true or a bluff
            elif "coup" in acts:
                await c.send(t="act", action="coup", target=other)
            else:
                await c.send(t="act", action="income")
        else:
            for c in clients.values():
                pr = (c.g().get("me") or {}).get("prompt")
                if not pr:
                    continue
                if pr["kind"] == "challenge":
                    await c.send(t="respond", choice="pass" if challenged else "challenge")
                    challenged = True
                elif pr["kind"] == "block":
                    await c.send(t="respond", choice="allow")
                elif pr["kind"] == "lose":
                    await c.send(t="lose", card=0)
                elif pr["kind"] == "exchange":
                    await c.send(t="keep", cards=list(range(pr["keep"])))
        await asyncio.sleep(0.05)
    await until(lambda: a.g().get("winner") and b.g().get("winner"), "winner", 20)
    assert a.g()["winner"] == b.g()["winner"]
    pub = lambda c: [(s["pid"], s["coins"], s["influence"], s["revealed"]) for s in c.g()["seats"]]
    assert pub(a) == pub(b)
    print("game over: both clients agree on the winner and the public table")
    assert challenged, "the challenge path was not exercised"

    n = 0
    for c in (a, b):
        for m in c.frames:
            check_frame(m, c.pid)
            n += 1
    print("checked %d frames: no seat or payload ever carried another player's cards" % n)
    for c in (a, b):
        c.reader.cancel()
        await c.ws.close()
    print("ALL PROTOCOL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
