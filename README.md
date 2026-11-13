# Andie Swim Scraper — Collections, Prices and Per-Size Stock in Python

[![release](https://img.shields.io/github/v/release/2scraper/andieswim-scraper?sort=semver)](https://github.com/2scraper/andieswim-scraper/releases)
[![tests](https://github.com/2scraper/andieswim-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/2scraper/andieswim-scraper/actions/workflows/tests.yml)
[![canary](https://github.com/2scraper/andieswim-scraper/actions/workflows/canary.yml/badge.svg)](https://github.com/2scraper/andieswim-scraper/actions/workflows/canary.yml)
[![python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.13-blue)](pyproject.toml)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![engines](https://img.shields.io/badge/engines-Playwright%20%7C%20Selenium%20%7C%20Puppeteer%20%7C%20Scraping%20Browser%20API-lightgrey)](#engines)
[![runs without an account](https://img.shields.io/badge/runs%20without%20an%20account-yes-brightgreen)](#do-you-need-any-of-the-paid-products)

**Andie Swim scraper** — an open-source (MIT) Python tool that reads andieswim.com collection listings, keyword lookups and product pages and writes sizes, prices, was-prices and which sizes are in stock to JSON or CSV. Measured on 2026-09-18 from an ordinary datacenter address, nothing on the read path was gated: no key, no proxy and no browser fingerprint were needed. Use it to track prices and per-size availability, or compare two runs with `diff_runs.py`.

Scrapes **[andieswim.com](https://andieswim.com)** (Andie Swim): collection
listings, keyword lookups, and single products with their full size/colour
table — sizes, prices, was-prices, and which sizes are actually in stock.

```bash
pip install -r requirements.txt -r requirements-playwright.txt
python3 -m playwright install chromium

python3 playwright_scraper.py \
    --url "https://andieswim.com/collections/one-pieces" --pages 3
```

```
[+] Saved 180 products -> andieswim_products.json
[+] Saved 180 products -> andieswim_products.csv
[+] Wrote run metadata -> andieswim_products.meta.json (status=complete)
```

---

## Do you need any of the paid products?

**No — not for anything on the read path.** Measured 2026-09-18 from an
ordinary datacenter address, with no key, no proxy and no browser
fingerprint:

| request | result |
|---|---|
| a collection's JSON, browser User-Agent | HTTP 200 |
| the same, `curl/8.5.0` | HTTP 200 |
| the same, `python-urllib/3.11` | HTTP 200 |
| the same, a crawler User-Agent | HTTP 200 |
| the same, **no `User-Agent` header at all** | HTTP 200 |
| 20 requests in 4.9 s | 20 × HTTP 200 |

Nothing is gated and no challenge has ever appeared on any capture.

**One qualification, added 2026-10-13 and worth the sentence.** A third-party
audit hit Cloudflare's own per-colo rate limit on this endpoint —
`HTTP 429`, 18 bytes of `local_rate_limited`, `Retry-After: 60`. It was not
reproducible from here that day (30 requests in 5.9 s all answered 200, and a
3-page run was `complete`), so it is an edge condition rather than a policy
the store applies to everyone. The scraper now recognises it as a THROTTLE —
it waits at the same exit rather than reporting a block, because a different
address would not help — and a run still holding nothing reports a rate
limit, never an empty catalogue.

So read the table as "this store does not gate reads", not as "you cannot be
rate limited". Re-derive it rather than trusting it: the
commands are one `curl` each.

**What the 2Captcha products actually buy here**, which is real but narrow:

* **A specific market.** The store sets prices *per market* (see below) and
  the market is a path prefix, so the honest answer is usually "just ask for
  `/en-gb/`". A proxy exit matters only if you also want the store's
  geolocation app to agree with you.
* **Volume from many addresses.** `--concurrency` from one IP is N× the
  traffic from one address; a pool spreads it.
* **No local browser.** `scraper_api_client.py` needs no Chromium at all.

### Which captcha is on this site

One is, and the precise answer matters more than "none":

* **Shopify storefront-forms hCaptcha** —
  `cdn.shopify.com/shopifycloud/storefront-forms-hcaptcha/ce_storefront_forms_captcha_hcaptcha.v1.5.3.iife.js`,
  sitekey `f06e6c50-85a8-45c8-87d0-21a2b65856fe`. It ships on **every page
  the store serves** and is bound to **form submits** — the script hooks
  `submit` and looks for an `h-captcha-response` field. It guards the
  newsletter, contact and account forms. **No listing, product page or JSON
  route renders one, so a scrape never meets it.**
* **Not reCAPTCHA.** `recaptcha-v3-token` and `g-recaptcha-response` do
  appear in the page — inside that same Shopify bundle, as two entries in a
  list of field names it checks for. No reCAPTCHA is loaded.
* **Nothing else.** Zero Turnstile, DataDome, PerimeterX, Incapsula, Kasada
  or AWS WAF markers, and no `data-sitekey`, across every capture.
* Checkout ships Shopify's own captcha. Out of scope, and
  [`robots.txt`](https://andieswim.com/robots.txt) asks agents not to
  complete checkouts automatically. This tool does not.

That is a statement about what the **page** carries, not about what can be
solved: 2Captcha solves hCaptcha with `HCaptchaTaskProxyless`. This repo
simply has no occasion to call it, so `--solve-captcha` stays wired and
never fires.

---

## What this reads, and why it is JSON

The rendered pages are the wrong place to look on this store, and that is
measured rather than assumed:

* **A collection page's HTML carries no product grid.** 793 KB of
  `/collections/one-pieces` contains **5** distinct `/products/` links, all
  from recommendation widgets — and `?page=2` returns the same five. The
  grid is painted after load by a React component over the Storefront API.
* **A product page publishes no Product JSON-LD.** One
  `application/ld+json` block, and its `@type` is `BreadcrumbList`.

What the store *does* publish, ungated, is its own JSON — the same objects
its front end consumes:

```
/collections/{handle}/products.json?limit=250&page=N    listing
/products/{handle}.js                                   one product, all variants
/search/suggest.json?q=…                                keyword lookup
/collections.json?limit=250&page=N                      the collection index
```

So the engines navigate to the endpoint and parse the payload. The browser is
still the transport — it is what the proxy, fingerprint and Scraping Browser
paths plug into — but the data is JSON on every route.

---

## Modes

| mode | reads | one row per |
|---|---|---|
| `listing` *(default)* | `/collections/{handle}` | **product** |
| `search` | `/search?q=…` | **product** |
| `product` | `/products/{handle}` | **variant** |

```bash
# a collection, three pages
python3 playwright_scraper.py --url ".../collections/one-pieces" --pages 3

# a keyword lookup
python3 playwright_scraper.py --mode search --query "bikini top"

# one product, one row per size
python3 playwright_scraper.py --mode product \
    --url ".../products/the-amalfi-flat-black-classic"

# a different market
python3 playwright_scraper.py --locale en-gb \
    --url "https://andieswim.com/en-gb/collections/one-pieces"
```

`--mode product` is the one that answers a question a listing cannot: **which
sizes are in stock**. On `one-pieces`, **most products are available in some
sizes and not others** — 63 / 116 / 1 (every size / some / none) out of 180 on
2026-09-18, and 64 / 115 / 1 the same evening, because it moves as stock
moves. A listing row says "this style is buyable"; only a variant row says
which size is. Re-derive rather than trusting the split: count
`variants_available` against `variants_total` in any run's JSON.

---

## Measured on a real run

`--url .../collections/one-pieces --pages 3`, 2026-09-18, from a datacenter
address with no proxy and no key. Re-derive rather than trusting this table
 — every figure comes from `<out>.json` and `<out>.meta.json`:

| | |
|---|---|
| rows | **180**, status `complete` |
| `title` · `price` · `currency` · `image_url` · `handle` · `product_type` | **100%** |
| `base_sku` | **91.7%** — the 8.3% are bundles whose variants share no style code |
| `original_price` / `discount_pct` | **45%** (81 of 180), discounts 20–75% |
| price range | 30.00 – 142.00 USD |
| in stock (any size) | 179 of 180 |
| sizes available | all / some / none — **the split moves daily**; two runs hours apart gave 63/116/1 and 64/115/1. Count `variants_available` vs `variants_total` |

Pagination, exercised with a smaller page size (at the default `--limit 250`
most collections fit in one request):

```
--limit 50 --pages 4   ->  50 + 50 + 50 + 30 = 180 rows, pages 1-4,
                           page+position unique on every row
```

The whole catalogue, walked at `limit=250`: **250 + 250 + 250 + 22 = 772
distinct handles**, no repeats, page 5 empty. The store's own
`sitemap_products_1.xml` lists 753 product URLs and **every one of them is in
those 772** — a strict superset with zero misses, which is what makes
"complete" mean complete here.

---

## Traps that look like bugs

Read this before concluding the tool is broken.

**`products_count` is not a product count.** `/collections.json` reports
`one-pieces` at **472** and `all-swimwear` at **3089**, while the storefront
serves **180** and **322** — against 772 published products in the whole
store, so 3089 cannot be a count of anything a visitor can reach. It is not a
variant count either (all-swimwear has 1997 variants). This scraper records
it as `catalog_count` in the sidecar **with that warning** and plans nothing
from it. A run that holds 180 of "472" is not short.

**A misspelt collection handle returns 200 and an empty list.**
`/collections/does-not-exist/products.json` answers HTTP 200 with
`{"products": []}`; only the HTML route 404s. So every run checks the handle
against the store's own collection index (830 collections) and reports
`unknown_collection` rather than `empty` when it is absent.

**Prices are set per market, not converted.** One variant, 2026-09-18:

```
112.00 USD · 195.00 CAD · 110.00 GBP · 175.00 AUD · 130.00 EUR · 21600 JPY
```

110 GBP is roughly 148 USD against a 112 USD list, so a cross-market gap is
**pricing policy, not arbitrage**. The store publishes 200 markets, all
`en-xx`, and every row carries which one it came from. Unlike some sibling
sites, the store is English everywhere — titles are byte-identical across
markets, so a cross-market join on `sku` is exact.

**An HTML page on this store is timing-dependent; a JSON endpoint is not.**
There is no HTTP redirect anywhere (`curl -L` follows zero hops), but the
theme ships a client-side geolocation app that rewrites the location to the
visitor's own market after load. Measured from a Finnish address:
`/collections/all` read at `domcontentloaded` says USD; the same URL read
after a full load has become `/en-fi/collections/all` and says EUR. This bit
the repo once — three engines disagreeing about the currency on one URL — and
is why nothing here is read from markup.

**There is no `--sort`, and that is a measurement.** The JSON endpoint does
not take `sort_by` and ignores one that is passed. A flag would report an
ordering the fetch never applied. Nothing is capped either, so ordering
decides `position` and nothing else: two runs under different orderings hold
the same rows.

**`in_stock: null` means not stated, never out of stock.** Only
`/products/{handle}.js` publishes per-variant availability; `.json` omits it
entirely. This repo reads `.js` for exactly that reason.

**Ratings are not in the output.** The store uses Okendo, whose stars are
`display:none` in the collection grid and absent from every JSON route here.
Collecting them would cost one third-party request *per product* — 180 for
one collection — so the column does not exist rather than existing and being
null.

---

## Engines

| engine | install | notes |
|---|---|---|
| **Playwright** *(primary)* | `requirements-playwright.txt` | what the canary runs |
| **Selenium** | `requirements-selenium.txt` | cannot use an authenticated remote CDP endpoint, and `--proxy-server` cannot authenticate at all |
| **pyppeteer** | `requirements-puppeteer.txt` | effectively unmaintained; its own README points at Playwright |
| **Scraping Browser API** | `requirements.txt` only | `scraper_api_client.py` — no local browser |

All three local engines produce **byte-identical output** on the same
collection (verified, modulo `scraped_at`) and agree on exit codes and run
status. **Install exactly one:** their pins are mutually unsatisfiable
(`pyee` <12 vs ≥13, `urllib3` <2.0 vs ≥2.6). Use a virtualenv per engine.

---

## Output

One row per product (or per variant in `--mode product`), same field order in
JSON and CSV. See [`sample_output.json`](sample_output.json) — cut from a real
run.

```
source scraped_at url sku title brand price currency in_stock image_url
category price_source page position mode locale
product_id handle base_sku product_type original_price discount_pct
price_max price_varies variants_total variants_available tags published_at
collection sort variant_id variant_title color size
```

`sku` is Shopify's numeric **product** id on a listing row and the variant's
own **SKU string** (`AO292-BLK-XS`) in `--mode product` — rows are different
things in the two modes, and `diff_runs.py` refuses to compare them.

Every run writes `<out>.meta.json` beside the data with `status`,
`stop_reason`, which pages failed by number, the market, the currency and its
source. **A failed run writes nothing** — last night's good output is never
replaced with `[]` (`--allow-empty` opts out).

**Exit codes:** `0` ok · `1` crash · `2` bad usage · `3` blocked ·
`4` zero products · `5` no rows, the content was never obtained (a
timeout, a dead proxy, a remote API error, or a served payload that
parsed to nothing) · `6` partial.

---

## Configuration

Credentials live in `.env` next to the scripts, never on a command line.

```bash
cp .env.example .env
python3 env_config.py      # prints what was picked up, without secrets
```

`ANDIESWIM_URL`, `ANDIESWIM_PROXY`, `ANDIESWIM_CDP_ENDPOINT`,
`TWOCAPTCHA_KEY`. Precedence: an explicit flag → an exported environment
variable → `.env` → the default.

---

## Tests

```bash
python3 smoke_test.py          # the offline suite, no network, no engine needed
pytest                          # the same checks, wrapped
```

Fixtures are cut from real captures and each was verified to parse to
identical values to its untrimmed original before being committed.

## Guides

- [How to run the 2scraper scrapers: setup, proxies, exit codes and access modes](https://2captcha.com/h/how-to-run-2scraper-open-source-scrapers) — installation, `.env`, `.meta.json` for the whole family.

## Related scrapers

Same CLI conventions, same output contract (one row per item, JSON or CSV, a `.meta.json` sidecar and shared exit codes):

- [Bershka scraper](https://github.com/2scraper/bershka-scraper) — Every SKU in a Bershka category
- [Catawiki scraper](https://github.com/2scraper/catawiki-scraper) — Auction lots, bids, reserves, estimates and sellers…
- [Etsy scraper](https://github.com/2scraper/etsy-scraper) — Search, category, shop and listing pages as JSON or CSV…
- [Farfetch scraper](https://github.com/2scraper/farfetch-scraper) — Luxury fashion listings and per-size product data…
- [Givenchy Beauty scraper](https://github.com/2scraper/givenchy-scraper) — Products, prices and shades across 11 storefront locales
- [Home Depot scraper](https://github.com/2scraper/homedepot-scraper) — Per-store prices, stock, brands, models and ratings…

All scrapers: [github.com/2scraper](https://github.com/2scraper) · Need another site? [Open a request](https://github.com/2scraper/.github/issues/new?title=%5BScraper%20request%5D%20)

## Licence

MIT. Not affiliated with Andie Swim. Respect the site's
[`robots.txt`](https://andieswim.com/robots.txt) and terms; this tool reads
public catalogue pages and does not touch checkout.
