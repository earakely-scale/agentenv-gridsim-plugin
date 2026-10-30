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
gets each rollout's tool calls as it is logged."""

import functools
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

import torch
from agent_env.training.trl import ENDED, FAILED, AgentEnv
from peft import LoraConfig
from transformers import TrainerCallback
from trl import GRPOConfig, GRPOTrainer

KIT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("OUT", "out"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "10"))
CONTEXT = json.loads((KIT / "opencode_context.json").read_text())
ANCHOR_C = json.loads((KIT / "anchor_c.json").read_text())
END_TURN = ("Every reply must call a tool. When you are done with this wake, call end_turn (with an optional short "
            "note); never end with a plain reply, or the rest of the day runs without you.")
CONTEXT_TOKENS = int(os.environ.get("CONTEXT", "40960"))
MAX_PROMPT_TOKENS = 9216
MAX_TOOL_ITERATIONS = 64
STARTED = time.monotonic()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
for noisy in ("httpx", "httpcore", "agent_env", "agentenv_protocol", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("agent_env.training.trl").setLevel(logging.INFO)
log = logging.getLogger("desk_grpo")


def opencode(row: dict) -> dict:
    system, wake = row["prompt"]
    return {"prompt": [{"role": "system", "content": CONTEXT["head"] + system["content"] + "\n" + END_TURN
                        + CONTEXT["tail"]},
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
                                              for c in r["calls"]) for r in scored) / len(scored), 4)}


class Metrics(TrainerCallback):
    def __init__(self):
        self.seen, self.trainer = 0, None
        OUT.mkdir(parents=True, exist_ok=True)
        self.file = (OUT / "metrics.jsonl").open("a")

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        phase = "eval" if any(key.startswith("eval_") for key in logs) else "train"
        new, self.seen = ROLLOUTS[self.seen:], len(ROLLOUTS)
        row = {"phase": phase, "step": state.global_step, "elapsed_s": round(time.monotonic() - STARTED), **rates(new),
               **{key: value for key, value in logs.items() if isinstance(value, (int, float))}}
        self.file.write(json.dumps(row) + "\n")
        self.file.flush()
        with (OUT / "rollouts.jsonl").open("a") as f:
            f.writelines(json.dumps(r | {"phase": phase, "step": state.global_step}) + "\n" for r in new)
        recent = self.trainer._logs
        rewards = next(iter(recent["rewards"].values()), [])
        (OUT / f"completions-{phase}-{state.global_step}.jsonl").write_text("".join(
            json.dumps({"completion": c, "reward": r, "advantage": a}, default=str) + "\n"
            for c, r, a in zip(recent["completion"], rewards, recent["advantages"], strict=False)))
        log.info("%s step %s: %s", phase, state.global_step,
                 json.dumps({key: row.get(key) for key in ("rollouts", "unscored", "c_mean", "c_sd", "r_mean",
                                                           "beats_idle_rate", "valid_offer_rate",
                                                           "end_turns_per_rollout", "finished_by_model_rate",
                                                           "elapsed_s")}))


class DeskGRPOTrainer(GRPOTrainer):
    """Evaluates by the episodes' rewards alone: TRL's eval step would also run the model over the whole eval batch at
    once (the loss, and the old log-probs of vLLM's importance-sampling correction), which runs out of memory at
    40k-token sequences."""

    def prediction_step(self, model, inputs, prediction_loss_only, ignore_keys=None):
        corrected, self.vllm_importance_sampling_correction = self.vllm_importance_sampling_correction, False
        try:
            self._prepare_inputs(inputs)
        finally:
            self.vllm_importance_sampling_correction = corrected
        return torch.zeros((), device=self.accelerator.device), None, None


trainer = DeskGRPOTrainer(
    model=os.environ.get("MODEL", "models/Qwen3-4B"),
    args=GRPOConfig(
        output_dir=str(OUT),
        max_steps=max(1, MAX_STEPS),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=32,
        num_generations=8,
        max_completion_length=CONTEXT_TOKENS - MAX_PROMPT_TOKENS,
        max_tool_calling_iterations=MAX_TOOL_ITERATIONS,
        chat_template_kwargs={"enable_thinking": True},
        temperature=1.0,
        learning_rate=float(os.environ.get("LR", "2e-5")),
        lr_scheduler_type="constant",
        loss_type="dr_grpo",
        beta=0.0,
        epsilon_high=0.28,
        vllm_importance_sampling_mode="token_truncate",
        use_vllm=True,
        vllm_mode=os.environ.get("VLLM_MODE", "colocate"),
        vllm_server_host="127.0.0.1",
        vllm_server_port=int(os.environ.get("VLLM_PORT", "8001")),
        vllm_gpu_memory_utilization=float(os.environ.get("VLLM_MEM", "0.6")),
        vllm_max_model_length=CONTEXT_TOKENS,
        vllm_enable_sleep_mode=os.environ.get("VLLM_SLEEP", "1") == "1",
        bf16=True,
        gradient_checkpointing=True,
        eval_strategy="steps",
        eval_steps=int(os.environ.get("EVAL_STEPS", str(max(1, MAX_STEPS)))),
        eval_on_start=os.environ.get("EVAL_ON_START", "1") == "1",
        num_generations_eval=1,
        per_device_eval_batch_size=int(os.environ.get("EVAL_BATCH", "12")),
        logging_steps=1,
        save_strategy="steps",
        save_steps=int(os.environ.get("SAVE_STEPS", "5")),
        save_only_model=True,
        report_to="none",
        seed=0,
    ),
    train_dataset=train_rows,
    eval_dataset=eval_rows,
    environment_factory=Desk,
    peft_config=LoraConfig(r=32, lora_alpha=64, target_modules="all-linear", task_type="CAUSAL_LM"),
    callbacks=[metrics := Metrics()],
)
metrics.trainer = trainer
if MAX_STEPS == 0:
    trainer.evaluate()
else:
    trainer.train()
    trainer.save_model(str(OUT / "adapter"))
(OUT / "log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))
log.info("done in %ss: %s", round(time.monotonic() - STARTED), json.dumps(rates(ROLLOUTS)))
env.close()
