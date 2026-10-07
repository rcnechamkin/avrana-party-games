#!/usr/bin/env bash
# Fast, browser-free syntax gate for every tracked shell and JavaScript file.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(git ls-files -z 'ops/*.sh')

while IFS= read -r -d '' script; do
  node --check "$script"
done < <(git ls-files -z 'web/*.js' 'games/**/*.js' 'checkers/**/*.js' 'checkers/**/*.mjs' 'tests/*.mjs')

# Generated game art must match its vendored sources (docs/ASSETS.md).
node ops/build_bluff_art.mjs --check

echo "static syntax checks passed"
