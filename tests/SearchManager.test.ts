import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchManager } from "../src/tools/SearchManager";
import { ConfigManager } from "../src/utils/config";

// Mock DuckDuckGoSearcher
vi.mock("../src/tools/DuckDuckGoSearcher", () => {
	return {
		DuckDuckGoSearcher: class {
			search = vi.fn().mockResolvedValue([
				{
					title: "DDG Result",
					link: "https://duckduckgo-source.com/page",
					snippet: "DDG snippet content",
				},
			]);
		},
	};
});

// Mock GoogleSearcher
vi.mock("../src/tools/GoogleSearcher", () => {
	return {
		GoogleSearcher: class {
			search = vi.fn().mockResolvedValue([
				{
					title: "Serper Result",
					link: "https://google-source.com/article",
					snippet: "Serper snippet content",
				},
			]);
		},
	};
});

describe("SearchManager", () => {
	let configManager: ConfigManager;
	let manager: SearchManager;

	beforeEach(() => {
		configManager = new ConfigManager();
		manager = new SearchManager(configManager);
		vi.clearAllMocks();
	});

	it("should prioritize GoogleSearcher when SERPER_API_KEY is configured", async () => {
		configManager.get = vi.fn().mockImplementation(async (key: string) => {
			if (key === "SERPER_API_KEY") return "valid-serper-key";
			return undefined;
		});

		const results = await manager.search("AI agents", 5);
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].title).toBe("Serper Result");
		expect(results[0].link).toBe("https://google-source.com/article");
	});

	it("should fallback to DuckDuckGo when SERPER_API_KEY is missing", async () => {
		configManager.get = vi.fn().mockResolvedValue(undefined);

		const results = await manager.search("Zero config query", 5);
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].title).toBe("DDG Result");
		expect(results[0].link).toBe("https://duckduckgo-source.com/page");
	});

	it("should fallback to DuckDuckGo when GoogleSearcher throws an error", async () => {
		configManager.get = vi.fn().mockImplementation(async (key: string) => {
			if (key === "SERPER_API_KEY") return "valid-serper-key";
			return undefined;
		});

		// Force googleSearcher to reject
		(manager as any).googleSearcher.search.mockRejectedValueOnce(
			new Error("Rate limit 429"),
		);

		const results = await manager.search("Fallback on error", 3);
		expect(results.length).toBeGreaterThan(0);
		expect(results[0].title).toBe("DDG Result");
	});

	it("should return empty array when query is empty", async () => {
		const results = await manager.search("   ");
		expect(results).toEqual([]);
	});

	it("should execute searchMulti and deduplicate results by normalized URL", async () => {
		configManager.get = vi.fn().mockResolvedValue(undefined);

		(manager as any).ddgSearcher.search = vi
			.fn()
			.mockImplementation(async (q: string) => {
				if (q.includes("architecture")) {
					return [
						{
							title: "Architecture Guide",
							link: "https://example.com/guide#part-1",
							snippet: "Part 1 overview",
						},
						{
							title: "Shared Article",
							link: "https://shared.org/research",
							snippet: "Shared overview",
						},
					];
				}
				return [
					{
						title: "Benchmarks",
						link: "https://example.com/benchmarks",
						snippet: "Performance stats",
					},
					{
						title: "Shared Article Dup",
						link: "https://shared.org/research#section2", // same normalized URL
						snippet: "Duplicate source snippet",
					},
				];
			});

		const results = await manager.searchMulti(
			["AI architecture", "AI benchmarks", "AI architecture"], // duplicate query handled
			3,
		);

		expect(results.length).toBe(3);
		const links = results.map((r) => r.link);
		expect(links).toContain("https://example.com/guide#part-1");
		expect(links).toContain("https://shared.org/research");
		expect(links).toContain("https://example.com/benchmarks");
	});

	it("should return empty array for searchMulti when given empty query array", async () => {
		const results = await manager.searchMulti(["  ", ""]);
		expect(results).toEqual([]);
	});

	describe("searchBatch", () => {
		it("should keep successful queries when another query throws, and never reject", async () => {
			configManager.get = vi.fn().mockResolvedValue(undefined);

			(manager as any).ddgSearcher.search = vi
				.fn()
				.mockImplementation(async (q: string) => {
					if (q === "broken query") throw new Error("network down");
					return [
						{
							title: "Healthy Result",
							link: "https://example.com/healthy",
							snippet: "from the working query",
						},
					];
				});

			const batch = await manager.searchBatch(
				["broken query", "working query"],
				3,
			);

			expect(batch.queryOutcomes).toHaveLength(2);

			const failed = batch.queryOutcomes.find((o) => o.query === "broken query");
			expect(failed?.status).toBe("error");
			expect(failed?.results).toEqual([]);
			expect(failed?.error).toBe("network down");

			const succeeded = batch.queryOutcomes.find(
				(o) => o.query === "working query",
			);
			expect(succeeded?.status).toBe("success");
			expect(succeeded?.error).toBeUndefined();
			expect(succeeded?.results).toHaveLength(1);
			expect(succeeded?.results[0].link).toBe(
				"https://example.com/healthy",
			);

			// The healthy query's results survive the failed query.
			expect(batch.mergedResults).toHaveLength(1);
			expect(batch.mergedResults[0].link).toBe(
				"https://example.com/healthy",
			);
			expect(batch.mergedResults[0].sourceQueries).toEqual([
				"working query",
			]);
		});

		it("should execute duplicate queries only once", async () => {
			configManager.get = vi.fn().mockResolvedValue(undefined);

			const searchSpy = vi
				.spyOn(manager, "search")
				.mockResolvedValue([
					{
						title: "Once",
						link: "https://example.com/once",
						snippet: "executed a single time",
					},
				]);

			const batch = await manager.searchBatch(
				["repeated", "  repeated  ", "repeated"],
				2,
			);

			expect(searchSpy).toHaveBeenCalledTimes(1);
			expect(searchSpy).toHaveBeenCalledWith("repeated", 2);
			expect(batch.queryOutcomes).toHaveLength(1);
			expect(batch.queryOutcomes[0].query).toBe("repeated");
		});

		it("should dedupe the same link with different hashes across queries and retain source attribution", async () => {
			configManager.get = vi.fn().mockResolvedValue(undefined);

			(manager as any).ddgSearcher.search = vi
				.fn()
				.mockImplementation(async (q: string) => {
					if (q === "first query") {
						return [
							{
								title: "Shared First Seen",
								link: "https://shared.org/research#intro",
								snippet: "first occurrence wins",
							},
							{
								title: "Only In First",
								link: "https://first.example.com/a",
								snippet: "unique to first query",
							},
						];
					}
					return [
						{
							title: "Shared Other Hash",
							link: "https://shared.org/research#conclusion",
							snippet: "same page, different fragment",
						},
						{
							title: "Only In Second",
							link: "https://second.example.com/b",
							snippet: "unique to second query",
						},
					];
				});

			const batch = await manager.searchBatch(
				["first query", "second query"],
				4,
			);

			expect(batch.queryOutcomes).toHaveLength(2);

			// First-seen order: shared link, first-only link, second-only link.
			expect(batch.mergedResults).toHaveLength(3);
			expect(batch.mergedResults.map((r) => r.link)).toEqual([
				"https://shared.org/research#intro",
				"https://first.example.com/a",
				"https://second.example.com/b",
			]);

			const shared = batch.mergedResults[0];
			expect(shared.title).toBe("Shared First Seen");
			expect(shared.sourceQueries).toEqual([
				"first query",
				"second query",
			]);

			// Per-query outcomes still carry each query's own deduped results.
			const firstOutcome = batch.queryOutcomes[0];
			expect(firstOutcome.results.map((r) => r.link)).toEqual([
				"https://shared.org/research#intro",
				"https://first.example.com/a",
			]);
			const secondOutcome = batch.queryOutcomes[1];
			expect(secondOutcome.results.map((r) => r.link)).toEqual([
				"https://shared.org/research#conclusion",
				"https://second.example.com/b",
			]);
		});

		it("should return empty conclusions when every query is blank, without searching", async () => {
			const searchSpy = vi.spyOn(manager, "search");

			const batch = await manager.searchBatch(["", "   ", "\t"], 3);

			expect(searchSpy).not.toHaveBeenCalled();
			expect(batch.queryOutcomes).toEqual([]);
			expect(batch.mergedResults).toEqual([]);
		});

		it("should distinguish a successful zero-result query from a failed query", async () => {
			configManager.get = vi.fn().mockResolvedValue(undefined);

			(manager as any).ddgSearcher.search = vi
				.fn()
				.mockImplementation(async (q: string) => {
					if (q === "empty but fine") return [];
					throw new Error("provider exploded");
				});

			const batch = await manager.searchBatch(
				["empty but fine", "doomed"],
				2,
			);

			const empty = batch.queryOutcomes.find(
				(o) => o.query === "empty but fine",
			);
			expect(empty?.status).toBe("success");
			expect(empty?.results).toEqual([]);
			expect(empty?.error).toBeUndefined();

			const failed = batch.queryOutcomes.find((o) => o.query === "doomed");
			expect(failed?.status).toBe("error");
			expect(failed?.results).toEqual([]);
			expect(failed?.error).toBe("provider exploded");

			expect(batch.mergedResults).toEqual([]);
		});

		it("should dedupe hash variants within a single query as well", async () => {
			configManager.get = vi.fn().mockResolvedValue(undefined);

			(manager as any).ddgSearcher.search = vi.fn().mockResolvedValue([
				{
					title: "Page",
					link: "https://page.example.com/doc#one",
					snippet: "first fragment",
				},
				{
					title: "Page Again",
					link: "https://page.example.com/doc#two",
					snippet: "second fragment",
				},
			]);

			const batch = await manager.searchBatch(["single query"], 5);

			expect(batch.queryOutcomes).toHaveLength(1);
			expect(batch.queryOutcomes[0].results).toHaveLength(1);
			expect(batch.queryOutcomes[0].results[0].link).toBe(
				"https://page.example.com/doc#one",
			);
			expect(batch.mergedResults).toHaveLength(1);
			expect(batch.mergedResults[0].sourceQueries).toEqual([
				"single query",
			]);
		});
	});
});
