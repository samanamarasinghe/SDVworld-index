/* State, the facet panel, and input coalescing.
 *
 * v1 calls applyFilters() straight out of every event handler, and applyFilters()
 * walks the corpus thirteen times. Dragging the importance slider from 0 to 6 fires
 * seven input events and pays for all of them. Here every path funnels into
 * schedule(), which does the work at most once per animation frame, and the title
 * input is debounced on top of that.
 */
import {
  FACET_KEYS, MOUNTS, SEARCHABLE, AFF_GROUPS, AFF_LABELS, CONF_RANK,
  NONE, labelFor,
} from './vocab.js';

export function allOn(group) {
  const m = {};
  for (const v of group.values) m[v] = true;
  return m;
}

export function freshState() {
  return {
    titleQuery: '',
    facetQuery: { authors: '' },
    sel: {
      kind: {}, sdv_concept: {}, sdv_component: {}, use_case: {}, integration: {},
      industry: {}, authors: {}, affiliations: {}, year: {},
      aff_type: allOn(AFF_GROUPS[0]), aff_region: allOn(AFF_GROUPS[1]),
    },
    group: 'none',
    sortWithin: 'importance',
    minImportance: 1,
    minPopularity: 0,
    summaryExpanded: false,
    showNeeds: false,
    /* §3 item 8: unique records rendered. Reset to PAGE by any filter, grouping or
       sort change -- see resetPage's callers. */
    limit: 100,
  };
}

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.appendChild(document.createTextNode(txt));
  return e;
}

/* ---- the facet panel ----------------------------------------------------- */

/* Faithful to v1's buildCheckboxFacet, including the sort orders, the 200-value cap
 * on searchable facets, the header count, and the rule that keeps a selected
 * zero-count value visible so it can still be cleared. The counts come from the
 * single walk rather than from a walk per facet. */
export function buildCheckboxFacet(facet, ctx) {
  const mount = ctx.els[facet];
  if (!mount) return;
  const state = ctx.state;
  const counts = ctx.counts[facet] || new Map();
  const get = (v) => counts.get(v) || 0;
  let values = (ctx.universe[facet] || []).slice();
  let truncated = false;

  /* Header count: how many values this facet still offers in the current view.
     Computed before the search filter and the cap, so it stays the denominator. */
  let active = 0;
  for (const [, n] of counts) if (n) active++;

  /* A region/type choice should show only organizations on that side of the split.
     Keep an already-selected zero-count item so it can still be cleared. */
  if (facet === 'affiliations' || facet === 'authors') {
    values = values.filter(v => get(v) || state.sel[facet][v]);
  }

  if (facet === 'confidence') {
    values.sort((a, b) => (CONF_RANK[b] || 0) - (CONF_RANK[a] || 0));
  } else if (SEARCHABLE[facet]) {
    const q = (state.facetQuery[facet] || '').trim().toLowerCase();
    if (q) values = values.filter(v => v.toLowerCase().indexOf(q) >= 0);
    values.sort((a, b) => (get(b) - get(a)) || a.localeCompare(b));
    truncated = !q && values.length > 200;
    if (truncated) values = values.slice(0, 200);
  } else {
    values.sort((a, b) => {
      // Not specified sorts last however common: an absence, not a popular answer.
      if (a === NONE) return 1;
      if (b === NONE) return -1;
      return (get(b) - get(a)) ||
        labelFor(facet, a).localeCompare(labelFor(facet, b));
    });
  }

  const block = mount.parentNode;
  const label = block && block.querySelector('.filter-label');
  if (label) {
    let tag = label.querySelector('.facet-count');
    if (!tag) {
      tag = el('span', 'facet-count', '');
      const hint = label.querySelector('.hint');
      if (hint) label.insertBefore(tag, hint); else label.appendChild(tag);
    }
    tag.textContent = truncated ? ' (top ' + values.length + ' of ' + active + ')'
      : values.length < active ? ' (' + values.length + ' of ' + active + ')'
        : ' (' + active + ')';
  }

  const wrap = el('div', 'facet-scroll');
  const list = el('div', 'facet-items');
  for (const v of values) {
    const n = get(v), on = !!state.sel[facet][v];
    const item = el('label', 'facet-item' + (n === 0 && !on ? ' disabled' : ''));
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.value = v; cb.checked = on;
    cb.addEventListener('change', function () {
      state.sel[facet][v] = this.checked;
      ctx.onFilterChange();
    });
    item.appendChild(cb);
    if (facet === 'confidence') item.appendChild(el('span', 'conf-dot conf-' + v));
    const txt = el('span', 'facet-text', labelFor(facet, v) + ' (' + n + ')');
    txt.title = labelFor(facet, v);
    item.appendChild(txt);
    list.appendChild(item);
  }
  wrap.appendChild(list);
  mount.replaceChildren(wrap);
}

const plainLabel = (v) => String(AFF_LABELS[v] || v).replace(/\s*\n\s*/g, ' ');

export function buildAffToggles(ctx) {
  const state = ctx.state;
  for (const grp of AFF_GROUPS) {
    const mount = ctx.els[grp.mount];
    if (!mount) continue;
    if (!ctx.affFieldsPresent) { mount.replaceChildren(); continue; }
    const counts = ctx.counts[grp.facet] || new Map();
    const group = el('div', 'aff-group');
    for (const v of grp.values) {
      const on = !!state.sel[grp.facet][v];
      const n = counts.get(v) || 0;
      const btn = el('button', 'aff-btn' + (on ? ' active' : ''));
      btn.type = 'button';
      btn.title = on
        ? 'Allowing ' + plainLabel(v) + ': ' + n + ' entries'
        : 'Excluding every entry ' + (v === 'unaffiliated'
          ? 'with no affiliation on record'
          : 'with any ' + plainLabel(v) + ' organization');
      btn.setAttribute('aria-pressed', String(on));
      btn.appendChild(el('span', 'aff-label', AFF_LABELS[v]));
      btn.appendChild(el('span', 'aff-badge', String(n)));
      btn.addEventListener('click', () => toggleAff(state, grp, v, ctx.onFilterChange));
      group.appendChild(btn);
    }
    mount.replaceChildren(group);
  }
}

/* A plain toggle with a floor: off lights, on unlights, and a group is never left
   empty because an empty group would show nothing at all. */
export function toggleAff(state, grp, v, done) {
  const sel = state.sel[grp.facet];
  if (!sel[v]) { sel[v] = true; done(); return; }
  sel[v] = false;
  let any = false;
  for (const x of grp.values) if (sel[x]) any = true;
  if (!any) {
    for (const x of grp.values) if (grp.onEmpty === 'all' || x !== v) sel[x] = true;
  }
  done();
}

export function buildYearGrid(ctx) {
  const mount = ctx.els.year;
  if (!mount) return;
  const state = ctx.state;
  const counts = ctx.counts.year || new Map();
  /* Undated sorts last however many entries it holds -- it is an absence, not a
     year. Left to parseInt it compares as NaN and lands wherever the sort puts it. */
  const years = (ctx.universe.year || []).slice().sort((a, b) => {
    if (a === NONE) return 1;
    if (b === NONE) return -1;
    return parseInt(b, 10) - parseInt(a, 10);
  });
  const frag = document.createDocumentFragment();
  for (const y of years) {
    const n = counts.get(y) || 0, on = !!state.sel.year[y];
    const btn = el('button', 'year-btn' + (on ? ' active' : ''));
    btn.type = 'button';
    btn.title = y === NONE ? 'Entries with no year on record' : '';
    btn.setAttribute('aria-pressed', String(on));
    btn.appendChild(document.createTextNode(labelFor('year', y) + ' '));
    btn.appendChild(el('span', 'year-badge', String(n)));
    btn.addEventListener('click', () => {
      state.sel.year[y] = !state.sel.year[y];
      ctx.onFilterChange();
    });
    frag.appendChild(btn);
  }
  mount.replaceChildren(frag);
}

export function rebuildFacets(ctx) {
  for (const f of ['kind', 'sdv_component', 'sdv_concept', 'use_case', 'integration',
    'industry', 'authors', 'affiliations']) {
    buildCheckboxFacet(f, ctx);
  }
  buildAffToggles(ctx);
  buildYearGrid(ctx);
}

/* ---- coalescing ---------------------------------------------------------- */

/* A frame-aligned tick that still ticks in a background tab.
 *
 * requestAnimationFrame is the right clock for coalescing work that ends in a paint,
 * and it is what §6 asks for. But a hidden tab stops firing it entirely, which would
 * leave a state change that arrived while the tab was backgrounded sitting unapplied
 * until the reader came back -- and would hang any harness driving the page from a
 * tab that is not in front. A MessageChannel task is not throttled, so it stands in
 * while the document is hidden. Rendering into a hidden document costs no paint. */
const chan = typeof MessageChannel === 'function' ? new MessageChannel() : null;
let waiting = [];
if (chan) {
  chan.port1.onmessage = () => { const w = waiting; waiting = []; for (const f of w) f(); };
}
export function nextTick(fn) {
  let ran = false;
  const run = () => { if (!ran) { ran = true; fn(); } };
  if (document.visibilityState === 'visible' || !chan) {
    requestAnimationFrame(run);
    /* rAF stops the instant the tab is hidden, so a frame requested just before the
       reader switched away never arrives and the pending pass is stranded until they
       come back. Racing a channel task instead would fix that but would also break
       the coalescing this exists for -- separate input events land in separate tasks,
       and only a frame gathers them into one pass. So keep the frame, and let a
       visibility change release the work if the frame is not going to come. */
    document.addEventListener('visibilitychange', run, { once: true });
  } else {
    waiting.push(run);
    chan.port2.postMessage(0);
  }
}

/* One scheduled pass per tick, however many events arrived. The design asks for
 * "slider labels update immediately but filter work coalesces to at most one
 * requestAnimationFrame callback" (§6) -- so labels are written by the handler and
 * only the expensive half comes through here. */
export function makeScheduler(work) {
  let queued = false;
  return function schedule() {
    if (queued) return;
    queued = true;
    nextTick(() => { queued = false; work(); });
  };
}

export function makeDebounce(fn, ms) {
  let t = 0;
  return function (...a) {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

export { FACET_KEYS, MOUNTS, AFF_GROUPS };
