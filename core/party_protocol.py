"""Party session protocol v0 (`avrana.party-session/v0`): the wire contract between the party and
one game server. ADR 0006 has the semantics; this file is the reference implementation.

It is deliberately separate from three other things:
  * Party Core's Python API (avrana.party.core): internal, may change freely;
  * LAN Games' GameSession class: one game-side implementation, not the protocol;
  * a future native-game SDK: would wrap this protocol, and does not exist.

Self-contained (stdlib, no avrana imports) so a game repository can vendor this one file; the
vectors in contracts/vectors/party-session.v0.json pin the format across repositories.

Envelope, for every token and message:

    aps0.<base64url(canonical JSON payload)>.<base64url(HMAC-SHA256(key, "aps0." + part1))>

Canonical JSON = sorted keys, no spaces, UTF-8. Every payload carries:
    v    "avrana.party-session/v0"
    typ  "ticket" | "launch" | "end" | "ended"   (a token of one type is never accepted as another)
    iss  who signed: "party", or the game id
    aud  who may accept it: the game id, or "party"
    sid  the game session id
    iat, exp   Unix seconds (both ends share the appliance clock)

Keys: one random 32-byte key per game, provisioned by the appliance (a 0600 file readable by the
party service and by that game's server only). Symmetric on purpose: one appliance, two local
services, no PKI. Consequence (documented, accepted): a game server can mint tickets for its own
sessions; it cannot touch another game's, whose key it does not hold. Built-in LAN Games modules
share one process, so their keys are per process in practice (GAME-INTEGRATION.md §3.1).

Key files: read_key refuses a key that anyone but its owner and this process could read, or that
anyone but its owner could change. A file with no group or other permission bits passes on its
mode. A systemd `LoadCredential=` file passes on its ACL: systemd may leave such a file owned by
root and grant the service user read through a POSIX ACL, and the mode then reads 0440, because
the group bits of a file with an ACL show the ACL's mask, not the group's rights. That file is
accepted only when the ACL itself says the owning group and everyone else get nothing and the one
named user is this process (key_file_problem). A plain group-readable key is still refused.

Clock: both ends read one wall clock, and the appliance has no RTC, so an NTP step after an
offline boot can move it. `unseal` tolerates CLOCK_SKEW seconds of future `iat` and nothing more
(tolerances are not widened silently). A token whose `iat` is further ahead than that means the
clock moved BACKWARD after minting (or the ends disagree): refused as Invalid('clock'), distinct
from Invalid('expired'), so callers can log "clock skew". A FORWARD step past `exp` is
indistinguishable from a genuinely old token and reads 'expired'; the browser's next fetch mints
a fresh ticket. The policy for handling steps is AVR-79, not this file.

Tickets are single-use at the game side (SpentTickets, used by GameSide.admit): the second
presentation of the same ticket string is Invalid('replay'). Reconnects fetch a fresh ticket.

The host claim: a ticket may carry `host`, true or false: whether its participant was the Party
Host when the party minted it. The party is the only authority for its host (succession
included), and a game never keeps a host of its own: for something only the host may do, the
browser fetches a fresh ticket and the game reads the claim from that one ticket
(GameSide.present). A ticket without the field comes from a party that does not say; a verifier
that predates the field ignores it.

Results: `ended` may carry one optional `result` object, the game's structured result for that
session. Its format is versioned on its own (`avrana.game-result/v1`, avrana.party.result,
ADR 0015) and is not part of this protocol's version: this file only carries it, signed, bound to
the session and replay-guarded like the rest of the message. A receiver that does not know the
field ignores it.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time

VERSION = 'avrana.party-session/v0'
PREFIX = 'aps0'
TICKET_TTL = 120            # s: long enough to reach the game's hello; a reconnect fetches anew
MESSAGE_TTL = 30            # s for server-to-server messages
MAX_TOKEN = 8192
CLOCK_SKEW = 5              # s: future-`iat` tolerance; beyond it the refusal is 'clock'
TYPES = ('ticket', 'launch', 'end', 'ended')
ROLES = ('player', 'spectator')
OUTCOMES = ('completed', 'abandoned')
GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')
SID = re.compile(r'^session-[0-9a-f]{32}$')
PID = re.compile(r'^participant-[0-9a-f]{32}$')


class Invalid(Exception):
    """A token or message was refused. `str(e)` names the reason (for logs and tests only)."""


# ---- keys -------------------------------------------------------------------------------------
def new_key():
    return secrets.token_bytes(32)


def write_key(path, key):
    """Create a key file (hex, 0600). Refuses to overwrite: rotating a key is a deliberate act."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as f:
        f.write(key.hex() + '\n')


ACL_XATTR = 'system.posix_acl_access'      # Linux: where a file's POSIX ACL lives
_ACL_OWNER, _ACL_USER, _ACL_GROUP_OBJ, _ACL_GROUP, _ACL_MASK, _ACL_OTHER = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
_READ = 4


def _acl_admits_only(acl, uid):
    """True when this raw POSIX ACL lets the file's owner and user `uid` read it and lets nobody
    else do anything: no write or execute for anyone, nothing for the owning group or for others,
    no named group, and no named user but `uid`. Anything unrecognised is False."""
    if not isinstance(acl, bytes) or len(acl) < 4 or (len(acl) - 4) % 8 \
            or struct.unpack_from('<I', acl)[0] != 2:
        return False
    named = False
    for offset in range(4, len(acl), 8):
        tag, perm, ident = struct.unpack_from('<HHI', acl, offset)
        if tag in (_ACL_OWNER, _ACL_MASK):
            if perm & ~_READ:
                return False
        elif tag == _ACL_USER:
            if ident != uid or perm != _READ:
                return False
            named = True
        elif tag in (_ACL_GROUP_OBJ, _ACL_OTHER):
            if perm:
                return False
        else:                                   # a named group, or a tag this code does not know
            return False
    return named


def key_file_problem(mode, owner, uid, acl=None):
    """Why a key file with these permission bits, this owner uid and this raw ACL (or None) must
    not be used by a process running as `uid`; None when it may. See "Key files" above."""
    if not mode & 0o077:
        return None                             # private by its mode alone
    if mode & 0o077 == 0o040 and owner in (0, uid) and _acl_admits_only(acl, uid):
        return None                             # 0440 where the 040 is only an ACL mask
    return 'key file must not be readable by group or others'


def read_key(path):
    with open(path, encoding='ascii') as f:
        text = f.read().strip()
        if os.name == 'posix':
            st = os.fstat(f.fileno())
            acl = None
            if st.st_mode & 0o077 and hasattr(os, 'getxattr'):
                try:
                    acl = os.getxattr(f.fileno(), ACL_XATTR)
                except OSError:
                    acl = None                  # no ACL, or a filesystem without them
            problem = key_file_problem(st.st_mode & 0o7777, st.st_uid, os.geteuid(), acl)
            if problem:
                raise ValueError(f'{path}: {problem}')
    if not re.fullmatch(r'[0-9a-f]{64}', text):
        raise ValueError(f'{path}: not a 32-byte hex key')
    return bytes.fromhex(text)


# ---- envelope ---------------------------------------------------------------------------------
def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(text):
    if not re.fullmatch(r'[A-Za-z0-9_-]*', text):
        raise Invalid('encoding')
    try:
        return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except (binascii.Error, ValueError):          # e.g. a length of 1 mod 4
        raise Invalid('encoding')


def _mac(key, signed):
    return hmac.new(key, signed.encode('ascii'), hashlib.sha256).digest()


def seal(key, payload):
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    head = f'{PREFIX}.{_b64(body.encode("utf-8"))}'
    return f'{head}.{_b64(_mac(key, head))}'


def unseal(key, token, typ, aud, now=None):
    """Verify signature, version, type, audience and time. Returns the payload or raises Invalid.
    The signature is checked before anything in the payload is trusted."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN:
        raise Invalid('shape')
    parts = token.split('.')
    if len(parts) != 3 or parts[0] != PREFIX:
        raise Invalid('shape')
    head = f'{parts[0]}.{parts[1]}'
    if not hmac.compare_digest(_mac(key, head), _unb64(parts[2])):
        raise Invalid('signature')
    try:
        payload = json.loads(_unb64(parts[1]).decode('utf-8'))
    except ValueError:
        raise Invalid('payload')
    if not isinstance(payload, dict) or payload.get('v') != VERSION:
        raise Invalid('version')
    if payload.get('typ') != typ:
        raise Invalid('type')
    if payload.get('aud') != aud:
        raise Invalid('audience')
    now = time.time() if now is None else now
    iat, exp = payload.get('iat'), payload.get('exp')
    if not (isinstance(iat, int) and isinstance(exp, int)):
        raise Invalid('expired')
    if iat > now + CLOCK_SKEW:
        raise Invalid('clock')
    if exp <= now:
        raise Invalid('expired')
    if not isinstance(payload.get('sid'), str) or not SID.match(payload['sid']):
        raise Invalid('session')
    return payload


def _base(typ, iss, aud, sid, now, ttl):
    now = int(time.time() if now is None else now)
    return {'v': VERSION, 'typ': typ, 'iss': iss, 'aud': aud, 'sid': sid,
            'iat': now, 'exp': now + ttl}


# ---- tickets (party -> browser -> game) --------------------------------------------------------
def mint_ticket(key, game, sid, participant, role, now=None, ttl=TICKET_TTL, host=None):
    """What the party hands one browser for one game session. Carries no device or member id,
    and no name: the game already has display names from the launch roster.

    `host` (True or False) says whether this participant was the Party Host when the ticket was
    minted. It is the only way a game learns who the host is, and it is true only of that moment:
    a game that lets the host do something asks for a fresh ticket with the request
    (GameSide.present) and keeps no host of its own. None leaves the claim out."""
    if role not in ROLES or not PID.match(participant) or not GAME_ID.match(game):
        raise ValueError('bad ticket fields')
    payload = _base('ticket', 'party', game, sid, now, ttl)
    # `jti` makes every ticket distinct even within one second (iat has whole-second resolution),
    # so a single-use ledger (AVR-52) never mistakes a fresh reconnect ticket for a replay. An
    # older verifier ignores the field; the vectors (minted without it) still verify.
    payload.update({'pid': participant, 'role': role, 'jti': secrets.token_hex(8)})
    if host is not None:
        payload['host'] = bool(host)
    return seal(key, payload)


def verify_ticket(key, ticket, game, current_sid, now=None):
    """Game side. Returns {'participant', 'role', 'sid', 'host'} or raises Invalid.
    `current_sid` is the session this game server is running now (None: no party session).
    `host` is the ticket's claim (True or False), or None for a ticket that says nothing about
    the host: a party from before the claim. None is never read as False or as True."""
    p = unseal(key, ticket, 'ticket', game, now)
    if p.get('iss') != 'party':
        raise Invalid('issuer')
    if current_sid is None or p['sid'] != current_sid:
        raise Invalid('session')
    if p.get('role') not in ROLES or not isinstance(p.get('pid'), str) or not PID.match(p['pid']):
        raise Invalid('participant')
    host = p.get('host')
    return {'participant': p['pid'], 'role': p['role'], 'sid': p['sid'],
            'host': host if type(host) is bool else None}


def game_token(key, sid, participant):
    """A stable, secret per-(session, participant) token a game may use internally where it used
    a browser-minted one (LAN Games' `wc-token`). The same participant reconnecting gets the same
    token; a different session gets an unrelated one; nobody can derive it without the key."""
    mac = hmac.new(key, f'game-token|{sid}|{participant}'.encode('ascii'), hashlib.sha256)
    return 'avr-' + mac.hexdigest()[:40]


# ---- server-to-server messages -----------------------------------------------------------------
def launch_message(key, game, sid, roster, now=None):
    """Party -> game: start this session with this roster. Roster entries are exactly
    {participant, name, role}; the game seats the players in its own way."""
    clean = []
    for r in roster:
        if set(r) != {'participant', 'name', 'role'} or r['role'] not in ROLES \
                or not PID.match(r['participant']) or not isinstance(r['name'], str):
            raise ValueError('bad roster entry')
        clean.append({'participant': r['participant'], 'name': r['name'], 'role': r['role']})
    payload = _base('launch', 'party', game, sid, now, MESSAGE_TTL)
    payload.update({'roster': clean, 'nonce': secrets.token_hex(12)})
    return seal(key, payload)


def end_message(key, game, sid, now=None):
    """Party -> game: end this session for everyone and return to a non-running state."""
    payload = _base('end', 'party', game, sid, now, MESSAGE_TTL)
    payload['nonce'] = secrets.token_hex(12)
    return seal(key, payload)


def ended_message(key, game, sid, outcome, now=None, result=None):
    """Game -> party: this session is over. `result`, when given, is the game's structured result
    (a dict in a separately versioned format; see the module docstring). It is carried as is:
    the party decides whether to accept it."""
    if outcome not in OUTCOMES:
        raise ValueError('bad outcome')
    payload = _base('ended', game, 'party', sid, now, MESSAGE_TTL)
    payload.update({'outcome': outcome, 'nonce': secrets.token_hex(12)})
    if result is not None:
        if not isinstance(result, dict):
            raise ValueError('bad result')
        payload['result'] = result
    message = seal(key, payload)
    if len(message) > MAX_TOKEN:
        raise ValueError('result too large')
    return message


class ReplayGuard:
    """Remembers message nonces until they expire, so a captured message is accepted once."""

    def __init__(self):
        self.seen = {}

    def check(self, payload, now=None):
        now = time.time() if now is None else now
        self.seen = {n: exp for n, exp in self.seen.items() if exp > now}
        nonce = payload.get('nonce')
        if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{24}', nonce):
            raise Invalid('nonce')
        if nonce in self.seen:
            raise Invalid('replay')
        self.seen[nonce] = payload['exp']


class SpentTickets:
    """Single-use tickets for any game, with or without GameSide. Remembers the SHA-256 of each
    spent ticket until its `exp` (after which unseal refuses it anyway), pruned on every call.
    Call `spend(ticket, exp)` only AFTER the ticket verified; a second spend of the same
    ticket string raises Invalid('replay')."""

    def __init__(self):
        self.spent = {}

    def spend(self, ticket, exp, now=None):
        now = time.time() if now is None else now
        self.spent = {h: e for h, e in self.spent.items() if e > now}
        digest = hashlib.sha256(ticket.encode('ascii')).hexdigest()
        if digest in self.spent:
            raise Invalid('replay')
        self.spent[digest] = exp

    def clear(self):
        self.spent.clear()


def open_message(key, token, typ, aud, guard, now=None):
    """Receiver side for launch/end/ended: verify, check the issuer matches the direction, and
    refuse replays. Returns the payload."""
    if typ not in ('launch', 'end', 'ended'):
        raise ValueError('not a message type')
    p = unseal(key, token, typ, aud, now)
    expected_iss = 'party' if typ in ('launch', 'end') else None
    if expected_iss and p.get('iss') != expected_iss:
        raise Invalid('issuer')
    if typ == 'ended' and (not isinstance(p.get('iss'), str) or not GAME_ID.match(p['iss'])
                           or p.get('outcome') not in OUTCOMES):
        raise Invalid('ended fields')
    if typ == 'launch':
        roster = p.get('roster')
        if not isinstance(roster, list) or not all(
                isinstance(r, dict) and set(r) == {'participant', 'name', 'role'}
                and r['role'] in ROLES and isinstance(r['participant'], str)
                and PID.match(r['participant']) and isinstance(r['name'], str) for r in roster):
            raise Invalid('roster')
    guard.check(p, now)
    return p


# ---- the game's side, as one small object ------------------------------------------------------
class GameSide:
    """Everything a game server needs, independent of how it runs its rooms. The seam for LAN
    Games (next step): core/net.py calls admit() at the WebSocket hello instead of trusting the
    browser's token; the room's end/abandon calls ended(); the two HTTP routes call on_launch() and
    on_end(). One party session at a time per game, matching one BLUFF table per server.

        side = GameSide(read_key(path), 'bluff')
        roster = side.on_launch(msg)          # reset the room; seat these players your way
        token, role = side.admit(ticket)      # at hello: stable per participant, None if refused
        who = side.present(ticket)            # the same, with the participant and the host claim
        side.on_end(msg)                      # party ended it: back to a non-running state
        report = side.ended('completed')      # then POST it to the party's ended route
        report = side.ended('completed', result=…)   # the same, with a structured result
    """

    def __init__(self, key, game):
        if not GAME_ID.match(game):
            raise ValueError('bad game id')
        self.key, self.game = key, game
        self.sid = None                   # the party session running now, or None
        self.roster = []
        self.guard = ReplayGuard()
        self.spent = SpentTickets()       # tickets already presented (single-use)

    def on_launch(self, message, now=None):
        p = open_message(self.key, message, 'launch', self.game, self.guard, now)
        self.sid, self.roster = p['sid'], p['roster']          # a newer launch replaces the old
        self.spent.clear()                                      # new session: fresh ticket ledger
        return self.roster

    def on_end(self, message, now=None):
        p = open_message(self.key, message, 'end', self.game, self.guard, now)
        if p['sid'] != self.sid:
            raise Invalid('session')
        self.sid, self.roster = None, []
        return p['sid']

    def present(self, ticket, now=None):
        """A valid ticket of the running session, spent: {'token', 'role', 'participant',
        'host'}, else raises Invalid. A ticket is single-use: presenting it again raises
        Invalid('replay'). `host` is the party's word at the moment it minted this ticket (True,
        False, or None from a party that does not say), so a host's action carries a fresh
        ticket of its own and the game keeps no copy of who the host is."""
        t = verify_ticket(self.key, ticket, self.game, self.sid, now)
        exp = unseal(self.key, ticket, 'ticket', self.game, now)['exp']
        self.spent.spend(ticket, exp, now)
        return {'token': game_token(self.key, t['sid'], t['participant']), 'role': t['role'],
                'participant': t['participant'], 'host': t['host']}

    def admit(self, ticket, now=None):
        """(game token, role) for a valid ticket of the running session, else raises Invalid.
        A ticket is single-use: presenting it again raises Invalid('replay')."""
        t = self.present(ticket, now)
        return t['token'], t['role']

    def ended(self, outcome, now=None, result=None):
        """The report for the party; the session stops being admissible here at once."""
        if self.sid is None:
            raise Invalid('session')
        msg = ended_message(self.key, self.game, self.sid, outcome, now, result)
        self.sid, self.roster = None, []
        return msg
