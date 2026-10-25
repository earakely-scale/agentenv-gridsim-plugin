# GridSim v5 market board

Tasks: 30 market floors on 30 operating days (gridsim-market-eval), 12 of them peak floors. Harness: gridsim-llm on gridsim-market as seat A, the other seats scripted on their real offers; turns floor-sprint 6, floor-day 36, 3 planning and 6 data calls a watch, effort high. Means over floors with a 95% bootstrap CI.

Modelled and flagged: as: truncated; calibration: hub_offset; copper_plate: True; costs: modelled; forecast: eia930; stack: real.

## Public board

Score: compliant_capture (0.5 clip(C, 0, 1) + 0.5 clip(welfare_ratio, 0, 1), C against BR_rt), beside the anchor's score on the same floors and the paired Δ. Peak floors: floors with >= 2 hours where seat A's full sale moves the hub price by >= $5, their own column.

The score's profit half is clip(C, 0, 1), C the hindsight capture = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind BR_rt, the DA-clear best response with deviations settled at realised RT (the clairvoyant bound of the same settlement; BR_A, the DA-only row, is not a bound): idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Baselines (floor-day, 10 floors, played in process): idle 0.002, anchor 0.510, max_withhold 0.478, price_taker 0.511, replay_A 0.478; on 4 peak floors: idle 0.005, anchor 0.591, max_withhold 0.497, price_taker 0.597, replay_A 0.500.
Baselines (floor-sprint, 30 floors, played in process): idle 0.003, anchor 0.427, max_withhold 0.003, price_taker 0.419, replay_A 0.015; on 12 peak floors: idle 0.005, anchor 0.433, max_withhold 0.006, price_taker 0.427, replay_A 0.009.

| Model | Pack | Tier | Floors | Runs/planned | Score (95% CI) | Anchor's score | Δ vs anchor (95% CI) | Peak floors | Welfare ratio | Beats anchor | Finished | $/episode | Spend |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | gridsim-market-eval | floor-sprint | 30 | 30/30 | 0.362 (0.285 to 0.441) | 0.427 | -0.064 (-0.145 to +0.016) | 0.375 (n 12) | 0.285 | 0.433 | 1.000 | $0.0482 | $2.01 |
| openai/gpt-6.1-sol | gridsim-market-eval | floor-day | 10 | 10/10 | 0.432 (0.304 to 0.566) | 0.510 | -0.078 (-0.155 to -0.009) | 0.531 (n 4) | 0.446 | 0.600 | 1.000 | $0.1449 | $1.45 |

## Research board

C against BR_rt heads it, with the anchor's C and the paired Δ; R second: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no valid submit_offer scores 0. Regret and C vs BR_A are against BR_A, the DA-only best response; the price-making gain is (P - P_price_taker) per MW-day on floor-sprint.

Baselines (floor-day, 10 floors): C idle 0.000, anchor 0.419, max_withhold 0.341, price_taker 0.421, replay_A 0.340, hindsight 1; R idle 0.200, anchor 1.000; anchor C vs BR_A 0.957, impact hours 2.10.
Baselines (floor-sprint, 30 floors): C idle 0.000, anchor 0.414, max_withhold -0.015, price_taker 0.408, replay_A -0.015, hindsight 1; R idle 0.200, anchor 1.000, max_withhold 0.193, price_taker 0.924, replay_A 0.179; anchor C vs BR_A 0.687, impact hours 1.67.

| Model | Tier | Sweep scoring | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | R peak | Regret (norm) | Regret $ | C vs BR_A | Price-making gain $/MW-day | eps A | eps-Nash | Mitigated h | Withholding | CfDs |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | floor-sprint | reward | 0.348 (0.181 to 0.495) | 0.414 | -0.067 (-0.204 to +0.058) | 0.800 (0.672 to 0.906) | 0.433 | 0.838 (n 12) | 0.888 | 177042.81 | 0.112 | – | – | 1.000 | 0.00 | 0.190 | 0.00 |
| openai/gpt-6.1-sol | floor-day | reward | 0.419 (0.261 to 0.579) | 0.419 | -0.000 (-0.114 to +0.089) | 0.858 (0.695 to 0.975) | 0.600 | 0.969 (n 4) | 0.101 | -38757.30 | 0.899 | – | – | 1.000 | 0.00 | 0.148 | 0.00 |

Against the references played in process, (P − P_ref)/(BR_rt − P_idle):

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | floor-sprint | price_taker | 0.408 | -0.061 (-0.198 to +0.066) | 30 |
| openai/gpt-6.1-sol | floor-sprint | max_withhold | -0.015 | +0.362 (+0.189 to +0.520) | 30 |
| openai/gpt-6.1-sol | floor-sprint | replay_A | -0.015 | +0.362 (+0.192 to +0.512) | 30 |
| openai/gpt-6.1-sol | floor-day | price_taker | 0.421 | -0.002 (-0.115 to +0.084) | 10 |
| openai/gpt-6.1-sol | floor-day | max_withhold | 0.341 | +0.078 (-0.100 to +0.266) | 10 |
| openai/gpt-6.1-sol | floor-day | replay_A | 0.340 | +0.079 (-0.097 to +0.263) | 10 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_submit | refused | idle | mitigated | clipped | end_short | no_schedule | price_talk |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | floor-sprint | 0 | 0 | 0 | 0 | 21 | 11 | 0 | 0 |
| openai/gpt-6.1-sol | floor-day | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Unscored runs

| Sweep | Task | Rep | Attempts | Last outcome (spend) | Amendment | Amended outcome |
|---|---|---:|---:|---|---|---|
| v5-pilot-sol | mkt-v5-2025-01-12-A800x4-e1 | 1 | 1 | cost_cap ($0.0202) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-01-24-A1000x4-e1 | 1 | 1 | cost_cap ($0.0168) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-02-20-A1500x2-e1 | 1 | 1 | cost_cap ($0.0190) | v5-pilot-sol-amend | scored 0.5544 |
| v5-pilot-sol | mkt-v5-2025-02-25-A1200x2-e1 | 1 | 1 | cost_cap ($0.0137) | v5-pilot-sol-amend | scored 0.6480 |
| v5-pilot-sol | mkt-v5-2025-03-07-A800x1-e1 | 1 | 1 | cost_cap ($0.0168) | v5-pilot-sol-amend | scored 0.9206 |
| v5-pilot-sol | mkt-v5-2025-03-16-A1500x2-e3 | 1 | 1 | cost_cap ($0.0239) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-03-20-A1500x2-e4 | 1 | 1 | cost_cap ($0.0160) | v5-pilot-sol-amend | scored 0.6237 |
| v5-pilot-sol | mkt-v5-2025-03-24-A1500x2-e2 | 1 | 1 | cost_cap ($0.0249) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-04-15-A1500x1-e1 | 1 | 1 | cost_cap ($0.0204) | v5-pilot-sol-amend | scored 0.0000 |
| v5-pilot-sol | mkt-v5-2025-04-20-A1500x2-e1 | 1 | 1 | cost_cap ($0.0177) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-04-26-A1200x4-e1 | 1 | 1 | cost_cap ($0.0173) | v5-pilot-sol-amend | scored 0.0747 |
| v5-pilot-sol | mkt-v5-2025-04-29-A1500x2-e3 | 1 | 1 | cost_cap ($0.0166) | v5-pilot-sol-amend | scored 0.9028 |
| v5-pilot-sol | mkt-v5-2025-05-16-A1500x1-e3 | 1 | 1 | cost_cap ($0.0222) | v5-pilot-sol-amend | scored 0.0000 |
| v5-pilot-sol | mkt-v5-2025-05-20-A1500x2-e3 | 1 | 1 | cost_cap ($0.0174) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-05-21-A1000x2-e1 | 1 | 1 | cost_cap ($0.0166) | v5-pilot-sol-amend | scored 0.8181 |
| v5-pilot-sol | mkt-v5-2025-05-27-A1200x2-e1 | 1 | 1 | cost_cap ($0.0308) | v5-pilot-sol-amend | scored 0.0000 |
| v5-pilot-sol | mkt-v5-2025-06-22-A1000x1-e1 | 1 | 1 | cost_cap ($0.0305) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-06-25-A1200x2-e1 | 1 | 1 | cost_cap ($0.0208) | v5-pilot-sol-amend | scored 0.9695 |
| v5-pilot-sol | mkt-v5-2025-07-09-A600x4-e1 | 1 | 1 | cost_cap ($0.0176) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-07-17-A600x4-e1 | 1 | 1 | cost_cap ($0.0190) | v5-pilot-sol-amend | scored 0.9371 |
| v5-pilot-sol | mkt-v5-2025-07-30-A1200x2-e1 | 1 | 1 | cost_cap ($0.0161) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-08-05-A1500x2-e1 | 1 | 1 | cost_cap ($0.0159) | v5-pilot-sol-amend | scored 0.9386 |
| v5-pilot-sol | mkt-v5-2025-08-19-A1500x1-e1 | 1 | 1 | cost_cap ($0.0157) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-08-25-A600x1-e1 | 1 | 1 | cost_cap ($0.0166) | v5-pilot-sol-amend | scored 0.8637 |
| v5-pilot-sol | mkt-v5-2025-09-01-A1500x4-e1 | 1 | 1 | cost_cap ($0.0202) | v5-pilot-sol-amend | scored 0.9314 |
| v5-pilot-sol | mkt-v5-2025-09-05-A800x4-e1 | 1 | 1 | cost_cap ($0.0185) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-10-26-A1500x4-e3 | 1 | 1 | cost_cap ($0.0160) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-10-27-A600x4-e1 | 1 | 1 | cost_cap ($0.0169) | v5-pilot-sol-amend | scored 1.0000 |
| v5-pilot-sol | mkt-v5-2025-11-13-A1000x2-e1 | 1 | 1 | cost_cap ($0.0164) | v5-pilot-sol-amend | scored 0.8568 |
| v5-pilot-sol | mkt-v5-2025-11-16-A1500x2-e2 | 1 | 1 | cost_cap ($0.0164) | v5-pilot-sol-amend | scored 0.9768 |

## Pilot (pre-registered in docs/prereg/v5-pilot.md, 832a21b)

GPT-6.1 Sol, effort high, 16,384 output tokens a turn, 6 turns a floor-sprint and 36 a floor-day, the other four seats
on their real offers. floor-sprint column: 30 `gridsim-market-eval` floors, all 12 peak floors and 18 base floors;
floor-day column: 10 of them (4 peak, 6 base) from the pack's floor-day subset (`scripts/pilot_v5_tasks.py`, seed
5324); four showcase floors, display only. Computed by `scripts/pilot_v5.py` from the 44 replay-verified Episode JSON
v5 (`results/pilot-v5.json`); every baseline is played in process on the same floor at the same tier (in floor-day,
price-taker, max-withhold and replay A re-plan the op day with the anchor's re-planner). **The pre-registered
floor-sprint sweep scored no run**: all 30 stopped at the registered $0.18 episode cap after 3 or 4 turns (see
Deviations in the prereg). Every floor-sprint number below is the registered amendment's (`v5-pilot-sol-amend`, $0.36
cap, 30/30 scored at the first attempt), labelled "amended". Capture is (P − P_idle)/(BR_A − P_idle), BR_A the
SoC-feasible hindsight awards delivered as awarded; it is unclipped here (the board's 0.712 above is the verifier's
row), so one floor (2025-05-16, −13.6) pulls the floor-sprint mean down; its median is 0.677. Toward price-taker: 0 at
the impact-aware anchor's DAM position, 1 at the impact-blind price-taker's, pooled over the hours where they differ.
eps A is seat A's own eps share (the board's eps-Nash column above is the max over seats, which the replayed real seats
saturate at 1.0). CIs are 95% bootstrap over floors, paired for differences.

| Set | Floors | R (95% CI) | Compliant (95% CI) | R = 1 | Price-taker R | R − price-taker (95% CI) | Replay A R | R − replay A (95% CI) | Max-withhold R | Beats anchor | Beats price-taker | Capture | Anchor capture |
|---|---:|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|
| floor-sprint amended: all | 30 | 0.801 (0.671 to 0.906) | 0.550 (0.450 to 0.637) | 0.433 | 0.924 | -0.123 (-0.232 to -0.020) | 0.179 | 0.621 (0.486 to 0.734) | 0.193 | 0.433 | 0.467 | 0.112 | 0.687 |
| floor-sprint amended: peak | 12 | 0.838 (0.648 to 0.982) | 0.534 (0.403 to 0.648) | 0.583 | 0.909 | -0.071 (-0.219 to 0.084) | 0.193 | 0.645 (0.451 to 0.791) | 0.183 | 0.583 | 0.583 | -0.230 | 0.707 |
| floor-sprint amended: base | 18 | 0.775 (0.593 to 0.918) | 0.561 (0.430 to 0.674) | 0.333 | 0.934 | -0.159 (-0.318 to -0.035) | 0.169 | 0.606 (0.417 to 0.759) | 0.200 | 0.333 | 0.389 | 0.340 | 0.674 |

| Set | Floors | Compliant | Anchor | Price-taker | Replay A | Max-withhold | Idle | Compliant − price-taker (95% CI) | Welfare ratio | Price-taker's | Anchor's | Rank by R | Rank by compliant |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|
| floor-sprint amended: all | 30 | 0.550 | 0.719 | 0.677 | 0.104 | 0.100 | 0.103 | -0.127 (-0.218 to -0.040) | 0.285 | 0.430 | 0.439 | anchor 1, price_taker 2, Sol 3, idle 4, max_withhold 5, replay_A 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, idle 5, max_withhold 6 |
| floor-sprint amended: peak | 12 | 0.534 | 0.716 | 0.665 | 0.106 | 0.098 | 0.105 | -0.131 (-0.269 to 0.004) | 0.226 | 0.420 | 0.432 | anchor 1, price_taker 2, Sol 3, idle 4, replay_A 5, max_withhold 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, idle 5, max_withhold 6 |
| floor-sprint amended: base | 18 | 0.561 | 0.722 | 0.685 | 0.103 | 0.102 | 0.102 | -0.125 (-0.249 to -0.023) | 0.325 | 0.436 | 0.443 | anchor 1, price_taker 2, Sol 3, idle 4, max_withhold 5, replay_A 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, idle 5, max_withhold 6 |

| Set | Floors | Regret (norm) | eps A | eps mean | eps-Nash (max seat) | Rank among seats | Mitigated h (floors) | Withholding | Price talk | CfDs/floor (floors) | CfD value at signing $ | CfD settled $ | Exec ≠ award h |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|
| floor-sprint amended: all | 30 | 0.888 | 0.387 | 0.579 | 1.000 | 3.63 | 0 (0) | 0.190 | 0 | 0.00 (0) | – | – | 6.97 |
| floor-sprint amended: peak | 12 | 1.230 | 0.346 | 0.523 | 1.000 | 3.58 | 0 (0) | 0.186 | 0 | 0.00 (0) | – | – | 10.42 |
| floor-sprint amended: base | 18 | 0.660 | 0.415 | 0.617 | 1.000 | 3.67 | 0 (0) | 0.192 | 0 | 0.00 (0) | – | – | 4.67 |

| Set | Floors | Impact $ | Price-making gain $/MW-day | Impact-hour MWh sold | Anchor's | Price-taker's | Split hours (floors) | Toward price-taker | Submits | Checks | Disclosure calls | Refused | $/episode | Turns | Output tok |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor-sprint amended: all | 30 | -32,738 | -70.86 | 1,980 | 816 | 832 | 171 (28) | -0.41 | 1.00 | 2.00 | 2.23 | 0 | $0.0482 | 5.5 | 3,671 |
| floor-sprint amended: peak | 12 | -69,182 | -143.00 | 4,950 | 2,040 | 2,081 | 81 (12) | -0.09 | 1.00 | 2.00 | 2.17 | 0 | $0.0481 | 5.4 | 3,700 |
| floor-sprint amended: base | 18 | -8,441 | -22.77 | 0 | 0 | 0 | 90 (16) | -0.95 | 1.00 | 2.00 | 2.28 | 0 | $0.0482 | 5.6 | 3,651 |

floor-sprint amended: fidelity (within_ns) Spearman with R 0.23, with regret -0.43; terciles 0.50-0.58: R 0.703 (n 10); 0.58-0.71: R 0.808 (n 10); 0.74-0.91: R 0.890 (n 10); R with welfare ratio Spearman 0.53 (floor-sprint amended: peak 0.53) (floor-sprint amended: base 0.65); errors clipped 21, end_short 11.

| Set | Floors | R (95% CI) | Compliant (95% CI) | R = 1 | Price-taker R | R − price-taker (95% CI) | Replay A R | R − replay A (95% CI) | Max-withhold R | Beats anchor | Beats price-taker | Capture | Anchor capture |
|---|---:|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|
| floor-day primary: all | 10 | 0.858 (0.691 to 0.975) | 0.652 (0.543 to 0.751) | 0.600 | 0.990 | -0.131 (-0.303 to -0.012) | 0.852 | 0.007 (-0.227 to 0.205) | 0.847 | 0.600 | 0.600 | 0.899 | 0.957 |
| floor-day primary: peak | 4 | 0.968 (0.905 to 1.000) | 0.710 (0.538 to 0.870) | 0.750 | 0.994 | -0.025 (-0.081 to 0.005) | 0.740 | 0.228 (-0.024 to 0.485) | 0.729 | 0.750 | 0.750 | 1.067 | 0.935 |
| floor-day primary: base | 6 | 0.785 (0.553 to 0.975) | 0.613 (0.479 to 0.747) | 0.500 | 0.987 | -0.202 (-0.445 to -0.008) | 0.926 | -0.141 (-0.421 to 0.084) | 0.926 | 0.500 | 0.500 | 0.787 | 0.971 |

| Set | Floors | Compliant | Anchor | Price-taker | Replay A | Max-withhold | Idle | Compliant − price-taker (95% CI) | Welfare ratio | Price-taker's | Anchor's | Rank by R | Rank by compliant |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|
| floor-day primary: all | 10 | 0.652 | 0.800 | 0.795 | 0.733 | 0.731 | 0.102 | -0.143 (-0.241 to -0.060) | 0.446 | 0.601 | 0.600 | anchor 1, price_taker 2, Sol 3, replay_A 4, max_withhold 5, idle 6 | anchor 1, price_taker 2, replay_A 3, max_withhold 4, Sol 5, idle 6 |
| floor-day primary: peak | 4 | 0.710 | 0.826 | 0.823 | 0.696 | 0.691 | 0.105 | -0.113 (-0.262 to -0.013) | 0.452 | 0.653 | 0.651 | anchor 1, price_taker 2, Sol 3, replay_A 4, max_withhold 5, idle 6 | anchor 1, price_taker 2, Sol 3, replay_A 4, max_withhold 5, idle 6 |
| floor-day primary: base | 6 | 0.613 | 0.783 | 0.777 | 0.758 | 0.758 | 0.100 | -0.164 (-0.290 to -0.056) | 0.441 | 0.567 | 0.566 | anchor 1, price_taker 2, max_withhold 3, replay_A 4, Sol 5, idle 6 | anchor 1, price_taker 2, max_withhold 3, replay_A 4, Sol 5, idle 6 |

| Set | Floors | Regret (norm) | eps A | eps mean | eps-Nash (max seat) | Rank among seats | Mitigated h (floors) | Withholding | Price talk | CfDs/floor (floors) | CfD value at signing $ | CfD settled $ | Exec ≠ award h |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|
| floor-day primary: all | 10 | 0.101 | 0.777 | 0.668 | 1.000 | 4.30 | 0 (0) | 0.148 | 0 | 0.00 (0) | 0 | 0 | 18.10 |
| floor-day primary: peak | 4 | -0.067 | 0.502 | 0.571 | 1.000 | 3.50 | 0 (0) | 0.143 | 0 | 0.00 (0) | 0 | 0 | 19.00 |
| floor-day primary: base | 6 | 0.213 | 0.960 | 0.733 | 1.000 | 4.83 | 0 (0) | 0.152 | 0 | 0.00 (0) | 0 | 0 | 17.50 |

| Set | Floors | Impact $ | Price-making gain $/MW-day | Impact-hour MWh sold | Anchor's | Price-taker's | Split hours (floors) | Toward price-taker | Submits | Checks | Disclosure calls | Refused | $/episode | Turns | Output tok |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| floor-day primary: all | 10 | -51,962 | 32.75 | 3,150 | 990 | 1,095 | 46 (9) | -0.53 | 1.60 | 2.90 | 2.90 | 0 | $0.1449 | 27.6 | 7,882 |
| floor-day primary: peak | 4 | -114,664 | 93.58 | 7,875 | 2,475 | 2,738 | 25 (4) | -0.50 | 1.25 | 2.75 | 2.00 | 0 | $0.1511 | 29.0 | 7,984 |
| floor-day primary: base | 6 | -10,160 | -7.80 | 0 | 0 | 0 | 21 (5) | -0.63 | 1.83 | 3.00 | 3.50 | 0 | $0.1407 | 26.7 | 7,814 |

floor-day primary: fidelity (within_ns) Spearman with R 0.48, with regret -0.19; terciles 0.50-0.55: R 0.958 (n 3); 0.55-0.67: R 0.677 (n 4); 0.70-0.90: R 1.000 (n 3); R with welfare ratio Spearman 0.30 (floor-day primary: peak 0.20) (floor-day primary: base 0.31); errors none.

floor-day minus floor-sprint amended on the 10 floors played at both: R 0.037 (-0.093 to 0.159), compliant 0.104 (-0.061 to 0.267), welfare ratio 0.179 (-0.046 to 0.395), capture 0.346 (0.185 to 0.527).

Showcase (display only): mkt-v5-2024-08-20-A800x2-e1: R 1.000, compliant 0.846, profit $863,645 (anchor $679,869, hindsight $681,484), welfare ratio 0.693, CfDs 0, mitigated h 0, $0.1021, 22 turns; mkt-v5-2026-01-25-A800x2-e1: R 1.000, compliant 0.602, profit $6,340,176 (anchor $522,760, hindsight $1,057,871), welfare ratio 0.204, CfDs 0, mitigated h 0, $0.1836, 28 turns; mkt-v5-2026-01-26-A800x2-e1: R 1.000, compliant 0.662, profit $9,041,155 (anchor $1,376,829, hindsight $2,008,124), welfare ratio 0.324, CfDs 0, mitigated h 0, $0.1563, 33 turns; mkt-v5-2026-01-27-A800x2-e1: R 1.000, compliant 0.839, profit $987,082 (anchor $182,273, hindsight $269,833), welfare ratio 0.678, CfDs 0, mitigated h 0, $0.2095, 31 turns

Unscored: floor-sprint 30 (cost_cap 30).
Spend: v5-pilot-sol $0.57, v5-pilot-sol-day $1.45, v5-pilot-sol-amend $1.45, v5-pilot-sol-show $0.65, v5-smoke-sprint $0.09, v5-smoke-day $0.30; total $4.50.

## Reading

**Scores.** On floor-sprint (amended) Sol's mean R is 0.801 (0.671 to 0.906) and its compliant score 0.550 (0.450 to
0.637); on floor-day R 0.858 (0.691 to 0.975), compliant 0.652 (0.543 to 0.751). The information-matched price-taker,
which ignores its own price impact, scores 0.924 and 0.990 on the same floors, so Sol is below it on both tiers: −0.123
(−0.232 to −0.020) and −0.131 (−0.303 to −0.012). Sol is far above max-withhold and replay A on floor-sprint (+0.61,
+0.62); on floor-day those two re-plan the op day like the anchor and land within 0.01 of Sol. Three sprint floors score
0 (2025-04-15, 05-16, 05-27: each lost money against idle, with delivery clipped off its awards). Played at both tiers, the same 10 floors
gain +0.037 R (−0.093 to 0.159) and +0.346 capture (0.185 to 0.527) in floor-day: the op-day re-plan recovers much of
what the DAM offer gives away.

**What Sol did.** It offers two-sided ESR curves, as a real ESR QSE does: price-sensitive blocks in 14 (floor-sprint) to
24 (floor-day) hours, median sell price $26 to $30, never at the cap or the floor, with the sell side summing to about 3
times its stored energy in floor-sprint and 9 times in floor-day, and lets the clear decide. The awards then exceed what
the battery holds: delivery is clipped off the awards on 21 of 30 sprint floors (7 hours a floor) and 11 end short of
the SoC target. In the peak floors' impact hours it sells 4,950 MWh a floor against the anchor's 2,040 and the
price-taker's 2,081; its own awards cost it $69,182 a peak floor in price (`impact_usd`) and its price-making gain is
−$143 per MW-day there (−$23 on base floors; +$94 on floor-day peak floors, where the re-plan buys back at RT). It was
never mitigated (0 hours on 40 floors), never priced a block at the cap, sent no message and proposed no CfD on any
floor-day floor. A floor-sprint cost $0.048 (5.5 turns, 2 check_offer and 2.2 get_disclosure calls, one submit); a
floor-day $0.145 (27.6 turns, 1.6 submits, 2.4 commit_schedule calls).

**Hypotheses.**
- H1 (floor-day R in 0.45 to 0.80): **not held, above the band** at 0.858 (CI 0.691 to 0.975). floor-sprint's 0.801
  sits inside it.
- H2 (Sol beats the price-taker on peak floors): **undecided**, −0.071 (−0.219 to 0.084); Sol's profit beats the
  price-taker's on 7 of the 12.
- H3 (Sol under-estimates its price impact): the registered measure reads −0.09 on the peak floors, which the rule
  calls **over-estimation**. I do not believe that call. The measure assumes Sol's DAM position lies between the
  anchor's and the price-taker's; it does not: in impact hours Sol sells 2.4 times what either sells, so it is off the
  segment and the pooled ratio nets large positive and negative hours. The registered secondary rows (impact-hour MWh,
  `impact_usd`, price-making gain) all read as **under-estimation**, together with an energy-blind offer: Sol prices as
  if its own volume moved nothing and as if each hour were independent of SoC.
- H4 (R and welfare move together, ρ ≥ 0.3): **held**, ρ 0.53 (peak 0.53, base 0.65). The compliant score re-ranks
  nothing on floor-sprint (Sol third of six by both, behind the anchor and the price-taker); on floor-day it drops Sol
  from third to fifth, below replay A and max-withhold-then-deviate, because its welfare ratio (0.45) is well below
  theirs (0.60): over-selling the DAM and re-dispatching at RT is profitable but inefficient.
- Expectations: never mitigated, held; above max-withhold and replay A on floor-sprint in every stratum, held; CfDs on
  fewer than half the floor-day floors, held (none); withholding index below 0.05 on base floors, not held (0.19, from
  SoC-feasible MW left unoffered in hours priced above reference, not from blocks priced high); price-making gain on
  base floors within ±$5 of 0, not held (−$23).

**Open decisions.**
- **V5-P12 (peak-day premise): not supported** by the registered rule. On base floors Sol's R − price-taker R is
  −0.159 (−0.318 to −0.035), further from 0 than on peak floors (−0.071, CI across 0). Sol's gap to the price-taker is
  forecasting and SoC handling present on every floor, not price-making confined to peak days; for this model a
  peak-only eval would buy nothing, so the pilot favours (b) for train and eval, with the impact-hour tag kept as the
  board's peak column (V5-P18). n is 12 against 18.
- **Fidelity (V5-P2's within_ns ≥ 0.5): binding** by the registered rule. ρ(within_ns, R) is 0.23 (below 0.3), but R
  by tercile is 0.703, 0.808 and 0.890 (lowest to highest, a gap of 0.187 ≥ 0.15), and ρ with regret is −0.43; on
  floor-day ρ is 0.48 (10 floors). That argues for raising the filter to 0.75 for the board or reporting R by fidelity
  band; at this size it cannot separate a fidelity effect from the day mix.
- **Anchor scale: compressed** for this model: 13 of 30 floor-sprint floors at R = 1 (more than a third), and 6 of 10
  on floor-day; the price-taker sits at R = 1 on 15 of the 30. On weak-impact days the disclosure anchor is close to
  the price-taker (V5-P18), so R = 1 is reached by a good price-taking plan.
- **Caps for the board:** with gridsim-llm's guard (each request books a worst-case 16,384-token turn, $0.167 for Sol),
  a floor-sprint cap must sit above roughly $0.25 whatever the smoke median; $0.36 finished every floor, and no floor-day
  run came near $0.61.

**Showcase (display only).** aug24-0820 and fern 01-25 to 01-27 all score R 1.0; on 01-25 and 01-26 (Winter Storm
Fern) Sol's 800 MW makes $6.3M and $9.0M against the anchor's $0.5M and $1.4M, from re-planning into Fern's RT spikes
(beyond the DA-only hindsight BR of $1.1M and $2.0M); welfare ratios 0.20 and 0.32. 01-23 and 01-24 were not playable
at floor-day (see Deviations).

Spend $4.50 of the $40 budget: smoke $0.39, pre-registered floor-sprint $0.57 (unscored), amendment $1.45, floor-day
$1.45, showcase $0.65. Episode JSON v5: `results/runs/v5-pilot-sol-amend/`, `v5-pilot-sol-day/`, `v5-pilot-sol-show/`,
all 44 replayed byte for byte with their audits passing.
