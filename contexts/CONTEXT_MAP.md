# CONTEXT_MAP

Durable context index for `token-history` (formerly `daily_tokens`). Register new contexts here.

## Conventions

- One topic per file, filenames use kebab-case
- Each context starts with a **status** and **date** marker
- Strictly distinguish "verified by measurement" from "inference"; list unresolved items in their own section — **do not paper over them**
- Numbers must be reproducible — give the command or file path, not "approximately"

## Index

| File | Topic | Status |
|---|---|---|
| [`decisions.md`](./decisions.md) | **User-decided directional decisions** — product positioning, repo visibility and sanitization, chart delivery, metrics, Codex scope, detail granularity, Anthropic color scheme, README catalog and uv-first | Complete |
| [`data-sources.md`](./data-sources.md) | Location, schema, dedup rules, retention period and recall window for Claude Code / Codex CLI local data, ccusage version status | Complete, with 1 unresolved item |
| [`pipeline-and-scheduling.md`](./pipeline-and-scheduling.md) | File layout, idempotency rules, git conflict handling, GitHub Actions positioning, macOS launchd scheduling, README chart rendering constraints, survey of existing solutions | Complete |

## Project Goal (one sentence)

Two macOS machines collect local Claude Code + Codex token usage daily at 00:30 / 12:00 / 21:00, idempotently persisting it into
`github.com/keli-wen/token-history` (to counter local 30-day cleanup), and render a gallery of chart styles for the README.

## Currently Unresolved

0. **The repo only keeps 30 days, but the full interval where "both sources are complete" is 52 days** — see `decisions.md` D9.
   The extra 21 days of Claude data are on a cleanup countdown; backfill it early.
1. **31% discrepancy in Codex-side accounting** — ccusage v20 reports 36,945,083, the in-house parser reports 53,206,631. Which is correct is unknown.
   See `data-sources.md` §4.6. Per `decisions.md` D1a the in-house parser was vetoed; **ccusage numbers are trusted as-is — not blocking launch**.
2. **The second machine's environment has not been surveyed** — ccusage version, whether Codex is installed, whether paths match are all unknown. A field issue for deployment time.

(The original three items — "primary metric undecided," "synthetic," "subscription or API billing" — have been resolved during the grill; see `decisions.md` D4 and "Not asked / deferred.")

## Settled Foundations (no longer up for discussion)

- Claude side: upgrading ccusage to v20 is sufficient; field-by-field reconciliation passes; the old v15.7.1 under-reports by 38.93%
- Codex side: accumulate `last_token_usage` (not `total`), bucket by event timestamp, dedup within a file by `(ts,in,out)`
- Field semantics differ between the two sides: Codex's `input_tokens` **includes** cached, Claude's are separate
- Timezone fixed to **Asia/Shanghai**, written into the record
- Layout `data/{host}/{YYYY-MM-DD}.json`, `claude`/`codex` as JSON keys
- Idempotency: blind overwrite for the last 7 days, merge-max only before that
- watermark **per-host**
- git goes over **SSH**, all executables in the script use absolute paths
- Scheduling stays at 00:30/12:00/21:00 + `RunAtLoad=true`, catch-up logic is built into the script
- Actions only generates derived views; source data integrity does not depend on it
</content>
</invoke>
