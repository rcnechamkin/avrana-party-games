"""Deterministic public metadata export; no runtime import or venue secrets.

python ops/export_avrana_catalog.py --out provider/catalog.json
python ops/export_avrana_catalog.py --check provider/catalog.json

Literal registry fields are authoritative. Dynamic metadata fails explicitly.
The source commit records the reviewed input revision; consistency compares the
registry digest and all metadata, so later unrelated commits do not cause drift.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Avrana-native games keep their bare slug as the catalog id (donor titles get `lan-<slug>`):
# the Party session protocol and the client's ticket check compare the Party game id with this
# server's slug, so for a game that joins Party sessions (core/party_session.GAMES) they must match.
FIRST_PARTY = ('bluff', 'expo')

REGISTRY = ROOT / 'games/registry.py'
INTEGRATION = 'avrana.lan-launch/v1'


def export(commit=None):
    raw = REGISTRY.read_bytes()
    tree = ast.parse(raw.decode('utf-8'))
    rows = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [n.id for n in node.targets if isinstance(n, ast.Name)]
        if not set(names) & {'REGISTRY', 'EXTERNAL'}:
            continue
        if not isinstance(node.value, ast.List):
            raise ValueError('registry must contain literal entries')
        for entry in node.value.elts:
            if not isinstance(entry, ast.Dict):
                raise ValueError('registry entry must be literal')
            fields = {}
            for key, value in zip(entry.keys, entry.values):
                name = ast.literal_eval(key)
                if name not in {'session', 'web'}:
                    fields[name] = ast.literal_eval(value)
            if fields.get('hidden'):
                continue
            slug = fields['slug']
            launch = fields.get('url', f'/games/{slug}/')
            if launch != f'/games/{slug}/':
                raise ValueError('only mounted same-origin direct games are supported')
            if not (ROOT / 'games' / slug / 'web/index.html').is_file():
                raise ValueError(f'{slug}: launch page missing')
            rows.append({
                'id': slug if slug in FIRST_PARTY else 'lan-' + slug,
                'slug': slug, 'title': fields['title'], 'icon': fields['icon'],
                'summary': fields['tagline'], 'description': fields['blurb'],
                'min_p': fields['min_p'], 'max_p': fields['max_p'],
                'tv': fields.get('tv', False), 'category': fields['category'],
                'solo': fields.get('solo', False), 'art': fields.get('art'),
                'accent': fields.get('accent'), 'playersLabel': fields['players'],
                'launch': launch,
            })
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate canonical ID')
    return {'schema': 'avrana.lan-catalog/v1', 'source': {
        'commit': commit or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'registrySha256': hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest(),
        'integration': INTEGRATION,
    }, 'games': sorted(rows, key=lambda r: r['id'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out')
    parser.add_argument('--check')
    args = parser.parse_args()
    if args.check:
        current = json.loads(Path(args.check).read_text(encoding='utf-8'))
        if current != export(current['source']['commit']):
            raise SystemExit('provider metadata drift: regenerate and review the snapshot')
        print('provider metadata is consistent')
    else:
        text = json.dumps(export(), ensure_ascii=False, indent=2) + '\n'
        if args.out:
            dest = Path(args.out); dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding='utf-8', newline='\n')
        else:
            print(text, end='')


if __name__ == '__main__':
    main()
