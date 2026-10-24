# GridSimEnv v2 live pack statistics

Built by `scripts/build_live_pack.py` (live 2.0, core contract 1.0). All numbers are measured on the packs. Notices come from lane N's archive (`gridsim_core.notices`, FD-4325); a day is `notice`, `quiet` (archive coverage 1.0, no notice) or `unknown` (an archive gap).

## Packs

| pack | tasks | notice / quiet / unknown | blind | short | naive R | naive R notice | naive R quiet | naive capture | anchor capture | watches | anchor commits |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gridsim-live-train | 4000 | 1600 / 1648 / 752 | 3720 | 3469 | 0.7677 | 0.9757 | 0.629 | 0.3529 | 0.453 | 5.485 | 2.746 |
| gridsim-live-eval | 300 | 150 / 136 / 14 | 276 | 252 | 0.8572 | 0.9606 | 0.7617 | 0.4335 | 0.5236 | 5.663 | 2.723 |
| gridsim-live-test-2025 | 200 | 60 / 72 / 68 | 187 | 192 | 0.7638 | 0.9779 | 0.6735 | 0.3575 | 0.475 | 5.275 | 2.77 |
| gridsim-live-rtcb | 100 | 30 / 59 / 11 | 95 | 91 | 0.779 | 0.9959 | 0.6749 | 0.3374 | 0.4392 | 5.4 | 2.8 |
| gridsim-live-showcase | 90 | 88 / 2 / 0 | 87 | 42 | 0.9044 | 0.9022 | 1.0 | 0.4148 | 0.4315 | 7.133 | 2.711 |
| fixtures-live | 20 | 8 / 10 / 2 | 19 | 17 | 0.8439 | 0.9884 | 0.7422 | 0.4084 | 0.51 | 5.75 | 2.25 |

Naive R is naive's reward under the shared contract with the rolling anchor at 1.0 (idle 0.2). Capture is (P - P_idle) / (P_hind - P_idle), the weight-0 hindsight row.

## Distributions (quantiles p5, p25, p50, p75, p95, mean)

### gridsim-live-eval

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.5785 | 0.7551 | 0.8718 | 1.0000 | 1.0000 | 0.8572 |
| naive capture | 0.0815 | 0.2560 | 0.4376 | 0.5814 | 0.8051 | 0.4335 |
| anchor capture | 0.0939 | 0.3317 | 0.5249 | 0.7390 | 0.8964 | 0.5236 |
| hindsight DA share | 0.2940 | 0.4101 | 0.5123 | 0.6136 | 0.7695 | 0.5149 |
| freeze6h anchor capture | 0.0816 | 0.2582 | 0.4396 | 0.5860 | 0.8051 | 0.4356 |
| blind anchor capture | 0.1438 | 0.3404 | 0.5382 | 0.7324 | 0.9205 | 0.5314 |
| RT-DA divergence $/MW | 102.6005 | 131.6238 | 187.1000 | 324.9300 | 960.6616 | 343.9549 |

### gridsim-live-test-2025

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.3988 | 0.6367 | 0.7769 | 0.9829 | 1.0000 | 0.7638 |
| naive capture | 0.0644 | 0.1782 | 0.3347 | 0.5118 | 0.7816 | 0.3575 |
| anchor capture | 0.1973 | 0.3305 | 0.4789 | 0.6049 | 0.8199 | 0.4750 |
| hindsight DA share | 0.2809 | 0.4170 | 0.4921 | 0.5890 | 0.7516 | 0.5046 |
| freeze6h anchor capture | 0.0666 | 0.1968 | 0.3561 | 0.5164 | 0.8127 | 0.3683 |
| blind anchor capture | 0.1642 | 0.3072 | 0.4316 | 0.5897 | 0.7964 | 0.4546 |
| RT-DA divergence $/MW | 133.3408 | 194.8625 | 243.4450 | 393.0150 | 907.4757 | 351.6212 |

### gridsim-live-rtcb

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.3311 | 0.6724 | 0.7953 | 1.0000 | 1.0000 | 0.7790 |
| naive capture | 0.0282 | 0.1989 | 0.3235 | 0.4633 | 0.6561 | 0.3374 |
| anchor capture | 0.1378 | 0.3063 | 0.4423 | 0.5726 | 0.7145 | 0.4392 |
| hindsight DA share | 0.3064 | 0.4189 | 0.5123 | 0.6064 | 0.7484 | 0.5178 |
| freeze6h anchor capture | 0.0282 | 0.1931 | 0.3199 | 0.4632 | 0.6687 | 0.3375 |
| blind anchor capture | 0.1302 | 0.2707 | 0.4172 | 0.5280 | 0.7324 | 0.4151 |
| RT-DA divergence $/MW | 87.4104 | 130.0025 | 181.6737 | 272.7450 | 492.9845 | 218.8552 |

### gridsim-live-train

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.3190 | 0.6131 | 0.8039 | 1.0000 | 1.0000 | 0.7677 |
| naive capture | 0.0248 | 0.1385 | 0.2947 | 0.5261 | 0.8802 | 0.3529 |
| anchor capture | 0.1014 | 0.2744 | 0.4260 | 0.6284 | 0.8764 | 0.4530 |
| hindsight DA share | 0.3452 | 0.4533 | 0.5226 | 0.6274 | 0.8835 | 0.5525 |
| freeze6h anchor capture | 0.0243 | 0.1473 | 0.3070 | 0.5372 | 0.8803 | 0.3600 |
| blind anchor capture | 0.0915 | 0.2794 | 0.4378 | 0.6115 | 0.8502 | 0.4518 |
| RT-DA divergence $/MW | 99.1857 | 182.7450 | 289.4787 | 525.3444 | 3099.6081 | 914.1490 |

## Notices

| pack | tasks with a notice watch | notice watches (mean) | at the 10-watch cap | notices after the last watch | anchor beats naive on notice days | distinct notice point-days |
|---|---|---|---|---|---|---|
| gridsim-live-train | 1294 | 0.48 | 10 | 134 | 378 of 1600 | 1600 |
| gridsim-live-eval | 136 | 0.66 | 0 | 8 | 50 of 150 | 150 |
| gridsim-live-test-2025 | 49 | 0.28 | 0 | 0 | 20 of 60 | 60 |
| gridsim-live-rtcb | 27 | 0.40 | 0 | 8 | 4 of 30 | 30 |
| gridsim-live-showcase | 68 | 2.13 | 15 | 43 | 27 of 88 | 88 |
| fixtures-live | 10 | 0.75 | 0 | 0 | 1 of 8 | 8 |

Candidates and eligible tasks by day kind (notice days skip the anchor-beats-naive criterion, L-D9; the last column is how many notice-day candidates would pass without that exemption):

| split | notice | quiet | unknown | notice eligible without L-D9 | kept by kind |
|---|---|---|---|---|---|
| train | 28858 / 28802 | 126197 / 2557 | 41727 / 1242 | 637 | {"notice": 1600, "unknown": 752, "quiet": 1648} |
| eval | 5582 / 5582 | 6819 / 136 | 8988 / 159 | 181 | {"notice": 150, "quiet": 136, "unknown": 14} |
| test | 1736 / 1736 | 5265 / 112 | 6978 / 100 | 86 | {"notice": 60, "quiet": 72, "unknown": 68} |
| rtcb | 664 / 664 | 10918 / 295 | 1532 / 45 | 5 | {"notice": 30, "quiet": 59, "unknown": 11} |

## Eligibility filter

Chosen: {"divergence_usd_per_mw": 40.0, "roll_minus_naive_share": 0.1, "roll_minus_naive_usd_per_mw": 5.0, "hind_headroom_usd_per_mw": 10.0}. Spec start: {"divergence_usd_per_mw": 40.0, "roll_minus_naive_share": 0.05, "roll_minus_naive_usd_per_mw": 5.0, "hind_headroom_usd_per_mw": 10.0}. V2-D5: the anchor-beats-naive share is raised in steps [0.05, 0.075, 0.1, 0.125, 0.15] until naive's mean R on the eval pool is at most 0.7 (capped at 15%), measured on non-notice candidates.

Candidates are point-days x battery draws per point-day ({"train": 8, "eval": 12, "test": 3, "rtcb": 3}); selection takes one battery per point-day before a second.

| split | candidates | eligible | share | kept |
|---|---|---|---|---|
| train | 196782 | 32601 | 0.1657 | 4000 (3394 point-days) |
| eval | 21389 | 5877 | 0.2748 | 300 (221 point-days) |
| test | 13979 | 1948 | 0.1394 | 200 (200 point-days) |
| rtcb | 13114 | 1004 | 0.0766 | 100 (100 point-days) |

Why candidates fail (foresight, chosen thresholds; a task can fail several):

| split | divergence | hindsight headroom | anchor beats naive (share) | anchor beats naive ($/MW) |
|---|---|---|---|---|
| train | 458 | 113 | 192150 | 181521 |
| eval | 0 | 0 | 20870 | 19623 |
| test | 0 | 0 | 13668 | 12842 |
| rtcb | 3 | 0 | 12758 | 11950 |

### Tuning table

| split | divergence $/MW | share | candidates | kept | kept share | naive R |
|---|---|---|---|---|---|---|
| train | 20.0 | 0.05 | 167924 | 7479 | 0.0445 | 0.6991 |
| eval | 20.0 | 0.05 | 15807 | 618 | 0.0391 | 0.7715 |
| test | 20.0 | 0.05 | 12243 | 495 | 0.0404 | 0.7666 |
| rtcb | 20.0 | 0.05 | 12450 | 733 | 0.0589 | 0.747 |
| train | 20.0 | 0.075 | 167924 | 5304 | 0.0316 | 0.649 |
| eval | 20.0 | 0.075 | 15807 | 446 | 0.0282 | 0.7292 |
| test | 20.0 | 0.075 | 12243 | 306 | 0.025 | 0.7129 |
| rtcb | 20.0 | 0.075 | 12450 | 491 | 0.0394 | 0.7052 |
| train | 20.0 | 0.1 | 167924 | 3799 | 0.0226 | 0.6067 |
| eval | 20.0 | 0.1 | 15807 | 295 | 0.0187 | 0.6925 |
| test | 20.0 | 0.1 | 12243 | 212 | 0.0173 | 0.6637 |
| rtcb | 20.0 | 0.1 | 12450 | 340 | 0.0273 | 0.6658 |
| train | 20.0 | 0.125 | 167924 | 2815 | 0.0168 | 0.5728 |
| eval | 20.0 | 0.125 | 15807 | 187 | 0.0118 | 0.6899 |
| test | 20.0 | 0.125 | 12243 | 150 | 0.0123 | 0.6324 |
| rtcb | 20.0 | 0.125 | 12450 | 238 | 0.0191 | 0.6369 |
| train | 20.0 | 0.15 | 167924 | 2067 | 0.0123 | 0.5362 |
| eval | 20.0 | 0.15 | 15807 | 120 | 0.0076 | 0.7022 |
| test | 20.0 | 0.15 | 12243 | 98 | 0.008 | 0.5935 |
| rtcb | 20.0 | 0.15 | 12450 | 165 | 0.0133 | 0.612 |
| train | 40.0 | 0.05 | 167924 | 7479 | 0.0445 | 0.6991 |
| eval | 40.0 | 0.05 | 15807 | 618 | 0.0391 | 0.7715 |
| test | 40.0 | 0.05 | 12243 | 495 | 0.0404 | 0.7666 |
| rtcb | 40.0 | 0.05 | 12450 | 733 | 0.0589 | 0.747 |
| train | 40.0 | 0.075 | 167924 | 5304 | 0.0316 | 0.649 |
| eval | 40.0 | 0.075 | 15807 | 446 | 0.0282 | 0.7292 |
| test | 40.0 | 0.075 | 12243 | 306 | 0.025 | 0.7129 |
| rtcb | 40.0 | 0.075 | 12450 | 491 | 0.0394 | 0.7052 |
| train | 40.0 | 0.1 | 167924 | 3799 | 0.0226 | 0.6067 |
| eval | 40.0 | 0.1 | 15807 | 295 | 0.0187 | 0.6925 |
| test | 40.0 | 0.1 | 12243 | 212 | 0.0173 | 0.6637 |
| rtcb | 40.0 | 0.1 | 12450 | 340 | 0.0273 | 0.6658 |
| train | 40.0 | 0.125 | 167924 | 2815 | 0.0168 | 0.5728 |
| eval | 40.0 | 0.125 | 15807 | 187 | 0.0118 | 0.6899 |
| test | 40.0 | 0.125 | 12243 | 150 | 0.0123 | 0.6324 |
| rtcb | 40.0 | 0.125 | 12450 | 238 | 0.0191 | 0.6369 |
| train | 40.0 | 0.15 | 167924 | 2067 | 0.0123 | 0.5362 |
| eval | 40.0 | 0.15 | 15807 | 120 | 0.0076 | 0.7022 |
| test | 40.0 | 0.15 | 12243 | 98 | 0.008 | 0.5935 |
| rtcb | 40.0 | 0.15 | 12450 | 165 | 0.0133 | 0.612 |
| train | 60.0 | 0.05 | 167924 | 7455 | 0.0444 | 0.6993 |
| eval | 60.0 | 0.05 | 15807 | 617 | 0.039 | 0.7717 |
| test | 60.0 | 0.05 | 12243 | 495 | 0.0404 | 0.7666 |
| rtcb | 60.0 | 0.05 | 12450 | 733 | 0.0589 | 0.747 |
| train | 60.0 | 0.075 | 167924 | 5281 | 0.0314 | 0.6492 |
| eval | 60.0 | 0.075 | 15807 | 445 | 0.0282 | 0.7293 |
| test | 60.0 | 0.075 | 12243 | 306 | 0.025 | 0.7129 |
| rtcb | 60.0 | 0.075 | 12450 | 491 | 0.0394 | 0.7052 |
| train | 60.0 | 0.1 | 167924 | 3780 | 0.0225 | 0.6069 |
| eval | 60.0 | 0.1 | 15807 | 294 | 0.0186 | 0.6925 |
| test | 60.0 | 0.1 | 12243 | 212 | 0.0173 | 0.6637 |
| rtcb | 60.0 | 0.1 | 12450 | 340 | 0.0273 | 0.6658 |
| train | 60.0 | 0.125 | 167924 | 2800 | 0.0167 | 0.573 |
| eval | 60.0 | 0.125 | 15807 | 186 | 0.0118 | 0.6899 |
| test | 60.0 | 0.125 | 12243 | 150 | 0.0123 | 0.6324 |
| rtcb | 60.0 | 0.125 | 12450 | 238 | 0.0191 | 0.6369 |
| train | 60.0 | 0.15 | 167924 | 2054 | 0.0122 | 0.5362 |
| eval | 60.0 | 0.15 | 15807 | 119 | 0.0075 | 0.7023 |
| test | 60.0 | 0.15 | 12243 | 98 | 0.008 | 0.5935 |
| rtcb | 60.0 | 0.15 | 12450 | 165 | 0.0133 | 0.612 |

## All candidates (before the filter)

- Candidates: 245264; anchor above naive on 63582, equal on 82749, below on 98933.
- naive R | 0.8704 | 0.9996 | 1.0000 | 1.0000 | 1.0000 | 0.9783 |
- anchor capture | 0.0573 | 0.2478 | 0.4721 | 0.6956 | 0.9005 | 0.4728 |
- naive capture | 0.0602 | 0.2451 | 0.4742 | 0.7039 | 0.9182 | 0.4778 |

## Data

- RT SPPs (NP6-785-ER, report 13061): {"point_days_raw": 42611, "dst_dropped": 224, "clean_point_days": 42387, "first_date": "2019-01-01", "last_date": "2026-10-17", "zips": ["RTMLZHBSPP_2019.zip", "RTMLZHBSPP_2020.zip", "RTMLZHBSPP_2021.zip", "RTMLZHBSPP_2022.zip", "RTMLZHBSPP_2023.zip", "RTMLZHBSPP_2024.zip", "RTMLZHBSPP_2025.zip", "RTMLZHBSPP_2026.zip"]}.
- Within-date dedup on DA and RT dropped 4707: {'HB_BUSAVG': 440, 'HB_HUBAVG': 180, 'HB_NORTH': 84, 'HB_PAN': 51, 'HB_SOUTH': 49, 'HB_WEST': 84, 'LZ_AEN': 151, 'LZ_CPS': 126, 'LZ_HOUSTON': 1293, 'LZ_LCRA': 405, 'LZ_NORTH': 960, 'LZ_RAYBN': 784, 'LZ_SOUTH': 54, 'LZ_WEST': 46}.
- Showcase days and ±3 days are out of every split: {"sep23-0906": "2023-09-06", "uri-0215": "2021-02-15", "elliott-1223": "2022-12-23", "heather-0116": "2024-01-16", "aug23-0820": "2023-08-20", "fern-0126": "2026-01-26"}.
- Timing: {"foresight_refs_ms_per_task": 29.78, "all_tier_refs_ms_per_task": 119.93}.

