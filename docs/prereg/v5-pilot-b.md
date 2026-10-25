# GridSimEnv v5 pilot B: pre-registration (GPT-6.1 Sol, The Market Floor, rules 5.1)

Committed on `v5-pilot-b` before the first model episode of this pilot, the smoke included. Nothing below changes after
a run starts, and nothing is rerun to improve a score. Anything done differently is logged under "Deviations", appended
after the run, with this text left as it is. This pilot supersedes the rules-5.0 pilot (`docs/prereg/v5-pilot.md`,
v5-preview 4162fda), which stays on record; it gives Edgar v5 numbers on the adopted reward scale and the viewer rules-5.1
replays. It is not the v5 board.

## Code and rules
- Branch `v5-pilot-b` at this commit: origin/lane-x5 43191fe, rules 5.1 (`MARKET_VERSION` 5.1; docs/CONTRACT-v5.md
  V5-P21 to V5-P24): fidelity bar 0.7; train back to 2022 (3,777 floors on 229 dates; the months before 2024-05 live in
  the overflow cache, which only path-B training reads); eval 289 floors on 147 dates, two seat-A portfolios a date, 12
  peak floors on the 6 peak dates, 60 floor-day floors (one a date, 6 peak); rtcb 65; a left-out, `null` or `"keep"`
  field keeps its value; `get_forecast` reads `issued_at` as a time (5.0 compared strings and refused 197 of the 5.0
  pilot's 276 calls, all 113 of its floor-sprint calls); the public board leads with the compliant score; `sweep run`
  refuses an episode cap below the agent's first-turn reserve. This commit adds only this pre-registration,
  `docs/prereg/v5-pilot-b-tasks.json`, `scripts/pilot_v5b_tasks.py` (seed 5324) and `scripts/pilot_v5b.py`. 825 tests
  pass; ruff is clean.
- **Reward scale (Edgar's cross-version rule, origin/lane-reward f6eae2d, `docs/REWARD-SCALES.md`):** the headline is
  hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, beside the anchor's C on the same floors and
  Δ = C − C_anchor with its paired 95% CI; R second with its R = 1 share. For v5, P_hind is the tier's BR_rt (`p_br_rt`,
  the clairvoyant bound of the same settlement); BR_A is not a bound and stays a weight-0 row. The public compliant
  score's profit half is clip(C, 0, 1): 0.5 clip(C, 0, 1) + 0.5 clip(W/W\*, 0, 1). No valid `submit_offer` scores 0 on
  every scale. The env's verifier is unchanged at 43191fe: its grade carries R, `p_br_rt` and the compliant score with
  R as its profit half ("as built"); `scripts/pilot_v5b.py` computes C, Δ and the compliant score on clip(C) from the
  Episode JSON and the pack rows.
- Env `gridsim-market`, verifier `gridsim-market-verifier`, agent `gridsim-llm`, run on EC2 box gridsim-board345
  (c7i.8xlarge, Ubuntu 24.04, local Docker), shared with lanes P3b and P4b: this lane has its own checkout, venv,
  agent-env state root, registry prefix and systemd units, and a third of the cores. After `agent-env gridsim setup
  --agent` (gridsim-llm v1 in this lane's registry), `scripts/market_e2e.py` passed at 43191fe on the box with no model spend, each run failing unless the anchor scores R 1.0 at its stored P_anchor to the cent with a
  clean audit and a byte-for-byte replay: the bundle's floor-day floor (2026-07-21, P_anchor $358,139.24) and
  floor-sprint floor (2024-08-20, $494,458.97), the eight wiring tasks, and two eval floors, floor-day
  `mkt-v5-2025-05-20-A1500x2-e3` ($1,447,228.26) and floor-sprint `mkt-v5-2025-07-30-A1200x4-e1` ($1,399,924.34, path B
  equal to path A); problems []. Setup and the floor-sprint e2e run again at this commit before the smoke.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  market rules card, 16,384 output tokens a turn, 6 turns and 24 calls a floor-sprint, 36 turns and 120 calls a
  floor-day, 3 planning and 6 data calls a watch, 1 h freeze, the other four seats scripted on their real offers of the
  day, the ISO replaying the day's real notices (floor-day only). The prompt and tools are those of 43191fe.
- One run per floor. A run that fails for infrastructure (unscored, not stopped at its cap) is retried by the sweep at
  most twice; every attempt is kept in results.jsonl and reported.
- The scored columns are graded on R (the verifier's headline; every scale above comes from the same runs). The
  showcase sweep is graded compliant, as the showcase bundles are. The agent's prompt and tools are the same either way.

## Smoke, caps and budget
- **Smoke** (after this commit, before any pilot sweep; never counted): 2 floor-sprint and 2 floor-day floors of
  `gridsim-market-train` whose days back to D−62 are in git, at the tiers' default episode caps ($1.00 floor-sprint,
  $2.00 floor-day), sweeps `v5b-smoke-sprint` (`--cap-usd 2`) and `v5b-smoke-day` (`--cap-usd 4`).
- **Episode caps** (`--episode-cap-usd`): m_s and m_d are the median priced costs of each tier's smoke runs.
  CAP_S = max($0.40, 4 × m_s) and CAP_D = max($2.00, 4 × m_d), rounded up to the cent; the showcase sweep takes CAP_D.
  gridsim-llm's guard books a worst-case 16,384-token turn (about $0.167 for Sol) before each request, so a cap just
  above that reserve stops a sprint after two turns (the rules-5.0 pilot); $0.40 leaves room for six. A run stopped at
  its cap is unscored.
- **Sweep caps** (`--cap-usd`): B = $25 − the smoke's spend − $2 (kept for amendments). Each sweep needs its parallel
  attempts at their episode cap plus three times its expected spend: floor-sprint 4 × CAP_S + 3 × 30 × m_s, floor-day
  3 × CAP_D + 3 × 10 × m_d, showcase 1 × CAP_D + 3 × 2 × m_d, rounded up to the cent. If the three needs fit in B each
  sweep's cap is its need; otherwise each is its need × B / their sum, rounded down to the cent. A sweep that stops with
  runs unplayed because its next attempt could pass its cap is resumed after all three have stopped, its cap raised by
  the unspent part of B (the same sweep and runs).
- **Total budget $25** across every sweep: smoke, pilot, showcase and amendments.
- **Amendment rule:** each run stopped at its episode cap is run once more at 2 × that cap, in a sweep named after its
  own with `-amend`, and reported as a labelled amendment; the primary numbers are the first sweeps alone. An amendment
  sweep's cap is $25 less the spend so far and the unspent caps of the sweeps still running.
- The caps that follow from the smoke are recorded in the status log and the results' Deviations section as "derived",
  not as deviations. The three pilot sweeps run at the same time: 8 attempts at most (floor-sprint 4, floor-day 3,
  showcase 1).

## Tasks
`scripts/pilot_v5b_tasks.py` (seed 5324) draws every column from the packs at this commit; the list with what is known
about each floor before any run is `docs/prereg/v5-pilot-b-tasks.json`.
- **floor-sprint column (scored, 30 floors of `gridsim-market-eval`):** all 12 peak floors (the pack's `peak` stratum:
  both portfolios of the 6 dates whose first draw has ≥ 2 hours where A's full sale moves the hub price by ≥ $5) and 18
  base floors drawn at random: the floor-day column's 4 base floors, then 14 more. Each draw takes the candidate on a
  date the column does not hold yet whose month it holds least, ties broken by the seeded shuffle.
- **floor-day column (scored, reported apart, never pooled with the sprint column):** 10 of the pack's 60 floor-day
  floors: all 6 peak ones and 4 base ones drawn as above. Every floor-day floor is also in the floor-sprint column, so
  the two tiers are compared paired on these 10.
- **Display only, never counted:** `mkt-v5-2024-08-20-A800x2-e1` (aug24-0820) and the Winter Storm Fern floor whose
  floor-day anchor earns the most over idle, `mkt-v5-2026-01-26-A800x2-e1`, at floor-day, graded compliant. (fern
  01-23 and 01-24 are not floor-day floors: the anchor loses money there.)
- **Smoke, never counted:** `smoke-sprint` and `smoke-day` below.
- **Overlap with the rules-5.0 pilot:** the 5.1 eval pack keeps 120 of the 5.0 pack's 200 floors with identical stored
  references. 7 of this floor-sprint column were in the 5.0 pilot's floor-sprint column (the 6 floor-day peak floors and
  `mkt-v5-2025-07-17-A600x4-e1`); 1 of the floor-day column was in its floor-day column (`mkt-v5-2025-11-16-A1500x2-e2`).

```
python scripts/pilot_v5b_tasks.py sprint --json docs/prereg/v5-pilot-b-tasks.json
M="--env gridsim-market --models openai/gpt-6.1-sol"
agent-env gridsim sweep run $M --name v5b-smoke-sprint --pack gridsim-market-train --tier floor-sprint \
  --tasks "$(python scripts/pilot_v5b_tasks.py smoke-sprint)" --episode-cap-usd 1 --cap-usd 2 --parallel 2
agent-env gridsim sweep run $M --name v5b-smoke-day --pack gridsim-market-train --tier floor-day \
  --tasks "$(python scripts/pilot_v5b_tasks.py smoke-day)" --episode-cap-usd 2 --cap-usd 4 --parallel 2
# CAP_S, CAP_D and SWEEP_* from the smoke (above)
agent-env gridsim sweep run $M --name v5b-pilot-sol --pack gridsim-market-eval --tier floor-sprint \
  --tasks "$(python scripts/pilot_v5b_tasks.py sprint)" --cap-usd $SWEEP_S --episode-cap-usd $CAP_S --parallel 4
agent-env gridsim sweep run $M --name v5b-pilot-sol-day --pack gridsim-market-eval --tier floor-day \
  --tasks "$(python scripts/pilot_v5b_tasks.py day)" --cap-usd $SWEEP_D --episode-cap-usd $CAP_D --parallel 3
agent-env gridsim sweep run $M --name v5b-pilot-sol-show --pack gridsim-market-showcase --tier floor-day --compliant \
  --tasks "$(python scripts/pilot_v5b_tasks.py showcase)" --cap-usd $SWEEP_SH --episode-cap-usd $CAP_D --parallel 1
agent-env gridsim episodes v5b-pilot-sol v5b-pilot-sol-day v5b-pilot-sol-show    # replay-verified Episode JSON v5
agent-env gridsim sweep report v5b-pilot-sol v5b-pilot-sol-day --card results/eval-v5b.json --board results/board-v5b.md
python scripts/pilot_v5b.py v5b-pilot-sol --day v5b-pilot-sol-day --showcase v5b-pilot-sol-show \
  --smoke v5b-smoke-sprint v5b-smoke-day --json results/pilot-v5b.json
```

The rules-5.0 pilot's `results/board-v5.md`, `eval-v5.json` and `pilot-v5.json` are left as they are.

### Known before any run
Stored references and the baselines played in process at each column's tier (`gridsim_core.market.baseline_plays`):
C against BR_rt (idle 0), R (idle 0.2, anchor 1.0), the compliant score on clip(C) and as built.

floor-sprint column:

| # | Floor | Stratum | Date | MW × h | η | Impact h (≥ $5 / ≥ $2) | within_ns | In 5.0 pilot | Anchor − idle ($) | BR_rt − idle ($) | Anchor C | Price-taker C | Replay A C | Max-withhold C | Price-taker R | Anchor compliant on C | Price-taker compliant on C |
|---:|---|---|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `mkt-v5-2025-01-01-A400x4-e1` | base | 2025-01-01 | 400 × 4 | 0.85 | 0 / 0 | 0.75 | no | 13,407 | 76,122 | 0.176 | 0.184 | 0.000 | 0.000 | 1.000 | 0.201 | 0.215 |
| 2 | `mkt-v5-2025-01-02-A1200x4-e2` | base | 2025-01-02 | 1,200 × 4 | 0.95 | 0 / 0 | 0.88 | no | 41,106 | 86,542 | 0.475 | 0.482 | 0.000 | 0.000 | 1.000 | 0.529 | 0.541 |
| 3 | `mkt-v5-2025-02-06-A1000x1-e1` | base | 2025-02-06 | 1,000 × 1 | 0.8 | 0 / 0 | 0.79 | no | 12,484 | 96,706 | 0.129 | 0.147 | -0.100 | 0.000 | 1.000 | 0.156 | 0.183 |
| 4 | `mkt-v5-2025-02-15-A800x4-e1` | base | 2025-02-15 | 800 × 4 | 0.8 | 0 / 0 | 0.75 | no | 21,364 | 86,924 | 0.246 | 0.246 | -0.280 | 0.000 | 1.000 | 0.241 | 0.241 |
| 5 | `mkt-v5-2025-02-18-A800x4-e2` | base | 2025-02-18 | 800 × 4 | 0.95 | 0 / 0 | 0.71 | no | 16,484 | 57,377 | 0.287 | 0.255 | 0.000 | 0.000 | 0.910 | 0.305 | 0.281 |
| 6 | `mkt-v5-2025-03-24-A1200x2-e3` | peak | 2025-03-24 | 1,200 × 2 | 0.9 | 3 / 6 | 0.91 | no | 262,598 | 662,447 | 0.396 | 0.138 | -0.034 | 0.000 | 0.478 | 0.357 | 0.130 |
| 7 | `mkt-v5-2025-03-24-A1500x2-e2` | peak | 2025-03-24 | 1,500 × 2 | 0.95 | 3 / 11 | 0.91 | yes | 301,415 | 819,680 | 0.368 | 0.123 | -0.005 | 0.000 | 0.468 | 0.349 | 0.126 |
| 8 | `mkt-v5-2025-04-13-A800x2-e1` | base | 2025-04-13 | 800 × 2 | 0.8 | 0 / 1 | 0.75 | no | 41,829 | 110,811 | 0.377 | 0.373 | 0.000 | 0.000 | 0.991 | 0.393 | 0.388 |
| 9 | `mkt-v5-2025-04-20-A1500x2-e1` | peak | 2025-04-20 | 1,500 × 2 | 0.95 | 3 / 7 | 0.71 | yes | 29,067 | 504,280 | 0.058 | 0.053 | 0.000 | 0.000 | 0.937 | 0.089 | 0.084 |
| 10 | `mkt-v5-2025-04-20-A400x4-e1` | peak | 2025-04-20 | 400 × 4 | 0.85 | 0 / 2 | 0.71 | no | 10,117 | 181,028 | 0.056 | 0.056 | 0.000 | 0.000 | 1.000 | 0.108 | 0.108 |
| 11 | `mkt-v5-2025-05-19-A600x1-e2` | base | 2025-05-19 | 600 × 1 | 0.95 | 0 / 0 | 0.75 | no | 9,717 | 77,888 | 0.125 | 0.125 | -0.004 | 0.000 | 0.999 | 0.166 | 0.165 |
| 12 | `mkt-v5-2025-05-20-A1200x1-e1` | peak | 2025-05-20 | 1,200 × 1 | 0.9 | 4 / 9 | 0.75 | no | 548,577 | 1,266,007 | 0.433 | 0.453 | 0.000 | 0.000 | 1.000 | 0.562 | 0.589 |
| 13 | `mkt-v5-2025-05-20-A1500x2-e3` | peak | 2025-05-20 | 1,500 × 2 | 0.95 | 5 / 10 | 0.75 | yes | 1,427,708 | 1,707,210 | 0.836 | 0.834 | 0.000 | -0.445 | 0.998 | 0.699 | 0.698 |
| 14 | `mkt-v5-2025-06-04-A800x4-e1` | base | 2025-06-04 | 800 × 4 | 0.95 | 0 / 0 | 0.75 | no | 26,448 | 143,104 | 0.185 | 0.003 | 0.000 | 0.000 | 0.212 | 0.224 | 0.013 |
| 15 | `mkt-v5-2025-06-05-A1200x2-e1` | base | 2025-06-05 | 1,200 × 2 | 0.8 | 0 / 0 | 0.79 | no | 56,441 | 537,787 | 0.105 | 0.110 | 0.000 | 0.000 | 1.000 | 0.398 | 0.416 |
| 16 | `mkt-v5-2025-06-28-A1500x4-e1` | base | 2025-06-28 | 1,500 × 4 | 0.8 | 0 / 0 | 0.71 | no | 113,718 | 141,288 | 0.805 | 0.812 | 0.000 | 0.000 | 1.000 | 0.774 | 0.785 |
| 17 | `mkt-v5-2025-07-17-A600x4-e1` | base | 2025-07-17 | 600 × 4 | 0.95 | 0 / 0 | 0.83 | yes | 79,811 | 85,908 | 0.929 | 0.929 | 0.000 | 0.000 | 1.000 | 0.717 | 0.717 |
| 18 | `mkt-v5-2025-07-30-A1200x2-e1` | peak | 2025-07-30 | 1,200 × 2 | 0.9 | 6 / 9 | 0.75 | yes | 971,120 | 1,344,886 | 0.722 | 0.750 | 0.000 | 0.000 | 1.000 | 0.663 | 0.688 |
| 19 | `mkt-v5-2025-07-30-A1200x4-e1` | peak | 2025-07-30 | 1,200 × 4 | 0.85 | 6 / 9 | 0.75 | no | 1,399,924 | 1,421,657 | 0.985 | 0.984 | 0.000 | 0.000 | 1.000 | 0.838 | 0.837 |
| 20 | `mkt-v5-2025-08-19-A1000x4-e2` | peak | 2025-08-19 | 1,000 × 4 | 0.85 | 4 / 11 | 0.74 | no | 617,600 | 842,680 | 0.733 | 0.732 | 0.000 | 0.000 | 0.999 | 0.612 | 0.612 |
| 21 | `mkt-v5-2025-08-19-A1500x1-e1` | peak | 2025-08-19 | 1,500 × 1 | 0.85 | 6 / 14 | 0.74 | yes | 333,501 | 1,321,506 | 0.252 | 0.252 | 0.000 | 0.000 | 0.998 | 0.364 | 0.366 |
| 22 | `mkt-v5-2025-08-28-A400x2-e2` | base | 2025-08-28 | 400 × 2 | 0.9 | 0 / 1 | 0.76 | no | 58,426 | 151,994 | 0.384 | 0.379 | -0.075 | 0.000 | 0.989 | 0.292 | 0.288 |
| 23 | `mkt-v5-2025-09-11-A600x1-e1` | base | 2025-09-11 | 600 × 1 | 0.8 | 0 / 0 | 0.88 | no | 14,609 | 42,678 | 0.342 | 0.317 | 0.000 | 0.000 | 0.941 | 0.276 | 0.256 |
| 24 | `mkt-v5-2025-09-13-A1000x2-e2` | base | 2025-09-13 | 1,000 × 2 | 0.95 | 0 / 0 | 0.83 | no | 45,776 | 165,313 | 0.277 | 0.279 | -0.015 | 0.000 | 1.000 | 0.345 | 0.349 |
| 25 | `mkt-v5-2025-09-25-A800x4-e1` | base | 2025-09-25 | 800 × 4 | 0.85 | 0 / 0 | 0.79 | no | 88,186 | 152,419 | 0.579 | 0.573 | 0.000 | 0.000 | 0.993 | 0.517 | 0.513 |
| 26 | `mkt-v5-2025-10-14-A1000x2-e2` | base | 2025-10-14 | 1,000 × 2 | 0.85 | 0 / 1 | 0.87 | no | 113,551 | 164,833 | 0.689 | 0.689 | -0.083 | 0.000 | 1.000 | 0.542 | 0.542 |
| 27 | `mkt-v5-2025-10-19-A1000x1-e1` | base | 2025-10-19 | 1,000 × 1 | 0.85 | 0 / 0 | 0.83 | no | 13,692 | 98,697 | 0.139 | 0.148 | 0.000 | 0.000 | 1.000 | 0.136 | 0.150 |
| 28 | `mkt-v5-2025-10-29-A1200x2-e1` | base | 2025-10-29 | 1,200 × 2 | 0.9 | 0 / 0 | 0.75 | no | 69,138 | 170,905 | 0.405 | 0.407 | 0.000 | 0.000 | 1.000 | 0.474 | 0.478 |
| 29 | `mkt-v5-2025-11-16-A1500x2-e2` | peak | 2025-11-16 | 1,500 × 2 | 0.95 | 4 / 7 | 0.90 | yes | 228,281 | 403,253 | 0.566 | 0.566 | -0.004 | 0.000 | 1.000 | 0.512 | 0.512 |
| 30 | `mkt-v5-2025-11-16-A800x2-e1` | peak | 2025-11-16 | 800 × 2 | 0.85 | 0 / 3 | 0.90 | no | 108,681 | 209,020 | 0.520 | 0.520 | 0.000 | 0.000 | 1.000 | 0.460 | 0.460 |

- all 30: C — anchor 0.419, price-taker 0.397, max-withhold −0.015, replay A −0.020, idle 0; R — price-taker 0.930
  (R = 1 on 14), max-withhold 0.193, replay A 0.173; compliant on C — anchor 0.410, price-taker 0.391, max-withhold
  0.007, replay A 0.019, idle 0.006; as built — anchor 0.700, price-taker 0.658. The price-taker out-earns the anchor on
  10; P_anchor − P_idle median $63,782.
- 12 peak: C — anchor 0.494, price-taker 0.455, max-withhold −0.037, replay A −0.004; R — price-taker 0.906 (R = 1 on
  4); compliant on C — anchor 0.468, price-taker 0.434; the price-taker out-earns the anchor on 2 (on the 03-24 pair it
  captures 0.12 to 0.14 against the anchor's 0.37 to 0.40).
- 18 base: C — anchor 0.370, price-taker 0.359, max-withhold 0.000, replay A −0.031; R — price-taker 0.946 (R = 1 on
  10); compliant on C — anchor 0.371, price-taker 0.362; the price-taker out-earns the anchor on 8.

floor-day column (price-taker, max-withhold and replay A submit at D−1 09:00 and re-plan the op day on their awards
with the anchor's re-planner, so each differs from the anchor only in its DAM offer):

| # | Floor | Stratum | Date | MW × h | η | Impact h (≥ $5 / ≥ $2) | within_ns | In 5.0 pilot | Anchor − idle ($) | BR_rt − idle ($) | Anchor C | Price-taker C | Replay A C | Max-withhold C | Price-taker R | Anchor compliant on C | Price-taker compliant on C |
|---:|---|---|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `mkt-v5-2025-01-01-A400x4-e1` | base | 2025-01-01 | 400 × 4 | 0.85 | 0 / 0 | 0.75 | no | 25,792 | 167,507 | 0.154 | 0.158 | 0.441 | 0.441 | 1.000 | 0.282 | 0.284 |
| 2 | `mkt-v5-2025-03-24-A1500x2-e2` | peak | 2025-03-24 | 1,500 × 2 | 0.95 | 3 / 11 | 0.91 | no | 508,400 | 1,067,504 | 0.476 | 0.402 | 0.411 | 0.411 | 0.876 | 0.526 | 0.489 |
| 3 | `mkt-v5-2025-04-20-A1500x2-e1` | peak | 2025-04-20 | 1,500 × 2 | 0.95 | 3 / 7 | 0.71 | no | 495,924 | 1,065,754 | 0.465 | 0.471 | 0.487 | 0.487 | 1.000 | 0.670 | 0.674 |
| 4 | `mkt-v5-2025-05-20-A1500x2-e3` | peak | 2025-05-20 | 1,500 × 2 | 0.95 | 5 / 10 | 0.75 | no | 1,447,228 | 2,070,392 | 0.699 | 0.700 | 0.217 | 0.226 | 1.000 | 0.642 | 0.643 |
| 5 | `mkt-v5-2025-06-28-A1500x4-e1` | base | 2025-06-28 | 1,500 × 4 | 0.8 | 0 / 0 | 0.71 | no | 138,460 | 192,563 | 0.719 | 0.661 | 0.769 | 0.769 | 0.936 | 0.781 | 0.757 |
| 6 | `mkt-v5-2025-07-30-A1200x2-e1` | peak | 2025-07-30 | 1,200 × 2 | 0.9 | 6 / 9 | 0.75 | no | 986,497 | 1,556,048 | 0.634 | 0.649 | 0.295 | 0.295 | 1.000 | 0.631 | 0.638 |
| 7 | `mkt-v5-2025-08-19-A1500x1-e1` | peak | 2025-08-19 | 1,500 × 1 | 0.85 | 6 / 14 | 0.74 | no | 294,765 | 1,489,192 | 0.198 | 0.209 | 0.066 | 0.066 | 1.000 | 0.339 | 0.335 |
| 8 | `mkt-v5-2025-09-11-A600x1-e1` | base | 2025-09-11 | 600 × 1 | 0.8 | 0 / 0 | 0.88 | no | 19,510 | 70,339 | 0.277 | 0.295 | 0.375 | 0.375 | 1.000 | 0.250 | 0.259 |
| 9 | `mkt-v5-2025-10-29-A1200x2-e1` | base | 2025-10-29 | 1,200 × 2 | 0.9 | 0 / 0 | 0.75 | no | 78,575 | 320,715 | 0.245 | 0.241 | 0.359 | 0.359 | 0.987 | 0.440 | 0.437 |
| 10 | `mkt-v5-2025-11-16-A1500x2-e2` | peak | 2025-11-16 | 1,500 × 2 | 0.95 | 4 / 7 | 0.90 | yes | 258,416 | 438,439 | 0.589 | 0.589 | 0.381 | 0.364 | 1.000 | 0.580 | 0.580 |

- all 10: C — anchor 0.446, price-taker 0.438, max-withhold-then-deviate 0.379, replay A 0.380; R — price-taker 0.980
  (R = 1 on 6), max-withhold 0.808, replay A 0.810; compliant on C — anchor 0.514, price-taker 0.510, max-withhold
  0.484, replay A 0.485, idle 0.004; as built — anchor 0.791, price-taker 0.781.
- 6 peak: C — anchor 0.510, price-taker 0.503, max-withhold 0.308, replay A 0.310.
- 4 base: C — anchor 0.349, price-taker 0.339, max-withhold and replay A 0.486 (R 1.000): on these floors withholding
  the whole DAM and arbitraging RT physically out-captures the anchor's DAM position, so the op-day re-planner, not the
  DAM offer, carries most of a floor-day score there.

Showcase (display only, floor-day): aug24-0820, P_anchor − P_idle $679,869, BR_rt − P_idle $6,981,602, anchor C 0.097;
fern 01-26, $1,376,829 and $9,476,593, anchor C 0.145, 21 impact hours.

Smoke floors (`gridsim-market-train`): smoke-sprint `mkt-v5-2024-08-15-A1000x1-e1`, `mkt-v5-2024-10-04-A800x4-e1`;
smoke-day `mkt-v5-2024-12-22-A1500x1-e1`, `mkt-v5-2024-09-11-A1000x4-e3`.

## Metrics
Computed by `scripts/pilot_v5b.py` from the replay-verified Episode JSON v5, results.jsonl and the pack rows: each
column over all its floors and by stratum (peak, base), the floor-day column apart, floor-day minus floor-sprint paired
on the 10 floors played at both, the rules-5.0 comparison, the showcase floors one line each. CIs are 95% percentile
bootstrap over floors (10,000 resamples, seed 0), paired where a difference is shown.
- **Primary (per column): mean C** with its CI, beside the anchor's C on the same floors and **Δ = C − C_anchor** with
  its paired CI; the count of floors with C < 0. The floor-sprint column is the pilot's primary; the floor-day column's
  is reported apart.
- **Registered secondaries:** the compliant score on clip(C) (the public default) with its CI, next to the compliant
  score as built (R as the profit half); R with its CI, its R = 1 share and the beats-anchor share (P > P_anchor at 6
  decimals); R − price-taker R (paired CI) and the price-making gain (P − P_price-taker)/MW per day (CI); `eps_a` (seat
  A's own ε-Nash share, CI).
- **Baselines on the same floors at the same tier**, each played in process by `baseline_plays`: idle, the anchor, the
  price-taker (the forecast DP's quantities self-scheduled, blind to its own impact), max-withhold and replay A, each on
  C, R and both compliant scores; Sol − baseline on C as (P − P_b)/(BR_rt − P_idle) with paired CIs, and the share of
  floors where Sol's profit beats each.
- **Over-offering:** seat A's final DAM offer's sell MWh over its energy e_mwh (mean and median), its buy MWh over
  e_mwh, its awarded sell MWh over e_mwh, the hours where delivery differs from the awards (floor-sprint: the
  SoC-feasible projection clipping the awards; floor-day: the op-day schedule, not an offering measure) and the floors
  with any, and the `get_forecast` calls and refusals.
- **Weight-0 rows**, as the rules-5.0 pilot: regret_norm and capture against BR_A, welfare ratio and dead-weight loss,
  `eps_mean`, `eps_nash`, A's rank among the seats, conduct (mitigated hours and floors, withholding index, price talk),
  the CfD row, clipped hours, `impact_usd`, the impact-hour MWh A sold against the anchor's and the price-taker's,
  toward-price-taker, fidelity (Spearman of within_ns with C, C and R by fidelity tercile), and play and cost (submits,
  checks, refusals, tokens, $/episode, turns, unscored runs and why, spend per sweep).
- **Against the rules-5.0 pilot** (labelled, never pooled): this pilot's means beside the rules-5.0 pilot's on its own
  floors (its committed Episode JSON v5 in `results/runs/v5-pilot-sol-amend` and `v5-pilot-sol-day`, C against its own
  pack's BR_rt at 4162fda), unpaired; and paired on the floors both played at the same tier (identical stored
  references): C, R, the compliant scores and the over-offering rows. The rules-5.0 pilot's committed values: C 0.348
  floor-sprint (amended) and 0.419 floor-day, its anchor's 0.414 and 0.419; compliant on clip(C) 0.362 and 0.432; R
  0.801 and 0.858; offered sell / e_mwh 5.58 (median 2.99) and 10.28, awarded 4.38 and 6.59; exec ≠ award 6.97 hours a
  floor-sprint floor, on 21 of 30; `get_forecast` refused 113 of 113 floor-sprint and 65 of 120 floor-day calls.

## Hypotheses
- **H1 (headline): Sol's capture against the anchor's.** Δ on the 30 floor-sprint floors: CI above 0, Sol out-captures
  the information-matched anchor; below 0, it captures less; across 0, level at this size. The same reading on the
  floor-day column, reported apart. Expectation: level on both (rules 5.0: −0.067 (−0.202 to +0.057) floor-sprint,
  −0.000 (−0.114 to +0.093) floor-day).
- **H2 (with forecasts now served, Sol's over-offering shrinks).** Registered measure: the mean of offered sell MWh /
  e_mwh over the 30 floor-sprint floors against the rules-5.0 pilot's 30 (5.58): supported if the unpaired 95% CI of
  the difference (5.1 − 5.0) lies below 0, reversed if above, undecided across. Read with it, on the same rule: awarded
  sell / e_mwh (4.38) and exec ≠ award hours a floor (6.97); the paired differences on the 7 floors both pilots played;
  the floor-day column's offered sell / e_mwh (10.28). Expectation beside it: under 10% of `get_forecast` calls refused.
- **H3 (Sol beats the price-taker on peak floors).** C − price-taker C, (P − P_pt)/(BR_rt − P_idle), over the 12 peak
  floor-sprint floors: paired CI above 0 supported, below 0 reversed (the impact-blind price-taker beats Sol), across 0
  undecided at this size; the share of peak floors where Sol's profit beats the price-taker's, R − price-taker R and
  the price-making gain are reported beside it, and the same rows on base floors. (Rules 5.0, R scale: −0.071 (−0.219
  to +0.084), 7 of 12.)
- **H4 (the op day adds capture).** floor-day minus floor-sprint C, paired on the 10 floors played at both: CI above 0
  supported; R and the compliant score on C beside it.
- **H5 (compliant vs profit).** Spearman ρ of C with the welfare ratio over the 30 floor-sprint floors: ≥ 0.3, profit
  and welfare move together and the compliant score re-ranks little; ≤ −0.3, a trade-off; between, no clear relation.
  The ranks of Sol and the five baselines by mean C and by the mean compliant score on C are reported per stratum.
- **H6 (rules 5.0 → 5.1, labelled):** paired C (5.1 − 5.0) on the 7 floor-sprint floors both pilots played: CI above 0
  called better under 5.1, below 0 worse, across 0 undecided (expected at n 7). The unpaired column comparisons are
  reported as descriptive only: different floors, the 5.0 column's at its amended $0.36 cap.
- Expectations, not success bars: Sol is never mitigated on a base floor; on floor-sprint it captures more than
  max-withhold and replay A in every stratum; on floor-day it signs a CfD on fewer than half the floors; the anchor scale
  is compressed for Sol (V2-D1's rule) if more than a third of its floor-sprint floors sit at R = 1.

## Deviations
