# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/) as
closely as a CLI toolkit can. A **patch** release means fixes; it does not
mean every flag and default is frozen, so a behaviour-changing default can
land in one — and when it does, the entry leads with it so nobody discovers
it from a bill or from a diff.

## [Unreleased]

## [0.1.2] — 2026-10-16

> **Behaviour change: `--allow-empty` writes an empty file only for a genuine
> empty result.** Its sidecar now says `status: empty` (it was `failed`), and
> `diff_runs.py` accepts it. A blocked or failed run with `--allow-empty` no
> longer replaces earlier output with `[]`. It keeps its exit code (3 or 5)
> and leaves that output and its sidecar untouched. With nothing earlier at
> `--out`, it writes only a sidecar, which now says `blocked` for a blocked
> run (it was `failed`).
>
> **Behaviour change: no job data is exit 4 only when the site says so.**
> - **A served page with neither records nor the site's own empty
>   container** used to end as exit 4 `completed`. That includes a small
>   200 that stayed unreadable through its retries. It is now
>   `parser_found_nothing`: exit 5, or 6 after rows, with the page in
>   `pages_unreadable`.
> - **An unexplained non-2xx** (not 404/410, 403, 429 or 5xx) is content
>   not obtained, even with an empty payload: exit 5 (6 after rows), stop
>   reason `target_http_error`, status in `pages_target_http_error`, not
>   retried.
> - **Everywhere.** This applies in all three engines and
>   `scraper_api_client.py`. A `parse_error` in the API client now goes
>   through `finish_run` too.

> **Behaviour change: target 410 and 429 are decided by their status.**
> - **410 means the page is gone.** Mercor's 410 is now `not_found`, like a
>   404: exit 4, fetched once, and counted in `jobs_not_found`. Before, it
>   was retried and ended as exit 5 (or 4 if the body held an empty
>   payload).
> - **429 means throttled.** Mercor's 429 is a new `throttled` state. It
>   used to be exit 4, "completed", whenever its body had no payload. It is
>   now retried within the existing block-retry budget, with a pause that
>   starts at twice `--retry-delay`, doubles and is capped at 60 s. If it
>   persists, the run stops with `throttled`: exit 3, or 6 after rows.
> - **Everywhere.** This applies in Playwright, Selenium, pyppeteer and
>   `scraper_api_client.py`.

### Changed

- CI only: the canary now runs weekly (Mondays 05:40 UTC) instead of daily, and on a manual dispatch.
- **A refused page has the same stop reason in every engine.** A 403 now
  ends with `blocked_refused` in Selenium and pyppeteer, which said
  `blocked_cloudflare (hard block)`; Playwright already said
  `blocked_refused`.
- **`scraper_api_client.py` refuses through `finish_run`.** A 403 or a
  persistent 429 goes through `finish_run` like the browser engines. That
  means exit 3, earlier output is kept, and with `--allow-empty` a sidecar
  is written that names the stop reason. Before, it returned a bare 3.
- **Offline checks.** They drive each engine's real `scrape()` and the real
  API client through 410, 403 and 429. Each one asserts the exit code, the
  number of fetches, the stop reason, that the pause is used for 429 only,
  that earlier output is kept, exit 6 after a good page, and that a 429
  which clears gives exit 0.

## [0.1.1] — 2026-10-16

> **Behaviour change: a Mercor 5xx is no longer exit 4.** A page the site
> answered with a server error used to be counted as served, and a run whose
> only page was a 503 said "empty result" (exit 4). Now the page is retried
> within the existing budget and then reported as content not obtained. That
> is exit 5 on the first page and exit 6 after earlier rows, with stop reason
> `target_http_5xx` and the status in `pages_target_http_error`. This applies
> in Playwright, Selenium, pyppeteer and `scraper_api_client.py`, where the
> status is the Scraper API's `http_code`. A Scraper API answer of
> `status: "error"` with no target status is exit 5 too. A 404 is still
> exit 4.

> **Behaviour changes for an existing user — read these before upgrading.**
>
> - **A page the site served and the parser could not read is exit 5, not
>   exit 4.** Exit 4 says the site answered and the answer was empty; for a
>   renamed key that was false. A genuinely empty index is still 4.
> - **A run that could not read one of its two enumeration sources is
>   `partial` (exit 6), no longer `complete`.** The rows are kept. Each
>   source is tried `--retries` times first.
> - **`--retries 0` is a usage error (exit 2).** It used to skip navigation
>   altogether, wait 45 s and report exit 4.
> - **`diff_runs.py` refuses more**: a run with no `.meta.json`, and two runs
>   that selected different things (`--mode`, `--domain`, start URL). Both
>   are `--force`-able. `scraper_api_client.py` now writes the sidecar this
>   requires.
> - **`--solve-captcha always` would pay for a solve on every marketplace
>   page** — see the correction below. The default does not.
>
> **Also changed in this release (2026-10-15).** `--pages`/`--concurrency`
> below 1 and a negative `--delay`, `--retry-delay` or `--proxy-block-retries` are
> now usage errors (exit 2) in every engine. A `MERCOR_URL` from `.env` that
> names a different route from the `--mode` you type is now ignored for that
> run instead of exiting 2, and `.env.example` ships it commented out. CSV
> cells that begin with `=`, `+`, `-`, `@`, a tab or a line break now get a
> leading apostrophe (CSV only; JSON is unchanged; the sidecar records
> `csv_cells_escaped`). Output files are replaced atomically and keep their
> mode.
>
> **A correction to what 0.1.0 said, which stays below as written.** 0.1.0
> claimed "Mercor runs reCAPTCHA v3 Enterprise on every page". Measured in a
> live browser afterwards: invisible reCAPTCHA **Enterprise** on
> `work.mercor.com` only (index, detail pages and its 404s); `www.mercor.com`
> and `/careers` load none, so `--mode careers` meets no captcha at all. And
> "v3" is an inference — invisible with no challenge frame reads as v3, but an
> unchallenging v2-invisible looks identical. Nothing depends on the variant
> here because no solve is attempted.

Found by a third-party audit of 0.1.0 (taken at `ceeb142`), every claim of
which was reproduced before it was worked, plus what running the fixes found.

### Fixed

- **`scraper_api_client.py` handles a Mercor 404 the way the browser engines
  do.** The exit code was already 4 and stays 4. A dead job answered through
  the Scraper API (HTTP 200 with `http_code: 404`) is now named `not_found` in
  the log. With `--allow-empty` it also writes the same empty output and
  sidecar as Playwright (`stop_reason`, `urls_not_found`, `jobs_not_found`).
  Before, it returned 4 with no sidecar and logged "0 jobs parsed". A
  non-200 from the Scraper API itself is still exit 5. A served page with
  no records (exit 4) now also goes through the shared writer, so
  `--allow-empty` writes its output and sidecar on that path too. An offline check
  runs the client against a sanitized real Mercor 404 and the Playwright
  engine against the same page, and compares the two.
- **A failed write no longer destroys the previous good output.** JSON, CSV
  and `<out>.meta.json` were opened with `"w"`, so a write that failed
  halfway (measured: an unserialisable row) left a 1,042-byte `out.json` as
  96 bytes of invalid JSON. Each file is now written to a temporary file in
  the same directory, flushed, fsynced and renamed over the target; the
  temporary file is removed on error. A new file gets the mode `open()`
  would have given it (`0o666 & ~umask`); an existing file keeps its own.
- **CSV formula cells are neutralised.** Titles, descriptions and company
  names are third-party text; a cell beginning with a formula character is
  prefixed with `'` (after list columns are joined), numbers are left alone,
  and the count goes in the sidecar under any value the caller set.
- **`cp .env.example .env` no longer breaks `--mode job` and `--mode
  careers`.** The example set `MERCOR_URL` to the index, which the URL/mode
  check then treated as if the user had typed `--url`. The engines and
  `scraper_api_client.py` now remember whether `--url` was typed; a typed URL
  that disagrees with `--mode` is still refused. `scraper_api_client.py`
  now also refuses a typed URL for another route and defaults the index and
  careers modes to their own address.
- **The captcha allowance is spent by purchases, not by checks.** The first
  of the two solve call sites counted itself against `SOLVES_PER_PAGE`
  before knowing whether a challenge existed, so on a page that classified
  as blocked the solve the state policy asks for could never run. The count
  now happens at the moment a task is submitted; still at most one purchase
  per page.
- **The credential scan read nothing from some checkouts.** Its skip list
  was matched against the ABSOLUTE path, so a clone under any directory
  named `build`, `venv`, `env`, `.venv` or `__pycache__` scanned 0 files and
  printed "ok". Exclusions are now relative to the repository, a scan of 0
  files fails, and `.env*` files and `.json`/`.csv`/`.toml`/`.cfg`/`.ini`/
  `.sh` files are read too.
- `.gitignore` covers `--dump-html` page files without an `.html` suffix
  (`X.page2`), raw `.html` dumps at the top level and live-run directories
  (`live/`, `out/`, `results/`, `tmp/`, ...).
- `--locale` and `--retries` help, and several comments, described other
  sites' parameters and pages; they now describe Mercor's.
- Comments, docstrings, workflows and the README pointed at numbered
  sections of an instruction file readers cannot open. The reasons are now
  stated in place, and a check fails if such a pointer returns.
- Canary: the careers job no longer requires 80% of roles to publish a
  salary (that is the employer's choice); it now requires every published
  salary figure to be parsed into a rate.
- **A withdrawn listing ended the whole `--mode job` queue.** Three enumerated
  addresses, the second a 404, gave ONE row, `status: complete`, exit 0,
  `stop_reason: no_new_products`, the third never fetched. "This page added
  no new sku" is the end-of-listing signal for slices of one result and wrong
  for independent addresses — and it was any empty page, not only a 404, in
  the sequential loop AND in the concurrent worker. Decided once in
  `page_flow.a_page_without_rows_ends_the_run`; withdrawn addresses are now
  recorded in the sidecar (`urls_not_found`, `jobs_not_found`).
- **A lost enumeration source was a log line.** Sitemap raising, 7 index
  records, 100 pages asked for → 7 rows, `complete`, exit 0. The list now
  travels with its provenance (`EnumerationResult`), a source fails if it
  raised OR answered and held nothing, exception text is scrubbed before it
  is stored, and the run is `partial` with `enumeration_failures` in the
  sidecar. The logic exists once in `product_parser`, not three times.
- **A renamed key read as an empty index.** `listings` → `listingsV2` gave
  `empty`, zero rows. The container's presence is now asked separately from
  its length, and a response that contradicts itself (an empty payload beside
  a JSON-LD listing jobs) is a parse failure. Fixing the label was not
  enough: an unreadable page was `ok` to the engine, so the run still ended
  complete with no rows and exit 4. Unreadable pages are now failed pages
  by number (`pages_unreadable`).
- **Selenium and pyppeteer crashed with `AttributeError` when a retryable page
  state met no `--proxy`** (`mask(pool.current)` on `None`); pyppeteer's
  load-failure rotation crashed on ANY repeated load failure without a
  proxy. Found by pointing a real browser at an unreadable page, the first
  time that state was reachable. Guarded by an AST check over every use.
- **`diff_runs.py` ignored the selection it was comparing.** `domain_filter`
  was written to the sidecar and never read back, so two complete runs under
  `--domain Finance` and `--domain Software Engineering` diffed as 2 added,
  2 removed. A run with no sidecar passed as "nothing to check". A
  `--mode job` run that fetched fewer jobs than it enumerated reported
  "removed" for listings that were merely outside its slice; it now says
  they left the slice, and `--fail-on-change` ignores that movement.
- `--retries 0` (above), and three `--help` strings stating another site's
  facts as this one's: `--locale` named `find_country`, `--solve-captcha`
  claimed "a scored address gets a managed challenge on every route here"
  (false, and contradicting the README) and said three different things in
  three engines. The texts live once in `page_flow` now.
- **User-visible strings stated live counts as current** ("390 contract
  roles", "72 of the 462 listings", `--pages 462`). Removed; a guard fails
  on one coming back.
- `scraper_api_client.py` classified every page as a listing (it never passed
  `mode`), and answered exit 4 for a page it could not read.
- **The HTTP status never reached the classifier**, so a withdrawn listing
  read as `empty`. There is no body to fall back on — the live 404 carries
  `__NEXT_DATA__`, its visible text is empty, and "404" appears *more* on
  good pages (7 and 17) than on the 404s (1 and 2). Playwright and pyppeteer
  bind `goto()`'s response; Selenium reads Chrome's performance log; the
  cross-engine fallback is that Mercor bounces a dead address to `/login`.
- **The mirror engines never told the classifier which mode they were in.**
- **A stated `$0` was banned along with a withheld salary.** "Mercor AI Safety
  Fund Grants" prints `$0` and means it; two roles withhold their pay. Told
  apart by the site's own `shouldDisplayCompensationOnJobPostings` flag,
  which the parser now obeys rather than merely coincides with. Found by the
  canary on its first dispatch.
- The `engine-smoke` CI job grepped for a phrase the suite never prints, so
  it could not fail. It also gained a check that the suite ran to completion.
- `diff_runs.TRACKED_FIELDS` named 25 fields of which this row class had four,
  so a rate going 100 → 999 diffed as "0 changed". Now this site's 23, pinned
  against the dataclass.
- `--concurrency` works in the Playwright engine only; that is now stated in
  the README and pinned in both directions.
- **`diff_runs.py` never reported `source_changed`.** Its one-source column
  list named another site's fields (`equity_min`, `company_badges`, ...),
  none of which `JobPosting` has, so the same listing read from the index
  and from its detail page came out as a `changed` row. It now lists this
  site's one-source columns (`domain`, `employment_type`, `rate_currency`,
  `company_website`), and a new check replays the pair in
  `sample_output.json`. Its usage example and its output line also
  described another site's flags and "profile" rows.
- `selenium_scraper.py` and `puppeteer_scraper.py`: a post-run block keyed
  on `--mode role`, which this repo does not have, so the `/explore`
  coverage note never printed. It now runs on `--mode listings`, as it does
  in `playwright_scraper.py`. The dead thin-page constant went with it.
- `--pages` help in all three engines described another site's
  pagination (`--mode role`, "page 48 of a 47-page listing"). It now says
  what this site does: only `--mode job` paginates, one job per page.
- `scraper_api_client.py --help`: the description said `--cdp-url` was
  required because Mercor refuses datacentre exits (false: every route was
  served to one), `--mode` claimed a default of "profile", `--url` named
  another site's routes, and `--category` claimed to tag rows.
- Issue templates: the bug report and site-change templates were written
  for another site (its bot vendor, URLs and columns). Rewritten from this
  README. Three links to a `TROUBLESHOOTING.md` that does not exist, one of
  them in `--dump-html` help, now point at the README's "Traps that look
  like bugs".
- `CONTRIBUTING.md`: removed four bullets describing another site's routes,
  pagination and pay strings.
- `.gitignore` / `.dockerignore`: another site's output prefix replaced with
  this repo's default, `mercor_jobs` (and `mercor_jobs_scraperapi`).
- Stale comments naming donor behaviour as this repo's, in the engines,
  `captcha_solver.py` (a pointer to a section that does not exist) and
  `smoke_test.py` (now names the sibling it happened in).
- **The Scraper API path sent `waitFor` in a form the live API rejects,
  and read the wrong field as the target's status.** Measured 2026-09-23
  against `scraper.2captcha.com/tasks/sync`: `waitFor` sent as a
  JSON-encoded string (what this client built for every `--wait-*` flag)
  is answered HTTP 422 "params.waitFor must be an object" and is still
  billed ($0.0005); the same request with an object gets HTTP 200. It is
  now an object. And the response's `status` is the API's own verdict
  ("success"), not the target site's HTTP code, which is `http_code` —
  so a target 403 or 503 never reached the page classifier. The target
  status is now read from `http_code` (falling back to `status` only if
  that is an integer). Pinned by an offline check that drives the real
  client with `requests.post` stubbed; verified by control (red with the
  old client).
- `SECURITY.md` said this project has no releases or version tags; it has
  both. "Supported versions" now names the latest release and `main`.

### Measured on 2026-10-07, from the same Hetzner address (AS24940, Helsinki)

All three engines served all three modes, exit 0: `--mode listings` 305 rows,
`--mode careers` 113, `--mode job` 3 and, with four workers, 8 of 306
enumerated. A real dead address planted in the middle of a real enumeration:
3 rows from 4 addresses on all three engines (it was 1), the dead one recorded
by address, the run `complete`. A simulated lost sitemap: all three engines
`partial`, exit 6, identical sidecars. A simulated renamed key: all three
exit 5, nothing written.

The catalogue moved. `/explore` held 305 records (390 on 2026-09-18), the
sitemap 304 (447), shared 303 (375), union 306 (462). The structural claims
held — neither source contains the other, and the JSON-LD `ItemList` is
always the smaller view, omitting every `evergreen` listing (55 + 9 then,
60 + 8 now). The SIZE of the sitemap-only gap did not: 72 → 1. No count in
this project's messages is a fact about the site; the sidecar carries the
run's own.

### Notes for anyone extending this

- **A guard written to watch a call can be blinded by moving the text out of
  the call.** The donor-words check first walked only calls that produce text;
  a control planted the word into a shared constant and stayed green. It now
  reads every non-docstring string constant (2,130 measured, 0 hits).
- **A control that stays green is a finding.** Two did here, and both were the
  suite's: a check gated on importing an engine skips for exactly the engine
  whose driver is absent from that venv, so a mirror's control must run in
  the mirror's own venv.
- **A fixture invented by hand will pass the check written against it.**
  `NOT_FOUND_HTML` carried `<h1>404</h1><p>Page not found</p>`, which this
  site has never served; the real 404 has no visible text at all. Replaced
  with the real capture, scrubbed of its Sentry ids, nonce and key.

## [0.1.0] — 2026-09-18

First release. Scrapes [mercor.com](https://mercor.com) with Playwright,
Selenium, Puppeteer, or the 2Captcha Scraping Browser API over CDP.

### Added

- **Three modes**, because the site publishes three different things:
  - `--mode listings` (default) — `work.mercor.com/explore`, the marketplace
    index. **390 contract roles in one response** with rate ranges, the
    site's own `domain` category, work/residence eligibility and slot
    counters.
  - `--mode job` — `work.mercor.com/jobs/{id}/{slug}`. One listing per page,
    adding the company website, company description, spot counts and a
    **currency** the index does not publish. This is the paginated mode: a
    "page" is one job, and the addresses come from a real enumeration rather
    than a guessed `?page=N` convention.
  - `--mode careers` — `www.mercor.com/careers`, Mercor's own salaried roles
    via the Ashby ATS. A different population with its own id space, so
    `diff_runs.py` refuses to compare it against the other two.
- `--domain`, a client-side filter on the site's own category, documented as
  client-side because Mercor's index accepts no query parameters at all.
- One `JobPosting` row shape across all three modes, with the family's
  `source, scraped_at, url, sku, title` prefix byte-identical and in order.
- All three engines plus `scraper_api_client.py`, agreeing on exit codes,
  run status and rows — verified live across all three modes.
- An **ungated** daily canary: a real scrape from a bare GitHub runner with
  no secrets, expected green. See below for why that is the point.

### Measured on 2026-09-18, from a Hetzner datacentre address (AS24940, Helsinki)

Every number in the README and in the code comments is dated and tied to
this run. The ones that shaped the design:

- **Nothing is gated.** Eighteen candidate bot-challenge markers counted
  across seven captures — all zero. Identical 200s from `curl`, from
  `python-requests` and from an **empty** User-Agent. Twelve rapid detail
  fetches, all 200 at ~0.4 s. No key, no proxy and no account is needed for
  any route this scraper reads.
- **The site's own JSON-LD index is incomplete.** `/explore` ships an
  `ItemList` of 326 URLs beside a React Query cache of **390** full records;
  the 64 it omits are all 55 `evergreen` listings plus 9 standard. This
  scraper reads the cache. A parser anchored on the JSON-LD — the obvious
  choice — would silently lose 16% of the catalogue.
- **No single route enumerates the catalogue.** sitemap 447, index 390,
  shared 375, **union 462**; neither contains the other, and all three
  sitemap-only listings checked were live. `--mode job` fetches the union,
  and a `--mode listings` run records in its sidecar that it holds 390 of
  them.
- **`/explore` has no second page.** `?page=2`, `?limit=`, `?offset=` and
  `?domain=` each returned a byte-identical payload, so `page_url()` returns
  None by design rather than manufacturing an address the site does not
  honour.
- **Mercor runs reCAPTCHA v3 Enterprise on every page** — invisible, found
  through `___grecaptcha_cfg` at runtime. Its sitekey is in no served HTML
  and in none of the eagerly-loaded JS bundles, so a static grep for the
  site's own captcha config finds nothing; only a real browser reveals it.
  It never renders a challenge and must never be paid for, which
  `--solve-captcha when-blocked` (the default) enforces.
- **Pay is not all hourly**: `hourly` 347, `per-task` 31, `one-time` 9,
  `yearly` 3 across the 390. And `commitment` is a different axis from
  `rate_period` — a task-based commitment can still be paid hourly, and 31
  are.
- **Currency is read, never defaulted.** Null on every index row (the route
  publishes none), USD on 40 of 40 sampled detail pages, and USD **or GBP**
  on the careers route.
- **`/explore`'s ordering is stable** — three fetches returned the identical
  390 ids in the identical order — while the slot counters are live and
  drift within minutes.

### Notes for anyone extending this

Four traps cost real time here and are pinned by tests so they stay fixed:

- **`__NEXT_DATA__` carries a `nonce`** on every page of this site. A regex
  written without one matches nothing, and the failure reads like the site
  having stopped server-rendering rather than like a typo.
- **`/cdn-cgi/challenge-platform` is on every page, including both 404s.**
  It is Cloudflare's ordinary bot-management script, not a challenge. It was
  briefly in the marker set and made a delisted job report exit 3 (blocked)
  instead of `not_found`. Count every candidate marker on a page you know is
  good before adding it.
- **Hydration rewrites every job anchor**, from `/jobs/list_…` to
  `/explore?listingId=…`. A readiness selector verified against a saved
  capture can match zero elements in a live browser — silently, because the
  rows come from `__NEXT_DATA__` either way. What it costs is a full timeout
  per page, and a captcha gate that concludes "no content here" and tries to
  pay.
- **The positive-asset heuristic is inverted here.** "Was this built out of
  the site's own assets?" works on sibling sites; on Mercor the 404 is the
  same Next.js app and references `/_next/static` *more* than a real page
  does. `detect_page_state` leads with the presence of `__NEXT_DATA__`
  instead, which the 404 carries none of.
- **`diff_runs.TRACKED_FIELDS` must name columns that exist.** Ported
  verbatim it named 25 fields of which this row class has four, so the diff
  compared nothing: a listing whose rate went 100 → 999 with its status
  changed to `closed` reported *0 changed* and exit 0. A price monitor that
  cannot see a price change is worse than none, because it reports success.
  No fixture and no live run would have shown it — two runs of identical
  data report "0 changed" whether the comparison works or not — so it is
  pinned against the dataclass instead. The family has now paid for this
  twice; the first was a supermarket scraper whose price diff tracked a
  blogging platform's "claps".

[Unreleased]: https://github.com/2scraper/mercor-scraper/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/2scraper/mercor-scraper/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/2scraper/mercor-scraper/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/2scraper/mercor-scraper/releases/tag/v0.1.0
