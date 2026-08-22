#!/usr/bin/env python3
"""Verify the committed site projection is current, without regenerating it.

    python3 scripts/verify_site.py

CI runs this instead of rebuilding `data/site/`, and the reason is specific.

`math.log1p` is not required to be correctly rounded and libm differs by platform.
Building this corpus on macOS and on CI's Linux produces 395 records whose popularity
scores differ in the last bit. If CI regenerates and commits, three things follow:

  1. every local build is followed by a CI commit rewriting it, and vice versa;
  2. `data_hash` -- the cache identity -- moves although nothing a reader can see has
     changed, so every client refetches for nothing;
  3. worst, the artifacts actually SERVED become CI's build, which no differential
     ever ran against. The tested build and the shipped build stop being the same
     bytes.

Rounding the score away is not available: v1 inherits the same floating-point artifact
and the Stage 0 corpus recorded the ordering it produces, so quantizing reorders the
page and fails 76 golden states. Fidelity to v1 wins.

So the committed artifacts are authoritative, produced and tested on one machine, and
this checks they are still CURRENT: same records, same ids, same order, same every
field -- with last-bit float noise on `pop` tolerated and nothing else. A structural
difference means someone edited the shards without rebuilding, and CI says so instead
of papering over it.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build                     # noqa: E402
import site_projection as sp     # noqa: E402

SITE = ROOT / 'data/site'


def main():
    if not (SITE / 'core.json').exists():
        print('data/site/core.json is missing; run python3 build.py --write',
              file=sys.stderr)
        return 1

    assembled, _ = build.assemble_records()
    cite, gh = sp.pool_residue(assembled)
    records = list(assembled) + cite + gh
    fresh = [sp.project(r) for r in records]
    committed = json.loads((SITE / 'core.json').read_text())['records']

    if len(fresh) != len(committed):
        print(f'core.json holds {len(committed)} records, the shards now assemble '
              f'{len(fresh)}; run python3 build.py --write', file=sys.stderr)
        return 1

    drift = 0
    for a, b in zip(committed, fresh):
        if a.get('id') != b.get('id'):
            print(f'record order changed: core.json has {a.get("id")!r} where the '
                  f'shards assemble {b.get("id")!r}; run python3 build.py --write',
                  file=sys.stderr)
            return 1
        for key in set(a) | set(b):
            x, y = a.get(key), b.get(key)
            if x == y:
                continue
            if key == 'pop' and isinstance(x, float) and isinstance(y, float) \
                    and abs(x - y) <= sp.POP_TOLERANCE:
                drift += 1          # last-bit libm difference; see the module docstring
                continue
            print(f'{a["id"]!r}: {key} is {x!r} in core.json but {y!r} from the '
                  f'shards; run python3 build.py --write', file=sys.stderr)
            return 1

    # The detail buckets and the postings are pure functions of the same records, with
    # no floating point anywhere, so they must match exactly.
    postings = sp.build_postings(records)
    on_disk = json.loads((SITE / 'summary-postings.json').read_text())
    if postings != on_disk:
        if postings['vocab'] != on_disk['vocab']:
            fresh_v, disk_v = set(postings['vocab']), set(on_disk['vocab'])
            missing = sorted(fresh_v - disk_v)[:1] or sorted(disk_v - fresh_v)[:1]
            print(f'summary-postings.json vocabulary is stale, e.g. {missing}; '
                  f'run python3 build.py --write', file=sys.stderr)
        else:
            print('summary-postings.json postings are stale; run python3 build.py '
                  '--write', file=sys.stderr)
        return 1

    print(f'site projection current: {len(committed):,} records, '
          f'{len(on_disk["vocab"]):,}-token postings'
          + (f' ({drift} popularity value(s) within last-bit float tolerance)'
             if drift else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
