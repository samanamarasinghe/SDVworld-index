/* Enumeration of the characterization states (design v2 §8).
 *
 * Every state is derived deterministically from the pinned corpus -- sorted
 * vocabularies, sorted frequency samples, no randomness -- so two runs against the
 * same data produce the same list in the same order.
 */

export const BOUNDED = ['kind', 'sdv_component', 'sdv_concept', 'use_case',
  'integration', 'industry', 'year'];
export const GROUPS = ['none', 'kind', 'year', 'sdv_component', 'sdv_concept',
  'use_case', 'industry'];
export const SORTS = ['popularity', 'importance', 'year', 'title'];
export const AFF_TYPES = ['academic', 'non_academic', 'unaffiliated'];
export const AFF_REGIONS = ['americas', 'europe', 'asia', 'africa_oceania'];

/* The default UI state, per §3 item 2. Every spec below is a delta from this. */
export const DEFAULT = {
  titleQuery: '', minImportance: 1, minPopularity: 0,
  group: 'none', sortWithin: 'importance', sel: {},
  aff: { aff_type: AFF_TYPES, aff_region: AFF_REGIONS },
};

function st(id, label, over) {
  return Object.assign({ id, label }, DEFAULT, over || {});
}

/* Deterministic high/mid/low-frequency sample of an unbounded vocabulary. Sorting
 * by count descending then by name breaks every tie by name, so the pick cannot
 * move when two values share a count. */
function frequencySample(counts, n) {
  const ranked = Object.keys(counts)
    .sort((a, b) => (counts[b] - counts[a]) || a.localeCompare(b));
  if (!ranked.length) return { high: [], mid: [], low: [] };
  const midStart = Math.max(0, Math.floor(ranked.length / 2) - Math.floor(n / 2));
  return {
    high: ranked.slice(0, n),
    mid: ranked.slice(midStart, midStart + n),
    low: ranked.slice(-n),
  };
}

/* §4/§8: the searches that must be frozen. Partial words, multiword queries,
 * punctuation, case, non-ASCII and a guaranteed miss -- these are the states the
 * planned search change will legitimately move, and they are the documented
 * exceptions, so they have to be recorded precisely before anything changes. */
const SEARCHES = ['h', 'he', 'health', 'healthcare', 'Health', ' health ', 'synth',
  'synthetic data', 'privacy', 'differential privacy', 'ctgan', 'CTGAN', 'sdv',
  'tabular', 'time-series', 'time series', 'GAN', 'C++', 'covid-19', 'naïve',
  'Müller', 'Zhang', 'multi word no match', 'zzzznomatch'];

export function enumerate(V1) {
  const U = V1.UNIVERSE;
  const all = V1.activeData();
  const out = [];

  // -- every importance stop.
  for (let i = 0; i <= 6; i++) out.push(st(`imp-${i}`, `importance ${i}`, { minImportance: i }));

  // -- every popularity stop (the slider is 0..95 step 5).
  for (let p = 0; p <= 95; p += 5) {
    out.push(st(`pop-${p}`, `popularity ${p}`, { minPopularity: p }));
  }
  out.push(st('imp-4-pop-50', 'importance 4 + popularity 50',
    { minImportance: 4, minPopularity: 50 }));
  out.push(st('imp-0-search-health', 'importance 0 + "health"',
    { minImportance: 0, titleQuery: 'health' }));

  // -- every value of every bounded facet, singly, at the default floor.
  for (const f of BOUNDED) {
    for (const v of (U[f] || []).slice().sort()) {
      out.push(st(`one:${f}:${v}`, `${f} = ${v}`, { sel: { [f]: [v] } }));
    }
  }

  // -- unbounded vocabularies: a high/mid/low-frequency sample plus a value that
  //    cannot match, since "no results" is its own code path.
  for (const f of ['authors', 'affiliations']) {
    const counts = V1.countValues(all, f);
    const s = frequencySample(counts, 3);
    for (const band of ['high', 'mid', 'low']) {
      s[band].forEach((v, i) => out.push(
        st(`sample:${f}:${band}${i}`, `${f} = ${v} (${band}-frequency)`,
           { sel: { [f]: [v] }, minImportance: 0 })));
    }
    out.push(st(`sample:${f}:absent`, `${f} = a value not in the corpus`,
      { sel: { [f]: ['  no such value'] }, minImportance: 0 }));
  }

  // -- cross-facet pairs. The top three values of each bounded facet, combined
  //    across every facet pair, gives well over the fifty §8 asks for; the list is
  //    truncated deterministically and half of it runs at importance 0 so pool rows
  //    are exercised under facets too.
  const top = {};
  for (const f of BOUNDED) {
    const c = V1.countValues(all, f);
    top[f] = Object.keys(c).sort((a, b) => (c[b] - c[a]) || a.localeCompare(b)).slice(0, 3);
  }
  let pairIdx = 0;
  outer:
  for (let i = 0; i < BOUNDED.length; i++) {
    for (let j = i + 1; j < BOUNDED.length; j++) {
      const fa = BOUNDED[i], fb = BOUNDED[j];
      for (let k = 0; k < 3 && k < top[fa].length && k < top[fb].length; k++) {
        if (pairIdx >= 63) break outer;
        const floor = pairIdx % 2 ? 0 : 1;
        out.push(st(`pair-${pairIdx}`, `${fa}=${top[fa][k]} + ${fb}=${top[fb][k]} @imp${floor}`,
          { sel: { [fa]: [top[fa][k]], [fb]: [top[fb][k]] }, minImportance: floor }));
        pairIdx++;
      }
    }
  }
  // -- OR within one facet, which no single-value state can distinguish from AND.
  for (const f of BOUNDED) {
    if (top[f].length >= 2) {
      out.push(st(`or:${f}`, `${f} = ${top[f][0]} OR ${top[f][1]}`,
        { sel: { [f]: top[f].slice(0, 2) } }));
    }
  }

  // -- searches (§4 frozen examples).
  SEARCHES.forEach((q, i) => out.push(
    st(`search-${String(i).padStart(2, '0')}`, `search ${JSON.stringify(q)}`,
       { titleQuery: q })));

  // -- every grouping against every sort.
  for (const g of GROUPS) {
    for (const s of SORTS) {
      out.push(st(`group:${g}:sort:${s}`, `group ${g}, sort ${s}`,
        { group: g, sortWithin: s }));
    }
  }

  // -- affiliation permission groups: each button dark alone, each button the only
  //    one lit, and cross-group combinations. The empty-group floor in toggleAff is
  //    a UI rule, so these set the resulting lit sets directly.
  for (const v of AFF_TYPES) {
    out.push(st(`aff:type:off:${v}`, `aff_type without ${v}`,
      { aff: { aff_type: AFF_TYPES.filter(x => x !== v), aff_region: AFF_REGIONS } }));
    out.push(st(`aff:type:only:${v}`, `aff_type only ${v}`,
      { aff: { aff_type: [v], aff_region: AFF_REGIONS } }));
  }
  for (const v of AFF_REGIONS) {
    out.push(st(`aff:region:off:${v}`, `aff_region without ${v}`,
      { aff: { aff_type: AFF_TYPES, aff_region: AFF_REGIONS.filter(x => x !== v) } }));
    out.push(st(`aff:region:only:${v}`, `aff_region only ${v}`,
      { aff: { aff_type: AFF_TYPES, aff_region: [v] } }));
  }
  const combos = [
    [['academic'], ['europe']],
    [['academic'], ['americas', 'europe']],
    [['non_academic'], ['asia']],
    [['academic', 'non_academic'], ['africa_oceania']],
    [['unaffiliated'], AFF_REGIONS],
    [['academic'], AFF_REGIONS.filter(r => r !== 'americas')],
  ];
  combos.forEach(([t, r], i) => out.push(
    st(`aff:combo-${i}`, `aff_type ${t.join('+')} by aff_region ${r.join('+')}`,
       { aff: { aff_type: t, aff_region: r }, minImportance: 0 })));

  // -- the §8 sanity checkpoints, named so a failure reads plainly.
  out.push(st('check:default', 'checkpoint: default view', {}));
  out.push(st('check:imp0', 'checkpoint: importance 0', { minImportance: 0 }));
  out.push(st('check:imp4', 'checkpoint: importance 4', { minImportance: 4 }));

  const seen = new Set();
  for (const s of out) {
    if (seen.has(s.id)) throw new Error('duplicate state id: ' + s.id);
    seen.add(s.id);
  }
  return out;
}

/* The §8 checkpoints, asserted before anything is written. If these move, the corpus
 * is not describing the baseline the design was approved against. */
export const CHECKPOINTS = {
  'check:default': 4703,
  'check:imp0': 4962,
  'check:imp4': 1543,
  'imp-4-pop-50': 846,
  'imp-0-search-health': 389,
};
