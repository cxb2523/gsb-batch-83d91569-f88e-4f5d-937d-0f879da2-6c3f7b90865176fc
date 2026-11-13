'use strict';

/**
 * Page-snapshot extraction logic, shared between the live browser path
 * (browser-control.js passes this function to page.evaluate) and the
 * offline tests (test/snapshot.test.js feeds it a minimal fake document).
 *
 * The function must stay fully self-contained: every helper is nested so
 * the function source can be serialized into the page by Playwright.
 *
 * @param {object} [doc] document-like object (defaults to the page's `document`)
 * @returns {{content: string, links: Array, interactiveElements: Array}}
 */
function collectSnapshot(doc) {
  if (!doc) {
    // eslint-disable-next-line no-undef
    doc = typeof document !== 'undefined' ? document : null;
  }
  if (!doc) throw new Error('collectSnapshot requires a document');

  const normText = (s) => (s == null ? '' : String(s)).replace(/\s+/g, ' ').trim();
  const escapeAttr = (v) => String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const tagOf = (el) => el.tagName.toLowerCase();
  const isVisible = (el) => el.offsetParent !== null;

  // Legacy selector, kept byte-for-byte compatible with previous releases.
  function legacySelector(el) {
    if (el.id) return `#${el.id}`;
    if (el.className && typeof el.className === 'string') {
      return `${tagOf(el)}.${el.className.split(' ')[0]}`;
    }
    return tagOf(el);
  }

  // Location candidates, most specific first. Each candidate carries its own
  // matcher so uniqueness can be verified against the live page — including
  // for text-based candidates, which CSS alone cannot express.
  function candidatesFor(el) {
    const tag = tagOf(el);
    const list = [];
    const byAttr = (attr) => {
      const v = el.getAttribute(attr);
      if (v) {
        list.push({
          selector: `${tag}[${attr}="${escapeAttr(v)}"]`,
          matches: (e) => tagOf(e) === tag && e.getAttribute(attr) === v,
        });
      }
    };
    byAttr('name');
    byAttr('aria-label');
    byAttr('placeholder');
    const text = normText(el.innerText).substring(0, 50);
    if (text) {
      list.push({
        selector: `${tag}:has-text("${escapeAttr(text)}")`,
        matches: (e) => tagOf(e) === tag && normText(e.innerText).includes(text),
      });
    }
    list.push({ selector: tag, matches: (e) => tagOf(e) === tag });
    return list;
  }

  // Pick the first candidate that matches exactly this element on the page.
  // If none is unique, return the most specific candidate and flag the
  // conflict explicitly instead of silently handing back an ambiguous one.
  function locate(el) {
    const all = Array.from(doc.querySelectorAll(tagOf(el)));
    let first = null;
    for (const cand of candidatesFor(el)) {
      const count = all.filter(cand.matches).length;
      if (!first) first = { selector: cand.selector, count };
      if (count === 1) return { stableSelector: cand.selector, unique: true };
    }
    return { stableSelector: first.selector, unique: false, conflict: { count: first.count } };
  }

  const content = doc.body && doc.body.innerText ? doc.body.innerText.substring(0, 5000) : '';

  // All links on the page (no truncation).
  const links = Array.from(doc.querySelectorAll('a'))
    .filter((a) => a.getAttribute('href') !== null)
    .map((a) => ({ text: (a.innerText || '').substring(0, 100), href: a.href }));

  // Every visible button and input (no truncation).
  const interactiveElements = [];
  for (const el of Array.from(doc.querySelectorAll('button'))) {
    if (!isVisible(el)) continue;
    interactiveElements.push({
      type: 'button',
      text: (el.innerText || '').substring(0, 50),
      selector: legacySelector(el),
      ...locate(el),
    });
  }
  for (const el of Array.from(doc.querySelectorAll('input'))) {
    if (!isVisible(el)) continue;
    interactiveElements.push({
      type: 'input',
      placeholder: el.placeholder || '',
      selector: legacySelector(el),
      ...locate(el),
    });
  }

  return { content, links, interactiveElements };
}

module.exports = { collectSnapshot };
