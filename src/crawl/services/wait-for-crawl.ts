import { setTimeout as sleep } from "node:timers/promises";
import type { GetCrawlStatusResponse, WebScrapingApi } from "@decodo/sdk-ts";
import { CrawlTimeoutError } from "../errors/crawl-timeout-error.js";

export interface WaitForCrawlOptions {
  onStatus?: (status: GetCrawlStatusResponse) => void;
  pollIntervalMs: number;
  timeoutMs: number;
}

export async function waitForCrawl(
  api: WebScrapingApi,
  crawlId: string,
  { onStatus, pollIntervalMs, timeoutMs }: WaitForCrawlOptions
): Promise<GetCrawlStatusResponse> {
  const deadline = Date.now() + timeoutMs;
  let status = await api.getCrawlStatus(crawlId);
  onStatus?.(status);

  while (status.status === "pending") {
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) {
      throw new CrawlTimeoutError(crawlId, timeoutMs / 1000);
    }
    await sleep(Math.min(pollIntervalMs, remainingMs));
    status = await api.getCrawlStatus(crawlId);
    onStatus?.(status);
  }

  return status;
}
