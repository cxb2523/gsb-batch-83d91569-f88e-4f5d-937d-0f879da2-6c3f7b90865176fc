# Agent-level comparison, 2026-10-09

- Claude Code `claude --version`: 2.1.295 (Claude Code); versions seen in traces: 2.1.295; orchestrator model: sonnet; models billed: claude-haiku-4-5-20251001, claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.13.0
- jevfetch revision 8d38867; instruction sha1 recorded at run time: webfetch ['fc609d4f0c'], webfetch-haiku45 ['fc609d4f0c'], jevfetch ['569edd574c']; allowed tools: webfetch ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; webfetch-haiku45 ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; jevfetch ['Bash(curl:*) Bash(grep:*) Bash(head:*) Bash(jevfetch:*)']
- mode: URL given, no WebSearch; question language: ko; small model override: None, claude-haiku-4-5-20251001
- questions: 32; runs per arm: webfetch 64, webfetch-haiku45 64, jevfetch 64; schedule seed 7; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 5 runs with a Bash command refused (allow rules or variable check), webfetch-haiku45: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 3 runs with a Bash command refused (allow rules or variable check), jevfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch | 126/126 | 64/64 | 0.0376 | 0.0328 | 0.0048 | 0.0000 | 24.5 | 24.4 | 2.48 | 16987 | 1427 | 1.22 | 19 (9) | 5 |
| webfetch-haiku45 | 124/126 | 64/64 | 0.0574 | 0.0300 | 0.0274 | 0.0000 | 16.9 | 19.1 | 2.59 | 17434 | 1254 | 1.14 | 29 (13) | 3 |
| jevfetch | 124/126 | 64/64 | 0.0327 | 0.0269 | 0.0000 | 0.0058 | 12.6 | 13.0 | 2.03 | 13512 | 1110 | 1.03 | 0 (0) | 0 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch, cost ratio: 0.87 (interval 0.78 to 0.98), i.e. 13% lower; 32 questions
- vs webfetch, mean-time ratio: 0.53 (interval 0.48 to 0.59); runs were executed one at a time (concurrency 1)
- vs webfetch, facts right per run, difference: -0.03 (interval -0.09 to +0.00)
- vs webfetch-haiku45, cost ratio: 0.57 (interval 0.49 to 0.67), i.e. 43% lower; 32 questions
- vs webfetch-haiku45, mean-time ratio: 0.68 (interval 0.61 to 0.75); runs were executed one at a time (concurrency 1)
- vs webfetch-haiku45, facts right per run, difference: +0.00 (interval -0.08 to +0.06)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | ko | 9 | webfetch | 18/18 | 0.0399 | 0.0325 | 0.0074 | 0.0000 | 26.3 | 3.44 | 23257 | 1369 | 1.50 | 19 (9) |  |  |
| large | ko | 9 | webfetch-haiku45 | 18/18 | 0.0720 | 0.0306 | 0.0413 | 0.0000 | 17.8 | 3.50 | 23315 | 1263 | 1.28 | 24 (10) |  |  |
| large | ko | 9 | jevfetch | 18/18 | 0.0411 | 0.0266 | 0.0000 | 0.0146 | 12.7 | 2.11 | 14090 | 1027 | 1.11 | 0 (0) | 1.03 (0.80 to 1.29) vs webfetch; 0.57 (0.40 to 0.82) vs webfetch-haiku45 | 0.51 (0.44 to 0.60) vs webfetch; 0.69 (0.56 to 0.83) vs webfetch-haiku45 |
| medium | ko | 16 | webfetch | 76/76 | 0.0399 | 0.0352 | 0.0046 | 0.0000 | 24.7 | 2.16 | 15131 | 1568 | 1.16 | 0 (0) |  |  |
| medium | ko | 16 | webfetch-haiku45 | 75/76 | 0.0600 | 0.0320 | 0.0280 | 0.0000 | 17.2 | 2.34 | 16156 | 1350 | 1.12 | 5 (3) |  |  |
| medium | ko | 16 | jevfetch | 74/76 | 0.0308 | 0.0278 | 0.0000 | 0.0030 | 13.0 | 2.00 | 13363 | 1187 | 1.00 | 0 (0) | 0.77 (0.69 to 0.88) vs webfetch; 0.51 (0.46 to 0.58) vs webfetch-haiku45 | 0.51 (0.45 to 0.58) vs webfetch; 0.62 (0.54 to 0.73) vs webfetch-haiku45 |
| small | ko | 7 | webfetch | 32/32 | 0.0293 | 0.0276 | 0.0018 | 0.0000 | 16.9 | 2.00 | 13170 | 1179 | 1.00 | 0 (0) |  |  |
| small | ko | 7 | webfetch-haiku45 | 31/32 | 0.0325 | 0.0245 | 0.0081 | 0.0000 | 13.7 | 2.00 | 12795 | 1025 | 1.00 | 0 (0) |  |  |
| small | ko | 7 | jevfetch | 32/32 | 0.0262 | 0.0253 | 0.0000 | 0.0009 | 11.2 | 2.00 | 13110 | 1039 | 1.00 | 0 (0) | 0.89 (0.85 to 0.94) vs webfetch; 0.80 (0.75 to 0.86) vs webfetch-haiku45 | 0.63 (0.52 to 0.83) vs webfetch; 0.83 (0.72 to 0.98) vs webfetch-haiku45 |

## Judge votes that were not unanimous (0 of 102 judged runs; review by hand before publishing)

- none

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-cache | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0344 | 0.0023 | 16.0 | 2 | 13825 | 1 | 0 | 0 | 0 | 89ce82b14b35 |
| claude-cache | medium | ko | webfetch | 0 | yes | 4/4 | 0.0377 | 0.0000 | 20.7 | 3 | 19320 | 0 | 2 | 0 | 0 | e4780471cb6d |
| claude-cache | medium | ko | webfetch-haiku45 | 0 | yes | 4/4 | 0.0713 | 0.0000 | 30.2 | 3 | 20227 | 0 | 2 | 0 | 0 | b4ffcdae2727 |
| claude-cache | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0344 | 0.0024 | 13.7 | 2 | 13814 | 1 | 0 | 0 | 0 | 0a29995249fd |
| claude-cache | medium | ko | webfetch | 1 | yes | 4/4 | 0.0446 | 0.0000 | 27.6 | 3 | 20392 | 0 | 2 | 0 | 0 | 94518fc24646 |
| claude-cache | medium | ko | webfetch-haiku45 | 1 | yes | 4/4 | 0.0685 | 0.0000 | 27.4 | 3 | 20000 | 0 | 2 | 0 | 0 | 3eba88c28335 |
| docker-swap | small | ko | jevfetch | 0 | yes | 2/2 | 0.0232 | 0.0006 | 10.4 | 2 | 12417 | 1 | 0 | 0 | 0 | 30351b408895 |
| docker-swap | small | ko | webfetch | 0 | yes | 2/2 | 0.0287 | 0.0000 | 25.3 | 2 | 12729 | 0 | 1 | 0 | 0 | 8d64be37ffc4 |
| docker-swap | small | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0254 | 0.0000 | 14.1 | 2 | 12063 | 0 | 1 | 0 | 0 | 27b59423e887 |
| docker-swap | small | ko | jevfetch | 1 | yes | 2/2 | 0.0237 | 0.0006 | 14.6 | 2 | 12391 | 1 | 0 | 0 | 0 | f3cf7aa93c7d |
| docker-swap | small | ko | webfetch | 1 | yes | 2/2 | 0.0256 | 0.0000 | 18.4 | 2 | 12386 | 0 | 1 | 0 | 0 | 3b46e259ca21 |
| docker-swap | small | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0284 | 0.0000 | 14.5 | 2 | 12225 | 0 | 1 | 0 | 0 | 277b581d88ae |
| gcs-lifecycle | small | ko | jevfetch | 0 | yes | 3/3 | 0.0346 | 0.0024 | 13.3 | 2 | 14354 | 1 | 0 | 0 | 0 | cc05db781cc7 |
| gcs-lifecycle | small | ko | webfetch | 0 | yes | 3/3 | 0.0400 | 0.0000 | 29.0 | 2 | 13419 | 0 | 1 | 0 | 0 | c0ed0b6b8d0c |
| gcs-lifecycle | small | ko | webfetch-haiku45 | 0 | yes | 2/3 | 0.0410 | 0.0000 | 15.9 | 2 | 12426 | 0 | 1 | 0 | 0 | 3bc43846ce14 |
| gcs-lifecycle | small | ko | jevfetch | 1 | yes | 3/3 | 0.0305 | 0.0023 | 12.9 | 2 | 13686 | 1 | 0 | 0 | 0 | f199ae790d63 |
| gcs-lifecycle | small | ko | webfetch | 1 | yes | 3/3 | 0.0366 | 0.0000 | 32.1 | 2 | 13438 | 0 | 1 | 0 | 0 | 9f98879f6b23 |
| gcs-lifecycle | small | ko | webfetch-haiku45 | 1 | yes | 3/3 | 0.0430 | 0.0000 | 19.7 | 2 | 12428 | 0 | 1 | 0 | 0 | a6a89e0a4027 |
| gdpr-fines | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0292 | 0.0018 | 13.9 | 2 | 12995 | 1 | 0 | 0 | 0 | 06d6649b2c77 |
| gdpr-fines | medium | ko | webfetch | 0 | yes | 2/2 | 0.0510 | 0.0000 | 38.5 | 3 | 21099 | 0 | 2 | 0 | 0 | 8d66330881cc |
| gdpr-fines | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0546 | 0.0000 | 16.9 | 2 | 12276 | 0 | 1 | 0 | 0 | ef139d3dd4ef |
| gdpr-fines | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0293 | 0.0017 | 13.9 | 2 | 12992 | 1 | 0 | 0 | 0 | 70071a9cf76c |
| gdpr-fines | medium | ko | webfetch | 1 | yes | 2/2 | 0.0352 | 0.0000 | 27.0 | 2 | 12943 | 0 | 1 | 0 | 0 | d5e54ba56b48 |
| gdpr-fines | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0994 | 0.0000 | 23.0 | 3 | 19513 | 0 | 2 | 0 | 0 | e92aa2afeb67 |
| gh-limits | small | ko | jevfetch | 0 | yes | 3/3 | 0.0220 | 0.0006 | 10.5 | 2 | 12541 | 1 | 0 | 0 | 0 | 793f553ec8c7 |
| gh-limits | small | ko | webfetch | 0 | yes | 3/3 | 0.0271 | 0.0000 | 22.9 | 2 | 12757 | 0 | 1 | 0 | 0 | dee7cef6665e |
| gh-limits | small | ko | webfetch-haiku45 | 0 | yes | 3/3 | 0.0287 | 0.0000 | 10.7 | 2 | 12004 | 0 | 1 | 0 | 0 | ba884c53f74e |
| gh-limits | small | ko | jevfetch | 1 | yes | 3/3 | 0.0231 | 0.0007 | 10.8 | 2 | 12540 | 1 | 0 | 0 | 0 | 4ba27969a9af |
| gh-limits | small | ko | webfetch | 1 | yes | 3/3 | 0.0208 | 0.0000 | 13.6 | 2 | 12109 | 0 | 1 | 0 | 0 | b78646821a88 |
| gh-limits | small | ko | webfetch-haiku45 | 1 | yes | 3/3 | 0.0289 | 0.0000 | 11.5 | 2 | 11998 | 0 | 1 | 0 | 0 | 0003a18e387e |
| gh-rest-rate | small | ko | jevfetch | 0 | yes | 3/3 | 0.0240 | 0.0009 | 10.4 | 2 | 12722 | 1 | 0 | 0 | 0 | b9ae2aecc059 |
| gh-rest-rate | small | ko | webfetch | 0 | yes | 3/3 | 0.0237 | 0.0000 | 16.4 | 2 | 12318 | 0 | 1 | 0 | 0 | 3ba90996571e |
| gh-rest-rate | small | ko | webfetch-haiku45 | 0 | yes | 3/3 | 0.0245 | 0.0000 | 12.3 | 2 | 12198 | 0 | 1 | 0 | 0 | f291ff40288e |
| gh-rest-rate | small | ko | jevfetch | 1 | yes | 3/3 | 0.0248 | 0.0009 | 11.3 | 2 | 12724 | 1 | 0 | 0 | 0 | d34d5278a8df |
| gh-rest-rate | small | ko | webfetch | 1 | yes | 3/3 | 0.0241 | 0.0000 | 15.5 | 2 | 12276 | 0 | 1 | 0 | 0 | 0299b266ce89 |
| gh-rest-rate | small | ko | webfetch-haiku45 | 1 | yes | 3/3 | 0.0271 | 0.0000 | 14.6 | 2 | 12315 | 0 | 1 | 0 | 0 | c904493c00c6 |
| git-lease | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0249 | 0.0032 | 12.1 | 2 | 12368 | 1 | 0 | 0 | 0 | 6dfb1db9e4d1 |
| git-lease | medium | ko | webfetch | 0 | yes | 2/2 | 0.0423 | 0.0000 | 32.2 | 2 | 13973 | 0 | 1 | 0 | 0 | 841f528002ca |
| git-lease | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0667 | 0.0000 | 32.5 | 2 | 13860 | 0 | 1 | 0 | 0 | d2590d8e8fc0 |
| git-lease | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0263 | 0.0031 | 13.3 | 2 | 12338 | 1 | 0 | 0 | 0 | 280c1d4656d3 |
| git-lease | medium | ko | webfetch | 1 | yes | 2/2 | 0.0422 | 0.0000 | 27.4 | 2 | 13849 | 0 | 1 | 0 | 0 | fd2e0acdabf0 |
| git-lease | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0676 | 0.0000 | 35.4 | 2 | 13862 | 0 | 1 | 0 | 0 | 159014c46f4a |
| http-415-meaning | large | ko | jevfetch | 0 | yes | 1/1 | 0.0822 | 0.0479 | 20.1 | 3 | 21031 | 2 | 0 | 0 | 0 | f79b5aee3dad |
| http-415-meaning | large | ko | webfetch | 0 | yes | 1/1 | 0.0486 | 0.0000 | 27.0 | 5 | 34616 | 0 | 1 | 3 | 1 | 9835bdffda11 |
| http-415-meaning | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0614 | 0.0000 | 20.2 | 4 | 26523 | 0 | 1 | 2 | 0 | 5e4cd5f1948c |
| http-415-meaning | large | ko | jevfetch | 1 | yes | 1/1 | 0.0795 | 0.0465 | 18.2 | 3 | 20771 | 2 | 0 | 0 | 0 | 8a4f36c1f089 |
| http-415-meaning | large | ko | webfetch | 1 | yes | 1/1 | 0.0447 | 0.0000 | 27.5 | 4 | 26901 | 0 | 2 | 1 | 1 | 8f1b2193a87f |
| http-415-meaning | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0598 | 0.0000 | 21.9 | 4 | 26267 | 0 | 1 | 2 | 0 | 02ef572ad8f1 |
| http-if-none-match-false | large | ko | jevfetch | 0 | yes | 1/1 | 0.0463 | 0.0232 | 11.5 | 2 | 12794 | 1 | 0 | 0 | 0 | 77a1b1f2925c |
| http-if-none-match-false | large | ko | webfetch | 0 | yes | 1/1 | 0.0490 | 0.0000 | 25.0 | 5 | 36873 | 0 | 1 | 3 | 0 | f143f074fe69 |
| http-if-none-match-false | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.1732 | 0.0000 | 37.1 | 9 | 66969 | 0 | 4 | 4 | 2 | 81765bbbca9e |
| http-if-none-match-false | large | ko | jevfetch | 1 | yes | 1/1 | 0.0458 | 0.0232 | 12.8 | 2 | 12761 | 1 | 0 | 0 | 0 | 721dbe0bd3c3 |
| http-if-none-match-false | large | ko | webfetch | 1 | yes | 1/1 | 0.0480 | 0.0000 | 25.6 | 5 | 34663 | 0 | 2 | 3 | 2 | 87024cc69a6e |
| http-if-none-match-false | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0678 | 0.0000 | 19.7 | 4 | 27826 | 0 | 1 | 3 | 0 | f04c394a8213 |
| http-retry-after-values | large | ko | jevfetch | 0 | yes | 1/1 | 0.0635 | 0.0230 | 14.1 | 2 | 14734 | 1 | 0 | 0 | 0 | bdebdb496fd2 |
| http-retry-after-values | large | ko | webfetch | 0 | yes | 1/1 | 0.0609 | 0.0000 | 34.4 | 5 | 34831 | 0 | 3 | 2 | 1 | de35c8d210cf |
| http-retry-after-values | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0844 | 0.0000 | 20.8 | 4 | 29288 | 0 | 1 | 3 | 0 | 69e8532a779e |
| http-retry-after-values | large | ko | jevfetch | 1 | yes | 1/1 | 0.0525 | 0.0230 | 13.4 | 2 | 14439 | 1 | 0 | 0 | 0 | f63e7e8aa260 |
| http-retry-after-values | large | ko | webfetch | 1 | yes | 1/1 | 0.0491 | 0.0000 | 28.6 | 5 | 35063 | 0 | 2 | 2 | 1 | 42b1e91ad9c9 |
| http-retry-after-values | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0617 | 0.0000 | 18.0 | 4 | 26657 | 0 | 1 | 2 | 0 | 3a958145973b |
| k8s-termination | medium | ko | jevfetch | 0 | yes | 3/3 | 0.0314 | 0.0026 | 14.6 | 2 | 13131 | 1 | 0 | 0 | 0 | b671d37ba99c |
| k8s-termination | medium | ko | webfetch | 0 | yes | 3/3 | 0.0627 | 0.0000 | 43.3 | 3 | 22990 | 0 | 2 | 0 | 0 | 21af0f1bd3f1 |
| k8s-termination | medium | ko | webfetch-haiku45 | 0 | yes | 3/3 | 0.0895 | 0.0000 | 31.8 | 6 | 45836 | 0 | 1 | 2 | 2 | 745ffd5b4fae |
| k8s-termination | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0304 | 0.0026 | 12.5 | 2 | 13179 | 1 | 0 | 0 | 0 | 2c0e445bba72 |
| k8s-termination | medium | ko | webfetch | 1 | yes | 3/3 | 0.0571 | 0.0000 | 42.5 | 3 | 22447 | 0 | 2 | 0 | 0 | 4a0d305783e6 |
| k8s-termination | medium | ko | webfetch-haiku45 | 1 | yes | 3/3 | 0.0939 | 0.0000 | 26.7 | 4 | 27524 | 0 | 2 | 1 | 1 | 60968cd38080 |
| ko-holiday | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0362 | 0.0014 | 14.0 | 2 | 14601 | 1 | 0 | 0 | 0 | 8b88651c69df |
| ko-holiday | medium | ko | webfetch | 0 | yes | 1/1 | 0.0358 | 0.0000 | 32.6 | 2 | 12769 | 0 | 1 | 0 | 0 | 3b0108ff15ec |
| ko-holiday | medium | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0648 | 0.0000 | 16.5 | 2 | 12073 | 0 | 1 | 0 | 0 | 267944fb54ca |
| ko-holiday | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0337 | 0.0014 | 11.7 | 2 | 14557 | 1 | 0 | 0 | 0 | 9ec14a4aac37 |
| ko-holiday | medium | ko | webfetch | 1 | yes | 1/1 | 0.0351 | 0.0000 | 26.0 | 2 | 12801 | 0 | 1 | 0 | 0 | 1c14caf55a21 |
| ko-holiday | medium | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0643 | 0.0000 | 15.5 | 2 | 12133 | 0 | 1 | 0 | 0 | a81f0bf62efa |
| ko-minwage | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0233 | 0.0014 | 10.4 | 2 | 12726 | 1 | 0 | 0 | 0 | ffaaf0ec2289 |
| ko-minwage | medium | ko | webfetch | 0 | yes | 4/4 | 0.0212 | 0.0000 | 14.9 | 2 | 12062 | 0 | 1 | 0 | 0 | 54044843efb9 |
| ko-minwage | medium | ko | webfetch-haiku45 | 0 | yes | 4/4 | 0.0403 | 0.0000 | 13.2 | 2 | 12130 | 0 | 1 | 0 | 0 | bd298d94db06 |
| ko-minwage | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0237 | 0.0014 | 10.8 | 2 | 12768 | 1 | 0 | 0 | 0 | 86542e45552b |
| ko-minwage | medium | ko | webfetch | 1 | yes | 4/4 | 0.0224 | 0.0000 | 14.3 | 2 | 12123 | 0 | 1 | 0 | 0 | ed5981d702e6 |
| ko-minwage | medium | ko | webfetch-haiku45 | 1 | yes | 4/4 | 0.0405 | 0.0000 | 14.4 | 2 | 12107 | 0 | 1 | 0 | 0 | caf31a143f4c |
| mdn-keepalive | small | ko | jevfetch | 0 | yes | 1/1 | 0.0209 | 0.0009 | 10.0 | 2 | 12550 | 1 | 0 | 0 | 0 | b4db9f3f395f |
| mdn-keepalive | small | ko | webfetch | 0 | yes | 1/1 | 0.0243 | 0.0000 | 17.4 | 2 | 12490 | 0 | 1 | 0 | 0 | 3f1e6acdd9ac |
| mdn-keepalive | small | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0301 | 0.0000 | 12.4 | 2 | 12181 | 0 | 1 | 0 | 0 | 5eb7b85c6ec4 |
| mdn-keepalive | small | ko | jevfetch | 1 | yes | 1/1 | 0.0216 | 0.0009 | 10.2 | 2 | 12523 | 1 | 0 | 0 | 0 | 197199ff5e42 |
| mdn-keepalive | small | ko | webfetch | 1 | yes | 1/1 | 0.0241 | 0.0000 | 16.0 | 2 | 12789 | 0 | 1 | 0 | 0 | 3b867f8cf146 |
| mdn-keepalive | small | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0298 | 0.0000 | 12.8 | 2 | 12279 | 0 | 1 | 0 | 0 | 64343b355624 |
| nginx-read-timeout | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0278 | 0.0048 | 11.5 | 2 | 13363 | 1 | 0 | 0 | 0 | 86a2c40b5089 |
| nginx-read-timeout | medium | ko | webfetch | 0 | yes | 2/2 | 0.0231 | 0.0000 | 15.9 | 2 | 12384 | 0 | 1 | 0 | 0 | 1edfd7e4ae5b |
| nginx-read-timeout | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0400 | 0.0000 | 14.5 | 2 | 12263 | 0 | 1 | 0 | 0 | 3dfd3c110738 |
| nginx-read-timeout | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0269 | 0.0048 | 11.6 | 2 | 13278 | 1 | 0 | 0 | 0 | 35b2fd2221b8 |
| nginx-read-timeout | medium | ko | webfetch | 1 | yes | 2/2 | 0.0253 | 0.0000 | 18.3 | 2 | 12633 | 0 | 1 | 0 | 0 | f9f07d0f8fed |
| nginx-read-timeout | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0392 | 0.0000 | 13.8 | 2 | 12181 | 0 | 1 | 0 | 0 | c1a1cbc52d12 |
| nist-aal2-reauthentication | large | ko | jevfetch | 0 | yes | 1/1 | 0.0320 | 0.0068 | 12.5 | 2 | 13080 | 1 | 0 | 0 | 0 | 6b3470258ab6 |
| nist-aal2-reauthentication | large | ko | webfetch | 0 | yes | 1/1 | 0.0289 | 0.0000 | 24.9 | 2 | 12702 | 0 | 1 | 0 | 0 | 0e7199f4f117 |
| nist-aal2-reauthentication | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0557 | 0.0000 | 20.7 | 3 | 19524 | 0 | 1 | 1 | 0 | 269ecd3d6817 |
| nist-aal2-reauthentication | large | ko | jevfetch | 1 | yes | 1/1 | 0.0311 | 0.0068 | 13.8 | 2 | 13079 | 1 | 0 | 0 | 0 | aacf1f90d495 |
| nist-aal2-reauthentication | large | ko | webfetch | 1 | yes | 1/1 | 0.0294 | 0.0000 | 27.1 | 2 | 12748 | 0 | 1 | 0 | 0 | 5c18a833a052 |
| nist-aal2-reauthentication | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0508 | 0.0000 | 17.6 | 2 | 12380 | 0 | 1 | 0 | 0 | 9245e5225b46 |
| nist-password-max-length | large | ko | jevfetch | 0 | yes | 1/1 | 0.0299 | 0.0068 | 11.4 | 2 | 12641 | 1 | 0 | 0 | 0 | 7911e018a887 |
| nist-password-max-length | large | ko | webfetch | 0 | yes | 1/1 | 0.0418 | 0.0000 | 27.2 | 3 | 21277 | 0 | 1 | 1 | 0 | 05e8657a1479 |
| nist-password-max-length | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0471 | 0.0000 | 15.1 | 2 | 12151 | 0 | 1 | 0 | 0 | 2aa538029f28 |
| nist-password-max-length | large | ko | jevfetch | 1 | yes | 1/1 | 0.0323 | 0.0067 | 15.0 | 2 | 12816 | 1 | 0 | 0 | 0 | a714897a8312 |
| nist-password-max-length | large | ko | webfetch | 1 | yes | 1/1 | 0.0274 | 0.0000 | 20.0 | 2 | 12397 | 0 | 1 | 0 | 0 | af2be2172b9b |
| nist-password-max-length | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0453 | 0.0000 | 13.9 | 2 | 12182 | 0 | 1 | 0 | 0 | 7298af8a8cfc |
| nist-password-min-length | large | ko | jevfetch | 0 | yes | 1/1 | 0.0354 | 0.0069 | 11.8 | 2 | 14049 | 1 | 0 | 0 | 0 | 45106d169a44 |
| nist-password-min-length | large | ko | webfetch | 0 | yes | 1/1 | 0.0308 | 0.0000 | 24.2 | 2 | 12758 | 0 | 1 | 0 | 0 | 8c55e282986f |
| nist-password-min-length | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0444 | 0.0000 | 13.4 | 2 | 12141 | 0 | 1 | 0 | 0 | 1768809bace9 |
| nist-password-min-length | large | ko | jevfetch | 1 | yes | 1/1 | 0.0353 | 0.0070 | 13.7 | 2 | 14011 | 1 | 0 | 0 | 0 | 0896e29ebbc9 |
| nist-password-min-length | large | ko | webfetch | 1 | yes | 1/1 | 0.0288 | 0.0000 | 21.5 | 2 | 12618 | 0 | 1 | 0 | 0 | a5a6fce95fdb |
| nist-password-min-length | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0463 | 0.0000 | 15.0 | 2 | 12191 | 0 | 1 | 0 | 0 | 776a91e8b2e6 |
| npm-peer | medium | ko | jevfetch | 0 | yes | 3/3 | 0.0245 | 0.0019 | 11.4 | 2 | 12368 | 1 | 0 | 0 | 0 | 4ccfe175310b |
| npm-peer | medium | ko | webfetch | 0 | yes | 3/3 | 0.0268 | 0.0000 | 22.1 | 2 | 12649 | 0 | 1 | 0 | 0 | 78c5e34efd40 |
| npm-peer | medium | ko | webfetch-haiku45 | 0 | yes | 3/3 | 0.0397 | 0.0000 | 14.4 | 2 | 12230 | 0 | 1 | 0 | 0 | a2ad6fb4a6c9 |
| npm-peer | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0243 | 0.0019 | 11.8 | 2 | 12482 | 1 | 0 | 0 | 0 | f6023a14f87e |
| npm-peer | medium | ko | webfetch | 1 | yes | 3/3 | 0.0264 | 0.0000 | 21.2 | 2 | 12444 | 0 | 1 | 0 | 0 | 1505f011706d |
| npm-peer | medium | ko | webfetch-haiku45 | 1 | yes | 2/3 | 0.0422 | 0.0000 | 16.8 | 2 | 12317 | 0 | 1 | 0 | 0 | abcf42c9f8b7 |
| pg-wraparound | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0359 | 0.0024 | 16.0 | 2 | 13449 | 1 | 0 | 0 | 0 | f1117b05fc42 |
| pg-wraparound | medium | ko | webfetch | 0 | yes | 2/2 | 0.0409 | 0.0000 | 30.2 | 2 | 13272 | 0 | 1 | 0 | 0 | 146eaaefc1b2 |
| pg-wraparound | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0388 | 0.0000 | 18.6 | 2 | 12420 | 0 | 1 | 0 | 0 | 9fbc2823c53c |
| pg-wraparound | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0356 | 0.0021 | 18.4 | 2 | 13316 | 1 | 0 | 0 | 0 | fa070880b514 |
| pg-wraparound | medium | ko | webfetch | 1 | yes | 2/2 | 0.0342 | 0.0000 | 23.1 | 2 | 12924 | 0 | 1 | 0 | 0 | b689a29b33ca |
| pg-wraparound | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0425 | 0.0000 | 20.8 | 2 | 12792 | 0 | 1 | 0 | 0 | 1718a9dc7912 |
| py-subprocess | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0290 | 0.0038 | 12.0 | 2 | 12692 | 1 | 0 | 0 | 0 | ce23cca4e762 |
| py-subprocess | medium | ko | webfetch | 0 | yes | 2/2 | 0.0434 | 0.0000 | 31.9 | 2 | 14264 | 0 | 1 | 0 | 0 | ef525a4c44eb |
| py-subprocess | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0639 | 0.0000 | 30.3 | 2 | 13837 | 0 | 1 | 0 | 0 | e852c0bffccf |
| py-subprocess | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0302 | 0.0037 | 12.9 | 2 | 12863 | 1 | 0 | 0 | 0 | 8df6527bba65 |
| py-subprocess | medium | ko | webfetch | 1 | yes | 2/2 | 0.0482 | 0.0000 | 35.8 | 2 | 14615 | 0 | 1 | 0 | 0 | 941d98ad22f7 |
| py-subprocess | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0716 | 0.0000 | 32.7 | 2 | 14566 | 0 | 1 | 0 | 0 | 68c9ff11cb3a |
| redis-expire | medium | ko | jevfetch | 0 | yes | 3/4 | 0.0512 | 0.0040 | 13.8 | 2 | 18254 | 1 | 0 | 0 | 0 | 6a8ddcc65bc6 |
| redis-expire | medium | ko | webfetch | 0 | yes | 4/4 | 0.0806 | 0.0000 | 14.7 | 2 | 25309 | 0 | 1 | 0 | 0 | 30b1071c34c9 |
| redis-expire | medium | ko | webfetch-haiku45 | 0 | yes | 4/4 | 0.0802 | 0.0000 | 15.9 | 2 | 25303 | 0 | 1 | 0 | 0 | 256862bba652 |
| redis-expire | medium | ko | jevfetch | 1 | yes | 3/4 | 0.0481 | 0.0040 | 14.1 | 2 | 17453 | 1 | 0 | 0 | 0 | 3b1d5c30acbf |
| redis-expire | medium | ko | webfetch | 1 | yes | 4/4 | 0.0830 | 0.0000 | 16.4 | 2 | 25261 | 0 | 1 | 0 | 0 | 9c4862dff967 |
| redis-expire | medium | ko | webfetch-haiku45 | 1 | yes | 4/4 | 0.0818 | 0.0000 | 14.2 | 2 | 25307 | 0 | 1 | 0 | 0 | ae4c4fe069ab |
| rfc9111-heuristic | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0336 | 0.0052 | 15.5 | 2 | 12764 | 1 | 0 | 0 | 0 | 7884e979c5fc |
| rfc9111-heuristic | medium | ko | webfetch | 0 | yes | 4/4 | 0.0329 | 0.0000 | 24.7 | 2 | 12721 | 0 | 1 | 0 | 0 | a8fa925fc4f5 |
| rfc9111-heuristic | medium | ko | webfetch-haiku45 | 0 | yes | 4/4 | 0.0526 | 0.0000 | 15.7 | 2 | 12316 | 0 | 1 | 0 | 0 | 963b912e706f |
| rfc9111-heuristic | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0327 | 0.0059 | 14.7 | 2 | 12847 | 1 | 0 | 0 | 0 | 43d37520fdb0 |
| rfc9111-heuristic | medium | ko | webfetch | 1 | yes | 4/4 | 0.0326 | 0.0000 | 24.8 | 2 | 12860 | 0 | 1 | 0 | 0 | 11ce886c9e96 |
| rfc9111-heuristic | medium | ko | webfetch-haiku45 | 1 | yes | 4/4 | 0.0729 | 0.0000 | 26.3 | 4 | 29031 | 0 | 1 | 2 | 0 | 41e06d506c42 |
| sqlite-length | small | ko | jevfetch | 0 | yes | 3/3 | 0.0204 | 0.0006 | 11.2 | 2 | 12426 | 1 | 0 | 0 | 0 | 375b953fb159 |
| sqlite-length | small | ko | webfetch | 0 | yes | 3/3 | 0.0290 | 0.0000 | 20.9 | 2 | 12852 | 0 | 1 | 0 | 0 | 95cd9e5d2296 |
| sqlite-length | small | ko | webfetch-haiku45 | 0 | yes | 3/3 | 0.0330 | 0.0000 | 21.7 | 2 | 12654 | 0 | 1 | 0 | 0 | e5c724d0bbfd |
| sqlite-length | small | ko | jevfetch | 1 | yes | 3/3 | 0.0232 | 0.0006 | 11.9 | 2 | 12529 | 1 | 0 | 0 | 0 | dc3b46ea298e |
| sqlite-length | small | ko | webfetch | 1 | yes | 3/3 | 0.0244 | 0.0000 | 16.5 | 2 | 12801 | 0 | 1 | 0 | 0 | cc323bc2df21 |
| sqlite-length | small | ko | webfetch-haiku45 | 1 | yes | 3/3 | 0.0295 | 0.0000 | 15.9 | 2 | 12278 | 0 | 1 | 0 | 0 | 229d047613e5 |
| stripe-rate | small | ko | jevfetch | 0 | yes | 1/1 | 0.0387 | 0.0000 | 16.1 | 2 | 15075 | 1 | 0 | 0 | 0 | fd7ff575319f |
| stripe-rate | small | ko | webfetch | 0 | yes | 1/1 | 0.0397 | 0.0000 | 11.6 | 2 | 16004 | 0 | 1 | 0 | 0 | 6eea4706a6ae |
| stripe-rate | small | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0432 | 0.0000 | 13.2 | 2 | 16023 | 0 | 1 | 0 | 0 | 3b5e34ceb78a |
| stripe-rate | small | ko | jevfetch | 1 | yes | 1/1 | 0.0355 | 0.0000 | 15.7 | 2 | 15062 | 1 | 0 | 0 | 0 | a9c2326a4a6c |
| stripe-rate | small | ko | webfetch | 1 | yes | 1/1 | 0.0425 | 0.0000 | 13.3 | 2 | 16007 | 0 | 1 | 0 | 0 | a779cebd2eea |
| stripe-rate | small | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0432 | 0.0000 | 13.4 | 2 | 16056 | 0 | 1 | 0 | 0 | b407382a3fa0 |
| subprocess-communicate-timeout | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0275 | 0.0035 | 11.4 | 2 | 12634 | 1 | 0 | 0 | 0 | c1bf3a520e1c |
| subprocess-communicate-timeout | medium | ko | webfetch | 0 | yes | 1/1 | 0.0331 | 0.0000 | 20.0 | 2 | 13001 | 0 | 1 | 0 | 0 | b3b61d630698 |
| subprocess-communicate-timeout | medium | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0492 | 0.0000 | 17.2 | 2 | 12547 | 0 | 1 | 0 | 0 | 96b48c4397d6 |
| subprocess-communicate-timeout | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0276 | 0.0035 | 11.0 | 2 | 12634 | 1 | 0 | 0 | 0 | f5f36e64ca15 |
| subprocess-communicate-timeout | medium | ko | webfetch | 1 | yes | 1/1 | 0.0295 | 0.0000 | 16.8 | 2 | 12455 | 0 | 1 | 0 | 0 | eab1dc5a385d |
| subprocess-communicate-timeout | medium | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0457 | 0.0000 | 13.8 | 2 | 12338 | 0 | 1 | 0 | 0 | 5ddfb6a29594 |
| subprocess-run-timeout | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0281 | 0.0036 | 12.4 | 2 | 12621 | 1 | 0 | 0 | 0 | d2a92b45306d |
| subprocess-run-timeout | medium | ko | webfetch | 0 | yes | 1/1 | 0.0359 | 0.0000 | 26.0 | 2 | 13358 | 0 | 1 | 0 | 0 | 256ffe6e96a5 |
| subprocess-run-timeout | medium | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0508 | 0.0000 | 18.8 | 2 | 12580 | 0 | 1 | 0 | 0 | 95773b3f8dc9 |
| subprocess-run-timeout | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0275 | 0.0037 | 12.3 | 2 | 12578 | 1 | 0 | 0 | 0 | 7386f27ea52f |
| subprocess-run-timeout | medium | ko | webfetch | 1 | yes | 1/1 | 0.0335 | 0.0000 | 23.9 | 2 | 13194 | 0 | 1 | 0 | 0 | b18228cc5d89 |
| subprocess-run-timeout | medium | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0488 | 0.0000 | 17.2 | 2 | 12346 | 0 | 1 | 0 | 0 | 7caabb2ce3fa |
| subprocess-shell-security | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0326 | 0.0043 | 14.1 | 2 | 13290 | 1 | 0 | 0 | 0 | 992c75eaf124 |
| subprocess-shell-security | medium | ko | webfetch | 0 | yes | 1/1 | 0.0463 | 0.0000 | 34.2 | 2 | 14763 | 0 | 1 | 0 | 0 | b2921f4a0f0a |
| subprocess-shell-security | medium | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0579 | 0.0000 | 25.5 | 2 | 13095 | 0 | 1 | 0 | 0 | 3b02909602c3 |
| subprocess-shell-security | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0316 | 0.0042 | 13.4 | 2 | 13281 | 1 | 0 | 0 | 0 | 77471efaba31 |
| subprocess-shell-security | medium | ko | webfetch | 1 | yes | 1/1 | 0.0449 | 0.0000 | 30.9 | 2 | 13649 | 0 | 1 | 0 | 0 | 2b30d2badb00 |
| subprocess-shell-security | medium | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0679 | 0.0000 | 33.8 | 2 | 13513 | 0 | 1 | 0 | 0 | eda25e339317 |
| us-dst | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0277 | 0.0020 | 13.1 | 2 | 13276 | 1 | 0 | 0 | 0 | 36a58d958114 |
| us-dst | medium | ko | webfetch | 0 | yes | 2/2 | 0.0330 | 0.0000 | 23.7 | 2 | 12672 | 0 | 1 | 0 | 0 | e2df382de2cb |
| us-dst | medium | ko | webfetch-haiku45 | 0 | yes | 2/2 | 0.0569 | 0.0000 | 16.2 | 2 | 12217 | 0 | 1 | 0 | 0 | 27b8d03ab34a |
| us-dst | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0271 | 0.0020 | 11.8 | 2 | 12891 | 1 | 0 | 0 | 0 | 1a622a61b043 |
| us-dst | medium | ko | webfetch | 1 | yes | 2/2 | 0.0357 | 0.0000 | 23.4 | 2 | 12983 | 0 | 1 | 0 | 0 | 1d001267395d |
| us-dst | medium | ko | webfetch-haiku45 | 1 | yes | 2/2 | 0.0561 | 0.0000 | 14.7 | 2 | 12240 | 0 | 1 | 0 | 0 | e322b6341223 |
| ww2-death-toll | large | ko | jevfetch | 0 | yes | 1/1 | 0.0304 | 0.0056 | 13.7 | 2 | 12877 | 1 | 0 | 0 | 0 | e0ea202202e3 |
| ww2-death-toll | large | ko | webfetch | 0 | yes | 1/1 | 0.0554 | 0.0000 | 35.5 | 4 | 27628 | 0 | 3 | 0 | 0 | a652e1fa6738 |
| ww2-death-toll | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0805 | 0.0000 | 22.4 | 5 | 33629 | 0 | 1 | 3 | 0 | 9ae4a8cf430b |
| ww2-death-toll | large | ko | jevfetch | 1 | yes | 1/1 | 0.0276 | 0.0056 | 10.7 | 2 | 12558 | 1 | 0 | 0 | 0 | c6f4be227b74 |
| ww2-death-toll | large | ko | webfetch | 1 | yes | 1/1 | 0.0531 | 0.0000 | 33.1 | 4 | 27384 | 0 | 3 | 0 | 0 | 569786d63630 |
| ww2-death-toll | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.1462 | 0.0000 | 29.1 | 4 | 26251 | 0 | 3 | 0 | 0 | c785be5ec0d4 |
| ww2-start-date | large | ko | jevfetch | 0 | yes | 1/1 | 0.0322 | 0.0061 | 12.1 | 2 | 13487 | 1 | 0 | 0 | 0 | 22d2b255d0a6 |
| ww2-start-date | large | ko | webfetch | 0 | yes | 1/1 | 0.0243 | 0.0000 | 13.5 | 2 | 11995 | 0 | 1 | 0 | 0 | ed6a45c91f76 |
| ww2-start-date | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0629 | 0.0000 | 12.5 | 2 | 12045 | 0 | 1 | 0 | 0 | 83222facad3e |
| ww2-start-date | large | ko | jevfetch | 1 | yes | 1/1 | 0.0322 | 0.0062 | 12.7 | 2 | 13484 | 1 | 0 | 0 | 0 | a19ad0b82548 |
| ww2-start-date | large | ko | webfetch | 1 | yes | 1/1 | 0.0279 | 0.0000 | 20.5 | 2 | 12355 | 0 | 1 | 0 | 0 | e64f9d7865ee |
| ww2-start-date | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0647 | 0.0000 | 15.4 | 2 | 12236 | 0 | 1 | 0 | 0 | 2c12947539be |
| ww2-un-founded | large | ko | jevfetch | 0 | yes | 1/1 | 0.0258 | 0.0052 | 11.4 | 2 | 12506 | 1 | 0 | 0 | 0 | a400527ba298 |
| ww2-un-founded | large | ko | webfetch | 0 | yes | 1/1 | 0.0348 | 0.0000 | 28.9 | 4 | 25785 | 0 | 1 | 2 | 0 | 099d694b9bb6 |
| ww2-un-founded | large | ko | webfetch-haiku45 | 0 | yes | 1/1 | 0.0700 | 0.0000 | 17.6 | 4 | 25356 | 0 | 1 | 2 | 0 | 1753f27da5cb |
| ww2-un-founded | large | ko | jevfetch | 1 | yes | 1/1 | 0.0261 | 0.0052 | 10.7 | 2 | 12497 | 1 | 0 | 0 | 0 | fc1fb694b2f7 |
| ww2-un-founded | large | ko | webfetch | 1 | yes | 1/1 | 0.0350 | 0.0000 | 22.0 | 4 | 26026 | 0 | 1 | 2 | 0 | 86c492f1efa7 |
| ww2-un-founded | large | ko | webfetch-haiku45 | 1 | yes | 1/1 | 0.0733 | 0.0000 | 17.3 | 4 | 26048 | 0 | 1 | 2 | 0 | 293d6f4ed94d |
