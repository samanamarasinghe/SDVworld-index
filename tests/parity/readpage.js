/* Reading a page, and comparing two of them.
 *
 * Shared by parity.js (randomized states) and stress.js (toggle sequences, systematic
 * sweeps, search, show-all) so that both judge "the same" by exactly one definition.
 * Two harnesses with two notions of equality would eventually disagree, and the
 * weaker one would be the one nobody noticed.
 */
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

/* Compare one page against ITSELF at an earlier moment.
 *
 * compare() above is asymmetric on purpose -- it knows `b` is the capped page and
 * `a` is not -- so it cannot be used to ask "did this page come back to where it
 * started". Passing v1's own snapshot through it trips the 100-card check against
 * v1's uncapped 4,703. This is the symmetric version. */
export function sameAs(before, after) {
  for (const key of ['count', 'grouped', 'empty']) {
    if (before[key] !== after[key]) {
      return `${key}: was ${JSON.stringify(before[key])}, now ${JSON.stringify(after[key])}`;
    }
  }
  for (const key of Object.keys(before.controls)) {
    if (before.controls[key] !== after.controls[key]) {
      return `control ${key}: was ${JSON.stringify(before.controls[key])}, ` +
             `now ${JSON.stringify(after.controls[key])}`;
    }
  }
  for (const [what, x, y] of [
    ['cards', before.cards, after.cards],
    ['facetHeaders', before.facetHeaders, after.facetHeaders],
    ['years', before.years, after.years],
    ['affButtons', before.affButtons, after.affButtons],
    ...FACET_MOUNTS.map(id => [id, before.facets[id], after.facets[id]]),
  ]) {
    if (eq(x, y)) continue;
    if (!x || !y) return `${what}: one side is absent`;
    if (x.length !== y.length) return `${what}: was ${x.length} item(s), now ${y.length}`;
    const at = x.findIndex((v, i) => !eq(v, y[i]));
    return `${what}[${at}]: was ${JSON.stringify(x[at]).slice(0, 120)}, ` +
           `now ${JSON.stringify(y[at]).slice(0, 120)}`;
  }
  return null;
}

export { FACET_MOUNTS, txt, readPage, compare, eq };
