// Smoke test: load network.js under jsdom and actually RUN init() by firing
// DOMContentLoaded. Catches ReferenceErrors from handlers that are wired but
// never defined — the class of bug that froze the page ("saveRoute is not
// defined"), which node --check and the Python suite both miss because neither
// executes the browser JS through its init path.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const JS = path.join(__dirname, '..', '..', 'web', 'desktop', 'js', 'network.js');
const HTML = path.join(__dirname, '..', '..', 'web', 'desktop', 'network.html');

function run() {
  const dom = new JSDOM(fs.readFileSync(HTML, 'utf8'),
                        { runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.fetch = () => new Promise(() => {});     // never resolves
  window.localStorage = { getItem: () => 'tok', setItem(){}, removeItem(){} };

  // Surface any error thrown inside an event handler (jsdom swallows these
  // into window.onerror rather than propagating them out of dispatchEvent).
  let handlerError = null;
  window.addEventListener('error', (e) => { handlerError = e.error || new Error(e.message); });

  new window.Function(fs.readFileSync(JS, 'utf8')).call(window);

  // readyState is 'loading', so init() is registered on DOMContentLoaded and
  // has NOT run yet. Fire it — this is what actually executes init() and its
  // handler wiring, where an undefined handler throws.
  const evt = window.document.createEvent('Event');
  evt.initEvent('DOMContentLoaded', true, true);
  window.document.dispatchEvent(evt);

  if (handlerError) throw handlerError;
  return true;
}

try {
  run();
  console.log('PASS: network.js init() ran with no ReferenceError');
  process.exit(0);
} catch (e) {
  console.error('FAIL:', e.constructor.name + ':', e.message);
  process.exit(1);
}
