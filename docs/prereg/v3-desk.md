# GridSimEnv desk v3 "Sun, Storage and Reserves": pre-registration

Committed on `desk` before the first scored v3 episode. Nothing below changes after a scored run starts, and nothing is
rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs.

## What is tested
The v2 desk (one real ERCOT ESR at its own node, ERCOT's own submission objects, events in real time) plus ERCOT's five
ancillary services in the DAM and post-RTC+B real time: RegUp, RegDn, RRS, ECRS and Non-Spin, with AS offers (or
ERCOT proxy offers when none are submitted), DAM AS awards bought back at the RT MCPC, AS duration rules on state of
charge, deployments, capacity-short charges, hub 5-minute LMPs, and on a third of the tasks a co-located PV plant
(modelled from ERCOT regional solar, labelled).

## Code and data
- Code: the tag `desk-v3-freeze` (acff0cd). No agent-visible behaviour changes until the last v3 episode ends.
- `desk-v3-eval` (01b017f, refs 3b93a2a): 24 battery-days, the same 4 real ESR sites as v2 × 6 post-RTC+B days
  (2026-04-11, 04-24, 05-26, 06-06, 07-21, 08-22), every day ≥ 60 days old with complete operator disclosures,
  after ERCOT's AS price errata window; 8 tasks with the PV option; 8 notice, 6 quiet, 4 scarcity, 3 outage and
  3 negative-price days. 04-24 is also a v2 eval day.
- References as v2 (idle, anchor, hind, hind_phys, operator replay, operator actual), settled by the same code with AS.
  `hind` bounds DAM positions at nameplate, so P_hind ≥ every reference (asserted when refs are built).
- **Anchor:** risk 1.5, DAM basis spread, chosen by the v2 procedure on the `desk-v2-tune` days with the v3 layer
  (contract §9.3), before any v3 eval result. Those tune days carry real MCPCs and ASDCs but no deployment series.
- **Reward:** as v2 (contract §9.1, with the floor); 13 of 24 tasks are floored. C and C_phys are the headline.

## Models and settings (path B', `scripts/desk_run.py`)
| model | route | effort / sampling | per-episode cap | lane cap | parallel |
|---|---|---|---|---|---|
| GPT-6.1 Sol | LiteLLM, Responses API | reasoning effort high | $5 | $45 | 12 |
| GPT-6 Luna | LiteLLM, Responses API | reasoning effort high | $1 | $10 | 12 |
| Qwen3-4B (base, untrained) | vLLM 0.29 (same build, revision and flags on every GPU), hermes tools | thinking off, temperature 0.7, top_p 0.8 | — | — | ≤ 6 a GPU |

Sol and Luna run on the g5 run host; Qwen3-4B's tasks are split over up to four identical single-A10G vLLM hosts
(one disjoint task list each), merged into one result set. Same prompt (`system_prompt(task, "v3")`), the same 11
tools with their v3 fields, v3 budgets (40 turns, 12 calls a turn, 8 reminders), the same compaction as v2. One run per
task per model; infrastructure failures retried at most twice, every attempt counted; a run stopped at its cap is final.

## Pilot
`docs/prereg/v3-desk-pilot.md`, GPT-6.1 Sol on two v3 battery-days; its outcome is appended there.

## Reported (descriptive, `scripts/desk_report.py`)
As v2, plus the AS statement lines (DAM AS capacity, RT AS imbalance, capacity-short) and AS submissions by product.
A "Sensitivity (post hoc)" section gives medians, per-day means and loss days.

## Prior
AS adds revenue for every policy; Sol uses AS offers and beats Luna on C; Qwen3-4B rarely offers AS correctly.
