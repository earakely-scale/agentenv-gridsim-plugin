# GridSimEnv v1 training, Qwen3-4B (path B), registered run 2: pre-registration

Committed before any training step of this run. Registered run 1 ([`v1-train-4b.md`](v1-train-4b.md), results in `results/train/4b/`) scored 0.804 [0.773, 0.834] sampled on the 200 eval-2025 tasks against the greedy rule's 0.764 [0.726, 0.800], and missed its primary bar by 0.027 at the CI's lower bound.

Run 1's logs pointed at two causes:
- Almost all of GRPO's gain came in the first ~100 steps. Entropy sat below 0.02 from step 43, and 16–45% of rollout groups had zero reward spread after step 150, so they carried no gradient.
- The warm start was small (1,500 schedules), and the largest error class left in the 1.7B was end-short (9%).

Run 2 tests two changes together, in one run. Everything else is held at run 1's values. Nothing below changes after training starts, and nothing is rerun to improve a score. The only allowed changes are the pre-run amendments described under "Smoke and amendments", appended here and committed before the GRPO run starts.

## Change 1: a bigger, rule-stating warm start (SFT-10k)
- **Data:** 10,000 DP-optimal schedules from `ercot-dam-v1-train` (2014–2024).
  - The train pack holds no eval-2025, eval-iid, rtcb or showcase day: 0 task ids and 0 dates overlap with those packs (checked before this commit).
  - The labels are the DP optimum stored with each task (`refs.foresight.opt`, `gridsim_core.dp`).
  - Stratified like run 1's set: 1,111–1,112 per cell over the 9 cells (curriculum C0–C2 × start empty/half/full), seed 0.
- **Completion:** a template rationale built from the DP solution (no LLM text), then the `submit_schedule` call. It keeps run 1's SoC-aware rationale and adds two parts:
  - **The kept part:** the start state, the end obligation, the cycle cap, the 3 cheapest and 3 dearest hours, and the plan with the SoC after each trade.
  - **The decision rule, stated plainly:** "a buy at b and a sell at s pay if (s − c_deg) × η > b". This is the exact v1 form of "sell price × η beats buy price plus degradation": losses are on the buy side and degradation is charged per MWh sold.
    - Then the pairs. Each sold unit is matched FIFO with the earliest open bought unit, or, when the battery started with energy, with the later buy-back.
    - Pairs are grouped by (buy segment, sell segment) and show the check on the group's mean prices, e.g. `buy HE02-HE05 -> sell HE18-HE20 x4: ($150 - $4) x 0.85 = $124 > $19`.
    - Units sold from stock above the end level, and units bought and held (paid to charge, or for the end level), are named as such.
    - Over the whole train pack every pair group passes its check and no DP schedule ends short.
  - **An end-of-day check:** the SoC the plan ends at against the required end level, and the units sold against the cycle cap.
- **Token budget (measured with the Qwen3-4B tokenizer before this commit):**
  - Completions are capped at 448 tokens, which leaves headroom under GRPO's 512.
  - A completion over 448 drops the cheapest/dearest lists. This happens on 1,155 of the 10,000.
  - A day whose trimmed text still runs past 448 is left out of the SFT pool: 788 of the 20,000 train days (3.9%), the most cycle-heavy ones. They stay in the GRPO pool.
  - The chosen set's completion tokens are p50 365, p99 446 and max 448; run 1's were p50 253 and max 351. The prompt is 1,084 tokens.
- **Training:** as run 1, except for the data.
  - LoRA r=32, α=64 on all attention and MLP projections; lr 1e-4, cosine with 10% warmup.
  - Batch 8 (per-device 4 × accumulation 2), **1 epoch = 1,250 optimizer steps**, expected to take about 1.7 h.
  - The adapter is merged into the base.
- **Code:** `scripts/sft.py` with `RATIONALE=rule STRATIFY=start N_SFT=10000 EPOCHS=1 MAX_TOKENS=448 SEED=0`.

## Change 2: no wasted GRPO groups
- **(a) Adaptive day sampling.** Each candidate prompt draws its (curriculum × start) cell uniformly, which is run 1's mix exactly. That is the floor: no cell can starve. Then, inside the cell:
  - With probability 0.5 it **replays** a seen day. Eligible days are those whose most recent group of 8 rollouts had reward std > 0 and that have had fewer than 4 visits.
  - The replay is chosen with weight equal to that std (the population std of the 8 rewards).
  - Otherwise, or when no seen day is eligible, it draws an **unseen** day of the cell uniformly.
  - A day's record is overwritten after every visit, so a day whose rollouts have all come to the same score drops out of replay.
  - No day appears twice in one step.
  - **The rule:** learnability is the group's reward std. A day the policy always solves, or always gets wrong the same way, has std 0 and is not replayed.
- **(b) Dynamic sampling (DAPO-style).** Each step generates 8 rollouts for **16 candidate prompts** (128 rollouts) and scores all of them.
  - It trains on the first 8 groups, in draw order, whose 8 rewards are not all equal. That is 64 rollouts, the same update size as run 1.
  - If fewer than 8 candidates have spread, the step is topped up in draw order with zero-spread groups. Those carry no gradient, and the count is logged.
  - Every candidate's outcome updates the sampler, kept or not.
  - TRL 1.15 has no dynamic sampling, so this is a subclass of `GRPOTrainer` that overrides `_generate_and_score_completions`. It draws the 16 candidates, calls the parent on all 128 rollouts (rewards, group advantages, vLLM importance weights), then slices every per-rollout tensor to the kept 64.
  - Advantages are per group, so slicing whole groups leaves them unchanged. The dataloader's own prompts are ignored.
- **Code:** `scripts/train.py` with `CURRICULUM=adaptive CANDIDATES=16 REPLAY_P=0.5 VISIT_CAP=4`.

## Held fixed (run 1's values)
- **Model:** `Qwen/Qwen3-4B` @ `1cfa9a7208912126459214e8b04321603b3df60c`, bf16, thinking off. Run 1's oneshot prompt and tools, and the reward `gridsim_core.trl.reward_fn` with no format credit.
- **GRPO:** a fresh LoRA r=32 / α=64 on the merged SFT model, with TRL 1.15 `GRPOTrainer` and colocated vLLM 0.29.
  - 8 generations × 8 kept prompts per step, at T 1.1.
  - Loss: `dr_grpo`, β 0, ε 0.2 / 0.28, `scale_rewards="group"`, `max_completion_length` 512.
  - **330 steps, lr 1e-5, cosine with 5 warmup steps, seed 0.** Checkpoints every 25, plus the final.
- **Cliff guard:** the same activation-gated guard. It arms the first time both 10-step means reach R 0.45 and feasibility 0.60, then stops the run if either 10-step mean falls below its level.
  - Run 2 computes it on the rollouts of the **fresh (unseen-day) draws**. Those are drawn like run 1's prompts (uniform cell, then a day in it), so the guard watches the same population at the same levels. Replays are chosen to be hard, so their reward is not a cliff signal.
  - The guard's 10-step means of fresh-draw R and feasibility are logged as the train curve; the kept and all-candidate means are logged beside them.
- **Engineering settings that are not part of the recipe:** run 1's per-device batch and accumulation (4 × 16) and vLLM `gpu_memory_utilization` 0.4. The smoke may tune these.
- **Packages:** run 1's environment (`results/train/pip_freeze.txt`): torch 2.13, trl 1.15.0, vllm 0.29.0, transformers 5.17.0, peft 0.21.2.
- **The claim is the final adapter** (step 330, or the step at which a stop rule fired). There is no checkpoint picking.

## Eval (as run 1)
- **Tasks:** the same 200 eval-2025 foresight tasks (`default_rng(20251)` sample of `ercot-dam-v1-eval`). The first 50 are the checkpoint subset.
- **Decoding:**
  - **Sampled (primary):** T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task.
  - **Greedy (secondary).**
  - Both use max_tokens 512 and `scripts/evaluate.py`.
- **Statistics:** mean R with a 95% bootstrap CI over tasks (10,000 resamples), and paired differences on the same tasks with a 95% paired-bootstrap CI (10,000 resamples) and the win rate. Also reported: valid, feasible, the error taxonomy, and R by start state and by curriculum.
- **Models evaluated:**
  - the **SFT-10k checkpoint** (step 0) on 200 tasks, sampled and greedy;
  - each GRPO checkpoint on the 50-task subset, sampled;
  - the final adapter on 200 tasks, sampled and greedy.
- The base Qwen3-4B is the same model on the same tasks and decoding as in run 1, so run 1's base eval (`results/train/4b/eval_base.json`) is reused, not rerun.

## Bars (the same as run 1)
- **PRIMARY:** the run-2 final adapter (sampled) beats the greedy rule.
  - Its 95% CI must lie wholly above greedy's: lower bound > 0.800, given greedy's 0.764 [0.726, 0.800].
  - It must also have **≥ 98% valid schedules**.
  - Both conditions must hold.
- **SECONDARY:** the paired difference (run-2 sampled minus the greedy rule) has a 95% CI wholly above 0.

## Registered comparisons
Each is paired on the 200 tasks, sampled, using run 1's committed per-task rewards. A comparison counts as "shown" only if its 95% CI lies wholly above 0. None changes the bars.
1. **Run 2 final minus run 1 final** (0.804): the two changes together.
2. **Run-2 SFT-10k minus run-1 SFT-1500** (0.666): change 1's effect on the warm start alone.
3. **Run 2 final minus run-2 SFT-10k:** what GRPO with change 2 added on top of the new warm start. Run 1's GRPO added +0.138 [0.092, 0.185].
- The design cannot separate change 2 from its interaction with change 1, because there is no arm with run 1's SFT and change 2. Comparison 3 is reported next to run 1's GRPO gain, not as a clean effect of change 2.
- All three are also reported for greedy decoding, along with the paired gaps to the threshold rule, the 1.7B arm 2c and the base 4B.

## Registered diagnostics
Logged every step and compared with run 1's `train_log.jsonl`:
- **Zero-spread share:**
  - among all 16 generated groups;
  - among the fresh-draw groups only, the population comparable to run 1;
  - among the 8 kept groups. This should be 0 except for top-ups.
- **Policy entropy** (TRL's, on the kept batch). Steps below 0.02 are counted, as in run 1.
- **Sampler state:** the replay share, eligible days and seen days.

## Prior (stated so the outcome can be checked against it)
- **SFT-10k:** we expect 0.68–0.76 sampled. Run 1's SFT-1500 scored 0.666.
- **Final:** we expect 0.80–0.86. The primary bar needs a mean near 0.84, so we put it at about even odds. The secondary bar needs about 0.81, and we think it more likely than not.

## Stop rules
- **Cliff guard:** as above. If it fires, the run stops and saves, and the adapter at that step is the claim.
- **Wall clock:**
  - The box powers itself off at 14:52 UTC on 2026-10-26, and the budget is about 12 box-hours.
  - GRPO stops and saves at **10:00 UTC on 2026-10-26** whatever its step. The adapter at that step is then the claim, with the step reported.
- **Crash:** a crash from an infrastructure or code fault (not the guard) gets one restart from scratch with the same seed, if the time left fits the full step count. Otherwise the last saved checkpoint is evaluated as the claim and labelled a short run.
- **Entropy:** below 0.02 is logged as a note and does not stop the run.

## Code check, smoke and amendments
- **Code check (not part of the run):** before the SFT, 2 GRPO steps of the new sampler and trainer run on the base Qwen3-4B to catch code faults. They are discarded.
- **Smoke:** a 5-step GRPO smoke runs on the merged SFT-10k model before the main run. It measures seconds per step and peak memory, then is discarded.
  - **If 330 steps at the measured rate (plus 5%) would not end by 10:00 UTC,** the step count is lowered to the largest multiple of 5 that fits. The lr, warmup and cosine stay as registered over the new count.
- **Amendments:** a step-count change, or any change to the engineering settings, is appended below and committed before the main run. The step count is never raised.

## Budget
- **Box:** one g6e.8xlarge (1× NVIDIA L40S 48 GB, 32 vCPU, 256 GB RAM) in us-east-1, at about $4.5/h on demand. It launched at 22:52 UTC on 2026-10-25, and the plan ends by about 11:00 UTC on 2026-10-26: about 12 h, or about $54.
- **API spend:** none.

## Published whatever the outcome
These go to `results/train/4b-v2/`, with the README labelled "registered run 2":
- `README.md` with the bar verdicts and the registered comparisons;
- `summary.json` with the verdicts, CIs, paired gaps, and the separate SFT-only and GRPO contributions;
- `curves.png` in run 1's style, with run 1's curves as reference lines;
- `train_log.jsonl`;
- `eval_sft.json`, `eval_checkpoints.json` and `eval_trained.json`;
- `episodes/*.jsonl`;
- LEVEL UP frames on the same 12 days (`base` from run 1's base episodes, `0000` = SFT-10k, every checkpoint, and the final);
- `scripts/` and `pip_freeze.txt`.

The adapters go to Scale-internal object storage under `gridsim/adapters/qwen3-4b-gridsim-v1-reg2-seed0.tgz` (SFT and final LoRA) and `…-checkpoints.tgz`. Any deviation from this file is listed in the README.

## Amendments
