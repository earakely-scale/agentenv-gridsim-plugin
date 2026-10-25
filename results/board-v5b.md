# GridSim v5 market board

Tasks: 30 market floors on 24 operating days (gridsim-market-eval), 12 of them peak floors. Harness: gridsim-llm on gridsim-market as seat A, the other seats scripted on their real offers; turns floor-sprint 6, floor-day 36, 3 planning and 6 data calls a watch, effort high. Means over floors with a 95% bootstrap CI.

Modelled and flagged: as: truncated; calibration: hub_offset; copper_plate: True; costs: modelled; forecast: eia930; stack: real.

## Public board

Score: compliant_capture (0.5 clip(C, 0, 1) + 0.5 clip(welfare_ratio, 0, 1), C against BR_rt), beside the anchor's score on the same floors and the paired Δ. Peak floors: floors with >= 2 hours where seat A's full sale moves the hub price by >= $5, their own column.

The score's profit half is clip(C, 0, 1), C the hindsight capture = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind BR_rt, the DA-clear best response with deviations settled at realised RT (the clairvoyant bound of the same settlement; BR_A, the DA-only row, is not a bound): idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Baselines (floor-day, 10 floors, played in process): idle 0.004, anchor 0.514, max_withhold 0.484, price_taker 0.510, replay_A 0.485; on 6 peak floors: idle 0.006, anchor 0.564, max_withhold 0.465, price_taker 0.560, replay_A 0.465.
Baselines (floor-sprint, 30 floors, played in process): idle 0.006, anchor 0.410, max_withhold 0.007, price_taker 0.391, replay_A 0.019; on 12 peak floors: idle 0.010, anchor 0.468, max_withhold 0.011, price_taker 0.434, replay_A 0.015.

| Model | Pack | Tier | Floors | Runs/planned | Score (95% CI) | Anchor's score | Δ vs anchor (95% CI) | Peak floors | Welfare ratio | Beats anchor | Finished | $/episode | Spend |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | gridsim-market-eval | floor-sprint | 30 | 30/30 | 0.308 (0.231 to 0.389) | 0.410 | -0.101 (-0.164 to -0.043) | 0.375 (n 12) | 0.174 | 0.400 | 1.000 | $0.0558 | $2.80 |
| openai/gpt-6.1-sol | gridsim-market-eval | floor-day | 10 | 10/10 | 0.553 (0.453 to 0.650) | 0.514 | +0.039 (-0.027 to +0.104) | 0.639 (n 6) | 0.539 | 0.700 | 1.000 | $0.1304 | $3.16 |

## Research board

C against BR_rt heads it, with the anchor's C and the paired Δ; R second: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no valid submit_offer scores 0. Regret and C vs BR_A are against BR_A, the DA-only best response; the price-making gain is (P - P_price_taker) per MW-day on floor-sprint.

Baselines (floor-day, 10 floors): C idle 0.000, anchor 0.446, max_withhold 0.379, price_taker 0.438, replay_A 0.380, hindsight 1; R idle 0.200, anchor 1.000; anchor C vs BR_A 0.995, impact hours 2.70.
Baselines (floor-sprint, 30 floors): C idle 0.000, anchor 0.419, max_withhold -0.015, price_taker 0.397, replay_A -0.020, hindsight 1; R idle 0.200, anchor 1.000, max_withhold 0.193, price_taker 0.930, replay_A 0.173; anchor C vs BR_A 0.683, impact hours 1.47.

| Model | Tier | Sweep scoring | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | R peak | Regret (norm) | Regret $ | C vs BR_A | Price-making gain $/MW-day | eps A | eps-Nash | Mitigated h | Withholding | CfDs |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | floor-sprint | reward | 0.296 (0.116 to 0.468) | 0.419 | -0.123 (-0.279 to +0.024) | 0.696 (0.545 to 0.834) | 0.400 | 0.887 (n 12) | 0.572 | 24589.21 | 0.428 | 26.13 | 0.450 | 1.000 | 0.00 | 0.169 | 0.00 |
| openai/gpt-6.1-sol | floor-day | reward | 0.566 (0.399 to 0.735) | 0.446 | +0.120 (-0.014 to +0.248) | 0.897 (0.775 to 1.000) | 0.700 | 0.940 (n 6) | -0.420 | -155858.52 | 1.420 | – | 0.721 | 1.000 | 0.00 | 0.052 | 0.00 |

Against the references played in process, (P − P_ref)/(BR_rt − P_idle):

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | floor-sprint | price_taker | 0.397 | -0.101 (-0.268 to +0.056) | 30 |
| openai/gpt-6.1-sol | floor-sprint | max_withhold | -0.015 | +0.311 (+0.124 to +0.491) | 30 |
| openai/gpt-6.1-sol | floor-sprint | replay_A | -0.020 | +0.316 (+0.137 to +0.483) | 30 |
| openai/gpt-6.1-sol | floor-day | price_taker | 0.438 | +0.129 (-0.005 to +0.260) | 10 |
| openai/gpt-6.1-sol | floor-day | max_withhold | 0.379 | +0.187 (-0.030 to +0.407) | 10 |
| openai/gpt-6.1-sol | floor-day | replay_A | 0.380 | +0.186 (-0.031 to +0.407) | 10 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_submit | refused | idle | mitigated | clipped | end_short | no_schedule | price_talk |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | floor-sprint | 0 | 0 | 0 | 0 | 24 | 3 | 0 | 0 |
| openai/gpt-6.1-sol | floor-day | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Unscored runs

None.

## Pilot (pre-registered in docs/prereg/v5-pilot-b.md, 34b3cc8)

GPT-6.1 Sol, effort high, 16,384 output tokens a turn, 6 turns a floor-sprint and 36 a floor-day, the other four seats
on their real offers, rules 5.1. floor-sprint column: 30 `gridsim-market-eval` floors, all 12 peak floors (both
portfolios of the 6 peak dates) and 18 base floors; floor-day column: 10 of them (all 6 peak and 4 base floor-day
floors), so the two tiers pair on those 10 (`scripts/pilot_v5b_tasks.py`, seed 5324); two showcase floors, display
only. Computed by `scripts/pilot_v5b.py` from the 42 replay-verified Episode JSON v5 (`results/pilot-v5b.json`); every
baseline is played in process on the same floor at the same tier (in floor-day, price-taker, max-withhold and replay A
re-plan the op day with the anchor's re-planner). Headline per the cross-version rule (`docs/REWARD-SCALES.md`): hindsight capture C = (P − P_idle)/(BR_rt − P_idle), unclipped, beside the anchor's C and Δ = C −
C_anchor (paired 95% CI); the compliant score on clip(C) is the public default, "as built" is the verifier's (R as its
profit half, the board above). Every run scored; 6 attempts lost to provider errors scored at their second attempt (see
the prereg's Deviations). CIs: 95% percentile bootstrap over floors, 10,000 resamples, paired for differences.

| Set | Floors | C (95% CI) | Anchor's C | C − anchor's C (95% CI) | C < 0 | Compliant on C (95% CI) | Compliant as built | R (95% CI) | R = 1 | Beats anchor | eps A (95% CI) |
|---|---:|---|---:|---|---:|---|---:|---|---:|---:|---|
| floor-sprint primary: all | 30 | 0.296 (0.112 to 0.466) | 0.419 | -0.123 (-0.278 to 0.021) | 7 | 0.308 (0.231 to 0.388) | 0.458 | 0.696 (0.543 to 0.834) | 0.400 | 0.400 | 0.449 (0.316 to 0.590) |
| floor-sprint primary: peak | 12 | 0.598 (0.424 to 0.755) | 0.494 | 0.104 (-0.011 to 0.240) | 1 | 0.375 (0.270 to 0.493) | 0.517 | 0.887 (0.708 to 0.996) | 0.667 | 0.667 | 0.262 (0.106 to 0.450) |
| floor-sprint primary: base | 18 | 0.095 (-0.138 to 0.319) | 0.370 | -0.274 (-0.484 to -0.073) | 6 | 0.264 (0.165 to 0.366) | 0.418 | 0.568 (0.365 to 0.759) | 0.222 | 0.222 | 0.575 (0.410 to 0.746) |

| Set | Floors | Idle C | Anchor C | Price-taker C | Max-withhold C | Replay A C | C − price-taker (95% CI) | C − replay A (95% CI) | C − max-withhold (95% CI) | Compliant on C: anchor / price-taker / replay A / max-withhold / idle | Beats price-taker | Beats replay A | Rank by C | Rank by compliant on C |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---|---|
| floor-sprint primary: all | 30 | 0.000 | 0.419 | 0.397 | -0.015 | -0.020 | -0.101 (-0.266 to 0.055) | 0.316 (0.135 to 0.483) | 0.311 (0.122 to 0.490) | 0.410 / 0.391 / 0.019 / 0.007 / 0.006 | 0.367 | 0.767 | anchor 1, price_taker 2, Sol 3, idle 4, max_withhold 5, replay_A 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, max_withhold 5, idle 6 |
| floor-sprint primary: peak | 12 | 0.000 | 0.494 | 0.455 | -0.037 | -0.004 | 0.143 (0.006 to 0.293) | 0.602 (0.428 to 0.758) | 0.635 (0.441 to 0.814) | 0.468 / 0.434 / 0.015 / 0.011 / 0.010 | 0.583 | 0.917 | Sol 1, anchor 2, price_taker 3, idle 4, replay_A 5, max_withhold 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, max_withhold 5, idle 6 |
| floor-sprint primary: base | 18 | 0.000 | 0.370 | 0.359 | 0.000 | -0.031 | -0.264 (-0.481 to -0.045) | 0.126 (-0.109 to 0.345) | 0.095 (-0.138 to 0.319) | 0.371 / 0.362 / 0.023 / 0.003 / 0.003 | 0.222 | 0.667 | anchor 1, price_taker 2, Sol 3, idle 4, max_withhold 5, replay_A 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, idle 5, max_withhold 6 |

| Set | Floors | Price-taker R | R − price-taker (95% CI) | Price-making gain $/MW-day (95% CI) | Impact $ | Impact-hour MWh sold | Anchor's | Price-taker's | Toward price-taker | Welfare ratio | Price-taker's | Anchor's |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor-sprint primary: all | 30 | 0.930 | -0.234 (-0.414 to -0.067) | 26.134 (-24.332 to 86.443) | -22,795 | 1,455 | 708 | 644 | -0.49 | 0.174 | 0.385 | 0.401 |
| floor-sprint primary: peak | 12 | 0.906 | -0.019 (-0.243 to 0.172) | 112.881 (10.041 to 239.056) | -48,904 | 3,637 | 1,769 | 1,610 | -0.41 | 0.138 | 0.413 | 0.442 |
| floor-sprint primary: base | 18 | 0.946 | -0.378 (-0.607 to -0.145) | -31.698 (-62.382 to 0.978) | -5,389 | 0 | 0 | 0 | -0.58 | 0.198 | 0.366 | 0.373 |

| Set | Floors | Offered sell / energy (median) | Offered buy / energy | Awarded sell / energy | Exec ≠ award h (floors) | get_forecast calls (refused) | Regret (norm) | Mitigated h (floors) | Withholding | CfDs/floor (floors) | Submits | Checks | Refused | $/episode | Turns | Output tok |
|---|---:|---|---:|---:|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| floor-sprint primary: all | 30 | 6.02 (3.50) | 4.98 | 3.60 | 9.20 (24) | 115 (0) | 0.572 | 0 (0) | 0.169 | 0.00 (0) | 1.00 | 2.00 | 0 | $0.0558 | 5.5 | 3,986 |
| floor-sprint primary: peak | 12 | 7.97 (7.75) | 3.06 | 6.06 | 10.67 (11) | 46 (0) | 0.001 | 0 (0) | 0.110 | 0.00 (0) | 1.00 | 2.00 | 0 | $0.0593 | 5.4 | 4,277 |
| floor-sprint primary: base | 18 | 4.72 (1.34) | 6.26 | 1.96 | 8.22 (13) | 69 (0) | 0.952 | 0 (0) | 0.208 | 0.00 (0) | 1.00 | 2.00 | 0 | $0.0535 | 5.6 | 3,791 |

floor-sprint primary: Spearman of C with the welfare ratio 0.19 (floor-sprint primary: peak 0.01) (floor-sprint primary: base 0.31); fidelity (within_ns) with C 0.07, terciles 0.71-0.75: C 0.124, R 0.467 (n 10); 0.75-0.79: C 0.359, R 0.749 (n 10); 0.83-0.91: C 0.406, R 0.871 (n 10); errors clipped 24, end_short 3.

floor-sprint primary against the rules-5.0 pilot (30 floors vs its 30, different floors, unpaired): C 0.296 vs 0.348, -0.051 (-0.291 to +0.192); R 0.696 vs 0.801, -0.105 (-0.295 to +0.083); compliant on C 0.308 vs 0.362, -0.054 (-0.165 to +0.059); as built 0.458 vs 0.550, -0.092 (-0.221 to +0.035); offered sell / energy 6.02 vs 5.58, +0.45 (-2.69 to +3.63); awarded sell / energy 3.60 vs 4.38, -0.78 (-3.04 to +1.36); exec ≠ award h 9.20 vs 6.97, +2.23 (-1.73 to +6.23); get_forecast refused 0.00 vs 1.00 of calls.

floor-sprint primary on the 7 floors both pilots played (5.1 − 5.0, paired): C -0.104 (-0.176 to -0.036), R -0.026 (-0.057 to -0.000), offered sell / energy 1.789 (-1.846 to 5.361), awarded sell / energy 0.889 (-1.729 to 3.382), exec ≠ award h 1.857 (-3.286 to 6.571).

| Set | Floors | C (95% CI) | Anchor's C | C − anchor's C (95% CI) | C < 0 | Compliant on C (95% CI) | Compliant as built | R (95% CI) | R = 1 | Beats anchor | eps A (95% CI) |
|---|---:|---|---:|---|---:|---|---:|---|---:|---:|---|
| floor-day primary: all | 10 | 0.566 (0.393 to 0.730) | 0.446 | 0.120 (-0.014 to 0.249) | 0 | 0.553 (0.450 to 0.649) | 0.718 | 0.897 (0.772 to 1.000) | 0.700 | 0.700 | 0.721 (0.521 to 0.900) |
| floor-day primary: peak | 6 | 0.705 (0.498 to 0.868) | 0.510 | 0.195 (0.017 to 0.344) | 0 | 0.639 (0.573 to 0.711) | 0.757 | 0.939 (0.818 to 1.000) | 0.833 | 0.833 | 0.603 (0.343 to 0.838) |
| floor-day primary: base | 4 | 0.358 (0.162 to 0.532) | 0.349 | 0.009 (-0.146 to 0.164) | 0 | 0.423 (0.319 to 0.605) | 0.660 | 0.832 (0.607 to 1.000) | 0.500 | 0.500 | 0.898 (0.695 to 1.000) |

| Set | Floors | Idle C | Anchor C | Price-taker C | Max-withhold C | Replay A C | C − price-taker (95% CI) | C − replay A (95% CI) | C − max-withhold (95% CI) | Compliant on C: anchor / price-taker / replay A / max-withhold / idle | Beats price-taker | Beats replay A | Rank by C | Rank by compliant on C |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---|---|
| floor-day primary: all | 10 | 0.000 | 0.446 | 0.438 | 0.379 | 0.380 | 0.129 (-0.005 to 0.260) | 0.186 (-0.031 to 0.407) | 0.187 (-0.031 to 0.408) | 0.514 / 0.510 / 0.485 / 0.484 / 0.004 | 0.700 | 0.500 | Sol 1, anchor 2, price_taker 3, replay_A 4, max_withhold 5, idle 6 | Sol 1, anchor 2, price_taker 3, replay_A 4, max_withhold 5, idle 6 |
| floor-day primary: peak | 6 | 0.000 | 0.510 | 0.503 | 0.308 | 0.310 | 0.202 (0.013 to 0.364) | 0.396 (0.122 to 0.604) | 0.397 (0.122 to 0.601) | 0.564 / 0.560 / 0.465 / 0.465 / 0.006 | 0.833 | 0.833 | Sol 1, anchor 2, price_taker 3, replay_A 4, max_withhold 5, idle 6 | Sol 1, anchor 2, price_taker 3, replay_A 4, max_withhold 5, idle 6 |
| floor-day primary: base | 4 | 0.000 | 0.349 | 0.339 | 0.486 | 0.486 | 0.019 (-0.115 to 0.158) | -0.128 (-0.228 to -0.028) | -0.128 (-0.228 to -0.028) | 0.438 / 0.434 / 0.514 / 0.514 / 0.000 | 0.500 | 0.000 | max_withhold 1, replay_A 2, Sol 3, anchor 4, price_taker 5, idle 6 | max_withhold 1, replay_A 2, anchor 3, price_taker 4, Sol 5, idle 6 |

| Set | Floors | Price-taker R | R − price-taker (95% CI) | Price-making gain $/MW-day (95% CI) | Impact $ | Impact-hour MWh sold | Anchor's | Price-taker's | Toward price-taker | Welfare ratio | Price-taker's | Anchor's |
|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor-day primary: all | 10 | 0.980 | -0.083 (-0.211 to 0.017) | 129.070 (19.183 to 243.939) | -55,090 | 3,870 | 1,233 | 1,132 | -0.43 | 0.539 | 0.582 | 0.582 |
| floor-day primary: peak | 6 | 0.979 | -0.040 (-0.181 to 0.062) | 205.871 (35.495 to 346.059) | -87,890 | 6,450 | 2,055 | 1,888 | -0.41 | 0.574 | 0.616 | 0.619 |
| floor-day primary: base | 4 | 0.981 | -0.148 (-0.384 to 0.000) | 13.868 (-29.309 to 71.454) | -5,892 | 0 | 0 | 0 | -0.49 | 0.487 | 0.530 | 0.527 |

| Set | Floors | Offered sell / energy (median) | Offered buy / energy | Awarded sell / energy | Exec ≠ award h (floors) | get_forecast calls (refused) | Regret (norm) | Mitigated h (floors) | Withholding | CfDs/floor (floors) | Submits | Checks | Refused | $/episode | Turns | Output tok |
|---|---:|---|---:|---:|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| floor-day primary: all | 10 | 9.75 (12.00) | 9.09 | 7.79 | 17.30 (10) | 61 (0) | -0.420 | 0 (0) | 0.052 | 0.00 (0) | 1.90 | 3.20 | 0 | $0.1304 | 25.2 | 7,021 |
| floor-day primary: peak | 6 | 14.00 (12.00) | 11.97 | 11.53 | 19.67 (6) | 37 (0) | -0.433 | 0 (0) | 0.021 | 0.00 (0) | 1.83 | 3.33 | 0 | $0.1344 | 24.8 | 7,198 |
| floor-day primary: base | 4 | 3.38 (3.88) | 4.76 | 2.19 | 13.75 (4) | 24 (0) | -0.399 | 0 (0) | 0.099 | 0.00 (0) | 2.00 | 3.00 | 0 | $0.1245 | 25.8 | 6,756 |

floor-day primary: Spearman of C with the welfare ratio -0.01 (floor-day primary: peak 0.09) (floor-day primary: base 0.40); fidelity (within_ns) with C 0.22, terciles 0.71-0.74: C 0.481, R 0.830 (n 3); 0.75-0.75: C 0.578, R 0.869 (n 4); 0.88-0.91: C 0.637, R 1.000 (n 3); errors none.

floor-day primary against the rules-5.0 pilot (10 floors vs its 10, different floors, unpaired): C 0.566 vs 0.419, +0.147 (-0.084 to +0.375); R 0.897 vs 0.858, +0.038 (-0.132 to +0.234); compliant on C 0.553 vs 0.432, +0.120 (-0.045 to +0.282); as built 0.718 vs 0.652, +0.066 (-0.050 to +0.186); offered sell / energy 9.75 vs 10.28, -0.53 (-6.95 to +5.70); awarded sell / energy 7.79 vs 6.59, +1.20 (-4.73 to +6.95); exec ≠ award h 17.30 vs 18.10, -0.80 (-4.80 to +3.00); get_forecast refused 0.00 vs 0.54 of calls.

floor-day primary on the 1 floors both pilots played (5.1 − 5.0, paired): C -0.011, R 0.000, offered sell / energy 0.000, awarded sell / energy 0.000, exec ≠ award h 0.000.

floor-day minus floor-sprint primary on the 10 floors played at both: C 0.173 (0.003 to 0.367), R 0.109 (-0.082 to 0.360), compliant on C 0.245 (0.145 to 0.337), welfare ratio 0.449 (0.310 to 0.577).

Showcase (display only): mkt-v5-2024-08-20-A800x2-e1: C 0.125 (anchor 0.097), compliant on C 0.410 (as built 0.847), R 1.000, profit $875,987 (anchor $679,869, hindsight BR_rt $6,981,602), welfare ratio 0.695, CfDs 0, mitigated h 0, $0.0863, 20 turns; mkt-v5-2026-01-26-A800x2-e1: C 0.962 (anchor 0.145), compliant on C 0.670 (as built 0.688), R 1.000, profit $9,120,202 (anchor $1,376,829, hindsight BR_rt $9,476,593), welfare ratio 0.377, CfDs 0, mitigated h 0, $0.1610, 31 turns

Unscored: none.
Spend: v5b-pilot-sol $2.80, v5b-pilot-sol-day $3.16, v5b-pilot-sol-show $0.82, v5b-smoke-sprint $0.10, v5b-smoke-day $0.28; total $7.16.

## Reading

**Headline (C against BR_rt).** floor-sprint, 30 floors: Sol's C is 0.296 (0.112 to 0.466) against the anchor's 0.419
on the same floors, Δ −0.123 (−0.278 to +0.021): level at this size, with the point estimate below. The column splits
by stratum: on the 12 peak floors C 0.598 against 0.494, Δ +0.104 (−0.011 to +0.240); on the 18 base floors C 0.095
against 0.370, Δ −0.274 (−0.484 to −0.073), and 7 floors (6 base) end below idle. floor-day, 10 floors: C 0.566
(0.393 to 0.730) against 0.446, Δ +0.120 (−0.014 to +0.249), level, point above; on its 6 peak floors Δ +0.195 (0.017
to 0.344). In dollars Sol is above the anchor on 12 of 30 sprint floors (mean +$33,879, median −$5,731) and on 7 of 10
floor-day floors (mean +$169,795, median +$40,484).

**Secondaries.** The public compliant score on clip(C): 0.308 (0.231 to 0.388) on floor-sprint, below the anchor's
0.410 and the price-taker's 0.391, because Sol's welfare ratio is 0.174 there (the anchor's 0.401; negative on 11 of 30
floors); 0.553 (0.450 to 0.649) on floor-day, first of the six policies (anchor 0.514, price-taker 0.510). As built
(R as its profit half) the same runs read 0.458 and 0.718. R: 0.696 (0.543 to 0.834) floor-sprint, 12 of 30 at R = 1;
0.897 (0.772 to 1.000) floor-day, 7 of 10. R − price-taker R: −0.234 (−0.414 to −0.067) and −0.083 (−0.211 to
+0.017); the price-making gain: +$26/MW-day (−24 to +86) on floor-sprint, +$113 (+10 to +239) on its peak floors,
−$32 (−62 to +1) on its base floors, +$129 (+19 to +244) on floor-day. eps_a 0.449 (0.316 to 0.590) floor-sprint,
0.721 (0.521 to 0.900) floor-day.

**What Sol did.** It used the served forecasts (176 `get_forecast` calls, none refused; rules 5.0 refused 197 of 276)
and still takes DAM positions far larger than its battery, then settles the part it cannot deliver at real time: in
effect a day-ahead/real-time spread trade written as an ESR offer. On the 12 peak floors its awarded sales average 6.06
times its energy (above it on 9); the DAM pays it $1.2M to $2.2M on the big days and the RT deviation takes back
$0.6M to $1.2M, which nets above the anchor where DA cleared above RT (03-24 pair, 05-20 A1200×1, 08-19 A1500×1:
C 0.56 to 0.95 against the anchor's 0.25 to 0.43). On base floors the same move on the buy side loses: on 02-06, 10-29,
04-13 and 05-19 it bought $0.16M to $0.38M of DAM energy it could not store and sold it back at a lower RT (C −0.19 to
−0.83). Delivery differs from the awards in 9.2 hours a sprint floor, on 24 of 30. It was never mitigated (0 hours on
42 floors), sent no message, proposed no CfD, and used 5.5 turns, 2 `check_offer` and 2.2 `get_disclosure` calls a
sprint ($0.056 in tokens) and 25.2 turns, 1.9 submits a floor-day ($0.130).

**Hypotheses.**
- H1 (C against the anchor's): **level** on both columns at this size (floor-sprint Δ −0.123, CI across 0; floor-day
  +0.120, CI across 0), as expected. By stratum the sign flips: above on peak floors (floor-day CI above 0), below on
  base floor-sprint floors (CI below 0).
- H2 (with forecasts served, over-offering shrinks): **not supported** (undecided by the registered rule, the point
  estimate the other way). Offered sell / energy 6.02 (median 3.50) against the rules-5.0 pilot's 5.58 (median 2.99),
  +0.45 (−2.69 to +3.63); awarded 3.60 against 4.38, −0.78 (−3.04 to +1.36); exec ≠ award 9.20 hours against 6.97,
  +2.23 (−1.73 to +6.23); paired on the 7 floors both played, offered +1.79 (−1.85 to +5.36). The forecasts arrive and
  the positions stay: the over-offering reads as a deliberate DA/RT position, not as missing information.
- H3 (Sol beats the price-taker on peak floors): **supported on C**, +0.143 (0.006 to 0.293), Sol's profit above the
  price-taker's on 7 of 12, price-making gain +$113/MW-day. On R the same comparison is undecided, −0.019 (−0.243 to
  +0.172), because R clips Sol's gains above the anchor. The gain is not withholding: in the peak floors' impact hours
  Sol sells 3,637 MWh a floor against the anchor's 1,769 and the price-taker's 1,610, its own sales cost it $48,904 a
  floor in price (`impact_usd`); toward-price-taker (−0.41) is not interpretable, as in rules 5.0, since Sol's
  positions lie off the anchor–price-taker segment. It wins on the DA/RT spread, not on price impact. On base floors it loses to the
  price-taker, −0.264 (−0.481 to −0.045).
- H4 (the op day adds capture): **supported**, floor-day minus floor-sprint C +0.173 (0.003 to 0.367) on the 10 paired
  floors; compliant on C +0.245 (0.145 to 0.337), welfare ratio +0.449 (0.310 to 0.577): re-dispatching the op day turns
  the infeasible DAM positions back into physical arbitrage.
- H5 (compliant vs profit): **no clear relation**, ρ(C, welfare ratio) 0.19 on floor-sprint (peak 0.01, base 0.31). By
  C Sol ranks third on floor-sprint (first on its peak floors) and first on floor-day; by the compliant score on C,
  third on floor-sprint in every stratum and first on floor-day.
- H6 (rules 5.0 → 5.1, labelled): **worse on the 7 shared floors**, C −0.104 (−0.176 to −0.036): Sol's 5.1 profit is
  below its 5.0 profit on 6 of the 7 (04-20 A1500×2 $115,510 against $248,176; 07-30 A1200×2 $978,681 against
  $1,267,328), while R moves −0.026 because both runs sit near R = 1. One run a floor in each pilot, so this is a
  run-to-run comparison, not a rules effect. Unpaired, different floors: floor-sprint C 0.296 against 0.348 (−0.051,
  −0.291 to +0.192), floor-day 0.566 against 0.419 (+0.147, −0.084 to +0.375).
- Expectations: never mitigated, held; on floor-sprint C above max-withhold and replay A in every stratum, held (base
  only on the point estimates, +0.095 and +0.126, CIs across 0); CfDs on fewer than half the floor-day floors, held
  (none); fewer than 10% of `get_forecast` calls refused, held (none); the anchor scale is compressed for Sol, 12 of 30
  sprint floors at R = 1.

**Also seen.** Fidelity matters on floor-sprint: by within_ns tercile C is 0.124, 0.359 and 0.406 (R 0.467, 0.749,
0.871), and 5 of the 7 floors below idle sit in the lowest tercile (0.71 to 0.75), though ρ(within_ns, C) is only 0.07.
On the 4 base floor-day floors max-withhold-then-deviate and replay A (C 0.486) out-capture Sol (0.358) and the anchor
(0.349): there the op-day re-planner, not the DAM offer, carries the score.

**Showcase (display only, floor-day, compliant).** aug24-0820: C 0.125 against the anchor's 0.097, R 1.0, $875,987.
fern-0126 (Winter Storm Fern): C 0.962 against the anchor's 0.145, $9,120,202 of a $9,476,593 hindsight, welfare ratio
0.377.

Spend: $7.16 booked of the $25 budget (smoke $0.38, floor-sprint $2.80, floor-day $3.16, showcase $0.82); $3.95 in
tokens, the difference being 19 provider-failed requests the guard books at a worst-case turn. Episode JSON v5:
`results/runs/v5b-pilot-sol/`, `v5b-pilot-sol-day/`, `v5b-pilot-sol-show/`, all 42 replayed byte for byte on the box
with their audits passing.
