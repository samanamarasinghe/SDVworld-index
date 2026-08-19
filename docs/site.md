# The page and its filter semantics

The site is `index.html` plus `assets/js/sdv-index.js`, served by GitHub Pages from
`main`. No build step, no framework, no bundler: the JS is one IIFE of ES5, and the
page fetches `data/sdv-index.json` and the two pool files at runtime.

`assets/js/sdv-index.js` carries a comment on every non-obvious decision. This file is
the model behind those decisions; the code is the detail.

## What is on screen

Three layers of data reach the page, and they are not equivalent:

- **Curated entries** — `data/sdv-index.json`, built from `data/shards/`. Every one has
  a summary written from the source and a full set of facets.
- **The citation tail** — `data/tail/openalex-citations.json`, works that cite an SDV
  paper, mechanically resolved and never read.
- **The repository tail** — `data/tail/github-repos.json`, repositories a code search
  matched and nobody visited.

Both pools are always in view; there is no toggle. They are fetched after the first
paint because the curated index is small and the pools are several MB between them.
A pooled row carries no `importance`, so at any importance floor above 0 — the default
is 1 — no pooled row is shown at all. `notCurated` keeps a row out of the pool view once
it has been curated, matching on every URL alias the row carries rather than only the
one displayed, because a curator may have filed the work under its landing page, its
DOI or its OpenAlex id.

## The two sliders

**SDV importance** is the primary control, 0 to 6, defaulting to 1. It filters on the
curator's judgment of how central SDV is to the entry. Seven stop marks sit under the
track, built by `buildStopMarks` from the input's own min/max/step so the two cannot
disagree; the row is inset 8px each side because the thumb travels between those
centres, not to the element's edges. The marks are deliberately not on the track —
styling a range track means `appearance: none` and taking over the whole control,
which loses the platform thumb.

**Popularity** is a percentile cut, not a raw value: GitHub stars for code and citations
for papers, log-compressed onto one 0-1 scale so the two are comparable, then cut by
percentile of whatever is currently in view. That keeps "rightmost = only the most
popular" true however large the pools grow. It defaults to All entries.

The defaults live in three places that must agree: the `value=` on both range inputs,
the initial label text in the markup, and `state` in the JS — plus the Clear filters
reset. Changing one and not the others is a bug the page will not report.

## Facets: include, except where they exclude

The nine checkbox facets — Kind, Integration, Year, Use case, SDV component, SDV
concept, Sector, Affiliations, Authors — are **include** filters. Ticking a value asks
for the entries carrying it; one match is enough; nothing ticked filters nothing.

The two **button groups** are the opposite. `aff_type` (Academic affiliation /
Non-academic affiliation / Affiliation not found) sits over Sector, and `aff_region`
(Americas / Europe / Asia / Africa-Oceania) sits over the organization list. They
**permit rather than select**: `groupPermits` requires every value a record carries to
be lit, so unlighting Americas drops an entry that has even one organization in the
Americas. On an overlapping split that makes one lit button read as "only here" rather
than "somewhere here". All lit is inert.

Clicking toggles. When the last lit button in a group goes dark the group would show
nothing, so `onEmpty` decides: a pair hands the selection to its partner, a group of
three or more reopens entirely.

Two traps live here.

**The `__none__` sentinel.** Absence is a curatorial statement — the source named SDV
and never named a synthesizer class, so no concept was guessed — and `valuesOf` appends
the sentinel so that absence is visible as an ordinary facet value rather than
vanishing the moment anyone ticks a box. It renders as "Not specified", or "Undated"
on the Year grid. `NO_NONE` exempts four facets. Authors and Affiliations are exempt
because a missing author list is an absent fact rather than a judgement. `aff_type` and
`aff_region` are exempt for a different reason, and leaving them out was a real
regression: a button group enumerates its own values, so a record with no resolved
region must come back with an empty list. Given the sentinel instead, `groupPermits`
finds a value no button lights and vetoes the record — which silently dropped every
entry with no affiliation, both pools included, and cut the default view to 419.
**Any new derived split must be added to `NO_NONE`.**

**A region of none must never veto anyone.** Every region is enumerated rather than one
serving as the remainder, and a country name none of the lists places returns `''`,
which appears in no button and so is vetoed by none. The cost of that trade is that a
country nobody listed shows in no count until it is added to the table — which is the
fix when one turns up unplaced.

## Organizations, not authors

An `affiliations` element may hold several `;`-separated organizations. `organizationsOf`
splits and dedupes them, and `affiliationRows` aligns `affiliation_types` and
`affiliation_countries` with that **organization** sequence rather than with `authors`.
`tests/validate.py` enforces the same alignment, so a shard whose three lists disagree
fails before it reaches the page.

The organization checkbox list stays an include filter even though the two groups above
it exclude: naming an organization is asking for the entries it appears on.

## Counting

Each facet's counts are computed with that facet excluded from the filter — the
`exclude` argument threaded through `filteredData`, `passesFacets` and `groupPermits`.
That is what lets a dark button still show how many entries it is holding back.

## Testing a filter change

`tests/validate.py` checks **data**, not what the page displays, and will pass happily
while the page shows nothing. The regression above proved it: a filter bug reaches the
header count and nothing in the repo notices.

A stub-DOM harness does notice, and is about 40 lines: fake `document` and `fetch` in
node, `vm.runInThisContext` on the real `assets/js/sdv-index.js`, then read
`pubs-count.textContent` and drive the sliders through `_ev.input` and the buttons
through their `onclick`. The stub needs `getElementById`, `createElement`,
`createTextNode`, `createDocumentFragment`, `childNodes` — `renderItem` reads
`chips.childNodes.length` — `classList`, and the range inputs' min/max/step/value copied
out of `index.html`. Run it after any filter change and compare the header count at
importance 0 / popularity 0, at 4 / 0, and at the defaults.

## Pushing site files

Push `assets/js/sdv-index.js` with `create_or_update_file` and the blob sha from
`git rev-parse HEAD:<path>`, not with `push_files`: the source contains literal
`\u2014`-style escapes inside string literals and `push_files` decodes them. Verify with
a byte diff against `origin/main` afterwards. GitHub reports `size` in bytes while
python `len()` counts characters, so a UTF-8 file reads larger by the count of its
non-ASCII bytes; that is not corruption.
