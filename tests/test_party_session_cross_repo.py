"""Party session v0 across both repositories, over real HTTP and real WebSockets on 127.0.0.1.

The REAL party service from rcnechamkin/avrana-party (avrana.party.service + sessions: Party Core,
its launch/end GameLink and its loopback `ended` route) drives THIS game server (server.py's
routes and core/net.py, uvicorn on an ephemeral port). Two phones play BLUFF with party tickets.

Needs a party checkout: $AVRANA_PARTY_REPO, or a sibling ../avrana-party. Skipped otherwise,
except with AVRANA_REQUIRE_PARTY=1 (CI), where a missing checkout is a failure: this test is the
executable Party <-> Games compatibility boundary (AVR-219) and may not skip silently there.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PARTY_REPO = Path(os.environ.get("AVRANA_PARTY_REPO") or ROOT.parent / "avrana-party")
if not (PARTY_REPO / "avrana" / "party" / "sessions.py").exists():
    if os.environ.get("AVRANA_REQUIRE_PARTY") == "1":
        pytest.fail(f"no avrana-party checkout at {PARTY_REPO} (AVRANA_REQUIRE_PARTY=1): "
                    "the cross-repository compatibility test cannot run", pytrace=False)
    pytest.skip("no avrana-party checkout (set AVRANA_PARTY_REPO); cross-repo compatibility NOT verified",
                allow_module_level=True)
sys.path.append(str(PARTY_REPO))

import uvicorn                                                   # noqa: E402
from websockets.sync.client import connect as ws_connect         # noqa: E402

from avrana.party import identity, protocol as party_protocol_ref, service, sessions  # noqa: E402
from core import party_protocol, party_session                   # noqa: E402
from core import session as base_session                         # noqa: E402
from core.net import GameBinding                                 # noqa: E402
from games.bluff.game import BluffSession                        # noqa: E402

KEY = party_protocol.new_key()


def test_the_vendored_protocol_is_the_party_one():
    assert party_protocol_ref.VERSION == party_protocol.VERSION
    norm = lambda p: p.read_bytes().replace(b"\r\n", b"\n")
    assert norm(ROOT / "core" / "party_protocol.py") == \
        norm(PARTY_REPO / "avrana" / "party" / "protocol.py")


class Stack:
    """The real party service + this game server, both on loopback ephemeral ports."""

    def __init__(self, monkeypatch):
        import server
        self.tmp = tempfile.TemporaryDirectory()
        store = identity.DeviceStore(os.path.join(self.tmp.name, "devices.json"))
        self.svc = service.PartyService(store, service.load_games({"bluff": {"max_players": 6}}))
        cfg = service.Config({"127.0.0.1"}, {"http://127.0.0.1"}, secure_cookie=False)
        self.party = service.make_server(self.svc, cfg, port=0)
        party_url = "http://127.0.0.1:%d" % self.party.server_address[1]
        threading.Thread(target=self.party.serve_forever, daemon=True).start()

        # the server's own binding (its WebSocket route holds that object), given a party side
        self.binding = server.bindings["bluff"]
        monkeypatch.setattr(self.binding, "party", party_protocol.GameSide(KEY, "bluff"))
        monkeypatch.setattr(self.binding, "party_url", party_session.party_url(party_url))
        fresh = GameBinding("bluff", BluffSession(rng=random.Random(1)))
        for name, value in vars(fresh).items():         # every piece of state, restored after
            if name not in ("party", "party_url"):
                monkeypatch.setattr(self.binding, name, value)
        self.game = uvicorn.Server(uvicorn.Config(server.app, host="127.0.0.1", port=0,
                                                  log_level="warning", lifespan="off"))
        threading.Thread(target=self.game.run, daemon=True).start()
        deadline = time.time() + 10
        while not self.game.started and time.time() < deadline:
            time.sleep(0.02)
        assert self.game.started
        self.game_port = self.game.servers[0].sockets[0].getsockname()[1]
        game_url = "http://127.0.0.1:%d/games/bluff" % self.game_port

        endpoints = {"bluff": sessions.GameEndpoint("bluff", game_url, KEY)}
        self.svc.link = sessions.HttpGameLink(endpoints, timeout=5)
        extra, internal = sessions.routes(self.svc, endpoints)
        self.party.RequestHandlerClass.extra_routes = extra
        self.party.RequestHandlerClass.internal_routes = internal
        self.phones = {}

    def join(self, name):
        _, device = self.svc.store.issue()
        self.svc.call("join", device, name)
        self.phones[name] = device
        return device

    def launch(self, host):
        return self.svc.launch(host, "bluff", self.svc.core.party.version)

    def ticket(self, name):
        """Exactly what the party's ticket route mints for this phone."""
        with self.svc.lock:
            s, p = self.svc.core.participant_for(self.phones[name])
        return party_protocol.mint_ticket(KEY, "bluff", s.id, p.id, p.role)

    def socket(self, name):
        ws = ws_connect("ws://127.0.0.1:%d/games/bluff/ws" % self.game_port, open_timeout=5)
        ws.send(json.dumps({"t": "hello", "ticket": self.ticket(name)}))
        return ws

    def session(self):
        return self.svc.core.party.session

    def stop(self):
        self.game.should_exit = True
        self.party.shutdown()
        self.party.server_close()
        self.tmp.cleanup()


def recv_until(ws, pred, timeout=5.0):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        try:
            msg = json.loads(ws.recv(timeout=max(0.01, deadline - time.time())))
        except TimeoutError:
            break
        except Exception:
            break                                     # closed
        seen.append(msg)
        if pred(msg):
            return msg, seen
    return None, seen


def wait_for(pred, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stack(monkeypatch):
    monkeypatch.setattr(base_session, "COUNTDOWN_SECONDS", 0.1)
    monkeypatch.setattr(base_session, "GAME_END_SECONDS", 0.5)
    st = Stack(monkeypatch)
    yield st
    st.stop()


def playing(stack):
    host = stack.join("Alice")
    stack.join("Bob")
    s = stack.launch(host)
    assert s.state == "active", getattr(s, "detail", None)
    assert stack.binding.party.sid == s.id
    alice, bob = stack.socket("Alice"), stack.socket("Bob")
    for ws in (alice, bob):
        got, seen = recv_until(ws, lambda m: m.get("type") == "welcome")
        assert got, seen
        ws.send(json.dumps({"t": "ready", "ready": True}))
    time.sleep(0.2)
    alice.send(json.dumps({"t": "start"}))
    assert wait_for(lambda: stack.binding.session.phase == "playing")
    return s, alice, bob


def test_a_completed_bluff_game_is_reported_to_and_accepted_by_the_real_party(stack):
    s, alice, bob = playing(stack)
    bob.send(json.dumps({"t": "leave_game"}))
    time.sleep(0.2)
    alice.send(json.dumps({"t": "act", "action": "income"}))
    assert wait_for(lambda: s.state == "ended")
    assert s.outcome == "completed"
    # ADR 0011: the party holds the results screen; the game keeps its room until the host goes
    # home, which the party relays as `end` and the game answers with `party_ended` to its phones.
    assert stack.svc.core.location()["at"] == "results"
    assert stack.binding.party_room_sid == s.id
    stack.svc.go_home(stack.phones["Alice"], stack.svc.core.party.version)
    assert stack.svc.core.view(stack.phones["Alice"])["state"] == "lobby"     # no active game
    end, _ = recv_until(alice, lambda m: m.get("kind") == "party_ended")
    assert end and end["outcome"] == "completed"
    assert wait_for(lambda: stack.binding.party_room_sid is None)
    for ws in (alice, bob):
        ws.close()


def test_a_player_cannot_end_a_party_round_only_the_host_can(stack):
    """ADR 0011: during a Party round the game's own end_game verb is not a player's to use; the
    Party Host ends it for everyone through the party (test below). The round keeps running."""
    s, alice, bob = playing(stack)
    bob.close()
    assert wait_for(lambda: not all(p.connected for p in stack.binding.session.humans()))
    alice.send(json.dumps({"t": "end_game"}))
    time.sleep(0.5)
    assert s.state == "active" and s.outcome is None
    assert stack.binding.session.phase == "playing"
    alice.close()


def test_an_abandoned_bluff_game_is_reported_as_abandoned(stack, monkeypatch):
    """The game's own rules abandon a table whose humans all left: that reaches the party as
    `ended` with outcome `abandoned` (the party then holds a results screen like any end)."""
    from games.bluff import game as bluff
    monkeypatch.setattr(bluff, "EMPTY_TABLE_ABANDON", 0.2)
    s, alice, bob = playing(stack)
    alice.close()
    bob.close()
    assert wait_for(lambda: s.state == "ended")
    assert s.outcome == "abandoned"


def test_the_hosts_end_for_everyone_resets_the_real_game_and_is_confirmed(stack):
    s, alice, bob = playing(stack)
    stack.svc.end(stack.phones["Alice"], stack.svc.core.party.version)
    assert (s.state, s.outcome, s.game_confirmed_end) == ("ended", "ended_by_host", True)
    assert stack.binding.party.sid is None and stack.binding.session.players == {}
    end, _ = recv_until(bob, lambda m: m.get("kind") == "party_ended")
    assert end and end["outcome"] == "ended"
    # the old session's tickets die with it
    with pytest.raises(Exception):
        stack.ticket("Alice")                        # the party mints none any more
    stale = party_protocol.mint_ticket(KEY, "bluff", s.id,
                                       next(iter(s.participants.values())).id, "player")
    ws = ws_connect("ws://127.0.0.1:%d/games/bluff/ws" % stack.game_port, open_timeout=5)
    ws.send(json.dumps({"t": "hello", "ticket": stale}))
    msg, seen = recv_until(ws, lambda m: m.get("type") == "welcome", timeout=2)
    assert msg is None and any(m.get("kind") == "invalid" for m in seen)
    for w in (ws, alice, bob):
        w.close()


def test_the_party_can_launch_again_after_a_completed_game(stack):
    s, alice, bob = playing(stack)
    bob.send(json.dumps({"t": "leave_game"}))
    time.sleep(0.2)
    alice.send(json.dumps({"t": "act", "action": "income"}))
    assert wait_for(lambda: s.state == "ended")
    s2 = stack.launch(stack.phones["Alice"])
    assert s2.state == "active" and s2.id != s.id
    assert stack.binding.party.sid == s2.id and stack.binding.party_room_sid == s2.id
    for ws in (alice, bob):
        ws.close()
