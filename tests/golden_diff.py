#!/usr/bin/env python3
"""Differential against the v1 characterization corpus (design v2 §8).

    python3 tests/golden_diff.py                       # self-check: v1 against itself
    python3 tests/golden_diff.py --actual docs/perf/golden/actual-v2.json

The corpus is produced by tests/oracle/driver.js (?emit=golden); the actual side by
the same driver against another engine (?emit=actual&target=v2). This only compares
and reports -- it deliberately contains no filter semantics of its own, so it cannot
quietly agree with a bug on both sides.

Output contract, design v2 §11 item 2: pass/fail counts plus THE FIRST FAILING STATE
ONLY. Dumping every difference makes a failure expensive to read and expensive to
feed back to an agent. --all overrides that when a human is genuinely triaging.
"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOLDEN = ROOT / 'docs/perf/golden'

# Design v2 §8/§4: the only states allowed to differ, and why. A state matching one
# of these prefixes is reported as a documented exception rather than a failure --
# but it is still reported, and it still fails if it is UNCHANGED when the change
# was supposed to move it (see --expect-exceptions-differ).
EXCEPTIONS = {
    'search-': 'token matching replaces substring matching (§4)',
    'imp-0-search-health': 'token matching replaces substring matching (§4)',
}


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except FileNotFoundError:
        sys.exit(f'missing {path} -- run the oracle first (see tests/oracle/README.md)')


def excepted(state_id):
    for prefix, why in EXCEPTIONS.items():
        if state_id.startswith(prefix):
            return why
    return None


def first_difference(want, got, want_ids, got_ids):
    """The single most legible thing that is wrong with this state, or None."""
    if want['total'] != got['total']:
        return f'total: expected {want["total"]}, got {got["total"]}'

    w = [want_ids[i] for i in want['ids']]
    g = [got_ids[i] for i in got['ids']]
    if w != g:
        ws, gs = set(w), set(g)
        missing, extra = ws - gs, gs - ws
        if missing:
            return f'{len(missing)} record(s) missing, first: {sorted(missing)[0]}'
        if extra:
            return f'{len(extra)} unexpected record(s), first: {sorted(extra)[0]}'
        at = next(i for i, (a, b) in enumerate(zip(w, g)) if a != b)
        return f'same records, different order at position {at}: expected {w[at]}, got {g[at]}'

    for facet in sorted(want['facets']):
        wf = want['facets'][facet]
        gf = got['facets'].get(facet)
        if gf is None:
            return f'facet {facet}: missing from the actual run'
        for value in sorted(wf):
            if wf[value] != gf.get(value):
                return (f'facet {facet}[{value!r}]: expected {wf[value]}, '
                        f'got {gf.get(value)}')
        extra = sorted(set(gf) - set(wf))
        if extra:
            return f'facet {facet}: unexpected value {extra[0]!r}'

    if want['groups'] != got['groups']:
        wg = {h: n for h, n in (want['groups'] or [])}
        gg = {h: n for h, n in (got['groups'] or [])}
        for h in sorted(set(wg) | set(gg)):
            if wg.get(h) != gg.get(h):
                return f'group {h!r}: expected {wg.get(h)}, got {gg.get(h)}'
        return 'group headings in a different order'
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--actual', help='actual-<target>.json; omit to self-check the corpus')
    ap.add_argument('--all', action='store_true', help='print every failure, not just the first')
    a = ap.parse_args()

    golden = load(GOLDEN / 'results.json')['results']
    golden_ids = load(GOLDEN / 'records.json')['ids']

    if a.actual:
        actual_doc = load(a.actual)
        actual, actual_ids = actual_doc['results'], actual_doc['ids']
        label = actual_doc.get('target', a.actual)
    else:
        # Self-check: the corpus against itself. Proves the comparator reads the
        # format and that a green run means something, before it is ever pointed at
        # a target that might legitimately differ.
        actual, actual_ids, label = golden, golden_ids, 'v1 (self-check)'

    missing = sorted(set(golden) - set(actual))
    extra = sorted(set(actual) - set(golden))

    failures, exceptions = [], []
    for sid in sorted(golden):
        if sid in missing:
            continue
        diff = first_difference(golden[sid], actual[sid], golden_ids, actual_ids)
        if diff is None:
            continue
        why = excepted(sid)
        (exceptions if why else failures).append((sid, diff, why))

    checked = len(golden) - len(missing)
    passed = checked - len(failures) - len(exceptions)
    print(f'golden_diff: {label}')
    print(f'  {checked} states compared, {passed} identical, '
          f'{len(exceptions)} documented exception(s), {len(failures)} FAILED')
    if missing:
        print(f'  {len(missing)} state(s) absent from the actual run, first: {missing[0]}')
    if extra:
        print(f'  {len(extra)} state(s) present only in the actual run, first: {extra[0]}')

    for sid, diff, why in exceptions[: None if a.all else 1]:
        print(f'  exception  {sid}: {diff}\n             ({why})')
    if len(exceptions) > 1 and not a.all:
        print(f'  ... and {len(exceptions) - 1} more exception(s); --all to list them')

    if failures:
        sid, diff, _ = failures[0]
        print(f'\n  FIRST FAILING STATE  {sid}\n    {diff}')
        if a.all:
            for sid, diff, _ in failures[1:]:
                print(f'  FAILED  {sid}\n    {diff}')
        elif len(failures) > 1:
            print(f'  ... and {len(failures) - 1} more failing state(s); --all to list them')

    bad = bool(failures or missing or extra)
    print('\nFAIL' if bad else '\nPASS')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
