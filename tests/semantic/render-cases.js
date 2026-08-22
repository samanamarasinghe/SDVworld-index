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

/* The 250-record corpus is generated and projected by scripts/build_fixture.py and
 * arrives as h.generated. It used to be built here in JavaScript; from Stage 2a the
 * page consumes the projection, so a fixture the harness projected itself would be
 * testing the engine against a second, private implementation of the transform under
 * test. Its shape is documented where it is now built. */

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
      await h.load(h.generated);
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
      await h.load(h.generated);
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
      await h.load(h.generated);
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
        await h.load(h.generated);
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
      await h.load(h.generated);
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
      await h.load(h.generated);
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

  /* ---- detail buckets (design v2 §3 items 6, 9, 10; §6) ------------------ */

  {
    id: 'a-detail-fetch-populates-summary-and-needs',
    closes: 2,
    why: 'Summary and needs live in a bucket now, not in core. Opening a card must ' +
         'fetch its bucket and fill in the text.',
    async run(h) {
      const D = new h.Details('/base/', async (url) => ({
        ok: true, json: async () => ({ x1: { summary: 'the summary', needs: 'the need' } }),
      }));
      const got = await D.forRecord({ id: 'x1', bucket: '07', hasSummary: true });
      if (got.summary !== 'the summary') return `summary came back as ${JSON.stringify(got.summary)}`;
      if (got.needs !== 'the need') return `needs came back as ${JSON.stringify(got.needs)}`;
      /* A record carrying neither must not cost a request at all. */
      const before = D.requests;
      const none = await D.forRecord({ id: 'x9', bucket: '11' });
      if (Object.keys(none).length) return 'a record with no detail returned something';
      if (D.requests !== before) return 'a record with no detail still fetched a bucket';
      return null;
    },
  },

  {
    id: 'concurrent-detail-fetches-for-one-bucket-share-a-promise',
    closes: 2,
    why: '§6: in-flight fetches deduplicate. Twenty cards from one bucket appearing ' +
         'at once must cost one request, not twenty -- and a bucket already in ' +
         'memory must cost none.',
    async run(h) {
      let resolve;
      const gate = new Promise(r => { resolve = r; });
      const D = new h.Details('/base/', async () => {
        await gate;
        return { ok: true, json: async () => ({ a: { summary: 's' } }) };
      });
      const all = Promise.all(Array.from({ length: 20 }, () =>
        D.forRecord({ id: 'a', bucket: '03', hasSummary: true })));
      if (D.requests !== 1) return `${D.requests} requests were started, expected 1`;
      resolve();
      await all;
      await D.forRecord({ id: 'a', bucket: '03', hasSummary: true });
      if (D.requests !== 1) return `${D.requests} requests after the bucket was cached`;
      return null;
    },
  },

  {
    id: 'a-failed-detail-fetch-leaves-the-core-card-usable',
    closes: 2,
    why: '§3 item 10. The card keeps its title, links and actions, and the summary ' +
         'area shows a retryable inline error rather than the card breaking.',
    async run(h) {
      await h.load(h.generated);
      /* Make the next bucket fetch fail, then open a summary. */
      h.app.details.loaded.clear();
      h.app.details.fetch = async () => ({ ok: false, status: 503 });
      const card = h.results.querySelector('li.pub-item');
      const before = card.querySelectorAll('.pub-action').length;
      card.querySelector('.pub-summary-toggle').click();
      await h.waitFor(() => card.querySelector('.pub-summary-error'), 'the inline error');
      if (!/503/.test(card.querySelector('.pub-summary-error').textContent)) {
        return 'the error does not say what went wrong';
      }
      if (!card.querySelector('.pub-title a')) return 'the card lost its title link';
      if (card.querySelectorAll('.pub-action').length < before) {
        return 'the card lost actions when the fetch failed';
      }
      if (!card.querySelector('.pub-summary-error a')) return 'no retry control offered';
      return null;
    },
  },

  {
    id: 'retrying-a-failed-detail-fetch-succeeds',
    closes: 2,
    why: '§3 item 10. A failure must not poison the bucket for the rest of the ' +
         'session -- so the rejected promise must not be cached.',
    async run(h) {
      await h.load(h.generated);
      h.app.details.loaded.clear();
      let fail = true;
      h.app.details.fetch = async (url) => (fail
        ? { ok: false, status: 503 }
        : { ok: true, json: async () => {
            const name = url.match(/detail\/(\w+)\.json/)[1];
            return h.generated.detail[name] || {};
          } });
      const card = h.results.querySelector('li.pub-item');
      card.querySelector('.pub-summary-toggle').click();
      await h.waitFor(() => card.querySelector('.pub-summary-error'), 'the inline error');
      fail = false;
      card.querySelector('.pub-summary-error a').click();
      await h.waitFor(() => {
        const box = card.querySelector('.pub-summary');
        return box && !box.classList.contains('pub-summary-error') &&
               /Summary for generated record/.test(box.textContent);
      }, 'the retry to load the summary');
      return null;
    },
  },

  /* ---- search (design v2 §4) --------------------------------------------- */

  {
    id: 'the-runtime-tokenizer-matches-the-build-tokenizer',
    closes: 2,
    why: 'The single highest-risk thing in 2b. The postings are built by Python and ' +
         'queried by JavaScript; if the two tokenize differently, a query is looked ' +
         'up under a key the text was never filed under and the search quietly ' +
         'returns too little. Both are pinned to one shared table rather than to ' +
         'each other, so neither can drift into agreeing on the wrong answer.',
    async run(h) {
      const { cases } = await (await fetch('/tests/semantic/tokenizer-cases.json',
        { cache: 'no-store' })).json();
      const { fold, tokenize } = await import('/v2/assets/js/search.js');
      for (const c of cases) {
        const got = tokenize(c.text);
        if (JSON.stringify(got) !== JSON.stringify(c.tokens)) {
          return `tokenize(${JSON.stringify(c.text)}) gave ${JSON.stringify(got)}, ` +
                 `the table says ${JSON.stringify(c.tokens)}`;
        }
        if (fold(c.text) !== c.folded) {
          return `fold(${JSON.stringify(c.text)}) gave ${JSON.stringify(fold(c.text))}, ` +
                 `the table says ${JSON.stringify(c.folded)}`;
        }
      }
      return null;
    },
  },

  {
    id: 'a-finished-word-is-not-prefix-matched',
    closes: 2,
    why: 'Prefix matching exists so a half-typed word still finds things. §4 applies ' +
         'it to the final term unconditionally, which is a gap in the spec: "C++" ' +
         'tokenizes to the single token c, and prefix-matching that returns almost ' +
         'the whole corpus. A trailing delimiter means the reader finished the word.',
    async run(h) {
      const { prefixWanted } = await import('/v2/assets/js/search.js');
      const wants = [['hea', true], ['health', true], ['C++', false],
                     ['covid-19', true], ['time-series', true], ['e.g.', false],
                     ['multi word', true], ['trailing ', false]];
      for (const [q, want] of wants) {
        if (prefixWanted(q) !== want) {
          return `prefixWanted(${JSON.stringify(q)}) is ${prefixWanted(q)}, expected ${want}`;
        }
      }
      return null;
    },
  },

  {
    id: 'search-terms-AND-and-the-last-one-matches-by-prefix',
    closes: 2,
    why: '§4. Several terms must all be present, in any order; the final term ' +
         'matches by prefix so results narrow as the reader types.',
    async run(h) {
      const { Postings } = await import('/v2/assets/js/search.js');
      /* Three records, hand-built so every expected answer is readable here. */
      const P = new Postings({
        vocab: ['alpha', 'beta', 'betamax', 'gamma'],
        postings: [[0, 1], [0, 2], [1], [2]],   // delta-encoded: a=[0,1] b=[0,2] bm=[1] g=[2]
      });
      const set = (q) => [...(P.candidates(q) || [])].sort();
      const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      if (!eq(set('alpha'), [0, 1])) return `alpha -> ${set('alpha')}`;
      if (!eq(set('bet'), [0, 1, 2])) return `bet (prefix) -> ${set('bet')}`;
      if (!eq(set('beta '), [0, 2])) return `"beta " (finished) -> ${set('beta ')}`;
      if (!eq(set('alpha bet'), [0, 1])) return `alpha bet -> ${set('alpha bet')}`;
      if (!eq(set('alpha beta '), [0])) return `alpha beta -> ${set('alpha beta ')}`;
      if (!eq(set('beta alpha '), [0])) return `order must not matter -> ${set('beta alpha ')}`;
      /* A finished term is matched exactly, so a prefix that is not itself a word
         finds nothing -- which is the whole point of the trailing-delimiter rule. */
      if (!eq(set('bet '), [])) return `"bet " is not a word -> ${set('bet ')}`;
      if (!eq(set('alpha gamma '), [])) return `alpha gamma -> ${set('alpha gamma ')}`;
      if (!eq(set('nosuch '), [])) return `an absent term must give nothing`;
      if (P.candidates('') !== null) return 'an empty query must not constrain anything';
      return null;
    },
  },

  {
    id: 'narrowing-to-titles-changes-the-result-and-is-reversible',
    closes: 2,
    why: 'The scope toggle is the mitigation for the §4 search change, so it has to ' +
         'actually work: ticking and unticking must move the result set and put it ' +
         'back, and it must not be reset by Clear filters, which resets FILTERS.',
    async run(h) {
      await h.load(h.generated);
      const box = h.mount.querySelector('#facet-title');
      const scope = h.mount.querySelector('#search-summaries');
      if (!scope) return 'the search-scope toggle is not in the markup';
      if (!scope.checked) return 'summaries are not searched by default';

      const count = () => h.app.els.count.textContent;
      /* "summary" appears in every generated summary and in no generated title, so
         the two scopes must disagree completely: 250 against 0. That also means the
         COUNT does not move when the search applies -- only when the scope does --
         so wait on the debounced state rather than on the number. */
      box.value = 'summary';
      box.dispatchEvent(new Event('input', { bubbles: true }));
      await h.waitFor(() => h.app.state.titleQuery === 'summary', 'the debounce to fire');
      await h.settle();
      if (count() !== '(250)') return `summaries mode found ${count()}, expected (250)`;

      scope.checked = false;
      scope.dispatchEvent(new Event('change', { bubbles: true }));
      await h.waitFor(() => count() === '(0)', 'narrowing to titles');

      scope.checked = true;
      scope.dispatchEvent(new Event('change', { bubbles: true }));
      await h.waitFor(() => count() === '(250)', 'the scope change to reverse');

      h.mount.querySelector('#btn-clear').click();
      await h.settle();
      if (!h.mount.querySelector('#search-summaries').checked) {
        return 'Clear filters reset the search scope, which is a preference not a filter';
      }
      return null;
    },
  },
];