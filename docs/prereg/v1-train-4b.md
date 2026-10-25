# GridSimEnv v1 training, Qwen3-4B (path B): pre-registration

Committed before any 4B training step or 4B eval. This is the first pre-registered training claim on GridSimEnv. The 1.7B arms in `results/train/` (arm 1, arms 2, 2b and 2c) were exploratory: each was designed after seeing the one before it. This run takes their recipe as one fixed schedule and tests it once on a larger model.

Nothing below changes after the main run starts. Nothing is rerun to improve a score. The only allowed change is a pre-run amendment from the 5-step smoke (see "Smoke and amendments"), appended here and committed before the main run starts.

## Model
- `Qwen/Qwen3-4B` at Hub revision `1cfa9a7208912126459214e8b04321603b3df60c` (Apache-2.0), bf16.
- Thinking off: `enable_thinking=False` in the chat template, for training and eval.
- Prompt and tools: `gridsim_core.prompt.messages(task, "foresight", 0)` + `tool_schemas("foresight", 0)`, the oneshot prompt. One completion, which must end in a `submit_schedule` tool call.
- Reward: `gridsim_core.trl.reward_fn` exactly (`extract_actions`, then `grade`). There is no format credit.

## Schedule (one run, seed 0)
1. **SFT warm start (SFT-1500, SoC-aware).**
   - Data: 1,500 DP-optimal schedules from `ercot-dam-v1-train`, stratified over the 9 cells (curriculum C0–C2 × start empty/half/full).
   - Each completion is a template rationale, then the tool call. The rationale gives the start state, the end obligation, the cycle cap, the 3 cheapest and 3 dearest hours, and the plan with the SoC after each trade.
   - Training: LoRA r=32, α=64, on all attention and MLP projections; lr 1e-4 with cosine decay and 10% warmup; batch 8; 1 epoch. The adapter is merged into the base.
   - Code: `results/train/arm2/scripts/sft.py` with `RATIONALE=soc STRATIFY=start`.
2. **GRPO from the merged SFT model.**
   - A fresh LoRA (r=32, α=64, same modules); TRL 1.15 `GRPOTrainer` with colocated vLLM 0.29.
   - Batch: 8 prompts × 8 generations = 64 rollouts per step, at temperature 1.1.
   - Loss: `dr_grpo`, β 0, ε 0.2 / ε_high 0.28, `scale_rewards="group"`, `max_completion_length` 512.
   - Mixed curriculum: each prompt draws a (curriculum × start state) cell uniformly, then a task in that cell.
   - **Steps: 330, with lr 1e-5, cosine decay to 0 and 5 warmup steps.** This is one schedule. The 330 matches the 1.7B's total GRPO steps over arms 2, 2b and 2c, which were three restarted cosine segments; here it is a single segment.
   - Checkpoints every 25 steps: 25 … 325, then the final step 330.
   - Code: `results/train/arm2c/scripts/train.py`, changed only to arm the cliff guard as described below.
- **Seeds:** 0 for the SFT data pick and shuffle, for the GRPO task draws and the TRL seed, and for eval sampling. There is one seed, so seed variance is not measured.
- **Engineering settings that are not part of the recipe:** the per-device batch and gradient accumulation (the product stays 64 rollouts per step), vLLM `gpu_memory_utilization`, and the max model length (2,048). The smoke may tune these.
- **The claim is the final adapter** (step 330, or the step where a stop rule fired). There is no checkpoint picking. The checkpoint evals are diagnostics only.

## Eval
- **Tasks:** the same 200 eval-2025 foresight tasks as the 1.7B arms. They are a seeded sample (`default_rng(20251)`) of `ercot-dam-v1-eval`, 2025-01-01 to 2025-11-30, held out from training. The first 50 are the fixed checkpoint subset.
- **Decoding:**
  - **Sampled (primary):** T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task.
  - **Greedy (secondary).**
  - Both use max_tokens 512, through `results/train/arm2c/scripts/evaluate.py`.
- **Statistics:**
  - Mean R with a 95% bootstrap CI over tasks (10,000 resamples).
  - Paired differences on the same tasks, with a 95% paired-bootstrap CI (10,000 resamples) and the win rate.
- **Also reported:** valid, feasible and the error taxonomy (overfill, sell before charge, rate, cycle cap, end short, all-idle, malformed, truncated), and R by start state and by curriculum tag.
- **Models evaluated:**
  - the base Qwen3-4B, zero-shot, on 200 tasks (sampled and greedy);
  - the SFT-only checkpoint (step 0), on 200 tasks (sampled and greedy);
  - each GRPO checkpoint, on the 50-task subset (sampled);
  - the final adapter, on 200 tasks (sampled and greedy).

## Bars
- **PRIMARY:** the trained 4B (final adapter, sampled) beats the greedy rule.
  - Its 95% CI must lie wholly above greedy's: lower bound > 0.800, given greedy's 0.764 [0.726, 0.800] on these tasks.
  - It must also have **≥ 98% valid schedules**.
  - Both conditions must hold.
- **SECONDARY:** the paired difference (trained 4B sampled minus greedy rule) has a 95% CI wholly above 0.
- **Reported, with no bar:**
  - against the threshold rule (0.637), as a paired difference;
  - against the 1.7B arm 2c (0.720 sampled / 0.719 greedy), paired on the same 200 tasks using arm 2c's committed per-task rewards;
  - against the base 4B and the SFT-only checkpoint;
  - all of these for greedy decoding as well.
- **Prior (stated so the outcome can be checked against it):**
  - The 1.7B with the same recipe and step count reached 0.720.
  - We expect the 4B to land between 0.72 and 0.84, so the primary bar is uncertain: a CI lower bound above 0.800 needs a mean near 0.84.
  - The secondary bar needs a mean of about 0.81.

## Stop rules
- **Cliff guard.**
  - Stop if the 10-step mean train reward falls below 0.45, or the 10-step mean feasibility below 0.60.
  - The guard arms the first time both 10-step means are at or above those levels. A cliff is a fall from a level the run has reached.
  - From an SFT start, the 1.7B's first 10 steps averaged R 0.39 and feasibility 0.39 (arm 2), so an always-on guard would stop a healthy run at step 10.
  - If the guard fires, the run stops and saves, and the adapter at that step is the claim.
- **Wall clock.**
  - The box powers itself off at 16:14 UTC on 2026-10-25.
  - GRPO stops and saves at **14:15 UTC** whatever its step, which leaves time for the evals and the upload. The adapter at that step is then the claim, with the step reported.
- **Crash.**
  - A crash from an infrastructure or code fault (not the guard) gets one restart from scratch with the same seed, if the time left fits the full step count.
  - Otherwise the last saved checkpoint is evaluated as the claim and labelled a short run.
- **Entropy:** below 0.02 is logged as a note and does not stop the run, as in arms 2b and 2c.

## Smoke and amendments
- A 5-step GRPO smoke runs on the merged SFT model before the main run. It measures seconds per step and peak memory, then is discarded.
- **If 330 steps at the measured rate (plus 5%) would not end by 14:15 UTC,** the step count is lowered to the largest multiple of 5 that fits. The lr, warmup and cosine stay as registered over the new count.
- That change, and any change to the engineering settings, is appended below and committed before the main run. The step count is never raised.

## Budget
- **Box:** one g6e.4xlarge (1× NVIDIA L40S 48 GB, 16 vCPU, 128 GB RAM) in us-west-2, at $3.004/h on demand. It launched at 00:13 UTC on 2026-10-25 and powers off by 16:14, so the cap is about 16 h, or about $48.
- **API spend:** none.

## Published whatever the outcome
These go to `results/train/4b/`, with the README labelled "registered run":
- `README.md` with the bar verdicts;
- `summary.json` with the verdicts, the CIs and the paired gaps;
- `curves.png` (train reward, held-out checkpoints and the rule lines; valid, feasible and errors; entropy and zero-spread);
- `train_log.jsonl`;
- `eval_base.json`, `eval_sft.json`, `eval_checkpoints.json` and `eval_trained.json`;
- `episodes/*.jsonl` (`gridsim.episode/v1`);
- LEVEL UP frames: `levelup/<task_id>/<frame>.json` on the same 12 days the 1.7B arms used, with frames `base`, `0000` (SFT), every checkpoint, and the final;
- `scripts/` (the exact code and unit scripts) and `pip_freeze.txt`.

The adapter goes to Scale-internal object storage under `gridsim/adapters/qwen3-4b-gridsim-v1-reg-seed0.tgz`, with the SFT adapter and the checkpoints. Any deviation from this file is listed in the README.

## Amendments
(none yet)
