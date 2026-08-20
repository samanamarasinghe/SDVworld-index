#!/usr/bin/env python3
"""One-shot: drop the pandas dependency from harvest/paper_fetch.py.

An .xlsx is a zip of XML, so the worklist can be read with the standard library.
README.txt promises there is nothing to install and the rest of the repository
keeps that promise. Delete this file after running it.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'harvest', 'paper_fetch.py')

READER = '''SHEET_NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


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
                 if re.match(r'xl/worksheets/sheet1\\.xml$', n)]
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
        doi = str(row.get('DOI') or '').strip()'''

EDITS = [
    ("import urllib.request\nimport xml.etree.ElementTree as ET",
     "import urllib.request\nimport xml.etree.ElementTree as ET\nimport zipfile"),
    ("""def load_xlsx(path, limit, reasons, routes=None):
    import pandas as pd
    frame = pd.read_excel(path)
    rows = []
    for _, row in frame.iterrows():
        doi = str(row.get('DOI') or '').strip()""", READER),
    ("""        year = row.get('Year')
        rows.append({'doi': doi, 'title': row.get('Title'),
                     'year': int(year) if year == year and year else None})""",
     """        year = str(row.get('Year') or '').strip()
        rows.append({'doi': doi, 'title': row.get('Title'),
                     'year': int(float(year)) if re.match(r'^\\d', year) else None})"""),
]

source = open(PATH, encoding='utf-8').read()
if 'def read_xlsx(' in source:
    sys.exit('already applied; nothing to do')
for old, new in EDITS:
    if source.count(old) != 1:
        sys.exit('anchor not found exactly once; patch by hand')
    source = source.replace(old, new)
if 'import pandas' in source:
    sys.exit('pandas still referenced; aborting without writing')
open(PATH, 'w', encoding='utf-8').write(source)
print('patched harvest/paper_fetch.py: pandas removed, stdlib xlsx reader added')
