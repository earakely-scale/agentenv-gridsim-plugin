# Arm 2b (exploratory continuation): more GRPO from arm 2's step 75, Qwen3-1.7B on one L4

Arm 2b ran on 2026-10-24 UTC. It continues arm 2 (`../arm2/README.md`), which is SoC-aware SFT-1500 plus 75 GRPO steps. Arm 2's train reward was still rising at step 75, and the question was whether more GRPO clears the threshold rule (0.637). Nothing else changed: the same box, model, prompt and tools (path A equals path B), the same reward (`gridsim_core.trl.reward_fn`), and the same 200 eval-2025 tasks and decoding.

## Headline

1. **105 more GRPO steps (76–180) add about +0.09 to +0.10, and this time the gain is significant.**
   - The final model scores **R = 0.668 [0.629, 0.707] sampled** and **0.681 [0.644, 0.718] greedy**, with valid 99.5% and feasible 86%.
   - Paired against arm 2 (step 75): +0.089 [0.051, 0.127] sampled and +0.100 [0.063, 0.138] greedy.
   - Paired against SFT-2: +0.127 [0.074, 0.179] sampled.
2. **Threshold rule: the mean is above it, but the result is not significant.**
   - The mean beats threshold (0.637 [0.601, 0.673]): paired +0.031 [−0.022, +0.086] sampled and +0.044 [−0.010, +0.098] greedy. Both CIs include 0, and the unpaired CIs overlap.
   - Read: on par with, or slightly above, the threshold rule.
3. **Greedy rule:** still below it, by −0.096 [−0.143, −0.050] sampled and −0.083 [−0.129, −0.036] greedy.
4. **No cliff.**
   - Train R (T 1.1) moved from about 0.57 to 0.62–0.67, and feasibility from about 0.73 to 0.80–0.88.
   - Entropy went from 0.049 to 0.033, with a minimum of 0.020, so no step fell below 0.02 and none carries a note.
   - The zero-spread share stayed at 0–11% as a 10-step mean (single steps up to 37.5%).
   - The cliff guard never fired, and all 105 steps ran.
5. **Held-out checkpoints rise steadily** on the fixed 50-task subset (sampled):

| step | 75 (start) | 100 | 125 | 150 | 175 | 180 (final) |
|---|---|---|---|---|---|---|
| R | 0.561 | 0.625 | 0.694 | 0.721 | 0.732 | 0.726 |

   Unlike in arm 2, this direction agrees with the 200-task result. The final model scores 0.726 on these 50 tasks and 0.649 on the other 150.
6. **Best days:** 28 of 200 days score ≥ 0.95 under greedy decoding (arm 2: 18), and 8 hit the DP optimum (arm 2: 5).

## Results (200 eval-2025 tasks, foresight, oneshot prompt, path B)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | rate | end short | R empty / half / full start |
|---|---|---|---|---|---|---|---|---|---|---|
| base Qwen3-1.7B | both | 0.000 | [0, 0] | 0% | 0% | – | – | – | – | 0 / 0 / 0 |
| arm 1: SFT-200 + GRPO 280 | sampled | 0.329 | [0.306, 0.354] | 99.0% | 56.5% | 41.0% | 0% | 1.5% | 15.5% | 0.493 / 0.338 / 0.195 |
| arm 2: SFT-2 | sampled | 0.542 | [0.493, 0.589] | 99.0% | 64.0% | 15.5% | 9.0% | 8.0% | 5.5% | 0.555 / 0.471 / 0.600 |
| arm 2: SFT-2 | greedy | 0.583 | [0.534, 0.630] | 98.5% | 69.0% | 10.0% | 9.0% | 7.5% | 3.0% | 0.616 / 0.489 / 0.649 |
| arm 2: + GRPO 75 | sampled | 0.579 | [0.538, 0.620] | 99.5% | 77.5% | 10.0% | 5.0% | 7.0% | 2.5% | 0.599 / 0.640 / 0.504 |
| arm 2: + GRPO 75 | greedy | 0.582 | [0.539, 0.624] | 99.5% | 79.5% | 8.0% | 3.5% | 8.5% | 2.5% | 0.588 / 0.630 / 0.530 |
| **arm 2b: + GRPO 180** | sampled | **0.668** | [0.629, 0.707] | 99.5% | 86.0% | 4.5% | 5.0% | 4.0% | 6.5% | 0.692 / 0.687 / 0.632 |
| **arm 2b: + GRPO 180** | greedy | **0.681** | [0.644, 0.718] | 99.5% | 86.5% | 6.5% | 3.5% | 2.5% | 5.5% | 0.719 / 0.734 / 0.602 |
| greedy rule | – | 0.764 | [0.726, 0.800] | 100% | | | | | | 0.781 / 0.796 / 0.720 |
| threshold rule | – | 0.637 | [0.601, 0.673] | 100% | | | | | | 0.590 / 0.696 / 0.616 |
| clock rule | – | 0.498 | [0.460, 0.536] | 100% | | | | | | 0.465 / 0.527 / 0.495 |
| idle / DP optimum | – | 0.2 / 1.0 | | | | | | | | |

- **Start states** among the 200 tasks: 56 empty, 71 half, 73 full.
- **Arm 2b's other errors:** cycle cap 0–0.5%, malformed 0%, all-idle 0%.
- **By curriculum tag, arm 2b:** C0 0.736 / 0.743, C1 0.530 / 0.534, C2 0.667 / 0.691 (sampled / greedy).
- **Against threshold by start state** (greedy decoding), arm 2b leads on empty starts (0.719 vs 0.590), roughly ties on half starts (0.734 vs 0.696) and trails on full starts (0.602 vs 0.616). Full-start days remain the weakest group, as in arm 2.

**Paired gaps for arm 2b** (paired bootstrap, `summary.json`):

| arm 2b minus | sampled | greedy | arm 2b wins on (sampled) |
|---|---|---|---|
| arm 2 (step 75) | **+0.089 [0.051, 0.127]** | **+0.100 [0.063, 0.138]** | 42% of tasks (ties are common) |
| SFT-2 | +0.127 [0.074, 0.179] | +0.099 [0.051, 0.148] | 54% |
| threshold rule | +0.031 [−0.022, 0.086] | +0.044 [−0.010, 0.098] | 51% |
| greedy rule | −0.096 [−0.143, −0.050] | −0.083 [−0.129, −0.036] | 21% |

## Setup

- **Start policy:** arm 2's step-75 GRPO LoRA, merged into the merged SFT-2 model (`merge_adapter.py`), which gives the same policy as arm 2's final. A fresh LoRA (r=32, α=64, all attention and MLP projections) is trained on top.
  - Check on the 50-task subset (sampled): the merged start scores 0.561; arm 2's step-75 adapter scored 0.565.
  - Adam moments start fresh.
- **GRPO, the same as arm 2:**
  - 8 generations × 8 prompts = 64 rollouts per step (per-device batch 4, accumulation 16);
  - temperature 1.1; `dr_grpo`; β 0; ε 0.2/0.28; `scale_rewards="group"`;
  - mixed curriculum (each prompt draws a C0–C2 × start-state cell uniformly);
  - `max_completion_length` 512 (30 of 6,720 rollouts hit it); colocated vLLM 0.4; bf16.
- **What changed:**
  - **lr 1e-5** cosine over 105 steps with 5 warmup steps;
  - **seed 1**, so the sampler draws train tasks that arm 2's seed-0 order did not;
  - steps numbered from 76 to continue arm 2's count.
- **Checkpoints and guards:**
  - Checkpoints every 25 steps: TRL `checkpoint-25/50/75/100` are steps 100/125/150/175, and the final adapter is step 180.
  - A hard stop at 16:10 UTC (not reached).
  - Stop rule: an automatic stop if the 10-step mean train R fell below 0.45 or feasibility below 0.60. It never fired; the lowest 10-step means were R 0.551 and feasibility 0.716.

## Time and cost

| step | UTC | duration |
|---|---|---|
| merge | 13:18 | 1 min |
| GRPO | 13:19–15:52 | 105 steps, 2 h 33 min, 87.5 s/step |
| evals | 15:52–15:55 | 3 min |

- **Cost:** about 2.7 h of g6.4xlarge at $1.32/h ≈ **$3.60**. Lane T's total across arms 1, 2 and 2b is about 9.6 h ≈ **$12.70**. No API spend.

## Files

- `train_log.jsonl`: one row per continuation step, with `arm_step` = 75 + the TRL step. It has TRL's metrics (including `entropy`) plus R, R by start state, the valid and feasible rates, the error taxonomy, completion length and the zero-spread share.
- `curves.png`: arm 2 (steps 1–75) and arm 2b (76–180) on one axis.
  - top: train reward, overall and by start state, the held-out 50-task checkpoint evals, the 200-task evals of arm 2 and arm 2b, and the rule lines;
  - middle: valid, feasible and error rates;
  - bottom: entropy and the zero-spread share.
- `eval_start.json` (the merged start on the 50-task subset), `eval_trained.json` (step 180 on 200 tasks, sampled and greedy, with R by start state and by curriculum tag) and `eval_checkpoints.json`.
- `summary.json`: arm 1, SFT-2, arm 2, arm 2b and the rules, with CIs and R by start state, plus paired bootstrap gaps of arm 2b against arm 2, SFT-2, threshold and greedy.
- `episodes/*.jsonl`: path-B `gridsim.episode/v1`, one per line.
  - `trained-*`: 200 tasks at step 180.
  - `ckpt-0100/0125/0150/0175-sampled`: the 50-task subset.
  - `start-sampled`: the merged start on the 50-task subset.
- `levelup/<task_id>/<frame>.json`: the same 12 days as arm 2, with every frame: `base`, `0000` (SFT-2), `0025`, `0050`, `0075` (copied from arm 2), then `0100`, `0125`, `0150`, `0175` and `0180` (final). `0195` does not exist: the run was 105 steps.
  - `levelup/index.json` lists each day's per-frame reward.
  - Good arcs: `dam-v1-2025-01-14-LZ_HOUSTON-4h-x` (0.39 → 0.22 → 0.80 from step 125), `dam-v1-2025-06-29-HB_NORTH-1h-v` (0.81 → 0 for steps 25–100 → 0.80 from step 125), `dam-v1-2025-01-14-HB_HOUSTON-2h-q` (0.32 → 0.98 at step 180) and `dam-v1-2025-06-06-LZ_CPS-1h-l` (0 → 0.15 → 0.98).
  - One full-start day stays bad: `dam-v1-2025-03-26-HB_PAN-2h-c` (0.64 at SFT-2, 0 from step 125).
- `scripts/`: `train.py`, `merge_adapter.py`, `evaluate.py`, `pathb.py`, `report2b.py` and the unit script.

## Adapter

- **Key:** `gridsim/adapters/qwen3-1.7b-gridsim-v1-arm2b-grpo180-seed1.tgz` in Scale-internal object storage, 776 MB.
- **Contents:** `adapter/grpo2b-lora/` (step 180) and `adapter/checkpoints/checkpoint-{25,50,75,100}/` (TRL numbering; add 75 for the arm step).
- **Base stack:** `Qwen/Qwen3-1.7B`. Merge in arm 2's `sft2-lora`, then arm 2's `grpo-lora` (step 75), then apply `grpo2b-lora`.

## Reading

- **More GRPO at this exploration level kept paying.** It made a significant +0.09 to +0.10 over arm 2, moving the 1.7B from below threshold to level with it. Entropy and the zero-spread share stayed healthy, and the 50-task checkpoints were still rising at step 175 (0.732).
- **Greedy (0.764) is still 0.08 to 0.10 away.** The remaining errors are spread thin: overfill 4.5–6.5%, sell-before-charge 3.5–5%, end-short 5.5–6.5%. Most of the gap is sub-optimal but feasible plans; 80% of completions are rule-clean.
- **Likely next levers:**
  - more steps (the curve has not flattened);
  - a second SFT-2 epoch;
  - full-start days, which are the weakest group;
  - the 4B model.
