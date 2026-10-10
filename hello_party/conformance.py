"""Hello Party's lifecycle, checked end to end against a REAL game process. EXPERIMENTAL (AVR-38).

    python -m hello_party.conformance

starts `python -m hello_party --dev-tcp` on a free loopback port with a throwaway key, plays the
Party (avrana_gamekit.devparty: launch, tickets, end, the receiver of `ended`) and the phones, and
checks every step of the lifecycle, printing one line per check. It needs no Pi and no Party Core,
and runs on Windows, macOS and Linux. The same file is the test (tests/test_hello_party_conformance.py).

A passing run means: this game, over real HTTP, behaves as a Party game must toward a Party that
speaks the vendored protocol. It does not prove the real Party's own side; the cross-repository
test does that (tests/test_hello_party_cross_repo.py).
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from core import party_protocol as protocol
from avrana_gamekit.devparty import DevParty, spawn_dev_game

MODULE = "hello_party"
GAME = "hello"


def _wait(check, timeout=10.0, what="the condition"):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


def lifecycle(dev, say=print):
    """Play the whole lifecycle against a running game. `dev` is a DevParty pointed at it and
    already started (so `ended` can arrive). Raises AssertionError at the first thing that is wrong."""
    def ok(condition, what):
        assert condition, what
        say(f"  ok  {what}")

    # -- a launch the game cannot host is refused with a sentence
    for people in ({}, {f"P{i}": "player" for i in range(7)}):
        s = dev.launch(people)
        ok(s.launched[0] == 409 and s.launched[1]["message"], f"{len(people)} players: refused with a sentence")
    # -- control traffic is Party Core's alone
    msg = protocol.launch_message(dev.key, GAME, "session-" + "e" * 32, [])
    for headers in ({"X-Forwarded-For": "10.0.0.5"}, {"X-Forwarded-For": ""}, {"X-Real-IP": ""}, {"Forwarded": ""}):
        status, _ = dev._post("/avrana/session/v0/launch", {"message": msg}, headers)
        ok(status == 404, f"launch with proxy header {list(headers.items())[0]!r} is not found")
    status, _ = dev._post("/avrana/session/v0/launch", {"message": "aps0.x.y"})
    ok(status == 403, "an unsigned launch is refused")

    # -- admission
    session = dev.launch({"Ana": "player", "Ben": "player", "Cy": "spectator"})
    ok(session.launched[0] == 200, "Party launches Ana, Ben (players) and Cy (spectator)")
    ana, ben, cy = (dev.phone(session, n) for n in ("Ana", "Ben", "Cy"))
    ok(ana.redeem()[0] == 200 and ben.redeem()[0] == 200, "seated players redeem their tickets")
    ok(ana.view["seat"] == 0 and ben.view["seat"] == 1, "seats follow the roster order")
    ticket = dev.ticket(session, "Ana")
    ok(ana.redeem(ticket)[0] == 200 and ana.redeem(ticket)[0] == 403, "a ticket is single use")
    ok(dev.phone(session, "Ana").redeem("x" * 120)[0] == 403, "a made-up ticket is refused")
    ok(dev.phone(session, "Ana").redeem("aps0.éé.é")[0] == 403, "a non-ASCII ticket is refused, not an error")
    ok(dev.phone(session, "Ana").redeem(ticket + "x")[0] == 403, "an altered ticket is refused")
    zed = dev.join_late(session, "Zed")
    forged = protocol.mint_ticket(dev.key, GAME, session.sid, zed, "player")
    ok(dev.phone(session, "Zed").redeem(forged)[0] == 403, "an unseated device (not on the roster) gets no seat")
    ok(cy.redeem()[0] == 200 and cy.view["seat"] is None, "a spectator on the roster watches")
    dee = dev.join_late(session, "Dee")
    late = dev.phone(session, "Dee")
    ok(late.redeem()[0] == 200 and late.view["seat"] is None, "a late member spectates")

    # -- private views never leak
    secrets_ = [ana.view["you"]["secret"], ben.view["you"]["secret"]]
    ok(secrets_[0] != secrets_[1], "each seat has its own secret word")
    blob = lambda phone: json.dumps(phone.view)
    ok(secrets_[1] not in blob(ana) and secrets_[0] not in blob(ben), "a seat's view holds no other seat's secret")
    ok(all(w not in blob(cy) + blob(late) for w in secrets_) and cy.view["you"] is None,
       "a watcher's view holds no secret at all")
    ok(not any(p in blob(ana) + blob(cy) for p in session.participants.values()) and ana.token not in blob(ben),
       "no view carries a participant id or a token")

    # -- input is validated by the server
    for text in ("", " ", "x" * 41, "zero​width", "bell\u0007"):
        status, body = ana.act("greet", text=text)
        ok(status == 409 and body["error"] == "bad_text", f"greeting {text!r:.12} is refused")
    ok(ana.post("greet", {"token": ana.token})[0] == 400, "a body missing a field is refused")
    ok(ana.post("greet", {"token": ana.token, "text": "hi", "extra": 1})[0] == 400, "a body with an extra field is refused")
    ok(ana.post("greet", {"token": "é" * 5, "text": "hi"})[0] == 403, "a non-ASCII token is refused, not an error")
    ok(ana.post("greet", {"token": "nope", "text": "hi"})[0] == 403, "an unknown token is refused")
    ok(cy.act("greet", text="hi")[0] == 403, "a watcher cannot greet")

    # -- shared state and the long poll
    ok(ana.act("greet", text="  hello   there ")[0] == 200, "Ana says hello")
    status, body = ben.poll(since=ben.view["v"])
    ok(status == 200 and [e["text"] for e in ben.view["board"]] == ["hello there"], "Ben's poll returns the shared board")
    ok(cy.poll(since=0)[0] == 200 and len(cy.view["board"]) == 1, "so does the watcher's")
    ok(ana.act("greet", text="again")[1]["error"] == "already", "a second hello from one seat is refused")

    # -- reconnect: a reload brings a fresh ticket and the same seat
    again = dev.phone(session, "Ana")
    ok(again.redeem()[0] == 200 and again.token == ana.token and again.view["seat"] == 0, "a reload returns the same seat and token")
    ok(again.view["you"]["secret"] == secrets_[0] and len(again.view["board"]) == 1, "and the same secret and board")

    # -- finish: everyone greeted -> a signed `ended` with a valid result
    ok(ben.act("greet", text="hi Ana")[0] == 200 and ben.view["over"], "Ben says hello; the game is over")
    _wait(lambda: session.ended is not None, what="the game's `ended`")
    payload, verdict = session.ended
    ok(payload["outcome"] == "completed" and verdict == "accepted", "the game reported `ended` and the Party accepted the result")
    res = payload["result"]
    ok(res["schema"] == "avrana.game-result/v1" and res["mode"] == "cooperative"
       and {e["participant"]: e["standing"] for e in res["standings"]} == {session.participants["Ana"]: "won", session.participants["Ben"]: "won"}
       and res["data"] == {"greetings": 2}, "the result: cooperative, both won, 2 greetings")
    ok(dev.phone(session, "Ana").redeem()[0] in (403, 409), "no ticket is admitted once the session has ended")
    ok(dev.end(session)[0] == 200, "the Party's end after `ended` is acknowledged")

    # -- the Host ends a session: no result
    session2 = dev.launch({"Ana": "player", "Ben": "player"})
    a2 = dev.phone(session2, "Ana")
    ok(session2.launched[0] == 200 and a2.redeem()[0] == 200, "a new session launches")
    count = len(dev.reports)
    ok(dev.end(session2)[0] == 200, "the Host ends it through the Party")
    ok(a2.poll(since=0)[0] == 403, "its seats are gone")
    ok(dev.phone(session2, "Ben").redeem()[0] in (403, 409), "its tickets buy nothing")
    time.sleep(0.2)
    ok(len(dev.reports) == count and session2.ended is None, "an ended-by-Host session reports no result")


def main(say=print):
    with tempfile.TemporaryDirectory() as tmp:
        key_path = Path(tmp) / "hello.key"
        key = protocol.new_key()
        protocol.write_key(str(key_path), key)
        dev = DevParty(GAME, "http://127.0.0.1:1/games/hello", key)
        address = dev.start()
        proc, url = spawn_dev_game(MODULE, key_path, address)
        dev.point_at(url)
        say(f"Hello Party at {url}/ ; fake Party receiving `ended` at {address[0]}:{address[1]}")
        try:
            lifecycle(dev, say)
        finally:
            proc.terminate()
            proc.wait(10)
            dev.stop()
    say("conformance: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
