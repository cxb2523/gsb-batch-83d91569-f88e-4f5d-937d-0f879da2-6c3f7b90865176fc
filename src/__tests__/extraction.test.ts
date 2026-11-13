import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { loadConfig } from "../config.js";
import { AppError, type ToolResult } from "../errors.js";
import { getTrackedTab, removeTrackedTab, trackTab } from "../state.js";
import type { ToolDeps } from "../server.js";
import { registerExtractionTools } from "../tools/extraction.js";
import type { TabInfo } from "../types.js";

function makeTab(tabId: string, overrides: Partial<TabInfo> = {}): TabInfo {
  return {
    tabId,
    url: "http://example.com",
    createdAt: "2026-02-16T00:00:00.000Z",
    lastActivity: 0,
    userId: "user-1",
    sessionKey: "session-1",
    visitedUrls: [],
    toolCalls: 0,
    refsCount: 0,
    ...overrides
  };
}

function parseToolTextJson(result: ToolResult): any {
  const first = result.content[0];
  if (!first || first.type !== "text") {
    throw new Error("Expected first content entry to be text");
  }
  return JSON.parse(first.text);
}

function makeServerCapture(): {
  server: { tool: ReturnType<typeof vi.fn> };
  getHandler: (name: string) => (input: unknown) => Promise<ToolResult>;
} {
  const server = {
    tool: vi.fn()
  };

  const getHandler = (name: string) => {
    const call = server.tool.mock.calls.find((c) => c[0] === name);
    if (!call) {
      throw new Error(`Expected tool '${name}' to be registered`);
    }
    return call[3] as (input: unknown) => Promise<ToolResult>;
  };

  return { server, getHandler };
}

describe("tools/extraction", () => {
  let deps: ToolDeps;
  const createdTabIds: string[] = [];

  beforeEach(() => {
    deps = {
      client: {
        extractResources: vi.fn(),
        extractStructured: vi.fn(),
        batchDownload: vi.fn(),
        downloadResource: vi.fn(),
        resolveBlobs: vi.fn()
      } as unknown as ToolDeps["client"],
      config: loadConfig([], { CAMOFOX_URL: "http://test:9377" } as NodeJS.ProcessEnv)
    };
  });

  afterEach(() => {
    for (const tabId of createdTabIds.splice(0, createdTabIds.length)) {
      removeTrackedTab(tabId);
    }
    vi.restoreAllMocks();
  });

  describe("extract_resources", () => {
    it("calls client.extractResources with tabId and params (forwards filters)", async () => {
      const tabId = "tab-extract";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId, { userId: "user-1" }));

      const response = { resources: [{ type: "images", url: "http://x" }], count: 1 };
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce(response as any);

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_resources");

      const result = await handler({
        tabId,
        selector: ".post",
        types: ["images", "links"],
        extensions: ["jpg", "png"],
        resolveBlobs: true,
        triggerLazyLoad: true,
        maxDepth: 3
      });

      expect(result.isError).toBeFalsy();
      expect(parseToolTextJson(result)).toEqual(response);
      expect(deps.client.extractResources).toHaveBeenCalledWith(tabId, {
        userId: "user-1",
        selector: ".post",
        ref: undefined,
        types: ["images", "links"],
        extensions: ["jpg", "png"],
        resolveBlobs: true,
        triggerLazyLoad: true,
        maxDepth: 3
      });
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("requires tabId (should error without tracked tab)", async () => {
      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_resources");

      const result = await handler({ tabId: "missing", selector: ".x" });
      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "TAB_NOT_FOUND" });
      expect(deps.client.extractResources).not.toHaveBeenCalled();
    });

    it("increments tool call counter on tracked tab", async () => {
      const tabId = "tab-extract-toolcalls";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({ ok: true } as any);

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_resources");

      await handler({ tabId, selector: ".x" });
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("client error -> returns error result", async () => {
      const tabId = "tab-extract-error";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));
      vi.mocked(deps.client.extractResources).mockRejectedValueOnce(new Error("extract failed"));

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_resources");

      const result = await handler({ tabId, selector: ".x" });
      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "INTERNAL_ERROR", message: "extract failed" });
      expect(getTrackedTab(tabId).toolCalls).toBe(0);
    });
  });

  describe("extract_structured", () => {
    it("calls client.extractStructured with schema and tracked user", async () => {
      const tabId = "tab-structured";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId, { userId: "user-structured" }));

      const schema = {
        kind: "object",
        selector: "#catalog",
        fields: {
          heading: { kind: "text", selector: "h1", required: true, trim: true }
        }
      };
      const response = { ok: true, data: { heading: "Catalog" }, metadata: { matchedRoots: 1 } };
      vi.mocked(deps.client.extractStructured).mockResolvedValueOnce(response as any);

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_structured");

      const result = await handler({ tabId, schema });

      expect(result.isError).toBeFalsy();
      expect(parseToolTextJson(result)).toEqual(response);
      expect(deps.client.extractStructured).toHaveBeenCalledWith(tabId, {
        userId: "user-structured",
        schema
      });
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("allows userId override for extract_structured", async () => {
      const tabId = "tab-structured-override";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId, { userId: "tracked-user" }));
      vi.mocked(deps.client.extractStructured).mockResolvedValueOnce({ ok: true, data: {} } as any);

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("extract_structured");

      await handler({ tabId, userId: "override-user", schema: { kind: "object", fields: {} } });

      expect(deps.client.extractStructured).toHaveBeenCalledWith(tabId, {
        userId: "override-user",
        schema: { kind: "object", fields: {} }
      });
    });
  });

  describe("batch_download", () => {
    function setupHandler() {
      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      return getHandler("batch_download");
    }

    it("downloads every extracted resource and reports per-item success", async () => {
      const tabId = "tab-batch-all-success";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId, { userId: "user-1" }));

      const urls = ["http://x/1.jpg", "http://x/2.jpg", "http://x/3.jpg"];
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({
        resources: urls.map((url) => ({ type: "images", url })),
        count: urls.length
      } as any);
      vi.mocked(deps.client.downloadResource).mockImplementation(async (_tabId, params: any) => ({
        downloadId: `dl-${params.url}`
      }));

      const handler = setupHandler();
      const result = await handler({
        tabId,
        selector: ".container",
        types: ["images"],
        extensions: ["jpg"],
        resolveBlobs: false,
        concurrency: 2,
        maxFiles: 7
      });

      expect(result.isError).toBeFalsy();
      const payload = parseToolTextJson(result);
      expect(payload.total).toBe(3);
      expect(payload.succeeded).toBe(3);
      expect(payload.failed).toBe(0);
      expect(payload.truncated).toBe(false);
      expect(payload.skipped).toBe(0);
      expect(payload.items).toHaveLength(3);
      expect(payload.items.map((item: any) => item.url)).toEqual(urls);
      for (const item of payload.items) {
        expect(item.status).toBe("success");
        expect(item.error).toBeUndefined();
      }
      // counts must agree with items
      expect(payload.succeeded + payload.failed).toBe(payload.items.length);
      expect(payload.total).toBe(payload.items.length);

      // filters are forwarded to extraction unchanged
      expect(deps.client.extractResources).toHaveBeenCalledWith(tabId, {
        userId: "user-1",
        selector: ".container",
        ref: undefined,
        types: ["images"],
        extensions: ["jpg"],
        resolveBlobs: false
      });
      expect(deps.client.downloadResource).toHaveBeenCalledTimes(3);
      for (const url of urls) {
        expect(deps.client.downloadResource).toHaveBeenCalledWith(tabId, { userId: "user-1", url });
      }
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("continues after a mid-batch failure and reports the failed item without failing the call", async () => {
      const tabId = "tab-batch-partial";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      const urls = ["http://x/a.png", "http://x/broken.png", "http://x/c.png"];
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({
        resources: urls.map((url) => ({ url }))
      } as any);
      vi.mocked(deps.client.downloadResource).mockImplementation(async (_tabId, params: any) => {
        if (params.url === "http://x/broken.png") {
          throw new Error("HTTP 404: not found");
        }
        return { downloadId: "ok" };
      });

      const handler = setupHandler();
      const result = await handler({ tabId, selector: ".container" });

      expect(result.isError).toBeFalsy();
      const payload = parseToolTextJson(result);
      expect(payload.total).toBe(3);
      expect(payload.succeeded).toBe(2);
      expect(payload.failed).toBe(1);
      expect(payload.items).toHaveLength(3);
      expect(payload.items[0]).toMatchObject({ url: urls[0], status: "success" });
      expect(payload.items[1]).toMatchObject({ url: urls[1], status: "failed" });
      expect(payload.items[1].error).toContain("404");
      // the item after the failure still downloaded
      expect(payload.items[2]).toMatchObject({ url: urls[2], status: "success" });
      expect(deps.client.downloadResource).toHaveBeenCalledTimes(3);
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("truncates to maxFiles and reports skipped resources", async () => {
      const tabId = "tab-batch-truncated";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      const urls = ["http://x/1.jpg", "http://x/2.jpg", "http://x/3.jpg", "http://x/4.jpg", "http://x/5.jpg"];
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({
        resources: urls.map((url) => ({ url }))
      } as any);
      vi.mocked(deps.client.downloadResource).mockResolvedValue({ downloadId: "ok" } as any);

      const handler = setupHandler();
      const result = await handler({ tabId, selector: ".container", maxFiles: 2 });

      expect(result.isError).toBeFalsy();
      const payload = parseToolTextJson(result);
      expect(payload.total).toBe(2);
      expect(payload.succeeded).toBe(2);
      expect(payload.failed).toBe(0);
      expect(payload.truncated).toBe(true);
      expect(payload.skipped).toBe(3);
      expect(payload.items).toHaveLength(2);
      expect(payload.items.map((item: any) => item.url)).toEqual(urls.slice(0, 2));
      expect(deps.client.downloadResource).toHaveBeenCalledTimes(2);
      expect(deps.client.downloadResource).toHaveBeenCalledWith(tabId, { userId: "user-1", url: urls[0] });
      expect(deps.client.downloadResource).toHaveBeenCalledWith(tabId, { userId: "user-1", url: urls[1] });
    });

    it("does not flag truncation when resources fit within maxFiles", async () => {
      const tabId = "tab-batch-not-truncated";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({
        resources: [{ url: "http://x/only.jpg" }]
      } as any);
      vi.mocked(deps.client.downloadResource).mockResolvedValue({ downloadId: "ok" } as any);

      const handler = setupHandler();
      const result = await handler({ tabId, selector: ".container", maxFiles: 50 });

      const payload = parseToolTextJson(result);
      expect(payload.truncated).toBe(false);
      expect(payload.skipped).toBe(0);
      expect(payload.total).toBe(1);
    });

    it("never exceeds the concurrency limit for in-flight downloads", async () => {
      const tabId = "tab-batch-concurrency";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      const urls = Array.from({ length: 6 }, (_, i) => `http://x/${i}.jpg`);
      vi.mocked(deps.client.extractResources).mockResolvedValueOnce({
        resources: urls.map((url) => ({ url }))
      } as any);

      let inFlight = 0;
      let maxInFlight = 0;
      vi.mocked(deps.client.downloadResource).mockImplementation(async () => {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        await new Promise((resolve) => setTimeout(resolve, 10));
        inFlight -= 1;
        return { downloadId: "ok" };
      });

      const handler = setupHandler();
      const result = await handler({ tabId, selector: ".container", concurrency: 2 });

      expect(result.isError).toBeFalsy();
      expect(deps.client.downloadResource).toHaveBeenCalledTimes(6);
      expect(maxInFlight).toBeGreaterThan(1);
      expect(maxInFlight).toBeLessThanOrEqual(2);
    });

    it("requires tabId (untracked tab errors before any download)", async () => {
      const handler = setupHandler();

      const result = await handler({ tabId: "missing", selector: ".x" });
      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "TAB_NOT_FOUND" });
      expect(deps.client.extractResources).not.toHaveBeenCalled();
      expect(deps.client.downloadResource).not.toHaveBeenCalled();
    });

    it("requires selector or ref", async () => {
      const tabId = "tab-batch-validation";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      const handler = setupHandler();
      const result = await handler({ tabId });

      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "VALIDATION_ERROR" });
      expect(deps.client.extractResources).not.toHaveBeenCalled();
      expect(deps.client.downloadResource).not.toHaveBeenCalled();
    });

    it("returns an error result when the browser service is unreachable during extraction", async () => {
      const tabId = "tab-batch-unreachable";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      vi.mocked(deps.client.extractResources).mockRejectedValueOnce(
        new AppError("CONNECTION_REFUSED", "Failed to connect to CamoFox API")
      );

      const handler = setupHandler();
      const result = await handler({ tabId, selector: ".x" });

      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "CONNECTION_REFUSED" });
      expect(deps.client.downloadResource).not.toHaveBeenCalled();
      expect(getTrackedTab(tabId).toolCalls).toBe(0);
    });
  });

  describe("resolve_blobs", () => {
    it("calls client.resolveBlobs with tabId and urls", async () => {
      const tabId = "tab-resolve";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId, { userId: "user-1" }));

      const response = { resolved: [{ url: "blob:1", dataUri: "data:text/plain;base64,WA==" }] };
      vi.mocked(deps.client.resolveBlobs).mockResolvedValueOnce(response as any);

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("resolve_blobs");

      const result = await handler({ tabId, urls: ["blob:1"] });
      expect(result.isError).toBeFalsy();
      expect(parseToolTextJson(result)).toEqual(response);
      expect(deps.client.resolveBlobs).toHaveBeenCalledWith(tabId, "user-1", ["blob:1"]);
      expect(getTrackedTab(tabId).toolCalls).toBe(1);
    });

    it("requires tabId and at least one URL", async () => {
      const tabId = "tab-resolve-validate";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("resolve_blobs");

      const result = await handler({ tabId, urls: [] });
      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "VALIDATION_ERROR" });
      expect(deps.client.resolveBlobs).not.toHaveBeenCalled();
      expect(getTrackedTab(tabId).toolCalls).toBe(0);
    });

    it("client error -> error result", async () => {
      const tabId = "tab-resolve-error";
      createdTabIds.push(tabId);
      trackTab(makeTab(tabId));
      vi.mocked(deps.client.resolveBlobs).mockRejectedValueOnce(new Error("resolve failed"));

      const { server, getHandler } = makeServerCapture();
      registerExtractionTools(server as unknown as Parameters<typeof registerExtractionTools>[0], deps);
      const handler = getHandler("resolve_blobs");

      const result = await handler({ tabId, urls: ["blob:1"] });
      expect(result.isError).toBe(true);
      const payload = parseToolTextJson(result);
      expect(payload).toMatchObject({ isError: true, code: "INTERNAL_ERROR", message: "resolve failed" });
      expect(getTrackedTab(tabId).toolCalls).toBe(0);
    });
  });
});
