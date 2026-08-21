/* The v2-only behaviors from design v2 §8: the page limit, and object URLs.
 *
 * These are structural properties of the rendering layer -- how many cards exist,
 * what a group header says, whether a Blob URL was minted -- so unlike cases.js they
 * are checked against the DOM rather than against the engine, and they need a corpus
 * larger than 100 records. That corpus is GENERATED rather than hand-authored: the
 * assertions here are about counts of nodes, not about curatorial judgement, and a
 * 250-record fixture nobody can read by eye would only weaken cases.json's promise
 * that every expectation in it was derived by reading the data.
 *
 * The four detail-fetch cases named in §8 are not here. Stage 1 runs on the current
 * flat export, where summary and needs are already in memory and "lazy" means lazy
 * DOM; the buckets those cases describe do not exist until Stage 2.
 */

export const N = 250;

/* Deterministic, and shaped to exercise the specific things under test:
 *   - every record rated 1 or above, so the default floor shows all of them
 *   - two thirds citable, so v1's per-card Blob would fire if it were still there
 *   - odd records in one use case, even records in two, so grouping duplicates and
 *     the group totals are known exactly: 125 / 125 / 125 over three headings */
export function generate(n = N) {
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push({
      id: 'g' + String(i).padStart(4, '0'),
      title: 'Generated record ' + String(i).padStart(4, '0'),
      kind: i % 3 === 0 ? 'paper' : (i % 3 === 1 ? 'code_repo' : 'preprint'),
      importance: 1 + (i % 5),
      year: 2000 + (i % 25),
      url: 'https://example.org/g' + i,
      summary: 'Summary for generated record ' + i + '.',
      needs: i % 7 === 0 ? 'verify the source' : undefined,
      authors: ['Author ' + (i % 13)],
      use_case: i % 2 ? ['privacy_protection'] : ['data_sharing', 'ml_training'],
      sdv_component: [], sdv_concept: [], industry: [],
      affiliations: [], affiliation_types: [], affiliation_countries: [],
      cited: i,
    });
  }
  return out;
}

const uniqueIds = (mount) =>
  new Set([...mount.querySelectorAll('li.pub-item[data-record-id]')]
    .map(li => li.getAttribute('data-record-id')));

const moreButton = (mount) =>
  mount.parentNode.querySelector('.more-btn:not(.more-all)') ||
  document.querySelector('.pub-more .more-btn:not(.more-all)');

export const RENDER_CASES = [
  {
    id: 'at-most-100-unique-records-render-initially',
    closes: 1,
    why: '§3 item 8 and §9. 250 records match; 100 cards exist. The header still ' +
         'reports the full result count, because the cap is about what is drawn, ' +
         'not about what matched.',
    async run(h) {
      await h.load(generate());
      const n = uniqueIds(h.results).size;
      if (n !== 100) return `${n} unique records rendered, expected 100`;
      const count = h.app.els.count.textContent;
      if (count !== '(250)') return `header count reads ${count}, expected (250)`;
      return null;
    },
  },

  {
    id: 'group-headers-show-visible-over-total',
    closes: 1,
    why: '§3 item 8. Each of the three use-case headings covers 125 of the 250 ' +
         'records (odd records carry one use case, even records two). A header must ' +
         'report how many of those 125 are on the page, not just how many exist and ' +
         'not just how many are drawn.',
    async run(h) {
      await h.load(generate());
      h.select('sort-group', 'use_case');
      await h.settle();
      const heads = [...h.results.querySelectorAll('.pub-group')];
      if (!heads.length) return 'grouping produced no sections';
      for (const sec of heads) {
        const text = sec.querySelector('h3').textContent;
        const cards = sec.querySelectorAll('li.pub-item').length;
        const m = text.match(/\((?:(\d+) of )?(\d+)\)\s*$/);
        if (!m) return `heading ${JSON.stringify(text)} carries no count`;
        const shown = m[1] ? Number(m[1]) : Number(m[2]);
        const total = Number(m[2]);
        if (total !== 125) return `heading ${JSON.stringify(text)}: total ${total}, expected 125`;
        if (shown !== cards) {
          return `heading ${JSON.stringify(text)}: says ${shown} shown, ${cards} cards present`;
        }
        if (shown >= total) {
          return `heading ${JSON.stringify(text)}: ${shown} of ${total} is not a page limit`;
        }
      }
      const n = uniqueIds(h.results).size;
      if (n !== 100) return `${n} unique records across the groups, expected 100`;
      return null;
    },
  },

  {
    id: 'show-100-more-adds-100-unique-records',
    closes: 1,
    why: '§3 item 8. The increment is in UNIQUE records, not in group placements -- ' +
         'under grouping a record can sit in two sections, and counting placements ' +
         'would make one click add fewer than a hundred.',
    async run(h) {
      await h.load(generate());
      moreButton(h.results).click();
      await h.settle();
      let n = uniqueIds(h.results).size;
      if (n !== 200) return `after one click: ${n} unique records, expected 200`;
      moreButton(h.results).click();
      await h.settle();
      n = uniqueIds(h.results).size;
      if (n !== 250) return `after two clicks: ${n} unique records, expected 250`;
      if (moreButton(h.results)) return 'the "show more" control survived the last page';
      return null;
    },
  },

  {
    id: 'any-filter-grouping-or-sort-change-resets-the-page-limit',
    closes: 1,
    why: '§3 item 8. Otherwise a narrow filter inherits a wide page and renders more ' +
         'than the cap -- which is the cap failing silently, the worst way for it to ' +
         'fail. Checked for a sort change, a grouping change and a filter change ' +
         'separately, because they are three different handlers.',
    async run(h) {
      for (const [what, act] of [
        ['sort', () => h.select('sort-within', 'title')],
        ['grouping', () => h.select('sort-group', 'kind')],
        ['a filter', () => h.range('min-importance', 2)],
      ]) {
        await h.load(generate());
        moreButton(h.results).click();
        await h.settle();
        if (uniqueIds(h.results).size !== 200) return `could not widen the page before the ${what} change`;
        act();
        await h.settle();
        const n = uniqueIds(h.results).size;
        if (n > 100) return `after changing ${what}: ${n} unique records, expected at most 100`;
      }
      return null;
    },
  },

  {
    id: 'no-blob-url-is-created-during-render',
    closes: 1,
    why: '§9, a hard gate. v1 creates one object URL per citable entry during render ' +
         '-- 8,541 of them, none reclaimed, before the reader has done anything. ' +
         'Two thirds of the generated corpus is citable, so if BibTeX were still ' +
         'built eagerly this would see them.',
    async run(h) {
      h.urls.reset();
      await h.load(generate());
      if (h.urls.created) return `${h.urls.created} object URL(s) created during load`;
      h.range('min-importance', 3);
      await h.settle();
      if (h.urls.created) return `${h.urls.created} object URL(s) created during a filter change`;
      moreButton(h.results).click();
      await h.settle();
      if (h.urls.created) return `${h.urls.created} object URL(s) created by "show more"`;
      return null;
    },
  },

  {
    id: 'a-bibtex-object-url-is-revoked-once-the-download-begins',
    closes: 1,
    why: '§3 item 6. Generating lazily is not enough if the URL then leaks -- the ' +
         'blob is held for the life of the document either way. Driven through ' +
         'downloadBibtex with delivery stubbed out, so the create-and-revoke path ' +
         'under test runs exactly as it does on the page without handing a real ' +
         'download to the browser.',
    async run(h) {
      await h.load(generate());
      h.urls.reset();
      const rec = { id: 'g0000', title: 'Generated record 0000', kind: 'paper',
        year: 2000, url: 'https://example.org/g0', authors: ['Author 0'] };
      const url = h.downloadBibtex(rec, { deliver: () => {} });
      if (h.urls.created !== 1) return `expected 1 object URL, got ${h.urls.created}`;
      if (h.urls.revoked !== 0) return 'the URL was revoked before the download could start';
      await new Promise(r => setTimeout(r, 20));
      if (h.urls.revoked !== 1) return `expected the URL to be revoked, revoked=${h.urls.revoked}`;
      if (h.urls.lastRevoked !== url) {
        return `revoked ${h.urls.lastRevoked}, but created ${url}`;
      }
      return null;
    },
  },
];
