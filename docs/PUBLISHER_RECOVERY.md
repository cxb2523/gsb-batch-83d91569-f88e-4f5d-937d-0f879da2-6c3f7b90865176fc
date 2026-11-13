# Publisher channels and automatic recovery

GatherRadar separates a **publisher** (`publisher_key`, for example `davvvat`) from its
**channels** (each configured Source: its website, its Instagram account) and from the
**strategy** that acquires a channel. Losing one channel is not losing the publisher.

**Publisher coverage ≠ every channel available.** A publisher is *covered* when at least
one channel contributed current-run observations. *All channels healthy* is reported
separately. Davvvat today is covered through Instagram while its website is blocked by
policy, so it is covered but not healthy.

The owner command is unchanged and non-interactive:

```bash
python -m gatherradar refresh --all-enabled --days 14
```

## Architecture

```text
Publisher (publisher_key)
└── Channel (Source: website | instagram)
    └── Strategy
        ├── website_listing     WebsiteCollector: robots, bounded list/detail
        ├── instagram_profile   owner's visible authenticated Chrome profile
        └── linked_page         depth-one approved detail page named by another channel
```

- `acquisition/strategies.py`: a strategy is selected per Source by capability
  (`supports`), never by publisher. The orchestrator has no publisher-specific branches.
  A future publisher with, say, a public RSS feed gets a new strategy class and
  registry entry, without changes to `RefreshService`.
- `acquisition/models.py`: fixed channel result vocabulary: `success`, `empty`,
  `unavailable`, `policy_blocked`, `access_restricted`, `temporary_failure`,
  `parse_failure`, and `stored` (offline). Failures are classified from the collector
  error category, never from a message, and persisted with safe diagnostics only.
- `acquisition/coverage.py`: publisher coverage, and `channel_gaps` on Events.
- `acquisition/policy.py`: cached robots re-check for policy-disabled website channels.

## Behaviour

- **Disabled channels are reported, never contacted.** `disabled_reason: robots` (or
  `terms`) reports the channel as `policy_blocked`; `owner` reports `unavailable`.
- **Run status.** A `policy_blocked` channel of a publisher that another channel covered
  does not make the run partial. Unexpected failures (network, layout, login) still do,
  even when the publisher is covered.
- **Linked pages.** A URL written verbatim in a non-website observation (for example a
  caption) may be collected when its origin is a configured website channel's origin and
  that channel's adapter accepts it as a detail page. Limits: one page per observation,
  at most `--limit` per target channel, depth one, no link following, normal robots/
  redirect checks. A disabled target is reported (`policy_blocked`) and not fetched.
- **Reference URLs.** Public URLs written in Event evidence are kept in `reference_urls`
  (platform self-links excluded) and shown as clickable workbook link columns. Their page
  content is not collected or claimed.
- **Provenance.** `Event.channel_provenance` lists each candidate's publisher, channel,
  source ID, raw observation ID, content URL, evidence slot and strategy. With
  `field_provenance` (field → candidate IDs), every fact resolves to the channel that
  really supplied it. Instagram facts are never labelled website facts.
- **Combination.** Channels complement each other only inside a Stage 8 group (the
  existing identity evidence). A shared `publisher_key` alone never merges Events.
  There is no universal channel precedence: structural facts outrank prose within one
  observation, and disagreement across channels stays a reviewable `field_conflict`.
- **No silent degradation.** When a publisher is covered only through channels that do
  not state some facts structurally, the run lists *potentially unavailable fields*
  (for Davvvat: full description, exact address, area, duration, organizer,
  availability, registration metadata, source category). Each affected Event's
  `channel_gaps` names its null fields in that set: *missing because the channel was
  unavailable*, as distinct from *the source did not expose it*. Nothing is filled.
- **Policy re-check.** At most once per 7 days per channel, only `robots.txt` is
  requested (cached in `<data-dir>/state/policy-checks.json`). `now_allowed` is
  reported with an instruction to set `enabled: true`; the source is never re-enabled
  automatically, and a failed check changes nothing.
- **Offline.** `refresh --stored` performs no acquisition, linked-page fetch or policy
  check; channels are reported as `stored`, and disabled ones still as `policy_blocked`.

## Safety (architectural, tested)

Strategies accept no user-agent, header, proxy, cookie, browser-launcher or CAPTCHA
options. Website access goes only through `HttpTransport` (fixed `GatherRadar/0.1`
user agent, `ProxyHandler({})` so environment proxies are ignored, robots enforced).
Instagram uses the existing visible, unmodified owner profile. The acquisition package
imports no stealth, scraping-evasion or alternative HTTP tooling. See
`tests/test_acquisition.py` (`NoUnsafeFallbackTests`).

## Davvvat channel investigation (2026-09-27)

`https://davvvat.ir/robots.txt` (fetched with the GatherRadar user agent, HTTP 200)
contains `User-Agent: GatherRadar` / `Disallow: /`. That rule covers every path on the
origin, including any feed, calendar, API, sitemap or page metadata, so none of these
was requested.

| Channel | Exists? | Usable by GatherRadar? | Fields | Implemented |
| --- | --- | --- | --- | --- |
| RSS / Atom | Not determined: requesting it would violate `Disallow: /` | No | — | No |
| ICS / calendar feed | Not determined (same reason) | No | — | No |
| Public / documented API | None documented; `/api/` is disallowed for all agents | No | — | No |
| Sitemap | Declared in robots.txt (`/sitemap.xml`) | No (origin disallowed for GatherRadar) | URLs only | No |
| schema.org / JSON-LD | Yes, seen on detail pages captured before the opt-out (location was a neighborhood; end before start) | No (origin disallowed) | title, dates, location name, attendance mode | No new access; extractor not added |
| OpenGraph / page metadata | Pages exist, but on the disallowed origin | No | — | No |
| Instagram `@davvvat` | Yes, owner-approved | Yes (authenticated owner profile) | title, date/time wording, venue, schedule, post URL; OCR optional | Yes (primary Davvvat channel) |
| Linked pages from captions | Captions sampled contain no URLs ("لینک توی بایو") | Generic support ready | — | Yes (generic); Davvvat yields none now |
| Third-party search/index | No official API/connector configured | Not used | — | No |

No endpoint was invented, and no traffic interception or private API was used.

## Validation (2026-09-27)

Branch `feat/portable-persistence` (HEAD `3644605`). Baseline 1,075 tests; final 1,108.

Bounded live run with the same composition as `refresh --all-enabled` (all enabled
sources, `--limit 3`, 14 days, caption-only Instagram, isolated directory
`data/stage9-validation/publisher-recovery-20260927/`, owner's existing Instagram
profile reused read-only): status **success**, 5/5 publishers covered.

| Publisher | Channel | Status | Observed |
| --- | --- | --- | --- |
| Davvvat | Instagram | success | 3 |
| Davvvat | Website | policy_blocked (not contacted) | 0 |
| Vadoostan | Website / Instagram | success / success | 3 / 3 |
| Jabama Events | Events website / Experiences website / Instagram | success ×3 | 3 / 3 / 3 |
| Emrooz Events, Tehran by Tehran | Instagram | success | 3 each |

19 canonical Events, 16 displayed. The robots re-check reported `still_blocked`. No
linked page qualified (no sampled caption named a configured website detail URL).

Davvvat recovered 3 Events from Instagram captions: `ایونت آرت سنتر` (`یکم تا سوم مهرماه
از ساعت ۱۰ تا ۲۲`), an untitled bazaar post (`۱ تا ۳ مهر، ساعت ۱۶:۰۰ تا ۲۲:۰۰`) and
`رویداد نگاه جانان` (`یکم تا سوم مهرماه`, venue `مرکزهمایش‌های رایزن`). All are 23–25 Sep 2026
ranges with inferred years, so they ended before the run and are correctly kept out of the
14-day review window (they remain in canonical history). No price, description section,
area, address or registration URL was stated in those captions.

SQLite integrity `ok`, 0 FK violations; workbook schema 3 reopens (freeze A2); JSON/CSV/
Gemini/XLSX field comparison: no mismatches; main `data/raw` and `data/evidence` hashes
unchanged. The CLI `refresh --all-enabled --days 14 --stored` on the same data exited 0
with stdin closed, no prompts, and printed the publisher/channel summary.
