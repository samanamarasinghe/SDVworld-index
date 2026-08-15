# SDVworld-index

A broad index of the Synthetic Data Vault (SDV) ecosystem: papers, theses, blog posts,
articles, documentation, case studies, and code repositories, each with a pointer, a short
summary, and multi-facet categorization.

Modelled on `data/publications.json` in `mit-commit/commit-website`, widened beyond papers.

## Layout

- `data/shards/NN-*.json` — append-only harvest shards, one per source channel/wave.
- `build.py` — merges shards into `data/sdv-index.json`, deduplicating on `url`.

Shards are never rewritten once complete; new waves add new shard files.

## Record schema

| field | notes |
|---|---|
| `id` | stable slug, unique |
| `title` | |
| `url` | pointer to the artifact |
| `kind` | see vocabulary below |
| `summary` | 1-3 sentences written from the source, ending with the SDV clause (see below) |
| `authors`, `year`, `venue`, `doi` | present where applicable |
| `affiliations`, `countries` | institutions and ISO country codes, where the source records them |
| `contributors` | GitHub logins, for code entries; never written into `authors` |
| `source_channel` | how the entry was found |
| `sdv_component[]` | which SDV *software* is involved; see vocabulary below |
| `sdv_concept[]` | which SDV *idea* is involved; see vocabulary below |
| `use_case[]` | see vocabulary below |
| `industry[]` | see vocabulary below |
| `integration` | the mechanism by which an entry relates to SDV software |
| `importance` | 0-5, how central SDV is to the entry; orthogonal to `integration` |
| `evidence` | the specific proof — a file path, a section reference, a quoted line |
| `confidence` | high = read the source; medium/low = metadata only |
| `needs` | open verification task, if any |
| `duplicate_of` | id of the canonical entry, when this record retires a duplicate |

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
media_recommenders, chemicals_materials, education_sector, agriculture

**sdv_component** (which software): sdv, ctgan, rdt, sdmetrics, sdgym, copulas, deepecho,
tgan, enterprise

**sdv_concept** (which idea): relational_hma, mode_specific_normalization,
conditional_sampling, gaussian_copula, vine_copula, tvae, par_sequential, metadata_schema,
constraints, reversible_transforms, ml_efficacy_eval, quality_report, benchmark_harness

**integration** (the mechanism): api_user (imports/uses the library), vendored_source
(copies SDV-family source in-tree), derivative_work (extends or modifies that source into a
new tool), baseline_only (runs it only as a comparison baseline), citation_only (cites but
does not run it), source_work (an SDV anchor paper or library itself), name_collision
(false-positive match, unrelated to SDV), unclear (use suspected but unverified).

**importance** (the weight), 0-5:

| | meaning |
|---|---|
| 5 | SDV *is* the work — anchor paper, the library itself, a fork or direct reimplementation |
| 4 | Load-bearing — the result depends on running SDV; remove it and the work does not stand |
| 3 | One of several — a compared baseline, one generator or metric among many |
| 2 | Contextual — SDV's method or evaluation protocol is described and adopted, not run |
| 1 | Passing citation, related work only |
| 0 | Name collision or otherwise unrelated |

`importance` is deliberately independent of `integration`. A repository can vendor the whole
CTGAN source and still be a 3 because it runs it as one baseline among several; a paper can
run nothing and still be a 2 because it adopts CTGAN's evaluation protocol. A re-read that
finds either field misjudged should correct it with `"override": true` and name the prior
value in `evidence`.

Do not invent facet values. Propose an addition; it is added to this file in the same commit
that first uses it.

## Tiers

- **Curated** — hand-summarized, `confidence: high` or `medium`.
- **Tail** — auto-listed from mechanical search (GitHub code search, citation graphs),
  pending curation into shards.
