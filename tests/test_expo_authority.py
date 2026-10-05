"""EXPO in a Party round: the Party Host and the EXPO captain are two authorities (AVR-252, AVR-275).

The Party Host owns the table's routine life (Begin, Retry, Next) and ends EXPO from the Party.
The captain owns what the rules give the captain. The crew still decides together what the rules
say it decides together. Who the host is comes from the Party alone: a fresh ticket with every
host action, and the Party's own answer, asked at that moment (avrana-party ADR 0006, amendment
2026-10-04), so succession and reconnects need nothing kept here and a lost role is worth
nothing at once. Harness: test_party_session.py.
"""
from __future__ import annotations

import asyncio
import time
import random

import pytest

from core import party_protocol as proto
from core.net import GameBinding
from core.session import HostRefused
from games.expo.engine import Engine, Invalid
from games.expo import game as expo_game
from games.expo.game import DISTRESS_GRACE, GRACE, HOST_ONLY, PARTY_END, ExpoSession

from test_party_session import ALICE, BOB, CAROL, KEY, SID, connect, roster, run, settle, shutdown

DANA = "participant-" + "d" * 32
PLAYERS = ((ALICE, "Alice"), (BOB, "Bob"), (CAROL, "Carol"))

# The adapter's monotonic clock, with a hand on it: tests move time instead of waiting for it.
CLOCK = {"skip": 0.0}


@pytest.fixture(autouse=True)
def a_clock_these_tests_can_move(monkeypatch):
    CLOCK["skip"] = 0.0
    monkeypatch.setattr(expo_game, "_mono", lambda: time.monotonic() + CLOCK["skip"])


def ticket(participant, host=None, role="player"):
    return proto.mint_ticket(KEY, "expo", SID, participant, role, host=host)


class Table:
    """A launched Party round with every phone connected and the mission dealt."""

    def __init__(self, b, socks, host):
        self.b, self.socks = b, socks                     # participant -> (ws, task)
        # Party Core, as far as the game can tell: who the host is NOW, and whether it answers.
        self.party_host, self.party_up, self.asked = host, True, 0
        self.forge = None                                 # an answer to hand back instead
        guard = proto.ReplayGuard()

        def ask(url, question):
            self.asked += 1
            if not self.party_up:
                return None
            q = proto.open_message(KEY, question, "host", "party", guard)
            return self.forge(q) if self.forge else proto.host_answer(KEY, q, q["pid"] == self.party_host)
        b.ask_host = ask

    @property
    def engine(self):
        return self.b.session.engine

    def pid(self, participant):
        return self.b.session.players[proto.game_token(KEY, SID, participant)].pid

    def participant(self, pid):
        return next(p for p in self.socks if p in dict(PLAYERS) and self.pid(p) == pid)

    def cmd(self, t, **kw):
        s = self.engine.s
        return {"t": t, "attempt": s["attempt"], "revision": s["revision"],
                "request": f"r{s['revision']}-{random.getrandbits(48):x}", **kw}

    async def send(self, participant, msg):
        """One message from that phone; returns what the phone was told (invalid fx, if any)."""
        ws = self.socks[participant][0]
        mark = len(ws.sent)
        told = lambda: [m for m in ws.sent[mark:] if m.get("type") == "fx" and m.get("kind") == "invalid"]
        engine = self.engine
        before = engine.s["revision"] if engine else None
        await ws.inbox.put(msg)
        await settle()
        if msg.get("t") == "host":
            # the Party is asked on another thread: wait for the outcome, not for a fixed time
            for _ in range(100):
                e = self.b.session.engine
                if told() or e is not engine or (e and e.s["revision"] != before):
                    break
                await settle()
            await settle()
        return told()

    async def act(self, participant, t, **kw):
        return await self.send(participant, self.cmd(t, **kw))

    async def host(self, participant, kind, host=True, role="player", **kw):
        """A host action carrying a fresh ticket that says `host` for that participant. Whether
        the Party then agrees is `self.party_host`."""
        s = self.engine.s
        return await self.send(participant, {
            "t": "host", "ticket": ticket(participant, host, role),
            "action": {"t": "lifecycle", "decision": {"kind": kind, **kw},
                       "attempt": s["attempt"], "revision": s["revision"]}})

    async def prepare(self, grace=False):
        """Allocate every task and commit every prediction: the crew is ready to begin. The
        moment kept for a distress request has passed, unless `grace`."""
        for _ in range(40):
            s = self.engine.s
            if s["phase"] == "allocation":
                seat = self.engine.selector()
                task = next((k for k in s["pool"] if self.engine.eligible(k, seat)), None)
                who = self.participant(self.engine.controller(seat))
                assert not await (self.act(who, "choose_task", task=task) if task
                                  else self.act(who, "pass_task"))
            elif s["phase"] == "prediction":
                k = next(k for k in s["assignments"] if k not in s["predictions"])
                who = self.participant(self.engine.controller(s["assignments"][k]))
                assert not await self.act(who, "predict", task=k, count=0)
            else:
                break
        assert self.engine.s["phase"] == "assistance"
        if not grace:
            CLOCK["skip"] += DISTRESS_GRACE + 1

    async def close(self):
        await shutdown(self.b, *self.socks.values())


SETUP = {"mission": 1, "timed": False}       # what a Party round offers first, and all a setup carries
SEAT = 2                                     # the seat offered for Tonoja: after both players


async def table(host=ALICE, claims=True, players=PLAYERS, mission=1, seed=1, watchers=(), setup=True):
    """A launched Party round, dealt from `seed`: the same seed is the same deal, tasks and
    captain every time, so a test meets the table it was written for. The round opens in setup
    (AVR-245, the last sections of this file); unless `setup` is False the table is taken through
    it here, on `mission`: two players first agree the seat offered for Tonoja, then whoever
    moves this table on deals (the Party Host, or the crew under a Party that does not name its
    host)."""
    b = GameBinding("expo", ExpoSession(rng=random.Random(seed)), party=proto.GameSide(KEY, "expo"))
    entries = [(p, n, "player") for p, n in players] + [(p, n, "spectator") for p, n in watchers]
    await b.party_launch(proto.launch_message(KEY, "expo", SID, roster(*entries)))
    # A launch replaces the room with a new session of its own (GameBinding._fresh_room), which
    # draws from an unseeded generator: the one given above is gone with the session it was
    # given to. The deal is drawn from the session's generator when the setup is confirmed, and
    # nothing draws from it before, so this is where the seed goes.
    b.session.rng = random.Random(seed)
    socks = {}
    early = Table(b, socks, host if claims else None)       # the Party answers from the first hello
    for p, _ in players:
        socks[p] = await connect(b, {"t": "hello", "ticket": ticket(p, (p == host) if claims else None)})
    for p, _ in watchers:
        socks[p] = await connect(b, {"t": "hello", "ticket": ticket(p, (p == host) if claims else None,
                                                                    "spectator")})
    async with b.lock:                                     # the 3-2-1, without the wait
        await b.push_all(b.session.tick(b.session.gen))
    assert b.session.engine is not None and b.session.party_round
    assert b.session.phase == "setup" and b.session.engine.s["mission"] is None
    assert b.session.engine.rng.getstate() == random.Random(seed).getstate()      # nothing drawn yet
    if not setup:
        return early
    chosen = dict(SETUP, mission=mission)
    if len(players) == 2:                                  # the two players, whoever the host is
        await agree_seat(early, players[0][0], players[1][0])
    if claims:
        role = "spectator" if host in dict(watchers) else "player"
        assert await early.host(host, "setup", role=role, **chosen) == []
        for _ in range(500):                               # the Party answers on another thread
            if b.session.phase != "setup":
                break
            await settle()
    elif expo_game.HOST_CLAIM_TRANSITION:
        assert await early.act(players[0][0], "propose", proposal={"kind": "setup", **chosen}) == []
        for p, _ in players[1:]:
            assert await early.act(p, "confirm", yes=True) == []
    else:
        # After the transition a Party that does not name its host cannot set a table up at all
        # (the last section of this file). These tests are about what follows, so the step is taken for it.
        s = b.session.engine.s
        async with b.lock:
            await b.push_all(b.session.host_action({"t": "lifecycle", "decision": {"kind": "setup", **chosen},
                                                    "attempt": s["attempt"], "revision": s["revision"]}))
    assert b.session.phase == "allocation" and b.session.engine.s["mission"]["id"] == mission
    # The seed took: this is the table that seed deals, card for card and task for task. The
    # steps of the setup are accepted changes and (for a crew that voted) remembered requests,
    # so those two counters are the only difference from a table dealt directly.
    direct = Engine([early.pid(p) for p, _ in players], random.Random(seed), mission, False, SEAT)
    dealt = b.session.engine.s
    for key in set(dealt) | set(direct.s):
        if key not in ("revision", "dedup"):
            assert dealt.get(key) == direct.s.get(key), f"seed {seed} did not decide the deal ({key})"
    assert b.session.engine.rng.getstate() == direct.rng.getstate()
    return early


async def agree_seat(t, proposer, other, position=SEAT):
    """The two players agree where Tonoja sits: one proposes, the other confirms (R p22)."""
    assert await t.act(proposer, "propose", proposal={"kind": "tonoja_seat", "position": position}) == []
    assert await t.act(other, "confirm", yes=True) == []
    assert t.engine.s["setup"]["tonoja_seat"] == position and t.engine.s["proposal"] is None


def other_than(t, pid):
    return next(p for p, _ in PLAYERS if t.pid(p) != pid)


# ---- the Party says who the host is ------------------------------------------------------------

def test_a_party_round_says_who_moves_the_table_on():
    async def scenario():
        t = await table()
        state = t.socks[BOB][0].last_state()
        assert state["party_round"] and state["party_host"]
        assert state["game"]["lifecycle"] == "host"
        assert state["game"]["lifecycle_transitional"] is False and t.b._no_host_claim_sid is None
        await t.close()
    run(scenario())


def test_the_host_begins_at_once_and_nobody_votes():
    async def scenario():
        t = await table()
        await t.prepare()
        attempts = t.engine.s["attempts"]
        assert await t.host(ALICE, "begin") == []
        s = t.engine.s
        assert s["phase"] == "before_trick" and s["proposal"] is None and s["attempts"] == attempts + 1
        await t.close()
    run(scenario())


def test_no_other_crew_member_can_move_the_table_on():
    async def scenario():
        t = await table()
        await t.prepare()
        before = t.engine.s["revision"]
        # a seat's own proposal, the old way
        said = await t.act(BOB, "propose", proposal={"kind": "begin"})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["begin"])]
        # the host message with a ticket that says "not the host"
        assert [m["code"] for m in await t.host(BOB, "begin", host=False)] == ["host"]
        # ... with a ticket that says nothing about the host
        assert [m["code"] for m in await t.host(BOB, "begin", host=None)] == ["host"]
        # ... with the host's own fresh ticket, sent from another phone
        stolen = {"t": "host", "ticket": ticket(ALICE, True),
                  "action": {"t": "lifecycle", "decision": {"kind": "begin"},
                             "attempt": t.engine.s["attempt"], "revision": before}}
        asked = t.asked
        assert [m["code"] for m in await t.send(BOB, dict(stolen))] == ["host"]
        assert t.asked == asked                             # the Party is not asked for those
        # ... and a ticket this server already saw is spent
        used = ticket(ALICE, True)
        t.b.party.present(used)
        assert [m["code"] for m in await t.send(ALICE, dict(stolen, ticket=used))] == ["host"]
        assert [m["code"] for m in await t.send(ALICE, dict(stolen, ticket="aps0.forged.ticket"))] == ["host"]
        # ... a host ticket for another game, another session, or one that has run out
        for bad in (proto.mint_ticket(KEY, "bluff", SID, ALICE, "player", host=True),
                    proto.mint_ticket(KEY, "expo", "another-session", ALICE, "player", host=True),
                    proto.mint_ticket(KEY, "expo", SID, ALICE, "player", host=True, now=time.time() - 3600)):
            assert [m["code"] for m in await t.send(ALICE, dict(stolen, ticket=bad))] == ["host"]
        assert t.engine.s["revision"] == before and t.engine.s["phase"] == "assistance"
        await t.close()
    run(scenario())


# ---- host and captain are different people -----------------------------------------------------

def test_a_captain_who_is_not_the_host_cannot_begin_and_stays_captain():
    async def scenario():
        t = await table()
        captain = t.engine.s["captain"]
        host = other_than(t, captain)
        t.party_host = host
        cap = t.participant(captain)
        await t.prepare()
        assert [m["msg"] for m in await t.act(cap, "propose", proposal={"kind": "begin"})] == [HOST_ONLY["begin"]]
        assert [m["code"] for m in await t.host(cap, "begin", host=False)] == ["host"]
        assert await t.host(host, "begin") == []
        s = t.engine.s
        assert s["phase"] == "before_trick" and s["captain"] == captain
        assert s["turn"] == captain                       # the captain still opens the first trick
        await t.close()
    run(scenario())


def test_a_host_who_is_not_the_captain_gets_none_of_the_captains_mechanics():
    async def scenario():
        # Mission 10: the captain alone decides who takes the tasks (AVR-251).
        t = await table(mission=10)
        captain = t.engine.s["captain"]
        # The deal this test needs, which seed 1 gives: tasks the captain may keep. About one
        # mission 10 deal in sixteen draws a captain comparison task, which the captain may not own.
        assert all(t.engine.eligible(k, captain) for k in t.engine.s["pool"])
        host = other_than(t, captain)
        t.party_host = host
        owner = t.pid(host)
        said = await t.act(host, "propose", proposal={"kind": "assign", "owner": owner, "task": "all"})
        assert [m["code"] for m in said] == ["captain"]
        # nor does the host's lifecycle authority reach a decision the rules give someone else
        s = t.engine.s
        for decision in ({"kind": "assign", "owner": owner, "task": "all"},
                         {"kind": "distress", "direction": "left"}, {"kind": "end"}):
            said = await t.send(host, {"t": "host", "ticket": ticket(host, True),
                                       "action": {"t": "lifecycle", "decision": decision,
                                                  "attempt": s["attempt"], "revision": s["revision"]}})
            assert [m["code"] for m in said] == ["strategic"]
        assert t.engine.s["pool"] and not t.engine.s["assignments"]
        # the captain's own decision is untouched by any of it
        cap = t.participant(captain)
        assert await t.act(cap, "propose", proposal={"kind": "assign", "owner": captain, "task": "all"}) == []
        assert set(t.engine.s["assignments"].values()) == {captain}
        await t.close()
    run(scenario())


def test_with_tonoja_only_the_captain_plays_tonojas_cards_host_or_not():
    async def scenario():
        t = await table(players=PLAYERS[:2], seed=3)
        captain = t.engine.s["captain"]
        host = next(p for p, _ in PLAYERS[:2] if t.pid(p) != captain)
        t.party_host = host
        await t.prepare()
        assert await t.host(host, "begin") == []
        s = t.engine.s
        s["turn"] = s["leader"] = "tonoja"                # Tonoja to lead
        s["revision"] += 1
        card = next(c["top"] for c in s["columns"] if c["top"])
        assert [m["code"] for m in await t.act(host, "play_card", card=card)] == ["turn"]
        assert await t.act(t.participant(captain), "play_card", card=card) == []
        await t.close()
    run(scenario())


def test_a_host_who_is_watching_moves_the_table_on_and_holds_no_seat():
    async def scenario():
        t = await table(host=DANA, watchers=((DANA, "Dana"),))
        await t.prepare()
        ws = t.socks[DANA][0]
        assert ws.last_state()["game"]["me"] is None      # a spectator: no hand, no seat
        assert await t.host(DANA, "begin", host=False, role="spectator")   # not the host: refused
        assert t.engine.s["phase"] == "assistance"
        assert await t.host(DANA, "begin", role="spectator") == []
        assert t.engine.s["phase"] == "before_trick"
        assert len(t.engine.s["humans"]) == 3 and ws.last_state()["game"]["me"] is None
        # a watcher without a ticket is nobody, whatever it sends
        anon = await connect(t.b, {"t": "hello", "name": "Mallory"})
        mark = t.engine.s["revision"]
        await anon[0].inbox.put({"t": "host", "ticket": ticket(DANA, True, "spectator"),
                                 "action": {"t": "lifecycle", "decision": {"kind": "retry", "keep": True},
                                            "attempt": t.engine.s["attempt"], "revision": mark}})
        await settle()
        assert t.engine.s["revision"] == mark
        t.socks["anon"] = anon
        await t.close()
    run(scenario())


# ---- the host cannot skip what the rules require first ------------------------------------------

def test_the_host_cannot_begin_before_the_tasks_are_allocated():
    async def scenario():
        t = await table()
        assert t.engine.s["phase"] == "allocation"
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["phase"]
        assert t.engine.s["phase"] == "allocation"
        await t.close()
    run(scenario())


def test_a_distress_request_stops_the_hosts_begin_until_the_crew_has_answered():
    async def scenario():
        t = await table()
        await t.prepare()
        assert await t.act(BOB, "propose", proposal={"kind": "distress", "direction": "left"}) == []
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["vote"]
        assert t.engine.s["phase"] == "assistance" and t.engine.s["proposal"]
        # distress is the crew's: everyone agrees, the host's word is one vote like any other
        assert await t.act(ALICE, "confirm", yes=True) == []
        assert t.engine.s["proposal"] and t.engine.s["phase"] == "assistance"
        assert await t.act(CAROL, "confirm", yes=True) == []
        assert t.engine.s["phase"] == "passing" and t.engine.s["distress"]
        await t.close()
    run(scenario())


def test_one_decline_still_cancels_a_strategic_decision_and_then_the_host_may_begin():
    async def scenario():
        t = await table()
        await t.prepare()
        await t.act(BOB, "propose", proposal={"kind": "distress", "direction": "right"})
        assert await t.act(CAROL, "confirm", yes=False) == []
        assert t.engine.s["proposal"] is None and not t.engine.s["distress"]
        assert await t.host(ALICE, "begin") == []
        assert t.engine.s["phase"] == "before_trick"
        await t.close()
    run(scenario())


def test_the_crew_gets_a_moment_to_ask_for_distress_before_the_host_can_begin():
    """Owner decision 2026-10-04: a protected opportunity, not a vote. Begin is closed to the
    host for a short fixed time after the tasks are settled; nobody has to say "ready"."""
    async def scenario():
        t = await table()
        await t.prepare(grace=True)
        view = t.socks[BOB][0].last_state()["game"]
        assert view["lifecycle"] == "host" and 0 < view["begin_at"] - time.time() <= DISTRESS_GRACE
        before = t.engine.s["revision"]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "begin")] == [("grace", GRACE)]
        assert t.engine.s["revision"] == before and t.engine.s["phase"] == "assistance"
        CLOCK["skip"] += DISTRESS_GRACE - 0.5               # not yet
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["grace"]
        CLOCK["skip"] += 1                                   # now, and with no one confirming
        assert await t.host(ALICE, "begin") == []
        assert t.engine.s["phase"] == "before_trick" and t.engine.s["proposal"] is None
        assert t.socks[BOB][0].last_state()["game"]["begin_at"] is None
        await t.close()
    run(scenario())


def test_every_phone_is_given_the_servers_reason_for_begin_and_told_when_it_no_longer_holds(monkeypatch):
    """AVR-263, owner decision 2026-10-05: why the host's Begin is closed is the server's own
    sentence, in the view of every phone (the host here only watches and has no seat). When the
    crew's moment ends the server says so itself: a state arrives with no reason, and nobody
    sent anything."""
    monkeypatch.setattr(expo_game, "DISTRESS_GRACE", 1.0)

    async def scenario():
        t = await table(host=DANA, watchers=((DANA, "Dana"),))
        await t.prepare(grace=True)
        phones = [t.socks[p][0] for p in (ALICE, BOB, CAROL, DANA)]
        views = [ws.last_state()["game"] for ws in phones]
        assert views[3]["me"] is None and views[0]["me"] is not None
        for view in views:
            assert view["lifecycle"] == "host" and view["begin_at"] is not None
            assert view["lifecycle_reasons"] == {"begin": GRACE, "retry": "Retry is available after a failed mission.",
                                                 "next": "Complete this mission first."}
        revision = t.engine.s["revision"]
        for _ in range(200):                                # the table's own timer, on the real clock
            if all(ws.last_state()["game"]["lifecycle_reasons"]["begin"] is None for ws in phones):
                break
            await asyncio.sleep(0.02)
        for ws in phones:
            view = ws.last_state()["game"]
            assert view["lifecycle_reasons"]["begin"] is None and view["begin_at"] is None
        assert t.engine.s["revision"] == revision and t.engine.s["phase"] == "assistance"   # nothing was played
        assert await t.host(DANA, "begin", role="spectator") == []
        assert t.engine.s["phase"] == "before_trick"
        # in play, Begin is refused for what it needs, and every phone already says so
        for ws in phones:
            assert ws.last_state()["game"]["lifecycle_reasons"]["begin"] == "Finish task allocation and predictions first."
        said = await t.host(DANA, "begin", role="spectator")
        assert [m["msg"] for m in said] == ["Finish task allocation and predictions first."]
        await t.close()
    run(scenario())


def test_a_distress_request_made_in_that_moment_holds_begin_until_it_is_answered():
    async def scenario():
        t = await table()
        await t.prepare(grace=True)
        assert await t.act(CAROL, "propose", proposal={"kind": "distress", "direction": "left"}) == []
        CLOCK["skip"] += DISTRESS_GRACE + 1                 # the moment has passed; the request has not
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["vote"]
        assert await t.act(BOB, "confirm", yes=False) == []                # declined: no new wait
        assert t.socks[BOB][0].last_state()["game"]["begin_at"] is None
        assert await t.host(ALICE, "begin") == []
        await t.close()
    run(scenario())


def test_the_moment_is_kept_once_per_attempt_and_only_where_distress_exists():
    async def scenario():
        t = await table()
        await t.prepare()
        assert await t.host(ALICE, "begin") == []
        t.engine._finish("failed", "fixture")
        t.engine.s["revision"] += 1
        assert await t.host(ALICE, "retry", keep=True) == []               # a new attempt
        await t.prepare(grace=True)
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["grace"]
        await t.close()
        # two humans and Tonoja: the rules offer no distress there, so there is nothing to wait for
        t = await table(players=PLAYERS[:2])
        await t.prepare(grace=True)
        assert t.socks[BOB][0].last_state()["game"]["begin_at"] is None
        assert await t.host(ALICE, "begin") == []
        await t.close()
    run(scenario())


# ---- retry and next ---------------------------------------------------------------------------

@pytest.mark.parametrize("keep", [True, False])
def test_after_a_failure_only_the_host_retries_and_chooses_the_tasks(keep):
    async def scenario():
        t = await table()
        await t.prepare()
        await t.host(ALICE, "begin")
        tasks, attempt = list(t.engine.s["selected"]), t.engine.s["attempt"]
        t.engine._finish("failed", "fixture")
        t.engine.s["revision"] += 1
        said = await t.act(BOB, "propose", proposal={"kind": "retry", "keep": keep})
        assert [m["msg"] for m in said] == [HOST_ONLY["retry"]]
        assert [m["code"] for m in await t.host(ALICE, "next", mission=2)] == ["phase"]
        assert await t.host(ALICE, "retry", keep=keep) == []
        s = t.engine.s
        assert s["attempt"] == attempt + 1 and s["result"] is None and s["mission"]["id"] == 1
        if keep:
            assert s["selected"] == tasks
        await t.close()
    run(scenario())


def test_after_a_success_only_the_host_chooses_the_next_mission():
    async def scenario():
        t = await table()
        await t.prepare()
        await t.host(ALICE, "begin")
        t.engine._finish("success", "fixture")
        t.engine.s["revision"] += 1
        said = await t.act(CAROL, "propose", proposal={"kind": "next", "mission": 2})
        assert [m["msg"] for m in said] == [HOST_ONLY["next"]]
        assert [m["code"] for m in await t.host(ALICE, "retry", keep=True)] == ["phase"]
        assert [m["code"] for m in await t.host(ALICE, "next", mission=999)] == ["mission"]
        assert await t.host(ALICE, "next", mission=2) == []
        assert t.engine.s["mission"]["id"] == 2 and t.engine.s["result"] is None
        await t.close()
    run(scenario())


# ---- succession and reconnect ------------------------------------------------------------------

def test_when_the_party_moves_the_host_role_the_game_follows_with_no_message():
    async def scenario():
        t = await table(host=ALICE)
        await t.prepare()
        t.party_host = BOB                                  # the Party moved the role; no message
        assert [m["code"] for m in await t.host(ALICE, "begin", host=False)] == ["host"]
        assert t.engine.s["phase"] == "assistance"
        assert await t.host(BOB, "begin") == []
        assert t.engine.s["phase"] == "before_trick"
        t.engine._finish("failed", "fixture")
        t.engine.s["revision"] += 1
        assert [m["code"] for m in await t.host(ALICE, "retry", host=False, keep=True)] == ["host"]
        assert await t.host(BOB, "retry", keep=True) == []
        assert not hasattr(t.b.session, "host") and not hasattr(t.engine, "host")   # nothing kept
        assert "host" not in t.engine.s
        await t.close()
    run(scenario())


def test_a_former_host_is_refused_at_once_whatever_tickets_they_kept():
    """AVR-275: tickets fetched while host still say `host: true` for their 120 s. They are worth
    nothing the moment the Party moves the role, because the Party is asked at the action."""
    async def scenario():
        t = await table(host=ALICE)
        await t.prepare()
        hoard = [ticket(ALICE, True) for _ in range(4)]     # all valid, unspent, claiming host
        action = lambda: {"t": "lifecycle", "decision": {"kind": "begin"},
                          "attempt": t.engine.s["attempt"], "revision": t.engine.s["revision"]}
        t.party_host = BOB
        before = t.engine.s["revision"]
        for kept in hoard:
            said = await t.send(ALICE, {"t": "host", "ticket": kept, "action": action()})
            assert [(m["code"], m["msg"]) for m in said] == [("host", "Only the Party Host can do that.")]
        assert t.engine.s["revision"] == before and t.engine.s["phase"] == "assistance"
        assert await t.host(BOB, "begin") == []             # the new host, at once
        # and back again: the role is whatever the Party says at that moment
        t.engine._finish("failed", "fixture")
        t.engine.s["revision"] += 1
        t.party_host = ALICE
        assert [m["code"] for m in await t.host(BOB, "retry", keep=True)] == ["host"]
        assert await t.host(ALICE, "retry", keep=True) == []
        await t.close()
    run(scenario())


def test_no_answer_from_the_party_is_a_refusal_never_a_yes():
    async def scenario():
        t = await table(host=ALICE)
        await t.prepare()
        before = t.engine.s["revision"]
        t.party_up = False                                  # down, slow, or refusing
        said = await t.host(ALICE, "begin")
        assert [(m["code"], m["msg"]) for m in said] == [("host", "The Party could not confirm its Host. Try again.")]
        other = proto.GameSide(KEY, "expo")
        t.party_up = True
        for forge in (lambda q: "aps0.not.an-answer",
                      lambda q: proto.host_answer(proto.new_key(), q, True),              # another key
                      lambda q: proto.host_answer(KEY, dict(q, pid=BOB), True),           # about someone else
                      lambda q: proto.host_answer(KEY, dict(q, nonce="0" * 24), True),    # to another question
                      lambda q: proto.host_answer(KEY, dict(q, sid="session-" + "9" * 32), True),
                      lambda q: proto.seal(KEY, dict(q))):                                # the question itself
            t.forge = forge
            assert [m["code"] for m in await t.host(ALICE, "begin")] == ["host"]
        assert t.engine.s["revision"] == before and t.engine.s["phase"] == "assistance"
        t.forge = None
        assert await t.host(ALICE, "begin") == []
        await t.close()
    run(scenario())


def test_a_round_that_ends_while_the_party_is_being_asked_is_not_moved_on():
    """The Party is asked off the room's lock. If the session ends or is launched again before
    the answer arrives, a yes for the old session does nothing, in either order."""
    async def scenario():
        for relaunch in (False, True):
            t = await table(host=ALICE)
            await t.prepare()
            answer, loop, asked = t.b.ask_host, asyncio.get_running_loop(), t.asked

            def slow(url, question):
                yes = answer(url, question)                   # the Party said yes, for that session
                async def over():
                    await t.b.party_end(proto.end_message(KEY, "expo", SID))
                    if relaunch:
                        await t.b.party_launch(proto.launch_message(
                            KEY, "expo", "session-" + "7" * 32, roster(*[(p, n, "player") for p, n in PLAYERS])))
                asyncio.run_coroutine_threadsafe(over(), loop).result(5)
                return yes
            t.b.ask_host = slow
            await t.host(ALICE, "begin")
            assert t.b.session.engine is None and t.asked == asked + 1    # nothing began anywhere
            await t.close()
    run(scenario())


def test_an_error_while_asking_the_party_refuses_and_the_room_carries_on():
    async def scenario():
        t = await table(host=ALICE)
        await t.prepare()
        before = t.engine.s["revision"]

        def broken(url, question):
            raise RuntimeError("the party fell over")
        answer, t.b.ask_host = t.b.ask_host, broken
        await t.host(ALICE, "begin")
        assert t.engine.s["revision"] == before and t.engine.s["phase"] == "assistance"
        t.b.ask_host = answer
        assert await t.host(ALICE, "begin") == []                          # and the next one works
        await t.close()
    run(scenario())


def test_when_the_transition_is_over_a_party_without_the_claim_cannot_vote_the_table_on(monkeypatch):
    """HOST_CLAIM_TRANSITION False: Begin, Retry and Next are the Party Host's in every Party
    round. A Party that cannot say who that is leaves only its own end."""
    monkeypatch.setattr(expo_game, "HOST_CLAIM_TRANSITION", False)

    async def scenario():
        t = await table(claims=False)
        view = t.socks[ALICE][0].last_state()["game"]
        assert view["lifecycle"] == "host" and view["lifecycle_transitional"] is False
        await t.prepare()
        said = await t.act(ALICE, "propose", proposal={"kind": "begin"})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["begin"])]
        assert [m["code"] for m in await t.host(ALICE, "begin", host=None)] == ["host"]
        assert t.engine.s["phase"] == "assistance" and t.engine.s["proposal"] is None
        await t.b.party_end(proto.end_message(KEY, "expo", SID))
        assert t.b.session.engine is None
        await t.close()
    run(scenario())


def test_the_question_goes_to_the_party_over_http_and_only_an_answer_comes_back():
    """core/party_session.ask_host against a real listener: the answer string, or None."""
    import http.server
    import json
    import threading

    from core import party_session
    replies, seen = [], []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            status, body = replies.pop(0)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        replies[:] = [(200, b'{"ok": true, "answer": "aps0.a.b"}'), (200, b'{"ok": true}'), (200, b'{"answer": 1}'),
                      (200, b"not json"), (200, b"[]"), (403, b'{"error": "bad_message"}'), (409, b'{"answer": "aps0.a.b"}')]
        assert party_session.ask_host(base, "the-question") == "aps0.a.b"
        assert seen == [(party_session.HOST_PATH, {"message": "the-question"})]
        for _ in range(6):                                  # nothing but a 200 with an answer counts
            assert party_session.ask_host(base, "the-question") is None
    finally:
        server.shutdown()
        server.server_close()
    assert party_session.ask_host(base, "the-question", timeout=0.5) is None       # nobody there
    assert party_session.ask_host(None, "the-question") is None                    # no party URL


def test_the_host_gets_begin_retry_and_next_and_nothing_else():
    """The host's capability is those three commands. Every other verb through the host message,
    with the Party's full agreement, is refused and changes nothing."""
    async def scenario():
        t = await table(host=ALICE)
        await t.prepare()
        s = t.engine.s
        base = {"attempt": s["attempt"], "revision": s["revision"]}
        task = next(iter(s["assignments"]), None)
        attempts = [
            {"t": "lifecycle", "decision": {"kind": "end"}, **base},
            {"t": "lifecycle", "decision": {"kind": "distress", "direction": "left"}, **base},
            {"t": "lifecycle", "decision": {"kind": "assign", "task": task, "owner": t.pid(BOB)}, **base},
            {"t": "lifecycle", "decision": {"kind": "begin", "extra": 1}, **base},
            {"t": "lifecycle", "decision": {"kind": "begin"}, **base, "actor": t.pid(BOB)},
            {"t": "propose", "proposal": {"kind": "begin"}, **base, "request": "x"},
            {"t": "confirm", "yes": True, **base, "request": "x"},
            {"t": "play_card", "card": "blue-1", **base, "request": "x"},
            {"t": "communicate", "card": "blue-1", "meaning": "only", **base, "request": "x"},
            {"t": "choose_task", "task": task, **base, "request": "x"},
            {"t": "settings", "patch": {"mission": 2}},
            {"t": "again"}, {"t": "start"}, {},
        ]
        before = t.engine.snapshot()
        for action in attempts:
            said = await t.send(ALICE, {"t": "host", "ticket": ticket(ALICE, True), "action": action})
            assert len(said) == 1 and said[0]["code"] in ("strategic", "payload"), (action, said)
        for junk in (None, "begin", 7, ["lifecycle"]):       # not an action at all
            said = await t.send(ALICE, {"t": "host", "ticket": ticket(ALICE, True), "action": junk})
            assert [m["code"] for m in said] == ["host"]
        assert t.engine.snapshot() == before
        await t.close()
    run(scenario())


def test_a_host_who_reconnects_is_still_the_host_and_the_table_waits_meanwhile():
    async def scenario():
        t = await table()
        await t.prepare()
        ws, task = t.socks[ALICE]
        await ws.close()
        await task
        await settle()
        assert t.pid(ALICE) in t.engine.s["away"]
        # nobody takes the role by being present: the Party has not moved it
        assert [m["code"] for m in await t.host(BOB, "begin", host=False)] == ["host"]
        t.socks[ALICE] = await connect(t.b, {"t": "hello", "ticket": ticket(ALICE, True)})
        assert t.engine.s["away"] == []
        assert await t.host(ALICE, "begin") == []
        assert t.engine.s["phase"] == "before_trick"
        await t.close()
    run(scenario())


def test_the_table_does_not_move_on_while_a_crew_member_is_away():
    async def scenario():
        t = await table()
        await t.prepare()
        ws, task = t.socks.pop(CAROL)
        await ws.close()
        await task
        await settle()
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["paused"]
        assert t.engine.s["phase"] == "assistance"
        t.engine._finish("failed", "fixture")
        t.engine.s["revision"] += 1
        assert [m["code"] for m in await t.host(ALICE, "retry", keep=True)] == ["paused"]
        # AVR-240 owns recovery. Until then nobody is stranded: the Party Host ends EXPO from the
        # Party, whoever is away, and every phone is told.
        await t.b.party_end(proto.end_message(KEY, "expo", SID))
        assert t.b.session.engine is None and t.b.party_room_sid is None
        assert any(m.get("kind") == "party_ended" for m in t.socks[BOB][0].sent)
        await t.close()
    run(scenario())


# ---- ending, and a Party that does not say who its host is -------------------------------------

@pytest.mark.parametrize("claims", [True, False])
def test_no_seat_ends_a_party_round_from_inside_the_game(claims):
    async def scenario():
        t = await table(claims=claims)
        said = await t.act(ALICE, "propose", proposal={"kind": "end"})
        assert [(m["code"], m["msg"]) for m in said] == [("host", PARTY_END)]
        assert t.engine.s["proposal"] is None and t.b.session.phase == "allocation"
        # the Party's own end releases the room whatever the table was doing
        await t.b.party_end(proto.end_message(KEY, "expo", SID))
        assert t.b.session.engine is None and t.b.party_room_sid is None
        assert any(m.get("kind") == "party_ended" for m in t.socks[BOB][0].sent)
        await t.close()
    run(scenario())


def test_under_a_party_that_does_not_name_its_host_the_crew_still_agrees():
    async def scenario():
        t = await table(claims=False)
        state = t.socks[ALICE][0].last_state()
        assert state["party_round"] and not state["party_host"]
        assert state["game"]["lifecycle"] == "crew"
        # transitional, and said so: to the players, and once in the server's log
        assert state["game"]["lifecycle_transitional"] is True
        assert t.b._no_host_claim_sid == SID
        await t.prepare()
        assert [m["code"] for m in await t.host(ALICE, "begin", host=None)] == ["host"]
        assert await t.act(ALICE, "propose", proposal={"kind": "begin"}) == []
        assert await t.act(BOB, "confirm", yes=True) == []
        assert t.engine.s["phase"] == "assistance"
        assert await t.act(CAROL, "confirm", yes=True) == []
        assert t.engine.s["phase"] == "before_trick"
        await t.close()
    run(scenario())


def test_a_standalone_table_has_no_party_host():
    s = ExpoSession(random.Random(4))
    for name in ("a-token-1", "b-token-2", "c-token-3"):
        s.join(name, name)
        s.set_ready(name, True)
    s.start("a-token-1")
    s.tick(s.gen)
    view = s.game_state("a-token-1")
    assert view["lifecycle"] == "crew" and view["lifecycle_transitional"] is False and view["begin_at"] is None
    with pytest.raises(HostRefused):
        s.host_action({"t": "lifecycle", "decision": {"kind": "begin"}, "attempt": 1, "revision": 0})


# ---- the engine's lifecycle command ------------------------------------------------------------

def lifecycle(e, kind, **kw):
    over = {k: kw.pop(k) for k in ("attempt", "revision") if k in kw}
    return {"t": "lifecycle", "decision": {"kind": kind, **kw},
            "attempt": e.s["attempt"], "revision": e.s["revision"], **over}


def ready_engine():
    e = Engine(["p1", "p2", "p3"], random.Random(7))
    while e.s["phase"] == "allocation":
        seat = e.selector()
        task = next((k for k in e.s["pool"] if e.eligible(k, seat)), None)
        e.apply(seat, {"t": "choose_task" if task else "pass_task", "attempt": e.s["attempt"],
                       "revision": e.s["revision"], "request": str(e.s["revision"]),
                       **({"task": task} if task else {})})
    assert e.s["phase"] == "assistance"
    return e


@pytest.mark.parametrize("msg,code", [
    (lambda e: lifecycle(e, "begin", revision=e.s["revision"] - 1), "stale"),
    (lambda e: lifecycle(e, "begin", attempt=e.s["attempt"] + 1), "stale"),
    (lambda e: lifecycle(e, "retry", keep=True), "phase"),
    (lambda e: lifecycle(e, "next", mission=2), "phase"),
    (lambda e: lifecycle(e, "retry"), "payload"),
    (lambda e: lifecycle(e, "begin", extra=1), "payload"),
    (lambda e: lifecycle(e, "end"), "strategic"),
    (lambda e: lifecycle(e, "distress", direction="left"), "strategic"),
    (lambda e: {**lifecycle(e, "begin"), "request": "x"}, "payload"),
    (lambda e: {**lifecycle(e, "begin"), "t": "propose"}, "payload"),
    (lambda e: "begin", "payload"),
])
def test_a_refused_lifecycle_command_changes_nothing(msg, code):
    e = ready_engine()
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        e.lifecycle(msg(e))
    assert refused.value.code == code and e.snapshot() == before


def test_the_lifecycle_command_is_one_revision_and_leaves_no_decision_behind():
    e = ready_engine()
    revision = e.s["revision"]
    assert e.lifecycle(lifecycle(e, "begin"), now=5) is True
    assert e.s["phase"] == "before_trick" and e.s["proposal"] is None and e.s["revision"] == revision + 1
    with pytest.raises(Invalid) as again:
        e.lifecycle(lifecycle(e, "begin"))
    assert again.value.code == "phase"


# ---- setup before the first deal (AVR-245, owner decisions 2026-10-05) --------------------------
# A Party round skips EXPO's lobby, so the mission and the timed setting are chosen inside EXPO
# before anything is dealt. The Party launch contract is untouched. Setup is one more routine step
# of the table's life, committed the way the next mission is after a success: by the Party Host,
# or by the whole crew where the crew moves the table on. Tonoja's seat is not part of it: the
# rulebook gives it to the players (R p22), so with two humans the two of them agree it as a crew
# decision of their own, and nothing is dealt until they have. Nothing ever starts by itself.

import json

from games.expo import content
from games.expo.engine import ANSWER_FIRST, DECIDING, PAUSED, SEAT_FIRST, SEAT_NOT_SETUP
from games.expo.rules import DECK

CREWS = (["p1", "p2"], ["p1", "p2", "p3"], ["p1", "p2", "p3", "p4"], ["p1", "p2", "p3", "p4", "p5"])
TWO = ["p1", "p2"]


def setup_engine(humans=("p1", "p2", "p3"), seed=7):
    return Engine(list(humans), random.Random(seed), setup=True)


def set_up(e, **chosen):
    return e.lifecycle(lifecycle(e, "setup", **{**SETUP, **chosen}))


def seat_msg(e, t, request, **kw):
    return {"t": t, "attempt": 0, "revision": e.s["revision"], "request": request, **kw}


def propose_seat(e, who, position, request=None):
    return e.apply(who, seat_msg(e, "propose", request or f"seat-{e.s['revision']}",
                                 proposal={"kind": "tonoja_seat", "position": position}))


def answer(e, who, yes=True):
    return e.apply(who, seat_msg(e, "confirm", f"answer-{e.s['revision']}", yes=yes))


def agree(e, position=SEAT):
    """The two players agree where Tonoja sits: one proposes, the other confirms."""
    a, b = e.s["humans"]
    assert propose_seat(e, a, position) and answer(e, b)
    assert e.s["setup"]["tonoja_seat"] == position and e.s["proposal"] is None
    return e


def two_engine(seed=7, position=SEAT):
    return agree(setup_engine(TWO, seed), position)


@pytest.mark.parametrize("humans", CREWS, ids=lambda h: f"{len(h)}-humans")
def test_setting_up_what_is_offered_deals_exactly_the_table_a_direct_start_deals(humans):
    """The proof that nothing else changed: confirming mission 1, untimed (and, for two players,
    their agreement on the seat offered for Tonoja, after both of them) gives the deal, the
    tasks, the captain, the random state and every view of a table started without a setup step,
    for the same seed. The one difference is the count of accepted changes: the setup is one,
    and the two players' proposal and confirmation are two more."""
    steps = 3 if len(humans) == 2 else 1
    for seed in range(25):
        direct = Engine(list(humans), random.Random(seed))
        waited = setup_engine(humans, seed)
        assert waited.s["phase"] == "setup"
        if len(humans) == 2:
            agree(waited)
        assert waited.rng.getstate() == random.Random(seed).getstate()      # nothing was drawn
        assert set_up(waited) is True
        a, b = dict(direct.s), dict(waited.s)
        assert (a.pop("revision"), b.pop("revision")) == (0, steps)
        assert a == b and direct.rng.getstate() == waited.rng.getstate()
        for viewer in list(humans) + [None]:
            va, vb = direct.view(viewer), waited.view(viewer)
            assert (va.pop("revision"), vb.pop("revision")) == (0, steps)
            assert va == vb


@pytest.mark.parametrize("humans", CREWS[1:], ids=lambda h: f"{len(h)}-humans")
def test_three_to_five_humans_have_no_seat_to_agree_and_nothing_changed_for_them(humans):
    """No Tonoja, no seat, no extra step: the host's setup deals at once, as it did before the
    seat became the players' decision, and nobody can open a decision about a seat."""
    e = setup_engine(humans, 3)
    view = e.view(None)["setup"]
    assert (view["tonoja"], view["tonoja_seat"], view["waiting"], view["seat_waiting"], view["seat_proposal"]) \
        == (False, None, None, None, None)
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        propose_seat(e, humans[0], 2)
    assert refused.value.code == "seat" and str(refused.value) == "Tonoja sits only with a crew of two players."
    assert e.snapshot() == before
    assert set_up(e, mission=5) is True
    assert e.s == {**Engine(list(humans), random.Random(3), 5).s, "revision": 1}
    assert "tonoja" not in e.s["seats"]


def test_setup_chooses_the_mission_and_the_clock_and_the_players_choose_tonojas_seat():
    for position in (0, 1, 2):
        e = setup_engine(TWO)
        assert e.s["seats"] == TWO                          # Tonoja has no seat until one is agreed
        agree(e, position)
        assert e.s["seats"] == TWO                          # and takes it only at the deal
        set_up(e, mission=5)
        assert e.s["seats"].index("tonoja") == position and e.s["mission"]["id"] == 5
        assert e.s == {**Engine(TWO, random.Random(7), 5, False, position).s, "revision": 3}
    e = setup_engine()
    set_up(e, mission=16, timed=True)
    assert e.s["timed"] is True and e.s["mission"]["seconds"] == 150 and "tonoja" not in e.s["seats"]
    assert e.s == {**Engine(["p1", "p2", "p3"], random.Random(7), 16, True).s, "revision": 1}
    e = setup_engine()
    set_up(e, mission=16)
    assert e.s["timed"] is False and e.s["mission"]["seconds"] is None


def lobby_answer(humans, mission, timed):
    """What a standalone lobby does with that choice: 'not offered' when its settings refuse the
    mission, the sentence Start is refused with, or None when the table starts."""
    s = ExpoSession(random.Random(1))
    tokens = [f"tok-{i}" for i in range(humans)]
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.set_settings(tokens[0], {"timed": timed})
    s.set_settings(tokens[0], {"mission": mission})
    if s.settings["mission"] != mission:
        return "not offered"
    said = [f["msg"] for f in s.start(tokens[0]) if f["kind"] == "invalid"]
    return said[0] if said else None


@pytest.mark.parametrize("humans", (2, 3, 5))
def test_setup_allows_exactly_what_the_standalone_lobby_allows(humans):
    crew = [f"p{i}" for i in range(humans)]
    fresh = lambda: agree(setup_engine(crew)) if humans == 2 else setup_engine(crew)
    offered = {m["id"] for m in setup_engine(crew).view()["setup"]["missions"] if m["enabled"]}
    accepted = set()
    for mission in range(0, 52):
        for timed in (False, True):
            lobby = lobby_answer(humans, mission, timed)
            e = fresh()
            before = e.snapshot()
            try:
                set_up(e, mission=mission, timed=timed)
                said = None
                accepted.add(mission)
            except Invalid as refused:
                assert refused.code == "mission" and e.snapshot() == before
                said = str(refused)
            if lobby == "not offered":
                assert said is not None, (mission, timed)
            else:
                assert said == lobby, (mission, timed)       # the same words, or the same yes
    assert accepted == offered                               # and the view offers exactly those


@pytest.mark.parametrize("decision,code", [
    ({"mission": 1}, "payload"),                                      # a field missing
    ({**SETUP, "extra": 1}, "payload"),
    ({**SETUP, "position": 2}, "payload"),                            # the seat is not smuggled in
    ({**SETUP, "tonoja_seat": 2}, "payload"),
    ({**SETUP, "mission": True}, "payload"),                          # a boolean is not a mission
    ({**SETUP, "mission": "1"}, "payload"),
    ({**SETUP, "timed": 1}, "payload"),
    ({**SETUP, "tonoja_position": 2}, "seat"),                        # what the setup used to carry
    ({**SETUP, "tonoja_position": 0}, "seat"),
    ({"tonoja_position": 2}, "seat"),
    ({**SETUP, "mission": 3}, "mission"),                             # blocked content stays blocked
    ({**SETUP, "mission": 51}, "mission"),
])
def test_a_refused_setup_changes_nothing_and_deals_nothing(decision, code):
    for e in (setup_engine(), two_engine(position=1)):
        before = e.snapshot()
        with pytest.raises(Invalid) as refused:
            e.lifecycle({"t": "lifecycle", "decision": {"kind": "setup", **decision}, "attempt": 0,
                         "revision": e.s["revision"]})
        assert refused.value.code == code and e.snapshot() == before and e.s["phase"] == "setup"
        if "tonoja_position" in decision:
            assert str(refused.value) == SEAT_NOT_SETUP     # in words, at any crew size, never trimmed
        # and a seat may not propose it that way either
        with pytest.raises(Invalid) as proposed:
            e.apply("p1", seat_msg(e, "propose", "x", proposal={"kind": "setup", **decision}))
        assert proposed.value.code == code and e.snapshot() == before


def test_the_setup_never_carries_or_decides_tonojas_seat():
    """Owner decision 2: the seat is the two players'. A setup that names one is refused, whoever
    sends it and whatever the players have agreed; it never overrides and is never read."""
    e = setup_engine(TWO)
    for sender in (lambda d: e.lifecycle(lifecycle(e, "setup", **d)),
                   lambda d: e.apply("p1", seat_msg(e, "propose", "x", proposal={"kind": "setup", **d}))):
        with pytest.raises(Invalid) as refused:
            sender({**SETUP, "tonoja_position": 0})
        assert (refused.value.code, str(refused.value)) == ("seat", SEAT_NOT_SETUP)
    assert e.s["setup"]["tonoja_seat"] is None and e.s["revision"] == 0
    agree(e, 1)
    with pytest.raises(Invalid) as refused:
        e.lifecycle(lifecycle(e, "setup", **SETUP, tonoja_position=0))
    assert str(refused.value) == SEAT_NOT_SETUP and e.s["setup"]["tonoja_seat"] == 1
    # nor is the seat a step of the table's life: the lifecycle authority cannot commit it
    with pytest.raises(Invalid) as refused:
        e.lifecycle(lifecycle(e, "tonoja_seat", position=0))
    assert (refused.value.code, str(refused.value)) == ("strategic", "The crew decides that together.")
    assert e.s["setup"]["tonoja_seat"] == 1 and e.s["phase"] == "setup"


def test_two_players_are_dealt_nothing_until_they_have_agreed_tonojas_seat():
    """Decisions 2 and 3: no seat by default, however long the table waits; agreement on the
    seat that is offered counts, and it has to be made (one proposes, the other confirms)."""
    e = setup_engine(TWO)
    start = e.snapshot()
    assert e.s["setup"] == {**SETUP, "tonoja_position": SEAT, "tonoja_seat": None}
    for _ in range(3):
        e.observe_time(10 ** 9)                             # no clock deals a table
        with pytest.raises(Invalid) as refused:
            set_up(e)
        assert (refused.value.code, str(refused.value)) == ("seat", SEAT_FIRST)
    with pytest.raises(Invalid) as refused:                 # a seat cannot propose past it either
        e.apply("p1", seat_msg(e, "propose", "x", proposal={"kind": "setup", **SETUP}))
    assert (refused.value.code, str(refused.value)) == ("seat", SEAT_FIRST)
    assert e.snapshot() == start and e.view(None)["setup"]["waiting"] == SEAT_FIRST
    # one player proposing the offered seat is not agreement
    assert propose_seat(e, "p1", SEAT)
    assert e.s["setup"]["tonoja_seat"] is None
    with pytest.raises(Invalid) as refused:
        set_up(e)
    assert (refused.value.code, str(refused.value)) == ("vote", DECIDING)      # the existing gate
    assert answer(e, "p2")
    assert e.s["setup"]["tonoja_seat"] == SEAT and e.view(None)["setup"]["waiting"] is None
    assert e.rng.getstate() == random.Random(7).getstate()  # and still nothing is dealt
    assert set_up(e) is True and e.s["seats"] == ["p1", "p2", "tonoja"]


@pytest.mark.parametrize("position,code", [(3, "seat"), (-1, "seat"), (True, "payload"), (1.0, "payload"),
                                           ("2", "payload"), (None, "payload")])
def test_a_seat_that_is_not_a_seat_is_refused(position, code):
    e = setup_engine(TWO)
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        propose_seat(e, "p1", position)
    assert refused.value.code == code and e.snapshot() == before
    with pytest.raises(Invalid) as refused:
        e.apply("p1", seat_msg(e, "propose", "y", proposal={"kind": "tonoja_seat", "position": 2, "extra": 1}))
    assert refused.value.code == "payload" and e.snapshot() == before


def test_the_seat_is_agreed_by_the_existing_crew_decision_rules():
    e = setup_engine(TWO)
    msg = seat_msg(e, "propose", "one", proposal={"kind": "tonoja_seat", "position": 1})
    assert e.apply("p1", msg) is True
    assert e.s["proposal"] == {"payload": {"kind": "tonoja_seat", "position": 1}, "votes": ["p1"]}
    view = e.view(None)["setup"]
    assert view["seat_proposal"] == {"position": 1, "by": "p1", "asked": ["p2"]}
    assert (view["tonoja_seat"], view["waiting"], view["seat_waiting"]) == (None, DECIDING, ANSWER_FIRST)
    pending = e.snapshot()
    assert e.apply("p1", msg) is False and e.snapshot() == pending          # a replay is nothing
    with pytest.raises(Invalid) as reused:                  # the same id for another request
        e.apply("p1", {**msg, "proposal": {"kind": "tonoja_seat", "position": 0}})
    assert reused.value.code == "request"
    for who, sent, code in (("p1", seat_msg(e, "confirm", "own", yes=True), "vote"),    # one vote each
                            ("p2", seat_msg(e, "propose", "two", proposal={"kind": "tonoja_seat", "position": 0}), "vote"),
                            ("p3", seat_msg(e, "confirm", "who", yes=True), "actor"),   # nobody else is asked
                            (None, seat_msg(e, "confirm", "none", yes=True), "actor"),
                            ("p2", {**seat_msg(e, "confirm", "old", yes=True), "revision": 0}, "stale")):
        with pytest.raises(Invalid) as refused:
            e.apply(who, sent)
        assert refused.value.code == code and e.snapshot() == pending
    # one decline and no seat is agreed
    decline = seat_msg(e, "confirm", "no", yes=False)
    assert e.apply("p2", decline) is True and e.apply("p2", decline) is False
    assert e.s["proposal"] is None and e.s["setup"]["tonoja_seat"] is None
    assert e.view(None)["setup"]["waiting"] == SEAT_FIRST and e.view(None)["setup"]["seat_proposal"] is None
    # either player may propose; the other confirms; a duplicate confirmation is nothing
    assert propose_seat(e, "p2", 0)
    yes = seat_msg(e, "confirm", "yes", yes=True)
    assert e.apply("p1", yes) is True and e.apply("p1", yes) is False
    assert e.s["setup"]["tonoja_seat"] == 0 and e.s["proposal"] is None and e.s["phase"] == "setup"
    assert e.rng.getstate() == random.Random(7).getstate()  # agreeing a seat deals nothing


def test_the_players_may_agree_another_seat_until_the_deal_and_not_after():
    e = two_engine(position=2)
    agree(e, 0)                                             # a new proposal and its confirmation
    assert e.s["setup"]["tonoja_seat"] == 0
    assert propose_seat(e, "p2", 1)
    assert e.s["setup"]["tonoja_seat"] == 0                 # a proposal alone changes nothing,
    with pytest.raises(Invalid) as refused:
        set_up(e)
    assert (refused.value.code, str(refused.value)) == ("vote", DECIDING)      # but it holds the deal
    assert answer(e, "p1", yes=False)
    assert e.s["setup"]["tonoja_seat"] == 0                 # declined: what they agreed still stands
    assert set_up(e, mission=2) is True and e.s["seats"] == ["tonoja", "p1", "p2"]
    dealt = e.snapshot()
    with pytest.raises(Invalid) as late:
        e.apply("p1", {"t": "propose", "attempt": 1, "revision": e.s["revision"], "request": "late",
                       "proposal": {"kind": "tonoja_seat", "position": 2}})
    assert (late.value.code, str(late.value)) == ("phase", "Tonoja’s seat is decided before the first deal.")
    assert e.snapshot() == dealt


def test_an_away_player_pauses_the_seat_agreement():
    e = setup_engine(TWO)
    e.s["away"] = ["p2"]
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        propose_seat(e, "p1", 2)
    assert (refused.value.code, str(refused.value)) == ("paused", PAUSED) and e.snapshot() == before
    view = e.view("p1")["setup"]
    assert view["waiting"] == PAUSED and view["seat_waiting"] == PAUSED
    e.s["away"] = []
    assert propose_seat(e, "p1", 2)
    e.s["away"] = ["p1"]                                    # the proposer drops: the answer waits too
    with pytest.raises(Invalid) as refused:
        answer(e, "p2")
    assert refused.value.code == "paused" and e.s["setup"]["tonoja_seat"] is None
    assert e.view(None)["setup"]["seat_proposal"] == {"position": 2, "by": "p1", "asked": ["p2"]}
    e.s["away"] = []
    assert answer(e, "p2") and e.s["setup"]["tonoja_seat"] == 2


def test_setup_happens_once_and_a_repeat_or_a_late_one_is_refused():
    e = setup_engine()
    with pytest.raises(Invalid) as early:
        e.lifecycle(lifecycle(e, "begin"))
    assert early.value.code == "phase"                      # nothing begins before the deal
    msg = lifecycle(e, "setup", **SETUP)
    assert e.lifecycle(msg) is True and (e.s["attempt"], e.s["revision"]) == (1, 1)
    assert e.s["proposal"] is None and "setup" not in e.s
    dealt = e.snapshot()
    with pytest.raises(Invalid) as replay:
        e.lifecycle(msg)
    assert replay.value.code == "stale"
    with pytest.raises(Invalid) as again:
        e.lifecycle(lifecycle(e, "setup", **dict(SETUP, mission=5)))
    assert again.value.code == "phase" and e.snapshot() == dealt
    # a table that opened without a setup step has none to take, whoever asks
    for humans in (["p1", "p2", "p3"], TWO):
        direct = Engine(humans, random.Random(7))
        for proposal in ({"kind": "setup", **SETUP}, {"kind": "tonoja_seat", "position": 0}):
            with pytest.raises(Invalid) as none:
                direct.apply("p1", {"t": "propose", "proposal": proposal,
                                    "attempt": 1, "revision": 0, "request": "x"})
            assert none.value.code == "phase" and direct.s["proposal"] is None


def test_no_card_task_or_table_command_works_before_the_deal():
    proposals = ({"kind": "begin"}, {"kind": "end"}, {"kind": "retry", "keep": True}, {"kind": "next", "mission": 2},
                 {"kind": "distress", "direction": "left"}, {"kind": "assign", "owner": "p1", "task": "all"})
    for e in (setup_engine(), setup_engine(TWO), two_engine()):
        before = e.snapshot()
        for msg in ({"t": "play_card", "card": "blue:1"}, {"t": "choose_task", "task": "x"}, {"t": "pass_task"},
                    {"t": "volunteer", "yes": True}, {"t": "predict", "task": "x", "count": 0},
                    {"t": "pass_card", "card": "blue:1"}, {"t": "communicate", "card": "blue:1", "assertion": "only"},
                    {"t": "confirm", "yes": True}, *({"t": "propose", "proposal": p} for p in proposals)):
            with pytest.raises(Invalid) as refused:
                e.apply("p1", {**msg, "attempt": 0, "revision": e.s["revision"], "request": "x"})
            assert refused.value.code not in ("snapshot", "payload"), msg      # refused by a rule, cleanly
            assert e.snapshot() == before, msg


def test_the_setup_view_is_public_and_holds_nothing_of_a_deal():
    e = setup_engine(TWO)
    public = e.view(None)
    assert set(public) == {"kind", "attempt", "revision", "stage", "mission", "seats", "away", "proposal",
                           "result", "expiry", "log", "setup", "me",
                           "resolving", "cause", "events", "event_seq",       # AVR-246: in every view
                           "trick_leading"}                                   # AVR-267: in every view, none before a deal
    assert public["trick_leading"] is None
    assert public["stage"] == "setup" and public["me"] is None and public["mission"] is None
    assert public["setup"] == {**SETUP, "tonoja_position": SEAT, "tonoja_seat": None, "tonoja": True,
                               "waiting": SEAT_FIRST, "seat_waiting": None, "seat_proposal": None,
                               "missions": content.catalog(2)}
    for seat in TWO:
        assert e.view(seat) == {**public, "me": {"seat": seat}}             # a seat learns only its seat
    # the same while a seat is proposed and once it is agreed: who proposed and who must answer
    # are public, and a player is shown nothing a watcher is not
    propose_seat(e, "p2", 0)
    asked = e.view(None)
    assert asked["setup"]["seat_proposal"] == {"position": 0, "by": "p2", "asked": ["p1"]}
    assert asked["proposal"] == {"payload": {"kind": "tonoja_seat", "position": 0}, "votes": ["p2"]}
    answer(e, "p1")
    agreed = e.view(None)
    assert (agreed["setup"]["tonoja_seat"], agreed["setup"]["waiting"], agreed["setup"]["seat_proposal"]) == (0, None, None)
    for view in (asked, agreed):
        assert set(view["setup"]) == set(public["setup"])
    for seat in TWO:
        assert e.view(seat) == {**agreed, "me": {"seat": seat}}
    said = json.dumps([e.view(v) for v in ("p1", "p2", None)] + [public, asked]) + json.dumps(e.s)
    assert not any(card in said for card in DECK)           # no card exists yet, so none can leak
    assert not {"hands", "columns", "captain", "pool", "deck_order"} & set(e.s) and e.s["deck"] == []
    three = setup_engine().view(None)["setup"]                              # no seat to agree for three
    assert (three["tonoja"], three["tonoja_seat"], three["waiting"], three["seat_waiting"]) == (False, None, None, None)


def test_a_table_saved_while_the_seat_is_being_agreed_restores_and_then_deals_the_same_table():
    e = setup_engine(TWO, seed=5)
    propose_seat(e, "p1", 0)
    saved = json.loads(json.dumps(e.snapshot()))
    assert saved["state"]["version"] == 1                    # the format did not change
    assert set(saved["state"]["setup"]) == {"mission", "timed", "tonoja_position", "tonoja_seat"}
    back = Engine.restore(saved)
    assert back.s == e.s and back.view("p2") == e.view("p2")
    assert back.view("p2")["setup"]["seat_proposal"] == {"position": 0, "by": "p1", "asked": ["p2"]}
    for table_ in (e, back):
        assert table_.apply("p2", {"t": "confirm", "yes": True, "attempt": 0, "revision": 1, "request": "b"})
    assert back.s == e.s and back.s["setup"]["tonoja_seat"] == 0
    back = Engine.restore(json.loads(json.dumps(back.snapshot())))          # and once it is agreed
    assert back.s == e.s and back.view(None) == e.view(None)
    for table_ in (e, back):
        assert set_up(table_, mission=5)
    assert back.s == e.s and back.rng.getstate() == e.rng.getstate()
    assert "setup" not in e.s and e.s["mission"]["id"] == 5 and e.s["seats"][0] == "tonoja"
    assert e.s == {**Engine(TWO, random.Random(5), 5, False, 0).s, "revision": e.s["revision"]}
    # a dealt table is saved with the keys it always had: nothing of the setup stays behind
    dealt = Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert set(dealt.s) == set(Engine(TWO, random.Random(1)).s)


def test_a_setup_proposal_saved_under_a_party_without_a_host_restores_too():
    e = two_engine(seed=5, position=1)
    offer = {"kind": "setup", **dict(SETUP, mission=5)}
    e.apply("p1", seat_msg(e, "propose", "a", proposal=offer))
    back = Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert back.s == e.s and back.view("p2")["proposal"]["payload"] == offer
    for table_ in (e, back):
        assert answer(table_, "p2")
    assert back.s == e.s and back.rng.getstate() == e.rng.getstate() and e.s["seats"][1] == "tonoja"


OLD_SETUP = {"mission": 1, "timed": False, "tonoja_position": 2}     # this branch's setup before the seat moved


@pytest.mark.parametrize("humans,forge", [
    (3, lambda s: s.update(phase="allocation")),             # no deal behind it
    (3, lambda s: s.update(attempt=1)),
    (3, lambda s: s.pop("setup")),
    (3, lambda s: s.update(setup={"mission": 1})),
    (3, lambda s: s.update(setup=dict(OLD_SETUP))),          # written before the seat was the players'
    (2, lambda s: s.update(setup=dict(OLD_SETUP))),
    (2, lambda s: s.update(setup=dict(OLD_SETUP), proposal={"payload": {"kind": "setup", **OLD_SETUP}, "votes": ["p1"]})),
    (2, lambda s: s.update(proposal={"payload": {"kind": "setup", **OLD_SETUP}, "votes": ["p1"]})),
    (3, lambda s: s["setup"].update(mission="1")),
    (3, lambda s: s["setup"].update(tonoja_seat=2)),         # a seat agreed where there is no Tonoja
    (2, lambda s: s["setup"].update(tonoja_seat=3)),
    (2, lambda s: s["setup"].update(tonoja_seat=True)),
    (2, lambda s: s["setup"].update(tonoja_seat="2")),
    (3, lambda s: s.update(seats=["p1", "tonoja", "p2", "p3"])),
    (2, lambda s: s.update(seats=["p1", "p2", "tonoja"])),   # seated before the deal
    (3, lambda s: s.update(expiry=5.0)),
    (3, lambda s: s.update(result={"status": "success", "reason": "forged"})),
    (3, lambda s: s.update(proposal={"payload": {"kind": "begin"}, "votes": ["p1"]})),
    (3, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat", "position": 2}, "votes": ["p1"]})),
    (2, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat", "position": 7}, "votes": ["p1"]})),
    (2, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat"}, "votes": ["p1"]})),
    (2, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat", "position": 2}, "votes": ["p9"]})),
    (2, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat", "position": 2}})),
    (2, lambda s: s.update(proposal="tonoja_seat")),
    (2, lambda s: s.update(proposal={"payload": {"kind": "tonoja_seat", "position": 2}, "votes": []})),
], ids=range(25))
def test_a_forged_or_older_setup_snapshot_is_refused_and_never_crashes(humans, forge):
    saved = setup_engine(CREWS[humans - 2]).snapshot()
    Engine.restore(json.loads(json.dumps(saved)))            # as written, it restores
    forge(saved["state"])
    with pytest.raises(Invalid) as refused:                  # Invalid, and nothing else
        Engine.restore(saved)
    assert refused.value.code in ("snapshot", "seat")
    dealt = Engine(["p1", "p2", "p3"], random.Random(7)).snapshot()
    dealt["state"]["phase"] = "setup"                        # a dealt table relabelled
    with pytest.raises(Invalid):
        Engine.restore(dealt)


# ---- the adapter: a Party round, without sockets -----------------------------------------------

def party_room(names=("Alice", "Bob", "Cara"), seed=3, arrive=True):
    s = ExpoSession(random.Random(seed))
    tokens = [f"tok-{n}" for n in names]
    s.party_start(list(zip(tokens, names)))
    for t in tokens if arrive else ():
        s.join(t)
    s.tick(s.gen)
    assert s.phase == "setup" and s.party_round
    return s, tokens


def host_setup(s, **chosen):
    """The Party Host's setup, as core.net hands it over once the Party has confirmed the host."""
    e = s.engine.s
    return s.host_action({"t": "lifecycle", "attempt": e["attempt"], "revision": e["revision"],
                          "decision": {"kind": "setup", **{**SETUP, **chosen}}})


def room_says(s, token, t, request, **kw):
    e = s.engine.s
    return s.game_action(token, {"t": t, "attempt": e["attempt"], "revision": e["revision"], "request": request, **kw})


def room_agree(s, tokens, position=SEAT):
    assert room_says(s, tokens[0], "propose", f"seat-{s.engine.s['revision']}",
                     proposal={"kind": "tonoja_seat", "position": position}) == []
    assert room_says(s, tokens[1], "confirm", f"yes-{s.engine.s['revision']}", yes=True) == []
    assert s.engine.s["setup"]["tonoja_seat"] == position


def test_an_unconfirmed_table_waits_and_no_timer_ever_starts_it():
    """Owner decision 3: an unconfirmed table never starts itself, with or without a seat agreed."""
    for names, agreed in ((("Alice", "Bob", "Cara"), False), (("Alice", "Bob"), False), (("Alice", "Bob"), True)):
        s, tokens = party_room(names)
        if agreed:
            room_agree(s, tokens)
        revision, rng = s.engine.s["revision"], s.engine.rng.getstate()
        assert s.deadline is None and s.remaining() is None
        for _ in range(3):
            s.tick(s.gen)                                    # whatever fires, nothing is dealt
            s.game_tick()
        assert s.phase == "setup" and s.engine.s["mission"] is None and s.deadline is None
        assert s.engine.s["revision"] == revision and s.engine.rng.getstate() == rng
        assert s.engine.s["setup"]["tonoja_seat"] == (SEAT if agreed else None)       # and no seat by default


@pytest.mark.parametrize("names", (("Alice", "Bob"), ("Alice", "Bob", "Cara")))
def test_a_party_round_set_up_as_offered_is_the_table_a_party_round_opened_on_before(names):
    s, tokens = party_room(names, seed=11)
    if len(names) == 2:
        with pytest.raises(HostRefused) as refused:
            host_setup(s)
        assert (refused.value.code, str(refused.value)) == ("seat", SEAT_FIRST) and s.phase == "setup"
        room_agree(s, tokens)
    host_setup(s)
    pids = [s.players[t].pid for t in tokens]
    direct = Engine(pids, random.Random(11), 1, False, 2)   # what game_start dealt before AVR-245
    assert s.engine.s == {**direct.s, "revision": s.engine.s["revision"]}
    assert s.engine.rng.getstate() == direct.rng.getstate()
    assert s.settings == ExpoSession.DEFAULT_SETTINGS and s.phase == "allocation"
    for token, pid in zip(tokens, pids):
        view = s.game_state(token)
        assert (view.pop("lifecycle"), view.pop("begin_at"), view.pop("lifecycle_transitional")) == ("crew", None, True)
        assert view.pop("lifecycle_reasons") == s.engine.lifecycle_reasons(False)      # the adapter's, AVR-263
        assert {**view, "revision": 0} == direct.view(pid)


def test_the_host_action_never_sets_tonojas_seat_and_the_agreed_seat_becomes_the_tables_setting():
    s, tokens = party_room(("Alice", "Bob"), seed=11)
    e = s.engine.s
    for decision, code, words in (
            ({"kind": "setup", **SETUP, "tonoja_position": 0}, "seat", SEAT_NOT_SETUP),
            ({"kind": "tonoja_seat", "position": 0}, "strategic", "The crew decides that together."),
            ({"kind": "setup", **SETUP}, "seat", SEAT_FIRST)):
        with pytest.raises(HostRefused) as refused:
            s.host_action({"t": "lifecycle", "attempt": 0, "revision": e["revision"], "decision": decision})
        assert (refused.value.code, str(refused.value)) == (code, words)
    assert s.engine.s["setup"]["tonoja_seat"] is None and s.engine.s["revision"] == e["revision"]
    room_agree(s, tokens, 0)
    with pytest.raises(HostRefused) as refused:              # agreed or not, the host's payload never names it
        host_setup(s, tonoja_position=1)
    assert str(refused.value) == SEAT_NOT_SETUP and s.phase == "setup"
    host_setup(s, mission=2)
    pids = [s.players[t].pid for t in tokens]
    assert s.engine.s["seats"] == ["tonoja", *pids]
    assert s.settings == {"mission": 2, "timed": False, "tonoja_position": 0}
    assert s.engine.s == {**Engine(pids, random.Random(11), 2, False, 0).s, "revision": s.engine.s["revision"]}


def test_a_setup_that_cannot_be_saved_is_not_taken():
    s, _ = party_room()

    class Full:
        def write(self, snapshot):
            raise OSError("disk full")
    s.store = Full()
    with pytest.raises(HostRefused) as refused:
        host_setup(s, mission=5, timed=True)
    assert refused.value.code == "storage" and s.phase == "setup" and s.engine.s["mission"] is None
    assert s.settings == ExpoSession.DEFAULT_SETTINGS
    s.store = None
    host_setup(s, mission=5, timed=True)
    assert s.settings == {"mission": 5, "timed": True, "tonoja_position": 2}


def test_a_seat_agreement_that_cannot_be_saved_is_not_taken():
    s, tokens = party_room(("Alice", "Bob"))

    class Full:
        def write(self, snapshot):
            raise OSError("disk full")
    assert room_says(s, tokens[0], "propose", "a", proposal={"kind": "tonoja_seat", "position": 1}) == []
    s.store = Full()
    said = room_says(s, tokens[1], "confirm", "b", yes=True)
    assert [f["code"] for f in said] == ["storage"]
    assert s.engine.s["setup"]["tonoja_seat"] is None and s.engine.s["proposal"]["votes"] == [s.players[tokens[0]].pid]
    s.store = None
    assert room_says(s, tokens[1], "confirm", "c", yes=True) == []
    assert s.engine.s["setup"]["tonoja_seat"] == 1


def test_a_seat_that_never_arrived_holds_the_setup_until_it_does():
    s, tokens = party_room(arrive=False)
    for t in tokens[:2]:
        s.join(t)
    assert s.engine.s["away"] == [s.players[tokens[2]].pid]
    with pytest.raises(HostRefused) as refused:
        host_setup(s)
    assert refused.value.code == "paused" and s.phase == "setup"
    assert s.game_state(tokens[0])["setup"]["waiting"] == PAUSED
    s.join(tokens[2])
    host_setup(s)
    assert s.phase == "allocation"


def test_a_session_saved_in_setup_comes_back_in_setup_with_every_seat_away():
    s, tokens = party_room(("Alice", "Bob"))
    assert room_says(s, tokens[0], "propose", "seat", proposal={"kind": "tonoja_seat", "position": 1}) == []
    saved = json.loads(json.dumps(s.snapshot()))
    assert saved["version"] == 1
    back = ExpoSession(random.Random(99))
    back.restore(saved)
    assert back.phase == "setup" and back.engine.s["mission"] is None and back.deadline is None
    assert sorted(back.engine.s["away"]) == sorted(back.engine.s["humans"])
    view = back.game_state(tokens[0])["setup"]
    assert view["waiting"] == PAUSED and view["seat_waiting"] == PAUSED and view["tonoja_seat"] is None
    for t in tokens:
        back.join(t)
    # restored outside a Party the table is its crew's, as any standalone table is
    assert back.game_state(tokens[0])["lifecycle"] == "crew"
    pids = [back.players[t].pid for t in tokens]
    asked = back.game_state(tokens[1])["setup"]["seat_proposal"]            # the question came back with it
    assert asked == {"position": 1, "by": pids[0], "asked": [pids[1]]}
    assert room_says(back, tokens[1], "confirm", "yes", yes=True) == []
    assert back.engine.s["setup"]["tonoja_seat"] == 1 and back.phase == "setup"
    assert room_says(back, tokens[0], "propose", "a", proposal={"kind": "setup", **SETUP}) == []
    assert room_says(back, tokens[1], "confirm", "b", yes=True) == []
    assert back.phase == "allocation" and back.engine.s["seats"] == [pids[0], "tonoja", pids[1]]
    assert room_says(s, tokens[1], "confirm", "yes", yes=True) == []         # the table that was never restarted
    host_setup(s)
    assert back.engine.s["hands"] == s.engine.s["hands"] and back.engine.s["columns"] == s.engine.s["columns"]


def test_an_older_setup_snapshot_fails_closed_in_the_adapter(tmp_path):
    """A setup saved by this branch before the seat moved to the players (never deployed) is not
    read as anything: the session says the saved table could not be restored, and does not raise."""
    s, _ = party_room(("Alice", "Bob"))
    saved = json.loads(json.dumps(s.snapshot()))
    saved["engine"]["state"]["setup"] = dict(OLD_SETUP)
    path = tmp_path / "expo.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    back = ExpoSession(snapshot_path=path)
    assert back.engine is None and back.recovery_error
    with pytest.raises(ValueError):
        ExpoSession(random.Random(1)).restore(saved)


def test_a_standalone_table_has_no_setup_step():
    s = ExpoSession(random.Random(4))
    tokens = ["a-token-1", "b-token-2", "c-token-3"]
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.set_settings(tokens[0], {"mission": 5})
    s.start(tokens[0])
    s.tick(s.gen)
    assert s.phase == "allocation" and "setup" not in s.engine.s and s.game_state(tokens[0])["stage"] == "allocation"
    assert s.engine.s == Engine([s.players[t].pid for t in tokens], random.Random(4), 5, False, 2).s
    for proposal in ({"kind": "setup", **SETUP}, {"kind": "tonoja_seat", "position": 1}):
        said = s.game_action(tokens[0], {"t": "propose", "proposal": proposal,
                                         "attempt": 1, "revision": 0, "request": "x"})
        assert [f["code"] for f in said] == ["phase"] and s.engine.s["proposal"] is None


def test_a_standalone_table_of_two_still_seats_tonoja_from_its_lobby():
    """P22 is unchanged where there is a lobby: its players set the seat there, before Start."""
    s = ExpoSession(random.Random(4))
    tokens = ["a-token-1", "b-token-2"]
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.set_settings(tokens[0], {"tonoja_position": 0})
    s.start(tokens[0])
    s.tick(s.gen)
    pids = [s.players[t].pid for t in tokens]
    assert s.phase == "allocation" and s.engine.s == Engine(pids, random.Random(4), 1, False, 0).s


# ---- who sets a Party round up -----------------------------------------------------------------

def test_a_party_round_opens_in_setup_and_only_the_party_host_sets_it_up():
    async def scenario():
        t = await table(setup=False)
        state = t.socks[BOB][0].last_state()
        assert state["phase"] == "setup" and state["party_round"]
        game = state["game"]
        assert game["stage"] == "setup" and game["lifecycle"] == "host" and game["me"] == {"seat": t.pid(BOB)}
        assert {k: game["setup"][k] for k in SETUP} == SETUP and game["setup"]["waiting"] is None
        assert (game["setup"]["tonoja"], game["setup"]["tonoja_seat"]) == (False, None)      # three: no Tonoja
        before = t.engine.snapshot()
        # a seat, the old way; then the host message from someone the Party does not call its host
        said = await t.act(BOB, "propose", proposal={"kind": "setup", **SETUP})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["setup"])]
        assert [m["code"] for m in await t.host(BOB, "setup", host=False, **SETUP)] == ["host"]
        assert [m["code"] for m in await t.host(BOB, "setup", host=None, **SETUP)] == ["host"]
        t.party_host = BOB                                   # the role moved: a kept ticket is nothing
        assert [m["code"] for m in await t.host(ALICE, "setup", **SETUP)] == ["host"]
        t.party_host = ALICE
        # the host cannot skip the setup, nor choose what the lobby would refuse, nor name a seat
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["phase"]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **dict(SETUP, mission=3))] \
            == [("mission", content.BLOCKED[3])]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP, tonoja_position=2)] \
            == [("seat", SEAT_NOT_SETUP)]
        said = await t.act(BOB, "propose", proposal={"kind": "tonoja_seat", "position": 2})
        assert [m["code"] for m in said] == ["seat"]         # and with three there is no seat to agree
        assert t.engine.snapshot() == before
        assert await t.host(ALICE, "setup", **dict(SETUP, mission=5, timed=True)) == []
        s = t.engine.s
        assert s["phase"] == "allocation" and s["mission"]["id"] == 5 and s["timed"] is True
        assert s["proposal"] is None                         # nobody voted
        state = t.socks[CAROL][0].last_state()
        assert state["settings"] == {"mission": 5, "timed": True, "tonoja_position": 2}
        assert len(state["game"]["me"]["hand"]) in (13, 14)       # forty cards among three
        await t.close()
    run(scenario())


def test_a_watching_party_host_sets_the_table_up_and_watchers_see_setup_without_a_seat():
    async def scenario():
        t = await table(host=DANA, watchers=((DANA, "Dana"),), setup=False)
        view = t.socks[DANA][0].last_state()["game"]
        assert view["stage"] == "setup" and view["me"] is None and view["seats"] == t.engine.s["humans"]
        anon = await connect(t.b, {"t": "hello", "name": "Mallory"})
        t.socks["anon"] = anon
        assert anon[0].last_state()["game"] == {**view, "revision": t.engine.s["revision"]}
        before = t.engine.snapshot()
        await anon[0].inbox.put({"t": "propose", "proposal": {"kind": "setup", **SETUP}, "attempt": 0,
                                 "revision": t.engine.s["revision"], "request": "x"})
        await settle()
        assert t.engine.snapshot() == before                 # a watcher sets nothing up
        assert await t.host(DANA, "setup", role="spectator", **dict(SETUP, mission=2)) == []
        assert t.engine.s["mission"]["id"] == 2 and len(t.engine.s["humans"]) == 3
        assert t.socks[DANA][0].last_state()["game"]["me"] is None          # and the host took no seat
        await t.close()
    run(scenario())


def test_setup_waits_for_an_away_seat_and_survives_reloads():
    async def scenario():
        t = await table(setup=False)
        ws, task = t.socks.pop(CAROL)
        await ws.close()
        await task
        await settle()
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP)] == [("paused", PAUSED)]
        view = t.socks[BOB][0].last_state()["game"]
        assert view["stage"] == "setup" and view["away"] == [t.pid(CAROL)] and view["setup"]["waiting"] == PAUSED
        ws, task = t.socks.pop(ALICE)                        # the host reloads as well
        await ws.close()
        await task
        await settle()
        t.socks[ALICE] = await connect(t.b, {"t": "hello", "ticket": ticket(ALICE, True)})
        t.socks[CAROL] = await connect(t.b, {"t": "hello", "ticket": ticket(CAROL, False)})
        back = t.socks[CAROL][0].last_state()
        assert back["phase"] == "setup" and back["game"]["me"] == {"seat": t.pid(CAROL)}
        assert back["game"]["away"] == [] and back["game"]["setup"]["waiting"] is None
        assert t.engine.s["mission"] is None                 # nothing was dealt meanwhile
        assert await t.host(ALICE, "setup", **dict(SETUP, mission=2)) == []
        assert t.engine.s["mission"]["id"] == 2
        await t.close()
    run(scenario())


@pytest.mark.parametrize("claims", [True, False])
def test_during_setup_no_seat_ends_expo_and_the_partys_end_still_releases_the_room(claims):
    async def scenario():
        t = await table(claims=claims, setup=False)
        said = await t.act(BOB, "propose", proposal={"kind": "end"})
        assert [(m["code"], m["msg"]) for m in said] == [("host", PARTY_END)]
        assert t.engine.s["proposal"] is None and t.b.session.phase == "setup"
        ws, task = t.socks.pop(CAROL)                        # even with a seat away
        await ws.close()
        await task
        await settle()
        await t.b.party_end(proto.end_message(KEY, "expo", SID))
        assert t.b.session.engine is None and t.b.party_room_sid is None
        assert any(m.get("kind") == "party_ended" for m in t.socks[BOB][0].sent)
        await t.close()
    run(scenario())


# ---- Tonoja's seat: the two players decide it, not the Party Host (owner decision 2) -----------
# "The Party Host controls party/game flow. Game-specific decisions remain with whoever the game's
# rules assign them to." (owner, 2026-10-05)

def seat_view(t, who):
    return t.socks[who][0].last_state()["game"]["setup"]


def test_a_party_host_who_plays_decides_tonojas_seat_only_as_a_player_with_the_others_consent():
    async def scenario():
        t = await table(players=PLAYERS[:2], setup=False, seed=4)            # Alice hosts and plays
        a, b = t.pid(ALICE), t.pid(BOB)
        for who in (ALICE, BOB):
            view = seat_view(t, who)
            assert (view["tonoja"], view["tonoja_seat"], view["waiting"], view["seat_waiting"]) \
                == (True, None, SEAT_FIRST, None)
        start = t.engine.snapshot()
        # as host: the deal is refused until the players have agreed, and no payload names the seat
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP)] == [("seat", SEAT_FIRST)]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP, tonoja_position=0)] \
            == [("seat", SEAT_NOT_SETUP)]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "tonoja_seat", position=0)] \
            == [("strategic", "The crew decides that together.")]
        assert t.engine.snapshot() == start
        # as a player: a proposal, which is not a decision until Bob answers
        msg = t.cmd("propose", proposal={"kind": "tonoja_seat", "position": 0})
        assert await t.send(ALICE, msg) == []
        revision = t.engine.s["revision"]
        assert await t.send(ALICE, msg) == [] and t.engine.s["revision"] == revision       # sent twice: once
        for who in (ALICE, BOB):
            view = seat_view(t, who)
            assert view["seat_proposal"] == {"position": 0, "by": a, "asked": [b]}
            assert (view["tonoja_seat"], view["waiting"], view["seat_waiting"]) == (None, DECIDING, ANSWER_FIRST)
        assert [m["code"] for m in await t.act(ALICE, "confirm", yes=True)] == ["vote"]     # not her own
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP)] == [("vote", DECIDING)]
        assert t.engine.s["mission"] is None and t.engine.s["setup"]["tonoja_seat"] is None
        # Bob declines: no seat is agreed and nothing is dealt
        assert await t.act(BOB, "confirm", yes=False) == []
        assert t.engine.s["proposal"] is None and seat_view(t, BOB)["tonoja_seat"] is None
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP)] == [("seat", SEAT_FIRST)]
        # Bob proposes the seat that is offered; agreement on it still has to be given
        assert await t.act(BOB, "propose", proposal={"kind": "tonoja_seat", "position": SEAT}) == []
        assert [m["code"] for m in await t.host(ALICE, "setup", **SETUP)] == ["vote"]
        assert await t.act(ALICE, "confirm", yes=True) == []
        assert seat_view(t, BOB)["tonoja_seat"] == SEAT and seat_view(t, BOB)["waiting"] is None
        # they change their minds before the deal
        await agree_seat(t, BOB, ALICE, 1)
        assert seat_view(t, ALICE)["tonoja_seat"] == 1 and t.engine.s["mission"] is None
        assert t.engine.rng.getstate() == random.Random(4).getstate()
        # only now does the host's Deal work, and it deals the seat the players agreed
        assert await t.host(ALICE, "setup", **dict(SETUP, mission=2)) == []
        s = t.engine.s
        assert s["phase"] == "allocation" and s["seats"] == [a, "tonoja", b] and s["proposal"] is None
        assert s == {**Engine([a, b], random.Random(4), 2, False, 1).s, "revision": s["revision"], "dedup": s["dedup"]}
        assert t.socks[BOB][0].last_state()["settings"] == {"mission": 2, "timed": False, "tonoja_position": 1}
        said = await t.act(BOB, "propose", proposal={"kind": "tonoja_seat", "position": 2})
        assert [(m["code"], m["msg"]) for m in said] == [("phase", "Tonoja’s seat is decided before the first deal.")]
        await t.close()
    run(scenario())


def test_a_watching_party_host_has_no_say_in_tonojas_seat():
    async def scenario():
        t = await table(host=DANA, watchers=((DANA, "Dana"),), players=PLAYERS[:2], setup=False, seed=6)
        a, b = t.pid(ALICE), t.pid(BOB)
        view = t.socks[DANA][0].last_state()["game"]
        assert view["me"] is None and view["lifecycle"] == "host" and view["setup"] == seat_view(t, ALICE)
        start = t.engine.snapshot()
        # the host's own message, every way it could be tried
        assert [(m["code"], m["msg"]) for m in await t.host(DANA, "setup", role="spectator", **SETUP)] \
            == [("seat", SEAT_FIRST)]
        assert [(m["code"], m["msg"]) for m in await t.host(DANA, "setup", role="spectator", **SETUP, tonoja_position=1)] \
            == [("seat", SEAT_NOT_SETUP)]
        assert [m["code"] for m in await t.host(DANA, "tonoja_seat", role="spectator", position=1)] == ["strategic"]
        # and a seat's message from someone who holds no seat: the room does not even answer it
        await t.act(DANA, "propose", proposal={"kind": "tonoja_seat", "position": 1})
        assert t.engine.snapshot() == start
        assert await t.act(ALICE, "propose", proposal={"kind": "tonoja_seat", "position": 0}) == []
        watching = t.socks[DANA][0].last_state()["game"]                    # read-only, and all of it public
        assert watching["setup"]["seat_proposal"] == {"position": 0, "by": a, "asked": [b]}
        assert watching["setup"] == seat_view(t, BOB) and watching["me"] is None
        pending = t.engine.snapshot()
        for yes in (True, False):                            # the host can neither confirm nor decline it
            await t.act(DANA, "confirm", yes=yes)
        assert [(m["code"], m["msg"]) for m in await t.host(DANA, "setup", role="spectator", **SETUP)] \
            == [("vote", DECIDING)]
        assert t.engine.snapshot() == pending
        assert await t.act(BOB, "confirm", yes=True) == []
        assert t.socks[DANA][0].last_state()["game"]["setup"]["tonoja_seat"] == 0
        assert await t.host(DANA, "setup", role="spectator", **SETUP) == []
        s = t.engine.s
        assert s["seats"] == ["tonoja", a, b] and t.socks[DANA][0].last_state()["game"]["me"] is None
        assert s == {**Engine([a, b], random.Random(6), 1, False, 0).s, "revision": s["revision"], "dedup": s["dedup"]}
        await t.close()
    run(scenario())


def test_the_seat_agreement_waits_for_an_away_player_and_survives_a_reload():
    async def scenario():
        t = await table(players=PLAYERS[:2], setup=False)
        a, b = t.pid(ALICE), t.pid(BOB)
        ws, task = t.socks.pop(BOB)
        await ws.close()
        await task
        await settle()
        said = await t.act(ALICE, "propose", proposal={"kind": "tonoja_seat", "position": 1})
        assert [(m["code"], m["msg"]) for m in said] == [("paused", PAUSED)]
        view = seat_view(t, ALICE)
        assert (view["waiting"], view["seat_waiting"], view["tonoja_seat"]) == (PAUSED, PAUSED, None)
        t.socks[BOB] = await connect(t.b, {"t": "hello", "ticket": ticket(BOB, False)})
        assert await t.act(ALICE, "propose", proposal={"kind": "tonoja_seat", "position": 1}) == []
        ws, task = t.socks.pop(BOB)                          # the player who must answer reloads
        await ws.close()
        await task
        await settle()
        assert t.engine.s["proposal"]["votes"] == [a] and seat_view(t, ALICE)["waiting"] == PAUSED
        t.socks[BOB] = await connect(t.b, {"t": "hello", "ticket": ticket(BOB, False)})
        back = t.socks[BOB][0].last_state()["game"]
        assert back["stage"] == "setup" and back["me"] == {"seat": b} and back["away"] == []
        assert back["setup"]["seat_proposal"] == {"position": 1, "by": a, "asked": [b]}
        assert await t.act(BOB, "confirm", yes=True) == []
        assert seat_view(t, ALICE)["tonoja_seat"] == 1 and t.engine.s["mission"] is None
        ws, task = t.socks.pop(BOB)                          # agreed, and a player away: the deal waits
        await ws.close()
        await task
        await settle()
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **SETUP)] == [("paused", PAUSED)]
        t.socks[BOB] = await connect(t.b, {"t": "hello", "ticket": ticket(BOB, False)})
        assert t.socks[BOB][0].last_state()["game"]["setup"]["tonoja_seat"] == 1    # what they agreed is kept
        assert await t.host(ALICE, "setup", **SETUP) == []
        assert t.engine.s["seats"] == [a, "tonoja", b]
        await t.close()
    run(scenario())


def test_under_a_party_that_does_not_name_its_host_the_crew_agrees_on_the_setup():
    """The transitional path. The crew confirms the setup as before, and with two players the
    seat is the same kind of unanimous decision, made first: one rule for every Party round."""
    async def scenario():
        t = await table(claims=False, players=PLAYERS[:2], setup=False)
        game = t.socks[ALICE][0].last_state()["game"]
        assert game["stage"] == "setup" and game["lifecycle"] == "crew" and game["lifecycle_transitional"] is True
        assert [m["code"] for m in await t.host(ALICE, "setup", host=None, **SETUP)] == ["host"]
        # nothing is dealt for two until the seat is agreed, and the setup never carries it
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **SETUP})
        assert [(m["code"], m["msg"]) for m in said] == [("seat", SEAT_FIRST)]
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **SETUP, "tonoja_position": 1})
        assert [(m["code"], m["msg"]) for m in said] == [("seat", SEAT_NOT_SETUP)]
        await agree_seat(t, BOB, ALICE, 1)
        # two players: the volunteer mission is refused in the lobby's own words
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **dict(SETUP, mission=16)})
        assert [(m["code"], m["msg"]) for m in said] == [("mission", content.catalog(2)[15]["reason"])]
        offer = {"kind": "setup", **dict(SETUP, mission=2)}
        msg = t.cmd("propose", proposal=offer)
        assert await t.send(ALICE, msg) == []
        pending = t.socks[BOB][0].last_state()["game"]
        assert pending["stage"] == "setup" and pending["proposal"] == {"payload": offer, "votes": [t.pid(ALICE)]}
        assert pending["setup"]["waiting"] == DECIDING and t.engine.s["mission"] is None
        assert pending["setup"]["seat_proposal"] is None and pending["setup"]["seat_waiting"] == ANSWER_FIRST
        revision = t.engine.s["revision"]
        assert await t.send(ALICE, msg) == []                # the same request again: nothing happens
        assert t.engine.s["revision"] == revision
        assert [m["code"] for m in await t.act(ALICE, "confirm", yes=True)] == ["vote"]    # one vote each
        said = await t.act(BOB, "propose", proposal={"kind": "tonoja_seat", "position": 0})
        assert [(m["code"], m["msg"]) for m in said] == [("vote", ANSWER_FIRST)]            # one decision at a time
        assert await t.act(BOB, "confirm", yes=False) == []  # one decline and nothing is dealt
        assert t.engine.s["proposal"] is None and t.engine.s["phase"] == "setup"
        assert t.engine.s["setup"]["tonoja_seat"] == 1       # the seat they agreed is still agreed
        assert await t.act(BOB, "propose", proposal=offer) == []
        assert await t.act(ALICE, "confirm", yes=True) == []
        s = t.engine.s
        assert s["phase"] == "allocation" and s["mission"]["id"] == 2 and s["seats"][1] == "tonoja"
        await t.close()
    run(scenario())


def test_when_the_transition_is_over_a_party_without_the_claim_cannot_set_the_table_up(monkeypatch):
    """HOST_CLAIM_TRANSITION False: setup, like Begin, Retry and Next, is the Party Host's in
    every Party round. A Party that cannot say who that is leaves only its own end. The two
    players' seat is still theirs to agree; it deals nothing."""
    monkeypatch.setattr(expo_game, "HOST_CLAIM_TRANSITION", False)

    async def scenario():
        t = await table(claims=False, setup=False)
        assert t.socks[ALICE][0].last_state()["game"]["lifecycle"] == "host"
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **SETUP})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["setup"])]
        assert [m["code"] for m in await t.host(ALICE, "setup", host=None, **SETUP)] == ["host"]
        assert t.b.session.phase == "setup" and t.engine.s["proposal"] is None
        await t.b.party_end(proto.end_message(KEY, "expo", SID))
        assert t.b.session.engine is None
        await t.close()
        t = await table(claims=False, players=PLAYERS[:2], setup=False)
        await agree_seat(t, ALICE, BOB)
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **SETUP})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["setup"])]
        assert t.b.session.phase == "setup" and t.engine.s["mission"] is None
        await t.close()
    run(scenario())


# ---- setup and the semantic events (AVR-246) ----------------------------------------------------
# The events, the resolving hold and failure causality were written for a table that is always
# dealt. Before the first deal there is no mission, no attempt and no trick: nothing is emitted,
# nothing resolves, and every view still carries the keys the adapter and the page read.

EVENT_KEYS = {"events": [], "event_seq": 0, "resolving": None, "cause": None, "failures": {}}
NOTHING_YET = {"resolving": None, "cause": None, "events": [], "event_seq": 0}


def test_the_setup_view_carries_the_event_keys_every_view_has():
    dealt = Engine(TWO, random.Random(7)).view("p1")
    for e in (setup_engine(), setup_engine(TWO), two_engine()):
        for viewer in (*e.s["humans"], None):
            view = e.view(viewer)
            assert {k: view[k] for k in NOTHING_YET} == NOTHING_YET
            assert set(NOTHING_YET) <= set(dealt)            # the same names a dealt table sends
            assert e.events(viewer) == []
    s, tokens = party_room(("Alice", "Bob"))
    for token in (*tokens, None):                            # the adapter reads view['resolving']
        view = s.game_state(token)
        assert view["stage"] == "setup" and {k: view[k] for k in NOTHING_YET} == NOTHING_YET
        assert view["begin_at"] is None and view["expiry"] is None


def test_a_seat_that_reconnects_during_setup_is_recorded_and_emits_nothing():
    for e in (setup_engine(), setup_engine(TWO)):
        assert e.presence("p1", True) is True and e.s["away"] == ["p1"] and e.s["revision"] == 1
        assert e.presence("p1", True) is False               # already away: nothing changes
        assert e.presence("p1", False) is True and e.s["away"] == [] and e.s["revision"] == 2
        assert e.presence("p9", False) is False              # not a seat
        assert {k: e.s[k] for k in EVENT_KEYS} == EVENT_KEYS and e.s["phase"] == "setup"
        e.check()
    # a seat proposal, its answer and a seat dropping in between: still no event before the deal
    e = setup_engine(TWO)
    propose_seat(e, "p1", 1)
    e.presence("p2", True)
    e.presence("p2", False)
    answer(e, "p2")
    assert {k: e.s[k] for k in EVENT_KEYS} == EVENT_KEYS and e.s["setup"]["tonoja_seat"] == 1
    # through the adapter: the last connection closes and comes back
    s, tokens = party_room(("Alice", "Bob"))
    pid = s.players[tokens[1]].pid
    assert s.leave(tokens[1]) == [] and s.engine.s["away"] == [pid]
    assert s.game_state(tokens[0])["setup"]["waiting"] == PAUSED
    s.join(tokens[1])
    assert s.engine.s["away"] == [] and s.phase == "setup"
    assert {k: s.engine.s[k] for k in EVENT_KEYS} == EVENT_KEYS
    view = s.game_state(tokens[1])
    assert view["events"] == [] and view["me"] == {"seat": pid}


def test_the_first_events_of_a_table_set_up_are_those_of_a_table_dealt_directly():
    """The return of a seat during setup left no event behind, so the log of the first attempt
    starts at 1 and is the log a direct start writes; a return after the deal is an event."""
    e = setup_engine(TWO, seed=9)
    e.presence("p2", True)
    e.presence("p2", False)
    agree(e)
    set_up(e)
    direct = Engine(TWO, random.Random(9))
    assert e.s["events"] == direct.s["events"] and e.s["event_seq"] == direct.s["event_seq"]
    assert all(event["attempt"] == 1 and event["mission"] == 1 for event in e.s["events"])
    assert e.events("p1") == direct.events("p1")
    seq = e.s["event_seq"]
    e.presence("p2", True)
    e.presence("p2", False)
    assert e.s["event_seq"] == seq + 1 and e.s["events"][-1]["type"] == "PLAYER_RECONNECTED"


def test_nothing_settles_and_no_hold_is_kept_during_setup():
    for e in (setup_engine(), two_engine()):
        before = e.snapshot()
        assert e.settle() is False and e.settle(10 ** 9) is False
        assert e.observe_time(10 ** 9) is False and e.snapshot() == before
    s, tokens = party_room(("Alice", "Bob"))
    before = s.engine.snapshot()
    assert not s._settle_due() and s._hold is None and s.deadline is None
    for _ in range(3):
        assert s.game_tick() == []
        s.tick(s.gen)
    assert s.engine.snapshot() == before and s._hold is None and s.deadline is None
    # commands in setup pass the adapter's settle check untouched
    room_agree(s, tokens)
    assert s._hold is None and s.deadline is None and s.phase == "setup"
    host_setup(s)
    assert s.phase == "allocation" and s._hold is None and s.engine.s["resolving"] is None


def test_a_setup_snapshot_round_trips_with_the_event_keys():
    for e in (setup_engine(), setup_engine(TWO), two_engine()):
        saved = json.loads(json.dumps(e.snapshot()))
        assert {k: saved["state"][k] for k in EVENT_KEYS} == EVENT_KEYS and saved["state"]["version"] == 1
        back = Engine.restore(saved)
        assert back.s == e.s and back.view(None) == e.view(None) and back.snapshot() == e.snapshot()
        # the keys are additive: a setup saved without them is read as a table where nothing happened
        for key in EVENT_KEYS:
            del saved["state"][key]
        assert Engine.restore(saved).s == e.s
    # through the adapter, with a seat proposal pending
    s, tokens = party_room(("Alice", "Bob"))
    assert room_says(s, tokens[0], "propose", "seat", proposal={"kind": "tonoja_seat", "position": 0}) == []
    back = ExpoSession(random.Random(99))
    back.restore(json.loads(json.dumps(s.snapshot())))
    assert back.phase == "setup" and back._hold is None and back.deadline is None
    assert {k: back.engine.s[k] for k in EVENT_KEYS} == EVENT_KEYS
    for t in tokens:
        back.join(t)                                         # every seat returns: still no event
    assert {k: back.engine.s[k] for k in EVENT_KEYS} == EVENT_KEYS
    assert back.game_state(tokens[1])["setup"]["seat_proposal"]["position"] == 0


@pytest.mark.parametrize("forge", [
    lambda s: s.update(events=[{"seq": 1, "type": "TURN_STARTED", "attempt": 0, "mission": 1, "trick": 0}], event_seq=1),
    lambda s: s.update(event_seq=4),
    lambda s: s.update(event_seq=False),
    lambda s: s.update(resolving={"trick": 0}),
    lambda s: s.update(cause={"kind": "task"}),
    lambda s: s.update(failures={"x": "violated"}),
    lambda s: s.update(events=None),
], ids=range(7))
def test_a_setup_snapshot_in_which_something_happened_is_refused(forge):
    for e in (setup_engine(), two_engine()):
        saved = e.snapshot()
        forge(saved["state"])
        with pytest.raises(Invalid) as refused:
            Engine.restore(saved)
        assert refused.value.code == "snapshot"


# ---- a setup snapshot holds nothing a table that dealt nothing could not hold --------------------

SEAT_ASKED = {"payload": {"kind": "tonoja_seat", "position": 1}}


@pytest.mark.parametrize("humans,forge", [
    (3, lambda s: s.update(deck=["blue4"])),
    (3, lambda s: s.update(used=["blue4"])),
    (3, lambda s: s.update(log=[{"mission": 1, "attempts": 1, "distress": False, "attempt": 1}])),
    (3, lambda s: s.update(distress=True)),
    (3, lambda s: s.update(attempts=1)),
    (3, lambda s: s.update(attempts=False)),
    (3, lambda s: s.update(counted=True)),
    (3, lambda s: s.update(dedup=[])),
    (3, lambda s: s.update(dedup={"p1:0:a": {"t": "propose"}})),
    (3, lambda s: s["setup"].update(mission=0)),
    (3, lambda s: s["setup"].update(mission=51)),
    (3, lambda s: s["setup"].update(mission=-4)),
    (2, lambda s: s["setup"].update(tonoja_position=3)),
    (2, lambda s: s["setup"].update(tonoja_position=-1)),
    (2, lambda s: s.update(proposal={**SEAT_ASKED, "votes": ["p1", "p2"]})),      # everyone confirmed: not pending
    (2, lambda s: s.update(proposal={**SEAT_ASKED, "votes": ["p2", "p1"]})),
    (2, lambda s: s.update(proposal={**SEAT_ASKED, "votes": ["p1", "p1"]})),
    (3, lambda s: s.update(proposal={"payload": {"kind": "setup", **SETUP}, "votes": ["p1", "p2", "p3"]})),
], ids=range(18))
def test_a_crafted_setup_snapshot_is_refused(humans, forge):
    e = setup_engine(CREWS[humans - 2])
    saved = e.snapshot()
    forge(saved["state"])
    with pytest.raises(Invalid) as refused:
        Engine.restore(saved)
    assert refused.value.code == "snapshot"


def test_what_a_setup_snapshot_may_hold_still_restores():
    e = setup_engine(TWO)
    propose_seat(e, "p1", 1)                                 # one vote of two, and its request remembered
    assert len(e.s["dedup"]) == 1 and Engine.restore(json.loads(json.dumps(e.snapshot()))).s == e.s
    e = setup_engine()
    e.apply("p1", seat_msg(e, "propose", "a", proposal={"kind": "setup", **SETUP}))
    e.apply("p2", seat_msg(e, "confirm", "b", yes=True))     # two votes of three
    assert Engine.restore(json.loads(json.dumps(e.snapshot()))).s == e.s
    for mission in (1, 3, 16, 50):                           # offered is any mission the catalog lists
        Engine(TWO, random.Random(1), mission, setup=True)
