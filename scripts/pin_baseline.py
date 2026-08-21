#!/usr/bin/env python3
"""Pin the Stage 0 baseline: design v2 preamble, "Baseline for all golden data".

Writes docs/perf/baseline.json with the source commit and a SHA-256 plus raw and
gzip size for every file the golden corpus and the payload budget depend on.
Nothing here reads a data file into anything but a hash; see CLAUDE.md.
"""
import gzip, hashlib, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The golden corpus is a function of exactly these inputs. If any hash moves, the
# corpus is stale and golden_diff.py must refuse to run against it.
CORPUS_INPUTS = [
    'data/sdv-index.json',
    'data/tail/openalex-citations.json',
    'data/tail/github-repos.json',
]
# The v1 runtime, hashed so the oracle can prove which bytes it characterized.
V1_RUNTIME = ['index.html', 'assets/js/sdv-index.js', 'assets/css/style.css']


def digest(path):
    p = ROOT / path
    raw = p.read_bytes()
    return {
        'sha256': hashlib.sha256(raw).hexdigest(),
        'bytes': len(raw),
        # mtime=0 so the gzip header carries no timestamp and the number is stable.
        'gzip_bytes': len(gzip.compress(raw, 9, mtime=0)),
    }


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def main():
    commit = git('rev-parse', 'HEAD')
    # Only the pinned files themselves have to be clean. Untracked work elsewhere
    # in the tree (curation shards, the Stage 0 scripts being written right now)
    # cannot change what the hashes below describe. A *modified* pinned file can:
    # the pin would then name a commit whose contents nobody can check out again.
    pinned = CORPUS_INPUTS + V1_RUNTIME
    dirty = [p for p in pinned if git('status', '--porcelain', '--', p)]
    if dirty:
        print('refusing to pin: these files differ from HEAD:',
              *dirty, sep='\n  ', file=sys.stderr)
        return 1

    out = {
        'pinned': '2026-08-21',
        'source_commit': commit,
        'note': ('Data files are byte-identical to 01a973bcccb406df14dc47e13045fef39ce7055d '
                 '("Version 1.0.0"), the commit the independent review ran against; the '
                 'commits since it touch docs only.'),
        'corpus_inputs': {p: digest(p) for p in CORPUS_INPUTS},
        'v1_runtime': {p: digest(p) for p in V1_RUNTIME},
    }
    dest = ROOT / 'docs/perf/baseline.json'
    dest.write_text(json.dumps(out, indent=2) + '\n')
    print('pinned', commit[:12], '->', dest.relative_to(ROOT))
    for name, d in out['corpus_inputs'].items():
        print(f'  {name:44s} {d["bytes"]:>10,} B  {d["gzip_bytes"]:>9,} B gz')
    return 0


if __name__ == '__main__':
    sys.exit(main())
