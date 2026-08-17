# Post-parallel audit brief

Read this when the four arXiv slices (shards 63-90) have all landed on `main`.
Work these in order. Do not start a new curation lane until step 1 is clean.

## 1. Audit the four slices — do this first

Four sessions curated ~88 papers without shared calibration. The precedent for
unsupervised parallel work on this repo is shard 08, where an agent wrote 24
fabricated DOIs that looked entirely plausible. Assume nothing.

Mechanical checks, all scriptable from a clone:

- `python tests/validate.py` must print `OK: every check passed.`
- `python build.py` must report 0 duplicate urls and an entry count equal to
  the previous count plus the number of new records.
- **URL integrity.** Every new entry's `url` must be
  `https://doi.org/10.48550/arXiv.<id>` where `<id>` appears in the influential
  arXiv worklist. Build the set of legitimate ids from
  `data/tail/openalex-citations.json` and assert every new url resolves to one.
  Any url that does not is fabricated — this is the shard-08 failure mode.
- **Title fidelity.** Compare each new entry's `title` against the OpenAlex title
  for that arXiv id, exactly, not fuzzily. `validate.py` matches at 0.70
  similarity and will not see a dropped word or letter.
- **Id hygiene.** No duplicate ids across the whole shard set; no id colliding
  with an entry that already existed.
- **Vocabulary rules.** No entry may carry `integration: unclear` together with
  `confidence: high`. Every entry needs `source_channel:
  "semantic_scholar_discovery"` and non-empty `evidence`.

Judgment spot-check, one entry per slice, chosen from the highest-importance
entries that slice produced:

- Fetch the PDF yourself and confirm the sentences quoted in `evidence` are
  actually in the source and say what the entry claims.
- Confirm the `integration` and `importance` call against the conventions in
  `curate/arxiv-lane-brief.md`. The two calls most likely to be wrong are
  `derivative_work` on a paper that only positions itself against CTGAN without
  running it, and `baseline_only` on a paper with no results row for CTGAN.
- If a slice fails its spot-check, widen to every entry from that slice.

Report what you found to Saman before fixing anything. Corrections go in a new
shard numbered **above 90**, never by editing another session's shard.

## 2. Reconcile coverage

`python curate/arxiv_lane.py` should print `0 influential arXiv works remaining`.
If it does not, the stragglers are papers a slice skipped; curate them into a
shard above 90 and say which slice dropped them.

## 3. Put the open questions in front of Saman

These are his calls, not yours. Each is recorded as a `needs` on the entry:

- `paper-nft-data-trading-dpctgan-2025` (shard 55) runs DP-CTGAN, a third-party
  named CTGAN derivative, as its production generator. Recorded `api_user` 4.
  The alternative is `inherited` 3. No convention covers running a descendant.
- `paper-constrained-dgm-realistic-2024` (shard 60) yields C-CTGAN from a
  model-agnostic constraint layer applied to five generators. Recorded
  `derivative_work` **4** rather than the conventional 5.
- `paper-fct-gan-fourier-2022` (shard 57) shipped at `baseline_only` 4 under the
  MTGAN precedent, but its conditional vector arrives via CTAB-GAN+ rather than
  from CTGAN directly. He was asked 4-vs-3 and did not answer.
- Two more reviewable calls, no `needs` attached: `paper-mtabgen-diffusion-2025`
  kept `baseline_only` 3 despite naming sdv.dev as its implementation source, and
  `paper-realtabformer-relational-2023` got `baseline_only` **4** because SDV's
  relational HMA is the only prior relational baseline its headline claim rests on.

Collect any `needs` the four slices added and add them to this list.

## 4. Remaining lanes, after arXiv

90 influential works left. Recompute the split rather than trusting this table.

| lane | count | route |
|---|---|---|
| other | 45 | mixed; triage by publisher before planning |
| Springer/Nature | 30 | likely needs Saman's login via claude-in-chrome |
| MDPI | 8 | open access, fetchable in-sandbox |
| no-DOI | 4 | landing-page fetch |
| Elsevier / T&F / SAGE | 3 | likely needs his login |

Beyond the influential subset: 2,618 of the 2,862 tail works are uncurated. That
is the real remaining scope; the influential 287 was its highest-value slice.

## 5. Housekeeping worth raising

- The project memory file is near its size cap and should be split, with the
  historical sections moved out and only the live handoff kept.
- The standing url-vs-DOI cross-check (compare a shard's `url` against the DOI the
  build-time join brings in from OpenAlex by title) is worth re-running across the
  whole index after this batch, not just the new shards.
