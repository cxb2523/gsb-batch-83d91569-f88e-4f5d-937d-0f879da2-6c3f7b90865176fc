import type {
  UrlCandidateRecord,
  UrlCandidateStatus,
  UrlExtractionResult,
  UrlRecord,
  UrlSortMode,
  UrlSourceCategory,
  UrlVisibilityMode,
  UrlSourceMode,
} from "./schemas.ts";

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

// Spec constants; fallbacks keep the engine runnable in lightweight DOM
// implementations used by tests (real browsers always define these).
const DOM_NODE_FILTER: typeof NodeFilter | undefined =
  typeof globalThis.NodeFilter !== "undefined"
    ? globalThis.NodeFilter
    : undefined;
const DOM_NODE: typeof Node | undefined =
  typeof globalThis.Node !== "undefined" ? globalThis.Node : undefined;
const NODE_FILTER_SHOW_TEXT = DOM_NODE_FILTER?.SHOW_TEXT ?? 4;
const NODE_FILTER_ACCEPT = DOM_NODE_FILTER?.FILTER_ACCEPT ?? 1;
const NODE_FILTER_REJECT = DOM_NODE_FILTER?.FILTER_REJECT ?? 2;
const DOCUMENT_POSITION_FOLLOWING = DOM_NODE?.DOCUMENT_POSITION_FOLLOWING ?? 4;
const DOCUMENT_POSITION_PRECEDING = DOM_NODE?.DOCUMENT_POSITION_PRECEDING ?? 2;

interface NormalizedUrl {
  url: string;
  domain: string;
}

export function parseAndNormalize(
  raw: string,
  baseUrl: string,
): NormalizedUrl | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return null;
  }
  try {
    const parsed = new URL(trimmed, baseUrl);
    if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
      return null;
    }
    return {
      url: parsed.toString(),
      domain: parsed.hostname.toLowerCase(),
    };
  } catch {
    return null;
  }
}

/**
 * Human-readable reason for a rejected raw value. Mirrors parseAndNormalize
 * so the trace can explain *why* parsing failed.
 */
function describeParseFailure(raw: string, baseUrl: string): string {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "Empty value";
  }
  try {
    const parsed = new URL(trimmed, baseUrl);
    if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
      return `Protocol "${parsed.protocol}" is not allowed (http/https only)`;
    }
  } catch {
    return "Value cannot be parsed as a URL";
  }
  return "Value cannot be parsed as a URL";
}

type SourceCandidate = {
  raw: string;
  element: Element;
  sourceCategory: UrlSourceCategory;
  /**
   * Source mode that enables this candidate. "always" sources (anchors/area)
   * are collected in every sourceMode.
   */
  enabledIn: UrlSourceMode | "always";
};

function collectFromAttr(
  root: Document,
  selector: string,
  attr: string,
  sourceCategory: UrlSourceCategory,
  enabledIn: UrlSourceMode | "always",
): SourceCandidate[] {
  const out: SourceCandidate[] = [];
  for (const el of root.querySelectorAll(selector)) {
    const raw = el.getAttribute(attr);
    if (raw !== null) {
      out.push({ raw, element: el, sourceCategory, enabledIn });
    }
  }
  return out;
}

function collectAnchors(root: Document): SourceCandidate[] {
  return [
    ...collectFromAttr(root, "a[href]", "href", "anchor", "always"),
    ...collectFromAttr(root, "area[href]", "href", "area", "always"),
  ];
}

function collectMedia(root: Document): SourceCandidate[] {
  return [
    ...collectFromAttr(root, "iframe[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "img[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "video[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "audio[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "source[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "embed[src]", "src", "media", "comprehensive"),
    ...collectFromAttr(root, "object[data]", "data", "media", "comprehensive"),
  ];
}

const URL_TEXT_REGEX = /\bhttps?:\/\/[^\s<>"'`)]+/gi;

function collectTextUrls(root: Document): SourceCandidate[] {
  const out: SourceCandidate[] = [];
  const walker = root.createTreeWalker(root.body, NODE_FILTER_SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) {
        return NODE_FILTER_REJECT;
      }
      const tag = parent.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") {
        return NODE_FILTER_REJECT;
      }
      return NODE_FILTER_ACCEPT;
    },
  });
  let node = walker.nextNode();
  while (node !== null) {
    const text = node.textContent ?? "";
    const matches = text.match(URL_TEXT_REGEX);
    if (matches !== null && node.parentElement !== null) {
      for (const raw of matches) {
        out.push({
          raw,
          element: node.parentElement,
          sourceCategory: "text",
          enabledIn: "comprehensive",
        });
      }
    }
    node = walker.nextNode();
  }
  return out;
}

function collectHeadAndScripts(root: Document): SourceCandidate[] {
  const out: SourceCandidate[] = [];
  for (const el of root.querySelectorAll("link[href]")) {
    const rel = (el.getAttribute("rel") ?? "").toLowerCase();
    if (
      rel.includes("stylesheet") ||
      rel.includes("preconnect") ||
      rel.includes("dns-prefetch")
    ) {
      continue;
    }
    const raw = el.getAttribute("href");
    if (raw !== null) {
      out.push({
        raw,
        element: el,
        sourceCategory: "head",
        enabledIn: "everything",
      });
    }
  }
  for (const el of root.querySelectorAll("script[src]")) {
    const raw = el.getAttribute("src");
    if (raw !== null) {
      out.push({
        raw,
        element: el,
        sourceCategory: "script",
        enabledIn: "everything",
      });
    }
  }
  for (const el of root.querySelectorAll("meta[content]")) {
    const raw = el.getAttribute("content") ?? "";
    if (/^https?:\/\//i.test(raw)) {
      out.push({
        raw,
        element: el,
        sourceCategory: "meta",
        enabledIn: "everything",
      });
    }
  }
  return out;
}

function isInHead(element: Element): boolean {
  let cur: Element | null = element;
  while (cur !== null) {
    if (cur.tagName === "HEAD") {
      return true;
    }
    cur = cur.parentElement;
  }
  return false;
}

function isComputedVisible(element: Element): boolean {
  let cur: Element | null = element;
  while (cur !== null) {
    if (cur.hasAttribute("hidden")) {
      return false;
    }
    if (cur.getAttribute("aria-hidden") === "true") {
      return false;
    }
    const style = element.ownerDocument.defaultView?.getComputedStyle(cur);
    if (style) {
      if (style.display === "none") {
        return false;
      }
      if (style.visibility === "hidden") {
        return false;
      }
      if (style.visibility === "collapse") {
        return false;
      }
      if (parseFloat(style.opacity) === 0) {
        return false;
      }
    }
    cur = cur.parentElement;
  }
  return true;
}

function isInViewport(element: Element): boolean {
  const rect = element.getBoundingClientRect();
  const win = element.ownerDocument.defaultView;
  if (!win) {
    return true;
  }
  return (
    rect.top < win.innerHeight &&
    rect.bottom > 0 &&
    rect.left < win.innerWidth &&
    rect.right > 0
  );
}

function passesVisibility(element: Element, mode: UrlVisibilityMode): boolean {
  if (mode === "all") {
    return true;
  }
  if (!isComputedVisible(element)) {
    return false;
  }
  if (mode === "visible") {
    return true;
  }
  return isInViewport(element);
}

function sortByDocumentPosition(candidates: SourceCandidate[]): void {
  candidates.sort((a, b) => {
    if (a.element === b.element) {
      return 0;
    }
    const pos = a.element.compareDocumentPosition(b.element);
    // compareDocumentPosition returns a bitmask; bitwise-AND is the spec API.
    // eslint-disable-next-line no-bitwise
    if ((pos & DOCUMENT_POSITION_FOLLOWING) !== 0) {
      return -1;
    }
    // eslint-disable-next-line no-bitwise
    if ((pos & DOCUMENT_POSITION_PRECEDING) !== 0) {
      return 1;
    }
    return 0;
  });
}

export function sortUrls(records: UrlRecord[], mode: UrlSortMode): UrlRecord[] {
  const copy = [...records];
  if (mode === "pageOrder") {
    copy.sort((a, b) => a.firstIndex - b.firstIndex);
    return copy;
  }
  copy.sort((a, b) => a.url.toLowerCase().localeCompare(b.url.toLowerCase()));
  return copy;
}

const SOURCE_MODE_RANK: Record<UrlSourceMode, number> = {
  anchors: 0,
  comprehensive: 1,
  everything: 2,
};

function sourceIsEnabled(
  candidate: SourceCandidate,
  sourceMode: UrlSourceMode,
): boolean {
  if (candidate.enabledIn === "always") {
    return true;
  }
  return SOURCE_MODE_RANK[sourceMode] >= SOURCE_MODE_RANK[candidate.enabledIn];
}

const SOURCE_DISABLED_REASON: Record<UrlSourceMode, string> = {
  anchors:
    "Source not enabled: Anchors-only mode collects just <a>/<area> links",
  comprehensive:
    "Source not enabled: head, scripts and meta require Everything mode",
  everything: "Source not enabled by the current source mode",
};

function describeInvisibility(
  element: Element,
  mode: UrlVisibilityMode,
): string {
  if (!isComputedVisible(element)) {
    let cur: Element | null = element;
    while (cur !== null) {
      if (cur.hasAttribute("hidden")) {
        return "Element (or an ancestor) is hidden via the hidden attribute";
      }
      if (cur.getAttribute("aria-hidden") === "true") {
        return "Element (or an ancestor) is marked aria-hidden";
      }
      const style = element.ownerDocument.defaultView?.getComputedStyle(cur);
      if (style) {
        if (style.display === "none") {
          return "Element (or an ancestor) has display: none";
        }
        if (style.visibility === "hidden" || style.visibility === "collapse") {
          return `Element (or an ancestor) has visibility: ${style.visibility}`;
        }
        if (parseFloat(style.opacity) === 0) {
          return "Element (or an ancestor) has opacity: 0";
        }
      }
      cur = cur.parentElement;
    }
  }
  if (mode === "viewport") {
    return "Element is outside the current viewport";
  }
  return "Element is not visible";
}

interface ExtractVisibleUrlsOpts {
  root: Document;
  visibilityMode: UrlVisibilityMode;
  sourceMode: UrlSourceMode;
}

/**
 * Runs the full URL-collection pipeline and returns both the accepted URL
 * records and a per-candidate decision trace. The accepted list is identical
 * to what extractVisibleUrls returns for the same inputs.
 *
 * Every supported source is collected up front so that candidates filtered out
 * by the source-mode gate still appear in the trace.
 */
export function extractUrlsWithTrace(
  opts: ExtractVisibleUrlsOpts,
): UrlExtractionResult {
  const { root, visibilityMode, sourceMode } = opts;

  const candidates: SourceCandidate[] = [
    ...collectAnchors(root),
    ...collectMedia(root),
    ...collectTextUrls(root),
    ...collectHeadAndScripts(root),
  ];

  sortByDocumentPosition(candidates);

  const baseUrl = root.baseURI;
  const records = new Map<string, UrlRecord>();
  const trace: UrlCandidateRecord[] = [];
  const occurrenceByUrl = new Map<string, number>();
  let counter = 0;

  candidates.forEach((candidate, index) => {
    const { raw, element, sourceCategory } = candidate;

    const fail = (
      status: UrlCandidateStatus,
      reason: string,
    ): UrlCandidateRecord => ({
      index,
      rawValue: raw,
      sourceCategory,
      status,
      url: null,
      domain: null,
      reason,
      occurrence: 1,
    });

    // Filter order mirrors the legacy pipeline exactly:
    // head gate -> visibility gate -> parse -> source-mode gate -> dedupe.
    if (sourceMode !== "everything" && isInHead(element)) {
      trace.push(
        fail(
          "skipped",
          "Element is inside <head>; switch to Everything mode to include it",
        ),
      );
      return;
    }

    if (!passesVisibility(element, visibilityMode)) {
      trace.push(
        fail("invisible", describeInvisibility(element, visibilityMode)),
      );
      return;
    }

    if (!sourceIsEnabled(candidate, sourceMode)) {
      trace.push(fail("sourceDisabled", SOURCE_DISABLED_REASON[sourceMode]));
      return;
    }

    const normalized = parseAndNormalize(raw, baseUrl);
    if (normalized === null) {
      trace.push(fail("parseFailed", describeParseFailure(raw, baseUrl)));
      return;
    }

    const occurrence = (occurrenceByUrl.get(normalized.url) ?? 0) + 1;
    occurrenceByUrl.set(normalized.url, occurrence);

    const existing = records.get(normalized.url);
    if (existing !== undefined) {
      existing.count += 1;
      trace.push({
        index,
        rawValue: raw,
        sourceCategory,
        status: "duplicate",
        url: normalized.url,
        domain: normalized.domain,
        reason: `Duplicate of an earlier candidate (occurrence #${occurrence})`,
        occurrence,
      });
      return;
    }

    records.set(normalized.url, {
      url: normalized.url,
      domain: normalized.domain,
      firstIndex: counter,
      count: 1,
    });
    counter += 1;
    trace.push({
      index,
      rawValue: raw,
      sourceCategory,
      status: "included",
      url: normalized.url,
      domain: normalized.domain,
      reason: "Collected",
      occurrence: 1,
    });
  });

  return {
    urls: Array.from(records.values()),
    candidates: trace,
  };
}

export function extractVisibleUrls(opts: ExtractVisibleUrlsOpts): UrlRecord[] {
  return extractUrlsWithTrace(opts).urls;
}
