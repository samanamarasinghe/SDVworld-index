#!/usr/bin/env python3
"""The site projection: data/site/{manifest,core}.json and data/site/detail/*.json.

Design v2 §5. Generated from the same assembled record list as the legacy export, by
one build path -- `build.py assemble_records()` produces the list, `write_legacy`
emits the public export, and this emits the browser's view of it.

The projection is INTENTIONALLY LOSSY (§1 item 2). data/sdv-index.json remains the
unchanged public export; this is a deterministic runtime view of it, not a
reconstruction. Fields the page never reads -- source_channel, evidence_tier,
openalex_id, countries, the raw aligned affiliation lists, and the popularity inputs
now folded into a single score -- do not travel.

Two things that used to happen in the browser happen here instead:

  - the derived affiliation values (organizations, types, regions) and the popularity
    score, which the v1 page recomputed on every one of its thirteen corpus walks per
    interaction;
  - the 44-row uncurated pool residue, which the page currently fetches 3.7 MB of raw
    pool data to discover.
"""
import hashlib
import json
import math
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, 'data', 'site')

SCHEMA_VERSION = 1
# 32 buckets. Enough that no bucket approaches the 75 KB gzip cap (§9) and few enough
# that a reader scrolling a page pulls only one or two.
BUCKETS = 32

# ---------------------------------------------------------------------------
# Ported from assets/js/sdv-index.js. These are the browser's rules for turning a
# raw pool row into an index entry, and they have to agree exactly or the residue
# changes. tests/build_tests.py pins the result against the Stage 0 corpus, which
# recorded what the browser actually produced.
# ---------------------------------------------------------------------------

TYPE2KIND = {
    'article': 'paper', 'conference-paper': 'paper', 'review': 'paper',
    'book-chapter': 'paper', 'preprint': 'preprint', 'dissertation': 'thesis',
    'book': 'paper', 'data-paper': 'dataset_benchmark',
    'dataset': 'dataset_benchmark', 'software-paper': 'paper',
}
HITS2COMPONENT = {
    'st': 'sdv', 'md': 'sdv', 'mt': 'sdv', 'sq': 'sdv', 'ev': 'sdv', 'gc': 'sdv',
    'par': 'sdv', 'hma': 'sdv', 'req': 'sdv',
    'ct': 'ctgan', 'sm': 'sdmetrics', 'rdt': 'rdt', 'gym': 'sdgym',
}

AMERICAS = ('United States|United States of America|USA|US|Canada|Mexico|Brazil|Colombia|'
            'Argentina|Chile|Peru|Ecuador|Uruguay|Paraguay|Bolivia|Venezuela|Costa Rica|'
            'Panama|Guatemala|Honduras|Nicaragua|El Salvador|Cuba|Dominican Republic|Haiti|'
            'Jamaica|Trinidad and Tobago|Barbados|Bahamas|Belize|Guyana|Suriname|'
            'Puerto Rico|Greenland')
EUROPE = ('United Kingdom|UK|Great Britain|England|Scotland|Wales|Northern Ireland|Ireland|'
          'France|Germany|Italy|Spain|Portugal|Netherlands|Belgium|Luxembourg|Switzerland|'
          'Austria|Denmark|Norway|Sweden|Finland|Iceland|Poland|Czech Republic|Czechia|'
          'Slovakia|Hungary|Romania|Bulgaria|Greece|Croatia|Slovenia|Serbia|'
          'Bosnia and Herzegovina|Montenegro|North Macedonia|Albania|Estonia|Latvia|'
          'Lithuania|Belarus|Ukraine|Moldova|Russia|Russian Federation|Malta|Cyprus|Kosovo|'
          'Monaco|Liechtenstein|Andorra|San Marino')
ASIA = ('China|India|South Korea|Korea|Republic of Korea|North Korea|Japan|Taiwan|Hong Kong|'
        'Macau|Singapore|Malaysia|Indonesia|Thailand|Vietnam|Philippines|Cambodia|Laos|'
        'Myanmar|Brunei|Timor-Leste|Bangladesh|Pakistan|Sri Lanka|Nepal|Bhutan|Maldives|'
        'Afghanistan|Iran|Iraq|Israel|Palestine|Jordan|Lebanon|Syria|Saudi Arabia|Yemen|'
        'Oman|United Arab Emirates|UAE|Qatar|Bahrain|Kuwait|Türkiye|Turkey|Georgia|Armenia|'
        'Azerbaijan|Kazakhstan|Uzbekistan|Turkmenistan|Kyrgyzstan|Tajikistan|Mongolia')
OCEANIA = ('Australia|New Zealand|Fiji|Papua New Guinea|Samoa|Tonga|Vanuatu|Solomon Islands|'
           'New Caledonia|French Polynesia|Guam')
AFRICA = ('Egypt|Morocco|Algeria|Tunisia|Libya|Sudan|South Sudan|Ethiopia|Eritrea|Djibouti|'
          'Somalia|Kenya|Uganda|Tanzania|Rwanda|Burundi|Nigeria|Ghana|Senegal|Ivory Coast|'
          'Cote d Ivoire|Mali|Burkina Faso|Niger|Chad|Cameroon|Gabon|Congo|'
          'Democratic Republic of the Congo|DR Congo|Central African Republic|Benin|Togo|'
          'Guinea|Sierra Leone|Liberia|Gambia|Mauritania|Cape Verde|Zambia|Zimbabwe|Malawi|'
          'Mozambique|Angola|Namibia|Botswana|South Africa|Lesotho|Eswatini|Madagascar|'
          'Mauritius|Seychelles')

_REGIONS = []
for _names, _region in ((AMERICAS, 'americas'), (EUROPE, 'europe'), (ASIA, 'asia'),
                        (AFRICA, 'africa_oceania'), (OCEANIA, 'africa_oceania')):
    _REGIONS.append(({n.lower() for n in _names.split('|')}, _region))


def region_of(name):
    """Every region is ENUMERATED; a name none of the lists recognizes gets NO region,
    so a veto can never rest on a country we failed to place."""
    k = re.sub(r'^the\s+', '', str(name or '').lower()).strip()
    if not k or k in ('unknown', 'n/a', 'unspecified'):
        return ''
    for names, region in _REGIONS:
        if k in names:
            return region
    return ''


def dedupe(seq):
    seen, out = set(), []
    for v in seq:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def organizations_of(rec):
    """One stored element can hold several semicolon-separated organizations, and
    co-authors repeat institutions. The filter works on distinct organizations."""
    out = []
    for value in rec.get('affiliations') or []:
        if not value:
            continue
        for part in str(value).split(';'):
            part = part.strip()
            if part:
                out.append(part)
    return dedupe(out)


def affiliation_rows(rec, organizations):
    types = rec.get('affiliation_types') or []
    countries = rec.get('affiliation_countries') or []
    rows = []
    for i, org in enumerate(organizations):
        raw_type = types[i] if i < len(types) else None
        raw_country = countries[i] if i < len(countries) else None
        rows.append({
            'type': 'academic' if raw_type == 'academic'
                    else ('non_academic' if raw_type and raw_type != 'unknown' else ''),
            'region': region_of(raw_country),
        })
    return rows


def aff_types(rows):
    """An entry with no affiliation on record is its own value; an organization whose
    type is unrecorded still reads non-academic."""
    if not rows:
        return ['unaffiliated']
    acad = any(r['type'] == 'academic' for r in rows)
    other = any(r['type'] != 'academic' for r in rows)
    if not acad:
        return ['non_academic']
    return ['academic', 'non_academic'] if other else ['academic']


def aff_regions(rows):
    return dedupe([r['region'] for r in rows if r['region']])


def popularity_of(rec):
    """Attention only, on one 0-1 scale. Both sides log-compressed; commits clamped
    before blending; an entry carrying both signals takes the higher; an entry with
    neither sits at 0.3, a neutral default rather than a zero."""
    best = None
    if rec.get('kind') == 'code_repo' or rec.get('stars') is not None:
        w = ((rec.get('stars') or 0) + 2 * (rec.get('forks') or 0)
             + 5 * (rec.get('contributors') or 0)
             + 0.1 * min(rec.get('commits') or 0, 2000))
        best = min(1.0, math.log1p(w) / math.log1p(8000))
    if rec.get('cited') is not None:
        c = min(1.0, math.log1p(rec['cited']) / math.log1p(1500))
        if best is None or c > best:
            best = c
    return 0.3 if best is None else best


# ---- the pool residue -----------------------------------------------------

def url_key(u):
    return re.sub(r'/+$', '', re.sub(r'^https?://', '', str(u or '').lower()))


def curated_url_set(curated):
    """Index every pointer a curated entry carries, not just the one it displays. A
    curator who replaces an OpenAlex pointer with the real source -- the right thing
    to do -- would otherwise unsuppress the pool row that entry was meant to retire."""
    keys = set()
    for r in curated:
        for u in (r.get('url'), r.get('openalex_id')):
            if u:
                keys.add(url_key(u))
    return keys


def not_curated(keys, row):
    for k in row.get('alt_urls') or [row.get('url')]:
        if k and url_key(k) in keys:
            return False
    return True


def dedupe_tail(raw):
    """The stored citation tail has carried the same work twice."""
    seen, out = set(), []
    for row in raw:
        key = row.get('id') or row.get('doi') or (row.get('title') or '')
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(row)
    return out


def normalize_cite(r):
    loc = r.get('primary_location') or {}
    authors = [a.get('author', {}).get('display_name')
               for a in (r.get('authorships') or [])]
    return {
        'id': r.get('id'), 'title': r.get('title') or 'Untitled',
        'year': r.get('publication_year') or None,
        'kind': TYPE2KIND.get(r.get('type'), 'paper'),
        'url': loc.get('landing_page_url') or r.get('doi') or r.get('id'),
        'doi': r.get('doi') or '',
        'alt_urls': [u for u in (loc.get('landing_page_url'), r.get('doi'), r.get('id')) if u],
        'authors': [a for a in authors if a],
        'sdv_component': [], 'sdv_concept': [], 'use_case': [], 'industry': [],
        'cited': r.get('cited_by_count') or 0, 'confidence': None, 'tier': 'tail',
    }


def normalize_gh(r):
    created = str(r.get('created') or '')[:4]
    try:
        year = int(created) or None
    except ValueError:
        year = None
    seen, components = set(), []
    for h in str(r.get('hit_patterns') or '').split('|'):
        c = HITS2COMPONENT.get(h)
        if c and c not in seen:
            seen.add(c)
            components.append(c)
    authors = [a for a in [r.get('owner')] + list(r.get('top_contributors') or []) if a]
    return {
        'id': 'gh-' + r['repo'], 'title': r['repo'],
        'url': 'https://github.com/' + r['repo'], 'kind': 'code_repo',
        'sdv_component': components, 'sdv_concept': [], 'use_case': [], 'industry': [],
        'authors': authors, 'summary': r.get('description') or '', 'year': year,
        'stars': r.get('stars') or 0, 'forks': r.get('forks') or 0,
        'contributors': r.get('contributors') or 0, 'commits': r.get('commits') or 0,
        'confidence': None, 'tier': 'tail',
    }


def load(path):
    full = os.path.join(ROOT, path)
    return json.load(open(full)) if os.path.exists(full) else None


def residue_from(curated, cite_raw, gh_raw):
    """The uncurated pool survivors, computed here instead of in the browser.

    §3 item 7: they remain visible only at importance 0 and keep `tier: tail`
    presentation. Order matters -- citation rows then repository rows, appended after
    the curated records -- because the Stage 0 corpus recorded that order and the
    differential compares ordered ids.

    Takes the raw pools as arguments so the synthetic fixture runs through exactly
    this code rather than through a lookalike.
    """
    keys = curated_url_set(curated)
    cite = [r for r in (normalize_cite(x) for x in dedupe_tail(cite_raw or []))
            if not_curated(keys, r)]
    gh_rows = gh_raw.get('repos', []) if isinstance(gh_raw, dict) else (gh_raw or [])
    gh = [r for r in (normalize_gh(x) for x in gh_rows) if not_curated(keys, r)]
    return cite, gh


def pool_residue(curated):
    return residue_from(curated,
                        load('data/tail/openalex-citations.json') or [],
                        load('data/tail/github-repos.json') or [])


# ---- search text -----------------------------------------------------------

# Normalization has to be IDENTICAL here and in v2/assets/js/search.js, or a query
# tokenizes differently from the text it is searching and the postings silently miss.
# tests/build_tests.py checks a shared table of cases against both.
#
# Combining marks are stripped after NFKD rather than kept, so "Muller" finds
# "Müller" and "naive" finds "naïve". Keeping them would also split those words in
# two, since a combining mark is neither a letter nor a number.

def fold(text):
    decomposed = unicodedata.normalize('NFKD', str(text or ''))
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()


def tokenize(text):
    return [w for w in re.split(r'[\W_]+', fold(text), flags=re.UNICODE) if w]


def build_postings(records):
    """Vocabulary and postings over title + summary (§4).

    Postings are delta-encoded: a record list is ascending, so storing the gaps
    instead of the values roughly halves it before compression and more than halves
    it after. Measured on the real corpus: 343 KB gzip, against 812 KB for the
    precomputed search string it replaces.
    """
    by_token = {}
    for i, rec in enumerate(records):
        text = (rec.get('title') or '') + ' ' + (rec.get('summary') or '')
        for token in set(tokenize(text)):
            by_token.setdefault(token, []).append(i)
    vocab = sorted(by_token)
    postings = []
    for token in vocab:
        ids = sorted(by_token[token])
        postings.append([ids[0]] + [ids[k] - ids[k - 1] for k in range(1, len(ids))])
    return {'schema_version': SCHEMA_VERSION, 'vocab': vocab, 'postings': postings}


# ---- the projection -------------------------------------------------------

def bucket_of(record_id):
    """Stable, documented, and recorded in core so the runtime never recomputes it:
    the low five bits of the first byte of SHA-256(id), as two hex digits."""
    digest = hashlib.sha256(str(record_id).encode('utf-8')).digest()
    return '%02x' % (digest[0] & (BUCKETS - 1))


def project(rec):
    """One record as the page needs it. Absent and empty values are omitted rather
    than written as null, which is most of why core is smaller than the export."""
    organizations = organizations_of(rec)
    rows = affiliation_rows(rec, organizations)
    summary = rec.get('summary') or ''
    core = {
        'id': rec['id'],
        'title': rec.get('title') or '',
        'kind': rec.get('kind'),
        # NOT rounded. Ordering falls through to popularity as a tie-break, so
        # rounding could collapse two records that differ in the last few bits into a
        # tie and silently send the sort down a different path than v1 takes.
        'pop': popularity_of(rec),
        'b': bucket_of(rec['id']),
    }
    for field in ('url', 'doi', 'venue', 'evidence', 'integration', 'confidence',
                  'tier'):
        if rec.get(field):
            core[field] = rec[field]
    for field in ('year', 'stars', 'cited', 'importance'):
        if rec.get(field) is not None:
            core[field] = rec[field]
    for field in ('authors', 'sdv_component', 'sdv_concept', 'use_case', 'industry'):
        if rec.get(field):
            core[field] = rec[field]
    if organizations:
        core['organizations'] = organizations
    core['aff_type'] = aff_types(rows)
    regions = aff_regions(rows)
    if regions:
        core['aff_region'] = regions
    # The card draws a Summary toggle, and an open-questions line, only when there is
    # one -- and has to know that without fetching the bucket.
    if summary:
        core['hs'] = 1
    if rec.get('needs'):
        core['hn'] = 1
    return core


def write_site(assembled):
    cite, gh = pool_residue(assembled)
    records = list(assembled) + cite + gh

    core = [project(r) for r in records]
    buckets = {'%02x' % i: {} for i in range(BUCKETS)}
    for rec in records:
        detail = {}
        if rec.get('summary'):
            detail['summary'] = rec['summary']
        if rec.get('needs'):
            detail['needs'] = rec['needs']
        if detail:
            buckets[bucket_of(rec['id'])][rec['id']] = detail

    os.makedirs(os.path.join(SITE, 'detail'), exist_ok=True)

    def dump(path, obj):
        full = os.path.join(SITE, path)
        with open(full, 'w') as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(',', ':'),
                      sort_keys=False)
            fh.write('\n')
        return os.path.getsize(full)

    files = {}
    files['core.json'] = dump('core.json', {'schema_version': SCHEMA_VERSION,
                                            'records': core})
    postings = build_postings(records)
    files['summary-postings.json'] = dump('summary-postings.json', postings)
    for name, content in sorted(buckets.items()):
        files[f'detail/{name}.json'] = dump(f'detail/{name}.json', content)

    # data_hash, not the date or the version, is the cache identity (§5). It is taken
    # over the projected content so that a rebuild which changes nothing the page can
    # see produces the same hash.
    h = hashlib.sha256()
    h.update(json.dumps(core, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':')).encode('utf-8'))
    h.update(json.dumps(postings, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':')).encode('utf-8'))
    for name in sorted(buckets):
        h.update(json.dumps(buckets[name], ensure_ascii=False, sort_keys=True,
                            separators=(',', ':')).encode('utf-8'))

    version_path = os.path.join(ROOT, 'VERSION')
    manifest = {
        'schema_version': SCHEMA_VERSION,
        'version': (open(version_path).read().strip()
                    if os.path.exists(version_path) else None),
        'data_hash': h.hexdigest(),
        'counts': {'curated': len(assembled), 'tail': len(cite) + len(gh),
                   'total': len(records),
                   'citation_pool': len(cite), 'repo_pool': len(gh)},
        'detail_buckets': BUCKETS,
        'files': {name: {'bytes': size} for name, size in sorted(files.items())},
    }
    with open(os.path.join(SITE, 'manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    return {'records': len(records), 'curated': len(assembled),
            'tail': len(cite) + len(gh), 'buckets': BUCKETS,
            'core_bytes': files['core.json'],
            'vocab': len(postings['vocab']),
            'postings_bytes': files['summary-postings.json'],
            'data_hash': manifest['data_hash']}


if __name__ == '__main__':
    import build
    assembled, _ = build.assemble_records()
    print(write_site(assembled))
