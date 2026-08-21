/* The v2 controller.
 *
 * Exported as a class rather than run on import, so the oracle adapter and the
 * benchmark can build one against a mount of their choosing and drive it directly.
 * main.js is the two lines that start it on the real page.
 */
import {
  Corpus, loadAll, dedupeTail, normalizeCite, normalizeGh,
  curatedUrlSet, notCurated,
} from './data.js';
import { Engine, countValues } from './engine.js';
import { sortWithin, groupHeadersFor, headerOrder } from './order.js';
import { renderResults, syncNeeds, PAGE } from './render.js';
import {
  freshState, allOn, rebuildFacets, buildCheckboxFacet, makeScheduler, makeDebounce,
  FACET_KEYS, AFF_GROUPS,
} from './state.js';

const IMPORTANCE_STEPS = [
  'All entries',
  '1+ — passing mention and up',
  '2+ — contextual and up',
  '3+ — one of several and up',
  '4+ — load-bearing and up',
  '5+ — SDV is the work',
  '6 — first-party only',
];

const popularityLabel = (v) => (v ? 'Top ' + (100 - v) + '% by attention' : 'All entries');

export class App {
  constructor(root = document) {
    this.root = root;
    this.corpus = new Corpus();
    this.engine = new Engine(this.corpus);
    this.state = freshState();
    this.byId = new Map();
    this.affFieldsPresent = false;
    this.els = {};
    this.schedule = makeScheduler(() => this.apply());
  }

  $(id) {
    return this.root.getElementById
      ? this.root.getElementById(id)
      : this.root.querySelector('#' + id);
  }

  mount() {
    const $ = (id) => this.$(id);
    this.els = {
      errors: $('pubs-errors'), results: $('pubs-results'), count: $('pubs-count'),
      title: $('facet-title'), authorSearch: $('author-search'),
      affiliations: $('facet-affiliations'),
      affTypeToggles: $('facet-aff-type-toggles'),
      affRegionToggles: $('facet-aff-region-toggles'),
      kind: $('facet-kind'), sdv_component: $('facet-component'),
      sdv_concept: $('facet-concept'), use_case: $('facet-usecase'),
      integration: $('facet-integration'), industry: $('facet-industry'),
      authors: $('facet-authors'), year: $('facet-years'),
      sortGroup: $('sort-group'), sortWithin: $('sort-within'),
      btnNeeds: $('btn-toggle-needs'), btnSummaries: $('btn-toggle-summaries'),
      btnClear: $('btn-clear'),
      minImportance: $('min-importance'), minImportanceLabel: $('min-importance-label'),
      importanceTicks: $('importance-ticks'),
      minPopularity: $('min-popularity'), minPopularityLabel: $('min-popularity-label'),
    };
    this.wire();
    return this;
  }

  /* ---- state changes ----------------------------------------------------- */

  /* §3 item 8: any filter, grouping or sort change resets N to 100. Routing every
     one of them through here makes that true by construction rather than by
     remembering to do it in eight separate handlers. */
  changed() {
    this.state.limit = PAGE;
    this.schedule();
  }

  showMore(all) {
    this.state.limit = all ? Infinity : this.state.limit + PAGE;
    this.schedule();
  }

  wire() {
    const s = this.state, els = this.els;

    /* The one input a reader holds down a key in. 150 ms, per §6. */
    const applyTitle = makeDebounce((v) => { s.titleQuery = v; this.changed(); }, 150);
    els.title.addEventListener('input', (e) => applyTitle(e.target.value));

    /* Typing in the author box narrows the LIST, not the results, so it needs no
       corpus walk and goes straight to the one facet. */
    els.authorSearch.addEventListener('input', (e) => {
      s.facetQuery.authors = e.target.value;
      this.rebuildOne('authors');
    });

    els.minImportance.max = '6';
    this.buildStopMarks(els.minImportance, els.importanceTicks);
    els.minImportance.addEventListener('input', (e) => {
      s.minImportance = parseInt(e.target.value, 10) || 0;
      /* The label is written now, in the handler; only the corpus walk waits for a
         frame. Dragging must feel continuous while the work behind it coalesces. */
      els.minImportanceLabel.textContent = IMPORTANCE_STEPS[s.minImportance] || 'All entries';
      this.changed();
    });
    els.minImportanceLabel.textContent = IMPORTANCE_STEPS[s.minImportance];

    els.minPopularity.addEventListener('input', (e) => {
      s.minPopularity = parseInt(e.target.value, 10) || 0;
      els.minPopularityLabel.textContent = popularityLabel(s.minPopularity);
      this.changed();
    });
    els.minPopularityLabel.textContent = popularityLabel(s.minPopularity);

    /* Grouping and sorting change what is on the page, so they reset the page limit
       too -- otherwise a narrow grouping inherits a wide page. */
    els.sortGroup.addEventListener('change', (e) => {
      s.group = e.target.value;
      this.changed();
    });
    els.sortWithin.addEventListener('change', (e) => {
      s.sortWithin = e.target.value;
      this.changed();
    });

    if (els.btnNeeds) els.btnNeeds.addEventListener('click', () => {
      s.showNeeds = !s.showNeeds;
      els.btnNeeds.setAttribute('aria-pressed', String(s.showNeeds));
      els.btnNeeds.textContent = s.showNeeds ? 'Hide open questions' : 'Show open questions';
      /* Operates on what is rendered, per §3 item 9 -- no walk, no re-render. */
      syncNeeds(els.results, this.byId, s.showNeeds);
    });

    els.btnSummaries.addEventListener('click', () => {
      s.summaryExpanded = !s.summaryExpanded;
      els.btnSummaries.setAttribute('aria-pressed', String(s.summaryExpanded));
      els.btnSummaries.textContent = s.summaryExpanded ? 'Hide summaries' : 'Show summaries';
      /* Also §3 item 9: currently rendered records only. The cards are rebuilt but
         the corpus is not rewalked -- the engine sees an unchanged signature and
         hands back the same snapshot. */
      this.schedule();
    });

    els.btnClear.addEventListener('click', () => {
      for (const fk of FACET_KEYS) s.sel[fk] = {};
      s.sel.aff_type = allOn(AFF_GROUPS[0]);
      s.sel.aff_region = allOn(AFF_GROUPS[1]);
      s.titleQuery = ''; s.facetQuery = { authors: '' };
      els.title.value = ''; els.authorSearch.value = '';
      s.minImportance = 1; els.minImportance.value = '1';
      els.minImportanceLabel.textContent = IMPORTANCE_STEPS[1];
      s.minPopularity = 0; els.minPopularity.value = '0';
      els.minPopularityLabel.textContent = popularityLabel(0);
      this.changed();
    });
  }

  /* The importance slider has 7 discrete stops and nothing in its native rendering
     says so. One mark per step, read off the input's own min/max/step. */
  buildStopMarks(input, mount) {
    if (!input || !mount) return;
    const min = parseFloat(input.min), max = parseFloat(input.max);
    const step = parseFloat(input.step);
    if (!(step > 0) || !(max > min)) return;
    const n = Math.round((max - min) / step);
    const frag = document.createDocumentFragment();
    for (let i = 0; i <= n; i++) {
      const sp = document.createElement('span');
      sp.className = 'slider-tick' + (i === 0 || i === n ? ' tick-end' : '');
      frag.appendChild(sp);
    }
    mount.replaceChildren(frag);
  }

  /* ---- the pass ---------------------------------------------------------- */

  facetCtx(counts) {
    return {
      els: this.els, state: this.state, counts,
      universe: this.corpus.universe,
      affFieldsPresent: this.affFieldsPresent,
      onFilterChange: () => this.changed(),
    };
  }

  rebuildOne(facet) {
    buildCheckboxFacet(facet, this.facetCtx(this.engine.snapshot(this.state).counts));
  }

  /* One corpus walk, then everything downstream reads the same snapshot. §6: "the
     filtered snapshot is computed once and passed to count rendering and card
     rendering." */
  apply() {
    const snap = this.engine.snapshot(this.state);
    rebuildFacets(this.facetCtx(snap.counts));

    const sorted = sortWithin(snap.results.slice(), this.state.sortWithin);
    renderResults(this.els.results, sorted, this.state, {
      summaryExpanded: this.state.summaryExpanded,
      showNeeds: this.state.showNeeds,
      onMore: () => this.showMore(false),
      onAll: () => this.showMore(true),
      onChip: (facet, value) => { this.state.sel[facet][value] = true; this.changed(); },
    });
    this.els.results.classList.toggle('show-needs', this.state.showNeeds);
    this.els.count.textContent = '(' + snap.results.length + ')';
  }

  /* ---- corpus ------------------------------------------------------------ */

  setCorpus(curated, cite, gh) {
    this.corpus.set(curated, cite, gh);
    this.engine.invalidate();
    this.byId = new Map(this.corpus.records.map(n => [String(n.id), n]));
    this.affFieldsPresent = this.corpus.records.some(
      n => n.rec.affiliation_types || n.rec.affiliation_countries);
    return this;
  }

  /* Takes the pools in their stored shape and runs them through dedupe,
     normalization and alias suppression -- the same path loadAll takes. The semantic
     fixture is swapped in through here so those steps are exercised for real. */
  setCorpusRaw(curated, rawCite, rawGh) {
    const map = curatedUrlSet(curated || []);
    const cite = rawCite
      ? dedupeTail(rawCite).map(normalizeCite).filter(r => notCurated(map, r)) : null;
    const gh = rawGh
      ? ((rawGh && rawGh.repos) || rawGh || []).map(normalizeGh)
        .filter(r => notCurated(map, r)) : null;
    return this.setCorpus(curated, cite, gh);
  }

  /* Pool rows are unrated, so at any importance floor above 0 none of them can pass
     -- and the default floor is 1. The one thing they can still move at a higher
     floor is the popularity percentile, which is taken over the whole active corpus.
     So the cards need rebuilding only in those two cases; otherwise the arriving
     pools change nothing but the facet vocabulary.
     v1 re-renders the whole default view once per pool regardless (§1 item 9). */
  poolsCanChangeResults() {
    return this.state.minImportance === 0 || this.state.minPopularity > 0;
  }

  async start({ onError } = {}) {
    const fail = onError || ((path, e) => {
      if (this.els.errors) this.els.errors.textContent = `Could not load ${path}: ${e.message}`;
    });
    try {
      await loadAll({
        onIndex: (curated) => {
          this.setCorpus(curated, null, null);
          this.apply();
        },
        onPools: (cite, gh) => {
          const needCards = this.poolsCanChangeResults();
          this.setCorpus(this.corpus.curated, cite, gh);
          if (needCards) {
            this.apply();
          } else {
            /* Facet lists still gain the pool's values, at count zero, exactly as in
               v1 -- but no card is rebuilt. */
            rebuildFacets(this.facetCtx(this.engine.snapshot(this.state).counts));
          }
        },
        onError: fail,
      });
    } catch (e) {
      if (this.els.errors) {
        this.els.errors.textContent =
          `Could not load the index: ${e.message}. Serve over HTTP, not the file:// scheme.`;
      }
    }
    return this;
  }

  /* ---- the interface the oracle and the semantic runner drive ------------- */

  /* Deliberately thin. Every method delegates to the same code the page runs, so the
     differential measures the shipped engine rather than a test-only sibling of it. */
  adapter() {
    const app = this;
    return {
      state: this.state,
      FACET_KEYS,
      get UNIVERSE() { return app.corpus.universe; },
      activeData: () => app.corpus.records,
      filteredData: (exclude) => {
        const snap = app.engine.snapshot(app.state);
        return exclude ? snap.excluded[exclude] : snap.results;
      },
      countValues,
      sortWithin: (arr) => sortWithin(arr, app.state.sortWithin),
      groupHeadersFor: (n) => groupHeadersFor(n, app.state.group),
      headerOrder: (h) => headerOrder(h, app.state.group),
      valuesOf: (n, facet) => n.vals[facet],
      organizationsOf: (n) => n.organizations,
      popularity: (n) => n.pop,
      /* v1 recomputes the universe on demand; here it is rebuilt whenever the corpus
         is set, so there is nothing to do and nothing that can be stale. */
      computeUniverse: () => {},
      scanCount: () => app.engine.scanCount(),
      probe: () => app.corpus.probe(),
      setCorpus: (curated, rawCite, rawGh) => app.setCorpusRaw(curated, rawCite, rawGh),
    };
  }
}
