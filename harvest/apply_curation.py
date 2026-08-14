#!/usr/bin/env python3
"""Apply curation patches to citing-works.json and the worklist CSV.

    python harvest/apply_curation.py --check     # validate, write nothing
    python harvest/apply_curation.py             # apply and rewrite both files

Patches live in harvest/patches/*.jsonl, one JSON object per line, keyed by
openalex_id. Only the fields being set need to appear:

    {"openalex_id": "W3202428668", "uses_sdv": false,
     "integration": "citation_only", "confidence": "high",
     "evidence": "survey; CTGAN cited as prior art, never run"}

Curated values are written into a "curation" object on each record, leaving the
raw OpenAlex fields untouched (note that OpenAlex already uses "type", which is
why the curated field is called "kind").

Idempotent: re-running produces the same result. Patches apply in filename
order. Changing a value set by an earlier patch is an error unless the later
line carries "override": true, which records the correction deliberately:

    {"openalex_id": "W7163879309", "override": true,
     "integration": "derivative_work", ...}

integration values:
    api_user         calls the SDV libraries
    vendored_source  carries a copy of SDV-family source in-tree
    baseline_only    runs an SDV model purely as a foil for a proposed method
    derivative_work  ports or reimplements SDV's design, in any language
    citation_only    cites the work without running the software
    unclear          evidence insufficient to classify
"""
import argparse
import csv
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKS = os.path.join(ROOT, 'data', 'tail', 'citing-works.json')
CSV_PATH = os.path.join(ROOT, 'harvest', 'curation-worklist.csv')
PATCHES = os.path.join(ROOT, 'harvest', 'patches', '*.jsonl')

LIST_FIELDS = {'sdv_component', 'use_case', 'industry'}
FIELDS = ['uses_sdv', 'integration', 'evidence', 'sdv_component', 'use_case',
          'industry', 'kind', 'summary', 'code_url', 'confidence', 'needs',
          'source_url']

VOCAB = {
    'integration': {'api_user', 'vendored_source', 'baseline_only',
                    'derivative_work', 'citation_only', 'unclear'},
    'confidence': {'high', 'medium', 'low'},
    'sdv_component': {'sdv', 'ctgan', 'rdt', 'sdmetrics', 'sdgym', 'copulas',
                      'deepecho', 'tgan', 'enterprise'},
    'use_case': {'privacy_protection', 'anonymization', 'data_sharing',
                 'software_testing', 'data_augmentation', 'class_imbalance',
                 'ml_training', 'benchmarking_evaluation', 'scenario_simulation',
                 'method_research', 'compliance', 'education'},
    'industry': {'healthcare_bio', 'finance_insurance', 'government_public',
                 'academia', 'energy_utilities', 'telecom', 'retail_ecommerce',
                 'transportation', 'manufacturing', 'software', 'cross_industry'},
    'kind': {'paper', 'preprint', 'thesis', 'blog_post', 'announcement',
             'case_study', 'news_article', 'documentation', 'code_repo',
             'tutorial', 'video', 'dataset_benchmark', 'forum'},
}


def short(work_id):
    return (work_id or '').rsplit('/', 1)[-1]


def as_list(value):
    if isinstance(value, list):
        return value
    return [v.strip() for v in str(value).split(';') if v.strip()]


def load_patches(errors):
    patches, seen = {}, {}
    for path in sorted(glob.glob(PATCHES)):
        name = os.path.basename(path)
        for lineno, line in enumerate(open(path), 1):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            where = f'{name}:{lineno}'
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f'{where}: bad JSON ({exc})')
                continue
            wid = short(rec.pop('openalex_id', ''))
            override = bool(rec.pop('override', False))
            if not wid:
                errors.append(f'{where}: missing openalex_id')
                continue
            clean = {}
            for field, value in rec.items():
                if field not in FIELDS:
                    errors.append(f'{where}: unknown field {field!r}')
                    continue
                if field in LIST_FIELDS:
                    value = as_list(value)
                    bad = set(value) - VOCAB[field]
                    if bad:
                        errors.append(f'{where}: {field} not in vocabulary: {sorted(bad)}')
                        continue
                elif field in VOCAB and value not in VOCAB[field]:
                    errors.append(f'{where}: {field}={value!r} not in vocabulary')
                    continue
                prior = seen.get((wid, field))
                if prior and prior[1] != value and not override:
                    errors.append(f'{where}: overwrites {wid}.{field} from {prior[0]}; '
                                  f'add "override": true if deliberate')
                seen[(wid, field)] = (where, value)
                clean[field] = value
            patches.setdefault(wid, {}).update(clean)
    return patches


def check_complete(wid, cur, errors):
    """A record claiming SDV use must carry the evidence for that claim."""
    if cur.get('uses_sdv') is not True:
        return
    for field in ('evidence', 'integration', 'summary', 'confidence'):
        if not cur.get(field):
            errors.append(f'{wid}: uses_sdv=true but {field} is empty')
    if cur.get('confidence') == 'high' and not cur.get('source_url'):
        errors.append(f'{wid}: confidence=high requires source_url (what you read)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='validate only')
    args = ap.parse_args()

    errors = []
    patches = load_patches(errors)
    works = json.load(open(WORKS))
    by_id = {short(w['id']): w for w in works}

    unknown = set(patches) - set(by_id)
    for wid in sorted(unknown):
        errors.append(f'{wid}: no such record in citing-works.json')

    applied = 0
    for wid, fields in patches.items():
        if wid not in by_id:
            continue
        cur = by_id[wid].setdefault('curation', {})
        cur.update(fields)
        check_complete(wid, cur, errors)
        applied += 1

    for line in errors:
        print(f'ERROR {line}', file=sys.stderr)
    if errors and args.check:
        return 1
    if args.check:
        print(f'{applied} records would be updated, no errors')
        return 0
    if errors:
        print('\nrefusing to write while errors remain', file=sys.stderr)
        return 1

    with open(WORKS, 'w') as fh:
        json.dump(works, fh, indent=1, ensure_ascii=False)

    rows = list(csv.DictReader(open(CSV_PATH, newline='', encoding='utf-8-sig')))
    for row in rows:
        cur = by_id.get(row['openalex_id'], {}).get('curation', {})
        for field in FIELDS:
            if field in cur:
                value = cur[field]
                row[field] = '; '.join(value) if isinstance(value, list) else \
                    ('' if value is None else str(value))
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    done = sum(1 for w in works if w.get('curation', {}).get('uses_sdv') is not None)
    uses = sum(1 for w in works if w.get('curation', {}).get('uses_sdv') is True)
    derived = sum(1 for w in works
                  if w.get('curation', {}).get('integration') == 'derivative_work')
    print(f'{applied} records patched; {done}/{len(works)} adjudicated; '
          f'{uses} use SDV; {derived} derivative works')
    return 0


if __name__ == '__main__':
    sys.exit(main())
