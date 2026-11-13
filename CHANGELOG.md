# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/) as closely
as a CLI toolkit can. A **patch** release means fixes; it does not promise
that every flag and default is frozen. Where a patch changes behaviour an
existing user would notice, the release notes lead with it.

## [Unreleased]

### Changed

- CI only: the scheduled canary now starts at 03:47 UTC (Mondays) instead of 05:40, so canaries that share one Scraping Browser profile no longer start at the same time and lock each other out.
- CI only: the whole canary, free and paid jobs alike, now runs weekly (Mondays 05:40 UTC) and on a manual dispatch; the daily schedule is removed.

## [0.3.0] — 2026-10-15

> **Newly refused flag values.** `--pages 0`, `--concurrency 0` and any
> negative `--pages`, `--concurrency`, `--delay`, `--retry-delay` or
> `--proxy-block-retries` are now usage errors (exit 2) naming the flag, in
> every engine and in `scraper_api_client.py`. They used to be accepted: a
> zero page count fetched nothing and reported an empty catalogue, and a
> negative pause crashed the run after page 1.
>
> **pyppeteer, a page that never loads, no `--proxy`:** the run now ends as a
> load failure (exit 5, or 6 with rows) instead of a traceback and exit 1.
> With a pool, a repeated timeout no longer rotates the exit; only an
> unusable exit does, as in the other engines.

### Fixed

- **pyppeteer crashed with `AttributeError` when a page failed to load and
  no proxy was configured.** The load-failure branch called
  `pool.advance(...)` on a `None` pool. It now rotates only for an unusable
  exit, and only when the pool has another exit to rotate to.
- **The per-page solve allowance was spent by a detection that bought
  nothing.** The pre-classification captcha check used up the page's one
  solve even when it found no challenge, so a challenge first seen after
  classification was never offered to the solver and the page was reported
  as blocked. The allowance is now claimed immediately before the paid
  request, in all three browser engines. A purchase that fails still counts,
  so the cap still holds at one per page across retries and rotations.
- **The credential scan read nothing from a clone under a directory named
  `build` or `dist`.** The skip list was tested against the absolute path. It
  now tests the path relative to the repository, a scan that reads zero
  files fails, and `.env*` backups, `.json` and `.csv` files are read too.
- `.gitignore` now covers every `--dump-html NAME --pages N` output
  (`NAME.pageN`), a root-level `*.html` dump and the usual working
  directories (`live/`, `out/`, `tmp/`, ...).
- `.env.example` ships `KOSE_URL` commented out, so a copied `.env` does not
  decide what a run fetches.
- The canary's Scraping Browser job no longer passes by skipping: with no
  `KOSE_CDP_ENDPOINT` secret it fails with an error naming the secret, and an
  exit 5 over CDP is a failure rather than a warning.
- Comments that named columns this schema does not have, stated a category
  total as current, carried another vendor's wording or gave the wrong exit
  code for `parser_found_nothing` (it is 5) were corrected; the CI sample
  summary counts priced rows instead of a column that does not exist.
- Shipped files, including the README, `--help` output and the 0.1.1 notes
  below, no longer cite private notes by name or section number; a suite
  check keeps it that way.
- `smoke_test.py -v` no longer crashes on a check whose detail is not a
  string.

## [0.2.0] — 2026-10-13

Worked through a third-party audit. Its headline conclusion was wrong and
three of its recommendations were right; the pass that followed found four
more defects it had not reached, two of which were in this repo's own
guards.

> **`--retries 0` is a usage error now.** It used to attempt no request at
> all and then judge the blank page — a script passing it received exit 4
> and no data, and will now receive exit 2 with the reason. If you have one,
> it has been getting nothing.

### Added

- **`http_scraper.py` — a fourth engine, over `requests`, and the
  recommended path on this site.** Same parser, same rows, same sidecar,
  same exit codes. Measured 2026-10-13 on the same three pages: **4.8–6.0 s
  against Playwright's 9.2–10.6 s**, identical rows, and the whole install
  is `pip install -r requirements.txt`.

  This was the audit's main recommendation and it is right for the reason it
  gave: the site server-renders its grid and gates nothing — a project UA, a
  `requests` UA, a Chrome UA and **no User-Agent header at all** are served
  byte-identical pages. The flags it cannot honour (`--cdp-endpoint`,
  `--solve-captcha`, `--fingerprint`) are refused as usage errors rather
  than accepted and ignored.

- **`<out>.last_attempt.json`** — a machine-readable record of the most
  recent attempt, successful or not, under its own name so it can sit beside
  a sidecar that still describes good data. The audit was right that a
  failed run left a caller nothing but an exit code.

- **`[project.scripts]`** — `kose-scrape`, `kose-scrape-browser` and
  `kose-diff`, so `pip install .` gives commands rather than paths. The
  default command is the browserless one.

- **The sidecar records which engine ran**, its driver version and the
  run's duration.

- **A canary job that runs the HTTP and browser engines over the same three
  pages and fails if any field differs.** That check is what found the
  truncation bug below, so it earns its place rather than decorating one.

### Fixed

- **An HTTP 404 the engines could not see, and `--retries 0` judging a page
  it never fetched.** The load loop is `range(1, retries + 1)`; zero ran it
  never, so `goto` was not called and the engine classified `about:blank` —
  39 bytes — as the site's answer. The audit ran exactly that, got exit 4,
  and concluded the browser path was broken and should be replaced. The same
  command with `--retries 1`, same address and same minute, returned 199,558
  bytes and 24 products.

- **Selenium and pyppeteer CRASHED on a blocked page with no `--proxy`.**
  `mask(pool.current)` on a `None` pool: `AttributeError`, exit 1, for a
  page that was merely blocked — which destroys the blocked/empty/partial
  distinction the whole exit-code contract rests on. Playwright had the
  guard all along, so this was "all three engines must agree" broken in the
  two quiet ones. Reproduced by forcing the state; exit 3 after.

- **The browser engines returned TRUNCATED product titles.** The site
  carries `data-module="TruncateText" data-options='{"length": 36}'` on each
  tile and its own JavaScript rewrites the name after load. A plain HTTP
  fetch sees the full name; a browser sees 36 characters and an ellipsis. On
  one live 3-page run the two engines differed on **10 of 72 rows**, every
  one a title — and nothing could see it until a browserless engine existed
  to disagree. The full name is recovered from the thumbnail's `alt`, which
  the rewrite does not touch.

- **A bare `recaptcha` marker fired on a good page fetched over
  `--cdp-endpoint`.** 2Captcha's auto-solve extension injects sixteen hunter
  scripts into every page it loads, two of them containing that substring. A
  listing with no tiles — an exhausted tag facet — would have been reported
  as a challenge: exit 3 for a correct answer. Narrowed to the loader paths
  the extension injects nothing matching, and a CDP-fetched page is now one
  of the suite's fixtures. The README's "zero captcha markers" claim was
  true of every capture this repo had and every one of them was fetched
  locally; it now says so.

- **Every paid solve goes through one budget.** `handle_captcha_if_present`
  runs twice per attempt and only the second call was counted, so the
  uncounted one repeated on every block-retry. Measured with the solver
  stubbed: **3 invocations against a limit of 1**, now 1. It has never cost
  anything here — no challenge has ever been observed on this site — which
  is exactly why it would have gone unnoticed.

- **Output is written atomically**, to a temporary file beside the target
  and then renamed, with the umask honoured and an existing file's mode
  kept. `open(path, "w")` truncates before a byte is written, so a crash
  halfway through left a shorter file where a complete one was — breaking
  the same promise `save()` keeps by refusing to overwrite good output with
  an empty result. The sidecar is the one that matters most.

- **CSV cells beginning `=`, `+`, `-`, `@` or whitespace are neutralised**,
  with the count in the sidecar. It does not fire on this site — 0 of 2,662
  measured string cells — and is worth shipping anyway.

- **`diff_runs.py` had never been in the list CI runs `--help` on.** Found
  by a check written for the new engine, which is the usual way a
  hand-written list turns out to be short.

### Not changed, and why

Two of the audit's recommendations were declined on the merits, and the
reasons are here so the next reader does not have to re-derive them:

- **"Drop pyppeteer and/or Selenium."** The three browser engines are this
  project family's contract: they exist so that a defect in one is visible
  as a disagreement rather than as a silent difference, and that is not
  theoretical — the browser/HTTP disagreement above is exactly what caught
  the truncation bug, and this release fixes a crash that lived in the two
  quiet engines precisely because nobody ran them. The maintenance cost the
  audit names is real; the answer to it is one shared fetch loop, not fewer
  engines, and that refactor is a decision for the family rather than for
  this repo alone.

- **"Make the HTTP loader the default path of the existing CLI."** It is a
  separate CLI instead. `playwright_scraper.py` quietly not using Playwright
  would be a worse lie than the one the audit was objecting to, and the two
  engines have genuinely different capabilities — only one can take
  `--cdp-endpoint` or solve a challenge. The README recommends the HTTP one
  and the canary runs both.

### Also in this release — work that had been unreleased

Family-wide fixes and a donor-leftovers pass that landed after
v0.1.1 and had not been tagged.

- **Scraper API: `waitFor` is now sent as a JSON object.** Measured
  2026-09-23 against `scraper.2captcha.com/tasks/sync`: the JSON-encoded
  string this client sent (the form older docs described) is refused with
  HTTP 422 "params.waitFor must be an object" -- and the task is still
  billed ($0.0005) -- so every run with `--wait-text` or its sibling wait flags
  failed with exit 5. The object form answers HTTP 200.
- **Scraper API: the target page's status is read from `http_code`.** The
  response's `status` field is the API's own verdict string (`"success"`),
  not the target site's HTTP code, so a target 403/503 was never seen by
  this client. `http_code` (an int) is read now, with `status` kept as a
  fallback only when it is an int.

Leftovers from the sibling repos this one was bootstrapped from
(montblanc-scraper, bbb-scraper, etsy-scraper), which described those sites
as if they were this one.

- **User-visible strings.** `--pages` help named a `--mode category` and
  `--mode search` this repo does not have and said a category past its end is
  "a served, empty grid" (here it re-serves its last page). The Playwright
  blocked-page error said this site's edge "refuses `curl`, `python-requests`
  and friends outright", the opposite of what the README measured; it now
  matches the other two engines. The parse-failure error pointed at a JSON-LD
  `ItemList` a listing here does not carry; the image-coverage log line
  described that same `ItemList`; `--mode product` logs and `--help` spoke of
  variants and a `ProductGroup`; `--retries` help spoke of hub pages;
  `--dump-html` help pointed at a `TROUBLESHOOTING.md` that does not exist.
- **Engines agree on the refusal reason.** pyppeteer and Selenium recorded a
  refusal as `blocked_cloudflare (hard block)`, a vendor never observed here,
  while Playwright recorded `blocked_edge refusal`. All three now say
  `edge refusal`.
- **`diff_runs.py` tracked Montblanc's columns** (`collection`,
  `sub_collection`, `color`, `size`, `special_edition`, `base_sku`), none of
  which exist in this row model. It now tracks this site's own `tax_rate` and
  `subcategory`, and treats `subcategory` / `variant_of` as product-mode-only.
- **Issue templates** were Etsy's (DataDome, `shop_rating`, an etsy.com
  example URL). Rewritten from this repo's README.
- **Donor prose in core modules and comments:** the BBB Turnstile paragraphs
  in `captcha_solver.py`, Montblanc URLs and counts in the engines, BBB's
  `find_country` in two locale comments, and an unnamed tokopedia hub
  anecdote now credited to tokopedia-scraper.
- **Test data:** `smoke_test.py` built its sidecar fixtures from a
  montblanc.com run; they now use this site's measured `/c/c15/` run (13
  pages, 304 products, `mode="listing"`) and assert the sidecar fields this
  engine actually writes.
- **`.dockerignore`** listed `bbb_businesses.*`; it now lists this repo's
  `kose_products.*`. The Dockerfile example wrote to `writing-instruments`.

- `SECURITY.md` said this project has no releases or version tags; it has
  both. "Supported versions" now names the latest release and `main`.
- `captcha_solver.py`'s docstring pointed at a "No DataDome solver" section
  that does not exist in this repo (it came with the copied core). Removed.

## [0.1.1] — 2026-09-18

A pass back over the project's own rules before calling the repo finished. Everything here
was found by checking a claim rather than by reading the code.

### Fixed

- **An HTTP 404 was retried instead of being believed.** The engines
  discarded what `goto()` returned, so every page reached the classifier with
  `status=None` — and this site answers a missing path with a bare
  1,040-byte page carrying *no site chrome at all*, which without a status
  reads as "not recognisably this site" and RETRIES. Playwright and pyppeteer
  now thread the real status; Selenium cannot (WebDriver exposes none), so
  the parser reads the status the site states in its own `<title>404- …`,
  which is what makes all three engines agree rather than two of them being
  better informed than the third.

  A new terminal `not_found` state does not retry, does not count as blocked
  — exit 3 would send the reader after a proxy problem — and stops the run
  with its own `stop_reason`. Verified end to end: the bare tag-facet URL
  (`/site/itemtags/list.aspx` with no `tags=`) is an address this scraper
  ACCEPTS and really does answer 404, so the branch is reachable rather than
  decorative.

- **A run pointed at page 10 quietly returned page 1.** `_target_url`
  normalised a listing URL back to page 1, so `--url .../c15_p10/ --pages 2`
  fetched pages 1 and 2 and reported success. The start page is now honoured:
  that run reads 10 and 11.

- **The credential scan failed on a clean clone.** It skipped virtualenvs by
  DIRECTORY NAME, so following this repo's own README with the environment
  called anything but `.venv` walked into it and failed on the 32-hex string
  inside pip's vendored `packaging/_elffile.py`. A venv is now recognised by
  a `pyvenv.cfg` above the file or `site-packages` in its path. Measured
  across the family: 21 of 26 sibling repos still have the name-based
  version.

- **Two planning implementations became one.** `page_flow.pages_to_plan` now
  returns the absolute page numbers a run should fetch and is the only place
  that arithmetic lives; `plan_from_total` (a wrapper nothing called) and
  `product_parser.pages_to_fetch` (used only by its own test) are gone. Found
  by grepping every public name for a consumer outside its own module.

- **A fabricated fixture was replaced with a real capture.** `NOTFOUND_HTML`
  had been written by hand with a `404-` title on it, and was wrong about the
  one thing it existed to show: this site answers a bogus goods code with
  HTTP **200** and its full chrome. Every fixture in the suite is now cut
  from a real response.

### Verified

- `--concurrency 3` over five pages: 120 rows, 120 distinct skus, merged in
  PAGE order although the pages arrived 4-3-2-5, and `page`+`position` unique
  across the run. Refused over `--cdp-endpoint`, with the reason.
- The published repo description, topics, homepage and release notes carry
  none of the banned wording — the surfaces a file scan cannot see.
- 459 offline checks, and every new check was CONTROLLED: the fix reverted,
  the expected failures confirmed by name, the fix restored. One control
  caught a check of mine that was passing for the wrong reason.

## [0.1.0] — 2026-09-18

First release. Reads **Maison KOSÉ** (`maison.kose.co.jp`), Kosé's own online
store.

> **The domain in this repo's name does not resolve.** `kose.com` is
> registered (GoDaddy, 1998, paid to 2029) and delegated to two nameservers
> that answer REFUSED for the zone, so every resolver returns SERVFAIL and no
> client anywhere gets an address. It is a broken delegation, not a bot
> manager. Kosé's storefront is `maison.kose.co.jp`, which is where
> `www.kose.co.jp` sends a visitor with its own meta refresh, and that is
> what this scraper reads.

### Added

- Two modes over three routes: `--mode listing` reads a category
  (`/site/{brand}/c/cNN/`) or a tag facet
  (`/site/itemtags/list.aspx?tags=…`), and `--mode product` reads one product
  page out of its own JSON-LD.
- Four engines: Playwright (primary), Selenium, pyppeteer, and the 2Captcha
  Scraper API. All four were run live on 2026-09-18; the three browser
  engines returned **48 of 48 identical rows** on the same two pages.
- 23 columns, including four this site needs that the family schema did not
  have: `tax_rate` (Japan charges 8% and 10% and the prices are
  tax-inclusive), `price_is_store_price`, `badges`, and `variant_of`.
- A canary that runs a real 3-page scrape **daily from a bare GitHub runner
  with no secrets**, because the README's central claim is that none are
  needed. A second job reads a product page; a third exercises the Scraping
  Browser API and skips with a `::notice::` when no secret is set.

### Measured, on 2026-09-18 from a datacentre address

- **No gating of any kind.** `curl`, `python-requests` and a request with **no
  `User-Agent` header at all** each returned the same 90,310-byte listing;
  twelve pages back to back were twelve HTTP 200s.
- **No captcha.** Zero markers of reCAPTCHA, hCaptcha, Turnstile, DataDome,
  PerimeterX, Incapsula, Kasada or AWS WAF across 13 captures, and no
  `data-sitekey` anywhere. The solver is wired and has never had anything to
  do. Nothing here claims a captcha on this site could not be solved.
- **216 rows across four live runs**, with `title`, `url`, `sku`, `brand`,
  `price`, `currency`, `in_stock`, `image_url` and `tax_rate` populated on
  216 of 216. Prices ran ¥495 to ¥264,000.
- One category, `/c/c15/`, states 13 pages and holds 12 × 24 + 16 = **304
  products**.

### Site traps this release handles

- **The brand segment in every URL is decorative.** `/site/xyz/c/c15/`
  returns byte-identical bytes to `/site/cosmedecorte/c/c15/`. Only `cNN` and
  `gSKU` address anything, so `brand` is read per tile — a tag listing mixed
  **11 brands across 72 rows**.
- **A category listing walked past its end serves its last page AGAIN**,
  byte-identical and HTTP 200, rather than 404ing or emptying. Runs plan
  against the site's own `N／Mページ` counter and still stop on "no new sku".
  A tag listing ends with a genuinely empty page and publishes no counter.
- **`&pageno=` and `&page=` are silently ignored** on a tag listing and
  return page 1 with HTTP 200; only `?p=` paginates it.
- **5 of 20 product pages canonicalise to a DIFFERENT sku** — `/g/gJQBA/` is
  the 60 g cream and points at the 20 g `/g/gJQGA/`. A row's URL is built
  from the page's own sku; the canonical is kept as `variant_of`.
- **A product page reuses the listing's tile class** on `<div>`s for
  staff-review cards, 15 on one measured page. The tile selector is
  element-qualified and sees zero of them.

### Known limitations

- `--cdp-endpoint` (the Scraping Browser API) is **not live-verified in this
  repo**: the profile available when this was built had expired (`401
  deny_no_user`), and those credentials live about a day. The code path is
  the family's and is exercised by sibling repos.
- Selenium cannot use an authenticated remote CDP endpoint or an
  authenticated proxy; both limits are the driver's and are documented in the
  README rather than left to be discovered.
- The site's own `/site/goods/search.aspx?keyword=…` route returns a page
  with no tiles on it, so there is no keyword-search mode. The tag facets are
  the route that crosses brands.

[0.3.0]: https://github.com/2scraper/kose-scraper/releases/tag/v0.3.0
[0.2.0]: https://github.com/2scraper/kose-scraper/releases/tag/v0.2.0
[0.1.1]: https://github.com/2scraper/kose-scraper/releases/tag/v0.1.1
[0.1.0]: https://github.com/2scraper/kose-scraper/releases/tag/v0.1.0
