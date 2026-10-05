"""core.net — sockets, timers, and bot scheduling for a GameSession.

One GameBinding per registered game. It owns:
  * the WebSocket endpoint for that game (mounted at /games/<slug>/ws)
  * an asyncio.Lock — every session mutation happens under it
  * personalized state pushes after every mutation (state_for per token)
  * exactly one pending deadline task, kept in sync with (deadline, gen)
  * bot scheduling: after every push, if session.next_bot_action() says a bot
    is due, a task runs it after the given delay (dropped if session.seq moved)

Party sessions (core/party_session.py, AVR-22/AVR-24): a binding given a GameSide admits players
by Party ticket at the hello. While the room belongs to a party session, a browser-minted token
only watches. When the game's rules finish or abandon that game (session.take_outcome()), the
binding reports `ended` once, off the lock; the party's /end resets the room at once. Either way
the room then goes back to its pre-launch state (fresh, empty, no party session) and the
session's phones get a `party_ended` fx, after any results screen.

Party rounds (AVR-129): the party ran the pregame, so a launch seats its roster's players at once
(GameSession.party_start) and the game's own ready/start lobby is skipped. A spectator ticket gets
a Party spectator socket, which is sent state_for(None, spectator=True): what the game lets
spectators see (BLUFF: every hand). Player sockets and anonymous watchers (a browser token, a TV)
never get it.

Games never touch sockets; this file never touches game rules.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

from core import avatars, party_protocol, party_result, party_session
from core.events import event
from core.session import HostRefused

log = logging.getLogger("gamehub.net")

RATE_N, RATE_WINDOW = 30, 2.0   # generous: stepper-mashing kids must not get
                                # throttled; realtime games send ~11Hz movement
MAX_SOCKETS_PER_TOKEN = 4
# Anonymous watchers per room (a TV, a passer-by). Each socket may hold up to
# ws_limit.MAX_OUTBOUND_BACKLOG in the server, so their number is capped too (AVR-217).
MAX_WATCHERS = 32

# Lobby verbs handled here for every game; anything else goes to game_action.
LOBBY_VERBS = ("ready", "start", "settings", "profile", "leave_table")
# Verbs worth a lifecycle log line (who started, who left or ended a game).
LOGGED_VERBS = ("ready", "start", "again", "leave_table", "leave_game", "end_game")


class GameBinding:
    def __init__(self, slug, session, party=None, party_url=None, standalone=True):
        self.slug = slug
        self.session = session
        # False retires standalone play for this room (AVR-222; avrana-party ADR 0014): a hello
        # without a Party ticket may only watch, so a browser-minted `wc-token` never takes a seat.
        self.standalone = standalone
        self.party = party            # party_protocol.GameSide, or None: standalone only
        self.party_url = party_url    # where `ended` goes (party_session.party_url), or None
        self.party_roster: dict[str, dict] = {}   # game token -> roster entry (players only)
        # the party session this room belongs to, from launch until it is released. It outlives
        # self.party.sid (admission) through the results screen of a completed game.
        self.party_room_sid: str | None = None
        self._party_outcome: str | None = None    # reported, waiting for the room to go idle
        self._party_last_sid: str | None = None   # the latest launch, for a late or racing /end
        self._party_reports: set[asyncio.Task] = set()
        self.lock = asyncio.Lock()
        self.player_sockets: dict[str, set[WebSocket]] = {}
        self.watch_sockets: set[WebSocket] = set()
        self.spectator_sockets: set[WebSocket] = set()   # Party spectators (spectator tickets)
        self._timer_task: asyncio.Task | None = None
        self._bot_task: asyncio.Task | None = None
        self._phase = session.phase

    def _pid(self, token):
        p = self.session.players.get(token)
        return p.pid if p is not None else None

    # ---- push ----

    async def _send(self, ws, obj):
        try:
            await ws.send_text(json.dumps(obj))
        except Exception:
            pass  # dead socket; its receive loop will reap it

    async def push_all(self, fxs):
        for fx in fxs or []:
            fx = dict(fx)
            to = fx.pop("to", None)
            msg = {"type": "fx", **fx}
            if to is None:
                for socks in list(self.player_sockets.values()):
                    for ws in list(socks):
                        await self._send(ws, msg)
                for ws in list(self.watch_sockets) + list(self.spectator_sockets):
                    await self._send(ws, msg)
            else:
                for ws in list(self.player_sockets.get(to, ())):
                    await self._send(ws, msg)
        for token, socks in list(self.player_sockets.items()):
            st = self.session.state_for(token)
            for ws in list(socks):
                await self._send(ws, st)
        if self.watch_sockets:
            st = self.session.state_for(None)
            for ws in list(self.watch_sockets):
                await self._send(ws, st)
        if self.spectator_sockets:
            st = self.session.state_for(None, spectator=True)
            for ws in list(self.spectator_sockets):
                await self._send(ws, st)
        if self.session.phase != self._phase:
            event(self.slug, "phase", old=self._phase, new=self.session.phase,
                  seated=[self._pid(t) for t in self.session.participants])
            self._phase = self.session.phase
        self._sync_timer()
        self._sync_bot()
        await self._party_after_push()

    # ---- deadline timer ----

    def _sync_timer(self):
        cur = None
        try:
            cur = asyncio.current_task()
        except RuntimeError:
            pass
        if self._timer_task is not None and self._timer_task is not cur \
                and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None
        if self.session.deadline is not None:
            self._timer_task = asyncio.create_task(
                self._fire(self.session.gen, self.session.remaining()))

    async def _fire(self, gen, delay):
        # `delay` is measured on the monotonic clock (GameSession.remaining). This task is
        # re-created on every push, so re-reading the wall clock here would let a clock step
        # fire the deadline at once, or hold it back by the size of the step (AVR-221).
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self.lock:
            if self._timer_task is asyncio.current_task():
                self._timer_task = None
            if self.session.gen != gen:
                return
            try:
                fxs = self.session.tick(gen)
                await self.push_all(fxs)
            except Exception:
                log.exception("[%s] tick error", self.slug)
                if self.session.gen == gen:
                    # tick died before advancing the generation — re-arming
                    # the same expired deadline would hot-loop the exception.
                    # gen++ kills the failing generation; retry in 2s.
                    self.session._bump(time.time() + 2.0)
                self._sync_timer()
                self._sync_bot()

    # ---- bots ----

    def _sync_bot(self):
        cur = None
        try:
            cur = asyncio.current_task()
        except RuntimeError:
            pass
        if self._bot_task is not None and self._bot_task is not cur \
                and not self._bot_task.done():
            self._bot_task.cancel()
        self._bot_task = None
        due = self.session.next_bot_action()
        if due is not None:
            delay, bot_token = due
            self._bot_task = asyncio.create_task(
                self._run_bot(self.session.seq, delay, bot_token))

    async def _run_bot(self, seq, delay, bot_token):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        async with self.lock:
            if self._bot_task is asyncio.current_task():
                self._bot_task = None
            if self.session.seq != seq:
                return  # something happened meanwhile; next push reschedules
            try:
                fxs = self.session.run_bot(bot_token)
                await self.push_all(fxs)
            except Exception:
                log.exception("[%s] bot error", self.slug)
                self._sync_timer()
                self._sync_bot()

    # ---- party session (core/party_session.py) ----

    async def party_launch(self, message):
        """A signed launch from the party: this room now belongs to that session and roster.
        The old room is replaced, not tidied: a fresh session object carries no hands, seats,
        timers or players across (BLUFF's own to_lobby() refuses during its results screen).
        Raises party_protocol.Invalid, changing nothing, if the message is refused."""
        if self.party is None:
            raise party_protocol.Invalid("no party side")
        async with self.lock:
            roster = self.party.on_launch(message)
            self.party_roster = {
                party_protocol.game_token(self.party.key, self.party.sid, r["participant"]): r
                for r in roster if r["role"] == "player"}
            self.party_room_sid = self._party_last_sid = self.party.sid
            self._party_outcome = None
            # every phone comes back with a fresh ticket and the new roster decides its role:
            # a watcher of the last session may be a player now (no reload needed); TV pages
            # simply reconnect as watchers
            old = self._fresh_room() + list(self.watch_sockets) + list(self.spectator_sockets)
            self.watch_sockets, self.spectator_sockets = set(), set()
            event(self.slug, "party_launch", players=len(self.party_roster),
                  spectators=len(roster) - len(self.party_roster), dropped=len(old))
            await self._close_all(old)
            # the party ran the pregame and its host started the round: seat its players now
            fxs = self.session.party_start([(t, r["name"]) for t, r in self.party_roster.items()])
            await self.push_all(fxs)
        return roster

    async def party_end(self, message):
        """A signed end from the party (the host ended it for everyone): the room goes back to
        a non-running state at once and that session's tickets die. No `ended` is reported: the
        party asked. An end for the latest session that already finished here (reported, or on
        its results screen) is acknowledged too, so the host's End always confirms; it releases
        the room only if the room still belongs to that session. Returns the session id.
        Raises party_protocol.Invalid, changing nothing, if the message is refused."""
        if self.party is None:
            raise party_protocol.Invalid("no party side")
        async with self.lock:
            # peek at the session first (signature, type, audience, time); then the full check,
            # replay guard included, exactly once
            sid = party_protocol.unseal(self.party.key, message, "end", self.party.game)["sid"]
            if sid == self.party.sid:
                self.party.on_end(message)
            elif sid == self._party_last_sid:
                party_protocol.open_message(self.party.key, message, "end", self.party.game,
                                            self.party.guard)
            else:
                raise party_protocol.Invalid("session")
            running = self.party_room_sid == sid
            event(self.slug, "party_end", running=running)
            if running:
                # a finished round keeps its own outcome (the host moved on from its results)
                await self._party_release(self._party_outcome or "ended")
        return sid

    def _fresh_room(self):
        """Replace the room with a fresh session object (no hands, seats, timers or players)
        and forget its player sockets. Returns those sockets for the caller to close."""
        cur = asyncio.current_task()
        for task in (self._timer_task, self._bot_task):
            if task is not None and task is not cur and not task.done():
                task.cancel()
        self._timer_task = self._bot_task = None
        old = [ws for socks in self.player_sockets.values() for ws in socks]
        self.player_sockets = {}
        self.session = type(self.session)()
        self._phase = self.session.phase
        return old

    async def _close_all(self, sockets):
        for ws in sockets:
            try:
                await ws.close()
            except Exception:
                pass

    async def _party_after_push(self):
        """Under the lock, after every mutation: did the game's own rules just finish or abandon
        the party session's game? Then report it once and, once the room is idle (after any
        results screen), release it."""
        outcome = self.session.take_outcome()        # always taken, so none is ever stale
        if self.party_room_sid is None:
            return                                   # standalone: nothing to report
        if outcome is not None and self.party.sid == self.party_room_sid:
            result = self._party_result() if outcome == "completed" else None
            report = self.party.ended(outcome, result=result)    # admission stops here
            self._party_outcome = outcome
            event(self.slug, "party_ended", outcome=outcome, result=result is not None)
            task = asyncio.create_task(party_session.deliver_ended(
                self.party_url, report, self.slug, outcome))
            self._party_reports.add(task)
            task.add_done_callback(self._party_reports.discard)
        if self._party_outcome is not None and not self.session.in_game():
            await self._party_release(self._party_outcome)

    def _party_result(self):
        """The game's structured result for the party (avrana.game-result/v1), or None. The game
        speaks in its own tokens; here they become the participant ids of the launch roster,
        the only names for people the party accepts. A result that is missing, malformed or
        would be refused is left out: the session still ends, as it did before results existed."""
        def ref(token):
            entry = self.party_roster.get(token)
            return entry["participant"] if entry else None
        try:
            made = self.session.game_result(ref)
            if made is None:
                return None
            standings = []
            for entry in made["standings"]:
                if ref(entry["token"]) is None:
                    continue                      # not a party participant (a bot)
                row = {"participant": ref(entry["token"]), "standing": entry["standing"]}
                if "rank" in entry:
                    row["rank"] = entry["rank"]
                standings.append(row)
            return party_result.build(
                self.slug, party_session.build_id(self.slug), made["mode"], standings,
                [r["participant"] for r in self.party_roster.values()],
                data_schema=made.get("data_schema"), data=made.get("data"),
                content=made.get("content"))
        except party_result.Refused as e:
            log.error("[%s] game result not sent: it would be refused (%s)", self.slug, e)
        except Exception:
            log.exception("[%s] game result not sent", self.slug)
        return None

    async def _party_release(self, outcome):
        """The party session is over: tell its phones (a `party_ended` fx: the page shows Back
        to Party; no automatic navigation), close the players' sockets and put back a fresh,
        empty room with no party session: the same state as before the first launch, so the
        next launch, or standalone play, starts clean. Watchers stay and see that empty lobby."""
        msg = {"type": "fx", "kind": "party_ended", "outcome": outcome,
               "msg": "This game is over. Go Back to Party."}
        players = [ws for socks in self.player_sockets.values() for ws in socks]
        spectators, self.spectator_sockets = list(self.spectator_sockets), set()
        for ws in players + spectators + list(self.watch_sockets):
            await self._send(ws, msg)
        self.party_room_sid = None
        self._party_outcome = None
        self.party_roster = {}
        # Party spectators stay, like watchers, but only ever see the public view from now on:
        # the omniscient view belonged to that party session and never reaches a later room
        self.watch_sockets |= set(spectators)
        old = self._fresh_room()
        event(self.slug, "party_release", outcome=outcome, dropped=len(old))
        await self._close_all(old)
        await self.push_all([])

    def _party_hello(self, hello):
        """(token, name, spectator, participant) for an admitted player; (None, None, spectator,
        participant) to watch, where `spectator` is True only for a Party spectator ticket
        (AVR-129) and `participant` is the ticket's participant id (None without a ticket).
        Raises Invalid for a ticket that is refused. The ticket itself is never logged."""
        ticket = hello.get("ticket")
        if ticket is None:
            return None, None, False, None      # a browser-minted token: watch only (public)
        who = self.party.present(ticket)
        if who["host"] is not None:
            # this party says who its host is (avrana-party ADR 0006, amendment 2026-10-04): the
            # game may give the host things to do. Who that is, is asked again with every action.
            self.session.party_host = True
        entry = self.party_roster.get(who["token"])
        if who["role"] != "player" or entry is None:
            return None, None, who["role"] == "spectator", who["participant"]
        return who["token"], entry["name"], False, who["participant"]

    async def _party_host_action(self, ws, participant, msg):
        """{"t": "host", "ticket": <a fresh ticket>, "action": {...}}: something only the Party
        Host may do in this game (AVR-252). Under the lock. The party's word is that one ticket:
        it must be valid for the running session, unspent, minted for this connection's own
        participant, and say `host: true`. Nothing about the host is kept here, so the next
        action is asked again and succession needs no message. A player or a Party spectator may
        be the host; an anonymous watcher never is. What the action means is the game's
        (GameSession.host_action). The ticket is never logged."""
        async def refuse(text, code="host"):
            await self._send(ws, {"type": "fx", "kind": "invalid", "code": code, "msg": text})
        action = msg.get("action")
        if self.party is None or participant is None or not isinstance(action, dict)                 or self.party_room_sid is None or self.party.sid != self.party_room_sid:
            await refuse("Only the Party Host can do that.")
            return
        try:
            who = self.party.present(msg.get("ticket"))
        except party_protocol.Invalid as e:
            event(self.slug, "host_refused", reason=str(e))
            await refuse("The Party could not confirm its Host. Try again.")
            return
        if who["participant"] != participant or who["host"] is not True:
            event(self.slug, "host_refused", reason="not_host")
            await refuse("Only the Party Host can do that.")
            return
        self.session.party_host = True
        event(self.slug, "host_action", t=action.get("t") if isinstance(action.get("t"), str) else None)
        try:
            fxs = self.session.host_action(action)
        except HostRefused as e:
            await refuse(str(e), e.code)
            fxs = []
        await self.push_all(fxs)

    # ---- websocket endpoint ----

    async def endpoint(self, ws: WebSocket):
        await ws.accept()
        token = None
        room = None                             # the room this connection joined (AVR-25)
        watching = False
        spectating = False                      # a Party spectator (AVR-129)
        participant = None                      # this connection's Party participant, by ticket
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=15)
            hello = json.loads(raw)
            assert isinstance(hello, dict) and hello.get("t") == "hello"
        except Exception:
            await ws.close()
            return

        # a ticket always takes the party path (refused if this game cannot verify it); while the
        # room belongs to a party session, so does every other hello
        party = "ticket" in hello or self.party_room_sid is not None
        if party:
            try:
                if self.party is None:
                    raise party_protocol.Invalid("no party side")
                token, name, spectating, participant = self._party_hello(hello)
            except party_protocol.Invalid as e:
                event(self.slug, "ticket_refused", reason=str(e))
                await self._send(ws, {"type": "fx", "kind": "invalid",
                                      "msg": "Party ticket refused. Go back to Party and try again."})
                await ws.close()
                return
            watching = token is None
        else:
            watching = bool(hello.get("watch"))
            name = hello.get("name")
            if not watching and not self.standalone:
                event(self.slug, "standalone_refused")
                watching = True                 # no Party ticket: the public view only

        if watching:
            watching = True
            async with self.lock:
                if spectating:
                    self.spectator_sockets.add(ws)
                    event(self.slug, "spectate_open")
                    await self._send(ws, {"type": "welcome", "watch": True, "spectator": True})
                    await self._send(ws, self.session.state_for(None, spectator=True))
                elif len(self.watch_sockets) >= MAX_WATCHERS:
                    event(self.slug, "watch_refused", watchers=len(self.watch_sockets))
                    await self._send(ws, {"type": "fx", "kind": "invalid",
                                          "msg": "Too many screens are watching this game"})
                    await ws.close()
                    return
                else:
                    self.watch_sockets.add(ws)
                    event(self.slug, "watch_open")
                    await self._send(ws, {"type": "welcome", "watch": True})
                    await self._send(ws, self.session.state_for(None))
        else:
            if not party:
                token = hello.get("token")
                if not (isinstance(token, str) and 8 <= len(token) <= 64
                        and not token.startswith("bot:")
                        and token.replace("-", "").replace("_", "").isalnum()):
                    token = secrets.token_urlsafe(16)
            async with self.lock:
                if party and token not in self.party_roster:
                    await ws.close()            # a newer launch replaced the roster meanwhile
                    return
                if not party and self.party_room_sid is not None:
                    await ws.close()            # a launch started a party session meanwhile:
                    return                      # the reconnect only watches
                if len(self.player_sockets.get(token, ())) >= MAX_SOCKETS_PER_TOKEN:
                    await ws.close()
                    return
                known = token in self.session.players
                player, fxs = self.session.join(token, name, hello.get("avatar"))
                if player is None:
                    event(self.slug, "join_rejected",
                          reason=next((f.get("msg") for f in fxs if f.get("msg")), None))
                    for f in fxs:
                        await self._send(ws, {"type": "fx",
                                              **{k: v for k, v in f.items() if k != "to"}})
                    await ws.close()
                    return
                player.pfp = player.picture(avatars.url_for(token))
                self.player_sockets.setdefault(token, set()).add(ws)
                room = self.session             # this connection acts on this room only (AVR-25)
                event(self.slug, "rejoin" if known else "join", pid=player.pid, name=player.name,
                      sockets=len(self.player_sockets[token]), phase=self.session.phase,
                      seated=token in self.session.participants)
                # a party game token stays on the server: reconnects fetch a new ticket
                welcome = {"type": "welcome", "pid": player.pid}
                if not party:
                    welcome["token"] = token
                await self._send(ws, welcome)
                await self.push_all(fxs)

        stamps: deque[float] = deque()
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > 4096:
                    continue
                now = time.time()
                stamps.append(now)
                while stamps and now - stamps[0] > RATE_WINDOW:
                    stamps.popleft()
                if len(stamps) > RATE_N:
                    continue
                try:
                    msg = json.loads(raw)
                    assert isinstance(msg, dict)
                except Exception:
                    continue
                if msg.get("t") == "ping":
                    await self._send(ws, {"type": "pong",
                                          "now": int(time.time() * 1000)})
                    continue
                if msg.get("t") == "host":
                    # the Party Host's own actions: by ticket, from a seat or from the audience
                    async with self.lock:
                        if room is not None and self.session is not room:
                            event(self.slug, "stale_message_dropped")
                            await self._close_all([ws])
                            break
                        try:
                            await self._party_host_action(ws, participant, msg)
                        except Exception:
                            log.exception("[%s] host action error", self.slug)
                            self._sync_timer()
                            self._sync_bot()
                    continue
                if watching or token is None:
                    continue
                if msg.get("t") in LOGGED_VERBS:
                    event(self.slug, "verb", t=msg["t"], pid=self._pid(token))
                async with self.lock:
                    if self.session is not room:
                        # read before a launch or release replaced the room, and dispatched
                        # after it: an old session's message never reaches the next room
                        event(self.slug, "stale_message_dropped")
                        await self._close_all([ws])
                        break
                    try:
                        fxs = self.dispatch(token, msg)
                        await self.push_all(fxs)
                    except Exception:
                        log.exception("[%s] dispatch error", self.slug)
                        self._sync_timer()
                        self._sync_bot()
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("[%s] ws loop error", self.slug)
        finally:
            if watching:
                self.watch_sockets.discard(ws)
                self.spectator_sockets.discard(ws)
            elif token is not None:
                async with self.lock:
                    # a replaced room already forgot this socket; the next room never hears of it
                    socks = self.player_sockets.get(token) if self.session is room else None
                    if socks is not None:
                        socks.discard(ws)
                        event(self.slug, "socket_close" if socks else "disconnect",
                              pid=self._pid(token), sockets=len(socks), phase=self.session.phase)
                        if not socks:
                            del self.player_sockets[token]
                            fxs = self.session.leave(token)
                            await self.push_all(fxs)

    def dispatch(self, token, msg):
        s = self.session
        t = msg.get("t")
        if t == "ready":
            return s.set_ready(token, bool(msg.get("ready", True)))
        if t == "start":
            return s.start(token)
        if t == "settings":
            return s.set_settings(token, msg.get("patch"))
        if t == "profile":
            # a party member's name is the party's; the game may not rename them
            name = None if token in self.party_roster else msg.get("name")
            fx = s.set_profile(token, name, msg.get("avatar"))
            p = s.players.get(token)
            if p is not None:
                p.pfp = p.picture(avatars.url_for(token))   # re-check after uploads
            return fx
        if t == "again":
            return s.to_lobby() if s.phase == "game_end" else []
        return s.game_action(token, msg)
