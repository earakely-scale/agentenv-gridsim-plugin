# Qwen3-4B on GridSim desk operating days through AgentEnv: the GRPO pilot kit (one H100)

The kit for fine-tuning Qwen3-4B (revision `1cfa9a72`, thinking on, LoRA) with TRL's `GRPOTrainer` on the GridSim
desk, every rollout an AgentEnv episode: the `desk-v4-train` bundle is served by
`agent_env.openenv.build_app` (`scripts/serve.py`, under systemd on the GPU box), and the trainer reads it with
`agent_env.training.trl.AgentEnv("http://127.0.0.1:8000")`. A rollout is one operating day under the v4 layer and env,
with the benchmark's eleven desk tools, and its reward is the hindsight capture C floored at -1. The first run is a
10-step pilot on one GPU box that runs the env server too. One step has run on an L40S (GPU check below); the
pilot itself hasn't run.

## The data: `desk-v4-train`

24 three-day windows (D0..D2) at all four sites, 96 site-windows and 288 operating days, built by
`scripts/desk_data_build.py desk-v4-train` (docs/desk-data.md §14): only 2025-12-20..2026-01-22 and
2026-05-11..2026-07-03, so the benchmark's January–May half and its July–August post-cutoff half keep their regimes to
themselves; the builder's DST and price checks; every day more than 3 days from every day of `desk-v4-bench`,
`desk-v4-eval` and `desk-v4-pilot`. A task is one operating day under the v4 layer (`n_days: 1`): the start at D-1
06:00 with the day's DAM, real time through D 24:00. References at `desk-v4-freeze`; C is defined on every day.

| | Dec 20–Jan 22 | May 11–Jul 3 | all |
|---|---|---|---|
| windows per site | 9 | 15 | 24 |
| days in the pack (4 sites) | 108 | 180 | 288 |
| `train` days in the bundle | 60 (15 a site) | 155 (39, 38, 39, 39) | 215 |
| `val` days in the bundle | 12 (window 01-13) | 24 (windows 06-06, 06-09) | 36 |

The bundle leaves out the 37 days whose operator disclosure fails the builder's `operator_ok` check (12-20..12-28 at
every site, where ERCOT's 60-day SCED AS-offer report has no rows, and 06-03 at S02); only the operator-replay
reference reads it (`--operator-gaps` keeps them). Day kinds in the bundle: 137 quiet, 53 negative-price, 52 notice,
9 outage.

The reference policies on the bundle's days (played in process; C floored at -1 as the reward is):

| | anchor C mean | anchor C median | anchor above idle | anchor R mean | idle C |
|---|---|---|---|---|---|
| train (215) | 0.076 | 0.071 | 73% | 0.687 | 0 on every day (R 0.2) |
| train, Dec–Jan (60) | 0.095 | 0.086 | 80% | 0.763 | 0 |
| train, May–Jun (155) | 0.069 | 0.060 | 70% | 0.658 | 0 |
| val (36) | 0.051 | 0.079 | 75% | 0.679 | 0 |

No anchor day reaches the -1 floor. On a single day the information-matched anchor captures far less of hindsight than
on a three-day window, and ends below idle on 27% of days.

## The bundle and the reward

`python scripts/desk_train.py bundle --out bundles/desk-v4-train` (in a full clone of the plugin, since it reads both
packs from their commits) writes the bundle: every task
is one operating day as `agent-env gridsim desk-tasks` writes it (the plain default agent, no harness config, the
`gridsim-desk-hook` post-turn hook, the env's clock armed frozen at D-1 06:00), on `gridsim-desk-v4` built from the
plugin at `desk-v4-freeze` with the `desk-v4-bench` and `desk-v4-train` packs added from their commits. Splits:

| split | tasks | what |
|---|---|---|
| `train` | 215 | the pack's train days |
| `val` | 36 | the days of the windows 01-13, 06-06 and 06-09 at all four sites |
| `bench` | 32 | `desk-v4-bench`'s three-day windows with the same `capture` step (they overflow the training context; the leaderboard eval is OpenCode's) |
| `all` | 283 | every task, as `build_app` serves any bundle |

Two steps score each task. `grade` is the benchmark's verifier, unchanged: the reward R. `capture` is
`gridsim-desk-capture-verifier` (`src/agentenv_gridsim/training-pack-desk-verify.py`): the hindsight capture
C = (P - P_idle) / (P_hind - P_idle) floored at -1 (idle 0, gains count fully, losses count against), 0 where C is
undefined. A verifier step's score is clamped to [0, 1] by the framework (`aggregate_score`), so the step records
(max(C, -1) + 1) / 2 and the served reward undoes the shift. With two scored steps a server needs `reward=`:

```python
reward = lambda scores: 2 * scores["capture"] - 1        # C floored at -1, the training reward
build_app("bundles/desk-v4-train", reward=reward)       # what serve.py does; REWARD=grade serves R
AgentEnv.local("bundles/desk-v4-train", split="train", reward=reward)   # one machine
```

`AgentEnv("http://...")` takes no `reward`: the server's `build_app` fixes it, so the trainer reads whatever the env
box serves, and `get_reward()` returns max(C, -1) for a scored rollout and `None` for one that ended in an error.

## Commands

One GPU box runs both the env server and the trainer, the server under systemd on `127.0.0.1:8000` (no traffic between
boxes). The Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04, Docker included), 400 GB root, as `ubuntu`:

```bash
git clone -b desk-train https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
sudo bash plugin/results/train/desk-4b/scripts/setup-box.sh    # FRAMEWORK=0.9.1387, PLUGIN_REF=desk-train by default
# the pilot: 10 steps, the 36 val days evaluated at step 0 and step 10, LoRA checkpoints at steps 5 and 10
OUT=out-pilot MAX_STEPS=10 bash plugin/results/train/desk-4b/scripts/run.sh > pilot.log 2>&1
# an eval only (one sample per val day; EVAL_LIMIT=8 for a quick one; EVAL_SPLIT=bench for the three-day windows)
OUT=out-base MAX_STEPS=0 bash plugin/results/train/desk-4b/scripts/run.sh
```

`setup-box.sh` (as root): inotify limits, `ubuntu` in the `docker` group, then `setup-env.sh` (the plugin, a venv with
`agentenv-framework[openenv]`, the bundle in `~/bundles/desk-v4-train`, a local agent-env profile) and `setup.sh` (a
venv with `agentenv-framework[trl]`, `trl[vllm,peft]==1.16.*`, `vllm==0.29.*`, Qwen3-4B at `1cfa9a72` in
`~/models/Qwen3-4B`, a GPU check) as `ubuntu`, then the `desk-env` unit (`desk-env.service`, log in
`~/desk-env.log`), whose first start builds the env image; it returns once the server answers. Both installs fall back
to the framework wheel's URL from PyPI's JSON API while the simple index lags a release. `MAX_CONCURRENT_ENVS=48`: the
trainer holds one session per rollout in flight (32; the val eval's 12 reuse them) plus the factory's probe, with room
for a dropped session's replacement while the old one closes. A run under `systemd-run` survives a dropped SSM session:
`sudo systemd-run --uid=ubuntu --unit=desk-pilot --setenv=HOME=/home/ubuntu --setenv=OUT=out-pilot
--setenv=MAX_STEPS=10 --property=StandardOutput=append:/home/ubuntu/pilot.log bash
/home/ubuntu/plugin/results/train/desk-4b/scripts/run.sh`.

`run.sh` picks vLLM's mode from the GPU count (`VLLM_MODE` overrides):

- **One GPU:** `vllm_mode="colocate"`, vLLM beside the trainer, asleep while it optimises (see GPU memory).
- **N > 1 GPUs:** `vllm_mode="server"`: `trl vllm-serve` on GPUs 1..N-1 with data parallel N-1 and tensor parallel 1
  (Qwen3-4B fits on one GPU), the same model files, `max_model_len` 40,960, on `127.0.0.1:8001`; the trainer on GPU 0.
  The server needs no LoRA flags: TRL 1.16 merges the adapter, streams the merged weights to the server over NCCL
  (vLLM's weight-transfer engine, 0.28 and later) and unmerges, every step. In TRL 1.16 the tool loop,
  `environment_factory` and PEFT take the same path in either mode (generation from token IDs; the trainer bounds a
  rollout by the model's 40,960 positions instead of vLLM's `max_model_len`). Not run on a multi-GPU box yet.

Everything else is the same in both modes: the settings below, 32 rollouts a step, the C reward and the eval.

On separate boxes, run `setup-env.sh` and `serve.py` (with `HOST=0.0.0.0`) on a CPU box with Docker, `setup.sh` on the
GPU box, and set `ENV_URL=http://ENV_HOST:8000`.

**GPU memory.** Training one sequence (Qwen3-4B, LoRA r 32 on all linear layers, gradient checkpointing, the
log-probs of every completion token over the 151,936-token vocabulary) peaks, measured on the L40S:

| sequence (tokens) | 8,192 | 16,384 | 24,576 | 32,768 | 40,960 |
|---|---|---|---|---|---|
| peak GiB | 15.0 | 22.7 | 31.1 | 39.5 | out of memory on 44.4 (about 48 by the trend) |

So at 40,960 tokens training needs about 48 GB on its own, beside vLLM's weights and cache. On one GPU vLLM therefore
sleeps while the trainer optimises (`vllm_enable_sleep_mode`, `VLLM_SLEEP=1`, the default) and takes 0.6 of the GPU
while it generates (`VLLM_MEM`): TRL re-merges the LoRA and reloads the weights at every generation call, which costs
far less than the KV cache it frees (on the L40S, generation took 17 minutes a step this way against 29 with vLLM
resident at 0.35). By GPU:

- **H100 80 GB** (`p5.4xlarge`): the settings as they are.
- **RTX PRO 6000 Blackwell 96 GB** (`g7e`): the settings as they are. Compute capability 12.0 (`sm_120`): the PyPI
  torch 2.13 and vLLM 0.29 wheels are CUDA 13 builds (base Qwen's bench boxes ran torch 2.13.0+cu130), which need
  NVIDIA driver 580 or later; `setup.sh` prints the driver and the arch and runs a bf16 matmul on the card. vLLM uses
  FlashAttention 2 or FlashInfer there (FlashAttention 3 is Hopper-only). Its memory bandwidth is about half an H100's,
  so generation is slower.
- **L40S 48 GB** (`g6e`): `CONTEXT=28672`, which the GPU check below ran; 40,960 runs out of memory in the backward pass.
- **A100 40 GB** (`p4d.24xlarge`, server mode, the trainer alone on GPU 0): `CONTEXT=28672` as on the L40S.
- **Several GPUs** (server mode): the trainer's GPU holds no vLLM; 80 GB cards take 40,960.

The leaderboard score of a trained LoRA comes from OpenCode on the 32 bench windows, as base Qwen's did:
[`opencode_eval.md`](opencode_eval.md), with a two-window check for a pilot checkpoint.

The CPU check (no model, any machine with Docker; `AGENT_ENV_CONFIG` and `XDG_STATE_HOME` as in `desk-env.service`):

```bash
python results/train/desk-4b/scripts/replay.py --bundle bundles/desk-v4-train \
  --pack-dir data/desk/desk-v4-train --split train --limit 8 --parallel 4 --out replay.json
```

## The trainer's settings (`scripts/train.py`)

| setting | value | why |
|---|---|---|
| model | Qwen3-4B at `1cfa9a72`, LoRA r 32, α 64, all linear | the benchmark's revision; the v1 run's adapter |
| thinking | `chat_template_kwargs={"enable_thinking": True}` | as the benchmark's Qwen |
| rollouts | 32 a step: 4 days × 8 generations (`per_device_train_batch_size=1`, `gradient_accumulation_steps=32` (`ROLLOUTS`), `num_generations=8` (`GENERATIONS`)) | one sequence per micro-batch: sequences run to 40k tokens |
| sampling | training 0.8, top_p 0.95, top_k 20; the eval 0.6 / 0.95 / 20 | pilot config 2: exploration a little under TRL's 1.0, the eval at the benchmark's sampling |
| format penalty | −0.1 (`FORMAT_PENALTY`) for a rollout whose last message ends in a whole tool call TRL could not parse | such a call ends the rollout; a call the length cap cuts off is not the model's error and is not penalised |
| rows | the OpenCode context, the `end_turn` line and "Keep every curve short: 2 to 4 [MW, price] points." | pilot config 2: long curves were where the 4B's JSON broke |
| loss | `dr_grpo`, β 0, ε_high 0.28 | as decided; ε_high as the v1 run |
| learning rate | 2e-5, constant (`LR`) | the v1 run's rate; a warmup's first step runs at 0 |
| importance sampling | `vllm_importance_sampling_mode="token_truncate"` (C_max 3) | TRL's default, sequence-level masking, masked nearly every rollout on the L40S: a day's thousands of sampled tokens sum small vLLM/trainer logprob differences past the clip |
| steps | 10 (`MAX_STEPS`); with `STOP_AT` (epoch seconds) training ends after the last step whose successor, timed by the longest step so far, could not finish by then | the pilot; a box with a fixed lifetime still runs the final eval |
| context | `vllm_max_model_length=40960` (`CONTEXT`) | Qwen3-4B's native positions; smaller on GPUs under 80 GB |
| completion | `max_completion_length=31744` (`CONTEXT` - 9,216) | the longest row prompt is 8,669 tokens |
| tool loop | `max_tool_calling_iterations=64` | see Token budget |
| vLLM | on one GPU colocated, asleep while the trainer optimises, 0.6 of the GPU awake (`VLLM_SLEEP`, `VLLM_MEM`); on more a server on the others (`run.sh`) | see GPU memory |
| memory | bf16, gradient checkpointing, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` | |
| eval | the 36 val days at step 0 and at the last step (`EVAL_STEPS`, `EVAL_LIMIT`), one sample each, 12 at a time (`EVAL_BATCH`), scored by their rewards alone | TRL's eval step would run the model over the whole eval batch at once; monitoring only, the leaderboard eval is OpenCode's |
| checkpoints | the LoRA every 5 steps (`save_steps=5`, `save_only_model=True`) and at the end in `$OUT/adapter` | |
| env client | `AgentEnv(ENV_URL, split="train", tool_timeout=300, reset_timeout=1800)`, `ENV_URL` `http://127.0.0.1:8000` | 32 concurrent deploys take minutes |

## Token budget

Counted with Qwen3-4B's chat template (thinking on) as GRPOTrainer concatenates a rollout (SCOPE's `tokens.py`; the
whole day is one completion of tool calls and tool results, and every reasoning block stays in context), over the 251
train and val days played by the anchor, and from base Qwen3-4B's own bench play (`tokens.json`):

| tokens per day | p50 | p90 | max |
|---|---|---|---|
| row prompt as `train.py` edits it (OpenCode context, 12 tools, start wake) | 6,971 | 7,855 | 8,669 |
| row prompt as the bundle serves it | 4,885 | 5,756 | 6,561 |
| anchor-played day, without reasoning | 33,346 | 65,028 | 130,713 |
| anchor-played day, with base Qwen's mean reasoning per message (485 tokens) | 48,245 | 96,207 | 188,428 |
| base Qwen's own play (its 32 bench windows / 3, with this prompt), without reasoning | 13,773 | 18,268 | 21,736 |
| base Qwen's own play, with its reasoning | 21,162 | 30,952 | 35,651 |

The prompts are rendered with agentenv-framework 0.9.1387, whose factory hands TRL each desk tool's full JSON Schema
(the nested `curves` and `as_offers` items included); that adds 302 tokens to every prompt over the 0.9.1386 prose
schemas the day counts were taken with, and the day rows include it.

The OpenCode context adds 2,047 tokens to the system message and the JSON-string wakes about 80 a day. The anchor
calls `optimize` about 10 times a day and its outputs are half the anchor's tokens; it sends 31 assistant messages at
the median (70 at p90, 119 at most), base Qwen about 22.

So a p90 day as base Qwen plays it (31.0k tokens in all) fits the 40,960-token context, and a day played like the anchor
does not: 245 of the 251 anchor days pass 40,960 once reasoning is counted. A rollout that reaches the budget ends
cleanly: TRL drops the tool result that would overflow and stops generating, and `get_reward` ends the open turns with
empty replies, so the day plays out on the offers in force and is scored. At about 1.3k tokens a message the budget
ends a long day near 25 messages, so the 64-iteration cap only stops a loop of short calls. If the pilot shows many
days cut short, the lever is YaRN (rope scaling 2 to 81,920 tokens in both the trainer and vLLM), at the cost of a
further gap to the 32,768-token eval.

## Tool schemas

agentenv-framework 0.9.1387 (#397) gives each environment instance a `SchemaTool` per desk tool: TRL takes it from the
instance, and transformers renders it as the env's JSON Schema, as OpenCode passes it. Rendered through `train.py`'s
class with Qwen3-4B's template, `submit_dam_offers` reaches the model with
`"curves": {"type": "array", "items": {"type": "object", "properties": {"hours": {"anyOf": [{"type": "string"},
{"type": "array", "items": {"type": "integer"}}]}, "points": {"type": "array", "items": {"type": "array", "items":
{"type": "number"}, "minItems": 2, "maxItems": 2}}}, "required": ["hours"]}}` (descriptions left out here), where
0.9.1386 gave a prose list of fields. `end_turn` stays a method, and `train.py`'s wrapper keeps its schema; the trainer
needed no change for it.

## Turn convention and the OpenCode context

TRL ends a rollout when the model replies without a tool call, so a turn must end with the `end_turn` tool, which
hands the reply to the env and answers with the next wake. `train.py` edits each row's prompt, leaving the bundle, the
env and the frozen desk brief as they are:

- the system message becomes the one Qwen saw in OpenCode at bench time (`opencode_context.json`, taken from base
  Qwen's first bench request): OpenCode's own prompt, the model and environment lines and the instructions-file line
  before the desk brief, the skills block after it, plus one line after the brief: "Every reply must call a tool. When
  you are done with this wake, call end_turn (with an optional short note); never end with a plain reply, or the rest
  of the day runs without you." It replaced a softer line ("In this session you end your turn by calling end_turn
  with your reply; a reply without a tool call ends the session."), under which base Qwen ended 30 of 32 rollouts of
  the GPU check with a plain reply;
- the start wake, and every later wake `end_turn` returns, reaches the model as a JSON string, as OpenCode delivered
  each wake (the row's user message reproduces base Qwen's first bench request byte for byte).

## Train and eval gap

What the leaderboard run (OpenCode, `opencode_eval.md`) shows the model and training doesn't. None of it closes without
a change outside this kit:

- **Ending a turn.** In OpenCode a turn ends with a reply that calls no tool, the next wake arrives as a new user
  message, and there is no `end_turn` tool. Training ends turns with `end_turn` and gets each wake as its tool
  result, because TRL's tool loop ends a rollout at the first reply without a tool call. A trained model that calls
  `end_turn` in OpenCode calls a tool OpenCode doesn't have and gets an error back (count those calls in the quick
  check).
  Closing it needs TRL to keep a rollout going past a reply without a tool call (an environment hook that treats it
  as `end_turn`), not a framework change.
- **Tool names.** OpenCode names the desk tools `env<4 random digits>_<tool>`: the framework's
  `random_mcp_server_name` draws a name per deploy for an env no MultiEnv names (env4523, env2039 and env9132 on the
  base Qwen boxes), so no fixed training name matches. The factory serves the env's own names (`get_prices`, ...), the
  names the desk brief uses. A stable name needs the bench bundle to declare one, and that bundle is frozen.
- **OpenCode's own tools.** Base Qwen's bench requests listed 29 tools: the 11 desk tools, 12 of OpenCode's (`bash`,
  `edit`, `glob`, `grep`, `read`, `write`, `skill`, `task`, `todowrite`, `list_mcp_resources`,
  `list_mcp_resource_templates`, `read_mcp_resource`) and 6 framework peer-agent tools (`peer_agents_peer_*`).
  Training shows the 11 and `end_turn`: the others act on the agent's sandbox and its peers, which an OpenEnv session
  doesn't have, and stubs would teach tools that do nothing. They are 6,375 of the 13,648 tokens of base Qwen's first
  bench request.
- **Reasoning and context.** Qwen3's chat template drops the reasoning of turns before the latest user message, so
  in OpenCode each wake starts without the earlier wakes' reasoning, at 32,768 tokens with OpenCode's auto-compaction.
  In TRL the day is one completion: every reasoning block stays, at 40,960 tokens, and overflow ends the rollout.
- **Sampling.** Training samples at 0.8 / 0.95 / 20; OpenCode runs Qwen at 0.6 / 0.95 / 20, as the trainer's eval
  does.

## Qwen3.5-9B on one GPU box (pilot config 2)

`Qwen/Qwen3.5-9B` at revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a` (thinking on), run by `scripts/run_9b.sh` as
root after `git clone -b desk-train-9b … /home/ubuntu/plugin`, with `MAX_HOURS` the box's lifetime: a `p5.4xlarge`
(one H100, colocated), a `p5.48xlarge` (eight H100s) or a `p4de.24xlarge` (eight A100s 80 GB), both in server mode:

- **Template and tool calls:** the model's chat template is the one TRL 1.16 ships as `qwen3_5_think.jinja`, byte for
  byte, so TRL parses its XML tool calls (`<tool_call><function=…><parameter=…>`; a nested argument such as `curves` is
  one JSON value inside its parameter) with its Qwen3.5 response schema. With thinking on, the generation prompt opens
  `<think>`.
- **What a broken call does** (TRL 1.16 and transformers 5.22, which types each argument by the tool's schema): a
  nested value that isn't valid JSON (a `curves` missing its last bracket) and a word where a number belongs still
  parse as calls, carrying the string, and the env answers with an error the model can act on; a call to a tool
  that doesn't exist parses too. A call the length cap cuts off parses with empty arguments when its `<function=…>`
  tag is complete. Only a whole call without a function tag, or in Qwen3's JSON form (`<tool_call>{"name": …}`), falls
  back to text and ends the rollout. So the 4B's dominant ending, malformed JSON that ended the day, mostly becomes
  a refused tool call for the 9B: the format penalty fires less, and the metrics count the env's refusals as
  `tool_error_share`.
- **Rows:** the OpenCode context names the served model (`SERVED_MODEL=qwen3.5-9b`: "You are powered by the model named
  qwen3.5-9b. The exact model ID is litellm/qwen3.5-9b"), and the template's own tool preamble replaces the 4B's: a row
  prompt runs 7,247 tokens at the median, 8,131 at p90 and 8,945 at most, within the 9,216 the trainer budgets.
- **Sampling:** training 0.8 / 0.95 / 20 and the eval 0.6 / 0.95 / 20, which is also Qwen's recommendation for
  thinking mode on precise tasks (its general thinking setting is 1.0 / 0.95 / 20 with presence penalty 1.5).
- **Trainer:** bf16 weights (`MODEL_DTYPE`), LoRA r 32 on every linear layer but the vision tower, flash-linear-attention
  for the linear-attention layers, and the 248k vocabulary's log-probs one sequence at a time
  (`per_device_train_batch_size=1`; the eval scores rewards alone).
- **Memory:** one training sequence on the L40S (bf16 9B, the LoRA, gradient checkpointing, the completion's
  log-probs; `memprobe9b.sh` in the ops notes) peaks at 21.8, 25.7, 29.6, 35.1 and 41.9 GiB at 4k, 8k, 12k, 16k and
  20k tokens (2.0k to 13.5k of them completion), and 24k runs out of the L40S's 44 GiB. That fits about 18.1 GiB plus
  0.14 GiB per 1k tokens plus 1.52 GiB per 1k completion tokens (the 248k-wide logits), so with an 8k prompt about
  6 GiB plus 1.66 GiB per 1k tokens of context, and the optimiser state adds about 1.5 GiB. With completions capped at
  CONTEXT − 9,216 tokens, CONTEXT 32,768 (`run_9b.sh`'s default) peaks near 60 GiB; 36,864 would reach about 67 and
  40,960 about 74, against an 80 GB GPU's 79 GiB.
- **vLLM on eight GPUs:** a `trl vllm-serve` server, data parallel over GPUs 1-7, tensor parallel 1, `max_model_len` =
  CONTEXT, with the weights TRL streams in over NCCL after merging the LoRA every step; the trainer has GPU 0 to itself.
- **vLLM on one 80 GB GPU:** colocated at 0.6 of the GPU (`VLLM_MEM`), asleep at level 2 (weights and KV cache
  released) while the trainer optimises, its weights loaded from the trainer's merged LoRA when it wakes. Awake: the
  trainer's bf16 weights, LoRA, gradients and Adam state (about 19.5 GiB) beside vLLM's 47.5 GiB (its 18.6 GiB of
  weights, CUDA graphs and TRL's 4,096-token batches, and about 26 GiB of KV cache, some 800k tokens at the 8
  full-attention layers' 32 KiB a token; the 24 linear-attention layers keep about 50 MB of state a sequence), about
  67 GiB of the 79 GiB. Asleep: the trainer's peak at CONTEXT 32,768 (a 7-9k prompt and the rest completion) is
  about 60 GiB with the optimiser state, plus a few GiB vLLM keeps (graphs, its CUDA context), so 13 GiB or more
  spare in both phases.
- **A100s:** nothing here needs Hopper. torch 2.13 (cu130) ships sm_80; vLLM 0.29's kernels carry sm_80 SASS, its
  FlashAttention 2 is built for sm_80 (FlashAttention 3, sm_90 only, is what it picks on H100s) and the L40S above ran
  that same non-Hopper path; flash-linear-attention is Triton, where Hopper only changes autotuning and TMA is opt-in
  (`FLA_USE_TMA`, sm_90 and up). bf16 runs on sm_80, and nothing in the kit uses FP8.
- **Order:** setup (the model downloads while the env image builds), a sanity eval of one val day (on eight GPUs the
  first NCCL weight transfer; the server then restarts, since vLLM doesn't guard a second trainer joining its group),
  then the pilot: the base eval of the 36 val days at step 0 (all 36 at once, `EVAL_BATCH=36`), up to 10 steps, the
  final eval. Training ends after the last step that leaves 25 min before the deadline (boot + `MAX_HOURS` − 15 min)
  for the final eval and the copies (`STOP_AT`).

### The 9B on the L40S (2026-10-30)

On the L40S box, at `e9d81b7`: `trl vllm-serve` with the 9B and `run.sh`'s server flags
(`max_model_len` 32768, prefix caching on the hybrid model) came up in 3 min 16 s and answered TRL's client with XML
calls (`<function=get_prices>`, then `<function=end_turn>`), 5 s for two 190-token completions. A one-step train smoke
in colocate mode (CONTEXT 16384, 2 rollouts, `ROLLOUTS=2 GENERATIONS=2`) took 8 min: generation, the env's rewards,
the format reward, one optimiser step (grad norm 0.14, IS ratio 0.995), the LoRA checkpoint (350 MB) and the adapter,
and a one-day eval after the weight sync (C +0.056, 2 `end_turn` calls). The base eval of the first 4 val days at
CONTEXT 28672 and 0.6 / 0.95 / 20 took 17.6 min: C mean +0.047 (sd 0.20; the 4B on the same days +0.055), R 0.60,
valid offers 4 of 4, 3 of 4 beat idle, 11.25 `end_turn` calls a rollout, 0.6% of tool calls refused by the env, no
malformed ending (one full day, two at the length cap after 30 and 54 calls, one cut off while reasoning, at 9k
characters a message). Server-mode weight transfer (NCCL, trainer on GPU 0) can't run on one GPU; `run_9b.sh`'s
sanity runs it first on the p5.

### Long-context spike: the trainer's memory and a thinking budget (L40S, 2026-10-30)

- **No Liger loss, none needed.** TRL 1.16's `GRPOTrainer` always scores the loss through its own fused LM head
  (`add_fused_lm_head`, `trl/kernels/chunked_logprob.py`: Triton tiles of 4,096 tokens by 32,768 vocabulary entries,
  fp32 accumulation, completion positions only), so the 248k-wide logits are never built. It works under PEFT and
  Qwen3.5's vision wrapper. On a 2k-token sequence its log-probs match a plain `log_softmax` of the full logits to
  3.8e-6 (max) and 2.6e-7 (mean). `use_liger_kernel` is deprecated there and its fused cross-entropy refused.
- **Memory per token** (`fused_probe.py`; one sequence, an 8k prompt, the rest completion, LoRA r 32, gradient
  checkpointing; the trainer holds 17.85 GiB loaded): 29.2 GiB at 16k and 40.6 GiB at 32k, out of memory at 48k on
  the L40S, about 0.70 GiB per 1k tokens: 0.25 for the checkpointed layer inputs and the rest for one layer's
  backward at full length. With `OFFLOAD_ACTIVATIONS=1` (what the forward saves for backward goes to pinned CPU
  memory, about 256 KiB a token) the peaks are 25.9, 33.6 and 41.3 GiB at 16k, 32k and 48k, about 0.48 GiB per 1k.
  So on an 80 GB GPU the trainer reaches about 80k tokens as TRL runs it and about 120k with the offload: 96k needs
  it (about 64 GiB, plus the optimiser state and vLLM asleep).
- **A colocated step at CONTEXT 40,960 with the offload** ran end to end (2 rollouts, loss −0.105, grad norm 0.073,
  IS ratio 0.992, 18 min), at most 39.8 GiB on the GPU while optimising. Its longer rollout stopped at the 64-iteration
  cap (81 tool results, about 27k tokens), so a full day at 96k also needs `MAX_TOOL_ITERATIONS` near 200. In colocate
  mode `torch_peak_gib` counts vLLM's sleeping pool; read it in server mode.
- **Thinking budget** (`think_budget_check.py`): vLLM 0.29's `thinking_token_budget` works on Qwen3.5 with the
  `qwen3` reasoning parser. It counts from the `<think>` the generation prompt opens and forces `</think>` at exactly N
  tokens: at 64, 256 and 1,024 every sample stopped there (one ended on its own at 945) and went on to a tool call,
  where without a budget two of four samples thought past 6,144 tokens with no call. In TRL it is
  `GRPOConfig(generation_kwargs={"thinking_token_budget": N})` with `--reasoning-parser qwen3` on the server; colocated
  vLLM also needs the parser passed to `LLM`. This path samples with FlashInfer, which compiles on first use, so set
  `VLLM_USE_FLASHINFER_SAMPLER=0` on a box without `ninja`.
- **AsyncGRPO** (TRL 1.16) refuses Qwen3.5: its tree packing routes only attention layers, and the 24 linear-attention
  layers would scan across samples.

## GPU check (L40S, 2026-10-30)

One g6e.4xlarge (1× L40S, 16 vCPU), set up with `setup-box.sh` in 288 s (driver 595, agentenv-framework 0.9.1387,
TRL 1.16.0, vLLM 0.29.0, transformers 5.22.0, torch 2.13.0+cu130), the env server under systemd; one GRPO step on 4
train days × 8 rollouts and 4 val days, at `CONTEXT=28672` (`gpu_check_l40s.json`):

- **The loop works end to end**: the desk tools render with their nested schemas, rollouts call them and `end_turn`
  advances the wakes, all 32 rollouts are scored (none unscored), `get_reward` returns C, a rollout that reached the
  budget ended cleanly and was scored, `checkpoint-1` and the adapter save, `metrics.jsonl` and the completions fill.
- **Time**: 44 minutes for the step (TRL's `step_time` 2,632 s): generation 20 minutes with all 32 rollouts in
  flight, collecting the 32 rewards 2.5, optimisation 23. Four val days take 4 minutes. GPU memory 43 GB while
  generating. Projections, at the base model's rollout lengths (they grow as the model learns to play the whole day):
  about 8 hours for the 10-step pilot with its two 36-day evals on this L40S; on an H100 about 12 minutes a step
  (memory bandwidth 3.9×, compute 5×, the same env side), about 2 hours for the pilot.
- **Fixed on the way**, now in the kit: the eval step's out-of-memory (TRL ran the model over the whole eval batch at
  once); Docker running out of address pools for 32 concurrent episodes (rollouts left unscored); the backward pass at
  40,960 tokens on 48 GB (`CONTEXT`); TRL's default sequence-level masked importance sampling, which masked nearly
  every rollout (ratio mean 0.03; token-level truncation gives 0.9996 and a grad norm of 0.026 against 0.0014); and
  the LR warmup that ran the first step at learning rate 0.
- **What base Qwen does in the loop** (the same 4 days, two runs): 41-47% of rollouts place an accepted offer, C is
  0 on 53-59%, below 0 on 25-34%, above 0 on 6-22%; mean C -0.049 and -0.050, standard deviation 0.16-0.18; every
  group's rewards spread (standard deviation 0.03-0.28 within a day), so GRPO has signal. Every tool call parsed and
  reached the env (TRL's tool failure rate 0): the nested `curves` arrive as well-formed arrays, and rejections are the
  desk's own (more than 10 points, a closed DAM, the D-1 day, the 14-call turn budget). But the model rarely plays
  the whole day: 1.3-2.7 `end_turn` calls a rollout and 2 of 32 finish the day; most end the rollout with a reply
  that calls no tool, as OpenCode's convention and the brief teach, and the day then runs on the offers in force.
  Completions average 4.5-5.2k tokens (11.6k at most); one rollout of 32 reached the budget.

## CPU verification

On the Mac with Docker, the bundle as `desk_train.py` writes it (its env image built from the freeze and both pack
commits), `replay.py` (`replay.json`), with agentenv-framework 0.9.1386 and again on 0.9.1387 (four of the train days:
the same outputs and rewards, the desk tools now `SchemaTool`s):

- **Eight train days with the anchor**, four at once, each environment reset again for a second day as TRL reuses
  its pool: 12-29 S01, 01-05 S02, 01-18 S03, 05-17 S03, 05-27 S02 (outage), 06-16 S04 (outage; 25 wakes, 74 calls),
  06-24 S01, 06-30 S04. The factory's methods are the 11 desk tools and `end_turn`; every tool output and every wake
  `end_turn` returned matched the in-process Session byte for byte (0 problems); `get_reward` equalled the core's C
  floored at -1 on every day (-0.040 to 0.191). Server start 1.4 s, factory 22 s (one probe episode), a day 27-35 s
  of wall time, about 23 s of it the deploy.
- **Two val days with the anchor** (01-15 S01, an outage day, and 06-08 S02): 0 problems, rewards 0.161 and 0.159.
- **Two train days with the idle policy**: reward 0.0 (R 0.2), as C defines idle.
- **`train.py` without a GPU**: with stand-ins for TRL, PEFT and transformers against `serve.py` on a small bundle,
  the class's tools as TRL collects them are the 11 desk tools and `end_turn` (the wrapped `end_turn` keeps its schema
  under `get_json_schema`), the rows carry the OpenCode context and the JSON-string wake, `end_turn` returns wakes as
  JSON strings, the episode ends and scores, and `metrics.jsonl` gets its line. The edited row reproduces base Qwen's
  first bench request (system and user message) byte for byte, apart from the added `end_turn` line.

## Files

- `scripts/setup-box.sh`, `scripts/desk-env.service`: one box's setup and its env server unit.
- `scripts/setup-env.sh`, `scripts/serve.py`: the env server's install and server.
- `scripts/setup.sh`, `scripts/run.sh`, `scripts/train.py`: the trainer's install, the launcher that picks vLLM's mode,
  and GRPO with the val evals (`MAX_STEPS=0`: an eval only). It writes `$OUT/metrics.jsonl` (per log line: the rollouts' C mean, median and spread, R mean, the shares
  beating idle, beating the anchor, at the -1 floor, with an accepted offer and finished by the model's own end_turn
  calls, end_turn calls a rollout, and TRL's own metrics), `$OUT/rollouts.jsonl` (task, C, R per
  rollout, with its tool calls), `$OUT/log_history.json`, `$OUT/checkpoint-5`, `$OUT/checkpoint-10` and `$OUT/adapter`.
- `scripts/replay.py`: the CPU check.
- `opencode_context.json`: OpenCode's system context around the desk brief.
- `anchor_c.json`: the anchor's C per task (train, val and bench), for the beats-anchor share.
- `opencode_eval.md`: the leaderboard eval of a LoRA in OpenCode.
- `replay.json`, `tokens.json`, `gpu_check_l40s.json`: the CPU check's, the token count's and the L40S check's outputs.
