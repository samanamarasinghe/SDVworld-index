#!/usr/bin/env python3
"""Ingest login-lane PDFs from a staging folder into harvest/papers/.

    python3 harvest/stage_login_pdfs.py --report
    python3 harvest/stage_login_pdfs.py --limit 10
    python3 harvest/stage_login_pdfs.py
    python3 harvest/stage_login_pdfs.py --write-log

The login lane downloads PDFs through Saman's institutional session into a staging
folder, named <doi with / replaced by _>.pdf.  paper_fetch.py cannot produce those
files -- no route reaches a paywalled publisher -- so this script does the half of
paper_fetch's job that remains: extract the text, write it under the SAME slug and
the SAME sidecar shape paper_fetch writes, and flip the row in fetch-log.json.

WHY THE FILENAME IS ENOUGH.  paper_fetch.slug_for is
re.sub(r'[^a-z0-9]+', '_', doi.lower()), which collapses dots as well as slashes, so
slugifying the staging filename stem gives exactly the slug paper_fetch would have
used.  The real DOI is still needed for the sidecar and the log, and is recovered by
matching that slug against the keys of harvest/fetch-log.json -- verified collision
free across all 2,384 logged DOIs.

The sidecar url is recorded as https://doi.org/<doi> rather than the publisher pdf
url the runner used: the runner's url is a session-authenticated route that nobody
else can follow, and doi.org is the honest, durable provenance for a paper obtained
through an institutional login.

A file whose slug matches no logged DOI is NOT an error: those are the rows that came
from missing_pdfs.xlsx and never went through paper_fetch.  They are reported
separately and skipped, because without a DOI there is nothing to key a record to.

--write-log is deliberately a separate pass over the sidecars on disk, so the log is
never edited on the strength of an extraction that has not landed.

Depends on pypdf, the one non-stdlib import paper_fetch.py already takes.
"""

import argparse
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'harvest', 'papers')
LOG = os.path.join(ROOT, 'harvest', 'fetch-log.json')
STAGING = os.path.expanduser('~/workspace/sdv-login-staging')
MIN_CHARS = 2000                  # paper_fetch's own floor: a cover page is not a paper
ROUTE = 'login'


def slug_for(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')


def load_log():
    with open(LOG, encoding='utf-8') as fh:
        return json.load(fh)


def doi_index(log):
    """slug -> real DOI, over every DOI the log has ever seen."""
    return {slug_for(doi): doi for doi in log['attempts']}


def extract(blob):
    """PDF bytes to text.  Same shape as paper_fetch.extract, deliberately.

    The surrogatepass/ignore round trip is not cosmetic: mathematical PDFs decode
    italic glyphs to lone surrogates, which cannot be encoded as UTF-8, and the write
    would die after the extraction had already succeeded.
    """
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or '')
        except Exception:
            pages.append('')
    text = '\n'.join(pages)
    return text.encode('utf-8', 'surrogatepass').decode('utf-8', 'ignore')


def scan(staging, index, meta):
    """Every staged pdf, classified.  Reads no pdf bytes."""
    rows = []
    for name in sorted(os.listdir(staging)):
        if not name.lower().endswith('.pdf'):
            continue
        slug = slug_for(name[:-4])
        text_path = os.path.join(OUT, slug + '.txt')
        cached = (os.path.exists(text_path)
                  and os.path.getsize(text_path) > MIN_CHARS)
        doi = index.get(slug)
        rows.append({'name': name, 'slug': slug, 'doi': doi, 'cached': cached,
                     'meta': meta.get(doi) or {},
                     'bytes': os.path.getsize(os.path.join(staging, name))})
    return rows


def report(rows):
    known = [r for r in rows if r['doi']]
    unknown = [r for r in rows if not r['doi']]
    todo = [r for r in known if not r['cached']]
    print(f'staged pdfs          {len(rows)}')
    print(f'  doi resolved       {len(known)}')
    print(f'  already extracted  {len(known) - len(todo)}')
    print(f'  to extract         {len(todo)}')
    print(f'  no doi in log      {len(unknown)}   (xlsx population, skipped)')
    by_prefix = {}
    for r in todo:
        prefix = r['doi'].split('/')[0]
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1
    if by_prefix:
        print('  to extract by prefix: '
              + ', '.join(f'{k} {v}' for k, v in sorted(by_prefix.items())))
    for r in unknown[:20]:
        print('    unresolved:', r['name'])
    if len(unknown) > 20:
        print(f'    ... and {len(unknown) - 20} more')


def ingest(staging, rows, limit):
    os.makedirs(OUT, exist_ok=True)
    todo = [r for r in rows if r['doi'] and not r['cached']]
    if limit:
        todo = todo[:limit]
    short, failed, done = [], [], 0
    for i, r in enumerate(todo, 1):
        path = os.path.join(staging, r['name'])
        try:
            with open(path, 'rb') as fh:
                blob = fh.read()
            text = extract(blob)
        except Exception as exc:
            failed.append((r['name'], type(exc).__name__))
            print(f'[{i}/{len(todo)}] {r["doi"]:38s} FAILED {type(exc).__name__}',
                  flush=True)
            continue
        if len(text) < MIN_CHARS:
            short.append((r['name'], len(text)))
            print(f'[{i}/{len(todo)}] {r["doi"]:38s} SHORT {len(text)} chars',
                  flush=True)
            continue
        text_path = os.path.join(OUT, r['slug'] + '.txt')
        tmp = text_path + '.part'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, text_path)
        with open(os.path.join(OUT, r['slug'] + '.json'), 'w', encoding='utf-8') as fh:
            json.dump({'doi': r['doi'], 'route': ROUTE,
                       'url': 'https://doi.org/' + r['doi'], 'chars': len(text),
                       'title': r['meta'].get('title'), 'year': r['meta'].get('year')},
                      fh, indent=1, ensure_ascii=False)
        done += 1
        print(f'[{i}/{len(todo)}] {r["doi"]:38s} {len(text)} chars', flush=True)
    print(f'\nextracted {done}, short {len(short)}, failed {len(failed)}')
    if short:
        print('SHORT -- scanned or front-matter only, needs a look:')
        for name, n in short:
            print(f'  {n:7d}  {name}')
    if failed:
        print('FAILED:')
        for name, why in failed:
            print(f'  {why:24s} {name}')


def write_log(rows):
    """Flip fetch-log rows from the sidecars that actually landed on disk."""
    log = load_log()
    attempts = log['attempts']
    today = time.strftime('%Y-%m-%d')
    changed = 0
    for r in rows:
        if not r['doi']:
            continue
        side = os.path.join(OUT, r['slug'] + '.json')
        if not os.path.exists(side):
            continue
        with open(side, encoding='utf-8') as fh:
            saved = json.load(fh)
        if saved.get('route') != ROUTE:
            continue                  # a real paper_fetch route won it; leave alone
        old = attempts.get(r['doi']) or {}
        tried = list(old.get('routes_tried') or [])
        if ROUTE not in tried:
            tried.append(ROUTE)
        attempts[r['doi']] = dict(old, status='ok', route=ROUTE,
                                  url=saved['url'], chars=saved['chars'],
                                  routes_tried=tried, when=today)
        changed += 1
    tmp = LOG + '.part'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, LOG)
    ok = sum(1 for a in attempts.values() if a.get('status') == 'ok')
    print(f'fetch-log.json: {changed} rows flipped to ok via {ROUTE}; '
          f'{ok} ok of {len(attempts)} total')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--staging', default=STAGING)
    ap.add_argument('--report', action='store_true', help='classify only, write nothing')
    ap.add_argument('--limit', type=int, help='extract at most N (pilot)')
    ap.add_argument('--write-log', action='store_true',
                    help='update harvest/fetch-log.json from the sidecars on disk')
    args = ap.parse_args()

    if not os.path.isdir(args.staging):
        sys.exit(f'no staging folder at {args.staging}')
    if not os.path.exists(LOG):
        sys.exit(f'no {LOG}; commit or pull it first')

    log = load_log()
    rows = scan(args.staging, doi_index(log), log['attempts'])
    if args.write_log:
        write_log(rows)
        return
    report(rows)
    if args.report:
        return
    print()
    ingest(args.staging, rows, args.limit)


if __name__ == '__main__':
    main()
