"""The Checkers game server (AVR-238): the routes, the lock, the seats and the report of `ended`.

`python3 -m checkers`, under the field-test runtime convention (see party.py). Every path is under
/games/checkers, which is where the front door and Party Core put the game.

Party Core to this process (signed with the game's key; never proxied):

    POST /games/checkers/avrana/session/v0/launch  {"message"}   starts a match from the roster
    POST /games/checkers/avrana/session/v0/end     {"message"}   drops it and holds no session

The phone (through nginx, so with proxy headers; a body is JSON and a token is only ever in a body):

    GET  /games/checkers/                  the page
    GET  /games/checkers/web/<file>        its script, style, icon and the vendored bridge shim
    GET  /games/checkers/onboarding.json   the rules, as avrana.onboarding/v0
    GET  /games/checkers/api/party         {"partyOrigin"}: the Party's origin, or null
    POST /games/checkers/api/redeem  {"ticket"}               -> {"ok","token","role","view"}
    POST /games/checkers/api/poll    {"token","since"}        -> {"ok","view"}  (long poll, 25 s)
    POST /games/checkers/api/move    {"token","v","move"}     -> {"ok","view"} | 409 {"error","message","view"}
    POST /games/checkers/api/resign  {"token"}                -> {"ok","view"}

A ticket is single use (core/party_protocol.GameSide.present). The token it buys is the protocol's
game_token: stable for one participant in one session, so a reload that redeems a fresh ticket
gets the same seat back. A token seats a participant; the Party's ticket is the only way to get
one. The page is handed the token in a body and keeps it in memory; it holds no cookie, and
this process sets none.

One match at a time: a newer launch replaces it. When the match is over the process builds the
result, stops admitting the session (GameSide.ended), tells the Party over its internal Unix socket
off the lock, and keeps the finished match and its tokens so that the phones that already hold a
seat can still read the final board. No ticket is issued once the session has ended, so a phone
that opens or reloads at the results has no seat and no board. The Party holds the results on this
game's page until the Host moves on (ADR 0011), so the page shows what the Party's bridge says
there: the Host's Play again and Party Home, or who everyone else is waiting for.
"""

from __future__ import annotations

import hmac
import logging
import os
import sys
import threading
import time
from pathlib import Path

from core import party_protocol as protocol
from core import party_result as result

from checkers import party
from checkers.party import BASE, END, GAME, INT, INTS, LAUNCH, STR, Bad, Reply, json_reply, strict_json
from checkers.session import Conflict, Match

log = party.log

PAGE = BASE + "/"
PARTY = BASE + "/api/party"
ONBOARDING = BASE + "/onboarding.json"
REDEEM, POLL, MOVE, RESIGN = (BASE + "/api/" + name for name in ("redeem", "poll", "move", "resign"))
POSTS = (REDEEM, POLL, MOVE, RESIGN)

WEB = Path(__file__).resolve().parent / "web"
SHARED = Path(__file__).resolve().parent.parent / "web"      # the repository's vendored bridge shim
JS, CSS = "text/javascript; charset=utf-8", "text/css; charset=utf-8"
FILES = {                                                    # exactly these, and nothing else, are served
    PAGE: (WEB / "index.html", "text/html; charset=utf-8"),
    ONBOARDING: (WEB / "onboarding.json", "application/json"),
    BASE + "/web/checkers.js": (WEB / "checkers.js", JS),
    BASE + "/web/app.mjs": (WEB / "app.mjs", JS),
    BASE + "/web/board.mjs": (WEB / "board.mjs", JS),
    BASE + "/web/checkers.css": (WEB / "checkers.css", CSS),
    BASE + "/web/icon.svg": (WEB / "icon.svg", "image/svg+xml"),
    # The shim is the Party's file, vendored unchanged and pinned by digest in
    # provider/avrana-contract.json. It is served from where it is, so the pinned bytes are the ones
    # the phone runs, at a path that does not move.
    BASE + "/web/avrana-party-bridge.js": (SHARED / "avrana-party-bridge.js", JS),
}

POLL_SECONDS = 25            # how long a poll waits for a change before answering "nothing new"
MAX_POLLERS = 32             # waiting polls at once: a party is a handful of phones
IDLE_SECONDS = 60            # no authoritative session: release the socket-activated process


def page_policy(party_origin):
    """The Content-Security-Policy of the page: its own scripts and style, requests to itself, and
    one frame, the Party's bridge, on the origin it was told (none when it was told nothing)."""
    frame = party_origin or "'none'"
    return ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"connect-src 'self'; frame-src {frame}; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def not_found():
    return json_reply(404, {"ok": False, "error": "not_found"})


def bad_json():
    return json_reply(400, {"ok": False, "error": "bad_json"})


class App:
    """The game's logic with no sockets in it: `handle` maps one request to one Reply. `side` is the
    protocol.GameSide for this game; `report(message)` is how `ended` reaches the Party (a callable
    returning (HTTP status or None, the Party's word on the result or None)); `new_match` makes a
    match from the two players (tests give it a position other than the opening)."""

    def __init__(self, side, report, party_origin=None, new_match=Match, poll_seconds=POLL_SECONDS,
                 sleep=time.sleep, clock=time.monotonic, idle_seconds=IDLE_SECONDS):
        self.side = side
        self.report = report
        self.party_origin = party_origin        # the Party's browser origin as handed to this process
        self.new_match = new_match
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self.clock, self.idle_seconds = clock, idle_seconds
        self.idle_since = clock()
        self.stopping = False
        self.cond = threading.Condition()       # guards everything below
        self.match = None                       # the running (or just finished) match
        self.tokens = {}                        # game token -> (participant, seat or None), this session
        self.finished_sid = None                # the session whose end this process has reported
        self.pollers = 0
        self.reporters = []                     # report threads, so a test can wait for them
        self.files = {path: (source.read_bytes(), ctype) for path, (source, ctype) in FILES.items()}

    # ---- routing ------------------------------------------------------------------------------

    def handle(self, method, path, headers, raw):
        """A Reply for one request. `headers` has lower-case names."""
        if path.startswith(BASE + "/avrana/"):
            # Control traffic: only Party Core sends it, and Party sends no proxy header; nginx
            # always adds one and also refuses this prefix itself. A proxy header at all, even an
            # empty one, is a request that came through the front door: it is not here.
            if any(h in headers for h in party.PROXY_HEADERS) or path not in (LAUNCH, END) \
                    or method != "POST":
                return not_found()
            return self._control(path, raw)
        if path in self.files or path == PARTY:
            if method != "GET":
                return json_reply(405, {"ok": False, "error": "method"})
            return self._static(path)
        if path in POSTS:
            if method != "POST":
                return json_reply(405, {"ok": False, "error": "method"})
            return {REDEEM: self._redeem, POLL: self._poll, MOVE: self._move, RESIGN: self._resign}[path](raw)
        return not_found()

    def _static(self, path):
        if path == PARTY:
            return json_reply(200, {"partyOrigin": self.party_origin})
        body, ctype = self.files[path]
        policy = page_policy(self.party_origin) if path == PAGE else "default-src 'none'"
        return Reply(200, ctype, body, (("Content-Security-Policy", policy),))

    # ---- Party Core: launch and end ------------------------------------------------------------

    def _control(self, path, raw):
        try:
            message = strict_json(raw, message=STR)["message"]
        except Bad:
            return bad_json()
        with self.cond:
            if self.stopping:
                return json_reply(503, {"ok": False, "message": "The game is restarting. Try again."})
            try:
                return self._launch(message) if path == LAUNCH else self._end(message)
            except protocol.Invalid as e:
                log.warning("control message refused (%s)", e)
                return json_reply(403, {"ok": False, "message": "Refused.", "reason": str(e)})

    def _forget(self):
        self.match, self.finished_sid = None, None
        self.tokens.clear()
        self.idle_since = self.clock()
        self.cond.notify_all()                  # waiting polls find their match gone

    def _launch(self, message):
        roster = self.side.on_launch(message)   # a newer launch replaces the old session
        self._forget()
        players = [r for r in roster if r["role"] == "player"]
        if len(players) != 2:
            # Not a game this process can host. The session is reset here too, so nothing admits a
            # ticket for it; the Party shows the sentence.
            self.side.sid, self.side.roster = None, []
            log.warning("launch refused: %d players on the roster", len(players))
            return json_reply(409, {"ok": False, "message": "Checkers needs two players."})
        try:
            self.match = self.new_match([{"participant": r["participant"], "name": r["name"]} for r in players])
        except ValueError:                      # the same person listed twice: not two players either
            self.side.sid, self.side.roster = None, []
            log.warning("launch refused: the two players are one participant")
            return json_reply(409, {"ok": False, "message": "Checkers needs two players."})
        log.info("launched (%d on the roster)", len(roster))
        return json_reply(200, {"ok": True})

    def _end(self, message):
        # The Party asks for the end of the session that is running, or (go home from the results)
        # of the one this process already reported: that is acknowledged too, so the Host's choice
        # always confirms and the finished match is released.
        sid = protocol.unseal(self.side.key, message, "end", GAME)["sid"]
        if self.side.sid is None and self.finished_sid is not None and sid == self.finished_sid:
            protocol.open_message(self.side.key, message, "end", GAME, self.side.guard)
            log.info("released by the party after the result was reported")
        else:
            self.side.on_end(message)
            log.info("ended by the party")
        self._forget()
        return json_reply(200, {"ok": True})

    # ---- the phones ----------------------------------------------------------------------------

    def _seat_for(self, token):
        """(participant, seat or None) for a token this session handed out, else None. Under the lock."""
        probe = token.encode("utf-8")
        for known, who in self.tokens.items():
            if hmac.compare_digest(known.encode("utf-8"), probe):
                return who
        return None

    @staticmethod
    def _no_seat():
        return json_reply(403, {"ok": False, "message": "There is no game for this seat."})

    def _redeem(self, raw):
        try:
            ticket = strict_json(raw, ticket=STR)["ticket"]
        except Bad:
            return bad_json()
        with self.cond:
            try:
                who = self.side.present(ticket)
            except protocol.Invalid as e:
                log.warning("ticket refused (%s)", e)
                return json_reply(403, {"ok": False, "message": "Refused."})
            match = self.match
            if match is None:
                return json_reply(409, {"ok": False, "message": "There is no game."})
            seat = match.seat_of(who["participant"])            # the roster seats people, not the ticket
            self.tokens[who["token"]] = (who["participant"], seat)
            role = "player" if seat else "spectator"
            view = match.view(seat)
        log.info("ticket redeemed (%s)", role)
        return json_reply(200, {"ok": True, "token": who["token"], "role": role, "view": view})

    def _poll(self, raw):
        try:
            body = strict_json(raw, token=STR, since=INT)
        except Bad:
            return bad_json()
        with self.cond:
            who, match = self._seat_for(body["token"]), self.match
            if who is None or match is None:
                return self._no_seat()
            if self.pollers >= MAX_POLLERS:
                return json_reply(503, {"ok": False, "error": "busy", "message": "Try again in a moment."})
            self.pollers += 1
            try:
                self.cond.wait_for(lambda: self.match is not match or match.v > body["since"],
                                   timeout=self.poll_seconds)
            finally:
                self.pollers -= 1
            if self.match is not match:                         # replaced or ended while waiting
                return self._no_seat()
            return json_reply(200, {"ok": True, "view": match.view(who[1])})

    def _move(self, raw):
        try:
            body = strict_json(raw, token=STR, v=INT, move=INTS)
        except Bad:
            return bad_json()
        return self._act(body["token"], lambda match, seat: match.move(seat, body["v"], body["move"]))

    def _resign(self, raw):
        try:
            body = strict_json(raw, token=STR)
        except Bad:
            return bad_json()
        return self._act(body["token"], lambda match, seat: match.resign(seat))

    def _act(self, token, action):
        """Run a move or a resignation for the token's seat. A game this ends is reported to the
        Party after the lock is released."""
        message = None
        with self.cond:
            who, match = self._seat_for(token), self.match
            if who is None or match is None:
                return self._no_seat()
            seat = who[1]
            if seat is None:
                return json_reply(403, {"ok": False, "error": "watching", "message": "You are watching this game."})
            try:
                action(match, seat)
            except Conflict as c:
                return json_reply(409, {"ok": False, "error": c.code, "message": c.message,
                                        "view": match.view(seat)})
            if match.over:
                message = self._conclude(match)
            self.cond.notify_all()
            view = match.view(seat)
        if message is not None:
            self._report_later(message)
        return json_reply(200, {"ok": True, "view": view})

    # ---- the end of a game ----------------------------------------------------------------------

    def _conclude(self, match):
        """The game is over: stop admitting this session and return the signed report (or None when
        the session is no longer running here). Under the lock."""
        sid = self.side.sid
        try:
            made = party.make_result(match.standings(), match.ending, match.plies)
        except result.Refused as e:
            # A result the Party would turn away is left out, not sent: the session still ends.
            log.error("the result would be refused (%s); reporting the end without it", e)
            made = None
        try:
            message = self.side.ended("completed", result=made)     # the session stops admitting here
        except (protocol.Invalid, ValueError) as e:
            log.error("the end could not be reported (%s)", e)
            return None
        self.finished_sid = sid
        self.idle_since = self.clock()
        log.info("finished (%s after %d moves)", match.ending, match.plies)
        return message

    def _report_later(self, message):
        thread = threading.Thread(target=self._report, args=(message,), name="checkers-report", daemon=True)
        self.reporters = [t for t in self.reporters if t.is_alive()] + [thread]
        thread.start()

    def _report(self, message):
        status, verdict = party.deliver(self.report, message, sleep=self.sleep)
        verdict = verdict if verdict in ("accepted", "refused") else "unknown"
        if status == 200 and verdict == "accepted":
            log.info("the party accepted the result")
        else:
            # The phones still show the final board; the Party shows the game as on until the Host's End.
            log.warning("the party did not accept the report (status %s, result %s)", status, verdict)

    def claim_idle_stop(self):
        """Atomically stop admission after a bounded interval without an authoritative session.
        An active match never expires, even with no phones. Finished-board reads do not keep an
        ended match resident forever; pending result delivery must finish before exit."""
        with self.cond:
            if self.side.sid is not None or any(t.is_alive() for t in self.reporters):
                return False
            if self.clock() - self.idle_since < self.idle_seconds:
                return False
            self.stopping = True
            return True

    def wait_for_reports(self, timeout=10):
        """Block until every report thread has finished (tests; nothing in production waits)."""
        for thread in list(self.reporters):
            thread.join(timeout)
        return not any(t.is_alive() for t in self.reporters)


def main(environ=os.environ):
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    if party.listen_fds(environ) != [3]:
        log.error("expected one inherited socket on fd 3 (LISTEN_FDS=1, LISTEN_PID)")
        return 2
    keys, party_socket = environ.get(party.ENV_KEYS), environ.get(party.ENV_SOCKET)
    if not keys or not party_socket:
        log.error("%s and %s are required", party.ENV_KEYS, party.ENV_SOCKET)
        return 2
    try:
        key = party.read_key(keys)
    except (OSError, ValueError):
        log.error("the party key is missing or unusable")       # never the key or the file content
        return 2
    origin = party.valid_origin(environ.get(party.ENV_ORIGIN))
    app = App(protocol.GameSide(key, GAME), lambda message: party.report_to(party_socket, message), origin)
    httpd = party.make_server(3, app)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
    return 0
