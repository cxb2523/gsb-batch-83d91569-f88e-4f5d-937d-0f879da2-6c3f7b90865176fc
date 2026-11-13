# Contributing

Bug reports, site-change reports and pull requests are all welcome. This file
covers the few things specific to a scraper, which are not the usual ones.

## Before you open anything

Run the offline suite. It needs no network, no browser and no API key, and takes
about a second:

```bash
pip install -r requirements.txt
python3 smoke_test.py
```

It prints its own check count, and lists any group it had to skip because an
engine library is absent.

**The suite must pass with no engine installed at all.** CI installs only
`beautifulsoup4` and `requests`, so any import of `playwright_scraper`,
`puppeteer_scraper` or `selenium_scraper` in a test has to sit inside
`try/except ImportError` with the skip recorded. This is easy to get wrong
locally, where you almost certainly have an engine installed and an unguarded
import passes.

If the suite fails on a clean clone, that is itself the bug — say so.

## Never commit a credential

`.env` is in `.gitignore`. Keep it there.

The scrapers mask `user:pass@` in their own log lines, but three things are **not**
masked: raw HTML dumps, the Scraper API's `x-debug` response header, and your
shell history. Before pasting any output into an issue or a PR, replace keys,
proxy passwords and full `ws://user:pass@host:9222` endpoints with `***`.

CI fails the build if something that looks like a credential is committed. That
check is a backstop, not a review — a leaked key has to be rotated whether or
not the check caught it.

## Reporting a site change

Wellfound changing its markup is the normal way this stops working, and it
has its own issue template. The detail that saves the most time is WHICH
anchor broke — and on this site that is not a CSS selector, because the
parser does not read the DOM.

There are **two** structured sources here, belonging to different
applications, so a break is in one of them and not the other:

```
a landing page / the feed   <script id="__NEXT_DATA__"> …
                            props.pageProps.apolloState.data
a job page                  <script type="application/ld+json"> … @type JobPosting
```

So there are five things that can break, and each fails loudly except the
third:

1. **The `__NEXT_DATA__` script tag.** If it is renamed,
   `extract_next_data` returns None, the page classifies as `parse_error`
   rather than as an empty listing, and the run dumps the bytes. Loud — and
   deliberately NOT "0 jobs", because a served page that parses to nothing is
   this repo's bug and reporting it as an empty category sends you to check
   the URL instead of the parser.
2. **`props.pageProps.apolloState.data`**, the two-level nesting. Reading
   only the outer level gives a one-entry dict whose values have no
   `__typename`, which looks like an empty page rather than a wrong path.
   `apollo_state()` accepts either level for that reason.
3. **The Apollo `__typename`s** — `JobListingSearchResult` and
   `StartupResult` on a landing page, `JobListing` and `Startup` on the
   `/jobs` feed. A rename here is the one that goes QUIET on a landing page:
   rows stop appearing rather than appearing wrong. `CORE_FIELDS` in the
   engines is the guard — a coverage floor of 99% on the five columns
   Wellfound filled on 203 of 203 captured job records.
4. **The `seoLandingPageJobSearchResults({…})` cache key.** It carries the
   site's own `pageCount` AND the page number the server actually used. If
   its shape moves, pagination loses both its ceiling and its
   end-of-listing signal, and a run can start silently re-collecting page 1.
   `listing_meta()` returning all-None is the symptom.
5. **The `JobPosting` JSON-LD on a job page.** If it goes, `--mode job`
   reports `parse_error` rather than zero jobs.

If you are reporting a break, say which of those four it is, and attach the
`--dump-html` snapshot. The exact bytes are the only way to tell a parsing
bug from a page that had not arrived.

`--dump-html PATH` writes the exact bytes the parser was given, on success as
well as failure, and a run that finds nothing writes a dump and a screenshot
next to the output on its own.

## Before this repository goes public

One item cannot be undone later, so it belongs on a checklist rather than in
someone's head. **A commit on top cannot reach what a published tag and a
merged PR's refs already hold** — those stay attached to the PR and cannot be
deleted from it. Afterwards, only a fresh repository removes anything.

```bash
python3 .github/ci_checks.py --history-check
```

That applies the same credential rules CI enforces to **every blob that has
ever existed**, not just the working tree. It is deliberately not part of
`--all` and not run by CI: it shells out to git once per object, and a dirty
history needs a decision, not a red check on every push.

Then the rest of the presentation, in the order that matters:

1. `python3 smoke_test.py` green, and the canary dispatched at least once
   with the `WELLFOUND_PROXY` secret set. EVERY route on this site is
   refused to a datacenter address, and a GitHub runner is one, so the
   `listing` job needs a residential exit; without the secret it FAILS with
   an error naming it, because a canary that skipped has tested nothing.
   The `datacentre` job runs without a secret and only confirms that the
   runner's refusal is recognised as one (exit 3) rather than misread.
2. The repo description, homepage and topics set (see the family notes on
   what those should say).
3. Only then the row in the org profile README — and check it with an
   ANONYMOUS request rather than your own logged-in browser. A row pointing
   at a private repo is a 404 for every visitor, which costs more trust than
   the missing row.

## Pull requests

**Add a test for the behaviour you are changing.** `smoke_test.py` is a single
file of plain functions with inline HTML/JSON fixtures — no pytest, no
conftest, no fixtures directory. Copy the nearest existing check and edit it.

Six properties in this repo exist because they were once absent or were
measured against expectation, and cost real time. Tests pin all six, so a PR
that breaks one will fail rather than silently regress:

- **A marker that matches every page is worse than no marker**, and on this
  site the marker the rest of this family settled on is the one that lies.
  Wellfound loads Cloudflare Turnstile as part of its OWN application: it
  ships `challenges.cloudflare.com/turnstile/v0/api.js`, publishes
  `CLOUDFLARE_TURNSTILE_SITE_KEY` in its page config, and renders a widget
  into `#turnstile_widget` when one of its own XHRs is challenged. Counted
  2026-09-17: `challenges.cloudflare.com` appears **once on every served
  landing page and zero times on either refusal**, and `turnstile` six times
  against zero. `cf-turnstile` appears nowhere at all.

  So neither is in `BOT_CHALLENGE_MARKERS`, and nor is the bare
  `cdn-cgi/challenge-platform` prefix — a served page loads
  `…/challenge-platform/scripts/jsd/main.js`, Cloudflare's passive
  JS-detections beacon, while a refusal loads
  `…/challenge-platform/h/g/orchestrate/chl_page/v1`. The prefix is on both;
  the orchestrator path is not.

  What discriminates is the challenge's own bootstrap vocabulary
  (`_cf_chl_opt`, `__cf_chl`) and, positively, whether the page was built out
  of `photos.wellfound.com` / `/_next/static`. `smoke_test.py` pins it in
  both directions: no marker may appear on a served page, every marker must
  fire on both refusals, and the excluded strings must really be PRESENT on a
  served page — or excluding them would be a precaution against nothing.

- **Wellfound's own Turnstile is configured, and is a different thing from
  Cloudflare's.** The site's widget publishes its sitekey, so it is solvable
  from a static read. Cloudflare's challenge publishes none — it calls
  `turnstile.render()` once and keeps nothing — so the only way to a solvable
  task is the init script the engines install on the context before any page
  script runs. A detection without a sitekey **refuses to build a task**
  rather than paying for one the API will reject. Never write that a captcha
  cannot be solved; write that this repo does not implement X.

- **Gating is per ROUTE, not per site.** `/role/…`, `/jobs` and
  `/jobs/{id}-{slug}` are served to a residential exit; `/company/{slug}` is
  refused to one, to plain HTTP and to a real browser alike, 3 of 3 each.
  There is no `--mode company` and adding one would need a measurement, not
  an idea.

- **Walking past the last page does not fail — it repeats.** `?page=48` of a
  47-page listing answers HTTP 200 carrying page 1's rows again. Two
  defences, and the second is the one to keep: runs plan against the site's
  own `pageCount`, and the response states which page the SERVER used inside
  its Apollo cache key, so a mismatch is an unambiguous end-of-listing rather
  than a "no new sku" heuristic.

- **`/jobs` has no addressable pages, and `/role/…` does.** `?page=2` on the
  feed returns the identical 46 job ids as page 1 — it does not fail and does
  not empty. `page_flow.pagination_is_addressable()` answers per URL for
  exactly this reason; a `page_url()` used unconditionally would report a
  complete multi-page run holding one page several times.

- **Pay is a rendered STRING, and three of its shapes break a naive
  parser.** The `•` separates salary from equity and either side may be
  absent (2 of 312 values are an equity range with no salary at all, so
  taking the part before the bullet writes 0.5 into a salary column). `L` is
  the Indian lakh, 1e5 — `₹30L – ₹80L` is 3,000,000 to 8,000,000. And
  `No equity` is a STATEMENT: `has_equity=False` is a fact the listing
  published, `None` is silence. `salary_period` stays null on a listing row
  because the string carries no period; only the detail page states one.

Plus the family's own invariants, which are not negotiable:

- **A run that finds nothing writes nothing.** It must not replace a good
  output file with `[]`. `--allow-empty` is the opt-out.
- **Exit codes are a contract**, not decoration: `0` ok, `1` crash, `2` bad
  usage, `3` blocked, `4` zero rows — including a query that genuinely
  matched nothing, which is a correct answer — `5` remote API error, `6`
  partial. A pipeline branches on these.
- **An EMPTY page is never retried and never counted as blocked.** A query
  that matched nothing was served exactly as asked.
- **Credentials never reach argv or a log, and an exception message is a
  log.** The masker is global rather than first-occurrence: a Playwright
  connection error repeats the endpoint five times.
- **Merge in page order, not arrival order**, so concurrency cannot change
  the output.

### If your change needs a live run

Most do not — the suite covers the parser, the writers, the captcha
classifier and the CLI contract against inline fixtures. If yours genuinely
needs wellfound.com, say in the PR what you ran, which mode and URL, from
which exit, and what you got — including the sidecar's `total_jobs`,
`total_companies` and `pages_available`, and the coverage lines the run
prints.

Three things about running this live that are specific to Wellfound:

* **You need a residential exit, for everything.** A datacenter address is
  refused on every route including `robots.txt`, by plain HTTP and by
  headless AND headful Chromium alike. "It does not work from my VPS" is not
  a finding; it is the documented behaviour.
* **Selenium cannot send proxy credentials.** `--proxy-server` takes an
  address only, so that engine strips them and warns. To exercise it live
  against this site you need an exit that authenticates by source IP, or a
  local forwarder that adds the credentials upstream.
* **The listing is live and its counts drift.** Three requests for the same
  URL within two minutes reported `totalJobCount` of 1881, 1887, 1886 and
  1874. A small difference between two runs is the site, not a regression —
  and `position` is not stable between requests either, though it is exactly
  stable between engines run back to back (0 of 52 differed).

**Run more than the primary engine.** "Mirror them exactly" is a design rule,
not a verification. All three were run live against the same listing for the
first release and returned byte-identical rows; that is the bar.

Do not add anything that submits a form. Wellfound's pages carry an apply
flow and a sign-up flow, and this project must never touch either — an
application submitted by a scraper is a false record about a real person and
a real company.

## Scope

This repo scrapes **public pages** on wellfound.com: role landing pages, the
jobs feed and individual job pages, exactly as an anonymous visitor is served
them. Every route it accepts is allowed by Wellfound's published
`robots.txt`, and every disallowed route has no mode —
`check_every_route_this_scraper_reads_is_robots_allowed` pins both halves
against the published file. It is a check, not a runtime gate; the docstring
there says why.

Out of scope: anything behind a login, anything that submits a form
(including the apply and sign-up flows), anything that defeats a protection
rather than passing it the way an ordinary browser does, and candidate
profiles — `/u/` is disallowed by `robots.txt`, there is deliberately no mode
for it, and adding one would be a product decision about personal data rather
than a bug fix.

## Licence

MIT. By opening a pull request you agree your contribution ships under it.
