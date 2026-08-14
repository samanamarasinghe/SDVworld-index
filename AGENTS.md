# AGENTS.md

Instructions for an agent with GitHub write access to `samanamarasinghe/SDVworld-index`,
a shell, and unrestricted network access. Read this file first; it is the task spec.

Owner: Saman Amarasinghe. Report back to him, not to whoever queued the task.

## What this repository is

An index of the Synthetic Data Vault (SDV) ecosystem — papers, theses, blog posts,
articles, documentation, case studies, and code repositories. Every entry carries a
pointer, a short summary, and categorization on three facets: information type, SDV
use case, and industry. Modelled on `data/publications.json` in
`mit-commit/commit-website`, widened well beyond papers.

## Current state

```
README.md                            schema + controlled vocabularies
build.py                             merges shards -> data/sdv-index.json
data/shards/01-first-party.json      44 entries: MIT/DataCebo research, libraries, docs, blog, cases
data/shards/02-github-curated.json   18 entries: third-party repos, verified against code evidence
data/tail/github-candidates-full.json 2019 repos, pooled, not yet curated
harvest/README.md                    source-by-source notes and the curation rule
harvest/openalex_citations.py        citing works for the 5 anchor papers
harvest/github_tail.py               partitioned GitHub code search
harvest/scholar_citations.py         Google Scholar via SerpAPI
```

**No harvest script has ever been executed.** They were written in an environment whose
sandbox could not reach any of the target APIs. Treat your first run as the test: expect
bugs, fix them, commit the fixes with a note in the commit message.

All three scripts are Python 3 standard library only. Nothing to install.

## Credentials and network

| need | for | required |
|---|---|---|
| `GITHUB_TOKEN` | `github_tail.py`, and pushing | yes |
| `OPENALEX_EMAIL` | polite-pool rate limits | recommended |
| `SERPAPI_KEY` | `scholar_citations.py` | only for the Scholar step |

Hosts that must be reachable: `api.openalex.org`, `api.github.com`, `serpapi.com`.

## Tasks, in order

### 1. OpenAlex sweep

```
OPENALEX_EMAIL=<email> python harvest/openalex_citations.py
```

Produces `data/tail/citing-works.json`. Expect several thousand records; CTGAN alone
carries most of them. Commit the raw output as its own commit before doing anything
else with it.

### 2. GitHub tail

```
GITHUB_TOKEN=<token> python harvest/github_tail.py
```

Produces `data/tail/github-candidates-full.json`, merging with the 130 repos already
pooled. Code search allows 10 requests/minute and caps any single query at 1000
retrievable results — the 13 patterns in the script exist to partition around that cap.
If a pattern returns exactly 1000, it is truncated: split it further (add a
`language:` or `size:` qualifier) rather than accepting the loss. Commit the output.

### 3. Google Scholar (optional, needs a paid key)

```
SERPAPI_KEY=<key> python harvest/scholar_citations.py
```

Run this *after* OpenAlex and treat its extra rows as a delta — that delta is theses,
workshop papers and non-English work, and it is the part worth reading by hand.
If Scholar serves a CAPTCHA, stop. Do not attempt to solve or evade it.

### 4. Curation pass — the actual work

Pooled records are not index entries. Promote them into new shards
(`data/shards/03-*.json` and up), one shard per source and wave.

**Citing a paper is not using the software.** CTGAN is cited constantly as prior art by
work that never runs it. Before promoting anything, find evidence of actual use: a named
synthesizer class, an install line, a linked repository, an SDMetrics score. Then set:

- `evidence` — the specific thing you found (a file path, a quoted method line)
- `integration` — `api_user`, `vendored_source`, `baseline_only`, or `citation_only`
- `confidence` — `high` only if you read the source. Metadata alone is `medium` at best.

Write `summary` from the abstract, README or page text — one to three sentences.
**Never write a summary from a title.** If you could not fetch the source, say so in
`needs` and set `confidence: "low"` rather than guessing. An entry flagged for follow-up
is useful; a confident wrong summary poisons the index.

Schema and the three controlled vocabularies are in `README.md`. Do not invent new facet
values silently — if something genuinely does not fit, add the value to the README
vocabulary in the same commit that first uses it, and flag it in your report.

Work in batches of roughly 50. Put each batch on its own branch (e.g. `curate/03-openalex`),
rebuild, and open one PR per batch — do not merge your own curation PRs; leave them for
Saman to review. Do not attempt the whole tail in one pass.

### 5. Rebuild

```
python build.py
```

Regenerate after each curation batch and include `data/sdv-index.json` in that batch's PR,
together with the shards that changed — never as a standalone commit, so the generated
index and the reviewed shards always match.

## Rules

- Shards are **append-only**. Never rewrite a completed shard; corrections go in a new
  shard, or as a targeted edit with the reason in the commit message.
- `data/sdv-index.json` is **generated**. Never hand-edit it.
- Keep pools in `data/tail/` separate from curated entries in `data/shards/`. Do not bulk
  promote a pool into a shard to raise the entry count.
- Raw harvest output (tasks 1–3) and script fixes go directly to `main`. Curation batches
  (task 4) go on their own branch and open a PR — do not merge your own curation PRs;
  leave them for Saman. One logical change per commit throughout.
- Do not delete anything without asking Saman.

## Open items inherited from the previous session

1. `ewvanwinkle/SyntheticDataVault` (shard 02) — a 2017 GTRI project whose two-line README
   mentions neither SDV nor the DSAA'16 paper. The link was inferred from the repository
   name and date, which is not good enough. Inspect the source and either confirm it as a
   reimplementation or drop the entry.
2. Four case studies in shard 01 (ING, MAPFRE, UCLA fraud, AML banking) point at listing
   pages rather than permanent URLs. Resolve them; they are marked `needs`.
3. Several shard 02 entries remain `medium`/`low` where classification rests on a file
   path rather than a read of the code.

## What to report back

Counts per source, how many pooled records survived the use-versus-citation filter and
how many did not, any facet values you had to add, any script bugs you fixed, and the
list of entries you left flagged in `needs`. Be specific about what you could not verify.
