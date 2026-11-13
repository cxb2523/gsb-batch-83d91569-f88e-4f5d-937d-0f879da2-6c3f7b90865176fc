# Contributing to the CoreClaw API Directory

Thanks for helping keep the directory accurate, useful and easy to browse.

## Quick rules

- Match Workers by their stable `owner/name` path, not by title.
- Keep titles and descriptions faithful to the public CoreClaw Store.
- Use one concise description focused on the data returned by the Worker.
- Preserve `?fpr=chris69` on public Worker URLs.
- Keep the affiliate disclosure visible in the README.
- Do not add private, unlisted or inaccessible Workers.

## Adding or updating a Worker

Every CSV record must include:

| Field | Requirement |
|---|---|
| `title` | Public Worker title |
| `path` | Stable `owner/name` path |
| `url` | Direct Worker URL ending in `?fpr=chris69` |
| `category` | One of the directory categories below |
| `source` | Human-friendly website or data source |
| `platform` | Platform label returned by CoreClaw |
| `author` | Worker publisher |
| `description` | One clear sentence describing the output |

## Categories

- E-Commerce & Marketplaces
- Social & Creator Data
- Search, Maps & SEO
- Jobs & Recruiting
- Lead Generation & Company Intelligence
- AI & Research
- Developer & Web Utilities
- Finance & Markets
- Real Estate
- Education & Knowledge
- News & Media

Choose the category that best describes the Worker’s primary use case. Use `source` for the website or service being queried.

## Validation

From the repository root:

```bash
# One command: sync the README directory and category pages from the CSV,
# then run the full validation. Safe to re-run; a second run changes nothing.
python scripts/sync_catalog.py

# CI-equivalent read-only checks (fail instead of writing files):
python scripts/sync_catalog.py --check
python scripts/generate_category_pages.py --check
python scripts/validate_catalog.py

# Offline end-to-end tests (add/delete/illegal/duplicate + idempotency):
python -I tests/test_sync_catalog.py
```

After changing `data/workers.csv`, run `python scripts/sync_catalog.py`. It
validates every record first (required fields, unique Worker paths, affiliate
URLs and known categories), regenerates the main README directory and every
category page, and then validates the result. Any problem aborts the run with
a non-zero exit code and lists every offending Worker path, file and check —
nothing is written until the CSV passes all checks. The checks verify required
CSV fields, unique Worker paths, affiliate URLs, main README coverage,
category-page coverage and the SVG banner.

## Pull-request checklist

- [ ] The Worker is publicly accessible.
- [ ] The path is unique.
- [ ] The direct URL contains `?fpr=chris69`.
- [ ] The CSV, main README and generated category pages are updated.
- [ ] The category and source are accurate.
- [ ] Both category-page and catalog validation commands pass.
