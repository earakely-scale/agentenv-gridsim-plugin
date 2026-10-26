"""Warm start: LoRA SFT on N DP-optimal schedules from the train split, each completion a template rationale from the
DP solution (no LLM text) then the submit_schedule tool call, on the same oneshot prompt. The adapter is merged into
the base and saved, so GRPO adds a fresh LoRA on top and vLLM serves the merged weights. RATIONALE=rule adds the
DP's decision rule (which buys pair with which sells, and why) and an end-of-day check to the SoC-aware rationale.

Env: MODEL, OUT (merged model dir), TRAIN_PACK, N_SFT, EPOCHS, LR, SEED, RATIONALE, STRATIFY, MICRO, MAX_TOKENS."""

import json
import math
import os
import random
import sys
import time
from collections import deque
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
MICRO = int(os.environ.get("MICRO", "4"))
ACCUM = 8 // MICRO
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "0"))


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


def dollars(p: float, d: int) -> str:
    return money(p) if d == 0 else f"{'-' if p < 0 else ''}${abs(p):.{d}f}"


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


def segments(opt: list[int]) -> list[tuple[int, int, bool]]:
    """Maximal same-direction runs of the schedule: (first hour, last hour, sell)."""
    out, h = [], 0
    while h < len(opt):
        if opt[h] == 0:
            h += 1
            continue
        sell, j = opt[h] > 0, h
        while j + 1 < len(opt) and opt[j + 1] != 0 and (opt[j + 1] > 0) == sell:
            j += 1
        out.append((h, j, sell))
        h = j + 1
    return out


def hours(h: int, j: int) -> str:
    return f"HE{h + 1:02d}" if h == j else f"HE{h + 1:02d}-HE{j + 1:02d}"


def pairing(task: dict, opt: list[int]) -> tuple[list, dict, dict, dict]:
    """Unit-level FIFO matching of the schedule: each sold unit pairs with the earliest open bought unit, a sell with
    none open uses stock above the end level, else it is bought back later. Returns (segments, {(seg, seg): [(buy,
    sell)]}, {seg: [price]} stored units sold, {seg: [price]} bought units still held at the end)."""
    b, p = task["battery"], task["prices"]
    segs = segments(opt)
    seg_of = {h: k for k, (i, j, _) in enumerate(segs) for h in range(i, j + 1)}
    free = max(0, b["s0"] - b["s_end_min"])
    longs, shorts, groups, stored, held = deque(), deque(), {}, {}, {}
    for h, a in enumerate(opt):
        k = seg_of.get(h)
        for _ in range(abs(a)):
            if a < 0 and shorts:
                k0, p0 = shorts.popleft()
                groups.setdefault((k0, k), []).append((p[h], p0))
            elif a < 0:
                longs.append((k, p[h]))
            elif longs:
                k0, p0 = longs.popleft()
                groups.setdefault((k0, k), []).append((p0, p[h]))
            elif free:
                free -= 1
                stored.setdefault(k, []).append(p[h])
            else:
                shorts.append((k, p[h]))
    assert not shorts, task["task_id"]
    for k, pr in longs:
        held.setdefault(k, []).append(pr)
    return segs, groups, stored, held


def rule_rationale(task: dict, opt: list[int], lists: bool = True) -> str:
    """The SoC-aware rationale plus the DP's decision rule: which buys pair with which sells and the margin check
    (sell - c_deg) x eta > buy, stored or held units, and an end-of-day check against the end level and cycle cap.
    lists=False drops the cheapest and dearest hours, the trim for days whose full text runs past MAX_TOKENS."""
    b, p = task["battery"], task["prices"]
    n, s0, c, eta = b["soc_levels"], b["s0"], b["c_deg"], b["eta"]
    start = {"full": f"Starts full ({n}/{n}), so the first trade must be a sell.",
             "empty": f"Starts empty (0/{n}), so the first trade must be a buy.",
             "half": f"Starts at {s0}/{n}."}[start_state(task)]
    order = sorted(range(len(p)), key=lambda h: (p[h], h))
    cheap = ", ".join(f"HE{h + 1:02d} {money(p[h])}" for h in order[:3])
    dear = ", ".join(f"HE{h + 1:02d} {money(p[h])}" for h in sorted(order[-3:], key=lambda h: (-p[h], h)))
    segs, groups, stored, held = pairing(task, opt)
    deg = f"(s - {money(c)}) x {eta:g}" if c else f"s x {eta:g}"
    items = []
    for (k0, k1), us in sorted(groups.items()):
        buy, sell = sum(u[0] for u in us) / len(us), sum(u[1] for u in us) / len(us)
        lhs = (sell - c) * eta
        i0, j0, s_first = segs[k0]
        i1, j1, _ = segs[k1]
        how = (f"sell {hours(i0, j0)} -> buy back {hours(i1, j1)}" if s_first
               else f"buy {hours(i0, j0)} -> sell {hours(i1, j1)}")
        d = next((d for d in (0, 1, 2) if dollars(lhs, d) != dollars(buy, d)), 2)
        calc = f"({dollars(sell, d)} - {money(c)}) x {eta:g}" if c else f"{dollars(sell, d)} x {eta:g}"
        items.append(f"{how} x{len(us)}: {calc} = {dollars(lhs, d)} {'>' if lhs > buy else '<='} {dollars(buy, d)}")
    for k, pr in sorted(stored.items()):
        items.append(f"sell {hours(*segs[k][:2])} x{len(pr)} from stock above the end level")
    for k, pr in sorted(held.items()):
        why = "paid to charge" if max(pr) < 0 else "for the end level"
        items.append(f"buy {hours(*segs[k][:2])} x{len(pr)} and hold, {why}")
    s, plan = s0, []
    for i, j, sell in segs:
        units = sum(abs(a) for a in opt[i:j + 1])
        s -= sum(opt[i:j + 1])
        lo, hi = money(min(p[i:j + 1])), money(max(p[i:j + 1]))
        plan.append(f"{'sell' if sell else 'buy'} {hours(i, j)} ({units} unit{'s' if units != 1 else ''}, "
                    f"{lo if lo == hi else f'{lo}-{hi}'}) -> {s}/{n}")
    sold = sum(a for a in opt if a > 0)
    end = "ok" if s >= b["s_end_min"] else f"short {b['s_end_min'] - s}"
    return (f"{start} Must end at >= {b['s_end_min']}/{n}; cycle cap {b['cycle_cap_units']} units sold. "
            f"{f'Cheapest hours: {cheap}. Dearest: {dear}.' if lists else ''}\n"
            f"Rule: a buy at b and a sell at s pay if {deg} > b. "
            f"Pairs: {'; '.join(items) if items else 'none pays today'}.\n"
            f"Plan: {'; '.join(plan) if plan else 'idle all day'}.\n"
            f"End check: ends at {s}/{n} vs >= {b['s_end_min']}/{n} required, {end}; "
            f"sold {sold} of {b['cycle_cap_units']} cap.")


def completion(task: dict, lists: bool = True) -> str:
    opt = task["refs"]["foresight"]["opt"]
    call = json.dumps({"name": "submit_schedule", "arguments": {"actions": opt}})
    if RATIONALE == "rule":
        why = rule_rationale(task, opt, lists)
    else:
        why = soc_rationale(task, opt) if RATIONALE == "soc" else rationale(task, opt)
    return f"{why}\n<tool_call>\n{call}\n</tool_call>"


def fitted(tok, task: dict) -> str | None:
    """The completion, trimmed of the cheapest/dearest lists when the full text runs past MAX_TOKENS; None when
    neither fits (the day is left out of the SFT pool)."""
    for lists in (True, False):
        c = completion(task, lists)
        if not MAX_TOKENS or len(tok(c + tok.eos_token, add_special_tokens=False).input_ids) <= MAX_TOKENS:
            return c
    return None


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
    pool = load_pack(os.environ.get("TRAIN_PACK", "ercot-dam-v1-train"))
    texts = {t["task_id"]: fitted(tok, t) for t in pool}
    tasks = pick([t for t in pool if texts[t["task_id"]]])
    trimmed = sum(texts[t["task_id"]] != completion(t) for t in tasks)
    rows = []
    for t in tasks:
        c = texts[t["task_id"]]
        assert score(t, c)["reward"] > 0.999, t["task_id"]
        p_ids = tok(prompt_text(tok, t), add_special_tokens=False).input_ids
        c_ids = tok(c + tok.eos_token, add_special_tokens=False).input_ids
        rows.append((p_ids + c_ids, [-100] * len(p_ids) + c_ids))
    clens = sorted(len(r[0]) - r[1].count(-100) for r in rows)
    print(f"sft rows {len(rows)}; completion tokens p50 {clens[len(clens) // 2]} p99 {clens[int(len(clens) * 0.99)]} "
          f"max {clens[-1]}; trimmed {trimmed}; pool {len(pool)}, left out {sum(not v for v in texts.values())}; "
          f"example completion:\n{texts[tasks[0]['task_id']]}", flush=True)
    meta = {"completion_tokens_max": clens[-1], "completion_tokens_p50": clens[len(clens) // 2],
            "completion_tokens_p99": clens[int(len(clens) * 0.99)], "n": len(rows), "trimmed": trimmed,
            "pool": len(pool), "left_out": sum(not v for v in texts.values()), "max_tokens": MAX_TOKENS}
    (Path(str(OUT) + "-meta.json")).write_text(json.dumps(meta))
    if os.environ.get("MEASURE") == "1":
        full = sorted(len(tok(completion(t) + tok.eos_token, add_special_tokens=False).input_ids) for t in pool)
        print(json.dumps({**meta, "pool_full_p50": full[len(full) // 2], "pool_full_p90": full[int(len(full) * .9)],
                          "pool_full_p99": full[int(len(full) * .99)], "pool_full_max": full[-1],
                          "pool_full_over": {k: sum(x > k for x in full) for k in (384, 416, 448, 480, 512)},
                          "prompt_tokens": len(tok(prompt_text(tok, tasks[0]), add_special_tokens=False).input_ids)}))
        return
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
