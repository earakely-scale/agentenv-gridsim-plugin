# GridSimEnv v4: forecast store depth report

Built 2026-10-24T17:30:44Z by `scripts/forecast_depth.py` from `cache/forecast/` (store `cb47cd9fc080268a`). Machine-readable: `data/forecast/coverage.json`. Times are CPT unless marked UTC.

## Answer

- **API era (2023-12-11 on)**: NP3-565-CD 25,144 postings, NP4-732-CD 25,147 postings, NP4-742-CD 25,127 postings, NP4-745-CD 25,142 postings. On 99.7% of 1048 days all three ERCOT kinds have a posting within 2 h before every fixed watch (00, 06, 10, 14, 18), so ERCOT's own vintages are deep enough to serve V4-P17's `ercot` windows.
- **HRRR**: 10,664 of 10,664 00/06/12/18Z runs 2019-07-01..2026-10-17 (100.00%); 0 missing; age of the latest run at 10:00 p50 1.0 h, max 2.0 h.
- **EIA-930 ERCO**: 2018-07-01..2026-10-24, DF on 3,034 operating days.
- **Leakage spot checks**: 2,480 served (watch, kind, key) lookups in 16 windows, issued_at <= watch in all: True; 1,797 vintage changes, 0 with an identical sha; sha recomputed for 38,740 vintages, 0 mismatches.

## HRRR (NOAA, as issued; issued_at = cycle + 120 min)

| Year | Runs | Expected | Coverage | Complete f00..fN | Partial | fh max | Backfilled | LastModified lag p50/p90/max (min) | GB read |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 736 | 736 | 100.00% | 735 | 1 | [35, 36] | 736 | - | 151.2 |
| 2020 | 1464 | 1464 | 100.00% | 1460 | 4 | [30, 36, 47, 48] | 1464 | - | 305.6 |
| 2021 | 1460 | 1460 | 100.00% | 1460 | 0 | [48] | 199 | 111.8/114.5/163.7 | 397.8 |
| 2022 | 1460 | 1460 | 100.00% | 1459 | 1 | [48] | 23 | 111.4/114.1/172.7 | 398.0 |
| 2023 | 1460 | 1460 | 100.00% | 1460 | 0 | [48] | 4 | 113.5/116.3/152.2 | 398.1 |
| 2024 | 1464 | 1464 | 100.00% | 1464 | 0 | [48] | 12 | 109.9/112.7/159.3 | 397.5 |
| 2025 | 1460 | 1460 | 100.00% | 1460 | 0 | [48] | 3 | 106.9/109.7/178.1 | 397.7 |
| 2026 | 1160 | 1160 | 100.00% | 1159 | 1 | [48] | 2 | 107.9/115.4/162.7 | 319.9 |

Missing runs: none. Runs with missing forecast hours: 2019-11-22T18Z, 2020-02-14T00Z, 2020-10-08T06Z, 2022-02-26T18Z.

Backfilled runs (S3 LastModified > cycle + 180 min) are kept; the store times every run at cycle + 120 min (V4-P3) and keeps LastModified and the flag for the audit.

## EIA-930 ERCO (reveal: DF 06:00 on its day, demand hour end + 60 min, fuel D+1 06:00)

| Year | Hours/expected | DF | Demand | Wind | Solar | Demand imputed (h) | Subregions |
|---|---|---|---|---|---|---|---|
| 2018 | 4410/4411 | 97.80% | 98.89% | 98.89% | 98.89% | 24 | 0.00% |
| 2019 | 8760/8760 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 59.93% |
| 2020 | 8784/8784 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 100.00% |
| 2021 | 8760/8760 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 100.00% |
| 2022 | 8760/8760 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 100.00% |
| 2023 | 8760/8760 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 100.00% |
| 2024 | 8784/8784 | 100.00% | 100.00% | 100.00% | 100.00% | 0 | 99.98% |
| 2025 | 8760/8760 | 99.45% | 99.73% | 99.73% | 99.73% | 24 | 99.41% |
| 2026 | 7110/7109 | 100.01% | 99.68% | 99.68% | 99.68% | 0 | 99.59% |

## ERCOT public API vintages (2023-12-11 on; issued_at = the API's postDatetime, CPT to UTC)

| Report | Postings | Listed | First | Last | Minute | Days < 23 | Gaps > 1.5 h | Age at 10:00 p50/p95/max (h) | DST postings | Ambiguous |
|---|---|---|---|---|---|---|---|---|---|---|
| NP3-565-CD | 25,144 | 25,144 | 2023-12-11 00:30 | 2026-10-23 23:30 | :30 | 2 | 5 | 0.5/0.5/0.5 | 16,937 | 0 |
| NP4-732-CD | 25,147 | 25,147 | 2023-12-11 00:55 | 2026-10-23 23:55 | :55 | 0 | 7 | 0.08/0.08/0.08 | 16,936 | 0 |
| NP4-742-CD | 25,127 | 25,127 | 2023-12-11 00:55 | 2026-10-23 23:55 | :55 | 3 | 10 | 0.08/0.08/0.08 | 16,916 | 0 |
| NP4-745-CD | 25,142 | 25,142 | 2023-12-11 00:55 | 2026-10-23 23:55 | :55 | 1 | 9 | 0.08/0.08/0.08 | 16,933 | 0 |

- NP3-565-CD largest gaps: 4.0 h after 2026-03-06 15:30 UTC; 2.0 h after 2026-10-05 09:30 UTC; 2.0 h after 2026-03-06 09:30 UTC; 2.0 h after 2026-10-05 11:30 UTC; 2.0 h after 2026-03-06 13:30 UTC
- NP3-565-CD in-use model by hour: E 466,508, E3 357,286, E1 348,941, E2 294,899, X 223,136, M 113,840, A3 3,735, A6 2,023
- NP3-565-CD zones sum vs system total max abs mw: 0.0
- NP3-565-CD fall-back hour postings (local, as the API reports them): 2024-11-01T01:30:00.000, 2024-11-02T01:30:00.000, 2024-11-03T01:30:00.000, 2024-11-03T01:30:00.000, 2024-11-04T01:30:00.000, 2024-11-05T01:30:00.000, 2024-11-06T01:30:00.000, 2024-11-07T01:30:00.000, 2025-11-01T01:30:00.000, 2025-11-02T01:30:00.000, 2025-11-02T01:30:00.000, 2025-11-03T01:30:00.000
- NP4-732-CD largest gaps: 3.0 h after 2024-01-18 21:55 UTC; 2.0 h after 2026-08-06 19:55 UTC; 2.0 h after 2024-05-16 19:55 UTC; 2.0 h after 2026-01-28 20:55 UTC; 2.0 h after 2026-06-04 19:55 UTC
- NP4-732-CD fall-back hour postings (local, as the API reports them): 2024-11-01T01:55:10.000, 2024-11-02T01:55:08.000, 2024-11-03T01:55:09.000, 2024-11-03T01:55:10.000, 2024-11-04T01:55:08.000, 2024-11-05T01:55:09.000, 2024-11-06T01:55:08.000, 2024-11-07T01:55:09.000, 2025-11-01T01:55:12.000, 2025-11-02T01:55:13.000, 2025-11-02T01:55:10.000, 2025-11-03T01:55:11.000
- NP4-742-CD largest gaps: 21.08 h after 2024-09-18 16:55 UTC; 3.0 h after 2024-01-18 21:55 UTC; 2.0 h after 2026-06-04 19:55 UTC; 2.0 h after 2026-01-28 20:55 UTC; 2.0 h after 2026-08-06 19:55 UTC
- NP4-742-CD fall-back hour postings (local, as the API reports them): 2024-11-01T01:55:09.000, 2024-11-02T01:55:08.000, 2024-11-03T01:55:09.000, 2024-11-03T01:55:10.000, 2024-11-04T01:55:08.000, 2024-11-05T01:55:09.000, 2024-11-06T01:55:08.000, 2024-11-07T01:55:09.000, 2025-11-01T01:55:12.000, 2025-11-02T01:55:11.000, 2025-11-02T01:55:11.000, 2025-11-03T01:55:12.000
- NP4-745-CD largest gaps: 3.0 h after 2024-01-18 21:55 UTC; 2.0 h after 2026-01-28 20:55 UTC; 2.0 h after 2026-08-06 19:55 UTC; 2.0 h after 2026-01-08 20:55 UTC; 2.0 h after 2026-10-05 11:55 UTC
- NP4-745-CD regions sum vs system wide max abs stppf mw: 0.0
- NP4-745-CD regions sum vs system wide max abs pvgrpp mw: 0.0
- NP4-745-CD fall-back hour postings (local, as the API reports them): 2024-11-01T01:55:07.000, 2024-11-02T01:55:07.000, 2024-11-03T01:55:08.000, 2024-11-03T01:55:08.000, 2024-11-04T01:55:08.000, 2024-11-05T01:55:08.000, 2024-11-06T01:55:07.000, 2024-11-07T01:55:08.000, 2025-11-01T01:55:10.000, 2025-11-02T01:55:10.000, 2025-11-02T01:55:11.000, 2025-11-03T01:55:09.000

Watch cover (V4-P17's `source` rule): share of days whose five fixed watches each have a posting within 2 h before: ercot_load 99.90%, ercot_wind 99.71%, ercot_solar 99.81%; all three 99.71%.

- ercot_load failing days: 2023-12-11
- ercot_wind failing days: 2023-12-11, 2024-01-18, 2025-03-28
- ercot_solar failing days: 2023-12-11, 2024-01-18

## Archive vs API spot check

NP4-745 posting `PVGR_20261024_0655.zip` cached from MIS by lane D3 vs the same posting through the API (`np4-745-cd_20261024T065512_1290252298.csv`): 216 of 216 rows matched, identical: True; max abs diff by column: COP_HSL_SYSTEM_WIDE 0, STPPF_SYSTEM_WIDE 0, PVGRPP_SYSTEM_WIDE 0, GEN_CenterWest 0, COP_HSL_CenterWest 0, STPPF_CenterWest 0, PVGRPP_CenterWest 0, GEN_NorthWest 0, COP_HSL_NorthWest 0, STPPF_NorthWest 0, PVGRPP_NorthWest 0, GEN_FarWest 0, COP_HSL_FarWest 0, STPPF_FarWest 0, PVGRPP_FarWest 0, GEN_FarEast 0, COP_HSL_FarEast 0, STPPF_FarEast 0, PVGRPP_FarEast 0, GEN_SouthEast 0, COP_HSL_SouthEast 0, STPPF_SouthEast 0, PVGRPP_SouthEast 0, GEN_CenterEast 0, COP_HSL_CenterEast 0, STPPF_CenterEast 0, PVGRPP_CenterEast 0.

## Store

| Kind | Keys | Vintages | Hours | Runs or postings by year |
|---|---|---|---|---|
| ercot_load | 9 | 226,296 | 72-72 | 2023: 498, 2024: 8,784, 2025: 8,760, 2026: 7,102 |
| ercot_solar | 7 | 175,973 | 1-72 | 2023: 498, 2024: 8,780, 2025: 8,759, 2026: 7,102 |
| ercot_wind | 6 | 150,734 | 2-72 | 2023: 996, 2024: 17,550, 2025: 17,504, 2026: 14,208 |
| load | 9 | 76,167 | 72-72 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |
| load_official | 1 | 2,670 | 23-25 | 2019: 184, 2020: 366, 2021: 365, 2022: 365, 2023: 365, 2024: 366, 2025: 363, 2026: 296 |
| mcpc | 5 | 38,767 | 72-72 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |
| price | 13 | 110,019 | 72-72 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |
| solar | 1 | 8,463 | 72-72 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |
| weather | 18 | 152,334 | 8-45 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |
| wind | 1 | 8,463 | 72-72 | 2021: 1,459, 2022: 1,460, 2023: 1,460, 2024: 1,464, 2025: 1,460, 2026: 1,160 |

Sizes (GB): HRRR points 0.124, EIA-930 1.178, ERCOT raw 2.565, store 0.557 (vintages 0.52).

## Leakage spot checks

Windows: fern-0124 (d1 2026-01-24), heather-0114 (d1 2024-01-14), uri-0213 (d1 2021-02-13), spring-0328 (d1 2024-03-28), random-0 (d1 2025-12-02), random-1 (d1 2024-09-08), random-2 (d1 2023-12-17), random-3 (d1 2022-07-26), random-4 (d1 2022-10-15), random-5 (d1 2021-03-31), random-6 (d1 2021-06-11), random-7 (d1 2021-02-07), random-8 (d1 2022-01-08), random-9 (d1 2025-09-15), random-10 (d1 2024-10-04), random-11 (d1 2026-04-13). For each fixed watch of a `front` window and each of `weather/DFW`, `load/system`, `load/NCEN`, `wind/system`, `solar/system`, `price/HB_NORTH`, `mcpc/regup`, `load_official/system`, `ercot_load/system`, `ercot_wind/system`, `ercot_solar/system`, the served vintage (the latest with reveal_at <= the watch) has issued_at <= the watch in all 2,480 lookups (True); across a window's watches 1,797 served vintages changed, 0 of them to a vintage with the same sha.

## Builder leakage tests and the guide card

- Reveal assertion: every feature family's latest reveal minus the vintage's issued_at is <= 0 (eia_demand_last 0 min, eia_demand_same_hour 0 min, eia_subregion_share 0 min, hrrr_run 0 min, eia_fuel_generation -120 min, da_last_day -30 min, rt_last_full_day -120 min, rt_last_24h 0 min, da_known_at_t -30 min).
- Canary (cutoff 2022-07-01T00:00:00, reduced build to 2023-01-01): 100,418 of 100,418 vintages issued before the cutoff identical, 33,856 of 33,856 after it changed: True.
- Quantiles sorted per hour: True.

Guide P50 MAE vs persistence at the DAM horizon (14-38 h), $/MWh, and 80% coverage:

| Year | DA | RT | MCPC | Desk load MAPE | Desk wind nMAE | Desk solar nMAE |
|---|---|---|---|---|---|---|
| 2021 | 61.365 / 60.715 / 0.5741 | 73.575 / 104.371 / 0.6382 | 56.53 / 53.532 / 0.8174 | 0.0576 | 0.3 | 0.2698 |
| 2022 | 29.75 / 20.766 / 0.6924 | 36.148 / 45.508 / 0.755 | 21.259 / 6.995 / 0.8341 | 0.0637 | 0.3153 | 0.2126 |
| 2023 | 26.727 / 23.608 / 0.6762 | 33.351 / 49.397 / 0.7545 | 10.365 / 7.847 / 0.8516 | 0.061 | 0.287 | 0.1916 |
| 2024 | 12.731 / 12.152 / 0.6561 | 15.235 / 21.953 / 0.7597 | 2.212 / 2.297 / 0.8372 | 0.0645 | 0.2794 | 0.2104 |
| 2025 | 9.25 / 11.176 / 0.6736 | 13.021 / 20.82 / 0.7941 | 0.662 / 0.71 / 0.8379 | 0.063 | 0.2641 | 0.1956 |
| 2026 | 14.297 / 14.95 / 0.7827 | 14.979 / 20.524 / 0.7884 | 0.818 / 0.894 / 0.8132 | 0.0606 | 0.2446 | 0.1809 |

The store, its raw pulls (HRRR points, EIA-930 CSVs, ERCOT API zips) and this report's inputs are in Scale-internal object storage under `gridsim/v4/` (`store/store-<sha>.tar.zst`, `raw/`).

