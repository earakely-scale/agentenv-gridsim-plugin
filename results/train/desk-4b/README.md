# Qwen3-4B on GridSim desk operating days through AgentEnv: the GRPO pilot kit (one H100)

The kit for fine-tuning Qwen3-4B (revision `1cfa9a72`, thinking on, LoRA) with TRL's `GRPOTrainer` on the GridSim
desk, every rollout an AgentEnv episode: the `desk-v4-train` bundle is served on a CPU box by
`agent_env.openenv.build_app` (`scripts/serve.py`), and the trainer on one H100 reads it with
`agent_env.training.trl.AgentEnv("http://ENV_HOST:8000")`. A rollout is one operating day under the v4 layer and env,
with the benchmark's eleven desk tools, and its reward is the hindsight capture C floored at -1. The first run is a
10-step pilot. Nothing here has run on a GPU yet; the CPU checks below have.

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

The env box (CPU, Docker; 16 vCPU and 64 GB hold 32 concurrent episodes at about 260 MB each), from its home:

```bash
git clone https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
bash plugin/results/train/desk-4b/scripts/setup-env.sh      # FRAMEWORK and PLUGIN_REF override the pins
AGENT_ENV_CONFIG=$HOME/envbox.toml XDG_STATE_HOME=$HOME/state BUNDLE=bundles/desk-v4-train MAX_CONCURRENT_ENVS=48 \
  envbox/bin/python plugin/results/train/desk-4b/scripts/serve.py      # :8000, reachable from the trainer only
```

The trainer box (one H100, `p5.4xlarge`), from its home:

```bash
git clone https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
bash plugin/results/train/desk-4b/scripts/setup.sh
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# the pilot: evals the 36 val days at step 0 and step 10, LoRA checkpoints at steps 5 and 10
ENV_URL=http://ENV_HOST:8000 MODEL=models/Qwen3-4B OUT=out-pilot MAX_STEPS=10 \
  trainer/bin/python plugin/results/train/desk-4b/scripts/train.py > pilot.log 2>&1
# an eval only (one sample per val day); EVAL_SPLIT=bench plays the 32 three-day windows, which overflow the context
ENV_URL=http://ENV_HOST:8000 OUT=out-base MAX_STEPS=0 trainer/bin/python plugin/results/train/desk-4b/scripts/train.py
```

The leaderboard score of a trained LoRA comes from OpenCode on the 32 bench windows, as base Qwen's did:
[`opencode_eval.md`](opencode_eval.md), with a two-window check for a pilot checkpoint.

The CPU check (no model, any machine with Docker; `AGENT_ENV_CONFIG` and `XDG_STATE_HOME` as on the env box):

```bash
python results/train/desk-4b/scripts/replay.py --bundle bundles/desk-v4-train \
  --pack-dir data/desk/desk-v4-train --split train --limit 8 --parallel 4 --out replay.json
```

## The trainer's settings (`scripts/train.py`)

| setting | value | why |
|---|---|---|
| model | Qwen3-4B at `1cfa9a72`, LoRA r 32, α 64, all linear | the benchmark's revision; the v1 run's adapter |
| thinking | `chat_template_kwargs={"enable_thinking": True}` | as the benchmark's Qwen |
| rollouts | 32 a step: 4 days × 8 generations (`per_device_train_batch_size=1`, `gradient_accumulation_steps=32`, `num_generations=8`) | one sequence per micro-batch: sequences run to 40k tokens |
| sampling | temperature 1.0 | GRPO exploration |
| loss | `dr_grpo`, β 0, ε_high 0.28 | as decided; ε_high as the v1 run |
| learning rate | 2e-5, constant after 2 warmup steps (`LR`) | the v1 run's rate, flat for a 10-step pilot |
| steps | 10 (`MAX_STEPS`) | the pilot |
| context | `vllm_max_model_length=40960` | Qwen3-4B's native positions |
| completion | `max_completion_length=32256` (40,960 - 8,704) | the longest row prompt is 8,367 tokens |
| tool loop | `max_tool_calling_iterations=64` | see Token budget |
| vLLM | colocated, `vllm_gpu_memory_utilization=0.35` (`VLLM_MEM`) | leaves room for the backward pass at 40k tokens; raise it if memory allows |
| memory | bf16, gradient checkpointing, `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` | |
| eval | the 36 val days at step 0 and at the last step (`EVAL_STEPS`), one sample each, 12 at a time (`EVAL_BATCH`) | monitoring; the leaderboard eval is OpenCode's |
| checkpoints | the LoRA every 5 steps (`save_steps=5`, `save_only_model=True`) and at the end in `$OUT/adapter` | |
| env client | `AgentEnv(ENV_URL, split="train", tool_timeout=300, reset_timeout=1800)` | 32 concurrent deploys on the env box take minutes |

## Token budget

Counted with Qwen3-4B's chat template (thinking on) as GRPOTrainer concatenates a rollout (SCOPE's `tokens.py`; the
whole day is one completion of tool calls and tool results, and every reasoning block stays in context), over the 251
train and val days played by the anchor, and from base Qwen3-4B's own bench play (`tokens.json`):

| tokens per day | p50 | p90 | max |
|---|---|---|---|
| row prompt as `train.py` edits it (OpenCode context, 12 tools, start wake) | 6,669 | 7,553 | 8,367 |
| row prompt as the bundle serves it | 4,583 | 5,454 | 6,259 |
| anchor-played day, without reasoning | 33,044 | 64,726 | 130,411 |
| anchor-played day, with base Qwen's mean reasoning per message (485 tokens) | 47,943 | 95,905 | 188,126 |
| base Qwen's own play (its 32 bench windows / 3, with this prompt), without reasoning | 13,471 | 17,966 | 21,434 |
| base Qwen's own play, with its reasoning | 20,860 | 30,650 | 35,349 |

The OpenCode context adds 2,047 tokens to the system message and the JSON-string wakes about 80 a day. The anchor
calls `optimize` about 10 times a day and its outputs are half the anchor's tokens; it sends 31 assistant messages at
the median (70 at p90, 119 at most), base Qwen about 22.

So a p90 day as base Qwen plays it (30.7k tokens in all) fits the 40,960-token context, and a day played like the anchor
does not: 245 of the 251 anchor days pass 40,960 once reasoning is counted. A rollout that reaches the budget ends
cleanly: TRL drops the tool result that would overflow and stops generating, and `get_reward` ends the open turns with
empty replies, so the day plays out on the offers in force and is scored. At about 1.3k tokens a message the budget
ends a long day near 25 messages, so the 64-iteration cap only stops a loop of short calls. If the pilot shows many
days cut short, the lever is YaRN (rope scaling 2 to 81,920 tokens in both the trainer and vLLM), at the cost of a
further gap to the 32,768-token eval.

## Turn convention and the OpenCode context

TRL ends a rollout when the model replies without a tool call, so a turn must end with the `end_turn` tool, which
hands the reply to the env and answers with the next wake. `train.py` edits each row's prompt, leaving the bundle, the
env and the frozen desk brief as they are:

- the system message becomes the one Qwen saw in OpenCode at bench time (`opencode_context.json`, taken from base
  Qwen's first bench request): OpenCode's own prompt, the model and environment lines and the instructions-file line
  before the desk brief, the skills block after it, plus one line after the brief: "In this session you end your turn
  by calling end_turn with your reply; a reply without a tool call ends the session.";
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
- **Tool schemas.** The factory's methods describe nested arguments (the offer curves, AS offers) in prose, through
  transformers' `get_json_schema`; OpenCode passes the full JSON Schema (3,586 tokens for the 11 desk tools). The
  framework change that passes the full schema into the factory is in progress elsewhere; set `FRAMEWORK` to the
  release that has it on both boxes.
- **Reasoning and context.** Qwen3's chat template drops the reasoning of turns before the latest user message, so
  in OpenCode each wake starts without the earlier wakes' reasoning, at 32,768 tokens with OpenCode's auto-compaction.
  In TRL the day is one completion: every reasoning block stays, at 40,960 tokens, and overflow ends the rollout.
- **Sampling.** Training samples at temperature 1.0; OpenCode runs Qwen at 0.6, top_p 0.95, top_k 20.

## CPU verification

On the Mac with Docker, agentenv-framework 0.9.1386, the bundle as `desk_train.py` writes it (its env image built
from the freeze and both pack commits), `replay.py` (`replay.json`):

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

- `scripts/setup-env.sh`, `scripts/serve.py`: the env box's install and server.
- `scripts/setup.sh`, `scripts/train.py`: the trainer box's install, and GRPO with the val evals (`MAX_STEPS=0`: an
  eval only). It writes `$OUT/metrics.jsonl` (per log line: the rollouts' C mean and median, R mean, the shares
  beating idle, beating the anchor and at the -1 floor, and TRL's own metrics), `$OUT/rollouts.jsonl` (task, C, R per
  rollout), `$OUT/log_history.json`, `$OUT/checkpoint-5`, `$OUT/checkpoint-10` and `$OUT/adapter`.
- `scripts/replay.py`: the CPU check.
- `opencode_context.json`: OpenCode's system context around the desk brief.
- `anchor_c.json`: the anchor's C per task (train, val and bench), for the beats-anchor share.
- `opencode_eval.md`: the leaderboard eval of a LoRA in OpenCode.
- `replay.json`, `tokens.json`: the CPU check's and the token count's outputs.
