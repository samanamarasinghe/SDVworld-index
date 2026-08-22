/* UI parity: drive the two SHIPPED pages through the same clicks and compare what
 * they put on screen.
 *
 * This is a different test from the golden differential, and it exists because the
 * differential cannot see most of what could be wrong. That one drives the filter
 * engine directly -- it never dispatches an event, never reads a checkbox, never
 * looks at the facet panel. So it would pass with flying colours on a v2 whose
 * checkboxes were wired to the wrong facet, whose counts rendered in the wrong
 * order, whose sliders were inverted, or whose cards were drawn out of order.
 *
 * Here both pages are loaded in iframes, unmodified and uninstrumented, and driven
 * through real DOM events. What is compared is what a reader would see:
 *
 *   - the result count in the header
 *   - the titles of the rendered cards, in order
 *   - every facet list: label text, count, order, and truncation
 *   - the facet header counts, the year grid, the affiliation buttons
 *   - group headings and their totals
 *
 * Two differences are expected by design and are normalized rather than reported:
 * v2 renders at most 100 unique records where v1 renders all of them, so v2's cards
 * are compared against the corresponding PREFIX of v1's; and v2's group headings read
 * "(11 of 2171)" where v1's read "(2171)", so only the total is compared.
 *
 *   ?n=100        how many random states (default 100)
 *   ?seed=1       PRNG seed -- the run is reproducible, "random" only in coverage
 */

const params = new URLSearchParams(location.search);
const N = parseInt(params.get('n') || '100', 10);
const SEED = parseInt(params.get('seed') || '20260821', 10);

const statusEl = document.getElementById('status');
const outEl = document.getElementById('out');
const say = (m) => { statusEl.textContent = m; };
const line = (m) => { outEl.textContent += m + '\n'; };

window.__PARITY__ = { done: false, error: null, i: 0, n: N, failed: 0 };

/* mulberry32: small, fast, and seeded, so "100 random states" is a fixed set of 100
 * states that can be re-run and argued about rather than a lottery. */
function rng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* The clock for every wait in this file.
 *
 * A driven run sits in a background tab, and none of the obvious clocks survive
 * that. requestAnimationFrame stops entirely, so a wait that picks it is stranded
 * until the reader comes back. setTimeout is clamped to a second, and after five
 * minutes hidden to a MINUTE, which turns a 120 ms settle window into a two-minute
 * stall. Racing rAF against a MessageChannel task avoids both, but the channel wins
 * instantly every time, so the wait becomes a spin that saturates the renderer and
 * piles up rAF callbacks that will never fire.
 *
 * A dedicated worker's timer is throttled by none of this -- measured at a steady
 * 25 ms in a hidden tab -- and costs one message per tick instead of a busy loop. */
const TICKER_SRC = 'setInterval(() => postMessage(0), 25);';
const ticker = new Worker(
  URL.createObjectURL(new Blob([TICKER_SRC], { type: 'text/javascript' })));
let waiters = [];
ticker.onmessage = () => {
  window.__TICK__.n++;
  const q = waiters; waiters = [];
  window.__TICK__.drained += q.length;
  for (const f of q) f();
};
window.__TICK__ = { n: 0, drained: 0, get waiting() { return waiters.length; } };
ticker.onerror = (e) => { window.__TICK__.error = String(e.message || e); };
const tick = () => new Promise(r => waiters.push(r));
async function waitMs(ms) {
  const t0 = performance.now();
  while (performance.now() - t0 < ms) await tick();
}

/* ---- reading a page ------------------------------------------------------ */

const FACET_MOUNTS = ['facet-kind', 'facet-component', 'facet-concept', 'facet-usecase',
  'facet-integration', 'facet-industry', 'facet-authors', 'facet-affiliations'];

const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
const attr = (el, name) => (el ? (el.getAttribute(name) || '') : null);

/* The trailing count from a group heading. v1 writes "(2171)", v2 writes
   "(11 of 2171)" because it also reports how many are on the page. The total is the
   number both must agree on. */
function headingTotal(s) {
  const m = String(s).match(/\((?:\d+ of )?([\d,]+)\)\s*$/);
  return m ? Number(m[1].replace(/,/g, '')) : null;
}
function headingName(s) {
  return String(s).replace(/\s*\((?:\d+ of )?[\d,]+\)\s*$/, '').trim();
}

/* Everything a reader can see on one card.
 *
 * Titles alone would miss a dropped venue, a wrong star count, a missing DOI link, a
 * chip rendered under the wrong facet, or a badge that lost its class. Two things are
 * deliberately NOT read, each because v2 is supposed to differ:
 *
 *   .pub-summary  v1 builds the body eagerly, v2 fetches it on demand. The TOGGLE is
 *                 compared; the body is covered by the semantic suite.
 *   .pub-needs    same reason, and covered by its own check.
 */
function readCard(li) {
  const actions = [...li.querySelectorAll('.pub-action')].map(a => {
    const label = txt(a);
    /* v1 mints a Blob URL per card during render -- the leak this project removes --
       so its BibTeX href is blob:… and v2's is '#'. The label is the contract; the
       href for that one action is not. */
    const href = label === 'BibTeX' ? '' : attr(a, 'href');
    return `${label}|${href}`;
  });
  return {
    cls: li.className,
    title: txt(li.querySelector('.pub-title')),
    titleHref: attr(li.querySelector('.pub-title a'), 'href'),
    meta: txt(li.querySelector('.pub-meta')),
    badges: [...li.querySelectorAll('.badge')].map(b => `${b.className}|${txt(b)}`),
    conf: txt(li.querySelector('.conf')),
    authors: txt(li.querySelector('.pub-authors')),
    evidence: txt(li.querySelector('.pub-evidence')),
    chips: [...li.querySelectorAll('.chip')].map(c => `${c.className}|${txt(c)}`),
    actions,
  };
}

/* A facet item as one string: class (which carries `disabled`), the label and its
   count, and whether the box is ticked. Comparing the checked state matters -- a
   facet that filters correctly but renders its own selection unticked is a bug the
   engine differential cannot see. */
function readFacetItems(doc, id) {
  const mount = doc.getElementById(id);
  if (!mount) return [];
  return [...mount.querySelectorAll('.facet-item')].map(item => {
    const box = item.querySelector('input[type=checkbox]');
    return `${item.className}|${txt(item)}|${box && box.checked ? 'on' : 'off'}`;
  });
}

function readPage(doc) {
  const results = doc.getElementById('pubs-results');
  const groups = [...results.querySelectorAll('.pub-group')].map(sec => ({
    name: headingName(txt(sec.querySelector('h3'))),
    total: headingTotal(txt(sec.querySelector('h3'))),
    cards: [...sec.querySelectorAll('li.pub-item')].map(readCard),
  }));
  const val = (id) => { const e = doc.getElementById(id); return e ? e.value : null; };
  return {
    count: txt(doc.getElementById('pubs-count')),
    /* The controls themselves, not just their effect: a slider whose label lies, or
       a select that does not reflect the state, is visible to a reader. */
    controls: {
      search: val('facet-title'),
      importance: val('min-importance'),
      importanceLabel: txt(doc.getElementById('min-importance-label')),
      popularity: val('min-popularity'),
      popularityLabel: txt(doc.getElementById('min-popularity-label')),
      group: val('sort-group'),
      sort: val('sort-within'),
      resultsClass: results.className,
    },
    grouped: groups.length > 0,
    groups,
    cards: groups.length ? null
      : [...results.querySelectorAll('li.pub-item')].map(readCard),
    facets: Object.fromEntries(FACET_MOUNTS.map(id => [id, readFacetItems(doc, id)])),
    facetHeaders: [...doc.querySelectorAll('.facet-count')].map(txt),
    years: [...doc.querySelectorAll('#facet-years .year-btn')].map(b => ({
      label: txt(b), on: b.classList.contains('active'),
    })),
    affButtons: [...doc.querySelectorAll('.aff-btn')].map(b => ({
      label: txt(b), on: b.classList.contains('active'),
    })),
    empty: !!results.querySelector('.empty'),
  };
}

/* ---- comparing two pages ------------------------------------------------- */

const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/* The first field on which two cards disagree, or null. */
function cardDiff(a, b) {
  for (const key of ['cls', 'title', 'titleHref', 'meta', 'conf', 'authors',
                     'evidence']) {
    if (a[key] !== b[key]) return `${key}: v1 ${JSON.stringify(a[key])}, v2 ${JSON.stringify(b[key])}`;
  }
  for (const key of ['badges', 'chips', 'actions']) {
    if (!eq(a[key], b[key])) {
      const x = a[key], y = b[key];
      if (x.length !== y.length) {
        return `${key}: v1 has ${x.length} (${x.join(' / ')}), v2 has ${y.length} (${y.join(' / ')})`;
      }
      const at = x.findIndex((v, i) => v !== y[i]);
      return `${key}[${at}]: v1 ${JSON.stringify(x[at])}, v2 ${JSON.stringify(y[at])}`;
    }
  }
  return null;
}

/* v2 renders at most 100 unique records; v1 renders all of them. v2's cards must be
   exactly v1's first N, in order and in every detail -- stronger than comparing sets,
   because it also proves the sort agrees. */
function compareCards(want, got, where) {
  if (got.length > 100) return `${where}v2 rendered ${got.length} cards, above its own cap of 100`;
  for (let i = 0; i < got.length; i++) {
    if (i >= want.length) return `${where}v2 rendered card ${i + 1}, v1 rendered only ${want.length}`;
    const d = cardDiff(want[i], got[i]);
    if (d) return `${where}card ${i + 1} ("${got[i].title}") ${d}`;
  }
  return null;
}

/* Returns the first difference, or null. One difference, not a list: a state that
 * differs usually differs in many correlated ways, and the first one is the one
 * worth reading. */
function compare(a, b) {
  if (a.count !== b.count) return `result count: v1 ${a.count}, v2 ${b.count}`;
  if (a.empty !== b.empty) return `empty state: v1 ${a.empty}, v2 ${b.empty}`;
  if (a.grouped !== b.grouped) return `grouped: v1 ${a.grouped}, v2 ${b.grouped}`;

  for (const key of Object.keys(a.controls)) {
    if (a.controls[key] !== b.controls[key]) {
      return `control ${key}: v1 ${JSON.stringify(a.controls[key])}, ` +
             `v2 ${JSON.stringify(b.controls[key])}`;
    }
  }

  if (!a.grouped) {
    const d = compareCards(a.cards, b.cards, '');
    if (d) return d;
    if (a.cards.length < b.cards.length) {
      return `v1 rendered ${a.cards.length} cards, v2 ${b.cards.length}`;
    }
  } else {
    const an = a.groups.map(g => g.name), bn = b.groups.map(g => g.name);
    /* A group entirely off v2's page is omitted rather than drawn empty, so v2's
       headings must be a subsequence of v1's in the same relative order. */
    let i = 0;
    for (const name of bn) {
      const at = an.indexOf(name, i);
      if (at < 0) return `group "${name}" is in v2 but not v1 (or out of order)`;
      i = at + 1;
    }
    for (const g2 of b.groups) {
      const g1 = a.groups.find(g => g.name === g2.name);
      if (g1.total !== g2.total) {
        return `group "${g2.name}" total: v1 ${g1.total}, v2 ${g2.total}`;
      }
      const d = compareCards(g1.cards, g2.cards, `group "${g2.name}" `);
      if (d) return d;
    }
    const shown = new Set(bn);
    const missing = a.groups.filter(g => !shown.has(g.name));
    const rendered = b.groups.reduce((n, g) => n + g.cards.length, 0);
    if (missing.length && rendered < 100) {
      return `v2 omitted group(s) ${missing.slice(0, 3).map(g => g.name).join(', ')} ` +
             `while rendering only ${rendered} cards -- the page was not full`;
    }
  }

  for (const id of FACET_MOUNTS) {
    if (!eq(a.facets[id], b.facets[id])) {
      const x = a.facets[id], y = b.facets[id];
      if (x.length !== y.length) return `${id}: v1 lists ${x.length} values, v2 ${y.length}`;
      const at = x.findIndex((v, i) => v !== y[i]);
      return `${id} item ${at + 1}: v1 ${JSON.stringify(x[at])}, v2 ${JSON.stringify(y[at])}`;
    }
  }
  if (!eq(a.facetHeaders, b.facetHeaders)) {
    const at = a.facetHeaders.findIndex((v, i) => v !== b.facetHeaders[i]);
    return `facet header ${at + 1}: v1 "${a.facetHeaders[at]}", v2 "${b.facetHeaders[at]}"`;
  }
  if (!eq(a.years, b.years)) {
    const at = a.years.findIndex((v, i) => !eq(v, b.years[i]));
    return `year button ${at + 1}: v1 ${JSON.stringify(a.years[at])}, v2 ${JSON.stringify(b.years[at])}`;
  }
  if (!eq(a.affButtons, b.affButtons)) {
    const at = a.affButtons.findIndex((v, i) => !eq(v, b.affButtons[i]));
    return `affiliation button ${at + 1}: v1 ${JSON.stringify(a.affButtons[at])}, ` +
           `v2 ${JSON.stringify(b.affButtons[at])}`;
  }
  return null;
}

/* ---- driving a page ------------------------------------------------------ */

function settler(doc) {
  const el = doc.getElementById('pubs-results');
  let last = 0;
  new MutationObserver(() => { last = performance.now(); })
    .observe(el, { childList: true, subtree: true, characterData: true });
  return async function settle(quietMs = 120, firstMs = 4000, timeoutMs = 30000) {
    const t0 = performance.now();
    last = 0;
    for (;;) {
      await tick();
      const now = performance.now();
      if (now - t0 > timeoutMs) return false;
      if (last && now - last > quietMs) return true;
      if (!last && now - t0 > firstMs) return true;   // a genuine no-op
    }
  };
}

const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));

/* Every control the run might touch, resolved ONCE from the pristine page.
 *
 * Resolving them per state does not work, and the reason is a real difference
 * between the two pages rather than an accident: v1 rebuilds its facet panel
 * synchronously inside every handler, while v2 coalesces the rebuild to a tick. So
 * immediately after "Clear filters", v1's panel already lists all 2,641
 * organizations and v2's still shows the previous state's filtered list -- and a
 * harness that looks up a checkbox right then finds it in one page and not the
 * other. That is the harness racing v2's coalescing, not a parity failure, and it
 * accounted for every failure in the first attempt at this run.
 *
 * Holding the nodes works even though each render replaces them. A detached
 * checkbox keeps its listener, and that listener closed over its own facet and
 * value, so setting `.checked` and firing `change` still records exactly the right
 * selection. The same is true of the year and affiliation buttons. */
function resolveControls(doc) {
  const map = { facets: {}, years: {}, aff: {} };
  for (const id of FACET_MOUNTS) {
    map.facets[id] = {};
    for (const box of doc.querySelectorAll(`#${id} input[type=checkbox]`)) {
      map.facets[id][box.value] = box;
    }
  }
  for (const btn of doc.querySelectorAll('#facet-years .year-btn')) {
    map.years[txt(btn).replace(/\s+\d+$/, '').trim()] = btn;
  }
  for (const btn of doc.querySelectorAll('.aff-btn')) {
    map.aff[txt(btn).replace(/\s*\d+$/, '').trim()] = btn;
  }
  map.doc = doc;
  map.clear = doc.getElementById('btn-clear');
  map.title = doc.getElementById('facet-title');
  map.imp = doc.getElementById('min-importance');
  map.pop = doc.getElementById('min-popularity');
  map.group = doc.getElementById('sort-group');
  map.sort = doc.getElementById('sort-within');
  return map;
}

/* Apply a state through the controls a reader would use. Everything is expressed
 * relative to the state immediately after "Clear filters": no facet ticked, every
 * year off, every affiliation button lit. That is what lets a held node be pressed
 * without first reading its current appearance. */
const LATE = [];

function apply(map, st) {
  const missing = [];
  map.clear.click();

  for (const [facet, values] of Object.entries(st.facets)) {
    for (const v of values) {
      /* Prefer the node held from the pristine page, but fall back to the live DOM:
         the panel is rebuilt on every render and a value can be listed now that was
         not listed then, or the reverse. Report which path was needed, so a genuine
         parity difference is still distinguishable from a stale reference. */
      let box = map.facets[facet][v];
      if (!box) {
        box = map.doc.querySelector(
          `#${facet} input[type=checkbox][value="${CSS.escape(v)}"]`);
        if (box) { LATE.push(`${facet}:${v}`); }
      }
      if (!box) {
        missing.push(`${facet}:${v}(absent, map has ` +
          `${Object.keys(map.facets[facet]).length})`);
        continue;
      }
      box.checked = true;
      fire(box, 'change');
    }
  }
  for (const y of st.years) {
    const btn = map.years[y];
    if (!btn) { missing.push(`year:${y}`); continue; }
    btn.click();               // all years are off after a clear
  }
  for (const label of st.affOff) {
    const btn = map.aff[label];
    if (!btn) { missing.push(`aff:${label}`); continue; }
    btn.click();               // all affiliation buttons are lit after a clear
  }
  if (st.search) { map.title.value = st.search; fire(map.title, 'input'); }
  if (st.minImportance !== 1) {
    map.imp.value = String(st.minImportance); fire(map.imp, 'input');
  }
  if (st.minPopularity) {
    map.pop.value = String(st.minPopularity); fire(map.pop, 'input');
  }
  if (st.group !== 'none') { map.group.value = st.group; fire(map.group, 'change'); }
  if (st.sort !== 'importance') { map.sort.value = st.sort; fire(map.sort, 'change'); }
  return missing;
}

/* ---- the states ---------------------------------------------------------- */

const GROUPS = ['none', 'none', 'kind', 'year', 'sdv_component', 'use_case', 'industry'];
const SORTS = ['importance', 'importance', 'popularity', 'year', 'title'];
/* Weighted so roughly a third of states carry a search. Every search costs the
   clamped debounce on the v2 side, and a search adds less coverage per second than a
   facet combination does. */
const SEARCHES = ['', '', '', '', '', '', '', '', 'health', 'privacy', 'tabular',
  'gan', 'sdv', 'synthetic data', 'time series', 'benchmark', 'medical', 'finance'];
/* As the buttons read once their count badge is stripped. */
const AFF_LABELS = ['Academic affiliation', 'Non-academic affiliation',
  'Affiliation not found', 'Americas', 'Europe', 'Asia', 'Africa / Oceania'];

/* Facet values are read from the CLEARED default view, where every bounded value is
 * present in both pages. */
function vocabulary(doc) {
  const v = {};
  for (const id of FACET_MOUNTS) {
    v[id] = [...(doc.getElementById(id) || document.createElement('div'))
      .querySelectorAll('input[type=checkbox]')].map(b => b.value);
  }
  v.years = [...doc.querySelectorAll('#facet-years .year-btn')]
    .map(b => txt(b).replace(/\s+\d+$/, '').trim());
  return v;
}

function makeState(rand, vocab, i) {
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];
  const some = (arr, max) => {
    const out = new Set();
    const k = 1 + Math.floor(rand() * max);
    for (let j = 0; j < k && arr.length; j++) out.add(pick(arr));
    return [...out];
  };

  const facets = {};
  /* One to three facets at a time, which is what a reader actually does, and enough
     to exercise AND-across with OR-within. */
  const pool = FACET_MOUNTS.filter(id => (vocab[id] || []).length);
  const chosen = some(pool, 3);
  for (const id of chosen) {
    /* Authors and affiliations run to thousands of values and are capped at 200 in
       the panel; take from the visible head so the click always lands. */
    const values = vocab[id].slice(0, id === 'facet-authors' || id === 'facet-affiliations'
      ? 60 : vocab[id].length);
    facets[id] = some(values, id === 'facet-kind' ? 3 : 2);
  }

  return {
    i,
    facets,
    years: rand() < 0.25 ? some(vocab.years, 2) : [],
    affOff: rand() < 0.2 ? [pick(AFF_LABELS)] : [],
    search: pick(SEARCHES),
    minImportance: pick([0, 1, 1, 2, 3, 4, 5, 6]),
    minPopularity: pick([0, 0, 0, 0, 25, 50, 75]),
    group: pick(GROUPS),
    sort: pick(SORTS),
  };
}

const describe = (st) => {
  const bits = [];
  for (const [f, v] of Object.entries(st.facets)) {
    bits.push(`${f.replace('facet-', '')}=[${v.join(',')}]`);
  }
  if (st.years.length) bits.push(`year=[${st.years.join(',')}]`);
  if (st.affOff.length) bits.push(`aff-off=[${st.affOff.join(',')}]`);
  if (st.search) bits.push(`search="${st.search}"`);
  bits.push(`imp>=${st.minImportance}`);
  if (st.minPopularity) bits.push(`pop>=${st.minPopularity}`);
  if (st.group !== 'none') bits.push(`group=${st.group}`);
  if (st.sort !== 'importance') bits.push(`sort=${st.sort}`);
  return bits.join(' ');
};

/* ---- main ---------------------------------------------------------------- */

async function main() {
  say('waiting for both pages to load their index and pools');
  /* Re-read contentDocument on every poll rather than capturing it once. This module
     evaluates while the frames are still on about:blank, and navigating REPLACES the
     document object -- so a captured reference points at a page that will never load
     anything, and the wait spins forever against a document nobody is using. */
  const ready = async (frameId, name) => {
    const f = document.getElementById(frameId);
    for (let i = 0; i < 900; i++) {
      const doc = f.contentDocument;
      const href = f.contentWindow && f.contentWindow.location.href;
      if (doc && href && href !== 'about:blank') {
        const c = doc.getElementById('pubs-count');
        if (c && /\(\d+\)/.test(c.textContent) &&
            doc.querySelectorAll('#facet-years .year-btn').length) return doc;
      }
      await waitMs(200);
    }
    throw new Error(`${name} never finished loading`);
  };
  const d1 = await ready('f1', 'v1');
  const d2 = await ready('f2', 'v2');
  /* Both pools land after the first paint and change the facet vocabulary; give them
     time or the two pages get compared at different stages of loading. */
  await waitMs(4000);

  const s1 = settler(d1), s2 = settler(d2);
  const c1 = resolveControls(d1), c2 = resolveControls(d2);
  const vocab = vocabulary(d1);
  const v2vocab = vocabulary(d2);
  for (const id of FACET_MOUNTS) {
    if (!eq(vocab[id], v2vocab[id])) {
      line(`NOTE: initial vocabulary differs for ${id} ` +
           `(v1 ${vocab[id].length} values, v2 ${v2vocab[id].length})`);
    }
  }
  line(`v1 default ${txt(d1.getElementById('pubs-count'))}, ` +
       `v2 default ${txt(d2.getElementById('pubs-count'))}`);
  line(`seed ${SEED}, ${N} states\n`);

  const rand = rng(SEED);
  const results = [];
  let failed = 0, expectedDiffs = 0;
  const t0 = performance.now();

  for (let i = 1; i <= N; i++) {
    const st = makeState(rand, vocab, i);
    const desc = describe(st);

    const m1 = apply(c1, st);
    const m2 = apply(c2, st);
    await Promise.all([s1(), s2()]);
    /* The title input is debounced in v2; give the clamped timer room to fire. */
    if (st.search) { await waitMs(1600); await Promise.all([s1(200, 900), s2(200, 900)]); }

    let diff = null;
    if (!eq(m1, m2)) {
      diff = `controls present in one page only: v1 missing [${m1}], v2 missing [${m2}]`;
    } else {
      diff = compare(readPage(d1), readPage(d2));
    }

    /* From Stage 2b the two pages search differently on purpose: v1 matches a
       contiguous substring over title and summary, v2 matches tokens with the last
       word as a prefix. So a state carrying a query is EXPECTED to differ, and
       asserting identity on it would just be asserting that the approved change did
       not happen.
       This does not mean search goes unchecked -- it is checked harder, by the
       golden differential's exception list and by docs/perf/search-recall.md, which
       reports what moved for every frozen query rather than merely permitting it. */
    const expected = !!st.search;
    if (expected && diff) {
      expectedDiffs++;
      results.push({ i, state: st, desc, ok: true, expectedDifference: diff });
      diff = null;
    } else {
      results.push({ i, state: st, desc, ok: !diff, diff });
    }
    if (expected && !diff) {
      /* A query that produces NO difference is fine -- most do not, since most
         queries are single words that tokenize to themselves. Nothing to report. */
    }
    if (diff) {
      failed++;
      line(`FAIL  #${i}  ${desc}\n        ${diff}`);
    }
    window.__PARITY__.i = i;
    window.__PARITY__.failed = failed;
    const per = (performance.now() - t0) / i;
    say(`${i}/${N} states, ${failed} failing ` +
        `(${(per / 1000).toFixed(1)} s each, ~${((N - i) * per / 60000).toFixed(1)} min left)`);

    if (i % 10 === 0 || i === N) {
      await fetch('/__sink/tests/parity/last-run.json', {
        method: 'POST',
        body: JSON.stringify({ seed: SEED, n: N, done: i, failed, expectedDiffs,
                               results }, null, 1),
      });
      line(`  … ${i}/${N}, ${failed} failing`);
    }
  }

  line('');
  line(`held-node lookups that needed a live-DOM fallback: ${LATE.length}` +
       (LATE.length ? ` (e.g. ${LATE[0]})` : ''));
  const searchStates = results.filter(r => r.state.search).length;
  line(`${searchStates} state(s) carried a query; ${expectedDiffs} of them differed, ` +
       'as the §4 search change intends (see docs/perf/search-recall.md)');
  line(`${N - failed - expectedDiffs} of ${N} states identical, ` +
       `${expectedDiffs} expected search differences, ${failed} FAILING`);
  window.__PARITY__.done = true;
  say(failed ? `FAIL: ${failed} of ${N} states differ`
             : `PASS: ${N - expectedDiffs} identical, ${expectedDiffs} expected search differences`);
}

main().catch(e => {
  window.__PARITY__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  line(String(e && e.stack || e));
});
