# Qwen3-4B SFT-10k: confirmatory evaluation on fresh tasks

**This evaluation is confirmatory and was pre-registered.** The plan is [`docs/prereg/v1-confirm-sft10k.md`](../../../docs/prereg/v1-confirm-sft10k.md). It was committed to `main` (e9ce27e) before any generation. There is no training in this lane. It ran on 2026-10-26 UTC.

**What it tests.** In registered run 2 (`../4b-v2/`), the SFT-10k warm start scored 0.841 [0.802, 0.877] sampled on the 200 eval-2025 tasks, against the greedy rule's 0.764 [0.726, 0.800].
- Its CI's lower bound cleared the rule's upper bound.
- That observation was **post hoc**: run 2 registered its final GRPO adapter as the claim, not SFT-10k.
- This lane re-tests it on 750 tasks that no Qwen model in this repo had seen or been scored on:
  - **eval-iid:** 500 tasks, the primary pack;
  - **rtcb:** 250 tasks from after RTC+B went live.
- The result is published whatever it is.

## Verdicts

| bar | result | verdict |
|---|---|---|
| **PRIMARY (eval-iid, 500):** SFT-10k sampled beats the greedy rule with non-overlapping 95% CIs, and is ≥ 98% valid | SFT-10k **0.880 [0.858, 0.900]**, valid 100%; greedy rule 0.751 [0.724, 0.777] | **MET** (0.858 > 0.777) |
| **SECONDARY (eval-iid):** the paired difference, SFT-10k sampled minus the rule, has its 95% CI above 0 | **+0.128 [+0.096, +0.161]**; wins 55%, ties 23% | **MET** |
| **RTCB-PRIMARY (rtcb, 250):** the same test on post-RTC+B days | SFT-10k **0.786 [0.747, 0.825]**, valid 99.6%; greedy rule 0.724 [0.687, 0.759] | **NOT MET** (0.747 < 0.759, short by 0.012) |
| **RTCB-SECONDARY:** paired, SFT-10k sampled minus the rule | **+0.062 [+0.009, +0.113]**; wins 59%, ties 12% | **MET** |

**The post-hoc observation is CONFIRMED.** On eval-iid, SFT-10k's CI lies wholly above the greedy rule's, with 100% valid schedules.

**On rtcb, the verdict is NOT CONFIRMED, BUT AHEAD PAIRED.** SFT-10k beats the rule task for task after RTC+B, but the two CIs overlap. Its lead shrinks from +0.128 on eval-iid to +0.062.

**Registered comparison, run-2 final minus SFT-10k** (eval-iid, sampled):
- **+0.004 [−0.022, +0.031]**, wins 27%, ties 47%: **no difference shown.**
- With greedy decoding (reported only): −0.015 [−0.040, +0.010].
- This matches run 2's eval-2025 finding (−0.015 sampled): GRPO on top of SFT-10k neither added nor cost anything that can be measured.
- On rtcb (reported only), the final trails SFT-10k by −0.015 [−0.058, +0.029] sampled and −0.039 [−0.084, +0.008] greedy.
- The final has fewer exact optima than SFT-10k on both packs (R ≥ 0.99):
  - eval-iid: 282 → 255 of 500;
  - rtcb: 95 → 72 of 250.

**Greedy decoding** (secondary, carries no weight in the verdict):
- **eval-iid:** SFT-10k 0.899 [0.879, 0.918], paired +0.148 [+0.114, +0.181]; both bars met.
- **rtcb:** 0.809 [0.772, 0.843], paired +0.085 [+0.033, +0.134]. That lower bound would clear the rule's 0.759, but the registered test is the sampled one.

**Against the prior:**

| test | expected | result |
|---|---|---|
| eval-iid PRIMARY (~80%) | 0.82–0.87 | 0.880, met |
| eval-iid SECONDARY (~95%) | | met |
| rtcb PRIMARY (~40%) | 0.76–0.84 | 0.786, not met |
| rtcb SECONDARY (~70%) | | met |
| final minus SFT-10k | −0.03 to +0.01, CI including 0 | +0.004, CI includes 0 |

eval-iid came in slightly above the expected range.

## Results

### eval-iid (500 tasks, every 10th calendar date 2014–2024, foresight, oneshot prompt, path B)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | rate | cycle cap | end short | truncated | R ≥ 0.99 | R empty / half / full start | R C0 / C1 / C2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SFT-10k (run 2, step 0)** | **sampled** | **0.880** | **[0.858, 0.900]** | 100% | 87.0% | 4.6% | 4.0% | 2.8% | 1.6% | 3.2% | 0% | 282 | 0.903 / 0.873 / 0.856 | 0.885 / 0.860 / 0.891 |
| SFT-10k (run 2, step 0) | greedy | 0.899 | [0.879, 0.918] | 100% | 88.0% | 3.8% | 4.8% | 2.0% | 1.4% | 2.4% | 0% | 296 | 0.923 / 0.871 / 0.900 | 0.893 / 0.919 / 0.890 |
| run-2 final (SFT-10k + GRPO 310) | sampled | 0.884 | [0.864, 0.903] | 99.4% | 87.0% | 4.8% | 5.8% | 0% | 1.8% | 2.4% | 0.6% | 255 | 0.915 / 0.854 / 0.877 | 0.904 / 0.890 / 0.847 |
| run-2 final (SFT-10k + GRPO 310) | greedy | 0.884 | [0.864, 0.903] | 99.2% | 87.4% | 4.6% | 4.8% | 0% | 2.4% | 1.6% | 0.8% | 257 | 0.900 / 0.855 / 0.896 | 0.909 / 0.890 / 0.841 |
| greedy rule | – | 0.751 | [0.724, 0.777] | 100% | | | | | | | | 151 | 0.770 / 0.746 / 0.734 | |
| threshold rule | – | 0.607 | [0.583, 0.632] | 100% | | | | | | | | | 0.545 / 0.642 / 0.650 | |
| clock rule | – | 0.555 | [0.531, 0.578] | 100% | | | | | | | | | 0.548 / 0.524 / 0.599 | |

- **Start states:** 191 empty, 167 half and 142 full. **Curriculum:** 214 C0, 141 C1 and 145 C2.
- Error rates are each completion's first failure, as a share of all 500 tasks.
- **The run-2 final against the rules** (sampled): greedy rule +0.132 [+0.102, +0.164]; threshold rule +0.276 [+0.246, +0.307].
- **SFT-10k against the threshold rule** (sampled): +0.272 [+0.239, +0.304].

### rtcb (250 tasks, 2025-12-05 to 2026-10-17, post-RTC+B, foresight, oneshot)

| model | decoding | mean R | 95% CI | valid | feasible | overfill | sell before charge | rate | cycle cap | end short | truncated | R ≥ 0.99 | R empty / half / full start | R C0 / C1 / C2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SFT-10k (run 2, step 0)** | **sampled** | **0.786** | **[0.747, 0.825]** | 99.6% | 78.4% | 13.2% | 4.0% | 2.0% | 2.0% | 3.2% | 0.4% | 95 | 0.701 / 0.808 / 0.857 | 0.756 / 0.801 / 0.803 |
| SFT-10k (run 2, step 0) | greedy | 0.809 | [0.772, 0.843] | 100% | 76.4% | 14.8% | 3.6% | 2.0% | 3.2% | 2.4% | 0% | 94 | 0.755 / 0.828 / 0.847 | 0.800 / 0.791 / 0.829 |
| run-2 final (SFT-10k + GRPO 310) | sampled | 0.771 | [0.733, 0.808] | 99.2% | 78.8% | 12.0% | 5.6% | 1.6% | 1.2% | 2.8% | 0.8% | 72 | 0.768 / 0.720 / 0.838 | 0.806 / 0.747 / 0.756 |
| run-2 final (SFT-10k + GRPO 310) | greedy | 0.770 | [0.732, 0.806] | 99.6% | 78.4% | 11.6% | 6.0% | 1.6% | 2.0% | 2.4% | 0.4% | 71 | 0.782 / 0.697 / 0.846 | 0.814 / 0.722 / 0.765 |
| greedy rule | – | 0.724 | [0.687, 0.759] | 100% | | | | | | | | 24 | 0.759 / 0.734 / 0.671 | |
| threshold rule | – | 0.664 | [0.633, 0.694] | 100% | | | | | | | | | 0.654 / 0.677 / 0.659 | |
| clock rule | – | 0.435 | [0.399, 0.471] | 100% | | | | | | | | | 0.401 / 0.415 / 0.499 | |

- **Start states:** 86 empty, 90 half and 74 full. **Curriculum:** 88 C0, 69 C1 and 93 C2.
- **The run-2 final against the greedy rule** (sampled): +0.047 [+0.001, +0.093].
- **The post-RTC+B drop is led by overfill** (charging past full).
  - Overfill rises from 4.6% of SFT-10k's tasks on eval-iid to 13.2% on rtcb (sampled).
  - Its share of the reward lost rises from 18% to 42%.
  - Empty-start days drop the most: R 0.903 → 0.701, with overfill on 14 of 86 and half of that start's lost reward.
  - The greedy rule barely moves on empty starts (0.770 → 0.759).

## Pipeline check (eval-2025, before any eval-iid or rtcb generation)

The same merge, engine and code were run on run 2's 200 eval-2025 tasks and compared per task with run 2's committed files. **The gate passed**: both sampled means fall inside run 2's CIs, and both models are ≥ 98% valid. These numbers are not part of any test and do not replace run 2's.

| model | decoding | this box (L4) | run 2 (L40S) | this box minus run 2 (paired) | identical schedules |
|---|---|---|---|---|---|
| SFT-10k | sampled | 0.846 [0.808, 0.881], valid 99.5% | 0.841 [0.802, 0.877] | +0.005 [+0.000, +0.013] | 95.5% |
| SFT-10k | greedy | 0.870 [0.836, 0.901] | 0.870 [0.835, 0.902] | +0.001 [−0.014, +0.016] | 94.5% |
| run-2 final | sampled | 0.840 [0.805, 0.871], valid 99.5% | 0.825 [0.789, 0.860] | +0.014 [−0.002, +0.033] | 93.0% |
| run-2 final | greedy | 0.820 [0.782, 0.856] | 0.824 [0.787, 0.858] | −0.004 [−0.023, +0.016] | 91.0% |

The L4 and the L40S produce the same schedule on 91–96% of tasks. The other 4–9% differ through kernel-level numerics in vLLM. That moves the means by at most 0.014, which is small next to the margins above.

## What this does and does not show
- **No training contamination:** eval-iid and rtcb share 0 task ids and 0 dates with SFT-10k's 10,000 training tasks. They also share none with the 20,000-task train pack that GRPO drew from (`summary.json` → `overlap`).
- **eval-iid's limit:** its days are interleaved with training days of the same years (every 10th calendar date), so neighbouring days were trained on.
  - It tests unseen days of the training era. It does not test a shift in time.
  - rtcb is that test: a later market design, which no training day comes from. There SFT-10k still beats the rule task for task, but by half the margin, and its CI overlaps the rule's.
- **The greedy rule** is each task's stored `refs.foresight.baselines.greedy`, the same field runs 1 and 2 compared against. Re-running `gridsim_core.baselines.greedy` on every task of eval, eval-iid and rtcb gives 0 reward and 0 schedule mismatches.
- **One sample per task** at T 0.7, as registered. There is no best-of-n.

## Setup
- **Models:**
  - SFT-10k is run 2's `adapter/sft-lora` merged into `Qwen/Qwen3-4B` @ `1cfa9a72` in bf16 on the GPU, as `scripts/sft.py` did it (`scripts/merge.py`).
  - The run-2 final is `adapter/grpo-lora` (step 310), served by vLLM as a LoRA on the merged model.
  - Both come from object storage, `gridsim/adapters/qwen3-4b-gridsim-v1-reg2-seed0.tgz`, sha256 `69c5f4a6aa03ad14a780d603f83a17f1298bc0cfb9390c27fa301a9f4cb6e33f`.
- **Code:** `scripts/evaluate.py` and `scripts/pathb.py` are unchanged copies of `../4b-v2/scripts/`.
  - `EVAL_PACK` and `N` set the pack (500 for eval-iid, 250 for rtcb, 200 for the check).
  - The tasks are ordered by `default_rng(20251)`; with N equal to the pack size, every task is kept.
- **Decoding:**
  - Sampled: T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task, max_tokens 512.
  - Greedy: T 0.
  - Engine: vLLM 0.29.0, engine seed 0, `max_model_len` 2048, `gpu_memory_utilization` 0.85.
- **Grading:** `gridsim_core` exactly, foresight tier, DP anchor, no format credit.
- **Statistics:** 95% percentile bootstrap over tasks, and a paired bootstrap on the same tasks (10,000 resamples, seed 0).
- **Packages:** `pip_freeze.txt`, identical to `../pip_freeze.txt` apart from the plugin and HF tools: torch 2.13, vllm 0.29.0, transformers 5.17.0, peft 0.21.2.
- **Box:** g6.4xlarge in us-east-1 (1× NVIDIA L4 24 GB; run 2 used an L40S), `gpu.csv`.
- **Timing:**
  - setup and merge 13:41–13:45 UTC;
  - pipeline check 13:45–13:55;
  - the four registered passes 13:55–14:23, in the registered order, at 2–4 min of generation each.
- **Cost:** about 1 box-hour, about $1.3. No API spend.

## Deviations from the registration
None. The run order, decoding, code and bars are as registered. The eval files are named `eval_iid_*.json` and `rtcb_*.json`, with `final` for the run-2 final; the episodes call it `trained`.

## Files
- `summary.json`: the verdicts, the bars for sampled and greedy decoding, the SFT-vs-final comparison, per-pack rows with error taxonomy and splits, all paired gaps, the overlap check and the pipeline check.
- `eval_iid_sft.json`, `eval_iid_final.json`, `rtcb_sft.json` and `rtcb_final.json`: evaluate.py's output with per-task rewards, validity, error kind and actions.
- `check_eval2025_sft.json` and `check_eval2025_final.json`: the pipeline check.
- `episodes/*.jsonl.gz`: Episode JSON lines for every completion.
- `scripts/`:
  - `setup_unit.sh` (venv, model, adapters, merge);
  - `merge.py`;
  - `eval_unit.sh` (check, gate, then the four passes);
  - `gate.py`;
  - `report_confirm.py` (builds this folder: `python report_confirm.py SRC ../4b-v2 .`);
  - `evaluate.py` and `pathb.py`.
- `pip_freeze.txt`, `gpu.csv` and `gpu_eval.csv`.
