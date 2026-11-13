# Flippa Scraper — Online Businesses for Sale and Asking Prices in Python

[![release](https://img.shields.io/github/v/release/2scraper/flippa-scraper?label=release)](https://github.com/2scraper/flippa-scraper/releases)
[![tests](https://github.com/2scraper/flippa-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/2scraper/flippa-scraper/actions/workflows/tests.yml)
[![canary](https://github.com/2scraper/flippa-scraper/actions/workflows/canary.yml/badge.svg)](https://github.com/2scraper/flippa-scraper/actions/workflows/canary.yml)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![engines](https://img.shields.io/badge/engines-playwright%20%7C%20pyppeteer%20%7C%20selenium%20%7C%20scraper--api-lightgrey)](#four-ways-to-run-it)
[![runs without an account](https://img.shields.io/badge/runs%20without%20an%20account-yes-brightgreen)](#what-the-paid-products-buy-you)

**Flippa scraper** — an open-source (MIT) Python tool that reads flippa.com search and category listing pages and writes online businesses for sale — asking price, monthly profit and revenue, profit multiple, asset type and industry — to JSON or CSV. On 2026-10-15 the Playwright engine, from a datacentre address with no proxy and no key, returned 150 listings across 3 pages of `?filter[property_type]=saas`. Use it to build a dataset of businesses for sale, or compare two runs with the included diff tool to see what changed.

A working scraper for **flippa.com** listing pages — the marketplace for
buying and selling online businesses, websites, apps and domains. Any
`/search` URL with any combination of `filter[...]` parameters, and the
category shortcuts (`/websites`, `/apps`, `/domains`, `/buy/sitetype/saas`).
Four engines, one parser, JSON and CSV out.

Part of the [2scraper](https://github.com/2scraper) family of open-source,
single-site scrapers.

**Status: live-verified on 2026-10-15 after a site rebuild.** Flippa rebuilt
its search page between 2026-09-28 and 2026-09-29 (the embedded listing JSON
and the Angular cards this repo read are gone), and every run from then until
this release returned 0 listings — the canary, then daily, was red throughout. The
parser now reads the server-rendered cards: the Playwright engine ran against
`?filter[property_type]=saas` on 2026-10-15 from a datacentre address with no
proxy and no key and returned **150 listings across 3 pages, exit 0,
`status: complete`**. The other engines share the parser but were not re-run
after the rebuild; their figures below are from 2026-09-19 and say so. The
offline suite needs no network; how many checks it runs depends on which
optional engines are installed, and it prints the count with any skips beside
it rather than promising a fixed number.

## What it extracts

One row per listing, 33 columns. The interesting ones:

| Column | What it is |
|---|---|
| `sku` | Flippa's own numeric listing id — the key `diff_runs.py` compares on |
| `url` | The listing's own link: `https://flippa.com/<id>-<slug>` |
| `title` | The card's heading, e.g. `SaaS | Internet` for a confidential listing, or the business's name |
| `description` | The seller's own one-line summary |
| `price` / `currency` | Asking price (the starting price or current bid on an auction). `null` for an "Open to Offers" listing, whose card shows only a price GUIDE range, and for a partial-equity sale. Currency is read off the card — USD on `/search`, EUR on `/fr/search` — never defaulted |
| `original_price` / `discount_pct` | Present when the price was reduced. The discount is **computed from the two prices**, not read off the site's "Reduced 28%" badge |
| `asset_type` / `industry` | SaaS, Ecommerce, YouTube Channel… / Internet, Health and Beauty… |
| `monthly_profit` / `monthly_revenue` | Per month. **Profit can be negative** and is reported that way. The card prints both ABBREVIATED ("USD $51.7K"), so they carry three significant figures, not the exact amount |
| `profit_multiple` | Flippa's own multiple as printed ("4.1x"), `null` where the card shows none |
| `age_text` / `country` | As the site writes them: "12 years", "FL, United States" |
| `bid_count` | "21 bids" on an auction card; `null` otherwise |
| `broker_name` / `managed_by_flippa` | The broker named on the card, and whether it says "Brokered by Flippa" |
| `page` / `position` | Where the row sat in the run. The PAIR is unique — `position` restarts at 1 on every page |
| `price_source` | `dom` — read off the card. Runs from before 2026-09-29 say `state` or `state+dom` |

`monetization`, `revenue_multiple`, `status`, `sale_method`, `sponsored`,
`editors_choice`, `confidential`, `verified_listing` and `image_url` are still
in the schema so a consumer's columns do not move, but the rebuilt card does
not show them and they are `null` on every row read since 2026-09-29.

Plus `source`, `scraped_at`, `category` (your `--category` label or one taken
from the URL) and `image_url`. The full row is in
[`sample_output.json`](sample_output.json), cut from the real run above.

Three columns the rest of this family has are deliberately **absent** here:
`brand` (Flippa sells businesses, not branded goods), `rating` (a listing card
shows none) and `in_stock` (not a concept on a marketplace for businesses).

## How it reads the page

Flippa's search page is **server-rendered**: all 50 listing cards of a page
are in the first HTTP response, with no JavaScript needed to produce them.
There is no structured listing data on it — no product JSON-LD, and since
2026-09-29 no embedded listing JSON either — so the cards are the source:

* A card is `<li id="listing-NNN">`. Its boundary is that id, not a CSS class
  (Flippa's are Tailwind build output). The page also carries filter counters
  with ids like `listing-category-count-saas`, which is why the id is matched
  as `listing-` plus digits, never as a bare prefix.
* The price column is read below the card's rule, never from the whole card:
  the key-data grid above it carries money too ("USD $51.7K" monthly profit).
* Key-data labels are translated on `/fr/` and `/es/` ("Bénéfice mensuel",
  "Beneficio mensual"); the parser has the three languages the site
  publishes, and a label it does not know leaves its column `null`.
* The site's own count — "Show 676 results" in the filter panel — tells an
  empty query ("Show 0 results", exit 4) apart from a page past the end of a
  listing (no cards, count above zero: the listing is complete) and from a
  page that was not a listing at all.

## Pagination

Pages are addressed by URL, `?page=N` — the parameter the site's own next
link uses (`?page=2&pagination=true`). Measured 2026-10-14 on a 676-match
filter: 50 per page, page 14 holds the last 26, page 15 answers HTTP 200 with
no cards. **Every run verifies the convention**: page 2 is fetched on its own
and checked for listings page 1 did not have. If it has none, the run stops
and reports `partial` with `stop_reason: pagination_not_addressable` rather
than a complete-looking result holding one page. That check exists because an
earlier version of this repo used a page parameter the site ignored and
returned one page of rows, reporting success, on every multi-page run.

`--concurrency N` fetches pages 3..N through N workers, each with its own
browser and its own proxy exit, and only after that check has passed.

## Four ways to run it

| Script | Engine | Live status |
|---|---|---|
| `playwright_scraper.py` | **Playwright** (recommended) | 2026-10-15, after the rebuild: 150 listings / 3 pages / exit 0 |
| `puppeteer_scraper.py` | pyppeteer | 2026-09-19, before the rebuild: 50 listings / 2 pages, identical data. Needs `PYPPETEER_EXECUTABLE_PATH` on modern macOS — its bundled Chromium is from 2018 |
| `selenium_scraper.py` | Selenium + Chrome | 2026-09-19, before the rebuild: 50 listings / 2 pages, identical data. Two page-1 loads timed out at 60s first and the retry carried it |
| `scraper_api_client.py` | 2Captcha Scraper API (no local browser) | 2026-09-19, before the rebuild: 50 listings / 2 pages, identical data. Two billable tasks at $0.0005 each |
| any of the three, with `--cdp-endpoint` | 2Captcha Scraping Browser API | 2026-09-19, before the rebuild: 75 listings / 3 pages, identical data. `Captcha.setAutoSolve` enabled on connect; `--concurrency` refused, one live connection per profile |

On 2026-09-19 all three browser engines produced **byte-identical rows**
(`scraped_at` aside) for the same 50 listings. They share the parser, the page-state
policy and the exit-code mapping precisely so that stays true.

## Install and run

```bash
pip install -r requirements.txt                    # core: bs4 + requests
pip install -r requirements-playwright.txt         # then ONE engine
playwright install chromium

python3 playwright_scraper.py \
  --url "https://flippa.com/search?filter%5Bproperty_type%5D=saas" \
  --pages 3 --out saas_listings --format both
```

Install exactly one engine per environment: playwright and pyppeteer pin
incompatible `pyee` versions, and pyppeteer and selenium collide on
`urllib3`. Use a virtualenv per engine if you want more than one.

**The pyppeteer engine carries a known-vulnerable urllib3.** pyppeteer
requires `urllib3<2`, and seven published urllib3 advisories (as of
2026-10-15) are fixed only in 2.x — among them one where a cross-origin
redirect can forward `Proxy-Authorization` to the new host
(GHSA-qccp-gfcp-xxvc), and one where the TLS settings meant for an HTTPS
proxy and for the target server can be mixed up (PYSEC-2026-4175). In that
engine's virtualenv `requests` uses the same urllib3, so the proxy preflight
and the captcha API calls do too. The weekly `pip-audit` job ignores exactly
those seven, by ID; prefer Playwright if you run with proxy credentials.

Credentials live in `.env`, never on a command line — a secret in `argv` is
readable by anything that can run `ps` and lands in shell history:

```bash
cp .env.example .env
python3 env_config.py     # says what was picked up, without printing it
```

## What the paid products buy you

**State it plainly: you do not need any of them for this site.** Every number
in this README was measured with no API key, no proxy and no Scraping Browser
— including plain `curl` fetches on 2026-10-14 that each came back with all 50
cards of a page. flippa.com is behind Cloudflare, but it served an ordinary
request from an ordinary connection every time it was asked, on 2026-09-19
and again on 2026-10-14/15 (including from GitHub's runners).

What the four 2Captcha products (one key, billed separately) actually buy —
each line says whether it was run against the live API on 2026-09-19:

* **Proxies** (`--proxy`, `--proxy-file`) — volume from many addresses, and a
  specific country. `--proxy-rotate per-page` relaunches the browser on each
  new exit, because carrying a session across addresses is a stronger signal
  than either address alone. **Verified:** a 2-page run through
  `eu.proxy.2captcha.com:2334` returned 50 listings, exit 0, with the
  credentials passed through Playwright's own fields and only `host:port` in
  the browser's argv.
* **Captcha solving** (`--twocaptcha-key`) — for the challenge this site does
  configure: `/signup` carries a real Cloudflare Turnstile widget. **Verified
  twice:** the static detector read the live sitekey, `TurnstileTaskProxyless`
  returned a token in about 5 seconds, and the token was written into the
  page's own response field. Nothing submits the form. Listing pages render no
  challenge at all, which is why the default `--solve-captcha when-blocked`
  refuses to pay when the listings are already readable — and why
  `--solve-captcha always` on a form page buys a token a scraper has no use
  for.
* **The Scraper API** (`scraper_api_client.py`) — no browser at all.
  **Verified:** two billable tasks at $0.0005 each returned 50 listings whose
  every column matched the browser engines' (2026-09-19, before the site's
  rebuild; the rebuilt page is server-rendered, so the browserless path reads
  the same cards).
* **The Scraping Browser API** (`--cdp-endpoint`) — no browser infrastructure
  of your own, a consistent device identity, a chosen exit country, and
  `Captcha.setAutoSolve`, which clears a challenge inside the browser before
  this code gets a turn. **Verified:** 75 listings across 3 pages, identical
  to the local-browser run bar three rows' `position`, with auto-solve
  enabled on connect and `--concurrency` correctly refused (one live
  connection per profile). Copy the CDP URL from the Browser API dashboard —
  a URL assembled by hand from the documented shape answers
  `401 deny_no_user`, which is how this was learned.
* **Fingerprints** (`--fingerprint`) — a device identity for a browser you
  launched yourself. **Not verified:** the same key answered **HTTP 403** at
  `/fingerprint/random`; fingerprints are a separate subscription. Rather than
  imply it works, `fingerprint_client.py --explain` prints field by field what
  it could and could not apply, and the 403 now says exactly that. Since
  0.2.0 a scraper run with `--fingerprint` stops there with **exit 5** and
  that reason, before any page is fetched, instead of crashing with exit 1
  (re-measured 2026-09-28: still 403).

## Exit codes

A pipeline branches on these, and every engine produces the same one for the
same situation.

| Code | Means |
|---|---|
| 0 | listings written |
| 1 | crash |
| 2 | bad usage, including an exit that fails its preflight — one small request through the proxy before any browser starts, so a rotated password costs a second rather than three minutes of timeouts |
| 3 | blocked before parsing — a challenge, a refusal status, or a page not built out of Flippa's own assets |
| 4 | zero listings, and the run can show the listing is empty: the site says the query matches nothing, or the listing ran out |
| 5 | zero listings because the content was never obtained: a remote API error, a navigation timeout, a dead proxy, a page that never painted, or a page of listings the parser could not read |
| 6 | partial: some pages were gathered, then the run stopped early |

Every run that writes output also writes `<out>.meta.json`. Two fields there
answer two different questions, and conflating them is how a short run gets
read as a whole catalogue:

| Field | Question it answers |
|---|---|
| `status` | did the run get the pages it went for? `complete`, `partial`, `failed` |
| `coverage` | were those pages the whole listing? `exhaustive`, `window`, or null for a run that did not finish |

A `--pages 3` run of a 27-page listing is `complete` **and** a `window`: every
listing past page 3 exists and was never looked at. `diff_runs.py` refuses
outright to compare runs that are not both `complete`, and for `window` runs
it still compares prices but labels the added/removed halves as
entered-window / left-window, keeping them out of `--fail-on-change`.

The sidecar also carries **which** pages failed by number, `pages_missing`
for pages that were requested and never came back at all, the site's own
`total_results` as of the first and the last page with `catalog_mutated` when
those differ, `rows_before_dedupe` and `duplicate_skus_across_pages`, and
whether pagination was addressable.

A run is `complete` only when its stop reason says so **and** every requested
page is accounted for. The page count is checked independently of the stop
reason: an engine that loses a page without noticing still cannot publish a
complete-looking run.

## Traps that look like bugs

Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the full list with the
measurements. The four that cost the most time:

* **A "3-page" run returning one page of rows** is pagination, and this repo
  now detects it rather than reporting success — see above.
* **`profit_multiple` does not always equal `price ÷ (12 × monthly_profit)`.**
  It is Flippa's own figure as printed, the card rounds the monthly profit,
  and it is reported as published rather than "corrected".
* **`monthly_profit` and `monthly_revenue` are rounded** — the card prints
  "USD $51.7K", and that is the precision the column has.
* **`<captcha-widgets>` is not Flippa's.** Captures taken through the
  Scraping Browser carry an empty `<captcha-widgets>` on every page, and it
  reads like the site's own captcha mount. It is the 2Captcha autosolver
  EXTENSION's markup: loading the same pages in a plain Chromium with no
  extensions (2026-09-21) finds zero occurrences. What the site actually
  ships is Cloudflare's own `<div class="cf-turnstile" data-sitekey="…">`,
  on `/signup` and not on listing pages. Detecting a FILLED mount is still
  useful — it means the extension found a challenge — and treating the bare
  element as a marker would report every run as challenged.
* **Solving a FORM's captcha buys nothing here.** A token in a form field is
  spent at submit time, and this scraper never submits anything. A reload
  after injecting would throw it away, so a page that was not blocked is no
  longer reloaded — see `handle_captcha_if_present`.

## Locales

Flippa's own `hreflang` set publishes three: `/search`, `/fr/search` and
`/es/search`. A localised path is not a translation layer on the same
numbers — **it converts the prices**. Measured on 2026-09-19, listing
`12857417` on the same day:

| URL | price | currency | age | industry |
|---|---|---|---|---|
| `/search` | 436,829 | USD | `3 years` | Health and Beauty |
| `/fr/search` | 380,546 | EUR | `3 années` | Santé et beauté |

Both rows are correct for the page they came from. The `currency` column
follows the page rather than defaulting, each engine says which localisation
it is scraping before it starts, and the locale segment is not mistaken for a
category label. Do not mix two locales in one dataset.

The key-data labels are localised too ("Industrie", "Ancienneté", "Profit"),
which is why the profit is read by the SHAPE of its value rather than by an
English label. The rendered-card fallback path is the exception — it still
keys `industry` and `monetization` on the English words, and the suite pins
that limitation rather than half-guarding it.

## Testing

```bash
python3 smoke_test.py      # no network, ~2s; prints passed/failed/skipped
pytest -q                  # the same run, through the pytest entry point
```

A check whose input is missing is reported as `SKIP` and counted separately —
never asserted as a pass, which would inflate the total with checks that never
ran. The suite asserts values on real captures rather than coverage, checks
that no requested page can go missing without the run reporting itself
partial, that a page classified as carrying listings but parsing to nothing is
a parse failure rather than the end of the listing, that a scraped title
cannot become a spreadsheet formula, that output files are published
atomically, that
both parse paths agree, that every engine exposes the same flags, that each
engine imports its driver at module level, that every call into a shared
module binds against its real signature, that no name is used undefined, that
the Dockerfile copies what the entrypoint imports, and that nothing
credential-shaped or personal is committed. `.github/workflows/canary.yml`
runs one real 3-page scrape a week (Mondays, plus on demand), because
pagination is never exercised by a one-page run.

## Guides

- [How to run the 2scraper scrapers: setup, proxies, exit codes and access modes](https://2captcha.com/h/how-to-run-2scraper-open-source-scrapers) — installation, `.env`, `.meta.json` for the whole family.

## Related scrapers

Same CLI conventions, same output contract (one row per item, JSON or CSV, a `.meta.json` sidecar and shared exit codes):

- [G2 scraper](https://github.com/2scraper/g2-scraper) — Categories, product pages and pricing pages
- [Google Play scraper](https://github.com/2scraper/googleplay-scraper) — Apps, installs, rating histograms and unbounded reviews…
- [Better Business Bureau scraper](https://github.com/2scraper/bbb-scraper) — BBB search and category listings with no key or proxy, plus…
- [Just Join IT scraper](https://github.com/2scraper/justjoin-scraper) — Polish IT job offers with real salaries, seniority, skill…
- [Mercor scraper](https://github.com/2scraper/mercor-scraper) — AI-talent marketplace: contract roles, rates, eligibility…
- [Wellfound scraper](https://github.com/2scraper/wellfound-scraper) — Startup jobs from Wellfound with salary and equity ranges…

All scrapers: [github.com/2scraper](https://github.com/2scraper) · Need another site? [Open a request](https://github.com/2scraper/.github/issues/new?title=%5BScraper%20request%5D%20)

## Licence

MIT. Scrapes public listing pages only: nothing behind a login, nothing that
submits a form, nothing that defeats a protection rather than passing it the
way an ordinary browser does.
