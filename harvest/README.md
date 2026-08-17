# Harvest scripts

Each script writes a raw pool into `data/tail/`. Nothing here produces index
entries directly: pooled records still need a summary and facet tags before they
are promoted into `data/shards/`.

| script | source | credential | notes |
|---|---|---|---|
| `openalex_citations.py` | OpenAlex | none | Cursor-paginates every citing work for the five anchor papers. Start here. |
| `github_tail.py` | GitHub code search | `GITHUB_TOKEN` | 13 partitioned patterns, since any one query caps at 1000 retrievable results. |
| `github_identities.py` | GitHub profiles, repositories, contributors, and commits | `GITHUB_TOKEN` | Builds provenance-bearing JSON and CSV repo-author tables; public profile claims are labelled rather than treated as verified identity or employment. |
| `affiliation_normalizations.py` | ROR affiliation matcher plus curated aliases | none | Preserves GitHub's raw company text and builds canonical organization names with confirmation status, country, type, ROR ID, and evidence. |
| `public_name_normalizations.py` | generated repo-author identity table | none | Preserves raw public names, applies conservative display cleanup, groups simple case/punctuation/diacritic variants, and flags shared names without merging GitHub accounts. |
| `publication_identities.py` | OpenAlex, official publication pages, and the generated GitHub identity table | optional `OPENALEX_API_KEY` or `OPENALEX_EMAIL` | Builds publication-scoped author-affiliation JSON/CSV rows keyed by canonical SDVworld ID, with persistent author IDs, direct content/download links, raw and canonical values, evidence, and explicit source/normalization statuses. |
| `scholar_citations.py` | Google Scholar via SerpAPI | `SERPAPI_KEY` | Widest coverage of theses, workshop papers and non-English work. Paid. |

`github_identities.py` writes a resumable cache to
`data/tail/github-identities.json` and reviewable tables to
`data/github-repo-authors.json` and `data/github-repo-authors.csv`. It does not
request or store email addresses. A GitHub `User` can still be an automation
account, so the output keeps the API account type separate from a conservative,
evidence-labelled semantic classification. Use `name_status`,
`affiliation_status`, and their evidence URLs when deciding which rows need
manual corroboration.

Affiliations are normalized through `data/affiliation-normalizations.json`.
`affiliation_raw` always preserves the GitHub profile text. The canonical
`affiliation` is safe to group in a pivot table only when read together with
`affiliation_status`: `official_source_confirmed` cites an official source,
`ror_confirmed` means the ROR affiliation matcher selected the record with
`chosen=true`, and `normalized_unconfirmed` or `profile_stated_unconfirmed`
remains best-effort. Values such as “Student” and “Freelance” are labelled
`not_an_affiliation` and receive a null canonical affiliation.

Public names are normalized through `data/public-name-normalizations.json`.
`public_name_raw` preserves the GitHub profile or linked commit text, while
`public_name` is the pivot-friendly display value. Use
`name_normalization_status` to distinguish unchanged, reformatted,
variant-canonicalized, and invalid values. `same_name_github_account_count`
explicitly warns when multiple numeric GitHub IDs use the same canonical name;
those accounts are deliberately not merged.

`publication_identities.py` writes a resumable cache to
`data/tail/publication-identities.json` and reviewable outputs to
`data/publication-author-affiliations.json` and `.csv`. One row is one
publication-author-affiliation relationship; the JSON also includes one coverage
row per canonical SDVworld ID. This intentionally permits the same persistent
person to carry different affiliations in different publications.
OpenAlex authorship institutions are labelled `openalex_authorship_metadata`;
only mappings checked in the actual source receive `publication_stated`.
GitHub-hosted tutorials, documentation, and datasets reuse the numeric account
IDs and evidence from `github-repo-authors.json` rather than running a second
identity search. Direct PDFs are recorded when an open source exposes one;
paywalled content is never bypassed.

Small full-text corrections live in
`data/publication-author-affiliation-overrides.json`, keyed by canonical SDVworld
ID and one-based author position. Keep these overrides limited to claims that can
cite the publication or an official repository record; the generated rows retain
the evidence URL and locator.

## On Google Scholar

Scholar publishes no API, and its terms do not permit automated querying. Three
routes, in descending order of how well they scale:

1. **SerpAPI** (`scholar_citations.py`) — a licensed provider that queries
   Scholar on your behalf. Paid, keyed, reliable.
2. **Publish or Perish** — Harzing's free desktop tool. Paste the paper title,
   open its Cited by list, export CSV or BibTeX, drop the file in `data/tail/`.
   No key, no code, but manual per anchor paper.
3. **Direct scraping** (e.g. the `scholarly` package) — works for a few dozen
   requests, then Scholar begins serving CAPTCHAs. Not used here.

All three hit the same ceiling: a Cited by list stops at 1000 results, and
Scholar exposes no stable record id, so deduplication against OpenAlex falls
back to normalized-title matching.

## Order of operations

OpenAlex first — it is free, complete for indexed venues, and carries DOIs that
make every later merge cheap. Run Scholar second and treat its extra rows as the
delta: work Scholar knows about that OpenAlex does not. That delta is where the
grey literature lives, and it is the part worth reading by hand.

## Curation pass

Citing a paper is not using the software. CTGAN in particular is cited
constantly as prior art by work that never runs it. Before promoting a pooled
record, look for evidence of actual use: a named synthesizer class, an install
line, a linked repository, an SDMetrics score. Record that evidence in the
entry's `evidence` field and set `integration` to `api_user`, `vendored_source`,
`baseline_only`, or `citation_only`.
