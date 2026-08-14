#!/usr/bin/env python3
"""Pull every work citing the SDV anchor papers from OpenAlex.

Run locally (no API key needed; the email just gets you the polite pool):
    OPENALEX_EMAIL=you@example.edu python harvest/openalex_citations.py

Writes data/tail/openalex-citations.json. Feed that to the curation pass, which
filters for works that actually *use* the software rather than only cite it.
"""
import json
import os
import time
import urllib.parse
import urllib.request

EMAIL = os.environ.get('OPENALEX_EMAIL', '')
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


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': f'sdvworld-index ({EMAIL})'})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def resolve(anchor):
    data = get(f'https://api.openalex.org/works/{urllib.parse.quote(anchor)}'
               f'?mailto={EMAIL}')
    return data['id'].rsplit('/', 1)[-1]


def citing(work_id):
    cursor, out = '*', []
    while cursor:
        data = get('https://api.openalex.org/works'
                   f'?filter=cites:{work_id}&per-page=200&cursor={cursor}'
                   f'&select={FIELDS}&mailto={EMAIL}')
        out.extend(data['results'])
        cursor = data['meta'].get('next_cursor')
        print(f'    {len(out)}/{data["meta"]["count"]}')
        time.sleep(0.2)
    return out


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
    with open(OUT, 'w') as fh:
        json.dump(list(works.values()), fh, indent=1)
    print(f'{len(works)} distinct citing works -> {OUT}')


if __name__ == '__main__':
    main()
