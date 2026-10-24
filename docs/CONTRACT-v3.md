# GridSimEnv v3 "Sun, Storage and Reserves" build contract

The v3 interface every lane builds against: `gridsim_core.hybrid` (core, lane C3), the `gridsim-hybrid` gateway env (the
env lane; a sibling of v2's `gridsim-live`), the hybrid inputs (lane D3) and path B / B' training. Design source: Linear
FD-4322 (v3 plan; its critique overrides win) and FD-4319 (shared rules). `docs/CONTRACT.md` (v1) and
`docs/CONTRACT-v2.md` (v2) hold for everything not restated here. Nothing in v1 or v2 changes: v3 is new modules
(`gridsim_core.hybrid`, `gridsim_core.hybrid_prompt`, `scripts/build_hybrid_pack.py`, `data/ercot-hybrid-v3-*`,
`data/fixtures-hybrid/`) plus backward-compatible extensions of v2's shared watch machinery (below).

`gridsim_core.hybrid.Session` holds the only v3 state machine. The env server imports it and only wraps it (clock PUTs,
MCP plumbing), exactly as `gridsim-live` wraps `gridsim_core.live.Session`; path B' imports the same class. Tool outputs
are produced by core as exact strings, so path A and path B' are byte-identical by construction.

## Shared with v2 (reused, not forked)

- Watches, the reveal rule and the 10-watch cap: `gridsim_core.live.schedule(task, "foresight", events)` (regular
  watches D-1 14:00, D 00:00, 06:00, 12:00, 18:00; one per notice freeze class, L-D4). Deployment notices rank with
  EEA/emergencies (priority 0) under the cap.
- Freeze: `live.freeze_line(minute)` = ceil_to_hour(now) + 1 h. Hour h (0..23, HE h+1, covering [60h, 60h + 60) minutes
  of D) is *settled* when it has ended, *frozen* when it has not started but starts before the freeze line, *open*
  otherwise. `frozen_until_hour` = the first open hour (0 at watch 0; 13 at the 12:00 watch; 24 means nothing is open).
- Triggers: `live.triggers(watches)`: after `advance` opens watch k, the gateway calls `grid_notice` once per notice of
  the watch, in order; a deployment notice carries its `deploy` payload in the same call.
- Tool dispatch, the exact output string (`json.dumps(obj, ensure_ascii=False, separators=(",", ":"))`), `messages`
  (notices delivered since the agent's last call, drained into every agent tool's output), the transcript, notice
  delivery and its log, and the audit's watch/reveal/once/get_time/replay checks live in `gridsim_core.live.WatchDay`,
  which both `live.Session` and `hybrid.Session` subclass.
- `live.Notice` gains an optional `deploy` field; `Notice.args()` adds `"deploy"` only when it is set, so v2 triggers
  and transcripts are unchanged.
- Constants: `PLANNING_CALLS = 3` (check_schedule and commit_schedule share them per watch), `TURNS_PER_WATCH = 5`,
  `MAX_TURNS = 52`, `BARRIER_SECONDS = 60`, the v2 URNs.

## Decisions (all provisional until Edgar confirms)

FD-4322's recommendations, taken as written:

| # | Decision | Taken (provisional) |
|---|---|---|
| V3-D1 | Pre-RTC+B Reg/RRS durations | 1 h, flagged conservative (`contract.AS_DURATION_H`, lane D3) |
| V3-D2 | ITC charging rule | No `grid_charge` flag in any era; "pre-2023 75% ITC charging share not modelled" is a card simplification |
| V3-D3 | PV availability | Lane D3: the system-wide hourly cf (no regional history exists; every region uses it), raised only on hours whose hub RT SPP is <= 0 (max(actual, the same hour's median cf on nearby positive-price days)); flagged `pv_availability: proxy`, `pv_scope: system` |
| V3-D4 | Action format | AS as blocks, energy as a list or blocks; `check_schedule` returns the per-hour reserve margin |
| V3-D5 | Live training path | Path B' in-process `hybrid.Session` with byte-identical replay CI; path A for eval |
| V3-D6 | Eval stratification | `ercot-hybrid-v3-eval` stratified by AS value; AS share reported |
| V3-D7 | POI default | PV AC nameplate, with a 1.2x variant (POI = 1.2 x PV AC, e.g. 180 MW); flagged |
| V3-D8 | Regulation drift | `hybrid_inputs.reg_drift(task_id)` (Beta, means 0.12 RegUp and 0.18 RegDn, concentration 6), stored in the task row, labelled "a seeded draw, not ERCOT telemetry" |
| V3-D9 | Watch 0 | D-1 14:00 commits the DA position and the DA AS book (v2's watch 0) |
| V3-D10 | T3 | **Dropped tonight**: the RT MCPC report (NP6-331-CD) exists but MIS keeps ~7 days and no history was found. The `rtcb` tier is implemented and refuses to load without `mcpc_rt`; era-C days ship as T2 (DA AS only) in `ercot-hybrid-v3-rtcb`, flagged `rt_as: "not_modelled"` |
| V3-D11 | Naming real sites | Site id plus region in public outputs; archetype sites are labelled `archetype` |

Core decisions where FD-4322 is silent or ambiguous (also provisional):

| # | Decision |
|---|---|
| C3-D1 | **Every plan value is MW, continuous** (ERCOT dispatches and awards in fractions of a MW): energy in [-P, P] (+ discharges), each AS award in [0, P]; no unit grid. The proposed 25 MW grid (energy in {-k..k}, AS in {0..k} units) made the MILP intractable (measured: 1% gap after 20 s per solve, 190 integers); continuous actions with the 24 direction binaries solve exactly in 10-25 ms. Outputs show 2 decimals; a sent value within 0.005 MW of the book counts as the book's (so re-sending displayed values never trips `frozen` or `as_fixed`). |
| C3-D2 | **Commits are per hour, evaluated in order.** From the first open hour, each hour's whole entry (energy and every product) is checked on the SoC path that the hours before it leave (accepted entries, or the kept book for refused ones). A failing hour first tries its energy alone with the book's AS for that hour: if that passes, the energy is committed and only the AS fields are refused; otherwise the whole entry is refused and keeps its previous book entry. `check_schedule` runs the same evaluation without committing. |
| C3-D3 | **The DA position is set when watch 0 ends**: x_DA = the projected export of the book then (PV curtailed at negative DA prices or to keep the meter limit, plus the base battery move). The DA AS book is the book's AS then. With no watch-0 commit the book is idle: x_DA is the solar-only plant's, no AS. |
| C3-D4 | **PV curtailment is the controller's**: per hour, pv = 0 when the hour's price is negative (RT when executed, DA when projected), else min(s, max(0, L - b - Up)): PV is curtailed to keep the meter limit after the battery's base move and to keep **headroom for the hour's up-awards** at the meter, so x + Up <= L always holds; the meter rule refuses only b + Up > L or b - RD < -L_imp. |
| C3-D5 | **SoC rules are checked on the base path**: with S the SoC at the start of the hour and B = S - dis + eta*ch its end before deployments, reserve_up needs min(S, B) >= sum_up dur_k*a_k and reserve_dn needs max(S, B) <= E - eta*dur_RD*RD, physics needs 0 <= B <= E. Projections (check, commit, references) carry the expected regulation drift (`reg.mean_up`, `reg.mean_dn`) and every delivered deployment into the next hour's S. |
| C3-D6 | **Governor**: before an hour executes, its base move is moved to the nearest value (MW, continuous) that keeps headroom, the cycle cap and 0 <= B <= E, and puts B inside the reservation band when reachable (else as close as possible). Clipped hours are listed; the energy moved is settled as executed (the energy stays in the battery, so no lost profit is paid back, unlike v2's derate excuse). |
| C3-D7 | **Charged vs excused** (FTP and the end-SoC penalty): each hour's AS shortfall and the end shortfall are also computed on the projection at the last watch where the hour was open (the snapshot taken when that watch's advance is called). Charged = min(realized, projected); excused = the rest (drift or deployments that arrived after the hour froze). |
| C3-D8 | **AS shortfall** in hour t: up products scale by f = min(1, min(S, B)/R_up); short_k = (1 - f)*a_k MW for each up product; RegDn likewise with room = E - max(S, B) against eta*dur_RD*RD. FTP = sum_k short_k * max(pi_DA, pi_RT) for 1 h (pi_RT only in era C). |
| C3-D9 | **Deployments**: RegUp/RegDn move SoC every hour by delta_up*RU and eta*delta_dn*RD (delta from the task, capped at the product's duration in hours). An RRS/ECRS/Non-Spin deployment draws frac x award(hour) over the first dur_k hours of its window, split by minutes per hour. Delivered energy is limited by SoC (up first, then RegDn), passes the meter, settles at RT and pays degradation. Deployments act at their real times whether or not the agent has been told. |
| C3-D10 | **Cycle cap** = 1.5*E MWh of base discharge (deployments are the grid's call and are not capped). Degradation applies to every MWh discharged. |
| C3-D11 | **No end-target commit rule** (unlike v2 L-D3): the projected end shortfall and its penalty are shown, and the realized one is charged per C3-D7. Archetypes have s_end_min = s0, so the idle book pays none. |
| C3-D12 | **RT is expected at DA** for the anchor (FD-4322); no decayed basis as in v2. |
| C3-D14 | **Deployment size**: lane D3's events carry no fraction (`frac` null; only Non-Spin states system MW), so every deployment uses frac = 1.0 of the award for min(window, duration): the stress case the reservation covers, labelled. |
| C3-D15 | **AC coupling only in packs** (EIA-860 2025 shows no DC-coupled ERCO sites); s = min(PV MWac, MWac x ILR x cf) with lane D3's system cf, which is already fleet-AC so ILR x cf is an approximate DC shape (flagged). The dc code path stays for later. |
| C3-D16 | **Baseline filter**: FD-4322's "sponge within 3% of the anchor" drop is extended to every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP: a day where any of them reaches reward 0.97 against the reserves anchor is dropped. Without it 13% of eval days had the T2 anchor below the energy-only MILP: the seeded regulation drift is independent of grid state, so RegDn drift buys energy at RT spikes while T2's awards are locked (the hero day, display-only, keeps it: T2 anchor $350k vs energy-only $482k). |
| C3-D13 | **Hindsight** (weight 0): one MILP with a DA-position copy of the plant (expected drift, DA curtailment free between its rule minimum and s) and a physical copy on realized RT, drift and deployments, sharing the AS book (separate RT AS in era C). An upper reference, not an achievable plan. |

## Site, units and physics

Site row (`task["site"]`), the archetype (lane D3 supplies real archetypes per hub/load zone):

```
{"site_id":"pv150-b100x2h-poi150","source":"archetype|matched","coupling":"ac|dc","pv_mwac":150,"pv_mwdc":195,
 "ilr":1.3,"poi_mw":150,"poi_import_mw":150,"inverter_mw":null,
 "bess":{"p_mw":100,"e_mwh":200,"unit_mw":25,"eta":0.85,"c_deg":4.0,"cycle_cap_mwh":300,"s0_mwh":100,
         "s_end_min_mwh":100},
 "qualified":["regup","regdn","rrs","ecrs","nspin"],"flags":{"poi":"default","coupling":"assumed","pv":"proxy"}}
```

- PV at the bus s_t (MW, = MWh in the hour), in `task["pv_mw"]` [24]: dc-coupled s = pv_mwac*ilr*cf_t (DC at the shared
  inverter); ac-coupled s = min(pv_mwac, pv_mwac*ilr*cf_t). L = poi_mw (ac) or min(poi_mw, inverter_mw) (dc); L_imp =
  poi_import_mw (ac) or min(poi_import_mw, inverter_mw) (dc).
- Battery: b = dis - ch (MW for one hour = MWh), one direction per hour, |b| <= P. Charging ch MWh at the bus stores
  eta*ch; discharging dis MWh removes dis. SoC is continuous in [0, E] MWh.
- Export x = pv + b + up_deployed - dn_deployed, within [-L_imp, L]. Clippable = max(0, s - L); clip_recovered =
  max(0, pv - L) (PV the battery caught above the meter limit); curtailed = s - pv.
- Awards a_k (MW) for k in regup, regdn, rrs, ecrs, nspin. Up = RU + RRS + ECRS + NS, Down = RD. Durations dur_k from
  `contract.as_duration_h(k, date)` (era A/B/C, lane D3). R_up = sum_up dur_k*a_k, R_dn = eta*dur_RD*RD.
- `unit_mw` is only a suggested block size for prompts; it is not a rule.
- Rules per hour (the `rule` strings): `parse`, `frozen` (a frozen hour's entry differs from the book), `power` (|b| > P
  or an award outside 0..P), `headroom_up` (b + Up > P), `headroom_dn` (b - RD < -P),
  `meter_up` (b + Up > L), `meter_dn` (b - RD < -L_imp), `soc_empty` (B < 0), `soc_full` (B > E), `cycle_cap`,
  `reserve_up`, `reserve_dn`, `not_offered` (the product does not exist that day, or the tier is `energy`),
  `not_qualified`, `as_fixed` (reserves tier after watch 0: AS differ from the DA book). Tolerance 1e-4 MWh.
- Settlement (price taker), per hour: energy_da = x_DA*DA, energy_rt = (x - x_DA)*RT, as_da = sum_k aDA_k*piDA_k,
  as_rt = sum_k (aRT_k - aDA_k)*piRT_k (era C; else aRT = aDA), degradation = c_deg*MWh discharged, ftp (charged, C3-D8).
  At 24:00 the end penalty = charged shortfall/eta * max(max_h DA_h, P_FLOOR). Profit P = energy_da + energy_rt + as_da +
  as_rt - degradation - ftp - end_penalty. Money in tool outputs is rounded to cents, MW/MWh to 2 decimals, grades to 6.

## Tiers

| Tier | Name | AS | Eras |
|---|---|---|---|
| T1 | `energy` | none (any AS is `not_offered`) | all |
| T2 | `reserves` | DA awards set at watch 0, fixed after (`as_fixed`) | A, B (C days load too, settled as B) |
| T3 | `rtcb` | DA awards financial; AS on open hours re-optimisable, settled at RT MCPC | C only; needs `mcpc_rt` |

## Plan format (`check_schedule` / `commit_schedule`)

`plan = {"energy": list | str | blocks, "regup"?: blocks, "regdn"?: blocks, "rrs"?: blocks, "ecrs"?: blocks,
"nspin"?: blocks}` (an object, or its JSON string), `from_hour` an int 0..23 ("13" and "13:00" are read as 13);
`from_hour` may be omitted and then is `frozen_until_hour`.

- A block is `{"from": h1, "to": h2, "mw": v}`: hours h1 <= h < h2, from_hour <= h1 < h2 <= 24. A field's blocks may not
  overlap; hours from from_hour that no block covers are 0. One block may be sent bare (not in a list).
- `energy` as a list (or comma/space-separated string) has 24 - from_hour values (from from_hour) or 24 values (hours
  before from_hour ignored). AS fields also take such lists.
- An omitted AS field keeps the book's values; `energy` is required. Hours before from_hour keep the book.
- Malformed input refuses the whole call with one `{"hour": null, "field": f, "rule": "parse", "detail": ...}` row.

## gridsim_core.hybrid API

```python
from gridsim_core.hybrid import (Session, schedule, triggers, references, replay, play, oneshot_grade, events_of,
                                 parse_plan, PlanError, solve_day, HYBRID_VERSION, HYBRID_ENV, EPISODE_SCHEMA, TIERS,
                                 PRODUCTS, TOOLS, NOTICE_TOOL, LIVE_LOAD_URI, END_DAY_URI, CLOCK_URI, PLANNING_CALLS,
                                 MAX_TURNS)
s = Session(task, tier="reserves", notices=None, deployments=None)  # None -> task["notices"] / task["deployments"]
s.call(tool, args) -> str           # the exact output string; agent tools carry "messages"; transcript recorded
s.situation() / s.check_schedule(plan, from_hour) / s.commit_schedule(plan, from_hour) / s.advance()
s.notice(event_id, name, text, level=None, derate_mw=None, start=None, until=None, deploy=None, via="trigger")
s.deliver_watch_notices(via="trigger") / s.end_day() / s.grade() / s.audit(get_time_reads=None) / s.data()
s.watches, s.watch, s.done, s.transcript, s.watch_time_utc(k), s.episode(**meta) -> gridsim.episode/v3
schedule(task, tier, notices, deployments) -> list[live.Watch]; triggers(watches) -> v2-shaped trigger list
replay(task, tier, notices, deployments, transcript) -> {"ok", "problems"}
references(task, tiers=("energy", "reserves")) -> refs dict      # never shown to the agent
oneshot_grade(task, plan, tier="reserves") -> {"submitted", "reward", "profit_usd", "p_idle", "p_milp", "refused", ...}
```

`HYBRID_ENV = "gridsim-hybrid"`, `EPISODE_SCHEMA = "gridsim.episode/v3"`, `TIERS = ("energy", "reserves", "rtcb")`,
`PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")`, `TOOLS = ("get_situation", "check_schedule",
"commit_schedule", "advance")`, `NOTICE_TOOL = "grid_notice"`; the URNs are v2's.

## Tools (agent role `default`; outputs are the dicts below plus `"messages"`)

Errors return `{"error": "...", "calls_left": n}` and change nothing; as v2 (L-D7), a planning tool with a missing or
unexpected argument uses a call, one after the day or with no calls left uses none.

- `get_situation()` (free; answers after the day too):

```
{"task_id","tier","date","era":"A|B|C","settlement_point","site_id","region","watch":k,"time":"2023-09-06 12:00",
 "frozen_until_hour":13,"calls_left":3,"day_over":false,
 "site":{"coupling","pv_mwac","pv_mwdc","meter_mw":L,"meter_import_mw":L_imp,"p_mw","e_mwh","eta","c_deg",
         "cycle_cap_mwh","s_end_min_mwh"},
 "as_rules":{"products":[offered today],"qualified":[...],"duration_h":{"regup":1.0,...},"reg_drift_mean":{"regup":0.12,
             "regdn":0.18},"as_fixed_after_watch_0":bool},
 "hours":{"pv_mw":[24],"da_usd":[24],"rt_usd":[settled hours only],
          "mcpc_da":{"regup":[24],...offered},"mcpc_rt":{...}|null (era C: settled hours only)},
 "soc_mwh":x,"discharged_mwh":d,"status":"SSSS…FFOO…",            # S settled, F frozen, O open
 "book":{"energy":[24],"regup":[24],...offered},                 # MW per hour as committed (advance shows executed)
 "da":{"x_da_mw":[24]|null,"regup":[24],...}|null,                # null until watch 0 ends
 "projected":{"soc_mwh":[25],"reserve_margin_mwh":[24],"energy_usd","as_usd","degradation_usd","ftp_usd",
              "end_penalty_usd","total_usd","end_soc_mwh"},
 "cash":{...settled so far, as advance},
 "deployments":[{"event_id","product","frac","from":"HH:MM","until":"HH:MM"}],   # delivered ones
 "notices":[{"event_id","source","level","time","name","title","text"}],
 "result":{...}}                                                 # only after the day
```

  `reserve_margin_mwh[h]` = min over the hour's two ends of (S - R_up, E - R_dn - S) on the projection (negative = a
  reservation the book breaks). `projected` values the whole day: settled hours as settled, the rest at DA prices and
  DA MCPC with expected drift.

- `check_schedule(plan, from_hour)` (uses a planning call; commits nothing):

```
{"feasible":bool,"issues":[{"hour","field","rule","detail"}],"refused":[hours],"projected":{...as above},
 "clip_recovered_mwh":x,"curtailed_mwh":x,"reserve_margin_mwh_by_hour":[24],
 "excused":[{"hour","product","mw","usd"}],"calls_left":n}
```

  `detail` reads like `"ECRS 2h + RRS 1h need 150.0 MWh at 18:00, SoC 120.0"`. The projection is of the book as it
  would be after the commit (C3-D2).

- `commit_schedule(plan, from_hour)` (uses a planning call):
  `{"committed":[hours],"refused":[{"hour","field","rule","detail"}],"frozen_until_hour","book":{...},
  "projected":{...},"calls_left":n}`. At watch 0 the book becomes the DA position and DA AS when watch 0 ends (C3-D3).
  In `rtcb`, AS changes on open hours after watch 0 are RT awards.
- `advance()` (free): runs the book to the next watch (governor, drift, deployments), settles every hour that ends by
  then and opens the watch (3 fresh calls).
  `{"watch":k,"time","frozen_until_hour","realized":[{"h","rt_usd","mcpc_rt"?,"pv_mw","export_mw","curtailed_mw",
  "clip_recovered_mw","b_mw","soc_mwh","reg_up_frac","reg_dn_frac","deployed_up_mwh","deployed_dn_mwh","governor",
  "ftp_mw","excused_mw"}],"soc_mwh","cash":{"energy_da","energy_rt","as_da","as_rt","deployment_energy","degradation",
  "ftp","excused","end_penalty","total"},"calls_left":3}`. From the last watch it runs to 24:00:
  `{"done":true,"time","realized","soc_mwh","cash","profit_usd","reward","capture_vs_hindsight"}` (no `watch` key, so
  no trigger matches). `deployment_energy` (RT value of deployed MWh) is inside `energy_rt`; `excused` is FTP not
  charged (information).
- `get_time()` comes from the gateway (UTC); hybrid tools take hours and show CPT.
- Harness only (hidden from `default`): `grid_notice(event_id, name, text, level?, derate_mw?, from?, until?, deploy?)`
  with `deploy = {"product","frac" (0..1),"start_min","end_min"}` (minutes from D 00:00 CPT) → `{"applied": event_id,
  "watch": k}`; it reveals the notice (the deployment acts at its real time regardless, C3-D9).
  `urn:gridsim:live-load/v1 {task_id, tier}` → `{"task_id","tier","watches"}` (one load per env);
  `urn:gridsim:end-day/v1` → `s.end_day()` = `{"end_reason","watch","profit_usd","reward","audit"}`;
  `urn:agentenv:clock/v1 sync_time`; `data/get` → `s.data()`; `data/reset`.
- `data()`: `{"task_id","tier","watches","watch","time","done","end_reason","calls_used","planning_calls","book",
  "da","executed","status","notices","frozen","refusals","governor","excused","settled","audit","grade","reward"}`; never
  a reference before the day ends.

## Deployments and notices

Deployment input (`task["deployments"]` or the `deployments` argument; lane D3 maps its events to this shape):

```
{"event_id":"ercot-dep-2023-09-06-rrs","issued_at":"2023-09-06T19:25:00-05:00","product":"rrs","frac":1.0,
 "start":"2023-09-06T19:25:00-05:00","end":"2023-09-06T20:37:00-05:00","name":"ERCOT","title":"RRS deployed",
 "text":"ERCOT deployed Responsive Reserve ...","level":"EEA2"}
```

`events_of(task, notices, deployments)` turns each into a v2 notice (`kind: "deployment"`, `source: "ERCOT"`) whose
`deploy` payload is `{"product","frac","start_min","end_min"}`, merged with the ordinary notices. The reveal rule is v2's:
revealed at ceil(issued_at, 15 min), at the first watch at or after it. `notices_sha` covers both lists.

## Grading (`grade()`; references are stored in the task row and never shown to the agent)

- **Reward**: no accepted hour in any commit → 0; else R = clip(0.2 + 0.8*(P - P_idle)/(P_anchor - P_idle), 0, 1)
  (`grade.reward_value`). No format credit. `raw_ratio` = (P - P_idle)/(P_anchor - P_idle) is logged.
- **P_idle**: the solar-only plant: battery idle, no AS, PV following the meter and negative prices, x_DA = that PV at
  DA (the Session with no commit).
- **P_anchor**: the information-matched rolling MILP (HiGHS, in-process), played through a Session: at each watch one
  solve over the open hours from the projected state at the freeze line (expected drift, delivered deployments, RT
  expected at DA, MCPC at DA, the tier's AS rule), committed through `commit_schedule` (one planning call); the same
  governor executes it.
- **Weight-0 rows**: `p_hind` (C3-D13) and its LP bound `p_lp`, `capture_vs_hindsight` = (P - P_idle)/(P_hind - P_idle);
  `energy_only_reward` (the `energy`-tier anchor on this day, graded against this tier's anchor); `as_share` = AS
  revenue / (energy + AS revenue); `clip_recovered_pct`; `curtailed_mwh`; `ftp_mwh` charged and excused; baselines
  (`sponge`, `as_hog`, `v2_energy`) as {profit, reward}.
- `grade()` → `{"submitted","tier","reward","raw_ratio","profit_usd","cash","p_idle","p_anchor","p_hind","p_lp",
  "capture_vs_hindsight","beats_anchor","energy_only_reward","as_share","clip_recovered_pct","curtailed_mwh",
  "ftp_mwh_charged","ftp_mwh_excused","governor_hours","refusals","commits"}`.
- **Oneshot (path B, `hybrid-oneshot`)**: `oneshot_grade(task, plan, tier)` grades one watch-0 commit (C3-D2 refusals
  apply) by the Session's projection with RT = DA, expected drift and no deployments, against `refs[tier].oneshot.p_milp`
  (the day's MILP on the same model). Unparseable or nothing accepted → 0.

## Audit (`s.audit()`; a failure makes the run unscored)

v2's rows (every watch got exactly its notices in order before the agent's next call; nothing before its reveal time;
each revealed once, exactly once in a finished day; get_time reads match the watch; byte-identical replay) plus: no
output showed an hour's RT price or RT MCPC before that hour ended.

## Task row (`data/ercot-hybrid-v3-*/tasks.jsonl.gz`)

```
{"task_id":"hyb-v3-2023-09-06-HB_WEST-arch-dc150","hybrid_version":"3.0","contract_version":"1.0","pack","split",
 "date","era":"A|B|C","settlement_point","point_kind","region","site":{...},
 "prices":[24 DA SPP],"rt":[24 hourly RT SPP (mean of the four 15-min SPPs)],"pv_cf":[24],"pv_mw":[24],
 "mcpc_da":{"regup":[24],"regdn":[24],"rrs":[24],"ecrs":[24]|absent,"nspin":[24]},"mcpc_rt":{...}|null,
 "reg":{"up":[24],"dn":[24],"mean_up":0.12,"mean_dn":0.18,"source":"seeded","label":"..."},
 "notices":[v2 notices],"deployments":[...],"events_sha":"...",
 "refs":{"hybrid_version","events_sha","p_idle",
         "energy":{"p_anchor","anchor":{"book","commits"},"p_hind","p_lp","oneshot":{"p_milp","plan"},
                   "baselines":{"sponge":{"profit","reward"},"v2_energy":{...}}},
         "reserves":{...,"p_energy_only","baselines":{"sponge","as_hog","v2_energy"}},"rtcb":{...}|null},
 "tags":{"watches","short_ok","notice_day","deploy_day","season","as_value_usd","as_stratum":"low|mid|high",
         "clip_mwh","neg_hours","showcase":null|"sept06-2023"},
 "flags":{"pv_availability":"proxy","reg_drift":"seeded","poi":"default","site":"archetype"}}
```

Task ids `hyb-v3-{date}-{point}-{site_id}`; the tier is the load config. Packs (counts in the manifests):
`ercot-hybrid-v3-train` (~2,400, 2021-2024, T1/T2), `ercot-hybrid-v3-eval` (300, 2025-01..11, stratified by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, so drift noise cannot move a day between strata),
`ercot-hybrid-v3-rtcb` (era C days as T2, DA AS only, flagged; V3-D10), `ercot-hybrid-v3-showcase` (`sept06-2023` hero, `aug10-2023`,
`mar29-2024`, `fern-0126-2026`; display only, each ±3 days out of every split), `data/fixtures-hybrid/` (20 CI tasks).
Filters: v1's low-spread drop; drop days where the sponge (C3-D16: any baseline) is within 3% of the anchor; drop P_anchor - P_idle < $500;
Uri ±3 days out of every split.

## Episode JSON `gridsim.episode/v3` (path A, path B' and references write the same shape)

v2's shape with hours instead of intervals:

```
{"schema":"gridsim.episode/v3","episode_id","env":"gridsim-hybrid","version":"v3","task_id","tier","bundle",
 "path":"A|B'|B|ref","model","trained","checkpoint_step","seed",
 "task":{date, era, settlement_point, point_kind, region, site, prices, rt, pv_mw, mcpc_da, mcpc_rt},
 "watches":[{"index","time","time_utc","freeze_line","notices":[event_id]}],
 "notices":[{"event_id","source","kind","level","issued_at","reveal_at","watch","name","title","text","deploy"}],
 "steps":[{"t","watch","tool","args","output"}],
 "book":{...},"da":{...},"soc_path":[25],
 "hours":[{"h","da","rt","pv_mw","x_da_mw","export_mw","curtailed_mw","clip_recovered_mw","e_mw","b_mw","awards":{...},
           "reg_up_frac","reg_dn_frac","deployed_up_mwh","deployed_dn_mwh","soc_mwh","energy_da_usd","energy_rt_usd",
           "as_da_usd","as_rt_usd","deg_usd","ftp_usd","excused_usd","governor"}],
 "commits":[{"watch","from_hour","committed","refused","call"}],
 "cash":{...},"profit_usd","reward","raw_ratio","capture_vs_hindsight","beats_anchor",
 "references":{"p_idle","p_anchor","p_hind","p_lp","p_energy_only","anchor":{...},"baselines":{...}},
 "audit":{"ok","problems"},"messages":[],"usage":{...},"wall_seconds"}
```

## Prompts (`gridsim_core.hybrid_prompt`, shared by the env's agent card and path B / B')

`system_prompt(tier, era)` (the hybrid rules card plus the era's duration table), `situation_text(session)`,
`opening(session)`, `watch_text(session)`, `tool_schemas(tier)` (OpenAI-style, the agent's four tools),
`oneshot_messages(task, tier)` (path B: one watch-0 plan as JSON).

## What the env lane builds (`gridsim-hybrid`)

A copy of `agentenv_gridsim/live.py`'s pattern around `hybrid.Session`: the same image, the four agent tools plus hidden
`grid_notice` (with `deploy`), the middleware that hands raw arguments to `Session.call`, `advance` PUTting the clock to
`watch_time_utc(k+1)` first, `urn:gridsim:live-load/v1` with tiers `energy|reserves|rtcb`, `end-day/v1`, `clock/v1`,
`data/get`/`data/reset`. Triggers come from `hybrid.triggers(hybrid.schedule(...))`. The verifier reads `data/get`:
`grade.reward` is the reward row, the weight-0 rows are listed above, and a failed `audit` raises.
