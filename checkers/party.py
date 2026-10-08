"""The Party boundary of the Checkers process (AVR-238): how it talks to Party Core and to the
socket it was handed. Nothing in this module knows a rule of checkers.

Plan decision D5: these helpers are written here and not shared. They are adapted from the
stand-in native game in avrana-party (avrana/games/standin/game.py, AVR-236), which has the same
five things (strict bounded JSON, the guard against proxied control traffic, an HTTP server on an
inherited socket, a reporter of `ended` over the Party's internal Unix socket, `listen_fds`).
Two games repeating one helper is evidence for a future SDK (AVR-37, AVR-38), not yet a reason to
freeze one; the findings in the pull request say what overlaps.

The session protocol and the result envelope are the vendored, byte-identical Party files
(`core/party_protocol.py`, `core/party_result.py`; plan decision D4). They are the public boundary
today, not an SDK: the module paths may change when one exists.

What the process is handed, as the field-test runtime convention (ADR 0016 section 5):

    fd 3                  its listening socket, an AF_UNIX stream socket (LISTEN_FDS, LISTEN_PID)
    $AVRANA_PARTY_KEYS    a directory holding `checkers.key`
    $AVRANA_PARTY_SOCKET  the Party's internal Unix socket, where `ended` is reported
    $AVRANA_PARTY_ORIGIN  the Party's browser origin, which the page hands to the bridge shim

It opens no IP socket and resolves no name: the unit is restricted to AF_UNIX.
"""

from __future__ import annotations

import http.client
import http.server
import json
import ipaddress
import logging
import os
import re
import socket
import sys
import time
import threading
from typing import NamedTuple

from core import party_protocol as protocol
from core import party_result as result

GAME = "checkers"
# Which implementation produced a result (avrana.game-result/v1 `game.build`). A hand-kept
# constant for now, to be changed whenever the rules or the session change what a result says;
# recomputing it from the sources is the fork's way (core/party_session.build_id) and a question
# for the SDK.
BUILD = "checkers-0.1.1"
DATA_SCHEMA = "checkers.result/v1"

BASE = f"/games/{GAME}"                       # where the front door and Party Core put the game
LAUNCH = BASE + "/avrana/session/v0/launch"
END = BASE + "/avrana/session/v0/end"
ENDED_ROUTE = "/internal/party-session/v0/ended"    # on the Party's internal socket

ENV_KEYS, ENV_SOCKET, ENV_ORIGIN = "AVRANA_PARTY_KEYS", "AVRANA_PARTY_SOCKET", "AVRANA_PARTY_ORIGIN"
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
MAX_BODY = 16384                # a signed launch for a few players fits many times over
MAX_INT = 2 ** 53               # what a JSON number holds exactly everywhere
REQUEST_TIMEOUT = 10            # s: a stalled client never holds a thread for long
REPORT_TIMEOUT = 3              # s for one `ended` POST to the party
REPORT_RETRY_AFTER = (1, 2, 4)  # s before each retry: at most four tries inside the message's 30 s
BARE_ORIGIN = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?")

SECURITY = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer"}

log = logging.getLogger("checkers")


# ---- strict, bounded JSON -----------------------------------------------------------------------

class Bad(Exception):
    """A request that is not acceptable JSON of the expected shape."""


def STR(value):
    """A string that can be written out as UTF-8: JSON allows a lone surrogate, which cannot."""
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def INT(value):
    return type(value) is int and abs(value) <= MAX_INT


def INTS(value):
    return isinstance(value, list) and len(value) <= 64 and all(INT(item) for item in value)


def strict_json(raw, **fields):
    """The body as a dict with exactly the keys named in `fields`, each passing its check (STR,
    INT or INTS). One object, no duplicate keys, no NaN or Infinity, nothing else."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise Bad("duplicate key")
            out[key] = value
        return out

    def no_constant(name):
        raise Bad("bad number")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=no_constant)
    except (ValueError, RecursionError):
        raise Bad("bad json")
    if not isinstance(body, dict) or set(body) != set(fields) \
            or not all(check(body[key]) for key, check in fields.items()):
        raise Bad("bad shape")
    return body


class Reply(NamedTuple):
    status: int
    ctype: str
    body: bytes
    headers: tuple = ()          # extra (name, value) pairs


def json_reply(status, body):
    return Reply(status, "application/json", json.dumps(body, sort_keys=True).encode())


# ---- the process's own environment --------------------------------------------------------------

def listen_fds(environ=os.environ, pid=None):
    """The sockets systemd passed to this process (sd_listen_fds): file descriptors 3, 4, ... when
    LISTEN_PID is this process and LISTEN_FDS says how many. [] otherwise."""
    try:
        if int(environ.get("LISTEN_PID", "-1")) != (os.getpid() if pid is None else pid):
            return []
        return list(range(3, 3 + int(environ.get("LISTEN_FDS", "0"))))
    except ValueError:
        return []


def read_key(keys_dir):
    """This game's key, from `<keys_dir>/checkers.key`, under the protocol's own file rules."""
    return protocol.read_key(os.path.join(keys_dir, f"{GAME}.key"))


def valid_origin(value):
    """`value` when it is an origin and nothing else (scheme, host, optional port), else None.
    The page is told this and nothing else decides where the Party is."""
    if not isinstance(value, str):
        return None
    named = BARE_ORIGIN.fullmatch(value)
    if named:
        port = named.group(1)
        return value if port is None or 1 <= int(port[1:]) <= 65535 else None
    # A literal is bracketed and contains only an address: no credentials, path, zone identifier,
    # query or fragment. ipaddress validates the full address without DNS or network imports.
    literal = re.fullmatch(r"https?://\[([0-9A-Fa-f:.]+)\](?::([0-9]{1,5}))?", value)
    if not literal:
        return None
    try:
        ipaddress.IPv6Address(literal.group(1))
    except ValueError:
        return None
    port = literal.group(2)
    return value if port is None or 1 <= int(port) <= 65535 else None


# ---- the result ---------------------------------------------------------------------------------

def make_result(standings, ending, plies):
    """The `avrana.game-result/v1` for a finished match. `standings` is [(participant, "won" |
    "lost" | "draw")], every player once. Raises party_result.Refused if the Party would turn it
    away (it never should: this applies the Party's own check)."""
    players = [participant for participant, _ in standings]
    return result.build(
        GAME, BUILD, "competitive",
        [{"participant": participant, "standing": standing} for participant, standing in standings],
        players, data_schema=DATA_SCHEMA, data={"ending": ending, "plies": plies})


# ---- reporting `ended` to the Party over its Unix socket ----------------------------------------

class UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP over a Unix stream socket: the same requests as loopback TCP, a different address."""

    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self.unix_path = path

    def connect(self):
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("this system has no Unix sockets")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.unix_path)
        self.sock = sock


def report_to(party_socket, message, timeout=REPORT_TIMEOUT, connect=None):
    """POST one signed `ended` to the Party's internal socket. Returns (HTTP status, the Party's
    word on the result: "accepted", "refused" or None), or (None, None) when nobody answers.
    `connect(address, timeout)` makes the connection (a Unix socket unless a test points it at a
    TCP receiver); it is looked up on each call."""
    conn = (connect or UnixHTTPConnection)(party_socket, timeout)
    try:
        conn.request("POST", ENDED_ROUTE, body=json.dumps({"message": message}).encode(),
                     headers={"Content-Type": "application/json", "Host": "localhost"})
        reply = conn.getresponse()
        raw = reply.read(MAX_BODY)
        try:
            answer = json.loads(raw.decode("utf-8"))
        except ValueError:
            answer = None
        verdict = answer.get("result") if isinstance(answer, dict) else None
        return reply.status, verdict if isinstance(verdict, str) else None
    except (OSError, ValueError, http.client.HTTPException) as e:
        log.warning("could not report to the party (%s)", type(e).__name__)   # the kind only
        return None, None
    finally:
        conn.close()


def deliver(report, message, delays=REPORT_RETRY_AFTER, sleep=time.sleep):
    """Send the same signed report until the Party answers: at once, then after each of `delays`
    seconds, for as long as nobody answers or the answer is a 5xx. A 200 or any 4xx is final (the
    Party's replay guard counts the report at most once). Returns the last (status, verdict)."""
    answer = report(message)
    for delay in delays:
        status = answer[0]
        if status is not None and status < 500:
            break
        sleep(delay)
        answer = report(message)
    return answer


# ---- the HTTP server on the inherited socket ----------------------------------------------------

def make_handler(app):
    """A request handler that gives every request to `app.handle(method, path, headers, raw)`,
    which returns a Reply. The handler logs nothing about requests: no URL, token or ticket."""
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT
        wbufsize = 65536                                # the head and the body leave in one write
        server_version = "checkers"
        sys_version = ""

        def log_message(self, *args):
            pass                                        # the game logs its own events, never URLs

        def address_string(self):
            return "unix"

        def _answer(self, reply):
            try:
                self.send_response(reply.status)
                self.send_header("Content-Type", reply.ctype)
                self.send_header("Content-Length", str(len(reply.body)))
                for key, value in SECURITY.items():
                    self.send_header(key, value)
                for key, value in reply.headers:
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(reply.body)
                self.wfile.flush()
            except OSError:
                self.close_connection = True            # the phone went away mid-answer

        def _length(self):
            """The declared body length when it is one this server will read, else None."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            return n if 0 <= n <= MAX_BODY else None

        def _serve(self, with_body):
            raw = b""
            if with_body:
                n = self._length()
                if n is None or "Content-Length" not in self.headers:
                    self.close_connection = True
                    return self._answer(json_reply(413, {"ok": False, "error": "body_size"}))
                raw = self.rfile.read(n)                # read before answering, so no reset
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    return self._answer(json_reply(415, {"ok": False, "error": "json_only"}))
            headers = {k.lower(): v for k, v in self.headers.items()}
            path = self.path.split("?", 1)[0]
            self._answer(app.handle(self.command, path, headers, raw))

        def do_GET(self):
            self._serve(False)

        def do_POST(self):
            self._serve(True)

        def _refuse_method(self):
            n = self._length()
            if n:
                self.rfile.read(n)                      # a body that is never used is still read, so no reset
            self.close_connection = True
            self._answer(json_reply(405, {"ok": False, "error": "method"}))

        do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse_method

    return Handler


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def service_actions(self):
        # shutdown() must run outside serve_forever's thread. Admission is already closed under
        # the App lock, so a simultaneous launch is refused and can retry on socket reactivation.
        if self.idle_check is not None and self.idle_check():
            self.idle_check = None
            threading.Thread(target=self.shutdown, name="checkers-idle-stop", daemon=True).start()

    def handle_error(self, request, client_address):
        # A phone that goes away mid-request is routine. One line, the kind of failure only: never
        # a traceback (which could carry a request line) and never the address.
        log.warning("a request ended badly (%s)", getattr(sys.exc_info()[0], "__name__", "unknown"))


def make_server(listener, app, families=None):
    """A threaded HTTP server on a socket that is already listening: a file descriptor number (the
    one systemd handed over, never bound here) or a socket object. By default only a Unix socket
    is accepted, because that is all the unit allows; tests pass `families` to serve a loopback
    TCP socket instead.

    The unit may create sockets of one family only (RestrictAddressFamilies=AF_UNIX), and the
    standard server class makes a socket of its own while it is being built. So the class is
    given the inherited socket's family first, and the socket it made is closed and replaced: no
    socket of any other family is ever created."""
    if families is None:
        if not hasattr(socket, "AF_UNIX"):
            raise SystemExit("checkers: this system has no Unix sockets")
        families = (socket.AF_UNIX,)
    sock = socket.socket(fileno=listener) if isinstance(listener, int) else listener
    if sock.family not in families or sock.type != socket.SOCK_STREAM:
        raise SystemExit("checkers: the inherited socket is not a Unix stream socket")
    if not sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        raise SystemExit("checkers: the inherited socket is not listening")
    server_class = type("Server", (_Server,), {"address_family": sock.family})
    server = server_class(sock.getsockname(), make_handler(app), bind_and_activate=False)
    server.socket.close()                               # the one it made for itself
    server.socket = sock
    server.idle_check = getattr(app, "claim_idle_stop", None)
    return server
