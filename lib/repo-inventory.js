/**
 * Repository inventory collector (shared by the Express API and tests).
 *
 * Walks the configured accounts, pages through GitHub's repo listing, and
 * reports a per-account outcome (success / partial / failed / rate_limited /
 * skipped). Pagination progress is kept in memory so a later request resumes
 * where the previous one stopped instead of re-reading pages that succeeded.
 *
 * The network call is injected as `fetchPage` so tests can serve local fake
 * GitHub responses without touching the network.
 */
const {
  sanitizeAccountName,
  sanitizeRepoName,
  sanitizeOwnerName,
} = require("./security");

const GITHUB_API_ROOT = "https://api.github.com";
const DEFAULT_PER_PAGE = 100;
const DEFAULT_MAX_PAGES = 50;

const STATUS = Object.freeze({
  SUCCESS: "success",
  PARTIAL: "partial",
  FAILED: "failed",
  RATE_LIMITED: "rate_limited",
  SKIPPED: "skipped",
});

const REASON = Object.freeze({
  INVALID_ACCOUNT_NAME: "invalid_account_name",
  INVALID_GITHUB_USER: "invalid_github_user",
  NOT_CONFIGURED: "not_configured",
  INTERNAL_ERROR: "internal_error",
  AUTH_REQUIRED: "auth_required",
  RATE_LIMITED: "rate_limited",
  HTTP_ERROR: "http_error",
  NETWORK_ERROR: "network_error",
  INVALID_REPO_NAME: "invalid_repo_name",
  OWNER_MISMATCH: "owner_mismatch",
});

// Keys the dashboard renderer reads from every account entry. Tests assert the
// API response and dashboard.html agree on this contract.
const INVENTORY_ACCOUNT_FIELDS = Object.freeze([
  "account",
  "label",
  "githubUser",
  "status",
  "ok",
  "repoCount",
  "repos",
  "pagesFetched",
  "pagesTotal",
  "reason",
  "message",
  "resume",
  "retryAfter",
  "retryAfterSeconds",
  "truncated",
  "complete",
  "reposSkipped",
  "warnings",
  "canRetry",
]);

function reposPageUrl(githubUser, page = 1, perPage = DEFAULT_PER_PAGE) {
  const params = new URLSearchParams({
    per_page: String(perPage),
    sort: "updated",
    affiliation: "owner",
    page: String(page),
  });
  return `${GITHUB_API_ROOT}/user/repos?${params.toString()}`;
}

function parseLinkHeader(linkHeader) {
  if (!linkHeader || typeof linkHeader !== "string") return {};
  const out = {};
  const parts = linkHeader.split(",").map((p) => p.trim()).filter(Boolean);
  for (const part of parts) {
    const m = part.match(/^<([^>]+)>\s*;\s*rel="([^"]+)"$/i);
    if (m) out[m[2]] = m[1];
  }
  return out;
}

function pageFromUrl(url, fallback) {
  try {
    const page = parseInt(new URL(url).searchParams.get("page"), 10);
    return Number.isFinite(page) && page > 0 ? page : fallback;
  } catch (e) {
    return fallback;
  }
}

function headerValue(headers, name) {
  if (!headers) return null;
  const key = String(name).toLowerCase();
  const direct = headers[key];
  if (direct !== undefined) return direct;
  for (const k of Object.keys(headers)) {
    if (String(k).toLowerCase() === key) return headers[k];
  }
  return null;
}

/**
 * Detect a GitHub rate-limit response and resolve when the account may retry.
 * Reads Retry-After (seconds or HTTP date), X-RateLimit-Remaining/Reset, and
 * the secondary-rate-limit message body.
 */
function parseRateLimitInfo(res, nowMs = Date.now()) {
  if (!res) return null;
  const status = Number(res.status) || 0;
  const headers = res.headers || {};
  const remaining = headerValue(headers, "x-ratelimit-remaining");
  const retryAfter = headerValue(headers, "retry-after");
  const resetHeader = headerValue(headers, "x-ratelimit-reset");
  const message = res.json && typeof res.json.message === "string" ? res.json.message : "";
  const secondary = (status === 403 || status === 429) && /rate limit/i.test(message);

  const exhausted = remaining !== null && String(remaining).trim() === "0";
  const limited = status === 429 || secondary || (status === 403 && (exhausted || retryAfter !== null));
  if (!limited) return null;

  let resetAtMs = null;
  if (retryAfter !== null && String(retryAfter).trim() !== "") {
    const raw = String(retryAfter).trim();
    if (/^\d+$/.test(raw)) {
      resetAtMs = nowMs + Number(raw) * 1000;
    } else {
      const parsed = Date.parse(raw);
      if (Number.isFinite(parsed)) resetAtMs = parsed;
    }
  }
  if (resetAtMs === null && resetHeader !== null && /^\d+$/.test(String(resetHeader).trim())) {
    resetAtMs = Number(String(resetHeader).trim()) * 1000;
  }
  if (resetAtMs === null || !Number.isFinite(resetAtMs) || resetAtMs <= nowMs) {
    // GitHub does not always send a usable hint; wait a minute before probing.
    resetAtMs = nowMs + 60 * 1000;
  }

  return {
    limited: true,
    resetAtMs,
    resetAt: new Date(resetAtMs).toISOString(),
    retryAfterSeconds: Math.max(0, Math.ceil((resetAtMs - nowMs) / 1000)),
  };
}

function mapRepo(raw, githubUser, warnings) {
  if (!raw || typeof raw !== "object") {
    warnings.add(REASON.INVALID_REPO_NAME);
    return null;
  }
  const name = sanitizeRepoName(raw.name);
  if (!name) {
    warnings.add(REASON.INVALID_REPO_NAME);
    return null;
  }
  const owner = raw.owner && raw.owner.login ? sanitizeOwnerName(raw.owner.login) : null;
  if (raw.owner && raw.owner.login && !owner) {
    warnings.add(REASON.OWNER_MISMATCH);
    return null;
  }
  if (owner && githubUser && owner.toLowerCase() !== githubUser.toLowerCase()) {
    // affiliation=owner should not return foreign repos, but never mix them in.
    warnings.add(REASON.OWNER_MISMATCH);
    return null;
  }
  return {
    name,
    fullName: `${owner || githubUser}/${name}`,
    owner: owner || githubUser,
    private: !!raw.private,
    fork: !!raw.fork,
    archived: !!raw.archived,
    description: raw.description || "",
    language: raw.language || "",
    updatedAt: raw.updated_at || "",
    url: raw.html_url || "",
    stars: Number(raw.stargazers_count) || 0,
    forks: Number(raw.forks_count) || 0,
  };
}

function skippedEntry({ account, label, githubUser, reason, message, warnings }) {
  return {
    account,
    label: label || account,
    githubUser: githubUser || null,
    status: STATUS.SKIPPED,
    ok: false,
    repoCount: 0,
    repos: [],
    pagesFetched: 0,
    pagesTotal: 0,
    reason,
    message: message || null,
    resume: null,
    retryAfter: null,
    retryAfterSeconds: null,
    truncated: false,
    complete: false,
    reposSkipped: 0,
    warnings: warnings ? Array.from(warnings) : [],
    canRetry: false,
  };
}

function createInventoryCollector(options = {}) {
  const getAccounts = options.getAccounts || (() => ({}));
  const getToken = options.getToken || (async () => null);
  const fetchPage = options.fetchPage;
  const now = options.now || (() => Date.now());
  const maxPages = options.maxPages || DEFAULT_MAX_PAGES;
  const perPage = options.perPage || DEFAULT_PER_PAGE;
  const states = new Map(); // accountKey -> pagination state

  function resetState(accountKey) {
    if (accountKey) states.delete(accountKey);
    else states.clear();
  }

  async function resolveToken(accountKey) {
    try {
      const token = await getToken(accountKey);
      return token ? String(token) : null;
    } catch (e) {
      return null;
    }
  }

  async function fetchOnce(args) {
    if (typeof fetchPage !== "function") {
      return { ok: false, status: 0, headers: {}, json: null, error: "No GitHub transport configured" };
    }
    try {
      const res = await fetchPage(args);
      if (!res || typeof res !== "object") {
        return { ok: false, status: 0, headers: {}, json: null, error: "Empty GitHub response" };
      }
      return res;
    } catch (e) {
      return { ok: false, status: 0, headers: {}, json: null, error: e && e.message ? e.message : String(e) };
    }
  }

  function persist(accountKey, state) {
    state.updatedAt = new Date(now()).toISOString();
    states.set(accountKey, state);
  }

  async function collectAccount(rawName, account, { reset } = {}) {
    const accountKey = sanitizeAccountName(rawName);
    if (!accountKey) {
      return skippedEntry({
        account: String(rawName === undefined || rawName === null ? "" : rawName).slice(0, 64),
        reason: REASON.INVALID_ACCOUNT_NAME,
        message: "Account name failed security validation; no request was made.",
      });
    }
    const githubUser = sanitizeOwnerName(account && account.githubUser);
    const label = (account && account.label) || accountKey;
    if (!githubUser) {
      return skippedEntry({
        account: accountKey,
        label,
        githubUser: null,
        reason: REASON.INVALID_GITHUB_USER,
        message: "GitHub username failed security validation; no request was made.",
      });
    }

    if (reset) resetState(accountKey);
    const token = await resolveToken(accountKey);
    if (!token) {
      return skippedEntry({
        account: accountKey,
        label,
        githubUser,
        reason: REASON.AUTH_REQUIRED,
        message: "No GitHub token for this account; add one in the Setup Wizard to list private repos.",
      });
    }
    const current = states.get(accountKey);
    const resuming = !!(current && !current.complete);

    // A previous run already learned when the account may retry. Do not hammer
    // GitHub before that time: report the stored outcome without any request.
    if (current && current.rateLimitedUntilMs && current.rateLimitedUntilMs > now()) {
      return {
        ...skippedEntry({ account: accountKey, label, githubUser, reason: REASON.RATE_LIMITED }),
        status: STATUS.RATE_LIMITED,
        repoCount: current.repos.length,
        repos: current.repos.slice(),
        pagesTotal: current.pagesTotal || 0,
        reposSkipped: current.reposSkipped || 0,
        warnings: Array.from(current.warnings || []),
        reason: REASON.RATE_LIMITED,
        message: "GitHub rate limit is still active for this account.",
        resume: { page: current.nextPage, url: current.nextUrl },
        retryAfter: new Date(current.rateLimitedUntilMs).toISOString(),
        retryAfterSeconds: Math.max(0, Math.ceil((current.rateLimitedUntilMs - now()) / 1000)),
        canRetry: true,
      };
    }

    const warnings = new Set(resuming ? current.warnings || [] : []);
    let repos = resuming ? current.repos.slice() : [];
    // GitHub's updated-sort order can shift between pages while a run is in
    // flight (or between the original run and a resume), so never emit the
    // same repository twice.
    const seenRepoNames = new Set(repos.map((r) => r.name.toLowerCase()));
    let pagesTotal = resuming ? current.pagesTotal || 0 : 0;
    let url = resuming ? current.nextUrl : reposPageUrl(githubUser, 1, perPage);
    let page = resuming ? current.nextPage : 1;
    let pagesFetched = 0;
    let reposSkipped = resuming ? current.reposSkipped || 0 : 0;
    let complete = false;
    let truncated = false;
    let failure = null;
    let rateLimit = null;

    while (pagesFetched < maxPages) {
      const res = await fetchOnce({ url, token, account: accountKey, githubUser });

      // Rate limits can arrive before or after pages have been collected.
      rateLimit = parseRateLimitInfo(res, now());
      if (rateLimit) break;

      if (!res.ok) {
        failure = res.error
          ? { reason: REASON.NETWORK_ERROR, message: res.error, status: 0 }
          : {
              reason: REASON.HTTP_ERROR,
              message: `GitHub responded with HTTP ${res.status || "error"}.`,
              status: res.status || 0,
            };
        break;
      }

      const items = Array.isArray(res.json) ? res.json : [];
      pagesFetched += 1;
      pagesTotal += 1;
      for (const raw of items) {
        const repo = mapRepo(raw, githubUser, warnings);
        if (!repo) { reposSkipped += 1; continue; }
        const dedupeKey = repo.name.toLowerCase();
        if (seenRepoNames.has(dedupeKey)) continue;
        seenRepoNames.add(dedupeKey);
        repos.push(repo);
      }

      const links = parseLinkHeader(res.headers && res.headers.link);
      if (!links.next) {
        complete = true;
        break;
      }
      url = links.next;
      page = pageFromUrl(url, page + 1);
    }

    if (!complete && !failure && !rateLimit) truncated = true; // maxPages reached

    const base = {
      account: accountKey,
      label,
      githubUser,
      repoCount: repos.length,
      repos,
      pagesFetched,
      pagesTotal,
      reposSkipped,
      warnings: Array.from(warnings),
      truncated,
      complete,
    };

    if (rateLimit) {
      persist(accountKey, {
        nextUrl: url,
        nextPage: page,
        repos,
        pagesTotal,
        warnings: Array.from(warnings),
        reposSkipped,
        complete: false,
        rateLimitedUntilMs: rateLimit.resetAtMs,
      });
      return {
        ...base,
        status: STATUS.RATE_LIMITED,
        ok: false,
        reason: REASON.RATE_LIMITED,
        message: "GitHub rate limit reached; collection will resume after the reset time.",
        resume: { page, url },
        retryAfter: rateLimit.resetAt,
        retryAfterSeconds: rateLimit.retryAfterSeconds,
        canRetry: true,
      };
    }

    if (failure) {
      persist(accountKey, {
        nextUrl: url,
        nextPage: page,
        repos,
        pagesTotal,
        warnings: Array.from(warnings),
        reposSkipped,
        complete: false,
        rateLimitedUntilMs: null,
      });
      return {
        ...base,
        status: repos.length > 0 ? STATUS.PARTIAL : STATUS.FAILED,
        ok: false,
        reason: failure.reason,
        message: failure.message,
        resume: { page, url },
        retryAfter: null,
        retryAfterSeconds: null,
        canRetry: true,
      };
    }

    if (truncated) {
      persist(accountKey, {
        nextUrl: url,
        nextPage: page,
        repos,
        pagesTotal,
        warnings: Array.from(warnings),
        reposSkipped,
        complete: false,
        rateLimitedUntilMs: null,
      });
      return {
        ...base,
        status: STATUS.SUCCESS,
        ok: true,
        reason: null,
        message: `Page limit (${maxPages}) reached; more pages are available.`,
        resume: { page, url },
        retryAfter: null,
        retryAfterSeconds: null,
        canRetry: true,
      };
    }

    // Fully collected: drop the state so the next run performs a fresh scan.
    resetState(accountKey);
    return {
      ...base,
      status: STATUS.SUCCESS,
      ok: true,
      reason: null,
      message: null,
      resume: null,
      retryAfter: null,
      retryAfterSeconds: null,
      canRetry: false,
    };
  }

  async function collect(opts = {}) {
    const configured = getAccounts() || {};
    const reset = !!opts.reset;
    const requested = normalizeRequestedAccounts(opts.accounts);
    const entries = [];
    const seen = new Set();

    if (requested) {
      for (const raw of requested) {
        const key = sanitizeAccountName(raw);
        if (!key) {
          entries.push(
            skippedEntry({
              account: String(raw === undefined || raw === null ? "" : raw).slice(0, 64),
              reason: REASON.INVALID_ACCOUNT_NAME,
              message: "Requested account name failed security validation; no request was made.",
            })
          );
          continue;
        }
        if (seen.has(key)) continue;
        seen.add(key);
        const match = Object.entries(configured).find(([name]) => sanitizeAccountName(name) === key);
        if (!match) {
          entries.push(
            skippedEntry({
              account: key,
              reason: REASON.NOT_CONFIGURED,
              message: "Account is not present in config.json.",
            })
          );
          continue;
        }
        entries.push(await safeCollectAccount(match[0], match[1], { reset }));
      }
    } else {
      for (const [rawName, account] of Object.entries(configured)) {
        entries.push(await safeCollectAccount(rawName, account, { reset }));
      }
    }

    return {
      generatedAt: new Date(now()).toISOString(),
      accounts: entries,
      summary: summarize(entries),
    };
  }

  async function safeCollectAccount(rawName, account, opts) {
    try {
      return await collectAccount(rawName, account, opts);
    } catch (e) {
      // One broken account must never abort the whole inventory run.
      const key = sanitizeAccountName(rawName) || String(rawName).slice(0, 64);
      return {
        ...skippedEntry({
          account: key,
          label: (account && account.label) || key,
          githubUser: sanitizeOwnerName(account && account.githubUser),
          reason: REASON.INTERNAL_ERROR,
          message: e && e.message ? e.message : String(e),
        }),
        status: STATUS.FAILED,
        canRetry: true,
      };
    }
  }

  return { collect, resetState, states };
}

function normalizeRequestedAccounts(input) {
  if (input === undefined || input === null) return null;
  const list = Array.isArray(input) ? input : [input];
  if (list.length === 0) return null;
  return list;
}

function summarize(entries) {
  const summary = {
    accounts: entries.length,
    success: 0,
    partial: 0,
    failed: 0,
    rate_limited: 0,
    skipped: 0,
    totalRepos: 0,
    truncated: 0,
  };
  for (const entry of entries) {
    if (Object.prototype.hasOwnProperty.call(summary, entry.status)) summary[entry.status] += 1;
    summary.totalRepos += entry.repoCount || 0;
    if (entry.truncated) summary.truncated += 1;
  }
  return summary;
}

module.exports = {
  STATUS,
  REASON,
  INVENTORY_ACCOUNT_FIELDS,
  DEFAULT_MAX_PAGES,
  DEFAULT_PER_PAGE,
  GITHUB_API_ROOT,
  reposPageUrl,
  parseLinkHeader,
  pageFromUrl,
  parseRateLimitInfo,
  createInventoryCollector,
  summarize,
};
