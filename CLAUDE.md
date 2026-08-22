# CLAUDE.md — SDVworld-index

Project orientation lives in `AGENTS.md` and `docs/`. Read `AGENTS.md` first; it is the
pointer to `README.txt`, `docs/schema.md`, `docs/agent-guide.md`, `TODO.txt`, and
`docs/open-questions.md`. Everything below is the operating constitution for the
performance redesign (`docs/perf/sdvworld-perf-design-v2.md`, approved 2026-08-21) and
takes precedence over habit.

## The constitution (design v2 §11, "Bug-free-by-construction" item 4)

1. **Never load `data/*.json` into context.** They run from hundreds of KB to ~9 MB.
   Compute every statistic, count, hash, or sample with a Python one-liner and read the
   *output*, not the file. `python3 -c "import json;d=json.load(open('data/sdv-index.json'));print(len(d['entries']))"`
   is the pattern. This applies equally to `data/tail/*.json`, `data/site/*.json`, and the
   golden corpus under `docs/perf/golden/`.
2. **Never hand-edit `data/sdv-index.json` or `data/build-info.json`.** They are generated
   by `python3 build.py --write` from `data/shards/`, and CI regenerates them on `main`.
   The same rule extends to every generated site artifact added by Stage 2
   (`data/site/manifest.json`, `core.json`, `summary-postings.json`, `detail/*.json`).
3. **All work happens on the `v2-perf` branch.** No force-push, no history rewrite, no
   rebase of pushed commits. One sanctioned exception, approved by the owner 2026-08-21:
   at the end of Stage 1, `v2-perf` merges to `main` so `/v2/` goes live on Pages for the
   pilot review. That merge may add only new files under `v2/`, `docs/`, `tests/`, and
   `scripts/`; `index.html`, `assets/`, and `data/` must be untouched, so v1 at the root
   cannot change. The exact file list is shown to the owner before the merge.
4. **Commit after each green sub-step.** A sub-step is green when the gate script passes.
   Small, reversible commits — Stage 3's cutover has to be revertible in one `git revert`.
5. **Legacy-export byte-identity check before every push.** `data/sdv-index.json`
   regenerated from unchanged shards must be byte-identical to the committed copy. The
   check is `scripts/check_export_identity.sh`; run it, do not eyeball it.

## Gates (design v2 §9) — hard, deterministic, and not negotiable

Run `python3 tests/gates.py` before every commit. It fails the commit on any of:

- more than 100 unique records rendered initially; default flat view ≥ 6,000 element nodes
- more than one corpus scan per filter interaction; any Blob URL created during render
- eager gzip budget > 1.5 MB (manifest + core + postings + JS + CSS + HTML); any detail
  bucket > 75 KB gzip
- any raw-pool network request from the v2 runtime
- any golden id/count mismatch outside the documented §8 exceptions

Wall-clock timings are **recorded, never gated** (§9). Report them; do not fail on them.

## Ordering rules

- **Oracle before code.** Stage 0 must be committed and green before any behavior-bearing
  file changes. Every later edit is judged against frozen golden data, never against
  recollection of the old behavior.
- **One stage per session**, against the stage brief in `docs/perf/stage-N.md`.
- **Stage 2 is split** (owner decision, 2026-08-21). §10 bundles the data-format
  change with the §4 search change; those are independent risks and Stage 1 showed
  what isolating them buys. **2a** is the projection, the single build path and the
  workflow fix, and its differential must stay 293/293 with **zero exceptions** —
  exactly as Stage 1 — so any difference is unambiguously a projection bug. **2b** is
  postings and the title-only search, where the only permitted differences are the
  frozen search states. Consequence: 2a carries a precomputed lowercase search string
  in `core.json` purely to hold v1's title+summary matching unchanged, so 2a is
  expected to exceed the 1.5 MB eager budget; 2b deletes that string and comes in
  under it. The payload and postings gates are therefore scoped to 2b, not 2a.
- **The §4 search default is inverted** (owner decision, 2026-08-21). §4 makes
  title-only the default with summaries opt-in, and that was a standing ruling — but
  it predates the performance work. Measured on this corpus, a title-only default
  keeps 29% of v1's results overall and collapses the terms the index is *about*:
  `sdv` from 3,146 hits to 61, `ctgan` from 3,293 to 123. v2 therefore searches title
  and summary by default and offers a toggle to narrow to titles. Everything else in
  §4 stands: identical normalization at build and runtime, Unicode letter/number
  tokens, terms AND, final term by prefix.
- **One correction to §4 as written.** "The final term matches by prefix" is applied
  only when the query does *not* end in a delimiter. Unconditionally, `C++` tokenizes
  to the single token `c` and prefix-matching returns 4,627 of 4,962 records. A
  trailing delimiter means the reader finished the word.
- **Browser harness** (owner decision, 2026-08-21): this machine has no Node, npm, or
  Playwright, and the package registries are unreachable from the command sandbox. The
  benchmark and screenshots therefore run as a dependency-free HTML/JS harness served by
  `scripts/serve.py` and driven through Chrome. The measurement code is kept free of any
  driver-specific API so a Playwright driver can reuse it unchanged if Node ever lands.
- v1 (`index.html`, `assets/js/sdv-index.js`) is frozen during Stages 1–2 except for the
  startup-waste fixes the design names. v2 lives under `v2/`.

## Golden-diff output contract

Failure output prints pass/fail counts plus **the first failing state only** — its state
id, expected, and actual. Never dump the full diff; it is unreadable and expensive.

## Data facts worth not re-deriving

- Current checkpoints: default view 4,703; importance 0 → 4,962; importance 4 → 1,543;
  importance 4 + popularity 50 → 846; importance 0 + `health` → 389.
- `data/build-info.json` reports 0.99 while `VERSION` says 1.0.0. That staleness is a
  known bug, fixed in Stage 2 (§7). Do not "fix" it by hand-editing the file.
- The two raw pools are `data/tail/openalex-citations.json` (~2.1 MB) and
  `data/tail/github-repos.json` (~1.5 MB). Stage 2 removes them from the wire.

## Commands

    python3 build.py                    # merge shards, report counts, write nothing
    python3 build.py --write            # write the generated index
    python3 tests/validate.py           # schema, vocabulary, pointer, alignment checks
    python3 tests/gates.py              # the §9 structural gates (added in Stage 0)
    python3 tests/golden_diff.py        # characterization oracle differential (Stage 0)
