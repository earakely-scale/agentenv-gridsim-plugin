---
license: other
license_name: ercot-website-user-agreement-eia-public-domain-apache-2.0
license_link: https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/v0.1.0/data/LICENSE
pretty_name: 'GridSimEnv v1: The Battery Desk'
language:
- en
task_categories:
- reinforcement-learning
- text-generation
size_categories:
- 10K<n<100K
tags:
- agentenv
- rl-environment
- agents
- simulation
- energy
- electricity-markets
- battery-storage
- ercot
- operations-research
- mcp
- real-world-data
- grpo
- trl
configs:
- config_name: v1_tasks
  default: true
  data_files:
  - split: train
    path: tasks/v1/train.parquet
  - split: eval_2025
    path: tasks/v1/eval_2025.parquet
  - split: eval_iid
    path: tasks/v1/eval_iid.parquet
  - split: rtcb
    path: tasks/v1/rtcb.parquet
- config_name: v1_showcase
  data_files:
  - split: showcase
    path: tasks/v1/showcase.parquet
- config_name: v1_references
  data_files:
  - split: train
    path: references/v1/train.parquet
  - split: eval_2025
    path: references/v1/eval_2025.parquet
  - split: eval_iid
    path: references/v1/eval_iid.parquet
  - split: rtcb
    path: references/v1/rtcb.parquet
  - split: showcase
    path: references/v1/showcase.parquet
- config_name: v1_episodes
  data_files:
  - split: eval_2025
    path: episodes/v1/eval_2025.parquet
---

<div align="center">

<!-- TODO: hero still or clip of the battery yard from the viewer lane, linking to the Space's hero day -->

<h1>GridSimEnv v1: The Battery Desk</h1>

<h3>Run a grid battery at a Texas hub for one day on the real day-ahead prices, graded exactly against the optimum</h3>

<p>An AgentEnv environment built from ERCOT's public day-ahead market prices and EIA-860 battery records, with 21,250 battery-days, a public train split and no judge: every schedule is scored against a dynamic program that finds the best possible day.</p>

<a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Space-Replays-FFD21E?style=for-the-badge&labelColor=1a1a1a" alt="Replays" height="32"></a>
<a href="https://github.com/earakely-scale/agentenv-gridsim-plugin"><img src="https://img.shields.io/badge/GitHub-agentenv--gridsim--plugin-181717?style=for-the-badge&logo=github&labelColor=1a1a1a" alt="Code on GitHub" height="32"></a>
<a href="https://www.agentenvframework.com"><img src="https://img.shields.io/badge/framework-AgentEnv-6f42c1?style=for-the-badge&labelColor=1a1a1a" alt="AgentEnv Framework" height="32"></a>

</div>

---

## The task

An agent operates one battery in the ERCOT day-ahead market (DAM) for one operating day at one of ERCOT's 7 trading
hubs or 8 load zones. It reads the battery and the day's 24 hourly DAM settlement point prices, then submits 24
integers, one per hour ending (HE01 to HE24, Central Prevailing Time): how many energy units to sell (positive) or buy
(negative) that hour. The battery is a price taker, so each hour settles at that hour's price. The schedule is graded
once, exactly, against the best schedule a dynamic program finds for the same day.

The battery moves energy in whole units of `unit_mwh` MWh and holds 0 to `soc_levels` units. The rules:

1. Each hour, `-k_ch <= a <= k_dis`.
2. The state of charge stays between 0 and `soc_levels` after every hour; selling `a` units lowers it by `a`.
3. The units discharged over the day sum to at most `cycle_cap_units`.
4. At the first hour that breaks rule 1, 2 or 3, that hour and every later hour execute as 0; the hours before still
   settle.
5. The state of charge after HE24 must be at least `s_end_min`. Each missing unit is bought back at `unit_mwh / eta`
   MWh times the day's highest price, or $50/MWh if that is higher.

Selling `a` units delivers `a * unit_mwh` MWh. Buying `a` units draws `a * unit_mwh / eta` MWh, so the losses fall on
the buy side. Each unit discharged costs `c_deg * unit_mwh` dollars of degradation. Profit is the sum of the hourly
cash less the end-of-day penalty.

The env exposes three tools: `get_situation`, `check_schedule` (up to 3 dry runs that return feasibility, the state
of charge path, any end shortfall and, at the foresight tier, the profit) and `submit_schedule`, which ends the
episode. An episode allows 4 turns and 24 tool calls. The `oneshot` harness, which training uses, offers only
`submit_schedule`.

**Two tiers.** At the **foresight** tier the agent sees the day's 24 prices. At the **blind** tier it sees the prices
at the same point for the previous day and for each of the previous 7 days, not the day's own, and its schedule
settles on the day's actual prices. Each row of `v1_tasks` is one battery-day at one tier; a battery-day with blind
inputs appears once per tier.

### A worked day

`dam-v1-2025-02-25-LZ_AEN-2h-o`, from `eval_2025`: the Austin Energy load zone on Tuesday 25 February 2025, with a
150 MW / 300 MWh battery (archetype `2h-o`): `unit_mwh` 75, `soc_levels` 4, `k_dis` = `k_ch` = 2 (150 MW),
`eta` 0.80, `c_deg` $4/MWh, `cycle_cap_units` 6 (1.5 cycles), starting empty and free to end empty. The prices, in
$/MWh:

| HE | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| $/MWh | 22.49 | 22.77 | 23.97 | 25.86 | 31.00 | 41.90 | 49.57 | 46.44 | 27.87 | 21.10 | 18.18 | 17.00 | 14.61 | 14.45 | 12.61 | 10.79 | 16.16 | 29.37 | 49.59 | 34.00 | 27.89 | 23.32 | 21.26 | 20.23 |

The day has two peaks, at HE07 and HE19. The optimum takes both, and its second round trip uses the last two units
of the cycle cap:

| HE | Price | Action | MWh | Cash | State of charge after |
|---|---:|---:|---:|---:|---:|
| 01 | 22.49 | −2 (buy) | −187.5 | −$4,216.88 | 2 |
| 07 | 49.57 | +2 (sell) | 150 | $6,835.50 | 0 |
| 15 | 12.61 | −2 | −187.5 | −$2,364.38 | 2 |
| 16 | 10.79 | −2 | −187.5 | −$2,023.12 | 4 |
| 19 | 49.59 | +2 | 150 | $6,838.50 | 2 |
| 20 | 34.00 | +2 | 150 | $4,500.00 | 0 |

Every other hour is idle. The day's profit is **$9,569.63** (P_opt; doing nothing earns $0), net of $1,800 of
degradation, and scores 1.0. The pack's references on the same day: the greedy rule, which pairs the cheapest hours
with the dearest later ones, makes one evening round trip for $4,815.38 (reward 0.603); the threshold rule $5,411.63
(0.652); the clock rule, which charges HE02 to HE05 and sells HE18 to HE21, $1,880.25 (0.357). At the blind tier the
anchor is the DP schedule on the previous day's prices, settled on this day: $8,937.75, a hindsight capture (`r_opt`)
of 0.947.

## Grading

A schedule's reward is

    R = clip(0.2 + 0.8 * (P - P_idle) / (P_anchor - P_idle), 0, 1)

where P is its profit, P_idle the profit of doing nothing (negative for the 12 of the 78 battery designs whose end
obligation is above their starting charge) and P_anchor the reference with the same information as the agent:

- **foresight**: P_opt, the exact optimum. A dynamic program over the state of charge, the units discharged so far
  and every allowed action finds it in under a millisecond, with ties broken deterministically. An LP relaxation
  bound (`p_lp`) is reported beside it: over every candidate day, the bound exceeds the optimum by at most 4.2% of
  its margin over idle, and by nothing up to the 99th percentile.
- **blind**: max(P_persist, P_ridge), the better of two schedules a desk could make from the same lagged prices,
  each the DP schedule on a price forecast, settled on the actual day: persistence (the previous day's prices) and a
  lagged ridge regression (`raw/packs/ridge-v1.json`). The blind headline is `r_opt`, the same formula against P_opt.

Idle scores 0.2, the anchor 1.0. A run that never submits a parseable schedule scores 0; there is no format credit.
The hindsight capture `r_opt` (the reward against P_opt) is reported on every row at weight 0. The env, its
verifier and training all grade with the same code, `gridsim_core.grade`, and the plugin's tests check that the env
and gridsim_core agree to 1e-6.

## Tables

All parquet. The splits are `train`, `eval_2025`, `eval_iid` and `rtcb`; the showcase days are a config of their
own, so they never mix into a split.

| Config | Split | Rows | What |
|---|---|---:|---|
| `v1_tasks` (default) | `train` | 26,000 | 20,000 battery-days of 2014 to 2024 at the foresight tier, and 6,000 of them again at the blind tier |
| | `eval_2025` | 800 | 500 held-out battery-days of January to November 2025, and 300 of them at the blind tier |
| | `eval_iid` | 500 | 500 battery-days on reserved dates of 2014 to 2024 (every 10th calendar day), foresight only |
| | `rtcb` | 452 | 250 battery-days after ERCOT's real-time co-optimization went live (5 December 2025 to 17 October 2026), and 202 of them at the blind tier |
| `v1_showcase` | `showcase` | 1,461 | 761 battery-days of famous events (Winter Storm Uri, Elliott, August 2023, 6 September 2023, Heather), 700 of them also blind: for display, never for scoring a claim |
| `v1_references` | each split above | 20,000 / 500 / 500 / 250 / 761 | per battery-day: P_opt and its schedule, P_idle, the LP bound, the clock, threshold, greedy and random-feasible schedules with their profits and rewards, and for blind battery-days the persistence and ridge schedules and the anchor |
| `v1_episodes` | the split of each episode's day | – | recorded runs: the model or checkpoint, the tier and harness, the reward and hindsight capture, the schedule, every tool call and the transcript as chat messages |

<!-- TODO: v1_episodes row counts after the board and training runs land -->

`raw/packs/` holds the five packs exactly as the env loads them, one JSON task per line (`<pack>.jsonl`), with each
pack's manifest (sources and their SHA-256, filters, counts, the battery table) and `stats.md`, the pack statistics.
`runs/` holds the Episode JSON (`gridsim.episode/v1`) the replay Space reads, with `runs/index.json` listing them, and
`results/` the eval card `eval-v1.json` and `board.md`. Each bundle published for `agent-env hf run` adds agentenv-hf's
`<bundle>_tasks` and `<bundle>_episodes` configs and the bundle under `bundles/` (see
[Run it yourself](#run-it-yourself)).

## Use

```python
import json
from datasets import load_dataset

repo = "earakely-scale/GridSimEnv-AgentEnv"
days = load_dataset(repo, "v1_tasks", split="eval_2025", revision="v0.1.0")
day = days[0]
print(day["task_id"], day["tier"], day["settlement_point"], day["archetype"])
# what the agent gets: the system prompt and the situation, as path-B training sends them
print(day["system_prompt"], day["situation"], sep="\n\n")
day["prompt"]                      # the same two messages, as a chat list
json.loads(day["tools"])           # the submit_schedule function schema
blind = days.filter(lambda r: r["tier"] == "blind")    # the 300 blind battery-days

refs = load_dataset(repo, "v1_references", split="eval_2025", revision="v0.1.0")
print(refs[0]["p_opt"], refs[0]["opt"], refs[0]["greedy_reward"])
```

Grade any schedule with `gridsim_core`, which installs with the plugin:

```python
from gridsim_core.grade import grade

task = json.loads(day["task"])                                        # the battery-day as the env loads it
grade(task, [0] * 24, day["tier"])["reward"]                          # idle: 0.2
grade(task, task["refs"]["foresight"]["opt"], "foresight")["reward"]  # the DP optimum: 1.0
```

For TRL, `v1_tasks` is a GRPO dataset as it stands: `prompt` is the conversational prompt, and
`gridsim_core.trl.reward_fn` takes the `task` and `tier` columns TRL passes to reward functions, reads the
`submit_schedule` call out of each completion and returns its reward.

```python
from gridsim_core.trl import reward_fn
from trl import GRPOConfig, GRPOTrainer

train = load_dataset(repo, "v1_tasks", split="train", revision="v0.1.0").filter(lambda r: r["tier"] == "foresight")
trainer = GRPOTrainer(model="Qwen/Qwen3-1.7B", reward_funcs=reward_fn, train_dataset=train,
                      args=GRPOConfig(output_dir="gridsim-grpo"))
```

The training recipe that produced the published checkpoints (chat template with the tool schema, thinking off, LoRA,
the C0 to C2 curriculum) is in the plugin; see [Training](#training).

## Run it yourself

You need Docker, [uv](https://docs.astral.sh/uv/) and git. Install the plugin, build and register the env and the
`gridsim-llm` agent, and check the wiring with a task that calls no model:

```bash
uv tool install agentenv-framework \
    --with "agentenv-gridsim @ git+https://github.com/earakely-scale/agentenv-gridsim-plugin@v0.1.0"
# build the env and agent images and register them
agent-env gridsim setup --agent
# no model: submits the DP optimum of a fixture day, prints "passed"
agent-env run gridsim --task smoke
```

Then play a battery-day straight from this dataset with a model on your LiteLLM endpoint:

```bash
agent-env hf run earakely-scale/GridSimEnv-AgentEnv@v0.1.0 --bundle ercot-dam-v1-eval \
    --task dam-v1-2025-02-25-LZ_AEN-2h-o --model openai/gpt-6.1-sol
```

<!-- TODO: confirm the published bundle names and tiers once the plugin's bundles are final -->

`hf run` downloads this card and `bundles/` at the tag's commit, checks that the plugin the card's `agentenv` table
names is installed, shows what it will run and asks first; `--dry-run` runs nothing. To sweep a model over a pack
and write the board, use the plugin's CLI:

```bash
agent-env gridsim sweep run --name mine --models openai/gpt-6.1-sol --tasks 20 --cap-usd 5
agent-env gridsim sweep report mine      # results/eval-v1.json and results/board.md
agent-env gridsim episodes mine          # Episode JSON under results/runs/mine/, each replayed and checked
agent-env gridsim view                   # the viewer on http://127.0.0.1:8239/
```

## How the battery-days were picked

- **Prices.** ERCOT's *Historical DAM Load Zone and Hub Prices* (report NP4-180-ER, report type 13060), the yearly
  files for 2014 to 2026, with their SHA-256 in each manifest: the hourly DAM settlement point price at the hubs
  HB_HOUSTON, HB_NORTH, HB_PAN (from 6 April 2019), HB_SOUTH, HB_WEST, HB_HUBAVG and HB_BUSAVG, and the load zones
  LZ_AEN, LZ_CPS, LZ_HOUSTON, LZ_LCRA, LZ_NORTH, LZ_RAYBN, LZ_SOUTH and LZ_WEST.
- **Clean days.** Days of the daylight-saving changes are dropped (364 point-days), as is any day without exactly 24
  hourly prices (none). 67,810 point-days remain. Seven point-days of 17 February 2021 (Uri) above the era's
  $9,000/MWh cap are kept for the showcase only.
- **Duplicates.** Within a date, a point whose 24 prices match a point already kept (correlation above 0.999 and no
  hour more than $1 apart) is dropped: 19,733 point-days, most of them load zones that track their hub, and the two
  averages.
- **Splits by date.** `eval_2025` is 1 January to 30 November 2025 (the first battery-day is 6 January); `rtcb` is 5
  December 2025, when real-time co-optimization plus batteries (RTC+B) went live, to 17 October 2026; `eval_iid` is
  every 10th calendar day from 10 January 2014 through 2024; `train` is the rest of 2014 to 2024; the showcase
  windows are 10 to 22 February 2021, 22 to 24 December 2022, August 2023, 6 September 2023 and 13 to 17 January
  2024. 1 to 4 December 2025 is unused. 2025 and later never reach `train`.
- **Batteries.** Each point-day gets one archetype battery, chosen by a stable hash of the date and point: the
  duration class with the mix 1 h 40%, 2 h 45%, 4 h 15%, then one of 26 lettered designs in that class. Power, `unit_mwh` and the rest come from a fixed table (in each manifest and in `stats.md`):
  7.5 to 225 MW, round-trip efficiency 0.80 to 0.90, degradation $0 to $8/MWh discharged, 1 to 2 cycles a day, varied
  start and end charge, and up to 16 charge levels. The sizes follow EIA-860 2025 (Schedule 3_4, operable storage in
  the ERCO balancing authority): 204 units, 13,115 MW, a mean duration of 1.645 h weighted by power, and 40% / 59% /
  1% of the power in the 1 h / 2 h / 4 h classes. 4 h batteries are over-weighted on purpose, to give long-duration
  days. The batteries are archetypes, not real sites.
- **Filters.** A battery-day is dropped as low-spread when P_opt − P_idle is under $22 per MW of discharge power
  (14.6% of train candidates, 5.4% of eval), and 80% of the days where the greedy rule already scores 0.97 or more
  are dropped, chosen by hash (31,281 train candidates). The values were tuned on train and eval so that the greedy
  mean lands near 0.75 to 0.80 and about 15% of train drops as low-spread; the tuning table is in `stats.md`. A day
  joins the blind tier only if its anchor clears the same low-spread margin.
- **Sampling.** `train` is 20,000 of the 27,688 kept candidates by hash, and 6,000 of those with blind inputs form
  its blind tier. `eval_2025`, `eval_iid` and `rtcb` are drawn round-robin over (point, duration class, month) to 500,
  500 and 250; `eval_2025`'s 300 blind battery-days are drawn the same way, and `rtcb` uses every blind-eligible
  day (202). `eval_iid` has no blind tier.
- **Tags.** `binding` names the first of the cycle cap, the end obligation and the rate limit whose removal would
  raise P_opt by more than 10% of P_opt − P_idle (`none` otherwise); `neg_hours` counts negative-price hours; `spike`
  marks a day whose top price reaches the larger of $200 and 3 times its median. `difficulty` is 1 minus the greedy
  reward. The curriculum is `C2` when the cycle cap or the end obligation binds or any hour is negative, else `C0`
  when difficulty is at most 0.15, else `C1`.

## Baselines

Mean foresight reward per pack, from `stats.md`. Idle is 0.2 and the DP optimum 1.0 by construction.

| Pack | Split | Battery-days | Blind | Clock | Threshold | Greedy | Random feasible |
|---|---|---:|---:|---:|---:|---:|---:|
| `ercot-dam-v1-train` | `train` | 20,000 | 6,000 | 0.573 | 0.606 | 0.761 | 0.064 |
| `ercot-dam-v1-eval` | `eval_2025` | 500 | 300 | 0.485 | 0.642 | 0.761 | 0.072 |
| `ercot-dam-v1-eval-iid` | `eval_iid` | 500 | 0 | 0.555 | 0.607 | 0.751 | 0.067 |
| `ercot-dam-v1-rtcb` | `rtcb` | 250 | 202 | 0.435 | 0.664 | 0.724 | 0.043 |
| `showcase` | `showcase` | 761 | 700 | 0.627 | 0.602 | 0.832 | 0.125 |

- **Clock**: charge at full rate HE02 to HE05, sell at full rate HE18 to HE21.
- **Threshold**: charge at or below the day's 25th-percentile price, sell at or above its 75th while the spread
  covers the losses and degradation.
- **Greedy**: pair the cheapest hours with the dearest later ones at full rate while each pair pays.
- **Random feasible**: uniform over the actions that keep every rule and leave the end obligation reachable.

Each is clipped to the rules hour by hour and repaired to meet the end obligation. At the blind tier, the hindsight
capture (`r_opt`) of the anchor and of persistence alone:

| Pack | Blind battery-days | Anchor r_opt | Persistence r_opt |
|---|---:|---:|---:|
| `ercot-dam-v1-train` | 6,000 | 0.904 | 0.858 |
| `ercot-dam-v1-eval` | 300 | 0.920 | 0.882 |
| `ercot-dam-v1-rtcb` | 202 | 0.888 | 0.844 |
| `showcase` | 700 | 0.894 | 0.882 |

## Results

GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) on the held-out `eval_2025` battery-days, once each, under
the board registered before the first run (`docs/prereg/v1-board.md` in the plugin): the `full` harness with three
checks at the foresight tier, the `oneshot` harness (the path-B training prompt) at the foresight tier, and the
`full` harness at the blind tier. The 95% intervals are bootstrap intervals over battery-days; valid means submitted
and feasible.

<!-- board:v1 -->
| Model | Tier | Harness | Tasks | Mean reward (95% CI) | Hindsight r_opt | Valid | Beats anchor | $ per episode |
|---|---|---|---:|---|---:|---:|---:|---:|
| GPT-6.1 Sol (base) | foresight | full | 500 | pending | pending | pending | – | pending |
| GPT-6.1 Sol (base) | foresight | oneshot | 500 | pending | pending | pending | – | pending |
| GPT-6.1 Sol (base) | blind | full | 300 | pending | pending | pending | pending | pending |
<!-- /board:v1 -->

<!-- TODO: the board fills from results/eval-v1.json when the runs land; add the trained rows after training -->

## Training

The point of GridSimEnv is to show training on an AgentEnv simulation end to end. Path B trains on the `train`
split with one prompt and one completion per battery-day: the prompt is exactly `v1_tasks`' `prompt` (the `oneshot`
harness's system prompt and situation), the completion ends in a `submit_schedule` call, and the reward is
`gridsim_core.trl.reward_fn`, the same `grade` the env's verifier uses, in under a millisecond. Path A proves the
policy in full AgentEnv episodes: the trained model plays the `oneshot` bundle on the env, so the two paths grade the
same schedule identically. Path-B evaluations write the same Episode JSON as the env's runs, so checkpoints appear in
`v1_episodes` with `trained` set to `grpo` and their `checkpoint_step`, and replay in the Space.

<!-- TODO: the training results (Qwen3-1.7B and 4B GRPO, base vs trained on eval_2025, with CIs), the LoRA
checkpoints and the Colab land with the training lane -->

## Simplifications

- **A price taker.** The battery's trades never move the price.
- **The DAM award is the physical schedule.** No real-time market, no deviations, no imbalance settlement.
- **Hourly steps.** One action per hour; `q_15` (a quarter of `unit_mwh`) is stored so a 15-minute version can
  expand the same battery exactly.
- **Losses on the buy side.** Buying a unit draws `unit_mwh / eta`; selling delivers `unit_mwh`.
- **Linear degradation.** A flat `c_deg` per MWh discharged, with no depth-of-discharge or calendar ageing.
- **Archetype batteries, not real sites.** Sizes follow the ERCOT fleet in EIA-860; no task is any operator's asset.
- **Energy only at hubs and load zones.** No ancillary services, no real-time prices, no congestion at a resource
  node, no outages.
- **Integer charge levels.** Energy moves in whole units, which is what makes the optimum exact.

## Dataset structure

**Tasks** (`v1_tasks`, `v1_showcase`), one row per battery-day and tier:

- `task_id` (`dam-v1-<date>-<point>-<archetype>`; the tier is not in the id), `tier` (`foresight` or `blind`),
  `has_blind` (the battery-day also plays at the blind tier), `split`, `date`, `settlement_point`, `point_kind`
  (`hub` or `load_zone`), `region` (the viewer's backdrop: west, panhandle, north, houston, south or central).
- The battery: `archetype`, `p_dis_mw`, `p_ch_mw`, `energy_mwh`, `unit_mwh`, `q_15`, `k_dis`, `k_ch`, `soc_levels`,
  `eta`, `c_deg` ($/MWh discharged), `cycle_cap_units`, `s0`, `s_end_min`.
- `prices`: the day's 24 DAM prices in $/MWh, HE01 first, on which every tier settles (a blind row's agent never sees
  them). `dam_prev_day` (24) and `dam_prev_7d` (7 × 24, oldest first): the blind inputs, when the battery-day has
  them.
- `system_prompt`, `situation`: the system prompt and the opening user message exactly as the `oneshot` harness and
  path-B training send them (`gridsim_core.prompt`); `prompt` is the same pair as a chat list, and `tools` the JSON
  function schema of `submit_schedule`. The `full` harness's prompt differs only in describing `check_schedule` and
  the check budget.
- `curriculum` (`C0`, `C1`, `C2`), `difficulty`, `season`, `binding`, `neg_hours`, `spike`, `era` (the market era:
  price caps and products in force), and `tags`, all the tags as JSON.
- `task`: the full battery-day as JSON, as the env loads it, with its references.

**References** (`v1_references`), one row per battery-day: `p_idle`, `p_opt`, `opt` (the DP schedule), `p_lp`; for
each of `clock`, `threshold`, `greedy` and `random`, its `_profit`, `_reward` and `_schedule`; and for blind
battery-days `p_persist` and `persist`, `p_ridge` and `ridge`, `p_anchor` and which one it is (`anchor`),
`r_opt_anchor`, and each forecast schedule's blind-tier `_reward` and `_r_opt`.

**Episodes** (`v1_episodes`), one row per recorded run: `episode_id`, `task_id`, `split`, `tier`, `bundle` (`full`,
`oneshot` or `train`), `path` (`A`, a full AgentEnv episode; `B`, a training-path completion), `model`, `trained`
(`base`, `grpo` or `sft`), `checkpoint_step`, `seed`; `reward`, `r_opt`, `beats_anchor` (blind), `submitted`,
`feasible`, `truncated_at`, `violation`, `end_shortfall_units`, `profit_usd`, `p_opt`, `p_idle`, `p_anchor`;
`final_schedule`, `soc_path`, `checks_used`, `tool_calls`, `steps` (each call's arguments as sent and its output, as
JSON); `messages`, the transcript as chat messages in the shape TRL and transformers read (OpenAI roles, `tool_calls`
with `arguments` as objects, `tool_call_id` and `name` on tool messages; the `actions` argument kept as the model sent
it, a list or a string); `transcript` (`record`, the agent's own record, or `rebuilt` from the Episode JSON's calls
when that record isn't published); `assistant_text`; `input_tokens`, `output_tokens`, `usd`, `wall_seconds`; and
`file`, the episode's JSON under `runs/`. Every episode is graded again with `gridsim_core` before it is published,
and the build stops if any reward, profit or situation differs.

## Licence and attribution

The dataset carries several sets of terms, hence `license: other`; the plugin's
[data/LICENSE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/v0.1.0/data/LICENSE) holds the ERCOT
terms in full and [NOTICE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/v0.1.0/NOTICE) sets out
each source.

**ERCOT prices, under ERCOT's terms.** The prices, and everything derived from them in this dataset, come from public
data of the Electric Reliability Council of Texas, Inc. (ERCOT): the report NP4-180-ER, *Historical DAM Load Zone and
Hub Prices*, at <https://www.ercot.com/mp/data-products/data-product-details?id=NP4-180-ER>. ERCOT data is used under
ERCOT's Website User Agreement (last updated 20 July 2023), section 5, quoted from
<https://www.ercot.com/help/terms> as accessed on 24 October 2026:

> 5. The information presented on this website has been compiled by or for ERCOT for general information purposes
> only. The publicly available contents of this website may be used, reproduced, and redistributed, provided that the
> contents are not modified and that you maintain all copyright and other notices contained in the contents,
> including this Agreement. Notwithstanding the foregoing, raw data provided in public portions of this website may
> be used, reproduced, and redistributed in compilations, charts, and analyses without maintaining such notices.
> ERCOT does not guarantee the accuracy of any such compilations, charts, or analyses.

Automated access to ERCOT's reports is governed by ERCOT's Market Data Transparency Terms of Use (version 1.2, 11
August 2020, linked from <https://www.ercot.com/services/mdt>), which limits how often a report may be queried; ERCOT
provides its data "as is", without warranties (Website User Agreement, section 2). data/LICENSE reproduces both. The ERCOT data is not relicensed:
it is not under CC BY or any other licence from us, and anyone using it is bound by ERCOT's terms. This dataset is a
compilation and analysis of ERCOT's raw data; ERCOT does not guarantee its accuracy. Source: ERCOT. GridSimEnv is not
affiliated with or endorsed by ERCOT, and uses no ERCOT logo or trademark beyond naming the source.

**EIA-860, public domain.** The battery archetypes are sized from the U.S. Energy Information Administration's Form
EIA-860 annual electric generator data (2025 release, Schedule 3_4, Energy Storage), at
<https://www.eia.gov/electricity/data/eia860/>, a work of the U.S. Government. Source: U.S. Energy Information
Administration.

**Apache-2.0: the code.** The grader (`gridsim_core`), the verifier and bundle files under `bundles/` and the plugin
that builds this dataset are Apache-2.0. The prompts, references and transcripts are derived from the ERCOT prices
and carry ERCOT's terms with them.

**Not in this dataset.** The replay Space can show each day's weather at a representative airport, from the Iowa
Environmental Mesonet's ASOS archive (Iowa State University), credited there.

`scripts/hub_dataset.py` in the plugin builds this dataset, after agentenv-hf's scan of every file for keys and token
shapes. Neither ERCOT, the EIA nor the IEM is affiliated with it or endorses it.

## Citation

```bibtex
@misc{gridsimenv2026,
  title        = {{GridSimEnv}: run a grid battery on the real {Texas} day-ahead market, an {AgentEnv} environment},
  author       = {Arakelyan, Edgar and Kolavi, Adithya S},
  year         = {2026},
  howpublished = {\url{https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv}},
  note         = {Version v0.1.0. Prices: ERCOT NP4-180-ER. Code: https://github.com/earakely-scale/agentenv-gridsim-plugin}
}
```
