# Decisions Made

> Status: grill complete. Date 2026-08-05.
> Prerequisites: `data-sources.md` (collection methodology), `pipeline-and-scheduling.md` (pipeline and scheduling).
> This document only records **user-decided directional decisions**. Technical facts backed by measurement are in the other two documents.

## D1. Product Positioning: An Incremental Layer on Top of ccusage

**Depend on ccusage as the sole collection layer** (use `@latest`, see revision below). This project's value = the four things ccusage **explicitly does not do**:

1. Persistence (counter local 30-day cleanup)
2. Multi-machine merging
3. Automatic chart generation
4. Stable URL

Don't rebuild the parser. Reason: ccusage has 17.7k★, updates daily, and is already the de facto standard for "parsing local coding CLI logs," with native support for 15 CLIs; anyone forking this project who uses Gemini/Copilot/OpenCode etc. gets support for free.

**Claude-side v20 has passed field-by-field reconciliation** (see `data-sources.md` §4.4), including cost — v20 reports `$70.7048` for 08-03, which matches exactly the independently computed "take max output + 1h cache surcharge" corrected value (v15 reported `$61.86`). **v20 fixed both the output under-reporting issue and the 1h cache surcharge issue.**

~~⚠️ Pin the version rather than `@latest`~~ **Revised**: the user chose `@latest`, and this instinct is actually the better one — the v15 pitfall existed precisely because this machine had a year-old version installed and never upgraded; `@latest` instead always gets upstream fixes.

Compensating measure: **write the ccusage version number into every data file** (`ccusageVersion` field). If upstream behavior shifts again in the future (like the v15→v20 38% jump), a step in the time series can be immediately traced to the day the version changed.

### D1a. Codex-Side Dual-Recording — ~~scrapped~~

It was once proposed to record the in-house parser's Codex numbers as a second field to cover the 31% discrepancy. **The user explicitly vetoed this**: User: "Only depend on ccusage, don't use the in-house one."

Result: Codex numbers **default to trusting ccusage**; the 31% discrepancy remains unresolved with no local reference point. If this needs investigating in the future, `data-sources.md` §4.6 has the complete reproduction method and ruled-out hypotheses.

## D2. Repo Public + Sanitized + Forkable

**Public**: `github.com/keli-wen/token-history`.

**Sanitization red lines** (must never appear in the public repo):
- Project names / `cwd` / file paths / git branches
- Real machine names — hosts use neutral aliases (`mac-a` / `mac-b`); the mapping does not go into the repo

**Forkable reuse** is an explicit design goal, not a bonus. This means:
- No hardcoded paths; all environment-specific items go into a config file
- A generic install script + clear setup documentation
- Someone forks → changes the config → it works

## D3. Chart Delivery: Stable URL, Tolerate Cache Delay

Generate charts at fixed paths inside the repo; the user references them once in their profile README, **requiring no write access to the profile repo whatsoever**.

Accept the multi-hour lag caused by `raw.githubusercontent.com` CDN caching. Reason: data is daily-granularity, collected only 3 times a day, so a lag of a few hours is unnoticeable; in exchange, forkers get the simplest possible setup (zero cross-repo permissions).

Rejected approach: Actions writing back to the profile README to swap in `?v=<sha>` (requires a PAT, and each forker would have to configure their own).

## D4. Two Charts: tokens + cost USD

The user explicitly wants two charts. The user also holds this view — User: "**Whether the charts look good is the core of whether this kind of project gets popular.**" — visual quality is a first-class citizen; build it carefully following dataviz standards.

- **Stack dimension is by source (claude / codex), not by token type.** Stacking by type would have `cache_read` fill 99% and become a solid-color bar; stacking by source keeps both sides' magnitudes comparable (08-04: Claude ≈ 80.1M, Codex ≈ 113.1M)
- **Cost must be labeled as "API-equivalent value," not actual spend.** The user is on a subscription plan (this session hit a `session limit · resets 5:20pm`), and ccusage's `totalCost` computes "how much this would be worth at API pricing." This is a better flex ("squeezed $X of API-equivalent usage out of a $200/month subscription"), but a mislabeled tag is misleading

## D5. Codex Scope: Count Everything

Desktop + VSCode + CLI + Mobile are all counted. Reason: they share the same ChatGPT subscription quota, and from the perspective of "how much AI did I use today" they should be merged anyway; also, ccusage v20 does this by default, requiring no filter logic, keeping behavior consistent for forkers.

(Distribution reference: Codex Desktop 87.9%, codex_vscode 5.3%, codex_cli_rs 4.6%, CodexMobile 1.3%, other 0.8%. Had only the command line been counted, the number would have shrunk by ~90%.)

## D6. Detail Granularity: Day × Host × Source × Model

**Irreversible decision** — history beyond the 30-day window cannot be reconstructed; the granularity must be gotten right the first time.

`modelBreakdowns` comes free from ccusage; storing it costs nothing. If we later want to chart "model share changes" or "opus share trend," no re-collection is needed (and it wouldn't be possible anyway). Size order of magnitude: a few KB per machine per day, a few MB per year.

Not doing per-project (even hashed) — in a public repo, "number of projects and switching frequency" is itself an information leak.

---

## Not Asked / Deferred

| Item | Why it can be left for later |
|---|---|
| Handling of the `<synthetic>` model | Default: **its own row, not mixed into real model breakdown, not counted toward cost**. Reversible — adjust once real proportions are visible after running |
| The second machine's actual environment | Only the current machine has been surveyed. The other machine's ccusage version, whether Codex is installed, and whether paths match are all unknown — this is a field issue for deployment time, not one that affects the design |
| Root cause of the Codex 31% discrepancy | Covered per D1a's dual-recording. Getting to the bottom of it requires reading ccusage v20's Rust Codex adapter source — an open-ended task that does not block launch |
| Specific visual design of the charts | Belongs to the implementation phase, not a directional decision |
| Whether to backfill 42 days of history on day one | Obviously yes — and **the sooner the better**; the 06-15~07-04 batch is only surviving on the parent-alive exemption, and the whole tree disappears the moment the parent file expires |

---

## Decisions Added During the Implementation Phase (2026-08-05)

### D7. Run Entry Point: `uv run` Pins the Interpreter, Not venv

A zero-dependency project doesn't need venv — there are no packages to isolate, and it would just give forkers one more step that can fail. The real problem is **interpreter drift**: the interactive shell on this machine is anaconda 3.11.5, while under launchd it's `/usr/bin/python3` 3.9.6. The same script, manually tested versus run automatically at 12:30am, doesn't use the same interpreter.

Approach: **PEP 723 inline metadata + `scripts/run.sh`** — pins to `.python-version` when uv is present, falls back to `python3` when absent. The SVGs produced by both paths have been verified to be **byte-identical**.

⚠️ Pitfall found by testing (uv 0.6.5): **`uv run` does not automatically read `.python-version`** — both `--project .` and running bare in the repo root silently inherit the environment's python. `--python` must be passed explicitly, otherwise the whole purpose of the wrapper is defeated.

**Revised (evening of 2026-08-05): changed to a repo-level uv project.** The user asked for the standard uv workflow of `pyproject.toml + uv sync / uv run`:

- Added `pyproject.toml` (`requires-python >=3.9`, zero dependencies, `[tool.uv] package = false` — a scripts repo, not an installable package) + committed `uv.lock`
- **PEP 723 headers removed from both scripts** — keeping them would make `uv run` switch to script mode, and script mode doesn't read `.python-version`; **project mode natively respects `.python-version`** (tested: uv 0.6.5 automatically picks up 3.12), so the `--python` pitfall above no longer applies
- `run.sh` changed to `uv run --project "$REPO"`; the python3 fallback is kept (scripts remain stdlib-only and 3.9-compatible; D2's forkability is unchanged)
- CI switched from setup-python to `astral-sh/setup-uv` + `uv run scripts/render.py`

### D8. Charts: Default to 30 Daily Bars, Not Weekly Bars

The original plan was 16 weekly bars. After actually rendering it, the user judged that User: "a 16-week bar plot isn't very intuitive." Under a 30-day window, weekly aggregation leaves only 4-5 thick bars, which is harder to read than 30 thin bars and also loses the daily rhythm.

`--weeks N` can still switch back to weekly granularity. Output filenames drop the granularity prefix (`charts/tokens.svg` / `charts/cost.svg`), keeping the URL stable.

### D9. Repo Keeps Only the Most Recent 30 Days

User: "I don't like incomplete data."

⚠️ **A trade-off that needs revisiting**: by the standard of "both sources have data," the complete interval is actually **52 days starting 2026-06-15** (the Claude starting point), not 30 days. Trimming to 30 days discards 21 days of Claude data prior to 07-06, and that portion is on the 30-day cleanup countdown — **unrecoverable once it expires** (the Codex half can be backfilled anytime, since it has no cleanup mechanism).

The full 201 days have been backed up in the session scratchpad's `data-backup/`. Reverting to 52 days is a one-command change, but **it must be done while the Claude transcripts haven't expired yet**.

### D10. Colors and Fonts: Anthropic Brand, Same Hue Fine-Tuned to Pass Validation

User's call (2026-08-05 grill):

- **Claude = orange, Codex = blue** (swapped from the initial implementation). Reason: Claude is an Anthropic product, so it wears the brand's primary accent orange #d97757 family; the blue #6a9bcc family serves as secondary, for Codex. At the time the repo wasn't yet promoted, so the switching cost was close to zero
- **The official hex values are not copied byte-for-byte; hue is preserved while fine-tuning until the dataviz validation fully passes.** Failures found for the official original values: in light mode, blue #6a9bcc's saturation is below the chroma floor (looks grayish) and its contrast against the surface is only 2.85:1; in dark mode, both colors' lightness falls outside the [0.48, 0.67] band
- Final values (`validate_palette.js` fully passes; must be re-verified after any change): light `#d06a41 / #4382c9` (surface `#faf9f5`, worst CVD ΔE 20.0); dark `#db7448 / #5b95d6` (surface `#141413`, worst CVD ΔE 18.5)
- Neutral colors and surfaces use brand values directly: `#141413` / `#faf9f5` / `#b0aea5` / `#e8e6dc`; calendar-type ramps use a monochromatic brand-orange scale (monotonic lightness, light and dark modes each with their own independent steps)
- Fonts follow the brand: headings use Poppins (Arial fallback), body text uses Lora (Georgia fallback). An SVG embedded via `<img>` cannot load webfonts, so the fallback stack is the brand-specified fallback

### D11. README = Fully Expanded Chart Catalog + uv-First English Tutorial

- **The chart gallery is fully expanded, not collapsed.** The README is simultaneously "a catalog for others to pick charts from" and "a testbed for how SVG actually renders inside a GitHub README." The user's own usage: pick just one or two to reference in the profile README
- Charts go into `charts/{day,week,month}/` by granularity, with multiple styles per granularity (bar / calendar / area / card / ledger), all regenerated on every render; `charts/tokens.svg` / `cost.svg` are kept as stable aliases for the daily-granularity bar chart (the URL promise from D3/D8 is not broken)
- Quick start changed to **uv-first** (English), including uv installation and `uv run --python` usage; the python3 fallback is retained (D7 unchanged)
- Once done, commit + push for live verification (user confirmed)
</content>

### D12. Rename to `token-history`, master branch, English contexts, style-plugin gallery

User decisions (2026-08-05, evening round):

- **Repo renamed `daily_tokens` → `token-history`** ("ledger" was rejected as not plain enough; the winning criterion was "two easy words that match what the repo does"). GitHub redirects the old URLs; local directory name on disk is unchanged and harmless. launchd label became `com.token-history.collect`; the installer retires the legacy `com.daily-tokens.collect` job on sight so two collectors never run side by side.
- **Default branch is `master`, not `main`** (user preference). Renamed via the GitHub branches API; all raw-URL examples updated.
- **All durable contexts are written in English** from now on (this file included; translated 2026-08-05).
- **Chart styles are drop-in plugins**: `scripts/styles/*.py`, each exposing `build_all(days, generated) -> [(relpath, svg)]`, auto-discovered by `render.py`. A broken plugin does not take the core charts down but fails CI loudly. First four plugins — pixel (8-bit), terminal (ASCII session), sketch (xkcd hand-drawn, deterministic seeded wobble), badge (shields.io-faithful set under `charts/badge/`) — were each built and visually verified in both color modes by a dedicated subagent.
- **README got a centered header with badges (CI / uv / Python / zero-deps / MIT + three self-rendered shields), a Contents TOC, and the gallery stays fully expanded** including the new styles. A `LICENSE` file (MIT) now exists to back the badge.

### D13. Sell fork-first, position generally, styles cut across formats

User decisions (2026-08-05, third round):

- **Positioning is general, not Claude/Codex-limited**: the pitch is "never lose your AI-coding history" — Claude Code and Codex are merely the *first* sources, with more models/data feeds explicitly on the roadmap. Repo description and README hero rewritten accordingly.
- **README opens by selling the fork**: first paragraph states you can copy the repo and get your own self-updating SVGs for a profile or anywhere, and stresses that unpersisted artifacts/trajectories get expired — persistence is the point.
- **"Honest notes" section removed**; its two load-bearing facts (API-equivalent ≠ spend; nothing identifying recorded) became bullets under "How it stays correct". The 31% ccusage note lives only in contexts now.
- **Styles are skins that cut across formats**, not one-chart-one-style: the pixel language now also covers the stat card (`day/pixel-card.svg`, bitmap-font game HUD) and a badge set (`badge/pixel-*.svg`, stair-cornered arcade chips). Future styles should consider the full format matrix (bars / card / calendar / badges).
- Clone command in Quick start uses the canonical `keli-wen/token-history` rather than a `<you>` placeholder.

### D14. Clean chart bottoms, pixel refinements, repo metadata

User decisions (2026-08-05, fourth round):

- **Chart bottoms carry only the generated timestamp.** All explanatory footnote prose (token composition, cost-is-not-spend, faded-means-in-progress, scale keys) removed from every chart; load-bearing bits moved up (the pixel chart's "1PX = 10M" quantum now lives in its subtitle) or live in README/SUMMARY only.
- **Pixel badges sized to the shields idiom**: 24px total (22px body + 2px shadow) next to shields' 20px — "slightly bigger" per user. Pixel badge row also joins the README header under the flat shields row.
- **Pixel icon**: `assets/icon.svg` (+ deterministic generator `assets/gen_icon.py`) — a minted pixel coin die-struck with a rising bar chart, blue peak cap; theme-aware, crisp at 96px and 32px. Shown atop the README header.
- **SUMMARY.md stays**: user asked whether it is necessary; kept as the charts' accessibility table twin (colour-blind/screen-reader/text-only path) at zero maintenance cost.
- **GitHub topics set**: ai-coding, ccusage, claude-code, codex, data-visualization, github-profile, profile-readme, svg-charts, token-usage, usage-tracking.

### D15. Fork-first onboarding, agent setup link, simplified "why", pixel-sm badges

User decisions (2026-08-05, fifth round):

- **Quick start is fork guidance** — cloning the canonical repo gives no push target, so the human path starts with "fork, then clone YOUR fork". A `> [!IMPORTANT]` callout states why.
- **Agent-first onboarding, highlighted above the human path**: a single raw link to `SETUP.md` — a step-by-step agent instruction file (fork → configure → backfill → render → schedule → push, each with a verification) meant to be handed to Claude Code/Codex verbatim.
- **README hero shows ONE chart** — the pixel bar chart — replacing the tokens+cost pair (too duplicative up top). `charts/tokens.svg`/`cost.svg` remain rendered as stable URLs.
- **"Why this exists" reduced to three points** (data disappears → persist; the record is becoming reputation; visualized it goes anywhere, many styles provided) plus a codex-imagegen pixel banner (`assets/why.png`: terminal→trash dissolving vs vault+framed chart). The ccusage detail paragraphs and the Persist/Merge/Render/Serve table were cut; ccusage credit moved to a new **Thanks** section, which also states contributions are welcome (styles are drop-in modules).
- **Pixel badges: small variant added, big one unchanged** — `badge/pixel-*-sm.svg`, 18px total (1px glyph cells), sits at/under shields' 20px; README header now uses the -sm set.
