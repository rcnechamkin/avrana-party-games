"""EXPO coverage tests (AVR-247): the gaps the traceability matrix named.

games/expo/docs/IMPLEMENTATION_PLAN.md lists, row by row, what was still thinly tested after the
reconciliation. Each test here names the matrix row (T..) it closes. Nothing here changes
behaviour: every test pins what the engine, the adapter and the WebSocket binding already do.
"""
import asyncio
import json
import random
import threading
import time
from copy import deepcopy

import pytest
import uvicorn
from fastapi import FastAPI, WebSocket
from websockets.sync.client import connect

import server
from core.net import GameBinding
from games.expo.content import TASKS
from games.expo.engine import Engine, Invalid
from games.expo import game
from games.expo.game import ExpoSession
from games.expo.rules import legal_cards, suit
from games.expo.tasks import evaluate

from test_expo import act, allocated, command, decide, place, playing, session, task_state
from test_expo_contract import play_trick, two_humans

PHASES = ('allocation', 'prediction', 'assistance', 'passing', 'before_trick', 'in_trick', 'mission_result')


# ---- T36 privacy: every phase, every viewer ----------------------------------------------------

def at_phase(n, phase, currents=False):
    """A table of n humans standing in the given phase, with something hidden in play: other
    hands, a committed secret prediction and, with `currents`, a declaration only its author knows."""
    humans = [f'p{i}' for i in range(n)]
    for seed in range(40):
        e = Engine(humans, random.Random(seed), 5)
        if currents:
            e.s['communication'] = 'currents'
        if phase != 'allocation':
            e.s['pool'] = ['exactlyXtrickSecret', 'blue4']
            e.s['selected'] = list(e.s['pool'])
            place(e)
            e.s['initial_count'] = 2
        if phase == 'prediction':
            while e.s['pool']:
                act(e, e.controller(e.selector()), 'choose_task', task=e.s['pool'][0])
        elif phase != 'allocation':
            allocated(e)
            if e.s['phase'] != 'assistance':
                continue                                             # a counted allocation failure
            if phase == 'passing':
                decide(e, humans[0], 'distress', direction='left')
                act(e, humans[0], 'pass_card', card=next(c for c in e.playable(humans[0]) if suit(c) != 'submarine'))
            elif phase != 'assistance':
                decide(e, humans[0], 'begin')
                options = e.communication_options(humans[0])
                if options:                                          # an exposure is part of the view
                    card, opts = next(iter(options.items()))
                    act(e, humans[0], 'communicate', card=card, assertion=opts[0])
                if phase in ('in_trick', 'mission_result'):
                    q = e.s['turn']
                    shown = {x['card'] for x in e.s['exposures']}        # keep the shown card in hand
                    legal = legal_cards(e.playable(q), e.s['trick'])
                    act(e, e.controller(q), 'play_card', card=next((c for c in legal if c not in shown), legal[0]))
                if phase == 'mission_result':
                    e._finish('failed', 'fixture')
        if e.s['phase'] == phase:
            return e
    pytest.fail(f'no fixture for {n} humans in {phase}')


def with_other_secrets(e, viewer, seed):
    """The same table with everything the viewer may not see changed: the other players' hands,
    Tonoja's covered cards, the other players' sealed distress choices, a secret prediction the
    viewer does not own and, in currents, a declaration the viewer did not make."""
    other = Engine.restore(deepcopy(e.snapshot()))
    s = other.s
    fixed = {x['card'] for x in s['exposures'] if x['active']} | {'submarine:4'}
    cells = [('hand', q, i) for q in s['humans'] if q != viewer
             for i, c in enumerate(s['hands'][q]) if c not in fixed]
    cells += [('covered', i, None) for i, col in enumerate(s['columns']) if col['covered'] is not None]
    read = lambda kind, key, i: s['hands'][key][i] if kind == 'hand' else s['columns'][key]['covered']
    cards = [read(*cell) for cell in cells]
    shuffled = list(cards)
    rng = random.Random(seed)
    while shuffled == cards:
        rng.shuffle(shuffled)
    for (kind, key, i), card in zip(cells, shuffled):
        if kind == 'hand':
            s['hands'][key][i] = card
        else:
            s['columns'][key]['covered'] = card
    for q in list(s['pass_choices']):                                # a sealed choice stays legal
        if q != viewer:
            s['pass_choices'][q] = next(c for c in reversed(s['hands'][q]) if suit(c) != 'submarine')
    if not s['result']:                                              # a result reveals predictions
        for k in s['predictions']:
            if TASKS[k]['params'].get('secret') and other.controller(s['assignments'][k]) != viewer:
                s['predictions'][k] += 1
    if s['communication'] == 'currents':                             # only its author knows it
        for x in s['exposures']:
            if x['seat'] != viewer:
                x['assertion'] = {'highest': 'lowest', 'lowest': 'only', 'only': 'highest'}[x['assertion']]
    other.check()
    return other


@pytest.mark.parametrize('n', [2, 3, 4, 5])
@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('currents', [False, True])
def test_no_view_depends_on_what_its_viewer_may_not_see(n, phase, currents):
    if phase == 'passing' and n == 2:
        pytest.skip('distress is unavailable to two players (C11)')
    e = at_phase(n, phase, currents)
    if phase in ('assistance', 'passing', 'before_trick', 'in_trick'):
        assert e.s['predictions'] == {'exactlyXtrickSecret': 0}      # a secret is really in play
    if phase in ('before_trick', 'in_trick', 'mission_result'):
        assert any(x['active'] for x in e.s['exposures'])            # and so is a live declaration
    viewers = list(e.s['humans']) + [None, 'tonoja', 'stranger']
    for viewer in viewers:
        view = e.view(viewer)
        for seed in range(3):
            other = with_other_secrets(e, viewer, seed)
            assert other.snapshot() != e.snapshot()
            assert other.view(viewer) == view, (viewer, phase)
        text = json.dumps(view)
        hidden = {c for q in e.s['humans'] if q != viewer for c in e.s['hands'][q]}
        hidden |= {col['covered'] for col in e.s['columns'] if col['covered']}
        hidden -= {x['card'] for x in e.s['exposures'] if x['active']}
        assert not [c for c in hidden if '"%s"' % c in text], (viewer, phase)
        assert 'pass_choices' not in text and 'hands' not in view and 'columns' not in view


def test_a_sealed_distress_choice_is_invisible_whichever_card_was_chosen():
    base = allocated(Engine(['a', 'b', 'c'], random.Random(4)))
    decide(base, 'a', 'distress', direction='left')
    first, second = [c for c in base.playable('a') if suit(c) != 'submarine'][:2]
    tables = []
    for card in (first, second):
        e = Engine.restore(deepcopy(base.snapshot()))
        act(e, 'a', 'pass_card', card=card)
        assert e.s['pass_choices'] == {'a': card} and card in e.s['hands']['a']
        tables.append(e)
    for viewer in ('b', 'c', None, 'stranger'):
        assert tables[0].view(viewer) == tables[1].view(viewer)
    assert all(t.view('a')['me']['pass_locked'] for t in tables)
    assert not tables[0].view('b')['me']['pass_locked']


def test_tonojas_covered_cards_reach_no_view_until_their_trick_is_resolved():
    uncovered_mid_trick = revealed = 0
    for seed in range(6):
        e = two_humans(1, seed)
        while not e.s['result']:
            covered = {c['covered'] for c in e.s['columns'] if c['covered']}
            # Tonoja has played from a column and the trick is still open: the card beneath
            # is the one a careless view would show in the empty place.
            waiting = [c['covered'] for c in e.s['columns'] if c['top'] is None and c['covered']]
            uncovered_mid_trick += bool(waiting)
            for viewer in ('a', 'b', None, 'tonoja', 'stranger'):
                view = e.view(viewer)
                text = json.dumps(view)
                assert not [c for c in covered if '"%s"' % c in text], (seed, viewer)
                assert view['tonoja'] == [c['top'] for c in e.s['columns']]
                assert view['hand_counts']['tonoja'] == sum((c['top'] is not None) + (c['covered'] is not None)
                                                            for c in e.s['columns'])
            q = e.s['turn']
            act(e, e.controller(q), 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
            if waiting and not e.s['trick']:                         # the trick resolved: now it shows
                assert all(card in e.view(None)['tonoja'] for card in waiting)
                revealed += 1
    assert uncovered_mid_trick and revealed


# ---- T38, T10 concurrency: two commands at one revision ----------------------------------------

def test_two_commands_built_at_the_same_revision_cannot_both_be_accepted():
    e = playing()
    first, second = [(q, next(iter(e.communication_options(q).items()))) for q in ('p0', 'p1')]
    messages = [(q, command(e, q, 'communicate', card=card, assertion=opts[0])) for q, (card, opts) in (first, second)]
    assert e.apply(*messages[0], 100)
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # legal on its own, but stale
        e.apply(*messages[1], 100)
    assert refused.value.code == 'stale' and e.snapshot() == before
    assert [x['seat'] for x in e.s['exposures']] == ['p0']
    q, (card, opts) = second                                        # at the new revision it is fine
    act(e, q, 'communicate', card=card, assertion=opts[0])
    assert [x['seat'] for x in e.s['exposures']] == ['p0', 'p1']


def test_the_last_shared_sonar_token_requested_twice_is_spent_once():
    e = playing(mid=11)
    assert e.s['communication'] == 'rapture' and e.s['shared'] == 1
    requests = []
    for q in ('p0', 'p1'):
        card, opts = next(iter(e.communication_options(q).items()))
        requests.append((q, command(e, q, 'communicate', card=card, assertion=opts[0])))
    assert e.apply(*requests[0], 100)
    with pytest.raises(Invalid) as refused:
        e.apply(*requests[1], 100)
    assert refused.value.code == 'stale'
    q, old = requests[1]
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # retried on the new state
        act(e, q, 'communicate', card=old['card'], assertion=old['assertion'])
    assert refused.value.code == 'communication' and e.snapshot() == before
    assert e.s['shared'] == 0 and len(e.s['exposures']) == 1


# ---- T12 task generation: the skip order -------------------------------------------------------

def test_task_drawing_skips_a_card_that_would_exceed_the_total_and_keeps_scanning():
    e = Engine(['a', 'b', 'c'], random.Random(1))
    difficulty = lambda k: TASKS[k]['difficulty']['3']
    by = {}
    for k, d in TASKS.items():
        if d['enabled']:
            by.setdefault(difficulty(k), []).append(k)
    three, two, one = by[3][0], by[2][0], by[1][0]
    deck = [three, by[3][1], two, by[2][1], one, by[1][1]]           # 3, 3, 2, 2, 1, 1
    e.s['deck'], e.s['used'] = list(deck), []
    drawn = e._generate({'target': 6})
    assert drawn == [three, by[3][1]]                                # 3 + 3, in deck order
    assert e.s['deck'] == [two, by[2][1], one, by[1][1]]             # the rest keeps its order
    e.s['deck'] = list(deck)
    drawn = e._generate({'target': 4})
    assert drawn == [three, one]                                     # the second 3 and both 2s are skipped
    assert e.s['deck'] == [by[3][1], two, by[2][1], by[1][1]]
    e.s['deck'] = list(deck)
    drawn = e._generate({'target': 5})
    assert drawn == [three, two] and sum(map(difficulty, drawn)) == 5


def test_a_total_the_task_deck_cannot_reach_is_a_setup_error_not_a_mission_failure():
    e = Engine(['a', 'b', 'c'], random.Random(1))
    three = next(k for k, d in TASKS.items() if d['enabled'] and d['difficulty']['3'] == 3)
    e.s['deck'], e.s['used'] = [three], []
    before = deepcopy(e.s['deck'])
    with pytest.raises(Invalid) as refused:
        e._generate({'target': 2})
    assert refused.value.code == 'task_deck' and e.s['deck'] == before and e.s['result'] is None


# ---- T35 retry with new tasks, and next in any order -------------------------------------------

def test_a_retry_with_new_tasks_draws_other_tasks_to_the_same_total():
    e = playing(mid=5)
    old = list(e.s['selected'])
    target = e.s['mission']['target']
    total = lambda ks: sum(TASKS[k]['difficulty']['3'] for k in ks)
    assert total(old) == target
    e._finish('failed', 'fixture')
    attempt, attempts = e.s['attempt'], e.s['attempts']
    decide(e, 'p0', 'retry', keep=False)
    new = e.s['selected']
    assert total(new) == target and not set(new) & set(old)          # the old ones are used up
    assert all(k in e.s['used'] for k in old) and not set(new) & set(e.s['deck'])
    assert e.s['attempt'] == attempt + 1 and e.s['attempts'] == attempts and e.s['phase'] == 'allocation'
    assert e.s['assignments'] == {} and e.s['spent'] == [] and e.s['history'] == []


def test_the_next_mission_may_be_any_enabled_mission_in_any_order():
    e = playing()
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # not before a success
        act(e, 'p0', 'propose', proposal={'kind': 'next', 'mission': 2})
    assert refused.value.code == 'phase' and e.snapshot() == before
    e._finish('success', 'fixture')
    decide(e, 'p0', 'next', mission=9)                               # forward, skipping missions
    assert e.s['mission']['id'] == 9 and e.s['communication'] == 'currents' and e.s['attempts'] == 0
    e._finish('failed', 'fixture')
    with pytest.raises(Invalid) as refused:                         # a failure allows retry only
        act(e, 'p0', 'propose', proposal={'kind': 'next', 'mission': 10})
    assert refused.value.code == 'phase'
    e.s['result'] = None
    e._finish('success', 'fixture')
    decide(e, 'p0', 'next', mission=2)                               # and back again
    assert e.s['mission']['id'] == 2
    assert [entry['mission'] for entry in e.s['log']] == [1, 9]


# ---- T31 allocation with the dummy, and five seats ---------------------------------------------

def test_mission_six_lets_the_crew_name_tonoja_and_the_captain_predicts_for_it():
    e = Engine(['a', 'b'], random.Random(9), 6)
    e.s['pool'] = ['blue4', 'exactlyXtrick']
    e.s['selected'] = list(e.s['pool'])
    place(e)
    captain = e.s['captain']
    other = next(q for q in e.s['humans'] if q != captain)
    act(e, other, 'propose', proposal={'kind': 'assign', 'owner': 'tonoja', 'task': 'all'})
    assert e.s['assignments'] == {}                                  # both humans decide together
    act(e, captain, 'confirm', yes=True)
    assert set(e.s['assignments'].values()) == {'tonoja'} and e.s['phase'] == 'prediction'
    assert not e.s['before_first_only']                              # that rule is missions 10 and 13
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # only the captain speaks for it
        act(e, other, 'predict', task='exactlyXtrick', count=1)
    assert refused.value.code == 'owner' and e.snapshot() == before
    act(e, captain, 'predict', task='exactlyXtrick', count=1)
    assert e.s['phase'] == 'assistance'


def test_mission_twenty_five_with_five_seats_skips_only_the_captain():
    for seed in range(8):
        e = Engine(['a', 'b', 'c', 'd', 'e'], random.Random(seed), 25)
        captain = e.s['captain']
        seats = e.s['seats']
        at = seats.index(captain)
        assert e.s['allocation_ring'] == seats[at + 1:] + seats[:at] and e.s['planned'] == 8
        assert sum(TASKS[k]['difficulty']['5'] for k in e.s['selected']) == 12
        order = []
        while e.s['pool']:
            seat = e.selector()
            order.append(seat)
            act(e, seat, 'choose_task', task=next(k for k in e.s['pool'] if e.eligible(k, seat)))
        ring = e.s['allocation_ring']
        assert order == [ring[i % 4] for i in range(len(order))] and captain not in e.s['assignments'].values()
        assert e.s['leader'] == captain
        before = e.snapshot()
        with pytest.raises(Invalid):                                # and allocation is over
            act(e, captain, 'choose_task', task=e.s['selected'][0])
        assert e.s['phase'] != 'allocation' and e.snapshot() == before


# ---- T02 the three-seat extra card -------------------------------------------------------------

def test_with_three_seats_the_card_left_unplayed_may_be_submarine_four():
    for seed in range(60):
        e = playing(seed=seed)
        captain = e.s['captain']
        if len(e.s['hands'][captain]) != 14:
            continue
        while not e.s['result'] and len(e.s['history']) < e.s['planned']:
            q = e.s['turn']
            legal = legal_cards(e.playable(q), e.s['trick'])
            keep = [c for c in legal if c != 'submarine:4'] or legal
            act(e, q, 'play_card', card=keep[0])
            e.check()
        if e.s['hands'][captain] == ['submarine:4'] and len(e.s['history']) == 13:
            assert e.s['result'] and e.s['planned'] == 13
            assert all(len(h) == 0 for q, h in e.s['hands'].items() if q != captain)
            assert 'submarine:4' not in [p['card'] for h in e.s['history'] for p in h['plays']]
            return
    pytest.fail('no deal left submarine 4 as the unplayed card')


# ---- T16, T19, T20, T21, T23 task boundaries ---------------------------------------------------

def held(cards, planned=13, extra=()):
    """History in which seat `a` wins one trick per given card list; `extra` tricks go to `b`."""
    wins = ['a'] * len(cards) + ['b'] * len(extra)
    tricks = {i + 1: list(cs) for i, cs in enumerate(list(cards) + list(extra))}
    return task_state(wins, tricks, planned)


EXACT = [('2x9', ['blue:9', 'green:9', 'pink:9'], 'yellow:9'),
         ('3x6', ['blue:6', 'green:6', 'pink:6', 'yellow:6'], None),
         ('4x3', ['blue:3', 'green:3', 'pink:3', 'yellow:3'], None),
         ('4x9', ['blue:9', 'green:9', 'pink:9', 'yellow:9'], None),
         ('1red', ['pink:1', 'pink:2'], None), ('2blue', ['blue:1', 'blue:2', 'blue:3'], None),
         ('2green', ['green:1', 'green:2', 'green:3'], None),
         ('1black', ['submarine:1', 'submarine:2'], None),
         ('2black', ['submarine:1', 'submarine:2', 'submarine:3'], None),
         ('3black', ['submarine:1', 'submarine:2', 'submarine:3', 'submarine:4'], None)]


@pytest.mark.parametrize('key,cards,_spare', EXACT)
def test_an_exact_count_is_pending_until_the_end_and_fails_one_over(key, cards, _spare):
    d = TASKS[key]
    k = d['params']['count']
    filler = [['blue:2' if suit(cards[0]) != 'blue' else 'yellow:2']]
    assert evaluate(d, 'a', held([[c] for c in cards[:k - 1]])) == 'pending'
    assert evaluate(d, 'a', held([[c] for c in cards[:k]])) == 'pending'          # judged at the end
    done = held([[c] for c in cards[:k]] + filler * (13 - k))
    assert evaluate(d, 'a', done) == 'satisfied'                                   # exactly k at the end
    if len(cards) > k:
        assert evaluate(d, 'a', held([[c] for c in cards[:k + 1]])) == 'failed'   # one too many, at once
    short = held([[c] for c in cards[:k - 1]] + filler * (13 - k + 1))
    assert evaluate(d, 'a', short) == 'failed'                                     # one too few at the end


@pytest.mark.parametrize('key,needed,total', [('2x9', 2, 4), ('3x6', 3, 4), ('4x3', 4, 4), ('4x9', 4, 4),
                                              ('1black', 1, 4), ('2black', 2, 4), ('3black', 3, 4),
                                              ('1red', 1, 9), ('2blue', 2, 9), ('2green', 2, 9),
                                              ('3orMore5', 3, 4), ('2orMore7', 2, 4), ('3orMore9', 3, 4),
                                              ('5orMoreRed', 5, 9), ('7orMoreYellow', 7, 9)])
def test_a_count_fails_as_soon_as_too_few_matching_cards_are_left(key, needed, total):
    d = TASKS[key]
    assert d['params']['count'] == needed
    selector = d['params']['selector']
    pool = [f'{s}:{r}' for s in selector['suits'] for r in selector.get('ranks', range(1, 10))
            if not (s == 'submarine' and r > 4)]
    assert len(pool) == total
    lost_ok = len(pool) - needed                                     # the others may win this many
    state = held([], extra=[[c] for c in pool[:lost_ok]])
    assert evaluate(d, 'a', state) == 'pending'
    state = held([], extra=[[c] for c in pool[:lost_ok + 1]])
    assert evaluate(d, 'a', state) == 'failed'


def test_the_two_named_submarine_counts_need_their_card_and_no_other():
    for key, own, other in (('black1', 'submarine:1', 'submarine:2'), ('black2', 'submarine:2', 'submarine:1')):
        d = TASKS[key]
        assert evaluate(d, 'a', held([[own]])) == 'pending'
        assert evaluate(d, 'a', held([[own]] + [['blue:2']] * 12)) == 'satisfied'
        assert evaluate(d, 'a', held([[own], [other]])) == 'failed'            # a second submarine
        assert evaluate(d, 'a', held([], extra=[[own]])) == 'failed'            # someone else took it
        assert evaluate(d, 'a', held([[other]] + [['blue:2']] * 12)) == 'failed'  # the wrong one


def test_one_pink_and_one_green_is_exact_for_each_color_and_judged_at_the_end():
    d = TASKS['1red+1green']
    assert evaluate(d, 'a', held([['pink:1', 'green:1']])) == 'pending'
    assert evaluate(d, 'a', held([['pink:1', 'green:1']] + [['blue:2']] * 12)) == 'satisfied'
    assert evaluate(d, 'a', held([['pink:1', 'green:1', 'green:2']])) == 'failed'
    assert evaluate(d, 'a', held([['pink:1']] + [['blue:2']] * 12)) == 'failed'


@pytest.mark.parametrize('planned,needed', [(13, 7), (10, 6), (8, 5)])
def test_more_than_half_the_tricks_is_strict_for_every_trick_count(planned, needed):
    d = TASKS['moreThanHalfTricks']
    assert evaluate(d, 'a', task_state(['a'] * (needed - 1), planned=planned)) == 'pending'
    assert evaluate(d, 'a', task_state(['a'] * needed, planned=planned)) == 'satisfied'      # at once
    half = ['a'] * (needed - 1) + ['b'] * (planned - needed + 1)
    assert evaluate(d, 'a', task_state(half, planned=planned)) == 'failed'    # exactly half is not more


def wins(a, b, c, planned=13):
    assert a + b + c == planned
    return task_state(['a'] * a + ['b'] * b + ['c'] * c, planned=planned)


@pytest.mark.parametrize('key,owner,counts,expected', [
    ('moreTricksThanOthers', 'a', (5, 4, 4), 'satisfied'),
    ('moreTricksThanOthers', 'a', (5, 5, 3), 'failed'),              # tied for most
    ('lessTricksThanOthers', 'a', (3, 5, 5), 'satisfied'),
    ('lessTricksThanOthers', 'a', (3, 3, 7), 'failed'),              # tied for fewest
    ('lessTricksThanOthers', 'a', (0, 0, 13), 'failed'),             # nothing against nothing is a tie
    ('moreTricksThanCaptain', 'a', (5, 4, 4), 'satisfied'),
    ('moreTricksThanCaptain', 'a', (4, 4, 5), 'failed'),             # level with the captain
    ('lessTricksThanCaptain', 'a', (3, 4, 6), 'satisfied'),
    ('lessTricksThanCaptain', 'a', (4, 4, 5), 'failed'),
    ('equalTricksThanCaptain', 'a', (4, 4, 5), 'satisfied'),
    ('equalTricksThanCaptain', 'a', (0, 0, 13), 'satisfied'),        # zero each is equal
    ('equalTricksThanCaptain', 'a', (5, 4, 4), 'failed'),
    ('equalTricksThanCaptain', 'c', (4, 4, 5), 'failed'),            # only the captain counts
    ('moreTricksThanCaptain', 'c', (6, 3, 4), 'satisfied')])        # another seat may have more
def test_trick_comparisons_are_strict_and_judged_only_at_the_end(key, owner, counts, expected):
    d = TASKS[key]
    final = wins(*counts)                                            # the captain is seat b
    assert evaluate(d, owner, final) == expected
    early = deepcopy(final)
    early['history'] = early['history'][:-1]                         # one trick still to play
    assert evaluate(d, owner, early) == 'pending'


@pytest.mark.parametrize('cards,expected', [
    (['blue:9', 'green:8', 'pink:4'], 'failed'),                     # 21
    (['blue:9', 'green:8', 'pink:5'], 'satisfied'),                  # 22
    (['blue:9', 'green:8', 'pink:6'], 'satisfied'),                  # 23
    (['blue:9', 'green:8', 'pink:7'], 'failed'),                     # 24
    (['blue:9', 'green:9', 'submarine:4'], 'failed'),                # 22 with a submarine
    (['blue:9', 'green:8', 'pink:3', 'yellow:2'], 'satisfied'),      # four cards
    (['blue:9', 'green:8', 'pink:3', 'yellow:2', 'yellow:1'], 'satisfied'),   # five cards
    (['blue:6', 'green:6', 'pink:5', 'yellow:5', 'yellow:2'], 'failed')])     # 24 with five
def test_a_trick_worth_twenty_two_or_twenty_three_has_exact_bounds(cards, expected):
    d = TASKS['value22or23']
    state = held([cards] + [['blue:1']] * 12)
    assert evaluate(d, 'a', state) == expected
    if expected == 'satisfied':                                      # and it completes at once
        assert evaluate(d, 'a', held([cards])) == 'satisfied'
    else:
        assert evaluate(d, 'a', held([cards])) == 'pending'
    assert evaluate(d, 'b', held([['blue:9', 'green:8', 'pink:5']])) == 'pending'   # another seat's trick


@pytest.mark.parametrize('planned', [13, 10, 8])
def test_the_last_trick_is_the_planned_trick_for_every_crew_size(planned):
    last = ['b'] * (planned - 1) + ['a']
    assert evaluate(TASKS['lastTrick'], 'a', task_state(last, planned=planned)) == 'satisfied'
    assert evaluate(TASKS['onlyLastTrick'], 'a', task_state(last, planned=planned)) == 'satisfied'
    assert evaluate(TASKS['lastTrick'], 'a', task_state(['b'] * planned, planned=planned)) == 'failed'
    early = ['b'] * (planned - 2) + ['a']                            # the trick before the last
    assert evaluate(TASKS['lastTrick'], 'a', task_state(early, planned=planned)) == 'pending'
    assert evaluate(TASKS['onlyLastTrick'], 'a', task_state(early, planned=planned)) == 'failed'
    both = ['a'] + ['b'] * (planned - 2) + ['a']
    assert evaluate(TASKS['firstAndLastTrick'], 'a', task_state(both, planned=planned)) == 'satisfied'
    final = task_state(last, {planned: ['green:2', 'blue:3', 'blue:4']}, planned)
    assert evaluate(TASKS['green2lastTrick'], 'a', final) == 'satisfied'
    wrong = task_state(last, {planned - 1: ['green:2', 'blue:3', 'blue:4']}, planned)
    assert evaluate(TASKS['green2lastTrick'], 'a', wrong) == 'failed'


def test_color_collection_tasks_complete_early_and_fail_only_at_the_end():
    each, whole = TASKS['eachColor'], TASKS['allOneColor']
    assert evaluate(each, 'a', held([['blue:1', 'green:1', 'pink:1']])) == 'pending'
    assert evaluate(each, 'a', held([['blue:1', 'green:1', 'pink:1'], ['yellow:1']])) == 'satisfied'
    assert evaluate(each, 'a', held([['blue:1', 'green:1', 'submarine:1']] + [['blue:2']] * 12)) == 'failed'
    nine = [[f'blue:{r}' for r in range(i, i + 3)] for i in (1, 4, 7)]
    assert evaluate(whole, 'a', held(nine[:2])) == 'pending'
    assert evaluate(whole, 'a', held(nine)) == 'satisfied'
    lost = held(nine[:2], extra=[nine[2]])                           # the last three went elsewhere:
    assert evaluate(whole, 'a', lost) == 'pending'                   # not recognised before the end
    lost = held(nine[:2] + [['green:1']] * 10, extra=[nine[2]])
    assert evaluate(whole, 'a', lost) == 'failed'


# ---- T27, T28, T29 mission outcomes ------------------------------------------------------------

def test_a_mission_succeeds_as_soon_as_its_last_task_is_complete():
    for seed in range(40):
        e = Engine(['a', 'b', 'c'], random.Random(seed))
        e.s['pool'] = ['firstTrick']
        e.s['selected'] = ['firstTrick']
        place(e)
        act(e, e.s['captain'], 'choose_task', task='firstTrick')
        decide(e, 'a', 'begin')
        first = play_trick(e)
        if first['winner'] == e.s['captain']:
            assert e.s['result'] == {'status': 'success', 'reason': 'All mission objectives completed.'}
            assert len(e.s['history']) == 1 < e.s['planned'] and e.s['phase'] == 'mission_result'
            assert e.s['log'][-1]['mission'] == 1
            return
        assert e.s['result']['status'] == 'failed'                   # lost the first trick: over at once
    pytest.fail('the captain never won the first trick')


def test_mission_eight_counts_tonoja_in_the_balance_of_nines():
    e = two_humans(8)
    order = e.s['seats']
    won = lambda i, seat, cards: {'index': i, 'leader': seat, 'winner': seat,
                                  'plays': [{'seat': order[j], 'card': c} for j, c in enumerate(cards)]}
    e.s['history'] = [won(1, 'tonoja', ['blue:9', 'blue:2', 'blue:3'])]
    e._outcome()
    assert e.s['result'] is None
    e.s['history'].append(won(2, 'tonoja', ['green:9', 'green:2', 'green:3']))
    e._outcome()
    assert e.s['result'] == {'status': 'failed', 'reason': 'A crew member has captured two more 9s than another.'}


def test_mission_twenty_three_holds_while_the_first_winner_stays_strictly_ahead_all_deal():
    order = ['p0', 'p0', 'p1', 'p0', 'p2', 'p0', 'p1', 'p0', 'p2', 'p0', 'p1', 'p0', 'p2']
    e = Engine(['p0', 'p1', 'p2'], random.Random(4), 23)
    decide(e, 'p0', 'begin')
    for i, seat in enumerate(order):
        e.s['history'].append({'index': i + 1, 'leader': seat, 'winner': seat, 'plays': []})
        e._outcome()
        if i < 12:
            assert e.s['result'] is None, i
    assert e.s['result'] == {'status': 'success', 'reason': 'All mission objectives completed.'}
    e = Engine(['p0', 'p1', 'p2'], random.Random(4), 23)
    decide(e, 'p0', 'begin')
    for i, seat in enumerate(['p0', 'p1']):                          # level after two tricks
        e.s['history'].append({'index': i + 1, 'leader': seat, 'winner': seat, 'plays': []})
        e._outcome()
    assert e.s['result']['status'] == 'failed' and len(e.s['history']) == 2


# ---- T08, T26, T40 restart: every point, and a write failure at each ---------------------------

def by_pid(s, tokens):
    return {s.players[t].pid: t for t in tokens}


def send(s, token, t, **kwargs):
    fx = s.game_action(token, command(s.engine, s.players[token].pid, t, **kwargs))
    fire_hold(s)
    return fx


def fire_hold(s):
    """The adapter's timer for a resolving trick, fired now instead of after RESOLVE_HOLD: the
    same path (game_tick) with the hold's moment moved to the present (AVR-246)."""
    if s.engine and s.engine.s['resolving'] and s._hold:
        s._hold = (s._hold[0], game._mono())
        s.game_tick()


def agree(s, tokens, kind, **kwargs):
    send(s, tokens[0], 'propose', proposal={'kind': kind, **kwargs})
    for t in tokens[1:]:
        send(s, t, 'confirm', yes=True)


def table_at(point, path):
    """A stored three-human table at one of the restart points, and its next legal command."""
    s, tokens = session(path=path)
    e = s.engine
    seat = by_pid(s, tokens)
    while e.s['pool']:
        q = e.selector()
        send(s, seat[q], 'choose_task', task=next(k for k in e.s['pool'] if e.eligible(k, q)))
    for k, q in list(e.s['assignments'].items()):
        if TASKS[k]['params'].get('predict'):
            send(s, seat[q], 'predict', task=k, count=0)
    color = lambda q: next(c for c in e.playable(q) if suit(c) != 'submarine')
    if point in ('sealed', 'exchanged'):
        agree(s, tokens, 'distress', direction='left')
        first = e.s['humans'][0]
        send(s, seat[first], 'pass_card', card=color(first))
        if point == 'sealed':
            q = e.s['humans'][1]
            return s, tokens, (seat[q], 'pass_card', {'card': color(q)})
        for q in e.s['humans'][1:]:
            send(s, seat[q], 'pass_card', card=color(q))
    else:
        agree(s, tokens, 'begin')
    q = s.engine.s['turn']
    if point == 'exposed':
        card, opts = next(iter(s.engine.communication_options(q).items()))
        send(s, seat[q], 'communicate', card=card, assertion=opts[0])
    if point == 'mid_trick':
        send(s, seat[q], 'play_card', card=s.engine.playable(q)[0])
        q = s.engine.s['turn']
    if point == 'result':
        while not s.engine.s['result']:
            q = s.engine.s['turn']
            send(s, seat[q], 'play_card', card=legal_cards(s.engine.playable(q), s.engine.s['trick'])[0])
        keep = s.engine.s['result']['status'] == 'failed'
        return s, tokens, (tokens[0], 'propose', {'proposal': {'kind': 'retry', 'keep': True} if keep
                                                 else {'kind': 'next', 'mission': 2}})
    card = legal_cards(s.engine.playable(q), s.engine.s['trick'])[0]
    return s, tokens, (seat[q], 'play_card', {'card': card})


POINTS = ('sealed', 'exchanged', 'exposed', 'mid_trick', 'result')
EXPECTED_PHASE = {'sealed': 'passing', 'exchanged': 'before_trick', 'exposed': 'before_trick',
                  'mid_trick': 'in_trick', 'result': 'mission_result'}


def stored(state):
    return {k: v for k, v in state.items() if k not in ('away', 'revision')}


@pytest.mark.parametrize('point', POINTS)
def test_a_restart_restores_the_table_exactly_at_every_point(point, tmp_path):
    path = tmp_path / 'crew.json'
    s, tokens, (token, verb, fields) = table_at(point, path)
    before = s.engine.snapshot()
    assert before['state']['phase'] == EXPECTED_PHASE[point]
    again = ExpoSession(random.Random(99), snapshot_path=path)
    after = again.engine.snapshot()
    assert again.recovery_error is None and again.participants == tokens
    assert stored(after['state']) == stored(before['state']) and after['rng'] == before['rng']
    assert after['state']['revision'] == before['state']['revision'] + 1
    assert after['state']['away'] == after['state']['humans']        # everyone must come back
    if point == 'sealed':
        assert len(after['state']['pass_choices']) == 1               # the sealed choice survived
    if point == 'exposed':
        assert after['state']['exposures'] == before['state']['exposures'] and after['state']['spent']
        assert again.engine.view(None)['exposures'] == s.engine.view(None)['exposures']
    refused = send(again, token, verb, **fields)                      # nothing moves while away
    assert refused[0]['code'] == 'paused'
    for t in tokens:
        again.join(t, t)
    assert again.engine.s['away'] == []
    assert send(again, token, verb, **fields) == []                   # the game simply continues
    assert again.engine.s['revision'] > after['state']['revision']
    if point == 'sealed':
        assert len(again.engine.s['pass_choices']) == 2 and again.engine.s['phase'] == 'passing'


@pytest.mark.parametrize('point', POINTS)
def test_a_write_failure_at_every_point_rejects_the_command_and_keeps_the_table(point, tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    s, tokens, (token, verb, fields) = table_at(point, path)
    before, on_disk = s.engine.snapshot(), path.read_text(encoding='utf-8')
    working = s.store.write

    def broken(snapshot):
        raise OSError('disk unavailable')
    monkeypatch.setattr(s.store, 'write', broken)
    effects = send(s, token, verb, **fields)
    assert effects[0]['code'] == 'storage'
    assert s.engine.snapshot() == before and s.phase == before['state']['phase']
    assert path.read_text(encoding='utf-8') == on_disk                # the stored table is intact
    monkeypatch.setattr(s.store, 'write', working)
    assert send(s, token, verb, **fields) == []                       # the same request now succeeds
    assert s.engine.s['revision'] == before['state']['revision'] + 1
    restored = ExpoSession(random.Random(99), snapshot_path=path)
    assert stored(restored.engine.snapshot()['state']) == stored(s.engine.snapshot()['state'])


def test_the_completed_distress_exchange_survives_a_restart_with_the_cards_in_their_new_hands(tmp_path):
    path = tmp_path / 'crew.json'
    s, tokens, (token, verb, fields) = table_at('sealed', path)
    sealed = dict(s.engine.s['pass_choices'])
    again = ExpoSession(random.Random(99), snapshot_path=path)
    for t in tokens:
        again.join(t, t)
    e = again.engine
    seat = by_pid(again, tokens)
    choices = dict(sealed)
    for q in e.s['humans']:
        if q not in choices:
            choices[q] = next(c for c in e.playable(q) if suit(c) != 'submarine')
            send(again, seat[q], 'pass_card', card=choices[q])
    assert e.s['phase'] == 'before_trick' and e.s['pass_choices'] == {} and e.s['distress']
    for q, card in choices.items():
        target = e.s['seats'][(e.s['seats'].index(q) + 1) % 3]
        assert card in e.s['hands'][target] and card not in e.s['hands'][q]
    final = ExpoSession(random.Random(7), snapshot_path=path)
    assert final.engine.s['hands'] == e.s['hands'] and final.engine.s['distress']


# ---- T39 reconnect in every phase, and T38 from two sockets: the real WebSocket binding --------

def until(cond, limit=10.0):
    end = time.time() + limit
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    raise AssertionError('condition not reached in %.0f s' % limit)


class Room:
    """An EXPO room behind the real WebSocket endpoint on a real server."""

    def __init__(self):
        self.session = ExpoSession(random.Random(4))
        self.binding = GameBinding('expo', self.session)
        room = self
        app = FastAPI()

        @app.websocket('/games/expo/ws')
        async def ws_endpoint(ws: WebSocket):
            room.loop = asyncio.get_running_loop()
            await room.binding.endpoint(ws)

        opts = server.serve_options()
        self.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='warning',
                                                    lifespan='off', ws_max_size=opts['ws_max_size']))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        until(lambda: self.server.started)
        self.url = 'ws://127.0.0.1:%d/games/expo/ws' % self.server.servers[0].sockets[0].getsockname()[1]

    def on_table(self, change):
        """Run a fixture change on the server's loop under the room lock, then push it."""
        async def go():
            async with self.binding.lock:
                change(self.session.engine)
                self.session.engine.s['revision'] += 1               # phones must read the new table
                self.session._sync()
                await self.binding.push_all([])
        asyncio.run_coroutine_threadsafe(go(), self.loop).result(10)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)


class Phone:
    def __init__(self, room, token, name):
        self.room, self.token, self.name = room, token, name
        self.state, self.fx, self.pid = None, [], None
        self.open()

    def open(self):
        # Nothing from an earlier socket may answer for this one: a returning phone is judged
        # on the welcome and the state the new connection is sent.
        self.state, self.fx, self.pid = None, [], None
        self.ws = connect(self.room.url)
        self.ws.send(json.dumps({'t': 'hello', 'token': self.token, 'name': self.name}))
        self.read(lambda p: p.pid is not None and p.state is not None)

    def read(self, done, limit=10.0):
        end = time.time() + limit
        while not done(self):
            remaining = end - time.time()
            assert remaining > 0, 'the expected state never arrived'
            try:
                message = json.loads(self.ws.recv(timeout=remaining))
            except TimeoutError:
                continue
            if message['type'] == 'welcome':
                self.pid = message['pid']
            elif message['type'] == 'state':
                self.state = message
            elif message['type'] == 'fx':
                self.fx.append(message)
        return self.state

    @property
    def game(self):
        return self.state['game']

    def send(self, t, **fields):
        scope = {'attempt': self.game['attempt'], 'revision': self.game['revision'],
                 'request': '%s-%s-%d' % (self.pid, t.replace('_', '-'), len(self.fx) + self.game['revision'])} if self.state.get('game') else {}
        self.ws.send(json.dumps({'t': t, **fields, **scope}))

    def plain(self, t, **fields):
        self.ws.send(json.dumps({'t': t, **fields}))

    def catch_up(self, revision=None, stage=None):
        return self.read(lambda p: p.state.get('game') is not None
                         and (revision is None or p.game['revision'] >= revision)
                         and (stage is None or p.game['stage'] == stage))

    def close(self):
        self.ws.close()


@pytest.fixture
def table():
    room, phones = Room(), []
    try:
        for i in range(3):
            phones.append(Phone(room, 'expo-phone-%d' % i, 'Crew %d' % i))
        for p in phones:
            p.plain('ready', ready=True)
        until(lambda: len(room.session._connected_ready()) == 3)
        phones[0].plain('start')
        for p in phones:
            p.catch_up(stage='allocation')                           # after the real countdown
        yield room, phones
    finally:
        for p in phones:
            p.close()
        room.stop()


def together(room, phones):
    """Every phone has received the engine's current revision."""
    revision = room.session.engine.s['revision']
    for p in phones:
        p.catch_up(revision)
    return revision


def drop_and_return(room, phones, stage):
    """One phone loses its socket in this phase and returns to the same seat, hand and table."""
    together(room, phones)
    victim, witness = phones[1], phones[0]
    engine = room.session.engine
    assert victim.game['stage'] == stage
    seat, hand, mine = victim.pid, list(victim.game['me']['hand']), deepcopy(victim.game['me'])
    # A return changes who is away, the revision, and adds its own event (AVR-246): nothing else.
    presence = ('away', 'revision', 'events', 'event_seq')
    table_before = {k: v for k, v in deepcopy(engine.s).items() if k not in presence}
    events_before = deepcopy(engine.s['events'])
    victim.close()
    witness.read(lambda p: p.game['away'] == [seat])
    assert engine.s['away'] == [seat]
    marker = len(witness.fx)
    witness.send('propose', proposal={'kind': 'begin'})              # nothing is accepted meanwhile
    witness.read(lambda p: len(p.fx) > marker)
    assert witness.fx[-1]['kind'] == 'invalid' and witness.fx[-1]['code'] == 'paused'
    victim.open()
    victim.read(lambda p: p.state.get('game') and p.game['away'] == [] and p.game['me'])
    assert victim.pid == seat and victim.game['me']['hand'] == hand and victim.game['stage'] == stage
    assert victim.game['me'] == mine                                 # and the same options
    witness.read(lambda p: p.game['away'] == [])
    assert {k: v for k, v in engine.s.items() if k not in presence} == table_before
    added = engine.s['events'][len(events_before):]
    assert engine.s['events'][:len(events_before)] == events_before
    assert [(x['type'], x['seat']) for x in added] == [('PLAYER_RECONNECTED', seat)]
    assert witness.game['events'][-1] == added[0]                    # and every viewer is told
    together(room, phones)


def phone_of(phones, pid):
    return next(p for p in phones if p.pid == pid)


def test_a_dropped_phone_returns_to_its_seat_in_every_phase_through_the_websocket(table):
    room, phones = table
    engine = room.session.engine

    def with_a_prediction(e):
        e.s['pool'] = ['exactlyXtrick', 'blue4']
        e.s['selected'] = list(e.s['pool'])
        place(e)
        e.s['initial_count'] = 2
    room.on_table(with_a_prediction)
    drop_and_return(room, phones, 'allocation')

    while engine.s['pool']:
        together(room, phones)
        chooser = phone_of(phones, engine.selector())
        revision = engine.s['revision']
        chooser.send('choose_task', task=engine.s['pool'][0])
        chooser.catch_up(revision + 1)
    drop_and_return(room, phones, 'prediction')

    together(room, phones)
    owner = phone_of(phones, engine.s['assignments']['exactlyXtrick'])
    owner.send('predict', task='exactlyXtrick', count=1)
    owner.catch_up(stage='assistance')
    drop_and_return(room, phones, 'assistance')

    def decide_together(kind, **fields):
        together(room, phones)
        revision = engine.s['revision']
        phones[0].send('propose', proposal={'kind': kind, **fields})
        for i, p in enumerate(phones[1:], 1):
            p.catch_up(revision + i)
            p.send('confirm', yes=True)
        phones[0].catch_up(revision + 3)

    decide_together('distress', direction='left')
    together(room, phones)
    first = phones[0]
    first.send('pass_card', card=next(c for c in first.game['me']['hand'] if not c.startswith('submarine')))
    first.read(lambda p: p.game['me']['pass_locked'])
    drop_and_return(room, phones, 'passing')                         # a sealed choice is pending
    assert engine.s['pass_choices'].keys() == {first.pid} and not phones[1].game['me']['pass_locked']

    for p in phones[1:]:
        together(room, phones)
        p.send('pass_card', card=next(c for c in p.game['me']['hand'] if not c.startswith('submarine')))
        p.read(lambda q: q.game['me']['pass_locked'] or q.game['stage'] == 'before_trick')
    for p in phones:
        p.catch_up(stage='before_trick')
    together(room, phones)
    speaker = phones[0]                                              # a live exposure and a spent token
    card, opts = next(iter(speaker.game['me']['communication_options'].items()))
    revision = engine.s['revision']
    speaker.send('communicate', card=card, assertion=opts[0])
    speaker.catch_up(revision + 1)
    exposure = {'seat': speaker.pid, 'card': card, 'assertion': opts[0], 'active': True}
    drop_and_return(room, phones, 'before_trick')
    assert engine.s['exposures'] == [exposure] and engine.s['spent'] == [speaker.pid]
    assert phones[1].game['exposures'] == [exposure] and phones[1].game['sonar_spent'] == [speaker.pid]

    together(room, phones)
    leader = phone_of(phones, engine.s['turn'])
    leader.send('play_card', card=leader.game['me']['legal_cards'][0])
    leader.catch_up(stage='in_trick')
    drop_and_return(room, phones, 'in_trick')
    assert len(engine.s['trick']) == 1                               # the card on the table stayed

    room.on_table(lambda e: e._finish('failed', 'fixture'))
    for p in phones:
        p.catch_up(stage='mission_result')
    drop_and_return(room, phones, 'mission_result')
    assert engine.s['result'] == {'status': 'failed', 'reason': 'fixture'}


def test_two_phones_asking_for_the_last_shared_token_at_once_spend_it_once(table):
    room, phones = table
    engine = room.session.engine

    def begun_with_one_shared_token(e):
        allocated(e)
        decide(e, e.s['humans'][0], 'begin')
        e.s['communication'], e.s['shared'] = 'rapture', 1
    room.on_table(begun_with_one_shared_token)
    for p in phones:
        p.catch_up(stage='before_trick')
    revision = together(room, phones)
    rivals = phones[:2]
    for p in rivals:                                                 # both built at one revision
        card, opts = next(iter(p.game['me']['communication_options'].items()))
        p.send('communicate', card=card, assertion=opts[0])
    for p in phones:
        p.catch_up(revision + 1)
    for p in rivals:                                                 # one of them is refused
        try:
            p.read(lambda q: any(f.get('kind') == 'invalid' for f in q.fx), 2)
        except AssertionError:
            pass
    refusals = [f for p in rivals for f in p.fx if f.get('kind') == 'invalid']
    assert [f['code'] for f in refusals] == ['stale']
    assert engine.s['shared'] == 0 and len(engine.s['exposures']) == 1
    assert engine.s['revision'] == revision + 1
    loser = next(p for p in rivals if any(f.get('kind') == 'invalid' for f in p.fx))
    loser.catch_up(revision + 1)
    assert loser.game['shared_sonar'] == 0 and loser.game['me']['communication_options'] == {}


# ---- T43 the reason shown for an unavailable control is the server's own -----------------------

def test_the_reasons_the_view_gives_for_an_unplayable_card_are_the_servers_rejections():
    e = playing()
    idle = next(q for q in e.s['humans'] if q != e.s['turn'])
    with pytest.raises(Invalid) as refused:
        act(e, idle, 'play_card', card=e.playable(idle)[0])
    assert e.view(idle)['me']['play_reason'] == str(refused.value) == 'It is another crew member’s turn.'
    assert e.view(e.s['turn'])['me']['play_reason'] is None
    e.s['away'] = [idle]
    with pytest.raises(Invalid) as refused:
        act(e, e.s['turn'], 'play_card', card=e.playable(e.s['turn'])[0])
    assert e.view(e.s['turn'])['me']['play_reason'] == str(refused.value) == 'Waiting for the crew to reconnect.'


DEFECT = dict(strict=True, raises=(AssertionError, Invalid))


@pytest.mark.xfail(reason='E-D8 / AVR-263: before play begins the view gives a reason that is not the server’s rejection', **DEFECT)
def test_defect_the_reason_shown_before_play_begins_is_the_servers_rejection():
    e = allocated(Engine(['p0', 'p1', 'p2'], random.Random(4)))
    assert e.s['phase'] == 'assistance'
    captain = e.s['captain']
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        act(e, captain, 'play_card', card=e.playable(captain)[0])
    assert refused.value.code == 'phase' and e.snapshot() == before  # refused either way
    assert e.view(captain)['me']['legal_cards'] == []
    assert e.view(captain)['me']['play_reason'] == str(refused.value)


# ---- E-M42 mission 32 played through -----------------------------------------------------------

@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_mission_thirty_two_deals_its_four_named_tasks_and_plays_to_a_result(n):
    fixed = ['0tricks', 'exactly3trickInARow', '2tricksInARow', 'firstAndLastTrick']
    outcomes = set()
    for seed in range(12):
        e = Engine([f'p{i}' for i in range(n)], random.Random(seed), 32)
        seats, captain = e.s['seats'], e.s['captain']
        assert e.s['selected'] == fixed and e.s['pool'] == fixed and e.s['mission']['allocation'] == 'normal'
        assert e.s['deck'] == [] and e.s['used'] == []               # nothing is drawn from the task deck
        ring = seats[seats.index(captain):] + seats[:seats.index(captain)]
        order = []
        while e.s['pool']:
            seat = e.selector()
            order.append(seat)
            assert not e.view(e.controller(seat))['me']['may_pass_task'] or len(seats) > 4
            act(e, e.controller(seat), 'choose_task', task=e.s['pool'][0])
        assert order == [ring[i % len(ring)] for i in range(4)] and e.s['phase'] == 'assistance'
        decide(e, e.s['humans'][0], 'begin')
        while not e.s['result']:
            q = e.s['turn']
            act(e, e.controller(q), 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
            e.check()
        status = e.s['result']['status']
        outcomes.add(status)
        progress = e.s['progress']
        assert set(progress) == set(fixed) and status in ('success', 'failed')
        assert (status == 'success') == all(v == 'satisfied' for v in progress.values())
        assert (status == 'failed') == any(v == 'failed' for v in progress.values())
        assert set(fixed) <= set(e.s['used'])                        # and they are used up afterwards
    assert 'failed' in outcomes
