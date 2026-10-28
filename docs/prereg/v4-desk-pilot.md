# GridSimEnv desk v4 pilot: pre-registration (GPT-6.1 Sol, Weather Front)

Committed on `desk` before the first v4 pilot episode. The pilot proves the three-day desk on a real front before the
v4 freeze; it is not part of the v4 board. Anything done differently is logged under "Deviations", appended after.

## Code and task
- Branch `desk` at this commit (tag `desk-v4-pilot-run`): the v4 layer (three operating days, a DAM each day, as-issued
  forecast vintages, per-day statements; AS and PV rules as v3), 100 turns, 14 calls a turn.
- `desk-v4-pilot` (37d7edd): one window, 2026-02-03..05 at S01 (Far West, 100 MW / 104 MWh), across the 02-04 cold
  front; 197 negative 5-minute intervals at the node, RT max $132.

## Model and settings
GPT-6.1 Sol (`openai/gpt-6.1-sol`), LiteLLM Responses API, reasoning effort high, path B' (`scripts/desk_run.py`), the
g5 run host. Episode cap $10, lane cap $12. GPT compaction for v4: tool results older than the last 3 turns elided past
80k characters.

## Pass criteria (each checked and reported)
1. The episode ends normally with no runner or tool server error.
2. Every DAM (three) opens and closes at its real time; DAM results, adjustment periods and `dam_morning` wakes fire on
   each day; reminders work across days.
3. Forecast vintages served are the latest issued at each wake, and the D1/D2 DAM prices are not visible before they
   post (perturbation check on the pilot task).
4. The per-day statements add up to the episode P, and the grade replays from the Episode JSON to the cent.
5. Cost and wall time per window measured, to size the v4 eval.

## Outcome (appended after the run)
One episode, ended normally with no tool error: 44 of 100 turns, 247 tool calls, $4.95, 45 minutes. P $25,389
(per day $5,036 / $12,046 / $8,307; the per-day statements sum to P) against anchor $19,122, operator actual about $13.7k
and hindsight $121,092. DAM offers submitted and accepted for each of the three operating days; three DAM results,
three adjustment-period openings and two `dam_morning` wakes fired; AS lines settle each day. Pass.
Deviation: the pilot ran at 3b7a4de, before CORE's v4 polish 41f146f (`optimize` proposes curves for the next open DAM
day only; per-day forecast vintage labels). The v4 eval runs on the v4 freeze, which includes it.
