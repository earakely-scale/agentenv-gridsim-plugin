# GridSimEnv v2 live pack statistics

Built by `scripts/build_live_pack.py` (live 2.0, core contract 1.0). All numbers are measured on the packs. No notices are attached yet (FD-4325 runs in parallel); every day is a quiet day until `--merge-notices` fills them.

## Packs

| pack | tasks | blind | short | notice days | naive R | naive capture | anchor capture | watches | anchor commits |
|---|---|---|---|---|---|---|---|---|---|
| gridsim-live-train | 4000 | 3746 | 4000 | 0 | 0.6187 | 0.2534 | 0.4298 | 5.0 | 2.94 |
| gridsim-live-eval | 300 | 286 | 300 | 0 | 0.6891 | 0.3421 | 0.5014 | 5.0 | 3.027 |
| gridsim-live-test-2025 | 200 | 194 | 200 | 0 | 0.6606 | 0.2778 | 0.4472 | 5.0 | 2.94 |
| gridsim-live-rtcb | 100 | 90 | 100 | 0 | 0.6642 | 0.2794 | 0.4381 | 5.0 | 3.08 |
| gridsim-live-showcase | 90 | 87 | 90 | 0 | 0.918 | 0.4148 | 0.4325 | 5.0 | 2.233 |
| fixtures-live | 20 | 20 | 20 | 2 | 0.6608 | 0.2771 | 0.4411 | 5.1 | 3.1 |

Naive R is naive's reward under the shared contract with the rolling anchor at 1.0 (idle 0.2). Capture is (P - P_idle) / (P_hind - P_idle), the weight-0 hindsight row.

## Distributions (quantiles p5, p25, p50, p75, p95, mean)

### gridsim-live-eval

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.3787 | 0.5939 | 0.7237 | 0.8248 | 0.8765 | 0.6891 |
| naive capture | 0.0363 | 0.1638 | 0.3308 | 0.5246 | 0.6924 | 0.3421 |
| anchor capture | 0.1588 | 0.3069 | 0.5162 | 0.6840 | 0.8515 | 0.5014 |
| hindsight DA share | 0.3342 | 0.4294 | 0.5035 | 0.5896 | 0.7245 | 0.5140 |
| freeze6h anchor capture | 0.0374 | 0.1734 | 0.3455 | 0.5399 | 0.7035 | 0.3576 |
| blind anchor capture | 0.1510 | 0.2452 | 0.4518 | 0.6377 | 0.8511 | 0.4634 |
| RT-DA divergence $/MW | 99.2139 | 124.0006 | 186.2225 | 297.3262 | 561.8150 | 254.0986 |

### gridsim-live-test-2025

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.3508 | 0.5470 | 0.6955 | 0.7861 | 0.8571 | 0.6606 |
| naive capture | 0.0542 | 0.1398 | 0.2551 | 0.4045 | 0.5710 | 0.2778 |
| anchor capture | 0.1954 | 0.3286 | 0.4345 | 0.5612 | 0.7310 | 0.4472 |
| hindsight DA share | 0.3575 | 0.4511 | 0.5058 | 0.5864 | 0.7477 | 0.5273 |
| freeze6h anchor capture | 0.0701 | 0.1458 | 0.2589 | 0.4176 | 0.5744 | 0.2921 |
| blind anchor capture | 0.1281 | 0.2764 | 0.3814 | 0.5152 | 0.7131 | 0.3981 |
| RT-DA divergence $/MW | 121.3359 | 190.7362 | 244.0725 | 396.2837 | 917.5461 | 400.4179 |

### gridsim-live-rtcb

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.2866 | 0.5958 | 0.6942 | 0.7920 | 0.8564 | 0.6642 |
| naive capture | 0.0193 | 0.1519 | 0.2691 | 0.4159 | 0.5610 | 0.2794 |
| anchor capture | 0.1719 | 0.3120 | 0.4255 | 0.5614 | 0.7192 | 0.4381 |
| hindsight DA share | 0.3408 | 0.4323 | 0.5279 | 0.6234 | 0.7842 | 0.5403 |
| freeze6h anchor capture | 0.0193 | 0.1686 | 0.2807 | 0.3915 | 0.5691 | 0.2830 |
| blind anchor capture | 0.1183 | 0.2335 | 0.3779 | 0.5023 | 0.6660 | 0.3840 |
| RT-DA divergence $/MW | 87.8807 | 130.9081 | 183.0213 | 283.3687 | 399.8037 | 216.7538 |

### gridsim-live-train

| row | p5 | p25 | p50 | p75 | p95 | mean |
|---|---|---|---|---|---|---|
| naive R | 0.2629 | 0.4852 | 0.6559 | 0.7725 | 0.8612 | 0.6187 |
| naive capture | 0.0167 | 0.0975 | 0.2195 | 0.3738 | 0.6109 | 0.2534 |
| anchor capture | 0.1718 | 0.2883 | 0.4079 | 0.5488 | 0.7705 | 0.4298 |
| hindsight DA share | 0.3579 | 0.4577 | 0.5218 | 0.5998 | 0.8497 | 0.5448 |
| freeze6h anchor capture | 0.0157 | 0.1056 | 0.2372 | 0.3862 | 0.6306 | 0.2656 |
| blind anchor capture | 0.1109 | 0.2853 | 0.4111 | 0.5470 | 0.7442 | 0.4165 |
| RT-DA divergence $/MW | 99.5181 | 178.8156 | 276.9100 | 437.3050 | 1594.0439 | 489.3862 |

## Eligibility filter

Chosen: {"divergence_usd_per_mw": 40.0, "roll_minus_naive_share": 0.1, "roll_minus_naive_usd_per_mw": 5.0, "hind_headroom_usd_per_mw": 10.0}. Spec start: {"divergence_usd_per_mw": 40.0, "roll_minus_naive_share": 0.05, "roll_minus_naive_usd_per_mw": 5.0, "hind_headroom_usd_per_mw": 10.0}. V2-D5: the anchor-beats-naive share is raised in steps [0.05, 0.075, 0.1, 0.125, 0.15] until naive's mean R on the eval pool is at most 0.7 (capped at 15%).

Candidates are point-days x battery draws per point-day ({"train": 8, "eval": 12, "test": 3, "rtcb": 3}); selection takes one battery per point-day before a second.

| split | candidates | eligible | share | kept |
|---|---|---|---|---|
| train | 199240 | 4307 | 0.0216 | 4000 (2028 point-days) |
| eval | 17803 | 358 | 0.0201 | 300 (150 point-days) |
| test | 13979 | 296 | 0.0212 | 200 (200 point-days) |
| rtcb | 13114 | 346 | 0.0264 | 100 (100 point-days) |

Why candidates fail (foresight, chosen thresholds; a task can fail several):

| split | divergence | hindsight headroom | anchor beats naive (share) | anchor beats naive ($/MW) |
|---|---|---|---|---|
| train | 458 | 113 | 194738 | 184183 |
| eval | 0 | 0 | 17405 | 16512 |
| test | 0 | 0 | 13670 | 12854 |
| rtcb | 3 | 0 | 12757 | 11958 |

### Tuning table

| split | divergence $/MW | share | candidates | kept | kept share | naive R |
|---|---|---|---|---|---|---|
| train | 20.0 | 0.05 | 199240 | 8569 | 0.043 | 0.7018 |
| eval | 20.0 | 0.05 | 17803 | 753 | 0.0423 | 0.7682 |
| test | 20.0 | 0.05 | 13979 | 623 | 0.0446 | 0.7475 |
| rtcb | 20.0 | 0.05 | 13114 | 748 | 0.057 | 0.7476 |
| train | 20.0 | 0.075 | 199240 | 6012 | 0.0302 | 0.652 |
| eval | 20.0 | 0.075 | 17803 | 537 | 0.0302 | 0.7259 |
| test | 20.0 | 0.075 | 13979 | 405 | 0.029 | 0.6941 |
| rtcb | 20.0 | 0.075 | 13114 | 500 | 0.0381 | 0.706 |
| train | 20.0 | 0.1 | 199240 | 4307 | 0.0216 | 0.6105 |
| eval | 20.0 | 0.1 | 17803 | 358 | 0.0201 | 0.6878 |
| test | 20.0 | 0.1 | 13979 | 296 | 0.0212 | 0.6463 |
| rtcb | 20.0 | 0.1 | 13114 | 346 | 0.0264 | 0.6665 |
| train | 20.0 | 0.125 | 199240 | 3174 | 0.0159 | 0.5763 |
| eval | 20.0 | 0.125 | 17803 | 237 | 0.0133 | 0.6829 |
| test | 20.0 | 0.125 | 13979 | 213 | 0.0152 | 0.6081 |
| rtcb | 20.0 | 0.125 | 13114 | 242 | 0.0185 | 0.6367 |
| train | 20.0 | 0.15 | 199240 | 2307 | 0.0116 | 0.5403 |
| eval | 20.0 | 0.15 | 17803 | 153 | 0.0086 | 0.6881 |
| test | 20.0 | 0.15 | 13979 | 146 | 0.0104 | 0.5749 |
| rtcb | 20.0 | 0.15 | 13114 | 167 | 0.0127 | 0.6118 |
| train | 40.0 | 0.05 | 199240 | 8569 | 0.043 | 0.7018 |
| eval | 40.0 | 0.05 | 17803 | 753 | 0.0423 | 0.7682 |
| test | 40.0 | 0.05 | 13979 | 623 | 0.0446 | 0.7475 |
| rtcb | 40.0 | 0.05 | 13114 | 748 | 0.057 | 0.7476 |
| train | 40.0 | 0.075 | 199240 | 6012 | 0.0302 | 0.652 |
| eval | 40.0 | 0.075 | 17803 | 537 | 0.0302 | 0.7259 |
| test | 40.0 | 0.075 | 13979 | 405 | 0.029 | 0.6941 |
| rtcb | 40.0 | 0.075 | 13114 | 500 | 0.0381 | 0.706 |
| train | 40.0 | 0.1 | 199240 | 4307 | 0.0216 | 0.6105 |
| eval | 40.0 | 0.1 | 17803 | 358 | 0.0201 | 0.6878 |
| test | 40.0 | 0.1 | 13979 | 296 | 0.0212 | 0.6463 |
| rtcb | 40.0 | 0.1 | 13114 | 346 | 0.0264 | 0.6665 |
| train | 40.0 | 0.125 | 199240 | 3174 | 0.0159 | 0.5763 |
| eval | 40.0 | 0.125 | 17803 | 237 | 0.0133 | 0.6829 |
| test | 40.0 | 0.125 | 13979 | 213 | 0.0152 | 0.6081 |
| rtcb | 40.0 | 0.125 | 13114 | 242 | 0.0185 | 0.6367 |
| train | 40.0 | 0.15 | 199240 | 2307 | 0.0116 | 0.5403 |
| eval | 40.0 | 0.15 | 17803 | 153 | 0.0086 | 0.6881 |
| test | 40.0 | 0.15 | 13979 | 146 | 0.0104 | 0.5749 |
| rtcb | 40.0 | 0.15 | 13114 | 167 | 0.0127 | 0.6118 |
| train | 60.0 | 0.05 | 199240 | 8544 | 0.0429 | 0.702 |
| eval | 60.0 | 0.05 | 17803 | 752 | 0.0422 | 0.7683 |
| test | 60.0 | 0.05 | 13979 | 623 | 0.0446 | 0.7475 |
| rtcb | 60.0 | 0.05 | 13114 | 748 | 0.057 | 0.7476 |
| train | 60.0 | 0.075 | 199240 | 5989 | 0.0301 | 0.6521 |
| eval | 60.0 | 0.075 | 17803 | 536 | 0.0301 | 0.726 |
| test | 60.0 | 0.075 | 13979 | 405 | 0.029 | 0.6941 |
| rtcb | 60.0 | 0.075 | 13114 | 500 | 0.0381 | 0.706 |
| train | 60.0 | 0.1 | 199240 | 4288 | 0.0215 | 0.6107 |
| eval | 60.0 | 0.1 | 17803 | 357 | 0.0201 | 0.6878 |
| test | 60.0 | 0.1 | 13979 | 296 | 0.0212 | 0.6463 |
| rtcb | 60.0 | 0.1 | 13114 | 346 | 0.0264 | 0.6665 |
| train | 60.0 | 0.125 | 199240 | 3159 | 0.0159 | 0.5765 |
| eval | 60.0 | 0.125 | 17803 | 236 | 0.0133 | 0.6829 |
| test | 60.0 | 0.125 | 13979 | 213 | 0.0152 | 0.6081 |
| rtcb | 60.0 | 0.125 | 13114 | 242 | 0.0185 | 0.6367 |
| train | 60.0 | 0.15 | 199240 | 2294 | 0.0115 | 0.5403 |
| eval | 60.0 | 0.15 | 17803 | 152 | 0.0085 | 0.6881 |
| test | 60.0 | 0.15 | 13979 | 146 | 0.0104 | 0.5749 |
| rtcb | 60.0 | 0.15 | 13114 | 167 | 0.0127 | 0.6118 |

## All candidates (before the filter)

- Candidates: 244136; anchor above naive on 62371, equal on 83837, below on 97928.
- naive R | 0.8751 | 0.9998 | 1.0000 | 1.0000 | 1.0000 | 0.9789 |
- anchor capture | 0.0570 | 0.2477 | 0.4723 | 0.6956 | 0.9003 | 0.4727 |
- naive capture | 0.0601 | 0.2452 | 0.4744 | 0.7039 | 0.9177 | 0.4778 |

## Data

- RT SPPs (NP6-785-ER, report 13061): {"point_days_raw": 42611, "dst_dropped": 224, "clean_point_days": 42387, "first_date": "2019-01-01", "last_date": "2026-10-17", "zips": ["RTMLZHBSPP_2019.zip", "RTMLZHBSPP_2020.zip", "RTMLZHBSPP_2021.zip", "RTMLZHBSPP_2022.zip", "RTMLZHBSPP_2023.zip", "RTMLZHBSPP_2024.zip", "RTMLZHBSPP_2025.zip", "RTMLZHBSPP_2026.zip"]}.
- Within-date dedup on DA and RT dropped 4707: {'HB_BUSAVG': 440, 'HB_HUBAVG': 180, 'HB_NORTH': 84, 'HB_PAN': 51, 'HB_SOUTH': 49, 'HB_WEST': 84, 'LZ_AEN': 151, 'LZ_CPS': 126, 'LZ_HOUSTON': 1293, 'LZ_LCRA': 405, 'LZ_NORTH': 960, 'LZ_RAYBN': 784, 'LZ_SOUTH': 54, 'LZ_WEST': 46}.
- Showcase days and ±3 days are out of every split: {"sep23-0906": "2023-09-06", "uri-0215": "2021-02-15", "elliott-1223": "2022-12-23", "heather-0116": "2024-01-16", "aug23-0820": "2023-08-20", "fern-0126": "2026-01-26"}.
- Timing: {"foresight_refs_ms_per_task": 30.85, "all_tier_refs_ms_per_task": 108.78}.

