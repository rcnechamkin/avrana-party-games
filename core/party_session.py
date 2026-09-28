"""core.party_session — the game side of Avrana's party session protocol v0 (AVR-22).

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

Not here yet (AVR-24): /end, and reporting `ended` to the party.
"""

from __future__ import annotations

import logging
import os

from core import party_protocol

log = logging.getLogger("gamehub.party")

KEYS_ENV = "AVRANA_PARTY_KEYS"
# Games whose server implements the game side. Kept here, not in games/registry.py: the registry
# is pinned catalog metadata (provider/catalog.json), and this is a server capability.
GAMES = ("bluff",)
MAX_BODY = 8192
PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")
LOOPBACK = ("127.0.0.1", "::1")


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
