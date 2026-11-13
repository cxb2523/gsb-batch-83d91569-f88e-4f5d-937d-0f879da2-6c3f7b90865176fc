# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/) as closely
as a CLI toolkit can. A **patch** release means fixes — it does not promise
that every flag and default is frozen, and where a default changes in one the
release notes say so at the top.

## [Unreleased]

### Changed

- CI only: the scheduled canary now starts at 03:27 UTC (Mondays) instead of 05:40, so canaries that share one Scraping Browser profile no longer start at the same time and lock each other out.
- CI only: the whole canary, free and paid jobs alike, now runs weekly (Mondays 05:40 UTC) and on a manual dispatch; the daily schedule is removed.

## [0.2.0] — 2026-10-15

> **Behaviour change:** `--retries 0` is now a usage error (exit 2). It used
> to be accepted and made the page-load loop unreachable, so nothing was
> fetched and the engine reported the browser's own blank page as a result:
> exit 3 or 4 with a 39-byte "capture", in tens of milliseconds. If a
> script of yours passes 0, pass **1**: the flag counts ATTEMPTS, so 1 means
> "try once and do not retry".

> **Behaviour change:** negative and zero values that never made sense are
> now usage errors (exit 2) naming the flag: `--pages` and `--concurrency`
> below 1, and a negative `--delay`, `--retry-delay` or
> `--proxy-block-retries`, in all three engines; a negative `--retries` or
> `--retry-delay` in `scraper_api_client.py`.

> **Behaviour change:** the CSV output now prefixes a cell that begins with
> `=`, `+`, `-`, `@`, a tab, CR or LF with an apostrophe, so a spreadsheet
> reads it as text. Numbers and the JSON output are unchanged, and the
> sidecar records `csv_cells_escaped`.

> **Behaviour change:** a `--locale` that agrees with the market in a typed
> `--url` is now accepted (it was refused, including in the README's own
> example), and `ANDIESWIM_URL` from the environment no longer blocks
> `--query`, `--category` or `--locale`: a typed flag wins over it.

### Fixed

- **The Selenium and pyppeteer engines crashed without a proxy pool.** Any
  page classified blocked, captcha or unknown (and, in pyppeteer, a load
  that failed `--retries` times) reached `pool.current` / `pool.advance` on
  `None` and ended the run with `AttributeError`, exit 1 and no output. Both
  now back off and re-fetch, as the Playwright engine did; a check drives
  each engine's real fetch loop with the driver stubbed and no pool.
- **The one-solve-per-page allowance was bypassed.** The captcha handler
  runs before and after the page is classified, and only the second call
  was counted, so with a stubbed solver a page bought 3 solves with no pool
  and 4 with a three-exit pool against a limit of 1. Both call sites in all
  three engines now go through one `page_flow.SolveBudget` per page,
  checked at the moment of purchase and not reset by retries or rotation.
- **Output writes were not atomic.** A write that failed halfway left a
  truncated `out.json` (12 bytes of invalid JSON where a 780-byte good file
  had been). JSON, CSV and the sidecar are now written to a temp file beside
  the target and renamed over it. A new file gets `0666 & ~umask`, as
  before; an existing file keeps its mode.
- **The credential scan skipped everything in a clone under a directory
  named like a virtualenv** (`~/venv/clone`) and still reported "nothing
  credential-shaped". Exclusions are now judged inside the repository, and
  a scan that read no files fails.
- **`.gitignore` missed real dump shapes**: `X.pageN` from `--dump-html`
  with `--pages`, a bare `dump.html` at the top level, and working
  directories such as `live/` and `out/`.
- **The canary could end green without testing everything.** The Scraping
  Browser job skipped with a notice when its secret was missing; it now
  fails with an error naming `ANDIESWIM_CDP_ENDPOINT`. The listing floor
  tests the parser (rows on all three pages) rather than sitting 10 rows
  under the 150-row cap, and "some products are partially available" is a
  notice, because it measures stock rather than the parser.
- Wording: exit 5 is described as "no rows, the content was never obtained"
  everywhere; the "credentials expire in about a day" claim is removed (the
  lifetime varies); the market count reads 200 everywhere; internal
  section references were replaced by the rule they pointed at, and a check
  keeps them out.

- **`--retries 0` fetched nothing and called it a result.** The load loop is
  `range(1, retries + 1)`, so 0 never runs it and the engine judged
  `about:blank`. Three third-party audits of this family ran exactly that and
  reported a working scraper as broken. `--retries` now goes through
  `page_flow.attempts` in every browser engine (`scraper_api_client.py`
  counts EXTRA attempts, so 0 is legal there); a check reads the source of each
  one and calls the validator, so a new engine declaring the flag with a
  plain int fails the suite.
- **The navigation's HTTP status now reaches the classifier.** `page.goto()`
  returns a Response and all three engines threw it away, so the status was
  never available to `detect_page_state()` — which does know what to do with
  one. A `429` from this edge is 18 bytes of plain text: not one of the
  store's payloads, not a page built out of its assets, so without the status
  it classified as `unknown`, waited the full 30-second readiness budget, and
  then retried — the one response a throttle must not get quickly.
- **`429` and `5xx` are now a `throttled` state of their own**, not a block
  and not an unknown. A throttle wants a wait at the SAME exit; a refusal
  wants a different one, and conflating them spends a rotation and reports
  exit 3 to a reader who needs no proxy at all. The wait honours the edge's
  own `Retry-After` (capped at 120 s), comes out of a budget of its own so it
  does not eat `--retries`, and a run still throttled afterwards reports a
  rate limit rather than an empty catalogue.
  - Selenium is the exception and says so in place: the WebDriver protocol
    exposes no response status, so that engine binds an explicit `None` and
    reaches `throttled` through the edge's own body wording instead — one
    rung weaker, and the only rung it has.

- **The Scraper API path (`scraper_api_client.py`) failed whenever a wait flag
  was given, and never saw the target's status.** Measured 2026-09-23 against
  the live `/tasks/sync` endpoint: `waitFor` sent as a JSON-encoded string
  (what this client sent) is answered HTTP 422 "params.waitFor must be an
  object" and is still billed ($0.0005); sent as an object it is answered
  HTTP 200. It is now an object. And the response's `status` is the API's own
  verdict ("success"), while the target site's HTTP code is `http_code` — the
  client handed `status` onward, so a target 403/503 never reached the page
  classifier. It now reads `http_code`, falling back to `status` only if that
  is an integer. After the fix, one live call with `--wait-text` against the canary collection answered HTTP 200, upstream 200, 180 rows.

- **Donor-repo leftovers removed.** `.gitignore` ignored `montblanc_products.*`
  and `.dockerignore` excluded `bbb_businesses.*`; both now name this repo's
  real default output prefix, `andieswim_products`.
- The issue templates were Etsy's (DataDome advice, an etsy.com example URL,
  a JSON-LD evidence recipe, a tile-overlay option). Rewritten for this store
  from the README's own measurements.
- `captcha_solver.py`'s module docstring and "what is not here" note described
  BBB's Cloudflare gate as this site's. They now state what the README
  measured here: only Shopify's form-submit captcha, nothing on the read path.
- A few comments that said "on BBB" or "BBB has not been measured" as if BBB
  were this site now name `bbb-scraper` as the sibling it is.

- `SECURITY.md` said this project has no releases or version tags; it has
  both. "Supported versions" now names the latest release and `main`.
- `captcha_solver.py`'s docstring pointed at a "No DataDome solver" section
  that does not exist in this repo (it came with the copied core). Removed.

### Changed

- **Confirming a collection exists costs ONE request instead of five.** The
  check used to walk `/collections.json?limit=250` to the end — 834
  collections, four full pages plus the empty one, about a megabyte — on
  every run, including every run that was never going to need the answer.
  Measured 2026-10-13: **7 preflight requests to fetch one page of 5
  products; now 3.**
  `/collections/{handle}.json` answers the same question in 536 bytes and
  answers it better: a walk could only ever report "not among the ones I
  managed to read", while a 404 with zero bytes is the store saying the route
  is not there. `products_count` comes back in the same response, so
  `catalog_count` costs nothing extra.
- **CI tests 3.9 and 3.13**, the oldest and newest supported, rather than 3.9
  and 3.12. The badge claimed 3.13 and nothing tested it.
- **The README's "nothing is gated" is re-scoped and re-dated.** It now says
  what it is entitled to — this store does not gate reads — and records the
  Cloudflare per-colo rate limit a third-party audit met (`429`,
  `local_rate_limited`, `Retry-After: 60`), together with the fact that it
  did not reproduce from here: 30 requests in 5.9 s all 200.

### A note on the audit that prompted this

Its headline was that a run had met a rate limit and reported it as an empty
catalogue. The run had not met one. The audit's command carried `--retries 0`,
which makes the page-load loop `range(1, 1)` — empty — so no navigation
happened at all and the engine judged whatever the browser still held.

What it held was the tail of the preflight: `{"collections":[]}`, the last
page of the collection-index walk. That is **18 bytes**. `local_rate_limited`
is **also exactly 18 bytes**, and the audit's later direct `curl` did see a
`429` — so the two numbers matched and the inference looked confirmed.
Reproduced here with `--dump-html`: the file is `{"collections":[]}`.

Both defects it named are real and both are fixed above, which is the useful
half. `--retries 0` itself is handled separately in #6.

## [0.1.0] — 2026-09-18

First release. Reads **andieswim.com** (Andie Swim) — collection listings,
keyword lookups, and single products with their full size/colour table.

### Added

- **Three local engines** (Playwright, Selenium, pyppeteer) plus
  `scraper_api_client.py` for the 2Captcha Scraping Browser API. All three
  local engines produce byte-identical output on the same collection
  (verified, modulo `scraped_at`) and agree on exit codes and run status.
- **Three modes.** `--mode listing` (default) reads a collection, one row per
  product; `--mode search` reads Shopify's predictive search; `--mode
  product` reads one product as **one row per variant**, with its own sku,
  size, colour, price and availability.
- **34-column output** in JSON and CSV, a `<out>.meta.json` sidecar per run,
  and the family's exit-code contract (`0` ok · `1` crash · `2` usage ·
  `3` blocked · `4` no products · `5` remote API error · `6` partial).
- **200 markets** via `--locale`, with the market recorded on every row.
- `diff_runs.py` for comparing two runs, which refuses to compare runs whose
  modes it cannot line up.

### Measured, and why the shape of this repo is what it is

- **Nothing on the read path is gated.** 2026-09-18, from a datacenter
  address: every route answered HTTP 200 with a browser User-Agent, with
  `curl/8.5.0`, with `python-urllib`, with a crawler UA, and with **no
  User-Agent header at all**. Twenty rapid requests: twenty 200s.
- **The rendered pages carry none of the data.** A collection page's HTML
  holds 5 `/products/` links in 793 KB — all from recommendation widgets —
  and `?page=2` returns the same five; the grid is painted after load by a
  React component. A product page publishes one JSON-LD block and its
  `@type` is `BreadcrumbList`. So the engines read the store's own JSON
  endpoints, which are ungated and richer than any tile.
- **The catalogue is reachable in full.** Walking `/products.json` at
  `limit=250`: 250 + 250 + 250 + 22 = **772 distinct handles**, page 5 empty.
  The store's own `sitemap_products_1.xml` lists 753 product URLs and every
  one of them is in those 772 — a strict superset with zero misses.
- **One collection, fully:** `one-pieces`, 180 rows, `complete`. `title`,
  `price`, `currency`, `image_url`, `handle` and `product_type` at 100%;
  `base_sku` at 91.7%; 81 of 180 reduced (20–75%); 63 products with every
  size available, 116 with some, 1 with none — a split that moves with stock
  (64 / 115 / 1 the same evening), so read it as "most products are partly
  available" rather than as a constant.

### The captcha on this site

Shopify's **storefront-forms hCaptcha**
(`ce_storefront_forms_captcha_hcaptcha.v1.5.3.iife.js`, sitekey
`f06e6c50-85a8-45c8-87d0-21a2b65856fe`) ships on every page the store serves
and is bound to **form submits** — newsletter, contact, account creation. No
listing, product page or JSON route renders one, so a scrape never meets it.
`recaptcha-v3-token` and `g-recaptcha-response` appear in the same bundle as
field names it checks for; no reCAPTCHA is loaded. Nothing else is present.

That is a statement about what the page carries, not about what can be
solved — 2Captcha solves hCaptcha with `HCaptchaTaskProxyless`. This repo
simply has no occasion to call it.

Both `hcaptcha` and `cf-turnstile` are therefore deliberately **absent** from
the bot-challenge marker set: each fires on pages the store plainly serves,
and a marker that matches every good page is worse than no marker.

### Traps handled, each with the measurement behind it

- **`products_count` is not a product count.** The collection index reports
  472 for a collection the storefront serves 180 of, and 3089 for one it
  serves 322 of, against 772 published products in the whole store. It is
  recorded as `catalog_count` with that warning and planned from by nothing.
- **A misspelt collection handle returns HTTP 200 and an empty list**; only
  the HTML route 404s. Every listing run checks the handle against the
  store's own index (830 collections) and reports `unknown_collection`
  rather than `empty`.
- **Prices are set per market, not converted.** One variant: 112.00 USD ·
  195.00 CAD · 110.00 GBP · 175.00 AUD · 130.00 EUR · 21600 JPY. A
  cross-market gap is pricing policy, not arbitrage.
- **An HTML page on this store is timing-dependent.** No HTTP redirect exists
  anywhere, but the theme's client-side geolocation app rewrites the location
  to the visitor's own market after load: `/collections/all` read at
  `domcontentloaded` says USD, and after a full load has become
  `/en-fi/collections/all` and says EUR. This made three engines disagree
  about the currency on one URL. Currency is now read from a JSON document
  instead, and all three agree.
- **Options are not positional.** `option1`/`option2` are Color and Size on
  622 of 665 products, and the store also ships `Rate`, `Length`,
  `Quantity`, `SPF`, `Pack Size`, `Strength` and `Product Size`. They are
  read by the product's own option NAME.
- **`/products/{h}.js` prices in integer cents** while every other route uses
  a decimal string; which one a payload is is detected from the payload, not
  the URL, because a `--dump-html` replay arrives without one.
- **A zero `compare_at_price` means absent, not free.** Predictive search
  writes `"0.00"` for a product that is not on sale.
- **`--sort` does not exist**, and that is a measurement: the JSON endpoint
  ignores `sort_by`. Nothing is capped either, so ordering decides
  `position` and nothing else.

### Not in the output, with the reason

- **`rating` / `review_count`** — the store uses Okendo, whose stars are
  `display:none` in the collection grid and absent from every JSON route
  read here. One third-party request per product would be needed: 180 for
  one collection.
- **`lowest_price_30d`** — the EU Omnibus disclosure a sibling repo needs is
  not published on this store, on any market, including the EU ones.

### Tests and CI

- 528 offline checks in `smoke_test.py`, with fixtures cut from real captures
  and each verified to parse to identical values to its untrimmed original.
  The verification caught two real trimming mistakes while being written.
- `tests.yml` — offline only, on Python 3.9 and 3.12, plus a Docker build,
  a per-engine venv matrix, and a committed-credential scan.
- `canary.yml` — a real 3-page run every morning, **with no credentials**,
  because the listing path needs none and a canary that can pass without one
  should never be gated on one. It runs at `--limit 50` so three pages
  really is three pages: at the default 250 most collections fit in one
  request and pagination would never be exercised.

[Unreleased]: https://github.com/2scraper/andieswim-scraper/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/2scraper/andieswim-scraper/releases/tag/v0.2.0
[0.1.0]: https://github.com/2scraper/andieswim-scraper/releases/tag/v0.1.0
