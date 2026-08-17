# Open questions for Saman

Queued during unattended curation runs. Nothing here blocks work — each item names the
provisional choice already made, so the index stays consistent either way. A ruling either
confirms it or triggers a correction patch.

Newest section last. Delete a resolved item, or record the ruling in place.

Fifteen earlier items were ruled on and removed on 2026-08-15. Their outcomes are in
README.md (the `inherited`, `declared_only`, `port` and `aerospace` values, the rule that
`unclear` may not carry `confidence: high`, and the preference for a domain over
`academia`), in AGENTS.md (correction shards sort after what they correct; the repository
tail is closed), and in `data/shards/41-open-question-rulings.json`.

## 1. Auditing `academia` for the domain underneath it

**Provisional:** entries filed `academia` keep it; three exoplanet and rocket-launch
entries have moved to the new `aerospace` value.

`academia` is on 287 entries, 170 of them with no second industry. The ruling is that a
domain beats `academia` wherever one applies — a paper is academic by construction, so the
tag on its own loses the field the work is actually about.

Sizing the audit: 231 of the 287 are repositories, 26 are papers. A keyword pass over
titles and summaries finds a plausible domain for only 83 of them — health 25, cybersecurity
21, finance 16, environment 10, transport 7, energy 7, space 5, education 4 — and nothing
for the remaining 204. So two-thirds need the entry read rather than pattern-matched.

The valuable half of this is not reassignment but **discovering industry values that do not
exist yet**, which is precisely what a keyword pass cannot do: it can only find categories
already in the vocabulary. `space_astronomy` is already visible as a candidate, since
neither exoplanet entry is about aircraft or launch vehicles and `aerospace` is carrying
them only by courtesy.

Planned as its own pass: a sample of roughly 25 spanning the keyword-flagged domains and a
slice of the 204, proposing both moves and new values, for a ruling before the rest.

## 2. Paywalled full text is the binding constraint on the papers lane

**Not a judgment call — a tooling note, recorded because it decides how good the next
papers batch can be.**

Of the 35 works in shard 40, 16 full texts were readable and 19 were not, for two reasons:

- **403 to automated fetches** — MDPI, IEEE Xplore, ACM DL, OUP, ScienceDirect, Wiley.
  Several are open access and still refuse both `urllib` and `curl` with a browser
  user-agent.
- **PDF-only, no extractor.** No `pdftotext`, `fitz`, `pdfminer` or `PyPDF2` in the
  environment. A minimal inflate-and-grep extractor handles simple PDFs but not the
  CID-encoded subset fonts that OSF and most publishers emit.

Two things have since narrowed it. OpenAlex's `best_oa_location` finds a free copy for 12 of
the 35 currently flagged, which is a cheap win requiring no new tooling. The remaining 20
are genuinely paywalled and want institutional access rather than a better fetcher.

Adding a PDF text extractor would still move roughly a third of every future papers batch
from `confidence: medium` to `high`, and remains the single highest-leverage change to the
lane. Until then, `confidence: high` in the papers lane tracks whether a publisher happens
to serve HTML, not how hard the curator looked.
