# Open questions for Saman

Queued during unattended curation runs. Nothing here blocks work — each item names
the provisional choice already made, so the index stays consistent either way. A
ruling either confirms it or triggers a correction patch.

Newest section last. Delete a resolved item, or record the ruling in place.

## 1. A distinct `integration` value for inherited relationships

**Provisional:** filed as `vendored_source` at `importance` 1–3.

Seven entries so far relate to SDV only through a third party rather than directly:

- `jansel/pytorch-jit-paritybench` — crawled CTGAN modules out of tab-ddpm's
  vendored copy
- `jim-schwoebel/voiceome` — vendors the whole Allie framework, itself an index entry
- `Hannah37/ConDOR-ICLR25` — inherited tab-ddpm's entire baselines directory,
  vendored CTGAN tree and `rdt` pin included
- `bvanbreugel/deep_generative_ensemble` (batch D) — carries a copy of synthcity in
  `src/`, whose SDV plugins are the generators; `DGE_data.py` defaults to
  `model_name='ctgan'`, so the ICML 2023 results run on CTGAN through synthcity
- `spalabucr/synth-audit` (batch G) — vendors opendp/smartnoise-sdk, itself an index
  entry, whose `snsynth/pytorch/nn/ctgan/` is CTGAN and whose `DPCTGAN` subclasses it
- `BQ-QB/AML` (batch H) — vendors tab-ddpm, which carries a whole CTGAN package, as
  `Hannah37/ConDOR-ICLR25` did
- `mshubhankar/DP-DataGeneration-MissingData` (batch I) — SmartNoise again, this time
  as the DP baselines of a paper on generation under missing data

`vendored_source` is technically true of all seven but says the wrong thing: it
implies a deliberate decision to embed SDV, when in each case SDV arrived as a
passenger. A value such as `inherited` or `transitive` would separate them.

Against adding it: seven of 297 curated entries. `importance` 1 covered most of what
mattered for the first three, but four of the seven are now 3 or 4 — the results
depend on the inherited CTGAN — so importance no longer stands in for the
distinction. Two intermediaries account for six of the seven: opendp/smartnoise-sdk
and yandex-research/tab-ddpm. Both are themselves worth being index entries, which
is the argument for a value that points at the intermediary rather than at SDV.

## 2. Canonical copies for three duplicate pairs

**Provisional:** both copies indexed, `needs` set on each, no `duplicate_of`.

- `privacy-enhancing-technologies/SynEval` and `SCU-TrustworthyAI/SynEval`
- `ParkLabML/DP-MERF` and `frhrdr/dp-merf`

Each pair is near-identical content under two owners. Picking the canonical one
means judging which account is authoritative — an author's copy, a lab's copy, a
research group's later home for the same work — and that is not decidable from the
code alone.

## 3. An `aerospace` industry value — condition met

**Provisional:** both entries filed as `academia`.

- `Three-Buddy-Problem/exoplanet-quest-web` (shard 05) generates synthetic exoplanet
  records from the NASA archive, for data scarcity rather than privacy.
- `Pierciest/Exoplanet_classifier` (batch I) fits `GaussianCopulaSynthesizer` on a
  survey catalogue to extend it for downstream simulation.

The original note said one entry does not justify a vocabulary value and a second
would. The second has arrived. `academia` is not wrong for either — both are
research code — but it loses the domain in exactly the way `healthcare_bio` would if
every clinical entry were filed as `academia` too.

Whether the value should be `aerospace` or something wider like `space_astronomy` is
worth a moment: neither repository is about aircraft or launch vehicles, and
`JimmyJamJr/spoc2025` (batch F, rocket-launch weather) is the only entry so far that
`aerospace` would fit in the ordinary sense.

## 4. Negative filters for the pooling search

**Provisional:** false positives recorded at `importance` 0 rather than dropped, so
a later sweep does not re-examine them.

Five distinct kinds now, in eleven entries, and they will keep re-pooling until
`harvest/github_tail.py` excludes them:

1. **Build-path fragments.** `abs_e2687gwsdv`, a conda temp directory, now in
   **eleven** repositories: `DTiapan/ai-agents-handbook`, `Salim-Lysiun/ARNN`,
   `aaronGeb/tenx_week_two`, both `petpals` copies, `abhiramp1998/bias-mitigation-bank-marketing-ML`,
   `mbobbin/final_project`, `SvenjaGuhr/Character_Sound_Analysis`,
   `Christopher-Win/Studiverse`, `HannaSaffi/ArtSphereWebApp` and two repositories by
   `GGSimmons1992`. Plus `p6sdv8fm`, a Nix build hash, in `Maxelee/CARPoolGP`. Every
   one arrives inside a `file://` URL in `requirements.txt` — always the same pinned
   `more-itertools` line from one machine's conda cache — so a rule excluding `sdv`
   matched inside a path component would remove the whole family at once. This single
   fragment is now the largest source of false positives in the index.
2. **Unrelated software of the same name.** `sdvae`, the stable-diffusion VAE, in
   `MischaD/BeyondFID`; SDMetricsOpenCore, the commercial UML design-metrics product,
   in `ptidejteam/ptidej-Ptidej`.
3. **A suffix inside a longer class name.** `FCTGANSynthesizer` contains
   `CTGANSynthesizer`, in `ethan-keller/FCT-GAN`. This one will recur across the
   CTAB-GAN family and is the hardest to exclude, because the models really are in
   CTGAN's design lineage even when no SDV code is present.
4. **A different `ParSynthesizer`.** An OCaml program-synthesis module, in
   `amiltner/DSInvariant` and `amiltner/HanoiArtifactEvaluation`. Excluding non-Python
   repositories from the `par` pattern would settle it.
5. **A typo.** `asdvantage`, a misspelling of "advantage", in
   `nkh/P5-PerlBuildSystem`.
6. **Base64 payloads.** Subresource-integrity hashes in exported HTML notebooks, in
   `joehigh/COMSW4771`; CSRF tokens and certificate blobs in captured pages, in
   `sealuzh/cd-linter-artifacts`.

Nineteen of 484 curated entries are now pure substring accidents, and the rate is
rising as predicted: eight of the nineteen came from the last three batches.

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
- `afsahurrehman11/PulseForge-AI` (batch I) — imports `TabularDiffusionSynthesizer`
  and `sdv.evaluation.evaluate_privacy`, neither of which exists, but inside `try`
  blocks with a logged fallback to `GaussianCopulaSynthesizer`, and the real
  synthesizers beside them do run. Filed `api_user`, `importance` 3.

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

## 10. Shard numbers are not reserved per lane

**Provisional:** the repo lane has claimed 20-39 and left 08-19 to the papers lane.
Shards 03-07 stay where they are, so the repo lane reads 03-07 then 20 onwards.

AGENTS.md reserves a block of *patch* numbers per agent because patches apply in
filename order. Shards have no such rule, and with the repo and papers lanes running
concurrently both were taking the next free number: batch F was pushed as
`08-github-tail-f` against an existing `08-openalex-a`, renumbered to 09 against
`09-openalex-b`, and finally moved clear to 20.

Nothing breaks — `build.py` globs the directory and dedupes on `url`, so two shards
sharing a number merge fine — but the number stops identifying a wave, which is the
one thing it is for.

A one-line addition to the parallel-agents table in AGENTS.md would settle it. The
block boundaries above are a guess at the right split; papers is the larger tail by
record count, repos the larger by batches so far.

**The reservation did not hold, which is the point.** `curate/20-openalex-d` was
branched from a commit that predates the note above, so the papers lane took 20 as
its next free number and `data/shards/20-openalex-d.json` now sits beside
`data/shards/20-github-tail-f.json`. Nothing breaks — `build.py` globs and dedupes on
`url` — but a convention recorded only in this file cannot bind an agent that
branched before reading it. It has to be in AGENTS.md, which every agent is told to
read first. The papers lane describes its batch D as final, so the contention should
stop on its own; the rule is still worth writing down before the next lane starts.


## 11. Whether the zero-star tail deserves this depth

**Provisional:** carrying on as before — read every repository, one clause per entry
from a file in its tree.

Twelve by-stars batches have taken the repo lane from 26 stars down to 1. What is
left is 1,485 repositories, of which roughly 1,370 have no stars at all, and the
shape of the last four batches is a fair preview: mostly coursework, portfolio
projects and small applications that fit a `GaussianCopulaSynthesizer` once and are
correctly filed `api_user` at importance 3 or 4.

The case for continuing is that the batches keep producing findings that could not
have been guessed from metadata — a national statistics institute in batch J, an MCP
server in batch G, a competitor's written decision *not* to depend on SDV in batch J,
a Kafka producer serving a fitted synthesizer in batch L. None of those correlate
with stars.

The case against is arithmetic. At forty-four a batch this is another thirty-four
batches and thirty-four more pull requests, and the last three produced roughly one
genuinely novel channel each against forty-odd routine entries.

Three options, in the order I would rank them:

1. **Keep going but widen the batch.** The routine entries are cheap to read and
   cheap to write once the pattern is recognised; the cost is dominated by the
   unusual ones. A hundred-repository batch would take about twice as long and cut
   the pull request count by half.
2. **Split the tail by signal, not by stars.** The `req`-only repositories (open
   question 5) and the zero-hit repositories are where the routine entries
   concentrate. Reading the repositories with an import hit first would front-load
   the findings and leave a clearly-labelled remainder.
3. **Stop at some star or activity floor** and record what was left, which is honest
   but throws away the finding rate that does not correlate with stars.

Nothing here blocks: batches continue in the meantime.
