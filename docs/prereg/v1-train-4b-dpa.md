# GridSimEnv v1 training, Qwen3-4B (path B), registered run 3: the DP's exact per-hour advantages (pre-registration)

Committed and pushed to `main` before any training step of this run. Nothing below changes after training starts, and nothing is rerun to improve a score. The only allowed changes are the pre-run amendments under "Smoke and amendments", appended here and committed before the main run starts.

## Why
GRPO stalled in both registered 4B runs:
- GRPO learns only from differences among the 8 rollouts of a day. The SFT-10k policy is near-deterministic: entropy was below 0.02 from GRPO step 3 of run 2, and about half of fresh days gave 8 rollouts with the same reward.
- On top of SFT-10k, run 2's GRPO changed nothing on held-out days (final minus SFT-10k −0.015 [−0.061, +0.030] on eval-2025, +0.004 [−0.022, +0.031] on eval-iid) and hurt greedy decoding (−0.046 [−0.090, −0.003]).

The foresight tier has an exact oracle. For any hour t, state of charge s and discharge units used d, `gridsim_core.dp` knows the value of every action. So every suboptimal hour of even a single rollout has a correct, non-zero advantage A_t = Q*(t, s_t, d_t, a_t) − V*(t, s_t, d_t) ≤ 0. That signal does not vanish when rollouts agree. Policy gradient with these advantages is AggreVaTeD (Sun et al., 2017): imitation of a cost-to-go oracle on the learner's own state distribution.

**The claim this run tests: held-out reward rises with more training steps.**

## The advantage (`src/gridsim_core/advantage.py`)
- **V\*[h, s, d]** is the DP's value-to-go table under `grade`'s rules. It uses the same cash, losses on the buy side, degradation, and end-shortfall penalty at max(max price, $50), and V\*[0, s0, 0] = P_opt.
- **Q\*(h, s, d, a) = cash(a) + V\*[h+1, s − a, d + max(a, 0)]** for a legal action.
  - A rule-breaking action (rate, SoC below 0 or above N, cycle cap) truncates the day exactly as `grade` does: this and every later hour execute as 0, then the end penalty applies. So Q\* = −shortfall(s) × penalty per unit.
- **The rollout's own path.** Parse the 24 integers of the `submit_schedule` call (`gridsim_core.trl.extract_actions`). Walk them from (s0, 0), and at each hour up to the first violation take **A_t = Q\*(t, s_t, d_t, a_t) − V\*(t, s_t, d_t)**.
  - Hours after a truncation get 0: nothing they say executes.
- **Reward units:** multiply by 0.8 / (P_opt − P_idle), the task's stored refs. Then Σ_t A_t = R_unclipped − 1, where R_unclipped = 0.2 + 0.8 (P − P_idle)/(P_opt − P_idle). This equals R − 1 whenever the reward is not clipped at 0.
- **Sign and digit split.** Qwen3's tokenizer writes each integer as a sign-deciding token (`' '`, `' -'`, `' ['` or `' [-'`) and then the digit token(s). So each hour's advantage is split exactly into two parts, which sum to A_t:
  - the **sign token** (the token right before the integer's first digit) gets Q\*(best action of the same sign class) − V\*;
  - the **digit token(s)** get Q\*(a) − Q\*(best action of the same sign class).
  - The sign classes are a < 0 and a ≥ 0.
- **Property tests (`tests/core/test_advantage.py`, hypothesis on random batteries and prices, plus the fixtures), passing before this commit:**
  - V\*[0, s0, 0] equals `solve_dp`'s profit.
  - On the DP-optimal plan every A_t = 0, and the action the table picks at each visited state is the DP's own (same tie order).
  - For any plan (random, idle, or the optimum with 1–4 hours perturbed, including illegal values), every A_t ≤ 0, and Σ_t A_t in $ equals P − P_opt. In reward units it equals R − 1 when R > 0, and is ≤ −1 when R = 0.
  - sign + digit = A_t, and both are ≤ 0.
  - The truncation hour matches `simulate`, and later hours are 0.
  - Also checked on 3,000 train days (A_t = 0 on every stored optimum; max |A| 2.5e-16) and on 2,000 one-hour perturbations (Σ A = R − 1 on every unclipped one).
- **Scale:** on 3,000 train days with 1–2 perturbed hours, the non-zero hour advantages have median −0.048 and 25th percentile −0.42. 5% are below −1.06; the minimum is −4.07.

## Token credit (`results/train/4b-dpa/scripts/credit.py`)
- **The 24 integers' tokens:** the sign and digit parts above, each **clipped to [−1, 0]**. −1 is the reward's own range: no single outcome can cost more than the whole reward. The clip touches about 5% of non-zero hours.
- **Every other token** (the rationale, the call's scaffolding, the end-of-turn token) gets the **sequence advantage R − 1**.
  - This is the sum of the hour advantages: the plan's shortfall from the DP optimum, in reward units.
  - **Why not 0:** under the optimal continuation a rationale token's own Q\* − V\* is 0, so 0 is the strictly exact choice. But SFT-10k's integers copy a plan that its rationale writes first. In run 2's train-day samples, 130 of 236 worst-of-step completions followed their written plan hour for hour and unit for unit, errors included; one wrote "sold 12 of 8 cap" and then broke the cycle cap. With 0 on the rationale, the source of those errors gets no gradient and the integers learn to contradict their own text.
  - R − 1 is the return minus a constant baseline (1, the value of the DP plan), so its policy gradient is unbiased.
- **Unparseable completion** (no `submit_schedule` call with 24 integers, including one cut at 512 tokens): **−1 on every token**. That is R − 1 with R = 0.
- **Text check:** if the completion's tokens do not decode, piece by piece, to the same text the engine returned, or the 24 integers cannot be located in the call, every token gets R − 1. The share of rollouts mapped is logged.

## Policy, rollouts and loss
- **Start:** `Qwen/Qwen3-4B` @ `1cfa9a7208912126459214e8b04321603b3df60c` with run 2's SFT-10k LoRA merged.
  - The LoRA is `gridsim/adapters/qwen3-4b-gridsim-v1-reg2-seed0.tgz` → `adapter/sft-lora`. It is merged in bf16 on the GPU (`merge_and_unload`), as `scripts/sft.py` and the confirm lane did.
  - **A fresh LoRA goes on top:** r = 32, α = 64, dropout 0, on all attention and MLP projections. Its B = 0 initialisation makes step 0 identical to SFT-10k. Thinking off, max completion 512 tokens. The prompt and tools are runs 1–2's oneshot prompt.
- **Rollouts:** vLLM 0.29 on one GPU serves the merged SFT-10k model with the current LoRA loaded from disk each step.
  - **T 1.0, top_p 1, no top_k, one rollout per day.** T 1.0 makes the engine's sampled-token logprobs the policy's own (no temperature or truncation to correct for).
  - **32 days per step**, from the **10,000 train-pack days outside SFT-10k's set** (`results/train/4b-v2/sft_task_ids.json`). The SFT days had their DP answer shown once, so fresh days carry more correction signal.
  - Each draw picks a uniform (curriculum C0–C2 × start empty/half/full) cell, then the next unused day of that cell, reshuffled when the cell is spent. Seed 0.
  - **Never** eval-2025, eval-iid, rtcb or showcase: the train pack shares no task id or date with them.
- **One step stale.** Batch k is sampled with the adapter after k − 1 updates (batches 0 and 1 with the initial one) while step k − 1 trains. This keeps the rollout GPU busy during training.
- **Loss, per completion token:**
  - −min(ρ·A, clip(ρ, 0.8, 1.2)·A) + β·KL;
  - ρ = π_θ / μ, where μ is the engine's logprob of the sampled token (the behaviour policy), so the clip also absorbs engine-versus-trainer numerics;
  - **KL:** the k3 estimator to the SFT-10k reference (the same weights with the LoRA switched off), **β = 0.04**, on every completion token. It guards greedy decoding, which run 2's β = 0 GRPO lowered. Tokens with A = 0 (correct hours, optimal rollouts) feel only this pull.
  - Summed over tokens and divided by 32 × 512 (Dr. GRPO's constant normaliser).
  - No group baseline, no reward standardisation, no entropy bonus, **no distillation term**. The DP action a\*_t is logged, not trained on.
- **Optimiser:** one AdamW step per batch. lr **1e-5** (runs 1–2's), constant after 5 linear warmup steps, weight decay 0, gradient clip 1.0. bf16 model with fp32 LoRA, micro-batch 1 sequence, gradient checkpointing.
- **Hardware split** (g5.12xlarge, 4× NVIDIA A10G 24 GB, us-east-1):
  - GPU 0: rollouts;
  - GPUs 1–2: training under torchrun, 16 rollouts each, LoRA gradients all-reduced as a mean;
  - GPU 3: evaluation, in parallel with training.
- **Code:** `results/train/4b-dpa/scripts/` (`dpa_train.py`, `rollout.py`, `credit.py`, `train_unit.sh`, `eval_unit.sh`) with `BATCH=32 LR=1e-5 WARMUP=5 BETA=0.04 EPS=0.2 TEMP=1.0 MAX_COMPLETION=512 SAVE_EVERY=25 SEED=0`.
  - **A CPU dry run passed before this commit:** a 2-layer random Qwen3 with the real tokenizer, 4 steps × 4 rollouts, the rollout worker on HF generate with SFT-style calls, and every path exercised (unparseable, mapped, truncated, KL, checkpoints, adapter hand-off).
- **Packages:** `results/train/pip_freeze.txt`: torch 2.13, vllm 0.29.0, transformers 5.17.0, peft 0.21.2.

## Steps, checkpoints and the claim
- **Training stops at 21:00 UTC on 2026-10-26.** The step count is fixed by the smoke rule below as the largest multiple of 25 that fits.
- **Checkpoints every 25 steps, plus the final.** Each is evaluated as soon as it lands.
- **The claim is the final adapter:** the last step, or the step at which a stop rule fired. There is no checkpoint picking.

## Eval (runs 1–2's script, unchanged)
- **Code:** `results/train/4b-v2/scripts/evaluate.py` and `pathb.py`, unchanged (copied into `scripts/`).
  - vLLM 0.29, engine seed 0, `max_model_len` 2048, `gpu_memory_utilization` 0.85, LoRA rank 32, max_tokens 512, on GPU 3 of the same box.
  - The script labels adapter episodes `trained: "grpo"`. That is its fixed label, not the method.
- **Decoding:**
  - **sampled:** T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task;
  - **greedy:** T 0.
- **Tasks:** **all 200 eval-2025 tasks** at every checkpoint (`default_rng(20251)` sample of `ercot-dam-v1-eval`, the same 200 as runs 1–2), not a 50-task subset. Run 2's subset rose while the full set fell.
- **Step 0** is the merged SFT-10k with no adapter, evaluated on this box. Run 2's L40S numbers are not reused, because sampled text depends on the hardware.
- **Evaluated:**
  - step 0 and every checkpoint on eval-2025 (200), sampled and greedy;
  - step 0 and the final on `ercot-dam-v1-eval-iid` (500), sampled and greedy.
- **Statistics:** mean R with a 95% percentile bootstrap CI over tasks (10,000 resamples, seed 0). Paired differences with a 95% paired-bootstrap CI (10,000, seed 0), with the win and tie rates. Valid, feasible, the error taxonomy, and R by start state and curriculum are also reported.

## Bars
- **PRIMARY: reward rises with more steps.** On all 200 eval-2025 tasks, sampled, both must hold:
  - **(a)** the final adapter beats step 0: the paired difference (final − step 0) has its 95% CI wholly above 0;
  - **(b)** the least-squares slope of held-out mean R against step is positive with its bootstrap 95% CI wholly above 0.
    - The fit uses step 0 and every evaluated checkpoint, including the final, at their step numbers.
    - The CI comes from 10,000 resamples of the 200 tasks (seed 0). The same resampled task set is applied to every checkpoint, and the slope is refit each time.
  - At least 5 checkpoints after step 0 are needed. If a stop rule ends the run before step 125, the primary is **not met**.
- **SECONDARY:**
  1. **Greedy decoding does not fall:** final − step 0, greedy, on eval-2025 (200), has a paired 95% CI lower bound ≥ −0.01.
  2. **The final beats the greedy rule** (runs 1–2's bar, sampled, 200 tasks): its 95% CI lies wholly above the rule's 0.764 [0.726, 0.800] (lower bound > 0.800), with ≥ 98% valid.
  3. **eval-iid (500):** final − SFT-10k, sampled, paired 95% CI wholly above 0.
- **Reported, not bars:**
  - the paired gaps to run 1's and run 2's finals and to run 2's SFT-10k, from their committed per-task rewards on the same 200 tasks (cross-hardware, so context only);
  - the greedy-decoding slope;
  - eval-iid greedy.

## Registered diagnostics (every step, `train_log.jsonl`)
- **Train rollouts** (T 1.0, 32 per step):
  - mean R, valid, feasible, the share at R = 1, and the error mix (`pathb.KINDS`);
  - the mean A_t over executed hours of parseable rollouts, and the share of those hours with A_t < 0.
- **Policy:**
  - entropy (mean over completion tokens, full softmax);
  - KL to the reference (mean k3 per token);
  - the PPO clip fraction and mean ratio;
  - the gradient norm.
- **Engineering:** completion length, 512-token hits, the mapped share, s/step, and generation wait.
- **Held-out greedy at every checkpoint** (diagnostic, not a bar).

## Stop rules
- **Wall clock:** training stops and saves at **21:00 UTC on 2026-10-26** whatever its step. The adapter at that step is the claim.
- **Collapse guard:** if the 10-step mean of train R falls below **0.60**, or the 10-step mean valid rate below **0.90**, training stops and saves. The adapter at that step is the claim.
- **Crash:** an infrastructure or code fault gets one restart from scratch with the same seed, if the full step count still fits before 21:00 at the smoke's rate. Otherwise the last checkpoint is evaluated as the claim and labelled a short run.
- **The box** powers itself off at 03:19 UTC on 2026-10-27. The plan ends by about 22:00 UTC.

## Smoke and amendments
- **Smoke (discarded):** 6 steps of the exact recipe on the box after this commit. It measures seconds per step (steps 3–6) and peak memory per GPU.
- **The step count:**
  - **STEPS** is the largest multiple of 25 such that STEPS × (the smoke's s/step + 5%) fits between the main run's start and 21:00 UTC.
  - If fewer than 125 steps fit, BATCH falls to 16, and the rule is applied again.
- **Engineering settings** (vLLM memory, how rollouts are split across GPUs) may change after the smoke, but the recipe may not.
- **Amendments** are appended below and committed before the main run. The step count is never raised once training starts.

## Prior (stated so the outcome can be checked against it)
- **Step 0 on this box:** about 0.84 sampled (run 2: 0.841; the confirm lane's pipeline check: 0.846).
- **Final, if the method works:** about 0.86–0.89 sampled.
- **PRIMARY:** about 40%. (a) needs a paired gain of roughly +0.03 on 200 tasks; (b) needs most of that gain to show as a trend rather than one jump.
- **SECONDARY 1 (greedy not down):** more likely than not, given β > 0 and only non-positive advantages.

## Budget
- **Box:** one g5.12xlarge (4× A10G 24 GB, 48 vCPU, 192 GB RAM) in us-east-1, at about $5.7/h. It booted at 15:18 UTC on 2026-10-26.
  - The plan ends by about 22:00 UTC, about 6.7 h or **about $38**.
  - The box is left idle for the main session to terminate.
- **API spend:** none.

## Published whatever the outcome
These go to `results/train/4b-dpa/`, with the README labelled "registered run 3":
- `README.md` with the verdicts and deviations;
- `summary.json` with the verdicts, CIs, slope and paired gaps;
- `curves.png`: held-out R against step on all 200 tasks, with run 1's and run 2's results as reference lines, plus the train diagnostics;
- `train_log.jsonl`;
- the eval files;
- `episodes/`;
- LEVEL UP frames on the same 12 days as runs 1–2;
- `scripts/` and `pip_freeze.txt`.

The adapters go to Scale-internal object storage under `gridsim/adapters/qwen3-4b-gridsim-v1-reg3-dpa-seed0.tgz` (final) and `…-checkpoints.tgz`. Any deviation from this file is listed in the README.

## Amendments
