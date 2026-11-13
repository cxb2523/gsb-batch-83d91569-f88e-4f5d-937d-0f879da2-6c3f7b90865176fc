import { describe, it, expect, jest } from "bun:test";
import { EventEmitter } from "node:events";
import { SurfingPage } from "../../src/cdp/page.js";
import type { CDPConnection } from "../../src/cdp/connection.js";
import { decodeDOMSnapshot } from "../../src/cdp/snapshot.js";
import { walkDOM } from "../../src/parser/dom-walker.js";
import { searchNodes, accessibleName } from "../../src/parser/search.js";
import type { OSNode } from "../../src/types.js";
import { ValidationError } from "../../src/errors.js";
import { htmlToSnapshot, htmlToCdpNodes } from "../support/html-snapshot.js";

const MARKERS = {
  visible: "data-test-visible",
  hidden: "data-test-hidden",
  state: "data-test-state",
  text: "data-test-text",
};

/** Decode locally-built HTML through the production snapshot + walker pipeline. */
function walkHtml(html: string): { nodes: OSNode[]; nodeMap: Map<string, number> } {
  const snapshot = decodeDOMSnapshot(htmlToSnapshot(html), {
    viewportWidth: 800,
    viewportHeight: 600,
    markViewport: false,
    markHidden: true,
    markerAttributes: MARKERS,
  });
  return walkDOM(snapshot.root, {
    truncate: false,
    markerAttributes: MARKERS,
  });
}

function preflight() {
  return {
    result: {
      value: {
        nodeCount: 50,
        characterCount: 500,
        viewportWidth: 800,
        viewportHeight: 600,
      },
    },
  };
}

/** A CDP connection whose only "page" is the supplied local HTML; no sockets. */
function mockConnection(html: string): {
  conn: CDPConnection;
  send: ReturnType<typeof jest.fn>;
} {
  const send = jest.fn().mockResolvedValue(htmlToSnapshot(html));
  const conn = {
    client: Object.assign(new EventEmitter(), {
      close: jest.fn(),
      send,
    }) as unknown as CDPConnection["client"],
    DOM: {} as unknown as CDPConnection["DOM"],
    Page: {} as unknown as CDPConnection["Page"],
    Runtime: {
      evaluate: jest.fn().mockResolvedValue(preflight()),
    } as unknown as CDPConnection["Runtime"],
    Emulation: {} as unknown as CDPConnection["Emulation"],
    disconnected: false,
    ownsBrowser: false,
  } as CDPConnection;
  return { conn, send };
}

const REGION_HTML = `
<html>
  <body>
    <header>
      <nav aria-label="Site navigation">
        <a href="/home">Home</a>
      </nav>
    </header>
    <main>
      <h1>Quarterly results</h1>
      <section aria-label="News section">
        <h2>Company news</h2>
        <p>Read more about the quarterly report in the news.</p>
        <a href="/news">Read more</a>
      </section>
      <section aria-label="Footer section">
        <h2>Legal notices</h2>
        <p>Read more in our terms and conditions archive.</p>
        <a href="/legal">Read more</a>
      </section>
      <button aria-label="Subscribe to updates">Subscribe</button>
      <input placeholder="Email address" />
      <img alt="Quarterly chart thumbnail" src="/chart.png" />
    </main>
  </body>
</html>`;

describe("searchNodes region clues", () => {
  it("returns normal hits with tag, accessible name, heading, and a location", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const results = searchNodes(nodes, { needle: "subscribe", maxResults: 10 });

    // The match is the button's text node; the button itself supplies the id.
    expect(results).toHaveLength(1);
    const hit = results[0];
    expect(hit.text).toBe("Subscribe");
    expect(hit.tag).toBe("button");
    expect(hit.index).toBe(1);
    expect(hit.elementId).toBe("B1");
    expect(hit.context.elementTag).toBe("#text");
    expect(hit.context.path.at(-1)).toBe("button");
    expect(hit.context.accessibleName).toBe("Subscribe to updates");
    expect(hit.context.location).toContain("main");
  });

  it("keeps the element-level accessible name for leaf elements matched directly", () => {
    const { nodes } = walkHtml(
      `<html><body><button aria-label="Subscribe to updates">Subscribe</button></body></html>`
    );
    const button = findNode(nodes, (node) => node.tag === "button")!;
    expect(accessibleName(button)).toBe("Subscribe to updates");
    const results = searchNodes(nodes, { needle: "subscribe", maxResults: 10 });
    expect(results[0].context.accessibleName).toBe("Subscribe to updates");
    expect(results[0].elementId).toBe("B1");
  });

  it("exposes placeholder as the accessible name for inputs", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const input = findNode(nodes, (node) => node.tag === "input");
    expect(input).toBeDefined();
    expect(accessibleName(input!)).toBe("Email address");
    expect(input!.id).toMatch(/^I\d+$/);
  });

  it("reads alt text as the accessible name for images", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const image = findNode(nodes, (node) => node.tag === "img");
    expect(image).toBeDefined();
    expect(accessibleName(image!)).toBe("Quarterly chart thumbnail");
  });

  it("distinguishes identical text in different sections by region and heading", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const results = searchNodes(nodes, { needle: "read more", maxResults: 10 });

    // Two text paragraphs plus two links share the phrase.
    expect(results).toHaveLength(4);
    const locations = new Set(results.map((r) => r.context.location));
    expect(locations.size).toBe(results.length);

    const news = results.find((r) => r.context.sectionName === "News section");
    const legal = results.find((r) => r.context.sectionName === "Footer section");
    expect(news).toBeDefined();
    expect(legal).toBeDefined();
    expect(news!.context.heading).toBe("Company news");
    expect(legal!.context.heading).toBe("Legal notices");
    expect(news!.context.sectionTag).toBe("section");
    expect(legal!.context.sectionTag).toBe("section");
    // The link hits retain directly-clickable stable ids (the nav "Home"
    // link is assigned first, so the section links are L2/L3).
    const links = results.filter((r) => r.elementId);
    expect(links.map((r) => r.elementId).sort()).toEqual(["L2", "L3"]);
    // The bare paragraph hits have no interactive ancestor and stay empty.
    const paragraphs = results.filter((r) => r.elementId === undefined);
    expect(paragraphs).toHaveLength(2);
  });

  it("attributes nav landmark text to the named navigation region", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const results = searchNodes(nodes, { needle: "home", maxResults: 10 });

    expect(results).toHaveLength(1);
    expect(results[0].context.sectionTag).toBe("nav");
    expect(results[0].context.sectionName).toBe("Site navigation");
    expect(results[0].context.location).toContain("Site navigation");
  });

  it("leaves elementId empty for plain text with no interactive ancestor", () => {
    const html = `<html><body><main><p>Quarterly figures are published below.</p></main></body></html>`;
    const { nodes } = walkHtml(html);
    const results = searchNodes(nodes, { needle: "quarterly", maxResults: 10 });

    expect(results).toHaveLength(1);
    // The collapsed paragraph leaves a #text node whose nearest retained
    // ancestor is the landmark main element.
    expect(results[0].tag).toBe("main");
    expect(results[0].elementId).toBeUndefined();
    expect(results[0].context.elementTag).toBe("#text");
    expect(results[0].context.sectionTag).toBe("main");
    expect(results[0].context.location).toContain("main");
  });

  it("enforces maxResults strictly and numbers hits from one", () => {
    const { nodes } = walkHtml(REGION_HTML);
    const all = searchNodes(nodes, { needle: "read more", maxResults: 50 });
    const limited = searchNodes(nodes, { needle: "read more", maxResults: 2 });

    expect(all.length).toBeGreaterThan(2);
    expect(limited).toHaveLength(2);
    expect(limited.map((r) => r.index)).toEqual([1, 2]);
    expect(limited).toEqual(all.slice(0, 2));
  });

  it("truncates long snippets at grapheme boundaries", () => {
    const longText = `${"a".repeat(120)}😀 tail`;
    const { nodes } = walkHtml(`<html><body><p>${longText}</p></body></html>`);
    const results = searchNodes(nodes, { needle: "aaa", maxResults: 10 });

    expect(results).toHaveLength(1);
    expect([...results[0].text]).toHaveLength(100);
  });

  it("works directly on CDPNode trees built from local HTML", () => {
    const root = htmlToCdpNodes(
      `<html><body><section aria-label="A"><h2>Title A</h2><p>shared phrase</p></section>
        <section aria-label="B"><h2>Title B</h2><p>shared phrase</p></section></body></html>`
    );
    const { nodes } = walkDOM(root, { truncate: false });
    const results = searchNodes(nodes, { needle: "shared phrase", maxResults: 10 });

    expect(results).toHaveLength(2);
    expect(results[0].context.sectionName).toBe("A");
    expect(results[1].context.sectionName).toBe("B");
    expect(results[0].context.heading).toBe("Title A");
    expect(results[1].context.heading).toBe("Title B");
  });

  it("tells the same phrase apart in header, body, and footer landmarks", () => {
    const html = `
      <html><body>
        <header><a href="/help">Support</a></header>
        <main><h1>Product overview</h1><p>Contact Support for help with billing.</p></main>
        <footer><a href="/contact">Support</a></footer>
      </body></html>`;
    const { nodes } = walkHtml(html);
    const results = searchNodes(nodes, { needle: "support", maxResults: 10 });

    expect(results.length).toBeGreaterThanOrEqual(3);
    const regions = results.map((r) => r.context.sectionTag);
    expect(regions).toContain("header");
    expect(regions).toContain("main");
    expect(regions).toContain("footer");

    // Every clue bundle is unique: no two hits share the full location string.
    const locations = results.map((r) => r.context.location);
    expect(new Set(locations).size).toBe(locations.length);

    // The two links are independently clickable; the body paragraph has no id.
    const linkHits = results.filter((r) => r.elementId);
    expect(new Set(linkHits.map((r) => r.elementId)).size).toBe(linkHits.length);
    const bodyHit = results.find((r) => r.context.sectionTag === "main");
    expect(bodyHit!.elementId).toBeUndefined();
    expect(bodyHit!.context.heading).toBe("Product overview");
  });

  it("resets the nearest heading when entering a new landmark", () => {
    const html = `
      <html><body>
        <main><h2>Main heading</h2><p>main word</p></main>
        <footer><a href="/x">footer word</a></footer>
      </body></html>`;
    const { nodes } = walkHtml(html);
    const results = searchNodes(nodes, { needle: "word", maxResults: 10 });

    const footer = results.find((r) => r.context.sectionTag === "footer");
    expect(footer).toBeDefined();
    expect(footer!.context.heading).toBeUndefined();
    const main = results.find((r) => r.context.sectionTag === "main");
    expect(main!.context.heading).toBe("Main heading");
  });

  it("distinguishes repeated text even inside unnamed containers via the tag path", () => {
    const html = `<html><body><ul><li>repeat</li><li>repeat</li><li>repeat</li></ul></body></html>`;
    const { nodes } = walkHtml(html);
    const results = searchNodes(nodes, { needle: "repeat", maxResults: 10 });

    expect(results).toHaveLength(3);
    expect(results.map((r) => r.index)).toEqual([1, 2, 3]);
    for (const result of results) {
      expect(result.context.path).toContain("item");
      expect(result.context.location).toBeTruthy();
    }
    // Ordinal suffixes make every path unique without relying on index.
    const paths = results.map((r) => r.context.path.join(" > "));
    expect(new Set(paths).size).toBe(3);
    expect(paths.some((p) => p.includes("item[2]"))).toBe(true);
    expect(paths.some((p) => p.includes("item[3]"))).toBe(true);
  });
});

describe("SurfingPage.search over local HTML", () => {
  it("returns hits carrying region clues and usable element ids", async () => {
    const { conn } = mockConnection(REGION_HTML);
    const page = new SurfingPage(conn);
    const state = await page.readPage({ includeHidden: true });

    const results = await page.search("Read more", 10);
    expect(results.length).toBeGreaterThanOrEqual(2);
    for (const result of results) {
      expect(result).toHaveProperty("context");
      expect(typeof result.context.location).toBe("string");
      expect(result.context.elementTag).toBeTruthy();
      if (result.elementId) {
        // Ids returned by search must resolve through the readPage node map.
        expect(state.nodeMap.has(result.elementId)).toBe(true);
      }
    }
    const names = new Set(results.map((r) => r.context.sectionName));
    expect(names.has("News section")).toBe(true);
    expect(names.has("Footer section")).toBe(true);
  });

  it("maps fresh snapshot ids back to the stable ids from readPage", async () => {
    const { conn } = mockConnection(REGION_HTML);
    const page = new SurfingPage(conn);
    await page.readPage({ includeHidden: true });

    const results = await page.search("home", 5);
    expect(results).toHaveLength(1);
    expect(results[0].elementId).toMatch(/^L\d+$/);
    expect(results[0].context.sectionName).toBe("Site navigation");
  });

  it("strictly truncates to maxResults", async () => {
    const { conn } = mockConnection(REGION_HTML);
    const page = new SurfingPage(conn);
    await page.readPage({ includeHidden: true });

    const limited = await page.search("Read more", 2);
    expect(limited).toHaveLength(2);
    expect(limited.map((r) => r.index)).toEqual([1, 2]);
  });

  it("rejects an empty query without capturing a snapshot", async () => {
    const { conn, send } = mockConnection(REGION_HTML);
    const page = new SurfingPage(conn);

    await expect(page.search("   ")).rejects.toBeInstanceOf(ValidationError);
    expect(send).not.toHaveBeenCalled();
  });

  it("rejects non-positive-integer maxResults without capturing a snapshot", async () => {
    const { conn, send } = mockConnection(REGION_HTML);
    const page = new SurfingPage(conn);

    for (const bad of [0, -1, 1.5]) {
      await expect(page.search("read", bad)).rejects.toBeInstanceOf(ValidationError);
    }
    expect(send).not.toHaveBeenCalled();
  });

  it("uses the nearest interactive ancestor id for nested text and leaves bare text empty", async () => {
    const html = `
      <html><body>
        <main>
          <p>Plain quarterly figures without any wrapper id.</p>
          <button type="button"><span><strong>Quarterly deep nested</strong></span></button>
        </main>
      </body></html>`;
    const { conn } = mockConnection(html);
    const page = new SurfingPage(conn);
    const state = await page.readPage({ includeHidden: true });

    const results = await page.search("quarterly", 10);
    expect(results).toHaveLength(2);

    const bare = results.find((r) => r.elementId === undefined);
    const nested = results.find((r) => r.elementId !== undefined);
    expect(bare).toBeDefined();
    expect(nested).toBeDefined();
    // The deeply nested text resolves to its clickable button ancestor.
    expect(nested!.elementId).toMatch(/^B\d+$/);
    expect(state.nodeMap.has(nested!.elementId!)).toBe(true);
  });
});

function findNode(
  nodes: OSNode[],
  predicate: (node: OSNode) => boolean
): OSNode | undefined {
  for (const node of nodes) {
    if (predicate(node)) return node;
    const found = findNode(node.children, predicate);
    if (found) return found;
  }
  return undefined;
}
