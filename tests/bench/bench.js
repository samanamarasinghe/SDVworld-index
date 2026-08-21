/* Benchmark and structural probe (design v2 §9, Stage 0).
 *
 *   /tests/bench/harness.html?target=v1     the current page
 *   /tests/bench/harness.html?target=v2     /v2/, from Stage 1
 *   &reps=7                                 repetitions per interaction (default 7)
 *
 * Produces two things from one page load, because they must describe the same run:
 *
 *   timings     median and p95 for each interaction in a fixed script
 *   structure   the §9 observations -- nodes rendered, unique records rendered,
 *               object URLs created during render, corpus scans per interaction,
 *               and whether either raw pool was fetched
 *
 * Timings are RECORDED, never gated (§9, "Benchmark noise"). tests/gates.py reads the
 * structural half and fails on it.
 *
 * No driver-specific API is used anywhere in this file: it runs the same whether a
 * human opens it, Chrome is scripted, or a future Playwright driver loads the URL and
 * waits for window.__BENCH__.done. That is the whole reason it is a page and not a
 * test script.
 */

const params = new URLSearchParams(location.search);
const TARGET = params.get('target') || 'v1';
const REPS = parseInt(params.get('reps') || '7', 10);

const statusEl = document.getElementById('status');
const outEl = document.getElementById('out');
const say = (m) => { statusEl.textContent = m; };
const line = (m) => { outEl.textContent += m + '\n'; };

window.__BENCH__ = { done: false, error: null, phase: 'starting' };

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
/* Ticking a background tab.
 *
 * A driven benchmark runs in a tab that is usually not the foreground one, and Chrome
 * throttles hidden tabs hard: requestAnimationFrame stops entirely and setTimeout is
 * clamped to a second, then to a minute under intensive throttling. Either one turns
 * the settle loop into a hang. A MessageChannel task is subject to neither, so use
 * rAF when the tab is visible -- frame-aligned, cheap -- and a channel task when it
 * is not. Tick granularity only affects how soon settling is NOTICED; the reported
 * number is taken from the mutation timestamp, so this costs no accuracy. */
const chan = new MessageChannel();
let pending = [];
chan.port1.onmessage = () => { const w = pending; pending = []; w.forEach(r => r()); };
const macrotask = () => new Promise(r => { pending.push(r); chan.port2.postMessage(0); });
const tick = () => (document.visibilityState === 'visible'
  ? new Promise(r => requestAnimationFrame(() => r()))
  : macrotask());

async function waitFor(fn, what, timeoutMs = 120000) {
  const t0 = performance.now();
  for (;;) {
    let v; try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    if (performance.now() - t0 > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await tick();
  }
}

/* ---- instrumentation, installed before the target's scripts evaluate ----- */

const probe = {
  objectUrlsCreated: 0,
  objectUrlsRevoked: 0,
  fetches: [],
  /* Reset around a single interaction so "during render" means what it says. */
  mark() { return { created: this.objectUrlsCreated, revoked: this.objectUrlsRevoked }; },
};

const realCreate = URL.createObjectURL.bind(URL);
const realRevoke = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = function (...a) { probe.objectUrlsCreated++; return realCreate(...a); };
URL.revokeObjectURL = function (...a) { probe.objectUrlsRevoked++; return realRevoke(...a); };

const realFetch = window.fetch.bind(window);
window.fetch = function (input, init) {
  const url = String(input && input.url ? input.url : input);
  probe.fetches.push({ url, t: performance.now() });
  return realFetch(input, init);
};

/* Corpus scans. v2 is required to expose a counter -- §6 says the filtered snapshot
 * is computed once per interaction and passed on, and a counter in the one place
 * that walks the corpus is that invariant made checkable. v1 has no such counter and
 * cannot be given one from outside its closure, so for v1 the count is measured by
 * watching Array.prototype.filter for calls over a corpus-sized array. That is an
 * approximation and is labeled as one in the report; it undercounts an engine that
 * walks with a for-loop, which is exactly why v2 does not rely on it. */
let corpusSize = 0;
let filterScans = 0;
const realFilter = Array.prototype.filter;
Object.defineProperty(Array.prototype, 'filter', {
  configurable: true, writable: true, enumerable: false,
  value: function (...a) {
    if (corpusSize && this.length === corpusSize) filterScans++;
    return realFilter.apply(this, a);
  },
});

/* ---- settle detection --------------------------------------------------- */

/* An interaction is over when the results container stops changing. v1's handlers
 * are synchronous and v2's are debounced and coalesced to a frame, so timing the
 * dispatch call alone would flatter v1 and misread v2.
 *
 * Quiet is measured in WALL TIME, not in ticks: tick rate depends on tab visibility
 * and would otherwise silently redefine what "settled" means.
 *
 * The reported number is (last mutation - dispatch), not (settled - dispatch). The
 * detector's own quiet period is a constant of the harness, not of the page, and
 * including it would add the same tens of milliseconds to every measurement on both
 * sides of the comparison. */
function makeSettler(el) {
  let last = 0, count = 0;
  const obs = new MutationObserver(() => { last = performance.now(); count++; });
  obs.observe(el, { childList: true, subtree: true, attributes: true, characterData: true });
  return {
    reset() { last = 0; count = 0; },
    async wait(t0, quietMs = 80, timeoutMs = 20000, firstMs = 1200) {
      for (;;) {
        await tick();
        const now = performance.now();
        if (now - t0 > timeoutMs) break;
        if (last && now - last > quietMs) break;
        /* Nothing has moved YET. That may mean a no-op interaction, or it may mean
           a debounce that has not expired -- so this allowance has to comfortably
           exceed the longest debounce on the page (150 ms) plus the work behind it,
           or a debounced input measures as zero. */
        if (!last && now - t0 > firstMs) break;
      }
      return { elapsed: last ? last - t0 : 0, mutations: count, settled: performance.now() - t0 };
    },
  };
}

/* ---- the interaction script --------------------------------------------- */

/* Fixed, ordered, and each step returns the page to a known state before the next,
 * so a repetition measures the same work every time. */
function script(doc) {
  const $ = (id) => doc.getElementById(id);
  const fire = (el, type) => el.dispatchEvent(new Event(type, { bubbles: true }));
  const setRange = (el, v) => { el.value = String(v); fire(el, 'input'); };

  const firstCheckbox = () => {
    const box = $('facet-kind');
    return box && box.querySelector('input[type=checkbox]');
  };

  return [
    { id: 'search-type-health', why: 'the commonest interaction there is',
      debounceMs: 150,
      run: () => { const e = $('facet-title'); e.value = 'health'; fire(e, 'input'); },
      undo: () => { const e = $('facet-title'); e.value = ''; fire(e, 'input'); } },

    { id: 'importance-1-to-4', why: 'narrows hard; post-action result set is small',
      run: () => setRange($('min-importance'), 4),
      undo: () => setRange($('min-importance'), 1) },

    { id: 'importance-1-to-0', why: 'widens to the whole corpus, pools included',
      run: () => setRange($('min-importance'), 0),
      undo: () => setRange($('min-importance'), 1) },

    { id: 'popularity-0-to-50', why: 'forces the percentile floor over the active corpus',
      run: () => setRange($('min-popularity'), 50),
      undo: () => setRange($('min-popularity'), 0) },

    { id: 'facet-tick-first-kind', why: 'a checkbox facet, the self-excluding count path',
      run: () => { const c = firstCheckbox(); if (c) { c.checked = true; fire(c, 'change'); } },
      undo: () => { const c = firstCheckbox(); if (c) { c.checked = false; fire(c, 'change'); } } },

    { id: 'group-by-kind', why: 'grouping and header ordering',
      run: () => { const s = $('sort-group'); s.value = 'kind'; fire(s, 'change'); },
      undo: () => { const s = $('sort-group'); s.value = 'none'; fire(s, 'change'); } },

    { id: 'sort-by-title', why: 'a full re-sort of the result set',
      run: () => { const s = $('sort-within'); s.value = 'title'; fire(s, 'change'); },
      undo: () => { const s = $('sort-within'); s.value = 'importance'; fire(s, 'change'); } },

    { id: 'clear-all', why: 'the reset path; runs from a dirtied state',
      setup: () => { const e = $('facet-title'); e.value = 'data'; fire(e, 'input'); },
      run: () => $('btn-clear').click(),
      undo: () => {} },
  ];
}

/* ---- statistics --------------------------------------------------------- */

const median = (a) => {
  const s = a.slice().sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
/* Nearest-rank p95. With seven repetitions this is the slowest sample; that is
 * honest for a sample this small and is labeled with the rep count in the report. */
const p95 = (a) => {
  const s = a.slice().sort((x, y) => x - y);
  return s[Math.min(s.length - 1, Math.ceil(0.95 * s.length) - 1)];
};
const r2 = (n) => Math.round(n * 100) / 100;

/* How long a 150 ms timer actually takes here.
 *
 * A driven benchmark runs in a background tab, and Chrome clamps setTimeout in one to
 * a second or worse. v2 debounces the title input by 150 ms; v1 debounces nothing. So
 * under a clamp the search comparison is not merely noisy, it is systematically
 * unfair to v2 -- it charges v2 for a wait the environment imposed and v1 never asks
 * for. Measuring the clamp is what lets the report say so instead of quietly
 * publishing a number that reads as v2 being slow. */
async function calibrateTimer(ms = 150, samples = 3) {
  const took = [];
  for (let i = 0; i < samples; i++) {
    const t0 = performance.now();
    await new Promise(r => setTimeout(r, ms));
    took.push(performance.now() - t0);
  }
  return r2(Math.min(...took));
}

/* ---- targets ------------------------------------------------------------ */

/* Bring-up is two-phase on purpose. The cold-load measurement is the whole point of
 * the phase split: the mutation observer has to be attached after the markup exists
 * but BEFORE the data starts arriving, or the first render happens unobserved and
 * cold load reads as zero. */
async function bringUpV1() {
  const { loadInstrumentedV1, injectV1Markup } = await import('../oracle/instrument.js');
  await injectV1Markup('/index.html', 'page');
  /* v1's init() runs the moment the patched script evaluates, so there is no seam
     between "markup exists" and "loading has started". Attaching the observer costs
     a fraction of a millisecond against a 5-second load, so the race is harmless --
     but it is a race, and v2 does not have one. */
  const provenance = await loadInstrumentedV1('/assets/js/sdv-index.js');
  const engine = await waitFor(() => window.__V1__, '__V1__');
  return {
    engine, provenance,
    ready: () => waitFor(() => {
      const p = engine.probe();
      return p.data > 0 && p.cite != null && p.gh != null;
    }, 'v1 index + both pools', 180000),
  };
}

async function bringUpV2() {
  const { App } = await import('/v2/assets/js/app.js');
  const { injectV2Markup } = await import('../oracle/adapter-v2.js');
  await injectV2Markup('page');
  const app = new App(document).mount();
  /* Deliberately not awaited: start() is the cold load, and it has to be in flight
     while the observer watches. */
  const started = app.start({ onError: (path, e) => line(`pool load failed: ${path}: ${e.message}`) });
  return {
    engine: app.adapter(),
    provenance: { target: 'v2', modules: 'v2/assets/js/*.js' },
    ready: () => started,
  };
}

/* ---- main --------------------------------------------------------------- */

async function main() {
  say('calibrating the timer');
  const timerClamp = await calibrateTimer();
  const clamped = timerClamp > 300;
  line(`a 150 ms timer takes ${timerClamp} ms here` +
       (clamped ? ` -- this tab is ${document.visibilityState}, so timers are clamped`
                : ''));

  say(`bringing up ${TARGET}`);
  const navStart = performance.now();
  const { engine, provenance, ready } = TARGET === 'v1' ? await bringUpV1() : await bringUpV2();

  const results = document.getElementById('pubs-results');
  if (!results) throw new Error('the target did not produce #pubs-results');
  const settler = makeSettler(results);
  await ready();

  /* Cold load: the page is ready when the result list first has content and stops
     growing. v1 renders the default view three times over -- once from the index and
     once per pool fetch -- and the §10 note about redundant default-floor renders is
     exactly this. */
  say('measuring cold load');
  const cold = await settler.wait(navStart, 2500, 180000);
  await sleep(500);

  corpusSize = engine.activeData ? engine.activeData().length : 0;
  const counts = engine.probe ? engine.probe() : {};
  line(`${TARGET}: cold load ${r2(cold.elapsed)} ms, ` +
       `${counts.data} curated + ${(counts.cite || 0) + (counts.gh || 0)} pool rows`);

  /* Structural observations on the settled default view. */
  const cards = results.querySelectorAll('li.pub-item');
  const uniqueRendered = new Set(
    [...cards].map((li, i) => li.getAttribute('data-record-id') || `dom-${i}`)).size;
  const structure = {
    element_nodes_default_view: results.querySelectorAll('*').length,
    cards_rendered_default_view: cards.length,
    unique_records_rendered_default_view: uniqueRendered,
    object_urls_created_during_load: probe.objectUrlsCreated,
    object_urls_revoked_during_load: probe.objectUrlsRevoked,
    raw_pool_fetches: probe.fetches
      .filter(f => /openalex-citations\.json|github-repos\.json/.test(f.url))
      .map(f => f.url.replace(location.origin, '')),
    fetches: probe.fetches.map(f => f.url.replace(location.origin, '')),
    /* Not a §9 gate, but the number the design's §1 item 9 calls out. */
    default_view_renders_during_load: cold.mutations,
  };
  line(`  ${structure.element_nodes_default_view.toLocaleString()} element nodes, ` +
       `${structure.cards_rendered_default_view.toLocaleString()} cards, ` +
       `${structure.object_urls_created_during_load.toLocaleString()} object URLs`);
  line('');

  /* Interactions. */
  const steps = script(document);
  const timings = {};
  for (const step of steps) {
    const samples = [], scanCounts = [], blobCounts = [];
    for (let rep = 0; rep < REPS; rep++) {
      /* Every wait needs its own reset. Without one the settler still holds the
         PREVIOUS step's mutation timestamp, reads it as "quiet since then", and
         returns immediately -- so the undo is never actually awaited, the next
         rep's run() lands inside the undo's 150 ms debounce and cancels it, and the
         state never moves. That measures a no-op and reports it as fast. */
      if (step.setup) {
        settler.reset();
        step.setup();
        await settler.wait(performance.now());
        await sleep(30);
      }

      const beforeBlob = probe.objectUrlsCreated;
      const beforeScans = engine.scanCount ? engine.scanCount() : filterScans;
      settler.reset();
      const t0 = performance.now();
      step.run();
      const r = await settler.wait(t0);
      samples.push(r.elapsed);
      scanCounts.push((engine.scanCount ? engine.scanCount() : filterScans) - beforeScans);
      blobCounts.push(probe.objectUrlsCreated - beforeBlob);

      settler.reset();
      step.undo();
      await settler.wait(performance.now());
      await sleep(30);
    }
    timings[step.id] = {
      why: step.why,
      /* Perceived latency: keystroke or click to the last DOM change. For a
         debounced input that includes the debounce, which is a deliberate wait
         rather than work -- debounce_ms records how much of it. v1 debounces
         nothing, so its numbers are all work. */
      debounce_ms: step.debounceMs || 0,
      /* What the reader would actually wait, minus the part of the wait that is a
         deliberate debounce inflated by the environment's timer clamp. For every
         undebounced row this is the same as median_ms. */
      median_work_ms: r2(Math.max(0, median(samples) -
        (step.debounceMs ? Math.max(step.debounceMs, timerClamp) : 0))),
      median_ms: r2(median(samples)),
      p95_ms: r2(p95(samples)),
      min_ms: r2(Math.min(...samples)),
      max_ms: r2(Math.max(...samples)),
      samples: samples.map(r2),
      corpus_scans: median(scanCounts),
      object_urls_created: Math.max(...blobCounts),
    };
    const work = timings[step.id].median_work_ms;
    line(`${step.id.padEnd(26)} median ${String(r2(median(samples))).padStart(8)} ms   ` +
         `p95 ${String(r2(p95(samples))).padStart(8)} ms   ` +
         (step.debounceMs ? `work ${String(work).padStart(7)} ms   ` : '                    ') +
         `scans ${median(scanCounts)}   objectURLs ${Math.max(...blobCounts)}`);
    window.__BENCH__.phase = step.id;
    await sleep(0);
  }

  const doc = {
    target: TARGET,
    reps: REPS,
    /* Everything a reader needs to judge whether a debounced row is comparable. */
    timer_clamp_ms: timerClamp,
    timers_clamped: clamped,
    visibility: document.visibilityState,
    scan_counter: engine.scanCount ? 'engine' : 'Array.prototype.filter (approximate)',
    corpus_size: corpusSize,
    cold_load_ms: r2(cold.elapsed),
    structure,
    timings,
    v1: provenance || null,
    user_agent: navigator.userAgent,
    viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio },
  };
  const res = await fetch(`/__sink/tests/bench/last-run-${TARGET}.json`,
    { method: 'POST', body: JSON.stringify(doc, null, 1) });
  if (!res.ok) throw new Error(`sink refused the run: HTTP ${res.status}`);

  window.__BENCH__.done = true;
  window.__BENCH__.doc = doc;
  say(`DONE (${TARGET}): ${Object.keys(timings).length} interactions, ${REPS} reps each`);
}

main().catch(e => {
  window.__BENCH__.error = String(e && e.stack || e);
  say('ERROR: ' + e.message);
  line(String(e && e.stack || e));
});
