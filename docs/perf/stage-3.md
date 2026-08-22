# Stage 3 brief — parity, accessibility, cutover

Design: `sdvworld-perf-design-v2.md` §10 (Stage 3), §11 touchpoint 4.
Preconditions: 2b green (`handoff-stage2b.md`). Branch: `v2-perf`.

## Scope

1. **v1/v2 differential at the pinned revision** — done and green each stage; re-run.
2. **Deep UI parity at scale.** Widen the comparison from card titles to *every*
   visible detail, and from 100 states to 300.
3. **Mobile-sized runs with screenshots.** Deferred from Stage 1 because resizing the
   browser window through the harness did not narrow the viewport. An iframe has its
   own viewport, and media queries respond to it, so a 390-wide iframe is a genuine
   390 px render rather than a scaled picture of a wide one.
4. **Keyboard and ARIA verification.**
5. **Root cutover** as a single commit touching only the entry point and assets, with
   v1 kept at `/v1/` for one release. Rollback is one `git revert`.

## What "everything" has to mean for the deep comparison

Titles alone would miss a dropped venue, a wrong star count, a missing DOI link, a
chip rendered under the wrong facet, or a checkbox that renders unchecked when it is
selected. So per rendered card: class, title text and href, the whole meta line,
every badge with its class, confidence, authors, integration and evidence, every chip
with its class, and every action with its label and href. Per facet: every item's
label, count, disabled state **and checked state**, in order. Plus the facet header
counts, the year grid, the affiliation buttons, both slider labels, the group and sort
selects, and the results container's classes.

## Differences that are by design, and are normalized

Each is normalized in exactly one place, with the reason at that place:

- **v2 renders at most 100 unique records.** v2's cards are compared against the
  corresponding prefix of v1's.
- **Group headings** read `(11 of 2171)` in v2 and `(2171)` in v1; only the total is
  compared.
- **BibTeX hrefs.** v1 mints a Blob URL per card at render time — the leak this whole
  project removes — so its href is `blob:…` and v2's is `#`. Labels are compared, that
  href is not.
- **Summary bodies.** v1 builds the summary DOM eagerly; v2 fetches it on demand. The
  *toggle* is compared; the body is not, and is covered instead by the semantic suite.
- **Needs lines.** Same reason; covered by a dedicated check rather than in every state.
- **Search states**, from 2b: v1 matches substrings, v2 matches tokens. Reported as
  expected differences and covered by `docs/perf/search-recall.md`.

Anything else that differs is a failure.

## Definition of green

- 300-state deep parity: every non-search state identical in every compared detail.
- Mobile screenshots at 390 px for the representative states.
- Keyboard/ARIA checks pass.
- All eleven gates still pass at stage 2b.

## Cutover

A separate commit, touching only `index.html` and the asset paths, moving v1 to
`/v1/`. **Owner approval required first** — §11 touchpoint 4, one yes/no.
