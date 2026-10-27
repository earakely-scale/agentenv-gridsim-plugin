# GridSimEnv v1: the live sealed board on ERCOT's day-ahead market (pre-registration)

Committed and pushed to `main` before the first seal (delivery day 2026-10-29). **A descriptive track record, not a
test:** at most six graded days fall before the contest deadline (2026-11-03 07:59 UTC), so nothing here carries a
verdict.

## What it is
Every day, each agent commits a 24-hour schedule for a grid battery on a future ERCOT DAM delivery day, **before that
day's DAM closes**, and the schedules are published with a server timestamp (a commit to the Hugging Face dataset
`earakely-scale/GridSimEnv-AgentEnv`). After ERCOT posts the day's DAM settlement point prices, every schedule is
settled at those prices with `gridsim_core`, and a cumulative dollar P&L board is updated. These are **sealed
schedules, not bids**: nothing is sent to ERCOT, and the battery is a price-taking simulation (docs/CONTRACT.md).
Unlike the fresh packs, neither the answer nor the inputs of a sealed day can be in any model's training data or in
any choice we make: the prices do not exist when the schedule is published.

## Timing
- DAM for delivery day D closes at 10:00 Central Prevailing Time on D−1; ERCOT posts D's prices at about 13:30 CPT on
  D−1 (18:30 UTC while CDT; 19:30 UTC from 2026-11-01).
- **One daily job** on a dedicated cloud box (no laptop), started by a systemd timer at 18:35 UTC. On Central day T it
  polls the public API every 5 minutes until T+1's DAM prices appear (it gives up at 23:30 UTC and logs it), then:
  1. **grades** the sealed schedules for T+1;
  2. **builds** the tasks for T+2 from T−5..T+1 prices, runs every agent, and **seals** T+2, about 20 hours before its
     DAM closes.
- Catch-up passes at 03:00 and 12:00 UTC run the same steps without polling, for a day the evening pass missed. Every
  step is idempotent: a sealed day is never resealed, a recorded reply is never rerun, a graded day is never regraded.
- **A seal counts only if** (a) the HF commit that publishes it has a server timestamp before 10:00 CPT on D−1, and
  (b) a query made just before that commit found **no DAM rows for D** in the API (every settlement point). The sealed
  file records the check's time and row count; the graded file records the commit and whether both held.
- **Days:** the first seal is 2026-10-29 (inputs complete when 10-28's prices post on 10-27). Sealed and graded before
  the contest deadline: **2026-10-29 .. 2026-11-03** (six days; 11-03's prices post on 11-02). The box keeps the board
  running until it powers off (about 2026-11-03 20:00 UTC); later days are listed after the deadline snapshot.
- A day that is not sealed in time (a box or API failure) is recorded as not sealed and never filled in later.

## The fall-back day
2026-11-01 has 25 hours (HE02 repeats; the API marks the repeated hour with `DSTFlag` true). The v1 packs drop DST
days. Here the repeated hour is dropped from inputs and settlement alike: **the battery idles during the repeated
hour**, and the day is the 24 hours HE01..HE24 as usual. This keeps 11-01 on the board and keeps the D−7..D−1 inputs of
11-02 and 11-03 complete. The agent sees 24 hours, as on every other day.

## Tasks: 45 a day
- **15 settlement points** (`results/fresh/2026-10/scripts/ercot_pull.py`'s `POINTS`: v1's five hubs, two hub averages
  and eight load zones) × **3 reference batteries at 100 MW**, taken from the v1 archetype table
  (`data/ercot-dam-v1-rtcb/manifest.json` `letters`, the table `scripts/build_pack.py` uses). The rule: in each
  duration class, the first letter (alphabetically) with P = 100 MW.

  | archetype | E (MWh) | unit (MWh) | k_dis / k_ch | SoC levels | η | c_deg ($/MWh) | cycle cap (units) | s0 | s_end_min |
  |---|---|---|---|---|---|---|---|---|---|
  | `1h-c` | 100 | 50 | 2 / 2 | 2 | 0.90 | 0 | 3 | 2 (full) | 2 |
  | `2h-b` | 200 | 50 | 2 / 2 | 4 | 0.90 | 4 | 4 | 4 (full) | 2 |
  | `4h-f` | 400 | 25 | 4 / 4 | 16 | 0.80 | 4 | 16 | 0 | 0 |

- **Blind tier, as the fresh blind pack:** the agent sees the battery and the point's DAM prices for D−1 and for
  D−7..D−1, nothing of day D. Rows are built with `build_pack.lags` and `battery_for`; task ids are
  `dam-v1-D-POINT-ARCH`.
- **No filters.** The packs' dedup, low-spread, greedy-easy and blind-anchor-margin filters are not applied: every
  (point, battery) is sealed and graded every day, because the board is a P&L book, not a test set.
- **Inputs:** NP4-190-CD (DAM Settlement Point Prices) through ERCOT's public API, as `ercot_pull.py` (at most 10
  requests a minute; no `/misapp` or `/misdownload` paths). A point-day must have exactly 24 hours (after the DST rule)
  and pass the era caps (`gridsim_core.contract.price_violations`). A later pull that disagrees with an earlier one
  stops the job.
- The sealed file holds the task rows **without prices or refs**, and an **inputs digest** (sha256 of the canonical
  JSON of the rows).

## Agents: the prompt, tool and single call of the cost-matched contest
Every model gets exactly `system_prompt(task, "blind", 0, forecast=True)`, `situation_text(task, "blind", 0)` and the
`submit_schedule` tool: one call, no checks, as in `results/cost-matched` (pack 3b) and run 4.
1. **GPT-6.1 Sol** (`openai/gpt-6.1-sol`), effort `high`: `results/train/4b-blind/scripts/sol_blind.py`'s `request`
   and `call` (Responses API through LiteLLM, `max_output_tokens` 16,384, streamed, `store` off).
2. **GPT-6 Luna** (`openai/gpt-6-luna`), effort `high`: `results/cost-matched/scripts/luna_eval.py`'s
   `Harness("blind", "high")`.
3. **The trained Qwen3-4B, registered run 4 final** (`results/train/4b-blind/`): `Qwen/Qwen3-4B` @ `1cfa9a72` → run 3
   merged (SFT-10k's `sft-lora`, then run 3's `dpa-lora`) → run 4's blind `sft-lora` merged → run 4's `rl-lora` (RL
   step 237) served as a vLLM LoRA. Adapter archives by sha256: reg2 `69c5f4a6…`, reg3 `05c1dcb2…`, reg4
   `677547ef…` (recorded in full in every sealed file). Merges with `results/train/4b-blind/scripts/merge.py` (bf16);
   vLLM 0.29.0 with `evaluate_blind.py`'s engine settings on one A10G; the registered eval's decoding: sampled,
   temperature 0.7, top_p 0.8, top_k 20, seed 0, `max_tokens` 768, thinking off.
   - **Serving check, before the first seal:** the live engine on the 331 tasks of `ercot-dam-v1-fresh-2026-10-blind`,
     against `eval_final.json`'s sampled run there (C 0.841). Reported: C and the share of identical schedules. If C
     is more than 0.03 away from 0.841, the 4B stays off the board until the serving is fixed (a serving fix, never a
     model change); the days it misses are recorded as missing.
4. **Rules, sealed with the same inputs:** persistence + DP (`baselines.persistence_dp`), ridge + DP
   (`baselines.ridge_dp`, `data/ridge-v1.json`) and the greedy rule on D−1's prices (`baselines.greedy`).
- **References, computed after grading** (they need the day's prices; not sealed): the **hindsight optimum** (the DP on
  day D's prices, C = 1) and the **blind anchor** (per task, the better in hindsight of persistence + DP and ridge + DP).
- **Beam** is not on the board (no LiteLLM route). An agent added later is announced in an amendment pushed before its
  first seal, starts on that day and is never backfilled.

## Sealing
- One call per task. An infra failure (no response) is retried at most twice and recorded; a response is final. No
  rerun to improve a score, no prompt change.
- An agent is **sealed for a day** if every one of the 45 tasks has a record (an infra-failed record counts and scores
  as no submission). Otherwise it is listed as missing for that day and not graded.
- `live/sealed/D.json`: the task rows, the inputs digest, the no-prices check, the seal time, and per agent its model
  id, effort or decoding, the 4B's chain and adapter sha256s, and per task the submitted actions (the first parseable
  `submit_schedule` call, `gridsim_core.trl.extract_actions`), the written forecast, the reply text, tokens and cost.
  The commit's server timestamp is the public seal; its id and time go into `live/board.json` and the graded file.

## Grading
- When D's prices post: each sealed row plus D's prices, refs from `gridsim_core.grade.references(task, ridge-v1)`.
  Model schedules are scored by `pathb_blind.graded` (as in run 4 and the cost-matched contest), rule schedules by
  `grade(task, schedule, "blind")`: settlement by `gridsim_core.physics` with rules 1–5, the degradation cost and the
  end-obligation penalty.
- **No valid submission:** C = 0 (as in every pack) and the battery idles in the P&L (the three batteries' idle P&L is
  $0).
- **Per agent and day:** P&L in **$ per MW** (the mean over the 45 books of profit ÷ 100 MW, i.e. $ per MW of discharge
  capacity per day) and in $ for the whole 4.5 GW book; mean **C** (hindsight capture, `r_opt`); R on the blind
  anchor's scale; the valid rate; each split by duration (1h, 2h, 4h).
- **Cumulative:** the sum of daily $/MW over graded days with a valid seal, and the mean C over those days.
- **Paired against persistence + DP** (the simplest sealed rule): per task, agent − persistence in C and in $/MW; the
  mean with a **day-block bootstrap 95% CI** (10,000 resamples of days, seed 0, task-weighted, as `report_blind.boot`)
  and the cumulative $/MW gap. **Descriptive only:** six days give wide intervals, and no hypothesis is tested.
- A day whose seal is not valid is shown and excluded from every cumulative number.

## Budget
- **API spend capped at $25 in total** (Sol about $0.72 a day and Luna about $0.09 at their per-task cost on the
  fresh blind pack). A request starts only if spend + the in-flight worst cases + its own worst case (16,384 output
  tokens) stays under the cap; spend is logged per agent and day in each sealed file.
- The 4B runs on the board's box (g5.xlarge, about $1 an hour for about 170 hours).

## Prior (from the fresh blind pack, 2026-10-18..27)
C: Sol about 0.91, ridge + DP 0.89, persistence + DP 0.87, the 4B and Luna about 0.84, greedy on D−1 0.75; the blind
anchor 0.92. Over six days one volatile day can reorder them.

## Published
- The HF dataset `earakely-scale/GridSimEnv-AgentEnv` under `live/`: `sealed/D.json`, `graded/D.json` and
  `board.json` (cumulative, with the sealed-vs-graded timeline and each commit), mirrored into this repo's `live/`.
- A "Live board" page on the Space; the default view is unchanged.
- Code: `scripts/live/live.py` (the daily job) and `scripts/live/live_4b.py` (the 4B's engine).
