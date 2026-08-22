/* Run the hand-authored semantic cases against a filter engine.
 *
 *   /tests/semantic/runner.html            v1 (default)
 *   /tests/semantic/runner.html?target=v2  the Stage 1 engine
 *
 * Swaps the synthetic fixture in for the real corpus by the same path loadPools
 * takes, so pool normalization and alias suppression are exercised for real rather
 * than simulated. Writes tests/semantic/last-run.json through the serve.py sink;
 * tests/gates.py reads it and refuses to pass on a stale or missing run.
 */
import { loadInstrumentedV1, injectV1Markup } from '../oracle/instrument.js';
import { CASES, PENDING_V2, ALL_AFF_TYPES, ALL_AFF_REGIONS } from './cases.js';
import { RENDER_CASES } from './render-cases.js';

/* Wrapped before anything else runs, so "created during render" means every object
 * URL the page made, not just the ones made after the counter was installed. */
const urls = {
  created: 0, revoked: 0, lastRevoked: null,
  reset() { this.created = 0; this.revoked = 0; this.lastRevoked = null; },
};
const realCreate = URL.createObjectURL.bind(URL);
const realRevoke = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = function (...a) { urls.created++; return realCreate(...a); };
URL.revokeObjectURL = function (u) { urls.revoked++; urls.lastRevoked = u; return realRevoke(u); };

const statusEl = document.getElementById('status');
const outEl = document.getElementById('out');
const say = (m) => { statusEl.textContent = m; };
const line = (m) => { outEl.textContent += m + '\n'; };

window.__SEMANTIC__ = { done: false, error: null, passed: 0, failed: 0, pending: 0 };

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function waitFor(fn, what, timeoutMs = 60000) {
  const t0 = performance.now();
  for (;;) {
    let v; try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    if (performance.now() - t0 > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await sleep(50);
  }
}

/* ---- assertions --------------------------------------------------------- */

const idOf = (rec) => String(rec.id);
const sorted = (a) => a.slice().sort();

function deepEqual(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

function applyState(E, s) {
  const st = E.state;
  st.titleQuery = s.titleQuery;
  st.minImportance = s.minImportance;
  st.minPopularity = s.minPopularity;
  st.group = s.group;
  st.sortWithin = s.sortWithin;
  st.facetQuery = { authors: '' };
  st.summaryExpanded = false;
  st.showNeeds = false;
  const sel = {};
  for (const fk of E.FACET_KEYS) sel[fk] = {};
  for (const f of Object.keys(s.sel || {})) for (const v of s.sel[f]) sel[f][v] = true;
  for (const g of ['aff_type', 'aff_region']) {
    sel[g] = {};
    for (const v of s.aff[g]) sel[g][v] = true;
  }
  st.sel = sel;
}

/* Duplicated from the driver on purpose -- see the note there. Grouping is display
 * behavior, and a shared helper would let a change to one silently redefine both. */
function groupsOf(E, items) {
  if (E.state.group === 'none') return null;
  const counts = Object.create(null), order = [], sizes = {};
  for (const rec of items) {
    for (const h of E.groupHeadersFor(rec)) {
      if (!counts[h]) { counts[h] = 0; order.push(h); }
      counts[h] += 1;
    }
  }
  for (const h of order) sizes[h] = counts[h];
  if (['sdv_component', 'sdv_concept', 'use_case', 'industry', 'integration']
      .indexOf(E.state.group) >= 0) {
    order.sort((A, B) => (sizes[B] - sizes[A]) || A.localeCompare(B));
  }
  return E.headerOrder(order).map(h => [h, counts[h]]);
}

function byId(E, id) {
  const rec = E.activeData().find(r => idOf(r) === id);
  if (!rec) throw new Error(`fixture record ${id} is not in the corpus`);
  return rec;
}

/* Returns the first failure message for a case, or null. One message, not a list:
 * the §11 output contract is that a failure is cheap to read. */
function check(E, c) {
  applyState(E, c.state);
  const items = E.filteredData();
  const ids = items.map(idOf);
  const e = c.expect;

  if (e.total != null && items.length !== e.total) {
    return `total: expected ${e.total}, got ${items.length}`;
  }
  if (e.ids) {
    if (!deepEqual(sorted(e.ids), sorted(ids))) {
      const want = new Set(e.ids), got = new Set(ids);
      const missing = e.ids.filter(i => !got.has(i));
      const extra = ids.filter(i => !want.has(i));
      if (missing.length) return `missing ${missing.length}: ${missing.join(', ')}`;
      return `unexpected ${extra.length}: ${extra.join(', ')}`;
    }
  }
  for (const id of e.idsInclude || []) {
    if (!ids.includes(id)) return `expected ${id} in the result, it is absent`;
  }
  for (const id of e.idsExclude || []) {
    if (ids.includes(id)) return `expected ${id} to be absent, it is present`;
  }
  for (const [id, n] of Object.entries(e.idCount || {})) {
    const got = ids.filter(i => i === id).length;
    if (got !== n) return `${id} appears ${got} time(s), expected ${n}`;
  }
  if (e.order && !deepEqual(e.order, E.sortWithin(items.slice()).map(idOf))) {
    const got = E.sortWithin(items.slice()).map(idOf);
    const at = e.order.findIndex((x, i) => x !== got[i]);
    return `order differs at position ${at}: expected ${e.order[at]}, got ${got[at]}`;
  }
  if (e.groups) {
    const got = groupsOf(E, items);
    if (!deepEqual(e.groups, got)) {
      const at = e.groups.findIndex((g, i) => !deepEqual(g, got && got[i]));
      return `groups differ at position ${at}: expected ` +
             `${JSON.stringify(e.groups[at])}, got ${JSON.stringify(got && got[at])}`;
    }
  }
  for (const [facet, want] of Object.entries(e.facetCounts || {})) {
    const got = E.countValues(E.filteredData(facet), facet);
    for (const [v, n] of Object.entries(want)) {
      if ((got[v] || 0) !== n) return `facet ${facet}[${v}]: expected ${n}, got ${got[v] || 0}`;
    }
  }
  for (const [id, facet, want] of e.valuesOf || []) {
    const got = E.valuesOf(byId(E, id), facet);
    if (!deepEqual(want, got)) {
      return `valuesOf(${id}, ${facet}): expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`;
    }
  }
  for (const [id, want] of e.organizationsOf || []) {
    const got = E.organizationsOf(byId(E, id));
    if (!deepEqual(want, got)) {
      return `organizationsOf(${id}): expected ${JSON.stringify(want)}, got ${JSON.stringify(got)}`;
    }
  }
  for (const [id, want] of e.popularity || []) {
    const got = E.popularity(byId(E, id));
    if (Math.abs(got - want) > 1e-12) return `popularity(${id}): expected ${want}, got ${got}`;
  }
  for (const [id, want] of e.tier || []) {
    const got = byId(E, id).tier;
    if (got !== want) return `tier(${id}): expected ${want}, got ${got}`;
  }
  for (const [facet, value] of Object.entries(e.universeExcludes || {})) {
    if ((E.UNIVERSE[facet] || []).includes(value)) {
      return `UNIVERSE.${facet} must not contain ${value}`;
    }
  }
  if (e.alsoAt) {
    const sub = check(E, { id: c.id + ' (second state)', state: e.alsoAt.state, expect: e.alsoAt });
    if (sub) return `second state: ${sub}`;
  }
  return null;
}

/* ---- engines ------------------------------------------------------------ */

async function v1Engine(fixture) {
  await injectV1Markup('/index.html', 'v1-markup');
  const provenance = await loadInstrumentedV1('/assets/js/sdv-index.js');
  const E = await waitFor(() => window.__V1__, '__V1__');
  /* init() is mid-flight against the real index. Let it finish so its late
     applyFilters cannot overwrite the fixture behind us, then swap the corpus. */
  await waitFor(() => E.probe().data > 0, 'the real index to finish loading', 180000);
  E.setCorpus(fixture.curated, fixture.citation_pool_raw, fixture.repo_pool_raw);
  return { E, provenance };
}

/* v1 gets the RAW fixture and does its own suppression, normalization and scoring in
 * the browser, because that is what v1 does. v2 gets the same fixture PROJECTED by
 * site_projection.py, because from Stage 2a that is what the page consumes.
 *
 * The two paths landing on the same 12 records is itself the check that the Python
 * port of the pool logic agrees with the JavaScript original it was ported from. */
async function v2Engine() {
  const mod = await import('../oracle/adapter-v2.js');
  const built = await mod.build({ say, note: line, waitFor });
  const proj = await (await fetch('/tests/semantic/fixture-projected.json',
    { cache: 'no-store' })).json();
  built.engine.setCorpus(proj.core, proj.counts);
  if (proj.postings) built.engine.setPostings(new (await import('../../v2/assets/js/search.js')).Postings(proj.postings));
  for (const [name, content] of Object.entries(proj.detail)) {
    built.app.details.prime(name, content);
  }
  return { E: built.engine, provenance: built.provenance };
}

/* ---- the rendering harness ---------------------------------------------- */

/* A real App on real markup, driven through real events. Nothing here reaches into
 * the App's internals to set a limit or force a render: the cases are about what the
 * page does when a reader clicks, so they click. */
async function renderHarness() {
  const { App } = await import('../../v2/assets/js/app.js');
  const { downloadBibtex } = await import('../../v2/assets/js/render.js');
  const { nextTick } = await import('../../v2/assets/js/state.js');

  const html = await (await fetch('/v2/index.html', { cache: 'no-store' })).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script').forEach(s => s.remove());
  const mount = document.getElementById('render-mount');
  mount.innerHTML = doc.body.innerHTML;

  const generated = await (await fetch('/tests/semantic/render-fixture.json',
    { cache: 'no-store' })).json();

  const h = {
    urls, downloadBibtex, mount, generated,
    Details: (await import('../../v2/assets/js/data.js')).Details,
    Postings: (await import('../../v2/assets/js/search.js')).Postings,
    app: null, results: null,
    /* Scoped to the container, so App.$ resolves ids inside it rather than globally. */
    async load(bundle) {
      h.app = new App(mount).mount();
      h.app.setCorpus(bundle.core, bundle.counts);
      if (bundle.postings) h.app.engine.postings = new h.Postings(bundle.postings);
      for (const [name, content] of Object.entries(bundle.detail || {})) {
        h.app.details.prime(name, content);
      }
      h.app.apply();
      h.results = h.app.els.results;
      await h.settle();
    },
    select(id, value) {
      const e = mount.querySelector('#' + id);
      e.value = value;
      e.dispatchEvent(new Event('change', { bubbles: true }));
    },
    range(id, value) {
      const e = mount.querySelector('#' + id);
      e.value = String(value);
      e.dispatchEvent(new Event('input', { bubbles: true }));
    },
    /* The controller coalesces to a tick, so a click's effect is not visible until
       the tick after it. Two ticks, to be sure the render has run. Uses the
       controller's own tick, which keeps working in a background tab -- these runs
       are driven, so the tab is usually not the one in front. */
    settle() {
      return new Promise(r => nextTick(() => nextTick(r)));
    },
    /* Bounded by TIME, not by a tick count. nextTick falls back to a MessageChannel
       task in a background tab, which resolves in microseconds -- so a loop of 200
       ticks expires in a few milliseconds, long before a 150 ms debounce (clamped to
       roughly 700 ms while hidden) has any chance to fire. */
    async waitFor(cond, what, timeoutMs = 10000) {
      const t0 = performance.now();
      for (;;) {
        if (cond()) return true;
        if (performance.now() - t0 > timeoutMs) {
          throw new Error(`timed out waiting for ${what}`);
        }
        await h.settle();
      }
    },
  };
  return h;
}

/* ---- main --------------------------------------------------------------- */

async function main() {
  const target = new URLSearchParams(location.search).get('target') || 'v1';
  say(`loading fixture and the ${target} engine`);

  const fixtureText = await (await fetch('/tests/semantic/fixture.json', { cache: 'no-store' })).text();
  const casesText = await (await fetch('/tests/semantic/cases.js', { cache: 'no-store' })).text();
  const fixture = JSON.parse(fixtureText);

  const { E, provenance } = target === 'v1' ? await v1Engine(fixture) : await v2Engine();
  const p = E.probe();
  line(`corpus: ${p.data} curated + ${p.cite} pool row(s) surviving suppression`);
  line('');

  const results = [];
  for (const c of CASES) {
    let failure;
    try { failure = check(E, c); }
    catch (err) { failure = `threw: ${err.message}`; }
    results.push({ id: c.id, ok: !failure, failure: failure || null });
    line(`${failure ? 'FAIL' : 'pass'}  ${c.id}${failure ? '\n        ' + failure : ''}`);
  }
  /* The rendering suite needs its own markup and its own App -- the engine run above
     has already mounted one copy, and two copies would collide on element ids. Tear
     the first one down before building the second. */
  const done = new Set();
  if (target === 'v2') {
    line('');
    document.getElementById('v1-markup').replaceChildren();
    const h = await renderHarness();
    for (const c of RENDER_CASES) {
      let failure;
      try { failure = await c.run(h); }
      catch (err) { failure = `threw: ${err.message}`; }
      done.add(c.id);
      results.push({ id: c.id, ok: !failure, failure: failure || null });
      line(`${failure ? 'FAIL' : 'pass'}  ${c.id}${failure ? '\n        ' + failure : ''}`);
    }
  }
  for (const c of PENDING_V2) {
    if (done.has(c.id)) continue;
    results.push({ id: c.id, ok: null, pending: true, closes: c.closes, why: c.why });
  }
  if (target === 'v2' && results.some(r => r.pending)) {
    line(`NOTE: ${results.filter(r => r.pending).length} case(s) named in cases.js ` +
         'have no implementation in render-cases.js');
  }

  const passed = results.filter(r => r.ok === true).length;
  const failed = results.filter(r => r.ok === false).length;
  const pending = results.filter(r => r.pending).length;

  line('');
  const byStage = {};
  for (const r of results) if (r.pending) byStage[r.closes] = (byStage[r.closes] || 0) + 1;
  const breakdown = Object.keys(byStage).sort()
    .map(k => `${byStage[k]} in stage ${k}`).join(', ');
  line(`${passed} passed, ${failed} failed, ${pending} pending (${breakdown})`);
  const firstFail = results.find(r => r.ok === false);
  if (firstFail) line(`FIRST FAILING CASE  ${firstFail.id}\n  ${firstFail.failure}`);

  const digest = async (t) => {
    const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(t));
    return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
  };
  const body = JSON.stringify({
    target,
    /* gates.py compares these against the files on disk, so a run cannot go stale
       without the gate noticing. */
    fixture_sha256: await digest(fixtureText),
    cases_sha256: await digest(casesText),
    v1: provenance || null,
    passed, failed, pending, results,
  }, null, 1);
  const r = await fetch('/__sink/tests/semantic/last-run.json', { method: 'POST', body });
  if (!r.ok) throw new Error(`sink refused the run: HTTP ${r.status}`);

  Object.assign(window.__SEMANTIC__, { done: true, passed, failed, pending });
  say(failed ? `FAIL: ${failed} case(s)` : `PASS: ${passed} passed, ${pending} pending (${breakdown})`);
}

main().catch(e => {
  window.__SEMANTIC__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  line(String(e && e.stack || e));
});
