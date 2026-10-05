"""Avrana adapter: authentication, lobby, clock, masking and reconnect lifecycle."""
from copy import deepcopy
import os
import time

from core.session import GameSession, HostRefused, Player
from .content import catalog, mission
from .engine import LIFECYCLE, Engine, Invalid
from .storage import SnapshotStore

# A timed mission runs on the monotonic clock (E-D7, AVR-242): a step of the wall clock, in
# either direction, neither grants nor takes time. Wall-clock moments exist only for browsers.
CLOCK_TOLERANCE = 2.0
UNTRUSTED_CLOCK = ('The server restarted and could not tell how much time had passed, '
                   'so the timed attempt has ended.')


CLOCK_RANGE = 1e12                # seconds; a clock reading outside it is not a clock reading

# Who moves a table through its routine steps (AVR-252). In a Party round they are the Party
# Host's: a seat that proposes one is told so. The words are shown to the player as they are.
HOST_ONLY = {'begin': 'Only the Party Host can begin the mission.',
             'retry': 'Only the Party Host can retry the mission.',
             'next': 'Only the Party Host can choose the next mission.'}
PARTY_END = 'In a Party, the Party Host ends EXPO for everyone.'
assert set(HOST_ONLY) == set(LIFECYCLE)

# Distress gets a protected opportunity, not a vote (AVR-275, owner decision 2026-10-04): once the
# tasks are settled the Party Host cannot Begin for this long, so a crew member who wants to ask
# for distress has time to. A request that is pending blocks Begin by itself (Engine.lifecycle).
# Nobody has to say "ready". Only where distress exists: before play, with three or more humans.
DISTRESS_GRACE = 4.0
GRACE = 'The crew has a moment to ask for distress first. Begin in a few seconds.'

# A completed trick is held for this long before the next one opens (AVR-246): the table is
# `resolving`, no seat acts, and every phone has the same moment to show who won. The engine
# only knows that it is resolving; the adapter decides how long and calls Engine.settle().
# A presentation boundary, not a rule: it is never saved, and a restored table settles at once.
# A timed mission gains no time from it (owner decision 2026-10-05): its clock runs through the
# hold and its deadline does not move. A deadline that passes during the hold is judged when the
# hold ends (Engine.settle), before anyone may act.
# 0.8 s is the owner's value (2026-10-05), provisional pending real-phone playtesting.
RESOLVE_HOLD = 0.8
HOLD_SLACK = 0.02                 # a timer that wakes this much early has still waited

# A Party that does not say who its host is leaves Begin, Retry and Next to the crew. That is a
# deploy-order allowance for a Party older than its host claim (avrana-party ADR 0006, amendment
# 2026-10-04), not a mode: it is logged and shown to the players.
# It stays True through the first paired deployment, so either service can be rolled back
# without stranding a table. Turning it off is its own small change, made only after the host
# claim has been seen working in production (owner decision 2026-10-04): from then on those
# steps are the Party Host's in every Party round, and a Party that cannot say who that is
# cannot move the table on (only end it). That cutoff is not undone by a Party rollback.
HOST_CLAIM_TRANSITION = True


def _mono():
    return time.monotonic()


def _reading(value):
    # A number a clock could have given. The comparison is false for NaN and the infinities and
    # exact for an integer too large to be a float.
    return type(value) in (int, float) and -CLOCK_RANGE < value < CLOCK_RANGE


def _boot():
    # The kernel's identity for this boot, or None where there is none to read. Without it a
    # reboot whose clocks happen to line up cannot be told from a restart of the service.
    try:
        with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as f:
            return f.read().strip() or None
    except OSError:
        return None


def _wall():
    return time.time()


class ExpoSession(GameSession):
    MIN_PLAYERS = 2
    MAX_HUMANS = 5
    DEFAULT_SETTINGS = {'mission': 1, 'timed': False, 'tonoja_position': 2}

    def __init__(self, rng=None, snapshot_path=None):
        super().__init__(rng)
        self.engine = None
        self._grace = None                # (attempt, monotonic moment the host's Begin opens)
        self._hold = None                 # ((attempt, trick), monotonic moment the trick settles)
        self.recovery_error = None
        path = snapshot_path or (os.environ.get('EXPO_SNAPSHOT_PATH') if rng is None else None)
        self.store = SnapshotStore(path) if path else None
        if self.store:
            try:
                saved = self.store.read()
                if saved is not None:
                    self.restore(saved)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError, OSError):
                self.recovery_error = 'The saved table could not be restored. Check the private snapshot before starting a new table.'

    def party_start(self, seats):
        # A Party round (core/session.py) owns this room: the Party's roster is the table. A
        # standalone snapshot restored by __init__ must never leak into it, and Party tables are
        # not written to the standalone snapshot (their tokens die with the Party session).
        self.engine, self.recovery_error, self.store = None, None, None
        self.players, self.participants = {}, []
        return super().party_start(seats)

    def validate_settings(self, patch):
        clean = {}
        if type(patch.get('mission')) is int:
            try:
                mission(patch['mission'], self.settings['timed'])
                clean['mission'] = patch['mission']
            except ValueError:
                pass
        if type(patch.get('timed')) is bool:
            clean['timed'] = patch['timed']
        if type(patch.get('tonoja_position')) is int and 0 <= patch['tonoja_position'] <= 2:
            clean['tonoja_position'] = patch['tonoja_position']
        return clean

    def start(self, token):
        if self.recovery_error:
            return [self.fx('invalid', to=token, msg=self.recovery_error)]
        n = len(self._connected_ready())
        choice = next((m for m in catalog(n, self.settings['timed']) if m['id'] == self.settings['mission']), None)
        if not choice or not choice['enabled']:
            return [self.fx('invalid', to=token, msg=choice['reason'] if choice else 'Invalid mission.')]
        return super().start(token)

    def game_start(self):
        self._grace = self._hold = None
        humans = [self.players[t].pid for t in self.participants]
        try:
            self.engine = Engine(humans, self.rng, self.settings['mission'], self.settings['timed'],
                                 self.settings['tonoja_position'])
        except ValueError as e:
            self.engine = None
            self.phase = 'lobby'
            self.participants = []
            self._bump(None)
            return [self.fx('toast', msg=str(e))]
        self._sync()
        try:
            self._save()
        except OSError:
            self.engine = None
            self.phase = 'lobby'
            self.participants = []
            self._bump(None)
            return [self.fx('toast', msg='The table could not be saved. Check the snapshot storage and start again.')]
        return []

    def _sync(self):
        if not self.engine:
            return
        self.phase = self.engine.s['phase']
        s = self.engine.s
        if self._distress_open() and (self._grace is None or self._grace[0] != s['attempt']):
            self._grace = (s['attempt'], _mono() + DISTRESS_GRACE)
        if s['resolving']:
            key = (s['attempt'], s['resolving']['trick'])
            if self._hold is None or self._hold[0] != key:
                self._hold = (key, _mono() + RESOLVE_HOLD)
        else:
            self._hold = None
        # One timer serves both. While a trick is resolving the timer waits for the end of the
        # hold: the committed trick settles first, and a mission deadline that has passed by then
        # is judged in that same step (Engine.settle), so nothing is lost by not arming it.
        self._bump(self._wall_moment(self._hold[1] if self._hold else s['expiry']))

    def _settle_due(self):
        """End a resolving trick whose hold is over. Two things call this, so that a lost timer
        cannot leave a table resolving: the timer itself (game_tick) and any command that
        arrives afterwards (_commit). A restore does not wait at all (restore)."""
        if not (self.engine and self.engine.s['resolving']):
            return False
        now = _mono()
        if self._hold is not None:
            if self._hold[1] - now > HOLD_SLACK:
                return False
            # A timer may wake a little early (HOLD_SLACK). The deadline is still judged at the
            # hold's own end, so one that falls anywhere inside the hold ends the attempt and
            # no turn is opened for the few milliseconds between the two.
            now = max(now, self._hold[1])
        # A timed attempt whose deadline has passed ends here and no turn opens (Engine.settle).
        return self.engine.settle(now)

    def _distress_open(self):
        # The moment the rules let a crew member ask for distress (Engine._proposal).
        s = self.engine.s
        return s['phase'] == 'assistance' and len(s['humans']) > 2 and not s['distress']

    def begin_opens(self):
        """The monotonic moment the Party Host's Begin opens, or None when it is open already
        (or is not the host's)."""
        if not (self.engine and self.lifecycle_authority() == 'host' and self._distress_open()):
            return None
        s = self.engine.s
        if self._grace is None or self._grace[0] != s['attempt'] or self._grace[1] <= _mono():
            return None
        return self._grace[1]

    def _wall_moment(self, expiry):
        # The engine's deadline as a wall-clock moment, for the shared timer and the browsers.
        return None if expiry is None else _wall() + (expiry - _mono())

    @staticmethod
    def _clock_continuous(clock, expiry=None, seconds=None):
        # After a restart the saved deadline still means something only if the monotonic clock
        # is the one the snapshot was written under: the same boot by the kernel's own word, a
        # clock that has not gone backward, and agreement with the wall clock about how long the
        # server was down (no step, no suspend). An appliance without a real-time clock cannot
        # say how long it was off, and its clocks can line up again after a reboot; where the
        # boot cannot be identified, nothing is trusted.
        if not (isinstance(clock, dict) and _reading(clock.get('wall')) and _reading(clock.get('mono'))):
            return False
        boot = _boot()
        if not (isinstance(boot, str) and boot and clock.get('boot') == boot):
            return False
        # A running deadline is never later than a full timer from when the snapshot was written.
        if expiry is not None and not (_reading(expiry) and _reading(seconds)
                                       and expiry <= clock['mono'] + seconds):
            return False
        return (_mono() >= clock['mono']
                and abs((_wall() - _mono()) - (clock['wall'] - clock['mono'])) <= CLOCK_TOLERANCE)

    def game_action(self, token, msg):
        if not isinstance(msg, dict) or not self.engine:
            return [self.fx('invalid', to=token, code='payload', msg='No active mission.')]
        actor = self.players[token].pid if token in self.participants and token in self.players else None
        refusal = self._host_owned(msg)
        if refusal:
            return [self.fx('invalid', to=token, code='host', msg=refusal)]
        return self._commit(token, lambda: self.engine.apply(actor, msg, _mono()))

    def _host_owned(self, msg):
        # A Party round belongs to the Party (avrana-party ADR 0011): its host ends it, there,
        # for everyone. Where the Party also says who its host is, Begin, Retry and Next are the
        # host's too (host_action) and no seat may propose them. A Party that does not say
        # leaves them to the crew, as a standalone table does. Decisions the rules give the crew
        # or the captain (distress, assignments) are never the host's.
        if not self.party_round or msg.get('t') != 'propose' or not isinstance(msg.get('proposal'), dict):
            return None
        kind = msg['proposal'].get('kind')
        if kind == 'end':
            return PARTY_END
        owned = self.party_host or not HOST_CLAIM_TRANSITION
        return HOST_ONLY.get(kind) if owned and isinstance(kind, str) else None

    def lifecycle_authority(self):
        owned = self.party_round and (self.party_host or not HOST_CLAIM_TRANSITION)
        return 'host' if owned else 'crew'

    def host_claim_missing(self):
        # A Party round whose Party has not said who its host is: the transitional allowance.
        return bool(HOST_CLAIM_TRANSITION and self.party_round and not self.party_host)

    def host_action(self, action):
        # core.net has the Party's word, on a fresh ticket, that the sender is its host now. The
        # host may be the captain, another seat or a spectator: none of that matters here, and
        # nothing here makes the host the captain. The engine still refuses a step whose
        # prerequisites the rules set (Engine.lifecycle).
        if not self.party_round:
            raise HostRefused('This table is not a Party round.')
        if not self.engine or not isinstance(action, dict):
            raise HostRefused('No active mission.', 'payload')
        decision = action.get('decision')
        if isinstance(decision, dict) and decision.get('kind') == 'begin' and self.begin_opens() is not None:
            raise HostRefused(GRACE, 'grace')
        refused = []
        fxs = self._commit(None, lambda: self.engine.lifecycle(action, _mono()), refused)
        if refused:
            raise HostRefused(*refused)
        return fxs

    def _commit(self, token, change, refused=None):
        # One engine command with its save. A refusal goes back to `token`, or into `refused`
        # (message, code) for a caller that has no seat to answer.
        def invalid(code, text):
            if refused is not None:
                refused.extend((text, code))
                return []
            return [self.fx('invalid', to=token, code=code, msg=text)]
        self._settle_due()
        before = self.engine.snapshot()
        try:
            change()
            self._sync()
            self._save()
        except Invalid as e:
            # Expiry is an independent server observation even on a rejected request.
            self._sync()
            try:
                self._save()
            except OSError:
                return invalid('storage', 'The table could not be saved. Try again.')
            return invalid(e.code, str(e))
        except OSError:
            self.engine = Engine.restore(before)
            self.rng = self.engine.rng
            self._sync()
            return invalid('storage', 'The table could not be saved. Try again.')
        if self.phase == 'closed':
            self._outcome = 'abandoned' if self.engine.s['result']['status'] == 'abandoned' else 'completed'
            return self.end_game()
        return []

    def game_tick(self):
        if self.engine:
            self.engine.observe_time(_mono())
            self._settle_due()
            self._sync()
            try:
                self._save()
            except OSError:
                # The timer fired for a deadline or for the end of a resolving trick.
                return [self.fx('toast', msg='The table could not be saved just now. A restored table is checked again: its deadline, and a trick that was being resolved.')]
        else:
            self._bump(None)
        return []

    def game_state(self, viewer_token):
        if not self.engine:
            return None
        viewer = self.players.get(viewer_token)
        view = self.engine.view(viewer.pid if viewer and viewer_token in self.participants else None)
        # The deadline is fixed for the attempt: a resolving hold does not move it (owner
        # decision 2026-10-05), so every view is sent the same moment from Begin to the result.
        view['expiry'] = self._wall_moment(view['expiry'])
        # 'host': the Party Host begins, retries and moves on; 'crew': the seated crew agrees.
        view['lifecycle'] = self.lifecycle_authority()
        # The wall-clock moment the host's Begin opens (the distress opportunity), or None.
        view['begin_at'] = self._wall_moment(self.begin_opens())
        # True only under a Party that does not name its host yet (HOST_CLAIM_TRANSITION).
        view['lifecycle_transitional'] = self.host_claim_missing()
        # While a trick is resolving: the wall-clock moment the next one opens (AVR-246).
        if view['resolving'] is not None:
            view['resolving']['until'] = self._wall_moment(self._hold[1]) if self._hold else None
        return view

    def state_for(self, viewer_token=None, spectator=False):
        # Party spectators (core/session.py) get game_state_spectator(): EXPO keeps the default,
        # the public view, so no hand ever reaches a spectator.
        st = super().state_for(viewer_token, spectator)
        st['missions'] = catalog(max(2, len(self._connected_ready())), self.settings['timed'])
        st['recovery_error'] = self.recovery_error
        return st

    def _presence(self, token, away):
        if self.engine and token in self.participants:
            self.engine.presence(self.players[token].pid, away)
            # Connection presence is ephemeral; restoration always marks every
            # human away. Card actions persist the authoritative table.
        return []

    def game_player_left(self, token):
        return self._presence(token, True)

    def game_player_back(self, token):
        return self._presence(token, False)

    def join(self, token, name=None, avatar=None):
        if self.engine and self.in_game() and token not in self.players:
            self.MAX_HUMANS = 10  # bounded public watchers; never added to participants
        try:
            return super().join(token, name, avatar)
        finally:
            self.__dict__.pop('MAX_HUMANS', None)

    def leave(self, token):
        if self.engine and token in self.participants and self.phase != 'game_end':
            self.seq += 1
            self.players[token].connected = False
            self.players[token].ready = False
            return self.game_player_left(token)
        return super().leave(token)

    def to_lobby(self):
        # core/net handles `again` without authentication beyond connection. It
        # cannot discard a crew table; only the consensual End action closes it.
        if self.engine and self.phase != 'game_end':
            return []
        if self.store:
            self.store.clear()
        self.engine = None
        # Keep only the seated humans; watchers can reconnect to the new lobby.
        for t in list(self.players):
            if t not in self.participants:
                del self.players[t]
        return super().to_lobby()

    def snapshot(self):
        return {'version': 1, 'engine': self.engine.snapshot(), 'settings': deepcopy(self.settings),
                'clock': {'wall': _wall(), 'mono': _mono(), 'boot': _boot()},
                'participants': list(self.participants), 'pid_counter': self._pid_counter,
                'players': [{k: getattr(p, k) for k in Player.__slots__} for p in self.players.values()
                            if p.token in self.participants]}

    def restore(self, saved):
        if saved.get('version') != 1:
            raise ValueError('Invalid session snapshot')
        engine = Engine.restore(saved['engine'])
        players = {}
        for row in saved['players']:
            p = Player(row['token'], row['pid'], row['name'], row['avatar'], row['color'])
            for k in Player.__slots__:
                setattr(p, k, row[k])
            p.connected = False
            players[p.token] = p
        if ({players[t].pid for t in saved['participants']} != set(engine.s['humans'])
                or len(players) != len(engine.s['humans'])):
            raise ValueError('Invalid saved seat identity mapping')
        engine.s['away'] = list(engine.s['humans'])
        engine.s['revision'] += 1
        # A trick that was resolving when the snapshot was written has nobody watching it now:
        # it settles at once. A timed attempt is judged first, so that one whose deadline has
        # passed, or whose clock cannot be trusted, ends without a turn being opened.
        if self._clock_continuous(saved.get('clock'), engine.s['expiry'], engine.s['mission']['seconds']):
            engine.settle(_mono())
            engine.observe_time(_mono())
            ended = False
        else:
            ended = engine.expire(UNTRUSTED_CLOCK)
            engine.settle()
        self.engine, self.rng, self.players = engine, engine.rng, players
        self.participants, self._pid_counter = saved['participants'], saved['pid_counter']
        self.settings = saved['settings']
        self._sync()
        if ended:
            # The end should outlive this process too: a later restart on the saved boot would
            # otherwise find the deadline still running in the file. If the write fails, that
            # restart judges the clocks again; a reboot still ends the attempt.
            try:
                self._save()
            except OSError:
                pass
        if engine.s['phase'] == 'closed':
            self.end_game()

    def _save(self):
        if self.store and self.engine:
            self.store.write(self.snapshot())
