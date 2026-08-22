#!/usr/bin/env python3
"""Project the test fixtures with the same code that projects the site.

    python3 scripts/build_fixture.py

Writes, from `tests/semantic/fixture.json`:

    tests/semantic/fixture-projected.json   the 11 hand-authored records plus the
                                            pool rows that survive suppression
    tests/semantic/render-fixture.json      250 generated records for the page-limit
                                            and object-URL cases

Why this exists rather than a few lines of JavaScript in the harness: from Stage 2a
the browser consumes the projection, so a harness that built its own fixture in JS
would be testing the engine against a second, private implementation of the very
transform under test. Suppression, deduplication, the derived affiliation values and
the popularity score all now live in site_projection.py, and the fixtures have to come
through it or the semantic suite stops meaning anything.

`tests/build_tests.py` checks that the committed output matches a fresh run, so an
edit to fixture.json that nobody re-projected is caught rather than silently ignored.
"""
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import site_projection as sp      # noqa: E402

SEMANTIC = ROOT / 'tests/semantic'


def strip_comments(obj):
    """fixture.json documents each record with a `_why`. Those are for a reader, not
    for the projection."""
    if isinstance(obj, dict):
        return {k: strip_comments(v) for k, v in obj.items()
                if not k.startswith('_')}
    if isinstance(obj, list):
        return [strip_comments(v) for v in obj]
    return obj


def bundle(curated, cite_raw, gh_raw):
    """Everything a harness needs to stand a corpus up: projected core records, the
    detail buckets keyed as the site keys them, and the counts the manifest carries."""
    cite, gh = sp.residue_from(curated, cite_raw, gh_raw)
    records = list(curated) + cite + gh
    core = [sp.project(r) for r in records]

    detail = {}
    for rec in records:
        d = {}
        if rec.get('summary'):
            d['summary'] = rec['summary']
        if rec.get('needs'):
            d['needs'] = rec['needs']
        if d:
            detail.setdefault(sp.bucket_of(rec['id']), {})[rec['id']] = d

    return {
        'core': core,
        'detail': detail,
        'postings': sp.build_postings(records),
        'counts': {'curated': len(curated), 'tail': len(cite) + len(gh),
                   'total': len(records), 'citation_pool': len(cite),
                   'repo_pool': len(gh)},
    }


def generated(n=250):
    """The corpus for the rendering cases. Deterministic, and shaped to exercise the
    specific things under test:

      - every record rated 1 or above, so the default floor shows all of them
      - two thirds citable, so an eagerly-built BibTeX Blob would show up
      - odd records in one use case, even records in two, so grouping duplicates and
        the group totals are known exactly: 125 / 125 / 125 over three headings
    """
    out = []
    for i in range(n):
        out.append({
            'id': 'g%04d' % i,
            'title': 'Generated record %04d' % i,
            'kind': 'paper' if i % 3 == 0 else ('code_repo' if i % 3 == 1 else 'preprint'),
            'importance': 1 + (i % 5),
            'year': 2000 + (i % 25),
            'url': 'https://example.org/g%d' % i,
            'summary': 'Summary for generated record %d.' % i,
            'needs': 'verify the source' if i % 7 == 0 else None,
            'authors': ['Author %d' % (i % 13)],
            'use_case': (['privacy_protection'] if i % 2
                         else ['data_sharing', 'ml_training']),
            'sdv_component': [], 'sdv_concept': [], 'industry': [],
            'affiliations': [], 'affiliation_types': [], 'affiliation_countries': [],
            'cited': i,
        })
    return out


def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + '\n')
    return path.stat().st_size


def main():
    raw = strip_comments(json.loads((SEMANTIC / 'fixture.json').read_text()))
    a = bundle(raw['curated'], raw.get('citation_pool_raw'), raw.get('repo_pool_raw'))
    b = bundle(generated(), [], [])

    n1 = write(SEMANTIC / 'fixture-projected.json', a)
    n2 = write(SEMANTIC / 'render-fixture.json', b)
    print(f'fixture-projected.json  {a["counts"]["total"]:>4} records '
          f'({a["counts"]["curated"]} curated + {a["counts"]["tail"]} tail)  {n1:,} B')
    print(f'render-fixture.json     {b["counts"]["total"]:>4} records  {n2:,} B')
    return 0


if __name__ == '__main__':
    sys.exit(main())
