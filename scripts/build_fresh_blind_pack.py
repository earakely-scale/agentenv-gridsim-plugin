"""The blind tier of a fresh pack: python scripts/build_fresh_blind_pack.py ercot-dam-v1-fresh-2026-10.

Keeps the tasks build_pack's rule marks blind (`tags.blind_eval`: D-7..D-1 history present and the blind anchor clears
the low-spread margin), rows unchanged, and adds `refs.blind.rules`: the greedy and threshold rules run on D-1's prices
(the most the blind tier shows of the day's shape), settled on the day. Each rule and reference also gets its hindsight
capture C (R against P_opt) and its R on the blind anchor's scale."""

import gzip
import hashlib
import json
import sys

import numpy as np

from gridsim_core import baselines
from gridsim_core.grade import reward_value
from gridsim_core.physics import simulate
from gridsim_core.task import data_root, load_pack


def rule(task: dict, name: str) -> dict:
    sched = getattr(baselines, name)(dict(task, prices=task["blind"]["dam_prev_day"]))
    return score(task, sched)


def score(task: dict, sched: list[int]) -> dict:
    f, b = task["refs"]["foresight"], task["refs"]["blind"]
    p = simulate(task, sched)["profit_usd"]
    return {"profit": round(p, 6), "reward": reward_value(p, f["p_idle"], b["p_anchor"]),
            "c": reward_value(p, f["p_idle"], f["p_opt"]), "schedule": sched}


def main():
    src = sys.argv[1]
    name = f"{src}-blind"
    out = data_root() / name
    out.mkdir(parents=True, exist_ok=True)
    tasks = []
    for t in load_pack(src):
        if not t["tags"]["blind_eval"]:
            continue
        b, f = t["refs"]["blind"], t["refs"]["foresight"]
        b["rules"] = {"greedy_d1": rule(t, "greedy"), "threshold_d1": rule(t, "threshold"),
                      "persistence_dp": score(t, b["persist"]), "ridge_dp": score(t, b["ridge"]),
                      "hindsight_dp": score(t, f["opt"]), "idle": score(t, baselines.idle(t))}
        t["pack"] = name
        tasks.append(t)
    with gzip.GzipFile(out / "tasks.jsonl.gz", "wb", mtime=0) as fh:
        for t in tasks:
            fh.write((json.dumps(t, separators=(",", ":")) + "\n").encode())
    means = {k: {"c": round(float(np.mean([t["refs"]["blind"]["rules"][k]["c"] for t in tasks])), 4),
                 "r_anchor": round(float(np.mean([t["refs"]["blind"]["rules"][k]["reward"] for t in tasks])), 4)}
             for k in tasks[0]["refs"]["blind"]["rules"]}
    means["anchor"] = {"c": round(float(np.mean([t["refs"]["blind"]["r_opt_anchor"] for t in tasks])), 4),
                       "r_anchor": 1.0}
    manifest = {"pack": name, "source_pack": src, "tier": "blind", "count": len(tasks),
                "by_date": {d: sum(t["date"] == d for t in tasks) for d in sorted({t["date"] for t in tasks})},
                "rule": "tasks of the source pack with tags.blind_eval (build_pack's blind_ok)",
                "references": "refs.blind: p_persist, p_ridge (data/ridge-v1.json), p_anchor = max; refs.blind.rules: "
                              "greedy_d1 / threshold_d1 (the rule on D-1 prices, settled on D), persistence_dp, "
                              "ridge_dp, hindsight_dp (C = 1), idle; c = R against P_opt, reward = R against P_anchor",
                "means": means,
                "tasks_sha256": hashlib.sha256((out / "tasks.jsonl.gz").read_bytes()).hexdigest(),
                "build_command": "python scripts/build_fresh_blind_pack.py " + src}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps({k: manifest[k] for k in ("count", "by_date", "means")}))


if __name__ == "__main__":
    main()
