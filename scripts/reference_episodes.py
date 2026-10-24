"""Reference episodes for the viewer, written with gridsim_core: the DP optimum, greedy, threshold and a deliberately
flawed plan (practice checks, then a submission that truncates or ends short) on chosen days, and the persistence-DP
plan on blind showcase days, as gridsim.episode/v1 JSON.

usage: python scripts/reference_episodes.py [--out results/runs/reference] [--tasks ID ...]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core.episode import check_result, submit_result, to_episode_json  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

PACKS = ("ercot-dam-v1-eval", "showcase", "ercot-dam-v1-train")
TASKS = {
    "dam-v1-2025-03-15-HB_WEST-1h-t": ("opt", "greedy", "threshold", "flawed"),
    "dam-v1-2024-04-10-HB_WEST-1h-q": ("opt", "short"),
    "dam-v1-2022-03-30-HB_WEST-2h-e": ("opt", "greedy", "threshold"),
    "dam-v1-2025-05-14-HB_PAN-1h-c": ("opt", "greedy", "flawed"),
    "dam-v1-2023-08-26-LZ_HOUSTON-2h-j": ("opt", "greedy", "threshold", "flawed"),
    "dam-v1-2025-10-21-HB_HOUSTON-2h-p": ("opt", "threshold"),
    "dam-v1-2025-02-20-LZ_NORTH-1h-v": ("opt", "greedy", "flawed"),
    "dam-v1-2021-02-15-HB_NORTH-4h-f": ("opt", "persist"),
    "dam-v1-2025-07-29-LZ_CPS-2h-o": ("opt", "greedy", "threshold"),
    "dam-v1-2025-08-11-LZ_AEN-4h-v": ("opt", "greedy", "flawed"),
    "dam-v1-2021-02-14-HB_WEST-2h-p": ("persist", "opt"),
}
MODELS = {"opt": "reference/dp-optimum", "greedy": "reference/greedy", "threshold": "reference/threshold",
          "flawed": "reference/flawed-plan", "short": "reference/flawed-plan", "persist": "reference/persistence-dp"}
SAY = {
    "opt": "The exact optimum: dynamic programming over every state of charge and every hour, settled on the day's "
           "real prices.",
    "greedy": "Greedy baseline: buy in the cheapest hours and sell in the dearest, pairing them in price order while "
              "the battery's limits allow.",
    "threshold": "Threshold baseline: charge when the price is below the day's lower band and discharge above the "
                 "upper band.",
    "flawed": "Morning prices are climbing, so I'll sell at full power into the morning ramp first and refill from "
              "the cheap midday hours, then sell again into the evening peak.",
    "short": "The evening peak is the prize: I'll charge at midday, sell everything into the evening and skip the "
             "late-night top-up, since prices then are not worth buying.",
    "persist": "Blind: tomorrow's prices are unknown, so plan on yesterday's curve (persistence) with the exact "
               "optimiser and settle on the real day.",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "reference")
    p.add_argument("--tasks", nargs="*")
    args = p.parse_args(argv)
    wanted = {t: TASKS.get(t, ("opt", "greedy", "threshold")) for t in (args.tasks or TASKS)}
    tasks = {}
    for pack in PACKS:
        for t in load_pack(pack):
            if t["task_id"] in wanted and t["task_id"] not in tasks:
                tasks[t["task_id"]] = t
        if len(tasks) == len(wanted):
            break
    args.out.mkdir(parents=True, exist_ok=True)
    for tid, kinds in wanted.items():
        task = tasks.get(tid)
        if task is None:
            print(f"missing {tid}")
            continue
        for kind in kinds:
            ep = episode(task, kind)
            if ep is None:
                continue
            name = f"{tid}-{ep['tier']}-{kind}.json"
            (args.out / name).write_text(json.dumps(ep, separators=(",", ":")))
            print(f"{name}: reward {ep['reward']}, profit {ep['profit_usd']:.0f}, truncated {ep['truncated_at']}")
    return 0


def episode(task: dict, kind: str) -> dict | None:
    f = task["refs"]["foresight"]
    tier, steps = "foresight", None
    if kind == "opt":
        acts = f["opt"]
    elif kind in ("greedy", "threshold"):
        acts = f["baselines"][kind]["schedule"]
    elif kind == "persist":
        if not task["refs"].get("blind"):
            return None
        acts, tier = task["refs"]["blind"]["persist"], "blind"
    else:
        acts = flawed(task) if kind == "flawed" else short(task)
        practice = [f["baselines"]["threshold"]["schedule"], nudge(f["opt"])]
        steps = [{"t": i, "tool": "check_schedule", "args": {"actions": a}, "output": check_result(task, a, 2 - i)}
                 for i, a in enumerate(practice)]
        steps.append({"t": len(steps), "tool": "submit_schedule", "args": {"actions": acts},
                      "output": submit_result(task, acts)})
    ep = to_episode_json(task, acts, tier, 3 if steps else 0, steps=steps, bundle="reference", path="ref",
                         model=MODELS[kind], messages=[{"role": "assistant", "content": SAY[kind]}],
                         episode_id=f"{task['task_id']}-{tier}-{kind}")
    return ep


def flawed(task: dict) -> list[int]:
    """The optimum with a full-power sale in the morning before the battery holds enough: truncates there."""
    b, opt = task["battery"], list(task["refs"]["foresight"]["opt"])
    soc = simulate(task, opt)["soc_path"]
    for h in range(5, 15):
        if soc[h] < b["k_dis"] and opt[h] <= 0:
            out = list(opt)
            out[h] = b["k_dis"]
            return out
    out = list(opt)
    out[7] = b["k_dis"] + 1
    return out


def short(task: dict) -> list[int]:
    """The optimum selling one more unit into its dearest hours where that still settles: it ends below the required
    charge and pays the shortfall penalty."""
    opt = task["refs"]["foresight"]["opt"]
    for h in sorted(range(24), key=lambda i: -task["prices"][i]):
        for extra in (1, 2):
            out = list(opt)
            out[h] += extra
            sim = simulate(task, out)
            if sim["feasible"] and sim["end_shortfall_units"] > 0:
                return out
    return flawed(task)


def nudge(opt: list[int]) -> list[int]:
    out = list(opt)
    h = max(range(24), key=lambda i: out[i])
    if out[h] > 0:
        out[h] -= 1
    return out


if __name__ == "__main__":
    sys.exit(main())
