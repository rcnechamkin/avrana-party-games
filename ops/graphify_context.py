#!/usr/bin/env python3
"""Thin launcher for the shared, immutable Party toolkit; no duplicated sync logic."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--toolkit', type=Path)
    args, rest = parser.parse_known_args()
    cfg = json.loads((root / '.graphify.json').read_text(encoding='utf-8'))
    toolkit = args.toolkit or Path(os.environ.get('AVRANA_GRAPHIFY_TOOLKIT', root / '.graphify-context/toolkit'))
    if rest == ['bootstrap']:
        toolkit = root / '.graphify-context/toolkit'
        if toolkit.exists():
            print('Toolkit already exists. Verify its pin; remove this ignored checkout explicitly before replacing it.')
            return 2
        subprocess.run(['git', 'clone', '--no-checkout', 'https://github.com/rcnechamkin/avrana-party.git', str(toolkit)], check=True)
        subprocess.run(['git', '-C', str(toolkit), 'checkout', '--detach', cfg['toolkit_revision']], check=True)
        print('Bootstrapped the pinned shared toolkit, including canonical Party documentation.')
        return 0
    if not (toolkit / 'tools/graphify_context.py').is_file():
        if rest == ['guard']:
            print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'additionalContext': 'Graphify toolkit unavailable; bootstrap it when practical. Consult canonical code/docs and live Linear directly. Graphify is derived only.'}}))
            return 0
        print('Shared toolkit unavailable. Run python ops/graphify_context.py bootstrap, or pass --toolkit PATH for local development.', file=sys.stderr)
        return 2
    if not args.toolkit:  # explicit override is for cross-repo development and is recorded in metadata
        revision = subprocess.run(['git', '-C', str(toolkit), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        if revision != cfg['toolkit_revision']:
            if rest == ['guard']:
                print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                    'additionalContext': 'Graphify toolkit pin differs; context is unavailable. Consult authoritative sources directly.'}}))
                return 0
            print('Shared toolkit revision differs from .graphify.json; refusing unpinned execution.', file=sys.stderr)
            return 2
    sys.argv = [str(toolkit / 'tools/graphify_context.py'), '--repo', str(root), '--toolkit', str(toolkit), *rest]
    runpy.run_path(sys.argv[0], run_name='__main__')
    return 0


if __name__ == '__main__':
    sys.exit(main())
