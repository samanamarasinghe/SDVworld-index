#!/usr/bin/env python3
"""Fetch full text for papers, by DOI, trying every route known to work.

    python3 harvest/paper_fetch.py --dois 10.3390/math10152733 10.5220/0012302400003654
    python3 harvest/paper_fetch.py --from-xlsx missing_pdfs.xlsx --limit 50
    python3 harvest/paper_fetch.py --from-xlsx missing_pdfs.xlsx --routes mdpi,scitepress
    python3 harvest/paper_fetch.py --report          # what is already cached

Output goes to harvest/papers/, which is GITIGNORED: publisher PDFs must not be
redistributed, and the extracted text is re-derivable. The cache exists so that a
re-read costs nothing and so a paper obtained through an institutional login stays
usable across sessions -- the single biggest gap in this project is that every PDF
read so far was thrown away, which is why 410 entries sit at confidence medium.

Per DOI it writes  <slug>.txt  (extracted text) and  <slug>.json  (which route won,
how many characters came back, and the URL that served it). The PDF itself is kept
only when --keep-pdf is passed.

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
  arxiv       a preprint is a SEPARATE record with its own DOI, so a DOI lookup never
              finds it. Search by title, accept a difflib ratio >= 0.80, and when the
              title has diverged too far try the distinctive project name instead.

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


def unpaywall(doi):
    blob = get(f'https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={EMAIL}')
    if not blob:
        return {}
    try:
        return json.loads(blob)
    except ValueError:
        return {}


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


def route_arxiv(doi, meta):
    title = (meta.get('title') or '').strip()
    if len(title) < 20:
        return None
    query = urllib.parse.quote(f'ti:"{title}"')
    blob = get(f'http://export.arxiv.org/api/query?search_query={query}&max_results=5')
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
    if not best or ratio_best < 0.80:
        return None
    identifier = (best.findtext(namespace + 'id') or '')
    arxiv_id = identifier.rsplit('/', 1)[-1]
    url = f'https://arxiv.org/pdf/{arxiv_id}'
    blob = get(url)
    if is_pdf(blob):
        return url, blob
    return None


def norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', (text or '').lower()).strip()


ROUTES = [('mdpi', route_mdpi), ('scitepress', route_scitepress),
          ('unpaywall', route_unpaywall), ('pmc', route_pmc), ('arxiv', route_arxiv)]

# A route that only ever fires on one DOI prefix. Used to skip rows a --routes
# subset cannot possibly serve, so --limit measures work attempted rather than
# rows scrolled past: the worklist is grouped by publisher, so the first several
# hundred rows are all IEEE and a naive --limit does nothing at all.
ROUTE_PREFIX = {'mdpi': '10.3390/', 'scitepress': '10.5220/'}


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
        return 'cached', None

    for name, route in ROUTES:
        if routes and name not in routes:
            continue
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
        return name, len(text)
    return None, None


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


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dois', nargs='*', default=[])
    parser.add_argument('--from-xlsx')
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
        return

    routes = set(args.routes.split(',')) if args.routes else None
    if args.from_xlsx:
        rows = load_xlsx(args.from_xlsx, args.limit, args.reason, routes)
    else:
        rows = [{'doi': d, 'title': None, 'year': None} for d in args.dois]
    if not rows:
        parser.error('give --dois or --from-xlsx')

    got = cached = 0
    for i, row in enumerate(rows, 1):
        name, size = fetch_one(row['doi'], row, routes, args.keep_pdf)
        if name == 'cached':
            cached += 1
            status = 'cached'
        elif name:
            got += 1
            status = f'{name} {size} chars'
        else:
            status = 'no route'
        print(f'[{i}/{len(rows)}] {row["doi"]:34s} {status}', flush=True)
    print(f'\n{got} fetched, {cached} already cached, '
          f'{len(rows) - got - cached} unreachable -> {OUT}')


if __name__ == '__main__':
    main()
