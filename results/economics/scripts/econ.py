"""What the blind-tier decisions are worth in dollars: every recorded schedule re-graded with gridsim_core and its
profit put per MW of battery power per day, with report_blind.py's own day-block boot / paired for every CI.
A descriptive re-analysis computed after the results; nothing here was pre-registered.

PYTHONPATH=src python results/economics/scripts/econ.py [--beam DIR]
(writes results/economics/summary.json, tables.md and value_ladder.png; Beam's records are read from DIR, by default
results/beam-agent/, and an effort is included once all 331 of its tasks are there)"""

import argparse
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
from gridsim_core import baselines  # noqa: E402
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402

OUT = ROOT / "results" / "economics"
TB = ROOT / "results" / "train" / "4b-blind"
CM = ROOT / "results" / "cost-matched"
G6E = 4.52856
YEAR, FLEET = 365, 100
EFFORTS = ("high", "low", "medium", "max")
TOP = 0.10
SOL = {"eval2025": "sol-ercot-dam-v1-eval", "fresh": "sol-ercot-dam-v1-fresh-2026-10-blind"}
LABELS = {
    "optimum": "hindsight optimum (DP on the day's own prices)",
    "anchor": "blind anchor: max(persistence-DP, ridge-DP) per task, an oracle pick",
    "sol": "GPT-6.1 Sol, effort high",
    "luna-high": "GPT-6 Luna, effort high", "luna-medium": "GPT-6 Luna, effort medium",
    "luna-low": "GPT-6 Luna, effort low",
    **{f"beam-{e}": f"Beam-1.0, effort {e}" for e in EFFORTS},
    "4b-sampled": "trained Qwen3-4B, run 4 final, sampled", "4b-greedy": "trained Qwen3-4B, run 4 final, greedy",
    "sft": "Qwen3-4B SFT start of run 4 (RL step 0), sampled", "base": "untrained Qwen3-4B, sampled",
    "persistence-dp": "persistence-DP: exact DP on yesterday's prices", "ridge-dp": "ridge-DP: exact DP on ridge-v1",
    "greedy-d1": "greedy rule on yesterday's prices", "threshold-d1": "threshold rule on yesterday's prices",
    "greedy-fs": "greedy rule on the day's own prices (sees the day)",
    "threshold-fs": "threshold rule on the day's own prices (sees the day)",
    "idle": "idle (the battery does nothing)",
}
KIND = {"optimum": "reference", "anchor": "reference", "sol": "llm", "luna-high": "llm", "luna-medium": "llm",
        "luna-low": "llm", **{f"beam-{e}": "llm" for e in EFFORTS}, "4b-sampled": "trained", "4b-greedy": "trained",
        "sft": "trained", "base": "trained", "persistence-dp": "baseline", "ridge-dp": "baseline",
        "greedy-d1": "baseline", "threshold-d1": "baseline", "greedy-fs": "foresight baseline",
        "threshold-fs": "foresight baseline", "idle": "baseline"}
GAPS = (("sol", "persistence-dp"), ("sol", "ridge-dp"), ("4b-sampled", "persistence-dp"), ("sol", "4b-sampled"),
        ("luna-high", "persistence-dp"), ("beam-best", "persistence-dp"), ("4b-sampled", "base"))
BY_DAY = ("sol", "luna-high", "4b-sampled", "beam-best")


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RB = load("report_blind", "results/train/4b-blind/scripts/report_blind.py")


def jsonl(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def found(d: Path, stem: str) -> Path | None:
    return next((p for p in (d / f"{stem}.jsonl.gz", d / f"{stem}.jsonl") if p.exists()), None)


def eval_run(file: str, pack: str, decoding: str) -> tuple[dict, float]:
    run = next(r for r in json.loads((TB / file).read_text())["runs"]
               if r["pack"] == pack and r["decoding"] == decoding)
    return {x["task_id"]: x for x in run["per_task"]}, run["wall_s"]


def settle(tasks: list[dict], recs: dict, key: str) -> tuple[np.ndarray, np.ndarray]:
    """Profit per task ($) and validity; a reply with no valid schedule settles as idle. Each grade is checked
    against the C the record carries."""
    p, ok = [], []
    for t in tasks:
        r = recs[t["task_id"]]
        g = grade(t, r["actions"], "blind") if r.get("actions") is not None else None
        if abs((g["r_opt"] if g else 0.0) - (r.get(key) or 0.0)) > 1e-6:
            raise ValueError(f"regrade mismatch on {t['task_id']}")
        p.append(g["profit"] if g else t["refs"]["foresight"]["p_idle"])
        ok.append(g is not None)
    return np.array(p), np.array(ok)


def rule_on(task: dict, rule, prices) -> float:
    return simulate(task, rule(task | {"prices": list(prices)}))["profit_usd"]


def profits(pack: str, tasks: list[dict], beam_dir: Path) -> tuple[dict, dict, dict, dict]:
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())
    prof = {"optimum": [t["refs"]["foresight"]["p_opt"] for t in tasks],
            "anchor": [t["refs"]["blind"]["p_anchor"] for t in tasks],
            "persistence-dp": [simulate(t, baselines.persistence_dp(t))["profit_usd"] for t in tasks],
            "ridge-dp": [simulate(t, baselines.ridge_dp(t, ridge))["profit_usd"] for t in tasks],
            "greedy-d1": [rule_on(t, baselines.greedy, t["blind"]["dam_prev_day"]) for t in tasks],
            "threshold-d1": [rule_on(t, baselines.threshold, t["blind"]["dam_prev_day"]) for t in tasks],
            "greedy-fs": [simulate(t, baselines.greedy(t))["profit_usd"] for t in tasks],
            "threshold-fs": [simulate(t, baselines.threshold(t))["profit_usd"] for t in tasks],
            "idle": [t["refs"]["foresight"]["p_idle"] for t in tasks]}
    prof = {k: np.array(v, float) for k, v in prof.items()}
    for k in ("persistence-dp", "ridge-dp"):
        ref = np.array([t["refs"]["blind"]["p_persist" if k == "persistence-dp" else "p_ridge"] for t in tasks])
        if np.abs(prof[k] - ref).max() > 1e-4:
            raise ValueError(f"{k} does not match the pack's refs")
    valid, cost, status = {}, {}, {}
    n = len(tasks)
    recs = {"sol": {r["task_id"]: r for r in jsonl(TB / "sol" / f"{SOL[pack]}.jsonl.gz")}}
    for e in ("high", "medium", "low"):
        f = found(CM / "luna", f"luna-blind-{pack}-{e}")
        if f:
            recs[f"luna-{e}"] = {r["task_id"]: r for r in jsonl(f)}
    if pack == "fresh":
        for e in EFFORTS:
            f = found(beam_dir, f"beam-blind-fresh-{e}")
            got = {r["task_id"]: r for r in jsonl(f)} if f else {}
            if len(got) < n or any(t["task_id"] not in got for t in tasks):
                status[e] = f"incomplete ({len(got)} of {n})" if got else "not run"
                continue
            status[e] = "included"
            recs[f"beam-{e}"] = got
    for name, r in recs.items():
        prof[name], valid[name] = settle(tasks, r, "c")
        cost[name] = float(np.mean([r[t["task_id"]]["usd"] for t in tasks]))
    for name, file, dec in (("4b-sampled", "eval_final.json", "sampled"), ("4b-greedy", "eval_final.json", "greedy"),
                            ("sft", "eval_rl-0000.json", "sampled"), ("base", "eval_step0_base.json", "sampled")):
        r, wall = eval_run(file, pack, dec)
        prof[name], valid[name] = settle(tasks, r, "c")
        cost[name] = wall * G6E / 3600 / n
    beams = [k for k in prof if k.startswith("beam-")]
    if beams:
        best = max(beams, key=lambda k: prof[k].mean())
        prof["beam-best"], valid["beam-best"], cost["beam-best"] = prof[best], valid[best], cost[best]
        status["best"] = best.removeprefix("beam-")
    return prof, valid, cost, status


def money(b: dict) -> dict:
    """A $/MW-day boot result with its $k/MW-yr and $k per 100 MW-yr equivalents."""
    k = {"k_usd_per_mw_yr": YEAR / 1000, "k_usd_per_100mw_yr": YEAR * FLEET / 1000}
    return {"usd_per_mw_day": b, **{n: {"mean": round(b["mean"] * f, 3), "ci": [round(v * f, 3) for v in b["ci"]]}
                                    for n, f in k.items()}}


def shape_change(tasks: list[dict]) -> np.ndarray:
    """1 - Pearson r of the day's hourly prices with the day before's, per task: 0 when the shape repeats."""
    out = []
    for t in tasks:
        a, b = np.asarray(t["prices"], float), np.asarray(t["blind"]["dam_prev_day"], float)
        out.append(1.0 - float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 1.0)
    return np.array(out)


def concentration(x: dict, days: np.ndarray, tasks: list[dict]) -> dict:
    """Per day, the mean over its battery-days (the average battery's day): the hindsight optimum's share in the top
    10% of days, the days each model gains or loses against persistence-DP, and how that tracks the day's price-shape
    change (quartiles on eval-2025, each day on fresh)."""
    u = np.unique(days)
    k = max(1, round(TOP * len(u)))
    day = {m: np.array([v[days == d].mean() for d in u]) for m, v in x.items()}
    opt = day["optimum"]
    out = {"unit": "day means of $/MW-day over each day's battery-days", "top_days": k, "n_days": int(len(u)),
           "optimum_share_in_top_days": round(float(np.sort(opt)[::-1][:k].sum() / opt.sum()), 4),
           "top_days_by_optimum": [{"date": str(u[i]), "optimum": round(float(opt[i]), 2)}
                                   for i in np.argsort(opt)[::-1][:min(k, 5)]],
           "shape_change": "1 - Pearson r of day D's 24 hourly prices with D-1's, mean over the day's battery-days"}
    sc = shape_change(tasks)
    day_sc = np.array([sc[days == d].mean() for d in u])
    gap = {m: day[m] - day["persistence-dp"] for m in BY_DAY if m in day}
    out["vs_persistence"] = {}
    for m, g in gap.items():
        o = np.argsort(g)
        top = np.sort(g)[::-1][:k].sum()
        out["vs_persistence"][m] = {
            "days_ahead": int((g > 1e-9).sum()), "days_level": int((abs(g) <= 1e-9).sum()),
            "days_behind": int((g < -1e-9).sum()),
            "net_gain_share_from_top_days": round(float(top / g.sum()), 3) if g.sum() > 0 else None,
            "best_days": [{"date": str(u[i]), "gap": round(float(g[i]), 2), "shape_change": round(float(day_sc[i]), 3),
                           "optimum": round(float(opt[i]), 2)} for i in o[::-1][:3]],
            "worst_days": [{"date": str(u[i]), "gap": round(float(g[i]), 2), "shape_change": round(float(day_sc[i]), 3),
                            "optimum": round(float(opt[i]), 2)} for i in o[:3]]}
    if len(u) >= 40:
        q = np.searchsorted(np.quantile(day_sc, [0.25, 0.5, 0.75]), day_sc, side="right")
        tq = q[np.searchsorted(u, days)]
        out["by_shape_change_quartile"] = []
        for i in range(4):
            sel = tq == i
            row = {"quartile": i + 1, "n_days": int((q == i).sum()), "n_tasks": int(sel.sum()),
                   "shape_change": [round(float(day_sc[q == i].min()), 3), round(float(day_sc[q == i].max()), 3)],
                   "optimum": RB.boot(x["optimum"][sel], days[sel]),
                   "persistence_shortfall": RB.boot((x["optimum"] - x["persistence-dp"])[sel], days[sel])}
            for m in gap:
                row[f"{m} - persistence-dp"] = RB.paired(x[m][sel], x["persistence-dp"][sel], days[sel])
            out["by_shape_change_quartile"].append(row)
    else:
        out["by_day"] = [{"date": str(d), "n_tasks": int((days == d).sum()), "shape_change": round(float(day_sc[i]), 3),
                          "optimum": round(float(opt[i]), 2),
                          "persistence-dp": round(float(day["persistence-dp"][i]), 2),
                          **{f"{m} - persistence-dp": round(float(g[i]), 2) for m, g in gap.items()}}
                         for i, d in enumerate(u)]
    return out


def pack_summary(pack: str, beam_dir: Path) -> dict:
    tasks = RB.tasks_of(pack)
    days = np.array([t["date"] for t in tasks])
    mw = np.array([t["battery"]["p_dis_mw"] for t in tasks], float)
    prof, valid, cost, status = profits(pack, tasks, beam_dir)
    x = {k: v / mw for k, v in prof.items()}
    rows = {}
    for k, v in x.items():
        if k == "beam-best":
            continue
        rows[k] = {"label": LABELS[k], "kind": KIND[k], **money(RB.boot(v, days))}
        if k in valid:
            rows[k] |= {"valid": round(float(valid[k].mean()), 4),
                        "usd_per_mw_day_invalid_as_0": round(float(np.where(valid[k], v, 0.0).mean()), 4)}
        if k in cost:
            rows[k]["usd_inference_per_battery_day"] = round(cost[k], 6)
    gaps, zero = {}, {}
    for a, b in GAPS:
        if a in x and b in x:
            g = RB.paired(x[a], x[b], days)
            name = f"{a} - {b}" if a != "beam-best" else f"beam-{status['best']} (best effort) - {b}"
            gaps[name] = money(g) | {k: g[k] for k in ("ahead", "level", "days_ahead")} | {
                "label": f"{SHORT[a] if a != 'beam-best' else SHORT['beam-' + status['best']] + ' (best effort)'} − "
                         f"{SHORT[b]}"}
            z = [np.where(valid[m], x[m], 0.0) if m in valid else x[m] for m in (a, b)]
            if any((~valid[m]).any() for m in (a, b) if m in valid):
                zg = RB.boot(z[0] - z[1], days)
                zero[name] = {"mean": zg["mean"], "ci": zg["ci"]}
    room = x["optimum"].mean() - x["persistence-dp"].mean()
    closed = {m: round(float((x[m].mean() - x["persistence-dp"].mean()) / room), 4) for m in BY_DAY if m in x}
    return {"pack": RB.PACKS[pack], "n_tasks": len(tasks), "n_days": int(len(np.unique(days))),
            "dates": [str(min(days)), str(max(days))], "mw": {"mean": round(float(mw.mean()), 1),
                                                                 "min": float(mw.min()), "max": float(mw.max())},
            "battery_hours": {h: int(sum(t["battery"]["archetype"].startswith(h) for t in tasks))
                              for h in ("1h", "2h", "4h")},
            "c_deg_usd_per_mwh": {str(c): int(sum(t["battery"]["c_deg"] == c for t in tasks))
                                  for c in sorted({t["battery"]["c_deg"] for t in tasks})},
            "rows": rows, "gaps": gaps, "gaps_invalid_as_0": zero, "beam": status or None,
            "share_of_persistence_to_optimum_gap_closed": closed,
            "concentration": concentration(x, days, tasks)}


def inference(s: dict) -> dict:
    """Cost per battery-day against the decision value per battery-day of a 100 MW battery, per pack."""
    out = {"note": "one model call per battery-day whatever the battery's size, so the cost does not scale with MW; "
                   "the value does",
           "prices": "Sol and Luna at the cost-matched contest's token prices, Beam at Baseten's on the HF router, "
                     "the 4Bs as busy L40S time (g6e.8xlarge on demand, wall time of the batched eval only)",
           "packs": {}}
    for pack, p in s["packs"].items():
        rows = p["rows"]
        llm = {k: r for k, r in rows.items() if "usd_inference_per_battery_day" in r}
        per = {}
        for k, r in llm.items():
            c, v = r["usd_inference_per_battery_day"], r["usd_per_mw_day"]["mean"]
            per[k] = {"usd_per_battery_day": c, "usd_per_battery_yr": round(c * YEAR, 2),
                      "earned_per_battery_day_100mw": round(v * FLEET, 0),
                      "over_persistence_per_day_100mw": round((v - rows["persistence-dp"]["usd_per_mw_day"]["mean"])
                                                              * FLEET, 0)}
        sol, fb = rows["sol"], rows["4b-sampled"]
        gap = p["gaps"]["sol - 4b-sampled"]["usd_per_mw_day"]["mean"]
        extra = sol["usd_inference_per_battery_day"] - fb["usd_inference_per_battery_day"]
        sp = p["gaps"]["sol - persistence-dp"]["usd_per_mw_day"]["mean"]
        out["packs"][pack] = {"models": per, "sol_over_4b": {
            "extra_inference_usd_per_battery_yr": round(extra * YEAR, 2),
            "decision_gap_k_usd_per_100mw_yr": round(gap * YEAR * FLEET / 1000, 1),
            "ratio": round(gap * YEAR * FLEET / (extra * YEAR)), "break_even_mw": round(extra / gap, 5)},
            "sol_over_persistence": {"inference_usd_per_battery_yr": round(sol["usd_inference_per_battery_day"] * YEAR,
                                                                           2),
                                     "decision_gap_k_usd_per_100mw_yr": round(sp * YEAR * FLEET / 1000, 1),
                                     "ratio": round(sp * FLEET / sol["usd_inference_per_battery_day"]),
                                     "break_even_mw": round(sol["usd_inference_per_battery_day"] / sp, 5)}}
    return out


CHART = ("anchor", "sol", "beam-high", "beam-medium", "beam-low", "beam-max", "luna-high", "luna-medium",
         "persistence-dp", "4b-sampled", "sft", "ridge-dp", "greedy-d1", "threshold-d1", "luna-low", "idle", "base")
SHORT = {"anchor": "blind anchor (oracle pick)", "sol": "GPT-6.1 Sol", "luna-high": "GPT-6 Luna, high",
         "luna-medium": "GPT-6 Luna, medium", "luna-low": "GPT-6 Luna, low",
         **{f"beam-{e}": f"Beam-1.0, {e}" for e in EFFORTS}, "4b-sampled": "trained Qwen3-4B (run 4)",
         "4b-greedy": "trained Qwen3-4B (run 4), greedy", "beam-best": "Beam-1.0 (best effort)",
         "sft": "Qwen3-4B, SFT only", "base": "untrained Qwen3-4B", "persistence-dp": "persistence-DP",
         "ridge-dp": "ridge-DP", "greedy-d1": "greedy rule, yesterday's prices",
         "threshold-d1": "threshold rule, yesterday's prices", "idle": "idle"}


def colour(k: str) -> tuple[str, float]:
    if k == "sol":
        return "#eb6834", 1.0
    if k.startswith("luna"):
        return "#1baf7a", {"luna-high": 1.0, "luna-medium": 0.7, "luna-low": 0.45}[k]
    if k.startswith("beam"):
        return "#6250d6", 1.0
    if k in ("4b-sampled", "sft", "base"):
        return "#2a78d6", {"4b-sampled": 1.0, "sft": 0.6, "base": 0.35}[k]
    if k == "persistence-dp":
        return "#52514e", 1.0
    return "#a9a7a1", 1.0


def chart(s: dict, path: Path):
    ink, muted, grid, surf = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    packs = [("eval2025", "Blind eval-2025: 300 battery-days on 191 days of 2025"),
             ("fresh", "Blind fresh: 331 battery-days on 10 days, 18-27 Oct 2026 (wide CIs)")]
    n = [sum(k in s["packs"][p]["rows"] for k in CHART) for p, _ in packs]
    fig, axes = plt.subplots(2, 1, figsize=(11, 0.34 * sum(n) + 2.6), height_ratios=n, facecolor=surf)
    rows_all = [s["packs"][p]["rows"] for p, _ in packs]
    lo = min(r[k]["k_usd_per_mw_yr"]["ci"][0] for r in rows_all for k in CHART if k in r)
    hi = max(r["optimum"]["k_usd_per_mw_yr"]["mean"] for r in rows_all)
    for ax, (p, title) in zip(axes, packs, strict=True):
        rows = s["packs"][p]["rows"]
        keys = sorted([k for k in CHART if k in rows], key=lambda k: -rows[k]["k_usd_per_mw_yr"]["mean"])
        ax.set_facecolor(surf)
        for i, k in enumerate(keys):
            r = rows[k]["k_usd_per_mw_yr"]
            col, a = colour(k)
            if k == "anchor":
                ax.barh(i, r["mean"], height=0.62, color=surf, edgecolor=muted, hatch="////", lw=0.8, zorder=2)
            else:
                ax.barh(i, r["mean"], height=0.62, color=col, alpha=a, lw=0, zorder=2)
            ax.plot(r["ci"], [i, i], color=ink, lw=1.0, zorder=3, solid_capstyle="butt")
            ax.annotate(f"{r['mean']:.1f}  [{r['ci'][0]:.1f}, {r['ci'][1]:.1f}]".replace("-", "\u2212"), (1.01, i),
                        xycoords=("axes fraction", "data"), va="center", ha="left", fontsize=8.5, color=ink)
        opt = rows["optimum"]["k_usd_per_mw_yr"]["mean"]
        ax.axvline(opt, color=ink, lw=1.0, ls=(0, (4, 3)), zorder=1)
        ax.annotate(f"hindsight optimum {opt:.1f}", (opt, -1.0), ha="right", va="center", fontsize=8.5, color=ink,
                    xytext=(-4, 0), textcoords="offset points")
        ax.annotate("\\$k/MW-yr  [95% CI]", (1.01, -1.0), xycoords=("axes fraction", "data"),
                    va="center", ha="left", fontsize=8.5, color=muted)
        ax.axvline(0, color=muted, lw=0.8, zorder=1)
        ax.set_yticks(range(len(keys)), [SHORT[k] for k in keys], fontsize=9, color=ink)
        ax.set_ylim(len(keys) - 0.4, -1.5)
        ax.set_xlim(lo - 1, hi + 1.5)
        ax.grid(axis="x", color=grid, lw=0.8, zorder=0)
        ax.tick_params(axis="x", colors=muted, labelsize=8, length=0)
        ax.tick_params(axis="y", length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(title, loc="left", fontsize=10, color=ink)
    axes[-1].set_xlabel("day-ahead energy arbitrage profit, \\$k per MW of battery power per year "
                        "(battery-day mean × 365)", fontsize=9, color=muted)
    fig.suptitle("What the blind day-ahead decisions are worth, every recorded schedule settled at ERCOT's prices",
                 fontsize=11, color=ink, x=0.01, ha="left")
    sol = s["packs"]["eval2025"]["rows"]["sol"]["k_usd_per_mw_yr"]["mean"]
    fig.text(0.01, 1 - 0.5 / fig.get_figheight(),
             f"For a 100 MW battery multiply by 100: Sol's {sol:.1f} is about \\${sol / 10:.1f}M a year. Greys: idle, "
             "and rules and exact DPs on yesterday's prices.\nDay-ahead energy arbitrage only: no real-time market, no "
             "ancillary services. Day-block 95% CIs.",
             fontsize=8.5, color=muted, ha="left", va="top")
    fig.tight_layout(rect=(0, 0, 0.87, 1 - 0.72 / fig.get_figheight()))
    fig.savefig(path, dpi=150, facecolor=surf)


ORDER = ("optimum", "anchor", "sol", *(f"beam-{e}" for e in EFFORTS), "luna-high", "luna-medium", "luna-low",
         "4b-sampled", "4b-greedy", "sft", "base", "persistence-dp", "ridge-dp", "greedy-d1", "threshold-d1",
         "greedy-fs", "threshold-fs", "idle")


def combined(s: dict) -> str:
    """Both packs side by side: $/MW-day with its CI, $k/MW-yr and the cost per battery-day."""
    ev, fr = s["packs"]["eval2025"]["rows"], s["packs"]["fresh"]["rows"]

    def cell(r):
        if r is None:
            return "– | – "
        d, y = r["usd_per_mw_day"], r["k_usd_per_mw_yr"]
        return f"{num(d['mean'])} [{num(d['ci'][0])}, {num(d['ci'][1])}] | {num(y['mean'])} "

    out = ["| row | eval-2025 $/MW-day [95% CI] | $k/MW-yr | fresh $/MW-day [95% CI] | $k/MW-yr | "
           "inference $ per battery-day |", "|---|---|---:|---|---:|---:|"]
    for k in ORDER:
        if k not in ev and k not in fr:
            continue
        r = ev.get(k) or fr[k]
        c = r.get("usd_inference_per_battery_day")
        out.append(f"| {r['label']} | {cell(ev.get(k))}| {cell(fr.get(k))}| {'–' if c is None else f'${c:.5f}'} |")
    out += ["", "| paired gap | eval-2025 $/MW-day [95% CI] | $k/MW-yr [95% CI] | fresh $/MW-day [95% CI] | "
            "$k/MW-yr [95% CI] |", "|---|---|---|---|---|"]
    eg, fg = s["packs"]["eval2025"]["gaps"], s["packs"]["fresh"]["gaps"]

    def gcell(v):
        if v is None:
            return "– | – "
        d, y = v["usd_per_mw_day"], v["k_usd_per_mw_yr"]
        return (f"{sg(d['mean'])} [{sg(d['ci'][0])}, {sg(d['ci'][1])}] | {sg(y['mean'])} "
                f"[{sg(y['ci'][0])}, {sg(y['ci'][1])}] ")

    for k in dict.fromkeys([*eg, *fg]):
        v = eg.get(k) or fg[k]
        out.append(f"| {v['label']} | {gcell(eg.get(k))}| {gcell(fg.get(k))}|")
    return "\n".join(out) + "\n"


def tables(s: dict) -> str:
    out = ["### Both packs\n", combined(s)]
    for p in s["packs"].values():
        out.append(f"### {p['pack']}: {p['n_tasks']} battery-days on {p['n_days']} days, {p['dates'][0]} to "
                   f"{p['dates'][1]}\n")
        out.append("| row | $/MW-day | 95% CI | $k/MW-yr | per 100 MW-yr | valid | inference $ per battery-day |")
        out.append("|---|---:|---|---:|---:|---:|---:|")
        for r in sorted(p["rows"].values(), key=lambda r: -r["usd_per_mw_day"]["mean"]):
            d, y, h = r["usd_per_mw_day"], r["k_usd_per_mw_yr"], r["k_usd_per_100mw_yr"]
            c, ok = r.get("usd_inference_per_battery_day"), r.get("valid")
            out.append(f"| {r['label']} | {num(d['mean'])} | [{num(d['ci'][0])}, {num(d['ci'][1])}] | "
                       f"{num(y['mean'])} | {usd_m(h['mean'])} | {'–' if ok is None else f'{ok:.1%}'} | "
                       f"{'–' if c is None else f'${c:.5f}'} |")
        if p.get("beam"):
            out.append("\nBeam-1.0 efforts: " + ", ".join(f"{e} {v}" for e, v in p["beam"].items() if e != "best")
                       + ".")
        out.append("\n| paired gap | $/MW-day [95% CI] | $k/MW-yr [95% CI] | per 100 MW-yr | ahead / level | "
                   "days ahead |")
        out.append("|---|---|---|---:|---|---:|")
        for v in p["gaps"].values():
            d, y, h = v["usd_per_mw_day"], v["k_usd_per_mw_yr"], v["k_usd_per_100mw_yr"]
            out.append(f"| {v['label']} | {sg(d['mean'])} [{sg(d['ci'][0])}, {sg(d['ci'][1])}] | {sg(y['mean'])} "
                       f"[{sg(y['ci'][0])}, {sg(y['ci'][1])}] | {sg(h['mean'], 0)}k | {v['ahead']:.0%} / "
                       f"{v['level']:.0%} | {v['days_ahead']}/{p['n_days']} |")
        out.append("")
    out.append("### Inference cost against decision value, per battery-day\n")
    out.append("| pack | model | inference $ per battery-day | per battery-year | earned per day, 100 MW | "
               "vs persistence-DP per day, 100 MW |")
    out.append("|---|---|---:|---:|---:|---:|")
    for pack, p in s["inference"]["packs"].items():
        for k, m in p["models"].items():
            out.append(f"| {pack} | {SHORT[k]} | ${m['usd_per_battery_day']:.5f} | ${m['usd_per_battery_yr']:.2f} | "
                       f"{usd0(m['earned_per_battery_day_100mw'])} | "
                       f"{usd0(m['over_persistence_per_day_100mw'], True)} |")
    out.append("")
    for p in s["packs"].values():
        c = p["concentration"]
        out.append(f"### {p['pack']}: by day\n")
        out.append(f"Hindsight optimum in the top {c['top_days']} of {c['n_days']} days: "
                   f"{c['optimum_share_in_top_days']:.1%} (day means of $/MW-day).\n")
        if "by_shape_change_quartile" in c:
            ms = [m for m in BY_DAY if f"{m} - persistence-dp" in c["by_shape_change_quartile"][0]]
            out.append("| price-shape change quartile | days | 1 − r range | optimum $/MW-day | "
                       "persistence-DP short of optimum | "
                       + " | ".join(f"{SHORT[m]} − persistence-DP" for m in ms) + " |")
            out.append("|---|---:|---|---:|---|" + "---|" * len(ms))
            for q in c["by_shape_change_quartile"]:
                ps = q["persistence_shortfall"]
                lo, hi = q["shape_change"]
                out.append(f"| Q{q['quartile']} | {q['n_days']} | {lo:.3f}–{hi:.3f} | {num(q['optimum']['mean'])} | "
                           f"{num(ps['mean'])} [{num(ps['ci'][0])}, {num(ps['ci'][1])}] | "
                           + " | ".join(f"{sg(g['mean'])} [{sg(g['ci'][0])}, {sg(g['ci'][1])}]" for g in
                                        (q[f"{m} - persistence-dp"] for m in ms)) + " |")
        else:
            ms = [m for m in BY_DAY if f"{m} - persistence-dp" in c["by_day"][0]]
            out.append("| day | battery-days | 1 − r | optimum | persistence-DP | " +
                       " | ".join(f"{SHORT[m]} − persistence-DP" for m in ms)
                       + " |")
            out.append("|---|---:|---:|---:|---:|" + "---:|" * len(ms))
            for d in c["by_day"]:
                out.append(f"| {d['date']} | {d['n_tasks']} | {d['shape_change']:.3f} | {num(d['optimum'])} | "
                           f"{num(d['persistence-dp'])} | " + " | ".join(sg(d[f"{m} - persistence-dp"]) for m in ms)
                           + " |")
        out.append("")
    return "\n".join(out) + "\n"


def num(v: float, nd: int = 1) -> str:
    return f"{round(v, nd) + 0.0:,.{nd}f}".replace("-", "−")


def usd_m(k: float) -> str:
    return f"{'−' if k < 0 else ''}${abs(k) / 1000:.2f}M"


def usd0(v: float, sign: bool = False) -> str:
    return f"{'−' if v < 0 else '+' if sign else ''}${abs(v):,.0f}"


def sg(v: float, nd: int = 1) -> str:
    return f"{round(v, nd) + 0.0:+,.{nd}f}".replace("-", "−")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--beam", type=Path, default=ROOT / "results" / "beam-agent")
    a = ap.parse_args()
    s = {"what": "profit per MW of battery discharge power per battery-day ($/MW-day): each task's settled profit "
                 "divided by its p_dis_mw, the task-weighted mean over the pack; x 365 for $/MW-yr",
         "metric_source": "gridsim_core.grade(task, actions, 'blind')['profit'] on every recorded schedule",
         "invalid": "a reply with no valid schedule settles as idle (the battery does nothing; an end-of-day "
                    "obligation shortfall is charged as for any schedule); usd_per_mw_day_invalid_as_0 counts it $0",
         "bootstrap": "day-block, 10,000 resamples, seed 0, task-weighted (report_blind.boot / paired)",
         "status": "descriptive re-analysis computed after the results; not pre-registered",
         "packs": {p: pack_summary(p, a.beam) for p in ("eval2025", "fresh")}}
    s["inference"] = inference(s)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(s, indent=1) + "\n")
    (OUT / "tables.md").write_text(tables(s))
    chart(s, OUT / "value_ladder.png")
    print(tables(s))


if __name__ == "__main__":
    main()
