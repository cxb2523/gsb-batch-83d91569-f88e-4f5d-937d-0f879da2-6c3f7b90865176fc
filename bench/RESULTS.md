# Measured against WebFetch

On a 30-question web-documentation suite asked in Korean and in English with the page URL given, jevfetch's mean agent-run duration was 47% shorter than WebFetch's in both languages. Observed mean cost was 7% lower in Korean and 3% lower in English, and both 95% intervals include no difference. WebFetch matched all 116 rubric fact checks in each language; jevfetch matched 115 in Korean and 116 in English (58 rubric items over two repetitions; jevfetch 488ed63, Claude Code 2.1.309 with Sonnet 5.5 and WebFetch's reader model Haiku 5.5, Jev jev-1.14.0, the two arms interleaved in random order and run one at a time, 2026-10-23).

The agent had no web search. Reports: [Korean](reports/agents-2026-10-23-2arm-ko/report.md), [English](reports/agents-2026-10-23-2arm-en/report.md). The 30 questions are on 21 pages:

| question language | reader | rubric fact checks matched (of 116) | mean cost per question | of which main model | of which reader model or Jev | main-model input / output tokens | mean turns | `curl` calls (runs) | median time | mean time |
|---|---|---|---|---|---|---|---|---|---|---|
| Korean | WebFetch | 116 | $0.033 | $0.029 | $0.005 | 16,777 / 1,411 | 2.47 | 20 (9 of 60) | 22.4 s | 24.3 s |
| Korean | jevfetch | 115 | $0.031 | $0.025 | $0.006 | 14,001 / 1,106 | 2.02 | 0 | 12.6 s | 12.9 s |
| English | WebFetch | 116 | $0.027 | $0.022 | $0.005 | 17,888 / 949 | 2.70 | 32 (13 of 60) | 18.3 s | 19.7 s |
| English | jevfetch | 116 | $0.026 | $0.020 | $0.006 | 13,925 / 691 | 2.02 | 0 | 9.7 s | 10.5 s |

Paired over questions (95% bootstrap intervals that resample questions), jevfetch against WebFetch: cost 0.93 (0.81 to 1.06) in Korean and 0.97 (0.83 to 1.13) in English; mean time 0.53 (0.48 to 0.59) and 0.53 (0.47 to 0.63). jevfetch's one miss was one of three facts in one of the two Korean runs of the Cloud Storage lifecycle question. Cost and time cover each run up to its final answer, including the turns in which a WebFetch agent went back to the page with `curl`. Cost includes Jev for jevfetch and every Haiku call for WebFetch. `curl` calls count the commands the agent attempted, including refused ones.

By page size (extracted tokens), cost and median time as WebFetch / jevfetch:

| pages | questions | Korean: cost | Korean: median time | English: cost | English: median time |
|---|---|---|---|---|---|
| small, under 5,000 | 5 | $0.024 / $0.022 | 15.8 s / 10.8 s | $0.023 / $0.017 | 16.6 s / 8.2 s |
| medium, under 20,000 | 16 | $0.036 / $0.029 | 27.0 s / 13.1 s | $0.027 / $0.024 | 21.2 s / 10.1 s |
| large, 33,000 to 101,000 | 9 | $0.033 / $0.040 | 20.8 s / 13.0 s | $0.028 / $0.034 | 16.6 s / 9.7 s |

Fact checks matched by size, WebFetch / jevfetch: medium 74/74 / 73/74 in Korean; every other cell matched all (small 24/24, medium 74/74 in English, large 18/18).

Paired cost ratios jevfetch / WebFetch: small 0.90 (0.82 to 0.99) Korean and 0.74 (0.50 to 1.04) English; medium 0.79 (0.70 to 0.91) and 0.90 (0.79 to 1.03); large 1.19 (0.92 to 1.54) and 1.21 (0.89 to 1.60). Mean-time ratios are between 0.48 and 0.62 in every cell. On the large pages (nine questions on three pages) jevfetch's mean cost was above WebFetch's, with intervals that include 1: Jev's cost scales with page length (about $0.022 per call on the 101,000-token RFC 9110), while WebFetch's model pass stays cheap even when the agent calls it again with an offset (1.3 to 1.4 calls and 3.2 to 3.3 turns per run there). Duration was still shorter, and both found every fact there.

Earlier measurements:

- WebFetch with Haiku 4.5 as its reader, set with `ANTHROPIC_SMALL_FAST_MODEL` (2026-10-09, Claude Code 2.1.295, the same 30 questions; reports: [Korean](reports/agents-2026-10-09-3arm-ko/report.md), [English](reports/agents-2026-10-09-3arm-en/report.md), which also list two questions no longer in the set). Against it jevfetch's cost ratio was 0.56 (0.48 to 0.66) in Korean and 0.57 (0.49 to 0.68) in English and its mean-time ratio 0.66 (0.59 to 0.73) and 0.68 (0.61 to 0.76). Its summaries matched 114 of 116 fact checks in Korean and 116 in English.
- At the tool level on 27 English questions, three runs each (2026-10-09, Claude Code 2.1.294), jevfetch returned the reference sentences verbatim in 81 of 81 outputs against 25 of 81 for a single WebFetch call ([tool comparison](reports/webfetch-2026-10-09.md)).

What these numbers are, and are not:

- A pilot on a small corpus: 30 questions on 21 pages. Intervals resample questions only, so they do not cover run-to-run or API-condition variation.
- Rubric scores measure whether required content is present, not whether the whole answer is correct. 116 is 58 rubric items checked over two repetitions.
- Both agents received instructions of the same shape, so the comparison is between each reader as configured, instructions included.
- Time is the duration Claude Code reports for the whole agent task, not the tool call alone; it leaves out process start and exit. By subprocess wall clock, jevfetch's mean-time ratio to WebFetch is 0.56 in both languages.
- Bash allow rules named `curl`, `grep` and `head`. One of the 60 Korean WebFetch runs had a command refused, and in each language 3 of the 60 WebFetch runs had a `grep` pattern rejected by the machine's `grep` (ugrep); no jevfetch run had either. Those turns stay in the measured runs.
- Costs are as billed, prompt caching included. The page bytes fetched and the Jev request bodies were not archived, so a run's reader inputs cannot be replayed exactly.

## WebCode Highlights

Exa's WebCode benchmark ([exa-labs/benchmarks](https://github.com/exa-labs/benchmarks), MIT) pairs coding questions with the page that answers them. We used its Highlights set with search held fixed: each reader got the item's URL and question. Of the 250 items, 137 were kept, those whose citation excerpt was on the page as fetched (in jevfetch's rendering or in the raw HTML); the other 113 were left out, 24 of them because the site refused the fetch.

At the agent level ([report](reports/webcode-2026-10-26/report.md); Claude Code 2.1.310, Sonnet 5.5 main model, WebFetch's reader Haiku 5.5, Jev `jev-1.14.0`; English questions, the URL given and no web search, one run per question, run one at a time). The WebFetch runs are from 2026-10-25 and the jevfetch runs from 2026-10-26: when jevfetch's selection changed, only its 137 runs were made again, since the WebFetch runs do not use jevfetch.

| reader | answers graded correct | under the original grading | mean cost per question | of which main model | of which reader model or Jev | main-model input tokens | median time |
|---|---|---|---|---|---|---|---|
| WebFetch, Haiku 5.5 (2026-10-25) | 132 of 137 | 126 | $0.0149 | $0.0131 | $0.0018 | 9,447 | 12.1 s |
| jevfetch (2026-10-26) | 137 of 137 | 136 | $0.0180 | $0.0168 | $0.0011 | 12,647 | 8.1 s |

Paired over the 137 questions (one run each, Claude Code 2.1.310; 95% bootstrap intervals that resample questions), jevfetch's runs of 2026-10-26 against WebFetch's of 2026-10-25: mean time 0.69 (0.66 to 0.72), cost 1.20 (1.13 to 1.28), and under the original grading +0.07 answers right per question (+0.03 to +0.12). The two readers ran a day apart, so the time ratio also carries any change in API latency between the two sessions. The cost difference is the main model reading jevfetch's verbatim output, which is longer than WebFetch's summary; Jev itself averaged $0.0011 per question over the 137 jevfetch runs of 2026-10-26.

The original grading, in the report, asks a Sonnet judge whether the answer states the whole expected answer, and Highlights' expected answers often explain more than their question asks: an answer naming the right flag failed for leaving out why. `bench/webcode.py regrade` asked again whether each answer gives what the question asks, three votes per answer, without telling the judge which reader's agent wrote it, though 24 of the 274 answers name WebFetch or jevfetch in their own text ([summary](reports/webcode-2026-10-26/regrade.txt)). Every vote was unanimous. Of the 274 answers (137 per reader, Claude Code 2.1.310), seven verdicts went from wrong to right, six WebFetch answers of 2026-10-25 and one jevfetch answer of 2026-10-26, and none the other way; all seven were read by hand and answer the question. The five WebFetch answers still wrong are four pages that returned HTTP 403 or 503 to WebFetch and one where it received only the site's navigation and footer; these were read by hand too.

At the tool level ([summary](reports/webcode-2026-10-26/tools.txt); Jev `jev-1.14.0`, WebFetch through Claude Code 2.1.310), on the 133 items whose page every reader fetched, the same kind of judge found the information needed for the expected answer in 133 jevfetch outputs of 2026-10-26, and in 120 single WebFetch calls and 123 WebFetch calls with continuation windows of 2026-10-25. Of those 133, jevfetch's output held the citation excerpt verbatim in 121, WebFetch's in 10 and 10. On the same 133 items, tool time summed to 124 s for jevfetch (2026-10-26) and 420 s and 453 s for WebFetch (2026-10-25).

What these numbers are, and are not:

- One run per question, in English, on coding and developer-documentation pages. Intervals resample questions only.
- Items were kept by whether the excerpt was on the page as fetched, so pages that refused every fetch, or no longer held the excerpt, are not in the 137.
- Pages were fetched live during each run, and the page bytes were not archived. jevfetch and WebFetch fetched each page at different times (a day apart at the agent level, about 90 minutes apart at the tool level), so a page that changed in between is not compared on the same bytes.
- The jevfetch measured here is the one [How it works](../README.md#how-it-works) describes, with candidate threshold 0.6. One item (`highlights_215`) has its answer only in a note written as `<aside>`.

How it is measured: [bench/README.md](README.md).
