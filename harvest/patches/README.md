# Curation patches

One JSONL file per batch, applied by `harvest/apply_curation.py` in filename
order. One JSON object per line, keyed by `openalex_id`, carrying only the
fields being set:

```
{"openalex_id": "W3202428668", "uses_sdv": false, "integration": "citation_only", "confidence": "high", "evidence": "survey; CTGAN cited as prior art, never run"}
```

Patches are small and reviewable in a diff. The 10.6 MB `citing-works.json` is
never edited by hand and never passes through a chat context — the script is the
only thing that writes it.

## Round trip

1. A batch of curated records arrives as `curation-<batch>.jsonl` in this folder.
2. `python harvest/apply_curation.py --check` validates: known ids, known field
   names, facet values in vocabulary, no silent overwrite of an earlier patch.
3. `python harvest/apply_curation.py` writes the `curation` object into each
   record in `citing-works.json` and fills the matching cells in
   `harvest/curation-worklist.csv`.
4. Commit the patch, the JSON and the CSV together.

Re-running is safe. Applying every patch from scratch reproduces the same state.

## Rules the script enforces

- `uses_sdv: true` requires `evidence`, `integration`, `summary` and `confidence`.
- `confidence: high` requires `source_url` — the thing that was actually read.
- Facet values must already exist in the vocabulary. Widening the vocabulary is a
  deliberate edit to `apply_curation.py`, made in the same commit as its first use.

A record with `uses_sdv: false` needs only `integration`, `confidence` and a
one-line `evidence` note. Most of the 874 will land there, and that is the
expected outcome: citing CTGAN is not using SDV.
