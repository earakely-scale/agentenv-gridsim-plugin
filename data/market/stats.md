# v5 market days: fidelity

Op days 2022-01-01..2026-08-25: 1686 full rows, 1 light rows; dropped 9 DST days, 2 without a public series (2025-12-05, 2025-12-06), 0 parse errors, 1 without a disclosure. Fidelity is the copper-plate re-clear of every real offer against NP4-523-CD λ in non-scarcity hours (λ < $100), within $5 or 10%; the simplification error is the shipped (≤ 64-point) replay against the full re-clear. A task needs raw within_ns ≥ 0.7 on its op day (V5-P2).

| Days | Full rows | raw within_ns ≥ 0.5 | ≥ 0.7 (V5-P2) | ≥ 0.9 (plan) | median within_ns | median MAE_ns $ | simplify err p95 $ | max $ |
|---|---|---|---|---|---|---|---|---|
| all | 1686 | 1361 | 812 (48%) | 68 | 0.67 | 5.47 | 2.81 | 57.49 |
| 2022 | 363 | 205 | 65 (18%) | 1 | 0.50 | 7.33 | 4.49 | 24.62 |
| 2023 | 362 | 335 | 229 (63%) | 29 | 0.75 | 4.91 | 5.78 | 27.23 |
| 2024 | 364 | 352 | 263 (72%) | 28 | 0.75 | 4.47 | 2.04 | 57.49 |
| 2025 | 361 | 293 | 175 (48%) | 8 | 0.68 | 5.76 | 1.02 | 5.00 |
| 2026 | 236 | 176 | 80 (34%) | 2 | 0.62 | 5.39 | 1.50 | 24.70 |
| pre-RTC+B | 1425 | 1167 | 725 (51%) | 65 | 0.71 | 5.48 | 3.06 | 57.49 |
| RTC+B (2025-12-05+) | 261 | 194 | 87 (33%) | 3 | 0.62 | 5.45 | 1.23 | 24.70 |

The store: 56 month files, 22.1 MB in git (data/market/days, 2024-05 on: every month an eval, rtcb or showcase floor reads) and 19.5 MB in the overflow (cache/market/days, 2022-01..2024-04: read by train floors only; the Hub dataset's raw/v5-market/days, checked against the manifest's sha256 per month).

## Packs (scripts/build_market_pack.py)

### gridsim-market-train

- dates 1089; day checks dropped {'missing day row': 96, 'fidelity': 461, 'pool': 76, 'missing disclosure': 3}; passed 453
- drawn tasks 12231: {'kept': 3777, 'headroom': 3689, 'impact': 4765} (headroom = V5-P11, impact = V5-P12 b)
- shipped 3777 tasks on 229 dates (3708 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 2121, 1: 467, 2: 202, 3: 112, 4: 107, 5: 108, 6: 150, 7: 133, 8: 66, 9: 156, 10: 81, 11: 50, 12: 16, 15: 6, 18: 2}; ≥ $2: {1: 947, 2: 559, 3: 299, 4: 159, 5: 174, 6: 242, 7: 278, 8: 223, 9: 326, 10: 193, 11: 174, 12: 69, 13: 52, 14: 19, 15: 21, 16: 4, 17: 12, 18: 6, 19: 6, 20: 6, 21: 6, 22: 2}

### gridsim-market-eval

- dates 334; day checks dropped {'missing day row': 12, 'fidelity': 159}; passed 163
- drawn tasks 978: {'headroom': 202, 'kept': 776} (headroom = V5-P11, impact = V5-P12 b)
- shipped 289 tasks on 147 dates (284 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 276, 1: 3, 3: 3, 4: 3, 5: 1, 6: 3}; ≥ $2: {0: 194, 1: 44, 2: 23, 3: 5, 4: 5, 5: 3, 6: 1, 7: 5, 8: 2, 9: 3, 10: 1, 11: 2, 14: 1}

### gridsim-market-rtcb

- dates 253; day checks dropped {'missing day row': 16, 'fidelity': 159}; passed 78
- drawn tasks 468: {'kept': 255, 'headroom': 213} (headroom = V5-P11, impact = V5-P12 b)
- shipped 65 tasks on 65 dates (62 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 64, 5: 1}; ≥ $2: {0: 60, 1: 2, 6: 2, 7: 1}

### gridsim-market-showcase

- dates 6; day checks dropped {}; passed 6
- drawn tasks 6: {'kept': 4, 'headroom': 2} (headroom = V5-P11, impact = V5-P12 b)
- shipped 6 tasks on 6 dates (4 also clear the floor-day anchor filter); impact hours ≥ $5: {0: 1, 1: 1, 4: 1, 5: 1, 21: 2}; ≥ $2: {1: 1, 9: 1, 16: 1, 20: 1, 21: 1, 24: 1}
