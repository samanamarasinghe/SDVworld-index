#!/usr/bin/env python3
"""Fetch the sentence in which each citing work cites an SDV anchor paper.

    python harvest/citation_contexts.py --check     # one page per anchor, write nothing
    python harvest/citation_contexts.py             # write data/tail/citation-contexts.json

Why this exists. For a citation_only work the abstract is the wrong document: SDV
appears in related work, so the abstract says what the paper is about and nothing
about what it says about SDV. Writing the second half of the SDV clause -- which
part of SDV, in what role -- otherwise means fetching 736 full texts.

Semantic Scholar returns that sentence directly. Citation edges carry `contexts`
(the text around the citation) and `intents` (Background / Methodology / Result),
so querying by ANCHOR rather than by citing paper covers the whole tail in about
ten paginated requests instead of 736 fetches. `isInfluential` comes along for free
and is a usable triage signal.

The endpoint is public; SEMANTIC_SCHOLAR_API_KEY is optional and only raises the
rate limit. Unauthenticated traffic is throttled during heavy use, hence the retry.

This script gathers. It does not judge: no summary, no facets, no importance. A
curating agent reads the contexts and writes the clause, exactly as with
harvest/repo_evidence.py.
"""
import argparse
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
DEST = os.path.join(ROOT, 'data', 'tail', 'citation-contexts.json')

API = 'https://api.semanticscholar.org/graph/v1/paper/{pid}/citations'
FIELDS = 'contexts,intents,isInfluential,title,externalIds,year'
PAGE = 1000          # API maximum per page
MAX_PAGES = 12       # CTGAN carries most of the tail; 12 pages is ample headroom

# Keyed to the `cites_anchors` values already present in the pooled records, so the
# output joins straight back onto them.
ANCHORS = {
    'sdv-dsaa-2016':      'DOI:10.1109/DSAA.2016.49',
    'ctgan-neurips-2019': 'arXiv:1907.00503',
    'tgan-2018':          'arXiv:1811.11264',
    'vine-copula-2019':   'arXiv:1812.01226',
    'sequential-2022':    'arXiv:2207.14406',
}


def ssl_context():
    """Build a context with a CA bundle that actually exists.

    The python.org macOS installer does not use the system keychain and ships
    without a populated CA store, so every HTTPS request fails with
    CERTIFICATE_VERIFY_FAILED until "Install Certificates.command" is run. That
    command is the proper fix, but this script should not depend on whether
    someone remembered to run it, so certifi is used when available. certifi is
    an optional convenience -- the script remains standard-library-only and falls
    back to the default context, which is correct on Linux and on Homebrew
    Python.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL = ssl_context()


def get(url, key, attempt=0):
    req = urllib.request.Request(url)
    if key:
        req.add_header('x-api-key', key)
    try:
        with urllib.request.urlopen(req, timeout=60, context=SSL) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        # 429 is the documented throttle for unauthenticated traffic; back off and retry.
        if exc.code in (429, 502, 503, 504) and attempt < 5:
            wait = 2 ** attempt * 5
            print(f'  HTTP {exc.code}, retrying in {wait}s', flush=True)
            time.sleep(wait)
            return get(url, key, attempt + 1)
        raise
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise SystemExit(
                'TLS certificate verification failed.\n'
                'On a python.org macOS build this means the CA store was never '
                'populated. Fix it with:\n'
                '    /Applications/Python\\ 3.x/Install\\ Certificates.command\n'
                'or install certifi (pip install certifi) and re-run.'
            ) from exc
        raise


def fetch_anchor(anchor, pid, key, max_pages):
    """Page through every citation edge pointing at one anchor paper."""
    out, offset = [], 0
    for _ in range(max_pages):
        qs = urllib.parse.urlencode({'fields': FIELDS, 'limit': PAGE, 'offset': offset})
        page = get(API.format(pid=urllib.parse.quote(pid, safe=':.')) + '?' + qs, key)
        rows = page.get('data') or []
        for row in rows:
            citing = row.get('citingPaper') or {}
            ext = citing.get('externalIds') or {}
            out.append({
                'anchor': anchor,
                'doi': (ext.get('DOI') or '').lower() or None,
                'arxiv': ext.get('ArXiv'),
                'title': citing.get('title'),
                'year': citing.get('year'),
                'contexts': row.get('contexts') or [],
                'intents': row.get('intents') or [],
                'influential': bool(row.get('isInfluential')),
            })
        print(f'  {anchor}: +{len(rows)} (offset {offset})', flush=True)
        if 'next' not in page or not rows:
            break
        offset = page['next']
        time.sleep(1)
    return out


def pool_index(path):
    """DOI -> openalex id, so contexts can be joined onto the curation pool."""
    if not os.path.exists(path):
        return {}
    idx = {}
    for rec in json.load(open(path)):
        doi = (rec.get('doi') or '').lower().replace('https://doi.org/', '')
        if doi:
            idx[doi] = rec['id']
    return idx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true',
                        help='one page per anchor, report coverage, write nothing')
    parser.add_argument('--anchor', help='fetch a single anchor by key')
    args = parser.parse_args()

    key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY')
    if not key:
        print('no SEMANTIC_SCHOLAR_API_KEY set; using the public rate limit')

    anchors = {args.anchor: ANCHORS[args.anchor]} if args.anchor else ANCHORS
    pages = 1 if args.check else MAX_PAGES

    rows = []
    for anchor, pid in anchors.items():
        print(f'{anchor} ({pid})', flush=True)
        rows.extend(fetch_anchor(anchor, pid, key, pages))

    idx = pool_index(POOL)
    matched = withctx = 0
    for r in rows:
        r['openalex_id'] = idx.get(r['doi'] or '')
        matched += bool(r['openalex_id'])
        withctx += bool(r['contexts'])

    print(f'\n{len(rows)} citation edges')
    print(f'  {withctx} carry at least one context sentence')
    print(f'  {matched} join onto a pooled OpenAlex record by DOI')
    intents = {}
    for r in rows:
        for i in (r['intents'] or ['(none)']):
            intents[i] = intents.get(i, 0) + 1
    print('  intents:', intents)

    if args.check:
        print('\n--check: nothing written')
        return

    with open(DEST, 'w') as fh:
        json.dump({'note': ('Citation contexts and intents from Semantic Scholar, keyed '
                            'by anchor. Gathering only: a curating agent writes the '
                            'clause from these sentences.'),
                   'edges': rows}, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    print(f'\n-> {DEST}')


if __name__ == '__main__':
    main()
