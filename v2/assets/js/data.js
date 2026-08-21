/* Loading and normalization.
 *
 * v1 derives everything on demand: organizationsOf splits semicolons, affiliationRows
 * rebuilds a per-author table, regionOf lowercases and looks up a country -- and all
 * of it runs again for every record on every one of the eleven-plus corpus walks each
 * interaction costs. Here each record is normalized exactly once and the derived
 * values are read thereafter.
 *
 * Stage 1 reads the CURRENT data/sdv-index.json, unchanged, plus both raw pools. The
 * site projection is Stage 2's job; keeping the format fixed here is what makes a
 * clean differential possible.
 */
import {
  TYPE2KIND, HITS2COMPONENT, AMERICAS, EUROPE, ASIA, AFRICA, OCEANIA,
  FACET_KEYS, NONE, NO_NONE,
} from './vocab.js';

/* Resolved against this module's own URL, not the document's.
 *
 * GitHub Pages serves this project under /SDVworld-index/, so a root-relative
 * '/data/...' would 404 in production while working perfectly on localhost -- the
 * single likeliest way for the pilot to look fine here and be broken live. A
 * document-relative '../data/...' is nearly as fragile: the oracle, the semantic
 * runner and the benchmark all load these modules from pages at other depths.
 * import.meta.url is true wherever the module is loaded from. */
const at = (rel) => new URL(rel, import.meta.url).href;
export const INDEX_PATH = at('../../../data/sdv-index.json');
export const TAIL_PATH = at('../../../data/tail/openalex-citations.json');
export const GITHUB_PATH = at('../../../data/tail/github-repos.json');

/* ---- derived values, computed once per record --------------------------- */

function regionOf(name) {
  const k = String(name || '').toLowerCase().replace(/^the\s+/, '').trim();
  if (!k || k === 'unknown' || k === 'n/a' || k === 'unspecified') return '';
  if (AMERICAS[k]) return 'americas';
  if (EUROPE[k]) return 'europe';
  if (ASIA[k]) return 'asia';
  if (AFRICA[k] || OCEANIA[k]) return 'africa_oceania';
  return '';   // unplaced: carried by no button, so vetoed by none of them
}

function dedupe(arr) {
  const seen = new Set(), out = [];
  for (const v of arr) if (!seen.has(v)) { seen.add(v); out.push(v); }
  return out;
}

/* The stored list is aligned with authors, so one element can contain several
   semicolon-separated organizations and co-authors can repeat an institution. */
function organizationsOf(rec) {
  const out = [];
  for (const value of rec.affiliations || []) {
    if (!value) continue;
    for (let part of String(value).split(';')) {
      part = part.trim();
      if (part) out.push(part);
    }
  }
  return dedupe(out);
}

function affiliationRows(rec, organizations) {
  const types = rec.affiliation_types || [];
  const countries = rec.affiliation_countries || [];
  return organizations.map((organization, i) => {
    const rawType = types[i];
    return {
      organization,
      type: rawType === 'academic' ? 'academic'
        : (rawType && rawType !== 'unknown' ? 'non_academic' : ''),
      region: regionOf(countries[i]),
    };
  });
}

/* An entry with no affiliation on record is its own value rather than being folded
   into non-academic. An organization whose type is unrecorded still reads
   non-academic. */
function affTypes(rows) {
  if (!rows.length) return ['unaffiliated'];
  let acad = false, other = false;
  for (const row of rows) {
    if (row.type === 'academic') acad = true; else other = true;
  }
  if (!acad) return ['non_academic'];
  return other ? ['academic', 'non_academic'] : ['academic'];
}

function affRegions(rows) {
  return dedupe(rows.map(r => r.region).filter(Boolean));
}

/* Popularity = attention the artifact has drawn, on one 0-1 scale so repositories and
   papers can be ranked against each other. Both sides are log-compressed; commits are
   clamped before blending; an entry carrying both signals takes the higher of the two;
   an entry with neither sits at 0.3, a neutral default rather than a zero. */
export function popularityOf(rec) {
  let best = null;
  if (rec.kind === 'code_repo' || rec.stars != null) {
    const w = (rec.stars || 0) + 2 * (rec.forks || 0) + 5 * (rec.contributors || 0) +
      0.1 * Math.min(rec.commits || 0, 2000);
    best = Math.min(1, Math.log1p(w) / Math.log1p(8000));
  }
  if (rec.cited != null) {
    const c = Math.min(1, Math.log1p(rec.cited) / Math.log1p(1500));
    if (best === null || c > best) best = c;
  }
  return best === null ? 0.3 : best;
}

function rawValuesOf(rec, facet, organizations, rows) {
  switch (facet) {
    case 'kind': return rec.kind ? [rec.kind] : [];
    case 'sdv_component': return rec.sdv_component || [];
    case 'sdv_concept': return rec.sdv_concept || [];
    case 'use_case': return rec.use_case || [];
    case 'integration': return rec.integration ? [rec.integration] : [];
    case 'industry': return rec.industry || [];
    case 'confidence': return rec.confidence ? [rec.confidence] : [];
    case 'authors': return rec.authors || [];
    case 'affiliations': return organizations;
    case 'aff_type': return affTypes(rows);
    case 'aff_region': return affRegions(rows);
    case 'year': return rec.year ? [String(rec.year)] : [];
  }
  return [];
}

/* The normalized view of one record. `rec` is the original object, untouched, because
 * rendering still reads it and the differential compares its id. */
export function normalize(rec, i) {
  const organizations = organizationsOf(rec);
  const rows = affiliationRows(rec, organizations);
  const vals = {}, sets = {};
  for (const f of FACET_KEYS) {
    const raw = rawValuesOf(rec, f, organizations, rows);
    /* Absence is a curatorial statement on bounded facets and an absent fact on the
       unbounded ones -- NO_NONE is the difference, and getting it wrong here would
       silently drop every unaffiliated entry. */
    vals[f] = (raw.length || NO_NONE[f]) ? raw : [NONE];
    sets[f] = new Set(vals[f]);
  }
  return {
    rec, i,
    id: rec.id,
    tier: rec.tier,
    /* Stage 1 preserves v1's search exactly: substring over title AND summary,
       lowercased. The title-only change of §4 is Stage 2's, deliberately kept out of
       the stage that rewrites the runtime, so a golden difference here can only mean
       a bug. */
    searchText: ((rec.title || '') + ' ' + (rec.summary || '')).toLowerCase(),
    importance: rec.importance != null ? rec.importance : null,
    pop: popularityOf(rec),
    organizations,
    vals, sets,
  };
}

/* ---- the pools ---------------------------------------------------------- */

function fromHits(hits) {
  const set = new Set();
  for (const h of hits || []) { const c = HITS2COMPONENT[h]; if (c) set.add(c); }
  return [...set];
}

export function normalizeCite(r) {
  const loc = r.primary_location || {};
  const authors = (r.authorships || [])
    .map(a => (a.author || {}).display_name).filter(Boolean);
  return {
    id: r.id, title: r.title || 'Untitled', year: r.publication_year || null,
    kind: TYPE2KIND[r.type] || 'paper',
    url: loc.landing_page_url || r.doi || r.id, doi: r.doi || '',
    alt_urls: [loc.landing_page_url, r.doi, r.id].filter(Boolean),
    authors, sdv_component: [], sdv_concept: [], use_case: [], industry: [],
    cited: r.cited_by_count || 0, confidence: null, tier: 'tail',
  };
}

export function normalizeGh(r) {
  const yr = parseInt((r.created || '').slice(0, 4), 10) || null;
  const authors = [r.owner].concat(r.top_contributors || []).filter(Boolean);
  return {
    id: 'gh-' + r.repo, title: r.repo, url: 'https://github.com/' + r.repo,
    kind: 'code_repo', sdv_component: fromHits((r.hit_patterns || '').split('|')),
    sdv_concept: [], use_case: [], industry: [], authors, summary: r.description || '',
    year: yr, stars: r.stars || 0, forks: r.forks || 0,
    contributors: r.contributors || 0, commits: r.commits || 0,
    confidence: null, tier: 'tail',
  };
}

/* The stored citation tail has carried the same work twice. Duplicates would show as
   repeated pool rows and inflate the corpus count, so collapse them on their id. */
export function dedupeTail(raw) {
  const seen = new Set(), out = [];
  for (const row of raw) {
    const key = row.id || row.doi || (row.title || '');
    if (key && seen.has(key)) continue;
    if (key) seen.add(key);
    out.push(row);
  }
  return out;
}

const urlKey = (u) =>
  String(u || '').toLowerCase().replace(/^https?:\/\//, '').replace(/\/+$/, '');

/* A work can be reached by three different pointers -- its landing page, its DOI, its
   OpenAlex id -- and a curator may have filed it under any one of them. Index every
   pointer the curated entry carries, not just the one it displays. */
export function curatedUrlSet(curated) {
  const map = new Set();
  for (const r of curated) {
    for (const u of [r.url, r.openalex_id]) if (u) map.add(urlKey(u));
  }
  return map;
}

export function notCurated(map, r) {
  for (const k of r.alt_urls || [r.url]) {
    if (k && map.has(urlKey(k))) return false;
  }
  return true;
}

/* ---- the corpus --------------------------------------------------------- */

export class Corpus {
  constructor() {
    this.curated = [];
    this.cite = null;
    this.gh = null;
    this.records = [];        // normalized, curated first then pools
    this.universe = {};       // facet -> sorted array of every value present
    this.popSorted = [];      // ascending popularity over the whole active corpus
  }

  /* One place where the corpus changes, so nothing can forget to rebuild what is
     derived from it. */
  set(curated, cite, gh) {
    this.curated = curated || [];
    this.cite = cite;
    this.gh = gh;
    const all = this.curated.concat(this.cite || [], this.gh || []);
    this.records = all.map(normalize);
    this.universe = {};
    for (const f of FACET_KEYS) {
      const set = new Set();
      for (const n of this.records) for (const v of n.vals[f]) set.add(v);
      this.universe[f] = [...set];
    }
    /* v1 re-sorts the whole corpus by popularity inside popularityFloor(), which is
       called inside every filteredData() -- thirteen times an interaction. It is a
       pure function of the corpus, so it is computed here instead, once. */
    this.popSorted = this.records.map(n => n.pop).sort((a, b) => a - b);
    return this;
  }

  /* The percentile floor for a slider stop, by exactly v1's indexing. */
  popularityFloor(minPopularity) {
    if (!minPopularity) return -1;
    const v = this.popSorted;
    if (!v.length) return -1;
    return v[Math.min(Math.floor(v.length * minPopularity / 100), v.length - 1)];
  }

  probe() {
    return {
      data: this.curated.length,
      cite: this.cite && this.cite.length,
      gh: this.gh && this.gh.length,
    };
  }
}

/* Both pools are fetched in parallel and applied together. v1 fires an applyFilters()
 * per pool, each re-rendering the full default view, although at any floor above 0 --
 * which the default is -- no pooled row can appear and no count can move. */
export async function loadAll({ onIndex, onPools, onError }) {
  const index = await fetch(INDEX_PATH).then(r => {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  });
  const curated = index || [];
  onIndex(curated);

  const map = curatedUrlSet(curated);
  const grab = (path, shape) => fetch(path)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(shape)
    .catch(e => { onError(path, e); return null; });

  const [cite, gh] = await Promise.all([
    grab(TAIL_PATH, raw => dedupeTail(raw || []).map(normalizeCite)
      .filter(r => notCurated(map, r))),
    grab(GITHUB_PATH, raw => ((raw && raw.repos) || raw || []).map(normalizeGh)
      .filter(r => notCurated(map, r))),
  ]);
  onPools(cite, gh);
}
