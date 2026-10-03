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
from games.expo.rules import DECK, legal_cards, rank, suit
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


# ---- pinned defects (games/expo/docs/RECONCILIATION.md) ----------------------------------------

@pytest.mark.xfail(reason='E-D1 / AVR-239: captain forced onto captain-comparison tasks stalls selection', **DEFECT)
def test_defect_unavoidable_captain_comparison_draw_does_not_stall_selection():
    e = Engine(['p0', 'p1', 'p2'], random.Random(1), 11)             # target 8 = 2 + 4 + 2 at three seats
    pool = ['lessTricksThanCaptain', 'equalTricksThanCaptain', 'moreTricksThanCaptain']
    e.s.update(pool=list(pool), selected=list(pool), initial_count=3, assignments={}, progress={}, pick_index=0)
    cap = e.s['captain']
    assert e.selector() == cap
    progressed = False
    for t, extra in [('pass_task', {})] + [('choose_task', {'task': k}) for k in pool]:
        try:
            act(e, cap, t, **extra)
            progressed = True
            break
        except Invalid:
            pass
    assert progressed or e.s['phase'] != 'allocation', 'the captain can neither pick nor pass'


@pytest.mark.xfail(reason='E-D1 / AVR-239: avoidable variant leaves no action but End table', **DEFECT)
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


@pytest.mark.xfail(reason='E-D2 / AVR-240: no decision, including End table, is accepted while a seat is away', **DEFECT)
def test_defect_a_table_can_be_ended_while_a_seated_player_is_away():
    s, tokens = session()
    s.leave(tokens[2])
    for t in tokens[:2]:
        pid = s.players[t].pid
        s.game_action(t, command(s.engine, pid, 'propose' if t == tokens[0] else 'confirm',
                                 **({'proposal': {'kind': 'end'}} if t == tokens[0] else {'yes': True})))
    assert s.phase == 'game_end'


@pytest.mark.xfail(reason='E-D3 / AVR-241: none-of-the-first-N tasks stay pending after their window', **DEFECT)
def test_defect_none_of_the_first_three_tricks_completes_after_trick_three():
    s = task_state(['b', 'b', 'c'])
    assert evaluate(TASKS['noneFirst3Tricks'], 'a', s) == 'satisfied'


@pytest.mark.xfail(reason='E-D4 / AVR-241: currents hides the assertion from its own communicator', **DEFECT)
def test_defect_currents_shows_the_communicator_their_own_assertion():
    e = playing(mid=9)
    card, opts = next(iter(e.communication_options('p0').items()))
    act(e, 'p0', 'communicate', card=card, assertion=opts[0])
    assert 'assertion' not in e.view('p1')['exposures'][0]
    assert e.view('p0')['exposures'][0].get('assertion') == opts[0]
