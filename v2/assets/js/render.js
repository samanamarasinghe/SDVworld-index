/* Result rendering.
 *
 * Three things separate this from v1:
 *
 *   1. At most PAGE unique records exist as DOM at any time (§3 item 8, §9). v1
 *      builds 4,703 cards and 129,114 element nodes before the reader has done
 *      anything.
 *   2. Summary and needs nodes are built on demand. Evidence stays in the eager card
 *      -- §1 item 1 is explicit that moving it would silently change what a collapsed
 *      card shows.
 *   3. BibTeX is generated in the click handler and its object URL revoked as soon as
 *      the download begins. v1 mints one Blob per citable entry during render: 8,541
 *      object URLs, none of them reclaimed, before any interaction.
 */
import {
  KIND_LABELS, INTEGRATION_LABELS, CITABLE, labelFor, prettify,
} from './vocab.js';
import { groupPlan, groupHeadersFor } from './order.js';

export const PAGE = 100;

function el(tag, cls, txt) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (txt != null) e.appendChild(document.createTextNode(txt));
  return e;
}

function actionLabel(rec) {
  if (rec.kind === 'code_repo') {
    return /github\.com/i.test(rec.url || '') ? 'GitHub' : 'Repository';
  }
  if (CITABLE[rec.kind]) return 'PDF';
  return 'Open';
}

/* ---- BibTeX, lazily and without leaking ---------------------------------- */

const BIB_TYPE = { paper: 'article', preprint: 'misc', thesis: 'mastersthesis' };

export function bibKey(rec) {
  return rec.id ||
    (rec.title || 'untitled').toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 24) +
    (rec.year || '');
}

export function buildBibtex(rec) {
  const out = ['@' + (BIB_TYPE[rec.kind] || 'misc') + '{' + bibKey(rec) + ','];
  const push = (k, v) => {
    if (v) out.push('  ' + k + ' = {' + String(v).replace(/[\n\r]+/g, ' ') + '},');
  };
  push('author', (rec.authors || []).join(' and '));
  push('title', '{' + (rec.title || '') + '}');
  push('year', rec.year);
  push('note', rec.venue);
  push('doi', rec.doi);
  push('url', rec.url);
  if (out.length > 1) out[out.length - 1] = out[out.length - 1].replace(/,\s*$/, '');
  out.push('}');
  return out.join('\n');
}

/* Exported so the semantic suite can drive it without a real click. Returns the URL
 * it created and revoked, which is the only way to assert the revocation happened. */
export function downloadBibtex(rec, doc = document) {
  const blob = new Blob([buildBibtex(rec)], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = doc.createElement('a');
  a.href = url;
  a.download = bibKey(rec) + '.bib';
  doc.body.appendChild(a);
  a.click();
  a.remove();
  /* The browser has taken its own reference by the time the click returns, so the
     URL can go on the next task. Holding it costs the blob's memory for the life of
     the document, which is exactly v1's leak. */
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return url;
}

/* ---- one card ------------------------------------------------------------ */

function summaryNode(text) {
  const sum = el('div', 'pub-summary open');
  /* Curated summaries carry inline HTML -- links to the source, mostly -- and v1
     renders them as markup. Parity matters more than taste here: switching to text
     would silently drop every link in the corpus. The text is curator-authored and
     travels with the generated index, not with anything a reader supplies. */
  for (const para of String(text).split(/\n\n+/)) {
    const pnode = document.createElement('p');
    pnode.innerHTML = para;
    sum.appendChild(pnode);
  }
  for (const a of sum.getElementsByTagName('a')) { a.target = '_blank'; a.rel = 'noopener'; }
  return sum;
}

function renderCard(n, ctx) {
  const rec = n.rec;
  const li = el('li', 'pub-item' + (rec.tier === 'tail' ? ' tail-item' : ''));
  /* The record's identity, in the DOM. The structural probe counts unique records
     rendered with this; v1 offers nothing to count and has to be measured by
     counting <li> elements instead. */
  li.setAttribute('data-record-id', String(rec.id));

  const t = el('div', 'pub-title');
  if (rec.url) {
    const a = el('a', null, rec.title || 'Untitled');
    a.href = rec.url; a.target = '_blank'; a.rel = 'noopener';
    t.appendChild(a);
  } else {
    t.appendChild(document.createTextNode(rec.title || 'Untitled'));
  }
  li.appendChild(t);

  const meta = el('div', 'pub-meta');
  meta.appendChild(el('span', 'badge badge-kind', KIND_LABELS[rec.kind] || prettify(rec.kind)));
  if (rec.tier === 'tail') meta.appendChild(el('span', 'badge badge-tail', 'tail'));
  const bits = [];
  if (rec.venue) bits.push(rec.venue);
  if (rec.year) bits.push(String(rec.year));
  if (rec.stars != null) bits.push('★ ' + rec.stars);
  if (rec.cited != null) bits.push('cited by ' + rec.cited);
  if (bits.length) meta.appendChild(el('span', 'pub-dim', ' ' + bits.join(' · ')));
  if (rec.confidence) {
    const conf = el('span', 'conf');
    conf.appendChild(el('span', 'conf-dot conf-' + rec.confidence));
    conf.appendChild(el('span', 'conf-label', rec.confidence));
    meta.appendChild(conf);
  }
  li.appendChild(meta);

  if (rec.authors && rec.authors.length) {
    li.appendChild(el('div', 'pub-authors', rec.authors.join(', ')));
  }

  /* Evidence is eager. §1 item 1: the current renderer shows it on collapsed cards,
     and moving it to lazy detail would silently change visible behavior. */
  if (rec.integration || rec.evidence) {
    const ev = el('div', 'pub-evidence');
    if (rec.integration) {
      ev.appendChild(el('span', 'badge badge-integration',
        INTEGRATION_LABELS[rec.integration] || prettify(rec.integration)));
    }
    if (rec.evidence) ev.appendChild(el('span', 'evidence-text', 'evidence: ' + rec.evidence));
    li.appendChild(ev);
  }

  const chips = el('div', 'pub-chips');
  for (const f of ['sdv_component', 'sdv_concept', 'use_case', 'industry']) {
    /* The raw field, not the normalized values: v1 chips what the record actually
       carries, so a record with nothing gets no "Not specified" chip. */
    for (const v of rec[f] || []) {
      const chip = el('span', 'chip chip-' + f, labelFor(f, v));
      chip.title = 'Filter by ' + labelFor(f, v);
      chip.addEventListener('click', () => ctx.onChip(f, v));
      chips.appendChild(chip);
    }
  }
  if (chips.childNodes.length) li.appendChild(chips);

  const actions = el('div', 'pub-actions');
  if (rec.url) {
    const link = el('a', 'pub-action', actionLabel(rec));
    link.href = rec.url; link.target = '_blank'; link.rel = 'noopener';
    actions.appendChild(link);
  }
  if (rec.doi) {
    const doi = el('a', 'pub-action', 'DOI');
    doi.href = /^https?:/.test(rec.doi) ? rec.doi : 'https://doi.org/' + rec.doi;
    doi.target = '_blank'; doi.rel = 'noopener';
    actions.appendChild(doi);
  }
  if (CITABLE[rec.kind]) {
    const bib = el('a', 'pub-action', 'BibTeX');
    bib.href = '#';
    bib.addEventListener('click', (e) => { e.preventDefault(); downloadBibtex(rec); });
    actions.appendChild(bib);
  }
  if (rec.url) {
    const copy = el('a', 'pub-action', 'Copy link');
    copy.href = '#';
    copy.addEventListener('click', (e) => {
      e.preventDefault();
      if (navigator.clipboard) navigator.clipboard.writeText(rec.url);
      copy.textContent = 'Copied';
      setTimeout(() => { copy.textContent = 'Copy link'; }, 1200);
    });
    actions.appendChild(copy);
  }

  /* Lazy detail. The toggle exists eagerly -- it is one node and the reader has to
     be able to see that a summary is there -- but the summary's own nodes are not
     built until asked for. At Stage 1 the text is already in memory, so "load" is a
     synchronous build; Stage 2 replaces the body of ensure() with a bucket fetch and
     the four pending cases in tests/semantic/cases.js become real. */
  if (rec.summary) {
    let node = null;
    const toggle = el('a', 'pub-action pub-summary-toggle');
    toggle.href = '#';
    const setArrow = (open) => { toggle.textContent = open ? 'Summary ▾' : 'Summary ▸'; };
    const ensure = () => {
      if (!node) { node = summaryNode(rec.summary); li.appendChild(node); }
      return node;
    };
    const setOpen = (open) => {
      if (open) { ensure().className = 'pub-summary open'; }
      else if (node) { node.className = 'pub-summary'; }
      setArrow(open);
    };
    toggle.addEventListener('click', (e) => {
      e.preventDefault();
      setOpen(!node || node.className.indexOf('open') === -1);
    });
    actions.appendChild(toggle);
    li.appendChild(actions);
    /* §3 item 9: newly rendered records honour the current global toggle. */
    setArrow(false);
    if (ctx.summaryExpanded) setOpen(true);
  } else {
    li.appendChild(actions);
  }

  if (rec.needs) {
    /* Hidden by CSS unless the results container carries .show-needs, as in v1 --
       but built only when the reader has asked to see open questions, so the default
       view carries none of these nodes. */
    if (ctx.showNeeds) li.appendChild(el('div', 'pub-needs', '⚑ needs: ' + rec.needs));
    else li.setAttribute('data-has-needs', '1');
  }

  return li;
}

/* ---- the list ------------------------------------------------------------ */

export function renderResults(mount, sorted, state, ctx) {
  const limit = state.limit;
  const visible = limit === Infinity ? sorted : sorted.slice(0, limit);
  const frag = document.createDocumentFragment();

  if (!sorted.length) {
    frag.appendChild(el('div', 'empty', 'No entries match the current filters.'));
    mount.replaceChildren(frag);
    return { rendered: 0, total: 0 };
  }

  if (state.group === 'none') {
    const ul = el('ul', 'pub-list');
    for (const n of visible) ul.appendChild(renderCard(n, ctx));
    frag.appendChild(ul);
  } else {
    for (const g of groupPlan(sorted, visible, state.group)) {
      /* A group can be entirely off the current page. Rendering an empty section
         with "0 of 412" is noise; the count that matters is still reachable by
         showing more. */
      if (!g.records.length) continue;
      const sec = el('div', 'pub-group');
      const head = el('h3');
      head.appendChild(document.createTextNode(g.heading));
      head.appendChild(el('span', 'group-count',
        g.records.length === g.total
          ? ' (' + g.total + ')'
          : ' (' + g.records.length + ' of ' + g.total + ')'));
      sec.appendChild(head);
      const ul = el('ul', 'pub-list');
      for (const n of g.records) ul.appendChild(renderCard(n, ctx));
      sec.appendChild(ul);
      frag.appendChild(sec);
    }
  }

  if (visible.length < sorted.length) {
    const more = el('div', 'pub-more');
    const rest = sorted.length - visible.length;
    const btn = el('button', 'more-btn',
      'Show ' + Math.min(PAGE, rest) + ' more  (' + visible.length.toLocaleString() +
      ' of ' + sorted.length.toLocaleString() + ' shown)');
    btn.type = 'button';
    btn.addEventListener('click', ctx.onMore);
    more.appendChild(btn);
    const all = el('button', 'more-btn more-all', 'Show all ' + rest.toLocaleString() +
      ' remaining (slow)');
    all.type = 'button';
    all.title = 'Renders every remaining entry at once. With thousands of results ' +
      'this can lock the page for several seconds.';
    all.addEventListener('click', ctx.onAll);
    more.appendChild(all);
    frag.appendChild(more);
  }

  mount.replaceChildren(frag);
  return { rendered: visible.length, total: sorted.length };
}

/* Turning "show open questions" on must not force a re-render of everything, but the
 * nodes were never built for the cards already on screen. Build them in place. */
export function syncNeeds(mount, byId, show) {
  mount.classList.toggle('show-needs', show);
  if (!show) return;
  for (const li of mount.querySelectorAll('li.pub-item[data-has-needs]')) {
    const n = byId.get(li.getAttribute('data-record-id'));
    if (!n) continue;
    li.removeAttribute('data-has-needs');
    li.appendChild(el('div', 'pub-needs', '⚑ needs: ' + n.rec.needs));
  }
}

export { groupHeadersFor };
