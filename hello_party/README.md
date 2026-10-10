# Hello Party: a deliberately boring reference game

**EXPERIMENTAL (AVR-38). Not an SDK, not "SDK v0", not frozen.** It shows, in under 300 lines of
game code and one small page, everything a native Avrana game does, built only on
[`avrana_gamekit`](../avrana_gamekit/README.md) and the Party's vendored protocol files. Freeze
gates still open: Checkers integrated on the kit; review of the four-human BLUFF evidence
(AVR-27); Spades boundary validation (Party ADR 0014). It is **not deployed** and is **not in any
product catalog**: its Game Contract is marked `test_only`.

## The game

One to six players. Each seat is dealt a **secret word** that only that seat is ever sent. Everyone
shares a **greeting board**. Each seat says hello once; when all have, the game is over and the
result is cooperative (everyone `won`, `data` = `{"greetings": n}`).

| AVR-38 lifecycle point | Where it is |
|---|---|
| join / admission | `redeem`: a seated player's single-use ticket buys a seat; a "player" ticket for someone the roster never seated is refused; a late member (spectator ticket) watches |
| private view | `Session.view(participant)`: a secret in the viewer's own view only; a watcher gets none; no ids or tokens in any view |
| broadcast (shared state) | the greeting board, delivered by long poll to every seat |
| input | `POST api/greet {"token","text"}`: validated by the server (1 to 40 printable characters, once per seat) |
| start | the Party's signed launch; the roster seats the players |
| end | finishing: a signed `ended` with a valid `avrana.game-result/v1`; the Host ending it through the Party: no result |
| reconnect / reload | a fresh ticket returns the same seat, token, secret and board |
| shutdown | idle exit (no session) and SIGTERM |

## Run it on your laptop (Windows, macOS, Linux; no Pi, no Party Core, no edits to Party)

From the root of this repository (Python 3.10 or newer, standard library only):

```text
python -m hello_party.conformance
```

starts the game as a real process on a free loopback port, plays the Party and four phones against
it, and prints one `ok` line per check (about 50). That is the whole lifecycle in a few seconds.

To run the game by itself and poke it (`curl`, your own client):

```text
python -m hello_party --dev-tcp 8765 --dev-key-file .dev/hello.key
```

It prints `listening http://127.0.0.1:8765/games/hello/`. `--dev-tcp` is a development-only
opt-in; it is refused when the appliance environment (`LISTEN_PID`, `LISTEN_FDS`,
`AVRANA_PARTY_KEYS`, `AVRANA_PARTY_SOCKET`) is present. Add `--dev-party HOST:PORT` to say where
`ended` goes (the real Party service's loopback port, or a `DevParty`).

The page needs a Party to hand it a ticket (it embeds the Party's bridge through the vendored
shim, `web/avrana-party-bridge.js`, unchanged): opened by hand it says so. To see it in a phone
browser you need the real Party service running locally and registered with a game entry; that
path is described in [Adding a game](https://github.com/rcnechamkin/avrana-party/blob/main/docs/runbooks/add-a-game.md)
and has not been exercised through a browser by this slice.

**Known limits:** the Hello page has not been opened in a browser and has no page-logic test (CI only
syntax-checks it). Windows was exercised locally and Linux in CI; macOS is expected to work but is
untested. The "real Party test" step needs a Party checkout with a local, uncommitted copy of the
contract and has not been exercised outside CI.

## Test it

```text
python -m pytest -q tests/test_gamekit.py tests/test_hello_party.py
```

| Test | Runs |
|---|---|
| `tests/test_gamekit.py`: JSON bounds, the two defect cases, config, server bounds, idle stop, another game on the kit | every OS |
| `tests/test_hello_party.py`: rules, admission, isolation, validation, finish with result, Host end, reconnect, a real process over loopback, `--dev-tcp` guards | every OS |
| `tests/test_hello_party.py`: the real process on an inherited fd-3 Unix socket; no IP socket; SIGTERM | Linux only (skipped on Windows: no `AF_UNIX`) |
| `tests/test_hello_party_cross_repo.py`: the **real Party service** launches Hello Party, looks up its participants (the HTTP ticket route is not exercised), accepts its result, ends it for the Host | with a Party checkout (`AVRANA_PARTY_REPO`, or a sibling `../avrana-party`); CI only |

The cross-repository test needs the paired Party branch for `contracts/games/hello.json` (a test
fixture; nothing about Hello Party is in Party Core).

## Files

```text
hello_party/
  session.py            the rules (pure; no sockets, no Party)
  server.py, __main__.py   the game's id, its one action, its files; python -m hello_party
  conformance.py        the lifecycle against a real process (python -m hello_party.conformance)
  game-contract.json    its Game Contract (avrana.game/v0); Party keeps a test fixture copy
  web/                  index.html, hello.mjs, hello.css, icon.svg, onboarding.json
```

## Getting a game like this onto an appliance

Honestly: **an outsider cannot do it alone today.** What you can do on your own: everything above,
including the proof against the real Party. What needs a maintainer or the owner:

1. the Game Contract merged into the Party repository (`contracts/games/<slug>.json`; Party Core
   reads game facts only from there, there is no external contracts directory);
2. a grant for the game in the appliance profile (`contracts/appliances/avrana-pi4.json`) with its
   `runtime.command` and `working_directory`;
3. the game's code under a root-owned release path on the appliance;
4. `provision-game <slug>` as root on the appliance (key, systemd instance, registry entry).

See Party's `docs/runbooks/add-a-game.md` and `provision-game.md`. None of it was done for Hello
Party, on purpose.
