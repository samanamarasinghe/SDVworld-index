#!/usr/bin/env python3
"""Re-judge already-curated papers whose evidence tier has improved to full_text.

    python3 curate/paper_rejudge.py --report
    python3 curate/paper_rejudge.py --pilot 5            # synchronous, prints the diff
    python3 curate/paper_rejudge.py --submit --dry-run
    python3 curate/paper_rejudge.py --submit
    python3 curate/paper_rejudge.py --status
    python3 curate/paper_rejudge.py --collect
    python3 curate/paper_rejudge.py --diff              # old vs new, no API call
    python3 curate/paper_rejudge.py --shard 148         # write the correction shard

paper_curate.py cannot do this.  Its load_candidates() skips any DOI a shard already
owns and any DOI already staged in records/, which is correct for finding NEW work and
exactly wrong here: every row this script cares about is curated already.  Its own
docstring asks for the pass anyway -- "when a paper later arrives as full text the rows
to re-judge are exactly the ones whose tier improved.  Re-judge them; do not simply
lift the confidence, because full text changes the integration call too" -- and this is
that pass.

THE POPULATION is every DOI that (a) a shard owns, (b) has text in harvest/papers/, and
(c) was curated at a tier below full_text.  Nothing is re-judged twice: a record whose
shard entry already reads evidence_tier full_text is skipped.

THE ID IS REUSED, NOT REGENERATED.  A re-judged record carries the id of the shard
record it replaces, so build.py merges it as a CORRECTION rather than adding a second
entry for the same paper.  paper_curate's slug_for() would mint a fresh id from the
title and quietly duplicate the work.

OUTPUT IS ISOLATED.  Records, the review queue and the batch state all live under
curate/paper-shards/rejudge/, never in records/ or needs-review.jsonl.  The curation
thread owns those, runs its own --submit/--collect against them, and a shared file
would let the two passes overwrite each other's staging.

MONKEY-PATCHING, DELIBERATELY AND LATE.  paper_curate.write_result() writes to the
module globals RECORDS and REVIEW, so redirecting the output means rebinding them.
That happens inside main(), never at import time -- paper_curate_nodoi.py patches
finalize and REVIEW AT IMPORT, which means merely importing it redirects an unrelated
lane's writes.  Import this module and nothing moves.

Needs ANTHROPIC_API_KEY.  Runs on the machine holding harvest/papers/, which is
gitignored and never leaves it.
"""

import argparse
import collections
import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_curate as pc                                    # noqa: E402

ROOT = pc.ROOT
OUT = os.path.join(ROOT, 'curate', 'paper-shards', 'rejudge')
RECORDS = os.path.join(OUT, 'records')
REVIEW = os.path.join(OUT, 'needs-review.jsonl')
STATE = os.path.join(OUT, '_batches.json')
REQUESTS_DUMP = os.path.join(OUT, '_requests.json')

# Fields whose change is a JUDGMENT change rather than better prose.  The diff report
# leads with these; a record that moves none of them is not worth a correction row.
JUDGMENT = ('integration', 'importance', 'confidence', 'sdv_component', 'sdv_concept',
            'use_case', 'industry')


def shard_records():
    """id -> (record, shard filename), over every shard.  Later shards win.

    Later-wins matters: a correction shard already overrides some of these records,
    and re-judging the superseded version would undo the correction.
    """
    found = {}
    for path in sorted(glob.glob(os.path.join(pc.SHARDS, '*.json'))):
        try:
            records = json.load(open(path))
        except ValueError:
            continue
        if isinstance(records, dict):
            records = records.get('entries') or records.get('records') or []
        for record in records:
            if isinstance(record, dict) and record.get('id'):
                found[record['id']] = (record, os.path.basename(path))
    return found


def load_candidates(limit=None):
    """Curated papers whose text is now on disk and whose tier was below full_text."""
    tail = {}
    for work in json.load(open(pc.TAIL)):
        doi = pc.bare_doi(work.get('doi'))
        if doi and doi not in tail:                  # the tail carries 14 doubled records
            tail[doi] = work
    abstracts, contexts = pc.load_side_data()
    done = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(RECORDS, '*.json'))}

    candidates, skipped = [], collections.Counter()
    for record, shard in shard_records().values():
        doi = pc.bare_doi(record.get('doi'))
        if not doi.startswith('10.'):
            skipped['no doi'] += 1
            continue
        if record.get('evidence_tier') == 'full_text':
            skipped['already full_text'] += 1
            continue
        text = pc.full_text_for(doi)
        if not text:
            skipped['no text on disk'] += 1
            continue
        if pc.slug_for_doi(doi) in done:
            skipped['already re-judged'] += 1
            continue
        work = tail.get(doi)
        if work is None:
            skipped['not in the tail'] += 1
            continue
        candidates.append({'doi': doi, 'id': record['id'],
                           'kind': record.get('kind') or 'paper',
                           'work': work, 'tier': 'full_text', 'text': text,
                           'abstract': pc.reconstruct(abstracts.get(work.get('id'))),
                           'cites': contexts.get(doi) or [],
                           'was': record, 'shard': shard})
    candidates.sort(key=lambda c: c['id'])
    return (candidates[:limit] if limit else candidates), skipped


def redirect_output():
    """Point paper_curate's writers at the rejudge staging area.  See the docstring."""
    os.makedirs(RECORDS, exist_ok=True)
    pc.RECORDS = RECORDS
    pc.REVIEW = REVIEW


def changes(old, new):
    """Judgment fields that moved, as 'field: old -> new'."""
    moved = []
    for field in JUDGMENT:
        before, after = old.get(field), new.get(field)
        if isinstance(before, list) or isinstance(after, list):
            before, after = sorted(before or []), sorted(after or [])
        if before != after:
            moved.append(f'{field}: {before!r} -> {after!r}')
    return moved


def do_report(candidates, skipped):
    print(f'{len(candidates)} papers to re-judge')
    for reason, count in sorted(skipped.items()):
        print(f'  skipped, {reason:22s} {count}')
    if not candidates:
        return
    print('\nby tier they were curated at: '
          + json.dumps(dict(collections.Counter(c['was'].get('evidence_tier')
                                                for c in candidates))))
    print('by integration they carry now: '
          + json.dumps(dict(collections.Counter(c['was'].get('integration')
                                                for c in candidates))))
    print('by shard: '
          + json.dumps(dict(sorted(collections.Counter(c['shard'][:3]
                                                       for c in candidates).items()))))
    sizes = [len(pc.pack_evidence(c)) for c in candidates[:200]]
    print(f'\nevidence payload over the first {len(sizes)}: '
          f'{sum(sizes) // len(sizes)} chars average '
          f'(~{sum(sizes) // len(sizes) // 4} tokens), max {max(sizes)}')


def do_pilot(candidates, count, vocab, seed):
    """Sampled at random, not the head: the head is one shard and one alphabet slice."""
    picked = list(candidates)
    random.Random(seed).shuffle(picked)
    picked = picked[:count]
    print(f'{len(candidates)} candidates; piloting {len(picked)}\n')
    for candidate in picked:
        request = pc.build_request(candidate, vocab)
        response = json.loads(pc.call('POST', '/messages', request['params']))
        text = ''.join(b.get('text', '') for b in response.get('content', []))
        problems = []
        record = pc.write_result(candidate, text, vocab, response.get('usage'), problems)
        print('=' * 78)
        print(candidate['id'], f'(was {candidate["was"].get("evidence_tier")}, '
                               f'{candidate["shard"]})')
        if not record:
            for problem in problems:
                print('  PROBLEM:', problem)
            print((text or '')[:2500])
        else:
            moved = changes(candidate['was'], record)
            print('  CHANGED:' if moved else '  no judgment change')
            for line in moved:
                print('   ', line)
            print('  old summary:', (candidate['was'].get('summary') or '')[:400])
            print('  new summary:', (record.get('summary') or '')[:400])
            print('  new evidence:', (record.get('evidence') or '')[:400])
        time.sleep(1)
    print(f'\nrecords in {RECORDS}, failures in {REVIEW}')


def do_submit(candidates, vocab, dry_run):
    if not candidates:
        return print('nothing to submit')
    requests_ = [pc.build_request(c, vocab) for c in candidates]
    os.makedirs(OUT, exist_ok=True)
    if dry_run:
        json.dump(requests_, open(REQUESTS_DUMP, 'w'), indent=1, ensure_ascii=False)
        chars = sum(len(r['params']['messages'][0]['content']) for r in requests_)
        print(f'{len(requests_)} requests, '
              f'{os.path.getsize(REQUESTS_DUMP) / 1e6:.1f} MB total, '
              f'{chars // len(requests_)} chars of evidence each '
              f'(~{chars // len(requests_) // 4} tokens)')
        print(f'wrote {REQUESTS_DUMP}; sent nothing')
        return
    state = json.load(open(STATE)) if os.path.exists(STATE) else {'batches': [],
                                                                  'dois': {}}
    state['dois'].update({c['id']: c['doi'] for c in candidates})
    for start in range(0, len(requests_), pc.PER_BATCH):
        chunk = requests_[start:start + pc.PER_BATCH]
        result = json.loads(pc.call('POST', '/messages/batches', {'requests': chunk}))
        state['batches'].append({'id': result['id'], 'n': len(chunk),
                                 'created': result.get('created_at'),
                                 'collected': False})
        json.dump(state, open(STATE, 'w'), indent=1)
        print(f'  submitted {result["id"]}  {len(chunk)} requests')
    print(f'\n{len(state["batches"])} batches recorded in {STATE}')
    print('come back and run --status, then --collect')


def load_state():
    if not os.path.exists(STATE):
        sys.exit(f'no {STATE}; run --submit first')
    return json.load(open(STATE))


def do_status():
    for batch in load_state()['batches']:
        info = json.loads(pc.call('GET', f'/messages/batches/{batch["id"]}'))
        print(f'{batch["id"]}  {info.get("processing_status"):12s} '
              f'{json.dumps(info.get("request_counts", {}))}  '
              f'collected={batch["collected"]}')


def do_collect(candidates, vocab):
    state = load_state()
    dois = state.get('dois', {})
    by_doi = {c['doi']: c for c in candidates}
    written = failed = 0
    for batch in state['batches']:
        if batch['collected']:
            continue
        info = json.loads(pc.call('GET', f'/messages/batches/{batch["id"]}'))
        if info.get('processing_status') != 'ended':
            print(f'{batch["id"]}: {info.get("processing_status")}, skipping')
            continue
        for line in pc.call('GET', info['results_url']).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry_id = row.get('custom_id')
            candidate = by_doi.get(dois.get(entry_id, ''))
            result = row.get('result') or {}
            if candidate is None or result.get('type') != 'succeeded':
                with open(REVIEW, 'a') as fh:
                    fh.write(json.dumps(
                        {'doi': dois.get(entry_id, ''), 'id': entry_id,
                         'tier': 'full_text',
                         'problems': [f'batch result {result.get("type")}'
                                      if candidate else 'candidate no longer in pool'],
                         'raw': json.dumps(result)[:2000]}) + '\n')
                failed += 1
                continue
            message = result.get('message') or {}
            text = ''.join(b.get('text', '') for b in message.get('content', []))
            if pc.write_result(candidate, text, vocab, message.get('usage')):
                written += 1
            else:
                failed += 1
        batch['collected'] = True
        json.dump(state, open(STATE, 'w'), indent=1)
        print(f'{batch["id"]}: collected')
    print(f'\n{written} records written to {RECORDS}')
    print(f'{failed} sent to {REVIEW}')


def collected_records():
    """id -> re-judged record, from the rejudge staging area."""
    out = {}
    for path in sorted(glob.glob(os.path.join(RECORDS, '*.json'))):
        record = json.load(open(path))
        if record.get('id'):
            out[record['id']] = record
    return out


def do_diff():
    """What the re-judge actually moved.  No API call, no writes."""
    old = shard_records()
    new = collected_records()
    moved_counts = collections.Counter()
    transitions = collections.Counter()
    unchanged = 0
    for entry_id, record in sorted(new.items()):
        before = (old.get(entry_id) or (None, None))[0]
        if before is None:
            print(f'{entry_id}: NO SHARD RECORD -- would add rather than correct')
            continue
        moved = changes(before, record)
        if not moved:
            unchanged += 1
            continue
        for line in moved:
            moved_counts[line.split(':')[0]] += 1
        if before.get('integration') != record.get('integration'):
            transitions[f'{before.get("integration")} -> '
                        f'{record.get("integration")}'] += 1
        print(f'{entry_id}  ({before.get("evidence_tier")} -> full_text, '
              f'{(old[entry_id][1])})')
        for line in moved:
            print('   ', line)
    print(f'\n{len(new)} re-judged, {unchanged} with no judgment change')
    print('fields moved: ' + json.dumps(dict(moved_counts.most_common())))
    if transitions:
        print('integration transitions: '
              + json.dumps(dict(transitions.most_common())))


def do_shard(number):
    """Write the changed records as a correction shard.  Unchanged rows are dropped.

    A correction shard must sort AFTER the shard it corrects, which is why the number
    is given rather than computed: the caller reserves it against the other lane.

    EVERY ROW CARRIES override: true.  Without it build.py treats the record as a new
    entry, matches on url instead of id, finds the original already there and drops it
    as a duplicate url -- so the corrections vanish and validate.py reports the id
    defined twice.  The flag is what makes build.py merge by id over the original; it is
    stripped from the merged record, so it never reaches the built index.
    """
    old = shard_records()
    rows = []
    for entry_id, record in sorted(collected_records().items()):
        before = (old.get(entry_id) or (None, None))[0]
        if before is not None and changes(before, record):
            rows.append(dict(record, override=True))
    if not rows:
        return print('no changed records; nothing to write')
    path = os.path.join(pc.SHARDS, f'{number:03d}-papers-rejudged-full-text.json')
    if os.path.exists(path):
        sys.exit(f'{path} exists; pick another number')
    with open(path, 'w') as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False)
    print(f'wrote {len(rows)} corrections to {path}')
    print('now: python3 build.py --write && python3 tests/validate.py')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--pilot', type=int, metavar='N')
    ap.add_argument('--seed', type=int, default=17)
    ap.add_argument('--submit', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--collect', action='store_true')
    ap.add_argument('--diff', action='store_true')
    ap.add_argument('--shard', type=int, metavar='N')
    ap.add_argument('--limit', type=int)
    args = ap.parse_args()

    if args.status:
        return do_status()
    if args.diff:
        return do_diff()
    if args.shard:
        return do_shard(args.shard)

    redirect_output()
    candidates, skipped = load_candidates(args.limit)
    if args.report:
        return do_report(candidates, skipped)

    vocab = pc.read_vocabularies()
    if args.pilot:
        return do_pilot(candidates, args.pilot, vocab, args.seed)
    if args.submit:
        return do_submit(candidates, vocab, args.dry_run)
    if args.collect:
        return do_collect(candidates, vocab)
    ap.error('pick one of --report, --pilot N, --submit, --status, --collect, '
             '--diff, --shard N')


if __name__ == '__main__':
    main()
