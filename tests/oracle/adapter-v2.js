/* Present the v2 engine to the harnesses behind the same handful of methods they
 * already call on the instrumented v1 closure.
 *
 * The adapter is deliberately thin -- it builds a real App against the real markup
 * and returns App.adapter(), which delegates to the same code the page runs. If it
 * reimplemented anything, the differential would be comparing the harness against
 * itself and would prove nothing.
 */
import { App } from '../../v2/assets/js/app.js';

export async function injectV2Markup(mountId) {
  /* The live v2 page, fetched rather than copied, for the same reason the v1
     harness fetches index.html: a copy drifts and the harness would then be
     measuring a page nobody ships. */
  const html = await (await fetch('/v2/index.html', { cache: 'no-store' })).text();
  const doc = new DOMParser().parseFromString(html, 'text/html');
  doc.querySelectorAll('script').forEach(s => s.remove());
  document.getElementById(mountId).innerHTML = doc.body.innerHTML;
}

export async function build({ say, note, mount = 'v1-markup' } = {}) {
  const tell = say || (() => {});
  const log = note || (() => {});

  tell('injecting v2 markup');
  await injectV2Markup(mount);

  tell('starting the v2 app');
  const app = new App(document).mount();
  await app.start({
    onError: (path, e) => log(`pool load failed: ${path}: ${e.message}`),
  });

  const p = app.corpus.probe();
  if (!(p.data > 0)) throw new Error('v2 loaded no curated records');
  if (p.cite == null || p.gh == null) {
    /* The oracle's states include importance 0, where the pool residue is visible.
       Recording that state without the pools would silently produce a corpus 44
       records short and blame v2 for it. */
    throw new Error('v2 did not finish loading both pools');
  }
  log(`v2 ready: ${p.data} curated + ${p.cite} citation-pool + ${p.gh} repo-pool`);

  return {
    engine: app.adapter(),
    app,
    provenance: { target: 'v2', modules: 'v2/assets/js/*.js' },
  };
}
