#!/usr/bin/env python3
"""Harvest every GitHub repo whose code matches an SDV usage pattern.

Run locally (macOS Homebrew Python needs a CA bundle; note python3):
    GITHUB_TOKEN=<token> SSL_CERT_FILE="$(python3 -m certifi)" python3 harvest/github_tail.py

GitHub code search caps any single query at 1000 retrievable results. Any pattern
over that cap is split automatically by file size until each slice fits.
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

MAX_SIZE = 400000  # GitHub code search does not index files larger than ~384 KB


def search(query, page=1):
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


def api(query, page=1):
    """search() with retry on rate limits, spacing every request 6s apart."""
    while True:
        try:
            data = search(query, page)
            time.sleep(6)  # code search allows 10 requests/minute
            return data
        except Exception as exc:  # 403 rate limit or transient failure
            print(f'    {exc}; sleeping 60s')
            time.sleep(60)


def collect(query, code, hits):
    for page in range(1, 11):  # 10 * 100 = the 1000 retrievable ceiling
        items = api(query, page).get('items', [])
        if not items:
            break
        for item in items:
            repo = item['repository']['full_name']
            if repo.startswith('sdv-dev/'):
                continue
            hits.setdefault(repo, set()).add(code)
        print(f'    {code} [{query}] page {page}: +{len(items)} '
              f'({len(hits)} unique so far)')


def harvest(code, base, hits):
    """Collect a pattern, recursively bisecting on file size when a query
    exceeds the 1000 results the code-search API will return."""
    total = api(base)['total_count']
    if total <= 1000:
        print(f'  {code}: {total}')
        collect(base, code, hits)
        return total
    print(f'  {code}: {total} -> partitioning by size')

    def bisect(lo, hi):
        sub = api(f'{base} size:{lo}..{hi}')['total_count']
        if sub == 0:
            return
        if sub <= 1000 or lo >= hi:
            collect(f'{base} size:{lo}..{hi}', code, hits)
        else:
            mid = (lo + hi) // 2
            bisect(lo, mid)
            bisect(mid + 1, hi)

    bisect(0, MAX_SIZE)
    return total


def main():
    hits = {}
    if os.path.exists(OUT):
        for row in json.load(open(OUT))['candidates']:
            hits[row['repo']] = set(row['hits'])

    totals = {code: harvest(code, query, hits) for code, query in PATTERNS.items()}

    payload = {
        'note': 'Candidate pool from GitHub code search. Not curated entries. '
                'Patterns over the 1000-result cap are split by file size.',
        'evidence_codes': PATTERNS,
        'query_totals': totals,
        'candidates': [{'repo': r, 'hits': sorted(h)} for r, h in sorted(hits.items())],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as fh:
        json.dump(payload, fh, indent=1)
    print(f'{len(hits)} unique repos -> {OUT}')


if __name__ == '__main__':
    main()
