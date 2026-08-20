#!/usr/bin/env python3
"""One-shot: make popularity a pure attention score.

First-party material used to be lifted into a fixed band here, which ranked a paper
cited once above one cited 109 times. Provenance is what importance 6 records, so
this axis keeps only measured attention. Delete this file after running it.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'assets', 'js', 'sdv-index.js')

NEW = '''  /* Popularity = attention the artifact has drawn, on one 0-1 scale so repositories
     and papers can be ranked against each other. Both sides are log-compressed,
     since raw stars and raw citations differ by an order of magnitude at the top.
     Repository weight blends stars with forks, contributors and commits, because a
     starless repository with real contributors is not the same as an abandoned one.
     Commits are clamped before blending: one monorepo carries 135,873 of them
     against a median of 16, and at ten commits to the point it alone reached the
     cap and put a two-star repository at the top of the whole index. No single
     signal should be able to carry an entry there.
     An entry carrying both signals takes the higher of the two. Entries with neither
     sit at 0.3, a neutral default rather than a zero.

     This axis is attention and NOTHING ELSE. First-party provenance used to lift
     every importance-6 entry into a fixed band here, which put a paper cited once
     above one cited 109 times and made a popularity sort unreadable. Provenance is
     what importance 6 records, and the two axes are each other's tie-break, so
     nothing is lost by keeping this one pure. */
  function popularity(rec) {
    var best = null;
    if (rec.kind === 'code_repo' || rec.stars != null) {
      var w = (rec.stars || 0) + 2 * (rec.forks || 0) + 5 * (rec.contributors || 0) +
              0.1 * Math.min(rec.commits || 0, 2000);
      best = Math.min(1, Math.log1p(w) / Math.log1p(8000));
    }
    if (rec.cited != null) {
      var c = Math.min(1, Math.log1p(rec.cited) / Math.log1p(1500));
      if (best === null || c > best) best = c;
    }
    return best === null ? 0.3 : best;
  }

'''

OPEN_MARK = '  /* First-party material is ordered editorially'
CLOSE_MARK = '  function sortWithin(arr) {'

source = open(PATH, encoding='utf-8').read()
if 'This axis is attention and NOTHING ELSE' in source:
    sys.exit('already applied; nothing to do')
if source.count(OPEN_MARK) != 1 or source.count(CLOSE_MARK) != 1:
    sys.exit('anchors not found exactly once; the file has moved on, patch by hand')

start, end = source.index(OPEN_MARK), source.index(CLOSE_MARK)
patched = source[:start] + NEW + source[end:]

for name in ('FOUNDATION', 'firstPartyBand', 'SCHOLARLY_KIND', 'measured('):
    if name in patched:
        sys.exit(f'{name} still referenced after the patch; aborting without writing')

open(PATH, 'w', encoding='utf-8').write(patched)
print(f'patched {PATH}: {end - start} chars replaced with {len(NEW)}')
print('now: node --check assets/js/sdv-index.js   (optional), then commit')
