# Author affiliations: where they come from

`docs/schema.md` defines the four attribution fields on a record — `authors`,
`affiliations`, `affiliation_types`, `affiliation_countries` — and how the two
facet lists align. This file covers the other half of the question: how a name
came to have an organization next to it, and what it means when it does not.

Read `docs/agent-guide.md` first for the working procedure.

## The curated series

Attribution evidence does not live in the shards. It lives in a numbered series of
override files that `curate/apply_author_affiliations.py` merges and writes into the
shards:

    data/github-repo-author-overrides.json      machine-owned: GitHub contributor harvest
    data/curated-author-affiliations.json       hand-owned, batch 1
    data/curated-author-affiliations-002.json   batch 2
    ...
    data/curated-author-affiliations-012.json   batch 12

The script globs `data/curated-author-affiliations*.json`, so a new batch is a new
numbered file rather than an edit to a growing one. Later files win on a repeated
entry id. Each file is self-contained and reviewable on its own, and a batch that
turns out to be wrong can be deleted whole.

Every file has the same three keys:

    note            one paragraph: what this batch is and where its evidence came from
    organizations   organization name -> {organization_type, country}
    entries         entry id -> ordered rows of {name, affiliation, affiliation_source_status}

`affiliation` holds one organization or several separated by semicolons, and is
`null` where nothing could be established. The rows are positionally aligned with
the entry's `authors`, so a batch that touches an entry restates every author of it.

## Source status vocabulary

`affiliation_source_status` records what the claim rests on. It never reaches the
built index — it exists so a whole class of inference can be audited or reversed
later without re-deriving it.

| value | what it means |
|---|---|
| `curator_stated` | a person decided it, usually from knowledge the sources do not carry |
| `publication_stated` | printed on the work itself: byline, title-page footnote, or the affiliation strings a publisher deposits with Crossref |
| `publisher_stated` | follows from who published the artifact rather than from a byline. Used for first-party documentation, and for a thesis held in its degree-granting university's repository |
| `profile_stated` | the author's own GitHub profile — company field, bio, or personal site — names an institution |
| `repository_owner_org` | the repository lives under an organization account that names a real place |
| `commit_email_domain` | the author's own commit emails carry an institutional or corporate domain |
| `unresolved` | looked for, not found. This is a finding, not a gap |

The three GitHub-derived statuses are inference and are weaker than the first three.
They are recorded separately for exactly that reason.

## Rules that decide a value

**The affiliation is the organization through which the person did *that* work**, not
their current employer. The same person can legitimately carry different affiliations
on different entries, and those are not inconsistencies to reconcile.

**An affiliation is a place.** A role descriptor is not one: "Independent Researcher",
"Open Source Contributor" and "Community Contributor" are recorded as no affiliation
rather than invented into an organization. A named legal entity qualifies however
small. A funding programme is not a place either.

**A null is a real answer.** Personal and student projects with no institutional
signal anywhere are correctly blank, and filling them with something plausible would
be worse than leaving them empty.

## Traps worth knowing before extending this

- **Agent tooling writes commits.** Five repositories in this index carry
  `anthropic.com` commit emails from AI coding tools. A commit-email domain is
  evidence about a person only when the person owns the address.
- **Owning a repository is not employing a contributor.** Outside contributors to a
  company's open-source repository take the owner organization only if their own
  commit emails agree.
- **Alumni bios are not affiliations.** "Alumni from @X" and bios naming only a
  country or a bare "University" are skipped.
- **Free mail, GitHub noreply, local hostnames** (`*.local`, `*.compute.internal`)
  and `example.com` are filtered before a domain is read as evidence.
- **Publisher deposits are unnormalized.** Crossref returns
  `"Croesus,Croesus Lab,Laval,Canada"`; the organization name is what gets stored.
- **One spelling per organization.** The name in `organizations` is the name in the
  rows, everywhere in the series.

## Applying a batch

    git pull --rebase
    python3 curate/apply_author_affiliations.py            # dry run, prints what would change
    python3 curate/apply_author_affiliations.py --write
    python3 build.py --write
    python3 tests/validate.py

The script refuses to write if any non-generated field would change or if the two
lists would fall out of alignment, and it augments rather than replaces: a fresh
harvest never drops a name or blanks a known affiliation. Running it twice reports
zero changes; if the second run reports work, something is wrong.

CI rebuilds `data/sdv-index.json` on any push touching `data/shards/`, so a batch
commit carries the override file only.

## Where attribution stands

Of 1087 entries, 678 carry at least one affiliation and 385 do not. The unattributed
set is 327 code repositories, 23 documentation pages, 19 tutorials, 12 papers and
preprints, 5 dataset benchmarks and 4 blog posts. One hundred of them record no
author name at all.

Every mechanical route has been worked through: arXiv front pages for all 126 papers
that had one, Crossref for every remaining DOI, and — for GitHub — owner accounts,
commit-email domains and profile bios across all 454 hosted entries. What is left
needs a browser (a handful of papers behind bot walls), a person's own knowledge, or
a decision about entries whose authors were never recorded.

Twenty-two repository entries return 404: the repository was deleted or renamed after
it was indexed. That is a data-quality task rather than an attribution one.
