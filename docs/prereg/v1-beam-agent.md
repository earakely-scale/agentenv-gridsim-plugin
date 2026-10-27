# Beam as the agent on the blind fresh days: pre-registration

Pushed before any Beam request on a scored task. A descriptive baseline: where an untrained Beam sits against the
trained 4B, GPT-6 Luna and GPT-6.1 Sol on score against cost, and how much room it leaves for training it.

## Model and access
- `reflection/Beam-1.0-501B-A23B`, served by Baseten through the Hugging Face router (OpenAI Chat Completions), the only
  public price for Beam: $0.40 per 1M input and $1.20 per 1M output tokens (reasoning tokens are output). Reflection's
  own API is a free beta with unpublished limits, so it gives no price to put on the chart.
- Beam's knowledge cutoff is 2026-06-30; every task here is from 2026-10-18..27.

## Tasks and harness
- Pack 3b of the cost-matched contest: the 331 blind tasks of `ercot-dam-v1-fresh-2026-10-blind` (10 days).
- Exactly the prompt every other model got on this pack: `system_prompt(task, "blind", 0, forecast=True)`,
  `situation_text(task, "blind", 0)` and the `submit_schedule` tool, one call, no checks. Scored by
  `results/train/4b-blind/scripts/pathb_blind.graded` on the text and the tool call, as Sol and Luna were.
- The only differences are the API shape (Chat Completions, as Reflection documents Beam) and `max_tokens` 32,768
  (65,536 at `max`), set from Reflection's guidance that low budgets end Beam's reasoning with `finish_reason: length`.
  A reply cut off that way scores 0 as `truncated`, as for every other model.
- `seed` has no effect on Beam and `n` must be 1, so each task is one sampled reply.

## Runs, in this order, under one $30 cap
1. effort `high`; 2. effort `low`; 3. effort `medium`; 4. effort `max`.

A run starts only if the lane's spend plus its projected cost (from the runs so far, or the 4-task smoke for the
first) fits the cap; a run that would not fit is not started and is reported as not run. Inside a run the guard is
`luna_eval.py`'s. A 429 or 5xx is retried at most twice, honouring `Retry-After`; a 429 with `x-should-retry: false`
stops the lane. Any reply is final.

Before run 1, a smoke on 4 blind fixture tasks (not scored, not reported) at `high`, to check the call, the parse and
the cost.

## Reported (descriptive; no verdicts)
- Per effort: C with its day-block 95% CI (10,000 resamples of days, seed 0, task-weighted), cost per task, output
  and reasoning tokens, the error mix, truncations, whether it wrote a forecast and the DP on its own forecast.
- Paired, day-block CI: Beam − trained 4B (run 4 final, sampled), Beam − Luna-high, Beam − Sol.
- **Headroom for training:** teacher forecast + exact DP (0.920 on this pack) − Beam's best C, with its CI.
- The score-against-cost chart with Beam's points added; the frontier recomputed.

## Prior
C 0.78–0.91 at `high`, a little under Sol's 0.913; more output tokens than Sol (3–15k at `high`), so roughly
$0.004–0.02 per task: on or near the frontier between Luna-high and Sol.
