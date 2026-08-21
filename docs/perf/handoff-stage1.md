# Stage 1 handoff — the v2 pilot

Branch `v2-perf`. Design: `sdvworld-perf-design-v2.md` §10, Stage 1.
Briefs: `stage-0.md`, `stage-1.md`. Constitution: `CLAUDE.md`.

**This is owner touchpoint 3.** Open `/v2/`, click around, give a verdict. Everything
below is so you can skim rather than dig.

Nothing under `index.html`, `assets/`, `data/`, `build.py` or `.github/` was touched.
v1 is byte-identical to what it was, which is what makes the differential mean
anything.

## What to look at

**https://samanamarasinghe.github.io/SDVworld-index/v2/** — live and verified there,
not just locally: 4,703 results, 100 cards, 2,252 element nodes, no console errors,
and the root page unchanged at 4,703 cards. Locally it is
`http://127.0.0.1:8765/v2/index.html` after `python3 scripts/serve.py`. It should look exactly like the current page,
because it is the current page's markup and stylesheet — the only visible additions
are the two buttons at the foot of the results and a "v2 preview" line in the credits.

Worth trying specifically: drag the importance slider end to end (v1 pays for every
step of the drag), tick a facet, group by kind and watch the section headers, type in
the search box, press "Clear filters". Then "Show 100 more", and "Show all" — the last
one is honestly labelled and will still take a few seconds, because rendering 4,703
cards is slow however good the engine is. That is the point of the cap.

## Benchmark

Same machine, same harness, 7 repetitions per interaction, Chrome 151, corpus 4,962
records (4,918 curated + 44 pool survivors). Median is over the 7; p95 with 7 samples
is the slowest one, so read it as "worst observed", not as a real 95th percentile.

| interaction | v1 median | v2 median | speedup | v1 p95 | v2 p95 | v1 scans | v2 scans |
| --- | --: | --: | --: | --: | --: | --: | --: |
| `search-type-health` \* | 231 ms | 183 ms | **1×** | 1,202 ms | 813 ms | 13 | 1 |
| `importance-1-to-4` | 710 ms | 89 ms | **8×** | 1,533 ms | 170 ms | 13 | 1 |
| `importance-1-to-0` | 2,198 ms | 153 ms | **14×** | 3,402 ms | 401 ms | 13 | 1 |
| `popularity-0-to-50` | 2,130 ms | 112 ms | **19×** | 7,883 ms | 212 ms | 13 | 1 |
| `facet-tick-first-kind` | 2,277 ms | 122 ms | **19×** | 4,903 ms | 303 ms | 13 | 1 |
| `group-by-kind` | 2,566 ms | 133 ms | **19×** | 3,982 ms | 341 ms | 1 | 0 |
| `sort-by-title` | 2,803 ms | 177 ms | **16×** | 3,356 ms | 1,173 ms | 1 | 0 |
| `clear-all` | 3,176 ms | 133 ms | **24×** | 9,300 ms | 350 ms | 13 | 1 |

| | v1 | v2 |
| --- | --: | --: |
| cold load to settled | 8,903 ms | 590 ms |
| element nodes, default flat view | 129,114 | 2,252 |
| cards rendered initially | 4,703 | 100 |
| object URLs before any interaction | 8,541 | 0 |
| corpus scans per interaction | 13 | 1 |

**\* The search row is not a fair comparison, and I would rather say so than publish
the 1×.** v2 debounces the title input by 150 ms and v1 debounces nothing, so v2 is
being charged for a wait it takes deliberately. Worse, the benchmark has to run in a
background tab, where Chrome clamps `setTimeout` — measured at 542 ms during the v2
run and 275 ms during the v1 run. The harness measures that clamp and subtracts it,
but subtracting a noisy 542 ms from a 725 ms measurement leaves a number with most of
the uncertainty in it. What is solid for that state is structural and not affected by
any clamp: v2 does **1 corpus scan and renders 100 cards** where v1 does **13 scans
and renders 384**. In front of a real reader, with an unclamped timer, the wait is the
150 ms debounce plus work in the tens of milliseconds.

The other seven rows are undebounced and directly comparable: **8× to 24×**, against
the design's target of ≥ 5×. Medians are 89–177 ms against the < 100 ms target — several
rows sit above it, all on the widest possible result sets.

Two further caveats, in the spirit of §9's "timings are recorded, not hard-gated":

- **Run-to-run variance is large — read the order of magnitude, not the digits.**
  Across three v2 runs the same interactions came out at 52–151 ms, 89–177 ms, and
  cold load at 380 ms, 1,303 ms and 590 ms. Three v1 cold loads ranged 4.9–8.9 s.
  These were measured on a working laptop, back to back, with a browser doing other
  things. The claim worth making is "tens of milliseconds against seconds", not any
  particular multiple.
- The v1 and v2 runs saw different timer clamps, which affects only the debounced
  row.

Raw data: `docs/perf/bench-baseline.json` (v1), `docs/perf/bench-v2.json`.

## UI parity: 100 states, both pages, real clicks

Added after the first handoff, because the differential above proves less than it
appears to. It drives the filter **engine** — it never dispatches an event, never
reads a checkbox, never looks at the facet panel. It would have passed at 293/293 on a
v2 whose checkboxes were wired to the wrong facet, whose facet lists rendered in the
wrong order, whose sliders were inverted, or whose cards were drawn out of order.

`tests/parity/` loads `/index.html` and `/v2/index.html` in two iframes, **unmodified
and uninstrumented**, and drives both through the same real clicks on the same real
controls — then compares what a reader would see: the header count, the card titles in
order, every facet list's labels/counts/order/truncation, the facet header counts, the
year grid, the affiliation buttons and their lit state, and the group headings.

**Result: 100 of 100 states identical, 0 differing** (seed `20260821`, reproducible).
299 individual facet-value selections; all seven importance stops; four popularity
stops; all six groupings and all four sorts; 45 states with a search; 64 combining two
or more facets; 71 with two or more values in one facet. Full breakdown in
`tests/parity/README.md`.

Verified by mutation first, because a hundred passes prove nothing if the comparison
cannot fail. Two bugs seeded into v2 — a reversed year tie-break (changes card order
only, no count anywhere) and facet lists sorted ascending (changes list order only,
every count still right) — were both caught with the exact card and the exact facet
item named. Neither is visible to the golden differential.

Two false alarms along the way, both recorded in that README because each looked
exactly like a v2 bug and neither was one. The second is worth repeating here: the
test server sent `Last-Modified` and answered `If-Modified-Since` with a `304`, so
Chrome served an **old copy of the harness** for two full runs even though every
response also said `Cache-Control: no-store`. Those runs reported stale-code failures
as product failures. `scripts/serve.py` now drops conditional request headers, so a
304 is impossible.

## Screenshots

Desktop, 1440×900, Chrome 151.

| | |
| --- | --- |
| `docs/perf/screenshots/v2-default-filters.jpg` | the default view's filter panel — every facet count identical to v1 |
| `docs/perf/screenshots/v2-default-results.jpg` | result cards: evidence eager, summary collapsed, chips and actions as before |
| `docs/perf/screenshots/v2-page-limit-controls.jpg` | the two new controls: "Show 100 more (100 of 4,703 shown)" and "Show all 4,603 remaining (slow)" |
| `docs/perf/screenshots/v2-grouped-by-kind.jpg` | grouping, with headers reading `visible of total` — "Paper (11 of 2171)" |

Mobile-sized screenshots are **not** in this handoff. Window resizing through the
automation harness did not actually narrow the viewport on this machine
(`outerWidth` 700 while `innerWidth` stayed 1990), and a faked narrow render would be
worse than none. §10 puts mobile-sized runs in Stage 3, which is where they belong.

## Green

`python3 tests/gates.py --target v2 --stage 1` → **PASS**, all gates in force.

    [ ok ] render-cap      100 unique records rendered initially (cap 100)
    [ ok ] node-budget     2,252 element nodes in the default flat view (budget 6,000)
    [ ok ] one-scan        1 corpus scan(s) in the worst interaction, counted via engine
    [ ok ] no-blob-render  0 object URLs during load, 0 in the worst interaction
    [ ok ] golden          293 states compared, 293 identical, 0 exceptions, 0 FAILED
    [ ok ] semantic        28 passed, 0 failed, 4 pending

- **Differential: 293 of 293 states identical, with no exceptions taken.** Same result
  ids in the same order, same self-excluding facet counts, same group headings and
  counts, at every importance and popularity stop, every bounded facet value singly,
  63 cross-facet pairs, 24 searches, every grouping against every sort, and every
  affiliation permission toggle. Stage 1 deliberately keeps v1's title+summary
  substring search, so the §4 exception list went unused — a difference here could
  only have been a bug.
- **28 of 28 semantic cases pass.** The 4 still pending are the Stage 2 detail-fetch
  ones; they describe buckets that do not exist yet.

## How much of this is trustworthy

Everything above is a green test result, which is worth exactly as much as the tests
are. So, on the tests:

- The oracle instruments the shipped v1 source rather than reimplementing it — one
  spliced line, both digests recorded — so it cannot agree with itself. Three full
  runs were byte-identical.
- `golden_diff.py` was verified against seven seeded mutations before being trusted.
- The semantic expectations were hand-derived from a 13-record fixture, and verified
  by seeding eight wrong expectations. Seven were caught; the eighth revealed that
  the runner never compared group output at all — a silently inert assertion, now
  fixed and re-verified.
- The Stage 1 render cases were verified by breaking the **product**, not the
  expectations: removing the page-limit reset, and minting the BibTeX object URL
  during render the way v1 does. Both caught.
- The gates fail loudly on missing or stale evidence rather than skipping, and they
  were run against v1 first to confirm they fail everything v1 is supposed to fail.
- The UI parity harness was mutation-verified before its 100 states were believed,
  and its two false alarms were chased to root cause rather than re-run until green.

## Knowingly open

- **The BibTeX click path is not exercised end to end.** The test drives
  `downloadBibtex` with delivery stubbed, because letting it run would drop `.bib`
  files into a Downloads folder on every run. Creation and revocation of the object
  URL are covered; the browser actually saving the file is not. Worth one click during
  your review.
- **Rendered summaries still use `innerHTML`**, as v1 does, because curated summaries
  carry inline links and switching to text would silently drop every one of them.
  Unchanged behavior, but now written down.
- **Timer clamping** makes the debounced search row hard to measure in an automated
  run, as above.
- The four Stage 2 semantic cases, and the payload, detail-bucket and raw-pool gates,
  are implemented and reported but not yet in force. Eager payload today is still
  2.04 MB gzip against the 1.50 MB budget — that is Stage 2's whole job.
- `data/build-info.json` still reports 0.99 while `VERSION` says 1.0.0. Reproduced,
  not fixed: §7 fixes it in the workflow at Stage 2, and hand-editing a generated file
  would hide the bug rather than fix it.

## Next

Stage 2 on your word: the site projection, the single build path, the 44-row residue
folded in at build time, raw pools off the wire, and the workflow's generated-output
fix. Stage 3 is parity, cutover and the mobile/keyboard/ARIA pass.
