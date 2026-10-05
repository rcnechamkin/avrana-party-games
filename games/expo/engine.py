"""Authoritative, deterministic engine. Commands are transactional and UI-independent.

Besides the table state the engine keeps a bounded log of semantic events (AVR-246): what
happened, in order, as meaning. It never says how to show, sound or time anything, and nothing
in the engine reads the log to decide a rule."""
from copy import deepcopy
import json
import random

from .content import CONTENT_HASH, TASKS, mission
from .rules import DECK, assertions, legal_cards, matches, rank, suit, winner
from .tasks import UNREACHABLE, VIOLATED, judge

VERSION = 1
# Routine steps of a table's life, as opposed to decisions the rules give the crew (AVR-252).
LIFECYCLE = ('begin', 'retry', 'next')

# Semantic events (AVR-246). The newest EVENT_LIMIT are kept, across attempts: more than one
# whole attempt at any crew size, so the two tricks a viewer may be sent are always among them.
EVENT_TYPES = ('TURN_STARTED', 'CARD_PLAYED', 'TRICK_RESOLVED', 'COMMUNICATION_SENT',
               'OBJECTIVE_PROGRESS', 'OBJECTIVE_COMPLETED', 'OBJECTIVE_FAILED',
               'MISSION_MODIFIER_ACTIVATED', 'MISSION_SUCCESS', 'MISSION_FAILURE',
               'PLAYER_RECONNECTED')
EVENT_LIMIT = 240
# Said to a seat that acts between a completed trick and the server's settle().
RESOLVING = 'The trick is being resolved.'


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
                  'away': [], 'result': None, 'proposal': None,
                  'events': [], 'event_seq': 0, 'resolving': None, 'cause': None, 'failures': {}}
        self.prepare(mission_id)

    # ---- semantic events and failure causality (AVR-246) ----

    def _emit(self, name, /, trick=None, private=None, **data):
        """Record that something happened. `trick` is the trick the event belongs to (0 before
        play; by default the one in progress). `private` is `{seat, fields}`: fields only that
        seat's own view may carry (a currents declaration)."""
        s = self.s
        s['event_seq'] += 1
        event = {'seq': s['event_seq'], 'type': name, 'attempt': s['attempt'],
                 'mission': s['mission']['id'],
                 'trick': len(s['history']) + 1 if trick is None else trick, **data}
        if private:
            event['private'] = private
        s['events'].append(event)
        del s['events'][:-EVENT_LIMIT]

    def _modifiers(self):
        # What this attempt changes from the base rules, as the mission and its draw define it.
        s, m = self.s, self.s['mission']
        if s['communication'] != 'normal':
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='communication',
                       value=s['communication'], drawn=m['communication'] == 'terrain')
        if m['allocation'] != 'normal':
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='allocation', value=m['allocation'])
        if m['objective']:
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='objective', value=m['objective'])
        if s['distress']:
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='distress', value='active')

    def _context(self):
        s, m = self.s, self.s['mission']
        return {'id': m['id'], 'attempt': s['attempt'], 'objective': m['objective'],
                'allocation': m['allocation'], 'communication': s['communication'],
                'timed': bool(m['seconds']), 'distress': s['distress']}

    def _cause(self, kind, objective=None, failure=None, affected=None, action=None, record=None,
               trigger=None, cards=None):
        """Who and what a failure is attributed to, from public facts only: the cards played, who
        won, who owns the task. `failure` is the evaluator's kind (games/expo/tasks.py).

        The triggering seat is named only where the engine can say so honestly:
          * a failure established when a trick resolved (`record`): the seat that won the trick,
            because every evaluator is a function of who won which cards;
          * a failure established by one card before its trick ended: the seat that played it;
          * a failure during task selection: the seat whose answer ended the attempt (`trigger`).
        A condition that was merely not met when the deal ended, and a deadline, name nobody.
        `action` is always the committed command that the failure followed."""
        s = self.s
        card = None
        if failure in (VIOLATED, UNREACHABLE) and trigger is None:
            if record:
                trigger = record['winner']
                card = next(p['card'] for p in record['plays'] if p['seat'] == trigger)
            elif action and action.get('card'):
                trigger, card = action['seat'], action['card']
        cards = list(cards or [])
        if card and card not in cards:
            cards.append(card)
        return {'kind': kind, 'objective': objective, 'failure': failure,
                'state': 'IMPOSSIBLE' if failure == UNREACHABLE else 'FAILED',
                'affected_seat': affected, 'trigger_seat': trigger,
                'trigger_controller': self.controller(trigger) if trigger else None,
                'trigger_card': card, 'action': deepcopy(action), 'cards': cards,
                'trick': (record['index'] if record else
                          len(s['history']) + 1 if s['phase'] in ('before_trick', 'in_trick') else 0),
                'mission': self._context()}

    @staticmethod
    def _relevant(definition, record):
        # The cards of the deciding trick that the task is about: the ones it names, or the ones
        # its selector counts.
        if not record:
            return []
        named = set()

        def walk(value):
            if isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
            elif isinstance(value, str) and value in DECK:
                named.add(value)
        params = definition['params']
        walk(params)
        selector = params.get('selector') if not named else None
        return [p['card'] for p in record['plays']
                if p['card'] in named or (selector and matches(p['card'], selector))]

    def _fail(self, reason, cause, owner=None):
        # An objective is lost and the attempt with it: the objective's event, then the mission's.
        if cause['kind'] in ('task', 'mission_objective'):
            self._emit('OBJECTIVE_FAILED', trick=cause['trick'], objective=cause['objective'],
                       scope=cause['kind'], owner=owner, failure=cause['failure'], state=cause['state'],
                       trigger_seat=cause['trigger_seat'], affected_seat=cause['affected_seat'],
                       cards=list(cause['cards']))
        self._finish('failed', reason, cause)

    def settle(self, credit=0):
        """The server's word that a resolved trick has been taken in: the table leaves
        `resolving` and the winner's turn begins. Not a player's action: no seat can send it, it
        does not wait for anyone who is away, and it is never refused. Who calls it, and when,
        is the adapter's business; the engine holds no clock for it. False if there was nothing
        to settle.

        `credit` is how long the server held the table, in seconds. A real-time mission's clock
        does not run while nobody may act (observe_time), so its deadline moves by that much:
        the hold costs the crew no time."""
        s = self.s
        if not s['resolving']:
            return False
        s['resolving'] = None
        if s['expiry'] is not None and type(credit) in (int, float) and 0 < credit <= 60:
            s['expiry'] += credit
        self._emit('TURN_STARTED', seat=s['turn'], controller=self.controller(s['turn']), lead=True)
        s['revision'] += 1
        return True

    def presence(self, seat, away):
        """A seated human's last connection closed, or the first one came back. The adapter
        tells the engine; nothing here knows about sockets. False if nothing changed."""
        s = self.s
        if seat not in s['humans'] or (seat in s['away']) == bool(away):
            return False
        if away:
            s['away'].append(seat)
        else:
            s['away'].remove(seat)
            self._emit('PLAYER_RECONNECTED', seat=seat)
        s['revision'] += 1
        return True

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
                 proposal=None, expiry=None, counted=False, before_first_only=False, dedup={},
                 resolving=None, cause=None, failures={})
        self._modifiers()
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

    def _selection_blocked(self, action=None):
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
        self._fail('The captain was left with only captain comparison tasks, which the captain '
                   'may not take. Give those tasks to other crew members on the next attempt.',
                   self._cause('allocation', failure='captain_left_with_comparison_tasks', affected=seat,
                               action=action, trigger=action['seat'] if action else None))

    def _begin(self, now):
        s = self.s
        s['phase'] = 'before_trick'
        if not s['counted']:
            s['attempts'] += 1
            s['counted'] = True
        s['expiry'] = now + s['mission']['seconds'] if s['mission']['seconds'] else None
        if s['mission']['seconds']:
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='timer', value=s['mission']['seconds'])
        self._emit('TURN_STARTED', seat=s['turn'], controller=self.controller(s['turn']), lead=True)

    def _finish(self, status, reason, cause=None):
        s = self.s
        if s['result']:
            return
        s['result'] = {'status': status, 'reason': reason}
        s['used'].extend(k for k in s['selected'] if k not in s['used'])
        s['phase'], s['expiry'], s['proposal'] = 'mission_result', None, None
        # A result is its own boundary: nothing is left to resolve. `cause` stands beside the
        # result, never inside it, and only a failure has one.
        s['resolving'] = None
        s['cause'] = cause if status == 'failed' else None
        if status == 'success':
            self._emit('MISSION_SUCCESS', trick=len(s['history']), reason=reason,
                       attempts=s['attempts'] + int(s['distress']), distress=s['distress'])
        elif status == 'failed':
            self._emit('MISSION_FAILURE', trick=cause['trick'] if cause else len(s['history']) + 1,
                       reason=reason, cause=deepcopy(cause))
        if status == 'success':
            s['log'].append({'mission': s['mission']['id'], 'attempts': s['attempts'] + int(s['distress']),
                             'distress': s['distress'], 'attempt': s['attempt']})

    def expire(self, reason='Time has run out.'):
        # A running deadline ends the attempt. The adapter also calls this when it restores a
        # timed table and cannot say how much time has passed (E-D7, AVR-242).
        if self.s['expiry'] is None:
            return False
        self._finish('failed', reason, self._cause('deadline', failure='deadline'))
        self.s['revision'] += 1
        return True

    def observe_time(self, now):
        # `now` and `expiry` are seconds on whatever clock the caller keeps; the engine has none.
        # While a trick is resolving nobody may act, and the mission's clock stands (settle()).
        if self.s['resolving']:
            return False
        if self.s['expiry'] is not None and now >= self.s['expiry']:
            return self.expire()
        return False

    def _outcome(self, action=None, record=None):
        """Judge the tasks and the mission objective after a committed play. `action` is that
        play; `record` is the trick it completed, if it completed one. What is decided, and
        when, is exactly what it was before the events existed: they only report it."""
        s = self.s
        number = record['index'] if record else len(s['history']) + 1
        for k, owner in s['assignments'].items():
            if s['progress'][k] == 'pending':
                s['progress'][k], kind = judge(TASKS[k], owner, s, s['predictions'].get(k))
                if s['progress'][k] == 'satisfied':
                    self._emit('OBJECTIVE_COMPLETED', trick=number, objective=k, scope='task', owner=owner)
                elif s['progress'][k] == 'failed':
                    s['failures'][k] = kind
                elif record and record['winner'] == owner:
                    # The task is still open and what it is judged on has changed. Whether that
                    # helps or hurts is not said: the engine reports, it does not advise.
                    self._emit('OBJECTIVE_PROGRESS', trick=number, objective=k, scope='task', owner=owner,
                               change='owner_won_trick',
                               owner_tricks=sum(h['winner'] == owner for h in s['history']))
            if s['progress'][k] == 'failed':
                self._fail(TASKS[k]['text'], self._cause(
                    'task', k, s['failures'].get(k), owner, action, record,
                    cards=self._relevant(TASKS[k], record)), owner)
                return
        objective = s['mission']['objective']
        if objective in ('balance1', 'balance9'):
            r = 1 if objective == 'balance1' else 9
            counts = [sum(suit(p['card']) != 'submarine' and rank(p['card']) == r
                          for h in s['history'] if h['winner'] == seat for p in h['plays']) for seat in s['seats']]
            if max(counts) - min(counts) >= 2:
                self._fail(f'A crew member has captured two more {r}s than another.', self._cause(
                    'mission_objective', objective, VIOLATED, None, action, record,
                    cards=[p['card'] for p in (record['plays'] if record else [])
                           if suit(p['card']) != 'submarine' and rank(p['card']) == r]))
        elif objective == 'first_winner' and s['history']:
            first = s['history'][0]['winner']
            counts = {seat: sum(h['winner'] == seat for h in s['history']) for seat in s['seats']}
            if any(counts[first] <= count for seat, count in counts.items() if seat != first):
                self._fail('The first trick winner must always have strictly more tricks.', self._cause(
                    'mission_objective', objective, VIOLATED, first, action, record))
        elif objective == 'final_yellow5':
            plays = [p for h in s['history'] for p in h['plays']] + s['trick']
            if any(p['card'] == 'yellow:5' for p in plays):
                correct = (len(s['history']) == s['planned'] and
                           s['history'][-1]['plays'][-1]['card'] == 'yellow:5')
                if not correct:
                    # The card that decides it is yellow 5 itself, whoever wins the trick.
                    played = next(p for p in plays if p['card'] == 'yellow:5')
                    self._fail('Yellow 5 must be the last card in the final trick.', self._cause(
                        'mission_objective', objective, VIOLATED, None, action, record,
                        trigger=played['seat'], cards=['yellow:5']))
            elif len(s['history']) == s['planned']:
                self._fail('Yellow 5 was left unplayed instead of ending the final trick.', self._cause(
                    'mission_objective', objective, 'unmet_at_end', None, action, record))
        if s['result']:
            return
        end = len(s['history']) == s['planned']
        if all(v == 'satisfied' for v in s['progress'].values()) and (not objective or end):
            if objective:
                self._emit('OBJECTIVE_COMPLETED', trick=number, objective=objective,
                           scope='mission_objective', owner=None)
            self._finish('success', 'All mission objectives completed.')
        elif end:
            self._fail('The final trick ended before all objectives were completed.',
                       self._cause('final_trick', None, 'unmet_at_end', None, action, record))

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
        number, record = len(s['history']) + 1, None
        s['trick'].append({'seat': seat, 'card': card})
        s['phase'] = 'in_trick'
        self._emit('CARD_PLAYED', trick=number, seat=seat, controller=actor, card=card,
                   position=len(s['trick']), lead_suit=suit(s['trick'][0]['card']))
        if len(s['trick']) == len(s['seats']):
            w = winner(s['trick'])
            record = {'index': number, 'leader': s['leader'], 'winner': w, 'plays': s['trick']}
            s['history'].append(record)
            s['trick'] = []
            for c in s['columns']:
                if c['top'] is None and c['covered'] is not None:
                    c['top'], c['covered'] = c['covered'], None
            s['leader'] = s['turn'] = w
            s['phase'] = 'before_trick'
            self._emit('TRICK_RESOLVED', trick=number, winner=w, leader=record['leader'],
                       winning_card=next(p['card'] for p in record['plays'] if p['seat'] == w),
                       lead_suit=suit(record['plays'][0]['card']), plays=deepcopy(record['plays']))
        else:
            s['turn'] = s['seats'][(s['seats'].index(seat) + 1) % len(s['seats'])]
        self._outcome({'t': 'play_card', 'seat': seat, 'controller': actor, 'card': card}, record)
        if s['result'] is None:
            if record:
                # The trick is decided and play goes on: the table stands still until the server
                # settles it (settle()). A trick that ends the mission has the result instead.
                s['resolving'] = {'trick': number}
            else:
                self._emit('TURN_STARTED', trick=number, seat=s['turn'],
                           controller=self.controller(s['turn']), lead=False)

    def communication_options(self, actor):
        s = self.s
        if (actor not in s['humans'] or s['away'] or s['phase'] != 'before_trick' or s['resolving']
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
            self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='distress', value=payload['direction'])
        elif kind == 'assign':
            owner = payload['owner']
            keys = [payload['task']] if s['mission']['allocation'] == 'free' else list(s['pool'])
            for k in keys:
                self._assign(k, owner)
            if s['mission']['allocation'] == 'captain_one':
                s['before_first_only'] = owner != s['captain']
                if s['before_first_only']:
                    self._emit('MISSION_MODIFIER_ACTIVATED', trick=0, modifier='sonar',
                               value='before_first_trick_only')
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
                self._selection_blocked({'t': t, 'seat': seat, 'controller': actor, 'task': msg['task']})
        elif t == 'pass_task':
            require(s['phase'] == 'allocation' and s['mission']['allocation'] in ('normal', 'skip_captain'),
                    'phase', 'Passing is not available here.')
            require(actor == self.controller(self.selector()), 'turn', 'It is another crew member’s turn.')
            require(self._may_pass_task(), 'pass', 'The remaining tasks must be assigned this round.')
            seat = self.selector()
            s['pick_index'] += 1
            self._selection_blocked({'t': t, 'seat': seat, 'controller': actor})
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
                    self._fail('The chosen volunteer cannot own a captain comparison task. Choose another volunteer on the next attempt.',
                               self._cause('allocation', failure='ineligible_volunteer', affected=seat,
                                           action={'t': t, 'seat': seat, 'controller': actor, 'yes': True},
                                           trigger=seat))
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
            # In currents the declaration is its author's alone, in the event as in the view.
            hidden = s['communication'] == 'currents'
            self._emit('COMMUNICATION_SENT', seat=actor, card=card, mode=s['communication'],
                       token='shared' if s['communication'] == 'rapture' else 'personal',
                       private={'seat': actor, 'fields': {'assertion': assertion}} if hidden else None,
                       **({} if hidden else {'assertion': assertion}))
        elif t == 'play_card':
            self._play(actor, msg)
        else:
            raise Invalid('action', 'Unknown game action.')

    @staticmethod
    def _decision_shape(p):
        keys = {'begin': {'kind'}, 'end': {'kind'}, 'retry': {'kind', 'keep'},
                'next': {'kind', 'mission'}, 'distress': {'kind', 'direction'},
                'assign': {'kind', 'owner', 'task'}}
        # Every field is a plain value of its own type (AVR-264): what is accepted here is
        # stored in the pending decision, copied and sent to every viewer.
        types = {'kind': str, 'keep': bool, 'mission': int, 'direction': str, 'owner': str, 'task': str}
        require(isinstance(p, dict) and isinstance(p.get('kind'), str) and p['kind'] in keys
                and set(p) == keys[p['kind']] and all(type(p[k]) is types[k] for k in p),
                'payload', 'Invalid crew decision.')

    def lifecycle(self, msg, now=0):
        """Begin, Retry or Next, committed at once on the word of the table's lifecycle authority
        (AVR-252): no seat proposes it and nobody votes. Who that authority is, is the adapter's
        business; in a Party round it is the Party Host, who may not hold a seat at all. The
        engine keeps what the rules require first: the step's own phase (tasks allocated and
        predictions made before Begin, a result before Retry or Next), a mission that exists, a
        crew that is all here, and no crew decision left unanswered. A strategic decision
        (distress, an assignment) is never committed this way."""
        self.observe_time(now)
        s = self.s
        require(isinstance(msg, dict) and set(msg) == {'t', 'decision', 'attempt', 'revision'}
                and msg['t'] == 'lifecycle' and type(msg['attempt']) is int
                and type(msg['revision']) is int, 'payload', 'Invalid lifecycle action.')
        payload = msg['decision']
        self._decision_shape(payload)
        require(payload['kind'] in LIFECYCLE, 'strategic', 'The crew decides that together.')
        require(not s['away'], 'paused', 'Waiting for the crew to reconnect.')
        require(msg['attempt'] == s['attempt'] and msg['revision'] == s['revision'],
                'stale', 'That moment has passed. Use the latest table state.')
        require(s['phase'] != 'closed', 'phase', 'This table is closed.')
        require(not s['resolving'], 'resolving', RESOLVING)
        require(s['proposal'] is None, 'vote', 'The crew is deciding something. Wait for their answer.')
        old, rng_state = deepcopy(s), self.rng.getstate()
        try:
            self._proposal(None, payload, now)
            self._commit_proposal(now)
            self.check()
            self.s['revision'] += 1
        except Exception:
            self.s = old
            self.rng.setstate(rng_state)
            raise
        return True

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
            self._decision_shape(msg['proposal'])
        identity = actor + ':' + str(msg['attempt']) + ':' + msg['request']
        fingerprint = json.dumps(msg, sort_keys=True)
        if identity in s['dedup']:
            require(s['dedup'][identity] == fingerprint, 'request', 'This request ID was already used.')
            return False
        require(msg['attempt'] == s['attempt'] and msg['revision'] == s['revision'],
                'stale', 'That moment has passed. Use the latest table state.')
        require(len(s['dedup']) < 10000, 'requests', 'This attempt has reached its request limit.')
        require(s['phase'] != 'closed', 'phase', 'This table is closed.')
        # Between a completed trick and the server's settle() no seat acts (AVR-246).
        require(not s['resolving'], 'resolving', RESOLVING)
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
        # The event log is bounded and ordered; a table is `resolving` only between two tricks of
        # an attempt still in play, for the trick that has just been resolved.
        events = s['events']
        require(type(events) is list and len(events) <= EVENT_LIMIT and type(s['event_seq']) is int
                and all(isinstance(x, dict) and type(x.get('seq')) is int and isinstance(x.get('type'), str)
                        and type(x.get('attempt')) is int and type(x.get('trick')) is int for x in events)
                and all(a['seq'] < b['seq'] for a, b in zip(events, events[1:]))
                and (not events or 0 < events[0]['seq'] and events[-1]['seq'] <= s['event_seq']),
                'snapshot', 'Event log check failed.')
        require(s['resolving'] is None or (
                    isinstance(s['resolving'], dict) and set(s['resolving']) == {'trick'}
                    and s['resolving']['trick'] == len(s['history']) and s['history']
                    and s['phase'] == 'before_trick' and s['result'] is None and not s['trick']),
                'snapshot', 'Resolving check failed.')
        require(isinstance(s['failures'], dict) and set(s['failures']) <= set(s['assignments'])
                and (s['cause'] is None or isinstance(s['cause'], dict)),
                'snapshot', 'Causality check failed.')

    def snapshot(self):
        return {'state': deepcopy(self.s), 'rng': self.rng.getstate()}

    @classmethod
    def restore(cls, snapshot):
        require(isinstance(snapshot, dict) and set(snapshot) == {'state', 'rng'}, 'snapshot', 'Invalid snapshot envelope.')
        s = deepcopy(snapshot['state'])
        require(s.get('version') == VERSION and s.get('content') == CONTENT_HASH,
                'snapshot', 'Snapshot rules or content version is incompatible.')
        # Additive keys (AVR-246): a snapshot written before the events existed has none of them
        # and is read as a table with an empty log and nothing to resolve. Format 1 still.
        for key, empty in (('events', []), ('event_seq', 0), ('resolving', None), ('cause', None),
                           ('failures', {})):
            s.setdefault(key, empty)
        obj = cls.__new__(cls)
        obj.s, obj.rng = s, random.Random()
        obj.rng.setstate(_tuple(snapshot['rng']))
        obj.check()
        return obj

    def events(self, actor=None):
        """The events a viewer may be sent, oldest first, as copies: nothing a caller does to
        them reaches the table.

        Which: those of the attempt in play that belong to the most recently resolved trick or
        to anything after it (before a trick is resolved, the whole attempt so far). Only the
        most recently won trick may be looked at again (R04); the log the engine keeps is longer
        and stays on the server. What: every field was public when the event happened, except
        the fields marked private, which go to their own seat only."""
        s = self.s
        floor, out = len(s['history']), []
        for event in s['events']:
            if event['attempt'] != s['attempt'] or event['trick'] < floor:
                continue
            item = deepcopy({k: v for k, v in event.items() if k != 'private'})
            private = event.get('private')
            if private and actor in s['humans'] and private['seat'] == actor:
                item.update(deepcopy(private['fields']))
            out.append(item)
        return out

    def objective_state(self, task):
        """PENDING (not in play yet), ACTIVE (in play, undecided), COMPLETED, FAILED or
        IMPOSSIBLE. IMPOSSIBLE is a failure the evaluator found as `unreachable`: what the task
        needs can no longer happen. The engine detects that for the cases the evaluators always
        detected and no others, and it ends the attempt exactly when it did before."""
        s = self.s
        status = s['progress'].get(task)
        if status == 'satisfied':
            return 'COMPLETED'
        if status == 'failed':
            return 'IMPOSSIBLE' if s['failures'].get(task) == UNREACHABLE else 'FAILED'
        played = bool(s['history'] or s['trick'])
        if status == 'pending' and (s['phase'] in ('before_trick', 'in_trick') or (s['result'] and played)):
            return 'ACTIVE'
        return 'PENDING'

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
                    'state': self.objective_state(k),
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
        elif s['resolving']:
            play_reason = RESOLVING
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
                # AVR-246. `resolving`: the trick just resolved, while no seat may act. `cause`:
                # what a failed attempt is attributed to. `events`: see events(); `event_seq` is
                # the newest sequence number at this table, sent or not.
                'resolving': deepcopy(s['resolving']), 'cause': deepcopy(s['cause']),
                'events': self.events(actor), 'event_seq': s['event_seq'],
                'me': {'seat': actor, 'hand': self.playable(actor), 'legal_cards': allowed,
                       'play_reason': play_reason, 'communication_options': self.communication_options(actor),
                       'may_pass_task': (s['phase'] == 'allocation' and s['mission']['allocation'] in ('normal', 'skip_captain')
                           and self.controller(self.selector()) == actor and
                           s['initial_count'] < len(s['allocation_ring']) and
                           len(s['pool']) <= len(s['allocation_ring']) - s['pick_index'] - 1),
                       'may_decline_volunteer': len(s['seats']) - len(s['answers']) > s['mission']['volunteers'] - len(s['volunteers']),
                       'pass_locked': actor in s['pass_choices']} if participant else None}
