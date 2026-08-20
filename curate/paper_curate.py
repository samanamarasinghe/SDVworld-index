#!/usr/bin/env python3
"""Curate the uncurated citation tail from fetched full text, via the Batch API.

    python3 curate/paper_curate.py --pilot 5          # live calls now, print, no batch
    python3 curate/paper_curate.py --submit --dry-run # build requests, write, send nothing
    python3 curate/paper_curate.py --submit           # create the batches
    python3 curate/paper_curate.py --status           # poll
    python3 curate/paper_curate.py --collect          # write records from finished batches
    python3 curate/paper_curate.py --tiers            # what evidence exists, no API call

The sibling of curate/auto_curate.py, which did the repository tail. The batch
machinery is the same on purpose. What is different is the evidence and therefore the
prompt: a repository is judged from import lines and file paths, a paper from prose.

Needs ANTHROPIC_API_KEY.

EVIDENCE TIERS. A repository either has code or does not; a paper's evidence varies
enormously, so every candidate carries the tier its evidence came from and the tier
CAPS confidence mechanically in validate():

  full_text        harvest/papers/<slug>.txt exists -- confidence may be high
  abstract_context  an OpenAlex abstract and/or the sentences in which the work cites
                    SDV -- confidence capped at medium
  metadata_only     title, venue, authors, year and nothing else -- capped at low

The cap is enforced in code rather than asked for in the prompt because the model
cannot tell its own certainty from having read the source: an abstract saying "we
generate records with CTGAN" reads as certain, and confidence in this index means the
source was read, not that the judgment feels safe. Importance is NOT capped -- "we
compare against CTGAN" in an abstract supports baseline_only 3 perfectly well.

Every record carries evidence_tier, so when a paper later arrives as full text the
rows to re-judge are exactly the ones whose tier improved. Re-judge them; do not
simply lift the confidence, because full text changes the integration call too.

Output is STAGING, not shards: curate/paper-shards/records/, failures in
needs-review.jsonl. Nothing here is an index entry until a human moves it into
data/shards/.

What this does NOT do, and must be done by hand afterwards: the cross-record work.
No duplicate sweep, no preprint/published pairing, no check against the open
questions. Each request sees one paper and nothing else. The preprint/published pair
is the one to watch here -- three were found in the hand-curated set, and this pass
adds hundreds of arXiv preprints whose published versions may already be indexed.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPERS = os.path.join(ROOT, 'harvest', 'papers')
TAIL = os.path.join(ROOT, 'data', 'tail', 'openalex-citations.json')
ABSTRACTS = os.path.join(ROOT, 'data', 'tail', 'openalex-abstracts.json')
CONTEXTS = os.path.join(ROOT, 'data', 'tail', 'citation-contexts.json')
INDEX = os.path.join(ROOT, 'data', 'sdv-index.json')
SHARDS = os.path.join(ROOT, 'data', 'shards')
NEVER = os.path.join(ROOT, 'curate', 'never-readd.json')
OUT = os.path.join(ROOT, 'curate', 'paper-shards')
RECORDS = os.path.join(OUT, 'records')
REVIEW = os.path.join(OUT, 'needs-review.jsonl')
STATE = os.path.join(OUT, '_batches.json')
REQUESTS_DUMP = os.path.join(OUT, '_requests.json')

API = 'https://api.anthropic.com/v1'
MODEL = 'claude-sonnet-5'
MAX_TOKENS = 6000        # the repo lane learned this the hard way: the model spends
                         # output tokens thinking before it writes, out of the same
                         # budget, and 3000 truncated 16 of 1433 records mid-string.
PER_BATCH = 400
MAX_ID_CHARS = 64
FACETS = ('kind', 'use_case', 'industry', 'sdv_component', 'sdv_concept', 'integration')

HEAD_CHARS = 3000        # byline, affiliations and abstract live in the first pages
ABSTRACT_CHARS = 1600
CONTEXT_CHARS = 2000
WINDOW = 600
MAX_WINDOWS = 14

TIER_CAP = {'full_text': 'high', 'abstract_context': 'medium', 'metadata_only': 'low'}
RANK = {'low': 0, 'medium': 1, 'high': 2}

# LOOSE to find. The tight pass is the model's job, not the packer's: a window that
# turns out to be "synthetic data variance" is evidence the model needs to see in
# order to answer name_collision.
FIND = re.compile(r'C?ct[- ]?GAN|CTGAN|CT-GAN|CctGAN|CTAB|TVAE|TV ?AE|\bSDV\b'
                  r'|Synthetic Data Vault|CopulaGAN|Gaussian ?Copula|sdmetrics|SDGym'
                  r'|deepecho|Veeramachaneni|Patki', re.I)

# The bibliography of a tabular-data paper is denser in SDV-family names than its
# body, so an evenly spread window sampler returns mostly reference entries -- four
# of the first six on the survey this was built against. A reference is a citation,
# never a use, so body passages are taken first and reference passages only fill the
# remainder, labelled as what they are.
BIBLIOGRAPHY = re.compile(r'^[ \t]*(?:\d+[.)]?[ \t]*)?'
                          r'(REFERENCES?|BIBLIOGRAPHY|LITERATURE CITED|WORKS CITED)'
                          r'[ \t]*:?[ \t]*$', re.I | re.M)


def split_bibliography(text):
    """(body, bibliography). The LAST heading in the second half wins: a paper's
    table of contents and its section headings both say References earlier on."""
    cut = None
    for match in BIBLIOGRAPHY.finditer(text):
        if match.start() > len(text) * 0.45:
            cut = match.start()
    if cut is None:
        return text, ''
    return text[:cut], text[cut:]


def windows_in(text, limit):
    """Passages around SDV-family mentions.

    Two passes, because the two failure modes pull opposite ways. Mentions that fall
    inside a window already taken are dropped, so a paragraph naming CTGAN four times
    costs one window rather than four. Then, if what survives still exceeds the
    budget, the windows are sampled EVENLY across the document rather than taking the
    first N -- otherwise a dense methods section spends the whole budget and the
    results tables, where a baseline is distinguished from a generator, never arrive.
    """
    spans, end = [], -1
    for match in FIND.finditer(text):
        if match.start() < end:
            continue
        start = max(0, match.start() - WINDOW // 3)
        end = start + WINDOW
        spans.append(text[start:end].replace('\n', ' '))
    if limit <= 0:
        return []
    if len(spans) <= limit:
        return spans
    step = len(spans) / float(limit)
    return [spans[min(len(spans) - 1, int(i * step))] for i in range(limit)]


# ---------------------------------------------------------------- vocabulary

def read_vocabularies():
    """Parse the controlled vocabularies out of docs/schema.md.

    Same source and same parse as tests/validate.py and auto_curate.py.
    """
    text = open(os.path.join(ROOT, 'docs', 'schema.md')).read()
    vocab = {}
    for facet in FACETS:
        match = re.search(r'\*\*' + facet + r'\*\*[^:]*:(.*?)(?:\n\s*\n)', text, re.S)
        if not match:
            sys.exit(f'docs/schema.md has no **{facet}** list; cannot build the prompt')
        body = re.sub(r'\([^)]*\)', ' ', match.group(1))
        vocab[facet] = sorted({t for t in re.split(r'[,\s]+', body)
                               if re.fullmatch(r'[a-z][a-z_]*', t or '')})
    return vocab


# ---------------------------------------------------------------- selection

def bare_doi(value):
    value = str(value or '').strip().lower()
    return re.sub(r'^https?://(dx\.)?doi\.org/', '', value)


def shard_dois():
    """Every DOI any shard owns, read from the SHARDS and not the built index.

    A retired entry -- one carrying duplicate_of -- is absent from
    data/sdv-index.json while its id and url are still owned by a shard. Filtering on
    the built index is exactly how the repo lane re-added two repositories that had
    been deliberately dropped.
    """
    found = set()
    for path in sorted(glob.glob(os.path.join(SHARDS, '*.json'))):
        try:
            records = json.load(open(path))
        except ValueError:
            continue
        if isinstance(records, dict):
            records = records.get('entries', records.get('records', []))
        for record in records or []:
            if not isinstance(record, dict):
                continue
            for key in ('doi', 'url'):
                value = bare_doi(record.get(key))
                if value.startswith('10.'):
                    found.add(value)
    return found


def existing_ids():
    entries = json.load(open(INDEX))
    if isinstance(entries, dict):
        entries = entries.get('entries', [])
    ids = {e.get('id') for e in entries if e.get('id')}
    for path in sorted(glob.glob(os.path.join(SHARDS, '*.json'))):
        try:
            records = json.load(open(path))
        except ValueError:
            continue
        if isinstance(records, dict):
            records = records.get('entries', records.get('records', []))
        for record in records or []:
            if isinstance(record, dict) and record.get('id'):
                ids.add(record['id'])
    return ids


def never_readd_dois():
    if not os.path.exists(NEVER):
        return set()
    data = json.load(open(NEVER))
    return {bare_doi(d) for d in data.get('dois', [])}


STOP = {'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'in', 'into',
        'is', 'of', 'on', 'or', 'the', 'to', 'with', 'using', 'via', 'towards',
        'toward', 'based', 'approach', 'study', 'novel', 'new', 'their', 'its',
        'that', 'this', 'these', 'through', 'over', 'under', 'between', 'data'}


def slug_for(title, year, kind, taken):
    """Deterministic id, assigned here and not by the model, matching the hand-made
    convention: paper-<three or four content words>-<year>."""
    words = [w for w in re.split(r'[^a-z0-9]+', (title or '').lower())
             if w and w not in STOP and len(w) > 2]
    stem = '-'.join(words[:4]) or 'untitled'
    prefix = 'preprint' if kind == 'preprint' else ('thesis' if kind == 'thesis'
                                                    else 'paper')
    suffix = f'-{year}' if year else ''
    candidate = trim(f'{prefix}-{stem}', reserve=len(suffix)) + suffix
    n = 2
    while candidate in taken:
        tag = f'-{n}{suffix}'
        candidate = trim(f'{prefix}-{stem}', reserve=len(tag)) + tag
        n += 1
    taken.add(candidate)
    return candidate


def trim(slug, reserve=0):
    limit = MAX_ID_CHARS - reserve
    if len(slug) <= limit:
        return slug
    cut = slug[:limit].rstrip('-')
    tail = cut.rfind('-')
    if tail > len('preprint-'):
        cut = cut[:tail]
    return cut.rstrip('-')


KIND_OF = {'preprint': 'preprint', 'dissertation': 'thesis', 'article': 'paper',
           'conference-paper': 'paper', 'review': 'paper', 'book-chapter': 'paper',
           'book': 'paper', 'peer-review': 'paper', 'report': 'paper'}


def reconstruct(inverted):
    """OpenAlex stores an abstract as word -> [positions]. Put it back in order."""
    if not isinstance(inverted, dict):
        return ''
    slots = {}
    for word, positions in inverted.items():
        for position in positions or []:
            slots[position] = word
    return ' '.join(slots[k] for k in sorted(slots))


def load_side_data():
    abstracts = json.load(open(ABSTRACTS)) if os.path.exists(ABSTRACTS) else {}
    contexts = collections.defaultdict(list)
    if os.path.exists(CONTEXTS):
        for edge in json.load(open(CONTEXTS)).get('edges', []):
            sentences = edge.get('contexts') or []
            if not sentences:
                continue
            key = bare_doi(edge.get('doi'))
            if key:
                for sentence in sentences:
                    contexts[key].append((edge.get('anchor'), sentence))
    return abstracts, contexts


def slug_for_doi(doi):
    return re.sub(r'[^a-z0-9]+', '_', doi.lower()).strip('_')


def full_text_for(doi):
    path = os.path.join(PAPERS, slug_for_doi(doi) + '.txt')
    if os.path.exists(path) and os.path.getsize(path) > 2000:
        return open(path, encoding='utf-8', errors='ignore').read()
    return None


def load_candidates(want_tiers=None):
    tail = json.load(open(TAIL))
    seen, works = set(), []
    for work in tail:                      # the tail carries 14 doubled records
        if work.get('id') in seen:
            continue
        seen.add(work['id'])
        works.append(work)
    works.sort(key=lambda w: -(w.get('cited_by_count') or 0))

    curated, blocked = shard_dois(), never_readd_dois()
    abstracts, contexts = load_side_data()
    done = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(RECORDS, '*.json'))}
    taken = existing_ids()

    candidates = []
    for work in works:
        doi = bare_doi(work.get('doi'))
        if not doi.startswith('10.') or doi in curated or doi in blocked:
            continue
        if slug_for_doi(doi) in done:
            continue
        text = full_text_for(doi)
        abstract = reconstruct(abstracts.get(work.get('id')))
        cites = contexts.get(doi) or []
        if text:
            tier = 'full_text'
        elif abstract or cites:
            tier = 'abstract_context'
        else:
            tier = 'metadata_only'
        if want_tiers and tier not in want_tiers:
            continue
        kind = KIND_OF.get(work.get('type'), 'paper')
        entry_id = slug_for(work.get('title'), work.get('publication_year'),
                            kind, taken)
        candidates.append({'doi': doi, 'id': entry_id, 'kind': kind, 'work': work,
                           'tier': tier, 'text': text, 'abstract': abstract,
                           'cites': cites})
    return candidates


# ---------------------------------------------------------------- the prompt

def system_prompt(vocab):
    return f"""You are curating one entry for the SDV index: an index of everything
connected to the Synthetic Data Vault (SDV), the open-source synthetic-data library
from MIT DAI Lab and DataCebo, and its family -- sdv, ctgan, rdt, sdmetrics, sdgym,
copulas, deepecho, tgan.

You are given the evidence for ONE published work that cites an SDV-family paper:
its metadata, the sentences in which it cites SDV where those are known, its abstract
where one exists, and passages from its full text around every SDV-family mention
where the full text was obtained. Judge only from that evidence. You cannot fetch
anything.

The evidence header states an EVIDENCE TIER. Take it seriously: it says how much of
the work you have actually seen. A judgment from an abstract is a judgment from an
abstract however confident the abstract sounds.

Return ONE JSON object and nothing else. No prose, no markdown fence.

Fields:
  title       the work's title as the evidence gives it
  summary     2-4 sentences: what the paper IS and what it contributes, then ENDING
              with the SDV clause
  venue       the journal or conference as printed, "" if the evidence does not say
  authors     the author list. Prefer the byline in the full text over the metadata
              list, which is truncated to one name on some small journals. [] if none.
  affiliations        aligned 1:1 with authors, null where unknown. [] if no authors.
                      An element may name several organisations separated by "; ".
  affiliation_types   one per DISTINCT ORGANISATION named in affiliations, in the order
                      they first appear -- not one per author. Allowed values:
                      academic, corporate, government, nonprofit, other, unknown.
                      MUST be [] when affiliations names no organisation at all.
  affiliation_countries  same alignment, full country names. [] under the same rule.
  sdv_component  {vocab['sdv_component']}
  sdv_concept    {vocab['sdv_concept']}
  use_case       {vocab['use_case']}
  industry       {vocab['industry']}
  integration    one of {vocab['integration']}
  importance     integer 0-5
  evidence       the specific proof, quoting the paper's own sentence where you can.
                 Under 400 characters. One good proof, not every occurrence.
  confidence     high | medium | low
  needs          optional; the open question or unresolved call, if any

THE SDV CLAUSE. The last sentence of the summary says why this work is in the index,
in two slots: which part of SDV is involved -- a component, a named synthesizer, or a
concept such as the conditional vector -- and how it is used: run as the generator,
run as one of several, benchmarked against, extended, or only cited. Write it from
the evidence, never from the title. Example of a whole summary:

  "Proposes a framework for detecting fraudulent transactions under extreme class
  imbalance, combining an autoencoder with a cost-sensitive classifier and evaluating
  on two public card-fraud datasets. CTGAN is run to oversample the minority class in
  the training split, and its output is compared against SMOTE and ADASYN. SDV's
  conditional tabular GAN is the generator producing the synthetic minority
  transactions the whole evaluation rests on."

INTEGRATION, the mechanism only:
  api_user        runs the library, or a synthesizer it ships, as part of the work
  derivative_work modifies SDV's own model -- its generator or critic losses, its
                  conditional vector, its architecture -- into a new model
  baseline_only   runs it only as a comparison baseline
  vendored_source carries an SDV-family source copy
  citation_only   cites it without running it
  inherited       SDV arrived inside a third-party library or dataset the authors used,
                  not by a decision to use SDV
  port            reimplements SDV's design in another language or framework
  name_collision  false positive; the match is not about SDV at all
  unclear         use suspected but unverifiable from this evidence

IMPORTANCE, independent of integration -- it scores how central SDV is to the work,
not how it arrived. Judging one from the other is the most common error.
  5 a named variant built on CTGAN, or the work is about SDV itself
  4 load-bearing: the whole empirical programme is SDV, or the headline result rests
    on SDV output
  3 one of several: one generator or metric among many
  2 contextual: SDV's method is described or adopted in prose, not run
  1 passing mention, an undifferentiated citation list in an off-domain paper
  0 name collision or unrelated
6 is reserved for first-party SDV-project work and is NOT available to you; a work
that genuinely looks first-party gets a `needs` saying so.

RULES THAT DECIDE MOST CASES. These come from a thousand hand-made judgments:
- TGAN (Xu & Veeramachaneni 2018) is a DIFFERENT work from CTGAN (2019). Check which
  is cited before keying anything to ctgan.
- ANY model set containing CopulaGAN is the SDV tabular API, library named or not:
  CopulaGAN ships only in SDV.
- CTGAN CONSTRUCTOR PARAMETER NAMES IN A HYPERPARAMETER TABLE PROVE the sdv-dev
  package was run, with no library named: embedding_dim, generator_dim,
  discriminator_dim, generator_lr, discriminator_lr, generator_decay,
  discriminator_decay, discriminator_steps.
- The ADOPTED-BUT-NOT-RUN pattern -- CTGAN's mode-specific normalization or its
  conditional design implemented in the authors' own prose while a different
  generator runs, or no experiment at all -- is citation_only 2, not baseline_only.
- "Positions itself against CTGAN" is not "builds on CTGAN". Look for an actual
  results row before calling anything baseline_only or derivative_work.
- A compound name containing a CTGAN-ish token predicts COMPOSITION more often than
  derivation: a pipeline that runs CTGAN unmodified as one stage is api_user, not
  derivative_work.
- Where a paper proposes no generator of its own -- a benchmark or comparative study
  -- the generators it runs are evaluation SUBJECTS, so api_user; importance follows
  how much of the empirical programme is SDV.
- Benchmarking a DESCENDANT (CTAB-GAN+, DP-CTGAN, table-GAN) rather than CTGAN itself
  is citation_only, unless the descendant is run through SDV.
- A paper that runs a generator only to reject it still counts as baseline_only.
- MIS-CITATION IS COMMON IN THIS LITERATURE and is not yours to fix: CTGAN cited to
  Goodfellow, RDT credited to an unrelated paper, TVAE glossed wrongly. Record the
  paper's own wording in evidence and never correct it silently.
- INDUSTRY IS THE DOMAIN THE WORK IS ABOUT, not the kind of institution that wrote
  it. A university paper about card fraud is finance_insurance. `academia` is the
  last resort, for work whose only subject is scholarship itself; a methods paper
  with no single domain is cross_industry.
- unclear may never carry confidence high.
- If the evidence is too thin to judge, say so in `needs` and use low rather than
  guessing. A flagged entry is useful; a confident wrong one poisons the index.
- Never invent a facet value outside the lists above. If nothing fits, use the
  closest and put the proposed value in `needs`.

TWO TRAPS IN THE EXTRACTED TEXT ITSELF, both of which have produced wrong judgments:
- The text comes from a PDF, so ligatures and spacing break words. "TV AE" is TVAE,
  and CTGAN sometimes extracts as "CctGAN". But "DistV AE" and "SurvivalV AE" are
  NOT TVAE, and "SDV" also abbreviates "synthetic data variance" and other phrases.
- A passage may come from the reference list rather than the body. A bibliography
  entry is a citation, not a use."""


def pack_evidence(candidate):
    work = candidate['work']
    parts = [f"evidence tier: {candidate['tier']} "
             f"(confidence is capped at {TIER_CAP[candidate['tier']]} for this tier)"]
    meta = {'title': work.get('title'), 'doi': candidate['doi'],
            'year': work.get('publication_year'), 'type': work.get('type'),
            'cited_by_count': work.get('cited_by_count'),
            'openalex_authors': [a.get('author', {}).get('display_name')
                                 for a in (work.get('authorships') or [])][:40],
            'cites_which_sdv_papers': work.get('cites_anchors')}
    parts.append('metadata:\n' + json.dumps(meta, indent=1, ensure_ascii=False))

    if candidate['cites']:
        lines, used = [], 0
        for anchor, sentence in candidate['cites']:
            block = f'  [cites {anchor}] {sentence.strip()[:600]}'
            if used + len(block) > CONTEXT_CHARS:
                break
            lines.append(block)
            used += len(block)
        parts.append('sentences in which this work cites an SDV paper:\n'
                     + '\n'.join(lines))

    if candidate['abstract']:
        parts.append('abstract:\n' + candidate['abstract'][:ABSTRACT_CHARS])

    text = candidate['text']
    if text:
        parts.append('first page of the full text (byline and affiliations '
                     'live here):\n' + text[:HEAD_CHARS])
        body, bibliography = split_bibliography(text)
        windows = windows_in(body, MAX_WINDOWS)
        if windows:
            parts.append(f'passages around SDV-family mentions in the BODY '
                         f'({len(windows)} of them, in document order):\n'
                         + '\n---\n'.join('  ' + w for w in windows))
        cited = windows_in(bibliography, max(0, MAX_WINDOWS - len(windows) - 6))
        if cited:
            parts.append(f'passages from the REFERENCE LIST ({len(cited)}). These '
                         f'establish what is cited, never what is run:\n'
                         + '\n---\n'.join('  ' + w for w in cited))
        if not windows and not cited:
            parts.append('passages around SDV-family mentions: NONE. The full text '
                         'was read and no SDV-family term appears in it. This is '
                         'evidence in itself -- consider name_collision or a '
                         'citation that the extraction lost.')
    else:
        parts.append('full text: NOT OBTAINED. Judge from the metadata, the citing '
                     'sentences and the abstract only, and say so in `needs` if that '
                     'is not enough to place the work.')
    return '\n\n'.join(parts)


def build_request(candidate, vocab):
    return {
        'custom_id': candidate['id'],
        'params': {
            'model': MODEL,
            'max_tokens': MAX_TOKENS,
            'system': system_prompt(vocab),
            'messages': [{'role': 'user', 'content': pack_evidence(candidate)}],
        },
    }


# ---------------------------------------------------------------- validation

REQUIRED = ('title', 'summary', 'authors', 'affiliations', 'affiliation_types',
            'affiliation_countries', 'sdv_component', 'sdv_concept', 'use_case',
            'industry', 'integration', 'importance', 'evidence', 'confidence')


def parse_record(text):
    text = (text or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('no JSON object in the response')
    return json.loads(text[start:end + 1])


def validate(record, candidate, vocab):
    problems = []
    for field in REQUIRED:
        if field not in record:
            problems.append(f'missing field {field}')
    if problems:
        return problems

    for facet in ('sdv_component', 'sdv_concept', 'use_case', 'industry'):
        values = record.get(facet)
        if not isinstance(values, list):
            problems.append(f'{facet} is not a list')
            continue
        for value in values:
            if value not in vocab[facet]:
                problems.append(f'{facet}: {value!r} is not in the vocabulary')

    integration = record.get('integration')
    # Same waiver as the repo lane, and for the same reason: a work that only cites
    # SDV has no use case for synthetic data, and demanding one invites invention.
    NO_USE_CASE = ('name_collision', 'citation_only', 'unclear')
    if integration not in NO_USE_CASE and not record.get('use_case'):
        problems.append('use_case is empty')
    if integration != 'name_collision' and not record.get('industry'):
        problems.append('industry is empty')
    if integration not in vocab['integration']:
        problems.append(f'integration: {integration!r} is not in the vocabulary')

    importance = record.get('importance')
    if not isinstance(importance, int) or not 0 <= importance <= 5:
        problems.append(f'importance {importance!r} is not an integer 0-5')

    confidence = record.get('confidence')
    if confidence not in ('high', 'medium', 'low'):
        problems.append(f'confidence {confidence!r} is not high/medium/low')
    if integration == 'unclear' and confidence == 'high':
        problems.append('unclear may not carry confidence high')

    summary = record.get('summary') or ''
    if not isinstance(summary, str) or not 40 <= len(summary) <= 1600:
        problems.append(f'summary is {len(summary)} chars, outside 40-1600')
    elif not summary.rstrip().endswith(('.', '!', '?')):
        problems.append('summary does not end in a sentence')
    if not (record.get('evidence') or '').strip():
        problems.append('evidence is empty')

    authors = record.get('authors')
    affiliations = record.get('affiliations')
    if not isinstance(authors, list) or not isinstance(affiliations, list):
        problems.append('authors/affiliations are not both lists')
    elif len(authors) != len(affiliations):
        problems.append(f'{len(authors)} authors but {len(affiliations)} affiliations')
    elif any(not isinstance(a, str) or not a.strip() for a in authors):
        problems.append('an author is empty or not a string')
    for value in record.get('affiliation_types') or []:
        if value not in ('academic', 'corporate', 'government', 'nonprofit',
                         'other', 'unknown'):
            problems.append(f'affiliation_type {value!r} is not in the vocabulary')

    organizations, seen = [], set()
    for affiliation in record.get('affiliations') or []:
        if not affiliation or not isinstance(affiliation, str):
            continue
        for organization in (part.strip() for part in affiliation.split(';')):
            if organization and organization not in seen:
                seen.add(organization)
                organizations.append(organization)
    for field in ('affiliation_types', 'affiliation_countries'):
        values = record.get(field) or []
        if len(values) > len(organizations):
            problems.append(f'{field} has {len(values)} values but affiliations names '
                            f'{len(organizations)} organization(s)')
    return problems


def finalize(record, candidate):
    """Fill the fields the script owns rather than the model, and apply the cap.

    The confidence cap is applied HERE rather than being rejected in validate(),
    because a capped record is correct, not faulty: the model's judgment stands and
    only its claim to have read the source is corrected. A rejection would send
    hundreds of good records to the review queue for a thing the script can fix.
    """
    out = {'id': candidate['id'],
           'title': record.get('title') or candidate['work'].get('title'),
           'url': f'https://doi.org/{candidate["doi"]}',
           'doi': f'https://doi.org/{candidate["doi"]}',
           'kind': candidate['kind']}
    for field in REQUIRED[1:]:
        out[field] = record[field]
    if record.get('venue'):
        out['venue'] = record['venue']
    if record.get('needs'):
        out['needs'] = record['needs']

    cap = TIER_CAP[candidate['tier']]
    if RANK[out['confidence']] > RANK[cap]:
        out['confidence'] = cap
    out['evidence_tier'] = candidate['tier']
    out['source_channel'] = 'semantic_scholar_discovery'
    out['auto_curated'] = {'model': MODEL, 'reviewed': False}
    return out


def write_result(candidate, text, vocab, usage=None):
    os.makedirs(RECORDS, exist_ok=True)
    try:
        parsed = parse_record(text)
        problems = validate(parsed, candidate, vocab)
    except Exception as exc:
        parsed, problems = None, [f'{type(exc).__name__}: {exc}']

    if problems:
        with open(REVIEW, 'a') as fh:
            fh.write(json.dumps({'doi': candidate['doi'], 'id': candidate['id'],
                                 'tier': candidate['tier'], 'problems': problems,
                                 'raw': (text or '')[:4000]}, ensure_ascii=False) + '\n')
        return None

    record = finalize(parsed, candidate)
    if usage:
        record['auto_curated']['usage'] = usage
    with open(os.path.join(RECORDS, slug_for_doi(candidate['doi']) + '.json'), 'w') as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
    return record


def do_recover(vocab):
    """Re-validate stored responses against the CURRENT rules; no API call."""
    if not os.path.exists(REVIEW):
        print('no review file'); return
    with open(REVIEW) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    by_doi = {c['doi']: c for c in load_candidates()}

    promoted, remaining = [], []
    for row in rows:
        candidate = by_doi.get(row['doi'])
        if candidate is None:              # already curated by a later run
            continue
        try:
            parsed = parse_record(row.get('raw'))
            problems = validate(parsed, candidate, vocab)
        except Exception as exc:
            problems = [f'{type(exc).__name__}: {exc}']
        if problems:
            row['problems'] = problems
            remaining.append(row)
            continue
        record = finalize(parsed, candidate)
        os.makedirs(RECORDS, exist_ok=True)
        with open(os.path.join(RECORDS, slug_for_doi(row['doi']) + '.json'), 'w') as fh:
            json.dump(record, fh, indent=1, ensure_ascii=False)
        promoted.append(row['doi'])

    with open(REVIEW, 'w') as fh:
        for row in remaining:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'{len(promoted)} promoted to records/, {len(remaining)} still in review')
    reasons = collections.Counter(str(p)[:60] for row in remaining
                                  for p in row['problems'])
    for reason, count in reasons.most_common():
        print(f'  {count:4d}  {reason}')


# ---------------------------------------------------------------- http

def call(method, path, payload=None, tries=6):
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        sys.exit('set ANTHROPIC_API_KEY first')
    url = path if path.startswith('http') else f'{API}{path}'
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers={
        'x-api-key': key,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'user-agent': 'sdvworld-index-paper-curate',
    })
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:300]
            if exc.code in (429, 500, 502, 503, 504, 529):
                wait = min(300, 10 * 2 ** attempt)
                print(f'    {exc.code}; sleeping {wait}s  {detail[:120]}')
                time.sleep(wait)
                continue
            sys.exit(f'{exc.code} {detail}')
        except Exception as exc:
            print(f'    {type(exc).__name__}; retrying in 20s')
            time.sleep(20)
    sys.exit('gave up after repeated failures')


# ---------------------------------------------------------------- modes

def do_tiers(want):
    candidates = load_candidates(want)
    counts = collections.Counter(c['tier'] for c in candidates)
    print(f'{len(candidates)} uncurated works')
    for tier in ('full_text', 'abstract_context', 'metadata_only'):
        print(f'  {counts.get(tier, 0):5d}  {tier}  '
              f'(confidence capped at {TIER_CAP[tier]})')
    sizes = [len(pack_evidence(c)) for c in candidates[:200]]
    if sizes:
        print(f'\nevidence payload over the first 200: '
              f'{sum(sizes) // len(sizes)} chars average '
              f'(~{sum(sizes) // len(sizes) // 4} tokens), max {max(sizes)}')


def do_pilot(count, vocab, want, dump):
    candidates = load_candidates(want)
    picked = []
    for tier in ('full_text', 'abstract_context', 'metadata_only'):
        if want and tier not in want:
            continue
        picked += [c for c in candidates if c['tier'] == tier][:count]
    print(f'{len(candidates)} candidates; piloting {len(picked)}\n')
    for candidate in picked:
        if dump:
            print('=' * 78)
            print(candidate['id'], candidate['tier'])
            print(pack_evidence(candidate))
            continue
        request = build_request(candidate, vocab)
        response = json.loads(call('POST', '/messages', request['params']))
        text = ''.join(b.get('text', '') for b in response.get('content', []))
        record = write_result(candidate, text, vocab, response.get('usage'))
        print('=' * 78)
        print(candidate['id'], candidate['tier'], '->',
              'OK' if record else 'NEEDS REVIEW', json.dumps(response.get('usage')))
        print(json.dumps(record, indent=1, ensure_ascii=False) if record
              else (text or '')[:1500])
        time.sleep(1)
    if not dump:
        print(f'\nrecords in {RECORDS}, failures in {REVIEW}')


def do_submit(vocab, dry_run, limit, want):
    candidates = load_candidates(want)
    if limit:
        candidates = candidates[:limit]
    if not candidates:
        return print('nothing to submit')
    requests_ = [build_request(c, vocab) for c in candidates]
    os.makedirs(OUT, exist_ok=True)

    if dry_run:
        with open(REQUESTS_DUMP, 'w') as fh:
            json.dump(requests_, fh, indent=1, ensure_ascii=False)
        chars = sum(len(r['params']['messages'][0]['content']) for r in requests_)
        print(f'{len(requests_)} requests, '
              f'{os.path.getsize(REQUESTS_DUMP) / 1e6:.1f} MB total, '
              f'{chars // len(requests_)} chars of evidence each '
              f'(~{chars // len(requests_) // 4} tokens)')
        print(f'wrote {REQUESTS_DUMP}; sent nothing')
        return

    state = json.load(open(STATE)) if os.path.exists(STATE) else {'batches': [],
                                                                  'dois': {}}
    state['dois'].update({c['id']: c['doi'] for c in candidates})
    for start in range(0, len(requests_), PER_BATCH):
        chunk = requests_[start:start + PER_BATCH]
        result = json.loads(call('POST', '/messages/batches', {'requests': chunk}))
        state['batches'].append({'id': result['id'], 'n': len(chunk),
                                 'created': result.get('created_at'),
                                 'collected': False})
        json.dump(state, open(STATE, 'w'), indent=1)
        print(f'  submitted {result["id"]}  {len(chunk)} requests')
    print(f'\n{len(state["batches"])} batches recorded in {STATE}')
    print('come back and run --status, then --collect')


def load_state():
    if not os.path.exists(STATE):
        sys.exit(f'no {STATE}; run --submit first')
    return json.load(open(STATE))


def do_status():
    for batch in load_state()['batches']:
        info = json.loads(call('GET', f'/messages/batches/{batch["id"]}'))
        print(f'{batch["id"]}  {info.get("processing_status"):12s} '
              f'{json.dumps(info.get("request_counts", {}))}  '
              f'collected={batch["collected"]}')


def do_collect(vocab):
    state = load_state()
    dois = state.get('dois', {})
    by_doi = {c['doi']: c for c in load_candidates()}
    written = failed = 0
    for batch in state['batches']:
        if batch['collected']:
            continue
        info = json.loads(call('GET', f'/messages/batches/{batch["id"]}'))
        if info.get('processing_status') != 'ended':
            print(f'{batch["id"]}: {info.get("processing_status")}, skipping')
            continue
        for line in call('GET', info['results_url']).splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry_id = row.get('custom_id')
            candidate = by_doi.get(dois.get(entry_id, ''))
            result = row.get('result') or {}
            if candidate is None or result.get('type') != 'succeeded':
                with open(REVIEW, 'a') as fh:
                    fh.write(json.dumps(
                        {'doi': dois.get(entry_id, ''), 'id': entry_id,
                         'tier': candidate['tier'] if candidate else None,
                         'problems': [f'batch result {result.get("type")}'
                                      if candidate else 'candidate no longer in pool'],
                         'raw': json.dumps(result)[:2000]}) + '\n')
                failed += 1
                continue
            message = result.get('message') or {}
            text = ''.join(b.get('text', '') for b in message.get('content', []))
            if write_result(candidate, text, vocab, message.get('usage')):
                written += 1
            else:
                failed += 1
        batch['collected'] = True
        json.dump(state, open(STATE, 'w'), indent=1)
        print(f'{batch["id"]}: collected')
    print(f'\n{written} records written to {RECORDS}')
    print(f'{failed} sent to {REVIEW}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=int, metavar='N',
                        help='N per tier, live calls, no batch')
    parser.add_argument('--dump', action='store_true',
                        help='with --pilot: print the packed evidence, call nothing')
    parser.add_argument('--tier', action='append',
                        help='restrict to an evidence tier; repeatable')
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--tiers', action='store_true',
                        help='count the evidence tiers and size the payload')
    parser.add_argument('--recover', action='store_true',
                        help='re-validate needs-review.jsonl against the current '
                             'rules and promote what now passes; makes no API call')
    args = parser.parse_args()

    want = set(args.tier) if args.tier else None
    if want and not want <= set(TIER_CAP):
        parser.error(f'--tier must be one of {sorted(TIER_CAP)}')

    if args.tiers:
        return do_tiers(want)
    vocab = read_vocabularies()
    if args.pilot:
        do_pilot(args.pilot, vocab, want, args.dump)
    elif args.submit:
        do_submit(vocab, args.dry_run, args.limit, want)
    elif args.status:
        do_status()
    elif args.collect:
        do_collect(vocab)
    elif args.recover:
        do_recover(vocab)
    else:
        parser.error('pick one of --pilot N, --submit, --status, --collect, '
                     '--recover, --tiers')


if __name__ == '__main__':
    main()
