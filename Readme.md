## Get Cricket Data

Scripts for scraping [espncricinfo.com](http://www.espncricinfo.com/) and data on over 43,000 cricket matches.

### Scripts

* [scraper.py](scripts/scraper.py) scrapes data from espncricinfo and downloads it to a local directory.
* [parser.py](scripts/parser.py) parses the data and creates a [csv with match level data](data/final_output.csv)

### Scraping

The scraper uses the Python 3 standard library only (no third-party
packages). With no arguments it reproduces the original behaviour: the
`first class` match search, pages `0` through `6018`, a one second delay
between pages and an output directory named `espncricinfo-fc`.

```bash
python scripts/scraper.py
```

Everything is configurable:

```bash
python scripts/scraper.py \
  --start-page 0 --end-page 6018 \
  --sleep 1 \
  --output-dir espncricinfo-fc \
  --search "first class" \
  --timeout 30 --max-attempts 3 --retry-backoff 2
```

Reliability features:

* every request has a timeout and a finite number of retries with linear
  backoff;
* a search page or match page that keeps failing is recorded with its page
  number and error reason, and the run continues with the next item;
* match URLs are de-duplicated (URL fragments are ignored), and match files
  that already exist and are non-empty are skipped, so a rerun resumes
  instead of downloading everything again;
* on Ctrl+C the results collected so far are still written to the manifest.

#### Manifest

At the end of every run a machine-readable JSON manifest is written to
`<output-dir>/manifest.json` (override with `--manifest`). It contains:

* `pages`: one entry per search page with its status (`success`,
  `success_after_retry` or `failed`), the number of attempts, the error
  reason on failure and the number of match links found;
* `duplicates`: every repeated match link that was skipped, with the page it
  appeared on;
* `skipped_existing`: match links already present as non-empty files;
* `download_failures`: match links that could not be downloaded, with the
  filename, attempt count and error reason;
* `summary`: aggregate counts for all of the above;
* `run`: the configuration the run was started with.

Pages marked as fully successful in an existing manifest are skipped on the
next run; failed pages and pages with failed match downloads are retried.
Pass `--no-resume` to ignore an existing manifest.

### Parsing

```bash
python scripts/parser.py
```

Input folders and the output path can be overridden:

```bash
python scripts/parser.py --input-folders espncricinfo-fc --output final_output.csv
```

The parser is fault tolerant: an input folder that does not exist is reported
and skipped, an unreadable or empty file never aborts the whole table, and
missing fields such as `match_id` are written as empty values. The CSV header
and field order are unchanged.

### Tests

A self-contained end-to-end test (a local mock HTTP server, no network
access) covers normal pages, duplicate links, retries, failed search and match
pages, resume after interruption, an empty file and a missing input folder:

```bash
python tests/test_scraper_parser.py
```

### Data

The scripts produce [final_output.csv](data/final_output.csv)

### Application
* Article based on current scripts/data: [Fairly Random](https://github.com/outside-edge/toss_up)
* An article based on previous version of the data: [Cricket: An Unfairly Random Game?](http://gbytes.gsood.com/2011/05/07/cricket-an-unfairly-random-game/)

### License

The license is only for the scripts and not for the data. The scripts are released under the [MIT License](https://opensource.org/licenses/MIT)
