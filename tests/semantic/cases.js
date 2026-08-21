/* Hand-authored semantic tests (design v2 §8).
 *
 * The characterization oracle preserves v1's behavior including its bugs -- that is
 * what a characterization oracle is for -- so it can say whether behavior CHANGED
 * but never whether it is RIGHT. These cases say what is right.
 *
 * Every expectation below was derived by reading tests/semantic/fixture.json, not by
 * running the engine and recording the output. Where a number needed arithmetic the
 * arithmetic is written out. If a case fails, the first question is whether the
 * fixture reasoning is wrong -- not whether to update the expectation.
 */

export const ALL_AFF_TYPES = ['academic', 'non_academic', 'unaffiliated'];
export const ALL_AFF_REGIONS = ['americas', 'europe', 'asia', 'africa_oceania'];

/* Every curated id, plus the one pool row that survives suppression. */
const EVERYTHING = ['p1', 'p2', 'p3', 'p4', 'p5', 'p6', 'r1', 'r2', 't1', 't2', 'c1',
  'https://openalex.org/W999'];
const W999 = 'https://openalex.org/W999';

const base = {
  titleQuery: '', minImportance: 0, minPopularity: 0,
  group: 'none', sortWithin: 'importance', sel: {},
  aff: { aff_type: ALL_AFF_TYPES, aff_region: ALL_AFF_REGIONS },
};
const at = (over) => Object.assign({}, base, over || {});

/* Assertion helpers. `ids` compares as a SET (order-insensitive); `order` compares
 * as a sequence. Mixing the two up is how an ordering bug hides. */
export const CASES = [

  // ---- facet combination -------------------------------------------------

  {
    id: 'or-within-a-facet',
    why: 'Two values of one facet are OR: p1 carries both, p2 only data_sharing, ' +
         'p4 only privacy_protection, and all three must come back.',
    state: at({ sel: { use_case: ['privacy_protection', 'data_sharing'] } }),
    expect: { ids: ['p1', 'p2', 'p4'] },
  },
  {
    id: 'and-across-facets',
    why: 'Two facets are AND. p1 has data_sharing but its only component is sdv, ' +
         'so requiring ctgan as well must leave p2 alone.',
    state: at({ sel: { use_case: ['data_sharing'], sdv_component: ['ctgan'] } }),
    expect: { ids: ['p2'] },
  },
  {
    id: 'and-across-facets-can-be-empty',
    why: 'p1 is the only privacy_protection record with any industry, and its ' +
         'industry is healthcare. p4 has privacy_protection but no industry at all, ' +
         'so it carries the __none__ sentinel rather than finance. Nothing matches.',
    state: at({ sel: { use_case: ['privacy_protection'], industry: ['finance_insurance'] } }),
    expect: { ids: [] },
  },

  // ---- the __none__ sentinel and its exceptions --------------------------

  {
    id: 'none-sentinel-on-a-bounded-facet',
    why: 'Absence is a curatorial statement on bounded facets, so every record with ' +
         'no industry must be reachable through the sentinel. That is everything ' +
         'except p1 (healthcare) and p2 (finance).',
    state: at({ sel: { industry: ['__none__'] } }),
    expect: { ids: EVERYTHING.filter(i => i !== 'p1' && i !== 'p2') },
  },
  {
    id: 'no-none-sentinel-for-authors',
    why: 'A missing author list is an absent fact, not a judgement, so authors must ' +
         'never carry the sentinel -- neither in the universe nor as a match. ' +
         'p3, t1 and t2 all have empty author lists.',
    state: at({ sel: { authors: ['__none__'] } }),
    expect: { ids: [], universeExcludes: { authors: '__none__' } },
  },
  {
    id: 'no-none-sentinel-for-affiliations',
    why: 'Same reasoning as authors. Six of the eleven curated records have no ' +
         'affiliation on record.',
    state: at({ sel: { affiliations: ['__none__'] } }),
    expect: { ids: [], universeExcludes: { affiliations: '__none__' } },
  },
  {
    id: 'affiliation-groups-return-empty-not-a-sentinel',
    why: 'This is the NO_NONE bug the v1 source comments on. A button group ' +
         'enumerates its own values, so a record with no resolved region must come ' +
         'back with an EMPTY list. Handed the sentinel instead, groupPermits sees a ' +
         'value no button lights and vetoes the record -- which silently drops every ' +
         'unaffiliated entry, the whole of both pools included. p3 has no ' +
         'affiliation at all: its type must be exactly [unaffiliated] and its ' +
         'region list must be empty.',
    state: at({}),
    expect: {
      valuesOf: [
        ['p3', 'aff_type', ['unaffiliated']],
        ['p3', 'aff_region', []],
      ],
      universeExcludes: { aff_region: '__none__', aff_type: '__none__' },
    },
  },

  // ---- affiliation shape --------------------------------------------------

  {
    id: 'semicolon-separated-organizations-split',
    why: 'The stored list aligns with authors, so one element can hold several ' +
         'organizations. p4 carries "MIT;Delft University of Technology" as a ' +
         'single string and must filter as two distinct organizations.',
    state: at({}),
    expect: {
      organizationsOf: [['p4', ['MIT', 'Delft University of Technology']]],
    },
  },
  {
    id: 'unrecorded-affiliation-type-reads-non-academic',
    why: 'p6 records its type as the literal string "unknown". That is not academic, ' +
         'so it must read as non-academic rather than as unaffiliated -- p6 does ' +
         'have an organization on record.',
    state: at({}),
    expect: { valuesOf: [['p6', 'aff_type', ['non_academic']]] },
  },

  // ---- the permission groups (veto, not selection) ------------------------

  {
    id: 'unlighting-unaffiliated-drops-only-records-with-no-affiliation',
    why: 'Five curated records carry an organization: p1, p2, p4, p5, p6. Everything ' +
         'else, including the pool row, is unaffiliated and must go.',
    state: at({ aff: { aff_type: ['academic', 'non_academic'], aff_region: ALL_AFF_REGIONS } }),
    expect: { ids: ['p1', 'p2', 'p4', 'p5', 'p6'] },
  },
  {
    id: 'overlapping-types-veto-rather-than-select',
    why: 'A button group asks whether EVERY value a record carries is still lit. ' +
         'p5 has both a university and a company, so lighting only Academic must ' +
         'drop it -- that is what makes a single lit button read as "only here". ' +
         'p1 (MIT) and p4 (MIT + Delft) are academic-only and stay.',
    state: at({ aff: { aff_type: ['academic'], aff_region: ALL_AFF_REGIONS } }),
    expect: { ids: ['p1', 'p4'] },
  },
  {
    id: 'multi-region-work-is-vetoed-by-either-region',
    why: 'p4 has organizations in the United States and the Netherlands. Unlighting ' +
         'Americas must drop it even though Europe stays lit. p1 (US only) goes too; ' +
         'everything else either has no region or is European.',
    state: at({ aff: { aff_type: ALL_AFF_TYPES, aff_region: ['europe', 'asia', 'africa_oceania'] } }),
    expect: { ids: EVERYTHING.filter(i => i !== 'p1' && i !== 'p4') },
  },
  {
    id: 'unplaced-and-unknown-countries-never-veto',
    why: 'A veto must never rest on a country we failed to place. p5 sits in the ' +
         'United Kingdom and in "Atlantis", which no region list recognizes; p6 sits ' +
         'in the literal string "unknown". With only Europe lit, p5 must survive on ' +
         'its UK organization and p6 must survive carrying no region at all. Only ' +
         'the genuinely-American p1 and p4 are dropped.',
    state: at({ aff: { aff_type: ALL_AFF_TYPES, aff_region: ['europe'] } }),
    expect: {
      ids: EVERYTHING.filter(i => i !== 'p1' && i !== 'p4'),
      idsInclude: ['p5', 'p6'],
    },
  },

  // ---- self-excluding counts ---------------------------------------------

  {
    id: 'facet-counts-exclude-their-own-facet',
    why: 'With Paper ticked the result is the nine papers, but the Kind facet must ' +
         'still show what the other kinds are holding -- one preprint (p3) and two ' +
         'repositories (r1, r2) -- or a reader could never widen the selection. ' +
         'The nine papers are p1, p2, p4, p5, p6, t1, t2, c1 and the pool row, whose ' +
         'OpenAlex type "article" maps to paper.',
    state: at({ sel: { kind: ['paper'] } }),
    expect: {
      total: 9,
      facetCounts: { kind: { paper: 9, preprint: 1, code_repo: 2 } },
    },
  },
  {
    id: 'a-facet-count-of-zero-still-appears',
    why: 'Nothing in the fixture is a thesis, and the sentinel is not a kind. ' +
         'A value the current view cannot offer must read 0 rather than vanish, so ' +
         'the reader can see it is empty rather than assume it is missing.',
    state: at({ sel: { kind: ['preprint'] } }),
    expect: { total: 1, facetCounts: { kind: { paper: 9, preprint: 1, code_repo: 2 } } },
  },

  // ---- popularity and the sort tie-break chain ----------------------------

  {
    id: 'popularity-is-attention-only',
    why: 'Hand arithmetic against the formula. r1: w = 100 + 2*10 + 5*4 + 0.1*500 = ' +
         '190, so log1p(190)/log1p(8000). r2 is a repository with no signal at all, ' +
         'which is 0 and NOT the 0.3 neutral default -- the default is for entries ' +
         'carrying no signal of either kind. t1 has neither stars nor citations, so ' +
         'it takes the default. p1 is cited 10 times, the pool row 200.',
    state: at({}),
    expect: {
      popularity: [
        ['r1', 0.5844091863425764],
        ['r2', 0],
        ['t1', 0.3],
        ['p1', 0.3278551238210548],
        [W999, 0.7251007610784499],
      ],
    },
  },
  {
    id: 'importance-sort-breaks-ties-on-popularity-then-year-then-title',
    why: 'c1 is the only 6. Among the 5s, p1 and p2 are cited equally so the tie ' +
         'falls to year (2024 before 2023), and t1/t2 tie on all three axes so it ' +
         'falls to title (Iota before Jota). Among the 4s, p4 and p5 tie to title ' +
         '(Delta before Epsilon). The unrated pool row sorts as -1, below 0, last.',
    state: at({ sortWithin: 'importance' }),
    expect: {
      order: ['c1', 'p1', 'p2', 't1', 't2', 'p4', 'p5', 'p3', 'p6', 'r1', 'r2', W999],
    },
  },
  {
    id: 'popularity-sort-breaks-ties-on-importance',
    why: 'The same twelve records in the other order. The pool row leads on 200 ' +
         'citations despite being unrated -- the two axes are independent. Everything ' +
         'at the 0.3 default then orders by importance: c1(6), t1(5), t2(5), p4(4), ' +
         'p5(4), p3(3), p6(2). The starless repository is last on 0.',
    state: at({ sortWithin: 'popularity' }),
    expect: {
      order: [W999, 'r1', 'p1', 'p2', 'c1', 't1', 't2', 'p4', 'p5', 'p3', 'p6', 'r2'],
    },
  },

  // ---- grouping -----------------------------------------------------------

  {
    id: 'a-record-with-two-values-appears-under-both-groups',
    why: 'p1 has two use cases, so it is placed under both headings and the group ' +
         'counts sum to 13 against a result set of 12. That is correct, not a bug: ' +
         'the headings partition values, not records. Size-ordered facets sort by ' +
         'group size descending and break the 2-2 tie alphabetically.',
    state: at({ group: 'use_case' }),
    expect: {
      total: 12,
      groups: [['Not specified', 9], ['Data sharing', 2], ['Privacy protection', 2]],
    },
  },

  // ---- the pool: suppression and the importance floor ---------------------

  {
    id: 'a-pooled-row-is-suppressed-by-alias-not-by-displayed-url',
    why: 'c1 displays a DOI but also carries openalex_id W123, and the pool row W123 ' +
         'displays an example.org landing page. Matching only the displayed pointer ' +
         'would leave the work in both the index and the pool. W999, which nothing ' +
         'curated points at, must survive.',
    state: at({}),
    expect: {
      idsExclude: ['https://openalex.org/W123'],
      idsInclude: [W999, 'c1'],
      total: 12,
    },
  },
  {
    id: 'a-repeated-pool-row-is-collapsed',
    why: 'The stored citation tail has carried the same work twice. The fixture ' +
         'repeats W999 verbatim; it must appear exactly once, or the pool row shows ' +
         'twice and inflates the header count.',
    state: at({}),
    expect: { idCount: { [W999]: 1 } },
  },
  {
    id: 'the-pool-residue-is-visible-only-at-importance-zero',
    why: 'No pooled row carries a rating, so any floor above 0 hides all of them. ' +
         'The default floor is 1, which must leave exactly the eleven curated ' +
         'records; dropping to 0 must reveal the one surviving pool row, tagged tail.',
    state: at({ minImportance: 1 }),
    expect: {
      total: 11,
      idsExclude: [W999],
      alsoAt: { state: at({ minImportance: 0 }), total: 12, idsInclude: [W999] },
      tier: [[W999, 'tail']],
    },
  },
];

/* Behaviors that only exist in v2. They are named here, in Stage 0, so the contract
 * is fixed before the code -- but their assertions need an API that Stage 1 has yet
 * to define, so the runner reports them as PENDING rather than inventing a shape for
 * them now.
 *
 * `closes` says which stage is supposed to make each one real. Six close in Stage 1,
 * which is the rendering and object-URL work. The four detail-fetch cases cannot:
 * Stage 1 runs on the current flat export, where summary and needs are already in
 * memory and "lazy" means lazy DOM, not a lazy fetch. The buckets those four describe
 * do not exist until Stage 2. A case still pending after the stage that `closes` it
 * is a gap, not a pass.
 *
 * v1 fails several of these by design -- it renders every card and mints one Blob
 * URL per citable entry. That is the redesign, not a regression. */
export const PENDING_V2 = [
  {
    id: 'at-most-100-unique-records-render-initially',
    closes: 1,
    why: 'Design v2 §3 item 8 and §9. Sort the full unique result set, render the ' +
         'first N unique records, place those into every applicable group.',
    pending: true,
  },
  {
    id: 'group-headers-show-visible-over-total',
    closes: 1,
    why: '§3 item 8. A group holding 400 records of which 12 are rendered must say so.',
    pending: true,
  },
  {
    id: 'show-100-more-adds-100-unique-records',
    closes: 1,
    why: '§3 item 8. The increment is in unique records, not in group placements.',
    pending: true,
  },
  {
    id: 'any-filter-grouping-or-sort-change-resets-the-page-limit',
    closes: 1,
    why: '§3 item 8. Otherwise a narrow filter inherits a wide page and renders more ' +
         'than the cap.',
    pending: true,
  },
  {
    id: 'no-blob-url-is-created-during-render',
    closes: 1,
    why: '§9, a hard gate. v1 creates about 8,541 unreclaimed object URLs before any ' +
         'interaction; BibTeX must move into the click handler.',
    pending: true,
  },
  {
    id: 'a-bibtex-object-url-is-revoked-once-the-download-begins',
    closes: 1,
    why: '§3 item 6. Generating lazily is not enough if the URL then leaks.',
    pending: true,
  },
  {
    id: 'a-detail-fetch-populates-summary-and-needs',
    closes: 2,
    why: '§3 item 6 and §6. Stage 2 artifact, but the loader lands in Stage 1.',
    pending: true,
  },
  {
    id: 'concurrent-detail-fetches-for-one-bucket-share-a-promise',
    closes: 2,
    why: '§6, "detail-bucket fetches deduplicate in-flight promises".',
    pending: true,
  },
  {
    id: 'a-failed-detail-fetch-leaves-the-core-card-usable',
    closes: 2,
    why: '§3 item 10. The card keeps working and shows a retryable inline error.',
    pending: true,
  },
  {
    id: 'retrying-a-failed-detail-fetch-succeeds',
    closes: 2,
    why: '§3 item 10. A failure must not poison the bucket for the rest of the session.',
    pending: true,
  },
];
