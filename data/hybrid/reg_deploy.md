# v3 regulation drift: ERCOT's storage fleet deployment and the fallback

Built by `scripts/build_reg_drift.py` (2026-10-24) from the reduced 60-Day SCED Disclosure days (`scripts/fetch_reg_deployment.py`). Loader: `gridsim_core.hybrid_inputs.reg_hourly`.

## Source

ERCOT publishes no regulation deployment or ACE series. Its public API lists 120 products; the closest are the AS deployment factors (NP5-520-ER, NP5-526-CD, NP5-528-CD), which are RUC planning inputs from 2025-12-05, not deployments. The 60-Day SCED Disclosure (NP3-965-ER) gives, per resource and disclosed SCED run, the telemetered net output, the base point and the RegUp/RegDn responsibility (awards from RTC+B). Regulation is the gap between a carrier's output and its base point, so the energy storage fleet's summed gap over its responsibility is its deployed fraction. Storage carries most of ERCOT's regulation and tracks base points closely, so only storage carriers are summed (online storage without a regulation award is kept as a control in the reduced days).

- Coverage: 2023-10-12..2026-08-25, 1039 operating days (2023 81, 2024 366, 2025 365, 2026 227); 1036 with every hour measured. Before 2023-10-12 (the archive starts with postings on 2023-12-11) the fallback is used.
- Sampling: one SCED run per 15 minutes is disclosed before RTC+B (2025-12-05) and every run after.
- Signal check: the carriers deviating more than 0.5 MW agree in sign on 86% of them per snapshot on average (a fleet-wide LFC signal, not tracking noise).
- Reference base point: the target the base points imply at the run's time, two thirds of the way from the previous disclosed base point to the run's own before RTC+B; the previous SCED run's base point from RTC+B. On RTC+B days, the hourly fractions from the first run per 15 minutes against the base point about 15 minutes old reproduce every-run fractions with correlation (up/down) bp3 0.715/0.718 (MAE 0.0883/0.1015), bp 0.706/0.705 (MAE 0.083/0.0941), i3 0.764/0.764 (MAE 0.0748/0.084) (bp3: 15 minutes back; bp: the run's own; i3: the implied target).

## Measured

- Mean fractions of the award: RegUp 0.1683, RegDn 0.2045 (the projection's `reg_drift_mean` on measured days).
- Correlation of the hourly net (up - dn) with RT - DA at HB_HUBAVG: 0.077.
- By hour (HE01..HE24) RegUp: 0.15 0.13 0.13 0.14 0.16 0.16 0.16 0.17 0.13 0.13 0.11 0.14 0.16 0.18 0.18 0.19 0.21 0.23 0.23 0.25 0.20 0.17 0.17 0.14
- By hour RegDn: 0.22 0.25 0.24 0.22 0.21 0.18 0.18 0.18 0.27 0.28 0.28 0.24 0.22 0.20 0.19 0.18 0.15 0.14 0.15 0.14 0.17 0.20 0.20 0.22

## Fallback (no measured series: 2021-01-01 until the series starts)

`up = up_max * tanh(max(RT - DA, 0) / scale), dn = dn_max * tanh(max(DA - RT, 0) / scale), each plus N(0, noise_sd) clipped to [0, 1]; RT and DA are the task's settlement point's hourly prices`: up_max 0.2031, dn_max 0.2256, scale $1/MWh, noise sd 0.02, seeded per task. Fit: least squares over 24792 measured hours at HB_HUBAVG, scale on a grid [1, 2, 3, 5, 10, 20, 30, 50, 100, 200]. Expected fractions over 2021..2023-10-12 at HB_HUBAVG: RegUp 0.067, RegDn 0.1434 (the projection's `reg_drift_mean` on modelled days). Labelled modelled in every task row.

| RT - DA ($/MWh) | Hours | Measured up | Measured dn | Model up | Model dn |
|---|---|---|---|---|---|
| -inf..-100 | 166 | 0.233 | 0.167 | 0.0 | 0.226 |
| -100..-20 | 1031 | 0.191 | 0.181 | 0.0 | 0.226 |
| -20..-5 | 6033 | 0.151 | 0.224 | 0.0 | 0.226 |
| -5..0 | 7613 | 0.151 | 0.216 | 0.0 | 0.191 |
| 0..5 | 5684 | 0.164 | 0.21 | 0.165 | 0.0 |
| 5..20 | 3175 | 0.212 | 0.162 | 0.203 | 0.0 |
| 20..100 | 953 | 0.246 | 0.132 | 0.203 | 0.0 |
| 100..inf | 137 | 0.26 | 0.153 | 0.203 | 0.0 |

The measured fleet deploys in both directions within most hours, so the one-sided fallback understates the gross deployment in the direction against the spread; it is the rule V3-D8 asked for, fitted to the measured fraction in the spread's direction.
