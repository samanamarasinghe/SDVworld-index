/* Search (design v2 §4).
 *
 * Two modes, and the toggle in the filter panel chooses between them:
 *
 *   summaries ON (the default)  token matching over title AND summary, via the
 *                               postings built at build time
 *   summaries OFF               case-insensitive substring over the title only
 *
 * §4 specifies title-only as the DEFAULT and summaries as opt-in. That is inverted
 * here, deliberately and with the owner's approval (2026-08-21), because the ruling
 * predates the performance work that made summary matching cheap. Measured against
 * the frozen queries, a title-only default keeps 29% of v1's results overall and far
 * less where it matters most: `sdv` falls from 3,146 hits to 61 and `ctgan` from
 * 3,293 to 123, because the terms this index is *about* are rarely in titles. The
 * toggle still exists, so narrowing to titles is one click away; it is the default
 * that changed, not the capability.
 *
 * Everything else in §4 is as written: identical normalization at build and runtime,
 * Unicode letter/number tokens, multiple terms AND, and the final term matched by
 * prefix so typing stays progressive.
 */

/* Must agree exactly with fold()/tokenize() in site_projection.py, or a query
 * tokenizes differently from the text it is searching and the postings quietly miss.
 * tests/build_tests.py runs a shared table of cases against both. */
export function fold(text) {
  return String(text || '').normalize('NFKD').replace(/\p{M}+/gu, '').toLowerCase();
}

export function tokenize(text) {
  return fold(text).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
}

/* Whether the final term should be matched by prefix.
 *
 * Prefix matching exists so that a half-typed word still finds things. If the reader
 * typed a delimiter after the last word, they have finished it -- and treating it as
 * a prefix anyway is actively harmful: "C++" tokenizes to the single token `c`, and
 * prefix-matching that returns 4,627 of 4,962 records. §4 does not say this; it is a
 * gap in the spec, found by running its own frozen examples. */
export function prefixWanted(query) {
  return !/[^\p{L}\p{N}]$/u.test(String(query || ''));
}

export class Postings {
  constructor(doc) {
    this.vocab = doc.vocab;
    /* Stored delta-encoded; expanded lazily, because a session touches a handful of
       tokens out of fifteen thousand. */
    this.raw = doc.postings;
    this.cache = new Map();
  }

  list(index) {
    let ids = this.cache.get(index);
    if (!ids) {
      const deltas = this.raw[index];
      ids = new Array(deltas.length);
      let at = 0;
      for (let k = 0; k < deltas.length; k++) { at += deltas[k]; ids[k] = at; }
      this.cache.set(index, ids);
    }
    return ids;
  }

  /* First vocabulary position at or after `term`. */
  lowerBound(term) {
    let lo = 0, hi = this.vocab.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.vocab[mid] < term) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  exact(term) {
    const at = this.lowerBound(term);
    return this.vocab[at] === term ? this.list(at) : null;
  }

  /* Every record carrying a token that starts with `term`. */
  withPrefix(term) {
    const out = new Set();
    for (let at = this.lowerBound(term);
         at < this.vocab.length && this.vocab[at].startsWith(term); at++) {
      for (const id of this.list(at)) out.add(id);
    }
    return out;
  }

  /* The candidate record indices for a query, or null for "no constraint".
   *
   * Terms AND. The rarest term is intersected first so the working set shrinks
   * immediately rather than after a full pass over the commonest one. */
  candidates(query) {
    const terms = tokenize(query);
    if (!terms.length) return null;
    const usePrefix = prefixWanted(query);

    const sets = [];
    for (let i = 0; i < terms.length; i++) {
      const last = i === terms.length - 1;
      if (last && usePrefix) {
        sets.push(this.withPrefix(terms[i]));
      } else {
        const ids = this.exact(terms[i]);
        if (!ids) return new Set();      // a term nothing carries: no results
        sets.push(new Set(ids));
      }
    }
    sets.sort((a, b) => a.size - b.size);
    let acc = sets[0];
    for (let i = 1; i < sets.length && acc.size; i++) {
      const next = new Set();
      for (const id of acc) if (sets[i].has(id)) next.add(id);
      acc = next;
    }
    return acc;
  }
}

export async function loadPostings(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`postings: HTTP ${r.status}`);
  return new Postings(await r.json());
}
