# GridSimEnv v2 "The Live Grid" build contract

The v2 interface every lane builds against: `gridsim_core.live` (core, lane L), the `gridsim-live` gateway env (lane E, a
port of PortSim's `portsim-live`), the notice archive (lane N) and path B' training. Design source: Linear FD-4321 (v2
plan) and FD-4319 (shared rules); the v1 contract (`docs/CONTRACT.md`) still holds for everything not restated here.
Nothing in v1 changes: v2 is new modules only (`gridsim_core.live`, `gridsim_core.live_prompt`,
`scripts/build_live_pack.py`, `data/gridsim-live-*`, `data/fixtures-live/`).

`gridsim_core.live.Session` holds the only v2 state machine. The env server imports it and only wraps it (clock PUTs,
MCP plumbing); path B' imports the same class. Tool outputs are produced by core as exact strings, so path A and path B'
are byte-identical by construction.

## Decisions (all provisional until Edgar confirms)

FD-4321's recommendations, taken as written:

| # | Decision | Taken (provisional) |
|---|---|---|
| V2-D1 | Anchor family | The notice-blind decayed-basis rolling DP (below). Revisit after the pilot sweep only if it saturates or sits near naive |
| V2-D2 | Training stretch reward | Training only: above the anchor r = 1 + 0.2·(P − P_roll)/(P_hind − P_roll), capped at 1.2. Never on the card (`grade()["stretch_reward"]`) |
| V2-D3 | Hard DA tier | `blind`: the DA position is chosen from D-1 and D-7..D-1 DAM only; D's DA prices appear at the 00:00 watch. No bid10 |
| V2-D4 | Notice text on the Hub | Not decided here; core carries the text it is given (trimmed to 600 chars). Packs ship notices only after Edgar decides |
| V2-D5 | Eligibility vs naive's score | Measure naive's mean R; if it is above 0.7, raise the "anchor beats naive" threshold from 5% toward 15% of headroom (recorded in `data/live-stats.md`), never move the floor |
| V2-D6 | Uri | Display-only (showcase), out of every split, with the other showcase days ±3 days |
| V2-D7 | Asset derates | The excuse path is built and tested on CI fixtures; no derate bulletins ship |
| V2-D8 | Turn budget | 52 turns for every task (`live.MAX_TURNS`) |
| V2-D9 | SCED ticker | Not in core; optional and display-only |

Lane decisions where FD-4321 is silent or self-contradictory (also provisional):

| # | Decision |
|---|---|
| L-D1 | **DA MWh carry v1's buy-side losses.** A DA buy of d units books d·unit·4/η MWh, exactly what a physical schedule that follows the position draws, so following the DA position has zero RT deviation and P_naive equals v1's P_opt on the same hourly battery. (FD-4321's formula writes d_h·P/4 for both signs.) |
| L-D2 | **The physical schedule follows the DA position until the first accepted `commit_schedule`.** An accepted `commit_da` sets the physical schedule to the position expanded ×4 if no schedule was committed yet (a COP that follows the DA award). With no commit at all the battery idles. |
| L-D3 | **End target is a commit rule.** `commit_da` and `commit_schedule` refuse a schedule ending below `s_end_min` ("end_target"). The shortfall penalty still applies to idle and to derate-clipped execution. P_hind and P_roll use the same hard end target. |
| L-D4 | **Watch merging** keeps the reveal rule: notice watches that would share a freeze line (same `ceil_to_hour(reveal_at)`) merge into one watch at the latest of their reveal times; a class whose freeze line equals a regular watch's is absorbed by that watch; a class whose freeze line is at or after D 24:00 makes no watch. At most 10 watches; over the cap the classes holding the most urgent notices keep their watches (EEA, Emergency and derates; conservation appeals; Watches and EEA exits; Advisories; OCNs; NWS warnings, watches, advisories; cancellations last; then the earliest), and the rest merge into the next watch at or after their reveal time. A notice with no watch at or after its reveal time is `after_day` and never delivered. |
| L-D5 | **`short` tier** = regular watches D-1 14:00, D 00:00 and D 12:00 plus notice watches; a task is short-eligible when that gives ≤ 4 watches (`tags.short_ok`). |
| L-D6 | **Batteries** are v1's archetype letters re-gridded to k_dis = 4: same P, E/P, η, c_deg, cycles; k_ch = 4 when v1's k_ch ≥ k_dis, else 3; s0 and s_end_min keep their fraction of N. One live unit is P/16 MWh. (Core accepts any v1 battery: the live unit is always v1's `q_15` = unit_mwh/4.) |
| L-D7 | **Every planning-tool call uses a planning call while calls remain**, refused or malformed ones included; a call made with none left, or after the day, is an error that uses none. |
| L-D8 | `blind` anchor = max over the persistence and ridge DA predictors of the rolling re-planner (mirrors v1's blind anchor). |
| L-D9 | **Notice days skip the anchor-beats-naive eligibility criterion** (divergence and headroom still apply). They are the X6 days, judged by beat-anchor rate and (P − P_roll)/(P_hind − P_idle); with the criterion only a handful of 2024 notice days survive. Naive's R is reported separately for notice and quiet tasks. |
| L-D10 | **Notices in packs** come from lane N's archive (`gridsim_core.notices.notices_for`): ERCOT grid-condition rows (cancellations included) and the region's NWS warnings and watches for load-moving phenomena plus heat advisories. The payload is lane N's paraphrased `summary` (NWS: a generated one-line summary), ids, times and levels, never the verbatim text (V2-D4). A day is `notice` (`notices.is_notice_day`), `quiet` (archive coverage 1.0 and no notice) or `unknown` (an archive gap). |

## Clock, grid and battery

- Times are Central Prevailing Time (CPT). Day D is never a DST day (DST days are dropped from packs), so D-1 14:00 to
  D 24:00 has one UTC offset. Core counts time in **minutes from D 00:00**: watch 0 is −600, D 24:00 is 1440.
  Strings shown to the agent are local `"YYYY-MM-DD HH:MM"`; the gateway clock gets UTC `"YYYY-MM-DDTHH:MM:SSZ"`
  (`Session.watch_time_utc(k)`).
- **Intervals**: t = 0..95, interval t covers [15t, 15t + 15) minutes of D, label `"HH:MM"` of its start. RT SPP_t is
  revealed when the interval ends (minute 15t + 15). Hour h = 0..23 (HE01..HE24) holds intervals 4h..4h+3.
- **Freeze line** at time m: `ceil_to_interval(m, 60) + 60` minutes (ceil_to_hour(now) + 1 h; `freeze6h` tier: + 360).
  An interval is *executed* when it has ended, *frozen* when it has not started but starts before the freeze line,
  *open* when it starts at or after the freeze line. Only open intervals can change.
- **Live grid** (what the agent sees as `battery`): from the task's hourly v1 battery (unit q, k_dis, k_ch, N, cap, s0,
  s_end_min): `unit_mwh` = q/4 (= P/16 for k = 4), `k_dis`, `k_ch` (per 15-minute interval), `soc_levels` = 4N,
  `cycle_cap_units` = 4·cap, `s0` = 4·s0, `s_end_min` = 4·s_end_min, η and c_deg unchanged.
- **Physics per interval** (v1's rules on the live grid): a_t ∈ [−k_ch, k_dis] (derates lower these), SoC s_{t+1} =
  s_t − a_t within [0, soc_levels], discharged units Σ max(a, 0) ≤ cycle_cap_units, end SoC ≥ s_end_min. Grid MWh
  g_t = unit·a_t when a_t > 0, unit·a_t/η when a_t < 0 (losses on the buy side). Degradation c_deg·unit·max(a_t, 0).
- **Expansion**: an hourly list (`step: "1h"`, and every DA position) means the same action in each of the hour's four
  intervals. This is exact: an hourly v1 action a on the hourly battery equals (a, a, a, a) on the live grid in SoC,
  cycles, MWh, cash and degradation.

## Watches, notices and the reveal rule

- **Regular watches**: watch 0 at D-1 14:00 (−600), then D 00:00, 06:00, 12:00, 18:00 (`short`: −600, 0, 720).
- **Notices** (input to the Session; lane N's records are mapped to this shape by the pack merge step):

```
{"event_id": "ercot-M-A090623-02", "source": "ERCOT|NWS|asset", "kind": "eea|conservation|watch|advisory|ocn|weather|derate|other",
 "level": "EEA2|Emergency|Watch|Advisory|OCN|Warning|...|null", "issued_at": "2023-09-06T19:25:00-05:00",
 "name": "ERCOT", "title": "short summary line", "text": "trimmed to 600 chars",
 "derate_mw": null, "from": null, "until": null, "action": "issue|cancel|end|null"}
```

  `issued_at` is ISO 8601 with an offset (or Z). `reveal_at = ceil_to_interval(issued_at, 15)`. A notice with
  `reveal_at` ≤ D-1 14:00 is on the **watch-0 board** (delivered at load, shown in `notices`, not in `messages`); with
  reveal_at ≤ D 00:00 it is delivered at the 00:00 watch; otherwise it gets a notice watch per L-D4. Each notice is
  delivered at the first watch ≥ its reveal_at, never earlier; a watch's notices are delivered in (reveal_at,
  issued_at, event_id) order. `derate_mw`, `from`, `until` (ISO times) make an asset derate: during [from, until) the
  per-interval limits become `floor(k·(P − derate_mw)/P)` for discharge and charge (never below 0).
- `live.schedule(task, tier, notices) -> list[Watch]`; `Watch(index, minute, time, time_utc, freeze_line, notices)`;
  `live.triggers(watches)` returns the PortSim-shaped trigger list for watches 1..N−1:
  `{"id": "watch-k", "when": {"type": "action", "tool": "advance", "where": {"result.watch": {"equals": k}}},
  "barrier": {"at": "provoking_call", "timeout_seconds": 60}, "actions": [{"type": "tool", "tool": "grid_notice",
  "args": {"event_id", "name", "text", "level", "derate_mw", "from", "until"}}, ...]}`.

## Settlement (ERCOT two-settlement, price-taking ESR)

With d_h the DA position (24 ints on the live grid's per-interval scale), m_h = 4·g(d_h) its DA MWh, a_t the executed
action and g_t its grid MWh:

```
P = Σ_h DA_h·m_h  +  Σ_t RT_t·(g_t − m_h(t)/4)  −  Σ_t c_deg·unit·max(a_t, 0)  −  shortfall_penalty  +  excused_usd
shortfall_penalty = max(0, s_end_min − s_96) · unit/η · max(max_h DA_h, P_FLOOR)     (P_FLOOR = $50/MWh)
```

Per interval the settled cash is `da_usd = DA_h·m_h/4`, `rt_usd = RT_t·(g_t − m_h/4)`, `deg_usd`; the P&L split is
`{da_usd, rt_deviation_usd, degradation_usd, shortfall_usd, excused_usd, total_usd}` over the intervals settled so far
(shortfall at the end). The DA position is financial only: SoC follows a_t alone. Prices are as published (negative
and administrative prices included). Money in tool outputs is rounded to cents; grades to 6 decimals.

**Execution and excuses.** An interval executes its committed action clipped to what the battery can do then (rate
limits including derates, SoC bounds, cycle cap). Without derates every committed schedule is feasible, so nothing is
ever clipped. When a derate is delivered, frozen intervals inside its window are clipped at once (the schedule records
the clipped action); for each, `excused_usd += max(0, cash_RT(committed) − cash_RT(clipped))`, and end-shortfall units
up to the charge units removed this way are excused at the shortfall price. Clipping in open intervals is never
excused (the agent can re-plan them), nor is any market outcome.

## gridsim_core.live API

```python
from gridsim_core.live import (Session, schedule, triggers, references, replay, play, naive_policy, roll_policy,
                               LIVE_VERSION, TOOLS, NOTICE_TOOL, LIVE_LOAD_URI, END_DAY_URI, CLOCK_URI, MAX_TURNS,
                               PLANNING_CALLS, TIERS, expand, freeze_line)
s = Session(task, tier="foresight", notices=None)   # notices None -> task["notices"]; tiers: foresight|blind|short|freeze6h
s.call(tool, args) -> str        # the exact tool output string (json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
s.situation() / s.commit_da(position) / s.check_schedule(actions, start, step="15m") / s.commit_schedule(actions, start, step="15m")
s.advance() / s.notice(event_id, name, text, level=None, derate_mw=None, start=None, until=None, via="trigger")
s.deliver_watch_notices(via="trigger")   # path B' and tests: what the gateway triggers do after each advance
s.end_day() -> dict / s.grade() -> dict / s.audit(get_time_reads=None) -> {"ok", "problems"} / s.data() -> dict
s.watches, s.watch, s.done, s.transcript, s.watch_time_utc(k)
s.episode(**meta) -> gridsim.episode/v2 dict
replay(task, tier, notices, transcript) -> {"ok", "problems"}     # byte-identical re-run of a recorded transcript
references(task, tier, notices=None, ridge=None) -> refs dict      # computed on the true day; never shown to the agent
```

The methods return dicts; `call` adds `"messages"` (the notices delivered since the agent's last call, drained) to
every agent tool's output and serialises it. `s.transcript` records every `call` (agent tools and `grid_notice`) as
`{"tool", "args", "output"}`; `replay` re-runs it and compares strings.

## Tools (agent role `default`; outputs are the dicts below plus `"messages"`)

Errors return `{"error": "...", "planning_calls_left": n}` and change nothing: a planning tool after the day or with
no calls left uses no call; a planning tool with a missing or unexpected argument uses one (L-D7). Refusals (`accepted:
false`, `feasible: false`) use one.

- `get_situation()` (free; answers after the day too):

```
{"task_id","tier","date","settlement_point","point_kind","market":"ERCOT two-settlement: DAM + 15-minute real time",
 "watch": k, "time": "2023-09-06 06:00", "freeze_line": "2023-09-06 07:00", "first_open_interval": 28,
 "planning_calls_left": 3, "day_over": false,
 "battery": {"p_dis_mw","p_ch_mw","energy_mwh","unit_mwh","k_dis","k_ch","soc_levels","eta","c_deg","cycle_cap_units","s0","s_end_min"},
 "limits": [{"from":"HH:MM","until":"HH:MM","k_dis","k_ch","event_id"}],
 "soc_units": s, "discharge_units_used": d, "cycle_units_left": cap − d,
 "da_prices_usd_per_mwh": [24] | null,                  # blind: null before the 00:00 watch
 "dam_prev_day_usd_per_mwh": [24], "dam_prev_7d_usd_per_mwh": [[24] x 7],   # blind only
 "da_position": [24] | null, "da_value_usd": x | null,
 "rt_prices_usd_per_mwh": [n],                          # the n settled intervals from 00:00, never more
 "schedule": [96], "schedule_status": "EEEE…FFFF…OOOO",  # E executed, F frozen, O open
 "projected_end_soc_units": s96,
 "pnl": {"da_usd","rt_deviation_usd","degradation_usd","shortfall_usd","excused_usd","total_usd"},
 "notices": [{"event_id","source","level","time","name","title","text"}],
 "result": {...} }                                       # only after the day: as advance's done result
```

- `commit_da(position)`: 24 ints (list, or a comma/space-separated string). Watch 0 only; accepted once. Rules: rate,
  SoC, cycle cap and end target on the expanded position from s0 (L-D3). Uses a planning call.
  `{"accepted": true, "refusals": [], "da_value_usd": x | null, "schedule_follows_da": bool, "planning_calls_left": n}`;
  refused: `{"accepted": false, "refusals": [{"hour": "HE05", "reason": r}], "planning_calls_left": n}` (the first
  failing hour; reasons `rate|soc_below_0|soc_above_max|cycle_cap|end_target|parse`). With no accepted DA position the
  position is all zeros (pure RT).
- `check_schedule(actions, start, step="15m")`: `start` "HH:MM" on D (on the hour for `1h`); `actions` covers start to
  24:00 (96 − start/15 ints for `15m`, 24 − start/60 for `1h`). The candidate day is the current schedule before
  `start` and `actions` from `start`. Uses a planning call.

```
{"feasible": bool, "refusals": [{"interval": i, "time": "HH:MM", "reason": r}],
 "projected": {"soc_path": [97], "end_soc_units", "pnl_at_da_prices_usd": x | null, "discharge_units": d},
 "excused_usd": x, "planning_calls_left": n}
```

  Refusals: every interval before the freeze line whose action differs from the schedule (`frozen`), then the first
  physics failure (`rate|soc_below_0|soc_above_max|cycle_cap`), then `end_target` at interval 95; a malformed call gives
  one `{"interval": null, "reason": "parse: ..."}`. `soc_path` follows the candidate with v1 truncation (the first
  failing interval and every later one idle). `pnl_at_da_prices_usd` is the day's projected total with settled
  intervals at their RT prices and the rest at DA prices (null while DA prices are hidden).
- `commit_schedule(actions, start, step="15m")`: the same candidate and refusals; all-or-nothing. Uses a planning call.
  `{"accepted": bool, "refusals": [...], "schedule_status": {"executed","frozen","open","freeze_line","end_soc_units",
  "discharge_units"}, "planning_calls_left": n}`.
- `advance()` (free): runs the schedule to the next watch, settles every interval that ends by then, and opens the
  watch (3 fresh planning calls; unused ones do not carry over).
  `{"watch": k, "time", "freeze_line", "first_open_interval", "settled": [{"interval", "time", "rt_spp", "q_units",
  "da_units", "usd"}], "soc_units", "pnl": {...}, "planning_calls_left": 3}`. From the last watch it runs to 24:00 and
  ends the day: `{"done": true, "time", "settled", "soc_units", "pnl", "feasible", "profit_usd", "reward",
  "capture_vs_hindsight"}` (no `watch` key, so no trigger matches). `usd` is the interval's da_usd + rt_usd − deg_usd.
  The watch's bulletins arrive in `messages` of the next tool result.
- Harness only (hidden from `default`): `grid_notice(event_id, name, text, level?, derate_mw?, from?, until?)` →
  `{"applied": event_id, "watch": k}`; `urn:gridsim:live-load/v1 {task_id, tier}` → `{"task_id", "tier", "watches": n}`
  (one load per env, as PortSim); `urn:gridsim:end-day/v1` → `s.end_day()` = `{"end_reason", "watch", "feasible",
  "profit_usd", "reward", "audit"}`; `urn:agentenv:clock/v1 sync_time`; `data/get` → `s.data()`; `data/reset`.
- `data()`: `{"task_id","tier","watches","watch","time","done","end_reason","calls_used","planning_calls":[per watch],
  "da_position","schedule","executed","schedule_status","notices":[log rows],"frozen":[{watch,time,freeze_line,
  first_open_interval,call}],"refusals":[...],"excused":{"usd","rows"},"settled":n,"audit","grade","reward"}`; never a
  reference plan or value before the day ends.
- `calls_used` counts every agent tool call through the Session (failed ones included); `grid_notice` is not counted.
  Constants: `PLANNING_CALLS = 3`, `TURNS_PER_WATCH = 5`, `MAX_WATCHES = 10`, `MAX_TURNS = 52`, `BARRIER_SECONDS = 60`.

## References and reward (`references()`; stored in the task row, never shown to the agent)

- **P_idle**: DA position zeros, schedule zeros (may pay the end shortfall when s_end_min > s0).
- **P_naive**: v1's foresight DP plan on D's DA prices (hard end target) as DA position and physical schedule, never
  re-planned (card baseline; the same for every tier). Equals v1's `solve_dp` profit on the hourly battery.
- **P_roll** (the anchor, notice-blind rolling re-planner), played through a `Session` with the agent's freeze, budget
  and DA rule: at watch 0 it commits the DA position (foresight: the naive DA position; blind: the DP plan on the
  persistence or ridge DA prediction, the better of the two runs, L-D8), then at every watch re-solves the exact DP over
  open intervals from the state at the freeze line (frozen intervals pinned, derate limits respected, hard end target)
  on the forecast f_t = DA_h(t) + b·0.5^((start_t − now)/120 min), b = mean(RT − DA) over the last 4 settled intervals
  (0 before any settle; the predicted DA replaces DA_h while DA is hidden), and commits it when it differs. It ignores
  notice text.
- **P_hind** (weight 0): exact, two separable DPs: the best DA position on the hourly spread DA_h − mean_{t∈h} RT_t
  (v1 DP on the hourly battery, c_deg 0, hard end) plus the best physical schedule on the 96 RT prices (live-grid DP,
  hard end). `p_lp` is the joint LP relaxation (HiGHS), an upper bound checked in tests.
- **Reward**: no accepted commit (`commit_da` or `commit_schedule`) → 0; otherwise `R = clip(0.2 + 0.8·(P − P_idle)/(P_roll
  − P_idle), 0, 1)` rounded to 6 decimals (v1's `reward_value`). Weight-0 rows: `capture_vs_hindsight = (P −
  P_idle)/(P_hind − P_idle)`, `beats_anchor`, `regret_usd = P_hind − P`, `regret_usd_per_mw`, `naive_reward`,
  `excused_usd`. Training only: `stretch_reward` (V2-D2).
- `grade()` → `{"submitted", "reward", "profit_usd", "pnl", "p_idle", "p_naive", "p_roll", "p_hind", "capture_vs_hindsight",
  "beats_anchor", "regret_usd", "regret_usd_per_mw", "naive_reward", "stretch_reward", "excused_usd", "feasible",
  "end_shortfall_units", "commits"}`. `feasible` is false when any interval was clipped or the day ended short.
- Determinism: same task, tier, notices and calls → same outputs, profit and reward to 6 decimals.

## Audit row (`s.audit()`; weight 0, a failure makes the run unscored)

- every watch reached got exactly its scheduled notices, in order, before the agent's next call (`via` trigger or env);
- no notice was delivered before its reveal_at;
- no tool output showed an RT price before its interval ended (each output's RT count is logged with its time);
- `get_time` reads, when the verifier passes them as `[(watch, iso_utc)]`, equal the watch time;
- each scheduled notice was delivered at most once, and exactly once in a finished day;
- `replay(task, tier, notices, transcript)` reproduces every recorded output byte for byte.

## Task row (`data/gridsim-live-*/tasks.jsonl.gz`)

```
{"task_id":"live-v2-2024-07-18-HB_WEST-2h-c","live_version":"2.0","contract_version":"1.0","pack":"gridsim-live-eval",
 "split":"eval_2024","date":"2024-07-18","settlement_point":"HB_WEST","point_kind":"hub","region":"west",
 "prices":[24 DA SPPs],"rt":[96 RT SPPs],"blind":{"dam_prev_day":[24],"dam_prev_7d":[[24]x7]}|null,
 "battery":{v1 hourly battery dict, k_dis 4, q_15 = P/16},
 "notices":[],"notices_sha":"…",
 "refs":{"p_idle","p_naive","naive":{"da":[24]},"p_hind","p_hind_da","p_hind_rt","hind":{"da":[24],"schedule":[96]},
         "p_lp":x|null,
         "roll":{"foresight":{"p_roll","da":[24],"executed":[96],"commits":n,"naive_reward"},
                 "blind":{…,"via":"persist|ridge"}|null,"short":{…}|null,"freeze6h":{…}}},
 "eligibility":{"divergence_usd_per_mw","roll_minus_naive_share","roll_minus_naive_usd_per_mw","hind_headroom_usd_per_mw"},
 "tags":{"watches":n,"short_ok":bool,"notice_day":bool,"season","era","neg_intervals","rt_spike":bool,"blind_eval":bool,"showcase":null|"sep23-0906"}}
```

Refs are computed for the row's `notices`; `notices_sha` is the sha256 of their canonical JSON, and a Session given
other notices recomputes them. Packs: `gridsim-live-train` (~4,000, 2019–2024 minus eval dates), `gridsim-live-eval`
(300, every third 2024 date), `gridsim-live-test-2025` (200, 2025-01-01..2025-11-30), `gridsim-live-rtcb` (100,
2025-12-05..2026-10-17), `gridsim-live-showcase` (display-only bundles `sep23-0906` hero, `uri-0215`, `elliott-1223`,
`heather-0116`, `aug23-0820`, `fern-0126`; every showcase day ±3 days is out of every split) and `data/fixtures-live/`
(20 CI tasks, including a derate fixture). `scripts/build_live_pack.py --merge-notices data/notices/notices.jsonl`
re-attaches notices and recomputes refs, eligibility and tags without re-parsing.

`--merge-notices DIR` re-reads a lane N archive directory (`notices.jsonl[.gz]`, `nws_vtec.jsonl[.gz]`,
`ops_coverage.json`) through `gridsim_core.notices` and re-attaches each task's notices (L-D10). The eval dates are
every third 2024 date plus every 2024 ERCOT notice day (all out of train); eval targets 150 notice-day and 150 quiet
tasks, train oversamples notice days up to 40%; the manifests record the actual counts.

**Eligibility** (FD-4321, measured and tuned in `data/live-stats.md`): RT–DA divergence Σ|RT_t − DA_h(t)|·0.25 ≥
$40/MW; P_hind − P_idle ≥ $10/MW; P_roll − P_naive ≥ $5/MW and ≥ a share of (P_hind − P_idle) that V2-D5 raises from
5% in 2.5-point steps until naive's mean R on the eval pool is ≤ 0.7 (cap 15%). Because the anchor beats naive by that
margin on only ~2–4% of battery-days, each point-day is drawn with several batteries (train 8, eval 12, test and rtcb
3) and selection takes one battery per point-day before a second.

## Episode JSON `gridsim.episode/v2` (path A, path B' and references write the same shape)

```
{"schema":"gridsim.episode/v2","episode_id","env":"gridsim-live","version":"v2","task_id","tier","bundle","path":"A|B'|ref",
 "model","trained":"base|grpo|sft|null","checkpoint_step","seed",
 "task":{date, settlement_point, point_kind, region, battery, prices, rt, blind},
 "grid":{the live battery},
 "watches":[{"index","time","time_utc","freeze_line","notices":[event_id]}],
 "notices":[{"event_id","source","kind","level","issued_at","reveal_at","watch","name","title","text"}],
 "steps":[{"t","watch","tool","args","output"}],          # output: the parsed exact output string
 "da_position":[24],"schedule":[96],"executed":[96],"soc_path":[97],
 "intervals":[{"i","time","da","rt","q_units","da_units","mwh","da_usd","rt_usd","deg_usd","soc","clipped"}],
 "commits":[{"watch","tool","start","step","accepted","call"}],
 "pnl":{…},"profit_usd","reward","capture_vs_hindsight","stretch_reward","beats_anchor","naive_reward",
 "references":{"p_idle","p_naive","p_roll","p_hind","p_hind_da","p_hind_rt","p_lp","naive":{…},"roll":{…},"hind":{…}},
 "audit":{"ok","problems"},"messages":[],"usage":{…},"wall_seconds"}
```

## Prompts (`gridsim_core.live_prompt`, shared by the env's agent card and path B')

`system_prompt(tier)`, `situation_text(session)` (the exact `get_situation` string), `watch_text(session)` (the per-watch
user note path B' sends after each advance), `tool_schemas(tier)` (OpenAI-style, agent tools only).
