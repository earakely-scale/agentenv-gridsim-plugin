"""GRPO of Qwen3-4B (thinking on, LoRA) on GridSim desk operating days through AgentEnv's TRL integration: the
desk-v4-train bundle served by serve.py (reward: hindsight capture C floored at -1), read here with AgentEnv(ENV_URL),
every rollout one operating day the env deploys, plays and grades. TRL evaluates the val days (the first EVAL_LIMIT) at
the start and every EVAL_STEPS; MAX_STEPS=0 only evaluates EVAL_SPLIT (val, or bench for the 32 three-day windows).
VLLM_MODE=colocate runs vLLM beside the trainer on its GPU; server reads a `trl vllm-serve` on VLLM_PORT (run.sh picks
the mode from the GPU count and starts the server).

The rows get the system context Qwen sees in OpenCode at bench time (opencode_context.json: OpenCode's prompt before the
desk brief, its skills block after it) and one line on ending a turn with end_turn, since TRL ends a rollout at a reply
without a tool call; each wake reaches the model as a JSON string, as OpenCode delivers it. A callback writes each log
line to $OUT/metrics.jsonl with the rollouts' C (the reward), R and the share beating idle and the anchor since the line
before, and the latest generation batch's completions to $OUT/completions-<phase>-<step>.jsonl; $OUT/rollouts.jsonl
gets each rollout's tool calls as it is logged.

Long days (pilot config 2 at 96k): THINK_BUDGET caps each turn's thinking (vLLM's thinking_token_budget, the qwen3
reasoning parser), MAX_TOOL_ITERATIONS bounds the turns, OFFLOAD_ACTIVATIONS keeps the saved activations in CPU memory,
and in colocate mode vLLM stays awake through a batch's whole tool loop (VLLM_HOLD_AWAKE), keeping its prefix cache,
and sleeps once before the trainer's passes. SAVE_STEPS checkpoints (weights, optimizer, step) and KEEP_CHECKPOINTS
names the steps kept besides the latest; a run whose OUT holds a checkpoint resumes from the last one. CPU_CHECK=1 runs
the same loop without vLLM or a GPU, for checks with a tiny model."""

import contextlib
import functools
import json
import logging
import os
import shutil
import statistics
import sys
import time
from pathlib import Path

import torch
from agent_env.training.trl import ENDED, FAILED, AgentEnv
from peft import LoraConfig
from transformers import TrainerCallback
from transformers.trainer_utils import get_last_checkpoint
from trl import GRPOConfig, GRPOTrainer
from trl.generation import vllm_generation

KIT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("OUT", "out"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "10"))
CONTEXT = json.loads((KIT / "opencode_context.json").read_text())
ANCHOR_C = json.loads((KIT / "anchor_c.json").read_text())
END_TURN = ("Every reply must call a tool. When you are done with this wake, call end_turn (with an optional short "
            "note); never end with a plain reply, or the rest of the day runs without you.")
SHORT_CURVES = "Keep every curve short: 2 to 4 [MW, price] points."
TRAIN_SAMPLING = {"temperature": 0.8, "top_p": 0.95, "top_k": 20}
EVAL_SAMPLING = {"temperature": 0.6, "top_p": 0.95, "top_k": 20}
FORMAT_PENALTY = float(os.environ.get("FORMAT_PENALTY", "0.1"))
SERVED_MODEL = os.environ.get("SERVED_MODEL", "qwen3-4b")
HEAD = CONTEXT["head"].replace("qwen3-4b", SERVED_MODEL)
CONTEXT_TOKENS = int(os.environ.get("CONTEXT", "40960"))
MAX_PROMPT_TOKENS = 9216
MAX_TOOL_ITERATIONS = int(os.environ.get("MAX_TOOL_ITERATIONS", "64"))
THINK_BUDGET = int(os.environ.get("THINK_BUDGET", "0"))
CPU_CHECK = os.environ.get("CPU_CHECK") == "1"
VLLM_MODE = os.environ.get("VLLM_MODE", "colocate")
KEEP_CHECKPOINTS = {int(step) for step in os.environ.get("KEEP_CHECKPOINTS", "").split(",") if step}
RESUME = get_last_checkpoint(str(OUT)) if OUT.is_dir() else None
STARTED = time.monotonic()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
for noisy in ("httpx", "httpcore", "agent_env", "agentenv_protocol", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("agent_env.training.trl").setLevel(logging.INFO)
log = logging.getLogger("desk_grpo")
if THINK_BUDGET and VLLM_MODE == "colocate" and not CPU_CHECK:
    vllm_generation.LLM = functools.partial(vllm_generation.LLM, reasoning_parser="qwen3")


def opencode(row: dict) -> dict:
    system, wake = row["prompt"]
    return {"prompt": [{"role": "system", "content": HEAD + system["content"] + "\n" + END_TURN + "\n"
                        + SHORT_CURVES + CONTEXT["tail"]},
                       {"role": "user", "content": json.dumps(wake["content"], ensure_ascii=False)}]}


env = AgentEnv(os.environ.get("ENV_URL", "http://127.0.0.1:8000"), split="train", tool_timeout=300,
               reset_timeout=1800)
EVAL_SPLIT = os.environ.get("EVAL_SPLIT", "val")
eval_split = env.dataset_for(EVAL_SPLIT)
EVAL_LIMIT = int(os.environ.get("EVAL_LIMIT", str(len(eval_split))))
train_rows, eval_rows = env.dataset.map(opencode), eval_split.select(range(EVAL_LIMIT)).map(opencode)
log.info("%d train rows, %d %s rows at %s in %ss", len(train_rows), len(eval_rows), EVAL_SPLIT, env.url,
         round(time.monotonic() - STARTED))

ROLLOUTS: list[dict] = []
Base = env.factory


@functools.wraps(Base.end_turn)
def end_turn(self, *args, **kwargs) -> str:
    answer = Base.end_turn(self, *args, **kwargs)
    return answer if answer in (ENDED, FAILED) or not answer.startswith("{") else json.dumps(answer, ensure_ascii=False)


def reset(self, **row) -> None:
    self.task_id, self.calls = row["task_id"].rsplit("/", 1)[-1], []
    Base.reset(self, **row)


def _call(self, name, arguments):
    answer = Base._call(self, name, arguments)
    self.calls.append({"tool": name, "args": arguments, "answer": answer[:400]})
    return answer


def _answer(self, rollout, name, result):
    if result.done:
        rollout.scores = (result.observation.get("metadata") or {}).get("scores")
    return Base._answer(self, rollout, name, result)


def get_reward(self) -> float | None:
    rollout = self._rollout
    finished = rollout is not None and rollout.done
    reward = Base.get_reward(self)
    scores = getattr(rollout, "scores", None) or {}
    ROLLOUTS.append({"task_id": self.task_id, "reward": reward, "r": scores.get("grade"), "finished_by_model": finished,
                     "calls": self.calls})
    return reward


def malformed_call(completions, **kwargs) -> list[float]:
    """-FORMAT_PENALTY for a rollout whose last message ends in a whole tool call TRL could not parse, which ended it;
    a call the length cap cut off is not the model's error."""
    return [-FORMAT_PENALTY if not messages[-1].get("tool_calls")
            and str(messages[-1].get("content")).rstrip().endswith("</tool_call>") else 0.0 for messages in completions]


Desk = type(Base.__name__, (Base,), {"end_turn": end_turn, "reset": reset, "_call": _call, "_answer": _answer,
                                     "get_reward": get_reward})


def rates(rollouts: list[dict]) -> dict:
    scored = [r for r in rollouts if r["reward"] is not None]
    if not scored:
        return {"rollouts": len(rollouts), "unscored": len(rollouts)}
    c = [r["reward"] for r in scored]
    anchor = [ANCHOR_C[r["task_id"]] for r in scored]
    return {"rollouts": len(rollouts), "unscored": len(rollouts) - len(scored), "c_mean": round(statistics.fmean(c), 4),
            "c_median": round(statistics.median(c), 4), "r_mean": round(statistics.fmean(r["r"] for r in scored), 4),
            "beats_idle_rate": round(sum(x > 0 for x in c) / len(c), 4),
            "at_floor_rate": round(sum(x <= -1 for x in c) / len(c), 4),
            "beats_anchor_rate": round(sum(x > a for x, a in zip(c, anchor, strict=True)) / len(c), 4),
            "anchor_c_mean": round(statistics.fmean(anchor), 4), "c_sd": round(statistics.pstdev(c), 4),
            "finished_by_model_rate": round(sum(r["finished_by_model"] for r in scored) / len(scored), 4),
            "end_turns_per_rollout": round(sum(c["tool"] == "end_turn" for r in scored for c in r["calls"])
                                           / len(scored), 2),
            "valid_offer_rate": round(sum(any(c["tool"].startswith("submit") and '"accepted_hours":"HE' in c["answer"]
                                              for c in r["calls"]) for r in scored) / len(scored), 4),
            "tool_error_share": round(sum('"error":' in c["answer"] for r in scored for c in r["calls"])
                                      / max(1, sum(len(r["calls"]) for r in scored)), 4)}



def thinking(completions: list, processing_class) -> dict:
    """Thinking tokens per assistant turn in the latest logged completions, and with THINK_BUDGET the share of turns
    the budget cut (vLLM forces `</think>` at the budget, so a cut turn thinks for the budget less a token or two)."""
    tokenizer = getattr(processing_class, "tokenizer", processing_class)
    counts = [len(tokenizer(str(m.get("reasoning_content") or ""), add_special_tokens=False)["input_ids"])
              for messages in completions for m in messages if m.get("role") == "assistant"]
    if not counts:
        return {}
    return {"think_tokens_per_turn": round(statistics.fmean(counts), 1), "turns_logged": len(counts),
            **({"think_cut_share": round(sum(c >= THINK_BUDGET - 4 for c in counts) / len(counts), 4)}
               if THINK_BUDGET else {})}

class Deadline(TrainerCallback):
    """Ends training after the last step whose successor could not finish before STOP_AT (epoch seconds; the longest
    step so far times the next), so a box with a fixed lifetime still runs the final eval, off its schedule if need
    be, and keeps its outputs."""

    def __init__(self):
        self.began, self.longest = 0.0, 0.0

    def on_step_begin(self, args, state, control, **kwargs):
        self.began = time.time()

    def on_step_end(self, args, state, control, **kwargs):
        self.longest = max(self.longest, time.time() - self.began)
        if time.time() + self.longest > float(os.environ.get("STOP_AT", "inf")):
            control.should_training_stop = True



class Prune(TrainerCallback):
    """Keeps the latest checkpoint and those of the steps in KEEP_CHECKPOINTS."""

    def on_save(self, args, state, control, **kwargs):
        for path in OUT.glob("checkpoint-*"):
            step = int(path.name.rsplit("-", 1)[1])
            if step != state.global_step and step not in KEEP_CHECKPOINTS:
                shutil.rmtree(path)

class Metrics(TrainerCallback):
    def __init__(self):
        self.seen, self.trainer = 0, None
        OUT.mkdir(parents=True, exist_ok=True)
        self.file = (OUT / "metrics.jsonl").open("a")

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        phase = "eval" if any(key.startswith("eval_") for key in logs) else "train"
        new, self.seen = ROLLOUTS[self.seen:], len(ROLLOUTS)
        recent = self.trainer._logs
        row = {"phase": phase, "step": state.global_step, "elapsed_s": round(time.monotonic() - STARTED), **rates(new),
               **(thinking(recent["completion"], self.trainer.processing_class) if new else {}),
               "torch_peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2) if not CPU_CHECK else 0,
               **{key: value for key, value in logs.items() if isinstance(value, (int, float))}}
        self.file.write(json.dumps(row) + "\n")
        self.file.flush()
        with (OUT / "rollouts.jsonl").open("a") as f:
            f.writelines(json.dumps(r | {"phase": phase, "step": state.global_step}) + "\n" for r in new)
        if new:
            rewards = next(iter(recent["rewards"].values()), [])
            (OUT / f"completions-{phase}-{state.global_step}.jsonl").write_text("".join(
                json.dumps({"completion": c, "reward": r, "advantage": a}, default=str) + "\n"
                for c, r, a in zip(recent["completion"], rewards, recent["advantages"], strict=False)))
        log.info("%s step %s: %s", phase, state.global_step,
                 json.dumps({key: row.get(key) for key in ("rollouts", "unscored", "c_mean", "c_sd", "r_mean",
                                                           "beats_idle_rate", "valid_offer_rate", "tool_error_share",
                                                           "end_turns_per_rollout", "finished_by_model_rate",
                                                           "elapsed_s")}))


class DeskGRPOTrainer(GRPOTrainer):
    """Evaluates by the episodes' rewards alone, sampling at EVAL_SAMPLING (the benchmark's): TRL's eval step would also
    run the model over the whole eval batch at once (the loss, and the old log-probs of vLLM's importance-sampling
    correction), which runs out of memory at 40k-token sequences."""

    def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=None):
        corrected, self.vllm_importance_sampling_correction = self.vllm_importance_sampling_correction, False
        sampling = {key: getattr(self.vllm_generation, key) for key in EVAL_SAMPLING}
        self.vllm_generation.__dict__.update(EVAL_SAMPLING)
        try:
            self._prepare_inputs(inputs)
        finally:
            self.vllm_importance_sampling_correction = corrected
            self.vllm_generation.__dict__.update(sampling)
        return torch.zeros((), device=self.accelerator.device), None, None

    def _generate(self, prompts):
        """With colocated vLLM asleep between generations, TRL wakes it, pushes the weights and drops the KV cache at
        every turn of the tool loop, so each turn prefills every day from its start. VLLM_HOLD_AWAKE (the default)
        keeps it awake, its weights pushed once and its prefix cache, through a batch's whole loop, then puts it to
        sleep before the trainer's passes."""
        generation = self.vllm_generation
        if not (self.use_vllm and generation.mode == "colocate" and generation.enable_sleep_mode
                and os.environ.get("VLLM_HOLD_AWAKE", "1") == "1"):
            return super()._generate(prompts)
        llm, awake, synced = generation.llm, set(), []
        sleep, wake_up, sync_weights = llm.sleep, llm.wake_up, generation.sync_weights

        def wake_once(tags=None):
            fresh = [tag for tag in tags or ("weights", "kv_cache") if tag not in awake]
            if fresh:
                wake_up(tags=fresh)
                awake.update(fresh)

        def sync_once():
            if not synced:
                sync_weights()
                synced.append(True)

        llm.sleep, llm.wake_up, generation.sync_weights = (lambda level=1: None), wake_once, sync_once
        try:
            return super()._generate(prompts)
        finally:
            llm.sleep, llm.wake_up = sleep, wake_up
            del generation.sync_weights
            sleep(level=2)
            generation._llm_weights_sleeping = True

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        """OFFLOAD_ACTIVATIONS=1 keeps what the forward saves for backward (the checkpointed layer inputs, about 256 KiB
        a token) in pinned CPU memory."""
        offload = os.environ.get("OFFLOAD_ACTIVATIONS") == "1"
        with torch.autograd.graph.save_on_cpu(pin_memory=True) if offload else contextlib.nullcontext():
            return super().compute_loss(model, inputs, return_outputs=return_outputs,
                                        num_items_in_batch=num_items_in_batch)


trainer = DeskGRPOTrainer(
    model=os.environ.get("MODEL", "models/Qwen3-4B"),
    reward_funcs=[malformed_call] if FORMAT_PENALTY else None,
    args=GRPOConfig(
        output_dir=str(OUT),
        max_steps=max(1, MAX_STEPS),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=int(os.environ.get("ROLLOUTS", "32")),
        num_generations=int(os.environ.get("GENERATIONS", "8")),
        max_completion_length=CONTEXT_TOKENS - MAX_PROMPT_TOKENS,
        max_tool_calling_iterations=MAX_TOOL_ITERATIONS,
        chat_template_kwargs={"enable_thinking": True},
        **TRAIN_SAMPLING,
        generation_kwargs={"thinking_token_budget": THINK_BUDGET} if THINK_BUDGET and not CPU_CHECK else None,
        learning_rate=float(os.environ.get("LR", "2e-5")),
        lr_scheduler_type="constant",
        loss_type="dr_grpo",
        beta=0.0,
        epsilon_high=0.28,
        vllm_importance_sampling_mode="token_truncate",
        use_vllm=not CPU_CHECK,
        vllm_mode=VLLM_MODE,
        vllm_server_host="127.0.0.1",
        vllm_server_port=int(os.environ.get("VLLM_PORT", "8001")),
        vllm_gpu_memory_utilization=float(os.environ.get("VLLM_MEM", "0.6")),
        vllm_max_model_length=2 * CONTEXT_TOKENS - MAX_PROMPT_TOKENS,
        vllm_enable_sleep_mode=os.environ.get("VLLM_SLEEP", "1") == "1",
        bf16=not CPU_CHECK,
        use_cpu=CPU_CHECK,
        model_init_kwargs={"dtype": os.environ.get("MODEL_DTYPE", "float32")},
        gradient_checkpointing=True,
        eval_strategy="steps" if EVAL_LIMIT else "no",
        eval_steps=int(os.environ.get("EVAL_STEPS", str(max(1, MAX_STEPS)))),
        eval_on_start=os.environ.get("EVAL_ON_START", "1") == "1" and EVAL_LIMIT > 0 and RESUME is None,
        num_generations_eval=1,
        per_device_eval_batch_size=int(os.environ.get("EVAL_BATCH", "12")),
        logging_steps=1,
        save_strategy="steps",
        save_steps=int(os.environ.get("SAVE_STEPS", "5")),
        save_only_model=False,
        report_to="none",
        seed=0,
    ),
    train_dataset=train_rows,
    eval_dataset=eval_rows if EVAL_LIMIT else None,
    environment_factory=Desk,
    peft_config=LoraConfig(r=32, lora_alpha=64, target_modules="all-linear", exclude_modules=r".*visual.*",
                           task_type="CAUSAL_LM"),
    callbacks=[metrics := Metrics(), Deadline()] + ([Prune()] if KEEP_CHECKPOINTS else []),
)
metrics.trainer = trainer
if MAX_STEPS == 0:
    trainer.evaluate()
else:
    if RESUME:
        log.info("resuming from %s", RESUME)
    trainer.train(resume_from_checkpoint=RESUME)
    if EVAL_LIMIT and trainer.state.global_step % trainer.args.eval_steps:
        trainer.evaluate()
    trainer.save_model(str(OUT / "adapter"))
(OUT / "log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))
log.info("done in %ss: %s", round(time.monotonic() - STARTED), json.dumps(rates(ROLLOUTS)))
env.close()
