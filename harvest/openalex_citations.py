#!/usr/bin/env python3
"""Pull every work citing the SDV anchor papers from OpenAlex.

Run locally with either credential; the key wins when both are set:
    OPENALEX_API_KEY=<key>       python harvest/openalex_citations.py
    OPENALEX_EMAIL=you@example.edu python harvest/openalex_citations.py

Writes data/tail/openalex-citations.json. Feed that to the curation pass, which
filters for works that actually *use* the software rather than only cite it.

The write is a merge, not a replacement. The pool also holds works recovered by
harvest/resolve_tail.py -- ones OpenAlex knows but never returns under `cites:`,
because its reference extraction for the anchors is incomplete. Those records are
invisible to this sweep, so overwriting the file would silently delete them and
strip `source_channel` from the rest. Existing curation and provenance are kept;
the sweep only refreshes bibliographic fields.
"""
import json
import os
import time
import urllib.parse
import urllib.request

API_KEY = os.environ.get('OPENALEX_API_KEY', '')
EMAIL = os.environ.get('OPENALEX_EMAIL', '')

# Fields carried by a pooled record that this sweep does not produce and must
# therefore never clobber: curation verdicts and discovery provenance.
PRESERVE = ('curation', 'source_channel', 'resolved_via')
OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'tail',
                   'openalex-citations.json')

# Anchor works, resolved by DOI or arXiv id at runtime.
ANCHORS = {
    'sdv-dsaa-2016': 'doi:10.1109/DSAA.2016.49',
    'ctgan-neurips-2019': 'doi:10.48550/arXiv.1907.00503',
    'tgan-2018': 'doi:10.48550/arXiv.1811.11264',
    'sequential-2022': 'doi:10.48550/arXiv.2207.14406',
    'vine-copula-2019': 'doi:10.48550/arXiv.1812.01226',
}

FIELDS = ('id,doi,title,publication_year,type,cited_by_count,'
          'primary_location,authorships,concepts,abstract_inverted_index')


def auth():
    """Premium key when set, polite pool otherwise; same precedence everywhere."""
    if API_KEY:
        return f'api_key={urllib.parse.quote(API_KEY)}'
    if EMAIL:
        return f'mailto={urllib.parse.quote(EMAIL)}'
    return ''


def get(url):
    sep = '&' if '?' in url else '?'
    cred = auth()
    if cred:
        url = f'{url}{sep}{cred}'
    req = urllib.request.Request(url, headers={'User-Agent': f'sdvworld-index ({EMAIL})'})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def resolve(anchor):
    data = get(f'https://api.openalex.org/works/{urllib.parse.quote(anchor)}')
    return data['id'].rsplit('/', 1)[-1]


def citing(work_id):
    cursor, out = '*', []
    while cursor:
        data = get('https://api.openalex.org/works'
                   f'?filter=cites:{work_id}&per-page=200&cursor={cursor}'
                   f'&select={FIELDS}')
        out.extend(data['results'])
        cursor = data['meta'].get('next_cursor')
        print(f'    {len(out)}/{data["meta"]["count"]}')
        time.sleep(0.2)
    return out


def merge(swept):
    """Fold the sweep into the existing pool, keeping what the sweep cannot know.

    A record the sweep did not return is kept, not dropped: it was recovered
    through another channel. A record it did return keeps its curation verdict,
    its source_channel and the union of its cites_anchors, and takes the fresh
    bibliographic fields.
    """
    if not os.path.exists(OUT):
        return list(swept.values())
    pool = {rec['id']: rec for rec in json.load(open(OUT))}
    kept = added = refreshed = 0
    for wid, rec in swept.items():
        old = pool.get(wid)
        if old is None:
            pool[wid] = rec
            added += 1
            continue
        anchors = list(dict.fromkeys((old.get('cites_anchors') or [])
                                     + (rec.get('cites_anchors') or [])))
        merged = {**old, **rec, 'cites_anchors': anchors}
        for field in PRESERVE:
            if field in old:
                merged[field] = old[field]
        pool[wid] = merged
        refreshed += 1
    kept = len(pool) - refreshed - added
    print(f'merge: {refreshed} refreshed, {added} new, {kept} kept from other channels')
    return list(pool.values())


def main():
    works = {}
    for name, anchor in ANCHORS.items():
        print(name)
        work_id = resolve(anchor)
        for rec in citing(work_id):
            key = rec['id']
            works.setdefault(key, rec).setdefault('cites_anchors', [])
            if name not in works[key]['cites_anchors']:
                works[key]['cites_anchors'].append(name)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    records = merge(works)
    with open(OUT, 'w') as fh:
        json.dump(records, fh, indent=1)
    print(f'{len(works)} distinct citing works swept; {len(records)} in pool -> {OUT}')


if __name__ == '__main__':
    main()
