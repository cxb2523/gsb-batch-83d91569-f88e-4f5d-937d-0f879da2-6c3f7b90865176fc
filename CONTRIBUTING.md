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

This is the most useful issue you can open, and the template
(`site_changed.yml`) asks for the two things that make it actionable: the URL
and what the run printed.

**Include the exit code**, because it says which layer moved:

| Exit | What it means here |
|---|---|
| 4 | zero products — the page shape moved, or the category is genuinely empty |
| 3 | blocked — which on this site would be NEW; see below |
| 6 | partial — some pages came back and some did not |

**Exit 3 is the one worth reporting loudest.** Measured 2026-09-18, this
site served an ordinary datacentre address on every route with no key and no
proxy — including a request with **no `User-Agent` header at all**. If a
plain run starts coming back blocked, Kosé has started gating its catalogue
and the README's central claim needs re-measuring the same day.

Four things are most likely to break the parser, in the order they would
actually bite:

1. **`li.c-product__item`.** The tile, and the whole of the listing path —
   this site publishes NO JSON-LD on a listing, so there is no primary path
   to fall back from. If the element or the class changes, rows go to zero
   while `product_link_count` carries on reporting a healthy page, which is
   exactly the case `stop_reason: parser_found_nothing` exists to name.
   The `li.` is not decoration: a PRODUCT page reuses the same class on
   `<div>`s for staff-review cards, 15 on one measured page.
2. **`p.c-product__price` and its `（税込）` annotation.** The price and the
   tax rate come out of one node. A rename takes both, and the quiet half is
   the rate: a row with a price and no `tax_rate` cannot be converted back to
   a pre-tax figure.
3. **The `_pN` and `?p=N` conventions.** Verified against the site's own
   `rel=next` rather than guessed, and getting either wrong is SILENT —
   `&pageno=2` and `&page=2` on a tag listing both return page 1 with HTTP
   200. Watch the dedupe drop count: on this site a full page of duplicates
   means the run walked past the last page, which serves that page again.
4. **The `N／Mページ` counter.** What pages are planned from, and the
   separator is the FULLWIDTH solidus U+FF0F rather than an ASCII slash. If a
   report says `pages_available: null` on a CATEGORY run, check the character
   before anything else. On a TAG run null is correct — that route publishes
   no counter.

## Before this repository goes public

Read what the HISTORY exposes, not just the working tree — scan every blob
that ever existed (`git rev-list --objects --all`) for credentials, and
remember that a commit on top cannot reach what a published tag or a merged
PR's refs already hold. Decide before publishing; afterwards only a fresh
repository removes it.

Then the rest of the presentation, in the order that matters:

1. `python3 smoke_test.py` green, and the canary dispatched at least once.
   **Both of this repo's real canary jobs run with NO secrets** and are
   expected to be green — that is not a convenience, it is what keeps the
   README's central claim honest. Only the last job, which exercises the
   Scraping Browser path, needs a secret (`KOSE_CDP_ENDPOINT`); without it
   that job FAILS with an error naming the secret rather than passing on a
   skip, because a green check that tested nothing is indistinguishable
   from one that tested something.
   Note `workflow_dispatch` requires the workflow to exist on the DEFAULT
   branch — from a feature branch `gh workflow run` answers
   `HTTP 404: workflow canary.yml not found on the default branch`, which
   reads like a typo in the filename. Merge first, dispatch second.
2. The repo description, homepage and topics set. A banned-wording check
   covers the FILES in this repo; a GitHub description is not a file, and a
   phrase that check forbids has reached public repo descriptions in this
   family that way. Check the description, the topics and the release notes
   by hand.

   Note this bullet does not QUOTE the phrase, and the omission is
   deliberate: this file is scanned, so a note explaining the ban would
   itself fail the check. It has happened — a release note quoting the
   offending text failed the check the release was adding. Describe, do not
   quote. The check's own source is where the list lives.
3. Only then the row in the org profile README — and check every row on that
   page with an ANONYMOUS request rather than your own logged-in browser. You
   are a member of the org, so a logged-in view shows you the private repos
   too and the page looks whole to the one person who cannot see the problem.


## Pull requests

**Add a test for the behaviour you are changing.** `smoke_test.py` is a single
file of plain functions with inline HTML/JSON fixtures — no pytest, no
conftest, no fixtures directory. Copy the nearest existing check and edit it.

Six properties in this repo exist because they were once absent or were
measured against expectation, and cost real time. Tests pin all six, so a PR
that breaks one will fail rather than silently regress:

- **A product page is not a small listing, and the listing parser must
  return NOTHING on one.** A Kosé product page carries 15 `div.c-product__item`
  staff-review cards and an `awoo-product-list` recommendation block. A
  class-only tile selector would emit fifteen products per product page, each
  with a `/staff/` URL and no sku. The selector is element-qualified and the
  fixture carries a real staff card, so the check can actually fail — a
  fixture without one passes for the wrong reason.

- **`in_stock` is an ALLOWLIST over the site's own button text**, never
  `!= OutOfStock`. Measured over 171 tiles: four wordings mean available
  (種類を選ぶ, カートに入れる, 商品を購入する, 予約受付中) and two mean not
  (現在購入頂けません, 予約受付終了). A wording Kosé adds tomorrow must read as
  unknown rather than as a quiet "in stock". The column is verified in BOTH
  directions — 19 of 171 tiles were unavailable — which is otherwise
  not verified at all.

- **`tax_rate` is a column because Japan has two rates.** 10% standard, 8%
  reduced on ingestibles, and the site states only the reduced one
  explicitly. Two tiles in 171 carried it. A consumer computing a pre-tax
  price from the wrong rate is wrong by two percent in silence.

- **A row's URL is built from the page's own sku, never from its
  `rel=canonical`.** Measured over 20 product pages: **5 canonicalise to a
  DIFFERENT sku** — `/g/gJQBA/` is the 60 g cream and points at the 20 g
  `/g/gJQGA/`. A row built from the canonical would link to the wrong product
  while every other column described the right one. The canonical is kept as
  `variant_of`, which is the only thing on the site that groups two sizes of
  one product.

- **`brand` comes from the TILE, never from the URL.** The brand segment in
  every address is decorative: `/site/xyz/c/c15/` returns byte-identical
  bytes to `/site/cosmedecorte/c/c15/`. And a tag listing genuinely mixes
  brands — 11 across 72 rows on a live run — so there is no per-page brand to
  fall back on even if the URL were honest.

- **No marker may fire on a page the site serves.** There is no captcha on
  this site at all: zero markers of any vendor across 13 captures, so
  `BOT_CHALLENGE_MARKERS` is a TRIPWIRE rather than a description of anything
  observed. **`cf-turnstile` is deliberately absent** — it is the obvious
  marker for a Turnstile and is measured useless across this family, because
  2Captcha's own Scraping Browser auto-solve extension injects its hunters
  into every page it loads. `challenges.cloudflare.com` is carried instead.

  `smoke_test.py` pins it in both directions: no marker may fire on any
  known-good fixture, including one carrying that extension's own injection,
  and a real Turnstile must still be reported. **Before adding any marker,
  count it on a page you know is good.**

### If your change needs a live run

Most do not — the suite covers the parser, the writers, the page-state
classifier and the CLI contract against inline fixtures. If yours genuinely
needs maison.kose.co.jp, say in the PR what you ran, which mode and URL, from
which exit, and what you got — including the sidecar's `pages_available`,
`route` and `canonical_url`, and the coverage lines the run prints.

Three things about running this live that are specific to this site:

* **No route needs a special exit.** All three answered a plain datacentre
  address on 2026-09-18 — as did a request with no User-Agent header at all —
  so "it worked from my laptop" is reproducible here in a way it is not on
  some sibling repos. If yours did not, say which exit you used: that is a
  finding, and an important one.
* **Say which PAGE you started on.** A run pointed at `/c/c15_p10/` reads 10,
  11, 12 — the start page is honoured rather than normalised away. The `page`
  column is the run's own index, so the sidecar's `start_url` is what says
  where the run began.
* **Watch for a full page of duplicates.** That is what walking past the last
  page of a category looks like here: the site serves its LAST PAGE again,
  byte-identical and HTTP 200, rather than 404ing or emptying.

**Run more than the primary engine.** "Mirror them exactly" is a design rule,
not a verification: the first live run of the pyppeteer engine crashed on its
FIRST fetch on a signature mismatch that four separate offline checks and 400
green assertions had not caught. In this repo all three were run against the
same two pages on 2026-09-18 and returned 48 of 48 identical rows.

Do not add anything that submits a form or puts anything in a cart.
Maison KOSÉ's pages carry an add-to-cart flow, a wishlist and a personalisation
step; this project reads the catalogue and must never touch any of them.

## Scope

This repo scrapes **public pages** on maison.kose.co.jp: category listings,
tag facets and product pages, exactly as an anonymous visitor is served them.

Out of scope: anything behind a login (the site's accounts live on a separate
OIDC host, `member.kose.co.jp`, and this project never touches it), anything
that submits a form — the cart, the wishlist, the counselling flow — and
anything that defeats a protection rather than passing it the way an ordinary
browser does.

Also deliberately out of scope: the **staff opinion pieces** at `/staff/…`.
They are written by named Kosé employees, they appear on product pages, and
the parser is built to ignore them. There is no column for them, and adding
one would be republishing identifiable people's writing — a product decision
rather than a bug fix, and one this repo has decided against.

## Licence

MIT. By opening a pull request you agree your contribution ships under it.
