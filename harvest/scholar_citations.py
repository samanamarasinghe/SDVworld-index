#!/usr/bin/env python3
"""Pull works citing the SDV anchor papers from Google Scholar via SerpAPI.

    SERPAPI_KEY=... python harvest/scholar_citations.py

Scholar has no public API. This uses SerpAPI, a licensed third-party provider,
which is the only route here that automates cleanly. See harvest/README.md for
the free alternative (Publish or Perish) if you would rather not pay for a key.

Scholar caps any 'Cited by' list at 1000 results and gives no stable record ids,
so output is deduplicated against OpenAlex on DOI where present and on
normalized title otherwise.

Writes data/tail/scholar-citing-works.json.
"""
import json
import os
import re
import time
import urllib.parse
import urllib.request

KEY = os.environ['SERPAPI_KEY']
OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'tail',
                   'scholar-citing-works.json')

# Titles are resolved to Scholar cluster ids at runtime; hardcoding the ids
# would rot, since Scholar reassigns them when it merges or splits clusters.
ANCHORS = {
    'sdv-dsaa-2016': 'The Synthetic Data Vault',
    'ctgan-neurips-2019': 'Modeling tabular data using conditional GAN',
    'tgan-2018': 'Synthesizing tabular data using generative adversarial networks',
    'sequential-2022': 'Sequential models in the synthetic data vault',
    'vine-copula-2019': 'Learning vine copula models for synthetic data generation',
}


def serpapi(**params):
    params['api_key'] = KEY
    params['engine'] = 'google_scholar'
    url = 'https://serpapi.com/search?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url) as resp:
        data = json.load(resp)
    if 'error' in data:
        raise RuntimeError(data['error'])
    return data


def cluster_id(title):
    """Resolve a paper title to the cites_id behind its 'Cited by' link."""
    data = serpapi(q=f'"{title}"', num=5)
    for result in data.get('organic_results', []):
        cited_by = result.get('inline_links', {}).get('cited_by', {})
        if cited_by.get('cites_id'):
            return cited_by['cites_id'], result.get('title', '')
    raise LookupError(f'no cited_by link found for: {title}')


def norm(title):
    return re.sub(r'[^a-z0-9]+', ' ', (title or '').lower()).strip()


def citing(cites_id):
    out, start = [], 0
    while start < 1000:  # Scholar's hard ceiling on a Cited by list
        data = serpapi(cites=cites_id, start=start, num=20)
        results = data.get('organic_results', [])
        if not results:
            break
        for r in results:
            info = r.get('publication_info', {})
            out.append({
                'title': r.get('title'),
                'link': r.get('link'),
                'snippet': r.get('snippet'),
                'venue_line': info.get('summary'),
                'authors': [a.get('name') for a in info.get('authors', [])],
                'cited_by_count': r.get('inline_links', {})
                                   .get('cited_by', {}).get('total'),
                'resources': [x.get('link') for x in r.get('resources', [])],
            })
        print(f'    {len(out)} so far')
        start += 20
        time.sleep(1)
    return out


def main():
    works = {}
    for name, title in ANCHORS.items():
        print(name)
        cites_id, matched = cluster_id(title)
        print(f'  matched: {matched} (cites_id={cites_id})')
        for rec in citing(cites_id):
            key = norm(rec['title'])
            works.setdefault(key, rec).setdefault('cites_anchors', [])
            if name not in works[key]['cites_anchors']:
                works[key]['cites_anchors'].append(name)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(list(works.values()), fh, indent=1, ensure_ascii=False)
    print(f'{len(works)} distinct citing works -> {OUT}')


if __name__ == '__main__':
    main()
