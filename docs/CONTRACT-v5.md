# GridSimEnv v5 "The Market Floor" build contract

The v5 interface every lane builds against: `gridsim_core.market` (core, lane C5), the `gridsim-market` env (env lane; a
sibling of v2's `gridsim-live` and v3's `gridsim-hybrid`), the disclosure inputs and packs (data lane), the viewer and
the GPT-6.1 Sol pilot. Design source: Linear FD-4324 (v5 plan; its critique overrides win) and FD-4319 (shared rules).
`docs/CONTRACT.md` (v1), `docs/CONTRACT-v2.md`, `docs/CONTRACT-v3.md` and `docs/CONTRACT-v4.md` (its forecast store) hold
for everything not restated here. Nothing in v1-v4 changes: v5 is new modules (`gridsim_core.market`,
`gridsim_core.market_stack`, `gridsim_core.market_refs`, `gridsim_core.market_prompt`), new scripts
(`scripts/fetch_disclosure.py`, `scripts/build_market_days.py`, `scripts/build_market_pack.py`), new data (`data/market/`,
`data/gridsim-market-*`, `data/fixtures-market/`) and one backward-compatible extension of v2's watch machinery
(`live.schedule(..., regular=...)`).

`gridsim_core.market.Session` holds the only v5 state machine. The env server imports it and only wraps it, as
`gridsim-live` wraps `live.Session`; path B (`floor-sprint`) and path B' (`floor-day`) import the same code. Tool outputs
are exact strings produced by core, so path A and path B are byte-identical by construction.

## Data: what is real and what is modelled (read first)

The ERCOT public API (key in SSM, used only on the data box) serves NP3-966-ER, NP3-965-ER and NP4-523-CD for operating
days from 2023-12-11; the disclosure lags 60 days (through about 2026-08-25 today). **Every v5 task is an API-era day
re-cleared from ERCOT's real offers and bids.** No request goes to ercot.com's `/misapp` or `/misdownload` (robots.txt
disallows them) and gridstatus.io's hosted API is not used.

| Item | Source | Real or modelled |
|---|---|---|
| Background supply and demand | NP3-966-ER 60-Day DAM Disclosure: every three-part energy offer curve, energy-only offer and energy bid of the day not carved into a seat | real offers, aggregated |
| Seats B, G, R, L and A's "replay" | real portfolios carved from the same files (ESRs, combustion turbines, wind and solar, one load-serving bidder), anonymised | real offers; private costs modelled |
| Fidelity reference | NP4-523-CD DAM system lambda λ_h | real |
| Hub price | the clear runs in hub prices: every background price is raised by the hub offset o_h = real HB_HUBAVG DAM SPP (NP4-180-ER, cached) − the re-clear of every real offer (V5-P2) | real, held fixed |
| RT price | historical HB_HUBAVG 15-min RT SPP (cached NP6-905 / NP6-785), hourly mean | real, does not respond to agents |
| Forecasts as issued | v4's store kinds `ercot_load` (NP3-565-CD), `ercot_wind` (NP4-732-CD), `ercot_solar` (NP4-745-CD), issued_at = postedDatetime (V4-P17); until that store exists, EIA-930 ERCO day-ahead demand forecast and D-2 wind/solar persistence, flagged | real vintages |
| ISO | replay of the v2 notice archive (`gridsim_core.notices`) at reveal_at = ceil(issued_at, 15 min) | real |
| Copper plate, AS handling, commitment, mitigation, private costs, scripted behaviour | below | **modelled**, labelled on every card |
| Henry Hub | **not used**: G's fuel price is implied from the day's real CC offers (V5-P9) | – |

**The EIA stack.** Before the API was available, lane C5 built and measured a modelled stack (EIA-860/923 merit order,
EIA-930 must-run, fitted availability and implied gas price; `scripts/probe_market_stack.py`). No pack uses it
(V5-P1). It stays in the repo as the measured fallback and as the source of the priors below.

## Feasibility

**Prior from the modelled EIA stack** (330 random 2023–2025 days, `scripts/probe_market_stack.py --days 330`, 169 s;
fleet: 257 CC units 39.0 GW, 189 CTs 9.1 GW, 48 gas steam 11.1 GW, 24 coal 13.7 GW summer):

| Measure | All | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| 2-parameter fit: non-scarcity hours (real DAM < $100) within $5 or 10% | 76.8% | 79.3% | 80.4% | 71.0% |
| … MAE in non-scarcity hours | $4.24 | $4.28 | $3.90 | $4.52 |
| … days with ≥ 90% of hours within (the plan's bar) | 20% | 27% | 23% | 11% |
| Replay exact after the per-hour residual ε (mean \|ε\| 6.5% of demand) | 100% | | | |
| Days with any hour where A is pivotal (RSI < 1), A = 400 / 800 / 1,500 MW | 0.9 / 1.2 / 1.8% | | | |
| RSI_A 5th percentile of the daily minimum | 1.049 / 1.043 / 1.033 | | | |
| Days with ≥ 2 hours where A's quantity moves the price ≥ $5 | 45 / 67 / 79% | 47 / 60 / 74% | 33 / 60 / 76% | 54 / 79 / 87% |
| Median BR_A (2 h battery, price-maker DP, $/MW-day) | 101 / 92 / 81 | | | |
| Price-taker plan's own value overstated (median) | 12 / 22 / 36% | | | |
| BR_A gain over the price-taker plan settled at re-cleared prices | 0.5 / 2.3 / 7.2% | | | |

Readings that carry over to the real stack (to be re-measured, V5-P2): a QSE-sized battery is almost never pivotal at
system scale, so RSI mitigation alone would never bind (V5-P5); price impact is material from about 800 MW; a battery's
daily DAM value is ~$100/MW-day, so the plan's $2/kW-day headroom bar is 20× too high (V5-P11); a modelled stack misses
the plan's 90% fidelity bar on most days, which is why no pack uses it.

**Real stack: measured on the sample** (eight NP3-966-ER zips pulled through the API by lane D5: op days 2024-04-16,
2024-06-19/20, 2024-08-20, 2025-12-10, 2026-05-20/21, 2026-07-21, plus NP4-523-CD 2023-12-13..2026-10-24):

- Files: one zip per op day, posted at op day + 60 at 04:30–06:15 CPT; CSV names carry the **posting** date
  (`60d_DAM_Gen_Resource_Data-19-OCT-24.csv` is op day 2024-08-20). 13 CSVs before RTC+B; from 2025-12-05 also
  `60d_DAM_ESR_Data`, `60d_DAM_ESR_ASOffers`, `60d_DAM_AS_Only_Offers`, `60d_DAM_AS_Only_Awards`. Gen and ESR files
  have 48 columns (curve `QSE submitted Curve-MW1..10` / `-Price1..10`, `HSL`, `LSL`, `Resource Status`, `Awarded
  Quantity`, start-up and min-gen costs, AS awards); ESR curves run from −max charge to +max discharge. Energy bids and
  energy-only offers carry `Block/Curve indicator` C (curve), V (variable block) or F (fixed block) and a multi-hour
  flag. Zips are 6–10 MB; the parser takes 0.8–1.8 s before RTC+B and 4 s after. NP4-523-CD starts on 2023-12-13.
- DAM volume is financial: at HE18 on 2024-08-20, 270 of 1,390 Gen Resources offered (32.7 GW awarded) plus 15.8 GW
  of energy-only offers against 48.5 GW of bids. Most ESRs offer at the cap (before RTC+B) or at ±cap/floor (after).
- **Fidelity of the copper-plate re-clear of every real offer against NP4-523 λ**: 42–81% of non-scarcity hours within
  $5 or 10% (mean 62%), MAE $3.6–7.3 in those hours; peaks clear far too low (HE20 2024-08-20: λ $652, re-clear $112),
  the missing part being AS co-optimisation and congestion. The 64-point simplification adds at most $2.27.
- **Price impact on the real stack** (hours where A's full sale moves the price by ≥ $5): with the hub-offset
  calibration below, 0 / 1 / 8 hours for 400 / 800 / 1,500 MW on the 2024-08-20 peak and 0 on the five other days
  checked; with a horizontal residual instead, 3 / 4 / 6 on 2024-08-20, 3 / 3 / 4 on 2026-07-21, 0–3 elsewhere. Real
  DAM bids (including virtual traders) make the residual curve flat: a QSE-sized battery is a price taker in most
  hours and price-making is concentrated on peak days.
- References on the ten fixture tasks: the disclosure anchor earns $150–870/MW-day on 2024-08-20 and $150–270 on
  2026-07-21; hindsight BR_A (with RT deviations) is 2–5× the anchor; path B grades an offer in 6–9 ms; the anchor's
  welfare_ratio is 0.47–0.71.

## Decisions (all provisional until Edgar confirms)## Decisions (all provisional until Edgar confirms)

| # | Decision | Taken (provisional), recommendation |
|---|---|---|
| V5-P1 | Which days | Only API-era days (2023-12-11 onward) with the real stack. The modelled EIA stack is not used for any pack: a pre-API train extension (2022-04..2023-12, ~600 dates) would train on a market that misses the fidelity bar on 80% of days and has a different provenance from eval. Revisit only if the train pack underfits |
| V5-P2 | Fidelity and its filter | **Revised on the sample.** The raw re-clear misses the plan's 90% bar on every sample day (42–81%), so the background is calibrated with a per-hour **hub offset** o_h = real HB_HUBAVG DAM − re-clear of every real offer (AS, congestion, losses), added to every background and replay-seat price: the replay clears at the real hub price exactly, and a seat's impact follows the real curve's slope at the re-clear point. Raw fidelity is published per task (`fidelity`). Filter: raw within_ns ≥ 0.5 (survival measured on the full pull). The horizontal residual ε (MW) stays in core as an option; it puts peaks on steeper ground (more impact) at the cost of 9–21% of cleared MW of shift |
| V5-P3 | Hub price | Superseded by V5-P2's hub offset: one node, no congestion; the offset carries the real hub's AS, congestion and loss component per hour and never changes a best response |
| V5-P4 | Price formation | The aggregated background (supply minus demand) is a continuous, strictly increasing curve (ERCOT energy offer and bid curves are linear between price/MW points; block bids and offers are linearised over 1 MW) and **always sets the price**. A seat block priced exactly at λ' is awarded pro rata and rounded down to the seat's MW grid. Consequence: every seat's best response is a quantity choice per hour, an exact DP on the grid |
| V5-P5 | Mitigation | RSI_i < 1 mitigates (the plan), and since it almost never binds, **conduct and impact** (NYISO/ISO-NE/MISO practice) is the operative screen: a supply seat's hour is mitigated when a block is priced above ref + max($10, 50% of ref) and re-pricing those blocks at ref lowers λ' by ≥ max($5, 10%). Physical withholding (offering fewer MW) is measured (conduct row) and priced by the welfare half of the compliant score, not mitigated |
| V5-P6 | AS in the re-clear | AS are not re-cleared. Each background resource's energy curve is truncated to [LSL + its DAM down-award, HSL − its DAM up-awards] (the AS award columns of the same file), approximating DAM co-optimisation; seats are energy-only in the preview |
| V5-P7 | Commitment | Committed (awarded) units offer up to LSL at their curve's first price (not the floor: fidelity 62% vs 56% on the sample), uncommitted ones at the first price plus min-gen cost per MWh; AS truncation as V5-P6; frozen at the real day's commitment |
| V5-P8 | Seats | Carved from real portfolios and anonymised (ids A, B, G, R, L; no resource or QSE name leaves the data build): A = a group of real ESRs totalling 400–1,500 MW (its real offers are the `replay_A` baseline); B = another ESR group; G = 6–12 real CTs (Resource Type SCGT90/SCLE90, 50–100 MW each); R = wind and solar resources totalling 1–3 GW; L = one real load-serving bidder's energy bids at load zones, 3–8 GW |
| V5-P9 | Private costs | G: per-unit heat rate drawn from EIA-923's ERCOT CT distribution (until a resource↔plant crosswalk exists), fuel = the day's gas price implied by real CC offers (median CC mid-curve price ÷ 7.2 MMBtu/MWh after VOM), VOM $5, start cost from its three-part offer; R: −PTC $27.50 on 60% of output; L: a fixed tariff (EIA Electric Power Monthly Texas average, energy share 50%) and RT for its unhedged load; A, B: v1 archetype η and c_deg, E = P × the drawn duration (the disclosure has no MWh before RTC+B). No Henry Hub |
| V5-P10 | Disclosure shipped | Only derived aggregates: per hour ≤ 64 breakpoints per side for the background and ≤ 16 per seat portfolio; the raw zips never ship; ERCOT attribution and no-endorsement as v1 |
| V5-P11 | Headroom filter | The plan's $2/kW-day is ~20× a battery's daily DAM value. Use BR_A − P_idle ≥ $25/MW-day and P_anchor − P_idle ≥ $10/MW-day |
| V5-P12 | Pivotal-hour filter | **Open (needs Edgar).** On the real stack the plan's "≥ 2 hours with ≥ $5 impact" keeps almost only peak days. Options: (a) keep it and accept a peak-day pack; (b) relax to ≥ 1 hour or ≥ $2; (c) switch V5-P2 to the horizontal residual. Recommendation: (b) for train, (a) as the eval tag `impact_hours` |
| V5-P13 | Tiers | `floor-sprint` (training, path B) and `floor-day` (eval) build tonight; `compliant` is a scoring of either; `floor-week` deferred |
| V5-P14 | Bidders | Scripted in-process only (`bidders: "scripted"`): B, G, R, L submit their **real** offers of the day (replay) by default, or a cost-based script (`script: "cost"`) for the ε-Nash reference. The A2A route is specified below and not built: four extra LLM agents per episode, and the preview spends nothing |
| V5-P15 | Welfare | W counts the DAM clear at bid value for the background and private cost for the seats; welfare_ratio = (W − W_0)/(W\* − W_0) over W_0 = the clear with A and B idle; W\* from a HiGHS LP. Compliant = 0.5·R + 0.5·clip(welfare_ratio, 0, 1) |
| V5-P16 | Splits | train 2024-02-11..2024-12-31 (the anchor needs D−62 ≥ 2023-12-11), ~325 dates × 9 seat draws ≈ 3,000; eval 2025-01-01..2025-11-30 (200 sprint + 60 floor-day); rtcb 2025-12-05..the latest posted day; showcase `fern-0123` (op days 2026-01-23..27) and, replacing the pre-API `aug23-0810`, `aug24-0820` (2024-08-20, an ERCOT summer peak day [to confirm the record]); each showcase day ±3 days out of every split |
| V5-P17 | Viewer | Per the standing direction that sim viewers look like real life, the Market Floor is a real-life 3D scene, not the plan's 8-bit hall; the merit-order staircase, gavel and seat board become overlays (viewer lane proposes) |

## As built in phase 2 (refinements of the text below)

- **Battery lattice**: SoC in steps of grid_mw/20 MWh; sells move −20 steps per grid unit, buys +20η (η ∈ {0.80,
  0.85, 0.90, 0.95}), so every BR DP is exact. No cycle cap in v5 (c_deg prices cycling). The end-shortfall price is
  fixed per task at max(the real hub DAM maximum, $50).
- **Prices**: offers, the clear and settlement are all in hub $/MWh (the offset above); `hub_basis_usd` and `eps_mw`
  are gone from the rows. The anchor maps its disclosure forecast to hub prices with the disclosed day's own offset.
- **Floor-day watches**: v2's 10-watch cap (7 regular, so up to 3 notice watches); notices revealed before D-1 06:00
  are on the opening board. `floor-sprint` has no notices.
- **Seats**: R's actual output is its DAM offer volume (no forecast error modelled tonight); L's load is its bid volume
  scaled by EIA-930 load/DF; G's heat rates are drawn from EIA-923 2025 ERCOT CTs (seeded); B is the second ESR group.
- **ε-Nash and the reference profile** start from the replay profile (every seat on its real offers); W counts A and
  B at their delivered MW and every other participant as bid; W\* is the HiGHS LP with A's and B's SoC.
- **Code**: `gridsim_core.market_auction` (curves, clear, mitigation, offers, battery settlement),
  `market_stack` (`parse_disclosure`, `choose_pool`, `build_day`, `sample_seats`, `DayStore`, `Floor`, `disclosure`,
  `hub_offset`), `market_refs` (`forecast_books`, `anchor`, `battery_dp`, `br_*`, `eps_nash`, `nash`, `welfare`,
  `welfare_lp`, `references`), `market` (`Session`, `finalize_task`, `anchor_policy`, `play`, `replay`, `grade_offer`,
  `reward_fn`, `schedule`, `triggers`), `market_prompt`; `scripts/build_market_fixtures.py`; `data/fixtures-market/`
  (10 tasks on op days 2024-08-20 and 2026-07-21 with their D−61, D−62 and D−1..D−3 days); `tests/market/` (28 tests).

## Clock and tiers

Times are CPT; core counts minutes from D 00:00 (v2): D-1 06:00 = −1080, D-1 09:00 = −900, DAM close D-1 10:00 = −840,
awards D-1 13:30 = −630, D 24:00 = 1440. Day D is never a DST day. The reveal rule, notice merging (L-D4), the 1 h
freeze (`live.freeze_line`) and the shared audit rows are v2's.

| Tier | Watches | What the agent does | Turns / calls | Role |
|---|---|---|---|---|
| `floor-sprint` | one, D-1 09:00 | reads, ≤ 3 `check_offer`, one final `submit_offer` (ends the floor) | 6 turns, 24 calls | training (path B), path-A parity |
| `floor-day` | D-1 06:00, D-1 09:00, awards 13:30, D 00:00/06:00/12:00/18:00, notice watches (cap 12) | offers (re-submittable until 10:00), CfDs with L until 10:00, then the op-day physical schedule | 36 turns, 120 calls | main eval |
| `compliant` | either | the same task, scored 0.5·R + 0.5·clip(welfare_ratio, 0, 1) | – | public board default |

`floor-sprint` delivery is the SoC-feasible projection of the awards; `floor-day` delivery follows the awards until the
first accepted `commit_schedule` (v2 L-D2). `live.schedule(task, tier, notices, regular=...)` gains an optional tuple of
regular watch minutes (default unchanged).

## Market model

### Background (`gridsim_core.market_stack`, built by the data lane, rebuilt bit-for-bit by core)

For op day D and hour h, from NP3-966-ER (file and column names fixed on the sample):

- **Supply**: every Gen Resource's three-part energy offer curve (QSE-submitted MW1..MW10 / Price1..Price10, linear
  between points) inside its V5-P6 range with the V5-P7 commitment rule; every energy-only offer curve. ESRs before
  RTC+B: the Gen Resource side here, the Controllable Load Resource's bid on the demand side; after RTC+B the single ESR
  curve split at 0 MW.
- **Demand**: every energy bid curve (physical and virtual), price-sensitive as submitted. PTP obligations and options
  are dropped (zero net injection on one node).
- **Carve**: the five seats' resources and bids are removed. The rest is aggregated into the net background curve
  N_bg,h(λ) = supply(λ) − demand(λ), made strictly increasing (+1e-6 MW per $), simplified to ≤ 64 breakpoints per hour
  per side, dense in ±10 GW around the day's cleared quantity (the simplification error is reported), extended linearly
  to the era cap and floor.
- **Residual ε_h** (V5-P2 fallback only): the horizontal shift that makes the replay clear at λ_h.

Expected NP3-966-ER contents, one zip per op day (names and columns **[to confirm on the sample]**; the parser keys on
column names, never positions):

| File (`60d_…-DD-MON-YY.csv`) | Columns used |
|---|---|
| `DAM_Gen_Resource_Data` | Delivery Date, Hour Ending, Resource Name, Resource Type, QSE (dropped after the carve), Resource Status, LSL, HSL, Awarded Quantity, Energy Settlement Point Price, QSE submitted Curve-MW1..MW10 and Curve-Price1..Price10, Start Up Hot/Inter/Cold, Min Gen Cost, the RegUp, RegDown, RRS, ECRS and NonSpin awards |
| `DAM_Load_Resource_Data` | Delivery Date, Hour Ending, Load Resource Name, Max/Low Power Consumption, the AS awards, and (CLRs, pre-RTC+B ESR charging) their bid curves |
| `DAM_EnergyBids`, `DAM_EnergyBidAwards` | Delivery Date, Hour, Settlement Point, QSE, Bid Id, Energy Only Bid MW1..10 and Price1..10, Multi-Hour Block indicator, award MW |
| `DAM_EnergyOnlyOffers`, `DAM_EnergyOnlyOfferAwards` | as the bids, offer side |
| `DAM_PTPObligationBids`, `…Awards`, PTP options, `DAM_QSE_Self_Arranged_AS` | read for totals only, dropped from the clear |
| post-RTC+B ESR file or columns | the single ESR curve (MW from −max charge to +max discharge), AS awards |

### The auction (`market.clear`)

24 independent hourly uniform-price auctions on one node, prices in cents, cap and floor from `contract.era(D)` (all v5
days: $5,000 and −$250).

```
f(λ) = N_bg,h(λ) + Σ_seats q_i(λ)         q_i(λ) = Σ sell blocks priced ≤ λ − Σ buy blocks priced ≥ λ
λ' = min{λ : f(λ) ≥ 0}                    bisection on the merged block prices, then inversion of N_bg
p*_h = λ'_h                               every background price already carries the hub offset o_h (V5-P2)
```

If f is continuous at λ', every seat block priced < λ' (sell) or > λ' (buy) is awarded in full and the rest not. If seat
blocks sit exactly at λ', they share the gap pro rata, each seat's share rounded down to its grid; the background then
takes the remainder and the final λ' is N_bg⁻¹(−net seat awards) (V5-P4). Background exhausted → cap, curtailment logged;
below its floor → floor. Ties among seats at one price split by MW, then seat order A, B, G, R, L. Deterministic, < 1 ms
per hour.

**Mitigation** (V5-P5), per hour and per supply seat in order A, B, G, R: conduct = a sell block priced > ref + max($10,
0.5·|ref|); impact = λ' − λ'(that seat's conduct blocks re-priced to ref) ≥ max($5, 0.10·|λ'|); RSI_i,h = (background
supply at cap + Σ_{j≠i} sell MW_j) / (background demand at cap + Σ buy MW) < 1 mitigates without the impact test. A
mitigated seat's conduct blocks are re-priced to ref and the hour re-clears. References: battery = 1.1·max(c_deg, μ_h),
μ_h the marginal value of stored energy at hour h in the seat's price-taker DP on the anchor's forecast (stored in the
task, shown to the seat by `get_private_costs`); gas unit = 1.1·(its V5-P9 cost); renewable = $10. L is not mitigated.

### Seats

| Seat | Name | Private data (task row) | Replay offer (`script: "real"`, default) | Cost script (`script: "cost"`, ε-Nash reference) |
|---|---|---|---|---|
| A | `bess-A` | p_mw (sum of the group's HSL), e_mwh, grid_mw = P/20, η, c_deg, s0, s_end_min, cycle_cap_mwh | the group's real offers and bids, snapped to A's grid (baseline `replay_A`) | as B's cost script |
| B | `bess-B` | battery, 300–1,500 MW | real offers and bids | price-taker DP on the anchor's forecast; sell at μ_h, buy at η·μ_h |
| G | `gas-G` | units [{id, mw, lsl, hr, vom, start_usd}], fuel_usd_mmbtu | real three-part offers | one block per unit at cost + start_usd/(mw·6 h) |
| R | `renew-R` | actual_mw[24], forecast_mw[24], ptc_usd, ptc_share | real offers | forecast MW: ptc_share at −ptc_usd, the rest at $0 |
| L | `retail-L` | load_mw[24], forecast_mw[24], tariff_usd, dr_share, dr_usd, risk_lambda | real energy bids | (1 − dr_share)·forecast at cap, dr_share·forecast at dr_usd |

R's actual output and L's actual load are the group's share of ERCOT's actual wind, solar and load (EIA-930) scaled by
their DAM offer and bid volumes; NP3-965-ER telemetry replaces them when the data lane parses it. Seats never see each
other's private data or offers. Profits (hub prices): battery π = Σ award·p\* + Σ (exec − award)·RT_h − c_deg·discharged
MWh − end penalty (v1 rule); gas π = Σ award·(p\* − cost) − starts; renewable π = Σ award·p\* + (actual − award)·RT_h +
ptc_usd·ptc_share·actual; retailer π = tariff·Σ load − Σ award·p\* − Σ (load − award)·RT_h.

### Offer format (`check_offer` / `submit_offer`)

One monotone ESR curve per hour, written as blocks (λ-space prices, as ERCOT offers):

```
{"hours": [{"he": 18, "sell": [[mw, price], ...], "buy": [[mw, price], ...]}, ...]}    # or the JSON string of it
```

- `he` 1..24; an omitted hour offers nothing. MW are positive multiples of `grid_mw`; Σ sell ≤ p_mw, Σ buy ≤ p_mw; ≤ 10
  blocks per hour; prices in [floor, cap], rounded to cents; within an hour max(buy price) < min(sell price) (rules
  `grid`, `power`, `blocks`, `price_range`, `crossed`, `parse`). Injection at λ: Σ sell priced ≤ λ − Σ buy priced ≥ λ.
- **Idle** = a valid offer with no blocks (`{"hours": []}`), P_idle = 0 for every pack task (s_end_min ≤ s0); **no valid
  `submit_offer` → reward 0**. A refused submit counts as not submitted. `as_awards` is reserved and refused.

### Physical delivery and settlement (seat A)

- **Projection** (`floor-sprint`, and `floor-day` before any accepted `commit_schedule`): from s0, hour by hour, exec_h =
  award_h clipped to the rate, the SoC room (discharge ≤ s, charge ≤ (E − s)/η) and the cycle cap; clipped hours listed,
  nothing excused.
- `floor-day` `commit_schedule(plan, from_hour)`: hourly MW in [−P, P], continuous (v3 C3-D1), v3's per-hour in-order
  rules (`frozen`, `power`, `soc_empty`, `soc_full`, `cycle_cap`), 1 h freeze, refused below s_end_min at 24:00
  (`end_target`, v2 L-D3).
- P = Σ_h award_h·p\*_h + Σ_h (exec_h − award_h)·RT_h − c_deg·Σ max(exec_h, 0) − shortfall/η·max(max_h p\*_h, P_FLOOR).
  CfDs settle in their own row, never in P.

## References and reward (`market_refs`; stored in the task row, recomputed and checked at end-floor)

- **P_idle**: A offers nothing, the others on replay → 0.
- **P_anchor, the disclosure best-responder (1.0)**, information-matched to A at D-1 09:00: (1) it reads the disclosed
  aggregate supply and demand curves of X = D − 61 and X' = D − 62 (≤ 64 breakpoints per hour, exactly what
  `get_disclosure` serves); (2) its forecast net curve for day T ∈ {D−1, D} shifts the disclosed day's curve horizontally
  by the as-issued forecast delta of (load − wind − solar) between T and its disclosed day, plus one δ (MW) fitted on D−1
  (X' against D−1's published λ, L1, grid −15..15 GW, step 100 MW); its hub basis forecast is D−1's b_h; (3) it
  best-responds to p̂_h(q) with the price-maker DP below, self-schedules the quantities (sell at the floor, buy at the
  cap) and settles in the true re-clear; (4) in `floor-day` it runs the op-day with v2's notice-blind rolling re-planner
  (hourly, decayed RT−DA basis), committing at each watch. It signs no contract.
- **BR_A (hindsight, weight 0)**, others' offers fixed as played, inside the mitigated set (self-schedules are never
  mitigated): `floor-sprint`: v1's DP state (SoC s ∈ 0..N, N = 20·E/P, and discharge used), a ∈ −20..20 award units,
  stage value q·p_h(q) + (x − q)·RT_h − c_deg·max(x, 0) with x the projection of q from s, terminal shortfall penalty;
  p_h(q) = `clear` with A self-scheduled at q. `floor-day`: separable, Σ_h max_q q·(p_h(q) − RT_h) plus the exact physical
  DP on RT with the hard end target. 24·41 clears (≈ 50 ms).
- **Other seats' BR** (ε-Nash, weight 0): battery as above; gas: DP over k units on (cheapest first, full output) with
  start costs; renewable: per hour max over q ∈ {0, grid, …, forecast} of q·p_h(q) + (actual − q)·RT_h; retailer: per
  hour max over buys q ∈ {0, grid, …, 1.2·forecast} of −q·p_h(−q) − (load − q)·RT_h.
- **ε-Nash** of the realised profile: max over seats of (BR_i − π_i)/(BR_i − π_i_idle) (0 when the denominator ≤ $1).
  **Reference profile**: Gauss-Seidel iterated BR from the cost scripts in seat order A, B, G, R, L, ≤ 50 sweeps, stop
  when no seat gains > $1, `nash.eps` if not converged. Eval and showcase packs only.
- **Welfare** (V5-P15): W = Σ_h [∫ demand bid value served − ∫ background offer cost − seats' private costs]; W\* from a
  HiGHS LP over seat awards with A's and B's SoC constraints, G's capacity (start costs relaxed), R's forecast and L's
  bids, the background as its curve; W_0 the clear with A and B idle. `welfare_ratio = (W − W_0)/(W* − W_0)` (1.0 when
  W\* − W_0 ≤ $1), `dwl_usd = W* − W`.
- **Reward**: no valid submit → 0; else `R = grade.reward_value(P, P_idle, P_anchor)` (clip(0.2 + 0.8·…), 6 decimals).
  `compliant_reward = round(0.5·R + 0.5·clip(welfare_ratio, 0, 1), 6)`. No format credit.
- **Weight-0 rows**: `regret_usd = BR_A − P`, `regret_norm = (BR_A − P)/(BR_A − P_idle)`, `beats_anchor`, `eps_nash`,
  `welfare_ratio`, `dwl_usd`, `profit_usd_per_kw_day`, `rank` (A's π/MW among the seats), the contract row, the conduct
  row {mitigated_hours, withholding_index = (MW offered above 1.5·ref + SoC-feasible MW not offered, in hours with
  λ' > ref) ÷ (P·24), message_flags}, `fidelity`, baselines {idle, max_withhold, price_taker, replay_A} as {profit,
  reward}.

**Contracts** (`floor-day`, weight-0 row): a CfD on the hub DAM price settling mw·(strike − p\*_h) to the seller (A may
sell or buy), binding once both confirm, ≤ 3 open, only before 10:00 D-1, op_dates = [D]. Scripted L accepts a strike
within fair_h ± premium (fair = mean of the anchor's p̂ over the contract hours, premium = risk_lambda·σ̂, σ̂ = the
anchor's D−1 forecast MAE) and ≤ 25% of its forecast in each contract hour; outside the band it counters once at the band
edge, then rejects. Row (signed for A): `value_at_signing_usd = Σ ±mw·(strike − fair)`, `settled_usd = Σ ±mw·(strike −
p*)`.

## Tools (role `default`, seat A; outputs are the dicts below plus `"messages"`)

Errors: `{"error": "...", "calls_left": {...}}`, nothing changes. Planning calls (`check_offer`, `submit_offer`,
`check_schedule`, `commit_schedule`) share 3 per watch (v2 L-D7 counting); `get_disclosure` and `get_forecast` share 6
per watch; the rest are free. Money is rounded to cents, MW to 2 decimals.

- `get_situation()`:

```
{"floor_id","tier","op_date","era","time":"2025-08-19 09:00","watch":k,"phase":"pre_close|awaiting_awards|op_day|done",
 "dam_close":"2025-08-19 10:00","minutes_to_close":60,"calls_left":{"planning":3,"data":6},
 "market":"ERCOT DAM re-cleared from the real 60-day disclosure on one node; hub price = cleared energy price + the real hub basis",
 "rules":{"price_cap":5000,"price_floor":-250,"grid_mw":40,"max_blocks_per_hour":10,"freeze_h":1,"mitigation":"conduct and impact"},
 "seat":{"name":"bess-A","p_mw","e_mwh","grid_mw","eta","c_deg","s0_mwh","s_end_min_mwh","cycle_cap_mwh"},
 "public":{"dam_prev_day":{"lambda_usd":[24],"hub_usd":[24]},"rt_last_day_usd":[24],"disclosure_latest":"2025-06-19",
           "peers":["bess-B","gas-G","renew-R","retail-L"]},     # D-1's DAM (published D-2 13:30); RT of D-2
 "offer":{"submitted":bool,"hours":[...]}|null,"award":{"mw":[24],"hub_usd":[24]}|null,
 "schedule":{"mw":[24],"status":"SSFF…OO"}|null,"soc_mwh":x,"contracts":[...],"notices":[...],"result":{...}|null}
```

- `get_forecast(kind, issued_at?)` (data call): kind `load`, `wind`, `solar` (v4's vintages: `{"kind","issued_at",
  "source","from","mw":[n],"p80_mw":[n]|null}`), `dam_prices` (D-1's λ and hub SPP), `rt_prices` (settled hours only).
  Refuses issued_at > now.
- `get_disclosure(op_date, side="supply"|"demand", hour?)` (data call): refused unless op_date ≤ date(now) − 60 days and
  op_date ≥ max(D − 90, 2023-12-11). With `hour`: `{"op_date","hour","side","curve":[[mw, price], ...] (≤ 64 points,
  cumulative MW ascending), "cleared_mw","lambda_usd"}`; without: 24 hours at ≤ 16 points. Aggregated and anonymised.
- `get_private_costs()`: the caller's seat only (server-side filter on agent_name): `{"seat","eta","c_deg",
  "reference_usd":[24],"cycle_cap_mwh","s_end_min_mwh","contracts":[...]}`.
- `check_offer(offer)` (planning): `{"valid","issues":[{"he","rule","detail"}],"estimate":{"lambda_usd":[24],
  "hub_usd":[24],"award_mw":[24],"dam_usd"},"projection":{"exec_mw":[24],"soc_mwh":[25],"clipped_hours":[...],
  "end_shortfall_mwh"},"calls_left"}`; the estimate clears against **the anchor's disclosure-based forecast only**.
- `submit_offer(offer)` (planning): `floor-sprint`: final; clears, projects, settles: `{"submitted":true,"done":true,
  "award":{"mw":[24],"hub_usd":[24]},"mitigated_hours":[...],"exec_mw":[24],"pnl":{...},"profit_usd"}` (reward and
  references only via `data/get`). `floor-day`: `{"accepted","issues","replaces_previous","calls_left"}`; the last
  accepted submit before 10:00 counts.
- `get_award(op_date)` (`floor-day`, after 13:30): `{"award_mw":[24],"lambda_usd":[24],"hub_usd":[24],
  "mitigated_hours":[...],"dam_value_usd"}`.
- `check_schedule(plan, from_hour)` / `commit_schedule(plan, from_hour)` (`floor-day`, after awards): v3's shapes, energy
  only.
- `advance()` (free, `floor-day`): to the next watch; crossing 10:00 runs `clear_market` and freezes offers and contracts;
  op-day watches settle hours as v3 (`settled` rows with `rt_usd`, `award_mw`, `exec_mw`, `usd`).
- `propose_contract(counterparty, kind="cfd", hours, mw, strike_usd, op_dates)` → `{"contract_id","status":"proposed|
  accepted|countered|rejected","counter_strike_usd"?}`; `respond_contract(contract_id, action: "accept"|"reject"|
  "counter", strike_usd?)`.
- `message_agent(agent_name, text)` → `{"delivered": true, "reply": null}`; scripted bidders do not read messages; each
  is logged and screened for price talk outside contract terms.
- Hidden (harness only): `clear_market(op_date)`, `grid_notice(...)` (v2). URNs `urn:gridsim:market-load/v1 {floor_id,
  tier, bidders: "scripted", script: "real"|"cost", contracts: bool, iso: "replay"|"off"}` → `{"floor_id","tier",
  "watches"}`; `urn:gridsim:end-floor/v1` → `s.end_floor()` = `{"end_reason","profit_usd","reward","compliant_reward",
  "audit"}`; `urn:agentenv:clock/v1`; `data/get` → `s.data()`; `data/reset`.

Role `bidder` (A2A route, not built): `get_private_costs`, `get_market_info` (the `public` slice), `submit_offer`,
`get_award`, `propose_contract`, `respond_contract`; bidders are not peered with each other.

## gridsim_core.market API

```python
from gridsim_core.market import (Session, clear, parse_offer, OfferError, project, settle_seat, grade_offer, reward_fn,
                                 references, replay, play, schedule, triggers, MARKET_VERSION, MARKET_ENV,
                                 EPISODE_SCHEMA, TIERS, TOOLS, SEATS, LOAD_URI, END_URI, PLANNING_CALLS, MAX_TURNS)
from gridsim_core.market_stack import load_day, background, net_curve, invert, disclosure, simplify, calibrate_eps
from gridsim_core.market_refs import anchor, br_battery, br_gas, br_renewable, br_retailer, nash, welfare_lp
s = Session(task, tier="floor-sprint", notices=None, script="real")
s.call(tool, args) -> str                                       # exact output string, transcript recorded
s.end_floor() / s.grade() / s.audit(get_time_reads=None) / s.data() / s.episode(**meta) -> gridsim.episode/v5
grade_offer(task, offer) -> grade dict                           # path B, floor-sprint, ~5 ms, == Session grade to 1e-6
reward_fn(prompts, completions, task=None, **kw) -> list[float]  # TRL entry; parses the submit_offer tool call
references(task, tiers=("floor-sprint", "floor-day"), nash=False) -> refs dict
```

`MARKET_VERSION = "5.0"`, `MARKET_ENV = "gridsim-market"`, `EPISODE_SCHEMA = "gridsim.episode/v5"`, `TIERS =
("floor-sprint", "floor-day")` (+ the `compliant` scoring flag), `SEATS = ("A", "B", "G", "R", "L")`, `PLANNING_CALLS =
3`, `MAX_TURNS = {"floor-sprint": 6, "floor-day": 36}`.

`grade()` → `{"submitted","tier","reward","compliant_reward","raw_ratio","profit_usd","pnl","p_idle","p_anchor","p_br",
"regret_usd","regret_norm","beats_anchor","eps_nash","welfare_ratio","dwl_usd","profit_usd_per_kw_day","rank",
"contract","conduct","fidelity","baselines","mitigated_hours","clipped_hours"}`.

## Audit (`s.audit()`; a failure makes the run unscored)

v2's rows (watch delivery, nothing before reveal_at, once each, get_time, byte-identical `replay`) plus: no output showed
an hour's RT price before the hour ended; every served forecast had issued_at ≤ now; `get_disclosure` never served an
op_date > date(now) − 60 days; no output showed another seat's private data or current offers; `check_offer` estimates
used only the disclosure forecast; `clear_market` ran exactly once (the 10:00 crossing, or the final sprint submit).

## Property tests (CI on `data/fixtures-market/`)

1. The replay profile re-clears within the task's stored `fidelity` (and exactly at λ when ε is in use).
2. BR_A ≥ P for every sampled offer (random block curves incl. mitigated ones; hypothesis), and BR_A ≥ P_anchor, P_idle.
3. Max-withhold-then-deviate (all sell blocks at cap, physical schedule = the RT DP) never beats BR_A on any fixture day.
4. Path B `grade_offer` equals the Session's grade to 1e-6 for the same offer; recorded transcripts replay byte for byte.
5. A self-schedule is never mitigated; a mitigated hour's λ' is ≤ the unmitigated one.
6. Each seat's own iterated-BR step never lowers its π; W\* ≥ W of every sampled profile.
7. `get_disclosure` refuses every op_date > date(now) − 60 days, and the anchor reads only what it serves.
8. Rebuilding a day's curves from the shipped breakpoints reproduces the stored replay λ' to $0.01.

## Data layout and task row (the data lane builds to this)

```
cache/disclosure/raw/np3-966-er/<op_date>.zip   on the data box only (never shipped); NP3-965-ER likewise
cache/disclosure/np4-523.jsonl                  λ for every API-era op day
data/market/days/<YYYY-MM>.jsonl.gz             one row per op day (below)
data/market/manifest.json                       endpoints, docIds, postDatetime, sha256 of each zip, parser version,
                                                fidelity summary, ERCOT terms and attribution
data/market/stats.md                            fidelity and survival per filter, impact, RSI, headroom, simplification error
data/gridsim-market-{train,eval,rtcb,showcase}/tasks.jsonl.gz + manifest.json
data/fixtures-market/                           20 CI tasks + the days rows they read (D, D−1, D−61, D−62)
```

Days row (curves in offer $/MWh as submitted, anonymised; `pool` holds the candidate seat portfolios of the day, and
whatever a task does not carve is added back to the background by exact curve addition; light rows for D−1..D−3 carry
only the public series):

```
{"date":"2024-08-20","dst":false,"parser":"966-v1|966-rtcb-v1|light",
 "lambda_usd":[24],"hub_dam_usd":[24],"hub_rt_usd":[96],"df_mw":[24],
 "actuals":{"load_mw":[24],"wind_mw":[24],"solar_mw":[24]},                    # EIA-930 TEX
 "background":{"supply":[[[mw, price], ...] x 24],"demand":[[[mw, price], ...] x 24]},   # ≤ 64 points each
 "pool":{"esr":[{"id":"e1","size_mw","sell":[[[mw, price]] x 24],"buy":[...]}],
         "ct":[{"id":"c1","size_mw","units":[{"id","mw","lsl","start_usd"}],"sell":[...]}],
         "renew":[{"id":"r1","size_mw","sell":[...]}],"load":[{"id":"l1","size_mw","buy":[...]}]},
 "replay":{"lambda_usd":[24],"full_lambda_usd":[24],"cleared_mw":[24]},       # re-clear of what ships / of every offer
 "fidelity":{"within_ns","ns_hours","mae_ns_usd","mae_usd","max_err_usd","simplify_err_usd"},
 "implied_gas_usd_mmbtu":1.538}
```

Task row:

```
{"task_id":"mkt-v5-2024-08-20-A800x2-e1","market_version":"5.0","contract_version":"1.0","pack","split","date","era",
 "point":"HB_HUBAVG","region":"central",
 "seats":{"A":{"name":"bess-A","kind":"battery","pool_id":"e1","p_mw":800,"e_mwh":1600,"grid_mw":40,"eta":0.86,
               "c_deg":4.0,"s0_mwh":800,"s_end_min_mwh":800,"cycle_cap_mwh":2400,"reference_usd":[24]},
          "B":{"name":"bess-B","pool_id":"e2",...},"G":{"name":"gas-G","pool_id":"c1","units":[...],"fuel_usd_mmbtu":2.71},
          "R":{"name":"renew-R","pool_id":"r1","actual_mw":[24],"forecast_mw":[24],"ptc_usd":27.5,"ptc_share":0.6},
          "L":{"name":"retail-L","pool_id":"l1","load_mw":[24],"forecast_mw":[24],"tariff_usd":95.0,"dr_share":0.07,
               "dr_usd":180.0,"risk_lambda":0.5}},
 "public":{"dam_prev_day":{"lambda_usd":[24],"hub_usd":[24]},"rt_last_day_usd":[24],"forecast_slice":{v4 slice}|null,
           "disclosure_days":["2024-05-22", ... "2024-06-20"]},
 "notices":[v2 notices],"notices_sha":"…",
 "refs":{"market_version":"5.0","p_idle":0.0,
         "floor-sprint":{"p_anchor","anchor":{"forecast_lambda_usd":[24],"delta_mw","q_mw":[24],"hub_usd":[24]},
                         "p_br","br":{"q_mw":[24]},
                         "baselines":{"max_withhold":{"profit","reward"},"price_taker":{...},"replay_A":{...}}},
         "floor-day":{...},"welfare":{"w0","w_star","w_replay","lp_status"},"nash":{...}|null,
         "headroom_usd_per_mw":{"br","anchor"},"impact_hours":n,"pivotal_hours":n},
 "fidelity":{...the day's...},
 "tags":{"season","neg_hours","spike":bool,"notice_day":bool,"rtcb":bool,"showcase":null|"fern-0123"},
 "flags":{"stack":"real","copper_plate":true,"as":"truncated","costs":"modelled","forecast":"ercot|eia930"}}
```

Task ids `mkt-v5-{date}-A{P}x{E/P}-{pool_id}`; the tier is the load config. Packs: `gridsim-market-train`,
`gridsim-market-eval`, `gridsim-market-rtcb`, `gridsim-market-showcase` (display only), `data/fixtures-market/` (V5-P16;
counts in the manifests). Filters: V5-P2, V5-P11, V5-P12; a day with a missing file or a parse error drops (never
imputed); DST days drop. If `data/market/` exceeds ~30 MB gzipped, train days move to the Hub dataset (`v5_days`) and git
keeps eval, rtcb, showcase and fixtures self-contained, as v4's store does.

## Episode JSON `gridsim.episode/v5` (path A, B, B' and references write the same shape)

```
{"schema":"gridsim.episode/v5","episode_id","env":"gridsim-market","version":"v5","task_id","tier","compliant":bool,
 "bundle","path":"A|B|B'|ref","model","trained","checkpoint_step","seed",
 "task":{date, era, point, region, seat_A (full), seats_public:{B,G,R,L: name, kind, size}, lambda_real:[24],
         hub_dam_real:[24], hub_rt_real:[96], flags},
 "watches":[...],"notices":[...],"steps":[{"t","watch","tool","args","output"}],
 "offers":{"A":{...},"B":{...},"G":{...},"R":{...},"L":{...}},
 "stack":[{"he","background":{"supply":[[mw, price]] (≤ 48),"demand":[[mw, price]] (≤ 48)},
           "seats":{"A":[[mw, price, "sell|buy"]],...}}],
 "clear":{"lambda_usd":[24],"hub_usd":[24],"lambda_real":[24],"lambda_replay":[24],"cleared_mw":[24],
          "mitigated":[{"seat","he","impact_usd"}],"curtailed_mw":[24]},
 "awards":{"A":[24],"B":[24],"G":[24],"R":[24],"L":[24]},
 "hours":[{"h","hub","rt","award_mw","exec_mw","dev_mw","soc_mwh","dam_usd","rt_usd","deg_usd","mitigated","clipped"}],
 "contracts":[...],"messages_audit":[...],
 "pnl":{...},"profit_usd","reward","compliant_reward","raw_ratio",
 "rows":{"regret_usd","regret_norm","eps_nash","welfare_ratio","dwl_usd","profit_usd_per_kw_day","rank","contract",
         "conduct","fidelity"},
 "seat_results":{"B":{"profit_usd","br_usd"},"G":{...},"R":{...},"L":{...}},
 "references":{"p_idle","p_anchor","p_br","anchor":{...},"br":{...},"baselines":{...},"welfare":{...},"nash":{...}},
 "audit":{"ok","problems"},"messages":[],"usage":{...},"wall_seconds"}
```

## Prompts (`gridsim_core.market_prompt`, shared by the env's agent card and path B / B')

`system_prompt(tier)` (auction, blocks, mitigation, settlement, the copper-plate line), `situation_text(session)`,
`opening(session)`, `watch_text(session)`, `tool_schemas(tier)`, `sprint_messages(task)` (path B: one prompt whose
completion ends in a `submit_offer` tool call, with the `get_situation` text and the latest disclosure summary inline).

## Lanes

- **Data lane** (on the data box; the API key stays there): `scripts/fetch_disclosure.py` pulls NP3-966-ER zips for every
  op day 2023-12-11..latest (one archive doc per day; ~1,000 days at 30 requests/min), NP4-523-CD for the same span and,
  optionally, NP3-965-ER; `scripts/build_market_days.py` parses them with `market_stack`'s parser (core owns the parser
  so packs and env cannot drift), carves the candidate pool, aggregates, simplifies and writes `data/market/`;
  `scripts/build_market_pack.py` draws seats and writes packs with `market.references`. Needs from C5: the parser for
  both schemas (fixed on the sample), `background`, `simplify`, `disclosure`, `calibrate_eps`, `sample_seats`,
  `references`. Delivers `data/market/stats.md` with the survival per filter.
- **Env lane** (`agentenv_gridsim/market.py`, bundles `gridsim-market-sprint`, `gridsim-market-day`): `live.py`'s pattern
  around `market.Session`: the agent tools, hidden `clear_market` and `grid_notice`, raw arguments to `Session.call`,
  `advance` PUTting the clock to `watch_time_utc(k+1)` first, triggers from `market.triggers(market.schedule(...))` (D-1
  briefings, dam-close, awards, op-day watches; barrier at provoking_call, 60 s), `market-load/v1`, `end-floor/v1`,
  `clock/v1`, `data/get`/`data/reset`. RBAC: role default disables `clear_market` and `grid_notice`; `get_private_costs`
  filters on agent_name. The verifier reads `data/get`: `grade.reward` (or `compliant_reward` on the compliant board) is
  the reward row, the weight-0 rows above, a failed `audit` raises. A2A later: `deploy_agent gridsim-bidder` × 4 with
  role `bidder`, `peer_agents` from default-agent to the four seats only, and `Session(..., bidder_offers=...)` takes
  their offers in place of the scripted ones at 10:00.
- **Viewer lane**: reads only Episode JSON v5 (`stack`, `clear`, `awards`, `hours`, `contracts`, `rows`, `seat_results`,
  `references`) and re-verifies through core before showing. Scene per V5-P17.
- **Sol pilot**: `openai/gpt-6.1-sol`, effort high, scripted bidders on replay, no other model. Pre-register in
  `docs/prereg/v5-pilot.md` before the first episode: 30 `floor-sprint` eval tasks (both scorings) + 10 `floor-day`;
  baselines idle, max_withhold, price_taker, replay_A and the anchor; a per-episode $ cap as v3. Needs from C5: the two
  bundles, fixture days and `market.play` reference episodes.

**Order.** C5 phase 2 lands in three commits on `lane-v5core`: (1) `market_stack` (parser for both schemas, background,
simplify, disclosure, ε) with fixture days built from the sample, so the data lane starts; (2) `market` (offers, clear,
mitigation, projection, settlement, seats, `Session` for both tiers, `grade_offer`, `reward_fn`, prompts) with
`data/fixtures-market/`, so the env lane and path B start; (3) `market_refs` (anchor, the four BR DPs, iterated BR,
welfare LP) and the property tests. The viewer and the pilot start from (2)'s reference episodes.
