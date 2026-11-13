/**
 * Integration tests for `charlotte_batch_collect`.
 *
 * The tool's whole value proposition is failure isolation, so every failure
 * mode here is produced by a *controllable local server* rather than a flaky
 * external site:
 *
 *  - normal pages: the fixture static server (simple.html / form.html / spa.html)
 *  - timeout: a loopback HTTP server whose response hangs longer than the
 *    call's per-page `timeout`, so the outcome is deterministic and fast
 *  - blocked: a second loopback address (127.0.0.2) behind the SSRF filtering
 *    proxy with an allowlist that admits 127.0.0.1 only — the same mechanism
 *    remote-ssrf.test.ts exercises for charlotte_navigate
 *
 * The harness runs with the navigation guard enabled
 * (`navigationGuardAllowlist: ["127.0.0.1/32"]`): ordinary fixture pages and
 * the slow server on 127.0.0.1 load, while anything on 127.0.0.2 is refused
 * before connect and surfaces as `status: "blocked"`.
 */
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import * as path from "node:path";
import * as http from "node:http";
import { setupHttpHarness, type HttpHarness } from "../helpers/http-harness.js";
import { parseToolJson } from "../helpers/mcp-harness.js";
import { BrowserManager } from "../../src/browser/browser-manager.js";
import { resolveTestNoSandbox } from "../helpers/sandbox-env.js";
import { charlotteTools } from "../../src/core/index.js";
import type { BatchCollectResult, BatchPageResult } from "../../src/core/batch-collect.js";

const FIXTURES_DIR = path.resolve(import.meta.dirname, "../fixtures/pages");

interface LocalServer {
  server: http.Server;
  port: number;
}

function startServer(host: string, handler: http.RequestListener): Promise<LocalServer> {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.once("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      if (address && typeof address === "object") resolve({ server, port: address.port });
      else reject(new Error("no listening port"));
    });
  });
}

function stopServer(target: LocalServer | undefined): Promise<void> {
  if (!target) return Promise.resolve();
  return new Promise((resolve) => {
    target.server.closeAllConnections?.();
    target.server.close(() => resolve());
  });
}

describe("charlotte_batch_collect", () => {
  let harness: HttpHarness;
  let slowServer: LocalServer;
  let blockedServer: LocalServer;
  let baseUrl: string;

  beforeAll(async () => {
    // Slow server on the allowlisted loopback: accepts the connection but never
    // responds, so page.goto reliably hits the call's short per-page timeout.
    slowServer = await startServer("127.0.0.1", (_req, res) => {
      // Intentionally no res.end() — the request hangs until teardown.
      res.writeHead(200, { "content-type": "text/html" });
      res.write("<!doctype html><html><body>slow</body></html>");
    });

    // Blocked server on a DIFFERENT loopback address the allowlist rejects.
    // Its handler must never run: the proxy refuses before connect.
    blockedServer = await startServer("127.0.0.2", (_req, res) => {
      res.writeHead(200, { "content-type": "text/html" });
      res.end("<html><body>must never be served</body></html>");
    });

    harness = await setupHttpHarness({
      serveDirectory: FIXTURES_DIR,
      navigationGuardAllowlist: ["127.0.0.1/32"],
    });
    baseUrl = harness.fixtureServer!.url;
  });

  afterAll(async () => {
    await harness?.teardown();
    await stopServer(slowServer);
    await stopServer(blockedServer);
  });

  async function collect(args: Record<string, unknown>): Promise<BatchCollectResult> {
    const result = await harness.callTool("charlotte_batch_collect", args);
    // Even batches containing failed pages are normal (non-error) tool results;
    // only parameter failures set isError.
    expect(
      result.isError,
      result.content[0]?.type === "text" ? result.content[0].text : "",
    ).toBeFalsy();
    return parseToolJson<BatchCollectResult>(result);
  }

  const byUrl = (payload: BatchCollectResult, url: string): BatchPageResult => {
    const entry = payload.results.find((result) => result.url === url);
    if (!entry)
      throw new Error(`no result for ${url}; got ${payload.results.map((r) => r.url).join(", ")}`);
    return entry;
  };

  describe("happy path", () => {
    it("collects several distinct pages and returns an interactive representation per page", async () => {
      const urls = [`${baseUrl}/simple.html`, `${baseUrl}/form.html`, `${baseUrl}/spa.html`];

      const payload = await collect({ urls, detail: "summary" });

      expect(payload.session_id).toBe("default");
      expect(payload.total).toBe(3);
      expect(payload.unique_count).toBe(3);
      expect(payload.success_count).toBe(3);
      expect(payload.failure_count).toBe(0);
      expect(payload.retry_urls).toEqual([]);
      expect(payload.results).toHaveLength(3);
      // First-seen ordering is preserved.
      expect(payload.results.map((result) => result.url)).toEqual(urls);

      for (const url of urls) {
        const entry = byUrl(payload, url);
        expect(entry.status).toBe("ok");
        expect(entry.detail).toBe("summary");
        expect(entry.reason).toBeUndefined();
        expect(entry.duplicate).toBeUndefined();
        // The ok payload carries the same structured page shape observe returns.
        expect(entry.page).toBeDefined();
        expect(entry.page!.url).toBe(url);
        expect(entry.page!.title).toEqual(expect.any(String));
        expect(Array.isArray(entry.page!.structure?.landmarks)).toBe(true);
        expect(Array.isArray(entry.page!.interactive)).toBe(true);
      }

      // The representation is genuinely interactive: an element ID from the
      // batch payload resolves through the normal find/click machinery.
      const simpleEntry = byUrl(payload, `${baseUrl}/simple.html`);
      const interactive = simpleEntry.page!.interactive as Array<{ id: string }>;
      expect(interactive.length).toBeGreaterThan(0);
      expect(interactive[0].id).toEqual(expect.any(String));

      // The active tab was left on the final successfully loaded page.
      expect(harness.pageManager.getActivePage().url()).toBe(`${baseUrl}/spa.html`);
    });

    it("honors detail minimal and full", async () => {
      // Sequential, not concurrent: every batch drives the shared active tab,
      // so parallel batches would abort each other's navigations.
      const minimal = await collect({ urls: [`${baseUrl}/simple.html`], detail: "minimal" });
      const full = await collect({ urls: [`${baseUrl}/simple.html`], detail: "full" });

      const minimalEntry = minimal.results[0];
      expect(minimalEntry.status).toBe("ok");
      expect(minimalEntry.detail).toBe("minimal");
      // minimal renders an interactive_summary instead of the full element list.
      expect(minimalEntry.page!.interactive_summary).toBeDefined();
      expect(minimalEntry.page!.interactive).toBeUndefined();

      const fullEntry = full.results[0];
      expect(fullEntry.detail).toBe("full");
      expect(fullEntry.page!.structure?.full_content).toBeDefined();
    });

    it("defaults detail to summary", async () => {
      const payload = await collect({ urls: [`${baseUrl}/simple.html`] });
      expect(payload.results[0].detail).toBe("summary");
      expect(payload.results[0].page!.interactive).toBeDefined();
    });
  });

  describe("failure isolation", () => {
    it("marks a timed-out page 'timeout' and still collects every later URL", async () => {
      const slowUrl = `http://127.0.0.1:${slowServer.port}/hung`;
      const urls = [`${baseUrl}/simple.html`, slowUrl, `${baseUrl}/form.html`];

      const payload = await collect({ urls, detail: "minimal", timeout: 1500 });

      expect(payload.total).toBe(3);
      expect(payload.unique_count).toBe(3);
      expect(payload.success_count).toBe(2);
      expect(payload.failure_count).toBe(1);

      const slowEntry = byUrl(payload, slowUrl);
      expect(slowEntry.status).toBe("timeout");
      expect(slowEntry.page).toBeUndefined();
      expect(slowEntry.reason).toContain("timed out after 1500ms");

      // Pages after the failure were still collected with their own outcomes.
      expect(byUrl(payload, `${baseUrl}/simple.html`).status).toBe("ok");
      const afterFailure = byUrl(payload, `${baseUrl}/form.html`);
      expect(afterFailure.status).toBe("ok");
      expect(afterFailure.page?.url).toBe(`${baseUrl}/form.html`);

      // Only the failed URL is offered for retry.
      expect(payload.retry_urls).toEqual([slowUrl]);
    });

    it("marks a navigation-guard refusal 'blocked' and continues the batch", async () => {
      const blockedUrl = `http://127.0.0.2:${blockedServer.port}/private`;
      const urls = [blockedUrl, `${baseUrl}/simple.html`, `${baseUrl}/spa.html`];

      const payload = await collect({ urls, timeout: 5000 });

      expect(payload.success_count).toBe(2);
      expect(payload.failure_count).toBe(1);

      const blockedEntry = byUrl(payload, blockedUrl);
      expect(blockedEntry.status).toBe("blocked");
      expect(blockedEntry.page).toBeUndefined();
      expect(blockedEntry.reason).toContain("SSRF guard");

      // The blocked page did not abort collection of the remaining URLs.
      expect(byUrl(payload, `${baseUrl}/simple.html`).status).toBe("ok");
      expect(byUrl(payload, `${baseUrl}/spa.html`).status).toBe("ok");
      expect(payload.retry_urls).toEqual([blockedUrl]);
    });

    it("survives multiple consecutive failures without dropping later pages", async () => {
      const slowUrl = `http://127.0.0.1:${slowServer.port}/hung-again`;
      const blockedUrl = `http://127.0.0.2:${blockedServer.port}/private-2`;
      const urls = [slowUrl, blockedUrl, `${baseUrl}/simple.html`];

      const payload = await collect({ urls, detail: "minimal", timeout: 1500 });

      expect(payload.results.map((result) => result.status)).toEqual(["timeout", "blocked", "ok"]);
      expect(payload.success_count).toBe(1);
      expect(payload.failure_count).toBe(2);
      expect(payload.retry_urls).toEqual([slowUrl, blockedUrl]);
    });
  });

  describe("duplicate URL dedup", () => {
    it("fetches a repeated URL once, marks it duplicate, and counts occurrences", async () => {
      const target = `${baseUrl}/simple.html`;
      const payload = await collect({
        urls: [target, `${baseUrl}/form.html`, target, target],
        detail: "minimal",
      });

      expect(payload.total).toBe(4);
      expect(payload.unique_count).toBe(2);
      expect(payload.results).toHaveLength(2);
      expect(payload.results.map((result) => result.url)).toEqual([target, `${baseUrl}/form.html`]);

      const repeated = byUrl(payload, target);
      expect(repeated.duplicate).toBe(true);
      expect(repeated.occurrences).toBe(3);
      expect(repeated.status).toBe("ok");

      const once = byUrl(payload, `${baseUrl}/form.html`);
      expect(once.duplicate).toBeUndefined();
      expect(once.occurrences).toBeUndefined();

      expect(payload.success_count).toBe(2);
      expect(payload.failure_count).toBe(0);
      expect(payload.retry_urls).toEqual([]);
    });

    it("marks a repeated failing URL once and lists it a single time in retry_urls", async () => {
      const slowUrl = `http://127.0.0.1:${slowServer.port}/hung-dup`;
      const payload = await collect({
        urls: [slowUrl, slowUrl, `${baseUrl}/simple.html`],
        detail: "minimal",
        timeout: 1500,
      });

      expect(payload.total).toBe(3);
      expect(payload.unique_count).toBe(2);
      const slowEntry = byUrl(payload, slowUrl);
      expect(slowEntry.status).toBe("timeout");
      expect(slowEntry.duplicate).toBe(true);
      expect(slowEntry.occurrences).toBe(2);
      expect(payload.retry_urls).toEqual([slowUrl]);
    });
  });

  describe("parameter validation", () => {
    it("rejects an empty urls array as INVALID_ARGUMENT before any browser launch", async () => {
      // A fresh, un-launched browser: the handler must fail validation before
      // ensureReady(), so no Chromium process is ever started.
      const browserManager = new BrowserManager(undefined, { noSandbox: resolveTestNoSandbox() });
      try {
        expect(browserManager.isConnected()).toBe(false);

        const definition = charlotteTools.find((tool) => tool.name === "charlotte_batch_collect");
        expect(definition).toBeDefined();
        const result = await definition!.handler(
          { browserManager } as never,
          { urls: [] } as never,
        );

        expect(result.isError).toBe(true);
        const text = (result.content as Array<{ text: string }>)[0].text;
        const payload = JSON.parse(text) as {
          session_id: string;
          error: { code: string; message: string };
        };
        expect(payload.session_id).toBe("default");
        expect(payload.error.code).toBe("INVALID_ARGUMENT");
        expect(payload.error.message).toContain("urls");
        expect(browserManager.isConnected()).toBe(false);
      } finally {
        await browserManager.close().catch(() => {});
      }
    });

    it("rejects an invalid detail level at the handler before ensureReady", async () => {
      const browserManager = new BrowserManager(undefined, { noSandbox: resolveTestNoSandbox() });
      try {
        const definition = charlotteTools.find((tool) => tool.name === "charlotte_batch_collect");
        const result = await definition!.handler(
          { browserManager } as never,
          { urls: ["https://example.test/"], detail: "verbose" } as never,
        );

        expect(result.isError).toBe(true);
        const payload = parseToolJson<{ error: { code: string } }>(result);
        expect(payload.error.code).toBe("INVALID_ARGUMENT");
        expect(browserManager.isConnected()).toBe(false);
      } finally {
        await browserManager.close().catch(() => {});
      }
    });

    it("rejects an empty urls array over MCP at the schema layer", async () => {
      // The zod schema (.min(1)) rejects this before the handler runs, so no
      // navigation occurs — the MCP SDK surfaces the validation failure as a
      // tool error. The handler-level INVALID_ARGUMENT guarantee (including the
      // "never launch a browser" case) is covered by the direct test above.
      const result = await harness.callTool("charlotte_batch_collect", { urls: [] });
      expect(result.isError).toBe(true);
      const text = (result.content as Array<{ text: string }>)[0].text;
      expect(text).toMatch(/validation|invalid/i);
    });

    it("rejects an invalid detail level over MCP without collecting anything", async () => {
      const result = await harness.callTool("charlotte_batch_collect", {
        urls: [`${baseUrl}/simple.html`],
        detail: "verbose",
      });
      expect(result.isError).toBe(true);
      const text = (result.content as Array<{ text: string }>)[0].text;
      expect(text).toMatch(/validation|invalid/i);
    });

    it("rejects more than 50 URLs at the schema layer", async () => {
      const urls = Array.from({ length: 51 }, (_, index) => `${baseUrl}/p-${index}.html`);
      const result = await harness.callTool("charlotte_batch_collect", { urls });
      expect(result.isError).toBe(true);
      const text = (result.content as Array<{ text: string }>)[0].text;
      expect(text).toMatch(/validation|invalid/i);
    });
  });
});
