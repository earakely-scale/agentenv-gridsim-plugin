"""GRPO on the GridSim v1 training bundle, as the Training docs show it: the bundle downloaded from the Hub, served in
this process by AgentEnv.local, every rollout an episode the bundle's verifier scores, and TRL's eval loop playing the
200 eval days at the start and every EVAL_STEPS. MODEL is the model to start from (the SFT warm start's merged model,
or Qwen/Qwen3-4B), LR the learning rate, and MAX_STEPS=0 only evaluates it.

The docs' script plus a callback that writes each log line to $OUT/metrics.jsonl, with the rates of the episodes'
rewards since the line before: above 0 (a schedule that earned something), above 0.2 (beats idle) and at the DP
optimum."""

import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path

from agent_env.training.trl import AgentEnv
from peft import LoraConfig
from transformers import TrainerCallback
from trl import GRPOConfig, GRPOTrainer

OUT = Path(os.environ.get("OUT", "out"))
STARTED = time.monotonic()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
for noisy in ("httpx", "httpcore", "agent_env", "agentenv_protocol", "websockets"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("agent_env.training.trl").setLevel(logging.INFO)
log = logging.getLogger("gridsim_grpo")

env = AgentEnv.local("bundles/gridsim-v1", split="train", max_concurrent_envs=32)
log.info("%d train rows, %d eval rows, served at %s in %ss", len(env.dataset), len(env.dataset_for("eval")), env.url,
         round(time.monotonic() - STARTED))

REWARDS: list[float | None] = []
Environment = env.factory


def get_reward(self) -> float | None:
    reward = Environment.get_reward(self)
    REWARDS.append(reward)
    return reward


Recorded = type(Environment.__name__, (Environment,), {"get_reward": get_reward})


def rates(rewards: list[float | None]) -> dict:
    scored = [reward for reward in rewards if reward is not None]
    share = (lambda hit: round(sum(map(hit, scored)) / len(scored), 4)) if scored else (lambda hit: None)
    return {"rollouts": len(rewards), "unscored": len(rewards) - len(scored),
            "reward_mean": round(statistics.fmean(scored), 4) if scored else None,
            "earned_rate": share(lambda r: r > 0), "beats_idle_rate": share(lambda r: r > 0.2 + 1e-9),
            "optimal_rate": share(lambda r: r >= 0.99)}


class Metrics(TrainerCallback):
    def __init__(self):
        self.seen = 0
        OUT.mkdir(parents=True, exist_ok=True)
        self.file = (OUT / "metrics.jsonl").open("a")

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = logs or {}
        phase = "eval" if any(key.startswith("eval_") for key in logs) else "train"
        new, self.seen = REWARDS[self.seen:], len(REWARDS)
        row = {"phase": phase, "step": state.global_step, "elapsed_s": round(time.monotonic() - STARTED),
               **rates(new), **{key: value for key, value in logs.items() if isinstance(value, (int, float))}}
        self.file.write(json.dumps(row) + "\n")
        self.file.flush()
        log.info("%s step %s: %s", phase, state.global_step,
                 json.dumps({key: row[key] for key in ("rollouts", "unscored", "reward_mean", "earned_rate",
                                                       "beats_idle_rate", "optimal_rate", "elapsed_s")}))


trainer = GRPOTrainer(
    model=os.environ.get("MODEL", "qwen3-4b-gridsim-sft"),
    args=GRPOConfig(
        output_dir=str(OUT),
        max_steps=max(1, int(os.environ.get("MAX_STEPS", "40"))),
        per_device_train_batch_size=8,
        gradient_accumulation_steps=4,
        num_generations=8,
        max_completion_length=1024,
        max_tool_calling_iterations=2,
        chat_template_kwargs={"enable_thinking": False},
        temperature=1.1,
        learning_rate=float(os.environ.get("LR", "2e-5")),
        lr_scheduler_type="cosine",
        warmup_steps=3,
        loss_type="dr_grpo",
        beta=0.0,
        epsilon_high=0.28,
        use_vllm=True,
        vllm_mode="colocate",
        vllm_gpu_memory_utilization=0.3,
        vllm_max_model_length=4096,
        bf16=True,
        gradient_checkpointing=True,
        eval_strategy="steps",
        eval_steps=int(os.environ.get("EVAL_STEPS", "20")),
        eval_on_start=os.environ.get("EVAL_ON_START", "1") == "1",
        num_generations_eval=1,
        per_device_eval_batch_size=32,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        seed=0,
    ),
    train_dataset=env.dataset,
    eval_dataset=env.dataset_for("eval"),
    environment_factory=Recorded,
    peft_config=LoraConfig(r=32, lora_alpha=64, target_modules="all-linear", task_type="CAUSAL_LM"),
    callbacks=[Metrics()],
)
if os.environ.get("MAX_STEPS") == "0":
    trainer.evaluate()
else:
    trainer.train()
    trainer.save_model(str(OUT / "adapter"))
(OUT / "log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))
log.info("done in %ss: %s", round(time.monotonic() - STARTED), json.dumps(rates(REWARDS)))
env.close()
