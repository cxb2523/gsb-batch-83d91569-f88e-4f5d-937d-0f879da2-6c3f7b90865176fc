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

It prints its own `passed / failed / skipped` counts, and lists both the
individual checks it had to skip and any group skipped because an engine
library is absent. A check whose input is missing must call `skip()`, never
`check(label, True)` — a skip asserted as a pass is indistinguishable in the
output from a check that actually ran, and it inflates the count the README
used to quote.

Some checks read `captures/`, which is not in the repository (it holds
multi-megabyte page dumps). Without it those checks report `SKIP`, which is
the honest result; record your own capture with
`--dump-html captures/live_search_page1_$(date +%F).html` if you are working
on the parser.

**The suite must pass with no engine installed at all.** CI installs only
`beautifulsoup4` and `requests`, so any import of `playwright_scraper`,
`puppeteer_scraper` or `selenium_scraper` in a test has to sit inside
`try/except ImportError` with the skip recorded. This is easy to get wrong
locally, where you almost certainly have an engine installed and an unguarded
import passes.

If the suite fails on a clean clone, that is itself the bug — say so.

## Dependencies: `.txt` is the spec, `.lock` is what gets installed

`requirements*.txt` hold the loose `>=` floors a person edits. Each has a
`.lock` beside it — exact versions and hashes, resolved for every Python from
3.9 up — and CI, the canary and the Docker image install only the locks, with
`--require-hashes`. `smoke_test.py` fails if a workflow installs anything
else, if a lock no longer satisfies its `.txt`, or if an action is referenced
by tag instead of by commit SHA.

After changing a `.txt`, or when `audit.yml` reports an advisory, regenerate
the locks with [uv](https://docs.astral.sh/uv/) — the exact command is also in
each lock's header:

```bash
uv pip compile --universal --python-version 3.9 --generate-hashes --annotation-style line \
    requirements.txt -o requirements.lock
uv pip compile --universal --python-version 3.9 --generate-hashes --annotation-style line \
    requirements.txt requirements-playwright.txt -o requirements-playwright.lock
uv pip compile --universal --python-version 3.9 --generate-hashes --annotation-style line \
    requirements.txt requirements-puppeteer.txt -o requirements-puppeteer.lock
uv pip compile --universal --python-version 3.9 --generate-hashes --annotation-style line \
    requirements.txt requirements-selenium.txt -o requirements-selenium.lock
uv pip compile --universal --python-version 3.9 --generate-hashes --annotation-style line \
    requirements.txt .github/requirements-ci.txt -o .github/requirements-ci.lock
```

Actions are pinned as `uses: owner/action@<40-char SHA> # vX.Y.Z`; Dependabot
(`.github/dependabot.yml`) proposes updates to both together.

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

Flippa changing its markup is the normal way this stops working, and it has its
own issue template. It happened on 2026-09-29: the embedded listing JSON this
repo read disappeared and the cards changed tag, and every run parsed 0
listings. The parser now reads the server-rendered cards
(`<li id="listing-NNN">`) and the site's own result count ("Show 676
results"). `--dump-html PATH` writes the exact bytes the parser was given, on
success as well as failure; a capture is the most useful thing a report can
carry.

## Pull requests

**Add a test for the behaviour you are changing.** `smoke_test.py` is a single
file of plain functions with inline HTML/JSON fixtures — no pytest, no
conftest, no fixtures directory. Copy the nearest existing check and edit it.

Four properties in this repo exist because they were once absent and cost real
time. Tests pin all four, so a PR that breaks one will fail rather than
silently regress:

- **Pagination is `?page=N`, and it is VERIFIED at runtime.** Every run
  fetches page 2 on its own and checks that it carries listings page 1 did
  not; if it does not, the run stops and reports `partial` rather than a
  complete-looking result holding one page. Every multi-page run in this
  repo's history before that check returned one page of rows and exit 0.
- **A run that finds nothing writes nothing.** It must not replace a good output
  file with `[]`. `--allow-empty` is the opt-out.
- **Exit codes are a contract**, not decoration: `0` ok, `1` crash, `2` bad
  usage, `3` blocked by a challenge, `4` zero listings from a listing shown
  to be empty, `5` zero listings because the content was never obtained,
  `6` partial run. A pipeline branches on these, and all four engines produce
  the same code for the same situation because they share `finish_run`.
- **A sku already written by an earlier page of the same run is dropped, not
  duplicated**, and pages are merged in PAGE order rather than arrival order,
  so a concurrent run produces the same bytes as a sequential one. See
  `dedupe_by_sku` in `output_writer.py` and `diff_runs.py`, which diffs two
  runs by the same key.
- **A zero-match query reports zero.** Flippa answers one with five PROMOTED
  listings alongside `totalResults: 0`; reporting them would be five
  fabricated rows in an empty result.

There is also a naming check: certain phrases are banned repo-wide and the suite
fails naming them. If it trips, read the message — the phrase is wrong for a
reason, not merely unfashionable.

### Style

- **Match the file you are editing.** No formatter is enforced.
- **Comments explain *why*.** What the code does is visible; why it does it that
  way, especially where the obvious version is wrong, is not.
- **A timeout on every remote call.** Every browser library used here has needed
  an explicit timeout its own API does not provide, and each has needed its own
  route out of the runtime — reporting a timeout is not the same as exiting on
  one. If you add a call to a remote browser or API, bound it.
- **Fail loudly.** A function that returns an empty list on error, or logs
  success without checking that the thing it wanted actually happened, is the
  single most common bug class in this codebase's history. A selector that
  matches the *wrong* element is worse than one that matches nothing, because
  the second one tells you.

### If your change needs a live run

Most do not — the suite covers the parser, the writers, the captcha classifier
and the CLI contract against inline fixtures. If yours genuinely needs
flippa.com, say in the PR what you ran, from which exit country, and what you
got. Product counts differ by country and by URL, so a bare "worked for me" is
not reproducible.

Do not add anything that submits the registration form. This project
deliberately never does, and a captcha token proved valid by creating a real
account is not a result worth having.

## Scope

This repo scrapes **public listing pages** on flippa.com. Out of scope:
anything behind a login, anything that submits a form, and anything that
defeats a protection rather than passing it the way an ordinary browser does.

## Licence

MIT. By opening a pull request you agree your contribution ships under it.
