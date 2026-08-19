# SDVworld-index

A broad index of the Synthetic Data Vault (SDV) ecosystem: papers, theses, blog posts,
articles, documentation, case studies, and code repositories, each with a pointer, a short
summary, and multi-facet categorization.

Published at https://samanamarasinghe.github.io/SDVworld-index/

Modelled on `data/publications.json` in `mit-commit/commit-website`, widened beyond papers.

## Quick start

    python3 build.py            # merge shards, report counts, write nothing
    python3 build.py --write    # write data/sdv-index.json and data/build-info.json
    python3 tests/validate.py   # schema, vocabulary, pointer and alignment checks

Python 3 standard library throughout; nothing to install.

## Layout

- `data/shards/NNN-*.json` — curated entries, append-only, one shard per wave.
- `data/tail/` — raw harvest pools. Metadata joined at build time, never curation.
- `data/sdv-index.json` — generated. Never hand-edit it; CI regenerates it on `main`.
- `build.py` — merges shards, joins pool metadata, applies corrections.
- `harvest/` — the scripts that find and fetch candidates.
- `curate/` — the scripts that maintain curated data. None of them makes a judgment.
- `tests/validate.py` — the gate. Exit 1 fails CI.

Shards are never rewritten once complete. A later shard corrects an earlier one with
`"override": true`, which is why a correction must sort after everything it corrects.

## Where the documentation is

| file | what it covers |
|---|---|
| `README.txt` | orientation for a new maintainer: what the project is, how data flows, and the traps. The fastest way in. |
| `docs/schema.md` | **the record schema and the controlled vocabularies.** `tests/validate.py` and `curate/auto_curate.py` both parse the vocabulary lists out of it, so it is the definition rather than a description of one. |
| `docs/agent-guide.md` | the working procedure: the append-only rule, correction shards, the judgment conventions, the access routes that reach full text. |
| `TODO.txt` | what is left, with the commands that regenerate every count in it. |
| `docs/open-questions.md` | judgment calls awaiting the owner's ruling. |
| `harvest/README.md`, `curate/README.md` | what each script does and when to run it. |
| `AGENTS.md` | the reading order for an agent working here. |

Adding a facet value means adding it to `docs/schema.md` in the same commit that first uses
it — validation rejects any value not listed there.
