# GridSimEnv v5 pilot: pre-registration (GPT-6.1 Sol, The Market Floor)

Committed on `v5-preview` before the first model episode of the pilot, the smoke included. Nothing below changes after a
run starts, and nothing is rerun to improve a score. Anything done differently is logged under "Deviations", appended
after the run, with this text left as it is. The pilot gives Edgar v5 numbers and the viewer v5 replays; it is not the
v5 board.

## Code
- Branch `v5-preview` at this commit: lane-v5core 2b2a29e, which holds lane-v5env 9cf6797 (the env, bundles,
  verifier, sweep and report, with lane-v5data 481cfeb's days store merged) and lane C5's fixes after lane E5's review:
  3afc0c6 (the episode's stack in hub prices), 5db4ab3 (eps a share in [0, 1], no valid submit scores 0 on both
  scorings, beats_anchor at 6 decimals, every baseline a legal offer with replay A scaled to A's size, per-tier headroom
  so floor-day plays only `floor_day_ok` floors, the hindsight BR as the SoC-feasible awards delivered as awarded, the
  rows `price_making_gain_usd_per_mw_day` and `impact_usd`, packs rebuilt: eval 200 floors, 194 floor-day eligible, 60
  tagged floor-day, 12 peak) and 2b2a29e (`eps_a`, `eps_mean`). This commit adds only the pre-registration,
  `scripts/pilot_v5_tasks.py` and `scripts/pilot_v5.py`. 722 tests pass; ruff is clean.
- Env `gridsim-market` (gateway, a trigger per watch delivering the day's notices, virtual clock frozen at each watch),
  verifier `gridsim-market-verifier`, agent `gridsim-llm`, run on one EC2 box (c7i.8xlarge, Ubuntu 24.04, local Docker,
  shared with lane P4 in its own checkout, stores and registry prefix) after `agent-env gridsim setup --agent`
  (gridsim-market v2, gridsim-llm v2). At 2b2a29e on the box `scripts/market_e2e.py` passed with no model spend: the
  anchor policy on the bundle's floor-day floor (2026-07-21, 1,160 MW × 2 h) scored R 1.0 at $358,139.24 (the stored
  P_anchor), on its floor-sprint floor (2024-08-20, 580 MW × 2 h) R 1.0 at $494,458.97, and the eight wiring tasks
  (no-play 0, late offer 0.828241, disclosure window 0.2, the five fern floors) passed, problems []. Setup and the e2e
  run again at this commit before the smoke.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  market rules card (`gridsim_core.market_prompt`), 16,384 output tokens a turn, 6 turns and 24 calls a floor-sprint,
  36 turns and 120 calls a floor-day, 3 planning and 6 data calls a watch, 1 h freeze, the other four seats scripted on
  their real offers of the day (`bidders: "scripted"`, `script: "real"`), the ISO replaying the day's real notices
  (floor-day only).
- One run per floor. A run that fails for infrastructure (unscored, not stopped at its cap) is retried by the sweep at
  most twice; every attempt is kept in results.jsonl and reported.
- Both scorings come from the same runs: every floor's grade carries R and the compliant score, and the verifier's
  headline is R for the scored columns (the showcase sweep is graded compliant, as the showcase bundles are). The
  agent's prompt and tools are the same under either scoring.

## Smoke, caps and budget
- **Smoke** (after this commit, before any pilot sweep; never counted): 2 floor-sprint and 2 floor-day floors of
  `gridsim-market-train` picked by the same seeded script (`smoke-sprint`, `smoke-day` below), at the tiers' default
  episode caps ($1.00 floor-sprint, $2.00 floor-day), sweeps `v5-smoke-sprint` (`--cap-usd 2`) and `v5-smoke-day`
  (`--cap-usd 4`).
- **Episode caps** (`GRIDSIM_MAX_COST_USD`, the agent's guard counts tokens): each tier's cap is 4 × the median priced
  cost of that tier's smoke runs, rounded up to the cent. A run stopped at its cap is unscored.
- **Sweep caps** (`--cap-usd`): B = $36 minus the smoke's spend ($4 stays in reserve for amendments) is split across
  the three pilot sweeps in proportion to their expected spend, the column's floors × its tier's smoke median
  (floor-sprint 30, floor-day 10, showcase 6 at the floor-day median). If the expected spend of the three passes B, the
  showcase sweep is dropped and B is split over the other two. A sweep that stops with runs unplayed because its next
  attempt could pass its cap is resumed after all three have stopped, with its cap raised by the unspent part of B
  (the same sweep and runs; the guard still books each running attempt at its episode cap).
- **Total budget $40** across every sweep: smoke, pilot, showcase and amendments.
- **Amendment rule:** each run stopped at its episode cap is run once more at 2 × that cap, in a sweep named after its
  own with `-amend`, and reported as a labelled amendment; the primary numbers are the first sweeps alone. Amendment
  sweeps get $40 minus the spend so far.
- The caps that follow from the smoke are recorded in the status log and in the results' Deviations section as
  "derived", not as deviations.

## Tasks
`scripts/pilot_v5_tasks.py` (seed 5324) draws every column from the packs at this commit; the list with what is known
about each floor before any run is `docs/prereg/v5-pilot-tasks.json`.
- **floor-sprint column (scored, 30 floors of `gridsim-market-eval`):** all 12 peak floors (≥ 2 hours where A's
  full sale moves the hub price by ≥ $5, the pack's `peak` stratum), the floor-day column's base floors, and base floors
  drawn until the column holds 30. Each draw takes the candidate whose month has been drawn least, ties broken by the
  seeded shuffle.
- **floor-day column (scored, reported apart, never pooled with the sprint column):** 10 floors of the pack's floor-day
  subset (`tags.floor_day`, each `floor_day_ok`), 4 peak and 6 base, drawn the same way. Every floor-day floor is also
  in the floor-sprint column, so the two tiers are compared paired on these 10.
- **Display only, never counted:** the six floors of `gridsim-market-showcase` (aug24-0820 and fern-0123 to fern-0127)
  at floor-day, graded compliant as the showcase bundles are. On 2026-01-23 and 01-24 the anchor loses money, so R is
  degenerate there.
- **Smoke, never counted:** `smoke-sprint` and `smoke-day`, 2 floors each of `gridsim-market-train`.
- **Known before any run** (stored references and the baselines played in process at each column's tier; R on the
  anchor scale, idle 0.2, anchor 1.0):
  - floor-sprint, all 30: price-taker R 0.924 (R = 1 on 15), max-withhold 0.193, replay A 0.179, idle 0.2; compliant:
    anchor 0.719, price-taker 0.677, max-withhold 0.100, replay A 0.104, idle 0.103. Anchor hindsight capture 0.687;
    P_anchor − P_idle median $75,519.
  - floor-sprint, 12 peak: price-taker R 0.909 (R = 1 on 4), max-withhold 0.183, replay A 0.193; compliant anchor 0.716,
    price-taker 0.665; anchor capture 0.707. The anchor and the price-taker are awarded different quantities in 2 to 10
    hours of every peak floor (81 hours in all); the anchor earns more than the price-taker on 8 of the 12 and less on 4
    (from −$30.77 to +$133.61 per MW-day).
  - floor-sprint, 18 base: price-taker R 0.934 (R = 1 on 11), max-withhold 0.200, replay A 0.169; compliant anchor
    0.722, price-taker 0.685; anchor capture 0.674.
  - floor-day, all 10 (baselines re-planning the op day as the anchor does): price-taker R 0.990, max-withhold then
    deviate 0.847, replay A 0.852, idle 0.2; compliant anchor 0.800, price-taker 0.795, max-withhold 0.731. Anchor
    capture of the delivered-as-awarded BR 0.957 (above 1 on two floors: the BR does not re-plan). On floor-day the
    op-day re-planner, not the DAM offer, carries most of the score: withholding the whole DAM and arbitraging RT
    physically already scores 0.85.
  - floor-day, 4 peak: price-taker 0.994, max-withhold 0.729; 6 base: price-taker 0.987, max-withhold 0.926.

```
python scripts/pilot_v5_tasks.py sprint --json docs/prereg/v5-pilot-tasks.json
M="--env gridsim-market --models openai/gpt-6.1-sol"
agent-env gridsim sweep run $M --name v5-smoke-sprint --pack gridsim-market-train --tier floor-sprint \
  --tasks "$(python scripts/pilot_v5_tasks.py smoke-sprint)" --cap-usd 2 --parallel 2
agent-env gridsim sweep run $M --name v5-smoke-day --pack gridsim-market-train --tier floor-day \
  --tasks "$(python scripts/pilot_v5_tasks.py smoke-day)" --cap-usd 4 --parallel 2
# CAP_S, CAP_D = 4 x each tier's smoke median; SWEEP_* = B split by floors x median (above)
agent-env gridsim sweep run $M --name v5-pilot-sol --pack gridsim-market-eval --tier floor-sprint \
  --tasks "$(python scripts/pilot_v5_tasks.py sprint)" --cap-usd $SWEEP_S --episode-cap-usd $CAP_S --parallel 6
agent-env gridsim sweep run $M --name v5-pilot-sol-day --pack gridsim-market-eval --tier floor-day \
  --tasks "$(python scripts/pilot_v5_tasks.py day)" --cap-usd $SWEEP_D --episode-cap-usd $CAP_D --parallel 4
agent-env gridsim sweep run $M --name v5-pilot-sol-show --pack gridsim-market-showcase --tier floor-day --compliant \
  --tasks "$(python scripts/pilot_v5_tasks.py showcase)" --cap-usd $SWEEP_SH --episode-cap-usd $CAP_D --parallel 2
agent-env gridsim episodes v5-pilot-sol v5-pilot-sol-day v5-pilot-sol-show
agent-env gridsim sweep report v5-pilot-sol v5-pilot-sol-day      # results/eval-v5.json, results/board-v5.md
python scripts/pilot_v5.py v5-pilot-sol --day v5-pilot-sol-day --showcase v5-pilot-sol-show \
  --smoke v5-smoke-sprint v5-smoke-day --json results/pilot-v5.json
```

The three pilot sweeps run at the same time (12 attempts at most, about half the box).

floor-sprint column (R and compliant at floor-sprint, baselines played in process):

| # | Floor | Stratum | Date | MW × h | η | Impact h (≥ $5 / ≥ $2) | within_ns | Notice day | Anchor − idle ($) | Anchor capture | Price-taker R | Max-withhold R | Replay A R | Anchor compliant | Price-taker compliant |
|---:|---|---|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `mkt-v5-2025-01-12-A800x4-e1` | base | 2025-01-12 | 800 × 4 | 0.9 | 0 / 0 | 0.54 | no | 42,628 | 0.803 | 0.999 | 0.200 | 0.000 | 0.769 | 0.768 |
| 2 | `mkt-v5-2025-01-24-A1000x4-e1` | base | 2025-01-24 | 1,000 × 4 | 0.8 | 0 / 2 | 0.54 | no | 17,651 | 0.155 | 1.000 | 0.200 | 0.000 | 0.549 | 0.558 |
| 3 | `mkt-v5-2025-02-20-A1500x2-e1` | peak | 2025-02-20 | 1,500 × 2 | 0.9 | 11 / 18 | 0.55 | yes | 2,260,376 | 0.980 | 0.998 | 0.200 | 0.200 | 0.914 | 0.913 |
| 4 | `mkt-v5-2025-02-25-A1200x2-e1` | base | 2025-02-25 | 1,200 × 2 | 0.9 | 0 / 0 | 0.62 | no | 63,367 | 0.735 | 1.000 | 0.200 | 0.200 | 0.740 | 0.794 |
| 5 | `mkt-v5-2025-03-07-A800x1-e1` | base | 2025-03-07 | 800 × 1 | 0.8 | 0 / 1 | 0.64 | no | 72,701 | 0.846 | 1.000 | 0.200 | 0.200 | 0.736 | 0.751 |
| 6 | `mkt-v5-2025-03-16-A1500x2-e3` | peak | 2025-03-16 | 1,500 × 2 | 0.85 | 4 / 8 | 0.55 | yes | 255,930 | 0.688 | 1.000 | 0.200 | 0.161 | 0.699 | 0.724 |
| 7 | `mkt-v5-2025-03-20-A1500x2-e4` | peak | 2025-03-20 | 1,500 × 2 | 0.85 | 2 / 8 | 0.50 | no | 244,168 | 0.803 | 0.967 | 0.200 | 0.200 | 0.737 | 0.712 |
| 8 | `mkt-v5-2025-03-24-A1500x2-e2` | peak | 2025-03-24 | 1,500 × 2 | 0.95 | 3 / 11 | 0.91 | no | 301,415 | 0.550 | 0.468 | 0.200 | 0.188 | 0.666 | 0.298 |
| 9 | `mkt-v5-2025-04-15-A1500x1-e1` | base | 2025-04-15 | 1,500 × 1 | 0.95 | 0 / 2 | 0.58 | no | 74,751 | 0.656 | 1.000 | 0.200 | 0.200 | 0.712 | 0.714 |
| 10 | `mkt-v5-2025-04-20-A1500x2-e1` | peak | 2025-04-20 | 1,500 × 2 | 0.95 | 3 / 7 | 0.71 | no | 29,067 | 0.065 | 0.937 | 0.200 | 0.200 | 0.560 | 0.526 |
| 11 | `mkt-v5-2025-04-26-A1200x4-e1` | base | 2025-04-26 | 1,200 × 4 | 0.9 | 0 / 2 | 0.79 | no | 44,918 | 0.368 | 0.259 | 0.200 | 0.200 | 0.659 | 0.168 |
| 12 | `mkt-v5-2025-04-29-A1500x2-e3` | peak | 2025-04-29 | 1,500 × 2 | 0.9 | 2 / 5 | 0.67 | no | 62,890 | 0.507 | 1.000 | 0.200 | 0.200 | 0.646 | 0.741 |
| 13 | `mkt-v5-2025-05-16-A1500x1-e3` | peak | 2025-05-16 | 1,500 × 1 | 0.9 | 2 / 7 | 0.64 | no | 181,744 | 0.813 | 0.540 | 0.200 | 0.200 | 0.674 | 0.349 |
| 14 | `mkt-v5-2025-05-20-A1500x2-e3` | peak | 2025-05-20 | 1,500 × 2 | 0.95 | 5 / 10 | 0.75 | no | 1,427,708 | 0.957 | 0.998 | 0.000 | 0.200 | 0.781 | 0.780 |
| 15 | `mkt-v5-2025-05-21-A1000x2-e1` | base | 2025-05-21 | 1,000 × 2 | 0.85 | 0 / 2 | 0.70 | yes | 94,798 | 0.620 | 0.786 | 0.200 | 0.200 | 0.749 | 0.584 |
| 16 | `mkt-v5-2025-05-27-A1200x2-e1` | base | 2025-05-27 | 1,200 × 2 | 0.95 | 0 / 1 | 0.54 | no | 54,904 | 0.662 | 1.000 | 0.200 | 0.200 | 0.776 | 0.785 |
| 17 | `mkt-v5-2025-06-22-A1000x1-e1` | base | 2025-06-22 | 1,000 × 1 | 0.95 | 0 / 0 | 0.50 | no | 17,018 | 0.658 | 0.981 | 0.200 | 0.200 | 0.739 | 0.725 |
| 18 | `mkt-v5-2025-06-25-A1200x2-e1` | base | 2025-06-25 | 1,200 × 2 | 0.85 | 0 / 0 | 0.75 | no | 76,288 | 0.978 | 0.997 | 0.200 | 0.200 | 0.907 | 0.904 |
| 19 | `mkt-v5-2025-07-09-A600x4-e1` | base | 2025-07-09 | 600 × 4 | 0.85 | 0 / 0 | 0.67 | no | 15,828 | 0.501 | 1.000 | 0.200 | 0.200 | 0.631 | 0.631 |
| 20 | `mkt-v5-2025-07-17-A600x4-e1` | base | 2025-07-17 | 600 × 4 | 0.95 | 0 / 0 | 0.83 | no | 79,811 | 0.956 | 1.000 | 0.200 | 0.200 | 0.752 | 0.752 |
| 21 | `mkt-v5-2025-07-30-A1200x2-e1` | peak | 2025-07-30 | 1,200 × 2 | 0.9 | 6 / 9 | 0.75 | no | 971,120 | 0.959 | 1.000 | 0.200 | 0.200 | 0.801 | 0.813 |
| 22 | `mkt-v5-2025-08-05-A1500x2-e1` | base | 2025-08-05 | 1,500 × 2 | 0.85 | 0 / 0 | 0.88 | no | 92,632 | 0.982 | 1.000 | 0.200 | 0.200 | 0.829 | 0.828 |
| 23 | `mkt-v5-2025-08-19-A1500x1-e1` | peak | 2025-08-19 | 1,500 × 1 | 0.85 | 6 / 14 | 0.74 | no | 333,501 | 0.987 | 0.998 | 0.200 | 0.200 | 0.738 | 0.740 |
| 24 | `mkt-v5-2025-08-25-A600x1-e1` | base | 2025-08-25 | 600 × 1 | 0.9 | 0 / 0 | 0.62 | no | 22,215 | 0.747 | 0.833 | 0.200 | 0.200 | 0.613 | 0.506 |
| 25 | `mkt-v5-2025-09-01-A1500x4-e1` | base | 2025-09-01 | 1,500 × 4 | 0.95 | 0 / 4 | 0.58 | no | 154,095 | 0.807 | 0.959 | 0.200 | 0.200 | 0.833 | 0.804 |
| 26 | `mkt-v5-2025-09-05-A800x4-e1` | base | 2025-09-05 | 800 × 4 | 0.8 | 0 / 0 | 0.75 | no | 34,438 | 0.462 | 1.000 | 0.200 | 0.200 | 0.655 | 0.680 |
| 27 | `mkt-v5-2025-10-26-A1500x4-e3` | peak | 2025-10-26 | 1,500 × 4 | 0.85 | 2 / 9 | 0.50 | no | 118,270 | 0.411 | 1.000 | 0.200 | 0.179 | 0.646 | 0.650 |
| 28 | `mkt-v5-2025-10-27-A600x4-e1` | base | 2025-10-27 | 600 × 4 | 0.8 | 0 / 1 | 0.70 | no | 62,459 | 0.606 | 1.000 | 0.200 | 0.087 | 0.666 | 0.700 |
| 29 | `mkt-v5-2025-11-13-A1000x2-e1` | base | 2025-11-13 | 1,000 × 2 | 0.9 | 0 / 0 | 0.50 | yes | 51,224 | 0.581 | 1.000 | 0.200 | 0.163 | 0.676 | 0.681 |
| 30 | `mkt-v5-2025-11-16-A1500x2-e2` | peak | 2025-11-16 | 1,500 × 2 | 0.95 | 4 / 7 | 0.90 | no | 228,281 | 0.764 | 1.000 | 0.200 | 0.194 | 0.729 | 0.729 |


floor-day column (at floor-day; price-taker, max-withhold and replay A re-plan the op day as the anchor does):

| # | Floor | Stratum | Date | MW × h | η | Impact h (≥ $5 / ≥ $2) | within_ns | Notice day | Anchor − idle ($) | Anchor capture | Price-taker R | Max-withhold R | Replay A R | Anchor compliant | Price-taker compliant |
|---:|---|---|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `mkt-v5-2025-01-12-A800x4-e1` | base | 2025-01-12 | 800 × 4 | 0.9 | 0 / 0 | 0.54 | no | 41,243 | 0.776 | 0.993 | 1.000 | 1.000 | 0.801 | 0.797 |
| 2 | `mkt-v5-2025-02-20-A1500x2-e1` | peak | 2025-02-20 | 1,500 × 2 | 0.9 | 11 / 18 | 0.55 | yes | 2,283,970 | 0.991 | 0.993 | 0.407 | 0.407 | 0.917 | 0.915 |
| 3 | `mkt-v5-2025-03-16-A1500x2-e3` | peak | 2025-03-16 | 1,500 × 2 | 0.85 | 4 / 8 | 0.55 | yes | 398,657 | 1.072 | 1.000 | 0.816 | 0.836 | 0.789 | 0.791 |
| 4 | `mkt-v5-2025-04-15-A1500x1-e1` | base | 2025-04-15 | 1,500 × 1 | 0.95 | 0 / 2 | 0.58 | no | 99,640 | 0.874 | 1.000 | 0.989 | 0.989 | 0.833 | 0.833 |
| 5 | `mkt-v5-2025-05-21-A1000x2-e1` | base | 2025-05-21 | 1,000 × 2 | 0.85 | 0 / 2 | 0.70 | yes | 145,526 | 0.952 | 0.975 | 0.842 | 0.842 | 0.894 | 0.882 |
| 6 | `mkt-v5-2025-07-09-A600x4-e1` | base | 2025-07-09 | 600 × 4 | 0.85 | 0 / 0 | 0.67 | no | 49,088 | 1.553 | 1.000 | 1.000 | 1.000 | 0.699 | 0.699 |
| 7 | `mkt-v5-2025-08-25-A600x1-e1` | base | 2025-08-25 | 600 × 1 | 0.9 | 0 / 0 | 0.62 | no | 27,368 | 0.921 | 0.952 | 0.786 | 0.786 | 0.647 | 0.623 |
| 8 | `mkt-v5-2025-09-05-A800x4-e1` | base | 2025-09-05 | 800 × 4 | 0.8 | 0 / 0 | 0.75 | no | 56,132 | 0.752 | 1.000 | 0.937 | 0.937 | 0.825 | 0.825 |
| 9 | `mkt-v5-2025-10-26-A1500x4-e3` | peak | 2025-10-26 | 1,500 × 4 | 0.85 | 2 / 9 | 0.50 | no | 233,720 | 0.812 | 0.982 | 1.000 | 1.000 | 0.812 | 0.802 |
| 10 | `mkt-v5-2025-11-16-A1500x2-e2` | peak | 2025-11-16 | 1,500 × 2 | 0.95 | 4 / 7 | 0.90 | no | 258,416 | 0.865 | 1.000 | 0.694 | 0.718 | 0.785 | 0.785 |


Showcase floors (display only; floor-day):
- `mkt-v5-2024-08-20-A800x2-e1` 2024-08-20: anchor − idle $679,869, impact h 1, price-taker R 1.000
- `mkt-v5-2026-01-23-A800x2-e1` 2026-01-23: anchor − idle $-13,158, impact h 0, price-taker R 0.000
- `mkt-v5-2026-01-24-A800x2-e1` 2026-01-24: anchor − idle $-19,606, impact h 4, price-taker R 0.000
- `mkt-v5-2026-01-25-A800x2-e1` 2026-01-25: anchor − idle $522,760, impact h 21, price-taker R 1.000
- `mkt-v5-2026-01-26-A800x2-e1` 2026-01-26: anchor − idle $1,376,829, impact h 21, price-taker R 0.959
- `mkt-v5-2026-01-27-A800x2-e1` 2026-01-27: anchor − idle $182,273, impact h 5, price-taker R 0.860

Smoke floors (`gridsim-market-train`):
- smoke-sprint: `mkt-v5-2024-11-11-A600x2-e1`, `mkt-v5-2024-10-27-A1500x2-e3`
- smoke-day: `mkt-v5-2024-06-24-A1500x4-e2`, `mkt-v5-2024-03-18-A1000x4-e2`

## Metrics
Computed by `scripts/pilot_v5.py` from the replay-verified Episode JSON v5 (`agent-env gridsim episodes`), results.jsonl
and the pack rows: the floor-sprint column over all 30 floors and by stratum (peak, base), the floor-day column the same
way, floor-day minus floor-sprint paired on the 10 floors played at both, the showcase floors as one line each. CIs are
95% bootstrap over floors (2,000 resamples, seed 0), paired where a difference is shown.
- **Primary: mean R over the 30 floor-sprint floors** with its 95% CI (the floor-day column's mean R with its CI is
  reported apart), R on the disclosure-anchor scale, clip(0.2 + 0.8 (P − P_idle)/(P_anchor − P_idle), 0, 1); no valid
  `submit_offer` scores 0. Also the share of floors at R = 1 and beats-anchor (P > P_anchor at 6 decimals).
- **Compliant score** 0.5 R + 0.5 clip(welfare ratio, 0, 1), with its CI, next to R.
- **Baselines on the same floors at the same tier, both scorings**, each played in process through
  `gridsim_core.market.Session` by `scripts/pilot_v5.py`: idle (an offer with no blocks), the anchor (its policy; in
  floor-day it also re-plans the op day), the price-taker (the forecast DP's quantities self-scheduled, blind to its own
  impact), max-withhold (all MW offered at the cap, bid at the floor) and replay A (seat A's real offers of the day,
  where its pool is the day's). In floor-day, price-taker, max-withhold and replay A submit at D-1 09:00 and re-plan the
  op day on their awards with the anchor's re-planner, so each differs from the anchor only in its DAM offer
  (max-withhold is then the contract's max-withhold-then-deviate); idle does nothing. R − baseline and compliant −
  baseline, paired; beats-baseline compares profit. The stored floor-sprint baselines in the pack rows are the same
  numbers at that tier. No AS-hog: v5 seats are energy-only.
- **Registered secondary: price-making gain** (P − P_price-taker)/MW per day, A's profit over the impact-blind
  price-taker's on the same floor at the same tier (the grade's `price_making_gain_usd_per_mw_day` in floor-sprint),
  mean with its CI, overall and by stratum.
- **Weight-0 rows:** hindsight capture (P − P_idle)/(BR_A − P_idle) next to the anchor's, regret_norm, welfare ratio and
  dead-weight loss, eps (seat A's own share `eps_a`, the board's eps row; the seats' mean `eps_mean`; and `eps_nash`,
  the largest seat's share, read only as the statement that the replayed real seats sit far from a hindsight Nash
  profile, since it saturates near 1), A's rank among the seats ($/MW), conduct (mitigated hours and floors, withholding index,
  price-talk flags), the CfD row (floor-day: contracts signed, value at signing against the ex-ante fair value, settled),
  clipped hours.
- **Price impact:** per floor, the hours where A's full sale moves the hub price by ≥ $5 (the pack's impact hours,
  recomputed); `impact_usd` = Σ award × (price − the price without A's offer), the grade's row, negative when A's own
  sales lowered its price; MWh A sold in impact hours against the anchor's and the price-taker's; and **toward
  price-taker**, over the hours where the impact-aware anchor and the impact-blind price-taker are awarded different
  quantities: Σ (A's award − anchor's) × sign(price-taker's − anchor's) / Σ |price-taker's − anchor's|, pooled over a
  set's floors (0 = at the anchor's position, 1 = at the price-taker's, < 0 beyond the anchor in the direction of
  withholding).
- **Fidelity:** Spearman ρ of the day's raw within_ns with R and with regret_norm, and R by fidelity tercile.
- **Play and cost:** submits, check_offer and get_disclosure calls, refused offers or schedules, input, output and
  cached tokens, $/episode, turns, audit failures, unscored runs and why, spend per sweep.

## Hypotheses
- **H1 (FD-4324's frontier target):** Sol's mean R on the floor-day column lies in 0.45 to 0.80. Read on the point
  estimate, its CI reported. The floor-sprint column is read against the same band as an expectation only.
- **H2 (price impact pays on peak floors): Sol beats the price-taker on peak floors.** Mean R − price-taker R over the 12
  peak floor-sprint floors: paired CI above 0 supported, below 0 reversed (the impact-blind price-taker beats Sol),
  across 0 undecided at this size; the share of peak floors where Sol's profit beats the price-taker's is reported.
- **H3 (Sol's estimate of its own impact):** toward-price-taker pooled over the peak floor-sprint floors. **Registered
  direction: Sol under-estimates its price impact**, called when it is ≥ 0.5 (Sol's DAM positions sit closer to the
  impact-blind price-taker's than to the information-matched, impact-aware anchor's); < 0 is called over-estimation (it
  withholds beyond the impact-aware position); 0 to 0.5 impact-aware. Not measurable if fewer than 3 peak floors have
  hours where the anchor and the price-taker are awarded differently (all 12 do, 81 hours); then the impact-hour MWh
  against both and `impact_usd` are reported only. The same measure on base floors is reported beside it.
- **H4 (compliant vs R):** Spearman ρ between R and the welfare ratio over the 30 floor-sprint floors. **Registered:
  ρ ≥ 0.3** (where A barely moves the price, profitable arbitrage is also welfare-improving, so the compliant score
  re-ranks little); ρ ≤ −0.3 is called a trade-off (Sol's profit comes at welfare cost); between, no clear relation.
  The ranks of Sol and the five baselines by mean R and by mean compliant score are reported per stratum.
- Expectations, not success bars: Sol is never mitigated on a base floor and its mean withholding index there is below
  0.05; on floor-sprint Sol scores above max-withhold and replay A on mean R in every stratum; on floor-day Sol signs a
  CfD on fewer than half of the floors; Sol's price-making gain on base floors is within ±$5/MW-day of 0.

## Readings for the open v5 decisions (registered before the run)
- **V5-P12, the peak-day premise** (price-making is at stake only on peak days, so the ≥ 2 impact-hour measure should
  define the eval stratum): read on Sol's R − price-taker R, paired, per stratum of the floor-sprint column. Called
  **supported** if the base-floor CI includes 0 and the peak-floor CI excludes it (Sol's play departs from price-taking
  only where its impact exists), which favours option (a) for eval (the peak stratum as its own column, as V5-P18 built)
  and (b) for train. Called **not supported** if the base-floor CI excludes 0 with a mean at least as far from 0 as the
  peak floors' (Sol's distance from the price-taker does not depend on impact, so a peak filter buys nothing for this
  model). If neither CI excludes 0, the impact axis is called **not visible at this size**, and the pilot recommends
  measuring option (c), the horizontal residual (steeper ground), before the board. Anything else is undecided.
- **Fidelity (V5-P2's filter, raw within_ns ≥ 0.5 with the hub offset):** called **binding** if ρ(within_ns, R) ≥ 0.3
  on the floor-sprint column or the lowest fidelity tercile's mean R is ≥ 0.15 below the highest's (low-fidelity floors
  score differently for a reason that is not the agent's), which would argue for raising the filter to 0.75 for the
  board; otherwise **not binding at this size**. The same rule on regret_norm (with the sign reversed) is reported.
- **Anchor scale:** called compressed for this model, as V2-D1's rule, if more than a third of Sol's floor-sprint floors
  sit at R = 1.

## Deviations

- **The floor-sprint episode cap rule failed.** The smoke (2 + 2 train floors, all scored, $0.39) gave medians of
  $0.0430 a floor-sprint and $0.1512 a floor-day, so the registered caps were $0.18 and $0.61. gridsim-llm's guard books
  a worst-case 16,384-token turn before each request ($0.167 at Sol's $10 per million output tokens), so at $0.18 every
  floor-sprint run of `v5-pilot-sol` stopped at its cap after 3 or 4 of its 6 turns: 0 of 30 scored, $0.57 spent. The
  rule ignored the guard's reservation; nothing else was changed. As registered, each run went once more at 2 × the cap
  ($0.36) in `v5-pilot-sol-amend` (30 of 30 scored at the first attempt, $1.45); every floor-sprint number in
  `results/board-v5.md` is that amendment's, labelled "amended", and no primary floor-sprint number exists. The
  floor-day sweep ($0.61) and the showcase sweep were not affected (no run came near its cap).
- **Showcase:** after 5db4ab3's per-tier headroom filter, 2026-01-23 and 01-24 are not floor-day floors
  (`floor_day_ok` false: the anchor loses money there), and the sweep refused them; `v5-pilot-sol-show` ran the other
  four (aug24-0820 and 2026-01-25 to 01-27). Display only either way.
- **Analysis code, no registered number changed:** ad4fc37 makes `scripts/pilot_v5.py` report every set (the empty
  primary floor-sprint column made its fidelity line fail) and summarise unscored runs by reason; 044224d adds the
  Spearman of R with the welfare ratio that H4 is read on, which the committed script did not compute.
- **Derived, not deviations:** caps $0.18 (floor-sprint) and $0.61 (floor-day); B = $35.61, split by expected spend into
  `--cap-usd` $12.38 (floor-sprint), $14.51 (floor-day) and $8.71 (showcase); the amendment sweep's `--cap-usd` $15.82,
  $40 less the spend so far and the two running sweeps' caps. The three pilot sweeps started together, the amendment
  once the floor-sprint sweep had stopped, on the box P4's lane shares; no run was retried, and every run of the
  amendment, floor-day and showcase sweeps scored at its first attempt. Total spend $4.50 of $40.
- **H3's measure did not measure what it was registered for:** it assumes Sol's DAM position lies between the anchor's
  and the price-taker's, and Sol's does not (it sells 2.4 times either's volume in impact hours). Its value and the
  registered call are reported as they are, with the other impact rows beside them (`results/board-v5.md`, Reading).
