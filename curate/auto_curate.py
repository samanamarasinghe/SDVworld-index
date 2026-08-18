#!/usr/bin/env python3
"""Curate the uncurated GitHub repo tail from harvested evidence, via the Batch API.

    python3 curate/auto_curate.py --pilot 5          # live calls now, print, no batch
    python3 curate/auto_curate.py --submit --dry-run # build requests, write, send nothing
    python3 curate/auto_curate.py --submit           # create the batches
    python3 curate/auto_curate.py --status           # poll
    python3 curate/auto_curate.py --collect          # write records from finished batches

Needs ANTHROPIC_API_KEY. Batch requests are processed asynchronously at half rate,
which is why there is no delay knob: nothing runs locally between submit and collect,
so there is no local rate to pace. The live paths retry with exponential backoff.

Input is harvest/evidence/*.json, one record per repository, written by
harvest/repo_evidence.py. Repositories that already have an index entry, and those
listed in curate/never-readd.json, are excluded -- past drop decisions are invisible
in the index and would otherwise be silently re-added.

Output is STAGING, not shards: one record per repository under
curate/auto-shards/records/, and everything that fails validation in
curate/auto-shards/needs-review.jsonl with the reasons. Nothing here is an index
entry until a human moves it into data/shards/.

What this does NOT do, and must be done by hand afterwards: the cross-record work.
No duplicate sweep, no detection that two repositories are the same project, no
check against open questions. Each request sees one repository and nothing else.
"""
import argparse
import glob
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, 'harvest', 'evidence')
POOL = os.path.join(ROOT, 'data', 'tail', 'github-repos.json')
INDEX = os.path.join(ROOT, 'data', 'sdv-index.json')
NEVER = os.path.join(ROOT, 'curate', 'never-readd.json')
OUT = os.path.join(ROOT, 'curate', 'auto-shards')
RECORDS = os.path.join(OUT, 'records')
REVIEW = os.path.join(OUT, 'needs-review.jsonl')
STATE = os.path.join(OUT, '_batches.json')
REQUESTS_DUMP = os.path.join(OUT, '_requests.json')

API = 'https://api.anthropic.com/v1'
MODEL = 'claude-sonnet-5'
MAX_TOKENS = 1500
PER_BATCH = 400          # keeps each POST near 10 MB; the API ceiling is far higher
FACETS = ('kind', 'use_case', 'industry', 'sdv_component', 'sdv_concept', 'integration')

README_CHARS = 6000
HITS_PER_CODE = 3
EVIDENCE_CHARS = 9000


# ---------------------------------------------------------------- vocabulary

def read_vocabularies():
    """Parse the controlled vocabularies out of README.md.

    Same source and same parse as tests/validate.py, deliberately: if the two
    disagreed, this script would happily produce records validation rejects.
    """
    text = open(os.path.join(ROOT, 'README.md')).read()
    vocab = {}
    for facet in FACETS:
        match = re.search(r'\*\*' + facet + r'\*\*[^:]*:(.*?)(?:\n\s*\n)', text, re.S)
        if not match:
            sys.exit(f'README.md has no **{facet}** list; cannot build the prompt')
        body = re.sub(r'\([^)]*\)', ' ', match.group(1))
        vocab[facet] = sorted({t for t in re.split(r'[,\s]+', body)
                               if re.fullmatch(r'[a-z][a-z_]*', t or '')})
    return vocab


# ---------------------------------------------------------------- selection

def indexed_repos():
    entries = json.load(open(INDEX))
    if isinstance(entries, dict):
        entries = entries.get('entries', [])
    pattern = re.compile(r'https?://(?:www\.)?github\.com/([^/#?]+)/([^/#?]+)')
    found = set()
    for entry in entries:
        match = pattern.match(entry.get('url') or '')
        if match:
            found.add(f'{match.group(1)}/{match.group(2)}'.removesuffix('.git').lower())
    return found


def existing_ids():
    entries = json.load(open(INDEX))
    if isinstance(entries, dict):
        entries = entries.get('entries', [])
    return {e.get('id') for e in entries if e.get('id')}


def never_readd():
    if not os.path.exists(NEVER):
        return set()
    data = json.load(open(NEVER))
    return {r.lower() for r in data.get('repos', [])}


def slug_for(repo, taken):
    """Deterministic id, assigned here rather than by the model, so two records can
    never collide on one and so a re-run reproduces the same ids."""
    owner, name = repo.split('/', 1)
    base = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'repo'
    candidate = f'repo-{base}'
    if candidate in taken:
        owner_slug = re.sub(r'[^a-z0-9]+', '-', owner.lower()).strip('-')
        candidate = f'repo-{owner_slug}-{base}'
    suffix = 2
    while candidate in taken:
        candidate = f'repo-{base}-{suffix}'
        suffix += 1
    taken.add(candidate)
    return candidate


def load_candidates():
    pool = {r['repo']: r for r in json.load(open(POOL))['repos']}
    curated, blocked = indexed_repos(), never_readd()
    taken = existing_ids()
    done = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(RECORDS, '*.json'))}

    candidates = []
    for path in sorted(glob.glob(os.path.join(EVIDENCE, '*.json'))):
        record = json.load(open(path))
        repo = record.get('repo', '')
        if record.get('status') != 'ok':
            continue
        if repo.lower() in curated or repo.lower() in blocked:
            continue
        if repo.replace('/', '__') in done:
            continue
        candidates.append((repo, record, pool.get(repo, {})))

    ids = {}                               # assigned in a stable order
    for repo, _, _ in candidates:
        ids[repo] = slug_for(repo, taken)
    return [(repo, ids[repo], ev, metrics) for repo, ev, metrics in candidates]


# ---------------------------------------------------------------- the prompt

def system_prompt(vocab):
    return f"""You are curating one entry for the SDV index: an index of everything
connected to the Synthetic Data Vault (SDV), the open-source synthetic-data library
from MIT DAI Lab and DataCebo, and its family -- sdv, ctgan, rdt, sdmetrics, sdgym,
copulas, deepecho, tgan.

You are given the harvested evidence for ONE GitHub repository: its README, its
dependency declarations, and every line in it matching an SDV usage pattern with
surrounding context. Judge only from that evidence. You cannot fetch anything.

Return ONE JSON object and nothing else. No prose, no markdown fence.

Fields:
  title       the repository's real name as its README presents it, not the slug
  summary     1-3 sentences, written from the evidence, saying what the repository IS
              and then ENDING with the SDV clause
  authors     real named people, from a README byline or citation block only. Never
              GitHub handles, bots or organisation names. [] if none are named.
  affiliations        aligned 1:1 with authors, null where unknown. [] if no authors.
  affiliation_types   [] unless the README states an organisation outright
  affiliation_countries  same
  sdv_component  {vocab['sdv_component']}
  sdv_concept    {vocab['sdv_concept']}
  use_case       {vocab['use_case']}
  industry       {vocab['industry']}
  integration    one of {vocab['integration']}
  importance     integer 0-5
  evidence       the specific proof: file path with line numbers, or a quoted line
  confidence     high | medium | low
  needs          optional; the open question or unresolved call, if any

THE SDV CLAUSE. The last sentence of the summary says why this repository is in the
index, in two slots: which part of SDV is involved (a component or a file path), and
how it is used -- run, vendored, extended, compared against, or only mentioned. Write
it from the evidence, never from the repository name. Example of a whole summary:

  "An NLP question-answering system over drilling reports from oil and gas
  operations. The reports are confidential, so Synthetic_Data_Generation.ipynb fits a
  GaussianCopulaSynthesizer on the structured drilling fields to manufacture a working
  dataset. SDV's copula synthesizer is run to stand in for operational data that
  cannot be published."

INTEGRATION, the mechanism only:
  api_user        imports and calls the library
  vendored_source copies SDV-family source in-tree
  derivative_work extends or modifies that source into a new tool
  baseline_only   runs it only as a comparison baseline
  agent_skill     packages SDV as a capability an AI agent invokes on demand
  citation_only   mentions but does not run it
  inherited       SDV arrived inside a vendored third party, not by a decision to embed
  port            reimplements SDV's design in another language, carrying no SDV source
  name_collision  false positive, unrelated to SDV
  unclear         use suspected but unverifiable from this evidence

IMPORTANCE, independent of integration -- it scores how central SDV is, not how it
arrived. Judging one from the other is the most common error.
  5 SDV is the work: a fork, a reimplementation, a language binding
  4 load-bearing: remove SDV and the repository does not stand
  3 one of several: one generator or metric among many
  2 contextual: SDV's method is described or adopted, not run
  1 passing mention
  0 name collision or unrelated
6 is reserved for first-party SDV-project work and is NOT available to you; a
repository that genuinely looks first-party gets a `needs` saying so.

RULES THAT DECIDE MOST CASES:
- A dependency line in requirements.txt with no call anywhere in the code is
  citation_only or unclear, not api_user. Importing is not using.
- Any model set containing CopulaGAN is the SDV tabular API even if no library is named.
- TGAN (Xu & Veeramachaneni 2018) is a DIFFERENT work from CTGAN. Key the component to
  what the evidence actually shows.
- A repository that carries an in-tree copy of ctgan/, sdv/, rdt/ or copulas/ is
  vendored_source, and if it only vendors a bundle it never calls, say so in `needs`.
- A tutorial or course exercise that runs SDV is still api_user; importance 3 at most.
- Prefer the domain over `academia` for industry; use academia only if nothing else fits.
- unclear may never carry confidence high.
- confidence high only where the evidence shows a call site. A README claim alone is
  medium. If the evidence is too thin to judge, say so in `needs` and use low rather
  than guessing -- a flagged entry is useful, a confident wrong one poisons the index.
- Never invent a facet value outside the lists above. If nothing fits, use the closest
  and put the proposed value in `needs`."""


def pack_evidence(repo, ev, metrics):
    parts = [f'repository: {repo}', f'url: https://github.com/{repo}']
    facts = {k: metrics.get(k) for k in
             ('stars', 'forks', 'commits', 'contributors', 'language', 'license',
              'created', 'pushed', 'is_archived', 'homepage', 'pypi_package',
              'hit_patterns', 'owner_type')}
    parts.append('pool metrics: ' + json.dumps({k: v for k, v in facts.items() if v}))
    if metrics.get('description'):
        parts.append('description: ' + metrics['description'][:400])
    if metrics.get('topics'):
        parts.append('topics: ' + ', '.join(metrics['topics'][:20]))
    if ev.get('vendored_dirs'):
        parts.append('directories that look like a vendored SDV-family copy: '
                     + ', '.join(ev['vendored_dirs'][:20]))

    deps = ev.get('dependencies') or {}
    if deps:
        lines = []
        for path, entries in list(deps.items())[:6]:
            for entry in entries[:6]:
                lines.append(f'  {path}: {entry[:160]}')
        parts.append('dependency declarations mentioning the SDV family:\n'
                     + '\n'.join(lines[:24]))

    hits = ev.get('hits') or {}
    if hits:
        # One import line matches several patterns, so the same file:line arrives
        # once per code with near-identical context. Deduplicate on the location and
        # carry the codes together, or a third of the payload is the same nine lines.
        seen = {}
        for code, entries in hits.items():
            for entry in entries[:HITS_PER_CODE]:
                key = (entry.get('file'), entry.get('line'))
                if key in seen:
                    seen[key]['codes'].append(code)
                else:
                    seen[key] = {'codes': [code], 'entry': entry}
        chunk, used = [], 0
        for (path, line), item in seen.items():
            entry = item['entry']
            block = (f'  [{",".join(sorted(set(item["codes"])))}] {path}:{line}\n'
                     + '\n'.join('    ' + c[:160]
                                  for c in (entry.get('context') or [])[:9]))
            if used + len(block) > EVIDENCE_CHARS:
                break
            chunk.append(block)
            used += len(block)
        parts.append('pattern hits with context:\n' + '\n'.join(chunk))
    else:
        parts.append('pattern hits: NONE. Nothing in the code matched an SDV pattern.')

    readme = (ev.get('readme') or '').strip()
    parts.append('README (truncated):\n' + (readme[:README_CHARS] if readme
                                            else '(no README in the repository)'))
    return '\n\n'.join(parts)


def build_request(repo, entry_id, ev, metrics, vocab):
    return {
        'custom_id': entry_id,
        'params': {
            'model': MODEL,
            'max_tokens': MAX_TOKENS,
            'system': system_prompt(vocab),
            'messages': [{'role': 'user', 'content': pack_evidence(repo, ev, metrics)}],
        },
    }


# ---------------------------------------------------------------- validation

REQUIRED = ('title', 'summary', 'authors', 'affiliations', 'affiliation_types',
            'affiliation_countries', 'sdv_component', 'sdv_concept', 'use_case',
            'industry', 'integration', 'importance', 'evidence', 'confidence')


def parse_record(text):
    text = (text or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)   # a fence, occasionally
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('no JSON object in the response')
    return json.loads(text[start:end + 1])


def validate(record, repo, entry_id, vocab):
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
    if not record.get('use_case'):
        problems.append('use_case is empty')
    if not record.get('industry'):
        problems.append('industry is empty')

    integration = record.get('integration')
    if integration not in vocab['integration']:
        problems.append(f'integration: {integration!r} is not in the vocabulary')
    if integration != 'name_collision' and not record.get('sdv_component'):
        problems.append('sdv_component is empty on a record that is not name_collision')

    importance = record.get('importance')
    if not isinstance(importance, int) or not 0 <= importance <= 5:
        problems.append(f'importance {importance!r} is not an integer 0-5')

    confidence = record.get('confidence')
    if confidence not in ('high', 'medium', 'low'):
        problems.append(f'confidence {confidence!r} is not high/medium/low')
    if integration == 'unclear' and confidence == 'high':
        problems.append('unclear may not carry confidence high')

    summary = record.get('summary') or ''
    if not isinstance(summary, str) or not 40 <= len(summary) <= 1400:
        problems.append(f'summary is {len(summary)} chars, outside 40-1400')
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
    return problems


def finalize(record, repo, entry_id):
    """Fill the fields the script owns rather than the model."""
    out = {'id': entry_id, 'title': record.get('title') or repo.split('/', 1)[1],
           'url': f'https://github.com/{repo}', 'kind': 'code_repo'}
    for field in REQUIRED[1:]:
        out[field] = record[field]
    if record.get('needs'):
        out['needs'] = record['needs']
    out['source_channel'] = 'github_code_search'
    out['auto_curated'] = {'model': MODEL, 'reviewed': False}
    return out


def write_result(repo, entry_id, text, vocab, usage=None):
    os.makedirs(RECORDS, exist_ok=True)
    try:
        parsed = parse_record(text)
        problems = validate(parsed, repo, entry_id, vocab)
    except Exception as exc:
        parsed, problems = None, [f'{type(exc).__name__}: {exc}']

    if problems:
        with open(REVIEW, 'a') as fh:
            fh.write(json.dumps({'repo': repo, 'id': entry_id, 'problems': problems,
                                 'raw': (text or '')[:4000]}, ensure_ascii=False) + '\n')
        return None

    record = finalize(parsed, repo, entry_id)
    if usage:
        record['auto_curated']['usage'] = usage
    path = os.path.join(RECORDS, repo.replace('/', '__') + '.json')
    with open(path, 'w') as fh:
        json.dump(record, fh, indent=1, ensure_ascii=False)
    return record


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
        'user-agent': 'sdvworld-index-auto-curate',
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

def do_pilot(count, seed, vocab):
    candidates = load_candidates()
    random.Random(seed).shuffle(candidates)
    picked = candidates[:count]
    print(f'{len(candidates)} candidates; piloting {len(picked)}\n')
    for repo, entry_id, ev, metrics in picked:
        request = build_request(repo, entry_id, ev, metrics, vocab)
        response = json.loads(call('POST', '/messages', request['params']))
        text = ''.join(b.get('text', '') for b in response.get('content', []))
        usage = response.get('usage')
        record = write_result(repo, entry_id, text, vocab, usage)
        print('=' * 78)
        print(repo, '->', 'OK' if record else 'NEEDS REVIEW', json.dumps(usage))
        print(json.dumps(record, indent=1, ensure_ascii=False) if record
              else (text or '')[:1500])
        time.sleep(1)
    print(f'\nrecords in {RECORDS}, failures in {REVIEW}')


def do_submit(vocab, dry_run, limit):
    candidates = load_candidates()
    if limit:
        candidates = candidates[:limit]
    if not candidates:
        return print('nothing to submit')
    requests_ = [build_request(repo, entry_id, ev, metrics, vocab)
                 for repo, entry_id, ev, metrics in candidates]
    lookup = {entry_id: repo for repo, entry_id, _, _ in candidates}
    os.makedirs(OUT, exist_ok=True)

    if dry_run:
        with open(REQUESTS_DUMP, 'w') as fh:
            json.dump(requests_, fh, indent=1, ensure_ascii=False)
        size = os.path.getsize(REQUESTS_DUMP)
        chars = sum(len(r['params']['messages'][0]['content']) for r in requests_)
        print(f'{len(requests_)} requests, {size / 1e6:.1f} MB total, '
              f'{chars // len(requests_)} chars of evidence each (~'
              f'{chars // len(requests_) // 4} tokens)')
        print(f'wrote {REQUESTS_DUMP}; sent nothing')
        return

    state = json.load(open(STATE)) if os.path.exists(STATE) else {'batches': [],
                                                                  'repos': {}}
    state['repos'].update(lookup)
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
    state = load_state()
    for batch in state['batches']:
        info = json.loads(call('GET', f'/messages/batches/{batch["id"]}'))
        counts = info.get('request_counts', {})
        print(f'{batch["id"]}  {info.get("processing_status"):12s} '
              f'{json.dumps(counts)}  collected={batch["collected"]}')


def do_collect(vocab):
    state = load_state()
    repos = state.get('repos', {})
    written = failed = 0
    for batch in state['batches']:
        if batch['collected']:
            continue
        info = json.loads(call('GET', f'/messages/batches/{batch["id"]}'))
        if info.get('processing_status') != 'ended':
            print(f'{batch["id"]}: {info.get("processing_status")}, skipping')
            continue
        body = call('GET', info['results_url'])
        for line in body.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry_id = row.get('custom_id')
            repo = repos.get(entry_id, entry_id)
            result = row.get('result') or {}
            if result.get('type') != 'succeeded':
                with open(REVIEW, 'a') as fh:
                    fh.write(json.dumps({'repo': repo, 'id': entry_id,
                                         'problems': [f'batch result '
                                                      f'{result.get("type")}'],
                                         'raw': json.dumps(result)[:2000]}) + '\n')
                failed += 1
                continue
            message = result.get('message') or {}
            text = ''.join(b.get('text', '') for b in message.get('content', []))
            if write_result(repo, entry_id, text, vocab, message.get('usage')):
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
    parser.add_argument('--pilot', type=int, metavar='N')
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()

    vocab = read_vocabularies()
    if args.pilot:
        do_pilot(args.pilot, args.seed, vocab)
    elif args.submit:
        do_submit(vocab, args.dry_run, args.limit)
    elif args.status:
        do_status()
    elif args.collect:
        do_collect(vocab)
    else:
        parser.error('pick one of --pilot N, --submit, --status, --collect')


if __name__ == '__main__':
    main()
