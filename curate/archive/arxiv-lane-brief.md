# arXiv lane brief — parallel curation

Self-contained instructions for a session curating part of the influential-arXiv
lane. Read this file, run `python curate/arxiv_lane.py <YOUR SLICE>`, and work only
that slice. 88 papers remain, split four ways.

## Your slice and your shard numbers

| slice | shard numbers | do not touch |
|---|---|---|
| A | 63-69 | any other range |
| B | 70-76 | any other range |
| C | 77-83 | any other range |
| D | 84-90 | any other range |

Shard numbers are reserved per slice so four sessions can push to `main`
concurrently without colliding. Never write a shard outside your range, never edit
a shard someone else wrote, and never touch `data/tail/`, `build.py`, `README.md`
or `AGENTS.md`.

## Workflow per batch (~7 papers, one shard)

1. `git clone https://github.com/samanamarasinghe/SDVworld-index.git`
2. `python curate/arxiv_lane.py <SLICE>` — take the next ~7 arXiv ids not yet done.
3. Fetch the PDFs in parallel: `curl -sL -A '<browser UA>' --max-time 90 -o pdfs/<id>.pdf https://arxiv.org/pdf/<id>`.
   `subprocess.Popen` for all seven at once; they all succeed in seconds.
4. `pip install pypdf --break-system-packages`, extract each to `.txt` once.
5. Scan, judge, write the shard (schema and vocabularies are in `README.md`).
6. `python tests/validate.py` — must print `OK: every check passed.`
7. `python build.py` — must report a clean entry count with 0 duplicate urls.
8. Push the shard file to `main` through the GitHub connector.
9. **Verify byte-for-byte**: `git fetch origin main && git show origin/main:data/shards/<file> | diff - <local file>`.
   This is not optional — see "How this has gone wrong before".

## Scanning: two passes, always

A **loose** pattern finds candidates; a **tight** pattern decides. Never judge from
the loose pass alone.

- loose: `C?ct[- ]?GAN|CTGAN|CT-GAN|CTAB|TVAE|TV ?AE|\bSDV\b|Synthetic Data Vault|sdv-dev|sdv\.dev|Veeramachaneni|Xu et al` (case-insensitive)
- tight: `\bCT-?GAN\b|\bCTGAN\b|\bCctGAN\b|\bTVAE\b|\bTV AE\b|\bSDV\b|Synthetic Data Vault|Veeramachaneni|Xu et al|CTAB`

Known false positives and negatives, all seen in this lane:

- `TV ?AE` matches **DistV AE**, **SurvivalV AE** and any `...tV AE`. One paper showed
  199 "hits" that were all its own model name.
- `\bSDV\b` matches **synthetic data variance**. One paper showed 81 such hits.
- pypdf renders one paper's CTGAN as **CctGAN**. A case-sensitive scan reported zero
  hits on one of the most CTGAN-dependent papers in the set.

**A zero-hit result is a reason to look harder, never a reason to drop a paper.**
The influential flag is unreliable per paper, but every flagged paper gets read.

## Judgment conventions

- `derivative_work` + importance 5 — the paper builds a *named variant* on CTGAN
  (MargCTGAN, DSF-GAN, AMC-GAN, SMOE-CTGAN). Importance 4 instead when CTGAN is one
  of several interchangeable substrates for a model-agnostic method.
- `api_user` + importance 4 — SDV runs and the result depends on it. Importance 3
  when SDV powers one experiment inside a paper about something else.
- `baseline_only` + importance 3 — CTGAN or TVAE is a compared generator.
  Importance 4 when the paper *also* builds on CTGAN's conditional vector or its
  mode-specific normalization.
- `citation_only` + importance 2 — CTGAN's method or evaluation protocol is
  described and adopted but not run, or it is the prior art the paper departs from.
  Importance 1 for a bare citation in an undifferentiated list.
- Benchmarking a descendant (CTAB-GAN+) rather than CTGAN itself is `citation_only`.
- Running a generator only to reject it is still `baseline_only`.
- **Check for an actual results row before calling anything baseline_only or
  derivative.** Two papers so far read like derivatives — a related-work section
  devoted to CTGAN, an architecture described by contrast with it — but never ran
  CTGAN at all. Those are `citation_only`.

Every entry: `source_channel: "semantic_scholar_discovery"`, `kind: "preprint"`,
`url` as `https://doi.org/10.48550/arXiv.<id>`, evidence quoting the actual
sentences with section or table numbers, `confidence: "high"` only when the body
was read. The summary describes the paper's own contribution first and ends with a
clause naming what part of SDV is involved and how.

## How this has gone wrong before

- An earlier parallel agent run wrote **24 fabricated DOIs** into one shard from
  memory instead of copying them. Every `url` must be built from the arXiv id in the
  worklist, never recalled.
- Re-typing a shard for the connector dropped a letter from a title. `validate.py`
  did **not** catch it — its title match is fuzzy at 0.70. Only the byte diff against
  `origin/main` found it.
- `validate.py` checks data, not rendering. Passing it does not mean the change
  reached `main` intact.

## Do not

- Do not write to memory files. One session owns the project handoff.
- Do not edit `curate/arxiv_lane.py` or this brief.
- Do not curate outside your slice, even if a paper looks interesting.
- Do not resolve an open question on your own: if a paper needs a convention that
  does not exist yet, record it in a `needs` field on the entry and say so.
