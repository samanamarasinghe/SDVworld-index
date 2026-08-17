# data/tail — raw harvest pools

Everything here is **mechanically harvested, uncurated raw data**: the firehose the
curated index is drawn *from*. It is **not** the index. `build.py` reads only
`data/shards/`, and touches these files only to join metadata — year, stars, citations,
DOI — onto entries a curator already wrote.

- `data/shards/` = curated, facet-tagged, confidence-rated entries. Append-only.
- `data/tail/` (here) = raw pools. Big, noisy, no facets, no `importance`.

You curate *from* these into shards. Never bulk-promote a pool row into a shard.

The site holds both pools in the list alongside curated entries, badged as tail. There is
no toggle: what keeps them out of the default view is the importance floor, since a pooled
row carries no rating and the floor requires one at anything above 0.

**Per-file contents and row schemas: `docs/data-files.md`.**
**Which script produces which file: `harvest/README.md`.**
