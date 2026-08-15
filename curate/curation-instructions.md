# Curation worklist — instructions for the extraction agent

You are given `harvest/curation-worklist.csv`: **874 works that cite an SDV paper**,
one per row, pre-filled with identifying/pointer columns. Your job is to decide, for
each row, whether the work **actually uses** SDV-ecosystem software — and if so, to
capture the facts needed to add it to the index.

Return the **same CSV** with the empty output columns filled. Do **not** change the
pre-filled columns, and do **not** reorder or drop rows (keep `openalex_id` as the key).

---

## The one rule that matters: citing is not using

Most of these works cite CTGAN or the SDV paper as **prior art** and never run any SDV
software. Those are **not** index entries. Before you record a use, find concrete
evidence that the authors actually ran SDV / CTGAN / RDT / SDMetrics / SDGym / Copulas /
DeepEcho / TGAN. Acceptable evidence, strongest first:

1. A linked code repo that imports it — `from sdv...`, `CTGANSynthesizer`, `import sdmetrics`, a vendored `ctgan/` tree.
2. An install/usage line in the paper or README — `pip install sdv`, "we used the SDV library", a named synthesizer class.
3. A reported **SDMetrics** score, or SDGym benchmark run.
4. A methods sentence describing generation with one of these tools.

"We compare against CTGAN [12]" with no run, or a generic mention of synthetic data, is
**citation_only** → set `uses_sdv = no`.

---

## Round-trip protocol

- Work in **batches of 50** (the `batch` column, 1–18). Do one batch, return it, repeat.
- Fill every output column for every row you process. If a field does not apply, leave it
  empty — except `uses_sdv`, `confidence`, and (when `no`) a short `evidence` note, which
  are always required.
- Keep the file as CSV, UTF-8, same header. Multi-value fields use a **pipe** `|`.
  Author lists use a **semicolon** `;`.

---

## Where to look (per row)

1. Open `url_landing` (or `url_pdf` if present) and read the **abstract + methods**.
2. Search the paper text for: `SDV`, `Synthetic Data Vault`, `CTGAN`, `TVAE`, `SDMetrics`,
   `SDGym`, `RDT`, `Copulas`, `DeepEcho`, `PAR`, `GaussianCopula`.
3. Find a **code link** (GitHub/GitLab/Zenodo) in the paper or its OpenAlex record. Open
   it and grep the source for the imports/classes above. This is where `uses_sdv = yes`
   is usually confirmed — record the repo in `code_url` and the exact file/line in `evidence`.
4. If you cannot fetch the source at all: `uses_sdv = unclear`, `confidence = low`, and say
   what you could not reach in `needs`.

---

## Output columns

| column | required | allowed values / format |
|---|---|---|
| `uses_sdv` | yes | `yes` \| `no` \| `unclear` — the gate. `no` = citation-only. |
| `integration` | if `uses_sdv=yes` | `api_user` (imports the library) \| `vendored_source` (copies the code in-tree) \| `baseline_only` (runs it only as a comparison baseline) \| `citation_only` \| `unclear` |
| `evidence` | yes | The specific thing you found: a quoted method sentence, a code path (`repo/path/file.py`), an install line, or an SDMetrics score. For `no`, one phrase such as "cites CTGAN as prior art, no run". |
| `sdv_component` | if `uses_sdv=yes` | pipe-list from: `sdv` `ctgan` `rdt` `sdmetrics` `sdgym` `copulas` `deepecho` `tgan` `enterprise` |
| `use_case` | if `uses_sdv=yes` | pipe-list from the **use_case** vocabulary below |
| `industry` | if `uses_sdv=yes` | pipe-list from the **industry** vocabulary below |
| `kind` | if `uses_sdv=yes` | one of the **kind** vocabulary below (usually `paper`, `preprint`, or `thesis`) |
| `summary` | if `uses_sdv=yes` | 1–3 sentences written from the abstract/methods/README. **Never** from the title. Plain text. |
| `code_url` | if found | URL of the associated code repo |
| `confidence` | yes | `high` = you read the paper's full text or the code. `medium` = abstract/metadata only. `low` = could not fetch. |
| `needs` | if applicable | any open follow-up, e.g. "PDF paywalled — confirm from repo" |
| `source_url` | yes | the exact URL you actually read to reach your verdict |

---

## Controlled vocabularies (use these values verbatim)

**kind**: paper, preprint, thesis, blog_post, announcement, case_study, news_article,
documentation, code_repo, tutorial, video, dataset_benchmark, forum

**use_case**: privacy_protection, anonymization, data_sharing, software_testing,
data_augmentation, class_imbalance, ml_training, benchmarking_evaluation,
scenario_simulation, method_research, compliance, education

**industry**: healthcare_bio, finance_insurance, government_public, academia,
energy_utilities, telecom, retail_ecommerce, transportation, manufacturing, software,
cross_industry

If something genuinely does not fit a vocabulary value, do **not** invent one — put your
proposed value in `needs` (e.g. "industry: propose 'legal'") and leave the field empty.

---

## Worked examples

A real use (kept):

```
uses_sdv = yes
integration = vendored_source
evidence = synth/snsynth/pytorch/nn/ctgan/ctgan.py (CTGAN copied into the DP toolkit)
sdv_component = ctgan
use_case = privacy_protection
industry = academia|government_public
kind = code_repo
summary = OpenDP's SmartNoise DP toolkit ships a CTGAN implementation among its DP synthesizers, putting CTGAN inside a mainstream differential-privacy library.
code_url = https://github.com/opendp/smartnoise-sdk
confidence = high
source_url = https://github.com/opendp/smartnoise-sdk
```

A citation, not a use (dropped):

```
uses_sdv = no
evidence = survey; lists CTGAN in a table of tabular GANs, no run
confidence = high
source_url = https://doi.org/10.1109/tnnls.2022.3229161
```

---

## What I do with your CSV

Rows where `uses_sdv = yes` become new curated entries in a fresh shard
(`data/shards/03-*.json` and up), one shard per batch, then `python build.py` and a PR.
`no`/`unclear` rows stay in the tail. So: be strict on the gate, exact on the vocab, and
honest with `confidence` — a flagged `low`/`needs` row is useful; a confident wrong
summary is not.
