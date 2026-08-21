/* Sorting and grouping.
 *
 * The comparators are v1's, deliberately unchanged down to the use of localeCompare
 * with no locale argument. The ordering half of the differential compares 293 states
 * of ordered ids; switching to a fixed collation here would fail most of them for
 * reasons that have nothing to do with the redesign. If collation is ever worth
 * pinning it is its own change, with its own golden regeneration.
 */
import { KIND_LABELS, KIND_ORDER, labelFor, prettify } from './vocab.js';

const SIZE_ORDERED = ['sdv_component', 'sdv_concept', 'use_case', 'industry', 'integration'];

export function sortWithin(arr, key) {
  arr.sort((na, nb) => {
    const a = na.rec, b = nb.rec;
    if (key === 'title') {
      return (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase());
    }
    /* The two orderings are each other's tie-break. Ties are common in both: entries
       with no attention signal share the neutral default, and thousands of pooled
       repositories sit at identical low scores. Unrated entries sort as -1, below 0. */
    const ia = na.importance !== null ? na.importance : -1;
    const ib = nb.importance !== null ? nb.importance : -1;
    if (key === 'popularity') {
      const dp = nb.pop - na.pop;
      if (dp) return dp;
      if (ib !== ia) return ib - ia;
    }
    if (key === 'importance') {
      if (ib !== ia) return ib - ia;
      const dq = nb.pop - na.pop;
      if (dq) return dq;
    }
    const dy = (b.year || 0) - (a.year || 0);
    if (dy) return dy;
    return (a.title || '').toLowerCase().localeCompare((b.title || '').toLowerCase());
  });
  return arr;
}

export function groupHeadersFor(n, group) {
  const rec = n.rec;
  if (group === 'none') return [''];
  if (group === 'kind') return [KIND_LABELS[rec.kind] || prettify(rec.kind)];
  if (group === 'year') return [rec.year ? String(rec.year) : 'Undated'];
  if (group === 'confidence') return [rec.confidence ? prettify(rec.confidence) : 'Unrated'];
  const vals = n.vals[group];
  if (!vals.length) return ['Other'];
  return vals.map(v => labelFor(group, v));
}

export function headerOrder(headers, group) {
  if (group === 'kind') {
    const rank = {};
    KIND_ORDER.forEach((k, i) => { rank[KIND_LABELS[k]] = i; });
    return headers.sort((A, B) => {
      const ra = rank[A] == null ? 99 : rank[A], rb = rank[B] == null ? 99 : rank[B];
      return ra !== rb ? ra - rb : A.localeCompare(B);
    });
  }
  if (group === 'year') {
    return headers.sort((A, B) => {
      if (A === 'Undated') return 1;
      if (B === 'Undated') return -1;
      return (parseInt(B, 10) || 0) - (parseInt(A, 10) || 0);
    });
  }
  if (group === 'confidence') {
    const cr = { High: 3, Medium: 2, Low: 1, Unrated: 0 };
    return headers.sort((A, B) => (cr[B] || 0) - (cr[A] || 0));
  }
  return headers;   // component/concept/use_case/industry: insertion order, by size
}

/* Grouping under the page limit (design v2 §3 item 8).
 *
 * "Sort the full unique result set first; render the first N unique records; place
 * those records into every applicable group. Group headers show visible / total."
 *
 * The two counts are genuinely different numbers and the order of operations is the
 * whole specification: grouping first and then limiting would render up to N records
 * PER GROUP, which is how a 100-record cap turns back into two thousand cards.
 *
 * Header order uses TOTAL sizes, not visible ones, so that pressing "show more" does
 * not reshuffle the sections under the reader.
 */
export function groupPlan(sortedResults, visible, group) {
  const totals = new Map();
  const order = [];
  for (const n of sortedResults) {
    for (const h of groupHeadersFor(n, group)) {
      if (!totals.has(h)) { totals.set(h, 0); order.push(h); }
      totals.set(h, totals.get(h) + 1);
    }
  }
  const members = new Map();
  for (const n of visible) {
    for (const h of groupHeadersFor(n, group)) {
      if (!members.has(h)) members.set(h, []);
      members.get(h).push(n);
    }
  }
  if (SIZE_ORDERED.indexOf(group) >= 0) {
    order.sort((A, B) => (totals.get(B) - totals.get(A)) || A.localeCompare(B));
  }
  return headerOrder(order, group).map(h => ({
    heading: h,
    total: totals.get(h),
    records: members.get(h) || [],
  }));
}
