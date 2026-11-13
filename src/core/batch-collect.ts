/**
 * Batch page collection — `charlotte_batch_collect`.
 *
 * A batch-oriented counterpart to navigate + observe: the agent submits up to
 * 50 URLs in one call and gets one auditable outcome per page instead of an
 * all-or-nothing tool error. The design contract:
 *
 *  - One result entry per DISTINCT URL. A URL repeated in `urls` is collected
 *    once and marked `duplicate: true` with its occurrence count, so a
 *    re-submitted batch never bills the same page twice.
 *  - A single page failing (timeout, navigation-guard refusal, any other
 *    navigation/render error) never aborts the run — every later URL is still
 *    visited and gets its own status. Failures carry a machine-readable
 *    `reason` plus the human-readable error message.
 *  - Parameter errors (empty/over-long `urls`, bad `detail`) are raised before
 *    `ensureReady`, so an invalid call never launches or touches the browser.
 *
 * Navigation and rendering reuse the exact same primitives as
 * {@link ./navigation.ts} (`page.goto` + the SSRF-block classification +
 * {@link renderActivePage}), so an `ok` entry's `page` is the same
 * interactive PageRepresentation a `charlotte_observe` on the landed page
 * would return — the active tab is left on the last successfully loaded page
 * and every element ID in the payload stays usable with the interaction tools.
 */
import { z } from "zod";
import { CharlotteError, CharlotteErrorCode } from "../types/errors.js";
import type { NavigationDenyInfo } from "../browser/navigation-guard.js";
import { logger } from "../utils/logger.js";
import type { DetailLevel } from "../renderer/renderer-pipeline.js";
import { defineTool, DEFAULT_SESSION_ID, type ToolDefinition } from "./types.js";
import {
  ensureReady,
  renderActivePage,
  stripEmptyFields,
  handleToolError,
} from "./tool-helpers.js";

/** Per-page outcome labels used in the batch result. */
export type BatchPageStatus = "ok" | "timeout" | "blocked" | "error";

/** Hard cap on submitted URLs, mirrored by the zod schema and the handler check. */
export const MAX_BATCH_URLS = 50;

/** Default per-page navigation timeout, matching charlotte_navigate. */
const DEFAULT_NAVIGATION_TIMEOUT_MS = 30_000;

/**
 * Turn a recorded SSRF-guard refusal into the blocked-status reason text. Kept
 * local to the batch tool: unlike navigate's CharlotteError wording, this is a
 * plain per-page explanation that lives inside a successful batch response.
 */
function describeBlock(block: NavigationDenyInfo): string {
  if (block.reason === "resolution-failed") {
    return (
      "Navigation refused by the SSRF guard: the host could not be resolved, so the " +
      "guard failed closed and no connection was attempted."
    );
  }
  const resolvedIp = block.ip ?? "an address";
  const matchedRange = block.matchedRange ?? "a denied range";
  return (
    `Navigation blocked by the SSRF guard: ${block.url} resolves to ${resolvedIp}, which is ` +
    `in the denied range ${matchedRange}. Add the range to allowPrivateNetworks in the config to allow it.`
  );
}

/**
 * Collapse a `page.goto` rejection into one of the batch statuses, honoring the
 * same precedence the navigate tool uses: a recorded guard refusal is a
 * `blocked`, a timeout-shaped failure is a `timeout`, everything else is an
 * `error`.
 */
function classifyNavigationFailure(
  url: string,
  navigationError: unknown,
  block: NavigationDenyInfo | null,
  timeoutMs: number,
): { status: BatchPageStatus; reason: string } {
  if (block) {
    return { status: "blocked", reason: describeBlock(block) };
  }
  const message =
    navigationError instanceof Error ? navigationError.message : String(navigationError);
  if (message.includes("timeout") || message.includes("Timeout")) {
    return {
      status: "timeout",
      reason: `Navigation to '${url}' timed out after ${timeoutMs}ms.`,
    };
  }
  return { status: "error", reason: `Navigation to '${url}' failed: ${message}` };
}

/** One distinct URL's outcome inside a batch collection. */
export interface BatchPageResult {
  url: string;
  status: BatchPageStatus;
  detail: DetailLevel;
  /**
   * Present on `ok`: the structured representation of the landed page, stripped
   * exactly like an observe response, with element IDs that remain interactive.
   */
  page?: Record<string, unknown>;
  /** Present on non-`ok`: a human-readable explanation of the failure. */
  reason?: string;
  /** True when the URL appeared more than once in the submitted `urls`. */
  duplicate?: boolean;
  /** How many times the URL appeared in the submitted `urls` (present when > 1). */
  occurrences?: number;
}

/** The full batch payload returned inside the tool's text content block. */
export interface BatchCollectResult {
  /** Number of URL entries submitted (including repeats). */
  total: number;
  /** Number of distinct URLs actually collected. */
  unique_count: number;
  /** Distinct URLs whose status is `ok`. */
  success_count: number;
  /** Distinct URLs whose status is not `ok`. */
  failure_count: number;
  /** One outcome per distinct URL, in first-seen order. */
  results: BatchPageResult[];
  /** Distinct unsuccessful URLs, ready to be re-submitted verbatim. */
  retry_urls: string[];
}

/**
 * Deduplicate a submitted URL list into first-seen order with occurrence
 * counts. Pure and exported so the no-browser unit tests can pin the
 * bookkeeping independently of Chromium.
 */
export function dedupeUrls(urls: readonly string[]): Array<{ url: string; occurrences: number }> {
  const counts = new Map<string, number>();
  for (const url of urls) {
    counts.set(url, (counts.get(url) ?? 0) + 1);
  }
  return [...counts.entries()].map(([url, occurrences]) => ({ url, occurrences }));
}

/**
 * Validate batch parameters against the same INVALID_ARGUMENT contract the
 * handler enforces. Throws {@link CharlotteError} for anything that must not
 * reach the browser; returns the parsed detail level otherwise. Exported for
 * the no-browser unit tests.
 */
export function validateBatchParams(urls: unknown, detail: unknown): DetailLevel {
  if (!Array.isArray(urls) || urls.length === 0) {
    throw new CharlotteError(
      CharlotteErrorCode.INVALID_ARGUMENT,
      "'urls' must be a non-empty array of URL strings.",
      "Pass between 1 and 50 URLs in a single batch_collect call.",
    );
  }
  if (urls.length > MAX_BATCH_URLS) {
    throw new CharlotteError(
      CharlotteErrorCode.INVALID_ARGUMENT,
      `'urls' contains ${urls.length} entries; a batch may contain at most ${MAX_BATCH_URLS}.`,
      "Split the batch into multiple calls of at most 50 URLs each.",
    );
  }
  if (urls.some((url) => typeof url !== "string" || url.trim() === "")) {
    throw new CharlotteError(
      CharlotteErrorCode.INVALID_ARGUMENT,
      "Every entry in 'urls' must be a non-empty URL string.",
      "Remove empty/non-string entries and re-submit the batch.",
    );
  }
  if (detail !== undefined && detail !== "minimal" && detail !== "summary" && detail !== "full") {
    throw new CharlotteError(
      CharlotteErrorCode.INVALID_ARGUMENT,
      `Invalid detail level '${String(detail)}'.`,
      "Use one of: 'minimal', 'summary', 'full'.",
    );
  }
  return (detail as DetailLevel | undefined) ?? "summary";
}

const batchCollectTool = defineTool({
  name: "charlotte_batch_collect",
  description:
    "Collect multiple pages in one batch (1-50 URLs) and get a separate, auditable outcome for each — one page timing out or being blocked never discards the rest. Each distinct URL is collected once; repeated URLs are marked 'duplicate' and not re-fetched. Every result carries status 'ok', 'timeout', 'blocked', or 'error': ok results include the page's structured representation (same detail levels as observe, default summary) with element IDs you can keep interacting with, failures include a 'reason'. The response includes total/unique/success/failure counts and 'retry_urls' — every unsuccessful URL, ready to submit again. The active tab ends on the last successfully loaded page.",
  inputSchema: {
    urls: z
      .array(z.string().min(1))
      .min(1)
      .max(MAX_BATCH_URLS)
      .describe(
        "URLs to collect, 1 to 50 entries. Duplicate URLs are fetched once and flagged in the results.",
      ),
    detail: z
      .enum(["minimal", "summary", "full"])
      .optional()
      .describe(
        'Page representation detail for every ok result, same levels as observe: "summary" (default), "full" (all text content), "minimal" (landmarks + interactive only)',
      ),
    timeout: z
      .number()
      .int()
      .positive()
      .optional()
      .describe(
        "Per-page navigation timeout in ms (default: 30000). A timeout marks that page 'timeout' and collection continues with the next URL.",
      ),
  },
  async handler(deps, { urls, detail, timeout }) {
    try {
      // Parameter validation happens FIRST — an invalid batch must never launch
      // the browser or open a tab (the zod layer also rejects these, but the
      // explicit check keeps the guarantee independent of transport behavior).
      const detailLevel = validateBatchParams(urls, detail);
      const timeoutMs = timeout ?? DEFAULT_NAVIGATION_TIMEOUT_MS;

      await ensureReady(deps);
      const page = deps.pageManager.getActivePage();
      const deduped = dedupeUrls(urls);

      const results: BatchPageResult[] = [];
      const retryUrls: string[] = [];
      let successCount = 0;

      for (const { url, occurrences } of deduped) {
        const duplicateMarkers = occurrences > 1 ? { duplicate: true as const, occurrences } : {};

        try {
          // Per-navigation reset so a guard refusal recorded for one URL can
          // never be attributed to the next one (mirrors charlotte_navigate).
          deps.pageManager.clearErrors();

          await page.goto(url, { waitUntil: "load", timeout: timeoutMs });

          // dom- selector IDs are scoped to the document they were created
          // against; drop them on each cross-document navigation.
          deps.elementIdGenerator.clearDomQueryIds();

          const representation = await renderActivePage(deps, {
            detail: detailLevel,
            source: "action",
          });

          results.push({
            url,
            status: "ok",
            detail: detailLevel,
            page: stripEmptyFields(representation),
            ...duplicateMarkers,
          });
          successCount++;
        } catch (navigationError: unknown) {
          // A guard refusal is recorded before goto rejects; check it first.
          const block = deps.pageManager.getLastNavigationBlock();
          const { status, reason } = classifyNavigationFailure(
            url,
            navigationError,
            block,
            timeoutMs,
          );
          logger.warn("batch_collect page failed", { url, status, reason });
          results.push({
            url,
            status,
            detail: detailLevel,
            reason,
            ...duplicateMarkers,
          });
          retryUrls.push(url);
          // Deliberately swallowed: the next URL must still be collected.
        }
      }

      const payload: BatchCollectResult = {
        total: urls.length,
        unique_count: deduped.length,
        success_count: successCount,
        failure_count: deduped.length - successCount,
        results,
        retry_urls: retryUrls,
      };

      // Partial failures are normal batch outcomes, not tool errors: the call
      // itself succeeded and every page has an auditable status.
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ session_id: DEFAULT_SESSION_ID, ...payload }),
          },
        ],
      };
    } catch (error: unknown) {
      // Only parameter/setup errors land here — per-page failures are handled
      // inside the loop and never escape it.
      return handleToolError(error);
    }
  },
});

export const batchCollectTools: ToolDefinition[] = [batchCollectTool];
