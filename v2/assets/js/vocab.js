/* Vocabularies, labels and the facet model, lifted verbatim from v1.
 *
 * Everything between the markers below is byte-identical to
 * assets/js/sdv-index.js lines 11-170 with the IIFE's two-space indent removed.
 * It was extracted by script, not retyped: these tables are hundreds of country
 * names and label strings, and a single dropped letter would move a facet count in
 * a way no reviewer would spot. scripts/check_vocab_parity.py re-runs the
 * extraction and fails if the two ever diverge.
 *
 * v1 keeps these as `var` inside a closure. Here they are module-scoped and
 * exported at the bottom, which is the only change.
 */

/* ===== BEGIN verbatim from assets/js/sdv-index.js ===== */
var TYPE2KIND = {
  article: 'paper', 'conference-paper': 'paper', review: 'paper', 'book-chapter': 'paper',
  preprint: 'preprint', dissertation: 'thesis', book: 'paper', 'data-paper': 'dataset_benchmark',
  dataset: 'dataset_benchmark', 'software-paper': 'paper'
};
var HITS2COMPONENT = {
  st: 'sdv', md: 'sdv', mt: 'sdv', sq: 'sdv', ev: 'sdv', gc: 'sdv', par: 'sdv', hma: 'sdv', req: 'sdv',
  ct: 'ctgan', sm: 'sdmetrics', rdt: 'rdt', gym: 'sdgym'
};

/* ---------- Labels ---------- */
var KIND_LABELS = {
  paper: 'Paper', preprint: 'Preprint', thesis: 'Thesis', blog_post: 'Blog post',
  announcement: 'Announcement', case_study: 'Case study', news_article: 'News article',
  documentation: 'Documentation', code_repo: 'Code repo', tutorial: 'Tutorial',
  video: 'Video', dataset_benchmark: 'Dataset / benchmark', forum: 'Forum', patent: 'Patent'
};
var COMPONENT_LABELS = {
  sdv: 'SDV', ctgan: 'CTGAN', rdt: 'RDT', sdmetrics: 'SDMetrics', sdgym: 'SDGym',
  copulas: 'Copulas', deepecho: 'DeepEcho', tgan: 'TGAN', enterprise: 'Enterprise'
};
var USECASE_LABELS = {
  privacy_protection: 'Privacy protection', anonymization: 'Anonymization',
  data_sharing: 'Data sharing', software_testing: 'Software testing',
  data_augmentation: 'Data augmentation', class_imbalance: 'Class imbalance',
  ml_training: 'ML training', benchmarking_evaluation: 'Benchmarking & evaluation',
  scenario_simulation: 'Scenario simulation', method_research: 'Method research',
  compliance: 'Compliance', education: 'Education',
  fairness_bias: 'Fairness & bias', imputation: 'Imputation',
  open_science_reproducibility: 'Open science & reproducibility'
};
var CONCEPT_LABELS = {
  relational_hma: 'Relational (HMA)', mode_specific_normalization: 'Mode-specific normalization',
  conditional_sampling: 'Conditional sampling', gaussian_copula: 'Gaussian copula',
  vine_copula: 'Vine copula', tvae: 'TVAE', par_sequential: 'PAR (sequential)',
  metadata_schema: 'Metadata schema', constraints: 'Constraints',
  reversible_transforms: 'Reversible transforms (RDT)',
  ml_efficacy_eval: 'ML-efficacy evaluation', quality_report: 'Quality report',
  benchmark_harness: 'Benchmark harness'
};
var INDUSTRY_LABELS = {
  healthcare_bio: 'Healthcare & bio', finance_insurance: 'Finance & insurance',
  government_public: 'Government & public', academia: 'Academia',
  energy_utilities: 'Energy & utilities', telecom: 'Telecom',
  retail_ecommerce: 'Retail & e-commerce', transportation: 'Transportation',
  manufacturing: 'Manufacturing', software: 'Software', cross_industry: 'Cross-industry',
  construction_infrastructure: 'Construction & infrastructure', cybersecurity: 'Cybersecurity',
  environment_climate: 'Environment & climate', media_recommenders: 'Media & recommenders',
  chemicals_materials: 'Chemicals & materials', education_sector: 'Education sector',
  agriculture: 'Agriculture', aerospace: 'Aerospace'
};
var INTEGRATION_LABELS = {
  api_user: 'API user', vendored_source: 'Vendored source', agent_skill: 'Agent skill',
  derivative_work: 'Derivative work', baseline_only: 'Baseline only',
  citation_only: 'Citation only', foundation: 'Foundation',
  inherited: 'Inherited', declared_only: 'Declared only', port: 'Port',
  name_collision: 'Name collision', unclear: 'Unclear'
};
/* Two derived splits over organization-aligned affiliation fields, each rendered as a
   button group rather than a checkbox list: the question is never "which of 500
   organizations" but "industry or academia" and "which part of the world".
   These groups PERMIT rather than select, the opposite of every checkbox facet on the
   page -- see passesAffiliationFacets. onEmpty says what to do when the last lit button
   in a group is switched off, since an empty group would show nothing: the pair hands
   the selection to its partner, a group of three or more reopens entirely. */
/* A label may carry a newline, which the button renders as two centred lines. Every
   label in the type group names the affiliation outright, because the group sits under
   Sector where a bare "Academic" would read as a claim about the subject matter rather
   than about the authors' organizations; stacking keeps the longer names narrow. */
var AFF_LABELS = {
  academic: 'Academic\naffiliation', non_academic: 'Non-academic\naffiliation',
  unaffiliated: 'Affiliation\nnot found',
  americas: 'Americas', europe: 'Europe', asia: 'Asia',
  africa_oceania: 'Africa /\nOceania'
};
/* Each group mounts beside the checkbox facet asking the same question from the other
   direction: the affiliation types over Sector, which classifies the work rather than
   the people, and the regions over the organization list they summarize. */
var AFF_GROUPS = [
  { facet: 'aff_type', mount: 'affTypeToggles',
    values: ['academic', 'non_academic', 'unaffiliated'], onEmpty: 'all' },
  { facet: 'aff_region', mount: 'affRegionToggles',
    values: ['americas', 'europe', 'asia', 'africa_oceania'], onEmpty: 'all' }
];
/* Country names as the affiliation tables spell them, plus the aliases those tables
   have used before. Every region is ENUMERATED rather than one of them serving as the
   remainder: a name none of the lists recognizes has to come out as no region at all,
   because a veto must never rest on a country we failed to place. Adding a country
   here is the fix when one turns up unplaced -- it will show in no count until it is
   listed. Africa and Oceania share one bucket -- single figures each, too thin to read
   as separate buttons -- but they are kept out of Asia so that a reader looking for
   African work does not have to know it had been filed under Asia to find it. */
var AMERICAS = {};
var EUROPE = {};
var ASIA = {};
var AFRICA = {};
var OCEANIA = {};
(function (index) {
  'United States|United States of America|USA|US|Canada|Mexico|Brazil|Colombia|Argentina|Chile|Peru|Ecuador|Uruguay|Paraguay|Bolivia|Venezuela|Costa Rica|Panama|Guatemala|Honduras|Nicaragua|El Salvador|Cuba|Dominican Republic|Haiti|Jamaica|Trinidad and Tobago|Barbados|Bahamas|Belize|Guyana|Suriname|Puerto Rico|Greenland'
    .split('|').forEach(function (n) { AMERICAS[n.toLowerCase()] = 1; });
  'United Kingdom|UK|Great Britain|England|Scotland|Wales|Northern Ireland|Ireland|France|Germany|Italy|Spain|Portugal|Netherlands|Belgium|Luxembourg|Switzerland|Austria|Denmark|Norway|Sweden|Finland|Iceland|Poland|Czech Republic|Czechia|Slovakia|Hungary|Romania|Bulgaria|Greece|Croatia|Slovenia|Serbia|Bosnia and Herzegovina|Montenegro|North Macedonia|Albania|Estonia|Latvia|Lithuania|Belarus|Ukraine|Moldova|Russia|Russian Federation|Malta|Cyprus|Kosovo|Monaco|Liechtenstein|Andorra|San Marino'
    .split('|').forEach(function (n) { EUROPE[n.toLowerCase()] = 1; });
  'China|India|South Korea|Korea|Republic of Korea|North Korea|Japan|Taiwan|Hong Kong|Macau|Singapore|Malaysia|Indonesia|Thailand|Vietnam|Philippines|Cambodia|Laos|Myanmar|Brunei|Timor-Leste|Bangladesh|Pakistan|Sri Lanka|Nepal|Bhutan|Maldives|Afghanistan|Iran|Iraq|Israel|Palestine|Jordan|Lebanon|Syria|Saudi Arabia|Yemen|Oman|United Arab Emirates|UAE|Qatar|Bahrain|Kuwait|Türkiye|Turkey|Georgia|Armenia|Azerbaijan|Kazakhstan|Uzbekistan|Turkmenistan|Kyrgyzstan|Tajikistan|Mongolia'
    .split('|').forEach(function (n) { ASIA[n.toLowerCase()] = 1; });
  'Australia|New Zealand|Fiji|Papua New Guinea|Samoa|Tonga|Vanuatu|Solomon Islands|New Caledonia|French Polynesia|Guam'
    .split('|').forEach(function (n) { OCEANIA[n.toLowerCase()] = 1; });
  'Egypt|Morocco|Algeria|Tunisia|Libya|Sudan|South Sudan|Ethiopia|Eritrea|Djibouti|Somalia|Kenya|Uganda|Tanzania|Rwanda|Burundi|Nigeria|Ghana|Senegal|Ivory Coast|Cote d Ivoire|Mali|Burkina Faso|Niger|Chad|Cameroon|Gabon|Congo|Democratic Republic of the Congo|DR Congo|Central African Republic|Benin|Togo|Guinea|Sierra Leone|Liberia|Gambia|Mauritania|Cape Verde|Zambia|Zimbabwe|Malawi|Mozambique|Angola|Namibia|Botswana|South Africa|Lesotho|Eswatini|Madagascar|Mauritius|Seychelles'
    .split('|').forEach(function (n) { AFRICA[n.toLowerCase()] = 1; });
})();

var CONF_RANK = { high: 3, medium: 2, low: 1 };
var KIND_ORDER = ['paper', 'preprint', 'thesis', 'code_repo', 'documentation',
  'blog_post', 'announcement', 'case_study', 'tutorial', 'video',
  'dataset_benchmark', 'news_article', 'forum', 'patent'];
var CITABLE = { paper: 1, preprint: 1, thesis: 1 };

function prettify(v) {
  return String(v || '').replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); });
}
function labelFor(facet, v) {
  /* Undated rather than the generic Not specified, and the same word the year group
     headings use, so the button and the heading agree. */
  if (facet === 'year' && v === '__none__') return 'Undated';
  if (v === '__none__') return 'Not specified';
  if (facet === 'kind') return KIND_LABELS[v] || prettify(v);
  if (facet === 'sdv_component') return COMPONENT_LABELS[v] || v;
  if (facet === 'sdv_concept') return CONCEPT_LABELS[v] || prettify(v);
  if (facet === 'use_case') return USECASE_LABELS[v] || prettify(v);
  if (facet === 'industry') return INDUSTRY_LABELS[v] || prettify(v);
  if (facet === 'integration') return INTEGRATION_LABELS[v] || prettify(v);
  if (facet === 'confidence') return prettify(v);
  if (facet === 'aff_type' || facet === 'aff_region') return AFF_LABELS[v] || v;
  return v;
}

/* ---------- Facet model ---------- */
var FACET_KEYS = ['kind', 'sdv_component', 'sdv_concept', 'use_case', 'integration',
  'industry', 'authors', 'affiliations', 'aff_type', 'aff_region', 'year'];
var MOUNTS = {
  kind: 'facet-kind', sdv_component: 'facet-component', sdv_concept: 'facet-concept',
  use_case: 'facet-usecase', integration: 'facet-integration',
  industry: 'facet-industry', authors: 'facet-authors',
  affiliations: 'facet-affiliations', year: 'facet-years'
};
/* Facets whose values run to the hundreds get a filter box above the list and are
   capped until something is typed. */
var SEARCHABLE = { authors: 1 };

/* Absence is a curatorial statement, not missing data: the source named SDV and never
   named a synthesizer class, so no concept was guessed. A sentinel makes that visible
   as an ordinary facet value; otherwise those entries vanish the moment anyone ticks a
   box. Authors is excluded -- a missing author list is an absent fact, not a judgement. */
var NONE = '__none__';
/* aff_type and aff_region are in here for a different reason from authors and
   affiliations, and leaving them out was a bug: a button group enumerates its own
   values, so a record with no resolved region must come back with an EMPTY list.
   Given the sentinel instead, groupPermits sees a value no button lights and vetoes
   the record -- which silently dropped every entry with no affiliation, the whole of
   both pools included. */
var NO_NONE = { authors: 1, affiliations: 1, aff_type: 1, aff_region: 1 };
/* ===== END verbatim ===== */

export {
  TYPE2KIND, HITS2COMPONENT,
  KIND_LABELS, COMPONENT_LABELS, USECASE_LABELS, CONCEPT_LABELS,
  INDUSTRY_LABELS, INTEGRATION_LABELS, AFF_LABELS, AFF_GROUPS,
  AMERICAS, EUROPE, ASIA, AFRICA, OCEANIA,
  CONF_RANK, KIND_ORDER, CITABLE,
  prettify, labelFor,
  FACET_KEYS, MOUNTS, SEARCHABLE, NONE, NO_NONE,
};
