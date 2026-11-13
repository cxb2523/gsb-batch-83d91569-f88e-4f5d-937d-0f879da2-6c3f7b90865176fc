# Marktplaats Scraper

[![CI](https://github.com/chadsr/marktplaats-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/chadsr/marktplaats-scraper/actions/workflows/ci.yml)
[![Docker](https://github.com/chadsr/marktplaats-scraper/actions/workflows/docker.yml/badge.svg)](https://github.com/chadsr/marktplaats-scraper/actions/workflows/docker.yml)
[![codecov](https://codecov.io/gh/chadsr/marktplaats-scraper/graph/badge.svg?token=UISQZBFTMR)](https://codecov.io/gh/chadsr/marktplaats-scraper)

Marktplaats.nl (Dutch Classifieds) Listing Scraper.

## Configuration

```shell
usage: mpscraper [-h] [--limit LIMIT] [--headless HEADLESS] [--chromium-path CHROMIUM_PATH]
                 [--driver-path DRIVER_PATH] [--timeout TIMEOUT] [--recrawl-hours RECRAWL_HOURS]
                 [--data-dir DATA_DIR] [--wait-seconds WAIT_SECONDS]

options:
  -h, --help            show this help message and exit
  --limit, -l LIMIT     The limit of new listings to scrape. (MP_LIMIT) (default: 0)
  --headless HEADLESS   Run browser in headless mode. (MP_HEADLESS) (default: False)
  --chromium-path CHROMIUM_PATH
                        Path to Chromium executable. (default: /usr/bin/chromium)
  --driver-path DRIVER_PATH
                        Path to Chromium ChromeDriver executable. (default: None)
  --timeout, -t TIMEOUT
                        Seconds before timeout occurs. (MP_TIMEOUT_SECONDS) (default: 10)
  --recrawl-hours, -r RECRAWL_HOURS
                        Recrawl listings that haven't been checked for this many hours or more
                        (MP_RECRAWL_HOURS) (default: 24)
  --data-dir, -d DATA_DIR
                        Directory to save output data. (default: ./)
  --wait-seconds WAIT_SECONDS
                        Seconds to wait before re-trying after being rate-limited. (MP_WAIT_SECONDS)
                        (default: 10)
```

## Running

### Docker

```shell
mkdir data/ && chown -R 1000:1000 data/
docker run -it -v ${PWD}/data:/data ghcr.io/chadsr/marktplaats-scraper:latest
```

### UV

```shell
uv sync
uv run mpscraper -d data/
```

## Output files

All output is written to the directory given by `--data-dir` (`./` by default).

- **`listings.csv`** — the scraped listings. Its columns and the `item_id`-based
  de-duplication are unchanged; advertisements (item IDs prefixed with `a`) and IDs
  already present in `existing_item_ids` are still skipped.
- **`crawl_pages.json`** — a page-level run record produced on every crawl that
  fetches at least one page. It lets you verify how far each sub-category paged, why
  it stopped, and which pages were swallowed by rate-limiting or timeouts. No file is
  written when a crawl produced no page records.

### `crawl_pages.json` structure

```json
{
  "status": "completed | interrupted | running",
  "started_at": "<ISO-8601 UTC>",
  "finished_at": "<ISO-8601 UTC or null>",
  "summary": {
    "parent_categories_crawled": 0,
    "successful_pages": 0,
    "empty_pages": 0,
    "rate_limited_attempts": 0,
    "timeout_attempts": 0,
    "element_missing_attempts": 0,
    "other_error_attempts": 0,
    "error_skipped_pages": 0,
    "total_attempts": 0,
    "total_new_listings": 0
  },
  "parent_categories": [
    {
      "category_id": 0,
      "category_url": "...",
      "subcategories": [
        {
          "category_id": 0,
          "category_url": "...",
          "stop_reason": "empty_page | limit_reached | retries_exhausted | interrupted | error",
          "pages": [
            {
              "page": 1,
              "attempt": 1,
              "result": "success | empty | rate_limited | timeout | element_missing | error",
              "new_listings": 0,
              "error": "optional error message",
              "timestamp": "<ISO-8601 UTC>"
            }
          ]
        }
      ]
    }
  ]
}
```

Every attempt at a sub-category page is recorded separately, including each
rate-limit/timeout retry (the `attempt` field starts at 1 and increments per retry of
the same `page`), so a page that failed multiple times leaves one record per attempt
rather than only the last one.

- An **empty page** is recorded with `result: "empty"` and is the stop reason
  (`stop_reason: "empty_page"`) that terminates paging for that sub-category.
- **Rate limiting** (`rate_limited`) and **timeouts** (`timeout`) are retried using
  the existing wait logic. If every retry fails, the page is counted once in
  `error_skipped_pages` and the sub-category stops with `retries_exhausted`.
- Reaching the configured **limit** stops paging with `limit_reached`.
- If the process is interrupted with **Ctrl+C / SIGTERM**, all already-completed page
  records have already been flushed to disk, and the final record is marked
  `status: "interrupted"` (the active sub-category gets `stop_reason: "interrupted"`).

A human-readable version of the summary is also logged at the end of each run.

## Examples

1. [**Category Classification Model**](./examples/category_classification/) - Predicts the appropriate Marktplaats category for a given listing title text.
2. [**Category Statistics**](./examples/category_statistics/) - Calculates some basic data-science/statistics tasks for a given category, ranking views/popularity of listing types.
