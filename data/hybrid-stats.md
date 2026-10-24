# v3 hybrid packs: counts, filters and baselines

Built by `scripts/build_hybrid_pack.py` (2026-10-24). References: `gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.

## Packs

| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | 2400 | A 1458, B 942 | 2021-01-01..2024-12-31 | 983 | 309 | 1819 |
| `ercot-hybrid-v3-eval` | 300 | B 300 | 2025-01-01..2025-11-28 | 88 | 13 | 255 |
| `ercot-hybrid-v3-rtcb` | 200 | C 200 | 2025-12-06..2026-09-29 | 46 | 24 | 163 |
| `ercot-hybrid-v3-showcase` | 4 | B 3, C 1 | 2023-08-10..2026-01-26 | 3 | 2 | 1 |
| `fixtures-hybrid` | 20 | A 8, B 9, C 3 | 2021-04-23..2026-08-19 | 8 | 5 | 14 |

## Filters (FD-4322)

Thresholds: P_anchor - P_idle >= $500 in both tiers; v1's low-spread drop (energy-tier anchor - idle >= $22 per MW of battery); sponge reward < 0.97 (the sponge within 3% of the anchor). Uri and every showcase day +/-3 days are out of every split; DST days and days without 24 hourly inputs are dropped.

| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Eligible | Kept |
|---|---|---|---|---|---|---|
| train | 4239 | 41 | 464 | 15 | 3764 | 2400 |
| eval | 1328 | 19 | 95 | 9 | 1222 | 300 |
| rtcb | 584 | 19 | 111 | 7 | 471 | 200 |

## Baselines and references (means over each pack)

| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours |
|---|---|---|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | energy | 17633.7677 | 0.4628 | 0.2 | 0.8256 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-train` | reserves | 52306.8572 | 0.687 | 0.2 | 0.4461 | 0.766 | 0.5064 | 54689.5148 | 7.095 |
| `ercot-hybrid-v3-eval` | energy | 9635.4997 | 0.4266 | 0.2 | 0.9883 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-eval` | reserves | 11995.7876 | 0.4721 | 0.2 | 0.8183 | 0.4956 | 0.8258 | 5566.3901 | 4.4467 |
| `ercot-hybrid-v3-rtcb` | energy | 7001.3829 | 0.3665 | 0.2 | 0.9809 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-rtcb` | reserves | 9196.4518 | 0.4177 | 0.2 | 0.7984 | 0.3729 | 0.8111 | 4869.425 | 3.81 |
| `ercot-hybrid-v3-showcase` | energy | 220608.0074 | 0.4897 | 0.2 | 0.9311 | - | - | 0.0 | 0.0 |
| `ercot-hybrid-v3-showcase` | reserves | 243465.4846 | 0.4814 | 0.2 | 0.7555 | 0.7379 | 0.8092 | 238422.3992 | 2.25 |
| `fixtures-hybrid` | energy | 45368.3543 | 0.4859 | 0.2 | 0.9275 | - | - | 0.0 | 0.0 |
| `fixtures-hybrid` | reserves | 118750.9163 | 0.6082 | 0.2 | 0.6174 | 0.6918 | 0.6486 | 142156.6791 | 5.05 |

## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise does not move a day between strata)

| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |
|---|---|---|---|---|
| low | 100 | 364..1712 | 0.4631 | 0.8858 |
| mid | 100 | 1720..3402 | 0.483 | 0.8229 |
| high | 100 | 3417..37000 | 0.5408 | 0.7687 |

## Timing

- references: 297.6 ms per task-core (both tiers; about 15 MILP solves, 2 hindsight MILPs and 2 LPs per task)
- MILP solve (watch 0, 24 open hours): median 6.5 ms, p95 8.3 ms over 60 solves
- build wall time 157 s on 12 workers

## Flags

- Sites are archetypes at hubs and load zones (no crosswalk tonight, V3-D11): 40% the FD-4322 default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; POI = PV AC, 25% at the 1.2x variant; AC coupling only (C3-D15).
- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).
- Regulation drift is a seeded draw, not ERCOT telemetry; deployments use frac 1.0 (stress case).
- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.
