# Beam as the agent on the blind fresh days

A descriptive baseline, pre-registered in [`docs/prereg/v1-beam-agent.md`](../../docs/prereg/v1-beam-agent.md) (e551798)
before any scored request: untrained `reflection/Beam-1.0-501B-A23B` on the 331 blind tasks of
`ercot-dam-v1-fresh-2026-10-blind` (2026-10-18..27, all after Beam's 2026-06-30 cutoff), with exactly the prompt, tool
and scoring the trained 4B, GPT-6 Luna and GPT-6.1 Sol got. Served by Baseten through the Hugging Face router at
$0.40 / $1.20 per 1M input / output tokens.

## Status
- **Effort `high`: complete** (331 tasks). Records and episodes in `beam/`.
- **Effort `low`: paused at 112 of 331; `medium` and `max`: not started.** The sweep was paused on 2026-10-27 to move
  Beam onto the team's model gateway instead of a personal Hugging Face account; it resumes from where it stopped
  under the same rules, and these rows will be added then.

## Effort `high` (331 tasks, 10 days; C = hindsight capture, day-block 95% CIs)

| model | C | 95% CI | cost per task | output tokens per task |
|---|---|---|---|---|
| trained 4B (run 4 final, sampled) | 0.841 | [0.793, 0.873] | $0.00047 | 429 |
| **Beam, effort high** | **0.861** | **[0.829, 0.886]** | **$0.0203** | **16,182** |
| GPT-6 Luna, effort high | 0.836 | [0.800, 0.861] | $0.0020 | 3,656 |
| GPT-6.1 Sol, effort high | 0.913 | [0.864, 0.949] | $0.0158 | 1,216 |

| paired gap | mean | day-block 95% CI |
|---|---|---|
| Beam − trained 4B | +0.020 | [−0.005, +0.047] |
| Beam − Sol | −0.052 | [−0.078, −0.025] |
| teacher forecast + exact DP (0.920) − Beam: headroom for training | 0.059 | |

- Beam reasons at length (about 16k reasoning tokens per task, 13× Sol), so at Baseten's price it costs more per task
  than Sol and earns less: off the score-against-cost frontier.
- 328 of 331 schedules are feasible (one overfill, one sell-before-charge, one cycle-cap breach). Beam keeps its
  forecast inside its reasoning, so the "DP on its own forecast" diagnostic is not available.
- In dollars (`../economics/`): Beam-high − persistence-DP is −3.4 $/MW-day [−8.6, +2.4].

`scripts/beam_eval.py` is the harness.
