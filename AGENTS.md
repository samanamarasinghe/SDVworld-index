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
data/tail/github-repos.json           2019 repos, pooled + metrics, not yet curated
data/tail/openalex-citations.json     874 citing works, first-pass curation verdicts
curate/facet_lift.py                  lifts bibliographic facets from both pools; no judgment, no fetching
curate/open-questions.md              judgment calls awaiting a ruling; each has a provisional applied
harvest/repo_evidence.py              per-repo SDV evidence bundles for a curating agent
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

`harvest/repo_evidence.py` needs **no token**: it reads public repositories through
`codeload.github.com` tarballs and `git clone`, neither of which authenticates. A token
only buys the code-search API and higher rate limits. Use a fine-grained read-only PAT
from the environment, never a value committed to this repository.

Hosts that must be reachable: `api.openalex.org`, `api.github.com`, `codeload.github.com`,
`serpapi.com`. Full paper text additionally needs `arxiv.org` and `doi.org`.

## Tasks, in order

### 1. OpenAlex sweep

```
OPENALEX_EMAIL=<email> python harvest/openalex_citations.py
```

Produces `data/tail/openalex-citations.json`. Expect several thousand records; CTGAN alone
carries most of them. Commit the raw output as its own commit before doing anything
else with it.

### 2. GitHub tail

```
GITHUB_TOKEN=<token> python harvest/github_tail.py
```

Produces `data/tail/github-repos.json`, merging with the 130 repos already
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

#### The SDV clause

Every `summary` ends with a clause saying why the entry is in this index, in two slots:

1. **which part of SDV** — an `sdv_concept` for papers, an `sdv_component` or file path
   for repositories;
2. **how it is used** — run, vendored, extended, compared against, or only described.

Write it from the source. Never from the title, and never from the bare fact that a
citation exists. If you could not read the source, say so in `needs` and set
`confidence: "low"` rather than guessing.

#### Importance

`importance` (0-6, defined in README.md) records how central SDV is to the entry and is
**independent of `integration`**, which records only the mechanism. A repository can
vendor the entire CTGAN source and still be a 3 because it runs it as one baseline among
several; a paper can run nothing and still be a 2 because it adopts CTGAN's evaluation
protocol. Judging weight from mechanism alone gets these backwards.

**6 is not a curator's rating.** It is reserved for SDV itself — the anchor papers and
the `sdv-dev` libraries — so that a first-party artifact can never be confused with a
third party that merely depends on one. Nothing you curate from the tails reaches 6; the
ceiling for judged work is 5. If a tail entry genuinely looks first-party, that is a
`needs`, not a 6.

If a re-read finds `importance`, `integration` or `confidence` misjudged — SDV turns out
to be central to the implementation, or to be a passing mention in related work — correct
it. A correction is a patch line with `"override": true` naming the prior value in
`evidence`, so the change is auditable rather than silent.

#### Evidence before promotion

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

Schema and the controlled vocabularies are in `README.md`. Do not invent new facet
values silently — if something genuinely does not fit, add the value to the README
vocabulary in the same commit that first uses it, and flag it in your report.

Work in batches of roughly 50. Put each batch on its own branch (e.g. `curate/03-openalex`),
rebuild, and open one PR per batch — do not merge your own curation PRs; leave them for
Saman to review. Do not attempt the whole tail in one pass.

**Check what is already curated before selecting a batch.** Unmerged branches are not
visible from `main`, so a batch selected against `main` alone will re-curate repositories
another agent has already done. List the `curate/*` branches and exclude their shards too.

#### Open questions

`curate/open-questions.md` holds judgment calls that could not be settled from the source.
Each carries the provisional choice already applied, so the index stays consistent while
the question is open. Add to it rather than blocking, and never invent a resolution to an
item already listed there.

### 5. Rebuild

```
python build.py
```

`.github/workflows/build-index.yml` rebuilds `data/sdv-index.json` automatically when
shards change on `main`, and reports drift on a pull request without writing. You do not
need to commit the generated index by hand; run `build.py` locally to check your shard
parses and dedupes as expected.

## Rules

- Shards are **append-only**. Never rewrite a completed shard; corrections go in a new
  shard, or as a targeted edit with the reason in the commit message.
- `data/sdv-index.json` and `data/tail/facet-lift.json` are **generated**. Never
  hand-edit either; regenerate with `build.py` and `curate/facet_lift.py`. A missing
  copy of facet-lift.json is not data loss.
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
4. Shards 01 and 02 predate the `importance`, `sdv_concept` and `agent_skill` additions
   and carry none of them. Until they are re-read, those 61 entries sort below every
   later batch under importance ordering.

## Running agents in parallel

Patches apply in filename order, so parallel agents must not compete for numbers.
Reserve a block per agent up front: agent *k* owns `curate/patches/{k}00` through
`{k}99`. Within a block, number batches in the order they should apply.

Lanes that can run concurrently:

| lane | unit of work | notes |
|---|---|---|
| repos | `harvest/repo_evidence.py --slice K/N` | no token needed; tarball or partial clone |
| papers | a slice of `data/tail/openalex-citations.json` | needs open network for full text |
| shard re-read | the 61 existing shard entries | corrections, so expect `override` |

One lane must stay serial: **vocabulary**. Agents *propose* facet values and never invent
them. A single arbiter adds an approved value to README.md in the commit that first uses
it. Parallel agents each coining their own near-synonyms is the way this index degrades.

## What to report back

Counts per source, how many pooled records survived the use-versus-citation filter and
how many did not, any facet values you had to add, any script bugs you fixed, and the
list of entries you left flagged in `needs`. Be specific about what you could not verify.
