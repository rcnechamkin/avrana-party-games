"""EXPO persistence hardening (AVR-242): reconciliation entries E-D5, E-D6 and E-D7.

E-D5: the content hash covers every mission definition as well as the task catalog.
E-D7: a timed mission runs on the monotonic clock; a restored one continues only when the clocks
      prove how long the server was down, and otherwise ends. It never gains time.
E-D6: only accepted requests are remembered, deliberately (games/expo/docs/GAME_STATE.md).
"""
import hashlib
import json
import random

import pytest

from games.expo import content, engine as engine_module, game
from games.expo.content import TASKS
from games.expo.engine import Engine, Invalid
from games.expo.game import ExpoSession

from test_expo import act, command, playing, session
from test_expo_coverage import agree, by_pid, send, stored


# ---- E-D5 the content hash ---------------------------------------------------------------------

def test_the_content_hash_is_the_hash_of_the_tasks_and_of_every_mission_definition():
    assert content.CONTENT_HASH == content.content_hash()
    assert content.CONTENT_HASH != hashlib.sha256(content._BYTES + b'crew-missions-v1').hexdigest()
    assert len(content.CONTENT_HASH) == 64


def retarget(monkeypatch, number, target):
    targets = list(content.TARGETS)
    targets[number] = target
    monkeypatch.setattr(content, 'TARGETS', targets)


CHANGES = {
    'the target of a numbered mission': lambda m: retarget(m, 7, content.TARGETS[7] + 1),
    'a mission becomes blocked': lambda m: m.setitem(content.BLOCKED, 2, 'C99: withdrawn'),
    'a blocked mission is opened': lambda m: m.delitem(content.BLOCKED, 3),
    'a blocking reason changes': lambda m: m.setitem(content.BLOCKED, 3, 'C02: reworded'),
    'the task catalog changes': lambda m: m.setattr(content, '_BYTES', content._BYTES + b' '),
}


@pytest.mark.parametrize('change', CHANGES)
def test_any_change_to_the_content_changes_the_hash(change, monkeypatch):
    before = content.content_hash()
    CHANGES[change](monkeypatch)
    assert content.content_hash() != before


def test_a_change_to_the_timed_variant_alone_changes_the_hash(monkeypatch):
    original = content.mission

    def changed(n, timed=False):
        m = original(n, timed)
        if n == 16 and timed:
            m['seconds'] = 120
        return m
    before = content.content_hash()
    monkeypatch.setattr(content, 'mission', changed)
    assert content.mission(16) == original(16)                       # the untimed definition is the same
    assert content.content_hash() != before


def modifier_change(monkeypatch, number, **fields):
    """The definition of one mission differs in the given fields, as an edit to mission() would."""
    original = content.mission

    def changed(n, timed=False):
        m = original(n, timed)
        if n == number:
            m.update(fields)
        return m
    monkeypatch.setattr(content, 'mission', changed)


@pytest.mark.parametrize('number,fields', [(9, {'communication': 'normal'}), (8, {'objective': None}),
                                           (25, {'allocation': 'normal'}), (16, {'seconds': 120}),
                                           (32, {'fixed': ['0tricks']}), (40, {'target': 26})])
def test_a_changed_modifier_timer_or_fixed_task_list_changes_the_hash(number, fields, monkeypatch):
    before = content.content_hash()
    modifier_change(monkeypatch, number, **fields)
    assert content.content_hash() != before


def test_a_snapshot_taken_before_a_mission_table_change_is_refused_after_it(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    s, tokens = session(path=path)                                   # a table playing mission 1
    assert s.engine.s['mission']['id'] == 1 and s.engine.s['content'] == content.CONTENT_HASH
    snap = json.loads(json.dumps(s.engine.snapshot()))
    on_disk = path.read_text(encoding='utf-8')
    retarget(monkeypatch, 7, content.TARGETS[7] + 1)                 # another mission changes
    after = content.content_hash()
    assert after != content.CONTENT_HASH
    monkeypatch.setattr(engine_module, 'CONTENT_HASH', after)        # the server restarts on new code
    assert content.mission(1) == snap['state']['mission']            # the mission in flight is as it was
    with pytest.raises(Invalid) as refused:
        Engine.restore(snap)
    assert refused.value.code == 'snapshot'
    again = ExpoSession(random.Random(1), snapshot_path=path)
    assert again.engine is None and again.recovery_error and again.phase == 'lobby'
    assert path.read_text(encoding='utf-8') == on_disk               # refused, never overwritten
    again.join('fresh', 'fresh')
    again.set_ready('fresh', True)
    assert again.start('fresh')[0]['msg'] == again.recovery_error    # and no new table over it


def test_an_unchanged_mission_table_still_restores(tmp_path):
    path = tmp_path / 'crew.json'
    s, tokens = session(path=path)
    again = ExpoSession(random.Random(1), snapshot_path=path)
    assert again.recovery_error is None and again.engine.s['content'] == content.CONTENT_HASH


# ---- E-D7 the clock ----------------------------------------------------------------------------

class Clock:
    """The adapter's two clocks and the boot they belong to, set by hand."""

    def __init__(self, monkeypatch, wall, mono, boot='boot-a'):
        self.wall, self.mono, self.boot = wall, mono, boot
        monkeypatch.setattr(game, '_wall', lambda: self.wall)
        monkeypatch.setattr(game, '_mono', lambda: self.mono)
        monkeypatch.setattr(game, '_boot', lambda: self.boot)

    def pass_time(self, seconds):
        self.wall += seconds
        self.mono += seconds


def timed_table(path, clock, begin=True):
    """A stored, timed mission 16 table; with `begin` its 150 seconds start at the clock's now."""
    for seed in range(40):
        s = ExpoSession(random.Random(seed), snapshot_path=path)
        tokens = [f'human-{i}' for i in range(3)]
        for t in tokens:
            s.join(t, t)
            s.set_ready(t, True)
        s.set_settings(tokens[0], {'timed': True})
        s.set_settings(tokens[0], {'mission': 16})
        s.start(tokens[0])
        s.tick(s.gen)
        e, seat = s.engine, by_pid(s, tokens)
        assert e.s['mission']['seconds'] == 150 and e.s['expiry'] is None
        send(s, seat[e.controller(e.selector())], 'volunteer', yes=True)
        for k, q in list(e.s['assignments'].items()):
            if TASKS[k]['params'].get('predict'):
                send(s, seat[q], 'predict', task=k, count=0)
        if e.s['phase'] == 'assistance':                             # else: an ineligible volunteer
            if begin:
                agree(s, tokens, 'begin')
                assert e.s['expiry'] == pytest.approx(clock.mono + 150, abs=2.0)
            return s, tokens
        s.store.clear()
    pytest.fail('no timed fixture')


def remaining(s, clock):
    """Seconds a browser would show: the view's wall-clock deadline against the wall clock."""
    return s.game_state(None)['expiry'] - clock.wall


def test_a_timed_mission_runs_on_the_monotonic_clock_and_browsers_get_a_wall_clock_moment(tmp_path, monkeypatch):
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(tmp_path / 'crew.json', clock)
    assert s.engine.s['expiry'] == 5150.0                            # the engine's own clock
    assert s.game_state(None)['expiry'] == 1150.0                    # what a browser counts down to
    assert s.game_state(tokens[0])['expiry'] == 1150.0
    assert s.deadline == 1150.0                                      # handed to the shared timer
    clock.pass_time(149)
    s.game_tick()
    assert s.engine.s['result'] is None and remaining(s, clock) == 1.0
    clock.pass_time(1)
    s.game_tick()
    assert s.engine.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}
    assert s.game_state(None)['expiry'] is None and s.deadline is None


def test_on_the_real_clocks_the_shared_timer_and_the_browsers_get_the_same_150_seconds(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(game, '_boot', lambda: 'this-boot')         # not every host can name its boot

    class Real:
        mono = property(lambda self: time.monotonic())
    wall = time.time()
    s, tokens = timed_table(tmp_path / 'crew.json', Real())
    assert s.remaining() == pytest.approx(150.0, abs=2.0)            # core/session.py, monotonic
    assert s.game_state(None)['expiry'] == pytest.approx(wall + 150.0, abs=2.0)
    assert s.engine.s['expiry'] == pytest.approx(time.monotonic() + 150.0, abs=2.0)
    saved = json.loads((tmp_path / 'crew.json').read_text(encoding='utf-8'))['clock']
    assert saved['wall'] == pytest.approx(wall, abs=2.0) and saved['mono'] == pytest.approx(time.monotonic(), abs=2.0)
    again = restart(tmp_path / 'crew.json')                          # a restart on this very boot
    assert again.engine.s['result'] is None and again.remaining() == pytest.approx(150.0, abs=2.0)


@pytest.mark.parametrize('step', [-600.0, -1.0, 3600.0, 86400.0 * 400])
def test_a_wall_clock_step_during_a_live_timed_mission_neither_grants_nor_takes_time(step, tmp_path, monkeypatch):
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(tmp_path / 'crew.json', clock)
    clock.pass_time(30)
    clock.wall += step                                               # the wall clock is corrected
    s.game_tick()
    assert s.engine.s['result'] is None and s.engine.s['expiry'] == 5150.0
    assert remaining(s, clock) == 120.0                              # exactly what was left
    clock.pass_time(119)
    s.game_tick()
    assert s.engine.s['result'] is None
    clock.pass_time(1)                                               # 150 seconds of real play
    seat = by_pid(s, tokens)
    turn = s.engine.s['turn']
    refused = send(s, seat[turn], 'play_card', card=s.engine.playable(turn)[0])
    assert refused[0]['code'] == 'stale'                             # the play revealed the deadline
    assert s.engine.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}


def restart(path):
    return ExpoSession(random.Random(99), snapshot_path=path)


def test_a_restart_on_the_same_boot_continues_the_deadline_and_charges_the_downtime(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(path, clock)
    on_disk = path.read_text(encoding='utf-8')
    assert json.loads(on_disk)['clock'] == {'wall': 1000.0, 'mono': 5000.0, 'boot': 'boot-a'}
    clock.pass_time(60)                                              # down for a minute; both clocks agree
    again = restart(path)
    assert again.recovery_error is None and again.engine.s['result'] is None
    assert again.engine.s['expiry'] == 5150.0 and remaining(again, clock) == 90.0
    assert stored(again.engine.snapshot()['state']) == stored(s.engine.snapshot()['state'])
    assert path.read_text(encoding='utf-8') == on_disk               # restoring writes nothing
    clock.pass_time(90)
    again.game_tick()
    assert again.engine.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}


def test_a_timed_table_restored_after_its_deadline_has_already_failed(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(path, clock)
    on_disk = path.read_text(encoding='utf-8')
    clock.pass_time(150)                                             # the server was down until then
    again = restart(path)
    assert again.recovery_error is None
    assert again.engine.s['result'] == {'status': 'failed', 'reason': 'Time has run out.'}
    assert again.phase == 'mission_result' and again.engine.s['expiry'] is None and again.deadline is None
    assert again.engine.s['hands'] == s.engine.s['hands'] and again.engine.s['history'] == []
    assert again.engine.s['attempts'] == 1 and again.engine.s['log'] == []
    assert path.read_text(encoding='utf-8') == on_disk
    for t in tokens:
        again.join(t, t)
    seat = by_pid(again, tokens)
    turn = again.engine.s['turn']
    refused = send(again, seat[turn], 'play_card', card=again.engine.playable(turn)[0])
    assert refused[0]['code'] == 'phase'                             # the deal is over
    agree(again, tokens, 'retry', keep=True)                         # and the crew may dive again
    assert again.engine.s['phase'] == 'allocation' and again.engine.s['result'] is None


# (wall, mono, boot) at the restart, for a snapshot written at wall 1000, mono 5000 on boot-a
# with 150 s to run.
UNTRUSTED = {
    'the wall clock stepped backward': (400.0, 5060.0, 'boot-a'),
    'the wall clock stepped back to before the snapshot': (990.0, 5060.0, 'boot-a'),
    'the wall clock jumped forward': (99999.0, 5060.0, 'boot-a'),
    'the wall clock is just outside the tolerance, ahead': (1062.1, 5060.0, 'boot-a'),
    'the wall clock is just outside the tolerance, behind': (1057.9, 5060.0, 'boot-a'),
    'a reboot: the monotonic clock began again': (1060.0, 12.0, 'boot-b'),
    'a reboot without a real-time clock: the wall clock resumed where it stopped': (1001.0, 12.0, 'boot-b'),
    'a reboot after a longer uptime than before': (1060.0, 9000.0, 'boot-b'),
    'a reboot whose two clocks line up exactly as before': (1005.0, 5005.0, 'boot-b'),
    'a host that cannot name its boot': (1060.0, 5060.0, None),
    'a suspend: the wall clock ran on, the monotonic clock did not': (1060.0, 5010.0, 'boot-a'),
    'both clocks went backward': (500.0, 4500.0, 'boot-a'),
}


@pytest.mark.parametrize('case', UNTRUSTED)
def test_a_timed_table_restored_under_a_clock_that_cannot_be_trusted_ends_and_never_gains_time(case, tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(path, clock)
    clock.wall, clock.mono, clock.boot = UNTRUSTED[case]
    again = restart(path)
    ended = {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}
    assert again.recovery_error is None                              # the table itself is kept
    assert again.engine.s['result'] == ended
    assert again.phase == 'mission_result' and again.engine.s['expiry'] is None and again.deadline is None
    assert again.game_state(None)['expiry'] is None
    assert again.engine.s['attempts'] == 1 and again.engine.s['log'] == []   # a counted attempt, no success
    assert again.engine.s['hands'] == s.engine.s['hands']
    # The end is written down, so no later restart can find the deadline still running: not even
    # one back on the first boot with both clocks exactly where a live deadline would expect them.
    on_disk = json.loads(path.read_text(encoding='utf-8'))
    assert on_disk['engine']['state']['result'] == ended and on_disk['engine']['state']['expiry'] is None
    clock.wall, clock.mono, clock.boot = 1020.0, 5020.0, 'boot-a'
    later = restart(path)
    assert later.engine.s['result'] == ended and later.engine.s['expiry'] is None
    for t in tokens:
        again.join(t, t)
    agree(again, tokens, 'retry', keep=True)                         # the crew is not stranded
    assert again.engine.s['phase'] == 'allocation'


def test_a_timed_snapshot_without_a_clock_record_ends_the_attempt(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    timed_table(path, clock)
    huge = 10 ** 400
    ok = {'wall': 1000.0, 'mono': 5000.0, 'boot': 'boot-a'}
    assert restart(path).engine.s['result'] is None                  # the record as written is trusted
    for bad in (None, {}, {'wall': 1000.0}, [1000.0, 5000.0], dict(ok, wall='1000'), dict(ok, wall=True),
                dict(ok, wall=float('nan')), dict(ok, mono=float('nan')), dict(ok, wall=float('inf')),
                dict(ok, mono=float('-inf')), dict(ok, wall=huge), dict(ok, mono=-huge),
                dict(ok, wall=-huge - 4000, mono=-huge), dict(ok, wall=1e300, mono=1e300),
                {'wall': 1000.0, 'mono': 5000.0}, dict(ok, boot=None), dict(ok, boot=True), dict(ok, boot=['boot-a'])):
        saved = json.loads(path.read_text(encoding='utf-8'))
        if bad is None:
            del saved['clock']
        else:
            saved['clock'] = bad
        path.write_text(json.dumps(saved), encoding='utf-8')
        again = restart(path)
        assert again.recovery_error is None
        assert again.engine.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}, bad
        saved = json.loads(path.read_text(encoding='utf-8'))         # put the running table back
        saved['engine']['state'].update(result=None, expiry=5150.0, phase='before_trick')
        saved['engine']['state']['revision'] -= 2
        path.write_text(json.dumps(saved), encoding='utf-8')


@pytest.mark.parametrize('case', UNTRUSTED)
def test_a_table_with_no_running_deadline_restores_whatever_the_clocks_say(case, tmp_path, monkeypatch):
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    untimed = tmp_path / 'untimed.json'
    s, tokens = session(path=untimed)
    waiting = tmp_path / 'timed-not-begun.json'
    t, _ = timed_table(waiting, clock, begin=False)                  # timed, but the clock is not running
    clock.wall, clock.mono, clock.boot = UNTRUSTED[case]
    for path, before in ((untimed, s), (waiting, t)):
        again = restart(path)
        assert again.recovery_error is None and again.engine.s['result'] is None
        assert again.engine.s['expiry'] is None
        assert stored(again.engine.snapshot()['state']) == stored(before.engine.snapshot()['state'])


def test_the_engine_expires_only_a_running_deadline():
    e = playing()
    before = e.snapshot()
    assert e.expire() is False and e.snapshot() == before            # untimed: nothing to end
    e.s['expiry'] = 200
    assert e.expire('because') is True
    assert e.s['result'] == {'status': 'failed', 'reason': 'because'} and e.s['expiry'] is None
    assert e.s['revision'] == before['state']['revision'] + 1
    after = e.snapshot()
    assert e.expire() is False and e.snapshot() == after             # and only once


# ---- E-D6 request memory: accepted requests only, on purpose -----------------------------------

def test_a_flood_of_rejected_requests_is_not_remembered_and_cannot_use_up_the_request_limit():
    e = playing()
    turn = e.s['turn']
    idle = next(q for q in e.s['humans'] if q != turn)
    before = e.snapshot()
    for i in range(500):                                             # one seat, on its own
        msg = {**command(e, idle, 'play_card', card=e.playable(idle)[0]), 'request': 'flood-%d' % i}
        with pytest.raises(Invalid) as refused:
            e.apply(idle, msg, 100)
        assert refused.value.code == 'turn'
    assert e.snapshot() == before and e.s['dedup'] == before['state']['dedup']
    act(e, turn, 'play_card', card=e.playable(turn)[0])              # the table still moves
    assert len(e.s['dedup']) == len(before['state']['dedup']) + 1


def test_the_same_rejected_request_sent_again_gets_the_same_answer():
    e = playing()
    idle = next(q for q in e.s['humans'] if q != e.s['turn'])
    msg = command(e, idle, 'play_card', card=e.playable(idle)[0])
    before = e.snapshot()
    codes = []
    for _ in range(3):
        with pytest.raises(Invalid) as refused:
            e.apply(idle, msg, 100)
        codes.append((refused.value.code, str(refused.value)))
    assert len(set(codes)) == 1 and e.snapshot() == before


def test_a_rejected_request_id_used_again_is_a_new_request_and_is_remembered_once_accepted():
    e = playing()
    turn = e.s['turn']
    msg = command(e, turn, 'play_card', card='not-a-card')
    with pytest.raises(Invalid) as refused:
        e.apply(turn, msg, 100)
    assert refused.value.code == 'card'
    good = {**msg, 'card': e.playable(turn)[0]}                      # the same id, a legal card
    assert e.apply(turn, good, 100) is True
    after = e.snapshot()
    assert e.apply(turn, good, 100) is False and e.snapshot() == after       # now a known request
    with pytest.raises(Invalid) as refused:                         # and its id is taken
        e.apply(turn, {**good, 'card': 'blue:1' if good['card'] != 'blue:1' else 'blue:2'}, 100)
    assert refused.value.code == 'request' and e.snapshot() == after


def test_a_request_refused_only_because_the_disk_failed_succeeds_when_sent_again_unchanged(tmp_path, monkeypatch):
    s, tokens = session(path=tmp_path / 'crew.json')
    e = s.engine
    seat = by_pid(s, tokens)
    actor = e.controller(e.selector())
    msg = command(e, actor, 'choose_task', task=next(k for k in e.s['pool'] if e.eligible(k, e.selector())))
    working = s.store.write

    def broken(snapshot):
        raise OSError('disk unavailable')
    monkeypatch.setattr(s.store, 'write', broken)
    before = s.engine.snapshot()
    assert s.game_action(seat[actor], msg)[0]['code'] == 'storage'
    assert s.engine.snapshot() == before                             # not remembered either
    monkeypatch.setattr(s.store, 'write', working)
    assert s.game_action(seat[actor], msg) == []                     # the very same message
    assert s.engine.s['revision'] == before['state']['revision'] + 1
    assert s.game_action(seat[actor], msg) == [] and s.engine.s['revision'] == before['state']['revision'] + 1


@pytest.mark.parametrize('drift', [-1.9, 0.0, 1.9])
def test_clocks_that_agree_within_two_seconds_on_the_same_boot_are_trusted(drift, tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    timed_table(path, clock)
    clock.wall, clock.mono = 1060.0 + drift, 5060.0
    again = restart(path)
    assert again.engine.s['result'] is None and again.engine.s['expiry'] == 5150.0
    assert remaining(again, clock) == 90.0                           # the monotonic clock decides how much


def test_a_failed_write_after_a_wall_clock_step_leaves_the_shared_timer_on_the_true_deadline(tmp_path, monkeypatch):
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = timed_table(tmp_path / 'crew.json', clock)
    clock.wall -= 600                                                # corrected while the table is live

    def broken(snapshot):
        raise OSError('disk unavailable')
    monkeypatch.setattr(s.store, 'write', broken)
    seat = by_pid(s, tokens)
    turn = s.engine.s['turn']
    assert send(s, seat[turn], 'play_card', card=s.engine.playable(turn)[0])[0]['code'] == 'storage'
    assert s.engine.s['expiry'] == 5150.0 and s.engine.s['trick'] == []
    assert s.deadline == clock.wall + 150.0                          # not the moment from before the step


@pytest.mark.parametrize('boot', [None, ''])
def test_a_host_that_never_could_name_its_boot_ends_the_attempt_on_every_restart(boot, tmp_path, monkeypatch):
    # The snapshot was written with no boot identity and the restart has none either: two
    # unknowns are not the same boot, even with both clocks exactly where they would be.
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0, boot=boot)
    timed_table(path, clock)
    assert json.loads(path.read_text(encoding='utf-8'))['clock']['boot'] == boot
    clock.pass_time(5)
    again = restart(path)
    assert again.recovery_error is None
    assert again.engine.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}


@pytest.mark.parametrize('expiry,refused', [(5150.1, False), (1e9, False), (1e18, True), (float('inf'), True),
                                            (float('nan'), True), (10 ** 400, True), ('5150', True), (True, True)])
def test_a_saved_deadline_later_than_a_full_timer_is_not_resumed(expiry, refused, tmp_path, monkeypatch):
    # No attempt has more than its 150 seconds from the moment its snapshot was written.
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    timed_table(path, clock)
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['engine']['state']['expiry'] = expiry
    path.write_text(json.dumps(saved), encoding='utf-8')
    clock.pass_time(5)
    again = restart(path)
    assert bool(again.recovery_error) is refused
    if refused:                                                      # not a deadline at all
        assert again.engine is None
    else:                                                            # a deadline, but too late to be true
        assert again.engine.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}
        assert again.engine.s['expiry'] is None


def test_a_snapshot_with_a_deadline_on_an_untimed_mission_is_refused(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    Clock(monkeypatch, wall=1000.0, mono=5000.0)
    s, tokens = session(path=path)                                   # mission 1, untimed
    assert restart(path).recovery_error is None
    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['engine']['state']['mission']['seconds'] is None
    saved['engine']['state']['expiry'] = 5100.0
    path.write_text(json.dumps(saved), encoding='utf-8')
    again = restart(path)
    assert again.recovery_error and again.engine is None


@pytest.mark.parametrize('expiry', [5100.0, 10 ** 400, float('nan'), float('inf'), '5150', True])
@pytest.mark.parametrize('boot', ['boot-a', 'boot-b', None])
def test_a_snapshot_with_a_deadline_beside_a_result_is_refused_not_raised(expiry, boot, tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    timed_table(path, clock)
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['engine']['state'].update(result={'status': 'failed', 'reason': 'x'}, phase='mission_result', expiry=expiry)
    path.write_text(json.dumps(saved), encoding='utf-8')
    clock.boot = boot
    again = restart(path)
    assert again.recovery_error and again.engine is None and again.deadline is None
    again.game_tick()


def test_an_end_that_could_not_be_written_is_judged_again_and_a_reboot_still_ends_it(tmp_path, monkeypatch):
    path = tmp_path / 'crew.json'
    clock = Clock(monkeypatch, wall=1000.0, mono=5000.0)
    timed_table(path, clock)
    on_disk = path.read_text(encoding='utf-8')
    from games.expo.storage import SnapshotStore

    def broken(self, snapshot):
        raise OSError('disk unavailable')
    monkeypatch.setattr(SnapshotStore, 'write', broken)
    clock.wall, clock.mono, clock.boot = 1001.0, 12.0, 'boot-b'       # a reboot; the end cannot be saved
    again = restart(path)
    assert again.engine.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}
    assert path.read_text(encoding='utf-8') == on_disk               # the file still shows it running
    clock.wall, clock.mono = 1030.0, 41.0                            # the service restarts on that boot
    later = restart(path)
    assert later.engine.s['result'] == {'status': 'failed', 'reason': game.UNTRUSTED_CLOCK}
