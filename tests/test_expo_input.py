"""EXPO malformed input (AVR-264): a crew-decision field of the wrong type is refused.

Before this, the `task` of an `assign` proposal was never read in missions 6, 10 and 13, so any
JSON value was stored in the pending decision and sent to every viewer. A value nested a few
hundred lists deep then made every view, snapshot and command raise: one seated player could
freeze the table.
"""
import json
import random

import pytest

from games.expo.engine import Engine, Invalid
from games.expo.game import ExpoSession

from test_expo import command


def nested(depth):
    value = []
    for _ in range(depth):
        value = [value]
    return value


WRONG = {'a list': [], 'nested 50 deep': nested(50), 'nested 500 deep': nested(500), 'a number': 5,
         'a fraction': 1.5, 'null': None, 'an object': {'a': 1}, 'true': True}
MISSION = {'normal': 1, 'one': 6, 'captain_one': 10, 'captain_one, timed': 13, 'volunteer': 16,
           'free': 17, 'skip_captain': 25}


def table(mid, seed=9):
    e = Engine(['a', 'b', 'c'], random.Random(seed), mid)
    return e, e.s['captain']                     # the captain may propose in every mode


def frozen(e):
    return json.dumps(e.snapshot(), sort_keys=True), e.rng.getstate()


def refused(e, actor, proposal, code='payload'):
    before = frozen(e)
    with pytest.raises(Invalid) as bad:
        e.apply(actor, command(e, actor, 'propose', proposal=proposal), 100)
    assert bad.value.code == code
    assert frozen(e) == before                   # nothing stored, nothing remembered, no revision
    assert e.s['proposal'] is None
    for q in e.s['humans']:
        e.view(q)
    e.check()


@pytest.mark.parametrize('mode', MISSION)
@pytest.mark.parametrize('field', ['task', 'owner'])
@pytest.mark.parametrize('wrong', WRONG)
def test_an_assign_field_of_the_wrong_type_is_refused_in_every_allocation_mode(mode, field, wrong):
    e, cap = table(MISSION[mode])
    proposal = {'kind': 'assign', 'owner': cap, 'task': e.s['pool'][0] if mode == 'free' else 'all'}
    proposal[field] = WRONG[wrong]
    refused(e, cap, proposal)


@pytest.mark.parametrize('kind,field,wrong', [
    (kind, field, wrong)
    for kind, field in (('distress', 'direction'), ('next', 'mission'), ('retry', 'keep'))
    for wrong in list(WRONG) + ['a string']
    if (field, wrong) not in (('direction', 'a string'), ('keep', 'true'), ('mission', 'a number'))])
def test_every_other_decision_field_of_the_wrong_type_is_refused(kind, field, wrong):
    e, cap = table(1)
    refused(e, cap, {'kind': kind, field: dict(WRONG, **{'a string': '2'})[wrong]})


@pytest.mark.parametrize('mode', ['one', 'captain_one', 'captain_one, timed'])
@pytest.mark.parametrize('task', ['', 'blue4', 'everything', 'x' * 3000])
def test_where_all_tasks_go_together_the_task_field_is_the_word_all(mode, task):
    # The client sends "all" in these modes. Any other string was stored and sent to every viewer.
    e, cap = table(MISSION[mode])
    refused(e, cap, {'kind': 'assign', 'owner': cap, 'task': task}, code='task')


@pytest.mark.parametrize('mid', [6, 10, 13])
def test_the_request_that_froze_the_table_is_refused_and_the_table_plays_on(mid):
    s = ExpoSession(random.Random(9))
    tokens = ['human-0', 'human-1', 'human-2']
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.settings['mission'] = mid
    s.start(tokens[0])
    s.tick(s.gen)
    e = s.engine
    seat = {s.players[t].pid: t for t in tokens}
    cap = e.s['captain']
    other = next(q for q in e.s['humans'] if q != cap)
    before = frozen(e)
    for depth in (500, 900):
        bad = command(e, cap, 'propose', proposal={'kind': 'assign', 'owner': other, 'task': nested(depth)})
        assert len(json.dumps(bad)) < 4096                           # it fits in one socket message
        fx = s.game_action(seat[cap], bad)
        assert [f['code'] for f in fx] == ['payload']
    assert frozen(e) == before and e.s['proposal'] is None
    for t in tokens:                                                 # every viewer still gets a state
        assert s.state_for(t)['game']['proposal'] is None
    # Nothing is pending, so there is nothing to decline, and the real decision goes through.
    assert [f['code'] for f in s.game_action(seat[other], command(e, other, 'confirm', yes=False))] == ['vote']
    assert s.game_action(seat[cap], command(e, cap, 'propose',
                                            proposal={'kind': 'assign', 'owner': other, 'task': 'all'})) == []
    assert s.game_action(seat[other], command(e, other, 'confirm', yes=True)) == []
    for q in e.s['humans']:
        if e.s['proposal'] and q not in (cap, other):
            assert s.game_action(seat[q], command(e, q, 'confirm', yes=True)) == []
    assert e.s['pool'] == [] and set(e.s['assignments'].values()) == {other}
    for t in tokens:
        s.state_for(t)
