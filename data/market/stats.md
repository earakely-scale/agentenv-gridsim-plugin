# v5 market days: fidelity

Op days 2023-12-11..2026-08-25: 982 full rows, 3 light rows; dropped 5 DST days, 2 without a public series, 0 parse errors, 0 without a disclosure. Fidelity is the copper-plate re-clear of every real offer against NP4-523-CD λ in non-scarcity hours (λ < $100), within $5 or 10%; the simplification error is the shipped (≤ 64-point) replay against the full re-clear.

| Days | Full rows | raw within_ns ≥ 0.5 (V5-P2) | ≥ 0.75 | ≥ 0.9 (plan) | median within_ns | median MAE_ns $ | simplify err p95 $ | max $ |
|---|---|---|---|---|---|---|---|---|
| all | 982 | 842 (86%) | 444 | 39 | 0.71 | 5.13 | 1.43 | 57.49 |
| 2023 | 21 | 21 (100%) | 16 | 1 | 0.75 | 3.45 | 0.22 | 0.69 |
| 2024 | 364 | 352 (97%) | 227 | 28 | 0.75 | 4.47 | 2.04 | 57.49 |
| 2025 | 361 | 293 (81%) | 137 | 8 | 0.68 | 5.76 | 1.02 | 5.00 |
| 2026 | 236 | 176 (75%) | 64 | 2 | 0.62 | 5.39 | 1.50 | 24.70 |
| pre-RTC+B | 721 | 648 (90%) | 375 | 36 | 0.75 | 5.00 | 1.44 | 57.49 |
| RTC+B (2025-12-05+) | 261 | 194 (74%) | 69 | 3 | 0.62 | 5.45 | 1.23 | 24.70 |

Notes on the inputs:

- NP4-523-CD λ comes from the API archive's daily CSVs (2022-01-01..2026-10-24); on the 25,127 hours it shares with
  the query endpoint (from 2023-12-13) it differs by at most $0.0001 (rounding).
- 2025-12-05 and 2025-12-06 (the first RTC+B days) drop: EIA-930 ERCO has no data for them (zeros in EIA's own
  Region_TEX file, gaps in the BALANCE files), so their light rows are missing and the tasks around them drop too.
- The simplification error is ≤ $1.43 on 95% of days and $57.49 on the worst; the shipped curves, not the full ones,
  are what every clear uses.

**The archive reaches back further than the contract assumed (not shipped, V5-P1).** The API's NP3-966-ER archive
holds every op day from at least 2022-01-01 (posted 2022-03-01), not only from 2023-12-11. Built with the same parser
for this table only:

| Days | Full rows | raw within_ns ≥ 0.5 | ≥ 0.75 | ≥ 0.9 | median within_ns | median MAE_ns $ | simplify err p95 $ |
|---|---|---|---|---|---|---|---|
| 2022-01-01..2023-12-10 | 704 | 518 (74%) | 218 | 29 | 0.65 | 6.08 | 5.17 |
| 2022 | 363 | 204 (56%) | 45 | 1 | 0.50 | 7.30 | 4.88 |
| 2023 (to 12-10) | 341 | 314 (92%) | 173 | 28 | 0.75 | 5.06 | 5.85 |

0 parse errors on 1,686 op days in all (2022-01-01..2026-08-25); the raw zips are not redistributed.

## Packs (scripts/build_market_pack.py)

### gridsim-market-train

- dates 318; day checks dropped {'missing day row': 10, 'fidelity': 8, 'pool': 1}; passed 299
- drawn tasks 8073: {'headroom': 2175, 'impact': 3547, 'kept': 2351} (headroom = V5-P11, impact = V5-P12 b)
- shipped 2351 tasks on 151 dates (2303 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 1622, 1: 435, 2: 148, 3: 20, 4: 30, 5: 42, 6: 15, 7: 12, 8: 7, 9: 20}; ≥ $2: {1: 923, 2: 505, 3: 255, 4: 117, 5: 127, 6: 106, 7: 104, 8: 61, 9: 64, 10: 68, 11: 13, 12: 5, 14: 1, 15: 2}

### gridsim-market-eval

- dates 334; day checks dropped {'missing day row': 12, 'fidelity': 55}; passed 267
- drawn tasks 1602: {'headroom': 298, 'kept': 1304} (headroom = V5-P11, impact = V5-P12 b)
- shipped 200 tasks on 200 dates (194 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 186, 1: 2, 2: 4, 3: 2, 4: 2, 5: 1, 6: 2, 11: 1}; ≥ $2: {0: 130, 1: 29, 2: 13, 3: 4, 4: 5, 5: 4, 6: 2, 7: 5, 8: 2, 9: 2, 10: 1, 11: 1, 14: 1, 18: 1}

### gridsim-market-rtcb

- dates 253; day checks dropped {'missing day row': 16, 'fidelity': 56}; passed 181
- drawn tasks 1086: {'kept': 647, 'headroom': 439} (headroom = V5-P11, impact = V5-P12 b)
- shipped 153 tasks on 153 dates (147 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 150, 1: 1, 5: 2}; ≥ $2: {0: 125, 1: 16, 2: 2, 3: 3, 4: 1, 6: 4, 7: 2}

### gridsim-market-showcase

- dates 6; day checks dropped {}; passed 6
- drawn tasks 6: {'kept': 4, 'headroom': 2} (headroom = V5-P11, impact = V5-P12 b)
- shipped 6 tasks on 6 dates (4 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 1, 1: 1, 4: 1, 5: 1, 21: 2}; ≥ $2: {1: 1, 9: 1, 16: 1, 20: 1, 21: 1, 24: 1}

