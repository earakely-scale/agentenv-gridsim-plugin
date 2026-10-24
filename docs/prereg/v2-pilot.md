# GridSimEnv v2 pilot: pre-registration (GPT-6.1 Sol, live foresight)

Committed on `v2-preview` before the first pilot episode. Nothing below changes after a run starts, and nothing is rerun to
improve a score. Anything done differently is logged under "Deviations", appended after the run, with this text left
as it is. The pilot gives Edgar data for V2-D1 (the anchor) and gives the viewer v2 replays; it is not the v2 board.

## Code
- Branch `v2-preview` at this commit: lane-v2env + lane-v2core f86139c, plus the prompt fix 7fbb569 (the per-watch
  loop spelled out; get_time reads the virtual clock in UTC). Lane E's single Sol smoke before the fix committed naive at
  watch 0, wrote a summary after the first `advance` and never re-planned.
- Env `gridsim-live` (gateway, triggers, virtual clock frozen at each watch), verifier `gridsim-live-verifier`, run on
  one EC2 box (c7i.8xlarge, local Docker) after `agent-env gridsim setup --agent` and a passing `scripts/live_e2e.py`.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` in live
  mode, 52 turns for every task, 8,192 output tokens a turn, 7,200 s wall limit, 3 planning calls a watch, 1 h freeze.
- One run per task. An infrastructure failure is retried at most twice by the sweep (every attempt is kept).
- Episode cap $0.60 (`GRIDSIM_MAX_COST_USD`). A run stopped at its cap is unscored, as in v1. Each run that ends unscored
  is retried once at a $1.20 cap in the sweep `v2-pilot-sol-amend`, reported as a labelled amendment; the primary
  numbers are the main sweep alone.
- Total budget $15 across the main sweep, the hero and any amendment. The main sweep runs with `--cap-usd 15`; each
  later sweep gets $15 minus the spend so far.

## Tasks
- 40 foresight days of `gridsim-live-eval` (2024), picked by `scripts/pilot_tasks.py` (seed 4321): 20 notice days and 20
  quiet days by the pack's `tags.day_kind`, round-robin over the 15 settlement points in a seeded order, one battery per
  point-day, an undrawn date first. The list and its references are in `docs/prereg/v2-pilot-tasks.json`.
- Known before any run, from the stored references on these 40 days: naive's mean R is 0.850 (notice 0.940, quiet
  0.759); naive scores R = 1.0 on 14 of the 20 notice days (the anchor ties or trails naive there, as L-D9 allows); mean
  hindsight capture is naive 0.425 and anchor 0.498 (notice 0.451 vs 0.450, quiet 0.399 vs 0.546). Seven quiet-tagged
  days still carry notices that do not make a notice day, and two of them get a notice watch.
- Hero, display only and never counted: `live-v2-2023-09-06-HB_NORTH-2h-l` (`sep23-0906`, pack
  `gridsim-live-showcase`), its own sweep `v2-pilot-sol-hero`. HB_NORTH over HB_WEST because there the anchor beats naive
  (naive R 0.596; the anchor commits 3 times) while at HB_WEST the anchor equals naive; both have 10 watches, 5 of them for
  notices.

```
agent-env gridsim sweep run --env gridsim-live --name v2-pilot-sol --models openai/gpt-6.1-sol \
  --pack gridsim-live-eval --tier foresight --tasks "$(python scripts/pilot_tasks.py)" \
  --cap-usd 15 --episode-cap-usd 0.60 --parallel 10
agent-env gridsim sweep run --env gridsim-live --name v2-pilot-sol-hero --models openai/gpt-6.1-sol \
  --pack gridsim-live-showcase --tier foresight --tasks live-v2-2023-09-06-HB_NORTH-2h-l \
  --cap-usd <15 - spent> --episode-cap-usd 0.60 --parallel 1
```

| # | Task | Kind | Point | Date | Watches | Notice watches | Notices | Naive R | Naive capture | Anchor capture |
|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | `live-v2-2024-08-16-HB_NORTH-1h-q` | notice | HB_NORTH | 2024-08-16 | 6 | 1 | 3 | 1.000 | 0.835 | 0.834 |
| 2 | `live-v2-2024-01-08-LZ_LCRA-4h-d` | notice | LZ_LCRA | 2024-01-08 | 6 | 1 | 1 | 1.000 | 0.323 | 0.286 |
| 3 | `live-v2-2024-01-11-LZ_HOUSTON-2h-p` | notice | LZ_HOUSTON | 2024-01-11 | 6 | 1 | 2 | 1.000 | 0.341 | 0.225 |
| 4 | `live-v2-2024-07-06-LZ_AEN-1h-n` | notice | LZ_AEN | 2024-07-06 | 6 | 1 | 3 | 0.623 | 0.252 | 0.478 |
| 5 | `live-v2-2024-08-06-LZ_WEST-2h-o` | notice | LZ_WEST | 2024-08-06 | 8 | 3 | 3 | 1.000 | 0.946 | 0.946 |
| 6 | `live-v2-2024-01-09-LZ_CPS-1h-q` | notice | LZ_CPS | 2024-01-09 | 5 | 0 | 1 | 1.000 | 0.367 | 0.367 |
| 7 | `live-v2-2024-05-10-LZ_RAYBN-2h-a` | notice | LZ_RAYBN | 2024-05-10 | 6 | 1 | 10 | 1.000 | 0.272 | 0.272 |
| 8 | `live-v2-2024-09-09-LZ_SOUTH-1h-b` | notice | LZ_SOUTH | 2024-09-09 | 7 | 2 | 5 | 1.000 | 0.401 | 0.401 |
| 9 | `live-v2-2024-05-17-LZ_NORTH-1h-i` | notice | LZ_NORTH | 2024-05-17 | 6 | 1 | 4 | 1.000 | 0.982 | 0.981 |
| 10 | `live-v2-2024-04-02-HB_SOUTH-4h-u` | notice | HB_SOUTH | 2024-04-02 | 5 | 0 | 2 | 1.000 | 0.546 | 0.546 |
| 11 | `live-v2-2024-11-07-HB_HUBAVG-1h-x` | notice | HB_HUBAVG | 2024-11-07 | 6 | 1 | 1 | 1.000 | 0.089 | 0.089 |
| 12 | `live-v2-2024-06-18-HB_HOUSTON-2h-q` | notice | HB_HOUSTON | 2024-06-18 | 6 | 1 | 1 | 0.737 | 0.047 | 0.069 |
| 13 | `live-v2-2024-03-26-HB_WEST-1h-n` | notice | HB_WEST | 2024-03-26 | 5 | 0 | 1 | 0.979 | 0.607 | 0.623 |
| 14 | `live-v2-2024-05-07-HB_BUSAVG-1h-t` | notice | HB_BUSAVG | 2024-05-07 | 6 | 1 | 1 | 0.953 | 0.603 | 0.641 |
| 15 | `live-v2-2024-05-08-HB_PAN-4h-z` | notice | HB_PAN | 2024-05-08 | 7 | 2 | 5 | 1.000 | 0.561 | 0.560 |
| 16 | `live-v2-2024-05-16-HB_NORTH-1h-d` | notice | HB_NORTH | 2024-05-16 | 7 | 2 | 3 | 1.000 | 0.518 | 0.518 |
| 17 | `live-v2-2024-07-08-LZ_LCRA-4h-i` | notice | LZ_LCRA | 2024-07-08 | 7 | 2 | 7 | 1.000 | 0.088 | -0.119 |
| 18 | `live-v2-2024-05-09-LZ_HOUSTON-1h-t` | notice | LZ_HOUSTON | 2024-05-09 | 6 | 1 | 8 | 0.516 | 0.080 | 0.201 |
| 19 | `live-v2-2024-07-03-LZ_AEN-2h-n` | notice | LZ_AEN | 2024-07-03 | 6 | 1 | 1 | 1.000 | 0.805 | 0.717 |
| 20 | `live-v2-2024-04-28-LZ_WEST-2h-l` | notice | LZ_WEST | 2024-04-28 | 5 | 0 | 3 | 0.998 | 0.358 | 0.359 |
| 21 | `live-v2-2024-06-21-HB_SOUTH-1h-u` | quiet | HB_SOUTH | 2024-06-21 | 5 | 0 | 0 | 0.876 | 0.699 | 0.828 |
| 22 | `live-v2-2024-11-24-HB_NORTH-2h-m` | quiet | HB_NORTH | 2024-11-24 | 5 | 0 | 0 | 0.622 | 0.275 | 0.522 |
| 23 | `live-v2-2024-11-27-LZ_HOUSTON-2h-q` | quiet | LZ_HOUSTON | 2024-11-27 | 5 | 0 | 0 | 0.620 | 0.115 | 0.219 |
| 24 | `live-v2-2024-06-03-HB_BUSAVG-2h-t` | quiet | HB_BUSAVG | 2024-06-03 | 5 | 0 | 0 | 0.648 | 0.287 | 0.513 |
| 25 | `live-v2-2024-11-18-LZ_RAYBN-4h-g` | quiet | LZ_RAYBN | 2024-11-18 | 5 | 0 | 0 | 0.837 | 0.504 | 0.633 |
| 26 | `live-v2-2024-11-06-HB_PAN-2h-l` | quiet | HB_PAN | 2024-11-06 | 5 | 0 | 0 | 0.866 | 0.559 | 0.672 |
| 27 | `live-v2-2024-07-12-HB_WEST-1h-j` | quiet | HB_WEST | 2024-07-12 | 5 | 0 | 4 | 0.737 | 0.318 | 0.474 |
| 28 | `live-v2-2024-01-23-LZ_SOUTH-2h-a` | quiet | LZ_SOUTH | 2024-01-23 | 5 | 0 | 1 | 0.691 | 0.169 | 0.275 |
| 29 | `live-v2-2024-01-05-HB_HOUSTON-1h-n` | quiet | HB_HOUSTON | 2024-01-05 | 5 | 0 | 0 | 0.859 | 0.589 | 0.715 |
| 30 | `live-v2-2024-09-25-LZ_WEST-1h-s` | quiet | LZ_WEST | 2024-09-25 | 5 | 0 | 0 | 0.778 | 0.321 | 0.444 |
| 31 | `live-v2-2024-08-11-LZ_LCRA-1h-k` | quiet | LZ_LCRA | 2024-08-11 | 5 | 0 | 1 | 0.762 | 0.239 | 0.340 |
| 32 | `live-v2-2024-06-18-LZ_NORTH-1h-y` | quiet | LZ_NORTH | 2024-06-18 | 5 | 0 | 0 | 0.705 | 0.254 | 0.403 |
| 33 | `live-v2-2024-01-02-LZ_CPS-1h-g` | quiet | LZ_CPS | 2024-01-02 | 5 | 0 | 0 | 0.611 | 0.148 | 0.288 |
| 34 | `live-v2-2024-08-08-HB_HUBAVG-1h-u` | quiet | HB_HUBAVG | 2024-08-08 | 6 | 1 | 4 | 0.857 | 0.554 | 0.674 |
| 35 | `live-v2-2024-01-29-LZ_AEN-2h-f` | quiet | LZ_AEN | 2024-01-29 | 5 | 0 | 0 | 0.897 | 0.723 | 0.829 |
| 36 | `live-v2-2024-07-09-HB_SOUTH-1h-q` | quiet | HB_SOUTH | 2024-07-09 | 6 | 1 | 9 | 0.880 | 0.700 | 0.823 |
| 37 | `live-v2-2024-01-23-HB_NORTH-2h-c` | quiet | HB_NORTH | 2024-01-23 | 5 | 0 | 1 | 0.694 | 0.228 | 0.369 |
| 38 | `live-v2-2024-07-12-HB_BUSAVG-1h-v` | quiet | HB_BUSAVG | 2024-07-12 | 5 | 0 | 4 | 0.713 | 0.495 | 0.772 |
| 39 | `live-v2-2024-11-24-LZ_RAYBN-4h-y` | quiet | LZ_RAYBN | 2024-11-24 | 5 | 0 | 0 | 0.755 | 0.418 | 0.601 |
| 40 | `live-v2-2024-09-04-HB_PAN-1h-j` | quiet | HB_PAN | 2024-09-04 | 5 | 0 | 0 | 0.767 | 0.378 | 0.534 |

Task 33 is the day of lane E's pre-fix smoke; the smoke is not part of the pilot.

## Metrics
Computed by `scripts/pilot_v2.py` from the replay-verified Episode JSON v2 (`agent-env gridsim episodes`) and
results.jsonl, over all 40 days and separately on notice and quiet days (secondary cuts: days where the anchor differs
from naive, days with a notice watch). CIs are 95% bootstrap over days (2,000 resamples, seed 0), paired where a
difference is shown.
- **R** on the anchor scale: clip(0.2 + 0.8(P − P_idle)/(P_roll − P_idle), 0, 1); no accepted commit scores 0. Also
  naive's R on the same days, R − naive's R, and the share of days at R = 1.
- **Hindsight capture** (P − P_idle)/(P_hind − P_idle), next to naive's and the anchor's capture on the same days, and
  the paired differences Sol − naive and Sol − anchor.
- **Beats naive**: P > P_naive (profit, not R, since naive's R is clipped at 1 on many notice days); ties reported.
  **Beats anchor**: P > P_roll.
- **Re-plan rate**: over all days, the watches after watch 0 with at least one accepted `commit_schedule`, divided by
  all watches after watch 0. Also the share of days with any re-plan, and the anchor's rate ((commits − 1)/(watches − 1)).
- Refused commits, audit failures (a failed audit makes a run unscored; the episodes command re-checks it), the share of
  days the agent finished with its own `advance`, $/episode (priced tokens), turns, unscored runs and why.

## Hypotheses
- FD-4321 estimated frontier API models at ~0.5–0.85 on the spec's old scale (idle 0, naive 0.2, anchor 1.0). On the
  provisional anchor scale (idle 0.2, anchor 1.0), where naive itself scores 0.850 on these days, Sol's R is unknown;
  no point prediction is registered. FD-4321's "the gap should show on notice days" is registered as a direction:
  Sol's beats-anchor rate and capture − anchor are higher on notice days than on quiet days. With 20 days a side the
  pilot is not powered to confirm it; it is read as a signal with its CIs.
- Pilot expectations for the prompt fix, not success bars: Sol finishes the day with its own `advance` on at least 90% of
  scored runs, and re-plans after watch 0 on at least half of the days.
- No direction is registered for Sol's capture against naive's or the anchor's; both are first measurements.

## Reading for V2-D1
Registered before the run, so the reading is not chosen after seeing it: the anchor scale is called compressed for this
model if Sol's mean R is within 0.05 of naive's mean R on the same days while Sol's mean capture differs from naive's
by more than 0.05, or if more than a third of Sol's days sit at R = 1. Either way the pilot reports both scales; the
headline choice (hindsight capture vs R on the anchor scale) stays Edgar's.

## Deviations
None yet.
