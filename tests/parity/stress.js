/* Four suites the state-based parity harness cannot express (owner, 2026-08-22).
 *
 *   toggles   select AND DESELECT sequences, compared after every single step
 *   sweeps    every importance stop, every popularity stop, every year, every
 *             grouping against every sort -- systematically, not sampled
 *   search    94 realistic queries drawn from the corpus itself
 *   showall   the "Show all" path timed on both pages
 *
 * Why separate from parity.js: that harness builds each state from a cleared
 * baseline, so nothing in it ever unticks a box or switches a toggle back. A
 * selection that lingers after being cleared, or a switch that does not return to
 * where it started, is invisible to it by construction. These drive sequences and
 * compare after each step.
 *
 *   ?suite=toggles,sweeps,search,showall   (default: all)
 *   ?seq=40    how many toggle sequences (default 40)
 */
import { readPage, compare, sameAs, FACET_MOUNTS, txt } from './readpage.js';

const params = new URLSearchParams(location.search);
const SUITES = (params.get('suite') || 'toggles,sweeps,search,showall').split(',');
const SEQUENCES = parseInt(params.get('seq') || '40', 10);

const statusEl = document.getElementById('status');
const outEl = document.getElementById('out');
const say = (m) => { statusEl.textContent = m; };
const line = (m) => { outEl.textContent += m + '\n'; };

window.__STRESS__ = { done: false, error: null, failed: 0, phase: 'starting', report: {} };

/* A dedicated worker's timer: rAF stops in a hidden tab and setTimeout is clamped to
 * a minute there, and a driven run is always in a hidden tab. */
const ticker = new Worker(URL.createObjectURL(
  new Blob(['setInterval(() => postMessage(0), 25);'], { type: 'text/javascript' })));
let waiters = [];
ticker.onmessage = () => { const q = waiters; waiters = []; for (const f of q) f(); };
const tick = () => new Promise(r => waiters.push(r));
async function waitMs(ms) {
  const t0 = performance.now();
  while (performance.now() - t0 < ms) await tick();
}

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function settler(doc) {
  const el = doc.getElementById('pubs-results');
  let last = 0;
  new MutationObserver(() => { last = performance.now(); })
    .observe(el, { childList: true, subtree: true, characterData: true });
  /* `require` means: this change MUST redraw, so waiting for quiet is not enough --
     wait for an actual mutation first. Both pages share one main thread, and v1
     re-rendering 4,703 cards blocks it for seconds at a time, so a fixed
     "nothing happened yet" allowance can expire before v2's coalesced pass has had a
     chance to run. Reading then compares the new state of one page against the
     PREVIOUS state of the other, which looks exactly like an ordering bug. */
  return async ({ quietMs = 120, firstMs = 3500, timeoutMs = 60000,
                  require = false } = {}) => {
    const t0 = performance.now();
    last = 0;
    for (;;) {
      await tick();
      const now = performance.now();
      if (now - t0 > timeoutMs) return { elapsed: -1, timedOut: true };
      if (last && now - last > quietMs) return { elapsed: last - t0 };
      if (!last && !require && now - t0 > firstMs) return { elapsed: 0 };
    }
  };
}

const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));

/* Suites must not inherit each other's view state.
 *
 * "Clear filters" resets the FILTERS and deliberately leaves grouping and sort alone
 * -- they are view preferences. So the sweeps suite left both pages grouped by
 * industry, and the search suite that followed counted every record once per group it
 * appeared under, which made 64 of 94 queries look internally inconsistent. */
async function resetView(d1, d2, s1, s2) {
  for (const d of [d1, d2]) {
    d.getElementById('btn-clear').click();
    for (const [id, v] of [['sort-group', 'none'], ['sort-within', 'importance']]) {
      const e = d.getElementById(id);
      if (e.value !== v) { e.value = v; fire(e, 'change'); }
    }
  }
  await Promise.all([s1(), s2()]);
}

/* ---- the operations a reader can perform ------------------------------- */

/* Each returns a function that performs it on one document, so the same operation is
 * applied to both pages and the two are compared afterwards. Every one is its own
 * inverse when applied twice, which is what makes deselection testable. */
function operations(doc, rand) {
  const ops = [];
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];

  for (const mount of FACET_MOUNTS) {
    const boxes = [...doc.querySelectorAll(`#${mount} input[type=checkbox]`)].slice(0, 40);
    if (boxes.length) {
      const v = pick(boxes).value;
      ops.push({ label: `${mount}:${v}`, run: (d) => {
        const b = d.querySelector(`#${mount} input[type=checkbox][value="${CSS.escape(v)}"]`);
        if (!b) return false;
        b.checked = !b.checked;
        fire(b, 'change');
        return true;
      } });
    }
  }
  const years = [...doc.querySelectorAll('#facet-years .year-btn')];
  if (years.length) {
    const label = txt(pick(years)).replace(/\s+\d+$/, '').trim();
    ops.push({ label: `year:${label}`, run: (d) => {
      const b = [...d.querySelectorAll('#facet-years .year-btn')]
        .find(x => txt(x).replace(/\s+\d+$/, '').trim() === label);
      if (!b) return false;
      b.click();
      return true;
    } });
  }
  const affs = [...doc.querySelectorAll('.aff-btn')];
  if (affs.length) {
    const label = txt(pick(affs)).replace(/\s*\d+$/, '').trim();
    ops.push({ label: `aff:${label}`, run: (d) => {
      const b = [...d.querySelectorAll('.aff-btn')]
        .find(x => txt(x).replace(/\s*\d+$/, '').trim() === label);
      if (!b) return false;
      b.click();
      return true;
    } });
  }
  for (const id of ['btn-toggle-summaries', 'btn-toggle-needs']) {
    ops.push({ label: `switch:${id}`, run: (d) => {
      const b = d.getElementById(id);
      if (!b) return false;
      b.click();
      return true;
    } });
  }
  return ops;
}

/* ---- suites ------------------------------------------------------------- */

async function suiteToggles(d1, d2, s1, s2, report) {
  await resetView(d1, d2, s1, s2);
  const rand = rng(90210);
  let failed = 0, steps = 0;
  for (let seq = 1; seq <= SEQUENCES; seq++) {
    d1.getElementById('btn-clear').click();
    d2.getElementById('btn-clear').click();
    await Promise.all([s1(), s2()]);

    const pristine1 = readPage(d1), pristine2 = readPage(d2);
    const ops = operations(d1, rand);
    /* Between three and six operations, then the SAME operations again in reverse,
       which returns every toggle to where it started. The page must come back to the
       pristine state exactly -- that is the deselection test. */
    const chosen = [];
    const n = 3 + Math.floor(rand() * 4);
    for (let i = 0; i < n; i++) chosen.push(ops[Math.floor(rand() * ops.length)]);

    const trace = [];
    for (const phase of ['forward', 'back']) {
      const list = phase === 'forward' ? chosen : [...chosen].reverse();
      for (const op of list) {
        const ok1 = op.run(d1), ok2 = op.run(d2);
        await Promise.all([s1(), s2()]);
        steps++;
        trace.push(`${phase}:${op.label}`);
        if (ok1 !== ok2) {
          failed++;
          line(`FAIL toggles #${seq} after ${trace.join(' → ')}\n` +
               `        control found in one page only (v1 ${ok1}, v2 ${ok2})`);
          break;
        }
        const diff = compare(readPage(d1), readPage(d2));
        if (diff) {
          failed++;
          line(`FAIL toggles #${seq} after ${trace.join(' → ')}\n        ${diff}`);
          break;
        }
      }
    }
    /* Deselect everything and require both pages to come back exactly.
     *
     * NOT by applying each operation a second time. That premise is unsound here and
     * cost two false failures before it was noticed: toggleAff has an empty-group
     * floor, so unlighting the last lit button re-lights the whole group rather than
     * leaving it empty, and a value whose count falls to zero disappears from the
     * Authors and Affiliation lists once it is no longer selected -- so the control
     * needed to undo a step may not be on the page any more.
     *
     * "Clear filters" is the deselect-everything path a reader actually uses, and it
     * is a sound invariant: after it, the page must equal its pristine state. */
    d1.getElementById('btn-clear').click();
    d2.getElementById('btn-clear').click();
    await Promise.all([s1(), s2()]);
    const back1 = sameAs(pristine1, readPage(d1));
    const back2 = sameAs(pristine2, readPage(d2));
    if (back1 || back2) {
      failed++;
      line(`FAIL toggles #${seq} ${back1 ? 'v1' : 'v2'} did not return to its ` +
           `starting state after Clear filters\n        ${back1 || back2}`);
    }
    if (seq % 10 === 0) say(`toggles ${seq}/${SEQUENCES}, ${failed} failing`);
  }
  report.toggles = { sequences: SEQUENCES, steps, failed };
  line(`toggles: ${SEQUENCES} sequences, ${steps} compared steps, ${failed} failing`);
  return failed;
}

async function suiteSweeps(d1, d2, s1, s2, report) {
  await resetView(d1, d2, s1, s2);
  let failed = 0, states = 0;
  const set = (d, id, v, ev) => { const e = d.getElementById(id); e.value = String(v); fire(e, ev); };
  /* Every sweep step changes what is on screen, so both pages must be seen to
     redraw before either is read. */
  const both = async (fn) => {
    fn(d1); fn(d2);
    const [a, b] = await Promise.all([s1({ require: true }), s2({ require: true })]);
    if (a.timedOut || b.timedOut) line('  (warning: a page did not redraw in time)');
  };

  const run = async (what) => {
    states++;
    const diff = compare(readPage(d1), readPage(d2));
    if (diff) { failed++; line(`FAIL sweep ${what}\n        ${diff}`); }
  };

  for (const imp of [0, 1, 2, 3, 4, 5, 6]) {
    await both(d => { d.getElementById('btn-clear').click(); });
    await both(d => set(d, 'min-importance', imp, 'input'));
    await run(`importance=${imp}`);
  }
  for (let pop = 0; pop <= 95; pop += 5) {
    await both(d => { d.getElementById('btn-clear').click(); });
    await both(d => set(d, 'min-popularity', pop, 'input'));
    await run(`popularity=${pop}`);
  }
  await both(d => { d.getElementById('btn-clear').click(); });
  const years = [...d1.querySelectorAll('#facet-years .year-btn')]
    .map(b => txt(b).replace(/\s+\d+$/, '').trim());
  for (const y of years) {
    await both(d => {
      d.getElementById('btn-clear').click();
      const b = [...d.querySelectorAll('#facet-years .year-btn')]
        .find(x => txt(x).replace(/\s+\d+$/, '').trim() === y);
      if (b) b.click();
    });
    await run(`year=${y}`);
  }
  for (const g of ['none', 'kind', 'year', 'sdv_component', 'sdv_concept', 'use_case', 'industry']) {
    for (const s of ['popularity', 'importance', 'year', 'title']) {
      await both(d => {
        d.getElementById('btn-clear').click();
        set(d, 'sort-group', g, 'change');
        set(d, 'sort-within', s, 'change');
      });
      await run(`group=${g} sort=${s}`);
    }
    say(`sweeps: group ${g}, ${failed} failing`);
  }
  report.sweeps = { states, failed };
  line(`sweeps: ${states} systematic states, ${failed} failing`);
  return failed;
}

async function suiteSearch(d1, d2, s1, s2, report) {
  await resetView(d1, d2, s1, s2);
  const { queries } = await (await fetch('/tests/parity/queries.json',
    { cache: 'no-store' })).json();
  const rows = [];
  let inconsistent = 0;
  const num = (d) => Number((txt(d.getElementById('pubs-count')) || '(0)')
    .replace(/[^\d]/g, '') || 0);

  for (let i = 0; i < queries.length; i++) {
    const { kind, q } = queries[i];
    for (const [d, s] of [[d1, s1], [d2, s2]]) {
      d.getElementById('btn-clear').click();
      await s();
      const e = d.getElementById('facet-title');
      e.value = q;
      fire(e, 'input');
    }
    await Promise.all([s1(), s2()]);
    await waitMs(1400);
    await Promise.all([s1({ quietMs: 200, firstMs: 900 }), s2({ quietMs: 200, firstMs: 900 })]);

    const a = num(d1), b = num(d2);
    /* v1 and v2 search differently by design, so this reports rather than asserts --
       but v2 must at least be internally consistent: below the page limit, the count
       in the header and the number of cards drawn have to agree. */
    const drawn = d2.querySelectorAll('#pubs-results li.pub-item').length;
    const consistent = b >= 100 ? drawn === 100 : drawn === b;
    if (!consistent) {
      inconsistent++;
      line(`FAIL search ${JSON.stringify(q)}: header says ${b}, ${drawn} cards drawn`);
    }
    rows.push({ kind, q, v1: a, v2: b });
    if (i % 20 === 0) say(`search ${i + 1}/${queries.length}`);
  }
  report.search = { queries: rows.length, inconsistent, rows };
  const gained = rows.filter(r => r.v2 > r.v1).length;
  const lost = rows.filter(r => r.v2 < r.v1).length;
  line(`search: ${rows.length} queries — ${rows.length - gained - lost} identical, ` +
       `${gained} return more in v2, ${lost} fewer; ${inconsistent} inconsistent`);
  return inconsistent;
}

async function suiteShowAll(d1, d2, s1, s2, report) {
  await resetView(d1, d2, s1, s2);
  const rows = [];
  const num = (d) => Number((txt(d.getElementById('pubs-count')) || '(0)')
    .replace(/[^\d]/g, '') || 0);

  /* Importance floors chosen to give a range of result-set sizes, from a few hundred
     to the whole corpus. */
  for (const imp of [6, 4, 1, 0]) {
    for (const [d, s] of [[d1, s1], [d2, s2]]) {
      d.getElementById('btn-clear').click();
      await s();
      const e = d.getElementById('min-importance');
      e.value = String(imp);
      fire(e, 'input');
    }
    await Promise.all([s1(), s2()]);

    const total = num(d2);
    /* v1 has no page limit -- it already drew everything, and the time to do that is
       what the settle above measured. v2 draws 100 and needs the button. */
    const btn = d2.querySelector('.pub-more .more-all');
    let t = null, nodes2 = null;
    if (btn) {
      const t0 = performance.now();
      btn.click();
      const r = await s2({ quietMs: 400, firstMs: 8000, timeoutMs: 120000 });
      t = r.elapsed > 0 ? Math.round(r.elapsed) : null;
      nodes2 = d2.getElementById('pubs-results').querySelectorAll('*').length;
    }
    const drawn = d2.querySelectorAll('#pubs-results li.pub-item').length;
    const nodes1 = d1.getElementById('pubs-results').querySelectorAll('*').length;
    rows.push({ importance: imp, total, showAllMs: t, cardsAfter: drawn,
                v2Nodes: nodes2, v1Nodes: nodes1 });
    line(`show-all at importance ${imp}: ${total.toLocaleString()} results, ` +
         `${t === null ? 'already complete' : t + ' ms'}, ` +
         `${drawn.toLocaleString()} cards, ${(nodes2 || 0).toLocaleString()} nodes ` +
         `(v1 draws ${nodes1.toLocaleString()} nodes eagerly)`);
    say(`show-all: importance ${imp} done`);
  }
  report.showAll = rows;
  return 0;
}

/* ---- main --------------------------------------------------------------- */

async function main() {
  say('waiting for both pages');
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
    throw new Error(`${name} never loaded`);
  };
  const d1 = await ready('f1', 'v1');
  const d2 = await ready('f2', 'v2');
  await waitMs(5000);   // pools on v1, author postings on v2

  const s1 = settler(d1), s2 = settler(d2);
  line(`v1 ${txt(d1.getElementById('pubs-count'))}, v2 ${txt(d2.getElementById('pubs-count'))}`);
  line('');

  const report = {};
  let failed = 0;
  const suites = { toggles: suiteToggles, sweeps: suiteSweeps,
                   search: suiteSearch, showall: suiteShowAll };
  for (const name of SUITES) {
    const fn = suites[name.trim()];
    if (!fn) continue;
    window.__STRESS__.phase = name;
    say(`running ${name}`);
    failed += await fn(d1, d2, s1, s2, report);
    window.__STRESS__.failed = failed;
    await fetch('/__sink/tests/parity/stress-run.json', {
      method: 'POST', body: JSON.stringify({ failed, report }, null, 1),
    });
  }

  line('');
  line(failed ? `${failed} FAILING` : 'no failures');
  window.__STRESS__.done = true;
  window.__STRESS__.report = report;
  say(failed ? `FAIL: ${failed}` : 'PASS: all suites');
}

main().catch(e => {
  window.__STRESS__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  line(String(e && e.stack || e));
});
