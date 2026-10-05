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


async def table(host=ALICE, claims=True, players=PLAYERS, mission=1, seed=1, watchers=()):
    """A launched Party round, dealt from `seed`: the same seed is the same deal, tasks and
    captain every time, so a test meets the table it was written for."""
    b = GameBinding("expo", ExpoSession(rng=random.Random(seed)), party=proto.GameSide(KEY, "expo"))
    entries = [(p, n, "player") for p, n in players] + [(p, n, "spectator") for p, n in watchers]
    await b.party_launch(proto.launch_message(KEY, "expo", SID, roster(*entries)))
    # A launch replaces the room with a new session of its own (GameBinding._fresh_room), which
    # draws from an unseeded generator: the one given above is gone with the session it was
    # given to. The deal is drawn from the session's generator when the round starts, so that
    # is where the seed goes.
    b.session.rng = random.Random(seed)
    b.session.settings["mission"] = mission
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
    # The seed took: this is the table that seed deals, card for card and task for task.
    dealt, same = b.session.engine.s, Engine([early.pid(p) for p, _ in players], random.Random(seed), mission).s
    for key in ("seats", "hands", "columns", "captain", "selected", "pool", "deck", "mission"):
        assert dealt[key] == same[key], f"seed {seed} did not decide the deal ({key})"
    assert b.session.engine.rng.getstate() == Engine(
        [early.pid(p) for p, _ in players], random.Random(seed), mission).rng.getstate()
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
            answer, loop = t.b.ask_host, asyncio.get_running_loop()

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
            assert t.b.session.engine is None and t.asked == 1            # nothing began anywhere
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
