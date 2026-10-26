# GridSimEnv v1, Qwen3-4B SFT-10k: confirmatory evaluation (pre-registration)

Committed and pushed before any generation on the tasks below. There is no training in this lane.

## Why
Registered run 2 ([`v1-train-4b-v2.md`](v1-train-4b-v2.md), results in `results/train/4b-v2/`) named its final GRPO adapter as the claim. Its SFT-10k warm start (step 0) was evaluated on the 200 eval-2025 tasks as a registered checkpoint:
- **SFT-10k, sampled:** 0.841 [0.802, 0.877], valid 99.5%.
- **Greedy rule:** 0.764 [0.726, 0.800].
- **Paired, SFT-10k minus greedy:** +0.076 [+0.024, +0.131].

The SFT-10k CI's lower bound cleared the greedy rule's upper bound. That observation is **post hoc**: run 2 did not register SFT-10k as a claim. This lane tests it on tasks no Qwen model in this repo has seen or been scored on. **The result confirms or fails to confirm that post-hoc observation, and it is published whatever it is.**

## Models (fixed; nothing retrained or reselected)
- **SFT-10k:** run 2's SFT LoRA merged into `Qwen/Qwen3-4B` @ `1cfa9a7208912126459214e8b04321603b3df60c`, bf16, thinking off.
  - The merge is done as `scripts/sft.py` did it: the base in bf16 on the GPU, `PeftModel.from_pretrained(...).merge_and_unload()`, then saved.
  - The adapter comes from object storage, `gridsim/adapters/qwen3-4b-gridsim-v1-reg2-seed0.tgz` (`adapter/sft-lora`). Its sha256 goes in the README.
- **Run-2 final:** the step-310 GRPO LoRA (`adapter/grpo-lora` in the same archive), served by vLLM as a LoRA on the merged SFT-10k model, as run 2 evaluated it.

## Tasks
- **`ercot-dam-v1-eval-iid` (primary):** all 500 tasks, foresight tier, the oneshot prompt (path B, the training prompt).
  - Every 10th calendar date of 2014–2024; 254 dates; pack sha256 `0b94ef2f…616e675`.
- **`ercot-dam-v1-rtcb`:** all 250 tasks, foresight tier, oneshot.
  - Post-RTC+B days, 2025-12-05 to 2026-10-17; 167 dates; pack sha256 `a814a4d7…f39414b`.
  - The 202 tasks that also carry blind inputs are graded in the foresight tier like the rest.
- **Order:** `scripts/evaluate.py`'s `default_rng(20251)` permutation, which with N equal to the pack size keeps every task. The order only fixes the bootstrap's indices.
- **No overlap with training (checked before this commit, against `results/train/4b-v2/sft_task_ids.json` and the whole train pack):**
  - eval-iid and rtcb share 0 task ids and 0 dates with SFT-10k's 10,000 tasks.
  - They also share 0 ids and 0 dates with the 20,000-task train pack, which is GRPO's pool, so the run-2 final is clean on both packs too.
- **What eval-iid does not test:** its dates sit between training dates of the same years, so neighbouring days were trained on. It tests unseen days of the training era, not a shift in time. rtcb tests the shift: a later market design that no training day comes from.

## Decoding, engine and grading (run 2's, unchanged)
- **Sampled (primary):** T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task, max_tokens 512.
- **Greedy decoding (secondary):** T 0, max_tokens 512.
- **Code:** `results/train/4b-v2/scripts/evaluate.py` and `pathb.py`, unchanged, with `EVAL_PACK` and `N` set per pack.
  - vLLM 0.29 with engine seed 0, `max_model_len` 2048, `gpu_memory_utilization` 0.85, `max_lora_rank` 32.
  - Packages from `results/train/pip_freeze.txt` (torch 2.13, vllm 0.29.0, transformers 5.17.0, peft 0.21.2).
- **Hardware differs from run 2:** one NVIDIA L4 24 GB (g6.4xlarge) instead of an L40S. Sampled text can differ token for token from what an L40S would give, which is why the pipeline check below comes first.
- **Grading:** `gridsim_core` exactly (`pathb.score`, which is `gridsim_core.trl.reward_fn`'s extraction then `grade`, foresight tier, DP anchor). There is no format credit.
- **The greedy rule** is each task's stored `refs.foresight.baselines.greedy` reward, the same field run 1 and run 2 compared against.
  - Re-running `gridsim_core.baselines.greedy` on every task of eval, eval-iid and rtcb and grading it gives 0 reward and 0 schedule mismatches with the stored values (checked before this commit).

## Statistics (run 2's)
- Mean R with a 95% percentile bootstrap CI over tasks (10,000 resamples, seed 0).
- Paired differences on the same tasks with a 95% paired-bootstrap CI (10,000 resamples, seed 0), plus the win and tie rates.
- Also reported: valid, feasible, the error taxonomy, R by start state and by curriculum, and the threshold and clock rules.
- **The rule's CIs, computed from the stored baselines before this commit (no model output involved):**

| Pack | Tasks | Greedy rule | Threshold rule |
| -- | -- | -- | -- |
| eval-iid | 500 | 0.751 [0.724, 0.777] | 0.607 [0.583, 0.632] |
| rtcb | 250 | 0.724 [0.687, 0.759] | 0.664 [0.633, 0.694] |
| eval-2025 (run 2's 200) | 200 | 0.764 [0.726, 0.800] | 0.637 [0.601, 0.673] |

## Bars
- **PRIMARY (eval-iid):** SFT-10k, sampled, beats the greedy rule. Both must hold:
  - its 95% CI lies wholly above the rule's: **lower bound > 0.777**;
  - **≥ 98% valid schedules**.
- **SECONDARY (eval-iid):** the paired difference, SFT-10k sampled minus the greedy rule, has a 95% CI wholly above 0.
- **RTCB-PRIMARY and RTCB-SECONDARY:** the same two tests on rtcb. The primary there needs a **lower bound > 0.759** and ≥ 98% valid.

## The verdict on the post-hoc observation
It rests on the eval-iid tests alone:
- **CONFIRMED:** PRIMARY met.
- **NOT CONFIRMED, BUT AHEAD PAIRED:** PRIMARY not met, SECONDARY met. SFT-10k beats the rule task for task, but the two CIs overlap.
- **NOT CONFIRMED:** neither met, and the paired CI includes 0.
- **REFUTED:** the paired CI lies wholly below 0, so SFT-10k is worse than the rule.

rtcb gets its own verdict in the same terms, as a second, separately named question: does the result carry over to the post-RTC+B market? There is no multiplicity correction, because the headline rests on one test, the eval-iid PRIMARY.

## Registered comparison: SFT-10k vs the run-2 final (eval-iid)
- **The test:** paired, run-2 final sampled minus SFT-10k sampled, on the 500 eval-iid tasks.
  - **"GRPO added"** if its CI lies wholly above 0.
  - **"GRPO cost"** if its CI lies wholly below 0.
  - Otherwise no difference is shown.
- **Run 2's eval-2025 numbers, for reference:** −0.015 [−0.061, +0.030] sampled; −0.046 [−0.090, −0.003] greedy.
- The same difference for greedy decoding is reported, with no verdict.
- **Reported, with no verdict:**
  - the run-2 final on eval-iid against the greedy rule;
  - the run-2 final on rtcb (sampled and greedy), with its gaps to the rule and to SFT-10k.

## Greedy decoding (secondary)
The four bar tests (PRIMARY, SECONDARY and both rtcb tests) are also computed for SFT-10k's greedy decoding. They are reported and carry no weight in the verdict.

## Pipeline check (before any eval-iid or rtcb generation)
- **What runs:** SFT-10k and the run-2 final on run 2's 200 eval-2025 tasks, sampled and greedy, through the same merge, engine and code.
- **Compared against:** run 2's committed `eval_sft.json` and `eval_trained.json`, per task.
- **Pass:** both sampled means fall inside run 2's committed 95% CIs (SFT-10k [0.802, 0.877], final [0.789, 0.860]), and both models have ≥ 98% valid.
- **Fail:** there is no eval-iid or rtcb generation until the fault (merge, packages or engine) is found and fixed. The fix is appended below as an amendment and pushed before those generations.
- **Status of these numbers:** they are reported, but they are not part of any test and they do not replace run 2's numbers.

## Prior (stated so the outcome can be checked against it)
- **eval-iid:**
  - This is the training era, so we expect SFT-10k at 0.82–0.87 sampled.
  - With 500 tasks the CI half-width should be about 0.025. We put the PRIMARY at about 80% and the SECONDARY at about 95%.
- **rtcb:**
  - This is a new market design, and the greedy rule also drops there (0.724). We expect 0.76–0.84.
  - We put RTCB-PRIMARY at about 40% and RTCB-SECONDARY at about 70%.
- **Final minus SFT-10k (eval-iid):** we expect −0.03 to +0.01, with a CI that includes 0.

## Rules
- One pass per (model, pack, decoding). Nothing is rerun to improve a score, and there is no checkpoint picking and no prompt change.
- **Crash:** a run that crashes from an infrastructure fault is rerun with the same command. Every attempt is logged, and only a completed pass is scored.
- **Run order:** the pipeline check, then SFT-10k on eval-iid, SFT-10k on rtcb, the final on eval-iid, and the final on rtcb.

## Budget
- **Box:** one g6.4xlarge (1× NVIDIA L4 24 GB, 16 vCPU, 64 GB RAM) in us-east-1 at about $1.3/h on demand, for about 1–2 h of work.
- **API spend:** none.

## Published whatever the outcome
These go to `results/train/confirm-sft10k/`, with the README labelled "confirmatory, pre-registered":
- `README.md` with the verdicts, the comparison, the pipeline check and any deviation from this file;
- `summary.json` with the verdicts, CIs and paired gaps;
- `eval_*.json` per pack, with per-task rewards;
- `episodes/*.jsonl.gz`;
- `scripts/` and the box's `pip_freeze.txt` and `gpu.csv`.

## Amendments
None yet.
