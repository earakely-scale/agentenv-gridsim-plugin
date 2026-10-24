# GridSim v4 forecast board

Tasks: 30 forecast windows (ercot-front-v4-eval; front 21, calm 9; sources ercot 30). Harness: gridsim-llm on gridsim-forecast, turns front 122, front-lite 72, 3 planning and 6 forecast calls a watch, 3 DAM submits a gate, 16384 output tokens a turn, effort high. Reward: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted hour in any submit_dam or commit_schedule scores 0; idle (0.2) is no DAM and the battery idle, the anchor (1.0) the rolling MILP on the desk's P50 guide (blind: on persistence). Mean R over windows with a 95% bootstrap CI.

Proxies and flags: forecasts: desk (modelled from NOAA HRRR as issued); load_official: EIA-930 DF; price_guide: modelled; pv_availability: proxy; reg_drift: seeded; rt_as: n/a; site: archetype.

Baselines (front, 20 windows): idle 0.200, naive 0.643, P_blind 0.720, P_roll 1.000, P_roll3 0.976, anchor 1.000; anchor hindsight capture 0.477.
Baselines (front-lite, 10 windows): idle 0.200, naive 0.351, P_blind 0.981, P_roll 1.000, P_roll3 0.965, anchor 1.000; anchor hindsight capture 0.450.

| Model | Tier | Windows | Runs/planned | Mean R (95% CI) | R front/calm | r_hind | Paired vs anchor | Beats anchor | r_roll3 | Forecast value | DAM missed | Forecast calls | Refusals | Planning calls | Turns | Finished | $/episode (max) | Spend |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | front | 20 | 20/20 | 0.909 (0.836 to 0.968) | 0.883/0.968 | 0.566 | -0.019 | 0.350 | 0.909 | – | 0.00 | 25.3 | 6.90 | 6.55 | 62.3 | 1.000 | $0.5698 ($0.9753) | $11.40 |
| openai/gpt-6.1-sol | front-lite | 10 | 10/10 | 0.883 (0.733 to 0.980) | 0.840/0.981 | 0.523 | -0.047 | 0.400 | 0.858 | – | 0.00 | 17.2 | 29.10 | 4.30 | 42.1 | 1.000 | $0.1934 ($0.2536) | $1.93 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | dam_missed | refused | ftp_charged | end_short | governed | no_replanning | no_forecasts | as_unused |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | front | 0 | 0 | 17 | 5 | 1 | 11 | 0 | 0 | 0 |
| openai/gpt-6.1-sol | front-lite | 0 | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |

## Unscored runs

None.

## Pilot (pre-registered in docs/prereg/v4-pilot.md, ab48a32)

GPT-6.1 Sol, effort high, 16,384 output tokens a turn, turns 122 (`front`) and 72 (`front-lite`), $2.62 episode cap
(4x the smoke median). Main column: 20 `ercot-front-v4-eval` windows at `front` (14 front, 6 calm); secondary: 10
more at `front-lite` (7 / 3), never pooled (`scripts/pilot_v4_tasks.py`, seed 4324); smoke: 3 more at `front`;
display: fern-0124 and heather-0114 at `front`. All 35 windows serve ERCOT's own load, wind and solar vintages. Computed
by `scripts/pilot_v4.py` from the 35 replay-verified Episode JSON v4 (`results/pilot-v4.json`). Paired vs anchor is
(P − P_roll)/(P_hind − P_idle); capture (P − P_idle)/(P_hind − P_idle); baselines are the stored references graded on the
anchor scale. Gates: "read before submit" is a forecast call at the gate watch before its first `submit_dam`;
"eligible" a later-day gate whose day Sol had already booked; "revised" its accepted DA battery position differing
from that booking by 10% of P in some hour. CIs are 95% bootstrap over windows (10,000 resamples), paired for
differences.

| Column | n | R (95% CI) | r_hind (anchor) | Paired vs anchor (95% CI) | Beats anchor | R at 1 | P_blind | R - P_blind (95% CI) | P_naive | R - P_naive | P_roll3 | R - P_roll3 | Capture (anchor) |
|---|---:|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| front (main) | 20 | 0.909 (0.836 to 0.968) | 0.566 (0.582) | -0.019 (-0.057 to 0.017) | 0.35 | 0.35 | 0.720 | 0.189 (0.096 to 0.286) | 0.643 | 0.265 | 0.976 | -0.067 | 0.458 (0.477) |
| front-lite | 10 | 0.883 (0.733 to 0.980) | 0.523 (0.560) | -0.047 (-0.098 to -0.005) | 0.40 | 0.50 | 0.981 | -0.098 (-0.248 to -0.007) | 0.351 | 0.531 | 0.965 | -0.082 | 0.404 (0.450) |

| Column | Label | n | R (95% CI) | r_hind | Paired vs anchor (95% CI) | P_blind | R - P_blind |
|---|---|---:|---|---:|---|---:|---:|
| front (main) | front | 14 | 0.883 (0.786 to 0.966) | 0.512 | -0.019 (-0.070 to 0.031) | 0.666 | 0.218 |
| front (main) | calm | 6 | 0.968 (0.930 to 0.995) | 0.692 | -0.020 (-0.053 to 0.009) | 0.848 | 0.120 |
| front-lite | front | 7 | 0.840 (0.646 to 0.972) | 0.470 | -0.061 (-0.127 to -0.005) | 0.973 | -0.133 |
| front-lite | calm | 3 | 0.981 (0.944 to 1.000) | 0.646 | -0.012 (-0.053 to 0.011) | 0.999 | -0.018 |

| Column | Forecast calls (refused) | get_forecast load/wind/solar/weather/price/alerts | Drift calls | Windows with ERCOT load/wind/solar call | Windows with drift call | Watches with a forecast call | Budget out (windows) |
|---|---|---|---:|---:|---:|---:|---:|
| front (main) | 25.3 (2.9) | 0.8/1.2/3.5/2.6/13.3/0.7 | 0.3 | 1.00 | 0.35 | 0.69 | 0.45 |
| front-lite | 17.2 (1.8) | 1.3/1.8/0.3/1.5/9.8/0.2 | 0.5 | 0.70 | 0.50 | 0.81 | 0.20 |

| Column | Gates | Missed (windows) | Submits/gate | Read before submit | Eligible gates | Revised (share) | Revised and read first | PV share < 1 | Gate nudges |
|---|---:|---|---:|---:|---:|---|---:|---:|---:|
| front (main) | 60 | 0 (0) | 1.47 | 0.95 | 12 | 12 (1.00) | 1.00 | 2 | 0 |
| front-lite | 20 | 0 (0) | 1.20 | 1.00 | 8 | 8 (1.00) | 1.00 | 20 | 0 |

| Column | Refusals | FTP MWh | Governor h | End short | AS $ (anchor) | Commits (anchor) | Re-plan rate | Finished | Turns | $/episode (median, max) | Output tok | Wall min |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| front (main) | 6.90 | 8.04 | 1.8 | 1 | 10,832 (15,600) | 5.7 (18.0) | 0.28 | 1.00 | 62.3 | $0.570 ($0.557, $0.975) | 9,538 | 7.3 |
| front-lite | 29.10 | 0.00 | 0.0 | 0 | 0 (0) | 3.8 (8.8) | 0.32 | 1.00 | 42.1 | $0.193 ($0.203, $0.254) | 4,802 | 4.2 |

- smoke: front-v4-2025-07-30-LZ_LCRA-pv100-r40-1h-poi100 (front, front): R 0.883, r_hind 0.663, paired -0.099, profit $207,590 vs anchor $217,475, P_blind R 0.914; 36 forecast calls (8 ERCOT load/wind/solar, 0 drift), 0 gates missed, 78 turns, $0.671, done
- smoke: front-v4-2025-04-08-LZ_SOUTH-pv150-b100x2h-poi150 (front, calm): R 0.977, r_hind 0.870, paired -0.024, profit $128,605 vs anchor $131,069, P_blind R 0.904; 23 forecast calls (5 ERCOT load/wind/solar, 2 drift), 0 gates missed, 56 turns, $0.586, done
- smoke: front-v4-2025-10-19-HB_PAN-pv200-r40-2h-poi200 (front, front): R 0.961, r_hind 0.550, paired -0.023, profit $97,887 vs anchor $100,319, P_blind R 0.596; 17 forecast calls (2 ERCOT load/wind/solar, 0 drift), 0 gates missed, 70 turns, $0.653, done
- display: front-v4-2026-01-24-HB_NORTH-pv150-b100x2h-poi150 (front, front): R 1.000, r_hind 0.741, paired 0.074, profit $1,151,139 vs anchor $1,039,573, P_blind R 0.674; 22 forecast calls (5 ERCOT load/wind/solar, 0 drift), 0 gates missed, 63 turns, $0.581, done
- display: front-v4-2024-01-14-HB_NORTH-pv150-b100x2h-poi150 (front, front): R 0.932, r_hind 0.762, paired -0.065, profit $1,591,392 vs anchor $1,722,653, P_blind R 0.892; 11 forecast calls (1 ERCOT load/wind/solar, 0 drift), 0 gates missed, 77 turns, $0.678, done

Unscored: none (35 of 35 scored at the first attempt; no retry, no cap stop). Spend: smoke $1.91, main $11.40,
front-lite $1.93, display $1.26; total $16.50 of $60.

Exploratory, not pre-registered (`anchor_policy` replayed in process on each main window, 19 of 20 reproducing the
stored anchor on macOS; mean per window, Sol − anchor): DA energy −$15,393 (below the anchor on 20 of 20), RT
deviations +$16,889, AS −$4,768 (17 of 20), deployment energy +$8,539, degradation −$1,070, FTP −$432; total −$1,771
(median −$476, below on 13 of 20). Sol's DA AS book per window (MW-h): RRS 2,960, RegDn 968, RegUp 280, Non-Spin
14, ECRS 0.

## Reading

- **H1 holds: forecasts are worth reading for Sol.** R is 0.909 (0.836 to 0.968) on the 20 `front` windows against
  P_blind's 0.720 on the same windows: +0.189 (0.096 to 0.286), above persistence on 15 of 20 (front windows 0.883 vs
  0.666, calm 0.968 vs 0.848), and +0.265 over P_naive (19 of 20). The registered expectation (0.6 to 0.9) is just
  exceeded.
- **Level with the rolling MILP, by a different book.** Paired vs anchor is −0.019 (−0.057 to 0.017); Sol beats the
  anchor on 7 windows, the 7 at R = 1; r_hind 0.566 against the anchor's 0.582; below P_roll3 by 0.067 (−0.143 to
  −0.003). It gets there with a smaller DA position, a third less AS (no ECRS at all, as in v3), far less RT churn and
  almost no FTP ($18 against $451 a window): 5.7 commits a window against the anchor's 18, the governor moving 1.8 of
  its hours against 14.9.
- **H2 undecided.** Sol's gap to the anchor is the same on front and calm windows (−0.019 and −0.020; difference
  +0.001, −0.057 to 0.061). R differs by label (0.883 vs 0.968), but so does every baseline's.
- **H3a not supported, on the drift count.** Every main window has an ERCOT load, wind or solar call, but mostly site
  solar (71 calls; wind 24, load 16), and only 7 of 20 windows ever call `get_forecast_drift` (0.3 a window). Sol reads
  the desk's price guide most: 13.3 of its 25.3 forecast calls a window.
- **H3b supported, narrowly.** All 12 eligible gates were revised, each after a forecast read at the gate, and Sol read
  a forecast before its first submit at 95% of gates. But only 12 of the 40 later-day gates were eligible: Sol mostly
  leaves the next day unbooked until its own gate, so it bids each day on the gate's vintage rather than revising a
  standing plan.
- **H4 holds.** 0 of 60 gates missed and no gate nudge needed. 1.47 submits a gate: the resubmits fix refused hours
  (`reserve_up` 44, `reserve_dn` 21, `soc_empty` 17, `soc_full` 12, `parse` 4 refused DAM rows).
- **Forecast-tool friction.** 47 calls in 26 of the 35 windows passed `issued_at: ""` and were refused as malformed,
  each using a forecast call; 22 main-column calls in 10 windows asked for a vintage issued after now, the UTC clock
  time read as CPT (16:00 at the 10:00 watch), and were refused with nothing served (audits pass). The budget ran out
  at some watch in 9 of 20 main windows.
- **Front-lite sits below persistence.** R 0.883 (0.733 to 0.980) against P_blind's 0.981: −0.098 (−0.248 to −0.007).
  The loss is one window: 2025-02-19 LZ_HOUSTON (the February 2025 cold snap) scored 0.285, because a later commit
  moved day 1's 125 MW DA discharge from 20:00 to 22:00, buying it back at RT $351, and day 2 carried no DA position
  in the $789 06:00 spike: $5,239 against the anchor's $49,353 and persistence's $81,415. Submits at 8 of 10
  `front-lite` windows sent AS fields the tier does not offer (288 refused hours, then an energy-only resubmit): the
  `front-lite` card and `submit_dam` description still speak of AS.
- **Display.** Fern: R 1.0, $1,151,139 against the anchor's $1,039,573 (+0.074 paired; P_blind 0.674): RegUp and RegDn
  on Jan 24, then RRS, ECRS and Non-Spin into the storm with a large DA discharge on Jan 26 (AS $428k, DA energy $867k,
  RT −$140k). Heather: R 0.932, $1,591,392 against $1,722,653 (P_blind 0.892), $1.29M of it RegUp and RegDn.
- **Play and cost.** All 35 finished with Sol's own `advance`: 62 turns a `front` window (max 83 of 122), 42 at
  `front-lite`; 3.06M input tokens (97% cached) and 9.5k output; $0.57 a `front` window (max $0.98), $0.19 a
  `front-lite` one.
- **Registered readings.** Front-lite as a scored tier: Sol's 0.883 is below 0.95, so not saturated by the rule, but
  P_blind's 0.981 leaves the tier no room to show forecast value: it stays a training and warm-up tier. Anchor scale at
  `front`: 7 of 20 at R = 1 (35%), so compressed for this model by V2-D1's rule; r_hind and paired vs anchor carry
  the signal above it. Front/calm label: uninformative as a stratifier of the gap at this size (H2 undecided); kept as
  an R breakdown. Forecast budget (V4-P14): binding (out at some watch in 45% of windows), though 2.9 of the 25.3 calls
  a window were refused misuse. Turn, watch and episode caps (V4-P10): not binding. DA PV share (V4-P5): not used (2
  of 60 gates below 1).
