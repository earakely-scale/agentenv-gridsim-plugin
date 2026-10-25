# GridSimEnv v1, lane T: path B training on Qwen3-1.7B (one L4)

Overnight run, 2026-10-24 UTC.

Path B is one prompt, one completion and reward = `gridsim_core.trl.reward_fn`, with no AgentEnv episodes. The goal was to show that training works on a small open model on one GPU, and to measure base vs trained on held-out 2025 battery-days.

## Headline

1. **Training moves the model, but not far.**
   - The final model is the SFT-200 warm start plus 280 GRPO steps.
   - It scores **R = 0.329 [0.306, 0.354]** on 200 held-out eval-2025 days, with **99% valid** submissions.
   - That is up from 0.234 for the SFT warm start alone (paired +0.095 [0.061, 0.131]) and from 0.000 for the base model.
   - It is far below the rules: threshold 0.637 [0.601, 0.673] and greedy 0.764 [0.726, 0.800].
2. **Pre-registered bars.**
   - "Trained beats greedy with non-overlapping CIs and valid ≥ 98%": **not met**. Valid ≥ 98% is met (99.0% sampled, 98.5% greedy). Beating greedy is not met: the paired gap to greedy is −0.435 [−0.476, −0.392].
   - The training plan's S5, "the 1.7B beats threshold": **not met** (one seed run).
3. **The base model cannot play at all with this prompt.**
   - Qwen3-1.7B with thinking off submits an all-zero list of 23 entries (22 on 8% of tasks) instead of 24.
   - So: 0/200 valid, R = 0, 3 distinct completions across 200 tasks.
   - Pure GRPO from the base therefore had no signal: 384 rollouts, 0 valid, every group with zero reward spread, loss and gradient exactly 0.
   - The reported model is the training plan's pre-registered fallback arm, **SFT warm start + GRPO**. It is a separate arm, not the "GRPO only" row.

## Results (200 eval-2025 tasks, foresight, oneshot prompt, path B)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | end short | all idle | malformed |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-1.7B base | sampled | **0.000** | [0.000, 0.000] | 0.0% | 0.0% | 0 | 0 | 0 | 0 | 100% |
| Qwen3-1.7B base | greedy | 0.000 | [0.000, 0.000] | 0.0% | 0.0% | 0 | 0 | 0 | 0 | 100% |
| + SFT-200 warm start | sampled | **0.234** | [0.209, 0.260] | 99.0% | 30.5% | 49.5% | 11.0% | 9.0% | 0 | 1.0% |
| + SFT-200 warm start | greedy | 0.242 | [0.217, 0.268] | 100% | 39.0% | 50.0% | 7.0% | 7.5% | 0 | 0 |
| + SFT-200 + GRPO 280 steps | sampled | **0.329** | [0.306, 0.354] | 99.0% | 56.5% | 41.0% | 0.0% | 15.5% | 0 | 1.0% |
| + SFT-200 + GRPO 280 steps | greedy | 0.329 | [0.305, 0.354] | 98.5% | 56.5% | 41.0% | 0.0% | 15.5% | 0 | 1.5% |
| greedy rule | – | **0.764** | [0.726, 0.800] | 100% | | | | | | |
| threshold rule | – | 0.637 | [0.601, 0.673] | 100% | | | | | | |
| clock rule | – | 0.498 | [0.460, 0.536] | 100% | | | | | | |
| random feasible | – | 0.070 | [0.052, 0.089] | 100% | | | | | | |
| idle / DP optimum | – | 0.2 / 1.0 | | | | | | | | |

- **CIs:** 95% bootstrap over tasks, 10,000 resamples.
- **Error rates:** each completion's first failure. Rates are shares of all 200 tasks.
- **Paired differences** (`summary.json`, paired bootstrap):

| comparison | mean | 95% CI | trained wins on |
|---|---|---|---|
| trained − SFT (sampled) | +0.095 | [0.061, 0.131] | 44% of tasks |
| trained − SFT (greedy) | +0.087 | [0.056, 0.119] | |
| trained − threshold (sampled) | −0.308 | [−0.355, −0.259] | 18% |
| trained − greedy (sampled) | −0.435 | [−0.476, −0.392] | 8% |

**Checkpoints on the fixed 50-task subset** (the first 50 of the 200; T 0.7; `eval_checkpoints.json`):

| step | 0 (SFT) | 50 | 100 | 150 | 200 | 250 | 280 |
|---|---|---|---|---|---|---|---|
| R | 0.266 | 0.170 | 0.340 | 0.378 | 0.375 | 0.364 | 0.360 |

- The step-50 dip is a malformed spike: 32% of completions were back to 23-entry lists. It cleared by step 80.
- The curve is flat after step 150.

**Why it stalls** (from the episodes):
1. **Collapse to a template.** The trained policy is near-deterministic: entropy fell from 0.18 to 0.008, sampled and greedy schedules are identical on 193 of 200 tasks, and groups with zero reward spread rose from 5% to 56%.
2. **It ignores the starting SoC.** The policy always opens "buy HE03 …, sell in the evening".
   - On the 73 days where the battery starts full (s0 = N), buying at HE03 overfills, the rest of the day executes as 0, and R ≈ idle: 0.195, vs 0.200 for SFT.
   - On the 127 days with headroom it scores 0.406, vs 0.267 for SFT. That is where GRPO's gain is.
   - All 82 overfill failures truncate at HE03, and 69 of them are full-start days.
3. By curriculum tag, the trained greedy model scores C0 0.359, C1 0.324 and C2 0.298. No task reaches 0.95; the best is 0.908.

The training plan's hypothesis was "1.7B ~0.30 → ~0.80". Measured: 0.00 → 0.23 (SFT) → 0.33 (SFT + GRPO).

## What ran, in order

1. **Smoke** (2 steps, synthetic tasks): TRL `GRPOTrainer` + LoRA + colocated vLLM run end to end.
2. **Base eval.** Qwen3-1.7B, thinking off, oneshot prompt, 200 eval-2025 tasks, sampled and greedy: 0/200 valid each, as above. `reward_fn` and the eval scorer agree on all 400 completions.
3. **The pre-registered recipe as is** (`train_log_pure_grpo.jsonl`): GRPO from the base model with the training plan's fallback credit (+0.05 for valid non-idle schedules, annealed to 0 by step 100).
   - 12 steps, 384 rollouts: 0 valid, every group zero spread, loss and grad_norm 0 on every step.
   - The credit cannot fire, because it pays only valid schedules.
4. **SFT warm start** (the training plan's fallback arm). SFT data: 200 DP-optimal schedules from `ercot-dam-v1-train`, about 67 per curriculum tag; task ids in `sft_task_ids.json`. Each target is a template rationale computed from the DP solution, then the tool call. There is no LLM text. Example:
   `Plan: buy HE05 (4 units) at $12/MWh; sell HE18-HE19 (8 units) at $77-$91/MWh; buy HE24 (4 units) at $29/MWh.`
   - Training: LoRA r=32, α=64 on all attention and MLP projections; lr 1e-4 cosine with 10% warmup; 2 epochs; batch 8; 50 optimizer steps; 6 min.
   - The adapter is merged into the base.
5. **GRPO from SFT at the pre-registered lr 5e-6.** Flat for 31 steps (`train_log_lr5e-6.jsonl`); stopped.
6. **GRPO from SFT at lr 2e-5**, everything else unchanged, 280 steps (`train_log.jsonl`). This is the reported run.
7. **Evals.**
   - Checkpoints every 50 steps on the 50-task subset.
   - The final adapter (step 280) on all 200 tasks, with the same decoding as the base eval.
   - No checkpoint was selected on eval: the reported model is the last step.

## Recipe (the reported GRPO run)

| setting | value |
|---|---|
| model | `Qwen/Qwen3-1.7B` in bf16 (no 4-bit, no Unsloth), with the SFT-200 LoRA merged in |
| adapter | LoRA r=32, α=64, dropout 0; q, k, v, o, gate, up and down projections |
| batch | TRL 1.15 `GRPOTrainer`; `num_generations` 8 × 4 prompts = 32 rollouts per step (per-device batch 8, gradient accumulation 4) |
| optimizer | AdamW (fused), **lr 2e-5** cosine, 10 warmup steps, weight decay 0, 280 steps |
| loss | `loss_type="dr_grpo"`, β = 0, ε_low 0.2, ε_high 0.28, `scale_rewards="group"` (TRL default), vLLM importance-sampling correction on (TRL default), `mask_truncated_completions` off |
| rollouts | temperature 1.0, top_p 1, no top_k; `max_completion_length` 384 (1 of 8,960 rollouts hit it); colocated vLLM, `gpu_memory_utilization` 0.4, max model length 2048 |
| prompt | `gridsim_core.prompt.messages(task, "foresight", 0)` and `tool_schemas("foresight", 0)` through the Qwen3 chat template with `enable_thinking=False`; about 1,080 tokens. This matches what the oneshot bundle sends |
| reward | `gridsim_core.trl.extract_actions` + `grade`, which is `reward_fn` exactly; no format credit |
| curriculum | C0 for the first 20% of steps (1–56), C1 to 60% (57–168), C2 after (169–280). From C1 on, 25% of prompts replay earlier tags; in C2 the top difficulty quartile is drawn 2×. Train split `ercot-dam-v1-train` (20k), seed 0, fixed order (`shuffle_dataset=False`) |
| checkpoints | every 50 steps, plus the final adapter |
| eval decoding | sampled: T 0.7, top_p 0.8, top_k 20, one sample per task, seed 0; greedy: T 0. `max_tokens` 512 |
| eval tasks | 200 of the 500 `ercot-dam-v1-eval` tasks (2025-01-06..2025-11-26; C0 84, C1 40, C2 76), foresight tier, from `numpy.random.default_rng(20251).permutation(500)[:200]`. Ids are in `eval_*.json` |

## Versions, hardware, time and cost

- **Packages:** torch 2.13.0+cu130, trl 1.15.0, vllm 0.29.0, transformers 5.17.0, peft 0.21.2, accelerate 1.15.0, datasets 5.1.0, numpy 2.3.5, Python 3.12 (uv venv). The full list is in `pip_freeze.txt`.
- **gridsim_core:** `lane-core` 920b7ad. The packs are from e856048; 920b7ad changes only a blind-tier error in `grade.py`.
- **Hardware:** AWS g6.4xlarge in us-west-2c: one NVIDIA L4 (23 GB, driver 595.91.07), 16 vCPU, 64 GB RAM.
  - Peak GPU memory during GRPO was 22.5 of 23 GB (vLLM 0.4 plus training).
- **Wall clock** (UTC):

| step | start | duration |
|---|---|---|
| setup | 06:22 | 3 min |
| smoke and probes | 06:27 | 8 min |
| base eval | 06:38 | 2 min |
| pure GRPO | | 7 min |
| SFT | | 6 min |
| SFT eval | | 2 min |
| GRPO at lr 5e-6 (31 steps) | 06:55 | 23 min |
| **GRPO at lr 2e-5 (280 steps)** | 07:19–10:08 | **2 h 49 min**, 36.3 s/step |
| checkpoint and final evals | | 2 min |

  - About 3.6 GPU-hours in all; the lane used the box from 06:21 to 10:16.
- **Cost:** about 3.9 h × $1.32/h ≈ **$5.20** of g6.4xlarge time. No API spend.

## Adapter

- **Location:** Scale-internal object storage (`gridsim/adapters/qwen3-1.7b-gridsim-v1-sft200-grpo280-lr2e-5-seed0.tgz`), 1.03 GB. Not on the HF Hub.
- **Contents:**
  - `adapter/sft200-lora/`: the SFT LoRA, applied to `Qwen/Qwen3-1.7B` and merged first.
  - `adapter/grpo-lora/`: the final GRPO LoRA (step 280). Its `base_model_name_or_path` points at the box path of the merged SFT model.
  - `adapter/checkpoints/checkpoint-{50,100,150,200,250,280}/`.
- **To rebuild the trained model:**
  1. Load `Qwen/Qwen3-1.7B`, apply `sft200-lora` and `merge_and_unload()`.
  2. Save the result, then serve it with `grpo-lora` (vLLM `enable_lora=True, max_lora_rank=32`) or merge that too.
- Each LoRA is fp32, about 140 MB.

## Files

- `train_log.jsonl`: one row per GRPO step. It has TRL's metrics (loss, grad_norm, entropy, clip ratios, importance-sampling stats) plus R, valid, tool-call and feasible rates, the error taxonomy, completion length and the share of zero-spread groups, over that step's 32 rollouts at T 1.0.
- `train_log_lr5e-6.jsonl` and `train_log_pure_grpo.jsonl`: the two earlier runs.
- `curves.png`:
  - top: train reward per step and as a 10-step mean, the held-out 50-task checkpoint evals, and lines for idle, threshold, greedy and DP;
  - bottom: 10-step means of the valid, feasible and error rates and of the zero-spread share.
- `eval_base.json`, `eval_sft.json`, `eval_trained.json` and `eval_checkpoints.json`: per decoding, the summary and per-task reward, kind and actions. The baselines are computed on the same tasks.
- `summary.json`: the table above and the paired bootstrap differences.
- `episodes/*.jsonl`: path-B `gridsim.episode/v1`, one Episode JSON per line, from `gridsim_core.episode.to_episode_json`. Bundle `oneshot`, path `B`, `trained` base / sft / grpo, with `checkpoint_step`; the raw completion is in `messages`.
  - `base-*`, `sft-*` and `trained-*`: 200 tasks each.
  - `ckpt-00NN-sampled`: the 50-task subset.
  - For a LEVEL UP montage on the first 50 tasks: base, then sft, then ckpt-0050 … ckpt-0250, then trained.
- `scripts/`: the exact code that ran (`pathb.py`, `train.py`, `sft.py`, `evaluate.py`, `report.py`, plus the three systemd unit scripts).
- `pip_freeze.txt` and `gpu.csv`.

## Error taxonomy

Each completion gets exactly one kind:
- `ok`: valid, feasible, no end shortfall.
- `all_idle`: valid and all zeros.
- `overfill`: the first rule break is SoC above N.
- `sell_before_charge`: the first rule break is SoC below 0.
- `rate` / `cycle_cap`: the first rule break is that rule.
- `end_short`: feasible, but ends below `s_end_min`.
- `malformed`: no parseable submit.
- `truncated`: no submit and the completion hit the max length.

"Valid" means `reward_fn` found 24 integers.

## Deviations (deliberate, all recorded)

1. **SFT warm start before GRPO.** Pure GRPO from the base model had 0% valid at step 0, so there was no reward spread. The pre-registered format credit only pays valid schedules, so it cannot fire. The training plan pre-registers this fallback arm for the 4B kill rule; here it is used for the 1.7B.
2. **lr 2e-5, not the pre-registered 5e-6.**
   - 5e-6 came from the 4-bit Unsloth recipe. With a bf16 LoRA it was flat for 31 steps, and only one full run fit the timebox.
   - At 2e-5 the train reward rose within about 40 steps. LoRA RL usually wants about 10× the full-fine-tune lr.
3. **bf16 base, no Unsloth or 4-bit.** A 1.7B fits an L4 in bf16 with colocated vLLM.
4. **280 steps, not 400–500.** That is what fit about 3 h at 36 s/step.
5. **Eval sizes.**
   - The final eval uses 200 of the 500 eval-2025 tasks.
   - Checkpoint evals use a fixed 50-task subset of eval-2025, as the lane brief asked, rather than the training plan's `val` slice; no `val` split exists yet.
6. **Thinking off only.** One seed, no 4B run, no path-A (AgentEnv) parity run.

## What to change next

1. **Fix the 24-count failure at the contract level.** Qwen3-1.7B writes 23 entries even when greedy. Options:
   - constrained decoding of the tool arguments (vLLM `tool_choice="required"` enforces the schema's `minItems`/`maxItems` 24), used in both path A and path B;
   - an hour-keyed action format;
   - an example list in the system prompt that has 24 entries (the current one is elided).

   Any of these would let pure GRPO start from the base model.
2. **A state-aware warm start.** The template rationale never mentions the starting SoC, and the policy locked onto "buy HE03 first". Instead:
   - state the start and the SoC path in the rationale ("starts full at 6/6, so sell first …");
   - use 1–2k SFT examples with full-start days included.
3. **Keep exploring.** Entropy fell to 0.008 and 56% of groups had no reward spread by the end. Options:
   - 16 generations per prompt and 8–16 prompts per step, which also cuts the step-to-step noise of 4 prompts;
   - temperature 1.1–1.2, or an entropy bonus;
   - stop or re-warm when zero-spread passes 50%.
4. **lr.** For the training plan's runs, use about 1–2e-5 for a bf16 LoRA, or re-check 5e-6 under Unsloth 4-bit before the W2 smoke.
5. **The rest of the training plan.**
   - Then: the 4B, the thinking-on ablation (the 1.7B may track SoC better with thinking) and seeds 1–2.
   - Path-A parity: serve base + merged SFT + the GRPO LoRA through vLLM in the oneshot bundle.
