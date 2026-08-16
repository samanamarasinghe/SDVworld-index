#!/usr/bin/env python3
"""Remove pool rows the validation suite reports as broken, and seed the ones missing.

The harvest pools are append-only in practice, so nothing ever removed a row that
turned out to be dead. `tests/validate.py --online --scope all` finds them; this takes
them out. Both files are megabytes, so this edits them in place rather than being
hand-patched.

Two kinds of removal so far:

- A repository that no longer exists. GitHub answers 404 for deleted and for private
  alike, so this only removes what the suite actually probed and found gone.
- A landing page OpenAlex itself recorded with a trailing '>' -- a scrape artifact on
  their side, not ours. The work stays; only the broken pointer is cleared, so the DOI
  or OpenAlex id still resolves it.

    python curate/pool_hygiene.py [--dry-run]

Stdlib only, no network. Re-running is a no-op.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')
CITE = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')

DEAD_REPOS = {'AndrewMichael2020/sample-hospital-network'}

# The pool came from a third-party code search, so it never held sdv-dev itself. That was
# harmless while impact.json carried star counts for those eight and while the shards
# carried them too. Both of those went away -- each removal verified lossless on its own,
# and together they left SDV scoring zero popularity, below every abandoned repository in
# the tail. Seeding them here puts the numbers in the file that owns repository metadata.
# Star counts read from the public repository pages on 2026-08-16.
FIRST_PARTY = [
    {'repo': 'sdv-dev/SDV', 'owner': 'sdv-dev', 'stars': 3546, 'created': '2018-05-04'},
    {'repo': 'sdv-dev/CTGAN', 'owner': 'sdv-dev', 'stars': 1559, 'created': '2019-06-24'},
    {'repo': 'sdv-dev/Copulas', 'owner': 'sdv-dev', 'stars': 650, 'created': '2018-04-04'},
    {'repo': 'sdv-dev/SDGym', 'owner': 'sdv-dev', 'stars': 310, 'created': '2019-04-22'},
    {'repo': 'sdv-dev/TGAN', 'owner': 'sdv-dev', 'stars': 298, 'created': '2018-06-12'},
    {'repo': 'sdv-dev/SDMetrics', 'owner': 'sdv-dev', 'stars': 263, 'created': '2020-06-23'},
    {'repo': 'sdv-dev/RDT', 'owner': 'sdv-dev', 'stars': 135, 'created': '2018-05-04'},
    {'repo': 'sdv-dev/DeepEcho', 'owner': 'sdv-dev', 'stars': 125, 'created': '2020-03-16'},
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    gh = json.load(open(GH))
    repos = gh.get('repos', gh) if isinstance(gh, dict) else gh
    keep = [r for r in repos if r.get('repo') not in DEAD_REPOS]
    dropped = len(repos) - len(keep)
    present = {r.get('repo') for r in keep}
    seeded = [r for r in FIRST_PARTY if r['repo'] not in present]
    keep += seeded
    print(f'repositories: {len(repos)} -> {len(keep)} '
          f'({dropped} dead removed, {len(seeded)} first-party seeded)')

    cite = json.load(open(CITE))
    cleared = 0
    for w in cite:
        loc = w.get('primary_location') or {}
        u = loc.get('landing_page_url')
        if isinstance(u, str) and u.rstrip().endswith('>'):
            loc['landing_page_url'] = None
            cleared += 1
            print(f'  cleared malformed landing page on {w.get("id")}')
    print(f'citation rows with a malformed landing page: {cleared}')

    if args.dry_run:
        print('\ndry run, nothing written')
        return 0
    if isinstance(gh, dict):
        gh['repos'] = keep
        json.dump(gh, open(GH, 'w'), ensure_ascii=False)
    else:
        json.dump(keep, open(GH, 'w'), ensure_ascii=False)
    json.dump(cite, open(CITE, 'w'), ensure_ascii=False)
    print('\nwritten')
    return 0


if __name__ == '__main__':
    sys.exit(main())
