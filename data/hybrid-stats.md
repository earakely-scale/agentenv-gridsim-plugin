# v3 hybrid packs: counts, filters and baselines

Built by `scripts/build_hybrid_pack.py` (2026-10-24). References: `gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.

## Packs

| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | 2400 | A 1449, B 951 | 2021-01-01..2024-12-31 | 980 | 305 | 1818 |
| `ercot-hybrid-v3-eval` | 300 | B 300 | 2025-01-01..2025-11-28 | 92 | 12 | 253 |
| `ercot-hybrid-v3-rtcb` | 200 | C 200 | 2025-12-06..2026-09-30 | 45 | 20 | 169 |
| `ercot-hybrid-v3-showcase` | 4 | B 3, C 1 | 2023-08-10..2026-01-26 | 3 | 2 | 1 |
| `fixtures-hybrid` | 20 | A 9, B 8, C 3 | 2021-01-17..2026-09-28 | 8 | 5 | 14 |

## Filters (FD-4322)

Thresholds: P_anchor - P_idle >= $500 in both tiers; v1's low-spread drop (energy-tier anchor - idle >= $22 per MW of battery); sponge reward < 0.97 (the sponge within 3% of the anchor); and, extending that rule (C3-D16), every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP below 0.97 against the reserves anchor. Uri and every showcase day +/-3 days are out of every split; DST days and days without 24 hourly inputs are dropped.

| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Fail baseline >= 0.97 | Eligible | Kept |
|---|---|---|---|---|---|---|---|
| train | 4239 | 41 | 464 | 15 | 416 | 3407 | 2400 |
| eval | 1328 | 19 | 95 | 9 | 227 | 1011 | 300 |
| rtcb | 584 | 19 | 111 | 7 | 111 | 390 | 200 |

## Baselines and references (means over each pack)

| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours |
|---|---|---|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | energy | 17585.1806 | 0.4658 | 0.2 | 0.8259 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-train` | reserves | 53388.3067 | 0.7005 | 0.2 | 0.4397 | 0.7541 | 0.497 | 54893.3537 | 7.0725 |
| `ercot-hybrid-v3-eval` | energy | 10627.9438 | 0.4385 | 0.2 | 0.9891 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-eval` | reserves | 14019.2604 | 0.5066 | 0.2 | 0.7854 | 0.4927 | 0.7933 | 6612.545 | 4.4033 |
| `ercot-hybrid-v3-rtcb` | energy | 6784.6776 | 0.3779 | 0.2 | 0.9844 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-rtcb` | reserves | 9625.9864 | 0.4437 | 0.2 | 0.7643 | 0.3501 | 0.775 | 5084.0007 | 3.805 |
| `ercot-hybrid-v3-showcase` | energy | 220608.0074 | 0.4897 | 0.2 | 0.9311 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-showcase` | reserves | 243465.4846 | 0.4814 | 0.2 | 0.7555 | 0.7379 | 0.8092 | 238422.3992 | 2.25 |
| `fixtures-hybrid` | energy | 44635.0836 | 0.5027 | 0.2 | 0.9275 | - | - | 0.0 | 0.0 |
| `fixtures-hybrid` | reserves | 119350.8845 | 0.6659 | 0.2 | 0.5764 | 0.7042 | 0.6077 | 142941.1036 | 4.65 |

## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise does not move a day between strata)

| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |
|---|---|---|---|---|
| low | 100 | 401..1905 | 0.4481 | 0.8425 |
| mid | 100 | 1924..3583 | 0.4844 | 0.7895 |
| high | 100 | 3621..37000 | 0.5457 | 0.7478 |

## Timing

- references: 309.1 ms per task-core (both tiers; about 15 MILP solves, 2 hindsight MILPs and 2 LPs per task)
- MILP solve (watch 0, 24 open hours): median 6.1 ms, p95 9.3 ms over 60 solves
- build wall time 163 s on 12 workers

## Flags

- Sites are archetypes at hubs and load zones (no crosswalk tonight, V3-D11): 40% the FD-4322 default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; POI = PV AC, 25% at the 1.2x variant; AC coupling only (C3-D15).
- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).
- Regulation drift is a seeded draw, not ERCOT telemetry; deployments use frac 1.0 (stress case).
- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.
