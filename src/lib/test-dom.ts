// Minimal local DOM harness for URL-extraction tests, backed by linkedom.
// No real browser, no network: every document is parsed from an HTML string.
//
// linkedom does not implement layout, so getComputedStyle / viewport checks
// are stubbed here. Visibility via the `hidden` attribute and
// `aria-hidden="true"` still works because the engine reads attributes
// directly.

import { parseHTML } from "linkedom";
import { extractUrlsWithTrace } from "./url-extract.ts";
import type {
  UrlExtractionResult,
  UrlSourceMode,
  UrlVisibilityMode,
} from "./schemas.ts";

interface TestDom {
  document: Document;
  window: Window & {
    getComputedStyle: (el: Element) => CSSStyleDeclaration;
    innerWidth: number;
    innerHeight: number;
  };
}

interface HarnessOptions {
  html: string;
  /**
   * Per-element computed style overrides keyed by a CSS selector. Values not
   * listed fall back to a visible default (display:block, visibility:visible,
   * opacity:1).
   */
  computedStyles?: Record<string, Partial<CSSStyleDeclaration>>;
  /** getBoundingClientRect overrides keyed by a CSS selector. */
  rects?: Record<
    string,
    { top: number; bottom: number; left: number; right: number }
  >;
  innerWidth?: number;
  innerHeight?: number;
}

const DEFAULT_STYLE = {
  display: "block",
  visibility: "visible",
  opacity: "1",
} as const;

export function createTestDom(opts: HarnessOptions): TestDom {
  const { window, document } = parseHTML(opts.html);

  const win = window as unknown as TestDom["window"];
  win.innerWidth = opts.innerWidth ?? 1024;
  win.innerHeight = opts.innerHeight ?? 768;

  win.getComputedStyle = (el: Element): CSSStyleDeclaration => {
    const overrides = opts.computedStyles ?? {};
    let merged: Partial<CSSStyleDeclaration> = { ...DEFAULT_STYLE };
    for (const [selector, style] of Object.entries(overrides)) {
      if (el.matches(selector)) {
        merged = { ...merged, ...style };
      }
    }
    return merged as CSSStyleDeclaration;
  };

  if (opts.rects) {
    for (const [selector, rect] of Object.entries(opts.rects)) {
      for (const el of document.querySelectorAll(selector)) {
        el.getBoundingClientRect = (() =>
          ({
            x: rect.left,
            y: rect.top,
            width: rect.right - rect.left,
            height: rect.bottom - rect.top,
            top: rect.top,
            bottom: rect.bottom,
            left: rect.left,
            right: rect.right,
          }) as DOMRect) as Element["getBoundingClientRect"];
      }
    }
  }

  return { document, window: win };
}

interface ExtractCase {
  html: string;
  visibilityMode?: UrlVisibilityMode;
  sourceMode?: UrlSourceMode;
  computedStyles?: Record<string, Partial<CSSStyleDeclaration>>;
  rects?: Record<
    string,
    { top: number; bottom: number; left: number; right: number }
  >;
}

/** Parse HTML from a string and run the traced extractor in one call. */
export function extractFromHtml(caseOpts: ExtractCase): UrlExtractionResult {
  const dom = createTestDom({
    html: caseOpts.html,
    computedStyles: caseOpts.computedStyles,
    rects: caseOpts.rects,
  });
  return extractUrlsWithTrace({
    root: dom.document,
    visibilityMode: caseOpts.visibilityMode ?? "visible",
    sourceMode: caseOpts.sourceMode ?? "comprehensive",
  });
}
