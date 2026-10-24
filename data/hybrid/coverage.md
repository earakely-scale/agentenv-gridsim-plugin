# v3 hybrid inputs: sources, coverage and caveats

Built by `scripts/build_hybrid_inputs.py` from `cache/raw/hybrid/` (fetched by `scripts/fetch_hybrid_inputs.py`), `cache/raw/eia860/`, `cache/raw/ercot-rt/` and lane N's notice archive (`data/notices/`). Times are Central prevailing time (CPT). Every source file and its sha256 is in `manifest.json` (`built_from`).

## Files

| File | What | Key fields |
|---|---|---|
| `as_dam_mcpc.jsonl.gz` | DA AS clearing prices (MCPC), one row per operating day | `date, era, n_hours, regup, regdn, rrs, ecrs, nspin` ($/MW per hour, HE01..HE24; `ecrs` null in era A; DST days carry `hour_ending` and 23/25 values), `source` |
| `solar_cf.jsonl.gz` | Hourly PV availability capacity factor, system-wide | `cf` (availability proxy), `cf_actual`, `repaired_hours`, `installed_mw`, `source`, `scope: system` |
| `deployments.jsonl` | RRS, ECRS and Non-Spin deployment events | `event_id, product, variant, date, start, end, end_basis, planned_end, mw_max, mw_steps, frac, source_notice_id, notice_ids, summary` |
| `durations.json` | The era-keyed AS duration table (same as `gridsim_core.contract.AS_DURATION_H`) | |
| `drift.json` | The seeded regulation-drift fallback spec (`gridsim_core.hybrid_inputs.reg_drift`) | |
| `archetypes.json` | EIA-860 2025 co-located PV+BESS sites in ERCO, the fit, the archetype grid, the default | |

Loader: `gridsim_core.hybrid_inputs` (`as_prices`, `solar_cf`, `pv_profile_mw`, `deployments`, `archetypes`, `reg_drift`).

## Sources

| Input | ERCOT/EIA product | Report type id | Files |
|---|---|---|---|
| DA AS MCPC, yearly | NP4-181-ER Historical DAM Clearing Prices for Capacity | 13091 | DAMASMCPC_2021..2026 (2021-2025 csv, 2026 xlsx through 2026-10-17) |
| DA AS MCPC, daily tail | NP4-188-CD DAM Clearing Prices for Capacity | 12329 | 7 daily csvs, delivery 2026-10-18..2026-10-24 |
| Solar, system-wide 2023-2025 | PG7-126-M Hourly Aggregated Wind and Solar Output | 13424 | ERCOT_2023..2025_Hourly_WindSolar_Output.xlsx (ERCOT.PVGR.GEN, Total Solar Installed MW) |
| Solar, system-wide 2021-2022 and 2026 | ERCOT Fuel Mix Report (gridinfo/generation) | n/a (files/docs) | FuelMixReport_PreviousYears.zip (IntGenbyFuel2021/2022), IntGenbyFuel2026.xlsx (through 2026-09-30) |
| Solar capacity 2021-2022, 2026 | EIA-860M September 2026 (Operating + Retired, BA ERCO, Solar Photovoltaic) | n/a | september_generator2026.xlsx |
| Curtailment hours | NP6-785-ER RT SPPs (v2's RTMLZHBSPP zips) at HB_HUBAVG | 13061 | RTMLZHBSPP_2021..2026 |
| Regional solar (layout only) | NP4-745-CD Solar Power Production, Hourly Averaged Actual and Forecasted Values by Geographical Region | 21809 | one sample file |
| RT AS MCPC era C (layout only) | NP6-331-CD Real-Time Clearing Prices for Capacity by 15-Minute Settlement Interval | 24898 | one sample file |
| RT AS price adders era C | NP6-793-ER Historical RT ORDC and Reliability Deployment Prices (15-min) | 13240 | HIST_RT15MPRICEADDER_2025, _2026 (fetched, not built) |
| Deployments | lane N's archive: ERCOT Operations Messages tagged `as_deployment` | n/a | data/notices/notices.jsonl.gz |
| Hybrid configs | EIA-860 2025 (2___Plant, 3_3 Solar, 3_4 Energy Storage) | n/a | eia8602025.zip |
| Pre-RTC+B SoC rule | NPRR1186 PUCT Report (ercot.com/mktrules/issues/NPRR1186) | n/a | 1186NPRR-36_PUCT_Report_041124.docx |

ERCOT MIS endpoints (`/misapp/servlets/IceDocListJsonWS`, `/misdownload/servlets/mirDownload`) are listed under `Disallow` in ercot.com's robots.txt. They were used as v1 used them, at 1 request per second with a named user agent, about 30 MIS requests in all; everything is cached so a rebuild makes no requests. EIA files come from `/electricity/data/eia860m/xls/` (allowed; `/archive/` is disallowed and was not used).

## 1. DA AS clearing prices

- Coverage: 2021-01-01 to 2026-10-24, 2123 days, no missing dates (gaps: 0); era A 890, era B 909, era C 324 days; 11 DST days kept with 23/25 hours. First ECRS price: 2023-06-10.
- Product mapping: the file columns REGUP, REGDN, RRS, ECRS and NSPIN map one to one to `regup, regdn, rrs, ecrs, nspin` in every era, including after RTC+B (the 2025 file's December rows and the 2026 file keep the same five columns). The DAM clears one RRS MCPC for all RRS sub-types (PFR, FFR, UFR/Load Resources), so v3's single RRS product uses it unchanged; ECRS is one DAM MCPC (on- and off-line ECRS are not priced separately). Non-Spin is the NSPIN column (on- and off-line Non-Spin share it).
- MCPCs are as published. Winter Storm Uri (February 2021) cleared AS above the $9,000 HCAP (up to $25,674 for RRS); those days are out of every split (Uri ±3 days).

| Year | regup mean / max | regdn mean / max | rrs mean / max | ecrs mean / max | nspin mean / max |
|---|---|---|---|---|---|
| 2021 | 244.37 / 24992.9 | 95.57 / 17925.1 | 312.24 / 25674.3 | - | 134.0 / 12866.7 |
| 2022 | 21.67 / 2977.77 | 8.46 / 250.0 | 20.31 / 2976.97 | - | 22.49 / 2976.77 |
| 2023 | 26.79 / 4082.91 | 13.63 / 2961.16 | 21.26 / 4083.28 | 58.15 / 4085.33 | 19.05 / 2715.7 |
| 2024 | 6.01 / 1007.0 | 3.44 / 1455.29 | 5.67 / 1458.75 | 8.23 / 2086.26 | 6.22 / 2150.0 |
| 2025 | 2.98 / 223.25 | 1.62 / 60.97 | 2.76 / 270.0 | 2.46 / 270.0 | 3.05 / 470.92 |
| 2026 | 2.07 / 896.96 | 1.32 / 26.71 | 1.6 / 999.02 | 1.97 / 1000.65 | 4.18 / 432.13 |

## 2. Solar profile

- Coverage: 2021-01-01 to 2026-09-30, 2099 days, no missing dates (gaps: 0). 2026-10 is not covered: ERCOT's 2026 fuel-mix workbook stops at 2026-09-30 and MIS keeps NP4-745-CD for about a week.
- **System-wide only, used for every region.** NP4-745-CD (regional actual, COP HSL, STPPF, PVGRPP; regions CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast, plus SYSTEM_WIDE_HSL) is real, but the MIS document list keeps only the last ~7 days (350 docs, 2026-10-17..24). ERCOT's public API archive (said to start 2023-12-11) needs a subscription key and was not used. So `scope` is `system` in every row and `solar_cf(date, region)` ignores the region. Flagged.
- cf_t = system solar MW / installed MW. 2023-2025 use ERCOT's own hourly `Total Solar Installed, MW` (PG7-126-M). 2021-2022 and 2026 use the fuel-mix 15-minute solar MWh summed per hour, over EIA-860M operable ERCO PV nameplate at month end times ERCOT/EIA calibration: ERCOT's installed figure runs 1.2258-1.4841x EIA's over the 36 overlap months, so 2021-2022 use the median of the first 6 overlap months (1.2991) and 2026 the median of the last 6 (1.2504). Expect about +/-10% level error in those years.
- **Availability proxy (flagged).** Actual output is curtailed output. Where an hour's HB_HUBAVG RT SPP (mean of its four 15-minute prices) is <= 0, `cf` = max(actual, median cf of the same hour on the days within +/-3 whose same hour priced above 0); otherwise `cf` = actual. `cf_actual` keeps the unrepaired value (for the weight-0 historical-operator row). 468 hours on 124 days were raised (example: 2024-03-29 HE09-HE17 cf 0.1834-0.4814 actual, 0.2181-0.6211 repaired). HSL-based availability (max(actual, HSL)) needs NP4-745's history, which is not available, so it is not applied. West-only curtailment at positive hub prices is not detected.
- The plan's plant profile AC x ILR x cf_t (`pv_profile_mw`) treats the fleet cf, which is AC output already clipped at the fleet's inverters (fleet ILR ~1.3), as a DC-side shape; it overstates midday DC potential slightly and is a proxy.

| Year | Days | Mean cf | Days with repaired hours | Sources |
|---|---|---|---|---|
| 2021 | 365 | 0.216 | 12 | fuel-mix+EIA-860M 365 |
| 2022 | 365 | 0.22 | 15 | fuel-mix+EIA-860M 365 |
| 2023 | 365 | 0.219 | 17 | PG7-126-M 365 |
| 2024 | 366 | 0.218 | 28 | PG7-126-M 366 |
| 2025 | 365 | 0.236 | 31 | PG7-126-M 365 |
| 2026 | 273 | 0.254 | 21 | fuel-mix+EIA-860M 273 |

## 3. AS duration table (era-keyed)

`gridsim_core.contract.AS_DURATION_H`, `as_era(d)`, `as_products(d)`, `as_duration_h(product, d)`; new code, nothing existing changed. Era A 2021-01-01..2023-06-09, B 2023-06-10..2025-12-04, C from 2025-12-05.

| Product | Era A | Era B | Era C (NPRR1282) |
|---|---|---|---|
| regup | 1 h | 1 h | 0.5 h |
| regdn | 1 h | 1 h | 0.5 h |
| rrs | 1 h | 1 h | 0.5 h |
| ecrs | n/a | 2 h | 1 h |
| nspin | 4 h | 4 h | 4 h |

- **The pre-RTC+B rule, from the NPRR1186 protocol text** (PUCT Report 1186NPRR-36, approved 2024-04-11; Nodal Protocols 8.1(4)(a)(ii)(A) and 6.5.5.2(14)(a)(ii)(A); fetched to `cache/raw/hybrid/nprr/`): the SoC an ESR must hold for each up AS (ECRS, Non-Spin, RRS, Reg-Up; FFR and FRRS aside) is its responsibility R times (the time left in the operating hour + the AS duration − 1 h); RRS from FFR needs R × 0.25 h; Reg-Down needs headroom R × the time left in the hour. At the top of each hour that is R × duration, sloping to R × (duration − 1 h) at its end.
- What stays open (V3-D1): the text uses "the duration of the Ancillary Service" without stating the values. 1 h for Reg and RRS is consistent with it (the (duration − 1 h) term implies at least 1 h) and is kept, flagged. ECRS 2 h and Non-Spin 4 h follow NPRR1096's sustained-capability titles. NPRR1186 went live 2024-06-27 (ERCOT notice M-B060424-01); before that no SoC rule applied, so applying the table from 2021 is a modelling choice. v3's check of R × duration at both ends of each hour is conservative against the in-hour slope.

## 4. Deployments

- From 1267 archive rows tagged `as_deployment` (1231 parsed messages; 13 ERS rows and EEA rows skipped; 21 cancellations and cancelled rows dropped; 2 unparsed). 32 rows are tagged `ruc` (counted, not events).
- Events: RRS 180, ECRS 56, Non-Spin 141 (all years 2017-2026). End basis: recall 377, planned END_TIME 0, next deploy 0, capped 0.
- Times are minute-stamped. A Non-Spin `CM-ASM-NOTF` message's BEGIN_TIME (often the next hour) is its step time; "At HH:MM" in the text is used when given. Messages apply in issue order, so a recall drops hourly re-deployments scheduled after it.
- MW: Non-Spin messages state system MW (`mw_max`, `mw_steps`). RRS and ECRS messages never state MW or a fraction, so `mw_max` is null. `frac` is null on every event: the system deployed share of the procured quantity needs the hourly AS plan or DAM procured MW, not fetched tonight. Core needs a labelled rule for frac (for example 1.0 of the award for the event window capped by the era's duration, the stress case the reservation rule already covers).
- `summary` is generated from the parsed fields; no verbatim notice text is stored.
- The archive has no RRS deployment message after 2023 and no ECRS one after 2025 (no untagged RRS/ECRS deployment wording either); after RTC+B, SCED releases reserves itself and only Non-Spin messages remain. Era C days therefore carry Non-Spin events only.
- Coverage follows the archive's operations-message coverage: 2021 0.995, 2022 0.999, 2023 1.0, 2024 0.992, 2025 0.986, 2026 0.991 (share of each day covered).

| Year | RRS | ECRS | Non-Spin | events with MW |
|---|---|---|---|---|
| 2021 | 40 | 0 | 8 | 8 |
| 2022 | 33 | 0 | 24 | 24 |
| 2023 | 8 | 44 | 33 | 33 |
| 2024 | 0 | 9 | 20 | 17 |
| 2025 | 0 | 3 | 15 | 14 |
| 2026 | 0 | 0 | 40 | 40 |

## 5. Regulation drift

System-level regulation fractions were not derived tonight (they would need regulation-deployment telemetry, which the public 60-day SCED disclosure does not carry as a signal). The seeded fallback is implemented: `gridsim_core.hybrid_inputs.reg_drift(task_id)` draws hourly RegUp and RegDn fractions from Beta(m·k, (1−m)·k) with m = 0.12 and 0.18, k = 6, seeded by `stable_seed(task_id + '|reg-drift')`. The pack builder stores the draw in the task row so episodes replay exactly. Label on the card: "Regulation drift is a seeded draw, not ERCOT telemetry".

## 6. EIA-860 hybrid archetypes

- 22 co-located PV+BESS sites in ERCO in EIA-860 2025 (same_plant 16, nearby_named 5, direct_support 1); 5 fall in the archetype window (PV 100-300 MWac, BESS 0.4-0.8 of PV MW, 1-2 h).
- PV MWac median 230.5 (p10 98.68, p90 386.62); ILR median 1.285 (p10 1.219, p90 1.411; MWdc reported for all); BESS/PV MW median 0.462; duration median 1.52 h.
- Coupling flags (3_4): independent 0.682, ac 0.318. No matched ERCO site reports DC or DC-tightly coupled storage, so the plan's ~70% AC / ~30% DC split is not supported by EIA-860 2025; many sites flag neither ("independent").
- Regions (coarse lat/lon boxes): west 8, north 8, central 3, south 2, houston 1.
- Default: 150 MWac / 195 MWdc PV, 100 MW / 200 MWh BESS, 150 MW POI (variant 180 MW). The grid (`archetypes`) is PV 100/150/200/300 MWac × BESS 0.4/0.67/0.8 of PV × 1/2 h, ILR at the fit median, POI = PV AC with a 1.2× variant; weights are in-window site counts per nearest cell plus 0.5 smoothing (the sample is small, so weights are near uniform).

## 7. RT AS MCPC (era C)

- The post-RTC+B report is **NP6-331-CD, Real-Time Clearing Prices for Capacity by 15-Minute Settlement Interval, report type 24898** (long format: DeliveryDate, DeliveryHour, DeliveryInterval, RepeatedHourFlag, ASType in REGUP/REGDN/RRS/ECRS/NSPIN, MCPC). The SCED-interval version is NP6-332-CD (24891).
- History: MIS keeps 7 days (702 csvs, 2026-10-17..24). No yearly historical file for RT MCPC was found. NP6-793-ER (13240) has HIST_RT15MPRICEADDER_2025/2026 from 2025-12-05 with per-AS reliability deployment price adders (RTRDPRU, RTRDPRD, RTRDPRRS, RTRDPECRS, RTRDPNS), which are adders, not MCPCs. ERCOT's API archive may hold the history but needs a key. **T3 cannot be built tonight; drop it, or start a daily NP6-331-CD capture.**
