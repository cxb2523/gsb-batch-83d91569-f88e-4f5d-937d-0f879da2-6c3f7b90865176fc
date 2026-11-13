# Agent-level comparison, 2026-10-23

- Claude Code `claude --version`: 2.1.309 (Claude Code); versions seen in traces: 2.1.309; orchestrator model: sonnet; models billed: claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.14.0
- jevfetch revision 488ed63; instruction sha1 recorded at run time: webfetch ['fc609d4f0c'], jevfetch ['f408570833']; allowed tools: webfetch ['WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; jevfetch ['Bash(curl:*) Bash(grep:*) Bash(head:*) Bash(jevfetch:*)']
- mode: URL given, no WebSearch; question language: ko; small model override: None
- questions: 30; runs per arm: webfetch 60, jevfetch 60; schedule seed 7; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 1 runs with a Bash command refused (allow rules or variable check), jevfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch | 116/116 | 60/60 | 0.0333 | 0.0285 | 0.0048 | 0.0000 | 22.4 | 24.3 | 2.47 | 16777 | 1411 | 1.18 | 20 (9) | 1 |
| jevfetch | 115/116 | 60/60 | 0.0309 | 0.0252 | 0.0000 | 0.0057 | 12.6 | 12.9 | 2.02 | 14001 | 1106 | 1.02 | 0 (0) | 0 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch, cost ratio: 0.93 (interval 0.81 to 1.06), i.e. 7% lower; 30 questions
- vs webfetch, mean-time ratio: 0.53 (interval 0.48 to 0.59); runs were executed one at a time (concurrency 1)
- vs webfetch, facts right per run, difference: -0.02 (interval -0.05 to +0.00)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | ko | 9 | webfetch | 18/18 | 0.0332 | 0.0267 | 0.0065 | 0.0000 | 20.8 | 3.17 | 21104 | 1222 | 1.33 | 18 (8) |  |  |
| large | ko | 9 | jevfetch | 18/18 | 0.0397 | 0.0265 | 0.0000 | 0.0132 | 13.0 | 2.06 | 14578 | 1084 | 1.06 | 0 (0) | 1.19 (0.92 to 1.54) | 0.62 (0.52 to 0.75) |
| medium | ko | 16 | webfetch | 74/74 | 0.0362 | 0.0313 | 0.0049 | 0.0000 | 27.0 | 2.22 | 15501 | 1648 | 1.16 | 2 (1) |  |  |
| medium | ko | 16 | jevfetch | 73/74 | 0.0287 | 0.0258 | 0.0000 | 0.0030 | 13.1 | 2.00 | 13924 | 1178 | 1.00 | 0 (0) | 0.79 (0.70 to 0.91) | 0.48 (0.43 to 0.53) |
| small | ko | 5 | webfetch | 24/24 | 0.0243 | 0.0227 | 0.0016 | 0.0000 | 15.8 | 2.00 | 13072 | 993 | 1.00 | 0 (0) |  |  |
| small | ko | 5 | jevfetch | 24/24 | 0.0218 | 0.0211 | 0.0000 | 0.0008 | 10.8 | 2.00 | 13209 | 915 | 1.00 | 0 (0) | 0.90 (0.82 to 0.99) | 0.61 (0.53 to 0.68) |

## Judge votes that were not unanimous (0 of 64 judged runs; review by hand before publishing)

- none

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-cache | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0363 | 0.0024 | 15.7 | 2 | 14752 | 1 | 0 | 0 | 0 | da2d9cc5535d |
| claude-cache | medium | ko | webfetch | 0 | yes | 4/4 | 0.0366 | 0.0000 | 21.3 | 3 | 20260 | 0 | 2 | 0 | 0 | 062861ec9582 |
| claude-cache | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0337 | 0.0029 | 14.7 | 2 | 14791 | 1 | 0 | 0 | 0 | b5c81a37ed3a |
| claude-cache | medium | ko | webfetch | 1 | yes | 4/4 | 0.0367 | 0.0000 | 25.5 | 3 | 20435 | 0 | 2 | 0 | 0 | 0c0fb4ff1554 |
| docker-swap | small | ko | jevfetch | 0 | yes | 2/2 | 0.0218 | 0.0007 | 10.8 | 2 | 12990 | 1 | 0 | 0 | 0 | ae0e9556d965 |
| docker-swap | small | ko | webfetch | 0 | yes | 2/2 | 0.0292 | 0.0000 | 23.8 | 2 | 13413 | 0 | 1 | 0 | 0 | 6a7fe09ecdd8 |
| docker-swap | small | ko | jevfetch | 1 | yes | 2/2 | 0.0171 | 0.0007 | 9.9 | 2 | 13026 | 1 | 0 | 0 | 0 | 87212c19c584 |
| docker-swap | small | ko | webfetch | 1 | yes | 2/2 | 0.0223 | 0.0000 | 20.3 | 2 | 12964 | 0 | 1 | 0 | 0 | 43c8a2d5837e |
| gcs-lifecycle | medium | ko | jevfetch | 0 | yes | 2/3 | 0.0252 | 0.0023 | 13.8 | 2 | 13887 | 1 | 0 | 0 | 0 | b4c1a669f824 |
| gcs-lifecycle | medium | ko | webfetch | 0 | yes | 3/3 | 0.0409 | 0.0000 | 35.9 | 2 | 14584 | 0 | 1 | 0 | 0 | b4f5230b58de |
| gcs-lifecycle | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0322 | 0.0024 | 16.6 | 2 | 14473 | 1 | 0 | 0 | 0 | 8465606b0af8 |
| gcs-lifecycle | medium | ko | webfetch | 1 | yes | 3/3 | 0.0417 | 0.0000 | 29.9 | 2 | 14228 | 0 | 1 | 0 | 0 | 21c757f27ac4 |
| gdpr-fines | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0270 | 0.0017 | 15.3 | 2 | 13694 | 1 | 0 | 0 | 0 | 1e0e3d933c3f |
| gdpr-fines | medium | ko | webfetch | 0 | yes | 2/2 | 0.0472 | 0.0000 | 38.6 | 3 | 22051 | 0 | 2 | 0 | 0 | e259885752c4 |
| gdpr-fines | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0259 | 0.0017 | 14.4 | 2 | 13726 | 1 | 0 | 0 | 0 | de0eddaacca4 |
| gdpr-fines | medium | ko | webfetch | 1 | yes | 2/2 | 0.0303 | 0.0000 | 24.5 | 2 | 13348 | 0 | 1 | 0 | 0 | b8e7bc579e82 |
| gh-limits | small | ko | jevfetch | 0 | yes | 3/3 | 0.0211 | 0.0008 | 11.2 | 2 | 13067 | 1 | 0 | 0 | 0 | dd854abab251 |
| gh-limits | small | ko | webfetch | 0 | yes | 3/3 | 0.0252 | 0.0000 | 18.6 | 2 | 13610 | 0 | 1 | 0 | 0 | 1041c322f7df |
| gh-limits | small | ko | jevfetch | 1 | yes | 3/3 | 0.0178 | 0.0007 | 10.6 | 2 | 13062 | 1 | 0 | 0 | 0 | 8c92d0bba5d4 |
| gh-limits | small | ko | webfetch | 1 | yes | 3/3 | 0.0161 | 0.0000 | 14.2 | 2 | 12620 | 0 | 1 | 0 | 0 | 3ab41db7db22 |
| gh-rest-rate | small | ko | jevfetch | 0 | yes | 3/3 | 0.0228 | 0.0010 | 10.3 | 2 | 13200 | 1 | 0 | 0 | 0 | 9c1bf6a591a6 |
| gh-rest-rate | small | ko | webfetch | 0 | yes | 3/3 | 0.0227 | 0.0000 | 15.3 | 2 | 12857 | 0 | 1 | 0 | 0 | 0a6852763134 |
| gh-rest-rate | small | ko | jevfetch | 1 | yes | 3/3 | 0.0317 | 0.0010 | 11.1 | 2 | 13272 | 1 | 0 | 0 | 0 | 0951ab29c673 |
| gh-rest-rate | small | ko | webfetch | 1 | yes | 3/3 | 0.0389 | 0.0000 | 15.6 | 2 | 12833 | 0 | 1 | 0 | 0 | f5b9cddb5c7a |
| git-lease | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0262 | 0.0030 | 12.2 | 2 | 13058 | 1 | 0 | 0 | 0 | 6cdc6a62372f |
| git-lease | medium | ko | webfetch | 0 | yes | 2/2 | 0.0405 | 0.0000 | 27.2 | 2 | 14412 | 0 | 1 | 0 | 0 | 1b10a5e6c1f6 |
| git-lease | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0226 | 0.0030 | 13.0 | 2 | 13056 | 1 | 0 | 0 | 0 | f0ef37dbb5fe |
| git-lease | medium | ko | webfetch | 1 | yes | 2/2 | 0.0406 | 0.0000 | 30.2 | 2 | 14888 | 0 | 1 | 0 | 0 | d26a6732a272 |
| http-415-meaning | large | ko | jevfetch | 0 | yes | 1/1 | 0.0499 | 0.0223 | 19.3 | 2 | 13418 | 1 | 0 | 0 | 0 | 2a333339dbb2 |
| http-415-meaning | large | ko | webfetch | 0 | yes | 1/1 | 0.0294 | 0.0000 | 18.7 | 4 | 26477 | 0 | 1 | 2 | 0 | 62918fa2914e |
| http-415-meaning | large | ko | jevfetch | 1 | yes | 1/1 | 0.0813 | 0.0489 | 21.7 | 3 | 22235 | 2 | 0 | 0 | 0 | c549b00cff0d |
| http-415-meaning | large | ko | webfetch | 1 | yes | 1/1 | 0.0287 | 0.0000 | 22.8 | 4 | 27405 | 0 | 1 | 2 | 0 | ae65620af6fc |
| http-if-none-match-false | large | ko | jevfetch | 0 | yes | 1/1 | 0.0425 | 0.0229 | 11.2 | 2 | 13196 | 1 | 0 | 0 | 0 | 0b399f04b7ff |
| http-if-none-match-false | large | ko | webfetch | 0 | yes | 1/1 | 0.0339 | 0.0000 | 23.9 | 4 | 28965 | 0 | 1 | 3 | 0 | 5b4fe2e7344d |
| http-if-none-match-false | large | ko | jevfetch | 1 | yes | 1/1 | 0.0460 | 0.0230 | 12.4 | 2 | 13234 | 1 | 0 | 0 | 0 | c138273aa300 |
| http-if-none-match-false | large | ko | webfetch | 1 | yes | 1/1 | 0.0401 | 0.0000 | 21.5 | 4 | 30541 | 0 | 1 | 2 | 0 | becef1ceaa21 |
| http-retry-after-values | large | ko | jevfetch | 0 | yes | 1/1 | 0.0513 | 0.0227 | 14.4 | 2 | 15300 | 1 | 0 | 0 | 0 | a1c3a063a91e |
| http-retry-after-values | large | ko | webfetch | 0 | yes | 1/1 | 0.0397 | 0.0000 | 23.9 | 4 | 30461 | 0 | 1 | 3 | 0 | 605dbde5752f |
| http-retry-after-values | large | ko | jevfetch | 1 | yes | 1/1 | 0.0537 | 0.0227 | 12.3 | 2 | 15296 | 1 | 0 | 0 | 0 | 239ca046a9a5 |
| http-retry-after-values | large | ko | webfetch | 1 | yes | 1/1 | 0.0496 | 0.0000 | 30.8 | 5 | 28763 | 0 | 3 | 2 | 1 | c4d4ca3a43c2 |
| k8s-termination | medium | ko | jevfetch | 0 | yes | 3/3 | 0.0319 | 0.0027 | 16.3 | 2 | 13923 | 1 | 0 | 0 | 0 | ff37f5765295 |
| k8s-termination | medium | ko | webfetch | 0 | yes | 3/3 | 0.0555 | 0.0000 | 40.1 | 3 | 23116 | 0 | 2 | 0 | 0 | a34a09085d9a |
| k8s-termination | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0317 | 0.0027 | 14.2 | 2 | 14103 | 1 | 0 | 0 | 0 | 10696b51e44a |
| k8s-termination | medium | ko | webfetch | 1 | yes | 3/3 | 0.0608 | 0.0000 | 48.5 | 3 | 23959 | 0 | 2 | 0 | 0 | e0cf1ced4c35 |
| ko-holiday | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0401 | 0.0012 | 14.2 | 2 | 17539 | 1 | 0 | 0 | 0 | fd641415f1a3 |
| ko-holiday | medium | ko | webfetch | 0 | yes | 1/1 | 0.0356 | 0.0000 | 36.9 | 2 | 13545 | 0 | 1 | 0 | 0 | d5fbfca4706c |
| ko-holiday | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0428 | 0.0012 | 11.4 | 2 | 17685 | 1 | 0 | 0 | 0 | 8d3b8000904d |
| ko-holiday | medium | ko | webfetch | 1 | yes | 1/1 | 0.0308 | 0.0000 | 29.1 | 2 | 13142 | 0 | 1 | 0 | 0 | cb3362ab43ed |
| ko-minwage | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0218 | 0.0015 | 9.1 | 2 | 13247 | 1 | 0 | 0 | 0 | 18c0e068d6b8 |
| ko-minwage | medium | ko | webfetch | 0 | yes | 4/4 | 0.0206 | 0.0000 | 14.9 | 2 | 12647 | 0 | 1 | 0 | 0 | 229d091f6f0a |
| ko-minwage | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0180 | 0.0015 | 8.3 | 2 | 13290 | 1 | 0 | 0 | 0 | e345c8e32017 |
| ko-minwage | medium | ko | webfetch | 1 | yes | 4/4 | 0.0209 | 0.0000 | 18.6 | 2 | 12815 | 0 | 1 | 0 | 0 | 3b6262a34653 |
| mdn-keepalive | small | ko | jevfetch | 0 | yes | 1/1 | 0.0231 | 0.0009 | 10.2 | 2 | 13449 | 1 | 0 | 0 | 0 | 4a2907b6f9c2 |
| mdn-keepalive | small | ko | webfetch | 0 | yes | 1/1 | 0.0222 | 0.0000 | 16.0 | 2 | 13066 | 0 | 1 | 0 | 0 | 4e03c642cb06 |
| mdn-keepalive | small | ko | jevfetch | 1 | yes | 1/1 | 0.0205 | 0.0009 | 10.9 | 2 | 13445 | 1 | 0 | 0 | 0 | 6122fec1e516 |
| mdn-keepalive | small | ko | webfetch | 1 | yes | 1/1 | 0.0193 | 0.0000 | 15.0 | 2 | 13030 | 0 | 1 | 0 | 0 | 49fc4b8f1710 |
| nginx-read-timeout | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0275 | 0.0048 | 12.6 | 2 | 13808 | 1 | 0 | 0 | 0 | 52be926b935f |
| nginx-read-timeout | medium | ko | webfetch | 0 | yes | 2/2 | 0.0241 | 0.0000 | 18.6 | 2 | 13262 | 0 | 1 | 0 | 0 | 7b1f53241449 |
| nginx-read-timeout | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0232 | 0.0048 | 10.1 | 2 | 13832 | 1 | 0 | 0 | 0 | f32586b485b8 |
| nginx-read-timeout | medium | ko | webfetch | 1 | yes | 2/2 | 0.0211 | 0.0000 | 16.3 | 2 | 13031 | 0 | 1 | 0 | 0 | bedd35e94c9f |
| nist-aal2-reauthentication | large | ko | jevfetch | 0 | yes | 1/1 | 0.0290 | 0.0067 | 10.7 | 2 | 13395 | 1 | 0 | 0 | 0 | e947f17da204 |
| nist-aal2-reauthentication | large | ko | webfetch | 0 | yes | 1/1 | 0.0264 | 0.0000 | 20.4 | 2 | 12855 | 0 | 1 | 0 | 0 | bf0426d5bbf2 |
| nist-aal2-reauthentication | large | ko | jevfetch | 1 | yes | 1/1 | 0.0325 | 0.0067 | 16.8 | 2 | 13522 | 1 | 0 | 0 | 0 | af59f876273d |
| nist-aal2-reauthentication | large | ko | webfetch | 1 | yes | 1/1 | 0.0257 | 0.0000 | 20.8 | 2 | 12956 | 0 | 1 | 0 | 0 | 8a3660971005 |
| nist-password-max-length | large | ko | jevfetch | 0 | yes | 1/1 | 0.0325 | 0.0067 | 15.0 | 2 | 13368 | 1 | 0 | 0 | 0 | 7f45b2d96e63 |
| nist-password-max-length | large | ko | webfetch | 0 | yes | 1/1 | 0.0300 | 0.0000 | 21.2 | 2 | 13249 | 0 | 1 | 0 | 0 | 7b61f540e99c |
| nist-password-max-length | large | ko | jevfetch | 1 | yes | 1/1 | 0.0317 | 0.0066 | 14.5 | 2 | 13374 | 1 | 0 | 0 | 0 | 894613e2ed6b |
| nist-password-max-length | large | ko | webfetch | 1 | yes | 1/1 | 0.0310 | 0.0000 | 23.8 | 2 | 13314 | 0 | 1 | 0 | 0 | 1daa7e7caa8f |
| nist-password-min-length | large | ko | jevfetch | 0 | yes | 1/1 | 0.0423 | 0.0067 | 12.3 | 2 | 14551 | 1 | 0 | 0 | 0 | 128d23134193 |
| nist-password-min-length | large | ko | webfetch | 0 | yes | 1/1 | 0.0273 | 0.0000 | 20.4 | 2 | 12965 | 0 | 1 | 0 | 0 | 1d3e94d885b3 |
| nist-password-min-length | large | ko | jevfetch | 1 | yes | 1/1 | 0.0347 | 0.0066 | 13.9 | 2 | 14337 | 1 | 0 | 0 | 0 | 272fea673c32 |
| nist-password-min-length | large | ko | webfetch | 1 | yes | 1/1 | 0.0288 | 0.0000 | 20.7 | 2 | 13136 | 0 | 1 | 0 | 0 | b8a4c369959e |
| npm-peer | medium | ko | jevfetch | 0 | yes | 3/3 | 0.0225 | 0.0020 | 10.7 | 2 | 12980 | 1 | 0 | 0 | 0 | 14844a191f5d |
| npm-peer | medium | ko | webfetch | 0 | yes | 3/3 | 0.0248 | 0.0000 | 20.2 | 2 | 12922 | 0 | 1 | 0 | 0 | 7c056588a86d |
| npm-peer | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0243 | 0.0021 | 12.8 | 2 | 12965 | 1 | 0 | 0 | 0 | 37b442d0318b |
| npm-peer | medium | ko | webfetch | 1 | yes | 3/3 | 0.0286 | 0.0000 | 22.1 | 2 | 13235 | 0 | 1 | 0 | 0 | 90be17072941 |
| pg-wraparound | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0357 | 0.0022 | 17.4 | 2 | 14246 | 1 | 0 | 0 | 0 | 529166b5299f |
| pg-wraparound | medium | ko | webfetch | 0 | yes | 2/2 | 0.0330 | 0.0000 | 22.3 | 2 | 13534 | 0 | 1 | 0 | 0 | 018d070beef4 |
| pg-wraparound | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0281 | 0.0022 | 16.4 | 2 | 13532 | 1 | 0 | 0 | 0 | 12a0044184c0 |
| pg-wraparound | medium | ko | webfetch | 1 | yes | 2/2 | 0.0339 | 0.0000 | 26.2 | 2 | 14006 | 0 | 1 | 0 | 0 | e756ca27bf0f |
| py-subprocess | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0290 | 0.0038 | 11.4 | 2 | 13234 | 1 | 0 | 0 | 0 | 52df4832cdac |
| py-subprocess | medium | ko | webfetch | 0 | yes | 2/2 | 0.0473 | 0.0000 | 33.7 | 2 | 15038 | 0 | 1 | 0 | 0 | 9d670fc80e14 |
| py-subprocess | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0278 | 0.0037 | 13.9 | 2 | 13226 | 1 | 0 | 0 | 0 | 68ed0bd364ad |
| py-subprocess | medium | ko | webfetch | 1 | yes | 2/2 | 0.0530 | 0.0000 | 34.7 | 2 | 15389 | 0 | 1 | 0 | 0 | 124b7c4ce0c9 |
| rfc9111-heuristic | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0336 | 0.0058 | 14.6 | 2 | 13508 | 1 | 0 | 0 | 0 | 6fbcf433f3df |
| rfc9111-heuristic | medium | ko | webfetch | 0 | yes | 4/4 | 0.0353 | 0.0000 | 29.4 | 2 | 13820 | 0 | 1 | 0 | 0 | e12904eeec53 |
| rfc9111-heuristic | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0290 | 0.0054 | 15.0 | 2 | 13579 | 1 | 0 | 0 | 0 | 1fb8098c5b05 |
| rfc9111-heuristic | medium | ko | webfetch | 1 | yes | 4/4 | 0.0349 | 0.0000 | 30.1 | 2 | 13563 | 0 | 1 | 0 | 0 | d54bdcca21a2 |
| sqlite-length | small | ko | jevfetch | 0 | yes | 3/3 | 0.0191 | 0.0005 | 12.6 | 2 | 13247 | 1 | 0 | 0 | 0 | 916a7a272756 |
| sqlite-length | small | ko | webfetch | 0 | yes | 3/3 | 0.0248 | 0.0000 | 22.6 | 2 | 13587 | 0 | 1 | 0 | 0 | f8397c72bf5b |
| sqlite-length | small | ko | jevfetch | 1 | yes | 3/3 | 0.0230 | 0.0005 | 11.3 | 2 | 13331 | 1 | 0 | 0 | 0 | c8f00e0ac4be |
| sqlite-length | small | ko | webfetch | 1 | yes | 3/3 | 0.0219 | 0.0000 | 15.7 | 2 | 12745 | 0 | 1 | 0 | 0 | 1360e343d029 |
| subprocess-communicate-timeout | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0227 | 0.0035 | 10.5 | 2 | 13180 | 1 | 0 | 0 | 0 | b78830eea3c0 |
| subprocess-communicate-timeout | medium | ko | webfetch | 0 | yes | 1/1 | 0.0254 | 0.0000 | 16.3 | 2 | 13138 | 0 | 1 | 0 | 0 | b3e3c9e5be4c |
| subprocess-communicate-timeout | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0259 | 0.0035 | 10.3 | 2 | 13180 | 1 | 0 | 0 | 0 | b690896a391e |
| subprocess-communicate-timeout | medium | ko | webfetch | 1 | yes | 1/1 | 0.0320 | 0.0000 | 23.7 | 2 | 13810 | 0 | 1 | 0 | 0 | c63cca94ae0e |
| subprocess-run-timeout | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0241 | 0.0037 | 12.1 | 2 | 13172 | 1 | 0 | 0 | 0 | bf701d30ee88 |
| subprocess-run-timeout | medium | ko | webfetch | 0 | yes | 1/1 | 0.0300 | 0.0000 | 20.6 | 2 | 13338 | 0 | 1 | 0 | 0 | 4865e4208c3a |
| subprocess-run-timeout | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0250 | 0.0036 | 11.4 | 2 | 13168 | 1 | 0 | 0 | 0 | bae6aa5e6167 |
| subprocess-run-timeout | medium | ko | webfetch | 1 | yes | 1/1 | 0.0336 | 0.0000 | 25.0 | 2 | 13503 | 0 | 1 | 0 | 0 | de5f4cd4e40a |
| subprocess-shell-security | medium | ko | jevfetch | 0 | yes | 1/1 | 0.0300 | 0.0043 | 13.2 | 2 | 13983 | 1 | 0 | 0 | 0 | 0bee23c18a01 |
| subprocess-shell-security | medium | ko | webfetch | 0 | yes | 1/1 | 0.0351 | 0.0000 | 26.8 | 2 | 13509 | 0 | 1 | 0 | 0 | 35a04d2f8bc2 |
| subprocess-shell-security | medium | ko | jevfetch | 1 | yes | 1/1 | 0.0358 | 0.0046 | 13.6 | 2 | 14177 | 1 | 0 | 0 | 0 | b76da4e65be3 |
| subprocess-shell-security | medium | ko | webfetch | 1 | yes | 1/1 | 0.0434 | 0.0000 | 30.7 | 2 | 13786 | 0 | 1 | 0 | 0 | a220dd4eb312 |
| us-dst | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0297 | 0.0020 | 12.9 | 2 | 14294 | 1 | 0 | 0 | 0 | b60a649c0c0d |
| us-dst | medium | ko | webfetch | 0 | yes | 2/2 | 0.0454 | 0.0000 | 37.3 | 4 | 30114 | 0 | 1 | 2 | 0 | 68d6604db65d |
| us-dst | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0298 | 0.0022 | 12.1 | 2 | 14278 | 1 | 0 | 0 | 0 | 8a4beefe24e7 |
| us-dst | medium | ko | webfetch | 1 | yes | 2/2 | 0.0382 | 0.0000 | 28.5 | 2 | 13612 | 0 | 1 | 0 | 0 | 2e450a1e6fc4 |
| ww2-death-toll | large | ko | jevfetch | 0 | yes | 1/1 | 0.0309 | 0.0058 | 12.5 | 2 | 13899 | 1 | 0 | 0 | 0 | 40e254ad28dd |
| ww2-death-toll | large | ko | webfetch | 0 | yes | 1/1 | 0.0553 | 0.0000 | 40.3 | 4 | 29392 | 0 | 3 | 0 | 0 | 162beb819bd8 |
| ww2-death-toll | large | ko | jevfetch | 1 | yes | 1/1 | 0.0299 | 0.0057 | 14.0 | 2 | 13595 | 1 | 0 | 0 | 0 | 270908aad1d6 |
| ww2-death-toll | large | ko | webfetch | 1 | yes | 1/1 | 0.0370 | 0.0000 | 20.8 | 4 | 27421 | 0 | 1 | 2 | 0 | d14a3f820f81 |
| ww2-start-date | large | ko | jevfetch | 0 | yes | 1/1 | 0.0444 | 0.0062 | 13.1 | 2 | 16890 | 1 | 0 | 0 | 0 | 14ff31214c9d |
| ww2-start-date | large | ko | webfetch | 0 | yes | 1/1 | 0.0241 | 0.0000 | 14.0 | 2 | 12589 | 0 | 1 | 0 | 0 | 91814e53b855 |
| ww2-start-date | large | ko | jevfetch | 1 | yes | 1/1 | 0.0397 | 0.0063 | 13.0 | 2 | 16883 | 1 | 0 | 0 | 0 | e57b9c15f550 |
| ww2-start-date | large | ko | webfetch | 1 | yes | 1/1 | 0.0214 | 0.0000 | 14.2 | 2 | 12620 | 0 | 1 | 0 | 0 | 0f3b61bfcfb5 |
| ww2-un-founded | large | ko | jevfetch | 0 | yes | 1/1 | 0.0223 | 0.0053 | 9.1 | 2 | 12949 | 1 | 0 | 0 | 0 | 6317c89b3c78 |
| ww2-un-founded | large | ko | webfetch | 0 | yes | 1/1 | 0.0330 | 0.0000 | 19.4 | 4 | 26959 | 0 | 1 | 2 | 0 | c1815f23c981 |
| ww2-un-founded | large | ko | jevfetch | 1 | yes | 1/1 | 0.0197 | 0.0053 | 10.4 | 2 | 12957 | 1 | 0 | 0 | 0 | d1f985bda8cf |
| ww2-un-founded | large | ko | webfetch | 1 | yes | 1/1 | 0.0368 | 0.0000 | 19.6 | 4 | 19800 | 0 | 3 | 0 | 0 | 534163084384 |

