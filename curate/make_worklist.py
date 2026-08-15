#!/usr/bin/env python3
"""Build a curation worklist CSV from the citation tail.

Reads data/tail/openalex-citations.json (raw OpenAlex citing works) and writes
curate/curation-worklist.csv: one row per work, with identifying/pointer
columns pre-filled and empty output columns for a downstream agent to fill.
See curate/curation-instructions.md for the column spec and rules.

Stdlib only. Re-run after the tail grows (Scholar / GitHub deltas).
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
OUT = os.path.join(ROOT, 'curate', 'curation-worklist.csv')
BATCH_SIZE = 50
MAX_AUTHORS = 12

# Pre-filled pointer columns, then the columns the downstream agent fills in.
INPUT_COLS = ['batch', 'openalex_id', 'title', 'authors', 'year', 'venue',
              'type', 'cited_by_count', 'doi', 'url_landing', 'url_pdf']
OUTPUT_COLS = ['uses_sdv', 'integration', 'evidence', 'sdv_component', 'use_case',
               'industry', 'kind', 'summary', 'code_url', 'confidence', 'needs',
               'source_url']


def short_id(openalex_url):
    return (openalex_url or '').rstrip('/').rsplit('/', 1)[-1]


def bare_doi(doi):
    return (doi or '').replace('https://doi.org/', '').strip()


def authors_of(rec):
    names = []
    for a in rec.get('authorships') or []:
        nm = (a.get('author') or {}).get('display_name')
        if nm:
            names.append(nm)
    if len(names) > MAX_AUTHORS:
        names = names[:MAX_AUTHORS] + ['et al.']
    return '; '.join(names)


def venue_of(rec):
    loc = rec.get('primary_location') or {}
    return ((loc.get('source') or {}) or {}).get('display_name') or ''


def pdf_of(rec):
    loc = rec.get('primary_location') or {}
    return loc.get('pdf_url') or (rec.get('open_access') or {}).get('oa_url') or ''


def landing_of(rec):
    loc = rec.get('primary_location') or {}
    return loc.get('landing_page_url') or rec.get('doi') or rec.get('id') or ''


def main():
    works = json.load(open(SRC))
    with open(OUT, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=INPUT_COLS + OUTPUT_COLS)
        w.writeheader()
        for i, rec in enumerate(works):
            row = {c: '' for c in INPUT_COLS + OUTPUT_COLS}
            row.update({
                'batch': (i // BATCH_SIZE) + 1,
                'openalex_id': short_id(rec.get('id')),
                'title': rec.get('title') or '',
                'authors': authors_of(rec),
                'year': rec.get('publication_year') or '',
                'venue': venue_of(rec),
                'type': rec.get('type') or '',
                'cited_by_count': rec.get('cited_by_count') or 0,
                'doi': bare_doi(rec.get('doi')),
                'url_landing': landing_of(rec),
                'url_pdf': pdf_of(rec),
            })
            w.writerow(row)
    print(f'{len(works)} rows, {(len(works) - 1) // BATCH_SIZE + 1} batches -> {OUT}')


if __name__ == '__main__':
    main()
