# Stage 2b brief — postings and the search change

Design: `sdvworld-perf-design-v2.md` §4, §9. Preconditions: 2a green
(`handoff-stage2a.md`). Branch: `v2-perf`. Constitution: `CLAUDE.md`.

The one planned semantic change in the redesign, kept apart from the data-format
change so that a difference in either can only mean one thing.

## Scope

- `data/site/summary-postings.json`: vocabulary and postings over title + summary,
  delta-encoded.
- Delete the precomputed search string from `core.json`, which brings the eager
  payload under the 1.5 MB budget and puts that gate in force.
- A matcher: tokens, terms AND, final term by prefix, identical normalization at
  build and runtime.
- A scope toggle in the filter panel, and updated help text.
- The frozen search states become documented exceptions in the differential, and a
  recall report says what actually moved for each one.

## The two departures from §4, both deliberate

**The default is inverted.** §4 says title-only by default. Measured first: a
title-only default keeps 29% of v1's results across the frozen queries, and `sdv`
falls from 3,146 hits to 61 because the terms this index is *about* are rarely in
titles. The owner inverted the ruling on 2026-08-21. Summaries are searched by
default; the toggle narrows to titles.

**Prefix matching is conditional.** §4 applies it to the final term unconditionally.
`C++` tokenizes to the single token `c`, which prefix-matches 4,627 of 4,962 records
— so the rule only applies when the query does not end in a delimiter.

## Definition of green

    python3 tests/gates.py --target v2 --stage 2b

with the eager-payload gate now in force, plus:

1. Golden differential: **only** search states differ, all as documented exceptions,
   zero failures.
2. `docs/perf/search-recall.md` regenerated, and read — an exception list permits a
   difference, it does not describe one.
3. Semantic suite green, including the tokenizer agreement table.
4. UI parity 100 states: every non-search state identical; search states reported as
   expected differences.

## The trap

**The build tokenizes in Python and the runtime tokenizes in JavaScript.** If they
disagree, a query is looked up under a key the text was never filed under and the
search quietly returns too little — no error, no crash, just fewer results. They are
pinned to a shared expectation table (`tests/semantic/tokenizer-cases.json`) checked
from both sides, rather than to each other.
