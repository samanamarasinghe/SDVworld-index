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
tests/validate.py                    schema, vocabulary and pointer checks
data/shards/NN-*.json                curated entries, append-only, one shard per wave
data/tail/github-repos.json          pooled repositories with metrics, mostly uncurated
data/tail/openalex-citations.json    pooled citing works with first-pass verdicts
data/tail/openalex-abstracts.json    abstracts, keyed by OpenAlex id; the page never reads it
curate/facet_lift.py                 lifts bibliographic facets from both pools; no judgment
curate/strip_joined_fields.py        removes from shards anything build.py can join
curate/open-questions.md             judgment calls awaiting a ruling; each has a provisional
harvest/repo_evidence.py             per-repo SDV evidence bundles for a curating agent
harvest/README.md                    source-by-source notes and the curation rule
harvest/openalex_citations.py        citing works for the 5 anchor papers
harvest/resolve_s2.py                folds the Semantic Scholar edges into the citation tail
harvest/github_tail.py               partitioned GitHub code search
harvest/scholar_citations.py         Google Scholar via SerpAPI
```

All the harvest scripts have now been run and their bugs fixed. `tests/validate.py` checks
the result: schema, controlled vocabulary, and that every pointer resolves to what the entry
says it does. Run it before opening a PR; `--online --scope all` probes every pointer in
about ninety seconds.

**The repository tail is closed.** Roughly 1,400 pooled repositories, almost all with no
stars, will not be read. They stay in `data/tail/` at low importance. Do not restart that
lane: indexing them unread would put clauses in the index that came from no source, which is
the one rule everything else here rests on.

**Shards carry curated attribution as well as judgment.** Every base entry in a numbered shard
stores `authors` and a positionally aligned `affiliations` list; repositories use `authors`
for real named owners and contributors. Unknown affiliations are JSON null, and handles,
bots, service accounts and organization bylines are excluded except for `DataCebo Team`.
Year, stars and citation counts are still joined from the pools because they drift. `venue`
and `doi` stay curator-owned because OpenAlex is wrong about fourteen venues.
`curate/strip_joined_fields.py` removes only the regenerable fields.

All the scripts are Python 3 standard library only. Nothing to install.

## Credentials and network

| need | for | required |
|---|---|---|
| `GITHUB_TOKEN` | `github_tail.py`, and pushing | yes |
| `OPENALEX_API_KEY` or `OPENALEX_EMAIL` | rate limits on the citation lane | recommended |
| `SERPAPI_KEY` | `scholar_citations.py` | only for the Scholar step |

`harvest/repo_evidence.py` needs **no token**: it reads public repositories through
`codeload.github.com` tarballs and `git clone`, neither of which authenticates. A token
only buys the code-search API and higher rate limits. Use a fine-grained read-only PAT
from the environment, never a value committed to this repository.

Hosts that must be reachable: `api.openalex.org`, `api.github.com`, `codeload.github.com`,
`serpapi.com`. Full paper text additionally needs `arxiv.org` and `doi.org`.

## Tasks, in order

### 1. OpenAlex sweep

```
OPENALEX_API_KEY=<key> python harvest/openalex_citations.py
```

Produces `data/tail/openalex-citations.json`. Merges rather than overwrites, preserving
`curation`, `source_channel` and `resolved_via` on records already there. Commit the raw
output as its own commit before doing anything else with it.

### 2. GitHub tail

```
GITHUB_TOKEN=<token> python harvest/github_tail.py
```

Produces `data/tail/github-repos.json`. Code search allows 10 requests/minute and caps any
single query at 1000 retrievable results — the 13 patterns in the script exist to partition
around that cap. If a pattern returns exactly 1000, it is truncated: split it further (add a
`language:` or `size:` qualifier) rather than accepting the loss. Commit the output.

### 3. Google Scholar (optional, needs a paid key)

```
SERPAPI_KEY=<key> python harvest/scholar_citations.py
```

Run this *after* OpenAlex and treat its extra rows as a delta — that delta is theses,
workshop papers and non-English work, and it is the part worth reading by hand.
If Scholar serves a CAPTCHA, stop. Do not attempt to solve or evade it.

## 4. Curation pass — the actual work

#### Schema and vocabulary

README.md owns both, and is the only place either is defined. Read it before curating.
The parts most often got wrong:

- Every `summary` ends with the **SDV clause** — which part of SDV, and how it is used.
  Written from the source, never from the title, never from the bare existence of a
  citation. If you could not read the source, say so in `needs` and set `confidence: low`.
- `importance` and `integration` are **independent**. One scores how central SDV is, the
  other records only the mechanism. Judging weight from mechanism gets it backwards.
- `importance` 6 is not a rating you assign. It marks first-party provenance, so nothing
  curated from the tails reaches it; your ceiling is 5.
- `unclear` may not carry `confidence: high`.

If a re-read finds `importance`, `integration`, `confidence` or the `url` misjudged,
correct it with `"override": true`, naming the prior value in `evidence` so the change is
auditable. Corrections are matched by id and must sort after the shard they correct.

#### Evidence before promotion

Pooled records are not index entries. Promote them into new shards, one shard per source
and wave.

**Citing a paper is not using the software.** CTGAN is cited constantly as prior art by
work that never runs it. Before promoting anything, find evidence of actual use: a named
synthesizer class, an install line, a linked repository, an SDMetrics score. Then set:

- `evidence` — the specific thing you found (a file path, a quoted method line)
- `integration` — the mechanism, from the vocabulary in README.md
- `confidence` — `high` only if you read the source. Metadata alone is `medium` at best.

Write `summary` from the abstract, README or page text — one to three sentences.
**Never write a summary from a title.** If you could not fetch the source, say so in
`needs` and set `confidence: "low"` rather than guessing. An entry flagged for follow-up
is useful; a confident wrong summary poisons the index.

Do not invent facet values silently — if something genuinely does not fit, add the value to
the README vocabulary in the same commit that first uses it, and flag it in your report.

Work in batches of roughly 50. Put each batch on its own branch, rebuild, and open one PR
per batch — do not merge your own curation PRs; leave them for Saman to review.

**Check what is already curated before selecting a batch.** Unmerged branches are not
visible from `main`, so a batch selected against `main` alone will re-curate repositories
another agent has already done. List the `curate/*` branches and exclude their shards too.

#### Open questions

`curate/open-questions.md` holds judgment calls that could not be settled from the source.
Each carries the provisional choice already applied, so the index stays consistent while
the question is open. Add to it rather than blocking, and never invent a resolution to an
item already listed there.

A ruling belongs where a curator will meet it — the vocabulary in README.md, a workflow
rule here, the data in a correction shard — not left in the notes file. A convention
recorded only in `open-questions.md` cannot bind an agent that branched before reading it.

### 5. Rebuild

```
python build.py            # validate only
python build.py --write    # write data/sdv-index.json; CI passes this
```

`.github/workflows/build-index.yml` rebuilds `data/sdv-index.json` automatically when
shards change on `main`, and reports drift on a pull request without writing. Do not commit
the generated index by hand; run `build.py` locally to check your shard parses and dedupes
as expected.

## Rules

- Shards are **append-only**. Never rewrite a completed shard; corrections go in a new
  shard, or as a targeted edit with the reason in the commit message.
- `data/sdv-index.json` and `data/tail/facet-lift.json` are **generated**. Never
  hand-edit either; regenerate with `build.py --write` and `curate/facet_lift.py`. A
  missing copy of facet-lift.json is not data loss.
- Keep pools in `data/tail/` separate from curated entries in `data/shards/`. Do not bulk
  promote a pool into a shard to raise the entry count.
- Raw harvest output (tasks 1–3) and script fixes go directly to `main`. Curation batches
  (task 4) go on their own branch and open a PR — do not merge your own curation PRs;
  leave them for Saman. One logical change per commit throughout.
- Do not delete anything without asking Saman.
- **A correction shard must sort after every shard it corrects.** `build.py` merges in
  filename order, so an `override` naming an id that a later shard has not yet defined is
  counted as orphaned and silently dropped. Number a correction above the highest shard in
  the repository, not above your own lane's.
- **Shard numbers are not reserved per lane and do not need to be.** Two shards sharing a
  number merge fine. Take the next number above the highest that exists, whichever lane put
  it there.

## Open items inherited from the previous session

1. `ewvanwinkle/SyntheticDataVault` (shard 02) — a 2017 GTRI project whose two-line README
   mentions neither SDV nor the DSAA'16 paper. The link was inferred from the repository
   name and date, which is not good enough. Inspect the source and either confirm it as a
   reimplementation or drop the entry.
2. Two case studies in shard 01 (UCLA fraud, AML banking) point at listing pages rather
   than permanent URLs. They share those URLs with their siblings, so `build.py` drops them
   before the id index and their corrections orphan. Resolving the permalinks fixes both.
3. Several shard 02 entries remain `medium`/`low` where classification rests on a file
   path rather than a read of the code.

## Running agents in parallel

Lanes that can run concurrently:

| lane | unit of work | notes |
|---|---|---|
| repos | `harvest/repo_evidence.py --slice K/N` | no token needed; tarball or partial clone |
| papers | a slice of `data/tail/openalex-citations.json` | needs open network for full text |

Shard numbering is not partitioned per agent — see the rules above. Take the next number
above the highest that exists, and remember that a correction has to sort after what it
corrects, which is a property of the whole repository rather than of your lane.

One lane must stay serial: **vocabulary**. Agents *propose* facet values and never invent
them. A single arbiter adds an approved value to README.md in the commit that first uses
it. Parallel agents each coining their own near-synonyms is the way this index degrades.

## What to report back

Counts per source, how many pooled records survived the use-versus-citation filter and
how many did not, any facet values you had to add, any script bugs you fixed, and the
list of entries you left flagged in `needs`. Be specific about what you could not verify.
