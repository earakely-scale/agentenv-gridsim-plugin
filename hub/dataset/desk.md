## GridSimEnv Desk

{gif}**The desk seats the agent at a real ERCOT battery's trading desk for a whole market day,** from 06:00 the day
before to midnight on the operating day.

- **A real battery, ERCOT's own objects.** The agent is the battery trader at a QSE for one real ERCOT energy storage
  resource at its own node. It never moves a megawatt itself: it bids energy curves into the day-ahead market (DAM)
  before the 10:00 close, sends real-time (RT) curves from 18:00 and keeps its Current Operating Plan (COP), all
  validated by ERCOT's rules; ERCOT's clearing decides what the battery does every 5 minutes.
- **Time moves on its own.** The clock stands still while the agent works. It wakes at the market's milestones, at
  each notice, outage and deployment at its real minute and at reminders it sets, and sees each price, forecast and
  report only once ERCOT posted it.
- **Graded in dollars.** P is the battery's settled ERCOT statement; degradation, warranty, end-of-day energy and,
  from v3, co-located solar and reserve capacity short are modelled. The headline is C, the share of the hindsight optimum's profit over idle that the desk captures.
- **Against the real operator.** The battery's real operator, through its bids, which ERCOT discloses 60 days later,
  replayed through the same clearing and settlement, and through its actual awards and metered output, settled the
  same way.

{results}

<details>
<summary><b>The desk in detail</b>: the version ladder, the eleven tools and how a battery-day is graded</summary>

{ladder}

**Eleven tools, each a system a real desk uses:**

| System | Tools |
|---|---|
| ERCOT's public reports | `get_prices`: the node's DAM, 15-minute RT and 5-minute SCED prices, the hub's DAM and RT<br>`get_forecasts`: ERCOT's load, wind, solar and outage forecasts as issued, NWS alerts, and the desk's price forecast (modelled)<br>`get_grid_conditions`: reserves (PRC, a modelled proxy after RTC+B), system lambda, load, wind, solar and notices |
| Plant telemetry | `get_asset_status`: state of charge, limits, recent base points and outages |
| The desk's book | `get_position`: DAM awards, RT position, the COP and the statement settled so far |
| ERCOT's market submission system | `submit_dam_offers`, `submit_rt_offers` and `update_cop`, and `check_submission`, a dry run that returns ERCOT's validation codes |
| The desk's analytics | `optimize`, a co-optimiser on the agent's own price view that proposes curves and a COP and never submits; `set_reminder` |

**How time works.** The clock is AgentEnv's, frozen while the agent works; there is no `advance` tool. After each turn
a post-turn hook takes the earlier of the desk's next wake-up and the gateway's next time trigger, moves the clock
there, and the environment runs the market forward to that minute: the DAM clears at the node's real day-ahead price,
every 5-minute dispatch run clears the curve in force at the node's real price within the battery's limits and state
of charge, and each 15-minute interval settles. Every price, forecast vintage and notice becomes visible at its real
posting time (a 5-minute price one minute after its interval, a 15-minute price two minutes after).

**How a battery-day is graded.** P sums the statement's lines: DAM energy, RT imbalance at the node's 15-minute
price, set-point deviation charges and the modelled lines. C = (P − P<sub>idle</sub>) / (P<sub>hind</sub> −
P<sub>idle</sub>), against the hindsight optimum, which knows every price in advance and may hold DAM/RT spread
positions. The anchor is the desk's own optimiser re-planning at every wake on the same information; it can take
spread positions too, which pay off on scarcity days. The env's reward R = clip(0.2 + 0.8 (P − P<sub>idle</sub>) /
(P<sub>anchor</sub> − P<sub>idle</sub>), 0, 1), with a floor when the anchor barely beats idle, is reported and used
for training, second to C. No valid submission scores R = 0.

</details>

---
