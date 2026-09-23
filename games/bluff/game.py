"""BLUFF (working title): the Avrana bluffing card game, baseline prototype.

A TEMPORARY mechanical baseline modelled on Coup-style play, used to prove the full
interaction model (hidden roles, claims, challenges, blocks, challenge-the-block,
losing influence, currency, elimination, winning). The role names and text are
original placeholders; mechanics and identity are to be redesigned once this plays
cleanly on phones.

Every phone is a complete client. The server is authoritative, and game_state()
filters per viewer: a player receives their own hidden cards (and their exchange
draw) and nobody else's. The deck order is never sent.

Flow (all driven by the server):
    turn ──act──▶ [claim?] challenge ──▶ [blockable?] block ──▶ block_challenge
                                   └──────────────────────────────▶ resolve ──▶ next turn
    losing a card may pause for a `lose` choice; the exchange pauses for an `exchange` choice.
Every waiting stage has a deadline; when it fires, remaining responders pass/allow,
a lose choice takes the first card, an exchange keeps the current hand, and an idle
turn takes Income (or the forced Coup).
"""

from __future__ import annotations

import time

from core.session import GameSession

# ---- placeholder roles (original names; baseline Coup-style duties) ----------
ROLES = {
    "Banker":   {"icon": "🏦", "text": "Tax: take 3 coins. Blocks Foreign Aid."},
    "Agent":    {"icon": "🗡", "text": "Strike: pay 3, target loses a card."},
    "Smuggler": {"icon": "🧳", "text": "Steal: take 2 coins from a player. Blocks stealing."},
    "Broker":   {"icon": "🔄", "text": "Exchange: draw 2, keep any, return the rest. Blocks stealing."},
    "Guardian": {"icon": "🛡", "text": "Blocks a Strike against you."},
}
COPIES = 3
START_COINS = 2
MUST_COUP_AT = 10
COSTS = {"coup": 7, "strike": 3}
MAX_SEATS = 6

# action -> (claimed role or None, needs target, who may block, roles that block)
ACTIONS = {
    "income":   (None,       False, None,     ()),
    "aid":      (None,       False, "anyone", ("Banker",)),
    "coup":     (None,       True,  None,     ()),
    "tax":      ("Banker",   False, None,     ()),
    "strike":   ("Agent",    True,  "target", ("Guardian",)),
    "steal":    ("Smuggler", True,  "target", ("Smuggler", "Broker")),
    "exchange": ("Broker",   False, None,     ()),
}
LABELS = {"income": "Income (+1)", "aid": "Foreign Aid (+2)", "coup": "Coup (pay 7)",
          "tax": "Tax (+3)", "strike": "Strike (pay 3)", "steal": "Steal (2)",
          "exchange": "Exchange"}

TURN_SECONDS = 90
RESPONSE_SECONDS = 20
LOSE_SECONDS = 30
EXCHANGE_SECONDS = 45
BOT_DELAY = 0.8
LOG_KEEP = 40


def _str(x, n=32):
    return isinstance(x, str) and 0 < len(x) <= n


class BluffSession(GameSession):
    MIN_PLAYERS = 1                  # a solo human can play against test bots
    MAX_HUMANS = MAX_SEATS
    DEFAULT_SETTINGS = {"bots": 0}

    def __init__(self, rng=None):
        super().__init__(rng)
        self.g = None

    def validate_settings(self, patch):
        out = {}
        b = patch.get("bots")
        if isinstance(b, int) and not isinstance(b, bool) and 0 <= b <= MAX_SEATS - 1:
            out["bots"] = b
        return out

    # ------------------------------------------------------------------ setup

    def game_start(self):
        seats = list(self.participants)[:MAX_SEATS]
        want = max(self.settings.get("bots", 0), 2 - len(seats))
        for i in range(max(0, min(want, MAX_SEATS - len(seats)))):
            seats.append(self.add_bot("Test bot %d" % (i + 1)).token)
        deck = [r for r in ROLES for _ in range(COPIES)]
        self.rng.shuffle(deck)
        self.g = {
            "seats": seats,
            "deck": deck,
            "hand": {t: [deck.pop(), deck.pop()] for t in seats},   # PRIVATE
            "revealed": {t: [] for t in seats},
            "coins": {t: START_COINS for t in seats},
            "turn": 0,
            "pending": None,
            "log": [],
            "winner": None,
            "exchange_draw": None,                                    # PRIVATE
        }
        self.phase = "playing"
        self._log("Game on: %d players, %d coins each." % (len(seats), START_COINS))
        return self._begin_turn()

    # ------------------------------------------------------------------ helpers

    def _name(self, tok):
        p = self.players.get(tok)
        return p.name if p else "?"

    def _pid(self, tok):
        p = self.players.get(tok)
        return p.pid if p else None

    def _log(self, text):
        self.g["log"].append(text)
        del self.g["log"][:-LOG_KEEP]

    def _alive(self, tok):
        return bool(self.g["hand"].get(tok))

    def _alive_seats(self):
        return [t for t in self.g["seats"] if self._alive(t)]

    def _actor(self):
        return self.g["seats"][self.g["turn"]]

    def _set_stage(self, stage, seconds, **kw):
        p = self.g["pending"] or {}
        p.update(kw)
        p["stage"] = stage
        self.g["pending"] = p
        self._bump(time.time() + seconds)

    # ------------------------------------------------------------------ turn flow

    def _begin_turn(self):
        if self._check_winner():
            return self.end_game()
        self.g["pending"] = {"stage": "turn", "actor": self._actor()}
        self._bump(time.time() + TURN_SECONDS)
        return []

    def _end_turn(self):
        if self._check_winner():
            return self.end_game()
        seats, n = self.g["seats"], len(self.g["seats"])
        i = self.g["turn"]
        for _ in range(n):
            i = (i + 1) % n
            if self._alive(seats[i]):
                break
        self.g["turn"] = i
        return self._begin_turn()

    def _check_winner(self):
        alive = self._alive_seats()
        if len(alive) <= 1 and self.g["winner"] is None:
            self.g["winner"] = alive[0] if alive else None
            if alive:
                self._log("🏆 %s wins." % self._name(alive[0]))
            return True
        return self.g["winner"] is not None

    def legal_actions(self, tok):
        """Actions `tok` may take now, with valid targets (pids)."""
        if self.phase != "playing" or not self._alive(tok) \
                or (self.g["pending"] or {}).get("stage") != "turn" or self._actor() != tok:
            return []
        coins = self.g["coins"][tok]
        others = [self._pid(t) for t in self._alive_seats() if t != tok]
        out = []
        for a, (_, needs_target, _, _) in ACTIONS.items():
            if coins >= MUST_COUP_AT and a != "coup":
                continue
            if coins < COSTS.get(a, 0):
                continue
            out.append({"action": a, "label": LABELS[a], "claims": ACTIONS[a][0],
                        "targets": others if needs_target else None})
        return out

    def _start_action(self, tok, action, target):
        role, needs_target, _, _ = ACTIONS[action]
        g = self.g
        g["coins"][tok] -= COSTS.get(action, 0)
        g["pending"] = {"stage": None, "actor": tok, "action": action, "target": target,
                        "claim_role": role}
        who = self._name(tok)
        tname = (" → " + self._name(target)) if target else ""
        if action == "income":
            g["coins"][tok] += 1
            self._log("%s takes Income (+1)." % who)
            return self._end_turn()
        if action == "coup":
            self._log("%s launches a Coup%s." % (who, tname))
            return self._lose(target, "Coup", then="end_turn")
        if action == "aid":
            self._log("%s asks for Foreign Aid (+2)." % who)
            return self._open_block()
        self._log("%s claims %s %s to %s%s." % (who, ROLES[role]["icon"], role,
                                               LABELS[action].split(" (")[0], tname))
        self._set_stage("challenge", RESPONSE_SECONDS, claimant=tok,
                        waiting=[t for t in self._alive_seats() if t != tok])
        return []

    def _open_block(self):
        p = self.g["pending"]
        _, _, who_blocks, roles = ACTIONS[p["action"]]
        if who_blocks == "target":
            eligible = [p["target"]] if self._alive(p["target"]) else []
        elif who_blocks == "anyone":
            eligible = [t for t in self._alive_seats() if t != p["actor"]]
        else:
            eligible = []
        if not eligible:
            return self._resolve()
        self._set_stage("block", RESPONSE_SECONDS, waiting=eligible, block_roles=list(roles))
        return []

    def _after_claim_ok(self):
        p = self.g["pending"]
        if ACTIONS[p["action"]][2] is not None:
            return self._open_block()
        return self._resolve()

    def _resolve(self):
        g, p = self.g, self.g["pending"]
        tok, a, target = p["actor"], p["action"], p.get("target")
        if a == "aid":
            g["coins"][tok] += 2
            self._log("%s takes Foreign Aid (+2)." % self._name(tok))
        elif a == "tax":
            g["coins"][tok] += 3
            self._log("%s takes Tax (+3)." % self._name(tok))
        elif a == "steal":
            amt = min(2, g["coins"][target]) if self._alive(target) else 0
            g["coins"][target] -= amt
            g["coins"][tok] += amt
            self._log("%s steals %d from %s." % (self._name(tok), amt, self._name(target)))
        elif a == "strike":
            if self._alive(target):
                return self._lose(target, "Strike", then="end_turn")
        elif a == "exchange":
            draw = [g["deck"].pop() for _ in range(min(2, len(g["deck"])))]
            g["exchange_draw"] = draw
            self._log("%s exchanges cards with the deck." % self._name(tok))
            self._set_stage("exchange", EXCHANGE_SECONDS, waiting=[tok])
            return []
        return self._end_turn()

    def _action_fails(self):
        p = self.g["pending"]
        self._log("%s's %s fails." % (self._name(p["actor"]),
                                      LABELS[p["action"]].split(" (")[0]))
        return self._end_turn()

    # ------------------------------------------------------------------ challenges

    def _challenge(self, challenger, claimant, role, ok_then, fail_then):
        """Resolve a challenge of `claimant` holding `role`."""
        g = self.g
        self._log("%s challenges %s's %s!" % (self._name(challenger), self._name(claimant), role))
        hand = g["hand"][claimant]
        if role in hand:
            # proven: reveal publicly, shuffle back, draw a replacement (privately)
            hand.remove(role)
            g["deck"].append(role)
            self.rng.shuffle(g["deck"])
            hand.append(g["deck"].pop())
            self._log("%s reveals %s %s: the claim was TRUE. They shuffle it back and draw anew."
                      % (self._name(claimant), ROLES[role]["icon"], role))
            return self._lose(challenger, "lost the challenge", then=ok_then)
        self._log("%s cannot show %s: the claim was a BLUFF." % (self._name(claimant), role))
        return self._lose(claimant, "caught bluffing", then=fail_then)

    # ------------------------------------------------------------------ losing influence

    def _lose(self, tok, why, then):
        hand = self.g["hand"][tok]
        if not hand:
            return self._continue(then)
        if len(hand) == 1:
            return self._reveal(tok, 0, why, then)
        p = self.g["pending"] or {}
        p["lose_then"] = then
        p["lose_why"] = why
        self.g["pending"] = p
        self._set_stage("lose", LOSE_SECONDS, loser=tok, waiting=[tok])
        return []

    def _reveal(self, tok, idx, why, then):
        g = self.g
        card = g["hand"][tok].pop(idx)
        g["revealed"][tok].append(card)
        self._log("%s loses %s %s (%s)." % (self._name(tok), ROLES[card]["icon"], card, why))
        if not g["hand"][tok]:
            self._log("☠ %s is out." % self._name(tok))
            g["coins"][tok] = 0
        if self._check_winner():
            return self.end_game()
        return self._continue(then)

    def _continue(self, step):
        return {"end_turn": self._end_turn, "claim_ok": self._after_claim_ok,
                "fails": self._action_fails, "resolve": self._resolve}[step]()

    # ------------------------------------------------------------------ input

    def game_action(self, token, msg):
        if self.phase != "playing" or self.g is None:
            return [self.fx("invalid", to=token, msg="No game in progress")]
        if token not in self.g["seats"]:
            return [self.fx("invalid", to=token, msg="You are watching this game")]
        t = msg.get("t")
        p = self.g["pending"] or {}
        stage = p.get("stage")
        bad = [self.fx("invalid", to=token, msg="Not now")]

        if t == "act":
            action, target_pid = msg.get("action"), msg.get("target")
            legal = {a["action"]: a for a in self.legal_actions(token)}
            if not _str(action) or action not in legal:
                return bad
            target = None
            if legal[action]["targets"] is not None:
                if not _str(target_pid) or target_pid not in legal[action]["targets"]:
                    return [self.fx("invalid", to=token, msg="Pick a valid target")]
                target = self.by_pid(target_pid).token
            return self._start_action(token, action, target)

        if token not in p.get("waiting", []):
            return bad

        if t == "respond" and stage in ("challenge", "block_challenge"):
            choice = msg.get("choice")
            if choice == "pass":
                p["waiting"].remove(token)
                if not p["waiting"]:
                    if stage == "challenge":
                        return self._after_claim_ok()
                    self._log("The block stands.")
                    return self._action_fails()
                return []
            if choice == "challenge":
                if stage == "challenge":
                    return self._challenge(token, p["claimant"], p["claim_role"],
                                           ok_then="claim_ok", fail_then="fails")
                return self._challenge(token, p["blocker"], p["block_role"],
                                       ok_then="fails", fail_then="resolve")
            return bad

        if t == "respond" and stage == "block":
            choice = msg.get("choice")
            if choice == "allow":
                p["waiting"].remove(token)
                return self._resolve() if not p["waiting"] else []
            if choice == "block":
                role = msg.get("role")
                if not _str(role) or role not in p.get("block_roles", []):
                    return [self.fx("invalid", to=token, msg="That role can't block this")]
                self._log("%s blocks, claiming %s %s." % (self._name(token), ROLES[role]["icon"], role))
                self._set_stage("block_challenge", RESPONSE_SECONDS, blocker=token,
                                block_role=role,
                                waiting=[x for x in self._alive_seats() if x != token])
                return []
            return bad

        if t == "lose" and stage == "lose":
            idx = msg.get("card")
            if not isinstance(idx, int) or isinstance(idx, bool) \
                    or not 0 <= idx < len(self.g["hand"][token]):
                return [self.fx("invalid", to=token, msg="Pick one of your cards")]
            return self._reveal(token, idx, p["lose_why"], p["lose_then"])

        if t == "keep" and stage == "exchange":
            keep = msg.get("cards")
            pool = self.g["hand"][token] + (self.g["exchange_draw"] or [])
            need = len(self.g["hand"][token])
            if not (isinstance(keep, list) and len(keep) == need
                    and all(isinstance(i, int) and not isinstance(i, bool) for i in keep)
                    and len(set(keep)) == need and all(0 <= i < len(pool) for i in keep)):
                return [self.fx("invalid", to=token, msg="Keep exactly %d card(s)" % need)]
            return self._finish_exchange(token, keep)

        return bad

    def _finish_exchange(self, tok, keep):
        g = self.g
        pool = g["hand"][tok] + (g["exchange_draw"] or [])
        g["hand"][tok] = [pool[i] for i in keep]
        g["deck"].extend(c for i, c in enumerate(pool) if i not in keep)
        self.rng.shuffle(g["deck"])
        g["exchange_draw"] = None
        return self._end_turn()

    # ------------------------------------------------------------------ timers

    def game_tick(self):
        p = self.g["pending"] or {}
        stage = p.get("stage")
        if stage == "turn":
            tok = self._actor()
            self._log("⏱ %s took too long." % self._name(tok))
            return self._auto_turn(tok)
        if stage == "challenge":
            p["waiting"] = []
            return self._after_claim_ok()
        if stage == "block_challenge":
            p["waiting"] = []
            self._log("The block stands.")
            return self._action_fails()
        if stage == "block":
            p["waiting"] = []
            return self._resolve()
        if stage == "lose":
            return self._reveal(p["loser"], 0, p["lose_why"], p["lose_then"])
        if stage == "exchange":
            tok = p["actor"]
            return self._finish_exchange(tok, list(range(len(self.g["hand"][tok]))))
        return []

    def _auto_turn(self, tok):
        if self.g["coins"][tok] >= COSTS["coup"]:
            targets = [t for t in self._alive_seats() if t != tok]
            return self._start_action(tok, "coup", self.rng.choice(targets))
        return self._start_action(tok, "income", None)

    # ------------------------------------------------------------------ test bots

    def _bot_due(self):
        p = self.g["pending"] if self.g else None
        if not p or self.phase != "playing":
            return None
        if p["stage"] == "turn":
            tok = self._actor()
            return tok if self.players[tok].is_bot else None
        for tok in p.get("waiting", []):
            if self.players.get(tok) and self.players[tok].is_bot:
                return tok
        return None

    def next_bot_action(self):
        tok = self._bot_due()
        return (BOT_DELAY, tok) if tok else None

    def run_bot(self, bot_token):
        """Test bots never claim a role: Income (Coup when rich), always pass/allow,
        lose their first card, keep their hand on exchange."""
        if self._bot_due() != bot_token:
            return []
        p = self.g["pending"]
        stage = p["stage"]
        if stage == "turn":
            return self._auto_turn(bot_token)
        if stage in ("challenge", "block_challenge"):
            return self.game_action(bot_token, {"t": "respond", "choice": "pass"})
        if stage == "block":
            return self.game_action(bot_token, {"t": "respond", "choice": "allow"})
        if stage == "lose":
            return self.game_action(bot_token, {"t": "lose", "card": 0})
        return []

    # ------------------------------------------------------------------ connection

    def leave(self, token):
        # phones sleep: never abandon a running game when every socket drops;
        # deadlines keep it moving (idle players auto-act).
        if self.in_game() and token in self.participants:
            self.seq += 1
            p = self.players.get(token)
            if p is not None:
                p.connected = False
                p.ready = False
            return []
        return super().leave(token)

    # ------------------------------------------------------------------ state (masked)

    def game_state(self, viewer_token):
        g = self.g
        if g is None:
            return None
        p = (g["pending"] or {}) if self.phase == "playing" else {"stage": "over"}
        pend = {                                 # PUBLIC view of the pending step
            "stage": p.get("stage"),
            "actor": self._pid(p.get("actor")),
            "action": p.get("action"),
            "label": LABELS.get(p.get("action"), ""),
            "target": self._pid(p.get("target")),
            "claim_role": p.get("claim_role"),
            "blocker": self._pid(p.get("blocker")),
            "block_role": p.get("block_role"),
            "loser": self._pid(p.get("loser")),
            "waiting": [self._pid(t) for t in p.get("waiting", [])],
        }
        seats = [{
            "pid": self._pid(t), "name": self._name(t),
            "bot": bool(self.players.get(t) and self.players[t].is_bot),
            "coins": g["coins"][t],
            "influence": len(g["hand"][t]),        # a COUNT only, never the cards
            "revealed": list(g["revealed"][t]),
            "alive": self._alive(t),
            "turn": self._alive(t) and t == self._actor() and self.phase == "playing",
        } for t in g["seats"]]
        st = {
            "kind": "bluff",
            "roles": ROLES,
            "seats": seats,
            "deck_count": len(g["deck"]),
            "pending": pend,
            "log": list(g["log"][-15:]),
            "winner": self._pid(g["winner"]),
            "me": None,
        }
        if viewer_token in g["seats"]:           # PRIVATE: the viewer's own cards only
            me = {
                "pid": self._pid(viewer_token),
                "cards": list(g["hand"][viewer_token]),
                "actions": self.legal_actions(viewer_token),
                "prompt": None,
            }
            if viewer_token in p.get("waiting", []):
                stage = p.get("stage")
                if stage in ("challenge", "block_challenge"):
                    me["prompt"] = {"kind": "challenge"}
                elif stage == "block":
                    me["prompt"] = {"kind": "block", "roles": list(p.get("block_roles", []))}
                elif stage == "lose":
                    me["prompt"] = {"kind": "lose"}
                elif stage == "exchange":
                    me["prompt"] = {"kind": "exchange",
                                    "pool": list(g["hand"][viewer_token]) + list(g["exchange_draw"] or []),
                                    "keep": len(g["hand"][viewer_token])}
            st["me"] = me
        return st
