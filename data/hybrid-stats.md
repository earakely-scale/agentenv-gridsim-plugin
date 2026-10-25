# v3 hybrid packs: counts, filters and baselines

Built by `scripts/build_hybrid_pack.py` (2026-10-24). References: `gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.

## Packs

| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | 2400 | A 1488, B 912 | 2021-01-01..2024-12-31 | 1006 | 312 | 1818 |
| `ercot-hybrid-v3-eval` | 300 | B 300 | 2025-01-01..2025-11-28 | 87 | 13 | 262 |
| `ercot-hybrid-v3-rtcb` | 200 | C 200 | 2025-12-06..2026-09-30 | 41 | 21 | 170 |
| `ercot-hybrid-v3-showcase` | 4 | B 3, C 1 | 2023-08-10..2026-01-26 | 3 | 2 | 1 |
| `fixtures-hybrid` | 20 | A 8, B 8, C 4 | 2021-04-23..2026-08-19 | 6 | 4 | 15 |

## Filters (the v3 plan)

Thresholds: P_anchor - P_idle >= $500 in both tiers; v1's low-spread drop (energy-tier anchor - idle >= $22 per MW of battery); sponge reward < 0.97 (the sponge within 3% of the anchor); and, extending that rule (C3-D16), every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP below 0.97 against the reserves anchor. Uri and every showcase day +/-3 days are out of every split; DST days and days without 24 hourly inputs are dropped.

| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Fail baseline >= 0.97 | Eligible | Kept |
|---|---|---|---|---|---|---|---|
| train | 4239 | 49 | 439 | 24 | 436 | 3419 | 2400 |
| eval | 1328 | 22 | 88 | 20 | 406 | 853 | 300 |
| rtcb | 584 | 16 | 95 | 9 | 174 | 341 | 200 |

## Baselines and references (means over each pack)

| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours | Anchor soft solves (share of watches) | Anchor entries repaired |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | energy | 17318.1114 | 0.4751 | 0.2464 | 0.7593 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-train` | reserves | 51569.7634 | 0.7016 | 0.2234 | 0.415 | 0.7122 | 0.5089 | 52346.8591 | 6.5904 | 0.2752 | 2.2425 |
| `ercot-hybrid-v3-eval` | energy | 10513.1164 | 0.4672 | 0.2648 | 0.9531 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-eval` | reserves | 14104.1071 | 0.5239 | 0.2524 | 0.7638 | 0.47 | 0.8009 | 6175.6325 | 4.6333 | 0.0989 | 0.35 |
| `ercot-hybrid-v3-rtcb` | energy | 7017.9321 | 0.4058 | 0.2982 | 0.9313 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-rtcb` | reserves | 9746.6419 | 0.4541 | 0.2783 | 0.7403 | 0.3944 | 0.7951 | 5376.0647 | 4.415 | 0.2238 | 0.405 |
| `ercot-hybrid-v3-showcase` | energy | 220608.0074 | 0.4897 | 0.2 | 0.9311 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-showcase` | reserves | 273508.7871 | 0.4777 | 0.4 | 0.7112 | 0.4129 | 0.7465 | 239003.3834 | 4.25 | 0.2667 | 1.0 |
| `fixtures-hybrid` | energy | 54039.6889 | 0.5024 | 0.2502 | 0.8627 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `fixtures-hybrid` | reserves | 67599.2617 | 0.6234 | 0.2823 | 0.5674 | 0.591 | 0.651 | 73125.4064 | 5.65 | 0.3233 | 1.35 |

## Energy tier by POI (PV AC / POI): the solar sponge and v2 energy-only against the energy anchor

| Pack | POI | Tasks | Clippable MWh/day | Sponge | v2 energy-only | Anchor - idle ($) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | at or above PV AC | 1435 | 0.0 | 0.2 | 0.8242 | 17742.2494 |
| `ercot-hybrid-v3-train` | oversized | 965 | 73.2133 | 0.3154 | 0.6629 | 16687.3985 |
| `ercot-hybrid-v3-eval` | at or above PV AC | 196 | 0.0 | 0.2 | 0.9776 | 11337.2711 |
| `ercot-hybrid-v3-eval` | oversized | 104 | 86.2818 | 0.387 | 0.9069 | 8959.9018 |
| `ercot-hybrid-v3-rtcb` | at or above PV AC | 119 | 0.0 | 0.2 | 0.9841 | 7328.3068 |
| `ercot-hybrid-v3-rtcb` | oversized | 81 | 99.8801 | 0.4424 | 0.8538 | 6561.9495 |
| `ercot-hybrid-v3-showcase` | at or above PV AC | 4 | 0.0 | 0.2 | 0.9311 | 220608.0074 |
| `fixtures-hybrid` | at or above PV AC | 14 | 0.0 | 0.2 | 0.9119 | 22671.3862 |
| `fixtures-hybrid` | oversized | 6 | 157.2573 | 0.3674 | 0.7479 | 127232.3953 |

## Regulation drift source (V3-D8)

| Pack | ercot | ercot+modelled | modelled |
|---|---|---|---|
| `ercot-hybrid-v3-train` | 704 | 0 | 1696 |
| `ercot-hybrid-v3-eval` | 300 | 0 | 0 |
| `ercot-hybrid-v3-rtcb` | 162 | 0 | 38 |
| `ercot-hybrid-v3-showcase` | 2 | 0 | 2 |
| `fixtures-hybrid` | 9 | 0 | 11 |

## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise does not move a day between strata)

| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |
|---|---|---|---|---|
| low | 100 | 336..1899 | 0.44 | 0.8546 |
| mid | 100 | 1938..3664 | 0.4582 | 0.8021 |
| high | 100 | 3682..26618 | 0.5119 | 0.7461 |

## Timing

- references: 510.5 ms per task-core (both tiers; about 15 MILP solves, 2 hindsight MILPs and 2 LPs per task)
- MILP solve (watch 0, 24 open hours): median 8.7 ms, p95 13.4 ms over 60 solves
- build wall time 321 s on 10 workers

## Flags

- Sites are archetypes at hubs and load zones (no crosswalk, V3-D11): 40% the v3 plan's default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; POI = PV AC, 20% at the 1.2x variant and 40% below PV AC (PV AC / POI one of 1.11, 1.25, 1.4; V3-D12); AC coupling only (C3-D15).
- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).
- Oversized sites clip at the meter (clippable MWh, every pack: ercot-hybrid-v3-train 70651, ercot-hybrid-v3-eval 8973, ercot-hybrid-v3-rtcb 8090, ercot-hybrid-v3-showcase 0, fixtures-hybrid 944), so the energy tier tests charging from clipped solar and the sponge is no longer idle.
- Anchor soft solves: after watch 0 the reserves tier keeps the DA awards, and realized drift can leave an hour whose awards no move can back; the hard MILP is then infeasible, the soft one minimises the shortfall, and the repair walk turns the entries the Session refuses into the governor's move (C3-D17), so the anchor's commits are never refused. A hard solution is never repaired (tested).
- Regulation drift is ERCOT's storage fleet deployment (60-Day SCED Disclosure) on days it covers (from 2023-10-12) and the imbalance-driven fallback before (data/hybrid/reg_deploy.md); deployments use frac 1.0 (stress case).
- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.
