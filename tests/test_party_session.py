"""Avrana party session v0, game side, for BLUFF (AVR-22; ADR 0006 in rcnechamkin/avrana-party).

Launch with a signed roster, admission by Party ticket in the WebSocket hello, a stable game token
per participant, browser-minted `wc-token` ignored while a party session runs, and the
capability advertised only when this server can really verify tickets. Completion, end and
`ended` reporting (AVR-24) are in test_party_session_end.py and test_party_session_cross_repo.py.
"""
from __future__ import annotations

import asyncio
import time
import hashlib
import json
import logging
import random
from pathlib import Path

import pytest
from fastapi import WebSocketDisconnect
from starlette.requests import Request

from core import party_protocol as proto
from core import party_session
from core.net import GameBinding
from games.bluff.game import BluffSession

ROOT = Path(__file__).resolve().parent.parent
VECTORS = ROOT / "tests" / "vectors" / "party-session.v0.json"
KEY = bytes(range(32))
SID = "session-" + "1" * 32
SID2 = "session-" + "3" * 32
ALICE = "participant-" + "a" * 32
BOB = "participant-" + "b" * 32
CAROL = "participant-" + "c" * 32


# ---- the vendored protocol ------------------------------------------------------------------
# Copied unchanged from rcnechamkin/avrana-party: avrana/party/protocol.py at 12aaf44 (PR #16),
# contracts/vectors/party-session.v0.json at f25d256. Update both hashes only together with a
# re-vendor.
VENDORED = {
    "core/party_protocol.py": "9f5db93044ecda4a9ac5f2b99ca847d1bfe8d13a93405868bd2fcd03768d8ac2",
    "tests/vectors/party-session.v0.json":
        "b6c7f347aa39d8d54c7df2f37a9d5fd62a41f6312dbd1377be4fee208e579245",
}


@pytest.mark.parametrize("path", sorted(VENDORED))
def test_vendored_protocol_files_are_unchanged(path):
    data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == VENDORED[path]


@pytest.mark.parametrize("path", sorted(VENDORED))
def test_vendored_protocol_matches_a_sibling_party_checkout(path):
    source = {"core/party_protocol.py": "avrana/party/protocol.py",
              "tests/vectors/party-session.v0.json": "contracts/vectors/party-session.v0.json"}
    sibling = ROOT.parent / "avrana-party" / source[path]
    if not sibling.exists():
        pytest.skip("no sibling avrana-party checkout")
    norm = lambda p: p.read_bytes().replace(b"\r\n", b"\n")
    assert norm(ROOT / path) == norm(sibling)


def test_vendored_protocol_verifies_the_cross_repository_vectors():
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    key, now = bytes.fromhex(doc["key_hex"]), doc["now"]
    for v in doc["vectors"]:
        assert proto.seal(key, v["payload"]) == v["token"]
        assert proto.unseal(key, v["token"], v["name"], v["payload"]["aud"], now) == v["payload"]
    gt = doc["game_token"]
    assert proto.game_token(key, gt["sid"], gt["participant"]) == gt["token"]


# ---- key loading ----------------------------------------------------------------------------

def test_no_keys_directory_means_no_party_side():
    assert party_session.load_side("bluff", None) is None


def test_missing_key_file_means_no_party_side(tmp_path):
    assert party_session.load_side("bluff", str(tmp_path)) is None


def test_a_key_file_gives_a_party_side_for_that_game(tmp_path):
    proto.write_key(str(tmp_path / "bluff.key"), KEY)
    side = party_session.load_side("bluff", str(tmp_path))
    assert side is not None and side.game == "bluff" and side.key == KEY and side.sid is None


def test_a_bad_key_file_disables_the_party_side_without_crashing(tmp_path, caplog):
    (tmp_path / "bluff.key").write_text("not a key\n", encoding="ascii")
    with caplog.at_level(logging.ERROR):
        assert party_session.load_side("bluff", str(tmp_path)) is None
    assert "bluff" in caplog.text and "not a key" not in caplog.text


# ---- harness --------------------------------------------------------------------------------

class FakeWS:
    def __init__(self):
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = False

    async def accept(self):
        pass

    async def receive_text(self):
        item = await self.inbox.get()
        if item is None:
            raise WebSocketDisconnect()
        return json.dumps(item)

    async def send_text(self, text):
        self.sent.append(json.loads(text))

    async def close(self, *args, **kwargs):
        if not self.closed:
            self.closed = True
            self.inbox.put_nowait(None)

    def welcome(self):
        return next((m for m in self.sent if m.get("type") == "welcome"), None)

    def last_state(self):
        return next((m for m in reversed(self.sent) if m.get("type") == "state"), None)


def binding(party=True):
    side = proto.GameSide(KEY, "bluff") if party else None
    return GameBinding("bluff", BluffSession(rng=random.Random(1)), party=side)


def roster(*entries):
    return [{"participant": p, "name": n, "role": r} for p, n, r in entries]


def launch(b, sid=SID, entries=((ALICE, "Alice", "player"), (BOB, "Bob", "player"))):
    return proto.launch_message(KEY, "bluff", sid, roster(*entries))


def ticket(participant, sid=SID, role="player", game="bluff", key=KEY, now=None):
    return proto.mint_ticket(key, game, sid, participant, role, now=now)


async def settle():
    await asyncio.sleep(0.02)


async def connect(b, hello):
    ws = FakeWS()
    task = asyncio.create_task(b.endpoint(ws))
    await ws.inbox.put(hello)
    await settle()
    return ws, task


async def shutdown(b, *pairs):
    for ws, _ in pairs:
        await ws.close()
    await asyncio.gather(*(t for _, t in pairs))
    for task in (b._timer_task, b._bot_task):
        if task:
            task.cancel()


def seated_here(b):
    """Tokens of the room's players whose phones are connected. A party launch seats its roster's
    players at once (AVR-129) but nobody is *here* until a phone arrives with a ticket."""
    return {t for t, p in b.session.players.items() if p.connected}


def roster_tokens(*participants, sid=SID):
    return {proto.game_token(KEY, sid, pt) for pt in participants}


def run(coro):
    return asyncio.run(coro)


# ---- launch ---------------------------------------------------------------------------------

def test_launch_starts_the_party_session_with_that_roster():
    async def scenario():
        b = binding()
        got = await b.party_launch(launch(b))
        assert b.party.sid == SID
        assert [r["name"] for r in got] == ["Alice", "Bob"]
        # AVR-129: the party ran the pregame; its players are seated, waiting for their phones
        assert b.session.phase == "countdown" and b.session.party_round
        assert set(b.session.players) == roster_tokens(ALICE, BOB) and seated_here(b) == set()
    run(scenario())


def test_launch_resets_a_room_that_was_in_use_and_drops_its_sockets():
    async def scenario():
        b = binding()
        old = b.session
        a = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        await a[0].inbox.put({"t": "ready", "ready": True})
        await a[0].inbox.put({"t": "start"})
        await asyncio.sleep(3.3)                           # countdown -> BLUFF is playing
        assert b.session.phase not in ("lobby", "countdown")
        await b.party_launch(launch(b))
        await settle()
        assert b.session is not old and b.session.phase == "countdown"
        assert set(b.session.players) == roster_tokens(ALICE, BOB) and b.session.g is None
        assert a[0].closed and b.player_sockets == {}
        # the only timer left is the new round's own arrival wait (AVR-129), never the old game's
        from core.session import PARTY_ARRIVAL_SECONDS
        assert b.session.deadline is not None
        assert b.session.deadline - time.time() <= PARTY_ARRIVAL_SECONDS + 0.5
        await shutdown(b, a)
    run(scenario())


@pytest.mark.parametrize("bad", ["garbage", "bad-base64", "replay", "other-game", "wrong-key",
                                 "end-as-launch"])
def test_a_refused_launch_changes_nothing(bad):
    async def scenario():
        b = binding()
        first = launch(b)
        await b.party_launch(first)
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        before = (b.party.sid, b.session, dict(b.session.players))
        msg = {
            "garbage": "aps0.nope.nope",
            "bad-base64": "aps0.x.y",      # a segment of length 1 mod 4: Invalid("encoding")
            "replay": first,
            "other-game": proto.launch_message(KEY, "poker", SID2, []),
            "wrong-key": proto.launch_message(bytes(32), "bluff", SID2, []),
            "end-as-launch": proto.end_message(KEY, "bluff", SID),
        }[bad]
        with pytest.raises(proto.Invalid):
            await b.party_launch(msg)
        assert (b.party.sid, b.session, dict(b.session.players)) == before
        assert not a[0].closed
        await shutdown(b, a)
    run(scenario())


def test_a_game_without_a_party_side_refuses_launch():
    async def scenario():
        b = binding(party=False)
        with pytest.raises(proto.Invalid):
            await b.party_launch(proto.launch_message(KEY, "bluff", SID, []))
    run(scenario())


# ---- admission --------------------------------------------------------------------------------

def test_a_valid_ticket_admits_the_participant_under_the_party_name():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE), "name": "Mallory"})
        w = a[0].welcome()
        assert w is not None and not w.get("watch") and w.get("pid")
        assert "token" not in w                           # the game token never leaves the server
        token = proto.game_token(KEY, SID, ALICE)
        assert seated_here(b) == {token}
        assert b.session.players[token].name == "Alice"   # the roster name, not the hello's
        assert a[0].last_state()["you"]["name"] == "Alice"
        await shutdown(b, a)
    run(scenario())


def test_reconnect_with_a_fresh_ticket_is_the_same_player_and_seat():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b, entries=((ALICE, "Alice", "player"),)))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        pid = a[0].welcome()["pid"]
        await a[0].inbox.put({"t": "ready", "ready": True})
        await a[0].inbox.put({"t": "start"})
        await asyncio.sleep(3.3)                           # solo vs bots: BLUFF is playing
        token = proto.game_token(KEY, SID, ALICE)
        assert b.session.phase == "playing" and token in b.session.g["seats"]
        await a[0].close()
        await a[1]
        await settle()
        again = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        assert again[0].welcome()["pid"] == pid
        assert again[0].last_state()["you"]["pid"] == pid
        assert b.session.players[token].connected
        assert len(b.session.humans()) == 1
        await shutdown(b, again)
    run(scenario())


def test_a_second_participant_gets_a_different_player():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        c = await connect(b, {"t": "hello", "ticket": ticket(BOB)})
        assert a[0].welcome()["pid"] != c[0].welcome()["pid"]
        assert sorted(p.name for p in b.session.humans()) == ["Alice", "Bob"]
        await shutdown(b, a, c)
    run(scenario())


@pytest.mark.parametrize("bad", ["forged", "expired", "old-session", "other-game", "garbage",
                                 "launch-as-ticket"])
def test_a_refused_ticket_is_told_and_closed_and_never_seated(bad, caplog):
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        t = {
            "forged": ticket(ALICE, key=bytes(32)),
            "expired": ticket(ALICE, now=1_000_000_000),
            "old-session": ticket(ALICE, sid=SID2),
            "other-game": ticket(ALICE, game="poker"),
            "garbage": "aps0.x.y",
            "launch-as-ticket": launch(b, sid=SID2),
        }[bad]
        ws, task = await connect(b, {"t": "hello", "ticket": t})
        await task
        assert ws.closed and ws.welcome() is None
        assert any(m.get("type") == "fx" and m.get("kind") == "invalid" for m in ws.sent)
        assert seated_here(b) == set() and b.player_sockets == {}
        assert t not in caplog.text
    caplog.set_level(logging.INFO)
    run(scenario())


def test_a_spectator_ticket_watches():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        s = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        # AVR-129: a Party spectator (the omniscient view), not an anonymous watcher
        assert s[0].welcome() == {"type": "welcome", "watch": True, "spectator": True}
        assert seated_here(b) == set() and s[0] in b.spectator_sockets
        assert s[0] not in b.watch_sockets and s[0].last_state()["spectator"] is True
        await shutdown(b, s)
    run(scenario())


def test_a_player_ticket_for_someone_not_on_the_roster_only_watches():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        s = await connect(b, {"t": "hello", "ticket": ticket(CAROL)})
        assert s[0].welcome() == {"type": "welcome", "watch": True}
        assert seated_here(b) == set() and s[0] in b.watch_sockets  # public view, not a spectator's
        await shutdown(b, s)
    run(scenario())


# ---- wc-token is off for party sessions --------------------------------------------------------

def test_a_browser_minted_token_only_watches_during_a_party_session():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        x = await connect(b, {"t": "hello", "token": "tok-browser-0001", "name": "Eve"})
        assert x[0].welcome() == {"type": "welcome", "watch": True}
        await x[0].inbox.put({"t": "ready", "ready": True})
        await x[0].inbox.put({"t": "start"})
        await settle()
        assert seated_here(b) == set() and b.session.phase == "countdown"
        assert "tok-browser-0001" not in b.session.players
        await shutdown(b, x)
    run(scenario())


def test_a_browser_cannot_claim_a_participant_by_sending_its_game_token():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        token = proto.game_token(KEY, SID, ALICE)
        x = await connect(b, {"t": "hello", "token": token})
        assert x[0].welcome() == {"type": "welcome", "watch": True}
        assert seated_here(b) == set()
        await shutdown(b, x)
    run(scenario())


def test_a_browser_hello_that_raced_a_launch_is_not_seated_in_the_party_session():
    """The hello is classified before the lock. A launch queued ahead of it on a busy room's lock
    must not let that browser-minted token join the party session it started."""
    async def scenario():
        b = binding()
        await b.lock.acquire()                             # the room is busy (a push, a bot, …)
        starting = asyncio.create_task(b.party_launch(launch(b)))
        await settle()
        assert b.party.sid is None                         # the launch waits its turn
        x = await connect(b, {"t": "hello", "token": "tok-browser-0001", "name": "Eve"})
        b.lock.release()
        await starting
        await settle()
        assert b.party.sid == SID
        assert seated_here(b) == set() and b.player_sockets == {}
        assert "tok-browser-0001" not in b.session.players
        assert x[0].welcome() is None or x[0].welcome().get("watch")
        await shutdown(b, x)
    run(scenario())


def test_party_names_cannot_be_changed_from_the_game():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        a = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await a[0].inbox.put({"t": "profile", "name": "Mallory"})
        await settle()
        assert b.session.players[proto.game_token(KEY, SID, ALICE)].name == "Alice"
        await shutdown(b, a)
    run(scenario())


def test_a_new_launch_invalidates_the_previous_sessions_tickets():
    async def scenario():
        b = binding()
        await b.party_launch(launch(b))
        old = ticket(ALICE)
        await b.party_launch(launch(b, sid=SID2))
        ws, task = await connect(b, {"t": "hello", "ticket": old})
        await task
        assert ws.closed and seated_here(b) == set()
    run(scenario())


# ---- standalone play is unchanged ----------------------------------------------------------------

@pytest.mark.parametrize("party", [False, True])
def test_standalone_play_is_unchanged_when_no_party_session_runs(party):
    async def scenario():
        b = binding(party=party)
        a = await connect(b, {"t": "hello", "token": "tok-standalone-1", "name": "Zed"})
        w = a[0].welcome()
        assert w["token"] == "tok-standalone-1" and w["pid"]
        assert list(b.session.players) == ["tok-standalone-1"]
        assert b.session.players["tok-standalone-1"].name == "Zed"
        await shutdown(b, a)
    run(scenario())


def test_a_ticket_to_a_game_with_no_party_side_is_not_a_player():
    async def scenario():
        b = binding(party=False)
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and b.session.players == {}
    run(scenario())


def test_a_ticket_when_no_party_session_runs_is_refused():
    async def scenario():
        b = binding()
        ws, task = await connect(b, {"t": "hello", "ticket": ticket(ALICE)})
        await task
        assert ws.closed and b.session.players == {}
    run(scenario())


# ---- HTTP: the launch route and the capability ---------------------------------------------------

def http_request(path, body, client=("127.0.0.1", 50000), headers=()):
    raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
    scope = {"type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
             "query_string": b"", "client": client, "server": ("127.0.0.1", 8096),
             "scheme": "http", "http_version": "1.1",
             "headers": [(b"content-type", b"application/json"),
                         (b"content-length", str(len(raw)).encode())]
             + [(k.lower().encode(), v.encode()) for k, v in headers]}
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": raw, "more_body": False}
    return Request(scope, receive)


@pytest.fixture
def server_with_bluff_party(monkeypatch):
    import server
    b = GameBinding("bluff", BluffSession(rng=random.Random(1)),
                    party=proto.GameSide(KEY, "bluff"))
    monkeypatch.setitem(server.bindings, "bluff", b)
    return server, b


def call_launch(server, slug, body, **kw):
    path = "/games/%s/avrana/session/v0/launch" % slug
    resp = run(server.party_session_launch(slug, http_request(path, body, **kw)))
    return resp.status_code, json.loads(resp.body)


def test_launch_route_is_registered_before_the_static_mount():
    import server
    paths = [getattr(r, "path", None) for r in server.app.routes]
    route = "/games/{slug}/avrana/session/v0/launch"
    assert route in paths and paths.index(route) < paths.index("/games/bluff")


def test_launch_route_accepts_a_signed_loopback_launch(server_with_bluff_party):
    server, b = server_with_bluff_party
    status, body = call_launch(server, "bluff", {"message": launch(b)})
    assert (status, body) == (200, {"ok": True})
    assert b.party.sid == SID


@pytest.mark.parametrize("client,headers", [
    (("10.42.0.23", 50000), ()),
    (("127.0.0.1", 50000), (("X-Forwarded-For", "10.42.0.23"),)),
    (("127.0.0.1", 50000), (("X-Real-IP", "10.42.0.23"),)),
    (("127.0.0.1", 50000), (("Forwarded", "for=10.42.0.23"),)),
])
def test_launch_route_refuses_anything_not_local_and_unproxied(server_with_bluff_party,
                                                               client, headers):
    server, b = server_with_bluff_party
    status, body = call_launch(server, "bluff", {"message": launch(b)},
                               client=client, headers=headers)
    assert status == 403 and body["ok"] is False
    assert b.party.sid is None


@pytest.mark.parametrize("body", [{"message": "aps0.x.y"}, {}, {"message": 7}, b"not json",
                                  b"[]"])
def test_launch_route_refuses_a_bad_message(server_with_bluff_party, body):
    server, b = server_with_bluff_party
    status, out = call_launch(server, "bluff", body)
    assert status in (400, 403) and out["ok"] is False
    assert b.party.sid is None


def test_launch_route_refuses_an_oversized_body(server_with_bluff_party):
    server, b = server_with_bluff_party
    status, out = call_launch(server, "bluff", {"message": "x" * 20000})
    assert status == 413 and out["ok"] is False


def test_launch_route_is_404_for_a_game_without_a_party_side():
    import server
    status, body = call_launch(server, "poker", {"message": "aps0.x.y"})
    assert status == 404 and body["ok"] is False
    status, body = call_launch(server, "no-such-game", {"message": "aps0.x.y"})
    assert status == 404


def test_api_games_advertises_the_party_session_only_where_a_ticket_can_be_verified(
        server_with_bluff_party):
    server, _ = server_with_bluff_party
    rows = {g["slug"]: g for g in json.loads(run(server.api_games()).body)["games"]}
    assert rows["bluff"]["avranaSession"] == "avrana.party-session/v0"
    assert all("avranaSession" not in g for s, g in rows.items() if s != "bluff")


def test_api_games_does_not_advertise_without_a_key():
    import server
    rows = {g["slug"]: g for g in json.loads(run(server.api_games()).body)["games"]}
    assert all("avranaSession" not in g for g in rows.values())


def test_only_party_session_games_load_a_key(tmp_path):
    import games.registry as reg
    assert party_session.GAMES == ("bluff",)
    assert set(party_session.GAMES) <= {e["slug"] for e in reg.REGISTRY}
    for slug in ("bluff", "poker"):
        proto.write_key(str(tmp_path / ("%s.key" % slug)), KEY)
    assert set(party_session.load_sides(str(tmp_path))) == {"bluff"}
    assert party_session.load_sides(None) == {}
