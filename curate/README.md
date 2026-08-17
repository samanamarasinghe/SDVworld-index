# curate — maintenance tooling

Scripts that maintain the curated data. None of them makes a judgment: every one either
reports drift, regenerates a mechanical field, or prepares a worklist for a human or agent
who then reads the source. The judgment lives in the shards.

Everything is Python 3 standard library.

## Live

| script | what it does |
|---|---|
| `affiliation_facets.py` | regenerates `affiliation_types` and `affiliation_countries` from `affiliations` in every base shard record, aligned with the distinct organization sequence rather than with `authors`. Run without `--write` to report drift. Skips correction records, because an empty field on an override would blank the base record's value when `build.py` merges |
| `strip_joined_fields.py` | removes from a shard anything `build.py` can join back from the pools, so a shard carries only what a curator decided. Only touches regenerable fields — never `venue` or `doi`, which stay curator-owned |
| `facet_lift.py` | lifts bibliographic facets out of the raw pools into `data/tail/facet-lift.json`, a curation-ready sidecar. Regenerable; a missing copy is not data loss |
| `arxiv_lane.py` | reports which influential arXiv works remain uncurated. Also the one place that dedupes `data/tail/openalex-citations.json` on read, which matters because the stored file holds 14 works twice. Slices by a stable hash of the arXiv id — never by position in the remaining list, which reshuffles every slice as soon as one shard lands |

## Archived

`curate/archive/` holds lane briefs whose lane is closed and one-off scripts that ran
once. They are kept for provenance — a shard's contents are easier to understand next to
the brief that produced it — and are not expected to run again. `curate/archive/README.md`
says what each one was for.

## Where the rest went

- The record schema and vocabularies: `docs/schema.md`
- How to curate, and the accumulated conventions: `docs/agent-guide.md`
- Judgment calls awaiting a ruling: `docs/open-questions.md`
- What is left to do: `TODO.txt`
