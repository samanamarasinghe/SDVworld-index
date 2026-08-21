# Stage 0 brief — contract and instrumentation

Design: `sdvworld-perf-design-v2.md` §8, §9, §10 (Stage 0), §11.
Branch: `v2-perf`. Constitution: `CLAUDE.md`.

No product change. Nothing under `index.html`, `assets/`, `data/`, `build.py` or
`.github/` is touched. The whole point of the stage is that it lands *before* any
behavior-bearing edit, so that every later edit is judged against frozen data rather
than against anyone's recollection of the old behavior (§11 item 1).

## Deliverables

| | what | where |
| --- | --- | --- |
| S0.1 | baseline pin — source commit, SHA-256 and gzip size of the corpus inputs and the v1 runtime | `scripts/pin_baseline.py` → `docs/perf/baseline.json` |
| | localhost server with a POST sink, so browser harnesses write to disk | `scripts/serve.py` |
| S0.2 | instrumentation of the shipped v1 source; state enumeration | `tests/oracle/instrument.js`, `states.js` |
| S0.3 | the characterization corpus, 293 states | `docs/perf/golden/*.json` |
| S0.4 | the differential comparator | `tests/golden_diff.py` |
| S0.5 | hand-authored semantic fixture and runner | `tests/semantic/` |
| S0.6 | the §9 structural gates | `tests/gates.py` |
| S0.7 | benchmark and structural probe | `tests/bench/` → `docs/perf/bench-baseline.json` |
| S0.8 | this brief and `stage-1.md` | `docs/perf/` |

## The two decisions taken here

**No Playwright.** §11 assumes a committed Playwright harness, but this machine has
no Node, no npm, and no reachable package registry from the command sandbox. The
owner chose (2026-08-21) a dependency-free harness instead: plain HTML/JS pages served
by `scripts/serve.py` and driven through Chrome. Nothing in `tests/bench/bench.js` or
`tests/oracle/driver.js` uses a driver-specific API — they are pages that finish and
set a global — so a Playwright driver can load the same URLs and wait on the same
globals if Node ever lands. Nothing is thrown away.

**The oracle instruments v1 rather than reimplementing it.** A second implementation
of v1's semantics would agree with itself and prove nothing. See
`tests/oracle/README.md` for how the one-line splice is kept provable.

## Green, as of 2026-08-21

- 293 states recorded. All five §8 checkpoints match exactly: default 4,703 ·
  importance 0 → 4,962 · importance 4 → 1,543 · importance 4 + popularity 50 → 846 ·
  importance 0 + `health` → 389.
- Three independent full runs produced byte-identical `records.json`, `states.json`
  and `results.json`.
- `golden_diff.py` verified against seven seeded mutations; the eighth exposed a
  silently inert assertion in the semantic runner, which was fixed.
- 22 hand-authored semantic cases pass against v1; ten v2 behaviors are recorded as
  pending, six of which Stage 1 must close.
- `gates.py` correctly *fails* v1 on every gate v1 is supposed to fail. A gate the
  current page passes is a gate that is not measuring the problem.

## The v1 baseline, measured

Corpus: 4,918 curated + 44 pool survivors (8 citation, 36 repository, after alias
suppression) = 4,962. The 44 are the residue §1 says Stage 2 folds in at build time.

| | v1 |
| --- | --- |
| cold load to settled | ~4.9 s |
| element nodes, default flat view | 129,114  (budget 6,000) |
| cards rendered initially | 4,703  (cap 100) |
| object URLs created before any interaction | 8,541  (budget 0) |
| corpus scans per interaction | 13  (budget 1) |
| eager gzip | 2.02 MB index + 0.55 MB pools  (budget 1.50 MB total) |

The 8,541 figure is the design's estimate reproduced exactly. Per-interaction
timings are in `docs/perf/bench-baseline.json`.

## What Stage 0 deliberately did not settle

- The `data/build-info.json` staleness (footer says 0.99, `VERSION` says 1.0.0) is
  real and reproduced, and is Stage 2's to fix in the workflow (§7). Hand-editing the
  generated file would hide the bug rather than fix it.
- Four of the ten pending semantic cases describe detail-bucket fetching, which
  cannot exist before Stage 2. They are tagged `closes: 2`.
- The payload and raw-pool gates are tagged as coming into force at Stage 2, because
  Stage 1 runs on the current flat export and keeps the pools on purpose (§10). They
  are implemented and reported from now, so the number is never a surprise.
