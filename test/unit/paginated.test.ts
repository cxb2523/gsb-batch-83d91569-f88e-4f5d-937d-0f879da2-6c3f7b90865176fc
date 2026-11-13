import assert from "node:assert/strict";
import { createServer, type IncomingMessage, type ServerResponse, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { test } from "node:test";

import { scrapePaginated } from "../../src/index";

// ---------------------------------------------------------------------------
// Offline fixture: a local HTTP server, never the network. Every test pins
// strategy: "http" so no Chrome is launched; the http tier uses Node's fetch
// against 127.0.0.1 only.
// ---------------------------------------------------------------------------

type Handler = (req: IncomingMessage, res: ServerResponse) => void;

async function startTestServer(handler: Handler): Promise<{ origin: string; close: () => Promise<void> }> {
  const server: Server = createServer(handler);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  return {
    origin: `http://127.0.0.1:${port}`,
    close: () => new Promise((resolve) => server.close(() => resolve())),
  };
}

function sendHtml(res: ServerResponse, body: string, status = 200): void {
  res.writeHead(status, { "content-type": "text/html; charset=utf-8" });
  res.end(body);
}

// Long enough to clear detectBlock()'s 200-char "almost no content" floor.
function filler(page: number): string {
  const sentence = `List page ${page} carries a long enough paragraph of ordinary list content to pass the short-page heuristic used by the block detector, so the page is trusted as real content rather than treated as an anti-bot interstitial. `;
  return sentence.repeat(3);
}

function listPage(page: number, nextHref?: string): string {
  return `<!doctype html><html lang="en"><head><title>List page ${page}</title></head>
<body>
<main>
  <h1>List page ${page}</h1>
  <p>${filler(page)}</p>
  <ul><li>Item ${page}.1</li><li>Item ${page}.2</li><li>Item ${page}.3</li></ul>
  ${nextHref ? `<nav><a class="next-page" href="${nextHref}">Next page</a></nav>` : ""}
</main>
</body></html>`;
}

// ---------------------------------------------------------------------------
// Selector mode: three pages linked via a.next-page, the last one without a
// next link.
// ---------------------------------------------------------------------------

test("scrapePaginated follows next-link selectors in order and keeps markdown + attempts per page", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/page/1") return sendHtml(res, listPage(1, "/page/2"));
    if (path === "/page/2") return sendHtml(res, listPage(2, "/page/3"));
    if (path === "/page/3") return sendHtml(res, listPage(3));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/page/1`,
      nextLinkSelector: "a.next-page",
      strategy: "http",
    });

    assert.equal(result.pages.length, 3);
    assert.deepEqual(
      result.pages.map((p) => p.page),
      [1, 2, 3],
    );
    assert.deepEqual(
      result.pages.map((p) => p.url),
      [`${server.origin}/page/1`, `${server.origin}/page/2`, `${server.origin}/page/3`],
    );

    for (const page of result.pages) {
      assert.equal(page.ok, true);
      assert.equal(page.actualUrl, page.url);
      assert.equal(page.tier, "http");
      assert.equal(page.title, `List page ${page.page}`);
      assert.match(page.markdown ?? "", new RegExp(`# List page ${page.page}`));
      assert.match(page.markdown ?? "", /Item \d+\.\d+/);
      // html is fetched internally for the selector but stripped by default.
      assert.equal(page.html, undefined);
      assert.equal(page.blocked, null);
      assert.ok(Array.isArray(page.attempts) && page.attempts.length === 1);
      assert.equal(page.attempts?.[0].tier, "http");
      assert.equal(page.attempts?.[0].ok, true);
      assert.equal(page.reason, undefined);
    }

    assert.equal(result.stoppedReason, "no next page");
  } finally {
    await server.close();
  }
});

test("scrapePaginated stops on the first page whose selector matches nothing", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/only") return sendHtml(res, listPage(1));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/only`,
      nextLinkSelector: "a.next-page",
      strategy: "http",
    });
    assert.equal(result.pages.length, 1);
    assert.equal(result.pages[0].ok, true);
    assert.equal(result.stoppedReason, "no next page");
  } finally {
    await server.close();
  }
});

// ---------------------------------------------------------------------------
// Selector mode: next link points back at an already scraped URL.
// ---------------------------------------------------------------------------

test("scrapePaginated stops with 'duplicate page' when the next link is already scraped", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    // The next link on page 1 points at page 1 itself.
    if (path === "/self") return sendHtml(res, listPage(1, "/self"));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/self`,
      nextLinkSelector: "a.next-page",
      strategy: "http",
    });
    assert.equal(result.pages.length, 1);
    assert.equal(result.pages[0].ok, true);
    assert.equal(result.stoppedReason, `duplicate page (${server.origin}/self)`);
  } finally {
    await server.close();
  }
});

test("scrapePaginated treats a fragment-only next link as a duplicate", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/frag") return sendHtml(res, listPage(1, "/frag#bottom"));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/frag`,
      nextLinkSelector: "a.next-page",
      strategy: "http",
    });
    assert.equal(result.pages.length, 1);
    assert.match(result.stoppedReason, /^duplicate page /);
  } finally {
    await server.close();
  }
});

// ---------------------------------------------------------------------------
// Template mode: URLs generated from {page}, bounded by maxPages.
// ---------------------------------------------------------------------------

test("scrapePaginated template mode generates page URLs and stops at maxPages", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    const match = path.match(/^\/t\/(\d+)$/);
    if (match) return sendHtml(res, listPage(Number(match[1])));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/t/1`,
      urlTemplate: `${server.origin}/t/{page}`,
      maxPages: 3,
      strategy: "http",
    });

    assert.equal(result.pages.length, 3);
    assert.deepEqual(
      result.pages.map((p) => p.page),
      [1, 2, 3],
    );
    assert.deepEqual(
      result.pages.map((p) => p.url),
      [`${server.origin}/t/1`, `${server.origin}/t/2`, `${server.origin}/t/3`],
    );
    assert.ok(result.pages.every((p) => p.ok && p.tier === "http"));
    assert.equal(result.stoppedReason, "reached max pages (3)");
  } finally {
    await server.close();
  }
});

test("scrapePaginated applies the default maxPages cap", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    const match = path.match(/^\/endless\/(\d+)$/);
    if (match) return sendHtml(res, listPage(Number(match[1])));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/endless/1`,
      urlTemplate: `${server.origin}/endless/{page}`,
      strategy: "http",
    });
    assert.equal(result.pages.length, 20);
    assert.equal(result.pages[19].page, 20);
    assert.equal(result.stoppedReason, "reached max pages (20)");
  } finally {
    await server.close();
  }
});

test("scrapePaginated template mode requires a {page} placeholder", async () => {
  const server = await startTestServer((_req, res) => {
    res.writeHead(404);
    res.end("not found");
  });

  try {
    await assert.rejects(
      scrapePaginated({ url: `${server.origin}/x`, urlTemplate: `${server.origin}/static`, strategy: "http" }),
      /\{page\}/,
    );
  } finally {
    await server.close();
  }
});

// ---------------------------------------------------------------------------
// Mid-batch failure: page 2 answers 403. The batch must not throw; page 2 is
// recorded with ok:false + reason and the pages collected before it survive.
// ---------------------------------------------------------------------------

test("scrapePaginated keeps collected pages and records reason when a mid-batch page returns 403", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/p/1") return sendHtml(res, listPage(1, "/p/2"));
    if (path === "/p/2") return sendHtml(res, "<!doctype html><html><body>forbidden</body></html>", 403);
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/p/1`,
      nextLinkSelector: "a.next-page",
      maxPages: 5,
      strategy: "http",
    });

    assert.equal(result.pages.length, 2);
    const [first, second] = result.pages;

    assert.equal(first.page, 1);
    assert.equal(first.ok, true);
    assert.match(first.markdown ?? "", /# List page 1/);

    assert.equal(second.page, 2);
    assert.equal(second.url, `${server.origin}/p/2`);
    assert.equal(second.ok, false);
    assert.equal(second.actualUrl, undefined);
    assert.match(second.reason ?? "", /HTTP 403/);
    assert.ok(Array.isArray(second.attempts));
    assert.equal(second.attempts?.[0].tier, "http");
    assert.equal(second.attempts?.[0].ok, false);
    assert.match(second.attempts?.[0].reason ?? "", /HTTP 403/);

    assert.equal(result.stoppedReason, `page 2 failed: ${second.reason}`);
  } finally {
    await server.close();
  }
});

test("scrapePaginated template mode also ends on the first failed page", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/b/1") return sendHtml(res, listPage(1));
    if (path === "/b/2") {
      res.writeHead(503, { "content-type": "text/plain" });
      res.end("boom");
      return;
    }
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/b/1`,
      urlTemplate: `${server.origin}/b/{page}`,
      maxPages: 4,
      strategy: "http",
    });
    assert.equal(result.pages.length, 2);
    assert.equal(result.pages[0].ok, true);
    assert.equal(result.pages[1].ok, false);
    assert.match(result.pages[1].reason ?? "", /HTTP 503/);
    assert.match(result.stoppedReason, /^page 2 failed: /);
  } finally {
    await server.close();
  }
});

// ---------------------------------------------------------------------------
// Format passthrough: asking for html returns it; markdown is then omitted.
// ---------------------------------------------------------------------------

test("scrapePaginated honors per-page formats", async () => {
  const server = await startTestServer((req, res) => {
    const path = new URL(req.url ?? "/", "http://x").pathname;
    if (path === "/f/1") return sendHtml(res, listPage(1, "/f/2"));
    if (path === "/f/2") return sendHtml(res, listPage(2));
    res.writeHead(404);
    res.end("not found");
  });

  try {
    const result = await scrapePaginated({
      url: `${server.origin}/f/1`,
      nextLinkSelector: "a.next-page",
      formats: ["html"],
      strategy: "http",
    });
    assert.equal(result.pages.length, 2);
    for (const page of result.pages) {
      assert.equal(page.ok, true);
      assert.match(page.html ?? "", /<!doctype html>/);
      assert.equal(page.markdown, undefined);
    }
    assert.equal(result.stoppedReason, "no next page");
  } finally {
    await server.close();
  }
});
