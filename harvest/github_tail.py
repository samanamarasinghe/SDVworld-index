#!/usr/bin/env python3
"""Harvest every GitHub repo whose code matches an SDV usage pattern.

Run locally:  GITHUB_TOKEN=ghp_... python harvest/github_tail.py

GitHub code search caps any single query at 1000 retrievable results, so the
patterns below partition the space. Add more patterns to widen coverage.
Writes data/tail/github-candidates-full.json (merging with what is already there).
"""
import json
import os
import time
import urllib.parse
import urllib.request

TOKEN = os.environ['GITHUB_TOKEN']
OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'tail',
                   'github-candidates-full.json')

PATTERNS = {
    'st': '"from sdv.single_table import"',
    'md': '"from sdv.metadata import"',
    'mt': '"from sdv.multi_table import"',
    'sq': '"from sdv.sequential import"',
    'ev': '"from sdv.evaluation"',
    'ct': '"CTGANSynthesizer"',
    'gc': '"GaussianCopulaSynthesizer"',
    'par': '"PARSynthesizer"',
    'hma': '"HMASynthesizer"',
    'sm': '"import sdmetrics"',
    'rdt': '"from rdt.transformers"',
    'gym': '"import sdgym"',
    'req': 'sdv filename:requirements.txt',
}


def search(query, page):
    url = ('https://api.github.com/search/code?q='
           + urllib.parse.quote(query + ' NOT is:fork')
           + f'&per_page=100&page={page}')
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'sdvworld-index',
    })
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main():
    hits = {}
    if os.path.exists(OUT):
        for row in json.load(open(OUT))['candidates']:
            hits[row['repo']] = set(row['hits'])

    totals = {}
    for code, query in PATTERNS.items():
        page = 1
        while page <= 10:  # 10 * 100 = the 1000-result ceiling
            try:
                data = search(query, page)
            except Exception as exc:  # rate limit or transient failure
                print(f'  {code} page {page}: {exc}; sleeping 60s')
                time.sleep(60)
                continue
            totals[code] = data['total_count']
            items = data.get('items', [])
            if not items:
                break
            for item in items:
                repo = item['repository']['full_name']
                if repo.startswith('sdv-dev/'):
                    continue
                hits.setdefault(repo, set()).add(code)
            print(f'  {code} page {page}: +{len(items)} '
                  f'({len(hits)} unique repos so far)')
            page += 1
            time.sleep(6)  # code search allows 10 requests/minute

    payload = {
        'note': 'Candidate pool from GitHub code search. Not curated entries.',
        'evidence_codes': PATTERNS,
        'query_totals': totals,
        'candidates': [{'repo': r, 'hits': sorted(h))} for r, h in sorted(hits.items())],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(payload, fh, indent=1)
    print(f'{len(hits)} unique repos -> {OUT}')


if __name__ == '__main__':
    main()
