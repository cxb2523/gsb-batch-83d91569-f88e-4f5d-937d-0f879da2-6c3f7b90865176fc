import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { CacheMode, RateLimiter, RobotsParser, WebCrawler } from "../../src/index";

/**
 * Integration tests for the robots.txt admission report produced by
 * deepCrawlWithReport. Runs entirely against a local Bun.serve server.
 */

const CRAWL_DELAY_SECONDS = 1;
const CRAWL_DELAY_MS = CRAWL_DELAY_SECONDS * 1000;

const page = (title: string, links: string[]) => `<!DOCTYPE html>
<html>
<head><title>${title}</title></head>
<body>
  <h1>${title}</h1>
  ${links.map((href) => `<a href="${href}">${href}</a>`).join("\n  ")}
</body>
</html>`;

let server: ReturnType<typeof Bun.serve>;
let baseUrl: string;
let robotsHits = 0;
let crawler: WebCrawler;

beforeAll(async () => {
	const html = (body: string) => new Response(body, { headers: { "content-type": "text/html" } });

	server = Bun.serve({
		port: 0,
		routes: {
			"/robots.txt": () => {
				robotsHits++;
				return new Response(
					["User-agent: *", "Disallow: /private", `Crawl-delay: ${CRAWL_DELAY_SECONDS}`, ""].join(
						"\n",
					),
					{ headers: { "content-type": "text/plain" } },
				);
			},
			"/": () => html(page("home", ["/a", "/private/secret"])),
			"/a": () => html(page("a", ["/b"])),
			"/b": () => html(page("b", ["/c"])),
			"/c": () => html(page("c", ["/"])),
			"/private/secret": () => html(page("secret", [])),
		},
	});
	baseUrl = `http://localhost:${server.port}`;

	crawler = new WebCrawler({ verbose: false });
	await crawler.start();
});

afterAll(async () => {
	await crawler.close();
	server.stop();
});

describe("Deep Crawl - robots report", () => {
	test("reports per-candidate robots decisions, applies crawl-delay, fetches robots.txt once", async () => {
		const robotsParser = new RobotsParser();
		const rateLimiter = new RateLimiter({ baseDelay: 0, maxDelay: 60_000, jitter: 0 });

		const { results, robotsReport } = await crawler.deepCrawlWithReport(
			`${baseUrl}/`,
			{ cacheMode: CacheMode.Bypass },
			{ maxDepth: 3, maxPages: 3, robotsParser, rateLimiter },
		);

		// Denied URL was never crawled; allowed URLs were.
		const crawledUrls = results.map((r) => r.url);
		expect(crawledUrls.some((u) => u.includes("/private/"))).toBe(false);
		expect(crawledUrls).toContain(`${baseUrl}/a`);
		expect(crawledUrls).toContain(`${baseUrl}/b`);

		// Report records: /a, /b, /c allowed; /private/secret denied with reason.
		const byUrl = new Map(robotsReport.records.map((r) => [r.url, r]));

		const denied = byUrl.get(`${baseUrl}/private/secret`);
		expect(denied).toBeDefined();
		expect(denied?.decision).toBe("denied");
		expect(denied?.reason).toBe("Disallow: /private");
		expect(denied?.crawlDelayMs).toBe(CRAWL_DELAY_MS);

		for (const path of ["/a", "/b", "/c"]) {
			const record = byUrl.get(`${baseUrl}${path}`);
			expect(record).toBeDefined();
			expect(record?.decision).toBe("allowed");
			expect(record?.reason).toBeNull();
			expect(record?.crawlDelayMs).toBe(CRAWL_DELAY_MS);
		}

		// Counts match the records.
		expect(robotsReport.denied).toBe(1);
		expect(robotsReport.allowed).toBe(robotsReport.records.length - 1);
		expect(robotsReport.allowed).toBe(3);

		// crawl-delay propagated to the rate limiter (maxDelay set above it, so no truncation).
		expect(rateLimiter.getDelay(`${baseUrl}/`)).toBe(CRAWL_DELAY_MS);

		// robots.txt fetched exactly once for the whole crawl (per-origin cache).
		expect(robotsHits).toBe(1);
	});

	test("returns an empty report when no robotsParser is configured", async () => {
		const { results, robotsReport } = await crawler.deepCrawlWithReport(
			`${baseUrl}/`,
			{ cacheMode: CacheMode.Bypass },
			{ maxDepth: 1, maxPages: 5 },
		);

		expect(results.length).toBeGreaterThanOrEqual(1);
		expect(robotsReport.records).toEqual([]);
		expect(robotsReport.allowed).toBe(0);
		expect(robotsReport.denied).toBe(0);
	});

	test("deepCrawl still returns plain results without a report", async () => {
		const results = await crawler.deepCrawl(
			`${baseUrl}/`,
			{ cacheMode: CacheMode.Bypass },
			{ maxDepth: 1, maxPages: 5, robotsParser: new RobotsParser() },
		);

		expect(Array.isArray(results)).toBe(true);
		expect(results.some((r) => r.url.includes("/private/"))).toBe(false);
	});
});
