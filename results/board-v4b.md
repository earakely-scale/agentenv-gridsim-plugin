# GridSim v4 forecast board

Tasks: 30 forecast windows (ercot-front-v4-eval; front 21, calm 9; sources ercot 30). Harness: gridsim-llm on gridsim-forecast, turns front 122, front-lite 72, 3 planning and 6 forecast calls a watch, 3 DAM submits a gate, 16384 output tokens a turn, effort high. R: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted hour in any submit_dam or commit_schedule scores 0; idle (0.2) is no DAM and the battery idle, the anchor (1.0) the rolling MILP on the desk's P50 guide (blind: on persistence).

Headline: hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind v3's hindsight MILP over the window (C replaces r_hind; Δ is the verifier's paired_vs_anchor): idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Proxies and flags: forecasts: desk (modelled from NOAA HRRR as issued); load_official: EIA-930 DF; price_guide: modelled; pv_availability: proxy; reg_drift: seeded; rt_as: n/a; site: archetype.

Baselines (front, 20 windows): C idle 0, naive 0.270, P_blind 0.375, P_roll 0.496, P_roll3 0.494, anchor 0.496, hindsight 1; R idle 0.200, naive 0.612, P_blind 0.762, P_roll 1.000, P_roll3 0.973, anchor 1.000.
Baselines (front-lite, 10 windows): C idle 0, naive 0.107, P_blind 0.390, P_roll 0.402, P_roll3 0.420, anchor 0.402, hindsight 1; R idle 0.200, naive 0.457, P_blind 0.930, P_roll 1.000, P_roll3 0.944, anchor 1.000.

| Model | Tier | Windows | Runs/planned | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | C front/calm | Forecast value | DAM missed | Forecast calls | Refusals | Planning calls | Turns | Finished | $/episode (max) | Spend |
|---|---|---:|---:|---|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | front | 20 | 20/20 | 0.463 (0.375 to 0.554) | 0.496 | -0.032 (-0.064 to -0.001) | 0.911 (0.859 to 0.956) | 0.350 | 0.350 | 0.394/0.624 | – | 0.00 | 26.8 | 6.90 | 7.75 | 59.5 | 1.000 | $0.6003 ($0.8671) | $17.04 |
| openai/gpt-6.1-sol | front-lite | 10 | 10/10 | 0.362 (0.262 to 0.463) | 0.402 | -0.040 (-0.091 to +0.008) | 0.873 (0.765 to 0.961) | 0.200 | 0.200 | 0.314/0.473 | – | 0.00 | 18.9 | 0.50 | 4.40 | 38.7 | 1.000 | $0.2011 ($0.2546) | $4.67 |

## Against the references

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | front | naive | 0.270 | +0.193 (+0.149 to +0.242) | 20 |
| openai/gpt-6.1-sol | front | blind | 0.375 | +0.088 (+0.040 to +0.141) | 20 |
| openai/gpt-6.1-sol | front | roll | 0.496 | -0.032 (-0.064 to -0.001) | 20 |
| openai/gpt-6.1-sol | front | roll3 | 0.494 | -0.031 (-0.058 to -0.003) | 20 |
| openai/gpt-6.1-sol | front-lite | naive | 0.107 | +0.255 (+0.164 to +0.346) | 10 |
| openai/gpt-6.1-sol | front-lite | blind | 0.390 | -0.029 (-0.099 to +0.039) | 10 |
| openai/gpt-6.1-sol | front-lite | roll | 0.402 | -0.040 (-0.091 to +0.008) | 10 |
| openai/gpt-6.1-sol | front-lite | roll3 | 0.420 | -0.058 (-0.147 to +0.005) | 10 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | dam_missed | refused | ftp_charged | end_short | governed | no_replanning | no_forecasts | as_unused |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | front | 0 | 0 | 20 | 5 | 2 | 12 | 0 | 0 | 0 |
| openai/gpt-6.1-sol | front-lite | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 |

## Unscored runs

None.

## Pilot (pre-registered in docs/prereg/v4-pilot-b.md, 11852c0)

GPT-6.1 Sol on rules 4.1, effort high, 16,384 output tokens a turn, turns 122 (`front`) and 72 (`front-lite`), $1.99
episode cap (4x the smoke median). Main column: 20 windows of the rebuilt `ercot-front-v4-eval` at `front` (14 front,
6 calm); secondary: 10 more at `front-lite` (7 / 3), never pooled; smoke: 3 more at `front`; display: fern-0124 and
heather-0114 at `front` (`scripts/pilot_v4_tasks.py`, seed 4324, redrawn on the 4.1 pack). All 35 windows serve ERCOT's
own load, wind and solar vintages. Computed by `scripts/pilot_v4b.py` from the 35 replay-verified Episode JSON v4
(`results/pilot-v4b.json`). Headline (docs/REWARD-SCALES.md): hindsight capture C = (P − P_idle)/(P_hind − P_idle),
unclipped, beside the anchor's C, and Δ = C − C_anchor (`paired_vs_anchor`); references on C as
(P − P_ref)/(P_hind − P_idle); R second. CIs are 95% bootstrap over windows (10,000 resamples), paired for differences.

| Column | n | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | C < 0 | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---:|---|---:|---:|
| front (main) | 20 | 0.463 (0.375 to 0.554) | 0.496 | -0.032 (-0.064 to -0.001) | 0 | 0.911 (0.859 to 0.956) | 0.35 | 0.35 |
| front-lite | 10 | 0.362 (0.262 to 0.463) | 0.402 | -0.040 (-0.091 to +0.008) | 0 | 0.873 (0.765 to 0.961) | 0.20 | 0.20 |

| Column | Reference | Its C | C − its C (95% CI) | Sol above it | Its R |
|---|---|---:|---|---:|---:|
| front (main) | P_naive | 0.270 | +0.193 (+0.149 to +0.242) | 1.00 | 0.612 |
| front (main) | P_blind | 0.375 | +0.088 (+0.040 to +0.141) | 0.75 | 0.762 |
| front (main) | P_roll3 | 0.494 | -0.031 (-0.058 to -0.003) | 0.30 | 0.973 |
| front-lite | P_naive | 0.107 | +0.255 (+0.164 to +0.346) | 1.00 | 0.457 |
| front-lite | P_blind | 0.390 | -0.029 (-0.099 to +0.039) | 0.40 | 0.930 |
| front-lite | P_roll3 | 0.420 | -0.058 (-0.147 to +0.005) | 0.50 | 0.944 |

| Column | Label | n | C | Anchor's C | Δ (95% CI) | P_blind C | C − P_blind C (95% CI) | R |
|---|---|---:|---:|---:|---|---:|---|---:|
| front (main) | front | 14 | 0.394 | 0.424 | -0.030 (-0.072 to +0.011) | 0.296 | +0.099 (+0.034 to +0.170) | 0.894 |
| front (main) | calm | 6 | 0.624 | 0.662 | -0.039 (-0.072 to -0.002) | 0.560 | +0.063 (+0.007 to +0.117) | 0.951 |
| front-lite | front | 7 | 0.314 | 0.388 | -0.074 (-0.121 to -0.029) | 0.371 | -0.057 (-0.141 to +0.032) | 0.826 |
| front-lite | calm | 3 | 0.473 | 0.435 | +0.038 (-0.031 to +0.088) | 0.436 | +0.037 (-0.030 to +0.076) | 0.984 |

| Column | issued_at blank or null (windows) | Malformed time refused (windows) | After now refused (windows) | Times sent with an offset | Zone name refused | Front-lite AS hours refused (windows) | Plan parse refusals |
|---|---|---|---|---:|---:|---|---:|
| front (main) | 522 (20) | 0 (0) | 0 (0) | 2 | 8 | 0 (0) | 17 |
| front-lite | 186 (10) | 0 (0) | 0 (0) | 0 | 0 | 0 (0) | 0 |

| Column | Drift calls a window | Windows with a drift call | Kept gates with a drift read before the submit | Eligible gates | Revised | Eligible with a drift read first | Revised with one |
|---|---:|---:|---:|---:|---:|---:|---:|
| front (main) | 0.60 | 8 of 20 | 0 of 60 | 10 | 10 | 0 | 0 |
| front-lite | 0.30 | 3 of 10 | 0 of 20 | 10 | 9 | 0 | 0 |

The board above and the tables below as the rules-4.0 pilot printed them (R on the anchor scale, `scripts/pilot_v4.py`):

| Column | n | R (95% CI) | r_hind (anchor) | Paired vs anchor (95% CI) | Beats anchor | R at 1 | P_blind | R - P_blind (95% CI) | P_naive | R - P_naive | P_roll3 | R - P_roll3 | Capture (anchor) |
|---|---:|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| front (main) | 20 | 0.911 (0.859 to 0.956) | 0.571 (0.597) | -0.032 (-0.064 to -0.001) | 0.35 | 0.35 | 0.762 | 0.148 (0.064 to 0.245) | 0.612 | 0.299 | 0.973 | -0.063 | 0.463 (0.496) |
| front-lite | 10 | 0.873 (0.765 to 0.961) | 0.489 (0.522) | -0.040 (-0.091 to 0.008) | 0.20 | 0.20 | 0.930 | -0.056 (-0.193 to 0.076) | 0.457 | 0.416 | 0.944 | -0.071 | 0.362 (0.402) |

| Column | Label | n | R (95% CI) | r_hind | Paired vs anchor (95% CI) | P_blind | R - P_blind |
|---|---|---:|---|---:|---|---:|---:|
| front (main) | front | 14 | 0.894 (0.824 to 0.955) | 0.516 | -0.030 (-0.072 to 0.011) | 0.714 | 0.179 |
| front (main) | calm | 6 | 0.951 (0.919 to 0.984) | 0.699 | -0.039 (-0.072 to -0.002) | 0.875 | 0.076 |
| front-lite | front | 7 | 0.826 (0.697 to 0.937) | 0.451 | -0.074 (-0.121 to -0.029) | 0.902 | -0.076 |
| front-lite | calm | 3 | 0.984 (0.952 to 1.000) | 0.578 | 0.038 (-0.031 to 0.088) | 0.994 | -0.010 |

| Column | Forecast calls (refused) | get_forecast load/wind/solar/weather/price/alerts | Drift calls | Windows with ERCOT load/wind/solar call | Windows with drift call | Watches with a forecast call | Budget out (windows) |
|---|---|---|---:|---:|---:|---:|---:|
| front (main) | 26.8 (0.4) | 1.2/1.6/4.9/3.5/13.6/1.1 | 0.6 | 1.00 | 0.40 | 0.75 | 0.15 |
| front-lite | 18.9 (0.0) | 2.1/2.0/0.4/2.9/10.5/0.7 | 0.3 | 0.90 | 0.30 | 0.80 | 0.20 |

| Column | Gates | Missed (windows) | Submits/gate | Read before submit | Eligible gates | Revised (share) | Revised and read first | PV share < 1 | Gate nudges |
|---|---:|---|---:|---:|---:|---|---:|---:|---:|
| front (main) | 60 | 0 (0) | 1.35 | 1.00 | 10 | 10 (1.00) | 1.00 | 0 | 0 |
| front-lite | 20 | 0 (0) | 1.10 | 1.00 | 10 | 9 (0.90) | 1.00 | 20 | 0 |

| Column | Refusals | FTP MWh | Governor h | End short | AS $ (anchor) | Commits (anchor) | Re-plan rate | Finished | Turns | $/episode (median, max) | Output tok | Wall min |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| front (main) | 6.90 | 3.73 | 3.8 | 2 | 14,201 (17,697) | 6.5 (17.6) | 0.34 | 1.00 | 59.5 | $0.600 ($0.586, $0.867) | 10,382 | 6.9 |
| front-lite | 0.50 | 0.00 | 0.0 | 0 | 0 (0) | 3.8 (8.1) | 0.27 | 1.00 | 38.7 | $0.201 ($0.198, $0.255) | 4,808 | 3.7 |

- smoke: front-v4-2025-01-17-LZ_WEST-pv150-b100x2h-poi180 (front, front): R 0.939, r_hind 0.477, paired -0.029, profit $71,541 vs anchor $74,955, P_blind R 0.733; 18 forecast calls (4 ERCOT load/wind/solar, 0 drift), 0 gates missed, 66 turns, $0.687, done; C 0.347 (anchor 0.375), Δ -0.029
- smoke: front-v4-2025-07-17-HB_NORTH-pv150-r40-1h-poi150 (front, calm): R 0.975, r_hind 0.843, paired -0.026, profit $133,986 vs anchor $134,909, P_blind R 0.933; 21 forecast calls (5 ERCOT load/wind/solar, 0 drift), 0 gates missed, 43 turns, $0.416, done; C 0.804 (anchor 0.830), Δ -0.026
- smoke: front-v4-2025-10-21-HB_WEST-pv150-b100x2h-poi150 (front, front): R 1.000, r_hind 0.351, paired 0.004, profit $107,076 vs anchor $106,580, P_blind R 0.537; 30 forecast calls (10 ERCOT load/wind/solar, 0 drift), 0 gates missed, 54 turns, $0.495, done; C 0.189 (anchor 0.185), Δ 0.004
- display: front-v4-2026-01-24-HB_NORTH-pv150-b100x2h-poi150 (front, front): R 0.816, r_hind 0.571, paired -0.139, profit $828,699 vs anchor $1,039,166, P_blind R 0.673; 24 forecast calls (5 ERCOT load/wind/solar, 0 drift), 0 gates missed, 63 turns, $0.855, done; C 0.464 (anchor 0.603), Δ -0.139
- display: front-v4-2024-01-14-HB_NORTH-pv150-b100x2h-poi150 (front, front): R 0.876, r_hind 0.719, paired -0.119, profit $1,482,556 vs anchor $1,722,653, P_blind R 0.892; 17 forecast calls (4 ERCOT load/wind/solar, 0 drift), 0 gates missed, 79 turns, $0.751, done; C 0.649 (anchor 0.768), Δ -0.119

Exploratory, not pre-registered as a test: against the rules-4.0 pilot (v4-preview befeefe, its committed Episode JSON on
its own pack's references). The two draws share 11 main and 4 front-lite windows; the comparison mixes the rules change,
the redraw and one run per window.

| Column | Rules | n | C | Anchor's C | Δ | R | R = 1 | Malformed time (windows) | After now (windows) | Front-lite AS hours (windows) | Windows with drift | Forecast calls |
|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|
| front (main) | 4.0 | 20 | 0.458 | 0.477 | -0.019 | 0.909 | 0.35 | 33 (18) | 22 (10) | 0 (0) | 7 | 25.3 |
| front (main) | 4.1 | 20 | 0.463 | 0.496 | -0.032 | 0.911 | 0.35 | 0 (0) | 0 (0) | 0 (0) | 8 | 26.8 |
| front-lite | 4.0 | 10 | 0.404 | 0.450 | -0.047 | 0.883 | 0.50 | 8 (6) | 10 (8) | 288 (8) | 5 | 17.2 |
| front-lite | 4.1 | 10 | 0.362 | 0.402 | -0.040 | 0.873 | 0.20 | 0 (0) | 0 (0) | 0 (0) | 3 | 18.9 |

- front (main), the 11 windows both pilots ran: C 4.1 − 4.0 -0.031 (-0.073 to +0.000), Δ 4.1 − 4.0 -0.031 (-0.074 to +0.001); the anchor's C moved +0.000 (solver 2, V4-P22)
- front-lite, the 4 windows both pilots ran: C 4.1 − 4.0 -0.016 (-0.057 to +0.040), Δ 4.1 − 4.0 -0.016 (-0.057 to +0.040); the anchor's C moved +0.000 (solver 2, V4-P22)

Exploratory (`anchor_policy` replayed in process from the stored calls on each main window, 20 of 20 reproducing
P_anchor on macOS; mean per window, Sol − anchor): DA energy −$9,816 (below the anchor on 16 of 20), RT deviations
+$8,669, AS −$3,495 (14 of 20), deployment energy +$2,870, degradation −$735, FTP −$457; total −$3,450 (median −$2,345,
below on 13 of 20). Sol's DA AS awards per window (MW-h): RRS 2,757, RegDn 1,509, RegUp 377, Non-Spin 45, ECRS 23
(4.0: 2,960, 968, 280, 14, 0).

Unscored: none (35 of 35 scored; 29 at the first attempt, 6 at the second after a provider outage: see the
pre-registration's Deviations). Spend: smoke $1.60, main $17.04 (of it $4.52 on the 4 failed attempts), front-lite
$4.67 ($2.49 on 2), display $1.61; total $24.92 of $30.

## Reading

- **Headline: Sol sits just below the anchor.** C 0.463 (0.375 to 0.554) on the 20 `front` windows against the
  anchor's 0.496 on the same windows: Δ −0.032 (−0.064 to −0.001), "below" by the registered reading, its CI ending at
  −0.001 (the rules-4.0 pilot read −0.019, level, on its own draw). R 0.911 (0.859 to 0.956), 7 of 20 at R = 1, the
  same 7 above the anchor. Sol is below P_roll3 too: −0.031 (−0.058 to −0.003), above it on 6 of 20.
- **H1 holds: forecasts are worth reading for Sol.** C − P_blind's C +0.088 (+0.040 to +0.141), above persistence on
  15 of 20 (front windows +0.099, calm +0.063), and +0.193 over P_naive (20 of 20).
- **H5 holds: the 4.0 friction is gone.** No forecast call was refused for a malformed time (4.0: 41 in 24 of the 30
  main and front-lite windows), none as issued after now (4.0: 22 in 10 main windows), and no `front-lite` hour as
  `not_offered` (4.0: 288 in 8 of 10). Sol now sends `issued_at: ""` on almost every forecast call (522 main, 186
  front-lite), each served as the latest vintage; it sent a time with an offset twice. Refused forecast calls fell
  from 2.9 to 0.4 a main window (the rest: 8 solar zone names), front-lite refusals from 29.1 to 0.5 a window, and the
  forecast budget ran out in 3 of 20 main windows (4.0: 9).
- **H3a not supported, on the drift count again.** Every main window has an ERCOT load, wind or solar call (solar 4.9,
  wind 1.6, load 1.2 a window), but only 8 of 20 call `get_forecast_drift` (0.6 a window; 4.0: 7 of 20). The desk's
  price guide is still most of what Sol reads: 13.6 of its 26.8 forecast calls a window.
- **H3b supported, narrowly, and not through the revisions.** All 10 eligible gates were revised, each after a forecast
  read at the gate; but only 10 of the 40 later-day gates were eligible (Sol leaves the next day unbooked until its
  gate, as in 4.0), and none of the 60 gates had a drift read before its submit. Sol re-bids each day on the gate's
  latest vintages; it does not read ERCOT's revision history before it does.
- **H4 holds.** 0 of 60 gates missed, no gate nudge, 1.35 submits a gate (4.0: 1.47): resubmits fix `reserve_up` (51),
  `reserve_dn` (16), SoC and `parse` (14: an AS field sent as one value or as "zero") rows.
- **H2 undecided.** Δ is −0.030 on front windows and −0.039 on calm ones (difference +0.009, −0.047 to +0.063).
- **Where the gap is (exploratory).** Against the anchor replayed in process, Sol gives up DA energy (−$9,816 a window,
  16 of 20) and wins part of it back in RT (+$8,669), sells less AS (−$3,495) and pays almost no FTP. It books more AS
  than in 4.0 (RegDn 1,509 against 968 MW-h a window, RegUp 377 against 280, some ECRS), still a fifth less than the
  anchor in dollars ($14,201 against $17,697), with 6.5 commits a window against the anchor's 17.6.
- **Front-lite: still below persistence on the headline.** C 0.362 (0.262 to 0.463) against the anchor's 0.402: Δ
  −0.040 (−0.091 to +0.008); against P_blind's C 0.390, −0.029 (−0.099 to +0.039), above it on 4 of 10; R 0.873. The
  gap is on front windows (Δ −0.074, −0.121 to −0.029; calm +0.038). The February 2025 cold snap (2025-02-19
  LZ_HOUSTON) is again the worst window: R 0.495, $18,196 against the anchor's $49,353 (4.0: $5,239).
- **Display.** Fern: R 0.816, C 0.464 against the anchor's 0.603 ($828,699 against $1,039,166; AS $256,673 against
  $393,477); the 4.0 run had beaten the anchor here ($1,151,139). Heather: R 0.876, C 0.649 against 0.768
  ($1,482,556 against $1,722,653).
- **Against 4.0 (exploratory).** Removing the friction did not lift Sol's capture: on the 11 main windows both pilots
  ran, C(4.1) − C(4.0) is −0.031 (−0.073 to +0.000), the anchor's C unchanged there; on the 4 shared front-lite windows
  −0.016 (−0.057 to +0.040). One run per window, so this reads as no gain, not as a loss. The time it freed went to
  more forecast calls (26.8 against 25.3 a main window) and more AS, not to the revision history.
- **Play and cost.** All 35 runs finished with Sol's own `advance`: 59.5 turns a `front` window (max 81 of 122), 38.7
  at `front-lite` (max 46 of 72); $0.60 a `front` window (median $0.59, max $0.87 of the $1.99 cap), $0.20 a
  `front-lite` one; 6.9 and 3.7 wall minutes.
- **Registered readings.** Front-lite as a scored tier: R 0.873 is below 0.95, so not saturated, and C − P_blind's C
  spans 0, so the tier shows no forecast value for this model: it stays a training and warm-up tier. Anchor scale at
  `front`: 7 of 20 at R = 1 (35%), compressed by V2-D1's rule; C carries the signal. Front/calm label: uninformative as
  a stratifier of Δ at this size (H2 undecided). Forecast budget (V4-P14): not binding (out in 15% of main windows;
  4.0: 45%, inflated by the friction). Turn, watch and episode caps (V4-P10): not binding. DA PV share (V4-P5): not
  used (0 of 60 main gates below 1).
