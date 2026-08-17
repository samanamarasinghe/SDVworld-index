# curate/archive — closed lanes and one-off scripts

Nothing here is expected to run again. It is kept because a shard is easier to read next
to the brief that produced it, and because a one-off script records what was done to the
data far more precisely than a commit message does.

If something here starts being useful again, move it back up to `curate/` and give it a
row in `curate/README.md` rather than running it from this directory.

## Lane briefs

| file | what it was |
|---|---|
| `arxiv-lane-brief.md` | self-contained instructions for the four parallel sessions that curated the influential-arXiv lane into shards 63-90. The lane is closed |
| `post-parallel-audit.md` | the audit those four slices were checked against once they had all landed. Its findings are in `docs/agent-guide.md` as conventions |
| `curation-instructions.md` | the brief for the original citation-curation lane, which worked from `curate/curation-worklist.csv` — a file this repository no longer carries |
| `read-queue.md` | the queue of records whose abstract suggested SDV use without establishing it. Everything on it was either read or left at `confidence: medium`, which is accurate labelling rather than a gap |

## One-off scripts

| file | what it did |
|---|---|
| `make_worklist.py` | built `curate/curation-worklist.csv` from the citation pool for that lane |
| `apply_curation.py` | folded the filled-in worklist rows back into shards |
| `triage_signals.py` | scored worklist rows by how strongly their metadata suggested real SDV use, to order the reading |

All three depend on `curate/curation-worklist.csv`, which is not in the repository. Rebuild
it with `make_worklist.py` before expecting any of them to run.
