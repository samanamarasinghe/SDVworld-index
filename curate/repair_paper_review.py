#!/usr/bin/env python3
"""Repair the rows paper_curate.py left in curate/paper-shards/needs-review.jsonl.

Five rows survived two --retry passes and were dropped by ruling at 99.8%. Read
against their stored raws they are not five failures but four bookkeeping slips
and one dead response, so four of them can be recovered with no API call at all.

The rows are NOT hand-written into records/. The validator is the only thing
between a bad record and a shard, and every problem it caught here was real in
shape. This script applies a NAMED patch and hands the result back through
pc.write_result(), which re-parses, re-validates and finalizes exactly as the
live run does.

    python3 curate/repair_paper_review.py            # dry run, writes nothing
    python3 curate/repair_paper_review.py --write    # write records, rewrite review

DO NOT import repair_nodoi_review to reuse its helpers. That module imports
paper_curate_nodoi, which monkey-patches paper_curate's finalize and REVIEW at
import time -- on this DOI-keyed lane that would strip the DOI off every record
and write to the wrong review file. organizations_of() and shard_org_facts() are
copied here for that reason, not by oversight.

Two things it reports that are worth reading even when everything passes:

  ORGANIZATIONS. tests/validate.py enforces ONE (type, country) per organization
  string across every record in every shard. That constraint is global and no
  single-record validator can see it -- it is what produced 115 failures on this
  batch. Every organization a patch introduces is looked up in the shards first.

  THE TIER IS RECOMPUTED AT REPAIR TIME. load_candidates() derives the evidence
  tier from what is in harvest/papers/ now, so a paper whose full text landed
  since the batch is finalized under the new tier and a looser confidence cap.
  That is the intended re-judge behaviour, but it means a repaired record can
  differ from what the same raw would have produced in August.

Makes no API call and costs nothing.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_curate as pc


# Keyed by DOI, lowercased. Each entry says WHY, because the reason is the part
# worth reading later.
#
# `raw_sub` edits the stored response BEFORE parsing, for a raw that is not valid
# JSON. `set` replaces whole fields. `sub` edits one field in place. Both text
# operations assert the old text appears EXACTLY once, so a patch can never
# silently match nothing or match twice.
#
# `affiliations_first_comma` truncates every affiliation at its first comma. It
# exists so this file can stay ASCII: writing the corrected strings out by hand
# would put accented characters into a script, and the repo's push discipline
# checks for exactly that.
FIXES = {
    '10.2196/16492': {
        'why': "affiliation_type 'healthcare_bio' is an INDUSTRY value written into "
               "the wrong field -- the same slip as the repo lane's "
               "'education_sector', and evidence the vocabulary confusion is "
               "positional rather than semantic. The record names three "
               "organizations (Rambam Health Care Campus, University of Haifa, "
               "Technion) against two facet values. Rambam is a hospital, and "
               "docs/schema.md is explicit that hospitals are nonprofit, university "
               "and government ones included, so no judgment is needed here.",
        'set': {'affiliation_types': ['nonprofit', 'academic', 'academic'],
                'affiliation_countries': ['Israel', 'Israel', 'Israel']},
    },
    '10.7554/elife.88117': {
        'why': "A compound 'academic; academic' in slot 4. The fourth organization "
               "is Samsung Medical Center, reached through an author affiliated to "
               "both Sungkyunkwan University and the hospital; the model joined the "
               "two types into one slot instead of giving the hospital its own. "
               "Hospitals are nonprofit per docs/schema.md. Slots 1-3 and all four "
               "countries were already correct, so only the type list moves.",
        'set': {'affiliation_types': ['academic', 'academic', 'academic', 'nonprofit']},
    },
    '10.48550/arxiv.2601.11444': {
        'why': "NOT a facet bug. Four authors sit at the same university, but their "
               "affiliation strings carry different lab suffixes (', Inria, CNRS, "
               "I3S, Maasai' against ', LJAD, Maasai'), so the ';'-split counts one "
               "university as two organizations and the two facet values fall short "
               "of three. This is the pilot-2 organisation-name-alone rule failing "
               "at scale: the fix is to the affiliation STRINGS, not to the facet "
               "lists, which already read correctly once the count is right.",
        'affiliations_first_comma': True,
    },
    '10.3390/su14159056': {
        'why': "A FAILURE SHAPE NOT SEEN BEFORE: the response is not truncated, it "
               "contains a Python expression. The model noticed 'real_estate' was "
               "absent from the vocabulary and wrote "
               "\"real_estate\".replace(\"real_estate\",\"retail_ecommerce\") into "
               "the JSON, which is the JSONDecodeError at char 996. Its substitute "
               "was wrong anyway -- house prices are not retail e-commerce -- and "
               "Saman ruled 2026-08-21 to add real_estate to docs/schema.md instead, "
               "under the schema's own rule that a proposed value is added in the "
               "commit that first uses it. So the expression collapses to the value "
               "it was written around.",
        'raw_sub': [('"real_estate".replace("real_estate","retail_ecommerce")',
                     '"real_estate"')],
    },
    # 10.1101/2024.01.06.23300659 is deliberately absent. Its stored raw is EMPTY
    # -- all 10,000 output tokens went to thinking -- so there is nothing to patch
    # and no rule change can reach it. It stays in the review file for
    # `paper_curate.py --retry`, which is the only thing that can move it.
}


def organizations_of(record):
    """The distinct organizations a record names, in first-appearance order.

    The same split paper_curate.validate() and tests/validate.py both use: an
    affiliation element may carry several organizations joined by ';'.
    """
    found, seen = [], set()
    for affiliation in record.get('affiliations') or []:
        if not affiliation or not isinstance(affiliation, str):
            continue
        for organization in (part.strip() for part in affiliation.split(';')):
            if organization and organization not in seen:
                seen.add(organization)
                found.append(organization)
    return found


def shard_org_facts():
    """organization string -> the set of (type, country) pairs the shards give it.

    A set rather than a value on purpose: if an organization already carries two
    facts the shards are themselves inconsistent, and that is worth seeing before
    adding a third record to the pile.
    """
    facts = {}
    for path in sorted(glob.glob(os.path.join(pc.SHARDS, '*.json'))):
        try:
            records = json.load(open(path))
        except ValueError:
            continue
        if isinstance(records, dict):
            records = records.get('entries', records.get('records', []))
        for record in records or []:
            if not isinstance(record, dict):
                continue
            organizations = organizations_of(record)
            types = record.get('affiliation_types') or []
            countries = record.get('affiliation_countries') or []
            if not organizations or len(types) != len(organizations):
                continue
            if len(countries) != len(organizations):
                continue
            for organization, kind, country in zip(organizations, types, countries):
                facts.setdefault(organization, set()).add((kind, country))
    return facts


def apply_raw(raw, fix):
    """Edit the stored response before it is parsed. Raises on any mismatch."""
    for old, new in (fix.get('raw_sub') or []):
        if raw.count(old) != 1:
            raise ValueError(f'raw: {old!r} appears {raw.count(old)} times, '
                             f'expected exactly once')
        raw = raw.replace(old, new)
    return raw


def apply_fix(record, fix):
    """Mutate the parsed record. Raises rather than guessing on any mismatch."""
    if fix.get('affiliations_first_comma'):
        record['affiliations'] = [
            affiliation.split(',')[0].strip() if isinstance(affiliation, str)
            else affiliation
            for affiliation in (record.get('affiliations') or [])]
    for field, value in (fix.get('set') or {}).items():
        record[field] = value
    for field, old, new in (fix.get('sub') or []):
        text = record.get(field)
        if not isinstance(text, str):
            raise ValueError(f'{field} is not a string, cannot substitute')
        if text.count(old) != 1:
            raise ValueError(f'{field}: {old!r} appears {text.count(old)} times, '
                             f'expected exactly once')
        record[field] = text.replace(old, new)
    return record


def report_organizations(record, facts):
    """Print what each organization this record names is already worth elsewhere."""
    organizations = organizations_of(record)
    types = record.get('affiliation_types') or []
    countries = record.get('affiliation_countries') or []
    for index, organization in enumerate(organizations):
        known = facts.get(organization)
        mine = (types[index] if index < len(types) else None,
                countries[index] if index < len(countries) else None)
        if not known:
            print(f'        NEW ORGANIZATION  {organization!r} -> {mine}')
            print('                          no shard names it; nothing to conflict '
                  'with, but check the spelling against near neighbours')
        elif mine in known:
            print(f'        matches shards    {organization!r} -> {mine}')
        else:
            print(f'        CONFLICT          {organization!r} -> {mine}')
            print(f'                          the shards already say {sorted(known)}; '
                  'validate.py will fail on this')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true',
                        help='write the repaired records and rewrite the review file')
    args = parser.parse_args()

    if not os.path.exists(pc.REVIEW):
        return print(f'no {pc.REVIEW}; nothing held')
    with open(pc.REVIEW) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    vocab = pc.read_vocabularies()
    if 'real_estate' not in (vocab.get('industry') or []):
        print('WARNING: real_estate is not in docs/schema.md yet, so the '
              'su14159056 repair will fail validation. Add it first.\n')
    by_doi = {c['doi'].lower(): c for c in pc.load_candidates()}
    facts = shard_org_facts()
    print(f'{len(rows)} held row(s); {len(facts)} organizations known to the shards\n')

    remaining, written = [], 0
    for row in rows:
        doi = (row.get('doi') or '').lower()
        print(f"  {row.get('id')}  [{doi}]")
        for problem in row.get('problems') or []:
            print(f'        was: {problem}')

        candidate = by_doi.get(doi)
        fix = FIXES.get(doi)
        if candidate is None:
            print('        SKIP: no longer a candidate -- curated by a later run')
            continue
        if fix is None:
            print('        HELD: no fix defined for this row')
            remaining.append(row)
            continue

        try:
            record = apply_fix(pc.parse_record(apply_raw(row.get('raw') or '', fix)),
                               fix)
        except Exception as exc:
            print(f'        HELD: {type(exc).__name__}: {exc}')
            remaining.append(row)
            continue

        print(f"        why: {fix['why']}")
        report_organizations(record, facts)
        problems = pc.validate(record, candidate, vocab)
        if problems:
            for problem in problems:
                print(f'        STILL FAILING: {problem}')
            remaining.append(row)
            continue

        if not args.write:
            print(f"        would write {pc.slug_for_doi(candidate['doi'])}.json")
            continue
        # Validation has already passed, so write_result cannot append this row
        # back into the review file -- which is what lets the rewrite below be a
        # plain filter rather than a rename-and-rebuild dance.
        if pc.write_result(candidate, json.dumps(record, ensure_ascii=False), vocab):
            written += 1
            print(f"        wrote {pc.slug_for_doi(candidate['doi'])}.json")
        else:
            print('        HELD: write_result rejected it after all')
            remaining.append(row)

    if not args.write:
        return print(f'\ndry run; {len(rows) - len(remaining)} row(s) would be '
                     'repaired. Re-run with --write')

    with open(pc.REVIEW, 'w') as fh:
        for row in remaining:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'\n{written} written to {pc.RECORDS}, {len(remaining)} still held in '
          f'{pc.REVIEW}')


if __name__ == '__main__':
    main()
