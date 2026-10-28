## GridSimEnv Desk

**v1 hands the agent one day's prices and takes back 24 numbers. The desk seats it at a real battery's trading desk
for the whole market day.** The agent is the battery trader at a qualified scheduling entity (QSE) for one real ERCOT
energy storage resource (ESR), trading at the battery's own resource node from 06:00 the day before to midnight on the
operating day. Like a real desk it never moves a megawatt itself: it offers energy bid/offer curves into the
day-ahead market (DAM) before the 10:00 close, sends real-time (RT) curves once the adjustment period opens at 18:00,
and keeps its Current Operating Plan (COP) up to date. ERCOT's clearing decides what the battery does every 5 minutes,
and the day settles on ERCOT's statement.

- **Real ERCOT data and objects.** Real batteries, shown by card name, with their own nodes' DAM settlement point
  prices and 5-minute SCED prices, ERCOT's load, wind and solar forecasts as each was issued, notices, NWS alerts and
  the batteries' own forced outages. The agent submits ERCOT's own objects, validated by ERCOT's rules (2 to 10 points
  a curve, the −⁠$250 floor, the $5,000 DAM and $2,000 RT caps, the submission windows); invalid ones are rejected with
  ERCOT-style codes.
- **Time moves on its own.** The clock stands still while the agent works and runs between its turns. The agent
  wakes at the market's milestones (the DAM results at the minute ERCOT posted them, the adjustment period, shift
  checkpoints), at each notice, outage and deployment at its real minute, and at reminders it sets. Waiting means
  ending its turn, and every price, forecast and report becomes visible only once ERCOT would have posted it. The
  clock is AgentEnv's: gateway time triggers and a post-turn hook move it, with no `advance` tool.
- **Graded on the settled statement.** P is the day's ERCOT statement for the battery: DAM energy, RT imbalance at the
  node's 15-minute prices and set-point deviation charges, less degradation, warranty and end-of-day energy lines,
  which are modelled and labelled as such. The headline is C, the share of the hindsight optimum's profit over idle
  that the desk captures. Every battery-day also carries an anchor, the desk's own optimiser re-planning at every
  wake on the same information, and **the real operator**: its bids, disclosed by ERCOT 60 days later, replayed
  through the same clearing and settlement, and its actual awards and metered output settled the same way.

{results}

{ladder}

**Eleven tools, each a system a real desk uses:**

| System | Tools |
|---|---|
| ERCOT's public reports | `get_prices`: the node's DAM, 15-minute RT and 5-minute SCED prices, the hub's DAM and RT<br>`get_forecasts`: ERCOT's load, wind, solar and outage forecasts as issued, NWS alerts, and the desk's price forecast (modelled)<br>`get_grid_conditions`: reserves (PRC, a modelled proxy after RTC+B), system lambda, load, wind, solar and notices |
| Plant telemetry | `get_asset_status`: state of charge, limits, recent base points and outages |
| The desk's book | `get_position`: DAM awards, RT position, the COP and the statement settled so far |
| ERCOT's market submission system | `submit_dam_offers`, `submit_rt_offers` and `update_cop`, and `check_submission`, a dry run that returns ERCOT's validation codes |
| The desk's analytics | `optimize`, a co-optimiser on the agent's own price view that proposes curves and a COP and never submits; `set_reminder` |

**Run the desk.** It lives on the plugin's `desk` branch; the commands below pin the `{ref}` tag. In process, with no
Docker and no key, play the anchor policy on the pilot's two real battery-days:

```bash
git clone --branch {ref} https://github.com/earakely-scale/agentenv-gridsim-plugin
cd agentenv-gridsim-plugin && uv sync --extra dev
uv run python scripts/desk_run.py --pack desk-v2-pilot --policy anchor --out runs/anchor
```

Each run writes every battery-day's Episode JSON and a results row with its grade; `--policy model` with `--base-url`
plays a model behind any OpenAI-compatible endpoint the same way. The tables load like any other config:

```python
from datasets import load_dataset

repo = "earakely-scale/GridSimEnv-AgentEnv"
board = load_dataset(repo, "desk_leaderboard", split="{latest}")  # models and references
runs = load_dataset(repo, "desk_runs", split="{latest}")          # one row per battery-day
```
