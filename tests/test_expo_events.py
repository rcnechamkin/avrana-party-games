"""EXPO semantic events, failure causality and the resolving phase (AVR-246).

The engine reports what happened as ordered, numbered events of meaning; it holds the table
still between a completed trick and the server's settle; and it says what a failure is
attributed to. None of that may change a rule, reveal what a viewer could not see when it
happened, or tell a player what a legal card will do before it is played.

Design and limits: games/expo/docs/GAME_STATE.md ("Semantic events", "The resolving phase",
"Failure causality") and RECONCILIATION.md, entry E-X1.
"""
import json
import random
import time
from copy import deepcopy

import pytest

from games.expo import game
from games.expo.content import TASKS
from games.expo.engine import EVENT_LIMIT, EVENT_TYPES, RESOLVING, Engine, Invalid
from games.expo.game import ExpoSession
from games.expo.rules import DECK, legal_cards, suit
from games.expo.tasks import evaluate, judge

from test_expo import act, allocated, command, decide, place, playing, session
from test_expo_contract import misplayed, with_single_task
from test_expo_coverage import (PHASES, agree, at_phase, by_pid, phone_of, send, table,    # noqa: F401
                                together, with_other_secrets)                             # (`table` is a fixture)
from test_expo_persistence import Clock as BothClocks

SEATS = ('p0', 'p1', 'p2')


# ---- fixtures ----------------------------------------------------------------------------------

def play(e, seat, card, now=100):
    """One card through the engine's own door, with no settle: what a seat can do."""
    e.apply(e.controller(seat), command(e, e.controller(seat), 'play_card', card=card), now)


def first_legal(e):
    q = e.s['turn']
    return q, legal_cards(e.playable(q), e.s['trick'])[0]


def trick(e, settle=True):
    """Play one whole trick with first legal cards; the events it added."""
    start = e.s['event_seq']
    for _ in e.s['seats']:
        if e.s['result']:
            break
        play(e, *first_legal(e))
    if settle:
        e.settle()
    return [x for x in e.s['events'] if x['seq'] > start]


def playout(e, rng=None):
    """Play to a result, settling every trick; first legal cards, or the generator's choice."""
    while not e.s['result']:
        q = e.s['turn']
        legal = legal_cards(e.playable(q), e.s['trick'])
        play(e, q, rng.choice(legal) if rng else legal[0])
        e.settle()
    return e


def dealt(hands, leader, task=None, owner=None, mission=1, mode=None):
    """Three humans before the first trick, each holding the named cards (and others), with
    `leader` to lead and, if given, one task for `owner`."""
    return rig(playing(3, seed=5, mid=mission), hands, leader, task, owner, mode)


def rig(e, hands, leader, task=None, owner=None, mode=None):
    """Lay the named cards into a three-human table that has not played a card yet."""
    named = [c for cards in hands.values() for c in cards]
    assert len(set(named)) == len(named)
    rest = [c for c in DECK if c not in named]
    new = {}
    for q in SEATS:
        need = len(e.s['hands'][q]) - len(hands.get(q, []))
        new[q] = sorted(list(hands.get(q, [])) + rest[:need])
        rest = rest[need:]
    e.s['hands'] = new
    e.s['captain'] = next(q for q in SEATS if 'submarine:4' in new[q])
    e.s['leader'] = e.s['turn'] = leader
    if mode:
        e.s['communication'] = mode
    if task:
        with_single_task(e, task, owner)
    e.check()
    return e


def open_table(n=3, seed=4):
    """A table in play whose one task is judged only when the deal ends, so that no trick
    before the last can end the mission."""
    e = playing(n, seed=seed)
    return with_single_task(e, 'moreTricksThanOthers', 'p0')


def again(e, task=None):
    """After a result: mission 1 once more (a retry, or the next mission), up to the first lead."""
    if e.s['result']['status'] == 'failed':
        decide(e, 'p0', 'retry', keep=True)
    else:
        decide(e, 'p0', 'next', mission=1)
    allocated(e)
    decide(e, 'p0', 'begin')
    return with_single_task(e, task, 'p0') if task else e


def overtaken(leader='p0'):
    """p1 must capture blue 4. With p0 leading, p2 plays last and may legally take the trick with
    blue 9. With p2 leading blue 9, p1 is forced to follow with blue 4 and plays last."""
    return dealt({'p0': ['blue:1'], 'p1': ['blue:4'], 'p2': ['blue:9', 'blue:2']}, leader, 'blue4', 'p1')


def types(events):
    return [x['type'] for x in events]


def rules_state(e):
    """Everything the rules decide, without the log and its counter."""
    return {k: v for k, v in e.s.items() if k not in ('events', 'event_seq')}


def cards_in(value):
    found = set()
    if isinstance(value, dict):
        for v in value.values():
            found |= cards_in(v)
    elif isinstance(value, list):
        for v in value:
            found |= cards_in(v)
    elif isinstance(value, str) and value in DECK:
        found.add(value)
    return found


# ---- order and sequence ------------------------------------------------------------------------

def test_begin_announces_the_first_turn_and_a_trick_emits_its_events_in_order():
    e = allocated(Engine(list(SEATS), random.Random(4), 1))
    before = e.s['event_seq']
    decide(e, 'p0', 'begin')
    begun = [x for x in e.s['events'] if x['seq'] > before]
    assert types(begun) == ['TURN_STARTED']
    assert begun[0]['seat'] == e.s['captain'] and begun[0]['lead'] is True and begun[0]['trick'] == 1
    order = e.s['seats'][e.s['seats'].index(e.s['leader']):] + e.s['seats'][:e.s['seats'].index(e.s['leader'])]
    added = trick(e, settle=False)
    record = e.s['history'][0]
    head = ['CARD_PLAYED', 'TURN_STARTED', 'CARD_PLAYED', 'TURN_STARTED', 'CARD_PLAYED', 'TRICK_RESOLVED']
    assert types(added)[:6] == head
    assert set(types(added)[6:]) <= {'OBJECTIVE_PROGRESS', 'OBJECTIVE_COMPLETED'}
    played = [x for x in added if x['type'] == 'CARD_PLAYED']
    assert [(x['seat'], x['card'], x['position']) for x in played] == [
        (p['seat'], p['card'], i + 1) for i, p in enumerate(record['plays'])]
    assert [x['seat'] for x in added if x['type'] == 'TURN_STARTED'] == order[1:]
    assert all(x['lead'] is False for x in added if x['type'] == 'TURN_STARTED')
    resolved = added[5]
    assert (resolved['winner'], resolved['leader'], resolved['plays'], resolved['trick']) == (
        record['winner'], record['leader'], record['plays'], 1)
    assert resolved['winning_card'] == next(p['card'] for p in record['plays'] if p['seat'] == record['winner'])
    assert all(x['trick'] == 1 and x['attempt'] == e.s['attempt'] and x['mission'] == 1 for x in added)
    # The winner's turn is announced by the settle, not before it.
    assert e.settle() is True
    last = e.s['events'][-1]
    assert (last['type'], last['seat'], last['lead'], last['trick']) == ('TURN_STARTED', record['winner'], True, 2)


def test_sequence_numbers_are_consecutive_from_one_and_never_reused():
    e = overtaken()
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(e, q, c)
    assert [x['seq'] for x in e.s['events']] == list(range(1, e.s['event_seq'] + 1))
    head = e.s['event_seq']
    again(e)
    first = next(x for x in e.s['events'] if x['attempt'] == e.s['attempt'])
    assert first['seq'] == head + 1 and first['type'] == 'TURN_STARTED'    # a new attempt goes on counting
    assert [x['seq'] for x in e.s['events']] == list(range(1, e.s['event_seq'] + 1))
    assert {x['type'] for x in e.s['events']} <= set(EVENT_TYPES)


def test_a_rejected_command_emits_nothing_and_leaves_the_log_as_it_was():
    e = playing(3, seed=4)
    q = e.s['turn']
    play(e, q, e.playable(q)[0])
    before = deepcopy(e.s['events']), e.s['event_seq']
    idle = next(p for p in e.s['humans'] if e.controller(e.s['turn']) != p)
    with pytest.raises(Invalid):
        play(e, idle, e.playable(idle)[0])                          # not their turn
    with pytest.raises(Invalid):
        e.apply(e.controller(e.s['turn']), command(e, e.controller(e.s['turn']), 'play_card', card='not-a-card'))
    assert (e.s['events'], e.s['event_seq']) == before


# ---- the resolving phase -----------------------------------------------------------------------

def test_a_completed_trick_holds_the_table_until_the_server_settles_it():
    e = playing(3, seed=4)
    trick(e, settle=False)
    assert e.s['resolving'] == {'trick': 1} and e.s['phase'] == 'before_trick' and e.s['result'] is None
    frozen = deepcopy(e.s)
    winner = e.s['turn']
    attempts = [(winner, 'play_card', {'card': e.playable(winner)[0]}),
                (winner, 'propose', {'proposal': {'kind': 'end'}}),
                (winner, 'confirm', {'yes': True})]
    card = next(c for c in e.playable(winner) if suit(c) != 'submarine')
    attempts.append((winner, 'communicate', {'card': card, 'assertion': 'highest'}))
    for actor, verb, fields in attempts:
        with pytest.raises(Invalid) as refused:
            e.apply(actor, command(e, actor, verb, **fields), 100)
        assert refused.value.code == 'resolving' and str(refused.value) == RESOLVING
    with pytest.raises(Invalid) as refused:
        e.lifecycle({'t': 'lifecycle', 'decision': {'kind': 'begin'}, 'attempt': e.s['attempt'],
                     'revision': e.s['revision']}, 100)
    assert refused.value.code == 'resolving'
    assert e.s == frozen                                            # nothing moved, nothing was logged
    for viewer in list(e.s['humans']) + [None]:
        v = e.view(viewer)
        assert v['resolving'] == {'trick': 1} and v['stage'] == 'before_trick'
        assert v['trick'] == [] and v['last_trick']['index'] == 1 and v['turn'] == winner
        if viewer:
            assert v['me']['legal_cards'] == [] and v['me']['communication_options'] == {}
            assert v['me']['play_reason'] == RESOLVING
    revision = e.s['revision']
    assert e.settle() is True
    assert e.s['resolving'] is None and e.s['revision'] == revision + 1
    assert e.view(winner)['resolving'] is None and e.view(winner)['me']['legal_cards']
    assert e.settle() is False and e.s['revision'] == revision + 1   # once
    play(e, winner, e.playable(winner)[0])                          # and play goes on
    assert len(e.s['trick']) == 1


def test_only_a_completed_trick_is_resolving():
    e = playing(3, seed=4)
    assert e.s['resolving'] is None and e.settle() is False
    for _ in range(2):
        play(e, *first_legal(e))
        assert e.s['resolving'] is None and e.settle() is False     # a trick in progress is not
    play(e, *first_legal(e))
    assert e.s['resolving'] == {'trick': 1}


def test_no_seat_can_settle_and_settling_never_waits_for_someone_who_is_away():
    e = playing(3, seed=4)
    trick(e, settle=False)
    for verb in ('settle', 'resolve', 'advance'):
        with pytest.raises(Invalid) as refused:
            e.apply('p0', {'t': verb, 'attempt': e.s['attempt'], 'revision': e.s['revision'], 'request': verb})
        assert refused.value.code == 'action'
    assert e.s['resolving'] == {'trick': 1}
    e.presence('p1', True)
    with pytest.raises(Invalid) as refused:
        play(e, e.s['turn'], e.playable(e.s['turn'])[0])
    assert refused.value.code == 'paused'                           # an away seat still stops play
    assert e.settle() is True and e.s['resolving'] is None          # but not the server
    e.check()


def test_a_trick_that_ends_the_mission_goes_to_the_result_and_is_never_resolving():
    e = overtaken()
    play(e, 'p0', 'blue:1')
    play(e, 'p1', 'blue:4')
    play(e, 'p2', 'blue:9')
    assert e.s['phase'] == 'mission_result' and e.s['resolving'] is None and e.settle() is False
    assert types(e.s['events'])[-3:] == ['TRICK_RESOLVED', 'OBJECTIVE_FAILED', 'MISSION_FAILURE']
    decide(e, 'p0', 'retry', keep=True)                             # the crew moves on at once
    assert e.s['attempt'] == 2 and e.s['resolving'] is None


def timed_begun(n=3):
    """Timed mission 16 for `n` humans, begun at 100: its 150 seconds end at 250. Its one task
    is judged only when the deal ends, so no trick before the last can end the mission."""
    humans = [f'p{i}' for i in range(n)]
    for seed in range(40):
        e = Engine(humans, random.Random(seed), 16, timed=True)
        act(e, e.controller(e.selector()), 'volunteer', yes=True)
        for k, q in list(e.s['assignments'].items()):
            if TASKS[k]['params'].get('predict'):
                act(e, e.controller(q), 'predict', task=k, count=0)
        if e.s['phase'] != 'assistance':
            continue
        decide(e, 'p0', 'begin')                                    # at 100: 150 seconds
        assert e.s['mission']['seconds'] == 150 and e.s['expiry'] == 250
        return with_single_task(e, 'moreTricksThanOthers', 'p0')
    pytest.fail('no timed fixture')


def timed_and_resolving(n=3, now=100):
    """Timed mission 16 with its first trick resolved at `now` and not settled; the deadline is 250."""
    e = timed_begun(n)
    for _ in e.s['seats']:
        play(e, *first_legal(e), now=now)
    assert e.s['resolving'] == {'trick': 1} and e.s['expiry'] == 250 and e.s['result'] is None
    return e


TIMEOUT = {'status': 'failed', 'reason': 'Time has run out.'}


def timed_out(e, trick_number):
    """The table ended by time, in the shape every timeout has."""
    cause = e.s['cause']
    e.check()
    return (e.s['result'] == TIMEOUT and e.s['phase'] == 'mission_result' and e.s['expiry'] is None
            and e.s['resolving'] is None
            and (cause['kind'], cause['failure'], cause['trigger_seat'], cause['affected_seat'],
                 cause['action'], cause['trick']) == ('deadline', 'deadline', None, None, None, trick_number)
            and types(e.s['events'])[-1] == 'MISSION_FAILURE')


# Owner decision 2026-10-05: a timed mission gains no time during the resolving hold. The clock
# runs on, the deadline is fixed for the attempt, the committed trick is settled first, and the
# deadline is judged before another turn opens.

@pytest.mark.parametrize('n', [3, 4, 5])
def test_the_deadline_of_a_timed_mission_is_the_same_after_any_number_of_holds(n):
    e = timed_begun(n)
    now, holds = 100.0, 0
    while holds < 6:
        for _ in e.s['seats']:
            now += 0.25
            play(e, *first_legal(e), now=now)
        assert e.s['resolving'] and e.s['expiry'] == 250            # held: the deadline has not moved
        now += 0.8
        assert e.settle(now) is True and e.s['expiry'] == 250       # settled: nor has it now
        holds += 1
    assert e.s['result'] is None and now < 250
    assert e.observe_time(249.999) is False and e.s['result'] is None
    assert e.observe_time(250) is True and timed_out(e, holds + 1)  # exactly the configured 150 s


def test_a_deadline_that_passes_during_a_hold_ends_the_attempt_when_the_trick_settles_and_opens_no_turn():
    e = timed_and_resolving(now=249.7)                              # committed before the deadline
    log, revision = deepcopy(e.s['events']), e.s['revision']
    assert types(log)[-1] == 'TRICK_RESOLVED'
    assert e.observe_time(250.2) is False and e.s['result'] is None     # the trick is settled first
    assert e.s['resolving'] == {'trick': 1} and e.s['expiry'] == 250 and e.s['revision'] == revision
    assert e.settle(250.5) is True                                  # the hold is over, past the deadline
    assert timed_out(e, 2)
    assert e.s['events'][:len(log)] == log                          # the trick and all it reported stand
    assert types(e.s['events'][len(log):]) == ['MISSION_FAILURE']   # and nobody's turn was opened
    assert len(e.s['history']) == 1 and e.s['trick'] == [] and e.s['revision'] == revision + 1
    assert e.settle(250.6) is False


@pytest.mark.parametrize('now,expired', [(249.999, False), (250, True), (250.0, True)])
def test_a_hold_that_ends_exactly_at_the_deadline_ends_the_attempt(now, expired):
    e = timed_and_resolving(now=249.2)
    seq = e.s['event_seq']
    assert e.settle(now) is True
    after = types([x for x in e.s['events'] if x['seq'] > seq])
    if expired:
        assert timed_out(e, 2) and after == ['MISSION_FAILURE']
    else:
        assert e.s['result'] is None and after == ['TURN_STARTED'] and e.s['expiry'] == 250
        assert e.observe_time(250) is True and timed_out(e, 2)


def test_a_command_during_a_hold_is_refused_before_and_after_the_deadline_and_changes_nothing():
    e = timed_and_resolving(now=249.7)
    q = e.s['turn']
    hand = list(e.playable(q))
    for now in (249.8, 250.0, 250.4, 10_000):
        before = deepcopy(e.s)
        with pytest.raises(Invalid) as refused:
            play(e, q, hand[0], now=now)
        assert refused.value.code == 'resolving' and e.s == before  # no card, no result, no event
    assert e.settle(250.5) is True and timed_out(e, 2) and e.playable(q) == hand


def test_a_card_sent_after_the_deadline_is_not_played_whether_or_not_the_hold_was_settled():
    e = timed_and_resolving(now=249.7)
    q = e.s['turn']
    hand = list(e.playable(q))
    late = command(e, e.controller(q), 'play_card', card=hand[0])
    assert e.settle(250.5) is True                                  # what the adapter does first
    with pytest.raises(Invalid) as refused:
        e.apply(e.controller(q), late, 250.5)
    assert refused.value.code == 'stale' and timed_out(e, 2) and e.playable(q) == hand
    # A caller that settles with no clock opens the turn; the next command still finds the deadline.
    e = timed_and_resolving(now=249.7)
    assert e.settle() is True and e.s['result'] is None
    q = e.s['turn']
    hand = list(e.playable(q))
    with pytest.raises(Invalid) as refused:
        play(e, q, hand[0], now=250)
    assert refused.value.code == 'stale' and timed_out(e, 2)
    assert e.playable(q) == hand and e.s['trick'] == []


def winning_trick():
    """A timed table whose first trick completes its only task if p2 does not overtake."""
    e = timed_begun()
    return rig(e, {'p0': ['blue:1'], 'p1': ['blue:4'], 'p2': ['blue:9', 'blue:2']}, 'p0', 'blue4', 'p1')


def test_a_trick_committed_before_the_deadline_that_completes_the_mission_succeeds():
    e = winning_trick()
    play(e, 'p0', 'blue:1', now=249.7)
    play(e, 'p1', 'blue:4', now=249.8)
    play(e, 'p2', 'blue:2', now=249.9)                              # 0.1 s left: any hold would cross it
    assert e.s['result'] == {'status': 'success', 'reason': 'All mission objectives completed.'}
    assert e.s['resolving'] is None and e.s['expiry'] is None and e.s['cause'] is None
    done = deepcopy(e.s)
    assert e.observe_time(250.7) is False and e.settle(250.7) is False and e.expire() is False
    assert e.s == done                                              # the result is not undone by the clock
    assert types(e.s['events'])[-3:] == ['TRICK_RESOLVED', 'OBJECTIVE_COMPLETED', 'MISSION_SUCCESS']


def test_the_same_trick_whose_last_card_comes_after_the_deadline_is_refused_and_times_out():
    e = winning_trick()
    play(e, 'p0', 'blue:1', now=249.7)
    play(e, 'p1', 'blue:4', now=249.8)
    with pytest.raises(Invalid) as refused:
        play(e, 'p2', 'blue:2', now=250)
    assert refused.value.code == 'stale' and timed_out(e, 1)
    assert 'blue:2' in e.s['hands']['p2'] and len(e.s['trick']) == 2 and e.s['history'] == []
    assert 'TRICK_RESOLVED' not in types(e.s['events'])


@pytest.mark.parametrize('n', [2, 3, 4, 5])
def test_an_untimed_table_is_the_same_whatever_clock_its_tricks_are_settled_with(n):
    plain, clocked = playing(n, seed=6), playing(n, seed=6)
    assert plain.s['expiry'] is None and plain.snapshot() == clocked.snapshot()
    now = 100
    while not plain.s['result']:
        card = first_legal(plain)
        play(plain, *card)
        now += 10_000_000
        play(clocked, *card, now=now)
        assert plain.settle() == clocked.settle(now + 10_000_000)
        assert plain.observe_time(0) is False and clocked.observe_time(now * 2) is False
        assert json.dumps(plain.snapshot(), sort_keys=True) == json.dumps(clocked.snapshot(), sort_keys=True)
        assert plain.view('p0') == clocked.view('p0') and plain.view('p0')['expiry'] is None


@pytest.mark.parametrize('now', [None, True, 'late', [300]])
def test_a_settle_with_no_usable_clock_settles_the_trick_and_judges_no_deadline(now):
    e = timed_and_resolving()
    assert e.settle(now) is True and e.s['expiry'] == 250 and e.s['result'] is None
    assert types(e.s['events'])[-1] == 'TURN_STARTED'


def test_a_forced_end_of_a_timed_attempt_clears_a_resolving_trick():
    e = timed_and_resolving()
    assert e.expire('because') is True                              # what a restore does under an untrusted clock
    assert e.s['phase'] == 'mission_result' and e.s['resolving'] is None and e.settle() is False
    e.check()


# ---- causality ---------------------------------------------------------------------------------

def test_a_legal_card_that_loses_the_mission_is_accepted_and_names_who_triggered_it_and_who_lost():
    e = overtaken()
    play(e, 'p0', 'blue:1')
    play(e, 'p1', 'blue:4')
    assert legal_cards(e.playable('p2'), e.s['trick']) == ['blue:2', 'blue:9']   # p2 has a choice
    play(e, 'p2', 'blue:9')                                         # legal, and it loses p1's task
    assert e.s['result'] == {'status': 'failed', 'reason': TASKS['blue4']['text']}
    cause = e.s['cause']
    assert cause['kind'] == 'task' and cause['objective'] == 'blue4'
    assert cause['trigger_seat'] == 'p2' and cause['affected_seat'] == 'p1'
    assert cause['trigger_seat'] != cause['affected_seat']
    assert cause['trigger_controller'] == 'p2' and cause['trigger_card'] == 'blue:9'
    assert cause['action'] == {'t': 'play_card', 'seat': 'p2', 'controller': 'p2', 'card': 'blue:9'}
    assert cause['cards'] == ['blue:4', 'blue:9'] and cause['trick'] == 1
    assert (cause['failure'], cause['state']) == ('unreachable', 'IMPOSSIBLE')
    assert cause['mission'] == {'id': 1, 'attempt': e.s['attempt'], 'objective': None, 'allocation': 'normal',
                                'communication': 'normal', 'timed': False, 'distress': False}
    failed, mission = e.s['events'][-2:]
    assert (failed['type'], failed['objective'], failed['scope'], failed['owner']) == (
        'OBJECTIVE_FAILED', 'blue4', 'task', 'p1')
    assert (failed['trigger_seat'], failed['affected_seat'], failed['failure'], failed['state'],
            failed['cards']) == ('p2', 'p1', 'unreachable', 'IMPOSSIBLE', ['blue:4', 'blue:9'])
    assert mission['type'] == 'MISSION_FAILURE' and mission['cause'] == cause
    assert mission['reason'] == TASKS['blue4']['text']
    for viewer in ('p0', 'p1', 'p2', None):
        assert e.view(viewer)['cause'] == cause                      # the same for every viewer


def test_the_trigger_is_the_seat_that_won_the_trick_not_the_one_that_played_last():
    e = overtaken(leader='p2')
    play(e, 'p2', 'blue:9')                                         # the card that takes it
    play(e, 'p0', 'blue:1')
    assert legal_cards(e.playable('p1'), e.s['trick']) == ['blue:4']
    play(e, 'p1', 'blue:4')                                         # forced, and last
    cause = e.s['cause']
    assert cause['action']['seat'] == 'p1'                          # the command the failure followed
    assert (cause['trigger_seat'], cause['trigger_card'], cause['affected_seat']) == ('p2', 'blue:9', 'p1')
    assert cause['state'] == 'IMPOSSIBLE'


def test_a_seat_that_breaks_its_own_task_is_both_trigger_and_affected_and_the_state_is_failed():
    e = dealt({'p0': ['blue:9'], 'p1': ['blue:1'], 'p2': ['blue:2']}, 'p0', '0tricks', 'p0')
    play(e, 'p0', 'blue:9')
    play(e, 'p1', 'blue:1')
    play(e, 'p2', 'blue:2')
    cause = e.s['cause']
    assert (cause['trigger_seat'], cause['affected_seat'], cause['trigger_card']) == ('p0', 'p0', 'blue:9')
    assert (cause['failure'], cause['state']) == ('violated', 'FAILED')
    assert e.view(None)['tasks'][0]['state'] == 'FAILED' and e.view(None)['tasks'][0]['status'] == 'failed'


def test_a_card_that_fails_a_task_before_its_trick_ends_names_the_seat_that_played_it():
    e = dealt({'p0': ['pink:3']}, 'p0', 'noLeadRedGreen', 'p0')
    play(e, 'p0', 'pink:3')                                         # a legal lead
    assert e.s['result']['status'] == 'failed' and e.s['history'] == [] and len(e.s['trick']) == 1
    cause = e.s['cause']
    assert (cause['trigger_seat'], cause['trigger_card'], cause['affected_seat'], cause['trick']) == (
        'p0', 'pink:3', 'p0', 1)
    assert (cause['failure'], cause['state']) == ('violated', 'FAILED')
    assert types(e.s['events'])[-3:] == ['CARD_PLAYED', 'OBJECTIVE_FAILED', 'MISSION_FAILURE']


def test_yellow_five_out_of_place_names_the_seat_that_played_it_even_when_the_trick_is_complete():
    # Mission 27. The failure is decided by the card, whoever wins: this is the one failure at a
    # resolved trick whose trigger is not that trick's winner (RECONCILIATION E-X1, residual question).
    e = dealt({'p0': ['yellow:1'], 'p1': ['yellow:9'], 'p2': ['yellow:5']}, 'p0',
              'moreTricksThanOthers', 'p0', mission=27)
    play(e, 'p0', 'yellow:1')
    play(e, 'p1', 'yellow:9')
    play(e, 'p2', 'yellow:5')
    assert e.s['result']['status'] == 'failed' and len(e.s['history']) == 1 and e.s['trick'] == []
    cause = e.s['cause']
    assert e.s['history'][0]['winner'] == 'p1'
    assert (cause['kind'], cause['objective'], cause['trigger_seat'], cause['trick']) == (
        'mission_objective', 'final_yellow5', 'p2', 1)
    assert 'yellow:5' in cause['cards'] and 'TRICK_RESOLVED' in types(e.s['events'])


def test_a_mission_objective_names_the_seat_that_took_the_trick_and_the_seat_that_had_to_stay_ahead():
    # Mission 23: the first trick's winner must always hold strictly more tricks.
    e = dealt({'p0': ['blue:9', 'green:1'], 'p1': ['blue:1', 'green:9'], 'p2': ['blue:2', 'green:2']},
              'p0', mission=23)
    for q, c in (('p0', 'blue:9'), ('p1', 'blue:1'), ('p2', 'blue:2')):
        play(e, q, c)
    assert e.s['result'] is None and e.settle()
    for q, c in (('p0', 'green:1'), ('p1', 'green:9'), ('p2', 'green:2')):
        play(e, q, c)
    cause = e.s['cause']
    assert (cause['kind'], cause['objective']) == ('mission_objective', 'first_winner')
    assert (cause['trigger_seat'], cause['affected_seat'], cause['trick']) == ('p1', 'p0', 2)
    assert cause['mission']['objective'] == 'first_winner'
    assert [x['scope'] for x in e.s['events'] if x['type'] == 'OBJECTIVE_FAILED'] == ['mission_objective']


def test_a_failure_in_task_selection_names_the_seat_whose_choice_ended_it():
    e, pool = misplayed()
    cause = e.s['cause']
    last = next(q for k, q in reversed(list(e.s['assignments'].items())))
    assert (cause['kind'], cause['failure'], cause['objective']) == (
        'allocation', 'captain_left_with_comparison_tasks', None)
    assert cause['affected_seat'] == e.s['captain'] and cause['trigger_seat'] == last
    assert cause['action']['t'] == 'choose_task' and cause['action']['task'] == pool[-2]
    assert cause['trick'] == 0 and cause['cards'] == []
    assert types(e.s['events'])[-1] == 'MISSION_FAILURE'            # no objective was lost: no such event
    assert 'OBJECTIVE_FAILED' not in types(e.s['events'])


def test_every_failure_in_many_games_has_a_cause_that_matches_the_table():
    seen = set()
    for n in (3, 4, 5):
        for mission in (1, 2, 5, 8, 23):
            for seed in range(10):
                e = Engine([f'p{i}' for i in range(n)], random.Random(seed), mission)
                try:
                    allocated(e)
                except StopIteration:                               # selection ended the attempt
                    continue
                if e.s['phase'] != 'assistance':
                    continue
                decide(e, 'p0', 'begin')
                playout(e, random.Random(seed))
                cause = e.s['cause']
                if e.s['result']['status'] == 'success':
                    assert cause is None and types(e.s['events'])[-1] == 'MISSION_SUCCESS'
                    continue
                seen.add((cause['kind'], cause['failure']))
                assert e.s['events'][-1]['type'] == 'MISSION_FAILURE' and e.s['events'][-1]['cause'] == cause
                assert cause['mission']['id'] == mission and cause['trick'] in (len(e.s['history']), len(e.s['history']) + 1)
                played = {p['card'] for h in e.s['history'] for p in h['plays']} | {p['card'] for p in e.s['trick']}
                assert cards_in(cause) <= played                    # nothing unplayed is named
                if cause['kind'] == 'task':
                    k = cause['objective']
                    assert cause['affected_seat'] == e.s['assignments'][k] and e.s['progress'][k] == 'failed'
                    assert cause['failure'] == e.s['failures'][k] == judge(
                        TASKS[k], e.s['assignments'][k], e.s, e.s['predictions'].get(k))[1]
                if cause['failure'] == 'unmet_at_end':
                    assert cause['trigger_seat'] is None and len(e.s['history']) == e.s['planned']
                elif not e.s['trick']:
                    record = e.s['history'][-1]
                    assert cause['trigger_seat'] == record['winner'] and cause['trick'] == record['index']
                    assert cause['trigger_card'] == next(
                        p['card'] for p in record['plays'] if p['seat'] == record['winner'])
                assert cause['state'] == ('IMPOSSIBLE' if cause['failure'] == 'unreachable' else 'FAILED')
    assert {('task', 'violated'), ('task', 'unreachable'), ('task', 'unmet_at_end'),
            ('mission_objective', 'violated')} <= seen


def test_the_failure_kind_is_a_label_and_never_changes_a_task_status():
    # Every enabled task, judged on tables at every point of many games: the status is the one
    # `evaluate` gives, and a kind is given exactly for a failure.
    kinds = set()
    for seed in range(6):
        e = playing(4, seed=seed)
        while not e.s['result'] and len(e.s['history']) < e.s['planned']:
            play(e, *first_legal(e))
            e.settle()
            for k, definition in TASKS.items():
                if not definition['enabled']:
                    continue
                for owner in e.s['seats']:
                    status, kind = judge(definition, owner, e.s, 1)
                    assert status == evaluate(definition, owner, e.s, 1)
                    assert (kind is not None) == (status == 'failed')
                    kinds.add(kind)
    assert kinds == {None, 'violated', 'unreachable', 'unmet_at_end'}


def test_objective_states_follow_the_task_through_the_attempt():
    e = Engine(list(SEATS), random.Random(4), 1)
    assert [t['state'] for t in e.view(None)['tasks']] == ['PENDING'] * len(e.s['selected'])
    allocated(e)
    assert {t['state'] for t in e.view(None)['tasks']} == {'PENDING'}      # assigned, not in play
    decide(e, 'p0', 'begin')
    assert {t['state'] for t in e.view(None)['tasks']} == {'ACTIVE'}
    done = overtaken()
    done.s['assignments'] = {'blue4': 'p2'}                         # the same trick, for its winner
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(done, q, c)
    assert done.s['result']['status'] == 'success'
    assert [(t['state'], t['status']) for t in done.view(None)['tasks']] == [('COMPLETED', 'satisfied')]
    lost = overtaken()
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(lost, q, c)
    assert [(t['state'], t['status']) for t in lost.view(None)['tasks']] == [('IMPOSSIBLE', 'failed')]


# ---- no oracle ---------------------------------------------------------------------------------

def test_nothing_in_any_view_tells_a_player_what_a_legal_card_will_do_before_it_is_played():
    e = overtaken()
    play(e, 'p0', 'blue:1')
    play(e, 'p1', 'blue:4')
    # The same moment at a table where blue 9 completes the task instead of losing it.
    kind = overtaken()
    kind.s['assignments'] = {'blue4': 'p2'}
    play(kind, 'p0', 'blue:1')
    play(kind, 'p1', 'blue:4')
    for viewer in ('p0', 'p1', 'p2', None):
        losing, winning = e.view(viewer), kind.view(viewer)
        assert losing['cause'] is None and losing['result'] is None and losing['resolving'] is None
        assert not {'OBJECTIVE_FAILED', 'MISSION_FAILURE', 'OBJECTIVE_COMPLETED'} & set(types(losing['events']))
        assert [t['state'] for t in losing['tasks']] == ['ACTIVE']
        # Apart from who owns the task, which is public, the two views are the same view.
        for v in (losing, winning):
            v['tasks'][0].pop('owner')
        assert losing == winning
    me = e.view('p2')['me']
    assert me['legal_cards'] == legal_cards(e.playable('p2'), e.s['trick']) == ['blue:2', 'blue:9']
    assert set(me) == {'seat', 'hand', 'legal_cards', 'play_reason', 'communication_options',
                       'may_pass_task', 'may_decline_volunteer', 'pass_locked'}
    assert me['play_reason'] is None
    before = e.s['event_seq']
    play(e, 'p2', 'blue:9')                                         # accepted like any other card
    after = [x for x in e.s['events'] if x['seq'] > before]
    assert types(after) == ['CARD_PLAYED', 'TRICK_RESOLVED', 'OBJECTIVE_FAILED', 'MISSION_FAILURE']
    assert e.s['history'][-1]['plays'][-1] == {'seat': 'p2', 'card': 'blue:9'}


# ---- determinism -------------------------------------------------------------------------------

@pytest.mark.parametrize('n,mission', [(2, 11), (3, 1), (4, 9), (5, 23)])
def test_the_same_seed_and_the_same_commands_give_the_same_event_stream(n, mission):
    def run(seed):
        humans = [f'p{i}' for i in range(n)]
        e = Engine(humans, random.Random(seed), mission)
        log = []
        try:
            allocated(e)
        except StopIteration:
            return None
        if e.s['phase'] != 'assistance':
            return None
        decide(e, humans[0], 'begin')
        options = e.communication_options(humans[0])
        if options:
            card, opts = next(iter(options.items()))
            act(e, humans[0], 'communicate', card=card, assertion=opts[0])
        while not e.s['result']:
            play(e, *first_legal(e))
            e.settle()
            log.append(json.dumps(e.s['events'], sort_keys=True))
        return log, {v: json.dumps(e.view(v)['events'], sort_keys=True) for v in humans + [None]}
    seeds = [s for s in range(12) if run(s)][:3]
    assert len(seeds) == 3
    for seed in seeds:
        assert run(seed) == run(seed)
    streams = {run(seed)[0][-1] for seed in seeds}
    assert len(streams) == 3 and all(len(json.loads(s)) > 10 for s in streams)   # and they are not all one stream


def test_the_engine_never_reads_the_log_to_decide_a_rule():
    a, b = playing(4, seed=6), playing(4, seed=6)
    rng_a, rng_b = random.Random(1), random.Random(1)
    while not a.s['result']:
        b.s['events'] = []                                          # b forgets everything, every time
        for e, rng in ((a, rng_a), (b, rng_b)):
            q = e.s['turn']
            play(e, q, rng.choice(legal_cards(e.playable(q), e.s['trick'])))
            e.settle()
        assert rules_state(a) == rules_state(b)
    assert a.view('p0')['result'] == b.view('p0')['result'] and len(a.s['events']) > len(b.s['events'])


# ---- presentation cannot change the table ------------------------------------------------------

def scribble(value):
    """Overwrite everything reachable in a payload."""
    if isinstance(value, dict):
        for k in list(value):
            scribble(value[k])
            value[k] = 'x'
        value['added'] = True
    elif isinstance(value, list):
        for item in value:
            scribble(item)
        value.clear()


@pytest.mark.parametrize('phase', ['before_trick', 'in_trick', 'mission_result'])
def test_what_a_viewer_is_given_is_a_copy_that_cannot_change_the_table(phase):
    if phase == 'mission_result':
        e = overtaken()
        for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
            play(e, q, c)
    else:
        e = open_table()
        if phase == 'in_trick':
            play(e, *first_legal(e))
        else:
            trick(e, settle=False)
    assert (e.s['phase'], bool(e.s['resolving'])) == (phase, phase == 'before_trick')
    before = json.dumps(e.snapshot(), sort_keys=True)
    for viewer in ('p0', 'p1', 'p2', None):
        scribble(e.view(viewer))
        scribble(e.events(viewer))
    assert json.dumps(e.snapshot(), sort_keys=True) == before
    assert e.view('p0')['events'] == e.events('p0') and e.events('p0')   # and it is given again, whole


def test_no_command_can_write_an_event_or_a_cause():
    e = playing(3, seed=4)
    q = e.s['turn']
    base = command(e, q, 'play_card', card=e.playable(q)[0])
    for extra in ({'events': []}, {'cause': {}}, {'resolving': None}, {'event_seq': 0}):
        with pytest.raises(Invalid) as refused:
            e.apply(q, {**base, **extra})
        assert refused.value.code == 'payload'
    for verb in ('emit', 'event', 'present'):
        with pytest.raises(Invalid) as refused:
            e.apply(q, {**base, 't': verb})
        assert refused.value.code == 'action'


# ---- what a viewer is sent ---------------------------------------------------------------------

def test_a_viewer_is_sent_the_latest_resolved_trick_and_what_followed_and_no_earlier_trick():
    e = open_table()
    assert [x['type'] for x in e.view('p0')['events']][-1] == 'TURN_STARTED'    # before any trick: all so far
    for _ in range(3):
        trick(e)
        done = len(e.s['history'])
        assert not e.s['result']
        play(e, *first_legal(e))                                    # and one card of the next
        for viewer in ('p0', 'p1', 'p2', None):
            sent = e.view(viewer)['events']
            assert sent and {x['trick'] for x in sent} == {done, done + 1}
            shown = cards_in(sent)
            latest = {p['card'] for p in e.s['history'][-1]['plays']} | {p['card'] for p in e.s['trick']}
            earlier = {p['card'] for h in e.s['history'][:-1] for p in h['plays']}
            assert latest <= shown and not shown & earlier          # R04: only the most recent trick
            assert [x['seq'] for x in sent] == sorted(x['seq'] for x in sent)
            assert e.view(viewer)['event_seq'] == e.s['event_seq'] == sent[-1]['seq']
        for _ in range(2):                                          # finish that trick
            play(e, *first_legal(e))
        e.settle()
    assert len(e.s['history']) == 6
    assert {1, 2, 3, 4, 5, 6} <= {x['trick'] for x in e.s['events']}    # the server still has them


def test_after_a_result_a_viewer_is_still_sent_only_the_latest_trick():
    # Owner decision 2026-10-05: no complete historical debrief or event stream yet.
    e = playout(open_table())
    last = len(e.s['history'])
    assert e.s['result'] and last > 3
    assert {x['trick'] for x in e.s['events'] if x['attempt'] == e.s['attempt']} >= set(range(1, last + 1))
    earlier = {p['card'] for h in e.s['history'][:-1] for p in h['plays']}
    for viewer in ('p0', 'p1', 'p2', None):
        sent = e.view(viewer)['events']
        assert sent and {x['trick'] for x in sent} == {last}
        assert types(sent)[-1] in ('MISSION_SUCCESS', 'MISSION_FAILURE') and not cards_in(sent) & earlier


def test_the_resolve_hold_is_the_owners_provisional_value():
    assert game.RESOLVE_HOLD == 0.8                                 # owner, 2026-10-05; pending real phones


def test_a_new_attempt_sends_none_of_the_last_attempts_events():
    e = overtaken()
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(e, q, c)
    assert 'MISSION_FAILURE' in types(e.view(None)['events'])
    old = e.s['event_seq']
    decide(e, 'p0', 'retry', keep=True)
    sent = e.view(None)['events']
    assert all(x['attempt'] == e.s['attempt'] and x['seq'] > old for x in sent)
    assert any(x['seq'] <= old for x in e.s['events'])              # kept on the server


def test_a_currents_declaration_is_in_its_authors_events_and_in_nobody_elses():
    e = dealt({'p0': ['blue:9', 'blue:1']}, 'p0', mode='currents')
    card, opts = next(iter(e.communication_options('p1').items()))
    act(e, 'p1', 'communicate', card=card, assertion=opts[0])
    stored = e.s['events'][-1]
    assert stored['type'] == 'COMMUNICATION_SENT' and 'assertion' not in stored
    assert stored['private'] == {'seat': 'p1', 'fields': {'assertion': opts[0]}}
    public = {'seq': stored['seq'], 'type': 'COMMUNICATION_SENT', 'attempt': e.s['attempt'], 'mission': 1,
              'trick': 1, 'seat': 'p1', 'card': card, 'mode': 'currents', 'token': 'personal'}
    assert e.view('p1')['events'][-1] == {**public, 'assertion': opts[0]}
    for viewer in ('p0', 'p2', None, 'tonoja', 'stranger'):
        assert e.view(viewer)['events'][-1] == public
        assert opts[0] not in json.dumps(e.view(viewer)['events'])
    # Whatever was declared, the others are sent the same bytes.
    other = Engine.restore(deepcopy(e.snapshot()))
    wrong = next(a for a in ('highest', 'lowest', 'only') if a != opts[0])
    other.s['events'][-1]['private']['fields']['assertion'] = wrong
    other.s['exposures'][-1]['assertion'] = wrong
    for viewer in ('p0', 'p2', None):
        assert json.dumps(other.view(viewer), sort_keys=True) == json.dumps(e.view(viewer), sort_keys=True)
    assert other.view('p1')['events'][-1]['assertion'] == wrong     # the difference is real


def test_an_open_declaration_is_in_everyones_events():
    e = dealt({'p0': ['blue:9', 'blue:1']}, 'p0')
    card, opts = next(iter(e.communication_options('p1').items()))
    act(e, 'p1', 'communicate', card=card, assertion=opts[0])
    for viewer in ('p0', 'p1', 'p2', None):
        last = e.view(viewer)['events'][-1]
        assert (last['type'], last['seat'], last['card'], last['assertion']) == (
            'COMMUNICATION_SENT', 'p1', card, opts[0])
    assert 'private' not in e.s['events'][-1]


@pytest.mark.parametrize('n', [2, 3, 4, 5])
@pytest.mark.parametrize('currents', [False, True])
def test_no_viewers_events_depend_on_what_that_viewer_may_not_see(n, currents):
    checked = 0
    for phase in PHASES:
        if n == 2 and phase == 'passing':
            continue
        e = at_phase(n, phase, currents)
        for viewer in list(e.s['humans']) + [None]:
            for seed in range(3):
                other = with_other_secrets(e, viewer, seed)
                for x in other.s['events']:                         # and the log's own private part
                    if x.get('private') and x['private']['seat'] != viewer:
                        x['private']['fields'] = {'assertion': 'changed'}
                assert other.events(viewer) == e.events(viewer), (phase, viewer)
                assert other.view(viewer)['cause'] == e.view(viewer)['cause']
                checked += len(e.events(viewer))
    assert checked > 0


def test_no_event_names_a_card_that_was_not_played_or_shown_and_none_carries_a_prediction():
    for n in (2, 3, 4, 5):
        for seed in range(6):
            e = Engine([f'p{i}' for i in range(n)], random.Random(seed), 5)
            e.s['pool'] = ['exactlyXtrickSecret', 'blue4']
            e.s['selected'] = list(e.s['pool'])
            place(e)
            e.s['initial_count'] = 2
            allocated(e)
            if e.s['phase'] != 'assistance':
                continue
            humans = e.s['humans']
            if n > 2:
                decide(e, humans[0], 'distress', direction='left')
                for q in humans:
                    act(e, q, 'pass_card', card=next(c for c in e.playable(q) if suit(c) != 'submarine'))
            else:
                decide(e, humans[0], 'begin')
            shown = set()
            options = e.communication_options(humans[0])
            if options:
                card, opts = next(iter(options.items()))
                act(e, humans[0], 'communicate', card=card, assertion=opts[0])
                shown.add(card)
            while not e.s['result']:
                play(e, *first_legal(e))
                e.settle()
                played = {p['card'] for h in e.s['history'] for p in h['plays']} | {p['card'] for p in e.s['trick']}
                assert cards_in(e.s['events']) <= played | shown
                text = json.dumps(e.s['events'])
                assert 'prediction' not in text and 'hand' not in text and 'covered' not in text
                assert 'pass_choices' not in text and 'deck' not in text


# ---- bounded history ---------------------------------------------------------------------------

def test_the_log_is_bounded_and_always_holds_what_a_viewer_may_be_sent():
    e = open_table()
    longest = 0
    for attempt in range(6):                                        # six attempts, far past the bound
        if attempt:
            again(e, 'moreTricksThanOthers')
        while not e.s['result']:
            play(e, *first_legal(e))
            e.settle()
            assert len(e.s['events']) <= EVENT_LIMIT
            floor = len(e.s['history'])
            due = [x['seq'] for x in e.s['events'] if x['attempt'] == e.s['attempt'] and x['trick'] >= floor]
            sent = [x['seq'] for x in e.view('p0')['events']]
            assert sent == due and sent == list(range(sent[0], sent[-1] + 1))    # whole, no hole
            longest = max(longest, len(sent))
    assert e.s['event_seq'] > EVENT_LIMIT and len(e.s['events']) == EVENT_LIMIT    # it did overflow
    assert e.s['events'][0]['seq'] == e.s['event_seq'] - EVENT_LIMIT + 1
    assert longest < EVENT_LIMIT // 2
    e.check()
    json.dumps(e.snapshot())


# ---- snapshots ---------------------------------------------------------------------------------

def test_a_restored_snapshot_keeps_the_log_the_sequence_and_the_resolving_trick():
    e = open_table(4, seed=6)
    trick(e)
    trick(e, settle=False)                                          # saved while a trick is resolving
    twin = Engine.restore(json.loads(json.dumps(e.snapshot())))
    assert twin.s['events'] == e.s['events'] and twin.s['event_seq'] == e.s['event_seq']
    assert twin.s['resolving'] == {'trick': 2}
    with pytest.raises(Invalid) as refused:
        play(twin, twin.s['turn'], twin.playable(twin.s['turn'])[0])
    assert refused.value.code == 'resolving'                        # still held after the restore
    for table in (e, twin):
        table.settle()
        playout(table)
    assert twin.s['events'] == e.s['events'] and twin.s == e.s
    assert twin.s['events'][-1]['seq'] == twin.s['event_seq']


def test_a_snapshot_written_before_the_events_existed_is_read_with_an_empty_log():
    e = playing(3, seed=4)
    trick(e)
    old = json.loads(json.dumps(e.snapshot()))
    for key in ('events', 'event_seq', 'resolving', 'cause', 'failures'):
        del old['state'][key]
    assert old['state']['version'] == 1
    restored = Engine.restore(old)
    assert (restored.s['events'], restored.s['event_seq'], restored.s['resolving'],
            restored.s['cause'], restored.s['failures']) == ([], 0, None, None, {})
    assert restored.view('p0')['events'] == []
    assert {k: v for k, v in rules_state(restored).items()} == {k: v for k, v in rules_state(e).items()}
    play(restored, *first_legal(restored))
    assert restored.s['events'][0]['seq'] == 1 and restored.s['events'][0]['type'] == 'CARD_PLAYED'


@pytest.mark.parametrize('damage', [
    lambda s: s.update(resolving={'trick': 7}),                     # not the trick just resolved
    lambda s: s.update(resolving={'trick': len(s['history']), 'until': 5}),
    lambda s: s.update(event_seq=1),                                # behind its own log
    lambda s: s['events'].reverse(),
    lambda s: s['events'].extend(deepcopy(s['events']) * 40),
    lambda s: s.update(events='x'),
    lambda s: s.update(failures={'not-a-task': 'violated'}),
    lambda s: s.update(cause='because'),
])
def test_a_snapshot_with_a_broken_log_or_resolving_mark_is_refused(damage):
    e = playing(3, seed=4)
    trick(e, settle=False)
    saved = json.loads(json.dumps(e.snapshot()))
    Engine.restore(deepcopy(saved))                                 # sound as written
    damage(saved['state'])
    with pytest.raises(Invalid) as refused:
        Engine.restore(saved)
    assert refused.value.code == 'snapshot'


def test_a_resolving_mark_outside_play_is_refused():
    e = overtaken()
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(e, q, c)
    saved = json.loads(json.dumps(e.snapshot()))
    saved['state']['resolving'] = {'trick': 1}                      # beside a mission result
    with pytest.raises(Invalid):
        Engine.restore(saved)


# ---- mission success and failure, modifiers ----------------------------------------------------

def test_a_mission_success_is_announced_after_the_objective_that_completed_it():
    e = overtaken()
    e.s['assignments'] = {'blue4': 'p2'}
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:4'), ('p2', 'blue:9')):
        play(e, q, c)
    assert e.s['result']['status'] == 'success' and e.s['cause'] is None
    done, won = e.s['events'][-2:]
    assert (done['type'], done['objective'], done['owner'], done['scope'], done['trick']) == (
        'OBJECTIVE_COMPLETED', 'blue4', 'p2', 'task', 1)
    assert (won['type'], won['attempts'], won['distress'], won['trick']) == ('MISSION_SUCCESS', 1, False, 1)
    assert e.view(None)['cause'] is None
    assert 'MISSION_FAILURE' not in types(e.s['events']) and 'OBJECTIVE_FAILED' not in types(e.s['events'])


def test_progress_is_reported_for_an_open_task_whose_owner_took_the_trick_and_says_no_more():
    e = dealt({'p0': ['blue:9'], 'p1': ['blue:1'], 'p2': ['blue:2']}, 'p0', 'moreThanHalfTricks', 'p0')
    for q, c in (('p0', 'blue:9'), ('p1', 'blue:1'), ('p2', 'blue:2')):
        play(e, q, c)
    progress = e.s['events'][-1]
    assert progress == {'seq': progress['seq'], 'type': 'OBJECTIVE_PROGRESS', 'attempt': e.s['attempt'],
                        'mission': 1, 'trick': 1, 'objective': 'moreThanHalfTricks', 'scope': 'task',
                        'owner': 'p0', 'change': 'owner_won_trick', 'owner_tricks': 1}
    other = dealt({'p0': ['blue:1'], 'p1': ['blue:9'], 'p2': ['blue:2']}, 'p0', 'moreThanHalfTricks', 'p0')
    for q, c in (('p0', 'blue:1'), ('p1', 'blue:9'), ('p2', 'blue:2')):
        play(other, q, c)
    assert other.s['events'][-1]['type'] == 'TRICK_RESOLVED'        # nothing of the owner's changed


def test_modifiers_are_announced_when_an_attempt_is_prepared_and_when_they_take_effect():
    def modifiers(e):
        return [(x['modifier'], x['value']) for x in e.s['events']
                if x['type'] == 'MISSION_MODIFIER_ACTIVATED' and x['attempt'] == e.s['attempt']]
    assert modifiers(Engine(list(SEATS), random.Random(1), 1)) == []
    assert modifiers(Engine(list(SEATS), random.Random(1), 9)) == [('communication', 'currents')]
    assert modifiers(Engine(list(SEATS), random.Random(1), 8)) == [('objective', 'balance9')]
    e = Engine(list(SEATS), random.Random(1), 23)
    assert modifiers(e) == [('communication', e.s['communication']), ('objective', 'first_winner')][
        e.s['communication'] == 'normal':]
    assert 'terrain' not in json.dumps(e.s['events']) and e.s['terrain'] not in json.dumps(e.s['events'])
    e = allocated(Engine(list(SEATS), random.Random(4), 1))
    decide(e, 'p0', 'distress', direction='right')
    assert modifiers(e) == [('distress', 'right')]
    assert all(x['trick'] == 0 for x in e.s['events'])
    timed = Engine(list(SEATS), random.Random(0), 16, timed=True)
    assert ('allocation', 'volunteer') in modifiers(timed)


# ---- reconnect ---------------------------------------------------------------------------------

def test_a_returning_player_is_announced_and_is_sent_the_same_events_again():
    s, tokens = session()
    e, seat = s.engine, by_pid(s, tokens)
    while e.s['pool']:
        q = e.selector()
        send(s, seat[q], 'choose_task', task=next(k for k in e.s['pool'] if e.eligible(k, q)))
    send(s, tokens[0], 'propose', proposal={'kind': 'begin'})
    for t in tokens[1:]:
        send(s, t, 'confirm', yes=True)
    for _ in range(len(e.s['seats']) + 1):                          # a trick and one card
        q = e.s['turn']
        send(s, seat[q], 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0])
    victim = tokens[1]
    pid = s.players[victim].pid
    before = s.game_state(victim)['events']
    assert before and s.game_state(victim)['event_seq'] == before[-1]['seq']
    s.leave(victim)
    assert s.game_state(tokens[0])['events'] == before              # going away is not an event
    s.join(victim, victim)
    after = s.game_state(victim)['events']
    assert after[:-1] == before                                     # the same events, replayed whole
    assert after[-1] == {'seq': before[-1]['seq'] + 1, 'type': 'PLAYER_RECONNECTED', 'attempt': e.s['attempt'],
                         'mission': 1, 'trick': len(e.s['history']) + 1, 'seat': pid}
    assert s.game_state(tokens[0])['events'] == s.game_state(None)['events'] == after
    s.join(victim, victim)                                          # a second socket is not a return
    assert s.game_state(victim)['events'] == after


def test_presence_is_told_to_the_engine_once_and_only_for_seated_humans():
    e = playing(3, seed=4)
    revision, seq = e.s['revision'], e.s['event_seq']
    assert e.presence('stranger', True) is False and e.presence('p1', False) is False
    assert (e.s['revision'], e.s['event_seq'], e.s['away']) == (revision, seq, [])
    assert e.presence('p1', True) is True and e.presence('p1', True) is False
    assert (e.s['revision'], e.s['event_seq'], e.s['away']) == (revision + 1, seq, ['p1'])
    assert e.presence('p1', False) is True
    assert (e.s['revision'], e.s['event_seq'], e.s['away']) == (revision + 2, seq + 1, [])


# ---- the adapter: who settles, and when --------------------------------------------------------

class Clock:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(game, '_mono', lambda: self.now)
        monkeypatch.setattr(game, '_wall', lambda: self.now + 5_000_000)


def begun(path=None):
    s, tokens = session(path=path)
    e, seat = s.engine, by_pid(s, tokens)
    while e.s['pool']:
        q = e.selector()
        assert s.game_action(seat[q], command(e, q, 'choose_task', task=next(
            k for k in e.s['pool'] if e.eligible(k, q)))) == []
    assert s.game_action(tokens[0], command(e, s.players[tokens[0]].pid, 'propose', proposal={'kind': 'begin'})) == []
    for t in tokens[1:]:
        assert s.game_action(t, command(e, s.players[t].pid, 'confirm', yes=True)) == []
    return s, tokens, seat


def raw_card(s, seat):
    """One card through the adapter with no timer fired: what the phone's message does."""
    e = s.engine
    q = e.s['turn']
    return s.game_action(seat[q], command(e, q, 'play_card', card=legal_cards(e.playable(q), e.s['trick'])[0]))


def test_the_adapter_holds_a_resolved_trick_and_its_timer_settles_it(monkeypatch):
    clock = Clock(monkeypatch)
    s, tokens, seat = begun()
    for _ in s.engine.s['seats']:
        assert raw_card(s, seat) == []
    assert s.engine.s['resolving'] == {'trick': 1}
    opens = clock.now + game.RESOLVE_HOLD
    assert s._hold == ((s.engine.s['attempt'], 1), opens)
    assert s.deadline == pytest.approx(opens + 5_000_000) and s.remaining() is not None     # the timer is armed
    view = s.game_state(tokens[0])
    assert view['resolving'] == {'trick': 1, 'until': pytest.approx(opens + 5_000_000)}
    refused = raw_card(s, seat)                                     # too early: the table is held
    assert [(f['kind'], f['code'], f['msg']) for f in refused] == [('invalid', 'resolving', RESOLVING)]
    assert s._hold == ((s.engine.s['attempt'], 1), opens)           # and asking does not move the moment
    revision = s.engine.s['revision']
    clock.now = opens - 0.5
    s.tick(s.gen)                                                   # a timer that fires early settles nothing
    assert s.engine.s['resolving'] == {'trick': 1} and s.deadline == pytest.approx(opens + 5_000_000)
    clock.now = opens
    assert s.tick(s.gen) == []                                      # the timer core.net keeps
    assert s.engine.s['resolving'] is None and s.engine.s['revision'] == revision + 1
    assert s._hold is None and s.deadline is None
    assert s.game_state(tokens[0])['resolving'] is None
    assert s.game_state(tokens[0])['events'][-1]['type'] == 'TURN_STARTED'
    assert raw_card(s, seat) == []                                  # play goes on


def test_a_command_after_the_hold_settles_the_trick_even_if_the_timer_never_fired(monkeypatch):
    clock = Clock(monkeypatch)
    s, tokens, seat = begun()
    for _ in s.engine.s['seats']:
        raw_card(s, seat)
    assert s.engine.s['resolving'] == {'trick': 1}
    clock.now += game.RESOLVE_HOLD + 3600                           # no tick: the timer was lost
    late = raw_card(s, seat)                                        # built against the held table
    assert [f['code'] for f in late] == ['stale'] and s.engine.s['resolving'] is None
    assert raw_card(s, seat) == []                                  # the next one is accepted
    assert len(s.engine.s['trick']) == 1


def test_a_table_cannot_stay_resolving_when_everyone_leaves(monkeypatch):
    clock = Clock(monkeypatch)
    s, tokens, seat = begun()
    for _ in s.engine.s['seats']:
        raw_card(s, seat)
    for t in tokens:
        s.leave(t)
    assert s.engine.s['resolving'] == {'trick': 1} and s.deadline is not None
    clock.now += game.RESOLVE_HOLD
    s.tick(s.gen)
    assert s.engine.s['resolving'] is None and s.engine.s['away'] == s.engine.s['humans']


def test_a_restart_during_a_resolving_trick_restores_a_table_that_is_not_held(tmp_path, monkeypatch):
    Clock(monkeypatch)
    path = tmp_path / 'expo.json'
    s, tokens, seat = begun(path)
    for _ in s.engine.s['seats']:
        raw_card(s, seat)
    assert json.loads(path.read_text(encoding='utf-8'))['engine']['state']['resolving'] == {'trick': 1}
    log = deepcopy(s.engine.s['events'])
    again = ExpoSession(random.Random(99), snapshot_path=path)
    assert again.recovery_error is None and again.engine.s['resolving'] is None and again._hold is None
    assert again.engine.s['events'][:len(log)] == log               # the log came back, in order
    assert types(again.engine.s['events'][len(log):]) == ['TURN_STARTED']
    for t in tokens:
        again.join(t, t)
    assert types(again.engine.s['events'][len(log) + 1:]) == ['PLAYER_RECONNECTED'] * 3
    seats = by_pid(again, tokens)
    assert raw_card(again, seats) == []                             # and the crew plays on


def timed_session(path, clock, n=3):
    """A stored, timed mission 16 table for `n` humans, begun at the clock's now, whose one task
    is judged only when the deal ends."""
    for seed in range(40):
        s = ExpoSession(random.Random(seed), snapshot_path=path)
        tokens = [f'human-{i}' for i in range(n)]
        for t in tokens:
            s.join(t, t)
            s.set_ready(t, True)
        s.set_settings(tokens[0], {'timed': True})
        s.set_settings(tokens[0], {'mission': 16})
        s.start(tokens[0])
        s.tick(s.gen)
        e, seat = s.engine, by_pid(s, tokens)
        send(s, seat[e.controller(e.selector())], 'volunteer', yes=True)
        for k, q in list(e.s['assignments'].items()):
            if TASKS[k]['params'].get('predict'):
                send(s, seat[q], 'predict', task=k, count=0)
        if e.s['phase'] == 'assistance':
            agree(s, tokens, 'begin')
            assert e.s['expiry'] == clock.mono + 150
            with_single_task(e, 'moreTricksThanOthers', e.s['humans'][0])
            s._save()
            return s, tokens, seat
        s.store.clear()
    pytest.fail('no timed fixture')


def shown_deadline(s, clock):
    """Seconds left on the countdown a browser draws from the view it was just sent."""
    views = [s.game_state(t)['expiry'] for t in list(s.participants) + [None]]
    assert len(set(views)) == 1                                     # every viewer, the same moment
    return views[0] - clock.wall


def held_near_the_deadline(path, clock, left):
    """A timed table whose first trick was completed `left` seconds before its deadline."""
    s, tokens, seat = timed_session(path, clock)
    e = s.engine
    for _ in e.s['seats'][:-1]:
        assert raw_card(s, seat) == []
    clock.pass_time(e.s['expiry'] - clock.mono - left)
    assert raw_card(s, seat) == []                                  # committed before the deadline
    assert e.s['resolving'] == {'trick': 1} and e.s['result'] is None
    return s, tokens, seat


@pytest.mark.parametrize('n', [3, 4, 5])
def test_a_timed_mission_lasts_exactly_its_configured_seconds_however_many_tricks_were_held(tmp_path, monkeypatch, n):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = timed_session(tmp_path / 'expo.json', clock, n)
    e = s.engine
    begun_at, expiry, moment = clock.mono, e.s['expiry'], s.game_state(tokens[0])['expiry']
    assert expiry == begun_at + 150 and moment == pytest.approx(clock.wall + 150)
    assert s.deadline == pytest.approx(moment)                      # the mission's timer is armed
    for held in range(1, 5):
        for _ in e.s['seats']:
            clock.pass_time(0.5)
            assert raw_card(s, seat) == []
        assert e.s['resolving'] == {'trick': held} and e.s['expiry'] == expiry
        assert s.deadline == pytest.approx(clock.wall + game.RESOLVE_HOLD)      # the hold is what is armed
        for t in list(tokens) + [None]:                             # every viewer: the same fixed moment
            assert s.game_state(t)['expiry'] == pytest.approx(moment)
        clock.pass_time(game.RESOLVE_HOLD)
        assert s.tick(s.gen) == []
        assert e.s['resolving'] is None and e.s['result'] is None and e.s['expiry'] == expiry
        assert s.deadline == pytest.approx(moment)                  # then the mission's again, unmoved
        assert s.game_state(tokens[0])['expiry'] == pytest.approx(moment)
    clock.pass_time(begun_at + 150 - clock.mono - 0.01)
    s.tick(s.gen)
    assert e.s['result'] is None                                    # 149.99 s after Begin
    clock.pass_time(0.01)
    s.tick(s.gen)
    assert clock.mono == pytest.approx(begun_at + 150)              # 150 s, four holds or none
    assert e.s['result'] == TIMEOUT and e.s['cause']['kind'] == 'deadline'
    assert e.s['cause']['trigger_seat'] is None and e.s['cause']['trick'] == 5


def test_a_deadline_that_passes_during_the_hold_ends_the_attempt_at_the_end_of_the_hold(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=0.3)
    e = s.engine
    log, expiry, until = deepcopy(e.s['events']), e.s['expiry'], s.game_state(tokens[0])['resolving']['until']
    assert types(log)[-1] == 'TRICK_RESOLVED' and shown_deadline(s, clock) == pytest.approx(0.3)
    assert until == pytest.approx(clock.wall + game.RESOLVE_HOLD)
    # The one timer is armed for the end of the hold, not for the deadline that comes sooner.
    assert s.deadline == pytest.approx(until) and s.deadline > clock.wall + 0.3 + 0.4
    clock.pass_time(0.5)                                            # 0.2 s past the deadline, still held
    assert s.tick(s.gen) == []                                      # a timer that fires now settles nothing
    assert e.s['resolving'] == {'trick': 1} and e.s['result'] is None and e.s['expiry'] == expiry
    assert s.deadline == pytest.approx(until)                       # and it is still the hold's end
    assert shown_deadline(s, clock) == pytest.approx(-0.2)          # the countdown was not stepped up
    assert s.game_state(tokens[0])['resolving']['until'] == pytest.approx(until)
    refused = raw_card(s, seat)                                     # a card now is not a play
    assert [(f['kind'], f['code']) for f in refused] == [('invalid', 'resolving')]
    assert e.s['trick'] == [] and e.s['result'] is None and e.s['events'] == log
    clock.pass_time(game.RESOLVE_HOLD - 0.5)
    assert s.tick(s.gen) == []                                      # the hold ends: settle, then time
    assert e.s['result'] == TIMEOUT and e.s['resolving'] is None and s._hold is None
    assert e.s['cause']['kind'] == 'deadline' and e.s['cause']['trick'] == 2
    assert e.s['events'][:len(log)] == log
    assert types(e.s['events'][len(log):]) == ['MISSION_FAILURE']   # no TURN_STARTED: no turn was opened
    view = s.game_state(tokens[0])
    assert view['resolving'] is None and view['expiry'] is None and view['events'][-1]['type'] == 'MISSION_FAILURE'
    assert s.deadline is None                                       # nothing is left to wait for
    again = ExpoSession(random.Random(1), snapshot_path=tmp_path / 'expo.json')
    assert again.engine.s['result'] == TIMEOUT                      # and the end was saved


def test_a_hold_that_ends_exactly_at_the_deadline_times_out_without_a_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(game, 'RESOLVE_HOLD', 0.5)                  # exact in binary: 1149.5 + 0.5 == 1150.0
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=0.5)
    e = s.engine
    seq = e.s['event_seq']
    assert s._hold[1] == e.s['expiry'] == 1150.0
    clock.pass_time(0.5)
    assert clock.mono == 1150.0
    s.tick(s.gen)
    assert e.s['result'] == TIMEOUT
    assert types([x for x in e.s['events'] if x['seq'] > seq]) == ['MISSION_FAILURE']


def test_a_timer_that_wakes_early_does_not_open_a_turn_before_a_deadline_inside_the_hold(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=game.RESOLVE_HOLD - 0.010)
    e = s.engine
    log, ends = deepcopy(e.s['events']), s._hold[1]
    assert e.s['expiry'] == pytest.approx(ends - 0.010) and e.s['expiry'] < ends
    clock.pass_time(game.RESOLVE_HOLD - 0.015)                      # within HOLD_SLACK of the end
    assert clock.mono < e.s['expiry'] < ends and ends - clock.mono < game.HOLD_SLACK
    s.tick(s.gen)                                                   # the hold's own end, 15 ms early
    assert e.s['result'] == TIMEOUT and e.s['resolving'] is None and s._hold is None
    assert types(e.s['events'][len(log):]) == ['MISSION_FAILURE']   # no turn for the last 5 ms


def test_a_timer_that_wakes_early_opens_the_turn_when_the_deadline_is_after_the_hold(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=game.RESOLVE_HOLD + 0.010)
    e = s.engine
    expiry = e.s['expiry']
    clock.pass_time(game.RESOLVE_HOLD - 0.015)
    s.tick(s.gen)
    assert e.s['result'] is None and e.s['resolving'] is None and e.s['expiry'] == expiry
    assert types(e.s['events'])[-1] == 'TURN_STARTED'
    assert s.deadline == pytest.approx(clock.wall + 0.025)          # the mission's deadline, unmoved


def test_a_hold_that_ends_just_before_the_deadline_opens_the_turn_and_the_deadline_still_stands(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=game.RESOLVE_HOLD + 0.25)
    e = s.engine
    expiry = e.s['expiry']
    clock.pass_time(game.RESOLVE_HOLD)
    s.tick(s.gen)
    assert e.s['resolving'] is None and e.s['result'] is None and e.s['expiry'] == expiry
    assert types(e.s['events'])[-1] == 'TURN_STARTED'
    assert s.deadline == pytest.approx(clock.wall + 0.25) and shown_deadline(s, clock) == pytest.approx(0.25)
    clock.pass_time(0.25)
    s.tick(s.gen)
    assert e.s['result'] == TIMEOUT


@pytest.mark.parametrize('late', [0.0, 5.0, 3600.0])
def test_a_card_sent_after_a_hold_that_crossed_the_deadline_is_refused_even_if_the_timer_never_fired(tmp_path, monkeypatch, late):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = held_near_the_deadline(tmp_path / 'expo.json', clock, left=0.3)
    e = s.engine
    log = deepcopy(e.s['events'])
    q = e.s['turn']
    hand = list(e.playable(q))
    clock.pass_time(game.RESOLVE_HOLD + late)                       # no tick: the timer was lost
    refused = raw_card(s, seat)                                     # this command settles the trick
    assert [(f['kind'], f['code']) for f in refused] == [('invalid', 'stale')]
    assert e.s['result'] == TIMEOUT and e.s['resolving'] is None
    assert e.playable(q) == hand and e.s['trick'] == [] and len(e.s['history']) == 1
    assert types(e.s['events'][len(log):]) == ['MISSION_FAILURE']


def test_a_lost_timer_gives_a_timed_table_no_time(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = timed_session(tmp_path / 'expo.json', clock)
    e = s.engine
    expiry = e.s['expiry']
    for _ in e.s['seats']:
        assert raw_card(s, seat) == []
    clock.pass_time(game.RESOLVE_HOLD + 5)                          # the timer never fired
    assert [f['code'] for f in raw_card(s, seat)] == ['stale']      # this command settles the trick
    assert e.s['resolving'] is None and e.s['result'] is None
    assert e.s['expiry'] == expiry and shown_deadline(s, clock) == pytest.approx(150 - game.RESOLVE_HOLD - 5)


@pytest.mark.parametrize('down,ended', [(0.1, False), (0.5, True), (30.0, True)])
def test_a_restart_during_a_hold_judges_the_fixed_deadline_before_any_turn(tmp_path, monkeypatch, down, ended):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    path = tmp_path / 'expo.json'
    s, tokens, seat = held_near_the_deadline(path, clock, left=0.3)
    saved = json.loads(path.read_text(encoding='utf-8'))['engine']['state']
    assert saved['resolving'] == {'trick': 1} and saved['expiry'] == s.engine.s['expiry']
    log, expiry = deepcopy(s.engine.s['events']), s.engine.s['expiry']
    clock.pass_time(down)                                           # the same boot, clocks in step
    again = ExpoSession(random.Random(99), snapshot_path=path)
    e = again.engine
    assert again.recovery_error is None and e.s['resolving'] is None and again._hold is None
    assert e.s['events'][:len(log)] == log
    if ended:
        assert e.s['result'] == TIMEOUT and e.s['cause']['kind'] == 'deadline'
        assert types(e.s['events'][len(log):]) == ['MISSION_FAILURE']   # settled, then time: no turn
        for t in tokens:
            again.join(t, t)
        refused = raw_card(again, by_pid(again, tokens))
        assert [f['kind'] for f in refused] == ['invalid'] and e.s['trick'] == [] and len(e.s['history']) == 1
    else:
        assert e.s['result'] is None and e.s['expiry'] == expiry    # no time credited, none taken
        assert types(e.s['events'][len(log):]) == ['TURN_STARTED']


def test_a_restart_during_a_hold_under_a_clock_that_cannot_be_trusted_opens_no_turn(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    path = tmp_path / 'expo.json'
    s, tokens, seat = held_near_the_deadline(path, clock, left=60)
    log = deepcopy(s.engine.s['events'])
    clock.boot = 'boot-b'                                           # a reboot: the deadline means nothing
    again = ExpoSession(random.Random(99), snapshot_path=path)
    e = again.engine
    assert e.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}
    assert e.s['resolving'] is None and types(e.s['events'][len(log):]) == ['MISSION_FAILURE']


def test_an_untimed_table_through_the_adapter_is_untouched_by_the_clock_during_a_hold(tmp_path, monkeypatch):
    clock = BothClocks(monkeypatch, wall=5_000_000.0, mono=1000.0)
    s, tokens, seat = begun(tmp_path / 'expo.json')
    e = s.engine
    for _ in e.s['seats']:
        assert raw_card(s, seat) == []
    assert e.s['resolving'] == {'trick': 1} and e.s['expiry'] is None
    assert s.game_state(tokens[0])['expiry'] is None
    clock.pass_time(10_000_000)                                     # any amount of time
    s.tick(s.gen)
    assert e.s['resolving'] is None and e.s['result'] is None and e.s['expiry'] is None
    assert types(e.s['events'])[-1] == 'TURN_STARTED' and s.deadline is None
    assert raw_card(s, seat) == []


def test_a_return_is_given_the_trick_of_its_phase_and_always_reaches_the_viewers():
    def returned(e):
        e.presence('p1', True)
        e.presence('p1', False)
        event = e.s['events'][-1]
        assert event['type'] == 'PLAYER_RECONNECTED' and event['seat'] == 'p1'
        for viewer in ('p0', 'p1', None):                           # inside the window it is sent in
            assert e.view(viewer)['events'][-1] == event
        return event['trick']
    e = Engine(list(SEATS), random.Random(4), 1)
    assert e.s['phase'] == 'allocation' and returned(e) == 0        # before play
    allocated(e)
    assert e.s['phase'] == 'assistance' and returned(e) == 0
    e = open_table()
    assert returned(e) == 1                                         # about to be led
    play(e, *first_legal(e))
    assert returned(e) == 1                                         # in progress
    for _ in range(2):
        play(e, *first_legal(e))
    assert e.s['resolving'] and returned(e) == 2                    # resolved: the next one
    e.settle()
    assert returned(e) == 2
    playout(e)
    assert e.s['phase'] == 'mission_result' and len(e.s['history']) == e.s['planned']
    assert returned(e) == e.s['planned']                            # after the last trick: that trick
    e = dealt({'p0': ['pink:3']}, 'p0', 'noLeadRedGreen', 'p0')
    play(e, 'p0', 'pink:3')
    assert e.s['result'] and len(e.s['trick']) == 1 and returned(e) == 1    # ended inside a trick
    e, _ = misplayed()
    assert e.s['phase'] == 'mission_result' and returned(e) == 0    # ended before any card


def test_a_timer_that_cannot_save_says_so_whatever_it_fired_for(tmp_path, monkeypatch):
    Clock(monkeypatch)
    s, tokens, seat = begun(tmp_path / 'expo.json')
    for _ in s.engine.s['seats']:
        raw_card(s, seat)
    assert s.engine.s['resolving'] and s.engine.s['expiry'] is None     # nothing can expire here
    monkeypatch.setattr(s.store, 'write', lambda snapshot: (_ for _ in ()).throw(OSError('disk')))
    s._hold = (s._hold[0], game._mono())
    fx = s.tick(s.gen)
    assert s.engine.s['resolving'] is None                          # the trick is settled all the same
    assert [f['kind'] for f in fx] == ['toast']
    assert 'expired' not in fx[0]['msg'] and 'could not be saved' in fx[0]['msg']


def test_real_phones_are_held_after_a_trick_and_released_by_the_servers_own_timer(table, monkeypatch):
    # The whole path: sockets, the room lock, the session's one timer in core/net.py. Nothing
    # here settles the trick; the hold is long enough to be seen on a busy machine.
    monkeypatch.setattr(game, 'RESOLVE_HOLD', 2.0)
    room, phones = table
    engine = room.session.engine

    def begun(e):
        allocated(e)
        decide(e, e.s['humans'][0], 'begin')
        with_single_task(e, 'moreTricksThanOthers', e.s['humans'][0])   # no trick ends this mission early
    room.on_table(begun)
    for p in phones:
        p.catch_up(stage='before_trick')
    for _ in phones:
        together(room, phones)
        actor = phone_of(phones, engine.s['turn'])
        revision = actor.game['revision']
        actor.send('play_card', card=actor.game['me']['legal_cards'][0])
        actor.catch_up(revision + 1)
    for p in phones:
        p.read(lambda q: q.game['resolving'] is not None)
        assert p.game['resolving']['trick'] == 1 and p.game['resolving']['until'] > 0
        assert p.game['me']['legal_cards'] == [] and p.game['me']['play_reason'] == RESOLVING
        assert p.game['last_trick']['index'] == 1 and p.game['trick'] == []
    held = time.monotonic()
    winner = phone_of(phones, engine.s['turn'])
    marker = len(winner.fx)
    winner.send('play_card', card=winner.game['me']['hand'][0])     # the page would not offer it
    winner.read(lambda q: len(q.fx) > marker)
    assert (winner.fx[-1]['kind'], winner.fx[-1]['code']) == ('invalid', 'resolving')
    for p in phones:                                                # and then nobody does anything
        p.read(lambda q: q.game['resolving'] is None)
        assert p.game['events'][-1]['type'] == 'TURN_STARTED' and p.game['events'][-1]['seat'] == winner.pid
    assert time.monotonic() - held > 1.0                            # it was the timer, after its hold
    assert engine.s['resolving'] is None and room.session._hold is None
    together(room, phones)
    assert winner.game['me']['legal_cards']
    revision = winner.game['revision']
    winner.send('play_card', card=winner.game['me']['legal_cards'][0])
    winner.catch_up(revision + 1)
    assert len(engine.s['trick']) == 1 and winner.game['stage'] == 'in_trick'
