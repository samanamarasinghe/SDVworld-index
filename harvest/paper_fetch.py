#!/usr/bin/env python3
"""Fetch full text for papers, by DOI, trying every route known to work.

    python3 harvest/paper_fetch.py --dois 10.3390/math10152733 10.5220/0012302400003654
    python3 harvest/paper_fetch.py --from-xlsx missing_pdfs.xlsx --limit 50
    python3 harvest/paper_fetch.py --from-xlsx missing_pdfs.xlsx --routes mdpi,scitepress
    python3 harvest/paper_fetch.py --from-tail --doi-prefix 10.48550 --routes arxiv
    python3 harvest/paper_fetch.py --report          # what is already cached

--from-tail builds the worklist from data/tail/openalex-citations.json minus whatever
is already in data/sdv-index.json, highest cited_by first, so --limit takes the works
that matter most. It is the right worklist for the curation lane: the xlsx is an
ACCESS-side view listing what a browser could not get, so open preprints -- 448 arXiv
DOIs, the largest free block in the tail -- never appear in it at all.

Output goes to harvest/papers/, which is GITIGNORED: publisher PDFs must not be
redistributed, and the extracted text is re-derivable. The cache exists so that a
re-read costs nothing and so a paper obtained through an institutional login stays
usable across sessions -- the single biggest gap in this project is that every PDF
read so far was thrown away, which is why 410 entries sit at confidence medium.

Per DOI it writes  <slug>.txt  (extracted text) and  <slug>.json  (which route won,
how many characters came back, and the URL that served it). The PDF itself is kept
only when --keep-pdf is passed.

It also keeps  harvest/fetch-log.json,  one record per DOI ever attempted: the
outcome, the route that served it, the routes tried, the url and the character count.
That file IS committed -- it holds no publisher text, only what happened -- so the
record of a failed attempt survives a fresh clone even though the cache does not. It
is the file to join against missing_pdfs.xlsx when reporting which papers were
obtained and which were not.

ROUTES, in the order tried. Each was established the hard way; see
docs/agent-guide.md for the full account.

  mdpi        mdpi.com 403s every automated request including the PDF path, but the
              CDN at mdpi-res.com does not. The URL is built from the DOI:
              10.3390/<abbrev><vol><iss:2><art:4>. The article number pads to FIVE
              digits in the path. A greedy volume group mis-splits e25010088, so the
              regex must be anchored and fixed-width.
  scitepress  serves PDFs directly at /Papers/<year>/<pid>/<pid>.pdf, where pid is
              characters 2:8 of the DOI suffix. The year must match the conference,
              so nearby years are tried.
  unpaywall   free, unmetered, no key. Its PMC urls are often malformed, missing the
              PMC prefix, and its Wiley locations are advertised but 403.
  pmc         the LEGACY host www.ncbi.nlm.nih.gov/pmc/articles/PMC<id>/ returns full
              text where pmc.ncbi.nlm.nih.gov and the Europe PMC fulltextRepo do not.
              Europe PMC's REST fullTextXML is the reliable one for a PMCID.
  openalex    the tail already carries primary_location.pdf_url for 890 uncurated
              works. It is a direct link that costs no API round trip, so it is tried
              before unpaywall. It is also often a landing page rather than a PDF,
              hence the %PDF check.
  arxiv       TWO CASES, and conflating them cost a whole 448-row run. A 10.48550
              DOI IS an arXiv id -- 10.48550/arxiv.2008.12763 is 2008.12763 -- so the
              PDF url is built directly and no API call happens at all. Only for a
              NON-arXiv DOI is the API searched by title, because a preprint of a
              published paper is a separate record the DOI cannot reach; accept a
              difflib ratio >= 0.80, and when the title has diverged too far try the
              distinctive project name instead. arxiv.org is throttled, so every
              fetch pauses and retries rather than being dropped on the first refusal.

Two rules that cost time when ignored:
  * A 200 is not evidence of a PDF. Springer returns the paywalled HTML page with a
    200. Check that the body starts with %PDF.
  * Never retry into the same output file. A 503 on the second attempt once
    overwrote a good 1.4MB PDF with 114 bytes of error text.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'harvest', 'papers')
TAIL = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
INDEX = os.path.join(ROOT, 'data', 'sdv-index.json')
EMAIL = os.environ.get('UNPAYWALL_EMAIL', 'saman@lcs.mit.edu')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
TIMEOUT = 90

MDPI_SLUG = {'e': 'entropy', 'app': 'applsci', 's': 'sensors', 'math': 'mathematics',
             'su': 'sustainability', 'w': 'water'}


def slug_for(doi):
    return re.sub(r'[^a-z0-9]+', '_', doi.lower()).strip('_')


def get(url, tries=2):
    """Return bytes, or None. Never writes; the caller decides what to keep."""
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            if attempt + 1 < tries:
                time.sleep(3)
    return None


def is_pdf(blob):
    return bool(blob) and blob[:4] == b'%PDF'


# ------------------------------------------------------------------ routes

def route_mdpi(doi, meta):
    match = re.match(r'10\.3390/([a-z]+)(\d+)(\d{2})(\d{4})$', doi)
    if not match:
        return None
    abbrev, volume, _issue, article = match.groups()
    journal = MDPI_SLUG.get(abbrev, abbrev)
    vol, art = int(volume), int(article)
    stem = f'{journal}-{vol:02d}-{art:05d}'
    for suffix in ('', '-v2', '-v3'):
        url = f'https://mdpi-res.com/d_attachment/{journal}/{stem}/article_deploy/{stem}.pdf{suffix}'
        blob = get(url, tries=1)
        if is_pdf(blob):
            return url, blob
    return None


def route_scitepress(doi, meta):
    match = re.match(r'10\.5220/(\d{16})$', doi)
    if not match:
        return None
    pid = match.group(1)[2:8]
    year = meta.get('year')
    years = [year] if year else []
    years += [y for y in range(2019, 2027) if y not in years]
    for candidate in years:
        url = f'https://www.scitepress.org/Papers/{candidate}/{pid}/{pid}.pdf'
        blob = get(url, tries=1)
        if is_pdf(blob):
            return url, blob
    return None


def route_openalex(doi, meta):
    url = meta.get('pdf_url')
    if not url:
        return None
    blob = get(url, tries=1)
    if is_pdf(blob):
        return url, blob
    return None


UNPAYWALL_CACHE = {}


def unpaywall(doi):
    """One answer per DOI per run. route_unpaywall and route_pmc both need it, and
    without the memo a --routes unpaywall,pmc pass asks the same question twice for
    every row."""
    if doi in UNPAYWALL_CACHE:
        return UNPAYWALL_CACHE[doi]
    blob = get(f'https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={EMAIL}')
    data = {}
    if blob:
        try:
            data = json.loads(blob)
        except ValueError:
            data = {}
    UNPAYWALL_CACHE[doi] = data
    return data


def route_unpaywall(doi, meta):
    data = unpaywall(doi)
    locations = [data.get('best_oa_location') or {}] + (data.get('oa_locations') or [])
    for location in locations:
        for url in (location.get('url_for_pdf'), location.get('url')):
            if not url:
                continue
            blob = get(url, tries=1)
            if is_pdf(blob):
                return url, blob
    return None


def route_pmc(doi, meta):
    data = unpaywall(doi)
    text = json.dumps(data)
    ids = set(re.findall(r'PMC(\d+)', text)) | set(re.findall(r'/pmc/articles/(\d{5,})', text))
    for pmcid in ids:
        url = (f'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC{pmcid}/fullTextXML')
        blob = get(url, tries=1)
        if blob and b'<' in blob[:200]:
            try:
                root = ET.fromstring(blob)
            except ET.ParseError:
                continue
            body = ' '.join(node.text or '' for node in root.iter() if node.text)
            if len(body) > 4000:
                return url, ('TEXT', body)
    return None


ARXIV_DOI = re.compile(r'^10\.48550/arxiv\.(.+)$', re.I)
ARXIV_DELAY = 1.0        # arxiv.org refuses a fast burst; 24 rows in, it stops
ARXIV_API_DELAY = 3.0    # export.arxiv.org asks for one request every three seconds


def arxiv_id_by_title(meta):
    title = (meta.get('title') or '').strip()
    if len(title) < 20:
        return None
    query = urllib.parse.quote(f'ti:"{title}"')
    blob = get(f'http://export.arxiv.org/api/query?search_query={query}&max_results=5')
    time.sleep(ARXIV_API_DELAY)   # the throttle that cost a 448-row run, on the API side
    if not blob:
        return None
    try:
        feed = ET.fromstring(blob)
    except ET.ParseError:
        return None
    namespace = '{http://www.w3.org/2005/Atom}'
    best, ratio_best = None, 0.0
    for entry in feed.iter(namespace + 'entry'):
        found = (entry.findtext(namespace + 'title') or '').strip()
        ratio = difflib.SequenceMatcher(None, norm(title), norm(found)).ratio()
        if ratio > ratio_best:
            best, ratio_best = entry, ratio
    # `not best` on an Element tests its CHILD COUNT, which is deprecated and will
    # become always-False. Test against None.
    if best is None or ratio_best < 0.80:
        return None
    return (best.findtext(namespace + 'id') or '').rsplit('/', 1)[-1] or None


def route_arxiv(doi, meta):
    match = ARXIV_DOI.match(doi)
    arxiv_id = match.group(1) if match else arxiv_id_by_title(meta)
    if not arxiv_id:
        return None
    url = f'https://arxiv.org/pdf/{arxiv_id}'
    blob = get(url, tries=3)
    time.sleep(ARXIV_DELAY)
    if is_pdf(blob):
        return url, blob
    return None


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


ROUTES = [('mdpi', route_mdpi), ('scitepress', route_scitepress),
          ('openalex', route_openalex), ('unpaywall', route_unpaywall),
          ('pmc', route_pmc), ('arxiv', route_arxiv)]

# A route that only ever fires on one DOI prefix. Used to skip rows a --routes
# subset cannot possibly serve, so --limit measures work attempted rather than
# rows scrolled past: the worklist is grouped by publisher, so the first several
# hundred rows are all IEEE and a naive --limit does nothing at all.
ROUTE_PREFIX = {'mdpi': '10.3390/', 'scitepress': '10.5220/'}
# arxiv is deliberately NOT in that table. It searches by TITLE, so it serves a row
# with any DOI whose work also has a preprint -- exactly the FEST case. To restrict a
# run to arXiv-DOI rows, filter the worklist with --doi-prefix instead.


# ------------------------------------------------------------------ driver

def extract(blob):
    """PDF bytes to text. pypdf only; a page that will not parse is skipped."""
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(blob))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or '')
        except Exception:
            pages.append('')
    text = '\n'.join(pages)
    # Mathematical PDFs yield lone surrogates -- a maths-italic glyph decoded to
    # half a surrogate pair -- and those cannot be encoded as UTF-8, so the write
    # dies after the fetch has already succeeded. Drop them; nothing downstream
    # reads the mathematics.
    return text.encode('utf-8', 'surrogatepass').decode('utf-8', 'ignore')


def fetch_one(doi, meta, routes, keep_pdf):
    slug = slug_for(doi)
    text_path = os.path.join(OUT, slug + '.txt')
    meta_path = os.path.join(OUT, slug + '.json')
    if os.path.exists(text_path) and os.path.getsize(text_path) > 2000:
        return 'cached', None, {'tried': []}

    tried = []
    for name, route in ROUTES:
        if routes and name not in routes:
            continue
        tried.append(name)
        try:
            result = route(doi, meta)
        except Exception as exc:
            print(f'    {name}: {type(exc).__name__}', file=sys.stderr)
            continue
        if not result:
            continue
        url, payload = result
        if isinstance(payload, tuple) and payload[0] == 'TEXT':
            text, blob = payload[1], None
        else:
            blob = payload
            try:
                text = extract(blob)
            except Exception as exc:
                print(f'    {name}: extract failed, {type(exc).__name__}', file=sys.stderr)
                continue
        if len(text) < 2000:          # a cover page is not a paper
            continue
        os.makedirs(OUT, exist_ok=True)
        # Write to a temp name and move, so a failure never truncates a good file.
        tmp = text_path + '.part'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, text_path)
        if keep_pdf and blob:
            with open(os.path.join(OUT, slug + '.pdf'), 'wb') as fh:
                fh.write(blob)
        with open(meta_path, 'w', encoding='utf-8') as fh:
            json.dump({'doi': doi, 'route': name, 'url': url, 'chars': len(text),
                       'title': meta.get('title'), 'year': meta.get('year')},
                      fh, indent=1, ensure_ascii=False)
        return name, len(text), {'url': url, 'tried': tried}
    return None, None, {'tried': tried}


LOG = os.path.join(ROOT, 'harvest', 'fetch-log.json')
LOG_NOTE = ('One record per DOI ever attempted by paper_fetch.py: outcome, the route '
            'that served it, every route tried, the url and the character count. '
            'Committed deliberately -- it carries no publisher text, and a failed '
            'attempt is worth as much as a successful one. harvest/papers/ is '
            'gitignored, so without this file a fresh clone cannot tell whether a '
            'paper was never tried or tried and refused. Join it on doi to report '
            'coverage against missing_pdfs.xlsx.')


def load_log():
    if not os.path.exists(LOG):
        return {}
    try:
        with open(LOG, encoding='utf-8') as fh:
            return json.load(fh).get('attempts', {})
    except (ValueError, OSError):
        return {}


def save_log(attempts):
    tmp = LOG + '.part'                      # never truncate a good log on a crash
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump({'note': LOG_NOTE, 'attempts': attempts}, fh,
                  indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, LOG)


def log_record(doi, meta, name, size, detail):
    """What happened to one DOI, in the shape the xlsx join wants."""
    if name == 'cached':
        # The sidecar already holds the winning route; re-read it rather than
        # recording a bare 'cached', which would lose how the paper was obtained.
        sidecar = os.path.join(OUT, slug_for(doi) + '.json')
        try:
            with open(sidecar, encoding='utf-8') as fh:
                saved = json.load(fh)
            return {'status': 'ok', 'route': saved.get('route'),
                    'url': saved.get('url'), 'chars': saved.get('chars'),
                    'routes_tried': [saved.get('route')],
                    'title': saved.get('title'), 'year': saved.get('year'),
                    'when': time.strftime('%Y-%m-%d')}
        except (ValueError, OSError):
            return None                      # no sidecar: leave any older record alone
    return {'status': 'ok' if name else 'no_route', 'route': name,
            'url': detail.get('url'), 'chars': size,
            'routes_tried': detail.get('tried') or [],
            'title': meta.get('title'), 'year': meta.get('year'),
            'when': time.strftime('%Y-%m-%d')}


SHEET_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def read_xlsx(path):
    """Rows of the first worksheet as dicts keyed by the header row. Stdlib only.

    An .xlsx is a zip of XML, so pandas and openpyxl are both avoidable, and this
    repository is otherwise pure standard library -- README.txt promises there is
    nothing to install. Text cells are indexes into a shared-strings table rather
    than literals, which is the only part that is not obvious.
    """
    with zipfile.ZipFile(path) as archive:
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            for item in root.findall(SHEET_NS + 'si'):
                shared.append(''.join(t.text or '' for t in item.iter(SHEET_NS + 't')))
        names = [n for n in archive.namelist()
                 if re.match(r'xl/worksheets/sheet1\.xml$', n)]
        if not names:
            raise SystemExit(f'{path}: no first worksheet')
        sheet = ET.fromstring(archive.read(names[0]))

    rows = []
    for row in sheet.iter(SHEET_NS + 'row'):
        cells = {}
        for cell in row.findall(SHEET_NS + 'c'):
            reference = cell.get('r') or ''
            column = re.match(r'([A-Z]+)', reference)
            if not column:
                continue
            value_node, kind = cell.find(SHEET_NS + 'v'), cell.get('t')
            if kind == 'inlineStr':
                value = ''.join(t.text or '' for t in cell.iter(SHEET_NS + 't'))
            elif value_node is None:
                value = ''
            elif kind == 's':
                value = shared[int(value_node.text)]
            else:
                value = value_node.text or ''
            cells[column.group(1)] = value
        rows.append(cells)
    if not rows:
        return []
    header = rows[0]
    return [{header.get(k, k): v for k, v in row.items()} for row in rows[1:]]


def load_xlsx(path, limit, reasons, routes=None):
    rows_in = read_xlsx(path)
    rows = []
    for row in rows_in:
        doi = str(row.get('DOI') or '').strip()
        doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi, flags=re.I)
        if not doi.startswith('10.'):
            continue
        if reasons and not any(r.lower() in str(row.get('Reason') or '').lower()
                               for r in reasons):
            continue
        if routes:
            prefixes = [ROUTE_PREFIX[r] for r in routes if r in ROUTE_PREFIX]
            if len(prefixes) == len(routes) and not any(doi.startswith(p)
                                                        for p in prefixes):
                continue
        year = str(row.get('Year') or '').strip()
        rows.append({'doi': doi, 'title': row.get('Title'),
                     'year': int(float(year)) if re.match(r'^\d', year) else None})
        if limit and len(rows) >= limit:
            break
    return rows


def load_tail(limit, routes=None, prefixes=None, with_pdf_url=False):
    """Uncurated tail works, highest cited_by first."""
    def bare(value):
        value = str(value or '').strip().lower()
        return re.sub(r'^https?://(dx\.)?doi\.org/', '', value)

    indexed = set()
    with open(INDEX, encoding='utf-8') as fh:
        for entry in json.load(fh):
            for key in ('doi', 'url'):
                value = bare(entry.get(key))
                if value.startswith('10.'):
                    indexed.add(value)
    with open(TAIL, encoding='utf-8') as fh:
        tail = json.load(fh)

    seen, works = set(), []
    for work in tail:                      # the tail carries 14 doubled records
        if work.get('id') in seen:
            continue
        seen.add(work['id'])
        works.append(work)
    works.sort(key=lambda w: -(w.get('cited_by_count') or 0))

    rows = []
    for work in works:
        doi = bare(work.get('doi'))
        if not doi.startswith('10.') or doi in indexed:
            continue
        if prefixes and not any(doi.startswith(p) for p in prefixes):
            continue
        if with_pdf_url and not (work.get('primary_location') or {}).get('pdf_url'):
            continue
        if routes:
            gated = [ROUTE_PREFIX[r] for r in routes if r in ROUTE_PREFIX]
            if len(gated) == len(routes) and not any(doi.startswith(p) for p in gated):
                continue
        rows.append({'doi': doi, 'title': work.get('title'),
                     'year': work.get('publication_year'),
                     'pdf_url': (work.get('primary_location') or {}).get('pdf_url')})
        if limit and len(rows) >= limit:
            break
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dois', nargs='*', default=[])
    parser.add_argument('--from-xlsx')
    parser.add_argument('--from-tail', action='store_true',
                        help='worklist from the uncurated citation tail')
    parser.add_argument('--with-pdf-url', action='store_true',
                        help='only rows OpenAlex gives a pdf_url for (the openalex route)')
    parser.add_argument('--doi-prefix', action='append',
                        help='only DOIs starting with this, e.g. 10.48550; repeatable')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--routes', help='comma-separated subset, e.g. mdpi,scitepress')
    parser.add_argument('--reason', action='append',
                        help='only rows whose Reason contains this; repeatable')
    parser.add_argument('--keep-pdf', action='store_true')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()

    if args.report:
        metas = [json.load(open(os.path.join(OUT, f)))
                 for f in sorted(os.listdir(OUT)) if f.endswith('.json')] \
                if os.path.isdir(OUT) else []
        print(f'{len(metas)} papers cached in {OUT}')
        by_route = {}
        for m in metas:
            by_route[m['route']] = by_route.get(m['route'], 0) + 1
        for name, count in sorted(by_route.items(), key=lambda kv: -kv[1]):
            print(f'  {count:5d}  {name}')
        attempts = load_log()
        if attempts:
            ok = sum(1 for a in attempts.values() if a.get('status') == 'ok')
            print(f'{len(attempts)} DOIs attempted, {ok} obtained, '
                  f'{len(attempts) - ok} refused every route -> {LOG}')
        return

    routes = set(args.routes.split(',')) if args.routes else None
    prefixes = args.doi_prefix or None
    if args.from_tail:
        rows = load_tail(args.limit, routes, prefixes, args.with_pdf_url)
    elif args.from_xlsx:
        rows = load_xlsx(args.from_xlsx, args.limit, args.reason, routes)
    else:
        rows = [{'doi': d, 'title': None, 'year': None} for d in args.dois]
    if not rows:
        parser.error('give --dois, --from-xlsx or --from-tail')

    attempts = load_log()
    got = cached = 0
    for i, row in enumerate(rows, 1):
        name, size, detail = fetch_one(row['doi'], row, routes, args.keep_pdf)
        record = log_record(row['doi'], row, name, size, detail)
        if record:
            attempts[row['doi']] = record
        if i % 10 == 0:                      # survive a Ctrl-C mid-run
            save_log(attempts)
        if name == 'cached':
            cached += 1
            status = 'cached'
        elif name:
            got += 1
            status = f'{name} {size} chars'
        else:
            status = 'no route'
        print(f'[{i}/{len(rows)}] {row["doi"]:34s} {status}', flush=True)
    save_log(attempts)
    print(f'\n{got} fetched, {cached} already cached, '
          f'{len(rows) - got - cached} unreachable -> {OUT}')
    print(f'{len(attempts)} DOIs in {LOG}')


if __name__ == '__main__':
    main()
