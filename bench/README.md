# bench

Regression benchmark for jevfetch's selection quality, output size, and Jev cost, plus two manual
comparisons with Claude Code's WebFetch.

## Run

```bash
uv run python -m bench                     # replay recorded Jev responses, compare with baseline.json (CI)
uv run python -m bench --record            # call Jev for requests without a recording (needs TYPESAFE_API_KEY)
uv run python -m bench --update-baseline   # write baseline.json after printing the per-case diff
uv run python -m bench --cases ID,ID       # a subset; compared with the matching part of the baseline
uv run python -m bench --set keep_threshold=0.9 --set min_output_tokens=0   # Config overrides for experiments
uv run python -m bench --record --update-baseline --prune   # after a change to the Jev requests: record, rebaseline, drop stale recordings
uv run python bench/compare_webfetch.py --runs 3   # live comparison with WebFetch, needs `claude` and both keys
```

Replay needs no key and takes about 7 seconds; the only network use is tiktoken's one-time encoding download. The runner removes `TYPESAFE_API_KEY`
from its own environment, so a request without a recording fails with a "missing recording" message
instead of calling the API.

## What is measured

Each case is a (page snapshot, question) pair with `facts` (sentences copied from the page) and
`keys` (short values any correct answer contains, with aliases). Per case:

| column | meaning |
|---|---|
| status | `Result.status`; must equal the case's expected status |
| facts | facts found verbatim in the output (heading lines excluded, markdown emphasis and `[text](url)` link markup stripped, punctuation kept) |
| keys | key groups found as whole-token sequences after SQuAD normalization; `exact` keys keep punctuation |
| extract | facts still present after `parse()` and `render()` of the whole page, before any Jev call |
| out/doc tok | output tokens / page tokens (cl100k_base) |
| workload | Jev input tokens, live plus replayed (`jev_input_tokens + jev_cached_input_tokens`) |
| pos | where the facts sit in the page text: start / middle / end third |

The summary line adds pooled retention (facts passed / facts total), case-mean and page-mean
retention, status matches, totals, and the cost estimate at $0.042 per million Jev input tokens
(TypeSafe list price read on 2026-10-08; output tokens are free).

Not measured: whether a retained fact is the complete answer, and block-level precision. Noise is
controlled by the output-token ceilings below.

## Gate

The run fails when, compared with `baseline.json`:

- a fact or key that passed in the baseline now fails, or is missing from the case;
- the status differs from the case's expected status;
- a fact that survived extraction in the baseline no longer does;
- the sum of output tokens or of Jev workload over the cases present in both runs exceeds 110% of
  the baseline sum (new cases are reported separately);
- one case's output tokens or workload exceeds 150% of its baseline value;
- a case present in the baseline is missing;
- a case's question or snapshot hash changed and `--update-baseline` was not given;
- the resolved Jev model differs from the baseline's, or a request has no recording.

Improvements are printed and pass. With `--update-baseline` only model and recording problems block;
regressions are printed as notes and the new numbers become the baseline, so review the diff of
`baseline.json` in the PR. The 110% and 150% limits are policy.

## When recordings go stale

Jev responses are stored in `bench/jev/<sha1>.json`, keyed by the full request body: query, block
texts, heading paths, prompt wording, model name. Any change to extraction, windowing, the stage-1
prompt, or `candidate_threshold` in a way that adds candidates changes requests, and replay then
fails with the missing-recording message. Run `--record` locally with a key and commit the new
files (about $0.17 and 30 seconds for the whole set from an empty cache). Changes that only use the
scores differently (`keep_threshold`, `neighbor_threshold`, `min_output_tokens`, block 0 retention, rendering) replay
without re-recording.

The model name is pinned to the resolved version in `baseline.json` (`jev-1.13.0`), never the
`jev-latest` alias; `--record` reads it from the baseline, else from an existing recording, else
from one live request. Re-recording with a new model version therefore needs an explicit
rebaseline.

Measured stability (cache disabled, 3 repeats): identical requests move by at most 0.07
in stage 1 and 0.07 in stage 2, so a block scored between about 0.75 and 0.85 can cross the 0.8
threshold on re-recording. Check such cases by hand before accepting a changed baseline.

## Adding a case

1. Pick a page from `pages/SOURCES.md` or add one (redistributable terms only; record URL, date,
   license and notice there). Snapshots are gzipped; the loader also reads plain files.
2. Write the question from the page's headings or from a real agent question, not from body text.
3. Copy `facts` from the page. For a table row use an ordered span list. Add `keys` with aliases for
   the literal form on the page (`86400s`, `https://...`).
4. For a negative, set `answerable: false`, `negative_kind`, `status: "no_match"`, empty `facts` and
   `keys`, and use a page over 2,000 tokens (shorter pages are always `passthrough`). Read the whole
   page first to confirm it does not answer the question.
5. Run `--record`, then `--update-baseline`, then a plain run; commit `cases.json`, `jev/`, `baseline.json`.

## WebFetch comparison

`compare_webfetch.py` runs each case against the live URL with both tools and writes
`reports/webfetch-<date>.md`; the per-run JSON and the raw `claude -p` traces under `reports/raw/` stay local.
It needs the `claude` CLI (2.1.290 or later, so truncation is reported rather than silent),
`TYPESAFE_API_KEY`, and a Claude account. WebFetch is driven with user settings, plugins, MCP servers
and skills disabled and the tool's URL cache off; the orchestrator is Sonnet so that the tool's own
Haiku usage is separable. Each call's tool arguments are checked; a run whose arguments or call
count differ is counted as invalid, not dropped.

WebFetch asks for `text/markdown`; a site that serves it (redis.io, docs.stripe.com) gets its whole page passed
through unprocessed, with no model call. The ten snapshot pages are all HTML, so the tool-level numbers
measure the model path only.

Protocols: "single call" (offset 0 only) and "continuation" (offsets 0, 100000, ... until the result
has no truncation note or five windows). Pages that fit one window reuse the single-call result.
Metrics per tool: key coverage, facts quoted verbatim, delivered tokens (full payload including
jevfetch's `# ` header lines and WebFetch's note), tool cost, tool seconds, invalid runs. The
whole-page row is the context-retention reference, not an answer.

Before publishing numbers: run with `--runs 3`, read each distinct output and label it correct,
incomplete or wrong in `reports/labels.json`, and quote the report header (date, versions, stale
count, denominators). The comparison is observational and limited to this corpus.

## Agent-level comparison

`bench/agents/` measures the real usage pattern: Claude Code answers a question by searching the web and reading
pages, once with WebFetch and once with jevfetch. It is manual and paid, like the WebFetch comparison above.

```bash
uv run python -m bench.agents run bench/reports/agents-<date> --reps 2 --concurrency 1 --seed 7 --with-url --lang ko --arms webfetch,jevfetch
uv run python -m bench.agents judge bench/reports/agents-<date>
uv run python -m bench.agents report bench/reports/agents-<date>
```

- Questions: `bench/agents/questions.json`, 30 in all, each with a Korean and an English wording. 18 Korean
  documentation questions (16 of the 18 pages are English; pages of 2,000 to 18,000 extracted tokens) plus 12 English
  questions promoted from the tool-level cases: 9 on long pages (RFC 9110, Wikipedia World War II, NIST SP 800-63B;
  33,000 to 101,000 tokens, past WebFetch's first 100,000-character window) and 3 on a medium page. The report
  groups results by page size (small < 5,000 tokens, medium < 20,000, large) and language; do not pool the
  two languages into one headline. A page for which WebFetch hands the agent the whole page without calling
  its reader model (some sites serve Markdown) does not measure WebFetch and is not used for a question.
- Arms: `claude -p --safe-mode --model sonnet`, 40 turns at most, 900 s timeout. WebFetch arm: WebSearch,
  WebFetch, and Bash limited to `curl`, `grep`, `head` (the fallback pipeline both instruction files describe),
  with `bench/agents/webfetch.md` as instructions. jevfetch arm: WebSearch, the same Bash commands plus
  `jevfetch` (this checkout's `.venv/bin`), with `skills/jevfetch/SKILL.md` as instructions. The instructions
  are the shipped skill versus a WebFetch guide of the same shape; the skill's "no need to fetch the page again
  to check a quote" sentence is part of the product and stays. Each run's `meta.json` records the instruction
  file and its hash, the tool list and the allow rules; the report header prints them. Arm order is random
  within each (question, repetition) block.
- Grading: the rubric in `bench/agents/rubric.py`; `re` and `near` elements are checked by regex, `judge`
  elements by a Sonnet judge that sees the answer with reader names redacted, three votes, majority. A fact
  counts only when all its required elements hold. Non-unanimous votes are listed in the report for a human
  to check before anything is published.
- Cost: the run's `total_cost_usd` (Sonnet plus every Haiku call: WebFetch, WebSearch, Claude Code's own
  background calls) plus the Jev tokens actually sent in that run, read from the run's own `JEVFETCH_CACHE_DIR`
  (one recording per request). Time: the run's `duration_ms`.
- Failures: an API error is retried once and both traces are kept, the failed attempt's cost is reported
  separately; reaching the turn limit counts as a finished run with no answer; a timeout counts as unfinished.
  Unfinished runs score zero facts and are left out of cost and time means. The header also counts runs in which
  a Bash command was refused by the allow rules or by Claude Code's variable check, since a refusal costs the
  agent a turn. The allow rules name `curl`, `grep` and `head`, but a pipeline that starts with an allowed
  command may contain other commands (`sed`, `cut`); the rules describe the permission prompt, not a strict
  boundary of what ran. `grep` on the machine that produced the published sets was ugrep 7.8, which rejected
  some of the agents' patterns as too complex; those failures stay in the measured runs.
- Time: the run's `duration_ms` as Claude Code reports it, which leaves out the process start and exit; the
  harness also records the subprocess wall time (`wall_seconds`) in `meta.json`. The report shows the median
  and the mean; the paired ratio is over means. The time note states the concurrency the runs were executed at;
  only concurrency 1 measures single-session latency.
- Uncertainty: paired per question, 95% bootstrap intervals that resample questions (the cluster). Two
  repetitions of 30 questions on 21 pages (the nine large-page questions sit on three pages) give wide
  intervals, and resampling questions does not cover run-to-run or API-condition variation; the report wording
  states the interval.

`--lang ko|en` picks the question's Korean or English wording (`query_ko` / `query_en` in `questions.json`) and
the matching task prompt; every question exists in both languages, so language and page size can be read
separately. Results directories are per language (`agents-<date>-2arm-ko`, `agents-<date>-2arm-en`).

`--with-url` gives the agent the question's page URL in the prompt and removes WebSearch from both arms, so
only the two readers (and `curl` as their fallback) differ; this isolates the reader from the search behaviour
of the model. Without it the agent searches, which is the deployed usage pattern. Each run's `meta.json` and
the report header record the mode.

The third arm `webfetch-haiku45` is the WebFetch arm with `ANTHROPIC_SMALL_FAST_MODEL=claude-haiku-4-5-20251001`,
the reader model WebFetch used before Haiku 5.5; run `--arms webfetch,webfetch-haiku45,jevfetch` to compare the
three in one interleaved schedule (block order and arm order are both random). `--small-model` sets the same
variable for every arm that does not pin its own. The model actually billed is in the report header.

Each run's `meta.json` records the exact task prompt, the instruction file and its hash computed before the
run, tools, allow rules, language, mode and small model; a finished run is reused only when all of these
match, otherwise the runner stops and asks for a fresh results directory. `runs.json` (local, not committed)
keeps the final answer and the judge votes of every run, so the answers and their grades can be checked without
the traces; the runs themselves cannot be re-executed from the committed files. Not archived: the page bytes each run fetched and the
request bodies sent to Jev (the recordings hold the responses and usage, keyed by a hash of the request), so a
run's reader inputs cannot be replayed exactly.

For latency, run with `--concurrency 1`; durations measured at higher concurrency are labelled as such.

`python -m bench.agents compare DIR:arm DIR:arm ...` pairs the finished runs of several result sets by
question (the first set is the reference) and prints facts, mean cost, median time and the paired ratios,
for example WebFetch with Haiku 4.5 against WebFetch with Haiku 5.5 against jevfetch.

`--arms webfetch --webfetch-instructions bench/agents/webfetch-minimal.md` runs one arm with another
instruction file; `webfetch-minimal.md` is a one-sentence instruction, used to measure
how much of a cost difference comes from instructions rather than from the reader.

## WebCode Highlights

`webcode.py` compares the readers on Exa's WebCode Highlights items ([exa-labs/benchmarks](https://github.com/exa-labs/benchmarks),
MIT; notice in `webcode-highlights/LICENSE`) with search held fixed: every reader gets the item's URL and question.
`webcode-highlights/` holds the 137 items behind the published figures (`items.json`), and the question file and
rubric that `bench.agents` takes for them. An item was kept when its citation excerpt was on the page as fetched,
in jevfetch's rendering or in the raw HTML; `webcode.py convert` makes these files from the dataset and those two
checks, which are not part of this repository. Like the comparisons above, this is a manual, paid run.

```bash
R=bench/reports/webcode-<date>
I=bench/webcode-highlights
uv run python bench/webcode.py tools $R/tools --items $I/items.json --thresholds 0.6
uv run python bench/webcode.py judge $R/tools --items $I/items.json
uv run python bench/webcode.py summary $R/tools
A=(--questions $I/questions.json --rubric $I/rubric.json --arms webfetch-only,jevfetch-only)
uv run python -m bench.agents run $R/agents "${A[@]}" --reps 1 --concurrency 1 --seed 7 --with-url --lang en
uv run python -m bench.agents judge $R/agents "${A[@]}"
uv run python -m bench.agents report $R/agents "${A[@]}" --seed 0
uv run python bench/webcode.py regrade $R/agents --items $I/items.json
```

- `tools` runs WebFetch through `claude -p`, once and with continuation windows as in the WebFetch comparison, and
  jevfetch at each candidate threshold given. `judge` asks a Sonnet judge whether each returned text holds the
  information for the expected answer: one vote per distinct text, two more for every text of an item whose texts
  got different first votes. A refused fetch, an HTTP error page, or a block page counts as a failed fetch.
- The agent arms `webfetch-only` and `jevfetch-only` allow nothing but the reader (no `curl`, no WebSearch with
  `--with-url`), so the reader is the only difference. `--questions` and `--rubric` point `bench.agents` at these
  files instead of its own 30 questions.
- The rubric holds each item's whole expected answer, and the expected answers often explain more than their
  question asks, so the rubric judge fails answers that leave that out. `regrade` asks a Sonnet judge, three votes
  per answer and without saying which arm wrote it, whether the answer gives what the question asks. Read every
  verdict that changes, and every answer still judged wrong, before publishing.
- Committed per run, at the top of `reports/webcode-<date>/`: `report.md` from `bench.agents report`, `tools.txt`
  from `summary`, and `regrade.txt` from `regrade`. Rows, judge votes, traces and the pages fetched stay local.

Only `report.md` of a results directory is committed; `runs.json` (answers, costs, judge votes),
`schedule.json`, traces, work directories, Jev recordings of the runs and the judge's raw replies stay local. The published numbers, and the reports they come from, are in `RESULTS.md`.
