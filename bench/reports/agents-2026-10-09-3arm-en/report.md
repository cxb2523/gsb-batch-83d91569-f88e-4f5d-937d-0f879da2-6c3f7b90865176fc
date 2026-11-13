# Agent-level comparison, 2026-10-09

- Claude Code `claude --version`: 2.1.295 (Claude Code); versions seen in traces: 2.1.295; orchestrator model: sonnet; models billed: claude-haiku-4-5-20251001, claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.13.0
- jevfetch revision 8d38867; instruction sha1 recorded at run time: webfetch ['fc609d4f0c'], webfetch-haiku45 ['fc609d4f0c'], jevfetch ['569edd574c']; allowed tools: webfetch ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; webfetch-haiku45 ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; jevfetch ['Bash(curl:*) Bash(grep:*) Bash(head:*) Bash(jevfetch:*)']
- mode: URL given, no WebSearch; question language: en; small model override: None, claude-haiku-4-5-20251001
- questions: 32; runs per arm: webfetch 64, webfetch-haiku45 64, jevfetch 64; schedule seed 7; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 2 runs with a Bash command refused (allow rules or variable check), webfetch-haiku45: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 4 runs with a Bash command refused (allow rules or variable check), jevfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch | 126/126 | 64/64 | 0.0298 | 0.0257 | 0.0041 | 0.0000 | 16.1 | 18.4 | 2.56 | 16711 | 918 | 1.12 | 28 (12) | 2 |
| webfetch-haiku45 | 126/126 | 64/64 | 0.0497 | 0.0262 | 0.0236 | 0.0000 | 13.6 | 15.3 | 2.94 | 19484 | 873 | 1.06 | 56 (20) | 4 |
| jevfetch | 124/126 | 64/64 | 0.0290 | 0.0231 | 0.0000 | 0.0059 | 10.4 | 10.8 | 2.05 | 13533 | 709 | 1.05 | 0 (0) | 0 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch, cost ratio: 0.97 (interval 0.85 to 1.13), i.e. 3% lower; 32 questions
- vs webfetch, mean-time ratio: 0.58 (interval 0.53 to 0.65); runs were executed one at a time (concurrency 1)
- vs webfetch, facts right per run, difference: -0.03 (interval -0.09 to +0.00)
- vs webfetch-haiku45, cost ratio: 0.58 (interval 0.50 to 0.69), i.e. 42% lower; 32 questions
- vs webfetch-haiku45, mean-time ratio: 0.70 (interval 0.63 to 0.79); runs were executed one at a time (concurrency 1)
- vs webfetch-haiku45, facts right per run, difference: -0.03 (interval -0.09 to +0.00)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | en | 9 | webfetch | 18/18 | 0.0303 | 0.0245 | 0.0058 | 0.0000 | 16.1 | 3.44 | 21780 | 847 | 1.22 | 22 (10) |  |  |
| large | en | 9 | webfetch-haiku45 | 18/18 | 0.0570 | 0.0244 | 0.0326 | 0.0000 | 14.2 | 3.39 | 21856 | 818 | 1.00 | 26 (10) |  |  |
| large | en | 9 | jevfetch | 18/18 | 0.0373 | 0.0226 | 0.0000 | 0.0147 | 10.4 | 2.11 | 14044 | 666 | 1.11 | 0 (0) | 1.23 (0.86 to 1.67) vs webfetch; 0.65 (0.47 to 0.92) vs webfetch-haiku45 | 0.64 (0.52 to 0.80) vs webfetch; 0.76 (0.63 to 0.93) vs webfetch-haiku45 |
| medium | en | 16 | webfetch | 76/76 | 0.0319 | 0.0277 | 0.0042 | 0.0000 | 19.7 | 2.16 | 14503 | 1019 | 1.12 | 1 (1) |  |  |
| medium | en | 16 | webfetch-haiku45 | 76/76 | 0.0540 | 0.0288 | 0.0252 | 0.0000 | 14.1 | 2.88 | 19584 | 966 | 1.09 | 24 (8) |  |  |
| medium | en | 16 | jevfetch | 74/76 | 0.0269 | 0.0238 | 0.0000 | 0.0032 | 10.9 | 2.03 | 13336 | 770 | 1.03 | 0 (0) | 0.84 (0.77 to 0.94) vs webfetch; 0.50 (0.44 to 0.57) vs webfetch-haiku45 | 0.55 (0.48 to 0.66) vs webfetch; 0.66 (0.57 to 0.79) vs webfetch-haiku45 |
| small | en | 7 | webfetch | 32/32 | 0.0243 | 0.0227 | 0.0016 | 0.0000 | 14.4 | 2.36 | 15240 | 778 | 1.00 | 5 (1) |  |  |
| small | en | 7 | webfetch-haiku45 | 32/32 | 0.0307 | 0.0224 | 0.0083 | 0.0000 | 12.6 | 2.50 | 16206 | 731 | 1.07 | 6 (2) |  |  |
| small | en | 7 | jevfetch | 32/32 | 0.0231 | 0.0223 | 0.0000 | 0.0009 | 9.3 | 2.00 | 13327 | 625 | 1.00 | 0 (0) | 0.95 (0.79 to 1.19) vs webfetch; 0.75 (0.59 to 0.93) vs webfetch-haiku45 | 0.59 (0.50 to 0.74) vs webfetch; 0.74 (0.63 to 0.88) vs webfetch-haiku45 |

## Judge votes that were not unanimous (1 of 102 judged runs; review by hand before publishing)

- redis-expire webfetch-haiku45 rep 0: f4#0

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-cache | medium | en | jevfetch | 0 | yes | 4/4 | 0.0318 | 0.0025 | 13.4 | 2 | 13717 | 1 | 0 | 0 | 0 | f07ff4c7d43a |
| claude-cache | medium | en | webfetch | 0 | yes | 4/4 | 0.0406 | 0.0000 | 23.1 | 3 | 19706 | 0 | 2 | 0 | 0 | b28079e8f478 |
| claude-cache | medium | en | webfetch-haiku45 | 0 | yes | 4/4 | 0.0617 | 0.0000 | 23.8 | 3 | 19381 | 0 | 2 | 0 | 0 | 5b6643b13858 |
| claude-cache | medium | en | jevfetch | 1 | yes | 4/4 | 0.0301 | 0.0025 | 11.3 | 2 | 13678 | 1 | 0 | 0 | 0 | d44107bf78d6 |
| claude-cache | medium | en | webfetch | 1 | yes | 4/4 | 0.0394 | 0.0000 | 23.6 | 3 | 19609 | 0 | 2 | 0 | 0 | eb364e93018d |
| claude-cache | medium | en | webfetch-haiku45 | 1 | yes | 4/4 | 0.0572 | 0.0000 | 22.6 | 3 | 19203 | 0 | 2 | 0 | 0 | b4b125c4485b |
| docker-swap | small | en | jevfetch | 0 | yes | 2/2 | 0.0174 | 0.0006 | 9.0 | 2 | 12209 | 1 | 0 | 0 | 0 | aece8be73076 |
| docker-swap | small | en | webfetch | 0 | yes | 2/2 | 0.0189 | 0.0000 | 14.1 | 2 | 11838 | 0 | 1 | 0 | 0 | 5d772380ebb4 |
| docker-swap | small | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0221 | 0.0000 | 10.7 | 2 | 11928 | 0 | 1 | 0 | 0 | aafc46c5f608 |
| docker-swap | small | en | jevfetch | 1 | yes | 2/2 | 0.0169 | 0.0006 | 9.4 | 2 | 12209 | 1 | 0 | 0 | 0 | a572e7eb2bed |
| docker-swap | small | en | webfetch | 1 | yes | 2/2 | 0.0173 | 0.0000 | 12.8 | 2 | 11830 | 0 | 1 | 0 | 0 | f59f7defa2b6 |
| docker-swap | small | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0210 | 0.0000 | 16.1 | 2 | 11919 | 0 | 1 | 0 | 0 | 4aaeb1bd716f |
| gcs-lifecycle | small | en | jevfetch | 0 | yes | 3/3 | 0.0400 | 0.0026 | 10.8 | 2 | 16410 | 1 | 0 | 0 | 0 | 3f32a3a446ae |
| gcs-lifecycle | small | en | webfetch | 0 | yes | 3/3 | 0.0246 | 0.0000 | 27.0 | 2 | 12235 | 0 | 1 | 0 | 0 | a67eefba6fec |
| gcs-lifecycle | small | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.0341 | 0.0000 | 12.6 | 2 | 12068 | 0 | 1 | 0 | 0 | d391d3aea3d1 |
| gcs-lifecycle | small | en | jevfetch | 1 | yes | 3/3 | 0.0376 | 0.0026 | 11.0 | 2 | 16227 | 1 | 0 | 0 | 0 | 7b6af0c54518 |
| gcs-lifecycle | small | en | webfetch | 1 | yes | 3/3 | 0.0243 | 0.0000 | 20.2 | 2 | 12267 | 0 | 1 | 0 | 0 | b8d5ce1e2c2a |
| gcs-lifecycle | small | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0341 | 0.0000 | 12.4 | 2 | 12053 | 0 | 1 | 0 | 0 | 3417f93cfbab |
| gdpr-fines | medium | en | jevfetch | 0 | yes | 2/2 | 0.0242 | 0.0017 | 10.6 | 2 | 12847 | 1 | 0 | 0 | 0 | 81ca828ef75e |
| gdpr-fines | medium | en | webfetch | 0 | yes | 2/2 | 0.0245 | 0.0000 | 14.6 | 2 | 12150 | 0 | 1 | 0 | 0 | f5d9e335182f |
| gdpr-fines | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0484 | 0.0000 | 11.7 | 2 | 11984 | 0 | 1 | 0 | 0 | ade1d3db9419 |
| gdpr-fines | medium | en | jevfetch | 1 | yes | 2/2 | 0.0242 | 0.0017 | 10.6 | 2 | 12839 | 1 | 0 | 0 | 0 | 9feda315b49f |
| gdpr-fines | medium | en | webfetch | 1 | yes | 2/2 | 0.0248 | 0.0000 | 15.7 | 2 | 12092 | 0 | 1 | 0 | 0 | f187b4bb98c9 |
| gdpr-fines | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0485 | 0.0000 | 11.9 | 2 | 11961 | 0 | 1 | 0 | 0 | 92552ce03306 |
| gh-limits | small | en | jevfetch | 0 | yes | 3/3 | 0.0191 | 0.0007 | 9.1 | 2 | 12491 | 1 | 0 | 0 | 0 | a0bb9258b169 |
| gh-limits | small | en | webfetch | 0 | yes | 3/3 | 0.0177 | 0.0000 | 11.9 | 2 | 11786 | 0 | 1 | 0 | 0 | a41ca5fc5b51 |
| gh-limits | small | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.0265 | 0.0000 | 11.0 | 2 | 11946 | 0 | 1 | 0 | 0 | e1847ec0cac8 |
| gh-limits | small | en | jevfetch | 1 | yes | 3/3 | 0.0193 | 0.0007 | 8.6 | 2 | 12422 | 1 | 0 | 0 | 0 | 2466b0ee811f |
| gh-limits | small | en | webfetch | 1 | yes | 3/3 | 0.0201 | 0.0000 | 14.7 | 2 | 12415 | 0 | 1 | 0 | 0 | 98555e57179f |
| gh-limits | small | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0627 | 0.0000 | 22.7 | 7 | 49374 | 0 | 2 | 4 | 2 | 6bceb37985d6 |
| gh-rest-rate | small | en | jevfetch | 0 | yes | 3/3 | 0.0199 | 0.0009 | 9.0 | 2 | 12513 | 1 | 0 | 0 | 0 | 11595c28f910 |
| gh-rest-rate | small | en | webfetch | 0 | yes | 3/3 | 0.0240 | 0.0000 | 22.3 | 2 | 12460 | 0 | 1 | 0 | 0 | ccd3e218c973 |
| gh-rest-rate | small | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.0259 | 0.0000 | 13.3 | 2 | 12282 | 0 | 1 | 0 | 0 | 8730008514fb |
| gh-rest-rate | small | en | jevfetch | 1 | yes | 3/3 | 0.0208 | 0.0009 | 10.2 | 2 | 12552 | 1 | 0 | 0 | 0 | 3ff9f9fb4963 |
| gh-rest-rate | small | en | webfetch | 1 | yes | 3/3 | 0.0243 | 0.0000 | 20.0 | 2 | 12327 | 0 | 1 | 0 | 0 | a8409103c661 |
| gh-rest-rate | small | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0241 | 0.0000 | 13.0 | 2 | 12135 | 0 | 1 | 0 | 0 | b5f956a62d39 |
| git-lease | medium | en | jevfetch | 0 | yes | 2/2 | 0.0221 | 0.0031 | 10.8 | 2 | 12300 | 1 | 0 | 0 | 0 | b440929596e6 |
| git-lease | medium | en | webfetch | 0 | yes | 2/2 | 0.0282 | 0.0000 | 19.7 | 2 | 12701 | 0 | 1 | 0 | 0 | c3869c88736c |
| git-lease | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0446 | 0.0000 | 15.0 | 2 | 12069 | 0 | 1 | 0 | 0 | 7b31e8c446f7 |
| git-lease | medium | en | jevfetch | 1 | yes | 2/2 | 0.0232 | 0.0031 | 10.3 | 2 | 12332 | 1 | 0 | 0 | 0 | d62901aa4de3 |
| git-lease | medium | en | webfetch | 1 | yes | 2/2 | 0.0316 | 0.0000 | 24.0 | 2 | 13293 | 0 | 1 | 0 | 0 | 390a864de5e2 |
| git-lease | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0572 | 0.0000 | 17.9 | 4 | 21584 | 0 | 1 | 2 | 0 | 40b6faa0f7c1 |
| http-415-meaning | large | en | jevfetch | 0 | yes | 1/1 | 0.0810 | 0.0484 | 18.0 | 3 | 21232 | 2 | 0 | 0 | 0 | b5a9332491a7 |
| http-415-meaning | large | en | webfetch | 0 | yes | 1/1 | 0.0271 | 0.0000 | 15.7 | 4 | 24965 | 0 | 1 | 2 | 0 | 6269ded068ef |
| http-415-meaning | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0557 | 0.0000 | 15.1 | 4 | 25352 | 0 | 1 | 2 | 0 | 3475c7c766e6 |
| http-415-meaning | large | en | jevfetch | 1 | yes | 1/1 | 0.0822 | 0.0486 | 19.2 | 3 | 21484 | 2 | 0 | 0 | 0 | e9b110dc7b6b |
| http-415-meaning | large | en | webfetch | 1 | yes | 1/1 | 0.0412 | 0.0000 | 20.3 | 5 | 33928 | 0 | 1 | 3 | 1 | 58065e948f27 |
| http-415-meaning | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0562 | 0.0000 | 15.4 | 4 | 26337 | 0 | 1 | 2 | 0 | f6c57dfbf48b |
| http-if-none-match-false | large | en | jevfetch | 0 | yes | 1/1 | 0.0421 | 0.0234 | 11.1 | 2 | 12668 | 1 | 0 | 0 | 0 | a9c6a89a606a |
| http-if-none-match-false | large | en | webfetch | 0 | yes | 1/1 | 0.0365 | 0.0000 | 18.9 | 5 | 33718 | 0 | 1 | 3 | 0 | 5dc3d7f81ed9 |
| http-if-none-match-false | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0588 | 0.0000 | 15.5 | 4 | 26449 | 0 | 1 | 2 | 0 | aebba81d5b61 |
| http-if-none-match-false | large | en | jevfetch | 1 | yes | 1/1 | 0.0427 | 0.0236 | 10.0 | 2 | 12683 | 1 | 0 | 0 | 0 | 7c172fd7bd38 |
| http-if-none-match-false | large | en | webfetch | 1 | yes | 1/1 | 0.0277 | 0.0000 | 15.9 | 3 | 19237 | 0 | 1 | 1 | 0 | 4b819c83bec0 |
| http-if-none-match-false | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0695 | 0.0000 | 20.5 | 6 | 42138 | 0 | 1 | 5 | 0 | 6e2cecfffcb3 |
| http-retry-after-values | large | en | jevfetch | 0 | yes | 1/1 | 0.0476 | 0.0228 | 10.4 | 2 | 14216 | 1 | 0 | 0 | 0 | f40674f6d6e0 |
| http-retry-after-values | large | en | webfetch | 0 | yes | 1/1 | 0.0378 | 0.0000 | 17.9 | 5 | 34112 | 0 | 1 | 3 | 0 | 4f66be7c2b45 |
| http-retry-after-values | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0588 | 0.0000 | 17.8 | 4 | 26348 | 0 | 1 | 2 | 0 | 127f8b1efbc0 |
| http-retry-after-values | large | en | jevfetch | 1 | yes | 1/1 | 0.0471 | 0.0227 | 9.3 | 2 | 14180 | 1 | 0 | 0 | 0 | 16dfdcc96729 |
| http-retry-after-values | large | en | webfetch | 1 | yes | 1/1 | 0.0279 | 0.0000 | 14.6 | 3 | 19098 | 0 | 1 | 1 | 0 | 85c022c2af0c |
| http-retry-after-values | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0559 | 0.0000 | 14.9 | 4 | 26135 | 0 | 1 | 2 | 0 | 3b6ef89171f2 |
| k8s-termination | medium | en | jevfetch | 0 | yes | 3/3 | 0.0276 | 0.0027 | 9.8 | 2 | 13363 | 1 | 0 | 0 | 0 | 1fd9d0db6d21 |
| k8s-termination | medium | en | webfetch | 0 | yes | 3/3 | 0.0377 | 0.0000 | 25.6 | 3 | 19793 | 0 | 2 | 0 | 0 | 69f9ded27ee2 |
| k8s-termination | medium | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.1117 | 0.0000 | 29.8 | 8 | 61618 | 0 | 2 | 5 | 1 | 2cc8998af59a |
| k8s-termination | medium | en | jevfetch | 1 | yes | 3/3 | 0.0284 | 0.0027 | 11.6 | 2 | 13415 | 1 | 0 | 0 | 0 | 18fc37c8df05 |
| k8s-termination | medium | en | webfetch | 1 | yes | 3/3 | 0.0411 | 0.0000 | 27.4 | 3 | 20009 | 0 | 2 | 0 | 0 | 6e1638815629 |
| k8s-termination | medium | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0874 | 0.0000 | 30.1 | 9 | 69765 | 0 | 1 | 7 | 1 | 6699de4bcfe0 |
| ko-holiday | medium | en | jevfetch | 0 | yes | 1/1 | 0.0307 | 0.0015 | 12.0 | 2 | 14468 | 1 | 0 | 0 | 0 | 9b8465779029 |
| ko-holiday | medium | en | webfetch | 0 | yes | 1/1 | 0.0321 | 0.0000 | 34.3 | 2 | 12557 | 0 | 1 | 0 | 0 | feefb02d686f |
| ko-holiday | medium | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0794 | 0.0000 | 18.0 | 3 | 21441 | 0 | 1 | 1 | 0 | 08f09a6beeb5 |
| ko-holiday | medium | en | jevfetch | 1 | yes | 1/1 | 0.0296 | 0.0014 | 11.3 | 2 | 14464 | 1 | 0 | 0 | 0 | f0d7ae56b8c3 |
| ko-holiday | medium | en | webfetch | 1 | yes | 1/1 | 0.0317 | 0.0000 | 34.1 | 2 | 12469 | 0 | 1 | 0 | 0 | f3bcf37cdc53 |
| ko-holiday | medium | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0781 | 0.0000 | 21.4 | 3 | 20881 | 0 | 1 | 1 | 0 | b041630c5fba |
| ko-minwage | medium | en | jevfetch | 0 | yes | 4/4 | 0.0213 | 0.0015 | 9.7 | 2 | 12291 | 1 | 0 | 0 | 0 | a6516d52e1ed |
| ko-minwage | medium | en | webfetch | 0 | yes | 4/4 | 0.0210 | 0.0000 | 15.9 | 2 | 12045 | 0 | 1 | 0 | 0 | 1a90009b99e0 |
| ko-minwage | medium | en | webfetch-haiku45 | 0 | yes | 4/4 | 0.0378 | 0.0000 | 13.0 | 2 | 12009 | 0 | 1 | 0 | 0 | f11523b4b802 |
| ko-minwage | medium | en | jevfetch | 1 | yes | 4/4 | 0.0195 | 0.0015 | 9.5 | 2 | 12303 | 1 | 0 | 0 | 0 | af40d2f03ea2 |
| ko-minwage | medium | en | webfetch | 1 | yes | 4/4 | 0.0196 | 0.0000 | 14.4 | 2 | 11922 | 0 | 1 | 0 | 0 | 8fd606cb4342 |
| ko-minwage | medium | en | webfetch-haiku45 | 1 | yes | 4/4 | 0.0389 | 0.0000 | 13.1 | 2 | 12033 | 0 | 1 | 0 | 0 | 7a46fd636320 |
| mdn-keepalive | small | en | jevfetch | 0 | yes | 1/1 | 0.0186 | 0.0009 | 8.2 | 2 | 12411 | 1 | 0 | 0 | 0 | 06e5db95a8e7 |
| mdn-keepalive | small | en | webfetch | 0 | yes | 1/1 | 0.0408 | 0.0000 | 22.1 | 7 | 48126 | 0 | 1 | 5 | 1 | 551b66329fc8 |
| mdn-keepalive | small | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0339 | 0.0000 | 15.6 | 4 | 25260 | 0 | 1 | 2 | 0 | df3c61c15095 |
| mdn-keepalive | small | en | jevfetch | 1 | yes | 1/1 | 0.0187 | 0.0009 | 9.0 | 2 | 12405 | 1 | 0 | 0 | 0 | cc880ad62b81 |
| mdn-keepalive | small | en | webfetch | 1 | yes | 1/1 | 0.0174 | 0.0000 | 10.7 | 2 | 11974 | 0 | 1 | 0 | 0 | d9d89e0db62b |
| mdn-keepalive | small | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0277 | 0.0000 | 11.3 | 2 | 11980 | 0 | 1 | 0 | 0 | 1fec83ad2c8d |
| nginx-read-timeout | medium | en | jevfetch | 0 | yes | 2/2 | 0.0248 | 0.0047 | 9.1 | 2 | 13167 | 1 | 0 | 0 | 0 | dbfdffdaf5be |
| nginx-read-timeout | medium | en | webfetch | 0 | yes | 2/2 | 0.0188 | 0.0000 | 12.7 | 2 | 11912 | 0 | 1 | 0 | 0 | 6af233409b09 |
| nginx-read-timeout | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0348 | 0.0000 | 11.0 | 2 | 11824 | 0 | 1 | 0 | 0 | c5af17a649ad |
| nginx-read-timeout | medium | en | jevfetch | 1 | yes | 2/2 | 0.0247 | 0.0047 | 13.3 | 2 | 13212 | 1 | 0 | 0 | 0 | f0890cb543cb |
| nginx-read-timeout | medium | en | webfetch | 1 | yes | 2/2 | 0.0181 | 0.0000 | 10.9 | 2 | 11814 | 0 | 1 | 0 | 0 | fdc8ff26c037 |
| nginx-read-timeout | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0347 | 0.0000 | 10.6 | 2 | 11832 | 0 | 1 | 0 | 0 | a9297c5284ca |
| nist-aal2-reauthentication | large | en | jevfetch | 0 | yes | 1/1 | 0.0256 | 0.0066 | 11.6 | 2 | 12650 | 1 | 0 | 0 | 0 | 5e41cc1fcf49 |
| nist-aal2-reauthentication | large | en | webfetch | 0 | yes | 1/1 | 0.0221 | 0.0000 | 16.1 | 2 | 11856 | 0 | 1 | 0 | 0 | 86c0a9fb2a35 |
| nist-aal2-reauthentication | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0429 | 0.0000 | 12.3 | 2 | 12120 | 0 | 1 | 0 | 0 | 422ae2cd8bdd |
| nist-aal2-reauthentication | large | en | jevfetch | 1 | yes | 1/1 | 0.0254 | 0.0066 | 9.9 | 2 | 12656 | 1 | 0 | 0 | 0 | aea8d77fdfc4 |
| nist-aal2-reauthentication | large | en | webfetch | 1 | yes | 1/1 | 0.0219 | 0.0000 | 14.1 | 2 | 11906 | 0 | 1 | 0 | 0 | 2274737d0d39 |
| nist-aal2-reauthentication | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0407 | 0.0000 | 12.1 | 2 | 12003 | 0 | 1 | 0 | 0 | a3f01d16663a |
| nist-password-max-length | large | en | jevfetch | 0 | yes | 1/1 | 0.0276 | 0.0071 | 9.0 | 2 | 13100 | 1 | 0 | 0 | 0 | d75781f83135 |
| nist-password-max-length | large | en | webfetch | 0 | yes | 1/1 | 0.0213 | 0.0000 | 16.0 | 2 | 11972 | 0 | 1 | 0 | 0 | 2dcd5e70da7f |
| nist-password-max-length | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0429 | 0.0000 | 13.9 | 2 | 12106 | 0 | 1 | 0 | 0 | 47aca2229644 |
| nist-password-max-length | large | en | jevfetch | 1 | yes | 1/1 | 0.0323 | 0.0071 | 11.3 | 2 | 13797 | 1 | 0 | 0 | 0 | 1fa6bb35a0b2 |
| nist-password-max-length | large | en | webfetch | 1 | yes | 1/1 | 0.0203 | 0.0000 | 12.5 | 2 | 11927 | 0 | 1 | 0 | 0 | b8b367b5d113 |
| nist-password-max-length | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0403 | 0.0000 | 11.6 | 2 | 11975 | 0 | 1 | 0 | 0 | 0a701d95d693 |
| nist-password-min-length | large | en | jevfetch | 0 | yes | 1/1 | 0.0310 | 0.0072 | 10.0 | 2 | 13870 | 1 | 0 | 0 | 0 | cf76026ea240 |
| nist-password-min-length | large | en | webfetch | 0 | yes | 1/1 | 0.0207 | 0.0000 | 14.9 | 2 | 11933 | 0 | 1 | 0 | 0 | 5331624f5a0b |
| nist-password-min-length | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0429 | 0.0000 | 13.2 | 2 | 12088 | 0 | 1 | 0 | 0 | b36842bf74cd |
| nist-password-min-length | large | en | jevfetch | 1 | yes | 1/1 | 0.0317 | 0.0072 | 10.6 | 2 | 13858 | 1 | 0 | 0 | 0 | 06fb4197c861 |
| nist-password-min-length | large | en | webfetch | 1 | yes | 1/1 | 0.0254 | 0.0000 | 19.3 | 2 | 12347 | 0 | 1 | 0 | 0 | f50cf3a2aa41 |
| nist-password-min-length | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0416 | 0.0000 | 11.7 | 2 | 12067 | 0 | 1 | 0 | 0 | 85e9fae3e597 |
| npm-peer | medium | en | jevfetch | 0 | yes | 3/3 | 0.0186 | 0.0019 | 7.3 | 2 | 12249 | 1 | 0 | 0 | 0 | 9d98ea8a821e |
| npm-peer | medium | en | webfetch | 0 | yes | 3/3 | 0.0179 | 0.0000 | 13.3 | 2 | 11826 | 0 | 1 | 0 | 0 | fd3f2c49ef95 |
| npm-peer | medium | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.0346 | 0.0000 | 12.2 | 2 | 12006 | 0 | 1 | 0 | 0 | 49ed814d60e1 |
| npm-peer | medium | en | jevfetch | 1 | yes | 3/3 | 0.0201 | 0.0019 | 14.6 | 2 | 12281 | 1 | 0 | 0 | 0 | b17ab3fdb33e |
| npm-peer | medium | en | webfetch | 1 | yes | 3/3 | 0.0187 | 0.0000 | 13.2 | 2 | 11813 | 0 | 1 | 0 | 0 | 7a5439777f4b |
| npm-peer | medium | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0341 | 0.0000 | 10.8 | 2 | 11987 | 0 | 1 | 0 | 0 | c467dd9c1767 |
| pg-wraparound | medium | en | jevfetch | 0 | yes | 2/2 | 0.0253 | 0.0019 | 13.2 | 2 | 12919 | 1 | 0 | 0 | 0 | 3fb7bd9e5590 |
| pg-wraparound | medium | en | webfetch | 0 | yes | 2/2 | 0.0296 | 0.0000 | 20.9 | 2 | 12934 | 0 | 1 | 0 | 0 | b03d4e98a595 |
| pg-wraparound | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0374 | 0.0000 | 18.4 | 2 | 12617 | 0 | 1 | 0 | 0 | e35707cc7616 |
| pg-wraparound | medium | en | jevfetch | 1 | yes | 2/2 | 0.0224 | 0.0019 | 11.3 | 2 | 12621 | 1 | 0 | 0 | 0 | 79b65ec4bdb2 |
| pg-wraparound | medium | en | webfetch | 1 | yes | 2/2 | 0.0286 | 0.0000 | 20.6 | 2 | 13090 | 0 | 1 | 0 | 0 | 7c4a9c11724c |
| pg-wraparound | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0330 | 0.0000 | 14.3 | 2 | 12259 | 0 | 1 | 0 | 0 | 0a8803682f22 |
| py-subprocess | medium | en | jevfetch | 0 | yes | 2/2 | 0.0388 | 0.0091 | 14.9 | 3 | 13974 | 2 | 0 | 0 | 0 | 28ced77c0506 |
| py-subprocess | medium | en | webfetch | 0 | yes | 2/2 | 0.0218 | 0.0000 | 12.8 | 2 | 12159 | 0 | 1 | 0 | 0 | 1996b5b1cc9e |
| py-subprocess | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0506 | 0.0000 | 21.2 | 2 | 12829 | 0 | 1 | 0 | 0 | 24952cc07d38 |
| py-subprocess | medium | en | jevfetch | 1 | yes | 2/2 | 0.0245 | 0.0037 | 10.2 | 2 | 12544 | 1 | 0 | 0 | 0 | 38b7614f5ea8 |
| py-subprocess | medium | en | webfetch | 1 | yes | 2/2 | 0.0333 | 0.0000 | 24.5 | 2 | 13177 | 0 | 1 | 0 | 0 | 50e29eca19fd |
| py-subprocess | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0457 | 0.0000 | 15.7 | 2 | 12321 | 0 | 1 | 0 | 0 | f129f3bcdf27 |
| redis-expire | medium | en | jevfetch | 0 | yes | 3/4 | 0.0483 | 0.0042 | 12.2 | 2 | 18920 | 1 | 0 | 0 | 0 | 0b750344937f |
| redis-expire | medium | en | webfetch | 0 | yes | 4/4 | 0.0721 | 0.0000 | 11.5 | 2 | 25105 | 0 | 1 | 0 | 0 | 52a2a66a3d1b |
| redis-expire | medium | en | webfetch-haiku45 | 0 | yes | 4/4 | 0.0725 | 0.0000 | 9.9 | 2 | 25119 | 0 | 1 | 0 | 0 | a87c189b9c22 |
| redis-expire | medium | en | jevfetch | 1 | yes | 3/4 | 0.0485 | 0.0040 | 11.8 | 2 | 18959 | 1 | 0 | 0 | 0 | ec92e94fbdef |
| redis-expire | medium | en | webfetch | 1 | yes | 4/4 | 0.0742 | 0.0000 | 12.0 | 2 | 25111 | 0 | 1 | 0 | 0 | ea38f5c9c52a |
| redis-expire | medium | en | webfetch-haiku45 | 1 | yes | 4/4 | 0.0732 | 0.0000 | 9.6 | 2 | 25195 | 0 | 1 | 0 | 0 | 25110aaf8270 |
| rfc9111-heuristic | medium | en | jevfetch | 0 | yes | 4/4 | 0.0296 | 0.0052 | 12.3 | 2 | 12801 | 1 | 0 | 0 | 0 | 45f6de540ae6 |
| rfc9111-heuristic | medium | en | webfetch | 0 | yes | 4/4 | 0.0513 | 0.0000 | 29.5 | 3 | 23324 | 0 | 1 | 1 | 0 | 82e3551c4396 |
| rfc9111-heuristic | medium | en | webfetch-haiku45 | 0 | yes | 4/4 | 0.0629 | 0.0000 | 18.8 | 3 | 20004 | 0 | 1 | 1 | 0 | 393565a857e0 |
| rfc9111-heuristic | medium | en | jevfetch | 1 | yes | 4/4 | 0.0285 | 0.0051 | 10.9 | 2 | 12801 | 1 | 0 | 0 | 0 | 38d8d315c0eb |
| rfc9111-heuristic | medium | en | webfetch | 1 | yes | 4/4 | 0.0333 | 0.0000 | 28.1 | 2 | 12677 | 0 | 1 | 0 | 0 | e826fbbdfaf7 |
| rfc9111-heuristic | medium | en | webfetch-haiku45 | 1 | yes | 4/4 | 0.0675 | 0.0000 | 23.1 | 4 | 27806 | 0 | 1 | 3 | 0 | 1525067fc012 |
| sqlite-length | small | en | jevfetch | 0 | yes | 3/3 | 0.0182 | 0.0005 | 9.3 | 2 | 12428 | 1 | 0 | 0 | 0 | 517a6091fc2c |
| sqlite-length | small | en | webfetch | 0 | yes | 3/3 | 0.0201 | 0.0000 | 14.1 | 2 | 12111 | 0 | 1 | 0 | 0 | 413aaca606c0 |
| sqlite-length | small | en | webfetch-haiku45 | 0 | yes | 3/3 | 0.0232 | 0.0000 | 12.7 | 2 | 12032 | 0 | 1 | 0 | 0 | 4d186b0fefda |
| sqlite-length | small | en | jevfetch | 1 | yes | 3/3 | 0.0187 | 0.0006 | 10.5 | 2 | 12422 | 1 | 0 | 0 | 0 | 0fe7fa38ef9b |
| sqlite-length | small | en | webfetch | 1 | yes | 3/3 | 0.0213 | 0.0000 | 16.1 | 2 | 12248 | 0 | 1 | 0 | 0 | cc74779ff047 |
| sqlite-length | small | en | webfetch-haiku45 | 1 | yes | 3/3 | 0.0251 | 0.0000 | 13.9 | 2 | 12127 | 0 | 1 | 0 | 0 | 3694e8d9d3f1 |
| stripe-rate | small | en | jevfetch | 0 | yes | 1/1 | 0.0291 | 0.0000 | 9.6 | 2 | 14962 | 1 | 0 | 0 | 0 | 05be7fd0cd02 |
| stripe-rate | small | en | webfetch | 0 | yes | 1/1 | 0.0343 | 0.0000 | 9.5 | 2 | 15867 | 0 | 1 | 0 | 0 | 3c5d9dbc2ed0 |
| stripe-rate | small | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0339 | 0.0000 | 7.6 | 2 | 15884 | 0 | 1 | 0 | 0 | ddb73f9d942f |
| stripe-rate | small | en | jevfetch | 1 | yes | 1/1 | 0.0300 | 0.0000 | 9.7 | 2 | 14923 | 1 | 0 | 0 | 0 | b4805856bcec |
| stripe-rate | small | en | webfetch | 1 | yes | 1/1 | 0.0349 | 0.0000 | 8.8 | 2 | 15870 | 0 | 1 | 0 | 0 | c93a0ee6f92a |
| stripe-rate | small | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0354 | 0.0000 | 8.2 | 2 | 15889 | 0 | 1 | 0 | 0 | fefdacc8345d |
| subprocess-communicate-timeout | medium | en | jevfetch | 0 | yes | 1/1 | 0.0232 | 0.0035 | 9.0 | 2 | 12553 | 1 | 0 | 0 | 0 | 992931d511b2 |
| subprocess-communicate-timeout | medium | en | webfetch | 0 | yes | 1/1 | 0.0244 | 0.0000 | 14.0 | 2 | 12369 | 0 | 1 | 0 | 0 | 6ff16d9dcccc |
| subprocess-communicate-timeout | medium | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0438 | 0.0000 | 13.9 | 2 | 12302 | 0 | 1 | 0 | 0 | b8e4faf55716 |
| subprocess-communicate-timeout | medium | en | jevfetch | 1 | yes | 1/1 | 0.0223 | 0.0035 | 10.9 | 2 | 12484 | 1 | 0 | 0 | 0 | abd7b6701022 |
| subprocess-communicate-timeout | medium | en | webfetch | 1 | yes | 1/1 | 0.0242 | 0.0000 | 15.7 | 2 | 12235 | 0 | 1 | 0 | 0 | 85cb7b9d520b |
| subprocess-communicate-timeout | medium | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0403 | 0.0000 | 11.7 | 2 | 12038 | 0 | 1 | 0 | 0 | 14da21998f36 |
| subprocess-run-timeout | medium | en | jevfetch | 0 | yes | 1/1 | 0.0235 | 0.0035 | 9.2 | 2 | 12575 | 1 | 0 | 0 | 0 | da2c5191c858 |
| subprocess-run-timeout | medium | en | webfetch | 0 | yes | 1/1 | 0.0289 | 0.0000 | 19.7 | 2 | 12649 | 0 | 1 | 0 | 0 | 12152a9746b9 |
| subprocess-run-timeout | medium | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0419 | 0.0000 | 13.2 | 2 | 12233 | 0 | 1 | 0 | 0 | cf1f1a66af48 |
| subprocess-run-timeout | medium | en | jevfetch | 1 | yes | 1/1 | 0.0223 | 0.0035 | 9.2 | 2 | 12532 | 1 | 0 | 0 | 0 | 460348075532 |
| subprocess-run-timeout | medium | en | webfetch | 1 | yes | 1/1 | 0.0250 | 0.0000 | 16.2 | 2 | 12243 | 0 | 1 | 0 | 0 | d29f6c06b60c |
| subprocess-run-timeout | medium | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0423 | 0.0000 | 12.4 | 2 | 12157 | 0 | 1 | 0 | 0 | ff521772fb59 |
| subprocess-shell-security | medium | en | jevfetch | 0 | yes | 1/1 | 0.0280 | 0.0044 | 11.1 | 2 | 13105 | 1 | 0 | 0 | 0 | 8d563de9f60e |
| subprocess-shell-security | medium | en | webfetch | 0 | yes | 1/1 | 0.0366 | 0.0000 | 27.6 | 2 | 13275 | 0 | 1 | 0 | 0 | 80828f7ffb60 |
| subprocess-shell-security | medium | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0467 | 0.0000 | 18.2 | 2 | 12398 | 0 | 1 | 0 | 0 | d8a09686d68a |
| subprocess-shell-security | medium | en | jevfetch | 1 | yes | 1/1 | 0.0276 | 0.0042 | 10.6 | 2 | 13093 | 1 | 0 | 0 | 0 | 5764b6b67519 |
| subprocess-shell-security | medium | en | webfetch | 1 | yes | 1/1 | 0.0348 | 0.0000 | 26.1 | 2 | 13120 | 0 | 1 | 0 | 0 | bc8d71aeea65 |
| subprocess-shell-security | medium | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0769 | 0.0000 | 34.3 | 8 | 51719 | 0 | 1 | 4 | 2 | 30a13de79296 |
| us-dst | medium | en | jevfetch | 0 | yes | 2/2 | 0.0238 | 0.0020 | 10.9 | 2 | 12952 | 1 | 0 | 0 | 0 | 49eb66403ad6 |
| us-dst | medium | en | webfetch | 0 | yes | 2/2 | 0.0293 | 0.0000 | 22.2 | 2 | 12431 | 0 | 1 | 0 | 0 | a7f8b006321f |
| us-dst | medium | en | webfetch-haiku45 | 0 | yes | 2/2 | 0.0524 | 0.0000 | 12.7 | 2 | 12059 | 0 | 1 | 0 | 0 | 99cd624d7a2d |
| us-dst | medium | en | jevfetch | 1 | yes | 2/2 | 0.0239 | 0.0019 | 10.3 | 2 | 12979 | 1 | 0 | 0 | 0 | 602cf51df98b |
| us-dst | medium | en | webfetch | 1 | yes | 2/2 | 0.0262 | 0.0000 | 17.5 | 2 | 12499 | 0 | 1 | 0 | 0 | 31bf8de2e1d7 |
| us-dst | medium | en | webfetch-haiku45 | 1 | yes | 2/2 | 0.0525 | 0.0000 | 12.4 | 2 | 12054 | 0 | 1 | 0 | 0 | 6d317a5918ca |
| ww2-death-toll | large | en | jevfetch | 0 | yes | 1/1 | 0.0255 | 0.0056 | 10.5 | 2 | 12450 | 1 | 0 | 0 | 0 | bd4244d49881 |
| ww2-death-toll | large | en | webfetch | 0 | yes | 1/1 | 0.0598 | 0.0000 | 34.4 | 7 | 46935 | 0 | 3 | 3 | 0 | 32febfab5444 |
| ww2-death-toll | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0760 | 0.0000 | 18.5 | 5 | 32647 | 0 | 1 | 3 | 0 | 0cb9407b08ac |
| ww2-death-toll | large | en | jevfetch | 1 | yes | 1/1 | 0.0256 | 0.0056 | 10.2 | 2 | 12446 | 1 | 0 | 0 | 0 | e7b7da453f61 |
| ww2-death-toll | large | en | webfetch | 1 | yes | 1/1 | 0.0360 | 0.0000 | 19.8 | 4 | 26145 | 0 | 1 | 2 | 0 | f3c96675a798 |
| ww2-death-toll | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0851 | 0.0000 | 21.7 | 6 | 40650 | 0 | 1 | 4 | 0 | 048237329c4a |
| ww2-start-date | large | en | jevfetch | 0 | yes | 1/1 | 0.0286 | 0.0059 | 11.4 | 2 | 13351 | 1 | 0 | 0 | 0 | 161fbeb9656d |
| ww2-start-date | large | en | webfetch | 0 | yes | 1/1 | 0.0206 | 0.0000 | 11.5 | 2 | 11670 | 0 | 1 | 0 | 0 | d92c24eb5614 |
| ww2-start-date | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0600 | 0.0000 | 11.5 | 2 | 11890 | 0 | 1 | 0 | 0 | 17620cb97eb4 |
| ww2-start-date | large | en | jevfetch | 1 | yes | 1/1 | 0.0281 | 0.0060 | 10.4 | 2 | 13343 | 1 | 0 | 0 | 0 | c0dbbb3f9aa8 |
| ww2-start-date | large | en | webfetch | 1 | yes | 1/1 | 0.0218 | 0.0000 | 11.5 | 2 | 11850 | 0 | 1 | 0 | 0 | 81274c15cd81 |
| ww2-start-date | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0603 | 0.0000 | 10.9 | 2 | 11997 | 0 | 1 | 0 | 0 | a4fc486d0366 |
| ww2-un-founded | large | en | jevfetch | 0 | yes | 1/1 | 0.0236 | 0.0052 | 9.2 | 2 | 12403 | 1 | 0 | 0 | 0 | 7d3b87236d14 |
| ww2-un-founded | large | en | webfetch | 0 | yes | 1/1 | 0.0464 | 0.0000 | 23.8 | 6 | 33359 | 0 | 3 | 2 | 0 | dd039b0a573c |
| ww2-un-founded | large | en | webfetch-haiku45 | 0 | yes | 1/1 | 0.0702 | 0.0000 | 14.2 | 4 | 25832 | 0 | 1 | 2 | 0 | 0d37c05566b0 |
| ww2-un-founded | large | en | jevfetch | 1 | yes | 1/1 | 0.0235 | 0.0052 | 9.3 | 2 | 12402 | 1 | 0 | 0 | 0 | 6c150206b6e6 |
| ww2-un-founded | large | en | webfetch | 1 | yes | 1/1 | 0.0313 | 0.0000 | 16.3 | 4 | 25077 | 0 | 1 | 2 | 0 | 54c7d9c4b2fd |
| ww2-un-founded | large | en | webfetch-haiku45 | 1 | yes | 1/1 | 0.0678 | 0.0000 | 14.2 | 4 | 25273 | 0 | 1 | 2 | 0 | 35313501b9b7 |
