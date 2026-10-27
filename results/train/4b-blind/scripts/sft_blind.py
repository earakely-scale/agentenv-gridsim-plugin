"""Registered run 4 SFT (forecast-then-plan warm start): a LoRA r=32/a=64 on every attention and MLP projection of
MODEL, one epoch over rows START..START+N of sft_rows.jsonl.gz (the blind forecast-then-plan prompt -> the teacher
completion + end of turn). lr LR cosine with 10% warmup, 8 rows per optimizer step, micro-batch 1 without padding;
loss = the mean over a step's 8 rows of each row's mean token NLL on its completion (logits on those positions only).
Alone or under torchrun (rank r takes rows r::world of each step; LoRA grads all-reduced as a sum). Writes the adapter,
the merged model and train_log.jsonl (with tokens/s, the throughput the N rule uses).

Env: MODEL, OUT, DATA, N, START, LR, SEED, GC (1 = gradient checkpointing), DEADLINE (unix s), MERGE (1)."""

import gzip
import json
import math
import os
import random
import sys
import time
from pathlib import Path

import torch
import torch.distributed as dist
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathb_blind import prompt_text, score  # noqa: E402

MODEL, OUT, DATA = os.environ["MODEL"], Path(os.environ["OUT"]), os.environ["DATA"]
N, START = int(os.environ["N"]), int(os.environ.get("START", "0"))
LR, SEED, ROWS = float(os.environ.get("LR", "1e-4")), int(os.environ.get("SEED", "0")), 8
GC, DEADLINE = os.environ.get("GC", "0") == "1", float(os.environ.get("DEADLINE", "0"))
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def load_rows(tok) -> list[tuple[list[int], int]]:
    with gzip.open(DATA, "rt") as f:
        rows = [json.loads(x) for _, x in zip(range(START + N), f, strict=False)][START:]
    out = []
    for r in rows:
        assert score(r["task"], r["completion"])["c_f"] == 1.0, r["task"]["task_id"]
        p = tok(prompt_text(tok, r["task"]), add_special_tokens=False).input_ids
        c = tok(r["completion"] + tok.eos_token, add_special_tokens=False).input_ids
        out.append((p + c, len(c)))
    return out


def main():
    world, rank = int(os.environ.get("WORLD_SIZE", "1")), int(os.environ.get("RANK", "0"))
    if world > 1:
        dist.init_process_group("nccl")
        torch.cuda.set_device(int(os.environ["LOCAL_RANK"]))
    torch.manual_seed(SEED)
    t0 = time.monotonic()
    tok = AutoTokenizer.from_pretrained(MODEL)
    rows = load_rows(tok)
    order = list(range(len(rows)))
    random.Random(SEED).shuffle(order)
    steps = math.ceil(len(order) / ROWS)
    clen = sorted(c for _, c in rows)
    if rank == 0:
        print(json.dumps({"rows": len(rows), "steps": steps, "tokens_mean": round(sum(len(r) for r, _ in rows)
                          / len(rows), 1), "completion_p50": clen[len(clen) // 2], "completion_max": clen[-1],
                          "prep_s": round(time.monotonic() - t0, 1), "world": world, "gc": GC}), flush=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.bfloat16).cuda()
    model.config.use_cache = False
    if GC:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.0, task_type="CAUSAL_LM",
                                             target_modules=TARGETS))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR, weight_decay=0.0)
    warm = max(1, steps // 10)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (s + 1) / warm if s < warm else
                                              0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, steps - warm))))
    model.train()
    OUT.mkdir(parents=True, exist_ok=True)
    log = (OUT / "train_log.jsonl").open("a") if rank == 0 else None
    started, note = time.monotonic(), None
    for step in range(steps):
        ts, ntok, losses = time.monotonic(), 0, []
        batch = order[step * ROWS:(step + 1) * ROWS]
        for i in batch[rank::world]:
            ids, c = rows[i]
            x = torch.tensor([ids], device="cuda")
            logits = model(input_ids=x, logits_to_keep=c + 1).logits[0, :-1].float()
            loss = F.cross_entropy(logits, x[0, -c:])
            (loss / len(batch)).backward()
            losses.append(float(loss))
            ntok += len(ids)
        if world > 1:
            flat = torch.cat([p.grad.reshape(-1) for p in params])
            dist.all_reduce(flat)
            off = 0
            for p in params:
                p.grad.copy_(flat[off:off + p.numel()].view_as(p.grad))
                off += p.numel()
            stat = torch.tensor([sum(losses), len(losses), ntok], device="cuda", dtype=torch.float64)
            dist.all_reduce(stat)
            loss_mean, ntok = float(stat[0] / stat[1]), int(stat[2])
        else:
            loss_mean = sum(losses) / len(losses)
        gnorm = float(torch.nn.utils.clip_grad_norm_(params, 1.0))
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        dt = time.monotonic() - ts
        if DEADLINE and time.time() > DEADLINE:
            note = f"stopped: deadline after step {step + 1} of {steps}"
        if rank == 0:
            row = {"step": step + 1, "loss": round(loss_mean, 4), "lr": sched.get_last_lr()[0],
                   "grad_norm": round(gnorm, 4), "step_s": round(dt, 2), "tokens": ntok,
                   "tokens_per_s": round(ntok / dt, 1), "elapsed_s": round(time.monotonic() - started),
                   "peak_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)} | ({"note": note} if note else {})
            log.write(json.dumps(row) + "\n")
            log.flush()
            if (step + 1) % 10 == 0 or step + 1 == steps or note:
                print(json.dumps(row), flush=True)
        if note:
            break
    if rank == 0:
        model.save_pretrained(str(OUT / "adapter"))
        if os.environ.get("MERGE", "1") == "1":
            merged = model.merge_and_unload()
            merged.save_pretrained(str(OUT / "merged"))
            tok.save_pretrained(str(OUT / "merged"))
        el = time.monotonic() - started
        tot = sum(len(r) for r, _ in rows)
        (OUT / "sft_done.json").write_text(json.dumps({"rows": len(rows), "steps_done": step + 1, "steps": steps,
                                                        "train_s": round(el), "tokens": tot,
                                                        "tokens_per_s": round(tot * (step + 1) / steps / el, 1),
                                                        "note": note}) + "\n")
        print(f"sft done in {round(el)}s -> {OUT}", flush=True)
    if world > 1:
        dist.barrier()
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
