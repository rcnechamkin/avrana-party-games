"""EXPERIMENTAL, DEVELOPMENT ONLY (AVR-38; see avrana_gamekit.__doc__). A stand-in for the Party's
half of the session protocol, so a developer can launch a game, hand out tickets, play the Host and
the phones, and check the lifecycle on a laptop with no Pi and no Party Core.

It is NOT Party Core: it has no lobby, no identity, no Host rules. It is built on the very same
vendored `core/party_protocol.py` and `core/party_result.py` that the real Party uses, so what it
signs and checks is what the real Party signs and checks. The cross-repository test
(tests/test_hello_party_cross_repo.py) runs the same game against the REAL Party service.

    party = DevParty("hello", "http://127.0.0.1:8765/games/hello", key)
    party.start()                                   # receives the game's `ended` on 127.0.0.1
    session = party.launch({"Ana": "player", "Ben": "player", "Cy": "spectator"})
    ana = party.phone(session, "Ana"); ana.redeem()     # a fresh ticket, then the game's token
    ana.act("greet", text="hello"); party.end(session)
    party.stop()

A phone is a plain HTTP client of the game's own routes, exactly what the page's script does.
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import secrets
import socketserver
import subprocess
import sys
import threading
from urllib.parse import urlsplit

from core import party_protocol as protocol
from core import party_result as result

from avrana_gamekit import party


class Session:
    def __init__(self, sid, participants, roles):
        self.sid, self.participants, self.roles = sid, participants, roles     # name -> id / role
        self.ended = None                      # (payload, verdict) once the game reported

    def players(self):
        return [pid for name, pid in self.participants.items() if self.roles[name] == "player"]


class DevParty:
    def __init__(self, slug, game_url, key):
        self.slug, self.key = slug, key
        self.point_at(game_url)
        self.sessions = {}
        self.reports = []                      # every `ended` received: (status, payload or None)
        self.guard = protocol.ReplayGuard()
        self.lock = threading.Lock()
        self.httpd = None

    def point_at(self, game_url, unix=None):
        """Where the game is: its URL (host and port are used over TCP), or, with `unix`, the path
        of its Unix socket (the URL then only supplies the /games/<slug> path)."""
        parts = urlsplit(game_url)
        self.host, self.port, self.base = parts.hostname, parts.port, parts.path.rstrip("/")
        self.unix = unix

    # ---- the receiver of `ended` (the Party's internal route) ----------------------------------

    def start(self, unix_path=None):
        """Listen for `ended` on 127.0.0.1 (a free port), or on a Unix socket at `unix_path`
        (what the appliance does). Returns the address to hand the game."""
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                status, body = outer._ended(self.path, self.rfile.read(n))
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.unix_path = unix_path
        if unix_path:
            class UnixHTTP(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
                daemon_threads = True
            self.httpd = UnixHTTP(unix_path, Handler)
        else:
            self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, name="devparty", daemon=True).start()
        return self.address

    @property
    def address(self):
        """What to hand the game as its Party address: (host, port), or the Unix socket path."""
        return self.unix_path or ("127.0.0.1", self.httpd.server_address[1])

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()

    def _ended(self, path, raw):
        if path != party.ENDED_ROUTE:
            return 404, {"ok": False}
        try:
            message = json.loads(raw.decode("utf-8")).get("message")
            payload = protocol.open_message(self.key, message, "ended", "party", self.guard)
            if payload["iss"] != self.slug:
                raise protocol.Invalid("issuer")
        except (ValueError, AttributeError, protocol.Invalid) as e:
            with self.lock:
                self.reports.append((403, None))
            return 403, {"ok": False, "reason": str(e)}
        session = self.sessions.get(payload["sid"])
        if session is None:
            return 409, {"ok": False}
        reply = {"ok": True}
        if "result" in payload:
            try:
                result.check(payload["result"], self.slug, session.players())
                reply["result"] = "accepted"
            except result.Refused as e:
                reply.update(result="refused", reason=str(e))
        with self.lock:
            session.ended = (payload, reply.get("result"))
            self.reports.append((200, payload))
        return 200, reply

    # ---- Party Core's calls to the game --------------------------------------------------------

    def _post(self, path, body, headers=None):
        conn = party._Conn(self.unix, 30) if self.unix else http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            data = json.dumps(body).encode()
            conn.request("POST", self.base + path, body=data,
                         headers={"Content-Type": "application/json", **(headers or {})})
            reply = conn.getresponse()
            raw = reply.read()
            try:
                return reply.status, json.loads(raw.decode("utf-8"))
            except ValueError:
                return reply.status, None
        finally:
            conn.close()

    def launch(self, people):
        """Launch a session. `people` maps display name -> "player" | "spectator". Returns the
        Session; `.launched` is the game's (status, body)."""
        sid = "session-" + secrets.token_hex(16)
        participants = {name: "participant-" + secrets.token_hex(16) for name in people}
        roster = [{"participant": participants[n], "name": n, "role": r} for n, r in people.items()]
        session = Session(sid, participants, dict(people))
        self.sessions[sid] = session
        session.launched = self._post(party.LAUNCH_PATH, {
            "message": protocol.launch_message(self.key, self.slug, sid, roster)})
        return session

    def end(self, session):
        """The Host ends the session through the Party. Returns the game's (status, body)."""
        return self._post(party.END_PATH, {"message": protocol.end_message(self.key, self.slug, session.sid)})

    def ticket(self, session, name, role=None, host=False):
        """What the Party's ticket route would mint for this participant."""
        return protocol.mint_ticket(self.key, self.slug, session.sid, session.participants[name],
                                    role or session.roles[name], host=host)

    def join_late(self, session, name):
        """A member who joined after the launch: the Party mints them a spectator ticket."""
        session.participants[name] = "participant-" + secrets.token_hex(16)
        session.roles[name] = "spectator"
        return session.participants[name]

    def phone(self, session, name, role=None):
        return Phone(self, session, name, role)


class Phone:
    """One browser, as the game sees it: tickets in, a token out, its own view."""

    def __init__(self, dev, session, name, role=None):
        self.dev, self.session, self.name, self.role = dev, session, name, role
        self.token = None
        self.view = None

    def post(self, route, body):
        return self.dev._post("/api/" + route, body)

    def redeem(self, ticket=None):
        """Trade a ticket (a fresh one unless given) for a seat. Returns (status, body)."""
        status, body = self.post("redeem", {"ticket": ticket or self.dev.ticket(self.session, self.name, self.role)})
        if status == 200 and body and body.get("ok"):
            self.token, self.view = body["token"], body["view"]
        return status, body

    def poll(self, since=None):
        status, body = self.post("poll", {"token": self.token, "since": self.view["v"] if since is None else since})
        if status == 200 and body and body.get("ok"):
            self.view = body["view"]
        return status, body

    def act(self, action, **fields):
        status, body = self.post(action, {"token": self.token, **fields})
        if body and isinstance(body.get("view"), dict):
            self.view = body["view"]
        return status, body


def spawn_dev_game(module, key_path, party_address=None, idle_seconds=None, cwd=None, timeout=15):
    """Start `python -m <module> --dev-tcp 0 ...` (any OS) and return (process, game_url) once it
    prints its `listening` line. The caller stops it (terminate)."""
    cmd = [sys.executable, "-m", module, "--dev-tcp", "0", "--dev-key-file", str(key_path)]
    if party_address:
        cmd += ["--dev-party", "%s:%d" % party_address]
    if idle_seconds is not None:
        cmd += ["--dev-idle-seconds", str(idle_seconds)]
    env = {k: v for k, v in os.environ.items() if k not in ("LISTEN_PID", "LISTEN_FDS")}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=cwd, env=env, text=True)
    line = {}
    reader = threading.Thread(target=lambda: line.setdefault("v", proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    text = line.get("v", "")
    if not text.startswith("listening "):
        proc.kill()
        raise RuntimeError("the game did not start: %r" % text)
    return proc, text.split()[1].rstrip("/")
