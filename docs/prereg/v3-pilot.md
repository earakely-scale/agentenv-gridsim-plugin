# GridSimEnv v3 pilot: pre-registration (GPT-6.1 Sol, hybrid reserves)

Committed on `v3-preview` before the first pilot episode. Nothing below changes after a run starts, and nothing is rerun to
improve a score. Anything done differently is logged under "Deviations", appended after the run, with this text left
as it is. The pilot gives Edgar v3 numbers and the viewer v3 replays; it is not the v3 board.

## Code
- Branch `v3-preview` at this commit: lane-v3env 3aa5447 (lane-v3core merged, with C3-D17: the anchor's commits are
  never refused), plus 1d788af (`beats_anchor` compares the profit at the stored references' 6 decimals, so the anchor
  does not beat itself). The agent is gridsim-llm with the token-estimating cost guard (b79ae18) and 16,384 output
  tokens a turn on hybrid days (4cf64fa).
- Env `gridsim-hybrid` (gateway, triggers carrying deployment payloads, virtual clock frozen at each watch), verifier
  `gridsim-hybrid-verifier`, run on one EC2 box (c7i.8xlarge, Ubuntu 24.04, local Docker) after
  `agent-env gridsim setup --agent` registers `gridsim-hybrid` and `scripts/hybrid_e2e.py` passes. At 1d788af on the box
  the e2e passed (anchor policy on the bundle day 2022-01-16 LZ_CPS: R 1.0, profit $55,726.09 = the stored P_anchor, no
  problems); both run again at this commit before the first episode.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  hybrid rules card, 52 turns for every task, 16,384 output tokens a turn, 7,200 s wall limit, 3 planning calls a watch,
  1 h freeze (v2's watch machinery).
- One run per task. An infrastructure failure is retried at most twice by the sweep (every attempt is kept).
- Episode cap $1.00 (`GRIDSIM_MAX_COST_USD`, the guard counts tokens). A run stopped at its cap is unscored.
  **Amendment rule:** each run that ends unscored, in any column, is run once more at a $2.00 cap, in a sweep named
  after its own with `-amend` (`v3-pilot-sol-amend`, ...), and reported as a labelled amendment; the primary numbers
  are the first sweeps alone.
- Total budget $25 across every sweep, amendments included. The first sweeps' `--cap-usd`: main $16, energy $5, each
  showcase tier $2 (sum $25), so they may run at the same time; each amendment sweep gets $25 minus the spend so far.

## Tasks
- **Main column (scored):** 30 reserves-tier days of `ercot-hybrid-v3-eval` (2025-01..11, era B), 10 per AS-value
  stratum, picked by `scripts/pilot_v3_tasks.py` (seed 4322): one seeded draw, round-robin over the strata, each pick
  the candidate on an undrawn date whose settlement point and then month its stratum has drawn least, then the point
  and month the whole draw has drawn least. Picks 1-30 cover all 13 points (1 to 3 days each), all 11 months (2 or 3
  each) and 30 distinct dates; 10 are notice days, none is a deployment day (the pack has 12), 2 have negative-price
  hours. The list and its references are in `docs/prereg/v3-pilot-tasks.json`.
- **Secondary column (reported separately, never pooled):** picks 31-40 of the same draw (4 low, 3 mid, 3 high), played
  at the `energy` tier.
- **Display only, never counted:** the showcase day mar29-2024
  (`hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150`, pack `ercot-hybrid-v3-showcase`, 16 negative DA hours), at the
  energy and the reserves tier, one sweep each.
- Not used: the sept06-2023 hero, broken at the reserves tier (seeded drift leaves its T2 anchor below energy-only).
- **Known before any run** (stored references on these days; R on the anchor scale, idle 0.2, anchor 1.0):
  - Main column: AS-hog 0.464, energy-only MILP 0.836, v2 energy-only 0.836, anchor hindsight capture 0.480. The
    energy-only MILP and v2 energy-only are identical on all 30 days (AC-only sites with POI >= PV AC never clip, so
    the PV-blind policy gives up nothing). By stratum (low/mid/high): AS-hog 0.479/0.411/0.503, energy-only
    0.853/0.870/0.786, anchor capture 0.416/0.404/0.619. AS-hog scores 0 on 3 days and beats energy-only on 2. The
    anchor commits 2.33 times a day, the governor moves 4.0 of its hours, it pays $13.76 a day of FTP and earns $6,241
    a day of AS; P_anchor − P_idle has a median of $12,288.
  - Energy column: v2 energy-only 0.979 (R = 1 on 8 of 10 days), anchor capture 0.484.
  - Showcase: energy tier v2 energy-only 1.0, anchor capture 0.840; reserves tier AS-hog 0.691, energy-only 0.587,
    anchor capture 0.920.

```
python scripts/pilot_v3_tasks.py main --json docs/prereg/v3-pilot-tasks.json
agent-env gridsim sweep run --env gridsim-hybrid --name v3-pilot-sol --models openai/gpt-6.1-sol \
  --pack ercot-hybrid-v3-eval --tier reserves --tasks "$(python scripts/pilot_v3_tasks.py main)" \
  --cap-usd 16 --episode-cap-usd 1.00 --parallel 10
agent-env gridsim sweep run --env gridsim-hybrid --name v3-pilot-sol-energy --models openai/gpt-6.1-sol \
  --pack ercot-hybrid-v3-eval --tier energy --tasks "$(python scripts/pilot_v3_tasks.py energy)" \
  --cap-usd 5 --episode-cap-usd 1.00 --parallel 5
agent-env gridsim sweep run --env gridsim-hybrid --name v3-pilot-sol-show-energy --models openai/gpt-6.1-sol \
  --pack ercot-hybrid-v3-showcase --tier energy --tasks hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 \
  --cap-usd 2 --episode-cap-usd 1.00 --parallel 1
agent-env gridsim sweep run --env gridsim-hybrid --name v3-pilot-sol-show-reserves --models openai/gpt-6.1-sol \
  --pack ercot-hybrid-v3-showcase --tier reserves --tasks hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150 \
  --cap-usd 2 --episode-cap-usd 1.00 --parallel 1
agent-env gridsim episodes v3-pilot-sol v3-pilot-sol-energy v3-pilot-sol-show-energy v3-pilot-sol-show-reserves
agent-env gridsim sweep report v3-pilot-sol v3-pilot-sol-energy      # results/eval-v3.json, results/board-v3.md
python scripts/pilot_v3.py v3-pilot-sol --energy v3-pilot-sol-energy \
  --showcase v3-pilot-sol-show-energy v3-pilot-sol-show-reserves --json results/pilot-v3.json
```

Main column (reserves tier):

| # | Task | Stratum | Point | Date | Watches | Notice day | AS value ($) | Anchor − idle ($) | AS-hog R | Energy-only R | v2 energy-only R | Anchor capture |
|---:|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `hyb-v3-2025-01-24-LZ_AEN-pv100-r40-2h-poi120` | low | LZ_AEN | 2025-01-24 | 5 | no | 911 | 4,632 | 0.339 | 0.905 | 0.905 | 0.355 |
| 2 | `hyb-v3-2025-09-03-LZ_SOUTH-pv300-r80-2h-poi300` | mid | LZ_SOUTH | 2025-09-03 | 5 | no | 3,164 | 29,679 | 0.412 | 0.928 | 0.928 | 0.443 |
| 3 | `hyb-v3-2025-07-30-HB_HOUSTON-pv150-b100x2h-poi150` | high | HB_HOUSTON | 2025-07-30 | 5 | no | 4,846 | 88,348 | 0.441 | 0.960 | 0.960 | 0.913 |
| 4 | `hyb-v3-2025-04-24-HB_WEST-pv150-b100x2h-poi150` | low | HB_WEST | 2025-04-24 | 5 | no | 1,894 | 13,290 | 0.563 | 0.945 | 0.945 | 0.385 |
| 5 | `hyb-v3-2025-03-25-LZ_RAYBN-pv150-r40-2h-poi150` | mid | LZ_RAYBN | 2025-03-25 | 5 | no | 3,490 | 12,975 | 0.541 | 0.820 | 0.820 | 0.634 |
| 6 | `hyb-v3-2025-05-21-LZ_WEST-pv150-r80-1h-poi150` | high | LZ_WEST | 2025-05-21 | 6 | yes | 4,392 | 18,833 | 0.686 | 0.754 | 0.754 | 0.715 |
| 7 | `hyb-v3-2025-10-27-HB_NORTH-pv150-b100x2h-poi180` | low | HB_NORTH | 2025-10-27 | 5 | no | 1,878 | 14,958 | 0.623 | 0.913 | 0.913 | 0.316 |
| 8 | `hyb-v3-2025-06-16-LZ_CPS-pv150-b100x2h-poi180` | mid | LZ_CPS | 2025-06-16 | 5 | no | 2,863 | 10,427 | 0.685 | 0.831 | 0.831 | 0.347 |
| 9 | `hyb-v3-2025-08-03-LZ_HOUSTON-pv300-r67-2h-poi300` | high | LZ_HOUSTON | 2025-08-03 | 5 | no | 4,730 | 21,729 | 0.588 | 0.868 | 0.868 | 0.698 |
| 10 | `hyb-v3-2025-02-03-LZ_LCRA-pv300-r40-1h-poi300` | low | LZ_LCRA | 2025-02-03 | 5 | no | 1,852 | 6,482 | 0.562 | 0.871 | 0.871 | 0.552 |
| 11 | `hyb-v3-2025-11-25-LZ_NORTH-pv150-b100x2h-poi180` | mid | LZ_NORTH | 2025-11-25 | 5 | no | 3,541 | 13,145 | 0.489 | 0.803 | 0.803 | 0.399 |
| 12 | `hyb-v3-2025-09-25-HB_SOUTH-pv200-r80-1h-poi200` | high | HB_SOUTH | 2025-09-25 | 5 | no | 4,284 | 9,612 | 0.481 | 0.707 | 0.707 | 0.288 |
| 13 | `hyb-v3-2025-07-27-HB_PAN-pv150-r40-2h-poi150` | low | HB_PAN | 2025-07-27 | 5 | yes | 1,024 | 2,549 | 0.476 | 0.790 | 0.790 | 0.475 |
| 14 | `hyb-v3-2025-10-07-HB_PAN-pv300-r40-1h-poi360` | mid | HB_PAN | 2025-10-07 | 6 | yes | 2,092 | 10,871 | 0.578 | 0.864 | 0.864 | 0.332 |
| 15 | `hyb-v3-2025-03-13-LZ_AEN-pv300-r40-1h-poi360` | high | LZ_AEN | 2025-03-13 | 6 | yes | 3,838 | 9,649 | 0.338 | 0.780 | 0.780 | 0.519 |
| 16 | `hyb-v3-2025-06-15-HB_HOUSTON-pv150-r40-2h-poi150` | low | HB_HOUSTON | 2025-06-15 | 5 | no | 1,694 | 5,925 | 0.633 | 0.781 | 0.781 | 0.695 |
| 17 | `hyb-v3-2025-01-11-LZ_WEST-pv300-r80-2h-poi300` | mid | LZ_WEST | 2025-01-11 | 5 | yes | 2,333 | 26,439 | 0.000 | 0.845 | 0.845 | 0.448 |
| 18 | `hyb-v3-2025-02-22-LZ_RAYBN-pv300-r67-1h-poi300` | high | LZ_RAYBN | 2025-02-22 | 5 | yes | 5,151 | 20,091 | 0.370 | 0.833 | 0.833 | 0.635 |
| 19 | `hyb-v3-2025-11-27-LZ_CPS-pv200-r40-1h-poi240` | low | LZ_CPS | 2025-11-27 | 5 | no | 1,827 | 3,030 | 0.804 | 0.738 | 0.738 | 0.192 |
| 20 | `hyb-v3-2025-04-02-LZ_HOUSTON-pv200-r80-2h-poi200` | mid | LZ_HOUSTON | 2025-04-02 | 5 | no | 3,226 | 44,426 | 0.491 | 0.953 | 0.953 | 0.547 |
| 21 | `hyb-v3-2025-11-01-HB_WEST-pv150-b100x2h-poi180` | high | HB_WEST | 2025-11-01 | 5 | yes | 4,976 | 11,601 | 0.348 | 0.801 | 0.801 | 0.269 |
| 22 | `hyb-v3-2025-08-15-HB_SOUTH-pv200-r40-2h-poi200` | low | HB_SOUTH | 2025-08-15 | 5 | no | 1,310 | 2,708 | 0.000 | 0.919 | 0.919 | 0.181 |
| 23 | `hyb-v3-2025-05-24-LZ_LCRA-pv150-b100x2h-poi150` | mid | LZ_LCRA | 2025-05-24 | 5 | yes | 2,358 | 9,103 | 0.484 | 0.940 | 0.940 | 0.518 |
| 24 | `hyb-v3-2025-01-21-LZ_NORTH-pv150-b100x2h-poi150` | high | LZ_NORTH | 2025-01-21 | 5 | yes | 6,337 | 34,356 | 0.260 | 0.853 | 0.853 | 0.823 |
| 25 | `hyb-v3-2025-09-20-LZ_SOUTH-pv150-b100x2h-poi150` | low | LZ_SOUTH | 2025-09-20 | 5 | no | 1,555 | 5,585 | 0.382 | 0.746 | 0.746 | 0.730 |
| 26 | `hyb-v3-2025-07-12-HB_SOUTH-pv150-b100x2h-poi180` | mid | HB_SOUTH | 2025-07-12 | 5 | no | 2,288 | 6,481 | 0.000 | 0.825 | 0.825 | 0.066 |
| 27 | `hyb-v3-2025-04-03-HB_PAN-pv200-r80-2h-poi200` | high | HB_PAN | 2025-04-03 | 6 | yes | 7,346 | 25,671 | 0.742 | 0.777 | 0.777 | 0.703 |
| 28 | `hyb-v3-2025-03-30-LZ_NORTH-pv150-b100x2h-poi180` | low | LZ_NORTH | 2025-03-30 | 5 | no | 1,313 | 15,551 | 0.408 | 0.927 | 0.927 | 0.284 |
| 29 | `hyb-v3-2025-08-01-LZ_AEN-pv150-b100x2h-poi150` | mid | LZ_AEN | 2025-08-01 | 5 | no | 3,515 | 16,251 | 0.425 | 0.891 | 0.891 | 0.307 |
| 30 | `hyb-v3-2025-06-23-LZ_SOUTH-pv150-b100x2h-poi150` | high | LZ_SOUTH | 2025-06-23 | 5 | no | 5,306 | 8,482 | 0.772 | 0.527 | 0.527 | 0.626 |

Secondary column (energy tier):

| # | Task | Stratum | Point | Date | Watches | Notice day | Anchor − idle ($) | v2 energy-only R | Anchor capture |
|---:|---|---|---|---|---:|---|---:|---:|---:|
| 31 | `hyb-v3-2025-10-08-LZ_WEST-pv150-r40-2h-poi150` | low | LZ_WEST | 2025-10-08 | 6 | yes | 4,926 | 1.000 | 0.285 |
| 32 | `hyb-v3-2025-02-07-HB_WEST-pv300-r40-1h-poi300` | mid | HB_WEST | 2025-02-07 | 5 | no | 4,675 | 1.000 | 0.353 |
| 33 | `hyb-v3-2025-11-08-HB_NORTH-pv150-b100x2h-poi150` | high | HB_NORTH | 2025-11-08 | 5 | no | 5,732 | 0.919 | 0.628 |
| 34 | `hyb-v3-2025-09-07-LZ_HOUSTON-pv200-r67-2h-poi200` | low | LZ_HOUSTON | 2025-09-07 | 5 | no | 4,379 | 1.000 | 0.461 |
| 35 | `hyb-v3-2025-10-14-HB_NORTH-pv200-r40-1h-poi240` | mid | HB_NORTH | 2025-10-14 | 5 | no | 5,740 | 1.000 | 0.641 |
| 36 | `hyb-v3-2025-05-15-LZ_LCRA-pv100-r67-2h-poi100` | high | LZ_LCRA | 2025-05-15 | 6 | yes | 29,940 | 0.872 | 0.876 |
| 37 | `hyb-v3-2025-04-18-LZ_RAYBN-pv150-r40-2h-poi150` | low | LZ_RAYBN | 2025-04-18 | 5 | no | 1,475 | 1.000 | 0.199 |
| 38 | `hyb-v3-2025-08-10-HB_HOUSTON-pv200-r80-2h-poi200` | mid | HB_HOUSTON | 2025-08-10 | 5 | no | 10,597 | 1.000 | 0.291 |
| 39 | `hyb-v3-2025-06-24-LZ_CPS-pv200-r67-2h-poi200` | high | LZ_CPS | 2025-06-24 | 5 | no | 7,212 | 1.000 | 0.636 |
| 40 | `hyb-v3-2025-03-28-LZ_WEST-pv150-b100x2h-poi180` | low | LZ_WEST | 2025-03-28 | 5 | no | 11,469 | 1.000 | 0.465 |

## Metrics
Computed by `scripts/pilot_v3.py` from the replay-verified Episode JSON v3 (`agent-env gridsim episodes`) and
results.jsonl: the main column over all 30 days, by AS stratum and on notice and quiet days; the energy column on its
own; the showcase day as one line per tier. CIs are 95% bootstrap over days (2,000 resamples, seed 0), paired where a
difference is shown.
- **R** on the anchor scale: clip(0.2 + 0.8(P − P_idle)/(P_anchor − P_idle), 0, 1); no accepted hour in any commit
  scores 0. Also the share of days at R = 1, and R by AS stratum.
- **Baselines on the same days:** idle (0.2), AS-hog, the energy-only MILP (the energy-tier anchor graded against the
  reserves anchor) and v2 energy-only, each as stored; R − each baseline's R, paired. Beats a baseline compares profit.
  **Beats anchor:** P > P_anchor at 6 decimals (the grade's `beats_anchor`).
- **Hindsight capture** (P − P_idle)/(P_hind − P_idle), next to the anchor's on the same days, and capture − anchor.
- **AS share** (the grade's: AS revenue / (AS revenue + energy gain over idle)); AS revenue against the anchor's (mean
  $ a day, median ratio); the DA AS book in MWh per product against the anchor's.
- **FTP MWh**, charged and excused (C3-D7), in total and per product (each episode replayed through
  `gridsim_core.hybrid.Session`); days with FTP charged; governor hours; days ending short of `s_end_min`.
- **Under-reserved:** a day is under-reserved in a product when FTP was charged on it or a commit row naming it was
  refused under `reserve_up` or `reserve_dn` (the plan's awards needed SoC its own path did not hold).
- **Refusals by rule:** refused rows in `commit_schedule` outputs counted by rule (`check_schedule` issues by rule
  reported apart), refused commits and the days with one.
- **Re-plan rate:** the watches after watch 0 with an accepted `commit_schedule` (at least one committed hour), over
  all watches after watch 0; the share of days with any re-plan; the anchor's rate ((commits − 1)/(watches − 1)).
- **Cost and play:** input, output and cached tokens per episode, $/episode (priced tokens), turns, the share of days
  finished by the agent's own `advance`, audit failures, unscored runs and why, spend per sweep.

## Hypotheses
- **H1 (the v3 plan's frontier estimate):** Sol's zero-shot mean R on the main column lies in 0.65 to 0.85. Read on the
  point estimate, its CI reported.
- **H2 (the v3 plan's expected failure): Sol under-reserves ECRS SoC.** Called supported if at least 6 of the 30 main days
  are under-reserved in some product and ECRS has the most under-reserved days of the five products; otherwise not
  supported, with the failures that were seen. Registered alternative, read on its own: Sol **under-bids AS** if its
  median AS revenue on the main column is below half the anchor's on the same day.
- Expectations, not success bars: Sol beats AS-hog on mean R; on the energy column Sol's mean R is 0.95 or more. No
  direction is registered against the energy-only MILP or v2 energy-only (0.836 here).

## Readings for the open v3 decisions (registered before the run)
- **Energy tier (decision 2, sites that clip):** if Sol's energy-column mean R is 0.95 or more, the energy tier on
  AC-only sites is called saturated for this model, and it stays a secondary column until sites that clip (dc coupling
  or POI < PV AC) are in the packs.
- **The reserves tier as the test:** if the CI of Sol's main-column R − energy-only R lies below 0, the reserves tier is
  called harder than energy-only arbitrage for this model (Sol's AS play loses money against simply skipping AS); above
  0, Sol is called to earn from co-optimising AS; across 0, undecided at this size.
- **Anchor scale:** called compressed for this model, as V2-D1's rule, if more than a third of Sol's main days sit at
  R = 1.

## Deviations

None in the runs. All 42 runs scored at the first attempt and none reached the $1.00 cap, so no amendment sweep ran;
the four sweeps ran at the same time as registered and spent $7.03 in all (main $5.70, energy $0.86, showcase $0.05
and $0.42). One change to the report code, none to a registered number: `sweep report` averaged each tier's baselines
over all 40 days of the two sweeps (the reserves line read AS-hog 0.465 and energy-only 0.814), and f2ab862 averages
each tier's over its own days before `results/board-v3.md` was written. `scripts/pilot_v3.py`, which computes the
registered metrics, is unchanged. Results: `results/board-v3.md` (Pilot and Reading), `results/pilot-v3.json`.
