"""Avrana party session v0, game side, for BLUFF: completion, abandonment, end and return (AVR-24).

What BLUFF reports (ADR 0006 `ended`, rcnechamkin/avrana-party):
  * completed  - the table played to BLUFF's own end: one seat left standing (game_end, winner).
  * abandoned  - the game stopped by BLUFF's own abandonment rules before anyone won: the empty
                 table timed out, the last one here used End game, a newcomer took over an
                 empty table, or every seat forfeited at once (no winner).
The report is built and sent by the server only, exactly once per party session, off the lock.
POST /games/<slug>/avrana/session/v0/end (the party ends it for everyone) resets the room at
once and kills that session's tickets. After either, the room goes back to its pre-launch
state: a fresh, empty, non-running lobby with no party session.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import pytest

from core import party_protocol as proto
from core import party_session
from core import session as base_session
from core.net import GameBinding
from games.bluff import game as bluff
from games.bluff.game import BluffSession
from test_party_session import (ALICE, BOB, CAROL, KEY, SID, SID2, FakeWS, connect, http_request,
                                launch, run, settle, shutdown, ticket)

PARTY_URL = "http://127.0.0.1:8190"
A, B = "tokenA_alice", "tokenB_bob"


# ---- BLUFF records how a game finished (pure, fake clock) -----------------------------------

class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def adv(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(time, "time", c)
    monkeypatch.setattr(time, "monotonic", c)    # time passing moves both clocks (AVR-221)
    return c


def table(n=2, bots=0):
    s = BluffSession(rng=random.Random(3))
    for t, name in list(zip((A, B), ("Alice", "Bob")))[:n]:
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing" and s.take_outcome() is None
    return s


def test_a_game_won_by_the_rules_is_completed(clock):
    s = table()
    s.game_action(B, {"t": "leave_game"})
    s.game_action(A, {"t": "act", "action": "income"})
    assert s.phase == "game_end" and s.g["winner"] == A
    assert s.take_outcome() == "completed"
    assert s.take_outcome() is None                      # once


def test_losing_to_test_bots_is_still_completed(clock):
    s = table(n=1, bots=1)
    s.game_action(A, {"t": "leave_game"})
    for _ in range(50):
        if s.phase != "playing":
            break
        due = s.next_bot_action()
        s.run_bot(due[1]) if due else s.tick(s.gen)
    assert s.phase == "game_end" and s.g["winner"] != A
    assert s.take_outcome() == "completed"


def test_end_game_by_the_last_one_here_is_abandoned(clock):
    s = table()
    s.leave(B)
    s.game_action(A, {"t": "end_game"})
    assert s.phase == "lobby" and s.take_outcome() == "abandoned"


def test_an_empty_table_that_times_out_is_abandoned(clock):
    s = table()
    s.leave(A)
    s.leave(B)
    clock.adv(bluff.EMPTY_TABLE_ABANDON + 1)
    s.tick(s.gen)
    assert s.phase == "lobby" and s.take_outcome() == "abandoned"


def test_a_takeover_of_an_empty_table_is_abandoned(clock):
    s = table()
    s.leave(A)
    s.leave(B)
    s.join("tokenS_stranger", "Sam")
    clock.adv(bluff.PAUSE_TAKEOVER + 1)
    s.game_action("tokenS_stranger", {"t": "end_game"})
    assert s.phase == "lobby" and s.take_outcome() == "abandoned"


def test_everyone_forfeiting_at_once_has_no_winner_and_is_abandoned(clock):
    s = table()
    s.game_action(A, {"t": "leave_game"})
    s.game_action(B, {"t": "leave_game"})
    for _ in range(10):
        if s.phase != "playing":
            break
        due = s.next_bot_action()
        s.run_bot(due[1]) if due else s.tick(s.gen)
    assert s.phase == "game_end" and s.g["winner"] is None
    assert s.take_outcome() == "abandoned"


def test_refused_end_game_and_the_results_screen_record_nothing(clock):
    s = table()
    assert s.game_action(A, {"t": "end_game"})[0]["kind"] == "invalid"   # Bob is here
    assert s.take_outcome() is None
    s.game_action(B, {"t": "leave_game"})
    s.game_action(A, {"t": "act", "action": "income"})
    assert s.take_outcome() == "completed"
    clock.adv(base_session.GAME_END_SECONDS + 1)
    s.tick(s.gen)                                        # results screen -> lobby
    assert s.phase == "lobby" and s.take_outcome() is None


def test_an_aborted_countdown_records_nothing(clock):
    s = BluffSession(rng=random.Random(1))
    s.join(A, "Alice")
    s.set_ready(A, True)
    s.start(A)
    s.set_ready(A, False)
    assert s.phase == "lobby" and s.take_outcome() is None


# ---- harness: a party BLUFF room with fast countdown/results and a fake party --------------------

@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(base_session, "COUNTDOWN_SECONDS", 0.05)
    monkeypatch.setattr(base_session, "GAME_END_SECONDS", 0.6)
    monkeypatch.setattr(party_session, "RETRY_DELAYS", (0.01, 0.01))


@pytest.fixture
def party(monkeypatch, fast):
    """Every `ended` POST the game makes: (url, message, lock_was_held)."""
    posts, answers, bindings = [], [], []

    def post(url, message, timeout=None):
        posts.append((url, message, any(b.lock.locked() for b in bindings)))
        return answers.pop(0) if answers else 200
    monkeypatch.setattr(party_session, "post_ended", post)
    return posts, answers, bindings


def binding(party=None, url=PARTY_URL, side=True):
    b = GameBinding("bluff", BluffSession(rng=random.Random(1)),
                    party=proto.GameSide(KEY, "bluff") if side else None, party_url=url)
    if party is not None:
        party[2].append(b)
    return b


def report_of(message):
    return proto.open_message(KEY, message, "ended", "party", proto.ReplayGuard())


async def reports(b):
    await settle()
    while b._party_reports:
        await asyncio.wait_for(asyncio.gather(*list(b._party_reports)), 10)


async def playing(b, *hellos):
    """Connect these hellos, ready everyone, start and wait until BLUFF is playing."""
    pairs = [await connect(b, h) for h in hellos]
    for ws, _ in pairs:
        await ws.inbox.put({"t": "ready", "ready": True})
    await settle()
    await pairs[0][0].inbox.put({"t": "start"})
    for _ in range(50):
        await settle()
        if b.session.phase == "playing":
            break
    assert b.session.phase == "playing"
    return pairs


def fxs(ws, kind):
    return [m for m in ws.sent if m.get("type") == "fx" and m.get("kind") == kind]


async def party_game(b, entries=((ALICE, "Alice", "player"), (BOB, "Bob", "player"))):
    await b.party_launch(launch(b, entries=entries))
    return await playing(b, *({"t": "hello", "ticket": ticket(p)} for p, _, r in entries
                              if r == "player"))


async def win_for_alice(a, c):
    await c[0].inbox.put({"t": "leave_game"})
    await settle()
    await a[0].inbox.put({"t": "act", "action": "income"})
    await settle()


# ---- completed ---------------------------------------------------------------------------------

def test_natural_completion_reports_completed_once_off_the_lock(party, caplog):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        assert b.session.phase == "game_end"             # BLUFF's results screen still runs
        await reports(b)
        assert len(posts) == 1
        url, message, locked = posts[0]
        assert url == PARTY_URL and not locked
        p = report_of(message)
        assert (p["iss"], p["sid"], p["outcome"]) == ("bluff", SID, "completed")
        assert set(p) == {"v", "typ", "iss", "aud", "sid", "iat", "exp", "outcome", "nonce"}
        assert b.party.sid is None                       # no more admissions for that session
        await asyncio.sleep(0.9)                         # results screen ends -> released
        assert len(posts) == 1                           # exactly once
        assert message not in caplog.text
        await shutdown(b, a, c)
    caplog.set_level(logging.DEBUG)
    run(scenario())


def test_party_results_are_held_until_the_host_goes_home_then_released_and_phones_told(party):
    """avrana-party ADR 0011: a Party round's results stay on screen (no timer) until the Party
    Host moves the party on; Party Home is the protocol's end for that finished session."""
    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        old = b.session
        await win_for_alice(a, c)
        assert not a[0].closed and not fxs(a[0], "party_ended")   # results first
        await asyncio.sleep(0.9)                                   # past the old results timer
        assert b.session is old and old.phase == "game_end" and old.deadline is None
        assert b.party_room_sid == SID and not a[0].closed
        await b.party_end(proto.end_message(KEY, "bluff", SID))    # the host's Party Home
        await settle()
        assert b.session is not old and b.session.phase == "lobby"
        assert b.session.players == {} and b.session.g is None
        assert b.player_sockets == {} and b.party_roster == {}
        assert b.party_room_sid is None
        for ws in (a[0], c[0]):
            assert ws.closed
            assert fxs(ws, "party_ended")[-1]["outcome"] == "completed"
        await shutdown(b, a, c)
    run(scenario())


def test_tickets_for_a_completed_session_are_refused(party):
    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and ws.welcome() is None and fxs(ws, "invalid")
        await shutdown(b, a, c)
    run(scenario())


def test_during_the_results_screen_an_unticketed_hello_only_watches(party):
    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        x = await connect(b, {"t": "hello", "token": "tok-browser-0001", "name": "Eve"})
        assert x[0].welcome() == {"type": "welcome", "watch": True}
        await shutdown(b, a, c, x)
    run(scenario())


# ---- abandoned ---------------------------------------------------------------------------------

def test_in_a_party_round_no_player_ends_the_game_on_their_own(party):
    """avrana-party ADR 0011: entering and leaving a Party round are the Party Host's moves.
    BLUFF's own end_game (a lone player, or a newcomer's takeover of an empty table) is refused;
    the host ends it through the Party."""
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await c[0].close()                               # Bob's phone is gone
        await c[1]
        await settle()
        await a[0].inbox.put({"t": "end_game"})          # Alice is the last one here
        await settle()
        assert fxs(a[0], "invalid")[-1]["msg"] == "Only the Party Host can end this game."
        assert b.session.phase == "playing" and posts == []
        assert b.party.sid == SID and b.party_room_sid == SID
        await shutdown(b, a)
    run(scenario())


def test_an_empty_table_timeout_reports_abandoned(party, monkeypatch):
    posts, _, _ = party
    monkeypatch.setattr(bluff, "EMPTY_TABLE_ABANDON", 0.1)

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        for ws, task in (a, c):
            await ws.close()
            await task
        await asyncio.sleep(0.3)
        await reports(b)
        assert [report_of(m)["outcome"] for _, m, _ in posts] == ["abandoned"]
        assert b.session.phase == "lobby" and b.party_room_sid is None
    run(scenario())


# ---- nothing to report --------------------------------------------------------------------------

@pytest.mark.parametrize("side", [True, False])
def test_standalone_games_never_report(party, side):
    posts, _, _ = party

    async def scenario():
        b = binding(party, side=side)
        a, c = await playing(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"},
                             {"t": "hello", "token": "tok-standalone-2", "name": "Yan"})
        await c[0].inbox.put({"t": "leave_game"})
        await settle()
        await a[0].inbox.put({"t": "act", "action": "income"})
        await asyncio.sleep(0.9)
        assert b.session.phase == "lobby" and "tok-standalone-1" in b.session.players
        assert posts == [] and not fxs(a[0], "party_ended") and not a[0].closed
        await shutdown(b, a, c)
    run(scenario())


def test_a_party_session_that_never_starts_is_not_reported_by_the_game(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await a[0].close()
        await a[1]
        await asyncio.sleep(0.2)
        assert posts == [] and b.party.sid == SID        # only the party's End ends it
    run(scenario())


def test_without_a_party_url_nothing_is_sent_and_it_is_logged_once(party, caplog, monkeypatch):
    posts, _, _ = party
    monkeypatch.setattr(party_session, "_warned", set())

    async def scenario():
        b = binding(party, url=None)
        for sid in (SID, SID2):
            await b.party_launch(launch(b, sid=sid))
            a, c = await playing(b, {"t": "hello", "ticket": ticket(ALICE, sid=sid)},
                                 {"t": "hello", "ticket": ticket(BOB, sid=sid)})
            await win_for_alice(a, c)
            await reports(b)
            assert b.party.sid is None                   # the session is over all the same
            await b.party_end(proto.end_message(KEY, "bluff", sid))   # the host's Party Home
            assert b.party_room_sid is None
            await shutdown(b, a, c)
    caplog.set_level(logging.WARNING)
    run(scenario())
    assert posts == []
    assert caplog.text.count(party_session.PARTY_URL_ENV) == 1


# ---- delivery: timeout and retry ----------------------------------------------------------------

def test_a_party_that_does_not_answer_is_retried_then_given_up(party, caplog):
    posts, answers, _ = party
    answers.extend([None, None, None])

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await reports(b)
        await shutdown(b, a, c)
    caplog.set_level(logging.WARNING)
    run(scenario())
    assert len(posts) == 1 + len(party_session.RETRY_DELAYS)
    assert len({m for _, m, _ in posts}) == 1            # the same signed report every time
    assert "gave up" in caplog.text and posts[0][1] not in caplog.text


def test_a_transient_failure_is_retried_until_accepted(party):
    posts, answers, _ = party
    answers.extend([None, 503, 200])

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await reports(b)
        await shutdown(b, a, c)
    run(scenario())
    assert len(posts) == 3


@pytest.mark.parametrize("status", [403, 409])
def test_a_refusal_is_final_and_not_retried(party, status, caplog):
    posts, answers, _ = party
    answers.append(status)

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await reports(b)
        await shutdown(b, a, c)
    caplog.set_level(logging.WARNING)
    run(scenario())
    assert len(posts) == 1 and str(status) in caplog.text


def test_a_slow_party_never_blocks_the_game(party, monkeypatch):
    posts, _, bindings = party
    import threading
    gate = threading.Event()

    def slow_post(url, message, timeout=None):
        posts.append((url, message, any(b.lock.locked() for b in bindings)))
        gate.wait(5)
        return 200
    monkeypatch.setattr(party_session, "post_ended", slow_post)

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await settle()
        assert len(posts) == 1 and not posts[0][2]
        await a[0].inbox.put({"t": "ping"})              # the loop and the lock are free
        await settle()
        assert any(m.get("type") == "pong" for m in a[0].sent)
        async with b.lock:
            pass
        gate.set()
        await reports(b)
        await shutdown(b, a, c)
    run(scenario())


def test_post_ended_really_posts_the_message_and_returns_the_status():
    import http.server
    import threading
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got["path"] = self.path
            got["headers"] = dict(self.headers)
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d" % srv.server_address[1]
        assert party_session.post_ended(url, "aps0.x.y") == 200
        assert got["path"] == "/internal/party-session/v0/ended"
        assert got["body"] == {"message": "aps0.x.y"}
        assert not any(h.lower() in ("x-forwarded-for", "x-real-ip", "forwarded")
                       for h in got["headers"])
    finally:
        srv.shutdown()
        srv.server_close()
    assert party_session.post_ended("http://127.0.0.1:9", "aps0.x.y", timeout=0.5) is None


@pytest.mark.parametrize("value,expected", [
    ("http://127.0.0.1:8190", "http://127.0.0.1:8190"),
    ("http://127.0.0.1:8190/", "http://127.0.0.1:8190"),
    ("http://[::1]:8190", "http://[::1]:8190"),
    (None, None), ("", None),
    ("https://127.0.0.1:8190", None),
    ("http://10.42.0.1:8190", None),
    ("http://party.avrana.net", None),
    ("http://localhost:8190", None),
    ("http://127.0.0.1:8190/party/api", None),
    ("http://127.0.0.1:8190?x=1", None),
    ("http://user:pw@127.0.0.1:8190", None),
    ("http://127.0.0.1:notaport", None),
])
def test_the_party_url_must_be_a_loopback_http_origin(value, expected):
    assert party_session.party_url(value) == expected


# ---- the party ends it: /end --------------------------------------------------------------------

def test_end_resets_the_room_kills_tickets_and_reports_nothing(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        old = b.session
        s = await b.party_end(proto.end_message(KEY, "bluff", SID))
        assert s == SID
        await settle()
        assert b.session is not old and b.session.phase == "lobby" and b.session.players == {}
        assert b.party.sid is None and b.party_room_sid is None and b.party_roster == {}
        assert b.session.deadline is None and b._bot_task is None
        for ws in (a[0], c[0]):
            assert ws.closed and fxs(ws, "party_ended")[-1]["outcome"] == "ended"
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and b.session.players == {}
        await reports(b)
        assert posts == []
    run(scenario())


def test_end_keeps_watchers_connected_and_shows_them_the_empty_lobby(party):
    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b))
        w = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        await b.party_end(proto.end_message(KEY, "bluff", SID))
        await settle()
        assert not w[0].closed and fxs(w[0], "party_ended")
        assert w[0].last_state()["phase"] == "lobby" and w[0].last_state()["players"] == []
        # AVR-129: the spectator view ended with the session; from now on it is a plain watcher
        assert w[0] in b.watch_sockets and w[0] not in b.spectator_sockets
        assert "spectator" not in w[0].last_state()
        await shutdown(b, w)
    run(scenario())


@pytest.mark.parametrize("bad", ["garbage", "bad-base64", "replay", "other-session", "wrong-key",
                                 "launch-as-end", "ended-as-end", "other-game"])
def test_a_refused_end_changes_nothing(party, bad):
    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        first = proto.end_message(KEY, "bluff", SID)
        msg = {
            "garbage": "aps0.nope.nope",
            "bad-base64": "aps0.x.y",
            "replay": first,
            "other-session": proto.end_message(KEY, "bluff", SID2),
            "wrong-key": proto.end_message(bytes(32), "bluff", SID),
            "launch-as-end": launch(b),
            "ended-as-end": proto.ended_message(KEY, "bluff", SID, "completed"),
            "other-game": proto.end_message(KEY, "poker", SID),
        }[bad]
        if bad == "replay":
            b.party.guard.check(proto.unseal(KEY, first, "end", "bluff"))   # already seen
        before = (b.party.sid, b.session, b.session.phase)
        with pytest.raises(proto.Invalid):
            await b.party_end(msg)
        assert (b.party.sid, b.session, b.session.phase) == before
        assert not a[0].closed
        await shutdown(b, a, c)
    run(scenario())


def test_end_during_the_results_screen_of_the_session_that_just_completed(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        assert b.session.phase == "game_end"
        await b.party_end(proto.end_message(KEY, "bluff", SID))    # the host was quicker
        await settle()
        assert b.session.phase == "lobby" and b.party_room_sid is None and a[0].closed
        await reports(b)
        assert len(posts) == 1                          # the completed report still went once
        await shutdown(b, a, c)
    run(scenario())


def test_a_late_end_for_a_released_session_is_acknowledged_but_touches_no_new_game(party):
    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b))
        await b.party_end(proto.end_message(KEY, "bluff", SID))
        z = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        room = b.session
        assert await b.party_end(proto.end_message(KEY, "bluff", SID)) == SID
        assert b.session is room and not z[0].closed and "tok-standalone-1" in room.players
        with pytest.raises(proto.Invalid):
            await b.party_end(proto.end_message(KEY, "bluff", SID2))
        await shutdown(b, z)
    run(scenario())


def test_end_with_no_party_session_ever_is_refused(party):
    async def scenario():
        b = binding(party)
        with pytest.raises(proto.Invalid):
            await b.party_end(proto.end_message(KEY, "bluff", SID))
        with pytest.raises(proto.Invalid):
            await binding(side=False).party_end(proto.end_message(KEY, "bluff", SID))
    run(scenario())


def test_after_end_the_room_is_standalone_again(party):
    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b))
        await b.party_end(proto.end_message(KEY, "bluff", SID))
        z = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        assert z[0].welcome()["token"] == "tok-standalone-1"
        await shutdown(b, z)
    run(scenario())


def test_a_new_launch_during_the_results_screen_starts_clean(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await b.party_launch(launch(b, sid=SID2))
        assert b.party.sid == SID2 and b.party_room_sid == SID2 and b.session.phase == "countdown"
        await asyncio.sleep(0.9)                        # the old results timer is gone
        assert b.party_room_sid == SID2 and b.party.sid == SID2
        await reports(b)
        assert [report_of(m)["sid"] for _, m, _ in posts] == [SID]
        await shutdown(b, a, c)
    run(scenario())


# ---- a browser cannot forge completion ----------------------------------------------------------

def test_watchers_and_browser_tokens_cannot_end_or_report(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        x = await connect(b, {"t": "hello", "token": "tok-browser-0001", "name": "Eve"})
        s = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        for ws, _ in (x, s):
            for verb in ("end_game", "leave_game", "again", "ended", "end"):
                await ws.inbox.put({"t": verb, "outcome": "completed"})
        await settle()
        assert b.session.phase == "playing" and posts == [] and b.party.sid == SID
        await shutdown(b, a, c, x, s)
    run(scenario())


def test_a_player_cannot_end_a_game_others_are_still_in(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        for msg in ({"t": "end_game"}, {"t": "ended", "outcome": "completed"},
                    {"t": "again"}, {"t": "end"}):
            await a[0].inbox.put(msg)
        await settle()
        assert b.session.phase == "playing" and posts == [] and b.party.sid == SID
        await shutdown(b, a, c)
    run(scenario())


# ---- HTTP: the /end route -----------------------------------------------------------------------

@pytest.fixture
def server_with_bluff_party(monkeypatch, party):
    import server
    b = binding(party)
    monkeypatch.setitem(server.bindings, "bluff", b)
    return server, b


def call_end(server, slug, body, **kw):
    path = "/games/%s/avrana/session/v0/end" % slug
    resp = run(server.party_session_end(slug, http_request(path, body, **kw)))
    assert resp.headers.get("cache-control") == "no-store"
    return resp.status_code, json.loads(resp.body)


def test_end_route_is_registered_before_the_static_mount_and_there_is_no_ended_route():
    import server
    paths = [getattr(r, "path", None) for r in server.app.routes]
    route = "/games/{slug}/avrana/session/v0/end"
    assert route in paths and paths.index(route) < paths.index("/games/bluff")
    assert not any(p and "ended" in p for p in paths)      # the game never accepts `ended`


def test_end_route_accepts_a_signed_loopback_end(server_with_bluff_party):
    server, b = server_with_bluff_party
    run(b.party_launch(launch(b)))
    status, body = call_end(server, "bluff", {"message": proto.end_message(KEY, "bluff", SID)})
    assert (status, body) == (200, {"ok": True})
    assert b.party.sid is None and b.party_room_sid is None


@pytest.mark.parametrize("client,headers", [
    (("10.42.0.23", 50000), ()),
    (("127.0.0.1", 50000), (("X-Forwarded-For", "10.42.0.23"),)),
    (("127.0.0.1", 50000), (("X-Real-IP", "10.42.0.23"),)),
    (("127.0.0.1", 50000), (("Forwarded", "for=10.42.0.23"),)),
])
def test_end_route_refuses_anything_not_local_and_unproxied(server_with_bluff_party,
                                                            client, headers):
    server, b = server_with_bluff_party
    run(b.party_launch(launch(b)))
    status, body = call_end(server, "bluff", {"message": proto.end_message(KEY, "bluff", SID)},
                            client=client, headers=headers)
    assert status == 403 and body["ok"] is False
    assert b.party.sid == SID


@pytest.mark.parametrize("body", [{"message": "aps0.x.y"}, {}, {"message": 7}, b"not json",
                                  b"[]"])
def test_end_route_refuses_a_bad_message(server_with_bluff_party, body):
    server, b = server_with_bluff_party
    run(b.party_launch(launch(b)))
    status, out = call_end(server, "bluff", body)
    assert status in (400, 403) and out["ok"] is False
    assert b.party.sid == SID


def test_end_route_refuses_an_oversized_body(server_with_bluff_party):
    server, b = server_with_bluff_party
    run(b.party_launch(launch(b)))
    status, out = call_end(server, "bluff", {"message": "x" * 20000})
    assert status == 413 and out["ok"] is False and b.party.sid == SID


def test_end_route_is_404_for_a_game_without_a_party_side():
    import server
    for slug in ("poker", "no-such-game"):
        path = "/games/%s/avrana/session/v0/end" % slug
        resp = run(server.party_session_end(slug, http_request(path, {"message": "aps0.x.y"})))
        assert resp.status_code == 404


def test_the_server_reads_the_party_url_from_the_environment():
    import server
    assert server.party_url == party_session.party_url(
        __import__("os").environ.get(party_session.PARTY_URL_ENV))


# ---- Party state decides roles across launches (integration of AVR-22/23/24) ----------------------
# The party's roster is authoritative: whoever watched under the last session, a new launch lets
# every phone come back with a fresh ticket and the new roster decides its role. One party
# session is one play-through; a rematch is a new session.

def test_a_later_launch_drops_every_watcher_so_the_new_roster_decides(party):
    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b, entries=((ALICE, "Alice", "player"),)))
        w = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        tv = await connect(b, {"t": "hello", "watch": True})
        assert w[0].welcome() == {"type": "welcome", "watch": True, "spectator": True}
        await b.party_launch(launch(b, sid=SID2, entries=((CAROL, "Carol", "player"),)))
        await settle()
        assert w[0].closed and tv[0].closed and b.watch_sockets == set() == b.spectator_sockets
        p = await connect(b, {"t": "hello", "ticket": ticket(CAROL, sid=SID2)})
        assert not p[0].welcome().get("watch") and p[0].welcome()["pid"]
        assert [q.name for q in b.session.humans()] == ["Carol"]
        await shutdown(b, w, tv, p)
    run(scenario())


def test_a_watcher_left_after_an_end_is_a_player_in_the_next_launch(party):
    async def scenario():
        b = binding(party)
        await b.party_launch(launch(b, entries=((ALICE, "Alice", "player"),)))
        w = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        await b.party_end(proto.end_message(KEY, "bluff", SID))
        await settle()
        assert not w[0].closed                                   # watchers see the empty lobby
        await b.party_launch(launch(b, sid=SID2, entries=((CAROL, "Carol", "player"),)))
        await settle()
        assert w[0].closed                                       # ... until the next launch
        p = await connect(b, {"t": "hello", "ticket": ticket(CAROL, sid=SID2)})
        assert proto.game_token(KEY, SID2, CAROL) in b.session.players
        await shutdown(b, w, p)
    run(scenario())


def test_a_rematch_is_a_new_party_session_with_a_fresh_table(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await asyncio.sleep(0.9)                                 # results are held for the party
        assert b.party_room_sid == SID and b.session.phase == "game_end"
        await b.party_launch(launch(b, sid=SID2))                # the host's Play again
        assert b.party_room_sid == SID2 and b.session.g is None
        assert not any(p.connected for p in b.session.players.values())   # seated, not here yet
        old, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert old.closed and old.welcome() is None               # the first play-through's ticket
        a2, c2 = await playing(b, {"t": "hello", "ticket": ticket(ALICE, sid=SID2)},
                               {"t": "hello", "ticket": ticket(BOB, sid=SID2)})
        assert a2[0].welcome()["pid"] and c2[0].welcome()["pid"]
        await win_for_alice(a2, c2)
        await reports(b)
        assert [report_of(m)["sid"] for _, m, _ in posts] == [SID, SID2]
        assert [report_of(m)["outcome"] for _, m, _ in posts] == ["completed", "completed"]
        await shutdown(b, a, c, a2, c2)
    run(scenario())


# ---- deployment config: party sessions only when both halves are configured (decision 6) ----------

def test_party_sessions_need_both_the_key_and_the_party_url(tmp_path, caplog):
    proto.write_key(str(tmp_path / "bluff.key"), KEY)
    env = {party_session.KEYS_ENV: str(tmp_path), party_session.PARTY_URL_ENV: "http://127.0.0.1:8191"}
    sides, url = party_session.configure(env)
    assert set(sides) == {"bluff"} and url == "http://127.0.0.1:8191"
    with caplog.at_level(logging.ERROR):
        sides, url = party_session.configure({party_session.KEYS_ENV: str(tmp_path)})
    assert sides == {} and url is None                 # half-wired: not advertised, not launchable
    assert party_session.PARTY_URL_ENV in caplog.text
    sides, url = party_session.configure({party_session.KEYS_ENV: str(tmp_path),
                                          party_session.PARTY_URL_ENV: "http://example.com:80"})
    assert sides == {}
    assert party_session.configure({}) == ({}, None)   # standalone, nothing logged as an error


def test_the_tracked_systemd_drop_in_configures_both_halves():
    from pathlib import Path
    conf = (Path(__file__).resolve().parent.parent / "deploy" / "avrana-party-session.conf").read_text()
    env = dict(line.split("=", 2)[1:] for line in conf.splitlines() if line.startswith("Environment="))
    assert set(env) == {party_session.KEYS_ENV, party_session.PARTY_URL_ENV}
    assert party_session.party_url(env[party_session.PARTY_URL_ENV]) == env[party_session.PARTY_URL_ENV]
    assert env[party_session.KEYS_ENV].startswith("/etc/")
