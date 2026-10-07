"""Checkers as a native Avrana game process (AVR-238).

Run as `python3 -m checkers` from the repository root. It is not a module of the LAN Games
fork: it imports nothing from `games/`, `server.py` or the rest of `core/` except the two vendored
Party protocol files (`core/party_protocol.py`, `core/party_result.py`), which are stdlib only.
See README.md for how Party Core launches it.

  rules.py    the rules of American checkers, pure functions (adapted from the fork; NOTICE.md)
  session.py  one match: two seats, a turn, a version counter and each seat's own view
  party.py    the Party boundary: strict JSON, the HTTP server on the inherited socket, the
              Unix-socket report of `ended`
  server.py   the routes, and `main()`
  web/        the phone page (plain ES modules), the rules content and the icon
"""
