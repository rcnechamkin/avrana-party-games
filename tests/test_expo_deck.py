"""EXPO task deck (AVR-265): a task card is in one place at a time.

Mission 32 took its four named tasks without removing them from the task deck. Once the mission
ended they were in the used pile too, and when the deck was later refilled from the used pile a
task was in it twice: a later mission could deal the same task card twice.
"""
import json
import random

import pytest

from games.expo.content import BLOCKED, MISSIONS, mission
from games.expo.engine import Engine, Invalid

from test_expo import decide

FIXED = mission(32)['fixed']
LATER = [n for n in MISSIONS if n > 32 and n not in BLOCKED]


def piles(e):
    """Assert that no task is in a pile twice or in two piles, and return the piles."""
    s = e.s
    deck, used, selected = s['deck'], s['used'], s['selected']
    for name, pile in (('deck', deck), ('used', used), ('selected', selected)):
        assert len(set(pile)) == len(pile), (name, sorted(k for k in pile if pile.count(k) > 1))
    assert not set(deck) & set(used), sorted(set(deck) & set(used))
    assert not set(deck) & set(selected), sorted(set(deck) & set(selected))
    if s['result'] is None:                      # in play; once it ends its tasks are set aside
        assert not set(used) & set(selected), sorted(set(used) & set(selected))
    return deck, used, selected


def finish(e, status='success'):
    e._finish(status, 'test')
    piles(e)


def advance(e, number):
    decide(e, e.s['humans'][0], 'next', mission=number)
    assert e.s['mission']['id'] == number
    piles(e)


@pytest.mark.parametrize('seed', range(200))
def test_no_task_is_dealt_twice_in_the_missions_after_mission_thirty_two(seed):
    e = Engine(['a', 'b', 'c'], random.Random(seed), 1)
    piles(e)
    finish(e)
    advance(e, 32)
    assert e.s['selected'] == FIXED
    finish(e)
    for number in LATER:
        advance(e, number)
        finish(e)


@pytest.mark.parametrize('n', [2, 4, 5])
@pytest.mark.parametrize('seed', range(20))
def test_no_task_is_dealt_twice_for_any_crew_size(n, seed):
    e = Engine([f'p{i}' for i in range(n)], random.Random(seed), 1)
    finish(e)
    advance(e, 32)
    finish(e)
    for number in LATER:
        advance(e, number)
        finish(e)


@pytest.mark.parametrize('seed', range(30))
def test_retries_before_and_after_mission_thirty_two_keep_every_task_in_one_place(seed):
    rng = random.Random(seed)
    e = Engine(['a', 'b', 'c'], random.Random(seed), 1)
    for number in [32] + LATER:
        for _ in range(rng.randrange(3)):        # fail, then retry with the same or new tasks
            finish(e, 'failed')
            decide(e, e.s['humans'][0], 'retry', keep=rng.random() < 0.5)
            piles(e)
        finish(e)
        advance(e, number)
        if number == 32:
            assert e.s['selected'] == FIXED


def test_mission_thirty_two_takes_its_four_tasks_out_of_the_deck_and_the_used_pile():
    e = Engine(['a', 'b', 'c'], random.Random(16), 1)
    assert set(FIXED) & set(e.s['deck']) or set(FIXED) & set(e.s['selected'])
    finish(e)
    advance(e, 32)
    deck, used, selected = piles(e)
    assert selected == FIXED and e.s['pool'] == FIXED
    assert not set(FIXED) & set(deck) and not set(FIXED) & set(used)
    finish(e, 'failed')
    decide(e, 'a', 'retry', keep=False)          # "new tasks" on a fixed mission: the same four
    deck, used, selected = piles(e)
    assert selected == FIXED and not set(FIXED) & set(deck) and not set(FIXED) & set(used)
    finish(e, 'failed')
    decide(e, 'a', 'retry', keep=True)
    assert piles(e)[2] == FIXED


def test_a_table_that_opens_on_mission_thirty_two_deals_its_four_tasks():
    e = Engine(['a', 'b', 'c'], random.Random(3), 32)
    assert piles(e) == ([], [], FIXED)
    finish(e)
    advance(e, 33)
    assert len(set(e.s['selected'])) == len(e.s['selected'])


def test_the_reported_table_reaches_mission_forty_seven_with_distinct_tasks():
    e = Engine(['a', 'b', 'c'], random.Random(16), 1)
    finish(e)
    advance(e, 32)
    finish(e)
    for number in [n for n in LATER if n <= 47]:
        advance(e, number)
        if number < 47:
            finish(e)
    assert len(e.s['selected']) == len(set(e.s['selected']))
    crew = str(len(e.s['seats']))
    from games.expo.content import TASKS
    assert sum(TASKS[k]['difficulty'][crew] for k in set(e.s['selected'])) == e.s['mission']['target']


def corrupt(change):
    e = Engine(['a', 'b', 'c'], random.Random(5), 1)
    snap = json.loads(json.dumps(e.snapshot()))
    assert Engine.restore(snap).s['selected'] == e.s['selected']     # sound as written
    change(snap['state'])
    return snap


@pytest.mark.parametrize('case,change', [
    ('a task twice in the deck', lambda s: s['deck'].append(s['deck'][0])),
    ('a task twice in the used pile', lambda s: s['used'].extend([s['deck'].pop()] * 2)),
    ('a task in the deck and in the used pile', lambda s: s['used'].append(s['deck'][0])),
    ('a task in play and in the deck', lambda s: s['deck'].append(s['selected'][0])),
    ('a task in play and in the used pile', lambda s: s['used'].append(s['selected'][0])),
    ('a task twice in play', lambda s: (s['selected'].append(s['selected'][0]), s['pool'].append(s['pool'][0]))),
    ('a pile that is not a list of task ids', lambda s: s['deck'].append(['blue4'])),
    ('a task that does not exist in the deck', lambda s: s['deck'].append('no-such-task')),
])
def test_a_snapshot_with_a_task_in_two_places_is_refused(case, change):
    with pytest.raises(Invalid) as bad:
        Engine.restore(corrupt(change))
    assert bad.value.code == 'snapshot'
