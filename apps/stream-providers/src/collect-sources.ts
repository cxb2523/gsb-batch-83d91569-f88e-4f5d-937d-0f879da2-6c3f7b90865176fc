import {
  collectSearch,
  type CollectSearchInput,
  type CollectSearchResult,
  type CollectSource,
} from './collect-search.ts';

/** Structural view of the source runtime used by the collection endpoint. */
export interface CollectSearchRuntime {
  search(
    query: string,
    options: { searchEngine: string; limit: number; signal?: AbortSignal },
  ): Promise<{ tracks: readonly unknown[] }>;
}

/** Structural view of the extractor registry owned by the source host. */
export interface CollectSearchExtractors {
  readonly store: ReadonlyMap<string, unknown>;
}

/** Display names for the extractors this deployment loads. Unknown IDs keep their identifier. */
const DISPLAY_NAMES: Readonly<Record<string, string>> = {
  'com.retrouser955.discord-player.discord-player-youtubei': 'youtube',
  'com.discord-player.itsmaat.spotifyextractor': 'spotify',
  'com.discord-player.applemusicextractor': 'apple-music',
  'com.discord-player.soundcloudextractor': 'soundcloud',
};

/**
 * Adapt every loaded extractor to an independently execrable search source.
 * Extractor order matches registration order, so merged results stay deterministic.
 */
export function createExtractorSources(host: {
  runtime: CollectSearchRuntime;
  extractors: CollectSearchExtractors;
}): CollectSource[] {
  return [...host.extractors.store.keys()].map((identifier) => ({
    name: DISPLAY_NAMES[identifier] ?? identifier,
    search: (input: CollectSearchInput) =>
      host.runtime
        .search(input.query, { searchEngine: identifier, limit: input.limit, signal: input.signal })
        .then((result) => result.tracks),
  }));
}

export { collectSearch };
export type { CollectSearchResult, CollectSource };
