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

async function v2Engine(fixture) {
  const mod = await import('../oracle/adapter-v2.js');
  const built = await mod.build({ say, note: line, waitFor });
  built.engine.setCorpus(fixture.curated, fixture.citation_pool_raw, fixture.repo_pool_raw);
  return { E: built.engine, provenance: built.provenance };
}

/* ---- main --------------------------------------------------------------- */

async function main() {
  const target = new URLSearchParams(location.search).get('target') || 'v1';
  say(`loading fixture and the ${target} engine`);

  const fixtureText = await (await fetch('/tests/semantic/fixture.json', { cache: 'no-store' })).text();
  const casesText = await (await fetch('/tests/semantic/cases.js', { cache: 'no-store' })).text();
  const fixture = JSON.parse(fixtureText);

  const { E, provenance } = target === 'v1' ? await v1Engine(fixture) : await v2Engine(fixture);
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
  for (const c of PENDING_V2) {
    results.push({ id: c.id, ok: null, pending: true, why: c.why });
  }

  const passed = results.filter(r => r.ok === true).length;
  const failed = results.filter(r => r.ok === false).length;
  const pending = results.filter(r => r.pending).length;

  line('');
  line(`${passed} passed, ${failed} failed, ${pending} pending (v2 behaviors, Stage 1)`);
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
  say(failed ? `FAIL: ${failed} case(s)` : `PASS: ${passed} passed, ${pending} pending`);
}

main().catch(e => {
  window.__SEMANTIC__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  line(String(e && e.stack || e));
});
