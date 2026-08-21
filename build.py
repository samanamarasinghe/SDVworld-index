#!/usr/bin/env python3
"""Merge harvest shards into data/sdv-index.json and report facet counts.

Curation records judgment: what an entry is, how it uses SDV, how central that use is.
Repository metadata lives in data/tail/github-repos.json and bibliographic metadata in
data/tail/openalex-citations.json, so year, DOI, venue and popularity metrics are joined
here at build time. Shard-provided author and affiliation lists are authoritative; the
legacy author join is only a fallback for newer shards that do not carry those fields yet.

The join only ever fills a field a shard left empty. A curator's value always wins.
"""
import argparse
import collections
import datetime
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
SCHOLARLY = {'paper', 'preprint', 'thesis', 'dataset_benchmark'}


def norm_url(u):
    return re.sub(r'/+$', '', re.sub(r'^https?://(www\.)?', '', str(u or '').lower()))


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', str(t or '').lower()).strip()


def load(path):
    full = os.path.join(ROOT, path)
    return json.load(open(full)) if os.path.exists(full) else None


def missing(rec, field):
    return rec.get(field) in (None, '', [], {})


def build_lookups():
    """URL/title lookups into the two harvest pools. Absent pools are not an error."""
    gh = {}
    raw = load('data/tail/github-repos.json')
    for r in (raw or {}).get('repos', []) if isinstance(raw, dict) else (raw or []):
        gh[norm_url('https://github.com/' + r['repo'])] = r

    oa_url, oa_title = {}, {}
    for r in load('data/tail/openalex-citations.json') or []:
        loc = r.get('primary_location') or {}
        for u in (loc.get('landing_page_url'), r.get('doi'), r.get('id'), loc.get('pdf_url')):
            if u:
                oa_url.setdefault(norm_url(u), r)
        t = norm_title(r.get('title'))
        if t:
            oa_title.setdefault(t, r)
    return gh, oa_url, oa_title


def enrich(records):
    gh, oa_url, oa_title = build_lookups()
    filled = collections.Counter()
    unjoined = collections.Counter()

    def put(rec, field, value):
        if value in (None, '', [], {}) or not missing(rec, field):
            return
        rec[field] = value
        filled[field] += 1

    for rec in records:
        kind = rec.get('kind')
        # Route on where the artifact lives, not on how it was classified: a dataset or
        # benchmark hosted on GitHub is a repository as far as metadata is concerned.
        g = gh.get(norm_url(rec.get('url')))

        if kind == 'code_repo' or g:
            if not g:
                unjoined['code_repo'] += 1
                continue
            created = str(g.get('created') or '')[:4]
            put(rec, 'year', int(created) if created.isdigit() else None)
            if 'authors' not in rec:
                put(rec, 'authors', [a for a in [g.get('owner')] +
                                     (g.get('top_contributors') or []) if a])
            for field in ('stars', 'forks', 'commits', 'contributors'):
                put(rec, field, g.get(field))

        elif kind in SCHOLARLY:
            o = oa_url.get(norm_url(rec.get('url'))) or oa_title.get(norm_title(rec.get('title')))
            if not o:
                unjoined['scholarly'] += 1
                continue
            put(rec, 'doi', o.get('doi'))
            put(rec, 'year', o.get('publication_year'))
            put(rec, 'venue', ((o.get('primary_location') or {}).get('source') or {}).get('display_name'))
            put(rec, 'cited', o.get('cited_by_count'))
            if 'authors' not in rec:
                put(rec, 'authors', [(a.get('author') or {}).get('display_name')
                                     for a in (o.get('authorships') or [])
                                     if (a.get('author') or {}).get('display_name')])

    return filled, unjoined


def assemble_records():
    """The single source of truth for what the index contains.

    Pure: reads the shards and the harvest pools, returns the assembled record list
    and the counters the report prints. Both the legacy export and the site
    projection are emitted from THIS list, so there is no second merge
    implementation to drift (design v2 §5).
    """
    by_url, by_id, out = {}, {}, []
    dupes = retired = applied = orphaned = 0
    for path in sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json'))):
        for rec in json.load(open(path)):
            # A record carrying duplicate_of has been retired in favour of another
            # entry. It stays in its shard as an audit trail; it is not an index entry.
            #
            # Corrections are exempt: a correction that SETS duplicate_of is retiring
            # its target, not itself, and must reach the merge below. Testing this
            # first swallowed the correction and counted it as a retirement, so the
            # target stayed in the index while the log claimed otherwise.
            if rec.get('duplicate_of') and not rec.get('override'):
                retired += 1
                continue

            # Shards are append-only, so a re-read that finds importance, integration,
            # confidence -- or the url itself -- misjudged cannot edit the shard that
            # got it wrong. It appends a correction to a later shard instead, carrying
            # only the fields that change, and the correction is merged over the
            # original here.
            #
            # A correction is matched by id, not url. The field most often wrong is the
            # url: a first-party paper whose host reorganized, a repository that moved.
            # Matching on url would file the fix as a second entry and leave the dead
            # link in place, which is the opposite of a correction. It also means a
            # correction need not repeat the url at all.
            if rec.get('override'):
                prior = by_id.get(rec['id'])
                if prior is None:
                    # No target: the id is wrong, or the shard holding it is absent.
                    # Silently dropping this is how a correction gets lost.
                    orphaned += 1
                    continue
                by_url.pop(prior['url'].rstrip('/'), None)
                prior.update({k: v for k, v in rec.items() if k != 'override'})
                by_url[prior['url'].rstrip('/')] = prior
                applied += 1
                continue

            key = rec['url'].rstrip('/')
            if key in by_url:
                dupes += 1
                continue
            by_url[key] = rec
            by_id.setdefault(rec['id'], rec)
            out.append(rec)

    # Retire anything a correction has since marked duplicate_of. This runs after the
    # merge because the marking may arrive in a later shard than the entry it retires.
    before = len(out)
    out = [rec for rec in out if not rec.get('duplicate_of')]
    retired += before - len(out)
    for key in [k for k, r in list(by_url.items()) if r.get('duplicate_of')]:
        by_url.pop(key, None)

    ids = collections.Counter(rec['id'] for rec in out)
    collisions = sorted(i for i, n in ids.items() if n > 1)
    if collisions:
        # Ids key BibTeX filenames, data/impact.json and every correction patch,
        # which is matched by id rather than url. A collision does not corrupt the
        # page -- it silently misroutes all three. Refuse to write the index.
        raise SystemExit(
            f'ERROR: {len(collisions)} duplicate id(s) across shards: '
            f'{", ".join(collisions)}'
        )

    filled, unjoined = enrich(out)

    impact = load('data/impact.json')
    if impact:
        for rec in out:
            if rec['id'] in impact:
                rec.update(impact[rec['id']])  # hand-checked figures win over the join

    # auto_curated carries the batch response's model, token usage and service
    # tier. That is provenance for a curator, not something to publish: the page
    # fetches this file, and the usage blob is 586KB of a 4MB payload. Keep the
    # reviewed flag, which the page can filter on, and leave the full record in
    # the shard.
    for rec in out:
        marker = rec.get('auto_curated')
        if isinstance(marker, dict):
            rec['auto_curated'] = {'reviewed': bool(marker.get('reviewed'))}

    out.sort(key=lambda r: (r['kind'], -(r.get('year') or 0), r['title']))
    return out, {'dupes': dupes, 'retired': retired, 'applied': applied,
                 'orphaned': orphaned, 'filled': filled, 'unjoined': unjoined}


def write_legacy(out):
    """data/sdv-index.json: the unchanged public export (§5 item 1).

    Byte-identity for identical inputs is a hard requirement -- downstream consumers
    read this file, and the projection work must not perturb it. Serialization is
    exactly as it has always been; do not "tidy" it.
    """
    dest = os.path.join(ROOT, 'data', 'sdv-index.json')
    with open(dest, 'w') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write('\n')
    return dest


def write_build_info(out):
    """A stamp the page can show, so a visitor can tell how current the index is.

    This file is why the live footer said 0.99 while VERSION said 1.0.0: the workflow
    runs --write, which rewrites it, and then commits only sdv-index.json. §7 fixes
    the workflow; this function is unchanged.
    """
    info = {
        'version': (open(os.path.join(ROOT, 'VERSION')).read().strip()
                    if os.path.exists(os.path.join(ROOT, 'VERSION')) else None),
        'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),
        'entries': len(out),
    }
    with open(os.path.join(ROOT, 'data', 'build-info.json'), 'w') as fh:
        json.dump(info, fh, indent=1)
        fh.write('\n')


def report(out, stats, wrote):
    dest = os.path.join(ROOT, 'data', 'sdv-index.json')
    dupes, retired = stats['dupes'], stats['retired']
    applied, orphaned = stats['applied'], stats['orphaned']
    filled, unjoined = stats['filled'], stats['unjoined']
    print(f'{len(out)} entries, {dupes} duplicate urls dropped, '
          f'{retired} retired by duplicate_of, {applied} corrections applied '
          + (f'-> {dest}' if wrote else '(validated only; pass --write to update it)'))
    if orphaned:
        print(f'WARNING: {orphaned} correction(s) matched no entry by id and were skipped')
    if filled:
        print('joined from harvest pools: '
              + ', '.join(f'{n} {f}' for f, n in filled.most_common()))
    if unjoined:
        print('not joined: ' + ', '.join(f'{n} {k}' for k, n in unjoined.most_common()))

    for facet in ('kind', 'use_case', 'industry', 'sdv_component',
                  'affiliation_types', 'affiliation_countries'):
        counter = collections.Counter()
        for rec in out:
            val = rec.get(facet)
            counter.update([val] if isinstance(val, str) else (val or []))
        print(f'\n{facet}:')
        for name, count in counter.most_common():
            print(f'  {count:>4}  {name}')


def main(write=False, site=True):
    out, stats = assemble_records()
    if write:
        write_legacy(out)
        write_build_info(out)
        if site:
            from site_projection import write_site
            summary = write_site(out)
            print(f"site projection: {summary['records']} records "
                  f"({summary['curated']} curated + {summary['tail']} tail), "
                  f"{summary['buckets']} detail buckets, "
                  f"core {summary['core_bytes']:,} B")
    report(out, stats, write)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Merge shards into data/sdv-index.json.')
    parser.add_argument('--write', action='store_true',
                        help='write the index; omit to validate the shards only')
    parser.add_argument('--no-site', dest='site', action='store_false',
                        help='skip the data/site/ projection (legacy export only)')
    main(**vars(parser.parse_args()))
