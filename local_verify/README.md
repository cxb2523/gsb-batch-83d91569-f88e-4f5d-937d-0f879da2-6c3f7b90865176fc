# Local, network-free verification of the scroll record

This directory verifies the Playwright engine's per-round scroll record and
its three-way stop summary entirely on this machine — no spinny.com, no
proxy, no API key. It exists so the distinction between a cleanly exhausted
listing and a stalled lazy load can be checked from generated HTML rather
than from a live run.

## What is here

- `scripts/make_fixture.py` — writes self-contained Spinny-shaped listing
  pages (and one detail page) into a directory you choose. Each listing has
  the real grid container, card and heading markup, plus an inline
  `IntersectionObserver` lazy-loader that appends 20-car batches when the
  document bottom scrolls into view — the same trigger shape as the real
  grid, without an XHR.
- `scripts/run_local.py` — drives the **real** `playwright_scraper` (real
  argument parser, real host checks, real Chromium, real parsing, real
  sidecar) against those pages. The browser is pointed at the real
  `https://www.spinny.com/...` URLs, but a Playwright route interceptor
  fulfils every request from the generated files, so nothing reaches the
  network. The interceptor is the only test-only seam: `args.route_handler`,
  which is `None` on every real run.

Generated HTML lives in `generated/` and run output in `work/`; both are
created by the commands below and are safe to delete.

## How to run

Needs the Playwright engine and its browser once:

```bash
pip install -r requirements.txt -r requirements-playwright.txt
python -m playwright install chromium
```

Then, from the repository root:

```bash
python -I local_verify/scripts/make_fixture.py "$(pwd)/local_verify/generated"
python -I local_verify/scripts/run_local.py \
    "$(pwd)/local_verify/generated" "$(pwd)/local_verify/work"
```

`-I` (isolated mode) keeps the generated-HTML directory off `sys.path`, so
the untrusted fixture files can never be imported.

## The six scenarios

| Scenario | Fixture shape | Expected `stop_summary` / `stop_reason` | Status, exit |
|---|---|---|---|
| `target_reached` | 80 cars render, heading says 200, `--pages 3` (60) reached mid-grid | `target_reached` / `completed` | complete, 0 |
| `exhausted` | all 80 advertised cars render, then the grid settles | `listing_exhausted` / `listing_exhausted` | partial, 6 |
| `stalled` | lazy loader dies at 62 while the heading still says 200 | `scroll_stalled` / `scroll_stalled` | partial, 6 |
| `stalled_no_total` | same stall, but the page has no heading node | `scroll_stalled` / `scroll_stalled` | partial, 6 |
| `stalled_zero_total` | same stall, heading literally reads 0 | `scroll_stalled` / `scroll_stalled` | partial, 6 |
| `detail` | one car's detail page | no `scroll_progress`; `single_page_mode` | complete, 0 |

The stall scenarios also assert that every zero-growth round is kept in
`scroll_progress.rounds` as a real `"added": 0` record rather than dropped or
treated as the end, and that the per-round increments reconstruct the final
card total.
