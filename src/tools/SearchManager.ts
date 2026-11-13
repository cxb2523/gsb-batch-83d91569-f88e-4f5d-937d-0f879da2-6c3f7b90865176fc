import { ConfigManager } from "../utils/config";
import { DuckDuckGoSearcher } from "./DuckDuckGoSearcher";
import { GoogleSearcher } from "./GoogleSearcher";
import type {
	BatchQueryOutcome,
	ISearchProvider,
	MergedSearchResult,
	SearchBatchResult,
	SearchResult,
} from "./search/types";

/**
 * Normalizes a result link by stripping the URL fragment (hash).
 * Links that cannot be parsed as URLs are returned unchanged, matching
 * the historical dedupe behavior of `searchMulti`.
 */
function normalizeLink(link: string): string {
	try {
		const parsed = new URL(link);
		parsed.hash = "";
		return parsed.toString();
	} catch {
		return link;
	}
}

/**
 * Reduces a result list to unique entries by hash-normalized link,
 * preserving the order of first appearance.
 */
function dedupeByNormalizedLink(results: SearchResult[]): SearchResult[] {
	const seen = new Set<string>();
	const deduped: SearchResult[] = [];
	for (const result of results) {
		const normalized = normalizeLink(result.link);
		if (!seen.has(normalized)) {
			seen.add(normalized);
			deduped.push(result);
		}
	}
	return deduped;
}

function describeError(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
}

export class SearchManager implements ISearchProvider {
	public readonly name = "SearchManager";
	private configManager: ConfigManager;
	private googleSearcher: GoogleSearcher;
	private ddgSearcher: DuckDuckGoSearcher;

	constructor(configManager?: ConfigManager) {
		this.configManager = configManager || new ConfigManager();
		this.googleSearcher = new GoogleSearcher(this.configManager);
		this.ddgSearcher = new DuckDuckGoSearcher();
	}

	public async search(query: string, numResults = 5): Promise<SearchResult[]> {
		const trimmed = query.trim();
		if (!trimmed) return [];

		const serperKey = await this.configManager.get("SERPER_API_KEY");

		if (serperKey) {
			try {
				const results = await this.googleSearcher.search(trimmed, numResults);
				if (results.length > 0) {
					return results;
				}
			} catch (err) {
				// Fallback to DuckDuckGo if Serper fails or rate-limits
			}
		}

		// Fallback to zero-config DuckDuckGo provider
		return await this.ddgSearcher.search(trimmed, numResults);
	}

	/**
	 * Executes multiple investigative search queries concurrently,
	 * deduplicating the aggregated results across queries by normalized URL.
	 */
	public async searchMulti(
		queries: string[],
		numPerQuery = 4,
	): Promise<SearchResult[]> {
		const uniqueQueries = Array.from(
			new Set(queries.map((q) => q.trim()).filter(Boolean)),
		);
		if (uniqueQueries.length === 0) return [];

		const searchPromises = uniqueQueries.map((q) =>
			this.search(q, numPerQuery),
		);
		const nestedResults = await Promise.all(searchPromises);

		const seenUrls = new Set<string>();
		const aggregated: SearchResult[] = [];

		for (const results of nestedResults) {
			for (const r of results) {
				const normalized = normalizeLink(r.link);

				if (!seenUrls.has(normalized)) {
					seenUrls.add(normalized);
					aggregated.push(r);
				}
			}
		}

		return aggregated;
	}

	/**
	 * Fault-tolerant batch search.
	 *
	 * Compared to {@link searchMulti}, this method never rejects when an
	 * individual query fails: blank queries are dropped, duplicate queries
	 * are executed only once, and every executed query gets an explicit
	 * outcome (success — with or without results — or error with a readable
	 * message). A cross-query merge keyed by hash-normalized link is returned
	 * alongside the per-query outcomes, recording which queries produced
	 * each merged result.
	 *
	 * @param queries Raw query strings; empty/whitespace-only entries are skipped.
	 * @param numPerQuery Number of results requested per executed query.
	 */
	public async searchBatch(
		queries: string[],
		numPerQuery = 4,
	): Promise<SearchBatchResult> {
		// Trim, drop blanks, and de-duplicate while retaining first-seen order.
		const uniqueQueries = Array.from(
			new Set(queries.map((q) => q.trim()).filter(Boolean)),
		);

		if (uniqueQueries.length === 0) {
			return { queryOutcomes: [], mergedResults: [] };
		}

		// Run every query concurrently; a rejection for one query must not
		// cancel the others, so each promise settles into an outcome object.
		const outcomes = await Promise.all(
			uniqueQueries.map(async (query): Promise<BatchQueryOutcome> => {
				try {
					const rawResults = await this.search(query, numPerQuery);
					return {
						query,
						status: "success",
						results: dedupeByNormalizedLink(rawResults),
					};
				} catch (err) {
					return {
						query,
						status: "error",
						results: [],
						error: describeError(err),
					};
				}
			}),
		);

		// Merge across queries by normalized link, keeping first-seen order
		// and recording every contributing query on each entry.
		const mergedByLink = new Map<string, MergedSearchResult>();
		for (const outcome of outcomes) {
			if (outcome.status !== "success") continue;
			for (const result of outcome.results) {
				const normalized = normalizeLink(result.link);
				const existing = mergedByLink.get(normalized);
				if (existing) {
					if (!existing.sourceQueries.includes(outcome.query)) {
						existing.sourceQueries.push(outcome.query);
					}
				} else {
					mergedByLink.set(normalized, {
						...result,
						sourceQueries: [outcome.query],
					});
				}
			}
		}

		return {
			queryOutcomes: outcomes,
			mergedResults: Array.from(mergedByLink.values()),
		};
	}
}
