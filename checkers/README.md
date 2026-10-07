# Checkers: the first native game process

Two people play American checkers on their phones. It is the first game here that is not a module
of the LAN Games fork: a separate Python process, standard library only, that Party Core launches
and ends (AVR-238; Party ADR 0014, ADR 0016 section 5). Its rules are the fork's, adapted: see
[NOTICE](NOTICE.md). Party's half (contract, grant, catalog entry, test harness, browser test, field
proof) is in avrana-party and is not described here.

One match at a time. The first player on the launch roster is white and moves first; the second is
black. Anyone else on the roster watches. A capture is compulsory and a move is one complete jump
sequence. There is no timer, draw offer, takeback or bot: a player who goes away leaves the game
waiting, and the Host can end it from Party. A player may resign at any time. The page is phone
first; Party's bridge is the only way it reaches Party.

## How Party starts it

```text
cd <this repository>  &&  python3 -m checkers
```

| It is handed | Where |
|---|---|
| its listening socket, an `AF_UNIX` stream socket | file descriptor 3 (`LISTEN_PID`, `LISTEN_FDS=1`) |
| its key, `checkers.key` | the directory in `$AVRANA_PARTY_KEYS` |
| Party's internal socket, where it reports `ended` | `$AVRANA_PARTY_SOCKET` |
| Party's browser origin (optional) | `$AVRANA_PARTY_ORIGIN`, told to the page; if absent or not an origin the page says to open the game from Party Home |

It opens no IP socket (the unit allows `AF_UNIX` only), resolves no name, writes nothing to disk and
sets no cookie. It reads files only from this checkout. The grant's `runtime.command` is
`["/usr/bin/python3", "-m", "checkers"]` with the checkout as its working directory.

Under `/games/checkers/`:

| Route | From | Does |
|---|---|---|
| `POST avrana/session/v0/launch`, `.../end` `{"message"}` | Party Core, never proxied | start the match from the roster / drop it |
| `GET /`, `web/*`, `onboarding.json`, `api/party` | the phone | the page, its files (the Party bridge shim is the repository's `web/avrana-party-bridge.js`, unchanged), the rules, Party's origin |
| `POST api/redeem {ticket}` | the phone | trade a single-use Party ticket for a seat |
| `POST api/poll {token, since}` | the phone | long poll, 25 s, for the next version of your view |
| `POST api/move {token, v, move}`, `api/resign {token}` | a player | play, or give up; a refused move is a 409 with the current view |

A launch with other than two players is refused (409) and the Party shows the sentence. When the
game is over the process builds the `avrana.game-result/v1`, closes the session, and reports `ended`
over the internal socket after releasing its lock, again after 1, 2 and 4 seconds if nobody answers
(the message lives 30 s). The finished board stays readable until Party releases the match.

## What is in the box

| File | Is |
|---|---|
| `rules.py` | the rules, pure functions (adapted from the fork) |
| `session.py` | one match: seats, versions, each seat's own view, moves, resignation, how it ends |
| `party.py` | the Party boundary: strict JSON, the HTTP server on the inherited socket, the `ended` report, the result |
| `server.py`, `__main__.py` | the routes, the lock, the tokens, `main` |
| `web/` | the page (`index.html`, `checkers.js`, `app.mjs`, `board.mjs`, `checkers.css`), `onboarding.json` (what Party shows as the rules), `icon.svg` |

Tests: `python -m pytest -q tests/test_checkers_*.py` (the Unix-socket process test needs Linux, the
page tests need Node), and `node --test tests/checkers_board_test.mjs`. No browser is started; the
two-phone browser test is Party's.

## Before there is an SDK (AVR-37, AVR-38)

Party's [`party_protocol.py` and `party_result.py`](../provider/README.md) are used as they are,
vendored byte for byte, because they are today's public boundary and not an SDK; their module paths
may change. Everything else a native game needs is written in `party.py` and deliberately not
shared: Checkers and the stand-in game in avrana-party each have it, and two copies are evidence,
not yet a reason to freeze an interface. The pull request for AVR-238 lists what overlaps.

## Known limits

- The match is in memory. A crash or restart loses it; the Party shows the session as running until
  the Host ends it.
- After `ended` the session admits no more tickets, so a phone that reloads at the results sees no
  board. Party's results are where the game is read afterwards.
- The process does not stop itself when idle (ADR 0016 section 4 asks games to): nothing says
  after how long, or on what signal.
- `BUILD` in `party.py` (what `game.build` says) is a constant to change by hand with the rules.
- No reconnect timer: a player who never comes back keeps the game waiting for the Host to end it.
