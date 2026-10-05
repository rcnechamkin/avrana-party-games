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
                "request": f"r{s['revision']}-{random.random()}", **kw}

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


SETUP = {"mission": 1, "timed": False, "tonoja_position": 2}     # what a Party round offers first


async def table(host=ALICE, claims=True, players=PLAYERS, mission=1, seed=1, watchers=(), setup=True):
    """A launched Party round. It opens in setup (AVR-245, the last section of this file); unless
    `setup` is False the table is taken through it here, on `mission`, by whoever moves this
    table on: the Party Host, or the crew under a Party that does not name its host."""
    b = GameBinding("expo", ExpoSession(rng=random.Random(seed)), party=proto.GameSide(KEY, "expo"))
    entries = [(p, n, "player") for p, n in players] + [(p, n, "spectator") for p, n in watchers]
    await b.party_launch(proto.launch_message(KEY, "expo", SID, roster(*entries)))
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
    if not setup:
        return early
    chosen = dict(SETUP, mission=mission)
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
    return early


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


# ---- setup before the first deal (AVR-245, owner decision 2026-10-05) ---------------------------
# A Party round skips EXPO's lobby, so the mission, the timed setting and Tonoja's seat are chosen
# inside EXPO before anything is dealt. The Party launch contract is untouched. Setup is one more
# routine step of the table's life, committed the way the next mission is after a success: by the
# Party Host, or by the whole crew where the crew moves the table on.

import json

from games.expo import content
from games.expo.engine import DECIDING, PAUSED
from games.expo.rules import DECK

CREWS = (["p1", "p2"], ["p1", "p2", "p3"], ["p1", "p2", "p3", "p4"], ["p1", "p2", "p3", "p4", "p5"])


def setup_engine(humans=("p1", "p2", "p3"), seed=7):
    return Engine(list(humans), random.Random(seed), setup=True)


def set_up(e, **chosen):
    return e.lifecycle(lifecycle(e, "setup", **{**SETUP, **chosen}))


@pytest.mark.parametrize("humans", CREWS, ids=lambda h: f"{len(h)}-humans")
def test_setting_up_what_is_offered_deals_exactly_the_table_a_direct_start_deals(humans):
    """The proof that nothing else changed: confirming mission 1, untimed, Tonoja after both
    players gives the deal, the tasks, the captain, the random state and every view of a table
    started without a setup step, for the same seed. The one difference is the count of accepted
    changes, because confirming the setup is one."""
    for seed in range(25):
        direct = Engine(list(humans), random.Random(seed))
        waited = setup_engine(humans, seed)
        assert waited.s["phase"] == "setup"
        assert waited.rng.getstate() == random.Random(seed).getstate()      # nothing was drawn
        assert set_up(waited) is True
        a, b = dict(direct.s), dict(waited.s)
        assert (a.pop("revision"), b.pop("revision")) == (0, 1)
        assert a == b and direct.rng.getstate() == waited.rng.getstate()
        for viewer in list(humans) + [None]:
            va, vb = direct.view(viewer), waited.view(viewer)
            assert (va.pop("revision"), vb.pop("revision")) == (0, 1)
            assert va == vb


def test_setup_chooses_the_mission_the_clock_and_tonojas_seat():
    for position in (0, 1, 2):
        e = setup_engine(["p1", "p2"])
        assert e.s["seats"] == ["p1", "p2"]                 # Tonoja has no seat until one is chosen
        set_up(e, mission=5, tonoja_position=position)
        assert e.s["seats"].index("tonoja") == position and e.s["mission"]["id"] == 5
        assert e.s == {**Engine(["p1", "p2"], random.Random(7), 5, False, position).s, "revision": 1}
    e = setup_engine()
    set_up(e, mission=16, timed=True, tonoja_position=0)    # the seat is unused with three or more
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
    offered = {m["id"] for m in setup_engine(crew).view()["setup"]["missions"] if m["enabled"]}
    accepted = set()
    for mission in range(0, 52):
        for timed in (False, True):
            lobby = lobby_answer(humans, mission, timed)
            e = setup_engine(crew)
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
    ({"mission": 1, "timed": False}, "payload"),                      # a field missing
    ({**SETUP, "extra": 1}, "payload"),
    ({**SETUP, "mission": True}, "payload"),                          # a boolean is not a mission
    ({**SETUP, "mission": "1"}, "payload"),
    ({**SETUP, "timed": 1}, "payload"),
    ({**SETUP, "tonoja_position": 1.0}, "payload"),
    ({**SETUP, "tonoja_position": 3}, "seat"),
    ({**SETUP, "tonoja_position": -1}, "seat"),
    ({**SETUP, "mission": 3}, "mission"),                             # blocked content stays blocked
    ({**SETUP, "mission": 51}, "mission"),
])
def test_a_refused_setup_changes_nothing_and_deals_nothing(decision, code):
    for e in (setup_engine(), setup_engine(["p1", "p2"])):
        before = e.snapshot()
        with pytest.raises(Invalid) as refused:
            e.lifecycle({"t": "lifecycle", "decision": {"kind": "setup", **decision}, "attempt": 0, "revision": 0})
        assert refused.value.code == code and e.snapshot() == before and e.s["phase"] == "setup"


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
    direct = Engine(["p1", "p2", "p3"], random.Random(7))
    with pytest.raises(Invalid) as none:
        direct.apply("p1", {"t": "propose", "proposal": {"kind": "setup", **SETUP},
                            "attempt": 1, "revision": 0, "request": "x"})
    assert none.value.code == "phase" and direct.s["proposal"] is None


def test_no_card_task_or_table_command_works_before_the_deal():
    e = setup_engine()
    before = e.snapshot()
    proposals = ({"kind": "begin"}, {"kind": "end"}, {"kind": "retry", "keep": True}, {"kind": "next", "mission": 2},
                 {"kind": "distress", "direction": "left"}, {"kind": "assign", "owner": "p1", "task": "all"})
    for msg in ({"t": "play_card", "card": "blue:1"}, {"t": "choose_task", "task": "x"}, {"t": "pass_task"},
                {"t": "volunteer", "yes": True}, {"t": "predict", "task": "x", "count": 0},
                {"t": "pass_card", "card": "blue:1"}, {"t": "communicate", "card": "blue:1", "assertion": "only"},
                {"t": "confirm", "yes": True}, *({"t": "propose", "proposal": p} for p in proposals)):
        with pytest.raises(Invalid) as refused:
            e.apply("p1", {**msg, "attempt": 0, "revision": 0, "request": "x"})
        assert refused.value.code not in ("snapshot", "payload"), msg      # refused by a rule, cleanly
        assert e.snapshot() == before, msg


def test_the_setup_view_is_public_and_holds_nothing_of_a_deal():
    e = setup_engine(["p1", "p2"])
    public = e.view(None)
    assert set(public) == {"kind", "attempt", "revision", "stage", "mission", "seats", "away", "proposal",
                           "result", "expiry", "log", "setup", "me"}
    assert public["stage"] == "setup" and public["me"] is None and public["mission"] is None
    assert public["setup"] == {**SETUP, "tonoja": True, "waiting": None, "missions": content.catalog(2)}
    for seat in ("p1", "p2"):
        assert e.view(seat) == {**public, "me": {"seat": seat}}             # a seat learns only its seat
    said = json.dumps([e.view(v) for v in ("p1", "p2", None)]) + json.dumps(e.s)
    assert not any(card in said for card in DECK)           # no card exists yet, so none can leak
    assert not {"hands", "columns", "captain", "pool", "deck_order"} & set(e.s) and e.s["deck"] == []
    assert setup_engine().view(None)["setup"]["tonoja"] is False            # no seat to choose for three


def test_a_table_saved_in_setup_restores_and_then_deals_the_same_table():
    e = setup_engine(["p1", "p2"], seed=5)
    offer = {"kind": "setup", **dict(SETUP, mission=5, tonoja_position=0)}
    e.apply("p1", {"t": "propose", "proposal": offer, "attempt": 0, "revision": 0, "request": "a"})
    saved = json.loads(json.dumps(e.snapshot()))
    assert saved["state"]["version"] == 1                    # the format did not change
    back = Engine.restore(saved)
    assert back.s == e.s and back.view("p2") == e.view("p2") and back.view("p2")["proposal"]["payload"] == offer
    for table_ in (e, back):
        assert table_.apply("p2", {"t": "confirm", "yes": True, "attempt": 0, "revision": 1, "request": "b"})
    assert back.s == e.s and back.rng.getstate() == e.rng.getstate()
    assert "setup" not in e.s and e.s["mission"]["id"] == 5 and e.s["seats"][0] == "tonoja"
    # a dealt table is saved with the keys it always had: nothing of the setup stays behind
    dealt = Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert set(dealt.s) == set(Engine(["p1", "p2"], random.Random(1)).s)


@pytest.mark.parametrize("forge", [
    lambda s: s.update(phase="allocation"),                  # no deal behind it
    lambda s: s.update(attempt=1),
    lambda s: s.pop("setup"),
    lambda s: s.update(setup={"mission": 1}),
    lambda s: s.update(setup={**SETUP, "mission": "1"}),
    lambda s: s.update(seats=["p1", "tonoja", "p2", "p3"]),
    lambda s: s.update(expiry=5.0),
    lambda s: s.update(result={"status": "success", "reason": "forged"}),
    lambda s: s.update(proposal={"payload": {"kind": "begin"}, "votes": ["p1"]}),
], ids=range(9))
def test_a_forged_setup_snapshot_is_refused(forge):
    saved = setup_engine().snapshot()
    forge(saved["state"])
    with pytest.raises(Invalid):
        Engine.restore(saved)
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


def test_an_unconfirmed_table_waits_and_no_timer_ever_starts_it():
    s, _ = party_room()
    revision = s.engine.s["revision"]
    assert s.deadline is None and s.remaining() is None
    for _ in range(3):
        s.tick(s.gen)                                        # whatever fires, nothing is dealt
        s.game_tick()
    assert s.phase == "setup" and s.engine.s["mission"] is None and s.deadline is None
    assert s.engine.s["revision"] == revision


@pytest.mark.parametrize("names", (("Alice", "Bob"), ("Alice", "Bob", "Cara")))
def test_a_party_round_set_up_as_offered_is_the_table_a_party_round_opened_on_before(names):
    s, tokens = party_room(names, seed=11)
    host_setup(s)
    pids = [s.players[t].pid for t in tokens]
    direct = Engine(pids, random.Random(11), 1, False, 2)   # what game_start dealt before AVR-245
    assert s.engine.s == {**direct.s, "revision": s.engine.s["revision"]}
    assert s.settings == ExpoSession.DEFAULT_SETTINGS and s.phase == "allocation"
    for token, pid in zip(tokens, pids):
        view = s.game_state(token)
        assert (view.pop("lifecycle"), view.pop("begin_at"), view.pop("lifecycle_transitional")) == ("crew", None, True)
        assert {**view, "revision": 0} == direct.view(pid)


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
    saved = json.loads(json.dumps(s.snapshot()))
    assert saved["version"] == 1
    back = ExpoSession(random.Random(99))
    back.restore(saved)
    assert back.phase == "setup" and back.engine.s["mission"] is None and back.deadline is None
    assert sorted(back.engine.s["away"]) == sorted(back.engine.s["humans"])
    assert back.game_state(tokens[0])["setup"]["waiting"] == PAUSED
    for t in tokens:
        back.join(t)
    # restored outside a Party the table is its crew's, as any standalone table is
    assert back.game_state(tokens[0])["lifecycle"] == "crew"
    pids = [back.players[t].pid for t in tokens]
    scope = lambda: {"attempt": 0, "revision": back.engine.s["revision"]}
    assert back.game_action(tokens[0], {"t": "propose", "request": "a", **scope(),
                                        "proposal": {"kind": "setup", **dict(SETUP, tonoja_position=1)}}) == []
    assert back.game_action(tokens[1], {"t": "confirm", "yes": True, "request": "b", **scope()}) == []
    assert back.phase == "allocation" and back.engine.s["seats"] == [pids[0], "tonoja", pids[1]]
    host_setup(s, tonoja_position=1)                         # the table that was never restarted
    assert back.engine.s["hands"] == s.engine.s["hands"] and back.engine.s["columns"] == s.engine.s["columns"]


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
    said = s.game_action(tokens[0], {"t": "propose", "proposal": {"kind": "setup", **SETUP},
                                     "attempt": 1, "revision": 0, "request": "x"})
    assert [f["code"] for f in said] == ["phase"] and s.engine.s["proposal"] is None


# ---- who sets a Party round up -----------------------------------------------------------------

def test_a_party_round_opens_in_setup_and_only_the_party_host_sets_it_up():
    async def scenario():
        t = await table(setup=False)
        state = t.socks[BOB][0].last_state()
        assert state["phase"] == "setup" and state["party_round"]
        game = state["game"]
        assert game["stage"] == "setup" and game["lifecycle"] == "host" and game["me"] == {"seat": t.pid(BOB)}
        assert {k: game["setup"][k] for k in SETUP} == SETUP and game["setup"]["waiting"] is None
        before = t.engine.snapshot()
        # a seat, the old way; then the host message from someone the Party does not call its host
        said = await t.act(BOB, "propose", proposal={"kind": "setup", **SETUP})
        assert [(m["code"], m["msg"]) for m in said] == [("host", HOST_ONLY["setup"])]
        assert [m["code"] for m in await t.host(BOB, "setup", host=False, **SETUP)] == ["host"]
        assert [m["code"] for m in await t.host(BOB, "setup", host=None, **SETUP)] == ["host"]
        t.party_host = BOB                                   # the role moved: a kept ticket is nothing
        assert [m["code"] for m in await t.host(ALICE, "setup", **SETUP)] == ["host"]
        t.party_host = ALICE
        # the host cannot skip the setup, nor choose what the lobby would refuse
        assert [m["code"] for m in await t.host(ALICE, "begin")] == ["phase"]
        assert [(m["code"], m["msg"]) for m in await t.host(ALICE, "setup", **dict(SETUP, mission=3))] \
            == [("mission", content.BLOCKED[3])]
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


def test_under_a_party_that_does_not_name_its_host_the_crew_agrees_on_the_setup():
    async def scenario():
        t = await table(claims=False, players=PLAYERS[:2], setup=False)
        game = t.socks[ALICE][0].last_state()["game"]
        assert game["stage"] == "setup" and game["lifecycle"] == "crew" and game["lifecycle_transitional"] is True
        assert [m["code"] for m in await t.host(ALICE, "setup", host=None, **SETUP)] == ["host"]
        # two players: the volunteer mission is refused in the lobby's own words
        said = await t.act(ALICE, "propose", proposal={"kind": "setup", **dict(SETUP, mission=16)})
        assert [(m["code"], m["msg"]) for m in said] == [("mission", content.catalog(2)[15]["reason"])]
        offer = {"kind": "setup", **dict(SETUP, mission=2, tonoja_position=1)}
        msg = t.cmd("propose", proposal=offer)
        assert await t.send(ALICE, msg) == []
        pending = t.socks[BOB][0].last_state()["game"]
        assert pending["stage"] == "setup" and pending["proposal"] == {"payload": offer, "votes": [t.pid(ALICE)]}
        assert pending["setup"]["waiting"] == DECIDING and t.engine.s["mission"] is None
        revision = t.engine.s["revision"]
        assert await t.send(ALICE, msg) == []                # the same request again: nothing happens
        assert t.engine.s["revision"] == revision
        assert [m["code"] for m in await t.act(ALICE, "confirm", yes=True)] == ["vote"]    # one vote each
        assert await t.act(BOB, "confirm", yes=False) == []  # one decline and nothing is dealt
        assert t.engine.s["proposal"] is None and t.engine.s["phase"] == "setup"
        assert await t.act(BOB, "propose", proposal=offer) == []
        assert await t.act(ALICE, "confirm", yes=True) == []
        s = t.engine.s
        assert s["phase"] == "allocation" and s["mission"]["id"] == 2 and s["seats"][1] == "tonoja"
        await t.close()
    run(scenario())


def test_when_the_transition_is_over_a_party_without_the_claim_cannot_set_the_table_up(monkeypatch):
    """HOST_CLAIM_TRANSITION False: setup, like Begin, Retry and Next, is the Party Host's in
    every Party round. A Party that cannot say who that is leaves only its own end."""
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
    run(scenario())
