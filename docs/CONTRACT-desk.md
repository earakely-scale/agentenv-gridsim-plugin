# GridSimEnv desk build contract

The interface every desk lane builds against: `gridsim_core.desk` (lane CORE), the data packs under `data/desk/`
(lane DATA, `scripts/desk_data*.py`, `docs/desk-data.md`), the gateway env and the runs (`scripts/desk_run.py`).
Design source: FD-4548 decisions D1–D13 and the ERCOT research brief; this file never relitigates them. Section
references "P§x.y" are the current Nodal Protocols and "pre-P§x.y" the Dec-1-2025 set, as in the brief.

`gridsim_core.desk.Session` holds the only desk state machine. The env server and the in-process runner both import it;
tool outputs are produced by core as exact dicts, so every path writes the same Episode JSON.

Labels used below: **[rule]** ERCOT protocol or validation rule, **[data]** a real public series as posted,
**[modelled]** our model of something with no public data, **[simplified]** a rule we apply in a reduced form.

## Contents

1. Data (lane DATA builds to this; read first)
2. Clock and event model
3. Tools
4. Submissions and validation
5. Clearing
6. Physics
7. Settlement
8. Optimiser
9. Grading and references
10. Version layers, packs and metrics
11. Episode JSON
12. Python API (`gridsim_core.desk`)
13. Provisional lane decisions (C-D*)

---

## 1. Data

A pack is `data/desk/<pack>/` with `manifest.json`, `tasks.jsonl.gz` (one task record per line) and
`series/<task_id>.json.gz` (one series document per task). Fixtures for CI live in `data/desk/fixtures/` with the same
layout; core also ships a generator for synthetic fixtures (`gridsim_core.desk.fixtures`) so tests never need a pack.

### 1.1 Conventions

- **Time.** Every timestamp in a pack is ISO 8601 with an offset (`2026-02-13T13:30:00-06:00`). Core converts to
  **minutes from D0 00:00 CPT**, where D0 is the first operating day (`D-1 06:00` = −1080, `D0 24:00` = 1440). Packs
  contain no DST-transition day anywhere in a task's window (D-7 .. last operating day), so the offset is constant.
- **Grids.** Date-keyed arrays are per CPT operating day: hourly arrays have 24 values (index h = HE(h+1)), 15-minute
  arrays 96 (interval i covers [15i, 15i+15) of the day), 5-minute arrays 288 (interval k covers [5k, 5k+5)).
  Missing values are `null`; a task whose operating-day arrays have any null in prices is not packed.
- **Units.** $/MWh for energy, $/MW/h for AS, MW (+ discharge / injection, − charge / withdrawal), MWh for SoC.
- **SCED to the 5-minute grid.** SCED runs are irregular (~5 min). The data lane maps each SCED run to the 5-minute
  interval containing its timestamp and keeps the last run in each interval; an interval with no run carries the
  previous run forward (counted in `manifest.json` as `sced_fill`). **[simplified]**

### 1.2 Task record (`tasks.jsonl.gz`)

```json
{"task_id": "desk-v2-2026-02-14-S07",
 "schema": "gridsim.desk.task/v1", "desk_version": "2.0", "pack": "desk-v2-eval", "split": "eval|pilot|train|fixture",
 "layer": "v2|v3|v4|v5", "era": "rtcb|pre", "dates": ["2026-02-14"],
 "site": { ...site record, 1.3... },
 "series": "series/desk-v2-2026-02-14-S07.json.gz", "series_sha": "<sha256 of the decompressed series JSON>",
 "operator_ok": true,
 "refs": { ...written by core (9.5); absent until `desk.refs.build_refs` runs... },
 "tags": {"season": "winter", "day_kind": "quiet|notice|scarcity|negative|outage", "notices": 3,
          "max_rt_lmp": 412.5, "min_rt_lmp": -12.1, "dam_spread": 88.0}}
```

`era` is `rtcb` when every operating day is on or after 2025-12-05, else `pre` (a window never straddles go-live).
`dates` has one day for v2, v3 and v5 and three consecutive days for v4. `operator_ok` is true when the operator's
disclosures (1.4 `operator`) are complete for every operating day.

### 1.3 Site record

```json
{"site_id": "S07",
 "resource": "BATCAVE_ESR1", "resource_pre": {"gen": "BATCAVE_BES1", "load": "BATCAVE_LD1"},
 "settlement_point": "BATCAVE_RN", "load_zone": "LZ_SOUTH", "hub": "HB_SOUTH", "region": "south",
 "hsl_mw": 100.5, "lsl_mw": -100.5, "e_max_mwh": 201.0, "e_min_mwh": 0.0, "ramp_mw_per_min": 20.0,
 "rte": 0.86, "standby_loss_pct_per_h": 0.05,
 "calibration": {"source": "NP3-965-ER 60d_ESR_Data_in_SCED", "window": ["2026-01-01", "2026-02-28"],
                 "n_intervals": 14112, "rte_ci": [0.84, 0.88], "standby_ci": [0.02, 0.09], "method": "text"},
 "deg_usd_per_mwh": 10.0, "warranty_cycles_per_day": 1.5,
 "soc0_mwh": 84.2, "soc0_source": "disclosed|default",
 "card": {"name": "Battery S07", "region": "South", "size": "100 MW / 201 MWh"},
 "pv": null}
```

- `hsl_mw` (max discharge, > 0) and `lsl_mw` (max charge, < 0) are the site's normal limits from the disclosures (the
  high percentile of telemetered HSL/LSL over the calibration window). `e_max_mwh` / `e_min_mwh` are nameplate
  MaxSOC / MinSOC (disclosure maximum MaxSOC, else EIA-860). `ramp_mw_per_min` is the normal ramp rate (default
  `hsl_mw / 5` when no disclosure gives it). **[data]**
- `rte` (round-trip, AC to AC) and `standby_loss_pct_per_h` (percent of the energy above nameplate MinSOC lost per hour) are calibrated by
  the data lane from SoC vs telemetered output in the 60-day SCED disclosure; `calibration` records how. Core splits
  RTE symmetrically: η_c = η_d = √rte. **[modelled]** (estimated from data)
- `deg_usd_per_mwh` (per MWh discharged) and `warranty_cycles_per_day` (equivalent full cycles, discharged MWh /
  (e_max − e_min)) are **[modelled]**; defaults 10.0 and 1.5 if the data lane has no better source.
- `soc0_mwh` is the disclosed SoC in the last SCED run before D0 00:00 (`disclosed`), else 50% (`default`).
- `card` is what the agent sees. `resource`, `settlement_point` and the real names are never shown to the agent (D9);
  the node is "your node", the hub by its ERCOT name.
- `pv` is `null` until v3 (co-located PV: `{"mw_ac": 50, "poi_mw": 100, "profile": "modelled"}`).

### 1.4 Series document (`series/<task_id>.json.gz`)

```json
{"schema": "gridsim.desk.series/v1", "task_id": "...", "tz": "America/Chicago", "d0": "2026-02-14",
 "history_days": ["2026-02-07", "...", "2026-02-13"],
 "dam_spp":     {"2026-02-07": [24], "...": [], "2026-02-14": [24]},
 "dam_spp_hub": {"<date>": [24]},
 "rt_spp":      {"<date>": [96]},   "rt_spp_hub": {"<date>": [96]},
 "rt_lmp":      {"<date>": [288]},
 "dam_mcpc":    {"<date>": {"regup": [24], "regdn": [24], "rrs": [24], "ecrs": [24], "nspin": [24]}},
 "rt_mcpc":     {"<date>": {"regup": [288], "...": []}},
 "rt_mcpc_15":  {"<date>": {"regup": [96], "...": []}},
 "asdc":        {"<date>": {"regup": [[[0, 5000.0], [250, 50.0], [800, 0.0]], "...24 hours..."], "...": []}},
 "system":      {"<date>": {"prc_mw": [288], "prc_kind": "real|proxy", "lambda": [288],
                            "load_mw": [288], "wind_mw": [288], "solar_mw": [288]}},
 "posted":      {"dam": {"<date>": "2026-02-13T13:14:00-06:00"}, "asdc": {"<date>": "..."}},
 "forecasts":   [{"kind": "load|wind|solar", "issued_at": "...", "start": "...", "step_min": 60,
                  "values": [], "model": "ERCOT STLF|STWPF|STPPF", "zone": "system"}],
 "outage_capacity": [{"issued_at": "...", "start": "...", "step_min": 60, "values": []}],
 "desk_forecast": [{"market": "dam|rt", "issued_at": "...", "start": "...", "step_min": 60,
                    "p10": [], "p50": [], "p90": [], "model": "desk-qr-v1"}],
 "unit_events": [{"kind": "forced_outage|derate", "start": "...", "end": "...", "hsl_mw": 0.0, "lsl_mw": 0.0,
                  "source": "NP1-346-ER"}],
 "notices":     [{"event_id": "OPS-...", "source": "ERCOT|NWS", "kind": "...", "level": "...", "issued_at": "...",
                  "title": "...", "text": "...", "action": "issue|cancel|end"}],
 "nws":         [{"event_id": "...", "event": "Heat Advisory", "severity": "Moderate", "issued_at": "...",
                  "expires": "...", "area": "...", "headline": "..."}],
 "deployments": [{"event_id": "...", "product": "rrs|ecrs|nspin|regup|regdn", "start": "...", "end": "...",
                  "frac": 0.25}],
 "operator":    { ...1.5... }}
```

| Key | Content | ERCOT source | Visible to the agent from |
|---|---|---|---|
| `dam_spp` | node DAM SPP; history days D-7..D-1 plus every operating day | NP4-190-CD **[data]** | `posted.dam[date]`, default D-1 13:30 |
| `dam_spp_hub` | the site's hub DAM SPP | NP4-190-CD **[data]** | as `dam_spp` |
| `rt_spp`, `rt_spp_hub` | 15-min RT SPP, node and hub; history day D-1 at least | NP6-905-CD **[data]** | interval end + 2 min |
| `rt_lmp` | 5-min SCED LMP at the node (1.1 grid) | NP6-788-CD **[data]** | interval end + 1 min |
| `dam_mcpc` | hourly DAM MCPC per product (v3+) | NP4-188-CD **[data]** | as `dam_spp` |
| `rt_mcpc`, `rt_mcpc_15` | post-RTC+B RT MCPC per SCED and per settlement interval (v3+) | NP6-332-CD, NP6-331-CD **[data]** | interval end + 1 / + 2 min |
| `asdc` | post-RTC+B AS demand curves per hour, (MW, $/MW/h) points (v3+) | NP4-212-CD **[data]** | `posted.asdc[date]`, default D-1 06:00 |
| `system.prc_mw` | pre-RTC+B archived PRC (`real`); post-RTC+B a proxy from NP6-323-CD/NP6-328-CD/MCPCs (`proxy`) | NP6-792-ER **[data]** / **[modelled]** (D12) | interval end + 1 min |
| `system.lambda`, `load_mw`, `wind_mw`, `solar_mw` | system lambda and actual load/wind/solar on the 5-min grid | NP6-323-CD, NP6-345-CD, NP4-732/737-CD **[data]** | interval end + 1 min |
| `forecasts` | each as-issued vintage of ERCOT's load/wind/solar forecasts (system; zone optional), hourly values from `start` | NP3-565-CD, NP4-732-CD, NP4-737-CD **[data]** | `issued_at` |
| `outage_capacity` | as-issued resource outage capacity, hourly | NP3-233-CD **[data]** | `issued_at` |
| `desk_forecast` | the desk's P10/P50/P90 price forecast vintages (DAM SPP hourly; RT SPP 15-min or hourly) built only from data public at `issued_at` | data lane model **[modelled]** | `issued_at` |
| `unit_events` | the site's forced outages and derates, replayed | NP1-346-ER **[data]** | `start` (telemetry) |
| `notices` | ERCOT notices (v2 notice shape) | ERCOT notices archive **[data]** | `issued_at` |
| `nws` | NWS alerts for the site's region | NWS **[data]** | `issued_at` |
| `deployments` | AS deployment events (v3+) | notices / reg drift archive **[data]**/**[modelled]** | `start` |
| `operator` | the real operator's disclosed bids, awards and SoC (1.5) | NP3-966-ER, NP3-965-ER, NP3-991-EX **[data]** | never |

Requirements on the data lane:
- `desk_forecast`: at least one `dam` vintage issued at or before D-1 06:00 covering every hour of each operating day
  it prices, and `rt` vintages issued at least hourly from D-1 06:00 to the last operating day 23:00, each covering
  from its `issued_at` hour to the end of the last operating day. `step_min` is 60 or 15. Core picks the latest vintage
  with `issued_at` ≤ now. When the series has no `desk_forecast`, core uses its fallback `naive` model (8.4), labelled
  as such.
- `forecasts` vintages: hourly postings from D-1 00:00 to the last operating day 23:00 are enough; horizons may be cut
  at the end of the last operating day + 24 h.
- History: `dam_spp`/`dam_spp_hub` for D-7..D-1 and `rt_spp`/`rt_lmp` for D-1 (the desk's look-back).

### 1.5 Operator disclosures (`operator`)

```json
{"resource": "BATCAVE_ESR1", "qse": "QSUE74",
 "dam": {"<date>": {"curves": [[[-100.5, -20.0], [0, 15.0], [0, 40.0], [100.5, 300.0]], "...24 hours, null when none..."],
                    "award_mw": [24], "spp": [24],
                    "pre": {"offer": [24 curves | null], "bid": [24 curves | null],
                            "offer_award_mw": [24], "bid_award_mw": [24]}}},
 "sced": {"<date>": {"curves": [{"t": "ISO of the SCED run", "points": [[-100.5, -20.0], "..."]}],
                     "base_point_mw": [288], "telemetry_mw": [288], "soc_mwh": [288],
                     "hsl_mw": [288], "lsl_mw": [288], "status": [288]}},
 "cop": {"<date>": {"hbsoc_mwh": [24], "min_soc_mwh": [24], "max_soc_mwh": [24], "hsl_mw": [24], "lsl_mw": [24],
                    "status": [24]}}}
```

Post-RTC+B `curves` are the single-model EB/OC (P§4.4.9.7.1). Pre-RTC+B `dam.curves` is null and `pre` holds the Gen
Resource offer (MW ≥ 0) and the Load Resource / node DAM energy bid (MW ≥ 0 consumed, price non-increasing); SCED
`curves` hold the gen offer as `points` and the load bid as `bid_points`. SCED `curves` list only runs where the curve
changed. `telemetry_mw` is the SCED telemetered net output, `soc_mwh` the telemetered SoC, both mapped to the 5-min grid.

---

## 2. Clock and event model

### 2.1 Time

- One episode covers **D-1 06:00 → last operating day 24:00** (v2/v3/v5: −1080 → 1440; v4: −1080 → 4320). The agent
  trades the DAM for each operating day on the day before and runs the battery in real time on every operating day.
  D-1's own real-time operation is outside the episode; the battery enters D0 at `soc0_mwh`.
- Time is frozen while the agent works. It moves only between turns (waiting = ending the turn; no advance tool).
- Shown to the agent as `"Fri 02-13 10:00"` (CPT, 24 h); accepted in tool arguments as that, as `"D0 14:35"`,
  `"D-1 10:00"`, `"14:35"` (the current operating day context, see 3.1), or an ISO timestamp.
- Operating hours are **HE01..HE24** (hour ending); HE h covers minutes [60(h−1), 60h) of its day.

### 2.2 Milestones (post-RTC+B and pre-RTC+B unless marked)

| Time (CPT) | Milestone | Wakes the agent | Effect in the env |
|---|---|---|---|
| D-1 06:00 | `start`: AS Plan, ASDCs (post), 7-day load forecast posted; DAM open | yes | episode starts |
| D-1 10:00 | `dam_close` (P§4.4.7.1) | no (a deadline shown from `start`) | DAM submissions for D close; curves for D freeze until DAM results |
| D-1 13:30 | `dam_results` (P§4.5.2): awards, DASPPs, MCPCs posted | yes | DAM cleared at 10:00, published at `posted.dam` |
| D-1 14:30 | `druc`: DRUC snapshot of the COP (P§5.3) | no (inbox) | COP snapshot stored (v3 capacity-short uses it) |
| D-1 18:00 | `adjustment_open` (P§6.3(2)) | yes | RT offers for D accepted from now |
| every hour | `hruc` (P§5.1) | no (inbox) | HRUC never commits an ESR (Battery Overview slide 26) |
| T-60 for each HE T | adjustment period for T closes | no | COP for T frozen; pre-RTC+B the charging bid for T freezes |
| D 00:00, 06:00, 12:00, 18:00 | `checkpoint` (desk shift checkpoints) | yes | none |
| any minute | `notice`, `nws` (Warning/Watch only), `deployment` (v3+), `outage` (unit event start/end) | yes | delivered at the real minute |
| agent-chosen | `reminder` (`set_reminder`) | yes | delivered at that minute |
| last day 24:00 | `end` | no | final settlement and grade |

Multi-day (v4): `start`, `dam_results`, `adjustment_open` recur on each day before an operating day (D0 06:00 for
D1's DAM, etc.), and the checkpoints recur each operating day. Each wake carries every reason due at that minute.

Forecast postings (hourly, HH:30 load and HH:55 wind/solar) and DAM/RT price postings never wake the agent; they are
data the next wake-up can read (C-D2).

### 2.3 Turns, calls and reminders

- A **turn** is the agent's work at one wake-up: any number of tool calls up to `calls_per_turn`, ended by a message
  without tool calls. Budgets (v2): `max_turns` 40, `calls_per_turn` 12, `max_reminders` 8 pending.
- Calls beyond `calls_per_turn` return an error (`budget: end your turn`) without effect and do not count.
- When the turns are used up, later wake-ups do not wake the agent; standing offers and the COP stay in force and the
  market runs to the end. The wake message always shows `turns_left`.
- Reminders: at a 5-minute boundary strictly after now and before the episode end; a reminder at the same minute as a
  milestone merges into it. `set_reminder` with `at` already queued replaces its note.
- Wake message (the user message the runner sends):

```json
{"now": "Fri 02-13 13:30", "reasons": ["dam_results"],
 "events": [{"t": "Fri 02-13 13:14", "kind": "dam_results", "text": "DAM results for Sat 02-14: awarded 6 of 24 hours, net +212.4 MWh, $9,812"}],
 "deadlines": [{"what": "COP for HE01 Sat 02-14 freezes", "at": "Fri 02-13 23:00"}],
 "budget": {"turns_left": 37, "calls_per_turn": 12}}
```

### 2.4 Hook and gateway contract

- `Session.next_wakeup()` → `{"at": <minute> | null, "at_utc": "...Z", "reasons": [...]}`: the env's own next wake
  (milestones, events, reminders). The post-turn hook calls it through the hidden `next_wakeup` tool (role `hook`), takes
  the earlier of it and the gateway's `next_event_at`, advances the frozen clock and wakes the agent with the reasons.
- `Session.advance_to(minute)` runs the market forward to `minute` (DAM clearing, SCED intervals, settlement postings,
  event delivery) and returns the wake (`reasons`, `events`) due at `minute`, or `null` when nothing wakes the agent.
  The env server calls it when the gateway clock moves; the runner calls `advance_to(next_wakeup()["at"])`.

---

## 3. Tools

Eleven agent tools plus the hidden `next_wakeup`. Every output is a JSON object of at most ~2,500 characters at its
default arguments; series longer than the cap are aggregated (5 min → 15 min → hourly) and say so in `step`. Every
output carries `"now"`. Errors are `{"error": "<code>: <text>"}`. AS fields are present only from v3.

### 3.1 Common arguments

- `day`: `"D0"`, `"D1"`, `"D-1"` or an ISO date; default: the operating day in progress, or D0 before it starts.
- `start`, `end`: times (2.1) or hours `"HE07"`; defaults per tool.
- `hours`: `"HE07-HE10"`, `"HE07"`, `"all"`, or a list of integers 1..24.

### 3.2 Read tools

| Tool | Arguments | Returns |
|---|---|---|
| `get_prices` | `market`: `dam|rt|sced|as_dam|as_rt` (default `rt`), `point`: `node|hub` (default `node`), `day`, `start`, `end`, `step`: `5m|15m|1h` | posted prices only: `{"market","point","unit","step","start","values":[...],"stats":{"min","max","mean"}}`; `dam` = DAM SPP hourly; `rt` = RT SPP 15-min; `sced` = 5-min LMP; `as_*` per product (v3) |
| `get_forecasts` | `kind`: `price|load|wind|solar|net_load|outages|weather` (default `price`), `market` (`dam|rt`, for price), `day`, `vintage`: `latest` or a time (any issued ≤ now), `step` | as-issued: `{"kind","issued_at","model","step","start","values"}`; `price` gives `p10/p50/p90` and `"label":"modelled desk forecast"`; `weather` lists NWS alerts in force |
| `get_grid_conditions` | `start`, `end` (default last 2 h) | `{"prc_mw":{"last","min_2h","kind"},"lambda":{...},"load_mw","wind_mw","solar_mw","eea_level","notices_in_force":[...]}` |
| `get_asset_status` | — | `{"status","soc_mwh","min_soc_mwh","max_soc_mwh","hsl_mw","lsl_mw","last_base_points":[last 6],"metered_mw","outage":null|{...},"cycles_today","rte","standby_loss_pct_per_h","deg_usd_per_mwh","warranty_cycles_per_day"}` |
| `get_position` | `day`, `detail`: `summary|hourly` (default `summary`) | DAM awards, RT net, standing curves (compact), COP rows, and the running statement of settled intervals: `{"dam":{...},"rt":{...},"cop":[...],"statement":{lines},"pnl_to_date"}` |

### 3.3 Submission and analytics tools

| Tool | Arguments | Returns |
|---|---|---|
| `submit_dam_offers` | `day`, `curves`: `[{"hours": "...", "points": [[mw, price], ...]}]`; pre-RTC+B `{"hours", "offer": [...], "bid": [...]}`; v3+: `as_offers` | per hour accepted/rejected with codes; accepted curves replace that hour's curve (overwrite only the hours given) |
| `submit_rt_offers` | `day`, `curves` (as above); v3+ `as_offers` | as above; post-RTC+B effective from the next SCED run; pre-RTC+B the `bid` side only for hours whose adjustment period is open |
| `update_cop` | `day`, `rows`: `[{"hours", "status"?, "hsl_mw"?, "lsl_mw"?, "hbsoc_mwh"?, "min_soc_mwh"?, "max_soc_mwh"?}]` (v3+: `as_capability`) | per hour accepted/rejected; fields not given keep their values |
| `check_submission` | `kind`: `dam|rt|cop`, `payload` (the arguments of the matching submit tool) | dry run: `{"ok","errors":[{"hour","code","text"}],"warnings":[...]}` plus `"would_clear"` for `dam` against the latest desk P50 |
| `optimize` | `price_view`: `"desk"` or `{"dam": [24 per day] , "rt": [96 per day], "scenarios": [{"name","weight","dam","rt"}]}`, `risk` 0..1 (default 0.5), `constraints`: `{"end_soc_mwh"?, "max_cycles"?, "hours"?, "day"?}` | `{"dam_curves","rt_curves","cop","schedule":{"hourly_mw","hbsoc_mwh"},"projected":{"pnl","dam","rt","degradation"},"basis":"..."}` — proposals only, never submitted; `dam_curves` for hours whose DAM is open, `rt_curves` for hours whose adjustment period is open, at most the next 12 |
| `set_reminder` | `at`, `note` (≤ 120 chars) | `{"ok", "at", "pending": n}` |

`optimize` sees only the price view the agent passes (`"desk"` means the latest desk forecast the agent can read), the
battery's current state, its own positions and the rules; never unposted prices.

Hidden: `next_wakeup` (role `hook`) → 2.4.

---

## 4. Submissions and validation

`check_submission` and the submit tools run the same validator. A rejected hour keeps its previous valid curve
(P§4.4.9.7(5)). Codes:

### 4.1 Post-RTC+B ESR Energy Bid/Offer Curve (P§4.4.9.7.1, MSVR NP4-450 redline) **[rule]**

| Code | Rule |
|---|---|
| `EBOC-01` | 2..10 price/MW points |
| `EBOC-02` | MW non-decreasing and price non-decreasing along the curve (from max charge, negative MW, to max discharge) |
| `EBOC-03` | no more than two consecutive points at the same price, nor at the same MW |
| `EBOC-04` | price in [−$250, DASWCAP $5,000] in the DAM; [−$250, RTSWCAP $2,000] for RT submissions (P§4.4.11) |
| `EBOC-05` | MW within the site's nameplate [lsl_mw, hsl_mw]; beyond the COP/telemetered limits is a warning (`EBOC-W1`): the market bounds it (P§4.4.9.7(2)) |
| `EBOC-06` | DAM: the operating day's DAM is open (before 10:00 of the day before); RT: the hour has not ended and its adjustment period has opened (18:00 of the day before) |
| `EBOC-07` | hours parse and lie in 1..24 |

A curve whose range does not include 0 MW is extended to 0 at the nearest point's price (RTCBTF "DAM ESR Offers"). An
accepted DAM curve for hour h is also the RT curve for h until an RT curve replaces it (P§4.4.9.7: one curve used by
DAM, RUC and SCED). With no curve at all, SCED uses ERCOT's proxy EB/OC: −$250 for the charging range, RTSWCAP for
the discharging range (P§4.4.9.7(7)). Self-schedule = a curve priced at the floor or cap.

### 4.2 Pre-RTC+B combo model (pre-P§4.4.9.3, pre-P§4.4.9.6.1, pre-P§6.4.3.1) **[rule]** / **[simplified]**

| Code | Rule |
|---|---|
| `GOC-01..04` | Gen Resource Energy Offer Curve: 2..10 points, MW ≥ 0 increasing, price non-decreasing, price in [−$250, SWCAP] (SWCAP $5,000 from 2022, $9,000 before) |
| `LRB-01..04` | Load bid (DAM energy bid at the node / RTM Energy Bid): 1..10 points, MW ≥ 0 increasing (consumption), price non-increasing, price in [−$250, SWCAP] |
| `LRB-05` | the RT charging bid for HE T is frozen once T's adjustment period ends (T−60) |
| `GOC-05` | MW ≤ hsl_mw; bid MW ≤ −lsl_mw |

The offer and the bid belong to two Resources, so a frozen bid in an RT item that also carries an offer rejects only
the bid (`LRB-05`) and accepts the offer. **[simplified]** With no RT load bid, the DAM bid carries into RT; with none at all the battery does not charge (no
VOLL proxy). With no RT gen offer the DAM offer carries; with none the battery does not discharge.

### 4.3 COP (P§3.9.1) **[rule]**

| Code | Rule |
|---|---|
| `COP-01` | `status` in ON, ONOS, ONTEST, ONEMR, ONHOLD, OUT (post); ON, OUT, ONTEST, ONEMR (pre) |
| `COP-02` | e_min ≤ MinSOC ≤ HBSOC ≤ MaxSOC ≤ e_max (P§3.9.1(17)) |
| `COP-03` | HBSOC of consecutive hours reachable at max charge/discharge rate (P§3.9.1(3)), with η applied |
| `COP-04` | lsl_mw ≤ LSL ≤ HSL ≤ hsl_mw |
| `COP-05` | hour still editable: before T−60 (MSVR) |

Default COP at start: ON, site limits, MinSOC/MaxSOC = nameplate, HBSOC flat at soc0 (flagged `COP-W2`, flat HBSOC).
Effects in v2: status OUT or ONHOLD → the battery is not dispatched (SCED, P§4.4.9.7(3); ONHOLD "not charging or
discharging"); COP HSL/LSL bound the DAM award; the DRUC snapshot is stored. HBSOC and AS capability matter from v3.

### 4.4 Outage compliance

On a forced outage or derate the agent should update the COP within 60 minutes (P§3.1.4.7, P§6.4.8). Telemetry and
SCED limits follow the event immediately regardless. A late or missing COP update is counted (`compliance.cop_late`),
not charged.

---

## 5. Clearing (price-taker everywhere through v4; D6)

### 5.1 Curve evaluation

A curve is piecewise linear between its points. For price p the cleared MW is
`q(p) = max{q ∈ [q_1, q_n] : price(q) ≤ p}` with `price(q)` the linear interpolation, and `q(p) = q_1` when p < p_1.
(Discharge when the price is at or above the offer; charge when the price is at or below the bid.) Pre-RTC+B the net
is `offer(p) − bid(p)` with `bid(p) = max{q : bid_price(q) ≥ p}` (0 when none).

### 5.2 DAM (hourly)

At `dam_close` each hour h of the operating day clears at the node DASPP_h: award `a_h = clip(q_h(DASPP_h), LSL_h,
HSL_h)` with the COP limits at the close; hours with no curve award 0. The DAM ignores SoC (Battery Overview slide 23)
and COP status for EB/OCs (P§4.4.9.7(3)) **[rule]**. Results are visible at `posted.dam` (default 13:30).

### 5.3 RT (5-minute SCED)

For each 5-minute interval k of an operating day, SCED runs at the interval start with the curve in force then
(submissions at time t apply to intervals starting at or after t):
1. desired `x = q_h(k)(LMP_k)` (the real node LMP of interval k);
2. limits: ramp `BP_{k−1} ± 5·ramp` (soft: an outage overrides it), telemetered `[LSL, HSL]` = the unit-event limits
   intersected with the hour's COP HSL/LSL, and SoC `[−12·(MaxSOC − drift(SoC))/η_c, 12·η_d·(drift(SoC) − MinSOC)]`
   with the hour's COP MinSOC/MaxSOC (P§6.5.7.2(4)-(5), P§6.5.7.3(1)); the QSE is taken to telemeter its COP limits
   (C-D9) **[simplified]**;
3. base point `BP_k` = x clipped to the ramp window, then to [LSL, HSL], then to the SoC window; status OUT/ONHOLD → 0.

Telemetry = base point (perfect set-point following) except during a unit event that starts inside the interval, when
the metered MW is the time-weighted mix (the deviation then settles under 7.3). **[simplified]** LMP_k is the real
posted price (price-taker; D6).

---

## 6. Physics (5-minute)

- `SoC_{k+1} = drift(SoC_k) + (η_c·c_k − d_k/η_d)/12` with `drift(S) = e_min + (S − e_min)·(1 − ℓ)^(1/12)`,
  `c_k = max(−m_k, 0)`, `d_k = max(m_k, 0)` from metered MW m_k, ℓ = standby_loss_pct_per_h/100 (standby losses apply to
  the energy above nameplate MinSOC, so an idle battery never drifts below it). η_c = η_d = √rte. **[modelled]**
- MinSOC ≤ SoC ≤ MaxSOC always holds (SCED limits in 5.3 guarantee it; asserted).
- Unit events: forced outage sets HSL = LSL = 0 for [start, end); a derate sets HSL/LSL to the event's values. **[data]**
- Ramp: |BP_k − BP_{k−1}| ≤ 5·ramp_mw_per_min.
- Cycles: discharged MWh / (e_max − e_min) per operating day.

---

## 7. Settlement (D10)

Lines are per operating day, + = paid to the QSE, in $. Interval i is 15 minutes (three SCED intervals); `m_i` is the
average metered MW, `DA_h(i)` the DAM award of the hour holding i.

| Line | Formula | Basis |
|---|---|---|
| `dam_energy` | Σ_h DASPP_h · a_h | P§4.6.2.1-4.6.2.2 (DAESAMT/DAEPAMT signs flipped to + = credit) **[rule]** |
| `rt_energy_imbalance` | Σ_i RTSPP_i · (m_i − DA_h(i)) / 4 | P§6.6.3.1 **[rule]**; charging energy priced at the node RT SPP rather than the WSL bus price RTRMPRESR **[simplified]** |
| `set_point_deviation` (post) / `base_point_deviation` (pre) | per interval, AASP = mean BP; over: tolerance max(3%·|AASP|, 3 MW), charge `max($20, RTSPP)·OPESR`; under: tolerance min(3%·|AASP|, 3 MW), charge `−min(−$20, RTSPP)·UPESR`; OPESR/UPESR = MWh beyond tolerance | P§6.6.5 **[rule]**; pre: 5% / 5 MW, same form **[simplified]** |
| `load_allocated` | 0: charging metered as Wholesale Storage Load is exempt (P§2 WSL; 16 TAC §25.501(m)) | **[rule]** |
| `dam_as_capacity`, `rt_as_imbalance`, `as_only_buyback` | v3+ (P§4.6.4, P§6.7.2.x) | **[rule]** |
| `capacity_short`, `failure_to_provide` | v3+: post RUC capacity-short (P§5.7.4.1); pre failure-to-provide (pre-P§6.7.3) | **[simplified]** |
| `degradation` | −deg_usd_per_mwh · discharged MWh | **[modelled]**, a separate labelled line |
| `warranty_overage` | −2·deg_usd_per_mwh · discharged MWh beyond warranty_cycles_per_day·(e_max − e_min) per day | **[modelled]** |
| `end_soc_shortfall` | −max(0, target − SoC_end)·max(mean DASPP of the last day, $20)/η_c; target = the end SoC of the idle path from soc0 (standby losses only) | **[modelled]** (values stored energy; no credit above target) |

Scarcity pricing is inside the posted prices (pre: ORDC adders in RT SPP; post: ASDC-priced LMP/MCPC); no separate
adder line. Statements post at OD+2 BD (DAM) and OD+5 (RT initial) in reality; the env shows each settled interval in
`get_position` once its RT SPP posts, labelled "shadow settlement". **P = Σ lines.**

---

## 8. Optimiser (D7; `gridsim_core.desk.optimize`, HiGHS)

One LP serves `optimize`, the anchor and the hindsight optimum.

### 8.1 LP

Horizon: from now (next 5-min boundary) to the episode end, 5-minute steps k. Inputs: DAM price path for each hour
whose DAM is still open, RT price path (per 5 min; a 15-min or hourly path is repeated), current SoC and
limits/outages known now, awarded DAM positions (fixed), site parameters.

```
max  Σ_h dam_h·q_h + Σ_k rt_k·(d_k − c_k − q_h(k))/12 − deg·Σ_k d_k/12 − 2·deg·w − pen·u − ε·Σ_h |q_h − n_h|
s.t. s_{k+1} = s_k·ρ + (η_c·c_k − d_k/η_d)/12            (ρ = (1 − ℓ)^(1/12))
     MinSOC ≤ s_k ≤ MaxSOC;   0 ≤ d_k ≤ HSL_k;   0 ≤ c_k ≤ −LSL_k;   d_k/HSL + c_k/(−LSL) ≤ 1
     LSL ≤ q_h ≤ HSL (open DAM hours; else fixed);   n_h = mean_k∈h (d_k − c_k)
     Σ_{k∈day} d_k/12 − w_day ≤ warranty·(e_max − e_min);   s_end + u ≥ target
```

`pen` is the 7 `end_soc_shortfall` price. The ε term ties the DAM position to the physical plan when the view has no
DA/RT spread.

### 8.2 Curves from the plan

Water value λ_k = dual of the SoC balance at k. For hour h with scenario duals λ_h^s (hour mean) and the risk band
`lo = λ^P50 − risk·(λ^P50 − min_s λ^s)`, `hi = λ^P50 + risk·(max_s λ^s − λ^P50)`:
- RT curve: `[(LSL, η_c·lo), (0, η_c·hi), (0, lo/η_d + deg), (HSL, hi/η_d + deg)]`, prices clipped to [−250, 2000],
  made monotone and reduced (no more than two equal neighbours); λ^P50 is the median scenario's value. Charging is
  linear in price between η_c·lo and η_c·hi, discharging between lo/η_d + deg and hi/η_d + deg.
- DAM curve: the same prices with MW capped to the scenario envelope of the planned hourly net (`max_s n_h^s` for
  discharge, `min_s n_h^s` for charge), so the DAM is not oversold beyond the plan.
- COP: HBSOC = planned SoC at each hour start; status ON; limits unchanged.

### 8.3 Scenarios

`price_view: "desk"` uses the latest desk vintages: scenarios P10 / P50 / P90 with weights 0.25 / 0.5 / 0.25 (each
a full path). A custom view gives its own paths; one path = deterministic (`lo = hi`).

### 8.4 Desk price forecast hook

`gridsim_core.desk.forecast.DeskForecaster` protocol: `vintage(market, now) -> Vintage | None` (latest issued ≤ now),
where `Vintage(market, issued_at, start, step_min, p10, p50, p90, model)` in minutes. `SeriesForecaster` reads the
series' `desk_forecast`; `NaiveForecaster` (fallback, labelled `naive`) uses only posted data: DAM P50 = the latest
posted DAM day by hour; RT P50 = the operating day's DAM SPP once posted, else the DAM P50; P10/P90 = P50 ∓ the
hour's mean absolute deviation over the posted history days (minimum $5).

---

## 9. Grading and references (D-reward contract as v1–v5)

### 9.1 Reward

- **No valid action → R = 0**: an episode with no accepted `submit_dam_offers` or `submit_rt_offers` scores 0.
- `R = clip(0.2 + 0.8·(P − P_idle)/den, 0, 1)` with **den = max(P_anchor − P_idle, 0.1·(P_hind_phys − P_idle))**
  (`desk.refs.desk_reward`; approved 2026-10-28). Reason: a single-day information-matched anchor can lose money on real
  days (DATA's desk-v2-eval had P_anchor < P_idle on 10 of 32 tasks under the first anchor), and the old degenerate rule
  then turns R into a 0/1 step that pays an idle-but-valid agent 1.0. When den is still ≤ 0 (a flat day) the
  degenerate rule of `grade.reward_value` applies. `floored: true|false` is recorded in every task's refs and every
  grade; `desk_run --refs-only` prints the floored tasks and writes them to `refs-report.json` (and, with
  `--manifest`, to the pack's manifest). The floor only guards the denominator; the anchor's settings come from the
  tune pack (9.3).
- `C = (P − P_idle)/(P_hind − P_idle)` (hindsight capture, reported; the board headline as in v2–v5).
- Training stretch S (`grade.stretch_value`) as v2–v5.

### 9.2 References (all settled by the same clearing, physics and settlement code)

| Ref | Policy |
|---|---|
| `idle` | submits a 0 MW curve for every hour at `start` and nothing else. P_idle = 0 by construction (the end target is the idle path) |
| `anchor` (information-matched) | at every wake-up except reminders (milestones, notices, outages, deployments), calls `optimize(price_view="desk", risk=0.5)` and submits its DAM curves (while the DAM is open), RT curves (once the adjustment period opens) and COP. The same desk forecast vintages the agent can read |
| `hind` | the 8.1 LP with the real DASPP and the real RT SPP (the settlement price; each 15-min value on its three SCED intervals), all DAM hours open at start, unit events known; its net dispatch is then run through the physics (net MW, SoC-clipped) and settled: the rules-bound optimum (includes DA/RT spread positions within [LSL, HSL]) |
| `hind_phys` | the physical optimum without DAM/RT spread positions: max of the LP with no DAM energy position (pure RT) and the LP with q_h = n_h (DAM position = its own dispatch), each executed and settled on its own (`p_hind_rt_only`, `p_hind_tied`) |
| `operator_replay` | the operator's disclosed DAM curves and SCED curves (1.5) through our clearing, physics and settlement from soc0 |
| `operator_actual` | the operator's disclosed DAM awards and telemetered output settled directly (their own SoC path) |

`refs` in the task row: `{"p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual",
"anchor": {"statement", "turns"}, "hind": {"dam_mw": [...], "rt_mw_15": [...]}, "core_version", "series_sha"}`. Core
recomputes the anchor at grade time when `refs` is missing or its `series_sha` differs.

---

## 10. Version layers, packs and metrics

| Layer | Adds | Tools changed | Settlement added |
|---|---|---|---|
| v2 "The Live Grid" | energy only; DAM + RT; events and notices; both eras | AS fields absent | 7 energy lines |
| v3 "Sun, Storage and Reserves" | five AS products DAM and RT; RT AS offers or ERCOT proxies; AS duration SoC rules (Reg 0.5 h, RRS 0.5 h (FFR 0.25 h), ECRS 1 h post / 2 h pre, Non-Spin 4 h); deployments; PV option | `as_offers`, COP `as_capability`, `get_prices` `as_*` | AS lines, capacity-short / FTP |
| v4 "Weather Front" | three operating days; DAM per day; as-issued vintages central | `day` everywhere | per-day statements |
| v5 "The Market Floor" | DAM price impact: re-clear against the 60-day disclosed offer stack (`gridsim_core.market` reuse); RT price-taker | — | DAM at the re-cleared price |

Packs: `fixtures` (CI), `desk-v{N}-pilot` (2 battery-days, post-RTC+B), `desk-v{N}-eval` (post-RTC+B, ≥ 60 days old,
`operator_ok`), `desk-v{N}-pre` (pre-RTC+B smoke and training). Metrics per run: R, C, P and its lines, P − P_anchor,
beats-anchor, vs operator (P − P_operator_replay), turns used, calls, submissions accepted/rejected by code, reminders,
cycles, SPD MWh, cop_late, cost and tokens.

---

### 9.3 The anchor's setting (pre-registered procedure, chosen 2026-10-28 on `desk-v2-tune`)

Procedure (pre-registered before any scored run): grid risk {0.5, 0.75, 1.0, 1.25, 1.5, 2.0} × DAM basis {physical,
spread}; pick the highest total anchor P on `desk-v2-tune` (12 post-RTC+B battery-days, 3 per site, Jan–Aug 2026,
disjoint from pilot and eval); if the best comes with a large single-day loss, take the runner-up when its total is
within 5%. No eval or model result was looked at.

| risk | DAM basis | total anchor P ($, 12 days) | worst single day ($) |
|---|---|---|---|
| 0.5 | physical | 4,766 | -5,433 |
| 0.5 | spread | -5,753 | -48,783 |
| 0.75 | physical | 6,692 | -5,200 |
| 0.75 | spread | 401 | -32,291 |
| 1.0 | physical | 3,361 | -4,911 |
| 1.0 | spread | 1,992 | -22,329 |
| 1.25 | physical | 5,797 | -4,719 |
| 1.25 | spread | 20,813 | -6,421 |
| 1.5 | physical | -3,233 | -4,189 |
| 1.5 | spread | 15,843 | -4,962 |
| 2.0 | physical | -2,458 | -2,679 |
| 2.0 | spread | 11,240 | -3,376 |

**Chosen: risk 1.25, DAM basis "spread"** (`policies.RISK`, `policies.DAM_POSITION`; recorded in every refs block as
`anchor_setting`). Runner-up 1.5/spread totals $15,843, 24% below, so the 5% rule does not apply; the chosen
setting's worst day is −$6,421. On the tune days the anchor makes $20,813 against the physical hindsight's $67,847 and
the operators' own −$2,766. Refs at this setting: tune 9 of 12 floored, pilot 0 of 2, eval 13 of 32 (8 eval days
with P_anchor < 0); the eval anchor's total ($3.79M) exceeds the physical hindsight ($2.03M) because the spread basis
wins large DAM/RT spreads on the scarcity days, so R on those days rewards matching a spread position.

**v3 (same procedure, the v3 layer played on the same `desk-v2-tune` days, AS included):**

| risk | DAM basis | total anchor P ($, 12 days) | worst single day ($) |
|---|---|---|---|
| 0.5 | physical | 10,283 | -14,920 |
| 0.5 | spread | 25,089 | -47,761 |
| 0.75 | physical | 24,577 | -4,712 |
| 0.75 | spread | 37,316 | -31,686 |
| 1.0 | physical | 33,117 | -1,789 |
| 1.0 | spread | 49,943 | -17,282 |
| 1.25 | physical | 37,244 | -1,578 |
| 1.25 | spread | 62,500 | -1,826 |
| 1.5 | physical | 39,648 | -1,077 |
| 1.5 | spread | 67,526 | -1,323 |
| 2.0 | physical | 32,545 | -853 |
| 2.0 | spread | 54,845 | -1,133 |

**Chosen for v3: risk 1.5, DAM basis "spread"** (runner-up 1.25/spread $62,500, 7.4% below; worst day −$1,323).
The tune days carry real DAM/RT MCPCs and ASDCs but no deployment series (`deployments` empty, no `reg_deploy` and no `as_plan`, so proxy AS offers sit at $1,999.99 and
regulation energy uses the labelled 0.17/0.20 fractions): the v3 pick is made without deployments. The tune days are
disjoint from every v3 eval day.

**v4 and v5 (pre-registered 2026-10-28, before any v4/v5 refs):** no separate tune packs (the ERCOT API is the
bottleneck); both reuse the v3 pick, risk 1.5 / spread — v4 is the v3 rules over three days and v5 the v3 rules plus
the DAM re-clear. Settings live per layer in `policies.SETTINGS` (`policies.setting(layer)`) and every refs block
records `anchor_setting`. If the re-clear makes the spread anchor lose heavily on the v5 pilot refs, that is reported
before the v5 pilot runs; the setting is not changed without approval.

### 10.1 v3 "Sun, Storage and Reserves" as built (`gridsim_core.desk.ancillary`; desk-research.md sections cited)

**Series fields (DATA, in addition to 1.4):** `as_plan` {date: {product: [24]}} (AS Plan MW, optional; proxy floor),
`reg_deploy` {date: {"up": [24], "dn": [24], "source": "measured|modelled"}} (fleet deployed fraction of Reg awards,
from `data/hybrid/reg_deploy` via `hybrid_inputs.reg_hourly`), `deployments` (data/hybrid/deployments shape:
product rrs|ecrs|nspin, start, end, frac or null = 1), `pv` {date: [288]} and `forecasts` kind `pv` (modelled),
`desk_forecast` markets `as_dam` / `as_rt` with a `product` key, and the operator's AS: `dam[date].as_offers`
{product: [24 x blocks]}, `dam[date].as_awards`, `sced[date].as_awards`, `sced[date].as_offer_updates`
[{t, product, blocks}], `cop[date].as_capability`. Operator product keys rrspfr/rrsffr (rrs_pfr/rrs_ffr accepted).

**Products.** regup, regdn, rrspfr, rrsffr, ecrs, nspin (price keys regup, regdn, rrs, ecrs, nspin). ESRs offer no UFR,
off-line reserves or ECRS-MD (§2c, "RTC+B DAM Changes" slide 10); ECRS exists from 2023-06-10. The 20% RRS-PFR share
of ESR training slide 13 (§4a) is **not** applied: P§3.18(3)(a) makes the PFR limit resource-specific (droop-based) and
the disclosures show ESR PFR awards above 20% (CROSSETT_ESR1 85 MW of a 196 MW range, 2026-04-20); every product is
capped at HSL − LSL.

**AS offers** (`as_offers` on `submit_dam_offers` / `submit_rt_offers`): per hour and product, 1..5 blocks [mw, $/MW/h]
(`blocks`, the same each hour) or one block per hour (`mw` + `price` lists). Codes: ASO-01 product, ASO-02 shape, ASO-03
block < 0.1 MW, ASO-04 price outside [0, cap] (DAM: DASWCAP $5,000 post / SWCAP pre; RT: RTSWCAP $2,000), ASO-05 MW
above the range or the PFR share, ASO-06 window (DAM before its close; RT post-RTC+B from 18:00 D-1 to the hour's end; no
RT AS market before RTC+B), ASO-07 hours (§3, P§4.4.7.2.1). An accepted DAM AS offer is also the RT offer until an RT
offer replaces it ("Market Submission Changes" slide 2).

**DAM clearing.** Per hour, energy and AS are co-cleared price-taker against the node DASPP and the DAM MCPCs: the LP
maximises the offers' surplus with energy + up-AS ≤ HSL and energy − RegDn ≥ LSL (COP limits; P§3.18, P§4.5.1(4)(c)(iii));
the DAM ignores SoC (§2b, §4a). With no AS offers the energy award is exactly 5.2's.

**RT, post-RTC+B.** Every 5-minute SCED co-clears energy and AS against the node LMP and the RT MCPC (per SCED, NP6-332)
with the offers in force per product: RT, else DAM, else ERCOT's linked proxy offer (MW = HSL − LSL, PFR 20%; price
min($2,000, ASDC at 95% of the AS Plan) − $0.01, or the highest submitted price if higher; $1,999.99 without an AS Plan,
**[simplified]**) (§2d, P§6.5.7.3(5)). Constraints: headroom as in the DAM; COP `as_capability` caps; SoC: Σ up awards ×
duration + 5-min discharge ≤ (SoC − MinSOC)·η, RegDn × duration + 5-min charge ≤ (MaxSOC − SoC)/η, durations Reg 0.5 h,
RRS 0.5 h, FFR 0.25 h, ECRS 1 h, Non-Spin 4 h (NPRR1282, §4a). The exact SCED SoC algebra is not public; this is our
form **[modelled]**.

**RT, pre-RTC+B.** No RT AS market: the DAM AS awards are the hour's physical responsibility (§2d). SCED holds the
headroom and, from 2024-06-27 (NPRR1186), SoC for responsibility × the time left in the hour (FFR 0.25 h) (§4a);
qualification durations (Reg/RRS 1 h, ECRS 2 h, Non-Spin 4 h; D11) are what the prompt states. Responsibility that
headroom or SoC cannot hold is recorded per interval as `as_short`.

**Deployments.** Regulation: each interval the battery moves RegUp × f_up − RegDn × f_dn MW, with the hour's fleet
fractions from `reg_deploy` (measured from 2023-10-12, else the labelled fallback; without the series 0.17/0.20,
**[modelled]**); part of the set point, so no deviation charge. RRS/ECRS/Non-Spin: during a deployment event the award
of that product × frac is added to the base point (ECRS energy is in the base point, P§6.5.7.6.2.4(6)); delivery that
SoC or limits cut is recorded as `deploy_short` (post: compliance only, P§8.1.1.4; pre: in failure-to-provide).

**Settlement (7) additions.** `dam_as_capacity` = Σ DAM MCPC × DAM award (P§4.6.4.1); post `rt_as_imbalance` = Σ_i
RT MCPC_15 × (mean RT award − DAM award)/4 (P§6.7.2.2-6.7.2.6, §4c); pre `failure_to_provide` = −Σ_h DAM MCPC × mean
shortfall MW (pre-P§6.7.3 without the ORDC price term AVGRTASIP, **[simplified]**); post `capacity_short` = per hour,
short MW = (Σ up awards × duration × 0.5 − (DRUC HBSOC − MinSOC)·η)/(weighted duration), charged at the awards'
mean DAM MCPC (P§5.7.4.1, NPRR1236; deployment factor 0.5 from the ERCOT training example, **[simplified]**);
`pv_energy` = Σ RT SPP × PV MW / 4 (**[modelled]**). Scarcity post-RTC+B is in the posted MCPCs and LMPs (ASDCs inside
SCED, §5); `get_prices(market="asdc")` shows the posted curves.

**PV site option.** `site.pv` {mw_ac, poi_mw}: PV output from `pv` (curtailed when the LMP < 0), battery limits
min(HSL, POI − PV) and max(LSL, −POI − PV); PV sells at the RT SPP; `get_forecasts(kind="pv")` gives the as-issued
modelled forecast. Everything PV is **[modelled]**.

**Optimiser.** The 8.1 LP adds per-interval RT awards r_p (post) and DAM AS positions R_p per open hour (post:
financial, revenue DAM MCPC × R + RT MCPC × (r − R); pre: physical, r = R), the headroom and SoC rows above, expected
regulation energy in the SoC balance (mean fractions; hindsight uses the real ones), the DAM joint limits, the
capacity-short test as a constraint (DAM positions and posted awards backed by the planned SoC at each hour start,
deployment factor 0.5) and slack at $500/MW/h for posted pre-RTC+B responsibilities SoC cannot hold. AS price views:
`get_forecasts(kind="as_price")` — the desk `as_dam`/`as_rt` vintages, else the latest posted DAM MCPC day ±50% and the
history RT/DA ratio (IMM 2025 ratios when no history; §7), labelled. Proposals: `dam_as_offers` / `rt_as_offers` as
one item per product and day with the P50 plan's MW at half the lowest scenario MCPC; `as_plan_mw` for the next 24 h.

**References.** idle (0 MW curve, no AS offers: ERCOT's proxies may clear, so P_idle can be > 0 post-RTC+B), the anchor
(also submits the AS proposals), the hindsight optimum (real MCPCs, reg fractions and deployments; DRUC HBSOC = its own
SoC path), the operator replay (its DAM and RT AS offers too) and the operator's actual (its disclosed AS awards; their
deployments are inside its telemetry). PV is not in the operator rows.

Budgets v3: 48 turns, 14 calls per turn. `optimize` output in v3 is about 4–5k characters.

### 10.2 v4 "Weather Front" as built

- **Window.** Three consecutive operating days (`dates` has 3), D-1 06:00 → D2 24:00 (−1080 → 4320). The battery
  enters D0 at soc0; the end-SoC target and its price apply after D2 (7). All v3 rules (AS, PV) hold.
- **DAM per day.** Each day's DAM closes at 10:00 the day before and posts its results then (`posted.dam[date]`).
  Curves and AS offers for any of the three days may be submitted from the start (up to 14 days ahead, MSVR); a new
  submission overwrites only its hours. Wakes: `start` (D-1 06:00, for D0), `dam_morning` (D0 06:00 for D1, D1 06:00
  for D2, merged with that minute's checkpoint), `dam_results` and `adjustment_open` per day, checkpoints on every
  operating day, events and reminders. `day` is an argument of every tool that reads or writes a day.
- **As-issued vintages central.** Every desk-forecast vintage issued by now is applied oldest first, so each day's
  DAM vintage (DATA: one per operating day, issued at its D-1 06:00) prices its own hours; ERCOT load/wind/solar/PV
  vintages are read with `get_forecasts(vintage=...)` as issued. DATA keeps vintages issued from D-1 00:00 to D2 23:00
  with horizons to D2 24:00.
- **Statements per day** (7): `statement.days[date]`; the shadow statement in `get_position(day=...)`.
- **Budgets.** 100 turns, 14 calls per turn, 12 pending reminders. Runner compaction for v4: tool results older than
  the last 3 turns are elided once the transcript passes 80k characters (v2/v3: 4 turns, 120k). Estimate for Sol
  (GPT-6.1, $2/$10/$0.10 per 1M): ~400 calls × ~18k input tokens (~90% cached) + ~500 output tokens each ≈ $4 per
  window, under the $6 target; the v2 fixture smoke measured 19k input tokens per call at 90% cache.
- **References.** The hindsight LP spans all three days with every DAM open at D-1 06:00; the anchor re-optimises at
  every non-reminder wake over the rest of the window.

### 10.3 v5 "The Market Floor" as built (`gridsim_core.desk.impact`)

- **Series field (DATA):** `market` {date: day row} in the previews' `data/market/days` shape (NP3-966-ER, parser
  `966-v1`): `background.supply`/`background.demand` per hour (every other resource's offers and bids, **the site's own
  resource carved out**), `lambda_usd`, `hub_dam_usd`, `replay.lambda_usd` (the copper-plate re-clear of every real
  offer). `pool` may be empty.
- **Re-clear.** At each day's DAM close, every hour's EB/OC (or pre-RTC+B offer and bid) is cut into price blocks
  (the 5.1 curve, four steps per linear piece) and cleared with `market_auction.clear_hour` against the hour's book
  (`market_auction.book` over `market_stack.hour_curves`, prices lifted by the real hub DAM − replay λ, so the book
  with the operator's own offer reproduces the real hub price). The battery's node DAM price is λ' + (real node DASPP −
  real hub DAM): the basis is held at its real value **[simplified]**. Without the battery's curve the re-clear posts the
  real price. The posted node price, the award and the settlement all use λ'; the agent sees the re-cleared price.
- **AS stays price-taker** at the real DAM MCPC: the co-clear (10.1) runs at the re-cleared energy price. **RT stays
  price-taker.** No market-power mitigation is applied **[simplified]**.
- **References under the same re-clear:** idle and the anchor play through it; the hindsight optimum is the
  price-taker plan with its DAM positions (and the dispatch-tied ones for `hind_phys`) self-scheduled into the re-clear
  and settled at the resulting prices (an approximation of the price-making optimum); the operator replay re-clears the
  operator's disclosed curves; the operator's actual stays at the real prices.
- The agent has no view of the stack (the day's offers are disclosed 60 days later); the prompt states that its DAM
  offers move the price.

## 11. Episode JSON (`gridsim.desk.episode/v1`)

```json
{"schema": "gridsim.desk.episode/v1", "task_id": "...", "layer": "v2", "era": "rtcb", "dates": ["..."],
 "site": {"card": {...}, "hsl_mw": 0, "lsl_mw": 0, "e_max_mwh": 0, "rte": 0},
 "policy": {"kind": "model|anchor|idle|scripted|operator", "model": "openai/gpt-6.1-sol", "effort": "high"},
 "wakes": [{"t": -1080, "label": "Fri 02-13 06:00", "reasons": ["start"], "turn": 0}],
 "turns": [{"turn": 0, "t": -1080, "calls": [{"tool": "...", "args": {}, "result": {}, "ok": true}], "text": "..."}],
 "submissions": [{"t": -900, "tool": "submit_dam_offers", "day": "D0", "hours": [1, 2], "accepted": true, "codes": []}],
 "dam": {"<date>": {"spp": [24], "award_mw": [24], "curves": [24 | null]}},
 "rt": {"<date>": {"lmp": [288], "base_point_mw": [288], "metered_mw": [288], "soc_mwh": [289], "curve_ver": [288],
                   "spp": [96]}},
 "events": [{"t": 0, "kind": "notice|nws|outage|deployment|reminder|milestone", "text": "..."}],
 "statement": {"<date>": {"lines": {"dam_energy": 0}, "total": 0}, "total": 0},
 "grade": {"reward": 0, "capture": 0, "p": 0, "p_idle": 0, "p_anchor": 0, "p_hind": 0, "p_operator_replay": 0,
           "valid": true, "stretch": 0},
 "usage": {"turns": 0, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0},
 "core_version": "desk-2.0"}
```

---

## 12. Python API (`gridsim_core.desk`)

```python
from gridsim_core.desk import Session, load_task, load_series, grade, build_refs, TOOL_SPECS

task, series = load_task(pack, task_id), load_series(pack, task)   # or fixtures.make_task(...)
s = Session(task, series, layer="v2")      # budgets from the layer; forecaster from the series (8.4)
wake = s.start()                           # {"now", "reasons", "events", "deadlines", "budget"}
s.call("get_prices", {"market": "dam"})    # one tool call (counts against calls_per_turn)
s.close_turn(text)                         # close the turn without moving time (gateway path)
wake = s.end_turn(text)                    # close the turn and advance to the next wake; None at the end
s.next_wakeup(); s.advance_to(minute)      # hook / gateway path (2.4)
s.done; s.episode(); s.grade()             # Episode JSON and the 9.1 grade
TOOL_SPECS                                 # the 11 tools' JSON schemas (OpenAI function format); tool_specs(layer, rtcb)
text(obj)                                  # the one serializer for tool outputs and wake messages (compact JSON)
system_prompt(task, layer)                 # the desk brief from the task record (or system_prompt(session))
```

Policies for runs and references: `desk.policies.idle`, `desk.policies.anchor`, `desk.policies.scripted` (a fixed-rule
desk: self-schedules the cheapest desk-P50 hours to charge and the dearest to discharge, through the same tools);
`desk.policies.run(task, series, "anchor")` plays a whole episode. `desk.prompt.system_prompt(session)` is the brief
every path gives the agent; `desk.tools.tool_specs(layer, rtcb)` the era's schemas (pre-RTC+B curves take
`offer`/`bid`). `scripts/desk_run.py` is the in-process runner (path B'): `--policy model --preset sol|luna|qwen` or
`--policy anchor|idle|scripted`, `--pack`/`--fixture`, per-episode `--max-usd`, `--lane-cap-usd`, resumable from
`<out>/ckpt`, writing `<out>/episodes/*.json` and `<out>/results.jsonl`. `--parallel N` plays N episodes in threads
of one process: one `Budget` holds the lane cap (`--lane-cap-usd`, seeded from `results.jsonl`) and every model call
reserves its worst case (input estimate + 16k output tokens, or `--max-tokens`) before it is sent and settles to the
real cost after, so concurrent episodes never overrun it together; only the main thread writes `results.jsonl`;
SIGTERM/SIGINT stop new calls, keep every checkpoint and write no row for interrupted episodes (rerun to resume).
`--tasks-file` takes ids one per line or a jsonl with `task_id`. Each results row carries `capture` (C vs `p_hind`)
and `capture_phys` (C vs `p_hind_phys`) side by side.

---

## 13. Provisional lane decisions (C-D*)

| # | Decision |
|---|---|
| C-D1 | Episode window D-1 06:00 → last day 24:00; D-1's own RT is out of scope and the battery enters D0 at soc0 |
| C-D2 | Forecast and price postings do not wake the agent; DRUC/HRUC do not wake it either (ESRs are never RUC-committed); RT checkpoints every 6 h on operating days |
| C-D3 | Curves are piecewise linear (5.1); a curve that misses 0 MW is extended to 0 at the nearest point's price |
| C-D4 | Perfect set-point following except at unit events; SPD/BPD arises only there in v2 (Reg deployments add it in v3) |
| C-D5 | End-of-horizon SoC: target = the idle path's end SoC, shortfall charged (7); no credit above target; P_idle = 0 |
| C-D6 | WSL charging priced at the node RT SPP (the WSL bus price is not public at the bus) |
| C-D7 | Budgets v2: 40 turns, 12 calls per turn, 8 pending reminders |
| C-D8 | The hindsight optimum is the rules-bound optimum (DA/RT spread positions included); `hind_phys` reported beside it |
| C-D9 | SCED uses the hour's COP HSL/LSL and MinSOC/MaxSOC as the telemetered limits (intersected with unit events) |
| C-D10 | The anchor's risk is 0.5 (fixture sweep: 0 to 0.5 similar, 0.75+ unstable); revisit on the first real pack |
| C-D11 | COP-03 checks each touched hour against both neighbours as they will stand (frozen neighbours included), with standby loss and 0.01 MWh slack |
