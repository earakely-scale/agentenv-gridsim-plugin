GridSim: run one battery at an ERCOT hub or load zone for one day on the day-ahead prices, graded exactly against the DP optimum.

Every task deploys the env registered as `gridsim` (run `agent-env gridsim setup` once) and loads one battery-day of
the fixture pack through the env's `urn:gridsim:load-task/v1` extension. The `gridsim-verifier` artifact reads the
episode from the env's `data/get`, grades the submitted schedule again with gridsim_core (it must agree with the env)
and scores the day's reward, with the hindsight capture r_opt as a weight-0 row; a run that submitted nothing scores
0, and an env that can't report fails the step.

The wiring tasks need no model and no agent. Each loads the fixture day `dam-v1-2022-11-14-LZ_WEST-2h-m` at the foresight
tier, and the first two submit a fixed schedule through `urn:gridsim:submit-schedule/v1`, which settles it as the
`submit_schedule` tool does:

- `smoke` submits the task's DP optimum and scores 1.0, so `agent-env run gridsim --task smoke` prints `passed`.
- `wiring-infeasible` submits the optimum with its second discharge hour past the rate limit: that hour and every
  later one execute as 0, the day ends short of its end-of-day state of charge and pays the buy-back, and it scores
  exactly 0.050083, below idle's 0.2.
- `wiring-nosubmit` submits nothing and scores 0.

`full` and `oneshot` play the same day with the gridsim-llm agent (`--model <litellm model id>`): `full` with
get_situation, three checks and submit_schedule; `oneshot` with submit_schedule only, exactly as path B trains.

Prices: ERCOT Day-Ahead Market settlement point prices (NP4-180-ER), public ERCOT data; ERCOT does not endorse this
work. Battery archetypes from EIA-860 (public domain).
