#!/usr/bin/env python3
"""Fold the Semantic Scholar citation edges into the OpenAlex citation tail.

OpenAlex links 94 citing works to the CTGAN paper; Semantic Scholar reports over two
thousand. data/tail/citation-contexts.json holds those edges but nothing ever resolved
them into tail records. This does that, and slims the tail while it is here.

Slimming is not optional. Tail records averaged 12 kB because they carried the OpenAlex
abstract index and concept list, neither of which the page reads. Tripling the work count
at that size gives a 36 MB file that index.html fetches on every load. The same records
without those two fields are 838 bytes, so the tripled tail lands at 2.2 MB.

The abstracts are still needed -- they are the evidence a curator reads -- so they move to
data/tail/openalex-abstracts.json, keyed by OpenAlex id. Nothing in the browser opens it.

    OPENALEX_API_KEY=... python harvest/resolve_s2.py [--dry-run] [--limit N]

Idempotent: re-running adds only works the tail does not already hold. Stdlib only.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAIL = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
ABSTRACTS = os.path.join(ROOT, 'data', 'tail', 'openalex-abstracts.json')
EDGES = os.path.join(ROOT, 'data', 'tail', 'citation-contexts.json')

# Everything the page (assets/js/sdv-index.js) and build.py read from a tail record.
# Anything not listed here is dropped from the tail; abstracts and concepts are diverted
# to the abstracts file rather than discarded.
KEEP = ('id', 'doi', 'title', 'publication_year', 'type', 'cited_by_count',
        'curation', 'cites_anchors', 'source_channel', 'influential')


def norm_doi(v):
    return re.sub(r'^https?://(dx\.)?doi\.org/', '', str(v or '').lower()).rstrip('/')


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', str(t or '').lower()).strip()


def slim(work):
    """Reduce an OpenAlex work to what the page needs, plus the curation fields."""
    loc = work.get('primary_location') or {}
    out = {k: work.get(k) for k in KEEP if work.get(k) is not None}
    out['primary_location'] = {'landing_page_url': loc.get('landing_page_url'),
                               'pdf_url': loc.get('pdf_url')}
    out['authorships'] = [{'author': {'display_name': (a.get('author') or {}).get('display_name')}}
                          for a in (work.get('authorships') or [])[:12]
                          if (a.get('author') or {}).get('display_name')]
    return out


def openalex(path, key, **params):
    if key:
        params['api_key'] = key
    url = 'https://api.openalex.org/' + path + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as fh:
        return json.load(fh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='resolve and report, write nothing')
    ap.add_argument('--limit', type=int, help='cap the works resolved, for a trial run')
    args = ap.parse_args()
    key = os.environ.get('OPENALEX_API_KEY')

    tail = json.load(open(TAIL))
    edges = json.load(open(EDGES))['edges']

    have_doi = {norm_doi(w.get('doi')) for w in tail if w.get('doi')}
    have_id = {str(w.get('id', '')).lower().rsplit('/', 1)[-1] for w in tail}
    have_title = {norm_title(w.get('title')) for w in tail}

    # One edge per citing work per anchor, so a work citing three anchors appears thrice.
    # Collapse first, and keep every anchor it cited.
    uniq, anchors = {}, collections.defaultdict(set)
    for e in edges:
        k = (norm_doi(e.get('doi')) or str(e.get('openalex_id') or '').lower()
             or e.get('arxiv') or norm_title(e.get('title')))
        if not k:
            continue
        uniq.setdefault(k, e)
        anchors[k].add(e['anchor'])

    todo = {k: e for k, e in uniq.items()
            if norm_doi(e.get('doi')) not in have_doi
            and str(e.get('openalex_id', '')).lower().rsplit('/', 1)[-1] not in have_id
            and norm_title(e.get('title')) not in have_title}
    print(f'{len(edges)} edges -> {len(uniq)} distinct works, {len(uniq) - len(todo)} already '
          f'in the tail, {len(todo)} to resolve')
    if args.limit:
        todo = dict(list(todo.items())[:args.limit])
        print(f'  limited to {len(todo)}')

    resolved = {}

    by_doi = {norm_doi(e['doi']): k for k, e in todo.items() if e.get('doi')}
    dois = sorted(by_doi)
    print(f'resolving {len(dois)} by DOI in {(len(dois) + 49) // 50} batches')
    for i in range(0, len(dois), 50):
        batch = dois[i:i + 50]
        try:
            data = openalex('works', key, filter='doi:' + '|'.join(batch), per_page=50)
        except Exception as e:
            print(f'  batch at {i}: {type(e).__name__}')
            continue
        for w in data.get('results', []):
            k = by_doi.get(norm_doi(w.get('doi')))
            if k:
                resolved[k] = w
        time.sleep(0.15)

    # arXiv ids resolve as DOIs under the 10.48550 prefix.
    by_arxiv = {'10.48550/arxiv.' + str(e['arxiv']).lower(): k
                for k, e in todo.items() if e.get('arxiv') and k not in resolved}
    axs = sorted(by_arxiv)
    print(f'resolving {len(axs)} by arXiv id')
    for i in range(0, len(axs), 50):
        batch = axs[i:i + 50]
        try:
            data = openalex('works', key, filter='doi:' + '|'.join(batch), per_page=50)
        except Exception as e:
            print(f'  arxiv batch at {i}: {type(e).__name__}')
            continue
        for w in data.get('results', []):
            k = by_arxiv.get(norm_doi(w.get('doi')))
            if k:
                resolved[k] = w
        time.sleep(0.15)

    # Title search is one request per work, so it goes last and only for what is left.
    left = [k for k in todo if k not in resolved and todo[k].get('title')]
    print(f'resolving {len(left)} by title search')
    for n, k in enumerate(left):
        title = re.sub(r'[^\w\s]', ' ', todo[k]['title'])[:180]
        try:
            data = openalex('works', key, filter='title.search:' + title, per_page=1)
        except Exception:
            continue
        cand = (data.get('results') or [None])[0]
        # Require an exact normalized match: a loose title hit attaches the wrong paper,
        # which is far worse than leaving the work unresolved.
        if cand and norm_title(cand.get('title')) == norm_title(todo[k]['title']):
            resolved[k] = cand
        if n % 25 == 0:
            time.sleep(0.5)
        time.sleep(0.1)

    print(f'\nresolved {len(resolved)} of {len(todo)} ({100 * len(resolved) // max(1, len(todo))}%)')

    added = []
    for k, w in resolved.items():
        rec = slim(w)
        rec['source_channel'] = 'semantic_scholar_discovery'
        rec['cites_anchors'] = sorted(anchors[k])
        if todo[k].get('influential'):
            rec['influential'] = True
        added.append(rec)

    # Slim the works already in the tail too, and lift every abstract out.
    abstracts = json.load(open(ABSTRACTS)) if os.path.exists(ABSTRACTS) else {}
    for w in tail:
        if w.get('abstract_inverted_index'):
            abstracts[w['id']] = w['abstract_inverted_index']
    for w in resolved.values():
        if w.get('abstract_inverted_index'):
            abstracts[w['id']] = w['abstract_inverted_index']
    merged = [slim(w) for w in tail] + added

    print(f'tail {len(tail)} -> {len(merged)} works, {len(added)} new, '
          f'{sum(1 for r in added if r.get("influential"))} of them flagged influential')
    print(f'abstracts lifted out: {len(abstracts)}')
    if args.dry_run:
        print('\ndry run, nothing written')
        return 0
    json.dump(merged, open(TAIL, 'w'), ensure_ascii=False)
    json.dump(abstracts, open(ABSTRACTS, 'w'), ensure_ascii=False)
    for path in (TAIL, ABSTRACTS):
        print(f'  wrote {path} ({os.path.getsize(path) / 1e6:.1f} MB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
