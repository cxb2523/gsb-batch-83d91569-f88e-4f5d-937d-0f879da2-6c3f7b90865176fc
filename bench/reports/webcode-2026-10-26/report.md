# Agent-level comparison, 2026-10-26

- The webfetch-only runs are reused from a run of 2026-10-25 (revision 75aad58 with uncommitted changes); only the jevfetch-only runs were made on 2026-10-26. The arm order below was randomized in the 2026-10-25 run; on 2026-10-26 the jevfetch-only runs ran alone in the same question order.

- Claude Code `claude --version`: 2.1.310 (Claude Code); versions seen in traces: 2.1.310; orchestrator model: sonnet; models billed: claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.14.0
- jevfetch revision 75aad58, ab8905b (uncommitted changes in jevfetch/ or skills/); instruction sha1 recorded at run time: webfetch-only ['fc609d4f0c'], jevfetch-only ['069e744610']; allowed tools: webfetch-only ['WebFetch']; jevfetch-only ['Bash(jevfetch:*)']
- mode: URL given, no WebSearch; question language: en; small model override: None
- questions: 137; runs per arm: webfetch-only 137, jevfetch-only 137; schedule seed 7; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch-only: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check), jevfetch-only: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 1 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch-only | 126/137 | 137/137 | 0.0149 | 0.0131 | 0.0018 | 0.0000 | 12.1 | 12.5 | 2.17 | 9447 | 505 | 1.17 | 0 (0) | 0 |
| jevfetch-only | 136/137 | 137/137 | 0.0180 | 0.0168 | 0.0000 | 0.0011 | 8.1 | 8.7 | 2.01 | 12647 | 496 | 1.01 | 0 (0) | 1 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch-only, cost ratio: 1.20 (interval 1.13 to 1.28), i.e. 20% higher; 137 questions
- vs webfetch-only, mean-time ratio: 0.69 (interval 0.66 to 0.72); runs were executed one at a time (concurrency 1)
- vs webfetch-only, facts right per run, difference: +0.07 (interval +0.03 to +0.12)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | en | 8 | webfetch-only | 7/8 | 0.0172 | 0.0126 | 0.0046 | 0.0000 | 13.5 | 2.12 | 9061 | 539 | 1.12 | 0 (0) |  |  |
| large | en | 8 | jevfetch-only | 8/8 | 0.0232 | 0.0175 | 0.0000 | 0.0057 | 8.9 | 2.12 | 13431 | 514 | 1.12 | 0 (0) | 1.35 (1.21 to 1.48) | 0.79 (0.62 to 1.02) |
| medium | en | 46 | webfetch-only | 43/46 | 0.0159 | 0.0134 | 0.0025 | 0.0000 | 12.0 | 2.22 | 9695 | 515 | 1.22 | 0 (0) |  |  |
| medium | en | 46 | jevfetch-only | 46/46 | 0.0180 | 0.0165 | 0.0000 | 0.0015 | 8.2 | 2.00 | 12464 | 506 | 1.00 | 0 (0) | 1.13 (1.01 to 1.23) | 0.66 (0.60 to 0.73) |
| small | en | 83 | webfetch-only | 76/83 | 0.0142 | 0.0129 | 0.0012 | 0.0000 | 11.6 | 2.14 | 9347 | 496 | 1.14 | 0 (0) |  |  |
| small | en | 83 | jevfetch-only | 82/83 | 0.0175 | 0.0170 | 0.0000 | 0.0005 | 8.1 | 2.00 | 12674 | 488 | 1.00 | 0 (0) | 1.23 (1.13 to 1.34) | 0.70 (0.66 to 0.73) |

## Judge votes that were not unanimous (8 of 274 judged runs; review by hand before publishing)

- highlights_029 jevfetch-only rep 0: f1#0
- highlights_046 webfetch-only rep 0: f1#0
- highlights_047 webfetch-only rep 0: f1#0
- highlights_097 webfetch-only rep 0: f1#0
- highlights_114 webfetch-only rep 0: f1#0
- highlights_200 webfetch-only rep 0: f1#0
- highlights_216 jevfetch-only rep 0: f1#0
- highlights_216 webfetch-only rep 0: f1#0

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| highlights_001 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0274 | 0.0000 | 8.7 | 2 | 15003 | 1 | 0 | 0 | 0 | 87753f037665 |
| highlights_001 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0144 | 0.0000 | 11.6 | 2 | 8605 | 0 | 1 | 0 | 0 | b169dad8bb29 |
| highlights_003 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0214 | 0.0000 | 6.5 | 2 | 14209 | 1 | 0 | 0 | 0 | 603f2807f2f3 |
| highlights_003 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0106 | 0.0000 | 10.8 | 2 | 8323 | 0 | 1 | 0 | 0 | e95ac7c393f2 |
| highlights_005 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0230 | 0.0016 | 7.8 | 2 | 13506 | 1 | 0 | 0 | 0 | 3aff638ea131 |
| highlights_005 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0250 | 0.0000 | 19.3 | 3 | 13514 | 0 | 2 | 0 | 0 | cc7246f4ba30 |
| highlights_006 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0185 | 0.0005 | 9.8 | 2 | 13002 | 1 | 0 | 0 | 0 | 631773b5dd4f |
| highlights_006 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0175 | 0.0000 | 12.7 | 3 | 13525 | 0 | 2 | 0 | 0 | 60a24c710a6e |
| highlights_011 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0148 | 0.0009 | 8.0 | 2 | 12007 | 1 | 0 | 0 | 0 | 2b19a279141d |
| highlights_011 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0135 | 0.0000 | 13.6 | 2 | 8509 | 0 | 1 | 0 | 0 | 28449ecd65b4 |
| highlights_015 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0134 | 0.0007 | 6.5 | 2 | 11885 | 1 | 0 | 0 | 0 | 4b96c27d5f56 |
| highlights_015 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0157 | 0.0000 | 13.7 | 3 | 12742 | 0 | 2 | 0 | 0 | db2ba55918fb |
| highlights_016 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0180 | 0.0003 | 9.9 | 2 | 12910 | 1 | 0 | 0 | 0 | 5d6c1a65ca45 |
| highlights_016 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0147 | 0.0000 | 14.7 | 2 | 8577 | 0 | 1 | 0 | 0 | d15c1096a599 |
| highlights_018 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0249 | 0.0000 | 7.9 | 2 | 14759 | 1 | 0 | 0 | 0 | 8cfd68a4c2f8 |
| highlights_018 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0107 | 0.0000 | 8.3 | 2 | 8314 | 0 | 1 | 0 | 0 | d2c8a4750320 |
| highlights_019 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0201 | 0.0046 | 7.7 | 3 | 17985 | 2 | 0 | 0 | 1 | d291ecd0c094 |
| highlights_019 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0137 | 0.0000 | 8.1 | 2 | 8319 | 0 | 1 | 0 | 0 | e2a0f87967f5 |
| highlights_021 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0232 | 0.0000 | 6.7 | 2 | 14609 | 1 | 0 | 0 | 0 | 99d771941e81 |
| highlights_021 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0100 | 0.0000 | 8.9 | 2 | 8245 | 0 | 1 | 0 | 0 | b1c0eb4087b7 |
| highlights_023 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0147 | 0.0005 | 10.5 | 2 | 12126 | 1 | 0 | 0 | 0 | 8a3bb7fd1ca3 |
| highlights_023 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0142 | 0.0000 | 10.3 | 3 | 12987 | 0 | 2 | 0 | 0 | 1ad5163b9ea4 |
| highlights_025 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0209 | 0.0058 | 7.9 | 2 | 12215 | 1 | 0 | 0 | 0 | 8dea14a41f03 |
| highlights_025 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0169 | 0.0000 | 10.1 | 2 | 8576 | 0 | 1 | 0 | 0 | 9c11c4c822fc |
| highlights_026 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0148 | 0.0008 | 7.3 | 2 | 12146 | 1 | 0 | 0 | 0 | 38cd468dc073 |
| highlights_026 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0103 | 0.0000 | 9.4 | 2 | 8282 | 0 | 1 | 0 | 0 | 263c98c26d33 |
| highlights_029 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0012 | 13.1 | 2 | 12264 | 1 | 0 | 0 | 0 | 1fb171de6b36 |
| highlights_029 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0138 | 0.0000 | 17.2 | 2 | 8456 | 0 | 1 | 0 | 0 | 671c1b5c1100 |
| highlights_032 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0159 | 0.0015 | 7.5 | 2 | 12166 | 1 | 0 | 0 | 0 | 8d642a391439 |
| highlights_032 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0122 | 0.0000 | 10.2 | 2 | 8405 | 0 | 1 | 0 | 0 | 9152d2f6b410 |
| highlights_033 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0177 | 0.0028 | 7.7 | 2 | 12026 | 1 | 0 | 0 | 0 | d5f7dd63386e |
| highlights_033 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0148 | 0.0000 | 15.3 | 2 | 8333 | 0 | 1 | 0 | 0 | e8aada6d2039 |
| highlights_035 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0187 | 0.0011 | 9.3 | 2 | 12478 | 1 | 0 | 0 | 0 | 10a214aef8ff |
| highlights_035 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0145 | 0.0000 | 14.3 | 2 | 8630 | 0 | 1 | 0 | 0 | 32f767e8e9c1 |
| highlights_037 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0171 | 0.0003 | 9.8 | 2 | 12525 | 1 | 0 | 0 | 0 | e9d240cb205d |
| highlights_037 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0129 | 0.0000 | 9.9 | 2 | 8509 | 0 | 1 | 0 | 0 | f6a92bc985bf |
| highlights_038 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0163 | 0.0004 | 8.9 | 2 | 12201 | 1 | 0 | 0 | 0 | ec3d8066c8c7 |
| highlights_038 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0000 | 13.1 | 3 | 13629 | 0 | 2 | 0 | 0 | 53826e1b8c67 |
| highlights_039 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0261 | 0.0000 | 8.1 | 2 | 14781 | 1 | 0 | 0 | 0 | f4b92eca276f |
| highlights_039 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0000 | 12.1 | 2 | 8442 | 0 | 1 | 0 | 0 | 03d84e126363 |
| highlights_040 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0178 | 0.0024 | 9.4 | 2 | 12096 | 1 | 0 | 0 | 0 | 26a531973ab7 |
| highlights_040 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0136 | 0.0000 | 12.1 | 2 | 8395 | 0 | 1 | 0 | 0 | 7b96cd9441d4 |
| highlights_041 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0015 | 8.6 | 2 | 12200 | 1 | 0 | 0 | 0 | 8511cd236aac |
| highlights_041 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0131 | 0.0000 | 12.2 | 2 | 8382 | 0 | 1 | 0 | 0 | e90676fc2f60 |
| highlights_045 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0147 | 0.0003 | 8.1 | 2 | 12082 | 1 | 0 | 0 | 0 | 865f53b9dc39 |
| highlights_045 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0176 | 0.0000 | 17.3 | 3 | 13053 | 0 | 2 | 0 | 0 | c1bc83244959 |
| highlights_046 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0152 | 0.0009 | 7.6 | 2 | 12153 | 1 | 0 | 0 | 0 | 69f2f4a2baa6 |
| highlights_046 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0116 | 0.0000 | 10.5 | 2 | 8359 | 0 | 1 | 0 | 0 | a195f2e33f5d |
| highlights_047 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0017 | 10.1 | 2 | 12107 | 1 | 0 | 0 | 0 | 4400be77291e |
| highlights_047 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0136 | 0.0000 | 13.8 | 2 | 8384 | 0 | 1 | 0 | 0 | 5540fbbf6629 |
| highlights_051 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0135 | 0.0005 | 8.3 | 2 | 12003 | 1 | 0 | 0 | 0 | 90a86b867432 |
| highlights_051 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0151 | 0.0000 | 13.0 | 3 | 13143 | 0 | 2 | 0 | 0 | 76c8d81fbeef |
| highlights_054 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0163 | 0.0017 | 7.2 | 2 | 12064 | 1 | 0 | 0 | 0 | 47b714edc282 |
| highlights_054 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0141 | 0.0000 | 13.0 | 2 | 8463 | 0 | 1 | 0 | 0 | b9195199a7f1 |
| highlights_057 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0015 | 7.1 | 2 | 12272 | 1 | 0 | 0 | 0 | 5a6287a6d8da |
| highlights_057 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0114 | 0.0000 | 8.8 | 2 | 8359 | 0 | 1 | 0 | 0 | 21367f8e7084 |
| highlights_058 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0147 | 0.0007 | 8.8 | 2 | 12012 | 1 | 0 | 0 | 0 | 93c552bb5768 |
| highlights_058 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0106 | 0.0000 | 8.3 | 2 | 8288 | 0 | 1 | 0 | 0 | 78268d742566 |
| highlights_059 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0158 | 0.0017 | 10.2 | 2 | 12044 | 1 | 0 | 0 | 0 | 1b8b2c52f7d1 |
| highlights_059 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0131 | 0.0000 | 10.5 | 2 | 8372 | 0 | 1 | 0 | 0 | 27f84fe49ea3 |
| highlights_062 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0171 | 0.0006 | 7.7 | 2 | 12463 | 1 | 0 | 0 | 0 | ce7053c6bd24 |
| highlights_062 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0000 | 12.4 | 2 | 8726 | 0 | 1 | 0 | 0 | 63e4b735ebb9 |
| highlights_063 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0150 | 0.0011 | 7.5 | 2 | 12128 | 1 | 0 | 0 | 0 | 3d8ec720c6c4 |
| highlights_063 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0401 | 0.0000 | 6.5 | 2 | 15542 | 0 | 1 | 0 | 0 | 8be6aee08208 |
| highlights_064 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0010 | 8.2 | 2 | 11938 | 1 | 0 | 0 | 0 | c418affafc40 |
| highlights_064 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0128 | 0.0000 | 11.5 | 2 | 8399 | 0 | 1 | 0 | 0 | 7c827eb48ef2 |
| highlights_066 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0188 | 0.0000 | 7.3 | 2 | 13150 | 1 | 0 | 0 | 0 | e45bbf4acd2f |
| highlights_066 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0119 | 0.0000 | 11.4 | 2 | 8378 | 0 | 1 | 0 | 0 | 6fedc8827fcd |
| highlights_067 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0162 | 0.0008 | 7.9 | 2 | 12197 | 1 | 0 | 0 | 0 | b9637a4371d1 |
| highlights_067 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0129 | 0.0000 | 10.8 | 2 | 8447 | 0 | 1 | 0 | 0 | c1a55eac43e7 |
| highlights_072 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0011 | 7.6 | 2 | 12074 | 1 | 0 | 0 | 0 | d7928cb630a3 |
| highlights_072 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0124 | 0.0000 | 11.4 | 2 | 8423 | 0 | 1 | 0 | 0 | 2ddc8f8500ca |
| highlights_074 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0223 | 0.0000 | 9.2 | 2 | 13477 | 1 | 0 | 0 | 0 | ae54a76072f2 |
| highlights_074 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0119 | 0.0000 | 12.6 | 2 | 8426 | 0 | 1 | 0 | 0 | bff745eff9bf |
| highlights_077 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0166 | 0.0007 | 8.3 | 2 | 12367 | 1 | 0 | 0 | 0 | b52311e69bd1 |
| highlights_077 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0131 | 0.0000 | 11.8 | 2 | 8418 | 0 | 1 | 0 | 0 | 0878941788a5 |
| highlights_078 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0004 | 8.1 | 2 | 12305 | 1 | 0 | 0 | 0 | 8c6ed7223e66 |
| highlights_078 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0138 | 0.0000 | 13.2 | 2 | 8552 | 0 | 1 | 0 | 0 | 103c65a05506 |
| highlights_080 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0307 | 0.0117 | 7.9 | 2 | 13397 | 1 | 0 | 0 | 0 | fbafafb48fbf |
| highlights_080 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0227 | 0.0000 | 16.4 | 3 | 13139 | 0 | 2 | 0 | 0 | fda86c569631 |
| highlights_081 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0186 | 0.0030 | 12.9 | 2 | 12369 | 1 | 0 | 0 | 0 | 6aad66f99303 |
| highlights_081 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0129 | 0.0000 | 11.6 | 2 | 8355 | 0 | 1 | 0 | 0 | 7e672cc28602 |
| highlights_082 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0167 | 0.0016 | 7.1 | 2 | 12411 | 1 | 0 | 0 | 0 | d84631c0a979 |
| highlights_082 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0139 | 0.0000 | 11.1 | 2 | 8297 | 0 | 1 | 0 | 0 | 60f6e2e8f109 |
| highlights_083 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0270 | 0.0019 | 17.0 | 2 | 12560 | 1 | 0 | 0 | 0 | 517460b0bec9 |
| highlights_083 | medium | en | webfetch-only | 0 | yes | 0/1 | 0.0174 | 0.0000 | 20.4 | 3 | 13275 | 0 | 2 | 0 | 0 | 522fcffbfc16 |
| highlights_085 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0003 | 7.6 | 2 | 12159 | 1 | 0 | 0 | 0 | 2e7101a9062f |
| highlights_085 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0190 | 0.0000 | 10.7 | 2 | 8713 | 0 | 1 | 0 | 0 | a5dffea33cd9 |
| highlights_086 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0000 | 9.0 | 2 | 12946 | 1 | 0 | 0 | 0 | 6d573121c786 |
| highlights_086 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0129 | 0.0000 | 11.9 | 2 | 8509 | 0 | 1 | 0 | 0 | 8749fd290313 |
| highlights_090 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0002 | 6.8 | 2 | 12621 | 1 | 0 | 0 | 0 | b3e9d9e22094 |
| highlights_090 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0103 | 0.0000 | 8.4 | 2 | 8282 | 0 | 1 | 0 | 0 | 9cbbbcab2ae0 |
| highlights_091 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0192 | 0.0036 | 9.1 | 2 | 12256 | 1 | 0 | 0 | 0 | b9cd6e6c4f0e |
| highlights_091 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0136 | 0.0000 | 12.8 | 2 | 8359 | 0 | 1 | 0 | 0 | 3178636d485a |
| highlights_092 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0183 | 0.0006 | 8.8 | 2 | 12682 | 1 | 0 | 0 | 0 | 8c6aeecf6579 |
| highlights_092 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0205 | 0.0000 | 13.4 | 3 | 13865 | 0 | 2 | 0 | 0 | c432fa448e3e |
| highlights_093 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0171 | 0.0007 | 7.9 | 2 | 12283 | 1 | 0 | 0 | 0 | d0070b38a51a |
| highlights_093 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0124 | 0.0000 | 10.0 | 2 | 8450 | 0 | 1 | 0 | 0 | c35384110a39 |
| highlights_095 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0233 | 0.0000 | 7.1 | 2 | 14304 | 1 | 0 | 0 | 0 | 4deb23cc6488 |
| highlights_095 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0192 | 0.0000 | 14.2 | 3 | 13680 | 0 | 2 | 0 | 0 | ced9ff2956e0 |
| highlights_096 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0194 | 0.0010 | 8.4 | 2 | 12617 | 1 | 0 | 0 | 0 | 37d3a64da633 |
| highlights_096 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0162 | 0.0000 | 13.3 | 2 | 8719 | 0 | 1 | 0 | 0 | b6172c5fe688 |
| highlights_097 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0153 | 0.0004 | 11.1 | 2 | 11979 | 1 | 0 | 0 | 0 | 1f7dd3d1e6ce |
| highlights_097 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0134 | 0.0000 | 14.4 | 2 | 8426 | 0 | 1 | 0 | 0 | 9de63b8b1a1e |
| highlights_099 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0179 | 0.0017 | 9.5 | 2 | 12214 | 1 | 0 | 0 | 0 | f268e3099855 |
| highlights_099 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0172 | 0.0000 | 11.8 | 2 | 8712 | 0 | 1 | 0 | 0 | f12f8f41beed |
| highlights_100 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0005 | 9.1 | 2 | 12301 | 1 | 0 | 0 | 0 | 22e9dde90e43 |
| highlights_100 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0112 | 0.0000 | 10.3 | 2 | 8308 | 0 | 1 | 0 | 0 | 51c0c3e812cd |
| highlights_101 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0168 | 0.0013 | 7.0 | 2 | 12155 | 1 | 0 | 0 | 0 | 01ef0373efad |
| highlights_101 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0161 | 0.0000 | 26.3 | 2 | 8468 | 0 | 1 | 0 | 0 | fd144d9134b6 |
| highlights_102 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0221 | 0.0000 | 8.1 | 2 | 13286 | 1 | 0 | 0 | 0 | 35162ef7b62a |
| highlights_102 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0141 | 0.0000 | 13.1 | 2 | 8642 | 0 | 1 | 0 | 0 | 2956f4c763e1 |
| highlights_104 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0162 | 0.0011 | 8.2 | 2 | 12538 | 1 | 0 | 0 | 0 | 839767e5b63b |
| highlights_104 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0124 | 0.0000 | 9.9 | 2 | 8377 | 0 | 1 | 0 | 0 | 99bee84ae0dd |
| highlights_107 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0201 | 0.0013 | 9.0 | 2 | 13204 | 1 | 0 | 0 | 0 | af6c727a4a1e |
| highlights_107 | medium | en | webfetch-only | 0 | yes | 0/1 | 0.0126 | 0.0000 | 11.6 | 3 | 12835 | 0 | 2 | 0 | 0 | 43db0fc3dfff |
| highlights_109 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0219 | 0.0000 | 13.4 | 2 | 13795 | 1 | 0 | 0 | 0 | 357dbb3b4701 |
| highlights_109 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0123 | 0.0000 | 15.2 | 2 | 8443 | 0 | 1 | 0 | 0 | fe22be1b36bd |
| highlights_110 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0149 | 0.0011 | 7.2 | 2 | 12168 | 1 | 0 | 0 | 0 | 19db144ef85d |
| highlights_110 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0110 | 0.0000 | 10.1 | 2 | 8319 | 0 | 1 | 0 | 0 | 4fec5450f480 |
| highlights_114 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0203 | 0.0009 | 7.9 | 2 | 13265 | 1 | 0 | 0 | 0 | 0f904507dd5a |
| highlights_114 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0159 | 0.0000 | 14.8 | 2 | 8585 | 0 | 1 | 0 | 0 | 4ef02f4e67c7 |
| highlights_117 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0007 | 7.4 | 2 | 12257 | 1 | 0 | 0 | 0 | 72177c15f5af |
| highlights_117 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0151 | 0.0000 | 14.9 | 2 | 8592 | 0 | 1 | 0 | 0 | c66813e45efb |
| highlights_120 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0150 | 0.0005 | 12.4 | 2 | 12368 | 1 | 0 | 0 | 0 | c4ed934c41c6 |
| highlights_120 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0110 | 0.0000 | 18.0 | 2 | 8358 | 0 | 1 | 0 | 0 | 65738da54f7f |
| highlights_121 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0007 | 7.8 | 2 | 12326 | 1 | 0 | 0 | 0 | ed4c270ad253 |
| highlights_121 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0133 | 0.0000 | 11.1 | 2 | 8432 | 0 | 1 | 0 | 0 | e76da0daffa7 |
| highlights_122 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0185 | 0.0029 | 11.4 | 2 | 12413 | 1 | 0 | 0 | 0 | b28059d7303a |
| highlights_122 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0000 | 22.5 | 2 | 8639 | 0 | 1 | 0 | 0 | 459429731153 |
| highlights_124 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0264 | 0.0011 | 9.4 | 2 | 14323 | 1 | 0 | 0 | 0 | 1e69fd6c5c01 |
| highlights_124 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0258 | 0.0000 | 11.0 | 2 | 8569 | 0 | 1 | 0 | 0 | 722ba1f46bd2 |
| highlights_126 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0140 | 0.0003 | 8.1 | 2 | 12057 | 1 | 0 | 0 | 0 | 908c3971963a |
| highlights_126 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0113 | 0.0000 | 13.0 | 2 | 8290 | 0 | 1 | 0 | 0 | d2ca7893e14a |
| highlights_127 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0232 | 0.0000 | 6.5 | 2 | 14470 | 1 | 0 | 0 | 0 | 2406f3a8c932 |
| highlights_127 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0106 | 0.0000 | 10.9 | 2 | 8322 | 0 | 1 | 0 | 0 | 218bd77a500b |
| highlights_128 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0258 | 0.0000 | 9.1 | 2 | 14767 | 1 | 0 | 0 | 0 | a9f1f656c47f |
| highlights_128 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0216 | 0.0000 | 16.8 | 3 | 13955 | 0 | 2 | 0 | 0 | 60494c32f701 |
| highlights_129 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0005 | 8.4 | 2 | 12268 | 1 | 0 | 0 | 0 | 765862278253 |
| highlights_129 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0151 | 0.0000 | 13.7 | 2 | 8627 | 0 | 1 | 0 | 0 | 971157ef0932 |
| highlights_130 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0008 | 7.4 | 2 | 12250 | 1 | 0 | 0 | 0 | 17db11afcdbc |
| highlights_130 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0122 | 0.0000 | 11.0 | 2 | 8422 | 0 | 1 | 0 | 0 | 58c3d8a934b6 |
| highlights_131 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0168 | 0.0004 | 7.9 | 2 | 12404 | 1 | 0 | 0 | 0 | 8c9fc2b8f90c |
| highlights_131 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0130 | 0.0000 | 9.3 | 2 | 8526 | 0 | 1 | 0 | 0 | 45fb1676dba5 |
| highlights_133 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0005 | 5.8 | 2 | 11906 | 1 | 0 | 0 | 0 | e163d9bf0245 |
| highlights_133 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0113 | 0.0000 | 12.7 | 2 | 8220 | 0 | 1 | 0 | 0 | e4830139c34a |
| highlights_135 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0138 | 0.0003 | 6.8 | 2 | 12358 | 1 | 0 | 0 | 0 | c54f4fb0d7c5 |
| highlights_135 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0111 | 0.0000 | 8.8 | 2 | 8274 | 0 | 1 | 0 | 0 | 87e8060c0273 |
| highlights_136 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0161 | 0.0008 | 7.8 | 2 | 12255 | 1 | 0 | 0 | 0 | 6f7840c15f98 |
| highlights_136 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0156 | 0.0000 | 13.7 | 2 | 8583 | 0 | 1 | 0 | 0 | ad813a7dd7f2 |
| highlights_137 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0213 | 0.0011 | 11.0 | 2 | 12541 | 1 | 0 | 0 | 0 | 11a7c7b00f8c |
| highlights_137 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0131 | 0.0000 | 11.1 | 2 | 8465 | 0 | 1 | 0 | 0 | ab0c8d01b855 |
| highlights_138 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0164 | 0.0006 | 9.1 | 2 | 12030 | 1 | 0 | 0 | 0 | fa1147ccdee6 |
| highlights_138 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0124 | 0.0000 | 10.7 | 2 | 8368 | 0 | 1 | 0 | 0 | a406a516dab7 |
| highlights_139 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0159 | 0.0006 | 10.1 | 2 | 12255 | 1 | 0 | 0 | 0 | 3f0b13e2ddf3 |
| highlights_139 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0138 | 0.0000 | 12.2 | 2 | 8509 | 0 | 1 | 0 | 0 | 20f34e966f46 |
| highlights_142 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0236 | 0.0000 | 7.3 | 2 | 14418 | 1 | 0 | 0 | 0 | c5ba0bc2a497 |
| highlights_142 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0000 | 14.8 | 2 | 8412 | 0 | 1 | 0 | 0 | 72f25dfc4f05 |
| highlights_146 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0007 | 8.7 | 2 | 12024 | 1 | 0 | 0 | 0 | 2db30d7b82a7 |
| highlights_146 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0096 | 0.0000 | 8.6 | 2 | 8262 | 0 | 1 | 0 | 0 | 08e21d1513f0 |
| highlights_148 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0164 | 0.0005 | 8.7 | 2 | 12326 | 1 | 0 | 0 | 0 | 5c149adbfea1 |
| highlights_148 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0126 | 0.0000 | 9.9 | 2 | 8471 | 0 | 1 | 0 | 0 | 4a4c2b18fb58 |
| highlights_149 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0200 | 0.0004 | 9.7 | 2 | 12842 | 1 | 0 | 0 | 0 | 2619784dd36a |
| highlights_149 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0158 | 0.0000 | 16.7 | 2 | 8580 | 0 | 1 | 0 | 0 | de12f2ec52f1 |
| highlights_153 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0012 | 7.2 | 2 | 12122 | 1 | 0 | 0 | 0 | 41b3b3b5d651 |
| highlights_153 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0441 | 0.0000 | 6.2 | 2 | 16734 | 0 | 1 | 0 | 0 | a41453f96030 |
| highlights_154 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0182 | 0.0006 | 10.2 | 2 | 12269 | 1 | 0 | 0 | 0 | 783f1b94a7bc |
| highlights_154 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0165 | 0.0000 | 12.5 | 2 | 8725 | 0 | 1 | 0 | 0 | 863d458dc44e |
| highlights_155 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0163 | 0.0007 | 11.9 | 2 | 12545 | 1 | 0 | 0 | 0 | d3b152494745 |
| highlights_155 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0000 | 13.8 | 2 | 8450 | 0 | 1 | 0 | 0 | bacdda852096 |
| highlights_159 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0141 | 0.0004 | 6.2 | 2 | 12198 | 1 | 0 | 0 | 0 | c9fc53f88737 |
| highlights_159 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0244 | 0.0000 | 6.9 | 2 | 11757 | 0 | 1 | 0 | 0 | f1a7c2b98846 |
| highlights_160 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0021 | 8.6 | 2 | 12079 | 1 | 0 | 0 | 0 | 231d5740e902 |
| highlights_160 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0178 | 0.0000 | 12.7 | 2 | 8799 | 0 | 1 | 0 | 0 | 1e0ccc909110 |
| highlights_161 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0005 | 10.2 | 2 | 12053 | 1 | 0 | 0 | 0 | 1719755a5bdb |
| highlights_161 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0139 | 0.0000 | 12.2 | 2 | 8536 | 0 | 1 | 0 | 0 | e6d5590cd02f |
| highlights_163 | small | en | jevfetch-only | 0 | yes | 0/1 | 0.0165 | 0.0009 | 8.1 | 2 | 12381 | 1 | 0 | 0 | 0 | 1d501a6148c0 |
| highlights_163 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0179 | 0.0000 | 17.1 | 3 | 12958 | 0 | 2 | 0 | 0 | 38c6dbcd81b1 |
| highlights_165 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0005 | 7.9 | 2 | 12245 | 1 | 0 | 0 | 0 | 920f82b2c1af |
| highlights_165 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0126 | 0.0000 | 10.8 | 2 | 8484 | 0 | 1 | 0 | 0 | 8bb15d24de88 |
| highlights_166 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0159 | 0.0013 | 6.9 | 2 | 12319 | 1 | 0 | 0 | 0 | cbe62dc9f01c |
| highlights_166 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0125 | 0.0000 | 11.5 | 2 | 8421 | 0 | 1 | 0 | 0 | 10e3ef707582 |
| highlights_168 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0150 | 0.0005 | 8.1 | 2 | 12174 | 1 | 0 | 0 | 0 | 8d53825938ad |
| highlights_168 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0165 | 0.0000 | 12.2 | 3 | 13378 | 0 | 2 | 0 | 0 | 6f98efc9a460 |
| highlights_169 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0133 | 0.0005 | 7.7 | 2 | 11891 | 1 | 0 | 0 | 0 | 6a4b38bdfd37 |
| highlights_169 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0177 | 0.0000 | 18.0 | 3 | 12931 | 0 | 2 | 0 | 0 | f2ce96abc4d8 |
| highlights_172 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0191 | 0.0011 | 9.1 | 2 | 12616 | 1 | 0 | 0 | 0 | b82628d6826e |
| highlights_172 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0126 | 0.0000 | 9.7 | 2 | 8430 | 0 | 1 | 0 | 0 | 16d85305ab1f |
| highlights_174 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0009 | 7.1 | 2 | 12184 | 1 | 0 | 0 | 0 | 8deb53598c15 |
| highlights_174 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0109 | 0.0000 | 9.2 | 2 | 8309 | 0 | 1 | 0 | 0 | f4a00dae431b |
| highlights_178 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0177 | 0.0006 | 8.5 | 2 | 12487 | 1 | 0 | 0 | 0 | ffc029496144 |
| highlights_178 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0108 | 0.0000 | 7.4 | 2 | 8338 | 0 | 1 | 0 | 0 | ad33784440aa |
| highlights_179 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0190 | 0.0007 | 8.7 | 2 | 12702 | 1 | 0 | 0 | 0 | a639d90e1013 |
| highlights_179 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0151 | 0.0000 | 12.8 | 2 | 8614 | 0 | 1 | 0 | 0 | 4e13c29302c1 |
| highlights_180 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0146 | 0.0008 | 7.2 | 2 | 12105 | 1 | 0 | 0 | 0 | da057d868e3f |
| highlights_180 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0246 | 0.0000 | 21.6 | 4 | 18149 | 0 | 3 | 0 | 0 | 69467bd7c557 |
| highlights_181 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0182 | 0.0016 | 7.9 | 2 | 12497 | 1 | 0 | 0 | 0 | 897098d10f5f |
| highlights_181 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0000 | 11.6 | 2 | 8659 | 0 | 1 | 0 | 0 | b03ad87af138 |
| highlights_182 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0165 | 0.0017 | 8.2 | 2 | 12372 | 1 | 0 | 0 | 0 | 1a2123ee59ad |
| highlights_182 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0145 | 0.0000 | 11.0 | 2 | 8393 | 0 | 1 | 0 | 0 | 5f8393697b4f |
| highlights_183 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0321 | 0.0140 | 11.3 | 2 | 12335 | 1 | 0 | 0 | 0 | 786cff354810 |
| highlights_183 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0193 | 0.0000 | 15.4 | 2 | 8607 | 0 | 1 | 0 | 0 | ec6d9bce5373 |
| highlights_184 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0180 | 0.0021 | 7.0 | 2 | 12571 | 1 | 0 | 0 | 0 | a61d52ccec1c |
| highlights_184 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0126 | 0.0000 | 9.1 | 2 | 8379 | 0 | 1 | 0 | 0 | a5f0dec2cbcc |
| highlights_186 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0183 | 0.0014 | 7.1 | 2 | 12843 | 1 | 0 | 0 | 0 | a90ab28f917d |
| highlights_186 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0113 | 0.0000 | 9.7 | 2 | 8264 | 0 | 1 | 0 | 0 | a059219bf5ee |
| highlights_191 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0259 | 0.0010 | 9.2 | 2 | 14476 | 1 | 0 | 0 | 0 | 3cfc01012c7a |
| highlights_191 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0000 | 15.0 | 2 | 8490 | 0 | 1 | 0 | 0 | a2bd8e5c8832 |
| highlights_192 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0014 | 8.2 | 2 | 12071 | 1 | 0 | 0 | 0 | 5c9fbe70da64 |
| highlights_192 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0203 | 0.0000 | 17.1 | 3 | 12971 | 0 | 2 | 0 | 0 | d5675b79f15a |
| highlights_194 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0189 | 0.0012 | 8.2 | 2 | 12656 | 1 | 0 | 0 | 0 | 923d657b32df |
| highlights_194 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0219 | 0.0000 | 22.4 | 3 | 13516 | 0 | 2 | 0 | 0 | 15541ee2e251 |
| highlights_196 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0190 | 0.0033 | 8.6 | 2 | 12555 | 1 | 0 | 0 | 0 | f830431fc434 |
| highlights_196 | large | en | webfetch-only | 0 | yes | 0/1 | 0.0142 | 0.0000 | 13.1 | 2 | 8389 | 0 | 1 | 0 | 0 | 81802d523936 |
| highlights_199 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0176 | 0.0007 | 10.3 | 2 | 12107 | 1 | 0 | 0 | 0 | eee612ce7ec1 |
| highlights_199 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0196 | 0.0000 | 19.5 | 2 | 9144 | 0 | 1 | 0 | 0 | e4c868ab7115 |
| highlights_200 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0146 | 0.0009 | 7.4 | 2 | 12214 | 1 | 0 | 0 | 0 | 69851c6f64e8 |
| highlights_200 | small | en | webfetch-only | 0 | yes | 0/1 | 0.0111 | 0.0000 | 13.7 | 2 | 8315 | 0 | 1 | 0 | 0 | d80b1403f25e |
| highlights_201 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0170 | 0.0007 | 9.8 | 2 | 12123 | 1 | 0 | 0 | 0 | 0dca37183bb0 |
| highlights_201 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0190 | 0.0000 | 15.9 | 2 | 8947 | 0 | 1 | 0 | 0 | 73369d941097 |
| highlights_202 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0146 | 0.0005 | 6.8 | 2 | 12063 | 1 | 0 | 0 | 0 | 49c16edcf8c5 |
| highlights_202 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0097 | 0.0000 | 10.4 | 2 | 8249 | 0 | 1 | 0 | 0 | 9728d2ab76b7 |
| highlights_206 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0144 | 0.0004 | 8.3 | 2 | 12183 | 1 | 0 | 0 | 0 | fc1570f76660 |
| highlights_206 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0107 | 0.0000 | 9.4 | 2 | 8267 | 0 | 1 | 0 | 0 | 91450fdf86ff |
| highlights_207 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0140 | 0.0006 | 6.3 | 2 | 12092 | 1 | 0 | 0 | 0 | 4c0c23fd0ed9 |
| highlights_207 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0360 | 0.0000 | 6.6 | 2 | 14556 | 0 | 1 | 0 | 0 | 7d0c537067f9 |
| highlights_208 | large | en | jevfetch-only | 0 | yes | 1/1 | 0.0176 | 0.0016 | 20.6 | 2 | 12227 | 1 | 0 | 0 | 0 | 013aac7cf2df |
| highlights_208 | large | en | webfetch-only | 0 | yes | 1/1 | 0.0187 | 0.0000 | 13.9 | 2 | 8610 | 0 | 1 | 0 | 0 | a9c936d6776e |
| highlights_209 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0155 | 0.0025 | 7.2 | 2 | 11978 | 1 | 0 | 0 | 0 | 088a81b96a02 |
| highlights_209 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0150 | 0.0000 | 12.6 | 2 | 8532 | 0 | 1 | 0 | 0 | c17b2cf539c8 |
| highlights_210 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0013 | 7.7 | 2 | 12766 | 1 | 0 | 0 | 0 | f70189d2e6e0 |
| highlights_210 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0143 | 0.0000 | 10.5 | 2 | 8428 | 0 | 1 | 0 | 0 | f975f3189aa5 |
| highlights_211 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0168 | 0.0015 | 14.6 | 2 | 12385 | 1 | 0 | 0 | 0 | a6ebe25d0478 |
| highlights_211 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0125 | 0.0000 | 11.5 | 2 | 8357 | 0 | 1 | 0 | 0 | a94628dd2e70 |
| highlights_215 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0234 | 0.0000 | 6.8 | 2 | 14337 | 1 | 0 | 0 | 0 | d4eae4816de2 |
| highlights_215 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0000 | 11.4 | 2 | 8340 | 0 | 1 | 0 | 0 | b5773ee9d42b |
| highlights_216 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0172 | 0.0011 | 10.2 | 2 | 12031 | 1 | 0 | 0 | 0 | 186274257bb4 |
| highlights_216 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0148 | 0.0000 | 13.3 | 2 | 8441 | 0 | 1 | 0 | 0 | 88c5842741fa |
| highlights_217 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0262 | 0.0005 | 9.9 | 2 | 14220 | 1 | 0 | 0 | 0 | 51ba07b33c4d |
| highlights_217 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0163 | 0.0000 | 17.2 | 2 | 8645 | 0 | 1 | 0 | 0 | b7a278d6f924 |
| highlights_218 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0205 | 0.0000 | 6.1 | 2 | 13796 | 1 | 0 | 0 | 0 | f9f9b3046797 |
| highlights_218 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0108 | 0.0000 | 8.7 | 2 | 8359 | 0 | 1 | 0 | 0 | 99cc50f3a5b6 |
| highlights_219 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0154 | 0.0006 | 8.8 | 2 | 12181 | 1 | 0 | 0 | 0 | f8b84a51054d |
| highlights_219 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0123 | 0.0000 | 10.5 | 2 | 8417 | 0 | 1 | 0 | 0 | 7f08c81f6876 |
| highlights_221 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0218 | 0.0000 | 7.9 | 2 | 13820 | 1 | 0 | 0 | 0 | 96bcb8a9e719 |
| highlights_221 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0117 | 0.0000 | 12.1 | 2 | 8419 | 0 | 1 | 0 | 0 | c97d885fddb3 |
| highlights_225 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0162 | 0.0016 | 8.0 | 2 | 12051 | 1 | 0 | 0 | 0 | 3eb8cf59816a |
| highlights_225 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0167 | 0.0000 | 11.1 | 3 | 13336 | 0 | 2 | 0 | 0 | 030a9505cb5f |
| highlights_230 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0007 | 8.9 | 2 | 12298 | 1 | 0 | 0 | 0 | 0a9dae5a5f5d |
| highlights_230 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0119 | 0.0000 | 9.8 | 2 | 8392 | 0 | 1 | 0 | 0 | e588f3116c7d |
| highlights_231 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0189 | 0.0005 | 8.2 | 2 | 13201 | 1 | 0 | 0 | 0 | 835334b7a571 |
| highlights_231 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0133 | 0.0000 | 11.5 | 2 | 8482 | 0 | 1 | 0 | 0 | 9a1ce1f33603 |
| highlights_233 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0201 | 0.0000 | 8.1 | 2 | 13287 | 1 | 0 | 0 | 0 | 1ecf2f7183a1 |
| highlights_233 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0135 | 0.0000 | 19.1 | 2 | 8544 | 0 | 1 | 0 | 0 | 531fe76cc87a |
| highlights_234 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0180 | 0.0015 | 7.9 | 2 | 12439 | 1 | 0 | 0 | 0 | 17494edf7cd0 |
| highlights_234 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0146 | 0.0000 | 12.5 | 2 | 8598 | 0 | 1 | 0 | 0 | 5d023a2c855a |
| highlights_235 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0252 | 0.0012 | 8.9 | 2 | 14000 | 1 | 0 | 0 | 0 | 1dd5aafd339b |
| highlights_235 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0000 | 14.8 | 2 | 8697 | 0 | 1 | 0 | 0 | 992e36c5f89b |
| highlights_236 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0164 | 0.0010 | 9.1 | 2 | 12129 | 1 | 0 | 0 | 0 | 8a3f2be101de |
| highlights_236 | medium | en | webfetch-only | 0 | yes | 0/1 | 0.0133 | 0.0000 | 10.4 | 3 | 12928 | 0 | 2 | 0 | 0 | e2d57798dfba |
| highlights_237 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0160 | 0.0007 | 7.7 | 2 | 12474 | 1 | 0 | 0 | 0 | 7f652910fdbe |
| highlights_237 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0121 | 0.0000 | 10.0 | 2 | 8273 | 0 | 1 | 0 | 0 | 17943b5b8024 |
| highlights_240 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0149 | 0.0007 | 12.0 | 2 | 12062 | 1 | 0 | 0 | 0 | 4c23c2cea4bb |
| highlights_240 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0123 | 0.0000 | 15.6 | 2 | 8423 | 0 | 1 | 0 | 0 | fe0b84b89e4f |
| highlights_243 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0181 | 0.0009 | 8.1 | 2 | 12609 | 1 | 0 | 0 | 0 | 6889fa6ea907 |
| highlights_243 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0153 | 0.0000 | 12.4 | 2 | 8620 | 0 | 1 | 0 | 0 | a17f453f6f09 |
| highlights_246 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0123 | 0.0004 | 7.3 | 2 | 11882 | 1 | 0 | 0 | 0 | 4f077b1e7453 |
| highlights_246 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0131 | 0.0000 | 10.4 | 3 | 13014 | 0 | 2 | 0 | 0 | e08e23c1f74a |
| highlights_247 | medium | en | jevfetch-only | 0 | yes | 1/1 | 0.0164 | 0.0013 | 7.8 | 2 | 12311 | 1 | 0 | 0 | 0 | ecfeee720e5a |
| highlights_247 | medium | en | webfetch-only | 0 | yes | 1/1 | 0.0140 | 0.0000 | 16.7 | 2 | 8534 | 0 | 1 | 0 | 0 | 7af47ab3f041 |
| highlights_248 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0145 | 0.0009 | 7.1 | 2 | 12028 | 1 | 0 | 0 | 0 | ba3de3757c20 |
| highlights_248 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0115 | 0.0000 | 8.9 | 2 | 8313 | 0 | 1 | 0 | 0 | e6f8b4a46251 |
| highlights_249 | small | en | jevfetch-only | 0 | yes | 1/1 | 0.0173 | 0.0007 | 10.0 | 2 | 12340 | 1 | 0 | 0 | 0 | 57ee8c2e61da |
| highlights_249 | small | en | webfetch-only | 0 | yes | 1/1 | 0.0111 | 0.0000 | 10.3 | 2 | 8370 | 0 | 1 | 0 | 0 | 841f2180ffa7 |

