# Harvest scripts

Each script writes a raw pool into `data/tail/`. Nothing here produces index
entries directly: pooled records still need a summary and facet tags before they
are promoted into `data/shards/`.

| script | source | credential | notes |
|---|---|---|---|
| `openalex_citations.py` | OpenAlex | none | Cursor-paginates every citing work for the five anchor papers. Start here. |
| `github_tail.py` | GitHub code search | `GITHUB_TOKEN` | 13 partitioned patterns, since any one query caps at 1000 retrievable results. |
| `scholar_citations.py` | Google Scholar via SerpAPI | `SERPAPI_KEY` | Widest coverage of theses, workshop papers and non-English work. Paid. |

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
