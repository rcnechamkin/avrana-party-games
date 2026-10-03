"""EXPO rules-contract tests (AVR-215): traceability gaps and pinned defects.

games/expo/docs/IMPLEMENTATION_PLAN.md maps every canonical rule to tests. The rules below had no
direct test before the reconciliation; each test names the rule (R..), matrix row (T..) or
reconciliation entry (E..) it proves. Nothing here changes behaviour.

Tests marked xfail(strict=True) pin confirmed implementation defects recorded in
games/expo/docs/RECONCILIATION.md. They assert the *intended* behaviour, fail today, and will
break the suite the moment the defect is fixed, so the fix must remove the marker and update the
reconciliation entry. They are not permission to treat the current behaviour as correct.
"""
import json
import random

import pytest

from games.expo import content
from games.expo.content import TASKS, catalog
from games.expo.engine import Engine, Invalid
from games.expo.game import ExpoSession
from games.expo.rules import DECK, assertions, legal_cards, rank, suit
from games.expo.tasks import evaluate

from test_expo import act, allocated, command, decide, playing, session, task_state

DEFECT = dict(strict=True, raises=(AssertionError, Invalid))


def play_trick(e):
    """Play one complete trick with the first legal card of every seat; return its record."""
    for _ in e.s['seats']:
        q = e.s['turn']
        act(e, e.controller(q), 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
    return e.s['history'][-1]


def trick(index, winner, cards, leader=None, seats=('a', 'b', 'c')):
    order = list(seats)
    return {'index': index, 'leader': leader or winner, 'winner': winner,
            'plays': [{'seat': order[i % len(order)], 'card': c} for i, c in enumerate(cards)]}


def history_state(tricks, planned=13, seats=('a', 'b', 'c'), captain='b', current=()):
    return {'seats': list(seats), 'captain': captain, 'history': list(tricks), 'planned': planned,
            'trick': list(current)}


# ---- R02 captain and order (T03) ---------------------------------------------------------------

@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_captain_opens_the_first_trick_and_each_winner_opens_the_next(n):
    for seed in range(8):
        e = playing(n, seed)
        if e.s['result']:
            continue
        assert e.s['leader'] == e.s['turn'] == e.s['captain'] and not e.s['history']
        first = play_trick(e)
        assert first['leader'] == e.s['captain']
        order = e.s['seats'][e.s['seats'].index(first['leader']):] + e.s['seats'][:e.s['seats'].index(first['leader'])]
        assert [p['seat'] for p in first['plays']] == order           # clockwise, one card each
        if not e.s['result']:
            assert e.s['leader'] == e.s['turn'] == first['winner']


# ---- R05 communication (T08, T09, T10) ---------------------------------------------------------

def test_an_exposed_card_stays_in_hand_follows_suit_and_its_token_is_never_restored():
    e = playing()
    actor = e.s['captain']
    card, opts = next(iter(e.communication_options(actor).items()))
    act(e, actor, 'communicate', card=card, assertion=opts[0])
    assert card in e.s['hands'][actor] and card in legal_cards(e.playable(actor), [])
    act(e, actor, 'play_card', card=card)                           # the captain leads it
    assert [x['active'] for x in e.s['exposures']] == [False]
    assert e.view(e.s['humans'][0])['exposures'] == []              # the reminder is gone
    assert actor in e.s['spent'] and not e.communication_options(actor)


def test_communication_is_refused_before_the_crew_begins_and_for_non_crew():
    e = allocated(Engine(['a', 'b', 'c'], random.Random(4)))
    assert e.s['phase'] == 'assistance' and e.communication_options('a') == {}
    with pytest.raises(Invalid):
        act(e, 'a', 'communicate', card=e.playable('a')[0], assertion='highest')
    e = playing()
    assert e.communication_options('nobody') == {} and e.communication_options('tonoja') == {}
    sub = next((c for c in e.playable('p0') if suit(c) == 'submarine'), None)
    if sub:
        assert sub not in e.communication_options('p0')


def test_sonar_is_available_again_on_the_next_attempt():
    e = playing()
    card, opts = next(iter(e.communication_options('p0').items()))
    act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    e._finish('failed', 'fixture')
    decide(e, 'p0', 'retry', keep=True)
    assert e.s['spent'] == [] and e.s['exposures'] == []


# ---- R05 unfamiliar terrain (T11) --------------------------------------------------------------

def test_terrain_card_maps_to_the_communication_mode_and_returns_to_the_deck():
    seen = set()
    for seed in range(60):
        e = Engine(['a', 'b', 'c'], random.Random(seed), 24)
        t = e.s['terrain']
        assert suit(t) != 'submarine'
        assert e.s['communication'] == ['normal', 'currents', 'rapture'][(rank(t) - 1) // 3]
        seen.add(e.s['communication'])
        e.check()                                                    # all 40 cards still dealt
    assert seen == {'normal', 'currents', 'rapture'}
    assert Engine(['a', 'b', 'c'], random.Random(1), 9).s['terrain'] is None


# ---- R08 feasibility: submarine deal exceptions (T25) ------------------------------------------

@pytest.mark.parametrize('task,held,expected', [
    ('black1', ['submarine:1', 'submarine:4'], True),
    ('black1', ['submarine:1', 'submarine:2', 'submarine:3'], True),
    ('black1', ['submarine:1', 'submarine:2'], False),
    ('black2', ['submarine:2', 'submarine:4'], True),
    ('1black', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4'], True),
    ('2black', ['submarine:2', 'submarine:3', 'submarine:4'], True),
    ('2black', ['submarine:1', 'submarine:2', 'submarine:3'], False),
    ('3black', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4'], True),
    ('red7WithBlack', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4', 'pink:7'], True),
    ('red7WithBlack', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4'], False),
    ('green9WithBlack', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4', 'green:9'], True),
    ('blue4', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4'], False),
])
def test_named_submarine_alignments_are_deal_exceptions(task, held, expected):
    e = Engine(['a', 'b', 'c'], random.Random(4))
    rest = [c for c in DECK if c not in held]
    e.s['hands'] = {'a': held + rest[:13 - len(held) + 1], 'b': [], 'c': []}
    assert e._deal_exception([task]) is expected


def test_a_deal_exception_is_redealt_before_the_attempt_is_counted():
    for seed in range(40):
        e = Engine(['a', 'b', 'c'], random.Random(seed))
        e.prepare(1, keep=['black1', '2black'])
        assert not e._deal_exception(e.s['pool'])
        assert e.s['attempts'] == 0 and not e.s['counted']


# ---- R07 task monitors (T15, T18, T22, T23, T24) -----------------------------------------------

def test_a_named_card_captured_by_someone_else_fails_at_once():
    s = history_state([trick(1, 'b', ['blue:4', 'blue:9', 'green:1'])])
    assert evaluate(TASKS['blue4'], 'a', s) == 'failed'
    s = history_state([trick(1, 'a', ['yellow:9', 'yellow:2', 'green:1'])])
    assert evaluate(TASKS['yellow9+blue7'], 'a', s) == 'pending'      # half done, not yet complete
    s['history'].append(trick(2, 'a', ['blue:7', 'blue:2', 'green:2']))
    assert evaluate(TASKS['yellow9+blue7'], 'a', s) == 'satisfied'


def test_win_with_uses_the_owners_own_winning_card():
    # 'a' wins with pink 9; the color 2 in the trick was played by someone else.
    s = history_state([trick(1, 'a', ['pink:9', 'pink:2', 'pink:3'], leader='a')], planned=1)
    assert evaluate(TASKS['trickWith2'], 'a', s) == 'failed'
    s = history_state([trick(1, 'a', ['submarine:1', 'pink:7', 'pink:3'], leader='a')])
    assert evaluate(TASKS['red7WithBlack'], 'a', s) == 'satisfied'
    s = history_state([trick(1, 'b', ['pink:1', 'pink:7', 'pink:3'], leader='a')])
    assert evaluate(TASKS['red7WithBlack'], 'a', s) == 'failed'      # the 7 is gone


def test_exact_streak_fails_once_the_wins_are_split_and_at_least_streak_allows_more():
    wins = lambda *w: history_state([trick(i + 1, q, ['blue:2', 'green:4', 'yellow:6']) for i, q in enumerate(w)])
    assert evaluate(TASKS['exactly2trickInARow'], 'a', wins('a', 'b', 'a')) == 'failed'
    assert evaluate(TASKS['exactly2trickInARow'], 'a', wins('a', 'a', 'a')) == 'failed'
    assert evaluate(TASKS['exactly2trickInARow'], 'a', wins('a', 'a', 'b')) == 'pending'
    assert evaluate(TASKS['2tricksInARow'], 'a', wins('a', 'a', 'a')) == 'satisfied'   # more is fine


def test_equal_counts_need_at_least_one_of_each_and_never_lead_fails_on_the_lead_itself():
    none = history_state([trick(i + 1, 'a', ['blue:2', 'green:4', 'blue:6']) for i in range(13)])
    assert evaluate(TASKS['equalRedYellow'], 'a', none) == 'failed'  # 0 = 0 does not count
    s = history_state([], current=[{'seat': 'a', 'card': 'pink:3'}])
    assert evaluate(TASKS['noLeadRedGreen'], 'a', s) == 'failed'
    assert evaluate(TASKS['noLeadRedGreen'], 'b', s) == 'pending'


# ---- mission modifiers (T28, T30, T31, T35) ----------------------------------------------------

def test_rank_balance_allows_a_difference_of_one_and_ignores_submarine_one():
    e = playing(mid=21)
    e.s['history'] = [{'index': 1, 'leader': 'p0', 'winner': 'p0', 'plays': [
        {'seat': 'p0', 'card': 'blue:1'}, {'seat': 'p1', 'card': 'submarine:1'}, {'seat': 'p2', 'card': 'pink:5'}]}]
    e._outcome()
    assert e.s['result'] is None
    e.s['history'].append({'index': 2, 'leader': 'p0', 'winner': 'p0', 'plays': [
        {'seat': 'p0', 'card': 'green:1'}, {'seat': 'p1', 'card': 'green:3'}, {'seat': 'p2', 'card': 'green:5'}]})
    e._outcome()
    assert e.s['result']['status'] == 'failed'


def test_yellow_five_as_the_last_card_of_the_last_trick_succeeds():
    e = Engine(['p0', 'p1', 'p2'], random.Random(4), 27)
    decide(e, 'p0', 'begin')
    filler = {'index': 0, 'leader': 'p0', 'winner': 'p0', 'plays': [{'seat': 'p0', 'card': 'blue:1'}]}
    e.s['history'] = [dict(filler, index=i + 1) for i in range(12)] + [{'index': 13, 'leader': 'p0', 'winner': 'p0', 'plays': [
        {'seat': 'p0', 'card': 'blue:9'}, {'seat': 'p1', 'card': 'blue:8'}, {'seat': 'p2', 'card': 'yellow:5'}]}]
    e._outcome()
    assert e.s['result']['status'] == 'success'


def test_only_the_captain_may_offer_the_tasks_in_missions_ten_and_thirteen():
    e = Engine(['a', 'b', 'c'], random.Random(9), 13)
    other = next(q for q in e.s['humans'] if q != e.s['captain'])
    e.s['pool'] = ['blue4']; e.s['selected'] = ['blue4']
    with pytest.raises(Invalid):
        act(e, other, 'propose', proposal={'kind': 'assign', 'owner': other, 'task': 'all'})
    decide(e, e.s['captain'], 'assign', owner=e.s['captain'], task='all')
    assert not e.s['before_first_only'] and set(e.s['assignments'].values()) == {e.s['captain']}


@pytest.mark.parametrize('mid', [6, 17])
def test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain(mid):
    e = Engine(['a', 'b', 'c'], random.Random(9), mid)
    e.s['pool'] = ['moreTricksThanCaptain']; e.s['selected'] = list(e.s['pool'])
    cap = e.s['captain']
    task = 'all' if mid == 6 else 'moreTricksThanCaptain'
    with pytest.raises(Invalid):
        act(e, 'a', 'propose', proposal={'kind': 'assign', 'owner': cap, 'task': task})
    other = next(q for q in e.s['humans'] if q != cap)
    decide(e, 'a', 'assign', owner=other, task=task)
    assert e.s['assignments'] == {'moreTricksThanCaptain': other}


def test_distress_surcharge_is_logged_once_and_a_new_mission_clears_it():
    e = allocated(Engine(['a', 'b', 'c'], random.Random(4)))
    decide(e, 'a', 'distress', direction='right')
    with pytest.raises(Invalid):
        act(e, 'a', 'pass_card', card='submarine:1' if 'submarine:1' in e.s['hands']['a'] else 'nonsense')
    for q in e.s['humans']:
        act(e, q, 'pass_card', card=next(c for c in e.playable(q) if suit(c) != 'submarine'))
    e._finish('failed', 'fixture')
    decide(e, 'a', 'retry', keep=False)
    e = allocated(e)
    decide(e, 'a', 'begin')                                         # second attempt, no exchange
    assert e.s['distress'] and e.s['attempts'] == 2
    e._finish('success', 'fixture')
    assert e.s['log'][-1]['attempts'] == 3 and e.s['log'][-1]['distress'] is True
    decide(e, 'a', 'next', mission=2)
    assert e.s['distress'] is False and e.s['attempts'] == 0 and e.s['mission']['id'] == 2


# ---- R10 two humans with Tonoja (T34) and conflict C11 -----------------------------------------

def test_tonoja_only_ever_offers_face_up_cards_and_follows_suit_from_them():
    e = playing(n=2)
    tops = [c['top'] for c in e.s['columns']]
    covered = [c['covered'] for c in e.s['columns']]
    assert e.playable('tonoja') == tops and not set(e.playable('tonoja')) & set(covered)
    led = next(s for s in ('blue', 'green', 'pink', 'yellow', 'submarine') if all(suit(c) != s for c in tops))
    assert legal_cards(e.playable('tonoja'), [{'seat': 'x', 'card': led + ':1'}]) == tops


def test_two_humans_cannot_use_distress_or_shared_sonar_or_volunteer_missions():
    e = allocated(Engine(['a', 'b'], random.Random(4)))
    with pytest.raises(Invalid):
        act(e, 'a', 'propose', proposal={'kind': 'distress', 'direction': 'left'})
    for mid in (11, 16, 21, 24, 27):
        with pytest.raises(Invalid):
            Engine(['a', 'b'], random.Random(1), mid)
    off = {m['id'] for m in catalog(2) if not m['enabled']}
    assert {11, 16, 21, 22, 23, 24, 25, 27} <= off and 8 not in off and 9 not in off


# ---- restoration, clock and persistence (T32, T39, T40) ----------------------------------------

def test_a_timed_mission_expires_while_a_player_is_away():
    e = playing()
    e.s['expiry'] = 200
    e.s['away'] = ['p1']
    assert not e.observe_time(199) and e.s['result'] is None
    assert e.observe_time(200) and e.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}


def test_a_snapshot_from_other_content_or_rules_is_refused():
    snap = json.loads(json.dumps(playing().snapshot()))
    for key, value in (('content', '0' * 64), ('version', 2)):
        bad = json.loads(json.dumps(snap))
        bad['state'][key] = value
        with pytest.raises(Invalid):
            Engine.restore(bad)
    assert Engine.restore(snap).s['content'] == content.CONTENT_HASH


def test_a_rejected_request_is_not_remembered_and_an_accepted_one_is():
    e = playing()
    turn = e.s['turn']
    wrong = next(p for p in e.s['humans'] if p != turn)
    msg = command(e, wrong, 'play_card', card=e.playable(wrong)[0])
    remembered = dict(e.s['dedup'])
    with pytest.raises(Invalid):
        e.apply(wrong, msg, 100)
    assert e.s['dedup'] == remembered                               # the rejection left no record
    ok = command(e, turn, 'play_card', card=e.playable(turn)[0])
    assert e.apply(turn, ok, 100) and len(e.s['dedup']) == len(remembered) + 1
    assert not e.apply(turn, ok, 100)                               # the duplicate is a no-op


def test_a_party_round_locks_settings_so_the_table_opens_on_mission_one():
    s = ExpoSession(random.Random(3))
    s.party_start([('t1', 'Alice'), ('t2', 'Bob'), ('t3', 'Cara')])
    s.set_settings('t1', {'mission': 5, 'timed': True})
    assert s.settings == {'mission': 1, 'timed': False, 'tonoja_position': 2}
    s.tick(s.gen)
    assert s.engine.s['mission']['id'] == 1 and s.engine.s['timed'] is False


# ---- C20 / AVR-239: the captain and captain comparison tasks (was defect E-D1) -------------------
# Owner decision 2026-10-04: an unavoidable draw is repaired before selection by replacing the most
# recently revealed comparison task with another of equal difficulty, and no attempt is counted
# (rulebook p14); a comparison task the crew leaves for the captain is an avoidable mistake and
# ends the attempt as a counted failure (rulebook p13). The captain never passes a task onward.

COMPARISON = ['lessTricksThanCaptain', 'equalTricksThanCaptain', 'moreTricksThanCaptain']


def drawn(humans, mission_id, first, seed=1):
    """A table whose task deck is in a known order, prepared through the real draw and repair."""
    e = Engine(list(humans), random.Random(seed))
    e.s['deck'] = list(first) + [k for k, d in TASKS.items() if d['enabled'] and k not in first]
    e.s['used'] = []
    e.prepare(mission_id)
    return e


def crew_difficulty(e, tasks):
    return sum(TASKS[k]['difficulty'][str(len(e.s['seats']))] for k in tasks)


def comparison(tasks):
    return [k for k in tasks if TASKS[k]['params'].get('other') == 'captain']


def test_defect_unavoidable_captain_comparison_draw_does_not_stall_selection():
    e = drawn(['p0', 'p1', 'p2'], 11, COMPARISON)                     # target 8 = 2 + 4 + 2 at three seats
    pool = list(e.s['pool'])
    cap = e.s['captain']
    assert e.selector() == cap and e.s['phase'] == 'allocation'
    progressed = False
    for t, extra in [('pass_task', {})] + [('choose_task', {'task': k}) for k in pool]:
        try:
            act(e, cap, t, **extra)
            progressed = True
            break
        except Invalid:
            pass
    assert progressed, 'the captain can neither pick nor pass'
    assert e.s['phase'] == 'allocation' and e.s['result'] is None


@pytest.mark.parametrize('humans,mission_id,first', [
    (['p0', 'p1', 'p2'], 11, COMPARISON),                             # three tasks, three seats
    (['p0', 'p1', 'p2'], 18, COMPARISON + ['green6']),                # four tasks: the captain picks twice
    (['p0', 'p1'], 18, COMPARISON + ['green6']),                      # two humans and Tonoja are three seats
])
def test_an_unavoidable_comparison_draw_replaces_the_most_recently_revealed_task(humans, mission_id, first):
    e = drawn(humans, mission_id, first)
    pool = e.s['pool']
    # Only the last comparison task in reveal order was exchanged, in place.
    assert pool[:2] == COMPARISON[:2] and pool[3:] == first[3:]
    replacement = pool[2]
    assert replacement not in COMPARISON and comparison(pool) == COMPARISON[:2]
    crew = str(len(e.s['seats']))
    assert TASKS[replacement]['difficulty'][crew] == TASKS['moreTricksThanCaptain']['difficulty'][crew]
    assert crew_difficulty(e, pool) == e.s['mission']['target']        # the challenge is unchanged
    # Deck bookkeeping: the exchanged task is back in the deck; nothing is duplicated or lost.
    assert 'moreTricksThanCaptain' in e.s['deck'] and replacement not in e.s['deck']
    everything = e.s['deck'] + e.s['used'] + pool
    assert len(everything) == len(set(everything)) == sum(d['enabled'] for d in TASKS.values())
    # A setup correction, not an attempt.
    assert e.s['attempts'] == 0 and not e.s['counted'] and e.s['result'] is None and e.s['selected'] == pool
    e.check()
    # The captain can now always be given an ordinary task.
    assert any(e.eligible(k, e.s['captain']) for k in pool)


def test_the_comparison_repair_is_deterministic_and_survives_a_snapshot():
    a = drawn(['p0', 'p1', 'p2'], 11, COMPARISON, seed=7)
    b = drawn(['p0', 'p1', 'p2'], 11, COMPARISON, seed=7)
    assert a.snapshot() == b.snapshot()
    restored = Engine.restore(json.loads(json.dumps(a.snapshot())))
    assert restored.s['pool'] == a.s['pool'] and restored.s['deck'] == a.s['deck']
    e = drawn(['p0', 'p1', 'p2'], 11, COMPARISON, seed=7)
    e._finish('failed', 'fixture')
    kept = list(e.s['selected'])
    decide(e, 'p0', 'retry', keep=True)                               # kept tasks need no second repair
    assert e.s['pool'] == kept


@pytest.mark.parametrize('humans,mission_id,first,reason', [
    (['p0', 'p1', 'p2'], 22, COMPARISON + ['green6', 'yellow1', 'red3'], 'six tasks: three ordinary ones cover the two captain picks'),
    (['p0', 'p1', 'p2', 'p3'], 9, COMPARISON, 'fewer tasks than seats: the captain may pass'),
    (['p0', 'p1', 'p2', 'p3'], 11, COMPARISON + ['green6'], 'four seats, four tasks: one ordinary task for the captain'),
    (['p0', 'p1', 'p2', 'p3', 'p4'], 11, COMPARISON, 'fewer tasks than seats'),
])
def test_an_avoidable_comparison_draw_is_left_alone(humans, mission_id, first, reason):
    e = drawn(humans, mission_id, first)
    assert e.s['pool'] == first, reason
    assert crew_difficulty(e, first) == e.s['mission']['target']


def test_the_comparison_repair_applies_only_to_clockwise_selection_that_includes_the_captain():
    e = Engine(['p0', 'p1', 'p2'], random.Random(1))
    for allocation in ('skip_captain', 'free', 'one', 'captain_one', 'volunteer'):
        assert e._captain_conflict(list(COMPARISON), {'allocation': allocation}) is None
    assert e._captain_conflict(list(COMPARISON), {'allocation': 'normal'}) == 'moreTricksThanCaptain'
    assert e._captain_conflict(['blue4'] + COMPARISON[:2], {'allocation': 'normal'}) is None


def test_defect_captain_left_with_a_comparison_task_ends_the_attempt_instead_of_stalling():
    e = Engine(['p0', 'p1', 'p2', 'p3'], random.Random(2), 1)
    pool = ['green6', 'yellow1', 'red3', 'blue4', 'lessTricksThanCaptain']
    e.s.update(pool=list(pool), selected=list(pool), initial_count=5, assignments={}, progress={}, pick_index=0)
    for k in pool[:4]:
        act(e, e.selector(), 'choose_task', task=k)
    assert e.selector() == e.s['captain']
    with pytest.raises(Invalid):
        act(e, e.s['captain'], 'choose_task', task=pool[4])
    assert e.s['phase'] != 'allocation', 'selection is stuck with one unassignable task'


def misplayed(humans=('p0', 'p1', 'p2', 'p3'), seed=2):
    """The crew takes every ordinary task and leaves a comparison task for the captain."""
    e = Engine(list(humans), random.Random(seed), 1)
    ordinary = ['green6', 'yellow1', 'red3', 'blue4', 'black3']
    pool = ordinary[:len(e.s['seats'])] + ['lessTricksThanCaptain']
    e.s.update(pool=list(pool), selected=list(pool), initial_count=len(pool), assignments={}, progress={}, pick_index=0)
    assert e._captain_conflict(pool, e.s['mission']) is None           # the crew could have avoided it
    for k in pool[:-1]:
        assert e.s['result'] is None
        act(e, e.controller(e.selector()), 'choose_task', task=k)
    return e, pool


@pytest.mark.parametrize('humans', [('p0', 'p1', 'p2'), ('p0', 'p1', 'p2', 'p3'), ('p0', 'p1', 'p2', 'p3', 'p4'), ('p0', 'p1')])
def test_a_comparison_task_left_for_the_captain_is_a_counted_failure_with_a_reason(humans):
    e, pool = misplayed(humans)
    assert e.s['phase'] == 'mission_result'
    assert e.s['result']['status'] == 'failed' and 'captain' in e.s['result']['reason'].lower()
    assert e.s['attempts'] == 1 and e.s['counted']                    # counted once
    assert e.s['pool'] == ['lessTricksThanCaptain']                   # nobody was given it
    assert 'lessTricksThanCaptain' not in e.s['assignments']
    assert e.s['history'] == [] and e.s['trick'] == []                # no card was played
    e.check()
    viewer = e.s['humans'][0]
    assert e.view(viewer)['result'] == e.view(None)['result'] == e.s['result']
    before = e.snapshot()
    for t, extra in (('pass_task', {}), ('choose_task', {'task': 'lessTricksThanCaptain'})):
        with pytest.raises(Invalid):
            act(e, e.s['captain'], t, **extra)                        # no passing the task onward
    assert e.snapshot() == before


def test_the_crew_can_retry_after_the_counted_failure_and_assign_the_task_correctly():
    e, pool = misplayed()
    decide(e, e.s['humans'][0], 'retry', keep=True)
    assert e.s['phase'] == 'allocation' and e.s['pool'] == pool
    assert e.s['attempts'] == 1 and not e.s['counted'] and e.s['result'] is None
    cap = e.s['captain']
    while e.s['pool']:
        seat = e.selector()
        if seat != cap and 'lessTricksThanCaptain' in e.s['pool']:
            k = 'lessTricksThanCaptain'                               # another seat takes it this time
        else:
            k = next(k for k in e.s['pool'] if e.eligible(k, seat))
        act(e, e.controller(seat), 'choose_task', task=k)
    assert e.s['result'] is None and e.s['assignments']['lessTricksThanCaptain'] != cap
    decide(e, e.s['humans'][0], 'begin')
    assert e.s['attempts'] == 2 and e.s['phase'] == 'before_trick'


def test_selection_never_fails_while_the_next_seat_can_take_or_pass():
    # Ordinary selection, and a pass that is still allowed, never trip the counted failure.
    for seed in range(25):
        for n in (3, 4, 5):
            e = allocated(Engine([f'p{i}' for i in range(n)], random.Random(seed), 7))
            assert e.s['result'] is None and e.s['attempts'] == 0
    e = Engine(['a', 'b', 'c'], random.Random(4))
    e.s['pool'] = ['moreTricksThanCaptain']
    e.s['selected'] = ['moreTricksThanCaptain']
    e.s['initial_count'] = 1
    act(e, e.s['captain'], 'pass_task')                               # fewer tasks than seats: a legal pass
    assert e.s['result'] is None and e.s['phase'] == 'allocation'


# ---- pinned defect (games/expo/docs/RECONCILIATION.md) -----------------------------------------

@pytest.mark.xfail(reason='E-D2 / AVR-240: no decision, including End table, is accepted while a seat is away', **DEFECT)
def test_defect_a_table_can_be_ended_while_a_seated_player_is_away():
    s, tokens = session()
    s.leave(tokens[2])
    for t in tokens[:2]:
        pid = s.players[t].pid
        s.game_action(t, command(s.engine, pid, 'propose' if t == tokens[0] else 'confirm',
                                 **({'proposal': {'kind': 'end'}} if t == tokens[0] else {'yes': True})))
    assert s.phase == 'game_end'


# ---- AVR-241: window tasks complete when their window closes (was defect E-D3) -------------------
# Rulebook p10: a task is complete when its condition is met and it can no longer fail. Only the
# three "win none of the first N tricks" tasks are completed early by this rule; every other
# reversible task still waits for the end of the deal.

WINDOW = {'noneFirst3Tricks': 3, 'noneFirst4Tricks': 4, 'noneFirst5Tricks': 5}


def test_defect_none_of_the_first_three_tricks_completes_after_trick_three():
    s = task_state(['b', 'b', 'c'])
    assert evaluate(TASKS['noneFirst3Tricks'], 'a', s) == 'satisfied'


@pytest.mark.parametrize('key,size', sorted(WINDOW.items()))
def test_a_window_task_is_pending_inside_its_window_and_satisfied_when_it_closes(key, size):
    assert evaluate(TASKS[key], 'a', task_state([])) == 'pending'
    assert evaluate(TASKS[key], 'a', task_state(['b'] * (size - 1))) == 'pending'
    assert evaluate(TASKS[key], 'a', task_state(['b'] * size)) == 'satisfied'
    # Winning afterwards does not matter; winning inside the window fails at that trick.
    assert evaluate(TASKS[key], 'a', task_state(['b'] * size + ['a', 'a'])) == 'satisfied'
    for at in range(size):
        wins = ['b'] * at + ['a']
        assert evaluate(TASKS[key], 'a', task_state(wins)) == 'failed'
    assert evaluate(TASKS[key], 'a', task_state(['b'] * 13)) == 'satisfied'


def test_only_the_three_window_tasks_complete_early_for_a_seat_that_wins_nothing():
    # A seat that has won no trick has met no positive condition. After five tricks the only
    # tasks that may already be complete are the window tasks: early completion was not
    # generalised to any other reversible task (exclusions, exact totals, comparisons, ...).
    s = task_state(['b', 'c', 'b', 'c', 'b'])
    early = {k for k, d in TASKS.items() if d['enabled'] and evaluate(d, 'a', s, 0) == 'satisfied'}
    assert early == set(WINDOW)
    for key in ('no9', 'noRed', '0tricks', 'onlyLastTrick', 'neverTwoTricksInARow', 'lessTricksThanOthers'):
        assert evaluate(TASKS[key], 'a', s) == 'pending', key


def with_single_task(e, key, owner):
    e.s.update(pool=[], selected=[key], assignments={key: owner}, progress={key: 'pending'})
    e.check()
    return e


def play_tricks(e, count, now=100):
    for _ in range(count * len(e.s['seats'])):
        if e.s['result']:
            return
        q = e.s['turn']
        act(e, e.controller(q), 'play_card', now=now, card=legal_cards(e.playable(q), e.s['trick'])[0])


@pytest.mark.parametrize('key,size', sorted(WINDOW.items()))
def test_closing_the_window_on_the_last_open_task_wins_the_mission_at_once(key, size):
    succeeded = failed = 0
    for seed in range(30):
        for owner in ('p0', 'p1', 'p2'):
            e = with_single_task(playing(3, seed), key, owner)
            play_tricks(e, size)
            wins = [h['winner'] for h in e.s['history']]
            if owner in wins:
                # the owner won inside the window: the mission failed on that very trick
                assert e.s['result']['status'] == 'failed' and wins.index(owner) == len(wins) - 1
                failed += 1
            else:
                assert len(wins) == size and e.s['progress'][key] == 'satisfied'
                assert e.s['result'] == {'status': 'success', 'reason': 'All mission objectives completed.'}
                assert e.s['phase'] == 'mission_result' and size < e.s['planned']
                assert e.s['log'][-1]['mission'] == e.s['mission']['id']
                succeeded += 1
            e.check()
    assert succeeded and failed                        # both paths were exercised


def test_a_window_task_does_not_finish_the_mission_while_another_task_is_open():
    for seed in range(30):
        e = playing(3, seed)
        e.s.update(pool=[], selected=['noneFirst3Tricks', '0tricks'],
                   assignments={'noneFirst3Tricks': 'p1', '0tricks': 'p1'},
                   progress={'noneFirst3Tricks': 'pending', '0tricks': 'pending'})
        play_tricks(e, 3)
        if 'p1' not in [h['winner'] for h in e.s['history']]:
            assert e.s['progress'] == {'noneFirst3Tricks': 'satisfied', '0tricks': 'pending'}
            assert e.s['result'] is None
            return
    pytest.fail('fixture must contain a seat that wins none of the first three tricks')


def timed_window_table(seed):
    """Mission 16 with its real-time limit: the volunteer owns noneFirst3Tricks; clock from 100."""
    e = Engine(['p0', 'p1', 'p2'], random.Random(seed), 16, timed=True)
    e.s['pool'] = ['noneFirst3Tricks']
    e.s['selected'] = ['noneFirst3Tricks']
    volunteer = e.selector()
    act(e, volunteer, 'volunteer', yes=True)
    decide(e, 'p0', 'begin')                           # act() supplies now=100
    assert e.s['expiry'] == 100 + 150 and e.s['assignments'] == {'noneFirst3Tricks': volunteer}
    return e, volunteer


def test_a_timed_mission_completed_by_a_window_task_cannot_time_out_afterwards():
    for seed in range(40):
        e, volunteer = timed_window_table(seed)
        play_tricks(e, 3, now=200)                     # well inside the 150 seconds
        if volunteer in [h['winner'] for h in e.s['history']]:
            continue
        assert e.s['result']['status'] == 'success' and e.s['expiry'] is None
        done = e.snapshot()
        assert not e.observe_time(250) and not e.observe_time(10_000)   # the old deadline passes
        assert e.snapshot() == done
        # A late command cannot turn the success into a timeout either.
        with pytest.raises(Invalid):
            act(e, e.s['turn'], 'play_card', now=10_000, card=e.playable(e.s['turn'])[0])
        assert e.s['result']['status'] == 'success'
        return
    pytest.fail('fixture must contain a volunteer who wins none of the first three tricks')


def test_a_timed_mission_still_times_out_while_the_window_is_open():
    e, volunteer = timed_window_table(0)
    play_tricks(e, 2, now=200)
    assert e.s['result'] is None and volunteer not in [h['winner'] for h in e.s['history']]
    assert e.s['progress']['noneFirst3Tricks'] == 'pending'            # the window is still open
    assert e.observe_time(250)
    assert e.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}


# ---- AVR-241: currents shows a declaration to its author only (was defect E-D4) -----------------

def test_defect_currents_shows_the_communicator_their_own_assertion():
    e = playing(mid=9)
    card, opts = next(iter(e.communication_options('p0').items()))
    act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    assert 'assertion' not in e.view('p1')['exposures'][0]
    assert e.view('p0')['exposures'][0].get('assertion') == opts[0]


@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_currents_hides_a_declaration_from_every_viewer_but_its_author(n):
    e = playing(n, seed=3, mid=9)
    assert e.s['communication'] == 'currents'
    made = {}
    for author in e.s['humans'][:2]:                   # two players communicate at the same boundary
        card, opts = next(iter(e.communication_options(author).items()))
        act(e, author, 'communicate', card=card, assertion=opts[-1])
        made[author] = (card, opts[-1])
    viewers = list(e.s['humans']) + [None, 'stranger', 'tonoja']
    for viewer in viewers:
        shown = e.view(viewer)['exposures']
        assert [(x['seat'], x['card']) for x in shown] == [(a, c) for a, (c, _) in made.items()]
        for x in shown:
            if viewer == x['seat']:
                assert x['assertion'] == made[viewer][1]       # the author, and only the author
            else:
                assert 'assertion' not in x
        # Nothing else in a viewer's payload carries another player's declaration.
        others = {m for a, (_, m) in made.items() if a != viewer}
        mine = made.get(viewer, (None, None))[1]
        text = json.dumps(shown)
        assert all(m == mine or ('"' + m + '"') not in text for m in others)
    # The author still sees it after a reload or a server restart: the view is rebuilt from state.
    restored = Engine.restore(json.loads(json.dumps(e.snapshot())))
    for author, (_, meaning) in made.items():
        own = next(x for x in restored.view(author)['exposures'] if x['seat'] == author)
        assert own['assertion'] == meaning


def test_normal_communication_still_shows_the_declaration_to_everyone():
    e = playing()
    card, opts = next(iter(e.communication_options('p0').items()))
    act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    for viewer in ('p0', 'p1', 'p2', None):
        assert e.view(viewer)['exposures'][0]['assertion'] == opts[0]


def test_a_watcher_and_another_player_never_get_a_currents_declaration_through_the_session():
    s, tokens = session()
    e = s.engine
    e.s['communication'] = 'currents'
    allocated(e)
    decide(e, e.s['humans'][0], 'begin')
    author = e.s['humans'][0]
    card, opts = next(iter(e.communication_options(author).items()))
    act(e, author, 'communicate', card=card, assertion=opts[0])
    by_pid = {s.players[t].pid: t for t in tokens}
    s.join('watcher', 'Observer')
    assert s.game_state(by_pid[author])['exposures'][0]['assertion'] == opts[0]
    for token in [t for pid, t in by_pid.items() if pid != author] + ['watcher', None]:
        assert 'assertion' not in s.game_state(token)['exposures'][0]
    assert 'assertion' not in s.game_state_spectator()['exposures'][0]      # Party spectators


# ---- AVR-248: a single card of a color is communicated only as "only" (C10, owner decision Q1) ---
# The three declarations have distinct meanings: "highest" and "lowest" always imply another card
# of that color, "only" says there is none. A declaration, once made, is never revised.

P0_HAND = ['yellow:4', 'blue:2', 'blue:9', 'submarine:4']             # one yellow, two blues


def table_with_known_hand(mid=1, mode=None):
    """Three players before the first trick; p0 is captain and holds exactly P0_HAND's yellow and blues."""
    e = playing(3, seed=5, mid=mid)
    size = len(e.s['hands']['p0'])
    filler = [c for c in DECK if suit(c) in ('green', 'pink')][:size - len(P0_HAND)]
    mine = P0_HAND + filler
    rest = [c for c in DECK if c not in mine]
    cut = len(e.s['hands']['p1'])
    e.s['hands'] = {'p0': sorted(mine), 'p1': sorted(rest[:cut]), 'p2': sorted(rest[cut:])}
    e.s['captain'] = e.s['leader'] = e.s['turn'] = 'p0'
    if mode:
        e.s['communication'] = mode
    e.check()
    return e


def test_the_rule_gives_a_single_card_only_and_never_gives_only_to_a_longer_holding():
    assert assertions(['yellow:4', 'blue:2', 'blue:9'], 'yellow:4') == ['only']
    assert assertions(['blue:2', 'blue:9'], 'blue:2') == ['lowest']
    assert assertions(['blue:2', 'blue:9'], 'blue:9') == ['highest']
    assert assertions(['blue:2', 'blue:5', 'blue:9'], 'blue:5') == []
    assert assertions(['blue:2', 'blue:5', 'blue:9'], 'blue:2') == ['lowest']
    assert assertions(['blue:2', 'blue:5', 'blue:9'], 'blue:9') == ['highest']
    assert assertions(['submarine:1'], 'submarine:1') == [] and assertions(['blue:2'], 'blue:9') == []
    for color in ('blue', 'green', 'pink', 'yellow'):                 # every rank, every color
        for r in range(1, 10):
            assert assertions([f'{color}:{r}', 'submarine:2'], f'{color}:{r}') == ['only']


@pytest.mark.parametrize('mode', [None, 'currents', 'rapture'])
def test_the_engine_refuses_highest_and_lowest_for_a_single_card_in_every_mode(mode):
    e = table_with_known_hand(mid=9 if mode == 'currents' else 1, mode=mode)
    assert e.communication_options('p0')['yellow:4'] == ['only']
    assert e.view('p0')['me']['communication_options']['yellow:4'] == ['only']   # what the client offers
    before = e.snapshot()
    for declared in ('highest', 'lowest'):
        with pytest.raises(Invalid) as refused:
            act(e, 'p0', 'communicate', card='yellow:4', assertion=declared)
        assert refused.value.code == 'communication'
        assert e.snapshot() == before                                 # state, random generator, request memory
    assert e.s['exposures'] == [] and 'p0' not in e.s['spent']
    act(e, 'p0', 'communicate', card='yellow:4', assertion='only')
    assert e.s['exposures'] == [{'seat': 'p0', 'card': 'yellow:4', 'assertion': 'only', 'active': True}]


@pytest.mark.parametrize('card,legal', [('blue:2', 'lowest'), ('blue:9', 'highest')])
def test_two_cards_of_a_color_keep_highest_and_lowest_and_cannot_be_called_only(card, legal):
    e = table_with_known_hand()
    assert e.communication_options('p0')[card] == [legal]
    before = e.snapshot()
    for declared in ('only', 'highest' if legal == 'lowest' else 'lowest'):
        with pytest.raises(Invalid):
            act(e, 'p0', 'communicate', card=card, assertion=declared)
        assert e.snapshot() == before
    act(e, 'p0', 'communicate', card=card, assertion=legal)
    assert e.s['exposures'][0]['assertion'] == legal


@pytest.mark.parametrize('mode', [None, 'currents'])
def test_an_earlier_highest_declaration_stays_when_the_card_becomes_the_only_one(mode):
    e = table_with_known_hand(mid=9 if mode == 'currents' else 1, mode=mode)
    act(e, 'p0', 'communicate', card='blue:9', assertion='highest')
    act(e, 'p0', 'play_card', card='blue:2')                          # p0 leads the other blue
    for _ in range(2):
        q = e.s['turn']
        act(e, q, 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
    assert [c for c in e.s['hands']['p0'] if suit(c) == 'blue'] == ['blue:9']
    assert assertions(e.s['hands']['p0'], 'blue:9') == ['only']       # what a new declaration would be
    record = e.s['exposures'][0]
    assert record == {'seat': 'p0', 'card': 'blue:9', 'assertion': 'highest', 'active': True}
    assert e.view('p0')['exposures'][0]['assertion'] == 'highest'     # the author still sees it
    other = e.view('p1')['exposures'][0]
    assert other.get('assertion') == (None if mode == 'currents' else 'highest')
    if e.s['result'] is None:
        assert 'blue:9' not in e.communication_options('p0')          # the token is spent; nothing to revise
        with pytest.raises(Invalid):
            act(e, 'p0', 'communicate', card='blue:9', assertion='only')
        assert e.s['exposures'][0]['assertion'] == 'highest'


def test_single_card_validation_does_not_change_who_sees_a_currents_declaration():
    e = table_with_known_hand(mid=9, mode='currents')
    act(e, 'p0', 'communicate', card='yellow:4', assertion='only')
    assert e.view('p0')['exposures'][0]['assertion'] == 'only'
    for viewer in ('p1', 'p2', None):
        assert 'assertion' not in e.view(viewer)['exposures'][0]


def test_every_offered_declaration_is_true_and_single_cards_are_always_only():
    for seed in range(30):
        for n in (2, 3, 4, 5):
            e = playing(n, seed)
            for human in e.s['humans']:
                hand = e.s['hands'][human]
                for card, offered in e.communication_options(human).items():
                    same = [c for c in hand if suit(c) == suit(card)]
                    assert len(offered) == 1                          # never an ambiguous choice
                    if len(same) == 1:
                        assert offered == ['only']
                    else:
                        assert offered == (['highest'] if rank(card) == max(map(rank, same)) else ['lowest'])

