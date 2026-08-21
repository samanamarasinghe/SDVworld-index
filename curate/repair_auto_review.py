#!/usr/bin/env python3
"""Salvage and repair the last rows in curate/auto-shards/needs-review.jsonl.

`--recover` re-validates a stored response AS IT STANDS and promotes what passes.
It deliberately edits nothing, which is right for a rule that was too strict and
useless for a response that is merely malformed. After the last --recover the file
held 14 rows and promoted zero. Those 14 are **7 repos, each attempted twice**, and
they are the whole of what the repository lane never finished.

Two mechanisms here, and the first matters more than the second.

SALVAGE, which needs no judgment at all. Five of the rows were logged as
JSONDecodeErrors and none of them is truncated -- every raw ends in a proper brace.
They fail for two mechanical reasons:

  * `"confidence":high` -- the value written as a bare word rather than a string.
  * TWO complete JSON objects concatenated in one response. `parse_record` spans
    from the first `{` to the LAST `}`, so it hands json.loads both objects plus
    whatever sits between them. Reading the FIRST BALANCED object instead recovers
    a perfectly good record.

Neither is a judgment failure, so neither should cost an API call. Anything salvage
recovers is then put through the ordinary validator; nothing skips it.

FIXES, for the rows that are genuinely wrong. Each is a named patch with its
reason. There are four, and only one of them is a judgment call rather than a
mechanical correction -- see THE BRIDGE SCHOOL below.

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
        'why': "FIRST-PARTY, and he has already ruled it: importance 6, alongside "
               "repo-datacebo-cookbook and repo-sdvworld-index. The model saw thin "
               "evidence and returned importance 1 with an empty component. Setting "
               "importance to his ruling and the component to the family marker, but "
               "DELIBERATELY LEAVING integration `unclear` with a needs rather than "
               "promoting it to api_user: 274 commits of DataCebo's own guides almost "
               "certainly run the library, but the evidence in hand does not say so, "
               "and a confident wrong record is worse than a flagged one. THIS ENTRY "
               "DESERVES A HAND-WRITTEN SUMMARY -- treat this patch as a floor.",
        'set': {'sdv_component': ['sdv'], 'importance': 6},
        'needs': ('First-party DataCebo repository indexed at importance 6 by ruling. '
                  'Integration left unclear: the harvested evidence does not show a '
                  'call site. Worth reading the guides directly and rewriting this '
                  'record by hand.'),
    },
}


def first_object(text):
    """The first BALANCED {...} in the text, respecting strings and escapes.

    parse_record spans first-brace to last-brace, which is correct for one object
    with trailing prose and wrong for two objects -- it swallows both and the gap.
    """
    start = text.find('{')
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
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
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def salvage(raw):
    """(record, note). Raises nothing the caller cannot report."""
    try:
        return ac.parse_record(raw), 'parsed as-is'
    except Exception:
        pass
    notes = []
    text = first_object(raw or '')
    if text is None:
        raise ValueError('no balanced JSON object in the response')
    if text != (raw or '').strip():
        notes.append('took the first balanced object')
    try:
        return json.loads(text), '; '.join(notes) or 'reparsed'
    except Exception:
        pass
    quoted = BARE_WORD.sub(lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)}', text)
    if quoted != text:
        notes.append('quoted a bare word value')
    return json.loads(quoted), '; '.join(notes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(ac.REVIEW):
        return print('no review file')
    with open(ac.REVIEW) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    vocab = ac.read_vocabularies()
    print(f'{len(rows)} row(s) over '
          f'{len({r.get("repo") for r in rows})} repo(s)\n')

    resolved, failures = {}, {}
    for row in rows:
        repo, entry_id = row.get('repo'), row.get('id')
        if repo in resolved:
            continue                       # a better attempt already worked
        print(f'  {repo}  ({entry_id})')
        for problem in row.get('problems') or []:
            print(f'        was: {problem}')
        try:
            record, note = salvage(row.get('raw'))
            print(f'        salvage: {note}')
        except Exception as exc:
            print(f'        HELD: {type(exc).__name__}: {exc}')
            failures.setdefault(repo, []).append(row)
            continue

        fix = FIXES.get(repo)
        if fix:
            print(f"        why: {fix['why']}")
            for field, value in (fix.get('set') or {}).items():
                print(f'        {field}: {record.get(field)!r} -> {value!r}')
                record[field] = value
            if fix.get('needs'):
                record['needs'] = fix['needs']

        problems = ac.validate(record, repo, entry_id, vocab)
        if problems:
            for problem in problems:
                print(f'        STILL FAILING: {problem}')
            failures.setdefault(repo, []).append(row)
            continue
        print(f"        clean -> {record.get('integration')} "
              f"importance {record.get('importance')}")
        resolved[repo] = (entry_id, record)

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
        for repo, held in failures.items():
            fh.write(json.dumps(held[0], ensure_ascii=False) + '\n')
    print(f'\n{len(resolved)} written to {ac.RECORDS}; review file rewritten '
          f'deduplicated with {len(failures)} row(s)')


if __name__ == '__main__':
    main()
