'use strict';

/**
 * Offline tests for the snapshot extraction logic (snapshot-extract.js).
 *
 * These tests run without a browser and without network access: static HTML
 * fixtures are parsed by a tiny purpose-built DOM (just enough surface for
 * collectSnapshot: tag-name querySelectorAll, attributes, innerText, visibility).
 */

const { test } = require('node:test');
const assert = require('node:assert');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { collectSnapshot } = require('../snapshot-extract');

const root = path.join(__dirname, '..');
const cli = path.join(root, 'browser-control.js');

// ---------------------------------------------------------------------------
// Minimal fake DOM
// ---------------------------------------------------------------------------

const VOID_TAGS = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);

class FakeElement {
  constructor(tagName, attrs, parent) {
    this.tagName = tagName.toUpperCase();
    this.attrs = attrs;
    this.parent = parent;
    this.children = []; // FakeElement | string
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null;
  }

  get id() { return this.attrs.id || ''; }
  get className() { return this.attrs.class || ''; }
  get placeholder() { return this.attrs.placeholder || ''; }
  get href() { return this.attrs.href === undefined ? undefined : this.attrs.href; }

  get isHidden() {
    for (let el = this; el; el = el.parent) {
      if (el.attrs && Object.prototype.hasOwnProperty.call(el.attrs, 'hidden')) return true;
      if (el.attrs && /display\s*:\s*none/i.test(el.attrs.style || '')) return true;
    }
    return false;
  }

  // Mirrors the browser semantics the extractor relies on: hidden => null.
  get offsetParent() {
    return this.isHidden ? null : {};
  }

  get innerText() {
    const parts = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (typeof child === 'string') parts.push(child);
        else if (!child.isHidden) walk(child);
      }
    };
    walk(this);
    return parts.join(' ').replace(/\s+/g, ' ').trim();
  }

  * descendants() {
    for (const child of this.children) {
      if (typeof child === 'string') continue;
      yield child;
      yield* child.descendants();
    }
  }

  querySelectorAll(selector) {
    if (!/^[a-zA-Z][a-zA-Z0-9]*$/.test(selector)) {
      throw new Error(`fake DOM only supports tag-name selectors, got: ${selector}`);
    }
    const tag = selector.toUpperCase();
    return Array.from(this.descendants()).filter((el) => el.tagName === tag);
  }
}

function parseHTML(html) {
  const rootEl = new FakeElement('#document', {}, null);
  const stack = [rootEl];
  const tokenRe = /<!--[\s\S]*?-->|<!doctype[^>]*>|<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*)\/?>|([^<]+)/g;
  let m;
  while ((m = tokenRe.exec(html))) {
    if (m[4] !== undefined) {
      if (m[4].trim()) stack[stack.length - 1].children.push(m[4]);
      continue;
    }
    if (m[2] === undefined) continue; // comment / doctype
    const [, closing, tag, attrSrc] = m;
    const lower = tag.toLowerCase();
    if (closing) {
      while (stack.length > 1) {
        const popped = stack.pop();
        if (popped.tagName === tag.toUpperCase()) break;
      }
      continue;
    }
    const attrs = {};
    const attrRe = /([a-zA-Z-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
    let am;
    while ((am = attrRe.exec(attrSrc || ''))) {
      attrs[am[1].toLowerCase()] = am[2] ?? am[3] ?? am[4] ?? '';
    }
    const el = new FakeElement(lower, attrs, stack[stack.length - 1]);
    stack[stack.length - 1].children.push(el);
    if (!VOID_TAGS.has(lower) && !/\/>$/.test(m[0])) stack.push(el);
  }
  return rootEl;
}

function makeDocument(html) {
  const rootEl = parseHTML(html);
  const bodies = rootEl.querySelectorAll('body');
  return {
    root: rootEl,
    body: bodies[0] || rootEl,
    querySelectorAll: (sel) => rootEl.querySelectorAll(sel),
  };
}

// ---------------------------------------------------------------------------
// Static HTML fixtures
// ---------------------------------------------------------------------------

// 12 visible buttons + 1 hidden, 3 visible inputs + 1 hidden, 25 links.
// Includes duplicate classes and dynamic-looking ids.
const manyLinks = Array.from({ length: 25 }, (_, i) => `<a href="https://example.com/page-${i}">Link ${i}</a>`).join('\n');
const manyButtons = Array.from({ length: 12 }, (_, i) =>
  `<button id="btn-${Math.random().toString(36).slice(2, 8)}-${i}" class="btn action" aria-label="Action ${i}">Do thing ${i}</button>`
).join('\n');

const BIG_PAGE = `<!doctype html>
<html>
<head><title>Big Page</title></head>
<body>
  <nav>${manyLinks}</nav>
  <main>
    ${manyButtons}
    <button class="btn action" style="display:none">Hidden button</button>
    <input type="text" name="email" placeholder="Email address">
    <input type="password" name="password" aria-label="Password">
    <input type="search" placeholder="Search the site">
    <input type="hidden" name="csrf" style="display:none">
  </main>
</body>
</html>`;

// Two buttons sharing the same legacy selector (duplicate class) but
// distinguishable via aria-label; two more with identical text and no
// distinguishing attributes -> unavoidable conflict.
const CONFLICT_PAGE = `<!doctype html>
<html>
<body>
  <button class="btn primary" aria-label="Save draft">Save</button>
  <button class="btn primary" aria-label="Save and publish">Save</button>
  <button class="btn primary">Save</button>
  <button class="btn primary">Save</button>
  <input class="field" type="text" placeholder="Your name">
  <input class="field" type="text" placeholder="Your name">
</body>
</html>`;

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test('interactiveElements covers every visible button and input (no 10-item cap)', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(BIG_PAGE));
  const buttons = interactiveElements.filter((e) => e.type === 'button');
  const inputs = interactiveElements.filter((e) => e.type === 'input');
  assert.strictEqual(buttons.length, 12, 'all 12 visible buttons collected');
  assert.strictEqual(inputs.length, 3, 'all 3 visible inputs collected');
  assert.ok(!interactiveElements.some((e) => e.text === 'Hidden button'), 'hidden button excluded');
  assert.ok(interactiveElements.every((e) => e.placeholder !== undefined || e.text !== undefined));
});

test('links are not truncated to 20', () => {
  const { links } = collectSnapshot(makeDocument(BIG_PAGE));
  assert.strictEqual(links.length, 25);
  assert.deepStrictEqual(links[0], { text: 'Link 0', href: 'https://example.com/page-0' });
  assert.strictEqual(links[24].href, 'https://example.com/page-24');
});

test('legacy fields (type, text/placeholder, selector) are preserved', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(BIG_PAGE));
  const button = interactiveElements.find((e) => e.type === 'button');
  assert.strictEqual(button.text, 'Do thing 0');
  const input = interactiveElements.find((e) => e.type === 'input' && e.placeholder === 'Email address');
  assert.strictEqual(input.placeholder, 'Email address');

  // class-based legacy selector (element without id): first class token only
  const conflictSnap = collectSnapshot(makeDocument(CONFLICT_PAGE));
  const classed = conflictSnap.interactiveElements.find((e) => e.type === 'button');
  assert.strictEqual(classed.selector, 'button.btn', 'legacy selector still uses first class when id is absent');
});

test('legacy selector keeps the (possibly unstable) id; stableSelector does not rely on it', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(BIG_PAGE));
  for (const el of interactiveElements.filter((e) => e.type === 'button')) {
    assert.match(el.selector, /^#btn-/, 'legacy selector unchanged: still id-based');
    assert.ok(!el.stableSelector.startsWith('#'), 'stable selector avoids dynamic ids');
  }
});

test('stable candidates are unique for elements distinguishable by name/aria-label/placeholder', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(BIG_PAGE));
  for (const el of interactiveElements) {
    assert.strictEqual(el.unique, true, `expected unique candidate, got ${JSON.stringify(el)}`);
    assert.strictEqual(el.conflict, undefined, 'no conflict flagged when unique');
  }
  const byAria = interactiveElements.find((e) => e.text === 'Do thing 3');
  assert.strictEqual(byAria.stableSelector, 'button[aria-label="Action 3"]');
  const byName = interactiveElements.find((e) => e.placeholder === 'Email address');
  assert.strictEqual(byName.stableSelector, 'input[name="email"]');
  const byPlaceholder = interactiveElements.find((e) => e.placeholder === 'Search the site');
  assert.strictEqual(byPlaceholder.stableSelector, 'input[placeholder="Search the site"]');
});

test('duplicate classes: legacy selectors collide, stable selectors stay unique', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(CONFLICT_PAGE));
  const ariaButtons = interactiveElements.filter((e) => e.type === 'button' && e.stableSelector.includes('aria-label'));
  assert.strictEqual(ariaButtons.length, 2);
  assert.ok(ariaButtons.every((e) => e.selector === 'button.btn'), 'legacy selectors all collide on the shared class');
  assert.ok(ariaButtons.every((e) => e.unique === true));
  assert.deepStrictEqual(
    ariaButtons.map((e) => e.stableSelector).sort(),
    ['button[aria-label="Save and publish"]', 'button[aria-label="Save draft"]']
  );
});

test('unresolvable elements are explicitly flagged as conflicts, never silently ambiguous', () => {
  const { interactiveElements } = collectSnapshot(makeDocument(CONFLICT_PAGE));
  const conflictButtons = interactiveElements.filter((e) => e.type === 'button' && e.unique === false);
  assert.strictEqual(conflictButtons.length, 2, 'both identical "Save" buttons flagged');
  for (const el of conflictButtons) {
    assert.strictEqual(el.stableSelector, 'button:has-text("Save")');
    assert.ok(el.conflict, 'conflict marker present');
    assert.strictEqual(el.conflict.count, 4, 'candidate matches all 4 Save-text buttons');
  }
  const conflictInputs = interactiveElements.filter((e) => e.type === 'input' && e.unique === false);
  assert.strictEqual(conflictInputs.length, 2, 'both identical inputs flagged');
  for (const el of conflictInputs) {
    assert.strictEqual(el.stableSelector, 'input[placeholder="Your name"]');
    assert.strictEqual(el.conflict.count, 2);
  }
});

test('content is the body text truncated to 5000 characters', () => {
  const longText = 'lorem ipsum dolor sit amet '.repeat(300); // > 5000 chars
  const doc = makeDocument(`<html><body><p>${longText}</p><button>OK</button></body></html>`);
  const { content } = collectSnapshot(doc);
  const expected = doc.body.innerText.substring(0, 5000);
  assert.strictEqual(content, expected);
  assert.ok(content.length <= 5000);
  assert.ok(longText.replace(/\s+/g, ' ').trim().length > 5000, 'fixture actually exceeds the cap');
});

test('snapshot without a running browser fails with "Browser not started"', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'lobster-snap-'));
  try {
    const r = spawnSync(process.execPath, [cli, 'snapshot'], {
      encoding: 'utf8',
      env: { ...process.env, HOME: tmp, LOBSTER_PORT: '18999' },
    });
    assert.strictEqual(r.status, 0);
    assert.ok(r.stdout.includes('"success": false'), r.stdout);
    assert.ok(r.stdout.includes('Browser not started'), r.stdout);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
