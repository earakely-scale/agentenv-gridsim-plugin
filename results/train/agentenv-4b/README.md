# Qwen3-4B through AgentEnv: SFT warm start + GRPO 40 on the GridSim v1 training bundle, on one L40S

The run behind the AgentEnv framework docs' Training page. Unlike path B, every rollout is an AgentEnv episode: the
training bundle `agent-env gridsim tasks training-pack` writes (published as `bundles/gridsim-v1/` in the Hub dataset)
is served by `agent_env.training.trl.AgentEnv.local`, each rollout deploys the env, plays one battery-day with
`submit_schedule` as the only tool, and the bundle's verifier scores it. It ran on 2026-10-29 UTC on an AWS
g6e.xlarge (one L40S, 4 vCPUs) with agentenv-framework 0.9.1380, TRL 1.16.0, vLLM 0.29.0 and transformers 5.21.0
(`pip_freeze.txt`), installed with the docs' pip line.

## Results (200 eval-2025 days, the bundle's eval split, one sampled rollout each at temperature 1.1)

| model | mean R | R > 0 | beats idle | at the optimum (R ≥ 0.99) |
|---|---|---|---|---|
| Qwen3-4B base | 0.180 | 89% | 1% | 0% |
| + SFT warm start (GRPO step 0) | 0.569 | 88% | 74.5% | 17% |
| + GRPO 20 steps | 0.562 | 89% | 72% | 12% |
| + GRPO 40 steps | 0.614 | 92% | 78.5% | 13.5% |

- **GRPO from the base model has no signal:** in a 3-step smoke from the base (`smoke-metrics.jsonl`), the base
  submits an idle day on 30 of 32 rollouts a step and one rollout of 96 beat idle; the mean stays at 0.1875.
- **The SFT warm start** is LoRA SFT (r 32, α 64, all linear) for one epoch on one row per train day of the bundle
  (2,000 rows, `sft/gridsim-v1/train.jsonl` in the Hub dataset, written by `scripts/sft_data.py`): the task's own prompt,
  a SoC-aware template rationale of the day's DP optimum (as in `../4b/`), then the `submit_schedule` call with it. The
  rows carry the tools GRPOTrainer renders for the bundle's environment class and thinking off, so SFT trains on the
  exact context GRPO generates from. lr 1e-4, cosine, 10% warmup, batch 8, max length 2,048; 26 min.
- **GRPO** from the merged SFT model: a fresh LoRA (r 32, α 64), 32 rollouts a step (4 days × 8), temperature 1.1,
  `dr_grpo`, β 0, ε_high 0.28, lr 2e-5 cosine with 3 warmup steps, 40 steps; evals at steps 0, 20 and 40.
- **The 40 GRPO steps add +0.045 on the eval**, inside one sampled rollout per day's noise (about ±0.065 at 95% for
  two independent means), and the train reward stays level (first five steps 0.681, last five 0.654). `../4b/` went
  from 0.666 to 0.804 with 330 steps of 64 rollouts.
- **Eval numbers** are the plain mean over the 200 rollouts. TRL's own `eval_reward` (0.561, 0.536, 0.617) averages
  its 7 eval batches' means, the last of them 8 days.

## Time

| stage | wall clock |
|---|---|
| base eval (200 rollouts) | 18 min |
| SFT | 26 min |
| GRPO, 40 steps and three 200-day evals | 3 h 6 min |

A GRPO step took 190 s (median): the 32 episodes deploy concurrently while vLLM generates, which is CPU-bound on 4
vCPUs (about 55 s to the last agent), and TRL collects the 32 rewards one at a time, each waiting out `prompt_agent`'s
2 s poll and the episode's teardown. A 200-day eval took about 15 min.

## Files

- `scripts/`: `setup.sh` (the install and the bundle download), `play.py` (the docs' hand-played rollout, output in
  `play.log`), `sft_data.py` (the SFT rows from the bundle), `sft.py`, `train.py` (GRPO, and with `MAX_STEPS=0` the
  base eval) and `pipeline.sh` (base eval, SFT, GRPO, in order).
- `base-metrics.jsonl`, `grpo-metrics.jsonl`, `smoke-metrics.jsonl`: one line per log, TRL's metrics plus the reward
  rates of the rollouts since the line before. `*-log_history.json`: TRL's log history.
