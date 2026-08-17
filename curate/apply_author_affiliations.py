#!/usr/bin/env python3
"""Apply curated author and affiliation lists to base shard records.

Four fields are GENERATED rather than authored: ``authors``, ``affiliations``,
``affiliation_types`` and ``affiliation_countries``.  Their source of truth for
repository entries is ``data/github-repo-author-overrides.json``; this script copies
that into the shards and derives the two facet lists with the same classifier
``curate/affiliation_facets.py`` already uses, so one rule decides every record.

Two files feed it: ``data/github-repo-author-overrides.json`` for repository contributors
harvested from GitHub, and ``data/curated-author-affiliations.json`` for hand-curated
writings, papers and theses.  The affiliation recorded is the organization through which
that author did THIS work, not their current employer.

Judgment stays append-only.  A wrong importance, integration, summary, url or facet
is still fixed by a correction shard in a later file -- this script refuses to write
if any non-generated field would differ, so it cannot become a back door for that.

Author order follows the override file, which lists contributors by commit count.
Rows carrying ``account_type`` of service_account or bot stay in the override file as
a record but are kept out of the author list, so that choice is reversible without
re-harvesting.  A name a shard already carries is never dropped.

Run without --write to report what would change.  Then::

    python3 curate/apply_author_affiliations.py --write
    python3 build.py --write
    python3 tests/validate.py

A second --write run must report zero changes; that is the idempotence check.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import affiliation_facets as facets

ROOT = facets.ROOT
SHARDS = facets.SHARDS

# Hand curation arrives in batches, so the curated series is globbed rather than listed:
# data/curated-author-affiliations.json, then -002, -003 ... Each batch is a small file
# that can be reviewed on its own, and no batch rewrites the ones before it.
OVERRIDE_FILES = ("data/github-repo-author-overrides.json",) + tuple(
    os.path.relpath(path, ROOT)
    for path in sorted(glob.glob(os.path.join(ROOT, "data",
                                              "curated-author-affiliations*.json")))
)

GENERATED = ("authors", "affiliations", "affiliation_types", "affiliation_countries")

# The override file names each organization's sector in the UI vocabulary, while
# affiliation_facets classifies from the raw ROR/OpenAlex tokens.  Translate on the way
# in rather than special-casing the classifier, so a curated organization and a
# harvested one are decided by the same code path.
TYPE_TOKENS = {
    "corporate": "company",
    "academic": "education",
    "government": "government",
    "nonprofit": "nonprofit",
    "other": "other",
}

SKIP_ACCOUNTS = {"service_account", "bot"}


def load_overrides():
    """Merge every override file. A later file wins on a repeated entry id."""
    organizations, entries = {}, {}
    for relative in OVERRIDE_FILES:
        data = facets.load(relative, {})
        organizations.update(data.get("organizations", {}))
        entries.update(data.get("entries", {}))
    return organizations, entries


def extend_evidence(evidence, organizations):
    """Feed curated organizations into the classifier's evidence table."""
    for name, meta in organizations.items():
        sector = meta.get("organization_type")
        facets.add_evidence(evidence, name, TYPE_TOKENS.get(sector, sector),
                            meta.get("country"))


def author_lists(rows):
    """Positionally aligned author and affiliation lists, in override order."""
    authors, affiliations = [], []
    for row in rows:
        if row.get("account_type") in SKIP_ACCOUNTS:
            continue
        name = row.get("name") or row.get("github_login")
        if not name:
            continue
        authors.append(name)
        affiliations.append(row.get("affiliation"))
    return authors, affiliations


def merge_existing(record, authors, affiliations):
    """Never drop a name a shard already carries, and never blank a known affiliation.

    The REST contributors endpoint and the GraphQL pass that built the pools disagree:
    ASyH and ctgan-tf already record people the endpoint does not return, including a
    repository owner whose commits carry an unlinked email.  A curated name outranks a
    fresh harvest, so anything already present is kept -- matched by name, appended in
    its old order if the override list does not mention it.
    """
    old_authors = record.get("authors") or []
    old_affiliations = record.get("affiliations") or []
    old = {}
    for index, name in enumerate(old_authors):
        old.setdefault(name, old_affiliations[index]
                       if index < len(old_affiliations) else None)
    for index, name in enumerate(authors):
        if affiliations[index] is None and old.get(name):
            affiliations[index] = old[name]
    known = set(authors)
    for name in old_authors:
        if name in known:
            continue
        known.add(name)
        authors.append(name)
        affiliations.append(old.get(name))
    return authors, affiliations


def place(record, fields):
    """Set the four generated fields, keeping the record's key order stable.

    The block lands where the first generated key already sits, so a re-run cannot
    reshuffle a shard.  For a record that carries none of them, it goes after ``year``
    to match the order the other shards use.
    """
    has_generated = any(key in record for key in GENERATED)
    anchor = None if has_generated else ("year" if "year" in record else None)
    out, inserted = {}, False
    for key, value in record.items():
        if key in GENERATED:
            if not inserted:
                out.update(fields)
                inserted = True
            continue
        out[key] = value
        if key == anchor and not inserted:
            out.update(fields)
            inserted = True
    if not inserted:
        out.update(fields)
    return out


def main(write=False, only=None):
    organizations, entries = load_overrides()
    if not entries:
        raise SystemExit("ERROR: no entries found in " + ", ".join(OVERRIDE_FILES))
    evidence = facets.build_evidence()
    extend_evidence(evidence, organizations)

    seen = set()
    changed_files = changed_records = 0
    author_slots = affiliation_slots = 0
    report = []

    for path in sorted(glob.glob(SHARDS)):
        if only and only not in os.path.basename(path):
            continue
        indent = facets.file_indent(path)
        records = facets.load(os.path.relpath(path, ROOT), [])
        updated, file_changed = [], False
        for record in records:
            rows = entries.get(record.get("id"))
            # Corrections are left alone: an empty field on an override would blank the
            # base record's value when build.py merges the shards.
            if record.get("override") or not rows:
                updated.append(record)
                continue
            seen.add(record["id"])

            authors, affiliations = merge_existing(record, *author_lists(rows))
            types, countries = facets.classify_record({"affiliations": affiliations},
                                                      evidence)
            revised = place(record, {"authors": authors,
                                     "affiliations": affiliations,
                                     "affiliation_types": types,
                                     "affiliation_countries": countries})

            if len(revised["affiliations"]) != len(revised["authors"]):
                raise SystemExit(f'ERROR: {record["id"]} affiliations and authors '
                                 'would not align')
            before = {k: v for k, v in record.items() if k not in GENERATED}
            after = {k: v for k, v in revised.items() if k not in GENERATED}
            if before != after:
                raise SystemExit(f'ERROR: {record["id"]} would change a field this '
                                 'script does not own; refusing to write')

            if revised != record:
                changed_records += 1
                file_changed = True
                author_slots += len(authors) - len(record.get("authors") or [])
                affiliation_slots += (sum(1 for a in affiliations if a)
                                      - sum(1 for a in (record.get("affiliations") or [])
                                            if a))
                report.append((os.path.basename(path), record["id"],
                               len(record.get("authors") or []), len(authors),
                               sum(1 for a in affiliations if a),
                               sorted(set(t for t in types))))
            updated.append(revised)
        if file_changed:
            changed_files += 1
            if write:
                facets.write_json(path, updated, indent)

    for shard, entry_id, was, now, resolved, types in report:
        print(f'{shard:38s} {entry_id:38s} authors {was:3d} -> {now:3d}, '
              f'{resolved:3d} with affiliation, types {",".join(types) or "-"}')

    action = "updated" if write else "would update"
    print(f'\n{action} {changed_records} base record(s) in {changed_files} shard file(s)')
    print(f'author slots {author_slots:+d}, resolved affiliation slots '
          f'{affiliation_slots:+d}')

    orphans = sorted(set(entries) - seen)
    if orphans:
        # Silently dropping these is how a curated list gets lost: the id is wrong, or
        # the entry was retired as a duplicate.
        print(f'WARNING: {len(orphans)} override id(s) matched no base record: '
              + ', '.join(orphans))
    return 1 if changed_records and not write else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="update the shards; omit to report drift only")
    parser.add_argument("--only", metavar="SUBSTRING",
                        help="restrict to shard files whose name contains SUBSTRING, "
                             "for reviewing one file at a time")
    args = parser.parse_args()
    raise SystemExit(main(**vars(args)))
