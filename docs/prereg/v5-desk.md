# GridSimEnv desk v5 "The Market Floor": pre-registration

Committed on `desk` before the first scored v5 episode. Nothing below changes after a scored run starts, and nothing is
rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs.

## What is tested
The v3 desk with DAM price impact: the agent's DAM curves are re-cleared against the day's real disclosed offer stack,
so the price it is paid depends on how much it sells. Everything else (AS, RT, settlement, events) as v3.

## Code and data
- Code: the tag `desk-v5-freeze` (be6ff8c). No agent-visible behaviour changes until the last v5 episode ends.
- `desk-v5-eval` (63ed11d, refs 3b93a2a): the same 24 battery-days as `desk-v3-eval` (4 sites × 2026-04-11, 04-24,
  05-26, 06-06, 07-21, 08-22; 8 with PV), so the price impact is the only difference from v3. 13 of 24 floored.
- Anchor 1.5/spread (the pre-registered v5 rule reuses the v3 pick, contract §9.3); references re-cleared the same way.

## Models and settings
As v3 (`docs/prereg/v3-desk.md`): GPT-6.1 Sol (effort high, $5 an episode, lane $45, parallel 12), GPT-6 Luna (effort
high, $1, lane $10, parallel 12), Qwen3-4B (vLLM, four identical hosts, disjoint task lists, ≤ 6 a GPU); v3 budgets
and compaction; one run per task per model.

## Reported
As v3, plus the paired v5 − v3 difference per model on the same battery-days (P, R, C), and the price impact of each
agent's DAM sales (re-cleared minus real DAM price, MWh-weighted).

## Prior
v5 ≈ v3 for every model: these ESRs are price takers at the positions models take.

## Deviations
1. Qwen3-4B's v5 tasks were queued to start after each host's v4 tasks and so began before the v5 pilot was checked;
   the pilot passed (outcome in `v5-desk-pilot.md`).
2. The same task-list error as v4: 2026-04-11 S01–S04 and 2026-04-24 S01–S02 were not queued and ran at 13:07 UTC on the
   same frozen code; 2026-07-21 S03–S04 and 2026-08-22 S01–S04 ran on two hosts, and the planned host's runs are scored
   under the same pre-set rule.
3. Known env defect K1 as v3.
