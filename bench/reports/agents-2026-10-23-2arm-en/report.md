# Agent-level comparison, 2026-10-23

- Claude Code `claude --version`: 2.1.309 (Claude Code); versions seen in traces: 2.1.309; orchestrator model: sonnet; models billed: claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.14.0
- jevfetch revision 488ed63; instruction sha1 recorded at run time: webfetch ['fc609d4f0c'], jevfetch ['f408570833']; allowed tools: webfetch ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; jevfetch ['Bash(curl:*) Bash(grep:*) Bash(head:*) Bash(jevfetch:*)']
- mode: URL given, no WebSearch; question language: en; small model override: None
- questions: 30; runs per arm: webfetch 60, jevfetch 60; schedule seed 7; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check), jevfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch | 116/116 | 60/60 | 0.0267 | 0.0221 | 0.0046 | 0.0000 | 18.3 | 19.7 | 2.70 | 17888 | 949 | 1.20 | 32 (13) | 0 |
| jevfetch | 116/116 | 60/60 | 0.0260 | 0.0204 | 0.0000 | 0.0056 | 9.7 | 10.5 | 2.02 | 13925 | 691 | 1.02 | 0 (0) | 0 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch, cost ratio: 0.97 (interval 0.83 to 1.13), i.e. 3% lower; 30 questions
- vs webfetch, mean-time ratio: 0.53 (interval 0.47 to 0.63); runs were executed one at a time (concurrency 1)
- vs webfetch, facts right per run, difference: +0.00 (interval +0.00 to +0.00)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | en | 9 | webfetch | 18/18 | 0.0280 | 0.0211 | 0.0068 | 0.0000 | 16.6 | 3.33 | 21174 | 850 | 1.44 | 17 (8) |  |  |
| large | en | 9 | jevfetch | 18/18 | 0.0338 | 0.0209 | 0.0000 | 0.0129 | 9.7 | 2.06 | 14444 | 642 | 1.06 | 0 (0) | 1.21 (0.89 to 1.60) | 0.61 (0.41 to 0.93) |
| medium | en | 16 | webfetch | 74/74 | 0.0272 | 0.0227 | 0.0044 | 0.0000 | 21.2 | 2.25 | 15092 | 1034 | 1.12 | 4 (3) |  |  |
| medium | en | 16 | jevfetch | 74/74 | 0.0244 | 0.0214 | 0.0000 | 0.0030 | 10.1 | 2.00 | 13889 | 762 | 1.00 | 0 (0) | 0.90 (0.79 to 1.03) | 0.50 (0.45 to 0.55) |
| small | en | 5 | webfetch | 24/24 | 0.0229 | 0.0215 | 0.0014 | 0.0000 | 16.6 | 3.00 | 20921 | 855 | 1.00 | 11 (2) |  |  |
| small | en | 5 | jevfetch | 24/24 | 0.0169 | 0.0161 | 0.0000 | 0.0008 | 8.2 | 2.00 | 13106 | 551 | 1.00 | 0 (0) | 0.74 (0.50 to 1.04) | 0.52 (0.38 to 0.71) |

## Judge votes that were not unanimous (0 of 64 judged runs; review by hand before publishing)

- none

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-cache | medium | en | jevfetch | 0 | yes | 4/4 | 0.0330 | 0.0032 | 12.9 | 2 | 14785 | 1 | 0 | 0 | 0 | c878a7f9042b |
| claude-cache | medium | en | webfetch | 0 | yes | 4/4 | 0.0409 | 0.0000 | 25.4 | 3 | 20640 | 0 | 2 | 0 | 0 | c1ff1ab9ca92 |
| claude-cache | medium | en | jevfetch | 1 | yes | 4/4 | 0.0289 | 0.0032 | 12.1 | 2 | 14646 | 1 | 0 | 0 | 0 | f965f1e3634c |
| claude-cache | medium | en | webfetch | 1 | yes | 4/4 | 0.0322 | 0.0000 | 23.6 | 3 | 20348 | 0 | 2 | 0 | 0 | 04de849ad85d |
| docker-swap | small | en | jevfetch | 0 | yes | 2/2 | 0.0168 | 0.0007 | 8.9 | 2 | 12855 | 1 | 0 | 0 | 0 | 639444517794 |
| docker-swap | small | en | webfetch | 0 | yes | 2/2 | 0.0156 | 0.0000 | 10.7 | 2 | 12392 | 0 | 1 | 0 | 0 | c6fa36cb3fa4 |
| docker-swap | small | en | jevfetch | 1 | yes | 2/2 | 0.0133 | 0.0006 | 7.4 | 2 | 12855 | 1 | 0 | 0 | 0 | 15ddada698bd |
| docker-swap | small | en | webfetch | 1 | yes | 2/2 | 0.0146 | 0.0000 | 15.8 | 2 | 12490 | 0 | 1 | 0 | 0 | 7e3996d20214 |
| gcs-lifecycle | medium | en | jevfetch | 0 | yes | 3/3 | 0.0255 | 0.0024 | 11.3 | 2 | 14557 | 1 | 0 | 0 | 0 | fb4e1932e2c8 |
| gcs-lifecycle | medium | en | webfetch | 0 | yes | 3/3 | 0.0220 | 0.0000 | 22.2 | 2 | 12995 | 0 | 1 | 0 | 0 | 66d06b61101e |
| gcs-lifecycle | medium | en | jevfetch | 1 | yes | 3/3 | 0.0325 | 0.0026 | 9.8 | 2 | 15863 | 1 | 0 | 0 | 0 | c5518d3bef6e |
| gcs-lifecycle | medium | en | webfetch | 1 | yes | 3/3 | 0.0229 | 0.0000 | 19.0 | 2 | 12792 | 0 | 1 | 0 | 0 | d90e88cfb455 |
| gdpr-fines | medium | en | jevfetch | 0 | yes | 2/2 | 0.0241 | 0.0018 | 9.5 | 2 | 13607 | 1 | 0 | 0 | 0 | b14b092379ac |
| gdpr-fines | medium | en | webfetch | 0 | yes | 2/2 | 0.0245 | 0.0000 | 15.1 | 2 | 12771 | 0 | 1 | 0 | 0 | 9ce9bba354f5 |
| gdpr-fines | medium | en | jevfetch | 1 | yes | 2/2 | 0.0210 | 0.0018 | 10.2 | 2 | 13623 | 1 | 0 | 0 | 0 | 2c7cbbc321a7 |
| gdpr-fines | medium | en | webfetch | 1 | yes | 2/2 | 0.0212 | 0.0000 | 16.0 | 2 | 12733 | 0 | 1 | 0 | 0 | 8cd3f4290603 |
| gh-limits | small | en | jevfetch | 0 | yes | 3/3 | 0.0182 | 0.0007 | 8.0 | 2 | 13025 | 1 | 0 | 0 | 0 | c898f4b9e775 |
| gh-limits | small | en | webfetch | 0 | yes | 3/3 | 0.0472 | 0.0000 | 24.9 | 7 | 55489 | 0 | 1 | 5 | 0 | 6e2677da22e0 |
| gh-limits | small | en | jevfetch | 1 | yes | 3/3 | 0.0161 | 0.0007 | 8.3 | 2 | 13021 | 1 | 0 | 0 | 0 | f87b85988fe6 |
| gh-limits | small | en | webfetch | 1 | yes | 3/3 | 0.0437 | 0.0000 | 26.7 | 7 | 52529 | 0 | 1 | 6 | 0 | 1e0b60592acf |
| gh-rest-rate | small | en | jevfetch | 0 | yes | 3/3 | 0.0161 | 0.0010 | 8.1 | 2 | 13097 | 1 | 0 | 0 | 0 | 6c11bd7ee000 |
| gh-rest-rate | small | en | webfetch | 0 | yes | 3/3 | 0.0180 | 0.0000 | 18.3 | 2 | 12825 | 0 | 1 | 0 | 0 | 4e34b99272cc |
| gh-rest-rate | small | en | jevfetch | 1 | yes | 3/3 | 0.0190 | 0.0010 | 8.0 | 2 | 13105 | 1 | 0 | 0 | 0 | 28e888d4ffd8 |
| gh-rest-rate | small | en | webfetch | 1 | yes | 3/3 | 0.0236 | 0.0000 | 19.3 | 2 | 12939 | 0 | 1 | 0 | 0 | fde712ecd2b6 |
| git-lease | medium | en | jevfetch | 0 | yes | 2/2 | 0.0215 | 0.0032 | 9.0 | 2 | 12988 | 1 | 0 | 0 | 0 | 57ebd346bf00 |
| git-lease | medium | en | webfetch | 0 | yes | 2/2 | 0.0322 | 0.0000 | 22.0 | 2 | 13637 | 0 | 1 | 0 | 0 | 702e4d440c02 |
| git-lease | medium | en | jevfetch | 1 | yes | 2/2 | 0.0181 | 0.0031 | 9.6 | 2 | 12988 | 1 | 0 | 0 | 0 | 327b2dcc4f50 |
| git-lease | medium | en | webfetch | 1 | yes | 2/2 | 0.0269 | 0.0000 | 21.1 | 2 | 13561 | 0 | 1 | 0 | 0 | 72a14e5be041 |
| http-415-meaning | large | en | jevfetch | 0 | yes | 1/1 | 0.0443 | 0.0223 | 11.9 | 2 | 13338 | 1 | 0 | 0 | 0 | a899d30013cc |
| http-415-meaning | large | en | webfetch | 0 | yes | 1/1 | 0.0278 | 0.0000 | 16.5 | 4 | 27385 | 0 | 1 | 2 | 0 | 256d17fa685c |
| http-415-meaning | large | en | jevfetch | 1 | yes | 1/1 | 0.0702 | 0.0451 | 17.7 | 3 | 21441 | 2 | 0 | 0 | 0 | 05e0462a7d45 |
| http-415-meaning | large | en | webfetch | 1 | yes | 1/1 | 0.0250 | 0.0000 | 15.6 | 4 | 26983 | 0 | 1 | 2 | 0 | d31b8e4bd0f4 |
| http-if-none-match-false | large | en | jevfetch | 0 | yes | 1/1 | 0.0371 | 0.0227 | 9.3 | 2 | 13066 | 1 | 0 | 0 | 0 | 32d6ed1265a6 |
| http-if-none-match-false | large | en | webfetch | 0 | yes | 1/1 | 0.0267 | 0.0000 | 17.7 | 4 | 27207 | 0 | 1 | 2 | 0 | d41ba66fc6a8 |
| http-if-none-match-false | large | en | jevfetch | 1 | yes | 1/1 | 0.0407 | 0.0228 | 9.5 | 2 | 13066 | 1 | 0 | 0 | 0 | e0290c638fcb |
| http-if-none-match-false | large | en | webfetch | 1 | yes | 1/1 | 0.0504 | 0.0000 | 26.4 | 7 | 43042 | 0 | 3 | 3 | 0 | 3962846076f3 |
| http-retry-after-values | large | en | jevfetch | 0 | yes | 1/1 | 0.0437 | 0.0225 | 9.5 | 2 | 14776 | 1 | 0 | 0 | 0 | 9d5852697d55 |
| http-retry-after-values | large | en | webfetch | 0 | yes | 1/1 | 0.0292 | 0.0000 | 15.1 | 4 | 28727 | 0 | 1 | 3 | 0 | 95fc216835e1 |
| http-retry-after-values | large | en | jevfetch | 1 | yes | 1/1 | 0.0500 | 0.0225 | 9.7 | 2 | 15211 | 1 | 0 | 0 | 0 | 696f86162b9c |
| http-retry-after-values | large | en | webfetch | 1 | yes | 1/1 | 0.0275 | 0.0000 | 16.6 | 4 | 26660 | 0 | 1 | 2 | 0 | afbbe920121e |
| k8s-termination | medium | en | jevfetch | 0 | yes | 3/3 | 0.0288 | 0.0027 | 12.3 | 2 | 14153 | 1 | 0 | 0 | 0 | 55e74e1d0b14 |
| k8s-termination | medium | en | webfetch | 0 | yes | 3/3 | 0.0406 | 0.0000 | 26.4 | 3 | 21045 | 0 | 2 | 0 | 0 | cd625175ab09 |
| k8s-termination | medium | en | jevfetch | 1 | yes | 3/3 | 0.0245 | 0.0028 | 9.5 | 2 | 14157 | 1 | 0 | 0 | 0 | 3cfe92355dd1 |
| k8s-termination | medium | en | webfetch | 1 | yes | 3/3 | 0.0379 | 0.0000 | 28.8 | 3 | 21493 | 0 | 2 | 0 | 0 | b890cdba34fe |
| ko-holiday | medium | en | jevfetch | 0 | yes | 1/1 | 0.0406 | 0.0013 | 11.7 | 2 | 18311 | 1 | 0 | 0 | 0 | 4899d5a4102e |
| ko-holiday | medium | en | webfetch | 0 | yes | 1/1 | 0.0266 | 0.0000 | 32.1 | 2 | 13035 | 0 | 1 | 0 | 0 | 582b007fb2a3 |
| ko-holiday | medium | en | jevfetch | 1 | yes | 1/1 | 0.0415 | 0.0013 | 11.0 | 2 | 17628 | 1 | 0 | 0 | 0 | a443bee0017c |
| ko-holiday | medium | en | webfetch | 1 | yes | 1/1 | 0.0259 | 0.0000 | 23.8 | 2 | 12749 | 0 | 1 | 0 | 0 | 1eb2ada89946 |
| ko-minwage | medium | en | jevfetch | 0 | yes | 4/4 | 0.0202 | 0.0017 | 12.2 | 2 | 12909 | 1 | 0 | 0 | 0 | ad524b35afb8 |
| ko-minwage | medium | en | webfetch | 0 | yes | 4/4 | 0.0200 | 0.0000 | 15.7 | 2 | 12539 | 0 | 1 | 0 | 0 | 926461ca864c |
| ko-minwage | medium | en | jevfetch | 1 | yes | 4/4 | 0.0183 | 0.0016 | 11.6 | 2 | 12913 | 1 | 0 | 0 | 0 | 8a0509c49586 |
| ko-minwage | medium | en | webfetch | 1 | yes | 4/4 | 0.0221 | 0.0000 | 15.8 | 3 | 19897 | 0 | 1 | 1 | 0 | bd3ce746f798 |
| mdn-keepalive | small | en | jevfetch | 0 | yes | 1/1 | 0.0187 | 0.0009 | 8.2 | 2 | 13410 | 1 | 0 | 0 | 0 | ea69645f9bf0 |
| mdn-keepalive | small | en | webfetch | 0 | yes | 1/1 | 0.0172 | 0.0000 | 11.7 | 2 | 12476 | 0 | 1 | 0 | 0 | 1a0ecd1fa1f7 |
| mdn-keepalive | small | en | jevfetch | 1 | yes | 1/1 | 0.0152 | 0.0009 | 7.9 | 2 | 13335 | 1 | 0 | 0 | 0 | 3ff93caff190 |
| mdn-keepalive | small | en | webfetch | 1 | yes | 1/1 | 0.0136 | 0.0000 | 10.3 | 2 | 12552 | 0 | 1 | 0 | 0 | c1c820b4d0d5 |
| nginx-read-timeout | medium | en | jevfetch | 0 | yes | 2/2 | 0.0244 | 0.0048 | 9.5 | 2 | 13748 | 1 | 0 | 0 | 0 | 0a3c40c0be73 |
| nginx-read-timeout | medium | en | webfetch | 0 | yes | 2/2 | 0.0182 | 0.0000 | 11.7 | 2 | 12517 | 0 | 1 | 0 | 0 | 7fc58e605d86 |
| nginx-read-timeout | medium | en | jevfetch | 1 | yes | 2/2 | 0.0201 | 0.0048 | 8.5 | 2 | 13719 | 1 | 0 | 0 | 0 | 9709b4b38bb7 |
| nginx-read-timeout | medium | en | webfetch | 1 | yes | 2/2 | 0.0140 | 0.0000 | 10.5 | 2 | 12425 | 0 | 1 | 0 | 0 | 97cbea42a46b |
| nist-aal2-reauthentication | large | en | jevfetch | 0 | yes | 1/1 | 0.0257 | 0.0067 | 9.5 | 2 | 13283 | 1 | 0 | 0 | 0 | f75d8c57059c |
| nist-aal2-reauthentication | large | en | webfetch | 0 | yes | 1/1 | 0.0220 | 0.0000 | 15.2 | 2 | 12511 | 0 | 1 | 0 | 0 | 9ccef52e5ac7 |
| nist-aal2-reauthentication | large | en | jevfetch | 1 | yes | 1/1 | 0.0231 | 0.0067 | 10.0 | 2 | 13293 | 1 | 0 | 0 | 0 | d08345e6bed7 |
| nist-aal2-reauthentication | large | en | webfetch | 1 | yes | 1/1 | 0.0226 | 0.0000 | 18.4 | 3 | 19640 | 0 | 1 | 1 | 0 | 758d5f15078a |
| nist-password-max-length | large | en | jevfetch | 0 | yes | 1/1 | 0.0274 | 0.0067 | 42.7 | 2 | 13719 | 1 | 0 | 0 | 0 | 03b36fb88778 |
| nist-password-max-length | large | en | webfetch | 0 | yes | 1/1 | 0.0211 | 0.0000 | 15.4 | 2 | 12622 | 0 | 1 | 0 | 0 | fad19a609410 |
| nist-password-max-length | large | en | jevfetch | 1 | yes | 1/1 | 0.0260 | 0.0067 | 10.0 | 2 | 13945 | 1 | 0 | 0 | 0 | f3a3a46791e6 |
| nist-password-max-length | large | en | webfetch | 1 | yes | 1/1 | 0.0182 | 0.0000 | 14.4 | 2 | 12712 | 0 | 1 | 0 | 0 | 83155d63598d |
| nist-password-min-length | large | en | jevfetch | 0 | yes | 1/1 | 0.0298 | 0.0067 | 9.6 | 2 | 14270 | 1 | 0 | 0 | 0 | d5fca190be0b |
| nist-password-min-length | large | en | webfetch | 0 | yes | 1/1 | 0.0243 | 0.0000 | 20.5 | 2 | 12940 | 0 | 1 | 0 | 0 | 24dae60719b5 |
| nist-password-min-length | large | en | jevfetch | 1 | yes | 1/1 | 0.0268 | 0.0067 | 11.2 | 2 | 14260 | 1 | 0 | 0 | 0 | 0ad2db8e98a2 |
| nist-password-min-length | large | en | webfetch | 1 | yes | 1/1 | 0.0209 | 0.0000 | 55.7 | 2 | 12842 | 0 | 1 | 0 | 0 | a5475441a8aa |
| npm-peer | medium | en | jevfetch | 0 | yes | 3/3 | 0.0183 | 0.0020 | 6.6 | 2 | 12870 | 1 | 0 | 0 | 0 | 446b788e4f6c |
| npm-peer | medium | en | webfetch | 0 | yes | 3/3 | 0.0174 | 0.0000 | 12.6 | 2 | 12409 | 0 | 1 | 0 | 0 | 47ab6a586355 |
| npm-peer | medium | en | jevfetch | 1 | yes | 3/3 | 0.0148 | 0.0020 | 7.4 | 2 | 12856 | 1 | 0 | 0 | 0 | 6de348c0b880 |
| npm-peer | medium | en | webfetch | 1 | yes | 3/3 | 0.0172 | 0.0000 | 15.3 | 2 | 12697 | 0 | 1 | 0 | 0 | 2d8470a57670 |
| pg-wraparound | medium | en | jevfetch | 0 | yes | 2/2 | 0.0228 | 0.0021 | 12.0 | 2 | 13246 | 1 | 0 | 0 | 0 | a04aaef87726 |
| pg-wraparound | medium | en | webfetch | 0 | yes | 2/2 | 0.0283 | 0.0000 | 21.9 | 2 | 13642 | 0 | 1 | 0 | 0 | 54069ec581f4 |
| pg-wraparound | medium | en | jevfetch | 1 | yes | 2/2 | 0.0199 | 0.0021 | 11.2 | 2 | 13318 | 1 | 0 | 0 | 0 | b0ac657787a1 |
| pg-wraparound | medium | en | webfetch | 1 | yes | 2/2 | 0.0257 | 0.0000 | 20.7 | 2 | 13582 | 0 | 1 | 0 | 0 | a9a7dc6344ba |
| py-subprocess | medium | en | jevfetch | 0 | yes | 2/2 | 0.0207 | 0.0038 | 9.9 | 2 | 13164 | 1 | 0 | 0 | 0 | 6e93bfa12153 |
| py-subprocess | medium | en | webfetch | 0 | yes | 2/2 | 0.0268 | 0.0000 | 20.7 | 2 | 13776 | 0 | 1 | 0 | 0 | cb66df92a49e |
| py-subprocess | medium | en | jevfetch | 1 | yes | 2/2 | 0.0249 | 0.0038 | 10.7 | 2 | 13162 | 1 | 0 | 0 | 0 | c20aab172f1c |
| py-subprocess | medium | en | webfetch | 1 | yes | 2/2 | 0.0314 | 0.0000 | 21.8 | 2 | 13784 | 0 | 1 | 0 | 0 | 80f55b815227 |
| rfc9111-heuristic | medium | en | jevfetch | 0 | yes | 4/4 | 0.0278 | 0.0052 | 11.2 | 2 | 13541 | 1 | 0 | 0 | 0 | b42623797e4a |
| rfc9111-heuristic | medium | en | webfetch | 0 | yes | 4/4 | 0.0425 | 0.0000 | 26.8 | 3 | 22578 | 0 | 1 | 1 | 0 | 45965f5be9be |
| rfc9111-heuristic | medium | en | jevfetch | 1 | yes | 4/4 | 0.0250 | 0.0052 | 12.3 | 2 | 13399 | 1 | 0 | 0 | 0 | 378789823092 |
| rfc9111-heuristic | medium | en | webfetch | 1 | yes | 4/4 | 0.0358 | 0.0000 | 27.2 | 4 | 29556 | 0 | 1 | 2 | 0 | 9b19ec45aa32 |
| sqlite-length | small | en | jevfetch | 0 | yes | 3/3 | 0.0164 | 0.0005 | 11.8 | 2 | 13180 | 1 | 0 | 0 | 0 | 5ce301e70836 |
| sqlite-length | small | en | webfetch | 0 | yes | 3/3 | 0.0161 | 0.0000 | 12.6 | 2 | 12702 | 0 | 1 | 0 | 0 | c59396b242e8 |
| sqlite-length | small | en | jevfetch | 1 | yes | 3/3 | 0.0194 | 0.0005 | 10.1 | 2 | 13178 | 1 | 0 | 0 | 0 | 14fa37949eb4 |
| sqlite-length | small | en | webfetch | 1 | yes | 3/3 | 0.0194 | 0.0000 | 17.5 | 2 | 12820 | 0 | 1 | 0 | 0 | c34aa338a383 |
| subprocess-communicate-timeout | medium | en | jevfetch | 0 | yes | 1/1 | 0.0195 | 0.0036 | 7.8 | 2 | 13106 | 1 | 0 | 0 | 0 | ac9214d3346e |
| subprocess-communicate-timeout | medium | en | webfetch | 0 | yes | 1/1 | 0.0213 | 0.0000 | 13.9 | 2 | 12962 | 0 | 1 | 0 | 0 | 153324041076 |
| subprocess-communicate-timeout | medium | en | jevfetch | 1 | yes | 1/1 | 0.0231 | 0.0035 | 9.2 | 2 | 13110 | 1 | 0 | 0 | 0 | 1fb48388ca41 |
| subprocess-communicate-timeout | medium | en | webfetch | 1 | yes | 1/1 | 0.0253 | 0.0000 | 16.2 | 2 | 13235 | 0 | 1 | 0 | 0 | 31ea2754ed12 |
| subprocess-run-timeout | medium | en | jevfetch | 0 | yes | 1/1 | 0.0184 | 0.0035 | 9.1 | 2 | 13093 | 1 | 0 | 0 | 0 | 15f89e977a8f |
| subprocess-run-timeout | medium | en | webfetch | 0 | yes | 1/1 | 0.0237 | 0.0000 | 19.0 | 2 | 13171 | 0 | 1 | 0 | 0 | 7e0b926ec0f7 |
| subprocess-run-timeout | medium | en | jevfetch | 1 | yes | 1/1 | 0.0214 | 0.0035 | 9.0 | 2 | 13095 | 1 | 0 | 0 | 0 | e48f7a477d8e |
| subprocess-run-timeout | medium | en | webfetch | 1 | yes | 1/1 | 0.0317 | 0.0000 | 25.1 | 2 | 13540 | 0 | 1 | 0 | 0 | 829e5d552609 |
| subprocess-shell-security | medium | en | jevfetch | 0 | yes | 1/1 | 0.0248 | 0.0044 | 10.3 | 2 | 13905 | 1 | 0 | 0 | 0 | 3bcf528d9de7 |
| subprocess-shell-security | medium | en | webfetch | 0 | yes | 1/1 | 0.0309 | 0.0000 | 25.1 | 2 | 13613 | 0 | 1 | 0 | 0 | 1a8789b26a04 |
| subprocess-shell-security | medium | en | jevfetch | 1 | yes | 1/1 | 0.0287 | 0.0043 | 10.9 | 2 | 13907 | 1 | 0 | 0 | 0 | 48b1b4522228 |
| subprocess-shell-security | medium | en | webfetch | 1 | yes | 1/1 | 0.0341 | 0.0000 | 26.0 | 2 | 13535 | 0 | 1 | 0 | 0 | e9989a7d7b4a |
| us-dst | medium | en | jevfetch | 0 | yes | 2/2 | 0.0217 | 0.0020 | 9.7 | 2 | 14048 | 1 | 0 | 0 | 0 | e4c0b01f49a3 |
| us-dst | medium | en | webfetch | 0 | yes | 2/2 | 0.0213 | 0.0000 | 17.7 | 2 | 12735 | 0 | 1 | 0 | 0 | 0eae421e9277 |
| us-dst | medium | en | jevfetch | 1 | yes | 2/2 | 0.0249 | 0.0020 | 9.5 | 2 | 14036 | 1 | 0 | 0 | 0 | 994f3912255c |
| us-dst | medium | en | webfetch | 1 | yes | 2/2 | 0.0274 | 0.0000 | 21.2 | 2 | 12967 | 0 | 1 | 0 | 0 | d09ab624e7b2 |
| ww2-death-toll | large | en | jevfetch | 0 | yes | 1/1 | 0.0275 | 0.0057 | 10.9 | 2 | 13501 | 1 | 0 | 0 | 0 | 1d3c3ad090ab |
| ww2-death-toll | large | en | webfetch | 0 | yes | 1/1 | 0.0464 | 0.0000 | 27.2 | 4 | 27279 | 0 | 3 | 0 | 0 | 63b75c47ad0a |
| ww2-death-toll | large | en | jevfetch | 1 | yes | 1/1 | 0.0240 | 0.0057 | 9.2 | 2 | 13511 | 1 | 0 | 0 | 0 | 14a7a25d892a |
| ww2-death-toll | large | en | webfetch | 1 | yes | 1/1 | 0.0396 | 0.0000 | 22.3 | 4 | 20016 | 0 | 3 | 0 | 0 | ec18c5002e8b |
| ww2-start-date | large | en | jevfetch | 0 | yes | 1/1 | 0.0385 | 0.0062 | 10.5 | 2 | 16760 | 1 | 0 | 0 | 0 | c023655ab290 |
| ww2-start-date | large | en | webfetch | 0 | yes | 1/1 | 0.0210 | 0.0000 | 10.3 | 2 | 12476 | 0 | 1 | 0 | 0 | 902cb633a6a7 |
| ww2-start-date | large | en | jevfetch | 1 | yes | 1/1 | 0.0353 | 0.0062 | 8.3 | 2 | 16752 | 1 | 0 | 0 | 0 | d66ea322c292 |
| ww2-start-date | large | en | webfetch | 1 | yes | 1/1 | 0.0189 | 0.0000 | 11.3 | 2 | 12522 | 0 | 1 | 0 | 0 | 84b86b06b52a |
| ww2-un-founded | large | en | jevfetch | 0 | yes | 1/1 | 0.0202 | 0.0053 | 7.2 | 2 | 12879 | 1 | 0 | 0 | 0 | 6a259aff02b8 |
| ww2-un-founded | large | en | webfetch | 0 | yes | 1/1 | 0.0381 | 0.0000 | 17.4 | 4 | 19477 | 0 | 3 | 0 | 0 | 2cbb0ec54979 |
| ww2-un-founded | large | en | jevfetch | 1 | yes | 1/1 | 0.0180 | 0.0053 | 9.1 | 2 | 12921 | 1 | 0 | 0 | 0 | 4014133aa78b |
| ww2-un-founded | large | en | webfetch | 1 | yes | 1/1 | 0.0243 | 0.0000 | 15.7 | 4 | 26092 | 0 | 1 | 2 | 0 | 63b4587c550b |

