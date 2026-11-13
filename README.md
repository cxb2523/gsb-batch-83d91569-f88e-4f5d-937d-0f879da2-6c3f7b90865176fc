# Mercor Scraper — AI Talent Jobs and Pay Rates in Python

**Mercor scraper** — an open-source (MIT) Python tool that reads Mercor's job index and individual listings on work.mercor.com plus Mercor's own careers page, and writes job titles, pay rates, work/residence eligibility and company details to JSON or CSV. On 2026-09-18 every route it reads was served in full to a bare datacentre address with no credentials at all, and a re-run on 2026-10-07 from the same address through all three engines was served again. Use it to build a dataset of contract roles and their rates, or compare two runs of the same mode with `diff_runs.py`.

Scrapes [mercor.com](https://mercor.com) — the AI-talent marketplace's job
index, individual listings, and Mercor's own corporate openings — with
Playwright, Selenium, Puppeteer, or the 2Captcha **Scraping Browser API**
over CDP.

[![release](https://img.shields.io/github/v/release/2scraper/mercor-scraper)](https://github.com/2scraper/mercor-scraper/releases)
[![tests](https://github.com/2scraper/mercor-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/2scraper/mercor-scraper/actions/workflows/tests.yml)
[![canary](https://github.com/2scraper/mercor-scraper/actions/workflows/canary.yml/badge.svg)](https://github.com/2scraper/mercor-scraper/actions/workflows/canary.yml)
[![python](https://img.shields.io/badge/python-3.9%20%7C%203.13-blue)](pyproject.toml)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)
[![engines](https://img.shields.io/badge/engines-playwright%20%7C%20selenium%20%7C%20puppeteer-informational)](#engines)
[![runs without an account](https://img.shields.io/badge/runs%20without-an%20account-success)](#you-do-not-need-to-buy-anything-for-this-site)

---

## You do not need to buy anything for this site

This is the honest headline, and it is unusual enough in this family to put
above everything else: **every route this scraper reads was served in full
to a bare datacentre address with no credentials at all.**

Measured 2026-09-18 from a Hetzner VPS in Helsinki (AS24940):

| Route | Result |
|---|---|
| `work.mercor.com/explore` | 200 — **390 listings in one response** |
| `work.mercor.com/jobs/{id}/{slug}` | 200 — twelve rapid fetches, ~0.4 s each, no rate limiting |
| `www.mercor.com/careers` | 200 — **108 roles** |
| `work.mercor.com/sitemap.xml` | 200 — **447 job URLs** |

Re-run on 2026-10-07 from the same Hetzner address, through all three
engines: `--mode listings` 305 rows, `--mode careers` 113, `--mode job` 3 and
then 8 (four workers) of 306 enumerated — every one served, exit 0. (The
catalogue is smaller than three weeks earlier; the access is not different.)

…to `curl`, to `python-requests`, and to a request with an **empty**
User-Agent. Eighteen candidate bot-challenge markers were counted across
seven captures — `cf-turnstile`, `challenges.cloudflare.com`, DataDome,
PerimeterX, Incapsula, Akamai, `errors.edgesuite.net`, AWS WAF, reCAPTCHA
in both spellings, hCaptcha, `data-sitekey` and the rest — and **every one
was zero**.

So this is a working command:

```bash
pip install -r requirements.txt -r requirements-playwright.txt
playwright install chromium
python3 playwright_scraper.py
```

No key, no proxy, no account. What the paid products actually buy here is
in [What the 2Captcha products are for](#what-the-2captcha-products-are-for)
— it is volume and a specific exit country, not access.

---

## Quick start

```bash
# The marketplace index — the whole of it, in one response
python3 playwright_scraper.py --mode listings --format both --out mercor

# Mercor's own salaried openings (a different host, a different population)
python3 playwright_scraper.py --mode careers

# Every listing's detail page. A "page" here is one job, enumerated from the
# sitemap AND the index; --pages is capped at what that enumeration holds, so
# a large number means "all of them" (462 of them on 2026-09-18, 306 on
# 2026-10-07 — the size moves, which is why the sidecar records it).
# (--concurrency is Playwright-only; the other two engines log that they
#  ignore it and fetch one page at a time.)
python3 playwright_scraper.py --mode job --pages 1000 --concurrency 4

# One specific listing
python3 playwright_scraper.py --mode job \
  --url "https://work.mercor.com/jobs/list_AAABoGhhxWgF7ygE2LZOgIy3/b-2-b-sales-expert-3-yoe-us-only"
```

Every mode has a correct default URL, so `--url` is optional — Mercor's
index accepts no query parameters, so there is only one address per route.

---

## Three modes, because the site publishes three different things

| Mode | Route | What it gives you |
|---|---|---|
| `listings` *(default)* | `work.mercor.com/explore` | The whole marketplace index in **one** response: rate ranges, the site's own `domain` category, work/residence eligibility, slot counters. |
| `job` | `work.mercor.com/jobs/{id}/{slug}` | One listing, adding the company website, company description, spot counts and a **currency** the index does not publish. The only mode that covers listings the index omits. |
| `careers` | `www.mercor.com/careers` | Mercor's own salaried roles, via the Ashby ATS. Department, team, Ashby apply URL, salary tiers. |

`listings` and `job` are two views of **one** thing, keyed by the same
`listingId`, so a `job` run enriches a `listings` run and `diff_runs.py`
joins them on `sku`. `careers` is a genuinely different population with its
own UUID id space and **no ids in common**, so `diff_runs.py` refuses to
compare it against the other two — every row would otherwise read as both
added and removed.

---

## Traps that look like bugs

Read this section before concluding the tool is broken.

**Most listings do not name a company, and that is the site.** 99 of 390
named one on 2026-09-18 and 65 of 305 on 2026-10-07; the rest are clients
Mercor runs the hiring for without naming them. `company_brand_visible` is the site's own flag saying which is
which, so a null `company_name` beside `False` is *withheld*, not missing.

**`/explore` is complete and is not exhaustive — and how far it falls short
moves.** A `--mode listings` run fetches everything that route serves,
genuinely `status: complete`, and the route does not always hold everything
the site publishes. Neither enumeration source contains the other, on either
date it was measured:

```
                      2026-09-18    2026-10-07
sitemap.xml job URLs      447           304
/explore records          390           305
shared                    375           303
sitemap only               72             1   (the 72 checked were all live)
explore only               15             2
union                     462           306
```

The structural claim held both days; the SIZE of the gap did not (72 → 1).
So no figure here is a fact about the site, and the answer is a command, not
a number: `--mode job` reads both sources every run and records the result in
the sidecar (`enumeration_sources`), together with whether both answered
(`enumeration_complete`).

**A lost source makes the run `partial`, not `complete`.** If the sitemap
cannot be read — it raised, or it answered and held no job URLs — the run
carries on with the index alone, keeps the rows, and reports `partial` (exit
6, stop reason `enumeration_incomplete`) with the failure named in
`enumeration_failures`. Each source is tried `--retries` times first, so one
dropped connection does not cost a run its status.

**A withdrawn listing is not the end of the queue.** In `--mode job` the
addresses are enumerated before any of them is fetched, so a listing taken
down in between answers 404 (or bounces to `/login`). Every enumerated
address is attempted regardless: that one address is recorded in
`urls_not_found`, the rest are still fetched, and the run stays `complete`.
The same holds for an address that answers with a 5xx or a refusal — the
queue is walked to its end either way, and the run is then reported
honestly (`partial`/exit 6 with rows, exit 5 with none).

**Every address's outcome is in the sidecar.** `job_url_outcomes` is one
entry per attempted address, in enumeration order, each with `url`,
`outcome` (`success`, `not_found`, `target_5xx`, `target_http_error`,
`refused`, `unparseable` or `load_failed`) and `attempts` (how many
navigations it actually cost). `jobs_enumerated`, `jobs_fetched`,
`jobs_not_found` and `urls_not_found` keep their existing meanings; the list
is what says *which* address ended how, where those counters only say how
many. A `--url` run naming one job carries a one-entry list.

**The index has no second page.** `?page=2`, `?limit=10`, `?offset=100` and
`?domain=Finance` each returned a byte-identical payload. `--pages` above 1
is ignored in `--mode listings` and `--mode careers`, with a log line
saying so. `--mode job` is the mode that paginates, and there a page is one
job.

**Rates are not all hourly.** `hourly` 347 / `per-task` 31 / `one-time` 9 /
`yearly` 3 of 390 on 2026-09-18; 267 / 27 / 8 / 3 of 305 on 2026-10-07. Read `rate_period` before doing arithmetic on
`rate_min`/`rate_max` — and note `commitment` is a *different* axis (how
much time is asked for: hourly 228, part-time 104, task-based 35, full-time
23). A task-based commitment can still be paid an hourly rate, and 31 are.

**`rate_currency` is null on every listings row.** The index publishes no
currency anywhere, so the column is null rather than a defaulted `"USD"`.
Detail pages do state one — USD on 40 of 40 sampled — and `--mode job`
fills it. The careers route publishes USD *and* GBP, so nothing is assumed
there either.

**The site's own JSON-LD is incomplete — do not use it.** `/explore` ships
an `ItemList` beside a React Query cache of full records, and the `ItemList`
is always the smaller view: 326 against 390 on 2026-09-18, 237 against 305 on
2026-10-07. What it omits is every `evergreen` listing plus a few standard
ones (55 + 9 then, 60 + 8 now). This scraper reads the cache; a parser
anchored on the JSON-LD would silently lose about a fifth of the catalogue.
A response whose cache is EMPTY beside an `ItemList` that lists jobs is
treated as a parse failure, not an empty index.

**Zero is not always missing.** On the careers route, "Mercor AI Safety Fund
Grants" states `$0` and means it (a grant programme); two other roles
withhold their pay. The site's own `shouldDisplayCompensationOnJobPostings`
flag tells them apart: a stated zero is written through as `0.0`, a withheld
figure is `null`, and `compensation` keeps the site's string either way.

**Hydration rewrites every job link.** The served markup has
`href="/jobs/list_…"`; the live DOM has `href="/explore?listingId=…"`. It
costs nothing here (rows come from `__NEXT_DATA__`, not the DOM) but it
will bite anyone writing a DOM-based selector against a saved capture.

---

## Output

One row shape across all three modes — `JobPosting` in `output_writer.py`.
See [`sample_output.json`](sample_output.json) and
[`sample_output.csv`](sample_output.csv), both cut from real runs on
2026-09-18 and including the same listing read **both** ways so the join on
`sku` is visible.

The family prefix — `source`, `scraped_at`, `url`, `sku`, `title` — is
byte-identical and in that order across every repo in this family.

There is no `price`, `currency`, `discount_pct`, `in_stock` or `brand`
column: this is a job board, and six columns null on every row of every run
are worse than absent ones. There is no `rating` either, and that is a
measurement — Mercor publishes no rating, score or review count for a
listing, a client or a contractor on any route read here.

`data_source` says which route produced a row (`explore` / `detail` /
`careers`), because **neither route is a subset of the other**: the index
has `domain`, `posted_at` and the slot counters; a detail page has the
company website, the company description and a currency. Checked field by
field on the same job: **zero disagreements** on the 37 columns both
publish.

**Exit codes:** `0` ok · `1` crash · `2` bad usage · `3` blocked · `4` the
site answered and the answer was empty · `5` the content was never obtained
or could not be read — a dead proxy, a timeout, a page whose shape the parser
no longer recognises · `6` partial (rows kept, something missing).

`4` and `5` are different claims and a pipeline should branch on them. A
page that was SERVED but in which the parser cannot find where the records
would be (a renamed key, say) is `5` with stop reason `parser_found_nothing`
and the page named in `pages_unreadable` — never `4`, which would tell you
the site had nothing. `--retries` counts attempts, so `--retries 0` is a
usage error (exit 2).

**A 404 or 410 from Mercor is `4`, and it is `4` on every path.** A job
address the site answers 404 or 410 for (stop reason `completed`, the address in
`urls_not_found`) is a real answer from the site: the job is gone. The
browser engines read that 404 from the navigation's status. Through
`scraper_api_client.py` it arrives as the `http_code` of an HTTP 200 Scraper
API response, because the API reports the target site's status there rather
than as an API error. A non-200 from the Scraper API itself (its own 404
means an unknown task id; 402, 408 and 422 are its other refusals) is `5`,
because then nothing was obtained from Mercor at all.

**A 5xx from Mercor is `5` (or `6` after earlier rows), never `4`.** A server
error says nothing about what the page holds. The page is fetched again
within the existing retry budget. If every attempt is a 5xx, the page is
failed (stop reason `target_http_5xx`), and the sidecar records the status
per page in `pages_target_http_error`. That status is the navigation's own in
the browser engines and `http_code` through the Scraper API. With no rows,
nothing is written, so earlier good output and its sidecar stay as they were.
Only when nothing earlier exists at `--out` does `--allow-empty` write a
`failed` sidecar on its own.

**A 403 from Mercor is `3` (blocked), and a 429 is `3` once it persists.**
Both pages are fetched again within the same block-retry budget as any
refusal: a different exit with a proxy pool, or one plain re-fetch without
one. A 429 waits longer before each new attempt. The pause starts at twice
`--retry-delay`, doubles with each attempt and is capped at 60 s. Through
`scraper_api_client.py` the same pause applies between its `--retries`
attempts. A page that is still refused ends the run with stop reason
`blocked_refused` (403) or `throttled` (429): exit `3`, or `6` after earlier
rows. Nothing about the page's contents is concluded either way. A 429 is
never solved.

**Any other non-2xx from Mercor is `5` too.** A 400 or 401, for example,
even with an empty payload. The stop reason is `target_http_error`, the
status goes into `pages_target_http_error`, and the page is not retried.

**No job data is `4` only when the site says so.** That means a 2xx page
whose own payload container is present and empty. A served page that
carries neither records nor that empty container is a parser failure. It is
`5` with stop reason `parser_found_nothing` and the page in
`pages_unreadable`, or `6` after rows. This covers a page that stayed
unreadable through its retries and wait. Such a page used to end as `4`
"completed".

A run that finds nothing **writes nothing**, so last night's good output is
never replaced with `[]`.

**`--allow-empty` is for a genuine empty result only.** With it, a run that
finished and found nothing writes an empty JSON (`[]`), a CSV holding only
its header, and a sidecar with `status: empty` and its `stop_reason`. It
still exits `4`. It never turns a blocked or failed run into an empty one:
- blocked still exits `3`;
- never obtained or parser failure still exits `5`;
- partial still exits `6`.

For the zero-row failures no row file is written, and an earlier output at
the same `--out` is left untouched, sidecar included. Only when nothing
earlier exists there does a blocked or failed `--allow-empty` run write a
sidecar on its own, with `status: blocked` or `failed`. `diff_runs.py`
compares an `empty` run like a complete one.

---

## Engines

Playwright is primary. All three agree on exit codes, run status and the
rows themselves — verified live on 2026-09-18 across all three modes, with
row output identical except one listing whose `remaining_slots` changed
between runs, which is the site and not the engines.

```bash
pip install -r requirements.txt -r requirements-playwright.txt  # then: playwright install chromium
pip install -r requirements.txt -r requirements-selenium.txt
pip install -r requirements.txt -r requirements-puppeteer.txt
```

**Install exactly one.** Playwright and pyppeteer declare mutually
unsatisfiable pins (`pyee` <12 vs ≥13), and pyppeteer and selenium collide
on `urllib3`. Use a virtualenv per engine if you need more than one.

Known limits, stated rather than left to be discovered:

- **`--concurrency` works in the Playwright engine only.** Selenium and
  pyppeteer accept the flag — it is part of the family's CLI contract — and
  log that they are ignoring it, fetching one page at a time. Parallel
  fetching is implemented in `playwright_scraper.py`, which is the primary
  engine. This matters only in `--mode job`, the one mode with more than one
  page to fetch.
- **Selenium cannot use an authenticated remote CDP endpoint.**
  chromedriver's `debuggerAddress` takes a bare `host:port` with nowhere to
  put a password, unlike Playwright's `connect_over_cdp` and Puppeteer's
  `browserWSEndpoint`.
- **Selenium's `--proxy-server` cannot authenticate at all.** Credentials are
  stripped and warned about rather than silently ignored.
- **pyppeteer is effectively unmaintained** — its own README points at
  Playwright.

Everything else is identical, and "identical" here means verified rather
than intended: same flags, same exit codes, same run status, same rows.

`scraper_api_client.py` is a fourth path that renders the page on 2Captcha's
infrastructure and returns HTML over plain HTTPS. On this site it is the one
with the least to recommend it, because nothing here needs someone else's
exit.

---

## What the 2Captcha products are for

Four separately-billed products behind one key. On this site none of them
is required, and saying what each actually buys is more useful than a pitch:

- **Proxies** — not for access. For *volume*: `--mode job` can fetch every
  detail page the enumeration holds (hundreds), and spreading those across exits is politer than sending
  them all from one address. `--concurrency N` without a pool sends N× the
  traffic from a single IP, and the engines warn about it.
- **Scraping Browser API** — a specific exit **country**, and no local
  Chromium to install. `--cdp-endpoint`. One live connection per profile, so
  `--concurrency > 1` is refused with that reason; use several `pid`s.
- **Fingerprints** — `--fingerprint`. Never combined with `--cdp-endpoint`:
  the remote browser brings its own, and stacking a second creates a
  contradiction rather than better cover.
- **Captcha solving** — see below.

### Captchas: what is actually here

Mercor has **never rendered a challenge** to this scraper. But "no challenge
rendered" is not "no captcha configured", and on this site the distinction
has teeth.

**The marketplace host runs invisible reCAPTCHA Enterprise. The corporate
host runs nothing.** Measured in a live browser on 2026-09-18:

| Route | reCAPTCHA |
|---|---|
| `work.mercor.com/explore` | **yes** — `enterprise.js`, anchor iframe, `size=invisible` |
| `work.mercor.com/jobs/{id}/{slug}` | **yes** — same |
| `work.mercor.com` 404 pages | **yes** — same |
| `www.mercor.com/careers` | **none** — zero captcha requests, zero iframes |
| `www.mercor.com` (home) | **none** |

Sitekey `6LcUUCgsAAAAAD_LMM5QDj1qUwsfKYDbNKa0v5wO`, loaded from
`https://www.google.com/recaptcha/enterprise/anchor?...&size=invisible`.
So `--mode careers` runs past no captcha at all, and the other two modes
run past one that never stops them.

Three things about it matter:

1. **It is invisible to a capture.** The sitekey appears in no served HTML
   and in none of the eagerly-loaded JS bundles — it arrives in a lazily
   loaded chunk. Grepping a saved page for the site's own captcha config
   finds nothing; only a real browser reveals it. A static marker count
   across seven captures returns zero for every reCAPTCHA spelling.
2. **It never blocks.** No `bframe` (challenge) iframe was rendered on any
   route, on any run: it scores the session in the background and Mercor
   served every row alongside it (390 on 2026-09-18, 305 on 2026-10-07). So it must never be paid for on a page
   that already has content — which is what `--solve-captcha when-blocked`
   (the default) enforces.
3. **The variant is inferred, not confirmed.** `size=invisible` with no
   challenge frame and no `render=explicit` reads as v3, and that is what
   this repo's detector classifies it as — but a v2-invisible that simply
   never challenged would look identical from outside. Nothing here depends
   on the answer, since no solve is ever attempted; it is flagged because
   a v3 parameter sent for a v2-invisible widget buys a token the
   site rejects, so anyone who *does* start solving here should settle the
   variant against a real challenge first.

This repo **does** implement enterprise reCAPTCHA
(`RecaptchaV2EnterpriseTaskProxyless`), ordinary reCAPTCHA v2/v3, and
Cloudflare Turnstile (`TurnstileTaskProxyless`, with the
`turnstile.render` interception a Managed Challenge requires). It has
simply never needed any of them here. If Mercor's posture changes, the
machinery is already in place.

One more measured non-finding: Mercor is fronted by Cloudflare, and every
page — including both 404s — carries `/cdn-cgi/challenge-platform`. That is
Cloudflare's ordinary bot-management script, **not** a challenge. It was
briefly in this repo's marker set and made a delisted job report exit 3;
counting it on pages known to be good is what caught that.

---

## Configuration

Credentials live in `.env` next to the scripts, never on a command line — a
secret in `argv` is readable by anything that can run `ps`.

```bash
cp .env.example .env
python3 env_config.py          # prints what was picked up, without secrets
```

Precedence, highest first: **explicit flag → exported env var → `.env` →
default.** A copied `.env.example` reads as *unset* for every credential, so
it is never sent to an API as if it were a key.

Variables: `TWOCAPTCHA_KEY`, `MERCOR_CDP_ENDPOINT`, `MERCOR_PROXY`,
`MERCOR_URL`.

`MERCOR_URL` ships commented out, because every mode already has a default.
If you set it and then type a `--mode` that reads a different route, the
variable is ignored for that run; a typed `--url` that disagrees with
`--mode` is still refused.

---

## Comparing two runs

```bash
python3 diff_runs.py --old monday.json --new tuesday.json
```

Joins on `sku`. It **refuses** to compare runs that

- are not both `complete` — a partial run's un-fetched pages would otherwise
  read as delisted jobs;
- have no `.meta.json` beside them, because completeness cannot then be
  checked (`--force` overrides, for output you know is whole);
- selected different things: another `--mode`, another `--domain`, another
  start URL. Two complete runs under different filters are two slices of the
  index, and every difference between them would be the filter;
- come from different populations (careers against the marketplace share no
  ids at all).

When a `--mode job` run fetched fewer jobs than it enumerated, the headline
says listings *entered* or *left the slice* rather than were added or
removed — `--pages` and the sitemap order decide what a slice holds, so a
listing missing from it has not been shown to be gone — and `--fail-on-change`
ignores that movement. A real change to a listing both runs hold still fails
it.

A price difference that comes with a `data_source` difference is reported as
`source_changed` rather than `changed`: that says something about our two
snapshots, not about the site.

---

## Testing

```bash
python3 smoke_test.py          # the offline suite; no network, no engine needed
python3 smoke_test.py -v       # print every check
pytest                         # same checks, via tests/test_smoke.py
```

Fixtures are cut from real captures taken 2026-09-18, and each was verified
to parse **identically** to its untrimmed original before being committed.

CI runs the suite offline on the oldest and newest supported Python, builds
and runs the Docker image, and installs each engine in its own virtualenv to
check the versions users actually get. The **canary** runs a real scrape
weekly (Mondays) from a bare GitHub runner with no secrets — which is what keeps this
README's central claim honest. If Mercor ever puts these routes behind a
challenge or a key, the badge goes red on the next weekly run and the claim is
retested without anyone having to remember to.

---

## Guides

- [How to run the 2scraper scrapers: setup, proxies, exit codes and access modes](https://2captcha.com/h/how-to-run-2scraper-open-source-scrapers) — installation, `.env`, `.meta.json` for the whole family.

## Related scrapers

Same CLI conventions, same output contract (one row per item, JSON or CSV, a `.meta.json` sidecar and shared exit codes):

- [Wellfound scraper](https://github.com/2scraper/wellfound-scraper) — Startup jobs from Wellfound with salary and equity ranges…
- [Just Join IT scraper](https://github.com/2scraper/justjoin-scraper) — Polish IT job offers with real salaries, seniority, skill…
- [Better Business Bureau scraper](https://github.com/2scraper/bbb-scraper) — BBB search and category listings with no key or proxy, plus…
- [Flippa scraper](https://github.com/2scraper/flippa-scraper) — Online businesses for sale on Flippa
- [G2 scraper](https://github.com/2scraper/g2-scraper) — Categories, product pages and pricing pages
- [Google Play scraper](https://github.com/2scraper/googleplay-scraper) — Apps, installs, rating histograms and unbounded reviews…

All scrapers: [github.com/2scraper](https://github.com/2scraper) · Need another site? [Open a request](https://github.com/2scraper/.github/issues/new?title=%5BScraper%20request%5D%20)

## Licence & contributing

MIT — see [LICENSE](LICENSE). Bug reports and site-change reports are
welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) and the issue templates.
Scrape responsibly: respect `robots.txt` (this scraper reads only paths
Mercor's own `robots.txt` allows), keep request rates civil, and do not
republish personal data.
