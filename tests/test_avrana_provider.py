"""Public deterministic export, actual route ownership, integration advertisement."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import server
from ops.export_avrana_catalog import export, ROOT


def test_export_is_deterministic_and_snapshot_has_no_drift():
    snapshot = json.loads((ROOT / 'provider/catalog.json').read_text(encoding='utf-8'))
    assert snapshot == export(snapshot['source']['commit'])
    assert export('0' * 40) == export('0' * 40)
    assert len(snapshot['games']) == 31
    assert len({g['id'] for g in snapshot['games']}) == 31
    assert next(g for g in snapshot['games'] if g['id'] == 'expo')['launch'] == '/games/expo/'
    assert {'lan-bluff', 'lan-expo'}.isdisjoint({g['id'] for g in snapshot['games']})


def test_every_exported_title_has_a_real_direct_route_and_explicit_context():
    mounts = {route.path for route in server.app.routes}
    for row in export()['games']:
        assert row['launch'][:-1] in mounts
        page = (ROOT / 'games' / row['slug'] / 'web/index.html').read_text(encoding='utf-8')
        assert '/shared/avrana-integration.js' in page
        assert row['launch'] != '/'
    response = asyncio.run(server.api_games())
    assert json.loads(response.body)['avranaIntegration'] == 'avrana.lan-launch/v1'


def test_export_check_detects_provider_metadata_drift(tmp_path):
    snapshot = export('0' * 40)
    snapshot['games'][0]['title'] = 'incorrect title'
    path = tmp_path / 'stale.json'
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    result = subprocess.run([sys.executable, str(ROOT / 'ops/export_avrana_catalog.py'), '--check', str(path)], capture_output=True)
    assert result.returncode != 0
    assert b'drift' in result.stderr
