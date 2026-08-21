#!/usr/bin/env python3
"""Teach the site's pooled-row suppression to match a curated entry's openalex_id.

THE DEFECT. `notCurated(r)` already checks every alias a POOL row carries --
`normalizeCite` builds `alt_urls` from the landing page, the DOI and the OpenAlex
id. But `curatedUrls()` indexes only `r.url` from each CURATED entry, so the only
alias that can ever match is the one the curator happened to file under.

That held while a no-DOI record's url WAS its OpenAlex id. Correcting two of them
to real sources -- an amslaurea eprint page and a Waterloo PDF -- left both works
counted twice: once as a curated entry, once as an uncurated pool row. The site
read 4964 against an index of 4907, a pool of 57 where 55 was right.

THE FIX. Index a curated entry's `openalex_id` alongside its url. Every record
`paper_curate_nodoi.py` writes carries that field, and it is the one pointer that
cannot drift when a url is corrected, so every future no-DOI record inherits the
suppression.

Deliberately NOT also indexing `doi`: it would work, but it changes suppression
for records well outside this lane, and the expected effect here is exactly two
rows. Widen it later on its own evidence if that is wanted.

The file is 52KB and carries literal \\u2014 escapes inside string literals, so it
is patched by exact-match splice rather than pushed whole -- a retyped copy is a
transcription risk for a two-line change.

    python3 curate/patch_site_js.py            # dry run, shows the splice
    python3 curate/patch_site_js.py --write    # apply

Verify afterwards with the stub-DOM harness, then rebuild nothing -- this is a
front-end file and build.py does not read it.
"""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
TARGET = os.path.join(ROOT, 'assets', 'js', 'sdv-index.js')

OLD = """  function curatedUrls() {
    if (!CURATED_URLS) {
      CURATED_URLS = {};
      DATA.forEach(function (r) { if (r.url) CURATED_URLS[urlKey(r.url)] = 1; });
    }
    return CURATED_URLS;
  }
"""

NEW = """  function curatedUrls() {
    if (!CURATED_URLS) {
      CURATED_URLS = {};
      /* Index every pointer the curated entry carries, not just the one it
         displays. A curator who replaces an OpenAlex record pointer with the real
         source -- the right thing to do -- would otherwise unsuppress the pool row
         that entry was meant to retire, and the work would be counted twice. */
      DATA.forEach(function (r) {
        [r.url, r.openalex_id].forEach(function (u) {
          if (u) CURATED_URLS[urlKey(u)] = 1;
        });
      });
    }
    return CURATED_URLS;
  }
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()

    with open(TARGET, encoding='utf-8') as fh:
        text = fh.read()
    print(f'{TARGET}: {len(text)} chars')

    count = text.count(OLD)
    if count != 1:
        sys.exit(f'refusing to patch: the target block appears {count} times, '
                 'expected exactly once. The file has moved on; re-read it.')
    if NEW in text:
        return print('already patched; nothing to do')

    patched = text.replace(OLD, NEW)
    print(f'\n--- removing ---\n{OLD}\n--- inserting ---\n{NEW}')
    print(f'{len(text)} -> {len(patched)} chars')

    if not args.write:
        return print('\ndry run; nothing written. Re-run with --write')
    with open(TARGET, 'w', encoding='utf-8') as fh:
        fh.write(patched)
    print(f'\nwrote {TARGET}')
    print('expected effect: the two patched no-DOI works stop appearing as pool '
          'rows, so the page total falls 4964 -> 4962 against an index of 4907 '
          '(pool 57 -> 55).')


if __name__ == '__main__':
    main()
