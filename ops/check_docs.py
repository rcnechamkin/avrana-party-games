#!/usr/bin/env python3
"""Documentation integrity for the Games repository: every Markdown file is classified in
docs/manifest.json (class, status), local links resolve, and agent layers stay thin pointers.
Same ideas as Party's tools/repo-check.py, sized for this repository. Stdlib only, no network.

    python ops/check_docs.py
"""
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CLASSES = {'canonical', 'guide', 'reference', 'historical', 'evidence'}
STATUSES = {'current', 'historical', 'mixed'}
REQUIRED = {'AGENTS.md': 'canonical', 'CONTRIBUTING.md': 'canonical', 'README.md': 'canonical',
            'provider/README.md': 'canonical'}
THIN_LAYERS = ('CLAUDE.md', 'CODEX-HANDOFF.md')


def tracked_markdown():
    out = subprocess.run(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                         cwd=ROOT, check=True, capture_output=True).stdout.decode('utf-8')
    return sorted(p for p in out.split('\0') if p.endswith('.md') and (ROOT / p).is_file())


def prose(text):
    lines, fence = [], False
    for line in text.splitlines():
        if re.match(r'^\s{0,3}(```|~~~)', line):
            fence = not fence
            lines.append('')
        elif fence:
            lines.append('')
        else:
            lines.append(re.sub(r'(`+).*?\1', '', line))
    return '\n'.join(lines)


def links(text):
    for m in re.finditer(r'!?\[(?:[^\]\\]|\\.)*\]\(\s*(?:<([^>]+)>|([^\s)]+))', prose(text)):
        yield text.count('\n', 0, m.start()) + 1, m[1] or m[2]


def check(root=ROOT):
    errors = []
    try:
        manifest = json.loads((root / 'docs/manifest.json').read_text(encoding='utf-8'))
        documents = {d['path']: d for d in manifest['documents']}
    except (OSError, ValueError, KeyError, TypeError):
        return ['docs/manifest.json: missing or invalid']
    files = tracked_markdown()
    for path in files:
        if path not in documents:
            errors.append(f'{path}: Markdown document missing from docs/manifest.json')
    for path, entry in documents.items():
        if path not in files:
            errors.append(f'{path}: manifest entry for a file that is not tracked')
            continue
        if entry.get('class') not in CLASSES or entry.get('status') not in STATUSES:
            errors.append(f'{path}: unknown class/status (classes {sorted(CLASSES)}, statuses {sorted(STATUSES)})')
        if path.startswith(('docs/archive/', 'docs/findings/')) and entry.get('status') != 'historical':
            errors.append(f'{path}: archive/findings namespace must stay historical')
        if 'last_verified' in entry and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(entry['last_verified'])):
            errors.append(f'{path}: last_verified must be an ISO date')
        text = (root / path).read_text(encoding='utf-8')
        for number, target in links(text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = ((root / path).parent / unquote(parsed.path)).resolve()
            if not resolved.exists():
                errors.append(f'{path}:{number}: relative link does not resolve ({target})')
    for path, cls in REQUIRED.items():
        if documents.get(path, {}).get('class') != cls or documents.get(path, {}).get('status') != 'current':
            errors.append(f'{path}: required canonical document missing or reclassified')
    for path in THIN_LAYERS:
        if path in documents:
            text = (root / path).read_text(encoding='utf-8')
            if 'AGENTS.md)' not in text or len(text.splitlines()) > 40:
                errors.append(f'{path}: agent layer must be brief and defer to AGENTS.md')
    return errors


def main():
    errors = check()
    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        print(f'Documentation integrity: {len(errors)} error(s)', file=sys.stderr)
        return 1
    print('Documentation integrity: OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
