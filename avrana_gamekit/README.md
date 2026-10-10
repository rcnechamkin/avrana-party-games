# avrana_gamekit: experimental plumbing for a native Avrana game

**EXPERIMENTAL. Not an SDK, not "SDK v0", not frozen.** No version promise: names, signatures and
module paths here may change or disappear without notice (AVR-38). It exists so the next native
game does not copy the Party boundary again and so an outsider can read one small package instead
of Checkers and the stand-in side by side. Checkers does **not** use it yet (follow-up).

**Freeze gates, all still open:** Checkers moved onto the kit; review of the four-human BLUFF
evidence (AVR-27); Spades boundary validation (Party ADR 0014). Until then nothing here is a
public contract. The contracts that *are* pinned are the Party's two vendored files, which the kit
imports and never copies or edits: `core/party_protocol.py` (the signed session protocol) and
`core/party_result.py` (`avrana.game-result/v1`).

Standard library only (a test enforces it). Start with the worked example, [Hello Party](../hello_party/README.md).

## Core primitives and optional helpers

| Module | Is | Kind |
|---|---|---|
| `jsonio.py` | strict, bounded JSON in (exact keys, no duplicate keys, no NaN, no lone surrogates, 16 KiB), `Reply` out | core |
| `party.py` | the Party boundary: control-traffic test, launch / end / ticket redeem, per-seat tokens, the signed `ended`, the result builder, retrying delivery | core |
| `runtime.py` | HTTP server on the inherited fd-3 Unix socket, or on a loopback port for development only; the key; idle stop; SIGTERM | core |
| `app.py` | `GameApp`: joins the three above into the routes a game page and Party Core talk to; the game plugs in a session class and actions | core |
| `helpers.py` | serve a fixed set of files; the page's Content-Security-Policy | **optional** (nothing in the core imports it) |
| `devparty.py` | a stand-in for the Party's half (mints launch / end / tickets, receives `ended`, checks the result) and a `Phone` client | **development only** |

What the kit guarantees (each is tested, in `tests/test_gamekit.py` and `tests/test_hello_party.py`):

- a request with a proxy header **present at all, even empty**, is never control traffic (the
  stand-in game once let an empty `X-Forwarded-For` through);
- a ticket or token that is not plain ASCII is refused, never an exception (the vendored
  `GameSide.present` raises `UnicodeEncodeError` on a non-ASCII ticket: the kit guards it);
- tickets are single use; a token is stable per participant and session (a reload gets the same
  seat); a ticket saying "player" for a participant the launch roster never seated is refused;
- the client only ever gets `session.view(participant)`, the one projection built for that
  participant; the kit never sees a device or member id, only participant ids, names and roles;
- request bodies are bounded and strict; the server never logs a URL, token or ticket;
- a result is checked with the Party's own check before it is sent; a refused result is dropped,
  the end is still reported;
- the process stops itself when idle (no session, no report pending) and on SIGTERM; a session
  never expires by itself.

What it does **not** do: persistence (a restart loses the session), WebSockets (the simplest event
mechanism is a long poll), the Host question (`ask_host` / `host_is` in the vendored protocol are
not wrapped), a lobby or any Party Core behavior, per-game resource limits, or the systemd sandbox.

## Running a game

On the appliance (what systemd does): fd 3 is an `AF_UNIX` listening socket (`LISTEN_PID`,
`LISTEN_FDS=1`), `$AVRANA_PARTY_KEYS/<slug>.key` is the key, `$AVRANA_PARTY_SOCKET` is where
`ended` goes, `$AVRANA_PARTY_ORIGIN` the Party's browser origin.

On a laptop (any OS; **development only**, an explicit opt-in that is refused if any of those
variables is present):

```text
python -m <your_game> --dev-tcp 8765 --dev-key-file .dev/game.key [--dev-party 127.0.0.1:8190] [--dev-origin http://127.0.0.1:8190]
```

It listens on `127.0.0.1` only, creates the key file if missing, prints `listening http://127.0.0.1:PORT/games/<slug>/`
and reports `ended` to `--dev-party` (nowhere if absent).

## A game, in short

```python
from avrana_gamekit import helpers, runtime
from avrana_gamekit.app import GameApp, Conflict, Declined, Finish
from avrana_gamekit.jsonio import bounded

class Session:            # your rules: no sockets, no Party
    def __init__(self, roster): ...        # raise Declined("sentence") if you cannot host it
    v, over = 1, False                     # bump v on every visible change
    def view(self, participant): ...       # THIS participant's projection (None: a watcher)
    def finished(self): return Finish("cooperative", ((pid, "won"), ...), "mygame.result/v1", {...})

def make_app(key, report, party_origin, **options):
    return GameApp("mygame", "mygame-0.1", key, report, Session,
                   {"act": ({"text": bounded(40)}, lambda session, participant, text: ...)},
                   helpers.load_files(FILES), party_origin, **options)

def main(argv=None): return runtime.run("mygame", make_app, argv)
```

## Testing a game without a Pi

`avrana_gamekit.devparty.DevParty` plays the Party: it signs launch and end messages with the
vendored protocol, mints tickets, receives `ended` on loopback (or a Unix socket) and applies the
Party's result check; `Phone` plays a browser. `hello_party/conformance.py` is a worked lifecycle.
It is a stand-in, not Party Core: the proof against the real implementation is
`tests/test_hello_party_cross_repo.py`, which starts the real Party service.

## Follow-ups (not done)

Move Checkers onto the kit (and delete the copies in `checkers/party.py`); wrap the Host question;
decide who owns `build` derivation (D15); a conformance test that is generic over games rather than
Hello-specific; WebSocket transport if a game needs it. See
[the Checkers findings](../docs/findings/2026-10-07-checkers-native-findings.md) for the evidence
base and decisions D1 to D15.
