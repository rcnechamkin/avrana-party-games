"""Game result envelope v1 (avrana.game-result/v1, AVR-237), game side.

The format and its rules are core/party_result.py, vendored unchanged from rcnechamkin/avrana-party
(avrana/party/result.py; ADR 0015 there). The result rides inside the signed `ended` report, so
only this server can make one: it is built in core/net.py from GameSession.game_result().

  * BLUFF reports its real result: one winner, everyone else lost, a few public game facts.
  * A cooperative, EXPO-shaped result passes through the same path with no change to it.
  * A game with no result, a broken one or an abandoned one still ends its session as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from pathlib import Path

import pytest

from core import party_protocol as proto
from core import party_result, party_session
from core.net import GameBinding
from games.bluff.game import ROLES, BluffSession
from test_party_session import ALICE, BOB, CAROL, KEY, SID, connect, launch, run, settle, shutdown, ticket
from test_party_session_end import (PARTY_URL, binding, fast, party, party_game, report_of,  # noqa: F401
                                    reports, win_for_alice)

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "tests/vectors/game-result.v1.json").read_text(encoding="utf-8"))
DECLARATION = json.loads((ROOT / "provider/avrana-contract.json").read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ---- the vendored format --------------------------------------------------------------------

def test_the_vendored_result_module_and_vectors_are_the_declared_ones():
    r = DECLARATION["result"]
    assert r["schema"] == party_result.SCHEMA == VECTORS["schema"]
    assert digest(r["vendored"]) == r["vendored_sha256"]
    assert digest(r["vectors"]) == r["vectors_sha256"]


@pytest.mark.parametrize("source,vendored", (("avrana/party/result.py", "core/party_result.py"),
                                             ("contracts/vectors/game-result.v1.json",
                                              "tests/vectors/game-result.v1.json")))
def test_vendored_result_files_match_a_sibling_party_checkout(source, vendored):
    sibling = Path(os.environ.get("AVRANA_PARTY_REPO") or ROOT.parent / "avrana-party") / source
    if not sibling.exists():
        pytest.skip("no sibling avrana-party checkout with the result envelope")
    norm = lambda p: p.read_bytes().replace(b"\r\n", b"\n")
    assert norm(ROOT / vendored) == norm(sibling)


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda c: c["name"])
def test_the_vendored_checker_decides_every_shared_case_as_recorded(case):
    if case["accept"]:
        assert party_result.check(case["result"], case["game"], case["players"]) == case["result"]
    else:
        with pytest.raises(party_result.Refused) as refused:
            party_result.check(case["result"], case["game"], case["players"])
        assert str(refused.value) == case["reason"]


def test_the_build_id_is_stable_well_formed_and_per_game():
    a = party_session.build_id("bluff")
    assert a == party_session.build_id("bluff") and party_result.TAG.match(a)
    assert a.startswith("sha256:") and a != party_session.build_id("expo")


def test_the_build_id_covers_the_shared_runtime_that_produces_the_result():
    names = {p.relative_to(ROOT).as_posix() for p in party_session.build_files("bluff")}
    assert {"server.py", "requirements.txt", "core/net.py", "core/session.py",
            "core/party_result.py", "core/party_protocol.py", "core/party_session.py",
            "games/registry.py", "games/bluff/game.py"} <= names
    assert not any(n.startswith(("games/bluff/web/", "games/bluff/art/", "games/expo/")) for n in names)
    assert not any(n.endswith((".md", ".pyc")) for n in names)
    assert "games/expo/content/tasks.json" in {
        p.relative_to(ROOT).as_posix() for p in party_session.build_files("expo")}


def _tree(root):
    for rel, text in (("server.py", "app = 1\n"), ("requirements.txt", "fastapi==1\n"),
                      ("core/net.py", "x = 1\n"), ("core/party_result.py", "y = 1\n"),
                      ("games/registry.py", "r = 1\n"), ("games/__init__.py", ""),
                      ("games/alpha/game.py", "a = 1\n"), ("games/alpha/content/set.json", "{}\n"),
                      ("games/alpha/web/client.js", "1\n"), ("games/alpha/README.md", "a\n"),
                      ("games/beta/game.py", "b = 1\n")):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


@pytest.mark.parametrize("rel,changes", (
    ("core/net.py", True),                     # the code that builds and sends the result
    ("core/party_result.py", True),            # the vendored envelope
    ("server.py", True),
    ("requirements.txt", True),                # pinned dependencies
    ("games/registry.py", True),
    ("games/alpha/game.py", True),             # the rules
    ("games/alpha/content/set.json", True),    # server-side content
    ("games/alpha/web/client.js", False),      # the browser's files decide nothing
    ("games/alpha/README.md", False),
    ("games/beta/game.py", False),             # another game
))
def test_the_build_id_changes_exactly_when_the_implementation_does(tmp_path, rel, changes):
    _tree(tmp_path)
    before = party_session.build_id("alpha", tmp_path)
    copy = tmp_path.parent / (tmp_path.name + "-copy")
    _tree(copy)
    assert party_session.build_id("alpha", copy) == before          # same content, same id
    with open(copy / rel, "a", encoding="utf-8") as f:
        f.write("# changed\n")
    party_session._builds.pop((str(copy), "alpha"))
    assert (party_session.build_id("alpha", copy) != before) is changes


def test_line_endings_do_not_change_the_build_id(tmp_path):
    _tree(tmp_path)
    before = party_session.build_id("alpha", tmp_path)
    path = tmp_path / "core/net.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    party_session._builds.clear()
    assert party_session.build_id("alpha", tmp_path) == before


# ---- BLUFF's real result --------------------------------------------------------------------

def test_a_completed_bluff_game_reports_who_won(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        await win_for_alice(a, c)                        # Bob forfeits, Alice is the last one in
        await reports(b)
        assert len(posts) == 1
        p = report_of(posts[0][1])
        assert (p["iss"], p["sid"], p["outcome"]) == ("bluff", SID, "completed")
        r = p["result"]
        assert party_result.check(r, "bluff", [ALICE, BOB]) == r      # what the party will do
        assert r["schema"] == "avrana.game-result/v1" and r["mode"] == "competitive"
        assert r["game"] == {"id": "bluff", "build": party_session.build_id("bluff")}
        assert {e["participant"]: e["standing"] for e in r["standings"]} == {ALICE: "won", BOB: "lost"}
        assert r["data_schema"] == "bluff.result/v1"
        assert r["data"]["forfeited"] == [BOB] and r["data"]["winner"] == "player"
        assert r["data"]["seats"] == 2 and r["data"]["bots"] == 0 and r["data"]["steps"] >= 1
        await shutdown(b, a, c)
    run(scenario())


def test_the_result_names_people_only_by_participant_id_and_leaks_no_cards(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        tokens = list(b.party_roster)
        hands = [card for t in tokens for card in b.session.g["hand"][t]]
        await win_for_alice(a, c)
        await reports(b)
        text = json.dumps(report_of(posts[0][1])["result"])
        assert hands and not any(role in text for role in ROLES)       # no card, held or revealed
        assert not any(t in text for t in tokens)                      # no game token
        assert "Alice" not in text and "Bob" not in text               # no name either
        assert "device" not in text and "member" not in text
        await shutdown(b, a, c)
    run(scenario())


def test_a_spectator_is_never_given_a_standing(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        entries = ((ALICE, "Alice", "player"), (BOB, "Bob", "player"), (CAROL, "Carol", "spectator"))
        a, c = await party_game(b, entries)
        watcher = await connect(b, {"t": "hello", "ticket": ticket(CAROL, role="spectator")})
        await win_for_alice(a, c)
        await reports(b)
        r = report_of(posts[0][1])["result"]
        assert [e["participant"] for e in r["standings"]] == [ALICE, BOB]
        assert CAROL not in json.dumps(r)
        await shutdown(b, a, c, watcher)
    run(scenario())


def test_an_abandoned_game_reports_no_result(party):
    posts, _, _ = party

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        b.session._outcome = "abandoned"                 # as the empty-table timeout sets it
        async with b.lock:
            await b.push_all([])
        await reports(b)
        p = report_of(posts[0][1])
        assert p["outcome"] == "abandoned" and "result" not in p
        await shutdown(b, a, c)
    run(scenario())


def test_bluff_game_result_alone():
    """Pure: no network. A bot can win; the party is then told every person lost."""
    s = BluffSession(rng=random.Random(3))
    s.join("tokenA_alice", "Alice"); s.set_ready("tokenA_alice", True)
    s.set_settings("tokenA_alice", {"bots": 1})
    s.start("tokenA_alice"); s.tick(s.gen)
    assert s.game_result(lambda t: None) is None                       # nobody has won yet
    bot = next(t for t in s.g["seats"] if s._is_bot(t))
    s.g["winner"] = bot
    r = s.game_result(lambda t: ALICE if t == "tokenA_alice" else None)
    assert [(e["token"], e["standing"]) for e in r["standings"]] == [("tokenA_alice", "lost"), (bot, "won")]
    assert r["data"]["winner"] == "bot" and r["data"]["bots"] == 1 and r["data"]["forfeited"] == []


# ---- any other game: a cooperative, EXPO-shaped result through the same path -------------------

class Cooperative(BluffSession):
    """Stands in for a cooperative game: BLUFF's table, but the result is the whole table's, the
    way EXPO's is (a mission passed or failed; nobody wins alone)."""
    status = "success"

    def game_result(self, ref):
        return {"mode": "cooperative",
                "standings": [{"token": t, "standing": "won" if self.status == "success" else "lost"}
                              for t in self.g["seats"]],
                "data_schema": "expo.result/v1", "content": "missions-1",
                "data": {"mission": 17, "status": self.status, "attempts": 3,
                         "tasks": {"done": 4, "total": 4}}}


def coop_binding(party, session):
    b = GameBinding("expo", session, party=proto.GameSide(KEY, "expo"), party_url=PARTY_URL)
    party[2].append(b)
    return b


@pytest.mark.parametrize("status,standing", (("success", "won"), ("failure", "lost")))
def test_a_cooperative_result_needs_no_change_to_the_reporting_path(party, status, standing):
    posts, _, _ = party

    async def scenario():
        Cooperative.status = status                      # party_launch makes a fresh session
        b = coop_binding(party, Cooperative(rng=random.Random(1)))
        await b.party_launch(proto.launch_message(KEY, "expo", SID, [
            {"participant": p, "name": n, "role": "player"} for p, n in ((ALICE, "Alice"), (BOB, "Bob"))]))
        pairs = [await connect(b, {"t": "hello", "ticket": ticket(p, game="expo")}) for p in (ALICE, BOB)]
        for _ in range(50):
            await settle()
            if b.session.phase == "playing":
                break
        await win_for_alice(*pairs)
        await reports(b)
        p = proto.open_message(KEY, posts[0][1], "ended", "party", proto.ReplayGuard())
        r = p["result"]
        assert p["iss"] == "expo" and party_result.check(r, "expo", [ALICE, BOB]) == r
        assert r["mode"] == "cooperative" and {e["standing"] for e in r["standings"]} == {standing}
        assert r["game"]["content"] == "missions-1" and r["data"]["status"] == status
        await shutdown(b, *pairs)
    run(scenario())
    Cooperative.status = "success"


# ---- a game that gets it wrong still ends ----------------------------------------------------

class Broken(BluffSession):
    def game_result(self, ref):
        return self.made


@pytest.mark.parametrize("made", (
    {"mode": "competitive", "standings": []},                                    # nobody listed
    {"mode": "teams", "standings": [{"token": "x", "standing": "won"}]},
    {"standings": "alice"},                                                      # not even the shape
    {"mode": "competitive", "standings": [], "data_schema": "bluff.result/v1",
     "data": {"log": ["x" * 150] * 20}},                                         # far too large
), ids=("empty", "mode", "shape", "size"))
def test_an_invalid_result_is_left_out_and_the_end_is_still_reported(party, caplog, made):
    posts, _, _ = party

    async def scenario():
        Broken.made = made
        b = GameBinding("bluff", Broken(rng=random.Random(1)), party=proto.GameSide(KEY, "bluff"),
                        party_url=PARTY_URL)
        party[2].append(b)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await reports(b)
        p = report_of(posts[0][1])
        assert p["outcome"] == "completed" and "result" not in p
        assert "game result not sent" in caplog.text
        await shutdown(b, a, c)
    caplog.set_level(logging.ERROR)
    run(scenario())


def test_a_game_without_game_result_reports_as_before(party):
    posts, _, _ = party

    class Plain(BluffSession):
        game_result = BluffSession.__mro__[1].game_result          # the base class: None

    async def scenario():
        b = GameBinding("bluff", Plain(rng=random.Random(1)), party=proto.GameSide(KEY, "bluff"),
                        party_url=PARTY_URL)
        party[2].append(b)
        a, c = await party_game(b)
        await win_for_alice(a, c)
        await reports(b)
        p = report_of(posts[0][1])
        assert set(p) == {"v", "typ", "iss", "aud", "sid", "iat", "exp", "outcome", "nonce"}
        await shutdown(b, a, c)
    run(scenario())


# ---- only the server makes one ---------------------------------------------------------------

def test_no_browser_message_can_put_a_result_in_the_report(party):
    posts, _, _ = party
    forged = {"schema": party_result.SCHEMA, "game": {"id": "bluff", "build": "x"},
              "mode": "competitive", "standings": [{"participant": BOB, "standing": "won"},
                                                   {"participant": ALICE, "standing": "lost"}]}

    async def scenario():
        b = binding(party)
        a, c = await party_game(b)
        for verb in ("result", "ended", "game_result", "end"):
            await c[0].inbox.put({"t": verb, "result": forged, "outcome": "completed"})
        await settle()
        assert posts == [] and b.session.phase == "playing"            # nothing was reported
        await win_for_alice(a, c)
        await reports(b)
        r = report_of(posts[0][1])["result"]
        assert {e["participant"]: e["standing"] for e in r["standings"]} == {ALICE: "won", BOB: "lost"}
        await shutdown(b, a, c)
    run(scenario())
