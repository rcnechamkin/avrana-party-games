"""Authoritative, deterministic engine. Commands are transactional and UI-independent."""
from copy import deepcopy
import json
import random

from .content import CONTENT_HASH, TASKS, mission
from .rules import DECK, assertions, legal_cards, rank, suit, winner
from .tasks import evaluate

VERSION = 1


class Invalid(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code, message):
    if not condition:
        raise Invalid(code, message)


def _tuple(value):
    return tuple(_tuple(v) for v in value) if isinstance(value, list) else value


class Engine:
    def __init__(self, humans, rng=None, mission_id=1, timed=False, tonoja_position=2):
        require(2 <= len(humans) <= 5 and len(set(humans)) == len(humans),
                'crew', 'The crew needs two to five different players.')
        self.rng = rng or random.Random()
        seats = list(humans)
        if len(humans) == 2:
            require(type(tonoja_position) is int and 0 <= tonoja_position <= 2,
                    'seat', 'Choose Tonoja’s clockwise position.')
            seats.insert(tonoja_position, 'tonoja')
        self.s = {'version': VERSION, 'content': CONTENT_HASH, 'humans': list(humans),
                  'seats': seats, 'attempt': 0, 'revision': 0, 'mission': None,
                  'timed': timed, 'distress': False, 'attempts': 0,
                  'log': [], 'counted': False, 'deck': [], 'used': [], 'dedup': {},
                  'away': [], 'result': None, 'proposal': None}
        self.prepare(mission_id)

    def playable(self, seat):
        if seat == 'tonoja':
            return [col['top'] for col in self.s['columns'] if col['top'] is not None]
        return list(self.s['hands'][seat])

    def controller(self, seat):
        return self.s['captain'] if seat == 'tonoja' else seat

    def eligible(self, task, seat):
        p = TASKS[task]['params']
        return not (p.get('other') == 'captain' and seat == self.s['captain'])

    def _generate(self, m):
        s = self.s
        if m.get('fixed'):
            # The named tasks are taken out of the piles like any drawn card (AVR-265): left in
            # the deck they came back from the used pile as a second copy.
            fixed = list(m['fixed'])
            s['deck'] = [k for k in s['deck'] if k not in fixed]
            s['used'] = [k for k in s['used'] if k not in fixed]
            return fixed
        remaining = m['target']
        selected, skipped = [], []
        if not s['deck']:
            s['deck'] = [k for k, v in TASKS.items() if v['enabled']]
            self.rng.shuffle(s['deck'])
            s['used'] = []
        def reachable(ids, target):
            sums = {0}
            for k in ids:
                d = TASKS[k]['difficulty'][str(len(s['seats']))]
                sums.update(x + d for x in list(sums) if x + d <= target)
            return target in sums
        if not reachable(s['deck'], remaining):
            s['deck'].extend(s['used'])
            s['used'] = []
            self.rng.shuffle(s['deck'])
        require(reachable(s['deck'], remaining), 'task_deck', 'The task deck cannot reach this difficulty.')
        # A greedy scan may leave an unreachable remainder. Retry with a new private
        # permutation rather than recursion. Failed scans do not discard candidate cards.
        original = list(s['deck'])
        for _ in range(200):
            remaining, selected, skipped = m['target'], [], []
            for k in s['deck']:
                d = TASKS[k]['difficulty'][str(len(s['seats']))]
                if remaining and d <= remaining:
                    selected.append(k)
                    remaining -= d
                else:
                    skipped.append(k)
            if not remaining:
                s['deck'] = skipped
                return selected
            s['deck'] = list(original)
            self.rng.shuffle(s['deck'])
        raise Invalid('task_deck', 'Task generation needs a fresh task deck.')

    def _index_conflict(self, pool, m):
        # R14's explicit example: overlapping fixed trick requirements forced
        # onto distinct owners when each can select at most one task.
        eligible_count = len(self.s['seats']) - (m['allocation'] == 'skip_captain')
        if len(pool) > eligible_count:
            return None
        seen = set()
        for k in pool:
            p = TASKS[k]['params']
            indices = set(p.get('required', [])) if TASKS[k]['family'] == 'indices' else set()
            if indices & seen:
                return k
            seen.update(indices)
        return None

    def _captain_conflict(self, pool, m):
        # C20 (AVR-239): in clockwise selection the captain takes every Nth task and may
        # not pass once there are as many tasks as seats. If the draw leaves fewer
        # ordinary tasks than the captain must take, a captain comparison task is
        # forced onto the captain whatever the crew does. The most recently revealed
        # one is the conflict (R13-14). In `skip_captain` the captain takes nothing.
        if m['allocation'] != 'normal':
            return None
        seats, count = len(self.s['seats']), len(pool)
        comparison = [k for k in pool if TASKS[k]['params'].get('other') == 'captain']
        captain_picks = -(-count // seats)
        if count < seats or count - len(comparison) >= captain_picks:
            return None
        return comparison[-1]

    def _repair_tasks(self, pool, m):
        # Unavoidable task combinations are exchanged for another task of the same
        # difficulty before selection opens; no attempt is counted (R13-14).
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

    def _deal(self):
        s = self.s
        deck = list(DECK)
        self.rng.shuffle(deck)
        s['hands'] = {seat: [] for seat in s['humans']}
        s['columns'] = []
        if 'tonoja' in s['seats']:
            deck.remove('submarine:4')
            s['columns'] = [{'covered': deck.pop(), 'top': deck.pop()} for _ in range(7)]
            deck.append('submarine:4')
            self.rng.shuffle(deck)
            targets = s['humans']
            s['planned'] = 13
        else:
            targets = s['seats']
            s['hands'] = {seat: [] for seat in targets}
            s['planned'] = 40 // len(targets)
        start = self.rng.randrange(len(targets))
        for i, c in enumerate(deck):
            s['hands'][targets[(start + i) % len(targets)]].append(c)
        for hand in s['hands'].values():
            hand.sort()
        s['captain'] = next(seat for seat, h in s['hands'].items() if 'submarine:4' in h)

    def _deal_exception(self, pool):
        hands = list(self.s['hands'].values())
        if self.s['columns']:
            hands.append([c[k] for c in self.s['columns'] for k in ('top', 'covered') if c[k]])
        sub = lambda *rs: {f'submarine:{r}' for r in rs}
        exceptions = {'black1': [sub(1, 4), sub(1, 2, 3)],
                      'black2': [sub(2, 4), sub(1, 2, 3)],
                      '1black': [sub(1, 2, 3, 4)], '2black': [sub(2, 3, 4)],
                      '3black': [sub(1, 2, 3, 4)],
                      'red7WithBlack': [sub(1, 2, 3, 4) | {'pink:7'}],
                      'green9WithBlack': [sub(1, 2, 3, 4) | {'green:9'}]}
        return any(e <= set(h) for k in pool for e in exceptions.get(k, []) for h in hands)

    def prepare(self, mission_id, keep=None):
        s = self.s
        m = mission(mission_id, s['timed'])
        if len(s['humans']) == 2:
            require(m['allocation'] != 'volunteer',
                    'C11', 'Volunteer missions with Tonoja need clarification.')
        changed = not s['mission'] or s['mission']['id'] != mission_id
        if changed:
            s['distress'], s['attempts'] = False, 0
        comm = m['communication']
        terrain = None
        if comm == 'terrain':
            terrain_deck = list(DECK)
            self.rng.shuffle(terrain_deck)
            terrain = terrain_deck.pop()
            while suit(terrain) == 'submarine':
                terrain = terrain_deck.pop()
            comm = ['normal', 'currents', 'rapture'][(rank(terrain) - 1) // 3]
        if keep is not None:
            s['used'] = [k for k in s['used'] if k not in keep]
        pool = list(keep) if keep is not None else self._generate(m)
        pool = self._repair_tasks(pool, m)
        for _ in range(200):
            self._deal()
            if not self._deal_exception(pool):
                break
        else:
            raise Invalid('feasibility', 'Unable to prepare a deal without the explicit submarine exception.')
        allocation_seats = [q for q in s['seats'] if not (m['allocation'] == 'skip_captain' and q == s['captain'])]
        first = s['captain'] if s['captain'] in allocation_seats else s['seats'][(s['seats'].index(s['captain']) + 1) % len(s['seats'])]
        at = allocation_seats.index(first)
        ring = allocation_seats[at:] + allocation_seats[:at]
        s.update(mission=m, attempt=s['attempt'] + 1, phase='allocation' if pool else 'assistance',
                 pool=pool, selected=list(pool), assignments={}, progress={}, predictions={},
                 allocation_ring=ring, pick_index=0, initial_count=len(pool),
                 volunteers=[], answers=[], history=[], trick=[], leader=s['captain'],
                 turn=s['captain'], exposures=[], spent=[], shared=len(s['seats']) - 2,
                 communication=comm, terrain=terrain, pass_choices={}, result=None,
                 proposal=None, expiry=None, counted=False, before_first_only=False, dedup={})
        self.check()

    def selector(self):
        s = self.s
        if s['mission']['allocation'] == 'volunteer':
            ring = s['seats']
            return ring[(ring.index(s['captain']) + 1 + len(s['answers'])) % len(ring)]
        return s['allocation_ring'][s['pick_index'] % len(s['allocation_ring'])]

    def _allocation_done(self):
        self.s['phase'] = 'prediction' if any(TASKS[k]['params'].get('predict') for k in self.s['assignments']) else 'assistance'

    def _assign(self, k, owner):
        require(k in self.s['pool'], 'task', 'That task was already chosen.')
        require(owner in self.s['seats'] and self.eligible(k, owner), 'owner',
                'The captain cannot take a captain comparison task.')
        self.s['pool'].remove(k)
        self.s['assignments'][k] = owner
        self.s['progress'][k] = 'pending'

    def _may_pass_task(self):
        s = self.s
        slots = len(s['allocation_ring']) - s['pick_index'] - 1
        return s['initial_count'] < len(s['allocation_ring']) and len(s['pool']) <= slots

    def _selection_blocked(self):
        # C20 (AVR-239): the next selector can take none of the remaining tasks and may
        # not pass. Only the captain can be in this position, and only because the crew
        # left a captain comparison task for the captain: an avoidable mistake, so the
        # attempt ends as a counted failure (R13), as an ineligible volunteer does.
        s = self.s
        seat = self.selector()
        if any(self.eligible(k, seat) for k in s['pool']) or self._may_pass_task():
            return
        s['attempts'] += 1
        s['counted'] = True
        self._finish('failed', 'The captain was left with only captain comparison tasks, which the captain '
                               'may not take. Give those tasks to other crew members on the next attempt.')

    def _begin(self, now):
        s = self.s
        s['phase'] = 'before_trick'
        if not s['counted']:
            s['attempts'] += 1
            s['counted'] = True
        s['expiry'] = now + s['mission']['seconds'] if s['mission']['seconds'] else None

    def _finish(self, status, reason):
        s = self.s
        if s['result']:
            return
        s['result'] = {'status': status, 'reason': reason}
        s['used'].extend(k for k in s['selected'] if k not in s['used'])
        s['phase'], s['expiry'], s['proposal'] = 'mission_result', None, None
        if status == 'success':
            s['log'].append({'mission': s['mission']['id'], 'attempts': s['attempts'] + int(s['distress']),
                             'distress': s['distress'], 'attempt': s['attempt']})

    def expire(self, reason='Time has run out.'):
        # A running deadline ends the attempt. The adapter also calls this when it restores a
        # timed table and cannot say how much time has passed (E-D7, AVR-242).
        if self.s['expiry'] is None:
            return False
        self._finish('failed', reason)
        self.s['revision'] += 1
        return True

    def observe_time(self, now):
        # `now` and `expiry` are seconds on whatever clock the caller keeps; the engine has none.
        if self.s['expiry'] is not None and now >= self.s['expiry']:
            return self.expire()
        return False

    def _outcome(self):
        s = self.s
        for k, owner in s['assignments'].items():
            if s['progress'][k] == 'pending':
                s['progress'][k] = evaluate(TASKS[k], owner, s, s['predictions'].get(k))
            if s['progress'][k] == 'failed':
                self._finish('failed', TASKS[k]['text'])
                return
        objective = s['mission']['objective']
        if objective in ('balance1', 'balance9'):
            r = 1 if objective == 'balance1' else 9
            counts = [sum(suit(p['card']) != 'submarine' and rank(p['card']) == r
                          for h in s['history'] if h['winner'] == seat for p in h['plays']) for seat in s['seats']]
            if max(counts) - min(counts) >= 2:
                self._finish('failed', f'A crew member has captured two more {r}s than another.')
        elif objective == 'first_winner' and s['history']:
            first = s['history'][0]['winner']
            counts = {seat: sum(h['winner'] == seat for h in s['history']) for seat in s['seats']}
            if any(counts[first] <= count for seat, count in counts.items() if seat != first):
                self._finish('failed', 'The first trick winner must always have strictly more tricks.')
        elif objective == 'final_yellow5':
            plays = [p for h in s['history'] for p in h['plays']] + s['trick']
            if any(p['card'] == 'yellow:5' for p in plays):
                correct = (len(s['history']) == s['planned'] and
                           s['history'][-1]['plays'][-1]['card'] == 'yellow:5')
                if not correct:
                    self._finish('failed', 'Yellow 5 must be the last card in the final trick.')
            elif len(s['history']) == s['planned']:
                self._finish('failed', 'Yellow 5 was left unplayed instead of ending the final trick.')
        if s['result']:
            return
        end = len(s['history']) == s['planned']
        if all(v == 'satisfied' for v in s['progress'].values()) and (not objective or end):
            self._finish('success', 'All mission objectives completed.')
        elif end:
            self._finish('failed', 'The final trick ended before all objectives were completed.')

    def _play(self, actor, msg):
        s = self.s
        require(s['phase'] in ('before_trick', 'in_trick'), 'phase', 'This is not a card-play phase.')
        seat, card = s['turn'], msg['card']
        require(actor == self.controller(seat), 'turn', 'It is another crew member’s turn.')
        hand = self.playable(seat)
        require(card in hand, 'card', 'That card is not in the playable hand.')
        require(card in legal_cards(hand, s['trick']), 'follow_suit', 'You must follow the opening suit.')
        if seat == 'tonoja':
            next(c for c in s['columns'] if c['top'] == card)['top'] = None
        else:
            s['hands'][seat].remove(card)
        for e in s['exposures']:
            if e['seat'] == seat and e['card'] == card:
                e['active'] = False
        s['trick'].append({'seat': seat, 'card': card})
        s['phase'] = 'in_trick'
        if len(s['trick']) == len(s['seats']):
            w = winner(s['trick'])
            s['history'].append({'index': len(s['history']) + 1, 'leader': s['leader'],
                                 'winner': w, 'plays': s['trick']})
            s['trick'] = []
            for c in s['columns']:
                if c['top'] is None and c['covered'] is not None:
                    c['top'], c['covered'] = c['covered'], None
            s['leader'] = s['turn'] = w
            s['phase'] = 'before_trick'
        else:
            s['turn'] = s['seats'][(s['seats'].index(seat) + 1) % len(s['seats'])]
        self._outcome()

    def communication_options(self, actor):
        s = self.s
        if (actor not in s['humans'] or s['away'] or s['phase'] != 'before_trick'
                or s['communication'] == 'none'
                or (s['mission']['id'] == 23 and not s['history'])
                or (s.get('before_first_only') and s['history'])
                or (s['communication'] == 'rapture' and not s['shared'])
                or (s['communication'] != 'rapture' and actor in s['spent'])):
            return {}
        active = {e['card'] for e in s['exposures'] if e['active'] and e['seat'] == actor}
        return {c: assertions(self.playable(actor), c) for c in self.playable(actor)
                if c not in active and assertions(self.playable(actor), c)}

    def _proposal(self, actor, payload, now):
        s = self.s
        kind = payload['kind']
        if kind == 'begin':
            require(s['phase'] == 'assistance', 'phase', 'Finish task allocation and predictions first.')
        elif kind == 'distress':
            require(s['phase'] == 'assistance' and len(s['humans']) > 2, 'distress',
                    'Distress is available before play; the Tonoja exchange is not yet verified.')
            require(payload.get('direction') in ('left', 'right'), 'direction', 'Choose left or right.')
        elif kind == 'assign':
            require(s['phase'] == 'allocation' and s['mission']['allocation'] in ('free', 'one', 'captain_one'),
                    'phase', 'Use the current task selector.')
            owner = payload.get('owner')
            require(isinstance(owner, str) and owner in s['seats'], 'owner', 'Choose a crew member.')
            if s['mission']['allocation'] == 'captain_one':
                require(actor == s['captain'], 'captain', 'The captain must offer these tasks.')
            if s['mission']['allocation'] == 'free':
                keys = [payload.get('task')]
            else:
                require(payload.get('task') == 'all', 'task', 'These tasks go together.')
                keys = list(s['pool'])
            require(all(isinstance(k, str) and k in s['pool'] and self.eligible(k, owner) for k in keys),
                    'task', 'Every task needs an eligible owner.')
        elif kind == 'retry':
            require(s['phase'] == 'mission_result' and s['result']['status'] == 'failed',
                    'phase', 'Retry is available after a failed mission.')
            require(type(payload.get('keep')) is bool, 'payload', 'Choose whether to keep the tasks.')
        elif kind == 'next':
            require(s['phase'] == 'mission_result' and s['result']['status'] == 'success',
                    'phase', 'Complete this mission first.')
            try:
                mission(payload.get('mission'), s['timed'])
            except ValueError as e:
                raise Invalid('mission', str(e)) from e
        elif kind == 'end':
            pass
        else:
            raise Invalid('action', 'Unknown crew decision.')
        s['proposal'] = {'payload': payload, 'votes': [actor]}
        if kind == 'assign' and s['mission']['allocation'] == 'captain_one':
            # Q8 (AVR-251), L M10 and M13: the captain decides. Keeping the tasks, or giving
            # them to Tonoja, whom the captain controls (R10), needs nobody's consent. An offer
            # to another human needs that human's consent and nobody else's.
            if self.controller(payload['owner']) == actor:
                self._commit_proposal(now)
            else:
                s['proposal']['recipient'] = payload['owner']

    def _voters(self):
        # Who must answer the pending decision: every seated human, or the one recipient
        # of the captain's offer in missions 10 and 13.
        recipient = self.s['proposal'].get('recipient')
        return [recipient] if recipient else self.s['humans']

    def _commit_proposal(self, now):
        s = self.s
        payload = s['proposal']['payload']
        kind = payload['kind']
        s['proposal'] = None
        if kind == 'begin':
            self._begin(now)
        elif kind == 'distress':
            s['distress'], s['phase'], s['direction'] = True, 'passing', payload['direction']
        elif kind == 'assign':
            owner = payload['owner']
            keys = [payload['task']] if s['mission']['allocation'] == 'free' else list(s['pool'])
            for k in keys:
                self._assign(k, owner)
            if s['mission']['allocation'] == 'captain_one':
                s['before_first_only'] = owner != s['captain']
            if not s['pool']:
                self._allocation_done()
        elif kind in ('retry', 'next'):
            if kind == 'retry':
                self.prepare(s['mission']['id'], s['selected'] if payload['keep'] else None)
            else:
                self.prepare(payload['mission'])
        elif kind == 'end':
            self._finish('abandoned', 'The crew ended the table.')
            s['phase'] = 'closed'

    def _dispatch(self, actor, msg, now):
        s = self.s
        t = msg['t']
        if t == 'propose':
            require(s['proposal'] is None, 'vote', 'Confirm or decline the current crew decision first.')
            self._proposal(actor, msg['proposal'], now)
        elif t == 'confirm':
            require(s['proposal'] is not None and actor in self._voters()
                    and actor not in s['proposal']['votes'],
                    'vote', 'There is no pending decision for you.')
            if msg['yes']:
                s['proposal']['votes'].append(actor)
                if all(q in s['proposal']['votes'] for q in self._voters()):
                    self._commit_proposal(now)
            else:
                s['proposal'] = None
        elif t == 'choose_task':
            require(s['phase'] == 'allocation' and s['mission']['allocation'] in ('normal', 'skip_captain'),
                    'phase', 'Tasks are not selected this way in this mission.')
            seat = self.selector()
            require(actor == self.controller(seat), 'turn', 'It is another crew member’s task selection.')
            self._assign(msg['task'], seat)
            s['pick_index'] += 1
            if not s['pool']:
                self._allocation_done()
            else:
                self._selection_blocked()
        elif t == 'pass_task':
            require(s['phase'] == 'allocation' and s['mission']['allocation'] in ('normal', 'skip_captain'),
                    'phase', 'Passing is not available here.')
            require(actor == self.controller(self.selector()), 'turn', 'It is another crew member’s turn.')
            require(self._may_pass_task(), 'pass', 'The remaining tasks must be assigned this round.')
            s['pick_index'] += 1
            self._selection_blocked()
        elif t == 'volunteer':
            require(s['phase'] == 'allocation' and s['mission']['allocation'] == 'volunteer',
                    'phase', 'There is no volunteer question now.')
            seat = self.selector()
            require(actor == self.controller(seat), 'turn', 'Answer when the captain asks you.')
            needed = s['mission']['volunteers'] - len(s['volunteers'])
            remaining = len(s['seats']) - len(s['answers'])
            require(msg['yes'] or remaining > needed, 'volunteer', 'The remaining crew must take the tasks.')
            s['answers'].append(seat)
            if msg['yes']:
                s['volunteers'].append(seat)
            if len(s['volunteers']) == s['mission']['volunteers']:
                if any(not self.eligible(k, seat) for k in s['pool']):
                    s['attempts'] += 1
                    s['counted'] = True
                    self._finish('failed', 'The chosen volunteer cannot own a captain comparison task. Choose another volunteer on the next attempt.')
                    return
                for k in list(s['pool']):
                    self._assign(k, seat)
                self._allocation_done()
        elif t == 'predict':
            k, value = msg['task'], msg['count']
            require(s['phase'] == 'prediction' and k in s['assignments'] and
                    TASKS[k]['params'].get('predict'), 'task', 'This task does not need a prediction now.')
            require(actor == self.controller(s['assignments'][k]), 'owner', 'Only the task owner can predict.')
            require(k not in s['predictions'] and 0 <= value <= s['planned'],
                    'prediction', 'Your prediction must be in range and cannot be changed.')
            s['predictions'][k] = value
            if all(k in s['predictions'] for k in s['assignments'] if TASKS[k]['params'].get('predict')):
                s['phase'] = 'assistance'
        elif t == 'pass_card':
            require(s['phase'] == 'passing' and actor not in s['pass_choices'], 'phase', 'Your pass is already locked or unavailable.')
            card = msg['card']
            require(card in s['hands'][actor] and suit(card) != 'submarine', 'card', 'Choose one of your color cards.')
            s['pass_choices'][actor] = card
            if len(s['pass_choices']) == len(s['humans']):
                for q, c in s['pass_choices'].items():
                    s['hands'][q].remove(c)
                delta = 1 if s['direction'] == 'left' else -1
                for q, c in s['pass_choices'].items():
                    target = s['seats'][(s['seats'].index(q) + delta) % len(s['seats'])]
                    s['hands'][target].append(c)
                s['pass_choices'] = {}
                self._begin(now)
        elif t == 'communicate':
            card, assertion = msg['card'], msg['assertion']
            require(assertion in self.communication_options(actor).get(card, []), 'communication',
                    'Communication requires an available sonar token, a trick boundary, and your highest, lowest or only color card.')
            if s['communication'] == 'rapture':
                s['shared'] -= 1
            else:
                s['spent'].append(actor)
            s['exposures'].append({'seat': actor, 'card': card, 'assertion': assertion, 'active': True})
        elif t == 'play_card':
            self._play(actor, msg)
        else:
            raise Invalid('action', 'Unknown game action.')

    def apply(self, actor, msg, now=0):
        # Observation is a server event, independent of acceptance of a client command.
        self.observe_time(now)
        require(isinstance(msg, dict), 'payload', 'Send a game action object.')
        s = self.s
        require(isinstance(actor, str) and actor in s['humans'], 'actor', 'Only seated crew members may act.')
        require(not s['away'], 'paused', 'Waiting for the crew to reconnect.')
        t = msg.get('t')
        fields = {'play_card': {'card': str}, 'communicate': {'card': str, 'assertion': str},
                  'choose_task': {'task': str}, 'pass_task': {}, 'predict': {'task': str, 'count': int},
                  'volunteer': {'yes': bool}, 'pass_card': {'card': str},
                  'propose': {'proposal': dict}, 'confirm': {'yes': bool}}
        require(isinstance(t, str) and t in fields, 'action', 'Unknown game action.')
        allowed = {'t', 'attempt', 'revision', 'request'} | set(fields[t])
        require(set(msg) == allowed and all(type(msg[k]) is typ for k, typ in fields[t].items()),
                'payload', 'Invalid action fields or types.')
        require(type(msg['attempt']) is int and type(msg['revision']) is int and
                isinstance(msg['request'], str) and 1 <= len(msg['request']) <= 80,
                'payload', 'Invalid action scope.')
        if t == 'propose':
            p = msg['proposal']
            keys = {'begin': {'kind'}, 'end': {'kind'}, 'retry': {'kind', 'keep'},
                    'next': {'kind', 'mission'}, 'distress': {'kind', 'direction'},
                    'assign': {'kind', 'owner', 'task'}}
            # Every field is a plain value of its own type (AVR-264): what is accepted here is
            # stored in the pending decision, copied and sent to every viewer.
            types = {'kind': str, 'keep': bool, 'mission': int, 'direction': str, 'owner': str, 'task': str}
            require(isinstance(p.get('kind'), str) and p['kind'] in keys and set(p) == keys[p['kind']]
                    and all(type(p[k]) is types[k] for k in p),
                    'payload', 'Invalid crew decision.')
        identity = actor + ':' + str(msg['attempt']) + ':' + msg['request']
        fingerprint = json.dumps(msg, sort_keys=True)
        if identity in s['dedup']:
            require(s['dedup'][identity] == fingerprint, 'request', 'This request ID was already used.')
            return False
        require(msg['attempt'] == s['attempt'] and msg['revision'] == s['revision'],
                'stale', 'That moment has passed. Use the latest table state.')
        require(len(s['dedup']) < 10000, 'requests', 'This attempt has reached its request limit.')
        require(s['phase'] != 'closed', 'phase', 'This table is closed.')
        require(s['proposal'] is None or t == 'confirm', 'vote', 'Confirm or decline the crew decision first.')
        old, rng_state = deepcopy(s), self.rng.getstate()
        try:
            self._dispatch(actor, msg, now)
            self.check()
            self.s['revision'] += 1
            self.s['dedup'][identity] = fingerprint
        except Exception:
            self.s = old
            self.rng.setstate(rng_state)
            raise
        return True

    def check(self):
        s = self.s
        require(s['phase'] in ('allocation', 'prediction', 'assistance', 'passing',
                              'before_trick', 'in_trick', 'mission_result', 'closed')
                and type(s['timed']) is bool and s['mission'] == mission(s['mission']['id'], s['timed'])
                and type(s['revision']) is int and s['revision'] >= 0
                and set(s['away']) <= set(s['humans']),
                'snapshot', 'Phase and mission check failed.')
        # A deadline is a finite number of seconds, and only a timed attempt still in play has one.
        require(s['expiry'] is None or (type(s['expiry']) in (int, float) and -1e12 < s['expiry'] < 1e12
                                        and s['result'] is None and bool(s['mission']['seconds'])),
                'snapshot', 'Deadline check failed.')
        require(len(s['humans']) in (2, 3, 4, 5) and len(set(s['humans'])) == len(s['humans'])
                and set(s['seats']) == set(s['humans']) | ({'tonoja'} if len(s['humans']) == 2 else set())
                and len(s['seats']) == len(set(s['seats'])) and set(s['hands']) == set(s['humans']),
                'snapshot', 'Seat identity check failed.')
        require(s['planned'] == (13 if len(s['humans']) == 2 else 40 // len(s['seats']))
                and len(s['columns']) == (7 if len(s['humans']) == 2 else 0)
                and s['captain'] in s['humans'] and s['leader'] in s['seats'] and s['turn'] in s['seats'],
                'snapshot', 'Turn and deal check failed.')
        cards = [c for h in s['hands'].values() for c in h]
        cards += [c[k] for c in s['columns'] for k in ('top', 'covered') if c[k] is not None]
        cards += [p['card'] for h in s['history'] for p in h['plays']] + [p['card'] for p in s['trick']]
        require(len(cards) == 40 and set(cards) == set(DECK), 'snapshot', 'Card conservation check failed.')
        require(all(len(h['plays']) == len(s['seats']) for h in s['history']) and
                len(s['history']) <= s['planned'] and len(s['trick']) < len(s['seats']),
                'snapshot', 'Trick history check failed.')
        for i, h in enumerate(s['history']):
            order = s['seats'][s['seats'].index(h['leader']):] + s['seats'][:s['seats'].index(h['leader'])]
            require(h['index'] == i + 1 and [p['seat'] for p in h['plays']] == order
                    and winner(h['plays']) == h['winner'], 'snapshot', 'Resolved trick check failed.')
        if s['trick']:
            order = s['seats'][s['seats'].index(s['leader']):] + s['seats'][:s['seats'].index(s['leader'])]
            require([p['seat'] for p in s['trick']] == order[:len(s['trick'])]
                    and s['turn'] == order[len(s['trick'])], 'snapshot', 'Current trick check failed.')
        # A task card is in one place: the deck, the used pile or the mission in play. The tasks
        # of a mission that has ended are in the used pile and still shown as its tasks.
        piles = (s['deck'], s['used'], s['selected'], s['pool'])
        require(all(type(p) is list and all(isinstance(k, str) and k in TASKS and TASKS[k]['enabled'] for k in p)
                    and len(set(p)) == len(p) for p in piles)
                and not set(s['deck']) & (set(s['used']) | set(s['selected']))
                and (s['result'] is not None or not set(s['used']) & set(s['selected'])),
                'snapshot', 'Task pile check failed.')
        require(all(k in TASKS and TASKS[k]['enabled'] for k in s['selected'])
                and all(owner in s['seats'] and self.eligible(k, owner) for k, owner in s['assignments'].items()),
                'snapshot', 'Task definition check failed.')
        require(set(s['assignments']) | set(s['pool']) == set(s['selected']) and
                not set(s['assignments']) & set(s['pool']), 'snapshot', 'Task ownership check failed.')

    def snapshot(self):
        return {'state': deepcopy(self.s), 'rng': self.rng.getstate()}

    @classmethod
    def restore(cls, snapshot):
        require(isinstance(snapshot, dict) and set(snapshot) == {'state', 'rng'}, 'snapshot', 'Invalid snapshot envelope.')
        s = deepcopy(snapshot['state'])
        require(s.get('version') == VERSION and s.get('content') == CONTENT_HASH,
                'snapshot', 'Snapshot rules or content version is incompatible.')
        obj = cls.__new__(cls)
        obj.s, obj.rng = s, random.Random()
        obj.rng.setstate(_tuple(snapshot['rng']))
        obj.check()
        return obj

    def view(self, actor=None):
        s = self.s
        participant = actor in s['humans']
        # Currents hides the declaration from the crew, never from the player who made it.
        active = [{k: v for k, v in e.items()
                   if k != 'assertion' or s['communication'] != 'currents' or (participant and e['seat'] == actor)}
                  for e in s['exposures'] if e['active']]
        task_views = []
        for k in s['selected']:
            d = TASKS[k]
            item = {'id': k, 'text': d.get('text_by_crew', {}).get(str(len(s['seats'])), d['text']),
                    'difficulty': d['difficulty'][str(len(s['seats']))],
                    'owner': s['assignments'].get(k), 'status': s['progress'].get(k, 'unassigned'),
                    'eligible_owners': [q for q in s['seats'] if self.eligible(k, q)],
                    'prediction_required': bool(d['params'].get('predict')),
                    'prediction_committed': k in s['predictions']}
            if k in s['predictions'] and (not d['params'].get('secret') or
                    self.controller(s['assignments'][k]) == actor or s['result']):
                item['prediction'] = s['predictions'][k]
            task_views.append(item)
        counts = {q: len(self.playable(q)) + sum(c['covered'] is not None for c in s['columns'])
                  if q == 'tonoja' else len(s['hands'][q]) for q in s['seats']}
        play_reason = None
        if s['away']:
            play_reason = 'Waiting for the crew to reconnect.'
        elif s['phase'] not in ('before_trick', 'in_trick'):
            play_reason = 'Finish mission preparation before playing.'
        elif self.controller(s['turn']) != actor:
            play_reason = 'It is another crew member’s turn.'
        allowed = legal_cards(self.playable(s['turn']), s['trick']) if participant and not play_reason else []
        return {'kind': 'expo', 'attempt': s['attempt'], 'revision': s['revision'],
                'stage': s['phase'], 'mission': deepcopy(s['mission']), 'seats': list(s['seats']),
                'captain': s['captain'], 'leader': s['leader'], 'turn': s['turn'],
                'selector': self.selector() if s['phase'] == 'allocation' else None,
                'controller': self.controller(self.selector()) if s['phase'] == 'allocation' else None,
                'trick': deepcopy(s['trick']), 'last_trick': deepcopy(s['history'][-1]) if s['history'] else None,
                'trick_number': min(len(s['history']) + 1, s['planned']), 'planned_tricks': s['planned'],
                'hand_counts': counts, 'trick_counts': {q: sum(h['winner'] == q for h in s['history']) for q in s['seats']},
                'tasks': task_views, 'communication': s['communication'], 'exposures': active,
                'shared_sonar': s['shared'] if s['communication'] == 'rapture' else None,
                'sonar_spent': list(s['spent']), 'tonoja': [c['top'] for c in s['columns']],
                'distress': s['distress'], 'attempts': s['attempts'], 'result': deepcopy(s['result']),
                'expiry': s['expiry'], 'away': list(s['away']), 'log': deepcopy(s['log']),
                'proposal': deepcopy(s['proposal']),
                'me': {'seat': actor, 'hand': self.playable(actor), 'legal_cards': allowed,
                       'play_reason': play_reason, 'communication_options': self.communication_options(actor),
                       'may_pass_task': (s['phase'] == 'allocation' and s['mission']['allocation'] in ('normal', 'skip_captain')
                           and self.controller(self.selector()) == actor and
                           s['initial_count'] < len(s['allocation_ring']) and
                           len(s['pool']) <= len(s['allocation_ring']) - s['pick_index'] - 1),
                       'may_decline_volunteer': len(s['seats']) - len(s['answers']) > s['mission']['volunteers'] - len(s['volunteers']),
                       'pass_locked': actor in s['pass_choices']} if participant else None}
