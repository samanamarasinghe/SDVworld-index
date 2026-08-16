#!/usr/bin/env python3
"""Remove from the shards every field build.py can join, and normalise their formatting.

Curation records judgment; the harvest pools record bibliography. Both currently hold
year, authors, stars and cited, and the two copies have already begun to disagree -- stars
and cited are stale the day after a shard is written, while the pool is refreshed by every
harvest.

Only fields the join reproduces are removed, and the script proves that before writing: it
builds the index with the fields present, builds it again with them absent, and compares.
The test is per record, not per field, so the two cases this found stay put -- the eight
sdv-dev repositories have no row in the third-party code-search pool and would lose their
year, and any entry whose pool record is thinner than the shard's keeps the shard's value.

venue and doi are never stripped. OpenAlex is wrong about the venue of fourteen entries --
it records CTGAN as published at arXiv rather than NeurIPS -- so the curator's value wins
there and has to stay in the shard to do so.

Formatting is normalised in the same pass: three shards are one record per line and twenty
are pretty-printed. Reflow is the point of this commit, not a side effect of an unrelated
edit.

    python curate/strip_joined_fields.py [--dry-run]

Stdlib only.
"""
import argparse
import collections
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRIP = ('year', 'authors', 'stars', 'cited', 'forks', 'commits', 'contributors')


def build_index():
    """Run build.py and return the entries it produces, keyed by id."""
    subprocess.run([sys.executable, 'build.py', '--write'], cwd=ROOT,
                   check=True, capture_output=True)
    return {r['id']: r for r in json.load(open(os.path.join(ROOT, 'data', 'sdv-index.json')))}


def shard_paths():
    return sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    originals = {p: open(p).read() for p in shard_paths()}
    before = build_index()

    candidates = collections.defaultdict(set)
    for path in shard_paths():
        for rec in json.loads(originals[path]):
            for field in STRIP:
                if field in rec:
                    candidates[rec['id']].add(field)

    # Strip everything once to see what the join alone produces.
    for path in shard_paths():
        recs = json.loads(originals[path])
        for rec in recs:
            for field in list(rec):
                if field in STRIP:
                    del rec[field]
        with open(path, 'w') as fh:
            json.dump(recs, fh, indent=1, ensure_ascii=False)
            fh.write('\n')
    joined = build_index()

    def restorable(entry_id, field):
        if entry_id not in before:
            return True          # retired by duplicate_of; never reaches the index anyway
        was, now = before[entry_id].get(field), joined.get(entry_id, {}).get(field)
        if was == now:
            return True
        # Author lists are the exception to strict equality: shards truncate them and the
        # pool carries the full list, so a joined superset is an improvement.
        if field == 'authors' and isinstance(was, list) and isinstance(now, list):
            return set(was) <= set(now)
        return False

    keep = collections.defaultdict(set)
    for entry_id, fields in candidates.items():
        for field in fields:
            if not restorable(entry_id, field):
                keep[entry_id].add(field)

    # Rewrite for real, putting back only what the join could not supply.
    removed, kept = collections.Counter(), collections.Counter()
    for path in shard_paths():
        recs = json.loads(originals[path])
        for rec in recs:
            for field in list(rec):
                if field not in STRIP:
                    continue
                if field in keep.get(rec['id'], ()):
                    kept[field] += 1
                else:
                    del rec[field]
                    removed[field] += 1
        with open(path, 'w') as fh:
            json.dump(recs, fh, indent=1, ensure_ascii=False)
            fh.write('\n')

    after = build_index()
    lost = [f'{i}.{f}' for i in before for f in STRIP
            if before[i].get(f) is not None and after.get(i, {}).get(f) is None]

    print('stripped: ' + (', '.join(f'{n} {f}' for f, n in removed.most_common()) or 'nothing'))
    if kept:
        print('kept, the pool cannot supply them: '
              + ', '.join(f'{n} {f}' for f, n in kept.most_common()))
    print(f'entries before {len(before)}, after {len(after)}')

    if lost or args.dry_run:
        for path, text in originals.items():
            open(path, 'w').write(text)
        subprocess.run([sys.executable, 'build.py', '--write'], cwd=ROOT,
                       check=True, capture_output=True)
        if lost:
            print(f'\nREFUSED: {len(lost)} value(s) would be lost. Shards restored.')
            for entry in lost[:20]:
                print(f'  {entry}')
            return 1
        print('\ndry run: shards restored, nothing changed')
        return 0

    print('\nlossless: every stripped value comes back from the join. Shards rewritten.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
