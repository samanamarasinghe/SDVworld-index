#!/usr/bin/env python3
"""Collect SDV-usage evidence from a repository, for a curating agent to read.

    python harvest/repo_evidence.py owner/repo [owner/repo ...]
    python harvest/repo_evidence.py --slice 3/8      # partition the pooled repos
    python harvest/repo_evidence.py --skip-existing  # resume: leave ok records alone
    python harvest/repo_evidence.py --uncurated      # skip repos already indexed
    python harvest/repo_evidence.py --out evidence/  # default: harvest/evidence/

No GITHUB_TOKEN is required. Two acquisition paths, chosen by repository size as
recorded in data/tail/github-repos.json:

  small (< SIZE_CAP kB)  codeload tarball, extracted once, grepped locally.
  large (>= SIZE_CAP)    partial clone filtered by blob size, so the fetch skips
                         exactly what makes large repositories large -- media, model
                         weights, datasets -- none of which can hold an import line.

Output is one JSON file per repository holding the README, the dependency
declarations, and every pattern hit with surrounding context. It contains no
summary and no facets: this script gathers, it does not judge. Writing the SDV
clause from this evidence is the agent's job.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')
INDEX = os.path.join(ROOT, 'data', 'sdv-index.json')
DEFAULT_OUT = os.path.join(ROOT, 'harvest', 'evidence')

SIZE_CAP_KB = 20000
BLOB_LIMIT = '128k'
CONTEXT_LINES = 4
MAX_HITS_PER_PATTERN = 12
READ_EXTENSIONS = ('.py', '.ipynb', '.txt', '.toml', '.cfg', '.yaml', '.yml',
                   '.md', '.r', '.rmd', '.qmd')
DEP_FILES = ('requirements.txt', 'pyproject.toml', 'setup.py', 'setup.cfg',
             'environment.yml', 'Pipfile', 'poetry.lock', 'conda/meta.yaml')

# Keyed to the evidence codes in data/tail/github-repos.json so a hit here can be
# lined up against the code-search pattern that surfaced the repository.
PATTERNS = {
    'st': r'from sdv\.single_table import',
    'md': r'from sdv\.metadata import',
    'mt': r'from sdv\.multi_table import',
    'sq': r'from sdv\.sequential import',
    'ev': r'from sdv\.evaluation',
    'sdv_any': r'\b(?:import sdv|from sdv\b)',
    'ctgan_mod': r'\b(?:import ctgan|from ctgan\b)',
    'ct': r'CTGANSynthesizer',
    'gc': r'GaussianCopulaSynthesizer',
    'par': r'PARSynthesizer',
    'hma': r'HMASynthesizer',
    'tvae': r'TVAESynthesizer',
    'sm': r'\b(?:import sdmetrics|from sdmetrics)',
    'rdt': r'\b(?:import rdt|from rdt)',
    'gym': r'\b(?:import sdgym|from sdgym)',
    'copulas': r'\b(?:import copulas|from copulas)',
}
# Directory names that betray a vendored copy rather than a dependency.
VENDOR_HINTS = re.compile(
    r'(^|/)(sdv|sdv_ctgan|sdv_copulas|sdv_rdt|ctgan|copulas|rdt|sdmetrics|sdgym)(/|$)',
    re.I)
COMPILED = {code: re.compile(pat) for code, pat in PATTERNS.items()}


def run(cmd, cwd=None, timeout=300):
    return subprocess.run(cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True)


def fetch_tarball(repo, dest):
    url = f'https://codeload.github.com/{repo}/tar.gz/HEAD'
    path = os.path.join(dest, 'src.tgz')
    with urllib.request.urlopen(url, timeout=180) as response, open(path, 'wb') as fh:
        shutil.copyfileobj(response, fh)
    with tarfile.open(path) as tar:
        # Skip absolute and parent-escaping members rather than trusting the archive,
        # and skip LINKS entirely. Python's data filter raises AbsoluteLinkError on a
        # committed virtualenv symlink -- venv/bin/python pointing at the machine that
        # built it -- and that exception aborts the WHOLE extraction, so one stray
        # symlink cost the entire repository. Nine of the first pass's fourteen
        # failures were this and not a dead repository. Nothing here needs to follow a
        # link: the scan reads regular files.
        safe = [m for m in tar.getmembers()
                if not m.name.startswith('/') and '..' not in m.name.split('/')
                and not (m.issym() or m.islnk())]
        tar.extractall(dest, members=safe)
    os.remove(path)
    roots = [d for d in os.listdir(dest) if os.path.isdir(os.path.join(dest, d))]
    return os.path.join(dest, roots[0]) if roots else dest


def fetch_partial(repo, dest):
    """Size-limited partial clone: one batched fetch of every blob under BLOB_LIMIT.

    A blobless clone plus per-path checkout was tried first and abandoned: git makes
    one network round trip per checkout invocation, so a few thousand files take
    longer than downloading the whole repository. Filtering by blob size keeps it to
    a single fetch. Measured on a 42 MB repository: 5 s, 4943 files in the tree.

    git exits non-zero when the checkout cannot materialise every path -- which the
    filter guarantees for any blob over BLOB_LIMIT, exactly the files this is meant
    to skip. "Clone succeeded, but checkout failed" is the normal outcome here, so
    the test is whether a work tree came back, not the exit status.
    """
    work = os.path.join(dest, 'repo')
    clone = run(['git', 'clone', f'--filter=blob:limit={BLOB_LIMIT}', '--depth', '1',
                 f'https://github.com/{repo}.git', work], timeout=600)
    listing = run(['git', 'ls-tree', '-r', '--name-only', 'HEAD'], cwd=work)
    if listing.returncode != 0:
        # Keep the tail: git puts the reason last, after pages of progress output.
        raise RuntimeError((clone.stderr.strip() or listing.stderr.strip())[-300:])
    return work, len([p for p in listing.stdout.splitlines() if p])


def scan(root):
    hits, vendored, deps = {}, set(), {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.venv')]
        for name in files:
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root)
            if name in DEP_FILES or rel.replace(os.sep, '/').endswith(DEP_FILES):
                try:
                    lines = [ln.rstrip() for ln in open(full, errors='ignore')
                             if re.search(r'sdv|ctgan|sdmetrics|sdgym|copulas|\brdt\b',
                                          ln, re.I)]
                except OSError:
                    lines = []
                if lines:
                    deps[rel] = lines[:20]
            parent = os.path.dirname(rel).replace(os.sep, '/')
            match = VENDOR_HINTS.search(parent)
            if match:
                # Keep the shallowest directory that matched, not every descendant of
                # it -- one line saying "CTGAN/" beats forty saying "CTGAN/.github/...".
                vendored.add(parent[:match.end()].strip('/'))
            if not name.lower().endswith(READ_EXTENSIONS):
                continue
            try:
                content = open(full, errors='ignore').read().splitlines()
            except OSError:
                continue
            for code, pattern in COMPILED.items():
                for number, line in enumerate(content, 1):
                    if not pattern.search(line):
                        continue
                    bucket = hits.setdefault(code, [])
                    if len(bucket) >= MAX_HITS_PER_PATTERN:
                        break
                    lo = max(0, number - 1 - CONTEXT_LINES)
                    bucket.append({
                        'file': rel.replace(os.sep, '/'),
                        'line': number,
                        'text': line.strip()[:300],
                        'context': [c[:200] for c in content[lo:number + CONTEXT_LINES]],
                    })
    return hits, sorted(vendored), deps


def read_readme(root):
    for name in ('README.md', 'README.rst', 'README.txt', 'readme.md', 'README'):
        path = os.path.join(root, name)
        if os.path.exists(path):
            return open(path, errors='ignore').read()[:20000]
    return ''


GITHUB_URL = re.compile(r'https?://(?:www\.)?github\.com/([^/#?]+)/([^/#?]+)')


def indexed_repos():
    """Repositories that already carry a curated entry in the built index.

    Lowercased on both sides: GitHub treats owner/name case-insensitively, and an
    entry url is typed by hand often enough for its capitalisation to drift from
    the pool's.
    """
    try:
        entries = json.load(open(INDEX))
    except (OSError, ValueError):
        return set()
    if isinstance(entries, dict):
        entries = entries.get('entries', [])
    found = set()
    for entry in entries:
        match = GITHUB_URL.match(entry.get('url') or '')
        if match:
            found.add(f'{match.group(1)}/{match.group(2)}'.removesuffix('.git').lower())
    return found


def harvested(repo, out_dir):
    """True if an earlier run already wrote a successful record for this repo.

    An error record does not count. A 404 is permanent but a timed-out fetch is
    not, and re-trying a handful of failures costs less than silently dropping a
    repository that would have worked on the second attempt.
    """
    path = os.path.join(out_dir, repo.replace('/', '__') + '.json')
    if not os.path.exists(path):
        return False
    try:
        return json.load(open(path)).get('status') == 'ok'
    except (OSError, ValueError):  # truncated by an interrupted run
        return False


def harvest(repo, size_kb, out_dir):
    dest = tempfile.mkdtemp(prefix='sdvrepo-')
    record = {'repo': repo, 'disk_kb': size_kb}
    try:
        if size_kb and size_kb >= SIZE_CAP_KB:
            root, tree_size = fetch_partial(repo, dest)
            record['method'], record['tree_files'] = 'partial_clone', tree_size
        else:
            root = fetch_tarball(repo, dest)
            record['method'] = 'tarball'
        hits, vendored, deps = scan(root)
        record.update({
            'status': 'ok',
            'readme': read_readme(root),
            'hits': hits,
            'hit_codes': sorted(hits),
            'vendored_dirs': vendored,
            'dependencies': deps,
        })
    except Exception as exc:  # network, archive, or git failure: record and move on
        record.update({'status': 'error', 'error': f'{type(exc).__name__}: {exc}'[:300]})
    finally:
        shutil.rmtree(dest, ignore_errors=True)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, repo.replace('/', '__') + '.json')
    with open(path, 'w') as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repos', nargs='*')
    parser.add_argument('--slice', help='K/N, take every Nth repo from the pool')
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument('--skip-existing', action='store_true',
                        help='leave repos that already have an ok record alone')
    parser.add_argument('--uncurated', action='store_true',
                        help='leave repos that already have an index entry alone')
    args = parser.parse_args()

    sizes = {r['repo']: r.get('disk_kb', 0) for r in json.load(open(POOL))['repos']}
    if args.slice:
        k, n = (int(v) for v in args.slice.split('/'))
        names = sorted(sizes)[k - 1::n]
    elif args.repos:
        names = args.repos
    else:
        parser.error('give repo names or --slice K/N')

    if args.uncurated:
        curated = indexed_repos()
        keep = [r for r in names if r.lower() not in curated]
        print(f'skipping {len(names) - len(keep)} already indexed, '
              f'{len(keep)} uncurated', file=sys.stderr)
        names = keep

    if args.skip_existing:
        keep = [r for r in names if not harvested(r, args.out)]
        print(f'skipping {len(names) - len(keep)} already harvested, '
              f'{len(keep)} to go', file=sys.stderr)
        names = keep

    ok = 0
    for i, repo in enumerate(names, 1):
        record = harvest(repo, sizes.get(repo, 0), args.out)
        ok += record['status'] == 'ok'
        print(f'[{i}/{len(names)}] {repo} {record["status"]} '
              f'{record.get("method", "")} codes={record.get("hit_codes", [])}',
              flush=True)
    print(f'{ok}/{len(names)} harvested -> {args.out}', file=sys.stderr)


if __name__ == '__main__':
    main()
