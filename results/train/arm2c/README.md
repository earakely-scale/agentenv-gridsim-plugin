# Arm 2c (exploratory continuation): 150 more GRPO steps from arm 2b's step 180, Qwen3-1.7B on one L4

Arm 2c ran on 2026-10-24 UTC. It continues arm 2b (`../arm2b/README.md`), which continued arm 2 (`../arm2/README.md`). Nothing else changed: the same box, model, prompt and tools (path A equals path B), the same reward (`gridsim_core.trl.reward_fn`), and the same 200 eval-2025 tasks and decoding.

## Headline

1. **After 330 GRPO steps in all, the 1.7B clears the threshold rule with non-overlapping CIs.**
   - It scores **R = 0.720 [0.681, 0.756] sampled** and **0.719 [0.681, 0.757] greedy**.
   - Valid is 100% sampled and 99% greedy; feasible is 92.5% and 91.5%.
   - Against threshold (0.637 [0.601, 0.673]): paired **+0.083 [0.031, 0.135]** sampled and **+0.082 [0.029, 0.137]** greedy. Arm 2c wins on 56% of tasks.
2. **Against arm 2b:** +0.051 [0.017, 0.086] sampled and +0.038 [0.003, 0.075] greedy. Both are significant.
3. **Greedy rule (0.764 [0.726, 0.800]): not beaten, and no longer significantly behind.**
   - Paired −0.044 [−0.091, +0.002] sampled and −0.045 [−0.091, +0.003] greedy. The CIs overlap.
   - Greedy still wins on more days: arm 2c wins on 23% of tasks.
4. **Best days:** 41 of 200 days score ≥ 0.95 under greedy decoding, and 12 hit the DP optimum (arm 2b: 28 and 8).
5. **Held-out checkpoints** on the fixed 50-task subset (sampled):

| step | 180 (merged start) | 205 | 230 | 255 | 280 | 305 | 330 (final) |
|---|---|---|---|---|---|---|---|
| R | 0.723 | 0.756 | 0.752 | 0.757 | 0.782 | 0.785 | 0.780 |

   The curve is flattening.
6. **Entropy dipped below 0.02 on 19 of 150 steps** (minimum 0.0137). Those rows carry `"note": "entropy below 0.02"` and the run was not stopped. The zero-spread share stayed at a 10-step mean of 0–18%.
7. **The cliff guard never fired.** The lowest 10-step means were R 0.605 and feasibility 0.78.

## Results (200 eval-2025 tasks, foresight, oneshot prompt, path B)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | rate | end short | R empty / half / full start |
|---|---|---|---|---|---|---|---|---|---|---|
| arm 2: SFT-2 + GRPO 75 | sampled | 0.579 | [0.538, 0.620] | 99.5% | 77.5% | 10.0% | 5.0% | 7.0% | 2.5% | 0.599 / 0.640 / 0.504 |
| arm 2b: + GRPO to 180 | sampled | 0.668 | [0.629, 0.707] | 99.5% | 86.0% | 4.5% | 5.0% | 4.0% | 6.5% | 0.692 / 0.687 / 0.632 |
| arm 2b: + GRPO to 180 | greedy | 0.681 | [0.644, 0.718] | 99.5% | 86.5% | 6.5% | 3.5% | 2.5% | 5.5% | 0.719 / 0.734 / 0.602 |
| **arm 2c: + GRPO to 330** | sampled | **0.720** | [0.681, 0.756] | 100% | 92.5% | 3.0% | 2.5% | 2.0% | 9.0% | 0.734 / 0.754 / 0.676 |
| **arm 2c: + GRPO to 330** | greedy | **0.719** | [0.681, 0.757] | 99.0% | 91.5% | 1.5% | 3.5% | 2.5% | 9.0% | 0.753 / 0.731 / 0.682 |
| greedy rule | – | 0.764 | [0.726, 0.800] | 100% | | | | | | 0.781 / 0.796 / 0.720 |
| threshold rule | – | 0.637 | [0.601, 0.673] | 100% | | | | | | 0.590 / 0.696 / 0.616 |
| clock rule | – | 0.498 | [0.460, 0.536] | 100% | | | | | | 0.465 / 0.527 / 0.495 |

- The base model scores 0.000, arm 1 0.329 and SFT-2 0.542 / 0.583 (see `../arm2/README.md`).
- **Start states** among the 200 tasks: 56 empty, 71 half, 73 full.
- **Arm 2c's other errors:** malformed 0–0.5%, cycle cap 0%, all-idle 0%.
- **The remaining main error is end-short (9%):** the schedule finishes below `s_end_min` and pays the buy-back.
- **By start state:** arm 2c now beats threshold on every start state, but greedy still leads on each.

**Paired gaps for arm 2c** (paired bootstrap, 10,000 resamples, `summary.json`):

| arm 2c minus | sampled | greedy | arm 2c wins on (sampled) |
|---|---|---|---|
| arm 2b (step 180) | **+0.051 [0.017, 0.086]** | **+0.038 [0.003, 0.075]** | 39% of tasks (ties are common) |
| arm 2 (step 75) | +0.141 [0.096, 0.187] | +0.138 [0.091, 0.185] | 56% |
| threshold rule | **+0.083 [0.031, 0.135]** | **+0.082 [0.029, 0.137]** | 56% |
| greedy rule | −0.044 [−0.091, +0.002] | −0.045 [−0.091, +0.003] | 23% |

## Setup

- **Start policy:** arm 2b's step-180 LoRA, merged into the arm-2 step-75 merged model (`merge_adapter.py`).
  - So the stack is `Qwen/Qwen3-1.7B` + SFT-2 + arm 2's step-75 LoRA + arm 2b's LoRA, all merged.
  - A fresh LoRA (r=32, α=64, all attention and MLP projections) is trained on top; Adam starts fresh.
  - Check on the 50-task subset (sampled): the merged start scores 0.723; arm 2b's final scored 0.726 there.
- **GRPO, the same as arms 2 and 2b:**
  - 8 generations × 8 prompts = 64 rollouts per step (per-device batch 4, accumulation 16);
  - temperature 1.1; `dr_grpo`; β 0; ε 0.2/0.28; `scale_rewards="group"`;
  - mixed curriculum (each prompt draws a C0–C2 × start-state cell uniformly);
  - `max_completion_length` 512 (69 of 9,600 rollouts hit it); colocated vLLM 0.4; bf16.
- **What changed:**
  - lr 1e-5 cosine over 150 steps with 5 warmup steps;
  - **seed 2**, for new task draws;
  - steps numbered 181–330.
- **Checkpoints:** every 25 steps. TRL `checkpoint-25 … 125` are steps 205–305; the final adapter is step 330.
- **Guards:**
  - The same cliff guard as arm 2b: stop if the 10-step mean R fell below 0.45 or feasibility below 0.60.
  - **The training hard stop was 20:00 UTC, not 20:15.** The box powers off around 20:20, and the evals plus the result push need about 6 minutes. It was not reached: all 150 steps finished at 19:43.

## Time and cost

| step | UTC | duration |
|---|---|---|
| merge | 15:59 | under 1 min |
| GRPO | 15:59:44–19:43 | 150 steps, 3 h 43 min including vLLM start, 89 s/step |
| evals | 19:43–19:47 | 4 min |

- **Result push:** the unit's own push to S3 failed because its presigned URLs had expired by 19:47. The tarballs were pushed again by hand at 19:49 with fresh URLs, and no data was lost.
- **Cost:** about 3.9 h of g6.4xlarge at $1.32/h ≈ **$5.10**. Lane T's total across arms 1, 2, 2b and 2c is about 13.5 h ≈ **$17.80**. No API spend.

## Files

- `train_log.jsonl`: one row per step, with `arm_step` = 180 + the TRL step. It has TRL's metrics (including `entropy`) plus R, R by start state, the valid and feasible rates, the error taxonomy, completion length, the zero-spread share and the low-entropy `note`.
- `curves.png`: arms 2 (steps 1–75), 2b (76–180) and 2c (181–330) on one axis.
  - top: train reward, overall and by start state, the held-out 50-task checkpoint evals, the 200-task evals of each arm, and the rule lines;
  - middle: valid, feasible and error rates;
  - bottom: entropy and the zero-spread share.
- `eval_start.json` (the merged start on the 50-task subset), `eval_trained.json` (step 330 on 200 tasks, sampled and greedy, with R by start state and by curriculum tag) and `eval_checkpoints.json`.
- `summary.json`: arm 2, arm 2b, arm 2c and the rules, with CIs and R by start state, plus paired gaps against arm 2b, arm 2, threshold and greedy.
- `episodes/*.jsonl`: path-B `gridsim.episode/v1`, one per line.
  - `trained-*`: 200 tasks at step 330.
  - `ckpt-0205 … ckpt-0305-sampled`: the 50-task subset.
  - `start-sampled`: the merged start on the 50-task subset.
- `levelup/<task_id>/<frame>.json`: the same 12 days with every frame.
  - Frames: `base`, `0000` (SFT-2), `0025` … `0075` (arm 2), `0100` … `0180` (arm 2b), then `0205`, `0230`, `0255`, `0280`, `0305`, `0330` (arm 2c).
  - `levelup/index.json` lists each day's per-frame reward.
- `scripts/`: the code and the unit script, with the presigned-URL lines removed.

## Adapter

- **Key:** `gridsim/adapters/qwen3-1.7b-gridsim-v1-arm2c-seed2.tgz` in Scale-internal object storage, 905 MB.
- **Contents:** `adapter/grpo2c-lora/` (step 330) and `adapter/checkpoints/checkpoint-{25,50,75,100,125,150}/` (TRL numbering; add 180 for the arm step).
- **Base stack:** `Qwen/Qwen3-1.7B`. Merge arm 2's `sft2-lora`, then arm 2's `grpo-lora`, then arm 2b's `grpo2b-lora`, then apply `grpo2c-lora`.
