"""Wall-clock jumps (AVR-221): a step of the system clock, forward or backward, must not change
how long anything inside one running game process takes.

The appliance has no battery-backed clock, so `systemd-timesyncd` may step the wall clock by
minutes while a party is running. Durations measured inside this process (away grace, autopilot,
the empty-table pause, the takeover delay, the armed deadline) therefore run on the monotonic
clock. Only what is told to a browser stays wall-clock: `now`, `deadline`, `takeover_at`.

The fake clock here has two hands. `adv` is time really passing (both move); `jump` is a clock
step (only the wall clock moves).
"""

from __future__ import annotations

import asyncio
import random
import time

import pytest

from core.net import GameBinding
from core.session import COUNTDOWN_SECONDS
from games.bluff.game import (AWAY_GRACE, AWAY_TURN_GRACE, AUTOPILOT_DELAY, EMPTY_TABLE_ABANDON,
                              PAUSE_TAKEOVER, RESUME_MIN, BluffSession)

A, B, S = "tokenA_alice", "tokenB_bob", "tokenS_stranger"
JUMPS = (600.0, -600.0, 3000.0, -3000.0)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0          # wall clock
        self.m = 5_000.0              # monotonic clock

    def adv(self, s):
        self.t += s
        self.m += s

    def jump(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(time, "time", lambda: c.t)
    monkeypatch.setattr(time, "monotonic", lambda: c.m)
    return c


def game(n=2, bots=0):
    s = BluffSession(rng=random.Random(3))
    for t, name in list(zip((A, B), ("Alice", "Bob")))[:n]:
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def turn(s, tok):
    s.g["turn"] = s.g["seats"].index(tok)
    s.g["pending"] = {"stage": "turn", "actor": tok}


def presence(s, tok):
    return next(x["presence"] for x in s.state_for(None)["game"]["seats"]
                if x["pid"] == s.players[tok].pid)


# ---------------------------------------------------------------- away grace and autopilot

@pytest.mark.parametrize("jump", JUMPS)
def test_away_turn_grace_is_unchanged_by_a_clock_jump(clock, jump):
    s = game()
    turn(s, A)
    s.leave(A)                                   # B is still here: no pause
    clock.adv(10)
    clock.jump(jump)
    delay, tok = s.next_bot_action()
    assert tok == A and delay == pytest.approx(AWAY_TURN_GRACE - 10)
    assert presence(s, A) == "reconnecting"      # 10 s away, whatever the wall clock says
    clock.adv(AWAY_GRACE)
    assert presence(s, A) == "away"


@pytest.mark.parametrize("jump", JUMPS)
def test_a_scheduled_autopilot_moment_survives_a_clock_jump(clock, jump):
    """The moment is memoised per step (so message spam cannot push it back); the memo must not
    be a wall-clock reading either."""
    s = game()
    turn(s, A)
    s.leave(A)
    assert s.next_bot_action()[0] == pytest.approx(AWAY_TURN_GRACE)      # memoised here
    clock.adv(20)
    clock.jump(jump)
    assert s.next_bot_action()[0] == pytest.approx(AWAY_TURN_GRACE - 20)
    clock.adv(AWAY_TURN_GRACE - 20)
    assert s.next_bot_action() == (0.0, A)


@pytest.mark.parametrize("jump", JUMPS)
def test_autopilot_is_prompt_once_the_grace_has_really_passed(clock, jump):
    s = game()
    turn(s, A)
    s.leave(A)
    clock.adv(AWAY_TURN_GRACE + 5)
    clock.jump(jump)
    assert s.next_bot_action() == (AUTOPILOT_DELAY, A)


# ---------------------------------------------------------------- all-away takeover

@pytest.mark.parametrize("jump", JUMPS)
def test_takeover_opens_after_the_real_delay_whatever_the_clock_does(clock, jump):
    s = game()
    s.leave(A); s.leave(B)
    assert s.g["paused"]
    s.join(S, "Stranger")
    clock.adv(PAUSE_TAKEOVER - 5)
    clock.jump(jump)
    out = s.game_action(S, {"t": "end_game"})
    assert out[0]["kind"] == "invalid" and "6 s" in out[0]["msg"] and s.phase == "playing"
    assert not s._takeover_open()
    # the browser is told a wall-clock moment, on the clock as it reads now
    assert s.state_for(S)["game"]["takeover_at"] == int((clock.t + 5) * 1000)
    clock.adv(5)
    assert s._takeover_open()
    s.game_action(S, {"t": "end_game"})
    assert s.phase == "lobby"


# ---------------------------------------------------------------- pause / resume

@pytest.mark.parametrize("jump", JUMPS)
def test_a_jump_before_the_pause_does_not_change_the_remaining_time(clock, jump):
    s = game()
    turn(s, A)
    s._bump(clock.t + 90)
    clock.adv(15)
    clock.jump(jump)                             # the clock steps, then everyone drops
    s.leave(A); s.leave(B)
    assert s.g["paused"]["remaining"] == pytest.approx(75)
    assert s.remaining() == pytest.approx(EMPTY_TABLE_ABANDON)
    clock.adv(120)
    s.join(B, "Bob")
    assert not s.g["paused"] and s.remaining() == pytest.approx(75)
    assert s.deadline == pytest.approx(clock.t + 75)


@pytest.mark.parametrize("jump", JUMPS)
def test_a_jump_during_the_pause_does_not_change_the_remaining_time(clock, jump):
    s = game()
    turn(s, A)
    s._bump(clock.t + 90)
    s.leave(A); s.leave(B)
    clock.adv(30)
    clock.jump(jump)
    assert s.remaining() == pytest.approx(EMPTY_TABLE_ABANDON - 30)     # abandon timer untouched
    s.join(A, "Alice")
    assert s.remaining() == pytest.approx(90) and s.deadline == pytest.approx(clock.t + 90)


def test_a_nearly_spent_stage_still_resumes_with_the_minimum(clock):
    s = game()
    turn(s, A)
    s._bump(clock.t + 3)
    clock.jump(-3000)
    s.leave(A); s.leave(B)
    s.join(A, "Alice")
    assert s.remaining() == pytest.approx(RESUME_MIN)


# ---------------------------------------------------------------- the armed deadline (core)

@pytest.mark.parametrize("jump", JUMPS)
def test_the_deadline_shown_to_browsers_follows_the_clock_they_are_given(clock, jump):
    """`now` and `deadline` go out together; their difference is the time really left."""
    s = game()
    s._bump(clock.t + 40)
    clock.adv(10)
    before = s.state_for(A)
    assert before["deadline"] - before["now"] == 30_000
    clock.jump(jump)
    after = s.state_for(A)
    assert after["deadline"] - after["now"] == 30_000
    assert s.remaining() == pytest.approx(30)


def test_without_a_jump_the_armed_wall_deadline_is_reported_unchanged(clock):
    s = game()
    s._bump(clock.t + 40)
    armed = s.state_for(A)["deadline"]
    clock.adv(12.3456)
    assert s.state_for(A)["deadline"] == armed == int(s.deadline * 1000)


def _countdown_binding():
    b = GameBinding("bluff", BluffSession(rng=random.Random(1)))
    for t, name in ((A, "Alice"), (B, "Bob")):
        b.session.join(t, name)
        b.session.set_ready(t, True)
    b.session.start(A)
    assert b.session.phase == "countdown"
    return b


async def _push(b):
    async with b.lock:
        await b.push_all([])


def _cancel(b):
    for task in (b._timer_task, b._bot_task):
        if task:
            task.cancel()


def test_a_forward_jump_then_a_push_does_not_fire_the_armed_timer_early(monkeypatch):
    """core.net re-arms the timer on every push; that must not re-read the wall clock."""
    async def scenario():
        b = _countdown_binding()
        await _push(b)                               # timer armed for COUNTDOWN_SECONDS
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 600)
        await _push(b)                               # any message causes a push
        await asyncio.sleep(0.3)
        phase = b.session.phase
        _cancel(b)
        return phase

    assert COUNTDOWN_SECONDS > 1
    assert asyncio.run(scenario()) == "countdown"


def test_a_backward_jump_then_a_push_does_not_delay_the_armed_timer(monkeypatch):
    async def scenario():
        b = _countdown_binding()
        b.session._bump(time.time() + 0.3)
        await _push(b)
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() - 600)
        await _push(b)
        await asyncio.sleep(0.8)
        phase = b.session.phase
        _cancel(b)
        return phase

    assert asyncio.run(scenario()) == "playing"
