import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { normalizeError, okResult, toErrorResult } from "../errors.js";
import { getTrackedTab, incrementToolCall } from "../state.js";
import type { ToolDeps } from "../server.js";

const structuredExtractionSchema = z
  .record(z.string(), z.unknown())
  .describe("Structured extraction schema understood by camofox-browser");

interface BatchDownloadItem {
  url: string;
  status: "success" | "failed";
  error?: string;
  download?: unknown;
}

function extractResourceUrls(extraction: unknown): string[] {
  const resources: unknown[] = Array.isArray(extraction)
    ? extraction
    : extraction && typeof extraction === "object" && Array.isArray((extraction as { resources?: unknown }).resources)
      ? ((extraction as { resources: unknown[] }).resources)
      : [];

  const urls: string[] = [];
  for (const resource of resources) {
    if (typeof resource === "string" && resource.length > 0) {
      urls.push(resource);
    } else if (resource && typeof resource === "object") {
      const url = (resource as { url?: unknown }).url;
      if (typeof url === "string" && url.length > 0) {
        urls.push(url);
      }
    }
  }
  return urls;
}

async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T, index: number) => Promise<void>
): Promise<void> {
  let nextIndex = 0;
  const lanes = Array.from({ length: Math.max(1, Math.min(limit, items.length)) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      await worker(items[index], index);
    }
  });
  await Promise.all(lanes);
}

export function registerExtractionTools(server: McpServer, deps: ToolDeps): void {
  server.tool(
    "extract_resources",
    "Extract resources (images, links, media, documents) from a specific DOM container. Use a CSS selector or element ref from snapshot to scope extraction to a particular section of the page. This is useful for extracting all images from a specific post, all links from a table, etc.",
    {
      tabId: z.string().min(1).describe("Tab ID from create_tab"),
      userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
      selector: z.string().min(1).optional().describe("CSS selector for target container (e.g., '.message:nth-child(3)')"),
      ref: z.string().min(1).optional().describe("Element ref from snapshot (e.g., 'e12'). Either selector or ref required."),
      types: z
        .array(z.enum(['images', 'links', 'media', 'documents', 'image', 'link', 'document']))
        .optional()
        .describe(
          "Resource types to extract: 'images', 'links', 'media', 'documents' (singular forms also accepted). Default: all."
        ),
      extensions: z.array(z.string().min(1)).optional().describe("Filter by file extensions: ['pdf', 'jpg', 'png']"),
      resolveBlobs: z.boolean().optional().default(false).describe("Resolve blob: URLs to data: URIs"),
      triggerLazyLoad: z.boolean().optional().default(false).describe("Scroll to trigger lazy-loaded images before extraction"),
      maxDepth: z.number().int().positive().optional().default(5).describe("Max nesting depth for container traversal")
    },
    async (input: unknown) => {
      try {
        const parsed = z
          .object({
            tabId: z.string().min(1).describe("Tab ID from create_tab"),
            userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
            selector: z.string().min(1).optional().describe("CSS selector for target container (e.g., '.message:nth-child(3)')"),
            ref: z.string().min(1).optional().describe("Element ref from snapshot (e.g., 'e12'). Either selector or ref required."),
            types: z
              .array(z.enum(['images', 'links', 'media', 'documents', 'image', 'link', 'document']))
              .optional()
              .describe(
                "Resource types to extract: 'images', 'links', 'media', 'documents' (singular forms also accepted). Default: all."
              ),
            extensions: z.array(z.string().min(1)).optional().describe("Filter by file extensions: ['pdf', 'jpg', 'png']"),
            resolveBlobs: z.boolean().optional().default(false).describe("Resolve blob: URLs to data: URIs"),
            triggerLazyLoad: z.boolean().optional().default(false).describe("Scroll to trigger lazy-loaded images before extraction"),
            maxDepth: z.number().int().positive().optional().default(5).describe("Max nesting depth for container traversal")
          })
          .refine((data) => Boolean(data.selector || data.ref), {
            message: "Either 'selector' or 'ref' is required"
          })
          .parse(input);

        const tracked = getTrackedTab(parsed.tabId);
        const userId = parsed.userId ?? tracked.userId;

        const result = await deps.client.extractResources(parsed.tabId, {
          userId,
          selector: parsed.selector,
          ref: parsed.ref,
          types: parsed.types,
          extensions: parsed.extensions,
          resolveBlobs: parsed.resolveBlobs,
          triggerLazyLoad: parsed.triggerLazyLoad,
          maxDepth: parsed.maxDepth
        });
        incrementToolCall(parsed.tabId);
        return okResult(result);
      } catch (error) {
        return toErrorResult(error);
      }
    }
  );

  server.tool(
    "extract_structured",
    "Extract deterministic structured JSON from a page using the camofox-browser structured extraction schema.",
    {
      tabId: z.string().min(1).describe("Tab ID from create_tab"),
      userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
      schema: structuredExtractionSchema
    },
    async (input: unknown) => {
      try {
        const parsed = z
          .object({
            tabId: z.string().min(1).describe("Tab ID from create_tab"),
            userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
            schema: structuredExtractionSchema
          })
          .parse(input);

        const tracked = getTrackedTab(parsed.tabId);
        const userId = parsed.userId ?? tracked.userId;
        const result = await deps.client.extractStructured(parsed.tabId, {
          userId,
          schema: parsed.schema
        });
        incrementToolCall(parsed.tabId);
        return okResult(result);
      } catch (error) {
        return toErrorResult(error);
      }
    }
  );

  server.tool(
    "batch_download",
    "Extract resources from a DOM container and download them all. Combines extract_resources + download in one call. Useful for downloading all images from a chat, all PDFs from a table, etc. Returns per-item results (url, status, error) plus total/succeeded/failed counts; a single broken or slow link never fails the whole call. maxFiles is a hard cap: extra resources are skipped and reported via truncated/skipped.",
    {
      tabId: z.string().min(1).describe("Tab ID from create_tab"),
      userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
      selector: z.string().min(1).optional().describe("CSS selector for target container"),
      ref: z.string().min(1).optional().describe("Element ref from snapshot"),
      types: z
        .array(z.enum(['images', 'links', 'media', 'documents', 'image', 'link', 'document']))
        .optional()
        .describe("Resource types: 'images', 'links', 'media', 'documents' (singular forms also accepted)"),
      extensions: z.array(z.string().min(1)).optional().describe("Filter extensions: ['jpg', 'pdf']"),
      resolveBlobs: z.boolean().optional().default(true).describe("Auto-resolve blob: URLs"),
      concurrency: z.number().int().positive().optional().default(5).describe("Parallel download limit"),
      maxFiles: z.number().int().positive().optional().default(50).describe("Maximum files to download")
    },
    async (input: unknown) => {
      try {
        const parsed = z
          .object({
            tabId: z.string().min(1).describe("Tab ID from create_tab"),
            userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
            selector: z.string().min(1).optional().describe("CSS selector for target container"),
            ref: z.string().min(1).optional().describe("Element ref from snapshot"),
            types: z
              .array(z.enum(['images', 'links', 'media', 'documents', 'image', 'link', 'document']))
              .optional()
              .describe("Resource types: 'images', 'links', 'media', 'documents' (singular forms also accepted)"),
            extensions: z.array(z.string().min(1)).optional().describe("Filter extensions: ['jpg', 'pdf']"),
            resolveBlobs: z.boolean().optional().default(true).describe("Auto-resolve blob: URLs"),
            concurrency: z.number().int().positive().optional().default(5).describe("Parallel download limit"),
            maxFiles: z.number().int().positive().optional().default(50).describe("Maximum files to download")
          })
          .refine((data) => Boolean(data.selector || data.ref), {
            message: "Either 'selector' or 'ref' is required"
          })
          .parse(input);

        const tracked = getTrackedTab(parsed.tabId);
        const userId = parsed.userId ?? tracked.userId;

        // Extraction applies the types/extensions/resolveBlobs filters server-side,
        // so filtered-out resources never reach the download list or the total count.
        const extraction = await deps.client.extractResources(parsed.tabId, {
          userId,
          selector: parsed.selector,
          ref: parsed.ref,
          types: parsed.types,
          extensions: parsed.extensions,
          resolveBlobs: parsed.resolveBlobs
        });

        const urls = extractResourceUrls(extraction);
        const toProcess = urls.slice(0, parsed.maxFiles);
        const skipped = urls.length - toProcess.length;

        const items: BatchDownloadItem[] = new Array(toProcess.length);
        // Download each resource independently: one failure must not abort the rest.
        await runWithConcurrency(toProcess, parsed.concurrency, async (url, slot) => {
          try {
            const download = await deps.client.downloadResource(parsed.tabId, { userId, url });
            items[slot] = {
              url,
              status: "success",
              ...(download !== undefined ? { download } : {})
            };
          } catch (error) {
            items[slot] = { url, status: "failed", error: normalizeError(error).message };
          }
        });

        const succeeded = items.filter((item) => item.status === "success").length;
        incrementToolCall(parsed.tabId);

        return okResult({
          total: items.length,
          succeeded,
          failed: items.length - succeeded,
          truncated: skipped > 0,
          skipped,
          items
        });
      } catch (error) {
        return toErrorResult(error);
      }
    }
  );

  server.tool(
    "resolve_blobs",
    "Resolve blob: URLs to downloadable base64 data. Blob URLs are temporary browser objects (common in Telegram, WhatsApp, Discord) that cannot be downloaded directly. This tool converts them to base64 data URIs.",
    {
      tabId: z.string().min(1).describe("Tab ID from create_tab"),
      userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
      urls: z.array(z.string().min(1)).min(1).describe("Array of blob: URLs to resolve")
    },
    async (input: unknown) => {
      try {
        const parsed = z
          .object({
            tabId: z.string().min(1).describe("Tab ID from create_tab"),
            userId: z.string().min(1).optional().describe("User ID override (default: tracked tab userId)"),
            urls: z.array(z.string().min(1)).min(1).describe("Array of blob: URLs to resolve")
          })
          .parse(input);

        const tracked = getTrackedTab(parsed.tabId);
        const userId = parsed.userId ?? tracked.userId;
        const result = await deps.client.resolveBlobs(parsed.tabId, userId, parsed.urls);
        incrementToolCall(parsed.tabId);
        return okResult(result);
      } catch (error) {
        return toErrorResult(error);
      }
    }
  );
}
