#!/usr/bin/env python3
"""Generate data/impact.json: an impact signal per curated record, joined into
data/sdv-index.json by build.py.

  - papers / preprints / theses -> citation count (OpenAlex, by DOI or title)
  - code repos                  -> stars / forks / contributors / commits
                                   (looked up in data/tail/github-repos.json)

Kept out of the shards on purpose: citations and stars drift, shards are
append-only and hand-curated. Regenerable; stdlib only. Network: api.openalex.org.

    OPENALEX_EMAIL=you@example.edu python curate/build_impact.py
"""
import glob
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARDS = sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json')))
REPOS = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')
OUT = os.path.join(ROOT, 'data', 'impact.json')
EMAIL = os.environ.get('OPENALEX_EMAIL', '')
CITABLE = {'paper', 'preprint'}  # theses are poorly DOI-indexed; title search mismatches them


def norm_words(t):
    return set(re.sub(r'[^a-z0-9 ]', ' ', (t or '').lower()).split())


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': f'sdvworld-index ({EMAIL})'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def cited_by(rec):
    doi = (rec.get('doi') or '').replace('https://doi.org/', '')
    try:
        if doi:
            return get(f'https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}'
                       '?select=cited_by_count')['cited_by_count']
        title = rec.get('title')
        if title:
            d = get('https://api.openalex.org/works?search=' + urllib.parse.quote(title)
                    + '&per-page=1&select=cited_by_count,title')
            res = d.get('results') or []
            if res:
                want = norm_words(title)
                got = norm_words(res[0].get('title'))
                if want and len(want & got) / len(want) >= 0.7:  # guard against wrong matches
                    return res[0]['cited_by_count']
                print(f'    ~ {rec["id"]}: title mismatch -> {res[0].get("title", "")[:45]}')
    except Exception as exc:
        print(f'    ! {rec["id"]}: {exc}')
    return None


def main():
    repos = {r['repo'].lower(): r for r in json.load(open(REPOS)).get('repos', [])}
    impact = {}
    for sh in SHARDS:
        for rec in json.load(open(sh)):
            rid = rec['id']
            if rec.get('kind') in CITABLE:
                c = cited_by(rec)
                if c is not None:
                    impact[rid] = {'cited': c}
                    print(f'  cited {c:>6}  {rid}')
                time.sleep(0.2)
            elif rec.get('kind') == 'code_repo':
                m = re.search(r'github\.com/([^/]+/[^/#?]+)', rec.get('url', ''))
                if m:
                    gr = repos.get(m.group(1).lower().rstrip('/'))
                    if gr:
                        impact[rid] = {k: gr.get(k, 0) for k in ('stars', 'forks', 'contributors', 'commits')}
                        print(f'  repo  {gr.get("stars"):>6}*  {rid}')
    json.dump(impact, open(OUT, 'w'), indent=1)
    print(f'{len(impact)} impact records -> {OUT}')


if __name__ == '__main__':
    main()
