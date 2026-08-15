#!/usr/bin/env python3
"""Resolve tier-A Google Scholar scrape items against OpenAlex.

    OPENALEX_API_KEY=... OPENALEX_EMAIL=... \
        python harvest/resolve_scrape.py sdv-scrape-new.json [n-per-lane]

Written for the 2026-08-15 Scholar delta (113 tier-A items, 100 resolved).
Three fixes worth keeping, each recovered papers a naive resolver drops:
  * publisher URLs append view segments to the DOI -- /full (Frontiers),
    .abstract (medRxiv). Stripped in doi_from(). Recovered 4.
  * Scholar truncates titles at a colon while OpenAlex keeps the subtitle,
    so token overlap scores a genuine match as low as 0.62. Handled by the
    truncated-prefix branch in title_match().
  * long or ALL-CAPS titles rank poorly on title.search; retried with
    distinctive keywords via trimmed().

Lanes:
  doi_in_url  -> singleton /works/doi:<doi>        (free)
  arxiv       -> singleton /works/doi:10.48550/arXiv.<id>  (free)
  title_only  -> /works?filter=title.search:<t>    (10 credits each)
"""
import json, os, re, sys, time, urllib.parse, urllib.request

KEY = os.environ.get('OPENALEX_API_KEY') or os.environ['OPENALEX_KEY']
MAIL = os.environ.get('OPENALEX_EMAIL', '')
FIELDS = ('id,doi,title,publication_year,type,cited_by_count,'
          'primary_location,authorships,concepts,abstract_inverted_index')


def norm(t):
    t = re.sub(r'^\s*\[(HTML|PDF|BOOK|CITATION|B)\]\s*', '', t or '', flags=re.I)
    t = re.sub(r'\$\\unicode\s*\{[^}]*\}\s*\$', ' ', t)
    return re.sub(r'[^a-z0-9]+', ' ', t.lower()).strip()


def clean_title(t):
    t = re.sub(r'^\s*\[(HTML|PDF|BOOK|CITATION|B)\]\s*', '', t or '', flags=re.I)
    return re.sub(r'\$\\unicode\s*\{[^}]*\}\s*\$', ' ', t).strip()


def get(url):
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bearer {KEY}',
        'User-Agent': f'sdvworld-index ({MAIL})'})
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f'HTTP {e.code}'
    except Exception as e:
        return None, str(e)


def lane(u):
    u = u or ''
    if re.search(r'arxiv\.org/(abs|pdf)/', u):
        return 'arxiv'
    if re.search(r'10\.\d{4,9}/', u):
        return 'doi_in_url'
    return 'title_only'


def doi_from(u):
    m = re.search(r'(10\.\d{4,9}/[^\s?&#]+)', u)
    if not m:
        return None
    d = m.group(1).rstrip('.').lower()
    # publisher URLs append view segments that are not part of the DOI
    d = re.sub(r'[./](full|abstract|pdf|html|meta|epdf|full-text|abs|long|short)$', '', d)
    return d


def arxiv_from(u):
    m = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})', u)
    return m.group(1) if m else None


def by_doi(doi):
    url = (f'https://api.openalex.org/works/doi:{urllib.parse.quote(doi)}'
           f'?select={FIELDS}&mailto={MAIL}')
    return get(url)


def title_match(cand, target):
    """Exact, truncated-prefix, or high-overlap match. Returns (ok, how)."""
    ct = norm(cand)
    if not ct:
        return False, 0.0
    if ct == target:
        return True, None
    tw, cw = target.split(), ct.split()
    # Scholar truncates at a colon; OpenAlex keeps the subtitle
    if len(tw) >= 6 and ct.startswith(target + ' '):
        return True, f'prefix +{len(cw) - len(tw)}w'
    if len(cw) >= 6 and target.startswith(ct + ' '):
        return True, f'prefix -{len(tw) - len(cw)}w'
    j = len(set(tw) & set(cw)) / len(set(tw) | set(cw))
    if j >= 0.75:
        return True, f'fuzzy {j:.2f}'
    return False, j


def _pick(resp, original):
    data, err = resp
    if err:
        return None, err
    results = data.get('results', [])
    if not results:
        return None, 'no results'
    target = norm(original)
    best, score = None, 0.0
    for r in results:
        ok, how = title_match(r.get('title'), target)
        if ok:
            return r, how
        if isinstance(how, float) and how > score:
            best, score = r, how
    return None, f'best {score:.2f} ({(best or {}).get("title", "")[:50]})'


def by_title(title):
    q = urllib.parse.quote(clean_title(title))
    url = (f'https://api.openalex.org/works?filter=title.search:{q}'
           f'&per-page=25&select={FIELDS}&mailto={MAIL}')
    return _pick(get(url), title)


def by_title_raw(query, original):
    q = urllib.parse.quote(query)
    url = (f'https://api.openalex.org/works?filter=title.search:{q}'
           f'&per-page=25&select={FIELDS}&mailto={MAIL}')
    return _pick(get(url), original)


STOP = set('a an the of for on in to and or with using via by from as at is are '
           'its their this that new novel study approach method towards toward '
           'based use uses used case cases analysis'.split())


def trimmed(title):
    words = [w for w in norm(title).split() if w not in STOP and len(w) > 2]
    return ' '.join(words[:8])


def resolve(rec):
    L = lane(rec['url'])
    if L == 'arxiv':
        aid = arxiv_from(rec['url'])
        if aid:
            w, err = by_doi(f'10.48550/arxiv.{aid}')
            if w:
                return w, L, 'arxiv-doi'
        return None, L, f'arxiv unresolved ({aid})'
    if L == 'doi_in_url':
        d = doi_from(rec['url'])
        w, err = by_doi(d)
        if w:
            return w, L, 'doi'
        return None, L, f'doi unresolved ({d}): {err}'
    w, err = by_title(rec['title'])
    if w:
        return w, L, f'title.search ({err or "exact"})'
    # long or oddly-cased titles rank poorly; retry with distinctive keywords
    tq = trimmed(rec['title'])
    w2, err2 = by_title_raw(tq, rec['title'])
    if w2:
        return w2, L, f'title.search trimmed ({err2 or "exact"})'
    return None, L, f'title unresolved: {err} | trimmed: {err2}'


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('usage: resolve_scrape.py <scrape.json> [n-per-lane] '
                 '   (env: OPENALEX_API_KEY, OPENALEX_EMAIL)')
    src = json.load(open(sys.argv[1]))
    A = [r for r in src if r.get('tier') == 'A']
    if len(sys.argv) > 2:
        n = int(sys.argv[2])
        picks, seen = [], {'doi_in_url': 0, 'arxiv': 0, 'title_only': 0}
        for r in A:
            L = lane(r['url'])
            if seen[L] < n:
                picks.append(r)
                seen[L] += 1
        A = picks
    out = []
    for i, r in enumerate(A, 1):
        w, L, how = resolve(r)
        out.append({'scrape': r, 'work': w, 'lane': L, 'how': how})
        wid = w['id'].rsplit('/', 1)[-1] if w else '-'
        print(f'{i:3d} [{L:10s}] {wid:12s} {how[:50]:52s} {r["title"][:55]}')
        time.sleep(0.15)
    with open('resolved.json', 'w') as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    ok = sum(1 for o in out if o['work'])
    print(f"\nresolved {ok}/{len(out)} -> resolved.json")
