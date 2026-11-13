# Data Sources: Local Token Usage for Claude Code and Codex CLI

> Status: research complete, with 1 unresolved item. Date 2026-08-05.
> All numbers are measured on keli-wen's local machine (macOS 15.6, Darwin 24.6.0).

## 1. Claude Code

### 1.1 File Location and Discovery

```
~/.claude/projects/**/*.jsonl        # recursive, includes subagents/
```

- `subagents/` accounts for **54% of assistant lines** (22,644 / 42,104), and has **zero overlap** with the main conversation
  (the count of lines with `isSidechain=true` exactly equals the count of subagent lines; the number of duplicate groups spanning "main file ↔ subagent file" is 0)
- Nesting reaches depth 6: `projects/<proj>/<uuid>/subagents/workflows/wf_*/agent-*.jsonl`
- The environment variable `CLAUDE_CONFIG_DIR` supports comma-separated multiple paths; once set, it **completely replaces** the default paths
  (the default paths are `${XDG_CONFIG_HOME:-~/.config}/claude` and `~/.claude`; if both exist, both are scanned)

### 1.2 Row Schema

Only rows with `type == "assistant"` carry usage. Relevant fields:

| Path | Description |
|---|---|
| `timestamp` | ISO8601, UTC |
| `message.id` + `requestId` | The two halves of the dedup key |
| `message.model` | e.g. `claude-opus-5`, `<synthetic>` |
| `message.usage.input_tokens` | Counted **separately** from cache_read |
| `message.usage.output_tokens` | ⚠️ see 1.3 |
| `message.usage.cache_creation_input_tokens` | = sum of the two items below |
| `message.usage.cache_creation.ephemeral_5m_input_tokens` | |
| `message.usage.cache_creation.ephemeral_1h_input_tokens` | Accounts for 55.6% of cache creation on this machine; **priced higher** |
| `message.usage.cache_read_input_tokens` | |
| `message.stop_reason` | Non-null on the true-value row; `None` on placeholder rows |

The `costUSD` field **does not exist** in this machine's data.

### 1.3 Key Pitfall: A Single API Call Is Written Across Multiple Lines

Claude Code writes each content block of a single API response as its own line, sharing the same `message.id` + `requestId`. There are **two patterns** (from a full-corpus census, 16,144 unique groups):

| Pattern | Group count | Description |
|---|---|---|
| Single line | 2,723 | Unambiguous |
| Multi-line with constant `output_tokens` | 7,207 | The final usage is repeated on every line; taking any line gives the correct value |
| Multi-line with increasing `output_tokens` | **6,198** | Earlier lines are small placeholder values; only the last line is the true value |

An instance of the increasing pattern (`msg_01BskaBd9EoS9tgW`):

```
out=3      blocks=['thinking']  content_chars=203,333 (~50,833 tok)  stop=None
out=3      blocks=['text']      content_chars=117                    stop=None
out=54,509 blocks=['tool_use']  content_chars=304                    stop=tool_use
```

**Correct operator: group by `(message.id, requestId)` and take `max(output_tokens)`.**
`max` is correct for both patterns; `sum` would blow up the constant pattern by a factor of N (48 identical-value lines have been observed).

First-line vs max, full-corpus gap: 13,625,367 vs 22,312,654 = **under-reports by 38.93%**.

### 1.4 Date Attribution

Bucketed by `timestamp`; **the timezone must be fixed and recorded**. Testing shows the same day's cost differs by 13% between `Asia/Shanghai` and `UTC`. This project fixes the timezone to **Asia/Shanghai**.

### 1.5 Current State on This Machine

16,144 unique groups, covering **42 days**, spanning `2026-06-15 .. 2026-08-05`.

---

## 2. Codex CLI

### 2.1 File Location

```
~/.codex/sessions/{YYYY}/{MM}/{DD}/rollout-*.jsonl
~/.codex/archived_sessions/rollout-*.jsonl        # flat layout, must be scanned together
```

- `archived_sessions` is **manually archived, move semantics**, with **zero id overlap** with `sessions/` (179 vs 1049)
- Archived file contents are complete, with `token_count` events fully present — **missing this scan means missing data**
- ⚠️ The binary contains a `local_thread_store_compression` feature flag, whose output is `.jsonl.zst`, with an outcome that includes `removed`.
  Currently not enabled (`.zst` file count is 0), but **the glob should match both `*.jsonl` and `*.jsonl.zst` from day one**,
  otherwise data will be silently missed the moment upstream enables it.

### 2.2 Event Schema

Take `payload.type == "token_count"`:

```json
{"timestamp":"...","type":"event_msg","payload":{"type":"token_count","info":{
  "total_token_usage":{...}, "last_token_usage":{...}, "model_context_window":258400},
  "rate_limits":{...}}}
```

**`last_token_usage` is the current turn's delta; `total_token_usage` is the session cumulative total.** Verified exactly by measurement:

```
sum(last.output) = 8,537       final total.output = 8,537      ✓
sum(last.input)  = 2,189,545   final total.input  = 2,189,545  ✓
total_tokens monotonically non-decreasing ✓        every event carries a timestamp ✓
```

**Correct method: accumulate `last_token_usage`, bucketed by each event's own timestamp.**
Taking the `total` at the end of a session would attribute an entire cross-day session to the last day.

### 2.3 Field Semantic Differences from Claude (a pitfall when merging)

**Codex's `input_tokens` includes `cached_input_tokens`; Claude's `input_tokens` and `cache_read_input_tokens` are separate.**

Confirmed by measurement (2026-08-01): my `input − cached` = 1,885,144 − 1,722,624 = 162,520, exactly equal to ccusage's `inputTokens`.

→ When normalizing, Codex's "uncached input" = `input_tokens − cached_input_tokens`.

### 2.4 Deduplication

- **Cross-file duplicates: 0** (1,233 files, 92,599 events, checked by `(ts, in, out)`)
- **No fork-replay issue** — `session_meta` has no fork/parent pointer at all
- **741 within-file duplicate pairs, all adjacent** (two consecutive lines identical); another 6 pairs are non-adjacent but with values `(0,0)`
- Inflation without dedup: **0.951%** (53,668,256 vs 53,162,626)

→ Deduping within a file by `(timestamp, input_tokens, output_tokens)` is sufficient.

### 2.5 originator Distribution (output over the full period)

| originator | files | out_tokens | share |
|---|---|---|---|
| Codex Desktop | 1075 | 46,777,480 | 87.9% |
| codex_vscode | 47 | 2,845,957 | 5.3% |
| codex_cli_rs | 43 | 2,443,101 | 4.6% |
| CodexMobile | 18 | 710,754 | 1.3% |
| codex-tui | 10 | 347,897 | 0.7% |
| codex_exec | 24 | 64,991 | 0.1% |
| Claude Code | 5 | 19,114 | 0.0% |

**The vast majority of usage comes from Codex Desktop in ChatGPT.app, not the CLI.** This affects the definition of "what to count."

### 2.6 No Cleanup Mechanism

`config.toml` contains no retention/cleanup keys anywhere. Files in `sessions/2025-09-04` (11 months old) are still fully readable. All 666 ids in `session_index.jsonl` have **zero losses** on disk.

(`max_rollout_age_days` exists but belongs to the `[memories]` section — it is the **read scope** for memory consolidation, not a deletion policy.)

---

## 3. Retention Period and Recall Window

### 3.1 Claude Code's Cleanup Mechanism

- `cleanupPeriodDays` **defaults to 30 days**, `0` = disabled
- The determination is based on **file mtime**; file contents are never read
- Cleanup granularity: when the parent `<uuid>.jsonl` expires and is deleted, `rm -rf <uuid>/` removes the entire directory root and all
- **Parent-alive exemption**: while the parent transcript exists and hasn't expired, its `subagents/` tree is **entirely skipped** — no matter how old the files inside are, they aren't deleted

### 3.2 Reconciliation with Observed Local Data

Apparent contradiction: `2026-08-04 − 30d = 2026-07-05`, yet the machine has files from `2026-06-15`.

Resolved: those 166 old files are **all inside `subagents/`**, with a parent transcript mtime of 7/10~7/11 (still alive). The oldest top-level transcript actually subject to scanning is `2026-07-04T08:05:18Z`; `.last-cleanup` (`2026-08-03T05:55:05Z`) minus 30 days = `2026-07-04T05:55:05Z`, a **gap of 2 hours 10 minutes, with not a single file before it**. The 30-day boundary matches exactly.

### 3.3 `.last-cleanup` Is Not a Daily Rate Limit

The marker's 24h freshness window can only **delay** cleanup by 10 minutes (the state machine's second tick doesn't recheck the sentinel). This machine measured **3** cleanup runs on 8/3 alone. **There is no grace period to rely on.**

(The documentation says "deletes at startup," but it's actually a background task delayed 5 seconds after startup + gated by 60s of user idle time. The documentation and the code disagree.)

### 3.4 Hard Guarantee and Window Recommendation

**Derivation**: the deletion predicate is `mtime < now − 30d`, and a file's mtime ≥ the timestamp of any message inside it
⇒ records for calendar day D exist only in files with mtime ≥ D
⇒ **for any day D, Claude data is guaranteed readable for 30 days starting from D.**

| Phase | Window | Description |
|---|---|---|
| Cleanup avoidance (before persisted to repo) | **21 days** | Deducted from 30: cutoff isn't midnight −1, UTC/CST timezone −1, the other machine's `cleanupPeriodDays` unknown −4, cleanup can trigger anytime with no grace −3 |
| Missed-run avoidance (already persisted to repo) | `clamp(time since last successful run + 2, 3, 21)` | **watermark must be per-host** — otherwise machine A running daily would flatten machine B's watermark |

The Codex side has no cleanup constraint; the window is driven only by "missed-run avoidance."

### 3.5 Three Things More Important Than Window Size

1. **Non-destructive writes**: for days with `date < today−7`, only **filling gaps and correcting upward (merge-max)** is allowed; overwriting downward is forbidden.
   On the day at the window's edge, "some files may have already expired," and overwrite-style writes would **shrink** an originally correct number — a missed collection is visible, a shrunk number is not.
2. **Read the actual config at runtime**: `W = min(W, (settings.cleanupPeriodDays ?? 30) − 7)`.
   Merge order: managed policy > user settings > default 30. The other machine may have set a smaller value, and managed settings aren't even visible yet.
3. **Scan paths must be complete** (see 1.1 / 2.1).

### 3.6 Failure Scenarios

| Scenario | Covered by the 21-day window? |
|---|---|
| Continuously powered off ≤ 21 days | ✅ |
| Continuously powered off 22–30 days | ⚠️ Covered as a fallback by non-destructive writes |
| Continuously powered off > 30 days | ❌ Claude-side data is definitively lost; no window can save it |
| A machine has `cleanupPeriodDays: 14` set | ❌ Must rely on the runtime clamp |
| User manually deletes a thread in the Codex UI | ❌ Cannot be defended against |
| Codex enables zstd compression | ❌ Must rely on the glob supporting `.zst` |

---

## 4. Status of ccusage (important correction)

### 4.1 The Version Installed on This Machine Is Out of Date

- This machine: `/opt/homebrew/bin/ccusage` **v15.7.1** (package mtime 2025-08-06)
- npm latest: **v20.0.19** (2026-07-27)
- The repo has migrated from `ryoppippi/ccusage` to **`ccusage/ccusage`** (17,727★, still updated daily)

### 4.2 v15.7.1 Does Have the Bug Described in 1.3

Controlled experiment (`CLAUDE_CONFIG_DIR` pointed at a fixture containing just 3 lines: `2/2/999`):

```
v15.7.1 → outputTokens = 2        # takes whichever is encountered first
reversed order 999/2/2 → outputTokens = 999 # confirms it's "take the first" not "take the min"
```

The dedup function `createUniqueHash = ${message.id}:${requestId}`, a global `Set`, checks before adding.

### 4.3 Upstream Has Already Fixed This, and the Fix Matches the Derivation in §1.3 of This Document

All related issues are closed:
[#705](https://github.com/ccusage/ccusage/issues/705), [#797](https://github.com/ccusage/ccusage/issues/797),
[#866](https://github.com/ccusage/ccusage/issues/866), [#888](https://github.com/ccusage/ccusage/issues/888),
[#901](https://github.com/ccusage/ccusage/issues/901), [#938](https://github.com/ccusage/ccusage/issues/938)
("First-wins dedup keeps partial streaming output_tokens"). Fixed in a batch on 2026-05-17.

The current `main` branch's `rust/adapters/claude/src/daily.rs`:

```rust
if candidate_total != existing_total {
    return candidate_total > existing_total;   // take the one with the larger total token count
}
```

### 4.4 v20 Reconciles Successfully Field-by-Field with This Document's Algorithm (Claude Side)

| date | v20 out | this doc's algorithm | v20 in | this doc | v20 cc | this doc cc_5m+cc_1h |
|---|---|---|---|---|---|---|
| 08-02 | 220,300 | **220,300** ✓ | 370 | **370** ✓ | 1,454,521 | 348,206+1,106,315 = **1,454,521** ✓ |
| 08-03 | 237,117 | **237,117** ✓ | 375 | **375** ✓ | 1,586,700 | 169,846+1,416,854 = **1,586,700** ✓ |
| 08-04 | 776,447 | **776,447** ✓ | 22,160 | **22,160** ✓ | 2,829,605 | 1,864,996+964,609 = **2,829,605** ✓ |

**Claude side: upgrading to v20 is sufficient; no need to write a custom parser.**

### 4.5 v20 Is a Different Product

`daily` now aggregates **all detected coding CLIs**, and has independent subcommands:
`claude` / `codex` / `opencode` / `amp` / `droid` / `codebuff` / `hermes` / `pi` / `goose` / `kilo` / `copilot` / `gemini` / `kimi` / `qwen` / `openclaw`

That is, it **natively supports both Claude and Codex simultaneously**, exactly what this project needs.

### 4.6 ⚠️ Unresolved: Codex-Side v20 Differs from This Document's Algorithm by 31%

```
ccusage v20:                          201 days   out = 36,945,083
this doc's algorithm, live only:      196 days   out = 44,998,756
this doc's algorithm, live+archived:  201 days   out = 53,206,631
```

ccusage's day count matches live+archived (indicating it reads the archive), but its output is **31% lower** than this document's algorithm — even lower than the live-only scan number.

**Explanations already ruled out**:
- Archive directory — day counts match, so it is being read
- originator filtering — even after excluding all `*vscode*`, still 50.4M, far from 36.9M
- Intra-day drift — 08-04 is a fully-elapsed day, and it still differs by 52,645

**Self-consistency evidence for this document's algorithm**: within a single file, `sum(last.output)` exactly equals `final total.output`.

**Which one is correct is unknown.** Resolving this requires reading ccusage v20's Rust Codex adapter source code. Until then, Codex-side numbers **should not be treated as settled**.

### 4.7 Other Defects in v15.7.1 (relevant only if insisting on the old version)

- `--offline`'s built-in price table only goes up to `claude-4-opus-20250514`, not including opus-5 → `totalCost: 0`
- By default, every run downloads the 1.67MB LiteLLM price table over the network, **with no disk cache**
- **Silent degradation on network failure**: in JSON mode, `logger.level=0` swallows the warning → stdout is valid JSON, cost=0, exit 0, stderr empty
- `--since/--until` filters only **after** aggregation — saving no I/O at all (full run 5.10s vs single-day 5.01s)
- `ccusage session` is broken under the current directory layout (it parses `sessionId` as `"subagents"` and the project name)
- Ignores the surcharge on `cache_creation.ephemeral_1h_input_tokens` (LiteLLM has `cache_creation_input_token_cost_above_1hr`)

### 4.8 Stability (measured on v15.7.1, not re-tested on v20)

- **Fully-elapsed days: byte-identical**, regardless of the `--since` window
- **The current day keeps growing**: `out` went from 268,505 → 268,542 within a few minutes
  → **idempotency can only overwrite by date, not append**
- Floating-point summation order is unstable: `61.86139775000001` vs `61.861397750000066` (difference ~1e-13)
  → **rounding must be applied to the value itself as it's written to disk**, not just done transiently when comparing/hashing

---

## 5. Not Yet Answered

1. **The Codex-side 31% discrepancy** (4.6) — requires reading ccusage v20's Rust Codex adapter source code
2. Whether v20 still has the network-failure silent cost=0 problem from 4.7
3. Whether v20's `--since` still saves no I/O
4. How to handle the `<synthetic>` model (v15 excludes it from the breakdown but still counts it in totals, causing the two to not reconcile)
5. Whether Codex runs on the ChatGPT subscription or API billing — whether the "cost" dimension is even meaningful
</content>
