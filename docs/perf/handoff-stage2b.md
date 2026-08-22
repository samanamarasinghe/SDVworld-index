# Stage 2b handoff — postings and the search change

Branch `v2-perf`. Design: `sdvworld-perf-design-v2.md` §4, §9.
Brief: `stage-2b.md`. Previous: `handoff-stage2a.md`.

This is the one planned semantic change in the redesign. **Every gate in the design
now passes**, including the eager payload budget, which is the last one that was
still outstanding.

## The search change, and the ruling you inverted

§4 made title-only the default. You inverted that on 2026-08-21 after seeing what it
would cost on this corpus, and the decision looks right in hindsight: with summaries
searched by default, v2 keeps **75% of v1's results overall and 99–100% on almost
every real query**, while the token semantics make several queries better.

Had we shipped §4 as written, `sdv` would have gone from 3,146 hits to 61.

| query | v1 | v2 | kept | gained | note |
| --- | --: | --: | --: | --: | --- |
| `health` | 389 | 387 | 99% | +0 |  |
| `` | 1,370 | 1,370 | 100% | +0 |  |
| `h` | 4,702 | 2,214 | 47% | +0 | **narrowed** |
| `he` | 4,691 | 714 | 15% | +0 | **narrowed** |
| `health` | 384 | 382 | 99% | +0 |  |
| `healthcare` | 153 | 153 | 100% | +0 |  |
| `Health` | 384 | 382 | 99% | +0 |  |
| ` health ` | 384 | 382 | 99% | +0 |  |
| `synth` | 3,966 | 3,843 | 97% | +0 |  |
| `synthetic data` | 1,818 | 3,208 | 100% | +1,390 | widened |
| `privacy` | 830 | 829 | 100% | +0 |  |
| `differential privacy` | 99 | 130 | 100% | +31 | widened |
| `ctgan` | 3,293 | 3,289 | 100% | +0 |  |
| `CTGAN` | 3,293 | 3,289 | 100% | +0 |  |
| `sdv` | 3,146 | 3,146 | 100% | +0 |  |
| `tabular` | 2,184 | 2,183 | 100% | +0 |  |
| `time-series` | 122 | 159 | 100% | +37 | widened |
| `time series` | 57 | 159 | 100% | +102 | widened |
| `GAN` | 3,589 | 1,311 | 37% | +0 | **narrowed** |
| `C++` | 3 | 25 | 67% | +23 | widened |
| `covid-19` | 22 | 22 | 100% | +0 |  |
| `naïve` | 2 | 26 | 100% | +24 | widened |
| `Müller` | 0 | 0 | -- | +0 | no results either way |
| `Zhang` | 0 | 0 | -- | +0 | no results either way |
| `multi word no match` | 0 | 0 | -- | +0 | no results either way |
| `zzzznomatch` | 0 | 0 | -- | +0 | no results either way |

Full report, including examples of what dropped and what was added:
`docs/perf/search-recall.md`.

**Three queries narrow, and all three are defensible.** `h` and `he` are one and two
letters — v1 matched them inside any word, so `he` returned 4,691 of 4,703 entries,
which is not a search result. v2 matches word *prefixes*, so it returns 714.

**`GAN` is the one judgement call worth your eye.** v1 returned 3,589 by matching the
substring anywhere, including inside `ctgan`; v2 returns 1,311 by matching the word.
Someone searching GAN arguably does want the CTGAN papers. Matching the final term as
a *substring* of the vocabulary rather than a prefix would restore that — about a
five-line change, and cheap at 15,143 tokens — at the cost of bringing back `he`
matching inside `the`. I left it as the design specifies; say the word and I will
change it.

**Several queries improve.** `time series` finds `time-series` too (57 → 159).
`naive` finds `naïve` (2 → 26) because accents are folded. `differential privacy`
finds the words apart as well as together (99 → 130).

## Payload — the last budget met

| | gzip |
| --- | --: |
| v1 today | 2.59 MB |
| 2a | 1.91 MB |
| **2b** | **1.38 MB**  *(budget 1.50)* |

`core.json` 1.00 MB + postings 0.34 MB. The postings replace an
0.81 MB precomputed search string with 0.34 MB of delta-encoded index — and buy
better matching in the process.

## Speed

| interaction | v1 | v2 (2b) |
| --- | --: | --: |
| `search-type-health` \* | 231 ms | 236 ms |
| `importance-1-to-4` | 710 ms | 60 ms |
| `importance-1-to-0` | 2,198 ms | 105 ms |
| `popularity-0-to-50` | 2,130 ms | 76 ms |
| `facet-tick-first-kind` | 2,277 ms | 74 ms |
| `group-by-kind` | 2,566 ms | 122 ms |
| `sort-by-title` | 2,803 ms | 122 ms |
| `clear-all` | 3,176 ms | 114 ms |
| **cold load to settled** | **8,903 ms** | **415 ms** |

\* Measured through a debounce the environment clamps; indicative only. Run-to-run
variance is large — read these as tens of milliseconds against seconds.

## Green

`python3 tests/gates.py --target v2 --stage 2b` → **PASS, all eleven gates.**

- **Golden differential: 275 identical, 18 documented exceptions, 0 failures.** Every
  single difference is a search state. Nothing else moved.
- **Semantic: 36/36.**
- **UI parity: 100/100, 0 failures** — 83 states byte-identical, 17 expected search
  differences. 28 of the 45 query-bearing states matched v1 *exactly* even after the
  change.
- **15 build checks**, including postings verified against a direct scan of the text.

## The riskiest thing here, and how it is pinned

The build tokenizes in Python and the runtime tokenizes in JavaScript. If they ever
disagree, a query is looked up under a key the text was never filed under, and search
quietly returns too little — no error, no crash, just fewer results. That is the worst
failure mode available in this stage, because nothing would surface it.

Both are pinned to a **shared expectation table**
(`tests/semantic/tokenizer-cases.json`), checked from Python in `build_tests.py` and
from JavaScript in the semantic suite. They are pinned to one written answer, not to
each other — two implementations can agree on the wrong thing.

The table is deliberately awkward: `C++`, `naïve`, `Müller`, `straße`, `ﬁle`,
`Ångström`, `深層学習`, `O'Brien`, `x²`, `a_b`, `café-au-lait`.

## One correction to §4

"The final term matches by prefix" is applied only when the query does **not** end in
a delimiter. Unconditionally, `C++` tokenizes to the single token `c` and prefix
matching returns 4,627 of 4,962 records. A trailing delimiter means the reader
finished the word. Found by running §4's own frozen examples against it.

## Two wrong tests, for the record

Both failures in the first run of the new suite were bad expectations of mine, not
product bugs, and each was worth having: `bet alpha ` has a trailing delimiter so both
terms match exactly, and `bet` is not a word — the engine was right. And a `waitFor`
that counted *ticks* rather than time expired in milliseconds, long before a debounce
clamped to ~700 ms could fire.

## A reproducibility bug CI found, and the fix that did not work

Right after 2a went live, CI rebuilt `core.json` on `main` and committed a diff:
**395 records whose popularity differed in the last bit.** `math.log1p` is not
required to be correctly rounded and libm differs between macOS and CI's Linux.

Three consequences, the third serious: every local build gets rewritten by CI and
vice versa; `data_hash` — the *cache identity* — moves although nothing a reader can
see changed; and the bytes actually **served** become CI's build, which no
differential has ever run against. The tested build and the shipped build stop being
the same thing.

The obvious fix is to round, and it looks measurably safe: of 647 apparently distinct
scores, 10 pairs sit 5.55e-17 apart, and every precision from 6 to 15 decimal places
collapses exactly those 10 and nothing else. Those pairs are records that *should*
score identically and do not, because `0.1 * commits` accumulates a different error
than an equivalent whole number.

**I rounded to 9 dp and it failed 76 golden states.** v1 does the same arithmetic in
JavaScript, inherits the same artifact, and therefore treats those pairs as ordered —
and the Stage 0 corpus recorded that order. Quantizing turned them into ties that fell
through to the next tie-break and reordered the page. Fidelity to v1 wins: v2 is not
allowed to reorder cards, even to fix a wart.

So it is solved at the other end. **CI verifies the projection instead of rebuilding
it** (`scripts/verify_site.py`): same records, same ids, same order, same every field,
with last-bit float noise on `pop` tolerated and nothing else. The committed artifacts
stay authoritative — produced and tested on one machine — and a structural staleness
fails the build and says which record and field moved.

## Next: Stage 3

Parity and cutover — the v1/v2 differential at the pinned revision (done and green),
real desktop and **mobile-sized** runs with screenshots, keyboard and ARIA
verification, then the root cutover as a **single revertible commit** touching only
the entry point and assets, with v1 kept at `/v1/` for one release.
