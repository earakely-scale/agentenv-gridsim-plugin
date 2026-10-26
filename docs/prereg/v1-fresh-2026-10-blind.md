# GridSimEnv v1, fresh days 2026-10-18 to 2026-10-27: blind-tier baseline (pre-registration)

**A diagnostic baseline, not a claim.** Committed and pushed before any blind-tier generation on these tasks. There is
no training. It measures where the blind tier stands on the newest ERCOT days before any model is trained for it
(FD-4420's target claim: a 4B trained on ERCOT history out-earns GPT-6.1 Sol bidding the day blind). 10 days is a
small sample, and this is the first blind entry of a running scoreboard.

## Tasks: `ercot-dam-v1-fresh-2026-10-blind`
- **331 tasks**: the fresh-2026-10 tasks (see [`v1-fresh-2026-10.md`](v1-fresh-2026-10.md)) that build_pack's rule
  marks blind (`tags.blind_eval`: the D-7..D-1 history exists and the blind anchor clears the low-spread margin; 31 of
  362 fail it). Rows are unchanged; `scripts/build_fresh_blind_pack.py` copies them and adds rule references.
  Per day: 41, 29, 46, 45, 53, 28, 19, 10, 34, 26 (2026-10-27).
- **What the agent sees** (docs/CONTRACT.md's blind tier): the battery, D-1's 24 DAM prices and D-7..D-1's, at that
  point. Not day D's. The history comes from the NP4-180-ER file through 2026-10-17 and the API pull from 2026-10-18;
  the two agree exactly where they overlap.
- **Graded on day D's realized DAM prices.** 2026-10-27's were posted on 10-26, so all 331 are gradable now. These
  tasks are bid on history alone, so nothing in a model's training data can contain the answer. They are not "live"
  bids: the history and the answer were both public when the models run.

## References (each task carries them; computed before this commit, no model output)
- **Hindsight:** the DP on day D's prices, P_opt (C = 1 by definition).
- **Blind anchor:** max(persistence-DP, ridge-DP), the DP on D-1's prices or on ridge-v1's forecast
  (`data/ridge-v1.json`), each settled on day D. Stored as `refs.blind` by build_pack's code.
- **Greedy and threshold rules on D-1's prices**, settled on day D (`refs.blind.rules.greedy_d1`, `threshold_d1`): the
  heuristics with only what the blind tier shows.
- **Idle.**

## Models
- **GPT-6.1 Sol** (`openai/gpt-6.1-sol`, reasoning effort `high`), path B: `gridsim_core.prompt.messages(task,
  "blind", 0)` and the single `submit_schedule` tool, one Responses request per task, one sample, `max_output_tokens`
  16,384, transport retries only. Same script and grader as the foresight lane
  (`results/fresh/2026-10/scripts/sol_eval.py`, tier `blind`). **Spend cap $15**, with the same pre-request guard.
- **Run 3 final and SFT-10k, zero-shot and out of distribution.** Both were trained only on the foresight prompt;
  neither has seen the blind prompt or a price forecast target. Same models, merge, engine and decoding as the
  foresight lane: sampled T 0.7 / top_p 0.8 / top_k 20 / seed 0 (primary) and greedy decoding, max_tokens 512.
  - **Two changes to the eval code, both forced by the tier:** `pathb.TIER` comes from the environment (`blind`), and
    `max_model_len` is 4,096 instead of 2,048, because the blind prompt carries 192 prices (about 2,000 tokens) and
    would not fit with 512 output tokens. The copies are in `results/fresh/2026-10-blind/scripts/`.

## Metrics (the cross-version rule)
- **Headline: hindsight capture C** = clip(0.2 + 0.8 (P − P_idle) / (P_opt − P_idle), 0, 1), per model, with its
  **paired Δ against the blind anchor's C** on the same tasks.
- **Second column: R on the anchor's scale** (the blind tier's reward, anchor = 1.0), and the share of tasks that beat
  the anchor.
- **Key gaps (C, paired):** Sol − anchor; run 3 − Sol; SFT-10k − Sol; also run 3 − SFT-10k.
- **CIs:** a block bootstrap over the 10 days (10,000 resamples, seed 0, every task of a drawn day, task-weighted mean),
  and the naive task-level bootstrap labelled as such. A gap is **shown** when its day-block CI lies wholly on one side
  of 0. No pass/fail bar.
- **2026-10-27 on its own** (26 tasks), descriptive.
- **Error mix** per model: valid, overfill, sell-before-charge, end-short, cycle cap, rate, all-idle, invalid.
- Sol's tokens and spend; the 4Bs are reported for sampled and greedy decoding.

**Reference values on these 331 tasks (C, day-block CI):** anchor 0.919 [0.862, 0.960]; ridge-DP 0.885; persistence-DP
0.871; greedy rule on D-1 0.755 [0.675, 0.813]; threshold rule on D-1 0.742. Ridge-DP − anchor −0.034, persistence-DP
− anchor −0.048. On 2026-10-27: anchor 0.895, persistence 0.865, ridge 0.834, greedy-D1 0.739, threshold-D1 0.519.

## Prior (stated so the outcome can be checked against it)
- **Sol:** C close to the anchor's, Δ between −0.03 and +0.01, not shown (on eval-2025's blind column, full harness, it
  was 0.9165 against the anchor's 0.9204).
- **The 4Bs zero-shot:** well below the anchor. They have only ever planned on the day's own prices; most likely they
  plan on D-1's prices as if they were today's, which is a persistence heuristic with their foresight error rate on
  top. We expect C 0.70–0.85, below Sol and the anchor with shown gaps, and more invalid schedules than on the
  foresight tier.

## Rules
- One pass per (model, decoding); nothing rerun to improve a score; no prompt change.
- Infrastructure crashes are rerun with the same command and logged.
- The box powers off at about 03:15 UTC; if this cannot finish by about 02:30 UTC, what is finished is published and
  the rest is listed as not run.

## Published whatever the outcome
`results/fresh/2026-10-blind/`: `README.md` (the C / R table, the key gaps, 2026-10-27 alone, the error mix),
`summary.json`, per-task eval files, gzipped episodes and `scripts/`.

## Amendments
None yet.
