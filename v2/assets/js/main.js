/* Entry point. Everything else is in app.js so the oracle adapter, the semantic
 * runner and the benchmark can build an App against their own mount. */
import { App } from './app.js';

const boot = () => new App(document).mount().start();
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
