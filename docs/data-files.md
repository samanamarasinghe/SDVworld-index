# What every file under `data/` contains

Three kinds of file live here, and confusing them is how work gets lost:

- **Curated** — a human or an agent made a judgment and wrote it down. Edit these.
- **Generated** — a script rebuilds them from something else. Never hand-edit; your
  change is erased on the next run.
- **Harvested** — mechanically collected raw material, uncurated. Big, noisy, and the
  thing you curate *from*.

Every JSON file here carries a `note` field describing itself. That note is the
authority if this file and it ever disagree.

## The index

| file | kind | what it is |
|---|---|---|
| `shards/NNN-*.json` | **curated** | The index itself, one shard per wave, append-only. 91 shards. A later shard corrects an earlier one with `"override": true`, which is why a correction must sort after everything it corrects. |
| `sdv-index.json` | **generated** | `build.py --write` merges the shards, joins pool metadata, applies corrections. This is what the page fetches. CI regenerates it on `main`; hand-editing it is always wrong. |
| `build-info.json` | **generated** | Version, build date and entry count, written alongside the index so the page can stamp itself. |
| `impact.json` | **curated** | Hand-checked citation counts for a handful of anchor papers, which override the pool join. |

## The harvest pools — `data/tail/`

These are the firehose. `build.py` reads only `data/shards/` and touches these files
only to join metadata onto entries a curator already wrote. Never bulk-promote a pool
row into a shard.

| file | what it is |
|---|---|
| `github-repos.json` | Every repository a GitHub code search matched on an SDV pattern, with stars, commits, contributors, language and dates. ~2,000 rows. The candidate list for the repository lane, and the join source for repository metadata. |
| `openalex-citations.json` | Works citing an SDV anchor paper, resolved through OpenAlex. The join source for `year`, `doi`, `venue` and `cited`. **Known defect: 14 works are stored twice.** Consumers dedupe on read; `curate/pool_hygiene.py` reports it. |
| `openalex-abstracts.json` | Abstracts for those works, split out because carrying them inline made the tail 36MB and the page never reads them. Opened by a curating agent, not by the site. |
| `citation-contexts.json` | Citation sentences and intents from Semantic Scholar, keyed by anchor. Gathering only — a curator writes the SDV clause from these, never lifts them verbatim. |
| `github-identities.json` | Resumable public GitHub profile metadata behind `github-repo-authors.json`. Self-published profile fields, not verified identity or employment. No email addresses are requested or stored. |
| `publication-identities.json` | The same idea for publications: OpenAlex institutions and web-page JSON-LD, with status fields separating a metadata claim from an affiliation checked in full text. |
| `affiliation-ror-matches.json` | Resumable responses from the public ROR affiliation matcher. |
| `patents.json` | Patents in the SDV problem space, held out of the shards until promotion criteria are settled. Not harvested systematically. |

`data/tail/README.md` says the same thing at the top of the directory.

## Authors and affiliations

This is the largest and least obvious group. The generated tables are big; the curated
overrides are small and are what you actually edit.

| file | kind | what it is |
|---|---|---|
| `publication-author-affiliations.json` | **generated** | One row per publication-author-affiliation relationship, so the same person may carry different affiliations across publications — which is correct, since the affiliation recorded is the one through which that author did *that* work. ~2,300 rows over 574 publications. A `.csv` twin exists for reading. |
| `github-repo-authors.json` | **generated** | One row per deduplicated author-like identity per repository, ~3,900 rows over ~2,000 repositories. `public_name_raw` and `affiliation_raw` preserve what the source claimed; the unsuffixed fields carry the normalized value. A `.csv` twin exists. |
| `publication-author-affiliation-overrides.json` | **curated** | Author affiliations checked directly in publication full text. Keyed by entry id plus one-based author position. Small and auditable by design. |
| `github-repo-author-overrides.json` | **curated** | Contributor lists and affiliations for index repositories, ordered by commit count, each carrying an `affiliation_source_status` that says how it was established. |
| `curated-author-affiliations.json` and `-002` … `-016` | **curated** | Hand-curated affiliations for everything that is not a GitHub repository: first-party writings, papers, theses. A numbered series rather than one file for the same reason shards are numbered — each wave is appended, never rewritten. |
| `affiliation-normalizations.json` | **generated** | Canonical names for the affiliation strings people put in their GitHub profiles. Raw values preserved in every mapping; `ror_confirmed` means the ROR matcher chose it, `official_source_confirmed` cites an official source, the rest are unconfirmed. |
| `public-name-normalizations.json` | **generated** | Canonical display names from public profile and commit names, derived conservatively. Formatting variants share one display name; **distinct GitHub numeric ids are never merged on a name match alone.** |

`curate/apply_author_affiliations.py` writes the override series into the base shards
and regenerates the two facet lists as it goes; `curate/affiliation_facets.py`
regenerates `affiliation_types` and `affiliation_countries` from `affiliations` alone.
Both refuse to write if a curator-owned field would change or if the lists would fall
out of alignment. `docs/author-affiliations.md` is the full procedure.

## The staging area — `curate/auto-shards/`

Not under `data/`, but it feeds it. `curate/auto_curate.py` writes one JSON record per
repository into `records/`, anything that fails validation into `needs-review.jsonl`,
and batch ids into `_batches.json`. `curate/merge_auto_shards.py` turns the records into
numbered shards. Records here are **not** in the index until that merge runs.

## Two rules that are easy to get wrong

**A retired entry is invisible in the built index but still owned by a shard.** An entry
carrying `duplicate_of` is dropped by `build.py`, so it is absent from
`data/sdv-index.json` while its id and url remain live in `data/shards/`. Any filter
meant to skip already-handled work must read the shards, not the built index — reading
the built index is how two retired repositories were re-curated and re-added.
`curate/never-readd.json` records deliberate drop decisions for the same reason.

**Size is not a diff.** `data/tail/github-repos.json` once produced a 67,680-line diff
that was pure formatting: the committed copy was single-line JSON and the harvester
writes it pretty-printed. Check the counts, not the line count.
