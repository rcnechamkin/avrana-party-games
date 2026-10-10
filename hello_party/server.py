"""Hello Party's process: `python -m hello_party` (the appliance model) or with `--dev-tcp` (a
laptop). EXPERIMENTAL (AVR-38). All the Party plumbing is avrana_gamekit's; this file only says
what the game is: its id, its one action and the files its page is made of.
"""

from __future__ import annotations

import os
from pathlib import Path

from avrana_gamekit import helpers, runtime
from avrana_gamekit.app import GameApp
from avrana_gamekit.jsonio import bounded

from hello_party.session import Session

GAME = "hello"
BUILD = "hello-0.1.0"
BASE = f"/games/{GAME}"

WEB = Path(__file__).resolve().parent / "web"
SHARED = Path(__file__).resolve().parent.parent / "web"      # the repository's vendored bridge shim
FILES = {                                                      # exactly these are served
    "/": (WEB / "index.html", helpers.HTML),
    "/onboarding.json": (WEB / "onboarding.json", helpers.JSON),
    "/web/hello.mjs": (WEB / "hello.mjs", helpers.JS),
    "/web/hello.css": (WEB / "hello.css", helpers.CSS),
    "/web/icon.svg": (WEB / "icon.svg", helpers.SVG),
    # the Party's bridge shim, vendored unchanged and served from this game's own origin
    "/web/avrana-party-bridge.js": (SHARED / "avrana-party-bridge.js", helpers.JS),
}
ACTIONS = {"greet": ({"text": bounded(200)}, lambda session, participant, text: session.greet(participant, text))}


def make_app(key, report, party_origin, **options):
    return GameApp(GAME, BUILD, key, report, Session, ACTIONS, helpers.load_files(FILES), party_origin,
                   page_headers=helpers.page_headers(party_origin), **options)


def main(argv=None, environ=os.environ):
    return runtime.run(GAME, make_app, argv, environ)
