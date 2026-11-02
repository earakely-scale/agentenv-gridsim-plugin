---
title: GridSimEnv Desk Environment
emoji: 🔋
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8000
base_path: /web
pinned: false
license: apache-2.0
short_description: Trade a real Texas battery's desk, as the agents do
tags: [openenv, simulation, rl-environment, energy, electricity-markets, battery-storage, agentenv]
datasets: [earakely-scale/GridSimEnv-AgentEnv]
---

# GridSimEnv Desk · OpenEnv

Run a real Texas battery's trading desk for three days across a weather front, on ERCOT's records as they were posted: the v4 benchmark's 32 windows, with the eleven desk tools, the call budget and the grade the benchmark's agents had.

**Try Environment** plays a window by hand beside the battery site in 3D, in that window's real light and weather. Pick
`reset(split=)` and `reset(index=)`, load it, then work the desk: ask for prices and forecasts, run the optimizer,
submit day-ahead and real-time offers and your current operating plan (COP), set reminders, and end your turn to let
the market run to your next wake-up. Quick play does the short version (optimize, submit its proposal, end the turn)
and its autopilot repeats it to the end. **Playground** is OpenEnv's MCP playground over the same tools. Each visitor
gets their own episode in both tabs.

It is the benchmark's environment, not a copy of it: every session runs `gridsim_core.desk.Session`, the state
machine the benchmark's `gridsim-desk` env serves, on the benchmark's pack, and is graded with the pack's stored
references. All 476 recorded benchmark episodes replay through this server's WebSocket with every wake-up and every
grade the same, and every tool answer the same byte for byte but one kind: an empty `as_offers` list no longer draws
the spurious ASO-02 note of the benchmark's frozen core (107 answers in 17 episodes; it changes nothing else). That is
on x86_64, where the Space and the benchmark run; on arm64 the optimizer's LP breaks some ties differently.

| Path | What |
|---|---|
| `/web` | the page: **Try Environment** and OpenEnv's **Playground** |
| `/play/` | the Try Environment page on its own (`?task=desk-v4-2026-08-18-S02` or `?index=25`, `&theme=dark`) |
| `/reset`, `/step`, `/state`, `/schema`, `/ws`, `/mcp`, `/health` | OpenEnv |
| `/gridsim_desk/...` | OpenEnv's Task API: `splits`, `num_tasks`, `task`, `task_range`, `tasks` |
| `/api/windows`, `/api/episodes/{id}` | read-only JSON for the play page (`server/viewer.py`) |

## An episode

`reset(split="bench", index=i)` or `reset(task_id="desk-v4-2026-08-18-S02")` opens a window at 06:00 Central the day
before its first operating day (`reset()` alone opens that one; `reset(seed=n)` draws one). The observation's metadata
holds the first `prompt` (the start wake-up, as JSON text), the `system_prompt` (the desk brief the agents had) and the
window's card. The clock is frozen while you work. Call tools, then `end_turn`: the market runs to your next wake-up (a
market milestone, a shift checkpoint, an ERCOT notice, an NWS alert, an outage or your own reminder) and `end_turn`
answers with its message as the next `prompt`. The `end_turn` that ends the window comes back `done`, with the reward.

Budgets are the benchmark's: 100 turns, 14 tool calls per turn (a 15th call is refused, and `end_turn` is free), 12
pending reminders. A window wakes the desk 17 to 43 times before any reminder you set; the benchmark's agents took 17 to
97 turns, 33 at the median.

## Tools

| Tool | Does |
|---|---|
| `get_prices` | posted prices only: DAM by hour, RT every 15 minutes, SCED every 5 minutes, at your node or hub; AS prices and demand curves |
| `get_forecasts` | as-issued forecasts: the desk's price forecast (P10/P50/P90, modelled), ERCOT load, wind, solar, net load, outage capacity, NWS alerts |
| `get_grid_conditions` | reserves (PRC), system lambda, load, wind, solar, EEA level, recent ERCOT notices |
| `get_asset_status` | the battery: status, charge, limits, base points, outages, cycles, parameters |
| `get_position` | DAM awards, real-time dispatch, curves in force, COP, the shadow statement |
| `submit_dam_offers`, `submit_rt_offers` | ESR energy bid/offer curves per hour, with AS offers |
| `update_cop` | the current operating plan per hour |
| `check_submission` | validate a submission without sending it |
| `optimize` | co-optimise DAM and real time on a price view; proposals only |
| `set_reminder` | wake yourself at a time |
| `end_turn` | end your turn with your reply |

The schemas are the desk's own (`gridsim_core.desk.tool_specs`); arguments reach the desk as sent, and a malformed call
gets the desk's own answer.

## Reward

The reward is the desk's R, from the `end_turn` that ends the window (0.0 on every other step), through an OpenEnv
rubric whose children report the hindsight capture C and whether any submission was accepted:

- P is the window's settled profit under ERCOT's rules (DAM and real-time energy and reserves, less deviation charges
  and modelled degradation).
- R = clip(0.2 + 0.8 (P − P_idle) / (P_anchor − P_idle), 0, 1), where the anchor is the desk's optimizer at every
  wake-up; 0 with no accepted submission.
- C = (P − P_idle) / (P_hindsight − P_idle), the benchmark's headline.

The final observation's metadata holds the grade (P, R, C, the references, the real operator's own P from ERCOT's
60-day disclosures) and the settlement statement.

## Connect

```python
from gridsim_desk import GridSimDesk

with GridSimDesk(base_url="https://earakely-scale-gridsimenv-openenv.hf.space").sync() as env:
    env.reset(split="bench", index=25)
    print(env.call_tool("get_forecasts", kind="price", market="dam", day="D0"))
    print(env.call_tool("end_turn", response="waiting for the DAM results"))
```

`git clone https://huggingface.co/spaces/earakely-scale/GridSimEnv-OpenEnv` and `pip install ./GridSimEnv-OpenEnv`
install the client. (`pip install git+https://huggingface.co/spaces/...` does not work: pip makes a partial clone, and
Hugging Face's git server cannot complete one.) The Task API describes each window as AgentEnv's OpenEnv adapter
(`agent_env.openenv`) does, with its `prompt`, `system_prompt`, `toolset` and `turns`, so AgentEnv's TRL helper
(`agent_env.training.trl.AgentEnv`) reads the windows and their tools.

## Run it

```bash
pip install -r requirements.txt
ENV_README_PATH=README.md uvicorn server.app:app --port 8000 --ws-ping-interval 60 --ws-ping-timeout 600
```

Each WebSocket session is its own environment; at most `MAX_CONCURRENT_ENVS` (32) at a time, and one idle for
`SESSION_IDLE_S` (20 minutes) is closed. The play page can replay a closed session's moves to restore it. No model is
called and nothing secret is read.

## Data

The four batteries are real ERCOT energy storage resources, shown by region and size only. Prices, system data,
notices and the operators' 60-day disclosures: ERCOT public reports; ERCOT does not endorse this work. Weather alerts:
NWS. Observed weather: Iowa Environmental Mesonet ASOS archive. The desk's price forecasts, degradation and warranty
are modelled.

## Links

- Article: https://huggingface.co/spaces/earakely-scale/GridSimEnv
- Benchmark replays in 3D: https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv
- Dataset (tasks, episodes, results): https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv
- Code: https://github.com/earakely-scale/agentenv-gridsim-plugin/tree/main/hub/openenv
