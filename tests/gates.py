#!/usr/bin/env python3
"""The design v2 §9 structural gates.

    python3 tests/gates.py                # v2 -- enforcing
    python3 tests/gates.py --target v1    # the baseline -- reports, never fails
    python3 tests/gates.py --stage 1      # only gates in force by that stage

Hard, deterministic, and not negotiable. Wall-clock timings are recorded by the
benchmark and deliberately NOT checked here: §9 says only structural properties can
fail CI, because timing noise that fails a build teaches people to ignore the build.

Every gate reads an artifact produced by something else -- the browser probe
(tests/bench/last-run-<target>.json), the semantic runner
(tests/semantic/last-run.json), the differential (docs/perf/golden/actual-<target>.json)
-- and each artifact is checked for staleness against the sources it describes. A gate
that silently passes on yesterday's evidence is worse than no gate.
"""
import argparse, gzip, hashlib, json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Which stage each gate comes into force at. Stage 1 runs on the current flat export
# and keeps the pools temporarily (§10), so the payload and raw-pool gates cannot
# apply until Stage 2 -- the artifacts they measure do not exist before then.
STAGE = {
    'render-cap': 1, 'node-budget': 1, 'one-scan': 1, 'no-blob-render': 1,
    'golden': 1, 'semantic': 1,
    'eager-payload': 2, 'detail-bucket': 2, 'no-raw-pool': 2,
}

EAGER_V2 = ['data/site/manifest.json', 'data/site/core.json',
            'data/site/summary-postings.json']
TARGET_SOURCES = {
    'v1': ['index.html', 'assets/js/sdv-index.js', 'assets/css/style.css'],
    'v2': ['v2'],
}


def gz(path):
    return len(gzip.compress(pathlib.Path(path).read_bytes(), 9, mtime=0))


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def newest_mtime(paths):
    latest = 0.0
    for rel in paths:
        p = ROOT / rel
        if p.is_dir():
            for f in p.rglob('*'):
                if f.is_file():
                    latest = max(latest, f.stat().st_mtime)
        elif p.exists():
            latest = max(latest, p.stat().st_mtime)
    return latest


class Gates:
    def __init__(self, target, stage, enforce):
        self.target, self.stage, self.enforce = target, stage, enforce
        self.rows = []

    def add(self, name, ok, detail, skipped=False):
        self.rows.append((name, ok, detail, skipped))

    def check(self, name, ok, detail):
        if STAGE[name] > self.stage:
            self.add(name, None, f'{detail}  (in force from stage {STAGE[name]})', True)
        else:
            self.add(name, ok, detail)

    # -- the gates ---------------------------------------------------------

    def structural(self, bench):
        if bench is None:
            # Every gate this method owns, so a missing run reads as "unproven"
            # rather than as a row that quietly disappeared from the report.
            for n in ('render-cap', 'node-budget', 'one-scan', 'no-blob-render',
                      'no-raw-pool'):
                self.check(n, False, 'no benchmark run on disk')
            return
        s = bench['structure']

        n = s['unique_records_rendered_default_view']
        self.check('render-cap', n <= 100, f'{n:,} unique records rendered initially (cap 100)')

        nodes = s['element_nodes_default_view']
        self.check('node-budget', nodes < 6000, f'{nodes:,} element nodes in the default flat view (budget 6,000)')

        scans = [t['corpus_scans'] for t in bench['timings'].values()]
        worst = max(scans) if scans else 0
        how = bench.get('scan_counter', '?')
        self.check('one-scan', worst <= 1,
                   f'{worst} corpus scan(s) in the worst interaction, counted via {how}')

        during_load = s['object_urls_created_during_load']
        during_inter = max((t['object_urls_created'] for t in bench['timings'].values()),
                           default=0)
        self.check('no-blob-render', during_load == 0 and during_inter == 0,
                   f'{during_load:,} object URLs during load, '
                   f'{during_inter:,} in the worst interaction (both must be 0)')

        pools = s['raw_pool_fetches']
        self.check('no-raw-pool', not pools,
                   'no raw-pool request' if not pools else f'fetched {", ".join(pools)}')

    def payload(self):
        eager = EAGER_V2 + [f'{self.target}/index.html', f'{self.target}/assets/js',
                            f'{self.target}/assets/css'] if self.target == 'v2' else \
                ['data/sdv-index.json', 'index.html', 'assets/js/sdv-index.js',
                 'assets/css/style.css']
        total, missing = 0, []
        for rel in eager:
            p = ROOT / rel
            if p.is_dir():
                total += sum(gz(f) for f in p.rglob('*') if f.is_file())
            elif p.exists():
                total += gz(p)
            else:
                missing.append(rel)
        note = f'{total / 1e6:.2f} MB gzip eager (budget 1.50 MB)'
        if missing:
            note += f'; not yet built: {", ".join(missing)}'
        self.check('eager-payload', total <= 1_500_000 and not missing, note)

        detail = ROOT / 'data/site/detail'
        if not detail.exists():
            self.check('detail-bucket', False, 'data/site/detail does not exist yet')
        else:
            sizes = {f.name: gz(f) for f in sorted(detail.glob('*.json'))}
            worst = max(sizes.items(), key=lambda kv: kv[1], default=('-', 0))
            self.check('detail-bucket', worst[1] <= 75_000,
                       f'largest bucket {worst[0]} at {worst[1] / 1000:.1f} KB gzip (cap 75 KB)')

    def golden(self):
        actual = ROOT / f'docs/perf/golden/actual-{self.target}.json'
        args = [sys.executable, str(ROOT / 'tests/golden_diff.py')]
        if self.target != 'v1':
            if not actual.exists():
                self.check('golden', False, f'no {actual.name}; run the oracle with '
                                            f'?emit=actual&target={self.target}')
                return
            args += ['--actual', str(actual)]
        r = subprocess.run(args, capture_output=True, text=True)
        summary = next((l.strip() for l in r.stdout.splitlines() if 'states compared' in l),
                       r.stdout.strip().splitlines()[-1] if r.stdout.strip() else 'no output')
        if r.returncode:
            first = next((l.strip() for l in r.stdout.splitlines()
                          if 'FIRST FAILING STATE' in l), '')
            detail = next((l.strip() for l in r.stdout.splitlines()
                           if l.startswith('    ')), '')
            summary = f'{summary}  |  {first} {detail}'.strip()
        self.check('golden', r.returncode == 0, summary)

    def semantic(self):
        p = ROOT / 'tests/semantic/last-run.json'
        if not p.exists():
            self.check('semantic', False, 'no run on disk; open /tests/semantic/runner.html')
            return
        run = json.loads(p.read_text())
        stale = []
        if run.get('fixture_sha256') != sha(ROOT / 'tests/semantic/fixture.json'):
            stale.append('fixture.json')
        if run.get('cases_sha256') != sha(ROOT / 'tests/semantic/cases.js'):
            stale.append('cases.js')
        if run.get('target') != self.target:
            stale.append(f"run targets {run.get('target')}, not {self.target}")
        if stale:
            self.check('semantic', False, 'stale run: ' + ', '.join(stale))
            return
        first = next((r for r in run['results'] if r.get('ok') is False), None)
        detail = f"{run['passed']} passed, {run['failed']} failed, {run['pending']} pending"
        if first:
            detail += f"  |  first failure: {first['id']}: {first['failure']}"
        self.check('semantic', run['failed'] == 0, detail)

    # -- reporting ---------------------------------------------------------

    def report(self):
        width = max(len(n) for n, *_ in self.rows)
        for name, ok, detail, skipped in self.rows:
            mark = '  --' if skipped else (' ok ' if ok else 'FAIL')
            print(f'  [{mark}] {name.ljust(width)}  {detail}')
        failed = [n for n, ok, _, sk in self.rows if ok is False and not sk]
        if not self.enforce:
            print(f'\nBASELINE ({self.target}): reporting only, no gate can fail. '
                  f'{len(failed)} would fail against the v2 budget.')
            return 0
        if failed:
            print(f'\nFAIL: {len(failed)} gate(s) -- {", ".join(failed)}')
            return 1
        print(f'\nPASS: all gates in force at stage {self.stage}')
        return 0


def load_bench(target):
    p = ROOT / f'tests/bench/last-run-{target}.json'
    if not p.exists():
        return None
    doc = json.loads(p.read_text())
    if p.stat().st_mtime < newest_mtime(TARGET_SOURCES.get(target, [])):
        print(f'  !! {p.relative_to(ROOT)} is older than the {target} sources it '
              f'measures; re-run the benchmark', file=sys.stderr)
        return None
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', default='v2', choices=['v1', 'v2'])
    ap.add_argument('--stage', type=int, default=1)
    a = ap.parse_args()

    # v1 is the thing being replaced. Running the gates against it is how the
    # baseline gets recorded and how the gates themselves are shown to have teeth --
    # a gate v1 passes is a gate that is not measuring the problem.
    enforce = a.target != 'v1'
    print(f'gates: target {a.target}, stage {a.stage}'
          f'{"" if enforce else "  (baseline: reporting only)"}')

    g = Gates(a.target, a.stage, enforce)
    g.structural(load_bench(a.target))
    g.payload()
    g.golden()
    g.semantic()
    return g.report()


if __name__ == '__main__':
    sys.exit(main())
