import { parse as parseHtml } from "node-html-parser";

import { Browser, type BrowserOptions } from "./core/browser";
import { HttpClient, type HttpClientOptions } from "./core/http";
import type { Tab, WaitUntil } from "./core/tab";
import { htmlToMarkdown, type MarkdownOptions } from "./content/markdown";
import { extractMetadata, type PageMetadata } from "./content/metadata";

// One call, cheapest tier first:
//   http    — browserless request (curl-impersonate for a real Chrome TLS
//             fingerprint when configured). Milliseconds, no Chrome.
//   browser — the stealth Chrome (no Runtime.enable, coherent persona). Runs
//             the page's JavaScript; needed for SPAs and soft bot checks.
//   stealth — same browser plus a behavioral warm-up and an interactive
//             Cloudflare Turnstile solve when a challenge is on the page.
// strategy "auto" escalates only when a tier looks blocked or empty, and the
// result reports which tier produced it, so you can see what each URL costs.

export type ScrapeFormat = "markdown" | "html" | "metadata" | "links" | "screenshot";
export type ScrapeTier = "http" | "browser" | "stealth";

export type ScrapeOptions = {
  url: string;
  // Default ["markdown", "metadata"].
  formats?: ScrapeFormat[];
  // "auto" (default) = http → browser → stealth. Pick one tier to pin it.
  strategy?: "auto" | ScrapeTier;
  // Reuse a running Browser (recommended for many URLs). When omitted, one is
  // launched with `browserOptions` and closed before returning.
  browser?: Browser;
  browserOptions?: BrowserOptions;
  // Options for the HTTP tier (e.g. { curlImpersonate: "curl_chrome131" }). With
  // a reused `browser`, its persona + proxy are applied automatically.
  http?: Partial<HttpClientOptions>;
  markdown?: MarkdownOptions & { includeIframes?: boolean };
  waitUntil?: WaitUntil;
  timeoutMs?: number;
};

export type ScrapeAttempt = { tier: ScrapeTier; ok: boolean; reason?: string; ms: number };

export type ScrapeResult = {
  url: string;
  tier: ScrapeTier;
  // HTTP status of the http tier; null when the page came from the browser.
  status: number | null;
  title: string;
  markdown?: string;
  html?: string;
  metadata?: PageMetadata;
  links?: Array<{ text: string; href: string }>;
  screenshot?: Buffer;
  attempts: ScrapeAttempt[];
};

export class ScrapeError extends Error {
  attempts: ScrapeAttempt[];

  constructor(message: string, attempts: ScrapeAttempt[]) {
    super(message);
    this.name = "ScrapeError";
    this.attempts = attempts;
  }
}

const BLOCK_STATUS = new Set([401, 403, 407, 429, 503]);
// The Turnstile widget marker: a widget embedded in a real page stays in its
// markup after it is solved, so it only counts while the challenge is unsolved.
// The challenge-platform markers below it mark the interstitial itself (in any
// language) and always count.
const TURNSTILE_MARKER = /challenges\.cloudflare\.com|cf-turnstile/i;
const CHALLENGE_MARKERS = [
  /<title>\s*(just a moment|attention required|access denied|verifying you are human|please wait|security check)/i,
  TURNSTILE_MARKER,
  /_cf_chl_opt|cf-browser-verification|cf_chl_/i,
  /captcha-delivery\.com|geo\.captcha-delivery|datadome/i,
  /perimeterx|px-captcha|_pxhd/i,
  /\/_Incapsula_Resource|incap_ses_/i,
  /g-recaptcha|h-captcha|hcaptcha\.com\/1\/api/i,
];

// Reasons that still return the page: it is short, or it may still be gated.
const isSoftReason = (reason: string) => reason.startsWith("almost no content") || reason.startsWith("solved challenge");

// Why a fetched page should not be trusted as the real content, or null.
export function detectBlock({ status, html, markdown, challengeSolved = false }: { status?: number | null; html: string; markdown?: string; challengeSolved?: boolean }): string | null {
  if (status != null && BLOCK_STATUS.has(status)) {
    return `HTTP ${status}`;
  }
  // Only look at the head + the start of the body: markers deep in a real
  // article (e.g. a blog post about Cloudflare) must not count.
  const text = markdown ?? htmlToMarkdown(html, { mainContent: false, links: "none", images: false }).markdown;
  const head = html.slice(0, 20_000);
  let solvedWidget = false;
  for (const marker of CHALLENGE_MARKERS) {
    if (marker.test(head) && text.length < 2_000) {
      if (challengeSolved && marker === TURNSTILE_MARKER) {
        solvedWidget = true;
        continue;
      }
      return `challenge page (${marker.source.split("|")[0].replace(/\\/g, "").slice(0, 40)})`;
    }
  }
  if (text.trim().length < 200 && (/<noscript[^>]*>[^<]*(enable|need|requires?)[^<]*javascript/i.test(html) || /<div id="(root|app|__next)">\s*<\/div>/i.test(html))) {
    return "needs JavaScript (empty app shell)";
  }
  // A short page that keeps a solved widget may be the real page (nowsecure.nl)
  // or a site's own Turnstile gate still waiting for a submit; the markup can't
  // tell them apart, so the page is returned but flagged.
  if (solvedWidget) {
    return "solved challenge still on the page (may be a gate)";
  }
  if (text.trim().length < 200) {
    return "almost no content";
  }
  return null;
}

export async function scrape(options: ScrapeOptions): Promise<ScrapeResult> {
  const formats = new Set<ScrapeFormat>(options.formats ?? ["markdown", "metadata"]);
  const strategy = options.strategy ?? "auto";
  const attempts: ScrapeAttempt[] = [];
  const timeout = options.timeoutMs ?? 30_000;

  let tiers: ScrapeTier[] = strategy === "auto" ? ["http", "browser", "stealth"] : [strategy];
  if (formats.has("screenshot")) {
    // A screenshot needs a rendered page.
    tiers = tiers.filter((tier) => tier !== "http");
  }

  // ---- http tier ----
  if (tiers.includes("http")) {
    const started = Date.now();
    try {
      const client = options.browser
        ? options.browser.createHttpClient({ timeoutMs: timeout, ...options.http })
        : new HttpClient({ proxy: options.browserOptions?.proxy ?? null, timeoutMs: timeout, ...options.http });
      const response = await client.get(options.url);
      const md = htmlToMarkdown(response.body, { baseUrl: response.url, ...options.markdown });
      const reason = detectBlock({ status: response.status, html: response.body, markdown: md.markdown });
      attempts.push({ tier: "http", ok: !reason, reason: reason ?? undefined, ms: Date.now() - started });

      if (!reason || tiers.length === 1) {
        if (reason && !isSoftReason(reason)) {
          throw new ScrapeError(`scrape(${options.url}) http tier: ${reason}`, attempts);
        }
        return {
          url: response.url,
          tier: "http",
          status: response.status,
          title: md.title,
          ...(formats.has("markdown") ? { markdown: md.markdown } : {}),
          ...(formats.has("html") ? { html: response.body } : {}),
          ...(formats.has("metadata") ? { metadata: extractMetadata(response.body, response.url) } : {}),
          ...(formats.has("links") ? { links: md.links } : {}),
          attempts,
        };
      }
    } catch (error) {
      if (error instanceof ScrapeError) {
        throw error;
      }
      attempts.push({ tier: "http", ok: false, reason: String((error as Error)?.message ?? error), ms: Date.now() - started });
      if (tiers.length === 1) {
        throw new ScrapeError(`scrape(${options.url}) http tier failed: ${String((error as Error)?.message ?? error)}`, attempts);
      }
    }
  }

  // ---- browser / stealth tiers (one tab, escalated in place) ----
  const owns_browser = !options.browser;
  const browser = options.browser ?? new Browser({ headless: true, ...options.browserOptions });
  let tab: Tab | null = null;

  try {
    tab = await browser.newTab();
    let loaded = false;
    let challengeSolved = false;

    for (const tier of tiers.filter((t) => t !== "http")) {
      const started = Date.now();
      try {
        if (!loaded) {
          await tab.goto({ url: options.url, waitUntil: options.waitUntil ?? "load", timeout });
          loaded = true;
          // Give client-side rendering a moment to settle.
          await tab.waitForFunction({ expression: "document.readyState === 'complete'", timeout: 5_000 }).catch(() => undefined);
          await tab.sleep({ milliseconds: 500 });
        }

        if (tier === "stealth") {
          await tab.ambientActivity({ durationMs: 1_200 });
          if (await tab.turnstilePresent()) {
            const solve = await tab.solveTurnstile({ timeoutMs: Math.min(timeout, 30_000) });
            challengeSolved = Boolean(solve?.solved);
          }
          // A solved challenge usually redirects to the real page.
          await tab.waitForNavigation({ timeout: 8_000 }).catch(() => undefined);
          await tab.sleep({ milliseconds: 800 });
        }

        const html = await tab.content();
        const md = await tab.markdown({ ...options.markdown });
        const reason = detectBlock({ html, markdown: md.markdown, challengeSolved });
        attempts.push({ tier, ok: !reason, reason: reason ?? undefined, ms: Date.now() - started });

        // Escalate to stealth only for a real block: a short page that rendered
        // fine in the browser is just a short page.
        const blocked = Boolean(reason) && !isSoftReason(reason!);
        const is_last = tier === tiers[tiers.length - 1];
        if (blocked && !is_last) {
          continue;
        }
        // A challenge / error page is never returned as content; a page that is
        // merely short is (some pages are tiny).
        if (reason && !isSoftReason(reason)) {
          throw new ScrapeError(`scrape(${options.url}) blocked on every tier: ${attempts.map((a) => `${a.tier}: ${a.reason}`).join("; ")}`, attempts);
        }

        return {
          url: md.url,
          tier,
          status: null,
          title: md.title,
          ...(formats.has("markdown") ? { markdown: md.markdown } : {}),
          ...(formats.has("html") ? { html } : {}),
          ...(formats.has("metadata") ? { metadata: await tab.metadata() } : {}),
          ...(formats.has("links") ? { links: md.links } : {}),
          ...(formats.has("screenshot") ? { screenshot: await tab.screenshot({ fullPage: true }) } : {}),
          attempts,
        };
      } catch (error) {
        if (error instanceof ScrapeError) {
          throw error;
        }
        attempts.push({ tier, ok: false, reason: String((error as Error)?.message ?? error), ms: Date.now() - started });
      }
    }

    throw new ScrapeError(`scrape(${options.url}) failed on every tier: ${attempts.map((a) => `${a.tier}: ${a.reason}`).join("; ")}`, attempts);
  } finally {
    if (tab) {
      await browser.closeTab(tab).catch(() => undefined);
    }
    if (owns_browser) {
      await browser.close().catch(() => undefined);
    }
  }
}

// ---------------------------------------------------------------------------
// Batched pagination
// ---------------------------------------------------------------------------

// Hard backstop so a misconfigured run can't walk a site forever. Callers can
// raise or lower it per run via maxPages.
export const DEFAULT_MAX_PAGES = 20;

// How the next page is discovered:
//   * { nextLinkSelector } — the current page's HTML is parsed (no new block
//     detection: the same detectBlock used by scrape() applies) and the first
//     element matching the CSS selector supplies the next URL via its href
//     (or data-href). When the selector matches nothing, the batch ends with
//     "no next page"; when it points at an already scraped URL, with
//     "duplicate page".
//   * { urlTemplate } — URLs are generated by replacing "{page}" in the
//     template with 2, 3, 4 … (page 1 is always `url`). The run continues
//     until maxPages or a failed page.
export type PaginationConfig =
  | { nextLinkSelector: string; urlTemplate?: never }
  | { urlTemplate: string; nextLinkSelector?: never };

export type PaginatedScrapeOptions = PaginationConfig & {
  // First page of the batch; its page number is always 1.
  url: string;
  // Upper bound on the number of pages fetched. Defaults to DEFAULT_MAX_PAGES.
  maxPages?: number;
  // Formats produced for every page. Defaults to ["markdown", "metadata"],
  // matching scrape().
  formats?: ScrapeFormat[];
  // Remaining options are passed straight through to each scrape() call.
  strategy?: "auto" | ScrapeTier;
  browser?: Browser;
  browserOptions?: BrowserOptions;
  http?: Partial<HttpClientOptions>;
  markdown?: MarkdownOptions & { includeIframes?: boolean };
  waitUntil?: WaitUntil;
  timeoutMs?: number;
};

// Why the batch stopped. Every value names the rule that fired:
//   "reached max pages (<n>)" | "no next page" | "duplicate page (<url>)" |
//   "page <n> failed: <reason>"
export type PaginatedStoppedReason = string;

export type PaginatedPage = {
  page: number;
  // The URL requested for this page.
  url: string;
  ok: boolean;
  // Present on successful pages; absent when the page failed.
  actualUrl?: string;
  tier?: ScrapeTier;
  title?: string;
  markdown?: string;
  html?: string;
  metadata?: PageMetadata;
  links?: Array<{ text: string; href: string }>;
  screenshot?: Buffer;
  // Same per-tier attempt log scrape() reports, so a caller can see whether a
  // page was blocked (detectBlock reason on an attempt) or simply short.
  attempts?: ScrapeAttempt[];
  // detectBlock() verdict for a page scrape() still returned (a soft block such
  // as "almost no content"). Null means the page looked like real content.
  blocked?: string | null;
  // Present only when ok is false.
  reason?: string;
};

export type PaginatedScrapeResult = {
  pages: PaginatedPage[];
  stoppedReason: PaginatedStoppedReason;
};

// Turns a thrown scrape() failure into a reason string. ScrapeError carries the
// per-tier attempts, whose reasons originate in detectBlock(); everything else
// is a transport/runtime failure and keeps its error message.
function failureReason(error: unknown): string {
  if (error instanceof ScrapeError) {
    const attemptReasons = error.attempts.map((attempt) => attempt.reason).filter((reason): reason is string => Boolean(reason));
    if (attemptReasons.length > 0) {
      return attemptReasons.join("; ");
    }
  }
  return String((error as Error)?.message ?? error);
}

// Finds the next-page URL inside a page's HTML via a CSS selector. The matched
// element may be an <a href> or any element carrying data-href. Returns null
// when the selector matches nothing / has no usable href ("no next page").
function findNextLink(html: string, selector: string, baseUrl: string): string | null {
  const root = parseHtml(html, { comment: false, lowerCaseTagName: true });
  const element = root.querySelector(selector);
  if (!element) {
    return null;
  }
  const rawHref = element.getAttribute("href") ?? element.getAttribute("data-href");
  if (!rawHref || !rawHref.trim()) {
    return null;
  }
  return new URL(rawHref, baseUrl).toString();
}

// A URL counts as already scraped ignoring its fragment only — query strings
// and trailing slashes are distinct pages.
function normalizePageUrl(url: string): string {
  const parsed = new URL(url);
  parsed.hash = "";
  return parsed.toString();
}

export async function scrapePaginated(options: PaginatedScrapeOptions): Promise<PaginatedScrapeResult> {
  const maxPages = options.maxPages ?? DEFAULT_MAX_PAGES;
  if (!Number.isInteger(maxPages) || maxPages < 1) {
    throw new Error(`scrapePaginated: maxPages must be a positive integer, got ${String(options.maxPages)}`);
  }
  const urlTemplate = options.urlTemplate;
  const nextLinkSelector = options.nextLinkSelector;
  if (urlTemplate !== undefined && !urlTemplate.includes("{page}")) {
    throw new Error('scrapePaginated: urlTemplate must contain a "{page}" placeholder, e.g. "https://site.test/list?p={page}"');
  }
  // Fail fast on malformed input instead of halfway through a batch.
  new URL(options.url);
  if (urlTemplate !== undefined) {
    new URL(urlTemplate.replaceAll("{page}", "2"));
  }

  const callerFormats = options.formats ?? ["markdown", "metadata"];
  // Selector mode needs the raw HTML to find the next link, and every page is
  // run through detectBlock(); ask scrape() for html internally and strip it
  // back out of the result unless the caller asked for it.
  const internalFormats: ScrapeFormat[] = callerFormats.includes("html") ? callerFormats : [...callerFormats, "html"];
  const keepHtml = callerFormats.includes("html");

  const pages: PaginatedPage[] = [];
  const seen = new Set<string>([normalizePageUrl(options.url)]);
  let currentUrl = options.url;
  let pageNumber = 1;

  while (pageNumber <= maxPages) {
    let result: ScrapeResult;
    try {
      result = await scrape({
        url: currentUrl,
        formats: internalFormats,
        ...(options.strategy !== undefined ? { strategy: options.strategy } : {}),
        ...(options.browser !== undefined ? { browser: options.browser } : {}),
        ...(options.browserOptions !== undefined ? { browserOptions: options.browserOptions } : {}),
        ...(options.http !== undefined ? { http: options.http } : {}),
        ...(options.markdown !== undefined ? { markdown: options.markdown } : {}),
        ...(options.waitUntil !== undefined ? { waitUntil: options.waitUntil } : {}),
        ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
      });
    } catch (error) {
      // A single failed page never aborts the batch with an exception: record
      // it and end the run by rule, keeping every page collected so far.
      const reason = failureReason(error);
      pages.push({ page: pageNumber, url: currentUrl, ok: false, reason, attempts: error instanceof ScrapeError ? error.attempts : undefined });
      return { pages, stoppedReason: `page ${pageNumber} failed: ${reason}` };
    }

    // detectBlock stays the single anti-bot verdict — the one scrape() itself
    // uses. On a returned (non-thrown) page it can only flag soft reasons.
    const blockReason = detectBlock({
      status: result.status,
      html: result.html ?? "",
      ...(result.markdown !== undefined ? { markdown: result.markdown } : {}),
    });

    const page: PaginatedPage = {
      page: pageNumber,
      url: currentUrl,
      ok: true,
      actualUrl: result.url,
      tier: result.tier,
      title: result.title,
      ...(result.markdown !== undefined ? { markdown: result.markdown } : {}),
      ...(keepHtml && result.html !== undefined ? { html: result.html } : {}),
      ...(result.metadata !== undefined ? { metadata: result.metadata } : {}),
      ...(result.links !== undefined ? { links: result.links } : {}),
      ...(result.screenshot !== undefined ? { screenshot: result.screenshot } : {}),
      attempts: result.attempts,
      blocked: blockReason,
    };
    pages.push(page);
    seen.add(normalizePageUrl(result.url));

    if (pageNumber === maxPages) {
      return { pages, stoppedReason: `reached max pages (${maxPages})` };
    }

    let nextUrl: string | null;
    if (urlTemplate !== undefined) {
      // Template mode: page 1 is `url`; pages 2+ come from the template.
      nextUrl = urlTemplate.replaceAll("{page}", String(pageNumber + 1));
    } else {
      nextUrl = findNextLink(result.html ?? "", nextLinkSelector as string, result.url);
      if (nextUrl === null) {
        return { pages, stoppedReason: "no next page" };
      }
      if (seen.has(normalizePageUrl(nextUrl))) {
        return { pages, stoppedReason: `duplicate page (${nextUrl})` };
      }
    }

    seen.add(normalizePageUrl(nextUrl));
    currentUrl = nextUrl;
    pageNumber += 1;
  }

  // Unreachable in practice: the maxPages check inside the loop returns first.
  return { pages, stoppedReason: `reached max pages (${maxPages})` };
}
