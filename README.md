[![XERJ Corpus Hub contributor](https://hub.xerj.org/contributors/MohebaliDesign/badge.svg)](https://hub.xerj.org/contributors/MohebaliDesign)

# GatherRadar

**Less scrolling. More showing up.**

GatherRadar is an open-source, local-first tool for discovering **events, workshops, exhibitions, and social gatherings** across selected websites and Instagram accounts. It brings scattered announcements into one place, identifies useful event details, and turns them into a reviewable **Persian Excel workbook** and a **Telegram experience**.

Built around a simple idea: finding something worth doing shouldn't mean checking dozens of pages, decoding posters, and copying dates into a spreadsheet.

**AI-assisted Event Discovery** · Source-grounded · Persian & English · No paid AI API required

[Get started](#quick-start) · [See what it can do](#what-you-can-do) · [Telegram bot](#telegram-bot) · [Documentation](#documentation)

> **Open-source recognition:** GatherRadar's [publisher channel recovery implementation](https://github.com/MohebaliDesign/GatherRadar/commit/9377618ce1056c0358389bda644ede427fd7d39b) was selected for inclusion in the [XERJ Corpus Hub](https://hub.xerj.org/contributors/MohebaliDesign) as a real-world reference for AI coding agents.

## Why GatherRadar?

Interesting experiences are often buried in Instagram posts, event websites, carousels, and announcements with different formats. Checking every source by hand takes time; comparing dates, locations, prices, and repeated listings takes even more.

GatherRadar streamlines that workflow. You choose the sources; it gathers public event information, connects each result to its evidence, and prepares an organized list that is easier to explore and verify.

It is designed to **help people discover experiences**, not to automate bookings or fill missing facts with guesses.

## What you can do

- **Collect from multiple sources.** Follow curated Instagram accounts and supported event websites; run all enabled sources or choose specific ones.
- **Discover events from text and images.** Analyze listings and captions, with optional local OCR for posters, carousels, and other visual evidence.
- **Make sense of schedules.** Normalize Persian and English dates, times, locations, prices, and events with multiple sessions.
- **Spot possible duplicates.** Group only well-supported matches; keep uncertain matches visible for review.
- **Keep information traceable.** Retain source links and original wording, and flag incomplete or conflicting details rather than inventing them.
- **Review everything in Excel.** Get a Persian-friendly workbook with upcoming events, schedule-review items, sources, and review history.
- **Control the workflow from Telegram.** Start crawls, select and manage sources, follow progress, browse results, and receive Excel files from the owner-controlled bot.

The default discovery pipeline uses deterministic, explainable rules. An external AI model or paid API is **not** required to run GatherRadar.

## How it works

```text
Selected public sources (websites + Instagram)
                    ↓
         Collection and evidence
       (pages, captions, optional OCR)
                    ↓
       Event discovery and extraction
                    ↓
      Dates, sessions, places, prices
                    ↓
     Duplicate checks and data review
                    ↓
         Excel + Telegram results
```

GatherRadar separates collection from interpretation. Source observations and evidence are retained locally; extracted details can be checked against their origins. Ambiguous dates, unsupported schedules, or conflicting values stay marked for review instead of being presented as certain.

## Ways to use GatherRadar

| Interface | Best for |
| --- | --- |
| **Command line** | Running collections, checking sources, and working with locally stored results. |
| **Excel workbook** | Filtering, comparing, reviewing, and keeping a record of discovered events. |
| **Telegram bot** | Managing sources and crawls from a phone, checking progress, and receiving results. |

### Excel output

A refresh writes the review workbook to **`data/review/GatherRadar.xlsx`**. It includes the current event view, separate schedule-review information, source links, and review-related sheets. Dates are presented for Persian readers, with the original evidence retained for verification.

Machine-readable CSV and JSON exports are also written under **`data/exports/`**.

### Telegram bot

The official bot is [**@GatherRadar_Bot**](https://t.me/GatherRadar_Bot). Its current deployment is **owner-only**, not a public, always-online bot service.

From the bot, the owner can:

- Crawl all enabled sources or select individual sources.
- Track actual elapsed time and view an estimated remaining-time range when local history supports one.
- Browse events and schedule-review items, expand details, and open source links.
- Receive the Excel workbook and revisit previous runs.
- Add supported sources, pause or restore them, and archive them without deleting historical results.

The bot runs locally with Telegram long polling. It answers only the configured owner while the program is running. See the [Telegram setup guide](docs/TELEGRAM_BOT_SETUP.md) for credentials, access rules, and the supported workflow.

## Quick start

### Requirements

- **Python 3.11+** and Git
- Internet access to the sources you choose
- **Google Chrome** for Instagram collection and one-time account sign-in
- Optional local OCR (Tesseract with Persian/English language data, EasyOCR, or Windows OCR) for images and posters

### Install and run

**Windows PowerShell**

```powershell
git clone https://github.com/MohebaliDesign/GatherRadar.git
cd GatherRadar
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# See the available sources
.\.venv\Scripts\python.exe -m gatherradar sources list

# Try one supported website source
.\.venv\Scripts\python.exe -m gatherradar refresh --source vadoostan_website --limit 5 --days 14
```

**macOS / Linux** (with the required browser and OCR tools configured separately)

```bash
git clone https://github.com/MohebaliDesign/GatherRadar.git
cd GatherRadar
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m gatherradar refresh --source vadoostan_website --limit 5 --days 14
```

Once the run finishes, open `data/review/GatherRadar.xlsx`. Source availability and the number of matching events vary over time.

### Collect from Instagram

Instagram uses a **dedicated local Chrome profile**. Sign in yourself once; GatherRadar does not ask for your Instagram password.

```powershell
.\.venv\Scripts\python.exe -m gatherradar auth instagram

# Collect from enabled sources, including configured Instagram accounts
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --limit 5 --days 14
```

For better text extraction from posters, install a supported OCR engine and check availability with `python -m gatherradar ocr check`. See the [local workflow guide](docs/LOCAL_REVIEW.md) for additional options and offline reprocessing.

### Run your own Telegram instance

The source includes a private, owner-controlled bot. To use it independently, create **your own bot** with [@BotFather](https://t.me/BotFather), configure your own token and Telegram user ID as environment variables, and start:

```powershell
.\.venv\Scripts\python.exe -m gatherradar telegram run
```

**Important:** The current implementation also validates the official username `GatherRadar_Bot`. If you create a separate bot, adjust `EXPECTED_USERNAME` in `src/gatherradar/telegram_bot/settings.py` to your bot's username. Never use or publish another bot owner's token. Full instructions are in [Telegram bot setup](docs/TELEGRAM_BOT_SETUP.md).

## Under the hood

GatherRadar is built with **Python** and a modular, source-aware pipeline. Its architecture keeps crawling, event interpretation, storage, and presentation separate so each part can be developed and tested independently.

| Area | Responsibility |
| --- | --- |
| `acquisition/` + `collectors/` | Approved-source access, website adapters, and Instagram capture. |
| `ocr/` + `extraction/` + `grouping/` | Image text, source-grounded signals, and discovery of event candidates. |
| `normalization/` + `deduplication/` | Dates, sessions, prices, and conservative event matching. |
| `storage/` + `review/` + `exports/` | Local records, human review, and XLSX/CSV/JSON output. |
| `orchestration/` | Runs, source progress, and workflow coordination. |
| `telegram_bot/` | Owner-only commands, source management, job status, and result delivery. |

The stack includes **Playwright/Chrome**, **SQLite**, **openpyxl**, and **python-telegram-bot**. Core event extraction is rule-based; OCR is local and optional. Detailed data contracts and implementation notes live in the linked documentation rather than this README.

### Working with sources

Built-in sources are defined in [`config/sources.yaml`](config/sources.yaml). Owner-added sources and their enabled/archived states are stored locally in `config/sources.local.json` and are not committed to Git.

Instagram accounts can be added through the Telegram manager. Websites must match a supported adapter before they can be crawled; adding an arbitrary URL does **not** create a new scraper. Disabled, archived, and access-policy-blocked sources are excluded from active collection.

## Privacy and responsible collection

GatherRadar is **local-first**. Runtime captures, Chrome profiles, credentials, databases, and exports stay on the machine running the application and are excluded from Git by the project configuration.

Collection is limited to approved public sources and must respect source terms, robots rules, and access restrictions. Do not use it to bypass authentication or collect private accounts, messages, or unrelated personal information.

Results can be incomplete: source layouts change, visual text can be difficult to recognize, and some event details may be missing or contradictory. Review source evidence before relying on an event's time, place, price, or availability.

## For developers

The codebase is open to exploration and contributions. To run the offline regression suite:

```bash
python -m unittest discover -s tests
```

If you find a bug, have an idea for a supported source, or want to contribute an improvement, open a [GitHub Issue](https://github.com/MohebaliDesign/GatherRadar/issues) or submit a pull request. Keep credentials and captured private data out of commits.

## Documentation

- [Telegram bot — setup and usage](docs/TELEGRAM_BOT_SETUP.md)
- [Local review and Excel workflow](docs/LOCAL_REVIEW.md)
- [Data model and provenance contracts](docs/DATA_CONTRACTS.md)
- [Source acquisition and channel coverage](docs/PUBLISHER_RECOVERY.md)

## Creator and license

**Created by [Mohamad Mohebali](https://github.com/MohebaliDesign)** — a product-design-led project combining event discovery, user-centered workflows, and AI-assisted development.

GatherRadar is released under the **[MIT License](LICENSE)**. Reuse and redistribution are permitted under its terms, including preservation of the copyright and license notice.

Copyright © 2026 Mohamad Mohebali.
