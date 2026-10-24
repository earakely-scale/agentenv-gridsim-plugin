# v3 hybrid packs: counts, filters and baselines

Built by `scripts/build_hybrid_pack.py` (2026-10-24). References: `gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.

## Packs

| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | 2400 | A 1445, B 955 | 2021-01-01..2024-12-31 | 981 | 307 | 1815 |
| `ercot-hybrid-v3-eval` | 300 | B 300 | 2025-01-01..2025-11-28 | 92 | 12 | 253 |
| `ercot-hybrid-v3-rtcb` | 200 | C 200 | 2025-12-06..2026-09-30 | 44 | 20 | 169 |
| `ercot-hybrid-v3-showcase` | 4 | B 3, C 1 | 2023-08-10..2026-01-26 | 3 | 2 | 1 |
| `fixtures-hybrid` | 20 | A 9, B 8, C 3 | 2021-01-17..2026-09-28 | 8 | 5 | 14 |

## Filters (FD-4322)

Thresholds: P_anchor - P_idle >= $500 in both tiers; v1's low-spread drop (energy-tier anchor - idle >= $22 per MW of battery); sponge reward < 0.97 (the sponge within 3% of the anchor); and, extending that rule (C3-D16), every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP below 0.97 against the reserves anchor. Uri and every showcase day +/-3 days are out of every split; DST days and days without 24 hourly inputs are dropped.

| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Fail baseline >= 0.97 | Eligible | Kept |
|---|---|---|---|---|---|---|---|
| train | 4239 | 44 | 464 | 16 | 430 | 3397 | 2400 |
| eval | 1328 | 19 | 95 | 8 | 224 | 1013 | 300 |
| rtcb | 584 | 18 | 111 | 5 | 109 | 392 | 200 |

## Baselines and references (means over each pack)

| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours | Anchor soft solves (share of watches) | Anchor entries repaired |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | energy | 17601.6812 | 0.4657 | 0.2 | 0.8257 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-train` | reserves | 53192.2249 | 0.6993 | 0.2 | 0.4401 | 0.7537 | 0.4974 | 55001.2817 | 6.5383 | 0.2508 | 1.76 |
| `ercot-hybrid-v3-eval` | energy | 10624.9646 | 0.4383 | 0.2 | 0.9891 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-eval` | reserves | 14005.1099 | 0.5054 | 0.2 | 0.7862 | 0.4923 | 0.794 | 6612.7689 | 4.24 | 0.134 | 0.48 |
| `ercot-hybrid-v3-rtcb` | energy | 6787.3751 | 0.3737 | 0.2 | 0.9844 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-rtcb` | reserves | 9621.381 | 0.4393 | 0.2 | 0.7638 | 0.3572 | 0.7748 | 5144.4013 | 3.645 | 0.2458 | 0.615 |
| `ercot-hybrid-v3-showcase` | energy | 220608.0074 | 0.4897 | 0.2 | 0.9311 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-showcase` | reserves | 245681.8159 | 0.4827 | 0.2 | 0.7507 | 0.7344 | 0.8031 | 238422.3992 | 2.25 | 0.2131 | 0.5 |
| `fixtures-hybrid` | energy | 44635.0836 | 0.5027 | 0.2 | 0.9275 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `fixtures-hybrid` | reserves | 115355.7846 | 0.6651 | 0.2 | 0.5757 | 0.7044 | 0.607 | 142941.1036 | 4.25 | 0.3438 | 1.95 |

## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise does not move a day between strata)

| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |
|---|---|---|---|---|
| low | 100 | 401..1905 | 0.4478 | 0.8408 |
| mid | 100 | 1924..3583 | 0.484 | 0.7942 |
| high | 100 | 3621..37000 | 0.5451 | 0.7471 |

## Timing

- references: 351.7 ms per task-core (both tiers; about 15 MILP solves, 2 hindsight MILPs and 2 LPs per task)
- MILP solve (watch 0, 24 open hours): median 6.5 ms, p95 9.2 ms over 60 solves
- build wall time 185 s on 12 workers

## Flags

- Sites are archetypes at hubs and load zones (no crosswalk tonight, V3-D11): 40% the FD-4322 default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; POI = PV AC, 25% at the 1.2x variant; AC coupling only (C3-D15).
- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).
- **The sponge and its filter are inert in these packs**: AC coupling with POI >= PV AC leaves no PV the meter cannot export (clippable MWh, every pack: ercot-hybrid-v3-train 0.0, ercot-hybrid-v3-eval 0.0, ercot-hybrid-v3-rtcb 0.0, ercot-hybrid-v3-showcase 0.0, fixtures-hybrid 0.0), so the sponge equals idle (0.2) and never comes within 3% of the anchor. Clipping is computed exactly where it exists (continuous MW; tests on dc-coupled and POI < PV AC sites). Whether to add such sites is Edgar's call (decision 2).
- Anchor soft solves: after watch 0 the reserves tier keeps the DA awards, and realized drift can leave an hour whose awards no move can back; the hard MILP is then infeasible, the soft one minimises the shortfall, and the repair walk turns the entries the Session refuses into the governor's move (C3-D17), so the anchor's commits are never refused. A hard solution is never repaired (tested).
- Regulation drift is a seeded draw, not ERCOT telemetry; deployments use frac 1.0 (stress case).
- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.
