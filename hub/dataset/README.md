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

GridSimEnv hands an AI agent the trading desk of a real battery on the Texas grid. For three days at a time, while a real
heat wave or winter storm sweeps across Texas, it reads ERCOT's prices and forecasts as they were posted, bids the
battery into the power markets and decides when to charge and when to sell. Every window is settled in dollars and
scored against the best plan hindsight allows. We put {F.env.models} AI models through {F.env.windows} of these windows,
and in the {F.duel.front} most of them out-earned the real operator at {F.duel.most} of the {F.env.sites_word}
batteries.

<!-- film -->

## Before and after: the real operator and the agents

Every window also happened for real. The battery's own operator traded those same three days, and ERCOT publishes what
each battery did 60 days later: its day-ahead awards, its output and its charge every five minutes
([NP3-966-ER](https://www.ercot.com/mp/data-products/data-product-details?id=NP3-966-ER),
[NP3-965-ER](https://www.ercot.com/mp/data-products/data-product-details?id=NP3-965-ER)). That gives each window a before
and an after. Here are the {F.duel.n} windows where the agents most clearly beat the operator, all on the
{F.duel.span} {F.duel.kind}, after every reported training cutoff. Each shows the operator beside the run that made the
most there, {F.duel.best}'s.

<!-- duel -->

Most of each gap is day-ahead trading. Through most of this heat wave the day-ahead price ran above real time, and
{F.duel.best} sold far more energy a day ahead than the battery could deliver, then bought it back in real time,
cheaper; other models traded the same way on a smaller scale. ERCOT's day-ahead market allows such positions because it
ignores a battery's charge; its credit screening, not modelled here, would limit them. They do not always pay: on the
next front, {F.duel.next.span}, real-time prices spiked to about {F.duel.next.rt} a MWh, and the operator came out ahead
of at least {F.duel.next.behind} of the models at each of its {F.duel.next.sites} batteries.

## Try it

The [GridSimEnv Playground]({F.tryit.space}), the environment's OpenEnv Space, runs it live. Load a window and run the
desk with the agents' own {F.tryit.tools} tools, call budget and grade: ask the optimizer, send its offers, end your turn and watch the
market play out beside the battery in 3D, then see how you rank against the real operator and the {F.env.models}
models.

<!-- tryit -->

## Why it matters

A grid battery makes its money on decisions: when to charge, when to sell and how much to hold in reserve, around the
clock in ERCOT's day-ahead and real-time markets. The same hardware earns very different amounts depending on who bids
it, so closing that gap is revenue without a single new battery, and well-timed batteries put power on the grid exactly
when it is scarcest, on heat-wave evenings and storm mornings.

<!-- tiles -->

That work is done today by round-the-clock trading desks and
[bidding software](https://fluenceenergy.com/mosaic-for-ercot/); an AI agent with the same forecasts, notices and rules
could watch every interval, act on news in seconds and let one desk run far more batteries. No one should hand a real
battery to an untested agent, though: here, one bad position in a price spike
[lost {F.eval.watch.lost} in a single window](#watch-a-rollout), nearly twice what the same model made at the same
battery a week earlier. GridSimEnv is where to test and train them first: real ERCOT days, the desk's own tools and
rules, and every window settled in dollars against hindsight and the battery's real operator.

## The eval

{F.header.models} models ran all {F.env.windows} windows once, each in its maker's own harness ({F.eval.closed}) or, for
the open-weight models, {F.eval.open}, with the same {F.tryit.tools} tools, {F.eval.calls} calls a wake-up and at most
{F.eval.turns} wake-ups a window.

<!-- pareto -->

- **{F.eval.lead.a.name} leads at {F.eval.lead.a.C}** of the best possible profit, for {F.eval.lead.a.usd} a window.
  {F.eval.lead.b.name} is close behind at {F.eval.lead.b.C} for {F.eval.lead.b.usd}; the 95% CI on the gap,
  {F.eval.lead.lo} to {F.eval.lead.hi} points, includes zero.
- **Every model scores lower in {F.eval.halves.post} than in {F.eval.halves.pre}**, even {F.eval.halves.old}, trained
  before any window: the later fronts are harder, not just unseen. On {F.duel.next.span}, a real-time spike to about
  {F.duel.next.rt} left {F.eval.halves.lost} of the {F.env.models} models in the red.
- **What to train next: re-planning to the end.** The later a model's last accepted offer, the higher it scores, a
  rank correlation of {F.eval.replan.rho} across the {F.env.models}: {F.eval.replan.a}'s last accepted offer comes
  {F.eval.replan.ah} hours before a window ends on average, {F.eval.replan.b}'s {F.eval.replan.bh}. Distilling the
  desk's own planner already lifted {F.eval.replan.base} from {F.eval.replan.baseC} to {F.eval.replan.sftC}, near the
  planner's {F.eval.replan.planner}.

<!-- board -->

### Watch a rollout

All {F.eval.runs} runs replay in the [Replays Space]({F.eval.viewer}): the battery site in 3D in its real light and
weather, each wake-up's tool calls and what the agent wrote, the market and the battery as they moved, and the grade.

<!-- rollout -->

### How the reward works

Every window ends in an ERCOT settlement statement: day-ahead and real-time energy, reserves, imbalance and battery
wear, priced by the market's own rules. The score is that statement's total P, so it is deterministic, with no judge
model and no sampling. Capture C places P between doing nothing and perfect hindsight,
C = (P − P<sub>idle</sub>) / (P<sub>hind</sub> − P<sub>idle</sub>): 0% at idle, 100% at hindsight, below zero for a run
that does worse than idling. The contract's reward R runs from 0.2 at idle to 1 at the desk's own planner,
R = 0.2 + 0.8 (P − P<sub>idle</sub>) / (P<sub>plan</sub> − P<sub>idle</sub>) clipped to 0 and 1, with the planner's
margin over idle counted as at least a tenth of the physical hindsight's; it is 0 for a run with no accepted offer.

<!-- reward -->

The references are settled the same way. Hindsight is the best plan the market's rules allow with every price, award
and deployment of the window known in advance, one linear program solved by the same optimiser the agents can call.
Idle sends no offers. The planner is that optimiser re-planning at every wake-up on exactly what the agent can see. The
real operator appears twice: its own disclosed bids replayed through the same clearing and settlement, and what it
actually did, settled on the same statement. Offers the desk's checks refuse change nothing.

On the film's window {F.reward.name} settles {F.reward.P}, idle settles {F.reward.idle} and hindsight {F.reward.hind},
so C = ({F.reward.P} − {F.reward.idle}) / ({F.reward.hind} − {F.reward.idle}) = {F.reward.C}. It beat the planner's
{F.reward.plan}, so its R is capped at 1.

## Training on GridSimEnv

We fine-tuned {F.train.base_name} with TRL on transcripts of the desk's own planner, which calls `optimize` and submits
its proposal. AgentEnv captured them by playing the planner through OpenCode on {F.train.windows} training windows whose
operating days stay clear of the benchmark's, and the model learned to make the same calls, with a short rationale at
each wake-up.

**The recipe**

<table>
<tr><td><b>Data</b></td><td>{F.train.windows} three-day training windows; {F.train.rows} rows, three a window; {F.train.kept} after the {F.train.cap}-token cap, about {F.train.tokens} tokens, {F.train.trained} of them trained</td></tr>
<tr><td><b>Model</b></td><td>{F.train.base_name}, LoRA r {F.train.rank} / α {F.train.alpha} on all linear layers</td></tr>
<tr><td><b>Training</b></td><td>TRL SFTTrainer, lr {F.train.lr}, {F.train.epochs} epoch, {F.train.steps} steps, gradient accumulation {F.train.accum}; activations offloaded to CPU, so rows up to {F.train.cap} tokens fit on one {F.train.mem} GiB GPU ({F.train.gpu_name}, {F.train.box} spot), in {F.train.hours} h</td></tr>
<tr><td><b>Eval</b></td><td>OpenCode with vLLM at a {F.train.ctx}-token context, the same harness for base and student</td></tr>
<tr><td><b>Cost</b></td><td>about {F.train.gpu} of GPU for training and the evals on our own servers; the teacher is our own planner, so no LLM API spend</td></tr>
<tr><td><b>Code</b></td><td><a href="{F.train.rows_code}">desk_distill_sft.py</a> and <a href="{F.train.code}">desk_distill_train.py</a>, and the <a href="{F.train.prereg}">pre-registration</a></td></tr>
<tr><td><b>Guide</b></td><td><a href="{F.links.training}">AgentEnv's training docs</a>: TRL, Unsloth, NeMo RL, prime-rl, verl and SkyRL on AgentEnv environments</td></tr>
</table>

<!-- train -->

- **Benchmark:** {F.train.gain} points over the base model [{F.train.lo}, {F.train.hi}], better on {F.train.better} of
  {F.train.n} windows. The fine-tuned 9B lands near the planner it copied ({F.train.sft} against {F.train.planner}), at
  {F.train.usd} a window.
- **Pre-registered primary test:** on {F.train.held} held-out training-period windows the gain was {F.train.hgain}
  points [{F.train.hlo}, {F.train.hhi}], not significant; the planner itself is only {F.train.hplan} points above base
  there.
- **The earlier attempt:** GRPO alone on {F.train.base_name}, {F.train.grpo} steps, did not move the score; imitating a
  strong policy moved it on the benchmark. What the model learned is the planner's habits: refused day-ahead offers
  fell from {F.train.refused} to {F.train.refusedSft}.

<small>One benchmark front, 8 to 10 May 2026, falls inside some training windows' spans, but only as their day-ahead
price history, the week before their operating days; no training transcript names those dates. Base
{F.train.base_name} was served by Fireworks on the benchmark and by our own vLLM on the held-out windows; the fine-tuned
model by our own vLLM on both.</small>

## Where models fail

We replayed every one of the {F.eval.runs} benchmark runs on the frozen engine and measured how each model ran the desk.
Three habits separate the top of the board from the bottom.

<!-- fail -->

## {F.beam.heading}

**How Beam was used.** {F.beam.provider}'s {F.beam.id} traded all {F.beam.n} benchmark windows as an autonomous agent
in {F.beam.harness} at {F.beam.setting}, served by {F.beam.server} through Hugging Face Inference Providers, on
agentenv-framework {F.beam.framework}, with {F.eval.calls} calls a wake-up and at most {F.eval.turns} wake-ups a window.
Each run covers {F.beam.days} operating days of the desk on ERCOT's records, with about {F.beam.wakes} wake-ups,
through the same {F.tryit.tools} desk tools over MCP as every other model, and no hand-holding.

**Result.** C {F.eval.m.beam.C} {F.eval.m.beam.ci}, at {F.eval.m.beam.usd} a window at {F.beam.seller}'s list price.
The real operator's bids, replayed, reach {F.beam.operator}, and the desk's planner {F.beam.planner}.

**Diagnosis.** We replayed all {F.beam.n} of Beam's runs exactly, every P to the cent, on the frozen desk, then changed
one thing at a time and graded each window again. Differences are in points of C, with 95% intervals.

- **Beam is faithful.** {F.beam.copied} of the day-ahead curve hours it submits against a planner proposal are exact
  copies of the proposal it had just received.
- **It asks the wrong question.** {F.beam.physical} of its `optimize` calls leave `dam_position` at the default,
  `{F.beam.default}`, which caps day-ahead curves at the planned dispatch. Asking the planner's question instead,
  `{F.beam.position}` at risk {F.beam.risk}, adds {F.beam.question} {F.beam.question_ci}. This leans on {F.beam.storm}:
  without that front's {F.beam.storm_n} windows it is {F.beam.calm} {F.beam.calm_ci}.
- **It stops re-planning.** Its last accepted offer comes {F.beam.late} hours before the window ends, on average.
  Letting the planner fill the wake-ups it ended without a submit adds {F.beam.replan} {F.beam.replan_ci}.
- **Both fixed:** {F.beam.both} {F.beam.both_ci}, {F.beam.share} of its {F.beam.gap}-point gap to the planner.
- AS offers left out, refused submits and its hand edits each move C by less than {F.beam.minor} points.

**What it means.** Beam reads the desk and follows the planner well. It lacks the desk's habits: a `{F.beam.position}`
position, and re-planning to the end of the window.

Watch Beam's runs in the [Replays Space]({F.beam.replay}), opening on the film's window; pick {F.beam.name} in the
article's [Where models fail]({F.beam.picker}) charts; or read [the diagnosis]({F.beam.report}) and its
[per-window files]({F.beam.files}).

### With the playbook

Those habits then went into a [playbook]({F.beam.pb.playbook}) for Beam: {F.beam.pb.lines} lines of general desk
practice, pre-registered and frozen before its first episode. Beam-1.0 ran all {F.beam.n} windows again with it, in the
same harness at the same settings, and reached C {F.beam.pb.C} {F.beam.pb.ci}, against its own {F.eval.m.beam.C}
{F.eval.m.beam.ci} and the planner's {F.beam.planner}. The replay put both fixes at {F.beam.both} points; Beam's own
play with the playbook recovered {F.beam.pb.all.d}.

| Windows | Beam + playbook − Beam, points of C | Windows ahead | Fronts ahead |
|---|---|---|---|
| All {F.beam.pb.all.n} | {F.beam.pb.all.d} {F.beam.pb.all.ci} | {F.beam.pb.all.ahead} of {F.beam.pb.all.n} | {F.beam.pb.all.fronts_ahead} of {F.beam.pb.all.fronts} |
| {F.eval.halves.post} ({F.beam.pb.jul_aug.n}) | {F.beam.pb.jul_aug.d} {F.beam.pb.jul_aug.ci} | {F.beam.pb.jul_aug.ahead} of {F.beam.pb.jul_aug.n} | {F.beam.pb.jul_aug.fronts_ahead} of {F.beam.pb.jul_aug.fronts} |
| Outside {F.beam.pb.storm} ({F.beam.pb.calm.n}) | {F.beam.pb.calm.d} {F.beam.pb.calm.ci} | {F.beam.pb.calm.ahead} of {F.beam.pb.calm.n} | {F.beam.pb.calm.fronts_ahead} of {F.beam.pb.calm.fronts} |

Outside {F.beam.pb.storm}'s front the interval includes zero.

<!-- beam-move -->

It changed how Beam ran the desk: {F.beam.pb.spread} of its {F.beam.pb.calls} answered `optimize` calls asked for
`{F.beam.position}`, against {F.beam.pb.spread0} of {F.beam.pb.calls0} before, and its last accepted offer came
{F.beam.pb.late} hours before a window's end on average ({F.beam.pb.late_med} median), against {F.beam.pb.late0}
({F.beam.pb.late0_med}). A window cost {F.beam.pb.usd} against {F.beam.pb.usd0} at {F.beam.seller}'s list price, the
card's basis; metered at the Hugging Face router's price, {F.beam.pb.metered} against {F.beam.pb.metered0}.

**Read it with this caveat.** The playbook was written after seeing Beam's failures on these same windows. The run
shows that the diagnosed fixes carry over to Beam's own play; it is not performance on unseen windows, and Beam +
playbook is not a leaderboard entry. The [pre-registration]({F.beam.pb.prereg}) gives the design, the
[run record]({F.beam.pb.record}) what happened, and [the results]({F.beam.pb.results}) every number, beside the
[graded episodes]({F.beam.pb.files}).

## What's in this dataset

<!-- inside -->

## Data sources and licence

| Data | Source | Licence |
|---|---|---|
| Day-ahead and real-time prices, reserve prices, system lambda and demand curves | ERCOT public reports NP4-190-CD, NP6-905-CD, NP6-788-CD, NP4-188-CD, NP6-332-CD, NP6-331-CD, NP4-212-CD and NP6-323-CD | ERCOT Website User Agreement, section 5; not relicensed |
| Load, wind and solar, ERCOT's forecasts as issued, outages | ERCOT public reports NP6-345-CD, NP4-733-CD, NP4-738-CD, NP3-565-CD, NP4-742-CD, NP4-745-CD, NP3-233-CD and NP1-346-ER | ERCOT Website User Agreement, section 5 |
| Market and operations notices | ERCOT notices | ERCOT Website User Agreement, section 5 |
| The real operator's bids, awards and output; each battery's limits, round-trip efficiency and standby loss | ERCOT 60-day disclosures NP3-966-ER, NP3-965-ER and NP3-991-EX, and ERCOT's December 2025 CDR report | ERCOT Website User Agreement, section 5; only derived values are published |
| Weather alerts | NWS watches, warnings and advisories, through the Iowa Environmental Mesonet's VTEC archive | public domain (NWS) |
| Weather in the replays | ASOS observations, from the Iowa Environmental Mesonet, Iowa State University | public domain (NWS, FAA), credited as the IEM asks |
| Temperatures that located the fronts | NOAA HRRR model runs | public domain (NOAA) |
| Solar capacity behind the modelled PV | U.S. Energy Information Administration, Form EIA-860M | public domain |
| The desk's price forecast | desk-qr-v1, fitted in the plugin on ERCOT's posted prices and forecasts | Apache-2.0 code; ERCOT's terms for the data |
| The battery sites in 3D | procedural, built in code; three.js | CC0; MIT |
| The clearing, settlement, grader and environment, and the scripts that build this dataset | `gridsim_core` and the plugin | Apache-2.0 |

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

## Links

- **Article:** [huggingface.co/spaces/earakely-scale/GridSimEnv](https://huggingface.co/spaces/earakely-scale/GridSimEnv)
- **Playground:** [huggingface.co/spaces/earakely-scale/GridSimEnv-OpenEnv]({F.links.env})
- **Replays:** [huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv]({F.links.replays})
- **Results:** [every model on every window, in the Replays Space]({F.links.results})
- **Code:** [github.com/earakely-scale/agentenv-gridsim-plugin]({F.links.code})
- **Pre-registration:** [docs/prereg/v4-bench.md]({F.links.prereg})
- **Training guide:** [agentenvframework.com/docs/training]({F.links.training})

## More on the benchmark

<details>
<summary><b>The desk</b>: what the agent does, its eleven tools, how time moves and what a window settles</summary>

- **A real battery, ERCOT's own objects.** The agent is the battery trader at a qualified scheduling entity (QSE) for
  one real ERCOT energy storage resource at its own node, from 06:00 the day before to midnight on the operating day
  (three operating days in v4). It never moves a megawatt itself: it bids energy curves into the day-ahead market (DAM)
  before the 10:00 close, sends real-time (RT) curves from 18:00 and keeps its Current Operating Plan (COP), all
  checked against ERCOT's rules; ERCOT's clearing decides what the battery does every 5 minutes.
- **Time moves on its own.** The clock stands still while the agent works. It wakes at the market's milestones, at
  each notice, outage and reserve deployment at its real minute and at reminders it sets, and sees each price,
  forecast and report only once ERCOT posted it.
- **Against the real operator.** ERCOT discloses every resource's bids, awards and metered output 60 days later. Each
  task replays the real operator's own bids through the same clearing and settlement, and settles its actual awards and
  output the same way.

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
a 15-minute price two minutes after, each forecast vintage as issued and each notice at its minute.

**What P sums.** The statement's lines: DAM energy, RT imbalance at the node's 15-minute price, set-point deviation
charges, from v3 ancillary-service capacity and imbalance, and the modelled lines. The hindsight optimum may hold
DAM/RT spread positions; its variant with the DAM position tied to dispatch is reported beside it.

</details>

<details>
<summary><b>How the benchmark ran</b>: harnesses, settings, cost and reliability</summary>

<!-- how -->

</details>

<details>
<summary><b>Methods</b>: pre-registration, references and uncertainty</summary>

- **Pre-registered, then frozen.** The three versions (v2–v4) plus a price-impact check (v5) each had a
  pre-registration committed before the first scored episode
  ([v2](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v2-desk.md),
  [v3](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v3-desk.md),
  [v4](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v4-desk.md),
  [v5](https://github.com/earakely-scale/agentenv-gridsim-plugin/blob/main/docs/prereg/v5-desk.md)): the pack, the
  models and their settings, the references, what is reported and the prior. The code is frozen at a tag before any
  scored run (`desk-v2-freeze`, `desk-v3-freeze`, `desk-v4-freeze` and `desk-v5-freeze`). Nothing is rerun to improve
  a score, and anything done differently is logged as a deviation in the pre-registration.
- **Reviewed and piloted.** A review of the environment before v2's runs found two information-timing leaks, fixed
  before any scored episode. Each version is then piloted on one or two tasks before its eval; the pilots are
  mechanics checks, not results.
- **The benchmark** plays v4's desk, frozen at `desk-v4-freeze`, on 32 windows (v4's 16 and 16 from July and August
  2026, after every reported training cutoff) with each model in its own agent harness, under a pre-registration of its
  own. `scripts/desk_bench_results.py` scores a model's first attempt on a window that reached the grade, counts every
  attempt in the cost, and never imputes a window a model did not finish.
<!-- bench-rule -->
- **Every grade replayed.** `scripts/desk_report.py` re-grades every Episode JSON against frozen references, and each
  version's `summary.json` records the references used and every difference from the runner's own grade.
- **References on every task,** settled by the same clearing, physics and settlement code: idle; the planner (the
  anchor), the desk's own optimiser re-planning at every wake on the same information, its risk setting and DAM basis
  chosen blind on a separate tuning pack (`desk-v2-tune`); the hindsight optimum, and its variant with the DAM position
  tied to dispatch; the real operator's disclosed bids, replayed, and its actual awards and metered output, settled.
- **Uncertainty.** 95% CIs come from a block bootstrap over operating days (in v4, over the four weather fronts; in
  the benchmark, over its eight, four within each side of the cutoffs): 10,000 resamples, seed 0, task-weighted.
  Paired gaps resample the tasks both sides played.

</details>

<details>
<summary><b>Known limitations</b></summary>

<!-- limits -->

</details>

<details>
<summary><b>Deviations from the pre-registration</b>, one line each</summary>

<!-- deviations -->

</details>

<details>
<summary><b>Earlier versions</b>: v2 to v4 on the desk's own runner, and the v5 price-impact check</summary>

<!-- earlier -->

</details>

<details>
<summary><b>Run it yourself</b>: the desk in process, and a benchmark window with <code>agent-env run</code></summary>

<!-- quickstart -->

</details>

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
