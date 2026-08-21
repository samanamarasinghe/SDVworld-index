================================================================================
SDVworld-index -- README for whoever takes this over
Index v0.999999999 | 4918 curated entries | 118 shards | written 2026-08-21
================================================================================

Published at   https://samanamarasinghe.github.io/SDVworld-index/
Repository     https://github.com/samanamarasinghe/SDVworld-index

WHAT THIS IS

  An index of the Synthetic Data Vault (SDV) ecosystem: papers, preprints,
  theses, blog posts, articles, documentation, case studies, tutorials,
  datasets and code repositories. Every entry carries a pointer, a short
  summary, and categorization on several facets -- what kind of artifact it is,
  which part of SDV it involves, how it uses it, what it is for, and which
  industry it belongs to.

  It is modelled on data/publications.json in mit-commit/commit-website, and
  widened well beyond papers.

WHAT MAKES IT WORTH ANYTHING

  Every summary ends with a clause saying why the entry is in the index: which
  part of SDV is involved, and how it is used -- run, vendored, extended,
  compared against, or only described. That clause is written from the source
  after reading it. Never from the title, never from the fact that a citation
  exists.

  Citing a paper is not using the software. CTGAN is cited constantly as prior
  art by work that never runs it, and separating those two cases is most of the
  labour in this project. An entry that admits it could not be verified is
  useful; a confident wrong summary poisons the index, because nobody
  downstream can tell the difference.

  If you keep one rule from this file, keep that one.

NOT EVERY ENTRY MEETS THAT STANDARD, AND YOU NEED TO KNOW WHICH

  3833 of the 4918 entries were curated by a batch model in August 2026 rather
  than by a person, in two runs: the repository tail (1335 records, shards 108
  to 119) judged from evidence files, and the paper citation tail (2382 records,
  shards 124 to 143) judged from whatever text could be obtained. They carry
  auto_curated.reviewed = false and are otherwise ordinary entries.

  The two halves are not equally reliable. A paper carries evidence_tier saying
  what was read -- full_text, abstract_context or metadata_only -- and its
  confidence is capped by that tier in code; 1799 entries now rest on full text.
  A repository carries no such marker.

  They were checked mechanically and the hard rules held: none claims to run
  SDV without a code hit outside a dependency file. Fifteen repositories were
  read against their evidence by hand and two of the fifteen were wrong, both in
  the same direction -- a runs-SDV integration on a repository that never
  imports SDV.

  Treat that tier as better than a keyword classifier and not equivalent to a
  curator's read. The evidence each judgment was made from is in
  harvest/evidence/<owner>__<repo>.json, so any one of them can be checked in
  under a minute. TODO.txt section 1 has the full account.


================================================================================
TEN MINUTES TO ORIENTED
================================================================================

  git clone https://github.com/samanamarasinghe/SDVworld-index
  cd SDVworld-index
  python3 build.py            # merge shards, print counts; writes nothing
  python3 tests/validate.py   # schema, vocabulary and cross-checks
  python3 -m http.server 8000 # then open http://localhost:8000/

  Everything is Python 3 standard library. There is nothing to install and no
  build step for the site. Opening index.html as a file:// URL will NOT work --
  the page fetches its data, and browsers block that on file://. Use the http
  server.

  python3 tests/validate.py --online --scope all   probes every pointer in the
  index and both raw pools; about ninety seconds. Run it before pushing
  anything that touches data.


================================================================================
HOW THE DATA FLOWS
================================================================================

    harvest/*.py                mechanical search: OpenAlex citations,
        |                        GitHub code search, Google Scholar
        v
    data/tail/*.json            RAW POOLS. Big, noisy, uncurated. Not the
        |                        index. The site lists them alongside curated
        |                        entries, always badged, and hides them at any
        |                        importance floor above 0.
        |
        |   a human or agent reads the actual source and records judgment
        v
    data/shards/NNN-*.json      CURATED ENTRIES. Append-only. This is the
        |                        real content of the project: the summaries,
        |                        the facets, the evidence, the confidence.
        |
        |   build.py            merges shards in filename order, dedupes on
        |                        url, applies corrections, and joins the
        |                        fields that drift (year, stars, forks,
        |                        commits, contributors, citations, DOI)
        v
    data/sdv-index.json         GENERATED. Never hand-edit.
        |
        v
    index.html + assets/js/sdv-index.js   -->   GitHub Pages

  Two directions of authority, and it matters which is which:

    Judgment flows from the shards.  A curator's value always wins; the join
    only ever fills a field a shard left empty.

    Metadata flows from the pools.  Star counts and citation counts drift, so
    they are joined at build time rather than frozen into a shard. venue and
    doi are exceptions and stay curator-owned, because OpenAlex is wrong about
    fourteen venues.


================================================================================
WHERE EVERYTHING LIVES
================================================================================

  README.txt              this file
  TODO.txt                the work queue: what is missing, unverified,
                          uncurated, and deliberately closed
  AGENTS.md               entry point for an AI agent with write access; a
                          pointer file, twenty lines
  VERSION                 stamped onto the page footer via build-info.json

  index.html              the whole site. One page, no framework, no build.
  assets/js/sdv-index.js  filter and render controller, ~1100 lines
  assets/css/style.css
  assets/img/sdv-logo.svg

  build.py                shards -> data/sdv-index.json
  tests/validate.py       every check that runs before a push

  data/shards/NNN-*.json  curated entries, append-only, one shard per wave
  data/sdv-index.json     GENERATED index the page reads
  data/build-info.json    GENERATED version/date/count stamp for the footer
  data/impact.json        hand-checked citation counts that override the join
  data/tail/              raw harvest pools -- see data/tail/README.md
  data/*.json, data/*.csv author and affiliation tables -- see docs/data-files.md

  harvest/                one script per source; see harvest/README.md
  curate/                 maintenance and worklist tooling; see curate/README.md
  curate/archive/         retired lane briefs and one-off scripts, kept for
                          provenance, not expected to run

  docs/schema.md          THE RECORD SCHEMA AND THE CONTROLLED VOCABULARIES.
                          tests/validate.py parses the vocabulary lists out of
                          this file, so it is executable documentation: change
                          a list here and validation changes with it.
  docs/agent-guide.md     the working rules -- curation procedure, correction
                          shards, parallel lanes, and the access routes that
                          are known to work
  docs/site.md            how index.html and sdv-index.js fit together, and
                          the filter semantics, which are not obvious
  docs/open-questions.md  judgment calls awaiting the owner's ruling, each with
                          the provisional value already applied
  docs/data-files.md      what every file under data/ contains and who produces it


================================================================================
THE FIVE RULES
================================================================================

  1. SHARDS ARE APPEND-ONLY. Never rewrite a completed shard. A re-read that
     finds a field misjudged appends a correction record to a NEW shard,
     carrying only the fields that change plus "override": true, and naming the
     prior value in `evidence` so the change is auditable.

  2. A CORRECTION MUST SORT AFTER EVERY SHARD IT CORRECTS. build.py merges in
     filename order and matches corrections by id, so an override naming an id
     that no earlier shard has defined is counted as orphaned and dropped.
     Take the next number above the highest that exists anywhere in the
     repository -- not above your own lane's.

  3. NEVER HAND-EDIT A GENERATED FILE. data/sdv-index.json and
     data/build-info.json are outputs. CI rebuilds the index on every push to
     main that touches shards or build.py.

  4. NEVER INVENT A FACET VALUE. Propose it; it is added to docs/schema.md in
     the same commit that first uses it. Parallel curators each coining their
     own near-synonyms is the way this index quietly degrades.

  5. DO NOT DELETE ANYTHING WITHOUT ASKING THE OWNER. That includes pool rows
     that look like junk.


================================================================================
ADDING AN ENTRY
================================================================================

  1. Find a candidate in data/tail/, or from anywhere else.
  2. FETCH AND READ THE SOURCE. Find the specific proof of use: a named
     synthesizer class, an install line, a linked repository, an SDMetrics
     score, a results row.
  3. Check it is not already in the index, by DOI and by fuzzy title -- a
     preprint and its published version are separate records with separate
     DOIs, and exact title matching misses the pair. Use a similarity ratio
     around 0.80, not equality.
  4. Write the record. Fields and vocabularies are in docs/schema.md. The
     summary is one to three sentences from the source, ending with the SDV
     clause. `evidence` holds the actual quoted line or file path.
     `confidence: high` only if you read the source; metadata alone is medium
     at best; if you could not read it, say so in `needs` and use low.
  5. Append it to a new shard: data/shards/<next-number>-<lane-name>.json.
     One shard per batch of roughly 50, not one shard per entry.
  6. python3 tests/validate.py, then python3 build.py, and check the entry
     count went up by exactly what you added.
  7. Push. On main, CI rebuilds data/sdv-index.json for you.

  When the published version of something already in the index turns up, the
  PUBLISHED version is the version of record: add it, fold any unique content
  from the preprint entry into it, and retire the preprint entry.


================================================================================
TRAPS THAT HAVE ALREADY COST TIME
================================================================================

  * VERIFY EVERY PUSH WITH A BYTE DIFF.
        git fetch origin main && git show origin/main:PATH | diff - LOCALPATH
    Two silent corruptions got through review: a dropped letter in a title
    ("regime" for "regimes"), and a duplicated "academic" in an affiliation
    type list. validate.py matches titles fuzzily at 0.70 and sailed past the
    first. Semantic equality is not enough; compare bytes. This applies to
    files small enough to eyeball, because both of those were.

  * EDIT SHARDS BY TEXT SPLICE, NOT BY JSON ROUND-TRIP. Loading and re-dumping
    reflows the whole file and buries your one-line change in a thousand-line
    diff. Assert that every surviving record is byte-identical to its old self,
    so the diff is pure insertion or deletion.

  * A CORRECTION SHARD CANNOT RETIRE A SAME-URL DUPLICATE. build.py drops a
    same-url duplicate at read time, before the id index is built, so an
    override targeting the loser is orphaned. Same url: mark duplicate_of in
    the loser's own shard. The correction rule only covers duplicate ids on
    different urls.

  * A ZERO-HIT REGEX RESULT IS A REASON TO LOOK HARDER, NOT TO DROP THE PAPER.
    Some PDF extractors render CTGAN as "CctGAN"; one of the most
    CTGAN-dependent papers in the set reported zero hits case-sensitively.
    Watch for the mirror-image trap too: "TV ?AE" matches "DistV AE", and
    "\bSDV\b" matches "synthetic data variance".

  * DO NOT LOOP A RETRY THAT WRITES TO THE SAME OUTPUT FILE. A 503 on the
    second attempt once overwrote a good 1.4MB PDF with 114 bytes of error
    text. Fetch to a temp name, check the first four bytes are %PDF, then move.

  * A 200 IS NOT EVIDENCE OF A PDF. Springer's constructed content/pdf URL
    returns the paywalled HTML page with a 200. Check the content type. Search
    engines also see body text that we do not, so a search snippet showing
    real content does not mean the URL is fetchable.

  * THE PAGE'S FILTER SEMANTICS ARE MIXED, DELIBERATELY. The checkbox facets
    are include filters: one match is enough. The two button groups
    (Academic / Non-academic / Affiliation-not-found, and Americas / Europe /
    Asia / Africa-Oceania) are the opposite -- they PERMIT, so unlighting one
    removes every entry carrying even one value of that kind. A record with no
    value in a group must therefore match nothing in it, or it gets vetoed by a
    group it has no business being in. That bug shipped once and hid 668
    entries. docs/site.md has the details; the relevant guard is the NO_NONE
    set in assets/js/sdv-index.js.

  * MISCITATION IS A PROPERTY OF THIS LITERATURE, not a transcription error.
    Nine cases and counting: a "CreditGAN" that does not exist, TGAN cited to
    Goodfellow, RDT credited to an unrelated privacy paper. Record the paper's
    own wording in `evidence` and never correct it silently.


================================================================================
CREDENTIALS AND HOSTS
================================================================================

  GITHUB_TOKEN      harvest/github_tail.py, and pushing. A fine-grained
                    read-only PAT from the environment; never committed.
  OPENALEX_API_KEY  or OPENALEX_EMAIL -- rate limits on the citation lane.
                    Recommended, not required. OpenAlex now meters requests.
  SERPAPI_KEY       only for harvest/scholar_citations.py. Paid.

  harvest/repo_evidence.py needs no token at all: it reads public repositories
  through codeload.github.com tarballs and git clone.

  Hosts that must be reachable: api.openalex.org, api.github.com,
  codeload.github.com, serpapi.com. Full paper text also needs arxiv.org,
  doi.org, and api.unpaywall.org.


================================================================================
WHERE THE JUDGMENT LIVES
================================================================================

  The facets are mechanical. The two fields that carry actual opinion are
  `integration` (the mechanism by which an entry touches SDV) and `importance`
  (0-6, how central SDV is to it), and they are INDEPENDENT. A repository can
  vendor the entire CTGAN source and still be a 3 because it runs it as one
  baseline among several; a paper can run nothing and still be a 2 because it
  adopts CTGAN's evaluation protocol. Judging weight from mechanism gets it
  backwards, and it is the most common mistake.

  importance 6 is not a rating. It records first-party provenance -- produced
  by the SDV project itself -- so nothing curated from the pools can reach it.

  Conventions that have accumulated for specific recurring shapes are in
  docs/agent-guide.md. They exist because the same argument came up four times.
  Read them before inventing a new one, and if a case genuinely has no
  convention, record the provisional call plus a `needs` and add it to
  docs/open-questions.md rather than blocking.

  A number of those calls are open right now, listed in
  docs/open-questions.md and summarized in TODO.txt section 2. They are the
  owner's, not yours.
