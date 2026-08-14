# data/tail — raw harvest pools

Everything here is **mechanically harvested, uncurated raw data** — the firehose
the curated index is drawn *from*. It is **not** part of the index: `build.py`
reads only `data/shards/`, never this directory.

- **`data/shards/`** = curated, facet-tagged, `confidence`-rated entries, merged
  by `build.py` into `data/sdv-index.json` (what the website shows). Append-only.
- **`data/tail/`** (here) = raw pools. Big, noisy, no facets. You curate *from*
  these into shards; you never add them to the index directly.

| file | source | produced by | contents |
|---|---|---|---|
| `openalex-citations.json` | OpenAlex | `harvest/openalex_citations.py` | every work citing the 5 anchor SDV papers |
| `github-repos.json` | GitHub code search | `harvest/github_tail.py` (patterns) + `harvest/github_metrics.py` (metrics) | repos whose code matches an SDV-usage pattern, with popularity/authorship signals |
| `patents.json` | manual | — | patents referencing SDV |

The website can optionally fold the citation tail (`openalex-citations.json`) and
the GitHub repo tail (`github-repos.json`) into the main list via the toggles;
those entries carry a `tail` badge and are gated/ranked, never shown as curated.
