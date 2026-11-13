import type {
  CrawlResultsOptions,
  GetCrawlStatusResponse,
  WebScrapingApi,
} from "@decodo/sdk-ts";
import { CrawlTimeoutError } from "../errors/crawl-timeout-error.js";
import type { CrawlWaitOptions } from "../types/crawl-command.js";
import { assertCrawlSucceeded } from "./assert-crawl-succeeded.js";
import { settleCrawl } from "./settle-crawl.js";
import { writeCrawlPages } from "./write-crawl-pages.js";

export async function deliverCrawlPages(
  api: WebScrapingApi,
  crawlId: string,
  options: CrawlWaitOptions & { output?: string },
  resultsOptions?: CrawlResultsOptions
): Promise<void> {
  const readPages = () =>
    resultsOptions === undefined
      ? api.getCrawlResults(crawlId)
      : api.getCrawlResults(crawlId, resultsOptions);

  let status: GetCrawlStatusResponse;
  try {
    status = await settleCrawl(api, crawlId, options);
  } catch (err) {
    if (!(err instanceof CrawlTimeoutError)) {
      throw err;
    }
    writeCrawlPages(await readPages(), options.output);
    throw err;
  }

  writeCrawlPages(await readPages(), options.output);
  assertCrawlSucceeded(status);
}
