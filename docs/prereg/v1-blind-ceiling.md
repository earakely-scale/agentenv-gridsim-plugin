# GridSimEnv v1 blind tier: ceiling check (pre-registration)

**A diagnostic, not a claim.** Committed and pushed before any forecaster is fitted. CPU only, no LLM calls, no new
model runs: Sol's schedules are the stored ones. It decides FD-4420's tier choice: can a forecaster that uses only what
the blind prompt shows, planned with the exact DP, beat GPT-6.1 Sol on hindsight capture? If not, the target claim ("a
trained 4B out-earns Sol bidding tomorrow") cannot be won on the plain blind tier, and the next step is an "informed
blind" tier.

## The bar
- **Sol** (stored schedules, re-graded with `gridsim_core.grade`):
  - blind eval-2025: the 300 tasks of `ercot-dam-v1-eval` with `tags.blind_eval`, column C of the v1 board, `full`
    bundle (sweeps `v1-board-sol-blind` + `-amend`);
  - fresh: the 331 tasks of `ercot-dam-v1-fresh-2026-10-blind`, path B (`eval_sol.jsonl.gz`).
- **Blind anchor:** `refs.blind.p_anchor = max(P_persist, P_ridge)` per task, where persistence-DP plans on D-1's prices
  and ridge-DP on ridge-v1's forecast, both settled on day D. **The max is taken per task on realized profit, so the
  anchor is an oracle selector chosen in hindsight, not an information-matched rule.** It is stronger than either rule
  (fresh: anchor 0.919 vs ridge-DP 0.885, persistence-DP 0.871). Sol is compared with the anchor only for context; the
  verdict is against Sol.
- **Reference values, recomputed before this commit** (C on the repo's scale / raw capture):

| pack | Sol | anchor | persistence-DP (raw) | ridge-DP (raw) |
|---|---|---|---|---|
| blind eval-2025 (300) | 0.9165 / 0.8956 | 0.9204 / 0.9005 | 0.8525 | 0.7474 |
| fresh 2026-10 (331) | 0.9264 / 0.9080 | 0.9192 / 0.8989 | 0.8388 | 0.8563 |

## Metric
- **Primary: C = clip(0.2 + 0.8 x, 0, 1)**, x = (P − P_idle) / (P_opt − P_idle), the hindsight capture as every
  published GridSimEnv table computes it (`grade()["r_opt"]`; Sol 0.926 on fresh, 0.9165 on eval-2025).
- **Secondary: raw capture x**, unclipped (FD-4420 quotes it: Sol 0.896, anchor 0.901 on eval-2025). Gaps in C are 0.8×
  gaps in x except where C clips at 0 (x < −0.25).

## Information set (what the blind prompt shows, `gridsim_core.prompt.situation(task, "blind")`)
The date (so weekday, month, day of year, year and US federal holidays, all computed from the date), the settlement
point and its kind, the battery, D-1's 24 DAM prices and D-7..D-1's at that point. Nothing else. Every
information-matched forecaster below uses only these.

## Data and splits
- **Price history:** the parsed NP4-180-ER cache (`cache/parsed/dam-a5c0b0fae22b11ea.json.gz`, clean point-days
  2014-01-01..2026-10-17, DST days and non-24-hour days dropped), plus `data/ercot-dam-v1-fresh-2026-10/dam_spp_api.csv.gz`
  for 2026-10-18..26 (used only to build inputs, never as a training target).
- **Training targets:** point-days that `build_pack.split` assigns to `train` (2014–2024 minus the every-10th eval-iid
  dates and the showcase dates), dedup-kept as ridge-v1's were, with all 7 lag days present. **No eval-2025, eval-iid,
  rtcb or fresh day is ever a training target.** Lag inputs may come from any earlier date.
- **Tuning holdout (2024):** models are fitted on training targets before 2024-01-01 and scored on
  - forecast error over the 2024 training point-days, and
  - C over the 922 `ercot-dam-v1-train` tasks dated 2024 with `tags.blind_eval` (286 days).

  Every hyperparameter, ensemble weight and the final method choice is made here. Final models are refitted on all
  2014–2024 training targets with the chosen settings and then scored once on blind eval-2025 and fresh.

## Methods (each predicts day D's 24 hourly prices; each forecast is planned with `dp.dp_schedule` on the task's battery and graded on realized prices with `grade()`)
- **(a) ridge-v1**, as stored in `data/ridge-v1.json` (reference; its holdout score uses a refit on pre-2024 targets).
- **(b) LightGBM**, one model with the hour as a feature. Features: D-1..D-7 at the same hour; D-1 at the neighbouring
  hours; D-1 and 7-day daily stats (mean, std, min, max); the 7-day mean at the hour; weekday of D, month, day of year
  (sin/cos), year, holiday flags for D and D-1; the point (categorical) and its kind. Tuned on the holdout: the
  objective (L2, Huber), the target (price, or price minus the 7-day mean at the hour), leaves, min child samples and
  the number of rounds.
- **(c) MLP** (scikit-learn `MLPRegressor`), 24 outputs from the 168 lagged prices plus calendar and point one-hots.
  Tuned on the holdout: the price transform (scaled raw, or asinh with a mean correction), width and L2 penalty.
- **(d) Ensemble:** a convex combination of persistence (D-1), (a), (b) and (c), weights on a 0.1 simplex grid chosen
  by holdout C.
- **Scenario variant of each:** 20 scenarios = the forecast plus residual day-vectors drawn (seeded by task id) from that
  method's out-of-sample 2024 residuals (pre-2024 fit) within ±1 calendar month of D. The plan maximises the mean profit
  over the scenarios exactly: settlement is linear in price and the schedule has no recourse, so this is the DP on the
  scenario-mean prices with the end-shortfall penalty at its scenario mean. It differs from the point plan only through
  the residuals' conditional mean, the penalty and sampling noise.
- **The best information-matched method** is the one of these 8 (4 × point/scenario) with the highest mean C on the
  2024 holdout, fixed before eval-2025 or fresh is scored. The others are reported, not used for the verdict.

## Exploratory, outside the verdict (labelled as such in every table)
- **Extended inputs:** LightGBM (b) plus all 15 points' D-1 prices. This uses more than the blind prompt shows.
- **Informed blind estimate:** LightGBM with ERCOT's as-issued day-D system load, wind and solar forecasts from the v4
  store (`ercot_load`, `ercot_wind`, `ercot_solar`, the last vintage issued before 10:00 CPT on D-1, the DAM bid
  deadline), against the same LightGBM without them, both fitted only on 2023-12-12..2024-12-31 training targets (the
  span those kinds cover) and compared paired on the eval-2025 tasks the store covers. If the store's HRRR-based desk
  kinds (2021+) are readable, the same comparison with a 2021–2024 fit is added.

## Report
- **Forecast error** per method: MAE and RMSE over all hours, the 4 dearest and the 4 cheapest realized hours of each
  task day, on the holdout, eval-2025 and fresh (unique point-days of each pack).
- **C and x per method**, with a day-block bootstrap 95% CI (10,000 resamples, seed 0, every task of a drawn day,
  task-weighted), as the fresh-2026-10 tables do.
- **Paired gaps** method − Sol and method − anchor (day-block CI), and the share of tasks where the method's profit beats
  Sol's.
- A chart of C by method with CIs and Sol / anchor reference lines.

## Decision rule (fixed now)
The plain blind tier **has headroom** if the best information-matched method (chosen on the 2024 holdout) has
1. a paired C gap over Sol on blind eval-2025 whose day-block 95% CI lies wholly above 0, **and**
2. on the fresh days, a paired mean gap ≥ −0.01 whose day-block CI is not wholly below 0.

Otherwise it has **no shown headroom**, and the recommendation is the "informed blind" tier, with the exploratory
estimate of what ERCOT's as-issued forecasts add. Methods that beat Sol only when picked on eval-2025 or fresh are
reported as post hoc and do not change the verdict.

## Prior (stated so the outcome can be checked against it)
The best information-matched method lands between ridge-DP and the anchor: C 0.89–0.92 on fresh, and within −0.02 to
+0.01 of Sol on eval-2025, not shown above 0. Expected verdict: no shown headroom, so "informed blind". The scenario
variant changes C by less than ±0.005. ERCOT's load/wind/solar forecasts add something (+0.01 to +0.03 C), with wide
uncertainty because their training window is one year.

## Rules
- Nothing is tuned on eval-2025, eval-iid, rtcb or fresh; each final model is scored once on each.
- Code, outputs and any deviation (as a dated amendment below) go to `results/blind-ceiling/`, published whatever the
  outcome.

## Amendments

### Amendment 1 (2026-10-27 00:48 UTC): an extended search, reported separately; the registered analysis is unchanged
- **Disclosure.** A pipeline smoke test (2 L2 LightGBM configs capped at 100 rounds, 2 MLP configs with one seed, an
  ensemble grid of step 0.5) scored blind eval-2025 and fresh at about 00:34 UTC, before the full tuning run. Its C
  (eval-2025 / fresh): LightGBM 0.898 / 0.903, ensemble 0.897 / 0.894, against Sol's 0.9165 / 0.926. No registered
  setting changed because of it.
- **The registered analysis ran as written.** Tuning finished at 00:47 UTC (holdout best: the ensemble, point plan,
  C 0.905); the final scoring started at 00:48 UTC. Its verdict is this pre-registration's verdict. This amendment is
  written before its eval-2025 or fresh numbers are read.
- **Why extend.** On the 2024 holdout, LightGBM's best checkpoint is the grid's lowest (25 rounds), and every L2
  objective loses to Huber (heavy tails in 2014–2023). The ceiling question asks whether *any* information-matched
  forecaster beats Sol, so a stronger search is worth reporting.
- **Extended search, all choices on the same 2024 holdout:**
  - **LightGBM, Huber only:** round checkpoints add 5, 10 and 15; a recency weight 0.5^((Y_last − year) / h) with
    h ∈ {1, 2, 4, ∞} years (Y_last = the fit's last year).
  - **m7-DP:** the DP on the D-7..D-1 hourly mean, a rule on the blind inputs only. Reported, and added as an ensemble
    member.
  - **Ensemble** over persistence, m7, ridge, the extended LightGBM and the registered MLP, 0.1 simplex, by holdout C.
  - Point plans only: the registered holdout put every scenario variant 0.05–0.16 C below its point plan.
- **Reporting.** The extended best (highest holdout C) is scored once on eval-2025 and fresh and judged by the same
  decision rule, as "extended search (Amendment 1)". If it disagrees with the registered verdict, the README reports
  both; a positive extended result is an existence proof of headroom found after registration, and says so.
