# GridSim v3 hybrid board

Tasks: 40 hybrid site-days (ercot-hybrid-v3-eval; AS strata low 13, mid 13, high 14). Harness: gridsim-llm on gridsim-hybrid, 52 turns, 3 planning calls a watch, 16384 output tokens a turn, effort high. R: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted commit scores 0; idle (0.2) is the solar-only plant, the anchor (1.0) the information-matched rolling MILP.

Headline: hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind the hindsight MILP on realised RT, drift and deployments (a DA copy and a physical copy sharing the AS book, settled as the Session settles), idle the solar-only plant: idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Tiers: reserves (the battery's energy and five AS products) is the headline; the energy tier (no AS) is a secondary column.

Proxies and flags: deploy_frac: 1.0 assumed (stress case); poi: 1.2x; poi: default; poi: oversized 1.11; poi: oversized 1.25; poi: oversized 1.40; pv_availability: proxy; pv_scope: system; pv_shape: ILR x fleet-AC cf (approximate); reg_drift: ercot; site: archetype.

Baselines (reserves, 30 days): C idle 0, sponge 0.043, AS-hog 0.043, v2 energy-only 0.320, energy-only MILP 0.350, anchor 0.449, hindsight 1; R idle 0.200, sponge 0.269, AS-hog 0.293, v2 energy-only 0.755, energy-only MILP 0.804, anchor 1.000.
Baselines (energy, 10 days): C idle 0, sponge 0.142, AS-hog –, v2 energy-only 0.317, energy-only MILP –, anchor 0.434, hindsight 1; R idle 0.200, sponge 0.442, AS-hog –, v2 energy-only 0.842, energy-only MILP –, anchor 1.000.

| Model | Tier | Days | Runs/planned | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | C low/mid/high AS | Beats sponge | AS share | Clip recovered % | FTP MWh | Refusals | Planning calls | Finished | $/episode | Spend |
|---|---|---:|---:|---|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 30 | 30/30 | 0.404 (0.339 to 0.468) | 0.449 | -0.045 (-0.073 to -0.017) | 0.878 (0.823 to 0.927) | 0.333 | 0.333 | 0.499/0.348/0.366 | 1.000 | 0.438 | 52.0 | 10.604 | 0.67 | 4.97 | 1.000 | $0.1596 | $4.79 |
| openai/gpt-6.1-sol | energy | 10 | 10/10 | 0.430 (0.290 to 0.585) | 0.434 | -0.004 (-0.011 to -0.000) | 0.989 (0.969 to 1.000) | 0.200 | 0.100 | 0.631/0.332/0.353 | 1.000 | 0.000 | 67.8 | 0.000 | 0.20 | 2.10 | 1.000 | $0.0708 | $0.71 |

## Against the references

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | reserves | sponge | 0.043 | +0.362 (+0.297 to +0.428) | 30 |
| openai/gpt-6.1-sol | reserves | v2_energy | 0.320 | +0.084 (+0.053 to +0.120) | 30 |
| openai/gpt-6.1-sol | reserves | as_hog | 0.043 | +0.362 (+0.284 to +0.435) | 30 |
| openai/gpt-6.1-sol | reserves | energy_only | 0.350 | +0.054 (+0.023 to +0.091) | 30 |
| openai/gpt-6.1-sol | energy | sponge | 0.142 | +0.288 (+0.178 to +0.442) | 10 |
| openai/gpt-6.1-sol | energy | v2_energy | 0.317 | +0.113 (+0.019 to +0.246) | 10 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | refused | ftp_charged | end_short | governed | no_replanning | as_unused |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 0 | 7 | 15 | 5 | 17 | 7 | 0 |
| openai/gpt-6.1-sol | energy | 0 | 1 | 0 | 0 | 0 | 9 | 0 |

## Unscored runs

None.

## Pilot under rules 3.2 (pre-registered in docs/prereg/v3-pilot-c.md, 30d4069)

GPT-6.1 Sol, effort high, 52 turns, 16,384 output tokens a turn, episode cap E = $0.82 (4 x the smoke median
$0.2038). Rules 3.2 (f3bb2c1): every shortfall charged as it happens and P_hind the clairvoyant optimum of that
settlement (C3-D19, C3-D20), the card stating that deployed energy settles at RT, malformed planning calls free up to
three a watch, the cost guard booking as priced, packs refilled. Reserves column: 30 `ercot-hybrid-v3-eval` days, the
24 of the 3.1 pilot's that survive the refill plus 6 drawn by its rule and seed (10 per AS stratum, 12 deployment
days); energy column (secondary): 10 days on sites with PV/POI >= 1.25 (8 survivors, 2 drawn); display: aug10-2023 and
mar29-2024 at the reserves tier (`scripts/pilot_v3c_tasks.py`). Computed by `scripts/pilot_v3c.py` from the 45
replay-verified Episode JSON v3 (`results/pilot-v3c.json`). Headline per `docs/REWARD-SCALES.md`: hindsight capture
C = (P − P_idle)/(P_hind − P_idle), the anchor's C and Δ = C − C_anchor with its paired CI; R second; a baseline
compared as (P − P_ref)/(P_hind − P_idle). CIs: 95% percentile bootstrap over days, 10,000 resamples. Every run
scored at its first attempt, so there is no amended set. FTP is each hour's realized shortfall; the excused column of
the AS table reads 0 under 3.2. L_reg = (Sol's − the anchor's RegDn drift energy bought at RT)/(P_hind − P_idle), the
anchor played in process.

### reserves primary

| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---|---:|---:|
| reserves primary: all | 30 | 0.404 (0.339 to 0.468) | 0.449 | -0.045 (-0.074 to -0.017) | 0.878 (0.820 to 0.927) | 0.33 | 0.33 |
| reserves primary: deployment days | 12 | 0.303 (0.211 to 0.398) | 0.355 | -0.052 (-0.082 to -0.022) | 0.826 (0.720 to 0.919) | 0.17 | 0.17 |
| reserves primary: other days | 18 | 0.472 (0.397 to 0.542) | 0.512 | -0.040 (-0.084 to +0.001) | 0.912 (0.853 to 0.961) | 0.44 | 0.44 |
| reserves primary: low AS | 10 | 0.499 (0.407 to 0.578) | 0.514 | -0.015 (-0.051 to +0.018) | 0.958 (0.920 to 0.990) | 0.50 | 0.50 |
| reserves primary: mid AS | 10 | 0.348 (0.285 to 0.417) | 0.433 | -0.085 (-0.137 to -0.037) | 0.850 (0.761 to 0.931) | 0.20 | 0.20 |
| reserves primary: high AS | 10 | 0.366 (0.226 to 0.513) | 0.400 | -0.034 (-0.078 to +0.017) | 0.826 (0.706 to 0.933) | 0.30 | 0.30 |

| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |
|---|---|---:|---:|---|---:|
| reserves primary: all | AS-hog | 0.043 | 0.293 | +0.362 (+0.285 to +0.436) | 0.97 |
| reserves primary: all | solar sponge | 0.043 | 0.269 | +0.362 (+0.296 to +0.429) | 1.00 |
| reserves primary: all | v2 energy-only | 0.320 | 0.755 | +0.084 (+0.053 to +0.120) | 0.87 |
| reserves primary: all | energy-only MILP | 0.350 | 0.804 | +0.054 (+0.023 to +0.090) | 0.73 |
| reserves primary: deployment days | AS-hog | 0.014 | 0.266 | +0.289 (+0.185 to +0.393) | 0.92 |
| reserves primary: deployment days | solar sponge | 0.020 | 0.239 | +0.283 (+0.190 to +0.381) | 1.00 |
| reserves primary: deployment days | v2 energy-only | 0.239 | 0.704 | +0.064 (+0.026 to +0.108) | 0.83 |
| reserves primary: deployment days | energy-only MILP | 0.270 | 0.762 | +0.033 (-0.002 to +0.067) | 0.75 |
| reserves primary: other days | AS-hog | 0.062 | 0.312 | +0.410 (+0.307 to +0.504) | 1.00 |
| reserves primary: other days | solar sponge | 0.057 | 0.289 | +0.414 (+0.332 to +0.495) | 1.00 |
| reserves primary: other days | v2 energy-only | 0.374 | 0.788 | +0.098 (+0.053 to +0.147) | 0.89 |
| reserves primary: other days | energy-only MILP | 0.403 | 0.832 | +0.069 (+0.022 to +0.122) | 0.72 |
| reserves primary: low AS | AS-hog | 0.040 | 0.280 | +0.459 (+0.358 to +0.553) | 1.00 |
| reserves primary: low AS | solar sponge | 0.077 | 0.299 | +0.421 (+0.338 to +0.505) | 1.00 |
| reserves primary: low AS | v2 energy-only | 0.392 | 0.821 | +0.107 (+0.082 to +0.139) | 1.00 |
| reserves primary: low AS | energy-only MILP | 0.439 | 0.881 | +0.060 (+0.032 to +0.082) | 0.90 |
| reserves primary: mid AS | AS-hog | 0.077 | 0.373 | +0.271 (+0.140 to +0.401) | 1.00 |
| reserves primary: mid AS | solar sponge | 0.049 | 0.295 | +0.300 (+0.208 to +0.392) | 1.00 |
| reserves primary: mid AS | v2 energy-only | 0.308 | 0.761 | +0.040 (+0.007 to +0.074) | 0.70 |
| reserves primary: mid AS | energy-only MILP | 0.329 | 0.803 | +0.019 (-0.022 to +0.062) | 0.50 |
| reserves primary: high AS | AS-hog | 0.011 | 0.228 | +0.355 (+0.218 to +0.485) | 0.90 |
| reserves primary: high AS | solar sponge | 0.002 | 0.213 | +0.365 (+0.224 to +0.511) | 1.00 |
| reserves primary: high AS | v2 energy-only | 0.261 | 0.682 | +0.106 (+0.028 to +0.195) | 0.90 |
| reserves primary: high AS | energy-only MILP | 0.282 | 0.728 | +0.085 (+0.011 to +0.173) | 0.80 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| reserves primary: all | 30 | 0.438 | 5,665 | 6,315 | 0.914 | 42.0 / 310.6 / 1139.9 / 2.7 / 20.9 | 330.4 / 583.5 / 851.5 / 62.1 / 76.1 | 10.60 | 0.00 | 15 | 17 (0 / 6 / 13 / 0 / 2) | 1.50 | 5 |
| reserves primary: deployment days | 12 | 0.511 | 8,507 | 9,409 | 0.833 | 20.3 / 359.2 / 1096.8 / 4.2 / 51.7 | 348.4 / 629.5 / 838.1 / 63.0 / 83.7 | 11.95 | 0.00 | 9 | 9 (0 / 3 / 7 / 0 / 2) | 1.75 | 2 |
| reserves primary: other days | 18 | 0.389 | 3,770 | 4,252 | 0.914 | 56.4 / 278.2 / 1168.7 / 1.6 / 0.4 | 318.3 / 552.9 / 860.4 / 61.6 / 71.0 | 9.70 | 0.00 | 6 | 8 (0 / 3 / 6 / 0 / 0) | 1.33 | 3 |
| reserves primary: low AS | 10 | 0.321 | 1,746 | 2,204 | 0.719 | 3.0 / 191.5 / 871.0 / 0.0 / 0.0 | 212.1 / 469.1 / 570.7 / 27.3 / 45.3 | 8.13 | 0.00 | 4 | 5 (0 / 2 / 4 / 0 / 0) | 1.40 | 2 |
| reserves primary: mid AS | 10 | 0.407 | 3,430 | 4,275 | 0.862 | 74.5 / 310.2 / 851.8 / 5.1 / 9.5 | 331.9 / 498.3 / 768.0 / 46.8 / 41.2 | 14.20 | 0.00 | 7 | 8 (0 / 3 / 6 / 0 / 1) | 1.50 | 2 |
| reserves primary: high AS | 10 | 0.584 | 11,819 | 12,464 | 0.938 | 48.4 / 430.1 / 1697.0 / 2.9 / 53.2 | 447.1 / 783.2 / 1215.7 / 112.3 / 141.7 | 9.48 | 0.00 | 4 | 4 (0 / 1 / 3 / 0 / 1) | 1.60 | 1 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| reserves primary: all | 30 | 0.304 | 0.733 | 0.311 | 1.000 | 9 on 7 days | reserve_up 8, soc_full 6, soc_empty 5, power 1 | 0 | 294,507 | 8,093 | 268,584 | $0.1596 | 15.9 |
| reserves primary: deployment days | 12 | 0.317 | 0.917 | 0.367 | 1.000 | 2 on 2 days | reserve_up 5, soc_full 1, soc_empty 1 | 0 | 346,213 | 9,067 | 317,353 | $0.1801 | 17.5 |
| reserves primary: other days | 18 | 0.293 | 0.611 | 0.267 | 1.000 | 7 on 5 days | soc_full 5, soc_empty 4, reserve_up 3, power 1 | 0 | 260,037 | 7,444 | 236,072 | $0.1460 | 14.9 |
| reserves primary: low AS | 10 | 0.250 | 0.600 | 0.273 | 1.000 | 2 on 1 days | soc_empty 2, soc_full 1, reserve_up 1 | 0 | 250,392 | 7,000 | 226,144 | $0.1411 | 14.5 |
| reserves primary: mid AS | 10 | 0.295 | 0.800 | 0.341 | 1.000 | 6 on 5 days | reserve_up 7, soc_full 5, soc_empty 2, power 1 | 0 | 281,850 | 8,227 | 256,785 | $0.1581 | 15.7 |
| reserves primary: high AS | 10 | 0.362 | 0.800 | 0.319 | 1.000 | 1 on 1 days | soc_empty 1 | 0 | 351,281 | 9,053 | 322,823 | $0.1797 | 17.6 |

| Set | Days | L_reg: (Sol − anchor RegDn drift $)/(P_hind − P_idle) (95% CI) | RegDn drift bought $/day Sol / anchor | Sol − anchor $/day (median) | Days Sol pays more | RegDn drift MWh/day Sol / anchor | RegDn MW-h in the 6 top-DA hours Sol / anchor | RegDn MW-h/day Sol / anchor | RegUp MW-h/day Sol / anchor |
|---|---:|---|---|---|---:|---|---|---|---|
| reserves primary: all | 30 | -0.076 (-0.122 to -0.037) | 2,546 / 4,458 | -1,911 (-1,139) | 7 of 30 | 74.1 / 139.2 | 76 / 119 | 311 / 584 | 42 / 330 |
| reserves primary: deployment days | 12 | -0.038 (-0.077 to -0.004) | 3,947 / 6,728 | -2,781 (-1,249) | 2 of 12 | 82.6 / 162.4 | 101 / 136 | 359 / 630 | 20 / 348 |
| reserves primary: other days | 18 | -0.102 (-0.170 to -0.042) | 1,612 / 2,944 | -1,332 (-1,139) | 5 of 18 | 68.4 / 123.7 | 59 / 107 | 278 / 553 | 56 / 318 |
| reserves primary: low AS | 10 | -0.086 (-0.150 to -0.026) | 558 / 1,633 | -1,075 (-767) | 2 of 10 | 48.2 / 98.4 | 35 / 76 | 191 / 469 | 3 / 212 |
| reserves primary: mid AS | 10 | -0.045 (-0.105 to +0.007) | 1,878 / 2,592 | -713 (-639) | 3 of 10 | 59.3 / 97.4 | 71 / 108 | 310 / 498 | 74 / 332 |
| reserves primary: high AS | 10 | -0.098 (-0.203 to -0.017) | 5,203 / 9,149 | -3,946 (-3,965) | 2 of 10 | 114.7 / 221.7 | 122 / 172 | 430 / 783 | 48 / 447 |

| Day | Deployed (hours) | Award MW-h in those hours Sol / anchor | FTP MWh charged in it Sol / anchor | Deployment watches, Sol committed at | C | Anchor's C | Δ | R |
|---|---|---|---|---|---:|---:|---:|---:|
| `hyb-v3-2025-03-05-HB_HOUSTON-pv150-b100x2h-poi180` | nspin 17-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [6] / [6] | 0.351 | 0.369 | -0.019 | 0.960 |
| `hyb-v3-2025-03-05-LZ_NORTH-pv100-r80-2h-poi80` | nspin 17-19 | nspin 0 / 0 | nspin 0.00 / 1.63 | [6] / [6] | 0.382 | 0.537 | -0.154 | 0.770 |
| `hyb-v3-2025-03-10-LZ_CPS-pv100-r40-1h-poi120` | nspin 18-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [5] | 0.392 | 0.391 | +0.001 | 1.000 |
| `hyb-v3-2025-03-10-LZ_NORTH-pv150-b100x2h-poi150` | nspin 18-19 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [5] | 0.366 | 0.427 | -0.061 | 0.886 |
| `hyb-v3-2025-04-07-HB_SOUTH-pv300-r80-1h-poi240` | ecrs 6-7, nspin 6-7 | ecrs 0 / 0, nspin 0 / 3 | ecrs 0.00 / 0.00, nspin 0.00 / 0.00 | [3] / [] | 0.042 | 0.108 | -0.066 | 0.511 |
| `hyb-v3-2025-05-16-LZ_WEST-pv100-r67-1h-poi120` | ecrs 19-20, nspin 19-21 | ecrs 0 / 0, nspin 0 / 0 | ecrs 0.00 / 0.00, nspin 0.00 / 0.00 | [5] / [] | 0.067 | 0.186 | -0.119 | 0.487 |
| `hyb-v3-2025-05-17-HB_WEST-pv150-b100x2h-poi180` | nspin 19-20 | nspin 0 / 5 | nspin 2.78 / 0.08 | [5] / [5] | 0.249 | 0.292 | -0.043 | 0.883 |
| `hyb-v3-2025-05-17-LZ_WEST-pv200-r40-2h-poi200` | nspin 19-20 | nspin 0 / 0 | nspin 0.00 / 2.27 | [5] / [] | 0.281 | 0.294 | -0.014 | 0.963 |
| `hyb-v3-2025-09-04-HB_PAN-pv100-r67-2h-poi100` | nspin 18-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [5] / [5] | 0.536 | 0.547 | -0.010 | 0.985 |
| `hyb-v3-2025-10-21-HB_HOUSTON-pv200-r40-1h-poi240` | nspin 17-20 | nspin 0 / 0 | nspin 0.00 / 0.00 | [4] / [4] | 0.206 | 0.307 | -0.101 | 0.738 |
| `hyb-v3-2025-10-21-LZ_SOUTH-pv300-r80-2h-poi300` | nspin 17-20 | nspin 114 / 0 | nspin 0.00 / 0.00 | [4] / [4] | 0.159 | 0.238 | -0.079 | 0.735 |
| `hyb-v3-2025-11-07-LZ_AEN-pv150-r67-1h-poi150` | nspin 16-18 | nspin 0 / 0 | nspin 0.00 / 2.36 | [4] / [] | 0.607 | 0.566 | +0.041 | 1.000 |

Δ on deployment days -0.052 against -0.040 on the others: gap -0.012 (-0.063 to +0.040, unpaired); FTP charged in the deployed products 2.78 MWh (anchor 6.33); Sol committed at 8 of 12 deployment watches.

RegUp (exploratory): Sol books 42 MW-h a day against the anchor's 330 (on 9 and 29 of 30 days); on the 24 days common with the 3.1 pilot 45 against 3.1 Sol's 1 and the 3.2 anchor's 356.

Format (V3-D16): 1 malformed planning calls on 1 days (1 parse refusals, 0 argument errors), 1 used no planning call and 0 used one; 0 planning calls found no calls left (0 in a watch after a malformed call); 78 plans kept an AS field by "keep" or null, 0 refused as parse; days without an accepted watch-0 commit: 0.

reserves primary: check_schedule issues by rule: reserve_up 77, soc_full 19, reserve_dn 14, soc_empty 10, power 4, headroom_dn 3, meter_dn 3, cycle_cap 2, parse 1; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 159.10 / 156.26 / 0.00 / 2.78; end penalty $111 a day on 5 days; error taxonomy governed 17, ftp_charged 15, no_replanning 7, refused 7, end_short 5.

reserves primary, exploratory: the 3.1 pilot's surviving days, paired (rules changed: not a model comparison)

| Days | Sol 3.1, 3.1 rules: C / Δ | Sol 3.1's play settled under 3.2: C / Δ | Sol 3.2: C / Δ | C 3.2 − C 3.1 (95% CI) | Δ 3.2 − Δ 3.1 (95% CI) | Sol 3.2 − Sol 3.1's play, both under 3.2: (P − P')/(P_hind − P_idle) (95% CI) | R 3.1 / 3.2 | R = 1 3.1 / 3.2 |
|---:|---|---|---|---|---|---|---|---|
| 24 | 0.432 / -0.068 | 0.391 / -0.058 | 0.396 / -0.053 | -0.036 (-0.083 to +0.017) | +0.015 (-0.029 to +0.063) | +0.005 (-0.038 to +0.053) | 0.820 / 0.858 | 6 / 6 |

### energy primary

| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |
|---|---:|---|---:|---|---|---:|---:|
| energy primary: all | 10 | 0.430 (0.289 to 0.578) | 0.434 | -0.004 (-0.011 to -0.000) | 0.989 (0.968 to 1.000) | 0.20 | 0.10 |
| energy primary: PV/POI 1.25 | 5 | 0.317 (0.202 to 0.483) | 0.324 | -0.007 (-0.022 to -0.000) | 0.979 (0.938 to 1.000) | 0.20 | 0.20 |
| energy primary: PV/POI 1.4 | 5 | 0.543 (0.332 to 0.734) | 0.543 | -0.001 (-0.002 to -0.000) | 0.999 (0.998 to 1.000) | 0.20 | 0.00 |

| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |
|---|---|---:|---:|---|---:|
| energy primary: all | solar sponge | 0.142 | 0.442 | +0.288 (+0.178 to +0.444) | 1.00 |
| energy primary: all | v2 energy-only | 0.317 | 0.842 | +0.113 (+0.019 to +0.245) | 0.80 |
| energy primary: PV/POI 1.25 | solar sponge | 0.118 | 0.391 | +0.199 (+0.171 to +0.226) | 1.00 |
| energy primary: PV/POI 1.25 | v2 energy-only | 0.295 | 0.946 | +0.022 (-0.015 to +0.064) | 0.80 |
| energy primary: PV/POI 1.4 | solar sponge | 0.166 | 0.493 | +0.377 (+0.166 to +0.630) | 1.00 |
| energy primary: PV/POI 1.4 | v2 energy-only | 0.339 | 0.737 | +0.204 (+0.033 to +0.420) | 0.80 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| energy primary: all | 10 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 0 |
| energy primary: PV/POI 1.25 | 5 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 0 |
| energy primary: PV/POI 1.4 | 5 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 0 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| energy primary: all | 10 | 0.024 | 0.100 | 0.195 | 1.000 | 1 on 1 days | meter_dn 1, soc_empty 1 | 0 | 146,913 | 3,088 | 133,617 | $0.0708 | 14.1 |
| energy primary: PV/POI 1.25 | 5 | 0.048 | 0.200 | 0.000 | 1.000 | 1 on 1 days | meter_dn 1, soc_empty 1 | 0 | 126,664 | 1,616 | 115,195 | $0.0506 | 14.4 |
| energy primary: PV/POI 1.4 | 5 | 0.000 | 0.000 | 0.400 | 1.000 | 0 on 0 days | none | 0 | 167,163 | 4,561 | 152,039 | $0.0911 | 13.8 |

Format (V3-D16): 0 malformed planning calls on 0 days (0 parse refusals, 0 argument errors), 0 used no planning call and 0 used one; 0 planning calls found no calls left (0 in a watch after a malformed call); 21 plans kept an AS field by "keep" or null, 0 refused as parse; days without an accepted watch-0 commit: 0.

energy primary: check_schedule issues by rule: meter_dn 1, soc_empty 1; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 0.00 / 0.00 / 0.00 / 0.00; end penalty $0 a day on 0 days; error taxonomy no_replanning 9, refused 1.

energy primary, exploratory: the 3.1 pilot's surviving days, paired (rules changed: not a model comparison)

| Days | Sol 3.1, 3.1 rules: C / Δ | Sol 3.1's play settled under 3.2: C / Δ | Sol 3.2: C / Δ | C 3.2 − C 3.1 (95% CI) | Δ 3.2 − Δ 3.1 (95% CI) | Sol 3.2 − Sol 3.1's play, both under 3.2: (P − P')/(P_hind − P_idle) (95% CI) | R 3.1 / 3.2 | R = 1 3.1 / 3.2 |
|---:|---|---|---|---|---|---|---|---|
| 8 | 0.426 / -0.005 | 0.426 / -0.005 | 0.426 / -0.005 | +0.000 (+0.000 to +0.000) | +0.000 (+0.000 to +0.000) | +0.000 (+0.000 to +0.000) | 0.987 / 0.987 | 2 / 2 |

Display only: hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150 (reserves): C 0.282 (anchor 0.262, Δ +0.020), R 1.000; AS-hog C 0.054 R 0.366, solar sponge C 0.000 R 0.200, v2 energy-only C 0.132 R 0.603, energy-only MILP C 0.181 R 0.753; profit $1,600,835 (idle $961,432, anchor $1,554,645, hindsight $3,228,428); AS share 0.732; FTP 7.13 MWh charged; RegDn drift bought $0 (anchor $122); deployment watches [5, 6], committed at [5, 6]; re-planned 2 of 6 later watches; $0.1657, 20 turns; hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 (reserves): C 0.562 (anchor 0.515, Δ +0.047), R 1.000; AS-hog C 0.090 R 0.339, solar sponge C 0.000 R 0.200, v2 energy-only C 0.402 R 0.823, energy-only MILP C 0.402 R 0.823; profit $7,136 (idle $587, anchor $6,591, hindsight $12,239); AS share 0.483; FTP 133.06 MWh charged; RegDn drift bought $-400 (anchor $-664); re-planned 3 of 4 later watches; $0.1797, 22 turns

Unscored: none.
Spend: v3c-smoke $0.42, v3c-smoke-energy $0.05, v3c-pilot-sol $4.79, v3c-pilot-sol-energy $0.71, v3c-pilot-sol-show $0.35; total $6.31.

Exploratory, not pre-registered (`anchor_policy` played in process on each reserves day; Sol − anchor, mean in C
units): DA energy −0.033, RT settlement of the base schedule +0.027, RegUp drift sold at RT −0.093 (Sol $276 a day,
the anchor $5,788; $422 against $11,345 on deployment days), RegDn drift bought +0.076, RRS/ECRS/Non-Spin deployments
0.000, AS revenue −0.040, degradation, FTP and end penalty +0.017. Deployment days alone: DA energy +0.019, base RT
−0.008, RegUp −0.077, RegDn +0.038, AS −0.037; other days: DA −0.067, base RT +0.050, RegUp −0.103, RegDn +0.102, AS
−0.041.

## Reading (rules 3.2)

- **Headline: below the anchor.** Reserves C 0.404 (0.339 to 0.468) against the anchor's 0.449 on the same 30 days,
  Δ −0.045 (−0.074 to −0.017), wholly below 0. R 0.878 (0.820 to 0.927), 10 of 30 at R = 1 (the same 10 beat the
  anchor). Sol beats AS-hog and the sponge by +0.362 each (C units, on 29 and 30 days), v2 energy-only by +0.084
  (+0.053 to +0.120) and the energy-only MILP by +0.054 (+0.023 to +0.090, on 22 days).
- **Reserves tier as the test:** Sol − energy-only MILP lies above 0, so by the registered reading Sol earns from
  co-optimising AS at this size, as at 3.1 (+0.044 there).
- **Deployments: handled.** Δ −0.052 (−0.082 to −0.022) on the 12 deployment days against −0.040 (−0.084 to +0.001)
  on the 18 others, a gap of −0.012 (−0.063 to +0.040), inside the registered 0.05 (3.1: −0.093). FTP in the deployed
  products 2.78 MWh (anchor 6.33); Sol committed at 8 of 12 deployment watches, and on 2025-10-21 LZ_SOUTH held 114
  MW-h of Non-Spin through its deployment without a shortfall. Against the energy-only MILP Sol is level on deployment
  days (+0.033, −0.002 to +0.067) and ahead on the others (+0.069, +0.022 to +0.122).
- **The 3.2 format fix holds.** Every reserves and energy day has an accepted watch-0 commit (3.1 lost 2025-09-25's to
  a 25-value RRS list). One planning call in 40 days was malformed (a parse refusal on 2025-07-25 LZ_AEN), and it used
  no call; no planning call found no calls left; 99 plans kept an AS field by `"keep"` or null, none refused.
- **RegUp: booked now, still the main loss (exploratory).** Sol books 42 MW-h of RegUp a day against the anchor's 330
  (on 9 of 30 days; 3.1 Sol booked 1 a day on the 24 common days), above a tenth of the anchor's, so by the registered
  reading the gap does not persist, narrowly. In cash it does: RegUp drift the anchor sells into RT is −0.093 of the
  attainable for Sol, more than its whole Δ, and Sol takes +0.076 back by booking half the anchor's RegDn (311 MW-h a
  day against 584; L_reg −0.076, −0.122 to −0.037). Worst day: 2025-09-25 HB_SOUTH (Δ −0.245, R 0.555; deployment
  energy −0.376): the anchor's 548 MW-h of RegUp sold its drift at RT, Sol held none and booked 540 MW-h of RegDn
  against the anchor's 158.
- **3.1 against 3.2 on the common days (exploratory; the rules changed, so not a model comparison).** On the 24
  reserves days Sol's C moved from 0.432 to 0.396 (−0.036, −0.083 to +0.017) while the anchor's fell from 0.500 to
  0.449 (excused charges now count and P_hind rose), so Δ moved from −0.068 to −0.053 (+0.015, −0.029 to +0.063). Under one
  settlement the two runs are level: P3b's plays re-settled on the 3.2 Session against this run, +0.005 (−0.038 to
  +0.053), per day from −0.187 to +0.298; R 0.820 and 0.858, 6 days at R = 1 in each. On the 8 energy days this run's
  plays settle at exactly P3b's profits (the energy card did not change).
- **Energy tier saturated (secondary column).** C 0.430 against the anchor's 0.434, Δ −0.004 (−0.011 to −0.000), R
  0.989 (the bar is 0.95), committing once at watch 0 on 8 of 10 days. Sol − v2 energy-only +0.113 (+0.019 to +0.245)
  and − sponge +0.288 (+0.178 to +0.444): the tier separates the PV-blind and sponge policies, not this model.
- **Anchor scale:** 10 of 30 at R = 1, exactly a third: not compressed by V2-D1's rule (more than a third), at its edge.
- **Display days.** aug10-2023: C 0.282 against the anchor's 0.262 (Δ +0.020), R 1.0 (3.1: 0.296 against 0.282).
  mar29-2024: C 0.562 against 0.515 (Δ +0.047), R 1.0 (3.1: 0.576 against 0.856, R 0.738); the anchor's C there fell
  most under 3.2.
- Spend $6.31 of $15 (smoke $0.47, reserves $4.79, energy $0.71, display $0.35), $0.160 a reserves episode. All 45
  Episode JSON (the smoke's 3 included) replay byte for byte on a fresh Session, audits ok.

## Earlier pilots

The 3.0 pilot (`results/board-v3.md`, `docs/prereg/v3-pilot.md`) and the 3.1 re-pilot (`results/board-v3b.md`,
`docs/prereg/v3-pilot-b.md`) stay on record under their own rules and references; their C and Δ are not comparable
with these except as read above.
