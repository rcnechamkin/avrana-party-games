"""EXPERIMENTAL (AVR-38; see avrana_gamekit.__doc__). Core primitive: the request router.

`GameApp.handle(method, path, headers, raw) -> Reply` has no sockets in it. Under
`/games/<slug>/` it serves exactly:

    POST avrana/session/v0/launch | end   {"message"}   Party Core only (no proxy header at all)
    GET  api/party                        {"partyOrigin"}  the Party's origin, or null
    POST api/redeem {"ticket"}            -> {"ok","token","role","view"}
    POST api/poll   {"token","since"}     -> {"ok","view"}  long poll until `session.v` passes `since`
    POST api/<action> {"token", ...}      -> {"ok","view"} | 409 {"error","message","view"}
    GET  <file>                           exactly the files the game lists, nothing else

What a game supplies (duck-typed; see hello_party/session.py for a worked one):

    new_session(roster) -> session        roster = [{participant, name, role}]; raise Declined(sentence)
    session.v        int                  bumped on every change a player could see
    session.over     bool                 True once the game is finished
    session.view(participant) -> dict     THAT participant's projection (None: a watcher); the only
                                          state a client ever gets
    session.finished() -> Finish          called once when `over` becomes true
    actions = {"name": ({field: check}, fn(session, participant, **fields))}
                                          fn raises Conflict(code, sentence) to refuse

The kit decides who may hold a token (a valid, unspent ticket of the running session; a ticket
that says "player" for a participant who is not on the launch roster is refused), keeps the
tokens, the lock and the long poll, builds and reports the signed `ended`, and stops the process
when it has been idle. The game decides its own rules and what each seat may see.
"""

from __future__ import annotations

import threading
import time
from typing import NamedTuple, Optional

from avrana_gamekit import party
from avrana_gamekit.jsonio import INT, STR, Bad, Reply, json_reply, strict_json

log = party.log

POLL_SECONDS = 25            # how long a poll waits before answering "nothing new"
MAX_POLLERS = 32
IDLE_SECONDS = 60            # no authoritative session this long: release the process


class Declined(Exception):
    """A launch the game cannot host; the sentence is shown by the Party."""


class Conflict(Exception):
    """A request the game refuses. `message` is the sentence the player sees."""

    def __init__(self, code, message):
        super().__init__(code)
        self.code, self.message = code, message


class Finish(NamedTuple):
    """How a finished session reports: outcome "completed" with a result, or "abandoned" without."""
    mode: str = "cooperative"             # "competitive" | "cooperative"
    standings: tuple = ()                  # ((participant, "won"|"lost"|"draw"), ...), every player
    data_schema: Optional[str] = None      # e.g. "hello.result/v1"
    data: Optional[dict] = None
    outcome: str = "completed"


class GameApp:
    def __init__(self, slug, build, key, report, new_session, actions, files, party_origin=None,
                 poll_seconds=POLL_SECONDS, sleep=time.sleep, clock=time.monotonic,
                 idle_seconds=IDLE_SECONDS, page_headers=None):
        self.slug, self.build = slug, build
        self.base = f"/games/{slug}"
        self.side = party.PartySide(key, slug)
        self.report = report                       # callable(message) -> (status|None, verdict|None)
        self.new_session, self.actions = new_session, actions
        self.files = files                         # {path under base: (bytes, content-type)}
        self.page_headers = page_headers or (lambda path: ())
        self.party_origin = party_origin
        self.poll_seconds, self.sleep = poll_seconds, sleep
        self.clock, self.idle_seconds = clock, idle_seconds
        self.idle_since = clock()
        self.cond = threading.Condition()          # guards everything below
        self.stopping = False
        self.session = None
        self.players = set()
        self.tokens = party.TokenBook()
        self.finished_sid = None                   # the session whose end this process reported
        self.pollers = 0
        self.reporters = []

    # ---- routing --------------------------------------------------------------------------------

    def handle(self, method, path, headers, raw):
        """A Reply for one request. `headers` has lower-case names."""
        base = self.base
        if not path.startswith(base + "/"):
            return self._not_found()
        rest = path[len(base):]
        if rest.startswith("/avrana/"):
            if not party.from_party_core(headers) or method != "POST" \
                    or rest not in (party.LAUNCH_PATH, party.END_PATH):
                return self._not_found()
            return self._control(rest, raw)
        if rest == "/api/party" and method == "GET":
            return json_reply(200, {"partyOrigin": self.party_origin})
        if rest == "/api/redeem" and method == "POST":
            return self._redeem(raw)
        if rest == "/api/poll" and method == "POST":
            return self._poll(raw)
        if rest.startswith("/api/") and rest[5:] in self.actions and method == "POST":
            return self._act(rest[5:], raw)
        if rest in self.files and method == "GET":
            body, ctype = self.files[rest]
            return Reply(200, ctype, body, tuple(self.page_headers(rest)))
        return self._not_found()

    @staticmethod
    def _not_found():
        return json_reply(404, {"ok": False, "error": "not_found"})

    @staticmethod
    def _bad_json():
        return json_reply(400, {"ok": False, "error": "bad_json"})

    @staticmethod
    def _no_seat():
        return json_reply(403, {"ok": False, "message": "There is no game for this seat."})

    # ---- Party Core: launch and end -------------------------------------------------------------

    def _control(self, rest, raw):
        try:
            message = strict_json(raw, message=STR)["message"]
        except Bad:
            return self._bad_json()
        with self.cond:
            if self.stopping:
                return json_reply(503, {"ok": False, "message": "The game is restarting. Try again."})
            try:
                return self._launch(message) if rest == party.LAUNCH_PATH else self._end(message)
            except party.Invalid as e:
                log.warning("control message refused (%s)", e)
                return json_reply(403, {"ok": False, "message": "Refused.", "reason": str(e)})

    def _forget(self):
        self.session, self.finished_sid, self.players = None, None, set()
        self.tokens.clear()
        self.idle_since = self.clock()
        self.cond.notify_all()

    def _launch(self, message):
        roster = self.side.launch(message)                 # a newer launch replaces the old session
        self._forget()
        try:
            self.session = self.new_session(roster)
        except Declined as e:
            self.side.forget()
            return json_reply(409, {"ok": False, "message": str(e)})
        self.players = {r["participant"] for r in roster if r["role"] == "player"}
        log.info("launched (%d on the roster)", len(roster))
        return json_reply(200, {"ok": True})

    def _end(self, message):
        # The running session, or one this process already reported (acknowledged, so the Host's
        # choice always confirms and the finished session is released).
        if self.side.sid is None and self.finished_sid is not None:
            self.side.acknowledge_end(message, self.finished_sid)
            log.info("released by the party after the result was reported")
        else:
            self.side.end(message)
            log.info("ended by the party")
        self._forget()
        return json_reply(200, {"ok": True})

    # ---- the phones -----------------------------------------------------------------------------

    def _redeem(self, raw):
        try:
            ticket = strict_json(raw, ticket=STR)["ticket"]
        except Bad:
            return self._bad_json()
        with self.cond:
            try:
                who = self.side.redeem(ticket)
            except party.Invalid as e:
                log.warning("ticket refused (%s)", e)
                return json_reply(403, {"ok": False, "message": "Refused."})
            session = self.session
            if session is None:
                return json_reply(409, {"ok": False, "message": "There is no game."})
            seated = who["participant"] in self.players
            if who["role"] == "player" and not seated:     # a seat the roster never gave
                log.warning("ticket refused (not on the roster)")
                return json_reply(403, {"ok": False, "message": "Refused."})
            self.tokens.add(who["token"], who["participant"])
            role = "player" if seated and who["role"] == "player" else "spectator"
            view = session.view(who["participant"] if role == "player" else None)
        log.info("ticket redeemed (%s)", role)
        return json_reply(200, {"ok": True, "token": who["token"], "role": role, "view": view})

    def _who(self, token):
        """The player's participant id, "watcher", or None for a token this session never issued."""
        participant = self.tokens.lookup(token)
        if participant is None:
            return None
        return participant if participant in self.players else "watcher"

    @staticmethod
    def _view(session, who):
        return session.view(None if who == "watcher" else who)

    def _poll(self, raw):
        try:
            body = strict_json(raw, token=STR, since=INT)
        except Bad:
            return self._bad_json()
        with self.cond:
            who, session = self._who(body["token"]), self.session
            if who is None or session is None:
                return self._no_seat()
            if self.pollers >= MAX_POLLERS:
                return json_reply(503, {"ok": False, "error": "busy", "message": "Try again in a moment."})
            self.pollers += 1
            try:
                self.cond.wait_for(lambda: self.session is not session or self.stopping
                                   or session.v > body["since"], timeout=self.poll_seconds)
            finally:
                self.pollers -= 1
            if self.session is not session:                # replaced or ended while waiting
                return self._no_seat()
            return json_reply(200, {"ok": True, "view": self._view(session, who)})

    def _act(self, name, raw):
        fields, fn = self.actions[name]
        try:
            body = strict_json(raw, token=STR, **fields)
        except Bad:
            return self._bad_json()
        message = None
        with self.cond:
            who, session = self._who(body["token"]), self.session
            if who is None or session is None:
                return self._no_seat()
            if who == "watcher":
                return json_reply(403, {"ok": False, "error": "watching", "message": "You are watching this game."})
            try:
                fn(session, who, **{k: v for k, v in body.items() if k != "token"})
            except Conflict as c:
                return json_reply(409, {"ok": False, "error": c.code, "message": c.message,
                                        "view": session.view(who)})
            if session.over and self.finished_sid is None and self.side.sid is not None:
                message = self._conclude(session)
            self.cond.notify_all()
            view = session.view(who)
        if message is not None:
            self._report_later(message)
        return json_reply(200, {"ok": True, "view": view})

    # ---- the end of a game ----------------------------------------------------------------------

    def _conclude(self, session):
        """Stop admitting this session and return the signed report (None if not running). Under the lock."""
        sid = self.side.sid
        done = session.finished()
        made = None
        if done.outcome == "completed":
            try:
                made = party.build_result(self.slug, self.build, done.mode, done.standings,
                                          done.data_schema, done.data)
            except party.Refused as e:
                log.error("the result would be refused (%s); reporting the end without it", e)
        try:
            message = self.side.finish(done.outcome, made)
        except (party.Invalid, ValueError) as e:
            log.error("the end could not be reported (%s)", e)
            return None
        self.finished_sid = sid
        self.idle_since = self.clock()
        log.info("finished")
        return message

    def _report_later(self, message):
        thread = threading.Thread(target=self._report, args=(message,), name="gamekit-report", daemon=True)
        self.reporters = [t for t in self.reporters if t.is_alive()] + [thread]
        thread.start()

    def _report(self, message):
        status, verdict = party.deliver(self.report, message, sleep=self.sleep)
        verdict = verdict if verdict in ("accepted", "refused") else "unknown"
        if status == 200 and verdict == "accepted":
            log.info("the party accepted the result")
        else:
            log.warning("the party did not accept the report (status %s, result %s)", status, verdict)

    # ---- lifetime -------------------------------------------------------------------------------

    def claim_idle_stop(self):
        """Atomically stop admission after `idle_seconds` without an authoritative session. A
        running session never expires; a pending report must be delivered first."""
        with self.cond:
            if self.side.sid is not None or any(t.is_alive() for t in self.reporters):
                return False
            if self.clock() - self.idle_since < self.idle_seconds:
                return False
            self.stopping = True
            self.cond.notify_all()
            return True

    def close(self):
        """Shutdown: wake every waiting poll so no thread outlives the server."""
        with self.cond:
            self.stopping = True
            self.cond.notify_all()

    def wait_for_reports(self, timeout=10):
        """Block until every report thread has finished (tests; nothing in production waits)."""
        for thread in list(self.reporters):
            thread.join(timeout)
        return not any(t.is_alive() for t in self.reporters)
