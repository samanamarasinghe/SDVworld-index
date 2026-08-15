#!/usr/bin/env python3
"""Validate the index: schema, vocabulary, and above all that every pointer
points where the entry says it does.

    python tests/validate.py              # offline checks only, seconds, no network
    python tests/validate.py --online     # adds DOI resolution and link checking
    python tests/validate.py --online --doi-only
    python tests/validate.py --online --links-only [--limit N]
    python tests/validate.py --online --scope all         # all ~3,000 pointers

Exit status is 0 when every check passes, 1 otherwise, so this can gate CI.

The controlled vocabularies are parsed out of README.md rather than restated
here. A test that keeps its own copy of the schema drifts from it, and then
agrees with itself while the data is wrong.

Stdlib only. OPENALEX_API_KEY is used if set; the polite pool works without it.
"""
import argparse
import collections
import difflib
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHOLARLY = {'paper', 'preprint', 'thesis', 'dataset_benchmark'}
FACETS = ('kind', 'use_case', 'industry', 'sdv_component', 'sdv_concept', 'integration')

failures = []
notes = []


def fail(check, detail):
    failures.append((check, detail))


def note(msg):
    notes.append(msg)


# ---------------------------------------------------------------- loading

def load(rel):
    path = os.path.join(ROOT, rel)
    return json.load(open(path)) if os.path.exists(path) else None


def shard_files():
    return sorted(glob.glob(os.path.join(ROOT, 'data', 'shards', '*.json')))


def read_vocabularies():
    """Pull the controlled vocabularies out of README.md.

    Each is a line of the form `**name** (aside): a, b, c` possibly wrapped over
    several lines. Parenthetical glosses are stripped before splitting."""
    text = open(os.path.join(ROOT, 'README.md')).read()
    vocab = {}
    for facet in FACETS:
        m = re.search(r'\*\*' + facet + r'\*\*[^:]*:(.*?)(?:\n\s*\n)', text, re.S)
        if not m:
            fail('vocabulary', f'README.md has no **{facet}** list; cannot validate that facet')
            continue
        body = re.sub(r'\([^)]*\)', ' ', m.group(1))
        vocab[facet] = {t for t in re.split(r'[,\s]+', body) if re.fullmatch(r'[a-z][a-z_]*', t or '')}
    return vocab


def norm_doi(v):
    return re.sub(r'^https?://(dx\.)?doi\.org/', '', str(v or '').strip().lower()).rstrip('/')


def norm_title(t):
    return re.sub(r'[^a-z0-9]+', ' ', str(t or '').lower()).strip()


def norm_url(u):
    return re.sub(r'/+$', '', re.sub(r'^https?://(www\.)?', '', str(u or '').lower()))


# ---------------------------------------------------------------- offline

def check_shards_parse():
    records = []
    for path in shard_files():
        name = os.path.basename(path)
        try:
            data = json.load(open(path))
        except Exception as e:
            fail('shard parses', f'{name}: {e}')
            continue
        if not isinstance(data, list):
            fail('shard parses', f'{name}: top level is {type(data).__name__}, expected a list')
            continue
        for rec in data:
            if not isinstance(rec, dict):
                fail('shard parses', f'{name}: contains a {type(rec).__name__}, expected objects')
                continue
            records.append((name, rec))
    note(f'{len(shard_files())} shards, {len(records)} records')
    return records


def check_required_fields(records):
    """Full entries need the fields the page renders from. Corrections carry
    only what changes, so they are held to id + override alone."""
    for name, rec in records:
        if rec.get('override'):
            if not rec.get('id'):
                fail('required fields', f'{name}: correction with no id')
            continue
        for field in ('id', 'title', 'url', 'kind', 'summary'):
            if rec.get(field) in (None, '', [], {}):
                fail('required fields', f'{name}: {rec.get("id", "<no id>")} missing {field}')


def check_ids(records):
    ids = collections.Counter(r['id'] for _, r in records if not r.get('override') and r.get('id'))
    for i, n in ids.items():
        if n > 1:
            fail('unique ids', f'{i} defined {n} times')
    known = set(ids)
    for name, rec in records:
        if rec.get('override') and rec.get('id') not in known:
            fail('correction targets', f'{name}: override for unknown id {rec.get("id")}')
        dup = rec.get('duplicate_of')
        if dup and dup not in known:
            fail('duplicate_of targets', f'{name}: {rec.get("id")} retires unknown id {dup}')
    return known


def check_vocabularies(records, vocab):
    for name, rec in records:
        for facet, allowed in vocab.items():
            v = rec.get(facet)
            for value in ([v] if isinstance(v, str) else (v or [])):
                if value not in allowed:
                    fail('vocabulary', f'{rec.get("id")}: {facet}={value!r} is not in README')


def check_scales(records):
    for name, rec in records:
        imp = rec.get('importance')
        if imp is not None and (not isinstance(imp, int) or not 0 <= imp <= 6):
            fail('importance range', f'{rec.get("id")}: importance={imp!r}, expected an integer 0-6')
        conf = rec.get('confidence')
        if conf is not None and conf not in ('high', 'medium', 'low'):
            fail('confidence values', f'{rec.get("id")}: confidence={conf!r}')
        year = rec.get('year')
        if year is not None and (not isinstance(year, int) or not 1990 <= year <= 2100):
            fail('year sanity', f'{rec.get("id")}: year={year!r}')


def check_url_shape(records):
    for name, rec in records:
        u = rec.get('url')
        if not u:
            continue
        p = urllib.parse.urlparse(str(u))
        if p.scheme not in ('http', 'https') or not p.netloc:
            fail('url shape', f'{rec.get("id")}: {u!r} is not an absolute http(s) url')
        elif ' ' in str(u):
            fail('url shape', f'{rec.get("id")}: {u!r} contains a space')


def check_built_index(index):
    """The generated index is what the page reads; it must be current."""
    if index is None:
        fail('built index', 'data/sdv-index.json is missing; run python build.py --write')
        return []
    urls = collections.Counter(norm_url(r.get('url')) for r in index if r.get('url'))
    for u, n in urls.items():
        if n > 1:
            fail('unique urls in the index', f'{u} appears {n} times')
    for r in index:
        if r.get('duplicate_of'):
            fail('retired entries', f'{r.get("id")} carries duplicate_of but is still in the index')
    return index


def check_url_vs_joined_doi(index):
    """The check that matters. An entry's url and the DOI joined from OpenAlex
    by title are two independent records of the same pointer. When they
    disagree, one of them was invented -- this is exactly how the 24 fabricated
    DOIs in shard 08 were found."""
    checked = unverifiable = 0
    for r in index:
        if r.get('kind') not in SCHOLARLY:
            continue
        u, d = norm_doi(r.get('url')), norm_doi(r.get('doi'))
        if not u.startswith('10.') or not d:
            unverifiable += 1
            continue
        checked += 1
        if u != d:
            fail('url agrees with the joined DOI',
                 f'{r.get("id")}: url says {u}, OpenAlex says {d} for this title')
    note(f'url-vs-DOI cross-check: {checked} scholarly entries verified, '
         f'{unverifiable} have no second source and were skipped')


def check_repo_urls_are_repos(index):
    for r in index:
        if r.get('kind') != 'code_repo':
            continue
        u = str(r.get('url') or '')
        if 'github.com' not in u:
            continue
        parts = [p for p in urllib.parse.urlparse(u).path.split('/') if p]
        if len(parts) != 2:
            fail('repo url shape', f'{r.get("id")}: {u} is not github.com/<owner>/<name>')


def check_repos_against_pool(index, gh):
    """Every third-party repo entry should correspond to a row in the harvest
    pool. First-party sdv-dev repos are expected to be absent: the pool came
    from a third-party code search."""
    if gh is None:
        note('data/tail/github-repos.json absent; skipped repo corroboration')
        return
    pool = {norm_url('github.com/' + r['repo']) for r in gh.get('repos', [])}
    offsite = 0
    for r in index:
        if r.get('kind') != 'code_repo':
            continue
        u = str(r.get('url') or '')
        if 'github.com' not in u:
            offsite += 1          # CRAN, PyPI and the like: nothing to corroborate against
            continue
        if '/sdv-dev/' in u.lower():
            continue              # first-party; the pool was a third-party code search
        if norm_url(u) not in pool:
            fail('repo corroborated by the pool', f'{r["id"]}: no row in data/tail/github-repos.json')
    if offsite:
        note(f'{offsite} code entries are not hosted on GitHub; no pool row to corroborate them')


def check_pool_dedup(index, cite):
    """A curated work must not also appear as an uncurated pooled row.

    A work is reachable by three pointers -- landing page, DOI, OpenAlex id --
    and a curator may file it under any one of them, so the page has to match on
    all three. This asserts that it does, rather than recomputing the overlap:
    once the page is alias-aware the overlap is zero by construction, and a test
    that only measured it would pass for ever while silently permitting a
    regression to naive matching."""
    if cite is None:
        return
    cur = {norm_url(r['url']) for r in index if r.get('url')}
    naive = 0
    for w in cite:
        loc = w.get('primary_location') or {}
        shown = loc.get('landing_page_url') or w.get('doi') or w.get('id')
        alts = {norm_url(u) for u in (loc.get('landing_page_url'), w.get('doi'), w.get('id')) if u}
        if norm_url(shown) not in cur and (alts & cur):
            naive += 1

    js_path = os.path.join(ROOT, 'assets', 'js', 'sdv-index.js')
    js = open(js_path).read() if os.path.exists(js_path) else ''
    alias_aware = 'alt_urls' in js and re.search(r'function notCurated[^}]*alt_urls', js, re.S)
    if not alias_aware:
        fail('pool dedup is alias-aware',
             f'notCurated in sdv-index.js matches a single url; {naive} curated works '
             f'would also show as pooled rows')
    elif naive:
        note(f'alias matching suppresses {naive} would-be duplicate pooled rows')


# ---------------------------------------------------------------- online

def openalex(path, **params):
    key = os.environ.get('OPENALEX_API_KEY')
    if key:
        params['api_key'] = key
    elif os.environ.get('OPENALEX_EMAIL'):
        params['mailto'] = os.environ['OPENALEX_EMAIL']
    url = 'https://api.openalex.org/' + path + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as fh:
        return json.load(fh)


def same_work(a, b):
    """Do two titles name the same paper?

    Two things make an honest title differ from the registry's. Cosmetic
    variants -- a "Poster:" prefix, an expanded acronym, a publisher typo --
    keep character similarity above 0.9. Subtitles are the harder case: a shard
    may carry the main title while the registry carries title-and-subtitle, so
    character similarity falls to 0.66 while every word of the shorter title is
    still present. Either signal is enough. A DOI pointing at an unrelated paper
    fails both, at 0.15 similarity and no shared words at all."""
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.70:
        return True
    wa, wb = set(a.split()), set(b.split())
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.85


def doi_registered(doi):
    req = urllib.request.Request('https://doi.org/' + doi, method='HEAD',
                                 headers={'User-Agent': 'SDVworld-index-validator'})
    try:
        urllib.request.urlopen(req, timeout=25)
        return True
    except urllib.error.HTTPError as e:
        return e.code < 400
    except Exception:
        return False


def check_dois_resolve(index):
    """Ask OpenAlex what each DOI actually is, 50 at a time, and compare titles.
    Catches a DOI that resolves to the wrong paper -- which a mere 200 response
    would not."""
    want = {}
    for r in index:
        if r.get('kind') in SCHOLARLY:
            d = norm_doi(r.get('url'))
            if d.startswith('10.'):
                want.setdefault(d, r)
    dois = sorted(want)
    note(f'resolving {len(dois)} DOIs against OpenAlex in {(len(dois) + 49) // 50} requests')
    seen = set()
    for i in range(0, len(dois), 50):
        batch = dois[i:i + 50]
        try:
            data = openalex('works', filter='doi:' + '|'.join(batch), per_page=50)
        except Exception as e:
            fail('DOI resolves', f'batch starting {batch[0]}: {e}')
            continue
        for w in data.get('results', []):
            d = norm_doi(w.get('doi'))
            seen.add(d)
            rec = want.get(d)
            if not rec:
                continue
            a, b = norm_title(rec.get('title')), norm_title(w.get('title'))
            if a and b and not same_work(a, b):
                fail('DOI points at the right paper',
                     f'{rec["id"]}: {d} is "{(w.get("title") or "")[:58]}"')
    for d in dois:
        if d in seen:
            continue
        # Not in OpenAlex is not the same as not a DOI -- a fresh arXiv preprint
        # can be registered and unindexed. Only a dead registration is a failure.
        if doi_registered(d):
            note(f'{want[d]["id"]}: {d} resolves but is not indexed by OpenAlex; title unverified')
        else:
            fail('DOI resolves', f'{want[d]["id"]}: {d} is not a registered DOI')


def pooled_targets(cite, gh, index):
    """The uncurated pools carry pointers too, and nothing has ever checked them.
    Anything already curated is excluded so each artifact is probed once."""
    cur = {norm_url(r['url']) for r in index if r.get('url')}
    out = []
    for w in (cite or []):
        loc = w.get('primary_location') or {}
        u = loc.get('landing_page_url') or w.get('doi') or w.get('id')
        if u and norm_url(u) not in cur:
            out.append({'id': w.get('id'), 'url': u, 'pool': 'citation'})
    for r in ((gh or {}).get('repos') or []):
        u = 'https://github.com/' + r['repo']
        if norm_url(u) not in cur:
            out.append({'id': r['repo'], 'url': u, 'pool': 'repo'})
    return out


def check_links(index, limit=None, extra=(), workers=12):
    """Liveness for every pointer. 404 means dead; it says nothing about whether
    a 200 is the right page -- that is what the DOI title check is for.

    Redirects are followed and reported apart from failures: a repository that
    was renamed answers 200 at a new path, which is not broken but is a stale
    pointer worth knowing about."""
    targets = [r for r in index if r.get('url') and not norm_doi(r['url']).startswith('10.')]
    targets += [r for r in extra if not norm_doi(r['url']).startswith('10.')]
    if limit:
        targets = targets[:limit]
    note(f'checking {len(targets)} links ({sum(1 for t in targets if t.get("pool"))} of them pooled)')

    def probe(r):
        req = urllib.request.Request(r['url'], method='HEAD',
                                     headers={'User-Agent': 'SDVworld-index-validator'})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                if resp.status >= 400:
                    return ('dead', f'{r["id"]}: HTTP {resp.status} {r["url"]}')
                if norm_url(resp.url) != norm_url(r['url']):
                    return ('moved', f'{r["id"]} -> {resp.url}')
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 429):
                return None  # host dislikes HEAD or bots; not evidence of a dead link
            return ('dead', f'{r["id"]}: HTTP {e.code} {r["url"]}')
        except Exception as e:
            return ('dead', f'{r["id"]}: {type(e).__name__} {r["url"]}')
        return None

    moved = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(probe, targets):
            if not res:
                continue
            kind, detail = res
            if kind == 'dead':
                fail('link is live', detail)
            else:
                moved.append(detail)
    if moved:
        note(f'{len(moved)} pointers redirect elsewhere (renamed or reorganised, not dead):')
        for m in moved[:20]:
            note('    ' + m)
        if len(moved) > 20:
            note(f'    ... and {len(moved) - 20} more')


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--online', action='store_true', help='also run the network checks')
    ap.add_argument('--doi-only', action='store_true', help='of the network checks, DOIs only')
    ap.add_argument('--links-only', action='store_true', help='of the network checks, links only')
    ap.add_argument('--limit', type=int, help='cap the number of links checked')
    ap.add_argument('--scope', choices=('curated', 'all'), default='curated',
                    help="'all' also probes the uncurated citation and repo pools")
    ap.add_argument('--workers', type=int, default=12, help='concurrent link probes')
    args = ap.parse_args()

    vocab = read_vocabularies()
    records = check_shards_parse()
    check_required_fields(records)
    check_ids(records)
    check_vocabularies(records, vocab)
    check_scales(records)
    check_url_shape(records)

    index = check_built_index(load('data/sdv-index.json')) or []
    cite = load('data/tail/openalex-citations.json')
    gh = load('data/tail/github-repos.json')
    check_url_vs_joined_doi(index)
    check_repo_urls_are_repos(index)
    check_repos_against_pool(index, gh)
    check_pool_dedup(index, cite)

    if args.online:
        if not args.links_only:
            check_dois_resolve(index)
        if not args.doi_only:
            extra = pooled_targets(cite, gh, index) if args.scope == 'all' else ()
            check_links(index, args.limit, extra, args.workers)

    for m in notes:
        print('  ' + m)
    if not failures:
        print('\nOK: every check passed.')
        return 0
    by_check = collections.OrderedDict()
    for check, detail in failures:
        by_check.setdefault(check, []).append(detail)
    print()
    for check, details in by_check.items():
        print(f'FAIL {check} ({len(details)})')
        for d in details[:25]:
            print(f'       {d}')
        if len(details) > 25:
            print(f'       ... and {len(details) - 25} more')
    print(f'\n{len(failures)} failures across {len(by_check)} checks.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
