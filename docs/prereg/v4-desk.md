# GridSimEnv desk v4 "Weather Front": pre-registration

Committed on `desk` before the first scored v4 episode. Nothing below changes after a scored run starts, and nothing is
rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs.

## What is tested
The v3 desk (energy and the five ancillary services, one real ESR at its own node, ERCOT's own objects, real-time
events) over three consecutive operating days across a real weather front: a DAM each day (each closing at 10:00 the
day before), as-issued ERCOT load/wind/solar forecast vintages and desk price-forecast vintages central to the
decisions, per-day statements.

## Code and data
- Code: the tag `desk-v4-freeze` (be6ff8c). No agent-visible behaviour changes until the last v4 episode ends.
- `desk-v4-eval` (be6ff8c): 16 three-day windows = 4 fronts × the 4 desk sites (48 battery-days): 2026-01-23..25
  (winter storm Fern, arctic front), 2026-03-16..18 (front then rebound), 2026-04-17..19 (front with negative prices;
  S04's window moved to 2026-04-03..05 because the site was on forced outage for the whole of 04-10..04-20), and
  2026-05-08..10 (severe-storm front). Fronts picked from HRRR daily-mean temperature swings; every day ≥ 60 days old,
  operator disclosures complete. No PV option in v4.
- References as v3, settled per day by the same code. Anchor 1.5/spread: the pre-registered v4 rule reuses the v3 pick
  (contract §9.3). Reward as v2/v3 with the floor; 4 of 16 windows are floored (all 2026-03-16). C and C_phys headline.

## Models and settings (path B', `scripts/desk_run.py`)
| model | route | effort / sampling | per-window cap | lane cap | parallel |
|---|---|---|---|---|---|
| GPT-6.1 Sol | LiteLLM, Responses API | reasoning effort high | $10 | $100 | 16 |
| GPT-6 Luna | LiteLLM, Responses API | reasoning effort high | $2 | $20 | 16 |
| Qwen3-4B (base, untrained) | vLLM 0.29, four identical single-A10G hosts, disjoint task lists, merged | thinking off, temperature 0.7, top_p 0.8 | — | — | ≤ 4 a GPU |

v4 budgets: 100 turns, 14 calls a turn, 8 reminders. Compaction: GPT models elide tool results older than the last 3
turns past 80k characters; Qwen3-4B by tokens to a 24k-token prompt. One run per window per model; infrastructure
failures retried at most twice, every attempt counted; a run stopped at its cap is final and scores what it earned.

## Pilot
`docs/prereg/v4-desk-pilot.md` (GPT-6.1 Sol, 2026-02-03..05 S01): passed; outcome appended there.

## Reported (descriptive, `scripts/desk_report.py`)
As v3, per window and per day: R, C, C_phys with day-block CIs (blocks = fronts), P and its per-day lines, P against
the anchor and the operator, turns, wakes, calls, submissions by day and code, cost. A "Sensitivity (post hoc)"
section gives medians, per-front means and loss windows.

## Prior
Fern dominates P for every policy; Sol rebids the D1/D2 DAMs as vintages move and beats Luna on C; Qwen3-4B struggles
to keep three DAMs and the COP straight over 100 turns.

## Deviations
1. Qwen3-4B task lists were set wrong by an operator error (a 1-indexed shell array): the four 2026-01-23 windows were
   not queued, and 2026-05-08 S02–S04 and 2026-04-03 S04 were queued on two hosts. The missing four ran at 13:07 UTC on
   the same frozen code and identical hosts. For the duplicated four, the run on the planned host is scored; the other
   copies are excluded under a rule fixed before any duplicate was read, kept on disk and not reported.
2. Known env defect K1 as v3.
