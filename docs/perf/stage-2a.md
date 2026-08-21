# Stage 2a brief — the site projection

Design: `sdvworld-perf-design-v2.md` §5, §7, §10 (Stage 2), §8 build tests.
Preconditions: Stage 1 green and reviewed (`handoff-stage1.md`); owner approved the
2a/2b split on 2026-08-21.
Branch: `v2-perf`. Constitution: `CLAUDE.md`.

## Why this is half of Stage 2

§10 bundles the data-format change with the §4 search change. They are independent
risks, and Stage 1 demonstrated what separating them buys: a differential that stayed
293/293 with **zero exceptions** meant every difference was unambiguously a bug, with
no exception list to hide behind.

**2a therefore changes no behavior at all.** Same records, same filter semantics, same
search, same order, same counts. Only where the bytes come from changes. The
differential must come back 293/293 with zero exceptions, exactly as it does today.

**2b** then makes the one planned semantic change: token postings and title-only
default search, where the frozen search states are the only permitted differences.

## Scope

In:

- **One build path.** A pure `assemble_records()` in `build.py` returning the
  in-memory record list; the legacy export and the site projection both emitted from
  it. No second merge implementation (§5).
- **`data/site/manifest.json`** — `schema_version`, product `version`, deterministic
  `data_hash`, curated/tail/total counts, detail bucket count, file names and byte
  counts. `data_hash` is the cache identity, not the date or the version.
- **`data/site/core.json`** — filter, sort and collapsed-card fields only, plus
  precomputed `organizations`, `aff_type`, `aff_region`, `popularity`, `tier` and the
  detail bucket id. **Evidence stays in core** (§1 item 1). Export-only fields —
  `source_channel`, `evidence_tier`, `openalex_id`, `countries`, the raw aligned
  affiliation lists, and the popularity inputs now folded into the score — are left
  out. The projection is intentionally lossy (§1 item 2).
- **`data/site/detail/00.json` … `1f.json`** — summary and needs only, keyed by id,
  bucket by a documented stable id hash recorded in core.
- **The 44-row pool residue folded in at build time** by the same alias-aware logic
  the browser runs today, with a test pinning it to the 44 ids the Stage 0 corpus
  recorded.
- **Raw-pool fetches removed** from the v2 runtime. The `no-raw-pool` gate comes into
  force here.
- **Workflow fix (§7).** The trigger and commit logic must cover `data/build-info.json`,
  the manifest/core/detail set, `VERSION`, the pool inputs and the build scripts, with
  every generated path staged explicitly. Today the workflow runs `build.py --write`,
  which writes `build-info.json`, then commits only `sdv-index.json` — which is why
  the live footer says 0.99 while `VERSION` says 1.0.0. Reproduced on 2026-08-21 by
  running the documented build command and watching the file change.
- **The four Stage 2 semantic cases** become real: detail fetch success, in-flight
  sharing, failure leaving the core card usable with a retryable error, and retry.

Out:

- The §4 search change, postings, and anything that alters recall. That is 2b.
- Dictionary encoding, bitsets, IndexedDB, a service worker, a database, or any new
  public export.
- Touching `index.html` or `assets/js/sdv-index.js`. v1 stays frozen; the golden
  corpus describes it and Stage 3 diffs against it.

## The one deliberate wart

2a keeps v1's search exactly: case-insensitive substring over **title and summary**.
But summary moves into the detail buckets, so it is no longer in core — and the
matcher still needs it.

So core carries a precomputed lowercase `search` string per record for 2a only. This
is the "aligned search-text sidecar" §4 names as the fallback, used here as a
temporary bridge rather than a permanent one. It costs roughly 0.8 MB gzip, so **2a is
expected to exceed the 1.5 MB eager budget**, and the payload gate stays scoped to 2b,
where postings replace the string and it is deleted.

Stating it plainly because it would otherwise look like a design decision: the sidecar
is scaffolding, and 2b removes it. If 2b ever stalls, this is the thing to go back and
finish, not something to live with.

## Definition of green

    python3 tests/gates.py --target v2 --stage 2a

1. `python3 build.py --write` leaves `data/sdv-index.json` **byte-identical**. This is
   the check that matters most: the public export is a downstream contract and the
   refactor must not touch it. `scripts/check_export_identity.sh`.
2. `python3 tests/build_tests.py` — §8's build tests: every core and detail id maps to
   exactly one assembled record; the projection equals a reference Python transform;
   every non-unknown affiliation country resolves to an explicit region or is reported;
   the manifest's hash, counts and sizes match the files on disk; bucket assignment is
   deterministic across runs; the 44 residue ids match the Stage 0 corpus; no runtime
   file references either raw pool.
3. Golden differential **293/293, zero exceptions taken**.
4. Semantic suite **32/32, nothing pending** — the four detail-fetch cases close here.
5. UI parity **100/100** on seed `20260821`, the same states Stage 1 passed.
6. Benchmark re-run and recorded; no detail bucket over 75 KB gzip.

Commit after each of these, not at the end.

## Traps

- **Byte-identity is easy to lose by accident.** The export is written with
  `json.dump(out, fh, indent=1, ensure_ascii=False)` and a trailing newline, after
  `out.sort(key=lambda r: (r['kind'], -(r.get('year') or 0), r['title']))`. Refactoring
  must not reorder, re-key, or re-serialize it.
- **The residue must be built by the same logic, not a lookalike.** Suppression
  matches on every alias a curated entry carries — `url` *and* `openalex_id` —
  normalized by stripping scheme, `www.` and trailing slashes. Matching only the
  displayed pointer unsuppresses rows that were meant to be retired. The Stage 0
  corpus pins the answer at 8 citation rows and 36 repository rows.
- **`normalizeCite` and `normalizeGh` are being ported from JS to Python.** Field for
  field, including `TYPE2KIND`, the `hit_patterns` → component map, the `gh-` id
  prefix, and `tier: 'tail'`. A port is a second implementation; the test that pins the
  44 ids and their projected fields is what keeps it honest.
- **Popularity is precomputed now**, so `stars`, `forks`, `contributors` and `commits`
  no longer need to reach the browser — except `stars` and `cited`, which the
  collapsed card displays. Dropping a field the card shows is a silent visual
  regression the golden differential cannot see; the UI parity run can.
- **Lazy summary needs a flag in core.** The card draws a "Summary" toggle only when
  there is one, and it must know that without fetching the bucket.
- **A failed bucket fetch must leave the card usable** (§3 item 10), and a retry must
  succeed — a failure must not poison the bucket for the rest of the session.

## Finishing

`docs/perf/handoff-stage2a.md`, then the same merge to `main` as Stage 1 so `/v2/`
keeps working against the new artifacts.
