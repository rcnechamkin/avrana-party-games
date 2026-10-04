"""EXPO's canonical documents stay true to the code (AVR-215).

games/expo/docs/ is the durable design record. These checks stop it drifting:

  * the mission table in MISSION_MODEL.md equals games/expo/content.py;
  * the task catalog in VTT_REFERENCE.md equals games/expo/content/tasks.json;
  * every conflict code the content uses to block something is a row of the conflict register;
  * every test the documents cite exists, and every pinned defect test is cited.

They read files only. A failure here means a definition or a test changed without its document
(or the reverse); fix both in the same commit.
"""
import ast
import json
import re
from pathlib import Path

import pytest

from games.expo import content

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'games' / 'expo' / 'docs'
REQUIRED = ('RULES_SPEC.md', 'GAME_STATE.md', 'ACTIONS.md', 'MISSION_MODEL.md', 'VTT_REFERENCE.md',
            'IMPLEMENTATION_PLAN.md', 'RECONCILIATION.md')
TEST_FILES = ('test_expo.py', 'test_expo_party.py', 'test_expo_contract.py', 'test_expo_coverage.py',
              'test_expo_persistence.py')


def read(name):
    return (DOCS / name).read_text(encoding='utf-8')


def table(name, marker):
    text = read(name)
    body = text.split(f'<!-- {marker}:start -->')[1].split(f'<!-- {marker}:end -->')[0]
    rows = [[c.strip() for c in line.strip().strip('|').split('|')]
            for line in body.strip().splitlines() if line.startswith('|')]
    return rows[2:]                                   # drop the header and the rule line


def defined_tests():
    names = {}
    for file in TEST_FILES:
        tree = ast.parse((ROOT / 'tests' / file).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                xfail = any('xfail' in ast.unparse(d) for d in node.decorator_list)
                names[node.name] = xfail
    return names


def test_the_six_required_documents_and_the_reconciliation_exist():
    for name in REQUIRED:
        assert (DOCS / name).is_file(), name
        assert read(name).startswith('# EXPO'), name


def test_the_mission_table_matches_the_content():
    rows = {int(r[0]): r for r in table('MISSION_MODEL.md', 'mission-table')}
    assert sorted(rows) == list(range(1, 33))
    for number, (_, target, allocation, communication, objective, status, _source) in rows.items():
        assert int(target) == content.TARGETS[number], number
        if number in content.BLOCKED:
            assert status == 'blocked ' + content.BLOCKED[number][:3], number
            assert (allocation, communication, objective) == ('-', '-', '-'), number
            continue
        m = content.mission(number)
        assert status == 'enabled', number
        assert (allocation, communication, objective) == (
            m['allocation'], m['communication'], m['objective'] or '-'), number
    text = read('MISSION_MODEL.md')
    assert content.mission(32)['fixed'] == ['0tricks', 'exactly3trickInARow', '2tricksInARow', 'firstAndLastTrick']
    assert all('`%s`' % k in text for k in content.mission(32)['fixed'])
    timed = content.mission(16, True)
    assert (timed['seconds'], timed['communication'], timed['volunteers']) == (150, 'normal', 1)
    for number in range(33, 51):                      # the continuation, as documented
        m = content.mission(number)
        assert (m['target'], m['allocation'], m['communication'], m['objective']) == (
            number - 15, 'free', 'normal', None)


def test_the_two_player_availability_matches_the_catalog():
    text = read('MISSION_MODEL.md')
    off = sorted(m['id'] for m in content.catalog(2) if not m['enabled'] and m['id'] not in content.BLOCKED)
    assert off == [16]
    assert 'the following are refused (DEFERRED C11): the `volunteer`\nmission (16) and distress in any mission.' in text
    assert 'with one shared token: missions 11, 21 to 25 and 27' in text


def test_the_task_catalog_matches_the_content():
    rows = table('VTT_REFERENCE.md', 'task-catalog')
    tasks = json.loads((ROOT / 'games/expo/content/tasks.json').read_text(encoding='utf-8'))
    assert len(rows) == len(tasks) == 96
    for row, task in zip(rows, tasks):
        d = task['difficulty']
        status = 'enabled' if task['enabled'] else 'blocked ' + task['blocked'][:3]
        assert row[:4] == ['`%s`' % task['id'], '%s / %s / %s' % (d['3'], d['4'], d['5']),
                           '`%s`' % task['family'], status], task['id']
    assert sum(t['enabled'] for t in tasks) == 92


def test_every_task_has_a_recorded_provenance_class():
    # Owner decision Q4 (AVR-243): each task is officially corroborated, reference-derived or
    # quarantined. An enabled task is never quarantined; a disabled one is never plain reference.
    rows = table('VTT_REFERENCE.md', 'task-catalog')
    tasks = {'`%s`' % t['id']: t for t in content.TASKS.values()}
    classes = {}
    for task_id, _difficulty, _family, _status, evidence in rows:
        kind = evidence.split(' ')[0]
        assert kind in ('corroborated', 'reference', 'quarantined'), task_id
        if kind == 'corroborated':
            assert re.fullmatch(r'corroborated \((R p\d+(, p\d+)*|L M\d+)\)', evidence), task_id
        assert (kind == 'quarantined') <= (not tasks[task_id]['enabled']), task_id
        assert (kind == 'reference') <= tasks[task_id]['enabled'], task_id
        classes[kind] = classes.get(kind, 0) + 1
    assert classes == {'corroborated': 22, 'reference': 70, 'quarantined': 4}
    # Every corroborated task is enabled (5with7 since AVR-249); only quarantined ones are not.
    pending = [i for i, *_rest, e in rows if e.startswith('corroborated') and not tasks[i]['enabled']]
    assert pending == []


def test_every_blocking_conflict_is_in_the_register():
    register = set(re.findall(r'^\| (C\d\d) \|', read('VTT_REFERENCE.md'), re.M))
    assert register == {'C%02d' % i for i in range(1, 21)}
    used = {reason[:3] for reason in content.BLOCKED.values()}
    used |= {t['blocked'][:3] for t in content.TASKS.values() if not t['enabled']}
    used |= {m['reason'][:3] for m in content.catalog(2) if m['reason']}
    assert used <= register, used - register


@pytest.mark.parametrize('name', REQUIRED)
def test_every_cited_test_exists(name):
    known = defined_tests()
    cited = set(re.findall(r'`(test_[a-z0-9_]+)`', read(name)))
    assert cited <= set(known), sorted(cited - set(known))


def test_every_pinned_defect_is_recorded_and_every_issue_is_named():
    known = defined_tests()
    pinned = {n for n, xfail in known.items() if xfail}
    assert pinned and all(n.startswith('test_defect_') for n in pinned)
    reconciliation = read('RECONCILIATION.md')
    assert all('`%s`' % n in reconciliation for n in pinned), pinned
    for entry in ('E-D1', 'E-D2', 'E-D3', 'E-D4', 'E-D5', 'E-D6', 'E-D7', 'E-D8'):
        row = next(line for line in reconciliation.splitlines() if line.startswith('| %s |' % entry))
        assert re.search(r'AVR-\d+', row), entry
