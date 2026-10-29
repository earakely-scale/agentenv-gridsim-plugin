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

**Tune pack** (`desk-v2-tune`): CORE uses it to tune the anchor's risk setting and DAM basis, so that the eval days
are never used to choose a reference. It has 12 post-RTC+B battery-days, all operator_ok and disjoint from eval and
pilot. Each site gets three days across the season:

| Site | Days |
|---|---|
| S01 | 2026-01-12, 04-15, 07-14 |
| S02 | 2026-02-11, 05-20, 08-05 |
| S03 | 2026-01-14, 04-02, 06-17 |
| S04 | 2026-03-04, 05-27, 08-12 |

Most of these are ordinary days; 2026-03-04 has negative prices and 2026-06-17 carries notices.

CROSSETT_ALL's RT SPP is incomplete on 2026-01-08, 03-08, 06-04 and 07-09. The builder rejects tasks with null
prices, so those days are not used for S01.

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
| `unit_events` | NP1-346-ER daily Unplanned Resource Outages (posted ~3 days late) | reports posted D+1..D+6 filtered on the ESR unit code (and the pre-RTC+B gen code). `hsl_mw` is the available MW during the outage. `end` is the realized end (actual, else the latest planned). `end_planned` is the Planned End Date in the first report listing the outage, about 3 days after it starts (REVIEW F3); no earlier public record of the expected end exists |
| `notices` | `data/notices/notices.jsonl.gz` (previews archive, covers through 2026-10) | minute-stamped, operator-relevant or grid-condition, issued D-2..D |
| `nws` | `data/notices/nws_vtec.jsonl.gz` (IEM VTEC), with `expires_initial` = IEM `init_expire` from the raw IEM cache | the site's region (west/houston/north/south), in force D-2..D (by initial expiry). From desk-v2-tune on, the folded final expiry (`expires`) is dropped (REVIEW F15); desk-v2-eval/pilot still carry it and core masks it |
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

**Results.** Pinball loss in $/MWh, the mean of q10/q50/q90. Every day of Dec 2025–Aug 2026, all four nodes. The
baseline is the contract's NaiveForecaster rule (§8.4) on the same rows.

| Market | n | desk-qr-v1 | naive | P50 MAE (model / naive) | 80% band coverage (model / naive) |
|---|---|---|---|---|---|
| DAM | 26,304 hours | **4.18** | 6.20 | 12.0 / 17.8 | 0.77 / 0.70 |
| RT (hourly, all horizons) | 989,688 hour-targets | **4.78** | 6.02 | 13.5 / 17.1 | 0.79 / 0.70 |

**By month.** Before widening, the DAM band covered only 51–72%. With widening it covers 68–86%. The model beats
naive in every month except DAM 2026-07 (2.53 vs 2.25). Winter Storm Fern dominates 2026-01: DAM 15.0 vs 23.1, RT 8.2
vs 13.7. The per-month and per-node detail is in the report.

## 8. Errata and gaps

**Errata**
- **M-B040326-01:** null AS offer prices written as $0 from 2025-12-05 to 2026-02-02. Affects only the 2026-01-25 operator AS replay (v3). Energy is unaffected.
- **M-B020626-01:** SoC missing on 2025-12-05. Not used: no task or calibration day falls on it.
- **M-A021826-01:** RRS sub-type capability missing 2025-12-05..12-20. Not used.

**Gaps**
- **NP4-160-SG mapping** is MIS-only, so load zone and hub are inferred from the CDR zone.
- **Pre-RTC+B SCED disclosures in the API.** They carry no SoC field. The 60d SCED Gen/Load Resource endpoints also return only one SCED run per 15 minutes (96 a day; the NP3-965-ER archive zips were not checked). Pre tasks therefore have `soc_mwh` null, `soc0` at the 50% default, and SCED curves carried forward 15 minutes. Their `operator_ok` requires ≥ 90 SCED rows, not 250.
- **Pre-RTC+B DAM bids.** `dam.pre.bid` aggregates every DAM energy bid by the operator's QSE at the node, as MW wanted at each price. It may include bids that are not the battery's (for example a QSE's load at the same node).
- **Real-time load** is hourly (NP6-345-CD), not 5-min. NP6-235-CD keeps only ~7 months in the API.
- **ERCOT forecast horizon** is 72 h in the store. This is enough for one-day tasks; v4's 3-day windows need the raw postings (168 h), re-pulled from the API.
- **Post-RTC+B PRC** has no public history; the series uses the proxy (§6).
- **2026-06-24 DAM delay.** The Advisory at 13:27 postponed the DAM posting for 2026-06-25, not the task's own DAM (posted 06-23 13:56). It is an inbox event only.

## 10. v3 "Sun, Storage and Reserves" data (lane DATA2, `scripts/desk_data_v3.py`)

`desk_data_build.build_task` calls `desk_data_v3.extend` for every layer above v2; the v2 fields (`dam_mcpc`,
`rt_mcpc`, `rt_mcpc_15`, `asdc`, `posted.asdc`, DAM and SCED `as_award_mw`) come from DATA's builder unchanged.

| Series key | Source | Notes |
|---|---|---|
| `as_plan` | NP4-33-CD DAM AS Plan | per operating day the latest posting at or before D-1 06:00 (ERCOT posts daily at 05:00 for seven days); products regup/regdn/rrs/ecrs/nspin, MW per hour; `posted_at` records the posting **[data]** |
| `reg_deploy` | `gridsim_core.hybrid_inputs.reg_hourly` over `data/hybrid/reg_deploy.jsonl.gz` | ERCOT storage-fleet regulation deployment measured from the 60-day SCED disclosure (2023-10-12..2026-08-25; `source: measured`), the fitted fallback elsewhere (`modelled`); RT input is the node's hourly mean RT SPP **[data]**/**[modelled]** |
| `deployments` | `data/hybrid/deployments.jsonl` (ERCOT operations notices) | RRS/ECRS/Non-Spin events overlapping an operating day; `frac` null = the whole award; `mw_max`, `notice_ids` kept **[data]** |
| `pv`, `forecasts` kind `pv`, `site.pv` | NP4-745-CD regional actual and STPPF, NP4-738-CD 5-min system shape, EIA-860M system AC capacity | the PV option (below) **[modelled]** |
| `operator.dam[d].as_offers` | NP3-966-ER 60-Day DAM ESR AS Offers (pre-RTC+B: DAM Generation Resource AS Offers) | {product: [24 x [[MW, $/MW/h], ...] or null]} |
| `operator.sced[d].as_offer_updates` | NP3-965-ER 60-Day SCED Resource AS Offers | [{t, product, blocks}] at every SCED run where a product's offer in force changed |
| `operator.cop[d].as_capability` | NP3-991-EX COP All Updates (REGUP, REGDN, RRSPFR, RRSFFR, ECRS, NSPIN) | per hour, the update in force at T-60 (the COP block's rule) |
| `operator.dam[d].as_awards` (pre only) | NP3-966-ER DAM Generation Resource Data | post-RTC+B uses DATA's `as_award_mw` |

**Operator AS offers.** ERCOT's AS offers are linked: one block's MW carries a price per product it may clear in. In
the DAM disclosure each row is one offer and `quantityMW{i}` is block i's own MW (checked against the awards: the
award never exceeds the sum of a product's blocks, while the cumulative reading is exceeded in 24 of 95 awarded
product-hours on two CROSSETT days). In the SCED disclosure `quantityMW{i}` is cumulative per product over the blocks that
price it (each product's curve then ends at HSL − LSL, e.g. CLO 180 MW at $6 + the proxy block to 200 MW). The SCED
rows are the offer SCED used each run: the QSE's RT offer, its DAM offer carried into RT and the proxy extension ERCOT
adds (`quantityMW6`), so `as_offer_updates` already contains the proxy blocks at their posted prices. The desk takes
one offer per product, so each block is offered to every product it prices, merged to at most five blocks per product
(equal prices summed, then the closest adjacent prices at their MW-weighted price) and capped at HSL − LSL
**[simplified]**: the replay can clear the same MW in two products where ERCOT's linked offer clears it once; the
co-clear's headroom row (energy + up AS ≤ HSL) bounds the overlap. No 20% RRS-PFR cap is applied to the operator's
data: CROSSETT (HSL 100, LSL −96) was awarded 85 MW of DAM RRS-PFR in HE11 on 2026-04-20. Off-line Non-Spin (`OFFNS`) and RRS-UFR rows are dropped (ESRs
offer neither on the desk).

**PV option (modelled).** One third of the eval battery-days carry a co-located plant (`site.pv`): AC nameplate
0.6 × HSL rounded to 5 MW, DC/AC 1.3, behind the POI = HSL. Hourly output = mw_ac × 1.3 × gen_region(h) / cap_region,
clipped at mw_ac, where gen_region is ERCOT's actual solar generation in the site's NP4-745-CD region and cap_region =
the region's share of system solar output in the D-1 06:00 posting × the EIA-860M system AC capacity
(`data/hybrid/solar_cf`). Within the hour the profile follows the 5-minute system solar actual (NP4-738-CD). The
`forecasts` kind `pv` vintages apply the same scaling to every hourly STPPF posting from D-1 00:00 to the last
operating day 23:00 (horizon to the last day + 24 h). Region assignment by county (NP4-160-SG is MIS-only and the CDR
maps only Far West/West): S01 Crane → FarWest, S02 Harris → SouthEast, S03 Collin → CenterEast, S04 Webb → SouthEast
(our assignment, **[modelled]**). Core curtails PV when the node LMP < 0.

**Errata respected.** Every v3/v5 post-RTC+B day is after 2026-02-02 (M-B040326-01 null AS prices written as $0), so
neither the SoC gap of 2025-12-05 (M-B020626-01) nor the missing RRS capability of 12/5–12/20/2025 (M-A021826-01)
touches a task.

**Not built.** `desk_forecast` markets `as_dam`/`as_rt` are absent: core's labelled fallback (the latest posted DAM MCPC
day ±50% and the history RT/DA ratio) prices AS views.

**Packs and days** (all post-RTC+B days after 2026-02-02 and ≥ 60 days old; no overlap with desk-v2-tune, the
v2 pilot or desk-v4-*; 2026-04-24 is also a v2-eval day, chosen for its scarcity):

| Pack | Battery-days | Days (CPT) | PV option |
|---|---|---|---|
| `desk-v3-pilot` | 2 | 2026-04-20 S01 (quiet, $244 node max), 2026-08-14 S03 (quiet) | 04-20 S01 |
| `desk-v3-eval` | 24 | 2026-04-11 (negative/outage days; S04 node to −$80), 04-24 (scarcity, node max $1,043–1,351, no notices), 05-26 (quiet), 06-06 (9 notices, Non-Spin deployed), 07-21 (7 notices, Non-Spin deployed), 08-22 (summer, RT MCPC to $188) × S01–S04 | 8: 04-11 S01, 04-24 S01, 05-26 S02/S04, 06-06 S03, 07-21 S02/S04, 08-22 S03 |
| `desk-v3-pre` | 2 | 2025-06-24 S04, 2025-10-21 S01 (scarcity, $609; Non-Spin deployed) | 06-24 S04 |

Day kinds in desk-v3-eval: notice 8, quiet 6, scarcity 4, outage 3, negative 3; `operator_ok` 24/24.

**Hub SCED LMP.** v3+ series carry `rt_lmp_hub` {date: [288]}: the 5-minute SCED LMP at the site's hub (NP6-788-CD),
D-1 and every operating day, mapped to the 5-minute grid like `rt_lmp` **[data]**.

## 11. v5 "The Market Floor" data (lane DATA2, `scripts/desk_data_v5.py`)

`market` {date: days row} per operating day, in the previews' `data/market/days` shape (`gridsim_core.market_stack`):
the day's NP3-966-ER 60-Day DAM Disclosure (archive document posted D+60, fetched through `desk_data_api`) parsed by
`market_stack.build_day` with **every curve of the site's own resource removed** before aggregation (`carved` records
the resource and the number of removed supply/demand hour-curves). The public series in the row (NP4-523-CD λ,
HB_HUBAVG DAM and RT, EIA-930 actuals and day-ahead forecast) are the packaged store's. `background` holds every other
resource's offers and bids (≤ 64 points per hour and side), `pool` the anonymised candidate seats, and
`replay.lambda_usd` the copper-plate re-clear of what ships. Core lifts the book by `hub_dam_usd − replay.lambda_usd`,
so the re-clear without the battery posts the real price exactly; the replay check below measures what happens when
the operator's real curve goes back in.

The v5 packs use the v3 battery-days (same sites, days and PV assignment), so v5 − v3 isolates the price impact.
`scripts/desk_data_v5.py PACK` writes `data/desk/PACK/replay_check.json`. Packs: `desk-v5-pilot` (2) and
`desk-v5-eval` (24), `operator_ok` 26/26.

**Replay check** (desk-v5-eval, 24 battery-days, absolute $/MWh at the node):

| Check | n hours | mean | p90 | p99 | max |
|---|---|---|---|---|---|
| re-clear without the battery vs the real DAM SPP | 576 | 0.000 | 0.000 | 0.000 | 0.000 |
| re-clear with the operator's real EB/OC put back vs the real DAM SPP | 293 | 0.008 | 0.000 | 0.226 | 0.466 |
| the operator's re-cleared award vs its real award (MW) | 293 | 0.054 | 0.000 | 0.971 | 5.637 |
| copper-plate replay λ (no offset) vs NP4-523-CD λ | 576 | 12.92 | 27.12 | 132.3 | 150.9 |

The first row is exact by construction (core lifts the book by the hub offset). The second is the operator's own price
impact: a 100–150 MW battery moves the ERCOT DAM price by cents, rarely by more than $0.25. The last row is the part of
the price the copper-plate auction does not model (congestion, losses, AS co-optimisation); 04-24's scarcity hours
dominate its tail. The offset absorbs it.

## 12. v4 "Weather Front" packs (`desk-v4-pilot`, `desk-v4-eval`)

**Windows.** Three consecutive operating days, D0..D2 (`n_days: 3`; task `dates` holds all three). Fronts were
picked from the v4 forecast store's HRRR 2-m temperatures: the daily mean of DFW, IAH, AUS, SAT and MAF analyses, and
the largest day-on-day swings between 2025-12-20 and 2026-08-25. Each window keeps D-7..D2 clear of DST.

| Window | Front | Why |
|---|---|---|
| 2026-02-03..05 (pilot, S01) | 02-02 +13°F then 02-04 −8.7°F | after the AS erratum window; negative West prices (197 negative 5-min intervals at CROSSETT) |
| 2026-01-23..25 | Winter Storm Fern arctic front, 01-24 −23.8°F | 202(c) orders, Transmission Emergency 01-25; inside the AS-offer erratum window (operator AS replay unreliable) |
| 2026-03-16..18 | spring cold front, 03-16 −24.4°F, rebound +10.6°F on 03-18 | hub RT max $221 on the front day |
| 2026-04-17..19 | April front, 04-18 −14°F | hub RT min −$12.8 behind the front |
| 2026-05-08..10 | warm front 05-09 +8.7°F, then 34 severe-thunderstorm watch/warning entries across the six regions on 05-10 | 7 operational notices on 05-09 |

`desk-v4-eval` runs all four eval fronts at S01–S04: 16 windows, 48 battery-days.

**Per-window data**
- `dam_spp`, `dam_mcpc`: D-7..D2.
- RT and system series: D-1..D2.
- Per operating day: `posted.dam` (real posting minute), `posted.asdc` and `asdc`.
- Operator: DAM/SCED/COP for each operating day. `soc0` is the last disclosed SoC on D-1.

**ERCOT forecasts**
- Every hourly posting from D-1 00:00 to D2 23:59, pulled straight from the API (the store keeps only 72 h): NP3-565-CD
  in-use model system total, NP4-732-CD system STWPF, NP4-737-CD system STPPF.
- Values run from the posting's hour to D2 24:00. That is 96 postings per kind.

**Desk forecast** (`desk_data_forecast.py --v4 PACK...`)
- **DAM:** one vintage per operating day, issued at that day's D-1 06:00. Same DAM model as v2.
- **RT:** hourly vintages from D-1 06:00 to D2 23:00, each to D2 24:00 (90 vintages). They come from an RT model
  trained on 3-day spans (issue times every 6 h, horizons up to 90 h).
- **Refits and bands:** monthly refits; bands widened by the previous month's out-of-sample errors on the same span.
- **Pinball by month** ($/MWh, all nodes, every window starting in the month):

| Month | DAM | RT (3-day horizons) | coverage DAM / RT |
|---|---|---|---|
| 2026-01 | 14.96 | 9.78 | 0.76 / 0.76 |
| 2026-02 | 2.94 | 3.49 | 0.69 / 0.83 |
| 2026-03 | 3.19 | 6.19 | 0.79 / 0.78 |
| 2026-04 | 4.02 | 6.81 | 0.71 / 0.81 |
| 2026-05 | 2.87 | 3.90 | 0.77 / 0.87 |

The RT model's ERCOT-forecast features come from the store (72 h). Beyond 72 h ahead they are missing (LightGBM
handles the gap; ridge and MLP impute it), so the second and third days lean on price history.

**References** (desk-2.1, anchor risk 1.5 / spread, core ≥ acff0cd)
- **How they were built:** `desk_run.py --refs-only --manifest`, merged into `tasks.jsonl.gz` with
  `desk_data_v3.py PACK refs.jsonl`.
- **Floored windows:** pilot 0 of 1; eval 4 of 16, the four 2026-03-16 windows, where the anchor loses or barely gains.
- **Window swap:** 2026-04-17 S04 was replaced by 2026-04-03..05 S04, because WFTANK was on a forced outage from 04-10
  to 04-20 (NP1-346-ER). The 04-17 front is kept at S01–S03.
## 13. v4 benchmark pack (`desk-v4-bench`)

**What it is.** 32 three-day windows: the 16 windows of `desk-v4-eval` (four fronts, January to May), copied unchanged,
plus 16 windows on four new fronts in July and August 2026. Each task's `tags.split` marks its half: `pre_cutoff`
(the January–May windows) or `post_cutoff` (from 2026-07-01). The post-cutoff half falls after the training cutoffs
reported for the models run on the desk, so it is the contamination-clean split. The manifest's `cutoff` records the
dates we were given: Gemini 4 Argon about 2026-03, GPT-6.1 Sol about 2026-04-30, GPT-6 Luna about 2026-05-18, Claude
Opus 5.5 about 2026-06. These come from third-party reports and are unconfirmed.

**Reused windows.** `desk_data_build.py` copies a task named by the spec's `reuse` pack instead of rebuilding it. The
series files are byte-identical to `desk-v4-eval`. The task records are identical except for the added
`tags.split`; they keep `pack: desk-v4-eval`, because no code reads that field.

**New fronts.** Found the same way as §12: HRRR 2-m daily means (DFW, IAH, AUS, SAT, MAF) from the v4 forecast store,
NWS VTEC warnings in `data/notices/nws_vtec.jsonl.gz`, ERCOT notices and hub RT prices.

| Window | Front | Evidence |
|---|---|---|
| 2026-07-04..06 | severe-storm line | Independence Day storm complex: 24 severe-thunderstorm warnings 07-04..06 (18 on 07-05); daily mean −0.8°F, then −1.2°F |
| 2026-07-23..25 | tropical system | Tropical Storm Warning on the upper Texas coast 07-23, after the July heat peak (90.6°F and Extreme Heat Warnings 07-22); then −1.9°F and −3.1°F |
| 2026-08-18..20 | heat wave | Extreme Heat Warning for North Texas in force 08-17..22; daily mean 88.9–89.4°F; hub RT max $154 on 08-18 |
| 2026-08-26..28 | heat-wave break, storm line | 08-26 scarcity (hub RT max $795, mean $120, 17 ERCOT notices), then 15 severe-thunderstorm warnings 08-27..28 and −2.2°F on 08-28 |

**Constraints.**
- Every new day is post-RTC+B and at least 60 days old: the last day is 2026-08-28.
- No DST change from D-7 through D2.
- No date overlaps v2-eval, v2-tune, the v2 and v3 pilots, v3/v5-eval or v4-pilot/eval.
- `operator_ok` holds for all 16 new windows.
- No NP1-346-ER outage or derate touches any new window, so no swaps were needed.
- The 08-26 windows carry 286 ERCOT forecast vintages instead of 288: the API has no wind or solar posting for
  08-27 17:00.

**Other candidates checked** (all four sites `operator_ok`, not used):
- 07-11..13: mid-July cool-down.
- 07-15..17: five tornado warnings in South Texas, then the heat rebuilds.
- 07-18..20: onset of the late-July heat wave (Houston hub to $223).
- 08-24..26: the start of the August break.

**Caveat for 08-26..28.** These days fall after the measured storage-fleet regulation data ends (2026-08-25), so
their `reg_deploy` is the fitted fallback, labelled `modelled`.

**Desk forecast.** The 2026-07 and 2026-08 refits are new in `report.json` `v4`. Re-running the existing months
reproduces them exactly.

| Month | DAM | RT (3-day horizons) | coverage DAM / RT |
|---|---|---|---|
| 2026-07 | 2.54 | 2.82 | 0.81 / 0.80 |
| 2026-08 | 2.14 | 4.71 | 0.78 / 0.72 |

**References.** Built with `desk_run.py --refs-only` on the core at tag `desk-v4-freeze` (be6ff8c, desk-2.1, anchor
risk 1.5 / spread). The 16 reused windows reproduce their `desk-v4-eval` refs byte for byte. Every hind-bound assert
passes and `c_undefined` is 0 of 32. 8 of 32 windows are floored:
- the four 2026-03-16 windows (as in `desk-v4-eval`);
- 07-23 S03;
- 08-26 S02, S03 and S04.

On 08-26 S04 the anchor loses money (−$33.1k against idle +$25.4k). Most of the loss is the RT AS imbalance on
08-26 (−$75.6k): the anchor's DAM AS awards are bought back at scarcity RT prices. Hindsight there is $464k.

## 14. v4 training days (`desk-v4-train`)

**What it is.** 288 single-day tasks under the v4 layer (`n_days: 1`, `desk-v4-<date>-<site>`), every operating day
D0, D1 and D2 of 24 three-day windows at all four sites (96 site-windows), for fine-tuning on one operating day per
episode. A day task is what `build_task` makes of one day: history D-7..D-1, RT and system series D-1..D, the desk's
single-day forecast vintages and the store's ERCOT vintages (72 h covers a day), soc0 from the disclosed D-1 SoC.
`tags.window` and `tags.window_day` name each day's window and its place in it.

**Windows.** Only 2025-12-20..2026-01-22 and 2026-05-11..2026-07-03, so the benchmark's January–May half and its
July–August post-cutoff half keep their regimes to themselves. Each window keeps D-7..D2 clear of DST, has every RT
and DAM interval in the price history (which rules out the windows holding 2026-01-08 and 2026-06-04), and every
day more than 3 days from every day of `desk-v4-bench`, `desk-v4-eval` and `desk-v4-pilot`. Within those rules the
windows are disjoint and as many as each period holds (9 and 15), placed on the strongest weather and notice fronts
where the count allows: 12-20, 12-23, 12-26, 12-29, 01-01, 01-04, 01-09, 01-13, 01-17; 05-14, 05-17, 05-20, 05-23,
05-26, 05-29, 06-01, 06-06, 06-09, 06-12, 06-15, 06-18, 06-22, 06-25, 06-28. Seven days are also days of older packs
of other layers (`desk-v2-tune` 01-14, 05-20, 05-27, 06-17; `desk-v2-eval` 06-24; `desk-v3-eval` and `desk-v5-eval`
05-26, 06-06).

**Splits.** `val` is every day of the windows 01-13, 06-06 and 06-09 at all four sites (36 days; one of the nine
December–January windows and two of the fifteen May–June ones, drawn with numpy `default_rng(0)`); the other 252
days are `train`.

**operator_ok.** 251 of 288. It fails on 12-20..12-28 at every site, where the 60-day SCED Resource AS Offers return
no rows for the four resources (they resume on 12-29), and on 06-03 at S02. Only the operator
replay reference reads that disclosure; the training bundle (`scripts/desk_train.py`) leaves these 37 days out unless
asked for them.

**Desk forecast.** Single-day vintages from `desk_data_forecast.py --packs desk-v4-train` with the months 2025-11,
2025-12, 2026-01, 2026-04, 2026-05 and 2026-06. Every month whose previous month is refit too reproduces
`report.json` exactly (2025-12, 2026-01, 2026-05, 2026-06, the months of the training days), so `report.json` is
unchanged.

**References.** `desk_run.py --refs-only` on the core at `desk-v4-freeze` (desk-2.1, anchor risk 1.5 / spread).
`c_undefined` is 0 of 288; 114 days are floored and on 74 the anchor ends below idle, as a one-day information-matched
anchor often does. On the 251 operator_ok days the anchor's C (hindsight capture) averages 0.076 on train (median
0.071, above idle on 73% of days) and 0.051 on val; idle's is 0.
