# GridSim v1 board

On 24 October 2026 GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort `high`, through LiteLLM) played the v1 board once
per battery-day, as [pre-registered](../docs/prereg/v1-board.md) before the first episode: column **A**, the `full`
harness (3 checks) at the foresight tier, on the 500 held-out days of January to November 2025 (`ercot-dam-v1-eval`);
**B**, the `oneshot` harness (submit only, the training prompt) on the same 500; **C**, `full` at the blind tier on that
pack's 300 blind days; and the optional **D**, `full` at the foresight tier on the 250 days of `ercot-dam-v1-rtcb`,
after ERCOT's real-time co-optimization went live. The overnight v1 build ran the four sweeps for Edgar Arakelyan with
`agent-env gridsim sweep run` on one Linux cloud box, the env and agent as local containers, from 06:58 to 07:22 UTC
(first attempts' starts), and the amendment's four re-run sweeps from 07:25 to 07:30 UTC. The run files don't record the
commit: main's head when the sweeps started was `1f0c24c`, and gridsim_core, the env, the verifier and the agent are the
same from it to the commit that publishes this board. The model spend was $25.88 over 1,635 attempts, 1,550 of them
scored.

Every scored run replays: `agent-env gridsim episodes` played each of the 2,634 recorded tool calls of the 1,550 scored
runs (1,550 submits, 1,051 checks, 33 `get_situation`) again on a fresh env and got the recorded output every time, and
every reward equals both the verifier's and gridsim_core's grade of the schedule (within 1e-6). No run mismatched. The
runs are in the dataset's `v1_episodes` config with their transcripts and replay in 3D in the Space ([links](#links)).

**Headline: the amended columns.** Foresight is saturated: Sol scores 0.9999 on A (99.6% of days optimal), 0.9999 on B
and 1.0000 on D, with no rule broken in any of the 1,550 scored runs. The blind tier separates: R 0.9721 (0.962 to
0.980), r_opt 0.9165 against the blind anchor's own 0.9204 on the same days, beating its anchor on 40.3%.

## The amendment

The board ran under one amendment, made after the sweeps and before this report, recorded as the main session wrote it:

> The pre-registered per-episode cap of $0.10 (4× the smoke median, rounded up) collided with the agent's pessimistic
> pre-request cost guard. It estimates about $0.08-0.11 worst-case per request. So some episodes stopped as unscored
> "cost_cap" failures, all of them guard trips and none model failures: A 14, B 3, C 63, D 5. Retries at the same cap
> failed again. Those exact tasks were re-run once at a $0.40 episode cap, as sweeps `*-amend`. All scored. Both are
> reported: the pre-registered column (scored only) and the amended column (pre-reg scored + amend). The amended column
> is the headline, with this footnote, because dropping 21% of blind days biases toward easy days.

What the files show:

- **The cap.** The smoke sweeps (`smoke-a`, `-b`, `-c`: 10 train days each at full/foresight, oneshot/foresight and
  full/blind, all 30 scored) had median episodes of $0.0126, $0.0073, $0.0148; 4× the largest is $0.0593, rounded up to
  the registered $0.10.
- **The stops.** 85 pre-registered runs stopped with `cost_cap` (A 14, B 3, C 63, D 5), each after 1 or 2 turns and
  $0.0208 to $0.0448 of spend, when the agent's guard put its next request's worst case at $0.0777 to $0.1081, past the
  cap. None had submitted. Each has one attempt in its sweep's `results.jsonl`: `sweep run` counts a cost-cap stop as
  final, so the same-cap retries are not in these files.
- **The re-runs.** The `-amend` sweeps re-ran exactly those 85 tasks once each at a $0.40 episode cap; all 85 scored,
  for $2.46, the dearest episode $0.0539.
- **The bias.** The stops fell on the days that make Sol work hardest: C's 63 re-run days score R 0.9539 (r_opt 0.8865)
  against 0.9769 (0.9245) on the 237 that scored under the cap, so the pre-registered C (0.9769) overstates the full
  column (0.9721). The 22 stopped foresight runs (A, B and D) scored 1.0000 on average on their re-runs.

## Columns

Reward R = clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1): foresight against P_opt, blind against max(P_persist, P_ridge); r_opt is R against P_opt. Mean R over battery-days, its CI a 95% bootstrap over tasks, 10,000 resamples. Optimal: R >= 0.99 (at the blind tier, at or within 1% of the anchor's scale). Valid: submitted and feasible. An amended row adds the amendment's re-runs to the pre-registered sweep's scored runs.

| Column | Scoring | Model | Pack | Tier | Harness | Scored/planned | Mean R (95% CI) | r_opt | Optimal | Valid | Beats anchor | Checks used |
|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|
| A | amended | GPT-6.1 Sol | ercot-dam-v1-eval | foresight | full | 500/500 | 0.9999 (0.9997 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | 1.00 |
| A | pre-registered | GPT-6.1 Sol | ercot-dam-v1-eval | foresight | full | 486/500 | 0.9999 (0.9997 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | 1.00 |
| B | amended | GPT-6.1 Sol | ercot-dam-v1-eval | foresight | oneshot | 500/500 | 0.9999 (0.9998 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | 0.00 |
| B | pre-registered | GPT-6.1 Sol | ercot-dam-v1-eval | foresight | oneshot | 497/500 | 0.9999 (0.9998 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | 0.00 |
| C | amended | GPT-6.1 Sol | ercot-dam-v1-eval | blind | full | 300/300 | 0.9721 (0.9624 to 0.9804) | 0.9165 | 72.3% | 100.0% | 40.3% | 1.00 |
| C | pre-registered | GPT-6.1 Sol | ercot-dam-v1-eval | blind | full | 237/300 | 0.9769 (0.9678 to 0.9846) | 0.9245 | 75.1% | 100.0% | 39.2% | 1.00 |
| D | amended | GPT-6.1 Sol | ercot-dam-v1-rtcb | foresight | full | 250/250 | 1.0000 (0.9999 to 1.0000) | 1.0000 | 100.0% | 100.0% | – | 1.00 |
| D | pre-registered | GPT-6.1 Sol | ercot-dam-v1-rtcb | foresight | full | 245/250 | 1.0000 (0.9999 to 1.0000) | 1.0000 | 100.0% | 100.0% | – | 1.00 |

## Errors

Scored runs whose submitted schedule broke a rule (it executes up to that hour), ended short of the end-of-day state of charge, or idled all day.

| Column | overfill | sell_before_charge | rate | cycle_cap | end_short | all_idle |
|---|---:|---:|---:|---:|---:|---:|
| A eval foresight full | 0 | 0 | 0 | 0 | 0 | 0 |
| B eval foresight oneshot | 0 | 0 | 0 | 0 | 0 | 0 |
| C eval blind full | 0 | 0 | 0 | 0 | 0 | 0 |
| D rtcb foresight full | 0 | 0 | 0 | 0 | 0 | 0 |

## Checks

Runs by the number of `check_schedule` calls, with their mean R (and r_opt at the blind tier); the count of runs in brackets.

| | A eval foresight full | B eval foresight oneshot | C eval blind full | D rtcb foresight full |
|---|---:|---:|---:|---:|
| 0 checks | – | 0.9999 (500) | 0.9978 / 0.9602 (1) | – |
| 1 check | 0.9999 (499) | – | 0.9720 / 0.9164 (299) | 1.0000 (249) |
| 2 checks | 1.0000 (1) | – | – | 1.0000 (1) |

## By battery class, binding constraint and day type

Mean R (and r_opt at the blind tier) over the battery-days in each group, the count in brackets. The binding constraint is the pack's tag for what limits the optimum; a day with negative-price hours and a spike counts in both.

| | A eval foresight full | B eval foresight oneshot | C eval blind full | D rtcb foresight full |
|---|---:|---:|---:|---:|
| 1 h battery | 1.0000 (172) | 1.0000 (172) | 0.9698 / 0.9303 (102) | 1.0000 (81) |
| 2 h battery | 1.0000 (166) | 1.0000 (166) | 0.9653 / 0.9083 (105) | 0.9999 (92) |
| 4 h battery | 0.9997 (162) | 0.9997 (162) | 0.9822 / 0.9106 (93) | 1.0000 (77) |

| | A eval foresight full | B eval foresight oneshot | C eval blind full | D rtcb foresight full |
|---|---:|---:|---:|---:|
| No constraint binds | 0.9999 (169) | 1.0000 (169) | 0.9604 / 0.9149 (94) | 1.0000 (110) |
| Rate | 1.0000 (163) | 0.9999 (163) | 0.9810 / 0.9162 (93) | 0.9999 (69) |
| Cycle cap | 0.9996 (103) | 0.9999 (103) | 0.9714 / 0.9050 (70) | 1.0000 (38) |
| End-of-day charge | 1.0000 (65) | 0.9998 (65) | 0.9793 / 0.9395 (43) | 1.0000 (33) |

| | A eval foresight full | B eval foresight oneshot | C eval blind full | D rtcb foresight full |
|---|---:|---:|---:|---:|
| Negative-price hours | 0.9983 (27) | 0.9998 (27) | 0.9794 / 0.8228 (12) | 1.0000 (25) |
| Price spike | 1.0000 (14) | 1.0000 (14) | 0.9790 / 0.9662 (9) | 1.0000 (3) |
| Neither | 1.0000 (459) | 0.9999 (459) | 0.9715 / 0.9189 (279) | 1.0000 (222) |

## Cost, tokens and time

Per scored run: model spend at the agent's price table, tokens and wall time of the whole `agent-env run`. Spend counts every attempt, the unscored ones included.

| Column | $/episode (median) | Spend (unscored) | Input tokens (cached) | Output tokens | Wall s, median (max) | Attempts | Unscored attempts |
|---|---:|---:|---:|---:|---:|---:|---|
| A eval foresight full | $0.0157 ($0.0145) | $8.24 ($0.39) | 3,012 (51) | 976 | 27.7 (88.1) | 514 | cost_cap 14 |
| B eval foresight oneshot | $0.0117 ($0.0104) | $5.98 ($0.13) | 883 (0) | 994 | 26.8 (96.5) | 503 | cost_cap 3 |
| C eval blind full | $0.0193 ($0.0185) | $7.52 ($1.73) | 5,362 (2,461) | 1,324 | 36.5 (103.1) | 363 | cost_cap 63 |
| D rtcb foresight full | $0.0161 ($0.0140) | $4.15 ($0.13) | 3,072 (68) | 1,005 | 28.6 (94.5) | 255 | cost_cap 5 |

## Baselines on the same tasks

Each reference policy graded by `gridsim_core` at the column's tier on the column's battery-days: mean R, and r_opt at the blind tier; persistence-DP, ridge-DP and the blind anchor need the blind inputs, so on foresight columns they cover only the days that have them (count in brackets). Threshold and greedy read the day's own prices, so at the blind tier they are not policies a blind desk could run.

| | A eval foresight full | B eval foresight oneshot | C eval blind full | D rtcb foresight full |
|---|---:|---:|---:|---:|
| Idle | 0.200 | 0.200 | 0.200 / 0.200 | 0.200 |
| Random feasible | 0.072 | 0.072 | 0.076 / 0.076 | 0.043 |
| Clock | 0.485 | 0.485 | 0.516 / 0.487 | 0.435 |
| Threshold | 0.642 | 0.642 | 0.698 / 0.655 | 0.664 |
| Greedy | 0.761 | 0.761 | 0.821 / 0.783 | 0.724 |
| Persistence-DP | 0.882 (300) | 0.882 (300) | 0.957 / 0.882 | 0.844 (202) |
| Ridge-DP | 0.799 (300) | 0.799 (300) | 0.861 / 0.799 | 0.764 (202) |
| Blind anchor | 0.920 (300) | 0.920 (300) | 1.000 / 0.920 | 0.888 (202) |
| DP optimum | 1.000 | 1.000 | 1.000 / 1.000 | 1.000 |
| **Model** | **1.000** | **1.000** | **0.972** / **0.916** | **1.000** |

LP bound (the convex relaxation, in $) against the exact DP optimum on each column's days:

- A eval foresight full: mean P_opt $11,726.75, mean P_lp $11,726.75; P_lp exceeds P_opt on 0 of 500 days (largest gap $0.00).
- B eval foresight oneshot: mean P_opt $11,726.75, mean P_lp $11,726.75; P_lp exceeds P_opt on 0 of 500 days (largest gap $0.00).
- C eval blind full: mean P_opt $11,417.64, mean P_lp $11,417.64; P_lp exceeds P_opt on 0 of 300 days (largest gap $0.00).
- D rtcb foresight full: mean P_opt $8,699.23, mean P_lp $8,699.23; P_lp exceeds P_opt on 0 of 250 days (largest gap $0.00).

## Hypotheses

The pre-registration's hypotheses, from the spec before any run, against the amended columns.

| Row | Hypothesis | Measured | Reading |
|---|---|---|---|
| Sol, full, foresight (A) | ~0.90-0.95 | 0.9999 (0.9997 to 1.0000) | above the range |
| Sol, oneshot, foresight (B) | below full, by an amount not predicted | 0.9999; B − A +0.0000 over the 500 days (B lower on 4, higher on 5) | not below: no difference |
| Greedy (filtered pack) | ~0.78 (tuned to 0.75-0.80) | 0.761 on A's days | in the tuned band, under 0.78 |
| Threshold | ~0.62 | 0.642 on A's days | near |
| Sol, blind (C) | no prior; first measurement | R 0.9721 (0.9624 to 0.9804), r_opt 0.9165, beats the anchor on 40.3% | first measurement |

## Reading

- **Foresight is saturated for Sol,** as FD-4332 warned it would be for a frontier model: A's mean is 0.9999, 99.6% of
  its 500 days score R ≥ 0.99 (the 2 others 0.968, 0.986), B matches A, and D's 250 post-RTC+B days all score 1.0000.
  Every submitted schedule was valid: no overfill, no sell-before-charge, no rate or cycle-cap break, no end-of-day
  shortfall and no all-idle day in any column. With 24 prices in view, Sol finds the DP's optimum; the foresight tier
  stays the training headline for small models and the check that the harness works, not a way to rank frontier models.
- **The blind tier carries the discrimination.** Sol's r_opt is 0.9165 against the blind anchor's own 0.9204 on the same
  300 days (persistence-DP 0.8820, ridge-DP 0.7988): it sits above persistence-DP and just under the better of the two
  forecasters, which a desk can build from the same inputs. It beats its anchor on 40.3% of the days and scores R ≥ 0.99
  on 72.3%; 21.7% of its blind days score r_opt ≥ 0.99. It does worst on days with negative-price hours (r_opt 0.823 on
  12 days, against 0.919 on the 279 days with neither negative prices nor a spike), and 1 blind day scored below idle.
- **Checking: one check, almost always.** Sol used exactly one of its three checks on 499 of A's 500 runs, 299 of C's
  300 and 249 of D's 250, never three; on 1,046 of the 1,049 runs that checked, the last schedule checked is the one it
  submitted. B, with no checks, scores the same as A, so at the foresight tier the check confirms rather than repairs.
- **Cost.** $25.88 on the model for the whole board, the amendment included: A $0.0157, B $0.0117, C $0.0193, D $0.0161
  a scored episode on average; the median episode took 28 s (A), 27 s (B), 36 s (C), 29 s (D) from container start to
  grade.

## Links

- Every run with its transcript: the dataset's
  [`v1_episodes`](https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv/viewer/v1_episodes).
- The replays in 3D: the [Space](https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv).
- The code: [agentenv-gridsim-plugin](https://github.com/earakely-scale/agentenv-gridsim-plugin); the eval card:
  [`eval-v1.json`](eval-v1.json).

## Unscored runs

| Sweep | Task | Rep | Attempts | Last outcome (spend) | Amendment | Amended outcome |
|---|---|---:|---:|---|---|---|
| v1-board-sol-full | dam-v1-2025-09-20-HB_HUBAVG-2h-v | 1 | 1 | cost_cap ($0.0230) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-02-08-LZ_CPS-4h-y | 1 | 1 | cost_cap ($0.0234) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-10-13-HB_WEST-4h-k | 1 | 1 | cost_cap ($0.0234) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-05-22-HB_BUSAVG-4h-v | 1 | 1 | cost_cap ($0.0286) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-07-31-LZ_CPS-4h-y | 1 | 1 | cost_cap ($0.0281) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-02-08-HB_HUBAVG-4h-v | 1 | 1 | cost_cap ($0.0286) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-08-22-LZ_LCRA-4h-v | 1 | 1 | cost_cap ($0.0382) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-03-17-HB_PAN-4h-w | 1 | 1 | cost_cap ($0.0364) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-02-19-HB_WEST-4h-e | 1 | 1 | cost_cap ($0.0239) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-08-22-HB_SOUTH-4h-v | 1 | 1 | cost_cap ($0.0340) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-06-30-HB_NORTH-4h-v | 1 | 1 | cost_cap ($0.0286) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-07-17-HB_HOUSTON-4h-y | 1 | 1 | cost_cap ($0.0234) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-08-20-LZ_HOUSTON-4h-d | 1 | 1 | cost_cap ($0.0270) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-full | dam-v1-2025-03-13-LZ_LCRA-4h-y | 1 | 1 | cost_cap ($0.0234) | v1-board-sol-full-amend | scored 1.0000 |
| v1-board-sol-oneshot | dam-v1-2025-05-22-HB_BUSAVG-4h-v | 1 | 1 | cost_cap ($0.0427) | v1-board-sol-oneshot-amend | scored 1.0000 |
| v1-board-sol-oneshot | dam-v1-2025-08-22-LZ_LCRA-4h-v | 1 | 1 | cost_cap ($0.0427) | v1-board-sol-oneshot-amend | scored 1.0000 |
| v1-board-sol-oneshot | dam-v1-2025-08-22-HB_SOUTH-4h-v | 1 | 1 | cost_cap ($0.0427) | v1-board-sol-oneshot-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-03-05-LZ_WEST-1h-u | 1 | 1 | cost_cap ($0.0243) | v1-board-sol-blind-amend | scored 0.8837 |
| v1-board-sol-blind | dam-v1-2025-01-24-LZ_CPS-4h-e | 1 | 1 | cost_cap ($0.0279) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-04-09-HB_HOUSTON-2h-b | 1 | 1 | cost_cap ($0.0237) | v1-board-sol-blind-amend | scored 0.7723 |
| v1-board-sol-blind | dam-v1-2025-05-06-LZ_RAYBN-2h-v | 1 | 1 | cost_cap ($0.0226) | v1-board-sol-blind-amend | scored 0.8415 |
| v1-board-sol-blind | dam-v1-2025-11-25-HB_BUSAVG-4h-s | 1 | 1 | cost_cap ($0.0354) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-25-LZ_WEST-4h-y | 1 | 1 | cost_cap ($0.0292) | v1-board-sol-blind-amend | scored 0.9328 |
| v1-board-sol-blind | dam-v1-2025-06-17-HB_BUSAVG-4h-v | 1 | 1 | cost_cap ($0.0233) | v1-board-sol-blind-amend | scored 0.9978 |
| v1-board-sol-blind | dam-v1-2025-11-17-HB_PAN-2h-p | 1 | 1 | cost_cap ($0.0238) | v1-board-sol-blind-amend | scored 0.9524 |
| v1-board-sol-blind | dam-v1-2025-04-26-HB_HUBAVG-2h-c | 1 | 1 | cost_cap ($0.0244) | v1-board-sol-blind-amend | scored 0.9738 |
| v1-board-sol-blind | dam-v1-2025-11-10-LZ_SOUTH-2h-k | 1 | 1 | cost_cap ($0.0283) | v1-board-sol-blind-amend | scored 0.9077 |
| v1-board-sol-blind | dam-v1-2025-02-12-LZ_LCRA-4h-p | 1 | 1 | cost_cap ($0.0250) | v1-board-sol-blind-amend | scored 0.9987 |
| v1-board-sol-blind | dam-v1-2025-06-23-HB_HUBAVG-4h-k | 1 | 1 | cost_cap ($0.0304) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-08-14-LZ_RAYBN-4h-r | 1 | 1 | cost_cap ($0.0448) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-07-15-LZ_WEST-1h-z | 1 | 1 | cost_cap ($0.0227) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-10-14-HB_SOUTH-4h-w | 1 | 1 | cost_cap ($0.0216) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-05-10-LZ_WEST-4h-a | 1 | 1 | cost_cap ($0.0293) | v1-board-sol-blind-amend | scored 0.9136 |
| v1-board-sol-blind | dam-v1-2025-03-17-HB_BUSAVG-2h-t | 1 | 1 | cost_cap ($0.0212) | v1-board-sol-blind-amend | scored 0.9753 |
| v1-board-sol-blind | dam-v1-2025-01-16-HB_BUSAVG-1h-p | 1 | 1 | cost_cap ($0.0243) | v1-board-sol-blind-amend | scored 0.9970 |
| v1-board-sol-blind | dam-v1-2025-04-22-HB_WEST-4h-p | 1 | 1 | cost_cap ($0.0224) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-02-08-HB_HUBAVG-4h-v | 1 | 1 | cost_cap ($0.0448) | v1-board-sol-blind-amend | scored 0.9796 |
| v1-board-sol-blind | dam-v1-2025-11-18-HB_HOUSTON-2h-c | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-05-03-HB_HUBAVG-4h-h | 1 | 1 | cost_cap ($0.0280) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-04-02-HB_PAN-2h-c | 1 | 1 | cost_cap ($0.0304) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-26-LZ_CPS-4h-j | 1 | 1 | cost_cap ($0.0312) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-07-04-HB_WEST-4h-r | 1 | 1 | cost_cap ($0.0235) | v1-board-sol-blind-amend | scored 0.9515 |
| v1-board-sol-blind | dam-v1-2025-05-27-LZ_LCRA-4h-y | 1 | 1 | cost_cap ($0.0277) | v1-board-sol-blind-amend | scored 0.9809 |
| v1-board-sol-blind | dam-v1-2025-05-03-LZ_NORTH-2h-i | 1 | 1 | cost_cap ($0.0242) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-02-19-HB_WEST-4h-e | 1 | 1 | cost_cap ($0.0365) | v1-board-sol-blind-amend | scored 0.9978 |
| v1-board-sol-blind | dam-v1-2025-05-25-LZ_WEST-1h-g | 1 | 1 | cost_cap ($0.0216) | v1-board-sol-blind-amend | scored 0.9954 |
| v1-board-sol-blind | dam-v1-2025-04-24-HB_PAN-4h-h | 1 | 1 | cost_cap ($0.0273) | v1-board-sol-blind-amend | scored 0.9942 |
| v1-board-sol-blind | dam-v1-2025-04-09-LZ_AEN-2h-b | 1 | 1 | cost_cap ($0.0220) | v1-board-sol-blind-amend | scored 0.8434 |
| v1-board-sol-blind | dam-v1-2025-04-12-LZ_SOUTH-4h-w | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-05-09-LZ_CPS-4h-j | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-02-01-LZ_WEST-2h-y | 1 | 1 | cost_cap ($0.0322) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-03-05-LZ_HOUSTON-4h-e | 1 | 1 | cost_cap ($0.0301) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-05-06-HB_HUBAVG-2h-o | 1 | 1 | cost_cap ($0.0282) | v1-board-sol-blind-amend | scored 0.9245 |
| v1-board-sol-blind | dam-v1-2025-04-09-HB_HUBAVG-4h-w | 1 | 1 | cost_cap ($0.0337) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-06-16-HB_WEST-4h-b | 1 | 1 | cost_cap ($0.0225) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-10-27-LZ_RAYBN-4h-e | 1 | 1 | cost_cap ($0.0314) | v1-board-sol-blind-amend | scored 0.9780 |
| v1-board-sol-blind | dam-v1-2025-05-15-HB_PAN-2h-a | 1 | 1 | cost_cap ($0.0260) | v1-board-sol-blind-amend | scored 0.8319 |
| v1-board-sol-blind | dam-v1-2025-11-28-HB_SOUTH-4h-y | 1 | 1 | cost_cap ($0.0284) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-05-10-HB_HOUSTON-2h-z | 1 | 1 | cost_cap ($0.0208) | v1-board-sol-blind-amend | scored 0.1972 |
| v1-board-sol-blind | dam-v1-2025-01-07-HB_PAN-4h-b | 1 | 1 | cost_cap ($0.0227) | v1-board-sol-blind-amend | scored 0.9972 |
| v1-board-sol-blind | dam-v1-2025-10-06-HB_HUBAVG-4h-v | 1 | 1 | cost_cap ($0.0268) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-09-07-HB_BUSAVG-4h-j | 1 | 1 | cost_cap ($0.0215) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-30-HB_HUBAVG-2h-f | 1 | 1 | cost_cap ($0.0285) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-18-LZ_WEST-2h-r | 1 | 1 | cost_cap ($0.0286) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-11-HB_WEST-2h-m | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 0.9311 |
| v1-board-sol-blind | dam-v1-2025-04-17-LZ_LCRA-4h-b | 1 | 1 | cost_cap ($0.0268) | v1-board-sol-blind-amend | scored 0.9837 |
| v1-board-sol-blind | dam-v1-2025-01-13-HB_WEST-4h-b | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-03-04-LZ_NORTH-2h-n | 1 | 1 | cost_cap ($0.0268) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-01-13-LZ_LCRA-4h-j | 1 | 1 | cost_cap ($0.0290) | v1-board-sol-blind-amend | scored 0.9950 |
| v1-board-sol-blind | dam-v1-2025-06-16-LZ_WEST-2h-r | 1 | 1 | cost_cap ($0.0250) | v1-board-sol-blind-amend | scored 0.9932 |
| v1-board-sol-blind | dam-v1-2025-04-20-LZ_LCRA-2h-v | 1 | 1 | cost_cap ($0.0277) | v1-board-sol-blind-amend | scored 0.9862 |
| v1-board-sol-blind | dam-v1-2025-01-27-LZ_RAYBN-4h-z | 1 | 1 | cost_cap ($0.0278) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-01-26-HB_PAN-2h-r | 1 | 1 | cost_cap ($0.0252) | v1-board-sol-blind-amend | scored 0.7164 |
| v1-board-sol-blind | dam-v1-2025-05-04-LZ_RAYBN-4h-r | 1 | 1 | cost_cap ($0.0381) | v1-board-sol-blind-amend | scored 0.9473 |
| v1-board-sol-blind | dam-v1-2025-11-23-LZ_AEN-2h-v | 1 | 1 | cost_cap ($0.0246) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-01-10-HB_NORTH-4h-b | 1 | 1 | cost_cap ($0.0304) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-11-30-HB_BUSAVG-2h-f | 1 | 1 | cost_cap ($0.0239) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-02-07-HB_BUSAVG-4h-y | 1 | 1 | cost_cap ($0.0304) | v1-board-sol-blind-amend | scored 1.0000 |
| v1-board-sol-blind | dam-v1-2025-04-03-LZ_RAYBN-4h-o | 1 | 1 | cost_cap ($0.0262) | v1-board-sol-blind-amend | scored 0.9299 |
| v1-board-sol-blind | dam-v1-2025-11-10-LZ_LCRA-1h-c | 1 | 1 | cost_cap ($0.0369) | v1-board-sol-blind-amend | scored 0.7927 |
| v1-board-sol-rtcb | dam-v1-2026-01-25-LZ_AEN-4h-m | 1 | 1 | cost_cap ($0.0234) | v1-board-sol-rtcb-amend | scored 1.0000 |
| v1-board-sol-rtcb | dam-v1-2026-10-12-LZ_SOUTH-4h-v | 1 | 1 | cost_cap ($0.0278) | v1-board-sol-rtcb-amend | scored 1.0000 |
| v1-board-sol-rtcb | dam-v1-2026-01-16-HB_HUBAVG-4h-s | 1 | 1 | cost_cap ($0.0286) | v1-board-sol-rtcb-amend | scored 1.0000 |
| v1-board-sol-rtcb | dam-v1-2026-04-15-HB_NORTH-4h-y | 1 | 1 | cost_cap ($0.0280) | v1-board-sol-rtcb-amend | scored 1.0000 |
| v1-board-sol-rtcb | dam-v1-2026-09-12-HB_PAN-4h-b | 1 | 1 | cost_cap ($0.0257) | v1-board-sol-rtcb-amend | scored 1.0000 |
