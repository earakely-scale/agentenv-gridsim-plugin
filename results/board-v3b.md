# GridSim v3 hybrid board

Tasks: 40 hybrid site-days (ercot-hybrid-v3-eval; AS strata low 14, mid 12, high 14). Harness: gridsim-llm on gridsim-hybrid, 52 turns, 3 planning calls a watch, 16384 output tokens a turn, effort high. Reward: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted commit scores 0; idle (0.2) is the solar-only plant, the anchor (1.0) the information-matched rolling MILP. Mean R over days with a 95% bootstrap CI.

Proxies and flags: deploy_frac: 1.0 assumed (stress case); poi: 1.2x; poi: default; poi: oversized 1.25; poi: oversized 1.40; pv_availability: proxy; pv_scope: system; pv_shape: ILR x fleet-AC cf (approximate); reg_drift: ercot; site: archetype.

Baselines (energy, 10 days): idle 0.200, sponge 0.392, AS-hog –, v2 energy-only 0.866, energy-only MILP –, anchor 1.000; anchor hindsight capture 0.426.
Baselines (reserves, 30 days): idle 0.200, sponge 0.256, AS-hog 0.399, v2 energy-only 0.765, energy-only MILP 0.813, anchor 1.000; anchor hindsight capture 0.505.

| Model | Tier | Days | Runs/planned | Mean R (95% CI) | R low/mid/high AS | Hindsight capture | Beats anchor | Beats sponge | AS share | Clip recovered % | FTP MWh | Refusals | Planning calls | Finished | $/episode | Spend |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 30 | 30/30 | 0.845 (0.759 to 0.920) | 0.942/0.862/0.730 | 0.451 | 0.300 | 0.967 | 0.447 | 70.4 | 11.273 | 1.07 | 5.77 | 1.000 | $0.1639 | $7.59 |
| openai/gpt-6.1-sol | energy | 10 | 10/10 | 0.990 (0.969 to 1.000) | 1.000/1.000/0.974 | 0.427 | 0.300 | 1.000 | 0.000 | 58.8 | 0.000 | 0.00 | 2.20 | 1.000 | $0.0461 | $0.46 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | refused | ftp_charged | end_short | governed | no_replanning | as_unused |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 0 | 13 | 11 | 5 | 26 | 4 | 1 |
| openai/gpt-6.1-sol | energy | 0 | 0 | 0 | 1 | 0 | 8 | 0 |

## Unscored runs

| Sweep | Task | Rep | Attempts | Last outcome (spend) | Amendment | Amended outcome |
|---|---|---:|---:|---|---|---|
| v3b-pilot-sol | hyb-v3-2025-02-17-LZ_HOUSTON-pv200-r40-1h-poi160 | 1 | 1 | cost_cap ($0.3631) | v3b-pilot-sol-amend | scored 1.0000 |

## Pilot under rules 3.1 (pre-registered in docs/prereg/v3-pilot-b.md, a677803)

GPT-6.1 Sol, effort high, 52 turns, 16,384 output tokens a turn, episode cap E = $0.53 (4 x the smoke median
$0.1317). Rules 3.1 (lane-x3 0c20373): ERCOT-measured regulation drift, C3-D18, oversized-PV sites, keep fields, packs
rebuilt. Reserves column: 30 `ercot-hybrid-v3-eval` days, all 13 deployment days plus 17 drawn by AS stratum (10 per
stratum); energy column: 10 days on sites with PV/POI >= 1.25 (5 at 1.25, 5 at 1.4); display: aug10-2023 and
mar29-2024 at the reserves tier (`scripts/pilot_v3b_tasks.py`, seed 4325). Computed by `scripts/pilot_v3b.py` from the
45 replay-verified Episode JSON v3 (`results/pilot-v3b.json`). Headline per `docs/REWARD-SCALES.md`: hindsight capture
C = (P − P_idle)/(P_hind − P_idle), the anchor's C and Δ = C − C_anchor with its paired CI; R second; a baseline
compared as (P − P_ref)/(P_hind − P_idle). CIs: 95% percentile bootstrap over days, 10,000 resamples. Primary: the
first sweeps (29 scored reserves days; one run stopped at its cap); amended: with that day's amendment run.
L_reg = (Sol's − the anchor's RegDn drift energy bought at RT)/(P_hind − P_idle), the anchor played in process.

| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---|---:|---:|
| reserves primary: all | 29 | 0.440 (0.354 to 0.526) | 0.498 | -0.057 (-0.095 to -0.022) | 0.839 (0.749 to 0.915) | 0.28 | 0.28 |
| reserves primary: deployment days | 13 | 0.266 (0.171 to 0.364) | 0.375 | -0.109 (-0.162 to -0.060) | 0.708 (0.550 to 0.850) | 0.15 | 0.15 |
| reserves primary: other days | 16 | 0.581 (0.494 to 0.666) | 0.597 | -0.016 (-0.057 to +0.025) | 0.947 (0.901 to 0.982) | 0.38 | 0.38 |
| reserves primary: low AS | 9 | 0.554 (0.426 to 0.660) | 0.575 | -0.020 (-0.057 to +0.015) | 0.936 (0.867 to 0.987) | 0.44 | 0.44 |
| reserves primary: mid AS | 10 | 0.387 (0.310 to 0.467) | 0.468 | -0.080 (-0.127 to -0.040) | 0.862 (0.779 to 0.929) | 0.00 | 0.00 |
| reserves primary: high AS | 10 | 0.390 (0.199 to 0.590) | 0.458 | -0.068 (-0.156 to +0.017) | 0.730 (0.516 to 0.916) | 0.40 | 0.40 |

| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |
|---|---|---:|---:|---|---:|
| reserves primary: all | AS-hog | 0.140 | 0.404 | +0.300 (+0.230 to +0.372) | 0.97 |
| reserves primary: all | solar sponge | 0.032 | 0.250 | +0.408 (+0.322 to +0.496) | 0.97 |
| reserves primary: all | v2 energy-only | 0.363 | 0.762 | +0.077 (+0.035 to +0.122) | 0.79 |
| reserves primary: all | energy-only MILP | 0.396 | 0.811 | +0.044 (+0.003 to +0.089) | 0.76 |
| reserves primary: deployment days | AS-hog | 0.054 | 0.305 | +0.212 (+0.122 to +0.310) | 0.92 |
| reserves primary: deployment days | solar sponge | 0.020 | 0.235 | +0.247 (+0.160 to +0.335) | 0.92 |
| reserves primary: deployment days | v2 energy-only | 0.250 | 0.705 | +0.016 (-0.031 to +0.063) | 0.62 |
| reserves primary: deployment days | energy-only MILP | 0.280 | 0.758 | -0.014 (-0.064 to +0.032) | 0.62 |
| reserves primary: other days | AS-hog | 0.209 | 0.485 | +0.372 (+0.283 to +0.461) | 1.00 |
| reserves primary: other days | solar sponge | 0.042 | 0.261 | +0.540 (+0.436 to +0.642) | 1.00 |
| reserves primary: other days | v2 energy-only | 0.455 | 0.809 | +0.127 (+0.073 to +0.188) | 0.94 |
| reserves primary: other days | energy-only MILP | 0.490 | 0.854 | +0.091 (+0.042 to +0.151) | 0.88 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| reserves primary: all | 29 | 0.456 | 5,751 | 6,630 | 0.934 | 2.6 / 616.8 / 1131.2 / 10.2 / 14.1 | 323.1 / 596.6 / 796.4 / 63.6 / 62.7 | 11.66 | 46.37 | 11 | 16 (1 / 7 / 11 / 1 / 1) | 4.28 | 5 |
| reserves primary: deployment days | 13 | 0.512 | 7,242 | 8,848 | 0.880 | 5.7 / 689.0 / 1103.8 / 9.4 / 29.3 | 332.5 / 650.9 / 850.8 / 71.4 / 79.8 | 20.27 | 71.88 | 5 | 6 (0 / 4 / 2 / 1 / 1) | 3.85 | 1 |
| reserves primary: other days | 16 | 0.411 | 4,540 | 4,828 | 1.012 | 0.0 / 558.1 / 1153.4 / 10.9 / 1.8 | 315.5 / 552.4 / 752.2 / 57.3 / 48.8 | 4.67 | 25.64 | 6 | 10 (1 / 3 / 9 / 0 / 0) | 4.62 | 4 |
| reserves primary: low AS | 9 | 0.352 | 2,178 | 2,075 | 1.042 | 4.9 / 617.4 / 1043.9 / 1.3 / 0.0 | 212.8 / 536.9 / 638.0 / 63.7 / 55.9 | 5.46 | 36.80 | 3 | 4 (0 / 1 / 3 / 0 / 0) | 4.89 | 2 |
| reserves primary: mid AS | 10 | 0.462 | 3,998 | 4,744 | 0.912 | 0.0 / 480.9 / 967.6 / 17.5 / 20.1 | 359.9 / 522.3 / 723.1 / 46.8 / 38.9 | 4.88 | 19.71 | 4 | 5 (1 / 2 / 4 / 0 / 0) | 3.00 | 0 |
| reserves primary: high AS | 10 | 0.543 | 10,719 | 12,616 | 0.919 | 3.0 / 752.1 / 1373.3 / 11.0 / 20.8 | 385.5 / 724.6 / 1012.2 / 80.3 / 92.6 | 24.02 | 81.65 | 4 | 7 (0 / 4 / 4 / 1 / 1) | 5.00 | 3 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| reserves primary: all | 29 | 0.395 | 0.897 | 0.349 | 1.000 | 14 on 11 days | reserve_up 13, reserve_dn 11, soc_full 3, parse 2, cycle_cap 1, soc_empty 1, headroom_dn 1 | 0 | 334,256 | 8,141 | 307,806 | $0.1651 | 17.6 |
| reserves primary: deployment days | 13 | 0.453 | 1.000 | 0.375 | 1.000 | 6 on 5 days | reserve_dn 4, reserve_up 4, soc_full 2, soc_empty 1, headroom_dn 1 | 0 | 421,518 | 9,054 | 391,350 | $0.1900 | 20.4 |
| reserves primary: other days | 16 | 0.338 | 0.812 | 0.323 | 1.000 | 8 on 6 days | reserve_up 9, reserve_dn 7, parse 2, cycle_cap 1, soc_full 1 | 0 | 263,356 | 7,399 | 239,927 | $0.1448 | 15.4 |
| reserves primary: low AS | 9 | 0.289 | 0.778 | 0.342 | 1.000 | 2 on 2 days | reserve_dn 4, reserve_up 2 | 0 | 293,140 | 8,184 | 267,591 | $0.1597 | 16.3 |
| reserves primary: mid AS | 10 | 0.455 | 1.000 | 0.364 | 1.000 | 4 on 3 days | reserve_up 5, parse 2, reserve_dn 2, soc_full 1 | 0 | 325,231 | 7,734 | 299,551 | $0.1587 | 17.2 |
| reserves primary: high AS | 10 | 0.426 | 0.900 | 0.340 | 1.000 | 8 on 6 days | reserve_up 6, reserve_dn 5, soc_full 2, cycle_cap 1, soc_empty 1, headroom_dn 1 | 0 | 380,286 | 8,509 | 352,256 | $0.1764 | 19.2 |

| Set | Days | L_reg: (Sol − anchor RegDn drift $)/(P_hind − P_idle) (95% CI) | RegDn drift bought $/day Sol / anchor | Sol − anchor $/day (median) | Days Sol pays more | RegDn drift MWh/day Sol / anchor | RegDn MW-h in the 6 top-DA hours Sol / anchor | RegDn MW-h/day Sol / anchor | RegUp MW-h/day Sol / anchor |
|---|---:|---|---|---|---:|---|---|---|---|
| reserves primary: all | 29 | -0.005 (-0.064 to +0.049) | 4,294 / 4,415 | -121 (-99) | 14 of 29 | 139.2 / 146.3 | 133 / 111 | 617 / 597 | 3 / 323 |
| reserves primary: deployment days | 13 | +0.012 (-0.060 to +0.077) | 6,401 / 6,329 | +72 (+688) | 9 of 13 | 168.8 / 167.6 | 120 / 149 | 689 / 651 | 6 / 332 |
| reserves primary: other days | 16 | -0.019 (-0.109 to +0.063) | 2,582 / 2,860 | -278 (-567) | 5 of 16 | 115.2 / 129.0 | 144 / 80 | 558 / 552 | 0 / 315 |
| reserves primary: low AS | 9 | +0.023 (-0.057 to +0.110) | 1,976 / 1,790 | +185 (-166) | 4 of 9 | 138.0 / 121.1 | 173 / 92 | 617 / 537 | 5 / 213 |
| reserves primary: mid AS | 10 | +0.014 (-0.058 to +0.093) | 2,833 / 2,808 | +26 (+30) | 5 of 10 | 91.9 / 105.2 | 99 / 104 | 481 / 522 | 0 / 360 |
| reserves primary: high AS | 10 | -0.050 (-0.177 to +0.058) | 7,840 / 8,385 | -545 (+241) | 5 of 10 | 187.7 / 210.1 | 132 / 134 | 752 / 725 | 3 / 385 |

| Day | Deployed (hours) | Award MW-h in those hours Sol / anchor | FTP MWh charged in it Sol / anchor | Deployment watches, Sol committed at | C | Anchor's C | Δ | R |
|---|---|---|---|---|---:|---:|---:|---:|
| `hyb-v3-2025-03-02-LZ_CPS-pv150-b100x2h-poi150` | nspin 17-22 | nspin 0 / 33 | nspin 0.00 / 0.00 | [4] / [4] | 0.137 | 0.223 | -0.086 | 0.690 |
| `hyb-v3-2025-03-05-HB_HOUSTON-pv150-b100x2h-poi180` | nspin 17-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [6] / [6] | 0.468 | 0.465 | +0.003 | 1.000 |
| `hyb-v3-2025-03-05-LZ_NORTH-pv100-r80-2h-poi80` | nspin 17-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [6] / [6] | 0.524 | 0.573 | -0.049 | 0.931 |
| `hyb-v3-2025-03-10-LZ_CPS-pv100-r40-1h-poi120` | nspin 18-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [] | 0.210 | 0.423 | -0.213 | 0.597 |
| `hyb-v3-2025-03-10-LZ_NORTH-pv150-b100x2h-poi150` | nspin 18-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [5] | 0.366 | 0.451 | -0.085 | 0.850 |
| `hyb-v3-2025-04-07-HB_SOUTH-pv300-r80-1h-poi240` | ecrs 6-7, nspin 6-7 | ecrs 0 / 0, nspin 0 / 3 | ecrs 0.00 / 0.00, nspin 0.00 / 0.00 | [3] / [] | -0.010 | 0.111 | -0.121 | 0.126 |
| `hyb-v3-2025-05-16-LZ_WEST-pv100-r67-1h-poi120` | ecrs 19-20, nspin 19-21 | ecrs 0 / 0, nspin 0 / 0 | ecrs 0.00 / 0.00, nspin 0.25 / 0.00 | [5] / [5] | 0.062 | 0.193 | -0.131 | 0.458 |
| `hyb-v3-2025-05-17-HB_WEST-pv150-b100x2h-poi180` | nspin 19-20 | nspin 0 / 5 | nspin 0.00 / 0.00 | [5] / [5] | 0.014 | 0.308 | -0.294 | 0.236 |
| `hyb-v3-2025-05-17-LZ_WEST-pv200-r40-2h-poi200` | nspin 19-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [] | 0.256 | 0.314 | -0.058 | 0.853 |
| `hyb-v3-2025-09-04-HB_PAN-pv100-r67-2h-poi100` | nspin 18-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [] | 0.547 | 0.594 | -0.047 | 0.937 |
| `hyb-v3-2025-10-21-HB_HOUSTON-pv200-r40-1h-poi240` | nspin 17-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [4] / [4] | 0.304 | 0.353 | -0.050 | 0.888 |
| `hyb-v3-2025-10-21-LZ_SOUTH-pv300-r80-2h-poi300` | nspin 17-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [4] / [] | 0.250 | 0.247 | +0.002 | 1.000 |
| `hyb-v3-2025-11-07-LZ_AEN-pv150-r67-1h-poi150` | nspin 16-18 | nspin 0 / 0 | nspin 0.00 / 0.00 | [4] / [] | 0.336 | 0.622 | -0.286 | 0.632 |

Δ on deployment days -0.109 against -0.016 on the others: gap -0.093 (-0.161 to -0.028, unpaired); FTP charged in the deployed products 0.25 MWh (anchor 0.00); Sol committed at 7 of 13 deployment watches.

Format: 87 planning calls kept an AS field by "keep" or null, 1 of them refused as parse; 2 commits refused as parse in all; 1 days without an accepted watch-0 commit.

reserves primary: check_schedule issues by rule: reserve_up 169, reserve_dn 42, soc_empty 23, soc_full 10, parse 5, power 5, headroom_dn 3, cycle_cap 2, meter_dn 1; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 247.75 / 81.11 / 9.09 / 0.25, excused 0.00 / 1038.69 / 302.50 / 0.00 / 3.61; error taxonomy governed 25, refused 13, ftp_charged 11, end_short 5, no_replanning 3, as_unused 1.

Amended (2025-02-17 LZ_HOUSTON from v3b-pilot-sol-amend):

| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---|---:|---:|
| reserves amended: all | 30 | 0.451 (0.365 to 0.534) | 0.505 | -0.054 (-0.092 to -0.019) | 0.845 (0.757 to 0.918) | 0.30 | 0.30 |
| reserves amended: deployment days | 13 | 0.266 (0.171 to 0.364) | 0.375 | -0.109 (-0.162 to -0.060) | 0.708 (0.550 to 0.850) | 0.15 | 0.15 |
| reserves amended: other days | 17 | 0.592 (0.509 to 0.677) | 0.604 | -0.012 (-0.053 to +0.027) | 0.950 (0.906 to 0.983) | 0.41 | 0.41 |

| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |
|---|---|---:|---:|---|---:|
| reserves amended: all | AS-hog | 0.136 | 0.398 | +0.315 (+0.242 to +0.392) | 0.97 |
| reserves amended: all | solar sponge | 0.037 | 0.256 | +0.414 (+0.327 to +0.501) | 0.97 |
| reserves amended: all | v2 energy-only | 0.371 | 0.765 | +0.081 (+0.039 to +0.125) | 0.80 |
| reserves amended: all | energy-only MILP | 0.403 | 0.813 | +0.048 (+0.008 to +0.092) | 0.77 |

| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---|---:|---:|
| energy primary: all | 10 | 0.427 (0.273 to 0.587) | 0.426 | +0.001 (-0.009 to +0.010) | 0.990 (0.969 to 1.000) | 0.40 | 0.30 |
| energy primary: PV/POI 1.25 | 5 | 0.296 (0.155 to 0.470) | 0.299 | -0.002 (-0.022 to +0.015) | 0.979 (0.938 to 1.000) | 0.40 | 0.40 |
| energy primary: PV/POI 1.4 | 5 | 0.558 (0.347 to 0.773) | 0.553 | +0.004 (-0.000 to +0.013) | 1.000 (1.000 to 1.000) | 0.40 | 0.20 |

| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |
|---|---|---:|---:|---|---:|
| energy primary: all | solar sponge | 0.098 | 0.392 | +0.329 (+0.179 to +0.507) | 1.00 |
| energy primary: all | v2 energy-only | 0.341 | 0.866 | +0.086 (+0.011 to +0.209) | 0.80 |
| energy primary: PV/POI 1.25 | solar sponge | 0.118 | 0.391 | +0.179 (+0.129 to +0.224) | 1.00 |
| energy primary: PV/POI 1.25 | v2 energy-only | 0.270 | 0.927 | +0.027 (-0.010 to +0.069) | 0.80 |
| energy primary: PV/POI 1.4 | solar sponge | 0.079 | 0.394 | +0.479 (+0.205 to +0.752) | 1.00 |
| energy primary: PV/POI 1.4 | v2 energy-only | 0.412 | 0.806 | +0.146 (+0.012 to +0.377) | 0.80 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| energy primary: all | 10 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 1 |
| energy primary: PV/POI 1.25 | 5 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 1 |
| energy primary: PV/POI 1.4 | 5 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 0 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| energy primary: all | 10 | 0.049 | 0.200 | 0.268 | 1.000 | 0 on 0 days | none | 0 | 103,319 | 1,500 | 92,399 | $0.0461 | 12.4 |
| energy primary: PV/POI 1.25 | 5 | 0.095 | 0.400 | 0.190 | 1.000 | 0 on 0 days | none | 0 | 118,529 | 1,694 | 106,882 | $0.0509 | 13.6 |
| energy primary: PV/POI 1.4 | 5 | 0.000 | 0.000 | 0.350 | 1.000 | 0 on 0 days | none | 0 | 88,110 | 1,306 | 77,916 | $0.0412 | 11.2 |

Format: 22 planning calls kept an AS field by "keep" or null, 0 of them refused as parse; 0 commits refused as parse in all; 0 days without an accepted watch-0 commit.

energy primary: check_schedule issues by rule: meter_dn 2, soc_empty 1; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 0.00 / 0.00 / 0.00 / 0.00, excused 0.00 / 0.00 / 0.00 / 0.00 / 0.00; error taxonomy no_replanning 8, end_short 1.

Display only: hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150 (reserves): C 0.296 (anchor 0.282, Δ +0.013), R 1.000; AS-hog C 0.081 R 0.429, solar sponge C 0.000 R 0.200, v2 energy-only C 0.134 R 0.580, energy-only MILP C 0.184 R 0.721; profit $1,620,009 (idle $961,432, anchor $1,590,378, hindsight $3,188,806); AS share 0.624; FTP 0.00 MWh charged / 0.00 excused; RegDn drift bought $0 (anchor $122); deployment watches [5, 6], committed at [5, 6]; re-planned 2 of 6 later watches; $0.1778, 23 turns; hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 (reserves): C 0.576 (anchor 0.856, Δ -0.280), R 0.738; AS-hog C 0.499 R 0.666, solar sponge C 0.000 R 0.200, v2 energy-only C 0.437 R 0.609, energy-only MILP C 0.437 R 0.609; profit $6,751 (idle $587, anchor $9,749, hindsight $11,285); AS share 0.948; FTP 215.05 MWh charged / 654.62 excused; RegDn drift bought $-774 (anchor $-664); re-planned 3 of 4 later watches; $0.1759, 22 turns

Unscored: hyb-v3-2025-02-17-LZ_HOUSTON-pv200-r40-1h-poi160 (reserves: cost_cap, 1 attempts).
Spend: v3b-smoke $0.29, v3b-smoke-energy $0.05, v3b-pilot-sol $7.46, v3b-pilot-sol-energy $0.46, v3b-pilot-sol-amend $0.13, v3b-pilot-sol-show $0.35; total $8.75.

Exploratory, not pre-registered (`anchor_policy` played in process on each primary reserves day; Sol − anchor, mean
in C units): DA energy +0.032, RT settlement of the base schedule +0.024, deployment energy −0.099, AS revenue
−0.021, degradation, FTP and end penalty +0.005. Inside deployment energy: RegUp drift sold at RT −0.102 (Sol $0 a
day, the anchor $5,894; $10,687 on deployment days), RegDn drift bought +0.005, RRS/ECRS/Non-Spin deployments
−0.003. Deployment days alone: DA energy +0.025, base RT +0.015, deployment energy −0.111 (RegUp −0.093), AS −0.042;
their mean daily RT maximum is $343 against $77 on the other days.

## Reading (rules 3.1)

- **Headline.** Reserves C 0.440 (0.354 to 0.526) against the anchor's 0.498 on the same 29 days, Δ −0.057 (−0.095
  to −0.022); R 0.839, 8 of 29 at R = 1 (the same 8 beat the anchor). Amended (30 days): C 0.451, Δ −0.054 (−0.092 to
  −0.019), R 0.845. Against P3 under 3.0 (Δ −0.083, different days and rules) the gap is smaller. Sol beats AS-hog by
  +0.300 and the sponge by +0.408 (C units, on 28 of 29 days each), v2 energy-only by +0.077 (+0.035 to +0.122) and
  the energy-only MILP by +0.044 (+0.003 to +0.089, beating it on 22 days).
- **H1 supported: the RegDn loss is gone.** L_reg −0.005 (−0.064 to +0.049), wholly below P3's +0.109 (also on the 17
  non-deployment days: −0.019, −0.109 to +0.063). Sol's RegDn drift bought $4,294 a day against the anchor's $4,415
  (P3: $7,022 against $3,516). Sol now books about the anchor's RegDn (617 MW-h a day against 597; P3 1,103 against
  665), though still more of it in the six highest-DA hours (133 against 111; P3 245 against 103), and the measured
  drift deploys less RegDn when RT clears above DA. **The regulation gap moved to RegUp:** Sol books 3 MW-h of RegUp a
  day against the anchor's 323, and the RegUp drift the anchor sells at RT is worth 0.10 of the attainable (exploratory
  rows), more than Sol's whole gap; Sol wins about half of it back on energy timing.
- **H2 not supported: deployment days cost Sol more, but not through the deployments.** Δ −0.109 (−0.162 to −0.060) on
  the 13 deployment days against −0.016 on the other 16, a gap of −0.093 (−0.161 to −0.028), past the registered
  −0.05. The deployed product is Non-Spin on all 13 days (with ECRS on 2), which neither Sol nor the anchor holds in
  the deployment hours (Sol 0 MW-h on all 13, the anchor 41 MW-h over 3 days), so FTP in the deployed products is
  0.25 MWh in all (anchor 0). Sol committed at 7 of the 13 deployment watches. Deployment days are scarcity days
  (RT peaks $343 on average); there the anchor's RegUp drift sells into the spikes and its AS book earns more
  (−0.093 and −0.042 of Δ). Worst: 2025-05-17 HB_WEST (Δ −0.294, all-AS book, 18 MWh FTP), 2025-11-07 LZ_AEN (−0.286),
  2025-03-10 LZ_CPS (−0.213). Against the energy-only MILP Sol is level on deployment days (−0.014, −0.064 to +0.032)
  and ahead on the others (+0.091, +0.042 to +0.151).
- **H3 supported; the energy tier is still saturated for Sol.** On the 10 oversized days Sol − v2 energy-only is
  +0.086 (+0.011 to +0.209) and Sol − sponge +0.329 (+0.179 to +0.507), so the PV-blind policy now trails (most at
  PV/POI 1.4: +0.146, +0.012 to +0.377; at 1.25 +0.027, −0.010 to +0.069). But Sol ties the anchor: C 0.427 against
  0.426, Δ +0.001 (−0.009 to +0.010), R 0.990 (the registered saturation bar is 0.95), committing once at watch 0 on 8
  of 10 days. The tier now tests clipping against PV-blind play, not this model.
- **H4 not supported, narrowly.** 87 planning calls kept an AS field with `"keep"` or null and none was refused for
  it; one of them (2025-01-24 LZ_SOUTH, watch 2) was refused as `parse` for an 18-value energy list, which the
  registered count includes. One day lost its watch-0 book to a list length again: on 2025-09-25 HB_SOUTH Sol's third
  watch-0 call sent 25 RRS values, the commit was refused as `parse` with no call left, and the day ran with no AS
  (R 0.889). P3's lost day was the same 25-value failure (RegDn).
- **Reserves tier as the test:** Sol − energy-only MILP +0.044 (+0.003 to +0.089) lies above 0, so by the registered
  reading Sol earns from co-optimising AS at this size (P3: undecided). **Anchor scale:** not compressed (8 of 29 at
  R = 1, 9 of 30 amended; the bar is a third).
- **AS and reserves.** AS share 0.456, AS revenue $5,751 a day against the anchor's $6,630 (median ratio 0.93). DA
  book a day: RegUp 3 / RegDn 617 / RRS 1,131 / ECRS 10 / Non-Spin 14 MWh against the anchor's 323 / 597 / 796 / 64 /
  63: Sol still sells RRS in place of RegUp and leaves ECRS and Non-Spin alone. FTP charged 11.7 MWh a day ($21),
  on 11 days, mostly RegDn (248 MWh in all) and RRS (81); 16 days under-reserved (RRS 11, RegDn 7).
- **Display (never counted).** aug10-2023, the hero C3-D18 fixed: Sol out-earns the anchor, $1,620,009 against
  $1,590,378, C 0.296 against 0.282 (Δ +0.013), R 1.0, no FTP, committing at both deployment watches (ECRS and
  Non-Spin). mar29-2024: C 0.576 against the anchor's 0.856 (Δ −0.280), R 0.738, AS share 0.948 and 215 MWh of FTP
  charged.
- **Play and cost.** Every scored day finished with Sol's own `advance` (17.6 turns on reserves days, 12.4 on energy
  days); re-planned after watch 0 on 26 of 29 days, 40% of later watches against the anchor's 35%. $0.165 a reserves
  episode and $0.046 an energy episode; the pilot spent $8.75 of $20 (smoke $0.35 included). Five first attempts
  failed on an upstream gateway authentication error and scored at their retry; one run stopped at its cap and scored
  R 1.0 in its amendment.
