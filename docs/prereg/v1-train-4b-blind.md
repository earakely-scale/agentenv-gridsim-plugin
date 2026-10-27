# GridSimEnv v1 training, Qwen3-4B (path B), registered run 4: forecast-then-plan on the blind tier (pre-registration)

Committed and pushed to `main` before any generation of this run (step 0 included), before any training step and
before any GPT-6.1 Sol request. Nothing below changes after training starts, and nothing is rerun to improve a score.
The only allowed changes are the pre-run amendments under "Smoke and amendments", appended here and committed before
the step they govern. Linear: FD-4420 ("Focus", "Target claim", "Training design" and the ceiling-check comment).

## The claim this run tests
**A Qwen3-4B trained on GridSimEnv v1's blind tier matches GPT-6.1 Sol's hindsight capture C on blind eval-2025,
with both models under one identical harness.**

- **Why it is plausible.** The blind ceiling check (`results/blind-ceiling/`, 86e9953) found that the best forecaster
  built from the blind inputs, planned with the exact DP, ties Sol: an ensemble of 0.1 ridge + 0.5 LightGBM + 0.4 MLP
  scores C 0.912 on blind eval-2025 against Sol's 0.9165 (paired −0.005 [−0.015, +0.006]) and 0.919 on the fresh days
  against 0.926. If a 4B learns to forecast like that ensemble and to plan like the DP, it draws level with Sol.
- **Why it is hard.** Zero-shot, the foresight-trained run 3 scores 0.717 on the fresh blind days (−0.209 against
  Sol). The 4B has to learn both halves: a teacher-quality forecast and a near-DP plan on it.
- **C** is the repo's r_opt = clip(0.2 + 0.8 (P − P_idle) / (P_opt − P_idle), 0, 1), graded by `gridsim_core.grade` on
  the day's realized prices, used for every model and reference. No valid submission scores 0 (no format credit).

## The harness: one prompt for every model
- **Prompt:** the blind path-B oneshot prompt (`gridsim_core.prompt.messages(task, "blind", 0)`: system prompt,
  situation JSON with D-1 and D-7..D-1 DAM prices at the point, and the `submit_schedule` tool, no checks) plus one
  closing paragraph, `gridsim_core.forecast.FORECAST_NOTE` (`messages(..., forecast=True)`):

  > You may write your forecast first. Before calling submit_schedule you may write one line "Forecast: p1, p2, ...,
  > p24" with your forecast of today's 24 hourly DAM prices in $/MWh (HE01 first), then a brief plan. Only the
  > submitted schedule is graded. Keep the reply brief.

- **One call, no `check_schedule`,** for the 4B and for Sol. The grader reads only the schedule (`gridsim_core.trl.
  extract_actions`, then `grade`); the forecast line is parsed (`gridsim_core.forecast.parse_forecast`) for
  diagnostics and for the RL credit, never for the score.
- **4B decoding:** Qwen3 chat template with thinking off, **max_tokens 768** (the completion budget), max_model_len
  4096, vLLM 0.29, engine seed 0. **Sampled** (T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task) is the
  registered decoding, as in runs 1–3; **greedy** (T 0) is reported.
- **Sol:** `openai/gpt-6.1-sol`, one Responses request per task, reasoning effort high, max_output_tokens 16,384 (its
  hidden reasoning counts against this; its visible reply is the same kind of text the 4B writes), the same
  instructions, situation text and tool schema. Up to 4 attempts per task on transport errors; a task that never
  returns scores 0.
- **Packs:** **blind eval-2025** = the 300 `blind_eval` tasks of `ercot-dam-v1-eval` (191 days of 2025-01..11);
  **fresh** = the 331 tasks of `ercot-dam-v1-fresh-2026-10-blind` (2026-10-18..27). Every task of a pack at every
  evaluation; no subsets.

## Data (CPU, done before this commit)
- **Teacher forecasts** (`results/train/4b-blind/scripts/teacher.py`): the ceiling check's registered ensemble with
  its registered settings (`results/blind-ceiling/runs/tune.json`: LightGBM Huber δ $20 on price − 7-day hourly mean,
  255 leaves, min child 100, 25 rounds; MLP asinh 512×512 α 1e-4, mean of seeds 0–2; ridge λ 1e4; weights 0.1/0.5/0.4),
  **cross-fitted by year**: each of the 33,363 train-split point-days of 2014–2024 gets the forecast of members fitted
  on the other ten years. The eval packs get the full 2014–2024 fit (ridge-v1 as stored), as the ceiling check
  scored it.
  - **Checks, passed:** the full fit reproduces the ceiling check exactly (DP on it: C 0.9119 eval-2025, 0.9194
    fresh); the 2024 fold reproduces its 2024 holdout (0.9051).
  - Cross-fitted teacher-DP beats persistence-DP on every year's SFT rows (all years: C 0.866 vs 0.812). Its MAE is
    worse than persistence in the 2021 fold (16.5 vs 11.8 $/MWh: LightGBM's year splits put a held-out middle year
    into a neighbour's regime). That is the teacher's out-of-sample behaviour, kept as is.
- **The 2024 start-choice holdout** (`sft_data.py`, seed 0): 100 seeded 2024 dates with blind tasks and up to 2
  `blind_eval` train-pack tasks on each, **187 tasks**. Every train task on those 100 dates is excluded from all SFT
  and RL rows.
- **SFT rows** (`sft_data.py`): every train-pack task (2014–2024 only; the pack shares no date with eval-2025,
  eval-iid, rtcb, showcase or fresh) outside the holdout dates with 7 days of lags: **18,028 rows**. Blind inputs are
  the pack's own or build_pack's `lags` (the same rounding). The completion:
  1. `Forecast: p1, ..., p24`: the cross-fitted teacher forecast in whole $/MWh (the **written** forecast);
  2. run 2's SFT-10k rule rationale (start state, end obligation, cycle cap; the buy/sell pairs with the
     "(s − c_deg) × η > b" check; the plan with the SoC after each trade; the end check), computed **on the written
     forecast**, without the cheapest/dearest lists (the forecast line replaces them);
  3. the `submit_schedule` call with **the exact DP plan on the written forecast**.
  - Completions are 409 tokens at the median, 650 at most (under the 768 budget); prompts 2,361–2,422 tokens.
  - **Order:** a seeded round-robin over the 9 (curriculum C0–C2 × start empty/half/full) cells, so the first N rows
    are as balanced as the pool allows (equal cells up to 10,125 rows; the smallest cell has 1,125).
- **RL pool:** the same 18,028 tasks. The RL credit reads only the model's own written forecast, never the day's prices,
  so SFT days are allowed.

## Step 0 (before any training)
The untrained `Qwen/Qwen3-4B` @ `1cfa9a7208912126459214e8b04321603b3df60c` and **run 3 zero-shot** (run 2's SFT-10k
LoRA merged, then run 3's step-300 `dpa-lora` merged; the foresight-trained model) on blind eval-2025 and fresh, sampled
and greedy, with the harness above. These are the "before" rows.

## SFT warm start
- **Start choice (pilot, measured before the main SFT).** Candidates: **(a)** Qwen3-4B base; **(b)** run 3 (merged as
  above). SFT-10k alone is not a candidate: run 3 is SFT-10k plus a registered planning gain (eval-iid +0.039 on
  foresight) and scored higher zero-shot on the fresh blind days (0.717 vs 0.642).
  - Each candidate gets the same pilot SFT: the **first 1,000 rows** of the SFT order with the main SFT's settings
    (below; the cosine schedule spans the pilot's 125 steps).
  - Measured on the **2024 holdout (187 tasks), sampled**: mean C.
  - **The higher holdout C wins.** If the two are within 0.005, run 3 wins (the plan half is its trained skill).
  - The main SFT starts again from the chosen model (the pilot adapters are discarded).
- **Main SFT** (`sft_blind.py`): LoRA r = 32, α = 64, dropout 0, on every attention and MLP projection; bf16; one
  epoch over the first **N** rows of the SFT order; lr 1e-4, cosine with 10% linear warmup; 8 rows per optimizer step,
  micro-batch 1 without padding; loss = the mean over a step's 8 rows of each row's mean token NLL on its completion and
  end-of-turn token (logits on those positions only); gradient clip 1.0; seed 0. Gradient checkpointing only if memory
  needs it (engineering). The adapter is merged into the start model: **the SFT model**.
- **N rule:** **N = min(18,028, the rows that fit in 150 min at pilot (b)'s measured training throughput** (tokens/s,
  steps 11–125; pilot (b) runs alone on the GPU), **rounded down to 500).** Recorded as an amendment before the main
  SFT. No floor: the time cap rules.

## RL on the plan half with exact credit
Planning on one's own forecast is a foresight problem on that forecast, so run 3's DP-exact credit applies with the
forecast as the prices.
- **Credit (`credit_blind.py`):** parse the completion's forecast line F and its `submit_schedule` integers. With
  `gridsim_core.advantage.hour_advantages(task, actions, prices=F)` (V\*, Q\* from the DP on F; the scale
  0.8 / (P_opt − P_idle) of the day, as run 3):
  - the **sign token** of each integer gets Q\*(best action of its sign class) − V\*, its **digit tokens** get
    Q\*(a) − Q\*(sign class), along the plan's own SoC path (a rule-breaking hour truncates, later hours get 0);
  - **forecast-line tokens get 0: the forecast is frozen to the SFT behaviour** (no RL credit; only the KL term acts
    on it);
  - **every other token** (rationale, scaffolding, end of turn) gets the plan's total Σ_t A_t, run 3's R − 1 analogue;
  - **no valid schedule or no parseable forecast** (including a cut at 768 tokens): −1 on every token;
  - every value clipped to [−1, 0]; if the tokens do not decode back to the engine's text, −1 on every token.
  - **Property tests passing before this commit** (`tests/core/test_forecast.py`, hypothesis): a written forecast
    parses back to the prices it states (alone, followed by a plan and a call, or followed by a second forecast
    line); a line without exactly 24 numbers does not parse; **the advantages computed on a written forecast are 0 at
    every hour for the DP plan on that forecast**, and on a perturbed plan every A_t ≤ 0 with Σ A_t = P_F(plan) −
    P_F(DP plan) in $; the forecast prompt is the blind prompt plus exactly one paragraph. On 200 SFT completions
    through the real Qwen3 tokenizer: every token's credit is 0 and every integer is mapped; with one hour perturbed,
    199 of 200 get negative credit and the forecast tokens stay 0.
- **Policy and loss:** run 3's trainer (`rl_blind.py` from `dpa_train.py`): a fresh LoRA r = 32 / α = 64 on the merged
  SFT model (step 0 = the SFT model); per token −min(ρA, clip(ρ, 0.8, 1.2)A) + β·KL_k3(π ‖ SFT model), **β = 0.04**,
  ρ against the engine's sampled-token logprobs (rollouts one step stale); summed and divided by 32 × 768; one AdamW step
  per batch, **lr 1e-5** constant after 5 warmup steps, gradient clip 1.0; seed 0.
- **Rollouts:** vLLM 0.29 on the same GPU (one L40S; engine memory share an engineering setting), **32 days per step,
  one rollout each, T 1.0, top_p 1, no top_k, max 768 tokens**, each draw a uniform (curriculum × start) cell then the
  next unused day of it (seed 0).
- **Steps:** **STEPS = min(300, the largest multiple of 25 such that STEPS × (smoke s/step + 5%) fits between the main
  RL start and 10:50 UTC on 2026-10-27).** Checkpoints every 25 steps. **The claim is the final checkpoint** (the last
  step, or the step a stop rule fired at); no checkpoint picking.
- **Exploratory realized-reward GRPO arm on the forecast tokens:** not run (no time on one GPU); not registered.

## Evaluations
| when | models | packs | decoding |
|---|---|---|---|
| step 0 | base Qwen3-4B; run 3 zero-shot | eval-2025, fresh | sampled, greedy |
| pilot | pilot (a), pilot (b) | 2024 holdout (187) | sampled |
| RL step 0 | the SFT model | eval-2025, fresh | sampled, greedy |
| every 25 RL steps | the checkpoint | eval-2025 (all 300) | sampled |
| final | the final checkpoint | eval-2025, fresh | sampled, greedy |
| Sol | GPT-6.1 Sol | eval-2025 first, then fresh | its default |

Code: `results/train/4b-blind/scripts/evaluate_blind.py` + `pathb_blind.py` (4B), `sol_blind.py` (Sol). Per task they
record C, R on the blind anchor's scale, validity, the error kind, the schedule, the parsed forecast, and the plan
diagnostics (below).

## Bars (C; paired by task; 95% CIs from a day-block bootstrap: 10,000 resamples of days, seed 0, task-weighted)
- **PRIMARY (non-inferiority to Sol):** on blind eval-2025 (300), sampled, the final 4B's C minus Sol's has its
  **paired 95% CI lower bound above −0.02**.
  - **Margin 0.02 C** (0.025 of raw hindsight capture, i.e. 2.5% of the hindsight optimum's value over idle), fixed
    before any blind training. It sits between "the same" and "worse" on the ceiling check's evidence: the teacher
    pipeline, which ties Sol, is −0.005 [−0.015, +0.006]; the weaker information-matched methods are clearly below it
    (LightGBM alone −0.017 [−0.029, −0.006]; MLP or persistence-DP about −0.035). A paired CI on 300 tasks has a
    half-width of about 0.011 for well-matched methods, so a 4B level with the teacher can clear −0.02, and a 4B
    that is LightGBM-quality or worse cannot. At about 1/100th of Sol's cost, a shortfall under 0.02 C is "matches".
  - **Superiority (bonus, reported):** the same CI's lower bound above 0.
- **SECONDARY:**
  1. **Training helps:** final − step 0 (untrained base) and final − run 3 zero-shot, on blind eval-2025, sampled:
     each paired CI wholly above 0. (Also reported on fresh.)
  2. **Non-inferiority on the fresh days:** the PRIMARY test (lower bound > −0.02) on fresh (331 tasks, 10 days).
  3. **C rises across RL checkpoints:** the least-squares slope of mean C on blind eval-2025 (sampled, all 300 tasks)
     against step, over RL step 0 (the SFT model) and every checkpoint including the final, has its 95% CI wholly
     above 0 (day-block bootstrap: the same resampled days applied to every checkpoint, slope refit). At least 5
     checkpoints after step 0 are needed, else not met.
  4. **Forecast error:** on the unique point-days of each pack, the final 4B's written forecast has an all-hours MAE
     below persistence's (D-1): the paired CI of (4B − persistence) wholly below 0 on blind eval-2025. Reported
     alongside: MAE on the day's 4 dearest and 4 cheapest realized hours; the teacher (full fit), ridge-v1, Sol's
     written forecast where it wrote one, and the share of completions with a parseable forecast (a missing forecast
     is excluded from MAE and counted).
  5. **Planning loss (diagnostic, no bar):** C of the model's own schedule minus C of the DP plan on its own written
     forecast (both on the realized day), paired CI; and c_F, the schedule's capture measured on its own forecast
     (1 = the forecast's DP plan), with the share of exact DP plans.
- **Reported, not bars:** the SFT model (RL step 0) against Sol and the teacher; greedy decoding for every bar; the
  pilot's holdout numbers; per-day C on fresh with 2026-10-27 alone; the error mix; Sol's spend; the teacher pipeline
  (0.912 / 0.919) and the blind anchor (0.920 / 0.919) as reference lines.

## Registered train diagnostics (every RL step, `train_log.jsonl`)
Realized C of the rollouts (diagnostic only; the credit never reads it), c_F mean, valid / feasible / forecast-parsed
rates, the share of exact DP-on-own-forecast plans, mean hour advantage and the share of negative hours, entropy, KL to
the SFT model, clip fraction, ratio, gradient norm, completion length, 768-token hits, mapped share, s/step. The SFT
logs loss, gradient norm and tokens/s per step.

## Stop rules
- **RL wall clock:** RL stops and saves at **10:50 UTC on 2026-10-27** whatever its step; that checkpoint is the claim.
- **RL collapse guard:** if the 10-step mean c_F falls below **0.60** or the 10-step mean valid rate below **0.90**,
  RL stops and saves; that checkpoint is the claim.
- **SFT overrun:** if the main SFT runs 20% past its 150 min, it stops at the next step and the adapter at that point
  (cosine schedule truncated) is the SFT model, labelled.
- **Crash:** one restart from scratch with the same seed if the remaining time allows the same N or STEPS; otherwise
  the last saved state is evaluated and labelled short.
- **Sol cap:** **$15** in total for this run, enforced in `sol_blind.py` with worst-case accounting of in-flight
  requests. Eval-2025 runs first (it carries the PRIMARY); if the cap stops the fresh run short, SECONDARY 2 is
  reported as not completed.
- **The box** (one g6e.8xlarge: 1× L40S 48 GB, 32 vCPU, us-west-2, up 02:59 UTC) powers itself off at about 14:55
  UTC. The plan ends by about 11:45 UTC.

## Smoke and amendments
- **Pilot throughput** gives N (rule above), recorded before the main SFT.
- **RL smoke (discarded):** 4 steps of the exact recipe on the SFT model; s/step is the mean of steps 2–4. It gives
  STEPS (rule above), recorded before the main RL. Engineering settings (vLLM memory share, gradient checkpointing)
  may change after a smoke; the recipe may not.
- **The pilot's start choice** is recorded before the main SFT.

## Prior (stated so the outcome can be checked against it)
- **Step 0:** base Qwen3-4B C 0.1–0.4 (many invalid or truncated replies); run 3 zero-shot 0.68–0.76 on both packs.
- **SFT model:** C 0.80–0.87 on eval-2025: the forecast half lands between persistence and the teacher (MAE 9.5–12
  $/MWh), and planning on it loses more than the teacher pipeline does.
- **Final:** C 0.82–0.89; RL cuts broken plans as in run 3.
- **Sol** with the new paragraph: 0.90–0.93 on eval-2025, near its earlier 0.9165.
- **PRIMARY:** about 15%. It needs the 4B within about 0.01 of Sol on average, i.e. teacher-quality forecasting and
  near-DP planning at once. **SECONDARY 1:** very likely. **SECONDARY 3:** about 40% (run 3's slope cleared 0 narrowly).
  **SECONDARY 4:** likely.

## Budget
- **Box:** about 8.75 h × $4.5/h ≈ **$40**. Left idle for the main session to terminate.
- **Sol:** ≤ **$15** (expected about $12: 631 requests at about $0.019).

## Published whatever the outcome
`results/train/4b-blind/`, README labelled "registered run 4 (blind)": `summary.json` with the verdicts,
`curves.png` (held-out C against step, with Sol, the teacher pipeline and the anchor as reference lines), the eval
files, `episodes/`, `train_log.jsonl`, `scripts/`, `pip_freeze.txt`, the teacher forecasts and the SFT metadata. The
adapters go to Scale-internal object storage under `gridsim/adapters/qwen3-4b-gridsim-v1-reg4-blind-seed0*.tgz`. Any
deviation from this file is listed in the README.

## Amendments
- **Amendment 1 (03:58 UTC, before the main SFT): step-0 order, the pilot's start choice and N.**
  - **Step-0 order (engineering).** Step 0 was planned to run on the GPU alongside pilot (a). The pilot SFT took
    38 GB, so the vLLM engine could not start (it failed at load and wrote nothing). Step 0 then ran alone right after
    pilot (a) and before pilot (b), on the same untrained checkpoints and harness. No training touches those models.
  - **Step 0 (C, sampled / greedy):** untrained Qwen3-4B 0.164 / 0.169 on eval-2025 and 0.171 / 0.173 on fresh
    (68% all-idle and 28% sell-before-charge on eval-2025; 95% wrote a forecast line). Run 3 zero-shot 0.366 / 0.363
    and 0.330 / 0.361 (overfill 54%). This is below the prior's 0.68–0.76: with the forecast paragraph, run 3 writes a
    forecast on every task and then breaks its plan.
  - **Pilot** (first 1,000 rows, 125 steps, 696–699 s each, 4,000 tokens/s, peak 32.7 GB allocated without gradient
    checkpointing). Holdout 2024 (187 tasks), sampled: **(a) base 0.520 [0.476, 0.564], (b) run 3 0.819 [0.788,
    0.847]** (task bootstrap from the eval script). Both wrote a forecast on every task; the DP on those forecasts
    would score 0.909 (a) and 0.905 (b). Overfill 15.5% (a) vs 5.9% (b). **The main SFT starts from run 3 (b).**
  - **N.** Pilot (b) trained at 3,996.8 tokens/s (steps 11–125); rows average 2,778.6 tokens. 150 min fits 12,946
    rows; **N = 12,500** (1,563 steps, about 145 min). The overrun stop is 180 min after the start.
