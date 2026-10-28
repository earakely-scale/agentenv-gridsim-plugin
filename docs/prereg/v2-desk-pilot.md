# GridSimEnv desk v2 pilot: pre-registration (GPT-6.1 Sol, The Live Grid)

Committed on `desk` before the first pilot episode. The pilot proves the desk environment and its tasks on real ERCOT
days before any scored run; it is not part of the v2 board. Nothing below changes after the pilot starts. Anything done
differently is logged under "Deviations", appended after the runs.

## Code and tasks
- Branch `desk` at 16e1e46 (core v2–v5 layers, the `gridsim-desk` env and bundle, the `desk-v2-pilot` pack f964286).
- `desk-v2-pilot`: two post-RTC+B battery-days, both at least 60 days old with complete operator disclosures:
  `desk-v2-2026-04-27-S01` (Far West, 100 MW / 104 MWh, a scarcity day, RT LMP −2 to 917 $/MWh) and
  `desk-v2-2026-08-17-S03` (North, 120 MW / 187 MWh, a day with 4 ERCOT notices, RT LMP 15 to 458 $/MWh).
- Layer v2 (energy only), budgets 40 turns, 12 calls a turn, 8 reminders.

## Model and settings
GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM's Responses API, reasoning effort high, path B'
(`scripts/desk_run.py --preset sol`, in-process `Session`), on the g5 run host. Per-episode cap $5, lane cap $12,
parallel 2. An attempt that fails for infrastructure is retried at most twice and every attempt is counted.

## The anchor is not frozen yet
The anchor's risk and DAM basis are being chosen on a separate tune pack (`desk-v2-tune`, disjoint from pilot and eval)
while the pilot runs. The pilot's R is graded against the frozen anchor once it is set, by replaying the Episode JSON;
its P, the statement and the operator comparison do not depend on the anchor.

## Pass criteria (each checked and reported)
1. Both episodes end normally (`episode_over` or turns used up), with no runner or tool server error.
2. Every wake fires at its stored minute (milestones, notices, reminders) and none is skipped.
3. At least one DAM and one RT submission is accepted per episode; every rejection carries an ERCOT-style code.
4. The grade replays from the Episode JSON to the cent, and no tool output in either episode reveals a value before its
   real posting time (the per-wake future-perturbation check in `tests/desk`).
5. Cost per episode measured, to size the v2 eval runs.

A failed criterion stops the main runs for a fix; the fix and a re-pilot are logged as a deviation.
