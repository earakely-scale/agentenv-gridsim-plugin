"""The GridSim v1 SFT warm start: one row per train day of the bundle, in TRL's conversational prompt-completion form.
The prompt is the task's own system prompt and prompt, the completion a template rationale from the day's DP optimum
then the submit_schedule call with it, and `tools` the schemas GRPOTrainer renders for env.factory's methods, in its
order, so SFT trains on the context GRPO generates from. Usage: sft_data.py BUNDLE OUT.jsonl"""

import gzip
import inspect
import json
import sys
import tomllib
from pathlib import Path

from agent_env.training.trl import AgentEnv
from transformers.utils import get_json_schema

bundle, out = Path(sys.argv[1]), Path(sys.argv[2])


def money(p: float) -> str:
    return f"{'-' if p < 0 else ''}${abs(round(p))}"


def rationale(task: dict, opt: list[int]) -> str:
    """Start, end obligation, cycle cap, cheapest and dearest hours, then the plan with the SoC after each trade."""
    b, p = task["battery"], task["prices"]
    n, s = b["soc_levels"], b["s0"]
    start = (f"Starts empty (0/{n}), so the first trade must be a buy." if s == 0 else
             f"Starts full ({n}/{n}), so the first trade must be a sell." if s == n else f"Starts at {s}/{n}.")
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
    plan = "; ".join(segs) if segs else "stay idle"
    return (f"{start} Must end at >= {b['s_end_min']}/{n}; cycle cap {b['cycle_cap_units']} units sold. "
            f"Cheapest hours: {cheap}. Dearest: {dear}. Plan: {plan}. Ends at {s}/{n}.")


days = {}
for pack in (bundle / "envs/gridsim/packs/ercot-dam-v1-train").glob("*.jsonl.gz"):
    with gzip.open(pack, "rt") as f:
        days.update((row["task_id"], row) for row in map(json.loads, f))
train = tomllib.loads((bundle / "evals/train.toml").read_text())["tasks"]

env = AgentEnv.local(bundle, split="train", max_concurrent_envs=1)
methods = [function for name, function in inspect.getmembers(env.factory, predicate=inspect.isfunction)
           if name not in ("reset", "get_reward") and not name.startswith("_")]
tools = json.dumps([get_json_schema(method) for method in methods])
print("tools", [m.__name__ for m in methods], flush=True)

with out.open("w") as f:
    for name, row in zip(train, env.dataset, strict=True):
        assert row["task_id"].endswith("/" + name), (name, row["task_id"])
        task = days[name]
        opt = task["refs"]["foresight"]["opt"]
        f.write(json.dumps({
            "prompt": row["prompt"],
            "completion": [{"role": "assistant", "content": rationale(task, opt), "tool_calls": [
                {"type": "function", "function": {"name": "submit_schedule", "arguments": {"actions": opt}}}]}],
            "tools": tools,
            "chat_template_kwargs": {"enable_thinking": False},
            "task_id": name,
        }) + "\n")
env.close()
print("wrote", len(train), "rows to", out)
