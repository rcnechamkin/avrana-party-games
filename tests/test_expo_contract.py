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

from test_expo import act, allocated, command, decide, place, playing, session, task_state

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
        e.s['deck'] = [k for k in e.s['deck'] if k not in ('black1', '2black')]   # kept tasks are in play
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
    place(e)
    with pytest.raises(Invalid):
        act(e, other, 'propose', proposal={'kind': 'assign', 'owner': other, 'task': 'all'})
    act(e, e.s['captain'], 'propose', proposal={'kind': 'assign', 'owner': e.s['captain'], 'task': 'all'})
    assert not e.s['before_first_only'] and set(e.s['assignments'].values()) == {e.s['captain']}


# ---- AVR-251: in missions 10 and 13 the captain decides, only the recipient consents (Q8, P09) ---
# L M10 and M13: the captain assumes all tasks or passes them to a willing crew member. Nobody
# else has a say. Every other crew decision still needs every seated human.

def captain_one(humans=('a', 'b', 'c'), mid=10, pool=('blue4',), seed=9):
    """A `captain_one` table at allocation: the engine, the captain and the other humans."""
    e = Engine(list(humans), random.Random(seed), mid)
    e.s['pool'] = list(pool); e.s['selected'] = list(pool)
    place(e)
    cap = e.s['captain']
    return e, cap, [q for q in e.s['humans'] if q != cap]


def offer(e, actor, owner):
    act(e, actor, 'propose', proposal={'kind': 'assign', 'owner': owner, 'task': 'all'})


@pytest.mark.parametrize('mid', [10, 13])
@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_the_captain_keeping_the_tasks_takes_effect_in_the_same_command(mid, n):
    e, cap, others = captain_one([f'p{i}' for i in range(n)], mid, ('blue4', 'green6'))
    revision = e.s['revision']
    offer(e, cap, cap)
    assert e.s['proposal'] is None and e.s['revision'] == revision + 1
    assert e.s['assignments'] == {'blue4': cap, 'green6': cap} and e.s['pool'] == []
    assert e.s['phase'] == 'assistance' and not e.s['before_first_only']
    for q in others:                                                 # nobody is asked, nobody can undo it
        for yes in (True, False):
            before = e.snapshot()
            with pytest.raises(Invalid) as refused:
                act(e, q, 'confirm', yes=yes)
            assert refused.value.code == 'vote' and e.snapshot() == before


@pytest.mark.parametrize('mid', [10, 13])
def test_an_offer_is_accepted_by_the_recipient_alone(mid):
    e, cap, (target, third) = captain_one(mid=mid)
    offer(e, cap, target)
    assert e.s['proposal'] == {'payload': {'kind': 'assign', 'owner': target, 'task': 'all'},
                               'votes': [cap], 'recipient': target}
    assert e.s['assignments'] == {} and e.s['pool'] == ['blue4'] and e.s['phase'] == 'allocation'
    assert all(e.view(v)['proposal']['recipient'] == target for v in (cap, target, third, None))
    act(e, target, 'confirm', yes=True)                              # the third player never answers
    assert e.s['proposal'] is None and e.s['assignments'] == {'blue4': target}
    assert e.s['before_first_only'] and e.s['phase'] == 'assistance'


@pytest.mark.parametrize('yes', [True, False])
def test_a_third_player_can_neither_confirm_nor_decline_an_offer(yes):
    e, cap, others = captain_one(('a', 'b', 'c', 'd'))
    target = others[0]
    offer(e, cap, target)
    before = e.snapshot()
    for bystander in [q for q in e.s['humans'] if q not in (cap, target)] + [cap]:
        with pytest.raises(Invalid) as refused:                     # the captain cannot answer either
            act(e, bystander, 'confirm', yes=yes)
        assert refused.value.code == 'vote'
    assert e.snapshot() == before and e.s['proposal']['recipient'] == target
    act(e, target, 'confirm', yes=True)
    assert e.s['assignments'] == {'blue4': target}


def test_a_declined_offer_returns_to_the_captain_with_the_pool_intact():
    e, cap, (target, third) = captain_one(pool=('blue4', 'green6'))
    offer(e, cap, target)
    act(e, target, 'confirm', yes=False)
    assert e.s['proposal'] is None and e.s['pool'] == ['blue4', 'green6'] and e.s['assignments'] == {}
    assert e.s['phase'] == 'allocation' and not e.s['before_first_only'] and e.s['progress'] == {}
    offer(e, cap, third)                                             # the captain chooses again
    assert e.s['proposal']['recipient'] == third
    act(e, third, 'confirm', yes=False)
    offer(e, cap, cap)                                               # or keeps them after all
    assert set(e.s['assignments'].values()) == {cap} and not e.s['before_first_only']


def test_tonoja_as_recipient_takes_effect_at_once_because_the_captain_decides_for_it():
    e, cap, (other,) = captain_one(('a', 'b'), pool=('blue4', 'green6'))
    offer(e, cap, 'tonoja')
    assert e.s['proposal'] is None and set(e.s['assignments'].values()) == {'tonoja'}
    assert e.s['before_first_only'] and e.s['phase'] == 'assistance'  # handed over: sonar rule applies
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:
        act(e, other, 'confirm', yes=False)
    assert refused.value.code == 'vote' and e.snapshot() == before
    e, cap, (other,) = captain_one(('a', 'b'))                       # the other human is asked alone
    offer(e, cap, other)
    assert e.s['proposal']['recipient'] == other
    act(e, other, 'confirm', yes=True)
    assert e.s['assignments'] == {'blue4': other}


@pytest.mark.parametrize('humans', [('a', 'b'), ('a', 'b', 'c')])
def test_a_non_captain_still_cannot_offer_or_keep_the_tasks(humans):
    e, cap, others = captain_one(humans)
    before = e.snapshot()
    for owner in e.s['seats']:
        with pytest.raises(Invalid) as refused:
            offer(e, others[0], owner)
        assert refused.value.code == 'captain'
    assert e.snapshot() == before


def test_the_captain_comparison_rule_still_binds_the_captains_own_choice():
    e, cap, (target, third) = captain_one(pool=('blue4', 'moreTricksThanCaptain'))
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # the captain may not own it
        offer(e, cap, cap)
    assert refused.value.code == 'task' and e.snapshot() == before
    with pytest.raises(Invalid) as refused:
        offer(e, cap, 'nobody')
    assert refused.value.code == 'owner' and e.snapshot() == before
    offer(e, cap, target)
    act(e, target, 'confirm', yes=True)
    assert set(e.s['assignments'].values()) == {target}


def test_a_handed_over_mission_still_limits_sonar_to_before_the_first_trick():
    e, cap, (target, third) = captain_one()
    offer(e, cap, target)
    act(e, target, 'confirm', yes=True)
    decide(e, cap, 'begin')
    assert e.communication_options(third)                            # before the first trick: allowed
    play_trick(e)
    assert all(e.communication_options(q) == {} for q in e.s['humans'])
    e, cap, _ = captain_one()                                        # kept: the usual sonar rule
    offer(e, cap, cap)
    decide(e, cap, 'begin')
    play_trick(e)
    assert any(e.communication_options(q) for q in e.s['humans'])


def test_a_pending_offer_survives_a_snapshot_and_blocks_other_commands():
    e, cap, (target, third) = captain_one()
    offer(e, cap, target)
    restored = Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert restored.s['proposal']['recipient'] == target
    before = restored.snapshot()
    with pytest.raises(Invalid) as refused:                         # no second decision meanwhile
        act(restored, third, 'propose', proposal={'kind': 'end'})
    assert refused.value.code == 'vote' and restored.snapshot() == before
    act(restored, target, 'confirm', yes=True)
    assert restored.s['assignments'] == {'blue4': target}


def test_every_other_crew_decision_still_needs_every_seated_human():
    e = Engine(['a', 'b', 'c'], random.Random(9), 6)                 # `one`: the crew decides together
    e.s['pool'] = ['blue4']; e.s['selected'] = ['blue4']
    place(e)
    act(e, 'a', 'propose', proposal={'kind': 'assign', 'owner': 'b', 'task': 'all'})
    assert 'recipient' not in e.s['proposal']
    act(e, 'b', 'confirm', yes=True)
    assert e.s['proposal']['votes'] == ['a', 'b'] and e.s['assignments'] == {}
    act(e, 'c', 'confirm', yes=False)                                # anyone may still decline
    assert e.s['proposal'] is None and e.s['pool'] == ['blue4']
    e, cap, (target, third) = captain_one()                          # begin in mission 10 is unchanged
    offer(e, cap, cap)
    act(e, cap, 'propose', proposal={'kind': 'begin'})
    act(e, target, 'confirm', yes=True)
    assert e.s['phase'] == 'assistance' and 'recipient' not in e.s['proposal']
    act(e, third, 'confirm', yes=True)
    assert e.s['phase'] == 'before_trick'


@pytest.mark.parametrize('mid', [6, 17])
def test_collective_and_free_allocation_refuse_a_captain_comparison_task_for_the_captain(mid):
    e = Engine(['a', 'b', 'c'], random.Random(9), mid)
    e.s['pool'] = ['moreTricksThanCaptain']; e.s['selected'] = list(e.s['pool'])
    place(e)
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


def test_two_humans_cannot_use_distress_or_volunteer_missions():
    # Still deferred by the owner decision Q6 (C11): the supplied rules do not say how Tonoja
    # passes or receives a distress card, or how it answers a volunteer question.
    for mid in (1, 11):                                              # distress stays off everywhere
        e = allocated(Engine(['a', 'b'], random.Random(4), mid))
        before = e.snapshot()
        with pytest.raises(Invalid) as refused:
            act(e, 'a', 'propose', proposal={'kind': 'distress', 'direction': 'left'})
        assert refused.value.code == 'distress' and e.snapshot() == before
    for timed in (False, True):
        with pytest.raises(Invalid) as refused:
            Engine(['a', 'b'], random.Random(1), 16, timed)
        assert refused.value.code == 'C11'
        off = {m['id']: m['reason'] for m in catalog(2, timed) if not m['enabled'] and m['id'] not in content.BLOCKED}
        assert list(off) == [16] and off[16].startswith('C11')


# ---- AVR-250: two humans and Tonoja share one sonar token (C11, owner decision Q6) -------------
# Tonoja is the third crew seat, so the shared pool of "seats minus two" holds one token. Only the
# two humans may spend it; Tonoja never communicates.

SHARED_SONAR_FOR_TWO = (11, 21, 22, 23, 24, 25, 27)


def two_humans(mid=11, seed=4, mode=None):
    """Two humans and Tonoja at the first trick boundary; `mode` picks a terrain draw by seed."""
    while True:
        e = Engine(['a', 'b'], random.Random(seed), mid)
        if mode is None or e.s['communication'] == mode:
            break
        seed += 1
    allocated(e)
    decide(e, 'a', 'begin')
    return e


def test_the_shared_sonar_and_terrain_missions_are_exactly_the_ones_opened_to_two_players():
    wanted = [n for n in range(1, 51) if n not in content.BLOCKED
              and content.mission(n)['communication'] in ('rapture', 'terrain')]
    assert tuple(wanted) == SHARED_SONAR_FOR_TWO


@pytest.mark.parametrize('mid', SHARED_SONAR_FOR_TWO)
def test_two_humans_can_prepare_every_shared_sonar_and_terrain_mission(mid):
    choice = next(m for m in catalog(2) if m['id'] == mid)
    assert choice == {'id': mid, 'enabled': True, 'reason': None}
    e = Engine(['a', 'b'], random.Random(mid), mid)
    assert e.s['seats'].count('tonoja') == 1 and len(e.s['seats']) == 3 and e.s['shared'] == 1
    assert e.s['mission'] == content.mission(mid)                    # the same mission as for 3 to 5
    e.check()


def test_a_two_player_table_starts_a_shared_sonar_mission_and_still_refuses_the_volunteer_mission():
    s = ExpoSession(random.Random(4))
    for t in ('human-0', 'human-1'):
        s.join(t, t)
        s.set_ready(t, True)
    s.settings['mission'] = 16
    refusal = s.start('human-0')
    assert s.engine is None and refusal[0]['msg'].startswith('C11')
    s.settings['mission'] = 11
    s.start('human-0')
    s.tick(s.gen)
    assert s.engine.s['mission']['id'] == 11 and s.engine.s['seats'].count('tonoja') == 1
    assert s.game_state('human-0')['shared_sonar'] == 1


def test_two_humans_on_mission_eleven_begin_with_exactly_one_shared_token():
    e = two_humans()
    assert e.s['communication'] == 'rapture' and e.s['shared'] == 1 and e.s['spent'] == []
    for viewer in ('a', 'b', None):
        assert e.view(viewer)['shared_sonar'] == 1
    assert e.communication_options('a') and e.communication_options('b')


@pytest.mark.parametrize('spender', ['a', 'b'])
def test_either_human_may_spend_the_shared_token_and_then_nobody_can_communicate(spender):
    e = two_humans()
    other = 'b' if spender == 'a' else 'a'
    card, opts = next(iter(e.communication_options(spender).items()))
    act(e, spender, 'communicate', card=card, assertion=opts[0])
    assert e.s['shared'] == 0 and e.s['spent'] == [] and len(e.s['exposures']) == 1
    assert e.communication_options(spender) == {} == e.communication_options(other)
    assert all(e.view(v)['shared_sonar'] == 0 for v in ('a', 'b', None))
    before = e.snapshot()
    for actor in (other, spender):
        c = next(c for c in e.playable(actor) if c != card and assertions(e.playable(actor), c))
        with pytest.raises(Invalid) as refused:
            act(e, actor, 'communicate', card=c, assertion=assertions(e.playable(actor), c)[0])
        assert refused.value.code == 'communication'
    assert e.snapshot() == before                                   # refusals changed nothing
    play_trick(e)                                                   # and the pool stays empty
    assert e.s['shared'] == 0 and e.communication_options(other) == {}


def test_tonoja_never_communicates_and_the_captain_cannot_communicate_for_it():
    e = two_humans()
    captain = e.s['captain']
    assert e.communication_options('tonoja') == {} and e.view('tonoja')['me'] is None
    shown = next(c for c in e.playable('tonoja') if assertions(e.playable('tonoja'), c))
    declaration = assertions(e.playable('tonoja'), shown)[0]
    before = e.snapshot()
    with pytest.raises(Invalid) as refused:                         # Tonoja is not an actor
        e.apply('tonoja', command(e, 'tonoja', 'communicate', card=shown, assertion=declaration), 100)
    assert refused.value.code == 'actor'
    with pytest.raises(Invalid) as refused:                         # the captain plays Tonoja's
        act(e, captain, 'communicate', card=shown, assertion=declaration)   # cards, never shows them
    assert refused.value.code == 'communication'
    assert e.snapshot() == before and e.s['shared'] == 1
    assert all(shown not in e.communication_options(q) for q in e.s['humans'])
    assert not any(x['seat'] == 'tonoja' for x in e.s['exposures'])


@pytest.mark.parametrize('card,assertion', [('blue:99', 'highest'), ('submarine:4', 'highest'),
                                            (None, 'middle'), (None, 'wrong')])
def test_an_invalid_shared_sonar_request_from_two_players_is_transactional(card, assertion):
    e = two_humans()
    actor = e.s['captain']
    real, opts = next(iter(e.communication_options(actor).items()))
    if assertion == 'wrong':                                         # a real card, an untrue claim
        assertion = next(a for a in ('highest', 'only', 'lowest') if a not in opts)
    before, rng = e.snapshot(), e.rng.getstate()
    with pytest.raises(Invalid) as refused:
        act(e, actor, 'communicate', card=card or real, assertion=assertion)
    assert refused.value.code == 'communication'
    assert e.snapshot() == before and e.rng.getstate() == rng and e.s['shared'] == 1
    act(e, actor, 'communicate', card=real, assertion=opts[0])       # the token was not consumed
    assert e.s['shared'] == 0


@pytest.mark.parametrize('n', [3, 4, 5])
def test_the_shared_pool_for_three_to_five_players_is_unchanged(n):
    e = playing(n=n, mid=11)
    assert e.s['communication'] == 'rapture' and e.s['shared'] == n - 2 and 'tonoja' not in e.s['seats']
    for _ in range(n - 2):                                           # one player may use several
        card, opts = next(iter(e.communication_options('p0').items()))
        act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    assert e.s['shared'] == 0 and e.s['spent'] == []
    assert all(e.communication_options(q) == {} for q in e.s['humans'])
    assert not next(m for m in catalog(n) if m['id'] == 11)['reason']


def test_personal_sonar_for_two_players_is_unchanged_outside_shared_sonar():
    e = playing(n=2)                                                 # mission 1, normal sonar
    assert e.s['communication'] == 'normal' and e.view('p0')['shared_sonar'] is None
    card, opts = next(iter(e.communication_options('p0').items()))
    act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    assert e.s['spent'] == ['p0'] and e.s['shared'] == 1             # the pool is not touched
    assert e.communication_options('p0') == {} and e.communication_options('p1')


def test_terrain_for_two_players_reaches_every_mode_with_the_matching_resource():
    seen = set()
    for seed in range(60):
        e = Engine(['a', 'b'], random.Random(seed), 24)
        assert e.s['communication'] == ['normal', 'currents', 'rapture'][(rank(e.s['terrain']) - 1) // 3]
        seen.add(e.s['communication'])
        e.check()
    assert seen == {'normal', 'currents', 'rapture'}
    e = two_humans(24, mode='rapture')
    card, opts = next(iter(e.communication_options('a').items()))
    act(e, 'a', 'communicate', card=card, assertion=opts[0])
    assert e.s['shared'] == 0 and e.communication_options('b') == {}
    e = two_humans(24, mode='normal')                                # personal tokens, one each
    card, opts = next(iter(e.communication_options('a').items()))
    act(e, 'a', 'communicate', card=card, assertion=opts[0])
    assert e.s['spent'] == ['a'] and e.communication_options('b')


def test_two_player_shared_sonar_views_stay_private():
    e = two_humans()
    card, opts = next(iter(e.communication_options('a').items()))
    act(e, 'a', 'communicate', card=card, assertion=opts[0])
    covered = {c['covered'] for c in e.s['columns']}
    for viewer in ('b', None, 'tonoja', 'stranger'):
        view = e.view(viewer)
        assert view['exposures'] == [{'seat': 'a', 'card': card, 'assertion': opts[0], 'active': True}]
        text = json.dumps(view)
        assert 'hands' not in view and 'columns' not in view and 'deck' not in view
        hidden = (set(e.s['hands']['a']) - {card}) | covered
        if viewer != 'b':
            hidden |= set(e.s['hands']['b'])
            assert view['me'] is None
        assert not [c for c in hidden if '"%s"' % c in text], viewer
    e = two_humans(24, mode='currents')                              # terrain can draw currents
    card, opts = next(iter(e.communication_options('a').items()))
    act(e, 'a', 'communicate', card=card, assertion=opts[0])
    assert e.view('a')['exposures'][0]['assertion'] == opts[0]
    assert all('assertion' not in e.view(v)['exposures'][0] for v in ('b', None, 'tonoja'))


# ---- AVR-250: what the existing mission rules imply with Tonoja as the third seat --------------
# These pin current behaviour. Nothing here is a new rule.

def test_mission_twenty_one_counts_tonoja_in_the_balance_of_color_ones():
    e = two_humans(21)
    won = lambda i, seat, cards: trick(i, seat, cards, seats=e.s['seats'])
    e.s['history'] = [won(1, 'tonoja', ['blue:1', 'submarine:1', 'pink:5'])]
    e._outcome()
    assert e.s['result'] is None                                     # Tonoja one ahead is legal
    e.s['history'].append(won(2, 'tonoja', ['green:1', 'green:3', 'green:5']))
    e._outcome()                                                     # Tonoja two ahead of a human
    assert e.s['result'] == {'status': 'failed', 'reason': 'A crew member has captured two more 1s than another.'}
    e = two_humans(21)
    e.s['history'] = [won(1, 'a', ['blue:1', 'blue:2', 'blue:3']), won(2, 'b', ['green:1', 'green:2', 'green:3'])]
    e._outcome()
    assert e.s['result'] is None                                     # 1, 1 and Tonoja 0
    e.s['history'].append(won(3, 'a', ['pink:1', 'pink:2', 'pink:3']))
    e._outcome()                                                     # a human two ahead of Tonoja
    assert e.s['result']['status'] == 'failed'


def test_mission_twenty_three_treats_tonoja_as_a_possible_first_winner():
    e = two_humans(23)
    assert e.communication_options('a') == {} == e.communication_options('b')   # not before trick 2
    won = lambda i, seat: {'index': i, 'leader': seat, 'winner': seat, 'plays': []}
    e.s['history'] = [won(1, 'tonoja'), won(2, 'tonoja'), won(3, 'a')]
    e._outcome()
    assert e.s['result'] is None                                     # Tonoja 2, a human 1
    e.s['history'].append(won(4, 'a'))
    e._outcome()                                                     # a human draws level with Tonoja
    assert e.s['result'] == {'status': 'failed',
                             'reason': 'The first trick winner must always have strictly more tricks.'}
    e = two_humans(23)
    e.s['history'] = [won(1, 'a'), won(2, 'a'), won(3, 'tonoja'), won(4, 'tonoja')]
    e._outcome()                                                     # Tonoja draws level with a human
    assert e.s['result']['status'] == 'failed'


def test_mission_twenty_five_with_tonoja_the_captain_takes_no_task_and_chooses_tonojas():
    for seed in range(12):
        e = Engine(['a', 'b'], random.Random(seed), 25)
        captain = e.s['captain']
        other = next(q for q in e.s['humans'] if q != captain)
        after = e.s['seats'][(e.s['seats'].index(captain) + 1) % 3]
        assert set(e.s['allocation_ring']) == {'tonoja', other} and e.s['allocation_ring'][0] == after
        while e.s['pool']:
            seat = e.selector()
            assert seat != captain and e.view(captain)['selector'] == seat
            task = next(k for k in e.s['pool'] if e.eligible(k, seat))
            if seat == 'tonoja':                                     # only the captain picks for it
                before = e.snapshot()
                with pytest.raises(Invalid) as refused:
                    act(e, other, 'choose_task', task=task)
                assert refused.value.code == 'turn' and e.snapshot() == before
                assert e.view(captain)['controller'] == captain
            act(e, e.controller(seat), 'choose_task', task=task)
        owners = set(e.s['assignments'].values())
        assert captain not in owners and owners <= {'tonoja', other}
        assert e.s['leader'] == e.s['turn'] == captain               # the captain still opens


def test_mission_twenty_seven_with_tonoja_holding_yellow_five():
    # Tonoja has fourteen cards and thirteen tricks. No rule redeals for yellow 5, so it may be
    # dealt to Tonoja, even face down, and it may end as the card Tonoja never plays.
    where = set()
    for seed in range(40):
        e = Engine(['a', 'b'], random.Random(seed), 27)
        assert e.s['pool'] == [] and not e._deal_exception(e.s['selected'])
        where |= {k for c in e.s['columns'] for k in ('top', 'covered') if c[k] == 'yellow:5'}
    assert where == {'top', 'covered'}
    e = two_humans(27)
    filler = [trick(i + 1, 'a', ['blue:1', 'blue:2', 'blue:3'], seats=e.s['seats']) for i in range(12)]
    e.s['history'] = filler + [trick(13, 'a', ['blue:9', 'blue:8', 'blue:7'], seats=e.s['seats'])]
    e._outcome()                                                     # all 13 tricks, never played
    assert e.s['result'] == {'status': 'failed',
                             'reason': 'Yellow 5 was left unplayed instead of ending the final trick.'}
    e = two_humans(27)
    order = [q for q in e.s['seats'] if q != 'tonoja'] + ['tonoja']
    e.s['history'] = filler + [trick(13, order[0], ['blue:9', 'blue:8', 'yellow:5'], seats=order)]
    assert e.s['history'][-1]['plays'][-1] == {'seat': 'tonoja', 'card': 'yellow:5'}
    e._outcome()                                                     # Tonoja plays it last
    assert e.s['result']['status'] == 'success'


@pytest.mark.parametrize('mid', SHARED_SONAR_FOR_TWO)
def test_two_players_play_every_shared_sonar_mission_to_a_result_with_legal_actions(mid):
    for seed in range(6):
        e = two_humans(mid, seed)
        for _ in range(45):
            if e.s['result']:
                break
            if not e.s['trick']:
                for q in e.s['humans']:                              # use sonar whenever offered
                    options = e.communication_options(q)
                    if options:
                        card, opts = next(iter(options.items()))
                        act(e, q, 'communicate', card=card, assertion=opts[0])
            q = e.s['turn']
            act(e, e.controller(q), 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
            e.check()
        assert e.s['result']['status'] in ('success', 'failed')
        assert not any(x['seat'] == 'tonoja' for x in e.s['exposures'])
        if e.s['communication'] == 'rapture':
            assert e.s['shared'] in (0, 1) and len(e.s['exposures']) <= 1


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
    place(e)
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
    place(e)
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
    place(e)
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
    place(e)
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
        place(e)
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
    place(e)
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


# ---- AVR-249: the task "win a 5 with a 7" is enabled (C18, owner decision Q5) --------------------
# The owner wins a trick with their own color 7, and that trick also contains a color 5. Any colors.
# 4with8 and 6with6 stay quarantined.

# The content hash of the catalog before 5with7 was enabled (main at 42ee69b).
HASH_BEFORE_5WITH7 = '9fa0f27a6f6b080b00cfb44e23268f7d47d82769e965204f9da1531cce47df99'
FIVE_WITH_SEVEN = TASKS['5with7']


def one_trick(winner, cards, planned=13):
    """One resolved trick; seat a plays cards[0], b cards[1], c cards[2]."""
    return history_state([trick(1, winner, cards, leader='a')], planned=planned)


def test_five_with_seven_is_enabled_with_its_stored_definition_and_the_others_stay_off():
    assert FIVE_WITH_SEVEN['enabled'] and 'blocked' not in FIVE_WITH_SEVEN
    colors = ['blue', 'green', 'pink', 'yellow']
    assert FIVE_WITH_SEVEN['family'] == 'win_with'
    assert FIVE_WITH_SEVEN['params'] == {'instrument': {'suits': colors, 'ranks': [7]},
                                         'target': {'suits': colors, 'ranks': [5]}}
    assert FIVE_WITH_SEVEN['difficulty'] == {'3': 1, '4': 2, '5': 2}
    for key in ('4with8', '6with6'):
        assert not TASKS[key]['enabled'] and TASKS[key]['blocked'].startswith('C18')
    assert sum(d['enabled'] for d in TASKS.values()) == 92


@pytest.mark.parametrize('cards', [
    ['blue:7', 'blue:5', 'blue:3'],                                    # same color
    ['green:7', 'pink:5', 'green:2'],                                  # the 5 was discarded by a void seat
    ['yellow:7', 'yellow:1', 'blue:5'],                                # the 5 can be anywhere in the trick
])
def test_winning_a_trick_with_a_seven_that_contains_a_five_satisfies_at_once(cards):
    assert evaluate(FIVE_WITH_SEVEN, 'a', one_trick('a', cards)) == 'satisfied'


@pytest.mark.parametrize('winner,cards,why', [
    ('a', ['blue:9', 'blue:7', 'blue:5'], 'the owner won with a 9; the 7 was another seat\'s'),
    ('a', ['submarine:1', 'blue:5', 'blue:7'], 'the owner won with a submarine'),
    ('b', ['blue:5', 'submarine:2', 'blue:7'], 'another seat\'s submarine won the trick'),
    ('b', ['blue:5', 'blue:7', 'blue:3'], 'another seat won with the 7'),
    ('c', ['blue:7', 'blue:5', 'blue:9'], 'the owner played the 7 and lost the trick'),
    ('a', ['blue:7', 'blue:4', 'blue:6'], 'no 5 in the trick'),
    ('a', ['green:7', 'blue:7', 'pink:7'], 'a 7 is not a 5: the two cards are distinct'),
    ('a', ['pink:5', 'pink:4', 'pink:3'], 'the owner won with the 5 itself'),
])
def test_other_ways_of_winning_or_losing_the_trick_do_not_satisfy_five_with_seven(winner, cards, why):
    assert evaluate(FIVE_WITH_SEVEN, 'a', one_trick(winner, cards)) == 'pending', why
    assert evaluate(FIVE_WITH_SEVEN, 'a', one_trick(winner, cards, planned=1)) == 'failed', why


def test_the_seven_and_the_five_are_always_two_different_cards():
    for seven in (c for c in DECK if rank(c) == 7 and suit(c) != 'submarine'):
        for five in (c for c in DECK if rank(c) == 5 and suit(c) != 'submarine'):
            assert seven != five
            lead_color = [seven, five, suit(seven) + ':1']             # a wins with the 7
            assert evaluate(FIVE_WITH_SEVEN, 'a', one_trick('a', lead_color)) == 'satisfied'
    # The task is for whoever owns it: seat b winning with the 7 satisfies b, not a.
    s = one_trick('b', ['blue:5', 'blue:7', 'blue:3'])
    assert evaluate(FIVE_WITH_SEVEN, 'b', s) == 'satisfied' and evaluate(FIVE_WITH_SEVEN, 'a', s) == 'pending'


def test_five_with_seven_can_be_drawn_selected_and_completes_a_mission():
    e = Engine(['p0', 'p1', 'p2'], random.Random(1))
    pool_and_deck = set(e.s['deck']) | set(e.s['pool'])
    assert '5with7' in pool_and_deck and not {'4with8', '6with6'} & pool_and_deck
    e = drawn(['p0', 'p1', 'p2'], 1, ['5with7'])                       # difficulty 1 at three seats
    assert e.s['pool'] == ['5with7']
    owner = e.s['captain']
    act(e, owner, 'choose_task', task='5with7')
    decide(e, 'p0', 'begin')
    seats = e.s['seats']
    order = seats[seats.index(owner):] + seats[:seats.index(owner)]
    e.s['history'] = [{'index': 1, 'leader': owner, 'winner': owner, 'plays': [
        {'seat': order[0], 'card': 'green:7'}, {'seat': order[1], 'card': 'green:5'}, {'seat': order[2], 'card': 'green:2'}]}]
    e._outcome()
    assert e.s['progress'] == {'5with7': 'satisfied'} and e.s['result']['status'] == 'success'
    assert [t['text'] for t in e.view(None)['tasks']] == ['Win a trick by playing a color 7 and capture a color 5 in that trick.']


def test_enabling_the_task_changed_the_content_hash_and_old_snapshots_are_refused(tmp_path):
    assert content.CONTENT_HASH != HASH_BEFORE_5WITH7
    snap = json.loads(json.dumps(playing().snapshot()))
    assert Engine.restore(json.loads(json.dumps(snap))).s['content'] == content.CONTENT_HASH
    snap['state']['content'] = HASH_BEFORE_5WITH7                      # a table saved before this change
    with pytest.raises(Invalid) as refused:
        Engine.restore(snap)
    assert refused.value.code == 'snapshot'
    # Through the adapter: the old file is not restored, not replaced, and no new table may start.
    path = tmp_path / 'expo.json'
    s, tokens = session(path=path)
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['engine']['state']['content'] = HASH_BEFORE_5WITH7
    path.write_text(json.dumps(saved), encoding='utf-8')
    before = path.read_bytes()
    room = ExpoSession(random.Random(9), snapshot_path=path)
    assert room.engine is None and room.recovery_error
    for t in tokens:
        room.join(t, t)
        room.set_ready(t, True)
    fx = room.start(tokens[0])
    assert room.phase == 'lobby' and fx and fx[0]['kind'] == 'invalid'
    assert path.read_bytes() == before

