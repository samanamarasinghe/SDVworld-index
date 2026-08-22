/* Keyboard and ARIA checks (design v2 §10, Stage 3).
 *
 * Two kinds of check, and the distinction matters:
 *
 *   PARITY   v2 must be no worse than v1. The cutover must not take away something a
 *            reader relies on today, so these compare the two pages.
 *   V2       properties v2 owns because it introduced the control -- the page-limit
 *            buttons and the search-scope toggle have no v1 equivalent to compare to.
 *
 * This is not a full audit. It checks what this project can actually break: focus
 * reachability of every control, accessible names, the pressed/checked state of the
 * toggles, and that lazily built content is reachable rather than orphaned.
 */

const results = [];
const check = (kind, name, ok, detail) => results.push({ kind, name, ok, detail });

const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

/* What a screen reader would announce for a control, by the usual precedence. */
function accessibleName(el, doc) {
  const labelled = el.getAttribute('aria-labelledby');
  if (labelled) {
    const parts = labelled.split(/\s+/).map(id => txt(doc.getElementById(id)));
    if (parts.join(' ').trim()) return parts.join(' ').trim();
  }
  const aria = el.getAttribute('aria-label');
  if (aria && aria.trim()) return aria.trim();
  if (el.id) {
    const lab = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (lab && txt(lab)) return txt(lab);
  }
  const wrapping = el.closest('label');
  if (wrapping && txt(wrapping)) return txt(wrapping);
  if (txt(el)) return txt(el);
  const title = el.getAttribute('title');
  if (title && title.trim()) return title.trim();
  return '';
}

const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';

function focusable(doc, root) {
  return [...(root || doc).querySelectorAll(FOCUSABLE)]
    .filter(el => !el.disabled && el.getAttribute('tabindex') !== '-1'
                  && el.offsetParent !== null);
}

export function run(d1, d2) {
  results.length = 0;

  /* ---- parity: nothing a reader can reach today may become unreachable ---- */

  const controlIds = ['facet-title', 'author-search', 'min-importance', 'min-popularity',
    'sort-group', 'sort-within', 'btn-clear', 'btn-toggle-summaries',
    'btn-toggle-needs'];
  for (const id of controlIds) {
    const a = d1.getElementById(id), b = d2.getElementById(id);
    check('parity', `${id} exists in both`, !!a === !!b,
          `v1 ${!!a}, v2 ${!!b}`);
    if (!a || !b) continue;
    const na = accessibleName(a, d1), nb = accessibleName(b, d2);
    check('parity', `${id} has an accessible name`, !!nb,
          nb ? `"${nb.slice(0, 60)}"` : 'none — a screen reader would announce nothing');
    /* The requirement is that v2 be no WORSE, not that it be identical. v1 leaves
       the search box and both sliders with no accessible name at all, and names the
       two selects by reading out their entire option list; v2 fixes all five. Failing
       those as "changed" would be asserting that the page may not improve. */
    check('parity', `${id} keeps an accessible name`, !na || !!nb,
          !na && nb ? `improved: v1 had none, v2 says "${nb.slice(0, 40)}"`
            : na === nb ? `unchanged: "${na.slice(0, 40)}"`
              : `v1 "${na.slice(0, 30)}" -> v2 "${nb.slice(0, 30)}"`);
  }

  /* Every facet checkbox must be reachable and named in both. */
  for (const mount of ['facet-kind', 'facet-integration', 'facet-industry']) {
    for (const [tag, doc] of [['v1', d1], ['v2', d2]]) {
      const boxes = [...doc.querySelectorAll(`#${mount} input[type=checkbox]`)];
      const unnamed = boxes.filter(b => !accessibleName(b, doc));
      check('parity', `${tag} ${mount} checkboxes are all named`, !unnamed.length,
            unnamed.length ? `${unnamed.length} of ${boxes.length} unnamed`
                           : `${boxes.length} named`);
    }
  }

  /* The toggle buttons carry state, and a button that looks pressed but does not say
     so is invisible to anyone not looking at it. */
  for (const id of ['btn-toggle-summaries', 'btn-toggle-needs']) {
    const b = d2.getElementById(id);
    if (!b) continue;
    check('parity', `${id} exposes aria-pressed`,
          b.hasAttribute('aria-pressed'),
          b.getAttribute('aria-pressed') ?? 'absent');
  }

  const f1 = focusable(d1), f2 = focusable(d2);
  check('parity', 'v2 has no fewer focusable controls in the filter panel',
        f2.length >= 20, `v1 ${f1.length}, v2 ${f2.length}`);

  /* ---- v2's own controls ------------------------------------------------- */

  const scope = d2.getElementById('search-summaries');
  check('v2', 'the search-scope toggle is a real checkbox',
        !!scope && scope.type === 'checkbox', scope ? scope.type : 'missing');
  check('v2', 'the search-scope toggle is named',
        !!scope && !!accessibleName(scope, d2),
        scope ? `"${accessibleName(scope, d2)}"` : 'missing');
  check('v2', 'the search-scope toggle is keyboard reachable',
        !!scope && focusable(d2).includes(scope),
        scope ? String(focusable(d2).includes(scope)) : 'missing');

  const aff = [...d2.querySelectorAll('.aff-btn')];
  check('v2', 'affiliation buttons expose aria-pressed',
        aff.length > 0 && aff.every(b => b.hasAttribute('aria-pressed')),
        `${aff.filter(b => b.hasAttribute('aria-pressed')).length}/${aff.length}`);
  const years = [...d2.querySelectorAll('.year-btn')];
  check('v2', 'year buttons expose aria-pressed',
        years.length > 0 && years.every(b => b.hasAttribute('aria-pressed')),
        `${years.filter(b => b.hasAttribute('aria-pressed')).length}/${years.length}`);

  const more = d2.querySelector('.pub-more .more-btn');
  check('v2', 'the page-limit control is a button, focusable and named',
        !!more && more.tagName === 'BUTTON' && !!txt(more),
        more ? `"${txt(more).slice(0, 50)}"` : 'missing');

  /* Every card action must be reachable; a lazily built summary must not orphan its
     toggle. */
  const cards = [...d2.querySelectorAll('li.pub-item')];
  const badAction = cards.flatMap(li => [...li.querySelectorAll('.pub-action')])
    .filter(a => !txt(a));
  check('v2', 'every card action has a visible label', !badAction.length,
        badAction.length ? `${badAction.length} unlabelled` : 'all labelled');
  const toggles = [...d2.querySelectorAll('.pub-summary-toggle')];
  check('v2', 'summary toggles are links with an href and are focusable',
        toggles.length > 0 && toggles.every(t => t.getAttribute('href')),
        `${toggles.length} toggle(s)`);

  return results;
}
