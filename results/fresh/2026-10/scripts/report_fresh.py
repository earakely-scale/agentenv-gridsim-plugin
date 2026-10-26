"""Scoreboard tables for a fresh pack: python report_fresh.py TIER PACK RUNS_DIR OUT_DIR.

RUNS_DIR holds evaluate.py's eval_sft10k.json / eval_run3.json and sol_eval.py's sol-TIER.jsonl. Every schedule is
re-graded with gridsim_core. Writes OUT_DIR/summary.json, tables.md and per_day.png. CIs: a block bootstrap over days
(10,000 resamples, seed 0, task-weighted) and, labelled, the naive task bootstrap."""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

B, SEED, LIVE = 10_000, 0, "2026-10-27"
KINDS = ("ok", "all_idle", "overfill", "sell_before_charge", "end_short", "cycle_cap", "rate", "malformed",
         "truncated", "error")
NAMES = {"run3-sampled": "run 3 final, sampled", "run3-greedy": "run 3 final, greedy decoding",
         "sft10k-sampled": "SFT-10k, sampled", "sft10k-greedy": "SFT-10k, greedy decoding",
         "sol": "GPT-6.1 Sol (path B)",
         "greedy": "greedy rule", "threshold": "threshold rule", "clock": "clock rule", "anchor": "blind anchor",
         "ridge_dp": "ridge-DP", "persistence_dp": "persistence-DP", "greedy_d1": "greedy rule on D-1",
         "threshold_d1": "threshold rule on D-1"}


def main():
    tier, pack, runs, out = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    out.mkdir(parents=True, exist_ok=True)
    tasks = load_pack(pack)
    if tier == "blind":
        tasks = [t for t in tasks if t["tags"]["blind_eval"]]
    days = sorted({t["date"] for t in tasks})
    day = np.array([days.index(t["date"]) for t in tasks])
    models = rules(tasks, tier)
    for label in ("run3", "sft10k"):
        f = runs / f"eval_{label}.json"
        if f.exists():
            for run in json.loads(f.read_text())["runs"]:
                recs = {r["task_id"]: r for r in run["per_task"]}
                models[f"{label}-{run['decoding']}"] = from_actions(tasks, tier, recs)
    sol = runs / f"sol-{tier}.jsonl"
    if sol.exists():
        recs = {r["task_id"]: r for r in map(json.loads, sol.read_text().splitlines())}
        models["sol"] = from_actions(tasks, tier, recs)
        models["sol"]["usd"] = round(sum(r.get("usd", 0.0) for r in recs.values()), 4)
        models["sol"]["usage"] = {k: int(sum((r.get("usage") or {}).get(k, 0) for r in recs.values()))
                                  for k in ("input", "output", "reasoning", "cached")}
    head = "c" if tier == "blind" else "r"
    base = "anchor" if tier == "blind" else "greedy"
    summ = {"tier": tier, "pack": pack, "n_tasks": len(tasks), "days": days, "metric": head,
            "bootstrap": {"resamples": B, "seed": SEED, "unit": "day (block), task-weighted; naive: task"},
            "models": {}}
    for name, m in models.items():
        summ["models"][name] = describe(m, tasks, day, days, head)
    pairs = gaps(tier, models)
    summ["paired"] = {f"{a} - {b}": paired(models, a, b, day, days, head, tasks) for a, b in pairs if
                      a in models and b in models}
    if tier == "blind":
        summ["vs_anchor"] = {f"{k} - anchor": paired(models, k, "anchor", day, days, "c", tasks) for k in models
                             if k not in ("anchor", "sol")}
    else:
        d1 = np.array([t["tags"].get("draw") == 1 for t in tasks])
        summ["draw1"] = {k: round(float(np.mean([x for x, t, s in zip(m["r"], tasks, d1, strict=True)
                                                  if s and t["task_id"] not in set(m.get("missing", []))])), 4)
                         for k, m in models.items()}
        summ["draw1_n"] = int(d1.sum())
    summ["by_start"] = {k: start_means(m, tasks, head) for k, m in models.items()}
    (out / "summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    (out / "tables.md").write_text(tables(summ, base) + "\n")
    chart(summ, out / "per_day.png", tier)
    print(tables(summ, base))


def rules(tasks: list, tier: str) -> dict:
    out = {}
    if tier == "foresight":
        for k in ("greedy", "threshold", "clock"):
            r = [t["refs"]["foresight"]["baselines"][k]["reward"] for t in tasks]
            out[k] = {"r": r, "c": r, "valid": [True] * len(r), "kind": [None] * len(r)}
        return out
    out["anchor"] = {"c": [t["refs"]["blind"]["r_opt_anchor"] for t in tasks], "r": [1.0] * len(tasks),
                     "valid": [True] * len(tasks), "kind": [None] * len(tasks), "beats": [False] * len(tasks)}
    for k in ("ridge_dp", "persistence_dp", "greedy_d1", "threshold_d1"):
        rs = [t["refs"]["blind"]["rules"][k] for t in tasks]
        out[k] = {"c": [x["c"] for x in rs], "r": [x["reward"] for x in rs], "valid": [True] * len(rs),
                  "kind": [None] * len(rs),
                  "beats": [x["profit"] > t["refs"]["blind"]["p_anchor"] + 1e-9
                            for x, t in zip(rs, tasks, strict=True)]}
    return out


def from_actions(tasks: list, tier: str, recs: dict) -> dict:
    m = {"r": [], "c": [], "valid": [], "kind": [], "beats": [], "missing": []}
    for t in tasks:
        r = recs.get(t["task_id"])
        if r is None:
            m["missing"].append(t["task_id"])
        acts = r and r.get("actions")
        g = grade(t, acts, tier) if acts is not None else None
        if g and abs(g["reward"] - r["reward"]) > 1e-6:
            raise ValueError(f"regrade mismatch on {t['task_id']}: {g['reward']} vs {r['reward']}")
        m["r"].append(g["reward"] if g else 0.0)
        m["c"].append(g["r_opt"] if g else 0.0)
        m["valid"].append(bool(g))
        m["kind"].append(r["kind"] if r else "error")
        m["beats"].append(bool(g and g.get("beats_anchor")))
    return m


def boot_day(x: np.ndarray, day: np.ndarray, nd: int) -> list[float]:
    day = np.unique(day, return_inverse=True)[1]
    nd = int(day.max()) + 1
    sums, cnt = np.bincount(day, x, nd), np.bincount(day, None, nd)
    idx = np.random.default_rng(SEED).integers(0, nd, (B, nd))
    m = sums[idx].sum(1) / cnt[idx].sum(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def boot_task(x: np.ndarray) -> list[float]:
    m = x[np.random.default_rng(SEED).integers(0, len(x), (B, len(x)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def describe(m: dict, tasks: list, day: np.ndarray, days: list, head: str) -> dict:
    miss = set(m.get("missing", []))
    keep = np.array([t["task_id"] not in miss for t in tasks])
    x, day, n = np.asarray(m[head], float)[keep], day[keep], int(keep.sum())
    live = day == days.index(LIVE)
    out = {"n": n, "mean": round(float(x.mean()), 4), "ci_day": boot_day(x, day, len(days)), "ci_task": boot_task(x),
           "per_day": {d: round(float(x[day == i].mean()), 4) for i, d in enumerate(days)},
           "live_day": {"n": int(live.sum()), "mean": round(float(x[live].mean()), 4), "ci_task": boot_task(x[live])}}
    if head == "c":
        r = np.asarray(m["r"], float)[keep]
        out["r_anchor"] = {"mean": round(float(r.mean()), 4), "ci_day": boot_day(r, day, len(days))}
        out["live_day"]["r_anchor"] = round(float(r[live].mean()), 4)
        out["beats_anchor"] = round(float(np.asarray(m["beats"])[keep].mean()), 4)
    if any(k is not None for k in m["kind"]):
        kinds = [k for k, ok in zip(m["kind"], keep, strict=True) if ok]
        out["valid"] = round(float(np.asarray(m["valid"])[keep].mean()), 4)
        out["errors"] = {k: round(sum(x == k for x in kinds) / n, 4) for k in KINDS}
        out["missing"] = m.get("missing", [])
    for k in ("usd", "usage"):
        if k in m:
            out[k] = m[k]
    return out


def gaps(tier: str, models: dict) -> list[tuple[str, str]]:
    out = []
    for dec in ("sampled", "greedy"):
        r3, sft = f"run3-{dec}", f"sft10k-{dec}"
        if tier == "foresight":
            out += [(r3, "greedy"), (r3, sft), (r3, "sol"), (sft, "greedy"), (r3, "threshold")]
        else:
            out += [(r3, "sol"), (sft, "sol"), (r3, sft)]
    return out + ([("sol", "anchor")] if tier == "blind" else [("sol", "greedy")])


def paired(models: dict, a: str, b: str, day: np.ndarray, days: list, head: str, tasks: list) -> dict:
    keep = np.ones(len(tasks), bool)
    for k in (a, b):
        miss = set(models[k].get("missing", []))
        keep &= np.array([t["task_id"] not in miss for t in tasks])
    x = (np.asarray(models[a][head], float) - np.asarray(models[b][head], float))[keep]
    d = day[keep]
    live = d == days.index(LIVE)
    ci = boot_day(x, d, len(days))
    return {"n": int(keep.sum()), "mean": round(float(x.mean()), 4), "ci_day": ci, "ci_task": boot_task(x),
            "shown": "above 0" if ci[0] > 0 else "below 0" if ci[1] < 0 else "not shown",
            "wins": round(float((x > 1e-9).mean()), 4), "ties": round(float((np.abs(x) <= 1e-9).mean()), 4),
            "days_ahead": int(sum(x[d == i].mean() > 0 for i in range(len(days)) if (d == i).any())),
            "live_day": {"n": int(live.sum()), "mean": round(float(x[live].mean()), 4), "ci_task": boot_task(x[live])}}


def start_means(m: dict, tasks: list, head: str) -> dict:
    out, miss = {}, set(m.get("missing", []))
    for s in ("empty", "half", "full"):
        sel = [x for x, t in zip(m[head], tasks, strict=True) if _start(t) == s and t["task_id"] not in miss]
        out[s] = {"n": len(sel), "mean": round(float(np.mean(sel)), 4)}
    return out


def _start(t: dict) -> str:
    b = t["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def tables(s: dict, base: str) -> str:
    head = "C (hindsight capture)" if s["metric"] == "c" else "mean R"
    cols = ["model", head, "day-block 95% CI", "naive task CI"] + (
        ["R (anchor scale)", "beats anchor"] if s["metric"] == "c" else []) + [s["days"][-1], "valid"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for k, m in s["models"].items():
        extra = f"{m['r_anchor']['mean']:.3f} | {m['beats_anchor']:.1%} | " if s["metric"] == "c" else ""
        lines.append(f"| {NAMES.get(k, k)} | {m['mean']:.3f} | [{m['ci_day'][0]:.3f}, {m['ci_day'][1]:.3f}] | "
                     f"[{m['ci_task'][0]:.3f}, {m['ci_task'][1]:.3f}] | {extra}{m['live_day']['mean']:.3f} | "
                     f"{m.get('valid', 1.0):.1%} |")
    lines += ["", "| paired gap | mean | day-block 95% CI | shown? | naive task CI | days ahead | "
              f"{s['days'][-1]} (n) |", "|---|---|---|---|---|---|---|"]
    for k, p in {**s["paired"], **s.get("vs_anchor", {})}.items():
        a, b = k.split(" - ")
        lines.append(f"| {NAMES.get(a, a)} − {NAMES.get(b, b)} | {p['mean']:+.3f} | [{p['ci_day'][0]:+.3f}, "
                     f"{p['ci_day'][1]:+.3f}] | {p['shown']} | [{p['ci_task'][0]:+.3f}, {p['ci_task'][1]:+.3f}] | "
                     f"{p['days_ahead']}/{len(s['days'])} | {p['live_day']['mean']:+.3f} ({p['live_day']['n']}) |")
    lines += ["", "| model | valid | " + " | ".join(KINDS[1:]) + " |", "|---" * (len(KINDS) + 1) + "|"]
    for k, m in s["models"].items():
        if "errors" in m:
            lines.append(f"| {NAMES.get(k, k)} | {m['valid']:.1%} | " + " | ".join(
                f"{m['errors'][e]:.1%}" for e in KINDS[1:]) + " |")
    lines += ["", "| model | " + " | ".join(s["days"]) + " |", "|---" * (len(s["days"]) + 1) + "|"]
    for k, m in s["models"].items():
        lines.append(f"| {NAMES.get(k, k)} | " + " | ".join(f"{m['per_day'][d]:.3f}" for d in s["days"]) + " |")
    return "\n".join(lines)


def chart(s: dict, path: Path, tier: str):
    show = [k for k in ("sol", "anchor", "run3-sampled", "sft10k-sampled", "ridge_dp", "persistence_dp", "threshold",
                        "greedy", "greedy_d1", "threshold_d1") if k in s["models"]]
    colors = {"sol": "#6b4fbb", "anchor": "#222222", "run3-sampled": "#d1495b", "sft10k-sampled": "#edae49",
              "ridge_dp": "#00798c", "persistence_dp": "#66a182", "threshold": "#8d96a3", "greedy": "#30638e",
              "greedy_d1": "#30638e", "threshold_d1": "#8d96a3"}
    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=150)
    x = np.arange(len(s["days"]))
    for k in show:
        y = [s["models"][k]["per_day"][d] for d in s["days"]]
        ax.plot(x, y, marker="o", lw=2 if k in ("run3-sampled", "sol", "anchor") else 1.2, color=colors[k],
                label=f"{NAMES[k]} ({s['models'][k]['mean']:.3f})")
    ax.axvspan(len(x) - 1.5, len(x) - 0.5, color="#f2e8cf", zorder=0)
    ax.text(len(x) - 1, 0.03, "not yet\nhappened", ha="center", fontsize=8, color="#7a6a3a")
    ax.set_xticks(x, [d[5:] for d in s["days"]])
    ax.set_ylim(0, 1.04)
    ax.set_ylabel("hindsight capture C" if tier == "blind" else "mean R (foresight)")
    ax.set_title(f"GridSimEnv v1, fresh ERCOT days, {tier} tier: per-day means ({s['n_tasks']} tasks)", fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, loc="lower left", ncol=2)
    fig.tight_layout()
    fig.savefig(path)


if __name__ == "__main__":
    main()
