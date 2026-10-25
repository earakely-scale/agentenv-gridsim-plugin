# GridSim v3 hybrid board: the earlier pilot (rules 3.0)

**Earlier pilot, kept on record.** This is the rules-3.0 pilot (`docs/prereg/v3-pilot.md`), re-reported on the cross-version scale. It ran on the 3.0 packs, since rebuilt at rules 3.1 and refilled at 3.2, so its Episode JSON (`results/runs/v3-pilot-sol*`) replay at the preview commit it ran on, not on today's packs. The current v3 pilot, under rules 3.2, is [`board-v3c.md`](board-v3c.md) (`eval-v3c.json`, `pilot-v3c.json`); the rules-3.1 pilot, also kept on record, is [`board-v3b.md`](board-v3b.md).

Tasks: 40 hybrid site-days (ercot-hybrid-v3-eval; AS strata low 14, mid 13, high 13). Harness: gridsim-llm on gridsim-hybrid, 52 turns, 3 planning calls a watch, 16384 output tokens a turn, effort high. R: clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted commit scores 0; idle (0.2) is the solar-only plant, the anchor (1.0) the information-matched rolling MILP.

Headline: hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind the hindsight MILP on realised RT, drift and deployments (a DA copy and a physical copy sharing the AS book), idle the solar-only plant: idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Proxies and flags: deploy_frac: 1.0 assumed (stress case); poi: 1.2x; poi: default; pv_availability: proxy; pv_scope: system; pv_shape: ILR x fleet-AC cf (approximate); reg_drift: seeded; site: archetype.

Baselines (energy, 10 days): C idle 0, sponge 0.000, AS-hog –, v2 energy-only 0.463, energy-only MILP –, anchor 0.484, hindsight 1; R idle 0.200, sponge 0.200, AS-hog –, v2 energy-only 0.979, energy-only MILP –, anchor 1.000.
Baselines (reserves, 30 days): C idle 0, sponge 0.000, AS-hog 0.166, v2 energy-only 0.379, energy-only MILP 0.379, anchor 0.480, hindsight 1; R idle 0.200, sponge 0.200, AS-hog 0.464, v2 energy-only 0.837, energy-only MILP 0.837, anchor 1.000.

| Model | Tier | Days | Runs/planned | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | C low/mid/high AS | Beats sponge | AS share | Clip recovered % | FTP MWh | Refusals | Planning calls | Finished | $/episode | Spend |
|---|---|---:|---:|---|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 30 | 30/30 | 0.397 (0.311 to 0.484) | 0.480 | -0.083 (-0.120 to -0.049) | 0.811 (0.738 to 0.876) | 0.200 | 0.200 | 0.349/0.312/0.530 | 1.000 | 0.510 | – | 2.609 | 1.77 | 6.67 | 1.000 | $0.1902 | $5.70 |
| openai/gpt-6.1-sol | energy | 10 | 10/10 | 0.483 (0.364 to 0.610) | 0.484 | -0.000 (-0.001 to +0.000) | 1.000 (0.999 to 1.000) | 0.800 | 0.600 | 0.352/0.428/0.712 | 1.000 | 0.000 | – | 0.000 | 0.10 | 1.90 | 1.000 | $0.0857 | $0.86 |

## Against the references

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | reserves | sponge | 0.000 | +0.397 (+0.311 to +0.484) | 30 |
| openai/gpt-6.1-sol | reserves | v2_energy | 0.379 | +0.018 (-0.019 to +0.055) | 30 |
| openai/gpt-6.1-sol | reserves | as_hog | 0.166 | +0.231 (+0.159 to +0.306) | 30 |
| openai/gpt-6.1-sol | reserves | energy_only | 0.379 | +0.018 (-0.019 to +0.055) | 30 |
| openai/gpt-6.1-sol | energy | sponge | 0.000 | +0.483 (+0.364 to +0.610) | 10 |
| openai/gpt-6.1-sol | energy | v2_energy | 0.463 | +0.020 (+0.000 to +0.053) | 10 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | refused | ftp_charged | end_short | governed | no_replanning | as_unused |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | reserves | 0 | 18 | 11 | 6 | 24 | 4 | 1 |
| openai/gpt-6.1-sol | energy | 0 | 1 | 0 | 0 | 0 | 10 | 0 |

## Unscored runs

None.

## Pilot (pre-registered in docs/prereg/v3-pilot.md, 87d2d86)

GPT-6.1 Sol, effort high, 52 turns, 16,384 output tokens a turn, $1.00 episode cap. Main column: 30
`ercot-hybrid-v3-eval` days at the reserves tier, 10 per AS stratum; secondary column: the same draw's next 10 days at
the energy tier (`scripts/pilot_v3_tasks.py`, seed 4322); the mar29-2024 showcase day at both tiers, display only.
Computed by `scripts/pilot_v3.py` from the 42 replay-verified Episode JSON v3 (`results/pilot-v3.json`). The
energy-only MILP and v2 energy-only coincide on all 30 main days. Capture is (P − P_idle)/(P_hind − P_idle).
Under-reserved: FTP charged in a product, or a commit row naming it refused under `reserve_up`/`reserve_dn`. Re-plan
rate: watches after watch 0 with an accepted `commit_schedule`, over all watches after watch 0. CIs are 95% bootstrap
over days, paired for differences.

| Set | Days | R (95% CI) | R = 1 | AS-hog R | R − AS-hog (95% CI) | Energy-only MILP R | R − energy-only (95% CI) | v2 energy-only R | Capture (95% CI) | Anchor capture | Capture − anchor (95% CI) | Beats anchor | Beats energy-only | Beats AS-hog |
|---|---:|---|---:|---:|---|---:|---|---:|---|---:|---|---:|---:|---:|
| reserves primary: all | 30 | 0.811 (0.740 to 0.877) | 0.200 | 0.464 | 0.347 (0.251 to 0.439) | 0.836 | -0.025 (-0.100 to 0.042) | 0.836 | 0.397 (0.312 to 0.483) | 0.480 | -0.083 (-0.121 to -0.048) | 0.200 | 0.500 | 0.900 |
| reserves primary: low AS | 10 | 0.830 (0.674 to 0.938) | 0.200 | 0.479 | 0.351 (0.272 to 0.440) | 0.853 | -0.023 (-0.196 to 0.107) | 0.853 | 0.349 (0.233 to 0.468) | 0.416 | -0.068 (-0.119 to -0.022) | 0.200 | 0.500 | 1.000 |
| reserves primary: mid AS | 10 | 0.774 (0.675 to 0.875) | 0.100 | 0.411 | 0.363 (0.190 to 0.548) | 0.870 | -0.096 (-0.200 to 0.011) | 0.870 | 0.312 (0.207 to 0.429) | 0.404 | -0.092 (-0.134 to -0.049) | 0.100 | 0.300 | 0.800 |
| reserves primary: high AS | 10 | 0.829 (0.704 to 0.944) | 0.300 | 0.503 | 0.326 (0.138 to 0.502) | 0.786 | 0.043 (-0.036 to 0.120) | 0.786 | 0.530 (0.360 to 0.704) | 0.619 | -0.089 (-0.176 to -0.011) | 0.300 | 0.700 | 0.900 |
| reserves primary: notice days | 10 | 0.847 (0.749 to 0.937) | 0.200 | 0.428 | 0.419 (0.242 to 0.601) | 0.824 | 0.024 (-0.076 to 0.116) | 0.824 | 0.475 (0.337 to 0.625) | 0.544 | -0.069 (-0.120 to -0.016) | 0.200 | 0.600 | 0.900 |
| reserves primary: quiet days | 20 | 0.793 (0.700 to 0.877) | 0.200 | 0.482 | 0.311 (0.201 to 0.410) | 0.843 | -0.050 (-0.145 to 0.036) | 0.843 | 0.358 (0.263 to 0.463) | 0.448 | -0.090 (-0.140 to -0.048) | 0.200 | 0.450 | 0.900 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| reserves primary: all | 30 | 0.510 | 5,985 | 6,241 | 0.961 | 15.9 / 1102.8 / 1473.4 / 17.8 / 13.6 | 493.2 / 664.7 / 1025.9 / 117.9 / 68.9 | 2.61 | 43.02 | 11 | 15 (0 / 8 / 10 / 1 / 1) | 3.87 | 6 |
| reserves primary: low AS | 10 | 0.496 | 2,731 | 3,132 | 0.885 | 0.0 / 758.1 / 1118.3 / 8.2 / 20.3 | 406.0 / 536.6 / 707.5 / 107.3 / 68.1 | 3.05 | 28.09 | 3 | 5 (0 / 3 / 1 / 0 / 1) | 4.40 | 1 |
| reserves primary: mid AS | 10 | 0.547 | 6,486 | 6,593 | 0.985 | 32.8 / 1433.8 / 1701.9 / 26.0 / 9.4 | 584.1 / 816.7 / 1196.8 / 105.2 / 98.0 | 3.93 | 57.29 | 6 | 7 (0 / 4 / 6 / 0 / 0) | 3.30 | 2 |
| reserves primary: high AS | 10 | 0.488 | 8,739 | 8,999 | 0.997 | 15.0 / 1116.6 / 1600.1 / 19.4 / 11.0 | 489.5 / 640.7 / 1173.4 / 141.1 / 40.4 | 0.85 | 43.69 | 2 | 3 (0 / 1 / 3 / 1 / 0) | 3.90 | 3 |
| reserves primary: notice days | 10 | 0.467 | 6,149 | 6,149 | 0.959 | 40.0 / 1021.8 / 1710.0 / 19.4 / 15.3 | 477.2 / 690.3 / 1284.7 / 85.2 / 50.2 | 3.94 | 48.12 | 6 | 6 (0 / 4 / 5 / 1 / 0) | 5.40 | 1 |
| reserves primary: quiet days | 20 | 0.532 | 5,903 | 6,288 | 0.979 | 3.9 / 1143.4 / 1355.1 / 17.1 / 12.7 | 501.3 / 651.9 / 896.5 / 134.2 / 78.2 | 1.94 | 40.48 | 5 | 9 (0 / 4 / 5 / 0 / 1) | 3.10 | 5 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| reserves primary: all | 30 | 0.460 | 0.867 | 0.323 | 1.000 | 16 on 12 days | reserve_up 16, reserve_dn 14, parse 10, soc_empty 5, soc_full 3, cycle_cap 2, headroom_dn 1, as_fixed 1, headroom_up 1 | 0 | 341,108 | 10,186 | 312,590 | $0.1902 | 17.6 |
| reserves primary: low AS | 10 | 0.525 | 1.000 | 0.350 | 1.000 | 4 on 4 days | parse 6, reserve_dn 5, soc_empty 3, reserve_up 1 | 0 | 344,770 | 12,911 | 313,949 | $0.2221 | 17.2 |
| reserves primary: mid AS | 10 | 0.439 | 0.900 | 0.317 | 1.000 | 8 on 5 days | reserve_up 12, reserve_dn 6, parse 3, soc_full 2, soc_empty 2, headroom_dn 1, as_fixed 1, headroom_up 1 | 0 | 334,343 | 9,436 | 306,356 | $0.1810 | 17.5 |
| reserves primary: high AS | 10 | 0.419 | 0.700 | 0.302 | 1.000 | 4 on 3 days | reserve_up 3, reserve_dn 3, cycle_cap 2, soc_full 1, parse 1 | 0 | 344,209 | 8,212 | 317,464 | $0.1674 | 18.1 |
| reserves primary: notice days | 10 | 0.523 | 0.900 | 0.364 | 1.000 | 5 on 5 days | reserve_dn 10, soc_empty 2, cycle_cap 2, reserve_up 2, headroom_dn 1 | 0 | 411,380 | 10,419 | 380,385 | $0.2042 | 19.8 |
| reserves primary: quiet days | 20 | 0.425 | 0.850 | 0.300 | 1.000 | 11 on 7 days | reserve_up 14, parse 10, reserve_dn 4, soc_empty 3, soc_full 3, as_fixed 1, headroom_up 1 | 0 | 305,971 | 10,070 | 278,692 | $0.1831 | 16.5 |

reserves primary: check_schedule issues by rule: reserve_up 172, reserve_dn 36, soc_empty 32, as_fixed 21, parse 15, soc_full 12, power 9, cycle_cap 6, headroom_dn 2, headroom_up 1; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 60.57 / 17.71 / 0.00 / 0.01, excused 21.88 / 814.86 / 445.71 / 0.00 / 8.25; error taxonomy governed 24, refused 18, ftp_charged 11, end_short 6, no_replanning 4, as_unused 1.

| Set | Days | R (95% CI) | R = 1 | v2 energy-only R | R − v2 energy-only (95% CI) | Capture (95% CI) | Anchor capture | Capture − anchor (95% CI) | Beats anchor | Beats v2 energy-only |
|---|---:|---|---:|---:|---|---|---:|---|---:|---:|
| energy primary: all | 10 | 1.000 (0.999 to 1.000) | 0.800 | 0.979 | 0.020 (0.000 to 0.049) | 0.483 (0.363 to 0.613) | 0.484 | -0.000 (-0.001 to 0.000) | 0.600 | 0.800 |

| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) | DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused | Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day | End short days |
|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|
| energy primary: all | 10 | 0.000 | 0 | 0 | – | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 / 0.0 / 0.0 | 0.00 | 0.00 | 0 | 0 (0 / 0 / 0 / 0 / 0) | 0.00 | 0 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|
| energy primary: all | 10 | 0.000 | 0.000 | 0.000 | 1.000 | 0 on 0 days | parse 1 | 0 | 146,890 | 4,357 | 132,434 | $0.0857 | 12.8 |

energy primary: check_schedule issues by rule: parse 2; FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) 0.00 / 0.00 / 0.00 / 0.00 / 0.00, excused 0.00 / 0.00 / 0.00 / 0.00 / 0.00; error taxonomy no_replanning 10, refused 1.

Showcase (display only): hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 (energy): R 0.989 (v2 energy-only 1.000), capture 0.828 (anchor 0.840), profit $5,204 (idle $587, anchor $5,266, hindsight $6,160), AS share 0.000, FTP 0.00 MWh charged / 0.00 excused, refused rows none, re-planned 0 of 4 later watches, $0.0456, 14 turns

Showcase (display only): hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 (reserves): R 0.847 (AS-hog 0.691, energy-only 0.587, v2 energy-only 0.587), capture 0.744 (anchor 0.920), profit $8,400 (idle $587, anchor $10,250, hindsight $11,084), AS share 0.895, FTP 10.70 MWh charged / 81.16 excused, refused rows none, re-planned 3 of 4 later watches, $0.4210, 25 turns

Unscored: none.
Spend: v3-pilot-sol $5.70, v3-pilot-sol-energy $0.86, v3-pilot-sol-show-energy $0.05, v3-pilot-sol-show-reserves $0.42; total $7.03.

Exploratory, not pre-registered (`anchor_policy` replayed in process on each main day; mean per day, Sol − anchor):
energy revenue −$2,133 (median −$1,140; below the anchor on 23 of 30 days), AS revenue −$256 (median −$214),
degradation +$106, FTP −$8, end penalty $0. RegDn booked in the day's six highest-DA hours: Sol 245 MW-h, anchor 103.
RegDn drift energy bought at RT: Sol $7,022 a day, anchor $3,516.

## Reading

- **H1 holds.** Sol's R is 0.811 (0.740 to 0.877) on the 30 reserves days, inside the v3 plan's 0.65 to 0.85. It beats
  AS-hog by +0.347 (0.251 to 0.439), on 27 of 30 days. Against the energy-only MILP (0.836, the same as v2
  energy-only on every one of these days) it is −0.025 (−0.100 to 0.042) and beats it on 15 days: by the registered
  rule, undecided at this size. By stratum: low 0.830 (energy-only 0.853), mid 0.774 (0.870, −0.096), high 0.829
  (0.786, +0.043). Capture 0.397 against the anchor's 0.480 (−0.083, −0.121 to −0.048). Sol beats the anchor on 6
  days, the same 6 where R = 1.
- **H2 is not supported: Sol does not under-reserve ECRS; it barely sells it.** Its DA book holds 18 MWh of ECRS a day
  against the anchor's 118, 16 MWh of RegUp against 493 and 14 of Non-Spin against 69, and leans on RRS (1,473
  against 1,026) and RegDn (1,103 against 665): the 1 h, drift-free RRS stands in for RegUp, and the 2 h ECRS and 4 h
  Non-Spin are mostly left alone. 15 of 30 days are under-reserved by the registered definition, but in RRS (10) and
  RegDn (8); ECRS and Non-Spin once each. The reservation rule catches nearly all of it before money moves:
  `check_schedule` flagged `reserve_up` on RRS 158 times, the commits still had 16 `reserve_up` and 14 `reserve_dn`
  rows refused (those hours keep their book), and charged FTP is 2.61 MWh and $5.74 a day (the anchor pays $13.76).
  Nor does Sol under-bid AS: $5,985 a day against the anchor's $6,241 (median ratio 0.96).
- **Where Sol loses: RegDn into the evening peak.** The gap to the anchor is on the energy side, not in AS revenue
  (exploratory rows above). Sol books 2.4 times the anchor's RegDn in the day's six highest-priced hours, so the
  seeded RegDn drift (0.18 of the award on average) buys energy at peak RT and fills the battery when it should be
  discharging. 2025-08-01 LZ_AEN is the clearest: RegDn 100 MW through 20:00 to 24:00 bought 114 MWh at $44 to $123,
  the day ended at 136 MWh against a 100 MWh floor, and R is 0.517 against energy-only's 0.891. The anchor sees the
  same expected drift in its projection and avoids it; Sol had it in `check_schedule`'s projected dollars and did not.
- **One day lost to format.** On 2025-06-23 LZ_SOUTH the watch-0 commit, Sol's third planning call after two clean
  checks, sent 25 RegDn values. The whole commit was refused as `parse`, the DA book stayed empty, and the AS were
  locked at zero for the day: R 0.463, against AS-hog 0.772 and energy-only 0.527 there. Seven later commits wrote
  `"keep"` for an AS field (the contract keeps the book when the field is omitted); each was refused as `parse` and
  sent again at the cost of a planning call.
- **Play.** Sol finished all 42 days with its own `advance` (12 to 26 turns, mean 17.6 on reserves days), used all 3
  calls at watch 0 on 26 of 30 days, and re-planned after watch 0 on 26 of 30 days, 46% of later watches against the
  anchor's 32% (v2's pilot: 30% of days, 7.1% of watches). $0.19 a reserves episode (341k input tokens, 92% cached;
  10.2k output) and $0.09 an energy episode; the whole pilot cost $7.03 of the $25 budget, with no cap stop and no
  amendment.
- **Energy tier: saturated.** R 1.000 (0.999 to 1.000) on its 10 days: Sol's profit equals the energy anchor's to
  the cent on 8 and trails it by $0.26 and $163 on the other 2, committing once at watch 0 and never re-planning (nor
  does the anchor). v2 energy-only scores 0.979 on the same days.
- **Showcase mar29-2024 (display only).** Energy tier R 0.989 (capture 0.828 against the anchor's 0.840). Reserves
  tier R 0.847, against AS-hog 0.691 and energy-only 0.587; capture 0.744 against the anchor's 0.920, AS share 0.895,
  10.7 MWh of FTP charged, re-planned at 3 of 4 later watches, $0.42 and 25 turns.
- **Registered readings.** Energy tier (decision 2): saturated for this model on AC-only sites, so it stays a
  secondary column until sites that clip (dc coupling or POI < PV AC) are in the packs. The reserves tier as the
  test: undecided at 30 days (R − energy-only CI −0.100 to 0.042); the tier is not saturated (R from 0.229 to 1.0, 20%
  at 1), and settling Sol against an energy-only MILP needs roughly the full 300 days. Anchor scale: not compressed
  (6 of 30 days at R = 1, under a third).
