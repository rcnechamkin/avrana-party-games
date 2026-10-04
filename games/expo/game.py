"""Avrana adapter: authentication, lobby, clock, masking and reconnect lifecycle."""
from copy import deepcopy
import os
import time

from core.session import GameSession, Player
from .content import catalog, mission
from .engine import Engine, Invalid
from .storage import SnapshotStore

# A timed mission runs on the monotonic clock (E-D7, AVR-242): a step of the wall clock, in
# either direction, neither grants nor takes time. Wall-clock moments exist only for browsers.
CLOCK_TOLERANCE = 2.0
UNTRUSTED_CLOCK = ('The server restarted and could not tell how much time had passed, '
                   'so the timed attempt has ended.')


def _mono():
    # Seconds since boot, the same for every process on the host (Linux and Windows).
    return time.monotonic()


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
        self._bump(self._wall_moment(self.engine.s['expiry']))

    def _wall_moment(self, expiry):
        # The engine's deadline as a wall-clock moment, for the shared timer and the browsers.
        return None if expiry is None else _wall() + (expiry - _mono())

    @staticmethod
    def _clock_continuous(clock):
        # After a restart the saved deadline still means something only if the monotonic clock
        # is the one the snapshot was written under: the same boot by the kernel's own word, a
        # clock that has not gone backward, and agreement with the wall clock about how long the
        # server was down (no step, no suspend). An appliance without a real-time clock cannot
        # say how long it was off, and its clocks can line up again after a reboot; where the
        # boot cannot be identified, nothing is trusted.
        if not (isinstance(clock, dict) and all(type(clock.get(k)) in (int, float) for k in ('wall', 'mono'))):
            return False
        boot = _boot()
        if not (isinstance(boot, str) and boot and clock.get('boot') == boot):
            return False
        return (_mono() >= clock['mono']
                and abs((_wall() - _mono()) - (clock['wall'] - clock['mono'])) <= CLOCK_TOLERANCE)

    def game_action(self, token, msg):
        if not isinstance(msg, dict) or not self.engine:
            return [self.fx('invalid', to=token, code='payload', msg='No active mission.')]
        actor = self.players[token].pid if token in self.participants and token in self.players else None
        before = self.engine.snapshot()
        try:
            self.engine.apply(actor, msg, _mono())
            self._sync()
            self._save()
        except Invalid as e:
            # Expiry is an independent server observation even on a rejected request.
            self._sync()
            try:
                self._save()
            except OSError:
                return [self.fx('invalid', to=token, code='storage', msg='The table could not be saved. Try again.')]
            return [self.fx('invalid', to=token, code=e.code, msg=str(e))]
        except OSError:
            self.engine = Engine.restore(before)
            self.rng = self.engine.rng
            self._sync()
            return [self.fx('invalid', to=token, code='storage', msg='The table could not be saved. Try again.')]
        if self.phase == 'closed':
            self._outcome = 'abandoned' if self.engine.s['result']['status'] == 'abandoned' else 'completed'
            return self.end_game()
        return []

    def game_tick(self):
        if self.engine:
            self.engine.observe_time(_mono())
            self._sync()
            try:
                self._save()
            except OSError:
                return [self.fx('toast', msg='The expired table could not be saved. Its deadline will be checked again on restoration.')]
        else:
            self._bump(None)
        return []

    def game_state(self, viewer_token):
        if not self.engine:
            return None
        viewer = self.players.get(viewer_token)
        view = self.engine.view(viewer.pid if viewer and viewer_token in self.participants else None)
        view['expiry'] = self._wall_moment(view['expiry'])
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
            pid = self.players[token].pid
            missing = self.engine.s['away']
            if away and pid not in missing:
                missing.append(pid)
                self.engine.s['revision'] += 1
            elif not away and pid in missing:
                missing.remove(pid)
                self.engine.s['revision'] += 1
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
        if self._clock_continuous(saved.get('clock')):
            engine.observe_time(_mono())
            ended = False
        else:
            ended = engine.expire(UNTRUSTED_CLOCK)
        self.engine, self.rng, self.players = engine, engine.rng, players
        self.participants, self._pid_counter = saved['participants'], saved['pid_counter']
        self.settings = saved['settings']
        self._sync()
        if ended:
            # The end must outlive this process too: a later restart on the saved boot would
            # otherwise find the deadline still running in the file.
            try:
                self._save()
            except OSError:
                pass
        if engine.s['phase'] == 'closed':
            self.end_game()

    def _save(self):
        if self.store and self.engine:
            self.store.write(self.snapshot())
