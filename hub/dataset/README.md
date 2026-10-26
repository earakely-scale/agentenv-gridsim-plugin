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
degradation, and captures all of hindsight: C 1.000, R 1.0. The pack's references on the same day: the greedy rule,
which pairs the cheapest hours with the dearest later ones, makes one evening round trip for $4,815.38 (C 0.503, R
0.603); the threshold rule $5,411.63 (C 0.566, R 0.652); the clock rule, which charges HE02 to HE05 and sells HE18 to
HE21, $1,880.25 (C 0.196, R 0.357). At the blind tier the anchor is the DP schedule on the previous day's prices,
settled on this day: $8,937.75, a hindsight capture C of 0.934.

## Grading

Every GridSim version reports on one scale ([`docs/REWARD-SCALES.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/REWARD-SCALES.md)).
The headline is the hindsight capture

    C = (P - P_idle) / (P_hind - P_idle)

unclipped, where P is the run's profit, P_idle the profit of doing nothing (negative for the 12 of the 78 battery
designs whose end obligation is above their starting charge) and P_hind the clairvoyant optimum of the same
settlement, in v1 P_opt. Nothing settles above it: a property test checks every stored reference, each anchor and
baseline, on every day of every v3, v4 and v5 pack against P_hind to the cent (in v5 against BR_rt, the best
response settled at real-time prices). C is printed beside the anchor's own C on the same days and Δ = C − C_anchor,
the paired gap, with its 95% interval; any other comparison is (P − P_ref) / (P_hind − P_idle). Second comes the
reward on the anchor scale,

    R = clip(0.2 + 0.8 * (P - P_idle) / (P_anchor - P_idle), 0, 1)

a level with its share at R = 1 and its beats-anchor share, never differenced, where P_anchor is the reference with
the same information as the agent:

- **foresight**: P_opt, the exact optimum. A dynamic program over the state of charge, the units discharged so far
  and every allowed action finds it in under a millisecond, with ties broken deterministically. An LP relaxation
  bound (`p_lp`) is reported beside it: over every candidate day, the bound exceeds the optimum by at most 4.2% of
  its margin over idle, and by nothing up to the 99th percentile.
- **blind**: max(P_persist, P_ridge), the better of two schedules a desk could make from the same lagged prices,
  each the DP schedule on a price forecast, settled on the actual day: persistence (the previous day's prices) and a
  lagged ridge regression (`raw/packs/ridge-v1.json`).

At the foresight tier the anchor is the hindsight, so C = (R − 0.2) / 0.8 and a model at C 1 has solved the tier. At
the blind tier C replaces the `r_opt` this card printed before (r_opt = 0.2 + 0.8 · C, still a weight-0 row of the
verifier and a column of the episodes). Idle scores C 0 and R 0.2, the anchor R 1.0. A run that never submits a
parseable schedule scores 0 on both; there is no format credit. Training uses a third scale, S: R up to the anchor,
then rising linearly to 1.2 at hindsight. In v1 the trained tier is foresight, where the anchor is the hindsight, so
S = R and `gridsim_core.trl.reward_fn` is unchanged. The env, its verifier and training all grade with the same code,
`gridsim_core.grade`, and the plugin's tests check that the env and gridsim_core agree to 1e-6.

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
| `v1_episodes` | `eval_2025`, `rtcb`, `showcase`, `train` (each episode's day) | 1,338 / 250 / 10 / 7 | recorded runs: the model or checkpoint, the tier and harness, the reward and hindsight capture, the schedule, every tool call and the transcript as chat messages. GPT-6.1 Sol's 1,550 board runs (1,300 on `eval_2025`, 250 on `rtcb`) with the agent's own transcripts, 37 reference episodes the Space also replays, the 16 Qwen3-1.7B checkpoint episodes of its LEVEL UP view on one `eval_2025` day, and registered Qwen3-4B run 2's SFT-10k and final episodes on that day, from its race |

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

Mean foresight reward per pack, from `stats.md`. Idle is 0.2 and the DP optimum 1.0 by construction. The anchor here
is the optimum, so a rule's C is (R − 0.2) / 0.8 wherever R is not clipped at 0: on `eval_2025`, clock 0.341, threshold
0.543 and greedy 0.701.

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
capture C of the anchor and of persistence alone:

| Pack | Blind battery-days | Anchor C | Persistence C |
|---|---:|---:|---:|
| `ercot-dam-v1-train` | 6,000 | 0.880 | 0.822 |
| `ercot-dam-v1-eval` | 300 | 0.901 | 0.852 |
| `ercot-dam-v1-rtcb` | 202 | 0.860 | 0.805 |
| `showcase` | 700 | 0.867 | 0.852 |

## Results

GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played each battery-day once, under the board registered
before the first run ([`docs/prereg/v1-board.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v1-board.md)):
column A is the `full` harness with three checks at the foresight tier on the held-out `eval_2025` battery-days, B the
`oneshot` harness (the path-B training prompt) on the same days, C the `full` harness at the blind tier, and the
optional D the `full` harness at the foresight tier on the `rtcb` days. The 95% intervals are bootstrap intervals over
battery-days (10,000 resamples), paired for Δ; valid means submitted and feasible. Every run is in `v1_episodes` with
its transcript, and every recorded tool call replays on the env with the same output and reward.

<!-- board:v1 -->
Hindsight capture C = (P − P_idle)/(P_opt − P_idle) heads the board, beside the anchor's own C and the paired gap Δ = C − C_anchor; R, the anchor scale, comes second. At the foresight tier the anchor is the DP optimum, so C = (R − 0.2)/0.8 and a column at C 1 has solved the tier.

| Column | Model | Pack | Tier | Harness | Battery-days | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | Valid | $ per episode |
|---|---|---|---|---|---:|---|---:|---|---|---:|---:|---:|---:|
| A | GPT-6.1 Sol | `ercot-dam-v1-eval` | foresight | full | 500 | **1.000 (1.000 to 1.000)** | 1.000 | +0.000 (+0.000 to +0.000) | 1.000 (1.000 to 1.000) | 98.8% | 0.0% | 100.0% | $0.0157 |
| B | GPT-6.1 Sol | `ercot-dam-v1-eval` | foresight | oneshot | 500 | **1.000 (1.000 to 1.000)** | 1.000 | +0.000 (+0.000 to +0.000) | 1.000 (1.000 to 1.000) | 98.8% | 0.0% | 100.0% | $0.0117 |
| C | GPT-6.1 Sol | `ercot-dam-v1-eval` | blind | full | 300 | **0.896 (0.881 to 0.910)** | 0.901 | -0.005 (-0.019 to +0.009) | 0.972 (0.962 to 0.980) | 62.3% | 33.0% | 100.0% | $0.0193 |
| D | GPT-6.1 Sol | `ercot-dam-v1-rtcb` | foresight | full | 250 | **1.000 (1.000 to 1.000)** | 1.000 | +0.000 (+0.000 to +0.000) | 1.000 (1.000 to 1.000) | 98.8% | 0.0% | 100.0% | $0.0161 |

Baselines graded on each column's battery-days (mean C / R):

- A: idle 0.000 / 0.200, random -0.559 / 0.072, clock 0.341 / 0.485, threshold 0.543 / 0.642, greedy 0.701 / 0.761, persistence-DP 0.852 / 0.882 on 300, ridge-DP 0.747 / 0.799 on 300, blind anchor 0.901 / 0.920 on 300; the DP optimum 1.000 / 1.000.
- B: idle 0.000 / 0.200, random -0.559 / 0.072, clock 0.341 / 0.485, threshold 0.543 / 0.642, greedy 0.701 / 0.761, persistence-DP 0.852 / 0.882 on 300, ridge-DP 0.747 / 0.799 on 300, blind anchor 0.901 / 0.920 on 300; the DP optimum 1.000 / 1.000.
- C: idle 0.000 / 0.200, random -0.507 / 0.076, clock 0.349 / 0.516, threshold 0.565 / 0.698, greedy 0.729 / 0.821, persistence-DP 0.852 / 0.957, ridge-DP 0.747 / 0.861, blind anchor 0.901 / 1.000; the DP optimum 1.000 / 1.000.
- D: idle 0.000 / 0.200, random -0.718 / 0.043, clock 0.251 / 0.435, threshold 0.567 / 0.664, greedy 0.654 / 0.724, persistence-DP 0.805 / 0.844 on 202, ridge-DP 0.702 / 0.764 on 202, blind anchor 0.860 / 0.888 on 202; the DP optimum 1.000 / 1.000.

The headline is the amended board. The pre-registered $0.10 episode cap stopped runs before they submitted (A 14, B 3, C 63, D 5): the agent's own pre-request cost guard, not the model. Those runs were re-run once at $0.40 and all scored. The pre-registered scoring, its scored runs only: A: C 1.000, R 0.9999 (486 of 500); B: C 1.000, R 0.9999 (497 of 500); C: C 0.906, R 0.9769 (237 of 300); D: C 1.000, R 1.0000 (245 of 250). Dropping the stopped runs would bias the blind column toward easy days, so the amended column is the headline.
<!-- /board:v1 -->

Foresight is solved for a frontier model: with the day's prices in view Sol finds the optimum, C 1.000 on A, B and D.
The blind tier is where models separate: Sol captures 0.896 (0.881 to 0.910) of hindsight against the blind anchor's
own 0.901 on the same days, Δ −0.005 (−0.019 to +0.009), level with the anchor; it is above persistence-DP by +0.043
(+0.028 to +0.059). R comes second: 0.972 (0.962 to 0.980), at R = 1 on 62.3% of the days, above the anchor on 33.0%.
The plugin's
[`results/board.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/results/board.md) has
the full board: the amendment, the breakdowns by checks used, battery class, binding constraint and day type, cost and
time, the hypotheses against what was measured, and the unscored runs.

The trained Qwen3-1.7B results are under [Training](#training).

## Training

The point of GridSimEnv is to show training on an AgentEnv simulation end to end. Path B trains on the `train`
split with one prompt and one completion per battery-day: the prompt is exactly `v1_tasks`' `prompt` (the `oneshot`
harness's system prompt and situation), the completion ends in a `submit_schedule` call, and the reward is
`gridsim_core.trl.reward_fn`, the same `grade` the env's verifier uses, in under a millisecond (S = R at the foresight
tier, so the training reward is R here, and R = 0.2 + 0.8 · C). Path A proves the
policy in full AgentEnv episodes: the trained model plays the `oneshot` bundle on the env, so the two paths grade the
same schedule identically.

Qwen3-1.7B (bf16, LoRA, thinking off) trained on one GPU and was graded on 200 `eval_2025` battery-days at the
foresight tier with the `oneshot` prompt, sampled at temperature 0.7. The base model writes no valid schedule
(R 0.000). Each arm was held to the same two bars on those 200 days: beat the threshold rule, and beat the greedy
rule, each with the 95% intervals apart and at least 98% of schedules valid. Arm 1's bars were set in the training
plan before it ran, but its learning rate changed in the run (2e-5, not the planned 5e-6); arm 2 was designed after
arm 1's result, arm 2b, a continuation of arm 2, after arm 2's, and arm 2c, a continuation of arm 2b, after arm 2b's.
All four 1.7B arms are exploratory. Two Qwen3-4B runs were pre-registered, each with its plan, one fixed schedule and
its bars committed before any of its steps or evals. Run 1
([`docs/prereg/v1-train-4b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v1-train-4b.md))
took the 1.7B arms' recipe, SoC-aware SFT-1500 then 330 GRPO steps, and nothing changed after. Run 2
([`docs/prereg/v1-train-4b-v2.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v1-train-4b-v2.md)),
designed after run 1's result, changed two things at once: a warm start on 10,000 DP-optimal schedules whose rationale
states the DP's rule (SFT-10k), then GRPO with adaptive day sampling and dynamic sampling, which trains only on groups
whose rollouts do not all score the same. Its smoke test set 310 GRPO steps rather than 330 by its registered rule,
committed before the main run. Both runs have the same bars: the primary is the greedy rule's, with the intervals
apart; the secondary, the paired gap to the greedy rule above 0. After run 2, a confirmatory evaluation with no
training re-tested its SFT-10k warm start on fresh battery-days under the same bars, its plan committed before any
generation ([`docs/prereg/v1-confirm-sft10k.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v1-confirm-sft10k.md)).

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
- Of the 1.7B arms only arm 2c clears a bar, the threshold rule's, and it was not registered: it continued arm 2b
  after arm 2b's result. No 1.7B arm beats the greedy rule.
- **Qwen3-4B, registered run 1:** 0.804 (0.773 to 0.834) sampled and 0.808 (0.778 to 0.836) with greedy decoding,
  every schedule valid. The primary bar is not met: its interval overlaps the greedy rule's 0.764 (0.726 to 0.800) by
  0.027. The secondary is not met either: the paired gap to the greedy rule is +0.040 (−0.002 to +0.082), its lower end
  0.002 below 0. The first pre-registered training claim on GridSimEnv missed both bars, narrowly. With greedy
  decoding the paired gap clears 0, +0.044 (+0.003 to +0.085), but the registered bars are on sampled decoding, so that
  is reported, not claimed. On the same days run 1 is +0.084 (+0.052 to +0.118) above the 1.7B arm 2c, paired; SFT
  alone reached 0.666 and the base model 0.06, half its sampled completions running past 512 tokens.
- **Qwen3-4B, registered run 2:** 0.825 (0.789 to 0.860) sampled and 0.824 (0.787 to 0.858) with greedy decoding,
  99.5% valid. The secondary bar is met: the paired gap to the greedy rule is +0.061 (+0.013 to +0.110). That is the
  first registered training claim on GridSimEnv that holds. The primary is not met: the interval overlaps the greedy
  rule's 0.764 (0.726 to 0.800) by 0.011. Run 2 is +0.021 (−0.015 to +0.057) above run 1, paired, so a gain over run
  1 is not shown.
- **The warm start did the work, and GRPO on top did not help.** SFT-10k alone scores 0.841 (0.802 to 0.877)
  sampled, +0.174 (+0.121 to +0.228) over run 1's SFT-1500, paired. GRPO on top of it moved the score by −0.015
  (−0.061 to +0.030) sampled and −0.046 (−0.090 to −0.003) with greedy decoding; in run 1 it added +0.138 (+0.092 to
  +0.185). SFT-10k's own interval clears the greedy rule's, by 0.002, but run 2's registration names its final model
  as the claim, so that was post hoc, not claimed, until the confirmatory evaluation below. Dynamic sampling cut the share of GRPO groups trained on whose
  rollouts all scored the same from run 1's 23.8% to 0.7%, but the policy's entropy was below 0.02 from step 3 (run
  1's from step 43), so GRPO had little left to explore. No arm separates run 2's two changes.
- **Confirmed on fresh days: SFT-10k beats the greedy rule outright.** On the 500 `eval_iid` battery-days, which
  share no task or date with its training, SFT-10k scores 0.880 (0.858 to 0.900) sampled, every schedule valid,
  against the greedy rule's 0.751 (0.724 to 0.777): the intervals are apart, and the paired gap is +0.128 (+0.096 to
  +0.161). Both bars are met. This is the first pre-registered claim on GridSimEnv that a trained small model beats
  the greedy rule outright, and it is the warm start on 10,000 DP-optimal schedules that does it, not GRPO: run 2's
  final model minus SFT-10k there is +0.004 (−0.022 to +0.031). `eval_iid`'s days sit between training days of the
  same years, so this tests unseen days of the training era, not a later market. On the 250 `rtcb` battery-days after
  RTC+B went live only the paired test holds: 0.786 (0.747 to 0.825) against 0.724 (0.687 to 0.759), the intervals
  overlapping by 0.012, paired +0.062 (+0.009 to +0.113). A check first re-ran run 2's 200 `eval_2025` tasks with the
  same code and reproduced SFT-10k's score, 0.846 against 0.841.
- The four 1.7B arms took about $18 of GPU time, the 4B runs about $19 and $48 and the confirmatory evaluation about
  $1, with no API spend. `training/` holds each arm's summary, checkpoint evaluations and training curves (the 4B
  runs' under `training/4b/` and `training/4b-v2/`, SFT-10k's with run 2's, the confirmatory evaluation's summary
  under `training/confirm-sft10k/`), and `training/arms.json` the bars and results, every registered verdict
  included. The LoRA adapters are not published.

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
> has run. The headline metric is decided (below); columns and numbers may still change before v2 ships. The contract
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

**Grading.** The headline is hindsight capture, C = (P − P_idle) / (P_hind − P_idle), with P_hind the exact optimum
with the day's RT prices known (the DA position on DA − RT, the physical schedule on RT), beside the anchor's own C
and Δ = C − C_anchor with its paired 95% interval. Second, R = clip(0.2 + 0.8 · (P − P_idle) / (P_roll − P_idle), 0,
1), v1's formula against the rolling anchor P_roll: it commits the naive DA position at watch 0, then at every watch
solves the exact dynamic program over the open intervals on the DA prices plus the latest RT−DA gap, decaying over
two hours. It reads no bulletin. Naive is v1's optimum on the DA prices, committed as the position and the schedule
and never changed. Training uses S, R up to the anchor rising to 1.2 at hindsight (`grade()["stretch_reward"]`).

**The headline, decided.** On the pilot's 40 days naive alone scores R 0.850 and the anchor captures only 0.498 of
hindsight, so R is squeezed between naive and the anchor: 37.5% of Sol's days sit at R = 1. Hindsight capture keeps
the order idle 0 < naive 0.425 < anchor 0.498 < hindsight 1 and leaves room above the anchor, so it heads the board,
with R second and naive the floor for any claim about bulletins.

| Config | Split | Rows | Battery-days | Dates | Notice / quiet / unknown days | Naive R | Naive C | Anchor C |
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

| Policy | C (95% CI) | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats the anchor | Re-plans |
|---|---|---|---|---:|---:|---|
| GPT-6.1 Sol | **0.437** (0.361 to 0.513) | −0.061 (−0.089 to −0.035) | 0.883 (0.838 to 0.924) | 15 of 40 days | 9 of 40 days | on 12 of 40 days, 7.1% of later watches |
| naive | 0.425 | −0.073 | 0.850 | – | – | never |
| rolling anchor | 0.498 | – | 1.000 | – | – | at 38.6% of later watches |

Sol against naive on the same days: +0.012 (−0.004 to +0.028) of the hindsight headroom.

- Sol commits naive's DA position at watch 0 on 33 of 40 days and mostly holds it. When it re-plans it mostly
  gains: 10 of the 12 re-planned days beat naive, by $21 to $9,418, mostly at the 12:00 and 18:00 watches on the
  settled RT prices.
- It beats the anchor on 9 days, all notice days, and they are exactly the 9 days where naive beats the anchor. Its
  capture minus naive's on notice days is −0.004 (−0.027 to 0.011): no sign yet that it uses the bulletins.
- On the hero day (HB_NORTH on 6 September 2023, when ERCOT declared an EEA2 in the evening) it read the
  reserve-shortage Watch, kept its evening discharge and never re-planned across 9 later watches: C 0.077 against
  the anchor's 0.156 (R 0.596, the same as naive). Profit $14,940, against $30,157 for the anchor and $193,619 in
  hindsight.
- 41 runs, all scored at the first attempt, $2.03 in all. Every episode replays byte for byte on
  `gridsim_core.live` and passes its audit. The full reading is in
  [`results/board-v2.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v2.md).

## v3 preview: Sun, Storage and Reserves

> **A preview, not a release.** The env, the packs and the grading are built and tested, and a registered pilot has
> run on rules 3.2. Some design decisions are open (below). The contract is [`docs/CONTRACT-v3.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v3.md).

**The task.** A solar farm and a battery share one meter at an ERCOT hub or load zone, played live in watches as in
v2 but by the hour. At watch 0 (14:00 on D-1) the agent commits a book for D: each hour's battery move in MW
(positive discharges) and awards in up to five reserve products, Regulation Up and Down, Responsive Reserve (RRS),
ERCOT Contingency Reserve (ECRS) and Non-Spin, paid the day's DA clearing prices. The book becomes the DA position
when watch 0 ends. Each hour settles at its RT price once it has ended. Regulation awards move the battery's charge by
the share of the award that ERCOT's storage fleet delivered in that hour, and ERCOT's real RRS, ECRS and Non-Spin
deployments that day draw reserve energy at their real times; a deployment uses up its product's duration as it runs,
and the energy regulation and deployments move settles at the hour's RT price. The charge must back every up-award for
its product's duration and leave room for RegDn; a governor nudges an hour's move to keep that, and every shortfall is
charged as failure to provide, whether or not the agent could have seen it coming. Plans are in MW, sent as hourly
blocks; a reserve field left out, or sent as `"keep"` or null, keeps the book. 52 turns and 3 planning calls a watch;
a planning call refused as malformed uses none, up to three a watch.

The tiers: `energy` (no reserves) and `reserves` (the DA awards are fixed after watch 0). A third, real-time
reserves tier after ERCOT's RTC+B is built but not playable, since no history of ERCOT's real-time reserve prices was
found: `rtcb` days play the `reserves` tier with DA reserve prices only. Each row of `v3_tasks` is one site-day at one
tier; `oneshot_prompt` is the one-decision prompt path-B training uses.

**Grading.** The headline is hindsight capture C against P_hind, beside the anchor's own C and the paired
Δ = C − C_anchor; idle is the solar-only plant. P_hind is the clairvoyant optimum of the same settlement: one plan that
knows the RT prices, the drift and the deployments, and may fall short of an award and pay for it as a run does. R as
in v1 and v2 comes second, against P_anchor: a rolling mixed-integer plan (HiGHS) with the agent's information, one
solve per watch over the open hours, energy and reserves together, RT expected at DA. At weight 0: the energy-only R
(the energy tier's anchor on the reserves scale), the reserves' share of revenue, and failure-to-provide MWh. The
reference baselines are AS-hog (reserves only, no energy position), the solar sponge (charge only from PV the meter
cannot take) and v2's energy-only rolling plan, each compared as (P − P_ref) / (P_hind − P_idle). Training uses S, R
up to the anchor rising to 1.2 at hindsight (`grade()["stretch_reward"]`); the one-shot path-B reward is R, its anchor
being the one-shot optimum itself.

**Settled in rules 3.2.**
- **Every shortfall is charged (C3-D19).** This reverses the earlier rule (C3-D7), which excused a shortfall the last
  projection had not shown: one that drift or a deployment caused after the hour froze. The excuse was no edge case:
  296 of 300 `eval` reserves anchors carried one (mean $848). On 2025-06-28 at LZ_AEN ERCOT's measured RegUp drift ran
  at 0.757 of the award at 19:00 (its mean is 0.17) and emptied the battery after the day's last watch; $9,744 of
  failure to provide and end shortfall went unpaid and the anchor settled $1,651 above hindsight. Now failure to
  provide and the end penalty are charged on what happened, an up award the battery has no power headroom for is short
  pro rata, and the DA position is the export the book's projection executes.
- **Hindsight bounds the settlement (C3-D20).** P_hind is now the optimum of that same settlement: a clairvoyant plan
  may hold awards it does not back and pay their failure to provide, as a run may. Before, it held the reservation
  band hard, so it was no bound. On the rules-3.1 `eval` reserves days P_hind rose $2,009 a day on average and the
  anchor's C fell from 0.524 to 0.450 (0.453 on the refilled pack); the energy tier, the one-shot optima, the solar
  sponge and v2 energy-only did not move. No stored reference settles above P_hind (the property test under
  [Grading](#grading)).
- **The rules card and the calls (V3-D15, V3-D16, V3-D18).** The card states that the energy regulation and
  deployments move settles at RT, as ERCOT settles it. A planning call refused because its input is malformed uses no
  call, up to three a watch, and its error names the shape the field needs. The board leads with the reserves tier;
  the energy tier is a secondary column.
- **Packs refilled.** The days that failed a filter on the rules-3.2 references were dropped and the build's own draw
  continued over the candidates that pass: 188 `train`, 48 `eval` and 28 `rtcb` days replaced, the others unchanged,
  each `eval` reserve-value stratum kept at 100 days on the cutoffs it was built with.

**Settled in rules 3.1.**
- **Measured regulation drift (V3-D8).** ERCOT publishes no regulation-deployment series, so the drift comes from its
  60-Day SCED Disclosure: the storage fleet's telemetered output against its base points and regulation
  responsibilities gives the share of the award deployed each hour (RegUp 0.17 and RegDn 0.21 on average). It covers
  every `eval` day, 164 of 200 `rtcb` days and 703 of 2,400 `train` days; days before 12 October 2023 and the
  archive's gaps take a fallback fitted to the measured hours, RegUp when RT clears above DA and RegDn when below.
  `flags.reg_drift` says which.
- **A deployment uses up its duration (C3-D18).** In an hour where RRS, ECRS or Non-Spin is deployed, its reservation
  and any shortfall use the duration it has left. On 10 August 2023 the anchor had paid $126k of failure to provide at
  19:00 for ECRS it had just delivered for two hours; it pays nothing there now.
- **Sites that clip (V3-D12).** 40% of sites now have PV AC above the meter (PV AC / POI of 1.11, 1.25 or 1.4), so
  the meter clips and the energy tier tests charging from clipped solar. At that tier, on `eval`'s 104 such days, the
  solar sponge scores 0.39, not idle's 0.2, and v2's PV-blind plan 0.92 (0.85 at 1.4), against 0.97 where the meter
  takes all the PV.
- **Keeping a field (V3-D13).** A reserve field left out, `"keep"` or null keeps the book's values; a malformed field
  still refuses the whole call.

**Open decisions.**
- **6 September 2023 stays display only.** RT cleared above DA in all 24 hours of that EEA2 day, so the fallback drift
  deploys RegUp all day and drains the battery before the evening sale: the reserves anchor ($215k) ends below the
  energy-only plan ($482k). Its reference replays play the energy tier; in the splits, a day where any baseline
  reaches 0.97 against the anchor is dropped.
- **The energy tier is saturated for Sol.** On 10 clipping days it ties the anchor (below), so the tier now tells
  clipping-aware play from PV-blind play, not this model from the anchor.
- **Continuous MW.** Plans are continuous MW, not the 25 MW steps first planned (those made the solver intractable),
  so a plan can differ from the book by fractions of a MW; a value within 0.005 MW of the book counts as the book's.

| Config | Split | Rows | Site-days | Dates | Notice / deployment days | Anchor − idle | Anchor capture | AS-hog R | Energy-only R | v2 energy-only R |
|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|
| `v3_tasks` | `train` | 4,800 | 2,400 | 2021 to 2024 | 1,004 / 301 | $47,110 | 0.594 | 0.680 | 0.531 | 0.430 |
| | `eval` | 600 | 300 | January to November 2025, 100 per reserve-value stratum | 89 / 12 | $12,680 | 0.453 | 0.344 | 0.821 | 0.784 |
| | `rtcb` | 400 | 200 | 5 December 2025 to 30 September 2026 | 42 / 17 | $9,769 | 0.405 | 0.338 | 0.796 | 0.741 |
| `v3_showcase` | `showcase` | 8 | 4 | 10 August 2023, 6 September 2023, 29 March 2024, 26 January 2026; display only | 3 / 2 | $252,595 | 0.376 | 0.314 | 0.808 | 0.771 |

Means at the reserves tier, from `raw/packs/hybrid-stats.md`; at the energy tier v2's energy-only plan scores 0.760
on `train`, 0.955 on `eval` and 0.932 on `rtcb`. The sites are archetypes: 40% a 150 MW-AC solar farm with a
100 MW / 200 MWh battery, 60% sized from the co-located solar and storage in EIA-860 2025's ERCOT records; the meter
sits at the PV's AC rating on 40% of sites, at 1.2 times it on 20% and below it on 40%. PV output is ERCOT's
system-wide hourly solar availability scaled to the site. `v3_references` has, per site-day and tier, the anchor's
profit, book and commits, hindsight, the LP bound, the one-shot optimum and its plan, and each baseline's profit and
R. `v3_episodes` has one row per recorded run, with the book, the DA position, the cash split and the transcript.

**Pilot (rules 3.2).** GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played 30 `eval` days at the
reserves tier, the 24 days of the rules-3.1 pilot that survive the refill and 6 drawn by its rule and seed (10 per
reserve-value stratum, all 12 deployment days), and 10 clipping days at the energy tier (8 survivors, 2 drawn), as
registered in [`docs/prereg/v3-pilot-c.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v3-pilot-c.md),
plus 10 August 2023 and 29 March 2024 at the reserves tier for display. Every run scored at its first attempt.

<!-- board:v3 -->
| Model | Tier | Days | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | C low / mid / high AS | AS share | $ per episode |
|---|---|---:|---|---:|---|---|---:|---:|---|---:|---:|
| GPT-6.1 Sol | reserves | 30 | **0.404 (0.339 to 0.468)** | 0.449 | -0.045 (-0.073 to -0.017) | 0.878 (0.823 to 0.927) | 0.333 | 0.333 | 0.499 / 0.348 / 0.366 | 0.438 | $0.1596 |
| GPT-6.1 Sol | energy | 10 | **0.430 (0.290 to 0.585)** | 0.434 | -0.004 (-0.011 to +0.000) | 0.989 (0.969 to 1.000) | 0.200 | 0.100 | 0.631 / 0.332 / 0.353 | 0.000 | $0.0708 |
<!-- /board:v3 -->

On the same days, C: the solar sponge 0.043, AS-hog 0.043, v2 energy-only 0.320, the energy-only plan 0.350 and the
anchor 0.449 at the reserves tier; the sponge 0.142, v2 energy-only 0.317 and the anchor 0.434 at the energy tier.

- **Reserves: below the anchor.** C 0.404 (0.339 to 0.468) against the anchor's 0.449, Δ −0.045 (−0.074 to −0.017),
  R 0.878 with 10 of 30 days at R = 1. Sol is above the energy-only plan by +0.054 (+0.023 to +0.090), so selling
  reserves with energy earns it more than energy alone, as under rules 3.1; it is above v2 energy-only by +0.084
  (+0.053 to +0.120) and above AS-hog and the solar sponge by +0.362 each. These intervals are the pilot script's
  (`scripts/pilot_v3c.py`).
- **RegUp is still the main loss (exploratory).** Sol now books RegUp, 42 MW-h a day against the anchor's 330 (under
  rules 3.1, 1 on the same days), but the RegUp drift the anchor sells into RT is worth −0.093 of the attainable
  against Sol, more than its whole gap; booking half the anchor's RegDn (311 MW-h a day against 584) wins +0.076 back.
- **Deployment days: handled.** Δ is −0.052 on the 12 days ERCOT deployed reserves and −0.040 on the 18 others, a gap
  of −0.012 (−0.063 to +0.040), inside the registered 0.05 (rules 3.1: −0.093).
- **Energy tier: level with the anchor.** C 0.430 against the anchor's 0.434, Δ −0.004 (−0.011 to −0.000), R 0.989
  on the 10 clipping days; Sol is above v2's PV-blind plan by +0.113 (+0.019 to +0.245).
- **Format.** Every day has an accepted watch-0 commit. One planning call in 40 days was malformed and used no call;
  99 plans kept a reserve field with `"keep"` or null and none was refused for it.
- **Display.** On 10 August 2023 (HB_NORTH) Sol out-earns the anchor, $1,600,835 against $1,554,645, C 0.282 against
  0.262 (R 1.0), committing at both deployment watches. On 29 March 2024, C 0.562 against the anchor's 0.515 (R 1.0).
- 45 runs, the smoke and display runs included, $6.31 in all. Every episode replays byte for byte on
  `gridsim_core.hybrid`; `v3_episodes` also holds 26 reference runs on 10 days the Space replays (the anchor, AS-hog,
  the solar sponge and v2 energy-only). The full reading is in [`results/board-v3c.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v3c.md).
- **Earlier pilots,** on record under their own rules; their episodes are not in this dataset. Rules 3.1, which excused
  unforeseen shortfalls, on packs since refilled: reserves C 0.451 against the anchor's 0.505, Δ −0.054 (−0.091 to
  −0.019) ([`results/board-v3b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v3b.md)).
  Rules 3.0, on packs since rebuilt: reserves C 0.397 against 0.480, Δ −0.083 (−0.120 to −0.049)
  ([`results/board-v3.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v3.md)).

## v4 preview: Weather Front

> **A preview, not a release.** The env, the packs, the forecast store and the grading are built and tested, and a
> registered pilot has run on rules 4.1. Some decisions are open (below), so tiers, filters and numbers may change
> before v4 ships. The contract is [`docs/CONTRACT-v4.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/CONTRACT-v4.md).

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
the store's builder tests it, and each run's audit replays every forecast call against the store. Site PV and the
missing RT reserve prices are as in v3; the regulation drift is v3's earlier seeded draw (`flags.reg_drift`).

**Grading.** The headline is hindsight capture C = (P − P_idle) / (P_hind − P_idle), P_hind the exact plan that
knows the realised prices, PV, drift and deployments, beside the anchor's own C and Δ = C − C_anchor = (P − P_roll) /
(P_hind − P_idle) (the verifier's `paired_vs_anchor`) with its paired 95% interval. C replaces `r_hind`, which stays a
weight-0 row. Second, R = clip(0.2 + 0.8 · (P − P_idle) / (P_roll − P_idle), 0, 1), against the rolling anchor
P_roll: a mixed-integer plan (HiGHS) with the agent's information, one solve per watch on the guide's P50 and the
served forecasts, bidding each gate and committing the open hours. At `blind` the anchor plans on persistence instead
(P_blind). The references, each compared as (P − P_ref) / (P_hind − P_idle): P_roll3 (the same re-planner on the P10,
P50 and P90 paths), P_blind, and the naive gate rule, which charges in the 4 cheapest and discharges in the 4 dearest
DA P50 hours of each day and never re-plans. Training uses S, R up to the anchor rising to 1.2 at hindsight
(`grade()["stretch_reward"]`).

**Settled since the plan.**
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

**Open decisions.**
- **Regulation drift.** v4 still draws the seeded drift that rules 3.1 replaced in v3 with ERCOT's measured one.
- **Shortfalls.** v4 still excuses a shortfall its last projection had not shown, the rule v3 dropped in rules 3.2.
- **The front label as a stratum.** In the pilot Δ is −0.030 on front windows and −0.039 on calm ones (difference
  +0.009, −0.047 to +0.063): at this size the label does not separate Sol's gap.

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

**Pilot (rules 4.1).** GPT-6.1 Sol (`openai/gpt-6.1-sol`, reasoning effort high) played 20 `eval` windows at `front`
(14 front, 6 calm) and 10 more at `front-lite`, redrawn on the 4.1 pack, as registered in [`docs/prereg/v4-pilot-b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v4-pilot-b.md),
plus 3 smoke windows and Fern and Heather for display. Every window served ERCOT's own forecasts.

<!-- board:v4 -->
| Model | Tier | Windows | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | C front / calm | Forecast calls | $ per episode |
|---|---|---:|---|---:|---|---|---:|---:|---|---:|---:|
| GPT-6.1 Sol | front | 20 | **0.463 (0.375 to 0.554)** | 0.496 | -0.032 (-0.064 to -0.001) | 0.911 (0.859 to 0.956) | 0.350 | 0.350 | 0.394 / 0.624 | 26.8 | $0.60 |
| GPT-6.1 Sol | front-lite | 10 | **0.362 (0.262 to 0.463)** | 0.402 | -0.040 (-0.091 to +0.008) | 0.873 (0.765 to 0.961) | 0.200 | 0.200 | 0.314 / 0.473 | 18.9 | $0.20 |
<!-- /board:v4 -->

On the same 20 `front` windows, C: the anchor 0.496, P_roll3 0.494, P_blind 0.375 and the naive gate rule 0.270,
against Sol's 0.463; R: P_roll3 0.973, P_blind 0.762 and the naive gate rule 0.612, against Sol's 0.911.

- **Just below the rolling MILP.** Δ −0.032 (−0.064 to −0.001), its interval ending just below 0; Sol beats the anchor
  on 7 windows, the same 7 at R = 1. It is also below P_roll3, −0.031 (−0.058 to −0.003).
- **Forecasts are worth reading.** Sol is above persistence (P_blind) by +0.088 (+0.040 to +0.141) of the hindsight
  headroom, on 15 of 20 windows, and above the naive gate rule by +0.193 (+0.149 to +0.242).
- **The 4.0 friction is gone.** No forecast call was refused for a malformed time or as issued after now, and no
  `front-lite` hour as a reserve it cannot offer (rules 4.0: 41, 22 and 288). Sol now sends a blank `issued_at` on
  almost every call and reads the latest vintage, but it seldom asks how a forecast moved: 8 of 20 windows call
  `get_forecast_drift`, and no gate had a drift read before its submit.
- **Where the gap is (exploratory).** Against the anchor replayed from its stored calls, Sol gives up DA energy
  (−$9,816 a window) and wins most of it back in real time (+$8,669); it sells a fifth less in reserves and commits
  6.5 times a window to the anchor's 17.6. It missed no gate.
- **`front-lite` stays a warm-up tier:** C 0.362 (0.262 to 0.463) against the anchor's 0.402, Δ −0.040 (−0.091 to
  +0.008), and −0.029 (−0.099 to +0.039) against P_blind; the February 2025 cold snap (LZ_HOUSTON) is again the worst
  window.
- **Fern** (HB_NORTH, 24 to 26 January 2026): C 0.464 against the anchor's 0.603 (R 0.816), $828,699 against
  $1,039,166; the 4.0 run had beaten the anchor here. **Heather**: C 0.649 against the anchor's 0.768 (R 0.876).
- 35 runs, all scored, $24.92 in all: six attempts hit an upstream provider error and scored at their registered
  retry, and the `front-lite` sweep resumed once after stopping at its budget. Every episode replays byte for byte on
  `gridsim_core.forecast` and passes its audit. The full reading is in
  [`results/board-v4b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v4b.md).
- **Earlier pilot (rules 4.0),** on the 4.0 packs: `front` C 0.458 against the anchor's 0.477, Δ −0.019 (−0.057 to
  +0.017); its episodes replay only at the commit it ran on and are not in this dataset
  ([`results/board-v4.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v4.md)).
  On the 11 windows both pilots ran, rules 4.1 did not lift Sol's capture: −0.031 (−0.073 to +0.000).

## v5 preview: The Market Floor

> **A preview, not a release.** The env, the packs, the market days and the grading are built and tested, and a
> registered pilot has run on rules 5.1. Some design decisions are open (below). The contract is
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

**Grading.** The public score is compliant: 0.5 · clip(C, 0, 1) + 0.5 · clip(W / W*, 0, 1), beside the anchor's
score on the same floors and the paired Δ. C = (P − P_idle) / (BR_rt − P_idle), with P_idle = 0 (no offer), is the
hindsight capture against BR_rt, the best SoC-feasible response to the day's clear with deviations settled at
realised RT, the clairvoyant bound of the same settlement; W / W* is the welfare ratio, the share the run delivers of
the welfare a planner could add over A and B idle. A run without a valid offer scores 0. The research board heads
with C, the anchor's C and Δ = C − C_anchor; R = clip(0.2 + 0.8 · (P − P_idle) / (P_anchor − P_idle), 0, 1) comes
second, against the disclosure best-responder: with the agent's information at 09:00 it shifts the curves disclosed
for 61 and 62 days earlier by the forecast change in net load, best-responds to its own price impact with an exact
dynamic program, self-schedules, and at `floor-day` re-plans the operating day. The env's `compliant_reward` row
keeps 0.5 · R + 0.5 · W / W*. At weight 0: capture and regret against BR_A (`p_br`, the day-ahead-only best
response, not a bound: the anchor exceeds it on some floors), ε-Nash, welfare and deadweight loss, the price-making
gain over the impact-blind price-taker, the price impact of A's own awards (`impact_usd`), mitigated hours and a
withholding index. Path B trains on S, R up to the anchor rising to 1.2 at BR_rt (`gridsim_core.market.reward_fn`).

**Real and modelled.** Real: every offer and bid behind the background curve (ERCOT's 60-Day DAM Disclosure,
aggregated to at most 64 points per hour and side), the seats' offers, ERCOT's system lambda, the hub DAM and RT
prices, and on `floor-day` the ERCOT and NWS bulletins. Modelled: one node, no congestion; reserves not cleared again
(each background curve is cut to the room its reserve awards leave); commitment as on the real day; the seats' private
costs (CT heat rates from EIA-923, the wind and solar production tax credit, a retail tariff); and the batteries'
energy, which the disclosure does not give before RTC+B. Each floor carries its day's raw fidelity: the share of
non-scarcity hours where the clear of every real offer lands within $5 or 10% of ERCOT's lambda.

**Settled in rules 5.1.**
- **`train` back to 2022 (V5-P1, V5-P16).** ERCOT's archive holds the disclosure from 1 January 2022, so `train` now
  takes 3,777 floors on 229 dates from 15 July 2022 to 29 December 2024, 23 of them in 2022 and 93 in 2023. The 2022
  files carry one RRS award column, which the reserve truncation now reads.
- **The fidelity bar: 0.7 (V5-P2).** The plan asked for 90% of non-scarcity hours within $5 or 10% of ERCOT's lambda;
  the clear reaches that on 68 of 1,686 days (median 0.67). A floor's day now needs 0.7, which 812 days pass (65 of
  363 in 2022, 175 of 361 in 2025), and the hub offset carries the rest.
- **Two portfolios a date in `eval` (V5-P24).** The bar leaves 147 `eval` dates, so each takes two seat-A draws: 289
  floors. A date is `peak` when its first draw has 2 or more hours of $5 impact: 6 dates, 12 floors. `floor-day`
  stays 60 floors, one a date.
- **Rules 5.1 (V5-P21, V5-P23).** `get_forecast` reads `issued_at` as a time (rules 5.0 compared strings and refused
  197 of the 5.0 pilot's 276 calls); an offer side, a schedule hour or an AS field left out, `null` or `"keep"` keeps
  what was last accepted; `get_disclosure` refuses a day with no full disclosure.

**Open decisions.**
- **The impact filter (V5-P12).** A QSE-sized battery moves the price in few hours: "2 or more hours of $5 impact"
  holds on 10 of 289 `eval` floors. `train` asks for 1 hour of $2 instead, and `eval`'s peak dates are a stratum of
  their own. In the pilot Sol's gap to the anchor changes sign with it: ahead on peak floors, behind on base ones.
- **The price-taker collapse (V5-P18).** On most floors the anchor's best response is the impact-blind price-taker's
  plan: the price-taker scores R = 1.0 on 152 of 289 `eval` floors (mean 0.937). So R mostly measures forecasting and
  scheduling under weak impact, not market power. The board adds the price-making gain over the price-taker as a
  weight-0 row and R on the `peak` stratum as a column of its own.

| Config | Split | Floors | Dates | Peak (2+ impact hours) | Also `floor-day` | Median fidelity | Anchor's C | Price-taker R | Replay A R | Max-withhold R |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `v5_tasks` | `train` | 3,777 | 229 dates, 15 July 2022 to 29 December 2024 | 1,189 | 3,708 | 0.79 | 0.392 | 0.945 | 0.166 | 0.185 |
| | `eval` | 289 | 147 dates, two portfolios a date, 1 January to 28 November 2025 | 12 (6 dates) | 284 (60 in the `floor-day` set) | 0.77 | 0.399 | 0.937 | 0.159 | 0.199 |
| | `rtcb` | 65 | one floor a date, 16 December 2025 to 25 August 2026 | 1 | 62 | 0.79 | 0.354 | 0.933 | 0.140 | 0.200 |
| `v5_showcase` | `showcase` | 6 | 20 August 2024 and Winter Storm Fern, 23 to 27 January 2026; display only | 4 | 4 | – | – | 0.790 | 0.215 | 0.467 |

R values are means at `floor-sprint`; the anchor's C is its mean hindsight capture against BR_rt there. A peak floor
in `eval` is one on a peak date. Seat A is 400, 600, 800, 1,000, 1,200 or 1,500 MW for 1, 2 or 4 hours, with
round-trip efficiency 0.80 to 0.95 and degradation $0 to $8 per MWh.
`v5_references` has, per floor, the anchor's forecast (its net-load shift and the prices it expects), its
self-schedule, P_anchor, P_br and the RT-inclusive bound at each tier with the hindsight awards, and the price-taker,
max-withhold and replay-A baselines' profit and R. `v5_episodes` has one row per recorded run: R, compliant, regret,
capture, welfare ratio, ε-Nash, impact, mitigation, the offer, the awards, the clear, the hourly settlement, the P&L,
the contracts, every call and the transcript.

**The market days.** `raw/v5-market/days/` holds the 1,687 operating days the floors are built from, 1 January 2022 to
25 August 2026, one JSON line a day in 56 monthly files (42 MB gzipped). The 28 months before May 2024 are read only by
`train` floors and are not in the plugin's git checkout: this dataset is where they are published, each checked against
the SHA-256 the days' manifest lists for it. Each day holds the background supply and demand curves, the seat pools'
curves by pool id (`e1`, `c1`, `r1`, `l1`, …, with the CTs' unit sizes and start costs), ERCOT's system lambda, the hub
DAM and RT prices, EIA-930 load, wind, solar and day-ahead forecast, and the clear of every real offer with its
fidelity. They are derived, aggregated and anonymised: no disclosure file is published, and no resource or QSE name
leaves the data build (the dataset's build checks every key and string). `raw/v5-market/` also holds the days' manifest
(each disclosure document's id, posting time and SHA-256), the fidelity statistics (`stats.md`) and the EIA-923 CT heat
rates.

**Pilot (rules 5.1).** GPT-6.1 Sol played 30 `eval` floors at `floor-sprint` (all 12 peak floors and 18 base ones)
and 10 of them at `floor-day` (the 6 peak `floor-day` floors and 4 base), as registered in [`docs/prereg/v5-pilot-b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/docs/prereg/v5-pilot-b.md),
plus two showcase floors for display, played at `floor-day` under the compliant scoring.

<!-- board:v5 -->
| Model | Tier | Floors | Score (95% CI) | Anchor's score | Δ vs anchor (95% CI) | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | Welfare ratio | Mitigated hours | $ per episode |
|---|---|---:|---|---:|---|---|---:|---|---|---:|---:|---:|---:|---:|
| GPT-6.1 Sol | floor-sprint | 30 | **0.308 (0.231 to 0.389)** | 0.410 | -0.101 (-0.164 to -0.043) | **0.296 (0.116 to 0.468)** | 0.419 | -0.123 (-0.279 to +0.024) | 0.696 (0.545 to 0.834) | 0.400 | 0.400 | 0.174 | 0.0 | $0.056 |
| GPT-6.1 Sol | floor-day | 10 | **0.553 (0.453 to 0.650)** | 0.514 | +0.039 (-0.027 to +0.104) | **0.566 (0.399 to 0.735)** | 0.446 | +0.120 (-0.014 to +0.248) | 0.897 (0.775 to 1.000) | 0.700 | 0.700 | 0.539 | 0.0 | $0.130 |
<!-- /board:v5 -->

- **Level with the anchor on C, split by stratum.** Against BR_rt Sol captures 0.296 (0.116 to 0.468) at
  `floor-sprint` and 0.566 (0.399 to 0.735) at `floor-day`, against the anchor's 0.419 and 0.446: Δ −0.123 (−0.279 to
  +0.024) and +0.120 (−0.014 to +0.248), both level at this size. On peak floors Sol is ahead, Δ +0.104 (−0.011 to
  +0.240) on the 12 at `floor-sprint` and +0.195 (+0.017 to +0.344) on the 6 at `floor-day`; on the 18 base floors it
  is behind, −0.274 (−0.484 to −0.073), and 7 sprint floors end below idle. The stratum intervals are the pilot
  script's (`scripts/pilot_v5b.py`), the rest the table's.
- **Spread trades, not withholding.** With the forecasts now served (176 calls, none refused), Sol still offers far
  more than its battery stores, its sell side 6.0 times its energy at `floor-sprint`, and settles what it cannot
  deliver at real time: a day-ahead against real-time position written as a battery's offer. That pays where DA
  cleared above RT, and loses on base floors where Sol bought DAM energy it could not store and sold it back lower in
  real time. On peak floors Sol beats the price-taker by +0.143 (+0.006 to +0.293), through the spread rather than
  its price impact. It was never mitigated, sent no message and signed no CfD.
- **The operating day adds capture.** On the 10 floors played at both tiers, `floor-day` minus `floor-sprint` C is
  +0.173 (+0.003 to +0.367): re-dispatching the operating day turns the oversized DAM position back into physical
  arbitrage.
- **Compliant:** 0.308 (0.231 to 0.389) at `floor-sprint` against the anchor's 0.410, Δ −0.101 (−0.164 to −0.043),
  pulled down by a welfare ratio of 0.17; 0.553 (0.453 to 0.650) at `floor-day` against the anchor's 0.514, Δ +0.039
  (−0.027 to +0.104), first of the six policies there. R comes second: 0.696 and 0.897.
- **Showcase:** on Winter Storm Fern (26 January 2026) Sol's 800 MW makes $9.1M of a $9.5M hindsight, C 0.962
  against the anchor's 0.145; on 20 August 2024, C 0.125 against the anchor's 0.097 (R 1.0).
- 42 runs, all scored; $7.16 in all, the four unpublished smoke runs included. Six attempts hit an upstream
  provider error and scored at their registered retry. Every episode replays byte for byte on `gridsim_core.market`
  and passes its audit. The full reading is in [`results/board-v5b.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v5b.md).
- **Earlier pilot (rules 5.0),** on the 5.0 packs: C 0.348 at `floor-sprint` and 0.419 at `floor-day`, against the
  anchor's 0.414 and 0.419, Δ −0.067 (−0.204 to +0.058) and −0.000 (−0.114 to +0.089); its episodes are not in this
  dataset ([`results/board-v5.md`](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/PREVIEW_REF/results/board-v5.md)).
  On the 7 floors both pilots played, Sol's 5.1 runs capture less, −0.104 (−0.176 to −0.036), one run a floor each.

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
ancillary-service clearing prices (NP4-181-ER and NP4-188-CD, *DAM Clearing Prices for Capacity*), its system-wide solar
output (PG7-126-M, *Hourly Aggregated Wind and Solar Output*, and the *Fuel Mix Report*), and the dates, times, types
and levels of its operations messages and news releases, reserve deployments included. No ERCOT notice text is
reproduced: each bulletin is our own one-line paraphrase. v3's regulation drift is derived from ERCOT's 60-Day SCED
Disclosure Reports (NP3-965-ER), obtained through the ERCOT Public API and reduced to the storage fleet's hourly
deployed share of its regulation awards; no disclosure file and no resource name is published. Solar capacity for 2021,
2022 and 2026 uses the EIA's Form EIA-860M (public domain). NWS watches, warnings and advisories come from the Iowa
Environmental Mesonet's archive of NWS VTEC products (Iowa State University; NWS data in the public domain), reduced to
the product, counties and times.

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
