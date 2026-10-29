### Both packs

| row | eval-2025 $/MW-day [95% CI] | $k/MW-yr | fresh $/MW-day [95% CI] | $k/MW-yr | inference $ per battery-day |
|---|---|---:|---|---:|---:|
| hindsight optimum (DP on the day's own prices) | 101.4 [89.8, 114.7] | 37.0 | 74.9 [58.1, 94.3] | 27.4 | – |
| blind anchor: max(persistence-DP, ridge-DP) per task, an oracle pick | 89.2 [78.9, 100.9] | 32.6 | 67.6 [49.3, 88.7] | 24.7 | – |
| GPT-6.1 Sol, effort high | 87.9 [77.5, 99.6] | 32.1 | 67.2 [49.6, 87.1] | 24.5 | $0.01580 |
| Beam-1.0, effort high | – | – | 59.9 [44.9, 78.5] | 21.9 | $0.02032 |
| GPT-6 Luna, effort high | 78.6 [68.1, 90.6] | 28.7 | 58.5 [43.7, 74.9] | 21.4 | $0.00202 |
| GPT-6 Luna, effort medium | – | – | 55.2 [40.4, 72.7] | 20.1 | $0.00119 |
| GPT-6 Luna, effort low | 55.5 [45.5, 66.9] | 20.2 | 42.0 [31.2, 52.5] | 15.3 | $0.00053 |
| trained Qwen3-4B, run 4 final, sampled | 74.3 [63.6, 86.0] | 27.1 | 57.7 [42.8, 73.7] | 21.1 | $0.00048 |
| trained Qwen3-4B, run 4 final, greedy | 75.7 [64.5, 87.9] | 27.6 | 58.4 [42.2, 75.9] | 21.3 | $0.00047 |
| Qwen3-4B SFT start of run 4 (RL step 0), sampled | 73.1 [62.7, 84.8] | 26.7 | 54.3 [40.9, 68.3] | 19.8 | $0.00047 |
| untrained Qwen3-4B, sampled | −38.6 [−48.9, −29.2] | −14.1 | −27.8 [−41.4, −14.2] | −10.2 | $0.00037 |
| persistence-DP: exact DP on yesterday's prices | 83.6 [73.4, 95.4] | 30.5 | 63.4 [43.9, 84.9] | 23.1 | – |
| ridge-DP: exact DP on ridge-v1 | 72.0 [63.0, 81.9] | 26.3 | 64.6 [46.3, 86.0] | 23.6 | – |
| greedy rule on yesterday's prices | 59.7 [50.5, 69.7] | 21.8 | 51.1 [32.7, 71.5] | 18.7 | – |
| threshold rule on yesterday's prices | 44.4 [36.6, 52.8] | 16.2 | 51.4 [33.6, 71.9] | 18.8 | – |
| greedy rule on the day's own prices (sees the day) | 67.9 [58.3, 78.2] | 24.8 | 48.8 [27.9, 71.8] | 17.8 | – |
| threshold rule on the day's own prices (sees the day) | 53.9 [46.0, 62.5] | 19.7 | 52.4 [37.6, 66.8] | 19.1 | – |
| idle (the battery does nothing) | −21.4 [−27.6, −15.5] | −7.8 | −12.6 [−16.3, −9.6] | −4.6 | – |

| paired gap | eval-2025 $/MW-day [95% CI] | $k/MW-yr [95% CI] | fresh $/MW-day [95% CI] | $k/MW-yr [95% CI] |
|---|---|---|---|---|
| GPT-6.1 Sol − persistence-DP | +4.3 [+2.1, +6.6] | +1.6 [+0.8, +2.4] | +3.8 [+0.9, +7.3] | +1.4 [+0.3, +2.7] |
| GPT-6.1 Sol − ridge-DP | +15.9 [+9.3, +24.6] | +5.8 [+3.4, +9.0] | +2.6 [+0.0, +4.7] | +0.9 [+0.0, +1.7] |
| trained Qwen3-4B (run 4) − persistence-DP | −9.3 [−15.2, −4.0] | −3.4 [−5.6, −1.5] | −5.7 [−12.0, +0.7] | −2.1 [−4.4, +0.2] |
| GPT-6.1 Sol − trained Qwen3-4B (run 4) | +13.6 [+8.6, +19.1] | +5.0 [+3.1, +7.0] | +9.5 [+5.3, +14.1] | +3.5 [+1.9, +5.1] |
| GPT-6 Luna, high − persistence-DP | −5.0 [−7.8, −2.1] | −1.8 [−2.9, −0.8] | −4.9 [−11.0, +2.2] | −1.8 [−4.0, +0.8] |
| trained Qwen3-4B (run 4) − untrained Qwen3-4B | +112.9 [+100.1, +126.4] | +41.2 [+36.6, +46.1] | +85.5 [+60.4, +112.1] | +31.2 [+22.0, +40.9] |
| Beam-1.0, high (best effort) − persistence-DP | – | – | −3.4 [−8.6, +2.4] | −1.3 [−3.2, +0.9] |

### ercot-dam-v1-eval: 300 battery-days on 191 days, 2025-01-06 to 2025-11-30

| row | $/MW-day | 95% CI | $k/MW-yr | per 100 MW-yr | valid | inference $ per battery-day |
|---|---:|---|---:|---:|---:|---:|
| hindsight optimum (DP on the day's own prices) | 101.4 | [89.8, 114.7] | 37.0 | $3.70M | – | – |
| blind anchor: max(persistence-DP, ridge-DP) per task, an oracle pick | 89.2 | [78.9, 100.9] | 32.6 | $3.26M | – | – |
| GPT-6.1 Sol, effort high | 87.9 | [77.5, 99.6] | 32.1 | $3.21M | 99.0% | $0.01580 |
| persistence-DP: exact DP on yesterday's prices | 83.6 | [73.4, 95.4] | 30.5 | $3.05M | – | – |
| GPT-6 Luna, effort high | 78.6 | [68.1, 90.6] | 28.7 | $2.87M | 99.0% | $0.00202 |
| trained Qwen3-4B, run 4 final, greedy | 75.7 | [64.5, 87.9] | 27.6 | $2.76M | 100.0% | $0.00047 |
| trained Qwen3-4B, run 4 final, sampled | 74.3 | [63.6, 86.0] | 27.1 | $2.71M | 100.0% | $0.00048 |
| Qwen3-4B SFT start of run 4 (RL step 0), sampled | 73.1 | [62.7, 84.8] | 26.7 | $2.67M | 100.0% | $0.00047 |
| ridge-DP: exact DP on ridge-v1 | 72.0 | [63.0, 81.9] | 26.3 | $2.63M | – | – |
| greedy rule on the day's own prices (sees the day) | 67.9 | [58.3, 78.2] | 24.8 | $2.48M | – | – |
| greedy rule on yesterday's prices | 59.7 | [50.5, 69.7] | 21.8 | $2.18M | – | – |
| GPT-6 Luna, effort low | 55.5 | [45.5, 66.9] | 20.2 | $2.02M | 99.7% | $0.00053 |
| threshold rule on the day's own prices (sees the day) | 53.9 | [46.0, 62.5] | 19.7 | $1.97M | – | – |
| threshold rule on yesterday's prices | 44.4 | [36.6, 52.8] | 16.2 | $1.62M | – | – |
| idle (the battery does nothing) | −21.4 | [−27.6, −15.5] | −7.8 | −$0.78M | – | – |
| untrained Qwen3-4B, sampled | −38.6 | [−48.9, −29.2] | −14.1 | −$1.41M | 100.0% | $0.00037 |

| paired gap | $/MW-day [95% CI] | $k/MW-yr [95% CI] | per 100 MW-yr | ahead / level | days ahead |
|---|---|---|---:|---|---:|
| GPT-6.1 Sol − persistence-DP | +4.3 [+2.1, +6.6] | +1.6 [+0.8, +2.4] | +156k | 45% / 37% | 101/191 |
| GPT-6.1 Sol − ridge-DP | +15.9 [+9.3, +24.6] | +5.8 [+3.4, +9.0] | +580k | 71% / 8% | 146/191 |
| trained Qwen3-4B (run 4) − persistence-DP | −9.3 [−15.2, −4.0] | −3.4 [−5.6, −1.5] | −341k | 39% / 10% | 72/191 |
| GPT-6.1 Sol − trained Qwen3-4B (run 4) | +13.6 [+8.6, +19.1] | +5.0 [+3.1, +7.0] | +497k | 55% / 19% | 118/191 |
| GPT-6 Luna, high − persistence-DP | −5.0 [−7.8, −2.1] | −1.8 [−2.9, −0.8] | −183k | 31% / 13% | 57/191 |
| trained Qwen3-4B (run 4) − untrained Qwen3-4B | +112.9 [+100.1, +126.4] | +41.2 [+36.6, +46.1] | +4,120k | 98% / 0% | 186/191 |

### ercot-dam-v1-fresh-2026-10-blind: 331 battery-days on 10 days, 2026-10-18 to 2026-10-27

| row | $/MW-day | 95% CI | $k/MW-yr | per 100 MW-yr | valid | inference $ per battery-day |
|---|---:|---|---:|---:|---:|---:|
| hindsight optimum (DP on the day's own prices) | 74.9 | [58.1, 94.3] | 27.4 | $2.74M | – | – |
| blind anchor: max(persistence-DP, ridge-DP) per task, an oracle pick | 67.6 | [49.3, 88.7] | 24.7 | $2.47M | – | – |
| GPT-6.1 Sol, effort high | 67.2 | [49.6, 87.1] | 24.5 | $2.45M | 99.1% | $0.01585 |
| ridge-DP: exact DP on ridge-v1 | 64.6 | [46.3, 86.0] | 23.6 | $2.36M | – | – |
| persistence-DP: exact DP on yesterday's prices | 63.4 | [43.9, 84.9] | 23.1 | $2.31M | – | – |
| Beam-1.0, effort high | 59.9 | [44.9, 78.5] | 21.9 | $2.19M | 100.0% | $0.02032 |
| GPT-6 Luna, effort high | 58.5 | [43.7, 74.9] | 21.4 | $2.14M | 98.8% | $0.00201 |
| trained Qwen3-4B, run 4 final, greedy | 58.4 | [42.2, 75.9] | 21.3 | $2.13M | 100.0% | $0.00048 |
| trained Qwen3-4B, run 4 final, sampled | 57.7 | [42.8, 73.7] | 21.1 | $2.11M | 100.0% | $0.00047 |
| GPT-6 Luna, effort medium | 55.2 | [40.4, 72.7] | 20.1 | $2.01M | 97.9% | $0.00119 |
| Qwen3-4B SFT start of run 4 (RL step 0), sampled | 54.3 | [40.9, 68.3] | 19.8 | $1.98M | 100.0% | $0.00044 |
| threshold rule on the day's own prices (sees the day) | 52.4 | [37.6, 66.8] | 19.1 | $1.91M | – | – |
| threshold rule on yesterday's prices | 51.4 | [33.6, 71.9] | 18.8 | $1.88M | – | – |
| greedy rule on yesterday's prices | 51.1 | [32.7, 71.5] | 18.7 | $1.87M | – | – |
| greedy rule on the day's own prices (sees the day) | 48.8 | [27.9, 71.8] | 17.8 | $1.78M | – | – |
| GPT-6 Luna, effort low | 42.0 | [31.2, 52.5] | 15.3 | $1.53M | 98.2% | $0.00052 |
| idle (the battery does nothing) | −12.6 | [−16.3, −9.6] | −4.6 | −$0.46M | – | – |
| untrained Qwen3-4B, sampled | −27.8 | [−41.4, −14.2] | −10.2 | −$1.02M | 100.0% | $0.00033 |

Beam-1.0 efforts: high included, low incomplete (112 of 331), medium not run, max not run.

| paired gap | $/MW-day [95% CI] | $k/MW-yr [95% CI] | per 100 MW-yr | ahead / level | days ahead |
|---|---|---|---:|---|---:|
| GPT-6.1 Sol − persistence-DP | +3.8 [+0.9, +7.3] | +1.4 [+0.3, +2.7] | +139k | 47% / 31% | 9/10 |
| GPT-6.1 Sol − ridge-DP | +2.6 [+0.0, +4.7] | +0.9 [+0.0, +1.7] | +93k | 56% / 10% | 8/10 |
| trained Qwen3-4B (run 4) − persistence-DP | −5.7 [−12.0, +0.7] | −2.1 [−4.4, +0.2] | −207k | 40% / 4% | 4/10 |
| GPT-6.1 Sol − trained Qwen3-4B (run 4) | +9.5 [+5.3, +14.1] | +3.5 [+1.9, +5.1] | +346k | 65% / 9% | 10/10 |
| GPT-6 Luna, high − persistence-DP | −4.9 [−11.0, +2.2] | −1.8 [−4.0, +0.8] | −178k | 37% / 8% | 4/10 |
| Beam-1.0, high (best effort) − persistence-DP | −3.4 [−8.6, +2.4] | −1.3 [−3.2, +0.9] | −126k | 37% / 10% | 4/10 |
| trained Qwen3-4B (run 4) − untrained Qwen3-4B | +85.5 [+60.4, +112.1] | +31.2 [+22.0, +40.9] | +3,121k | 98% / 0% | 10/10 |

### Inference cost against decision value, per battery-day

| pack | model | inference $ per battery-day | per battery-year | earned per day, 100 MW | vs persistence-DP per day, 100 MW |
|---|---|---:|---:|---:|---:|
| eval2025 | GPT-6.1 Sol | $0.01580 | $5.77 | $8,787 | +$427 |
| eval2025 | GPT-6 Luna, high | $0.00202 | $0.74 | $7,860 | −$500 |
| eval2025 | GPT-6 Luna, low | $0.00053 | $0.19 | $5,548 | −$2,812 |
| eval2025 | trained Qwen3-4B (run 4) | $0.00048 | $0.17 | $7,425 | −$935 |
| eval2025 | trained Qwen3-4B (run 4), greedy | $0.00047 | $0.17 | $7,569 | −$791 |
| eval2025 | Qwen3-4B, SFT only | $0.00047 | $0.17 | $7,306 | −$1,054 |
| eval2025 | untrained Qwen3-4B | $0.00037 | $0.13 | −$3,861 | −$12,221 |
| fresh | GPT-6.1 Sol | $0.01585 | $5.78 | $6,718 | +$380 |
| fresh | GPT-6 Luna, high | $0.00201 | $0.73 | $5,851 | −$487 |
| fresh | GPT-6 Luna, medium | $0.00119 | $0.43 | $5,518 | −$819 |
| fresh | GPT-6 Luna, low | $0.00052 | $0.19 | $4,197 | −$2,140 |
| fresh | Beam-1.0, high | $0.02032 | $7.42 | $5,993 | −$344 |
| fresh | trained Qwen3-4B (run 4) | $0.00047 | $0.17 | $5,771 | −$567 |
| fresh | trained Qwen3-4B (run 4), greedy | $0.00048 | $0.17 | $5,840 | −$497 |
| fresh | Qwen3-4B, SFT only | $0.00044 | $0.16 | $5,434 | −$903 |
| fresh | untrained Qwen3-4B | $0.00033 | $0.12 | −$2,782 | −$9,119 |

### ercot-dam-v1-eval: by day

Hindsight optimum in the top 19 of 191 days: 30.3% (day means of $/MW-day).

| price-shape change quartile | days | 1 − r range | optimum $/MW-day | persistence-DP short of optimum | GPT-6.1 Sol − persistence-DP | GPT-6 Luna, high − persistence-DP | trained Qwen3-4B (run 4) − persistence-DP |
|---|---:|---|---:|---|---|---|---|
| Q1 | 48 | 0.007–0.045 | 92.0 | 3.7 [2.4, 5.2] | +0.2 [−2.0, +2.0] | −9.5 [−15.1, −5.3] | −13.0 [−22.8, −5.6] |
| Q2 | 47 | 0.046–0.107 | 109.1 | 10.5 [6.9, 14.8] | +0.9 [−2.9, +4.2] | −10.4 [−15.5, −5.7] | −22.6 [−39.9, −9.1] |
| Q3 | 48 | 0.107–0.248 | 72.8 | 16.7 [12.2, 21.3] | +3.7 [+0.4, +7.2] | −3.1 [−8.2, +2.0] | −1.4 [−6.4, +3.9] |
| Q4 | 48 | 0.256–0.895 | 133.8 | 41.6 [29.4, 54.5] | +12.7 [+6.5, +20.1] | +3.4 [−3.4, +11.5] | +0.0 [−11.3, +10.6] |

### ercot-dam-v1-fresh-2026-10-blind: by day

Hindsight optimum in the top 1 of 10 days: 20.4% (day means of $/MW-day).

| day | battery-days | 1 − r | optimum | persistence-DP | GPT-6.1 Sol − persistence-DP | GPT-6 Luna, high − persistence-DP | trained Qwen3-4B (run 4) − persistence-DP | Beam-1.0 (best effort) − persistence-DP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-10-18 | 41 | 0.336 | 77.2 | 44.3 | +11.7 | +11.7 | +0.2 | +3.9 |
| 2026-10-19 | 29 | 0.404 | 54.2 | 33.8 | +12.2 | −5.6 | +9.1 | +8.7 |
| 2026-10-20 | 46 | 0.020 | 84.3 | 82.3 | +0.5 | −14.4 | −8.5 | −16.5 |
| 2026-10-21 | 45 | 0.076 | 138.2 | 131.4 | −0.1 | −19.9 | −23.6 | −9.7 |
| 2026-10-22 | 53 | 0.140 | 67.8 | 63.9 | +0.1 | −7.9 | −10.1 | −8.4 |
| 2026-10-23 | 28 | 0.116 | 49.3 | 42.7 | +1.7 | −3.4 | −4.0 | −2.9 |
| 2026-10-24 | 19 | 0.193 | 40.6 | 30.9 | +0.7 | +1.9 | −6.1 | +0.0 |
| 2026-10-25 | 10 | 0.067 | 40.4 | 33.2 | +1.2 | −3.3 | −15.2 | −9.0 |
| 2026-10-26 | 34 | 0.094 | 67.5 | 50.6 | +7.9 | +3.6 | +5.9 | +7.2 |
| 2026-10-27 | 26 | 0.706 | 58.8 | 48.3 | +2.5 | +0.8 | +0.8 | +0.7 |

