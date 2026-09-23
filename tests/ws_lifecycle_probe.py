"""Lifecycle probe for BLUFF against a RUNNING, fresh instance (not a pytest).

    .venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 main
    .venv/bin/python tests/ws_lifecycle_probe.py ws://127.0.0.1:8198 countdown_abandon

`main`: 3 humans; disconnect/reconnect scenarios mid-game (one room = one run).
`countdown_abandon`: refresh during the 3 s lobby countdown, then every human
leaves permanently and a spectator measures how long the room stays blocked.
Each scenario prints PASS/FAIL/OBS with evidence. Needs a fresh server per mode.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import socket
import sys
import time

import websockets

BASE = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8198"
URL = BASE + "/games/bluff/ws"
MODE = sys.argv[2] if len(sys.argv) > 2 else "main"
T0 = time.time()


def log(tag, name, msg=""):
    print("[%6.1fs] %-4s %-38s %s" % (time.time() - T0, tag, name, msg), flush=True)


def check(name, cond, evidence=""):
    log("PASS" if cond else "FAIL", name, evidence)
    return cond


class Client:
    def __init__(self, name, token=None, watch=False):
        self.name, self.watch = name, watch
        self.token = token or ("t" + secrets.token_hex(12))
        self.state, self.pid, self.fx, self.ws, self.welcome = None, None, [], None, None

    async def open(self):
        self.state, self.welcome = None, None
        self.ws = await websockets.connect(URL)
        hello = {"t": "hello", "watch": True} if self.watch else \
            {"t": "hello", "token": self.token, "name": self.name}
        await self.ws.send(json.dumps(hello))
        self.reader = asyncio.create_task(self._read(self.ws))
        await self.until(lambda: self.state is not None, 5)
        return self

    async def _read(self, ws):
        try:
            async for raw in ws:
                m = json.loads(raw)
                if m.get("type") == "welcome":
                    self.welcome, self.pid = m, m.get("pid")
                elif m.get("type") == "state":
                    self.state = m
                elif m.get("type") == "fx":
                    self.fx.append((time.time(), m))
        except Exception:
            pass

    async def close(self):
        await self.ws.close()
        await asyncio.sleep(0.3)

    async def send(self, **msg):
        await self.ws.send(json.dumps(msg))
        await asyncio.sleep(0.25)

    async def until(self, pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if pred():
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.05)
        return False

    # helpers over the last state
    def g(self):
        return (self.state or {}).get("game") or {}

    def pend(self):
        return self.g().get("pending") or {}

    def me(self):
        return self.g().get("me") or {}

    def player(self, pid):
        return next((p for p in self.state["players"] if p["pid"] == pid), None)

    def connected(self, pid):
        p = self.player(pid)
        return p and p["connected"]

    def left(self):
        s = self.state
        return None if not s or not s["deadline"] else (s["deadline"] - s["now"]) / 1000


def frozen_socket(token, name):
    """Raw TCP WebSocket that sends hello and then never reads again (no pongs):
    what a suspended phone looks like to the server."""
    host, port = BASE.split("//")[1].split(":")
    s = socket.create_connection((host, int(port)))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /games/bluff/ws HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
               % (host, port, key)).encode())
    s.recv(4096)
    payload = json.dumps({"t": "hello", "token": token, "name": name}).encode()
    mask = os.urandom(4)
    hdr = bytes([0x81, 0x80 | len(payload)]) if len(payload) < 126 else \
        bytes([0x81, 0x80 | 126]) + len(payload).to_bytes(2, "big")
    s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
    return s


async def lobby(*clients, bots=0):
    if bots:
        await clients[0].send(t="settings", patch={"bots": bots})
    for c in clients:
        await c.send(t="ready", ready=True)
    await clients[0].send(t="start")


async def main_mode():
    A, B, C = Client("Alice"), Client("Bob"), Client("Cara")
    for c in (A, B, C):
        await c.open()
    W = await Client("TV", watch=True).open()
    await lobby(A, B, C)
    await A.until(lambda: A.state["phase"] == "playing", 6)
    log("OBS", "game started", "seats=%s actor=%s" % (
        [s["name"] for s in A.g()["seats"]], A.pend().get("actor")))

    # S1: non-active player away ~5 s, same token back
    cards, pid = list(C.me()["cards"]), C.pid
    await C.close()
    seen_off = await A.until(lambda: not A.connected(pid), 2)
    await asyncio.sleep(5)
    nfx = len(A.fx)
    await C.open()
    check("S1 short drop: same pid+cards", C.pid == pid and C.me()["cards"] == cards,
          "pid %s->%s" % (pid, C.pid))
    await A.until(lambda: A.connected(pid), 2)
    check("S1 others saw away/back via players[].connected", seen_off and A.connected(pid))
    log("OBS", "S1 fx to others on return", [m for _, m in A.fx[nfx:]] or "none (no 'is back' toast)")

    # S2: ACTIVE player (Alice) drops on her turn
    d0 = A.state["deadline"]
    await A.close()
    await asyncio.sleep(3)
    await A.open()
    check("S2 active drop: still her turn, same deadline",
          A.pend().get("stage") == "turn" and A.pend().get("actor") == A.pid
          and A.state["deadline"] == d0 and len(A.me()["actions"]) > 0,
          "deadline same=%s, left=%.1fs, now-drift=%dms" % (
              A.state["deadline"] == d0, A.left(), A.state["now"] - int(time.time() * 1000)))

    # S6a: Alice claims Tax; Bob (a responder) drops during the challenge window
    await A.send(t="act", action="tax")
    await A.until(lambda: A.pend().get("stage") == "challenge", 2)
    d1 = A.state["deadline"]
    await B.close()
    await C.send(t="respond", choice="pass")
    stalled = A.pend().get("waiting") == [B.pid]
    await asyncio.sleep(4)
    await B.open()
    check("S6a responder drop: window waits for him; prompt+deadline restored on return",
          stalled and (B.me().get("prompt") or {}).get("kind") == "challenge"
          and B.state["deadline"] == d1, "waiting=%s left=%.1fs" % (A.pend().get("waiting"), B.left()))
    await B.send(t="respond", choice="pass")
    await A.until(lambda: A.pend().get("actor") == B.pid and A.pend().get("stage") == "turn", 3)

    # S7: prompt changes while disconnected (Cara away; Bob steals from Cara)
    await C.close()
    await B.send(t="act", action="steal", target=C.pid)
    await A.send(t="respond", choice="pass")
    await C.open()
    check("S7 prompt created while away is shown on return",
          (C.me().get("prompt") or {}).get("kind") == "challenge", "prompt=%s" % C.me().get("prompt"))
    await C.send(t="respond", choice="pass")
    await C.until(lambda: (C.me().get("prompt") or {}).get("kind") == "block", 2)
    await C.send(t="respond", choice="allow")
    await A.until(lambda: A.pend().get("actor") == C.pid and A.pend().get("stage") == "turn", 3)
    await C.send(t="act", action="income")
    await A.until(lambda: A.pend().get("actor") == A.pid and A.pend().get("stage") == "turn", 3)

    # S6b: TARGET of a Strike is away; measure the stall and what it costs him
    log("OBS", "coins", {s["name"]: s["coins"] for s in A.g()["seats"]})
    b_inf = next(s for s in A.g()["seats"] if s["pid"] == B.pid)["influence"]
    await B.close()
    t0 = time.time()
    await A.send(t="act", action="strike", target=B.pid)
    await C.send(t="respond", choice="pass")
    stages = []

    def watch_stage():
        st = (A.pend().get("stage"), tuple(A.pend().get("waiting") or ()))
        if not stages or stages[-1][1] != st:
            stages.append((round(time.time() - t0, 1), st))
        return A.pend().get("actor") == B.pid and A.pend().get("stage") == "turn"
    done = await A.until(watch_stage, 90)
    b_inf2 = next(s for s in A.g()["seats"] if s["pid"] == B.pid)["influence"]
    check("S6b away strike target: game advanced without him", done,
          "stall=%.1fs stages=%s influence %s->%s" % (time.time() - t0, stages, b_inf, b_inf2))

    # S8: Safari background: Bob away 45 s ON HIS TURN, then hello again
    t0 = time.time()
    await asyncio.sleep(45)
    await B.open()
    # Bob has been away since S6b (~77 s in total by now), longer than the own-turn
    # grace, so a passive autopilot may have played his turn (Income). What must hold:
    # same seat, same private cards, and the game did not stall waiting for him.
    check("S8 long absence (~77 s): seat + private cards intact, game kept moving",
          B.me() is not None and len(B.me().get("cards", [])) == b_inf2
          and A.pend().get("stage") is not None, "left=%.1fs actor=%s" % (
              B.left(), A.pend().get("actor")))

    # S3: duplicate tabs (same token, two sockets)
    B2 = Client("Bob", token=B.token)
    await B2.open()
    same = B2.me().get("cards") == B.me().get("cards") and B2.pid == B.pid
    await B2.send(t="act", action="income")
    await B.until(lambda: B.pend().get("actor") == C.pid, 2)
    both = B.pend().get("actor") == C.pid and B2.pend().get("actor") == C.pid
    await B.close()
    await asyncio.sleep(0.5)
    still = A.connected(B.pid)
    check("S3 dup tabs: same private view, act from either, 1 close keeps seat connected",
          same and both and still, "same=%s both_updated=%s connected_after_1_close=%s" % (same, both, still))
    B = B2

    # S4: refresh (close + immediate reopen) on own turn
    nfx = len(A.fx)
    await C.ws.close()
    await C.open()
    check("S4 refresh on own turn keeps actions", C.pend().get("actor") == C.pid and C.me()["actions"],
          "fx seen by others=%s" % [m.get("kind") for _, m in A.fx[nfx:]])
    await C.send(t="act", action="income")

    # S5: unknown/stale token joins mid-game
    nfx = len(A.fx)
    D = await Client("Dave").open()
    await D.send(t="act", action="income")
    inv = [m.get("msg") for _, m in D.fx if m.get("kind") == "invalid"]
    check("S5 stranger mid-game = spectator, no seat",
          D.me() == {} and D.pid not in [s["pid"] for s in A.g()["seats"]] and inv,
          "pid=%s invalid=%s toasts-to-table=%s players=%d" % (
              D.pid, inv, [m.get("msg") for _, m in A.fx[nfx:]], len(A.state["players"])))
    await D.send(t="again")
    log("OBS", "S5 spectator 'again' mid-game", "phase=%s" % A.state["phase"])
    await D.close()

    # S9: several players drop (Bob+Cara); Alice keeps playing
    await A.until(lambda: A.pend().get("actor") == A.pid, 3)
    await B.close()
    await C.close()
    await A.send(t="act", action="income")
    check("S9 two away: present player still acts; next actor is away",
          A.pend().get("actor") == B.pid, "Bob connected=%s Cara connected=%s left=%.1fs" % (
              A.connected(B.pid), A.connected(C.pid), A.left()))
    await B.open()
    await C.open()

    # S10: EVERY human socket gone <=10 s, then back
    snap = (A.pend().get("actor"), A.state["deadline"])
    for c in (A, B, C):
        await c.close()
    await asyncio.sleep(8)
    ph = W.state["phase"]
    offline = [p["connected"] for p in W.state["players"]]
    for c in (A, B, C):
        await c.open()
    check("S10 all humans gone 8 s: game NOT abandoned, resumes identically",
          # the table clock stops while everyone is away: same actor, and the
          # deadline moves later by the pause (never earlier)
          ph == "playing" and A.pend().get("actor") == snap[0]
          and (A.state["deadline"] or 0) >= (snap[1] or 0),
          "phase while empty=%s connected flags=%s" % (ph, offline))

    # S11: frozen socket (suspended phone): how long until the server notices?
    await C.close()
    raw = frozen_socket(C.token, "Cara")
    await A.until(lambda: A.connected(C.pid), 3)
    t0 = time.time()
    ok = await A.until(lambda: not A.connected(C.pid), 90)
    check("S11 half-open socket detected (uvicorn ws ping)", ok, "after %.1fs" % (time.time() - t0))
    raw.close()
    await C.open()
    log("OBS", "end of main", "phase=%s" % A.state["phase"])


async def countdown_abandon_mode():
    A, B = Client("Alice"), Client("Bob")
    await A.open()
    await B.open()
    W = await Client("TV", watch=True).open()
    await lobby(A, B, bots=1)
    await A.until(lambda: A.state["phase"] == "countdown", 2)
    old = B.pid
    await B.ws.close()
    await asyncio.sleep(0.2)
    await B.open()
    await A.until(lambda: A.state["phase"] == "playing", 6)
    seated = [s["name"] for s in A.g()["seats"]]
    check("C1 refresh during lobby countdown keeps the seat", B.pid == old and B.me() != {},
          "pid %s->%s seats=%s ready=%s" % (old, B.pid, seated, B.state["you"]["ready"]))

    # every human leaves for good
    for c in (A, B):
        await c.close()
    t0 = time.time()
    E = await Client("Eve").open()
    # the table is paused (phones may just be asleep); a newcomer may end it only
    # once it has been empty for PAUSE_TAKEOVER (60 s)
    await E.send(t="end_game")
    early = E.state["phase"]
    await asyncio.sleep(61)
    await E.send(t="end_game")
    await E.until(lambda: E.state["phase"] == "lobby", 5)
    await E.send(t="ready", ready=True)
    await E.send(t="start")
    check("C2 newcomer can end an EMPTY table after 60 s and start a game",
          early == "playing" and E.state["phase"] in ("lobby", "countdown", "playing"),
          "phase=%s you.ready=%s" % (E.state["phase"], E.state["you"]["ready"]))
    await E.close()
    last = None
    while time.time() - t0 < float(os.environ.get("ABANDON_WATCH", "600")):
        st = W.state
        key = (st["phase"], (st.get("game") or {}).get("pending", {}).get("stage"))
        if key != last:
            last = key
            log("OBS", "abandoned room", "phase=%s stage=%s alive=%s" % (
                key[0], key[1], [(s["name"], s["influence"]) for s in (st.get("game") or {}).get("seats", [])]))
        if st["phase"] == "lobby":
            break
        await asyncio.sleep(1)
    check("C3 abandoned room returns to lobby within watch window", W.state["phase"] == "lobby",
          "blocked for %.0fs" % (time.time() - t0))


asyncio.run({"main": main_mode, "countdown_abandon": countdown_abandon_mode}[MODE]())
