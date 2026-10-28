# v3 hybrid packs: counts, filters and baselines

Built by `scripts/build_hybrid_pack.py` (2026-10-25). References: `gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.

## Packs

| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | 2400 | A 1489, B 911 | 2021-01-01..2024-12-31 | 1004 | 301 | 1828 |
| `ercot-hybrid-v3-eval` | 300 | B 300 | 2025-01-01..2025-11-28 | 89 | 12 | 264 |
| `ercot-hybrid-v3-rtcb` | 200 | C 200 | 2025-12-05..2026-09-30 | 42 | 17 | 172 |
| `ercot-hybrid-v3-showcase` | 4 | B 3, C 1 | 2023-08-10..2026-01-26 | 3 | 2 | 1 |
| `fixtures-hybrid` | 20 | A 8, B 8, C 4 | 2021-04-23..2026-08-19 | 6 | 4 | 15 |

## Filters (the v3 plan)

Thresholds: P_anchor - P_idle >= $500 in both tiers; v1's low-spread drop (energy-tier anchor - idle >= $22 per MW of battery); sponge reward < 0.97 (the sponge within 3% of the anchor); and, extending that rule (C3-D16), every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP below 0.97 against the reserves anchor. Uri and every showcase day +/-3 days are out of every split; DST days and days without 24 hourly inputs are dropped.

Refilled with --refill after the rules-3.2 references (C3-D19, C3-D20): the days that failed a filter were dropped and the build's draw continued over the candidates that pass, the surviving days unchanged (train 188 dropped, 188 drawn (2400 of 2400); eval 48 dropped, 48 drawn (300 of 300); rtcb 28 dropped, 28 drawn (200 of 200); eval strata cutoffs $1,926.81 and $3,682.01, as built).

| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Fail baseline >= 0.97 | Eligible | Kept |
|---|---|---|---|---|---|---|---|
| train | 4239 | 56 | 439 | 32 | 669 | 3199 | 2400 |
| eval | 1328 | 24 | 88 | 22 | 510 | 745 | 300 |
| rtcb | 584 | 23 | 95 | 12 | 206 | 312 | 200 |

## Baselines and references (means over each pack)

| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours | Anchor soft solves (share of watches) | Anchor entries repaired |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | energy | 16787.2885 | 0.4763 | 0.2453 | 0.76 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-train` | reserves | 47109.9529 | 0.5937 | 0.2238 | 0.4298 | 0.6804 | 0.5306 | 52245.8323 | 6.7654 | 0.2726 | 2.1321 |
| `ercot-hybrid-v3-eval` | energy | 9529.2454 | 0.4567 | 0.265 | 0.9546 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-eval` | reserves | 12680.4271 | 0.4529 | 0.2537 | 0.7841 | 0.3436 | 0.8207 | 6192.6591 | 4.7233 | 0.1001 | 0.3133 |
| `ercot-hybrid-v3-rtcb` | energy | 6963.1617 | 0.4027 | 0.2929 | 0.9321 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-rtcb` | reserves | 9768.5972 | 0.4045 | 0.2758 | 0.7413 | 0.3383 | 0.7958 | 6063.8869 | 4.515 | 0.2271 | 0.44 |
| `ercot-hybrid-v3-showcase` | energy | 220608.0074 | 0.4897 | 0.2 | 0.9311 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `ercot-hybrid-v3-showcase` | reserves | 252595.4458 | 0.3756 | 0.4 | 0.771 | 0.3137 | 0.8083 | 239003.3834 | 4.25 | 0.2667 | 1.0 |
| `fixtures-hybrid` | energy | 54039.6889 | 0.5024 | 0.2502 | 0.8627 | - | - | 0.0 | 0.0 | 0.0 | 0.0 |
| `fixtures-hybrid` | reserves | 61632.416 | 0.5197 | 0.283 | 0.5987 | 0.5498 | 0.6841 | 73125.4064 | 5.65 | 0.3233 | 1.35 |

## Energy tier by POI (PV AC / POI): the solar sponge and v2 energy-only against the energy anchor

| Pack | POI | Tasks | Clippable MWh/day | Sponge | v2 energy-only | Anchor - idle ($) |
|---|---|---|---|---|---|---|
| `ercot-hybrid-v3-train` | at or above PV AC | 1434 | 0.0 | 0.2 | 0.8222 | 17489.2919 |
| `ercot-hybrid-v3-train` | oversized | 966 | 69.4586 | 0.3125 | 0.6675 | 15745.1841 |
| `ercot-hybrid-v3-eval` | at or above PV AC | 196 | 0.0 | 0.2 | 0.9747 | 9722.1612 |
| `ercot-hybrid-v3-eval` | oversized | 104 | 85.3287 | 0.3874 | 0.9167 | 9165.6734 |
| `ercot-hybrid-v3-rtcb` | at or above PV AC | 119 | 0.0 | 0.2 | 0.9853 | 7134.657 |
| `ercot-hybrid-v3-rtcb` | oversized | 81 | 92.541 | 0.4293 | 0.854 | 6711.2117 |
| `ercot-hybrid-v3-showcase` | at or above PV AC | 4 | 0.0 | 0.2 | 0.9311 | 220608.0074 |
| `fixtures-hybrid` | at or above PV AC | 14 | 0.0 | 0.2 | 0.9119 | 22671.3862 |
| `fixtures-hybrid` | oversized | 6 | 157.2573 | 0.3674 | 0.7479 | 127232.3953 |

## Regulation drift source (V3-D8)

| Pack | ercot | ercot+modelled | modelled |
|---|---|---|---|
| `ercot-hybrid-v3-train` | 703 | 0 | 1697 |
| `ercot-hybrid-v3-eval` | 300 | 0 | 0 |
| `ercot-hybrid-v3-rtcb` | 164 | 0 | 36 |
| `ercot-hybrid-v3-showcase` | 2 | 0 | 2 |
| `fixtures-hybrid` | 9 | 0 | 11 |

## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise does not move a day between strata)

| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |
|---|---|---|---|---|
| low | 100 | 226..1919 | 0.3047 | 0.8809 |
| mid | 100 | 1938..3664 | 0.3342 | 0.8224 |
| high | 100 | 3682..26618 | 0.392 | 0.7588 |

## Timing

- references: 394.7 ms per task-core (both tiers; about 15 MILP solves, 2 hindsight MILPs and 2 LPs per task)
- MILP solve (watch 0, 24 open hours): median 6.6 ms, p95 8.4 ms over 60 solves
- build wall time 208 s on 12 workers

## Flags

- Sites are archetypes at hubs and load zones (no crosswalk, V3-D11): 40% the v3 plan's default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; POI = PV AC, 20% at the 1.2x variant and 40% below PV AC (PV AC / POI one of 1.11, 1.25, 1.4; V3-D12); AC coupling only (C3-D15).
- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).
- Oversized sites clip at the meter (clippable MWh, every pack: ercot-hybrid-v3-train 67097, ercot-hybrid-v3-eval 8874, ercot-hybrid-v3-rtcb 7496, ercot-hybrid-v3-showcase 0, fixtures-hybrid 944), so the energy tier tests charging from clipped solar and the sponge is no longer idle.
- Anchor soft solves: after watch 0 the reserves tier keeps the DA awards, and realized drift can leave an hour whose awards no move can back; the hard MILP is then infeasible, the soft one minimises the shortfall, and the repair walk turns the entries the Session refuses into the governor's move (C3-D17), so the anchor's commits are never refused. A hard solution is never repaired (tested).
- Regulation drift is ERCOT's storage fleet deployment (60-Day SCED Disclosure) on days it covers (from 2023-10-12) and the imbalance-driven fallback before (data/hybrid/reg_deploy.md); deployments use frac 1.0 (stress case).
- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.
