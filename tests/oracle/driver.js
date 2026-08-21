/* Evaluate the characterization states (design v2 §8) against a filter engine.
 *
 * Two jobs, one code path, because the differential is only worth anything if both
 * sides are observed identically:
 *
 *   ?emit=golden            record the corpus       -> docs/perf/golden/{records,states,results,provenance}.json
 *   ?emit=actual&target=v2  replay it against v2    -> docs/perf/golden/actual-v2.json
 *
 * Drives the engine directly rather than the DOM: the oracle records what the filter
 * engine decides, and rendering 4,703 cards per state three hundred times over would
 * take an hour and prove nothing extra.
 *
 * Results are POSTed to scripts/serve.py's sink, so there is no ceiling on how much
 * the run can write and nothing depends on a download directory.
 *
 *   ?limit=N   evaluate only the first N states (smoke runs)
 */
import { loadInstrumentedV1, injectV1Markup } from './instrument.js';
import { enumerate, BOUNDED, CHECKPOINTS } from './states.js';

const V1_SRC = '/assets/js/sdv-index.js';
const V1_PAGE = '/index.html';
const SINK = '/__sink/';

/* The affiliation button groups are counted the same way the checkbox facets are
 * (buildAffToggles -> countValues(filteredData(facet), facet)), so they belong in
 * the recorded facet maps even though they render as buttons. */
const COUNTED = BOUNDED.concat(['aff_type', 'aff_region']);

const statusEl = document.getElementById('harness-status');
const logEl = document.getElementById('harness-log');
const say = (m) => { statusEl.textContent = m; console.log('[oracle]', m); };
const note = (m) => { logEl.textContent += m + '\n'; console.log('[oracle]', m); };

/* Exposed so the runner can poll progress without scraping text. */
window.__ORACLE__ = { done: false, error: null, progress: 0, total: 0, summary: null };

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function waitFor(fn, what, timeoutMs = 120000) {
  const t0 = performance.now();
  for (;;) {
    let v;
    try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    if (performance.now() - t0 > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await sleep(100);
  }
}

function applySpec(V1, spec) {
  const s = V1.state;
  s.titleQuery = spec.titleQuery;
  s.minImportance = spec.minImportance;
  s.minPopularity = spec.minPopularity;
  s.group = spec.group;
  s.sortWithin = spec.sortWithin;
  s.facetQuery = { authors: '' };
  s.summaryExpanded = false;
  s.showNeeds = false;
  const sel = {};
  for (const fk of V1.FACET_KEYS) sel[fk] = {};
  for (const f of Object.keys(spec.sel || {})) {
    for (const v of spec.sel[f]) sel[f][v] = true;
  }
  /* A permission group's map holds only its LIT values; a dark button is simply
     absent, which is what groupPermits reads as a veto. */
  for (const g of ['aff_type', 'aff_region']) {
    sel[g] = {};
    for (const v of spec.aff[g]) sel[g][v] = true;
  }
  s.sel = sel;
}

/* renderResults' grouping block, minus the DOM. Kept in step with it deliberately:
 * if the two ever disagree the oracle is recording something the page never shows. */
function groupingOf(V1, items) {
  if (V1.state.group === 'none') return null;
  const groups = Object.create(null), order = [], sizes = {};
  for (const rec of items) {
    for (const h of V1.groupHeadersFor(rec)) {
      if (!groups[h]) { groups[h] = 0; order.push(h); }
      groups[h] += 1;
    }
  }
  for (const h of order) sizes[h] = groups[h];
  if (['sdv_component', 'sdv_concept', 'use_case', 'industry', 'integration']
      .indexOf(V1.state.group) >= 0) {
    order.sort((A, B) => (sizes[B] - sizes[A]) || A.localeCompare(B));
  }
  return V1.headerOrder(order).map(h => [h, groups[h]]);
}

function evaluate(V1, spec, indexOf) {
  applySpec(V1, spec);
  const items = V1.filteredData();
  const ordered = V1.sortWithin(items.slice());
  const ids = ordered.map(r => indexOf.get(r));
  if (ids.some(i => i === undefined)) {
    throw new Error(`state ${spec.id}: a result row is not in the record table`);
  }
  const facets = {};
  for (const f of COUNTED) {
    /* Self-excluding count, exactly as buildCheckboxFacet/buildAffToggles compute it,
       and materialized over the whole universe so a value dropping out of the map is
       distinguishable from a value falling to zero. */
    const counts = V1.countValues(V1.filteredData(f), f);
    const m = {};
    for (const v of (V1.UNIVERSE[f] || []).slice().sort()) m[v] = counts[v] || 0;
    facets[f] = m;
  }
  return { total: items.length, ids, facets, groups: groupingOf(V1, items) };
}

async function post(name, obj) {
  /* Big artifacts (the id table, the per-state index arrays) go out unindented --
     they are read by tools, and indenting them triples the committed size. */
  const compact = obj.__compact === true;
  delete obj.__compact;
  const body = JSON.stringify(obj, null, compact ? 0 : 1);
  const r = await fetch(SINK + name, { method: 'POST', body });
  if (!r.ok) throw new Error(`sink refused ${name}: HTTP ${r.status}`);
  const info = await r.json();
  note(`wrote ${info.path} (${info.bytes.toLocaleString()} B)`);
  return info;
}

/* Bring up the v1 engine: inject the live markup so init() finds its element ids,
 * evaluate the instrumented source, wait for the index and both pools. */
async function v1Engine() {
  say('injecting v1 markup');
  await injectV1Markup(V1_PAGE, 'v1-markup');

  say('loading instrumented v1');
  const provenance = await loadInstrumentedV1(V1_SRC);
  note(`v1 source sha256 ${provenance.source_sha256}`);

  /* init() runs on DOMContentLoaded, which already fired, so the runtime starts as
     soon as the script evaluates. */
  say('waiting for index and both pools');
  const V1 = await waitFor(() => window.__V1__, '__V1__');
  await waitFor(() => {
    const p = V1.probe();
    return p.data > 0 && p.cite != null && p.gh != null;
  }, 'index + citation pool + repository pool', 180000);
  V1.computeUniverse();
  return { engine: V1, provenance };
}

/* Stage 1 adds tests/oracle/adapter-v2.js, presenting the v2 modules behind the same
 * handful of methods this file uses. Loaded lazily so a v1-only run cannot fail on a
 * file that does not exist yet. */
async function v2Engine() {
  say('loading the v2 engine adapter');
  const mod = await import('./adapter-v2.js');
  return mod.build({ say, note, waitFor });
}

async function main() {
  const params = new URLSearchParams(location.search);
  const limit = parseInt(params.get('limit') || '0', 10);
  const emit = params.get('emit') || 'golden';
  const target = params.get('target') || 'v1';
  if (emit !== 'golden' && emit !== 'actual') throw new Error(`unknown emit=${emit}`);
  if (emit === 'golden' && target !== 'v1') {
    throw new Error('the golden corpus is defined by v1; refusing to record another target as golden');
  }

  const { engine: V1, provenance } = target === 'v1' ? await v1Engine() : await v2Engine();
  const probe = V1.probe();
  note(`target ${target} -- corpus: ${probe.data} curated + ${probe.cite} citation-pool + ${probe.gh} repo-pool`);

  /* The canonical record table. Every state's result is stored as indices into it,
     which keeps the corpus small enough to read and to commit while still naming the
     exact record behind any mismatch. */
  const all = V1.activeData();
  const indexOf = new Map();
  const table = [];
  const dupes = [];
  all.forEach((rec, i) => {
    const id = rec.id != null ? String(rec.id) : `__noid__${i}`;
    indexOf.set(rec, i);
    table.push(id);
  });
  const seenIds = new Set();
  for (const id of table) {
    if (seenIds.has(id)) dupes.push(id); else seenIds.add(id);
  }
  if (dupes.length) note(`WARNING: ${dupes.length} duplicate record ids, e.g. ${dupes[0]}`);

  say('enumerating states');
  /* Enumerated from the target's own universe. For emit=actual that is a claim in
     itself: if v2's vocabularies drifted, the state list drifts with them and
     golden_diff.py reports the missing and extra states by name. */
  let specs = enumerate(V1);
  if (limit > 0) specs = specs.slice(0, limit);
  window.__ORACLE__.total = specs.length;
  note(`${specs.length} states`);

  const results = {};
  const t0 = performance.now();
  for (let i = 0; i < specs.length; i++) {
    results[specs[i].id] = evaluate(V1, specs[i], indexOf);
    window.__ORACLE__.progress = i + 1;
    if (i % 10 === 0 || i === specs.length - 1) {
      const per = (performance.now() - t0) / (i + 1);
      say(`state ${i + 1}/${specs.length} (${per.toFixed(0)} ms each, ` +
          `~${((specs.length - i - 1) * per / 1000).toFixed(0)} s left)`);
      await sleep(0);   // yield, so progress is observable from outside
    }
  }
  const elapsed = (performance.now() - t0) / 1000;
  note(`evaluated ${specs.length} states in ${elapsed.toFixed(1)} s`);

  const bad = [];
  for (const id of Object.keys(CHECKPOINTS)) {
    if (!(id in results)) { if (!limit) bad.push(`${id}: missing`); continue; }
    const got = results[id].total, want = CHECKPOINTS[id];
    if (got !== want) bad.push(`${id}: expected ${want}, got ${got}`);
  }
  if (bad.length && emit === 'golden') {
    /* A corpus that disagrees with the design's stated baseline is not worth
       writing, and quietly writing it is how a bad oracle gets trusted. */
    window.__ORACLE__.error = 'checkpoint mismatch: ' + bad.join('; ');
    say('CHECKPOINT MISMATCH -- nothing written');
    bad.forEach(note);
    return;
  }
  if (bad.length) {
    /* On the actual side a checkpoint may legitimately move: the title-only search
       of §4 is a planned semantic change, and imp-0-search-health is one of its
       documented exceptions. Record it and let golden_diff.py, which knows the
       exception list, decide whether it is allowed. */
    note('checkpoints differing from the v1 baseline (golden_diff.py adjudicates):');
    bad.forEach(b => note('  ' + b));
  } else {
    note('all §8 checkpoints match');
  }

  if (emit === 'actual') {
    await post(`docs/perf/golden/actual-${target}.json`, {
      __compact: true, target,
      counts: { curated: probe.data, citation_pool: probe.cite, repo_pool: probe.gh,
                total: table.length, duplicate_ids: dupes.length },
      /* The actual side carries its own id table: nothing requires v2 to hold the
         corpus in v1's order, so the diff has to compare id sequences, not indices
         into two tables that may not line up. */
      ids: table, results,
      provenance: provenance || null,
      collation: { locale: Intl.DateTimeFormat().resolvedOptions().locale },
    });
    window.__ORACLE__.summary = { states: specs.length, records: table.length, elapsed };
    window.__ORACLE__.done = true;
    say(`DONE (actual/${target}): ${specs.length} states, ${table.length} records, ${elapsed.toFixed(1)} s`);
    return;
  }


  await post('docs/perf/golden/records.json', {
    __compact: true,
    counts: { curated: probe.data, citation_pool: probe.cite, repo_pool: probe.gh,
              total: table.length, duplicate_ids: dupes.length },
    ids: table,
  });
  await post('docs/perf/golden/states.json', { states: specs });
  await post('docs/perf/golden/results.json', { __compact: true, results });
  await post('docs/perf/golden/provenance.json', {
    generated_by: 'tests/oracle/driver.js',
    v1: provenance,
    /* sortWithin and several facet sorts call localeCompare with no locale, so the
       recorded order is a property of the runtime that generated it. Record enough
       to detect a machine whose collation would produce a different corpus. */
    collation: {
      locale: Intl.DateTimeFormat().resolvedOptions().locale,
      canary: ['a'.localeCompare('B'), 'ä'.localeCompare('az'),
               "o'brien".localeCompare('oa'), '10'.localeCompare('9')],
    },
    user_agent: navigator.userAgent,
    state_count: specs.length,
    elapsed_seconds: Number(elapsed.toFixed(1)),
    checkpoints: CHECKPOINTS,
  });

  window.__ORACLE__.summary = {
    states: specs.length, records: table.length, elapsed: elapsed,
  };
  window.__ORACLE__.done = true;
  say(`DONE: ${specs.length} states, ${table.length} records, ${elapsed.toFixed(1)} s`);
}

main().catch(e => {
  window.__ORACLE__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  note(String(e && e.stack || e));
});
