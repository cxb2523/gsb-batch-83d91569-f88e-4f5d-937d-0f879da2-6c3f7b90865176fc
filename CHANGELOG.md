# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/) as
closely as a CLI toolkit can. **A patch release means "fixes", not "no flag
moved"** — a default that changes behaviour can ship in a patch, and when one
does it leads the release notes rather than being discovered from a bill.

## [Unreleased]

> **Behaviour changes.** (1) A run through a proxy now makes one pre-check
> request before starting a browser. A proxy that answers **HTTP 407** or
> **402** ends the run with **exit 5** and
> `<out>.latest_attempt.meta.json` (`status: failed`, `stop_reason:
> proxy_auth_failed` / `proxy_balance_exhausted`) instead of timing out on
> every retry. (2) Through a local proxy, images, video/audio and fonts are
> **no longer downloaded**; `--load-media` (or `WELLFOUND_LOAD_MEDIA=1`)
> restores them. Runs without a proxy or over `--cdp-endpoint` are unchanged.
> (3) A run through a local proxy now **stops at 10 MB of proxy traffic** by
> default (`--proxy-budget-mb`, `0` = no cap): it keeps its rows and exits
> **6** (**5** with none) with `stop_reason: proxy_budget_exceeded`, and it
> always writes `<out>.latest_attempt.meta.json`.

### Added

- `proxy_meter.py`: per-run proxy traffic meter and budget, in all three
  engines, only through a local proxy. Playwright sums `request.sizes()`;
  pyppeteer and Selenium count CDP `Network.loadingFinished.encodedDataLength`
  plus each request's own size. Over budget, Playwright aborts new requests
  in a route and pyppeteer/Selenium block every URL over CDP, and the run
  stops before its next navigation; Playwright's `--concurrency` workers
  share one meter and all stop. New sidecar fields `proxy_bytes`,
  `proxy_budget_bytes`, `proxy_budget_exceeded`; a closing log line
  `Proxy traffic: X.X MB of Y MB budget`. `--proxy-budget-mb` and
  `WELLFOUND_PROXY_BUDGET_MB` (commented out in `.env.example`).
- CI only: each canary run passes `--proxy-budget-mb 10`, writes its proxy
  traffic to the step summary, and fails with
  `::error::stopped: proxy budget 10 MB exceeded` when the cap was hit
  (`.github/proxy_traffic.py`).
- Offline checks: the meter against known CDP and Playwright sizes, an HTTP
  client through a byte-counting stub proxy, the sidecars and exit codes
  over budget, every engine driven past the budget (Playwright also with
  `--concurrency 2`), the canary steps and their summary script. An opt-in
  real-browser check (`PROXY_METER_BROWSER=1`) compares each driver's count
  with a stub proxy's.

- `proxy_check.py`: the proxy pre-check (one CONNECT plus `HEAD /robots.txt`
  on the target host, no third-party service) and media blocking for all
  three engines. The 407 message names `WELLFOUND_PROXY` and says the
  gateway refused the credential (or the traffic balance is exhausted); a
  402 says the proxy traffic/balance is exhausted. Neither prints the
  credential. A proxy that does not answer keeps the existing retry
  behaviour.
- `--load-media` on all three engines, and `WELLFOUND_LOAD_MEDIA` (commented
  out) in `.env.example`.
- Offline checks: a stub proxy that answers 407/402/200 or nothing, each
  engine driven to exit 5 without a browser on a 407, the attempt sidecar,
  the Playwright route handler, the pyppeteer Fetch patterns, the Selenium
  blocked-URL list, and when each engine installs blocking.

### Changed

- `pyproject.toml` lists `proxy_check` (missing since it was added) and
  `proxy_meter` among the installed modules.
- An explicit numeric flag value of `0` is no longer overridden by the
  environment (`--proxy-budget-mb 0` wins over `WELLFOUND_PROXY_BUDGET_MB`).
- CI only: the whole canary, free and paid jobs alike, now runs weekly (Mondays 05:40 UTC) and on a manual dispatch; the daily schedule is removed.

### Fixed

- The pyppeteer and Selenium proxy meter counts only `http://` / `https://` requests and responses that came over the network. Chrome's own loads (the `chrome://` new-tab page, `data:`, `blob:`), cache hits (`requestServedFromCache`, `fromDiskCache`, `fromPrefetchCache`, `fromServiceWorker`) and Chrome's error page count nothing. A sibling repo's Selenium run had counted about 2.8 MB of new-tab scripts while its proxy carried about 6 KB. The pyppeteer block sent once the budget is spent now reaches the page's own event loop even when the budget runs out on another thread.

## [0.2.1] — 2026-10-16

> **Behaviour change.** `--allow-empty` now writes an empty file only for a
> genuine empty result, and its sidecar says `status: empty` (was
> `failed`). A blocked or failed run with `--allow-empty` no longer
> replaces an earlier output with an empty file. It keeps its exit code
> (3 or 5) and leaves that output and its sidecar untouched.

### Fixed

- **`--allow-empty` could destroy the output it exists to protect.** With
  the flag, a blocked run or a run that never obtained its content wrote
  an empty JSON and CSV over the previous good result, plus a sidecar
  saying `failed`. A genuinely empty, complete run was labelled `failed`
  too, so `diff_runs.py` refused it. Now:
  - A finished run whose answer was nothing writes `[]`, a header-only
    CSV and a sidecar with `status: empty` and its `stop_reason`. It
    exits 4.
  - Blocked (3), never obtained or parser failure (5) and partial (6) keep
    their exit codes. No empty row file is written for them, and an
    earlier output at the same `--out` is kept byte for byte, sidecar
    included.
  - When nothing earlier exists, a blocked or failed `--allow-empty` run
    writes only a sidecar, with `status: blocked` or `failed`.
  - `diff_runs.py` compares an `empty` run like a complete one.

## [0.2.0] — 2026-10-15

> **Behaviour changes:**
> - **CSV cells that start with `=`, `+`, `-`, `@`, TAB, CR or LF now get a
>   leading apostrophe** so a spreadsheet reads them as text. Only text
>   cells, only in the CSV; numbers and the JSON output are unchanged, and
>   the sidecar records how many cells were escaped as `csv_cells_escaped`.
> - **Counting flags reject values that skipped or crashed a run** with exit
>   2 naming the flag: `--pages` and `--concurrency` below 1,
>   `--proxy-block-retries` below 0 (a negative value fetched nothing at
>   all), `--delay` and `--retry-delay` below 0 (a negative delay crashed in
>   `time.sleep`). In `scraper_api_client.py`, `--timeout` below 1 and
>   `--retries`/`--retry-delay` below 0.
> - **A 404 now exits 4 in the Playwright and pyppeteer engines and in the
>   Scraper API client**, as the 0.1.2 notes already said it did: the HTTP
>   status now reaches the page classifier. Before, a removed job was
>   waited on, re-fetched and reported as content not obtained (exit 5).
>   Selenium exposes no HTTP status and still decides by the page body.
> - **`.env.example` ships `WELLFOUND_URL` commented out**, and an
>   environment URL no longer collides with `--role`/`--location`/`--remote`
>   or an explicit `--mode job`/`--mode jobs`: only a `--url` typed on the
>   command line does.

### Fixed

- **Selenium and pyppeteer crashed when a page was refused and no proxy was
  configured** — the normal outcome from a datacentre address. The block
  retry touched `pool.current` with no pool and raised `AttributeError`;
  pyppeteer also did so on a plain load timeout. Both now re-fetch through
  the same path, as the Playwright engine does, and rotate only when a pool
  of more than one exit exists.
- **Selenium and pyppeteer misread every `--mode job` page.** They
  classified it as a listing, found no listing payload and reported a parse
  error: zero rows, exit 5. Every classify call now passes the mode.
- **The canary skipped green for as long as it existed.** Without the
  `WELLFOUND_PROXY` secret it now fails with an error naming the secret,
  and a second job runs from the bare runner and requires the datacentre
  refusal to be recognised as one (exit 3), not misread or crashed. The
  exit-5 explanation in the canary named an old meaning.
- **The credential scan skipped everything when the clone lived under a
  directory named `build`, `venv`, `.venv` and similar**, because the
  exclusions were tested on the absolute path. They are now tested on the
  path inside the repository, and a scan that reads 0 files fails.
- **`.gitignore`** now covers `--dump-html` page files whatever the base
  name (`snap.json.page2`), a `live/` directory and root-level `.html`
  dumps.
- **Comments and help text** no longer describe other sites' pages, a
  `challenge` state this repo does not have, or a `--mode profile` it never
  had, and no longer cite private working notes.

### Tests

- The offline suite now loads each engine with its driver library stubbed
  and drives the real page loop, so the no-proxy block, the timeout, `--mode
  job` and the 404 status are checked in every venv, not only where the
  engine is installed. New checks also cover the environment URL with the
  role flags, the counting-flag bounds, CSV formula escaping, the scan's
  path handling and private citations in tracked files.

## [0.1.2] — 2026-10-13

> **Behaviour change:** `--retries 0` is now a usage error (exit 2) instead
> of silently running no navigation at all. It counts ATTEMPTS per page
> load, and zero never entered the loop — nothing was fetched, and the
> engine then judged `about:blank`. A script passing `0` used to get exit 4
> ("no jobs") for a site it had never asked.

From a third-party audit dated 2026-10-13. Four findings were real; the
audit's headline live result was an artefact of its own command, and that
artefact is fixed too, because it is what made the misreading possible.

### Fixed

- **A run that fetched nothing reported "0 jobs".** State `unknown` or
  `parse_error` left the page outcome marked ok, so the run reported
  `completed` with zero rows and exited **4** — an ETL trusting the exit
  code would conclude the catalogue had emptied. They now exit **5**.
  `empty` still exits 4 (the site served a listing and it matched nothing),
  and so does `not_found` (a 404 is the site answering definitively that the
  address holds nothing). `page_flow.STATE_POLICY` carries `obtained` per
  state and `stop_reason_for()` replaces a triage the three engines were
  deriving in seven places between them.
- **`--retries 0` ran no navigation.** See the blockquote. Measured on the
  audited commit: `--retries 0` gave 39 bytes and exit 4; the same command
  with `--retries 1` gave the site's real refusal — 11,922 bytes, `blocked`,
  exit 3 — and with a residential exit, 115 rows over three pages, exit 0.
- **`--category` did nothing in the Scraper API adapter.** It assigned
  `row.category` to a dataclass with no such field, so `asdict()` never saw
  it. It is a run label and goes to the sidecar; the adapter writes one now.
- **The same adapter returned exit 4 for a served page that parsed to
  nothing**, which is this repo's bug rather than an empty catalogue.
- **Output writes were not atomic.** `open(path, "w")` truncates before a
  byte is written, so an interrupted run left a shorter file where a
  complete one was — worst for `<out>.meta.json`, the file a consumer
  branches on. Writes go to a temp file in the same directory, fsync, then
  `os.replace`, preserving an existing file's mode and otherwise using the
  process umask (never a flat 0644, and never the 0600 a naive port leaves).
- **Donor residue in the Scraper API adapter**: its description and `--mode`
  help described a `profile` mode that does not exist in this repo.

### Changed

- **The `robots.txt` claim now says what is guaranteed.** "Reads only routes
  `robots.txt` allows" read as a mechanism this code does not have. Every
  route the parser accepts is allowed and every disallowed route has no
  mode — now checked by the offline suite against the published file. It is
  deliberately not a runtime gate: a preflight fetch is itself 403 from a
  datacentre address, so it would fail closed where the scraper already
  fails, or fail open.
- Python **3.13** is in the CI matrix; the badge claimed 3.9–3.13 while CI
  tested 3.9 and 3.12.


### Fixed
- **The Scraper API engine failed on every `--wait-text` / `--wait-element` /
  `--wait-state` call, and was billed for it.** It sent `waitFor` as a
  JSON-encoded string; measured 2026-09-23 the live API answers that with
  HTTP 422 "params.waitFor must be an object" and still charges $0.0005,
  while the same request with an object is answered 200. It is now sent as
  an object. **And the target site's status was never seen:** the client
  read the response's `status`, which is the API's own verdict string
  ("success"), instead of `http_code`, the target's HTTP status — so a
  target 403/503 reached the page classifier as "success". It now reads
  `http_code` (falling back to `status` only if that is an int). A
  regression check drives the real `fetch_html` with `requests.post`
  stubbed.
- The bug-report and site-changed issue templates were Etsy's, copied from
  the repo this one was bootstrapped from: they told a reporter about
  DataDome, `t=bv`, Etsy's shop ratings and storefront redirects, and gave an
  etsy.com URL as the example. Rewritten for Wellfound from this README (the
  datacentre 403, the gated `/company/` route, the Apollo cache / JSON-LD
  split, `page_echo_mismatch`).
- Both issue templates and `playwright_scraper.py --dump-html --help`
  pointed at a `TROUBLESHOOTING.md` this repo has never had. They now point
  at the README sections that exist.
- `captcha_solver.py`'s docstring referred to a "No DataDome solver"
  section that is not in the file. The dangling line is gone.

- `SECURITY.md` said this project has no releases or version tags; it has
  both. "Supported versions" now names the latest release and `main`.

## [0.1.1] — 2026-09-17

An audit against this family's own checklist, section by section, executing
each claim rather than re-reading it. Three defects, all found by running a
path that had never been run, and none of them visible to the 356 green
offline checks v0.1.0 shipped with.

> **Correction to v0.1.0's documentation.** v0.1.0 described the captcha
> path as wired in and bounded, and did not say what buying a solve
> actually achieves here. Measured now: on this site, from a datacenter
> address, a paid Turnstile token is **refused** — the challenge is
> captured and solved correctly and Cloudflare does not accept it. If you
> read v0.1.0's README and bought solving to get past the block, that is
> not what will get you in; a residential exit is, and it costs less. The
> table under "About the captcha, precisely" now carries the numbers,
> including the control that makes them mean something: the block does
> not expire on its own — 0 of 8 reloads in the same session cleared it.

### Fixed

- **`SOLVES_PER_PAGE` was not enforced, and it is a money limit.** Every
  engine calls `handle_captcha_if_present` twice per attempt — once before
  the page is classified, once after — and only the second was counted.
  Measured from a datacenter address, where a real Cloudflare challenge
  renders on every fetch: **one page bought three Turnstile solves**. Both
  call sites now go through `_solve_budget()`, and the same run buys one.
- **A dead proxy was reported as a plain "gave up loading".** The reason was
  computed and logged on rotation with a pool, then dropped without one —
  the single-`--proxy` case, which is the common one. All three engines now
  name it, and pyppeteer gained the `exit_failed` binding its twins already
  had so the three are structurally identical.
- **Two inherited claims that were false about this site.**
  `scraper_api_client.py` printed a sibling repo's measurement as this
  repo's; replaced with what was measured here — the Scraper API's own exits
  get upstream 403 and 11,825 bytes, while the same task through a Scraping
  Browser session returns 200, 610,897 bytes and 37 job rows.
  `captcha_solver.py`'s docstring described another site's PerimeterX
  defence and called itself load-bearing here; rewritten, with the sibling
  figures kept and labelled as such.
- **The README said `angel.co`'s old routes no longer exist.** Measured,
  `angel.co/role/r/software-engineer` returns the same page as the
  wellfound.com URL. The host is still refused — one job must not appear
  under two spellings — but the stated reason is now the true one.

### Added

- Regression checks for both fixes, each controlled in both directions:
  planting the fault makes them fail with the expected message, reverting
  makes them green. 373 checks total.
- `years_experience_max` documented as almost always null — 1 of 1,216 rows
  pooled across every live run.

### Verified, by running it

The fingerprint path applies its user agent, locale (`en-US`, not
`en-{country}`) and timezone to the real browser; a failing API call does not
leak the key; credentials never reach the browser's argv (`--proxy-server`
carries host and port only); the engine flag set covers all 28 of the
family's contract flags with none missing; `pip check` passes in each
engine's own venv; the Scraping Browser path serves this site; `--dump-html`
writes on success; exit 3 and exit 4 are distinct; no column is null on every
row of every run; and all three engines return 52 identical rows after the
edits.

## [0.1.0] — 2026-09-17

First release. Everything below was measured on 2026-09-17 unless a different
date is given.

### Added

- **Three modes.** `--mode role` reads a `/role/{r}`, `/role/r/{r}` or
  `/role/l/{r}/{loc}` landing page and paginates; `--mode jobs` reads the
  `/jobs` discovery feed; `--mode job` reads one `/jobs/{id}-{slug}` page.
  `--role`, `--location` and `--remote` build a landing URL so a run needs no
  hand-assembled address.
- **Four fetchers.** `playwright_scraper.py` (primary, with `--concurrency`),
  `selenium_scraper.py`, `puppeteer_scraper.py`, and `scraper_api_client.py`
  for the 2Captcha Scraper API. All three browser engines were run live
  against the same listing and returned **byte-identical rows** — the same 52
  skus, the same 38 columns, the same `position` on every row, and identical
  sidecars.
- **38-column `JobPosting` row**, carrying the family prefix (`source`,
  `scraped_at`, `url`, `sku`, `title`) unchanged, plus the company's size,
  badges and tagline, the salary AND equity ranges, the remote configuration
  and the full job description.
- **Compensation parsing** for the nine shapes measured across 312 non-null
  values, including `₹30L – ₹80L` (the Indian lakh, 1e5 — not 30 to 80),
  `0.5% – 1.0%` with no salary at all, and `No equity` as a statement rather
  than a missing value.
- **`data_source` provenance column** (`apollo` / `jsonld`), because a
  landing page and a job page publish through different mechanisms and
  neither is a subset of the other. `diff_runs.py` reports a difference that
  comes with a source difference as `source_changed`.
- **355 offline checks**, with fixtures cut from real captures and verified
  to parse identically to their untrimmed originals.

### Notes on the site, which decide how this repo is built

- **Gating is per ROUTE.** From a residential US exit, three requests each:
  `/`, `/jobs`, every `/role/…` shape and `/jobs/{id}-{slug}` answered 200
  every time; `/company/{slug}` answered 403 every time, to plain HTTP and to
  a real Chromium on that same exit. There is no `--mode company`, because
  there is nothing this repo can honestly offer for it.
- **A datacenter address gets nothing.** Every route was refused from a
  Hetzner VPS, `robots.txt` included, to plain HTTP and to headless and
  headful Chromium alike (0 of 1 each). A residential exit is not optional.
- **The obvious challenge marker is inverted on this site.**
  `challenges.cloudflare.com` appears once on every page Wellfound SERVES —
  the site loads Cloudflare Turnstile as part of its own application, with
  its sitekey in its own page config — and zero times on either refusal.
  `cf-turnstile` appears nowhere at all. This repo uses `_cf_chl_opt` and
  its siblings instead, and the offline suite fails the build if the
  inverted marker is reintroduced.
- **Walking past the last page does not fail — it repeats.** `?page=48` of a
  47-page listing answers HTTP 200 carrying page 1's rows again. Runs plan
  against the `pageCount` the site states, and the response's own echoed page
  number stops a run that gets past that.
- **A "page" is twenty COMPANIES, not twenty jobs.**
  `/role/r/software-engineer` reported `perPage: 20`, `pageCount: 47`,
  `totalStartupCount: 923` and `totalJobCount: 1881`, and its pages carried
  between 32 and 45 job rows each.
- **`/jobs` has no addressable pages.** `?page=2` returns the identical 46
  job ids as page 1, so that mode reports `single_page_listing` rather than a
  complete multi-page run holding one page several times.
- **The two structured sources agree about pay.** Job 4697947 is
  `$100k – $180k` on the listing and 100000–180000 USD in the detail page's
  `baseSalary`.

[Unreleased]: https://github.com/2scraper/wellfound-scraper/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/2scraper/wellfound-scraper/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/2scraper/wellfound-scraper/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/2scraper/wellfound-scraper/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/2scraper/wellfound-scraper/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/2scraper/wellfound-scraper/releases/tag/v0.1.0
