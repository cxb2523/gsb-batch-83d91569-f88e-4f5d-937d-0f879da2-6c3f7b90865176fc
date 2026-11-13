/* Minimal DOM stand-ins so the real card class can run under `node --test` without a browser.
   The card only touches HTMLElement/shadowRoot.query* and the `customElements` registry. */

class FakeNode {
  constructor(selector) {
    this.selector = selector;
    this.className = '';
    this.textContent = '';
    this.hidden = false;
    this.style = {};
    this._listeners = new Map();
  }
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  dispatchEvent(ev) {
    for (const fn of this._listeners.get(ev.type) || []) fn(ev);
    return true;
  }
  setAttribute() {}
}

class FakeShadowRoot {
  constructor() { this._nodes = new Map(); this._html = ''; }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  querySelector(selector) {
    if (!this._nodes.has(selector)) this._nodes.set(selector, new FakeNode(selector));
    return this._nodes.get(selector);
  }
}

class FakeHTMLElement {
  constructor() { this._shadowRoot = null; }
  attachShadow() { return (this._shadowRoot ||= new FakeShadowRoot()); }
  get shadowRoot() { return this._shadowRoot; }
  dispatchEvent() { return true; }
  addEventListener() {}
}

/* Install the globals the card modules expect. Safe to call more than once. */
export function installDom() {
  globalThis.HTMLElement = globalThis.HTMLElement || FakeHTMLElement;
  globalThis.customElements = globalThis.customElements || {
    _map: new Map(),
    get(name) { return this._map.get(name); },
    define(name, ctor) { this._map.set(name, ctor); },
  };
  globalThis.document = globalThis.document || {
    querySelector: () => null,
    createElement: () => new FakeHTMLElement(),
  };
  globalThis.window = globalThis.window || globalThis;
  globalThis.window.customCards = globalThis.window.customCards || [];
}

/* Text/visibility of one node inside the card's shadow root. */
export const nodeText = (card, selector) => card.shadowRoot.querySelector(selector).textContent;
export const nodeHidden = (card, selector) => card.shadowRoot.querySelector(selector).hidden;
