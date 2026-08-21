#!/usr/bin/env python3
"""Curate the citation-tail works that carry NO DOI.

curate/paper_curate.py is DOI-keyed end to end: its worklist filter, its staging
filenames, its full-text cache lookup and the url and doi it writes on every
record all assume one. The tail holds a couple of dozen works with no DOI at all
-- institutional-repository deposits, HAL and DiVA records, dissertations, a
statistics-agency report -- so that script has never seen them, and they are the
residue that keeps showing as uncurated pooled rows on the site.

Rather than re-plumb a 50KB script for two dozen rows, this imports it and
replaces exactly two things: the candidate loader, which keys on the OpenAlex
work id instead of a DOI, and the two script-owned fields, so the record's url
is the landing page rather than a doi.org link. The prompt, the evidence packer,
the validator, the confidence cap and the staging layout are all the originals.

    python3 curate/paper_curate_nodoi.py --list    # what is in scope, no API call
    python3 curate/paper_curate_nodoi.py --dump    # print the packed evidence
    python3 curate/paper_curate_nodoi.py --run     # live calls, one per work

Records land in curate/paper-shards/records/ beside the DOI-keyed ones, named
for the OpenAlex id so the two can never collide. Failures go to a SEPARATE
needs-review-nodoi.jsonl, because paper_curate's --recover and --retry look
their rows up by DOI and would skip these silently.

Needs ANTHROPIC_API_KEY for --run.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_curate as pc

REVIEW = os.path.join(pc.OUT, 'needs-review-nodoi.jsonl')


def nurl(value):
    return re.sub(r'/+$', '', re.sub(r'^https?://(www\.)?', '', str(value or '').lower()))


def norm_title(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def shard_urls():
    """Every url any shard owns. paper_curate's shard_dois() collects DOIs only,
    which is exactly the wrong key here."""
    found = set()
    for path in sorted(glob.glob(os.path.join(pc.SHARDS, '*.json'))):
        try:
            records = json.load(open(path))
        except ValueError:
            continue
        if isinstance(records, dict):
            records = records.get('entries', records.get('records', []))
        for record in records or []:
            if isinstance(record, dict) and record.get('url'):
                found.add(nurl(record['url']))
    return found


def key_for(work):
    return 'openalex-' + str(work.get('id') or '').rstrip('/').split('/')[-1].lower()


def title_contexts():
    """Citation contexts keyed by TITLE.

    The edges carry doi, arxiv, openalex_id and title, and for a work with no DOI
    the first three are all commonly null -- so the title is the only join that
    reaches them.
    """
    by_title = collections.defaultdict(list)
    if not os.path.exists(pc.CONTEXTS):
        return by_title
    for edge in json.load(open(pc.CONTEXTS)).get('edges', []):
        for sentence in edge.get('contexts') or []:
            by_title[norm_title(edge.get('title'))].append((edge.get('anchor'), sentence))
    return by_title


def load_candidates():
    tail = json.load(open(pc.TAIL))
    seen, works = set(), []
    for work in tail:                      # the tail carries 14 doubled records
        if work.get('id') in seen:
            continue
        seen.add(work['id'])
        works.append(work)
    works.sort(key=lambda w: -(w.get('cited_by_count') or 0))

    curated = shard_urls()
    abstracts = json.load(open(pc.ABSTRACTS)) if os.path.exists(pc.ABSTRACTS) else {}
    contexts = title_contexts()
    done = {os.path.basename(p)[:-5]
            for p in glob.glob(os.path.join(pc.RECORDS, '*.json'))}
    taken = pc.existing_ids()

    candidates = []
    for work in works:
        if pc.bare_doi(work.get('doi')).startswith('10.'):
            continue                       # paper_curate.py owns these
        location = work.get('primary_location') or {}
        url = location.get('landing_page_url') or work.get('id')
        if not url:
            continue
        if nurl(url) in curated or nurl(work.get('id')) in curated:
            continue
        key = key_for(work)
        if pc.slug_for_doi(key) in done:
            continue
        abstract = pc.reconstruct(abstracts.get(work.get('id')))
        cites = contexts.get(norm_title(work.get('title'))) or []
        tier = 'abstract_context' if (abstract or cites) else 'metadata_only'
        kind = pc.KIND_OF.get(work.get('type'), 'paper')
        entry_id = pc.slug_for(work.get('title'), work.get('publication_year'),
                               kind, taken)
        candidates.append({'doi': key, 'url': url, 'id': entry_id, 'kind': kind,
                           'work': work, 'tier': tier, 'text': None,
                           'abstract': abstract, 'cites': cites})
    return candidates


_original_finalize = pc.finalize


def finalize(record, candidate):
    """The script-owned fields, minus the DOI this work does not have."""
    out = _original_finalize(record, candidate)
    out['url'] = candidate['url']
    out.pop('doi', None)
    out['openalex_id'] = candidate['work'].get('id')
    return out


_original_pack = pc.pack_evidence


def pack_evidence(candidate):
    return (_original_pack(candidate)
            + '\n\nNOTE: this work has NO DOI. The "doi" shown in the metadata above '
              'is an internal key, not a real identifier, and must not appear in the '
              f'record. The work is published at {candidate["url"]}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true', help='what is in scope')
    parser.add_argument('--dump', action='store_true', help='print packed evidence')
    parser.add_argument('--run', action='store_true', help='live calls, costs money')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()

    pc.finalize = finalize
    pc.pack_evidence = pack_evidence
    pc.REVIEW = REVIEW

    candidates = load_candidates()
    if args.limit:
        candidates = candidates[:args.limit]
    tiers = collections.Counter(c['tier'] for c in candidates)
    print(f'{len(candidates)} works with no DOI: ' +
          ', '.join(f'{n} {t}' for t, n in tiers.most_common()))

    if args.list or not (args.dump or args.run):
        for c in candidates:
            print(f"  {c['tier']:16s} {c['id']:52s} {c['url']}")
        if not (args.dump or args.run):
            print('\nnothing called. Re-run with --dump or --run.')
        return

    if args.dump:
        for c in candidates:
            print('=' * 78)
            print(c['id'], c['tier'], c['url'])
            print(pack_evidence(c))
        return

    vocab = pc.read_vocabularies()
    ok = failed = 0
    for c in candidates:
        response = json.loads(pc.call('POST', '/messages',
                                      pc.build_request(c, vocab)['params']))
        text = ''.join(b.get('text', '') for b in response.get('content', []))
        problems = []
        record = pc.write_result(c, text, vocab, response.get('usage'), problems)
        ok, failed = (ok + 1, failed) if record else (ok, failed + 1)
        print(f'  {"OK   " if record else "AGAIN"}  {c["id"]}')
        for problem in problems:
            print('        ', problem)
        time.sleep(1)
    print(f'\n{ok} written to {pc.RECORDS}, {failed} to {REVIEW}')


if __name__ == '__main__':
    main()
