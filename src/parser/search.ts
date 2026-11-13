import type { OSNode, SearchResult, SearchResultContext } from "../types.js";
import { truncateGraphemes } from "./truncation.js";

const SNIPPET_LIMIT = 100;
const HEADING_LIMIT = 80;
const PATH_LIMIT = 8;

const HEADING_TAGS = new Set(["h1", "h2", "h3", "h4", "h5", "h6", "heading"]);

/**
 * Landmark elements that define a named page region. Entering one resets the
 * "nearest heading" because headings belong to the enclosing landmark scope.
 * `section`/`article`/`aside` are ordinary sectioning content, not landmarks:
 * headings continue across them.
 */
const REGION_TAGS = new Set([
  "header",
  "footer",
  "nav",
  "main",
  "form",
  "dialog",
]);

/** Sectioning containers reported as region clues without resetting headings. */
const SECTION_TAGS = new Set(["section", "article", "aside"]);

const ACCESSIBLE_NAME_ATTRS = [
  "aria-label",
  "alt",
  "title",
  "placeholder",
] as const;

export interface SearchNodesOptions {
  needle: string;
  maxResults: number;
  /** Resolves a freshly-walked node id to the stable element id from the last read. */
  resolveStableId?: (nodeId: string) => string | undefined;
}

/**
 * Immutable position in the walked tree. `heading` is the nearest heading
 * encountered *before* the current position, so a fresh frame per sibling lets
 * an `<h2>` reached through one child label the paragraph sibling that follows.
 */
interface Frame {
  /** Retained-element tags from the root to the parent of the current node. */
  path: string[];
  /** Nearest interactive ancestor's stable/raw id, inherited by text matches. */
  nearestId?: string;
  regionTag?: string;
  regionName?: string;
  sectionTag?: string;
  sectionName?: string;
  heading?: string;
}

/**
 * Label an element with its 1-based position among same-tag siblings. The
 * first occurrence stays a plain tag; later ones carry `[n]` so repeated
 * identical structures (three list items, two links) never share a path.
 */
function siblingOrdinal(parent: OSNode, node: OSNode): number {
  let ordinal = 0;
  for (const child of parent.children) {
    if (child.tag !== node.tag) continue;
    ordinal += 1;
    if (child === node) return ordinal;
  }
  return ordinal;
}

/** First non-empty accessible-name attribute, in assistive-tech priority order. */
export function accessibleName(node: OSNode): string | undefined {
  for (const attr of ACCESSIBLE_NAME_ATTRS) {
    const value = node.attributes[attr]?.trim();
    if (value) return value;
  }
  return undefined;
}

function nodeText(node: OSNode): string {
  const parts: string[] = [];
  const collect = (current: OSNode): void => {
    if (current.text) parts.push(current.text);
    for (const child of current.children) collect(child);
  };
  collect(node);
  return parts.join(" ").replace(/\s+/g, " ").trim();
}

function describeLocation(frame: Frame, name: string | undefined): string {
  const parts: string[] = [];
  if (frame.regionTag) {
    parts.push(
      frame.regionName
        ? `${frame.regionTag} "${frame.regionName}"`
        : frame.regionTag
    );
  }
  const sectionTag = frame.sectionTag;
  if (sectionTag && sectionTag !== frame.regionTag) {
    parts.push(
      frame.sectionName
        ? `${sectionTag} "${frame.sectionName}"`
        : sectionTag
    );
  }
  if (frame.heading) parts.push(`heading "${frame.heading}"`);
  if (name) parts.push(`labeled "${name}"`);
  return parts.length > 0 ? parts.join(" > ") : "page";
}

function buildContext(
  frame: Frame,
  owner: OSNode,
  elementTag: string,
  name: string | undefined
): SearchResultContext {
  return {
    elementTag,
    sectionTag: frame.sectionTag ?? frame.regionTag,
    sectionName: frame.sectionName ?? frame.regionName,
    accessibleName: name,
    heading: frame.heading,
    location: describeLocation(frame, name),
    path: [...frame.path, owner.tag].slice(-PATH_LIMIT),
  };
}

function resolveId(node: OSNode, options: SearchNodesOptions): string | undefined {
  if (!node.id) return undefined;
  return options.resolveStableId?.(node.id) ?? node.id;
}

/**
 * Walk a compressed OSNode tree and collect text matching `needle`, stopping
 * once `maxResults` hits are found. Every hit carries region/heading clues so
 * repeated text in different sections stays distinguishable.
 */
export function searchNodes(
  roots: OSNode[],
  options: SearchNodesOptions
): SearchResult[] {
  const results: SearchResult[] = [];

  const visit = (node: OSNode, owner: OSNode, parent: OSNode, frame: Frame): void => {
    if (results.length >= options.maxResults) return;

    if (node.tag === "#text") {
      const text = node.text?.trim();
      if (text && text.toLowerCase().includes(options.needle)) {
        results.push({
          text: truncateGraphemes(text, SNIPPET_LIMIT),
          // Legacy semantics: text hits report the owning element's tag.
          tag: owner.tag,
          index: results.length + 1,
          elementId: frame.nearestId,
          context: buildContext(frame, owner, "#text", accessibleName(owner)),
        });
      }
      return;
    }

    const name = accessibleName(node);
    const isRegion = REGION_TAGS.has(node.tag);
    const isSection = SECTION_TAGS.has(node.tag);
    const ownId = resolveId(node, options);
    const ordinal = siblingOrdinal(parent, node);
    const pathSegment = ordinal > 1 ? `${node.tag}[${ordinal}]` : node.tag;

    const next: Frame = {
      path: [...frame.path, pathSegment].slice(-PATH_LIMIT),
      nearestId: frame.nearestId ?? ownId,
      regionTag: isRegion ? node.tag : frame.regionTag,
      regionName: isRegion ? name : frame.regionName,
      sectionTag: isSection ? node.tag : frame.sectionTag,
      sectionName: isSection ? name : frame.sectionName,
      // Landmarks start a fresh heading scope; sectioning content keeps the
      // flow heading already in scope.
      heading: isRegion ? undefined : frame.heading,
    };

    // Element-level hit: synthesized node text (mode summaries, truncated
    // markers) or a leaf element carrying text without text children.
    const ownText = node.text?.trim();
    if (ownText && ownText.toLowerCase().includes(options.needle)) {
      results.push({
        text: truncateGraphemes(ownText, SNIPPET_LIMIT),
        tag: node.tag,
        index: results.length + 1,
        elementId: ownId,
        context: buildContext(next, node, node.tag, name),
      });
      if (results.length >= options.maxResults) return;
    }

    // A heading reached through one child labels the sibling elements that
    // follow it; each sibling therefore receives a frame carrying the latest
    // heading rather than sharing the pre-heading frame.
    let siblingFrame = next;
    for (const child of node.children) {
      if (results.length >= options.maxResults) return;
      if (HEADING_TAGS.has(child.tag)) {
        const heading = truncateGraphemes(nodeText(child), HEADING_LIMIT);
        siblingFrame = { ...siblingFrame, heading: heading || siblingFrame.heading };
      }
      visit(child, child.tag === "#text" ? node : child, node, siblingFrame);
    }
  };

  const virtualRoot: OSNode = { tag: "#root", attributes: {}, children: roots };
  const rootFrame: Frame = { path: [] };
  for (const root of roots) {
    if (results.length >= options.maxResults) break;
    visit(root, root, virtualRoot, rootFrame);
  }

  return results;
}
