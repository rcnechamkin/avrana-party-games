"""Hostile-client attack run against a RUNNING, FRESH BLUFF instance (not a pytest).

    .venv/bin/python tests/ws_attack_bluff.py ws://127.0.0.1:8199

Two honest players + a watch:true spectator + a mid-game token joiner + an attacker
socket. Fires malformed/oversized/nested/flood/impersonation traffic, then checks:
the server still answers, no attack changed game state, flooding never produced
extra actions, no frame to anyone carried another viewer's cards or any human token.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys

import websockets

sys.path.insert(0, __import__("os").path.dirname(__file__))
from ws_check_bluff import check_frame  # noqa: E402  (shape whitelist)

BASE = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8199"
URL = BASE + "/games/bluff/ws"
results = []


def ok(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("HELD  " if cond else "FAIL  ") + name + (("  -- " + detail) if detail else ""))


class Client:
    def __init__(self, name, token=None, watch=False):
        self.name, self.watch = name, watch
        self.token = token if token is not None else "t" + secrets.token_hex(12)
        self.frames, self.state, self.pid, self.closed = [], None, None, False

    async def open(self, hello=None):
        self.ws = await websockets.connect(URL, max_size=2**24)
        h = hello or ({"t": "hello", "watch": True} if self.watch else
                      {"t": "hello", "token": self.token, "name": self.name})
        await self.ws.send(json.dumps(h) if not isinstance(h, str) else h)
        self.reader = asyncio.create_task(self._read())
        return self

    async def _read(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                self.frames.append(m)
                if m.get("type") == "welcome":
                    self.pid = m.get("pid")
                    if m.get("token"):
                        self.token = m["token"]
                if m.get("type") == "state":
                    self.state = m
        except Exception:
            pass
        self.closed = True

    async def send(self, raw_or_obj, pause=0.1):
        await self.ws.send(raw_or_obj if isinstance(raw_or_obj, (str, bytes)) else json.dumps(raw_or_obj))
        await asyncio.sleep(pause)

    def g(self):
        return (self.state or {}).get("game") or {}


async def until(pred, what, timeout=10):
    for _ in range(int(timeout / 0.05)):
        if pred():
            return True
        await asyncio.sleep(0.05)
    raise AssertionError("timed out: " + what)


def public_table(c):
    g = c.g()
    return json.dumps([g.get("seats"), g.get("pending"), g.get("log"), c.state.get("phase")],
                      sort_keys=True)


async def alive():
    c = await Client("probe", watch=True).open()
    await until(lambda: c.state, "probe state")
    await c.send({"t": "ping"})
    got = any(f.get("type") == "pong" for f in c.frames)
    await c.ws.close()
    return got


async def main():
    a, b = await Client("Alice").open(), await Client("Bob").open()
    spec = await Client("Spec", watch=True).open()
    await until(lambda: a.pid and b.pid and a.state and spec.state, "welcome")
    assert a.state["phase"] == "lobby", "needs a fresh server"

    # --- hello-level attacks
    for tok in ("bot:p1", "short", "x" * 65, "bad token!", 12345):
        c = Client("Evil", token=tok)
        await c.open()
        await until(lambda: c.pid, "welcome for %r" % (tok,))
        ok("hello token %r is replaced by a server-minted one" % (tok,), c.token != tok)
        await c.ws.close()
    for raw in ("not json", "[1,2]", "null", json.dumps({"t": "hello", "name": "x" * 10000}),
                "[" * 3000 + "]" * 3000):
        c = Client("Raw")
        c.ws = await websockets.connect(URL)
        await c.ws.send(raw)
        try:
            reply = await asyncio.wait_for(c.ws.recv(), 2)
        except Exception:
            reply = None
        # a non-object hello must be dropped; an object hello with a long name is OK (name cleaned)
        good = (reply is None) if not raw.startswith('{"t"') else ("welcome" in reply)
        ok("malformed hello %r... handled" % raw[:20], good)
        await c.ws.close()

    await a.send({"t": "ready", "ready": True}); await b.send({"t": "ready", "ready": True})
    await a.send({"t": "start"})
    await until(lambda: a.g().get("seats") and b.g().get("seats"), "game start")
    await until(lambda: a.g()["pending"]["stage"] == "turn", "turn")

    joiner = await Client("Late").open()            # mid-game token player (not seated)
    await until(lambda: joiner.pid and joiner.g().get("seats"), "joiner state")
    ok("mid-game joiner gets no me block", joiner.g().get("me") is None)
    ok("spectator gets no me block", spec.g().get("me") is None)

    actor_pid = a.g()["pending"]["actor"]
    actor, other = (a, b) if actor_pid == a.pid else (b, a)
    snap0 = public_table(a)

    # --- non-actors / spectators / joiner try everything
    verbs = [{"t": "act", "action": "income"}, {"t": "act", "action": "tax"},
             {"t": "act", "action": "coup", "target": actor.pid},
             {"t": "respond", "choice": "challenge"}, {"t": "respond", "choice": "pass"},
             {"t": "lose", "card": 0}, {"t": "keep", "cards": [0, 1]},
             {"t": "again"}, {"t": "start"}, {"t": "settings", "patch": {"bots": 5}},
             {"t": "state", "token": actor.token}, {"t": "hello", "token": actor.token}]
    for c, label in ((other, "non-actor"), (spec, "watch:true spectator"), (joiner, "mid-game joiner")):
        for v in verbs:
            await c.send(v, pause=0.02)
        await asyncio.sleep(0.3)
        ok("%s cannot change the table" % label, public_table(a) == snap0)

    # --- malformed game messages from the actor
    garbage = ["{", "[]", "1", '"act"', "null", json.dumps({"t": "act", "action": "tax" * 2000}),
               "[" * 3000 + "]" * 3000, json.dumps({"t": "act", "action": ["income"]}),
               json.dumps({"t": "act", "action": "steal", "target": actor.pid}),
               json.dumps({"t": "lose", "card": 0}), json.dumps({"t": "keep", "cards": [0, 1]}),
               json.dumps({"t": "act", "action": "income", "pad": "x" * 5000})]
    for raw in garbage:
        await actor.send(raw, pause=0.02)
    await asyncio.sleep(0.3)
    ok("malformed/oversized/nested/self-target messages ignored", public_table(a) == snap0)

    # --- oversized frame far above the 4096 app cap (P2 check: server still takes it)
    big_closed = False
    try:
        await actor.ws.send("x" * (4 * 1024 * 1024))
        await asyncio.sleep(0.5)
        big_closed = actor.closed
    except Exception:
        big_closed = True
    ok("4 MB frame: connection not dropped (app cap only discards AFTER full receipt)",
       not big_closed, "informational: uvicorn ws_max_size default is 16 MiB")

    # --- flood: 200 income acts in a burst -> exactly one Income
    coins0 = next(s["coins"] for s in a.g()["seats"] if s["pid"] == actor.pid)
    for _ in range(200):
        await actor.ws.send(json.dumps({"t": "act", "action": "income"}))
    await asyncio.sleep(1.0)
    coins1 = next(s["coins"] for s in a.g()["seats"] if s["pid"] == actor.pid)
    ok("flood of 200 acts produced exactly one Income", coins1 == coins0 + 1,
       "%d -> %d" % (coins0, coins1))
    await asyncio.sleep(2.2)                           # let the rate window drain

    # --- other player (now actor) claims Tax; attacker/actor replays old messages
    await until(lambda: a.g()["pending"]["actor"] == other.pid, "turn passes")
    await other.send({"t": "act", "action": "tax"})
    await until(lambda: a.g()["pending"]["stage"] == "challenge", "challenge stage")
    snap1 = public_table(a)
    for v in ({"t": "respond", "choice": "pass"}, {"t": "respond", "choice": "challenge"}):
        await other.send(v, pause=0.05)                # claimant answering own claim
    await other.send({"t": "act", "action": "income"}) # replay of an act, wrong stage
    await joiner.send({"t": "respond", "choice": "challenge"})
    await asyncio.sleep(0.3)
    ok("claimant/joiner cannot answer the claim; act replay refused", public_table(a) == snap1)
    await actor.send({"t": "respond", "choice": "challenge"})
    await until(lambda: a.g()["pending"]["stage"] != "challenge", "challenge resolved")
    # replay the challenge after it resolved
    snap2 = public_table(a)
    await actor.send({"t": "respond", "choice": "challenge"}, pause=0.3)
    ok("replayed challenge after resolution refused", public_table(a) == snap2)

    # --- play out to the end with honest moves, then attack the results screen
    clients = {a.pid: a, b.pid: b}
    for _ in range(300):
        g = a.g()
        if g.get("winner") or a.state["phase"] != "playing":
            break
        p = g["pending"]
        if p["stage"] == "turn":
            c = clients[p["actor"]]
            acts = {x["action"] for x in c.g()["me"]["actions"]}
            tgt = next(x for x in clients if x != c.pid)
            await c.send({"t": "act", "action": "coup", "target": tgt} if "coup" in acts
                         else {"t": "act", "action": "income"}, pause=0.05)
        for c in clients.values():
            pr = (c.g().get("me") or {}).get("prompt")
            if pr and pr["kind"] == "lose":
                await c.send({"t": "lose", "card": 0}, pause=0.05)
            elif pr and pr["kind"] in ("challenge",):
                await c.send({"t": "respond", "choice": "pass"}, pause=0.05)
            elif pr and pr["kind"] == "block":
                await c.send({"t": "respond", "choice": "allow"}, pause=0.05)
            elif pr and pr["kind"] == "exchange":
                await c.send({"t": "keep", "cards": list(range(pr["keep"]))}, pause=0.05)
        await asyncio.sleep(0.03)
    await until(lambda: a.state["phase"] == "game_end", "game_end", 30)
    ok("game_end: loser/spectator still see no hidden cards",
       all(c.g().get("me") is None or c.g()["me"]["pid"] == c.pid for c in (a, b, spec, joiner)))
    await joiner.send({"t": "again"}, pause=0.5)
    ok("mid-game joiner cannot cut the results screen with 'again'",
       a.state["phase"] == "game_end", "phase now %r" % a.state["phase"])

    # --- global checks over every frame every client received
    human_tokens = [a.token, b.token, joiner.token]
    leaks = []
    nframes = 0
    for c in (a, b, spec, joiner):
        for m in c.frames:
            nframes += 1
            try:
                check_frame(m, c.pid)
            except AssertionError as e:
                leaks.append("shape %s: %s" % (c.name, e))
            blob = json.dumps(m)
            for t in human_tokens:
                if t != c.token and t in blob:
                    leaks.append("token of another player in frame to %s" % c.name)
            for f in ("Traceback", "Error", "Exception"):
                if f in blob:
                    leaks.append("error text in frame to %s" % c.name)
    ok("no shape/token/error leak in %d frames" % nframes, not leaks, "; ".join(leaks[:5]))
    ok("server still alive (ping/pong)", await alive())

    for c in (a, b, spec, joiner):
        c.reader.cancel()
        try:
            await c.ws.close()
        except Exception:
            pass
    fails = [n for n, r in results if not r]
    print("\n%d checks, %d failed: %s" % (len(results), len(fails), fails))


if __name__ == "__main__":
    asyncio.run(main())
