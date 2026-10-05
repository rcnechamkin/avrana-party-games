"""Task monitor library. Exact and reversible conditions wait for hand exhaustion.

`evaluate` gives a task's status. `judge` gives the same status and, for a failure, what kind of
failure the evaluator found (AVR-246): `violated` (something the task forbids happened),
`unreachable` (what the task needs can no longer happen) or `unmet_at_end` (the deal ended
without it). The kind is a label on a decision already made; it never changes the status."""
from .rules import COLORS, DECK, matches, rank, suit


VIOLATED, UNREACHABLE, UNMET = 'violated', 'unreachable', 'unmet_at_end'


def evaluate(definition, owner, state, prediction=None):
    return judge(definition, owner, state, prediction)[0]


def judge(definition, owner, state, prediction=None):
    hist = state['history']
    won = [h for h in hist if h['winner'] == owner]
    cards = [p['card'] for h in won for p in h['plays']]
    all_cards = [p['card'] for h in hist for p in h['plays']]
    n = len(won)
    end = len(hist) == state['planned']
    remaining = state['planned'] - len(hist)
    p = definition['params']
    family = definition['family']
    # `broke`: a prohibition was breached. `lost`: a requirement can no longer be met.
    ok = broke = lost = False
    monotonic = False
    if family == 'capture':
        needed = p['cards']
        ok = all(c in cards for c in needed)
        lost = any(c in all_cards and c not in cards for c in needed)
        monotonic = True
    elif family == 'capture_final':
        c = p['card']
        ok = any(h['index'] == state['planned'] and any(q['card'] == c for q in h['plays']) for h in won)
        lost = c in all_cards and not ok
        monotonic = True
    elif family in ('count', 'forbidden'):
        count = sum(matches(c, p['selector']) for c in cards)
        k = p.get('count', 0)
        if p.get('mode') == 'at_least':
            ok, monotonic = count >= k, True
        else:
            ok, broke = count == k, count > k
        if 'per_suit' in p:
            counts = [sum(suit(c) == s for c in cards) for s in p['per_suit']]
            ok, broke = all(x == k for x in counts), any(x > k for x in counts)
        if p.get('required'):
            ok = ok and p['required'] in cards
            lost = p['required'] in all_cards and p['required'] not in cards
        available = sum(matches(c, p['selector']) for c in DECK if c not in all_cards)
        if family == 'count' and 'per_suit' not in p:
            lost = lost or count + available < k
    elif family == 'tricks':
        k = prediction if p.get('predict') else p['count']
        if k is None:
            return 'pending', None
        ok, broke, lost = n == k, n > k, n + remaining < k
    elif family in ('streak', 'exact_streak', 'never_streak'):
        run = best = 0
        for h in hist:
            run = run + 1 if h['winner'] == owner else 0
            best = max(best, run)
        k = p['count']
        if family == 'streak':
            ok, monotonic = best >= k, True
        elif family == 'never_streak':
            ok, broke = best < k, best >= k
        else:
            ok, broke, lost = n == k and best == k, n > k, n + remaining < k
            # Once wins have been split, an exact-total consecutive run is impossible.
            lost = lost or (n > best and any(h['winner'] != owner for h in hist[
                next((i for i, h in enumerate(hist) if h['winner'] == owner), len(hist)):]))
    elif family == 'indices':
        required = [state['planned'] if i == 'last' else i for i in p.get('required', [])]
        forbidden = p.get('forbidden', [])
        mine = {h['index'] for h in won}
        ok = all(i in mine for i in required) and not mine.intersection(forbidden)
        lost = any(i <= len(hist) and i not in mine for i in required)
        broke = bool(mine.intersection(forbidden))
        if p.get('only'):
            broke = broke or any(i not in required for i in mine)
        elif forbidden and not required:
            # "Win none of the first N tricks": once trick N is resolved without a win the
            # task can no longer fail, so it is complete (rulebook p10). AVR-241.
            monotonic = len(hist) >= max(forbidden)
        else:
            monotonic = not forbidden
    elif family in ('compare', 'majority'):
        if family == 'majority':
            ok = n > state['planned'] / 2
            monotonic = True
        else:
            others = [sum(h['winner'] == s for h in hist) for s in state['seats']
                      if s != owner and (p['other'] == 'all' or s == state['captain'])]
            ok = all({'lt': n < v, 'gt': n > v, 'eq': n == v}[p['op']] for v in others)
    elif family in ('value', 'parity', 'win_with', 'equal_trick'):
        for h in won:
            cs = [q['card'] for q in h['plays']]
            values = [rank(c) for c in cs]
            no_sub = all(suit(c) != 'submarine' for c in cs)
            if family == 'parity':
                ok = ok or (no_sub and all(v % 2 == p['parity'] for v in values))
            elif family == 'value':
                threshold = p.get('thresholds', {}).get(str(len(state['seats'])), p.get('threshold'))
                conditions = {'lt': sum(values) < (threshold or 0),
                              'gt': sum(values) > (threshold or 0),
                              'in': sum(values) in p.get('values', []),
                              'all_lt': all(v < (threshold or 0) for v in values),
                              'all_gt': all(v > (threshold or 0) for v in values)}
                ok = ok or (no_sub and conditions[p['op']])
            elif family == 'equal_trick':
                a, b = [sum(suit(c) == s for c in cs) for s in p['suits']]
                ok = ok or a == b > 0
            else:
                instrument = next(q['card'] for q in h['plays'] if q['seat'] == owner)
                ok = ok or (matches(instrument, p['instrument']) and
                            (not p.get('target') or any(matches(c, p['target']) and c != instrument for c in cs)))
        monotonic = True
        if family == 'win_with' and p.get('target', {}).get('card'):
            lost = p['target']['card'] in all_cards and not ok
    elif family in ('equal', 'greater'):
        a, b = [sum(suit(c) == s for c in cards) for s in p['suits']]
        ok = a == b > 0 if family == 'equal' else a > b
    elif family == 'each_color':
        ok, monotonic = all(any(suit(c) == s for c in cards) for s in COLORS), True
    elif family == 'all_color':
        ok, monotonic = any(sum(suit(c) == s for c in cards) == 9 for s in COLORS), True
    elif family == 'no_lead':
        broke = any(h['leader'] == owner and suit(h['plays'][0]['card']) in p['suits'] for h in hist)
        if state['trick']:
            broke = broke or (state['trick'][0]['seat'] == owner and
                              suit(state['trick'][0]['card']) in p['suits'])
        ok = not broke
    else:
        raise ValueError('Unknown task evaluator: ' + family)
    if broke or lost or (end and not ok):
        return 'failed', VIOLATED if broke else UNREACHABLE if lost else UNMET
    if ok and (end or monotonic):
        return 'satisfied', None
    return 'pending', None
