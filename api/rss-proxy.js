import { getCorsHeaders, isDisallowedOrigin } from './_cors.js';
import { UA_BROWSER } from './_ua.js';

export const config = { runtime: 'edge' };

/**
 * Categories a single feed retrieval can end in. Every failure mode keeps its
 * own label so diagnostics can tell a blocked domain apart from an upstream
 * 5xx, a timeout, or a redirect that left the allowlist.
 */
export const FEED_OUTCOME = Object.freeze({
  SUCCESS: 'success',
  INVALID_URL: 'invalid-url',
  INVALID_PROTOCOL: 'invalid-protocol',
  DOMAIN_NOT_ALLOWED: 'domain-not-allowed',
  REDIRECT_NOT_ALLOWED: 'redirect-not-allowed',
  UPSTREAM_ERROR: 'upstream-error',
  TIMEOUT: 'timeout',
  NETWORK_ERROR: 'network-error',
});

const HTTP_PROTOCOLS = new Set(['http:', 'https:']);
const DEFAULT_TIMEOUT_MS = 12000;
const GOOGLE_NEWS_TIMEOUT_MS = 20000;
const GOOGLE_NEWS_HOST = 'news.google.com';
const MAX_REDIRECTS = 5;

// Browser-like request headers. Many publishers reject the default fetch UA or
// a bare UA; sending a realistic header set recovers the feeds that only do
// lightweight filtering. (Feeds behind full bot-protection / datacenter-IP
// blocks still fail — those are handled by emptyFeed() below.)
const FEED_HEADERS = {
  'User-Agent': UA_BROWSER,
  'Accept': 'application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5',
  'Accept-Language': 'en-US,en;q=0.9',
  'Cache-Control': 'no-cache',
  'Pragma': 'no-cache',
  'Sec-Fetch-Dest': 'document',
  'Sec-Fetch-Mode': 'navigate',
  'Sec-Fetch-Site': 'none',
  'Sec-Fetch-User': '?1',
  'Upgrade-Insecure-Requests': '1',
};

// A well-formed, empty RSS document. Returned with HTTP 200 whenever an
// upstream feed is unreachable (4xx/5xx, blocked, moved, or timed out) so the
// client parses zero items instead of logging a failed request on every load.
// The real upstream status is preserved in the X-Feed-Status header.
const EMPTY_RSS =
  '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>unavailable</title><description>Feed temporarily unavailable</description></channel></rss>';

// Allowed RSS feed domains for security
export const ALLOWED_DOMAINS = [
  'feeds.bbci.co.uk',
  'www.theguardian.com',
  'feeds.npr.org',
  'news.google.com',
  'www.aljazeera.com',
  'rss.cnn.com',
  'hnrss.org',
  'feeds.arstechnica.com',
  'www.theverge.com',
  'www.cnbc.com',
  'feeds.marketwatch.com',
  'www.defenseone.com',
  'breakingdefense.com',
  'www.bellingcat.com',
  'techcrunch.com',
  'huggingface.co',
  'www.technologyreview.com',
  'rss.arxiv.org',
  'export.arxiv.org',
  'www.federalreserve.gov',
  'www.sec.gov',
  'www.whitehouse.gov',
  'www.state.gov',
  'www.defense.gov',
  'home.treasury.gov',
  'www.justice.gov',
  'tools.cdc.gov',
  'www.fema.gov',
  'www.dhs.gov',
  'www.thedrive.com',
  'krebsonsecurity.com',
  'finance.yahoo.com',
  'thediplomat.com',
  'venturebeat.com',
  'foreignpolicy.com',
  'www.ft.com',
  'openai.com',
  'www.reutersagency.com',
  'feeds.reuters.com',
  'rsshub.app',
  'www.cfr.org',
  'www.csis.org',
  'www.politico.com',
  'www.brookings.edu',
  'layoffs.fyi',
  'www.defensenews.com',
  'www.foreignaffairs.com',
  'www.atlanticcouncil.org',
  // Tech variant domains
  'www.zdnet.com',
  'www.techmeme.com',
  'www.darkreading.com',
  'www.schneier.com',
  'rss.politico.com',
  'www.anandtech.com',
  'www.tomshardware.com',
  'www.semianalysis.com',
  'feed.infoq.com',
  'thenewstack.io',
  'devops.com',
  'dev.to',
  'lobste.rs',
  'changelog.com',
  'seekingalpha.com',
  'news.crunchbase.com',
  'www.saastr.com',
  'feeds.feedburner.com',
  // Additional tech variant domains
  'www.producthunt.com',
  'www.axios.com',
  'github.blog',
  'githubnext.com',
  'mshibanami.github.io',
  'www.engadget.com',
  'news.mit.edu',
  'dev.events',
  // VC blogs
  'www.ycombinator.com',
  'a16z.com',
  'review.firstround.com',
  'www.sequoiacap.com',
  'www.nfx.com',
  'www.aaronsw.com',
  'bothsidesofthetable.com',
  'www.lennysnewsletter.com',
  'stratechery.com',
  // Regional startup news
  'www.eu-startups.com',
  'tech.eu',
  'sifted.eu',
  'www.techinasia.com',
  'kr-asia.com',
  'techcabal.com',
  'disrupt-africa.com',
  'lavca.org',
  'contxto.com',
  'inc42.com',
  'yourstory.com',
  // Funding & VC
  'pitchbook.com',
  'www.cbinsights.com',
  // Accelerators
  'www.techstars.com',
  // Middle East & Regional News
  'english.alarabiya.net',
  'www.arabnews.com',
  'www.timesofisrael.com',
  'www.scmp.com',
  'kyivindependent.com',
  'www.themoscowtimes.com',
  'feeds.24.com',
  'feeds.capi24.com',  // News24 redirect destination
  // International Organizations
  'news.un.org',
  'www.iaea.org',
  'www.who.int',
  'www.cisa.gov',
  'www.crisisgroup.org',
  // Think Tanks & Research (Added 2026-01-29)
  'rusi.org',
  'www.rusi.org',
  'warontherocks.com',
  'www.aei.org',
  'responsiblestatecraft.org',
  'www.fpri.org',
  'jamestown.org',
  'www.chathamhouse.org',
  'ecfr.eu',
  'www.gmfus.org',
  'www.wilsoncenter.org',
  'www.lowyinstitute.org',
  'www.mei.edu',
  'www.stimson.org',
  'www.cnas.org',
  'carnegieendowment.org',
  'www.rand.org',
  'fas.org',
  'www.armscontrol.org',
  'www.nti.org',
  'thebulletin.org',
  'www.iss.europa.eu',
  // Economic & Food Security
  'www.fao.org',
  'worldbank.org',
  'www.imf.org',
  // Additional
  'news.ycombinator.com',
  // DeFi / Crypto News — Tier 1
  'www.coindesk.com',
  'www.theblock.co',
  'decrypt.co',
  'cointelegraph.com',
  'bitcoinmagazine.com',
  'blockworks.co',
  'thedefiant.io',
  'www.dlnews.com',
  'blockworks.com',
  // DeFi / Crypto News — Tier 2
  'bitcoinist.com',
  'cryptoslate.com',
  'www.newsbtc.com',
  'crypto.news',
  'cryptopotato.com',
  'ambcrypto.com',
  'beincrypto.com',
  'u.today',
  'dailyhodl.com',
  'coingape.com',
  'forkast.news',
  'unchainedcrypto.com',
  'protos.com',
  // DeFi & Web3
  'defirate.com',
  'dailydefi.org',
  'rekt.news',
  'defipulse.com',
  'www.defipulse.com',
  'newsletter.banklesshq.com',
  'defillama.com',
  'blog.yearn.finance',
  'uniswap.org',
  'aave.mirror.xyz',
  'blog.makerdao.com',
  'dappradar.com',
  // Research & Analysis
  'messari.io',
  'thedefireport.substack.com',
  'cryptobriefing.com',
  'insights.glassnode.com',
  'members.delphidigital.io',
  'www.paradigm.xyz',
  'a16zcrypto.com',
  // Security & Auditing
  'slowmist.medium.com',
  'www.certik.com',
  'blog.openzeppelin.com',
  'blog.trailofbits.com',
  'samczsun.com',
  'immunefi.medium.com',
  // L1 / L2 Ecosystems
  'solana.com',
  'near.org',
  'blog.cosmos.network',
  'blog.sui.io',
  'iohk.io',
  'polkadot.network',
  'l2beat.com',
  'optimism.mirror.xyz',
  'arbitrum.io',
  'polygon.technology',
  'starkware.medium.com',
  'zksync.mirror.xyz',
  'base.mirror.xyz',
  // Institutional & ETF
  'www.coinbase.com',
  'www.binance.com',
  'www.galaxy.com',
  'panteracapital.com',
  'multicoin.capital',
  'grayscale.com',
  'bitwiseinvestments.com',
  'www.vaneck.com',
  'blog.coinshares.com',
  'ark-invest.com',
  '21shares.com',
  // Developer & Tech
  'www.alchemy.com',
  'blog.chain.link',
  'blog.infura.io',
  'thegraph.com',
  // Mining & Energy
  'hashrateindex.com',
  'compassmining.io',
  // On-Chain Analytics
  'blog.kaiko.com',
  'coinmetrics.substack.com',
  'blog.thetie.io',
  'woobull.com',
  'cryptoquant.com',
  // Stablecoin & Derivatives
  'www.circle.com',
  'tether.to',
  'insights.deribit.com',
  // Bitcoin Ecosystem
  'lightning.engineering',
  'stacker.news',
  // Substacks & Mirrors
  'thedailygwei.substack.com',
  'wublock.substack.com',
  'medium.com',
  // NFT & Gaming
  'nftnow.com',
  'nftplazas.com',
  'playtoearn.net',
  // Mainstream Finance Crypto
  'www.bloomberg.com',
  'www.reuters.com',
  'www.forbes.com',
  'feeds.a.dj.com',
  'www.finextra.com',
  'www.pymnts.com',
  // Ethereum
  'weekinethereumnews.com',
  'etherscan.io',
  'blog.ethereum.org',
  'vitalik.eth.limo',
  'ethhub.substack.com',
  'blog.optimism.io',
  // Solana
  'www.helius.dev',
  'www.jito.network',
  'phantom.app',
];

function toErrorMessage(error) {
  if (error instanceof Error) return error.message;
  return String(error || 'unknown error');
}

function isAllowedFeedUrl(url) {
  return HTTP_PROTOCOLS.has(url.protocol) && ALLOWED_DOMAINS.includes(url.hostname);
}

/**
 * Request one URL with a hard timeout. `redirect: 'manual'` keeps every hop
 * under our control so the allowlist can be re-checked before each request.
 */
async function requestWithTimeout(url, fetchImpl, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetchImpl(url, {
      headers: FEED_HEADERS,
      redirect: 'manual',
      signal: controller.signal,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      const timeoutError = new Error(`timed out after ${timeoutMs}ms`);
      timeoutError.name = 'TimeoutError';
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function buildOutcome(feedUrl, startedAt, fields) {
  return {
    // Requested address (kept raw) plus the address the last request was
    // actually sent to.
    feedUrl,
    url: feedUrl,
    category: fields.category,
    ok: fields.category === FEED_OUTCOME.SUCCESS,
    // Upstream HTTP status when a response was received, otherwise null.
    status: fields.status ?? null,
    // Human-readable reason for non-success outcomes (status text for the
    // upstream-error case, the exception message otherwise).
    error: fields.error ?? null,
    redirected: Boolean(fields.redirected),
    finalUrl: fields.finalUrl ?? feedUrl,
    redirectChain: fields.redirectChain ?? [],
    durationMs: Math.max(0, Math.round(Date.now() - startedAt)),
    // Raw XML body on success so callers do not need to re-fetch.
    body: fields.body ?? null,
  };
}

/**
 * Retrieve a single feed and return a structured outcome describing exactly
 * what happened. This is the export tests (and other callers) should use; the
 * default handler below only translates an outcome into the HTTP contract.
 *
 * @param {string} feedUrl
 * @param {{ fetchImpl?: typeof fetch, timeoutMs?: number }} [options]
 * @returns {Promise<{
 *   feedUrl: string, url: string,
 *   category: string, ok: boolean,
 *   status: number | null, error: string | null,
 *   redirected: boolean, finalUrl: string, redirectChain: string[],
 *   durationMs: number, body: string | null,
 * }>}
 */
export async function fetchFeedOutcome(feedUrl, options = {}) {
  const startedAt = Date.now();
  const requestedUrl = typeof feedUrl === 'string' ? feedUrl : '';
  const fail = (category, fields = {}) =>
    buildOutcome(requestedUrl, startedAt, { category, ...fields });

  if (!requestedUrl) {
    return fail(FEED_OUTCOME.INVALID_URL, { error: 'missing feed url' });
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(requestedUrl);
  } catch (error) {
    return fail(FEED_OUTCOME.INVALID_URL, { error: `invalid feed url: ${toErrorMessage(error)}` });
  }

  // Security: Only allow http/https protocols (prevent file://, data://, etc.)
  if (!HTTP_PROTOCOLS.has(parsedUrl.protocol)) {
    return fail(FEED_OUTCOME.INVALID_PROTOCOL, {
      error: `protocol not allowed: ${parsedUrl.protocol}`,
    });
  }

  // Security: Check if domain is allowed
  if (!ALLOWED_DOMAINS.includes(parsedUrl.hostname)) {
    return fail(FEED_OUTCOME.DOMAIN_NOT_ALLOWED, {
      error: `domain not allowed: ${parsedUrl.hostname}`,
    });
  }

  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  // Google News is slow - use longer timeout
  const timeoutMs = Number.isFinite(options.timeoutMs) && options.timeoutMs > 0
    ? options.timeoutMs
    : (requestedUrl.includes(GOOGLE_NEWS_HOST) ? GOOGLE_NEWS_TIMEOUT_MS : DEFAULT_TIMEOUT_MS);

  let currentUrl = parsedUrl.href;
  let redirected = false;
  const redirectChain = [];

  for (let hop = 0; hop <= MAX_REDIRECTS; hop += 1) {
    let response;
    try {
      response = await requestWithTimeout(currentUrl, fetchImpl, timeoutMs);
    } catch (error) {
      const category = error?.name === 'TimeoutError'
        ? FEED_OUTCOME.TIMEOUT
        : FEED_OUTCOME.NETWORK_ERROR;
      return fail(category, {
        error: toErrorMessage(error),
        redirected,
        finalUrl: currentUrl,
        redirectChain: [...redirectChain],
      });
    }

    const status = typeof response.status === 'number' ? response.status : null;

    if (status !== null && status >= 300 && status < 400) {
      let location = null;
      try {
        location = response.headers.get('location');
      } catch {
        location = null;
      }
      if (!location) {
        return fail(FEED_OUTCOME.UPSTREAM_ERROR, {
          status,
          error: `upstream redirect without location (HTTP ${status})`,
          redirected,
          finalUrl: currentUrl,
          redirectChain: [...redirectChain],
        });
      }

      let redirectUrl;
      try {
        redirectUrl = new URL(location, currentUrl);
      } catch (error) {
        return fail(FEED_OUTCOME.REDIRECT_NOT_ALLOWED, {
          status,
          error: `invalid redirect location: ${toErrorMessage(error)}`,
          redirected: true,
          finalUrl: location,
          redirectChain: [...redirectChain, location],
        });
      }

      redirected = true;
      redirectChain.push(redirectUrl.href);

      // The redirect target must pass the same protocol + allowlist checks as
      // the original request. Anything else is treated as unavailable.
      if (!isAllowedFeedUrl(redirectUrl)) {
        return fail(FEED_OUTCOME.REDIRECT_NOT_ALLOWED, {
          status,
          error: `redirect target not allowed: ${redirectUrl.href}`,
          redirected: true,
          finalUrl: redirectUrl.href,
          redirectChain: [...redirectChain],
        });
      }

      if (hop === MAX_REDIRECTS) {
        return fail(FEED_OUTCOME.NETWORK_ERROR, {
          status,
          error: `too many redirects (>${MAX_REDIRECTS})`,
          redirected: true,
          finalUrl: currentUrl,
          redirectChain: [...redirectChain],
        });
      }

      currentUrl = redirectUrl.href;
      continue;
    }

    // Any non-OK upstream status (403 bot-block, 404 dead feed, 5xx) degrades
    // to an empty feed so it does not surface as a failed request client-side.
    if (status === null || status < 200 || status >= 300) {
      return fail(FEED_OUTCOME.UPSTREAM_ERROR, {
        status,
        error: `upstream returned HTTP ${status}`,
        redirected,
        finalUrl: currentUrl,
        redirectChain: [...redirectChain],
      });
    }

    try {
      const body = await response.text();
      return buildOutcome(requestedUrl, startedAt, {
        category: FEED_OUTCOME.SUCCESS,
        status,
        redirected,
        finalUrl: currentUrl,
        redirectChain: [...redirectChain],
        body,
      });
    } catch (error) {
      return fail(FEED_OUTCOME.NETWORK_ERROR, {
        status,
        error: `failed reading upstream body: ${toErrorMessage(error)}`,
        redirected,
        finalUrl: currentUrl,
        redirectChain: [...redirectChain],
      });
    }
  }

  // The loop always returns inside; this keeps the function total.
  return fail(FEED_OUTCOME.NETWORK_ERROR, {
    error: `too many redirects (>${MAX_REDIRECTS})`,
    redirected,
    finalUrl: currentUrl,
    redirectChain: [...redirectChain],
  });
}

function emptyFeed(corsHeaders, outcome) {
  const headers = {
    'Content-Type': 'application/xml',
    'Cache-Control': 'public, max-age=120, s-maxage=120, stale-while-revalidate=60',
    'X-Feed-Status': outcome.category,
    'X-Feed-Duration-Ms': String(outcome.durationMs),
    ...corsHeaders,
  };
  if (typeof outcome.status === 'number') {
    headers['X-Feed-Upstream-Status'] = String(outcome.status);
  }
  if (outcome.redirected) {
    headers['X-Feed-Final-Url'] = outcome.finalUrl;
  }
  return new Response(EMPTY_RSS, {
    status: 200,
    headers,
  });
}

function jsonError(corsHeaders, status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders },
  });
}

export default async function handler(req, options = {}) {
  const corsHeaders = getCorsHeaders(req, 'GET, OPTIONS');

  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const requestUrl = new URL(req.url);
  const feedUrl = requestUrl.searchParams.get('url');

  if (!feedUrl) {
    return jsonError(corsHeaders, 400, 'Missing url parameter');
  }

  const outcome = await fetchFeedOutcome(feedUrl, options);

  if (outcome.category === FEED_OUTCOME.INVALID_PROTOCOL) {
    return jsonError(corsHeaders, 400, 'Invalid protocol');
  }
  if (outcome.category === FEED_OUTCOME.DOMAIN_NOT_ALLOWED) {
    return jsonError(corsHeaders, 403, 'Domain not allowed');
  }

  if (outcome.category === FEED_OUTCOME.SUCCESS) {
    const headers = {
      'Content-Type': 'application/xml',
      'Cache-Control': 'public, max-age=300, s-maxage=300, stale-while-revalidate=60',
      'X-Feed-Status': outcome.category,
      'X-Feed-Duration-Ms': String(outcome.durationMs),
      ...corsHeaders,
    };
    if (outcome.redirected) {
      headers['X-Feed-Final-Url'] = outcome.finalUrl;
    }
    return new Response(outcome.body, {
      status: 200,
      headers,
    });
  }

  if (outcome.category === FEED_OUTCOME.TIMEOUT || outcome.category === FEED_OUTCOME.NETWORK_ERROR) {
    console.warn('RSS proxy error:', feedUrl, outcome.category, outcome.error);
  }

  return emptyFeed(corsHeaders, outcome);
}
