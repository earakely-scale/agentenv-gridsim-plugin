---
license: other
license_name: ercot-website-user-agreement-eia-public-domain-apache-2.0
license_link: https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/data/LICENSE
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
- solar
- ancillary-services
- weather
- forecasting
- auctions
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
- config_name: v2_tasks
  data_files:
  - split: train
    path: tasks/v2/train.parquet
  - split: eval_2024
    path: tasks/v2/eval_2024.parquet
  - split: test_2025
    path: tasks/v2/test_2025.parquet
  - split: rtcb
    path: tasks/v2/rtcb.parquet
- config_name: v2_showcase
  data_files:
  - split: showcase
    path: tasks/v2/showcase.parquet
- config_name: v2_references
  data_files:
  - split: train
    path: references/v2/train.parquet
  - split: eval_2024
    path: references/v2/eval_2024.parquet
  - split: test_2025
    path: references/v2/test_2025.parquet
  - split: rtcb
    path: references/v2/rtcb.parquet
  - split: showcase
    path: references/v2/showcase.parquet
- config_name: v2_episodes
  data_files:
  - split: eval_2024
    path: episodes/v2/eval_2024.parquet
- config_name: v3_tasks
  data_files:
  - split: train
    path: tasks/v3/train.parquet
  - split: eval
    path: tasks/v3/eval.parquet
  - split: rtcb
    path: tasks/v3/rtcb.parquet
- config_name: v3_showcase
  data_files:
  - split: showcase
    path: tasks/v3/showcase.parquet
- config_name: v3_references
  data_files:
  - split: train
    path: references/v3/train.parquet
  - split: eval
    path: references/v3/eval.parquet
  - split: rtcb
    path: references/v3/rtcb.parquet
  - split: showcase
    path: references/v3/showcase.parquet
- config_name: v3_episodes
  data_files:
  - split: eval
    path: episodes/v3/eval.parquet
- config_name: v4_tasks
  data_files:
  - split: train
    path: tasks/v4/train.parquet
  - split: eval
    path: tasks/v4/eval.parquet
  - split: rtcb
    path: tasks/v4/rtcb.parquet
- config_name: v4_showcase
  data_files:
  - split: showcase
    path: tasks/v4/showcase.parquet
- config_name: v4_references
  data_files:
  - split: train
    path: references/v4/train.parquet
  - split: eval
    path: references/v4/eval.parquet
  - split: rtcb
    path: references/v4/rtcb.parquet
  - split: showcase
    path: references/v4/showcase.parquet
- config_name: v4_episodes
  data_files:
  - split: eval
    path: episodes/v4/eval.parquet
- config_name: v5_tasks
  data_files:
  - split: train
    path: tasks/v5/train.parquet
  - split: eval
    path: tasks/v5/eval.parquet
  - split: rtcb
    path: tasks/v5/rtcb.parquet
- config_name: v5_showcase
  data_files:
  - split: showcase
    path: tasks/v5/showcase.parquet
- config_name: v5_references
  data_files:
  - split: train
    path: references/v5/train.parquet
  - split: eval
    path: references/v5/eval.parquet
  - split: rtcb
    path: references/v5/rtcb.parquet
  - split: showcase
    path: references/v5/showcase.parquet
- config_name: v5_episodes
  data_files:
  - split: eval
    path: episodes/v5/eval.parquet
---

<div align="center">

<a href="https://earakely-scale-gridsimenv-agentenv.static.hf.space/index.html?episode=runs/dam-v1-2025-03-15-HB_WEST-1h-t-zgptiln6.json"><img src="assets/gridsim-hero.jpg" alt="GPT-6.1 Sol's run of a 160 MW battery at ERCOT's West hub on 15 March 2025, replayed in 3D at the $102 evening peak" width="100%"></a>

<h1>GridSimEnv v1: The Battery Desk</h1>

<h3>Run a grid battery at a Texas hub for one day on the real day-ahead prices, graded exactly against the optimum</h3>

<p>An AgentEnv environment built from ERCOT's public day-ahead market prices and EIA-860 battery records, with 21,250 battery-days, a public train split and no judge: every schedule is scored against a dynamic program that finds the best possible day.</p>

<a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Space-Replays-FFD21E?style=for-the-badge&labelColor=1a1a1a" alt="Replays" height="32"></a>
<a href="https://github.com/earakely-scale/agentenv-gridsim-plugin"><img src="https://img.shields.io/badge/GitHub-agentenv--gridsim--plugin-181717?style=for-the-badge&logo=github&labelColor=1a1a1a" alt="Code on GitHub" height="32"></a>
<a href="https://www.agentenvframework.com"><img src="https://img.shields.io/badge/framework-AgentEnv-6f42c1?style=for-the-badge&labelColor=1a1a1a" alt="AgentEnv Framework" height="32"></a>

</div>

---

> **Also here, as previews:** [v2, The Live Grid](#v2-preview-the-live-grid), the same batteries played live through
> the day on real-time prices and grid bulletins; [v3, Sun, Storage and Reserves](#v3-preview-sun-storage-and-reserves),
> a solar farm and a battery behind one meter selling energy and ERCOT reserves;
> [v4, Weather Front](#v4-preview-weather-front), that plant run for three days on weather and load forecasts as they
> were issued; and
> [v5, The Market Floor](#v5-preview-the-market-floor), a battery bidding into ERCOT's day-ahead market as it clears
> again from the real offers of the day. Each has its own configs, references and pilot runs. v1 is the release; the
> previews have open design decisions.

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
| `v1_episodes` | `eval_2025`, `rtcb`, `showcase`, `train` (each episode's day) | 1,320 / 250 / 10 / 7 | recorded runs: the model or checkpoint, the tier and harness, the reward and hindsight capture, the schedule, every tool call and the transcript as chat messages. GPT-6.1 Sol's 1,550 board runs (1,300 on `eval_2025`, 250 on `rtcb`) with the agent's own transcripts, and 37 reference episodes the Space also replays |

`raw/packs/` holds the five packs exactly as the env loads them, one JSON task per line (`<pack>.jsonl`), with each
pack's manifest (sources and their SHA-256, filters, counts, the battery table) and `stats.md`, the pack statistics.
`runs/` holds the Episode JSON (`gridsim.episode/v1`) the replay Space reads, with `runs/index.json` listing them, and
`results/` the eval card `eval-v1.json` and `board.md`. Each bundle published for `agent-env hf run` adds the bundle
under `bundles/` and agentenv-hf's `<bundle>_tasks` config, and `<bundle>_episodes` once it has recorded runs (see
[Run it yourself](#run-it-yourself)). A config with no rows yet is left off this card. `training/` holds the
training summary ([Training](#training)); the v2 to v5 previews have configs of their own, set out in their sections,
and v4's forecast store and v5's market days are under `raw/`.

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

This is the minimal wiring; the recipe behind the published runs (the chat template with the tool schema, thinking
off, LoRA, the C0 to C2 curriculum) lands with the training results ([Training](#training)).

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
export LITELLM_BASE_URL=https://your-litellm-proxy/v1 LITELLM_API_KEY=...
agent-env hf run earakely-scale/GridSimEnv-AgentEnv@v0.1.0 --bundle ercot-dam-v1-eval \
    --task dam-v1-2025-02-25-LZ_AEN-2h-o --model openai/gpt-6.1-sol
```

<!-- TODO: confirm which bundles (packs, tiers, harnesses) the release publishes -->

The plugin brings agentenv-hf with it. `hf run` downloads this card and `bundles/` at the tag's commit, checks that
the plugin the card's `agentenv` table names is installed, shows what it will run and asks first; `--dry-run` runs
nothing. To sweep a model over a pack and write the board, use the plugin's CLI:

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
  duration class with the mix 1 h 40%, 2 h 45%, 4 h 15%, then one of 26 lettered designs in that class. Power,
  `unit_mwh` and the rest come from a fixed table (in each manifest and in `stats.md`): 7.5 to 225 MW, round-trip
  efficiency 0.80 to 0.90, degradation $0 to $8/MWh discharged, 1 to 2 cycles a day, varied start and end charge, and
  up to 16 charge levels. The sizes follow EIA-860 2025 (Schedule 3_4, operable storage in the ERCO balancing
  authority): 204 units, 13,115 MW, a mean duration of 1.645 h weighted by power, and 40% / 59% / 1% of the power in
  the 1 h / 2 h / 4 h classes. 4 h batteries are over-weighted on purpose, to give long-duration days. The batteries
  are archetypes, not real sites.
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

GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played each battery-day once, under the board registered
before the first run ([`docs/prereg/v1-board.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v1-board.md)):
column A is the `full` harness with three checks at the foresight tier on the held-out `eval_2025` battery-days, B the
`oneshot` harness (the path-B training prompt) on the same days, C the `full` harness at the blind tier, and the
optional D the `full` harness at the foresight tier on the `rtcb` days. The 95% intervals are bootstrap intervals over
battery-days (10,000 resamples); optimal means R ≥ 0.99, valid submitted and feasible. Every run is in `v1_episodes`
with its transcript, and every recorded tool call replays on the env with the same output and reward.

<!-- board:v1 -->
| Column | Model | Pack | Tier | Harness | Battery-days | Mean reward (95% CI) | r_opt | Optimal | Valid | Beats anchor | $ per episode |
|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|
| A | GPT-6.1 Sol | `ercot-dam-v1-eval` | foresight | full | 500 | **0.9999** (0.9997 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | $0.0157 |
| B | GPT-6.1 Sol | `ercot-dam-v1-eval` | foresight | oneshot | 500 | **0.9999** (0.9998 to 1.0000) | 0.9999 | 99.6% | 100.0% | – | $0.0117 |
| C | GPT-6.1 Sol | `ercot-dam-v1-eval` | blind | full | 300 | **0.9721** (0.9624 to 0.9804) | 0.9165 | 72.3% | 100.0% | 40.3% | $0.0193 |
| D | GPT-6.1 Sol | `ercot-dam-v1-rtcb` | foresight | full | 250 | **1.0000** (0.9999 to 1.0000) | 1.0000 | 100.0% | 100.0% | – | $0.0161 |

Baselines graded on each column's battery-days (mean reward; r_opt in brackets at the blind tier):

- A: idle 0.200, random 0.072, clock 0.485, threshold 0.642, greedy 0.761, persistence-DP 0.882 on 300, ridge-DP 0.799 on 300, blind anchor 0.920 on 300; the DP optimum 1.000.
- B: idle 0.200, random 0.072, clock 0.485, threshold 0.642, greedy 0.761, persistence-DP 0.882 on 300, ridge-DP 0.799 on 300, blind anchor 0.920 on 300; the DP optimum 1.000.
- C: idle 0.200 (0.200), random 0.076 (0.076), clock 0.516 (0.487), threshold 0.698 (0.655), greedy 0.821 (0.783), persistence-DP 0.957 (0.882), ridge-DP 0.861 (0.799), blind anchor 1.000 (0.920); the DP optimum 1.000.
- D: idle 0.200, random 0.043, clock 0.435, threshold 0.664, greedy 0.724, persistence-DP 0.844 on 202, ridge-DP 0.764 on 202, blind anchor 0.888 on 202; the DP optimum 1.000.

The headline is the amended board. The pre-registered $0.10 episode cap stopped runs before they submitted (A 14, B 3, C 63, D 5): the agent's own pre-request cost guard, not the model. Those runs were re-run once at $0.40 and all scored. The pre-registered scoring, its scored runs only: A 0.9999 (486 of 500); B 0.9999 (497 of 500); C 0.9769 (237 of 300); D 1.0000 (245 of 250). Dropping the stopped runs would bias the blind column toward easy days, so the amended column is the headline.
<!-- /board:v1 -->

Foresight is saturated for a frontier model: with the day's prices in view Sol finds the optimum. The blind tier is
where models separate, against the anchor's own hindsight capture on the same days. The plugin's
[`results/board.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/results/board.md) has
the full board: the amendment, the breakdowns by checks used, battery class, binding constraint and day type, cost and
time, the hypotheses against what was measured, and the unscored runs.

The trained Qwen3-1.7B results are under [Training](#training).

## Training

The point of GridSimEnv is to show training on an AgentEnv simulation end to end. Path B trains on the `train`
split with one prompt and one completion per battery-day: the prompt is exactly `v1_tasks`' `prompt` (the `oneshot`
harness's system prompt and situation), the completion ends in a `submit_schedule` call, and the reward is
`gridsim_core.trl.reward_fn`, the same `grade` the env's verifier uses, in under a millisecond. Path A proves the
policy in full AgentEnv episodes: the trained model plays the `oneshot` bundle on the env, so the two paths grade the
same schedule identically.

Qwen3-1.7B (bf16, LoRA, thinking off) trained on one GPU and was graded on 200 `eval_2025` battery-days at the
foresight tier with the `oneshot` prompt, sampled at temperature 0.7. The base model writes no valid schedule
(R 0.000). Each arm was held to the same two bars on those 200 days: beat the threshold rule, and beat the greedy
rule, each with the 95% intervals apart and at least 98% of schedules valid. Arm 1 was registered before it ran; arm 2
was designed after arm 1's result, arm 2b, a continuation of arm 2, after arm 2's, and arm 2c, a continuation of arm 2b,
after arm 2b's.

<!-- training -->
The training summary lands with the training lane.
<!-- /training -->

- **Arm 1:** a warm start on 200 DP-optimal schedules, each with a template rationale, then 280 GRPO steps. GRPO
  straight from the base model never produced a valid schedule, so it had no reward signal to learn from.
- **Arm 2:** a warm start on 1,500 DP-optimal schedules whose rationale tracks the state of charge, which alone
  scores 0.542 (0.493 to 0.589), then 75 GRPO steps: +0.037 (−0.016 to 0.091), not significant, though feasible
  schedules rose from 64% to 77.5%.
- **Arm 2b (exploratory continuation):** 105 more GRPO steps from arm 2's step 75 score 0.668 (0.629 to 0.707)
  sampled and 0.681 (0.644 to 0.718) greedy, +0.089 (0.051 to 0.127) over arm 2 on the same days, paired. That is
  level with the threshold rule's 0.637, paired +0.031 (−0.022 to 0.086) sampled and +0.044 (−0.010 to 0.098) greedy,
  and below the greedy rule's 0.764 by 0.08 to 0.10, paired −0.096 (−0.143 to −0.050) sampled.
- **Arm 2c (exploratory continuation):** 150 more GRPO steps from arm 2b's step 180 score 0.720 (0.681 to 0.756)
  sampled and 0.719 (0.681 to 0.757) greedy, +0.051 (0.017 to 0.086) over arm 2b on the same days, paired. That is
  above the threshold rule, paired +0.083 (0.031 to 0.135) sampled, with the intervals apart and every schedule valid,
  and level with the greedy rule's 0.764, paired −0.044 (−0.091 to 0.002).
- Only arm 2c clears a bar, the threshold rule's, and it was not registered: it continued arm 2b after arm 2b's result.
  No arm beats the greedy rule. All four arms took about $18 of GPU time in all, and no API spend. `training/` holds
  each arm's summary, checkpoint evaluations and training curves, and `training/arms.json` the bars and results. The
  LoRA adapters are not published.

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
`oneshot` or `train`), `path` (`A`, a full AgentEnv episode; `B`, a training-path completion), `model` (the LiteLLM
id, or `reference/...` for the reference episodes the Space also replays: the DP optimum, the baselines, persistence-DP
and a deliberately flawed plan), `model_label` (the display name, e.g. GPT-6.1 Sol), `trained`
(`base`, `grpo` or `sft`), `checkpoint_step`, `seed`; `reward`, `r_opt`, `beats_anchor` (blind), `submitted`,
`feasible`, `truncated_at`, `violation`, `end_shortfall_units`, `profit_usd`, `p_opt`, `p_idle`, `p_anchor`;
`final_schedule`, `soc_path`, `checks_used`, `tool_calls`, `steps` (each call's arguments as sent and its output, as
JSON); `messages`, the transcript as chat messages in the shape TRL and transformers read (OpenAI roles, `tool_calls`
with `arguments` as objects, `tool_call_id` and `name` on tool messages; the `actions` argument kept as the model sent
it, a list or a string); `transcript` (`record`, the agent's own record, or `rebuilt` from the Episode JSON's calls
when that record isn't published); `assistant_text`; `input_tokens`, `output_tokens`, `usd`, `wall_seconds`; and
`file`, the episode's JSON under `runs/`. Every episode is graded again with `gridsim_core` before it is published,
and the build stops if any reward, profit or situation differs.

## v2 preview: The Live Grid

> **A preview, not a release.** The env, the packs and the grading are built and tested, and one registered pilot
> has run. The headline metric is still open (below), so columns and numbers may change before v2 ships. The contract
> is [`docs/CONTRACT-v2.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v2.md).

**The task.** The same archetype batteries at the same hubs and load zones as v1, but the day is played live. The
clock starts at 14:00 the day before the operating day (D), when the day-ahead market closes, and runs to midnight on
D in watches: 14:00 on D-1, then 00:00, 06:00, 12:00 and 18:00 on D, plus one for each batch of grid bulletins, at
most 10 a day. At watch 0 the agent commits a day-ahead (DA) position, 24 hourly integers, and a physical schedule.
The battery then runs in 15-minute intervals, each settling at its real-time (RT) settlement point price once it has
ended. At each later watch the agent sees the settled RT prices and any new bulletins, and may change the intervals
past the freeze line (the next whole hour plus one hour), with 3 planning calls a watch. Profit is two-settlement: DA
cash on the position, RT cash on the deviation from it, less degradation and any end shortfall. An episode allows 52
turns.

The tiers: `foresight` (D's DA prices at watch 0), `blind` (only the previous 7 days' DA prices until 00:00 on D),
`short` (only the 14:00, 00:00 and 12:00 regular watches) and `freeze6h` (a six-hour freeze line). Each row of
`v2_tasks` is one battery-day at one tier.

**Grading.** R = clip(0.2 + 0.8 · (P − P_idle) / (P_roll − P_idle), 0, 1), v1's formula against the rolling anchor
P_roll: it commits the naive DA position at watch 0, then at every watch solves the exact dynamic program over the
open intervals on the DA prices plus the latest RT−DA gap, decaying over two hours. It reads no bulletin. Naive is
v1's optimum on the DA prices, committed as the position and the schedule and never changed. Hindsight capture,
(P − P_idle) / (P_hind − P_idle), is reported at weight 0; P_hind is the exact optimum with the day's RT prices known.

**Open decision: the headline metric.** On the pilot's 40 days naive alone scores R 0.850 and the anchor captures
only 0.498 of hindsight, so R is squeezed between naive and the anchor: 37.5% of Sol's days sit at R = 1. Hindsight
capture keeps the order idle 0 < naive 0.425 < anchor 0.498 < hindsight 1 and leaves room above the anchor. It is the
candidate headline, with R as a second row and naive as the floor for any claim about bulletins.

| Config | Split | Rows | Battery-days | Dates | Notice / quiet / unknown days | Naive R | Naive capture | Anchor capture |
|---|---|---:|---:|---|---|---:|---:|---:|
| `v2_tasks` | `train` | 15,189 | 4,000 | 2019 to 2024, the eval dates left out | 1,600 / 1,648 / 752 | 0.768 | 0.353 | 0.453 |
| | `eval_2024` | 1,128 | 300 | every third 2024 date and every 2024 ERCOT notice day | 150 / 136 / 14 | 0.857 | 0.434 | 0.524 |
| | `test_2025` | 779 | 200 | 1 January to 30 November 2025 | 60 / 72 / 68 | 0.764 | 0.358 | 0.475 |
| | `rtcb` | 386 | 100 | 5 December 2025 to 17 October 2026 | 30 / 59 / 11 | 0.779 | 0.337 | 0.439 |
| `v2_showcase` | `showcase` | 309 | 90 | Uri, Elliott, Heather, Fern, August 2023 and 6 September 2023, ±3 days out of every split; display only | 88 / 2 / 0 | 0.904 | 0.415 | 0.432 |

Naive R and the captures are at the foresight tier, from `raw/packs/live-stats.md`. A notice day has an ERCOT
grid-condition bulletin or a load-moving NWS warning for the point's region; an unknown day falls in a gap of the
bulletin archive. A battery-day is kept when its RT prices stray from DA by at least $40 per MW over the day,
hindsight beats idle by $10 per MW, and the anchor beats naive by $5 per MW and a share of the headroom. Notice days
skip that last test, so naive can beat the anchor there. `v2_references` has, per battery-day, P_idle, naive (its
profit and DA position), hindsight (its profit, DA and RT parts, position and schedule) and the LP bound, and for each
tier the anchor's profit, position, executed schedule and commits and naive's R. `v2_episodes` has one row per
recorded run, like `v1_episodes`, with the DA position, the schedule as committed and as executed, the P&L split and
the transcript.

**Bulletins, paraphrased.** The env delivers ERCOT operations notices (OCNs, Advisories, Watches, Emergencies,
Energy Emergency Alerts and conservation appeals) and NWS warnings, watches and heat advisories for the point's
region, each at the first watch after it was issued, never earlier. The dataset carries none of their wording. An
ERCOT bulletin is one line naming its type, its level and a reason category, such as "ERCOT issued a Watch (a
projected shortage of reserves)."; an NWS bulletin is built from the warning's type, counties and end time, such as
"NWS FWD: Excessive Heat Warning for Dallas, Tarrant, Collin and 2 more counties until 2023-09-08 21:00 CPT.". The
same lines are in the task rows, the prompts, `raw/packs/` and the episodes, and every episode replays on the rows as
published. The plugin's own packs word some ERCOT bulletins differently, so `raw/packs/` differs from them in that
text and its hash only; the references depend on when bulletins arrive, never on their words.

**Pilot.** GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played 40 `eval_2024` days at the foresight
tier, 20 notice days and 20 quiet ones, as registered in [`docs/prereg/v2-pilot.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v2-pilot.md),
plus the 6 September 2023 hero day for display. The intervals are 95% bootstrap intervals over days.

| Policy | Mean R (95% CI) | Hindsight capture (95% CI) | Beats the anchor | Re-plans |
|---|---|---|---:|---|
| GPT-6.1 Sol | **0.883** (0.840 to 0.924) | **0.437** (0.360 to 0.517) | 9 of 40 days | on 12 of 40 days, 7.1% of later watches |
| naive | 0.850 | 0.425 | – | never |
| rolling anchor | 1.000 | 0.498 | – | at 38.6% of later watches |

- Sol commits naive's DA position at watch 0 on 33 of 40 days and mostly holds it. When it re-plans it mostly
  gains: 10 of the 12 re-planned days beat naive, by $21 to $9,418, mostly at the 12:00 and 18:00 watches on the
  settled RT prices.
- It beats the anchor on 9 days, all notice days, and they are exactly the 9 days where naive beats the anchor. Its
  capture minus naive's on notice days is −0.004 (−0.027 to 0.011): no sign yet that it uses the bulletins.
- On the hero day (HB_NORTH on 6 September 2023, when ERCOT declared an EEA2 in the evening) it read the
  reserve-shortage Watch, kept its evening discharge and never re-planned across 9 later watches: R 0.596, the same
  as naive, and capture 0.077 against the anchor's 0.156. Profit $14,940, against $30,157 for the anchor and $193,619
  in hindsight.
- 41 runs, all scored at the first attempt, $2.03 in all. Every episode replays byte for byte on
  `gridsim_core.live` and passes its audit. The full reading is in
  [`results/board-v2.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v2.md).

## v3 preview: Sun, Storage and Reserves

> **A preview, not a release.** The env, the packs and the grading are built and tested, and one registered pilot
> has run. Design decisions are open (below). The contract is [`docs/CONTRACT-v3.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v3.md).

**The task.** A solar farm and a battery share one meter at an ERCOT hub or load zone, played live in watches as in
v2 but by the hour. At watch 0 (14:00 on D-1) the agent commits a book for D: each hour's battery move in MW
(positive discharges) and awards in up to five reserve products, Regulation Up and Down, Responsive Reserve (RRS),
ERCOT Contingency Reserve (ECRS) and Non-Spin, paid the day's DA clearing prices. The book becomes the DA position
when watch 0 ends. Each hour settles at its RT price once it has ended. Regulation awards move the battery's charge by
a drift drawn for each hour, and ERCOT's real RRS, ECRS and Non-Spin deployments that day draw reserve energy at
their real times. The charge must back every up-award for its product's duration and leave room for RegDn; a
governor nudges an hour's move to keep that, and a shortfall the agent could have seen coming is charged as failure
to provide. Plans are in MW, sent as hourly blocks; 52 turns and 3 planning calls a watch.

The tiers: `energy` (no reserves) and `reserves` (the DA awards are fixed after watch 0). A third, real-time
reserves tier after ERCOT's RTC+B is built but not playable, since no history of ERCOT's real-time reserve prices was
found: `rtcb` days play the `reserves` tier with DA reserve prices only. Each row of `v3_tasks` is one site-day at one
tier; `oneshot_prompt` is the one-decision prompt path-B training uses.

**Grading.** R as in v1 and v2, against P_anchor: a rolling mixed-integer plan (HiGHS) with the agent's
information, one solve per watch over the open hours, energy and reserves together, RT expected at DA. At weight 0:
hindsight capture against P_hind (one plan that knows the RT prices, the drift and the deployments), the energy-only
R (the energy tier's anchor on the reserves scale), the reserves' share of revenue, and failure-to-provide MWh. The
reference baselines are AS-hog (reserves only, no energy position), the solar sponge (charge only from PV the meter
cannot take) and v2's energy-only rolling plan.

**Open decisions.**
- **The reserves tier is the test, and it is undecided.** On 30 days Sol is far ahead of AS-hog but level with the
  energy-only plan (below); settling that takes about the full 300 eval days.
- **The hero day's seeded drift.** The regulation drift is a seeded draw, not ERCOT telemetry, and it ignores the
  grid. On the 6 September 2023 hero day (HB_WEST) it buys energy into the evening price spike while the DA awards are
  locked, so the reserves anchor ($345k) ends below the energy-only plan ($482k). The hero is display only and its
  replays play the energy tier; in the splits, a day where any baseline reaches 0.97 against the anchor is dropped.
- **AC-only sites never clip.** EIA-860 2025 shows no DC-coupled solar-plus-storage site in ERCOT, and every site's
  meter is at least its PV's AC rating, so no PV is ever clipped. The solar sponge equals idle, and the energy tier is
  close to saturated: v2's PV-blind plan scores 0.989 on `eval`.
- **Continuous MW.** Plans are continuous MW, not the 25 MW steps first planned (those made the solver intractable),
  so a plan can differ from the book by fractions of a MW; a value within 0.005 MW of the book counts as the book's.

| Config | Split | Rows | Site-days | Dates | Notice / deployment days | Anchor − idle | Anchor capture | AS-hog R | Energy-only R | v2 energy-only R |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| `v3_tasks` | `train` | 4,800 | 2,400 | 2021 to 2024 | 981 / 307 | $53,192 | 0.699 | 0.754 | 0.497 | 0.440 |
| | `eval` | 600 | 300 | January to November 2025, 100 per reserve-value stratum | 92 / 12 | $14,005 | 0.505 | 0.492 | 0.794 | 0.786 |
| | `rtcb` | 400 | 200 | 6 December 2025 to 30 September 2026 | 44 / 20 | $9,621 | 0.439 | 0.357 | 0.775 | 0.764 |
| `v3_showcase` | `showcase` | 8 | 4 | 10 August 2023, 6 September 2023, 29 March 2024, 26 January 2026; display only | 3 / 2 | $245,682 | 0.483 | 0.734 | 0.803 | 0.751 |

Means at the reserves tier, from `raw/packs/hybrid-stats.md`; at the energy tier v2's energy-only plan scores 0.826
on `train` and 0.98 to 0.99 on `eval` and `rtcb`. The sites are archetypes: 40% a 150 MW-AC solar farm with a
100 MW / 200 MWh battery, 60% sized from the co-located solar and storage in EIA-860 2025's ERCOT records, with the
meter at the PV's AC rating or 1.2 times it. PV output is ERCOT's system-wide hourly solar availability scaled to the
site. `v3_references` has, per site-day and tier, the anchor's profit, book and commits, hindsight, the LP bound, the
one-shot optimum and its plan, and each baseline's profit and R. `v3_episodes` has one row per recorded run, with the
book, the DA position, the cash split and the transcript.

**Pilot.** GPT-6.1 Sol played 30 `eval` days at the reserves tier, 10 per reserve-value stratum, and the same
draw's next 10 days at the energy tier, as registered in [`docs/prereg/v3-pilot.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v3-pilot.md),
plus 29 March 2024 at both tiers for display.

<!-- board:v3 -->
The v3 pilot's board lands with its eval card.
<!-- /board:v3 -->

On the same days: AS-hog 0.464, the energy-only plan 0.836 (the same as v2 energy-only on every one of the 30) and
the anchor's capture 0.480 at the reserves tier; v2 energy-only 0.979 and the anchor's capture 0.484 at the energy
tier.

- **Reserves.** R 0.811 (0.740 to 0.877). Sol beats AS-hog by 0.347 (0.251 to 0.439), on 27 of 30 days; against the
  energy-only plan it is −0.025 (−0.100 to 0.042), undecided at this size. Capture 0.397 against the anchor's 0.480.
- **Where it loses.** Sol earns nearly the anchor's reserve revenue, $5,985 a day against $6,241, but leans on RRS
  and RegDn and barely sells ECRS or Non-Spin. The gap is on the energy side: it books 2.4 times the anchor's RegDn in
  the day's six dearest hours, so the drift buys energy at peak RT prices.
- **Format.** One day was lost to a malformed commit, 25 RegDn values for 24 hours: the whole watch-0 commit was
  refused and the day ran with no reserves.
- **Energy tier: saturated.** R 1.000 (0.999 to 1.000) on 10 days.
- 42 runs, all scored, $7.03 in all. Every episode replays byte for byte on `gridsim_core.hybrid`; `v3_episodes` also
  holds 25 reference runs the Space replays (the anchor, AS-hog, the solar sponge and v2 energy-only on 10 days). The
  full reading is in [`results/board-v3.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v3.md).

## v4 preview: Weather Front

> **A preview, not a release.** The env, the packs, the forecast store and the grading are built and tested, and one
> registered pilot has run. Design decisions are open (below), so tiers, filters and numbers may change before v4
> ships. The contract is [`docs/CONTRACT-v4.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v4.md).

**The task.** v3's solar farm and battery behind one meter, run for three operating days on forecasts as they were
issued. The clock opens at 10:00 the day before the first day and runs to midnight after the last, in watches: 16
fixed ones (10:00, 14:00 and 18:00 the day before, then 00:00, 06:00, 10:00, 14:00 and 18:00 on each day but the last,
and 00:00, 06:00 and 18:00 on the last) plus one for each ERCOT or NWS bulletin, reserve deployment or weather run that
moves the desk's price outlook by 10% or more, at most 24 a window. Each day's DAM position, battery moves and reserve
awards, is bid at the 10:00 gate the day before (`submit_dam`, 3 submits a gate) and its results arrive by the 14:00
watch. The real-time book is re-planned at each watch (`check_schedule`, `commit_schedule`, 3 planning calls a watch).
Forecasts come from `get_forecast` and `get_forecast_drift`, 6 calls a watch: HRRR weather at the site and zone
points, load, wind and solar forecasts, the desk's price guide (P10, P50 and P90 of DA and RT prices and the reserve
clearing prices) and the NWS alerts in force. A forecast issued after the current time is refused. Settlement is v3's
two settlements: DA cash on the DAM position, RT cash on the deviation, reserves at their DA clearing prices, less
degradation, failure to provide and any end shortfall. 122 turns (72 at `front-lite`).

The tiers: `front` (three days with reserves), `front-lite` (two days, the battery alone, no reserves), `blind` (no
forecast tools) and `freeze-6h` (a six-hour freeze line). One task row serves all four. Each row of `v4_tasks` is one
window, with its opening at its headline tier: `front`, or `front-lite` in `train`, whose references cover that tier
only.

**What is served, and what is modelled.** Weather is NOAA's HRRR as issued: each 00, 06, 12 and 18Z run's 0 to 48 h
forecast at 18 fixed points (the 8 airports of v1's hubs and load zones, 3 more zone points, 4 wind and 3 solar points),
issued two hours after its cycle. ERCOT's own load forecast by weather zone (NP3-565-CD), wind forecast (NP4-732-CD and
NP4-742-CD) and solar forecast (NP4-745-CD), every hourly posting from 11 December 2023 through the ERCOT public API,
serve the windows from 12 December 2023 (`source: ercot`). Earlier windows and the whole `train` split serve the
desk's load, wind and solar forecasts instead (`source: desk`), modelled from the same HRRR runs. ERCOT's
day-ahead load forecast as reported to EIA-930 arrives at 06:00 on its day. The price guide is always the desk's: a
quantile model refitted each year only on data revealed before that year. Nothing is served before its reveal time;
the store's builder tests it, and each run's audit replays every forecast call against the store. Site PV, the
regulation drift and the missing RT reserve prices are as in v3.

**Grading.** R = clip(0.2 + 0.8 · (P − P_idle) / (P_roll − P_idle), 0, 1), against the rolling anchor P_roll: a
mixed-integer plan (HiGHS) with the agent's information, one solve per watch on the guide's P50 and the served
forecasts, bidding each gate and committing the open hours. At `blind` the anchor plans on persistence instead
(P_blind). At weight 0: `r_hind`, the same formula against P_hind (the exact plan that knows the realised prices, PV,
drift and deployments), `paired_vs_anchor` = (P − P_roll) / (P_hind − P_idle), P_roll3 (the same re-planner on the
P10, P50 and P90 paths), P_blind, and the naive gate rule, which charges in the 4 cheapest and discharges in the 4
dearest DA P50 hours of each day and never re-plans.

**Open decisions.**
- **Pack filters (V4-P18).** The plan's per-kW headroom bars kept under 10% of candidates on the real store, and none
  in `rtcb`: the median window's hindsight headroom is $0.40 per kW in `train` and $0.81 in `eval`. The packs instead
  drop each split's lowest 15% by hindsight headroom per kW, and keep a window only if the anchor beats idle by $0.10
  per kW and 5% of the headroom, hindsight beats the anchor by 8% of it, and the anchor beats persistence by 5% of it.
- **The front label (V4-P19).** "15 °F colder within 12 hours" marked every candidate a front: the West Texas points
  swing 25 to 30 °F a day. A window is now `front` when a zone point is 15 °F colder than the same hour a day earlier,
  or an NWS winter storm, freeze, excessive heat or high wind warning or watch is in force; else `calm`.
- **`train` (V4-P21).** The draw takes up to 3 settlement points per first day and label: 1,290 windows, 900 front
  and 390 calm. Calm is short: 1,883 windows pass the filters, 522 of them calm, and 390 of those fit at 3 a day; a
  strict 60/40 split would be 975 windows.
- **Stored anchor calls (V4-P20, V4-P22).** HiGHS breaks ties differently on different platforms, so every row stores
  the anchor's own decisions (`anchor_calls`) and the anchor replays them: P_roll reproduces to the cent on macOS and
  Linux, arm64 and amd64.
- **Rules 4.1 (V4-P23, V4-P24).** From the pilot's tool misuse: a blank or null `issued_at` is the latest forecast;
  every time the env shows carries its UTC offset (`2025-01-28T10:00-06:00`) and a time passed with one is converted
  (a time after now is still refused); `front-lite`'s card and DAM tool are energy-only; `"keep"` or null leaves a
  reserve field as it is.

| Config | Split | Windows | Dates | Front / calm | Forecasts | Anchor − idle | Anchor capture | P_blind R | Naive R | P_roll3 R |
|---|---|---:|---|---|---|---:|---:|---:|---:|---:|
| `v4_tasks` | `train` | 1,290 | 3 March 2021 to 28 December 2024 | 900 / 390 | desk, read from the store | $52,575 | 0.476 | 0.743 | 0.345 | 0.839 |
| | `eval` | 60 | 1 January to 29 October 2025 | 40 / 20 | ERCOT, inline | $54,102 | 0.511 | 0.738 | 0.598 | 0.970 |
| | `rtcb` | 20 | 11 December 2025 to 8 September 2026 | 10 / 10 | ERCOT, inline | $40,706 | 0.511 | 0.710 | 0.660 | 0.970 |
| `v4_showcase` | `showcase` | 4 | Uri (13 February 2021), Heather (14 January 2024), a calm spring window with negative prices (28 March 2024), Fern (24 January 2026); display only | 3 / 1 | desk (Uri), ERCOT | – | 0.636 | 0.887 | 0.378 | 0.961 |

Means per window at each split's headline tier (`front`; `front-lite` in `train`); anchor − idle is P_roll − P_idle
over the window. The sites are v3's archetypes (50 in `train`, 22 in `eval`) at the 13 hubs and load zones; every
showcase window is v3's showcase site, 150 MW-AC of solar with a 100 MW / 200 MWh battery. `v4_references` has, per
window and tier, P_idle, P_roll, P_roll3, P_blind, P_naive, P_hind, the LP bound, the anchor's DAM days and commits,
and the baselines' profit and R. `v4_episodes` has one row per recorded run: R, `r_hind`, paired vs anchor, the DAM
book, submits and misses, forecast calls, refusals, the cash split, the SoC path, every call and the transcript.

**The forecast store.** `raw/v4-store/` is the store every window reads, v4-store@cb47cd9f: 949,886 vintages in 557 MB
of parquet. `vintages/<year>.parquet` has one row per vintage and field (issued at, run, kind, key, source, the hourly
values and the SHA-256 of its fields), `index.parquet` each vintage's reveal time and hash, `ercot_postings.parquet`
each ERCOT API posting (report, document id, posting time, run id) and `manifest.json` the spans and the store's hash.
The `eval`, `rtcb` and showcase rows embed their window's slice; `train` rows name the store by its hash, and
`gridsim_core.forecast_inputs.slice_for(task, "raw/v4-store")` reads it. `raw/v4-forecast/` holds the 18 points, the
reveal table, the price guide's yearly pinball loss and coverage (`guide-card.json`) and the store's hash. No GRIB file
and no raw API response is published.

**Pilot.** GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played 20 `eval` windows at `front` (14 front, 6
calm) and 10 more at `front-lite`, as registered in [`docs/prereg/v4-pilot.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v4-pilot.md), plus 3
smoke windows and Fern and Heather for display. Every window served ERCOT's own forecasts. This is the rules-4.0
pilot, on the 4.0 packs: its episodes replay at the preview commit it ran on, not on rules 4.1, and a 4.1 pilot
replaces it.

<!-- board:v4 -->
The v4 pilot's board lands with its eval card.
<!-- /board:v4 -->

On the same 20 `front` windows: P_blind 0.720, the naive gate rule 0.643 and P_roll3 0.976; the anchor's `r_hind` is
0.582 and its hindsight capture, (P − P_idle) / (P_hind − P_idle), 0.477, against Sol's 0.566 and 0.458.

- **Forecasts are worth reading.** R 0.909 (0.836 to 0.968) against persistence's 0.720: +0.189 (0.096 to 0.286),
  above it on 15 of 20 windows, and +0.265 over the naive gate rule.
- **Level with the rolling MILP, by a different book.** Paired vs the anchor −0.019 (−0.057 to 0.017); Sol beats it
  on 7 windows. It bids a smaller DA position and a third less reserve, never ECRS, and commits 5.7 times a window to
  the anchor's 18.
- **It bids each day at that day's gate.** No gate was missed, and Sol read a forecast before its first submit at 95%
  of gates. But it leaves the next day unbooked until its own gate, so only 12 of 40 later-day gates had a standing
  plan to revise; all 12 were revised.
- **`front-lite` sits below persistence:** 0.883 against P_blind's 0.981, the loss almost all one window (LZ_HOUSTON
  on 19 February 2025, the cold snap, R 0.285). It stays a training and warm-up tier.
- **Fern** (HB_NORTH, 24 to 26 January 2026): R 1.0, $1,151,139 against the anchor's $1,039,573, regulation on the
  first day, then RRS, ECRS and Non-Spin into the storm with a large DA discharge on the 26th. **Heather**: R 0.932.
- 35 runs, all scored at the first attempt, $16.50 in all. Every episode replays byte for byte on
  `gridsim_core.forecast` at rules 4.0 and passes its audit. The full reading is in
  [`results/board-v4.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v4.md).

## v5 preview: The Market Floor

> **A preview, not a release.** The env, the packs, the market days and the grading are built and tested, and one
> registered pilot has run. Design decisions are open (below). The contract is
> [`docs/CONTRACT-v5.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v5.md).

**The task.** The agent is seat A, a battery of 400 to 1,500 MW, in ERCOT's day-ahead market (DAM) for one operating
day, cleared again from the offers and bids ERCOT disclosed for that day. Four other seats share the floor, each carved
from a real portfolio of the same day and anonymised: a second battery group (B), 6 to 12 gas combustion turbines (G),
a wind and solar portfolio (R) and a load-serving bidder (L). They submit their real offers. Seat A offers one curve
per hour, up to 10 sell and 10 buy blocks in steps of its grid (a twentieth of its power). The 24 hourly auctions clear
on one node at a uniform price; the battery delivers its awards as far as its state of charge allows, and any
deviation settles at the real RT hub price. Every price is a hub price: the clear plus the real hub's per-hour offset,
so the real offers clear at the real HB_HUBAVG DAM price exactly and a seat's price impact follows the real curve's
slope. Conduct and impact mitigation re-prices blocks far above a seat's reference when they move the price.

The tiers: `floor-sprint`, one watch at 09:00 the day before: read, up to 3 `check_offer` calls, then one
`submit_offer` that clears the market (6 turns; the training tier, path B); and `floor-day`, watches from 06:00 the day
before through the operating day: offers until the 10:00 close, contracts for differences with the retailer, then the
physical schedule against the awards (36 turns). The agent reads the aggregate supply and demand curves of disclosed
days at least 60 days old (`get_disclosure`), the day-ahead load forecast and the last complete day's wind and solar
from EIA-930, the previous day's prices (`get_forecast`), and its own costs and mitigation references. Each row of
`v5_tasks` is one floor: `prompt` is the path-B prompt (the rules, the situation and the latest disclosed day's
curves) and `day_prompt` the `floor-day` opening, where the floor also plays at `floor-day`.

**Grading.** R = clip(0.2 + 0.8 · (P − P_idle) / (P_anchor − P_idle), 0, 1), with P_idle = 0 (no offer), against
the disclosure best-responder: with the agent's information at 09:00 it shifts the curves disclosed for 61 and 62 days
earlier by the forecast change in net load, best-responds to its own price impact with an exact dynamic program,
self-schedules, and at `floor-day` re-plans the operating day. A run without a valid offer scores 0. `compliant` scores
the same run as 0.5 · R + 0.5 · its welfare ratio, the share it delivers of the welfare a planner could add over A and
B idle. At weight 0: capture and regret against P_br (the best SoC-feasible awards in hindsight), ε-Nash, welfare and
deadweight loss, the price-making gain over the impact-blind price-taker, the price impact of A's own awards
(`impact_usd`), mitigated hours and a withholding index.

**Real and modelled.** Real: every offer and bid behind the background curve (ERCOT's 60-Day DAM Disclosure,
aggregated to at most 64 points per hour and side), the seats' offers, ERCOT's system lambda, the hub DAM and RT
prices, and on `floor-day` the ERCOT and NWS bulletins. Modelled: one node, no congestion; reserves not cleared again
(each background curve is cut to the room its reserve awards leave); commitment as on the real day; the seats' private
costs (CT heat rates from EIA-923, the wind and solar production tax credit, a retail tariff); and the batteries'
energy, which the disclosure does not give before RTC+B. Each floor carries its day's raw fidelity: the share of
non-scarcity hours where the clear of every real offer lands within $5 or 10% of ERCOT's lambda.

**Open decisions.**
- **The impact filter (V5-P12).** A QSE-sized battery moves the price in few hours: "2 or more hours of $5 impact"
  keeps almost only peak days (12 of 200 `eval` floors). `train` asks for 1 hour of $2 instead, and `eval` keeps the
  stricter rule as its `peak` stratum. In the pilot Sol's gap to the price-taker was no smaller on base floors, so for
  this model a peak-only eval would add nothing.
- **The fidelity bar: 0.9 or 0.5.** The plan asked for 90% of hours within $5 or 10% of ERCOT's lambda; the clear
  reaches that on 39 of 982 days (median 0.71), so the packs take 0.5 and the hub offset carries the rest. In the
  pilot R rose with fidelity (0.70, 0.81 and 0.89 by tercile), which argues for a higher bar on the board, or R by
  fidelity band.
- **The price-taker collapse (V5-P18).** On most days the anchor's best response is the impact-blind price-taker's
  plan: the price-taker scores R = 1.0 on 105 of 200 `eval` floors (mean 0.949). So R mostly measures forecasting and
  scheduling under weak impact, not market power. The board adds the price-making gain over the price-taker as a
  weight-0 row and R on the `peak` stratum as a column of its own.
- **`train` back to 2022.** ERCOT's archive holds the disclosure from 1 January 2022, not only from December 2023.
  `train` uses 2024 (12 February to 31 December); of the 704 days from January 2022 to 10 December 2023, 74% pass the
  0.5 fidelity bar (56% in 2022). They are not shipped yet.

| Config | Split | Floors | Dates | Peak (2+ impact hours) | Also `floor-day` | Median fidelity | Anchor capture (median) | Price-taker R | Replay A R | Max-withhold R |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `v5_tasks` | `train` | 2,351 | 151 dates, 12 February to 31 December 2024 | 294 | 2,303 | 0.75 | 0.680 | 0.956 | 0.137 | 0.194 |
| | `eval` | 200 | one floor a date, 1 January to 28 November 2025 | 12 | 194 (60 in the `floor-day` set) | 0.71 | 0.731 | 0.949 | 0.176 | 0.199 |
| | `rtcb` | 153 | one floor a date, 10 December 2025 to 25 August 2026 | 2 | 147 | 0.67 | 0.683 | 0.934 | 0.136 | 0.200 |
| `v5_showcase` | `showcase` | 6 | 20 August 2024 and Winter Storm Fern, 23 to 27 January 2026; display only | 4 | 4 | – | – | 0.790 | 0.215 | 0.467 |

R values are means at `floor-sprint`; anchor capture is P_anchor / P_br. Seat A is 400, 600, 800, 1,000, 1,200 or
1,500 MW for 1, 2 or 4 hours, with round-trip efficiency 0.80 to 0.95 and degradation $0 to $8 per MWh.
`v5_references` has, per floor, the anchor's forecast (its net-load shift and the prices it expects), its
self-schedule, P_anchor, P_br and the RT-inclusive bound at each tier with the hindsight awards, and the price-taker,
max-withhold and replay-A baselines' profit and R. `v5_episodes` has one row per recorded run: R, compliant, regret,
capture, welfare ratio, ε-Nash, impact, mitigation, the offer, the awards, the clear, the hourly settlement, the P&L,
the contracts, every call and the transcript.

**The market days.** `raw/v5-market/days/` holds the 985 operating days the floors are built from, 11 December 2023 to
25 August 2026, one JSON line a day in monthly files (24 MB gzipped): the background supply and demand curves, the seat
pools' curves by pool id (`e1`, `c1`, `r1`, `l1`, …, with the CTs' unit sizes and start costs), ERCOT's system lambda,
the hub DAM and RT prices, EIA-930 load, wind, solar and day-ahead forecast, and the clear of every real offer with its
fidelity. They are derived, aggregated and anonymised: no disclosure file is published, and no resource or QSE name
leaves the data build (the dataset's build checks every key and string). `raw/v5-market/` also holds the days'
manifest (each disclosure document's id, posting time and SHA-256), the fidelity statistics (`stats.md`) and the
EIA-923 CT heat rates.

**Pilot.** GPT-6.1 Sol played 30 `eval` floors at `floor-sprint` (all 12 peak floors and 18 base ones) and 10 of them
at `floor-day`, as registered in [`docs/prereg/v5-pilot.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v5-pilot.md), plus four showcase floors
for display. The registered $0.18 episode cap stopped all 30 `floor-sprint` runs before they submitted (the agent's
own cost guard books a worst-case turn), so that column is the registered amendment at $0.36.

<!-- board:v5 -->
The v5 pilot's board lands with its eval card.
<!-- /board:v5 -->

- **Below the price-taker on both tiers.** The information-matched price-taker scores 0.924 and 0.990 on the same
  floors: Sol is −0.123 (−0.232 to −0.020) behind it at `floor-sprint` and −0.131 (−0.303 to −0.012) at `floor-day`.
  It is far above max-withhold and replay A at `floor-sprint` (+0.61 and +0.62).
- **It over-sells.** Sol offers two-sided curves with price-sensitive blocks and lets the clear decide, but its sell
  side sums to about 3 times its stored energy (9 times at `floor-day`). Awards outrun the battery: delivery is
  clipped on 21 of 30 sprint floors. In the peak floors' impact hours it sells 4,950 MWh against the anchor's 2,040,
  which costs it $69,182 a floor in price; its price-making gain there is −$143 per MW-day (+$94 at `floor-day`, where
  the re-plan buys back at RT).
- **Never mitigated, no contracts.** 0 mitigated hours on 40 floors, no block at the cap, no message and no CfD.
- **Compliant:** 0.550 and 0.652. At `floor-day` the welfare half drops Sol from third to fifth of six, below replay
  A and max-withhold: over-selling the DAM and dispatching again at RT pays, but wastes welfare (ratio 0.45 against
  about 0.6 for both).
- **Showcase:** on Winter Storm Fern (25 and 26 January 2026) Sol's 800 MW makes $6.3M and $9.0M against the
  anchor's $0.5M and $1.4M, re-planning into Fern's RT spikes.
- 44 runs, all scored at the first attempt; $4.50 in all, the smoke runs and the unscored registered sweep included.
  Every episode replays byte for byte on `gridsim_core.market` and passes its audit. The full reading is in
  [`results/board-v5.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v5.md).

## Licence and attribution

The dataset carries several sets of terms, hence `license: other`; the plugin's
[data/LICENSE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/data/LICENSE) holds the ERCOT
terms in full and [NOTICE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/NOTICE) sets out
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
provides its data "as is", without warranties (Website User Agreement, section 2). data/LICENSE reproduces both. The
ERCOT data is not relicensed: it is not under CC BY or any other licence from us, and anyone using it is bound by
ERCOT's terms. This dataset is a compilation and analysis of ERCOT's raw data; ERCOT does not guarantee its accuracy.
Source: ERCOT. GridSimEnv is not affiliated with or endorsed by ERCOT, and uses no ERCOT logo or trademark beyond
naming the source.

**EIA-860, public domain.** The battery archetypes are sized from the U.S. Energy Information Administration's Form
EIA-860 annual electric generator data (2025 release, Schedule 3_4, Energy Storage), at
<https://www.eia.gov/electricity/data/eia860/>, a work of the U.S. Government. Source: U.S. Energy Information
Administration.

**v2 and v3 previews: more ERCOT data, under the same terms.** The previews add ERCOT's real-time settlement point
prices at the hubs and load zones (NP6-785-ER, *Historical RTM Load Zone and Hub Prices*), its day-ahead
ancillary-service clearing prices (NP4-181-ER and NP4-188-CD, *DAM Clearing Prices for Capacity*), its system-wide
solar output (PG7-126-M, *Hourly Aggregated Wind and Solar Output*, and the *Fuel Mix Report*), and the dates, times,
types and levels of its operations messages and news releases, reserve deployments included. No ERCOT notice text is
reproduced: each bulletin is our own one-line paraphrase. Solar capacity for 2021, 2022 and 2026 uses the EIA's Form
EIA-860M (public domain). NWS watches, warnings and advisories come from the Iowa Environmental Mesonet's archive of
NWS VTEC products (Iowa State University; NWS data in the public domain), reduced to the product, counties and times.

**v4 preview: weather and forecasts.** The weather is NOAA's High-Resolution Rapid Refresh (HRRR) model output from
NOAA's Open Data Dissemination program, reduced to hourly series at 18 fixed points: a work of the U.S. Government, in
the public domain. Source: NOAA, National Centers for Environmental Prediction. ERCOT's demand, its day-ahead demand
forecast and its wind and solar generation come from the EIA's Form EIA-930 Hourly Electric Grid Monitor (public
domain). Source: U.S. Energy Information Administration. ERCOT's load (NP3-565-CD), wind (NP4-732-CD, NP4-742-CD) and
solar (NP4-745-CD) forecasts were obtained through the ERCOT Public API and are used under the same ERCOT terms as the
rest of the ERCOT data above; GridSimEnv is not affiliated with or endorsed by ERCOT. The desk's forecasts and price
guide in the store are our own models of these inputs and of ERCOT's prices.

**v5 preview: ERCOT's 60-Day DAM Disclosure, derived and anonymised.** The market days are derived from ERCOT's 60-Day
DAM Disclosure Reports (NP3-966-ER) and DAM System Lambda (NP4-523-CD), obtained through the ERCOT Public API and used
under the same ERCOT terms. Only derived data is published: curves aggregated to at most 64 points per hour and side,
and each seat's portfolio by an anonymous pool id. No disclosure file and no resource or QSE name is in this dataset.
The CT heat rates are from the EIA's Form EIA-923 (public domain). GridSimEnv is not affiliated with or endorsed by
ERCOT, and ERCOT does not guarantee the accuracy of these compilations.

**Apache-2.0: the code.** The grader (`gridsim_core`), the verifier and bundle files under `bundles/` and the plugin
that builds this dataset are Apache-2.0. The prompts, references and transcripts are derived from the ERCOT prices
and carry ERCOT's terms with them.

**Not in this dataset.** The replay Space can show each day's weather at a representative airport, from the Iowa
Environmental Mesonet's ASOS archive (Iowa State University), credited there.

`scripts/hub_dataset.py` in the plugin builds this dataset, after agentenv-hf's scan of every file for keys and token
shapes. Neither ERCOT, NOAA, the EIA, the NWS nor the IEM is affiliated with it or endorses it.

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
