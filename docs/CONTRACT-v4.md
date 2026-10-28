# GridSimEnv v4 "Weather Front" build contract (preview)

The v4 interface every lane builds against: `gridsim_core.forecast` (core, lane C4), the `gridsim-forecast` gateway env
(the env lane; a sibling of `gridsim-hybrid`), the forecast store (the data lane), the "Weather Front" replay (the
viewer lane) and the GPT-6.1 Sol pilot. Design source: the v4 plan on Linear (its critique fixes win), the archive-depth
check and the umbrella's shared rules. `docs/CONTRACT.md`, `docs/CONTRACT-v2.md` and `docs/CONTRACT-v3.md` hold for
everything not restated here. Nothing in v1-v3 changes: v4 is new modules (`gridsim_core.forecast`,
`gridsim_core.forecast_prompt`, `gridsim_core.forecast_inputs`, `scripts/*forecast*`, `data/ercot-front-v4-*`,
`data/fixtures-forecast/`, `data/forecast/`) plus backward-compatible refactors of v3 (below) that keep every recorded
v2 and v3 transcript byte-identical.

`gridsim_core.forecast.Session` holds the only v4 state machine. The env server imports it and only wraps it (clock
PUTs, MCP plumbing); path B' imports the same class. Tool outputs are exact strings made by core, so path A and path B'
are byte-identical by construction.

## What is real, what is modelled, what waits for the ERCOT API key

The plan serves ERCOT's own forecast vintages (NP3-565 load, NP4-732/742 wind, NP4-745 solar). The preview cannot: the
ERCOT public API needs a subscription key we do not have, MIS keeps these reports for about 7 days (cached NP4-745 list:
2026-10-17..24 only), and ercot.com's robots.txt disallows `/misapp` and `/misdownload`. The preview substitutes public
archives that are themselves as issued, and models the rest from them only:

| Plan | Preview | Kind |
|---|---|---|
| HRRR point weather as issued | NOAA HRRR `s3://noaa-hrrr-bdp-pds` 00/06/12/18Z runs, 0-48 h (0-36 h before 2020-12-02 12Z), GRIB2 `.idx` byte ranges; issued_at = cycle + 120 min (V4-P3) | real |
| NWS watches and warnings | IEM VTEC archive (v2's `data/notices/nws_vtec.jsonl.gz`, 2019-01-01..2026-10-16) | real |
| ERCOT notices | v2's scraped archive (`data/notices/notices.jsonl.gz`, minute-stamped rows only) | real |
| DAM and RT SPPs | cached NP4-180-ER hub/LZ DAM (2014-01-01..2026-10-17) and NP6-785-ER RT, 15-minute mean per hour (2019-01-01..2026-10-17) | real |
| DA AS MCPC | lane D3's `data/hybrid/as_dam_mcpc.jsonl.gz` (2021-01-01..2026-10-24) | real |
| ERCOT's day-ahead load forecast | ERCOT's own forecast as reported to EIA-930 (`DF`), one vintage per operating day, revealed 06:00 CPT on that day (V4-P2) | real, late |
| NP3-565 load vintages by zone | desk load forecast (system and the 8 weather zones) per HRRR run, fitted rolling-origin on EIA-930 demand | modelled |
| NP4-732/742 STWPF wind | desk wind forecast per HRRR run from 80 m wind at four wind points, fitted on EIA-930 ERCO wind | modelled |
| NP4-745 STPPF/PVGRPP solar | desk solar forecast per HRRR run from DSWRF and cloud at three solar points, fitted on lane D3's system solar cf | modelled |
| Site PV actuals | v3's proxy: lane D3's system hourly cf x site MWac x ILR (V3-D3) | modelled |
| Desk price guide | rolling-origin quantile model (P10/P50/P90) on the as-issued inputs above (V4-P4) | modelled |
| Henry Hub | not used (V4-P4) | - |
| RT MCPC (rtcb) | not modelled: DA AS only, as v3's T2 (V3-D10) | waits |
| Resource-node SPPs | hubs and load zones only | waits (v1.1) |
| ERCOT forecast vintages, API era | NP3-565 load by model and zone, NP4-732/742 STWPF/WGRPP, NP4-745 STPPF/PVGRPP from the ERCOT public API (2023-12-11 on), served in windows from 2023-12-12 (V4-P17) | real |
| ERCOT forecast vintages before 2023-12-11, `ercot-front-v4-fresh` | the portal archive (the depth check) and the forward-capture cron | waits |

Every modelled series is a deterministic function of inputs revealed at or before its issued_at (the reveal table
below, enforced by the store builder's leakage tests and replayed by the audit), so the plan's information discipline
holds even where the forecast is the desk's and not ERCOT's. The card says "desk forecasts (modelled from NOAA
HRRR as issued)" wherever the plan says NP3-565 or STPPF.

Measured tonight (phase-1 probes, `$SP/gridsim/c4/out`):

- HRRR availability: 104 real-time 00/06/12/18Z runs sampled quarterly 2021-03..2026-10 were complete on S3 (f00..f48
  `.idx`) at p50 111 min, p90 116 min, max 118.5 min after the cycle. The 2021-02-14 runs (Uri week) carry LastModified
  3.0-3.6 days late (a backfill), so LastModified cannot time old runs; the rule is cycle + 120 min for every run.
- Point extraction: 5 fields x 49 forecast hours = 300 GETs and 257-298 MB per run; 15-19 s per run from the laptop
  (16-24 threads, ~17 MB/s); eccodes decodes one CONUS field in 10-15 ms (~3 CPU-s per run). The Utah Zarr archive
  (`s3://hrrrzarr`, us-west-1) lacks DSWRF before 2025, so GRIB2 is the one source.
- EIA-930: the six-month `EIA930_BALANCE_*` and `EIA930_SUBREGION_*` CSVs download (robots allow
  `/electricity/gridmonitor/`); ERCO's subregions are the 8 weather zones (COAS EAST FWES NCEN NRTH SCEN SOUT WEST);
  `Demand Forecast (MW)` is 97.8% non-null in 2018-H2 and 100% in 2024-H1 and 2026-H1; 2026 files split wind and solar
  into with/without integrated storage columns (sum them). The form instructions put `DF` ("yesterday's hourly
  day-ahead demand forecast for today") in the daily file due by 07:00 Eastern on the operating day.
- Showcase coverage: DAM, RT, MCPC, solar cf, ERCOT notices (ops coverage 1.0), VTEC and complete HRRR runs cover Uri
  (2021-02-12..16), Heather (2024-01-13..17) and Fern (2026-01-22..27); EIA-930 was checked for Heather and Fern (24
  hours a day), Uri's 2021-H1 file is the data lane's first check. EIA DF against actual peak: Fern 85,215 vs 75,599
  MW on 2026-01-26 (+12.7%); Heather 87,055 vs 78,155 MW on 2024-01-16 (+11.4%; so Heather is also a load-forecast
  bust in this data, not "forecast right"); HB_NORTH DAM max $1,899 vs RT $525 on 2026-01-26.

## Shared with v2 and v3 (reused, not forked)

- From `gridsim_core.live`: `WatchDay` (dispatch, exact output string, `messages`, transcript, notice delivery and its
  log, the watch/reveal/once/get_time/RT/replay audit rows), `Notice`, `Watch`, `triggers`, `label`, `utc`,
  `to_minutes`, `freeze_line`, `PLANNING_CALLS = 3`, `TURNS_PER_WATCH = 5`, `BARRIER_SECONDS = 60`, `CLOCK_URI`.
  `live.parse_notice` gains a `reveal_minutes` argument (default 15, v4 passes 60).
- From `gridsim_core.hybrid`: `Site`/`site_of`, `make_site`/`site_from_archetype`, `pv_at_bus`, `step` (governor, AS
  shortfall, deployments, PV curtailment), `limits`, `govern`, `x_da_of`, `r_up`/`r_dn`, `deploy_hours`,
  `parse_plan`/`PlanError`, the MILP pieces (`_Model`, `_Lin`, `_plant`, `_awards`, `_value`, `_clean`), `events_of`,
  `CASH_KEYS`, `PRODUCTS`/`UP`/`EVENT_PRODUCTS`. Two refactors, each covered by the v3 replay tests: the hour rules
  (`Session.rules`) become a module function `hybrid.hour_rules(site, dur, S, cyc, e, a, ...)` that `Session.rules`
  calls, and `deploy_hours`, `parse_plan` and `solve_day` take an hour count (default 24) instead of the module
  constant.
- v3's rules hold per hour: C3-D1 (continuous MW), C3-D2 (per-hour evaluation, energy-alone fallback), C3-D4 (PV
  curtailment controller), C3-D5 (SoC rules on the base path), C3-D6 (governor), C3-D7 (charged vs excused), C3-D8 (AS
  shortfall, FTP), C3-D9 and C3-D14 (deployments at frac 1.0), C3-D15 (AC coupling in packs), C3-D17 (inherited awards).
- `contract.as_duration_h` (era A/B/C) and the era table; `P_FLOOR = 50`.

## Decisions for Edgar (all provisional; the build follows the recommendation until Edgar says otherwise)

| # | Decision | Recommendation (taken) |
|---|---|---|
| V4-P1 | Forecast sources | Serve HRRR, VTEC, ERCOT notices and ERCOT's DF via EIA-930 as issued; serve desk load/wind/solar forecasts and the price guide modelled only from them; label them "desk" on the card. ERCOT's NP3-565/NP4-73x vintages wait for the API key and the cron; the depth check stays the plan's test for them |
| V4-P2 | EIA DF reveal | 06:00 CPT on the operating day (the EIA-930 daily-file deadline, 07:00 Eastern). The official forecast therefore arrives after that day's DAM: DAM bids rest on the desk forecasts, and the DF is the in-day bust signal (Fern +12.7%, Heather +11.4%) |
| V4-P3 | HRRR issued_at | cycle + 120 min for every run (measured completion max 118.5 min); the store keeps S3 LastModified and a `backfilled` flag for the audit only |
| V4-P4 | Price guide | One rolling-origin model per calendar year Y fitted on vintages and targets before Y-01-01 (sklearn `HistGradientBoostingRegressor`, quantile loss, P10/P50/P90, `random_state=0`); targets DA SPP and hourly RT SPP at each point and DA MCPC per product; no Henry Hub (EIA republishes it from a third party): the lagged DAM level carries the fuel signal. Pinball loss and 80% coverage per year and horizon bucket on the card |
| V4-P5 | DA position | A DAM bid is v3's plan for the day (battery moves + AS blocks) plus `pv_da_share` in [0, 1]: x_DA = move + share x the gate's desk P50 site PV (curtailed at a negative guide DA P50, kept inside the meter and up-award headroom). No naked DA/RT positions: a P50-only anchor with free x_DA would arbitrage the full meter |
| V4-P6 | AS | DA only, fixed at the gate for the day; no RT AS re-optimisation (no RT MCPC history, V3-D10); rtcb windows settle DA-only, flagged `rt_as: not_modelled` |
| V4-P7 | Extraction span | HRRR and EIA-930 from 2019-07-01, so the 2021 guide has 18 months of history (2019-07..2020-12-01 runs reach 36 h; their 37-48 h features are missing, flagged). Windows from 2021-03 |
| V4-P8 | Task ids and tiers | `front-v4-{d1}-{point}-{site_id}`; the tier is the load config (v1-v3 house rule), not the id as the plan wrote; one row serves all four tiers |
| V4-P9 | DST and eras | Drop windows where any of d1-1..d3 is a DST transition day or where the era (contract.era, AS era) changes inside d1-1..d3 |
| V4-P10 | Watch caps and turns | front, blind, freeze-6h: at most 24 watches, 122 turns (5 x 24 + 2) for every task; front-lite: at most 14 watches, 72 turns |
| V4-P11 | HRRR event watch (the plan's V4-D9) | A run adds a watch at its issued_at when the guide's RT P50 at the site's point over the run's open hours moves by >= 10% of the previous vintage (mean absolute change / max(mean absolute previous, $10/MWh)); it ranks below every notice under the cap |
| V4-P12 | Where vintages live | One shared store built by the data lane (`cache/forecast/store/`, published as the dataset's `v4_vintages`); eval, rtcb, showcase and fixture rows embed their window slice (self-contained in git and the image); train rows reference the store |
| V4-P13 | Preview pack sizes | train ~1,500 front-lite windows (2021-03..2024-12, front-lite refs only), eval 60 (40 front / 20 calm, 2025-01..2025-11), rtcb 20 (2025-12-05..2026-09-27), showcase 4, fixtures 12 |
| V4-P14 | Forecast-call budget | `get_forecast` and `get_forecast_drift` share 6 calls per watch (free of the planning calls); `submit_dam` 3 per gate |
| V4-P15 | Weather points | 18 fixed points (`data/forecast/points.json`): the 8 v1 site airports (ASOS-checkable), 3 more zone points (SPS, ABI, HRL), 4 wind and 3 solar points; zones by nearest representative city, labelled approximate |
| V4-P16 | Henry Hub, NBM, fleet/desk tiers, overworld map | Not built (the plan's V4-D4/D5/D6) |
| V4-P17 | ERCOT's own vintages | Windows from d1 = 2023-12-12 serve ERCOT's load, wind and solar vintages (`source: ercot`); earlier windows and the whole train pack serve the desk's (`source: desk`). The price guide stays on desk features in every era, so P_roll's prices are one model family; P_roll's site PV follows the served solar. Details below |
| V4-P18 | Pack filters | The plan's per-kW headrooms are miscalibrated on the real store: over 4,327 candidates the median P_hind - P_idle is $0.40/kW per window (train, `front-lite`, 48 h) and $0.81/kW (eval, `front`, 72 h), p90 $1.81 and $1.71, in line with ERCOT battery revenue of about $29-56/kW-yr; $3/kW kept 6.7%, 3.7% and 0% of train, eval and rtcb, $1/kW of P_roll headroom 5.6%, 9.8% and 2.1%. Instead: drop the lowest 15% of each split's candidates by hindsight headroom per kW (v1's low-spread rule); require P_roll - P_idle >= max($0.10/kW, 5% of P_hind - P_idle) so the reward's denominator is well defined; keep P_hind - P_roll >= 8% (forecasts cost something) and P_roll - P_blind >= 5% (forecasts are worth reading) |
| V4-P19 | Front label | A front is a synoptic change, not the diurnal cycle: the plan's "drops >= 15 F within 12 h" marked all 4,327 candidates `front` (the West Texas points swing 25-30 F a day). `front` when, at any weather-zone point inside the window, the stitched HRRR near-analysis 2 m temperature is >= 15 F below the same hour 24 h earlier, or an NWS winter storm, hard freeze, excessive heat or high wind product (WS, HZ, EH, XH, HW; W or A) is in force; else `calm` |
| V4-P20 | Reference reproducibility | HiGHS breaks MILP ties by platform (8 of 48 macOS-built fixture refs did not reproduce on Linux arm64/amd64). Each tier's refs store the anchor's own decisions, `anchor_calls` = [{watch, tool, args}] (its commits and DAM submits); `anchor_policy` replays them through the Session whenever the row's refs hold (same events, vintages and source), so P_anchor reproduces to the cent on every platform (the Session is plain float arithmetic). New builds also re-solve with `solver: 2`: a tie-break of $1e-4/MW x (1 + t/1000) on battery moves and (x (1 + i/100) per product) on free awards, so re-solves agree wherever the optimum is unique. Rows without `anchor_calls` (the current eval, rtcb and showcase packs) keep solver 1 and re-solve as before: their stored P_anchor and reward scale are unchanged |
| V4-P21 | Train draw (Edgar) | Up to 3 settlement points per d1 per label (front/calm) in `train` (`eval` and `rtcb` keep one), with the builder's targets of 60% front and 40% calm of ~1,500: 1,883 windows pass V4-P18/P19 (1,361 front, 522 calm) and the draw takes 1,290, 900 front and 390 calm (70/30). Calm binds: only 390 calm windows fit at 3 a day (212 calm days). A strict 60/40 would be 975 (585/390); every window that fits at 3 a day, 1,331 (941/390) |
| V4-P22 | Packs rebuilt with stored anchor calls (Edgar) | Every pack (`train`, `eval`, `rtcb`, `showcase`, fixtures) is rebuilt on store cb47cd9f with solver 2 and each tier's `anchor_calls` (V4-P20), so its references replay on any platform: the anchor's stored calls reproduce P_anchor to the cent with R = 1.0 and a clean audit on macOS arm64, Linux arm64 and Linux amd64 (Docker): `eval`, `rtcb`, `showcase` and fixtures at all four tiers, 384 of 384 on each; `train`'s 1,290 `front-lite` rows on macOS and Linux arm64 (pyarrow crashes under amd64 emulation, so the store-backed rows are not checked there); `test_anchor_reproduces_stored_reference` (fixtures and showcase) passes on linux/amd64. On the windows both builds share, solver 2 moved P_anchor by a median of 0 (−2.1% to +1.2% of P_hind − P_idle); 57 of the 60 `eval` windows are the 4.0 pack's |
| V4-P23 | Forecast-tool friction (Edgar; the rules-4.0 pilot's misuse) | (a) A blank or null `issued_at` in `get_forecast` is the latest vintage at or before now, as one left out. (b) Every time the env shows is ISO 8601 CPT with its UTC offset (`2025-01-28T10:00-06:00`; watches, notices, alerts, forecasts, refusals, headlines, Episode JSON); a time the agent passes with an offset or `Z` is converted to CPT, one without is read as CPT, and a time after now is still refused. (c) `front-lite`'s card, its `submit_dam` description and schema are energy-only: no reserves, AS, MCPC or `pv_da_share`. A refused forecast call still uses one of the watch's 6 (V4-P14 unchanged) |
| V4-P24 | Keep fields (Edgar) | As v3: an AS field of a `submit_dam` plan (or of a `check_schedule`/`commit_schedule` plan) sent as `"keep"` or null is unchanged, as one left out; the parse error, the card and the schema say to leave the field out or send `"keep"`. Energy is always sent |
| V4-P25 | Rules version | `FORECAST_VERSION = "4.1"` for V4-P21..P24. The GPT-6.1 Sol pilot at v4-preview befeefe (`results/runs/v4-pilot-sol*`, `results/board-v4.md`, `results/pilot-v4.json`) is the rules-4.0 pilot and stays on record: its episodes replay only at befeefe (4.0 time labels, `issued_at: ""` refused, the 4.0 packs) and are not re-graded; a new pilot on 4.1 supersedes it |
| V4-P26 | Scoring (Edgar, adopted 2026-10-25) | The cross-version scale ([CONTRACT.md](CONTRACT.md#scoring-across-versions-adopted)): C against P_hind heads the board and replaces `r_hind` there (`r_hind` = 0.2 + 0.8 C stays a weight-0 row), beside the anchor's C and Δ, which is `paired_vs_anchor`; R second; P_roll3, P_blind and naive compared as (P − P_ref)/(P_hind − P_idle). `grade()` adds `capture_vs_hindsight` (C) and `stretch_reward` (S), the path-B' training reward |

## ERCOT vintages in the API era (V4-P17)

The ERCOT public API (subscription key and ID-token login in SSM, read only inside the fetching process, never logged)
serves these reports from 2023-12-11, from US egress, at 30 requests a minute. The data lane fetches them on the box
into the same store, beside the desk, HRRR and EIA kinds, with the same issued_at discipline:

| Kind | Report | Keys | Fields |
|---|---|---|---|
| `ercot_load` | NP3-565-CD Seven-Day Load Forecast by Model and Weather Zone | `system` (the 8 zones summed) and each zone | `mw` (the model with the in-use flag set), `model` |
| `ercot_wind` | NP4-732-CD (system), NP4-742-CD (regions) | `system`, each wind region | `stwpf_mw` (P50), `wgrpp_mw` (P80) |
| `ercot_solar` | NP4-745-CD | `system` (the regions summed), each solar region | `stppf_mw` (P50), `pvgrpp_mw` (P80) |

- issued_at = the posting time the API reports (`postedDatetime`, CPT, converted to UTC); reveal_at = issued_at. The
  store keeps every hourly posting, trimmed to 72 h from the posting hour; `run_id` = `"{report}@{posted UTC}"`. A
  posting's rows are taken as posted (no later revision replaces them); the index's `sha` binds them.
- A window's `source` is `ercot` when d1 >= 2023-12-12 (so every vintage it can serve, from 24 h before the open, lies
  in the API span) and the store has, for each of the three kinds, a posting within 2 h before every fixed watch;
  otherwise `desk`. The load config may override it (`{"task_id", "tier", "source"}`) for the desk ablation; refs are
  stored for the row's own source and computed on demand for the other.
- In an `ercot` window `get_forecast(load|wind|solar)` and `get_forecast_drift` serve the ercot kinds (`mw` = the
  P50 field; `wgrpp_mw`/`pvgrpp_mw` also returned as `p80_mw`), with `source` naming the report; zones map to
  NP3-565's weather zones. The site's PV P50 is `hybrid.pv_at_bus(site, stppf_system / installed_mw)` (lane D3's
  installed MW of the day). Weather, price, alerts and the EIA DF are served as in `desk` windows.
- `ercot_load` zone keys use the EIA subregion codes of `points.json` (COAS, EAST, FWES, NCEN, NRTH, SCEN, SOUT,
  WEST), as the desk's `load` kind does. Neither kind carries a `site` key in the store: the pack builder adds
  `solar`/`site` and `ercot_solar`/`site` vintages (field `mw`) to a window's slice from the system series and the
  site row (`hybrid.pv_at_bus`, with the day's installed MW).
- References: P_roll, P_roll3 and P_naive read the guide's prices (desk features in every era) and the served site PV;
  P_blind is unchanged. The agent's extra information (ERCOT's load and wind) is an edge the anchor does not use; it
  shows in `beats_anchor` and `paired_vs_anchor`, and the card states it.
- Packs: train stays `desk` throughout (one forecast family to train on); eval (2025), rtcb, `fern-0124`,
  `heather-0114` and `spring-0328` are `ercot`; `uri-0213` is `desk`. Eval rows carry both slices, so the `desk`
  ablation runs on the same windows. The task row gains `"source": "ercot|desk"` and the slice's `kinds` list.
- The audit's forecast replay covers the ercot kinds the same way (reveal_at <= the call's minute, `sha` from the
  index).

## Clock, window and watches

- Times are CPT. A window is d1..d(n) with n = 3 (`front`, `blind`, `freeze-6h`) or 2 (`front-lite`). Core counts
  **minutes from d1 00:00**: the clock opens at d1-1 10:00 (minute -840) and the window ends at 1440 n. Window hour h =
  0..24n-1 covers [60h, 60h + 60); day index k = h // 24; agent-facing times are ISO 8601 CPT with the UTC offset,
  `"2026-01-24T10:00-06:00"` (V4-P23; rules 4.0 showed `"YYYY-MM-DD HH:MM"`).
- The plant is handed over at d1 00:00 with SoC s0: nothing executes or settles before minute 0.
- **Freeze**: `freeze_line(m) = ceil_to_hour(m) + 60` (`freeze-6h`: + 360). Hour h is *settled* when it has ended,
  *frozen* when it starts before the freeze line, *open* otherwise. `frozen_until_hour` = the first open hour.
- **DAM gate** for day k (k = 0..n-1): the 10:00 watch of day k-1 (minute 1440k - 840). `submit_dam` is accepted only
  there; results (DA SPPs and DA MCPCs of day k) are revealed at 13:30 of day k-1 and delivered by the 14:00 watch.
- **Fixed watches**: 10:00, 14:00, 18:00 on d1-1; 00:00, 06:00, 10:00, 14:00, 18:00 on d1..d(n-1); 00:00, 06:00,
  18:00 on d(n). `front`: 16 watches (minutes -840, -600, -360, 0, 360, 600, 840, 1080, 1440, 1800, 2040, 2280, 2520,
  2880, 3240, 3960); `front-lite`: 11 (-840, -600, -360, 0, 360, 600, 840, 1080, 1440, 1800, 2520).
- **Event watches**: each notice (ERCOT, NWS, deployment) at reveal_at = ceil(issued_at, 60 min); each HRRR run that
  passes V4-P11 at its issued_at (not in `blind`, where a forecast-driven watch would leak the forecast). v2's L-D4
  merge applies on the hour: events at a fixed watch's hour are absorbed by it; an event whose freeze line is at or
  after the window end makes no watch; over the cap (V4-P10) the most urgent keep their watches (deployments, EEA and
  Emergency; conservation; ERCOT Watch and EEA exit; NWS warnings; NWS watches; HRRR moves; Advisories; OCN and other;
  cancellations last; then the earliest) and the rest are delivered at the next watch at or after their reveal.
  Notices revealed at or before the open are the watch-0 board.
- Triggers are `live.triggers(watches)`: after `advance` opens watch k, `grid_notice` once per notice of the watch.
  New forecast vintages and DAM results are not notices: they appear in `advance`'s output and through `get_forecast`.

## Reveal table (one table: the Session, the store builder's leakage tests and the audit all read it)

`forecast_inputs.REVEAL` maps each item to the moment it may first be shown or used as a feature:

| Item | reveal_at |
|---|---|
| HRRR run (cycle c) | c + 120 min |
| Desk load/wind/solar and guide vintages of a run | the run's reveal_at |
| EIA-930 `DF` for operating day D | D 06:00 CPT |
| EIA-930 demand, hour ending t | t + 60 min |
| EIA-930 net generation by fuel (wind, solar) for day D | D+1 06:00 CPT |
| EIA-930 subregion demand | t + 31 days (desk fitting only, never served) |
| DA SPP and DA MCPC of day D | D-1 13:30 CPT |
| RT SPP of hour h (mean of its four 15-minute SPPs) | end of hour h |
| Site PV actual of hour h | end of hour h |
| ERCOT notice, NWS VTEC product, AS deployment | ceil(issued_at, 60 min) |
| ERCOT NP3-565, NP4-732/742, NP4-745 posting | its posting time (V4-P17) |

## Plant, settlement and the terminal rule

- `front`, `blind`, `freeze-6h`: v3's hybrid site (`task["site"]`, v3 row shape) for 72 h. `front-lite`: the same
  row's battery alone (PV 0, no AS, meter = POI) for 48 h.
- Per hour, as v3: battery base move b (+ discharge), `step()` executes it with the governor, regulation drift
  (`reg.up/dn`, 24n values, seeded per task id), deployments, PV curtailment and the AS shortfall.
- **DA position** (V4-P5): per hour of day k with an accepted DAM entry (e_DA, a), x_DA = e_DA + pv_da, where pv_da =
  0 if the gate's guide DA P50 < 0, else min(share x pv_p50_gate, max(0, L - e_DA - Up)); `pv_p50_gate` is the desk
  site-PV P50 of the latest vintage at the gate (`front-lite`: pv_da = 0 and the share is ignored). An hour without an
  accepted entry (a missed gate, a refused hour) has x_DA = 0 and no AS.
- **Settlement** (price taker, two settlements): energy_da = x_DA x DA; energy_rt = (x - x_DA) x RT; as_da = sum_k
  a_k x MCPC_DA,k; degradation = c_deg x MWh discharged (base and deployed); ftp per C3-D8 (charged per C3-D7).
  RT is the hourly mean of the 15-minute SPPs (the plan's V4-D7, flagged).
- **Cycle cap**: 1.5 x E MWh of base discharge per day, pooled over the window (1.5 E n).
- **Terminal**: SoC at the window end must be >= s_end_min (= s0); the charged shortfall (C3-D7) is bought back at
  shortfall / eta x max(window max DA SPP, P_FLOOR).
- Profit P = energy_da + energy_rt + as_da - degradation - ftp - end_penalty, rounded as v3.

## Forecasts and the projection

- A **vintage** is `{"kind", "key", "issued_at" (UTC ISO Z), "run_id", "source", "start" (UTC ISO of its first valid
  hour), "fields": {name: [values]}, "sha"}`; `sha` = sha256 of the canonical JSON of `fields`. Kinds and keys:
  `weather` (a point id; fields `t2m_f`, `wind80_ms`, `dswrf_wm2`, `cloud_pct`; up to 48 h), `load` (`system` or a zone;
  `mw`), `wind` (`system`; `mw`), `solar` (`system`, `site`; `mw`), `price` (the settlement point; `da_p10`, `da_p50`,
  `da_p90`, `rt_p10`, `rt_p50`, `rt_p90`), `mcpc` (a product; `p10`, `p50`, `p90`), `load_official` (`system`; `mw`,
  24 values of its operating day). Desk and guide vintages run 72 h from the hour after issued_at. A weather value
  for hour [t, t + 1 h) is the mean of the run's instantaneous values at t and t + 1 h (unit conversions by the store
  builder: K to F, wind speed from u and v).
- **The served value of an hour** at minute m: the latest vintage of its kind and key with reveal_at <= m that covers
  the hour; a revealed DA price replaces `da_*` (all three quantiles equal it, `known: true`); beyond every vintage's
  range the same hour-of-day of its last covered day.
- **Projection** (check, commit, `projected`, the anchors): settled hours as settled; the rest on the served P50s:
  DA (revealed or P50), RT P50, MCPC P50 for days without results, site PV P50, expected drift (`reg.mean_up/dn`) and
  delivered deployments. The `blind` tier projects on persistence instead: DA, RT and MCPC = the last revealed DA day's
  same hour, PV = the last settled day's same hour. A projection never reads an unrevealed actual.

## gridsim_core.forecast API

```python
from gridsim_core.forecast import (Session, schedule, triggers, references, replay, play, slice_for, FORECAST_VERSION,
                                   FORECAST_ENV, EPISODE_SCHEMA, TIERS, TOOLS, NOTICE_TOOL, FORECAST_LOAD_URI,
                                   END_WINDOW_URI, CLOCK_URI, PLANNING_CALLS, FORECAST_CALLS, DAM_SUBMITS, MAX_WATCHES,
                                   MAX_TURNS)
s = Session(task, tier="front", notices=None, deployments=None, vintages=None)  # vintages None -> task["vintages"]
s.call(tool, args) -> str           # the exact output string; agent tools carry "messages"; transcript recorded
s.situation() / s.get_forecast(...) / s.get_forecast_drift(...) / s.check_schedule(plan, from_hour)
s.commit_schedule(plan, from_hour) / s.submit_dam(operating_day, plan, pv_da_share=1.0) / s.advance()
s.notice(...) / s.deliver_watch_notices(via="trigger") / s.end_window() / s.grade() / s.audit(get_time_reads=None)
s.data() / s.episode(**meta) -> gridsim.episode/v4
s.watches, s.watch, s.done, s.transcript, s.forecast_log, s.watch_time_utc(k)
schedule(task, tier, notices, deployments, vintages) -> list[live.Watch]; triggers(watches) -> v2-shaped trigger list
replay(task, tier, notices, deployments, vintages, transcript) -> {"ok", "problems"}
references(task, tiers=TIERS) -> refs dict        # never shown to the agent
slice_for(task, store=None) -> the window's vintages (inline rows return their own; train rows read the store)
```

`FORECAST_VERSION = "4.1"` (V4-P25), `FORECAST_ENV = "gridsim-forecast"`, `EPISODE_SCHEMA = "gridsim.episode/v4"`,
`TIERS = ("front-lite", "front", "blind", "freeze-6h")`, `TOOLS = ("get_situation", "get_forecast",
"get_forecast_drift", "check_schedule", "commit_schedule", "submit_dam", "advance")`, `NOTICE_TOOL = "grid_notice"`,
`FORECAST_LOAD_URI = "urn:gridsim:forecast-load/v1"`, `END_WINDOW_URI = "urn:gridsim:end-window/v1"`,
`FORECAST_CALLS = 6`, `DAM_SUBMITS = 3`, `MAX_WATCHES = {"front-lite": 14, other: 24}`, `MAX_TURNS = 5 x cap + 2`.

## Tools (agent role `default`; outputs are the dicts below plus `"messages"`)

Errors return `{"error": "...", "calls_left": n}` (or `forecast_calls_left`, `submits_left`) and change nothing; as v2
L-D7, a budgeted tool with a missing or unexpected argument uses its call; a call with none left, or after the window,
uses none. Hours are window hours (0..24n-1) or times: ISO 8601 or `"YYYY-MM-DD HH:MM"`, read as CPT without an
offset and converted to CPT with one (`Z`, `+-HH:MM`) (V4-P23); money is rounded to cents, MW and MWh
to 2 decimals, prices to cents, weather to 1 decimal.

- `get_situation()` (free; answers after the window too):

```
{"task_id","tier","era","settlement_point","zone","site_id","region",
 "window":{"days":["2026-01-24","2026-01-25","2026-01-26"],"open":"2026-01-23T10:00-06:00","end":"2026-01-27T00:00-06:00",
           "tz":"CST","hour_0":"2026-01-24 00:00"},
 "watch":k,"time":"2026-01-24T10:00-06:00","phase":"dam_gate|rt","frozen_until_hour":11,"calls_left":3,
 "forecast_calls_left":6,"window_over":false,
 "dam_gate":{"operating_day":"2026-01-25","submits_left":3,"submitted":bool}|null,
 "site":{v3's site fields,"cycle_cap_mwh" (pooled),"cycle_used_mwh"},
 "as_rules":{v3's as_rules,"set_by":"submit_dam"},                      # front, blind, freeze-6h only
 "days":[{"date","first_hour","dam":"submitted|missed|open|pending","da_usd":[24]|null,"mcpc_da":{k:[24]}|null,
          "x_da_mw":[24]|null,"awards":{k:[24]}|null,"pv_da_share":x|null}],
 "rt_usd_last_24h":[settled hours, at most 24],"pv_mw_last_24h":[...],"soc_mwh":x,
 "status":"SSS…FFOO…" (24n chars),"book":{"energy":[24n]},
 "projected":{"soc_end_mwh","reserve_margin_min_mwh","energy_da_usd","energy_rt_usd","as_usd","degradation_usd",
              "ftp_usd","end_penalty_usd","total_usd","basis":"P50 as of now|persistence"},
 "cash":{settled so far, as advance},
 "latest_vintages":{"weather":"2026-01-24 08:00","load":…,"wind":…,"solar":…,"price":…,"load_official":…|null}|null,
 "active_alerts":[{"event_id","name","title","until"}],               # at most 5, NWS products in force now
 "notices":[{"event_id","source","level","time","name","title","text"}],
 "result":{...}}                                                       # only after the window
```

- `get_forecast(kind, zone=None, hours=48, issued_at=None)` (a forecast call; refused in `blind`): `kind` in `load`,
  `wind`, `solar`, `weather`, `price`, `alerts`; `zone` a weather zone (`COAST`, `EAST`, `FAR_WEST`, `NORTH`,
  `NORTH_C`, `SOUTHERN`, `SOUTH_C`, `WEST`), `system`, `site` or a point id, defaulting to `system` (load, wind),
  `site` (solar, weather) and the settlement point (price); `hours` 1..72 from the next hour; `issued_at` picks the
  latest vintage issued at or before it and **any issued_at after now is refused** (`"issued_at is after now"`); a
  blank or null `issued_at` is the latest vintage at or before now, as one left out (V4-P23).

```
load:    {"kind","zone","issued_at","source":"desk load model on HRRR 12Z","from","mw":[n],"prev_vintage_delta_mw":[n],
          "official":{"issued_at","source":"ERCOT day-ahead forecast via EIA-930","from","mw":[m]}|null}
wind:    {"kind","zone":"system","issued_at","source","from","mw":[n],"prev_vintage_delta_mw":[n]}
solar:   {"kind","zone":"system|site","issued_at","source","from","mw":[n],"prev_vintage_delta_mw":[n]}
weather: {"kind","point","zone","issued_at","source":"NOAA HRRR 12Z run","from","t2m_f":[n],"wind80_ms":[n],
          "dswrf_wm2":[n],"cloud_pct":[n]}
price:   {"kind","point","issued_at","source":"desk price guide (modelled)","from",
          "da":{"p10":[n],"p50":[n],"p90":[n],"known":[n bools]},"rt":{"p10","p50","p90"},
          "mcpc_da":{product:{"p10","p50","p90"}}}                    # mcpc_da only where AS are offered
alerts:  {"kind","alerts":[{"event_id","source":"NWS","phenomena","significance","title","issued","from","until",
          "zones":[...]}]}                                            # issued <= now, not expired
```

  `n` is cut at the window end and at the vintage's last hour; every output also carries `"forecast_calls_left"`.
- `get_forecast_drift(kind, target_hour, zone=None)` (a forecast call; refused in `blind`): every vintage revealed by
  now that covers the target hour, oldest first: `{"kind","zone","target":"2026-01-26 08:00","vintages":[{"issued_at",
  "value"}]}` (`price`: `value = {"da_p50","rt_p50","da_p10","da_p90"}`; `load` includes the official DF when
  revealed, marked `"official": true`).
- `check_schedule(plan, from_hour)` (a planning call): `plan = {"energy": list | str | blocks}` over window hours (v3's
  format; AS fields are an error: AS are set by `submit_dam`). Evaluated per hour from `from_hour` (default
  `frozen_until_hour`) per C3-D2 on the projection; commits nothing.

```
{"feasible","issues":[{"hour","field","rule","detail"}],"refused":[hours],"projected":{...},
 "soc_mwh_path":[from from_hour to the end],"reserve_margin_mwh_by_hour":[...],"calls_left"}
```

- `commit_schedule(plan, from_hour)` (a planning call): the same evaluation; accepted hours replace the book.
  `{"committed":[hours],"refused":[{"hour","field","rule","detail"}],"frozen_until_hour","book":{"energy":[24n]},
  "projected":{...},"calls_left"}`.
- `submit_dam(operating_day, plan, pv_da_share=1.0)` (a DAM submit; only at the gate for that day): `plan` is v3's
  plan for the day's 24 hours (`energy` battery moves plus AS blocks for the offered and qualified products; an AS
  field sent as `"keep"` or null is unchanged, as one left out (V4-P24); `front-lite`: energy only, and its card, tool
  description and schema name no AS and no `pv_da_share` (V4-P23)). Evaluated per hour per C3-D2 and C3-D5 on the
  projection from the projected SoC at the day's start, with the AS duration table of the day's era. Accepted hours
  set the day's DAM entry and the book's entries for that day; refused hours keep the previous DAM entry (none: idle,
  no AS). Replaceable until `advance`.

```
{"accepted":[hours],"refused":[{"hour","field","rule","detail"}],"operating_day","x_da_mw":[24],"pv_da_mw":[24],
 "awards":{k:[24]},"projected":{...},"submits_left"}
```

- `advance()` (free): runs the book to the next watch, settles every hour that ends by then, opens the watch.

```
{"watch":k,"time","phase","frozen_until_hour",
 "realized":[{"h","time","rt_usd","pv_mw","x_da_mw","export_mw","curtailed_mw","b_mw","soc_mwh","reg_up_frac",
              "reg_dn_frac","deployed_up_mwh","deployed_dn_mwh","governor","ftp_mw","excused_mw"}],
 "dam_results":{"operating_day","da_usd":[24],"mcpc_da":{k:[24]},"x_da_mw":[24],"value_usd"}|null,
 "new_vintages":[{"kind","issued_at","source","headline"}],          # runs and DFs revealed since the last watch
 "soc_mwh","cash":{"energy_da","energy_rt","as_da","deployment_energy","degradation","ftp","excused","end_penalty",
                   "total"},"calls_left":3,"forecast_calls_left":6}
```

  From the last watch it runs to the window end: `{"done":true,"time","realized","soc_mwh","cash","profit_usd",
  "reward","capture_vs_hindsight"}` (no `watch` key, so no trigger matches). Headlines are generated by core, e.g.
  `"HRRR 12Z run; desk peak load 84,120 MW at 2026-01-26T08:00-06:00 (+3,210); site RT P50 +14%"`.
- `get_time()` comes from the gateway (UTC).
- Harness only (hidden from `default`): `grid_notice(event_id, name, text, level?, derate_mw?, from?, until?, deploy?)`
  as v3; `urn:gridsim:forecast-load/v1 {task_id, tier}` -> `{"task_id","tier","watches","days"}` (one load per env;
  unknown ids fail loudly); `urn:gridsim:end-window/v1` -> `s.end_window()` = `{"end_reason","watch","profit_usd",
  "reward","audit"}`; `urn:agentenv:clock/v1 sync_time`; `data/get` -> `s.data()`; `data/reset`.
- `data()`: `{"task_id","tier","watches","watch","time","done","end_reason","calls_used","planning_calls",
  "forecast_calls","dam":[per day],"book","executed","status","notices","forecast_log","frozen","refusals","governor",
  "excused","settled","audit","grade","reward"}`; never a reference before the window ends.

## References and reward (`references()`; stored in the row, never shown to the agent)

All are played through a `Session` with the tier's freeze, budgets and DAM rule, on HiGHS (`hybrid._Model`, with
presolve retried off when it calls a model with rounded fixed awards infeasible); one MILP per watch over the open hours
to the window end, frozen hours pinned, submitted DAM entries and AS fixed (C3-D17 inherited-award rule), soft fallback
and repair walk as v3's anchor, so its commits are never refused. At a gate the anchor commits its energy first and
then submits the gated day, so the DAM plan is checked from the SoC its own commit leads to.

- **P_idle**: no DAM, battery idle, PV exported at RT under the meter (`front-lite`: 0 unless the terminal rule bites).
- **P_roll** (the anchor of `front`, `front-lite`, `freeze-6h`): at each watch, solve on the projection's P50 inputs
  (V4 "Forecasts and the projection"); at a gate, `submit_dam` the solve's day plan (share 1.0) and then
  `commit_schedule` its open hours; elsewhere commit when the solve changes the book. Unsubmitted days' DA entries and
  AS are variables valued at DA P50 and MCPC P50; their RT deviation at RT P50.
- **P_roll3** (strong reference, reported): the same re-planner on the three-scenario sample average: one plan valued
  equally on the P10, P50 and P90 paths of DA, RT and MCPC (PV at P50), which for the linear objective is the solve on
  the scenarios' mean.
- **P_blind** (the anchor of `blind`; reported elsewhere): P_roll on the persistence projection.
- **P_naive** (card baseline): at each gate, charge P in the 4 cheapest and discharge P in the 4 dearest DA P50 hours
  of the day (governed, no AS), never re-planned.
- **P_hind** (weight 0) and its LP bound **P_lp**: v3's hindsight (C3-D13) over the window: a DA copy per day on DA
  prices and a physical copy on realized RT, PV, drift and deployments, sharing each day's AS book.
- **Reward**: no accepted hour in any `submit_dam` or `commit_schedule` -> 0; else R = clip(0.2 + 0.8 (P - P_idle) /
  (P_anchor - P_idle), 0, 1) (`grade.reward_value`). Weight-0 rows: `r_hind` (the same with P_hind),
  `paired_vs_anchor` = (P - P_anchor) / (P_hind - P_idle), `beats_anchor`, `r_roll3`, `forecast_value` (blind only:
  the run graded against P_roll), `dam_missed` (gates without an accepted hour), baselines {profit, reward},
  `capture_vs_hindsight` (C, the board's headline) and `stretch_reward` (S, training only; V4-P26).
- `grade()` -> `{"submitted","tier","reward","raw_ratio","profit_usd","cash","p_idle","p_anchor","p_roll","p_roll3",
  "p_blind","p_naive","p_hind","p_lp","r_hind","paired_vs_anchor","capture_vs_hindsight","stretch_reward","beats_anchor",
  "forecast_value","dam_missed",
  "ftp_mwh_charged","ftp_mwh_excused","governor_hours","refusals","commits","dam_submits","forecast_calls"}`.
- **Reference-solver test** (V4-P20): the anchor's stored calls, replayed through the Session (core) and through the
  env (`scripts/forecast_e2e.py --policy anchor`), reproduce R = 1.0 and the stored P_anchor to the cent; rows without
  stored calls fall back to re-solving, which reproduces only on the platform that built them. Every pack row stores
  its calls from rules 4.1 on (V4-P22).

## Audit (`s.audit()`; weight 0, a failure leaves the run unscored)

v3's rows (watch notices in order before the agent's next call, nothing before its reveal, each revealed exactly once
in a finished window, get_time reads, byte-identical replay, no RT price before its hour ended) plus:

- every `get_forecast`/`get_forecast_drift` output is re-derived from the vintages: each vintage it used had reveal_at
  <= the call's minute, its `sha` matches the vintage index, and a default request used the latest such vintage;
- no output showed a DA price or MCPC of day k before minute 1440k - 630, a PV actual before its hour ended, an EIA
  DF before 06:00 of its day, or EIA demand or fuel generation before its reveal (the reveal table);
- each DAM entry was accepted at its own gate, and x_DA matches the gate's vintage.

## Window selection and packs

- **Candidates**: d1 from 2021-03-02 to 2026-09-28 (so d1-1..d3 lie inside the price, MCPC, solar-cf and HRRR spans),
  at the 13 non-average points (v3's `POINTS`) with v3's archetype sites (lane D3, default + POI variant shares);
  V4-P9 drops DST and era-crossing windows; showcase windows +-3 days are out of every split.
- **Label** (V4-P19): `front` when the stitched near-analysis (the first 6 h of consecutive HRRR runs) 2 m temperature
  at any of the 8 zone points is >= 15 F below the same hour 24 h earlier at some hour inside the window, or an NWS
  product WS/HZ/EH/XH/HW (W or A) is in force over an ERCOT zone during it; else `calm`. `tags.forecast_bust`: on some window day the EIA DF peak
  misses the actual peak by >= 5%.
- **Filters** (V4-P18, on the tier the pack is for): P_hind - P_idle per kW of battery P at or above the split's 15th
  percentile over its candidates; P_roll - P_idle >= max($0.10/kW, 5% of P_hind - P_idle); P_hind - P_roll >= 8% of
  (P_hind - P_idle); P_roll - P_blind >= 5% of it. Candidates: 20,000 train, 1,200 eval, 400 rtcb draws (before
  V4-P9's drops), at most one window per d1 and label in the eval and rtcb draws and three in train's (V4-P21).
- **Packs**: `ercot-front-v4-train` (1,290, 2021-03..2024-12, 900 front / 390 calm (V4-P21), `front-lite` refs + P_hind),
  `ercot-front-v4-eval` (60: 40 front, 20 calm, 2025-01..2025-11; all tiers), `ercot-front-v4-rtcb` (20, 2025-12-05..
  2026-09-28, Fern +-3 days out; all tiers; flagged `rt_as: not_modelled`), `ercot-front-v4-showcase` (display only,
  on v3's showcase site `pv150-b100x2h-poi150`: `fern-0124` hero, d1 2026-01-24 at HB_NORTH; `heather-0114`, d1
  2024-01-14 at HB_NORTH; `uri-0213`, d1 2021-02-13 at HB_HOUSTON, $9,000 era; `spring-0328`, d1 2024-03-28 at
  HB_WEST, calm with negative prices), `data/fixtures-forecast/` (12 CI windows with inline slices: both tier
  families, a notice-heavy window, a deployment, a missed gate, a guide move watch). Manifests record counts, filter
  yields, front/calm shares, guide years and store sha.

## Task row (`data/ercot-front-v4-*/tasks.jsonl.gz`)

```
{"task_id":"front-v4-2025-02-18-HB_NORTH-pv150-r67-2h-poi150","forecast_version":"4.1","contract_version":"1.0",
 "pack","split","d1","days":3,"dates":[d1,d2,d3],"open":"YYYY-MM-DDT10:00:00-06:00","era","settlement_point",
 "point_kind","region","zone","weather_point","site":{v3 site row},
 "prices":[72 DA SPP],"rt":[72 hourly RT SPP],"mcpc_da":{k:[72]},"pv_cf":[72],"pv_mw":[72],
 "history":{"dam":[[24] x 7, d1-7..d1-1],"rt":[[24] x 7, d1-8..d1-2],"rt_d0":[24, d1-1],"pv_mw":[[24] x 2, d1-2..d1-1],
            "mcpc_da":{k:[[24] x 2]}},                                # revealed per the reveal table
 "actuals":{"start":"UTC ISO","load_mw":[..],"wind_mw":[..],"solar_mw":[..],"df_mw":[..]},   # EIA-930, d1-2..d3
 "reg":{"up":[72],"dn":[72],"mean_up","mean_dn","source":"seeded","label"},
 "notices":[v2 notices],"deployments":[v3 deployments],"events_sha",
 "vintages":{"store":null|"v4-store@<sha>","runs":[{"run_id","cycle","issued_at","hrrr","fh_max","backfilled"}],
             "series":[vintage...]}|{"store":"v4-store@<sha>","keys":{...}},                 # V4-P12
 "vintages_sha",
 "refs":{"forecast_version","events_sha","vintages_sha",
         "front":{"p_idle","p_roll","roll":{"dam":[..],"commits"},"p_roll3","p_blind","p_naive","p_hind","p_lp",
                  "baselines":{"naive":{"profit","reward"},"blind":{...}}},
         "front-lite":{...},"blind":{...},"freeze-6h":{...}},
 "tags":{"label":"front|calm","front_signal":{"t2m_drop_f","zone","nws":[..]},"forecast_bust","watches":{tier:n},
         "season","neg_hours","era","dam_max","rt_max","showcase":null|"fern-0124"},
 "flags":{"forecasts":"desk (modelled from NOAA HRRR as issued)","load_official":"EIA-930 DF","price_guide":"modelled",
          "pv_availability":"proxy","reg_drift":"seeded","rt_as":"not_modelled|n/a","site":"archetype",
          "hrrr":"v4|v3-36h"}}
```

A row with a `store` reference resolves through `slice_for(task, store)`; refs are computed on the resolved slice and
`vintages_sha` (sha256 over the sorted vintage shas) binds them.

## Forecast store (built by the data lane; the core reads it)

```
cache/forecast/                     raw, gitignored
  hrrr/runs.parquet                 run_id "2024-01-15T12Z", cycle_utc, issued_at_utc (cycle + 120 min),
                                    s3_last_modified_utc (max over the run's .idx), fh_max, n_fh, hrrr "v3"|"v4",
                                    backfilled (LastModified > cycle + 180 min), bytes, seconds
  hrrr/points/YYYY.parquet          run_id, point, fh, valid_utc (the instant the field is valid at), t2m_k, u80_ms,
                                    v80_ms, dswrf_wm2, tcdc_pct (float32, the nearest grid cell in points.json)
  eia930/erco.parquet               hour_end_utc, df_mw, demand_mw, wind_mw, solar_mw, battery_mw (NaN before the 2026
                                    schema), imputed flags; eia930/erco_sub.parquet: hour_end_utc, subregion, demand_mw
  ercot/raw/{report}/...            API responses as fetched (the data lane's layout)
  store/vintages/YYYY.parquet       issued_at_utc, run_id, kind, key, source, start_utc, field, values (list<double>,
                                    2 decimals), sha
                                    (kinds: weather, load, wind, solar, price, mcpc, load_official, ercot_load,
                                    ercot_wind, ercot_solar)
  store/index.parquet               kind, key, issued_at_utc, reveal_at_utc, run_id, start_utc, n_hours, sha
  store/manifest.json               spans, row counts, guide years, builder version, store sha
data/forecast/                      committed
  points.json                       the 18 points: id, lat, lon, role (site|zone|wind|solar), zone, label, grid i/j
  reveal.json                       the reveal table (forecast_inputs.REVEAL is loaded from it)
  guide-card.json                   per guide year and target class: pinball P10/P50/P90, 80% coverage, MAE vs
                                    persistence, by horizon bucket (0-14 h, 14-38 h = the DAM horizon, 38-72 h); desk
                                    MAPE per series
  store-index-sha.txt               the store sha the packs were built on
```

Desk models and the guide (one model family per series, refitted per calendar year Y on data revealed before
Y-01-01, used for the vintages issued in Y; every feature is read at the vintage's issued_at through the reveal table):

| Series | Target | Features at valid hour t (from the vintage's run unless noted) |
|---|---|---|
| desk load, `system` and each zone | EIA-930 demand (system) or subregion demand (zone) | hour, weekday, holiday, month, horizon; HRRR 2 m temperature at the zone point (system: all 8), heating and cooling degrees from 65 F, the run's temperature 3 h earlier; the latest revealed system demand and the same hour of the latest revealed day (zone models scale the system lag by the zone's prior-year share) |
| desk wind, `system` | EIA-930 ERCO wind (sum of the storage-split columns from 2026) | 80 m wind speed and its capped cube at the 4 wind points, hour, month, horizon, the fleet proxy (30-day max of revealed wind) |
| desk solar, `system` | lane D3's system cf (MW = cf x installed MW) | DSWRF and cloud at the 3 solar points, solar elevation, hour, month, horizon; the site's PV is `hybrid.pv_at_bus(site, cf)` |
| guide `price` | DA SPP and hourly RT SPP at each of the 13 pack points (pooled, point as a categorical) | calendar and horizon; desk load, wind, solar and net load at t; HRRR temperature at the point's zone; the last revealed DA day at the point (same hour, mean, max); the mean RT of the last 24 revealed hours; RT - DA of the last revealed day; the revealed DA price at t (RT targets only); era flags (ECRS, RTC+B, HCAP) |
| guide `mcpc` | DA MCPC per product | as `price` without the point, plus the last revealed MCPC of the product (same hour, mean) |

Desk series are point forecasts (`mw`); the guide gives P10, P50 and P90 (sorted per hour). HRRR features beyond a
run's last forecast hour are missing (the 37-72 h tail of every vintage, and 37-48 h before 2020-12-02); the models take
missing values natively.

The store is written through `forecast_inputs.write_store(series, root)` (one row per field, the index and the manifest
with `store_sha`), so the reader (`forecast_inputs.slice_for`) and the schema cannot drift; a row built on one store
refuses to read another (`v4-store@<sha>` must match the manifest) and a missing store fails loudly.

Store rules: desk and guide vintages exist for every HRRR run from 2021-01-01 (guide year 2021 fitted on 2019-07..
2020-12); a vintage's features are revealed at or before its issued_at (asserted per row by the builder); the guide
for year Y never sees a target or feature revealed on or after Y-01-01. Leakage tests ship with the builder: (1) the
canary test (overwrite every price and actual revealed after a cutoff with noise, refit, identical outputs before the
cutoff); (2) the per-feature reveal assertion; (3) quantiles are sorted per hour (P10 <= P50 <= P90).

## Episode JSON `gridsim.episode/v4` (path A, path B' and references write the same shape)

v3's shape over window hours, plus forecasts and DAM gates:

```
{"schema":"gridsim.episode/v4","episode_id","env":"gridsim-forecast","version":"v4","task_id","tier","bundle",
 "path":"A|B'|ref","model","trained","checkpoint_step","seed",
 "task":{d1, days, dates, era, settlement_point, point_kind, region, zone, weather_point, site, prices, rt, mcpc_da,
         pv_mw, actuals},
 "watches":[{"index","time","time_utc","freeze_line","kind":"fixed|event","notices":[event_id],"new_vintages":[..]}],
 "notices":[{"event_id","source","kind","level","issued_at","reveal_at","watch","name","title","text","deploy"}],
 "vintages":{"runs":[..],"series":[the window slice, for the fan chart and the vintage slider]},
 "forecasts_served":[{"call","watch","kind","key","issued_at","sha"}],
 "steps":[{"t","watch","tool","args","output"}],
 "dam":[{"day","gate_watch","submits","accepted":[hours],"x_da_mw":[24],"pv_da_mw":[24],"awards":{k:[24]},
         "pv_da_share","missed"}],
 "book":{"energy":[24n]},"soc_path":[24n+1],
 "hours":[{"h","time","da","rt","pv_mw","pv_p50_gate","x_da_mw","export_mw","curtailed_mw","b_mw","awards":{..},
           "reg_up_frac","reg_dn_frac","deployed_up_mwh","deployed_dn_mwh","soc_mwh","energy_da_usd","energy_rt_usd",
           "as_da_usd","deg_usd","ftp_usd","excused_usd","governor"}],
 "commits":[{"watch","from_hour","committed","refused","call"}],
 "cash":{..},"profit_usd","reward","raw_ratio","r_hind","paired_vs_anchor","beats_anchor",
 "references":{"p_idle","p_roll","p_roll3","p_blind","p_naive","p_hind","p_lp","roll":{..},"baselines":{..}},
 "audit":{"ok","problems"},"messages":[],"usage":{..},"wall_seconds"}
```

## Prompts (`gridsim_core.forecast_prompt`, shared by the env's agent card and path B')

`system_prompt(tier, era)` (the desk card: the window and gates, two settlements, the DA position rule, AS from v3 with
the era's durations, the freeze, the terminal rule, what each forecast kind is and that it is the desk's modelled
forecast, the call budgets), `situation_text(session)`, `opening(session)`, `watch_text(session)`,
`tool_schemas(tier)` (OpenAI-style; `blind` omits the forecast tools, `front-lite` omits AS fields).

## Lane plan

- **Data lane (box)**, needs from C4: this contract, `data/forecast/points.json` and `reveal.json` (committed with
  it), `scripts/fetch_hrrr_points.py` (the probe as a resumable script). Builds: `cache/forecast/hrrr` (2019-07-01 00Z
  to 2026-10-17 18Z, ~10,660 runs), `cache/forecast/eia930` (BALANCE and SUBREGION six-month CSVs 2018-H2..2026-H2,
  ERCO rows only), then `scripts/build_forecast_store.py` (desk load/wind/solar models, the yearly price guide, the
  store, `guide-card.json`, the three leakage tests), and publishes `cache/forecast` as a tarball to the private HF
  dataset or back to the laptop. Box: us-east-1 (the bucket's region; S3 to EC2 transfer is free and NODD pays the
  requests), c6in.16xlarge or similar (64 vCPU, 100 Gbps), 100 GB gp3, ~2-3 h, ~$10-15; ~3.0 TB read through the
  network, nothing stored but the points (~0.2 GB) and the store (~0.1-0.2 GB).
- **Core (C4, phase 2)**: `gridsim_core.forecast`, `forecast_prompt`, `forecast_inputs`, the two hybrid refactors,
  `scripts/build_forecast_pack.py` (packs, refs, stats in `data/forecast-stats.md`; train on the box when the store
  lands), fixtures with inline slices built from a store sample, tests (reveal table, audit, replay, anchor parity,
  v3 transcripts unchanged), `scripts/forecast_reference_episodes.py`. The Session, references and tests start on a
  deterministic synthetic slice with the store's schema; fixtures, packs and the reference episodes switch to the real
  store when the box delivers it (packs need the guide, so they cannot be built before).
- **Env lane**: `agentenv_gridsim/forecast.py` = the hybrid env's `WatchEnv` around `forecast.Session` (seven agent
  tools, hidden `grid_notice`), `forecast_tasks` (the flow above, tool access per tier: `blind` disables
  `get_forecast`/`get_forecast_drift`), bundles `front-lite`, `front`, `blind`, `freeze-6h`, `fern-0124`,
  `heather-0114`, `uri-0213`, `spring-0328`, `wiring-nodam`, `wiring-lookahead` (an agent that asks for
  `issued_at` > now must be refused and the audit must stay ok), `gridsim-forecast-verifier` (reward row, weight-0 rows,
  raising audit), `scripts/forecast_e2e.py`, sweep/report to `results/eval-v4.json` and `board-v4.md`.
  `gridsim-llm` gets the v4 nudges (a DAM gate open with no submit). Model params: max_tokens 16,384, max_turns per
  V4-P10.
- **Viewer lane**: reads Episode JSON v4 only: the forecast fan (P10-P90 of the latest vintage, older vintages as
  fading lines, the realized line to now), DAM bars against RT commits with frozen hours, the HRRR temperature/cloud at
  the site for sky and the front line, the zone mini-map from `load` per zone vs EIA actuals, the vintage slider from
  `forecasts_served`, race lanes agent / P_roll / P_blind / P_hind (reference episodes from core).
- **Pilot**: `docs/prereg/v4-pilot.md` before the first episode; GPT-6.1 Sol on ~20 eval `front` windows plus
  `fern-0124` (display) and 10 `front-lite` windows; estimate ~60-120 turns and ~$1-2 per `front` window from v3's
  pilot rates, so a ~$40 cap; results into `results/eval-v4.json`, Episode JSON for the viewer.
