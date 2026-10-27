# Beam as the agent on the blind fresh days

A descriptive baseline, pre-registered in [`docs/prereg/v1-beam-agent.md`](../../docs/prereg/v1-beam-agent.md) (e551798)
before any scored request: untrained `reflection/Beam-1.0-501B-A23B` on the 331 blind tasks of
`ercot-dam-v1-fresh-2026-10-blind` (2026-10-18..27, all after Beam's 2026-06-30 cutoff), with exactly the prompt, tool
and scoring the trained 4B, GPT-6 Luna and GPT-6.1 Sol got. Served by Baseten through the Hugging Face router at
$0.40 / $1.20 per 1M input / output tokens.

All four pre-registered runs are complete (high, low, medium, max, in that order), under the $30 cap: $23.44 spent,
the 4-task smoke included. The sweep was paused once (2026-10-27, after high and 112 low tasks) and resumed under the
same rules; no task was rerun. Records and episodes are in `beam/`.

## Results (331 tasks, 10 days; C = hindsight capture, day-block 95% CIs)

| model | C | 95% CI | cost per task | output tokens per task |
|---|---|---|---|---|
| trained Qwen3-4B (run 4 final, sampled) | 0.841 | [0.793, 0.873] | $0.00047 | 429 |
| Beam, effort low | 0.759 | [0.726, 0.786] | $0.0056 | 3,947 |
| Beam, effort medium | 0.829 | [0.808, 0.848] | $0.0115 | 8,867 |
| Beam, effort high | 0.861 | [0.829, 0.886] | $0.0203 | 16,182 |
| **Beam, effort max** | **0.890** | **[0.859, 0.913]** | **$0.0330** | **26,788** |
| GPT-6 Luna, effort high | 0.836 | [0.800, 0.861] | $0.0020 | 3,656 |
| GPT-6.1 Sol, effort high | 0.913 | [0.864, 0.949] | $0.0158 | 1,216 |

| paired gap (day-block 95% CI) | low | medium | high | max |
|---|---|---|---|---|
| Beam − trained 4B | −0.082 [−0.112, −0.050] | −0.012 [−0.045, +0.029] | +0.020 [−0.005, +0.047] | **+0.049 [+0.007, +0.101]** |
| Beam − Sol | −0.154 [−0.183, −0.121] | −0.084 [−0.115, −0.044] | −0.052 [−0.078, −0.025] | −0.023 [−0.062, +0.026] |

- **Score rises with effort and so does cost:** each step roughly doubles the tokens. At max, Beam is ahead of the
  trained 4B and level with Sol within the CI, at about 2× Sol's cost per task and 70× the 4B's.
- **Off the score-against-cost frontier at every effort** at Baseten's price: the trained 4B, Luna-high and Sol each
  score higher for less at the matching point.
- **Headroom for training** (teacher forecast + exact DP, 0.920 on this pack, − Beam's best C): 0.030 at max, 0.059 at
  high.
- **Errors:** low overfills on 16 tasks (5%); at max, one reply hit the 65,536-token limit and one was malformed.
  Beam keeps its forecast inside its reasoning, so the "DP on its own forecast" diagnostic is not available.

`scripts/beam_eval.py` is the harness.
