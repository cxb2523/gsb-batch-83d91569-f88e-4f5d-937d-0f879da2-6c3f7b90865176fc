# Pipeline and Scheduling: Multi-Machine Collection, Idempotent Writes, git Persistence, README Charts

> Status: research complete. Date 2026-08-05.
> Prerequisite: `data-sources.md` (collection methodology and retention period).

## 1. Data File Layout

**Recommended: `data/{host}/{YYYY-MM-DD}.json`**

| Scheme | Cross-machine conflict | Idempotency difficulty | Querying |
|---|---|---|---|
| **1. `data/{host}/{date}.json`** | **Structurally zero** — the two machines never write the same path | Simple: overwriting the whole file = the day's snapshot | Needs glob aggregation |
| 2. `data/{host}.jsonl` append | Zero | Cumbersome: appending doesn't naturally support "overwrite a given day" | Friendly for single-machine time series |
| 3. `data/daily.json` single file | Touches the same file every time — maximal | Worst: requires application-level read-merge-write | Most convenient |
| 4. `data/{date}.json` containing both machines | Guaranteed one conflict per day | Medium: still needs application-level merging | Convenient |

Reason for choosing 1: it's the only scheme that resolves "hosts are two independent writers" **structurally, via the file path** — not by lowering the probability of a conflict, but by making a same-path conflict **geometrically impossible**. The query-inconvenience cost is deferred to Actions (see §5).

**`claude` vs `codex` go into the content as JSON keys, not into the path.** They're collected by the same process in the same run — **there's no conflict dimension** — putting them in the path would only multiply the file count without buying any safety. With them in the content, whether "host+date collection is complete" can be checked with a single file-existence check; adding a third source in the future is just adding a key.

---

## 2. Idempotent Write Rules

**Unified into one rule**:

```
date ∈ [today−7, today]  →  blind overwrite
date <  today−7          →  merge-max only (per field, take max(existing, newly read); fill empty with present, never overwrite larger with smaller)
```

- The data source itself is still evolving for the last 7 days (the current day keeps growing, recent days may be corrected), so the newly read value is trusted as a complete snapshot
- Using merge-max for days before that is a safety net, preventing "local JSONL being cleaned up causing a recalculated smaller number to erase a historically correct larger value"
- Under normal circumstances, the per-host watermark keeps the script from ever touching days before that; merge-max only covers "manual backfill / re-running history"

**Mark the current day `partial`, change it to `final` the next day** — worth it. The extra cost is one meaningful state transition the next day (not an empty commit), in exchange for eliminating the permanent ambiguity of "is this data half-finished." When downstream charting happens, the current-day `partial` point shouldn't be treated as a final value.

---

## 3. Empty Commits and Floating Point

```bash
git add -A data/ && git diff --cached --quiet || git commit -m "..."
```

`git diff --cached --quiet` implies `--exit-code` (`man git-diff`): exits 0 with no diff (`||` short-circuits, no commit), exits 1 with a diff.

⚠️ **Floating-point rounding must be applied to the value itself as it's written to disk**, not just done transiently at the compare/hash stage. Otherwise, if a commit is skipped today after rounding, the same underlying data recomputed tomorrow will produce new trailing digits again, and the rule becomes meaningless. (Trailing-digit noise measured on this machine is ~1e-13.)

---

## 4. git Conflict Handling

**`git pull --rebase` + a retry loop** is community convention, but there's no official spec dictating the retry count. Judgment call: 5 retries with a 2/4/8/16/32s backoff is sufficient.

**With §1's per-host path split, the rebase stage almost never has a true text conflict** — the two sides never modify the same line; failures are purely non-fast-forward ref races, solvable mindlessly by retrying, with no conflict-resolution logic needed at all.

**`.gitattributes`'s `merge=union` is unnecessary, and has pitfalls**:
- git's own official docs warn: "This tends to leave the added lines in the resulting file in **random order**"
- When the same host makes a partial→final correction, union would leave both the old and new lines, producing two records with different values for the same date
- ⚠️ **The GitHub web UI's merge button does not honor `.gitattributes`** — official response: "GitHub doesn't consider user-defined .gitattributes files" ([community#9288](https://github.com/orgs/community/discussions/9288)). It only takes effect when actually running `git merge`/`git rebase` via the CLI.

**A failed push doesn't need an extra staging queue** — a local git commit is itself the queue:

```
write file → git add → git commit   (doesn't touch the network, almost never fails)
        → pull --rebase && push  (only this step can fail)
```

Even when all retries fail, the local commit remains fully intact — no data loss. The next trigger runs `pull --rebase` as usual (rebasing the unpushed commit along with it) and re-pushes; `git push` by default pushes up all commits ahead of origin together. **The only thing to add**: write an obvious warning log when failures persist across more than 3 cycles.

**Not recommended to start out with "each machine pushes its own branch + Actions merges to main"** — that trades a small risk (local push contention) for large complexity (an extra pipeline stage depending on Actions' schedule, which itself has the reliability issues in §5). Only escalate to this if testing shows direct pushes frequently fail.

---

## 5. Positioning of GitHub Actions

**Used only to generate derived views (aggregation / charts / README updates); source data integrity does not depend on it running on time at all.** Actions being late, dropping a run, or not running for several days in a row doesn't affect correctness — only chart freshness.

Limitations officially acknowledged:
- **Can be delayed**: "The `schedule` event can be delayed during periods of high loads"; officially recommended **not to schedule on the exact hour**
- **Can drop runs**: "If the load is sufficiently high enough, some queued jobs may be dropped"
- **Auto-disables after 60 days of inactivity** for scheduled workflows (only a new commit resets the timer; opening an issue/publishing a release doesn't count)
- Only runs on the latest commit of the default branch

**Recursion protection is official default behavior; `[skip ci]` is not needed**:
> if a workflow run pushes code using the repository's `GITHUB_TOKEN`, a new workflow will not run even when the repository contains a workflow configured to run when push events occur.

⚠️ But **this machine's push over SSH uses your own identity, not `GITHUB_TOKEN`** — local pushes **will** normally trigger the aggregation workflow. This is exactly what's wanted — don't confuse the two.

**Quota**: a public repo on standard runners is **free and unlimited**; the private free plan gets 2,000 Linux minutes/month (macOS counts 10x). 3 times a day × 1 minute ≈ 90 minutes/month — not a bottleneck.

---

## 6. macOS Scheduling

### 6.1 launchd's Catch-Up Behavior

**Sleep — explicitly documented** (`man 5 launchd.plist`, verified against the original text on this machine's macOS 15.6):
> Unlike cron which skips job invocations when the computer is asleep, launchd will start the job the next time the computer wakes up. **If multiple intervals transpire before the computer is woken, those events will be coalesced into one event** upon wake from sleep.

That is, if N intervals are missed, only **1** catch-up run happens after waking.

**Power-off — the documentation is silent.** That man page passage only covers sleep. Community testing consistently concludes that misses during power-off are simply skipped, not caught up, going straight to the next scheduled point. ([Apple Community 5137946](https://discussions.apple.com/thread/5137946), [Apple Forums 815034](https://developer.apple.com/forums/thread/815034))

⚠️ **Correcting a widely circulated error**: it's commonly said online that "`StartCalendarInterval` implies `RunAtLoad`" — **the man page says no such thing**. What actually says "implies RunAtLoad" is `KeepAlive`. The two keys are completely independent.

→ **Cover the power-off scenario via `RunAtLoad=true`** (runs once immediately on every load; harmless because of idempotency — the only side effect is one extra run when debugging bootstrap).

**Catch-up logic must be built into the script itself; it cannot be expected of launchd.**

### 6.2 Schedule Frequency: Keep 00:30 / 12:00 / 21:00, Don't Switch to Hourly

Reasons for not splitting the difference:
- Hourly can only alleviate the **transient** problem of "sleep/network-down at exactly that moment." Three spread-out points + next-day 00:30 + the 7-day watermark already self-heal, losing no data — only losing the fine granularity of "multiple sample points within a day"
- Hourly **does not solve at all** the truly dangerous scenario — extended power-off. If a machine is powered off for two days while traveling, both hourly and three-times-daily miss everything equally, no fundamental difference. The actual remedy is `RunAtLoad` + watermark, already covered
- The cost isn't zero: 24×2-machine scheduling overhead, log noise, edge cases from overlapping runs
- The three time points likely carry business meaning (midday/evening checkpoints); switching to hourly would erase that layer of semantics

### 6.3 TCC / Full Disk Access: **Not Needed**

Measured on this machine (the current shell explicitly does **not** have FDA — all 15 paths like `~/Library/Safari`, `~/Library/Mail` return `Operation not permitted`):

```
~/.claude      READABLE
~/.codex       READABLE
~/OpenSource   READABLE
```

**Precondition: the repo must not live under `~/Documents` / `~/Desktop` / `~/Downloads` / iCloud Drive / external volumes / network volumes** — those are what TCC actually governs. `/Users/wenkeli/OpenSource/daily_tokens` is safe.

If FDA is ever genuinely needed: the grant target is the **interpreter binary** (`/bin/bash` or `node`), not the script file (TCC cannot compute a designated requirement for a text file). And Homebrew's `node` is **ad-hoc signed** (CDHash changes on every recompile), so `brew upgrade node` will **silently revoke** the grant ([claude-code#55661](https://github.com/anthropics/claude-code/issues/55661)). One more reason to "not rely on FDA."

`man 5 launchd.plist` CAVEATS, original text:
> Daemons and agents managed by launchd are subject to macOS user privacy protections. Specifying privacy sensitive files and folders in a launchd plist may not have the desired effect, and may prevent the job from running.

### 6.4 git Credentials: **Use SSH**

Current state on this machine (measured):
- `~/.gitconfig` has `credential.https://github.com.helper = !/opt/homebrew/bin/gh auth git-credential` set; the token lives in the keyring
- `~/.ssh/id_rsa` / `id_ed25519` / `id_test` — **all three have no passphrase**
- `~/.ssh/config` has `github.com → ssh.github.com:443` (working around port 22 being blocked)
- `ssh -T git@github.com` → `Hi keli-wen!` ✓

**The current HTTPS + gh path is the most fragile**: [cli/cli#13317](https://github.com/cli/cli/issues/13317) — keychain reads have a ~3 second timeout, and **on failure, `gh` returns an empty token and continues on as unauthenticated** — what you see is an inexplicable 403, not a credential error.

**SSH doesn't touch keychain, doesn't touch ssh-agent, doesn't touch TCC, and isn't affected by brew upgrade.**

```bash
git -C /Users/wenkeli/OpenSource/daily_tokens remote set-url origin git@github.com:keli-wen/token-history.git
```

Declare explicitly in the script rather than relying on inherited state:
```bash
export HOME=/Users/wenkeli
export GIT_SSH_COMMAND='/usr/bin/ssh -F /Users/wenkeli/.ssh/config -o BatchMode=yes -o IdentitiesOnly=yes -i /Users/wenkeli/.ssh/id_rsa'
export GIT_TERMINAL_PROMPT=0   # fail fast, don't hang
```

Optional hardening: generate a dedicated ed25519 **deploy key** (write access) for this repo, instead of reusing the personal `id_rsa`.

### 6.5 Other macOS Pitfalls

- **PATH is `/usr/bin:/bin:/usr/sbin:/sbin`** (measured on this machine's running LaunchAgent). `node`/`gh` live in `/opt/homebrew/bin`, **absolute paths must be used, or `EnvironmentVariables.PATH` set in the plist**
- **`/usr/bin/git` is Apple's git**, and loads `/Applications/Xcode.app/.../git-core/gitconfig` — your `credential.helper=osxkeychain` and `init.defaultBranch=main` actually come from there, not from your dotfiles. This changes when Xcode updates
- The LaunchAgent shows up under **System Settings → Login Items & Extensions → "Allow in the Background"**, and can be accidentally toggled off (turning it off doesn't delete the plist, but it stops running). If the job mysteriously stops, check here first
- **Do not set `SessionCreate`** — it throws the job into a new audit session, which actually detaches it from Aqua's keychain context
- LaunchAgent defaults to an `Aqua` session, **only loaded into `gui/501` on GUI login**. FileVault is enabled on this machine with no auto-login, so someone must already have logged in by the time the job runs

### 6.6 plist Skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wenkeli.daily-tokens</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/wenkeli/OpenSource/daily_tokens/scripts/collect.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/wenkeli/OpenSource/daily_tokens</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/wenkeli/Library/Logs/daily-tokens.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/wenkeli/Library/Logs/daily-tokens.log</string>
</dict>
</plist>
```

launchd does not do `~` expansion — all paths must be absolute.

**The correct commands for macOS 15+** (the man page marks `load`/`unload` as Legacy; the Recommended alternative is `bootstrap | bootout | enable | disable`):

```bash
# Install (after editing the plist, you must bootout then bootstrap — there is no reload)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wenkeli.daily-tokens.plist

# If it was turned off via "Allow in the Background," explicit enable is needed
launchctl enable gui/$(id -u)/com.wenkeli.daily-tokens

# Trigger it manually right now (for debugging)
launchctl kickstart -k gui/$(id -u)/com.wenkeli.daily-tokens

# Check status: whether loaded, next trigger time, last exit code
launchctl print gui/$(id -u)/com.wenkeli.daily-tokens

# Uninstall
launchctl bootout gui/$(id -u)/com.wenkeli.daily-tokens
```

Debugging first step is always to configure `StandardOutPath` + `StandardErrorPath`. A TCC denial manifests as **EPERM** (`Operation not permitted`), while a POSIX permission issue is EACCES — these two must be distinguished.

---

## 7. Existing Solutions

### 7.1 The Only Direct Match: `Baek-Seunghyun/ai-coding-usage-card`

- 24★ / 10 forks / MIT, created 2026-07-15, last push 2026-07-23 — **only about 3 weeks of history, not a mature project**
- Calls `npx -y ccusage@latest --json` (**not version-pinned**); one `cards/devices/<device>.json` per device; merges by taking the daily max high-water mark
- Explicitly **forbids** syncing log directories across machines; its approach is to **account per-device separately then sum**, with no session-level dedup
- Officially states it **provides no automatic recall/backfill**, but the high-water-mark merge has an implicit catch-up effect
- Produces 4 contribution-graph-style SVGs committed into the repo, run via local cron/launchd (**not Actions** — the cloud can't read `~/.claude`)
- The README recommends staggering times across multiple devices (e.g. 09:37/09:42/09:47) to avoid git conflicts

Against this project's requirements: cross-machine merging ⚠️ (separate accounting, not dedup), recall window ⚠️ (implicit), weekly chart ⚠️ (a heatmap, not a weekly chart), day-to-day detail ⚠️ (inside a snapshot JSON, not day-by-day readable).

**Directly reusable**: the daily max high-water-mark merge algorithm (very little code).

### 7.2 Nothing Found in Any Other Direction

`claude code usage badge` / `claude token usage action` / `codex usage readme` / `claude code usage readme` — gh search **all returned empty**.

The `claude-code-stats` family (AeternaLabsHQ 29★, dmelo 19★, nermalcat69 5★), the `llm-usage-tracker` family, and the popular `Maciek-roboblog/Claude-Code-Usage-Monitor` (8,590★), `Iamshankhadeep/ccseva` (800★) — **are all local dashboards/menubar apps that don't write back to git/README** — a different product line entirely.

**Conclusion: only one project works on the "local collection → git persistence → README chart" niche, and it's quite immature. Building it in-house is a reasonable choice.**

### 7.3 Techniques Worth Borrowing from the waka-readme Family

`athul/waka-readme` 1,830★ (updated 2026-08-01), `anmol098/waka-readme-stats` 3,976★ (updated 2026-08-04).

- **Automatic README updates**: the `<!--START_SECTION:waka-->` … `<!--END_SECTION:waka-->` marked region is replaced wholesale via regex. **This technique has been proven for years and the ecosystem is mature — it can be directly copied.**
- **Chart form: ASCII bar chart**, with characters customized via the `BLOCKS` environment variable (`░▒▓█` / `⣀⣄⣤⣦⣶⣷⣿`). Zero dependencies, zero image hosting, pure Markdown rendering
- ⚠️ Their scheduling is pure GitHub Actions (because they read the WakaTime **cloud API**) — **this project cannot copy that** — its data source is local

---

## 8. Constraints on README Chart Rendering

| Approach | Conclusion |
|---|---|
| **ASCII / emoji bar chart written directly in markdown** | Most stable. Zero dependencies, no caching issues, no privacy risk. Production-proven for years by waka-readme |
| **SVG committed into the repo + referenced via `<img>`** | Feasible and controllable. ⚠️ See the caching pitfall below |
| **mermaid `xychart-beta`** | GitHub renders mermaid natively, but its bundled version lags upstream (upstream was still fixing xychart label occlusion as of 2026-03). Good enough but poorly controllable |
| **quickchart.io and other third-party chart hosts** | Not recommended. 120 req/min/IP rate limit, free tier of 1000 charts/month; and the chart config (including your usage/spend data) is encoded in the URL and sent to a third-party server |

### 8.1 Caching Pitfall (must be avoided)

- **camo (`camo.githubusercontent.com`) only proxies images outside the GitHub domain** (shields.io etc.)
- **`raw.githubusercontent.com` doesn't go through camo, but has its own independent CDN cache** (community observations put the default at ~5 minutes; in some cases `Cache-Control: max-age=86400`, i.e. 24 hours) — this is the real reason for "committed a new image but the page still shows the old one" ([community#46773](https://github.com/orgs/community/discussions/46773), [#46758](https://github.com/orgs/community/discussions/46758))
- **The only reliable workaround**: append a timestamp or commit-sha as a query string to the URL (`?v=<sha>`); changing the URL changes the cache key. **Cannot rely on "waiting for the cache to expire"**

### 8.2 SVG Sanitize Boundary

- A raw `<svg>` tag pasted directly into Markdown will have `<script>` etc. stripped by the sanitizer
- But **when referenced via `<img src="x.svg">`, the SVG's internal `<style>` (including `@keyframes` animations) is preserved and renders normally**
- ⚠️ The `prefers-color-scheme` inside the SVG follows the **browser/system** color preference, **not GitHub's own in-site light/dark theme toggle** — the two may disagree
- GitHub's officially recommended dark-mode approach is `<picture>` + `<source media="(prefers-color-scheme: dark)">` + a fallback `<img>`, replacing the old `#gh-dark-mode-only` fragment trick

---

## 9. A Practical Problem with the Data Shape

Measured on this machine (Claude side, Asia/Shanghai):

```
2026-08-04   input 22,160   output 776,447   cache_creation 2,829,605   cache_read 76,486,943
```

**`cache_read` is 100x larger than `output`.** If the weekly chart plots stacked bars of "total tokens," **99% of the area will be cache_read**, and the output portion will be essentially invisible.

Which primary metric to choose (total / output / separate dual scales) is a design decision that must be settled up front — not an implementation detail.
</content>
