"""avrana_gamekit (EXPERIMENTAL, AVR-38): the core primitives, without any game and without the
Party. Runs on every OS; nothing here needs a Unix socket.
"""

import http.client
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import party_protocol as protocol                       # noqa: E402
from avrana_gamekit import app as gk_app, helpers, jsonio, party, runtime   # noqa: E402
from avrana_gamekit.devparty import DevParty                       # noqa: E402

KEY = protocol.new_key()
SID = "session-" + "a" * 32
ANA, BEN = ("participant-" + c * 32 for c in "ab")


# ---- jsonio -------------------------------------------------------------------------------------

def test_strict_json_accepts_exactly_the_named_fields():
    got = jsonio.strict_json(b'{"a": "x", "n": 3}', a=jsonio.STR, n=jsonio.INT)
    assert got == {"a": "x", "n": 3}


@pytest.mark.parametrize("raw", [
    b'{"a": "x", "a": "y"}',                 # duplicate key
    b'{"a": "x", "n": NaN}', b'{"a": "x", "n": Infinity}',
    b'{"a": "x"}',                            # missing
    b'{"a": "x", "n": 1, "z": 2}',            # extra
    b'{"a": 5, "n": 1}', b'{"a": "x", "n": true}', b'{"a": "x", "n": 1.5}',
    b'{"a": "x", "n": 9007199254740993}',     # beyond exact JSON numbers
    b'["a"]', b'not json', b'\xff\xfe', b'{"a": "\\ud800", "n": 1}',   # lone surrogate
    b'[' * 5000,                              # deep nesting
])
def test_strict_json_refuses(raw):
    with pytest.raises(jsonio.Bad):
        jsonio.strict_json(raw, a=jsonio.STR, n=jsonio.INT)


def test_bounded_strings():
    check = jsonio.bounded(3)
    assert check("abc") and not check("abcd") and not check(5) and not check("\ud800")


# ---- party: the two defects the stand-in had, fixed by construction ---------------------------------

@pytest.mark.parametrize("name", ["x-forwarded-for", "x-real-ip", "forwarded"])
def test_a_proxy_header_present_but_empty_is_still_the_front_door(name):
    assert party.from_party_core({}) is True
    assert party.from_party_core({"host": "localhost"}) is True
    assert party.from_party_core({name: "10.0.0.1"}) is False
    assert party.from_party_core({name: ""}) is False


def test_a_non_ascii_ticket_is_refused_without_raising():
    side = party.PartySide(KEY, "hello")
    side.launch(protocol.launch_message(KEY, "hello", SID, [{"participant": ANA, "name": "Ana", "role": "player"}]))
    for bad in ("aps0.é.x", "é", "aps0.aaaa.é", "", None, 5, "\ud800"):
        with pytest.raises(party.Invalid):
            side.redeem(bad)
    # the vendored function this guards: it raises something that is not Invalid (the defect)
    with pytest.raises(UnicodeEncodeError):
        side.side.present("aps0.é.x")


def test_token_lookup_never_raises():
    book = party.TokenBook()
    book.add("avr-" + "0" * 40, ANA)
    assert book.lookup("avr-" + "0" * 40) == ANA
    for bad in ("", "avr-", "é" * 44, "\ud800", None, 5, b"avr-", "avr-" + "0" * 41):
        assert book.lookup(bad) is None
    book.clear()
    assert book.lookup("avr-" + "0" * 40) is None


def test_a_session_redeems_once_and_the_token_is_stable():
    side = party.PartySide(KEY, "hello")
    roster = [{"participant": ANA, "name": "Ana", "role": "player"}]
    assert side.launch(protocol.launch_message(KEY, "hello", SID, roster)) == roster
    one = side.redeem(protocol.mint_ticket(KEY, "hello", SID, ANA, "player"))
    two = side.redeem(protocol.mint_ticket(KEY, "hello", SID, ANA, "player"))
    assert one["token"] == two["token"] and one["participant"] == ANA
    ticket = protocol.mint_ticket(KEY, "hello", SID, ANA, "player")
    side.redeem(ticket)
    with pytest.raises(party.Invalid):
        side.redeem(ticket)
    with pytest.raises(party.Invalid):                        # another game's ticket
        side.redeem(protocol.mint_ticket(protocol.new_key(), "hello", SID, ANA, "player"))


def test_build_result_is_checked_the_way_the_party_checks_it():
    made = party.build_result("hello", "b-1", "cooperative", [(ANA, "won"), (BEN, "won")],
                              "hello.result/v1", {"greetings": 2})
    assert made["schema"] == "avrana.game-result/v1"
    with pytest.raises(party.Refused):                          # a cooperative table wins or loses together
        party.build_result("hello", "b-1", "cooperative", [(ANA, "won"), (BEN, "lost")], "hello.result/v1", {})


def test_deliver_retries_until_the_party_answers():
    calls, sleeps = [], []
    answers = iter([(None, None), (503, None), (200, "accepted")])

    def report(message):
        calls.append(message)
        return next(answers)
    assert party.deliver(report, "m", sleep=sleeps.append) == (200, "accepted")
    assert len(calls) == 3 and sleeps == [1, 2]
    assert party.deliver(lambda m: (403, None), "m", sleep=sleeps.append) == (403, None)   # a 4xx is final


def test_report_to_a_tcp_address_reaches_the_receiver():
    dev = DevParty("hello", "http://127.0.0.1:1/games/hello", KEY)
    address = dev.start()
    try:
        # not a known session: the receiver says 409; the transport worked
        message = protocol.ended_message(KEY, "hello", SID, "abandoned")
        assert party.report_to(address, message)[0] == 409
        assert party.report_to(("127.0.0.1", 1), message, timeout=0.5) == (None, None)
    finally:
        dev.stop()


# ---- runtime: configuration ---------------------------------------------------------------------

def test_dev_mode_is_refused_where_the_appliance_environment_is_present(tmp_path):
    flags = ["--dev-tcp", "0", "--dev-key-file", str(tmp_path / "k")]
    for name in runtime.SYSTEMD_ENV:
        with pytest.raises(SystemExit) as e:
            runtime.configure("hello", flags, {name: "1"})
        assert "development-only" in str(e.value)
    assert not (tmp_path / "k").exists()                       # and nothing was created


def test_dev_mode_needs_both_flags_and_listens_on_loopback_only(tmp_path):
    with pytest.raises(SystemExit):
        runtime.configure("hello", ["--dev-tcp", "0"], {})
    with pytest.raises(SystemExit):
        runtime.configure("hello", ["--dev-key-file", str(tmp_path / "k")], {})
    with pytest.raises(SystemExit):
        runtime.configure("hello", ["--dev-tcp", "99999", "--dev-key-file", str(tmp_path / "k")], {})
    cfg = runtime.configure("hello", ["--dev-tcp", "0", "--dev-key-file", str(tmp_path / "k"),
                                      "--dev-party", "127.0.0.1:9", "--dev-origin", "http://127.0.0.1:8190",
                                      "--dev-idle-seconds", "3"], {})
    try:
        assert cfg.dev and cfg.listener.getsockname()[0] == "127.0.0.1"
        assert cfg.report_target == ("127.0.0.1", 9) and cfg.origin == "http://127.0.0.1:8190"
        assert cfg.options == {"idle_seconds": 3.0}
        assert protocol.read_key(str(tmp_path / "k")) == cfg.key
    finally:
        cfg.listener.close()


def test_the_appliance_model_needs_its_socket_key_and_party_socket(tmp_path):
    if not hasattr(socket, "AF_UNIX"):
        with pytest.raises(SystemExit):
            runtime.configure("hello", [], {})
        return
    me = str(os.getpid())
    with pytest.raises(SystemExit):                             # no inherited socket
        runtime.configure("hello", [], {})
    with pytest.raises(SystemExit):                             # no keys directory
        runtime.configure("hello", [], {"LISTEN_PID": me, "LISTEN_FDS": "1"})
    with pytest.raises(SystemExit) as e:                        # key missing: says so, names no key
        runtime.configure("hello", [], {"LISTEN_PID": me, "LISTEN_FDS": "1",
                                        "AVRANA_PARTY_KEYS": str(tmp_path), "AVRANA_PARTY_SOCKET": "/x"})
    assert "missing or unusable" in str(e.value)
    protocol.write_key(str(tmp_path / "hello.key"), KEY)
    cfg = runtime.configure("hello", [], {"LISTEN_PID": me, "LISTEN_FDS": "1", "AVRANA_PARTY_KEYS": str(tmp_path),
                                          "AVRANA_PARTY_SOCKET": "/run/party.sock",
                                          "AVRANA_PARTY_ORIGIN": "https://party.example"})
    assert (cfg.listener, cfg.key, cfg.report_target, cfg.origin, cfg.dev) == (
        3, KEY, "/run/party.sock", "https://party.example", False)


def test_listen_fds_and_origins():
    me = os.getpid()
    assert runtime.listen_fds({"LISTEN_PID": str(me), "LISTEN_FDS": "1"}) == [3]
    for environ in ({}, {"LISTEN_PID": str(me + 1), "LISTEN_FDS": "1"}, {"LISTEN_PID": "x", "LISTEN_FDS": "1"},
                    {"LISTEN_PID": str(me), "LISTEN_FDS": "many"}):
        assert runtime.listen_fds(environ) == []
    assert runtime.valid_origin("https://party.example:8443") == "https://party.example:8443"
    for bad in (None, "", "party.example", "https://u:p@x.example", "https://x.example/path", "https://x.example:99999",
                "javascript:alert(1)", "https://x.example?q"):
        assert runtime.valid_origin(bad) is None


# ---- the server: bounds, idle stop, shutdown ---------------------------------------------------------

class Echo:
    """The smallest app the server can host."""
    def __init__(self, idle=None):
        self.idle, self.seen = idle, []

    def handle(self, method, path, headers, raw):
        self.seen.append((method, path, headers, raw))
        return jsonio.json_reply(200, {"ok": True})

    def claim_idle_stop(self):
        return bool(self.idle and self.idle())


@pytest.fixture
def server_for():
    started = []

    def start(app):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        httpd = runtime.serve_forever_on(app, sock, (socket.AF_INET,))
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        started.append((httpd, thread))
        return httpd, thread, sock.getsockname()[1]
    yield start
    for httpd, thread in started:
        httpd.shutdown()
        httpd.server_close()


def _request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        reply = conn.getresponse()
        return reply.status, reply.read(), dict(reply.getheaders())
    finally:
        conn.close()


def test_the_server_bounds_what_it_reads(server_for):
    app = Echo()
    _, _, port = server_for(app)
    json_h = {"Content-Type": "application/json"}
    assert _request(port, "POST", "/x", b"{}", json_h)[0] == 200
    assert _request(port, "POST", "/x", b"{}" + b" " * jsonio.MAX_BODY, json_h)[0] == 413     # too large
    assert _request(port, "POST", "/x", b"{}", {"Content-Type": "text/plain"})[0] == 415
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        assert _request(port, method, "/x")[0] == 405
    status, _, headers = _request(port, "GET", "/x")
    assert status == 200 and headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "no-store"
    assert "Server" in headers and "Python" not in headers["Server"]
    n = len(app.seen)
    assert _request(port, "POST", "/x", b"{}", {**json_h, "Content-Length": "abc"})[0] in (400, 413)
    assert len(app.seen) == n                                   # nothing refused reached the app
    # a query string is never given to the app, and the proxy header it was sent is
    _request(port, "GET", "/y?token=secret", None, {"X-Forwarded-For": ""})
    method, path, headers, _ = app.seen[-1]
    assert path == "/y" and "x-forwarded-for" in headers


def test_the_server_stops_itself_when_the_app_says_idle(server_for):
    flag = {"idle": False}
    _, thread, port = server_for(Echo(idle=lambda: flag["idle"]))
    assert _request(port, "GET", "/")[0] == 200 and thread.is_alive()
    flag["idle"] = True
    thread.join(5)
    assert not thread.is_alive()


def test_the_server_takes_only_the_expected_socket_family():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        with pytest.raises(SystemExit):
            runtime.serve_forever_on(Echo(), sock, (getattr(socket, "AF_UNIX", -1),))
    finally:
        sock.close()
    unbound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(SystemExit):                          # not listening
            runtime.serve_forever_on(Echo(), unbound, (socket.AF_INET,))
    finally:
        unbound.close()


# ---- GameApp with a game of its own: the kit asks nothing of Hello Party --------------------------------

class Counter:
    """A game that is not Hello Party: one number, anyone may add to it; it ends at 3."""
    def __init__(self, roster):
        if not [r for r in roster if r["role"] == "player"]:
            raise gk_app.Declined("Needs a player.")
        self.v, self.n, self.over = 1, 0, False

    def view(self, participant):
        return {"v": self.v, "n": self.n, "you": participant is not None, "over": self.over}

    def add(self, participant, by):
        if by < 1:
            raise gk_app.Conflict("small", "Add at least one.")
        self.n += by
        self.v += 1
        self.over = self.n >= 3

    def finished(self):
        return gk_app.Finish("cooperative", ((ANA, "won"),), "counter.result/v1", {"n": self.n})


def counter_app(report=None, **kw):
    reports = []
    app = gk_app.GameApp("counter", "c-1", KEY, report or (lambda m: reports.append(m) or (200, "accepted")),
                         Counter, {"add": ({"by": jsonio.INT}, Counter.add)},
                         {"/": (b"<html>", "text/html")}, "https://party.example", **kw)
    return app, reports


def post(app, path, body, headers=None):
    reply = app.handle("POST", "/games/counter" + path, headers or {}, json.dumps(body).encode())
    return reply.status, json.loads(reply.body)


def test_another_game_runs_on_the_same_kit():
    app, reports = counter_app()
    roster = [{"participant": ANA, "name": "Ana", "role": "player"}]
    assert post(app, "/avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "counter", SID, [])})[0] == 409
    assert post(app, "/avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "counter", SID, roster)})[0] == 200
    status, body = post(app, "/api/redeem", {"ticket": protocol.mint_ticket(KEY, "counter", SID, ANA, "player")})
    assert status == 200 and body["role"] == "player" and body["view"]["you"] is True
    token = body["token"]
    assert post(app, "/api/add", {"token": token, "by": 0})[0] == 409
    assert post(app, "/api/add", {"token": token, "by": 3})[0] == 200
    assert app.wait_for_reports() and len(reports) == 1
    opened = protocol.open_message(KEY, reports[0], "ended", "party", protocol.ReplayGuard())
    assert opened["outcome"] == "completed" and opened["result"]["data"] == {"n": 3}
    assert app.handle("GET", "/games/counter/", {}, b"").status == 200
    assert app.handle("GET", "/games/counter/other", {}, b"").status == 404
    assert app.handle("GET", "/elsewhere", {}, b"").status == 404
    assert app.handle("GET", "/games/counter/api/party", {}, b"").body == b'{"partyOrigin": "https://party.example"}'


def test_idle_stop_waits_for_a_session_and_a_pending_report():
    now = {"t": 0.0}
    app, _ = counter_app(clock=lambda: now["t"], idle_seconds=10)
    roster = [{"participant": ANA, "name": "Ana", "role": "player"}]
    now["t"] = 100
    assert app.claim_idle_stop() is True and app.stopping                         # idle with no session
    app, _ = counter_app(clock=lambda: now["t"], idle_seconds=10)
    post(app, "/avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "counter", SID, roster)})
    now["t"] += 1000
    assert app.claim_idle_stop() is False                                          # a session never expires
    post(app, "/avrana/session/v0/end", {"message": protocol.end_message(KEY, "counter", SID)})
    assert app.claim_idle_stop() is False                                          # just ended: the interval restarts
    now["t"] += 11
    assert app.claim_idle_stop() is True
    assert post(app, "/avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "counter", SID, roster)})[0] == 503


def test_close_wakes_a_waiting_poll():
    app, _ = counter_app(poll_seconds=30)
    roster = [{"participant": ANA, "name": "Ana", "role": "player"}]
    post(app, "/avrana/session/v0/launch", {"message": protocol.launch_message(KEY, "counter", SID, roster)})
    token = post(app, "/api/redeem", {"ticket": protocol.mint_ticket(KEY, "counter", SID, ANA, "player")})[1]["token"]
    out = []
    t = threading.Thread(target=lambda: out.append(post(app, "/api/poll", {"token": token, "since": 1})))
    t.start()
    time.sleep(0.2)
    assert t.is_alive()
    app.close()
    t.join(5)
    assert not t.is_alive() and out[0][0] == 200


def test_helpers_are_optional_and_the_core_does_not_import_them():
    import ast
    for name in ("jsonio", "party", "runtime", "app"):
        tree = ast.parse((ROOT / "avrana_gamekit" / f"{name}.py").read_text(encoding="utf-8"))
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                   {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.endswith(("helpers", "devparty")) or "avrana_gamekit.helpers" in m for m in imported), name
    assert "'none'" in helpers.page_policy(None) and "frame-src https://p.example" in helpers.page_policy("https://p.example")


def test_the_kit_imports_only_the_standard_library_and_the_pinned_party_files():
    import ast
    stdlib = set(sys.stdlib_module_names)
    for path in sorted((ROOT / "avrana_gamekit").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            for name in names:
                top = name.split(".")[0]
                assert top in stdlib or top in ("core", "avrana_gamekit"), f"{path.name} imports {name}"
                if top == "core":
                    wanted = [a.name for a in node.names] if isinstance(node, ast.ImportFrom) else [name.split(".", 1)[-1]]
                    assert set(wanted) <= {"party_protocol", "party_result"}, f"{path.name} imports {name} {wanted}"
