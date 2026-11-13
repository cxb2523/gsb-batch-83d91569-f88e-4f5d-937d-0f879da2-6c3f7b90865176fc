# Maison KOSÉ Scraper — Product Listings, Prices and Stock in Python

[![release](https://img.shields.io/github/v/release/2scraper/kose-scraper?sort=semver)](https://github.com/2scraper/kose-scraper/releases)
[![tests](https://github.com/2scraper/kose-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/2scraper/kose-scraper/actions/workflows/tests.yml)
[![canary](https://github.com/2scraper/kose-scraper/actions/workflows/canary.yml/badge.svg)](https://github.com/2scraper/kose-scraper/actions/workflows/canary.yml)
[![python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.13-blue)](pyproject.toml)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![engines](https://img.shields.io/badge/engines-playwright%20%7C%20selenium%20%7C%20puppeteer%20%7C%20scraper--api-lightgrey)](#engine-limits)
[![no account needed](https://img.shields.io/badge/runs%20without%20an%20account-yes-brightgreen)](#you-do-not-need-a-2captcha-key-a-proxy-or-a-browser)

**Maison KOSÉ scraper** — an open-source (MIT) Python tool that reads Kosé's online store maison.kose.co.jp (brand and category listings, tag facets and product pages) and writes products, tax-inclusive prices, brands, stock and the consumption-tax rate to JSON or CSV. Measured on 2026-09-18 from a datacentre address, it needs no 2Captcha key, no proxy and no browser: plain HTTP was served and no page the site served carried a captcha marker. Use it to track prices and stock across a brand's catalogue, or compare two runs with `diff_runs.py`.

**Maison KOSÉ listing-page scraper** (plain HTTP, Playwright, Selenium,
Puppeteer, or the 2Captcha Scraping Browser API via CDP) — product listings,
prices, brands, stock and Japan's two consumption-tax rates, captcha solving,
proxies, fingerprints.

---

## Read this first: the site is `maison.kose.co.jp`, not `kose.com`

`kose.com` **resolves for nobody.** Measured 2026-09-18:

```
$ dig +short @8.8.8.8 kose.com A     # SERVFAIL, no answer
$ dig +norecurse @a.gtld-servers.net kose.com NS
kose.com.  172800  IN  NS  dns1.supremecenter.com.
kose.com.  172800  IN  NS  dns2.supremecenter.com.
$ dig +norecurse @162.210.102.140 kose.com SOA   # REFUSED
```

The domain is registered (GoDaddy, created 1998-11-30, paid to 2029) and
delegated to two nameservers that no longer serve the zone, so every resolver
returns SERVFAIL. That is a broken delegation, not a bot manager: there is
nothing at that name for anyone to fetch.

Kosé's actual online store is **[maison.kose.co.jp](https://maison.kose.co.jp/)**
(Maison KOSÉ) — which is where `www.kose.co.jp` sends a visitor, with its own
`<meta http-equiv="refresh">`. That is what this scraper reads.

## You do not need a 2Captcha key, a proxy, or a browser

Stated plainly rather than sold. Measured 2026-09-18 from a datacentre
address (netcup, Nuremberg, AS197540), against
`/site/cosmedecorte/c/c15_p3/`:

| request | result |
|---|---|
| `curl/8.5.0` | HTTP 200, 90,310 bytes |
| `python-requests/2.31.0` | HTTP 200, 90,310 bytes — byte-identical |
| a desktop Chrome User-Agent | HTTP 200, 90,310 bytes — byte-identical |
| **no `User-Agent` header at all** | HTTP 200, 90,310 bytes — byte-identical |
| 12 pages back to back, no delay | 12 × HTTP 200 |

and **zero captcha markers of any vendor on any page the SITE serves** — no
reCAPTCHA, hCaptcha, Turnstile, DataDome, PerimeterX, Incapsula, Kasada or
AWS WAF, no `data-sitekey`, no challenge iframe, on listings, product pages,
the site's own 404 and an exhausted facet alike.

One honest footnote, because the first version of this sentence was wrong by
omission. A page fetched through the **Scraping Browser API** does carry
captcha strings — sixteen of them on one 101 KB listing — and not one is
Kosé's: 2Captcha's auto-solve extension injects a hunter script per vendor
into every page it loads, including `cf-turnstile`, a bare `recaptcha` and an
empty `<captcha-widgets>` mount. They are the client's, not the site's. This
repo's marker set was narrowed on 2026-10-13 so none of them matches, and a
CDP-fetched page is now one of the fixtures the suite runs against — because
a guard is only as good as the fixture it runs against, and every capture
this repo had until then was fetched locally.

The grid is server-rendered into the first response, so a plain HTTP client
gets the whole page — which is why `http_scraper.py` is the recommended
engine. A browser here is a convenience, not a necessity.

**What the paid products would buy you, if that changes or at volume:**

* **2Captcha solving** — if Kosé ever renders a challenge. Nothing in this
  repo says a captcha here could not be solved; there is simply none to
  solve today. The solver is wired and the run pays for it under the usual
  `--solve-captcha when-blocked` rule.
* **Proxies** — many addresses, for a run large enough that one would be
  conspicuous. A Japanese exit is *not* required: a German datacentre address
  is served the same pages.
* **The Scraping Browser API** — a managed browser with a persistent profile
  and no local Chromium to maintain.
* **Fingerprints** — a consistent device identity. Verified working here
  (a JP fingerprint applied, 24 products returned), not needed.

---

## Install

**The short version — no browser at all:**

```bash
git clone https://github.com/2scraper/kose-scraper
cd kose-scraper
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # beautifulsoup4, requests
python http_scraper.py --category c15 --pages 3
```

That is the whole install for the recommended path. `http_scraper.py` reads
the same pages with the same parser and writes the same rows — the site
server-renders its grid, so there is nothing for a browser to do (measured
below).

**If you want a browser** — for the Scraping Browser API, for a captcha that
does not exist yet, or to check the two against each other:

```bash
pip install -r requirements-playwright.txt # then ONE engine
playwright install chromium
```

Install **exactly one** engine. playwright and pyppeteer pin incompatible
`pyee` versions and pyppeteer and selenium collide on `urllib3`; they do run
side by side in practice, but `pip check` reports the conflict and pip may
resolve it by downgrading something you wanted. Use a virtualenv per engine
if you need more than one.

## Use

Every example below works with `http_scraper.py` and with
`playwright_scraper.py`, which take the same flags and return the same rows.

```bash
# a brand's catalogue, three pages — no browser needed
python http_scraper.py \
    --url "https://maison.kose.co.jp/site/cosmedecorte/c/c15/" --pages 3

# the same thing by category id — the id is the only thing that selects one
python playwright_scraper.py --category c15 --pages 3

# a tag facet, which crosses brands
python playwright_scraper.py --tags "シワ改善,スキンケア" --pages 2

# one product page: adds volume, subcategory, colour count and release date
python playwright_scraper.py --mode product \
    --url "https://maison.kose.co.jp/site/onebykose/g/gMUSC/"

# the same scrape through a real browser, when you want one
python playwright_scraper.py --category c15 --pages 3

# no local browser AND no local Python dependency on one — 2Captcha's
# hosted browser over HTTP
python scraper_api_client.py --key "$TWOCAPTCHA_KEY" \
    --url "https://maison.kose.co.jp/site/cosmedecorte/c/c15/"
```

### Which engine

| | needs | use it for |
|---|---|---|
| `http_scraper.py` | `requests` | **the default.** Nothing here is gated, so this is the whole job |
| `playwright_scraper.py` | Chromium | `--cdp-endpoint`, `--fingerprint`, a future captcha, `--concurrency` |
| `selenium_scraper.py` | chromedriver | parity; cannot authenticate a remote CDP endpoint or a proxy |
| `puppeteer_scraper.py` | pyppeteer | parity; can authenticate a remote CDP endpoint |
| `scraper_api_client.py` | a 2Captcha key | one page per call, no local browser at all |

Measured 2026-10-13 on the same three pages, no delay: **4.8–6.0 s over HTTP
against 9.2–10.6 s through Playwright**, identical rows. The four engines
were run against the same two pages the same day and returned **48 of 48
identical rows**, every column.

Output is `kose_products.json` + `.csv` plus a `kose_products.meta.json`
sidecar. `python3 env_config.py` prints what was picked up from `.env`,
without printing secrets.

---

## What a run actually returns

Measured 2026-10-13 by walking a whole brand catalogue — 308 rows over 13
pages of `/c/c15/`:

| column | coverage |
|---|---|
| `title` `url` `sku` `brand` | 308 / 308 |
| `price` `currency` `tax_rate` | 308 / 308 |
| `in_stock` `image_url` | 308 / 308 |

Prices ran **¥220 to ¥264,000**; 41 of the 308 were out of stock and 2
carried the reduced 8% tax rate. Status `complete`, exit 0, 26 s.

**All four engines agree.** `http_scraper`, Playwright, Selenium and
pyppeteer were run against the same two pages the same day: **48 of 48 rows
identical**, every column — which is a stronger claim than it was a month
ago, because the browserless engine is what found the browser ones were
returning truncated titles.

### Columns worth knowing about

* **`tax_rate`** — Japan runs two consumption-tax rates and the prices here
  are tax-INCLUSIVE. 10% is standard; **8%** is the reduced rate on
  ingestibles, so a beauty supplement sits at 8% while the cream beside it is
  at 10%. Two tiles in 171 carried it. Computing a pre-tax figure from the
  wrong rate is wrong by two percent, silently, which is why it is a column.
* **`in_stock`** — read from the site's own button text as an ALLOWLIST, so a
  wording Kosé adds tomorrow reads as unknown rather than as a quiet "in
  stock". Verified in both directions: 19 of 171 measured tiles say
  現在購入頂けません or 予約受付終了.
* **`price_is_store_price`** — the site marks its own selling price with `※`,
  expanded on a product page as `Maison KOSÉ販売価格`. It says which of two
  different things a number is.
* **`variant_of`** — on a product row, the sku the page's own `rel=canonical`
  points at when that is a DIFFERENT product. It groups two sizes or shades
  of one item, and it exists as a column precisely so nobody uses the
  canonical as the row's URL — see the traps below.
* **`badges`** — the site's own `new` / `limited` / `online` flags, on 21% of
  rows. `limited` is often why a row vanishes between two runs.

### Columns this site does not have, and why

A column null on every row of every run should not exist, and removing one
needs the measurement written down:

* **no `original_price` / `discount_pct` / `lowest_price_30d`** — 360 price
  nodes surveyed and not one carries a struck-through, was- or reference
  price. There is no discount chain on this site, so there is no second view
  to reconcile a price against.
* **no `rating` / `review_count`** — absent from every tile and every product
  page's JSON-LD. The site publishes staff opinion pieces, which are
  editorial content by named employees rather than a score of anything.
* **no `locale`** — one market. No `hreflang` set, no `/en/`, `/site/en/` or
  `/global/` route (all 404), JPY on every row.
* **no `sort`** — the site offers no ordering control on either listing
  route, so there is nothing a run could have asked for.

---

## Traps that look like bugs

Each of these cost time to find and each is guarded by a check.

**`--retries 0` used to run no request at all, and then judge the blank
page.** The load loop is `range(1, retries + 1)`, so zero attempted nothing,
and the engine classified `about:blank` — a 39-byte empty document — as the
site's answer. It is a **usage error** now, because of how it failed: a
third-party audit ran exactly that on 2026-10-13, got the 39-byte page and
exit 4, and concluded in writing that the browser path was broken and should
be replaced. The same command with `--retries 1`, same address and same
minute, returned 199,558 bytes and 24 products. If you are reading an old
script that passes `--retries 0`, it has been getting nothing.

**The site shortens long product names in the BROWSER, and only there.**
Each tile carries `data-module="TruncateText" data-options='{"length": 36}'`
and the site's own JavaScript rewrites the name after load: 36 characters
and an ellipsis. A plain HTTP fetch sees the full name the server rendered.
So until this repo had a browserless engine, every long title came back
short — **10 of 72 rows** on one live 3-page run — and nothing could see it,
because there was nothing to disagree with. The parser now recovers the full
name from the thumbnail's `alt`, which the rewrite does not touch and which
is present on 171 of 171 measured tiles. The canary runs both engines weekly (Mondays)
and fails if any field differs.

**The brand in a URL selects nothing.** `/site/xyz/c/c15/` returns
byte-identical bytes (97,017) to `/site/cosmedecorte/c/c15/`, and the page's
own `rel=canonical` rewrites it. Only the `cNN` addresses a category and only
the `gSKU` addresses a product. So `brand` is read from each TILE — and a tag
listing genuinely mixes brands, **11 of them across 72 rows** on a live run.

**A category listing walked past its end serves its LAST PAGE AGAIN.** Not a
404 and not an empty grid: `/c/c15_p14/` and `/c/c15_p15/` each return the
same bytes as `/c/c15_p13/`, HTTP 200, with real tiles on them. A run that
stopped on "a page came back empty" would never stop. This scraper plans
against the site's own `N／Mページ` counter and still stops on "this page
added no new sku". A TAG listing ends differently, with a genuinely empty
page, and publishes no counter at all.

Walking the whole of Cosme Decorté, 2026-10-13: `/c/c15/` states **13
pages** and yields **308 products**, every one with a title, url, sku,
brand, price, currency, stock state, image and tax rate, in **26 s** over
HTTP. That number is dated because it moves — the same walk a month earlier
returned 304.

**The wrong pagination parameter fails silently.** On a tag listing `?p=2`
works while `&pageno=2` and `&page=2` are ignored and return page 1 with HTTP
200. A run that built one of those would dedupe every page down to page 1's
rows and report a `complete` run holding a single page.

**A quarter of product pages canonicalise to a different product.** Measured
over 20: `/g/gJQBA/` is the 60 g cream and its `rel=canonical` points at
`/g/gJQGA/`, which is the 20 g one. Five of the twenty do this. A row built
from the canonical would link to the wrong product while its title, sku and
price described the right one, so the row's URL is built from the page's own
sku and the canonical goes in `variant_of`.

**A product page reuses the listing's tile class.** `c-product__item` appears
on `<div>`s for staff-review cards — 15 of them on one measured page — plus
an `awoo` recommendation block. A class-only selector would invent fifteen
products per product page, each with a `/staff/` URL and no sku. The tile
selector is element-qualified (`li.c-product__item`) and sees zero.

**Product-shaped links outnumber real tiles.** A grid page carries 48–57
`/g/g…/` hrefs against 24 tiles (and 107 under Selenium, where more of the
page's JavaScript has run). The extra links are carousel banners. Rows come
from tiles; the link count is only used to tell a broken parser apart from an
empty category.

**A 404 and an empty page are different answers, and the site gives both.**
A bogus goods code or category id (`/site/x/g/gZZZZZZ/`, `/c/c99999/`)
answers HTTP **200** with the site's full chrome and no tiles — that is an
answer about the CATALOGUE. A wrong PATH answers a real **404** with a bare
1,040-byte page carrying no site chrome at all, and the scraper stops on it
rather than retrying: retrying spends the budget on an address that will
never exist. The bare tag-facet URL (`/site/itemtags/list.aspx` with no
`tags=`) is the one this scraper accepts that really does 404.

Selenium cannot read an HTTP status — WebDriver exposes none — so the parser
also reads the status the site states in its own `<title>404- …`. That is
what makes all three engines agree instead of two being better informed than
the third.

**A run pointed at page 10 reads page 10.** `--url .../c15_p10/ --pages 3`
fetches 10, 11 and 12; the start page is honoured rather than normalised
back to 1. The `page` column is the run's own index, so the sidecar's
`start_url` is what says where a run began.

**Zero is a real price and a real rank.** Prices reach six figures —
¥264,000 for one cream — so a parser that mishandles the comma turns that
into 264. Every fixture in the suite pins the value, not the coverage.

---

## Engine limits

* **Selenium cannot use an authenticated remote CDP endpoint.** chromedriver's
  `debuggerAddress` takes a bare `host:port` with nowhere to put a password.
  Playwright and pyppeteer authenticate on the WebSocket upgrade; use one of
  those with `--cdp-endpoint`.
* **Selenium's `--proxy-server` cannot authenticate at all.** Credentials are
  stripped and a warning printed rather than letting you believe otherwise.
* **pyppeteer is effectively unmaintained** and its own README points at
  Playwright.
* **Never set a proxy or a fingerprint over `--cdp-endpoint`.** The remote
  browser brings its own; the engines refuse the combination on purpose.
* **`--concurrency` is refused over `--cdp-endpoint`.** A Scraping Browser
  profile allows one live connection, so workers collide. Use several `pid`s,
  one run each.

## What has and has not been verified live

Honest about the gap, because a claim here is either measured or absent:

| path | status, 2026-10-13 |
|---|---|
| `http_scraper.py`, listing / tags / product | **verified** — 308 rows over 13 pages, exit 0 |
| Playwright, listing / tags / product | **verified** — identical rows, exit 0 |
| Selenium, listing | **verified** — 48 rows, identical to the HTTP engine's |
| pyppeteer, listing | **verified** — 48 rows, identical to the HTTP engine's |
| Scraper API (`scraper_api_client.py`) | **verified** — 24 rows, $0.0005 |
| `--fingerprint` (2Captcha Fingerprint API) | **verified** — JP fingerprint applied, 24 rows |
| `--cdp-endpoint` (Scraping Browser) | **verified 2026-10-13** — 24 rows over a `country-de` profile, exit 0. It was unverified a month ago because the only profile to hand had expired; two of the three tried today still answer `401`, which is what an expired one looks like. |
| `--concurrency 3` | **verified** — 120 rows over 5 pages, merged in page order although they arrived 4-3-2-5 |
| credential masking in errors | **verified** — a deliberately wrong endpoint's password appears 0 times in the output, including in Playwright's own five-line call log |
| `--solve-captcha` | **never fired** — no challenge has been observed on this site at all |

## Exit codes

`0` ok · `1` crash · `2` bad usage · `3` blocked · `4` zero products ·
`5` the content was never obtained · `6` partial

A run that finds nothing writes nothing — it will not replace last night's
good output with `[]`. Pass `--allow-empty` to opt out.

### What a failed run leaves behind

Three files, and the distinction between them is the point:

| file | describes |
|---|---|
| `<out>.json` / `.csv` | the last run that produced rows |
| `<out>.meta.json` | **that** run — never overwritten by a failed one |
| `<out>.last_attempt.json` | the MOST RECENT attempt, successful or not |

A failed run deliberately writes no sidecar: `save` leaves the previous good
output in place, and a `"failed"` sidecar beside good rows would contradict
them and make `diff_runs.py` refuse a comparison of data that is fine. The
cost of that used to be that a failed run left a caller nothing but an exit
code. `last_attempt.json` is the fix — a separate NAME, so both facts can be
true at once. It carries the status, the stop reason, the engine, its driver
version and how long the attempt took.

Every one of those files is written atomically — to a temporary file beside
the target, then renamed — so a crash, a kill or a full disk cannot leave a
truncated file where a complete one was.

## Tests

```bash
python3 smoke_test.py          # offline, no engine library required
python3 smoke_test.py -v       # and say what each check looked at
pytest                         # the same suite, wrapped
```

Fixtures are cut verbatim from real captures and were verified to parse to
identical values to their untrimmed originals before being committed. The one
staff-review card in the product fixture has its author name and text
replaced with placeholders: it is there because the parser must IGNORE it,
and republishing a named employee's writing is a separate act from the site
showing it on its own page.

## Guides

- [How to run the 2scraper scrapers: setup, proxies, exit codes and access modes](https://2captcha.com/h/how-to-run-2scraper-open-source-scrapers) — installation, `.env`, `.meta.json` for the whole family.

## Related scrapers

Same CLI conventions, same output contract (one row per item, JSON or CSV, a `.meta.json` sidecar and shared exit codes):

- [LG scraper](https://github.com/2scraper/lg-scraper) — Every model in an lg.com category
- [Lidl US scraper](https://github.com/2scraper/lidl-scraper) — Grocery prices, unit prices and pack sizes from lidl.com…
- [MediaMarkt scraper](https://github.com/2scraper/mediamarkt-scraper) — Category grids, search results and product pages from ten…
- [Montblanc scraper](https://github.com/2scraper/montblanc-scraper) — Per-market prices, stock, collections and full variant…
- [Pottery Barn scraper](https://github.com/2scraper/potterybarn-scraper) — Every product in a Pottery Barn category, and every SKU's…
- [Rakuten Ichiba scraper](https://github.com/2scraper/rakuten-scraper) — Japan's largest marketplace

All scrapers: [github.com/2scraper](https://github.com/2scraper) · Need another site? [Open a request](https://github.com/2scraper/.github/issues/new?title=%5BScraper%20request%5D%20)

## Licence

MIT. This repo reads **public pages**: listings, prices and product
descriptions. It does not log in, does not touch a cart or a wishlist, and
does not collect personal data.
