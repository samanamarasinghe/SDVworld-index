# Characterization oracle

Freezes what the v1 filter engine does, so every later change is judged against
recorded behavior instead of anyone's memory of it. Design v2 §8, Stage 0.

## Running it

    python3 scripts/serve.py &                 # localhost:8765, with a POST sink
    open http://127.0.0.1:8765/tests/oracle/harness.html

The page reports progress and writes four files under `docs/perf/golden/` when it
finishes. Poll `window.__ORACLE__` (`{done, error, progress, total, summary}`) to
watch it from a script. Query parameters:

| parameter | effect |
| --- | --- |
| `?limit=N` | evaluate only the first N states — smoke runs |
| `?emit=golden` | *(default)* record the corpus |
| `?emit=actual&target=v2` | replay the same states against v2 → `actual-v2.json` |

Then compare:

    python3 tests/golden_diff.py                                     # self-check
    python3 tests/golden_diff.py --actual docs/perf/golden/actual-v2.json

## Why it instruments v1 instead of reimplementing it

A second implementation of v1's semantics would agree with itself and prove nothing;
the point of a characterization oracle is to preserve the existing behavior *including
its bugs*, so the recorded behavior has to come from the shipped code.

`instrument.js` fetches `assets/js/sdv-index.js` verbatim and splices exactly one line
in ahead of the file's final `})();`, publishing the IIFE's own bindings as
`window.__V1__`. Every other byte is untouched. The run records the source digest, the
patched digest, and the full text of the inserted line in `provenance.json`, so the
claim is checkable after the fact rather than taken on trust. The size of the patch is
asserted at load time: if it ever changes more than the one line, the run fails.

The markup is pulled from the live `index.html` at run time for the same reason — a
copy would drift, and the oracle would then characterize a page nobody ships.

The engine is driven directly rather than through the DOM. Rendering 4,703 cards for
each of 293 states would take about an hour and record nothing the engine does not
already decide. Driving the closure takes 50 seconds.

## What is recorded

`records.json` is the canonical record table — every id in corpus order, so a state's
result can be stored as indices into it. `states.json` is the state list. Per state,
`results.json` holds:

- `total` — the result count
- `ids` — the **ordered** result, as indices, after `sortWithin`
- `facets` — for every bounded facet plus both affiliation groups, the *self-excluding*
  count of every value in the universe (materialized including zeros, so a value
  dropping out of the map is distinguishable from a value falling to zero)
- `groups` — `[heading, count]` in display order, or `null` when grouping is off

The actual side carries its own `ids` table. Nothing requires v2 to hold the corpus in
v1's order, so `golden_diff.py` compares id sequences rather than indices into two
tables that may not line up.

## Constraints worth knowing

**Collation.** `sortWithin` and several facet sorts call `localeCompare` with no
locale, so the recorded order is a property of the machine that generated it.
`provenance.json` records the locale (`en-US`) and four canary comparisons. A corpus
regenerated under different collation is not comparable to this one.

**Determinism.** Two full runs on 2026-08-21 produced byte-identical `records.json`,
`states.json` and `results.json`. Any future non-determinism is a bug in the oracle,
not noise to be tolerated.

**The corpus is pinned.** `docs/perf/baseline.json` holds the source commit and the
SHA-256 of `data/sdv-index.json` and both pool files. If those move, the corpus is
stale and has to be regenerated, not patched.

## The 293 states

Per §8: every importance stop (7) and popularity stop (20); every value of every
bounded facet singly (kind, sdv_component, sdv_concept, use_case, integration,
industry, year); a deterministic high/mid/low-frequency sample of authors and of
organizations plus a value that cannot match; 63 cross-facet pairs, half at importance
0 so the pool residue is exercised under facets; one OR-within-one-facet state per
bounded facet, which no single-value state can distinguish from AND; 24 searches
covering partial words, multiword queries, case, punctuation and non-ASCII; every
grouping against every sort (28); every affiliation button dark alone and lit alone,
plus six cross-group combinations; and the five §8 checkpoints by name.

The checkpoints are asserted **before** anything is written when recording the corpus:
default 4,703 · importance 0 → 4,962 · importance 4 → 1,543 · importance 4 +
popularity 50 → 846 · importance 0 + `health` → 389. All five matched on 2026-08-21.
