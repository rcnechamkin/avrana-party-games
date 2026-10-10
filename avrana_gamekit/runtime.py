"""EXPERIMENTAL (AVR-38; see avrana_gamekit.__doc__). Core primitive: the process around a game.

Two ways to run, and they never mix:

  * the appliance (systemd model): the listening socket is an AF_UNIX stream socket inherited on
    file descriptor 3 (LISTEN_PID, LISTEN_FDS=1); the key is `<slug>.key` in the directory
    $AVRANA_PARTY_KEYS (a systemd credential); `ended` goes to the Party's internal Unix socket
    $AVRANA_PARTY_SOCKET; the Party's browser origin is $AVRANA_PARTY_ORIGIN. No IP socket is
    opened and no name resolved.
  * development only, an explicit opt-in: `--dev-tcp [PORT]` listens on 127.0.0.1 (never another
    address), `--dev-key-file PATH` names the key (created if missing), `--dev-party HOST:PORT`
    says where to report `ended`, `--dev-origin ORIGIN` is the Party's origin. Refused when any
    systemd variable above is present, so a unit can never run in dev mode by accident.

`serve(app, listener)` is the HTTP server on a socket that is already listening. The app is
asked to stop itself when idle (`claim_idle_stop`), and SIGTERM stops the server cleanly.
"""

from __future__ import annotations

import argparse
import http.server
import logging
import os
import re
import signal
import socket
import sys
import threading
from typing import NamedTuple

from core import party_protocol as protocol

from avrana_gamekit import party
from avrana_gamekit.jsonio import MAX_BODY, json_reply

ENV_KEYS, ENV_SOCKET, ENV_ORIGIN = "AVRANA_PARTY_KEYS", "AVRANA_PARTY_SOCKET", "AVRANA_PARTY_ORIGIN"
SYSTEMD_ENV = ("LISTEN_PID", "LISTEN_FDS", ENV_KEYS, ENV_SOCKET)
REQUEST_TIMEOUT = 10             # s: a stalled client never holds a thread for long
SECURITY = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer"}
BARE_ORIGIN = re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?")

log = logging.getLogger("avrana_gamekit")


def listen_fds(environ=os.environ, pid=None):
    """The sockets systemd passed to this process (sd_listen_fds): 3, 4, ... or []."""
    try:
        if int(environ.get("LISTEN_PID", "-1")) != (os.getpid() if pid is None else pid):
            return []
        return list(range(3, 3 + int(environ.get("LISTEN_FDS", "0"))))
    except ValueError:
        return []


def valid_origin(value):
    """`value` when it is a bare http(s) origin (scheme, host, optional port), else None. IPv6
    literals are not accepted by this experimental helper."""
    named = BARE_ORIGIN.fullmatch(value) if isinstance(value, str) else None
    if not named:
        return None
    port = named.group(1)
    return value if port is None or 1 <= int(port[1:]) <= 65535 else None


# ---- the HTTP server ------------------------------------------------------------------------------

def _make_handler(app):
    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT
        wbufsize = 65536
        server_version = "avrana-gamekit"
        sys_version = ""

        def log_message(self, *args):
            pass                                        # never a URL, token or ticket in a log

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
                self.close_connection = True

        def _length(self):
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
                raw = self.rfile.read(n)
                if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                    return self._answer(json_reply(415, {"ok": False, "error": "json_only"}))
            headers = {k.lower(): v for k, v in self.headers.items()}
            self._answer(app.handle(self.command, self.path.split("?", 1)[0], headers, raw))

        def do_GET(self):
            self._serve(False)

        def do_POST(self):
            self._serve(True)

        def _refuse_method(self):
            n = self._length()
            if n:
                self.rfile.read(n)
            self.close_connection = True
            self._answer(json_reply(405, {"ok": False, "error": "method"}))

        do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse_method

    return Handler


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    idle_check = None

    def service_actions(self):
        if self.idle_check is not None and self.idle_check():
            self.idle_check = None
            threading.Thread(target=self.shutdown, name="gamekit-idle-stop", daemon=True).start()

    def handle_error(self, request, client_address):
        log.warning("a request ended badly (%s)", getattr(sys.exc_info()[0], "__name__", "unknown"))


def serve_forever_on(app, listener, families):
    """A threaded HTTP server on a socket that is already listening: a file descriptor number (the
    one systemd handed over, never bound here) or a socket object. Only `families` are accepted;
    the server class is given the socket's family first so that no socket of another family is
    ever created."""
    sock = socket.socket(fileno=listener) if isinstance(listener, int) else listener
    if sock.family not in families or sock.type != socket.SOCK_STREAM:
        raise SystemExit("the inherited socket is not the kind of stream socket expected")
    if not sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        raise SystemExit("the inherited socket is not listening")
    server_class = type("Server", (_Server,), {"address_family": sock.family})
    server = server_class(sock.getsockname(), _make_handler(app), bind_and_activate=False)
    server.socket.close()                                # the one it made for itself
    server.socket = sock
    server.idle_check = getattr(app, "claim_idle_stop", None)
    return server


# ---- configuration --------------------------------------------------------------------------------

class Config(NamedTuple):
    listener: object            # fd number (appliance) or a listening socket (development)
    families: tuple
    key: bytes
    report_target: object       # Unix socket path, (host, port), or None
    origin: object              # the Party's browser origin or None
    dev: bool
    options: dict = {}          # extra keyword arguments for the app (development: idle_seconds)


def _parser(slug):
    ap = argparse.ArgumentParser(prog=slug, description="EXPERIMENTAL Avrana native game process")
    ap.add_argument("--dev-tcp", nargs="?", const=0, type=int, metavar="PORT",
                    help="DEVELOPMENT ONLY: listen on 127.0.0.1:PORT (0 or omitted: any free port)")
    ap.add_argument("--dev-key-file", metavar="PATH", help="development: the game key (created if missing)")
    ap.add_argument("--dev-party", metavar="HOST:PORT", help="development: where to report `ended`")
    ap.add_argument("--dev-origin", metavar="ORIGIN", help="development: the Party's browser origin")
    ap.add_argument("--dev-idle-seconds", type=float, metavar="S", help="development: idle stop after S seconds")
    return ap


def configure(slug, argv=(), environ=os.environ):
    """Resolve how this process runs. Raises SystemExit(message) for anything unusable; never
    prints a key."""
    args = _parser(slug).parse_args(list(argv))
    dev_flags = [f for f, v in (("--dev-tcp", args.dev_tcp), ("--dev-key-file", args.dev_key_file),
                                ("--dev-party", args.dev_party), ("--dev-origin", args.dev_origin),
                                ("--dev-idle-seconds", args.dev_idle_seconds))
                 if v is not None]
    if dev_flags:
        present = [name for name in SYSTEMD_ENV if name in environ]
        if present:
            raise SystemExit(f"{slug}: {', '.join(dev_flags)} are development-only and refused "
                             f"where the appliance environment is present ({', '.join(present)})")
        if args.dev_tcp is None or not args.dev_key_file:
            raise SystemExit(f"{slug}: development mode needs --dev-tcp and --dev-key-file")
        if not 0 <= args.dev_tcp <= 65535:
            raise SystemExit(f"{slug}: bad --dev-tcp port")
        path = args.dev_key_file
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            protocol.write_key(path, protocol.new_key())
        try:
            key = protocol.read_key(path)
        except (OSError, ValueError):
            raise SystemExit(f"{slug}: the dev key file is unusable")
        target = None
        if args.dev_party:
            host, _, port = args.dev_party.rpartition(":")
            if not host or not port.isdigit() or not 0 < int(port) <= 65535:
                raise SystemExit(f"{slug}: --dev-party is HOST:PORT")
            if host.strip("[]") not in ("127.0.0.1", "localhost", "::1"):
                raise SystemExit(f"{slug}: --dev-party must be a loopback address (development only)")
            target = (host, int(port))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", args.dev_tcp))
        sock.listen(16)
        options = {} if args.dev_idle_seconds is None else {"idle_seconds": args.dev_idle_seconds}
        return Config(sock, (socket.AF_INET,), key, target, valid_origin(args.dev_origin), True, options)
    if not hasattr(socket, "AF_UNIX"):
        raise SystemExit(f"{slug}: this system has no Unix sockets; use --dev-tcp for development")
    if listen_fds(environ) != [3]:
        raise SystemExit(f"{slug}: expected one inherited socket on fd 3 (LISTEN_FDS=1, LISTEN_PID)")
    keys, party_socket = environ.get(ENV_KEYS), environ.get(ENV_SOCKET)
    if not keys or not party_socket:
        raise SystemExit(f"{slug}: {ENV_KEYS} and {ENV_SOCKET} are required")
    try:
        key = protocol.read_key(os.path.join(keys, f"{slug}.key"))
    except (OSError, ValueError):
        raise SystemExit(f"{slug}: the party key is missing or unusable")   # never the key or its path content
    return Config(3, (socket.AF_UNIX,), key, party_socket, valid_origin(environ.get(ENV_ORIGIN)), False)


def run(slug, make_app, argv=None, environ=os.environ):
    """Run one game process. `make_app(key, report, party_origin, **options) -> GameApp`. Returns the exit
    code: 0 after an idle stop or a SIGTERM, 2 for a configuration problem."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    try:
        cfg = configure(slug, sys.argv[1:] if argv is None else argv, environ)
    except SystemExit as e:
        if isinstance(e.code, str):
            log.error("%s", e.code)
            return 2
        raise
    report = (lambda message: party.report_to(cfg.report_target, message)) if cfg.report_target \
        else (lambda message: (None, None))
    app = make_app(cfg.key, report, cfg.origin, **cfg.options)
    server = serve_forever_on(app, cfg.listener, cfg.families)
    if cfg.dev:
        host, port = server.server_address[:2]
        print(f"listening http://{host}:{port}/games/{slug}/", flush=True)

    def stop(*_):
        threading.Thread(target=server.shutdown, name="gamekit-stop", daemon=True).start()
    try:
        signal.signal(signal.SIGTERM, stop)
    except (ValueError, OSError):
        pass                                             # not the main thread, or not supported
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        server.server_close()
    return 0
