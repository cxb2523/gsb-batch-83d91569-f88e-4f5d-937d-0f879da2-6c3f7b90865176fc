import type { CDPNode, DOMSnapshotData } from "../../src/cdp/snapshot.js";
import { SNAPSHOT_COMPUTED_STYLES } from "../../src/cdp/snapshot.js";

/**
 * Minimal, dependency-free HTML used only by unit tests. It deliberately
 * supports the subset of HTML the search tests need (elements, attributes,
 * text, void elements) without pulling in a parser dependency or touching the
 * network. The output is fed through the same snapshot decoder + DOM walker
 * the real CDP path uses, so tests exercise production parsing code.
 */

interface ParsedElement {
  tag: string;
  attrs: Record<string, string>;
  children: ParsedNode[];
}

type ParsedNode = ParsedElement | { text: string };

const VOID_TAGS = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
]);

const TAG_NAME = /[a-zA-Z][a-zA-Z0-9-]*/y;
const ATTRIBUTE_NAME = /[^\s=/>"'`]+/y;

class HtmlParser {
  private index = 0;

  constructor(private readonly source: string) {}

  parse(): ParsedElement {
    const root: ParsedElement = { tag: "#root", attrs: {}, children: [] };
    const stack: ParsedElement[] = [root];

    while (this.index < this.source.length) {
      const next = this.source.indexOf("<", this.index);
      if (next < 0) {
        this.appendText(stack, this.source.slice(this.index));
        break;
      }
      if (next > this.index) {
        this.appendText(stack, this.source.slice(this.index, next));
      }
      this.index = next;
      if (this.source.startsWith("<!--", this.index)) {
        const end = this.source.indexOf("-->", this.index + 4);
        this.index = end < 0 ? this.source.length : end + 3;
        continue;
      }
      if (this.source.startsWith("<!", this.index) || this.source.startsWith("<?", this.index)) {
        const end = this.source.indexOf(">", this.index);
        this.index = end < 0 ? this.source.length : end + 1;
        continue;
      }
      this.consumeTag(stack);
    }
    return root;
  }

  private appendText(stack: ParsedElement[], raw: string): void {
    const text = decodeEntities(raw);
    if (!text) return;
    const parent = stack[stack.length - 1];
    const previous = parent.children[parent.children.length - 1];
    if (previous && "text" in previous) {
      previous.text += text;
    } else {
      parent.children.push({ text });
    }
  }

  private consumeTag(stack: ParsedElement[]): void {
    // Positioned at "<".
    this.index += 1;
    if (this.source[this.index] === "/") {
      this.index += 1;
      const name = this.readTagName().toLowerCase();
      this.skipUntil(">");
      this.index += 1;
      for (let depth = stack.length - 1; depth > 0; depth--) {
        if (stack[depth].tag === name) {
          stack.length = depth;
          break;
        }
      }
      return;
    }

    const name = this.readTagName().toLowerCase();
    const attrs = this.readAttributes();
    const selfClosing = this.skipUntil(">");
    this.index += 1;

    const element: ParsedElement = { tag: name, attrs, children: [] };
    stack[stack.length - 1].children.push(element);
    if (!VOID_TAGS.has(name) && !selfClosing) {
      stack.push(element);
    }
  }

  private readTagName(): string {
    TAG_NAME.lastIndex = this.index;
    const match = TAG_NAME.exec(this.source);
    if (!match) return "";
    this.index = TAG_NAME.lastIndex;
    return match[0];
  }

  private readAttributes(): Record<string, string> {
    const attrs: Record<string, string> = {};
    for (;;) {
      while (/\s/.test(this.source[this.index] ?? "")) this.index += 1;
      if (this.source[this.index] === ">" || this.source[this.index] === "/" || this.index >= this.source.length) {
        break;
      }
      ATTRIBUTE_NAME.lastIndex = this.index;
      const nameMatch = ATTRIBUTE_NAME.exec(this.source);
      if (!nameMatch) {
        this.index += 1;
        continue;
      }
      const name = nameMatch[0].toLowerCase();
      this.index = ATTRIBUTE_NAME.lastIndex;
      while (/\s/.test(this.source[this.index] ?? "")) this.index += 1;
      let value = "";
      if (this.source[this.index] === "=") {
        this.index += 1;
        while (/\s/.test(this.source[this.index] ?? "")) this.index += 1;
        const quote = this.source[this.index];
        if (quote === '"' || quote === "'") {
          const end = this.source.indexOf(quote, this.index + 1);
          value = end < 0 ? this.source.slice(this.index + 1) : this.source.slice(this.index + 1, end);
          this.index = end < 0 ? this.source.length : end + 1;
        } else {
          const start = this.index;
          while (this.index < this.source.length && !/[\s>]/.test(this.source[this.index])) {
            this.index += 1;
          }
          value = this.source.slice(start, this.index);
        }
      }
      attrs[name] = decodeEntities(value);
    }
    return attrs;
  }

  /** Advances past the next ">"; returns true if a self-closing slash preceded it. */
  private skipUntil(terminator: string): boolean {
    let selfClosing = false;
    while (this.index < this.source.length && this.source[this.index] !== terminator) {
      if (this.source[this.index] === "/") selfClosing = true;
      this.index += 1;
    }
    return selfClosing;
  }
}

function decodeEntities(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

/** Parse a local HTML string into a synthetic CDP DOMSnapshot.captureSnapshot payload. */
export function htmlToSnapshot(
  html: string,
  metadata: { url?: string; title?: string } = {}
): DOMSnapshotData {
  const parsed = new HtmlParser(html).parse();

  const strings: string[] = [];
  const stringIndices = new Map<string, number>();
  const intern = (value: string): number => {
    if (value === "") return -1;
    const existing = stringIndices.get(value);
    if (existing !== undefined) return existing;
    const index = strings.length;
    strings.push(value);
    stringIndices.set(value, index);
    return index;
  };

  const parentIndex: number[] = [];
  const nodeType: number[] = [];
  const nodeName: number[] = [];
  const nodeValue: number[] = [];
  const backendNodeId: number[] = [];
  const attributes: number[][] = [];
  const layoutNodeIndex: number[] = [];
  const layoutStyles: number[][] = [];
  const layoutBounds: number[][] = [];
  const defaultStyle = SNAPSHOT_COMPUTED_STYLES.map((name) =>
    intern(DEFAULT_STYLE[name] ?? "visible")
  );

  let nextBackendId = 1;

  const emit = (node: ParsedNode, parent: number): void => {
    const index = parentIndex.length;
    parentIndex.push(parent);
    if ("text" in node) {
      nodeType.push(3);
      nodeName.push(intern("#text"));
      nodeValue.push(intern(node.text));
      backendNodeId.push(nextBackendId++);
      attributes.push([]);
      return;
    }
    nodeType.push(1);
    nodeName.push(intern(node.tag.toUpperCase()));
    nodeValue.push(intern(""));
    backendNodeId.push(nextBackendId++);
    const flat: string[] = [];
    for (const [key, value] of Object.entries(node.attrs)) {
      flat.push(key, value);
    }
    attributes.push(flat.map((value) => intern(value)));
    layoutNodeIndex.push(index);
    layoutStyles.push([...defaultStyle]);
    layoutBounds.push([0, 0, 800, 20]);
    for (const child of node.children) emit(child, index);
  };

  // Synthetic #document root, matching the real snapshot column layout.
  const documentIndex = 0;
  parentIndex.push(-1);
  nodeType.push(9);
  nodeName.push(intern("#document"));
  nodeValue.push(intern(""));
  backendNodeId.push(nextBackendId++);
  attributes.push([]);
  for (const child of parsed.children) emit(child, documentIndex);

  return {
    strings,
    documents: [
      {
        documentURL: intern(metadata.url ?? "https://example.test/"),
        title: intern(metadata.title ?? "Test page"),
        frameId: intern("main-frame"),
        scrollOffsetX: 0,
        scrollOffsetY: 0,
        contentWidth: 800,
        contentHeight: 600,
        nodes: {
          parentIndex,
          nodeType,
          nodeName,
          nodeValue,
          backendNodeId,
          attributes,
        },
        layout: {
          nodeIndex: layoutNodeIndex,
          styles: layoutStyles,
          bounds: layoutBounds,
        },
      },
    ],
  };
}

const DEFAULT_STYLE: Record<string, string> = {
  display: "block",
  visibility: "visible",
  opacity: "1",
  "content-visibility": "visible",
  "clip-path": "none",
  "overflow-x": "visible",
  "overflow-y": "visible",
  "pointer-events": "auto",
  contain: "none",
  clip: "auto",
  position: "static",
};

/** Build a CDPNode tree directly from HTML for parser-level unit tests. */
export function htmlToCdpNodes(html: string): CDPNode {
  const parsed = new HtmlParser(html).parse();
  let backendId = 1;

  const convert = (node: ParsedNode): CDPNode => {
    if ("text" in node) {
      return {
        nodeId: 0,
        backendNodeId: backendId++,
        nodeType: 3,
        nodeName: "#text",
        localName: "",
        nodeValue: node.text,
      };
    }
    const children = node.children.map(convert);
    return {
      nodeId: 0,
      backendNodeId: backendId++,
      nodeType: 1,
      nodeName: node.tag.toUpperCase(),
      localName: node.tag,
      nodeValue: "",
      attributes: Object.entries(node.attrs).flatMap(([key, value]) => [key, value]),
      children,
      childNodeCount: children.length,
    };
  };

  return {
    nodeId: 0,
    backendNodeId: backendId++,
    nodeType: 9,
    nodeName: "#document",
    localName: "",
    nodeValue: "",
    children: parsed.children.map(convert),
    childNodeCount: parsed.children.length,
  };
}
