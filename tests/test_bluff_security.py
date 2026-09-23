"""BLUFF security / private-state regression tests (hostile-client audit).

Differential tests: two sessions identical except for one player's HIDDEN state;
every other viewer's state_for() must be byte-identical at every step.
Authorization tests: every verb from every wrong seat/stage must be rejected
without mutating the game.
"""

from __future__ import annotations

import copy
import json
import random

import pytest

from core.session import clean_name
from games.bluff.game import BluffSession

A, B, C, D = "tokenA_alice", "tokenB_bob", "tokenC_cara", "tokenD_dave"
TOKS = {"A": A, "B": B, "C": C}


def game(n=3, bots=0, seed=1):
    s = BluffSession(rng=random.Random(seed))
    for t, name in list(zip((A, B, C), ("Alice", "Bob", "Cara")))[:n]:
        s.join(t, name)
        s.set_ready(t, True)
    if bots:
        s.set_settings(A, {"bots": bots})
    s.start(A)
    s.tick(s.gen)
    assert s.phase == "playing"
    return s


def rig(s, deck=None, **hands):
    for k, cards in hands.items():
        s.g["hand"][TOKS[k]] = list(cards)
    first = TOKS[next(iter(hands))]
    s.g["turn"] = s.g["seats"].index(first)
    s.g["pending"] = {"stage": "turn", "actor": first}
    if deck is not None:
        s.g["deck"] = list(deck)


def act(s, tok, action, target=None):
    msg = {"t": "act", "action": action}
    if target:
        msg["target"] = s.players[target].pid
    return s.game_action(tok, msg)


def snap(s, tok):
    st = s.state_for(tok)
    st.pop("now", None)
    st.pop("deadline", None)          # wall-clock; differs between the two runs
    return json.dumps(st, sort_keys=True)


def core(s):
    """Everything that matters, for 'nothing changed' assertions."""
    g = copy.deepcopy(s.g)
    return json.dumps([g, s.phase], sort_keys=True, default=str)


def stage(s):
    return s.g["pending"]["stage"]


class Twin:
    """Run the same script on two sessions; compare observers each step."""

    def __init__(self, s1, s2, observers):
        self.s = (s1, s2)
        self.obs = observers
        self.check("setup")

    def check(self, label):
        for o in self.obs:
            a, b = snap(self.s[0], o), snap(self.s[1], o)
            assert a == b, "hidden state leaked to %r at %s" % (o, label)

    def do(self, fn, label):
        fx1, fx2 = fn(self.s[0]), fn(self.s[1])
        # fx to observers must match too (strip ones addressed to the victim)
        pub = lambda fx: [f for f in (fx or []) if f.get("to") in self.obs or f.get("to") is None]
        assert json.dumps(pub(fx1), sort_keys=True) == json.dumps(pub(fx2), sort_keys=True), label
        self.check(label)


# ======================================================== hidden-card leakage

def test_claim_truth_invisible_before_and_without_challenge():
    """A true Tax and a bluffed Tax look identical to everyone else."""
    s1, s2 = game(), game()
    rig(s1, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    rig(s2, A=["Guardian", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    t = Twin(s1, s2, [B, C, None])
    t.do(lambda s: act(s, A, "tax"), "claim")
    t.do(lambda s: s.game_action(B, {"t": "respond", "choice": "pass"}), "B pass")
    t.do(lambda s: s.game_action(C, {"t": "respond", "choice": "pass"}), "C pass")
    assert s1.g["coins"][A] == s2.g["coins"][A] == 5


@pytest.mark.parametrize("action,target", [("steal", "B"), ("strike", "B"), ("exchange", None)])
def test_other_claims_invisible_until_challenged(action, target):
    s1, s2 = game(), game()
    base = dict(B=["Guardian", "Smuggler"], C=["Broker", "Banker"])
    rig(s1, A=["Smuggler", "Agent"] if action != "exchange" else ["Broker", "Agent"], **base)
    rig(s2, A=["Banker", "Banker"], **base)
    for s in (s1, s2):
        s.g["coins"][A] = 3
        s.g["deck"] = ["Guardian", "Agent", "Banker", "Smuggler"]
    t = Twin(s1, s2, [B, C, None])
    t.do(lambda s: act(s, A, action, TOKS[target] if target else None), "claim")
    t.do(lambda s: s.game_action(B, {"t": "respond", "choice": "pass"}), "B pass")
    t.do(lambda s: s.game_action(C, {"t": "respond", "choice": "pass"}), "C pass")
    if action in ("steal", "strike"):
        t.do(lambda s: s.game_action(B, {"t": "respond", "choice": "allow"}), "allow")
        if stage(s1) == "lose":
            t.do(lambda s: s.game_action(B, {"t": "lose", "card": 0}), "lose")
    else:
        assert stage(s1) == "exchange"
        t.do(lambda s: s.game_action(A, {"t": "keep", "cards": [3, 1]}), "keep")


def test_proven_claim_replacement_card_stays_private():
    """A wins a challenge; the card A draws back must not be visible to anyone else."""
    s1, s2 = game(), game()
    common = dict(B=["Guardian", "Smuggler"], C=["Broker", "Banker"])
    rig(s1, deck=["Agent", "Agent", "Agent"], A=["Banker", "Guardian"], **common)
    rig(s2, deck=["Broker", "Smuggler", "Guardian"], A=["Banker", "Guardian"], **common)
    t = Twin(s1, s2, [B, C, None])
    t.do(lambda s: act(s, A, "tax"), "claim")
    t.do(lambda s: s.game_action(B, {"t": "respond", "choice": "challenge"}), "challenge")
    assert stage(s1) == "lose" and s1.g["hand"][A] != s2.g["hand"][A]   # different redraws
    t.do(lambda s: s.game_action(B, {"t": "lose", "card": 1}), "B loses")
    # A's own view does reveal the new card (sanity: we tested something real)
    assert s1.state_for(A)["game"]["me"]["cards"] != s2.state_for(A)["game"]["me"]["cards"]


def test_exchange_draw_private_to_everyone_else():
    s1, s2 = game(), game()
    common = dict(A=["Broker", "Agent"], B=["Guardian", "Smuggler"], C=["Banker", "Banker"])
    rig(s1, deck=["Agent", "Guardian", "Smuggler"], **common)
    rig(s2, deck=["Agent", "Banker", "Broker"], **common)
    t = Twin(s1, s2, [B, C, None])
    t.do(lambda s: act(s, A, "exchange"), "claim")
    t.do(lambda s: s.game_action(B, {"t": "respond", "choice": "pass"}), "pass")
    t.do(lambda s: s.game_action(C, {"t": "respond", "choice": "pass"}), "pass2")
    assert stage(s1) == "exchange"
    assert s1.g["exchange_draw"] != s2.g["exchange_draw"]
    t.do(lambda s: s.game_action(A, {"t": "keep", "cards": [2, 3]}), "keep")
    assert s1.g["hand"][A] != s2.g["hand"][A]


def test_exchange_timeout_private():
    s1, s2 = game(), game()
    common = dict(A=["Broker", "Agent"], B=["Guardian", "Smuggler"], C=["Banker", "Banker"])
    rig(s1, deck=["Agent", "Guardian", "Smuggler"], **common)
    rig(s2, deck=["Agent", "Banker", "Broker"], **common)
    t = Twin(s1, s2, [B, C, None])
    t.do(lambda s: act(s, A, "exchange"), "claim")
    t.do(lambda s: s.tick(s.gen), "challenge window expires")
    t.do(lambda s: s.tick(s.gen), "exchange expires")


def test_lose_prompt_and_game_end_do_not_reveal_remaining_cards():
    """Coup A down, then let A win: B's/spectator's view never depends on A's hidden card."""
    s1, s2 = game(n=2), game(n=2)
    rig(s1, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    rig(s2, A=["Guardian", "Agent"], B=["Guardian", "Smuggler"])
    for s in (s1, s2):
        s.g["coins"][B] = 7
        s.g["coins"][A] = 7
        s.g["turn"] = s.g["seats"].index(B)
        s.g["pending"] = {"stage": "turn", "actor": B}
    t = Twin(s1, s2, [B, None])
    t.do(lambda s: act(s, B, "coup", A), "coup A")
    assert stage(s1) == "lose"
    t.do(lambda s: s.game_action(A, {"t": "lose", "card": 1}), "A reveals Agent")
    t.do(lambda s: act(s, A, "coup", B), "coup B")
    t.do(lambda s: s.game_action(B, {"t": "lose", "card": 0}), "B loses")
    s1.g["coins"][A] = s2.g["coins"][A] = 7
    s1.g["pending"]["stage"] = s2.g["pending"]["stage"] = "turn"
    t.do(lambda s: act(s, A, "coup", B) if s.g["pending"]["actor"] == A else [], "final")
    t.do(lambda s: s.tick(s.gen) if s.phase == "playing" else [], "timer")
    # finish the game deterministically
    for s in (s1, s2):
        s.g["hand"][B] = []
        s.g["revealed"][B] = ["Guardian", "Smuggler"]
        s.g["winner"] = None
    t.do(lambda s: s._end_turn(), "end")
    assert s1.phase == "game_end" and s1.g["winner"] == A
    t.check("game_end")
    t.do(lambda s: s.tick(s.gen), "back to lobby")
    assert s1.phase == "lobby" and s1.state_for(B)["game"] is None


def test_no_secret_tokens_in_any_payload():
    """Human tokens are the only credential; they must never be serialized to anyone
    (including in the viewer's own state), nor bot tokens."""
    s = game(n=3, bots=2, seed=4)
    s.join(D, "Dave")                                     # mid-game non-participant
    secrets_ = [A, B, C, D] + [t for t in s.players if t.startswith("bot:")]
    for step in range(300):
        if s.phase != "playing":
            break
        for v in (A, B, C, D, None):
            blob = json.dumps(s.state_for(v))
            for tok in secrets_:
                assert tok not in blob, "token %r leaked to %r at step %d" % (tok, v, step)
        due = s.next_bot_action()
        if due:
            s.run_bot(due[1])
        else:
            s.tick(s.gen)


def test_log_lines_never_name_a_hidden_card():
    """Play many random games; every role named in a log line must be public info:
    a claim, a block claim, a revealed card, or a card proven then shuffled back."""
    for seed in range(20):
        s = game(n=3, seed=seed)
        rng = random.Random(seed)
        for _ in range(400):
            if s.phase != "playing":
                break
            p = s.g["pending"]
            tok = p.get("actor") if p["stage"] == "turn" else (p.get("waiting") or [None])[0]
            if tok is None:
                s.tick(s.gen)
                continue
            before = len(s.g["log"])
            if p["stage"] == "turn":
                acts = s.legal_actions(tok)
                a = rng.choice(acts)
                msg = {"t": "act", "action": a["action"]}
                if a["targets"]:
                    msg["target"] = rng.choice(a["targets"])
            elif p["stage"] in ("challenge", "block_challenge"):
                msg = {"t": "respond", "choice": rng.choice(["pass", "challenge"])}
            elif p["stage"] == "block":
                msg = {"t": "respond", "choice": "block", "role": rng.choice(p["block_roles"])} \
                    if rng.random() < .5 else {"t": "respond", "choice": "allow"}
            elif p["stage"] == "lose":
                msg = {"t": "lose", "card": rng.randrange(len(s.g["hand"][tok]))}
            else:
                n = len(s.g["hand"][tok])
                msg = {"t": "keep", "cards": rng.sample(range(n + len(s.g["exchange_draw"])), n)}
            hidden_before = {t: list(h) for t, h in s.g["hand"].items()}
            s.game_action(tok, msg)
            for line in s.g["log"][before:]:
                if any(k in line for k in ("claims", "blocks", "loses", "reveals", "cannot show",
                                            "challenges")):
                    continue                          # these name only public roles
                for r in ("Banker", "Agent", "Smuggler", "Broker", "Guardian"):
                    assert r not in line, "log names a role outside a public event: %r" % line
            del hidden_before


# ======================================================== authorization

def _all_verbs(s, target_pid):
    return [
        {"t": "act", "action": "income"}, {"t": "act", "action": "tax"},
        {"t": "act", "action": "coup", "target": target_pid},
        {"t": "act", "action": "steal", "target": target_pid},
        {"t": "respond", "choice": "pass"}, {"t": "respond", "choice": "challenge"},
        {"t": "respond", "choice": "allow"},
        {"t": "respond", "choice": "block", "role": "Banker"},
        {"t": "lose", "card": 0}, {"t": "keep", "cards": [0, 1]},
    ]


def _stages():
    """Yield sessions parked in every waiting stage (3 players)."""
    def mk():
        s = game(n=3)
        rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
        s.g["coins"][A] = 7
        return s
    s = mk(); yield "turn", s
    s = mk(); act(s, A, "tax"); yield "challenge", s
    s = mk(); act(s, A, "aid"); yield "block", s
    s = mk(); act(s, A, "aid"); s.game_action(B, {"t": "respond", "choice": "block", "role": "Banker"})
    yield "block_challenge", s
    s = mk(); act(s, A, "coup", B); yield "lose", s
    s = mk(); s.g["hand"][A] = ["Broker", "Agent"]; act(s, A, "exchange")
    s.tick(s.gen); yield "exchange", s


@pytest.mark.parametrize("who", ["spectator", "eliminated", "unknown", "bot_token", "none"])
def test_non_players_can_never_act(who):
    for name, s in _stages():
        if who == "spectator":
            s.join(D, "Dave"); tok = D
        elif who == "eliminated":
            # add a fourth seated player who is already out
            s.join(D, "Dave"); s.g["seats"].append(D)
            s.g["hand"][D] = []; s.g["revealed"][D] = ["Agent", "Agent"]; s.g["coins"][D] = 0
            tok = D
        elif who == "unknown":
            tok = "neverjoined1"
        elif who == "bot_token":
            tok = "bot:p9"
        else:
            tok = None
        before = core(s)
        for m in _all_verbs(s, s.players[C].pid):
            out = s.game_action(tok, m)
            assert out and out[0]["kind"] == "invalid" and out[0]["to"] == tok, (name, m)
        assert core(s) == before, "%s mutated game in stage %s" % (who, name)


def test_wrong_seat_wrong_stage_matrix():
    """In every stage, only the listed (token, verb) pairs may change state."""
    allowed = {
        "turn": {(A, "act")},
        "challenge": {(B, "respond"), (C, "respond")},
        "block": {(B, "respond"), (C, "respond")},
        "block_challenge": {(A, "respond"), (C, "respond")},
        "lose": {(B, "lose")},
        "exchange": {(A, "keep")},
    }
    for name, s0 in _stages():
        for tok in (A, B, C):
            for m in _all_verbs(s0, s0.players[C].pid):
                if (tok, m["t"]) in allowed[name]:
                    continue
                s = copy.deepcopy(s0)
                before = core(s)
                out = s.game_action(tok, m)
                assert out and out[0]["kind"] == "invalid", (name, tok, m)
                assert core(s) == before, (name, tok, m)


@pytest.mark.parametrize("target", ["self", "eliminated", "spectator", "unknown", "bot_dead",
                                    None, 1, ["p2"], {"pid": "p2"}, "", "p" * 33])
def test_bad_targets_rejected(target):
    s = game(n=1, bots=2)
    bots = [t for t in s.g["seats"] if t.startswith("bot:")]
    s.g["hand"][bots[1]] = []
    s.g["revealed"][bots[1]] = ["Agent", "Agent"]
    rig(s, A=["Banker", "Agent"])
    s.g["coins"][A] = 7
    s.join(D, "Dave")
    pid = {"self": s.players[A].pid, "eliminated": s.players[bots[1]].pid,
           "bot_dead": s.players[bots[1]].pid, "spectator": s.players[D].pid,
           "unknown": "p99"}.get(target, target) if isinstance(target, str) and target in \
        ("self", "eliminated", "spectator", "unknown", "bot_dead") else target
    for action in ("coup", "steal", "strike"):
        before = core(s)
        out = s.game_action(A, {"t": "act", "action": action, "target": pid})
        assert out and out[0]["kind"] == "invalid", (action, target)
        assert core(s) == before


def test_replay_after_stage_moved_on_is_rejected():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    act(s, A, "tax")
    s.game_action(B, {"t": "respond", "choice": "pass"})
    before = core(s)
    assert s.game_action(B, {"t": "respond", "choice": "pass"})[0]["kind"] == "invalid"
    assert s.game_action(B, {"t": "respond", "choice": "challenge"})[0]["kind"] == "invalid"
    assert core(s) == before
    s.game_action(C, {"t": "respond", "choice": "challenge"})     # true: C loses
    s.game_action(C, {"t": "lose", "card": 0})
    before = core(s)
    for m in ({"t": "lose", "card": 0}, {"t": "lose", "card": 1},
              {"t": "respond", "choice": "challenge"}):
        assert s.game_action(C, m)[0]["kind"] == "invalid"
    assert core(s) == before
    # A's turn is over; replaying the act is refused
    assert s.game_action(A, {"t": "act", "action": "tax"})[0]["kind"] == "invalid"
    assert core(s) == before
    # exchange keep replay
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "exchange"); s.tick(s.gen)
    s.game_action(A, {"t": "keep", "cards": [2, 3]})
    before = core(s)
    assert s.game_action(A, {"t": "keep", "cards": [0, 1]})[0]["kind"] == "invalid"
    assert core(s) == before


BAD_IDX = [-1, 2, 10**30, -10**30, 0.0, 1.5, True, False, "0", None, [0], {"i": 0}, float("nan")]


@pytest.mark.parametrize("idx", BAD_IDX, ids=repr)
def test_bad_lose_index(idx):
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.g["coins"][A] = 7
    act(s, A, "coup", B)
    before = core(s)
    assert s.game_action(B, {"t": "lose", "card": idx})[0]["kind"] == "invalid"
    assert core(s) == before


@pytest.mark.parametrize("keep", [[0], [0, 0], [0, 1, 2], [-1, 0], [0, 4], [0, 10**30],
                                  [True, 1], [0.0, 1], ["0", "1"], None, "01", {"0": 1},
                                  [[0], [1]], [None, 1]], ids=repr)
def test_bad_exchange_keep(keep):
    s = game(n=2)
    rig(s, A=["Broker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "exchange"); s.tick(s.gen)
    assert stage(s) == "exchange"
    before = core(s)
    assert s.game_action(A, {"t": "keep", "cards": keep})[0]["kind"] == "invalid"
    assert core(s) == before


@pytest.mark.parametrize("role", ["Guardian", "Agent", "banker", "BANKER", "", None, 1,
                                  ["Banker"], {"r": "Banker"}, "Banker" * 10, "__class__"],
                         ids=repr)
def test_block_with_invalid_role(role):
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    act(s, A, "aid")
    before = core(s)
    out = s.game_action(B, {"t": "respond", "choice": "block", "role": role})
    assert out[0]["kind"] == "invalid" and core(s) == before


def test_claimant_and_blocker_cannot_answer_their_own_claim():
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    act(s, A, "tax")
    before = core(s)
    for ch in ("pass", "challenge"):
        assert s.game_action(A, {"t": "respond", "choice": ch})[0]["kind"] == "invalid"
    assert core(s) == before
    s = game(n=3)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"], C=["Broker", "Broker"])
    act(s, A, "aid")
    s.game_action(B, {"t": "respond", "choice": "block", "role": "Banker"})
    before = core(s)
    for ch in ("pass", "challenge"):
        assert s.game_action(B, {"t": "respond", "choice": ch})[0]["kind"] == "invalid"
    assert core(s) == before


@pytest.mark.parametrize("msg", [
    {"t": ["act"]}, {"t": {"a": 1}}, {"t": None}, {"t": "act", "action": None},
    {"t": "act", "action": "x" * 5000}, {"t": "act", "action": {"__proto__": 1}},
    {"t": "respond", "choice": ["pass"]}, {"t": "respond", "choice": None},
    {"t": "lose"}, {"t": "keep"}, {"t": "state", "token": B}, {"t": "state_for", "viewer": B},
    {"t": "hello", "token": B}, {"t": "leave_table"},
], ids=repr)
def test_garbage_verbs_never_raise_or_mutate(msg):
    for name, s in _stages():
        before = core(s)
        for tok in (A, B, C):
            out = s.game_action(tok, msg)
            assert out and out[0]["kind"] == "invalid" and out[0]["to"] == tok
            assert "Traceback" not in json.dumps(out)
        assert core(s) == before, (name, msg)


def test_invalid_fx_only_goes_to_sender_and_carries_no_secrets():
    s = game(n=2)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    for m in _all_verbs(s, s.players[B].pid):
        for f in s.game_action(B, m):
            assert f["to"] == B
            blob = json.dumps(f)
            assert A not in blob and "Banker" not in blob and "Agent" not in blob


# ======================================================== names / injection

@pytest.mark.parametrize("raw", ['<img src=x onerror=alert(1)>', '"><script>x</script>',
                                 "a&amp;b", "`${alert(1)}`", "‮evil", "x\n\ny",
                                 "{{7*7}}", "%s%s%s", 12, None, ["x"]])
def test_names_are_sanitized(raw):
    n = clean_name(raw)
    assert all(ch not in n for ch in '<>&"`${}\n‮%')
    s = game(n=2)
    s.set_profile(B, raw)
    rig(s, A=["Banker", "Agent"], B=["Guardian", "Smuggler"])
    s.g["coins"][A] = 7
    act(s, A, "coup", B)
    for line in s.g["log"]:
        assert "<" not in line and ">" not in line.replace("→", "")


# ======================================================== known issues (xfail)

@pytest.mark.xfail(strict=True, reason="BUG P2: core/net.py dispatch 'again' lets ANY connected "
                   "token (incl. a mid-game non-participant) end the game_end results screen")
def test_non_participant_cannot_cut_results_screen():
    from core.net import GameBinding
    s = game(n=2)
    s.join(D, "Dave")                       # joined mid-game: a spectator-by-token
    s.g["hand"][B] = []
    s._end_turn()
    assert s.phase == "game_end"
    GameBinding("bluff", s).dispatch(D, {"t": "again"})
    assert s.phase == "game_end"


@pytest.mark.xfail(strict=True, reason="BUG P2: a player may take another seat's exact name or "
                   "the client's reserved 'You' label (games/bluff/web/client.js nameOf) "
                   "-> others see 'You claim ...' / '👑 You win!' for someone else")
def test_names_cannot_impersonate():
    s = game(n=3)
    s.set_profile(C, "Bob")
    s.set_profile(A, "You")
    names = [p.name for p in s.players.values()]
    assert len(set(names)) == len(names) and "You" not in names
