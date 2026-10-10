"""EXPERIMENTAL (AVR-38; see avrana_gamekit.__doc__). Core primitive: the Party boundary.

Built on the vendored `core/party_protocol.py` and `core/party_result.py`, imported unchanged.
This module adds what every native game wrote for itself around them:

  * `from_party_core(headers)`: control traffic is Party Core's alone and Party sends no proxy
    header, while the front door always adds one. A proxy header PRESENT AT ALL, even empty, is
    the front door (the stand-in once let an empty one through);
  * `PartySide`: launch / end / redeem, with a ticket that is not plain ASCII refused (the
    vendored `GameSide.present` raises UnicodeEncodeError on one; the stand-in once let that out);
  * `TokenBook`: this session's per-participant tokens, looked up in constant time, safe for any
    string a client sends;
  * `Reporter` and `deliver`: the signed `ended`, with retries, to the Party's internal Unix
    socket (production) or to a loopback TCP address (development);
  * `build_result`: an `avrana.game-result/v1` that passed the Party's own check.

It never sees a device or member id: a ticket carries a participant id, a role and, optionally,
the Host claim of the moment it was minted (kept off the games' view by default).
"""

from __future__ import annotations

import hmac
import http.client
import json
import logging
import socket
import time

from core import party_protocol as protocol
from core import party_result as result

from avrana_gamekit.jsonio import MAX_BODY

Invalid, Refused = protocol.Invalid, result.Refused

PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
ENDED_ROUTE = "/internal/party-session/v0/ended"
LAUNCH_PATH = "/avrana/session/v0/launch"
END_PATH = "/avrana/session/v0/end"
REPORT_TIMEOUT = 3                  # s for one `ended` POST
REPORT_RETRY_AFTER = (1, 2, 4)      # s before each retry (the message lives 30 s)

log = logging.getLogger("avrana_gamekit")


def from_party_core(headers):
    """True when a request may be control traffic: `headers` (lower-case names) carry no proxy
    header at all. Presence is the test, never the value."""
    return not any(name in headers for name in PROXY_HEADERS)


class PartySide:
    """One game's side of the session protocol: a thin, safer face for `protocol.GameSide`.
    Not thread-safe; the caller holds its lock around every call."""

    def __init__(self, key, slug):
        self.slug = slug
        self.side = protocol.GameSide(key, slug)
        self.key = key

    @property
    def sid(self):
        return self.side.sid

    def launch(self, message):
        """Open a signed launch; returns the roster [{participant, name, role}]. Raises Invalid."""
        return self.side.on_launch(message)

    def end(self, message):
        """Open a signed `end` for the running session; returns its sid. Raises Invalid."""
        return self.side.on_end(message)

    def acknowledge_end(self, message, sid):
        """An `end` for a session this game already reported: verified, acknowledged, nothing else."""
        if sid is None or protocol.unseal(self.key, message, "end", self.slug)["sid"] != sid:
            raise Invalid("session")
        protocol.open_message(self.key, message, "end", self.slug, self.side.guard)

    def forget(self):
        """Stop admitting any session (a launch this game cannot host)."""
        self.side.sid, self.side.roster = None, []

    def redeem(self, ticket):
        """A single-use ticket of the running session -> {token, role, participant}. Raises
        Invalid, including for a ticket that is not plain ASCII (a real one always is)."""
        if not isinstance(ticket, str) or not ticket.isascii():
            raise Invalid("shape")
        who = self.side.present(ticket)
        return {"token": who["token"], "role": who["role"], "participant": who["participant"]}

    def finish(self, outcome, made=None):
        """The signed `ended` report; the session stops being admissible here at once."""
        return self.side.ended(outcome, result=made)


class TokenBook:
    """This session's tokens: token -> participant. A lookup compares in constant time and answers
    None, never an exception, for any string a client can send."""

    def __init__(self):
        self.tokens = {}

    def add(self, token, participant):
        self.tokens[token] = participant

    def clear(self):
        self.tokens.clear()

    def lookup(self, token):
        try:
            probe = token.encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            return None
        found = None
        for known, participant in self.tokens.items():
            if hmac.compare_digest(known.encode("utf-8"), probe):
                found = participant
        return found


def build_result(slug, build, mode, standings, data_schema=None, data=None):
    """The `avrana.game-result/v1` for a finished session. `standings` is [(participant,
    "won"|"lost"|"draw")], every PLAYER once. Raises party_result.Refused if the Party would turn
    it away (this applies the Party's own check)."""
    players = [participant for participant, _ in standings]
    return result.build(
        slug, build, mode, [{"participant": p, "standing": s} for p, s in standings], players,
        data_schema=data_schema, data=data)


# ---- reporting `ended` ----------------------------------------------------------------------------

class _Conn(http.client.HTTPConnection):
    """HTTP over a Unix stream socket when `target` is a path, over TCP when it is (host, port)."""

    def __init__(self, target, timeout):
        if isinstance(target, str):
            super().__init__("localhost", timeout=timeout)
        else:
            super().__init__(target[0], target[1], timeout=timeout)
        self.target = target

    def connect(self):
        if not isinstance(self.target, str):
            return super().connect()
        if not hasattr(socket, "AF_UNIX"):
            raise OSError("this system has no Unix sockets")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.target)
        self.sock = sock


def report_to(target, message, timeout=REPORT_TIMEOUT):
    """POST one signed `ended`. Returns (HTTP status, the Party's word on the result: "accepted",
    "refused" or None), or (None, None) when nobody answers."""
    conn = _Conn(target, timeout)
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
        log.warning("could not report to the party (%s)", type(e).__name__)
        return None, None
    finally:
        conn.close()


def deliver(report, message, delays=REPORT_RETRY_AFTER, sleep=time.sleep):
    """Send the same signed report until the Party answers: at once, then after each of `delays`
    seconds, while nobody answers or the answer is a 5xx. A 200 or any 4xx is final."""
    answer = report(message)
    for delay in delays:
        status = answer[0]
        if status is not None and status < 500:
            break
        sleep(delay)
        answer = report(message)
    return answer
