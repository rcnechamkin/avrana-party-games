"""Protocol-level full-game simulator for BLUFF (not a pytest; name avoids collection).

Plays complete games with N real WebSocket clients (+ optional server bots) against a
RUNNING isolated server, one serialized step at a time, and checks after EVERY push:

  * payload shape / hidden-info masking (seats carry no cards, `me` is the viewer's,
    exchange pool only for the exchange actor, spectators get me=None)
  * cross-client consistency: every client's k-th push has the same public table
  * card conservation (hands + revealed + deck + exchange draw == 15, <=3 per role)
  * coins >= 0, dead => 0 coins / not actor / not waiting, one `turn` flag
  * me.actions and me.prompt match the rules for the current stage
  * a RULES ORACLE: every transition (our message, a bot move or a deadline) is
    replayed on an independent model of the baseline rules and the predicted public
    table / owners' hands must match what the server pushed
  * --adversarial: illegal but well-formed messages must yield an `invalid` fx to
    the sender only and leave the table (and deadline) unchanged
  * --lazy: the last client never answers prompts and idles its first turn, so
    deadlines drive the game; timeout transitions are checked for timing too

    python tests/sim_bluff.py --url ws://127.0.0.1:8200 --players 4 --bots 1 \
        --games 5 --seed 42 [--adversarial] [--lazy] [--spectator]

Server randomness is NOT controlled by --seed (it only seeds client policies). For
bit-exact replays start a fresh server with a seeded RNG through this same file:

    LANGAMES_PORT=8200 python tests/sim_bluff.py --serve --server-seed 7
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import copy
import json
import os
import random
import secrets
import sys
import time

ROLES = ["Banker", "Agent", "Smuggler", "Broker", "Guardian"]
CLAIM = {"tax": "Banker", "strike": "Agent", "steal": "Smuggler", "exchange": "Broker"}
BLOCK = {"aid": ("anyone", ["Banker"]), "strike": ("target", ["Guardian"]),
         "steal": ("target", ["Smuggler", "Broker"])}
COST = {"coup": 7, "strike": 3}
TARGETED = {"coup", "strike", "steal"}
STAGE_SECS = {"turn": 90, "challenge": 20, "block": 20, "block_challenge": 20,
              "lose": 30, "exchange": 45}
SEAT_KEYS = {"pid", "name", "bot", "coins", "influence", "revealed", "alive", "turn"}
GAME_KEYS = {"kind", "roles", "seats", "deck_count", "pending", "log", "winner", "me"}
PENDING_KEYS = {"stage", "actor", "action", "label", "target", "claim_role", "blocker",
                "block_role", "loser", "waiting"}
ME_KEYS = {"pid", "cards", "actions", "prompt"}


# =============================================================== rules oracle

class Model:
    """Independent model of the baseline rules, built from an observed push."""

    def __init__(self, g, hands, then):
        self.seats = [s["pid"] for s in g["seats"]]
        self.bot = {s["pid"]: s["bot"] for s in g["seats"]}
        self.coins = {s["pid"]: s["coins"] for s in g["seats"]}
        self.rev = {s["pid"]: list(s["revealed"]) for s in g["seats"]}
        self.hand = {s["pid"]: list(hands.get(s["pid"]) or ["?"] * s["influence"])
                     for s in g["seats"]}
        self.deck = g["deck_count"]
        p = g["pending"]
        self.p = {k: p.get(k) for k in PENDING_KEYS if k != "label"}
        self.p["waiting"] = list(p.get("waiting") or [])
        self.turner = p.get("actor")
        self.then = then
        self.draw = 0
        self.winner = None
        self.over = False
        self.ev = []                                 # coverage events

    def alive(self, x):
        return len(self.hand[x]) > 0

    def alive_seats(self):
        return [x for x in self.seats if self.alive(x)]

    def stage(self, st, **kw):
        self.p.update(kw)
        self.p["stage"] = st

    # ---- turn actions
    def act(self, actor, a, tgt):
        self.coins[actor] -= COST.get(a, 0)
        self.p = {"stage": None, "actor": actor, "action": a, "target": tgt,
                  "claim_role": CLAIM.get(a), "blocker": None, "block_role": None,
                  "loser": None, "waiting": []}
        self.ev.append("act:" + a)
        if a == "income":
            self.coins[actor] += 1
            return self.end_turn()
        if a == "coup":
            return self.lose(tgt, "end_turn")
        if a == "aid":
            return self.open_block()
        self.stage("challenge", waiting=[x for x in self.alive_seats() if x != actor])

    def open_block(self):
        a = self.p["action"]
        who, roles = BLOCK[a]
        if who == "target":
            el = [self.p["target"]] if self.alive(self.p["target"]) else []
        else:
            el = [x for x in self.alive_seats() if x != self.p["actor"]]
        if not el:
            return self.resolve()
        self.stage("block", waiting=el)

    def claim_ok(self):
        if self.p["action"] in BLOCK:
            return self.open_block()
        return self.resolve()

    def resolve(self):
        a, actor, tgt = self.p["action"], self.p["actor"], self.p["target"]
        self.ev.append("resolve:" + a)
        if a == "aid":
            self.coins[actor] += 2
        elif a == "tax":
            self.coins[actor] += 3
        elif a == "steal":
            amt = min(2, self.coins[tgt]) if self.alive(tgt) else 0
            self.ev.append("steal_amt:%d" % amt)
            self.coins[tgt] -= amt
            self.coins[actor] += amt
        elif a == "strike":
            if self.alive(tgt):
                return self.lose(tgt, "end_turn")
            self.ev.append("strike_target_already_dead")
        elif a == "exchange":
            self.draw = min(2, self.deck)
            self.deck -= self.draw
            self.stage("exchange", waiting=[actor])
            return
        return self.end_turn()

    def fails(self):
        self.ev.append("fails:" + str(self.p["action"]))
        return self.end_turn()

    # ---- responses
    def respond(self, who, choice, role=None):
        st = self.p["stage"]
        if st in ("challenge", "block_challenge"):
            if choice == "pass":
                self.p["waiting"] = [x for x in self.p["waiting"] if x != who]
                if not self.p["waiting"]:
                    if st == "challenge":
                        return self.claim_ok()
                    self.ev.append("block_stands")
                    return self.fails()
                return
            if st == "challenge":
                return self.challenge(who, self.p["actor"], self.p["claim_role"],
                                      "claim_ok", "fails", "claim")
            return self.challenge(who, self.p["blocker"], self.p["block_role"],
                                  "fails", "resolve", "block")
        if st == "block":
            if choice == "allow":
                self.p["waiting"] = [x for x in self.p["waiting"] if x != who]
                if not self.p["waiting"]:
                    return self.resolve()
                return
            self.ev.append("block:%s:%s" % (self.p["action"], role))
            self.stage("block_challenge", blocker=who, block_role=role,
                       waiting=[x for x in self.alive_seats() if x != who])

    def challenge(self, chal, claimant, role, ok_then, fail_then, what):
        h = self.hand[claimant]
        if role in h:
            h.remove(role)
            h.append("?")                             # replacement drawn (hidden)
            self.ev.append("challenge_%s:true_claim" % what)
            return self.lose(chal, ok_then)
        self.ev.append("challenge_%s:bluff_caught" % what)
        return self.lose(claimant, fail_then)

    # ---- influence
    def lose(self, x, then):
        n = len(self.hand[x])
        if n == 0:
            self.ev.append("lose_but_already_dead")
            return self.cont(then)
        if n == 1:
            return self.reveal(x, 0, then, auto=True)
        self.then = then
        self.stage("lose", loser=x, waiting=[x])

    def reveal(self, x, idx, then, auto=False, card=None):
        c = self.hand[x].pop(idx)
        self.rev[x].append(card or c)
        self.ev.append("reveal_auto" if auto else "reveal_choice")
        if not self.hand[x]:
            self.coins[x] = 0
            self.ev.append("elim")
            if x == self.turner and not self.over:
                self.ev.append("actor_eliminated_on_own_turn")
        if self.check_winner():
            return
        return self.cont(then)

    def cont(self, then):
        return {"end_turn": self.end_turn, "claim_ok": self.claim_ok,
                "fails": self.fails, "resolve": self.resolve}[then]()

    def keep(self, who, pool, keep):
        self.hand[who] = [pool[i] for i in keep]
        self.deck += len(pool) - len(keep)
        self.draw = 0
        self.ev.append("exchange_done")
        return self.end_turn()

    def check_winner(self):
        al = self.alive_seats()
        if len(al) <= 1:
            self.winner = al[0] if al else None
            self.over = True
            return True
        return False

    def end_turn(self):
        if self.check_winner():
            return
        n = len(self.seats)
        i = self.seats.index(self.turner)
        for _ in range(n):
            i = (i + 1) % n
            if self.alive(self.seats[i]):
                break
        self.turner = self.seats[i]
        self.p = {"stage": "turn", "actor": self.turner, "action": None, "target": None,
                  "claim_role": None, "blocker": None, "block_role": None, "loser": None,
                  "waiting": []}

    # ---- deadline
    def timeout(self, pool=None, coup_target=None):
        st = self.p["stage"]
        self.ev.append("timeout:" + st)
        if st == "turn":
            x = self.turner
            if self.coins[x] >= 7:
                self.ev.append("timeout_turn_coup_at_%d" % self.coins[x])
                return self.act(x, "coup", coup_target)
            return self.act(x, "income", None)
        if st == "challenge":
            self.p["waiting"] = []
            return self.claim_ok()
        if st == "block_challenge":
            self.p["waiting"] = []
            return self.fails()
        if st == "block":
            self.p["waiting"] = []
            return self.resolve()
        if st == "lose":
            return self.reveal(self.p["loser"], 0, self.then)
        if st == "exchange":
            x = self.p["actor"]
            return self.keep(x, pool, list(range(len(self.hand[x]))))

    # ---- projection
    def proj(self):
        p = self.p
        st = "over" if self.over else p["stage"]
        return {"phase": "game_end" if self.over else "playing",
                "winner": self.winner, "deck": self.deck,
                "seats": [(x, self.coins[x], len(self.hand[x]), tuple(self.rev[x]),
                           self.alive(x)) for x in self.seats],
                "pending": pend_proj(st, p)}


def pend_proj(st, p):
    out = {"stage": st}
    if st == "turn":
        out["actor"] = p.get("actor")
    elif st in ("challenge", "block", "block_challenge", "exchange"):
        out.update(actor=p.get("actor"), action=p.get("action"), target=p.get("target"),
                   waiting=sorted(p.get("waiting") or []))
        if st == "challenge":
            out["claim_role"] = p.get("claim_role")
        if st == "block_challenge":
            out.update(blocker=p.get("blocker"), block_role=p.get("block_role"))
    elif st == "lose":
        out.update(loser=p.get("loser"), waiting=sorted(p.get("waiting") or []))
    return out


def obs_proj(st):
    g = st["game"]
    p = g["pending"]
    return {"phase": st["phase"], "winner": g["winner"], "deck": g["deck_count"],
            "seats": [(s["pid"], s["coins"], s["influence"], tuple(s["revealed"]),
                       s["alive"]) for s in g["seats"]],
            "pending": pend_proj(p["stage"], p)}


def public(st):
    g = st.get("game") or {}
    return json.dumps([st["phase"], g.get("seats"), g.get("pending"), g.get("winner"),
                       g.get("deck_count"), g.get("log"), st.get("deadline")],
                      sort_keys=True)


def wild_eq(a, b):
    """Structural equality where '?' in the model (a) matches any string."""
    if a == "?" and isinstance(b, str):
        return True
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(wild_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(wild_eq(a[k], b[k]) for k in a)
    return a == b


def hand_eq(model_hand, cards):
    if len(model_hand) != len(cards):
        return False
    rest = list(cards)
    for c in model_hand:
        if c != "?":
            if c not in rest:
                return False
            rest.remove(c)
    return True


def diff(a, b):
    out = []
    for k in a:
        if not wild_eq(a[k], b.get(k)):
            out.append("%s: expected %s, got %s" % (k, a[k], b.get(k)))
    return "; ".join(out)


# =============================================================== clients

class Client:
    def __init__(self, sim, name, lazy=False, spectator=False):
        self.sim, self.name, self.lazy, self.spectator = sim, name, lazy, spectator
        self.token = "sim" + secrets.token_hex(10)
        self.pid = None
        self.states = []                 # every state frame, in order
        self.fx = []                     # (push index it precedes, fx)
        self.last_send = 0.0

    async def open(self, url):
        import websockets
        self.ws = await websockets.connect(url, max_size=2 ** 22)
        await self.ws.send(json.dumps({"t": "hello", "token": self.token, "name": self.name}))
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m.get("type") == "welcome":
                    self.pid = m.get("pid")
                elif m.get("type") == "state":
                    self.states.append(m)
                    self.sim.check_shape(self, m)
                elif m.get("type") == "fx":
                    self.fx.append((len(self.states), m))
                self.sim.bell.set()
        except Exception as e:           # noqa: BLE001
            self.sim.violate("socket", "%s reader died: %r" % (self.name, e))
            self.sim.bell.set()

    async def send(self, **msg):
        gap = time.time() - self.last_send
        if gap < 0.08:                   # stay well under 30 msgs / 2 s
            await asyncio.sleep(0.08 - gap)
        self.last_send = time.time()
        await self.ws.send(json.dumps(msg))


# =============================================================== simulator

class Sim:
    def __init__(self, a):
        self.a = a
        self.rng = random.Random(a.seed)
        self.bell = asyncio.Event()
        self.violations = []
        self.vkinds = collections.Counter()
        self.cov = collections.Counter()
        self.recent = collections.deque(maxlen=14)
        self.game_no = 0

    # ---------------------------------------------------------------- reporting
    def violate(self, kind, detail, frame=None):
        self.vkinds[kind] += 1
        if self.vkinds[kind] <= self.a.max_reports:
            v = {"game": self.game_no, "kind": kind, "detail": detail,
                 "recent": list(self.recent)}
            if frame is not None:
                g = frame.get("game") or {}
                v["frame"] = {"phase": frame.get("phase"), "pending": g.get("pending"),
                              "seats": [(s["pid"], s["coins"], s["influence"],
                                         s["revealed"]) for s in g.get("seats", [])],
                              "log_tail": (g.get("log") or [])[-4:]}
            self.violations.append(v)
            print("  !! VIOLATION [%s] g%d: %s" % (kind, self.game_no, detail), flush=True)

    # ---------------------------------------------------------------- per-frame
    def check_shape(self, c, m):
        g = m.get("game")
        if not g or m.get("phase") not in ("playing", "game_end"):
            return
        try:
            assert set(g) <= GAME_KEYS, "extra game keys %s" % (set(g) - GAME_KEYS)
            assert set(g["pending"]) <= PENDING_KEYS, "extra pending keys"
            for s in g["seats"]:
                assert set(s) == SEAT_KEYS, "seat keys %s" % (set(s) ^ SEAT_KEYS)
                assert s["coins"] >= 0, "negative coins %s" % s["pid"]
                assert s["influence"] + len(s["revealed"]) == 2, "influence+revealed!=2"
                assert s["alive"] == (s["influence"] > 0), "alive flag"
                assert s["alive"] or s["coins"] == 0, "dead seat holds coins"
            me = g["me"]
            if c.spectator or c.pid not in [s["pid"] for s in g["seats"]]:
                assert me is None, "spectator received a me block"
            else:
                assert me is not None and set(me) == ME_KEYS, "me block shape"
                assert me["pid"] == c.pid, "me.pid %s != own %s" % (me["pid"], c.pid)
                seat = next(s for s in g["seats"] if s["pid"] == c.pid)
                assert len(me["cards"]) == seat["influence"], "cards != influence"
                pr = me["prompt"]
                if pr and pr.get("kind") == "exchange":
                    assert g["pending"]["actor"] == c.pid, "exchange pool to non-actor"
            txt = json.dumps({k: v for k, v in g.items() if k != "me"})
            assert "deck\"" not in txt.replace("deck_count\"", ""), "deck list leaked"
        except AssertionError as e:
            self.violate("shape/masking", "%s: %s" % (c.name, e), m)

    def check_push(self, k):
        """Cross-client + table invariants for aligned push k."""
        frames = [(c, c.states[c.base + k]) for c in self.clients]
        f0 = frames[0][1]
        if f0["phase"] not in ("playing", "game_end"):
            return f0
        pub0 = public(f0)
        for c, f in frames[1:]:
            if public(f) != pub0:
                self.violate("cross-client", "%s disagrees with %s at push %d"
                             % (c.name, frames[0][0].name, k), f)
            if abs(f["now"] - f0["now"]) > 2000:
                self.violate("cross-client", "push %d now skew %dms" % (k, f["now"] - f0["now"]))
        g = f0["game"]
        p = g["pending"]
        seats = {s["pid"]: s for s in g["seats"]}
        st = p["stage"]
        if f0["phase"] == "playing":
            alive = [s["pid"] for s in g["seats"] if s["alive"]]
            if p["actor"] not in alive:
                self.violate("pending", "actor %s not alive" % p["actor"], f0)
            for w in p["waiting"]:
                if w not in alive:
                    self.violate("pending", "dead %s in waiting" % w, f0)
            if len(set(p["waiting"])) != len(p["waiting"]):
                self.violate("pending", "duplicate waiting", f0)
            if st == "challenge" and p["actor"] in p["waiting"]:
                self.violate("pending", "claimant may challenge self", f0)
            if st == "block_challenge" and p["blocker"] in p["waiting"]:
                self.violate("pending", "blocker may challenge own block", f0)
            if st in ("lose", "exchange") and len(p["waiting"]) != 1:
                self.violate("pending", "%s waiting %s" % (st, p["waiting"]), f0)
            if st == "turn" and p["waiting"]:
                self.violate("pending", "turn stage has waiting", f0)
            turns = [s["pid"] for s in g["seats"] if s["turn"]]
            if turns != [p["actor"]]:
                self.violate("turn-flag", "turn flags %s actor %s" % (turns, p["actor"]), f0)
            if not f0.get("deadline"):
                self.violate("deadline", "playing without deadline", f0)
        # conservation, from the owners' private views
        total = sum(s["influence"] + len(s["revealed"]) for s in g["seats"]) + g["deck_count"]
        known = collections.Counter()
        for s in g["seats"]:
            known.update(s["revealed"])
        draw = 0
        for c, f in frames:
            me = f["game"]["me"]
            if c.spectator or me is None:
                continue
            known.update(me["cards"])
            pr = me["prompt"]
            want_prompt = f["phase"] == "playing" and c.pid in p["waiting"]
            if bool(pr) != want_prompt:
                self.violate("prompt", "%s prompt=%s but waiting=%s" % (c.name, pr, p["waiting"]), f)
            if pr:
                kind = {"challenge": "challenge", "block_challenge": "challenge",
                        "block": "block", "lose": "lose", "exchange": "exchange"}.get(st)
                if pr["kind"] != kind:
                    self.violate("prompt", "%s kind %s in stage %s" % (c.name, pr["kind"], st), f)
                if pr["kind"] == "block" and pr["roles"] != BLOCK[p["action"]][1]:
                    self.violate("prompt", "block roles %s for %s" % (pr["roles"], p["action"]), f)
                if pr["kind"] == "exchange":
                    draw = len(pr["pool"]) - len(me["cards"])
                    if pr["pool"][:len(me["cards"])] != me["cards"] or pr["keep"] != len(me["cards"]):
                        self.violate("exchange", "pool/keep inconsistent %s" % pr, f)
                    known.update(pr["pool"][len(me["cards"]):])
            exp = expected_actions(g, c.pid) if f["phase"] == "playing" else {}
            got = {x["action"]: sorted(x["targets"]) if x["targets"] is not None else None
                   for x in me["actions"]}
            if got != exp:
                self.violate("actions", "%s actions %s expected %s" % (c.name, got, exp), f)
            for x in me["actions"]:
                if x["claims"] != CLAIM.get(x["action"]):
                    self.violate("actions", "claims field %s" % x, f)
        if st == "exchange" and draw == 0 and any(
                c.pid == p["actor"] for c in self.clients if not c.spectator):
            self.violate("exchange", "exchange stage without a draw", f0)
        if st == "exchange" and not any(c.pid == p["actor"] for c in self.clients):
            draw = 2  # bot exchange (bots never claim; defensive)
        if total + draw != 15:
            self.violate("conservation", "cards total %d (+%d drawn) != 15" % (total, draw), f0)
        over = [r for r, n in known.items() if n > 3 or r not in ROLES]
        if over:
            self.violate("conservation", "role counts %s" % dict(known), f0)
        if not self.bots and sum(known.values()) != 15 - g["deck_count"]:
            self.violate("conservation", "known %d != 15-deck %d" % (sum(known.values()), g["deck_count"]), f0)
        return f0

    # ---------------------------------------------------------------- plumbing
    async def wait(self, pred, timeout):
        end = time.time() + timeout
        while not pred():
            left = end - time.time()
            if left <= 0:
                return False
            self.bell.clear()
            try:
                await asyncio.wait_for(self.bell.wait(), min(left, 1.0))
            except asyncio.TimeoutError:
                pass
        return True

    def have(self, k):
        return all(len(c.states) > c.base + k for c in self.clients)

    def hands(self, k):
        out = {}
        for c in self.clients:
            if not c.spectator:
                out[c.pid] = c.states[c.base + k]["game"]["me"]["cards"]
        return out

    def me(self, c, k):
        return c.states[c.base + k]["game"]["me"]

    # ---------------------------------------------------------------- lobby
    async def start_game(self):
        c0 = self.clients[0]
        ok = await self.wait(lambda: all(c.states and c.states[-1]["phase"] == "lobby"
                                         for c in self.clients), self.a.lobby_wait)
        if not ok:
            self.violate("lobby", "clients not back in the lobby: %s"
                         % [c.states[-1]["phase"] if c.states else None for c in self.clients])
            return False
        lobby = c0.states[-1]
        gone = [p for p in lobby["players"] if not p.get("connected", True)]
        if gone:
            self.violate("lobby", "disconnected players not pruned: %s" % gone)
        await c0.send(t="settings", patch={"bots": self.a.bots})
        for c in self.clients:
            if not c.spectator:
                await c.send(t="ready", ready=True)
        await asyncio.sleep(0.3)
        await c0.send(t="start")
        ok = await self.wait(lambda: all(any(s["phase"] == "playing" for s in c.states[c.mark:])
                                         for c in self.clients), 15)
        if not ok:
            self.violate("lobby", "game did not start")
            return False
        for c in self.clients:
            c.base = next(i for i in range(c.mark, len(c.states))
                          if c.states[i]["phase"] == "playing")
        return True

    # ---------------------------------------------------------------- policy
    def policy_turn(self, c, me, g):
        r = self.rng
        acts = {x["action"]: x for x in me["actions"]}
        prof = self.prof[c.pid]
        if c.lazy and "exchange" in acts and r.random() < 0.5:
            return "exchange", None          # lazy seats then sit on the exchange prompt
        if "coup" in acts and (len(acts) == 1 or r.random() < 0.6):
            return "coup", r.choice(acts["coup"]["targets"])
        opts = []
        for a, x in acts.items():
            if a == "coup":
                continue
            role = x["claims"]
            w = 1.0
            if role:
                w = 3.0 if role in me["cards"] else 2.0 * prof["bluff"]
            opts.append((a, w))
        tot = sum(w for _, w in opts)
        pick = r.random() * tot
        for a, w in opts:
            pick -= w
            if pick <= 0:
                break
        tgt = r.choice(acts[a]["targets"]) if acts[a]["targets"] else None
        return a, tgt

    def policy_prompt(self, c, me, g):
        r = self.rng
        pr, p = me["prompt"], g["pending"]
        prof = self.prof[c.pid]
        if pr["kind"] == "challenge":
            role = p["claim_role"] if p["stage"] == "challenge" else p["block_role"]
            pc = prof["chal"] * (2.0 if me["cards"].count(role) >= 1 else 1.0)
            return {"t": "respond", "choice": "challenge" if r.random() < pc else "pass"}
        if pr["kind"] == "block":
            held = [x for x in pr["roles"] if x in me["cards"]]
            if held and r.random() < 0.8:
                return {"t": "respond", "choice": "block", "role": r.choice(held)}
            if r.random() < prof["bluff"] * 0.6:
                return {"t": "respond", "choice": "block", "role": r.choice(pr["roles"])}
            return {"t": "respond", "choice": "allow"}
        if pr["kind"] == "lose":
            return {"t": "lose", "card": r.randrange(len(me["cards"]))}
        if pr["kind"] == "exchange":
            return {"t": "keep", "cards": r.sample(range(len(pr["pool"])), pr["keep"])}

    def illegal(self, k, f0):
        """A well-formed message that the rules forbid right now."""
        r = self.rng
        g = f0["game"]
        p = g["pending"]
        c = r.choice(self.clients)
        if c.spectator:
            return c, {"t": "act", "action": "income"}, "spectator act"
        me = self.me(c, k)
        seats = {s["pid"]: s for s in g["seats"]}
        dead = [x for x, s in seats.items() if not s["alive"]]
        st = p["stage"]
        cands = [({"t": "dance"}, "unknown verb"),
                 ({"t": "act", "action": "fly"}, "unknown action")]
        if not me["actions"]:
            cands.append(({"t": "act", "action": "income"}, "act out of turn/stage"))
        else:
            coins = seats[c.pid]["coins"]
            if coins < 3:
                other = [x for x in seats if x != c.pid and seats[x]["alive"]][0]
                cands.append(({"t": "act", "action": "strike", "target": other}, "strike unaffordable"))
            if coins < 7:
                cands.append(({"t": "act", "action": "coup", "target": "p1"}, "coup unaffordable"))
            if coins >= 10:
                cands.append(({"t": "act", "action": "tax"}, "non-coup at 10+"))
            cands += [({"t": "act", "action": "steal", "target": c.pid}, "target self"),
                      ({"t": "act", "action": "steal", "target": "p999"}, "unknown target"),
                      ({"t": "act", "action": "steal", "target": 3}, "non-string target"),
                      ({"t": "act", "action": "steal"}, "missing target")]
            if dead:
                cands.append(({"t": "act", "action": "steal", "target": dead[0]}, "dead target"))
        if c.pid not in p["waiting"]:
            cands += [({"t": "respond", "choice": "pass"}, "respond not waiting"),
                      ({"t": "respond", "choice": "challenge"}, "challenge not waiting"),
                      ({"t": "lose", "card": 0}, "lose not loser"),
                      ({"t": "keep", "cards": [0]}, "keep not exchanger")]
        else:
            n = len(me["cards"])
            if st in ("challenge", "block_challenge"):
                cands += [({"t": "respond", "choice": "allow"}, "allow in challenge"),
                          ({"t": "respond", "choice": "block", "role": "Guardian"}, "block in challenge"),
                          ({"t": "respond", "choice": 1}, "bad choice"),
                          ({"t": "lose", "card": 0}, "lose in challenge")]
            elif st == "block":
                bad = [x for x in ROLES if x not in BLOCK[p["action"]][1]]
                cands += [({"t": "respond", "choice": "block", "role": r.choice(bad)}, "wrong block role"),
                          ({"t": "respond", "choice": "block"}, "block without role"),
                          ({"t": "respond", "choice": "pass"}, "pass in block"),
                          ({"t": "respond", "choice": "challenge"}, "challenge in block")]
            elif st == "lose":
                cands += [({"t": "lose", "card": n}, "lose idx out of range"),
                          ({"t": "lose", "card": -1}, "lose idx -1"),
                          ({"t": "lose", "card": "0"}, "lose idx string"),
                          ({"t": "lose", "card": True}, "lose idx bool"),
                          ({"t": "respond", "choice": "pass"}, "pass in lose")]
            elif st == "exchange":
                pool = len(me["prompt"]["pool"])
                cands += [({"t": "keep", "cards": list(range(n + 1))}, "keep too many"),
                          ({"t": "keep", "cards": [0] * n}, "keep duplicates"),
                          ({"t": "keep", "cards": [pool] + list(range(n - 1))}, "keep out of range"),
                          ({"t": "keep", "cards": [True] + list(range(1, n))}, "keep bools"),
                          ({"t": "keep", "cards": {"0": 0}}, "keep dict"),
                          ({"t": "lose", "card": 0}, "lose in exchange")]
        msg, why = r.choice(cands)
        return c, msg, why

    # ---------------------------------------------------------------- one game
    async def play_game(self):
        self.game_no += 1
        for c in self.clients:
            c.mark = len(c.states)
        if not await self.start_game():
            return None
        n_players = len(self.a_players)
        stats = collections.Counter()
        then = None
        k = 0
        lazy_idled = set()
        t0 = time.time()
        winner = None
        while True:
            if not await self.wait(lambda: self.have(k), 5):
                self.violate("sync", "push %d missing on some client: %s" % (
                    k, [len(c.states) - c.base for c in self.clients]))
                return None
            f0 = self.check_push(k)
            g = f0["game"]
            if f0["phase"] == "game_end":
                winner = g["winner"]
                alive = [s["pid"] for s in g["seats"] if s["alive"]]
                if winner is None or alive != [winner]:
                    self.violate("end", "winner %s alive %s" % (winner, alive), f0)
                if g["pending"]["stage"] != "over":
                    self.violate("end", "pending stage %s at game_end" % g["pending"]["stage"], f0)
                if any(self.me(c, k)["actions"] or self.me(c, k)["prompt"]
                       for c in self.clients if not c.spectator):
                    self.violate("end", "actions/prompt offered after game end", f0)
                break
            if f0["phase"] != "playing":
                self.violate("phase", "unexpected phase %s" % f0["phase"], f0)
                return None
            if k > self.a.max_pushes or time.time() - t0 > self.a.max_seconds:
                self.violate("liveness", "game not over after %d pushes / %ds" % (k, time.time() - t0), f0)
                return None
            p = g["pending"]
            st = p["stage"]
            seats = {s["pid"]: s for s in g["seats"]}
            bypid = {c.pid: c for c in self.clients if not c.spectator}
            # --- adversarial probe (never while a bot or deadline is about to act)
            bot_due = (st == "turn" and seats[p["actor"]]["bot"]) or \
                any(seats[w]["bot"] for w in p["waiting"])
            if self.a.adversarial and not bot_due and self.rng.random() < self.a.adv_rate \
                    and f0["deadline"] - f0["now"] > 3000:
                c, msg, why = self.illegal(k, f0)
                self.recent.append("g%d k%d %s ILLEGAL %s (%s)" % (self.game_no, k, c.name, msg, why))
                await c.send(**msg)
                if not await self.wait(lambda: self.have(k + 1), 5):
                    self.violate("sync", "no push after illegal %s" % msg)
                    return None
                k += 1
                f1 = c.states[c.base + k]
                self.check_push(k)
                inv = [fx for i, fx in c.fx if i == c.base + k and fx.get("kind") == "invalid"]
                stats["illegal_sent"] += 1
                self.cov["illegal:" + why] += 1
                if not inv:
                    self.violate("adversarial", "no invalid fx for %s (%s)" % (msg, why), f1)
                for o in self.clients:
                    if o is not c and any(i == o.base + k and fx.get("kind") == "invalid"
                                          for i, fx in o.fx):
                        self.violate("adversarial", "invalid fx leaked to %s" % o.name)
                if public(f1) != public(f0) or self.hands(k) != self.hands(k - 1):
                    self.violate("adversarial", "illegal %s (%s) changed the table" % (msg, why), f1)
                continue
            # --- choose the next event
            send = None
            if bot_due:
                kind = "bot"
            else:
                movers = []
                if st == "turn":
                    c = bypid.get(p["actor"])
                    if c and not (c.lazy and p["actor"] not in lazy_idled):
                        movers = [c]
                    elif c:
                        lazy_idled.add(p["actor"])
                else:
                    movers = [bypid[w] for w in p["waiting"] if w in bypid and not bypid[w].lazy]
                if movers:
                    c = self.rng.choice(movers)
                    me = self.me(c, k)
                    if st == "turn":
                        a, tgt = self.policy_turn(c, me, g)
                        send = (c, {"t": "act", "action": a, "target": tgt})
                    else:
                        send = (c, self.policy_prompt(c, me, g))
                    kind = "send"
                else:
                    kind = "timeout"
            # --- build the model from push k
            hands = self.hands(k)
            base = Model(g, hands, then)
            pool = None
            ex = [c for c in self.clients if not c.spectator and self.me(c, k)["prompt"]
                  and self.me(c, k)["prompt"]["kind"] == "exchange"]
            if ex:
                pool = self.me(ex[0], k)["prompt"]["pool"]
                base.draw = len(pool) - len(ex[0].states[ex[0].base + k]["game"]["me"]["cards"])
            cands = []
            if kind == "send":
                c, msg = send
                self.recent.append("g%d k%d %s %s" % (self.game_no, k, c.name, msg))
                t = msg["t"]
                if t == "act":
                    cands.append(("act", lambda m: m.act(c.pid, msg["action"], msg.get("target"))))
                elif t == "respond":
                    cands.append(("respond", lambda m: m.respond(c.pid, msg["choice"], msg.get("role"))))
                elif t == "lose":
                    card = hands[c.pid][msg["card"]]
                    cands.append(("lose", lambda m: m.reveal(c.pid, msg["card"], m.then)))
                elif t == "keep":
                    cands.append(("keep", lambda m: m.keep(c.pid, pool, msg["cards"])))
                await c.send(**msg)
                stats["sent"] += 1
                wait_s = 8
            elif kind == "bot":
                self.recent.append("g%d k%d (bot due, stage %s)" % (self.game_no, k, st))
                if st == "turn":
                    actor = p["actor"]
                    if seats[actor]["coins"] >= 7:
                        for tg in [x for x in seats if x != actor and seats[x]["alive"]]:
                            cands.append(("bot coup " + tg, lambda m, tg=tg: m.act(actor, "coup", tg)))
                    else:
                        cands.append(("bot income", lambda m: m.act(actor, "income", None)))
                else:
                    w = next(x for x in p["waiting"] if seats[x]["bot"])
                    if st in ("challenge", "block_challenge"):
                        cands.append(("bot pass", lambda m: m.respond(w, "pass")))
                    elif st == "block":
                        cands.append(("bot allow", lambda m: m.respond(w, "allow")))
                    elif st == "lose":
                        cands.append(("bot lose0", lambda m: m.reveal(w, 0, m.then)))
                wait_s = 6
            else:
                self.recent.append("g%d k%d (awaiting %s deadline)" % (self.game_no, k, st))
                if st == "turn" and seats[p["actor"]]["coins"] >= 7:
                    for tg in [x for x in seats if x != p["actor"] and seats[x]["alive"]]:
                        cands.append(("timeout coup " + tg, lambda m, tg=tg: m.timeout(pool, tg)))
                else:
                    cands.append(("timeout", lambda m: m.timeout(pool)))
                wait_s = (f0["deadline"] - f0["now"]) / 1000 + 8
                stats["timeouts"] += 1
            if not await self.wait(lambda: self.have(k + 1), wait_s):
                self.violate("liveness", "no push within %.0fs after %s (stage %s)" % (wait_s, kind, st), f0)
                return None
            k += 1
            f1 = self.check_push(k)
            if kind == "send":
                inv = [fx for i, fx in send[0].fx if i == send[0].base + k and fx.get("kind") == "invalid"]
                if inv:
                    self.violate("legal-rejected", "legal %s got invalid %s" % (send[1], inv[0].get("msg")), f1)
            if kind == "timeout":
                late = f1["now"] - f0["deadline"]
                if late < -150:
                    self.violate("timer", "stage %s advanced %dms BEFORE its deadline" % (st, -late), f1)
                elif late > 5000:
                    self.violate("timer", "stage %s deadline overshot by %dms" % (st, late), f1)
            # --- oracle
            got = obs_proj(f1)
            hands1 = self.hands(k)
            best, bestdiff = None, None
            for label, fn in cands:
                m = copy.deepcopy(base)
                try:
                    fn(m)
                except Exception as e:      # noqa: BLE001
                    bestdiff = bestdiff or "model error %r" % e
                    continue
                pr = m.proj()
                # model reveals of hidden bot cards are wildcards
                d = diff(pr, got)
                hd = [x for x in hands1 if not hand_eq(m.hand[x], hands1[x])]
                if not d and not hd:
                    best = (label, m)
                    break
                if bestdiff is None:
                    bestdiff = d + ("; hands differ for %s: model %s got %s" % (
                        hd, [m.hand[x] for x in hd], [hands1[x] for x in hd]) if hd else "")
            if best is None:
                self.violate("oracle", "after %s: %s" % (self.recent[-1], bestdiff), f1)
                then = None
            else:
                m = best[1]
                then = m.then
                for e in m.ev:
                    self.cov[e] += 1
                    stats[e if e.startswith(("act:", "challenge_", "timeout:")) else e.split(":")[0]] += 1
                # a new stage must carry a fresh deadline of the right length
                st1 = f1["game"]["pending"]["stage"]
                if f1["phase"] == "playing" and (st1 != st or m.ev and any(
                        e.startswith(("act", "block:")) for e in m.ev)):
                    secs = (f1["deadline"] - f1["now"]) / 1000
                    if abs(secs - STAGE_SECS[st1]) > 2:
                        self.violate("timer", "stage %s deadline %.1fs (expected %d)"
                                     % (st1, secs, STAGE_SECS[st1]), f1)
            if kind == "send" and send[1]["t"] == "act" and CLAIM.get(send[1]["action"]):
                held = CLAIM[send[1]["action"]] in hands[send[0].pid]
                stats["claim_honest" if held else "claim_bluff"] += 1
            if kind == "send" and send[1].get("choice") == "block":
                held = send[1]["role"] in hands[send[0].pid]
                stats["block_honest" if held else "block_bluff"] += 1
        stats["pushes"] = k
        name = next((s["name"] for s in g["seats"] if s["pid"] == winner), "?")
        dur = time.time() - t0
        print("game %d: %d players+%d bots, %d pushes, %.0fs | turns=%d claims=%d (bluff %d) "
              "chal claim true/bluff=%d/%d blocks=%d (bluff %d) blockchal true/bluff=%d/%d "
              "exch=%d coups=%d elim=%d timeouts=%d illegal=%d | winner %s (%s)" % (
                  self.game_no, n_players, self.bots, k, dur,
                  sum(v for e, v in stats.items() if e.startswith("act:")),
                  stats["claim_honest"] + stats["claim_bluff"], stats["claim_bluff"],
                  stats["challenge_claim:true_claim"],
                  stats["challenge_claim:bluff_caught"],
                  stats["block_honest"] + stats["block_bluff"], stats["block_bluff"],
                  stats["challenge_block:true_claim"], stats["challenge_block:bluff_caught"],
                  stats["exchange_done"], stats["act:coup"], stats["elim"], stats["timeouts"],
                  stats["illegal_sent"], winner, name), flush=True)
        # game_end -> lobby after ~20 s; players must not be pruned (all connected)
        return winner

    # ---------------------------------------------------------------- main
    async def run(self):
        a = self.a
        url = a.url.rstrip("/") + "/games/bluff/ws"
        self.bots = a.bots
        self.a_players = list(range(a.players))
        self.clients = [Client(self, "P%d" % (i + 1), lazy=a.lazy and i == a.players - 1)
                        for i in range(a.players)]
        if a.spectator:
            self.clients.append(Client(self, "Spec", spectator=True))
        for c in self.clients:
            await c.open(url)
            await self.wait(lambda: c.pid and c.states, 10)
            c.mark = 0
        self.prof = {}
        for c in self.clients:
            self.prof[c.pid] = {"bluff": self.rng.choice([0.1, 0.4, 0.8]),
                                "chal": self.rng.choice([0.1, 0.25, 0.45])}
        if self.clients[0].states[-1]["phase"] != "lobby":
            print("waiting for the server to return to the lobby...", flush=True)
        results = []
        for _ in range(a.games):
            try:
                w = await self.play_game()
            except Exception as e:          # noqa: BLE001  harness bug: report, stop cleanly
                import traceback
                traceback.print_exc()
                self.violate("harness", "simulator error %r" % e)
                w = None
            results.append(w)
            if w is None:
                break
        for c in self.clients:
            c.reader.cancel()
            await c.ws.close()
        print("\n== %d game(s), %d finished; violations: %d %s" % (
            len(results), sum(1 for w in results if w), sum(self.vkinds.values()),
            dict(self.vkinds)))
        print("coverage:", json.dumps(dict(sorted(self.cov.items())), separators=(",", ":")))
        for v in self.violations:
            print("VIOLATION", json.dumps(v, separators=(",", ":")))
        return 1 if self.vkinds else 0


def expected_actions(g, pid):
    p = g["pending"]
    seats = {s["pid"]: s for s in g["seats"]}
    if p["stage"] != "turn" or p["actor"] != pid or not seats[pid]["alive"]:
        return {}
    coins = seats[pid]["coins"]
    others = sorted(x for x, s in seats.items() if s["alive"] and x != pid)
    out = {}
    for a in ("income", "aid", "coup", "tax", "strike", "steal", "exchange"):
        if coins >= 10 and a != "coup":
            continue
        if coins < COST.get(a, 0):
            continue
        out[a] = others if a in TARGETED else None
    return out


def serve(seed):
    """Run server.py (repo root = parent of tests/) with seeded default RNGs."""
    import runpy
    base = random.Random

    class Seeded(base):
        def __init__(self, x=None):
            super().__init__(seed if x is None else x)

    random.Random = Seeded
    random.seed(seed)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    sys.path.insert(0, root)
    sys.argv = ["server.py"]
    runpy.run_path(os.path.join(root, "server.py"), run_name="__main__")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8200")
    ap.add_argument("--players", type=int, default=4)
    ap.add_argument("--bots", type=int, default=0)
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--adversarial", action="store_true")
    ap.add_argument("--adv-rate", type=float, default=0.15)
    ap.add_argument("--lazy", action="store_true")
    ap.add_argument("--spectator", action="store_true")
    ap.add_argument("--max-pushes", type=int, default=4000)
    ap.add_argument("--max-seconds", type=int, default=1800)
    ap.add_argument("--max-reports", type=int, default=3)
    ap.add_argument("--lobby-wait", type=int, default=45, help="max s to wait for the lobby")
    ap.add_argument("--serve", action="store_true", help="run a seeded server instead")
    ap.add_argument("--server-seed", type=int, default=1)
    a = ap.parse_args()
    if a.serve:
        return serve(a.server_seed)
    sys.exit(asyncio.run(Sim(a).run()))


if __name__ == "__main__":
    main()
