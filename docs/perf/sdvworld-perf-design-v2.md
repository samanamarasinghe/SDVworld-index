# SDVworld-index performance redesign — design v2

Status: approved 2026-08-21
Supersedes: `sdvworld-perf-design.md` (v1)
Incorporates: independent review of 2026-08-21 against commit `01a973bcccb406df14dc47e13045fef39ce7055d` (main, "Version 1.0.0")
Baseline for all golden data: to be pinned in Stage 0 as a named source commit plus SHA-256 of `data/sdv-index.json` and both pool files.

## 1. Disposition of the independent review

The review confirms the v1 diagnosis — eager creation of thousands of cards dominates interaction time, repeated whole-corpus scans make the facet panel the next bottleneck, the raw pools should not be browser inputs, and derived values belong in a build artifact — and its live measurements (interactions of 800–1,300 ms tracking post-action result size) match v1's qualitative findings. All of its corrections are accepted. v2 therefore adopts the review's implementation brief as the implementation section, with the specific changes below.

Accepted corrections to v1:

1. **Evidence stays in the eager core.** The current renderer shows evidence on collapsed cards; moving it to lazy detail would silently change visible behavior. Only summary and needs are lazy.
2. **The site projection is intentionally lossy.** `data/sdv-index.json` remains the unchanged public export; the projection is a deterministic runtime view of it, not a reconstruction. Fields such as `source_channel`, `evidence_tier`, `openalex_id`, and `countries` are export-only.
3. **No dictionary encoding.** It saves about 50 KB gzip on the measured core while making the format materially harder to debug. Revisit only after measurement (Stage 4).
4. **No IndexedDB, no service worker.** GitHub Pages already returns ETags and `304 Not Modified`; cache identity comes from a generated manifest carrying a `data_hash`. The v1 premise that a returning visitor necessarily re-downloads the index was wrong. The stale-`build-info.json` hazard the review found is fixed in the workflow instead (§7).
5. **One-pass fail masks first, bitsets only on evidence.** At roughly 5,000 records, ordinary arrays and masks should meet budget; `Uint32Array` bitsets are a measured follow-on, not a starting design.
6. **Database and Parquet/SQLite exports are out of scope.** They do not improve the site. (Consistent with the earlier ruling: no hosted DB, no browser SQLite; a derived export can be its own later project.)
7. **The v1 golden corpus is discarded.** Its counts are stale against main (`health` at importance 0 returns 389, not 384), and "every facet value singly" is infeasible with 10,599 authors and 2,656 organizations. The oracle is regenerated from the pinned commit with exhaustive states only for bounded vocabularies (§8).
8. **Timing is not a hard CI gate.** Structural budgets are the hard gates; wall-clock timing is recorded against a baseline with a generous regression ratio (§9).
9. **Startup waste is fixed in Stage 1.** The page currently renders the full default view twice (each pool fetch re-triggers `applyFilters()` although pools cannot affect the default floor) and creates about 8,541 unreclaimed Blob URLs before any interaction. Both are corrected as part of the runtime fix.
10. **Pagination under grouping is specified** (§3, item 8), resolving the ambiguity the review identified.

Retained from v1 (unchanged): the 100-card rendering cap with a "more" button, lazy summary/needs DOM, lazy BibTeX, precomputed record normalization, a single filter/count pass per interaction, build-time folding of the 44-row pool residue, the parallel `/v2/` rollout, and title-only default search with opt-in summary search. All five earlier design rulings stand: (1) title-only default search, (2) pools off the wire, (3) a bundler is permitted, (4) first-100-plus-more rather than virtualization, (5) `/v2/` on the live site during migration.

## 2. Goal and non-goals

Goal: every normal filter/search/reset interaction responsive, preserving the current data source of truth, filter semantics, visible collapsed-card content, sorting, grouping, and the public JSON export. Reduce eager network and heap cost without adding a backend.

Non-goals for this effort:

- No shard edits or data re-curation.
- No hosted database, runtime SQLite, or SQLite/Parquet exports.
- No framework migration.
- No IndexedDB or service worker.
- No URL-state feature until parity and cutover are complete.
- No dictionary encoding unless later measurement shows a material win.

## 3. Functional contract

1. `data/sdv-index.json` remains a generated, readable, unchanged-shape export for downstream consumers.
2. Default state remains importance 1, popularity 0, no facet selections, grouping none, sorting by importance.
3. Checkbox facets remain inclusive (OR within a facet, AND across facets); affiliation type and region remain permission/veto groups; `NO_NONE` behavior is preserved.
4. Popularity percentile remains computed over the complete active corpus, as today.
5. Collapsed cards continue to show title, kind, metadata, authors, integration, evidence, chips, and actions.
6. Summary and needs are lazy. BibTeX is generated only in the click handler; any object URL is revoked as soon as the download begins.
7. The 44 uncurated pool survivors remain visible only at importance 0 and retain `tier: tail` presentation; the residue is computed at build time by the same alias-aware logic, covered by tests.
8. Grouping/pagination: sort the full unique result set first; render the first N unique records; place those records into every applicable group. Group headers show `visible / total`. "Show 100 more" increases N by 100 unique records. Any filter, grouping, or sort change resets N to 100. A "show all" action may remain, labeled as potentially slow.
9. "Show summaries" and "Show open questions" operate on currently rendered records; newly rendered records load their detail on demand.
10. A failed detail fetch leaves the core card usable and shows a retryable inline error.

## 4. Search contract

This is the one planned semantic change, per the earlier ruling.

- Default: case-insensitive substring matching over the title only.
- With "include summaries" enabled: summary and query text are normalized identically at build and runtime, split into Unicode letter/number tokens; multiple query terms AND; the final term matches by prefix so typing remains progressive. Summary postings return candidates without fetching detail buckets.
- UI help text is updated, and explicit frozen examples cover partial words, multiword queries, punctuation, and non-ASCII text. These states are documented golden exceptions in the v1/v2 differential (§8).

Fallback: if exact old title+summary substring behavior is ever required, ship the aligned search-text sidecar (measured ~0.81 MB gzip) and the old matcher; do not treat token postings as equivalent.

## 5. Site artifacts

Generated from the same assembled record list as the legacy export, by one build path:

- `data/site/manifest.json` — `schema_version`, product `version`, deterministic `data_hash`, curated/tail/total counts, detail bucket count, file names and byte counts. `data_hash`, not date or version, is the cache identity.
- `data/site/core.json` — only filter/sort/collapsed-card fields, plus precomputed `organizations`, `aff_type`, `aff_region`, `popularity`, `tier`, and detail bucket id. Evidence is in core. (Measured: ~1.00 MB gzip with evidence preserved.)
- `data/site/summary-postings.json` — vocabulary and postings under the contract in §4.
- `data/site/detail/00.json` … `1f.json` — summary and needs only, keyed by id, bucket assignment by a documented stable id hash stored in core.
- `data/sdv-index.json` and `data/build-info.json` remain for compatibility; the v2 runtime reads only the site artifacts. No runtime fetch references either raw pool.

Build refactor: a single pure `assemble_records()` produces the in-memory record list; the legacy export and the site projection are both emitted from it. No second merge implementation.

## 6. Runtime model

Native ES modules split the controller into: data loading/normalization, filter/count engine, sorting/grouping, result rendering/detail loading, UI wiring/state. (A bundler is permitted if browser-test or TypeScript ergonomics justify it; if used, it is pinned with a lockfile and generated vs. source files stay explicit.)

On load, each record is normalized once: facet arrays/sets, lowercase title string, stable numeric index, precomputed popularity and bucket. The facet universe is computed once after load.

Each interaction performs one corpus walk. Every inclusive facet and permission group gets a bit; after the global importance/popularity/search predicates, each record's failure bitmask is computed. Mask zero means the record is in the result set; it contributes to facet F's self-excluding count when `(mask & ~bit(F)) === 0`. No function calls the filter engine independently — the filtered snapshot is computed once and passed to count rendering and card rendering.

Input coalescing: title search debounced ~150 ms; slider labels update immediately but filter work coalesces to at most one `requestAnimationFrame` callback. Rendering uses `DocumentFragment`/`replaceChildren`, at most 100 unique records initially, no summary/needs DOM until requested, zero Blob URLs during render.

Detail-bucket fetches deduplicate in-flight promises and retain loaded buckets in memory; ordinary HTTP caching (ETag revalidation) does the rest.

## 7. Build and workflow fixes

The workflow currently runs `build.py --write` (which writes both `data/sdv-index.json` and `data/build-info.json`) but checks and commits only the former; the live footer consequently reports 0.99 while `VERSION` says 1.0.0. Stage 2 fixes generated-output coverage: the trigger and commit logic include `data/build-info.json`, the manifest/core/postings/detail set, `VERSION`, pool inputs, and build scripts, with every generated path staged explicitly.

## 8. Test plan

**Characterization oracle (Stage 0, before any behavior change).** Generated at the pinned commit, storing the source SHA, SHA-256 of the index and both pools, and per-state: total count, ordered matching ids, every bounded facet's value/count map, and group headings/counts. Roughly 250 deterministic states: every importance and popularity stop; every value singly for bounded facets (kind, integration, component, concept, use case, industry, year); a deterministic high/mid/low-frequency sample of authors and organizations plus missing-value cases; at least 50 cross-facet pairs; at least 20 searches (`h`, `he`, `health`, partials, multiword, punctuation, non-ASCII); every grouping and sorting option; every affiliation permission toggle alone and in representative combinations. Current exact checkpoints for sanity: default 4,703; importance 0 → 4,962; importance 4 → 1,543; importance 4 + popularity 50 → 846; importance 0 + `health` → 389.

**Hand-authored semantic tests** on a tiny synthetic fixture, because a differential oracle preserves existing bugs: facet OR/AND semantics; self-excluding counts; `__none__` and every `NO_NONE` exception; overlapping academic/non-academic and multi-region veto; unplaced/unknown countries never veto; popularity and importance ties; duplicate grouping and page-limit semantics; curated/tail alias suppression; detail fetch success, sharing, failure, retry; zero Blob URLs during render and revocation after a BibTeX click.

**Build tests.** Legacy export byte-identical for identical inputs; every core/detail id maps to exactly one assembled record; runtime projection values equal a reference Python transform; every non-unknown affiliation country maps to an explicit region or fails/warns per policy; manifest hash/counts/sizes match the files; deterministic bucket assignment; no runtime reference to either raw pool.

## 9. Gates

Hard, deterministic CI gates:

- ≤ 100 unique records rendered initially; default flat view < 6,000 element nodes
- one corpus scan per filter interaction; zero Blob URLs created during render
- eager gzip budget ≤ 1.5 MB (manifest + core + postings + JS + CSS + HTML); no detail bucket > 75 KB gzip
- no raw-pool network request
- exact golden ids/counts for all non-excepted states

Recorded, not hard-gated: real-browser timings against the same runner's v1 baseline. Targets after warm load: median common interaction < 100 ms desktop; p95 < 200 ms desktop, < 300 ms under a documented mid-range mobile CPU profile; ≥ 5× over the v1 baseline. CI fails only on a large regression ratio; the benchmark is otherwise published as an artifact.

## 10. Delivery stages

- **Stage 0 — contract and instrumentation.** Characterization corpus, semantic fixture, repeatable browser benchmark, payload accounting, baseline metadata. No product change.
- **Stage 1 — runtime win on the current export.** `/v2/` against the current flat index: normalization, cached universe/thresholds, one-pass masks, 100-record rendering, lazy summary/needs, lazy/revoked BibTeX, coalesced inputs; pools still load temporarily but in parallel and without redundant default-floor renders. This isolates the dominant runtime fix from data-format risk and should already remove the seconds-long interactions.
- **Stage 2 — site projection.** Single build path; manifest/core/postings/detail; precomputed derived fields; 44-row residue folded in at build time; raw-pool fetches removed; workflow generated-output fix. No dictionary encoding, IndexedDB, bitsets, database, or exports.
- **Stage 3 — parity and cutover.** v1/v2 differential at the pinned revision with only the documented search change and pagination display as exceptions; real desktop and mobile-sized browser runs with screenshots for representative states; keyboard/focus/ARIA verification. Root cutover is a separate commit touching only the entry point/assets; v1 stays at `/v1/` for one release; the legacy export remains. Rollback is a single revert.
- **Stage 4 — optional, evidence-gated.** Shareable query-string state; dictionary encoding, bitsets, or a TypeScript/bundler toolchain only if measurement or maintainability justifies them.

First milestone: Stage 0 + Stage 1 together — most of the user-visible win at the smallest semantic and build risk. **Stage 1 on `/v2/` is the pilot for review before Stages 2–3 proceed.**

## 11. Implementation with Claude

### Tooling and model

- **Claude Code** (terminal CLI or the desktop app's Code tab) on the machine holding the repo clone. Rationale: it runs `build.py`, `tests/validate.py`, the Playwright benchmark, and git push locally in one agent loop — no copying between chat and terminal, and the GitHub-connector file-size constraints that shaped earlier heredoc-patch deliveries disappear entirely.
- **Model: Opus 5** (`claude-opus-5`; alias `opus` in scripts) for all design-bearing stages. It is the model Anthropic positions for exactly this shape of work — long-horizon agentic coding with self-verification — at $5/$25 per million tokens. Fable 5 offers no advantage here at twice the price. Mechanical subtasks (oracle-state enumeration, fixture generation, screenshot triage) run on **Sonnet** subagents (`.claude/agents/` files with an explicit `model:` field) to cut cost.
- **Verification harness:** Playwright (headless Chromium) is both the timing benchmark and the screenshot source; it is committed to the repo so every run is repeatable and CI-capable.

### Bug-free-by-construction protocol

1. **Oracle before code.** Stage 0 lands and is green before any behavior-bearing file changes — every later edit is judged against frozen golden data, not against the model's memory of the old behavior.
2. **Gates as hooks.** The §9 structural gates run as a Claude Code stop-hook / pre-commit script; the agent cannot commit a state that violates them. Golden-diff output prints pass/fail plus the first failing state only, so failures are cheap to read and to feed back.
3. **One stage per session, plan mode first.** Each stage begins in plan mode against a short repo-resident stage brief (`docs/perf/stage-N.md`); the plan is executed only after it matches the brief. Session-per-stage keeps context small and prevents drift.
4. **`CLAUDE.md` carries the constitution:** never load `data/*.json` into context (use Python to compute stats); never edit `data/sdv-index.json` by hand; all work on the `v2-perf` branch; commit after each green sub-step; legacy-export byte-identity check before every push.
5. **Differential cutover.** Stage 3's v1/v2 diff plus the single-revert cutover commit mean any escaped defect is one `git revert` from gone.

### Owner involvement (four touchpoints)

1. Approve this document. (Done 2026-08-21.)
2. One-time setup, ~10 minutes: `npm install -g @anthropic-ai/claude-code`, `claude` in the repo clone, accept the permission profile (edit/test/commit on `v2-perf`, push allowed; no force-push, no history rewrite). Docs: https://docs.claude.com/en/docs/claude-code/overview
3. Review the Stage 1 pilot: open `/v2/` on the live Pages site, click around, give a verdict. Screenshots and the benchmark table are attached to the handoff for a faster skim.
4. Approve the Stage 3 root cutover (one yes/no).

Everything else — code, tests, benchmarks, commits, pushes, and checking the live site after deploys — runs inside the agent loop. Progress lands in `docs/perf/` handoff notes rather than chat.

### Token-cost measures

- Session-per-stage with repo-resident briefs: each session starts from a few-KB brief instead of a long conversation; Claude Code's prompt caching then keeps repeated file context cheap within a session.
- Data files never enter context; scripts summarize. Test output is terse by design (item 2 above).
- Sonnet subagents for enumeration/generation work; Opus only where judgment is exercised.
- `/compact` at natural checkpoints inside long stages; `--max-turns` caps on any headless (`claude -p`) verification runs.

Rough cost at API rates, dominated by Stages 1–2: on the order of $50–150 total for Stages 0–3. (On a Max subscription it draws on the plan's included usage instead.)

## 12. Risks

- **Semantic drift in the filter engine** — the highest-consequence risk; mitigated by the oracle-first ordering, the synthetic semantic fixture, and hard golden gates.
- **Search-change surprise** — mitigated by the explicit contract, frozen examples, and the opt-in summary toggle preserving a discoverable path to old recall.
- **Workflow/generated-file staleness** — the review's `build-info.json` finding; fixed in Stage 2 and covered by a manifest-vs-files build test.
- **Benchmark noise** — timings are reported, not hard-gated; only structural properties can fail CI.
