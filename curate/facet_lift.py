#!/usr/bin/env python3
"""Lift bibliographic facets out of the raw pools into a curation-ready sidecar.

    python curate/facet_lift.py --check     # report coverage, write nothing
    python curate/facet_lift.py             # write data/tail/facet-lift.json

No judgment happens here. Every field is copied from a pooled record that already
carries it: OpenAlex authorships/year/venue/institutions for the citation tail, and
the GitHub metrics block for the repo tail. Nothing is inferred, nothing is fetched.

The output is keyed by openalex id (W...) and by "owner/repo", and is consumed at
promotion time so that a curating agent never has to retype an author list. Facets
that require reading the source -- summary, sdv_concept, use_case, industry,
integration, importance -- are NOT produced here.

The output is generated data, like data/sdv-index.json: regenerate it, never hand-edit
it, and do not treat a missing copy as data loss.
"""
import argparse
import collections
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKS = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
REPOS = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')
DEST = os.path.join(ROOT, 'data', 'tail', 'facet-lift.json')


def lift_works(path):
    out, missing = {}, collections.Counter()
    for rec in json.load(open(path)):
        oid = rec['id'].rsplit('/', 1)[-1]
        authorships = rec.get('authorships') or []
        location = rec.get('primary_location') or {}
        source = (location.get('source') or {}).get('display_name') or ''

        authors = [a['author']['display_name'] for a in authorships if a.get('author')]
        institutions = sorted({
            inst['display_name']
            for a in authorships for inst in (a.get('institutions') or [])
            if inst.get('display_name')
        })
        countries = sorted({
            inst['country_code']
            for a in authorships for inst in (a.get('institutions') or [])
            if inst.get('country_code')
        })

        entry = {}
        if authors:
            entry['authors'] = authors
        else:
            missing['authors'] += 1
        if rec.get('publication_year'):
            entry['year'] = int(rec['publication_year'])
        else:
            missing['year'] += 1
        if source:
            entry['venue'] = source
        else:
            missing['venue'] += 1
        if institutions:
            entry['affiliations'] = institutions
        if countries:
            entry['countries'] = countries
        if rec.get('doi'):
            entry['doi'] = rec['doi']
        out[oid] = entry
    return out, missing


def lift_repos(path):
    out, missing = {}, collections.Counter()
    for rec in json.load(open(path))['repos']:
        entry = {}
        # GitHub logins, not real names -- kept under a distinct key so nothing
        # downstream mistakes them for an author list. Real names for a repository
        # come from its linked paper, if it has one.
        if rec.get('top_contributors'):
            entry['contributors'] = rec['top_contributors']
        else:
            missing['contributors'] += 1
        # A repository has no publication year; creation year is the closest honest
        # analogue and is labelled as such rather than written into `year`.
        if rec.get('created'):
            entry['created'] = rec['created']
        for field in ('language', 'license', 'topics', 'homepage', 'owner_type'):
            if rec.get(field):
                entry[field] = rec[field]
        out[rec['repo']] = entry
    return out, missing


def report(name, table, missing):
    total = len(table)
    print(f'\n{name}: {total} records')
    counter = collections.Counter(k for entry in table.values() for k in entry)
    for field, count in counter.most_common():
        print(f'  {count:>5} / {total}  {field}')
    for field, count in missing.most_common():
        print(f'  {count:>5} MISSING  {field}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='report only, write nothing')
    args = parser.parse_args()

    works, works_missing = lift_works(WORKS)
    repos, repos_missing = lift_repos(REPOS)
    report('openalex', works, works_missing)
    report('github', repos, repos_missing)

    if args.check:
        print('\n--check: nothing written')
        return

    payload = {
        'note': ('Bibliographic facets lifted mechanically from the raw pools. No '
                 'judgment, no fetching. Consumed at promotion time; not index entries.'),
        'works': works,
        'repos': repos,
    }
    with open(DEST, 'w') as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    print(f'\n{len(works)} works + {len(repos)} repos -> {DEST}')


if __name__ == '__main__':
    main()
