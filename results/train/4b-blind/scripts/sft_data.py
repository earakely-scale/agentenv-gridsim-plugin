"""Registered run 4's data (CPU): the 2024 start-choice holdout, the SFT rows and the RL pool, from the train pack.

Every train-pack task outside the holdout dates gets its blind inputs (build_pack's lags when the pack row has none) and
its completion: the written cross-fitted teacher forecast, run 2's rule rationale made on that forecast (no
cheapest/dearest lists), then the submit_schedule call with the DP plan on the written forecast. The SFT order is a
seeded round-robin over the (curriculum x start) cells, so its first N rows are as balanced as the pool allows.

PYTHONPATH=src:scripts:results/blind-ceiling/scripts python sft_data.py TEACHER.json.gz OUT_DIR"""

import gzip
import json
import random
import sys
from collections import deque
from pathlib import Path

import build_pack as bp
import ceiling as cl

from gridsim_core.dp import dp_schedule
from gridsim_core.forecast_line import forecast_line, parse_forecast, written
from gridsim_core.task import battery_of, load_pack

SEED, N_HOLD_DATES, PER_DATE = 0, 100, 2
KEEP = ("task_id", "date", "settlement_point", "point_kind", "region", "prices", "blind", "battery", "curriculum",
        "difficulty", "tags")


def start_state(task: dict) -> str:
    b = task["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def money(p: float) -> str:
    return f"{'-' if p < 0 else ''}${abs(round(p))}"


def dollars(p: float, d: int) -> str:
    return money(p) if d == 0 else f"{'-' if p < 0 else ''}${abs(p):.{d}f}"


def segments(opt: list[int]) -> list[tuple[int, int, bool]]:
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
    """Run 2's unit-level FIFO matching of the schedule (results/train/4b-v2/scripts/sft.py), unchanged."""
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


def rule_rationale(task: dict, opt: list[int]) -> str:
    """Run 2's rule rationale with lists=False, on task["prices"] (here: the written forecast)."""
    b, p = task["battery"], task["prices"]
    n, s0, c, eta = b["soc_levels"], b["s0"], b["c_deg"], b["eta"]
    start = {"full": f"Starts full ({n}/{n}), so the first trade must be a sell.",
             "empty": f"Starts empty (0/{n}), so the first trade must be a buy.",
             "half": f"Starts at {s0}/{n}."}[start_state(task)]
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
    return (f"{start} Must end at >= {b['s_end_min']}/{n}; cycle cap {b['cycle_cap_units']} units sold.\n"
            f"Rule: a buy at b and a sell at s pay if {deg} > b. "
            f"Pairs: {'; '.join(items) if items else 'none pays today'}.\n"
            f"Plan: {'; '.join(plan) if plan else 'idle all day'}.\n"
            f"End check: ends at {s}/{n} vs >= {b['s_end_min']}/{n} required, {end}; "
            f"sold {sold} of {b['cycle_cap_units']} cap.")


def completion(task: dict, forecast) -> tuple[str, list[float], list[int]]:
    """(completion text, written forecast, DP plan on it)."""
    w = written(forecast)
    plan = dp_schedule(battery_of(task), w)
    call = json.dumps({"name": "submit_schedule", "arguments": {"actions": plan}})
    text = f"{forecast_line(w)}\n{rule_rationale(dict(task, prices=w), plan)}\n<tool_call>\n{call}\n</tool_call>"
    assert parse_forecast(text) == w
    return text, w, plan


def holdout(train: list[dict]) -> tuple[list[str], list[str]]:
    """N_HOLD_DATES seeded 2024 dates with blind tasks, up to PER_DATE blind tasks on each."""
    by: dict = {}
    for t in train:
        if t["date"] >= "2024-01-01" and t["tags"].get("blind_eval"):
            by.setdefault(t["date"], []).append(t)
    rng = random.Random(SEED + 2024)
    dates = sorted(rng.sample(sorted(by), N_HOLD_DATES))
    ids = [t["task_id"] for d in dates for t in rng.sample(by[d], min(PER_DATE, len(by[d])))]
    return dates, ids


def slim(t: dict, blind: dict) -> dict:
    f = t["refs"]["foresight"]
    return {**{k: t[k] for k in KEEP}, "blind": blind,
            "refs": {"foresight": {k: f[k] for k in ("p_idle", "p_opt", "opt")}, "blind": t["refs"].get("blind")}}


def main():
    teacher, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(teacher, "rt") as f:
        cross = json.load(f)["crossfit"]
    dam = cl.load_dam()
    train = load_pack("ercot-dam-v1-train")
    dates, hold_ids = holdout(train)
    (out / "holdout2024.json").write_text(json.dumps({"dates": dates, "task_ids": hold_ids}, indent=1) + "\n")
    rows, skipped = [], {"holdout_date": 0, "no_lags": 0, "no_teacher": 0}
    for t in train:
        if t["date"] in dates:
            skipped["holdout_date"] += 1
            continue
        blind = t["blind"] or bp.lags(dam, t["date"], t["settlement_point"])
        key = f"{t['date']}|{t['settlement_point']}"
        if blind is None:
            skipped["no_lags"] += 1
            continue
        if key not in cross:
            skipped["no_teacher"] += 1
            continue
        text, w, plan = completion(t, cross[key])
        rows.append({"task": slim(t, blind), "completion": text, "forecast": w, "plan": plan,
                     "cell": f"{t.get('curriculum', 'C0')}-{start_state(t)}"})
    cells: dict = {}
    for r in rows:
        cells.setdefault(r["cell"], []).append(r)
    rng = random.Random(SEED)
    queues = {c: rng.sample(v, len(v)) for c, v in sorted(cells.items())}
    order, keys = [], sorted(queues)
    while any(queues.values()):
        for c in rng.sample(keys, len(keys)):
            if queues[c]:
                order.append(queues[c].pop())
    with gzip.open(out / "sft_rows.jsonl.gz", "wt") as f:
        for r in order:
            f.write(json.dumps(r) + "\n")
    meta = {"rows": len(order), "skipped": skipped, "cells": {c: len(v) for c, v in sorted(cells.items())},
            "holdout_dates": len(dates), "holdout_tasks": len(hold_ids),
            "first_20000_cells": {c: sum(r["cell"] == c for r in order[:20000]) for c in keys},
            "first_1000_cells": {c: sum(r["cell"] == c for r in order[:1000]) for c in keys},
            "years": {y: sum(r["task"]["date"][:4] == y for r in order) for y in sorted({r["task"]["date"][:4]
                                                                                       for r in order})}}
    (out / "sft_meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(json.dumps(meta, indent=1))
    print(order[0]["completion"])


if __name__ == "__main__":
    main()
