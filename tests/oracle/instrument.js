/* Load the v1 runtime with its closure exposed.
 *
 * The oracle has to characterize the code that actually ships, bugs included, so it
 * must not re-derive v1's semantics in a second implementation -- a re-derivation
 * would agree with itself and prove nothing. Instead the source is fetched verbatim
 * and ONE line is spliced in ahead of the IIFE's closing brace, publishing the
 * closure's own bindings. Every other byte is untouched, and both the original and
 * the patched digests are recorded so the diff is provable after the fact.
 */

export const EXPORT_LINE =
  'window.__V1__={state:state,filteredData:filteredData,sortWithin:sortWithin,' +
  'groupHeadersFor:groupHeadersFor,headerOrder:headerOrder,countValues:countValues,' +
  'computeUniverse:computeUniverse,activeData:activeData,valuesOf:valuesOf,' +
  'popularity:popularity,labelFor:labelFor,allOn:allOn,AFF_GROUPS:AFF_GROUPS,' +
  'FACET_KEYS:FACET_KEYS,UNIVERSE:UNIVERSE,applyFilters:applyFilters,' +
  'renderResults:renderResults,makeBibLink:makeBibLink,' +
  'probe:function(){return{data:DATA.length,cite:CITE&&CITE.length,gh:GH&&GH.length};}};';

/* Exactly what gets added, so the size assertion below can compare against it
 * rather than against a hand-counted constant. */
const INSERT = '\n  ' + EXPORT_LINE + '\n';

async function sha256(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/* Splice ahead of the outer IIFE's close rather than appending, so the export runs
 * inside the closure.
 *
 * `})();` occurs more than once -- the region tables are built by their own inline
 * IIFE -- so position, not uniqueness, identifies the anchor: the outer close is the
 * last non-whitespace text in the file. Anchoring on "ends with" makes the patch fail
 * loudly rather than guess if the file ever grows a trailing statement. */
function splice(src) {
  const anchor = '})();';
  const end = src.replace(/\s+$/, '');
  if (!end.endsWith(anchor)) {
    throw new Error('instrument: source does not end with the outer IIFE close `})();`');
  }
  const at = end.length - anchor.length;
  return src.slice(0, at) + INSERT + src.slice(at);
}

export async function loadInstrumentedV1(srcPath) {
  const src = await (await fetch(srcPath, { cache: 'no-store' })).text();
  const patched = splice(src);
  const provenance = {
    source_path: srcPath,
    source_sha256: await sha256(src),
    patched_sha256: await sha256(patched),
    source_bytes: src.length,
    /* The whole of the difference, so a reader can verify the claim without
       re-running anything. */
    inserted_line: EXPORT_LINE,
    inserted_at: 'immediately before the file\u2019s final `})();`',
    inserted_bytes: patched.length - src.length,
  };
  if (patched.length - src.length !== INSERT.length) {
    throw new Error('instrument: patch changed more than the inserted line');
  }

  await new Promise((resolve, reject) => {
    const el = document.createElement('script');
    el.textContent = patched;
    el.onerror = () => reject(new Error('instrument: patched script failed to parse'));
    document.head.appendChild(el);
    resolve();
  });
  if (!window.__V1__) throw new Error('instrument: __V1__ was not published');
  return provenance;
}

/* Pull the live v1 markup in rather than keeping a copy: a copy drifts, and the
 * oracle would then characterize a page that is not the one being shipped. Scripts
 * inserted through innerHTML never execute, so the uninstrumented runtime cannot
 * start behind our back -- they are stripped anyway to keep that obvious. */
export async function injectV1Markup(pagePath, mountId) {
  const html = await (await fetch(pagePath, { cache: 'no-store' })).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script').forEach(s => s.remove());
  document.getElementById(mountId).innerHTML = doc.body.innerHTML;
}
