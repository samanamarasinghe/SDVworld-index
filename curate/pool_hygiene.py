#!/usr/bin/env python3
"""Remove pool rows the validation suite reports as broken.

The harvest pools are append-only in practice, so nothing ever removed a row that
turned out to be dead. `tests/validate.py --online --scope all` finds them; this takes
them out. Both files are megabytes, so this edits them in place rather than being
hand-patched.

Two kinds so far:

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    gh = json.load(open(GH))
    repos = gh.get('repos', gh) if isinstance(gh, dict) else gh
    keep = [r for r in repos if r.get('repo') not in DEAD_REPOS]
    dropped = len(repos) - len(keep)
    print(f'repositories: {len(repos)} -> {len(keep)} ({dropped} dead)')

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
