# Agent-level comparison, 2026-10-09

- Claude Code `claude --version`: 2.1.295 (Claude Code); versions seen in traces: 2.1.295; orchestrator model: sonnet; models billed: claude-haiku-5-5, claude-sonnet-5-5; Jev models: jev-1.13.0
- jevfetch revision 8d38867; instruction sha1 recorded at run time: webfetch ['c732ccb62d'], jevfetch ['569edd574c']; allowed tools: webfetch ['WebSearch WebFetch Bash(curl:*) Bash(grep:*) Bash(head:*)']; jevfetch ['WebSearch Bash(curl:*) Bash(grep:*) Bash(head:*) Bash(jevfetch:*)']
- mode: no URL, WebSearch; question language: ko; small model override: None
- questions: 20; runs per arm: webfetch 40, jevfetch 40; schedule seed None; bootstrap seed 0; arm order randomized within each (question, repetition) block, block order random
- failures: webfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 3 runs with a Bash command refused (allow rules or variable check), jevfetch: 0 unfinished, 0 timed out, 0 hit the turn limit, 0 retried API errors ($0.0000 spent on failed attempts, not in the means), 0 runs with a Bash command refused (allow rules or variable check)
- all finished runs graded
- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, the Jev input tokens actually sent during the run (one recording per request in the run's own cache) at $0.042/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: WebFetch's reader and Claude Code's own background calls, which occur in both arms.

## Summary

| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model | of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens | main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| webfetch | 100/102 | 40/40 | 0.0556 | 0.0458 | 0.0098 | 0.0000 | 26.2 | 28.2 | 4.08 | 23559 | 2002 | 2.17 | 32 (9) | 3 |
| jevfetch | 102/102 | 40/40 | 0.0558 | 0.0430 | 0.0073 | 0.0054 | 20.1 | 23.4 | 3.25 | 20599 | 1749 | 1.82 | 1 (1) | 0 |

## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)

- vs webfetch, cost ratio: 1.00 (interval 0.89 to 1.12), i.e. 0% higher; 20 questions
- vs webfetch, mean-time ratio: 0.83 (interval 0.73 to 0.93); runs were executed with concurrency 2, so this is not single-session latency
- vs webfetch, facts right per run, difference: +0.05 (interval +0.00 to +0.15)

## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language

| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns | main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) | mean-time ratio (interval) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| large | ko | 3 | webfetch | 16/16 | 0.0625 | 0.0539 | 0.0086 | 0.0000 | 32.9 | 6.33 | 40884 | 2385 | 2.17 | 27 (6) |  |  |
| large | ko | 3 | jevfetch | 16/16 | 0.0696 | 0.0457 | 0.0041 | 0.0198 | 22.0 | 3.67 | 19926 | 1971 | 2.50 | 0 (0) | 1.11 (0.88 to 1.59) | 0.66 (0.60 to 0.79) |
| medium | ko | 11 | webfetch | 54/56 | 0.0618 | 0.0492 | 0.0126 | 0.0000 | 27.2 | 3.77 | 21624 | 2089 | 2.14 | 4 (2) |  |  |
| medium | ko | 11 | jevfetch | 56/56 | 0.0633 | 0.0493 | 0.0100 | 0.0040 | 23.3 | 3.64 | 23304 | 1938 | 2.09 | 1 (1) | 1.02 (0.88 to 1.17) | 0.93 (0.80 to 1.03) |
| small | ko | 6 | webfetch | 30/30 | 0.0408 | 0.0356 | 0.0053 | 0.0000 | 22.0 | 3.50 | 18444 | 1652 | 2.25 | 1 (1) |  |  |
| small | ko | 6 | jevfetch | 30/30 | 0.0351 | 0.0302 | 0.0040 | 0.0009 | 14.8 | 2.33 | 15976 | 1291 | 1.00 | 0 (0) | 0.86 (0.70 to 1.00) | 0.72 (0.57 to 0.91) |

## Judge votes that were not unanimous (2 of 52 judged runs; review by hand before publishing)

- redis-expire jevfetch rep 0: f4#0
- sqlite-length jevfetch rep 1: f3#0

## Per run

| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok | jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-cache | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0398 | 0.0036 | 20.1 | 2 | 15002 | 1 | 0 | 0 | 0 | 29969a5a42ce |
| claude-cache | medium | ko | webfetch | 0 | yes | 4/4 | 0.0442 | 0.0000 | 26.1 | 3 | 21227 | 0 | 2 | 0 | 0 | d4955bb3a2fa |
| claude-cache | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0600 | 0.0030 | 25.7 | 3 | 24417 | 1 | 0 | 0 | 0 | eb9b8029d4a6 |
| claude-cache | medium | ko | webfetch | 1 | yes | 4/4 | 0.0454 | 0.0000 | 27.4 | 3 | 21487 | 0 | 2 | 0 | 0 | 45d62b15dbf9 |
| docker-swap | small | ko | jevfetch | 0 | yes | 2/2 | 0.0192 | 0.0006 | 10.1 | 2 | 13385 | 1 | 0 | 0 | 0 | 95debc0aeddb |
| docker-swap | small | ko | webfetch | 0 | yes | 2/2 | 0.0347 | 0.0000 | 20.9 | 3 | 14016 | 0 | 2 | 0 | 0 | 7e54335c2c60 |
| docker-swap | small | ko | jevfetch | 1 | yes | 2/2 | 0.0203 | 0.0006 | 9.6 | 2 | 13403 | 1 | 0 | 0 | 0 | d6a835032d76 |
| docker-swap | small | ko | webfetch | 1 | yes | 2/2 | 0.0288 | 0.0000 | 15.6 | 3 | 13334 | 0 | 2 | 0 | 0 | d844228079f3 |
| gcs-lifecycle | small | ko | jevfetch | 0 | yes | 3/3 | 0.0347 | 0.0023 | 16.4 | 2 | 14542 | 1 | 0 | 0 | 0 | a4afa26e70bc |
| gcs-lifecycle | small | ko | webfetch | 0 | yes | 3/3 | 0.0384 | 0.0000 | 23.9 | 5 | 21616 | 0 | 4 | 0 | 0 | 56dcf79bac7a |
| gcs-lifecycle | small | ko | jevfetch | 1 | yes | 3/3 | 0.0356 | 0.0024 | 17.3 | 2 | 14470 | 1 | 0 | 0 | 0 | 036eb2a9a44f |
| gcs-lifecycle | small | ko | webfetch | 1 | yes | 3/3 | 0.0503 | 0.0000 | 26.4 | 5 | 22371 | 0 | 4 | 0 | 0 | a24bd8bed0af |
| gdpr-fines | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0848 | 0.0045 | 48.7 | 7 | 36289 | 5 | 0 | 0 | 0 | 7140491d8d29 |
| gdpr-fines | medium | ko | webfetch | 0 | yes | 2/2 | 0.0420 | 0.0000 | 28.9 | 3 | 14124 | 0 | 2 | 0 | 0 | 350ce65a3597 |
| gdpr-fines | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0508 | 0.0016 | 23.7 | 3 | 22999 | 1 | 0 | 0 | 0 | dfdb89a1a94d |
| gdpr-fines | medium | ko | webfetch | 1 | yes | 2/2 | 0.0676 | 0.0000 | 44.0 | 6 | 32725 | 0 | 4 | 0 | 1 | 0d6d14bc59db |
| gh-limits | small | ko | jevfetch | 0 | yes | 3/3 | 0.0429 | 0.0007 | 16.4 | 3 | 14844 | 1 | 0 | 0 | 0 | d27a2b6e6578 |
| gh-limits | small | ko | webfetch | 0 | yes | 3/3 | 0.0375 | 0.0000 | 19.1 | 4 | 20972 | 0 | 3 | 0 | 0 | 3eb87d1ad58c |
| gh-limits | small | ko | jevfetch | 1 | yes | 3/3 | 0.0426 | 0.0006 | 17.3 | 3 | 14823 | 1 | 0 | 0 | 0 | d6c34ab2cfa9 |
| gh-limits | small | ko | webfetch | 1 | yes | 3/3 | 0.0414 | 0.0000 | 24.3 | 5 | 28556 | 0 | 3 | 1 | 0 | c6f85403f674 |
| gh-rest-rate | small | ko | jevfetch | 0 | yes | 3/3 | 0.0302 | 0.0010 | 13.1 | 2 | 14503 | 1 | 0 | 0 | 0 | 37c99d13c831 |
| gh-rest-rate | small | ko | webfetch | 0 | yes | 3/3 | 0.0240 | 0.0000 | 16.4 | 2 | 13205 | 0 | 1 | 0 | 0 | abd73e9f3326 |
| gh-rest-rate | small | ko | jevfetch | 1 | yes | 3/3 | 0.0236 | 0.0011 | 10.0 | 2 | 13886 | 1 | 0 | 0 | 0 | 9e3309b9a2d4 |
| gh-rest-rate | small | ko | webfetch | 1 | yes | 3/3 | 0.0246 | 0.0000 | 17.4 | 2 | 13161 | 0 | 1 | 0 | 0 | 2f165ef86d77 |
| git-lease | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0289 | 0.0033 | 15.2 | 2 | 13653 | 1 | 0 | 0 | 0 | 06a475decf47 |
| git-lease | medium | ko | webfetch | 0 | yes | 2/2 | 0.0579 | 0.0000 | 27.2 | 3 | 15032 | 0 | 1 | 0 | 0 | d12552709d98 |
| git-lease | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0268 | 0.0029 | 13.8 | 2 | 13461 | 1 | 0 | 0 | 0 | 341e9067ae96 |
| git-lease | medium | ko | webfetch | 1 | yes | 2/2 | 0.0372 | 0.0000 | 26.0 | 2 | 14061 | 0 | 1 | 0 | 0 | e3359e103854 |
| k8s-termination | large | ko | jevfetch | 0 | yes | 3/3 | 0.0805 | 0.0146 | 31.9 | 4 | 24844 | 2 | 0 | 0 | 0 | 9aa0a5e08888 |
| k8s-termination | large | ko | webfetch | 0 | yes | 3/3 | 0.0861 | 0.0000 | 48.9 | 10 | 65798 | 0 | 3 | 7 | 1 | 611f89b2bd21 |
| k8s-termination | large | ko | jevfetch | 1 | yes | 3/3 | 0.0506 | 0.0146 | 17.2 | 3 | 15170 | 2 | 0 | 0 | 0 | 001665dd5449 |
| k8s-termination | large | ko | webfetch | 1 | yes | 3/3 | 0.0621 | 0.0000 | 31.7 | 4 | 26007 | 0 | 2 | 1 | 0 | 6e119e12aba5 |
| ko-holiday | medium | ko | jevfetch | 0 | yes | 1/1 | 0.1048 | 0.0008 | 60.0 | 6 | 40877 | 3 | 0 | 0 | 0 | c418f75b1883 |
| ko-holiday | medium | ko | webfetch | 0 | yes | 1/1 | 0.1128 | 0.0000 | 64.8 | 7 | 43108 | 0 | 3 | 2 | 0 | 703739d337aa |
| ko-holiday | medium | ko | jevfetch | 1 | yes | 1/1 | 0.1240 | 0.0013 | 57.1 | 6 | 43274 | 5 | 0 | 1 | 0 | 48e5489b6e62 |
| ko-holiday | medium | ko | webfetch | 1 | yes | 1/1 | 0.0770 | 0.0000 | 37.3 | 5 | 26040 | 0 | 3 | 0 | 0 | d801d74a9990 |
| ko-minwage | medium | ko | jevfetch | 0 | yes | 4/4 | 0.1012 | 0.0030 | 42.1 | 5 | 30710 | 3 | 0 | 0 | 0 | 7ac16d60046b |
| ko-minwage | medium | ko | webfetch | 0 | yes | 3/4 | 0.0802 | 0.0000 | 34.7 | 6 | 26524 | 0 | 4 | 0 | 0 | 0308b64de104 |
| ko-minwage | medium | ko | jevfetch | 1 | yes | 4/4 | 0.1070 | 0.0018 | 46.3 | 6 | 31072 | 3 | 0 | 0 | 0 | bf55e93401c3 |
| ko-minwage | medium | ko | webfetch | 1 | yes | 3/4 | 0.1046 | 0.0000 | 58.2 | 7 | 39656 | 0 | 3 | 2 | 0 | 7f42435a2680 |
| mdn-keepalive | large | ko | jevfetch | 0 | yes | 1/1 | 0.0787 | 0.0155 | 30.5 | 4 | 16908 | 2 | 0 | 0 | 0 | 21cab5f65119 |
| mdn-keepalive | large | ko | webfetch | 0 | yes | 1/1 | 0.0514 | 0.0000 | 37.9 | 7 | 46564 | 0 | 2 | 4 | 0 | 0d7a52733eff |
| mdn-keepalive | large | ko | jevfetch | 1 | yes | 1/1 | 0.0780 | 0.0171 | 24.3 | 5 | 31385 | 5 | 0 | 0 | 0 | 370df4f23ebc |
| mdn-keepalive | large | ko | webfetch | 1 | yes | 1/1 | 0.0472 | 0.0000 | 31.6 | 5 | 31371 | 0 | 2 | 2 | 0 | ec02e6a2bf21 |
| nginx-read-timeout | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0262 | 0.0047 | 10.6 | 2 | 14316 | 1 | 0 | 0 | 0 | 09d99f8f9d40 |
| nginx-read-timeout | medium | ko | webfetch | 0 | yes | 2/2 | 0.0231 | 0.0000 | 14.9 | 2 | 13084 | 0 | 1 | 0 | 0 | 8447b5d1aec3 |
| nginx-read-timeout | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0271 | 0.0048 | 11.0 | 2 | 14345 | 1 | 0 | 0 | 0 | b34a59fded2d |
| nginx-read-timeout | medium | ko | webfetch | 1 | yes | 2/2 | 0.0210 | 0.0000 | 13.5 | 2 | 12949 | 0 | 1 | 0 | 0 | 1d0fad081f75 |
| npm-peer | medium | ko | jevfetch | 0 | yes | 3/3 | 0.0863 | 0.0023 | 27.8 | 5 | 28065 | 3 | 0 | 0 | 0 | 7751b2b8d151 |
| npm-peer | medium | ko | webfetch | 0 | yes | 3/3 | 0.0544 | 0.0000 | 25.5 | 4 | 14914 | 0 | 2 | 0 | 0 | cf490e1a21f9 |
| npm-peer | medium | ko | jevfetch | 1 | yes | 3/3 | 0.0494 | 0.0021 | 24.6 | 3 | 14942 | 1 | 0 | 0 | 0 | c174d5ac9eb0 |
| npm-peer | medium | ko | webfetch | 1 | yes | 3/3 | 0.0442 | 0.0000 | 22.9 | 4 | 14443 | 0 | 3 | 0 | 0 | adf00002bf08 |
| pg-wraparound | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0518 | 0.0037 | 22.8 | 3 | 17191 | 2 | 0 | 0 | 0 | 0a39df68c24c |
| pg-wraparound | medium | ko | webfetch | 0 | yes | 2/2 | 0.0460 | 0.0000 | 27.4 | 3 | 14715 | 0 | 2 | 0 | 0 | 81705d5feeb6 |
| pg-wraparound | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0470 | 0.0034 | 21.4 | 3 | 16013 | 2 | 0 | 0 | 0 | 5c3061c2ad00 |
| pg-wraparound | medium | ko | webfetch | 1 | yes | 2/2 | 0.0428 | 0.0000 | 24.6 | 3 | 15127 | 0 | 2 | 0 | 0 | fb12a3ce0b91 |
| py-subprocess | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0524 | 0.0121 | 16.8 | 4 | 16072 | 3 | 0 | 0 | 0 | d324d57d6947 |
| py-subprocess | medium | ko | webfetch | 0 | yes | 2/2 | 0.0507 | 0.0000 | 29.9 | 3 | 15671 | 0 | 2 | 0 | 0 | 9fa534aa3836 |
| py-subprocess | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0498 | 0.0104 | 20.0 | 3 | 22612 | 2 | 0 | 0 | 0 | 32bcfb98e832 |
| py-subprocess | medium | ko | webfetch | 1 | yes | 2/2 | 0.0479 | 0.0000 | 27.2 | 3 | 15191 | 0 | 2 | 0 | 0 | 381d0b8b1314 |
| redis-expire | medium | ko | jevfetch | 0 | yes | 4/4 | 0.0581 | 0.0054 | 15.1 | 2 | 20520 | 1 | 0 | 0 | 0 | 18bbda661cae |
| redis-expire | medium | ko | webfetch | 0 | yes | 4/4 | 0.1087 | 0.0000 | 20.1 | 3 | 31745 | 0 | 2 | 0 | 0 | 60b388ecd7f5 |
| redis-expire | medium | ko | jevfetch | 1 | yes | 4/4 | 0.0909 | 0.0095 | 21.7 | 3 | 26065 | 2 | 0 | 0 | 0 | da964729101c |
| redis-expire | medium | ko | webfetch | 1 | yes | 4/4 | 0.1098 | 0.0000 | 21.6 | 3 | 31766 | 0 | 2 | 0 | 0 | 0f5857afb653 |
| rfc9111-heuristic | large | ko | jevfetch | 0 | yes | 4/4 | 0.0665 | 0.0282 | 19.6 | 3 | 15556 | 2 | 0 | 0 | 0 | 622e66904a65 |
| rfc9111-heuristic | large | ko | webfetch | 0 | yes | 4/4 | 0.0684 | 0.0000 | 34.0 | 7 | 42663 | 0 | 2 | 7 | 1 | 1816dae97f44 |
| rfc9111-heuristic | large | ko | jevfetch | 1 | yes | 4/4 | 0.0633 | 0.0289 | 17.5 | 3 | 15694 | 2 | 0 | 0 | 0 | f676052f3d0a |
| rfc9111-heuristic | large | ko | webfetch | 1 | yes | 4/4 | 0.0597 | 0.0000 | 28.2 | 5 | 32900 | 0 | 2 | 6 | 0 | 247f88aabdc2 |
| sqlite-length | small | ko | jevfetch | 0 | yes | 3/3 | 0.0227 | 0.0006 | 12.3 | 2 | 13629 | 1 | 0 | 0 | 0 | 57e54d7b09b1 |
| sqlite-length | small | ko | webfetch | 0 | yes | 3/3 | 0.0438 | 0.0000 | 28.3 | 4 | 23162 | 0 | 3 | 0 | 0 | 7c068a0efdcf |
| sqlite-length | small | ko | jevfetch | 1 | yes | 3/3 | 0.0230 | 0.0006 | 12.2 | 2 | 13637 | 1 | 0 | 0 | 0 | 719604c764af |
| sqlite-length | small | ko | webfetch | 1 | yes | 3/3 | 0.0347 | 0.0000 | 21.6 | 3 | 14284 | 0 | 2 | 0 | 0 | 3cfbeaf24642 |
| stripe-rate | small | ko | jevfetch | 0 | yes | 1/1 | 0.0635 | 0.0000 | 27.1 | 3 | 25424 | 1 | 0 | 0 | 0 | 041fe51a0d3b |
| stripe-rate | small | ko | webfetch | 0 | yes | 1/1 | 0.0632 | 0.0000 | 22.4 | 3 | 18227 | 0 | 1 | 0 | 0 | e625cf1c896e |
| stripe-rate | small | ko | jevfetch | 1 | yes | 1/1 | 0.0628 | 0.0000 | 25.8 | 3 | 25161 | 1 | 0 | 0 | 0 | bab3241f2300 |
| stripe-rate | small | ko | webfetch | 1 | yes | 1/1 | 0.0685 | 0.0000 | 24.6 | 3 | 18428 | 0 | 1 | 0 | 0 | af74ca08cd8e |
| us-dst | medium | ko | jevfetch | 0 | yes | 2/2 | 0.0577 | 0.0015 | 30.2 | 4 | 24900 | 2 | 0 | 0 | 0 | b637715c6d6f |
| us-dst | medium | ko | webfetch | 0 | yes | 2/2 | 0.0424 | 0.0000 | 20.9 | 3 | 14357 | 0 | 1 | 0 | 0 | 068f9f91ebe2 |
| us-dst | medium | ko | jevfetch | 1 | yes | 2/2 | 0.0672 | 0.0022 | 33.2 | 4 | 25897 | 2 | 0 | 0 | 0 | 99474494afb2 |
| us-dst | medium | ko | webfetch | 1 | yes | 2/2 | 0.0993 | 0.0000 | 33.2 | 5 | 27787 | 0 | 2 | 0 | 0 | 992476276f5e |
