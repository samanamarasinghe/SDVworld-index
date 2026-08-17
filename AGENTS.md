# AGENTS.md

You are working on `samanamarasinghe/SDVworld-index`, an index of the Synthetic Data Vault
ecosystem published at https://samanamarasinghe.github.io/SDVworld-index/

Owner: Saman Amarasinghe. Report back to him, not to whoever queued the task.

This file is a pointer. The instructions live in `docs/`, and there is more of them than
fits here. Read in this order:

1. **`README.txt`** — what the project is, how the data flows, and the traps. Written for
   a human but it is the fastest orientation there is.
2. **`docs/schema.md`** — the record schema and the controlled vocabularies.
   `tests/validate.py` parses the vocabulary lists out of that file, so it is the
   definition and not a description of one.
3. **`docs/agent-guide.md`** — how to work here: the append-only rule, correction shards,
   the curation procedure, the accumulated judgment conventions, the access routes that
   get at full text, and how to run lanes in parallel.
4. **`TODO.txt`** — what is actually left, with the commands that regenerate every count
   in it.
5. **`docs/open-questions.md`** — judgment calls awaiting the owner's ruling. Do not
   resolve these yourself and do not invent a resolution to one already listed.

Also: `docs/site.md` for the page and its filter semantics, `docs/data-files.md` for what
every file under `data/` contains, `harvest/README.md` and `curate/README.md` for the
scripts.

The four rules worth stating twice, because breaking one is expensive:

- **Read the source before writing a summary.** Every summary ends with a clause saying
  which part of SDV is involved and how it is used, written from the source. Citing a
  paper is not using the software. If you could not read it, say so in `needs` and set
  `confidence: low` rather than guessing.
- **Shards are append-only**, and a correction must sort after every shard it corrects.
- **Never hand-edit `data/sdv-index.json` or `data/build-info.json`**; they are generated
  by `build.py --write`, and CI regenerates them on `main`.
- **Verify every push with a byte diff** against `origin/main`. Two silent corruptions
  have got through review; `validate.py` matches titles fuzzily and will not catch a
  dropped letter.

    python3 build.py            # merge shards, report counts, write nothing
    python3 build.py --write    # write the generated index
    python3 tests/validate.py   # schema, vocabulary, pointer and alignment checks
