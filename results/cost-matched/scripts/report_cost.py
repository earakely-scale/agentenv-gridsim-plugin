"""The cost-matched contest's report: the trained 4Bs, GPT-6 Luna and GPT-6.1 Sol on four packs, every schedule
re-graded with gridsim_core; day-block CIs and paired gaps with report_blind.py's own boot / paired; cost per task.

PYTHONPATH=src python report_cost.py   (reads the committed eval files and results/cost-matched/luna/, writes
results/cost-matched/summary.json, tables.md and score_vs_cost.png)"""

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

OUT = ROOT / "results" / "cost-matched"
G5_GPU, G6E = 5.672 / 4, 4.52856  # USD/h: one A10G of a g5.12xlarge (us-east-1); a g6e.8xlarge, 1x L40S (us-west-2)
PACKS = {
    "foresight-eval2025": {"title": "1. Foresight, eval-2025", "tier": "foresight", "pack": "ercot-dam-v1-eval",
                           "fourb": ("results/train/4b-dpa/eval_trained.json", None), "rate": G5_GPU,
                           "fourb_name": "run 3 final", "box": "g5.12xlarge, 1 of 4 A10G"},
    "foresight-fresh": {"title": "2. Foresight, fresh 10-18..27", "tier": "foresight",
                        "pack": "ercot-dam-v1-fresh-2026-10", "fourb": ("results/fresh/2026-10/eval_run3.json", None),
                        "rate": G5_GPU, "fourb_name": "run 3 final", "box": "g5.12xlarge, 1 of 4 A10G",
                        "sol": "results/fresh/2026-10/eval_sol.jsonl.gz"},
    "blind-eval2025": {"title": "3a. Blind, eval-2025", "tier": "blind", "pack": "ercot-dam-v1-eval",
                       "fourb": ("results/train/4b-blind/eval_final.json", "eval2025"), "rate": G6E,
                       "fourb_name": "run 4 final", "box": "g6e.8xlarge, 1x L40S",
                       "sol": "results/train/4b-blind/sol/sol-ercot-dam-v1-eval.jsonl.gz"},
    "blind-fresh": {"title": "3b. Blind, fresh 10-18..27", "tier": "blind", "pack": "ercot-dam-v1-fresh-2026-10-blind",
                    "fourb": ("results/train/4b-blind/eval_final.json", "fresh"), "rate": G6E,
                    "fourb_name": "run 4 final", "box": "g6e.8xlarge, 1x L40S",
                    "sol": "results/train/4b-blind/sol/sol-ercot-dam-v1-fresh-2026-10-blind.jsonl.gz"},
}
BOARD = ("results/runs/v1-board-sol-oneshot", "results/runs/v1-board-sol-oneshot-amend")
NAMES = {"4b-sampled": "trained 4B, sampled", "4b-greedy": "trained 4B, greedy decoding",
         "luna-high": "GPT-6 Luna, effort high", "luna-low": "GPT-6 Luna, effort low",
         "sol": "GPT-6.1 Sol, effort high"}
KINDS = ("ok", "all_idle", "overfill", "sell_before_charge", "end_short", "cycle_cap", "rate", "malformed",
         "truncated", "error")
INVALID = ("malformed", "truncated", "error")
MIX = ("invalid", "overfill", "sell_before_charge", "end_short", "all_idle", "rate", "cycle_cap")


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RB = load("report_blind", "results/train/4b-blind/scripts/report_blind.py")
KIND_OF = load("pathb", "results/fresh/2026-10/scripts/pathb.py").kind_of


def tasks_of(key: str) -> list[dict]:
    p = PACKS[key]
    tasks = load_pack(p["pack"])
    if p["tier"] == "blind":
        return [t for t in tasks if t["tags"]["blind_eval"]]
    if key == "foresight-eval2025":
        by = {t["task_id"]: t for t in tasks}
        return [by[i] for i in json.loads((ROOT / p["fourb"][0]).read_text())["task_ids"]]
    return tasks


def jsonl(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def regrade(tasks: list[dict], tier: str, recs: dict, score_key: str) -> dict:
    """Per task: score (R on foresight, C = r_opt on blind; 0 with no valid schedule), R on the anchor's scale and the
    error kind, re-graded from the schedule and checked against the record."""
    out = {"score": [], "r": [], "kind": [], "feasible": [], "ran": []}
    for t in tasks:
        r = recs.get(t["task_id"])
        out["ran"].append(r is not None)
        acts = (r or {}).get("actions")
        g = grade(t, acts, tier) if acts is not None else None
        s = (g["r_opt"] if tier == "blind" else g["reward"]) if g else 0.0
        if r is not None and abs(s - (r.get(score_key) or 0.0)) > 1e-6:
            raise ValueError(f"regrade mismatch on {t['task_id']}: {s} vs {r.get(score_key)}")
        out["score"].append(s)
        out["r"].append(g["reward"] if g else 0.0)
        out["feasible"].append(bool(g and g["feasible"]))
        out["kind"].append(KIND_OF(g, acts) if g else (r or {}).get("kind", "error"))
    return {k: np.array(v) for k, v in out.items()}


def models_for(key: str, tasks: list[dict]) -> dict:
    p, tier = PACKS[key], PACKS[key]["tier"]
    sk = "c" if tier == "blind" else "reward"
    f, pack = p["fourb"]
    ev = json.loads((ROOT / f).read_text())
    m = {}
    for run in ev["runs"]:
        if pack and run.get("pack") != pack:
            continue
        recs = {r["task_id"]: r for r in run["per_task"]}
        m[f"4b-{run['decoding']}"] = regrade(tasks, tier, recs, sk) | {
            "wall_s": run["wall_s"], "usd_task": run["wall_s"] * p["rate"] / 3600 / len(tasks),
            "out_tokens": float(np.mean([r["len"] for r in run["per_task"]]))}
    if key == "foresight-eval2025":
        sol = {}
        for d in BOARD:
            for f in sorted((ROOT / d).glob("*.json")):
                e = json.loads(f.read_text())
                u = e["usage"]
                sol[e["task_id"]] = {"reward": e["reward"], "actions": e["final_schedule"], "usd": u["usd"],
                                     "usage": {"input": u["input_tokens"], "output": u["output_tokens"]}}
    else:
        sol = {r["task_id"]: r for r in jsonl(ROOT / p["sol"])}
    luna = {}
    for effort in ("high", "low"):
        path = OUT / "luna" / f"luna-{key}-{effort}.jsonl.gz"
        if path.exists():
            luna[f"luna-{effort}"] = {r["task_id"]: r for r in jsonl(path)}
    for name, recs in {"sol": sol, **luna}.items():
        recs = {t["task_id"]: recs[t["task_id"]] for t in tasks if t["task_id"] in recs}
        rows = list(recs.values())
        m[name] = regrade(tasks, tier, recs, sk) | {
            "usd_task": float(np.mean([r["usd"] for r in rows])), "usd_total": float(sum(r["usd"] for r in rows)),
            "out_tokens": float(np.mean([(r.get("usage") or {}).get("output", 0) for r in rows])),
            "in_tokens": float(np.mean([(r.get("usage") or {}).get("input", 0) for r in rows])),
            "reasoning_tokens": float(np.mean([(r.get("usage") or {}).get("reasoning", 0) for r in rows])),
            "infra_retries": int(sum(max(0, r.get("attempts", 1) - 1) for r in rows)),
            "infra_failed": [r["task_id"] for r in rows if r.get("kind") == "error"],
            "wall_s_median": float(np.median([r.get("wall_s") or 0 for r in rows]))}
    return m


def describe(m: dict, days: np.ndarray, tier: str) -> dict:
    ran = m["ran"]
    s, d = m["score"][ran], days[ran]
    out = {"n": int(ran.sum()), "unrun": int((~ran).sum()), "score": RB.boot(s, d)}
    if tier == "foresight":
        out["x"] = RB.boot((s - 0.2) / 0.8, d)
    else:
        out["r_anchor"] = RB.boot(m["r"][ran], d)
    k = m["kind"][ran]
    out["valid"] = round(float(np.isin(k, INVALID, invert=True).mean()), 4)
    out["feasible"] = round(float(m["feasible"][ran].mean()), 4)
    out["mix"] = {x: round(float((np.isin(k, INVALID) if x == "invalid" else k == x).mean()), 4) for x in MIX}
    out["kinds"] = {x: int((k == x).sum()) for x in KINDS if (k == x).any()}
    out |= {x: (round(m[x], 8) if isinstance(m[x], float) else m[x]) for x in
            ("usd_task", "usd_total", "wall_s", "out_tokens", "in_tokens", "reasoning_tokens", "infra_retries",
             "infra_failed", "wall_s_median") if x in m}
    return out


def gap(a: dict, b: dict, days: np.ndarray) -> dict:
    both = a["ran"] & b["ran"]
    g = RB.paired(a["score"][both], b["score"][both], days[both])
    return g | {"shown": "above 0" if g["ci"][0] > 0 else "below 0" if g["ci"][1] < 0 else "not shown",
                "n_days": int(len(np.unique(days[both])))}


def verdict(g: dict) -> str:
    return {"above 0": "4B ahead", "below 0": "Luna ahead"}.get(g["shown"], "not separated")


def main():
    summ = {"metric": {"foresight": "R (= r_opt on foresight); x = (R - 0.2) / 0.8 also given",
                       "blind": "C = r_opt (hindsight capture); R on the blind anchor's scale also given",
                       "invalid": "0 (no valid submit_schedule; not retried)"},
            "bootstrap": "day-block, 10,000 resamples, seed 0, task-weighted (report_blind.boot / paired)",
            "prices_usd_per_m_tokens": {"openai/gpt-6-luna": [0.10, 0.50, 0.01],
                                        "openai/gpt-6.1-sol": [2.00, 10.00, 0.10]},
            "gpu_usd_per_h": {"A10G (1 of 4 on a g5.12xlarge, us-east-1, $5.672/h)": round(G5_GPU, 4),
                              "L40S (g6e.8xlarge, us-west-2)": G6E},
            "gpu_assumption": "busy GPU: billed only for the logged batched-generation wall time (wall_s), on-demand "
                              "Linux; engine start, model load and idle time not charged",
            "packs": {}}
    for key, p in PACKS.items():
        tasks = tasks_of(key)
        days = np.array([t["date"] for t in tasks])
        m = models_for(key, tasks)
        res = {"title": p["title"], "tier": p["tier"], "pack": p["pack"], "n_tasks": len(tasks),
               "n_days": int(len(np.unique(days))), "fourb": p["fourb_name"], "fourb_box": p["box"],
               "models": {k: describe(v, days, p["tier"]) for k, v in m.items()}, "gaps": {}}
        res["models"]["4b-sampled"]["usd_task_whole_box"] = (
            res["models"]["4b-sampled"]["usd_task"] * (4 if p["rate"] == G5_GPU else 1))
        pairs = [("4b-sampled", "luna-high"), ("4b-greedy", "luna-high"), ("4b-sampled", "luna-low"),
                 ("4b-greedy", "luna-low"), ("4b-sampled", "sol"), ("4b-greedy", "sol"), ("luna-high", "sol"),
                 ("luna-low", "sol"), ("luna-low", "luna-high")]
        for a, b in pairs:
            if a in m and b in m:
                res["gaps"][f"{a} - {b}"] = gap(m[a], m[b], days)
        if "4b-sampled - luna-high" in res["gaps"]:
            g = res["gaps"]["4b-sampled - luna-high"]
            res["headline"] = {"test": "4B (sampled) - Luna (high), day-block 95% CI wholly above 0",
                               "verdict": verdict(g), "met": g["shown"] == "above 0"}
        if "luna-high" in m:
            ratio = res["models"]["luna-high"]["usd_task"] / res["models"]["4b-sampled"]["usd_task"]
            res["luna_high_cost_ratio_to_4b"] = round(ratio, 2)
            res["secondary_triggered"] = ratio > 3
        summ["packs"][key] = res
    luna = [r for p in (OUT / "luna").glob("luna-*.jsonl.gz") if "episodes" not in p.name for r in jsonl(p)]
    summ["luna_spend_usd"] = {"total": round(sum(r["usd"] for r in luna), 4),
                              "by_file": {p.name: round(sum(r["usd"] for r in jsonl(p)), 4)
                                          for p in sorted((OUT / "luna").glob("luna-*.jsonl.gz"))
                                          if "episodes" not in p.name}}
    summ["training_gpu_usd"] = {"run 3": 31, "run 4": 40}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    (OUT / "tables.md").write_text(tables(summ))
    chart(summ, OUT / "score_vs_cost.png")
    print(tables(summ))


def f3(v):
    return f"{v:.3f}"


def ci(b):
    return f"[{b['ci'][0]:.3f}, {b['ci'][1]:.3f}]"


def sgn(b):
    return f"{b['mean']:+.3f} [{b['ci'][0]:+.3f}, {b['ci'][1]:+.3f}]".replace("-", "−")


def usd(v):
    return f"${v:.4f}" if v >= 0.001 else f"${v:.5f}"


def tables(s: dict) -> str:
    out = []
    for p in s["packs"].values():
        fore = p["tier"] == "foresight"
        out.append(f"### {p['title']} ({p['n_tasks']} tasks, {p['n_days']} days; the 4B is {p['fourb']})\n")
        head = ("| model | R | 95% CI | x = (R − 0.2)/0.8 | " if fore else "| model | C | 95% CI | R (anchor scale) | ")
        out.append(head + "valid | feasible | cost per task | output tokens per task |")
        out.append("|---|---|---|---|---|---|---|---|")
        for name in ("4b-sampled", "4b-greedy", "luna-high", "luna-low", "sol"):
            if name not in p["models"]:
                continue
            m = p["models"][name]
            sec = m["x"]["mean"] if fore else m["r_anchor"]["mean"]
            bold = name in ("4b-sampled", "luna-high")
            nm = f"**{NAMES[name]}**" if bold else NAMES[name]
            sc = f"**{f3(m['score']['mean'])}**" if bold else f3(m["score"]["mean"])
            out.append(f"| {nm} | {sc} | {ci(m['score'])} | {f3(sec)} | {m['valid']:.1%} | {m['feasible']:.1%} | "
                       f"{usd(m['usd_task'])} | {m['out_tokens']:,.0f} |")
        out.append("\n| paired gap | mean [day-block 95% CI] | shown | 4B or first model ahead / level | days ahead |")
        out.append("|---|---|---|---|---|")
        for g, v in p["gaps"].items():
            a, b = g.split(" - ")
            label = f"{NAMES[a]} − {NAMES[b]}"
            label = f"**{label}**" if g == "4b-sampled - luna-high" else label
            out.append(f"| {label} | {sgn(v)} | {v['shown']} | {v['ahead']:.0%} / {v['level']:.0%} | "
                       f"{v['days_ahead']}/{v['n_days']} |")
        out.append("")
    out.append("### Error mix (share of tasks)\n")
    out.append("| pack | model | invalid or no submit | overfill | sell before charge | end short | all idle | rate | "
               "cycle cap |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for p in s["packs"].values():
        for name in ("4b-sampled", "luna-high", "luna-low", "sol"):
            if name in p["models"]:
                x = p["models"][name]["mix"]
                out.append(f"| {p['title']} | {NAMES[name]} | " + " | ".join(f"{x[k]:.1%}" for k in MIX) + " |")
    return "\n".join(out) + "\n"


def chart(s: dict, path: Path):
    ink, muted, grid, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    style = {"4b-sampled": ("#2a78d6", "o", "trained 4B (sampled)", True),
             "luna-high": ("#1baf7a", "s", "GPT-6 Luna, high", True),
             "luna-low": ("#1baf7a", "s", "GPT-6 Luna, low", False),
             "sol": ("#eb6834", "D", "GPT-6.1 Sol, high", True)}
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.6), facecolor=surf)
    for ax, p in zip(axes.flat, s["packs"].values(), strict=True):
        ax.set_facecolor(surf)
        ax.set_xscale("log")
        ax.set_xlim(1.5e-5, 5e-2)
        lows = []
        for name, (col, mk, label, filled) in style.items():
            if name not in p["models"]:
                continue
            m = p["models"][name]
            x, y, (lo, hi) = m["usd_task"], m["score"]["mean"], m["score"]["ci"]
            lows.append(lo)
            ax.errorbar(x, y, yerr=[[y - lo], [hi - y]], color=col, lw=1.5, capsize=0, zorder=2)
            ax.plot(x, y, mk, ms=9, color=col, mfc=col if filled else surf, mec=surf if filled else col,
                    mew=2 if filled else 2, zorder=3, label=label)
            left = name in ("luna-low", "4b-sampled")
            ax.annotate(f"{label}\n{y:.3f} · {usd(x)}", (x, y), xytext=(-9 if left else 9, -4),
                        textcoords="offset points", fontsize=7.5, color=ink, va="center",
                        ha="right" if left else "left")
        ax.set_ylim(max(0.0, min(lows) - 0.06), 1.02)
        ax.set_title(f"{p['title']} ({p['n_tasks']} tasks)", loc="left", fontsize=10, color=ink)
        ax.set_ylabel("mean R" if p["tier"] == "foresight" else "hindsight capture C", fontsize=9, color=muted)
        ax.set_xlabel("cost per task, USD (log)", fontsize=9, color=muted)
        ax.grid(True, which="major", color=grid, lw=0.8)
        ax.tick_params(colors=muted, labelsize=8, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
    fig.suptitle("Score against cost per battery-day: the trained 4B, GPT-6 Luna and GPT-6.1 Sol "
                 "(day-block 95% CIs)", fontsize=11, color=ink, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=surf)


if __name__ == "__main__":
    main()
