"""Game result envelope v1 (`avrana.game-result/v1`): what one game server tells the party about
how one session finished. ADR 0015 has the semantics; this file is the reference implementation.

It is versioned on its own. It travels as the optional `result` field of the session protocol's
signed `ended` message (avrana.party.protocol, ADR 0006), so it is authenticated, bound to one
session and replay-guarded by that message; nothing here signs or transports anything.

Self-contained (stdlib, no avrana imports) so a game repository can vendor this one file; the
cases in contracts/vectors/game-result.v1.json pin the rules across repositories.

    {
      "schema": "avrana.game-result/v1",
      "game": {"id": "bluff", "build": "sha256:3f9c…", "content": "…"},     platform: provenance
      "mode": "competitive" | "cooperative",                                platform
      "standings": [{"participant": "participant-…",                        platform: one entry
                     "standing": "won" | "lost" | "draw",                   per PLAYER of the
                     "rank": 1}, …],                                        session, no one else
      "data_schema": "bluff.result/v1",                                     game-owned
      "data": {…}                                                           game-owned, small
    }

People are named only by the session's participant ids, which the party issued in the launch
roster. A game never has a member or device id, so it cannot put one here.

The platform reads `game`, `mode` and `standings`. `data` belongs to the game: the party checks
its size and shape, keeps it, and never interprets it. `data_schema` names the game's own format
so a later reader knows what it is looking at.

Two entry points:
    build(...)                      game side: assemble a result, refusing an invalid one
    check(result, game, players)    party side: the only way a result is accepted
"""
import json
import math
import re

SCHEMA = 'avrana.game-result/v1'
MAX_BYTES = 2048            # canonical JSON of the whole result
MAX_DATA_BYTES = 1024       # canonical JSON of `data`
MAX_DEPTH = 4               # containers nested inside `data`
MAX_KEY = 64                # a participant id fits, so data may be keyed by participant
MAX_STRING = 200
MAX_INT = 2 ** 53           # what a JSON number holds exactly everywhere
MODES = ('competitive', 'cooperative')
STANDINGS = ('won', 'lost', 'draw')
GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')
PID = re.compile(r'^participant-[0-9a-f]{32}$')
TAG = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}$')              # build and content ids
DATA_SCHEMA = re.compile(r'^[a-z][a-z0-9_.-]{0,39}/v[0-9]{1,3}$')


class Refused(Exception):
    """A result was not accepted. `str(e)` names the reason (for logs and tests only)."""


def _canonical(obj):
    try:
        return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError):
        raise Refused('shape')


def _data(value, players, depth):
    """`data` is authenticated but untrusted: bounded depth, plain JSON types, bounded strings
    and numbers, and no participant id that is not a player of this session."""
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_INT:
            raise Refused('data')
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise Refused('data')
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            raise Refused('data')
        if PID.match(value) and value not in players:
            raise Refused('not_in_session')
        return
    if depth >= MAX_DEPTH:
        raise Refused('data')
    if isinstance(value, list):
        for item in value:
            _data(item, players, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not 0 < len(key) <= MAX_KEY:
                raise Refused('data')
            if PID.match(key) and key not in players:
                raise Refused('not_in_session')
            _data(item, players, depth + 1)
        return
    raise Refused('data')


def check(result, game, players):
    """Party side. `game` is the id of the game this session runs (and the issuer of the message
    that carried the result); `players` are the participant ids of the session's players. Returns
    a clean copy of the result, or raises Refused. Fails closed: anything not understood is a
    refusal, never a guess."""
    if not isinstance(result, dict):
        raise Refused('shape')
    if len(_canonical(result)) > MAX_BYTES:
        raise Refused('size')
    if result.get('schema') != SCHEMA:
        raise Refused('schema')
    if not set(result) <= {'schema', 'game', 'mode', 'standings', 'data_schema', 'data'}:
        raise Refused('shape')

    g = result.get('game')
    if not isinstance(g, dict) or not {'id', 'build'} <= set(g) <= {'id', 'build', 'content'}:
        raise Refused('game')
    if g['id'] != game or not isinstance(g['id'], str) or not GAME_ID.match(g['id']):
        raise Refused('game')
    for tag in ('build', 'content'):
        if tag in g and not (isinstance(g[tag], str) and TAG.match(g[tag])):
            raise Refused('game')

    if result.get('mode') not in MODES:
        raise Refused('mode')

    players = list(players)
    standings = result.get('standings')
    if not isinstance(standings, list) or not standings:
        raise Refused('standings')
    seen, ranked = [], 0
    for entry in standings:
        if not isinstance(entry, dict) or \
                not {'participant', 'standing'} <= set(entry) <= {'participant', 'standing', 'rank'}:
            raise Refused('standings')
        pid = entry['participant']
        if not isinstance(pid, str) or not PID.match(pid):
            raise Refused('participant')
        if pid not in players:
            raise Refused('not_in_session')
        if pid in seen or entry['standing'] not in STANDINGS:
            raise Refused('standings')
        seen.append(pid)
        if 'rank' in entry:
            rank = entry['rank']
            if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= len(players):
                raise Refused('rank')
            ranked += 1
    if set(seen) != set(players):
        raise Refused('incomplete')                 # every player, nobody else
    if ranked not in (0, len(standings)):
        raise Refused('rank')                       # ranks for everyone or for no one
    if result['mode'] == 'cooperative':
        shared = {entry['standing'] for entry in standings}
        if len(shared) != 1 or shared == {'draw'}:
            raise Refused('standings')              # the table wins or loses together

    if ('data_schema' in result) != ('data' in result):
        raise Refused('data_schema')
    if 'data' in result:
        if not isinstance(result['data_schema'], str) or not DATA_SCHEMA.match(result['data_schema']):
            raise Refused('data_schema')
        if not isinstance(result['data'], dict):
            raise Refused('data')
        if len(_canonical(result['data'])) > MAX_DATA_BYTES:
            raise Refused('size')
        _data(result['data'], players, 0)
    return json.loads(_canonical(result))


def build(game, build, mode, standings, players, data_schema=None, data=None, content=None):
    """Game side. `standings` is a list of {participant, standing[, rank]}; `players` are the
    player participant ids from the launch roster. Returns the result, having passed the same
    check the party will apply; raises Refused otherwise, so a game cannot send what would be
    turned away."""
    result = {'schema': SCHEMA, 'game': {'id': game, 'build': build}, 'mode': mode,
              'standings': [dict(entry) for entry in standings]}
    if content is not None:
        result['game']['content'] = content
    if data is not None or data_schema is not None:
        result['data_schema'], result['data'] = data_schema, data
    return check(result, game, players)
