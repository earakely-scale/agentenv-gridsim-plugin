"""Registered run 3: policy gradient with the DP's exact per-hour advantages (credit.py) on Qwen3-4B SFT-10k, a fresh
LoRA r=32/a=64, a k3 KL penalty to the SFT-10k reference (the adapter switched off), PPO ratio clipping against the
behaviour policy's logprobs (rollouts are one step stale: batch k is sampled with the adapter of step k-1 while step
k-1 trains). One optimizer step per batch; loss normalised by BATCH x MAX_COMPLETION (Dr. GRPO's constant). Runs alone
(CPU or one GPU) or under torchrun (each rank takes rows[rank::world], LoRA grads all-reduced). Rollouts come from
rollout.py through ROLL/; the run's days are the train-pack days outside SFT-10k's set, each draw a uniform
(curriculum x start) cell then an unused day of it.

Env: MODEL, OUT, ROLL, STEPS, BATCH, LR, WARMUP, BETA, EPS, TEMP, MAX_COMPLETION, SAVE_EVERY, SEED, DEADLINE (unix s),
EXCLUDE (json list of task ids), TRAIN_PACK, GUARD_R, GUARD_VALID, MICRO_LOG."""

import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

import torch
import torch.distributed as dist
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from credit import pieces_of, token_credit  # noqa: E402
from pathb import KINDS, prompt_text  # noqa: E402

from gridsim_core.task import load_pack  # noqa: E402

MODEL = os.environ["MODEL"]
OUT = Path(os.environ["OUT"])
ROLL = Path(os.environ["ROLL"])
STEPS = int(os.environ.get("STEPS", "300"))
BATCH = int(os.environ.get("BATCH", "32"))
LR = float(os.environ.get("LR", "1e-5"))
WARMUP = int(os.environ.get("WARMUP", "5"))
BETA = float(os.environ.get("BETA", "0.04"))
EPS = float(os.environ.get("EPS", "0.2"))
TEMP = float(os.environ.get("TEMP", "1.0"))
MAX_COMPLETION = int(os.environ.get("MAX_COMPLETION", "512"))
SAVE_EVERY = int(os.environ.get("SAVE_EVERY", "25"))
SEED = int(os.environ.get("SEED", "0"))
DEADLINE = float(os.environ.get("DEADLINE", "0"))
GUARD_R = float(os.environ.get("GUARD_R", "0.6"))
GUARD_VALID = float(os.environ.get("GUARD_VALID", "0.9"))
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def start_state(task: dict) -> str:
    b = task["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


class Sampler:
    """Each draw: a uniform (curriculum x start) cell, then the next unused day of that cell (reshuffled when spent)."""

    def __init__(self, tasks: list[dict]):
        self.rng = random.Random(SEED)
        self.cells: dict = {}
        for t in tasks:
            self.cells.setdefault((t.get("curriculum", "C0"), start_state(t)), []).append(t["task_id"])
        self.keys = sorted(self.cells)
        self.left = {k: [] for k in self.keys}

    def draw(self, m: int) -> list[str]:
        out = []
        for _ in range(m):
            cell = self.rng.choice(self.keys)
            if not self.left[cell]:
                self.left[cell] = self.rng.sample(self.cells[cell], len(self.cells[cell]))
            out.append(self.left[cell].pop())
        return out


def write_json(path: Path, obj: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.rename(path)


def save_adapter(model, path: Path):
    tmp = path.with_name(path.name + ".tmp")
    model.save_pretrained(str(tmp))
    tmp.rename(path)


def token_logprobs(model, ids: torch.Tensor, c: int, entropy: bool = False):
    logits = model(input_ids=ids, logits_to_keep=c + 1).logits[0, :-1].float()
    lp = torch.log_softmax(logits, -1)
    out = lp.gather(-1, ids[0, -c:, None])[:, 0]
    if not entropy:
        return out, None
    with torch.no_grad():
        return out, -(lp.exp() * lp).nansum(-1)


def main():
    world = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    if world > 1:
        dist.init_process_group("nccl")
        torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
    dev = torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    torch.manual_seed(SEED)
    tok = AutoTokenizer.from_pretrained(MODEL)
    pack = load_pack(os.environ.get("TRAIN_PACK", "ercot-dam-v1-train"))
    exclude = set(json.loads(Path(os.environ["EXCLUDE"]).read_text())) if os.environ.get("EXCLUDE") else set()
    pool = [t for t in pack if t["task_id"] not in exclude]
    tasks = {t["task_id"]: t for t in pool}
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.bfloat16 if dev.type == "cuda" else torch.float32)
    model.to(dev)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.0, task_type="CAUSAL_LM",
                                             target_modules=TARGETS))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / WARMUP))
    model.train()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adapters").mkdir(exist_ok=True)
    (OUT / "checkpoints").mkdir(exist_ok=True)
    ROLL.mkdir(parents=True, exist_ok=True)
    log = (OUT / "train_log.jsonl").open("a") if rank == 0 else None
    samples = (OUT / "samples.jsonl").open("a") if rank == 0 else None
    sampler = Sampler(pool)
    prompt_ids: dict = {}

    def post(k: int, adapter: Path):
        ids = sampler.draw(BATCH)
        for tid in ids:
            if tid not in prompt_ids:
                prompt_ids[tid] = tok(prompt_text(tok, tasks[tid]), add_special_tokens=False).input_ids
        write_json(ROLL / f"req-{k:05d}.json", {"step": k, "adapter": str(adapter), "seed": SEED * 1_000_003 + k,
                                                "temperature": TEMP, "max_tokens": MAX_COMPLETION,
                                                "prompts": [{"task_id": t, "prompt_ids": prompt_ids[t]} for t in ids]})

    if rank == 0:
        print(f"pool {len(pool)} days (excluded {len(pack) - len(pool)}), {len(sampler.keys)} cells; "
              f"world {world}; steps {STEPS} x {BATCH}", flush=True)
        a0 = OUT / "adapters" / "a-00000"
        save_adapter(model, a0)
        post(0, a0)
        post(1, a0)
    started, rows_log, stop = time.monotonic(), [], False
    for k in range(STEPS):
        t0 = time.monotonic()
        if rank == 0 and k > 0:
            ak = OUT / "adapters" / f"a-{k:05d}"
            save_adapter(model, ak)
            if k + 1 < STEPS:
                post(k + 1, ak)
            old = OUT / "adapters" / f"a-{k - 3:05d}"
            if k >= 3 and old.exists():
                for f in old.iterdir():
                    f.unlink()
                old.rmdir()
        path = ROLL / f"roll-{k:05d}.json"
        while not path.exists():
            time.sleep(0.2)
        wait_s = time.monotonic() - t0
        batch = json.loads(path.read_text())
        mine = batch["rows"][rank::world]
        stats = []
        norm = len(batch["rows"]) / world * MAX_COMPLETION
        for row in mine:
            ids_c = row["ids"]
            pieces = pieces_of(tok, ids_c)
            cr = token_credit(tasks[row["task_id"]], pieces, truncated=row["finish"] == "length")
            if "".join(pieces) != row["text"]:
                cr = {**cr, "adv": [cr["reward"] - 1.0 if cr["valid"] else -1.0] * len(ids_c), "mapped": False}
            c = len(ids_c)
            ids = torch.tensor([row["prompt_ids"] + ids_c], device=dev)
            with torch.no_grad(), model.disable_adapter():
                ref, _ = token_logprobs(model, ids, c)
            logp, ent = token_logprobs(model, ids, c, entropy=True)
            mu = torch.tensor(row["logprobs"], device=dev, dtype=torch.float32)
            adv = torch.tensor(cr["adv"], device=dev, dtype=torch.float32)
            ratio = torch.exp(logp - mu)
            pg = -torch.minimum(ratio * adv, torch.clamp(ratio, 1 - EPS, 1 + EPS) * adv)
            kl = torch.exp(ref - logp) - (ref - logp) - 1
            loss = (pg + BETA * kl).sum() / norm
            loss.backward()
            with torch.no_grad():
                clipped = ((ratio < 1 - EPS) & (adv < 0)) | ((ratio > 1 + EPS) & (adv > 0))
                stats.append({"task_id": row["task_id"], "reward": cr["reward"], "valid": cr["valid"],
                              "feasible": cr["feasible"], "kind": cr["kind"], "mapped": cr["mapped"],
                              "hour_adv": cr["hour_adv"], "len": c, "trunc": row["finish"] == "length",
                              "entropy": float(ent.mean()), "kl": float(kl.mean()), "loss": float(loss) * norm / c,
                              "clip": float(clipped.float().mean()), "ratio": float(ratio.mean()),
                              "adv_tok": float(adv.mean()), "text": row["text"]})
        if world > 1:
            flat = torch.cat([p.grad.reshape(-1) for p in params])
            dist.all_reduce(flat)
            flat /= world
            off = 0
            for p in params:
                p.grad.copy_(flat[off:off + p.numel()].view_as(p.grad))
                off += p.numel()
            gathered = [None] * world
            dist.all_gather_object(gathered, stats)
            stats = [s for g in gathered for s in g]
        gnorm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        step = k + 1
        if rank == 0:
            row = summary(stats, step, batch, gnorm, wait_s, time.monotonic() - t0, time.monotonic() - started,
                          sched.get_last_lr()[0])
            rows_log.append(row)
            last = rows_log[-10:]
            if len(rows_log) >= 10 and (statistics.fmean(r["reward_mean"] for r in last) < GUARD_R
                                        or statistics.fmean(r["valid_rate"] for r in last) < GUARD_VALID):
                row["note"] = "stopped: 10-step guard"
                stop = True
            if DEADLINE and time.time() > DEADLINE:
                row["note"] = (row.get("note", "") + "; " if row.get("note") else "") + "stopped: deadline"
                stop = True
            log.write(json.dumps(row) + "\n")
            log.flush()
            best = max(stats, key=lambda s: s["reward"])
            worst = min(stats, key=lambda s: s["reward"])
            samples.write(json.dumps({"step": step, "best": {k2: best[k2] for k2 in ("task_id", "reward", "text")},
                                      "worst": {k2: worst[k2] for k2 in ("task_id", "reward", "text", "hour_adv")}})
                          + "\n")
            samples.flush()
            print(json.dumps({k2: row[k2] for k2 in ("step", "reward_mean", "valid_rate", "feasible_rate",
                                                     "share_opt", "hour_adv_mean", "share_hours_neg", "entropy",
                                                     "kl", "clip_frac", "grad_norm", "gen_wait_s", "step_s")
                              if k2 in row} | ({"note": row["note"]} if "note" in row else {})), flush=True)
            if step % SAVE_EVERY == 0 or step == STEPS or stop:
                save_adapter(model, OUT / "checkpoints" / f"ckpt-{step:04d}")
        if world > 1:
            flag = torch.tensor([1.0 if stop else 0.0], device=dev)
            dist.broadcast(flag, 0)
            stop = bool(flag.item())
        if stop:
            break
    if rank == 0:
        model.save_pretrained(str(OUT / "adapter"))
        (ROLL / "STOP").write_text("1")
        print(f"done in {round(time.monotonic() - started)}s", flush=True)
    if world > 1:
        dist.barrier()
        dist.destroy_process_group()


def summary(stats, step, batch, gnorm, wait_s, step_s, elapsed, lr) -> dict:
    n = len(stats)
    hours = [a for s in stats if s["hour_adv"] for a in s["hour_adv"]]
    out = {"step": step, "elapsed_s": round(elapsed), "step_s": round(step_s, 1), "gen_s": batch["gen_s"],
           "gen_wait_s": round(wait_s, 1), "n": n, "lr": lr,
           "reward_mean": round(statistics.fmean(s["reward"] for s in stats), 4),
           "valid_rate": round(sum(s["valid"] for s in stats) / n, 4),
           "feasible_rate": round(sum(s["feasible"] for s in stats) / n, 4),
           "share_opt": round(sum(s["reward"] >= 0.999999 for s in stats) / n, 4),
           "mapped_rate": round(sum(s["mapped"] for s in stats) / n, 4),
           "hour_adv_mean": round(statistics.fmean(hours), 5) if hours else None,
           "share_hours_neg": round(sum(a < -1e-9 for a in hours) / len(hours), 4) if hours else None,
           "hours_scored": len(hours), "entropy": round(statistics.fmean(s["entropy"] for s in stats), 5),
           "kl": round(statistics.fmean(s["kl"] for s in stats), 6),
           "clip_frac": round(statistics.fmean(s["clip"] for s in stats), 5),
           "ratio_mean": round(statistics.fmean(s["ratio"] for s in stats), 5),
           "adv_tok_mean": round(statistics.fmean(s["adv_tok"] for s in stats), 5),
           "loss_per_token": round(statistics.fmean(s["loss"] for s in stats), 6), "grad_norm": round(gnorm, 5),
           "completion_len_mean": round(statistics.fmean(s["len"] for s in stats), 1),
           "rate_hit_max_tokens": round(sum(s["trunc"] for s in stats) / n, 4)}
    for k in KINDS:
        out[f"rate_{k}"] = round(sum(s["kind"] == k for s in stats) / n, 4)
    return out


if __name__ == "__main__":
    main()
