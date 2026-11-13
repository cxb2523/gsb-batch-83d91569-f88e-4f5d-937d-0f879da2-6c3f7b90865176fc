import * as cheerio from 'cheerio';
import { SearchResult, type EngineSearchOptions } from '../types.js';
import { logger } from '../infrastructure/logger.js';
import { withTimeout } from '../infrastructure/abort.js';
import { fetchForEngine } from '../infrastructure/engine-http.js';
import { EngineAdapterError } from './engine-error.js';
import {
  profileHeaders,
  resolveRequestProfile,
  currentProfileWindowKey,
  type RequestProfile,
} from './request-profiles.js';

export const duckduckgoHtmlProvider = {
  id: 'duckduckgo' as const,
  name: 'DuckDuckGo (HTML)',
  isFree: true,
  languages: ['en'],
};

/**
 * What the primary HTML representation reported. Today the Lite fallback is only
 * entered after an HTTP 202 rate-limit answer, but the type stays open so a new
 * trigger can be documented without breaking callers.
 */
export type DuckDuckGoPrimaryChannelStatus = 'http_202';

/**
 * How the same-provider Lite representation ended.
 *
 * - `results`   — Lite returned one or more usable organic results
 * - `empty`     — Lite answered normally but carried no usable results
 * - `challenge` — Lite answered with a `#challenge-form` bot/captcha page
 * - `failed`    — Lite could not produce a page at all (HTTP error, network, abort)
 */
export type DuckDuckGoFallbackOutcome = 'results' | 'empty' | 'challenge' | 'failed';

/**
 * Inspectable record of one HTML → Lite fallback. Lite is an alternate
 * representation of the same provider, never an independent source and never a
 * rate-limit bypass: the trace makes that lineage explicit.
 *
 * All fields are frozen so callers cannot quietly rewrite audit evidence.
 */
export interface DuckDuckGoFallbackTrace {
  /** Status reported by the primary HTML channel that triggered the fallback. */
  readonly primaryChannelStatus: DuckDuckGoPrimaryChannelStatus;
  /** Same-provider representation that was tried opportunistically. */
  readonly fallbackChannel: 'lite';
  /** How the Lite attempt ended (challenge pages are not "empty"). */
  readonly fallbackOutcome: DuckDuckGoFallbackOutcome;
  /** Organic results actually returned to the caller after filtering. */
  readonly count: number;
  /** Sponsored/ad title rows (with their following snippet rows) discarded. */
  readonly sponsoredDropped: number;
  /** Rows discarded because their link was non-http(s) or DuckDuckGo-internal. */
  readonly unsafeLinkDropped: number;
}

/**
 * Search answer plus the optional fallback trace. `fallbackTrace` is present
 * only when the primary HTML channel returned 202 and a Lite attempt was made.
 */
export interface DuckDuckGoSearchOutcome {
  readonly results: SearchResult[];
  readonly fallbackTrace?: DuckDuckGoFallbackTrace;
}

export class DuckDuckGoFallbackError extends EngineAdapterError {
  /** Structured fallback evidence, attached when the trace is available. */
  readonly fallbackTrace?: DuckDuckGoFallbackTrace;

  constructor(message: string, cause?: unknown, fallbackTrace?: DuckDuckGoFallbackTrace) {
    super('bot_challenge', message, {
      retryable: false,
      cooldownMs: 60 * 60 * 1000,
      suggestion: 'Wait for the provider cooldown or use another network runner',
      cause,
    });
    this.name = 'DuckDuckGoFallbackError';
    if (fallbackTrace) this.fallbackTrace = fallbackTrace;
  }
}

// Keep one identity across same-provider representations. The profile is
// derived deterministically from the query, so HTML + Lite fallback share one
// identity while different queries rotate among coherent browser profiles.
const DDG_ROTATE_STATUS = Object.freeze([202, 403, 429] as const);
const MAX_STATUS_ROTATIONS = 1;

/**
 * Extract the real URL from a DuckDuckGo redirect link.
 * DDG wraps result URLs in /l/?uddg=<encoded_url> format (protocol-relative).
 * Also filters out ad redirects (duckduckgo.com/y.js) and non-http URLs.
 * Pattern adapted from gajae-code + ddgs post_extract_results.
 */
function extractRealUrl(href: string): string | null {
  // DDG returns protocol-relative URLs — prepend https: for URL parsing
  const normalized = href.startsWith('//') ? `https:${href}` : href;
  try {
    const url = new URL(normalized);

    // Decode uddg redirect if present
    if (url.pathname === '/l/' && url.searchParams.has('uddg')) {
      const uddg = url.searchParams.get('uddg');
      if (!uddg) return null;
      try {
        const target = new URL(uddg);
        if (target.protocol !== 'http:' && target.protocol !== 'https:') return null;
        if (target.hostname.endsWith('duckduckgo.com')) return null;
        return target.toString();
      } catch {
        return null;
      }
    }

    // Direct URL — reject DDG-internal links (ads, tracking)
    if (url.hostname.endsWith('duckduckgo.com')) return null;
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    return url.toString();
  } catch {
    return null;
  }
}

interface ParseCounters {
  sponsoredDropped: number;
  unsafeLinkDropped: number;
}

interface LiteParseResult extends ParseCounters {
  results: SearchResult[];
  /** A `#challenge-form` page is a challenge failure, never an empty answer. */
  challenge: boolean;
}

/**
 * Search DuckDuckGo using direct HTML parsing (no Python dependency).
 * Uses POST to https://html.duckduckgo.com/html/ (matches DDG's own form + ddgs).
 *
 * The return shape stays a plain result array so existing callers and the
 * provider chain are unaffected; use {@link searchDuckDuckGoHtmlWithTrace} when
 * the fallback lineage has to be auditable.
 */
export async function searchDuckDuckGoHtml(query: string, limit: number = 10, options?: EngineSearchOptions): Promise<SearchResult[]> {
  const { results } = await runDuckDuckGoHtmlSearch(query, limit, options);
  return results;
}

/**
 * Same search as {@link searchDuckDuckGoHtml}, but the answer also carries a
 * trace whenever the HTML channel answered 202 and the Lite representation was
 * tried. Failure and cancellation semantics are identical.
 */
export async function searchDuckDuckGoHtmlWithTrace(
  query: string,
  limit: number = 10,
  options?: EngineSearchOptions,
): Promise<DuckDuckGoSearchOutcome> {
  return runDuckDuckGoHtmlSearch(query, limit, options);
}

/**
 * Shared implementation. Owns the 202 → Lite decision and builds the immutable
 * fallback trace. Soft-error mode swallows failures into an empty answer here;
 * the Lite runner itself always throws so the concrete reason survives for both
 * the error message and the trace.
 */
async function runDuckDuckGoHtmlSearch(
  query: string,
  limit: number,
  options?: EngineSearchOptions,
): Promise<DuckDuckGoSearchOutcome> {
  try {
    const body = new URLSearchParams({
      q: query,
      b: '',         // first-page marker (ddgs pattern)
      l: options?.requestContext?.region ?? 'us-en',
    });
    const signal = withTimeout(options?.signal, 10000);
    // Resolve the browser identity once and hand it to Lite, so both requests
    // of one query are provably the same identity.
    const profile = resolveRequestProfile(query, currentProfileWindowKey());

    const res = await fetchForEngine('duckduckgo', 'https://html.duckduckgo.com/html/', {
      method: 'POST',
      headers: {
        ...profileHeaders(profile, {
          acceptLanguage: options?.requestContext?.acceptLanguage
            ?? 'en-US,en;q=0.9',
          referer: 'https://html.duckduckgo.com/html/',
          kind: 'form',
        }),
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: body.toString(),
      signal,
    }, {
      affinityKey: query,
      rotateOnStatus: DDG_ROTATE_STATUS,
      maxStatusRotations: MAX_STATUS_ROTATIONS,
    });

    // DDG returns 202 for rate limits (gajae-code pattern)
    if (res.status === 202) {
      logger.warn('DDG HTML: Rate limited (HTTP 202), trying the Lite representation once');
      // A caller that cancelled after the 202 must not trigger a Lite request.
      signal.throwIfAborted();
      try {
        const lite = await runDuckDuckGoLiteAttempt(query, limit, options, signal, profile);
        const fallbackOutcome: DuckDuckGoFallbackOutcome = lite.challenge
          ? 'challenge'
          : lite.results.length > 0
            ? 'results'
            : 'empty';
        const fallbackTrace: DuckDuckGoFallbackTrace = Object.freeze({
          primaryChannelStatus: 'http_202',
          fallbackChannel: 'lite',
          fallbackOutcome,
          count: lite.results.length,
          sponsoredDropped: lite.sponsoredDropped,
          unsafeLinkDropped: lite.unsafeLinkDropped,
        });
        logger.info(
          {
            primaryAttempt: fallbackTrace.primaryChannelStatus,
            fallbackAttempt: fallbackTrace.fallbackOutcome,
            count: fallbackTrace.count,
            sponsoredDropped: fallbackTrace.sponsoredDropped,
            unsafeLinkDropped: fallbackTrace.unsafeLinkDropped,
          },
          'DDG same-provider fallback completed',
        );
        return { results: lite.results, fallbackTrace };
      } catch (error) {
        // Preserve the caller's cancellation as an AbortError: it is neither a
        // fallback failure nor a reason to start more work.
        options?.signal?.throwIfAborted();
        signal.throwIfAborted();
        const fallbackMessage = error instanceof Error ? error.message : String(error);
        const fallbackTrace: DuckDuckGoFallbackTrace = Object.freeze({
          primaryChannelStatus: 'http_202',
          fallbackChannel: 'lite',
          fallbackOutcome: 'failed',
          count: 0,
          sponsoredDropped: 0,
          unsafeLinkDropped: 0,
        });
        throw new DuckDuckGoFallbackError(
          `DuckDuckGo fallback failed: HTML HTTP 202 rate limit; Lite: ${fallbackMessage}`,
          error,
          fallbackTrace,
        );
      }
    }

    if (!res.ok) {
      if (options?.throwOnError) throw new Error(`DuckDuckGo HTTP ${res.status}`);
      logger.warn({ status: res.status }, 'DDG HTML: HTTP error');
      return { results: [] };
    }

    const html = await res.text();
    return { results: parseDdgHtml(html, limit, options?.throwOnError === true).results };
  } catch (error) {
    options?.signal?.throwIfAborted();
    if (options?.throwOnError) throw error;
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.includes('timeout')) {
      logger.warn('DDG HTML: Search timed out');
    } else {
      logger.warn({ err: msg.slice(0, 200) }, 'DDG HTML search failed');
    }
    return { results: [] };
  }
}

/**
 * Search DuckDuckGo using its low-bandwidth Lite endpoint.
 * This is one opportunistic alternate representation of the same provider.
 * It must not count as an independent source or as a rate-limit bypass.
 */
export async function searchDuckDuckGoLiteHtml(query: string, limit: number = 10, options?: EngineSearchOptions): Promise<SearchResult[]> {
  try {
    const signal = withTimeout(options?.signal, 10000);
    const profile = resolveRequestProfile(query, currentProfileWindowKey());
    const lite = await runDuckDuckGoLiteAttempt(query, limit, options, signal, profile);
    return lite.results;
  } catch (error) {
    options?.signal?.throwIfAborted();
    if (options?.throwOnError) throw error;
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.includes('timeout')) {
      logger.warn('DDG Lite: Search timed out');
    } else {
      logger.warn({ err: msg.slice(0, 200) }, 'DDG Lite search failed');
    }
    return [];
  }
}

/**
 * The actual Lite request. Always throws on transport/HTTP/challenge problems so
 * the HTML fallback path can record the concrete reason; the public Lite wrapper
 * is responsible for soft-error swallowing. Receives the shared identity so Lite
 * cannot rotate into a different browser than the HTML attempt.
 */
async function runDuckDuckGoLiteAttempt(
  query: string,
  limit: number,
  options: EngineSearchOptions | undefined,
  signal: AbortSignal,
  profile: RequestProfile,
): Promise<LiteParseResult> {
  const body = new URLSearchParams({
    q: query,
    b: '',
    l: options?.requestContext?.region ?? 'us-en',
  });

  const res = await fetchForEngine('duckduckgo', 'https://lite.duckduckgo.com/lite/', {
    method: 'POST',
    headers: {
      ...profileHeaders(profile, {
        acceptLanguage: options?.requestContext?.acceptLanguage
          ?? 'en-US,en;q=0.9',
        referer: 'https://lite.duckduckgo.com/lite/',
        kind: 'form',
      }),
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: body.toString(),
    signal,
  }, {
    affinityKey: query,
    rotateOnStatus: DDG_ROTATE_STATUS,
    maxStatusRotations: MAX_STATUS_ROTATIONS,
  });

  if (res.status === 202) {
    throw new Error('DuckDuckGo Lite HTTP 202 rate limit');
  }

  if (!res.ok) {
    throw new Error(`DuckDuckGo Lite HTTP ${res.status}`);
  }

  const html = await res.text();
  const parsed = parseDdgLiteHtml(html, limit);
  if (parsed.challenge) {
    if (options?.throwOnError) throw new Error('DuckDuckGo Lite captcha challenge');
    logger.warn('DDG Lite: Captcha challenge detected, results will be empty');
  }
  return parsed;
}

interface HtmlParseResult extends ParseCounters {
  results: SearchResult[];
}

function parseDdgHtml(
  html: string,
  limit: number,
  throwOnChallenge = false,
): HtmlParseResult {
  const $ = cheerio.load(html);
  const counters: ParseCounters = { sponsoredDropped: 0, unsafeLinkDropped: 0 };

  // Detect captcha challenge page (searxng pattern)
  if ($('#challenge-form').length > 0) {
    if (throwOnChallenge) throw new Error('DuckDuckGo captcha challenge');
    logger.warn('DDG HTML: Captcha challenge detected, results will be empty');
    return { results: [], ...counters };
  }

  const results: SearchResult[] = [];

  $('.result').each((_, el) => {
    if (results.length >= limit) return false;

    const $el = $(el);

    // Skip sponsored results (DDG marks ads with class "result--ad")
    if ($el.hasClass('result--ad')) {
      counters.sponsoredDropped += 1;
      return;
    }

    const titleLink = $el.find('.result__a').first();
    const rawUrl = titleLink.attr('href') || '';
    const title = titleLink.text().trim();

    // Skip results without title or URL
    if (!title || !rawUrl) return;

    const url = extractRealUrl(rawUrl);

    // Skip if URL extraction failed (ads, internal links, invalid URLs)
    if (!url) {
      counters.unsafeLinkDropped += 1;
      return;
    }

    const snippet = $el.find('.result__snippet').first().text().trim();

    results.push({
      title,
      url,
      snippet,
      source: 'duckduckgo',
      engines: ['duckduckgo'],
    });
  });

  return { results, ...counters };
}

function parseDdgLiteHtml(html: string, limit: number): LiteParseResult {
  const $ = cheerio.load(html);
  const counters: ParseCounters = { sponsoredDropped: 0, unsafeLinkDropped: 0 };

  if ($('#challenge-form').length > 0) {
    return { results: [], challenge: true, ...counters };
  }

  const results: SearchResult[] = [];

  $('.result-link').each((_, el) => {
    if (results.length >= limit) return false;

    const $el = $(el);
    const titleRow = $el.closest('tr');
    let sponsored =
      $el.closest('.result-sponsored').length > 0
      || titleRow.hasClass('result-sponsored')
      || titleRow.find('.result-sponsored').length > 0;
    const titleLink = $el.is('a') ? $el : $el.find('a').first();
    const rawUrl = titleLink.attr('href') || '';
    const title = titleLink.text().trim();
    if (!title || !rawUrl) return;

    const url = extractRealUrl(rawUrl);
    if (!url) {
      // javascript:, DDG-internal and otherwise non-http(s) links are dropped,
      // along with any snippet row that belongs to this title row.
      counters.unsafeLinkDropped += 1;
      return;
    }

    // Lite uses a table layout. Pair the snippet with this result's following
    // rows instead of matching two global arrays by index: ads and malformed
    // rows otherwise shift every later snippet.
    let snippet = '';
    let row = titleRow.next();
    while (row.length > 0 && row.find('.result-link').length === 0) {
      if (
        row.hasClass('result-sponsored')
        || row.find('.result-sponsored').length > 0
      ) {
        sponsored = true;
      }
      const candidate = row.find('.result-snippet').first();
      if (candidate.length > 0) {
        snippet = candidate.text().trim();
        break;
      }
      row = row.next();
    }

    if (sponsored) {
      // The sponsored title row and its following snippet row are both discarded.
      counters.sponsoredDropped += 1;
      return;
    }

    results.push({
      title,
      url,
      snippet,
      source: 'duckduckgo',
      engines: ['duckduckgo'],
    });
  });

  return { results, challenge: false, ...counters };
}
