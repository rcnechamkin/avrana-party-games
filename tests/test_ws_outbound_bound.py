"""AVR-217: one socket that stops reading must cost the server a bounded amount of memory, must be
dropped and cleaned up, and must not affect anyone else in the room.

A real uvicorn server and real sockets: the buffering in question lives in uvicorn and asyncio,
not in this application, so a fake socket would prove nothing. The stalled client is a raw TCP
socket that completes the WebSocket handshake, says hello, and then never reads again.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import socket
import struct
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from websockets.sync.client import connect

import server
from core import ws_limit
from core.net import GameBinding, MAX_WATCHERS
from games.bluff.game import BluffSession

FRAME = 8000                       # bytes of text in one pushed toast
PUSHES = 1500                      # ~12 MB per socket: far past the bound plus any kernel buffer


class Room:
    """A BLUFF room on a real server, with a way to run coroutines on the server's loop."""

    def __init__(self, ws_protocol):
        self.binding = GameBinding("bluff", BluffSession(rng=random.Random(1)))
        self.protocols = []
        room = self

        class Recording(ws_protocol):
            def connection_made(self, transport):
                super().connection_made(transport)
                room.protocols.append(self)

        app = FastAPI()

        @app.websocket("/games/bluff/ws")
        async def ws_endpoint(ws: WebSocket):
            room.loop = asyncio.get_running_loop()
            await room.binding.endpoint(ws)

        opts = server.serve_options()
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=0, log_level="warning", lifespan="off",
            ws_max_size=opts["ws_max_size"], ws=Recording))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        until(lambda: self.server.started)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = "ws://127.0.0.1:%d/games/bluff/ws" % self.port

    def on_loop(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def push(self, n=PUSHES):
        """n broadcast pushes, each a large fx plus every socket's state. Returns the longest
        time one push held the room lock."""
        async def go():
            worst = 0.0
            for _ in range(n):
                t0 = time.perf_counter()
                async with self.binding.lock:
                    await self.binding.push_all([{"kind": "toast", "to": None, "msg": "x" * FRAME}])
                worst = max(worst, time.perf_counter() - t0)
                await asyncio.sleep(0)
            return worst
        return self.on_loop(go(), timeout=120)

    def backlog(self, proto):
        async def go():
            return 0 if proto.transport.is_closing() else proto.transport.get_write_buffer_size()
        return self.on_loop(go())

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)


def until(cond, limit=10.0):
    end = time.time() + limit
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError("condition not reached in %.0f s" % limit)


def stalled_client(port, hello):
    """Handshake, one hello, then silence: the socket stays open and is never read again."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET /games/bluff/ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
               % (port, key)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += s.recv(1)
    assert b" 101 " in head.split(b"\r\n")[0]
    body, mask = json.dumps(hello).encode(), os.urandom(4)
    assert len(body) < 126
    s.sendall(struct.pack("!BB", 0x81, 0x80 | len(body)) + mask
              + bytes(b ^ mask[i % 4] for i, b in enumerate(body)))
    return s


class Reader:
    """A normal client: a thread that reads everything it is sent."""

    def __init__(self, url, hello):
        self.ws = connect(url, max_size=None)
        self.ws.send(json.dumps(hello))
        self.msgs = []
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        try:
            for raw in self.ws:
                self.msgs.append(json.loads(raw))
        except Exception:
            pass

    def toasts(self):
        return sum(1 for m in self.msgs if m.get("type") == "fx" and m.get("kind") == "toast"
                   and len(m.get("msg", "")) == FRAME)

    def last_state(self):
        return next(m for m in reversed(self.msgs) if m.get("type") == "state")

    def send(self, msg):
        self.ws.send(json.dumps(msg))

    def close(self):
        self.ws.close()


@pytest.fixture
def room():
    r = Room(ws_limit.BoundedWebSocketProtocol)
    yield r
    r.stop()


def players(room):
    a = Reader(room.url, {"t": "hello", "token": "tok-alice-0001", "name": "Alice"})
    b = Reader(room.url, {"t": "hello", "token": "tok-bob-00002", "name": "Bob"})
    until(lambda: len(room.binding.player_sockets) == 2)
    return a, b


# ---- the listener ---------------------------------------------------------------------------

def test_the_server_runs_the_bounded_websocket_protocol():
    assert server.serve_options()["ws"] is ws_limit.BoundedWebSocketProtocol
    assert ws_limit.MAX_OUTBOUND_BACKLOG == 1024 * 1024


# ---- one stalled watcher --------------------------------------------------------------------

def test_a_stalled_watcher_is_dropped_at_the_bound_and_cleaned_up(room, caplog):
    caplog.set_level("INFO", logger="gamehub.events")
    a, b = players(room)
    dead = stalled_client(room.port, {"t": "hello", "watch": True})
    until(lambda: len(room.binding.watch_sockets) == 1)
    stalled = room.protocols[-1]
    peak = []
    orig = stalled.pause_writing
    stalled.pause_writing = lambda: (peak.append(stalled.transport.get_write_buffer_size()), orig())

    worst = room.push()

    until(lambda: not room.binding.watch_sockets)              # reaped by its own receive loop
    assert stalled.transport.is_closing() and room.backlog(stalled) == 0
    assert len(peak) == 1                                       # dropped once, at the bound
    assert ws_limit.MAX_OUTBOUND_BACKLOG < peak[0] <= ws_limit.MAX_OUTBOUND_BACKLOG + 4 * FRAME
    assert any('"ev":"slow_socket_dropped"' in r.getMessage() and '"game":"bluff"' in r.getMessage()
               for r in caplog.records)
    # nobody else noticed: every push arrived, in order, and no push held the room
    until(lambda: a.toasts() == PUSHES and b.toasts() == PUSHES, limit=30)
    assert worst < 1.0
    assert set(room.binding.player_sockets) == {"tok-alice-0001", "tok-bob-00002"}
    assert all(p.connected for p in room.binding.session.players.values())
    dead.close(); a.close(); b.close()


def test_normal_play_carries_on_after_a_slow_socket_is_dropped(room):
    a, b = players(room)
    dead = stalled_client(room.port, {"t": "hello", "watch": True})
    until(lambda: len(room.binding.watch_sockets) == 1)
    room.push()
    until(lambda: not room.binding.watch_sockets)
    a.send({"t": "ready", "ready": True}); b.send({"t": "ready", "ready": True})
    a.send({"t": "start"})
    until(lambda: a.last_state()["phase"] == "playing" and b.last_state()["phase"] == "playing")
    assert a.last_state()["you"]["name"] == "Alice" and b.last_state()["you"]["name"] == "Bob"
    dead.close(); a.close(); b.close()


# ---- a stalled player -----------------------------------------------------------------------

def test_a_stalled_player_is_dropped_and_can_come_back_to_the_same_seat(room):
    a, b = players(room)
    a.send({"t": "ready", "ready": True}); b.send({"t": "ready", "ready": True})
    a.send({"t": "start"})
    until(lambda: room.binding.session.phase == "playing")
    b.close()
    until(lambda: "tok-bob-00002" not in room.binding.player_sockets)
    dead = stalled_client(room.port, {"t": "hello", "token": "tok-bob-00002", "name": "Bob"})
    until(lambda: "tok-bob-00002" in room.binding.player_sockets)
    hand = list(room.binding.session.g["hand"]["tok-bob-00002"])

    room.push()

    until(lambda: "tok-bob-00002" not in room.binding.player_sockets)      # dropped, seat kept
    assert room.binding.session.phase == "playing"
    assert not room.binding.session.players["tok-bob-00002"].connected
    assert "tok-bob-00002" in room.binding.session.g["away_since"]         # ordinary away handling
    until(lambda: a.toasts() == PUSHES, limit=30)
    back = Reader(room.url, {"t": "hello", "token": "tok-bob-00002", "name": "Bob"})
    until(lambda: any(m.get("type") == "state" for m in back.msgs))
    assert back.last_state()["game"]["me"]["cards"] == hand                # one frame: current
    assert room.binding.session.players["tok-bob-00002"].connected
    dead.close(); a.close(); back.close()


# ---- many slow sockets ----------------------------------------------------------------------

def test_several_stalled_sockets_are_each_bounded(room):
    a, b = players(room)
    dead = [stalled_client(room.port, {"t": "hello", "watch": True}) for _ in range(5)]
    until(lambda: len(room.binding.watch_sockets) == 5)
    worst = room.push()
    until(lambda: not room.binding.watch_sockets)
    until(lambda: a.toasts() == PUSHES and b.toasts() == PUSHES, limit=30)
    assert worst < 1.0
    for s in dead:
        s.close()
    a.close(); b.close()


def test_watchers_per_room_are_capped(room):
    """Without a cap the per-socket bound multiplies by however many sockets someone opens."""
    watchers = [Reader(room.url, {"t": "hello", "watch": True}) for _ in range(MAX_WATCHERS)]
    until(lambda: len(room.binding.watch_sockets) == MAX_WATCHERS)
    extra = Reader(room.url, {"t": "hello", "watch": True})
    extra.thread.join(5)
    assert not extra.thread.is_alive()                          # closed by the server
    assert any(m.get("kind") == "invalid" for m in extra.msgs)
    assert len(room.binding.watch_sockets) == MAX_WATCHERS
    watchers[0].close()                                         # a place frees up
    until(lambda: len(room.binding.watch_sockets) == MAX_WATCHERS - 1)
    again = Reader(room.url, {"t": "hello", "watch": True})
    until(lambda: len(room.binding.watch_sockets) == MAX_WATCHERS)
    for w in watchers[1:] + [again]:
        w.close()


# ---- why the bound exists -------------------------------------------------------------------

def test_uvicorns_own_protocol_holds_everything_for_a_stalled_socket():
    """The behaviour being bounded, pinned: with uvicorn's protocol as shipped, the same stalled
    socket is never dropped and the server holds every unread byte. If a later uvicorn adds
    write flow control this fails, and core/ws_limit.py should be reviewed against it."""
    from uvicorn.protocols.websockets.auto import AutoWebSocketsProtocol
    assert AutoWebSocketsProtocol is ws_limit.WebSocketsSansIOProtocol     # what "auto" selects
    room = Room(AutoWebSocketsProtocol)
    try:
        a, b = players(room)
        dead = stalled_client(room.port, {"t": "hello", "watch": True})
        until(lambda: len(room.binding.watch_sockets) == 1)
        stalled = room.protocols[-1]
        worst = room.push()
        assert len(room.binding.watch_sockets) == 1             # still attached
        assert room.backlog(stalled) > 3 * ws_limit.MAX_OUTBOUND_BACKLOG
        assert worst < 1.0                                     # and sends never blocked the room
        dead.close(); a.close(); b.close()
    finally:
        room.stop()
