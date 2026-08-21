# Record schema and controlled vocabularies

This file defines what an index entry is. `tests/validate.py` parses the vocabulary
lists below out of this file rather than restating them, so this is executable
documentation: add a value here and validation accepts it, remove one and validation
starts rejecting it. Keep the `**facet**: a, b, c` shape and the blank line that ends
each list.

Orientation for a new maintainer is in `README.txt`; the working procedure is in
`docs/agent-guide.md`.

## Three layers, and which one owns a field

A record passes through three hands, and knowing which hand owns a field tells you
where to fix it.

1. **Curator-owned** — written into a shard by whoever read the source. Judgment and
   attribution both live here. `build.py` never overwrites a value a shard supplies.
2. **Build-joined** — filled in by `build.py` from the raw pools in `data/tail/`, but
   only where the shard left the field empty. These are the figures that drift, so
   freezing them into a shard would make the index stale. `data/impact.json` overrides
   the join for a handful of hand-checked citation counts.
3. **Generated** — exists only in `data/sdv-index.json` or in the page. Never in a shard.

| field | layer | notes |
|---|---|---|
| `id` | curator | stable slug, unique across the whole index. Keys corrections, BibTeX filenames and `data/impact.json`; a collision makes `build.py` refuse to write |
| `title` | curator | as the source spells it |
| `url` | curator | the pointer to the artifact |
| `kind` | curator | see vocabulary below |
| `summary` | curator | 1-3 sentences written from the source, ending with the SDV clause |
| `authors` | curator | real named publication authors, or real named repository owners and contributors. Handles, bots, service accounts and organization bylines are excluded, except `DataCebo Team` |
| `affiliations` | curator | positionally aligned with `authors`; `null` where an author's affiliation is unconfirmed. One element may name several organizations separated by semicolons |
| `affiliation_types[]` | curator | one sector per distinct organization; aligned with the organization sequence, not with `authors` |
| `affiliation_countries[]` | curator | one full country name per distinct organization, same alignment |
| `source_channel` | curator | how the entry was found |
| `sdv_component[]` | curator | which SDV *software* is involved |
| `sdv_concept[]` | curator | which SDV *idea* is involved |
| `use_case[]` | curator | what the synthetic data is for |
| `industry[]` | curator | the sector the work belongs to |
| `integration` | curator | the mechanism by which the entry relates to SDV software |
| `importance` | curator | 0-6, how central SDV is; orthogonal to `integration` |
| `evidence` | curator | the specific proof — a file path, a section reference, a quoted line |
| `confidence` | curator | `high` = read the source; `medium`/`low` = metadata only |
| `needs` | curator | the open verification task or unresolved judgment call, if any |
| `countries` | curator | ISO codes, where the source records them. Distinct from `affiliation_countries` and rarely used |
| `venue` | curator | curator-owned deliberately: OpenAlex is wrong about fourteen venues. Joined only when a shard leaves it empty |
| `doi` | curator | same |
| `duplicate_of` | curator | id of the canonical entry. The record stays in its shard as an audit trail and is not an index entry |
| `override` | curator | marks a correction record: only the changed fields, merged over the original by id. Never appears in the built index |
| `year` | joined | publication year, or repository creation year for code |
| `stars`, `forks`, `commits`, `contributors` | joined | GitHub metrics, from `data/tail/github-repos.json` |
| `cited` | joined | citation count, from `data/tail/openalex-citations.json` or `data/impact.json` |
| `popularity` | generated | not stored anywhere. The page derives it from stars, forks, contributors and citations, log-compressed onto one scale so code and papers compare. See `docs/site.md` |
| `aff_type`, `aff_region` | generated | derived in the page from the two affiliation lists. Not fields; do not put them in a shard |

Every base record in a numbered shard carries the first fourteen fields. A correction
record carries `id`, `override`, and only what changes.

## Alignment of the two affiliation lists

`affiliations` aligns with `authors`. `affiliation_types` and `affiliation_countries`
align with the distinct *organization* sequence derived from it: scan the
author-aligned list left to right, split each non-null value on semicolons, trim, and
keep the first occurrence of each organization. Index *i* in the two filter lists
describes organization *i* in that sequence.

    authors:                ["A. Kim", "B. Lee", "C. Park"]
    affiliations:           ["Harvard University; Korea University", "Harvard University", null]
    affiliation_types:      ["academic", "academic"]
    affiliation_countries:  ["United States", "South Korea"]

Each resolved organization contributes exactly one type and one country. Hospitals are
`nonprofit`, including university and government hospitals. A multinational company
uses one canonical home country rather than every country it operates in. A literal
`unknown` is used only when a named organization could not be resolved; a null author
affiliation contributes no organization and no facet value.

`curate/affiliation_facets.py` regenerates the two lists from `affiliations` and reports
drift; run it without `--write` first.

## The SDV clause

Every `summary` ends with a clause that says why the entry is in this index. It has two
slots, always in this order:

1. **which part of SDV** — a concept for papers, a component or file path for repositories;
2. **how it is used** — run, vendored, extended, compared against, or only described.

The clause is written from the source, never from the title, and never from the fact that a
citation exists. If the source could not be read, say so in `needs` and set
`confidence: "low"` rather than guessing.

## Vocabularies

**kind**: paper, preprint, thesis, blog_post, announcement, case_study, news_article,
documentation, code_repo, tutorial, video, dataset_benchmark, forum, patent

**use_case**: privacy_protection, anonymization, data_sharing, software_testing,
data_augmentation, class_imbalance, ml_training, benchmarking_evaluation,
scenario_simulation, method_research, compliance, education, fairness_bias,
open_science_reproducibility, imputation

**industry**: healthcare_bio, finance_insurance, government_public, academia,
energy_utilities, telecom, retail_ecommerce, transportation, manufacturing, software,
cross_industry, construction_infrastructure, cybersecurity, environment_climate,
media_recommenders, chemicals_materials, education_sector, agriculture, aerospace, real_estate

**affiliation_types**: academic, corporate, government, nonprofit, other, unknown

Countries are stored as standardized full names, for readable JSON and pivot tables.
The alignment rule for these two lists is above.

Prefer the domain over `academia`. A paper is academic by construction, so `academia` on its
own loses the field the work is actually about; use it only when no domain applies.

**sdv_component** (which software): sdv, ctgan, rdt, sdmetrics, sdgym, copulas, deepecho,
tgan, enterprise

**sdv_concept** (which idea): relational_hma, mode_specific_normalization,
conditional_sampling, gaussian_copula, vine_copula, tvae, par_sequential, metadata_schema,
constraints, reversible_transforms, ml_efficacy_eval, quality_report, benchmark_harness

**integration** (the mechanism): api_user (imports/uses the library), vendored_source
(copies SDV-family source in-tree), derivative_work (extends or modifies that source into a
new tool), baseline_only (runs it only as a comparison baseline), agent_skill (ships SDV as
an executable capability for an AI agent to invoke — working code inside a skill or
instruction file, with no dependency declared by the host repository), citation_only (cites
but does not run it), foundation (the artifact is SDV itself: a library, an anchor paper, or
a thesis behind one), inherited (SDV arrived inside a vendored third party rather than by a
decision to embed it — the intermediary is usually an index entry in its own right),
port
(reimplements SDV's design in another language, carrying no SDV source), name_collision
(false-positive match, unrelated to SDV), unclear (use suspected but unverified).

`unclear` may not carry `confidence: high`. If the library link could not be established,
the doubt belongs in a sortable field rather than only in prose — and `importance` still
scores how central the SDV-family *method* is, so the two fields stay independent.

`agent_skill` is not a synonym for documentation. The test is whether the artifact packages
SDV as a capability an agent is expected to execute on demand — a runnable pattern, a
routing rule about when SDV may be used — as opposed to prose that merely records that SDV
exists, which is `citation_only`.

**importance** (the weight), 0-6:

| | meaning |
|---|---|
| 6 | First-party — produced by the SDV project itself. Provenance, not a rating; see below |
| 5 | SDV *is* the work — a fork, a direct reimplementation, a language binding |
| 4 | Load-bearing — the result depends on running SDV; remove it and the work does not stand |
| 3 | One of several — a compared baseline, one generator or metric among many |
| 2 | Contextual — SDV's method or evaluation protocol is described and adopted, not run |
| 1 | Passing citation, related work only |
| 0 | Name collision or otherwise unrelated |

**6 records provenance, not centrality.** It marks everything produced by the SDV project
itself: the MIT DAI and DataCebo research papers and theses, the `sdv-dev` repositories,
and DataCebo's own documentation, blog, case studies and announcements. The test is who
made it, not how much SDV is in it — a first-party paper that predates SDV, or a docs page
that runs nothing, is still a 6.

This means 6 is not one step above 5; it is a different axis occupying the top slot, so the
whole 0-5 range stays available for judging third-party work on its merits. Nothing curated
from the tails reaches 6, because the tails are third-party by construction. A tail entry
that genuinely looks first-party is a `needs`, not a 6.

`importance` is otherwise independent of `integration`. A repository can vendor the whole
CTGAN source and still be a 3 because it runs it as one baseline among several; a paper can
run nothing and still be a 2 because it adopts CTGAN's evaluation protocol. A re-read that
finds either field misjudged should correct it with `"override": true` and name the prior
value in `evidence`.

Do not invent facet values. Propose an addition; it is added to this file in the same commit
that first uses it.

## Tiers

- **Curated** — hand-summarized, `confidence: high` or `medium`, lives in `data/shards/`.
- **Tail** — auto-listed from mechanical search (GitHub code search, citation graphs),
  lives in `data/tail/`, pending curation. The page shows it alongside curated entries,
  always badged and never as curated, and the importance floor hides it at any value above
  0. `build.py` never reads it as index content.
