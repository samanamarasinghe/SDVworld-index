#!/usr/bin/env python3
"""Patch staged records in curate/paper-shards/records/ before they are merged.

A staging record is not yet an index entry, so a correction made here costs
nothing: no correction shard, no edit to a committed file, no id already in
circulation. Once merge_paper_shards.py has run, the same fix needs a shard
edit and an override. This script exists to take that window.

It applies a NAMED patch to a record found by its current id, re-checks the
things that will otherwise fail later, and rewrites the file in the same shape
write_result() produced. Dry run by default.

    python3 curate/patch_staged_records.py            # show every patch
    python3 curate/patch_staged_records.py --write    # apply them

It also runs a KIND AUDIT over the no-DOI staging records and reports any whose
kind may be wrong. That audit is the reason this script exists: OpenAlex gave the
Bologna thesis `type: other` and a null date, so paper_curate's KIND_OF defaulted
it to `paper` and its id got no year. The no-DOI set is institutional-repository
deposits, where that shape is common -- a repository url under a record typed
`paper` is worth a look every time.
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_curate as pc
import repair_nodoi_review as repair


# `set` replaces named fields outright.
#
# `affiliation_all` is the common case and safer than writing the three lists by
# hand: it puts ONE organization on every author slot and derives the facet lists
# from it, so affiliations stays exactly as long as authors whatever the model
# wrote, and the (type, country) pair lands once, not once per author.
PATCHES = {
    'paper-anomaly-detection-railway-radio': {
        'why': "NOT A PAPER. OpenAlex carried type 'other' with a null date and a "
               "MALFORMED landing page -- the CDS9063 course-listing url with a "
               "stray '>' -- so KIND_OF defaulted the kind to paper and the id got "
               "no year. The real record is amslaurea eprint 37877: Riccardo Romeo, "
               "Laurea magistrale in Artificial Intelligence, discussed 6 February "
               "2026, supervisors Andrea Borghesi and Paolo Torroni. University of "
               "Bologna follows from the batch-11 thesis precedent -- a thesis takes "
               "its degree-granting university from the repository holding it -- and "
               "amslaurea is the repository that set that precedent.",
        'set': {'id': 'thesis-anomaly-detection-railway-radio-2026',
                'kind': 'thesis',
                'url': 'https://amslaurea.unibo.it/id/eprint/37877'},
        'affiliation_all': ('University of Bologna', 'academic', 'Italy'),
    },
    'preprint-establishing-fair-care-efficient': {
        'why': "The url was the openalex.org record pointer, which is not a source. "
               "OpenAlex has no DOI, no date and no landing page for this work; its "
               "source is RePEc, and the paper is hosted by Waterloo economics as an "
               "IARIW 2023 paper. Byline read off the PDF: Helen Chen, Maura R. "
               "Grossman, Anindya Sen and Shu-Feng Tsao, all University of Waterloo "
               "across three units (Public Health Sciences, Cheriton School of "
               "Computer Science, Economics) -- which under the organization-name-"
               "alone rule is ONE organization, not three. Its reference list carries "
               "Xu et al. 2019, consistent with the citation_only already recorded.",
        'set': {'id': 'preprint-establishing-fair-care-efficient-2023',
                'url': 'https://uwaterloo.ca/economics/sites/default/files/uploads/'
                       'documents/chen-fair-care-and-efficient-data-sharing-iariw-'
                       '2023-10.pdf'},
        'affiliation_all': ('University of Waterloo', 'academic', 'Canada'),
    },
}

# Hosts that serve institutional deposits. A record typed paper or preprint whose
# url sits on one of these is not necessarily wrong -- plenty of real papers are
# deposited -- but it is where the miscategorization above came from.
REPOSITORY_HINTS = ('amslaurea', 'diva-portal', 'urn.kb.se', 'hdl.handle.net',
                    'resolver.tudelft', 'scholarbank', 'orbilu', 'tubiblio',
                    'digitalcommons', 'eprints', 'dspace', 'theses')
THESIS_WORDS = ('thesis', 'dissertation', 'master', "master's", 'laurea', 'msc',
                'mphil', 'doctoral')


def load_staged():
    """(path, record) for every staging record, no-DOI ones marked."""
    out = []
    for path in sorted(glob.glob(os.path.join(pc.RECORDS, '*.json'))):
        with open(path, encoding='utf-8') as fh:
            out.append((path, json.load(fh)))
    return out


def apply_patch(record, patch):
    """Mutate in place; return the list of (field, before, after) changes."""
    changes = []
    for field, value in (patch.get('set') or {}).items():
        before = record.get(field)
        if before == value:
            continue
        record[field] = value
        changes.append((field, before, value))
    if patch.get('affiliation_all'):
        organization, kind, country = patch['affiliation_all']
        authors = record.get('authors') or []
        if not authors:
            raise ValueError('affiliation_all needs at least one author')
        new = {'affiliations': [organization] * len(authors),
               'affiliation_types': [kind],
               'affiliation_countries': [country]}
        for field, value in new.items():
            before = record.get(field)
            if before == value:
                continue
            record[field] = value
            changes.append((field, before, value))
    return changes


def check(record, taken_ids, facts):
    """Everything that would otherwise fail at merge or shard time."""
    problems = []
    authors = record.get('authors') or []
    affiliations = record.get('affiliations') or []
    if len(authors) != len(affiliations):
        problems.append(f'{len(authors)} authors but {len(affiliations)} affiliations')
    organizations = repair.organizations_of(record)
    for field in ('affiliation_types', 'affiliation_countries'):
        values = record.get(field) or []
        if len(values) != len(organizations):
            problems.append(f'{field} has {len(values)} values but affiliations '
                            f'names {len(organizations)} organization(s)')
    if record.get('id') in taken_ids:
        problems.append(f"id {record.get('id')!r} is already used in the index")
    for field in ('id', 'url', 'title', 'summary', 'kind'):
        if not (record.get(field) or '').strip():
            problems.append(f'{field} is empty')
    return problems


def audit_kinds(staged):
    """No-DOI records whose kind may be wrong. Reports; changes nothing."""
    flagged = []
    for path, record in staged:
        if not os.path.basename(path).startswith('openalex_'):
            continue                       # DOI-keyed records are not this lane
        url = (record.get('url') or '').lower()
        blob = ' '.join(str(record.get(f) or '') for f in ('title', 'summary'))
        if record.get('kind') == 'thesis':
            continue
        reasons = []
        if any(hint in url for hint in REPOSITORY_HINTS):
            reasons.append('repository url')
        if any(word in blob.lower() for word in THESIS_WORDS):
            reasons.append('thesis wording in title/summary')
        if reasons:
            flagged.append((record.get('id'), record.get('kind'), url,
                            ' + '.join(reasons)))
    return flagged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='apply the patches')
    args = parser.parse_args()

    staged = load_staged()
    by_id = {r.get('id'): (p, r) for p, r in staged}
    print(f'{len(staged)} staging records')

    # existing_ids() reads the built index AND every shard, so an id retired by a
    # correction still counts as taken. The record's own current id is removed,
    # or a patch that leaves the id alone would flag itself.
    taken = pc.existing_ids()
    facts = repair.shard_org_facts()

    changed_paths = []
    for entry_id, patch in PATCHES.items():
        print(f'\n  {entry_id}')
        if entry_id not in by_id:
            print('        SKIP: no staged record carries this id')
            continue
        path, record = by_id[entry_id]
        print(f'        file: {os.path.basename(path)}')
        print(f"        why: {patch['why']}")
        try:
            changes = apply_patch(record, patch)
        except Exception as exc:
            print(f'        FAILED: {type(exc).__name__}: {exc}')
            continue
        if not changes:
            print('        nothing to change; already patched')
            continue
        for field, before, after in changes:
            print(f'        {field}:')
            print(f'            was {before!r}')
            print(f'            now {after!r}')
        repair.report_organizations(record, facts)
        problems = check(record, taken - {entry_id}, facts)
        if problems:
            for problem in problems:
                print(f'        PROBLEM: {problem}')
            print('        NOT WRITTEN')
            continue
        changed_paths.append((path, record))
        print('        checks clean')

    flagged = audit_kinds(staged)
    print(f'\nKIND AUDIT over the no-DOI records: {len(flagged)} to eyeball')
    for entry_id, kind, url, reason in flagged:
        print(f'    {kind:9s} {entry_id}')
        print(f'              {url}')
        print(f'              flagged by: {reason}')
    if not flagged:
        print('    none -- every no-DOI record typed paper or preprint sits on a '
              'non-repository url')

    if not args.write:
        print(f'\ndry run; {len(changed_paths)} record(s) would be rewritten. '
              'Re-run with --write')
        return
    for path, record in changed_paths:
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(record, fh, indent=1, ensure_ascii=False)
    print(f'\n{len(changed_paths)} record(s) rewritten in {pc.RECORDS}')


if __name__ == '__main__':
    main()
