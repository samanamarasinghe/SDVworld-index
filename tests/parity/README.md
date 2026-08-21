# UI parity

Drives the two **shipped** pages through the same clicks and compares what they put
on screen.

    python3 scripts/serve.py &
    open 'http://127.0.0.1:8765/tests/parity/harness.html?n=100&seed=20260821'

Poll `window.__PARITY__` (`{done, error, i, n, failed}`); results are written to
`tests/parity/last-run.json` every ten states.

| parameter | effect |
| --- | --- |
| `?n=100` | how many states (default 100) |
| `?seed=20260821` | PRNG seed — the run is reproducible; "random" describes the coverage, not the outcome |

## Why this exists when the golden differential already passes

The differential in `tests/oracle/` drives the filter **engine**. It never dispatches
an event, never reads a checkbox, never looks at the facet panel. It would pass at
293/293 on a v2 whose checkboxes were wired to the wrong facet, whose facet lists
rendered in the wrong order, whose sliders were inverted, or whose cards were drawn
out of order — because none of that is the engine.

This harness loads `/index.html` and `/v2/index.html` in two iframes, **unmodified and
uninstrumented**, and drives them through real DOM events on the real controls. It
compares what a reader would see:

- the result count in the header
- the titles of the rendered cards, in order
- every facet list: label text, count, order, and the 200-value truncation
- the facet header counts, the year grid, the affiliation buttons and their lit state
- group headings and their totals

## The two normalized differences

Both are by design, and normalizing them is the only place this harness makes a
judgement call rather than comparing bytes:

1. **v2 renders at most 100 unique records; v1 renders all of them.** v2's cards are
   compared against the corresponding *prefix* of v1's list. That is a stronger check
   than comparing sets — it proves the sort agrees too, not just the membership.
2. **Group headings differ in format.** v1 writes `(2171)`; v2 writes `(11 of 2171)`
   because it also reports how many are on the page. Only the total is compared.
   Separately, a group entirely off v2's page is omitted rather than drawn empty, so
   v2's headings must be a subsequence of v1's in the same order — and if v2 omits a
   group while its page is not even full, that is reported as a failure.

## Verified by mutation

A hundred passes prove nothing unless the comparison can fail. Two bugs were seeded
into v2 and both were caught with the exact difference named:

| seeded bug | what the harness said |
| --- | --- |
| reversed the year tie-break in `sortWithin` — changes card **order** only, no count anywhere | `card 1: v1 "How DataCebo Supports Enterprises…", v2 "DataCebo Forum"` and, under grouping, `group "Paper" card 1: …` |
| sorted facet lists ascending by count — changes list **order** only, every count still correct | `facet-kind item 1: v1 "Code repo (81)", v2 "Dataset / benchmark (0)"` |

Neither of these is visible to the golden differential. That is the point.

## The clock

Everything here waits on a **dedicated worker's timer**, and the reason is worth
recording because three more obvious choices all fail in a driven run, which by
definition happens in a tab that is not in front:

- `requestAnimationFrame` stops entirely in a hidden tab. A wait that picks it is
  stranded until the reader comes back — and picking it *conditionally* on
  `document.visibilityState` is worse, because a tab that hides between the choice and
  the frame strands the wait forever. This actually happened here.
- `setTimeout` is clamped to a second in a hidden tab, and to a **minute** after five
  minutes hidden. A 120 ms settle window becomes a two-minute stall.
- Racing rAF against a `MessageChannel` task avoids both, but the channel wins
  instantly every time, so the wait becomes a spin that saturates the renderer and
  piles up rAF callbacks that will never fire. This also actually happened here.

A worker's `setInterval` is throttled by none of it — measured at a steady 25 ms in a
hidden tab — and costs one message per tick instead of a busy loop.

The pages under test still use their own timers. v2 debounces the title input by
150 ms, which becomes the clamp when hidden, so search states get an extra allowance
before the comparison is taken.

## Result, 2026-08-21

Seed `20260821`, 100 states: **100 of 100 identical, 0 differing.** Coverage across
those states — 299 individual facet-value selections in all:

| | |
| --- | --- |
| facets exercised | kind 29 · integration 28 · use case 27 · industry 26 · component 26 · concept 21 · affiliations 18 · authors 14 |
| importance floor | all seven stops, 8–29 states each |
| popularity floor | 0 (53), 25 (14), 50 (13), 75 (20) |
| grouping | none 29 · use case 22 · industry 17 · kind 13 · year 13 · component 6 |
| sort | importance 33 · year 32 · popularity 20 · title 15 |
| searches | 45 states |
| year buttons | 31 states |
| affiliation button darkened | 18 states |
| two or more facets at once (AND across) | 64 states |
| two or more values in one facet (OR within) | 71 states |

`held-node lookups that needed a live-DOM fallback: 0`, so every control was found
where expected.

## Two false alarms, and what they were

Both are recorded because each looked exactly like a v2 bug and neither was one.

**Eight states "failed" with a checkbox missing from v2.** The first version of this
harness looked each control up per state, immediately after clicking "Clear filters".
v1 rebuilds its facet panel synchronously inside the handler; v2 coalesces the rebuild
to a tick. So at that instant v1 already listed all 2,641 organizations and v2 still
showed the previous state's filtered list. The harness was racing v2's coalescing —
which is a feature, and the reason v2 is fast. Fixed by resolving every control once
from the pristine page and holding the nodes; a detached checkbox keeps its listener,
and that listener closed over its own facet and value.

**The same eight states then failed again, identically, after the fix.** That one was
not the harness logic at all: `scripts/serve.py` sent `Last-Modified` and answered
`If-Modified-Since` with a `304`, so Chrome kept serving the *old* module even though
every response also said `Cache-Control: no-store`. Two full twenty-five-minute runs
executed stale code and reported it as product failures. The server now drops
conditional request headers outright, making a 304 impossible.

The lesson worth keeping: a test result is only as trustworthy as the guarantee that
the test you edited is the test that ran.

## Cost

About 14 s per state, dominated entirely by v1: each control change re-renders every
matching card, and a state changes several controls. v2's half of each state is in the
tens of milliseconds. A hundred states takes roughly 25 minutes.
