# Stage 2a handoff — the site projection

Branch `v2-perf`. Design: `sdvworld-perf-design-v2.md` §5, §7, §8.
Brief: `stage-2a.md`. Previous: `handoff-stage1.md`.

Stage 2 was split on your approval. **2a changes no behavior at all** — same records,
same filter semantics, same search, same order, same counts. Only where the bytes come
from changes. That is why the differential still has to come back with *zero*
exceptions, and does. **2b** is the one planned semantic change: token postings and
title-only search.

## What changed

**One build path.** `build.py` now exposes a pure `assemble_records()`; the legacy
export and the projection are both emitted from that single list, so there is no
second merge implementation to drift. `data/sdv-index.json` rebuilds **byte-identical**
— its own gate, because it is a downstream contract that none of this work may perturb.

**`data/site/`** — `manifest.json` (with `data_hash` as the cache identity),
`core.json`, and 32 detail buckets holding summary and needs only.

**Moved from the browser to build time:** splitting semicolon-separated affiliations,
deriving affiliation types and regions, scoring popularity, and the 44-row pool
residue — which the page previously downloaded 3.7 MB of raw pool data to discover.
The page now fetches no pool at all.

**The workflow (§7)** covers every generated path, with each staged explicitly, and
runs the build tests in CI.

## Payload

| | gzip |
| --- | --: |
| v1 eager — what the live site loads today | 2.59 MB |
| **v2 eager — 2a** | **1.91 MB** |
| projected after 2b removes the search bridge | 1.03 MB  *(budget 1.50)* |

`core.json` is 1.87 MB gzip of that, and **0.87 MB of it is scaffolding**: a
precomputed lowercase search string that exists only so v1's title+summary matching
survives 2a unchanged. Without it core measures **1.00 MB**, almost exactly the
~1.00 MB §5 predicted. 2b deletes the string when postings land.

So 2a is knowingly over the 1.5 MB budget, and the payload gate is scoped to 2b
accordingly. Saying it plainly because it would otherwise look like a design decision:
**the search string is temporary.** If 2b ever stalls, this is the thing to go back and
finish, not something to live with.

Detail buckets: 32, largest 37 KB gzip against the 75 KB cap, 1.04 MB gzip in total if
a reader somehow opened a summary in every one — and a normal session touches one or
two.

## Speed

Unchanged from Stage 1 in kind — the engine did not change here — but the cold load
improves again, because the page no longer downloads 3.7 MB of raw pool data it was
only using to find 44 rows.

| interaction | v1 | v2 (2a) | corpus scans |
| --- | --: | --: | --: |
| `search-type-health` \* | 231 ms | 69 ms | 1 |
| `importance-1-to-4` | 710 ms | 83 ms | 1 |
| `importance-1-to-0` | 2,198 ms | 199 ms | 1 |
| `popularity-0-to-50` | 2,130 ms | 75 ms | 1 |
| `facet-tick-first-kind` | 2,277 ms | 122 ms | 1 |
| `group-by-kind` | 2,566 ms | 168 ms | 0 |
| `sort-by-title` | 2,803 ms | 175 ms | 0 |
| `clear-all` | 3,176 ms | 122 ms | 1 |
| **cold load to settled** | **8,903 ms** | **539 ms** | |

\* The search row is measured through a debounce the environment clamps, as explained
in the Stage 1 handoff; treat it as indicative. Run-to-run variance is large — read
these as tens of milliseconds against seconds, not as exact multiples.

## Green

`python3 tests/gates.py --target v2 --stage 2a` → **PASS**

    [ ok ] render-cap       100 unique records rendered initially (cap 100)
    [ ok ] node-budget      2,252 element nodes in the default flat view (budget 6,000)
    [ ok ] one-scan         1 corpus scan(s) in the worst interaction, counted via engine
    [ ok ] no-blob-render   0 object URLs during load, 0 in the worst interaction
    [ ok ] no-raw-pool      no raw-pool request
    [ ok ] export-identity  legacy export byte-identical
    [ ok ] build            13 build checks passed
    [ ok ] detail-bucket    largest bucket 1c.json at 37.0 KB gzip (cap 75 KB)
    [ ok ] golden           293 states compared, 293 identical, 0 exceptions, 0 FAILED
    [ ok ] semantic         32 passed, 0 failed, 0 pending
    [  --] eager-payload    1.91 MB gzip (budget 1.50 MB)  (in force from stage 2b)

- **Golden differential: 293/293 identical, zero exceptions.** The projection is
  provably behavior-identical to v1 across every recorded state.
- **Semantic: 32/32, nothing pending.** The four detail-fetch cases named in §8 back in
  Stage 0 are now real and passing — fetch populates summary and needs; twenty cards
  from one bucket cost one request and a cached bucket costs none; a failed fetch
  leaves the card's title, links and actions intact and offers a retry; the retry
  succeeds, because the rejection is deliberately not cached.
- **UI parity: 100/100 states identical**, same seed and same states as Stage 1, with
  both real pages driven through real clicks.

## How the risky parts are pinned

**The pool logic was ported from JavaScript to Python**, which is a second
implementation and therefore the most dangerous thing in this stage. It is pinned two
ways. The Stage 0 corpus recorded what the *browser* produced from the raw pools
before any of this existed, and the build reproduces **all 4,962 ids in the same
order**, including 8 citation rows and 36 repository rows. And the hand-authored
semantic fixture is now run through both paths — v1 does its own suppression in the
browser from the raw fixture, v2 gets the same fixture projected by Python — with both
landing on the same 12 records.

**Test fixtures are projected by the same Python that projects the site.** A harness
that built its own fixture in JavaScript would be testing the engine against a private
second implementation of the transform under test.

**Popularity is deliberately not rounded** in core. Ordering falls through to
popularity as a tie-break, so rounding could collapse two records differing in the last
few bits into a tie and quietly send the sort down a different path than v1 takes.

**The 13 build checks each get their independent answer** from somewhere that cannot
have inherited the same mistake — the legacy export, the Stage 0 corpus, or the files
on disk. Every non-unknown affiliation country resolves to a region today, so that
check is strict: adding a country to the curation will fail the build until it is
added to the region tables in both `assets/js/sdv-index.js` and `site_projection.py`.

## Knowingly open

- **The repo grows by ~10 MB** (`data/site/`), because Pages serves static files from
  the repository. 2b brings that to roughly 4.7 MB when the search string goes.
- **`data/sdv-index.json` stays**, unchanged, as the public export (§5 item 1). It is
  no longer read by the site.
- The BibTeX click path is still not exercised end to end, for the same reason as in
  Stage 1: the test stubs delivery so runs do not drop `.bib` files in a Downloads
  folder.
- Rendered summaries still use `innerHTML`, as v1 does, because curated summaries carry
  inline links.

## Next

**2b:** `summary-postings.json`, the §4 title-only default search with opt-in summary
matching, deletion of the search bridge from core, and the eager payload gate coming
into force. It is the one planned semantic change in the redesign, so its differential
will take documented exceptions on the frozen search states — and those exceptions are
exactly what you should look at, because they are the change in recall made visible.

Then **Stage 3**: v1/v2 parity at the pinned revision, mobile-sized and keyboard/ARIA
passes, and the root cutover as a single revertible commit.
