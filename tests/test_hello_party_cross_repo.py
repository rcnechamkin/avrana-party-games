"""Hello Party (EXPERIMENTAL, AVR-38) driven by the REAL Party service from rcnechamkin/avrana-party:
Party Core's launch / end GameLink, its ticket minting for the session's participants, its internal
`ended` route and its acceptance of a game result. The game is the real process (`python -m
hello_party --dev-tcp`), reached over loopback HTTP, so this runs on Windows too; the Unix-socket
variant of the same process is in tests/test_hello_party.py (Linux).

Needs a Party checkout: $AVRANA_PARTY_REPO, or a sibling ../avrana-party. Skipped otherwise, except
with AVRANA_REQUIRE_PARTY=1 (CI), where a missing checkout is a failure.

Nothing Hello-Party-specific is in Party Core: the Party half of this test is a Game Contract file
(contracts/games/hello.json, test only) and a game entry given by hand, like BLUFF's test does.
"""

from __future__ import annotations

import json
import os
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
        pytest.fail(f"no avrana-party checkout at {PARTY_REPO} (AVRANA_REQUIRE_PARTY=1)", pytrace=False)
    pytest.skip("no avrana-party checkout (set AVRANA_PARTY_REPO); Hello Party vs the real Party NOT verified",
                allow_module_level=True)
sys.path.insert(0, str(ROOT))
sys.path.append(str(PARTY_REPO))

from core import party_protocol                                       # noqa: E402
from avrana.party import core, identity, service, sessions            # noqa: E402
from avrana_gamekit.devparty import DevParty, spawn_dev_game          # noqa: E402

GAME = "hello"
KEY = party_protocol.new_key()


class Seat:
    """What Phone needs of a session: the Party's session id and who is who."""
    def __init__(self, sid):
        self.sid, self.participants, self.roles = sid, {}, {}


class Stack:
    """The real party service + the Hello Party process, both on loopback."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        store = identity.DeviceStore(str(self.tmp / "devices.json"))
        self.svc = service.PartyService(store, service.load_games({GAME: {"max_players": 6}}))
        cfg = service.Config({"127.0.0.1"}, {"http://127.0.0.1"}, secure_cookie=False)
        self.party = service.make_server(self.svc, cfg, port=0)
        threading.Thread(target=self.party.serve_forever, daemon=True).start()
        key_path = self.tmp / "hello.key"
        party_protocol.write_key(str(key_path), KEY)
        self.proc, url = spawn_dev_game("hello_party", key_path, ("127.0.0.1", self.party.server_address[1]),
                                        cwd=str(ROOT))
        self.dev = DevParty(GAME, url, KEY)                            # only its phone client is used
        endpoints = {GAME: sessions.GameEndpoint(GAME, url, KEY)}
        self.svc.link = sessions.HttpGameLink(endpoints, timeout=10)
        extra, internal = sessions.routes(self.svc, endpoints)
        self.party.RequestHandlerClass.extra_routes = extra
        self.party.RequestHandlerClass.internal_routes = internal
        self.devices = {}

    def join(self, name):
        _, device = self.svc.store.issue()
        self.svc.call("join", device, name)
        self.devices[name] = device
        return device

    def launch(self, host_name):
        return self.svc.launch(self.devices[host_name], GAME, self.svc.core.party.version)

    def ticket(self, name):
        """What the Party's ticket route mints for this device (it raises for a device with no seat)."""
        with self.svc.lock:
            s, p = self.svc.core.participant_for(self.devices[name], GAME)
            host = p.member_id == self.svc.core.party.host_id
        return party_protocol.mint_ticket(KEY, GAME, s.id, p.id, p.role, host=host)

    def phone(self, name):
        stack = self

        class Real(DevParty):
            def ticket(self, session, who, role=None, host=False):
                return stack.ticket(who)
        real = Real(GAME, "http://127.0.0.1:%d/games/hello" % self.dev.port, KEY)
        real.point_at("http://127.0.0.1:%d/games/hello" % self.dev.port)
        s = self.svc.core.party.session
        return real.phone(Seat(s.id if s else None), name)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except Exception:
            self.proc.kill()
        self.party.shutdown()
        self.party.server_close()


def wait_for(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def stack():
    with tempfile.TemporaryDirectory() as tmp:
        st = Stack(tmp)
        try:
            yield st
        finally:
            st.stop()


def test_the_contract_files_agree_with_the_partys_copy():
    mine = json.loads((ROOT / "hello_party" / "game-contract.json").read_text(encoding="utf-8"))
    theirs_path = PARTY_REPO / "contracts" / "games" / "hello.json"
    if not theirs_path.exists():
        if os.environ.get("AVRANA_REQUIRE_PARTY") == "1":
            pytest.fail("Party has no contracts/games/hello.json: the paired Party branch is missing", pytrace=False)
        pytest.skip("this Party checkout has no contracts/games/hello.json (the paired AVR-38 branch)")
    assert json.loads(theirs_path.read_text(encoding="utf-8")) == mine


def test_a_game_the_real_party_launches_plays_and_reports_a_result_it_accepts(stack):
    stack.join("Alice")
    stack.join("Bob")
    s = stack.launch("Alice")
    assert s.state == "active", getattr(s, "detail", None)
    alice, bob = stack.phone("Alice"), stack.phone("Bob")
    assert alice.redeem()[0] == 200 and bob.redeem()[0] == 200
    assert {alice.view["seat"], bob.view["seat"]} == {0, 1}
    assert alice.view["you"]["secret"] not in json.dumps(bob.view)
    # a late member is a spectator; a device that never joined gets no ticket from the Party at all
    stack.join("Carol")
    carol = stack.phone("Carol")
    assert carol.redeem()[0] == 200 and carol.view["seat"] is None and carol.view["you"] is None
    with pytest.raises(Exception):
        stack.ticket("Nobody")
    # a reload: a fresh ticket, the same seat
    again = stack.phone("Alice")
    assert again.redeem()[0] == 200 and again.token == alice.token and again.view["seat"] == alice.view["seat"]
    # a refused intent changes nothing; both seats greet; the game finishes and reports
    assert alice.act("greet", text="")[0] == 409
    assert alice.act("greet", text="hello from Alice")[0] == 200
    assert bob.act("greet", text="hi")[0] == 200
    assert wait_for(lambda: s.state == "ended")
    assert s.outcome == "completed"
    assert s.result_refused is None and s.result is not None, s.result_refused    # ADR 0015: accepted
    assert s.result["mode"] == "cooperative" and s.result["game"]["id"] == GAME
    assert s.result["data_schema"] == "hello.result/v1" and s.result["data"] == {"greetings": 2}
    members = {m.name: m.id for m in stack.svc.core.party.members.values()}
    assert {e["member"]: e["standing"] for e in s.result["standings"]} == {members["Alice"]: "won", members["Bob"]: "won"}
    assert stack.svc.core.location()["at"] == "results"                           # the Party holds the results
    stack.svc.go_home(stack.devices["Alice"], stack.svc.core.party.version)       # the Host moves on: `end` is relayed
    assert stack.svc.core.view(stack.devices["Alice"])["state"] == "lobby"
    assert wait_for(lambda: alice.poll(since=0)[0] == 403)                        # the game released the finished session


def test_the_hosts_end_through_the_real_party_ends_the_game_with_no_result(stack):
    stack.join("Alice")
    stack.join("Bob")
    s = stack.launch("Alice")
    assert s.state == "active", getattr(s, "detail", None)
    alice = stack.phone("Alice")
    assert alice.redeem()[0] == 200
    stack.svc.end(stack.devices["Alice"], stack.svc.core.party.version)
    assert (s.state, s.outcome, s.game_confirmed_end) == ("ended", "ended_by_host", True)
    assert s.result is None
    assert alice.poll(since=0)[0] == 403                                          # its seats are gone
    with pytest.raises(Exception):
        stack.ticket("Alice")                                                     # the Party mints no more tickets
    s2 = stack.launch("Alice")                                                    # and a new game can start
    assert s2.state == "active" and s2.id != s.id
