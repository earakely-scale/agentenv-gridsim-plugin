# Distilling the desk anchor into Qwen3.5-9B: pre-registration

Committed before any training data is generated and before any model plays a held-out window. Nothing below changes
after training data exists; anything done differently is logged under "Deviations", appended later.

## Question
Does Qwen3.5-9B (thinking on), fine-tuned with TRL `SFTTrainer` (LoRA) on transcripts of the desk's anchor, capture more
of hindsight than base Qwen3.5-9B on three-day desk-v4 windows it never trained on, both played in OpenCode?

## Teacher
The desk's information-matched anchor, `gridsim_core.desk.policies.anchor` (v4 setting: risk 1.5, DAM position spread):
at every wake but reminders it calls the agent-visible `optimize` tool and submits what it proposes
(`submit_dam_offers`, `submit_rt_offers`, `update_cop`, AS offers included). No third-party model's output is used.

## Windows
Pack `desk-v4-win` (task ids `desk-v4w-<d0>-<site>`), built by `scripts/desk_data_build.py desk-v4-win` with the
sources and rules of `desk-v4-train` (docs/desk-data.md §14): three operating days D0..D2 under the v4 layer at the
four desk sites; operating days only in 2025-12-20..2026-01-22 and 2026-05-11..2026-07-03; no DST change in D-8..D2;
no window holding 2026-01-08 or 2026-06-04 (gaps in the price history); every operating day more than 3 days from every
day of `desk-v4-bench`, `desk-v4-eval` and `desk-v4-pilot`. The lists are computed by
`scripts/desk_distill_windows.py`.

**Held-out (eval), 36 site-windows:** the windows starting 2026-01-09, 01-13, 01-17, 06-06, 06-09, 06-12, 06-15, 06-18
and 06-22, at S01–S04. They are nine of the 24 `desk-v4-train` windows and include its three val windows (01-13,
06-06, 06-09), so none of the 36 val days the GRPO kit evaluates on is trained on. Two contiguous blocks, one per
period, so that the lookback rule below costs the fewest training windows.

**Training, 144 site-windows:** every start d0 that meets the window rules and whose span holds no held-out operating
day, at S01–S04: 2025-12-20 through 2026-01-05 (17 starts) and 2026-05-14 through 2026-06-01 (19 starts). Starts one
day apart overlap; they are different episodes (start time, state of charge, the forecasts issued, the DAM gates).
They cover 40 distinct operating days.

**Leakage rule.** A window starting d0 reads the dates D-7..D2: the DAM and MCPC history D-7..D-1, RT and system series
D-1..D2, the operating days. No training window's span holds an operating day of a held-out window (the closest is two
days away), so no price, outcome or event a held-out window is scored on appears in training data. The desk forecast's
vintages for a window come from a model fitted on data before the window's month; ERCOT's forecasts are as issued.
Checked in code by `scripts/desk_distill_windows.py`: the span check asserts the rule on the lists; with `--pack` it
scans every date string in every training task's built series and reports any that falls on a held-out operating day.

## Training data
Transcripts of the anchor playing the training windows, rendered exactly as OpenCode sends Qwen3.5-9B's requests
through vLLM (its system prompt, the 29 tools under their `env####_` names, each wake as a JSON-string user message,
earlier wakes' reasoning dropped by the chat template). Each wake the anchor plans at: the `optimize` call, the
submits with their real outputs, then a reply without a tool call, which ends the turn in OpenCode. The thinking in
each assistant turn is a short rationale written by code from that wake's inputs only (the wake message and the
outputs of the calls made so far in that wake): never hindsight, references, the grade or later data.

Planned variant: the anchor planning at every other wake but reminders (on 215 single train days it kept 107% of the
full anchor's C with about two thirds of its tokens). Kept if, on the 144 training windows, its mean C is at least the
full anchor's minus 0.01 and its longest transcript fits the serving context below; otherwise the full anchor. The
choice and both numbers are reported before training.

## Eval protocol
- **Models.** Base: `Qwen/Qwen3.5-9B` at revision c202236235762e1c871ad0ccb60c8ee5ba337b9a, bf16. Student: the SFT LoRA
  merged into that base, saved with the base's tokenizer and processor files.
- **Serving.** vLLM 0.29.0, the same flags for both: `--served-model-name qwen3.5-9b --dtype bfloat16
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 --enable-prefix-caching
  --enable-prompt-tokens-details --language-model-only --max-model-len 262144`.
- **Harness.** OpenCode 1.17.18 on route C (local Docker, the host egress rule, the strict per-lane proxy), as the v4
  benchmark ran base Qwen3-4B, with the `opencode-qwen35-long` harness (`bench/harness/bench-opencode-qwen35-long`):
  temperature 0.6, top_p 0.95, top_k 20, min_p 0, thinking on, `limit` context 262,144 and output 8,192, so OpenCode
  never compacts a window. Bundle: `desk_bench.py tasks --harness opencode-qwen35-long --pack desk-v4-win` over the 36
  held-out windows.
- **Runs.** One scored attempt per model and window. A window that fails for infrastructure (the classes of the v4
  benchmark's pre-registration) is rerun, up to three attempts; anything the model does is scored as the grader scores
  it. Base and student run on the same instance type, four windows at a time per model, in the same order.
- **Score.** Hindsight capture C per window from the desk grader (`grade`), with R and P beside it.
- **Primary result.** The mean over the 36 windows of C(student) − C(base), with a 95% window-block bootstrap
  interval: the nine windows are the blocks, each resample draws nine windows with replacement and keeps their four
  sites, 10,000 resamples, seed 0, percentile interval. The student beats base when the interval's lower end is above
  0. Each model's mean C is reported with the same interval, and the anchor's C on the same windows beside them.
- **Also reported.** Per window the largest prompt OpenCode sent (tokens, from vLLM's usage); compaction events
  (expected 0); the env's refusal rate per submit tool (`submit_dam_offers`, `submit_rt_offers`, `update_cop`, and AS
  offers within them) for base, student and the anchor on the same windows; GPU time per window.
- **After.** An optional short GRPO from the SFT adapter is scored the same way on the same 36 windows. The 32-window
  benchmark run (base and best student as leaderboard rows) happens only after Edgar approves it.

## Secondary comparison: the benchmark
Only after the primary result is in, and only if Edgar approves the leaderboard run: base and student each play the 32
`desk-v4-bench` windows once in OpenCode, with the serving, harness and decoding of the primary eval
(`opencode-qwen35-long`, 262,144 tokens; base Qwen3-4B's leaderboard row ran at 32,768, which is noted beside the rows).
Secondary result: the mean over the 32 windows of C(student) − C(base) with a 95% front-block bootstrap interval (the
eight fronts are the blocks, 10,000 resamples, seed 0, percentile), and each model's C with the benchmark's own
interval. It is reported as secondary and does not change the primary verdict; infrastructure reruns follow the v4
benchmark's rules.

## Deviations
None yet.
