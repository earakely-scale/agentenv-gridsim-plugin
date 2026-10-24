# GridSimEnv v1 board: pre-registration (GPT-6.1 Sol)

Committed before the first board episode. Nothing below changes after a run starts, and nothing is rerun to improve a score.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`), reasoning effort `high`, through LiteLLM. Edgar's rule: one model until a version is final; more models run once v1 is final.
- Agent `gridsim-llm`, max_turns 4, max_tokens 4,096 per turn, 24 tool calls and 3 checks per episode, enforced server-side.
- One run per task. An unscored run (an infrastructure failure, not a model failure) is retried at most twice and every attempt is kept. A run with no valid submit scores 0; that is a result, not a retry.

## Columns (held-out 2025, Jan 1 - Nov 30, pre-RTC+B)
| Column | Bundle | Tier | Tasks |
| -- | -- | -- | -- |
| A (primary) | `full` (3 checks) | foresight | the 500 eval-2025 foresight tasks |
| B | `oneshot` (0 checks, submit only; the path-B training prompt) | foresight | the same 500 |
| C | `full` | blind | the 300 eval-2025 blind tasks |

Column D (optional, same rules): `full` foresight on the 250 rtcb tasks (post-RTC+B), reported separately.

## Metrics
- Mean R with a 95% bootstrap CI over tasks (10,000 resamples); blind column: R_opt (headline), R on the anchor scale and the beats-anchor rate.
- Valid-submit, no-submit and malformed rates; optimal rate (R >= 0.99).
- Error taxonomy from the grader: overfill (`soc_above_N`), sell-before-charge (`soc_below_0`), rate, cycle cap, end-short, all-idle.
- Checks used per episode and R by number of checks; R by archetype, by binding constraint and by day type.
- Spend, tokens, $/episode, end reasons, wall time, unscored runs and why.
- Baselines on the same tasks from gridsim_core: idle 0.200, random feasible, clock, threshold, greedy, persistence-DP and the blind anchor; DP = 1.000 on foresight; the LP bound in $.

## Hypotheses (from the spec, before any run)
| Row | Hypothesis |
| -- | -- |
| Sol, full, foresight | ~0.90-0.95 |
| Sol, oneshot, foresight | below full, by an amount not predicted |
| Greedy (filtered pack) | ~0.78 (tuned to 0.75-0.80) |
| Threshold | ~0.62 |
| Sol, blind | no prior; first measurement |

## Budget
Column A ~$0.05/episode, B ~$0.02, C ~$0.05 [estimates, measured by a 10-task smoke first]. Per-episode cap: 4x the smoke median, rounded up to $0.10. A watcher stops the sweep past $150 total for the board.
