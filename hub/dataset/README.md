---
license: other
license_name: ercot-website-user-agreement-eia-public-domain-apache-2.0
license_link: https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/data/LICENSE
pretty_name: 'GridSimEnv Desk: a live ERCOT battery desk'
language:
- en
task_categories:
- reinforcement-learning
- text-generation
size_categories:
- n<1K
tags:
- agentenv
- rl-environment
- agents
- tool-use
- simulation
- energy
- electricity-markets
- battery-storage
- ercot
- real-world-data
- ancillary-services
- solar
- weather
- forecasting
- auctions
---

<div align="center">

<!-- badges -->

</div>

# GridSimEnv Desk

<!-- pitch -->

<!-- gif -->

<!-- bench -->

<!-- earlier -->

## Quick start

<!-- quickstart -->

## The desk

**An agent trades one real ERCOT battery from the day-ahead market through real time, on ERCOT's own market objects
and on data as ERCOT posted it, graded in dollars against the hindsight optimum and the battery's real operator.**

- **A real battery, ERCOT's own objects.** The agent is the battery trader at a qualified scheduling entity (QSE) for
  one real ERCOT energy storage resource at its own node, from 06:00 the day before to midnight on the operating day
  (three operating days in v4). It never moves a megawatt itself: it bids energy curves into the day-ahead market (DAM)
  before the 10:00 close, sends real-time (RT) curves from 18:00 and keeps its Current Operating Plan (COP), all
  checked against ERCOT's rules; ERCOT's clearing decides what the battery does every 5 minutes.
- **Time moves on its own.** The clock stands still while the agent works. It wakes at the market's milestones, at
  each notice, outage and reserve deployment at its real minute and at reminders it sets, and sees each price,
  forecast and report only once ERCOT posted it.
- **Graded in dollars.** P is the battery's settled ERCOT statement. The headline is C, the share of the hindsight
  optimum's profit over idle that the desk captures; R, the environment's reward, is reported beside it.
- **Against the real operator.** ERCOT discloses every resource's bids, awards and metered output 60 days later. Each
  task replays the real operator's own bids through the same clearing and settlement, and settles its actual awards and
  output the same way.
- **Three versions (v2–v4) plus a price-impact check (v5).** Each version adds one kind of realism to the same desk:
  v2 trades energy alone, v3 adds ERCOT's reserves and a solar option, v4 three-day weather fronts. v5 re-runs v3's
  battery-days with the desk's own day-ahead offers re-clearing the market.

<!-- ladder -->

**Eleven tools, each a system a real desk uses.**

| System | Tools |
|---|---|
| ERCOT's public reports | `get_prices`: the node's DAM, 15-minute RT and 5-minute SCED prices, the hub's DAM and RT<br>`get_forecasts`: ERCOT's load, wind, solar and outage forecasts as issued, NWS alerts, and the desk's price forecast (modelled)<br>`get_grid_conditions`: reserves (PRC, a modelled proxy after RTC+B), system lambda, load, wind, solar and notices |
| Plant telemetry | `get_asset_status`: state of charge, limits, recent base points and outages |
| The desk's book | `get_position`: DAM awards, RT position, the COP and the statement settled so far |
| ERCOT's market submission system | `submit_dam_offers`, `submit_rt_offers` and `update_cop`, and `check_submission`, a dry run that returns ERCOT-style validation codes; from v3, ancillary-service offers ride in the same submissions |
| The desk's analytics | `optimize`, a co-optimiser on the agent's own price view that proposes curves and a COP and never submits; `set_reminder` |

**How time works.** The clock is AgentEnv's virtual clock, frozen while the agent works; there is no `advance` tool.
After each turn a post-turn hook takes the earlier of the desk's next wake-up and the gateway's next time trigger,
moves the clock there, and the environment runs the market forward to that minute: the DAM clears at the node's real
day-ahead price (in the v5 price-impact check, at a price re-cleared against the day's real offers with the desk's
own), every 5-minute dispatch run clears the curve in force at the node's real price within the battery's limits and
state of charge, and each 15-minute interval settles. A 5-minute price becomes visible one minute after its interval,
a 15-minute price two minutes after, each forecast vintage as issued and each notice at its minute. The runs here play
the same desk in process; the environment's tests check that both paths give byte-identical tool outputs and wake-ups.

**How a task is graded.** P sums the statement's lines: DAM energy, RT imbalance at the node's 15-minute price,
set-point deviation charges, from v3 ancillary-service capacity and imbalance, and the modelled lines. C = (P −
P<sub>idle</sub>) / (P<sub>hind</sub> − P<sub>idle</sub>), against the hindsight optimum, which knows every price in
advance and may hold DAM/RT spread positions. The reward is R = clip(0.2 + 0.8 (P − P<sub>idle</sub>) / d, 0, 1)
with d = max(P<sub>anchor</sub> − P<sub>idle</sub>, 0.1 (P<sub>hind,phys</sub> − P<sub>idle</sub>)): idle scores
0.2 and the anchor 1.0, and the floor keeps R defined where the anchor barely beats idle. No valid submission scores
R = 0.

## Methods

- **Pre-registered, then frozen.** The three versions (v2–v4) plus a price-impact check (v5) each had a
  pre-registration committed before the first scored episode
  ([v2](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v2-desk.md),
  [v3](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v3-desk.md),
  [v4](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v4-desk.md),
  [v5](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v5-desk.md)): the pack, the
  models and their settings, the references, what is reported and the prior. The code is frozen at a tag before any
  scored run (`desk-v2-freeze`, `desk-v3-freeze`, `desk-v4-freeze` and `desk-v5-freeze`). Nothing is rerun to improve
  a score, and anything done differently is logged as a deviation in the pre-registration; v4's are also stated
  beside its results.
- **Reviewed and piloted.** A review of the environment before v2's runs found two information-timing leaks, fixed
  before any scored episode. Each version is then piloted on one or two tasks before its eval; the pilots are
  mechanics checks, not results.
- **The v4 benchmark** plays v4's desk, frozen at `desk-v4-freeze`, on 32 windows (v4's 16 and 16 after every
  model's training cutoff) with each model in a native agent harness, under a pre-registration of its own.
  `scripts/desk_bench_results.py` scores a model's first attempt on a window that reached the grade, counts every
  attempt in the cost, and never imputes a window a model did not finish.
<!-- bench-rule -->
- **Every grade replayed.** `scripts/desk_report.py` re-grades every Episode JSON against frozen references, and each
  version's `summary.json` records the references used and every difference from the runner's own grade.
- **References on every task,** settled by the same clearing, physics and settlement code: idle; the anchor, the
  desk's own optimiser re-planning at every wake on the same information, its risk setting and DAM basis chosen blind
  on a separate tuning pack (`desk-v2-tune`); the hindsight optimum, and its variant with the DAM position tied to
  dispatch; the real operator's disclosed bids, replayed, and its actual awards and metered output, settled.
- **Uncertainty.** 95% CIs come from a block bootstrap over operating days (in v4, over the four weather fronts; in
  the benchmark, over its eight, four within each side of the cutoffs): 10,000 resamples, seed 0, task-weighted.
  Paired gaps resample the tasks both sides played.
<!-- models -->

## Limitations

- **DAM credit screening is not modelled.** ERCOT screens a QSE's day-ahead bids and offers against its available
  credit; here, day-ahead positions are bounded only by the battery's MW limits. That favours large DAM/RT spread
  positions, and the days where those paid carry most of v2's and v4's dollars.
- **A known env defect in v3 to v5 (K1).** An empty `as_offers` list drew a spurious ASO-02 note while the energy
  curves in the same call were accepted. It was fixed after the freezes; the reserve figures leave those calls out of
  the refused offers.
- **Modelled lines.** The co-located solar profile, degradation, warranty overage, the end-of-day energy charge and
  the capacity-short charge are modelled and marked as such; so is the desk's own price forecast, built only from
  data public at the time.
- **One battery is a price taker.** In v2 to v4 the desk clears at the real prices; the v5 price-impact check
  re-clears the DAM with the desk's own offers and shows that a 100–150 MW battery moves the day-ahead price by cents.
- **One run per model per task, and small packs.** 16 to 32 tasks per version over four to eight blocks, so the CIs
  are wide; the v5 check repeats v3's battery-days, and the gaps between the two runs are the scale of that noise.

## Next steps

- **A fleet desk:** a QSE trading a portfolio of batteries, bidding them into the DAM at once, where price impact can
  matter.
- **More runs per task,** to separate skill from run-to-run noise, and more model families on the same packs.

## What's inside

<!-- inside -->

## Data sources and licence

| Source | What it gives | Terms |
|---|---|---|
| ERCOT public reports: DAM and RT settlement point prices (NP4-190-CD, NP6-905-CD), SCED LMPs (NP6-788-CD), ancillary-service prices (NP4-188-CD, NP6-332-CD, NP6-331-CD), demand curves (NP4-212-CD), system lambda (NP6-323-CD), load, wind and solar (NP6-345-CD, NP4-733-CD, NP4-738-CD), forecasts as issued (NP3-565-CD, NP4-742-CD, NP4-745-CD), outage capacity (NP3-233-CD), unplanned outages (NP1-346-ER) and operations notices | what the desk sees, as ERCOT posted it | ERCOT's Website User Agreement, section 5; not relicensed |
| ERCOT 60-day disclosures: DAM (NP3-966-ER), SCED (NP3-965-ER) and COP (NP3-991-EX) | the real operator's bids, awards and output, replayed and settled; each battery's calibrated round-trip efficiency and standby loss | the same; only derived values are published |
| NWS watches, warnings and advisories, through the Iowa Environmental Mesonet's VTEC archive | the weather alerts that wake the desk | NWS data, public domain |
| U.S. Energy Information Administration, Form EIA-860M | the solar capacity behind the modelled co-located PV | public domain |
| `gridsim_core`, the environment and the scripts that build this dataset | the clearing, settlement, grader and env | Apache-2.0 |

The dataset carries several sets of terms, hence `license: other`; the plugin's
[data/LICENSE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/data/LICENSE) holds the ERCOT
terms in full and [NOTICE](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/NOTICE) sets out each
source. ERCOT data is used under ERCOT's Website User Agreement, section 5, quoted from <https://www.ercot.com/help/terms>:

> 5. The information presented on this website has been compiled by or for ERCOT for general information purposes
> only. The publicly available contents of this website may be used, reproduced, and redistributed, provided that the
> contents are not modified and that you maintain all copyright and other notices contained in the contents,
> including this Agreement. Notwithstanding the foregoing, raw data provided in public portions of this website may
> be used, reproduced, and redistributed in compilations, charts, and analyses without maintaining such notices.
> ERCOT does not guarantee the accuracy of any such compilations, charts, or analyses.

The ERCOT data is not relicensed, and anyone using it is bound by ERCOT's terms. No disclosure file is in this
dataset, and no resource, node, QSE or operator name: the four batteries appear only as anonymous cards (Battery S01
to S04) by region and size. Source: ERCOT. GridSimEnv is not affiliated with or endorsed by ERCOT, NOAA, the EIA or
the Iowa Environmental Mesonet.

## Citation

```bibtex
@misc{gridsimenvdesk2026,
  title = {{GridSimEnv} Desk: trade a real {ERCOT} battery from the day-ahead
           market through real time, an {AgentEnv} environment},
  author = {Arakelyan, Edgar},
  year = {2026},
  url = {https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv},
  note = {Desk versions v2 to v4, a price-impact check (v5) and the v4
          benchmark of models in native agent harnesses. Code:
          \url{https://github.com/earakely-scale/agentenv-gridsim-plugin}}
}
```

---

<!-- archive -->
