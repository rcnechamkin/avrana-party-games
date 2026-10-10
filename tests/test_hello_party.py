"""Hello Party (EXPERIMENTAL, AVR-38): the session rules, the game around the kit, a real process
over loopback (every OS) and a real process over a Unix socket inherited on fd 3 (Linux CI; skipped
on Windows, which has no AF_UNIX).
"""

import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import party_protocol as protocol, party_result            # noqa: E402
from avrana_gamekit.app import Conflict, Declined                     # noqa: E402
from avrana_gamekit.devparty import DevParty, spawn_dev_game          # noqa: E402
from hello_party import conformance, server                           # noqa: E402
from hello_party.session import MAX_PLAYERS, Session                  # noqa: E402

KEY = protocol.new_key()
SID = "session-" + "a" * 32
P = ["participant-" + c * 32 for c in "abcdefgh"]
UNIX = hasattr(socket, "AF_UNIX")


def roster(n=2, spectators=0):
    return [{"participant": P[i], "name": f"P{i}", "role": "player"} for i in range(n)] + \
           [{"participant": P[n + i], "name": f"S{i}", "role": "spectator"} for i in range(spectators)]


# ---- the rules, with no sockets ---------------------------------------------------------------

def test_seats_follow_the_roster_and_other_counts_are_declined():
    s = Session(roster(3, spectators=1), random.Random(1))
    assert [s.seat_of(P[i]) for i in range(4)] == [0, 1, 2, None]
    for n in (0, MAX_PLAYERS + 1):
        with pytest.raises(Declined):
            Session(roster(n))
    with pytest.raises(Declined):
        Session([{"participant": P[0], "name": "A", "role": "player"}] * 2)


def test_each_seat_sees_only_its_own_secret():
    s = Session(roster(4, spectators=1), random.Random(7))
    views = {p: s.view(p) for p in P[:5]}
    secrets_ = [views[P[i]]["you"]["secret"] for i in range(4)]
    assert len(set(secrets_)) == 4
    for i in range(4):
        blob = json.dumps(views[P[i]])
        assert [w for w in secrets_ if w in blob] == [secrets_[i]]
    assert views[P[4]]["you"] is None and not any(w in json.dumps(views[P[4]]) for w in secrets_)
    assert s.view(None)["you"] is None and s.view("participant-" + "9" * 32)["seat"] is None
    assert all(p not in json.dumps(v) for v in views.values() for p in P)           # no ids in any view


def test_greeting_rules_and_finish():
    s = Session(roster(2), random.Random(1))
    with pytest.raises(Conflict) as e:
        s.greet(P[0], "x" * 41)
    assert e.value.code == "bad_text"
    for bad in ("", "   ", "a\u0007", "​"):
        with pytest.raises(Conflict):
            s.greet(P[0], bad)
    assert s.v == 1 and not s.board                                  # refusals change nothing
    with pytest.raises(Conflict) as e:
        s.greet("participant-" + "9" * 32, "hi")
    assert e.value.code == "watching"
    s.greet(P[0], "  hi   there ")
    assert s.board == [{"seat": 0, "by": "P0", "text": "hi there"}] and s.v == 2 and not s.over
    with pytest.raises(Conflict) as e:
        s.greet(P[0], "again")
    assert e.value.code == "already"
    s.greet(P[1], "yo")
    assert s.over and s.view(P[0])["result"] == {"greetings": 2}
    with pytest.raises(Conflict) as e:
        s.greet(P[1], "late")
    assert e.value.code == "over"
    done = s.finished()
    made = party_result.build("hello", "b", done.mode, [{"participant": p, "standing": st} for p, st in done.standings],
                              [P[0], P[1]], data_schema=done.data_schema, data=done.data)
    assert made["mode"] == "cooperative" and len(json.dumps(made)) < party_result.MAX_BYTES


# ---- the game around the kit (App.handle, no sockets) ------------------------------------------

def make(report=None, **kw):
    reports = []
    app = server.make_app(KEY, report or (lambda m: reports.append(m) or (200, "accepted")), "https://party.example", **kw)
    return app, reports


def call(app, route, body, headers=None, method="POST"):
    reply = app.handle(method, f"{server.BASE}/{route}", headers or {}, json.dumps(body).encode())
    return reply.status, json.loads(reply.body)


def launch(app, n=2, spectators=1, sid=SID):
    return call(app, "avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "hello", sid, roster(n, spectators))})


def redeem(app, i, role="player", sid=SID):
    return call(app, "api/redeem", {"ticket": protocol.mint_ticket(KEY, "hello", sid, P[i], role)})


def test_admission_private_views_and_a_spectator():
    app, _ = make()
    assert launch(app)[0] == 200
    s0, ana = redeem(app, 0)
    s1, ben = redeem(app, 1)
    s2, cy = redeem(app, 2, "spectator")
    assert (s0, s1, s2) == (200, 200, 200)
    assert (ana["role"], ben["role"], cy["role"]) == ("player", "player", "spectator")
    assert cy["view"]["you"] is None and cy["view"]["seat"] is None
    assert ben["view"]["you"]["secret"] not in json.dumps(ana) + json.dumps(cy)
    assert redeem(app, 5, "player")[0] == 403                          # a player nobody seated
    assert redeem(app, 5, "spectator")[0] == 200                       # a late member watches
    assert redeem(app, 0, "spectator")[1]["role"] == "spectator"       # never more than the ticket says
    assert call(app, "api/greet", {"token": cy["token"], "text": "hi"})[0] == 403
    assert call(app, "api/greet", {"token": ana["token"], "text": "hi"})[0] == 200


def test_reconnect_returns_the_same_seat_and_state():
    app, _ = make()
    launch(app)
    _, first = redeem(app, 0)
    call(app, "api/greet", {"token": first["token"], "text": "hi"})
    _, again = redeem(app, 0)
    assert again["token"] == first["token"] and again["view"]["seat"] == 0
    assert again["view"]["you"] == first["view"]["you"] and again["view"]["board"][0]["text"] == "hi"


def test_finish_reports_a_valid_signed_result_and_the_party_may_then_release_it():
    app, reports = make()
    launch(app)
    tokens = [redeem(app, i)[1]["token"] for i in (0, 1)]
    call(app, "api/greet", {"token": tokens[0], "text": "a"})
    assert call(app, "api/greet", {"token": tokens[1], "text": "b"})[1]["view"]["over"]
    assert app.wait_for_reports() and len(reports) == 1
    payload = protocol.open_message(KEY, reports[0], "ended", "party", protocol.ReplayGuard())
    assert payload["outcome"] == "completed" and payload["sid"] == SID
    checked = party_result.check(payload["result"], "hello", [P[0], P[1]])
    assert {e["standing"] for e in checked["standings"]} == {"won"} and checked["data"] == {"greetings": 2}
    assert redeem(app, 0)[0] == 403                                   # no ticket once it has ended
    assert call(app, "api/poll", {"token": tokens[0], "since": 1})[0] == 200   # the finished board stays readable
    assert call(app, "avrana/session/v0/end", {"message": protocol.end_message(KEY, "hello", SID)})[0] == 200
    assert call(app, "api/poll", {"token": tokens[0], "since": 1})[0] == 403
    assert len(reports) == 1


def test_the_hosts_end_reports_nothing():
    app, reports = make()
    launch(app)
    token = redeem(app, 0)[1]["token"]
    assert call(app, "avrana/session/v0/end", {"message": protocol.end_message(KEY, "hello", SID)})[0] == 200
    assert call(app, "api/poll", {"token": token, "since": 0})[0] == 403
    assert redeem(app, 0)[0] == 403 and reports == []
    other = "session-" + "b" * 32                                     # an end for a session that is not running
    assert call(app, "avrana/session/v0/end", {"message": protocol.end_message(KEY, "hello", other)})[0] == 403


def test_a_proxied_or_wrong_control_request_is_not_found():
    app, _ = make()
    message = {"message": protocol.launch_message(KEY, "hello", SID, roster())}
    for headers in ({"x-forwarded-for": "1.2.3.4"}, {"x-forwarded-for": ""}, {"x-real-ip": ""}, {"forwarded": ""}):
        assert call(app, "avrana/session/v0/launch", message, headers)[0] == 404
    assert call(app, "avrana/session/v0/launch", message, method="GET")[0] == 404
    assert call(app, "avrana/session/v0/other", message)[0] == 404
    assert call(app, "avrana/session/v0/launch", message)[0] == 200
    assert call(app, "avrana/session/v0/launch", message)[0] == 403   # a replayed launch


def test_every_served_file_is_exact_and_the_page_has_a_policy():
    app, _ = make()
    for path in server.FILES:
        reply = app.handle("GET", server.BASE + path, {}, b"")
        assert reply.status == 200 and dict(reply.headers)["Content-Security-Policy"]
    page = dict(app.handle("GET", server.BASE + "/", {}, b"").headers)["Content-Security-Policy"]
    assert "frame-src https://party.example" in page and "script-src 'self'" in page
    assert app.handle("GET", server.BASE + "/web/../session.py", {}, b"").status == 404
    assert app.handle("GET", server.BASE + "/hello_party/session.py", {}, b"").status == 404
    shim = (ROOT / "web" / "avrana-party-bridge.js").read_bytes()
    assert app.handle("GET", server.BASE + "/web/avrana-party-bridge.js", {}, b"").body == shim   # vendored, unchanged


def test_the_page_uses_the_bridge_and_stores_nothing():
    text = (ROOT / "hello_party" / "web" / "hello.mjs").read_text(encoding="utf-8")
    assert "connectParty" in text and "credentials: 'omit'" in text
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "indexedDB", "innerHTML", "eval("):
        assert forbidden not in text


def test_the_contract_is_this_games_and_the_game_ships_no_party_internals():
    contract = json.loads((ROOT / "hello_party" / "game-contract.json").read_text(encoding="utf-8"))
    assert contract["id"] == server.GAME == "hello" and contract["kind"] == "native"
    assert contract["extensions"]["net.avrana.test"]["test_only"] is True
    onboarding = json.loads((ROOT / "hello_party" / "web" / "onboarding.json").read_text(encoding="utf-8"))
    assert onboarding["schema"] == "avrana.onboarding/v0" and onboarding["game"] == "hello"
    import ast
    for path in (ROOT / "hello_party").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] in ("hello_party", "avrana_gamekit", "core", "__future__", "pathlib",
                                                    "os", "random", "json", "sys", "tempfile", "time"), (path.name, node.module)
                if node.module == "core":
                    assert {a.name for a in node.names} <= {"party_protocol"}, path.name   # only to mint keys in dev tooling


# ---- a real process over loopback (every OS) -----------------------------------------------------

def test_conformance_against_a_real_dev_process(capsys):
    assert conformance.main(say=lambda *_: None) == 0


def test_dev_mode_stops_when_idle_and_refuses_the_appliance_environment(tmp_path):
    key = tmp_path / "hello.key"
    protocol.write_key(str(key), KEY)
    proc, url = spawn_dev_game("hello_party", key, idle_seconds=0.3, cwd=str(ROOT))
    try:
        assert proc.wait(10) == 0                                       # idle: released itself
    finally:
        proc.kill()
    env = dict(os.environ, AVRANA_PARTY_KEYS=str(tmp_path))
    out = subprocess.run([sys.executable, "-m", "hello_party", "--dev-tcp", "0", "--dev-key-file", str(key)],
                         env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=20)
    assert out.returncode == 2 and "development-only" in out.stderr and "listening" not in out.stdout


def test_a_dev_process_with_no_party_still_serves_and_survives_an_unreachable_party(tmp_path):
    key = tmp_path / "hello.key"
    protocol.write_key(str(key), KEY)
    dev = DevParty("hello", "http://127.0.0.1:1/games/hello", KEY)
    proc, url = spawn_dev_game("hello_party", key, party_address=("127.0.0.1", 9), cwd=str(ROOT))   # nobody listens on 9
    try:
        dev.point_at(url)
        s = dev.launch({"Ana": "player"})
        ana = dev.phone(s, "Ana")
        assert ana.redeem()[0] == 200
        assert ana.act("greet", text="hi")[1]["view"]["over"]            # finishing works; reporting fails quietly
        time.sleep(0.3)
        assert proc.poll() is None and ana.poll(since=0)[0] == 200
    finally:
        proc.kill()


# ---- a real process on an inherited Unix socket (the systemd model) -------------------------------------

LAUNCHER = ("import os, runpy, sys, functools\n"
            "args = sys.argv[1:]; sys.argv[1:] = []\n"        # the game takes no arguments under systemd
            "os.dup2(int(args[0]), 3); os.set_inheritable(3, True)\n"
            "os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS='1')\n"
            "if len(args) > 1:\n"
            " import hello_party.server as s\n"
            " s.make_app = functools.partial(s.make_app, idle_seconds=float(args[1]))\n"
            "runpy.run_module('hello_party', run_name='__main__', alter_sys=True)\n")


@pytest.mark.skipif(not UNIX, reason="AF_UNIX is not available on this platform (runs on Linux CI)")
def test_the_real_process_on_an_inherited_unix_socket(tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir()
    protocol.write_key(str(keys / "hello.key"), KEY)
    game_sock, party_sock = str(tmp_path / "game.sock"), str(tmp_path / "party.sock")
    dev = DevParty("hello", "http://localhost/games/hello", KEY)
    dev.start(unix_path=party_sock)
    dev.point_at("http://localhost/games/hello", unix=game_sock)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(game_sock)
    listener.listen(16)
    env = dict(os.environ, AVRANA_PARTY_KEYS=str(keys), AVRANA_PARTY_SOCKET=party_sock,
               AVRANA_PARTY_ORIGIN="https://party.example", PYTHONPATH=str(ROOT))
    env.pop("LISTEN_PID", None)
    env.pop("LISTEN_FDS", None)
    log = open(tmp_path / "game.log", "wb")
    proc = subprocess.Popen([sys.executable, "-c", LAUNCHER, str(listener.fileno()), "3.0"],
                            pass_fds=[listener.fileno()], env=env, cwd=str(ROOT), stderr=log)
    try:
        conformance.lifecycle(dev, say=lambda *_: None)                  # the whole lifecycle, over AF_UNIX
        assert proc.wait(15) == 0                                        # then idle: it released the socket
    finally:
        proc.kill()
        log.close()
        listener.close()
        dev.stop()
    out = (tmp_path / "game.log").read_text(encoding="utf-8", errors="replace")
    assert "Traceback" not in out and "ended badly" not in out


@pytest.mark.skipif(not UNIX, reason="AF_UNIX is not available on this platform (runs on Linux CI)")
def test_the_process_opens_no_ip_socket_and_exits_on_sigterm(tmp_path):
    keys = tmp_path / "keys"
    keys.mkdir()
    protocol.write_key(str(keys / "hello.key"), KEY)
    game_sock = str(tmp_path / "game.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(game_sock)
    listener.listen(4)
    env = dict(os.environ, AVRANA_PARTY_KEYS=str(keys), AVRANA_PARTY_SOCKET=str(tmp_path / "none.sock"), PYTHONPATH=str(ROOT))
    env.pop("LISTEN_PID", None)
    env.pop("LISTEN_FDS", None)
    proc = subprocess.Popen([sys.executable, "-c", LAUNCHER, str(listener.fileno())], pass_fds=[listener.fileno()],
                            env=env, cwd=str(ROOT), stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.8)
        assert proc.poll() is None
        proc.terminate()
        assert proc.wait(10) == 0                                       # clean shutdown
    finally:
        proc.kill()
        listener.close()
