"""Typed catalog. VTT-derived data remains attributed and conflicts stay disabled."""
from pathlib import Path
import hashlib
import json

_BYTES = (Path(__file__).parent / 'content' / 'tasks.json').read_bytes()
TASKS = {t['id']: t for t in json.loads(_BYTES)}
BLOCKED = {3: 'C02: supplied mission difficulty conflicts with VTT',
           4: 'C03: official mission difficulty missing',
           12: 'C12: prohibited-lead outcome needs clarification',
           14: 'C03: official mission difficulty missing',
           15: 'C03: official mission difficulty missing',
           19: 'C08: hardest-task tie ordering needs clarification',
           20: 'C06: supplied mission objective conflicts with VTT',
           26: 'C07: timed difficulty conflicts with VTT'}
TARGETS = [0, 1, 2, 4, 4, 5, 5, 6, 0, 7, 4, 8, 0, 5, 6, 6, 6,
           9, 9, 9, 10, 0, 11, 0, 12, 12, 10, 0, 14, 15, 16, 17, 0]


MISSIONS = range(1, 51)


def mission(number, timed=False):
    if type(number) is not int or number not in MISSIONS:
        raise ValueError('Choose a mission from 1 to 50.')
    if number in BLOCKED:
        raise ValueError(BLOCKED[number])
    m = {'id': number, 'target': TARGETS[number] if number <= 32 else number - 15,
         'allocation': 'normal', 'communication': 'normal', 'objective': None,
         'seconds': None, 'volunteers': 0, 'source': 'supplied logbook / rulebook'}
    if number == 6:
        m['allocation'] = 'one'
    if number in (10, 13):
        m['allocation'] = 'captain_one'
    if number == 9:
        m['communication'] = 'currents'
    if number == 11:
        m['communication'] = 'rapture'
    if 21 <= number <= 27:
        m['communication'] = 'terrain'
    if number == 8:
        m['objective'] = 'balance9'
    if number == 21:
        m['objective'] = 'balance1'
    if number == 23:
        m['objective'] = 'first_winner'
    if number == 27:
        m['objective'] = 'final_yellow5'
    if number in (17, 28, 29, 30, 31) or number > 32:
        m['allocation'] = 'free'
    if number == 25:
        m['allocation'] = 'skip_captain'
    if number == 32:
        m['fixed'] = ['0tricks', 'exactly3trickInARow', '2tricksInARow', 'firstAndLastTrick']
    if number == 16:
        m.update(allocation='volunteer', volunteers=1,
                 seconds=150 if timed else None,
                 communication='normal' if timed else 'none')
    return m


def content_hash():
    # A snapshot is only meaningful under the content it was written with (E-D5, AVR-242): the
    # task catalog and every mission as this module defines it, untimed and timed, a blocked
    # mission by its reason. A change to a target, a modifier, a fixed task list, a timer or the
    # blocked set changes the hash, whichever mission the saved table was playing. A rule that
    # lives in the engine or the evaluators instead is not in it: changing one needs a new
    # engine VERSION.
    table = []
    for number in MISSIONS:
        for timed in (False, True):
            try:
                table.append(mission(number, timed))
            except ValueError as e:
                table.append({'id': number, 'blocked': str(e)})
    return hashlib.sha256(_BYTES + json.dumps(table, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


CONTENT_HASH = content_hash()


def catalog(humans=3, timed=False):
    result = []
    for n in MISSIONS:
        try:
            m = mission(n, timed)
            reason = None
            if humans == 2 and m['allocation'] == 'volunteer':
                reason = 'C11: Tonoja volunteer handling needs clarification'
        except ValueError as e:
            reason = str(e)
        result.append({'id': n, 'enabled': reason is None, 'reason': reason})
    return result
