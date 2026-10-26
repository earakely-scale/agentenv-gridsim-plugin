"""Path B GRPO: one prompt (oneshot system prompt + situation + submit_schedule schema), one completion, reward =
gridsim_core.grade. TRL GRPOTrainer with reward_funcs, LoRA and colocated vLLM. CURRICULUM=adaptive adds the registered
run 2 sampling: each step draws CANDIDATES prompts (a uniform curriculum x start cell each, then with probability
REPLAY_P a seen day weighted by its last group's reward std, else an unseen day), generates NUM_GEN rollouts for each,
and trains on the first PROMPTS_PER_STEP groups whose rewards are not all equal (DAPO-style dynamic sampling).

Env: MODEL, OUT, TRAIN_PACK, MAX_STEPS, SAVE_STEPS, SEED, MAX_COMPLETION, FORMAT_CREDIT (0 = none), SMOKE=1 (synthetic
tasks, 2 steps), PROMPTS_PER_STEP, NUM_GEN, MICRO (per-device batch), VLLM_UTIL, LR, CANDIDATES, REPLAY_P, VISIT_CAP."""

import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig
from transformers import AutoTokenizer, TrainerCallback
from trl import GRPOConfig, GRPOTrainer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathb import prompt_text, score, summarize  # noqa: E402

MODEL = os.environ.get("MODEL", "/home/ubuntu/gs/models/Qwen3-1.7B")
OUT = Path(os.environ.get("OUT", "/home/ubuntu/gs/runs/grpo"))
SMOKE = os.environ.get("SMOKE") == "1"
MAX_STEPS = int(os.environ.get("MAX_STEPS", "2" if SMOKE else "400"))
SAVE_STEPS = int(os.environ.get("SAVE_STEPS", "50"))
SEED = int(os.environ.get("SEED", "0"))
MAX_COMPLETION = int(os.environ.get("MAX_COMPLETION", "384"))
FORMAT_CREDIT = float(os.environ.get("FORMAT_CREDIT", "0"))
CREDIT_UNTIL = int(os.environ.get("CREDIT_UNTIL", "100"))
PROMPTS = int(os.environ.get("PROMPTS_PER_STEP", "4"))
NUM_GEN = int(os.environ.get("NUM_GEN", "8"))
MICRO = int(os.environ.get("MICRO", "8"))
PHASES = (0.2, 0.6)
CURRICULUM = os.environ.get("CURRICULUM", "phased")
TEMP = float(os.environ.get("TEMP", "1.0"))
DEADLINE = float(os.environ.get("DEADLINE", "0"))
STEP_OFFSET = int(os.environ.get("STEP_OFFSET", "0"))
CLIFF_R = float(os.environ.get("CLIFF_R", "0"))
CLIFF_FEAS = float(os.environ.get("CLIFF_FEAS", "0"))
REPLAY = 0.25
CANDIDATES = int(os.environ.get("CANDIDATES", "16"))
REPLAY_P = float(os.environ.get("REPLAY_P", "0.5"))
VISIT_CAP = int(os.environ.get("VISIT_CAP", "4"))
STARTED = time.monotonic()
STATE = {"step": 0}
RECORDS: list[dict] = []


def synthetic_tasks(n: int) -> list[dict]:
    from gridsim_core.task import make_battery, make_task

    rng = random.Random(SEED)
    out = []
    for i in range(n):
        base = rng.uniform(15, 40)
        prices = [round(base + 25 * max(0, 1 - abs(h - 18) / 4) * rng.uniform(0.5, 3) - 8 * max(0, 1 - abs(h - 4) / 3)
                        + rng.gauss(0, 3), 2) for h in range(24)]
        b = make_battery(100, 200, 4, archetype="2h-c", c_deg=4.0, cycles=1.5)
        t = make_task(prices, b, date=f"2024-07-{1 + i % 28:02d}", point="HB_WEST")
        t["curriculum"] = f"C{i % 3}"
        t["difficulty"] = rng.random()
        out.append(t)
    return out


def load_tasks() -> list[dict]:
    if SMOKE:
        return synthetic_tasks(24)
    from gridsim_core.task import load_pack

    return load_pack(os.environ.get("TRAIN_PACK", "ercot-dam-v1-train"))


def start_state(task: dict) -> str:
    b = task["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def mixed(tasks: list[dict], steps: int) -> list[dict]:
    """From step 0, each prompt draws a (curriculum tag, start state) cell uniformly, then a task in it."""
    rng = random.Random(SEED)
    cells: dict = {}
    for t in tasks:
        cells.setdefault((t.get("curriculum", "C0"), start_state(t)), []).append(t)
    keys = sorted(cells)
    return [{**rng.choice(cells[rng.choice(keys)]), "_phase": "mix"} for _ in range(steps * PROMPTS)]


def curriculum(tasks: list[dict], steps: int) -> list[dict]:
    """PROMPTS rows per step: phase k (C0 for the first 20% of steps, C1 to 60%, C2 after) draws its own tag, with
    REPLAY of earlier tags from phase 1 on; in C2 the top difficulty quartile is drawn twice as often."""
    rng = random.Random(SEED)
    tags = {c: [t for t in tasks if t.get("curriculum") == c] for c in ("C0", "C1", "C2")}
    tags = {c: v for c, v in tags.items() if v} or {"C0": tasks}
    order = sorted(tags)
    c2 = tags.get("C2", [])
    cut = sorted(t.get("difficulty", 0) for t in c2)[3 * len(c2) // 4] if c2 else None
    c2w = [2.0 if t.get("difficulty", 0) >= cut else 1.0 for t in c2]
    rows = []
    for s in range(steps):
        phase = min(len(order) - 1, 0 if s < PHASES[0] * steps else 1 if s < PHASES[1] * steps else 2)
        for _ in range(PROMPTS):
            if phase and rng.random() < REPLAY:
                pick = rng.choice([t for c in order[:phase] for t in tags[c]])
            elif order[phase] == "C2":
                pick = rng.choices(c2, c2w)[0]
            else:
                pick = rng.choice(tags[order[phase]])
            rows.append({**pick, "_phase": order[phase]})
    return rows


tok = AutoTokenizer.from_pretrained(MODEL)
tasks = load_tasks()
TASKS = {t["task_id"]: t for t in tasks}
rows = (mixed if CURRICULUM in ("mixed", "adaptive") else curriculum)(tasks, MAX_STEPS)
PHASE_OF = [r["_phase"] for r in rows[::PROMPTS]]
dataset = Dataset.from_list([{"prompt": prompt_text(tok, r), "task_id": r["task_id"]} for r in rows])
plens = [len(tok(p).input_ids) for p in dataset["prompt"][:64]]
print(f"tasks {len(tasks)} rows {len(rows)} prompt tokens mean {statistics.fmean(plens):.0f} max {max(plens)}",
      flush=True)
print(dataset["prompt"][0], flush=True)


def credit(r: dict) -> float:
    if not FORMAT_CREDIT or not r["valid"] or r["kind"] == "all_idle":
        return 0.0
    return FORMAT_CREDIT * max(0.0, 1 - STATE["step"] / CREDIT_UNTIL)


class Sampler:
    """Adaptive day sampling: each draw picks a (curriculum, start) cell uniformly, the T4 mix, so no cell starves;
    then with probability REPLAY_P a seen day of that cell whose last group of NUM_GEN rollouts had reward std > 0
    and fewer than VISIT_CAP visits, chosen with weight = that std, else an unseen day of the cell."""

    def __init__(self, tasks: list[dict]):
        self.rng = random.Random(SEED + 1)
        self.cells: dict = {}
        for t in tasks:
            self.cells.setdefault((t.get("curriculum", "C0"), start_state(t)), []).append(t["task_id"])
        self.keys = sorted(self.cells)
        self.unseen = {k: self.rng.sample(v, len(v)) for k, v in self.cells.items()}
        self.cell_of = {tid: k for k, v in self.cells.items() for tid in v}
        self.seen: dict = {}
        self.replayable: dict = {k: {} for k in self.keys}

    def draw(self, m: int) -> list[tuple[str, str]]:
        out, used = [], set()
        for _ in range(m):
            cell = self.rng.choice(self.keys)
            pool = [t for t in self.replayable[cell] if t not in used]
            if pool and self.rng.random() < REPLAY_P:
                tid, how = self.rng.choices(pool, [self.replayable[cell][t] for t in pool])[0], "replay"
            else:
                tid, how = self.unseen[cell].pop(), "fresh"
            used.add(tid)
            out.append((tid, how))
        return out

    def update(self, tid: str, rewards: list[float], step: int):
        sd = statistics.pstdev(rewards)
        n = self.seen.get(tid, {}).get("n", 0) + 1
        self.seen[tid] = {"n": n, "sd": round(sd, 4), "succ": sum(r >= 0.95 for r in rewards) / len(rewards),
                          "step": step}
        cell = self.cell_of[tid]
        if sd > 0 and n < VISIT_CAP:
            self.replayable[cell][tid] = sd
        else:
            self.replayable[cell].pop(tid, None)


def gridsim_reward(prompts, completions, task_id, completion_ids=None, **kwargs) -> list[float]:
    out = []
    for i, (text, tid) in enumerate(zip(completions, task_id, strict=True)):
        n = len(completion_ids[i]) if completion_ids is not None else 0
        r = score(TASKS[tid], text, truncated=n >= MAX_COMPLETION)
        r.update(len=n, task_id=tid, text=text, start=start_state(TASKS[tid]))
        RECORDS.append(r)
        out.append(r["reward"] + credit(r))
    return out


class DynamicGRPOTrainer(GRPOTrainer):
    """Replaces each step's dataloader prompts with CANDIDATES adaptive draws, scores NUM_GEN rollouts for each, and
    keeps the first PROMPTS groups with reward spread (topped up in draw order with zero-spread groups if too few)."""

    def _generate_and_score_completions(self, inputs):
        if not self.model.training or CURRICULUM != "adaptive":
            return super()._generate_and_score_completions(inputs)
        draws = SAMPLER.draw(CANDIDATES)
        big = [{"prompt": prompt_of(tid), "task_id": tid} for tid, _ in draws for _ in range(NUM_GEN)]
        start = len(RECORDS)
        out = super()._generate_and_score_completions(big)
        recs = RECORDS[start:]
        spread = []
        for g, (tid, how) in enumerate(draws):
            group = recs[g * NUM_GEN:(g + 1) * NUM_GEN]
            spread.append(statistics.pstdev([r["reward"] for r in group]) > 0)
            SAMPLER.update(tid, [r["reward"] for r in group], self.state.global_step)
            for r in group:
                r["draw"] = how
        keep = ([g for g in range(len(draws)) if spread[g]] + [g for g in range(len(draws)) if not spread[g]])[:PROMPTS]
        keep.sort()
        for g in keep:
            for r in recs[g * NUM_GEN:(g + 1) * NUM_GEN]:
                r["kept"] = True
        idx = torch.tensor([g * NUM_GEN + i for g in keep for i in range(NUM_GEN)], device=out["advantages"].device)
        b = len(big)
        out = {k: v[idx] if torch.is_tensor(v) and v.dim() and v.size(0) == b else v for k, v in out.items()}
        out["num_items_in_batch"] = out["completion_mask"].sum()
        return out


PROMPT_CACHE: dict = {}


def prompt_of(tid: str) -> str:
    if tid not in PROMPT_CACHE:
        PROMPT_CACHE[tid] = prompt_text(tok, TASKS[tid])
    return PROMPT_CACHE[tid]


SAMPLER = Sampler(tasks)


class Log(TrainerCallback):
    """One train_log.jsonl row per optimizer step: TRL's logs plus R, valid rate and the error taxonomy of that
    step's rollouts; a sample completion per step goes to samples.jsonl."""

    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        self.file = (OUT / "train_log.jsonl").open("a")
        self.samples = (OUT / "samples.jsonl").open("a")
        self.seen = 0
        self.rows = []

    def on_step_begin(self, args, state, control, **kwargs):
        STATE["step"] = state.global_step

    def on_log(self, args, state, control, logs=None, **kwargs):
        allnew, self.seen = RECORDS[self.seen:], len(RECORDS)
        if not allnew:
            return
        groups = [allnew[i:i + NUM_GEN] for i in range(0, len(allnew), NUM_GEN)]
        zero = sum(statistics.pstdev([r["reward"] for r in g]) == 0 for g in groups) / len(groups)
        extra = {}
        new = allnew
        if CURRICULUM == "adaptive":
            new = [r for r in allnew if r.get("draw") == "fresh"] or allnew
            kept = [g for g in groups if g[0].get("kept")]
            for name, gs in (("fresh", [g for g in groups if g[0].get("draw") == "fresh"]),
                             ("replay", [g for g in groups if g[0].get("draw") == "replay"]), ("kept", kept)):
                if gs:
                    extra[f"frac_zero_spread_{name}"] = round(
                        sum(statistics.pstdev([r["reward"] for r in g]) == 0 for g in gs) / len(gs), 4)
                    extra[f"reward_mean_{name}"] = round(statistics.fmean(r["reward"] for g in gs for r in g), 4)
                    extra[f"groups_{name}"] = len(gs)
            extra["reward_mean_all"] = round(statistics.fmean(r["reward"] for r in allnew), 4)
            extra["replayable_days"] = sum(len(v) for v in SAMPLER.replayable.values())
            extra["seen_days"] = len(SAMPLER.seen)
        step = state.global_step
        row = {"step": step, "arm_step": step + STEP_OFFSET, "phase": PHASE_OF[min(step - 1, len(PHASE_OF) - 1)],
               "elapsed_s": round(time.monotonic() - STARTED), **summarize(new),
               "frac_zero_spread_groups": round(zero, 4), **extra,
               "format_credit": round(FORMAT_CREDIT * max(0.0, 1 - (step - 1) / CREDIT_UNTIL), 4),
               **{f"reward_{st}": round(statistics.fmean(r["reward"] for r in new if r["start"] == st), 4)
                  for st in ("empty", "half", "full") if any(r["start"] == st for r in new)},
               **{k: v for k, v in (logs or {}).items() if isinstance(v, (int, float))}}
        if row.get("entropy", 1.0) < 0.02:
            row["note"] = "entropy below 0.02"
        self.rows.append(row)
        last = self.rows[-10:]
        if (CLIFF_R or CLIFF_FEAS) and len(self.rows) >= 10:
            above = (statistics.fmean(r["reward_mean"] for r in last) >= CLIFF_R
                     and statistics.fmean(r["feasible_rate"] for r in last) >= CLIFF_FEAS)
            if above and not STATE.get("armed"):
                STATE["armed"] = step
                row["note"] = (row.get("note", "") + "; " if row.get("note") else "") + "cliff guard armed"
            elif not above and STATE.get("armed"):
                row["note"] = (row.get("note", "") + "; " if row.get("note") else "") + "stopped: 10-step cliff guard"
                control.should_save = True
                control.should_training_stop = True
        row["guard_armed"] = bool(STATE.get("armed"))
        self.file.write(json.dumps(row) + "\n")
        self.file.flush()
        best = max(allnew, key=lambda r: r["reward"])
        self.samples.write(json.dumps({"step": step, "task_id": best["task_id"], "reward": best["reward"],
                                       "text": best["text"], "worst": min(allnew, key=lambda r: r["reward"])["text"]})
                           + "\n")
        self.samples.flush()
        print(json.dumps({k: row[k] for k in ("step", "arm_step", "phase", "elapsed_s", "reward_mean", "valid_rate",
                                              "rate_all_idle", "rate_malformed", "rate_truncated",
                                              "completion_len_mean", "frac_zero_spread_groups",
                                              "frac_zero_spread_kept", "reward_mean_kept", "entropy", "note")
                          if k in row}),
              flush=True)


class Deadline(TrainerCallback):
    """Stop and save at the wall-clock DEADLINE (unix seconds); the cosine schedule still runs to MAX_STEPS."""

    def on_step_end(self, args, state, control, **kwargs):
        if DEADLINE and time.time() > DEADLINE:
            print(f"deadline reached at step {state.global_step}", flush=True)
            control.should_save = True
            control.should_training_stop = True


config = GRPOConfig(
    output_dir=str(OUT),
    max_steps=MAX_STEPS,
    per_device_train_batch_size=MICRO,
    gradient_accumulation_steps=PROMPTS * NUM_GEN // MICRO,
    num_generations=NUM_GEN,
    max_completion_length=MAX_COMPLETION,
    temperature=TEMP,
    learning_rate=float(os.environ.get("LR", "5e-6")),
    lr_scheduler_type=os.environ.get("LR_SCHED", "cosine"),
    warmup_steps=int(os.environ.get("WARMUP", "10")),
    weight_decay=0.0,
    optim="adamw_torch_fused",
    beta=0.0,
    loss_type="dr_grpo",
    epsilon=0.2,
    epsilon_high=0.28,
    shuffle_dataset=False,
    use_vllm=True,
    vllm_mode="colocate",
    vllm_gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.4")),
    vllm_max_model_length=2048,
    bf16=True,
    gradient_checkpointing=True,
    logging_steps=1,
    save_strategy="steps",
    save_steps=SAVE_STEPS,
    save_only_model=True,
    report_to="none",
    seed=SEED,
)
trainer = DynamicGRPOTrainer(
    model=MODEL,
    args=config,
    train_dataset=dataset,
    reward_funcs=[gridsim_reward],
    processing_class=tok,
    peft_config=LoraConfig(r=32, lora_alpha=64, lora_dropout=0.0, task_type="CAUSAL_LM",
                           target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj",
                                           "down_proj"]),
    callbacks=[Log(), Deadline()],
)
trainer.train()
trainer.save_model(str(OUT / "adapter"))
(OUT / "log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))
print(f"done in {round(time.monotonic() - STARTED)}s", flush=True)
