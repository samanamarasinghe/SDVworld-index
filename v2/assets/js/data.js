/* Loading the site projection.
 *
 * Stage 2a. The page no longer reads data/sdv-index.json or either raw pool. It reads
 * data/site/, which the build produces from the same assembled record list as the
 * public export (§5):
 *
 *   manifest.json   counts, file sizes, and data_hash -- the cache identity
 *   core.json       everything the filter, the sort and a collapsed card need
 *   detail/NN.json  summary and needs only, 32 buckets, fetched when asked for
 *
 * What used to happen here and no longer does: splitting semicolon-separated
 * affiliations, deriving affiliation types and regions, scoring popularity, and
 * fetching 3.7 MB of raw pool data in order to discover the 44 rows of it that
 * survive suppression. All of that is done once now, at build time, by
 * site_projection.py.
 */
import { FACET_KEYS, NONE, NO_NONE } from './vocab.js';

/* Resolved against this module's own URL. Pages serves this project under
 * /SDVworld-index/, so a root-relative path would 404 in production while working on
 * localhost, and a document-relative one breaks the harnesses, which load these
 * modules from pages at other depths. */
const at = (rel) => new URL(rel, import.meta.url).href;
export const SITE = at('../../../data/site/');
export const MANIFEST_PATH = SITE + 'manifest.json';

/* ---- normalization ------------------------------------------------------- */

/* Far less work than Stage 1's version: the derived values arrive precomputed, so
 * this only has to shape the facet lookups the engine walks. */
export function normalize(core, i) {
  const vals = {}, sets = {};
  const raw = {
    kind: core.kind ? [core.kind] : [],
    sdv_component: core.sdv_component || [],
    sdv_concept: core.sdv_concept || [],
    use_case: core.use_case || [],
    integration: core.integration ? [core.integration] : [],
    industry: core.industry || [],
    authors: core.authors || [],
    affiliations: core.organizations || [],
    aff_type: core.aff_type || [],
    aff_region: core.aff_region || [],
    year: core.year ? [String(core.year)] : [],
  };
  for (const f of FACET_KEYS) {
    /* Absence is a curatorial statement on bounded facets and an absent fact on the
       unbounded ones. Getting NO_NONE wrong here would hand a permission group a
       value no button lights, silently dropping every unaffiliated entry. */
    vals[f] = (raw[f].length || NO_NONE[f]) ? raw[f] : [NONE];
    sets[f] = new Set(vals[f]);
  }
  return {
    rec: core, i,
    id: core.id,
    tier: core.tier,
    bucket: core.b,
    hasSummary: !!core.hs,
    hasNeeds: !!core.hn,
    /* Stage 2a preserves v1's search exactly -- substring over title AND summary --
       and the build ships a precomputed lowercase string for it because summary now
       lives in a detail bucket. Stage 2b replaces this with token postings and the
       title-only matching of §4, and the string goes away. */
    searchText: core.s || (core.title || '').toLowerCase(),
    importance: core.importance != null ? core.importance : null,
    pop: core.pop,
    organizations: core.organizations || [],
    vals, sets,
  };
}

/* ---- the corpus ---------------------------------------------------------- */

export class Corpus {
  constructor() {
    this.records = [];
    this.universe = {};
    this.popSorted = [];
    this.counts = { curated: 0, tail: 0, total: 0 };
  }

  /* One place where the corpus changes, so nothing can forget to rebuild what is
     derived from it. */
  set(coreRecords, counts) {
    this.records = (coreRecords || []).map(normalize);
    this.counts = counts || { curated: this.records.length, tail: 0,
                              total: this.records.length };
    this.universe = {};
    for (const f of FACET_KEYS) {
      const set = new Set();
      for (const n of this.records) for (const v of n.vals[f]) set.add(v);
      this.universe[f] = [...set];
    }
    /* v1 re-sorted the whole corpus by popularity inside popularityFloor(), which
       ran inside every filteredData() -- thirteen times an interaction. It is a pure
       function of the corpus, so it is sorted once. */
    this.popSorted = this.records.map(n => n.pop).sort((a, b) => a - b);
    return this;
  }

  popularityFloor(minPopularity) {
    if (!minPopularity) return -1;
    const v = this.popSorted;
    if (!v.length) return -1;
    return v[Math.min(Math.floor(v.length * minPopularity / 100), v.length - 1)];
  }

  probe() {
    const c = this.counts;
    return {
      data: c.curated,
      cite: c.citation_pool != null ? c.citation_pool : null,
      gh: c.repo_pool != null ? c.repo_pool : null,
      total: this.records.length,
    };
  }
}

/* ---- detail buckets ------------------------------------------------------ */

/* §6: "Detail-bucket fetches deduplicate in-flight promises and retain loaded
 * buckets in memory; ordinary HTTP caching (ETag revalidation) does the rest."
 *
 * A rejected fetch is deliberately NOT retained. Caching the rejection would poison
 * the bucket for the rest of the session, so every record in it would be permanently
 * unable to show its summary after one flaky response -- and §3 item 10 requires the
 * error to be retryable. */
export class Details {
  constructor(base = SITE, fetcher = null) {
    this.base = base;
    this.fetch = fetcher || ((url) => fetch(url));
    this.loaded = new Map();
    this.inflight = new Map();
    this.requests = 0;
  }

  bucket(name) {
    if (this.loaded.has(name)) return Promise.resolve(this.loaded.get(name));
    if (this.inflight.has(name)) return this.inflight.get(name);
    this.requests++;
    const p = Promise.resolve(this.fetch(`${this.base}detail/${name}.json`))
      .then(r => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(json => {
        this.loaded.set(name, json);
        this.inflight.delete(name);
        return json;
      })
      .catch(e => {
        this.inflight.delete(name);
        throw e;
      });
    this.inflight.set(name, p);
    return p;
  }

  /* Returns {summary, needs}; an empty object is a legitimate answer for a record
     that carries neither. */
  async forRecord(n) {
    if (!n.hasSummary && !n.hasNeeds) return {};
    const b = await this.bucket(n.bucket);
    return b[n.id] || {};
  }

  /* Test seam: preload a bucket without a network round trip. */
  prime(name, content) { this.loaded.set(name, content); }
}

/* ---- loading ------------------------------------------------------------- */

export async function loadSite() {
  const grab = async (url, what) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${what}: HTTP ${r.status}`);
    return r.json();
  };
  const manifest = await grab(MANIFEST_PATH, 'manifest');
  const core = await grab(SITE + 'core.json', 'core');
  if (core.schema_version !== manifest.schema_version) {
    /* A half-deployed site is the realistic failure here, and silently rendering a
       mismatched pair is worse than saying so. */
    throw new Error(`schema mismatch: manifest ${manifest.schema_version}, ` +
                    `core ${core.schema_version}`);
  }
  return { manifest, records: core.records, counts: manifest.counts };
}
