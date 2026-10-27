# GridSimEnv v1: the trained Qwen3-4Bs against cost-matched GPT-6 Luna (pre-registration)

Committed and pushed to `main` before any GPT-6 Luna request, the smoke included. There is no training and no GPU
work: the 4B's side of every comparison is its committed per-task results, unchanged.

## The question
Our trained 4Bs trail GPT-6.1 Sol on both tiers, but Sol costs far more per battery-day. **GPT-6 Luna**
(`openai/gpt-6-luna`) is priced at $0.10 / $0.50 / $0.01 per million input / output / cached-input tokens
(`agents/gridsim-llm/agent.py`'s `PRICES`), 1/20th of Sol's $2.00 / $10.00 / $0.10 and in the same cost range as a
self-hosted 4B. Does the trained 4B earn more than the frontier model at its price? Sol stays in every table as the
ceiling reference.

## Three contests, four packs, each under exactly the harness its 4B and Sol already used

| contest | tasks | the 4B (fixed, committed) | Sol reference (committed) | Luna's harness |
|---|---|---|---|---|
| **1. Foresight, eval-2025** | run 3's 200 eval-2025 tasks (157 days; `results/train/4b-dpa/eval_trained.json`'s `task_ids`) | registered run 3 final (step 300), `eval_trained.json` | the board's `oneshot` column on these 200 tasks (`results/runs/v1-board-sol-oneshot{,-amend}`, effort high; one task is the amendment's row) | `results/fresh/2026-10/scripts/sol_eval.py`'s `request` and `score`, tier `foresight` |
| **2. Foresight, fresh** | `ercot-dam-v1-fresh-2026-10`, 362 tasks, 2026-10-18..27 (10 days) | run 3 final, `results/fresh/2026-10/eval_run3.json` | `results/fresh/2026-10/eval_sol.jsonl.gz` (path B, effort high) | the same `sol_eval.py` functions |
| **3a. Blind, eval-2025** | the 300 `blind_eval` tasks of `ercot-dam-v1-eval` (191 days) | registered run 4 final (RL step 237), `results/train/4b-blind/eval_final.json`, pack `eval2025` | `results/train/4b-blind/sol/sol-ercot-dam-v1-eval.jsonl.gz` (same single-call prompt, effort high) | `results/train/4b-blind/scripts/sol_blind.py`'s `request` and `score` (the blind path-B prompt plus `gridsim_core.forecast`'s "you may write your forecast first" paragraph) |
| **3b. Blind, fresh** | `ercot-dam-v1-fresh-2026-10-blind`, 331 tasks (10 days) | run 4 final, `eval_final.json`, pack `fresh` | `results/train/4b-blind/sol/sol-ercot-dam-v1-fresh-2026-10-blind.jsonl.gz` | the same `sol_blind.py` functions |

- **The harness is reused, not re-implemented.** `results/cost-matched/scripts/luna_eval.py` imports the committed Sol
  scripts and calls their `request` and `score` functions unchanged. The request it sends differs from Sol's in the
  `model` field alone (and in the reasoning effort for the secondary row). This was checked on the first task of every
  pack before this commit, with no request sent.
  - Prompts: `gridsim_core.prompt` (`system_prompt`, `situation_text`, `tool_schemas`; `forecast=True` on blind).
  - Grading: `gridsim_core.trl.extract_actions`, then `grade`; the error kind from `pathb.kind_of` /
    `pathb_blind.graded`.
  - Contest 1's Sol reference ran through the env's `oneshot` bundle (path A), which sends the same prompt (README,
    "Harnesses"); it is a reference row only.
- **Luna's request:** one Responses-API request per task through LiteLLM, one sample, `max_output_tokens` 16,384,
  streamed, `store` off, reasoning summary `auto`, as Sol's.

## Luna's setting
- **Primary: reasoning effort `high`**, the setting Sol used everywhere above. One sample per task.
- **Secondary (labelled, never the headline): effort `low`.** It runs on a pack only if Luna-high's mean cost per task
  there is **more than 3×** the 4B's (sampled) cost per task on the same pack, as computed below. If the endpoint
  rejects `low` for Luna (found on the smoke), the secondary uses `medium`; if it rejects both, there is no secondary.
- **Smoke first:** 2 fixture tasks (`data/fixtures`) at effort high and 1 at low, before any scored request; they are
  not scored and count toward the spend.

## Metrics (the cross-version rule)
- **Foresight (contests 1 and 2):** mean **R**, the contract reward with the DP optimum as anchor. On foresight R is
  already the repo's hindsight capture `r_opt` (the anchor is P_opt). Also reported, as the brief asks, the raw
  hindsight capture **x = (R − 0.2) / 0.8**. It is a linear rescale of R, so every verdict on x equals R's.
- **Blind (contests 3a and 3b):** mean hindsight capture **C** = `r_opt` = clip(0.2 + 0.8 (P − P_idle) / (P_opt −
  P_idle), 0, 1), as runs 4 and L1 report it. R on the blind anchor's scale is a second column.
- No valid `submit_schedule` scores 0 (R and C). It is not retried.
- **Paired differences**, same tasks: **4B − Luna** (the headline), and as references **4B − Sol** and **Luna − Sol**,
  each for the 4B's sampled decoding (primary) and greedy decoding (secondary).
- **CIs:** a **day-block bootstrap**: 10,000 resamples of the pack's days with replacement, seed 0, every task of a
  drawn day kept, task-weighted mean; the same resample is applied to the per-task paired difference (report_blind.py's
  `boot` / `paired`).
- **Error mix** per model: invalid or no submit (malformed, truncated, infra error), overfill, sell before charge, end
  short; also all-idle, rate, cycle cap and feasible.
- **The share of tasks where the 4B earns more than Luna** (score difference > 1e-9), where they are level, and the
  days on which the 4B's day mean is ahead.
- Luna's tokens (input, output, reasoning, cached), wall time and every infra retry.

## Cost per task
- **Luna and Sol:** actual token usage × the price table: (input − cached) × input price + cached × cached price +
  output × output price (reasoning tokens are output). Sol's committed records already carry this (`usd`, `cost_usd`).
  A request with no response has no usage and costs 0 here; any such request is listed.
- **The 4B:** the logged GPU wall time of its evaluation pass (`wall_s` in the committed eval files: vLLM's batched
  `generate` over the whole pack, engine start excluded) × the hourly price of the GPU it ran on ÷ the pack's tasks.
  - **Assumption: a busy GPU.** It is billed only while generating: a continuously used serving GPU, with no idle time,
    no engine start and no model load charged. On-demand Linux prices from the AWS price list (effective 2026-10-01).
  - **Contests 1 and 2:** a g5.12xlarge (4× A10G 24 GB), us-east-1, $5.672/h; each pass ran on one of its four GPUs,
    so **$1.418 per GPU-hour**. Contest 1: 67.3 s for 200 tasks (T6's box) → **$0.000133/task**. Contest 2: 128.4 s
    for 362 (L1's box) → **$0.000140/task**.
  - **Contest 3:** a g6e.8xlarge (1× L40S 48 GB), us-west-2, **$4.529/h** (T7's box). 3a: 114.3 s for 300 →
    **$0.000479/task**. 3b: 124.8 s for 331 → **$0.000474/task**.
  - **Sensitivity (reported):** the whole g5.12xlarge billed for a one-GPU pass (×4 on contests 1 and 2).
  - Training is not in the per-task cost (run 3 about $31, run 4 about $40 of GPU); it is reported alongside.
- **Committed Sol cost per task:** contest 1 $0.0120, contest 2 $0.0103, 3a $0.0158, 3b $0.0159.

## The headline test
**"The trained 4B earns more than cost-matched Luna"**: on a pack, the day-block 95% CI of the paired difference
**4B (sampled) − Luna (effort high)** lies wholly above 0. It is tested **on each of the four packs separately** (1, 2,
3a, 3b), with no pooling across packs or contests and no multiplicity correction. Each pack gets one of: **4B ahead**
(CI above 0), **Luna ahead** (CI below 0) or **not separated**. The secondary rows (Luna low, the 4B's greedy
decoding) are reported with the same CIs and carry no verdict.

## Spend, failures and order
- **Cap: $10 of Luna spend in total**, the smoke and any secondary included. A guard starts a request only if spend +
  every in-flight request's worst case + its own worst case (16,384 output tokens) stays under the cap. From 25
  finished tasks of a run on, no further request starts once spend + the run's mean cost × (its unstarted tasks +
  the tasks of the planned high-effort runs after it) exceeds the cap. Tasks left unrun are listed and excluded from
  Luna's paired gaps.
- **Infra failures** (a provider or gateway error, no response) are retried at most twice, and every retry is recorded.
  A task still without a response after three attempts scores 0 and is listed as an infra error.
- **Concurrency 8**, from a laptop.
- **Order:** smoke → 1 → 2 → 3a → 3b at effort high → the triggered secondary rows in the same order.
- One pass per (pack, effort); nothing rerun to improve a score; no prompt change.

## Prior (stated so the outcome can be checked against it)
- **Luna, foresight:** R 0.80–0.97. Foresight is a calculation that a reasoning model can do; a small one makes more
  rule errors (overfill, end short) than Sol's ~1.0. The 4B (0.885 on 1, 0.855 on 2) ahead with its CI above 0:
  about 25% on contest 1 and 20% on contest 2.
- **Luna, blind:** C 0.80–0.90, a little under Sol's 0.903 / 0.913, with more invalid or broken schedules. The 4B
  (0.828 / 0.841) ahead: about 15% on each blind pack.
- **Cost:** Luna-high at about $0.0005–$0.002 per task (Sol's tokens × 1/20th if it reasons as long as Sol), so 1–15×
  the 4B on foresight and 1–4× on blind; the secondary most likely runs on contests 1 and 2.

## Published whatever the outcome
`results/cost-matched/`: `README.md` (the three contests' tables with Sol as reference, the paired CIs, the verdicts,
the error mix, cost per task, and a chart of score against cost per task on a log axis for the 4B, Luna and Sol),
`summary.json`, Luna's per-task records and episodes, and `scripts/`.

## Amendments
None yet.
