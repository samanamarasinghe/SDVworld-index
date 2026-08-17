# Agent guide

Working instructions for an agent with GitHub write access to
`samanamarasinghe/SDVworld-index`, a shell, and network access. `AGENTS.md` at the root
points here.

Owner: Saman Amarasinghe. Report back to him, not to whoever queued the task.

Read in this order: `README.txt` (what the project is and how it fits together),
`docs/schema.md` (the record schema and the controlled vocabularies), this file (how to
work), `TODO.txt` (what is actually left). `docs/open-questions.md` holds judgment calls
that are his to make, not yours.

## Ground rules

- **Shards are append-only.** Never rewrite a completed shard. A re-read that finds
  `importance`, `integration`, `confidence` or the `url` misjudged appends a correction
  record — `"override": true`, only the fields that change, the prior value named in
  `evidence` — to a new shard.
- **A correction must sort after every shard it corrects.** `build.py` merges in
  filename order and matches corrections by id, so an override naming an id no earlier
  shard has defined is orphaned and dropped, with a warning. Take the next number above
  the highest that exists anywhere in the repository, not above your own lane's.
  Shard numbers are not reserved per lane and two shards sharing a number merge fine.
- **A correction cannot retire a same-url duplicate.** `build.py` drops a same-url
  duplicate at read time, before the id index exists, so the override orphans. For a
  same-url duplicate, mark `duplicate_of` in the loser's own shard.
- **`data/sdv-index.json` and `data/build-info.json` are generated.** Never hand-edit
  them. `.github/workflows/build-index.yml` rebuilds and commits them when shards or
  `build.py` change on `main`, and reports drift on a pull request without writing.
- **Never invent a facet value.** Propose it; a single arbiter adds it to
  `docs/schema.md` in the commit that first uses it. Parallel agents each coining their
  own near-synonyms is how this index degrades.
- **Do not delete anything without asking him.** That includes pool rows that look
  like junk.
- **Verify every push with a byte diff.**
  `git fetch origin main && git show origin/main:PATH | diff - LOCALPATH`.
  Two silent corruptions have got through review this way — a dropped letter in a title,
  a duplicated `"academic"` in an affiliation type list. `validate.py` matches titles
  fuzzily at 0.70 and sailed past the first. Do this even for a file small enough to
  eyeball, because both of those were.
- **Edit shards by text splice, not by JSON round-trip.** Round-tripping reflows the
  file and buries a one-line change. Assert every surviving record is byte-identical to
  its old self so the diff is pure insertion or deletion.
- **Pushing through the GitHub connector:** `create_or_update_file` with the blob sha
  from `git rev-parse HEAD:<path>` for a whole file. Note that the connector can only
  write a whole file, so any edit means re-emitting every byte of it — which is why the
  byte diff is not optional, and why a one-line fix to a thousand-line file is better
  batched with other work than done alone.
- One logical change per commit. Raw harvest output and script fixes go to `main`;
  curation batches go on a branch and open a PR — do not merge your own curation PRs.

## Curation, which is the actual work

**Citing a paper is not using the software.** CTGAN is cited constantly as prior art by
work that never runs it, and separating those cases is most of the labour here.

Before promoting anything out of a pool:

1. **Fetch and read the source.** Find the specific proof: a named synthesizer class, an
   install line, a linked repository, an SDMetrics score, a results row.
2. **Sweep for duplicates first, by DOI and by fuzzy title, against every shard record.**
   A preprint and its published version are separate records with separate DOIs, and
   exact title matching misses the pair — use a similarity ratio around 0.80. This sweep
   has caught a duplicate that an index-wide sweep could not, because the twin was not
   in the index yet. Never skip it.
3. Write the record per `docs/schema.md`. `summary` is one to three sentences from the
   source, ending with the SDV clause. `evidence` quotes the actual line. `confidence:
   high` only if you read the source; metadata alone is `medium` at best; if you could
   not read it, say so in `needs` and use `low`. An entry flagged for follow-up is
   useful; a confident wrong summary poisons the index.
4. Batches of roughly 50, one shard per batch, then `python3 tests/validate.py` and
   `python3 build.py` — check the entry count rose by exactly what you added.

**Check what is already curated before selecting a batch.** Unmerged branches are not
visible from `main`, so a batch selected against `main` alone will re-curate work
another agent has already done. List the `curate/*` branches and exclude their shards.

**When the published version of something already indexed turns up**, the published
version is the version of record: add it, fold any unique content from the preprint
entry into it, and retire the preprint entry.

**A retracted work stays in the index** with the retraction stated in its summary and in
`evidence`. Where a publisher's galley 404s but Crossref still resolves the DOI, check
the landing page for a retraction blanking.

**Open questions.** A case with no convention gets the provisional call, a `needs`
string, and a section in `docs/open-questions.md`. Never invent a resolution to an item
already listed there. A ruling belongs where a curator will meet it — the vocabulary in
`docs/schema.md`, a rule in this file, the data in a correction shard — not left in the
notes file, because a convention recorded only in the notes cannot bind an agent that
branched before reading it.

## Judgment conventions

`importance` and `integration` are **independent**. One scores how central SDV is, the
other records only the mechanism. Judging weight from mechanism gets it backwards, and
it is the most common mistake. `importance` 6 is not a rating you assign — it marks
first-party provenance, so nothing curated from the pools reaches it; your ceiling is 5.
`unclear` may never carry `confidence: high`.

Conventions that accumulated because the same argument came up repeatedly:

- **TGAN is not CTGAN.** TGAN (Xu & Veeramachaneni 2018, arXiv 1811.11264) is a
  different work. Check which Xu paper is cited before keying an entry to `ctgan`.
- **Any model set containing CopulaGAN is the SDV tabular API**, library named or not,
  because CopulaGAN ships only in SDV.
- **CTGAN constructor parameter names in a hyperparameter table prove the `sdv-dev`
  package was run**, with no library named: `embedding_dim`, `generator_dim`,
  `discriminator_dim`, `generator_lr`, `discriminator_lr`, `generator_decay`,
  `discriminator_decay`, `discriminator_steps`.
- **The adopted-but-not-run pattern** — CTGAN's mode-specific normalization or
  conditional design reimplemented in prose while a different generator runs, or no
  experiment at all — is `citation_only` 2.
- `derivative_work` 5 when a paper builds a *named variant* on CTGAN. (Whether an
  *unnamed* modification qualifies is open; see `docs/open-questions.md`.)
- `baseline_only` 4 rather than 3 when a paper both benchmarks CTGAN and builds on its
  conditional vector. MTGAN is the precedent.
- `citation_only` 2 when a paper cites CTGAN as the GAN-era prior art it departs from.
- Benchmarking a descendant such as CTAB-GAN+ rather than CTGAN itself is
  `citation_only`, not `baseline_only`.
- `api_user` **4** when the whole empirical program is SDV; `api_user` **3** when SDV
  powers one experiment inside a paper about something else.
- Running an SDV-family *tool* outranks a comparison role: a paper that runs SDGym while
  merely benchmarking CTGAN is `api_user` 4.
- A paper that runs a generator only to reject it is still `baseline_only`.
- `importance` **1** when CTGAN sits in an undifferentiated citation list in an
  off-domain paper.
- **A compound name containing a CTGAN-ish token predicts composition more often than
  derivation.** A pipeline that runs CTGAN unmodified as a stage is `api_user`.
- **"Positions itself against CTGAN" is not "builds on CTGAN".** Check for an actual
  results row before calling anything `baseline_only` or `derivative_work`.
- **Miscitation is a property of this literature**, nine cases and counting: a
  "CreditGAN" that does not exist, TGAN cited to Goodfellow, RDT credited to an
  unrelated privacy paper. Record the paper's own wording in `evidence` and never
  correct it silently.
- **Year comes from OpenAlex `publication_year`** even where the printed issue year
  differs, so that ids and the build-time join stay consistent.
- **Named derivatives are usually invisible in metadata.** Ten of the first forty-five
  were named variants whose names appear nowhere in an abstract. This is the argument
  for reading full text.

## Getting at full text

Route by **access**, not by publisher: MDPI is open access but bot-blocked, and Springer
is half free.

- **MDPI**: `mdpi.com` 403s everything, but the CDN `mdpi-res.com` does not. Build the
  path from the DOI `10.3390/<abbrev><vol><iss><art>`:
  `https://mdpi-res.com/d_attachment/<journal>/<journal>-<vol:02d>-<art:05d>/article_deploy/<journal>-<vol:02d>-<art:05d>.pdf`,
  trying suffixes ``, `-v2`, `-v3`. The article number pads to **five** digits. Journal
  slug is the DOI abbreviation except e->entropy, app->applsci, s->sensors,
  math->mathematics, su->sustainability, w->water.
- **SciTePress**: `https://www.scitepress.org/Papers/<year>/<pid>/<pid>.pdf`, where
  `pid` is characters 2:8 of the DOI suffix. Year must match the conference year.
- **PMC**: Unpaywall's PMC urls are often missing the `PMC` prefix. Add it and use the
  legacy host `www.ncbi.nlm.nih.gov/pmc/articles/PMC<id>/`. PMC blocks curl, but
  `https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML` serves the full
  text; Europe PMC's `fulltextRepo` endpoint 403s.
- **Institutional repositories** (HAL, ORBi, Lirias, university handles) need one hop:
  scrape the landing page for `bitstream|/download|retrieve|\.pdf` and probe those.
- **Unpaywall** (`api.unpaywall.org/v2/<doi>?email=...`) is free and unmetered and is
  the right first stop for `is_oa` and `oa_locations`. OpenAlex now meters requests.
- **A 200 is not evidence of a PDF.** Springer's constructed `content/pdf/<doi>.pdf`
  returns the paywalled HTML page with a 200. Check the content type. Springer also
  cloaks for search crawlers, so a search snippet showing real body text does not mean
  the url is fetchable.
- **Mechanical first, then web search.** Unpaywall and OpenAlex find volume; a web
  search on the residual finds the preprint OpenAlex has no record of at all. When a
  sibling preprint is not found by title, try the author or the distinctive project
  name — titles diverge between preprint and published version far enough to defeat
  fuzzy matching.
- **Always run a positive control before reporting a negative search result.** The
  controls that work here: CTGAN itself (arXiv 1907.00503) and CARTGen-IR (2506.02811).
- **Behind his institutional login**, via a browser session: navigate to
  `https://doi.org/<doi>`, wait, then read the page. Not being signed in yields the
  abstract page *silently* — about 5KB of text with a plausible `Abstract:` block and no
  body. Check the length; under ~10KB means no full text. ACM serves no HTML body at
  all. For those, he downloads the PDF and uploads it to the chat, which is faster than
  any fetching route.

## Fetching and scanning mechanics

- arXiv PDF url is `https://arxiv.org/pdf/<id>` from the `10.48550/arXiv.<id>` DOI. curl
  with a browser user-agent; `urllib` gets a 403. Then `pypdf`, which installs with
  `pip install --break-system-packages`. Allow 90s for large PDFs.
- **Never loop a retry that writes to the same output file.** A 503 on the second
  attempt once overwrote a good 1.4MB PDF with 114 bytes of error text. Fetch to a temp
  name, check the first four bytes are `%PDF`, then move.
- **Loose pattern to find, tight pattern to judge.**
  Loose: `/C?ct[- ]?GAN|CTGAN|CT-GAN|CTAB|TVAE|TV ?AE|\bSDV\b|Synthetic Data Vault|Copula/gi`.
  Tight: `\bCT-?GAN\b|\bCTGAN\b|\bCctGAN\b|\bTVAE\b|\bTV AE\b|\bSDV\b|Synthetic Data Vault|Veeramachaneni|Xu et al|CTAB`.
- **Three regex traps, each of which cost a re-scan**: `TV ?AE` matches "DistV AE";
  `\bSDV\b` matches "synthetic data variance"; and some extractors render CTGAN as
  `CctGAN`, so one of the most CTGAN-dependent papers in the set reported zero hits
  case-sensitively. **A zero-hit result is a reason to look harder, never to drop.**
- Roughly ten papers per turn is the real ceiling, and fetching is not the constraint.
  Do not push past it by shrinking the digest you read — the near-misses were caught by
  reading more, not less.
- Judge papers from the same group together; they reuse each other's setups.
- Do not drop a candidate on its title alone.

## Harvest

Raw pools only; nothing here produces index entries. Per-script notes are in
`harvest/README.md`, output schemas in `docs/data-files.md`.

    OPENALEX_API_KEY=<key> python3 harvest/openalex_citations.py   # citing works
    GITHUB_TOKEN=<token>   python3 harvest/github_tail.py          # code search
    SERPAPI_KEY=<key>      python3 harvest/scholar_citations.py    # optional, paid

Commit raw output as its own commit before doing anything with it. OpenAlex first: it is
free, complete for indexed venues, and carries the DOIs that make every later merge
cheap. Treat Scholar's extra rows as the delta — theses, workshop papers, non-English
work — and read them by hand. If Scholar serves a CAPTCHA, stop; do not work around it.

**The repository tail is closed.** About 1400 pooled repositories, almost all with no
stars, will not be read. They stay in `data/tail/` at low importance. Do not restart that
lane: indexing them unread would put clauses in the index that came from no source,
which is the one rule everything else here rests on.

## Rebuild

    python3 build.py            # validate and report only
    python3 build.py --write    # write data/sdv-index.json and data/build-info.json

## Running lanes in parallel

Concurrent lanes: repositories (`harvest/repo_evidence.py --slice K/N`, no token needed)
and papers (a slice of `data/tail/openalex-citations.json`, needs open network). Slice a
paper lane on a **stable hash of the work id**, never on position in the remaining list:
positional round-robin reshuffles every slice as soon as one shard lands, and papers move
between sessions mid-run.

One lane must stay serial: **vocabulary**. Agents propose values; one arbiter adds them.

## What to report back

Counts per source. How many pooled records survived the use-versus-citation filter and
how many did not. Any facet value you had to add. Any script bug you fixed. The entries
you left flagged in `needs`. Be specific about what you could not verify.
