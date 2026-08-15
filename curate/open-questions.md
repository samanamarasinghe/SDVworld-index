# Open questions for Saman

Queued during unattended curation runs. Nothing here blocks work — each item names
the provisional choice already made, so the index stays consistent either way. A
ruling either confirms it or triggers a correction patch.

Newest section last. Delete a resolved item, or record the ruling in place.

## 1. A distinct `integration` value for inherited relationships

**Provisional:** filed as `vendored_source` at `importance` 1–3.

Four entries so far relate to SDV only through a third party rather than directly:

- `jansel/pytorch-jit-paritybench` — crawled CTGAN modules out of tab-ddpm's
  vendored copy
- `jim-schwoebel/voiceome` — vendors the whole Allie framework, itself an index entry
- `Hannah37/ConDOR-ICLR25` — inherited tab-ddpm's entire baselines directory,
  vendored CTGAN tree and `rdt` pin included
- `bvanbreugel/deep_generative_ensemble` (batch D) — carries a copy of synthcity in
  `src/`, whose SDV plugins are the generators; `DGE_data.py` defaults to
  `model_name='ctgan'`, so the ICML 2023 results run on CTGAN through synthcity

`vendored_source` is technically true of all four but says the wrong thing: it
implies a deliberate decision to embed SDV, when in each case SDV arrived as a
passenger. A value such as `inherited` or `transitive` would separate them.

Against adding it: four of 165 curated entries. `importance` 1 covered most of what
mattered for the first three, but the fourth is a 4 — the paper's headline
experiments depend on the inherited CTGAN — so importance no longer stands in for
the distinction.

## 2. Canonical copies for three duplicate pairs

**Provisional:** both copies indexed, `needs` set on each, no `duplicate_of`.

- `privacy-enhancing-technologies/SynEval` and `SCU-TrustworthyAI/SynEval`
- `ParkLabML/DP-MERF` and `frhrdr/dp-merf`

Each pair is near-identical content under two owners. Picking the canonical one
means judging which account is authoritative — an author's copy, a lab's copy, a
research group's later home for the same work — and that is not decidable from the
code alone.

## 3. An `aerospace` industry value

**Provisional:** `Three-Buddy-Problem/exoplanet-quest-web` filed as `academia`.

It generates synthetic exoplanet records from the NASA archive — for data scarcity,
not privacy. `academia` is not wrong but loses the domain. One entry does not
justify a vocabulary value; a second would.

## 4. Negative filters for the pooling search

**Provisional:** false positives recorded at `importance` 0 rather than dropped, so
a later sweep does not re-examine them.

Two substring accidents recur and will keep re-pooling until `harvest/github_tail.py`
excludes them:

- `abs_e2687gwsdv` — a conda temp-directory fragment, in `DTiapan/ai-agents-handbook`
  and `Salim-Lysiun/ARNN`
- `sdvae` — the stable-diffusion VAE, in `MischaD/BeyondFID`

Four of 121 curated entries so far are pure substring accidents, and the rate should
rise as the remaining tail is almost entirely zero-star repositories.

## 5. Treatment for the 348 `req`-only pooled repositories

**Provisional:** none — not yet reached.

348 of the remaining repositories matched only a dependency line, with no import
anywhere in the tree; 272 of those also have zero stars. Reading each one properly
costs the same as a substantive entry and can only ever support one sentence and
`importance` 1.

A mechanical pass — one templated clause naming the dependency file and the pinned
version, `confidence: low` — would turn roughly eight batches into one. The cost is
that these entries would not be read, which is a departure from the rule that every
clause comes from a source.

Batch D is a data point in favour of still reading them. Six landed there and the
readings diverged: `spack/pypi-to-spack-package` turned out to record the SDV family
being packaged for HPC through Spack, `nphdang/Pred-LLM` pins the family because
synthcity's evaluation code pulls it in, `serval-uni-lu/constrained-attacks` names
`ctgan` and `tvae` training regimes in its experiment runner and so is `unclear`
rather than dependency-only, and `JianhanZhang/PyCFRL`'s only CTGAN block sits inside
a triple-quoted string. A template would have flattened all four into the same
sentence. Reading each cost roughly a tenth of a substantive entry, not the same.

## 6. Repositories that failed to clone — resolved

**Ruling:** transient. Nothing to decide.

All six retried cleanly in batch D with no change to `harvest/repo_evidence.py`'s
timeout or fetch strategy, and all are now indexed. Keep the pattern of leaving a
failure pooled and retrying it in the next batch rather than blocking on it.

## 7. A `benchmark_target` integration value

**Provisional:** `SWE-bench-Live/submission` filed as `citation_only`, `importance` 2.

The repository holds coding-agent trajectories and evaluation logs for
SWE-bench-Live. Two of its task instances, `sdv-dev__SDV-2532` and
`sdv-dev__SDV-2546`, come from SDV's own issue tracker, so the stored logs are SDV's
pytest output over `test_ctgan.py`, `test_par.py` and `test_hma.py`.

No code in the repository imports SDV, which is what `citation_only` records — but
SDV's test suite is executed inside the harness, which `citation_only` denies. The
mechanism is neither using the library nor merely citing it: SDV is the *subject*
being repaired.

Against adding it: one entry. It will recur, though — SWE-bench-style harnesses that
draw tasks from SDV's issue tracker are a growing category, and the same reading
applies to any agent-benchmark repository that lands in the tail.

## 8. Versioned release repositories of one program

**Provisional:** all three NeuroMiner repositories indexed separately, each with a
`needs` pointing at the others.

`neurominer-git/NeuroMiner_1.2`, `NeuroMiner_1.3` and `NeuroMiner` (1.4) are three
published releases of one MATLAB toolbox, each a whole repository rather than a tag.
Their SDV usage is the same simulation module.

Indexing all three is defensible and, in this case, informative: 1.2 still pins the
pre-1.0 `sdv.tabular` API while 1.3 and 1.4 carry the migrated
`GaussianCopulaSynthesizer` version of the same file, so the set records the SDV 1.0
migration inside one project. Against: 1.3 and 1.4 look byte-identical in that
module, which is three index entries for what a reader would call one tool.

A rule would help either way — collapse to the newest release with `duplicate_of` on
the rest, or keep every release repository that shows a distinct SDV API generation.

## 9. Code that names SDV but cannot run

**Provisional:** filed case by case — `citation_only` when the code is inert by
construction, `unclear` when it looks intended to run but cannot.

Three entries so far name SDV in code that never executes:

- `JianhanZhang/PyCFRL` (batch D) — a `CTGANSynthesizer` block inside a
  triple-quoted string in an example, no `sdv` import, no declared dependency.
  Filed `citation_only`, `importance` 1.
- `Cukurikik/Omni` (batch E) — an `omni_sdv_engine.py` registry mapping five
  synthesizer names to descriptions and speed hints, as strings. Nothing imports
  `sdv`. Filed `citation_only`, `importance` 2.
- `cosmic-hydra/zane` (batch E) — `from sdv.tabular import GAN`, a class SDV has
  never exported, in a synthetic-patient module. Filed `unclear`, `importance` 2.

The split is defensible but it is a judgment each time, and the category is growing
as generated code reaches the tail. Two candidate rules: treat any non-executing
reference as `citation_only` regardless of intent, which is simple and loses the
distinction between a deliberate comment and a broken import; or add a value for
code that targets SDV's API but does not work against any released version, which
keeps the distinction and is a genuinely useful signal about how SDV is
misremembered.

`repo-zorai` in shard 03 is the near neighbour: a skill file calling names current
SDV no longer exposes, filed `agent_skill`. The difference there is that the names
were once real.
