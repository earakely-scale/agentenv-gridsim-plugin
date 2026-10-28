# Desk data: sites, days, series, calibration, PRC proxy and the desk price forecast

Lane DATA's companion to `docs/CONTRACT-desk.md` §1. That contract defines the schemas; this file records where each
field comes from, which sites and days were chosen and why, how the battery was calibrated, the proposed PRC proxy,
the desk price forecast, and the known gaps and errata.

## Pipeline

| Step | Script | Output (git) | Raw cache (scratchpad, never git) |
|---|---|---|---|
| ERCOT API client (ROPC token, SSM credentials, ≤ 30 req/min shared) | `scripts/desk_data_api.py` (wraps `fetch_disclosure.Client`) | — | `$DESK_RAW/{query,archive,listing,meta}` |
| ESR site registry | `scripts/desk_data_sites.py` | `data/desk/sites.parquet` | CDR, crosswalk xlsx in `$DESK_RAW/web` |
| Node and hub price history 2024-01..2026-08, DAM MCPC | `scripts/desk_data_history.py` | — | `$DESK_RAW/history/*.parquet` |
| Calibration (RTE, standby, ramp) | `scripts/desk_data_calibrate.py` | `data/desk/calibration.{json,md}` | |
| PRC proxy fit and validation | `scripts/desk_data_prc.py` | `data/desk/prc_proxy.json` | `$DESK_RAW/history/prc_2025.parquet` |
| Desk price forecast desk-qr-v1 | `scripts/desk_data_forecast.py` | `data/desk/forecast/report.json` | `$DESK_RAW/forecast/vintages` |
| Packs | `scripts/desk_data_build.py [pack ...]` | `data/desk/<pack>/{manifest.json,tasks.jsonl.gz,series/}` | |

Rebuild: `sites → history → calibrate → prc → forecast → build`. Every API response is cached by (endpoint, params),
so a rebuild without network reproduces the packs byte-for-byte (gzip mtime 0). `$DESK_RAW` defaults to the lane
scratchpad. `DESK_API_GAP` sets the per-process gap between requests (4.5 s; use 6.5 s with three processes).
Credentials are read from SSM (profile `agent-environments-admin`, override with `DESK_AWS_PROFILE`) inside the
process and are never printed or written.

robots.txt: everything comes from `api.ercot.com` or `www.ercot.com/files/docs/...` (allowed). Nothing is fetched
from `/misapp` or `/misdownload`. NP4-160-SG (settlement point mapping) is MIS-only and not in the API, so it is not
used. Load zone and hub come from the CDR zone and county (below).

## 1. ESR site registry (`data/desk/sites.parquet`)

339 ESRs, one row per post-RTC+B single-model resource.

| Column group | Source |
|---|---|
| `resource_name`, `settlement_point`, `qse`, `dme`, `hsl_mw` (max), `lsl_mw` (min), `first/last_seen_post`, `days_post`, `days_on_post`, `n_qse`, `n_settlement_points` | NP3-966-ER 60d DAM ESR Data, HE1 of every day 2025-12-06..2026-08-28 (API query) |
| `max_soc_mwh` (max), `min_soc_mwh` (min), `max_soc_median_mwh`, `sced_hsl/lsl_mw`, `soc_reported_share` | NP3-965-ER 60d ESR Data in SCED: one 5-minute snapshot at 03:00, 12:00 and 19:00 on the 15th of each month, Dec 2025..Aug 2026 (28 snapshots) |
| `power_mw` = max(DAM HSL, SCED HSL); `duration_h` = (MaxSOC − MinSOC) / power | derived |
| `pre_gen_resource`, `pre_load_resource` | ERCOT combo-to-single-model crosswalk `single-model-esr-names_16Jun2025.xlsx` (267 rows) |
| `first/last_seen_pre`, `pre_settlement_point`, `pre_qse`, `pre_hsl_mw` | NP3-966-ER 60d DAM Gen Resource Data, type PWRSTR, HE1, API rows from 2024-01-19 |
| `cdr_name`, `county`, `cdr_zone`, `in_service_date`, `installed_mw`, `cdr_status`, `cdr_wind/solar_region` | CDR Dec 2025 "Unit Details" (by pre-RTC+B unit code) and "Wind-Solar Region Mapping" |
| `first_operating_date` | the CDR in-service date when it is earlier or the first API row is the API floor (2024-01-19); else the first DAM row. `first_operating_date_source` says which |

Coverage: all 339 have MaxSOC; 254 map to a pre-RTC+B Gen/Load pair; 313 have a CDR county.

## 2. Sites (S01–S04)

Selection filters:
- 90–210 MW;
- 0.9–2.3 h;
- in service from go-live, ON in the DAM on ≥ 250 days;
- SoC telemetered in 100% of snapshots;
- one QSE and one settlement point throughout.

35 ESRs pass. From them, one site per region, with different QSE families and a spread of durations. The calibration
fit was also checked (below).

| Site | Resource | Node | Region (county, CDR zone) | Hub / load zone | MW / MWh / h | QSE (DME) | Pre-RTC+B pair |
|---|---|---|---|---|---|---|---|
| S01 | CROSSETT_ESR1 | CROSSETT_ALL | Far West (Crane, WEST) | HB_WEST / LZ_WEST | 100 (charge 96) / 104 / 1.04 | QJPEM1 (Jupiter; QJPEM until 2026-01-06) | CROSSETT_BES1 / CROSSETT_LD1 |
| S02 | CLO_ESR1 | CLO_RN | Houston (Harris, HOUSTON) | HB_HOUSTON / LZ_HOUSTON | 100 / 206 / 2.06 | QMEA1 (YMEA) | CLO_BESS1 / CLO_LD1 |
| S03 | WIG_ESS_ESR1 | WIG_BESS_RN | North (Collin, NORTH) | HB_NORTH / LZ_NORTH | 120 / 187 / 1.56 | QHEI1 (Habitat) | WIG_ESS_BES1 / WIG_ESS_LD1 |
| S04 | WFTANK_ESR1 | WFTANK_ESS1 | South (Webb, SOUTH) | HB_SOUTH / LZ_SOUTH | 150 (charge 160) / 185 / 1.23 | QTEN28 (YWOLFT) | WFTANK_ESS1 / WFTANK_LD1 |

- **Durations** span 1.0 to 2.1 h; **sizes** 100 to 150 MW.
- **Operators.** Four QSE families: Jupiter, MEA, Habitat, Tenaska-agent. Their DAM styles differ: S03 (Habitat) leaves most DAM hours without an EB/OC and trades in RT.
- **Load zone and hub** come from the county and the CDR zone; NP4-160-SG is MIS-only, so this mapping is not from ERCOT's mapping file.
- **Dropped candidate.** HYDR_ESS_ESR1 (Pecos, 200 MW / 203 MWh, QSUE74) was the first West pick. Its SoC telemetry is inconsistent with its output: hourly-balance R² 0.86, implied η_d > 1 and RTE 0.97. CROSSETT (R² 0.97) replaced it.
- **Card names.** Real names never reach the agent. Cards read "Battery S0x", with the region and size.

## 3. Days

**Constraints**
- Post-RTC+B and ≥ 60 days old, so the 60-day disclosures exist: 2025-12-20..2026-08-25.
- No DST change in D-7..D. This excludes 2026-03-08..2026-03-15.

The **v2 eval** pack is 8 days × 4 sites = 32 battery-days. The days were picked from hub RT/DAM statistics, the
notices archive and NWS:

| Day | Kind | Why |
|---|---|---|
| 2026-01-25 (Sun) | winter storm | Winter Storm Fern: DOE 202(c) orders 01-25/26, Transmission Emergency 01-25 21:04, hub RT mean $263 |
| 2026-02-24 (Tue) | negative | wind-driven: hub RT mean $3.3, min −$29.7, 4.5 h negative at the hub |
| 2026-03-23 (Mon) | spring volatile | hub RT max $936 on a shoulder day |
| 2026-04-24 (Fri) | shoulder scarcity | hub RT max $1,085, no notices (a price event with no warning) |
| 2026-05-03 (Sun) | negative (solar) | hub RT mean $9.8, midday negative |
| 2026-06-24 (Wed) | notices | Advisory 13:27 postponing the next DAM's posting, 1,013 MW Non-Spin deployed 20:34–22:19 |
| 2026-07-22 (Wed) | summer peak | hub RT max $349, Non-Spin deployed 19:42–22:25 |
| 2026-08-23 (Sun) | summer peak | hub RT max $560, 13 notices, Non-Spin 18:54–22:05 |

**Pilot** (2 battery-days, outside the eval days):
- 2026-04-27 S01: hub RT max $784, West congestion.
- 2026-08-17 S03: summer, $458 node max, Non-Spin deployment.

**Pre-RTC+B smoke** (`desk-v2-pre`):
- 2025-05-16 S02: hub RT max $2,350.
- 2025-08-20 S03: summer, $326.

**AS versions (v3+).** Seven of the eight eval days fall after 2026-02-02. 2026-01-25 is inside the
M-B040326-01 window, where null AS offer prices were written as $0. On that day the operator's AS offer replay is
unreliable; flag it in v3 or swap in 2026-01-28 (Non-Spin deployment, $1,281). Its energy data is unaffected.

Per-task tags (`day_kind`, `notices`, `max/min_rt_lmp`, `dam_spread`, `neg_lmp_intervals`) are computed at the node.

## 4. Series fields and their sources

| Series key | Source | Notes |
|---|---|---|
| `dam_spp`, `dam_spp_hub` | NP4-190-CD (query by settlement point) | D-7..D; `posted.dam` = the real posting minute of the NP4-190-CD file (archive `postDatetime` on D-1), e.g. 13:56 for 2026-06-24 |
| `rt_spp`, `rt_spp_hub` | NP6-905-CD | D-1, D |
| `rt_lmp` | NP6-788-CD | per SCED run → 5-min grid, last run per interval, carry-forward; fills counted in `manifest.sced_fill` |
| `dam_mcpc` | NP4-188-CD | D-7..D, keys regup/regdn/rrs/ecrs/nspin |
| `rt_mcpc`, `rt_mcpc_15` | NP6-332-CD (capped MCPC, per SCED), NP6-331-CD | post-RTC+B only, D-1 and D |
| `asdc` | NP4-212-CD | the latest posting ≤ D-1 06:00 (else the first); curves Douglas-Peucker-simplified to price error ≤ max($0.50, 1%) (raw NSPIN curves have ~6,500 points per hour) |
| `system.lambda` | NP6-323-CD (post); NP6-792-ER yearly file (pre) | 5-min grid |
| `system.prc_mw` | pre: NP6-792-ER PRC (`real`); post: the proxy (§6, `proxy`) | |
| `system.load_mw` | NP6-345-CD hourly actual system load, repeated on the 5-min grid | NP6-235-CD (15-min) only holds ~7 months in the API |
| `system.wind_mw`, `solar_mw` | NP4-733-CD, NP4-738-CD actual 5-min system generation | |
| `forecasts` | v4 forecast store (`cache/forecast/store`, built from NP3-565-CD in-use model, NP4-742-CD, NP4-745-CD) | system zone; every hourly vintage issued D-1 00:00..D 23:59; horizon cut at D+1 24:00 (store keeps 72 h) |
| `outage_capacity` | NP3-233-CD | every posting D-1..D; values = Σ zones (resource + IRR outage MW), hourly from the first operating hour in the posting |
| `unit_events` | NP1-346-ER daily Unplanned Resource Outages (posted ~3 days late) | reports posted D+1..D+6 filtered on the ESR unit code (and the pre-RTC+B gen code); `hsl_mw` = available MW during outage |
| `notices` | `data/notices/notices.jsonl.gz` (previews archive, covers through 2026-10) | minute-stamped, operator-relevant or grid-condition, issued D-2..D |
| `nws` | `data/notices/nws_vtec.jsonl.gz` (IEM VTEC) | the site's region (west/houston/north/south), in force D-2..D |
| `deployments` | — | `[]` in v2; v3 adds them |
| `desk_forecast` | desk-qr-v1 (§7) | |
| `operator` | NP3-966-ER 60d DAM ESR Data; NP3-965-ER 60d ESR Data in SCED; NP3-991-EX 60d COP All Updates | below |

Operator record:
- **Post-RTC+B.**
  - `dam`: the 10-point EB/OC per hour (null when the operator submitted none), award, SPP, status, and AS awards.
  - `sced`: EB/OC at each change, then base point, telemetered net output, SoC, HSL/LSL, MinSOC/MaxSOC and status on the 5-min grid, plus AS awards.
  - `cop`: per hour, the last non-cancelled update submitted before T−60 (HBSOC, MinSOC/MaxSOC, HSL/LSL, status).
- **Pre-RTC+B.**
  - `dam.pre.offer` is the Gen Resource curve. `dam.pre.bid` is the operator's DAM energy bid at the node from 60d DAM Energy Bids filtered by settlement point and QSE. This assumes the operator bid ESR charging as a node DAM energy bid, as the brief infers.
  - `sced` holds the gen curve, the CLR bid curves (`bid_curves`) and net = gen − load base points and telemetry.
  - **SoC is not in the pre-RTC+B 60-day SCED API**, so `soc_mwh` is null and `soc0` is the default (50%).
- **`operator_ok`.** DAM rows exist for all 24 hours, ≥ 250 SCED rows, and (post) SoC is never null.
- **`soc0_mwh`.** The last disclosed SCED SoC on D-1, clipped to [e_min, e_max].

## 5. Calibration (`data/desk/calibration.md`)

**Windows.** 2026-02-03..2026-03-02 and 2026-06-01..2026-06-28. These are post-erratum days with SoC present.

**Fit.**
- For each hour block where the unit is ON and SCED gaps are ≤ 10 min: ΔSoC = a·C − k·D − ℓ·S̄·T.
- C and D are charged and discharged AC MWh, from telemetered net output (left Riemann sum over SCED runs). S̄ is the mean SoC and T the block hours.
- Huber-weighted least squares. 90% CIs from a 300-draw day-block bootstrap.
- RTE = a/k, clipped to [0.70, 0.98]. Standby = 100·ℓ %/h, clipped to [0, 1].
- Ramp = the median telemetered `rampRateUp`, capped at HSL per minute (S04 telemeters 999 MW/min).

| Site | RTE (90% CI) | standby %/h (90% CI) | R² | hours |
|---|---|---|---|---|
| S01 CROSSETT | 0.902 (0.892–0.912) | 0.18 (0.15–0.23) | 0.967 | 1,324 |
| S02 CLO | 0.907 (0.900–0.913) | 0.62 (0.56–0.69) | 0.995 | 1,339 |
| S03 WIG | 0.860 (0.851–0.869) | 0.71 (0.65–0.77) | 0.991 | 1,338 |
| S04 WFTANK | 0.888 (0.880–0.896) | 0.72 (0.66–0.79) | 0.989 | 1,341 |

**What the standby term includes.** It is the site's auxiliary and self-discharge loss as seen in its telemetered
SoC. Idle hours confirm the scale: S03 loses about 0.9 MWh/h at a mean SoC of 83 MWh. The η_c/η_d split depends on
where the operator meters SoC: η_c or η_d sometimes comes out > 1. Core splits RTE symmetrically (contract §1.3).

**Alternative model.** Adding a constant-auxiliary term (−m·T) moves RTE by ≤ 0.02 on S02–S04. It is not used.

## 6. PRC proxy (proposal; formula to agree with CORE)

**Problem.** Post-RTC+B, NP6-323-CD no longer posts PRC.

**Proposal.** Use only fields public in both eras:

```
headroom = RTOLHSL − actual system load (NP6-345-CD, hour of the SCED run)
pre:  PRC ≈ a + b · headroom                    (fit 2025-01-01..2025-08-31 on NP6-792-ER PRC)
post: PRC_proxy = a + b · (s · headroom + c)    (s, c: quantile-matching the post headroom distribution
                                                 2025-12-05..2026-01-31 onto 2025-10-01..2025-12-04)
```

**Fitted values** (`data/desk/prc_proxy.json`):
- a = 7,383 MW, b = 0.329, s = 0.766, c = −6,447 MW.
- Held-out test, 2025-09-01..2025-12-04, n = 27,569 SCED runs:
  - MAE 1,375 MW, RMSE 1,604 MW, bias −333 MW, corr 0.82;
  - MAE 2,313 MW where PRC < 7,000 MW.

**Era break.** Median headroom roughly doubles across go-live, from 10.3 GW in the last pre-RTC+B fortnight to 21.5
GW in the first post fortnight. This is consistent with RTOLHSL changing definition under the single ESR model;
ERCOT does not document the change. The rescale (s, c) handles it. It assumes reserve conditions in Dec 2025–Jan 2026
resemble Oct–Nov 2025.

**Weak spot.** The proxy regresses toward the mean, so it understates tightness: low-PRC MAE is about 2.3 GW. Adding
system lambda as a feature gained little (low-PRC MAE 2,148 MW), so it is left out.

**Label.** The proxy is `prc_kind: "proxy"` and modelled.

**For CORE.** `eea_level` and Watch thresholds (PRC < 3,000 MW) should come from the notices, not from the proxy.

## 7. Desk price forecast desk-qr-v1 (`data/desk/forecast/report.json`)

**Targets**
- Node DAM SPP: one vintage per operating day, issued D-1 06:00, 24 hourly values.
- Node RT SPP, hourly mean of the 15-min SPP: hourly vintages from D-1 06:00 to D 23:00, each covering its issue hour
  to D 24:00 (step 60).

**Features.** Each feature is read as public at the issue time t:
- **Calendar:** hour, day of week, month.
- **DAM:** DAM at T if posted by t (D-1 13:30), DAM at T−24 h and T−168 h, hub DAM at T−24 h.
- **RT:** last full RT hour, 24 h RT mean/max/min, last RT − DAM, RT at T−24 h if ended by t.
- **ERCOT forecasts:** load, wind, solar and net load at T from the latest vintage ≤ t; net-load daily max and min.
- **Horizon** (RT model only).

**Members.** The v1 teacher ensemble: P50 = 0.1 ridge + 0.5 LightGBM (quantile 0.5) + 0.4 MLP. P10 and P90 come from
LightGBM quantile models. All are fitted in asinh(x/50) space and pooled over the four nodes. RT training uses issue
times every 3 h.

**Refits.** Monthly, expanding window from 2024-01-08. The month-M model sees only targets revealed before M-01 00:00
CPT, so every vintage in a pack is out of sample.

**Band widening.** Split-conformal: the month-M bands are widened by the 90th-percentile normalised exceedance of
month M−1's out-of-sample errors. Month M−1's targets are revealed before M-01.

**Results.** Pinball loss ($/MWh, mean of q10/q50/q90) on every day of Dec 2025–Aug 2026, all four nodes, against
the contract's NaiveForecaster rule on the same rows: see `held_out_post_rtcb` in the report; summary in §9 below.

## 8. Errata and gaps

**Errata**
- **M-B040326-01:** null AS offer prices written as $0 from 2025-12-05 to 2026-02-02. Affects only the 2026-01-25 operator AS replay (v3). Energy is unaffected.
- **M-B020626-01:** SoC missing on 2025-12-05. Not used: no task or calibration day falls on it.
- **M-A021826-01:** RRS sub-type capability missing 2025-12-05..12-20. Not used.

**Gaps**
- **NP4-160-SG mapping** is MIS-only, so load zone and hub are inferred from the CDR zone.
- **Pre-RTC+B SoC** is not disclosed in the API, so pre tasks have `operator_ok` without SoC and `soc0` is the default.
- **Real-time load** is hourly (NP6-345-CD), not 5-min. NP6-235-CD keeps only ~7 months in the API.
- **ERCOT forecast horizon** is 72 h in the store. This is enough for one-day tasks; v4's 3-day windows need the raw postings (168 h), re-pulled from the API.
- **Post-RTC+B PRC** has no public history; the series uses the proxy (§6).
- **2026-06-24 DAM delay.** The Advisory at 13:27 postponed the DAM posting for 2026-06-25, not the task's own DAM (posted 06-23 13:56). It is an inbox event only.
