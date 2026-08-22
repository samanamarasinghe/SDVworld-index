/* The filter and count engine: one corpus walk per interaction (design v2 §6).
 *
 * v1 walks the corpus thirteen times for a single click -- once for the result list,
 * once for the header count, and once per facet for its self-excluding count -- and
 * each walk re-sorts the whole corpus to find the popularity floor. Measured: 523 ms
 * to 3.4 s per interaction.
 *
 * Here one walk computes a failure MASK per record. Bit F is set when the record
 * fails facet F. Mask zero means the record is in the result set. The record
 * contributes to facet F's self-excluding count when clearing F's own bit leaves the
 * mask empty -- `(mask & ~bit(F)) === 0` -- which is precisely "passes everything
 * except F", the thing v1 computed with a separate walk each time.
 *
 * The design (§5 item 5) says ordinary arrays and masks should meet budget at this
 * corpus size, and that Uint32Array bitsets are a measured follow-on rather than a
 * starting design. They are not used here.
 */
import { FACET_KEYS, NO_NONE } from './vocab.js';
import { fold } from './search.js';

/* Which facets veto rather than select. A checkbox facet asks whether ANY value the
   record carries was ticked; a button group asks whether EVERY value it carries is
   still lit. */
const PERMIT = { aff_type: 1, aff_region: 1 };

/* Facets whose counts are rendered. All of them, as it happens -- nine checkbox
   lists plus the two button groups -- but naming it separately keeps the walk honest
   about what work it is doing. */
const COUNTED = FACET_KEYS;

export class Engine {
  constructor(corpus) {
    this.corpus = corpus;
    this.postings = null;
    this._cache = null;
    this._signature = null;
    this._scans = 0;
  }

  /* Incremented once per actual corpus walk. §6's "no function calls the filter
     engine independently" is otherwise an intention rather than a fact; the
     benchmark reads this and tests/gates.py fails the build above one per
     interaction. */
  scanCount() { return this._scans; }

  invalidate() { this._cache = null; this._signature = null; }

  /* State changes arrive from several places -- a debounced input, a slider, a
     checkbox, the adapter used by the oracle -- and every one of them may ask for
     the snapshot more than once. Keying the cache on the state itself means the walk
     happens when the state actually moved and not otherwise. */
  static signature(state) {
    const sel = {};
    for (const f of FACET_KEYS) {
      const on = [];
      for (const k in state.sel[f]) if (state.sel[f][k]) on.push(k);
      if (on.length) sel[f] = on.sort();
    }
    return JSON.stringify([state.titleQuery.replace(/\s+/g, ' ').trim().toLowerCase(),
      !!state.searchSummaries, state.minImportance, state.minPopularity, sel]);
  }

  snapshot(state) {
    const sig = Engine.signature(state);
    if (this._cache && this._signature === sig) return this._cache;
    this._signature = sig;
    this._cache = this._walk(state);
    return this._cache;
  }

  _walk(state) {
    this._scans++;
    const { records } = this.corpus;
    const rawQuery = state.titleQuery.replace(/\s+/g, ' ').trim();
    /* Summaries mode resolves the whole query up front, to a set of record indices,
       so the corpus walk below stays one cheap membership test per record rather
       than a string scan. Title-only mode keeps substring matching, which is what a
       reader expects of a title box and what §4 specifies for it. */
    const useSummaries = state.searchSummaries !== false;
    let candidates = null, titleNeedle = '';
    if (rawQuery) {
      if (useSummaries && this.postings) candidates = this.postings.candidates(rawQuery);
      else titleNeedle = fold(rawQuery);
    }
    const floor = this.corpus.popularityFloor(state.minPopularity);
    const minImp = state.minImportance;

    /* Only facets with a selection can fail anything, so only they need a bit. An
       untouched facet costs nothing per record. */
    const active = [];
    const bitOf = {};
    for (const f of FACET_KEYS) {
      const chosen = [];
      for (const k in state.sel[f]) if (state.sel[f][k]) chosen.push(k);
      if (!chosen.length) { bitOf[f] = 0; continue; }
      /* A permission group with every value lit permits everything, so it is not an
         active constraint and does not need a bit either. */
      if (PERMIT[f] && chosen.length >= (this.corpus.universe[f] || []).length &&
          (this.corpus.universe[f] || []).every(v => state.sel[f][v])) {
        bitOf[f] = 0;
        continue;
      }
      const bit = 1 << active.length;
      bitOf[f] = bit;
      active.push({ facet: f, bit, sel: new Set(chosen), permit: !!PERMIT[f] });
    }

    const results = [];
    const counts = {};
    for (const f of COUNTED) counts[f] = new Map();
    /* Per-facet "passes everything except this facet" sets. The adapter the oracle
       drives asks for exactly these, and building them here means the differential
       measures the same walk the page does rather than a second implementation. */
    const excluded = {};
    for (const f of COUNTED) excluded[f] = [];

    for (const n of records) {
      /* Global predicates first, exactly as v1 orders them: the floor is applied
         before facets so the facet counts reflect what is shown. A record failing
         one of these is out of everything, counts included. */
      if (minImp && (n.importance === null || n.importance < minImp)) continue;
      if (n.pop < floor) continue;
      if (candidates && !candidates.has(n.i)) continue;
      if (titleNeedle && n.foldedTitle.indexOf(titleNeedle) < 0) continue;

      let mask = 0;
      for (const a of active) {
        const vals = n.vals[a.facet];
        let ok;
        if (a.permit) {
          ok = true;
          for (const v of vals) if (!a.sel.has(v)) { ok = false; break; }
        } else {
          ok = false;
          for (const v of vals) if (a.sel.has(v)) { ok = true; break; }
        }
        if (!ok) mask |= a.bit;
      }

      if (mask === 0) results.push(n);

      for (const f of COUNTED) {
        if ((mask & ~bitOf[f]) !== 0) continue;
        excluded[f].push(n);
        const m = counts[f];
        for (const v of n.vals[f]) m.set(v, (m.get(v) || 0) + 1);
      }
    }

    return { results, counts, excluded, floor };
  }
}

/* Counting an arbitrary array, for callers that are not the main walk -- the oracle's
 * frequency sampling over the whole corpus, and the semantic runner. The walk above
 * does not use this; it counts inline, which is the point. */
export function countValues(normalized, facet) {
  const out = {};
  for (const n of normalized) {
    for (const v of n.vals[facet]) out[v] = (out[v] || 0) + 1;
  }
  return out;
}

export { NO_NONE };
