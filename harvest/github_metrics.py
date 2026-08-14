#!/usr/bin/env python3
"""Enrich the GitHub candidate pool with popularity/authorship signals.

    GITHUB_TOKEN=<token> SSL_CERT_FILE="$(python3 -m certifi)" python3 harvest/github_metrics.py

Reads and updates data/tail/github-repos.json (the consolidated GitHub pool from
github_tail.py) in place, and writes curate/github-worklist.csv -- one row/repo:
raw metric columns (each a separate number) + empty curation columns.

Core metrics come from the GraphQL API (batched ~40 repos/request); contributor
counts come from REST (count via the Link header); download counts come from
release assets and, where the repo is a published package, PyPI (pypistats).

No composite score is computed here on purpose -- the raw signals are kept
separate so the index can be designed and reweighted later in the sheet.
Resumable: re-running skips repos already enriched (status == ok). Stdlib only.
"""
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')  # read + written in place
OUT_JSON = POOL
OUT_CSV = os.path.join(ROOT, 'curate', 'github-worklist.csv')
TOKEN = os.environ['GITHUB_TOKEN']
BATCH = 12
META = {}  # evidence_codes / query_totals carried through from the pool file

METRIC_COLS = ['repo', 'owner', 'owner_type', 'hit_patterns', 'stars', 'forks',
               'watchers', 'commits', 'contributors', 'top_contributors',
               'release_downloads', 'pypi_package', 'pypi_downloads_month',
               'open_issues', 'pull_requests', 'disk_kb', 'language', 'license',
               'created', 'pushed', 'is_archived', 'is_fork', 'is_mirror',
               'homepage', 'topics', 'description', 'status', 'fetched_at']
OUTPUT_COLS = ['uses_sdv', 'integration', 'evidence', 'sdv_component', 'use_case',
               'industry', 'kind', 'summary', 'authors', 'confidence', 'needs']

FRAGMENT = '''
fragment F on Repository {
  nameWithOwner stargazerCount forkCount isArchived isFork isMirror
  diskUsage description homepageUrl createdAt pushedAt
  primaryLanguage { name }
  licenseInfo { spdxId }
  owner { login __typename }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  watchers { totalCount }
  issues(states: OPEN) { totalCount }
  pullRequests { totalCount }
  defaultBranchRef { target { ... on Commit { history { totalCount } } } }
  releases(first: 5) { nodes { releaseAssets(first: 10) { nodes { downloadCount } } } }
  pyproject: object(expression: "HEAD:pyproject.toml") { ... on Blob { text } }
  setuppy: object(expression: "HEAD:setup.py") { ... on Blob { text } }
  setupcfg: object(expression: "HEAD:setup.cfg") { ... on Blob { text } }
}'''


def req(url, data=None, headers=None):
    h = {'User-Agent': 'sdvworld-index'}
    h.update(headers or {})
    return urllib.request.Request(url, data=data, headers=h)


def graphql(query):
    body = json.dumps({'query': query}).encode()
    r = req('https://api.github.com/graphql', body,
            {'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'})
    for _ in range(8):
        try:
            with urllib.request.urlopen(r, timeout=90) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            wait = 60 if e.code == 403 else 20  # 403 = rate limit, 5xx = transient
            print(f'    graphql {e.code}; retry in {wait}s'); time.sleep(wait)
        except Exception as e:
            print(f'    graphql {type(e).__name__}; retry in 20s'); time.sleep(20)
    raise RuntimeError('graphql failed after 8 retries')


def rest(url):
    r = req(url, headers={'Authorization': f'Bearer {TOKEN}',
                          'Accept': 'application/vnd.github+json'})
    while True:
        try:
            resp = urllib.request.urlopen(r, timeout=45)
            return resp, resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 403:  # primary/secondary rate limit
                print(f'    rest 403; sleeping 60s'); time.sleep(60); continue
            raise


def pkg_name(node):
    for key, pat in [('pyproject', r'(?m)^\s*name\s*=\s*["\']([A-Za-z0-9._-]+)["\']'),
                     ('setupcfg', r'(?m)^\s*name\s*=\s*([A-Za-z0-9._-]+)'),
                     ('setuppy', r'name\s*=\s*["\']([A-Za-z0-9._-]+)["\']')]:
        blob = node.get(key) or {}
        m = re.search(pat, blob.get('text') or '')
        if m:
            return m.group(1)
    return ''


_pypi_cache = {}
_pypi_enabled = [True]  # circuit-breaker: pypistats rate-limits hard (429)
def pypi_downloads(pkg):
    if not pkg or not _pypi_enabled[0]:
        return ''
    if pkg in _pypi_cache:
        return _pypi_cache[pkg]
    try:
        with urllib.request.urlopen(req(f'https://pypistats.org/api/packages/{pkg.lower()}/recent'), timeout=30) as resp:
            v = json.load(resp).get('data', {}).get('last_month', '')
    except urllib.error.HTTPError as e:
        if e.code == 429:
            _pypi_enabled[0] = False  # stop trying once rate-limited
        v = ''
    except Exception:
        v = ''
    _pypi_cache[pkg] = v
    time.sleep(0.4)
    return v


def contributors(repo):
    url = f'https://api.github.com/repos/{repo}/contributors?per_page=100&anon=1'
    try:
        resp, raw = rest(url)
    except urllib.error.HTTPError as e:
        return (0, []) if e.code in (204, 404, 403) else (None, [])
    data = json.loads(raw or b'[]')
    top = [(c.get('login') or c.get('name') or 'anon') for c in data[:5]]
    link = resp.headers.get('Link', '')
    m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
    if m:
        last = int(m.group(1))
        resp2, raw2 = rest(url + f'&page={last}')
        count = (last - 1) * 100 + len(json.loads(raw2 or b'[]'))
    else:
        count = len(data)
    time.sleep(0.4)
    return count, top


def parse(node, repo, hp):
    if node is None:
        return {'repo': repo, 'hit_patterns': hp, 'status': 'gone',
                'fetched_at': time.strftime('%Y-%m-%d')}
    dl = sum(a['downloadCount'] for rel in (node.get('releases', {}) or {}).get('nodes', [])
             for a in (rel.get('releaseAssets', {}) or {}).get('nodes', []))
    br = node.get('defaultBranchRef') or {}
    commits = (((br.get('target') or {}).get('history') or {}).get('totalCount')) or 0
    topics = [t['topic']['name'] for t in (node.get('repositoryTopics', {}) or {}).get('nodes', [])]
    pkg = pkg_name(node)
    return {
        'repo': node['nameWithOwner'],
        'owner': (node.get('owner') or {}).get('login', ''),
        'owner_type': (node.get('owner') or {}).get('__typename', ''),
        'hit_patterns': hp,
        'stars': node.get('stargazerCount', 0),
        'forks': node.get('forkCount', 0),
        'watchers': (node.get('watchers') or {}).get('totalCount', 0),
        'commits': commits,
        'release_downloads': dl,
        'pypi_package': pkg,
        'pypi_downloads_month': pypi_downloads(pkg),
        'open_issues': (node.get('issues') or {}).get('totalCount', 0),
        'pull_requests': (node.get('pullRequests') or {}).get('totalCount', 0),
        'disk_kb': node.get('diskUsage', 0),
        'language': (node.get('primaryLanguage') or {}).get('name', ''),
        'license': (node.get('licenseInfo') or {}).get('spdxId', ''),
        'created': (node.get('createdAt') or '')[:10],
        'pushed': (node.get('pushedAt') or '')[:10],
        'is_archived': node.get('isArchived', False),
        'is_fork': node.get('isFork', False),
        'is_mirror': node.get('isMirror', False),
        'homepage': node.get('homepageUrl') or '',
        'topics': topics,
        'description': (node.get('description') or '').strip(),
        'status': 'ok',
        'fetched_at': time.strftime('%Y-%m-%d'),
    }


def write_outputs(records):
    with open(OUT_JSON, 'w') as fh:
        json.dump({'note': 'Consolidated GitHub repo pool: harvest patterns + per-repo '
                           'metrics. Raw, uncurated; not index entries.',
                   'generated': time.strftime('%Y-%m-%d'), 'count': len(records),
                   'evidence_codes': META.get('evidence_codes', {}),
                   'query_totals': META.get('query_totals', {}),
                   'repos': list(records.values())}, fh, indent=1, ensure_ascii=False)
    with open(OUT_CSV, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=METRIC_COLS + OUTPUT_COLS)
        w.writeheader()
        for rec in sorted(records.values(), key=lambda r: -(r.get('stars') or 0)):
            row = {c: '' for c in METRIC_COLS + OUTPUT_COLS}
            row.update(rec)
            row['topics'] = '|'.join(rec.get('topics') or [])
            row['top_contributors'] = '|'.join(rec.get('top_contributors') or [])
            w.writerow({k: row.get(k, '') for k in METRIC_COLS + OUTPUT_COLS})


def main():
    pool_json = json.load(open(POOL))
    pool = pool_json.get('repos', [])
    META['evidence_codes'] = pool_json.get('evidence_codes', {})
    META['query_totals'] = pool_json.get('query_totals', {})
    hits_by = {r['repo']: (r.get('hit_patterns') or '') for r in pool}
    records = {r['repo']: r for r in pool if r.get('status') == 'ok'}
    todo = [r['repo'] for r in pool if r.get('status') != 'ok']
    print(f'{len(records)} already enriched, {len(todo)} to fetch')

    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        pairs = [r.split('/', 1) for r in batch]
        aliases = '\n'.join(
            f'  r{i}: repository(owner: {json.dumps(o)}, name: {json.dumps(n)}) {{ ...F }}'
            for i, (o, n) in enumerate(pairs))
        resp = graphql('query {\n' + aliases + '\n  rateLimit { remaining cost }\n}' + FRAGMENT)
        data = resp.get('data') or {}
        for i, repo in enumerate(batch):
            rec = parse(data.get(f'r{i}'), repo, hits_by[repo])
            if rec['status'] == 'ok':
                cnt, top = contributors(repo)
                rec['contributors'] = cnt if cnt is not None else ''
                rec['top_contributors'] = top
            records[repo] = rec
        rl = (data.get('rateLimit') or {})
        print(f'  {start + len(batch)}/{len(todo)}  graphql remaining={rl.get("remaining")}')
        write_outputs(records)          # checkpoint every batch
        if (rl.get('remaining') or 5000) < 100:
            print('    graphql budget low; sleeping 120s'); time.sleep(120)

    gone = sum(1 for r in records.values() if r.get('status') == 'gone')
    print(f'done: {len(records)} repos ({gone} gone) -> {OUT_JSON} + {OUT_CSV}')


if __name__ == '__main__':
    main()
