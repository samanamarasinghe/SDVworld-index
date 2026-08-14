#!/usr/bin/env python3
"""Merge harvest shards into data/sdv-index.json and report facet counts."""
import collections
import glob
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    seen, out, dupes = set(), [], 0
    for path in sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json'))):
        for rec in json.load(open(path)):
            key = rec['url'].rstrip('/')
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            out.append(rec)

    out.sort(key=lambda r: (r['kind'], -(r.get('year') or 0), r['title']))
    dest = os.path.join(ROOT, 'data', 'sdv-index.json')
    with open(dest, 'w') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    print(f'{len(out)} entries, {dupes} duplicates dropped -> {dest}')
    for facet in ('kind', 'use_case', 'industry', 'sdv_component'):
        counter = collections.Counter()
        for rec in out:
            val = rec.get(facet)
            counter.update([val] if isinstance(val, str) else (val or []))
        print(f'\n{facet}:')
        for name, count in counter.most_common():
            print(f'  {count:>4}  {name}')


if __name__ == '__main__':
    main()
