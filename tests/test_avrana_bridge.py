"""The Party bridge on the game origin (avrana-party ADR 0013, AVR-226): what this server tells its
pages, and the vendored shim.

A page learns the Party's origin from this server's configuration and from nowhere else. With no
(or a malformed) AVRANA_PARTY_ORIGIN the answer is null and every page behaves as it does today,
on the Party's own origin. The shim (web/avrana-party-bridge.js) is avrana-party's
web/party/bridge/shim.js, vendored unchanged like the session protocol.
"""
import asyncio
import hashlib
import json
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = json.loads((ROOT / 'provider/avrana-contract.json').read_text(encoding='utf-8'))['bridge']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def answer():
    response = asyncio.run(server.api_avrana())
    assert response.headers['cache-control'] == 'no-store'
    return json.loads(response.body)


def test_with_no_party_origin_pages_are_told_none(monkeypatch):
    monkeypatch.delenv(server.PARTY_ORIGIN_ENV, raising=False)
    assert answer() == {'integration': 'avrana.lan-launch/v1', 'bridge': BRIDGE['protocol'], 'partyOrigin': None}


@pytest.mark.parametrize('origin', ('https://party.avrana.net', 'http://party.avrana.test:8183'))
def test_a_configured_party_origin_is_told_to_pages(monkeypatch, origin):
    monkeypatch.setenv(server.PARTY_ORIGIN_ENV, origin)
    assert answer()['partyOrigin'] == origin


@pytest.mark.parametrize('value', (
    '', 'party.avrana.net', 'https://party.avrana.net/', 'https://party.avrana.net/party/',
    'https://party.avrana.net?x=1', 'https://user@party.avrana.net', 'javascript:alert(1)',
    'ftp://party.avrana.net', 'https://party.avrana.net https://evil.example', '*',
    'https://party.avrana.net\n',
))
def test_anything_that_is_not_an_origin_is_ignored(monkeypatch, value):
    monkeypatch.setenv(server.PARTY_ORIGIN_ENV, value)
    assert answer()['partyOrigin'] is None


def test_the_declaration_names_what_this_server_does():
    assert BRIDGE['protocol'] == server.BRIDGE
    assert BRIDGE['party_origin_env'] == server.PARTY_ORIGIN_ENV
    assert any(getattr(route, 'path', None) == BRIDGE['advertised_at'] for route in server.app.routes)
    assert f"PROTOCOL = '{BRIDGE['protocol']}'" in (ROOT / BRIDGE['vendored']).read_text(encoding='utf-8')


def test_the_vendored_shim_and_vectors_are_the_declared_ones():
    assert digest(ROOT / BRIDGE['vendored']) == BRIDGE['vendored_sha256']
    assert digest(ROOT / BRIDGE['vectors']) == BRIDGE['vectors_sha256']
    assert json.loads((ROOT / BRIDGE['vectors']).read_text(encoding='utf-8'))['protocol'] == BRIDGE['protocol']


# That the vendored shim and vectors are Party's own is checked where it can fail: the cross-repo
# job compares the two declarations' digests (avrana-party tools/contract_check.py). A sibling
# checkout on another branch says nothing either way, so there is no local comparison here.


def test_the_drop_in_documents_the_setting_and_does_not_set_it():
    conf = (ROOT / 'deploy/avrana-party-session.conf').read_text(encoding='utf-8')
    assert server.PARTY_ORIGIN_ENV in conf
    assert not [line for line in conf.splitlines()
                if server.PARTY_ORIGIN_ENV in line and not line.lstrip().startswith('#')]


def test_the_page_takes_the_party_origin_from_this_server_only():
    page = (ROOT / 'web/avrana-integration.js').read_text(encoding='utf-8')
    assert "fetch('/api/avrana'" in page
    assert page.count('URLSearchParams') == 1          # the launch marker, nothing else
    assert 'location.hash' not in page and 'postMessage' not in page
