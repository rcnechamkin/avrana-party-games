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
turn takes Income (Coup only when forced at 10+).

Every prompt has a `step` number; clients echo it so a late answer meant for an
earlier prompt is rejected instead of landing in a new one.

Lifecycle (phones sleep, so sockets come and go):
    here ──last socket closes──▶ reconnecting ──grace──▶ away (autopilot)
      (grace: AWAY_GRACE for prompts, AWAY_TURN_GRACE for the player's own turn)
      ▲──────────────── same token says hello again ───────────────┘
    * autopilot plays passively for away seats and `left` seats: Income (Coup only
      when forced), pass, allow, first card, keep hand. It never claims or bluffs.
    * if every seated human is disconnected the table PAUSES (timers frozen); if nobody
      returns within EMPTY_TABLE_ABANDON the game is abandoned and the room returns to
      the lobby. Anyone coming back resumes it exactly.
    * a player may forfeit (`leave_game`): their seat goes on autopilot at once and is
      eliminated at the next turn boundary.
    * `end_game` returns the room to the lobby when every other alive human is away/left.

How a game finished (take_outcome(); reported to an Avrana party session, AVR-24):
    completed  one seat is left standing: the results screen (game_end) with a winner
    abandoned  stopped before anyone won: the empty table timed out, `end_game`, a takeover of
               an empty table, or every seat forfeited at once (game_end with no winner)
Recording it changes no rule; the results screen still runs its course.
"""

from __future__ import annotations

import re
import time

from core.session import GameSession
from core.events import event

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
MAX_SPECTATORS = 6            # mid-game watchers allowed beyond the seats

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
AWAY_GRACE = 30               # seconds without a socket before autopilot answers prompts
AWAY_TURN_GRACE = 60          # ...and before it plays the away player's own turn (app switch)
AUTOPILOT_DELAY = 2.0         # autopilot answers this fast once it is in charge
EMPTY_TABLE_ABANDON = 300     # all seated humans gone this long -> abandon the game
PAUSE_TAKEOVER = 60           # ...but after this long anyone connected may end it
RESUME_MIN = 10               # a resumed stage gets at least this many seconds
LOG_KEEP = 40
RESERVED_NAMES = {"you", "bot", "test bot"}
RESERVED_RE = re.compile(r"^test ?bot( ?\d+)?$")


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
        # drop lobby ghosts (disconnected during the countdown and not seated)
        for t in [t for t, p in self.players.items()
                  if not p.is_bot and not p.connected and t not in self.participants]:
            del self.players[t]
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
            "step": 0,
            "log": [],
            "winner": None,
            "exchange_draw": None,                                    # PRIVATE
            "away_since": {},        # token -> monotonic time its last socket closed
            "left": set(),           # tokens that forfeited
            "paused": None,          # {"remaining": seconds, "since": monotonic} while empty
            "due": None,             # {"step": n, "at": {token: due_at}} for bots/autopilot
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
        event("bluff", "table", text=text)    # the PUBLIC table log only (never hidden cards)

    def _alive(self, tok):
        return bool(self.g["hand"].get(tok))

    def _alive_seats(self):
        return [t for t in self.g["seats"] if self._alive(t)]

    def _actor(self):
        return self.g["seats"][self.g["turn"]]

    def _is_bot(self, tok):
        p = self.players.get(tok)
        return bool(p and p.is_bot)

    def _new_step(self):
        self.g["step"] += 1

    def _set_stage(self, stage, seconds, **kw):
        p = self.g["pending"] or {}
        p.update(kw)
        p["stage"] = stage
        self.g["pending"] = p
        self._new_step()
        self._bump(time.time() + seconds)

    def _clear(self, *keys):
        for k in keys:
            (self.g["pending"] or {}).pop(k, None)

    # ------------------------------------------------------------------ turn flow

    def _begin_turn(self):
        self._apply_forfeits()
        if self._check_winner():
            return self.end_game()
        if not self._alive(self._actor()):
            return self._end_turn()
        self.g["pending"] = {"stage": "turn", "actor": self._actor()}
        self._new_step()
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

    def _apply_forfeits(self):
        """Forfeited seats are eliminated at a turn boundary, never mid-claim."""
        for tok in list(self.g["left"]):
            if self._alive(tok):
                self.g["revealed"][tok].extend(self.g["hand"][tok])
                self.g["hand"][tok] = []
                self.g["coins"][tok] = 0
                self._log("🏳 %s left the game." % self._name(tok))

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
        if self.phase != "playing" or self.g["paused"] or not self._alive(tok) \
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
        self._clear("claimant", "blocker", "block_role")
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
        self._clear("blocker", "block_role", "block_roles")
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

    def _block_stands(self):
        self._log("The block stands.")
        return self._action_fails()

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
        self._clear("loser", "lose_why", "lose_then")
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
                "fails": self._action_fails, "block_stands": self._block_stands,
                "resolve": self._resolve}[step]()

    # ------------------------------------------------------------------ input

    def game_action(self, token, msg):
        if self.phase != "playing" or self.g is None:
            return [self.fx("invalid", to=token, msg="No game in progress")]
        if msg.get("t") == "end_game" and self.party_round:
            # a Party round is the party's: only the Party Host ends it (avrana-party ADR 0011)
            return [self.fx("invalid", to=token, msg="Only the Party Host can end this game.")]
        if msg.get("t") == "end_game" and self.g["paused"] and token not in self.g["seats"]:
            return self._takeover(token)
        if token not in self.g["seats"]:
            return [self.fx("invalid", to=token, msg="You are watching this game")]
        t = msg.get("t")
        if t == "leave_game":
            return self._forfeit(token)
        if t == "end_game":
            return self._end_game_request(token)
        if self.g["paused"]:
            return [self.fx("invalid", to=token, msg="The game is paused")]
        if token in self.g["left"]:
            return [self.fx("invalid", to=token, msg="You left this game")]
        # a stale answer (meant for an earlier prompt) must not land in a new one
        step = msg.get("step")
        if step is not None and step != self.g["step"]:
            return [self.fx("invalid", to=token, msg="Too late: that moment has passed")]
        return self._apply(token, msg)

    def _apply(self, token, msg):
        """Apply a validated player/autopilot/bot message. Never raises on bad input."""
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
                    return self._block_stands()
                return []
            if choice == "challenge":
                if stage == "challenge":
                    return self._challenge(token, p["claimant"], p["claim_role"],
                                           ok_then="claim_ok", fail_then="fails")
                blocker, role = p["blocker"], p["block_role"]
                return self._challenge(token, blocker, role,
                                       ok_then="block_stands", fail_then="resolve")
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

    # ------------------------------------------------------------------ leaving / ending

    def _forfeit(self, tok):
        if not self._alive(tok) or tok in self.g["left"] or self._is_bot(tok):
            return [self.fx("invalid", to=tok, msg="You're not in this game")]
        self.g["left"].add(tok)
        self._log("🏳 %s is leaving (autopilot until the turn ends)." % self._name(tok))
        self.g["due"] = None
        if self._table_empty():
            return self.game_player_left(tok)       # nobody left at the table: pause
        return []

    def _end_game_request(self, tok):
        """Return the room to the lobby, allowed when nobody else alive is still here."""
        others = [t for t in self._alive_seats() if t != tok and not self._is_bot(t)
                  and t not in self.g["left"] and self.players.get(t)
                  and self.players[t].connected]
        if self._is_bot(tok) or others:
            return [self.fx("invalid", to=tok,
                            msg="Other players are still here: they can use Leave game")]
        self._log("Game ended by %s." % self._name(tok))
        fx = [self.fx("toast", msg="Game ended by %s" % self._name(tok))]
        return fx + self._abandon()

    def _takeover(self, tok):
        """A newcomer may end a table that has been EMPTY for PAUSE_TAKEOVER seconds
        (short phone sleeps stay protected; a really abandoned room frees up fast)."""
        wait = self.g["paused"]["since"] + PAUSE_TAKEOVER - time.monotonic()
        if wait > 0:
            return [self.fx("invalid", to=tok,
                            msg="The players just stepped away. Try again in %d s" % (int(wait) + 1))]
        self._log("Game ended by %s: the table was empty." % self._name(tok))
        return [self.fx("toast", msg="Game ended: the table was empty")] + self._abandon()

    def _abandon(self):
        self.g["paused"] = None
        self._outcome = "abandoned"
        return self.to_lobby()

    def end_game(self):
        # the rules decided the game is over; without a winner (everyone forfeited in the same
        # turn) nobody played it to an end, so it is reported as abandoned
        self._outcome = "completed" if self.g["winner"] is not None else "abandoned"
        return super().end_game()

    # ------------------------------------------------------------------ timers

    def game_tick(self):
        if self.g["paused"]:
            self._log("Game abandoned: the table was empty for %d minutes." % (EMPTY_TABLE_ABANDON // 60))
            return [self.fx("toast", msg="Game abandoned: nobody came back")] + self._abandon()
        p = self.g["pending"] or {}
        stage = p.get("stage")
        if stage == "turn":
            tok = self._actor()
            self._log("⏱ %s took too long." % self._name(tok))
            return self._passive_turn(tok)
        if stage == "challenge":
            p["waiting"] = []
            return self._after_claim_ok()
        if stage == "block_challenge":
            p["waiting"] = []
            return self._block_stands()
        if stage == "block":
            p["waiting"] = []
            return self._resolve()
        if stage == "lose":
            return self._reveal(p["loser"], 0, p["lose_why"], p["lose_then"])
        if stage == "exchange":
            tok = p["actor"]
            return self._finish_exchange(tok, list(range(len(self.g["hand"][tok]))))
        return []

    def _passive_turn(self, tok, coup_at=MUST_COUP_AT):
        """Income, or a Coup when rich enough (forced at 10+ for humans/autopilot)."""
        if self.g["coins"][tok] >= max(coup_at, COSTS["coup"]):
            targets = [t for t in self._alive_seats() if t != tok]
            most = max(len(self.g["hand"][t]) for t in targets)
            return self._start_action(tok, "coup", self.rng.choice(
                [t for t in targets if len(self.g["hand"][t]) == most]))
        return self._start_action(tok, "income", None)

    # ------------------------------------------------------------------ bots + autopilot

    def _needs_autopilot(self, tok, now):
        if self._is_bot(tok) or tok in self.g["left"]:
            return 0.0 if self._is_bot(tok) else AUTOPILOT_DELAY
        since = self.g["away_since"].get(tok)
        if since is None:
            return None
        grace = AWAY_TURN_GRACE if (self.g["pending"] or {}).get("stage") == "turn" else AWAY_GRACE
        return max(AUTOPILOT_DELAY, since + grace - now)

    def _bot_due(self, now=None):
        """(token, due_at) for the seat autopilot/bots must act for next, or None."""
        g = self.g
        p = g["pending"] if g else None
        if not p or self.phase != "playing" or g["paused"]:
            return None
        now = time.monotonic() if now is None else now
        cands = [self._actor()] if p["stage"] == "turn" else list(p.get("waiting", []))
        # remember when each seat became due for this step, so repeated pushes (e.g.
        # message spam) re-schedule the SAME moment instead of pushing it back
        if not g["due"] or g["due"]["step"] != g["step"]:
            g["due"] = {"step": g["step"], "at": {}}
        memo, best = g["due"]["at"], None
        for tok in cands:
            wait = self._needs_autopilot(tok, now)
            if wait is None:
                memo.pop(tok, None)
                continue
            at = now + (BOT_DELAY if self._is_bot(tok) else wait)
            memo[tok] = min(memo.get(tok, at), at)
            if best is None or memo[tok] < best[1]:
                best = (tok, memo[tok])       # the EARLIEST due seat acts first
        return best

    def next_bot_action(self):
        due = self._bot_due()
        if due is None:
            return None
        tok, at = due
        return (max(0.0, at - time.monotonic()), tok)

    def run_bot(self, bot_token):
        """Bots and autopilot play passively: they never claim, challenge or block."""
        # core.net only calls this after the scheduled delay and drops stale calls (seq)
        due = self._bot_due()
        if due is None or due[0] != bot_token:
            return []
        self.seq += 1                              # upstream convention (see spades)
        p = self.g["pending"]
        stage = p["stage"]
        if stage == "turn":
            # test bots Coup as soon as they can (so bot games end); autopilot only when forced
            return self._passive_turn(bot_token, coup_at=COSTS["coup"] if self._is_bot(bot_token)
                                      else MUST_COUP_AT)
        if stage in ("challenge", "block_challenge"):
            return self._apply(bot_token, {"t": "respond", "choice": "pass"})
        if stage == "block":
            return self._apply(bot_token, {"t": "respond", "choice": "allow"})
        if stage == "lose":
            return self._apply(bot_token, {"t": "lose", "card": 0})
        if stage == "exchange":
            return self._finish_exchange(bot_token, list(range(len(self.g["hand"][bot_token]))))
        return []

    # ------------------------------------------------------------------ connection

    def _table_empty(self):
        """Some non-forfeited human holds a seat, and none of them is connected."""
        humans = [t for t in self._seated_humans() if t in self.players]
        return (not self.g["paused"] and bool(humans)
                and not any(self.players[t].connected for t in humans))

    def _takeover_open(self):
        return bool(self.g and self.g["paused"]
                    and time.monotonic() >= self.g["paused"]["since"] + PAUSE_TAKEOVER)

    def _takeover_at(self, now):
        """When takeover opens, as a wall-clock ms for browsers: the wait left (monotonic) added
        to the wall clock as it reads now, so it stays right across a clock step."""
        if not self.g["paused"]:
            return None
        return int((time.time() + self.g["paused"]["since"] + PAUSE_TAKEOVER - now) * 1000)

    def _prune_lobby_ghosts(self):
        if self.phase == "lobby":
            for t in [t for t, p in self.players.items() if not p.is_bot and not p.connected]:
                del self.players[t]

    def _seated_humans(self):
        """Humans who still hold (or held) a seat and haven't forfeited."""
        return [t for t in (self.g["seats"] if self.g else [])
                if not self._is_bot(t) and t not in self.g["left"]]

    def join(self, token, name=None, avatar=None):
        p0 = self.players.get(token)
        old_name = p0.name if p0 else None
        if p0 is None and self.in_game():
            # mid-game arrivals are never seated (spectators), so the 6-seat cap doesn't
            # apply to them; bounded so one device can't flood the room with tokens
            self.MAX_HUMANS = MAX_SEATS + MAX_SPECTATORS
        try:
            player, fx = super().join(token, name, avatar)
        finally:
            self.__dict__.pop("MAX_HUMANS", None)
        if player is not None:
            if self.in_game() and old_name is not None:
                player.name = old_name            # no renaming mid-game
            else:
                self._fix_name(player)
        return player, fx

    def set_profile(self, token, name=None, avatar=None):
        if self.in_game():
            name = None                           # names are locked during a game
        fx = super().set_profile(token, name, avatar)
        p = self.players.get(token)
        if p is not None and not self.in_game():
            self._fix_name(p)
        return fx

    def _fix_name(self, player):
        """Names are public identity: no reserved words, no duplicates."""
        base = player.name
        if base.strip().lower() in RESERVED_NAMES or RESERVED_RE.match(base.strip().lower()):
            base = "Player"
        taken = {q.name.lower() for q in self.players.values() if q is not player}
        name, n = base, 2
        while name.lower() in taken:
            name = "%s %d" % (base[:11], n)
            n += 1
        player.name = name

    def game_player_back(self, token):
        if not self.g:
            return []
        if self.g["away_since"].pop(token, None) is None and not self.g["paused"]:
            return []                               # a second tab / re-hello, not a return
        self.g["due"] = None
        fx = [self.fx("toast", msg="%s is back" % self._name(token))]
        if self.g["paused"]:
            rem = max(self.g["paused"]["remaining"], RESUME_MIN)
            self.g["paused"] = None
            self._bump(time.time() + rem)
            self._log("%s is back: game resumed." % self._name(token))
        return fx

    def game_player_left(self, token):
        """A seated human's last socket closed: start the grace clock, pause if empty."""
        if not self.g or self.phase != "playing":
            return []
        self.g["away_since"].setdefault(token, time.monotonic())
        self.g["due"] = None
        if self._table_empty():
            self.g["paused"] = {"remaining": self.remaining() or 0.0, "since": time.monotonic()}
            self._bump(time.time() + EMPTY_TABLE_ABANDON)      # a real deadline, never None
            self._log("Everyone stepped away: game paused.")
        return []

    def leave(self, token):
        # Only difference from the base class: a running game is never abandoned the
        # instant every socket drops (phones sleep). Presence handling lives in
        # game_player_left / game_player_back.
        if self.in_game() and token in self.participants:
            self.seq += 1
            p = self.players.get(token)
            if p is not None:
                p.connected = False
                p.ready = False
            return self.game_player_left(token)
        if self.party_round and token in self.participants:
            # a party round's seats are the party's: a phone that drops before the start keeps
            # its seat (it starts away); nothing here aborts the round (AVR-129)
            self.seq += 1
            if token in self.players:
                self.players[token].connected = False
            return []
        if self.phase == "countdown" and token in self.players \
                and not self.players[token].is_bot and self.players[token].ready:
            # a refresh during the 3-2-1 must not cost the seat: keep the player (and
            # their ready flag); ghosts that never come back are pruned at game_start
            self.seq += 1
            self.players[token].connected = False
            if len(self._connected_ready()) < self.MIN_PLAYERS:
                self._bump(None)
                self.phase = "lobby"
                self._prune_lobby_ghosts()
                return [self.fx("toast", msg="Launch aborted — not enough players")]
            return []
        return super().leave(token)

    def set_ready(self, token, ready):
        fx = super().set_ready(token, ready)
        self._prune_lobby_ghosts()                   # an aborted countdown leaves no ghosts
        return fx

    def tick(self, gen):
        # only the results-screen timer itself may end game_end (see to_lobby)
        self._results_timer = self.phase == "game_end" and gen == self.gen
        try:
            fx = super().tick(gen)
        finally:
            self._results_timer = False
        self._prune_lobby_ghosts()                   # e.g. a countdown that aborted
        return fx

    def to_lobby(self):
        # The results screen always runs its course: core.net's "again" verb (which any
        # connected token, even a spectator, may send) is ignored during game_end.
        if self.phase == "game_end" and not getattr(self, "_results_timer", False):
            return []
        return super().to_lobby()

    # ------------------------------------------------------------------ state (masked)

    def _presence(self, tok, now):
        if self._is_bot(tok):
            return "bot"
        if tok in self.g["left"]:
            return "left"
        p = self.players.get(tok)
        if p is not None and p.connected:
            return "here"
        since = self.g["away_since"].get(tok, now)
        return "reconnecting" if now - since < AWAY_GRACE else "away"

    def game_state(self, viewer_token):
        g = self.g
        if g is None:
            return None
        now = time.monotonic()
        p = (g["pending"] or {}) if self.phase == "playing" else {"stage": "over"}
        stage = p.get("stage")
        pend = {                                 # PUBLIC view of the pending step
            "stage": stage,
            "step": g["step"],
            "actor": self._pid(p.get("actor")),
            "action": p.get("action"),
            "label": LABELS.get(p.get("action"), ""),
            "target": self._pid(p.get("target")),
            "claim_role": p.get("claim_role"),
            "blocker": self._pid(p.get("blocker")) if stage == "block_challenge" else None,
            "block_role": p.get("block_role") if stage == "block_challenge" else None,
            "loser": self._pid(p.get("loser")) if stage == "lose" else None,
            "waiting": [self._pid(t) for t in p.get("waiting", [])],
        }
        seats = [{
            "pid": self._pid(t), "name": self._name(t),
            "bot": self._is_bot(t),
            "coins": g["coins"][t],
            "influence": len(g["hand"][t]),        # a COUNT only, never the cards
            "revealed": list(g["revealed"][t]),
            "alive": self._alive(t),
            "turn": self._alive(t) and t == self._actor() and self.phase == "playing",
            "presence": self._presence(t, now),
        } for t in g["seats"]]
        st = {
            "kind": "bluff",
            "roles": ROLES,
            "seats": seats,
            "deck_count": len(g["deck"]),
            "pending": pend,
            "paused": bool(g["paused"]),
            "takeover_at": self._takeover_at(now),
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
                "left": viewer_token in g["left"],
            }
            if viewer_token in p.get("waiting", []) and not g["paused"] \
                    and viewer_token not in g["left"]:
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

    def game_state_spectator(self):
        """A Party spectator's view (AVR-129): intentionally omniscient. The public table plus
        every seat's hidden cards (and the exchange draw while one is open), so watching BLUFF
        shows every bluff. core.net sends this only to Party spectator sockets: never to a
        player, and never to an anonymous watcher or a TV (a screen the players can see)."""
        st = self.game_state(None)
        if st is None:
            return None
        g = self.g
        for seat, t in zip(st["seats"], g["seats"]):
            seat["cards"] = list(g["hand"][t])
        p = (g["pending"] or {}) if self.phase == "playing" else {}
        if p.get("stage") == "exchange":
            st["exchange_draw"] = list(g["exchange_draw"] or [])
        st["omniscient"] = True
        return st
