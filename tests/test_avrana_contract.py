"""provider/avrana-contract.json: what this server requires from Party, proven against this code.

The cross-repository comparison (both declarations, the vendored protocol, the catalog snapshot)
is rcnechamkin/avrana-party's tools/contract_check.py; it runs here too when a Party checkout is
available ($AVRANA_PARTY_REPO or ../avrana-party). In CI that checkout is required
(AVRANA_REQUIRE_PARTY=1), so the comparison can never skip silently there.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from core import party_protocol, party_session
from ops.export_avrana_catalog import INTEGRATION

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = json.loads((ROOT / 'provider/avrana-contract.json').read_text(encoding='utf-8'))
PARTY_REPO = Path(os.environ.get('AVRANA_PARTY_REPO') or ROOT.parent / 'avrana-party')


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def test_declaration_names_the_contract_and_protocol_this_code_implements():
    sp = DECLARATION['session_protocol']
    assert DECLARATION['requires'].startswith('avrana.party-games/v')
    assert sp['version'] == party_protocol.VERSION
    assert digest(sp['vendored']) == sp['vendored_sha256']
    assert digest(sp['vectors']) == sp['vectors_sha256']
    assert DECLARATION['routes']['party_ended'] == party_session.ENDED_PATH
    assert DECLARATION['environment']['keys_dir'] == party_session.KEYS_ENV
    assert DECLARATION['launch']['integration'] == INTEGRATION
    assert list(DECLARATION['party_side_games']) == list(party_session.GAMES)


def test_server_mounts_the_declared_game_routes():
    server = (ROOT / 'server.py').read_text(encoding='utf-8')
    for key in ('game_launch', 'game_end'):
        assert f'"/games/{{slug}}{DECLARATION["routes"][key]}"' in server, key


def test_drop_in_sets_the_declared_environment():
    conf = (ROOT / 'deploy/avrana-party-session.conf').read_text(encoding='utf-8')
    for name in DECLARATION['environment'].values():
        assert re.search(rf'^Environment={name}=', conf, re.M), name


def test_cross_repository_contract_check():
    checker = PARTY_REPO / 'tools/contract_check.py'
    if not checker.exists():
        if os.environ.get('AVRANA_REQUIRE_PARTY') == '1':
            pytest.fail(f'no Party checkout at {PARTY_REPO} (AVRANA_REQUIRE_PARTY=1); cannot verify the contract')
        pytest.skip('no avrana-party checkout (set AVRANA_PARTY_REPO); cross-repository contract NOT verified')
    result = subprocess.run([sys.executable, str(checker), '--party', str(PARTY_REPO), '--games', str(ROOT)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'compatible' in result.stdout
