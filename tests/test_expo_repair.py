"""EXPO task repair (AVR-270): the replacement for a conflicting task may come from the used pile.

A draw that holds an unavoidable task combination exchanges the conflicting task for another of
the same difficulty. The exchange looked in the task deck only. Late in a long table the deck is
small and held no such task, so the next mission was refused with `feasibility` every time,
although the used pile held one.
"""
import random

import pytest

from games.expo.content import TASKS, catalog, mission
from games.expo.engine import Engine, Invalid

from test_expo import decide

STEPS = 40


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


def walk(n, seed, steps=STEPS):
    """Finish a mission and agree on a random next one, `steps` times. Yields (step, mission)."""
    e = Engine([f'p{i}' for i in range(n)], random.Random(seed), 1)
    r = random.Random(seed)
    enabled = [m['id'] for m in catalog(n, False) if m['enabled']]
    for step in range(steps):
        e._finish('success', 't')
        piles(e)
        number = r.choice(enabled)
        try:
            decide(e, e.s['humans'][0], 'next', mission=number)
        except Invalid as x:
            raise AssertionError(f'{n} humans, seed {seed}, step {step}, mission {number}: {x.code}') from x
        assert e.s['mission']['id'] == number
        piles(e)
        e.check()
        yield step, number


@pytest.mark.parametrize('n, seed, at, number', [(2, 109, 24, 7), (4, 118, 26, 7), (5, 144, 20, 24)])
def test_the_recorded_tables_reach_the_mission_that_was_refused(n, seed, at, number):
    reached = dict(walk(n, seed, at + 1))
    assert reached[at] == number


@pytest.mark.parametrize('n', [2, 3, 4, 5])
@pytest.mark.parametrize('seed', range(150))
def test_a_long_table_is_never_refused_its_next_mission_and_keeps_its_piles_apart(n, seed):
    assert len(list(walk(n, seed))) == STEPS


def overlapping():
    """Two index tasks that share a trick, and a task of the second one's difficulty that has none."""
    crew = '3'
    index = [k for k, v in TASKS.items() if v['enabled'] and v['family'] == 'indices']
    for a in index:
        for b in index:
            if a == b or not set(TASKS[a]['params']['required']) & set(TASKS[b]['params']['required']):
                continue
            d = TASKS[b]['difficulty'][crew]
            for c, v in TASKS.items():
                if (v['enabled'] and v['family'] != 'indices' and v['difficulty'][crew] == d
                        and v['params'].get('other') != 'captain'):
                    return a, b, c
    raise AssertionError('no overlapping index tasks')


def repairable():
    a, b, c = overlapping()
    e = Engine(['a', 'b', 'c'], random.Random(1), 1)
    m = next(mission(x['id']) for x in catalog(3, False)
             if x['enabled'] and mission(x['id'])['allocation'] == 'normal')
    d = TASKS[b]['difficulty']['3']
    other = [k for k, v in TASKS.items() if v['enabled'] and k not in (a, b, c) and v['difficulty']['3'] != d]
    return e, m, a, b, c, other


def test_a_replacement_taken_from_the_used_pile_leaves_it():
    e, m, a, b, c, other = repairable()
    e.s['deck'], e.s['used'] = list(other[:5]), [other[5], c, other[6]]
    pool = e._repair_tasks([a, b], m)
    assert pool == [a, c]
    assert e.s['used'] == [other[5], other[6]]
    assert e.s['deck'] == other[:5] + [b]


def test_a_replacement_in_the_deck_is_preferred_and_the_used_pile_is_untouched():
    e, m, a, b, c, other = repairable()
    same = [k for k, v in TASKS.items() if v['enabled'] and k not in (a, b, c)
            and v['difficulty']['3'] == TASKS[b]['difficulty']['3']]
    e.s['deck'], e.s['used'] = list(other[:5]) + [c], same[:1] + [other[5]]
    pool = e._repair_tasks([a, b], m)
    assert pool == [a, c]
    assert e.s['used'] == same[:1] + [other[5]]
    assert e.s['deck'] == other[:5] + [b]


def test_no_replacement_in_either_pile_is_still_refused():
    e, m, a, b, c, other = repairable()
    e.s['deck'], e.s['used'] = list(other[:5]), [other[5]]
    with pytest.raises(Invalid) as x:
        e._repair_tasks([a, b], m)
    assert x.value.code == 'feasibility'
    assert e.s['deck'] == other[:5] and e.s['used'] == [other[5]]
