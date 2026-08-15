#!/usr/bin/env python3
"""Merge harvest shards into data/sdv-index.json and report facet counts.

Curation records judgment: what an entry is, how it uses SDV, how central that use is.
It does not re-record bibliography that the harvest pools already hold. Repository
metadata lives in data/tail/github-repos.json and bibliographic metadata in
data/tail/openalex-citations.json, so year, authors, DOI, venue and the popularity
metrics are joined in here at build time rather than copied into every shard by hand.

The join only ever fills a field a shard left empty. A curator's value always wins.
"""
import collections
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SCHOLARLY = {'paper', 'preprint', 'thesis', 'dataset_benchmark'}


def norm_url(u):
    return re.sub(r'/+$', '', re.sub(r'^https?://(www\.)?', '', str(u or '').lower()))


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', str(t or '').lower()).strip()


def load(path):
    full = os.path.join(ROOT, path)
    return json.load(open(full)) if os.path.exists(full) else None


def missing(rec, field):
    return rec.get(field) in (None, '', [], {})


def build_lookups():
    """URL/title lookups into the two harvest pools. Absent pools are not an error."""
    gh = {}
    raw = load('data/tail/github-repos.json')
    for r in (raw or {}).get('repos', []) if isinstance(raw, dict) else (raw or []):
        gh[norm_url('https://github.com/' + r['repo'])] = r

    oa_url, oa_title = {}, {}
    for r in load('data/tail/openalex-citations.json') or []:
        loc = r.get('primary_location') or {}
        for u in (loc.get('landing_page_url'), r.get('doi'), r.get('id'), loc.get('pdf_url')):
            if u:
                oa_url.setdefault(norm_url(u), r)
        t = norm_title(r.get('title'))
        if t:
            oa_title.setdefault(t, r)
    return gh, oa_url, oa_title


def enrich(records):
    gh, oa_url, oa_title = build_lookups()
    filled = collections.Counter()
    unjoined = collections.Counter()

    def put(rec, field, value):
        if value in (None, '', [], {}) or not missing(rec, field):
            return
        rec[field] = value
        filled[field] += 1

    for rec in records:
        kind = rec.get('kind')
        # Route on where the artifact lives, not on how it was classified: a dataset or
        # benchmark hosted on GitHub is a repository as far as metadata is concerned.
        g = gh.get(norm_url(rec.get('url')))

        if kind == 'code_repo' or g:
            if not g:
                unjoined['code_repo'] += 1
                continue
            created = str(g.get('created') or '')[:4]
            put(rec, 'year', int(created) if created.isdigit() else None)
            put(rec, 'authors', [a for a in [g.get('owner')] + (g.get('top_contributors') or []) if a])
            for field in ('stars', 'forks', 'commits', 'contributors'):
                put(rec, field, g.get(field))

        elif kind in SCHOLARLY:
            o = oa_url.get(norm_url(rec.get('url'))) or oa_title.get(norm_title(rec.get('title')))
            if not o:
                unjoined['scholarly'] += 1
                continue
            put(rec, 'doi', o.get('doi'))
            put(rec, 'year', o.get('publication_year'))
            put(rec, 'venue', ((o.get('primary_location') or {}).get('source') or {}).get('display_name'))
            put(rec, 'cited', o.get('cited_by_count'))
            put(rec, 'authors', [(a.get('author') or {}).get('display_name')
                                 for a in (o.get('authorships') or [])
                                 if (a.get('author') or {}).get('display_name')])

    return filled, unjoined


def main():
    seen, out, dupes, retired = set(), [], 0, 0
    for path in sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json'))):
        for rec in json.load(open(path)):
            # A record carrying duplicate_of has been retired in favour of another
            # entry. It stays in its shard as an audit trail; it is not an index entry.
            if rec.get('duplicate_of'):
                retired += 1
                continue
            key = rec['url'].rstrip('/')
            if key in seen:
                dupes += 1
                continue
            seen.add(key)
            out.append(rec)

    ids = collections.Counter(rec['id'] for rec in out)
    collisions = sorted(i for i, n in ids.items() if n > 1)

    filled, unjoined = enrich(out)

    impact = load('data/impact.json')
    if impact:
        for rec in out:
            if rec['id'] in impact:
                rec.update(impact[rec['id']])  # hand-checked figures win over the join

    out.sort(key=lambda r: (r['kind'], -(r.get('year') or 0), r['title']))
    dest = os.path.join(ROOT, 'data', 'sdv-index.json')
    with open(dest, 'w') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    print(f'{len(out)} entries, {dupes} duplicate urls dropped, '
          f'{retired} retired by duplicate_of -> {dest}')
    if collisions:
        print(f'WARNING: {len(collisions)} duplicate id(s) across shards: {", ".join(collisions)}')
    if filled:
        print('joined from harvest pools: '
              + ', '.join(f'{n} {f}' for f, n in filled.most_common()))
    if unjoined:
        print('not joined: ' + ', '.join(f'{n} {k}' for k, n in unjoined.most_common()))

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
