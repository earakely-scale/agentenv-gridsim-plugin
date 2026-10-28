# GridSimEnv desk v2 "The Live Grid": pre-registration

Committed on `desk` before the first scored v2 episode. Nothing below changes after a scored run starts, and nothing is
rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs.

## What is tested
A battery trader at a QSE runs one real ERCOT energy storage resource at its own resource node for one operating day,
energy only, under the post-RTC+B rules (design FD-4548, D1–D13; `docs/CONTRACT-desk.md`). The agent submits ERCOT's
own objects (DAM and RT Energy Bid/Offer Curves, the COP); clearing, 5-minute SCED physics and settlement decide the
money. Time moves on its own: the agent wakes at market milestones, shift checkpoints, ERCOT notices, NWS warnings and
watches, outages and its own reminders.

## Code and data
- Code: the tag `desk-v2-freeze` (cf27f8d). No agent-visible behaviour changes until the last v2 episode ends.
- `desk-v2-eval`: 32 battery-days, 4 real ESR sites (Far West 100 MW / 104 MWh, Houston 100 MW / 206 MWh, North
  120 MW / 187 MWh, South 150 MW / 185 MWh) × 8 post-RTC+B days (2026-01-25, 02-24, 03-23, 04-24, 05-03, 06-24,
  07-22, 08-23), every day ≥ 60 days old with complete operator disclosures; 14 scarcity, 10 negative-price and 8
  notice days (b5a5f35).
- References on every task, settled by the same code: idle, the information-matched anchor, the hindsight optimum
  (`hind`, DAM/RT spread positions allowed), the hindsight optimum with the DAM position tied to dispatch (`hind_phys`),
  the operator replay and the operator's actual.
- **Anchor settings** (risk, DAM basis) are chosen by a fixed procedure on a separate pack, blind to every model result:
  `desk-v2-tune` (12 post-RTC+B battery-days, 3 per site, disjoint from pilot and eval); grid risk {0.5, 0.75, 1.0,
  1.25, 1.5, 2.0} × DAM basis {physical, spread}; the largest total anchor P, unless its worst single day is a larger
  loss than the runner-up's and the runner-up's total is within 5%, in which case the runner-up. The choice and the
  grid go into contract §9.2 before any model result is read; the eval refs are then built with it. Model runs may
  start before the choice: R is graded after, by replaying each Episode JSON against the frozen refs (`desk_report.py
  --regrade`).
- **Reward** (contract §9.1): R = clip(0.2 + 0.8·(P − P_idle)/den, 0, 1), den = max(P_anchor − P_idle,
  0.1·(P_hind_phys − P_idle)); tasks where the floor binds are flagged `floored`. No valid submission → R = 0.
  C = (P − P_idle)/(P_hind − P_idle) and C_phys = (P − P_idle)/(P_hind_phys − P_idle) are reported; C is the headline.

## Models and settings (path B', `scripts/desk_run.py`, one g5.xlarge run host)
| model | route | effort / sampling | per-episode cap | lane cap | parallel |
|---|---|---|---|---|---|
| GPT-6.1 Sol `openai/gpt-6.1-sol` | LiteLLM, Responses API | reasoning effort high | $5 | $45 | 16 |
| GPT-6 Luna `openai/gpt-6-luna` | LiteLLM, Responses API | reasoning effort high | $1 | $12 | 16 |
| Qwen3-4B (base, untrained) | vLLM 0.29 on the run host, chat completions, hermes tool parser | thinking off, temperature 0.7, top_p 0.8 | — | — | 8 |

The same system prompt (`gridsim_core.desk.system_prompt`), the same 11 tools, v2 budgets (40 turns, 12 calls a turn,
8 pending reminders). Context compaction: GPT models elide tool results older than the last 4 turns past 120k
characters; Qwen3-4B (32,768-token window) elides by token count to a 24k-token prompt and caps output to fit. One run
per task per model, all three models concurrently. An attempt that fails for infrastructure is retried at most twice;
every attempt is kept and counted in the spend. A run stopped at its cost cap is final and scores what its submissions
earned. A task with no row after three attempts is reported as missing, not scored as zero.

## Pilot (done, `docs/prereg/v2-desk-pilot.md`)
GPT-6.1 Sol on two real battery-days, as a mechanics and cost check: both episodes ended normally with no env error,
wakes fired at milestones, notices, NWS alerts and the agent's reminders; $0.98 and $0.76 an episode. It ran on a
commit before two information-timing fixes found in review (049cc93), so it is not scored.

## Reported (descriptive, `scripts/desk_report.py`)
- Per model: mean R, C and C_phys with day-block 95% CIs (10,000 resamples of days, seed 0, task-weighted); mean P and
  each statement line; P − P_anchor and the share beating the anchor; P − P_operator_replay and P − P_operator_actual;
  turns, wakes, tool calls, accepted and rejected submissions by code, reminders, cycles, cost and tokens.
- Paired day-block CIs: Sol − Luna, Sol − Qwen3-4B, Luna − Qwen3-4B, and each model − operator replay.

## Prior
Sol near or above the anchor on most days, with occasional large losses from DAM over-commitment (seen in the pilot);
Luna below Sol; Qwen3-4B untrained mostly valid but well below both. The real operator's actual P sits between the
anchor and the hindsight optimum on most days.
