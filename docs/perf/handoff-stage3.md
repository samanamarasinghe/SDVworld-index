# Stage 3 handoff — parity, accessibility, cutover

Branch `v2-perf`, merged to `main`. Design: `sdvworld-perf-design-v2.md` §10, §11.
Brief: `stage-3.md`. Previous: `handoff-stage2b.md`.

**The cutover is live.** `/` serves the rebuilt page; `/v1/` archives the previous one
for one release. Rollback is one `git revert` of a commit touching two files.

## Deep UI parity — 300 states, 0 failures

Fresh seed (`30003`), so these are 300 states the page had never been tested against.
The comparison was widened from card titles to **every visible detail**: per card its
class, title and href, the whole meta line, every badge with its class, confidence,
authors, evidence, every chip, and every action with label and href; per facet item
its label, count, disabled state **and checked state**; plus both sliders and their
labels, the selects, the search box and the results container's classes.

812 facet-value selections, 186 states combining two or more facets, all seven
importance stops, all six groupings, all four sorts. 62 expected search differences,
**0 failures**.

Verified by seeding two bugs the previous title-only comparison would have passed:
dropping the star count from the meta line, and rendering a *selected* checkbox as
unticked. Both caught, naming the exact card and facet item.

## Stress suites — the owner's testing rules

| suite | scale | result |
| --- | --- | --- |
| toggles — select **and deselect** sequences, compared after every step | 40 sequences, 366 steps | 0 failing |
| sweeps — every importance and popularity stop, every year, every grouping × sort | 70 systematic states | 0 failing |
| search — queries drawn from the corpus itself | 94 queries | 0 inconsistent |
| show all — the uncapped render path, timed | 4 result sizes | see below |

### Show all

| state | results | to render all | v2 nodes | v1 nodes |
| --- | --: | --: | --: | --: |


This is the one path where the rebuilt page has no advantage: with the cap lifted it
draws everything, just as the old page always did. The difference is that the old page
paid this on *every* interaction and this one pays it only when asked.

### Search across realistic queries

| query kind | n | more in v2 | fewer |
| --- | --: | --: | --: |
| author-first | 8 | 7 | 1 |
| author-full | 8 | 8 | 0 |
| author-last | 10 | 9 | 1 |
| domain | 12 | 0 | 5 |
| nonsense | 10 | 3 | 2 |
| rare-phrase | 6 | 3 | 0 |
| title-phrase | 14 | 14 | 0 |
| unicode | 6 | 3 | 0 |
| venue | 12 | 1 | 0 |
| year | 8 | 0 | 5 |

Every author query improved, which was the point: the search box had never matched
authors in either version. Title phrases all return more, because words are matched
separately and may appear apart. Where v2 returns fewer it is almost always v1
substring noise — `Ali` matched inside *quality*, `Li` inside *like*, `gan` inside
*organ*.

## Accessibility — 44/44

Three checks found real defects **the old page shares**: the search box and both
sliders had *no accessible name at all*, and the two selects were named by reading out
their entire option list. Fixed with `aria-label`.

The first version of that check asserted names must be *identical* to v1, which failed
those very fixes. The requirement is that the new page be no **worse**, so it now
fails only if a name is lost.

## Mobile

Sizing the browser *window* never narrowed the viewport, which is why Stage 1 shipped
without mobile screenshots. Sizing the **iframe** does — an iframe has its own
viewport and media queries respond to it — so `tests/parity/mobile.html` renders both
pages at a genuine 390 px, confirmed by `innerWidth` reporting 390 in both.
Screenshots in `docs/perf/screenshots/mobile-390-*.jpg`; layouts match.

## Bugs found by this stage

**One in the product**, from the nonsense queries: a punctuation-only search such as
`???` returned **all 4,703 entries**. It tokenizes to nothing, so the engine treated it
as an absent query and stopped filtering — telling the reader their query matched
everything, which is false. The old page returned none. Fixed: a non-empty query that
yields no tokens now matches nothing, with a case covering `???`, `---`, `...` and
`@@@` alongside the empty and whitespace queries that must still mean "no filter".

**Three in the harnesses**, all of which produced false failures and none of which was
a product defect:

- The round-trip check assumed applying an operation twice returns the page to its
  start. `toggleAff` has an empty-group floor that re-lights the whole group, and a
  facet value disappears from the Authors and Affiliation lists once deselected, so
  the control needed to undo a step may no longer exist. Replaced with **Clear
  filters**, which is sound and is the path a reader uses.
- A sweep reported a grouped-sort difference that reproduced nowhere. Both pages share
  one main thread, and the old page rendering 4,703 cards blocks it for seconds, so
  the settle's fixed allowance could expire before the new page's coalesced pass ran —
  comparing one page's new state against the other's previous one. The settler can now
  **require** a redraw.
- The search suite reported 64 of 94 queries internally inconsistent. *Clear filters*
  deliberately does not reset grouping, so the previous suite left both pages grouped
  by industry and every record was counted once per group. Suites now reset the view.

## Still open

- **Retire `/v1/`** after one release — and read `tests/parity/README.md` first: the
  parity harness compares against it and stops being meaningful once it is gone.
- **Should `GAN` match inside `ctgan`?** 3,589 hits then, 1,328 now. Needs a ruling;
  recorded in the manual.
- The BibTeX download is not tested end to end; Node is not installed so the browser
  harnesses run by hand rather than in CI.
