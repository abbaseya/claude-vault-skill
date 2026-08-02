#!/usr/bin/env bash
# Run every check this repo has. CI calls this, so `bash bin/run-tests.sh` locally
# and a green build mean the same thing.
#
# Suites are discovered rather than listed. A new tests/ directory is picked up
# without editing this file or the workflow — the alternative is a suite that
# passes locally, never runs in CI, and reports green anyway.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Nothing personal leaked into a public repo =="
python bin/check-leaks.py

echo
echo "== Scripts import cleanly and the config layer resolves =="
python -c "
import sys; sys.path.insert(0, 'scripts')
import config, detect, digest        # noqa: F401
print('   imports OK')
print('   data home:', config.data_home())
"

echo
echo "== Test suites =="
found=0
while IFS= read -r dir; do
  echo "-- $dir"
  python -m unittest discover -s "$dir" -v
  found=$((found + 1))
done < <(find tests -type d -name 'tests' -o -type d -path 'tests' | sort -u)
echo "   ran $found suite directory(ies)"

echo
echo "All checks passed."
