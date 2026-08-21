#!/usr/bin/env python3
"""Repair the rows paper_curate_nodoi.py sent to needs-review-nodoi.jsonl.

The companion has no --recover and no --retry. paper_curate's own two look their
rows up by DOI, and these works have none -- which is exactly why the companion
writes to a separate review file. So a held row has to be repaired by hand.

It must NOT be hand-written into records/. The validator is the only thing
standing between a bad record and a shard, and every failure it caught here was
real in shape even where the judgment was sound. This script instead applies a
NAMED patch to the stored `raw` response and hands the result back through
pc.write_result(), which re-parses, re-validates and finalizes precisely as the
live run does. paper_curate_nodoi is imported for its patched finalize and
pack_evidence, so a repaired record comes out identical in shape to the ones
that passed first time.

    python3 curate/repair_nodoi_review.py            # dry run, writes nothing
    python3 curate/repair_nodoi_review.py --write    # write records, rewrite review

Two things it reports that are worth reading even when everything passes:

  ORGANIZATIONS. tests/validate.py enforces ONE (type, country) per organization
  string across every record in every shard. That constraint is global and no
  single-record validator can see it -- it is what produced 115 failures on the
  papers batch. So every organization a patch introduces is looked up in the
  shards first: an existing spelling and its existing fact are printed, and a
  disagreement or a brand-new string is flagged before it can propagate.

  A NULL AFFILIATION TAKES EMPTY FACET LISTS. Both theses held here failed the
  same way: the model wrote affiliations [null] and still filled one facet value.
  A null names no organization, so affiliation_types and affiliation_countries
  must be [] -- not ["unknown"]. Either fill the affiliation or empty the facets;
  never leave a placeholder standing in for an organization that is not there.

Makes no API call and costs nothing.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_curate as pc
import paper_curate_nodoi as nodoi


# Each entry says WHY, because the reason is the part worth reading later.
#
# `set` replaces whole fields. `sub` edits one field in place as (field, old, new)
# and asserts the old text appears EXACTLY once, so a patch can never silently
# match nothing or match twice.
FIXES = {
    'thesis-augmenting-high-dimensional-deep-2018': {
        'why': "A thesis takes its degree-granting university from the repository "
               "holding it -- the batch-11 precedent (Bologna from amslaurea, "
               "Tampere from trepo). The landing page is urn.kb.se ... kth:diva, "
               "so this is KTH. NOT the GOGGLE case, where a Lirias deposit was "
               "refused as evidence: that was a conference paper archived by one "
               "author's institution, while a thesis is GRANTED by the repository's "
               "university. The model had written affiliations [null] with "
               "affiliation_types ['unknown'], which names zero organizations "
               "against one facet value and is what the validator caught.",
        'set': {'affiliations': ['KTH Royal Institute of Technology'],
                'affiliation_types': ['academic'],
                'affiliation_countries': ['Sweden']},
    },
    'thesis-generation-methods-multi-label-2020': {
        'why': "Same precedent, same failure shape: affiliations [null] with "
               "affiliation_types ['academic']. The landing page is "
               "resolver.tudelft.nl, so the degree is Delft's -- the record's own "
               "`needs` had already reached that conclusion and then failed to act "
               "on it.",
        'set': {'affiliations': ['Delft University of Technology'],
                'affiliation_types': ['academic'],
                'affiliation_countries': ['Netherlands']},
    },
    'paper-knowledge-discovery-mining-demographic-2018': {
        'why': "A VALIDATOR FALSE POSITIVE, not a bad record. The summary is "
               "complete and ends with a quoted phrase, so its last character is a "
               "closing quote and validate()'s endswith(('.','!','?')) test fails. "
               "The period moves outside the quote. Worth fixing in "
               "paper_curate.validate() itself -- strip trailing quotes and "
               "brackets before the test -- since any summary ending in a quotation "
               "will hit this.",
        'sub': [('summary', "bottleneck.'", "bottleneck'.")],
    },
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


def apply_fix(record, fix):
    """Mutate the parsed record. Raises rather than guessing on any mismatch."""
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
    for organization in organizations_of(record):
        known = facts.get(organization)
        index = organizations_of(record).index(organization)
        types = record.get('affiliation_types') or []
        countries = record.get('affiliation_countries') or []
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

    # The same three globals the companion's main() patches, for the same reason:
    # write_result resolves finalize, pack_evidence and REVIEW at call time.
    pc.finalize = nodoi.finalize
    pc.pack_evidence = nodoi.pack_evidence
    pc.REVIEW = nodoi.REVIEW

    if not os.path.exists(nodoi.REVIEW):
        return print(f'no {nodoi.REVIEW}; nothing held')
    with open(nodoi.REVIEW) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    vocab = pc.read_vocabularies()
    by_doi = {c['doi']: c for c in nodoi.load_candidates()}
    facts = shard_org_facts()
    print(f'{len(rows)} held row(s); {len(facts)} organizations known to the shards\n')

    remaining, written = [], 0
    for row in rows:
        print(f"  {row['id']}")
        for problem in row.get('problems') or []:
            print(f"        was: {problem}")

        candidate = by_doi.get(row.get('doi'))
        fix = FIXES.get(row.get('id'))
        if candidate is None:
            print('        SKIP: no longer a candidate -- curated by a later run')
            continue
        if candidate['id'] != row.get('id'):
            print(f"        HELD: id moved to {candidate['id']}; the fix names the "
                  'old one, so nothing is applied')
            remaining.append(row)
            continue
        if fix is None:
            print('        HELD: no fix defined for this row')
            remaining.append(row)
            continue

        try:
            record = apply_fix(pc.parse_record(row.get('raw')), fix)
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
            print('        would write '
                  f"{pc.slug_for_doi(candidate['doi'])}.json")
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

    with open(nodoi.REVIEW, 'w') as fh:
        for row in remaining:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'\n{written} written to {pc.RECORDS}, {len(remaining)} still held in '
          f'{nodoi.REVIEW}')


if __name__ == '__main__':
    main()
