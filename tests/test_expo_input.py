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


# ---- AVR-268: a request id that cannot be stored ------------------------------------------------
# An accepted request id is kept in the request memory, which is part of the snapshot file. One
# that cannot be written as UTF-8 stopped the table from saving, and every later command raised.

UNSTORABLE = {'a lone surrogate': '\ud800', 'a surrogate inside an id': 'abc\udfffdef', 'a NUL': 'a\x00b',
              'a newline': 'a\nb', 'an escape': '\x1b[2J', 'a delete': 'a\x7f', 'non-ASCII text': 'café',
              'a line separator': 'a b'}


def saved_engine(path):
    return json.loads(path.read_text(encoding='utf-8'))['engine']


def stored_table(path, humans=3):
    s = ExpoSession(random.Random(4), snapshot_path=path)
    tokens = ['human-%d' % i for i in range(humans)]
    for t in tokens:
        s.join(t, t)
        s.set_ready(t, True)
    s.start(tokens[0])
    s.tick(s.gen)
    return s, tokens


@pytest.mark.parametrize('case', UNSTORABLE)
def test_a_request_id_that_is_not_plain_printable_text_is_refused(case):
    e, cap = table(1)
    before = frozen(e)
    bad = dict(command(e, cap, 'propose', proposal={'kind': 'end'}), request=UNSTORABLE[case])
    with pytest.raises(Invalid) as refusal:
        e.apply(cap, bad, 100)
    assert refusal.value.code == 'payload' and frozen(e) == before


@pytest.mark.parametrize('request_id', ['1', 'x' * 80, '3f2b6c1e-8a51-4c7e-9d2a-0b1c2d3e4f5a',
                                        '3F2B6C1E-8A51-4C7E-9D2A-0B1C2D3E4F5A', '-', 'Az09-' * 16])
def test_a_plain_request_id_is_still_accepted(request_id):
    e, cap = table(1)
    assert e.apply(cap, dict(command(e, cap, 'propose', proposal={'kind': 'end'}), request=request_id), 100)


@pytest.mark.parametrize('case', UNSTORABLE)
def test_an_unstorable_request_id_leaves_a_stored_table_saving_and_answering(case, tmp_path):
    path = tmp_path / 'crew.json'
    s, tokens = stored_table(path)
    e = s.engine
    seat = {s.players[t].pid: t for t in tokens}
    first, other = e.s['humans'][0], e.s['humans'][1]
    on_disk, before = saved_engine(path), frozen(e)
    bad = dict(command(e, first, 'propose', proposal={'kind': 'end'}), request=UNSTORABLE[case])
    assert [f['code'] for f in s.game_action(seat[first], bad)] == ['payload']
    assert frozen(s.engine) == before and saved_engine(path) == on_disk
    for t in tokens:
        s.state_for(t)
    s.game_tick()
    # A legal command is accepted, saved, and survives a restart from the file.
    q = e.selector()
    task = next(k for k in e.s['pool'] if e.eligible(k, q))
    assert s.game_action(seat[e.controller(q)], command(e, e.controller(q), 'choose_task', task=task)) == []
    again = ExpoSession(random.Random(1), snapshot_path=path)
    assert again.recovery_error is None and again.engine.s['assignments'] == {task: q}


def test_a_snapshot_that_cannot_be_written_as_text_is_a_storage_failure_not_a_crash(tmp_path):
    # Whatever reaches the snapshot (a player name comes from the platform, not from EXPO), a
    # value the file cannot hold rolls the command back like any other failed write.
    path = tmp_path / 'crew.json'
    s, tokens = stored_table(path)
    e = s.engine
    seat = {s.players[t].pid: t for t in tokens}
    on_disk, before = saved_engine(path), frozen(e)
    s.players[tokens[0]].name = 'bad\ud800name'
    q = e.selector()
    task = next(k for k in e.s['pool'] if e.eligible(k, q))
    msg = command(e, e.controller(q), 'choose_task', task=task)
    assert [f['code'] for f in s.game_action(seat[e.controller(q)], msg)] == ['storage']
    assert frozen(s.engine) == before and saved_engine(path) == on_disk
    e = s.engine                                 # the rollback put the engine back from its snapshot
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('.crew-')]      # no temp file left
    s.players[tokens[0]].name = 'human-0'
    assert s.game_action(seat[e.controller(q)], msg) == []                         # the same request, sent again
    assert ExpoSession(random.Random(1), snapshot_path=path).engine.s['assignments'] == {task: q}


@pytest.mark.parametrize('value', [object(), b'bytes', {1, 2}, nested(100000), 'bad\ud800name', float('nan')],
                         ids=['an object', 'bytes', 'a set', 'nested too deep', 'a lone surrogate', 'not a number'])
def test_the_store_reports_any_snapshot_it_cannot_write_as_a_failed_write(value, tmp_path):
    from games.expo.storage import SnapshotStore
    store = SnapshotStore(tmp_path / 'crew.json')
    store.write({'kept': 1})
    if isinstance(value, float):                 # JSON as Python writes it can hold this one
        store.write({'value': value})
        return
    with pytest.raises(OSError):
        store.write({'value': value})
    assert store.read() == {'kept': 1}
    assert [p.name for p in tmp_path.iterdir()] == ['crew.json']


# ---- AVR-273: the request memory must fit in a file the server reads back -----------------------
# The snapshot file is refused above MAX_SNAPSHOT_BYTES when it is read. An accepted request id is
# written into it twice, and a quotation mark took four bytes the second time: two seats could
# fill the request memory of one attempt with ids of 80 quotation marks and leave a file that a
# restart refused. Two rules now: an id is letters, digits and "-", and a file over the limit is
# never written.

NOT_AN_ID = {'quotation marks': '"' * 80, 'a backslash': 'a\\b', 'a space': 'a b', 'an underscore': 'a_b',
             'a full stop': '0.5', 'a colon': 'a:b', 'a slash': 'a/b', 'a brace': '{a}', 'a tilde': '~',
             'a plus sign': 'a+b', 'a non-ASCII letter': 'café', 'a non-ASCII digit': '٣',
             '81 characters': 'x' * 81, 'nothing': ''}


def end_or_decline(e, i, request_id):
    # What the two seats alternate: one proposes to end the table, the other declines.
    verb = {'t': 'propose', 'proposal': {'kind': 'end'}} if i % 2 == 0 else {'t': 'confirm', 'yes': False}
    return {**verb, 'attempt': e.s['attempt'], 'revision': e.s['revision'], 'request': request_id}


def longest_id(i):
    return ('%d' % i).rjust(80, 'Z')             # 80 characters, the most an id may have


@pytest.mark.parametrize('case', NOT_AN_ID)
def test_a_request_id_is_letters_digits_and_hyphens_only(case, tmp_path):
    path = tmp_path / 'crew.json'
    s, tokens = stored_table(path)
    e = s.engine
    seat = {s.players[t].pid: t for t in tokens}
    first = e.s['humans'][0]
    on_disk, before = saved_engine(path), frozen(e)
    bad = end_or_decline(e, 0, NOT_AN_ID[case])
    with pytest.raises(Invalid) as refusal:
        e.apply(first, dict(bad), 100)
    assert refusal.value.code == 'payload' and frozen(e) == before
    assert [f['code'] for f in s.game_action(seat[first], bad)] == ['payload']
    assert frozen(s.engine) == before and saved_engine(path) == on_disk


def test_two_seats_filling_the_request_memory_leave_a_file_the_server_reads_back(tmp_path):
    # The run from the issue, in full: 10,000 accepted commands in one attempt, each with the
    # longest id allowed. Every save replaces the whole file, so only the last one decides what
    # a restart finds; to keep the test to seconds, most commands go to the table's engine
    # without their save, and every thousandth and the last two go through the adapter.
    from games.expo.storage import MAX_SNAPSHOT_BYTES
    path = tmp_path / 'crew.json'
    s, tokens = stored_table(path, humans=2)
    e = s.engine
    seat = {s.players[t].pid: t for t in tokens}
    pair = e.s['humans']
    assert len(pair) == 2 and e.s['dedup'] == {}
    limit = 10000
    for i in range(limit):
        actor, msg = pair[i % 2], end_or_decline(e, i, longest_id(i))
        if i % 1000 == 999 or i >= limit - 2:
            assert s.game_action(seat[actor], msg) == [] and s.engine is e
            assert path.stat().st_size <= MAX_SNAPSHOT_BYTES
        else:
            assert e.apply(actor, msg, 100) is True
    assert len(e.s['dedup']) == limit and e.s['proposal'] is None
    # The attempt is full: the next command is refused by the request limit, and nothing changes.
    on_disk, before = saved_engine(path), frozen(e)
    more = end_or_decline(e, limit, longest_id(limit))
    assert [f['code'] for f in s.game_action(seat[pair[0]], more)] == ['requests']
    assert frozen(s.engine) == before and saved_engine(path) == on_disk
    assert on_disk['state']['dedup'] == e.s['dedup']
    assert path.stat().st_size <= MAX_SNAPSHOT_BYTES
    again = ExpoSession(random.Random(1), snapshot_path=path)
    assert again.recovery_error is None and again.engine.s['dedup'] == e.s['dedup']
    assert again.engine.s['attempt'] == e.s['attempt'] and again.engine.s['revision'] == e.s['revision'] + 1


def test_a_command_whose_snapshot_would_pass_the_size_limit_is_rolled_back_and_the_table_restarts(tmp_path, monkeypatch):
    # The size rule on its own, with ids the engine accepts and the limit brought down to just
    # above the table's file: the command that would take the file past it is a failed write.
    from games.expo import storage
    path = tmp_path / 'crew.json'
    s, tokens = stored_table(path, humans=2)
    seat = {s.players[t].pid: t for t in tokens}
    pair = s.engine.s['humans']
    limit = path.stat().st_size + 1500
    monkeypatch.setattr(storage, 'MAX_SNAPSHOT_BYTES', limit)
    accepted = 0
    for i in range(40):
        e = s.engine
        on_disk, before = path.read_bytes(), frozen(e)
        msg = end_or_decline(e, i, longest_id(i))
        answer = s.game_action(seat[pair[i % 2]], msg)
        if answer:
            break
        accepted += 1
        assert path.stat().st_size <= limit
    assert [f['code'] for f in answer] == ['storage'] and accepted >= 2
    # Rolled back: the table, its request memory and the file are those of the last accepted command.
    assert frozen(s.engine) == before and path.read_bytes() == on_disk
    assert len(s.engine.s['dedup']) == accepted and not any(msg['request'] in k for k in s.engine.s['dedup'])
    assert len(on_disk) <= limit and [p.name for p in tmp_path.iterdir()] == ['crew.json']
    for t in tokens:
        s.state_for(t)
    assert [f['code'] for f in s.game_action(seat[pair[i % 2]], msg)] == ['storage']     # and again
    assert frozen(s.engine) == before and path.read_bytes() == on_disk
    # A restart reads that file under the same limit and has the same table.
    again = ExpoSession(random.Random(1), snapshot_path=path)
    assert again.recovery_error is None and again.engine.s['dedup'] == s.engine.s['dedup']
    assert again.engine.s['proposal'] == s.engine.s['proposal']
    # The refused request was never remembered: with room in the file it is accepted as sent.
    monkeypatch.setattr(storage, 'MAX_SNAPSHOT_BYTES', limit + 100000)
    assert s.game_action(seat[pair[i % 2]], msg) == []
    assert len(s.engine.s['dedup']) == accepted + 1
    assert ExpoSession(random.Random(1), snapshot_path=path).engine.s['dedup'] == s.engine.s['dedup']


def test_the_store_counts_the_bytes_of_the_file_against_the_limit_it_reads_with(tmp_path, monkeypatch):
    from games.expo import storage
    monkeypatch.setattr(storage, 'MAX_SNAPSHOT_BYTES', 100)
    path = tmp_path / 'crew.json'
    store = storage.SnapshotStore(path)
    exact = {'v': 'x' * (100 - len('{"v": ""}'))}
    store.write(exact)                                               # a file of exactly the limit
    assert path.stat().st_size == 100 and store.read() == exact
    for over in ({'v': exact['v'] + 'x'},                            # one byte more
                 {'v': 'é' * 60}):                               # 60 characters, 120 bytes
        with pytest.raises(OSError):
            store.write(over)
        assert store.read() == exact and [p.name for p in tmp_path.iterdir()] == ['crew.json']
    path.write_bytes(b' ' * 101)                                     # a file over the limit, however it came
    with pytest.raises(ValueError):
        store.read()
