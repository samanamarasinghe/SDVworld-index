# Stage 1 brief — the runtime win, on `/v2/`

Design: `sdvworld-perf-design-v2.md` §10 (Stage 1), §3, §6, §9.
Preconditions: Stage 0 committed and green (`docs/perf/stage-0.md`).
Branch: `v2-perf`. Constitution: `CLAUDE.md`.

**This stage is the pilot the owner reviews before Stages 2–3 proceed.** It isolates
the dominant runtime fix from all data-format risk: v2 reads the *current*
`data/sdv-index.json`, unchanged, and the build is not touched.

## Scope

In:

- Per-record normalization, once, at load: facet arrays, lowercase title, stable
  numeric index, precomputed popularity, precomputed affiliation types and regions.
- Facet universe and the popularity threshold computed once per corpus change, not
  once per facet per interaction.
- One corpus walk per interaction, producing a per-record failure mask. Mask zero is
  in the result set; it feeds facet F's self-excluding count when
  `(mask & ~bit(F)) === 0`. The filtered snapshot is computed **once** and handed to
  both count rendering and card rendering — nothing calls the engine independently.
- At most 100 unique records rendered, with a "Show 100 more" control and a
  "show all" clearly labeled as potentially slow.
- Lazy summary and needs **DOM** — the text is already in memory at this stage, so
  this is about not building thousands of nodes nobody asked for. Lazy *fetching* is
  Stage 2.
- BibTeX generated in the click handler; the object URL revoked as soon as the
  download begins. Zero object URLs created during render.
- Title search debounced ~150 ms; slider labels update immediately while filter work
  coalesces to at most one `requestAnimationFrame` callback.
- `DocumentFragment` / `replaceChildren` rendering.
- Both pools still load — but in parallel, and **without the redundant default-floor
  re-renders**: today each pool fetch re-triggers `applyFilters()` although no pooled
  row can appear at the default floor of 1 (§1 item 9).

Out — deliberately, and each has its own stage:

- Any change to `data/`, `build.py`, or the workflow. Stage 2.
- The site projection, manifest, postings, detail buckets, dictionary encoding,
  bitsets, IndexedDB, a service worker, a database, or any new export.
- Removing the raw-pool fetches. Stage 2.
- The §4 search change. Stage 1 keeps v1's title+summary substring matching, so the
  differential must be **clean, with no exceptions taken**. Changing search and
  changing the runtime in one step would make any golden difference ambiguous.
- URL/query-string state. Stage 4.
- Touching `index.html` or `assets/js/sdv-index.js`. v1 stays exactly as it is; the
  golden corpus describes it and Stage 3 diffs against it.

## Shape

Native ES modules under `v2/`, no bundler (§6 permits one; nothing here needs it):

    v2/index.html
    v2/assets/css/v2.css          only what is new; the shared sheet is reused
    v2/assets/js/main.js          entry point
    v2/assets/js/data.js          load + normalize + the pool residue
    v2/assets/js/engine.js        one-pass masks, counts, the popularity threshold
    v2/assets/js/order.js         sorting and grouping
    v2/assets/js/render.js        cards, the page limit, lazy detail DOM, BibTeX
    v2/assets/js/state.js         UI wiring, coalescing, state

**Every path must be relative.** Pages serves this project under
`/SDVworld-index/`, so `/assets/...` and `/data/...` resolve to the domain root and
404 in production while working perfectly on localhost. Use `../assets/...` and
`../data/...`. This is the single most likely way for the pilot to be broken on the
live site while green locally.

## Definition of green

    python3 tests/gates.py --target v2 --stage 1

with, in order:

1. `tests/oracle/adapter-v2.js` written, presenting the v2 engine behind the handful
   of methods `driver.js` and `runner.js` already call.
2. `/tests/oracle/harness.html?emit=actual&target=v2` →
   `python3 tests/golden_diff.py --actual docs/perf/golden/actual-v2.json` **PASS
   with zero exceptions taken.** All 293 states, identical ids in identical order,
   identical facet counts, identical group headings and counts.
3. `/tests/semantic/runner.html?target=v2` → 22 passing, and the six Stage 1 cases in
   `PENDING_V2` implemented and passing. 28 total; only the four Stage 2 detail-fetch
   cases may remain pending.
4. `/tests/bench/harness.html?target=v2` → the four Stage 1 gates pass:
   ≤ 100 unique records, < 6,000 element nodes, ≤ 1 corpus scan per interaction,
   0 object URLs during load and during every interaction. `engine.scanCount()` must
   exist so the scan gate is measured rather than approximated.
5. Timings recorded against the v1 baseline in `docs/perf/bench-baseline.json`.
   Targets: median common interaction < 100 ms, p95 < 200 ms, ≥ 5× the baseline.
   **Recorded, not gated** (§9) — report the number, do not fail on it.

Commit after each of these, not at the end.

## Traps, from reading v1

- **`popularityFloor()` sorts the whole corpus on every call**, and is called inside
  every `filteredData()` — eleven-plus times per interaction. It is a pure function
  of the corpus and the slider stop: compute the sorted popularity array once per
  corpus change and index into it.
- **`filteredData(exclude)` is called once per facet**, each time re-deriving
  `organizationsOf` and `affiliationRows` by splitting strings. Precompute at load.
- **Self-excluding counts are the whole reason for the mask.** A count must be taken
  with that facet's own bit cleared, or a dark value collapses to 0 and the reader
  can never widen. `tests/semantic/cases.js` has two cases on this, including one
  that requires a zero-count value to still render.
- **The affiliation groups permit, they do not select**, and they must be given an
  EMPTY value list for a record with no resolved region — never the `__none__`
  sentinel. Handing them the sentinel silently drops every unaffiliated entry. There
  is a case named for this.
- **`sortWithin` and several facet sorts use `localeCompare`.** Keep using it, with
  no locale argument, exactly as v1 does, or the ordering half of the differential
  will fail for reasons that have nothing to do with the redesign.
- **Grouping places a record under every applicable heading**, so group counts sum to
  more than the result count. That is correct. Under the page limit, sort the full
  unique result set first, render the first N unique records, then place *those* into
  groups; headers show `visible / total` (§3 item 8).
- **Any filter, grouping, or sort change resets N to 100.**
- The 44-row pool residue (8 citation + 36 repository, after alias suppression) must
  stay visible at importance 0 with `tier: tail` presentation.

## Finishing

`docs/perf/handoff-stage1.md`: the benchmark table (v1 baseline against v2, per
interaction, median and p95), screenshot paths, what is green, and what is knowingly
still open. Then the merge to `main` described in `CLAUDE.md` rule 3, so `/v2/` is
live for the owner's review — new files only, `index.html`, `assets/` and `data/`
untouched, file list shown before merging.
