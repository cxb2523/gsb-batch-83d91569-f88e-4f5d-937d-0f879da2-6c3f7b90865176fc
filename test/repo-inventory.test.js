/**
 * Repository inventory collection: local fake GitHub responses, no network.
 *
 * Covers all-success, mid-run failure + resume, rate limiting, and invalid
 * account names. Also asserts the response contract matches the pure
 * view-model block extracted from dashboard.html.
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const { describe, it, before, after, beforeEach } = require("node:test");
const assert = require("node:assert/strict");

const testRoot = fs.mkdtempSync(path.join(os.tmpdir(), "gitdock-inventory-"));
process.env.GITDOCK_TEST = "1";
process.env.GITDOCK_TEST_ROOT = testRoot;

const server = require("../server");
const inventory = server.repoInventory;
const { api } = require("./helpers/http");

const app = server.app;

// --- Fake GitHub transport ---------------------------------------------------
function jsonResponse(body, { status = 200, headers = {} } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers,
    json: body,
    raw: JSON.stringify(body),
  };
}

function repo(name, owner = "octocat", extra = {}) {
  return {
    name,
    owner: { login: owner },
    private: false,
    fork: false,
    archived: false,
    description: `${name} description`,
    language: "JavaScript",
    updated_at: "2026-01-02T03:04:05Z",
    html_url: `https://github.com/${owner}/${name}`,
    stargazers_count: 3,
    forks_count: 1,
    ...extra,
  };
}

function nextLink(pageUrl, nextPage) {
  const u = new URL(pageUrl);
  u.searchParams.set("page", String(nextPage));
  return `<${u.toString()}>; rel="next"`;
}

/**
 * Fake transport keyed by the Authorization token, because the collector calls
 * /user/repos (the token identifies the account). Records every request URL so
 * tests can prove pages are not re-fetched.
 */
function makeTokenKeyedTransport(handlersByToken) {
  const calls = [];
  function transport({ url, token }) {
    calls.push({ url, token });
    const u = new URL(url);
    const page = parseInt(u.searchParams.get("page") || "1", 10);
    const handlers = handlersByToken[token] || handlersByToken.default;
    const handler = typeof handlers === "function" ? handlers : handlers[page];
    if (typeof handler !== "function") {
      return jsonResponse({ message: "Not Found" }, { status: 404 });
    }
    return handler({ url, page });
  }
  return { transport, calls };
}

function pageOf(items, { link = null } = {}) {
  const headers = {};
  if (link) headers.link = link;
  return jsonResponse(items, { headers });
}

async function createAccount(name, githubUser) {
  const res = await api(app).post("/api/accounts", {
    name,
    githubUser,
    label: `${name} label`,
  });
  assert.equal(res.status, 200, JSON.stringify(res.body));
}

async function removeAccount(name) {
  await api(app).del(`/api/accounts/${name}`);
}

const tokens = {
  alpha: "token-alpha",
  beta: "token-beta",
  gamma: "token-gamma",
};

function setTokens() {
  server.setInventoryTokenResolver(async (account) => tokens[account] || "token-default");
}

describe("repo inventory API", () => {
  before(async () => {
    for (const name of Object.keys(tokens)) await removeAccount(name);
    await createAccount("alpha", "octocat");
    await createAccount("beta", "monalisa");
    await createAccount("gamma", "hubot");
    setTokens();
  });

  after(async () => {
    server.setInventoryTransport(null);
    server.setInventoryTokenResolver(null);
    server.resetInventoryState();
    for (const name of Object.keys(tokens)) await removeAccount(name);
    fs.rmSync(testRoot, { recursive: true, force: true });
  });

  beforeEach(() => {
    server.setInventoryTransport(null);
    server.resetInventoryState();
    setTokens();
  });

  it("collects every account across all pages (all success)", async () => {
    const { transport, calls } = makeTokenKeyedTransport({
      [tokens.alpha]: {
        1: ({ url }) => pageOf([repo("alpha-one"), repo("alpha-two")], { link: nextLink(url, 2) }),
        2: ({ url }) => pageOf([repo("alpha-three")], { link: nextLink(url, 3) }),
        3: () => pageOf([repo("alpha-four")]),
      },
      [tokens.beta]: {
        1: () => pageOf([repo("beta-one", "monalisa")]),
      },
      [tokens.gamma]: {
        1: () => pageOf([repo("gamma-one", "hubot")]),
      },
    });
    server.setInventoryTransport(transport);

    const res = await api(app).get("/api/repos/inventory?reset=1");
    assert.equal(res.status, 200);
    assert.equal(res.body.ok, true);

    const byAccount = Object.fromEntries(res.body.accounts.map((a) => [a.account, a]));
    assert.deepEqual(Object.keys(byAccount).sort(), ["alpha", "beta", "gamma"]);

    assert.equal(byAccount.alpha.status, "success");
    assert.equal(byAccount.alpha.ok, true);
    assert.equal(byAccount.alpha.repoCount, 4);
    assert.deepEqual(
      byAccount.alpha.repos.map((r) => r.name),
      ["alpha-one", "alpha-two", "alpha-three", "alpha-four"]
    );
    assert.equal(byAccount.alpha.pagesFetched, 3);
    assert.equal(byAccount.alpha.complete, true);
    assert.equal(byAccount.alpha.resume, null);
    assert.equal(byAccount.alpha.canRetry, false);

    assert.equal(byAccount.beta.status, "success");
    assert.equal(byAccount.beta.repoCount, 1);
    assert.equal(byAccount.gamma.status, "success");

    assert.equal(res.body.summary.accounts, 3);
    assert.equal(res.body.summary.success, 3);
    assert.equal(res.body.summary.totalRepos, 6);

    // Every repo entry carries the dashboard-facing fields.
    for (const entry of res.body.accounts) {
      for (const field of inventory.INVENTORY_ACCOUNT_FIELDS) {
        assert.ok(field in entry, `missing field ${field} on ${entry.account}`);
      }
      for (const r of entry.repos) {
        assert.equal(typeof r.name, "string");
        assert.equal(typeof r.url, "string");
        assert.equal(typeof r.private, "boolean");
      }
    }

    // Page 2 was fetched exactly once for alpha.
    const alphaPage2 = calls.filter((c) => c.token === tokens.alpha && /[?&]page=2\b/.test(c.url));
    assert.equal(alphaPage2.length, 1);
  });

  it("keeps other accounts going when one fails, then resumes from the saved page", async () => {
    let alphaFailSecondPage = true;
    const { transport, calls } = makeTokenKeyedTransport({
      [tokens.alpha]: {
        1: ({ url }) => pageOf([repo("alpha-one")], { link: nextLink(url, 2) }),
        2: () => {
          if (alphaFailSecondPage) {
            return jsonResponse({ message: "Server Error" }, { status: 500 });
          }
          return pageOf([repo("alpha-two")]);
        },
      },
      [tokens.beta]: {
        1: () => pageOf([repo("beta-one", "monalisa")]),
      },
      [tokens.gamma]: {
        1: () => pageOf([repo("gamma-one", "hubot")]),
      },
    });
    server.setInventoryTransport(transport);

    const first = await api(app).get("/api/repos/inventory?reset=1");
    assert.equal(first.status, 200);
    const byAccount = Object.fromEntries(first.body.accounts.map((a) => [a.account, a]));

    // alpha failed partway: partial with the page it got and the page to retry.
    assert.equal(byAccount.alpha.status, "partial");
    assert.equal(byAccount.alpha.ok, false);
    assert.equal(byAccount.alpha.repoCount, 1);
    assert.equal(byAccount.alpha.reason, "http_error");
    assert.equal(byAccount.alpha.canRetry, true);
    assert.equal(byAccount.alpha.resume.page, 2);
    assert.match(byAccount.alpha.message, /HTTP 500/);

    // beta and gamma still succeeded in the same run.
    assert.equal(byAccount.beta.status, "success");
    assert.equal(byAccount.gamma.status, "success");

    // A failed account is reported before its later page, not dropped.
    const alphaLevelCalls = calls.filter((c) => c.token === tokens.alpha);
    assert.equal(alphaLevelCalls.length, 2);

    // Resume: page 1 must not be re-fetched.
    alphaFailSecondPage = false;
    const resumed = await api(app).post("/api/repos/inventory/retry", { account: "alpha" });
    assert.equal(resumed.status, 200);
    assert.equal(resumed.body.ok, true);
    const entry = resumed.body.account;
    assert.equal(entry.account, "alpha");
    assert.equal(entry.status, "success");
    assert.equal(entry.repoCount, 2);
    assert.deepEqual(entry.repos.map((r) => r.name), ["alpha-one", "alpha-two"]);
    assert.equal(entry.resume, null);
    assert.equal(entry.canRetry, false);

    const resumedPage1 = calls.filter(
      (c) => c.token === tokens.alpha && /[?&]page=1\b/.test(c.url)
    );
    assert.equal(resumedPage1.length, 1, "page 1 should be fetched only once");
  });

  it("marks a rate-limited account, reports when to resume, and avoids re-requesting before then", async () => {
    const resetEpoch = Math.floor(Date.now() / 1000) + 120;
    const { transport, calls } = makeTokenKeyedTransport({
      [tokens.alpha]: {
        1: ({ url }) => pageOf([repo("alpha-one")], { link: nextLink(url, 2) }),
        2: () =>
          jsonResponse(
            { message: "API rate limit exceeded for user ID 1." },
            {
              status: 403,
              headers: {
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": String(resetEpoch),
              },
            }
          ),
      },
      [tokens.beta]: { 1: () => pageOf([repo("beta-one", "monalisa")]) },
      [tokens.gamma]: { 1: () => pageOf([repo("gamma-one", "hubot")]) },
    });
    server.setInventoryTransport(transport);

    const first = await api(app).get("/api/repos/inventory?reset=1");
    assert.equal(first.status, 200);
    const byAccount = Object.fromEntries(first.body.accounts.map((a) => [a.account, a]));

    assert.equal(byAccount.alpha.status, "rate_limited");
    assert.equal(byAccount.alpha.ok, false);
    assert.equal(byAccount.alpha.reason, "rate_limited");
    assert.equal(byAccount.alpha.repoCount, 1);
    assert.equal(byAccount.alpha.retryAfter, new Date(resetEpoch * 1000).toISOString());
    assert.ok(byAccount.alpha.retryAfterSeconds > 0 && byAccount.alpha.retryAfterSeconds <= 121);
    assert.equal(byAccount.alpha.resume.page, 2);
    assert.equal(byAccount.alpha.canRetry, true);

    // The other accounts are unaffected by the rate limit.
    assert.equal(byAccount.beta.status, "success");
    assert.equal(byAccount.gamma.status, "success");

    const callsBefore = calls.length;
    const second = await api(app).get("/api/repos/inventory");
    const secondAlpha = second.body.accounts.find((a) => a.account === "alpha");
    assert.equal(secondAlpha.status, "rate_limited");
    assert.equal(secondAlpha.reason, "rate_limited");
    assert.equal(secondAlpha.repoCount, 1);
    assert.equal(secondAlpha.resume.page, 2);
    assert.ok(secondAlpha.retryAfter);
    // beta/gamma were fully collected, so they are re-scanned; alpha is not
    // requested again while its rate-limit window is still open.
    const alphaCallsAfter = calls
      .slice(callsBefore)
      .filter((c) => c.token === tokens.alpha);
    assert.equal(alphaCallsAfter.length, 0);
  });

  it("skips invalid account names and never sends a request for them", async () => {
    const { transport, calls } = makeTokenKeyedTransport({
      [tokens.alpha]: { 1: () => pageOf([repo("alpha-one")]) },
    });
    server.setInventoryTransport(transport);

    const res = await api(app).get(
      `/api/repos/inventory?reset=1&accounts=${encodeURIComponent("alpha,bad name!,../etc,delta")}`
    );
    assert.equal(res.status, 200);
    const byAccount = Object.fromEntries(res.body.accounts.map((a) => [a.account, a]));

    assert.equal(byAccount.alpha.status, "success");

    const badEntry = res.body.accounts.find((a) => a.reason === "invalid_account_name");
    assert.ok(badEntry, "expected an invalid-account-name entry");
    assert.equal(badEntry.status, "skipped");
    assert.equal(badEntry.repoCount, 0);
    assert.equal(badEntry.canRetry, false);

    // "../etc" fails validation too.
    const traversal = res.body.accounts.find(
      (a) => a.account === "../etc" && a.reason === "invalid_account_name"
    );
    assert.ok(traversal, "expected traversal account to be skipped");
    assert.equal(traversal.status, "skipped");

    // delta is valid but not configured -> skipped for a different reason.
    const unconfigured = res.body.accounts.find((a) => a.account === "delta");
    assert.equal(unconfigured.status, "skipped");
    assert.equal(unconfigured.reason, "not_configured");

    // Only the valid, configured account produced a GitHub request.
    assert.ok(calls.length >= 1);
    for (const call of calls) assert.equal(call.token, tokens.alpha);
  });

  it("drops repo entries whose names fail security validation", async () => {
    const { transport } = makeTokenKeyedTransport({
      [tokens.alpha]: {
        1: () =>
          pageOf([
            repo("good-repo"),
            repo("../escape"),
            repo("ok.too"),
            { name: "", owner: { login: "octocat" } },
            { name: "foreign", owner: { login: "someone-else" } },
          ]),
      },
    });
    server.setInventoryTransport(transport);

    const res = await api(app).get("/api/repos/inventory?reset=1&accounts=alpha");
    const entry = res.body.accounts[0];
    assert.equal(entry.status, "success");
    assert.deepEqual(entry.repos.map((r) => r.name), ["good-repo", "ok.too"]);
    assert.equal(entry.repoCount, 2);
    assert.equal(entry.reposSkipped, 3);
    assert.ok(entry.warnings.includes("invalid_repo_name"));
    assert.ok(entry.warnings.includes("owner_mismatch"));
  });

  it("reports a skipped account when no token is connected", async () => {
    server.setInventoryTransport(() => pageOf([]));
    server.setInventoryTokenResolver(async () => null);
    const res = await api(app).get("/api/repos/inventory?reset=1&accounts=alpha");
    const entry = res.body.accounts[0];
    assert.equal(entry.account, "alpha");
    assert.equal(entry.status, "skipped");
    assert.equal(entry.reason, "auth_required");
    assert.equal(entry.canRetry, false);
  });

  it("exposes every documented account field on success and skipped entries", async () => {
    server.setInventoryTransport(
      makeTokenKeyedTransport({ [tokens.alpha]: { 1: () => pageOf([repo("alpha-one")]) } }).transport
    );
    const ok = await api(app).get("/api/repos/inventory?reset=1&accounts=alpha");
    for (const field of inventory.INVENTORY_ACCOUNT_FIELDS) {
      assert.ok(field in ok.body.accounts[0], `success entry missing ${field}`);
    }
    const skipped = await api(app).get(
      `/api/repos/inventory?reset=1&accounts=${encodeURIComponent("bad name!")}`
    );
    for (const field of inventory.INVENTORY_ACCOUNT_FIELDS) {
      assert.ok(field in skipped.body.accounts[0], `skipped entry missing ${field}`);
    }
  });

  it("rejects retry without an account name", async () => {    const res = await api(app).post("/api/repos/inventory/retry", {});
    assert.equal(res.status, 400);
  });

  it("requires the x-gitdock CSRF header for retry", async () => {
    const request = require("supertest");
    const res = await request(app)
      .post("/api/repos/inventory/retry")
      .set("Host", "127.0.0.1")
      .send({ account: "alpha" });
    assert.equal(res.status, 403);
  });
});

// --- Dashboard contract ------------------------------------------------------
function loadDashboardView() {
  const html = fs.readFileSync(path.join(__dirname, "..", "dashboard.html"), "utf8");
  const start = html.indexOf("// --- INVENTORY VIEW (shared contract)");
  const end = html.indexOf("// --- END INVENTORY VIEW");
  assert.ok(start > 0 && end > start, "inventory view block must exist in dashboard.html");
  const source = html.slice(start, end);
  const factory = new Function(
    `${source}\nreturn { buildInventoryRow, renderInventoryRow, inventoryStatusLabel, inventoryResumeText };`
  );
  return factory();
}

describe("dashboard inventory rendering contract", () => {
  const view = loadDashboardView();
  const escapeAttr = (s) =>
    String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  it("renders one row per account with outcome, repo count, reason, and resume hint", () => {
    const entries = [
      {
        account: "alpha",
        label: "Alpha",
        githubUser: "octocat",
        status: "success",
        ok: true,
        repoCount: 4,
        repos: [],
        pagesFetched: 3,
        reason: null,
        message: null,
        resume: null,
        complete: true,
        canRetry: false,
      },
      {
        account: "beta",
        label: "Beta",
        githubUser: "monalisa",
        status: "partial",
        ok: false,
        repoCount: 1,
        repos: [],
        pagesFetched: 1,
        reason: "http_error",
        message: "GitHub responded with HTTP 500.",
        resume: { page: 2, url: "https://api.github.com/user/repos?page=2" },
        retryAfter: null,
        complete: false,
        canRetry: true,
      },
      {
        account: "gamma",
        label: "Gamma",
        githubUser: "hubot",
        status: "rate_limited",
        ok: false,
        repoCount: 2,
        repos: [],
        pagesFetched: 2,
        reason: "rate_limited",
        message: "GitHub rate limit reached.",
        resume: { page: 3, url: "https://api.github.com/user/repos?page=3" },
        retryAfter: "2026-01-01T00:02:00.000Z",
        retryAfterSeconds: 120,
        complete: false,
        canRetry: true,
      },
      {
        account: "bad name!",
        label: "bad name!",
        status: "skipped",
        ok: false,
        repoCount: 0,
        repos: [],
        pagesFetched: 0,
        reason: "invalid_account_name",
        message: "Account name failed security validation; no request was made.",
        resume: null,
        complete: false,
        canRetry: false,
      },
    ];

    for (const entry of entries) {
      const row = view.buildInventoryRow(entry);
      const html = view.renderInventoryRow(row, escapeAttr);

      // Response -> view model mapping.
      assert.equal(row.account, entry.account);
      assert.equal(row.repoCount, entry.repoCount);
      assert.equal(row.status, entry.status);
      assert.equal(row.canRetry, entry.canRetry);
      assert.equal(row.reason, entry.reason);

      // Render agrees with the entry.
      assert.match(html, new RegExp(`data-inv-row="${escapeAttr(entry.account).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`));
      assert.match(html, new RegExp(`inv-status st-${entry.status}`));
      assert.ok(html.includes(`>${entry.repoCount} <small>(`), "repo count should be rendered");
      if (entry.reason) assert.ok(html.includes(escapeAttr(entry.reason)), "reason code should be rendered");
      if (entry.canRetry) assert.match(html, /class="inv-retry-btn/);
      else assert.ok(!/inv-retry-btn/.test(html), "no retry button for non-retryable rows");
      if (entry.resume) {
        assert.ok(html.includes(`Resume at page ${entry.resume.page}`), "resume page should be rendered");
      }
    }
  });

  it("labels every status the API can return", () => {
    for (const status of Object.values(inventory.STATUS)) {
      assert.notEqual(view.inventoryStatusLabel(status), "Unknown", `missing label for ${status}`);
    }
  });

  it("escapes account names rendered into rows", () => {
    const row = view.buildInventoryRow({
      account: `<img src=x onerror=alert(1)>`,
      label: `<img src=x onerror=alert(1)>`,
      status: "failed",
      repoCount: 0,
      reason: "network_error",
      canRetry: true,
    });
    const html = view.renderInventoryRow(row, escapeAttr);
    assert.ok(!html.includes("<img"), "markup must be escaped");
    assert.ok(html.includes("&lt;img"));
  });

  it("resume hint mentions the retry time for rate-limited entries", () => {
    const row = view.buildInventoryRow({
      account: "gamma",
      status: "rate_limited",
      repoCount: 0,
      retryAfter: "2026-01-01T00:02:00.000Z",
      retryAfterSeconds: 90,
      resume: { page: 2 },
      canRetry: true,
    });
    assert.match(row.resumeText, /Retry after/);
    assert.match(row.resumeText, /Resume at page 2/);
    assert.match(row.resumeText, /90s/);
  });
});

// --- Rate-limit parsing ------------------------------------------------------
describe("rate-limit detection", () => {
  const nowMs = Date.parse("2026-01-01T00:00:00.000Z");

  it("uses Retry-After seconds", () => {
    const info = inventory.parseRateLimitInfo(
      jsonResponse({ message: "You have exceeded a secondary rate limit." }, {
        status: 429,
        headers: { "retry-after": "30" },
      }),
      nowMs
    );
    assert.ok(info);
    assert.equal(info.retryAfterSeconds, 30);
    assert.equal(info.resetAt, new Date(nowMs + 30000).toISOString());
  });

  it("uses the X-RateLimit-Reset epoch when Retry-After is absent", () => {
    const resetEpoch = Math.floor(nowMs / 1000) + 45;
    const info = inventory.parseRateLimitInfo(
      jsonResponse([], {
        status: 403,
        headers: { "x-ratelimit-remaining": "0", "x-ratelimit-reset": String(resetEpoch) },
      }),
      nowMs
    );
    assert.ok(info);
    assert.equal(info.resetAt, new Date(resetEpoch * 1000).toISOString());
    assert.equal(info.retryAfterSeconds, 45);
  });

  it("falls back to a short wait when GitHub sends no usable hint", () => {
    const info = inventory.parseRateLimitInfo(
      jsonResponse({ message: "API rate limit exceeded" }, { status: 403 }),
      nowMs
    );
    assert.ok(info);
    assert.equal(info.retryAfterSeconds, 60);
  });

  it("does not treat a plain 403 as a rate limit", () => {
    const info = inventory.parseRateLimitInfo(
      jsonResponse({ message: "Resource not accessible by personal access token" }, { status: 403 }),
      nowMs
    );
    assert.equal(info, null);
  });
});

// Small self-check that the fake transport's token routing behaves as the
// other tests assume.
describe("fake transport helper self-check", () => {
  it("routes pages by token", async () => {
    const { transport } = makeTokenKeyedTransport({
      "t1": { 1: () => pageOf([repo("x")]) },
    });
    const r = await transport({ url: inventory.reposPageUrl("octocat", 1), token: "t1" });
    assert.equal(r.ok, true);
    assert.equal(r.json.length, 1);
  });
});
