# SDVworld-index

A broad index of the Synthetic Data Vault (SDV) ecosystem: papers, theses, blog posts,
articles, documentation, case studies, and code repositories, each with a pointer, a short
summary, and three-facet categorization.

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
| `summary` | 1-3 sentences, written from the source |
| `authors`, `year`, `venue`, `doi` | present where applicable |
| `source_channel` | how the entry was found |
| `sdv_component[]` | sdv, ctgan, rdt, sdmetrics, sdgym, copulas, deepecho, tgan, enterprise |
| `use_case[]` | see vocabulary below |
| `industry[]` | see vocabulary below |
| `integration` | how a code/paper entry uses SDV; see vocabulary below |
| `evidence` | the specific proof of use — a file path or a quoted line |
| `confidence` | high = read the source; medium/low = metadata only |
| `needs` | open verification task, if any |
| `duplicate_of` | id of the canonical entry, when this record retires a duplicate |

## Vocabularies

**kind**: paper, preprint, thesis, blog_post, announcement, case_study, news_article,
documentation, code_repo, tutorial, video, dataset_benchmark, forum, patent

**use_case**: privacy_protection, anonymization, data_sharing, software_testing,
data_augmentation, class_imbalance, ml_training, benchmarking_evaluation,
scenario_simulation, method_research, compliance, education

**industry**: healthcare_bio, finance_insurance, government_public, academia,
energy_utilities, telecom, retail_ecommerce, transportation, manufacturing, software,
cross_industry

**integration** (how an entry relates to SDV software): api_user (imports/uses the
library), vendored_source (copies SDV/CTGAN source in-tree), derivative_work (extends or
modifies that source into a new tool), baseline_only (runs it only as a comparison
baseline), citation_only (cites but does not run it), source_work (an SDV anchor paper
itself), name_collision (false-positive match, unrelated to SDV), unclear (use suspected
but unverified).

## Tiers

- **Curated** — hand-summarized, `confidence: high` or `medium`.
- **Tail** — auto-listed from mechanical search (GitHub code search, citation graphs).
  As of 2026-08-14, GitHub code search returns 2,180 non-fork hits for
  `from sdv.single_table import` and 1,420 for `CTGANSynthesizer`.
