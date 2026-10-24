# GridSimEnv v4 pilot: pre-registration (GPT-6.1 Sol, Weather Front)

Committed on `v4-preview` before the first pilot episode. Nothing below changes after a run starts, and nothing is rerun to
improve a score. Anything done differently is logged under "Deviations", appended after the runs, with this text left
as it is. The pilot gives Edgar v4 numbers and the viewer v4 replays; it is not the v4 board.

## Code
- Branch `v4-preview` at this commit: lane-v4env 4b5d5b6 (lane-v4core c92f034; the `gridsim-forecast` env, its bundles
  with the four showcase windows, the verifier, gridsim-llm's DAM-gate guard and forecast nudges, sweep/report v4) with
  lane-v4data 7b88f64 merged (packs built on the forecast store `v4-store@cb47cd9f` under V4-P18 and V4-P19: eval 60 =
  40 front / 20 calm, rtcb 20, showcase 4, train 659). 704 tests pass, ruff clean.
- Every pilot window is an eval or showcase row, which carry their forecast slices inline: no pilot window reads the
  store, so it is not on the box. All 35 pilot windows are `source: ercot` (ERCOT's own load, wind and solar vintages,
  V4-P17); the price guide is the desk's.
- Env `gridsim-forecast` (gateway, one trigger per watch, virtual clock frozen at each watch), verifier
  `gridsim-forecast-verifier`, agent `gridsim-llm`, run on one EC2 box (c7i.8xlarge, Ubuntu 24.04, local Docker) shared
  with another lane: this pilot has its own checkout, venv, agent-env state root and registry prefix, and at most 16
  vCPUs. `agent-env gridsim setup --agent` registered the env and gridsim-llm v1 there.
- Checks on the box before any episode, at this tree: every pilot window's stored P_roll (the anchor), P_blind,
  P_roll3, P_naive and P_idle reproduce to the cent when played in process (35 of 35; the anchor MILP is
  platform-dependent and the eval refs were built on Linux x86_64); `scripts/forecast_e2e.py` (anchor, zero spend)
  passed through Docker on the eval windows 2025-05-03 LZ_HOUSTON and 2025-07-25 LZ_AEN at `front`, 2025-03-29 LZ_SOUTH
  at `front-lite` and fern-0124 at `front`, each scoring R 1.0 at the stored P_anchor to the cent with no problems. The
  bundle's macOS-built Elliott fixture misses its stored anchor by $274.89 on Linux, the known platform tie-break; it
  is not a pilot window.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  v4 desk card (`gridsim_core.forecast_prompt`), 16,384 output tokens a turn, turns per V4-P10 (`front` 122,
  `front-lite` 72), 14,400 s play limit, 3 planning calls and 6 forecast calls a watch, 3 DAM submits a gate, 1 h freeze.
- One run per window. An attempt that fails for infrastructure is retried by the sweep at most twice (three attempts
  in all); every attempt is kept in results.jsonl and counted in the spend. A run stopped at its cost cap or refused by
  the provider is final and unscored. No amendment sweeps.

## Budget and the smoke
- Total cap $60 for everything below, smoke included.
- **Smoke** (`v4-pilot-sol-smoke`): the three smoke windows at `front`, episode cap $5 (the env default), `--cap-usd 15`,
  parallel 3. Let s be its spend and m the median priced cost of its three final attempts.
- **Stop rule:** if any smoke run ends at its $5 cap, or s + 22 m + 10 × 0.6 m > $60 (the main column and the two
  display windows at m, the front-lite column at 0.6 m, its turn cap over front's), nothing else runs and the pilot
  stops for a decision.
- **Episode cap** E = 4 m, rounded up to the cent, for every later sweep (`--episode-cap-usd`).
- **Main sweeps**, run at the same time: `v4-pilot-sol` (20 windows, `front`) with `--cap-usd` (60 − s − 2E) × 20/26
  and `v4-pilot-sol-lite` (10 windows, `front-lite`) with (60 − s − 2E) × 6/26, each rounded down to the cent; parallel
  6 and 4. If a main sweep stops at its cap with runs not final, it is resumed once, after both have stopped, with its
  cap raised to its own spend plus (60 − total spend − 2E).
- **Display** (`v4-pilot-sol-show`): fern-0124 and heather-0114 at `front`, after the main sweeps, `--cap-usd` 60 −
  total spend, parallel 2.

## Tasks
Windows of `ercot-front-v4-eval` (d1 2025-01-01..2025-10-29, all `source: ercot`), picked by
`scripts/pilot_v4_tasks.py` (seed 4324): one seeded draw in slots, each slot a column and a label in a fixed order
(main 14 front / 6 calm, then front-lite 7 / 3, then smoke 2 / 1, calm slots spread evenly); a slot takes the window of
its label, not drawn yet, on a d1 the draw hasn't used, whose settlement point and then month its column has drawn
least, then the point and month the whole draw has drawn least, ties broken by the seeded shuffle. The main column
covers all 13 settlement points and 10 months (no eval window falls in November); all 33 picks have distinct d1. The
list and its references are in `docs/prereg/v4-pilot-tasks.json`.

Known before any run (stored references on these windows, R on the anchor scale: idle 0.2, P_roll 1.0):
- Main column: P_naive 0.643, P_blind 0.720, P_roll3 0.976, anchor hindsight capture 0.477, median P_roll − P_idle
  $46,933. Front windows (14): P_blind 0.666, P_naive 0.607, capture 0.409; calm (6): P_blind 0.848, P_naive 0.729,
  capture 0.636. The anchor commits 18.0 times a window over 19.3 watches (it re-plans at nearly every watch), the
  governor moves 14.9 of its hours, it pays $451 a window of FTP and earns $15,600 of AS. P_blind is below 0.99 on all
  20; P_roll3 is at 0.975 or more on 16 (at 1.0 on 10).
- Front-lite column: P_blind 0.981 (at 0.99 or more on 7 of 10), P_roll3 0.965, P_naive 0.351, anchor capture 0.450,
  median P_roll − P_idle $15,575: at `front-lite` persistence nearly matches the forecast-driven anchor.
- Smoke: P_blind 0.805, P_naive 0.659, capture 0.667. Display: Fern P_blind 0.674, capture 0.603, P_roll − P_idle
  $914,199 (DAM max $1,899); Heather P_blind 0.892, capture 0.768, $1,548,294.

```
python scripts/pilot_v4_tasks.py main --json docs/prereg/v4-pilot-tasks.json
agent-env gridsim sweep run --env gridsim-forecast --name v4-pilot-sol-smoke --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front --tasks "$(python scripts/pilot_v4_tasks.py smoke)" \
  --episode-cap-usd 5 --cap-usd 15 --parallel 3
agent-env gridsim sweep run --env gridsim-forecast --name v4-pilot-sol --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front --tasks "$(python scripts/pilot_v4_tasks.py main)" \
  --episode-cap-usd E --cap-usd "(60 - s - 2E) x 20/26" --parallel 6
agent-env gridsim sweep run --env gridsim-forecast --name v4-pilot-sol-lite --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front-lite --tasks "$(python scripts/pilot_v4_tasks.py lite)" \
  --episode-cap-usd E --cap-usd "(60 - s - 2E) x 6/26" --parallel 4
agent-env gridsim sweep run --env gridsim-forecast --name v4-pilot-sol-show --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-showcase --tier front --tasks "$(python scripts/pilot_v4_tasks.py display)" \
  --episode-cap-usd E --cap-usd "60 - spend" --parallel 2
agent-env gridsim episodes v4-pilot-sol-smoke v4-pilot-sol v4-pilot-sol-lite v4-pilot-sol-show
agent-env gridsim sweep report v4-pilot-sol v4-pilot-sol-lite      # results/eval-v4.json, results/board-v4.md
python scripts/pilot_v4.py v4-pilot-sol --lite v4-pilot-sol-lite --smoke v4-pilot-sol-smoke \
  --display v4-pilot-sol-show --json results/pilot-v4.json
```

Main column (`front` tier, scored):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | P_naive R | P_blind R | P_roll3 R | Anchor capture |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| 1 | `front-v4-2025-05-03-LZ_HOUSTON-pv150-b100x2h-poi150` | front | LZ_HOUSTON | 2025-05-03 | 20 | 0 | yes | 34,464 | 0.317 | 0.845 | 1.000 | 0.558 |
| 2 | `front-v4-2025-07-25-LZ_AEN-pv150-r67-2h-poi150` | calm | LZ_AEN | 2025-07-25 | 19 | 0 | no | 49,336 | 0.439 | 0.931 | 0.998 | 0.635 |
| 3 | `front-v4-2025-03-04-LZ_RAYBN-pv150-r80-1h-poi180` | front | LZ_RAYBN | 2025-03-04 | 20 | 5 | no | 57,515 | 0.758 | 0.640 | 0.984 | 0.540 |
| 4 | `front-v4-2025-08-03-HB_SOUTH-pv200-r40-1h-poi200` | front | HB_SOUTH | 2025-08-03 | 18 | 2 | no | 60,203 | 0.857 | 0.825 | 0.988 | 0.870 |
| 5 | `front-v4-2025-01-21-HB_WEST-pv150-b100x2h-poi150` | calm | HB_WEST | 2025-01-21 | 20 | 2 | no | 113,895 | 0.693 | 0.883 | 0.875 | 0.611 |
| 6 | `front-v4-2025-06-10-LZ_LCRA-pv150-b100x2h-poi180` | front | LZ_LCRA | 2025-06-10 | 19 | 0 | no | 10,682 | 0.000 | 0.177 | 1.000 | 0.135 |
| 7 | `front-v4-2025-10-24-HB_PAN-pv150-b100x2h-poi150` | front | HB_PAN | 2025-10-24 | 20 | 0 | no | 18,158 | 0.616 | 0.473 | 1.000 | 0.177 |
| 8 | `front-v4-2025-04-21-LZ_NORTH-pv150-b100x2h-poi150` | front | LZ_NORTH | 2025-04-21 | 19 | 0 | no | 32,335 | 0.819 | 0.715 | 1.000 | 0.421 |
| 9 | `front-v4-2025-02-24-LZ_WEST-pv150-b100x2h-poi150` | calm | LZ_WEST | 2025-02-24 | 20 | 3 | yes | 52,213 | 0.970 | 0.873 | 1.000 | 0.445 |
| 10 | `front-v4-2025-05-10-LZ_SOUTH-pv150-b100x2h-poi150` | front | LZ_SOUTH | 2025-05-10 | 23 | 5 | no | 36,793 | 0.570 | 0.828 | 0.992 | 0.468 |
| 11 | `front-v4-2025-08-02-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2025-08-02 | 19 | 0 | no | 50,532 | 0.744 | 0.938 | 0.985 | 0.746 |
| 12 | `front-v4-2025-07-05-HB_HOUSTON-pv150-b100x2h-poi180` | calm | HB_HOUSTON | 2025-07-05 | 17 | 0 | no | 35,921 | 0.822 | 0.649 | 1.000 | 0.617 |
| 13 | `front-v4-2025-09-25-LZ_HOUSTON-pv150-b100x2h-poi150` | front | LZ_HOUSTON | 2025-09-25 | 18 | 0 | no | 20,278 | 0.703 | 0.765 | 1.000 | 0.292 |
| 14 | `front-v4-2025-01-01-LZ_NORTH-pv150-r40-2h-poi150` | front | LZ_NORTH | 2025-01-01 | 19 | 1 | yes | 8,010 | 0.505 | 0.814 | 0.933 | 0.270 |
| 15 | `front-v4-2025-08-16-LZ_CPS-pv150-r40-2h-poi150` | calm | LZ_CPS | 2025-08-16 | 19 | 0 | no | 83,739 | 0.777 | 0.867 | 1.000 | 0.661 |
| 16 | `front-v4-2025-03-03-LZ_AEN-pv300-r80-1h-poi360` | front | LZ_AEN | 2025-03-03 | 19 | 5 | no | 55,380 | 0.950 | 0.293 | 1.000 | 0.337 |
| 17 | `front-v4-2025-04-02-LZ_RAYBN-pv200-r67-2h-poi200` | front | LZ_RAYBN | 2025-04-02 | 21 | 4 | yes | 53,088 | 0.367 | 0.731 | 0.864 | 0.355 |
| 18 | `front-v4-2025-10-21-HB_WEST-pv150-b100x2h-poi150` | front | HB_WEST | 2025-10-21 | 20 | 0 | no | 24,167 | 0.458 | 0.542 | 0.909 | 0.181 |
| 19 | `front-v4-2025-06-22-LZ_LCRA-pv300-r80-2h-poi360` | calm | LZ_LCRA | 2025-06-22 | 16 | 0 | no | 121,996 | 0.670 | 0.883 | 0.987 | 0.845 |
| 20 | `front-v4-2025-01-17-LZ_WEST-pv150-b100x2h-poi180` | front | LZ_WEST | 2025-01-17 | 19 | 5 | no | 44,531 | 0.834 | 0.733 | 1.000 | 0.375 |

Secondary column (`front-lite` tier, reported apart, never pooled):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | P_naive R | P_blind R | P_roll3 R | Anchor capture |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| 21 | `front-v4-2025-03-29-LZ_SOUTH-pv200-r80-2h-poi240` | front | LZ_SOUTH | 2025-03-29 | 13 | 0 | yes | 20,753 | 0.194 | 1.000 | 1.000 | 0.222 |
| 22 | `front-v4-2025-10-14-HB_NORTH-pv300-r40-1h-poi300` | calm | HB_NORTH | 2025-10-14 | 12 | 0 | no | 20,104 | 0.149 | 1.000 | 1.000 | 0.755 |
| 23 | `front-v4-2025-05-21-HB_PAN-pv150-b100x2h-poi180` | front | HB_PAN | 2025-05-21 | 14 | 4 | no | 22,512 | 0.430 | 0.972 | 1.000 | 0.547 |
| 24 | `front-v4-2025-06-15-HB_HOUSTON-pv150-b100x2h-poi150` | front | HB_HOUSTON | 2025-06-15 | 11 | 0 | yes | 14,320 | 0.306 | 0.988 | 0.976 | 0.354 |
| 25 | `front-v4-2025-09-01-LZ_WEST-pv150-b100x2h-poi180` | calm | LZ_WEST | 2025-09-01 | 12 | 0 | no | 16,101 | 0.833 | 1.000 | 1.000 | 0.426 |
| 26 | `front-v4-2025-02-19-LZ_HOUSTON-pv300-r40-1h-poi300` | front | LZ_HOUSTON | 2025-02-19 | 13 | 8 | yes | 49,353 | 0.000 | 1.000 | 1.000 | 0.257 |
| 27 | `front-v4-2025-07-13-LZ_NORTH-pv200-r40-1h-poi200` | front | LZ_NORTH | 2025-07-13 | 13 | 0 | no | 7,425 | 0.456 | 1.000 | 1.000 | 0.516 |
| 28 | `front-v4-2025-01-28-HB_WEST-pv150-b100x2h-poi150` | front | HB_WEST | 2025-01-28 | 12 | 0 | no | 15,049 | 0.684 | 1.000 | 0.703 | 0.370 |
| 29 | `front-v4-2025-04-27-LZ_AEN-pv200-r40-2h-poi200` | calm | LZ_AEN | 2025-04-27 | 13 | 0 | no | 13,047 | 0.462 | 0.998 | 0.988 | 0.527 |
| 30 | `front-v4-2025-02-15-LZ_RAYBN-pv200-r40-2h-poi200` | front | LZ_RAYBN | 2025-02-15 | 14 | 5 | no | 7,987 | 0.000 | 0.853 | 0.981 | 0.529 |

Smoke (`front` tier, for the budget; one line each, never pooled):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | P_naive R | P_blind R | P_roll3 R | Anchor capture |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| 31 | `front-v4-2025-07-30-LZ_LCRA-pv100-r40-1h-poi100` | front | LZ_LCRA | 2025-07-30 | 20 | 0 | no | 67,813 | 0.470 | 0.914 | 1.000 | 0.678 |
| 32 | `front-v4-2025-04-08-LZ_SOUTH-pv150-b100x2h-poi150` | calm | LZ_SOUTH | 2025-04-08 | 19 | 0 | no | 86,737 | 0.719 | 0.904 | 1.000 | 0.862 |
| 33 | `front-v4-2025-10-19-HB_PAN-pv200-r40-2h-poi200` | front | HB_PAN | 2025-10-19 | 20 | 0 | no | 49,266 | 0.789 | 0.596 | 1.000 | 0.460 |

Display only (`front` tier, pack `ercot-front-v4-showcase`, never counted):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | P_naive R | P_blind R | P_roll3 R | Anchor capture |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|
| 34 | `front-v4-2026-01-24-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2026-01-24 | 21 | 6 | yes | 914,199 | 0.255 | 0.674 | 0.851 | 0.603 |
| 35 | `front-v4-2024-01-14-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2024-01-14 | 24 | 12 | yes | 1,548,294 | 0.419 | 0.892 | 0.991 | 0.768 |

## Metrics
Computed by `scripts/pilot_v4.py` (committed here) from the replay-verified Episode JSON v4 (`agent-env gridsim
episodes`), results.jsonl and the transcripts: the main column over its 20 windows and by label, the front-lite column
on its own, the smoke and display windows one line each. CIs are 95% bootstrap over windows (10,000 resamples, seed 0),
paired where a difference is shown; front minus calm resamples within each label.
- **Primary: R** on the P_roll anchor scale, clip(0.2 + 0.8(P − P_idle)/(P_roll − P_idle), 0, 1); no accepted hour in
  any `submit_dam` or `commit_schedule` scores 0. Mean over the scored main windows with its CI; the share at R = 1. A
  sensitivity line counts each model-caused unscored window (cost cap, provider refusal) as R = 0.
- **Weight 0, on the same windows:** r_hind (the same formula against P_hind) next to the anchor's; the paired
  (P_agent − P_roll)/(P_hind − P_idle) (`paired_vs_anchor`); beats anchor (P > P_roll at 6 decimals); hindsight
  capture (P − P_idle)/(P_hind − P_idle) next to the anchor's.
- **Baselines, as stored:** P_roll3, P_blind and P_naive on the anchor scale; R − each, paired, with its CI, and the
  share of windows Sol beats each.
- **By label** (front, calm): n, R, r_hind, paired vs anchor (each with its CI), P_blind and R − P_blind; front minus
  calm of the paired vs anchor with its CI.
- **Forecast reading:** `get_forecast` calls by kind (load, wind, solar, weather, price, alerts) and
  `get_forecast_drift` calls, per window; refused calls; the share of windows with at least one call of kind load, wind
  or solar (ERCOT's own forecasts in these windows) and with at least one drift call (the revision history); calls
  with `issued_at`; the share of opened watches with a forecast call; windows where the forecast budget ran out at
  some watch (`forecast_calls_left` 0).
- **DAM gates:** missed gates (no accepted hour) in all and the windows with one; submits per gate; the share of kept
  gates where a successful forecast call came at the gate watch before its first `submit_dam`; gates with
  `pv_da_share` below 1; the harness's gate nudges (an `advance` held back at an open gate). **Revision of Sol's own
  plan at a gate:** for the gates of the second and later days, a gate is eligible when Sol's book for that day, as it
  stood before the gate watch (the last `commit_schedule` or `get_situation` book of an earlier watch), had a non-zero
  hour and the gate accepted an hour; it is revised when the accepted DAM battery position (x_DA − PV DA) differs from
  that book by at least 10% of the battery's P in some accepted hour. Reported: eligible gates, revised share, and the
  share of revised gates read first. ERCOT posts a vintage every hour in these windows, so a revision is always
  available between the earlier plan and the gate.
- **Play:** refusals, FTP MWh charged, governor hours, windows ending short, AS revenue against the anchor's, commits
  against the anchor's, the re-plan rate (watches after watch 0 with an accepted commit over all such watches),
  finished by the agent's own `advance`, audit failures, unscored runs and why, turns, tokens, $ per episode (mean,
  median, max), wall minutes, spend per sweep.

## Hypotheses (main column)
- **H1, forecasts are worth reading for Sol:** Sol's R beats P_blind's on the same windows (stored mean 0.720).
  Supported if the paired CI of R − R_blind lies above 0, refuted if below, undecided otherwise.
- **H2, the front gap:** Sol falls further behind the anchor on front windows than on calm ones: the front minus calm
  difference of paired vs anchor is negative. Supported if its CI lies below 0, refuted if above, undecided otherwise
  (14 against 6 windows: a weak test, read on its CI).
- **H3a, Sol reads ERCOT's own forecasts and their revisions:** supported if at least 75% of the main windows have a
  load, wind or solar call and at least 50% have a drift call; otherwise not supported, with the counts.
- **H3b, Sol revises its DAM position on new forecasts:** supported if at least half of the eligible gates are
  revised; otherwise not supported.
- **H4, the DAM gates hold:** Sol misses at most 1 of the 60 main-column gates.
- Expectations, not success bars: Sol's main-column mean R lies in 0.6 to 0.9 (v3's reserves pilot read 0.811); Sol
  beats P_naive on mean R; Sol's paired vs anchor is negative (P_roll3 sits at 0.976, so the rolling MILP is hard to beat
  on its own scale).

## Readings for the open v4 decisions (registered before the run)
- **Front-lite as a scored tier:** P_blind already sits at 0.981 there; if Sol's front-lite mean R is 0.95 or more, the
  tier is called saturated for this model and stays a training and warm-up tier, not a board column.
- **Anchor scale at `front`:** called compressed for this model, as V2-D1's rule, if more than a third of Sol's main
  windows sit at R = 1.
- **The front/calm label (V4-P19) as a stratifier:** kept as a board breakdown if H2 is supported or refuted (the CI
  excludes 0); called uninformative at this size if undecided.
- **Forecast budget (V4-P14):** called binding if the budget ran out at some watch in a quarter or more of the main
  windows.
- **Turn and watch caps (V4-P10) and the episode cap:** called binding if any main run ends by the turn limit or its
  cost cap.
- **DA PV share (V4-P5):** reported as used if Sol sets `pv_da_share` below 1 at a fifth or more of its kept gates.

## Deviations

None in the registered runs. The smoke spent s = $1.91 (3 scored, $0.586, $0.671, $0.653; m = $0.6533), so the
projection was $20.20 and the pilot went on with E = $2.62, `--cap-usd` 40.65 (main) and 12.19 (front-lite), then
44.76 (display). All 35 runs scored at the first attempt: no retry, no cap stop, no resume, nothing unscored; spend
$16.50 of $60 (smoke $1.91, main $11.40, front-lite $1.93, display $1.26). Every episode replays byte for byte into
Episode JSON v4 on the box (`agent-env gridsim episodes`) and again through a fresh Session on the laptop, every audit
ok. One statement above was loose: the 16-vCPU quota bound the sweep processes, not the Docker containers they
started; the box's load average was at most 11.1 of 32 when sampled with the other lane running. `scripts/pilot_v4.py` is unchanged
since this file's commit; `agent-env gridsim sweep report v4-pilot-sol v4-pilot-sol-lite` wrote `results/eval-v4.json`
and `results/board-v4.md`, and the Pilot and Reading sections were added below the generated board. Results:
`results/board-v4.md`, `results/pilot-v4.json`, the Episode JSON under `results/runs/v4-pilot-sol*/`.
