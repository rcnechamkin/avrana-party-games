"""EXPO task repair (AVR-270): when the deck cannot supply the replacement, the used pile is recycled.

A draw that holds an unavoidable task combination exchanges the conflicting task for another of
the same difficulty. The exchange looked in the task deck only. Late in a long table the deck is
small and held no such task, so the next mission was refused with `feasibility` every time,
although the used pile held one.

Owner decision, 2026-10-05: the used pile is shuffled back into the deck and the replacement is
drawn from there, as the source game's task deck is handled. A mission's own named tasks (mission
32) are not replaced by this path.

`DeckOnly` below is the repair as it was before this change. Wherever it finds a replacement the
engine must do exactly what it did: same tasks, same piles, same random state.
"""
import json
import random

import pytest

from games.expo.content import TASKS, catalog, mission
from games.expo.engine import Engine, Invalid, require

from test_expo import decide

STEPS = 40
ENABLED = {k for k, v in TASKS.items() if v['enabled']}
FIXED = mission(32)['fixed']
COMPARISON = ['lessTricksThanCaptain', 'equalTricksThanCaptain', 'moreTricksThanCaptain']


class DeckOnly(Engine):
    """The engine with `_repair_tasks` as it was before AVR-270: the deck or nothing."""

    def _repair_tasks(self, pool, m):
        if m['allocation'] not in ('normal', 'skip_captain'):
            return pool
        crew = str(len(self.s['seats']))
        for _ in range(100):
            conflict, forced = self._index_conflict(pool, m), False
            if conflict is None:
                conflict, forced = self._captain_conflict(pool, m), True
            if conflict is None:
                return pool
            difficulty = TASKS[conflict]['difficulty'][crew]
            candidates = [k for k in self.s['deck'] if TASKS[k]['difficulty'][crew] == difficulty
                          and not (forced and TASKS[k]['params'].get('other') == 'captain')]
            require(bool(candidates), 'feasibility', 'No same-difficulty replacement is available for this setup.')
            replacement = self.rng.choice(candidates)
            self.s['deck'].remove(replacement)
            self.s['deck'].append(conflict)
            pool[pool.index(conflict)] = replacement
        raise Invalid('feasibility', 'Task combination needs a fresh task deck.')


def piles(e, whole=True):
    """Assert that every task card is in exactly one place, and return the piles.

    The deck, the used pile and the mission in play (its named tasks included, assigned or not)
    hold every enabled task once. The tasks of a mission that has ended are in the used pile and
    still shown as its tasks. `whole=False` for a table that began on mission 32, which names its
    tasks before any deck has been shuffled."""
    s = e.s
    deck, used, selected = s['deck'], s['used'], s['selected']
    for name, pile in (('deck', deck), ('used', used), ('selected', selected)):
        assert len(set(pile)) == len(pile), (name, sorted(k for k in pile if pile.count(k) > 1))
    assert not set(deck) & set(used), sorted(set(deck) & set(used))
    assert not set(deck) & set(selected), sorted(set(deck) & set(selected))
    assert set(s['pool']) | set(s['assignments']) == set(selected)
    if s['result'] is None:                      # in play; once it ends its tasks are set aside
        assert not set(used) & set(selected), sorted(set(used) & set(selected))
    else:
        assert set(selected) <= set(used)
    if whole:
        everything = set(deck) | set(used) | set(selected)
        assert everything == ENABLED, (sorted(ENABLED - everything), sorted(everything - ENABLED))
    return deck, used, selected


def humans(n):
    return [f'p{i}' for i in range(n)]


def walk(n, seed, steps=STEPS):
    """Finish a mission and agree on a random next one, `steps` times, on the engine and on the
    engine as it was. Yields (engine, step, mission, refused): `refused` when the old repair found
    no replacement in the deck. Otherwise the two tables are equal, random state included. After
    a refusal the old engine is given the new one's table and the comparison goes on."""
    e = Engine(humans(n), random.Random(seed), 1)
    old = DeckOnly(humans(n), random.Random(seed), 1)
    r = random.Random(seed)
    enabled = [m['id'] for m in catalog(n, False) if m['enabled']]
    for step in range(steps):
        e._finish('success', 't')
        old._finish('success', 't')
        piles(e)
        number = r.choice(enabled)
        try:
            decide(e, e.s['humans'][0], 'next', mission=number)
        except Invalid as x:
            raise AssertionError(f'{n} humans, seed {seed}, step {step}, mission {number}: {x.code}') from x
        assert e.s['mission']['id'] == number
        piles(e)
        e.check()
        if number == 32:
            assert e.s['selected'] == FIXED
        try:
            decide(old, old.s['humans'][0], 'next', mission=number)
            refused = False
            assert old.snapshot() == e.snapshot(), (n, seed, step, number)
        except Invalid as x:
            assert x.code == 'feasibility'
            refused = True
            old = DeckOnly.restore(e.snapshot())
        yield e, step, number, refused


def through_json(e):
    return Engine.restore(json.loads(json.dumps(e.snapshot())))


# --- the tables that were refused ----------------------------------------------------------

RECORDED = [(2, 109, 24, 7), (4, 118, 26, 7), (5, 144, 20, 24)]


@pytest.mark.parametrize('n, seed, at, number', RECORDED)
def test_the_recorded_tables_reach_the_mission_that_was_refused(n, seed, at, number):
    reached = {step: (mission_id, refused) for _, step, mission_id, refused in walk(n, seed, at + 1)}
    assert reached[at] == (number, True)
    assert not any(refused for step, (_, refused) in reached.items() if step < at)


@pytest.mark.parametrize('n, seed, at, number', RECORDED)
def test_a_table_repaired_from_the_used_pile_is_stored_restored_and_played_on_the_same(n, seed, at, number):
    e = [e for e, *_ in walk(n, seed, at + 1)][-1]
    again = through_json(e)
    assert again.snapshot() == e.snapshot()
    piles(again)
    for table in (e, again):
        table._finish('success', 't')
        decide(table, table.s['humans'][0], 'next', mission=24)
        piles(table)
    assert again.snapshot() == e.snapshot()


@pytest.mark.parametrize('n, seed, at, number', RECORDED)
def test_the_same_seed_recycles_the_used_pile_the_same_way(n, seed, at, number):
    first, second = ([e for e, *_ in walk(n, seed, at + 1)][-1].snapshot() for _ in range(2))
    assert first == second


# --- long tables: never refused, every card in one place, and unchanged where the deck sufficed --

@pytest.mark.parametrize('n', [2, 3, 4, 5])
@pytest.mark.parametrize('seed', range(25))
def test_a_long_table_is_never_refused_keeps_every_task_in_one_place_and_draws_as_before(n, seed):
    assert len(list(walk(n, seed))) == STEPS


@pytest.mark.parametrize('n', [2, 3, 4, 5])
@pytest.mark.parametrize('seed', range(5))
def test_a_long_table_with_retries_keeps_every_task_in_one_place_and_draws_as_before(n, seed):
    # As the walk above, with failed missions retried: the same tasks kept, or new ones drawn.
    e = Engine(humans(n), random.Random(seed), 1)
    old = DeckOnly(humans(n), random.Random(seed), 1)
    r = random.Random(1000 + seed)
    enabled = [m['id'] for m in catalog(n, False) if m['enabled']]
    lead = e.s['humans'][0]
    seen = set()
    for step in range(60):
        move = r.choice(['next', 'keep', 'new'])
        fields = {'mission': r.choice(enabled)} if move == 'next' else {'keep': move == 'keep'}
        kind = 'next' if move == 'next' else 'retry'
        kept = list(e.s['selected'])
        for table in (e, old):
            table._finish('success' if move == 'next' else 'failed', 't')
        piles(e)
        decide(e, lead, kind, **fields)
        piles(e)
        e.check()
        if move == 'keep':
            assert e.s['selected'] == kept
        if e.s['mission']['id'] == 32:
            assert e.s['selected'] == FIXED
        try:
            decide(old, lead, kind, **fields)
            assert old.snapshot() == e.snapshot(), (n, seed, step, move)
        except Invalid as x:
            assert x.code == 'feasibility'
            old = DeckOnly.restore(e.snapshot())
        seen.add(move)
    assert seen == {'next', 'keep', 'new'}


# --- the exchange itself -------------------------------------------------------------------

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


def repairable(cls=Engine, seed=1):
    a, b, c = overlapping()
    e = cls(['a', 'b', 'c'], random.Random(seed), 1)
    m = next(mission(x['id']) for x in catalog(3, False)
             if x['enabled'] and mission(x['id'])['allocation'] == 'normal')
    d = TASKS[b]['difficulty']['3']
    other = [k for k, v in TASKS.items() if v['enabled'] and k not in (a, b, c) and v['difficulty']['3'] != d]
    return e, m, a, b, c, other


def test_the_used_pile_is_shuffled_into_the_deck_and_the_replacement_drawn_from_it():
    e, m, a, b, c, other = repairable()
    e.s['deck'], e.s['used'] = list(other[:5]), [other[5], c, other[6]]
    pool = e._repair_tasks([a, b], m)
    assert pool == [a, c]
    assert e.s['used'] == []
    assert sorted(e.s['deck']) == sorted(other[:7] + [b])        # c left it, b went back, none twice
    assert e.s['deck'][-1] == b
    assert e.s['deck'][:-1] != other[:7]                         # shuffled, not appended in order


def test_recycling_the_used_pile_is_decided_by_the_seed_alone():
    def result(seed):
        e, m, a, b, c, other = repairable(seed=seed)
        d = TASKS[b]['difficulty']['3']
        same = [k for k, v in TASKS.items() if v['enabled'] and k not in (a, b) and v['difficulty']['3'] == d
                and v['family'] != 'indices' and v['params'].get('other') != 'captain']
        e.s['deck'], e.s['used'] = list(other[:5]), other[5:9] + same
        pool = e._repair_tasks([a, b], m)
        assert pool[0] == a and pool[1] in same
        return pool, list(e.s['deck']), e.rng.getstate()
    assert result(7) == result(7)
    assert len({result(seed)[0][1] for seed in range(40)}) > 1   # a random one of them, not the first


def test_a_replacement_in_the_deck_is_taken_as_before_and_the_used_pile_is_untouched():
    states = []
    for cls in (Engine, DeckOnly):
        e, m, a, b, c, other = repairable(cls)
        same = [k for k, v in TASKS.items() if v['enabled'] and k not in (a, b, c)
                and v['difficulty']['3'] == TASKS[b]['difficulty']['3']]
        e.s['deck'], e.s['used'] = list(other[:5]) + [c], same[:1] + [other[5]]
        pool = e._repair_tasks([a, b], m)
        assert pool == [a, c]
        assert e.s['used'] == same[:1] + [other[5]]
        assert e.s['deck'] == other[:5] + [b]
        states.append((pool, e.s['deck'], e.s['used'], e.rng.getstate()))
    assert states[0] == states[1]


def test_no_replacement_in_either_pile_is_still_refused_and_nothing_is_shuffled():
    e, m, a, b, c, other = repairable()
    e.s['deck'], e.s['used'] = list(other[:5]), [other[5]]
    before = e.rng.getstate()
    with pytest.raises(Invalid) as x:
        e._repair_tasks([a, b], m)
    assert x.value.code == 'feasibility'
    assert e.s['deck'] == other[:5] and e.s['used'] == [other[5]]
    assert e.rng.getstate() == before


def test_known_limit_a_deck_whose_only_replacements_conflict_again_is_refused_without_recycling():
    # A known limit, recorded as an open question for the owner (RECONCILIATION, AVR-270), not a
    # rule: the used pile is recycled only when the deck holds NO task of the difficulty. Here the
    # deck holds one, `firstTwoTrick`, which conflicts with `firstThreeTrick` just as `firstTrick`
    # did; the two are exchanged for each other until the repair gives up, although the used pile
    # holds ordinary tasks of that difficulty. The engine did the same before AVR-270.
    for cls in (Engine, DeckOnly):
        e = cls(['a', 'b', 'c'], random.Random(3), 1)
        e._finish('success', 't')
        done = set(e.s['selected'])
        ordinary = [k for k in sorted(ENABLED) if TASKS[k]['difficulty']['3'] == 1 and k not in done
                    and TASKS[k]['family'] != 'indices']
        two = next(k for k in sorted(ENABLED) if TASKS[k]['difficulty']['3'] == 2 and k not in done
                   and TASKS[k]['family'] != 'indices' and k not in COMPARISON)
        drawn = ['firstThreeTrick', 'firstTrick', two]               # 2 + 1 + 2: mission 5
        assert sum(TASKS[k]['difficulty']['3'] for k in drawn) == mission(5)['target']
        used = ordinary + sorted(done)
        assert len(ordinary) >= 5 and not done & set(drawn + ['firstTwoTrick'])
        deck = [k for k in sorted(ENABLED) if k not in drawn + used + ['firstTwoTrick']
                and TASKS[k]['difficulty']['3'] != 1]
        e.s['deck'] = drawn + deck + ['firstTwoTrick']
        e.s['used'] = used + [k for k in sorted(ENABLED) if k not in drawn + deck + used + ['firstTwoTrick']]
        piles(e)
        before = e.snapshot()
        with pytest.raises(Invalid) as x:
            host(e, 'next', mission=5)
        assert (x.value.code, str(x.value)) == ('feasibility', 'Task combination needs a fresh task deck.')
        assert e.snapshot() == before                # state and random state rolled back


# --- the captain's repair (C20) from the used pile, through a crew decision ---------------------

def captain_forced(cls, kind, order):
    """A three-seat table about to draw all three captain comparison tasks for mission 11 (8
    points, clockwise selection), which forces one onto the captain. The deck holds no ordinary
    task of the difficulty of the one that must go; the used pile holds them all."""
    e = cls(['a', 'b', 'c'], random.Random(5), 11 if kind == 'retry' else 1)
    e._finish('failed' if kind == 'retry' else 'success', 't')
    conflict = order[-1]
    d = TASKS[conflict]['difficulty']['3']
    done = set(e.s['selected'])
    rest = [k for k in sorted(ENABLED) if k not in order]
    deck = [k for k in rest if TASKS[k]['difficulty']['3'] != d and k not in done]
    e.s['deck'] = list(order) + deck
    e.s['used'] = [k for k in rest if k not in deck]
    piles(e)
    return e, conflict, d


def host(e, kind, **fields):
    """The Party Host's word (AVR-252): committed at once, nobody votes."""
    return e.lifecycle({'t': 'lifecycle', 'decision': {'kind': kind, **fields},
                        'attempt': e.s['attempt'], 'revision': e.s['revision']})


def go(e, kind, by='crew'):
    fields = {'keep': False} if kind == 'retry' else {'mission': 11}
    if by == 'host':
        host(e, kind, **fields)
    else:
        decide(e, 'a', kind, **fields)


@pytest.mark.parametrize('by', ['crew', 'host'])
@pytest.mark.parametrize('kind', ['next', 'retry'])
@pytest.mark.parametrize('order', [COMPARISON, COMPARISON[::-1], [COMPARISON[0], COMPARISON[2], COMPARISON[1]]])
def test_a_comparison_task_forced_on_the_captain_is_replaced_from_the_recycled_used_pile(kind, order, by):
    e, conflict, d = captain_forced(Engine, kind, order)
    assert sum(TASKS[k]['difficulty']['3'] for k in order) == mission(11)['target']
    go(e, kind, by)
    s = e.s
    assert s['mission']['id'] == 11 and s['phase'] == 'allocation'
    kept = [k for k in order if k != conflict]
    replacement = [k for k in s['selected'] if k not in kept]
    assert [k for k in s['selected'] if k in kept] == kept and len(replacement) == 1
    assert TASKS[replacement[0]]['difficulty']['3'] == d
    assert TASKS[replacement[0]]['params'].get('other') != 'captain'
    assert s['used'] == [] and conflict in s['deck']             # recycled; the replaced task went back
    piles(e)
    e.check()
    again = through_json(e)
    assert again.snapshot() == e.snapshot()
    # The table is playable: the captain has a task to take.
    assert any(e.eligible(k, s['captain']) for k in s['pool'])
    # Before the change this decision was refused, and rolled back, every time.
    old, _, _ = captain_forced(DeckOnly, kind, order)
    tasks = (list(old.s['deck']), list(old.s['used']), list(old.s['selected']))
    before = old.snapshot()
    with pytest.raises(Invalid) as x:
        go(old, kind, by)
    assert x.value.code == 'feasibility'
    assert (old.s['deck'], old.s['used'], old.s['selected']) == tasks
    if by == 'host':                             # one command: the whole table is as it was
        assert old.snapshot() == before


def test_a_comparison_task_is_never_the_replacement_for_one_forced_on_the_captain():
    # Four tasks at three seats, all three comparisons among them: the captain must take two and
    # only one is ordinary. The used pile holds one ordinary task of the difficulty; the replaced
    # comparison task is back in the deck and is not drawn again in its own place.
    ordinary = [k for k in sorted(ENABLED) if TASKS[k]['difficulty']['3'] == 2 and k not in COMPARISON]
    filler = [k for k in sorted(ENABLED) if TASKS[k]['difficulty']['3'] not in (2, 4)]
    for seed in range(30):
        e = Engine(['a', 'b', 'c'], random.Random(seed), 1)
        e.s['deck'], e.s['used'] = filler[1:6], [filler[6], ordinary[0], filler[7]]
        out = e._repair_tasks([filler[0]] + COMPARISON, mission(11))
        assert out == [filler[0], COMPARISON[0], COMPARISON[1], ordinary[0]]
        assert e.s['used'] == [] and COMPARISON[2] in e.s['deck']


# --- a mission's own named tasks stay as they are ----------------------------------------------

@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_the_named_tasks_of_mission_thirty_two_are_never_looked_at_for_repair(n, monkeypatch):
    def refuse(self, pool, m):
        assert not m.get('fixed'), 'the repair examined a mission with named tasks'
        return None
    monkeypatch.setattr(Engine, '_index_conflict', refuse)
    monkeypatch.setattr(Engine, '_captain_conflict', refuse)
    for seed in range(10):
        e = Engine(humans(n), random.Random(seed), 32)
        assert e.s['selected'] == FIXED
        piles(e, whole=False)
        for keep in (False, True):
            e._finish('failed', 't')
            decide(e, e.s['humans'][0], 'retry', keep=keep)
            assert e.s['selected'] == FIXED
            piles(e, whole=False)


def test_named_tasks_are_not_exchanged_even_if_they_would_make_a_forced_combination():
    # No mission names such tasks today. If one did, the generic exchange still leaves them alone:
    # nothing is replaced, no pile is touched and no random number is drawn.
    e, m, a, b, c, other = repairable()
    named = dict(m, fixed=[a, b])
    e.s['deck'], e.s['used'] = list(other[:5]) + [c], [other[5]]
    assert e._index_conflict([a, b], m) == b                     # an ordinary draw would be repaired
    before = e.rng.getstate()
    assert e._repair_tasks([a, b], named) == [a, b]
    assert e.s['deck'] == other[:5] + [c] and e.s['used'] == [other[5]]
    assert e.rng.getstate() == before


@pytest.mark.parametrize('n, seed, at, number', RECORDED)
def test_mission_thirty_two_keeps_its_tasks_out_of_a_recycled_pile(n, seed, at, number):
    # The table that recycles its used pile at `at`, then plays mission 32 and the mission that
    # needed the recycling again: the four named tasks are the mission's while it is in play
    # (never in the deck or the used pile, so never a replacement), and ordinary cards afterwards.
    e = [e for e, *_ in walk(n, seed, at + 1)][-1]
    lead = e.s['humans'][0]
    e._finish('success', 't')
    decide(e, lead, 'next', mission=32)
    assert e.s['selected'] == FIXED
    assert not set(FIXED) & (set(e.s['deck']) | set(e.s['used']))
    piles(e)
    e._finish('failed', 't')
    decide(e, lead, 'retry', keep=False)
    assert e.s['selected'] == FIXED
    assert not set(FIXED) & (set(e.s['deck']) | set(e.s['used']))
    piles(e)
    e._finish('success', 't')
    assert set(FIXED) <= set(e.s['used'])
    for _ in range(6):
        decide(e, lead, 'next', mission=number)
        piles(e)
        e.check()
        e._finish('success', 't')
