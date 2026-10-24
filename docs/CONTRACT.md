# GridSimEnv v1 build contract

This is the shared contract for the v1 lanes (core + packs, plugin, viewer, runs, Hub). The design source is Linear FD-4319 / FD-4320 and its v1 sub-issues; this file fixes the interfaces so lanes can build in parallel. Change it only through the main session.

## Repository layout

One distribution, `agentenv-gridsim`, with two import packages:

```
pyproject.toml          hatchling; packages src/gridsim_core and src/agentenv_gridsim; data/ force-included
src/gridsim_core/       pure Python + numpy (highspy optional for the LP bound). The ONLY physics/grading code.
  contract.py task.py parse.py physics.py dp.py lp.py baselines.py grade.py trl.py episode.py prompt.py
src/agentenv_gridsim/   the AgentEnv plugin (copies agentenv-portsim's layout and house style)
  server.py tasks.py sweep.py episodes.py view.py record.py cli.py bundles/ web/
agents/gridsim-llm/     fork of agentenv-portsim's portsim-llm
data/ercot-dam-v1-*/    tasks.jsonl.gz + manifest.json per pack; data/fixtures/ (20 tasks for CI)
scripts/                build_pack.py (one command from cache/raw to data/), hub_dataset.py, hub_space.py
cache/                  gitignored: raw ERCOT zips (cache/raw/ercot/DAMLZHBSPP_YYYY.zip, 2014-2026 downloaded), EIA-860, IEM weather
hub/dataset hub/space   Hub cards and Space build
results/                eval-v1.json, board.md, runs (Episode JSON) for the Space
tests/                  pytest (+ hypothesis) on committed fixtures; nothing skips at import
docs/                   this contract, prereg/v1-board.md, notes
```

Style: the agent-env house style (terse code, no comments beyond short docstrings, ruff line length 120, py3.11+, never `git add -A`, commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`).

## Decisions taken for v1 tonight (recorded on Linear for Edgar)

- **Points**: the 7 HB_* hubs and 8 LZ_* load zones in NP4-180-ER (report 13060), yearly files 2014-2026. HB_HUBAVG and HB_BUSAVG stay in the pool and are removed by the within-date dedup when they duplicate a component.
- **Grid**: one SoC unit is q MWh; k_dis, k_ch in 2..4 (some asymmetric); N = E/q <= 16; `q_15 = q/4` is stored in every task.
- **p_floor** = $50/MWh for the shortfall buy-back.
- **Blind tier** situation carries D-1 [24] and D-7..D-1 [7x24]; no history tool.
- **submit_schedule** returns profit and feasibility only; the reward and references come from `data/get` after done.
- **Model for runs**: `openai/gpt-6.1-sol` only, reasoning effort high (Edgar, 2026-10-23: Sol only until a version is final).
- **Viewer**: a real-life 3D scene (Three.js) of a battery yard at the point's region in that day's light and weather, with a plain-English card and the expert charts behind a toggle. This replaces the 8-bit pixel engine in FD-4334, per Edgar's standing direction that sim viewers look like real life (the 8-bit engine stays possible as a later race/LEVEL UP reel).
- **Hub repos** are created private for Edgar's review; GitHub repo is private until Edgar flips it.

## Battery and physics (exact)

Battery fields (all in the task row, key `battery`):

```
{"archetype":"2h-c","source":"archetype","p_dis_mw":100,"p_ch_mw":100,"energy_mwh":200,
 "unit_mwh":25,"q_15":6.25,"k_dis":4,"k_ch":4,"soc_levels":8,"eta":0.85,"c_deg":4.0,
 "cycle_cap_units":12,"s0":4,"s_end_min":4}
```

Actions: 24 integers for HE01..HE24 (hour ending, Central Prevailing Time). `a > 0` discharges (sells) `a` units; `a < 0` charges (buys) `|a|` units.

- Rate: `-k_ch <= a_h <= k_dis` (violation `rate`).
- SoC: `s_h = s_{h-1} - a_h`, `0 <= s_h <= N` (violations `soc_below_0`, `soc_above_N`).
- Cycle cap: running `sum max(a,0) <= cycle_cap_units` (violation `cycle_cap`).
- Energy: selling `a` units delivers `a*q` MWh; buying `|a|` units draws `|a|*q/eta` MWh (losses on the buy side).
- Cash: `pi_h = p_h * g_h - c_deg * q * max(a_h, 0)`, with `g_h = q*a_h` if `a_h > 0` else `q*a_h/eta`.
- Truncation: at the first hour that breaks a rule, that hour and every later hour execute as 0. The prefix settles.
- End obligation: shortfall `u = max(0, s_end_min - s_24)`; penalty `u * q / eta * max(max_h p_h, p_floor)`.
- Profit `P = sum pi_h - penalty`. Idle (all zeros) may pay a penalty when `s_end_min > s0` (15% of tasks).
- Parsing: a JSON list or a comma/whitespace-separated string of exactly 24 integers. Anything else is not a submission (ParseError). Out-of-range integers parse and then truncate.

## Reward (one contract)

`R = clip(0.2 + 0.8 * (P - P_idle) / (P_anchor - P_idle), 0, 1)`, rounded to 6 decimals; no valid submit -> 0; no format credit.

- foresight: anchor = P_opt (exact DP).
- blind: anchor = max(P_persist, P_ridge) (DP on predicted prices, settled on the real day); `r_opt` uses P_opt and is the blind headline; also report `beats_anchor`.
- Hindsight capture `r_opt` is a weight-0 row everywhere.
- Degenerate anchor (P_anchor - P_idle <= 1e-9) never reaches a pack (filtered).

## gridsim_core API (what every lane imports)

```python
from gridsim_core import CONTRACT_VERSION                       # "1.0"
from gridsim_core.parse import parse_actions, ParseError        # (list|str) -> list[int] (len 24)
from gridsim_core.physics import simulate                       # (task, actions, prices=None) -> Sim dict
from gridsim_core.dp import solve_dp                            # (task, prices=None) -> (profit, schedule[24])
from gridsim_core.lp import lp_bound                            # (task) -> float | None (None if highspy missing)
from gridsim_core.baselines import idle, clock, threshold, greedy, random_feasible, persistence_dp, ridge_dp
from gridsim_core.grade import grade                            # (task, actions, tier="foresight") -> Grade dict
from gridsim_core.prompt import system_prompt, situation       # the exact text/JSON the agent sees (path A == path B)
from gridsim_core.trl import reward_fn                          # TRL reward_funcs entry
from gridsim_core.episode import to_episode_json                # -> gridsim.episode/v1 dict
```

`simulate` returns `{feasible, truncated_at (0-based hour or None), violation, executed[24], soc_path[25], cashflow[24], mwh[24], degradation_usd, end_shortfall_units, penalty_usd, profit_usd}`.

`grade` returns `{submitted, reward, r_opt, profit, profit_idle, profit_anchor, profit_opt, feasible, truncated_at, violation, end_shortfall_units, beats_anchor (blind) }`. For an unparseable submission: `{submitted: false, reward: 0, error}`.

The DP is exact over s in 0..N, d (discharge units used) in 0..cycle_cap_units, a in -k_ch..k_dis; the terminal value applies the same shortfall penalty; ties break toward smaller |a| then lexicographically, deterministically.

## Task row (packs: data/<pack>/tasks.jsonl.gz, one JSON per line)

```
{"task_id":"dam-v1-2024-07-18-HB_WEST-2h-c","contract_version":"1.0","pack":"ercot-dam-v1-eval","split":"eval_2025",
 "date":"2024-07-18","settlement_point":"HB_WEST","point_kind":"hub","region":"west",
 "prices":[24 floats],"blind":{"dam_prev_day":[24],"dam_prev_7d":[[24],...7]} | null,
 "battery":{...},
 "refs":{"foresight":{"p_idle":..,"p_opt":..,"opt":[24],"p_lp":..|null,
                      "baselines":{"clock":{"profit":..,"reward":..,"schedule":[24]},"threshold":{..},"greedy":{..},"random":{..}}},
         "blind":{"p_persist":..,"persist":[24],"p_ridge":..,"ridge":[24],"p_anchor":..,"r_opt_anchor":..} | null},
 "difficulty":0.21,"curriculum":"C0|C1|C2","tags":{"neg_hours":0,"spike":false,"season":"summer","binding":"cycle_cap|end_soc|rate|none"}}
```

Task ids: `dam-v1-{date}-{point}-{arch}`; the tier is NOT in the id (it is the load-task config). `region` maps the point to a viewer backdrop: west (HB_WEST, LZ_WEST), panhandle (HB_PAN), north (HB_NORTH, LZ_NORTH, LZ_RAYBN), houston (HB_HOUSTON, LZ_HOUSTON), south (HB_SOUTH, LZ_SOUTH, LZ_CPS), central (LZ_AEN, LZ_LCRA, HB_BUSAVG, HB_HUBAVG).

Packs (sizes are targets; build_pack.py records the actual counts in the manifest):
- `ercot-dam-v1-train`: 2014-2024 minus reserved/showcase dates, ~20k foresight (+ blind inputs on ~6k).
- `ercot-dam-v1-eval`: 2025-01-01..2025-11-30, 500 foresight + 300 blind (stratified by point x archetype x month).
- `ercot-dam-v1-eval-iid`: every 10th calendar date 2014-2024, 500.
- `ercot-dam-v1-rtcb`: 2025-12-05..2026-10-17 (in-year file), 250.
- `showcase`: Uri 2021-02-10..22, Elliott 2022-12-22..24, 2023-08, 2023-09-06, Heather 2024-01-13..17 (display only).
- `data/fixtures/`: 20 tasks (mixed tiers/archetypes, incl. a max-price<=0 day and an s_end_min>s0 day) for CI.

Filters: drop DST-transition days and any day without exactly 24 hourly values; within-date dedup (corr > 0.999 and max abs diff < $1); low-spread drop when `(P_opt - P_idle) < $22 per MW of p_dis` (tuned: $8 dropped only 3%); drop 80% of tasks where greedy >= 0.97; tune so greedy mean sits ~0.75-0.80 and ~15% drop as low-spread; commit the tuning table in `data/stats.md`.

## Tools (env `gridsim`, server env, no gateway)

- `get_situation()` -> the situation JSON (free).
- `check_schedule(actions)` -> `{feasible, truncated_at, violation, soc_path, end_shortfall_units, profit_usd, checks_left}`; max 3; never a reward or reference. In the blind tier `profit_usd` is null (it would reveal the hidden prices); use `gridsim_core.episode.check_result(..., tier)`.
- `submit_schedule(actions)` -> `{submitted, feasible, truncated_at, violation, soc_path, profit_usd}`; ends the episode. Unparseable -> `{submitted:false, error}` and uses a call.
- Caps: 24 calls, 3 checks, 4 turns; calls after done error.
- Harness: `apply_server_config urn:gridsim:load-task/v1 {task_id, tier, checks}`; `data/get` -> `{task_id, tier, checks_used, calls_used, done, end_reason, schedule, grade, reward}` (grade/reward only after done); `data/reset`.

## Episode JSON `gridsim.episode/v1` (path A sweeps and path B training write the same shape)

```
{"schema":"gridsim.episode/v1","episode_id":"...","env":"gridsim","version":"v1","task_id":"...","tier":"foresight|blind",
 "bundle":"full|oneshot|train|reference","path":"A|B|ref","model":"openai/gpt-6.1-sol","trained":"base|grpo|sft|null",
 "checkpoint_step":null,"seed":null,
 "situation":{...},                       # exactly what the agent saw
 "task":{date, settlement_point, point_kind, region, battery, prices, blind},
 "steps":[{"t":0,"tool":"check_schedule","args":{...as sent},"output":{...}}, ...],
 "final_schedule":[24],"soc_path":[25],
 "hourly":[{"he":1,"price":..,"action":..,"mwh":..,"cash":..,"degradation":..,"soc":..}],
 "truncated_at":null,"violation":null,"end_shortfall_units":0,"profit_usd":..,"reward":..,"r_opt":..,
 "references":{"p_opt":..,"p_idle":..,"p_lp":..,"opt":[24],"greedy":{..},"threshold":{..},"clock":{..},"blind":{..}|null},
 "messages":[{"role":"assistant","content":"..."}],   # optional excerpt for the viewer's text card
 "usage":{"input_tokens":..,"output_tokens":..,"usd":..},"wall_seconds":..}
```

The viewer only reads Episode JSON plus optional sidecars (`weather` hourly for the point's representative airport from IEM ASOS, keyed by date+point). Every episode is re-verified through gridsim_core before it is shown or published.

## Runs

GPT-6.1 Sol (`openai/gpt-6.1-sol`, effort high) on cloud VMs (agent-environments-admin). The LiteLLM key is read from SSM `/gridsim/litellm-key`; it is never printed, committed or written to task JSON. Board columns: A full/foresight on eval (500), B oneshot/foresight (500), C full/blind (300). Pre-registration is committed in `docs/prereg/v1-board.md` before the first episode.
