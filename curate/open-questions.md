# Open questions for Saman

Queued during unattended curation runs. Nothing here blocks work — each item names
the provisional choice already made, so the index stays consistent either way. A
ruling either confirms it or triggers a correction patch.

Newest section last. Delete a resolved item, or record the ruling in place.

## 1. A distinct `integration` value for inherited relationships

**Provisional:** filed as `vendored_source` at `importance` 1–3.

Three entries so far relate to SDV only through a third party rather than directly:

- `jansel/pytorch-jit-paritybench` — crawled CTGAN modules out of tab-ddpm's
  vendored copy
- `jim-schwoebel/voiceome` — vendors the whole Allie framework, itself an index entry
- `Hannah37/ConDOR-ICLR25` — inherited tab-ddpm's entire baselines directory,
  vendored CTGAN tree and `rdt` pin included

`vendored_source` is technically true of all three but says the wrong thing: it
implies a deliberate decision to embed SDV, when in each case SDV arrived as a
passenger. A value such as `inherited` or `transitive` would separate them.

Against adding it: three of 121 curated entries, and `importance` 1 already
communicates most of what matters.

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

## 6. Repositories that failed to clone

**Provisional:** left in the pool, not indexed.

`lxyeternal/MalSkillBench` (later succeeded on retry), `akohsa/BEAS`,
`SWE-bench-Live/submission`, `ptidejteam/ptidej-Ptidej`,
`apachecn/towardsdatascience-blog-zh-2022`, `deem-data/sempipes`.

Mostly large or slow clones rather than missing repositories. They need either a
longer timeout or a shallower fetch; worth a retry pass once the main sweep is done
rather than blocking a batch on each.
