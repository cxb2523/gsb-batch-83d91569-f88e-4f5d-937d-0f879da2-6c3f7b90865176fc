# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[SemVer](https://semver.org/) as closely as a CLI toolkit can: a PATCH release
means fixes, not that every flag is frozen. A behaviour-changing default in a
patch release is announced at the top of its notes rather than discovered from
a bill.

## [Unreleased]

### Changed

- CI only: the canary now runs weekly (Mondays 06:23 UTC) and on a manual dispatch, with its optional secret `FLIPPA_PROXY` passed on every run; the daily schedule is removed.

### Security

- Locks: `certifi` 2026.7.22 → 2026.10.23 in every lock (PYSEC-2026-4320, fixed in 2026.10.18), which had turned the `pip-audit` job red. The CI-only lock also moves `filelock` to 4.2.9 on Python 3.11+ (4.1.0 on 3.10, the newest that supports it) for advisories published against 4.0.6.

### Fixed

- README: the testing section said the canary runs a scrape a day; it has run weekly since 2026-10-16.

## [0.3.0] — 2026-10-15

> **Flippa rebuilt its search page between 2026-09-28 and 2026-09-29, and
> every version up to 0.2.1 has returned 0 listings (exit 4) on every URL
> since.** This release reads the new page. Rows now carry
> `price_source: "dom"`; `monthly_profit` and `monthly_revenue` are the
> card's abbreviated figures ("USD $51.7K", three significant figures) rather
> than exact amounts; and `monetization`, `revenue_multiple`, `status`,
> `sale_method`, `sponsored`, `editors_choice`, `confidential`,
> `verified_listing` and `image_url` are null on every row, because the card
> no longer shows them. The columns stay in the schema.

> **Behaviour changes.**
> - A run that ends with **zero listings because it never obtained the
>   content** — a navigation timeout, a page that never painted, a page of
>   listings the parser could not read, a lost worker, a Scraper API error —
>   now exits **5**, not **4**. Exit 4 is kept for a listing the run can show
>   is empty (the site says it matches nothing, or the listing ran out). A
>   pipeline that treated 4 as "nothing listed today" was being told that
>   about runs that never saw the listing.
> - Output files and the `.meta.json` sidecar are created with the mode a
>   plain `open()` would give them (`0o666` minus the umask) instead of
>   `0600`, and an existing file keeps its mode.
> - `--fingerprint` is now refused (exit 2) by the pyppeteer and Selenium
>   engines, and by the Playwright engine together with `--cdp-endpoint`,
>   where it used to be accepted with a warning and ignored.

### Fixed

- **The parser reads the rebuilt search page.** Measured 2026-10-14 on the
  canary's own capture and on plain-HTTP captures of `/search`, `/fr/search`,
  `/es/search`, `/websites` and a filtered search: the embedded
  `const STATE` JSON is gone (0 occurrences), cards are `<li id="listing-N">`
  instead of `<div>`, listing links are `flippa.com/<id>-<slug>`, and a page
  holds 50 listings, not 25. The card selector is now tag-agnostic and
  excludes the filter counters that share its id prefix
  (`listing-category-count-*`); prices are read from the card's price column
  (asking, struck-through original, auction price and bid count), key data
  from a label table for the three languages the site publishes, money in
  either `USD $1,234` or `1 234 € (EUR)` form with `K`/`M` abbreviations.
  An open-to-offers listing (a price-guide range) and a partial-equity sale
  report no price, as the site prints none.
- **Empty and past-the-end pages are read from the site's own count**
  ("Show 676 results" in the filter panel): "Show 0 results" is an empty
  query (exit 4), no cards with a count above zero is the end of the listing
  (complete).
- **Pagination uses `?page=N`**, the parameter of the site's own next link.
  The old `?page[number]=N` still works and a URL carrying it is rewritten
  rather than doubled. `PAGE_SIZE` is 50, so the per-page shortfall check
  expects 50.
- **The canary checks columns that every card carries** (title, type,
  industry, country, age, monthly revenue: at least 95% non-null each) and
  that no original price sits at or below its price, instead of the share of
  rows cross-checked against the embedded JSON, which no longer exists. Row
  floor 120 of 150.

Verified 2026-10-15: a live Playwright run of
`?filter[property_type]=saas`, `--pages 3`, from a datacentre address with no
proxy and no key — 150 listings, `status: complete`, `addressable: true`,
exit 0; the canary's assertion block passes on that run's output and fails
when a column is planted null. `sample_output.*` is cut from that run (broker
names redacted). The pyppeteer, Selenium and Scraper API engines share the
parser but were not re-run live.

- **One paid captcha solve per page.** Every engine now routes its solve
  through a per-page allowance (`page_flow.SolveBudget`, limit
  `SOLVES_PER_PAGE = 1`) checked before the solver is called and not reset by
  a retry or an exit rotation. Measured with a stubbed solver and a page that
  is always a Cloudflare interstitial: a three-exit pool bought 3 solves for
  one page before, 1 after.
- **The HTTP status reaches the page classifier** in the Playwright and
  pyppeteer engines (from what `goto()` returns), so a refusal page with no
  vendor marker is classified by its status. Selenium exposes no status and
  passes none, explicitly. The Scraper API client reads the target's status
  from `http_code`; `status` is the API's own verdict string.
- **Scraper API `waitFor` is sent as an object.** The JSON-string form is
  answered with HTTP 422 and still billed. `waitFor.state` is checked against
  `load` / `domcontentloaded`.
- **The Scraper API's `x-debug` header is redacted** before it is logged.
- **CSV formula guard**: a cell starting with a line feed is escaped too, and
  the sidecar records `csv_cells_escaped` — how many CSV cells differ from
  the JSON because of it.
- **The credential scan** matches its skipped directories against paths
  RELATIVE to the repository, so a clone under an ancestor called `legacy`,
  `captures` or `venv` is no longer skipped whole, and a scan that reads 0
  files now fails instead of printing "ok".
- **A suite check needed a browser binary and a clean `~/.cache`**: the
  fingerprint-refusal check now skips when Playwright has no Chromium, and
  runs with a private HOME so a cached fingerprint cannot answer it.
- Public files no longer cite private instruction files by section number;
  the rules are stated in this repository's own words, and a suite check
  keeps it that way.
- The weekly `pip-audit` job had been red since 2026-10-05 on two new urllib3
  1.x advisories (PYSEC-2026-4175, PYSEC-2026-4177) in the pyppeteer lock.
  pyppeteer 2.0.0 still requires `urllib3<2` and the fix is only in 2.8.0, so
  they are ignored by ID beside the five already listed, and the README says
  so.

## [0.2.1] — 2026-09-29

### Fixed

Found by a family-wide pass against the template on 2026-09-29; each one
made a documented feature do less than it said while the run reported
success.

- **`--fingerprint` never patched anything.** The init script it installs
  was syntactically broken JavaScript (`( => {` — the parameter list and the
  IIFE call were missing), and a syntax error in an init script is silent:
  the page ran unpatched. Fixed, and the suite now runs `node --check` on
  that script too — the earlier check did not cover it.
- **pyppeteer could not authenticate a proxy on current Chrome.**
  `page.authenticate()` uses `Network.setRequestInterception`, which
  current Chrome no longer has ("wasn't found", exit 5 before the first
  request — measured 2026-09-29 in rosreestr-scraper, which shares this
  engine code). The engine now answers the proxy's 407 through the CDP
  Fetch domain; verified against a local Basic-auth proxy.
- **A failing suite could turn the engine CI job green.** The step ran
  `smoke_test.py | tee` under GitHub's default shell, which has no
  pipefail, so the job took tee's exit status. It now runs with
  `shell: bash`, imports the engine by name first, and the suite fails if
  any piped step lacks pipefail.
- **The engine CI jobs had been failing, unseen.** Once pipefail made the
  step's exit status real, all three engine jobs went red on the secret
  scan: it walked into CI's own `.venv-<engine>` and read pip's and
  selenium's vendored code as credentials. The scan now skips any directory
  holding `pyvenv.cfg`, whatever it is called, and still
  reads ordinary untracked files — both planted in a check.
- **The Playwright engine job never had a browser**, so the suite's
  fingerprint-refusal check — which starts Chromium before it fetches —
  crashed there with exit 1 instead of the expected 5. Also hidden until
  pipefail; the engine jobs now install the browser they drive.
- **Skipped checks were counted as passed.** A check that could not run
  printed "SKIPPED" and was added to the pass count. Skips are now their own
  count, listed at the end.
- **`env_config.py --help` read `.env`.** `ci_checks.py` runs every CLI's
  `--help`; a help screen now opens no credentials file.
- **`.gitignore` let a renamed `.env` through** (`.env.bak`, `.env.local`),
  and a run directory (`live/`) or a paged dump (`X.page3`). Now ignored by
  shape, with a check.

### Changed

- **Supply chain, as in the rest of the family.** Every dependency set now
  has a hashed lock (`requirements*.lock`, `.github/requirements-ci.lock`,
  generated with `uv pip compile`); CI, the canary and the Docker image
  install only those, with `--require-hashes`. Actions are pinned by commit
  SHA and kept current by Dependabot; `audit.yml` runs `pip-audit` on every
  lock weekly. The five urllib3 1.x advisories in the pyppeteer lock are
  ignored by ID (pyppeteer forbids urllib3 2.x) — measured with pip-audit on
  2026-09-29.

- **Connecting to the Scraping Browser API** follows one policy in every
  engine: three attempts 3 s apart for a locked
  profile or an outage, none for an expired login (401), and a message that
  names the status's own cause. pyppeteer's per-attempt timeout is 10 s (it
  reports a refused handshake only as a timeout), and the orphaned-task
  traceback that followed a correct exit is filtered.


- README and TROUBLESHOOTING say that a `--fingerprint` run on a key
  without the Fingerprint subscription stops with exit 5, not exit 1.

## [0.2.0] — 2026-09-28

Data-integrity fixes from a second review of the 2026-09-21 external audit,
and captcha and fingerprint fixes from the family core. Nearly every item
below is a case where a run could exit 0 with `status: complete` while the
output was short of what it claimed.

> **Behaviour changes for an existing user:**
>
> - A run that loses, skips or cannot parse a page is now reported as
>   **partial** (exit 6) or failed, where 0.1.0 said `complete` with exit 0.
>   A pipeline that treated exit 0 as "all pages" was already wrong; now it
>   is told so.
> - `--pages`, `--retries`, `--concurrency` and `--timeout` refuse values
>   below 1, and delays refuse negatives. That is exit 2, before any
>   request.
> - Text columns in the CSV that begin with `=`, `+`, `-`, `@`, a tab or a
>   CR are neutralised against spreadsheet formula injection. Numeric
>   columns are unchanged.
> - `.meta.json` gains `coverage` and the catalogue-integrity fields, and
>   `diff_runs.py` labels a window comparison as entered-window /
>   left-window.
> - `--fingerprint` against a Fingerprint API that refuses the key exits
>   5 with the reason. It used to crash with exit 1.

### Fixed

- **A refused Fingerprint API crashed the run with a traceback and exit 1.**
  It now exits 5, the remote-API code, with the reason and no traceback.
  The case is real: on 2026-09-28 a key with a working captcha-solving
  balance got 403 from `/fingerprint/random`, because fingerprints are a
  separate subscription.
- **Runtime captcha detection never ran, in any engine.** The in-page
  discovery script began ` => {`, with no parameter list. That is a
  SyntaxError, and it was logged at debug level. Selenium also returned the
  function instead of calling it. Both are fixed, and a discovery failure is
  now a warning. The suite now runs `node --check` on every shipped script
  and executes discovery in a real Chromium page. A script error there is a
  failure, not a skip.
- **An explicitly rendered reCAPTCHA v2 widget was classified as v3** by the
  HTML detector. 2Captcha answers a v2 task sent as v3 with
  `ERROR_CAPTCHA_UNSOLVABLE`. Found by a live solve in screener-scraper
  (2026-09-28, 2Captcha's reCAPTCHA v2 demo page), which shares this
  module; after the fix, the demo page's own server-side check returned
  `"success": true`.
- **A worker that died took its page with it.** In
  `_fetch_pages_concurrently` the page was already off the queue when the
  fetch raised, and the `except` sat outside the loop: the page appeared in
  no list at all — not in the results, not in `unattempted`, not in
  `pages_failed` — and the run reported `complete`. Each queue item now has
  its own handler, and a reconciliation pass at the end manufactures a failed
  outcome for any requested page that is in none of the three lists. The
  existing test asserted `check("...does not hang the run", True)`, which
  could not fail; it now asserts that page 4 comes back as a lost page.
- **`complete` no longer rests on the stop reason alone.** `finish_run`
  compares pages completed against pages requested for every engine, so an
  engine that loses a page without noticing still cannot publish a
  complete-looking run. Shared, because the previous check lived in no engine
  at all.
- **A page that carried listings and parsed to nothing was read as the end of
  the listing.** `page_flow` only returns `CONTENT` when it has counted
  records in the page's own JSON or cards in the DOM, so zero parsed rows
  there is a parser or schema failure. It is now `content_unparsed`, which is
  not a complete stop reason, instead of `listing_exhausted`, which is.
- **One empty page stopped dispatch for pages below it.** Workers do not
  finish in page order, so a page that came back empty could stop the run
  while lower-numbered pages were still queued — and those hold rows. The
  page that ended dispatch is now reported, and unattempted pages below it
  are a gap (`pages_unattempted`), not an exhausted listing.
- **`--retries 0` reported the site as blocking us without sending a
  request.** The attempt loop was `range(1, retries + 1)`, so zero attempts
  meant no navigation at all, a blank tab classified as an interstitial, exit
  3, and a burnt proxy rotation. `--pages`, `--retries`, `--concurrency` and
  `--timeout` now refuse values below 1, delays refuse negatives, and `--url`
  must be http(s) — including when it arrives from `.env`.
- **A scraped title could be a spreadsheet formula.** Every text column is
  written by whoever listed the business, and this project tells people to
  open the CSV in Excel. Leading `=`, `+`, `-`, `@`, tab and CR in string
  values are now neutralised; numeric columns keep their type and their sign,
  because `monthly_profit` is legitimately negative.
- **Output was written straight to its final path.** JSON, CSV and the
  metadata sidecar now go through a temporary file in the same directory with
  `fsync` and `os.replace`, so a crash or a full disk cannot leave a
  truncated file where the last good result was.

### Added

- **`coverage` in `<out>.meta.json`**, beside `status`. `status` says whether
  the run got the pages it went for; `coverage` (`exhaustive` / `window`)
  says whether those pages were the whole listing. A `--pages 3` run of a
  27-page listing is complete and a window, and `diff_runs.py` now labels the
  added/removed halves of such a comparison as entered-window / left-window
  and keeps them out of `--fail-on-change`. Price changes on SKUs both runs
  hold stay comparable either way.
- **`catalog_mutated`, `total_results_first` / `_last`, `rows_before_dedupe`,
  `duplicate_skus_across_pages`, `pages_missing`** in the sidecar. Offset
  pagination over a catalogue being edited mid-run repeats a listing when one
  is inserted ahead of the cursor and *steps over* one when it is deleted.
  Only the first leaves a duplicate, so the duplicate count is recorded
  rather than gated on — failing a run on it would turn every insertion into
  a false partial — and the deletion case is caught by Flippa's own
  `total_results` moving between the first page and the last. Measured on
  2026-09-22: two plain HTTP fetches seconds apart returned 672 then 671
  results with zero overlapping SKUs.
- **`cli_types.py`**, one set of argparse bounds shared by all four CLIs.
- **`output_writer.merge_pages` and `failure_stop_reason`**, replacing four
  copies each of the page-merge loop and the failure-to-stop-reason ternary.
- Regression coverage for all of the above, plus the first tests
  `diff_runs.py` has ever had.

### Changed

- `smoke_test.py` reports skips as `SKIP` with their reason and counts them
  separately. A check whose fixture is absent used to be asserted as a pass.
- `captures/` and `legacy/` are excluded in `.gitignore` rather than only in
  the local, never-cloned `.git/info/exclude`.
- The README no longer promises a fixed "327 offline checks"; the count
  depends on which optional engines are installed.
- `SECURITY.md` no longer claims the project has no releases or tags.

## [0.1.0] — 2026-09-21

First release of the rewritten scraper. Everything below is a difference
from the previous, unreleased version of this code, with the measurement
that justified the change.

### Added

- **Flippa's own embedded listing JSON (`const STATE = {...}`) as the primary
  parse path.** It is in the HTML the site serves, with no JavaScript
  executed, and carries all 25 listings per page as numbers. The rendered
  cards became the fallback, and the two were verified to agree on all 22
  shared columns across all 25 rows of a real capture.
- **`page_flow.py`** — one classification of what a page IS (content, empty,
  past the end, served-but-unpainted, blocked) and one policy table
  (`STATE_POLICY`) shared by every engine, so three copies of the same
  if-chain cannot drift.
- **`proxy_pool.py`, `env_config.py`, `fingerprint_client.py`,
  `diff_runs.py`** — proxy pools with rotation and credential masking, `.env`
  loading with documented precedence, the Fingerprint API client, and a
  run-to-run diff keyed on the listing id.
- **Run metadata sidecar** (`<out>.meta.json`): status, stop reason, WHICH
  pages failed by number, the site's own `total_results`, and whether
  pagination was addressable.
- **`--concurrency N`**, where each worker owns its browser and its own proxy
  exit, dispatch stops at the end of the listing, and unattempted pages are
  reported rather than counted as failed.
- **A 327-check offline suite** and `.github/ci_checks.py`, invoked from both
  CI and the suite, plus a daily 3-page canary.
- `page` and `position` columns, with the pair asserted unique across a
  multi-page run.

### Fixed

- **Pagination never worked.** The scraper constructed `?page=N`, which
  Flippa's own JavaScript deletes (`t.page && delete t.page`); the correct
  parameter is `?page[number]=N`. Every multi-page run before this returned
  exactly 25 rows — one page — and exited 0. Pagination is now both corrected
  and VERIFIED at runtime: page 2 must carry listings page 1 did not, or the
  run reports `partial` instead of a complete-looking result.
- **Negative net profit parsed as null.** Flippa writes a loss as
  `-USD $315 p/mo`, and the currency was stripped with a `^`-anchored pattern,
  so the leading minus made the whole field fail. 2 of 25 rows on the
  2026-08-27 capture were affected.
- **Badges were read from card TEXT.** `sponsored`, `confidential` and a
  `status` matched against the word "Open" all fired on a seller's own summary
  containing those words. They are now read from the Angular `ng-if`
  attributes, which name the field they render.
- **`0.0` reported as a valuation multiple.** The site's JSON carries `0.0`
  where it shows no multiple at all; that is now `null`, on 12 of 75 rows in
  the 2026-09-19 run.
- **The Scraper API engine was reported as not working against this site.** It
  waited for a CSS class that only appears once the grid has PAINTED, and
  timed out on responses that already contained all 25 listings.
- **`asyncio.get_event_loop()` in the pyppeteer engine** — since Python 3.12
  there is no implicit loop in the main thread, so the engine died before its
  first fetch. Found by running it, not by reading it.
- **A challenge marker that matches every good page.** The inherited marker
  set contained `challenge-platform`, and Cloudflare's JS-detections tag
  (`/cdn-cgi/challenge-platform/scripts/jsd/main.js`) is on every page Flippa
  serves — it would have reported exit 3 on every successful run.
- **Credentials in exception text.** The legacy captcha endpoint and the
  Fingerprint API both take the key as a query parameter, and `requests` puts
  the full URL into every error it raises. Both paths now redact before
  raising — globally, not on the first occurrence — and the redaction covers
  every URL scheme, `socks5://` included.
- **`--fp-tags` defaulted to a three-tag list**, which the Fingerprint API
  rejects with HTTP 400. It is now one OS-family tag.
- **A copied `.env.example` read as configured.** Any value still carrying
  `{braces}` is now treated as unset, and an empty value is unset without a
  warning about nothing.
- **A remote browser's password printed in a traceback.** Measured live on
  2026-09-19 against a Scraping Browser endpoint that answered 401: Playwright
  put the full `ws://user:pass@…` endpoint into the exception message and into
  a four-line call log beneath it — five occurrences of the password in one
  traceback, and the engine let it through untouched. All three engines now
  wrap the remote connect and redact any traceback before printing it, and the
  offline suite pins both.
- **A dead proxy reported as a slow site.** An exit whose password had been
  rotated answered `407 Proxy Authentication Required` in 0.2s to a plain
  request, while the same exit under Chromium produced only navigation
  timeouts — three 60s attempts per page, with the proxy never mentioned in
  the log. Every engine now sends one small request through the exit before
  launching a browser: a rejected or unusable exit ends the run in under a
  second with exit 2 and a message naming the proxy, a slow one only warns,
  because the target may be what is slow.
- **A bought captcha token thrown away.** `--solve-captcha always` injected the
  token and then reloaded the page, which discards it: a form reads its token
  at submit time, not from a cookie. Measured on `/signup`, which carries a
  real Turnstile. A page that was NOT blocked is no longer reloaded, so the
  token stays where it was written — and, since nothing here submits a form,
  the default `when-blocked` still refuses to buy one at all.

### Verified against the live APIs (2026-09-19)

- Captcha solving: a real Cloudflare Turnstile on `/signup`, detected from the
  static markup with its live sitekey and solved through
  `TurnstileTaskProxyless` in about 5 seconds. Twice. No form was submitted.
- The Scraper API: two billable tasks at $0.0005 each, 50 listings, every
  column matching the browser engines' except `price_source`.
- Proxies: a 2-page run through `eu.proxy.2captcha.com:2334`, 50 listings,
  credentials never in argv.
- The canary, dispatched by hand on 2026-09-21: 75 listings across 3 pages
  from a bare GitHub runner — a datacentre address with no proxy and no key —
  and every threshold in its sanity check met. The runner-IP caveat in the
  workflow's own comment stands; it simply did not bite here.
- The Fingerprint API answered `403` for the key used here — a separate
  subscription — so that path remains unverified rather than assumed.
- The Scraping Browser API, over a CDP URL copied from the Browser API
  dashboard: 75 listings across 3 pages, `Captcha.setAutoSolve` enabled on
  connect, `--concurrency` refused with the profile-lock reason, and data
  identical to the local-browser run bar three rows' `position`. An endpoint
  assembled BY HAND from the documented URL shape answers `401 deny_no_user`
  — the URL is copied, not built, and that 401 said nothing about the
  account.

### Removed

- The removed local-solver flag and the hardcoded `127.0.0.1` endpoint behind
  it. That endpoint was a placeholder for a product that does not exist under
  that name, so the flag could not work for anyone who set it — and a flag
  that cannot succeed is worse than a missing feature, because it reads as an
  option. The real "the browser solves it for you" path is
  `Captcha.setAutoSolve` over the Scraping Browser API. The offline suite
  asserts the flag stays gone.
- The JSON-LD parse path. A flippa.com search page carries two `ld+json`
  blocks, a `WebPage` and an `FAQPage`, and neither contains a listing — the
  code was dead and looked load-bearing.
