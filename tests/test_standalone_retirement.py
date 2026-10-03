"""AVR-222 (avrana-party ADR 0014): the bounds and the switch that retire standalone LAN Games.

* The server listens on loopback unless told otherwise: nginx is the only way in.
* The WebSocket server refuses an oversized frame before buffering it.
* With standalone admission off, a hello without a Party ticket may only watch: a browser-minted
  `wc-token` never takes a seat, and one client can no longer fill a lobby with invented tokens.
  Party tickets are unaffected.
"""
from __future__ import annotations

import asyncio
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
import websockets

import server
from core.net import GameBinding
from games.bluff.game import BluffSession
from test_party_session import (ALICE, BOB, KEY, binding, connect, launch, proto, seated_here,
                                shutdown, ticket)


ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


def retired(party=False):
    side = proto.GameSide(KEY, "bluff") if party else None
    return GameBinding("bluff", BluffSession(rng=random.Random(1)), party=side, standalone=False)


# ---- the listener ---------------------------------------------------------------------------

def test_the_server_listens_on_loopback_with_a_small_frame_limit():
    opts = server.serve_options()
    assert opts["host"] == "127.0.0.1"
    assert opts["ws_max_size"] == server.WS_MAX_SIZE == 64 * 1024
    assert opts["port"] == server.PORT


def test_host_and_admission_are_environment_switches():
    """A fresh process, so no other test sees a re-imported server."""
    code = ("import server; print(server.serve_options()['host'], server.STANDALONE_ADMISSION, "
            "sorted({b.standalone for b in server.bindings.values()}))")
    env = dict(os.environ, LANGAMES_HOST="0.0.0.0", AVRANA_STANDALONE_ADMISSION="0")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "0.0.0.0 False [False]"
    assert server.STANDALONE_ADMISSION is True                       # this process: the default
    assert all(b.standalone is True for b in server.bindings.values())


def test_an_oversized_frame_is_refused_by_the_websocket_server_itself():
    """Reproduced in the audit: an 8 MiB frame was fully received and only then dropped by the
    application's own length check. The server now closes with 1009 at its own limit."""
    opts = server.serve_options()
    game = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=0, log_level="warning",
                                         lifespan="off", ws_max_size=opts["ws_max_size"]))
    thread = threading.Thread(target=game.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not game.started and time.time() < deadline:
        time.sleep(0.02)
    assert game.started
    port = game.servers[0].sockets[0].getsockname()[1]

    async def scenario():
        url = "ws://127.0.0.1:%d/games/bluff/ws" % port
        async with websockets.connect(url, max_size=None) as ws:
            await ws.send("x" * (opts["ws_max_size"] + 1))
            with pytest.raises(websockets.ConnectionClosed) as closed:
                await asyncio.wait_for(ws.recv(), timeout=5)
            return closed.value.rcvd.code if closed.value.rcvd else None

    try:
        assert run(scenario()) == 1009                      # message too big
    finally:
        game.should_exit = True
        thread.join(5)


# ---- admission ------------------------------------------------------------------------------

def test_standalone_play_still_works_by_default():
    async def scenario():
        b = binding(party=False)
        a = await connect(b, {"t": "hello", "token": "tok-alice-1", "name": "Alice"})
        assert a[0].welcome().get("pid") and not a[0].welcome().get("watch")
        assert len(seated_here(b)) == 1
        await shutdown(b, a)
    run(scenario())


def test_with_admission_off_a_browser_token_only_watches():
    async def scenario():
        b = retired()
        a = await connect(b, {"t": "hello", "token": "tok-alice-1", "name": "Alice"})
        assert a[0].welcome() == {"type": "welcome", "watch": True}
        assert seated_here(b) == set() and not b.session.players
        await shutdown(b, a)
    run(scenario())


def test_with_admission_off_invented_tokens_cannot_fill_a_lobby():
    """Reproduced in the audit: one client with six invented tokens filled BLUFF's lobby and the
    seventh, real guest was told the room is full."""
    async def scenario():
        b = retired()
        pairs = [await connect(b, {"t": "hello", "token": "invented-%02d-xx" % i, "name": "N%d" % i})
                 for i in range(7)]
        assert all(ws.welcome() == {"type": "welcome", "watch": True} for ws, _ in pairs)
        assert not b.session.players
        await shutdown(b, *pairs)
    run(scenario())


def test_with_admission_off_party_tickets_are_unaffected():
    async def scenario():
        b = retired(party=True)
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        assert a[0].welcome().get("pid") and c[0].welcome().get("pid")
        assert seated_here(b) == {proto.game_token(KEY, launch_sid(b), p) for p in (ALICE, BOB)}
        tv = await connect(b, {"t": "hello", "watch": True})          # a TV page still watches
        assert tv[0].welcome() == {"type": "welcome", "watch": True}
        await shutdown(b, a, c, tv)
    run(scenario())


def launch_sid(b):
    return b.party_room_sid
