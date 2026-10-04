"""deploy/avranaparty-games.service and its drop-in: the games service as its own user
(avrana-party ADR 0016 phase 1, AVR-256). Text checks only: nothing here starts a unit, and the
unit has never run on any host (see its header for what it was reconstructed from)."""
import re
from pathlib import Path

from core import party_session

ROOT = Path(__file__).resolve().parent.parent
UNIT = (ROOT / 'deploy/avranaparty-games.service').read_text(encoding='utf-8')
DROP_IN = (ROOT / 'deploy/avrana-party-session.conf').read_text(encoding='utf-8')
KEY_DIR = '/etc/avrana-party/game-keys'


def directives(text):
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if sep and not line.lstrip().startswith('#'):
            out.setdefault(key.strip(), []).append(value.strip())
    return out


def test_runs_as_its_own_user_from_root_owned_code():
    d = directives(UNIT)
    assert (d['User'], d['Group']) == (['avrana-lan-games'], ['avrana-lan-games'])
    assert d['WorkingDirectory'] == ['/opt/avrana-party-games/current']
    assert d['ExecStart'] == ['/opt/avrana-party-games/venv/bin/python /opt/avrana-party-games/current/server.py']
    assert (d['NoNewPrivileges'], d['ProtectSystem'], d['ProtectHome']) == (['yes'], ['strict'], ['yes'])
    for values in list(d.values()) + list(directives(DROP_IN).values()):
        for value in values:
            assert '/home/' not in value, value


def test_data_is_the_services_own_state_directory_bound_over_the_release():
    d = directives(UNIT)
    assert (d['StateDirectory'], d['StateDirectoryMode']) == (['avrana-lan-games'], ['0700'])
    assert d['BindPaths'] == ['/var/lib/avrana-lan-games:/opt/avrana-party-games/current/data']
    # the release is built from tracked files only, so the mount point has to be one of them
    assert (ROOT / 'data/.gitkeep').is_file()
    from core import avatars, chatmedia
    assert avatars.AVATAR_DIR.parent == chatmedia.CHAT_DIR.parent == ROOT / 'data'


def test_it_is_handed_exactly_the_keys_of_the_party_games_it_hosts():
    d = directives(DROP_IN)
    assert sorted(d['LoadCredential']) == sorted(f'{g}.key:{KEY_DIR}/{g}.key' for g in party_session.GAMES)
    env = dict(v.split('=', 1) for v in d['Environment'])
    assert env[party_session.KEYS_ENV] == '%d'              # the credentials directory, never the store
    assert KEY_DIR not in ' '.join(d['Environment'])
    assert not re.search(r'(?im)^(Set|Import)Credential|^LoadCredentialEncrypted', UNIT + DROP_IN)


def test_the_listener_is_loopback_and_no_drop_in_widens_it():
    """AVR-272: port 8096 is reached through nginx only, never from the LAN."""
    env = [v for v in directives(UNIT)['Environment'] if v.startswith('LANGAMES_HOST=')]
    assert env == ['LANGAMES_HOST=127.0.0.1']
    for path in sorted((ROOT / 'deploy').glob('*.conf')):
        for value in directives(path.read_text(encoding='utf-8')).get('Environment', []):
            assert 'LANGAMES_HOST' not in value, path.name


def test_the_kernel_allows_this_unit_loopback_traffic_only():
    """AVR-272, owner decision 2026-10-04. Text only: the unit has never run."""
    d = directives(UNIT)
    assert (d['IPAddressDeny'], d['IPAddressAllow']) == (['any'], ['localhost'])
    for path in sorted((ROOT / 'deploy').glob('*.conf')):
        assert not {'IPAddressAllow', 'IPAddressDeny'} & set(directives(path.read_text(encoding='utf-8'))), path.name
    # The server's only outbound connection is to Party Core, and that origin must be loopback
    # (core/party_session.py refuses any other), so the filter takes nothing away from it.
    assert party_session.LOOPBACK == ('127.0.0.1', '::1')
    callers = [p.relative_to(ROOT).as_posix() for p in [ROOT / 'server.py', *sorted((ROOT / 'core').glob('*.py'))]
               if re.search(r'urlopen|http\.client|create_connection', p.read_text(encoding='utf-8'))]
    assert callers == ['core/party_session.py']
    env = dict(v.split('=', 1) for v in directives(DROP_IN)['Environment'])
    assert env.get(party_session.PARTY_URL_ENV, 'http://127.0.0.1:8191').startswith('http://127.0.0.1:')


def test_the_header_says_what_was_not_confirmed():
    assert 'RECONSTRUCTED, NOT COPIED' in UNIT
    assert UNIT.count('# not confirmed from the records') == 3
