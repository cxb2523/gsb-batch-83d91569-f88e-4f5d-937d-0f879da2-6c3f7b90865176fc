import { TimeoutError } from "@decodo/sdk-ts";

export class CrawlTimeoutError extends TimeoutError {
  readonly crawlId: string;
  readonly waitedSeconds: number;

  constructor(crawlId: string, waitedSeconds: number) {
    super(
      `Crawl ${crawlId} did not finish within ${waitedSeconds}s. It is still running; run \`decodo crawl cancel ${crawlId}\` to stop it.`
    );
    this.crawlId = crawlId;
    this.waitedSeconds = waitedSeconds;
  }
}
