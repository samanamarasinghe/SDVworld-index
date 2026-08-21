#!/usr/bin/env python3
"""Build tests for the site projection (design v2 §8, "Build tests").

    python3 tests/build_tests.py

Output contract, §11 item 2: pass/fail per check plus the first failing detail only.

These do not re-derive the projection and compare it to itself. Where a check needs
an independent answer it gets one from somewhere that cannot have inherited the same
mistake -- the legacy export, the Stage 0 golden corpus recorded from the browser, or
the files on disk.
"""
import collections
import gzip
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SITE = ROOT / 'data/site'

import build                      # noqa: E402
import site_projection as sp      # noqa: E402

CHECKS = []


def check(name):
    def wrap(fn):
        CHECKS.append((name, fn))
        return fn
    return wrap


def gz(path):
    return len(gzip.compress(pathlib.Path(path).read_bytes(), 9, mtime=0))


# --------------------------------------------------------------------------

@check('legacy export is byte-identical after a rebuild')
def _legacy(ctx):
    """The public export is a downstream contract (§5 item 1). The projection refactor
    must not perturb it -- not its ordering, not its key order, not its whitespace."""
    dest = ROOT / 'data/sdv-index.json'
    before = dest.read_bytes()
    r = subprocess.run([sys.executable, str(ROOT / 'build.py'), '--write'],
                       capture_output=True, text=True, cwd=ROOT)
    if r.returncode:
        return f'build.py --write failed: {r.stderr.strip()[-300:]}'
    if dest.read_bytes() != before:
        return 'data/sdv-index.json changed; the refactor perturbed the public export'
    return None


@check('every core id maps to exactly one assembled record')
def _core_ids(ctx):
    core_ids = [r['id'] for r in ctx['core']]
    dupes = [i for i, n in collections.Counter(core_ids).items() if n > 1]
    if dupes:
        return f'{len(dupes)} duplicate id(s) in core, first {dupes[0]!r}'
    expected = {r['id'] for r in ctx['records']}
    if set(core_ids) != expected:
        missing = expected - set(core_ids)
        extra = set(core_ids) - expected
        if missing:
            return f'{len(missing)} assembled record(s) absent from core, first {sorted(missing)[0]!r}'
        return f'{len(extra)} core record(s) not in the assembled list, first {sorted(extra)[0]!r}'
    return None


@check('every detail id maps to exactly one core record, in its own bucket')
def _detail_ids(ctx):
    core_bucket = {r['id']: r['b'] for r in ctx['core']}
    seen = set()
    for name, content in ctx['buckets'].items():
        for rid in content:
            if rid in seen:
                return f'id {rid!r} appears in more than one detail bucket'
            seen.add(rid)
            if rid not in core_bucket:
                return f'detail id {rid!r} is in no core record'
            if core_bucket[rid] != name:
                return (f'id {rid!r} is filed in bucket {name} but core says '
                        f'{core_bucket[rid]}')
    # Anything core says has detail must actually have it, and vice versa.
    claims = {r['id'] for r in ctx['core'] if r.get('hs') or r.get('hn')}
    if claims != seen:
        missing = claims - seen
        if missing:
            return (f'{len(missing)} record(s) advertise summary/needs with no detail '
                    f'row, first {sorted(missing)[0]!r}')
        return (f'{len(seen - claims)} detail row(s) nothing advertises, first '
                f'{sorted(seen - claims)[0]!r}')
    return None


@check('detail holds summary and needs, and core holds neither')
def _detail_contents(ctx):
    """§5: the buckets carry summary and needs only. If either leaked back into core
    the payload work is undone and nobody would notice from the page."""
    for r in ctx['core']:
        for field in ('summary', 'needs'):
            if field in r:
                return f'core record {r["id"]!r} still carries {field!r}'
    by_id = {r['id']: r for r in ctx['records']}
    for name, content in ctx['buckets'].items():
        for rid, d in content.items():
            extra = set(d) - {'summary', 'needs'}
            if extra:
                return f'detail {rid!r} carries unexpected field(s) {sorted(extra)}'
            src = by_id[rid]
            if d.get('summary', '') != (src.get('summary') or ''):
                return f'detail summary for {rid!r} differs from the assembled record'
            if d.get('needs', '') != (src.get('needs') or ''):
                return f'detail needs for {rid!r} differs from the assembled record'
    return None


@check('core omits every export-only field')
def _lossy(ctx):
    """§1 item 2: the projection is intentionally lossy. These fields exist for
    downstream consumers of the export and must not travel to the browser."""
    banned = {'source_channel', 'evidence_tier', 'openalex_id', 'countries',
              'affiliations', 'affiliation_types', 'affiliation_countries',
              'alt_urls', 'auto_curated', 'duplicate_of', 'override',
              'forks', 'contributors', 'commits'}
    for r in ctx['core']:
        leaked = banned & set(r)
        if leaked:
            return f'core record {r["id"]!r} carries export-only field(s) {sorted(leaked)}'
    return None


@check('derived values are well formed')
def _derived(ctx):
    legal_types = {'academic', 'non_academic', 'unaffiliated'}
    legal_regions = {'americas', 'europe', 'asia', 'africa_oceania'}
    for r in ctx['core']:
        t = set(r.get('aff_type') or [])
        if not t or not t <= legal_types:
            return f'{r["id"]!r}: aff_type {sorted(t)} is not a legal set'
        if 'unaffiliated' in t and len(t) > 1:
            return f'{r["id"]!r}: unaffiliated cannot combine with another type'
        if not set(r.get('aff_region') or []) <= legal_regions:
            return f'{r["id"]!r}: aff_region {r.get("aff_region")} is not a legal set'
        if not (0.0 <= r['pop'] <= 1.0):
            return f'{r["id"]!r}: popularity {r["pop"]} is outside 0..1'
        if not re.fullmatch(r'[0-9a-f]{2}', r['b']):
            return f'{r["id"]!r}: bucket id {r["b"]!r} is malformed'
    return None


@check('organizations equal an independent re-split of the export')
def _organizations(ctx):
    """Recomputed from data/sdv-index.json rather than from the assembled list, so a
    mistake in the projection cannot be confirmed by the projection."""
    by_id = {r['id']: r for r in json.load(open(ROOT / 'data/sdv-index.json'))}
    for r in ctx['core']:
        src = by_id.get(r['id'])
        if src is None:
            continue          # a pool row; it has no export entry by construction
        want, seen = [], set()
        for value in src.get('affiliations') or []:
            for part in str(value or '').split(';'):
                part = part.strip()
                if part and part not in seen:
                    seen.add(part)
                    want.append(part)
        if (r.get('organizations') or []) != want:
            return (f'{r["id"]!r}: organizations {r.get("organizations")} != '
                    f'independently split {want}')
    return None


@check('every non-unknown affiliation country resolves to a region')
def _countries(ctx):
    """A veto must never rest on a country we failed to place, so an unplaced country
    is carried by no button and silently filters nothing. That is the safe failure
    mode, but it is still a curation gap: adding the country to the region table in
    both assets/js/sdv-index.js and site_projection.py is the fix. Zero as of
    2026-08-21, so this is strict rather than advisory."""
    unplaced = collections.Counter()
    for rec in json.load(open(ROOT / 'data/sdv-index.json')):
        for c in rec.get('affiliation_countries') or []:
            if not c:
                continue
            if str(c).lower().strip() in ('unknown', 'n/a', 'unspecified'):
                continue
            if not sp.region_of(c):
                unplaced[c] += 1
    if unplaced:
        name, n = unplaced.most_common(1)[0]
        return (f'{len(unplaced)} country name(s) resolve to no region, '
                f'commonest {name!r} on {n} affiliation(s)')
    return None


@check('the 44-row pool residue matches the Stage 0 corpus')
def _residue(ctx):
    """The strongest check available: the corpus recorded what the BROWSER produced
    from the raw pools, before any of this existed. The Python port has to land on the
    same ids in the same order or the port is wrong."""
    corpus = ROOT / 'docs/perf/golden/records.json'
    if not corpus.exists():
        return 'docs/perf/golden/records.json is missing; regenerate the Stage 0 corpus'
    recorded = json.load(open(corpus))
    n_curated = recorded['counts']['curated']
    want = recorded['ids'][n_curated:]
    got = [r['id'] for r in ctx['core'][len(ctx['assembled']):]]
    if got != want:
        if len(got) != len(want):
            return f'residue is {len(got)} rows, the corpus recorded {len(want)}'
        at = next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)
        return f'residue row {at}: built {got[at]!r}, corpus recorded {want[at]!r}'
    return None


@check('the manifest agrees with the files on disk')
def _manifest(ctx):
    m = ctx['manifest']
    for name, meta in m['files'].items():
        path = SITE / name
        if not path.exists():
            return f'manifest lists {name}, which does not exist'
        if path.stat().st_size != meta['bytes']:
            return (f'{name}: manifest says {meta["bytes"]:,} B, file is '
                    f'{path.stat().st_size:,} B')
    on_disk = {'core.json'} | {f'detail/{p.name}' for p in (SITE / 'detail').glob('*.json')}
    if set(m['files']) != on_disk:
        extra = on_disk - set(m['files'])
        return f'{len(extra)} file(s) on disk are absent from the manifest, e.g. {sorted(extra)[:1]}'
    if m['counts']['total'] != len(ctx['core']):
        return f'manifest total {m["counts"]["total"]} != {len(ctx["core"])} core records'
    if m['counts']['curated'] != len(ctx['assembled']):
        return f'manifest curated {m["counts"]["curated"]} != {len(ctx["assembled"])}'
    if m['detail_buckets'] != len(ctx['buckets']):
        return f'manifest claims {m["detail_buckets"]} buckets, {len(ctx["buckets"])} exist'
    return None


@check('bucket assignment and data_hash are deterministic')
def _deterministic(ctx):
    again = sp.write_site(ctx['assembled'])
    if again['data_hash'] != ctx['manifest']['data_hash']:
        return ('data_hash moved between two runs on identical input: '
                f'{ctx["manifest"]["data_hash"][:16]} then {again["data_hash"][:16]}')
    for r in ctx['core']:
        if sp.bucket_of(r['id']) != r['b']:
            return f'{r["id"]!r}: bucket_of() gives {sp.bucket_of(r["id"])}, core says {r["b"]}'
    return None


@check('no detail bucket exceeds 75 KB gzip')
def _bucket_size(ctx):
    worst, worst_n = None, 0
    for path in sorted((SITE / 'detail').glob('*.json')):
        n = gz(path)
        if n > worst_n:
            worst, worst_n = path.name, n
    if worst_n > 75_000:
        return f'{worst} is {worst_n:,} B gzip, over the 75,000 B cap'
    return None


@check('no v2 runtime file references either raw pool')
def _no_raw_pool(ctx):
    """§5: no runtime fetch references either raw pool. Checked in the source rather
    than only at run time, so a code path nobody exercised still fails the build."""
    offenders = []
    for path in sorted((ROOT / 'v2').rglob('*.js')):
        text = path.read_text()
        if 'openalex-citations.json' in text or 'github-repos.json' in text:
            offenders.append(str(path.relative_to(ROOT)))
    if offenders:
        return f'{len(offenders)} v2 file(s) still reference a raw pool: {offenders[0]}'
    return None


# --------------------------------------------------------------------------

def main():
    assembled, _ = build.assemble_records()
    ctx = {
        'assembled': assembled,
        'records': assembled + [r for pool in sp.pool_residue(assembled) for r in pool],
        'core': json.load(open(SITE / 'core.json'))['records'],
        'manifest': json.load(open(SITE / 'manifest.json')),
        'buckets': {p.stem: json.load(open(p))
                    for p in sorted((SITE / 'detail').glob('*.json'))},
    }
    failures = []
    for name, fn in CHECKS:
        try:
            problem = fn(ctx)
        except Exception as e:                      # noqa: BLE001
            problem = f'raised {type(e).__name__}: {e}'
        print(f'  [{"FAIL" if problem else " ok "}] {name}')
        if problem:
            failures.append((name, problem))
    if failures:
        name, problem = failures[0]
        print(f'\n  FIRST FAILING CHECK  {name}\n    {problem}')
        if len(failures) > 1:
            print(f'  ... and {len(failures) - 1} more')
        print('\nFAIL')
        return 1
    print(f'\nPASS: {len(CHECKS)} build checks')
    return 0


if __name__ == '__main__':
    sys.exit(main())
