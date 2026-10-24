"""FD-4333's fallback warm start: LoRA SFT on N DP-optimal schedules from the train split, each completion a short
template rationale from the DP solution (no LLM text) then the submit_schedule tool call, on the same oneshot prompt.
The adapter is merged into the base and saved, so GRPO adds a fresh LoRA on top and vLLM serves the merged weights.

Env: MODEL, OUT (merged model dir), TRAIN_PACK, N_SFT, EPOCHS, LR, SEED."""

import json
import math
import os
import random
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathb import prompt_text, score  # noqa: E402

from gridsim_core.task import load_pack  # noqa: E402

MODEL = os.environ.get("MODEL", "/home/ubuntu/gs/models/Qwen3-1.7B")
OUT = Path(os.environ.get("OUT", "/home/ubuntu/gs/models/qwen3-1.7b-sft200"))
N = int(os.environ.get("N_SFT", "200"))
EPOCHS = int(os.environ.get("EPOCHS", "2"))
LR = float(os.environ.get("LR", "1e-4"))
SEED = int(os.environ.get("SEED", "0"))
RATIONALE = os.environ.get("RATIONALE", "plan")
STRATIFY = os.environ.get("STRATIFY", "tag")
MICRO, ACCUM = 4, 2


def rationale(task: dict, opt: list[int]) -> str:
    """'Plan: buy HE02-HE05 (8 units) at $18-$19/MWh; sell HE18-HE20 (8 units) at $118-$213/MWh.'"""
    p, segs, h = task["prices"], [], 0
    while h < len(opt):
        if opt[h] == 0:
            h += 1
            continue
        sell, j = opt[h] > 0, h
        while j + 1 < len(opt) and opt[j + 1] != 0 and (opt[j + 1] > 0) == sell:
            j += 1
        ps, units = p[h:j + 1], sum(abs(a) for a in opt[h:j + 1])
        hrs = f"HE{h + 1:02d}" if h == j else f"HE{h + 1:02d}-HE{j + 1:02d}"
        lo, hi = round(min(ps)), round(max(ps))
        segs.append(f"{'sell' if sell else 'buy'} {hrs} ({units} unit{'s' if units != 1 else ''}) at "
                    f"{f'${lo}' if lo == hi else f'${lo}-${hi}'}/MWh")
        h = j + 1
    return "Plan: " + "; ".join(segs) + "."


def money(p: float) -> str:
    return f"{'-' if p < 0 else ''}${abs(round(p))}"


def start_state(task: dict) -> str:
    b = task["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def soc_rationale(task: dict, opt: list[int]) -> str:
    """Start, end obligation, cycle cap, cheapest and dearest hours, then the plan with the SoC after each trade."""
    b, p = task["battery"], task["prices"]
    n, s = b["soc_levels"], b["s0"]
    start = {"full": f"Starts full ({n}/{n}), so the first trade must be a sell.",
             "empty": f"Starts empty (0/{n}), so the first trade must be a buy.",
             "half": f"Starts at {s}/{n}."}[start_state(task)]
    order = sorted(range(len(p)), key=lambda h: (p[h], h))
    cheap = ", ".join(f"HE{h + 1:02d} {money(p[h])}" for h in order[:3])
    dear = ", ".join(f"HE{h + 1:02d} {money(p[h])}" for h in sorted(order[-3:], key=lambda h: (-p[h], h)))
    segs, h = [], 0
    while h < len(opt):
        if opt[h] == 0:
            h += 1
            continue
        sell, j = opt[h] > 0, h
        while j + 1 < len(opt) and opt[j + 1] != 0 and (opt[j + 1] > 0) == sell:
            j += 1
        units = sum(abs(a) for a in opt[h:j + 1])
        s -= sum(opt[h:j + 1])
        lo, hi = money(min(p[h:j + 1])), money(max(p[h:j + 1]))
        hrs = f"HE{h + 1:02d}" if h == j else f"HE{h + 1:02d}-HE{j + 1:02d}"
        segs.append(f"{'sell' if sell else 'buy'} {hrs} ({units} unit{'s' if units != 1 else ''}, "
                    f"{lo if lo == hi else f'{lo}-{hi}'}) -> {s}/{n}")
        h = j + 1
    return (f"{start} Must end at >= {b['s_end_min']}/{n}; cycle cap {b['cycle_cap_units']} units sold. "
            f"Cheapest hours: {cheap}. Dearest: {dear}. Plan: {'; '.join(segs)}. Ends at {s}/{n}.")


def completion(task: dict) -> str:
    opt = task["refs"]["foresight"]["opt"]
    call = json.dumps({"name": "submit_schedule", "arguments": {"actions": opt}})
    why = soc_rationale(task, opt) if RATIONALE == "soc" else rationale(task, opt)
    return f"{why}\n<tool_call>\n{call}\n</tool_call>"


def pick(tasks: list[dict]) -> list[dict]:
    """N tasks spread evenly over the curriculum tags (and the start states when STRATIFY=start)."""
    rng = random.Random(SEED + 17)
    key = (lambda t: (t.get("curriculum", "C0"), start_state(t))) if STRATIFY == "start" else (
        lambda t: t.get("curriculum", "C0"))
    cells = sorted({key(t) for t in tasks})
    out = []
    for i, c in enumerate(cells):
        pool = [t for t in tasks if key(t) == c]
        out += rng.sample(pool, N // len(cells) + (1 if i < N % len(cells) else 0))
    rng.shuffle(out)
    return out


def main():
    t0 = time.monotonic()
    torch.manual_seed(SEED)
    tok = AutoTokenizer.from_pretrained(MODEL)
    tasks = pick(load_pack(os.environ.get("TRAIN_PACK", "ercot-dam-v1-train")))
    rows = []
    for t in tasks:
        c = completion(t)
        assert score(t, c)["reward"] > 0.999, t["task_id"]
        p_ids = tok(prompt_text(tok, t), add_special_tokens=False).input_ids
        c_ids = tok(c + tok.eos_token, add_special_tokens=False).input_ids
        rows.append((p_ids + c_ids, [-100] * len(p_ids) + c_ids))
    clens = sorted(len(r[0]) - r[1].count(-100) for r in rows)
    print(f"sft rows {len(rows)}; completion tokens p50 {clens[len(clens) // 2]} p99 {clens[int(len(clens) * 0.99)]} "
          f"max {clens[-1]}; example completion:\n{completion(tasks[0])}", flush=True)
    (Path(str(OUT) + "-meta.json")).write_text(json.dumps({"completion_tokens_max": clens[-1], "n": len(rows)}))
    model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.bfloat16).cuda()
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.0, task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj",
                                                             "up_proj", "down_proj"]))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR, weight_decay=0.0)
    steps = EPOCHS * math.ceil(len(rows) / (MICRO * ACCUM))
    sched = get_cosine_schedule_with_warmup(opt, max(1, steps // 10), steps)
    model.train()
    rng, step = random.Random(SEED), 0
    for ep in range(EPOCHS):
        order = list(range(len(rows)))
        rng.shuffle(order)
        batches = [order[i:i + MICRO] for i in range(0, len(order), MICRO)]
        for b, idx in enumerate(batches):
            width = max(len(rows[i][0]) for i in idx)
            ids = torch.tensor([rows[i][0] + [tok.pad_token_id] * (width - len(rows[i][0])) for i in idx]).cuda()
            lab = torch.tensor([rows[i][1] + [-100] * (width - len(rows[i][1])) for i in idx]).cuda()
            att = (torch.arange(width)[None, :] < torch.tensor([len(rows[i][0]) for i in idx])[:, None]).cuda()
            loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
            (loss / ACCUM).backward()
            if (b + 1) % ACCUM == 0 or b == len(batches) - 1:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
                step += 1
                print(json.dumps({"epoch": ep, "step": step, "loss": round(loss.item(), 4),
                                  "lr": sched.get_last_lr()[0]}), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUT) + "-adapter")
    merged = model.merge_and_unload()
    merged.save_pretrained(str(OUT))
    tok.save_pretrained(str(OUT))
    (OUT / "sft_task_ids.json").write_text(json.dumps([t["task_id"] for t in tasks]))
    print(f"sft done in {round(time.monotonic() - t0)}s -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
