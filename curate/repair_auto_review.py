#!/usr/bin/env python3
"""Salvage and repair the last rows in curate/auto-shards/needs-review.jsonl.

`--recover` re-validates a stored response AS IT STANDS and promotes what passes.
It deliberately edits nothing, which is right for a rule that was too strict and
useless for a response that is merely malformed. After the last --recover the file
held 14 rows and promoted zero. Those 14 are **7 repos, each attempted twice**, and
they are the whole of what the repository lane never finished.

Two mechanisms here, and the first matters more than the second.

SALVAGE, which needs no judgment at all. Five rows were logged as JSONDecodeErrors
and none of them is truncated -- every raw ends in a proper brace. Two mechanical
causes:

  * `"confidence":high` -- the value written as a bare word rather than a string.
  * SEVERAL complete JSON objects in one response. `parse_record` spans from the
    first `{` to the LAST `}`, so it hands json.loads every object plus the gaps
    between them.

For the second case the right object is NOT reliably the first: GuardDog's response
is a partial object followed by a complete one, so a first-object rule picks the
one missing `confidence`. Every balanced object is therefore tried and the first
that VALIDATES wins. Nothing skips the validator.

FIXES, for rows that are genuinely wrong. Each is a named patch with its reason.

WHAT CANNOT BE FIXED HERE: importance 6. It is reserved for first-party SDV-project
work, the prompt withholds it from the model, and validate() rejects it -- so a
first-party repo cannot be staged at 6 by any means. The established route is his
own from shard 120, where two importance-6 lifts were applied as POST-MERGE
OVERRIDES in a correction shard. datacebo-guides takes the same route: staged
honestly here, lifted after the merge.

    python3 curate/repair_auto_review.py            # dry run
    python3 curate/repair_auto_review.py --write    # write records, rewrite review

The review file ACCUMULATES across runs -- that is how 14 real rows hid inside 56 --
so --write rewrites it deduplicated, carrying only repos that are still unresolved.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_curate as ac


BARE_WORD = re.compile(r'("(?:confidence|integration|kind)"\s*:\s*)'
                       r'(high|medium|low|[a-z_]+)(\s*[,}])')

FIXES = {
    'IraitzTB/DSPT2025-ML': {
        'why': "affiliation_type 'education_sector' is not in the vocabulary -- that "
               "value belongs to `industry`, where the record already uses it "
               "correctly. THE BRIDGE SCHOOL IS THE ONE JUDGMENT CALL IN THIS FILE: "
               "it is a private Spanish tech bootcamp, so `academic` (an educational "
               "institution) and `corporate` (a company selling courses) are both "
               "arguable. Taking academic, because the field describes what kind of "
               "institution it is and a school is a school. Flagged for his override.",
        'set': {'affiliation_types': ['academic']},
    },
    'daemonX10/Notes': {
        'why': "sdv_component empty on a citation_only record. His standing ruling: a "
               "repo that only DECLARES SDV keeps `sdv_component: [sdv]` -- the "
               "component records that the family is present, not that a synthesizer "
               "ran. Using the family marker rather than [ctgan], because claiming "
               "ctgan would assert an import this study-notes repo does not have.",
        'set': {'sdv_component': ['sdv']},
    },
    'mohitsharma29/comparision_data_bias_fairness': {
        'why': "affiliation_countries carried three values for two distinct "
               "organizations. affiliations reads [IIIT Delhi, Microsoft Research, "
               "IIIT Delhi] -- three AUTHOR slots naming TWO organizations -- and the "
               "model wrote one country per author instead of one per organization. "
               "affiliation_types already has it right at two.",
        'set': {'affiliation_countries': ['India', 'United States']},
    },
    'datacebo/datacebo-guides': {
        'why': "FIRST-PARTY. He has ruled importance 6 for it, alongside "
               "repo-datacebo-cookbook and repo-sdvworld-index -- but 6 CANNOT BE SET "
               "HERE: validate() caps importance at 5 because 6 is reserved and the "
               "prompt withholds it from the model. So this patch fixes only what it "
               "can (the empty component) and the importance-6 lift goes in a "
               "correction shard after the merge, exactly as shard 120 did for the "
               "other two. Integration is DELIBERATELY left `unclear` with a needs "
               "rather than promoted to api_user: 274 commits of DataCebo's own guides "
               "almost certainly run the library, but the evidence in hand does not "
               "say so. THIS ENTRY DESERVES A HAND-WRITTEN SUMMARY -- treat the patch "
               "as a floor.",
        'set': {'sdv_component': ['sdv']},
        'needs': ('First-party DataCebo repository. AWAITING AN IMPORTANCE-6 LIFT in a '
                  'correction shard, per his ruling; it cannot be staged at 6. '
                  'Integration left unclear: the harvested evidence shows no call '
                  'site. Worth reading the guides directly and rewriting by hand.'),
    },
}


def objects(text):
    """Every BALANCED {...} in the text, in order, respecting strings and escapes.

    parse_record spans first-brace to last-brace, which is right for one object with
    trailing prose and wrong for several -- it swallows them all and the gaps. And
    the FIRST object is not reliably the good one, so yield them all and let the
    caller validate.
    """
    depth = start = -1
    in_string = escaped = False
    for i, ch in enumerate(text or ''):
        if in_string:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            if depth <= 0:
                depth, start = 0, i
            depth += 1
        elif ch == '}' and depth > 0:
            depth -= 1
            if depth == 0:
                yield text[start:i + 1]


def candidates(raw):
    """(record, note) for everything parseable in the response, best-effort."""
    out = []
    try:
        out.append((ac.parse_record(raw), 'parsed as-is'))
    except Exception:
        pass
    for n, text in enumerate(objects(raw or ''), 1):
        try:
            out.append((json.loads(text), f'object {n} of the response'))
            continue
        except Exception:
            pass
        quoted = BARE_WORD.sub(lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)}',
                               text)
        if quoted != text:
            try:
                out.append((json.loads(quoted),
                            f'object {n}, quoted a bare word value'))
            except Exception:
                pass
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(ac.REVIEW):
        return print('no review file')
    with open(ac.REVIEW) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    vocab = ac.read_vocabularies()
    repos = {r.get('repo') for r in rows}
    print(f'{len(rows)} row(s) over {len(repos)} repo(s)\n')

    resolved, failures = {}, {}
    for row in rows:
        repo, entry_id = row.get('repo'), row.get('id')
        if repo in resolved:
            continue                       # an earlier attempt already worked
        print(f'  {repo}  ({entry_id})')
        for problem in row.get('problems') or []:
            print(f'        was: {problem}')

        fix = FIXES.get(repo)
        if fix:
            print(f"        why: {fix['why']}")

        found, last = None, []
        for record, note in candidates(row.get('raw')):
            if fix:
                for field, value in (fix.get('set') or {}).items():
                    record[field] = value
                if fix.get('needs'):
                    record['needs'] = fix['needs']
            problems = ac.validate(record, repo, entry_id, vocab)
            if not problems:
                found = (record, note)
                break
            last = problems
        if found is None:
            if not last:
                print('        HELD: nothing parseable in the response')
            for problem in last:
                print(f'        STILL FAILING: {problem}')
            failures.setdefault(repo, row)
            continue

        record, note = found
        print(f'        salvage: {note}')
        if fix:
            for field, value in (fix.get('set') or {}).items():
                print(f'        {field} -> {value!r}')
        print(f"        clean -> {record.get('integration')} "
              f"importance {record.get('importance')}")
        resolved[repo] = (entry_id, record)

    # A repo resolved by a later attempt is NOT a failure, whatever an earlier row
    # did. Without this the rewritten review file keeps a row for a repo that was
    # written to records/ in the same run.
    for repo in resolved:
        failures.pop(repo, None)

    print(f'\n{len(resolved)} repo(s) repaired, {len(failures)} still failing')
    if not args.write:
        return print('dry run; nothing written. Re-run with --write')

    for repo, (entry_id, record) in resolved.items():
        # Validation has already passed, so write_result cannot append this row
        # back into the review file while we are rewriting it below.
        if ac.write_result(repo, entry_id, json.dumps(record, ensure_ascii=False),
                           vocab):
            print(f'  wrote {repo}')
    with open(ac.REVIEW, 'w') as fh:
        for repo, row in failures.items():
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'\n{len(resolved)} written to {ac.RECORDS}; review file rewritten '
          f'deduplicated with {len(failures)} row(s)')


if __name__ == '__main__':
    main()
