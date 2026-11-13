export interface SearchResult {
	title: string;
	link: string;
	snippet: string;
}

export interface ISearchProvider {
	readonly name: string;
	search(query: string, numResults?: number): Promise<SearchResult[]>;
}

/**
 * Outcome of a single query inside a batch search.
 * - "success": the query executed (it may still have zero results)
 * - "error": the query threw before any results could be returned
 */
export type BatchQueryStatus = "success" | "error";

/**
 * Per-query outcome produced by {@link SearchManager.searchBatch}.
 * Empty/blank queries are filtered out beforehand, so every entry here
 * corresponds to a query that was actually executed.
 */
export interface BatchQueryOutcome {
	/** The trimmed query that was executed. */
	query: string;
	/** "success" means the query ran; distinguish zero-result runs via `results`. */
	status: BatchQueryStatus;
	/** Deduplicated (by hash-normalized link) results for this query. */
	results: SearchResult[];
	/** Human-readable error message; present only when status is "error". */
	error?: string;
}

/**
 * A merged result spanning every query in the batch, keyed by
 * hash-normalized link.
 */
export interface MergedSearchResult extends SearchResult {
	/** Queries (trimmed) that returned this normalized link, first-seen first. */
	sourceQueries: string[];
}

/**
 * Full result of {@link SearchManager.searchBatch}: per-query outcomes plus
 * a cross-query merged list. The batch promise never rejects — individual
 * failures are reported through the per-query `status`/`error` fields.
 */
export interface SearchBatchResult {
	/** One outcome per executed query, in the order the queries were given. */
	queryOutcomes: BatchQueryOutcome[];
	/** Cross-query merge keyed by normalized link, first-seen order retained. */
	mergedResults: MergedSearchResult[];
}
