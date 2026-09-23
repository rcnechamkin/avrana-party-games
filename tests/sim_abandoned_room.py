"""How long does an ABANDONED BLUFF game (every human gone for good) block the
room? Fake-clock simulation with the real game constants; no server needed.

    .venv/bin/python tests/sim_abandoned_room.py
"""

from __future__ import annotations

import random
import statistics
import sys
import time as _time

sys.path.insert(0, ".")
import core.session as cs  # noqa: E402
import games.bluff.game as bg  # noqa: E402


class Clock:
    t = 1_000_000.0

    def time(self):
        return self.t


CLOCK = Clock()
cs.time = CLOCK
bg.time = CLOCK


def blocked_seconds(humans, bots, seed):
    s = bg.BluffSession(rng=random.Random(seed))
    toks = ["human%02d_tok" % i for i in range(humans)]
    for t in toks:
        s.join(t, t[:7])
        s.set_ready(t, True)
    s.set_settings(toks[0], {"bots": bots})
    s.start(toks[0])
    CLOCK.t = s.deadline
    s.tick(s.gen)
    for t in toks:                       # everyone leaves at t0
        s.leave(t)
    t0 = CLOCK.t
    while s.phase != "lobby":
        due = s.next_bot_action()
        if due is not None and (s.deadline is None or CLOCK.t + due[0] < s.deadline):
            CLOCK.t += due[0]
            s.run_bot(due[1])
            continue
        CLOCK.t = s.deadline
        s.tick(s.gen)
        if CLOCK.t - t0 > 6 * 3600:
            return float("inf")
    return CLOCK.t - t0


print("humans bots  median_min  max_min   (all humans gone at t=0; includes 20 s results)")
for humans, bots in [(1, 1), (2, 0), (2, 2), (3, 0), (4, 0), (6, 0), (3, 3)]:
    xs = [blocked_seconds(humans, bots, seed) / 60 for seed in range(40)]
    print("%6d %4d %11.1f %8.1f" % (humans, bots, statistics.median(xs), max(xs)))
