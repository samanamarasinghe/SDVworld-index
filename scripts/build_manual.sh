#!/usr/bin/env bash
# Render docs/manual/manual.html to SDVworld-manual.pdf.
#
# Chrome headless rather than a PDF library: the manual carries hand-authored SVG
# diagrams and a print stylesheet, and a real browser is the only thing here that
# renders both faithfully. No Node, no LaTeX and no Python PDF package is installed on
# the maintainer's machine; Chrome is.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo "Chrome not found at $CHROME" >&2; exit 1; }

"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$PWD/SDVworld-manual.pdf" \
  "file://$PWD/docs/manual/manual.html" 2>/dev/null

[ -s SDVworld-manual.pdf ] || { echo "no PDF produced" >&2; exit 1; }
python3 - <<'PY'
import pathlib, re
b = pathlib.Path('SDVworld-manual.pdf').read_bytes()
pages = len(re.findall(rb'/Type\s*/Page[^s]', b))
print(f'SDVworld-manual.pdf  {len(b):,} bytes, {pages} pages')
PY
