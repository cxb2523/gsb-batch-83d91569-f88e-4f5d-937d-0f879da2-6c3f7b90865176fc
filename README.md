# Wellfound Scraper — Job Listings, Salary and Equity in Python

[![release](https://img.shields.io/github/v/release/2scraper/wellfound-scraper?sort=semver)](https://github.com/2scraper/wellfound-scraper/releases)
[![tests](https://github.com/2scraper/wellfound-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/2scraper/wellfound-scraper/actions/workflows/tests.yml)
[![canary](https://github.com/2scraper/wellfound-scraper/actions/workflows/canary.yml/badge.svg)](https://github.com/2scraper/wellfound-scraper/actions/workflows/canary.yml)
[![python](https://img.shields.io/badge/python-3.9%20%E2%80%93%203.13-blue)](pyproject.toml)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![engines](https://img.shields.io/badge/engines-Playwright%20%C2%B7%20Selenium%20%C2%B7%20Puppeteer%20%C2%B7%20Scraping%20Browser%20API-lightgrey)](#engines)
[![what you need](https://img.shields.io/badge/what%20you%20need-a%20residential%20exit-orange)](#do-you-need-to-pay-for-anything)

**Wellfound scraper** — an open-source (MIT) Python tool that reads wellfound.com role landing pages, the /jobs feed and individual job pages and writes job titles, company size and badges, salary and equity ranges and full descriptions to JSON or CSV. It needs a residential exit and nothing else: measured 2026-09-17, a datacenter address was refused on every route, while a 2Captcha residential US exit got HTTP 200 on every route this scraper reads. Use it for a job-listings dataset or salary research, and compare two runs with `diff_runs.py`.

Scrapes job listings from [wellfound.com](https://wellfound.com) (formerly
AngelList Talent): role landing pages, the `/jobs` discovery feed, and
individual job pages — with the company's size, badges and tagline, the
salary AND equity ranges, and the full job description.

Four ways to fetch — Playwright, Selenium, Puppeteer, or the 2Captcha
Scraping Browser API over CDP — one output schema, and every number below
measured on a date that is written beside it.

```bash
pip install -r requirements.txt -r requirements-playwright.txt
playwright install chromium

python3 playwright_scraper.py \
    --url "https://wellfound.com/role/r/software-engineer" --pages 3
```

---

## What you actually get

One row per job listing, 38 columns. Cut from a real run —
[`sample_output.json`](sample_output.json) and
[`sample_output.csv`](sample_output.csv) are ten of those rows.

```json
{
  "source": "wellfound.com",
  "url": "https://wellfound.com/jobs/4697947-senior-software-engineer",
  "sku": "4697947",
  "title": "Senior Software Engineer",
  "company_name": "Confident LIMS",
  "company_size": "11-50",
  "company_tagline": "The easiest way to test",
  "company_badges": ["Actively Hiring", "Top 1% of responders", "YC Funded"],
  "job_type": "full-time",
  "years_experience_min": 5,
  "posted_at": "2026-09-10T17:59:14+00:00",
  "remote": true,
  "remote_locations": ["Canada", "South America", "United States"],
  "compensation": "$100k – $180k • 0.05% – 0.25%",
  "salary_min": 100000.0, "salary_max": 180000.0, "salary_currency": "USD",
  "equity_min": 0.05, "equity_max": 0.25, "has_equity": true,
  "description": "…",
  "data_source": "apollo", "page": 1, "position": 1
}
```

Measured over 375 landing-page rows from 165 distinct companies, across six
live runs on **2026-09-17**:

| column | populated | why not more |
|---|---|---|
| `title`, `sku`, `url`, `company_name`, `company_id` | **100%** | the floor the run warns below |
| `description` | **100%** on landing rows, **0%** on the `/jobs` feed | the feed's records are a thinner type that carries none |
| `company_badges` | 92–98% | a company with no badges genuinely has none |
| `salary_min` | **83%** | 63 of 375 listings state no pay at all |
| `has_equity` | 33 say yes, 30 say "No equity", 312 do not say | `false` is a statement the listing made; `null` is silence |

Currencies seen: USD 303, INR 6, GBP 2. Company sizes: `51-200` and `11-50`
dominate at 127 and 126.

---

## Three modes

```bash
# 1. A role landing page — the rich one. Paginates.
python3 playwright_scraper.py --role software-engineer --remote --pages 3
python3 playwright_scraper.py --role data-scientist --location new-york --pages 2

# 2. The discovery feed. One page, thinner rows.
python3 playwright_scraper.py --mode jobs

# 3. One job, from its schema.org JobPosting.
python3 playwright_scraper.py --mode job \
    --url "https://wellfound.com/jobs/4697947-senior-software-engineer"
```

| mode | route | rows carry | paginates |
|---|---|---|---|
| `role` *(default)* | `/role/{r}` · `/role/r/{r}` · `/role/l/{r}/{loc}` | everything above | yes, `?page=N` |
| `jobs` | `/jobs` | no description, no job type, no badges | **no** — one address |
| `job` | `/jobs/{id}-{slug}` | adds `salary_period`, `benefits`, `industry`; no equity | n/a |

`--role r --remote` and `--role r` are **different listings**, not a filter
on one: `/role/r/software-engineer` reported 1,881 jobs and
`/role/software-engineer` a different set.

### The two sources agree, and that is checked

A landing page carries a normalised Apollo cache in `__NEXT_DATA__`; a job
page carries no `__NEXT_DATA__` at all and one schema.org `JobPosting`
instead. They are different applications, so `data_source` records which one
a row came from (`apollo` / `jsonld`) and `diff_runs.py` reports a change
that comes with a source change as `source_changed` rather than as a real
one.

Where both publish a salary they agree — job 4697947 is
`$100k – $180k` on the listing and `100000`–`180000` USD in the detail
page's `baseSalary`. The offline suite pins that.

---

## What is gated and what is not

**Gating is per ROUTE, not per site.** Measured 2026-09-17, three requests
each:

| route | datacenter (Hetzner, Helsinki) | 2captcha residential US exit |
|---|---|---|
| `/` | 403 | **200** |
| `/jobs` | 403 | **200** |
| `/role/{r}`, `/role/r/{r}`, `/role/l/{r}/{loc}` | 403 | **200** |
| `/jobs/{id}-{slug}` | 403 | **200** |
| `/company/{slug}` | 403 | **403** |
| `robots.txt` | 403 | 200 |

From a datacenter address **everything** is refused, including `robots.txt`,
and no browser gets past it: headless and headful Chromium both sat on
Cloudflare's "Just a moment..." for the full wait, 0 of 1 each.

From a residential exit every route this scraper reads answered 200 every
time — and `/company/{slug}` still answered 403, to plain HTTP **and** to a
real Chromium on that same exit. There is no `--mode company`, because there
is nothing this repo can honestly offer for it.

### Which captcha is on this site

**One vendor, and only one: Cloudflare.** Counted across 16 served pages and
4 real refusals on 2026-09-18 — zero occurrences of reCAPTCHA (v2, v3 or
Enterprise), hCaptcha, DataDome, PerimeterX, Incapsula, Kasada, AWS WAF,
Arkose/FunCaptcha or GeeTest. Not on the listings, not on the job pages, and
not on the login or sign-up pages either.

What there is, is **two different Turnstiles**, and telling them apart is the
whole story:

| | sitekey | where it lives | solvable from the markup? |
|---|---|---|---|
| **Wellfound's own** | `0x4AAAAAAAgpA-Qx7SsJOW-g` | published in the page config of the Next.js routes — 12 of 17 served captures | **yes**, the key is right there |
| **Cloudflare's challenge** | `0x4AAAAAAADnPIDROrmt1Wwj` | passed to `turnstile.render()` on the refusal and kept nowhere | **no** — it must be intercepted |

Wellfound's own widget is wired to its fetch layer: the site loads
`challenges.cloudflare.com/turnstile/v0/api.js` and renders into
`#turnstile_widget` when one of its own XHRs is challenged. It has not been
observed firing on a listing fetch.

Cloudflare's is what a scored address meets, and it arrives in **two skins
that are not equally solvable**:

| skin | who gets it | `_cf_chl_opt` | a widget on it |
|---|---|---|---|
| **"Security Check \| Wellfound"** — branded, the site's own styling | a plain HTTP client | 7× | **none at all** |
| **"Just a moment..."** | a real browser | 7× | yes, 1× |

The branded one has nothing on it for any solver at any price, which is the
only honest use of the word *unsolvable* — it describes that page, not the
product. The browser one does carry a widget, and that is the one this
scraper intercepts and solves (and whose token Cloudflare then refused — see
below).

### The marker that lies

`challenges.cloudflare.com` is on **14 of 16 served pages** and on only 1 of
4 refusals, because it is the site's own loader. `cf-turnstile` is on no
served page and on only the browser skin. So the obvious marker fires on
good pages and misses three refusals out of four.

`product_parser.BOT_CHALLENGE_MARKERS` uses the challenge's own bootstrap
vocabulary instead — `_cf_chl_opt`, `__cf_chl`, `orchestrate/chl_page` — each
**0 on every served page and present on all four refusals**. The offline
suite fails the build if the inverted marker is reintroduced.

## Do you need to pay for anything?

**You need a residential exit. Nothing else is required.**

That is the whole answer for the three modes this scraper has. A 2Captcha
residential proxy is one variable in `.env`:

```
WELLFOUND_PROXY=http://{user}:{password}@na.proxy.2captcha.com:2334
```

What the other paid products buy here:

* **Scraping Browser API** (`--cdp-endpoint`) — a browser you do not host,
  with its own residential exit and an auto-solve extension. Useful when you
  have no browser infrastructure, or want a persistent cookie profile.
* **Captcha solving** (`--twocaptcha-key`) — only reached if a challenge is
  actually rendered. On the routes above, a residential exit removes the
  challenge entirely, so most runs never touch this path.
* **Fingerprints** (`--fingerprint`) — a consistent device identity across
  runs. Not needed for anything measured here.

### About the captcha, precisely

Cloudflare's managed challenge **is** solvable — 2Captcha builds it as
`TurnstileTaskProxyless` — but the task needs `sitekey`, `action`, `cData`
and `chlPageData`, and a Cloudflare challenge page publishes **none of
them**: it calls `turnstile.render()` once and keeps nothing. So no static
read of the HTML can produce a solvable task, however careful.

This repo installs an init script on the browser context, before any page
script runs, that hooks `turnstile.render` and records its arguments. If a
sitekey is still not captured the run **refuses to build a task** rather
than paying for one the API will reject.

**And here is what that actually bought, measured 2026-09-17 from a
datacenter address**, because a claim about a paid product with no number
beside it is a guess wearing a fact's clothes:

| step | result |
|---|---|
| the hook captured the parameters | **yes** — `sitekey`, `action=managed`, `cData`, `chlPageData`, on every attempt |
| 2Captcha returned a token | **yes** — `TurnstileTaskProxyless`, 5–20 s |
| Cloudflare accepted it | **no** — the page stayed blocked |
| *control:* the block clears by itself | **no** — 0 of 8 reloads in the same session |

The control is what makes that a finding rather than an anecdote: a block
that expired on its own would produce the same observation as a token that
worked. It does not expire — eight consecutive reloads of the same page in
the same session returned HTTP 403 every time.

So on this site, from a scored address, a solved token did not get in
during testing. That is a statement about **this page and this exit**, not
about the product: the same challenge type is solved and accepted elsewhere
in this project family. What works here is a residential exit, which costs
less and removes the challenge entirely.

The run is bounded accordingly: `SOLVES_PER_PAGE` is 1 and **both** of the
engine's solve call sites are counted against it. That cap was not actually
enforced until this was measured — one call site was uncounted, so a single
page bought three tokens before the fix and one after.

The site's own widget is a different thing and is solvable from a static
read, because its sitekey is published in the page config.

## Engines

| engine | notes |
|---|---|
| `playwright_scraper.py` | **primary.** Full `--concurrency`, remote CDP. |
| `selenium_scraper.py` | cannot use an authenticated remote CDP endpoint — `debuggerAddress` takes a bare `host:port` with nowhere for a password. `--proxy-server` cannot authenticate either, so credentials are stripped and a warning printed. |
| `puppeteer_scraper.py` | pyppeteer is effectively unmaintained; its own README points at Playwright. |
| `scraper_api_client.py` | no local browser at all. Its own exits are datacenter addresses, so pass `--cdp-url`. |

All three browser engines agree on exit codes, run status, and whether a run
crashes or spends money — a shared `finish_run()` keeps that mapping from
drifting, and the offline suite asserts their flag sets against each other in
both directions.

**Install exactly one engine.** Playwright and pyppeteer declare mutually
unsatisfiable pins, and pyppeteer and selenium collide on `urllib3`. Use a
virtualenv per engine if you need more than one.

### Proxy traffic savers

A proxy is billed by traffic, so a run through `--proxy` / `--proxy-file` /
`WELLFOUND_PROXY` does two things to avoid paying for bytes it does not use:

- **One pre-check before any browser starts.** A CONNECT through the proxy
  and a `HEAD /robots.txt` on the target host. Chromium reports a proxy's
  HTTP 407 as a navigation timeout, so a wrong or exhausted credential used
  to spend every retry before ending as a load failure. Now a **407** (the
  gateway refused the credential, or the traffic balance is exhausted) or a
  **402** (proxy traffic/balance exhausted) ends the run in seconds with
  **exit 5** and `<out>.latest_attempt.meta.json` saying `status: failed`,
  `stop_reason: proxy_auth_failed` (or `proxy_balance_exhausted`). Any
  previous output and its `.meta.json` are left as they were. The message
  names the variable and never prints the credential. If the proxy does not
  answer at all, the run goes on as before and the browser makes its own
  attempt. No pre-check runs without a proxy or with `--cdp-endpoint`.
- **Images, video/audio and web fonts are not downloaded** through a local
  proxy: all three engines abort those requests (Playwright by resource type,
  pyppeteer through CDP's Fetch domain, Selenium by file extension with CDP
  `Network.setBlockedURLs`). Every row comes from JSON the server embeds in
  the page, never from an image or a font, and Cloudflare's challenge is
  scripts and an iframe, which are not blocked. This was decided from what
  the parser reads: on 2026-10-20 a free run from a datacentre was refused by
  Cloudflare before any listing was served, so a loaded-vs-blocked comparison
  of live rows was not possible. `--load-media` (or `WELLFOUND_LOAD_MEDIA=1`)
  loads them. Without a proxy, or over `--cdp-endpoint`, nothing is blocked.
- **Every run is metered and capped.** `--proxy-budget-mb` (default **10**,
  `0` = no cap, also `WELLFOUND_PROXY_BUDGET_MB`). Once more than that has
  gone through the proxy, further requests are refused, the run stops before
  its next navigation (every `--concurrency` worker shares one meter and
  stops with it), keeps the rows it has and exits **6** (or **5** with no
  rows), `stop_reason: proxy_budget_exceeded`. It never carries on past the
  cap. The sidecars (`<out>.meta.json`, and
  `<out>.latest_attempt.meta.json`, which every metered run writes) carry
  `proxy_bytes`, `proxy_budget_bytes` (`null` with no cap) and
  `proxy_budget_exceeded`, and the log ends with
  `Proxy traffic: X.X MB of Y MB budget`.

How the bytes are counted, per engine: Playwright sums `request.sizes()`
(request headers + body, response headers + body) of every finished or
failed request; pyppeteer reads CDP `Network.loadingFinished.encodedDataLength`
(bytes received, headers included) plus each request's line, headers and
body from `Network.requestWillBeSent`; Selenium reads the same CDP events
from chromedriver's performance log after each page. Only `http(s)` requests and responses that came over the network are counted: Chrome's own `chrome://`, `data:` and `blob:` loads, cache hits and Chrome's error page count nothing. The figure is an
**estimate of the payload through the tunnel**: TLS, the CONNECT exchange
and connections the browser opens for itself are not visible to any of the
engines, and add a few percent. Measured 2026-10-21 against a local stub
proxy that counted every byte it carried (a 60 kB page, a 30 kB stylesheet,
a 90 kB script): Playwright within 0.2%, pyppeteer 0.6%, Selenium 0.7%. A
megabyte here is 10^6 bytes. Nothing is metered without a proxy or over
`--cdp-endpoint`.

---

## Pagination, and the trap in it

A landing page states its own arithmetic, and **it counts companies, not
jobs**:

```
perPage: 20   pageCount: 47   totalStartupCount: 923   totalJobCount: 1881
```

Forty-seven pages of twenty **companies**, carrying between 32 and 45 job
rows each. Dividing 1,881 by 47 gives an answer that is wrong for every
page, which is why the sidecar records `total_jobs`, `total_companies`,
`per_page` and `pages_available` rather than leaving you to infer them.

**Asking past the last page does not fail — it repeats.** `?page=48` of a
47-page listing answers HTTP 200 carrying page 1's rows again. A run that
trusted its own request would re-collect page 1 for as long as it was asked
to and report success. Two defences:

1. the run **plans** against `pageCount` and never asks past it;
2. the response states which page the server actually used, inside the
   Apollo cache key, and a mismatch stops the run with
   `stop_reason=page_echo_mismatch`.

**`/jobs` is not addressable at all.** `?page=2` on it returns the identical
46 job ids as page 1, so `--pages 5` in that mode fetches one page and says
`single_page_listing` rather than reporting a complete five-page run holding
one page five times.

---

## Traps that look like bugs

* **`compensation` is one rendered string**, not numbers: `$100k – $180k •
  0.05% – 0.25%`. The `•` separates pay from equity and **either side may be
  absent** — 9 of 312 measured values are `No equity` alone and 2 are an
  equity range with no pay. `k` is 1e3 and **`L` is the Indian lakh, 1e5**;
  `₹30L – ₹80L` is 3,000,000–8,000,000, not 30–80.
* **`salary_period` is null on a landing row.** `$140k` reads as a year, but
  the page does not say so. The detail page does, and that is the only place
  the column is filled.
* **`has_equity: false` is not the same as `null`.** False means the listing
  printed "No equity". Null means it said nothing.
* **A "page" is twenty companies.** See above.
* **`years_experience_max` is almost always null** — 1 of 1,216 rows pooled
  across every live run. Wellfound's listings state a minimum and rarely a
  maximum. The column is kept because it is genuinely populated sometimes,
  not because the field exists.
* **`remote_kind` is null on 231 of 432 records.** The listing did not
  configure one; `remote` is the field to trust.
* **`/company/{slug}` is gated** even from a residential exit. Not a bug in
  your proxy.
* **`angel.co` redirects here and the redirect keeps your path** —
  measured, `angel.co/role/r/software-engineer` returns the same page as
  `wellfound.com/role/r/software-engineer`. The scraper still refuses the
  old host, so that one job never appears under two spellings, and the
  refusal says exactly that rather than "not a Wellfound site".

---

## Output contract

Exit codes: `0` ok · `1` crash · `2` bad usage · `3` blocked · `4` zero jobs
· `5` content not obtained (a remote API error, a load failure, or a proxy
that answered 407/402 to the pre-check: `stop_reason: proxy_auth_failed` /
`proxy_balance_exhausted`, or the proxy budget spent before any row:
`proxy_budget_exceeded`) · `6` partial (including a run `--proxy-budget-mb`
stopped).

* **A run that finds nothing writes nothing** — last night's good output is
  never replaced with `[]`.
* **Blocked ≠ empty ≠ partial**, three distinct exit codes, and
  `<out>.meta.json` records `status`, `stop_reason` and *which* pages failed
  by number.
* **A failed run writes no sidecar**, so a `"failed"` file never sits beside
  good data (the one exception is below, and only where no earlier output
  exists). A run the proxy pre-check stopped writes
  `<out>.latest_attempt.meta.json` instead, a separate file, and leaves
  `<out>.meta.json` alone. A run through a local proxy always writes that
  file too, with its proxy traffic, rows or not.
* **`--allow-empty` is for a genuine empty result only.** With it, a run
  that finished and found nothing writes an empty JSON (`[]`), a CSV holding
  only its header, and a sidecar with `status: empty` and its `stop_reason`,
  and still exits `4`. It never turns a blocked or failed run into an empty
  one. A blocked run still exits `3`. A run whose content was never
  obtained, or whose parser read nothing from a page that stated rows, still
  exits `5`. A run that saved rows and then stopped early still exits `6`.
  For the zero-row failures no empty row file is written, and an earlier
  output at the same `--out` is left untouched, sidecar included. Only when
  nothing earlier exists there does a blocked or failed `--allow-empty` run
  write a sidecar on its own, with `status: blocked` or `failed`.
  `diff_runs.py` compares an `empty` run like a complete one.
* **An empty CSV still carries its header.**
* `diff_runs.py` refuses to compare runs that are not both `complete`, or
  whose modes differ.

---

## Configuration

Credentials live in `.env` next to the scripts, never on a command line — a
secret in `argv` is readable by anything that can run `ps`. Copy
[`.env.example`](.env.example) and fill in what you use. Precedence, highest
first: **explicit flag → exported environment variable → `.env` → default.**

```bash
python3 env_config.py     # prints what was picked up, without any secret
```

---

## Development

```bash
python3 smoke_test.py -v     # the offline suite; no engine library needed
pytest                       # same checks, through tests/test_smoke.py
```

The suite passes with no engine installed and *records* the skips, because
"skipped, engine absent" reads identically to a real import error. CI
installs each engine in its own venv and fails if that engine's group
reports a skip.

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md) ·
Security: [SECURITY.md](SECURITY.md) ·
Changes: [CHANGELOG.md](CHANGELOG.md)

## Guides

- [How to run the 2scraper scrapers: setup, proxies, exit codes and access modes](https://2captcha.com/h/how-to-run-2scraper-open-source-scrapers) — installation, `.env`, `.meta.json` for the whole family.

## Related scrapers

Same CLI conventions, same output contract (one row per item, JSON or CSV, a `.meta.json` sidecar and shared exit codes):

- [Just Join IT scraper](https://github.com/2scraper/justjoin-scraper) — Polish IT job offers with real salaries, seniority, skill…
- [Mercor scraper](https://github.com/2scraper/mercor-scraper) — AI-talent marketplace: contract roles, rates, eligibility…
- [Better Business Bureau scraper](https://github.com/2scraper/bbb-scraper) — BBB search and category listings with no key or proxy, plus…
- [Flippa scraper](https://github.com/2scraper/flippa-scraper) — Online businesses for sale on Flippa
- [G2 scraper](https://github.com/2scraper/g2-scraper) — Categories, product pages and pricing pages
- [Google Play scraper](https://github.com/2scraper/googleplay-scraper) — Apps, installs, rating histograms and unbounded reviews…

All scrapers: [github.com/2scraper](https://github.com/2scraper) · Need another site? [Open a request](https://github.com/2scraper/.github/issues/new?title=%5BScraper%20request%5D%20)

## Licence

MIT. This is an independent tool; it is not affiliated with or endorsed by
Wellfound or AngelList. Scraping is your responsibility — check the site's
terms and `robots.txt`, and keep your request rate civil.

**On `robots.txt`:** every route this scraper accepts is allowed by
Wellfound's published rules, and every route those rules disallow (`/u/`,
`/_jobs/`, `/search`, `/jobs/signup`, `/auth/`, …) has no mode here. That is
a property of the code and the offline suite checks it against the published
file, so adding a mode for a disallowed route fails the build. It is **not**
a runtime gate: the scraper does not fetch `robots.txt` before each run and
does not parse rules at request time. Said precisely because the previous
wording — "reads only routes robots.txt allows" — read as a mechanism this
code does not have.
