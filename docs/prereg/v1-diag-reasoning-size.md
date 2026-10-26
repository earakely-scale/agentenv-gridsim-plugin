# GridSimEnv v1: is the ceiling the reasoning budget or the model size? (diagnostic, pre-registered)

Committed and pushed to `main` before any generation in this lane. There is no training. **This is a diagnostic, not a confirmatory test:** it decides where the next training run should spend its compute. It makes no claim about a trained policy, and no number from it replaces a registered result.

## Why
Every registered Qwen number on v1 so far was decoded with thinking off and a 512-token cap (T 0.7, top_p 0.8, top_k 20; run 1 and run 2's `scripts/evaluate.py`). On the 200 eval-2025 tasks:
- **Qwen3-4B base:** 0.061 [0.048, 0.073] sampled. Valid only 35.5%; 48% of completions hit the 512 cap before a `submit_schedule` call.
- **Qwen3-4B SFT-10k (run 2, step 0):** 0.841 [0.802, 0.877]; confirmed on eval-iid at 0.880 [0.858, 0.900].
- **Greedy rule:** 0.764 [0.726, 0.800]. **Threshold rule:** 0.637 [0.601, 0.673].
- GPT-6.1 Sol at high reasoning effort scores about 1.0 on the same task.

Two cheap explanations for the gap to 1.0 compete: the model has no room to reason (thinking off, 512 tokens), or a 4B model is too small. This sweep measures both on base models, plus the SFT-10k model with thinking turned on.

## Rows (the same 200 eval-2025 tasks for every row)
| row | model | thinking | max tokens | role |
|---|---|---|---|---|
| `q4b-off512` | Qwen3-4B base | off | 512 | counterpart; pipeline sanity check against the registered 0.061 |
| `q4b-on4096` | Qwen3-4B base | **on** | 4,096 | primary |
| `q4b-on2048` | Qwen3-4B base | on | 2,048 | budget curve, secondary |
| `q8b-off512` | Qwen3-8B base | off | 512 | primary |
| `q8b-on4096` | Qwen3-8B base | **on** | 4,096 | primary |
| `q14awq-off512` | Qwen3-14B-AWQ base | off | 512 | secondary (quantised) |
| `q14awq-on4096` | Qwen3-14B-AWQ base | on | 4,096 | secondary (quantised) |
| `sft-off512` | Qwen3-4B SFT-10k | off | 512 | counterpart; pipeline check against the registered 0.841 |
| `sft-on2048` | Qwen3-4B SFT-10k | **on** | 2,048 | **out of distribution:** the SFT was trained with thinking off |

- **Models, pinned:**
  - `Qwen/Qwen3-4B` @ `1cfa9a7208912126459214e8b04321603b3df60c` (bf16), the revision runs 1 and 2 used.
  - `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` (bf16).
  - `Qwen/Qwen3-14B-AWQ` @ `31c69efc29464b6bb0aee1398b5a7b50a99340c3`, Qwen's official 4-bit AWQ checkpoint (group size 128). Qwen3-14B in bf16 (about 29.5 GB) does not fit one 24 GB A10G. **Quantisation is a caveat:** a 14B row may differ from bf16 14B, so 14B rows carry no verdict.
  - SFT-10k: run 2's SFT LoRA (`gridsim/adapters/qwen3-4b-gridsim-v1-reg2-seed0.tgz` in object storage, `adapter/sft-lora`) merged into the 4B base exactly as `results/train/confirm-sft10k/scripts/merge.py` did (bf16 on the GPU, `merge_and_unload`).
- All three bases share one chat template (sha256 of `chat_template` starts `a55ee1b1`), so with thinking off every model sees byte-identical prompts. `diag_eval.py` asserts that its thinking-off prompt equals `pathb.prompt_text`, and it logs a hash of each row's prompts.

## Prompt, decoding, engine
- **Prompt:** the oneshot prompt (path B, the training prompt): `gridsim_core.prompt.messages` plus the `submit_schedule` tool schema, foresight tier, through the model's chat template.
  - **Thinking off:** `enable_thinking=False`, which is exactly `pathb.prompt_text`.
  - **Thinking on:** `enable_thinking=True`, with nothing else changed. The model writes a `<think>` block and then, if it gets that far, its answer.
- **Decoding (primary, every row):** run 2's registered sampling, T 0.7, top_p 0.8, top_k 20, seed 0, one sample per task. `max_tokens` covers the thinking and the answer together.
- **Secondary, only if time allows:** Qwen's recommended thinking-mode sampling, T 0.6, top_p 0.95, top_k 20, for the four thinking-on rows at the same budgets. These rows are labelled `-t06`, are reported only, and carry no verdict.
- **Engine:** vLLM 0.29.0 with engine seed 0, `max_model_len` 6,144, `gpu_memory_utilization` 0.92, no LoRA (SFT-10k is merged), one NVIDIA A10G 24 GB (GPU 3 of a g5.12xlarge shared with another lane). Packages come from `results/train/pip_freeze.txt` (torch 2.13, vllm 0.29.0, transformers 5.17.0).
  - Run 2 used an L40S with `max_model_len` 2,048 and LoRA enabled, so sampled text can differ token for token. That is why the thinking-off counterparts are re-run here instead of borrowed.
- **Code:** `results/train/diag-reasoning-size/scripts/diag_eval.py`, committed with this file. It imports run 2's `evaluate.py` (task sample, CI, baselines) and `pathb.py` (prompt, scoring, error taxonomy) unchanged.

## Grading
- **Exactly the trainer's reward:** `pathb.score`, which is `gridsim_core.trl.extract_actions` and then `grade`, foresight tier, with no format credit.
- `extract_actions` drops every `<think>…</think>` block, and an unclosed `<think>` to the end of the text. So the schedule is the first parseable `submit_schedule` call after the thinking. A bare list of 24 integers counts only when there is no tool call, as in training.
- **No valid submit scores 0.** That includes a completion cut off inside its thinking.
- **Tasks:** `ercot-dam-v1-eval`, the 200 tasks of `evaluate.py`'s `default_rng(20251)` permutation: run 1's and run 2's eval set.

## Reported per row
- Mean R with a 95% percentile bootstrap CI (10,000 resamples, seed 0).
- Valid % (a parseable schedule), feasible %, and R ≥ 0.99 count.
- **The error mix**, each completion's first failure as a share of all 200: all idle, overfill, sell before charge, rate, cycle cap, end short, malformed, truncated (no submit). Truncated is split into cut off inside the thinking and cut off after it.
- Mean, median and p90 completion tokens; the share that hit `max_tokens`; mean thinking tokens; the share with a closed `</think>`.
- Wall time of the 200-task vLLM pass on one A10G.

## Pipeline check (before any thinking-on generation)
- **SFT-10k, thinking off:** `sft-off512` must land inside run 2's committed CI [0.802, 0.877] with valid ≥ 98%.
- **4B base, thinking off:** `q4b-off512` must land in [0.03, 0.09]. That band is about twice the registered CI's half-width around 0.061: base-model scores are small and noisy, so this is a sanity band, not a test.
- **If either fails,** there is no further generation until the fault is found and fixed. The fix is appended below as an amendment and pushed first.

## Decision rule
All comparisons are paired on the 200 tasks, with a 95% paired-bootstrap CI (10,000 resamples, seed 0) and the win and tie rates.
- **"Reasoning helps"** at a model if its thinking-on row beats its own thinking-off row with the paired CI wholly above 0.
  - Registered pairs: `q4b-on4096 − q4b-off512` and `q8b-on4096 − q8b-off512`. **The verdict is "reasoning helps" if either is met.**
  - Reported without a verdict: `q4b-on2048 − q4b-off512`, `q14awq-on4096 − q14awq-off512` (quantised), and `sft-on2048 − sft-off512` (out of distribution for the SFT).
- **"Size helps"** if 8B beats 4B at the same setting with the paired CI wholly above 0.
  - Registered pairs: `q8b-off512 − q4b-off512` and `q8b-on4096 − q4b-on4096`. **The verdict is "size helps" if either is met.** Each pair is named in the result.
  - Reported without a verdict: 14B-AWQ minus 8B at both settings.
- Also reported: `q4b-off512` against the registered per-task 4B base (`results/train/4b/eval_base.json`), and `sft-off512` against run 2's `eval_sft.json`.
- There is no multiplicity correction: this is a diagnostic, and the verdicts steer the next run's design; they are not claims.

## What each outcome means for the next training run
- **Reasoning helps, size does not:** the next run trains with thinking on and a larger budget (for example 2,048 tokens), starting from a thinking-mode warm start instead of the thinking-off SFT-10k.
- **Size helps, reasoning does not:** the next run uses Qwen3-8B with run 2's SFT-10k recipe, thinking off.
- **Both:** 8B with thinking on, if the measured token and wall costs fit a training box; otherwise the larger of the two gains decides.
- **Neither:** the ceiling is not budget or size at this scale. Keep 4B with thinking off, and look at the training signal instead (registered run 3's DP-exact advantages).
- **Caveat for all of these:** base-model rows measure zero-shot ability, not what training could reach. The only trained row with thinking on, `sft-on2048`, is out of distribution. The verdicts are evidence about headroom, not a forecast of a trained score.

## Prior (stated so the outcome can be checked against it)
- `q4b-on4096`: 0.25–0.45, with many completions cut off inside the thinking. "Reasoning helps" at 4B: about 85%.
- `q8b-off512`: 0.05–0.20. `q8b-on4096`: 0.30–0.55. "Size helps" thinking on: about 55%; thinking off: about 50%.
- `q14awq-on4096`: 0.35–0.60.
- `sft-on2048`: 0.70–0.85, and no better than `sft-off512` (about 70% that its paired CI includes or lies below 0).

## Rules and budget
- One pass per row. Nothing is rerun to improve a score, and no prompt is changed.
- **Crash:** a pass that crashes from an infrastructure fault (OOM, engine error) is rerun with the same command; every attempt is logged, and only a completed pass is scored.
- **Run order:** the pipeline check (`q4b-off512`, `sft-off512`), then `q4b-on4096`, `q4b-on2048`, `q8b-off512`, `q8b-on4096`, `q14awq-off512`, `q14awq-on4096`, `sft-on2048`, then the `-t06` rows.
- **Stop:** whatever has not started by 01:30 UTC on 2026-10-27 is dropped, `-t06` rows first, and the README says so. The box powers off at about 03:15 UTC.
- **Box:** GPU 3 of a g5.12xlarge (4× A10G) already running for another lane; expected 2–4 GPU-hours. **API spend:** none.

## Published whatever the outcome
These go to `results/train/diag-reasoning-size/`, with the README labelled "diagnostic":
- `README.md` with the table, both verdicts and what they imply;
- `summary.json` with every row's numbers, CIs and the paired gaps;
- a chart of mean R by model and thinking setting with CIs, with the greedy rule, threshold rule and SFT-10k as reference lines;
- `eval_*.json` with per-task rewards, `episodes/*.jsonl.gz`, `scripts/`, the box's `pip_freeze.txt` and `gpu.csv`.

## Amendments

### Amendment 1 (2026-10-26 ~16:40 UTC): a 16,384-token budget probe, before any amended generation
- **What happened:** `q4b-on4096` finished with R 0.000. All 200 completions hit 4,096 tokens inside `<think>`; none closed it, so none reached a `submit_schedule` call. Reading the episodes shows coherent, non-repeating reasoning (3% duplicate lines), not loops. At this budget, thinking mode never gets to an answer.
- **So the registered pairs at 4,096 measure the budget,** not whether reasoning helps given room. They stay registered and are reported as written, and the README will say that a "reasoning helps: not met" verdict is a statement about a 4,096-token budget.
- **Added rows (budget probe; reported only, no verdict):**
  - `q4b-on16384-n50` and `q8b-on16384-n50`: thinking on, `max_tokens` 16,384, `max_model_len` 17,664, the same T 0.7 sampling and engine settings.
  - Both run on the first 50 of the 200 tasks (the same permutation's first 50, `evaluate.py`'s checkpoint subset), paired against the same 50 tasks of the thinking-off rows.
  - **Why 50:** on one A10G the 4B row took 1,443 s for 819k generated tokens. At 16k per completion, all 200 tasks would take over 3 h for 4B and far longer for 8B, whose bf16 weights leave about 4 GB for the KV cache.
- **Order:** the registered primaries first, then `q4b-on16384-n50`, then `q8b-on16384-n50`, then the `-t06` rows.
  - Rows already written are skipped, which is how the running unit is replaced by `scripts/run_unit2.sh` between two rows.
  - The 01:30 UTC stop applies to every engine call, and any call still running at 02:15 UTC is killed so the results can be packed before the box powers off. A killed row is reported as not completed.
- **Nothing registered changes:** the rows, pairs, verdict rules and prior above are as committed in a6d8d0b.
