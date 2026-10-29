"""Registered run 4's report: re-grades every schedule with gridsim_core, then the verdicts, tables, forecast errors,
planning loss and curves. CIs: a day-block bootstrap (10,000 resamples of days, seed 0, task-weighted).

PYTHONPATH=src python report_blind.py RUNS SOL_DIR OUT   (RUNS holds step0/, pilot-eval/, rl-eval/, sft/, rl-*/)"""

import gzip
import json
import sys
from pathlib import Path

import numpy as np

from gridsim_core.baselines import ridge_features
from gridsim_core.grade import grade
from gridsim_core.task import load_pack

B, SEED, MARGIN = 10_000, 0, 0.02
ROOT = Path(__file__).resolve().parents[4]
PACKS = {"eval2025": "ercot-dam-v1-eval", "fresh": "ercot-dam-v1-fresh-2026-10-blind"}
SOL = {"eval2025": "sol-ercot-dam-v1-eval.jsonl", "fresh": "sol-ercot-dam-v1-fresh-2026-10-blind.jsonl"}
LIVE = "2026-10-27"


def tasks_of(pack: str) -> list[dict]:
    return [t for t in load_pack(PACKS[pack]) if t["tags"].get("blind_eval")]


def model_rows(tasks: list[dict], recs: dict) -> dict:
    """Per task: C (0 for no valid schedule), R, validity, kind, forecast and the plan diagnostics, re-graded."""
    out = {k: [] for k in ("c", "r", "valid", "kind", "forecast", "c_f", "c_dp_own", "is_dp_own")}
    for t in tasks:
        r = recs.get(t["task_id"]) or {}
        acts = r.get("actions")
        g = grade(t, acts, "blind") if acts is not None else None
        if g and abs(g["r_opt"] - r.get("c", g["r_opt"])) > 1e-6:
            raise ValueError(f"regrade mismatch on {t['task_id']}")
        out["c"].append(g["r_opt"] if g else 0.0)
        out["r"].append(g["reward"] if g else 0.0)
        out["valid"].append(bool(g))
        out["kind"].append(r.get("kind", "error"))
        out["forecast"].append(r.get("forecast"))
        for k in ("c_f", "c_dp_own", "is_dp_own"):
            out[k].append(r.get(k))
    out["c"], out["r"] = np.array(out["c"]), np.array(out["r"])
    return out


def boot_idx(days: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    u, inv = np.unique(days, return_inverse=True)
    return inv, np.random.default_rng(SEED).integers(0, len(u), (B, len(u)))


def boot(x, days) -> dict:
    """Task-weighted mean and day-block 95% CI."""
    x = np.asarray(x, float)
    inv, idx = boot_idx(days)
    s, c = np.bincount(inv, x), np.bincount(inv)
    m = s[idx].sum(1) / c[idx].sum(1)
    return {"mean": round(float(x.mean()), 4), "ci": [round(float(v), 4) for v in np.percentile(m, [2.5, 97.5])],
            "n": int(len(x)), "days": int(len(c))}


def paired(a, b, days) -> dict:
    d = np.asarray(a, float) - np.asarray(b, float)
    out = boot(d, days)
    out |= {"ahead": round(float((d > 1e-9).mean()), 4), "level": round(float((abs(d) <= 1e-9).mean()), 4),
            "days_ahead": int(sum(d[days == x].mean() > 0 for x in np.unique(days)))}
    return out


def slope(curve: list[tuple[int, np.ndarray]], days) -> dict:
    """Least-squares slope of mean C against step; the CI applies one day resample to every checkpoint."""
    steps = np.array([s for s, _ in curve], float)
    inv, idx = boot_idx(days)
    cnt = np.bincount(inv)
    means = np.stack([np.bincount(inv, c)[idx].sum(1) / cnt[idx].sum(1) for _, c in curve], 1)
    xs = steps - steps.mean()
    sl = (means - means.mean(1, keepdims=True)) @ xs / (xs @ xs)
    point = float(np.polyfit(steps, [c.mean() for _, c in curve], 1)[0])
    return {"per_100_steps": round(point * 100, 4), "ci": [round(float(v) * 100, 4) for v in
                                                           np.percentile(sl, [2.5, 97.5])],
            "share_above_0": round(float((sl > 0).mean()), 4), "points": len(curve)}


def ridge_coef():
    return np.asarray(json.loads((ROOT / "data" / "ridge-v1.json").read_text())["coef"])


def forecast_errors(tasks: list[dict], fcs: dict, teacher: dict) -> dict:
    """MAE on all hours and on the day's 4 dearest / 4 cheapest realized hours, per unique point-day (a model's
    forecasts on a point-day are averaged over its tasks), with paired day-block CIs of (model - persistence)."""
    coef = ridge_coef()
    keys = sorted({(t["date"], t["settlement_point"]) for t in tasks})
    by = {k: [t for t in tasks if (t["date"], t["settlement_point"]) == k] for k in keys}
    days = np.array([k[0] for k in keys])
    y = np.array([by[k][0]["prices"] for k in keys])
    p7 = [np.array(by[k][0]["blind"]["dam_prev_7d"]) for k in keys]
    base = {"persistence": np.array([p[-1] for p in p7]),
            "ridge_v1": np.array([np.einsum("hf,hf->h", ridge_features(k[0], p[-1], p), coef) for k, p in zip(keys, p7,
                                                                                                         strict=True)]),
            "teacher": np.array([teacher[f"{k[0]}|{k[1]}"] for k in keys])}
    order = np.argsort(y, 1)
    masks = {"all": np.ones_like(y, bool), "dear4": np.zeros_like(y, bool), "cheap4": np.zeros_like(y, bool)}
    np.put_along_axis(masks["dear4"], order[:, -4:], True, 1)
    np.put_along_axis(masks["cheap4"], order[:, :4], True, 1)

    def mae(f, rows):
        return {m: np.array([np.abs(f[i] - y[j])[masks[m][j]].mean() for i, j in enumerate(rows)]) for m in masks}

    allrows = np.arange(len(keys))
    ref = {k: mae(v, allrows) for k, v in base.items()}
    out = {"n_point_days": len(keys), "references": {k: {m: round(float(v[m].mean()), 3) for m in masks}
                                                     for k, v in ref.items()}, "models": {}}
    for name, per_task in fcs.items():
        f, rows = [], []
        for j, k in enumerate(keys):
            got = [per_task[t["task_id"]] for t in by[k] if per_task.get(t["task_id"]) is not None]
            if got:
                f.append(np.mean(got, 0))
                rows.append(j)
        if not rows:
            out["models"][name] = {"n_point_days": 0}
            continue
        e, rows = mae(np.array(f), rows), np.array(rows)
        out["models"][name] = {"n_point_days": len(rows), "share_tasks_with_forecast": round(
            sum(v is not None for v in per_task.values()) / max(1, len(per_task)), 4),
            **{m: round(float(e[m].mean()), 3) for m in masks},
            "minus_persistence_all": boot(e["all"] - ref["persistence"]["all"][rows], days[rows]),
            "minus_teacher_all": boot(e["all"] - ref["teacher"]["all"][rows], days[rows]),
            "minus_ridge_all": boot(e["all"] - ref["ridge_v1"]["all"][rows], days[rows])}
    return out


def load_eval(path: Path) -> dict:
    """{(pack, decoding): {task_id: per-task record}} from an evaluate_blind.py file."""
    if not path.exists():
        return {}
    res = json.loads(path.read_text())
    return {(r["pack"], r["decoding"]): {x["task_id"]: x for x in r["per_task"]} for r in res["runs"]}


def load_sol(sol_dir: Path, pack: str) -> dict | None:
    f = sol_dir / SOL[pack]
    if not f.exists():
        return None
    return {r["task_id"]: r for r in map(json.loads, f.read_text().splitlines())}


def teacher_c(tasks: list[dict], teacher: dict) -> np.ndarray:
    from gridsim_core.dp import dp_schedule
    from gridsim_core.task import battery_of

    return np.array([grade(t, dp_schedule(battery_of(t), teacher[f"{t['date']}|{t['settlement_point']}"]),
                           "blind")["r_opt"] for t in tasks])


def main():
    runs, sol_dir, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    with gzip.open(ROOT / "results" / "train" / "4b-blind" / "data" / "teacher.json.gz", "rt") as f:
        teacher = json.load(f)["eval"]
    evals = {"base": load_eval(runs / "step0" / "eval_base.json"), "run3": load_eval(runs / "step0" / "eval_run3.json"),
             "sft": load_eval(runs / "rl-eval" / "eval_rl-0000.json"),
             "final": load_eval(runs / "rl-eval" / "eval_final.json")}
    ckpts = sorted((runs / "rl-eval").glob("eval_ckpt-*.json"))
    summ = {"metric": "C = r_opt (hindsight capture), invalid = 0",
            "bootstrap": {"resamples": B, "seed": SEED, "unit": "day (block), task-weighted"}, "packs": {}}
    for pack in PACKS:
        tasks = tasks_of(pack)
        days = np.array([t["date"] for t in tasks])
        models = {}
        for name, ev in evals.items():
            for dec in ("sampled", "greedy"):
                if (pack, dec) in ev:
                    models[f"{name}-{dec}"] = model_rows(tasks, ev[(pack, dec)])
        sol = load_sol(sol_dir, pack)
        if sol and len(sol) == len(tasks):
            models["sol"] = model_rows(tasks, sol)
        if "final-sampled" in models and all(x is not None for x in models["final-sampled"]["c_dp_own"]):
            models["final-dp-own"] = {"c": np.array(models["final-sampled"]["c_dp_own"], float)}
        models["teacher"] = {"c": teacher_c(tasks, teacher)}
        models["anchor"] = {"c": np.array([t["refs"]["blind"]["r_opt_anchor"] for t in tasks])}
        pk = {"n_tasks": len(tasks), "n_days": len(set(days)), "models": {}, "paired": {}}
        for name, m in models.items():
            row = {"c": boot(m["c"], days)}
            if "valid" in m:
                row |= {"valid": round(float(np.mean(m["valid"])), 4),
                        "kinds": {k: round(m["kind"].count(k) / len(tasks), 4) for k in sorted(set(m["kind"]))},
                        "forecast_rate": round(float(np.mean([f is not None for f in m["forecast"]])), 4)}
                pl = [(c, d, cf, dp) for c, d, cf, dp in zip(m["c"], m["c_dp_own"], m["c_f"], m["is_dp_own"],
                                                             strict=True) if d is not None]
                if pl:
                    ok = np.array([d is not None for d in m["c_dp_own"]])
                    row["planning"] = {"n": len(pl), "c_f_mean": round(float(np.mean([p[2] for p in pl])), 4),
                                       "share_dp_plan_on_own_forecast": round(float(np.mean([p[3] for p in pl])), 4),
                                       "c_dp_own_mean": round(float(np.mean([p[1] for p in pl])), 4),
                                       "own_minus_dp_own": boot(np.array([p[0] - p[1] for p in pl]), days[ok])}
            if pack == "fresh":
                live = days == LIVE
                row["c_2026_10_27"] = round(float(m["c"][live].mean()), 4)
                row["per_day"] = {d: round(float(m["c"][days == d].mean()), 4) for d in sorted(set(days))}
            pk["models"][name] = row
        for a, b in (("final-sampled", "sol"), ("final-greedy", "sol"), ("sft-sampled", "sol"),
                     ("final-sampled", "base-sampled"), ("final-sampled", "run3-sampled"),
                     ("final-greedy", "base-greedy"), ("final-greedy", "run3-greedy"),
                     ("final-sampled", "sft-sampled"), ("final-sampled", "teacher"), ("final-sampled", "anchor"),
                     ("sft-sampled", "teacher"), ("sol", "teacher"), ("sol", "anchor"),
                     ("run3-sampled", "base-sampled"), ("final-dp-own", "sol"), ("final-dp-own", "teacher")):
            if a in models and b in models:
                pk["paired"][f"{a} - {b}"] = paired(models[a]["c"], models[b]["c"], days)
        fcs = {k: {t["task_id"]: f for t, f in zip(tasks, m["forecast"], strict=True)} for k, m in models.items()
               if "forecast" in m}
        pk["forecast_err"] = forecast_errors(tasks, fcs, teacher)
        summ["packs"][pack] = pk
        if pack == "eval2025":
            curve = [(0, models["sft-sampled"]["c"])] if "sft-sampled" in models else []
            for f in ckpts:
                ev = load_eval(f)
                st = json.loads(f.read_text())["runs"][0]["checkpoint_step"]
                curve.append((st, model_rows(tasks, ev[(pack, "sampled")])["c"]))
            if "final-sampled" in models:
                st = json.loads((runs / "rl-eval" / "eval_final.json").read_text())["runs"][0]["checkpoint_step"]
                curve.append((st, models["final-sampled"]["c"]))
            curve.sort(key=lambda x: x[0])
            summ["curve"] = [{"step": s, "c": boot(c, days)} for s, c in curve]
            if len(curve) >= 2:
                summ["slope"] = slope(curve, days)
    summ["verdicts"] = verdicts(summ)
    (out / "summary.json").write_text(json.dumps(summ, indent=1) + "\n")
    log = runs / "rl-main" / "train" / "train_log.jsonl"
    chart(summ, [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else [], out / "curves.png")
    print(json.dumps(summ["verdicts"], indent=1))


def chart(s: dict, log: list[dict], path: Path):
    """Held-out C on blind eval-2025 against RL step with Sol, the teacher pipeline and the anchor as reference lines;
    the train rollouts' capture on their own forecast and on the realized day below (same unit, one axis each)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    blue, orange, aqua = "#2a78d6", "#eb6834", "#1baf7a"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": muted, "axes.labelcolor": ink, "xtick.color": muted,
                         "ytick.color": muted, "axes.spines.top": False, "axes.spines.right": False})
    fig, (a, b) = plt.subplots(2, 1, figsize=(9, 8), height_ratios=[3, 2], facecolor="#fcfcfb")
    for ax in (a, b):
        ax.set_facecolor("#fcfcfb")
        ax.grid(axis="y", color=grid, lw=0.8)
    m = s["packs"]["eval2025"]["models"]
    if s.get("curve"):
        st = [c["step"] for c in s["curve"]]
        mu = [c["c"]["mean"] for c in s["curve"]]
        lo, hi = [c["c"]["ci"][0] for c in s["curve"]], [c["c"]["ci"][1] for c in s["curve"]]
        a.fill_between(st, lo, hi, color=blue, alpha=0.12, lw=0)
        a.plot(st, mu, color=blue, lw=2, marker="o", ms=5, mec="#fcfcfb", mew=1.5, label="Qwen3-4B, run 4 (sampled)")
        a.annotate(f"{mu[-1]:.3f}", (st[-1], mu[-1]), xytext=(6, -3), textcoords="offset points", color=ink)
        a.annotate(f"SFT {mu[0]:.3f}", (st[0], mu[0]), xytext=(6, -12), textcoords="offset points", color=ink)
        for key, name, col, ls, dy in (("sol", "GPT-6.1 Sol, same prompt", orange, "-", -12),
                                       ("teacher", "teacher forecast + exact DP", aqua, "--", 4),
                                       ("anchor", "blind anchor (oracle pick)", muted, ":", 4)):
            if key in m:
                v = m[key]["c"]["mean"]
                a.axhline(v, color=col, lw=1.5, ls=ls)
                a.annotate(f"{name} {v:.3f}", (st[-1], v), xytext=(-4, dy), textcoords="offset points", ha="right",
                           color=ink, fontsize=9)
        a.axhline(m["sol"]["c"]["mean"] - MARGIN if "sol" in m else np.nan, color=orange, lw=0.8, ls=(0, (1, 3)))
        if "sol" in m:
            a.annotate("non-inferiority margin (Sol - 0.02)", (st[0], m["sol"]["c"]["mean"] - MARGIN),
                       xytext=(4, -11), textcoords="offset points", color=muted, fontsize=8)
    base = [f"{n} {m[k]['c']['mean']:.3f}" for k, n in (("base-sampled", "untrained Qwen3-4B"),
                                                        ("run3-sampled", "run 3 zero-shot")) if k in m]
    a.set_title("Held-out C on blind eval-2025 (300 tasks), day-block 95% CI" + (f"\nstep 0: {', '.join(base)}"
                                                                                if base else ""), loc="left",
                color=ink, fontsize=11)
    a.set_ylabel("hindsight capture C")
    a.set_xlabel("RL step (0 = the forecast-then-plan SFT model)")
    if log:
        x = np.array([r["step"] for r in log])

        def roll(k):
            v = np.array([r.get(k) or 0.0 for r in log], float)
            return np.convolve(v, np.ones(10) / 10, "valid"), x[9:]

        for k, name, col in (("c_f_mean", "capture on its own forecast (c_F)", blue),
                             ("reward_mean", "capture on the realized day (C)", orange)):
            y, xx = roll(k)
            b.plot(xx, y, color=col, lw=2, label=name)
            b.annotate(name, (xx[-1], y[-1]), xytext=(-4, 6), textcoords="offset points", ha="right", color=ink,
                       fontsize=9)
        b.set_title("Train rollouts (T 1.0, 32 days per step), 10-step means", loc="left", color=ink, fontsize=11)
        b.set_xlabel("RL step")
        b.set_ylabel("capture")
    a.legend(frameon=False, loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def verdicts(s: dict) -> dict:
    ev, fr = s["packs"]["eval2025"]["paired"], s["packs"]["fresh"]["paired"]
    out = {}
    g = ev.get("final-sampled - sol")
    if g:
        out["primary"] = {"gap": g, "margin": -MARGIN, "non_inferior": g["ci"][0] > -MARGIN,
                          "superior_bonus": g["ci"][0] > 0}
    for k in ("final-sampled - base-sampled", "final-sampled - run3-sampled"):
        if k in ev:
            out.setdefault("secondary_1", {})[k] = {"gap": ev[k], "met": ev[k]["ci"][0] > 0}
    if "secondary_1" in out:
        out["secondary_1"]["met"] = all(v["met"] for v in out["secondary_1"].values() if isinstance(v, dict))
    g = fr.get("final-sampled - sol")
    out["secondary_2"] = ({"gap": g, "non_inferior": g["ci"][0] > -MARGIN} if g else
                          {"completed": False})
    if "slope" in s:
        n_after = len(s["curve"]) - 1
        out["secondary_3"] = {"slope": s["slope"], "checkpoints_after_0": n_after,
                              "met": s["slope"]["ci"][0] > 0 and n_after >= 5}
    fe = s["packs"]["eval2025"]["forecast_err"]["models"].get("final-sampled")
    if fe and fe.get("n_point_days"):
        out["secondary_4"] = {"minus_persistence_all": fe["minus_persistence_all"],
                              "met": fe["minus_persistence_all"]["ci"][1] < 0}
    return out


if __name__ == "__main__":
    main()
