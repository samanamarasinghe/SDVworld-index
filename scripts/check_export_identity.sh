#!/usr/bin/env bash
# The public export must rebuild byte-identically from unchanged shards.
#
# CLAUDE.md rule 5 requires this before every push. data/sdv-index.json is read by
# downstream consumers, and none of the performance work is allowed to perturb it --
# not its ordering, not its key order, not its whitespace.
set -euo pipefail
cd "$(dirname "$0")/.."

before=$(shasum -a 256 data/sdv-index.json | cut -d' ' -f1)
python3 build.py --write >/dev/null
after=$(shasum -a 256 data/sdv-index.json | cut -d' ' -f1)

if [ "$before" = "$after" ]; then
  echo "legacy export byte-identical (${before:0:16})"
else
  echo "LEGACY EXPORT CHANGED: was ${before:0:16}, now ${after:0:16}" >&2
  exit 1
fi
