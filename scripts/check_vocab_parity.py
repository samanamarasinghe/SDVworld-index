#!/usr/bin/env python3
"""Fail if v2's extracted vocabularies have drifted from v1's.

v2/assets/js/vocab.js carries a verbatim copy of assets/js/sdv-index.js lines
11-170: the kind/label/region tables and the facet model. A copy is only safe while
something checks it, and these tables are hundreds of country names -- a dropped
letter moves a facet count in a way no reviewer would spot.

This re-runs the extraction and compares. It does not repair: if the two differ,
either v1 changed (v1 is frozen during Stages 1-2, so that is itself a finding) or
someone hand-edited the copy.
"""
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BEGIN = '/* ===== BEGIN verbatim from assets/js/sdv-index.js ===== */\n'
END = '\n/* ===== END verbatim ===== */'
FIRST_LINE, LAST_LINE = 11, 170          # 1-based, inclusive


def extracted_from_v1():
    lines = (ROOT / 'assets/js/sdv-index.js').read_text().split('\n')
    block = lines[FIRST_LINE - 1:LAST_LINE]
    return '\n'.join(l[2:] if l.startswith('  ') else l for l in block).rstrip()


def copied_into_v2():
    text = (ROOT / 'v2/assets/js/vocab.js').read_text()
    if BEGIN not in text or END not in text:
        sys.exit('vocab.js has lost its verbatim markers')
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


def main():
    want, got = extracted_from_v1(), copied_into_v2()
    if want == got:
        print(f'vocab parity: ok ({len(want):,} bytes verbatim from v1 lines '
              f'{FIRST_LINE}-{LAST_LINE})')
        return 0
    print('vocab parity: DRIFT', file=sys.stderr)
    w, g = want.split('\n'), got.split('\n')
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else '<end of v1 block>'
        b = g[i] if i < len(g) else '<end of v2 copy>'
        if a != b:
            # First differing line only, per the §11 output contract.
            print(f'  first difference at block line {i + 1} '
                  f'(v1 source line {FIRST_LINE + i}):', file=sys.stderr)
            print(f'    v1: {a}', file=sys.stderr)
            print(f'    v2: {b}', file=sys.stderr)
            break
    return 1


if __name__ == '__main__':
    sys.exit(main())
