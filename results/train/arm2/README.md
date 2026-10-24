# Arm 2 (exploratory, not pre-registered): SoC-aware warm start + exploratory GRPO, Qwen3-1.7B on one L4

Arm 2 ran on 2026-10-24 UTC, after arm 1 (`../README.md`).
- **Kept from arm 1:** the box, the model (`Qwen/Qwen3-1.7B`, bf16, thinking off), the prompt and tools (`gridsim_core.prompt.messages(task, "foresight", 0)` + `tool_schemas("foresight", 0)`, which keeps path A equal to path B), the action format, the reward (`gridsim_core.trl.reward_fn`), the 200 eval-2025 tasks and the eval decoding.
- **Changed:** the warm start (SoC-aware, 1,500 examples) and the GRPO exploration settings.
- **Not pre-registered:** this arm was designed after seeing arm 1's results, so it is labelled exploratory.

## Headline

1. **The SoC-aware warm start does most of the work.**
   - SFT-2 alone scores 0.542 [0.493, 0.589] sampled and 0.583 [0.534, 0.630] greedy.
   - Arm 1's SFT-200 + GRPO-280 scored 0.329.
2. **GRPO on top adds little that we can measure.**
   - After 75 steps the model scores **R = 0.579 [0.538, 0.620] sampled** and **0.582 [0.539, 0.624] greedy**, with valid 99.5%.
   - Paired against SFT-2: +0.037 [−0.016, +0.091] sampled and −0.001 [−0.054, +0.052] greedy. Neither is significant.
   - GRPO did raise feasibility (64% → 77.5% sampled) and the half-start days (0.471 → 0.640). It lost ground on full-start days (0.600 → 0.504).
3. **Against arm 1:** +0.250 [0.207, 0.292] sampled, winning on 74% of tasks.
4. **It clears neither rule.**
   - **Threshold (0.637 [0.601, 0.673]):** the CIs overlap. Paired gap −0.058 [−0.113, −0.004] sampled and −0.055 [−0.112, +0.001] greedy.
   - **Greedy (0.764 [0.726, 0.800]):** paired gap −0.185 [−0.237, −0.133].
5. **Exploration stayed alive**, unlike arm 1.
   - Entropy went from 0.081 to 0.046; the minimum was 0.023, never below 0.02.
   - The zero-spread share stayed at 0–6% (arm 1 reached 56%).
   - Sampled and greedy schedules are identical on 94 of 200 tasks (arm 1: 193).
   - 18 of 200 days score ≥ 0.95 under greedy decoding, and 5 hit the DP optimum.

## Results (200 eval-2025 tasks, foresight, oneshot prompt, path B)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | rate | end short | malformed | R empty / half / full start |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-1.7B base | sampled | 0.000 | [0.000, 0.000] | 0% | 0% | – | – | – | – | 100% | 0 / 0 / 0 |
| arm 1: SFT-200 | sampled | 0.234 | [0.209, 0.260] | 99.0% | 30.5% | 49.5% | 11.0% | 3.5% | 9.0% | 1.0% | 0.247 / 0.258 / 0.200 |
| arm 1: SFT-200 + GRPO 280 | sampled | 0.329 | [0.306, 0.354] | 99.0% | 56.5% | 41.0% | 0% | 1.5% | 15.5% | 1.0% | 0.493 / 0.338 / 0.195 |
| arm 1: SFT-200 + GRPO 280 | greedy | 0.329 | [0.305, 0.354] | 98.5% | 56.5% | 41.0% | 0% | 1.0% | 15.5% | 1.5% | 0.497 / 0.335 / 0.195 |
| **arm 2: SFT-2 (SoC-aware, 1,500)** | sampled | **0.542** | [0.493, 0.589] | 99.0% | 64.0% | 15.5% | 9.0% | 8.0% | 5.5% | 0.5% | 0.555 / 0.471 / 0.600 |
| **arm 2: SFT-2** | greedy | **0.583** | [0.534, 0.630] | 98.5% | 69.0% | 10.0% | 9.0% | 7.5% | 3.0% | 1.5% | 0.616 / 0.489 / 0.649 |
| **arm 2: SFT-2 + GRPO 75** | sampled | **0.579** | [0.538, 0.620] | 99.5% | 77.5% | 10.0% | 5.0% | 7.0% | 2.5% | 0% | 0.599 / 0.640 / 0.504 |
| **arm 2: SFT-2 + GRPO 75** | greedy | **0.582** | [0.539, 0.624] | 99.5% | 79.5% | 8.0% | 3.5% | 8.5% | 2.5% | 0% | 0.588 / 0.630 / 0.530 |
| greedy rule | – | 0.764 | [0.726, 0.800] | 100% | | | | | | | 0.781 / 0.796 / 0.720 |
| threshold rule | – | 0.637 | [0.601, 0.673] | 100% | | | | | | | 0.590 / 0.696 / 0.616 |
| clock rule | – | 0.498 | [0.460, 0.536] | 100% | | | | | | | 0.465 / 0.527 / 0.495 |
| idle / DP optimum | – | 0.2 / 1.0 | | | | | | | | | |

- **Start states** among the 200 tasks: 56 empty, 71 half, 73 full.
- **CIs:** 95% bootstrap over tasks, 10,000 resamples.
- **Error rates** are each completion's first failure, as a share of all 200 tasks. `cycle_cap` is 0–4.5% and `all_idle` 0% for every model; see `summary.json`.

**Paired gaps for arm 2** (paired bootstrap, `summary.json`):

| arm 2 minus | sampled | greedy | arm 2 wins on (sampled) |
|---|---|---|---|
| arm 1 final | +0.250 [0.207, 0.292] | +0.253 [0.209, 0.296] | 74% of tasks |
| SFT-2 | +0.037 [−0.016, 0.091] | −0.001 [−0.054, 0.052] | 45% |
| threshold rule | −0.058 [−0.113, −0.004] | −0.055 [−0.112, 0.001] | 41% |
| greedy rule | −0.185 [−0.237, −0.133] | −0.182 [−0.236, −0.129] | 21% |

**By curriculum tag:**

| model (sampled) | C0 | C1 | C2 |
|---|---|---|---|
| SFT-2 | 0.461 | 0.469 | 0.669 |
| arm 2 | 0.623 | 0.437 | 0.605 |

**Checkpoints on the fixed 50-task subset** (sampled, T 0.7; `eval_checkpoints.json`):

| step | 0 (SFT-2) | 25 | 50 | 75 |
|---|---|---|---|---|
| R | 0.631 | 0.565 | 0.566 | 0.565 |

- This subset flatters SFT-2: it scores 0.631 on these 50 tasks but 0.512 on the other 150. Arm 2 scores 0.565 and 0.584 on the same two groups.
- The 50-task CIs are about ±0.09, so the checkpoint curve cannot separate SFT-2 from GRPO. Use the 200-task paired numbers above.

**Train curve** (T 1.1, 64 rollouts per step, 10-step means):
- R: 0.391 → 0.421 → 0.489 → 0.528 → 0.585 → 0.526 → 0.615 → 0.595 (steps 71–75).
- Feasible: 39% → 78–80%.
- Overfill: 27% → 6%; sell-before-charge: 23% → 8–11%.

Much of that rise is the policy becoming robust at T 1.1, and it carried over to the T 0.7 eval only as the feasibility gain.

## What changed from arm 1

### 1. The SoC-aware warm start ("SFT-2")

**Data:** 1,500 DP-optimal schedules from `ercot-dam-v1-train`, 167 (or 166) per cell of curriculum stage (C0–C2) × start state.
- The start state is s0 = 0 (empty), N/2 (half) or N (full); the packs use exactly these three.
- Task ids are in `sft2_task_ids.json`.

**Target:** a template rationale computed from the task and its DP schedule (no LLM text), then the exact 24-int `submit_schedule` call. The rationale gives:
- the starting charge, with "so the first trade must be a sell/buy" on full and empty starts;
- the end obligation and the cycle cap;
- the 3 cheapest and 3 dearest hours with prices;
- the plan as trade segments, each with its units, price range and the SoC after it;
- the end SoC.

Example:

```
Starts empty (0/3), so the first trade must be a buy. Must end at >= 1/3; cycle cap 3 units sold. Cheapest hours:
HE15 $11, HE14 $11, HE16 $13. Dearest: HE21 $188, HE20 $154, HE22 $100. Plan: buy HE15 (3 units, $11) -> 3/3;
sell HE21 (3 units, $188) -> 0/3; buy HE24 (1 unit, $55) -> 1/3. Ends at 1/3.
<tool_call>
{"name": "submit_schedule", "arguments": {"actions": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -3, 0, 0, 0, 0, 0, 3, 0, 0, -1]}}
</tool_call>
```

All 1,500 targets score 1.0 through `reward_fn`.
- **Completion tokens:** p50 253, p99 320, max 351.
- **Training:** LoRA r=32, α=64 (all attention and MLP projections); lr 1e-4 cosine with 10% warmup; **1 epoch**; batch 8 (4 × 2 accumulation); 188 steps in 22 min. The adapter is merged into the base.

### 2. GRPO with exploration kept alive

| setting | arm 2 | arm 1 |
|---|---|---|
| rollouts per step | **8 generations × 8 prompts = 64** (per-device batch 4, accumulation 16) | 8 × 4 = 32 |
| rollout temperature | **1.1** | 1.0 |
| lr | **1.5e-5** cosine over a 75-step schedule, 10 warmup steps | 2e-5 over 280 |
| curriculum | **mixed from step 0**: each prompt draws a (C0–C2 × start state) cell uniformly, then a train task in it | C0 → C1 → C2 phases |
| `max_completion_length` | **512** (the longest SFT-2 completion is 351 tokens; 14 of 4,800 rollouts hit 512) | 384 |
| steps | **75**, all completed (86 s/step, 1 h 48 min) | 280 |
| checkpoints | every 25 steps | every 50 |
| unchanged | `dr_grpo`, β 0, ε 0.2/0.28, `scale_rewards="group"`, LoRA r=32/α=64, bf16, colocated vLLM 0.4, seed 0 | |

- **Entropy and zero-spread share** are logged every step. No step fell below entropy 0.02, so `train_log.jsonl` carries no `note` rows.
- **Note on `max_completion_length`:** `dr_grpo` divides by this constant, so moving from 384 to 512 scales the per-token loss by 0.75 relative to arm 1.

### Deviations from the brief

1. **75 steps, not 150–200.** 64 rollouts of about 250 tokens take about 86 s per step on the L4, and a first launch crashed at step 16 (below). The restart's 75-step cosine schedule was sized to end by 13:10 UTC, and it completed.
2. **A crashed first launch** (`train_log_crashed_run1.jsonl`, steps 1–16).
   - Cause: my tool-call *metrics* helper (`pathb.tool_call`, not the reward) raised when a T 1.1 sample wrote `<tool_call>[…]</tool_call>` with a bare JSON list.
   - Fix: the helper now returns False for a non-object call.
   - The restart used the same seed, so the same task order. The crash cost about 25 minutes.
3. **`max_completion_length` 512** instead of 384 (see above).

## Time and cost

| step | UTC | duration |
|---|---|---|
| SFT-2 | 10:21–10:45 | 24 min |
| SFT-2 eval | 10:45–10:48 | 2.5 min |
| crashed GRPO (16 steps) | 10:48–11:12 | 24 min |
| idle gap | 11:12–11:20 | 8 min |
| GRPO (75 steps) | 11:20–13:08 | 1 h 48 min |
| evals | 13:08–13:11 | 2 min |

- **Cost:** about 2.9 h of g6.4xlarge at $1.32/h ≈ **$3.80**. Lane T's total across both arms is about 6.9 h ≈ **$9**. No API spend.
- **Versions:** as in arm 1 (`../pip_freeze.txt`), with gridsim_core at `lane-core` 920b7ad.

## Files

- `train_log.jsonl`: one row per GRPO step, over that step's 64 rollouts at T 1.1. It has TRL's metrics (including `entropy`) plus R, R by start state (`reward_empty`, `reward_half`, `reward_full`), the valid and feasible rates, the error taxonomy, completion length and the zero-spread share.
- `train_log_crashed_run1.jsonl`: the crashed first launch.
- `curves.png`:
  - top: train reward, overall and by start state, the held-out 50-task checkpoint evals, and lines for idle, threshold, greedy, arm 1 final and DP;
  - middle: valid, feasible and error rates;
  - bottom: entropy and the zero-spread share.
- `eval_sft2.json`, `eval_trained.json` and `eval_checkpoints.json`: per decoding, the summary (with R by start state and by curriculum tag, each with CIs) and per-task reward, kind and actions.
- `summary.json`: base, SFT-200, arm 1, SFT-2, arm 2 and the rules, with CIs and R by start state, plus paired bootstrap gaps of arm 2 against arm 1, SFT-2, threshold and greedy.
- `episodes/*.jsonl`: path-B `gridsim.episode/v1`, one per line, from `gridsim_core.episode.to_episode_json`.
  - `base-*` (copied from arm 1; same model and prompt), `sft2-*` and `trained-*` (step 75): 200 tasks each.
  - `ckpt-0025-sampled` and `ckpt-0050-sampled`: the 50-task subset.
  - `trained` is `grpo`; SFT-2 is `sft`; `checkpoint_step` is set throughout.
- `levelup/<task_id>/<frame>.json`: per-file Episode JSON for 12 fixed eval days, all sampled at T 0.7.
  - The days: 4 per start state, from the 50-task subset, spread over January–November and six regions.
  - Frames: `base`, `0000` (SFT-2), `0025`, `0050`, `0075` (final).
  - `levelup/index.json` lists each day's start state, region, date, point and per-frame reward.
  - Good montage days: `dam-v1-2025-06-06-LZ_CPS-1h-l` (0 → 0.15 → 0.85 → 0.98 → 0.98) and `dam-v1-2025-10-26-LZ_LCRA-1h-q` (0 → 0.20 → 0.85 → 0.84 → 0.84).
  - Some days get worse. For example, `dam-v1-2025-06-29-HB_NORTH-1h-v` goes from 0.81 at SFT-2 to 0 from step 25 on.
- `sft2_task_ids.json`, `sft2_meta.json`.
- `scripts/`: the exact code (`pathb.py`, `train.py`, `sft.py`, `evaluate.py`, `report2.py`) and the two unit scripts.

## Adapter

- **Key:** `gridsim/adapters/qwen3-1.7b-gridsim-v1-arm2-sft1500soc-grpo75-seed0.tgz` in Scale-internal object storage, 647 MB.
- **Contents:**
  - `adapter/sft2-lora/`: apply to `Qwen/Qwen3-1.7B` and merge first.
  - `adapter/grpo-lora/`: step 75.
  - `adapter/checkpoints/checkpoint-{25,50,75}/`.

## Reading and next steps

- **The binding constraint was the warm start's view of the state,** not exploration. Spelling out the start, the end obligation and the SoC path in the template took the same model from 0.23 to 0.54–0.58 with no RL. GRPO's measurable contribution in 75 steps is feasibility (+13 points) and the half-start days, at the cost of full-start days.
- **To clear threshold** (needs about +0.06):
  - more GRPO steps at this exploration level (the train curve was still rising at step 75);
  - more SFT-2 epochs or examples (one epoch, with loss still falling);
  - the 4B model.
- **To approach greedy** (needs +0.18): probably a model that can do the arithmetic, either the 4B or thinking on. The 24-entry fix (constrained decoding or an hour-keyed format) remains a contract decision for Edgar.
