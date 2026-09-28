"""core.party_session — the game side of Avrana's party session protocol v0 (AVR-22, AVR-24).

The protocol itself is core/party_protocol.py, vendored unchanged from rcnechamkin/avrana-party
(avrana/party/protocol.py; ADR 0006 there has the semantics). This file only wires it into this
server:

  * keys: one 32-byte hex key per game, a 0600 file named <slug>.key in the directory given by
    $AVRANA_PARTY_KEYS. Only the games in GAMES look for one. No directory, no file or a bad file
    means no party side: that game runs standalone as before.
  * POST /games/<slug>/avrana/session/v0/launch  {"message": <launch>}  (server.py): loopback,
    unproxied and signed; GameBinding.party_launch() resets the room to that roster.
  * the WebSocket hello (core/net.py): {"t": "hello", "ticket": …} is admitted with
    GameSide.admit(); while a party session runs, a browser-minted token only watches.
  * POST /games/<slug>/avrana/session/v0/end  {"message": <end>}  (server.py, AVR-24): same
    guards; GameBinding.party_end() puts back a fresh, empty, non-running room.
  * `ended` (AVR-24): when the game's own rules finish or abandon a party game, core/net.py
    takes the signed report from GameSide.ended() under its lock and deliver_ended() POSTs it
    here, off the lock and off the event loop, to $AVRANA_PARTY_URL + ENDED_PATH.

Delivery policy for `ended`: one POST, then a retry after each of RETRY_DELAYS while the party
does not answer (connection error, timeout) or answers 5xx; any other answer is final (200
accepted; 403/409 refused: stale, replayed or ended meanwhile). The same signed report is sent
every time, so the party's replay guard and session check make it count at most once; the last
retry is still inside the message's 30 s lifetime. If it never lands, the party still shows the
game as on until the host uses End for everyone (which this server then acknowledges).
The report is never logged, only its outcome and the HTTP status.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from core import party_protocol

log = logging.getLogger("gamehub.party")

KEYS_ENV = "AVRANA_PARTY_KEYS"
# Games whose server implements the game side. Kept here, not in games/registry.py: the registry
# is pinned catalog metadata (provider/catalog.json), and this is a server capability.
GAMES = ("bluff",)
MAX_BODY = 8192
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
LOOPBACK = ("127.0.0.1", "::1")

PARTY_URL_ENV = "AVRANA_PARTY_URL"      # e.g. http://127.0.0.1:8190 (the party service itself)
ENDED_PATH = "/internal/party-session/v0/ended"
POST_TIMEOUT = 3.0                      # s per attempt
RETRY_DELAYS = (1.0, 2.0, 4.0)          # s; worst case ~19 s, inside the 30 s message lifetime
_warned: set = set()                    # log-once keys


def load_side(slug, keys_dir):
    """The GameSide for `slug`, or None when this server cannot verify its tickets."""
    if not keys_dir:
        return None
    path = os.path.join(keys_dir, "%s.key" % slug)
    if not os.path.exists(path):
        return None
    try:
        return party_protocol.GameSide(party_protocol.read_key(path), slug)
    except (OSError, ValueError):
        # never log the file's contents; the path and the game are enough to fix it
        log.error("[%s] party session key %s is unusable; party sessions are off", slug, path)
        return None


def load_sides(keys_dir, games=GAMES):
    """{slug: GameSide} for the party-session games that have a usable key."""
    sides = {}
    for slug in games:
        side = load_side(slug, keys_dir)
        if side is not None:
            sides[slug] = side
    return sides


def local_unproxied(client_host, headers):
    """True only for a request made on this machine and not relayed by the reverse proxy
    (nginx adds X-Forwarded-For / X-Real-IP), matching the party's own internal routes."""
    return client_host in LOOPBACK and not any(headers.get(h) for h in PROXY_HEADERS)


def party_url(value):
    """The party's base URL from config, or None. Only a plain http origin on a loopback
    address is accepted (the party's internal routes answer nothing else); anything else is
    logged and ignored rather than used."""
    if not value:
        return None
    try:
        u = urlsplit(value.strip())
        host, port = u.hostname, u.port
        ok = (u.scheme == "http" and host is not None and ipaddress.ip_address(host).is_loopback
              and port is not None and not u.username and not u.password
              and u.path in ("", "/") and not u.query and not u.fragment)
    except ValueError:
        ok = False
    if not ok:
        log.error("%s must be a loopback http origin such as http://127.0.0.1:8190; "
                  "`ended` reports are off", PARTY_URL_ENV)
        return None
    return "http://%s:%d" % ("[%s]" % host if ":" in host else host, port)


def post_ended(base_url, message, timeout=POST_TIMEOUT):
    """One POST of an `ended` report. Returns the HTTP status, or None if the party did not
    answer. Blocking: call it off the event loop."""
    req = urllib.request.Request(base_url + ENDED_PATH, method="POST",
                                 data=json.dumps({"message": message}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


async def deliver_ended(base_url, message, slug, outcome):
    """Send one `ended` report with the retry policy above. True once the party accepted it."""
    if base_url is None:
        if slug not in _warned:
            _warned.add(slug)
            log.warning("[%s] party session %s, but %s is not set: the party was not told",
                        slug, outcome, PARTY_URL_ENV)
        return False
    loop = asyncio.get_running_loop()
    status = None
    for attempt, delay in enumerate((0.0,) + tuple(RETRY_DELAYS)):
        if delay:
            await asyncio.sleep(delay)
        status = await loop.run_in_executor(None, post_ended, base_url, message)
        if status == 200:
            log.info("[%s] party session %s: reported", slug, outcome)
            return True
        if status is not None and status < 500:
            log.warning("[%s] party session %s: the party refused the report (HTTP %d)",
                        slug, outcome, status)
            return False
    log.warning("[%s] party session %s: gave up reporting after %d attempts (last: %s)",
                slug, outcome, attempt + 1, "HTTP %d" % status if status else "no answer")
    return False
